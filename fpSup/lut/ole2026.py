"""Experimental Ole Berek March 2026 CST subchain, outside the RAW menu.

This is a numerical candidate, not a sensor IDT or a Resolve pixel-match claim.
Gen5/DWG use published constants; Gen1 uses the older local Resolve extraction
in bmd_gen1/notes/BMD_FILM_GEN1_GAMUT.md, pending current-version measurement.
The author's final DaVinci DRT/Rec.709-gamma node is intentionally not modelled.
Our optional monitoring output is explicitly clip-linear + Gamma 2.4.
"""
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from color import GAMUTS, adaptation, rgb, transfer, xyz_white


GEN1_PRIMARIES = ((.91726, .25024), (.28333, 1.70723), (.08557, -.07078))
GEN1_WHITE = (.31354, .33048)
INPUT_ENCODINGS = ('bwg-film5', 'dwg-intermediate')


@dataclass(frozen=True)
class MeasuredMatrices:
    """Explicit reference matrices, with provenance kept by the caller's report."""
    p3_to_bwg: object
    gen1_to_srgb: object
    bwg_to_dwg: object
    dwg_to_709: object

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            matrix = np.array(getattr(self, name), dtype=np.float64, copy=True)
            if (matrix.shape != (3, 3) or not np.isfinite(matrix).all()
                    or np.linalg.cond(matrix) > 1e9):
                raise ValueError('finite invertible 3x3 reference matrix required: ' + name)
            matrix.flags.writeable = False
            object.__setattr__(self, name, matrix)

    def summary(self):
        return {name: getattr(self, name).tolist() for name in self.__dataclass_fields__}


@lru_cache(None)
def native_xyz(gamut):
    """RGB -> native-white XYZ; no implicit adaptation to common D65."""
    primaries, white = ((GEN1_PRIMARIES, GEN1_WHITE) if gamut == 'bmd-gen1-legacy'
                        else GAMUTS[gamut])
    p = np.array([xyz_white(xy) for xy in primaries]).T
    matrix = p * np.linalg.solve(p, xyz_white(white))
    matrix.flags.writeable = False
    return matrix


def linear_matrix(source, destination, *, cat):
    source_white = GEN1_WHITE if source == 'bmd-gen1-legacy' else GAMUTS[source][1]
    destination_white = GEN1_WHITE if destination == 'bmd-gen1-legacy' else GAMUTS[destination][1]
    adaptation_matrix = adaptation(source_white, destination_white) if cat else np.eye(3)
    return np.linalg.solve(native_xyz(destination), adaptation_matrix @ native_xyz(source))


def q_matrix():
    return linear_matrix('bmd-gen1-legacy', '709', cat=False)


def q(film5_values, *, matrices=None):
    """Deliberately reinterpret Film5 code values as Gen1/sRGB (author Node02)."""
    values = transfer(rgb(film5_values), 'srgb', inverse=True)
    matrix = q_matrix() if matrices is None else matrices.gen1_to_srgb
    return transfer(values @ matrix.T, 'srgb')


def node01(p3_linear, *, matrices=None):
    matrix = linear_matrix('p3d60', 'bmwg5', cat=True) if matrices is None else matrices.p3_to_bwg
    linear = rgb(p3_linear) @ matrix.T
    return transfer(linear, 'film5')


def node03(film5_values, *, encoded=True, matrices=None):
    linear = transfer(rgb(film5_values), 'film5', inverse=True)
    matrix = linear_matrix('bmwg5', 'dwg', cat=False) if matrices is None else matrices.bwg_to_dwg
    linear = linear @ matrix.T
    return transfer(linear, 'intermediate') if encoded else linear


def chain(p3_linear, *, correction, matrices=None):
    film5 = node01(p3_linear, matrices=matrices)
    return node03(q(film5, matrices=matrices) if correction else film5, matrices=matrices)


def input_to_film5(values, encoding, *, matrices=None):
    values = rgb(values)
    if encoding == 'bwg-film5':
        return values.copy()
    if encoding == 'dwg-intermediate':
        linear = transfer(values, 'intermediate', inverse=True)
        matrix = (linear_matrix('dwg', 'bmwg5', cat=False) if matrices is None
                  else np.linalg.inv(matrices.bwg_to_dwg))
        linear = linear @ matrix.T
        return transfer(linear, 'film5')
    raise ValueError('explicit supported log input required: ' + str(encoding))


