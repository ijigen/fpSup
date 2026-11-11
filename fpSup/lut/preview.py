"""Explicit linear 4:2:2 8-bit unpacking for native-preview diagnostic/reference use.

fp CINE MONIT1 evidence shows a 1620x911 linear 4:2:2 image in the native ring, packed Y0 Cr Y1 Cb (YVYU):
read as Y0 Cb Y1 Cr an orange cat came out blue against the LCD (isp-lab, 2026-10-27, user-confirmed).
That does not establish packing for every mode, RGB encoding, frame ownership,
chroma siting, or the place to write CPU corrections. The decoder requires
matrix and range explicitly, and never clips decoded RGB.

Luma coefficient cross-check: FFmpeg's official libavutil/csp.c.
https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavutil/csp.c
The matrix choice does not specify primaries or transfer function.
"""
from dataclasses import dataclass
import numpy as np

LUMA = {'601': (0.299, 0.114), '709': (0.2126, 0.0722)}


@dataclass(frozen=True)
class YUYVFrame:
    y: np.ndarray
    cb: np.ndarray
    cr: np.ndarray

    def __post_init__(self):
        planes = [np.asarray(p) for p in (self.y, self.cb, self.cr)]
        y, cb, cr = planes
        if (y.ndim != 2 or not all(y.shape) or y.shape[1] % 2
                or cb.shape != (y.shape[0], y.shape[1] // 2) or cr.shape != cb.shape
                or any(p.dtype != np.uint8 for p in planes)):
            raise ValueError('YUYV requires byte Y and half-width byte Cb/Cr planes')
        for name, plane in zip(('y', 'cb', 'cr'), planes):
            plane = plane.copy()
            plane.flags.writeable = False
            object.__setattr__(self, name, plane)

    @classmethod
    def unpack(cls, data, width, height, row_stride=None):
        if type(width) is not int or type(height) is not int or width < 2 or height < 1 or width % 2:
            raise ValueError('positive height and positive even width required')
        stride = width * 2 if row_stride is None else row_stride
        if type(stride) is not int or stride < width * 2:
            raise ValueError('explicit byte stride cannot be shorter than active row')
        if len(data) != stride * height:
            raise ValueError('exact image extent required; trim ring tail explicitly')
        rows = np.frombuffer(data, np.uint8).reshape(height, stride)
        pairs = rows[:, :width * 2].reshape(height, width // 2, 4)
        y = np.empty((height, width), np.uint8)
        y[:, 0::2], y[:, 1::2] = pairs[:, :, 0], pairs[:, :, 2]
        return cls(y, pairs[:, :, 3], pairs[:, :, 1])     # Y0 Cr Y1 Cb

    def rgb(self, matrix, value_range):
        """Pair-replicated chroma; no gamma conversion and no output clamp."""
        if matrix not in LUMA or value_range not in ('full', 'limited'):
            raise ValueError('explicit 601/709 matrix and full/limited range required')
        y = self.y.astype(np.float64)
        cb = np.repeat(self.cb.astype(np.float64) - 128, 2, axis=1)
        cr = np.repeat(self.cr.astype(np.float64) - 128, 2, axis=1)
        if value_range == 'limited':
            y, cb, cr = (y - 16) / 219, cb / 224, cr / 224
        else:
            y, cb, cr = y / 255, cb / 255, cr / 255
        kr, kb = LUMA[matrix]
        kg = 1 - kr - kb
        return np.stack((y + 2 * (1 - kr) * cr,
                         y - 2 * kb * (1 - kb) / kg * cb - 2 * kr * (1 - kr) / kg * cr,
                         y + 2 * (1 - kb) * cb), axis=-1)

    def summary(self):
        return {'width': self.y.shape[1], 'height': self.y.shape[0],
                'packing': 'linear Y0 Cr Y1 Cb (YVYU), 8-bit 4:2:2',
                'active_bytes': self.y.size * 2,
                'chroma_reconstruction': 'replicate one Cb/Cr pair to two pixels',
                'chroma_siting_verified': False, 'rgb_encoding_verified': False,
                'camera_write_path_verified': False}
