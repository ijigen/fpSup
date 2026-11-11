"""Embed LUT settings into a COPY of a classic TIFF/DNG without moving pixels.

Original offsets remain valid, including MakerNote-relative data. Only the root
IFD pointer is changed; a replacement IFD and metadata are appended. This is an
offline reference for the future camera writer, not an on-camera installer.
"""
import base64
from dataclasses import dataclass
import hashlib
import json
from numbers import Real
import struct
import xml.etree.ElementTree as ET
import zlib

import numpy as np

from cube import Cube, MAX_SOURCE_BYTES

XMP = 700
RGB_TABLES = 52543
DNG_VERSION = 50706
LUT_NS = 'https://ijigen.github.io/fpSup/ns/lut/1.0/'
RDF_NS = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
X_NS = 'adobe:ns:meta/'
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2,
             9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
SPACES = {  # DNG gamma enum, primaries enum. Input/output must use the SAME space.
    'srgb': (1, 0), 'linear-709': (0, 0), '709-gamma22': (3, 0),
    'adobe-rgb': (3, 1), 'display-p3': (1, 2), 'linear-2020': (0, 3),
    'prophoto': (2, 4), 'linear-prophoto': (0, 4),
}
ET.register_namespace('x', X_NS)
ET.register_namespace('rdf', RDF_NS)
ET.register_namespace('fpLUT', LUT_NS)


def settings(cube, name, input_space, output_space, strength=1.):
    if not all(isinstance(s, str) and 0 < len(s) <= 256 for s in (name, input_space, output_space)):
        raise ValueError('name and input/output spaces must be declared (1..256 characters)')
    if not isinstance(strength, Real) or not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('strength must be in 0..1')
    return {'schema': 'fpSup-LUT-settings-1', 'name': name,
            'input_space': input_space, 'output_space': output_space,
            'strength': float(strength), 'interpolation': 'tetrahedral',
            'source_sha256': cube.sha256, 'source_bytes': len(cube.source),
            'cube': cube.summary()}


def validate_settings(cube, config):
    if not isinstance(config, dict):
        raise ValueError('LUT settings must be a JSON object')
    try:
        expected = settings(cube, config['name'], config['input_space'],
                            config['output_space'], config['strength'])
    except KeyError as error:
        raise ValueError('incomplete LUT settings') from error
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError('LUT settings or source integrity mismatch')


def xmp_packet(existing, cube, config):
    validate_settings(cube, config)
    if existing:
        if len(existing) > 32 * 1024 * 1024 or b'<!DOCTYPE' in existing.upper():
            raise ValueError('unsupported XMP packet')
        root = ET.fromstring(existing.rstrip(b'\x00'))
        rdf = root if root.tag == f'{{{RDF_NS}}}RDF' else root.find(f'.//{{{RDF_NS}}}RDF')
        if rdf is None:
            raise ValueError('existing XMP has no RDF container')
    else:
        root = ET.Element(f'{{{X_NS}}}xmpmeta')
        rdf = ET.SubElement(root, f'{{{RDF_NS}}}RDF')
    # Replace only our namespace; other EXIF/XMP/vendor metadata remain active.
    for parent in root.iter():
        for key in list(parent.attrib):
            if key.startswith('{' + LUT_NS + '}'):
                del parent.attrib[key]
        for child in list(parent):
            if child.tag.startswith('{' + LUT_NS + '}'):
                parent.remove(child)
    desc = ET.SubElement(rdf, f'{{{RDF_NS}}}Description', {f'{{{RDF_NS}}}about': ''})
    ET.SubElement(desc, f'{{{LUT_NS}}}Settings').text = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
    ET.SubElement(desc, f'{{{LUT_NS}}}CubeZlibBase64').text = base64.b64encode(zlib.compress(cube.source)).decode('ascii')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def extract_xmp(packet):
    if len(packet) > 32 * 1024 * 1024 or b'<!DOCTYPE' in packet.upper():
        raise ValueError('unsupported XMP packet')
    root = ET.fromstring(packet.rstrip(b'\x00'))
    config_node = root.find(f'.//{{{LUT_NS}}}Settings')
    cube_node = root.find(f'.//{{{LUT_NS}}}CubeZlibBase64')
    if config_node is None or cube_node is None:
        raise ValueError('no fpSup LUT embedded')
    if not config_node.text or not cube_node.text:
        raise ValueError('incomplete embedded LUT properties')
    config = json.loads(config_node.text)
    compressed = base64.b64decode(cube_node.text, validate=True)
    decoder = zlib.decompressobj()
    source = decoder.decompress(compressed, MAX_SOURCE_BYTES + 1)
    if len(source) > MAX_SOURCE_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError('invalid or oversized embedded .cube')
    cube = Cube.parse(source)
    validate_settings(cube, config)
    return cube, config


