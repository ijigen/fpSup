"""Explicit LUT input encodings; scene exposure 0.18 means 18% grey.

No sensor calibration or display rendering is inferred from a .cube. Matrices
operate on linear light. Negative/overrange values survive these conversions;
the monitoring layer declares display clipping and LUT lookup clipping itself.
Primary references (formulae, primaries, published check values):
ACES AP0: https://docs.acescentral.com/encodings/aces2065-1/
Adobe RGB: https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf
ARRI LogC3: https://www.arri.com/resource/blob/31918/66f56e6abb6e5b6553929edf9aa7483e/2017-03-alexa-logc-curve-in-vfx-data.pdf
ARRI LogC4: https://www.arri.com/resource/blob/278790/f3318e8c9c65617d8c5ca3f8b3e32051/2023-05-arri-logc4-specification-data.pdf
Sony: https://download.pro.sony/FNGP/protein/1237494271390/1237494271406.pdf
Panasonic: https://pro-av.panasonic.net/jp/cinema_camera_varicam_eva/support/pdf/VARICAM_V-Log_V-Gamut.pdf
DWG/DI: https://documents.blackmagicdesign.com/InformationNotes/DaVinci_Resolve_17_Wide_Gamut_Intermediate.pdf
BMD Gen5: local official reference transcription in
bmcc6k/analysis-20260924/bmcc6k-liveview-rec709-20260924/reference/gen5_technical.txt.
"""
from dataclasses import dataclass
from functools import lru_cache
import numpy as np


D65 = (0.3127, 0.3290)
D60 = (0.32168, 0.33767)
GAMUTS = {
    '709': (((.640, .330), (.300, .600), (.150, .060)), D65),
    '2020': (((.708, .292), (.170, .797), (.131, .046)), D65),
    'p3d60': (((.680, .320), (.265, .690), (.150, .060)), D60),
    'p3d65': (((.680, .320), (.265, .690), (.150, .060)), D65),
    'adobe-rgb': (((.640, .330), (.210, .710), (.150, .060)), D65),
    'aces-ap0': (((.7347, .2653), (.0000, 1.0000), (.0001, -.0770)), D60),
    'awg3': (((.6840, .3130), (.2210, .8480), (.0861, -.1020)), D65),
    'awg4': (((.7347, .2653), (.1424, .8576), (.0991, -.0308)), D65),
    'sgamut3cine': (((.766, .275), (.225, .800), (.089, -.087)), D65),
    'sgamut3': (((.730, .280), (.140, .855), (.100, -.050)), D65),
    'vgamut': (((.730, .280), (.165, .840), (.100, -.030)), D65),
    'bmwg5': (((.7177215, .3171181), (.2280410, .8615690),
               (.1005841, -.0820452)), (.3127170, .3290312)),
    'dwg': (((.8000, .3130), (.1682, .9877), (.0790, -.1155)), D65),
}

# ARRI's normative AWG4 matrix has higher precision than its rounded primaries.
AWG4_XYZ = np.array([[.704858320407232064, .129760295170463003, .115837311473976537],
                    [.254524176404027025, .781477732712002049, -.036001909116029039],
                    [0., 0., 1.089057750759878429]])
BRADFORD = np.array([[.8951, .2664, -.1614], [-.7502, 1.7135, .0367],
                     [.0389, -.0685, 1.0296]])
LOGC3 = dict(cut=.010591, a=5.555556, b=.052272, c=.247190,
             d=.385537, e=5.367655, f=.092809)
LOGC4 = dict(a=(2.**18 - 16) / 117.45, b=(1023. - 95) / 1023, c=95. / 1023)
LOGC4['s'] = (7 * np.log(2) * 2.**(7 - 14 * LOGC4['c'] / LOGC4['b'])
              / (LOGC4['a'] * LOGC4['b']))
LOGC4['t'] = (2.**(14 * (-LOGC4['c'] / LOGC4['b']) + 6) - 64) / LOGC4['a']
GEN5 = dict(a=.08692876065491224, b=.005494072432257808, c=.5300133392291939,
            d=8.283605932402494, e=.09246575342465753, cut=.005)


