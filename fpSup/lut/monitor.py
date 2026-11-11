"""Monitoring .cube pipeline with selectable input and fixed Rec.709/Gamma 2.4.

Input is calibrated, white-balanced scene-linear XYZ D65 (18% grey Y=.18),
or an explicitly declared reference RGB source converted to XYZ D65. This is
not a decoder/calibration for fp RAW or its uncharacterised native YUYV ring.
The baseline is a named simple clip/gamma rendering, not an ARRI/Resolve DRT.
"""
from dataclasses import dataclass
import hashlib
import json
from numbers import Real
from pathlib import Path
from typing import Optional
import numpy as np

from color import (REFERENCE_SPACES, GEN5, LOGC3, LOGC4,
                   from_xyz_matrix, rgb, source_to_xyz, transfer)
from cinemadng import Selection, catalogue
from cube import Cube, lookup_range


OUTPUT = 'rec709-gamma24'
BASELINE = 'clip-linear-rec709-gamma24-v1'
OUTPUT_CONTRACT = dict(space=OUTPUT, white='D65', transfer='gamma24',
                       range='normalized-full', scene_to_display_after_lut='none',
                       identified_from_cube=False)


def presets():
    return dict(schema='fpSup-monitor-presets-2', output=OUTPUT_CONTRACT.copy(),
                **catalogue(),
                camera_runtime_verified=False)


def baseline_xyz(xyz):
    linear = rgb(xyz) @ from_xyz_matrix('709').T
    return transfer(np.clip(linear, 0, 1), 'gamma24')


def _extent(values):
    values = rgb(values).reshape(-1, 3)
    return dict(min_rgb=values.min(0).tolist(), max_rgb=values.max(0).tolist(),
                **lookup_range(values, np.zeros(3), np.ones(3)))