@dataclass(frozen=True)
class Entry:
    tag: int
    kind: int
    count: int
    raw: bytes  # Exact 12-byte TIFF entry, including the original data pointer.
    data: bytes


class Dng:
    def __init__(self, data):
        self.data = data
        if len(data) < 8 or data[:2] not in (b'II', b'MM'):
            raise ValueError('not a TIFF/DNG')
        self.bo = '<' if data[:2] == b'II' else '>'
        if struct.unpack_from(self.bo + 'H', data, 2)[0] != 42:
            raise ValueError('only classic TIFF supported; BigTIFF is not supported')
        self.root_offset = struct.unpack_from(self.bo + 'I', data, 4)[0]
        self.root, self.next_ifd = self.ifd(self.root_offset)
        if DNG_VERSION not in self.root:
            raise ValueError('TIFF has no DNGVersion')
        v = self.root[DNG_VERSION]
        if v.kind != 1 or v.count != 4:
            raise ValueError('invalid DNGVersion')
        self.image_ranges = self._image_ranges()
        if not self.image_ranges:
            raise ValueError('DNG has no strip or tile data')

    def ifd(self, offset):
        if offset < 8 or offset + 2 > len(self.data):
            raise ValueError('IFD outside file')
        count = struct.unpack_from(self.bo + 'H', self.data, offset)[0]
        end = offset + 2 + count * 12
        if end + 4 > len(self.data):
            raise ValueError('truncated IFD')
        result = {}
        for at in range(offset + 2, end, 12):
            tag, kind, n = struct.unpack_from(self.bo + 'HHI', self.data, at)
            if kind not in TYPE_SIZE or tag in result or not n:
                raise ValueError('unsupported TIFF type, empty or duplicate tag')
            size = n * TYPE_SIZE[kind]
            p = struct.unpack_from(self.bo + 'I', self.data, at + 8)[0] if size > 4 else at + 8
            if p + size > len(self.data):
                raise ValueError('tag payload outside file')
            result[tag] = Entry(tag, kind, n, self.data[at:at + 12], self.data[p:p + size])
        return result, struct.unpack_from(self.bo + 'I', self.data, end)[0]

    def uints(self, entry):
        formats = {3: 'H', 4: 'I', 13: 'I'}
        if entry.kind not in formats:
            raise ValueError('invalid offset/count type')
        return struct.unpack(self.bo + formats[entry.kind] * entry.count, entry.data)

    def _image_ranges(self):
        queue, seen, ranges = [self.root_offset], set(), []
        while queue:
            off = queue.pop()
            if off in seen:
                raise ValueError('cyclic or shared IFD tree unsupported')
            seen.add(off)
            entries, nxt = self.ifd(off)
            if nxt:
                queue.append(nxt)
            if 330 in entries:  # SubIFDs may hold the actual Bayer image.
                queue.extend(self.uints(entries[330]))
            for offset_tag, count_tag in ((273, 279), (324, 325), (513, 514)):
                if offset_tag not in entries and count_tag not in entries:
                    continue
                if offset_tag not in entries or count_tag not in entries:
                    raise ValueError('incomplete image storage tags')
                offsets, lengths = self.uints(entries[offset_tag]), self.uints(entries[count_tag])
                if len(offsets) != len(lengths):
                    raise ValueError('image offset/count length mismatch')
                for start, length in zip(offsets, lengths):
                    if not length or start < 8 or start + length > len(self.data):
                        raise ValueError('image payload outside file')
                    ranges.append((start, length))
        return ranges

    def image_digest(self):
        h = hashlib.sha256()
        for start, length in self.image_ranges:
            h.update(struct.pack('<II', start, length))
            h.update(self.data[start:start + length])
        return h.hexdigest()

    def extract(self):
        if XMP not in self.root:
            raise ValueError('no embedded XMP')
        return extract_xmp(self.root[XMP].data)

    def embed(self, cube, config, render_table=False, divisions=32):
        validate_settings(cube, config)
        if RGB_TABLES in self.root:
            raise ValueError('existing RGBTables must be reviewed; refusing to replace a color transform')
        config = dict(config)
        config['rendering'] = 'dng-rgbtables-reader-dependent' if render_table else 'settings-only'
        table = None
        if render_table:
            table = rgb_tables(cube, config, self.bo, divisions)
            config['rgbtables_divisions'] = divisions
            config['rgbtables_resampling_error'] = table_error(cube, config, table, self.bo)
        packet = xmp_packet(self.root[XMP].data if XMP in self.root else None, cube, config)
        result = bytearray(self.data)
        replacement = {tag: entry.raw for tag, entry in self.root.items()}

        def add(tag, kind, count, payload):
            if len(payload) != TYPE_SIZE[kind] * count:
                raise ValueError('invalid appended tag length')
            if len(payload) <= 4:
                value = payload.ljust(4, b'\x00')
            else:
                if len(result) % 2:
                    result.append(0)
                value = struct.pack(self.bo + 'I', len(result))
                result.extend(payload)
            replacement[tag] = struct.pack(self.bo + 'HHI', tag, kind, count) + value

        add(XMP, 1, len(packet), packet)
        if table is not None:
            add(RGB_TABLES, 7, len(table), table)
            version = max(self.root[DNG_VERSION].data, bytes((1, 6, 0, 0)))
            add(DNG_VERSION, 1, 4, version)
        if len(result) % 2:
            result.append(0)
        new_ifd = len(result)
        if len(replacement) > 65535 or new_ifd + 6 + len(replacement) * 12 >= 2 ** 32:
            raise ValueError('classic TIFF size limit exceeded')
        result.extend(struct.pack(self.bo + 'H', len(replacement)))
        for tag in sorted(replacement):
            result.extend(replacement[tag])
        result.extend(struct.pack(self.bo + 'I', self.next_ifd))
        struct.pack_into(self.bo + 'I', result, 4, new_ifd)
        output = bytes(result)
        check = Dng(output)
        if check.image_digest() != self.image_digest():
            raise ValueError('image data changed')
        recovered, recovered_config = check.extract()
        if recovered.source != cube.source or recovered_config != config:
            raise ValueError('metadata round trip failed')
        return output


