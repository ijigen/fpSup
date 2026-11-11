"""Strict .cube import and a complete LUT reference, independent of fp hardware.

RGB table rows in .cube have red changing fastest. Do not fit this table to a
matrix at import: the complete source is also used for embedded DNG settings.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shlex

import numpy as np

MAX_SOURCE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class Cube:
    source: bytes
    title: str
    table1d: object
    table3d: object  # [blue, green, red, output_channel]
    range1d: tuple
    range3d: tuple

    @classmethod
    def read(cls, path):
        path = Path(path)
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('.cube exceeds 16 MiB')
        return cls.parse(path.read_bytes())

    @classmethod
    def parse(cls, source):
        if len(source) > MAX_SOURCE_BYTES:
            raise ValueError('.cube exceeds 16 MiB')
        text = source.decode('utf-8-sig')
        headers, values = {}, []
        supported = {'TITLE', 'LUT_1D_SIZE', 'LUT_3D_SIZE', 'DOMAIN_MIN',
                     'DOMAIN_MAX', 'LUT_1D_INPUT_RANGE', 'LUT_3D_INPUT_RANGE'}
        for line_no, line in enumerate(text.splitlines(), 1):
            try:
                # A # inside a quoted title is text, not a comment.
                parts = shlex.split(line, comments=True)
                if not parts:
                    continue
                key = parts[0]
                if key in supported:
                    if values:
                        raise ValueError('headers must precede data')
                    if key in headers:
                        raise ValueError('duplicate ' + key)
                    if key == 'TITLE':
                        if len(parts) != 2:
                            raise ValueError('TITLE needs one quoted name')
                        headers[key] = parts[1]
                    elif key.endswith('_SIZE'):
                        if len(parts) != 2:
                            raise ValueError(key + ' needs one integer')
                        size = int(parts[1])
                        limit = 4096 if key == 'LUT_1D_SIZE' else 65
                        if not 2 <= size <= limit:
                            raise ValueError(key + ' outside 2..' + str(limit))
                        headers[key] = size
                    else:
                        count = 2 if key.endswith('_INPUT_RANGE') else 3
                        if len(parts) != count + 1:
                            raise ValueError(key + ' has the wrong component count')
                        nums = tuple(float(p) for p in parts[1:])
                        if not np.isfinite(nums).all():
                            raise ValueError('non-finite range')
                        headers[key] = nums
                else:
                    if len(parts) != 3:
                        raise ValueError('unknown directive or invalid RGB row')
                    row = tuple(float(p) for p in parts)
                    if not np.isfinite(row).all():
                        raise ValueError('non-finite LUT output')
                    values.append(row)
                    n1 = headers.get('LUT_1D_SIZE', 0)
                    n3 = headers.get('LUT_3D_SIZE', 0)
                    if len(values) > n1 + n3 ** 3:
                        raise ValueError('too many rows or missing size header')
            except ValueError as e:
                raise ValueError(f'line {line_no}: {e}') from e
        n1, n3 = headers.get('LUT_1D_SIZE', 0), headers.get('LUT_3D_SIZE', 0)
        if not (n1 or n3) or len(values) != n1 + n3 ** 3:
            raise ValueError(f'expected {n1 + n3 ** 3} RGB rows; found {len(values)}')
        has_domain = 'DOMAIN_MIN' in headers or 'DOMAIN_MAX' in headers
        if n1 and n3 and has_domain:
            raise ValueError('combined shaper+3D requires separate INPUT_RANGE headers')
        if has_domain and any(k.endswith('_INPUT_RANGE') for k in headers):
            raise ValueError('DOMAIN and INPUT_RANGE declarations cannot be mixed')
        for kind, n in (('1D', n1), ('3D', n3)):
            if not n and f'LUT_{kind}_INPUT_RANGE' in headers:
                raise ValueError(f'INPUT_RANGE declared without LUT_{kind}_SIZE')
        domain = (headers.get('DOMAIN_MIN', (0., 0., 0.)),
                  headers.get('DOMAIN_MAX', (1., 1., 1.)))
        ranges = []
        for kind in ('1D', '3D'):
            r = headers.get(f'LUT_{kind}_INPUT_RANGE')
            low, high = domain if r is None else ((r[0],) * 3, (r[1],) * 3)
            with np.errstate(over='ignore'):
                span = np.array(high) - low
            if not np.isfinite(span).all() or np.any(span <= 0):
                raise ValueError('range maximum must exceed minimum in every channel')
            ranges.append((low, high))
        data = np.array(values, dtype=np.float64)
        one = data[:n1].copy() if n1 else None
        three = data[n1:].reshape(n3, n3, n3, 3).copy() if n3 else None
        for a in (one, three):
            if a is not None:
                a.flags.writeable = False
        return cls(source, headers.get('TITLE', ''), one, three, *ranges)

    @property
    def sha256(self):
        return hashlib.sha256(self.source).hexdigest()

    def summary(self):
        return {'title': self.title, 'source_sha256': self.sha256,
                'size1d': 0 if self.table1d is None else len(self.table1d),
                'size3d': 0 if self.table3d is None else len(self.table3d),
                'range1d': [list(v) for v in self.range1d],
                'range3d': [list(v) for v in self.range3d]}

    def apply(self, rgb, strength=1., *, diagnostics=None):
        """Tetrahedral interpolation using four vertices; only coordinates clamp.

        Accept an (..., 3) array already in the LUT's declared input color space.
        This performs no camera calibration, gamma conversion or auto exposure.
        """
        if not np.isfinite(strength) or not 0 <= strength <= 1:
            raise ValueError('strength must be in 0..1')
        if diagnostics is not None and not isinstance(diagnostics, dict):
            raise ValueError('diagnostics must be a dictionary')
        original = np.asarray(rgb, dtype=np.float64)
        if original.ndim < 1 or original.shape[-1] != 3 or not np.isfinite(original).all():
            raise ValueError('input must contain finite RGB triples')
        if strength == 0:
            return original.copy()
        y = original.reshape(-1, 3).copy()
        if self.table1d is not None:
            low, high = map(np.asarray, self.range1d)
            if diagnostics is not None:
                diagnostics['shaper_lookup'] = lookup_range(y, low, high)
            coordinates = np.clip((y - low) / (high - low), 0, 1)
            grid = np.linspace(0, 1, len(self.table1d))
            y = np.stack([np.interp(coordinates[:, c], grid, self.table1d[:, c])
                          for c in range(3)], axis=-1)
        if self.table3d is not None:
            n = len(self.table3d)
            low, high = map(np.asarray, self.range3d)
            if diagnostics is not None:
                diagnostics['cube_lookup'] = lookup_range(y, low, high)
            pos = np.clip((y - low) / (high - low), 0, 1) * (n - 1)
            base = np.minimum(np.floor(pos).astype(int), n - 2)
            fractions = pos - base
            order = np.argsort(-fractions, axis=1, kind='stable')
            sorted_f = np.take_along_axis(fractions, order, axis=1)
            weights = np.column_stack((1 - sorted_f[:, 0],
                                       sorted_f[:, 0] - sorted_f[:, 1],
                                       sorted_f[:, 1] - sorted_f[:, 2], sorted_f[:, 2]))
            vertices = base.copy()
            result = np.zeros_like(y)
            rows = np.arange(len(y))
            for v in range(4):
                if v:
                    vertices[rows, order[:, v - 1]] += 1
                r, g, b = vertices.T
                result += weights[:, v, None] * self.table3d[b, g, r]
            y = result
        if strength != 1:
            y = (1 - strength) * original.reshape(-1, 3) + strength * y
        return y.reshape(original.shape)

    def rgb_table(self, divisions, strength=1.):
        """Normalized RGB grid with RED OUTER / BLUE INNER order for DNG RGBTables."""
        if not 2 <= divisions <= 32:
            raise ValueError('DNG RGBTables divisions must be in 2..32')
        axis = np.linspace(0, 1, divisions)
        grid = np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1)
        return self.apply(grid, strength)


def lookup_range(values, low, high):
    """Counts before coordinate clipping; includes the post-shaper 3D input."""
    values = np.asarray(values).reshape(-1, 3)
    below, above = values < low, values > high
    return dict(samples=len(values), below_channels=int(below.sum()),
                above_channels=int(above.sum()),
                outside_samples=int(np.any(below | above, axis=1).sum()))