def rgb(values):
    values = np.asarray(values, dtype=np.float64)
    if (values.ndim < 1 or values.shape[-1] != 3 or not values.size
            or not np.isfinite(values).all()):
        raise ValueError('nonempty finite RGB/XYZ triples required')
    return values


def xyz_white(xy):
    x, y = xy
    return np.array([x / y, 1., (1 - x - y) / y])


def adaptation(source_white, destination_white):
    if source_white == destination_white:
        return np.eye(3)
    scales = (BRADFORD @ xyz_white(destination_white)) / (BRADFORD @ xyz_white(source_white))
    return np.linalg.solve(BRADFORD, np.diag(scales) @ BRADFORD)


@lru_cache(None)
def to_xyz_matrix(gamut):
    """Linear gamut RGB -> XYZ with the common D65 white; row-vector caller uses M.T."""
    if gamut not in GAMUTS:
        raise ValueError('unknown gamut: ' + str(gamut))
    primaries, white = GAMUTS[gamut]
    if gamut == 'awg4':
        matrix = AWG4_XYZ.copy()
    else:
        p = np.array([xyz_white(xy) for xy in primaries]).T
        matrix = p * np.linalg.solve(p, xyz_white(white))
    matrix = adaptation(white, D65) @ matrix
    matrix.flags.writeable = False
    return matrix


@lru_cache(None)
def from_xyz_matrix(gamut):
    matrix = np.linalg.inv(to_xyz_matrix(gamut))
    matrix.flags.writeable = False
    return matrix


def transfer(values, curve, inverse=False):
    """Unclipped transfer functions, with linear toes extended below black.

    Power curves use a signed extension solely for numerical conversion; display
    rendering clips explicitly in monitor.py. np.where's unused log branch is
    evaluated on a safe argument, never by clipping the actual linear toe.
    """
    x = np.asarray(values, dtype=np.float64)
    if not np.isfinite(x).all():
        raise ValueError('finite transfer values required')
    if curve == 'linear':
        return x.copy()
    if curve in ('gamma24', 'gamma26', 'adobe-rgb'):
        exponent = {'gamma24': 2.4, 'gamma26': 2.6, 'adobe-rgb': 563/256}[curve]
        return np.sign(x) * np.abs(x)**(exponent if inverse else 1/exponent)
    if curve == 'srgb':
        if inverse:
            return np.where(x <= .04045, x / 12.92, ((np.maximum(x, .04045) + .055) / 1.055)**2.4)
        return np.where(x <= .0031308, 12.92*x, 1.055*np.maximum(x, .0031308)**(1/2.4) - .055)
    if curve == 'logc3-ei800':
        p = LOGC3
        if inverse:
            return np.where(x > p['e']*p['cut']+p['f'],
                            (10**((x-p['d'])/p['c'])-p['b'])/p['a'], (x-p['f'])/p['e'])
        return np.where(x > p['cut'], p['c']*np.log10(p['a']*np.maximum(x, p['cut'])+p['b'])+p['d'],
                        p['e']*x+p['f'])
    if curve == 'logc4':
        p = LOGC4
        if inverse:
            return np.where(x >= 0, (2**(14*(x-p['c'])/p['b']+6)-64)/p['a'], x*p['s']+p['t'])
        return np.where(x >= p['t'], (np.log2(p['a']*np.maximum(x, p['t'])+64)-6)/14*p['b']+p['c'],
                        (x-p['t'])/p['s'])
    if curve == 'slog3':
        if inverse:
            return np.where(x >= 171.2102946929/1023,
                            10**((x*1023-420)/261.5)*.19-.01,
                            (x*1023-95)*.01125/(171.2102946929-95))
        return np.where(x >= .01125, (420+np.log10((np.maximum(x, .01125)+.01)/.19)*261.5)/1023,
                        (x*(171.2102946929-95)/.01125+95)/1023)
    if curve == 'vlog':
        if inverse:
            return np.where(x >= .181, 10**((x-.598206)/.241514)-.00873, (x-.125)/5.6)
        return np.where(x >= .01, .241514*np.log10(np.maximum(x, .01)+.00873)+.598206, 5.6*x+.125)
    if curve == 'film5':
        p = GEN5
        if inverse:
            return np.where(x >= p['d']*p['cut']+p['e'], np.exp((x-p['c'])/p['a'])-p['b'], (x-p['e'])/p['d'])
        return np.where(x >= p['cut'], p['a']*np.log(np.maximum(x, p['cut'])+p['b'])+p['c'], p['d']*x+p['e'])
    if curve == 'intermediate':
        if inverse:
            return np.where(x > .02740668, 2**(x/.07329248-7)-.0075, x/10.44426855)
        return np.where(x > .00262409, (np.log2(np.maximum(x, .00262409)+.0075)+7)*.07329248,
                        x*10.44426855)
    raise ValueError('unknown transfer curve: ' + str(curve))


