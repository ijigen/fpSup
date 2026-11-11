"""Observed Resolve CinemaDNG menu and separate standard numerical models.

Menu evidence is the user's three screenshots and accompanying description in
projects/lut-sup/validation/20261016-cdng-menu-01. The installed manual's shorter
list is not exhaustive. Screenshots establish labels, not pixel equivalence or
enabled states. No proprietary Blackmagic model is inferred from a menu label.
"""
from dataclasses import dataclass
from typing import Optional

from color import Space


@dataclass(frozen=True)
class ColorChoice:
    label: str
    gamut: Optional[str]


@dataclass(frozen=True)
class GammaChoice:
    label: str
    curve: Optional[str]


COLOR_SPACES = {
    'aces': ColorChoice('ACES', 'aces-ap0'),
    'adobe-rgb': ColorChoice('Adobe RGB', 'adobe-rgb'),
    'blackmagic-design': ColorChoice('Blackmagic Design', None),
    'p3-d60': ColorChoice('P3 D60', 'p3d60'),
    'p3-d65': ColorChoice('P3 D65', 'p3d65'),
    'rec2020': ColorChoice('Rec.2020', '2020'),
    'rec709': ColorChoice('Rec.709', '709'),
    'srgb': ColorChoice('sRGB', '709'),
}
GAMMAS = {
    'adobe-rgb': GammaChoice('Adobe RGB', 'adobe-rgb'),
    'gamma24': GammaChoice('Gamma 2.4', 'gamma24'),
    'gamma26': GammaChoice('Gamma 2.6', 'gamma26'),
    'linear': GammaChoice('Linear', 'linear'),
    'rec709': GammaChoice('Rec.709', None),
    'srgb': GammaChoice('sRGB', 'srgb'),
    'blackmagic-film': GammaChoice('Blackmagic Design Film', None),
    'blackmagic-extended-video': GammaChoice('Blackmagic Design Extended Video', None),
}
COMMON_GAMMAS = ('adobe-rgb', 'gamma24', 'gamma26', 'linear', 'rec709', 'srgb')
BLACKMAGIC_GAMMAS = ('blackmagic-film', 'blackmagic-extended-video')
EVIDENCE = 'projects/lut-sup/validation/20261016-cdng-menu-01/evidence.json'


def gamma_choices(color_space):
    if not isinstance(color_space, str) or color_space not in COLOR_SPACES:
        raise ValueError('select a CinemaDNG color space')
    return BLACKMAGIC_GAMMAS if color_space == 'blackmagic-design' else COMMON_GAMMAS


@dataclass(frozen=True)
class Selection:
    color_space: str
    gamma: str

    def __post_init__(self):
        if self.gamma not in gamma_choices(self.color_space):
            raise ValueError('gamma is not in the selected CinemaDNG color space menu')

    @property
    def numerical_reference_available(self):
        return (COLOR_SPACES[self.color_space].gamut is not None
                and GAMMAS[self.gamma].curve is not None)

    def encoding(self):
        color, gamma = COLOR_SPACES[self.color_space], GAMMAS[self.gamma]
        if not self.numerical_reference_available:
            if self.color_space == 'blackmagic-design':
                reason = 'CinemaDNG Blackmagic colorimetry/curve is unverified; Film Gen5 is not a substitute'
            else:
                reason = 'Resolve CinemaDNG Rec.709 gamma formula is unverified; BT.709 OETF is not a substitute'
            raise ValueError(reason)
        # No pre-LUT display rendering/clamp. ACES here uses standard AP0/D60;
        # its identification with Resolve's label still needs paired renders.
        return Space('cdng:' + self.color_space + '/' + self.gamma,
                     color.label + ' / ' + gamma.label, color.gamut, gamma.curve)

    def summary(self):
        return dict(color_space=self.color_space, color_space_label=COLOR_SPACES[self.color_space].label,
                    gamma=self.gamma, gamma_label=GAMMAS[self.gamma].label,
                    numerical_reference_available=self.numerical_reference_available,
                    model='standard primaries/Bradford/transfer; no Resolve DRT'
                        if self.numerical_reference_available else 'pending; no numerical substitute',
                    aces_mapping='AP0/D60 standard reference; Resolve mapping unverified'
                        if self.color_space == 'aces' else None,
                    negative_power_extension='signed; Resolve negative handling unverified',
                    resolve_pixel_match_verified=False, menu_evidence=EVIDENCE)


def catalogue():
    def describe_gamma(key):
        return dict(id=key, label=GAMMAS[key].label,
                    numerical_curve_available=GAMMAS[key].curve is not None)
    return dict(
        color_spaces=[dict(id=key, label=value.label, standard_gamut=value.gamut,
                           gamma_ids=list(gamma_choices(key)),
                           numerical_gamma_ids=[g for g in gamma_choices(key)
                                                if Selection(key, g).numerical_reference_available])
                      for key, value in COLOR_SPACES.items()],
        common_gammas=[describe_gamma(key) for key in COMMON_GAMMAS],
        blackmagic_gammas=[describe_gamma(key) for key in BLACKMAGIC_GAMMAS],
        menu_evidence=EVIDENCE, menu_option_enabled_state_verified=False,
        resolve_pixel_match_verified=False,
        pending_models=['Resolve CinemaDNG Rec.709 gamma',
                        'CinemaDNG Blackmagic Design / Film',
                        'CinemaDNG Blackmagic Design / Extended Video'])
