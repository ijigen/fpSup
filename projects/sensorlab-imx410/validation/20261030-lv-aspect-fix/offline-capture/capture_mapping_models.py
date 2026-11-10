#!/usr/bin/env python3
"""Pixel-only capture mapping analysis. No product imports, builds or USB.

The source framebuffer is unavailable. Models below are conditional on the
fixed stock UI landmark positions measured in h4040. They can reject simple
mapping explanations; they cannot distinguish a capture transform from an
identical transform earlier in LCD/OSD composition.
"""
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
SHOTS = RUN / 'live' / 'shots'


def components(mask, minimum=30):
    pending = set(zip(*np.where(mask)))
    found = []
    while pending:
        first = pending.pop()
        queue, pixels = deque([first]), []
        while queue:
            y, x = queue.popleft()
            pixels.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    other = y + dy, x + dx
                    if other in pending:
                        pending.remove(other)
                        queue.append(other)
        if len(pixels) >= minimum:
            p = np.asarray(pixels)
            lo, hi = p.min(axis=0), p.max(axis=0) + 1
            found.append(dict(area=len(pixels), bbox=[int(lo[1]), int(lo[0]), int(hi[1]), int(hi[0])],
                              centre=[float(p[:, 1].mean()), float(p[:, 0].mean())]))
    return sorted(found, key=lambda v: -v['area'])


def landmarks(a, kind):
    r, g, b = (a[:, :, i] for i in range(3))
    if kind == 'qs':
        mask = (r < 100) & (g > 120) & (b > 120) & (b > r * 1.7)
    else:
        mask = (g > 170) & (g > r * 1.3) & (g > b * 1.2)
    return components(mask)