def monitor(values, encoding, *, correction, matrices=None):
    """Normalized full Rec.709 D65 / Gamma 2.4, fixed clipping display model."""
    film5 = input_to_film5(values, encoding, matrices=matrices)
    linear_dwg = node03(q(film5, matrices=matrices) if correction else film5,
                        encoded=False, matrices=matrices)
    matrix = linear_matrix('dwg', '709', cat=False) if matrices is None else matrices.dwg_to_709
    linear_709 = linear_dwg @ matrix.T
    return transfer(np.clip(linear_709, 0., 1.), 'gamma24')


def factorized_monitor(bwg_film5, *, correction, matrices=None):
    """Exact curve/matrix graph, before approximation by any hardware 1D table.

    The two output linear matrices compose algebraically. The sRGB encode and
    Film5 decode compose as a scalar curve; they cannot cancel each other.
    This is an offline implementation candidate, not an ISP execution claim.
    """
    values = rgb(bwg_film5)
    if correction:
        matrix = q_matrix() if matrices is None else matrices.gen1_to_srgb
        values = transfer(values, 'srgb', inverse=True) @ matrix.T
        values = transfer(transfer(values, 'srgb'), 'film5', inverse=True)
    else:
        values = transfer(values, 'film5', inverse=True)
    output_matrix = (linear_matrix('dwg', '709', cat=False) @
                     linear_matrix('bmwg5', 'dwg', cat=False) if matrices is None
                     else matrices.dwg_to_709 @ matrices.bwg_to_dwg)
    return transfer(np.clip(values @ output_matrix.T, 0., 1.), 'gamma24')


def cube_bytes(size, encoding, *, correction, matrices=None):
    if isinstance(size, bool) or not isinstance(size, int) or not 2 <= size <= 65:
        raise ValueError('cube size must be an integer in 2..65')
    if encoding not in INPUT_ENCODINGS:
        raise ValueError('cube export requires an explicit supported log input')
    axis = np.linspace(0., 1., size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing='ij')
    source = np.stack((r, g, b), axis=-1)
    output = monitor(source, encoding, correction=correction, matrices=matrices).reshape(-1, 3)
    branch = ('Q-legacy-candidate' if matrices is None else 'Q-measured-CST') if correction else 'bypass'
    header = (f'TITLE "Ole2026 {branch} {encoding} to Rec709 Gamma24 clip v1"\n'
              '# EXPERIMENTAL. No RAW decoding or DaVinci DRT. No pixel-match claim.\n'
              f'# Input: {encoding}; normalized full; lookup clips outside 0..1.\n'
              '# Output: Rec.709 D65 / Gamma 2.4; clip-linear-0-1-v1.\n'
              f'LUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
    return (header + ''.join('%.9g %.9g %.9g\n' % tuple(row) for row in output)).encode()


def description():
    return dict(status='experimental-legacy-gen1-candidate',
                resolve_pixel_match_verified=False, sensor_calibration_verified=False,
                camera_backend_verified=False, raw_menu_registration=False,
                gen1_primaries_xy=GEN1_PRIMARIES, gen1_white_xy=GEN1_WHITE,
                gen1_source='bmd_gen1/notes/BMD_FILM_GEN1_GAMUT.md',
                negative_extension='local sRGB linear toe; current Resolve pending',
                nodes=[
                    dict(input='P3-D60/Linear', output='BWG4/5/Film5', cat=True),
                    dict(input='Gen1/sRGB (reinterpret)', output='sRGB/sRGB', cat=False),
                    dict(input='BWG4/5/Film5 (reinterpret)', output='DWG/DI', cat=False)],
                tone_mapping='none', gamut_mapping='none', ootf=False,
                q_matrix=q_matrix().tolist(),
                node01_matrix=linear_matrix('p3d60', 'bmwg5', cat=True).tolist(),
                node03_matrix=linear_matrix('bmwg5', 'dwg', cat=False).tolist(),
                q_factorization=['sRGB decode', '3x3 Gen1 to sRGB, CAT off', 'sRGB encode'],
                output=dict(gamut='Rec.709 D65', gamma='2.4', range='normalized-full',
                            display_model='clip-linear-0-1-v1',
                            matches_author_final_drt=False))