@dataclass(frozen=True)
class Space:
    id: str
    label: str
    gamut: str
    curve: str
    display_input: bool = False

    def to_xyz(self, values):
        return transfer(rgb(values), self.curve, inverse=True) @ to_xyz_matrix(self.gamut).T

    def from_xyz(self, values):
        return transfer(rgb(values) @ from_xyz_matrix(self.gamut).T, self.curve)

    def summary(self):
        return dict(id=self.id, label=self.label, gamut=self.gamut, transfer=self.curve,
                    white_xy=list(GAMUTS[self.gamut][1]),
                    xyz_d65_to_linear_rgb=from_xyz_matrix(self.gamut).tolist(),
                    input_render='clip-linear-0-1-v1' if self.display_input else 'none',
                    reference_grey_linear=.18, code_range='normalized-full')


# Generic numerical references, NOT the CinemaDNG Camera RAW menu. Keep these
# for archived manufacturer-LUT regressions and explicitly declared RGB sources.
REFERENCE_SPACES = {s.id: s for s in [
    Space('rec709-gamma24', 'Rec.709 / Gamma 2.4', '709', 'gamma24', True),
    Space('srgb', 'sRGB', '709', 'srgb', True),
    Space('arri-logc3-ei800', 'ARRI Wide Gamut 3 / LogC3 EI800', 'awg3', 'logc3-ei800'),
    Space('arri-logc4', 'ARRI Wide Gamut 4 / LogC4', 'awg4', 'logc4'),
    Space('sony-slog3-cine', 'Sony S-Gamut3.Cine / S-Log3', 'sgamut3cine', 'slog3'),
    Space('sony-slog3', 'Sony S-Gamut3 / S-Log3', 'sgamut3', 'slog3'),
    Space('panasonic-vlog', 'Panasonic V-Gamut / V-Log', 'vgamut', 'vlog'),
    Space('blackmagic-film-gen5', 'Blackmagic Wide Gamut / Film Gen5', 'bmwg5', 'film5'),
    Space('davinci-intermediate', 'DaVinci Wide Gamut / Intermediate', 'dwg', 'intermediate'),
    Space('linear-709', 'Rec.709 / Linear', '709', 'linear'),
    Space('linear-p3d60', 'P3-D60 / Linear', 'p3d60', 'linear'),
]}
SOURCE_SPACES = {k: REFERENCE_SPACES[k] for k in ('srgb', 'linear-709', 'davinci-intermediate')}
SOURCE_SPACES.update({
    'linear-2020': Space('linear-2020', 'Rec.2020 / Linear', '2020', 'linear'),
    'linear-dwg': Space('linear-dwg', 'DaVinci Wide Gamut / Linear', 'dwg', 'linear'),
})


def source_to_xyz(values, source_space):
    if source_space == 'xyz-d65':
        return rgb(values).copy()
    if source_space not in SOURCE_SPACES:
        raise ValueError('explicit supported source space required')
    return SOURCE_SPACES[source_space].to_xyz(values)