def rgb_tables(cube, config, bo='<', divisions=32):
    """One unmasked background table, per Adobe DNG 1.6/1.7 RGBTables.

    DNG requires the same primaries/gamma at LUT input AND output. A log-to-709
    transform must remain settings-only until its color-space conversion exists.
    .cube red-fast rows must be reordered to DNG red-outer/blue-inner rows.
    """
    space = config['input_space']
    if space != config['output_space'] or space not in SPACES:
        raise ValueError('RGBTables requires a supported identical input/output space')
    gamma, primaries = SPACES[space]
    # Preserve domain clamping and LUT strength by resampling the complete chain.
    grid = cube.rgb_table(divisions, config['strength'])
    if np.min(grid) < 0 or np.max(grid) > 1:
        raise ValueError('RGBTables output must stay in 0..1; use settings-only to preserve overrange')
    header = struct.pack(bo + 'IIH5B', 1, 0, 0, divisions, 2, gamma, primaries, 1)
    return header + grid.astype(np.dtype(bo + 'f4')).tobytes()


def table_error(cube, config, table, bo):
    """Report resampling/float32 error under the tetrahedral reference.

    RGBTables permits at most 32 divisions; 33/65 point .cube tables are not
    stored verbatim there. Always keep the original source in XMP as well.
    This is a numeric reference, not a test of an application's interpolation.
    """
    n = table[10]
    grid = np.frombuffer(table[15:], dtype=bo + 'f4').reshape(n, n, n, 3)
    sampled = Cube(b'', '', None, grid.transpose(2, 1, 0, 3),
                   ((0.,) * 3, (1.,) * 3), ((0.,) * 3, (1.,) * 3))
    axis = np.linspace(0, 1, 17)
    points = np.concatenate((np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1).reshape(-1, 3),
                             np.random.default_rng(0x46504C).random((10000, 3))))
    delta = np.abs(sampled.apply(points) - cube.apply(points, config['strength']))
    return {'reference': 'tetrahedral, normalized input cube, RGB absolute error',
            'samples': len(points), 'mean': float(delta.mean()),
            'p95': float(np.percentile(delta, 95)), 'max': float(delta.max())}
