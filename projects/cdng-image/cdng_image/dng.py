"""Conservative Sigma fp TIFF rewriting; original metadata stays at its offsets.

Independent implementation. Does not copy the referenced third-party compressor.
Only native, single-IFD, single-strip CFA layouts with prefix metadata are rewritten.
"""
import hashlib
import io
import struct

import imagecodecs
import numpy as np
import tifffile

TYPE_SIZE = {1:1, 2:1, 3:2, 4:4, 5:8, 6:1, 7:1, 8:2, 9:4, 10:8, 11:4, 12:8, 13:4}
LAYOUT = {259, 273, 278, 279, 322, 323, 324, 325}


def pixel_hash(array):
    return hashlib.sha256(array.astype('<u2', copy=False).tobytes()).hexdigest()


def _prefix_check(data, limit, offset, seen=None):
    """Ensure all reachable metadata and thumbnail bytes survive prefix copying."""
    seen = set() if seen is None else seen
    if offset in seen:
        raise ValueError('Cyclic metadata IFD')
    seen.add(offset)
    if offset < 8 or offset + 2 > limit:
        raise ValueError('Metadata outside the retained header is unsupported')
    n, = struct.unpack_from('<H', data, offset)
    end = offset + 2 + 12*n + 4
    if end > limit:
        raise ValueError('Metadata IFD overlaps RAW data')
    values = {}
    for i in range(n):
        at = offset+2+12*i
        tag, typ, count, val = struct.unpack_from('<HHII', data, at)
        if typ not in TYPE_SIZE:
            raise ValueError(f'Unsupported TIFF field type {typ}')
        size = TYPE_SIZE[typ]*count
        if tag not in LAYOUT and size > 4 and (val < 8 or val+size > limit):
            raise ValueError(f'Metadata tag {tag} is outside the retained header')
        values[tag] = (typ, count, val)
        if tag in (330, 34665, 34853, 40965):
            if typ not in (4, 13):
                raise ValueError('Unsupported IFD pointer')
            ptrs = (val,) if count == 1 else struct.unpack_from('<'+'I'*count, data, val)
            for ptr in ptrs:
                if ptr:
                    _prefix_check(data, limit, ptr, seen)
    following, = struct.unpack_from('<I', data, end-4)
    if following:
        raise ValueError('Multiple image IFDs are not supported for recompression')
    if 513 in values or 514 in values:
        if not (513 in values and 514 in values):
            raise ValueError('Incomplete thumbnail pointers')
        start, size = values[513][2], values[514][2]
        if start+size > limit:
            raise ValueError('Thumbnail outside the retained header')


def _jpeg_is_lossless(blob):
    """Read JPEG markers up to SOF; never mistake an entropy byte for a marker."""
    if blob[:2] != b'\xff\xd8':
        return False
    i = 2
    while i+3 < len(blob):
        if blob[i] != 255:
            return False
        while i < len(blob) and blob[i] == 255:
            i += 1
        marker = blob[i]; i += 1
        if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
            return marker == 0xc3
        if marker in (0xda, 0xd9):
            return False
        size = int.from_bytes(blob[i:i+2], 'big')
        if size < 2:
            return False
        i += size
    return False


