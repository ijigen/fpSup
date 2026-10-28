#!/usr/bin/env python3
"""Print the raw-image and capture-time tags of DNG files, read-only.

    ./dnghead.py SDIM0183.DNG SDIM0184.DNG ...

Walks IFD0, its SubIFDs and the EXIF IFD with the standard library only, so
it runs where exiftool is not installed.
"""
import pathlib
import struct
import sys

TAG_NAMES = {
    254: 'NewSubfileType', 256: 'ImageWidth', 257: 'ImageLength',
    258: 'BitsPerSample', 259: 'Compression', 262: 'Photometric',
    272: 'Model', 277: 'SamplesPerPixel', 305: 'Software',
    322: 'TileWidth', 323: 'TileLength', 330: 'SubIFDs',
    33434: 'ExposureTime', 33437: 'FNumber', 34665: 'ExifIFD',
    34855: 'ISO', 36867: 'DateTimeOriginal', 37386: 'FocalLength',
    37521: 'SubSecTimeOriginal', 50706: 'DNGVersion', 50717: 'WhiteLevel',
    50714: 'BlackLevel', 50829: 'ActiveArea',
}
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 13: 4}
TYPE_FORMATS = {1: 'B', 3: 'H', 4: 'I', 7: 'B', 9: 'i', 13: 'I'}


class DngReader:
    def __init__(self, path: pathlib.Path):
        self.data = path.read_bytes()
        order = self.data[:2]
        if order not in (b'II', b'MM'):
            raise ValueError(f'{path.name}: not a TIFF/DNG file')
        self.endian = '<' if order == b'II' else '>'

    def unpack(self, fmt: str, offset: int):
        return struct.unpack_from(self.endian + fmt, self.data, offset)

    def read_value(self, value_type: int, count: int, field_offset: int):
        size = TYPE_SIZES.get(value_type, 1) * count
        if size <= 4:
            where = field_offset
        else:
            where = self.unpack('I', field_offset)[0]
        if value_type == 2:
            return self.data[where:where + count].split(b'\0')[0].decode('latin1')
        if value_type in (5, 10):
            fmt = 'I' if value_type == 5 else 'i'
            pairs = self.unpack(f'{2 * count}{fmt}', where)
            values = [num / den if den else float('nan')
                      for num, den in zip(pairs[0::2], pairs[1::2])]
            return values[0] if count == 1 else values
        fmt = TYPE_FORMATS.get(value_type)
        if fmt is None:
            return f'<type {value_type} x{count}>'
        values = self.unpack(f'{count}{fmt}', where)
        return values[0] if count == 1 else list(values)

    def read_ifd(self, offset: int) -> dict:
        entry_count = self.unpack('H', offset)[0]
        tags = {}
        for index in range(entry_count):
            entry = offset + 2 + 12 * index
            tag, value_type, count = self.unpack('HHI', entry)
            if tag in TAG_NAMES:
                tags[TAG_NAMES[tag]] = self.read_value(value_type, count, entry + 8)
        return tags


def describe(path: pathlib.Path) -> None:
    reader = DngReader(path)
    ifd0 = reader.read_ifd(reader.unpack('I', 4)[0])
    print(f'== {path.name}  ({path.stat().st_size} B)')
    print(f'  IFD0     {ifd0}')
    sub_offsets = ifd0.get('SubIFDs', [])
    if isinstance(sub_offsets, int):
        sub_offsets = [sub_offsets]
    for number, sub_offset in enumerate(sub_offsets):
        print(f'  SubIFD{number}  {reader.read_ifd(sub_offset)}')
    if 'ExifIFD' in ifd0:
        print(f'  EXIF     {reader.read_ifd(ifd0["ExifIFD"])}')


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2
    status = 0
    for name in sys.argv[1:]:
        try:
            describe(pathlib.Path(name))
        except (OSError, ValueError, struct.error) as error:
            print(f'== {name}: {error}')
            status = 1
    return status


if __name__ == '__main__':
    sys.exit(main())