@dataclass(frozen=True)
class Monitor:
    cube: Cube
    input_space: str
    strength: float = 1.
    exposure_ev: float = 0.
    input_gamma: Optional[str] = None

    @property
    def encoding(self):
        if self.input_gamma is not None:
            return Selection(self.input_space, self.input_gamma).encoding()
        if not isinstance(self.input_space, str) or self.input_space not in REFERENCE_SPACES:
            raise ValueError('select a CinemaDNG color space AND gamma, or an explicit numerical reference')
        return REFERENCE_SPACES[self.input_space]

    def __post_init__(self):
        self.encoding  # Reject unsupported/proprietary models before creating output files.
        if not isinstance(self.strength, Real) or not np.isfinite(self.strength) or not 0 <= self.strength <= 1:
            raise ValueError('strength must be in 0..1')
        if not isinstance(self.exposure_ev, Real) or not np.isfinite(self.exposure_ev) or not -20 <= self.exposure_ev <= 20:
            raise ValueError('finite exposure in -20..20 EV required')

    def settings(self):
        return dict(schema='fpSup-monitor-2', cube=self.cube.summary(),
                    input_space=self.encoding.summary(),
                    input_scope='cinemadng-standard-reference' if self.input_gamma is not None
                                else 'generic-numerical-reference; not a CinemaDNG menu option',
                    cinemadng=Selection(self.input_space, self.input_gamma).summary()
                        if self.input_gamma is not None else None,
                    output=OUTPUT_CONTRACT.copy(), strength=float(self.strength),
                    strength_space=OUTPUT, baseline=BASELINE, exposure_ev=float(self.exposure_ev),
                    exposure_reference='scene-linear 18% grey = 0.18; not sensor saturation',
                    transfer_parameters=dict(logc3_ei800=dict(LOGC3), logc4=dict(LOGC4), film5=dict(GEN5)),
                    fp_input_calibration_verified=False, on_camera_ready=False)

    def evaluate_xyz(self, xyz):
        xyz = rgb(xyz) * 2.**self.exposure_ev
        baseline = baseline_xyz(xyz)
        report = dict(baseline=BASELINE, strength_space=OUTPUT,
                      baseline_linear_709=_extent(xyz @ from_xyz_matrix('709').T),
                      lut_evaluated=self.strength != 0, lut_lookups={})
        if self.strength == 0:
            return baseline, {**report, 'output_before_display_clip': _extent(baseline)}
        space = self.encoding
        linear_input = xyz @ from_xyz_matrix(space.gamut).T
        report['input_linear_before_render'] = _extent(linear_input)
        # Legacy display-reference models clip explicitly. CinemaDNG standard
        # models preserve negative/HDR values until the declared LUT domain.
        if space.display_input:
            linear_input = np.clip(linear_input, 0, 1)
        encoded = transfer(linear_input, space.curve)
        look = self.cube.apply(encoded, diagnostics=report['lut_lookups'])
        if not np.isfinite(look).all():
            raise ValueError('LUT evaluation produced non-finite output')
        # Blend only two Rec.709/Gamma 2.4 images, never Log input with 709 output.
        output = look if self.strength == 1 else baseline + self.strength*(look-baseline)
        report['output_before_display_clip'] = _extent(output)
        return output, report

    def evaluate(self, values, source_space):
        output, report = self.evaluate_xyz(source_to_xyz(values, source_space))
        return output, {**report, 'source_space': source_space}

    def evaluate_codes(self, encoded):
        """Input conversion and exposure have already happened upstream.

        Used to compile lookup/strength in the user's selected LUT input domain,
        avoiding the severe saturated-colour errors of rebaking to another gamut.
        """
        encoded = rgb(encoded)
        if self.strength == 0:
            return baseline_xyz(self.encoding.to_xyz(encoded))
        look = self.cube.apply(encoded)
        if self.strength == 1:
            return rgb(look)
        baseline = baseline_xyz(self.encoding.to_xyz(encoded))
        return baseline + self.strength*(look-baseline)

    def compile(self, size=33, domain=None):
        """Sample lookup/strength in the LUT's own input encoding.

        The backend performs fp calibration/WB/exposure, input matrix and transfer
        before this table. Those operations and LCD adaptation are not baked.
        Arbitrary shapers/domain combinations can still incur resampling error;
        report it on held-out points using the actual float32 nodes.
        """
        if domain is None:
            domain = self.cube.range1d if self.cube.table1d is not None else self.cube.range3d
        domain = np.asarray(domain, dtype=float)
        if type(size) is not int or size not in (17, 33, 65) or domain.shape != (2, 3) or not np.isfinite(domain).all() or np.any(domain[1] <= domain[0]):
            raise ValueError('17/33/65 grid and finite increasing RGB domain required')
        axis = np.linspace(0, 1, size)
        # .cube: red fastest. Keep the user's chosen input encoding and domain.
        b, g, r = np.meshgrid(axis, axis, axis, indexing='ij')
        grid = np.stack((r, g, b), -1)*(domain[1]-domain[0])+domain[0]
        target = self.evaluate_codes(grid)
        header = ('TITLE "fpSup monitoring reference"\n'
                  'DOMAIN_MIN ' + ' '.join(f'{v:.12g}' for v in domain[0]) + '\n'
                  'DOMAIN_MAX ' + ' '.join(f'{v:.12g}' for v in domain[1]) + '\n'
                  f'LUT_3D_SIZE {size}\n')
        rows = '\n'.join(' '.join(f'{v:.12g}' for v in row) for row in target.reshape(-1, 3))
        composite = Cube.parse((header+rows+'\n').encode())
        packed = composite.table3d.astype('<f4')
        if not np.isfinite(packed).all():
            raise ValueError('composite exceeds float32 range')
        # Validate the actual float32 nodes intended for the backend.
        quantized = Cube(b'', '', None, packed, composite.range1d, composite.range3d)
        rng = np.random.default_rng(0x46504C55)
        points = rng.uniform(domain[0], domain[1], (8192, 3))
        # Include shadows and bright neutral values independently of random RGB.
        grey = np.repeat(np.linspace(domain[0, 0], domain[1, 0], 1025)[:, None], 3, axis=1)
        grey = grey[np.all((grey >= domain[0]) & (grey <= domain[1]), axis=1)]
        points = np.concatenate((points, grey))
        reference = self.evaluate_codes(points)
        delta = np.abs(quantized.apply(points)-reference)
        error = dict(samples=len(points), rgb_mae=float(delta.mean()),
                     p95_max_channel=float(np.percentile(delta.max(1), 95)),
                     max_channel=float(delta.max()), metric='709 gamma2.4 code error, not DeltaE',
                     includes_float32_nodes=True, measured_on_camera=False)
        return composite, packed.tobytes(), error


def prepare(model, output, size=33):
    composite, packed, error = model.compile(size)
    assets = {'source.cube': model.cube.source, 'monitor.cube': composite.source,
              'monitor.f32le': packed}
    config = model.settings()
    config['compiled'] = dict(input_space=model.encoding.id, size=size,
                             domain=[list(v) for v in composite.range3d],
                             table_order='blue outer, green middle, red inner, RGB channel',
                             interpolation='tetrahedral', error=error,
                             strength_baked=True, exposure_baked=False,
                             upstream='fp calibration/WB/exposure -> selected input matrix/transfer',
                             outside_domain='report before lookup clamp',
                             hardware_approximation_verified=False)
    config['assets'] = {name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                        for name, data in assets.items()}
    assets['settings.json'] = (json.dumps(config, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode()
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    for name, data in assets.items():
        with (out / name).open('xb') as stream:
            stream.write(data)
    return config


def png_bytes(monitor_rgb):
    """Map 709/Gamma2.4 to sRGB for a colour-tagged PNG; clip only for display."""
    import io
    from PIL import Image, ImageCms
    linear = np.clip(rgb(monitor_rgb), 0, 1)**2.4
    srgb = transfer(linear, 'srgb')
    array = np.rint(np.clip(srgb, 0, 1)*255).astype(np.uint8)
    if array.ndim != 3:
        raise ValueError('PNG preview requires an H x W x 3 image')
    buffer = io.BytesIO()
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    Image.fromarray(array).save(buffer, format='PNG', icc_profile=profile)
    return buffer.getvalue()
