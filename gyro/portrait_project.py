#!/usr/bin/env python3
"""Rotate a Gyroflow project to match a portrait CinemaDNG take.

    gyro/portrait_project.py A001_003.gyroflow      -> A001_003_portrait.gyroflow

Gyroflow reads a DNG sequence's size from the frames themselves (FFmpeg's tiff
decoder, which ignores the Orientation tag) but rotates the picture it shows by
that tag.  The stabiliser then works on portrait pixels with a landscape model:
the result is stretched, barely corrected, and autosync returns nonsense offsets
(+2283 ms and +3997 ms measured on a take whose true offset is -260 ms).
Gyroflow tracks this as issue #1117.

Three things have to agree, and only one of them can be set from the camera's
sidecars, so this rewrites all three in the project file:

    video_info      the frame size the stabiliser uses     1936x1090 -> 1090x1936
    calibration_data the lens model and rolling-shutter    swapped, LeftToRight
    imu_orientation  the IMU axes                          xyz -> Yxz

Landscape takes are left alone.  Verified against a Resolve export of A001_014
(EXIF 8): residual frame-to-frame motion 2.52 px unstabilised, 0.26 px through
a project rotated this way, against 2.35 px with the landscape project.

Use it like this, and note that autosync has to run AFTER the rotation:

    1  Gyroflow: load the DNG sequence, the .gcsv and the .json by hand.
    2  Save the project.  Do not autosync yet -- before the rotation it cannot
       find the right offset.
    3  gyro/portrait_project.py <that file>
    4  Gyroflow: open the _portrait project, autosync, save.
    5  Resolve: point the Gyroflow plugin at it, and rotate the clip yourself.
"""
import copy, json, os, struct, sys, urllib.parse

IMU     = {1: 'xyz', 3: 'XYz', 6: 'yXz', 8: 'Yxz'}
READOUT = {1: 'TopToBottom', 3: 'BottomToTop', 6: 'RightToLeft', 8: 'LeftToRight'}


def dng_orientation(path):
    """TIFF tag 0x112 of one frame: 1 landscape, 3 inverted, 6/8 portrait."""
    d = open(path, 'rb').read(0x1000)
    if d[:4] != b'II*\0':
        raise SystemExit(f'{os.path.basename(path)} is not a little-endian TIFF/DNG')
    ifd0 = struct.unpack_from('<I', d, 4)[0]
    for i in range(struct.unpack_from('<H', d, ifd0)[0]):
        tag, typ, cnt, val = struct.unpack_from('<HHII', d, ifd0 + 2 + 12 * i)
        if tag == 0x112:
            return val & 0xFFFF
    return 1


def frames_folder(project):
    url = urllib.parse.urlparse(project['videofile'])
    return os.path.dirname(urllib.parse.unquote(url.path))


def rotate(project, orientation):
    p = copy.deepcopy(project)
    quarter = orientation in (6, 8)

    vi = p['video_info']
    if quarter:
        vi['width'], vi['height'] = vi['height'], vi['width']
    vi['rotation'] = 0.0          # the size now describes the rotated frame

    out = p.get('output') or {}
    if quarter and out.get('output_width') and out.get('output_height'):
        out['output_width'], out['output_height'] = out['output_height'], out['output_width']

    c = p.get('calibration_data') or {}
    if c:
        if quarter:
            w, h = c['calib_dimension']['w'], c['calib_dimension']['h']
            for k in ('calib_dimension', 'orig_dimension', 'output_dimension'):
                if k in c:
                    c[k] = {'w': h, 'h': w}
            m = c['fisheye_params']['camera_matrix']
            # fx, fy stay; the principal point follows the rotation
            c['fisheye_params']['camera_matrix'] = [[m[0][0], 0.0, m[1][2]],
                                                    [0.0, m[1][1], m[0][2]],
                                                    [0.0, 0.0, 1.0]]
            for k in ('name', 'camera_setting', 'identifier'):
                if k in c and isinstance(c[k], str):
                    c[k] = c[k].replace(f'{w}x{h}', f'{h}x{w}')
        c['frame_readout_direction'] = READOUT[orientation]

    p['gyro_source']['imu_orientation'] = IMU[orientation]
    p['offsets'] = {}             # the old offset belongs to the old geometry
    return p


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    project = json.load(open(src))
    folder = frames_folder(project)
    dngs = sorted(f for f in os.listdir(folder) if f.lower().endswith('.dng'))
    if not dngs:
        raise SystemExit(f'no DNG frames beside the project, in {folder}')
    o = dng_orientation(os.path.join(folder, dngs[0]))
    if o not in IMU:
        raise SystemExit(f'unexpected Orientation {o} in {dngs[0]}')
    if o == 1:
        print(f'{os.path.basename(src)}: Orientation 1, a landscape take -- nothing to change')
        return

    fps = project['video_info'].get('fps')
    if fps and abs(fps - round(fps)) < 1e-6 and abs(fps - 29.97) < 0.5:
        print(f'  note: the project says {fps} fps.  If the take is 29.97, set it with the '
              f'pencil beside the frame rate -- 30.0 drifts about a millisecond per second.')

    p = rotate(project, o)
    dst = os.path.splitext(src)[0] + '_portrait.gyroflow'
    json.dump(p, open(dst, 'w'), indent=2)
    vi, c = p['video_info'], p['calibration_data']
    print(f'{os.path.basename(src)}: Orientation {o}')
    print(f'  video       {project["video_info"]["width"]}x{project["video_info"]["height"]}'
          f' -> {vi["width"]}x{vi["height"]}')
    print(f'  lens model  -> {c["calib_dimension"]["w"]}x{c["calib_dimension"]["h"]},'
          f' readout {c["frame_readout_direction"]}')
    print(f'  IMU         -> {p["gyro_source"]["imu_orientation"]}')
    print(f'  written     {os.path.basename(dst)}   (autosync it in Gyroflow now)')


if __name__ == '__main__':
    main()