def compress(data, effort='balanced', codec='lj92', cancel=None, _geometry=None, backend='cpu'):
    """Return bytes and audit info; source and output RAW samples must match exactly."""
    if effort not in ('fast', 'balanced', 'max') or codec not in ('lj92', 'jxl'):
        raise ValueError('Unknown compression option')
    if codec != 'lj92':
        raise ValueError('Direct JPEG XL encoding of CFA CinemaDNG is not enabled: Resolve validation did not pass')
    if backend not in ('cpu','metal','cuda'):raise ValueError('Unknown compute backend')
    gpu=None
    if backend != 'cpu':
        from .gpu import get_gpu
        gpu=get_gpu(backend)
    if effort == 'max' and _geometry is None and codec == 'lj92':
        results = [compress(data,effort,codec,cancel,geometry,backend)
                   for geometry in ((256,256),(512,256),(1024,512))]
        return min(results,key=lambda result:len(result[0]))
    with tifffile.TiffFile(io.BytesIO(data)) as tf:
        if len(tf.pages) != 1:
            raise ValueError('Only single-image CinemaDNG frames are supported')
        p = tf.pages[0]
        if int(p.photometric) != 32803 or p.samplesperpixel != 1:
            raise ValueError('Expected a one-channel Bayer CFA DNG')
        bits = int(p.bitspersample)
        if bits not in (8,10,12,14,16):
            raise ValueError(f'Unsupported bit depth: {bits}')
        width, height = p.imagewidth, p.imagelength
        if width % 2:
            raise ValueError('Bayer frame width must be even')
        for tag in (50974,50975,52547):
            if p.tags.get(tag) and any(v != 1 for v in np.atleast_1d(p.tags[tag].value)):
                raise ValueError('Input with non-default pixel interleaving is unsupported')
        compression = int(p.compression)
        if compression == 7:
            for off, size in zip(p.dataoffsets, p.databytecounts):
                if not _jpeg_is_lossless(data[off:off+size]):
                    raise ValueError('Input uses lossy JPEG; lossless archive mode refuses it')
            pixels = p.asarray().astype(np.uint16, copy=False)
        elif compression != 1 or p.is_tiled or len(p.dataoffsets) != 1:
            raise ValueError('Recompression requires an uncompressed single-strip Sigma fp DNG')
        if tf.byteorder != '<' or tf.is_bigtiff:
            raise ValueError('Recompression currently requires little-endian classic TIFF')
        if p.tags.get(330):
            raise ValueError('SubIFD images are not supported for recompression')
        if p.tags.get(266) and int(p.tags[266].value) != 1:
            raise ValueError('Unsupported TIFF FillOrder')
        if p.tags.get(317) and int(p.tags[317].value) != 1:
            raise ValueError('Unsupported source TIFF predictor')
        off = min(p.dataoffsets)
        _prefix_check(data, off, struct.unpack_from('<I', data, 4)[0])
        row_bytes = (width*bits+7)//8
        required = row_bytes*height
        if compression == 1 and (p.databytecounts[0] < required or off+required > len(data)):
            raise ValueError('Truncated RAW data')
        if compression == 1:
            packed = data[off:off+required]
            if bits == 16:
                pixels = np.frombuffer(packed, '<u2').reshape(height, width).copy()
            elif bits == 8:
                pixels = np.frombuffer(packed, np.uint8).reshape(height, width).astype(np.uint16)
            else:
                pixels = imagecodecs.packints_decode(packed, np.uint16, bits, runlen=width).reshape(height,width)
        entries = {}
        root = struct.unpack_from('<I', data, 4)[0]
        count = struct.unpack_from('<H', data, root)[0]
        for i in range(count):
            entry = data[root+2+12*i:root+14+12*i]
            tag = struct.unpack_from('<H', entry)[0]
            if tag not in LAYOUT:
                entries[tag] = entry

    tw, th = _geometry or (512, 256)
    output = bytearray(data[:off])
    offsets, sizes = [], []
    predictors = {'fast':(1,), 'balanced':(1,5,7), 'max':tuple(range(1,8))}[effort]
    for y in range(0,height,th):
        for x in range(0,width,tw):
            if cancel and cancel.is_set():
                raise InterruptedError('Cancelled')
            tile = np.empty((th,tw), np.uint16)
            view = pixels[y:y+th,x:x+tw]
            tile[:view.shape[0],:view.shape[1]] = view
            # Repeat the last CFA pair when extending edges, without mixing phases.
            for xx in range(view.shape[1],tw):
                tile[:view.shape[0],xx] = tile[:view.shape[0],xx-2]
            for yy in range(view.shape[0],th):
                tile[yy] = tile[max(0,yy-2)]
            if codec == 'lj92':
                # Pair two sensor rows in each JPEG row: the JPEG's vertical
                # predictor then sees the same CFA color two sensor rows back.
                # Sample order stays unchanged; DNG permits different internal
                # JPEG dimensions when total sample counts match (spec p.21).
                components = tile.reshape((th,tw//2,2) if effort == 'fast' else (th//2,tw,2))
                if bits == 8:
                    components = components.astype(np.uint8)
                selected=predictors
                if gpu and len(predictors)>1:
                    ranked=gpu.rank(tile,components.shape[1]*2,bits,predictors)
                    selected=ranked[:2 if effort=='max' else 1]
                candidates = [imagecodecs.jpeg_encode(components, lossless=True, predictor=pred,
                              bitspersample=bits, colorspace='UNKNOWN', outcolorspace='UNKNOWN')
                              for pred in selected]
                blob = min(candidates, key=len)
                decoded = imagecodecs.jpeg_decode(blob).reshape(th,tw)
            else:
                blob = imagecodecs.jpegxl_encode(tile, lossless=True, distance=0,
                    effort={'fast':3,'balanced':7,'max':9}[effort], bitspersample=bits,
                    usecontainer=False, numthreads=1)
                decoded = imagecodecs.jpegxl_decode(blob, numthreads=1)
            if not np.array_equal(tile, decoded):
                raise ValueError('Codec roundtrip changed RAW values')
            offsets.append(len(output)); sizes.append(len(blob)); output.extend(blob)
    if len(output) & 1:
        output.append(0)
    def entry(tag, typ, count, value):
        entries[tag] = struct.pack('<HHII', tag, typ, count, value)
    entry(259,3,1,7 if codec == 'lj92' else 52546)
    entry(322,4,1,tw); entry(323,4,1,th)
    for tag, values in ((324, offsets),(325,sizes)):
        location = values[0]
        if len(values) > 1:
            location = len(output)
            output.extend(struct.pack('<'+'I'*len(values), *values))
        entry(tag,4,len(values),location)
    if codec == 'jxl':
        for tag in (50706,50707):
            entry(tag,1,4,int.from_bytes(b'\x01\x07\x00\x00','little'))
    ifd_at = len(output)
    output.extend(struct.pack('<H',len(entries)))
    for tag in sorted(entries):
        output.extend(entries[tag])
    output.extend(b'\0'*4)
    struct.pack_into('<I',output,4,ifd_at)
    result = bytes(output)
    # Verify the TIFF layout and tile indexing, in addition to each codec roundtrip.
    with tifffile.TiffFile(io.BytesIO(result)) as tf:
        decoded_image=tf.pages[0].asarray()
        if not np.array_equal(decoded_image, pixels):
            raise ValueError('Reconstructed DNG changed RAW values')
    info = dict(codec=codec, bits=bits, width=width, height=height,
                pixel_sha256=pixel_hash(pixels), pixel_verified=True,backend=backend,
                gpu_device=gpu.name if gpu else None)
    if len(result) >= len(data) and codec == 'lj92':
        return data, dict(info,codec='lj92-passthrough' if compression == 7 else 'uncompressed-passthrough')
    return result, info