def repeat(a, axis):
    n = a.shape[axis]
    candidates = []
    for period in range(n // 2, n - 15):
        tail, head = (a[period:], a[:n - period]) if axis == 0 else (a[:, period:], a[:, :n - period])
        candidates.append((float(np.abs(tail - head).mean()), period))
    error, period = min(candidates)
    return dict(period=period, overlap=n - period, rgb_mae_255=round(error, 4), strong=error < 3)


def transform_bbox(box, scale, origin):
    x, y, right, bottom = box
    sx, sy = scale
    ox, oy = origin
    return [sx * x + ox, sy * y + oy, sx * right + ox, sy * bottom + oy]


def max_error(a, b):
    return round(max(abs(x - y) for x, y in zip(a, b)), 3)


def analyse():
    plan = json.loads((RUN / 'standby-acceptance-plan.json').read_text())
    geometry = {g['tag']: g for g in plan['geometry']}
    files = sorted(SHOTS.glob('*.jpg'))
    arrays = {p.name: np.asarray(Image.open(p)).astype(float) for p in files}
    base_qs = landmarks(arrays['h4040-qs-SS2888.jpg'], 'qs')[0]
    base_lv = landmarks(arrays['h4040-lv-SS2889.jpg'], 'lv')[0]
    results = []
    for path in files:
        match = re.fullmatch(r'(h4040|h3800|h3500|w5088|w5008|w4800)-(qs|lv)-SS(\d+)\.jpg', path.name)
        if not match:
            continue
        tag, kind, _ = match.groups()
        a = arrays[path.name]
        h, w = a.shape[:2]
        objects = landmarks(a, kind)
        main = objects[0]
        # For the LV periodic copies choose the top marker, independent of tiny
        # JPEG-induced area changes between its first and repeated instances.
        if kind == 'lv':
            main = min((v for v in objects if v['area'] >= objects[0]['area'] * 0.75), key=lambda v: v['centre'][1])
        xywh = geometry[tag]['estimated_screenshot_1024x682']
        scale = [xywh[2] / w, xywh[3] / h]
        if kind == 'qs':
            reference = list(base_qs['bbox'])
            if tag.startswith('w'):
                reference[0] -= 256
                reference[2] -= 256
            actual = main['bbox']
            predicted_zero = transform_bbox(reference, scale, [0, 0])
            predicted_centred = transform_bbox(reference, scale, xywh[:2])
            # Fit translation only; scaling is independently fixed by plan.
            tx = ((actual[0] - predicted_zero[0]) + (actual[2] - predicted_zero[2])) / 2
            ty = ((actual[1] - predicted_zero[1]) + (actual[3] - predicted_zero[3])) / 2
            predicted_fitted = transform_bbox(reference, scale, [tx, ty])
            metric = 'focus-frame bbox edges'
        else:
            reference = base_lv['centre']
            actual = main['centre']
            predicted_zero = [reference[0] * scale[0], reference[1] * scale[1]]
            predicted_centred = [predicted_zero[0] + xywh[0], predicted_zero[1] + xywh[1]]
            tx, ty = actual[0] - predicted_zero[0], actual[1] - predicted_zero[1]
            predicted_fitted = actual
            metric = 'top green AF marker centre'
        nonblack = a.max(axis=2) > 10
        right_edges = [int(np.where(row)[0][-1] + 1) if row.any() else 0 for row in nonblack]
        counts = {str(edge): right_edges.count(edge) for edge in sorted(set(right_edges))}
        yr, xr = repeat(a, 0), repeat(a, 1)
        predictions = {}
        if yr['strong']:
            period = yr['period']
            # Leading active rows predict an unseen trailing strip; the fit
            # does not reuse the trailing pixels it predicts.
            predictions['leading_rows_periodic_tail'] = dict(
                period=period, held_out_rows=h - period,
                rgb_mae_255=round(float(np.abs(a[period:] - a[:h - period]).mean()), 4))
        if kind == 'lv' and tag.startswith('w'):
            active = max(set(right_edges), key=right_edges.count)
            predictions['per_row_black_right_padding'] = dict(
                active_width=active, held_out_columns=w - active,
                rgb_mae_255=round(float(np.abs(a[:, active:]).mean()), 4))
            predictions['compact_wrong_pitch_counterexample'] = dict(
                compact_pitch_pixels=active, wrongly_assumed_output_pitch=w,
                phase_advance_per_row=(w - active) % active,
                row_start_phases=[(row * w) % active for row in range(5)],
                phase_cycle_rows=active // math.gcd(w, active),
                observed_right_edge_counts=counts)
        if kind == 'qs' and tag == 'h3800':
            oy, period = round(xywh[1]), round(xywh[3])
            compact = a[oy:oy + period]
            hypothetical = compact[(np.arange(h) - oy) % period]
            alternatives = []
            for candidate_origin in range(19, 22):
                for candidate_height in range(641, 645):
                    active = a[candidate_origin:candidate_origin + candidate_height]
                    predicted_top = active[(np.arange(candidate_origin) - candidate_origin) % candidate_height]
                    alternatives.append(dict(origin_y=candidate_origin, active_height=candidate_height,
                                             rgb_mae_255=round(float(np.abs(predicted_top - a[:candidate_origin]).mean()), 4)))
            predictions['centred_whole_rgb_y_repeat_counterexample'] = dict(
                origin_y=oy, active_height=period, tested_rows=[0, oy],
                rgb_mae_255=round(float(np.abs(hypothetical[:oy] - a[:oy]).mean()), 4),
                nearby_integer_mapping_best=min(alternatives, key=lambda v: v['rgb_mae_255']),
                reason='Wrapping the complete centred compact RGB image predicts its black footer above the viewport; actual top rows contain scene.')
        if kind == 'qs' and tag == 'w5088':
            ox, width = round(xywh[0]), round(xywh[2])
            outside = np.concatenate((a[:, :ox], a[:, ox + width:]), axis=1)
            predictions['centred_whole_rgb_black_padding_counterexample'] = dict(
                origin_x=ox, active_width=width,
                outside_rgb_mean_255=round(float(outside.mean()), 4),
                reason='A complete RGB viewport with black border predicts zero outside; actual QS background remains visible outside the centred UI panel.')
        results.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            tag=tag, screen=kind, size=[w, h], plan_xywh=xywh, landmark_metric=metric,
                            main_landmark=main, all_landmarks=objects, reference=reference,
                            zero_origin_prediction=predicted_zero, centred_origin_prediction=predicted_centred,
                            zero_origin_max_error_px=max_error(actual, predicted_zero),
                            centred_origin_max_error_px=max_error(actual, predicted_centred),
                            fitted_origin_px=[round(tx, 3), round(ty, 3)],
                            fitted_translation_max_error_px=max_error(actual, predicted_fitted),
                            vertical_repeat=yr, horizontal_repeat=xr,
                            held_out_mapping_checks=predictions,
                            row_right_nonblack_edge_counts=counts))
    return dict(kind='Conditional pixel-coordinate capture hypotheses; no product changes or camera access',
                reference_images=['h4040-qs-SS2888.jpg', 'h4040-lv-SS2889.jpg'],
                coordinate_convention='Half-open pixel boxes. Plan scaling includes its rounded decimal estimates.',
                assumptions=['Stock OSD landmarks would occupy baseline coordinates before the hypothesized capture transform.',
                             'Source frames are not available; actual native layout changes could produce the same landmarks.',
                             'Repeated strips can be capture sampling wrap, pre-existing composed pixels, or another earlier consumer.'],
                models=[
                    dict(name='translation only on a fixed full canvas', verdict='insufficient',
                         reason='QS frame and AF marker dimensions/positions scale with crop. Translation alone cannot scale a landmark or duplicate a strip.'),
                    dict(name='one zero-origin crop-sized transform for every consumer', verdict='rejected by paired QS images',
                         reason='Fits LV marker positions and late QS; h3800 QS needs about +20px y and w5088 QS about +81px x.'),
                    dict(name='one centred crop-sized transform for every consumer', verdict='rejected by LV and late QS',
                         reason='LV crop extent begins at0 and its marker lacks the planned +20/+46px y or +81/+85/+105px x offset.'),
                    dict(name='compact width pixels read as a1024-pixel contiguous row pitch', verdict='rejected under compact-buffer assumption',
                         reason='For width860/852/812, successive rows would walk horizontally modulo the compact width; observed LV right edges are vertical and stable. Padding each row would be a different model.'),
                    dict(name='per-capture origin plus Y repeat and X black padding', verdict='geometric model fits LV and late QS; does not explain all QS composites alone',
                         reason='Height LV/two h3500 captures repeat compressed content; width LV has constant valid span then black. Early QS has centred UI over a full background, requiring an additional layer/state distinction.'),
                    dict(name='state/consumer-specific viewport transform with independent video and OSD composition', verdict='compatible but underdetermined',
                         reason='Can assign centred origin to early h3800/w5088 QS and zero origin to LV/late QS, with repeat/padding edge rules. Assignment is inferred per capture, so it does not prove a capture-only cause or normal physical LCD.')],
                observations=results,
                unavailable_discriminators=['Source buffer identity and dimensions/stride at capture time',
                                            'Actual destination visibleW/H and offsets per video/OSD/screenshot consumer',
                                            'Independent physical LCD observation'],
                conclusion='No single dimension+origin mapping independent of consumer/state reproduces all13files. '
                'The pixels support a reduced viewport reaching the composite/capture path, with differing origin/edge handling. '
                'They neither prove capture-only error nor prove correct physical LCD output.')


if __name__ == '__main__':
    analysis = analyse()
    assert len(analysis['observations']) == 13, 'expected the complete13-image evidence set'
    by_name = {r['file']: r for r in analysis['observations']}
    assert by_name['h3800-qs-SS2890.jpg']['zero_origin_max_error_px'] > 15
    assert by_name['w5088-qs-SS2894.jpg']['zero_origin_max_error_px'] > 70
    assert all(r['zero_origin_max_error_px'] < 1.1 for r in analysis['observations'] if r['screen'] == 'lv')
    for name, width in [('w5088-lv-SS2895.jpg', 860), ('w5008-lv-SS2897.jpg', 852), ('w4800-lv-SS2899.jpg', 812)]:
        assert by_name[name]['row_right_nonblack_edge_counts'] == {str(width): 682}
    output = HERE / 'capture_mapping_models.json'
    output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + '\n')
    print(output)
