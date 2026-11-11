"""Verified CEQ resource packing, NOT a model of silicon pixel arithmetic.

fp 5.02 C01084D8 accepts 144 u16 values, arranged as six 24-value planes.
C0108C98 routes the first 16 and final 8 values to CEQ and CEQ24 shadows.
Planes 1 and 4 are shifted left by two. The geometric pattern is suggestive of
HSV anchors, but channel meaning and interpolation require pixel measurements.
This module never writes the camera, enables a block or changes its controls.
"""
from dataclasses import dataclass
import struct

PLANE_B_SHIFT = 2
TABLES = {'ORG': (0x30211EE0, 48), 'TGT': (0x30211FA0, 48),
          'ORG24': (0x30212080, 24), 'TGT24': (0x302120E0, 24)}
ROUTE_NAMES = {'ORG': 'CEQ_ORG', 'TGT': 'CEQ_TGT',
               'ORG24': 'CEQ24_ORG', 'TGT24': 'CEQ24_TGT'}


@dataclass(frozen=True)
class CEQResource:
    planes: tuple

    def __post_init__(self):
        planes = tuple(tuple(p) for p in self.planes)
        if len(planes) != 6 or any(len(p) != 24 for p in planes):
            raise ValueError('CEQ resource requires six planes of 24 values')
        if any(type(v) is not int or not 0 <= v <= 65535 for p in planes for v in p):
            raise ValueError('CEQ source values must be exact u16 integers')
        object.__setattr__(self, 'planes', planes)

    @classmethod
    def from_bytes(cls, data):
        if len(data) != 288:
            raise ValueError('CEQ resource must be exactly 288 bytes')
        values = struct.unpack('<144H', data)
        return cls(tuple(values[i:i + 24] for i in range(0, 144, 24)))

    def to_bytes(self):
        return struct.pack('<144H', *(v for plane in self.planes for v in plane))

    def shadow_tables(self, context=0):
        if context not in (0, 1):
            raise ValueError('unknown ISP context')
        result = {}
        for offset, main, extra in ((0, 'ORG', 'ORG24'), (3, 'TGT', 'TGT24')):
            planes = [list(self.planes[offset + i]) for i in range(3)]
            planes[1] = [v << PLANE_B_SHIFT for v in planes[1]]
            for key, span in ((main, slice(0, 16)), (extra, slice(16, 24))):
                address, count = TABLES[key]
                words = [v for plane in planes for v in plane[span]]
                assert len(words) == count
                result[key] = {'address': address + 0x30000 * context, 'words': words}
        return result

    @classmethod
    def from_shadow_tables(cls, tables):
        planes = []
        for main, extra in (('ORG', 'ORG24'), ('TGT', 'TGT24')):
            a, b = tables[main], tables[extra]
            if len(a) != 48 or len(b) != 24:
                raise ValueError('wrong CEQ table size')
            for i in range(3):
                values = list(a[i * 16:(i + 1) * 16]) + list(b[i * 8:(i + 1) * 8])
                if any(type(v) is not int or v < 0 for v in values):
                    raise ValueError('invalid CEQ shadow word')
                if i == 1:
                    mask = (1 << PLANE_B_SHIFT) - 1
                    if any(v & mask for v in values):
                        raise ValueError('shadow cannot be losslessly encoded as native CEQ resource')
                    values = [v >> PLANE_B_SHIFT for v in values]
                planes.append(tuple(values))
        return cls(tuple(planes))

    @classmethod
    def from_snapshot(cls, regions, context=0):
        if context not in (0, 1):
            raise ValueError('unknown ISP context')
        tables = {}
        for key, route in ROUTE_NAMES.items():
            address, count = TABLES[key]
            prefix = f'bank{context}_{route}_'
            matches = [v for name, v in regions.items() if name.startswith(prefix)]
            if len(matches) != 1 or int(matches[0]['address'], 16) != address + context * 0x30000:
                raise ValueError('missing or ambiguous native CEQ region')
            words = matches[0]['words']
            if len(words) != (56 if key == 'TGT' else count):
                raise ValueError('incomplete native CEQ region')
            # TGT's final eight words are control fields, not source anchors.
            tables[key] = words[:count]
        return cls.from_shadow_tables(tables)

    def summary(self):
        return {'source_bytes': 288, 'planes': [list(p) for p in self.planes],
                'layout_verified': True, 'pixel_formula_verified': False,
                'complete_isp_job': False, 'control_fields_included': False,
                'plane_names': ['ORG_A', 'ORG_B', 'ORG_C', 'TGT_A', 'TGT_B', 'TGT_C'],
                'shadow_plane_b_shift': PLANE_B_SHIFT}
