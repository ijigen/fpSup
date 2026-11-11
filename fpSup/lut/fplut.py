#!/usr/bin/env python3
"""fpSup LUT offline import/preview and DNG settings reference (no camera I/O)."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zlib

from cube import Cube
from dng import Dng, settings


def exclusive_write(path, content):
    with Path(path).open('xb') as f:
        f.write(content)


def add_settings_args(parser):
    parser.add_argument('--name')
    parser.add_argument('--input-space', required=True, help='explicit LUT input space; .cube does not identify it')
    parser.add_argument('--output-space', required=True)
    parser.add_argument('--strength', type=float, default=1.)


def monitor_command(args):
    """Monitoring always declares 709 output; no output-space option."""
    import io
    import numpy as np
    from monitor import Monitor, png_bytes, prepare
    cube = Cube.read(args.cube)
    model = Monitor(cube, args.input_space, args.strength, args.exposure, input_gamma=args.input_gamma)
    if args.command == 'monitor-prepare':
        config = prepare(model, args.output, args.size)
        print(json.dumps(config, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    output = Path(args.output)
    sidecar = output.with_suffix(output.suffix + '.json')
    if output.exists() or sidecar.exists():
        raise FileExistsError('monitor output or settings sidecar already exists')
    if args.command == 'monitor-render':
        if output.suffix.lower() != '.npy':
            raise ValueError('monitor-render output must be .npy')
        values = np.load(args.image, allow_pickle=False)
        if not isinstance(values, np.ndarray) or values.dtype.kind != 'f':
            if hasattr(values, 'close'):
                values.close()
            raise ValueError('monitor-render requires a floating-point .npy RGB/XYZ array')
        result, report = model.evaluate(values, args.source_space)
        buffer = io.BytesIO()
        np.save(buffer, result, allow_pickle=False)
        payload = buffer.getvalue()
        file_encoding = 'unclipped float64 Rec.709 D65 / Gamma 2.4'
    else:
        if output.suffix.lower() != '.png':
            raise ValueError('monitor-preview output must be .png')
        from PIL import Image, ImageOps, ImageCms
        with Image.open(args.image) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            if source.info.get('icc_profile'):
                try:
                    image = ImageCms.profileToProfile(image,
                        ImageCms.ImageCmsProfile(io.BytesIO(source.info['icc_profile'])),
                        ImageCms.createProfile('sRGB'), outputMode='RGB')
                except ImageCms.PyCMSError as error:
                    raise ValueError('invalid source ICC profile') from error
            image.thumbnail((1280, 1280))
            values = np.asarray(image, dtype=np.float64)/255
        result, report = model.evaluate(values, 'srgb')
        payload = png_bytes(result)
        file_encoding = 'sRGB ICC PNG, converted from monitoring 709/Gamma2.4 for viewing'
    config = dict(model.settings(), evaluation=report, file_encoding=file_encoding)
    metadata = (json.dumps(config, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode()
    exclusive_write(output, payload)
    exclusive_write(sidecar, metadata)
    print(json.dumps(dict(output=str(output.resolve()), settings=str(sidecar.resolve()),
                          on_camera_ready=False), indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('inspect', help='validate a .cube without modifying it')
    inspect.add_argument('cube')
    prepare = commands.add_parser('prepare', help='prepare full LUT assets for offline integration')
    prepare.add_argument('cube')
    prepare.add_argument('output', help='new output directory')
    add_settings_args(prepare)
    embed = commands.add_parser('embed', help='embed original .cube/settings into a NEW DNG copy')
    embed.add_argument('cube')
    embed.add_argument('dng')
    embed.add_argument('output')
    add_settings_args(embed)
    embed.add_argument('--render-table', action='store_true', help='also add DNG RGBTables; reader support is unverified')
    embed.add_argument('--divisions', type=int, default=32)
    extract = commands.add_parser('extract', help='recover the exact embedded .cube')
    extract.add_argument('dng')
    extract.add_argument('output')
    preview = commands.add_parser('preview', help='offline sRGB image reference, not camera Live View')
    preview.add_argument('cube')
    preview.add_argument('image')
    preview.add_argument('output', help='new .png file')
    add_settings_args(preview)
    from color import SOURCE_SPACES
    from cinemadng import COLOR_SPACES, GAMMAS
    lib_import=commands.add_parser('library-import',help='import cubes with per-file author/user settings')
    lib_import.add_argument('library');lib_import.add_argument('cubes',nargs='+')
    lib_import.add_argument('--input-space',choices=list(COLOR_SPACES))
    lib_import.add_argument('--input-gamma',choices=list(GAMMAS))
    lib_import.add_argument('--color-matrix',choices=('standard','off','custom'),help="the user's choice; the author's line stays")
    lib_list=commands.add_parser('library-list',help='show filenames, enabled items and per-cube input settings')
    lib_list.add_argument('library')
    lib_recover=commands.add_parser('library-recover',help='merge saved camera BIN settings (by file name; older prepared records by content ID) before rebuilding')
    lib_recover.add_argument('library');lib_recover.add_argument('bin')
    lib_recover.add_argument('--sources',help='an older card\'s LUT/SOURCES folder (v2 records); a v3 record carries its settings')
    lib_set=commands.add_parser('library-set',help='set one cube; other cubes keep their own settings')
    lib_set.add_argument('library');lib_set.add_argument('lut',help='filename or unambiguous content ID prefix')
    lib_set.add_argument('--input-space',choices=list(COLOR_SPACES))
    lib_set.add_argument('--input-gamma',choices=list(GAMMAS))
    lib_set.add_argument('--color-matrix',choices=('standard','off','custom'),
                         help="DNG color matrix the LUT expects; the author's value clears the override")
    lib_set.add_argument('--strength',type=int,choices=(0,25,50,75,100))
    lib_set.add_argument('--enabled',choices=('on','off'))
    lib_set.add_argument('--active',action='store_true')
    commands.add_parser('monitor-presets', help='list monitoring input choices and fixed 709 output')
    for command, description in [
            ('monitor-prepare', 'prepare lookup tables in the selected LUT input domain; not a camera installer'),
            ('monitor-preview', 'preview an sRGB/ICC image through the selected LUT input to 709'),
            ('monitor-render', 'evaluate a declared floating RGB/XYZ source; preserve unclipped 709 output')]:
        sub = commands.add_parser(command, help=description)
        sub.add_argument('cube')
        if command != 'monitor-prepare':
            sub.add_argument('image')
        sub.add_argument('output')
        sub.add_argument('--input-space', required=True, choices=list(COLOR_SPACES))
        sub.add_argument('--input-gamma', required=True, choices=list(GAMMAS),
                         help='independent gamma; Blackmagic has its own restricted list')
        sub.add_argument('--strength', type=float, default=1.)
        sub.add_argument('--exposure', type=float, default=0., help='scene exposure adjustment in EV')
        if command == 'monitor-prepare':
            sub.add_argument('--size', type=int, choices=(17, 33, 65), default=33)
        if command == 'monitor-render':
            sub.add_argument('--source-space', required=True, choices=[*SOURCE_SPACES, 'xyz-d65'])
    args = parser.parse_args(argv)
    try:
        if args.command.startswith('library-'):
            import library
            path=Path(args.library)
            if not path.exists() and args.command!='library-import':raise ValueError('library does not exist')
            document=library.read(path) if path.exists() else library.blank()
            if args.command=='library-import':
                document=library.import_cubes(document,args.cubes,input_space=args.input_space,input_gamma=args.input_gamma,
                                               color_matrix=args.color_matrix)
                library.save(path,document)
            elif args.command=='library-set':
                document=library.configure(document,args.lut,input_space=args.input_space,input_gamma=args.input_gamma,
                      color_matrix=args.color_matrix,
                      strength_percent=args.strength,enabled=None if args.enabled is None else args.enabled=='on',active=args.active)
                library.save(path,document)
            elif args.command=='library-recover':
                document=library.recover(document,Path(args.bin).read_bytes(),sources=args.sources);library.save(path,document)
            print(json.dumps(library.summary(document),ensure_ascii=False,indent=2))
            return 0
        if args.command == 'monitor-presets':
            from monitor import presets
            print(json.dumps(presets(), indent=2, ensure_ascii=False))
            return 0
        if args.command.startswith('monitor-'):
            return monitor_command(args)
        if args.command == 'extract':
            cube, config = Dng(Path(args.dng).read_bytes()).extract()
            exclusive_write(args.output, cube.source)
            print(json.dumps(config, indent=2, ensure_ascii=False))
            return 0
        cube = Cube.read(args.cube)
        if args.command == 'inspect':
            print(json.dumps(cube.summary(), indent=2, ensure_ascii=False))
            return 0
        config = settings(cube, args.name or cube.title or Path(args.cube).stem,
                          args.input_space, args.output_space, args.strength)
        if args.command == 'prepare':
            assets = {'source.cube': cube.source}
            for name, table in (('shaper', cube.table1d), ('cube3d', cube.table3d)):
                if table is not None:
                    import numpy as np
                    with np.errstate(over='ignore'):
                        packed = table.astype('<f4')
                    if not np.isfinite(packed).all():
                        raise ValueError('LUT output exceeds finite float32 integration range')
                    assets[name + '.f32le'] = packed.tobytes()
            config['on_camera_ready'] = False
            config['table_order'] = 'blue outer, green middle, red inner, RGB channel'
            config['assets'] = {name: {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                                for name, value in assets.items()}
            assets['settings.json'] = (json.dumps(config, indent=2, ensure_ascii=False) + '\n').encode()
            out = Path(args.output)
            out.mkdir(parents=True, exist_ok=False)
            for name, content in assets.items():
                exclusive_write(out / name, content)
            print(f'Prepared offline LUT assets: {out.resolve()}')
        elif args.command == 'embed':
            before = Dng(Path(args.dng).read_bytes())
            after = before.embed(cube, config, args.render_table, args.divisions)
            exclusive_write(args.output, after)
            print(json.dumps({'output': str(Path(args.output).resolve()),
                              'image_payload_sha256': before.image_digest(),
                              'cube_sha256': cube.sha256,
                              'rendering': 'RGBTables, reader support unverified' if args.render_table else 'settings only'}, indent=2))
        elif args.command == 'preview':
            if args.input_space != 'srgb' or args.output_space != 'srgb':
                raise ValueError('image preview currently requires an sRGB→sRGB look')
            if Path(args.output).suffix.lower() != '.png':
                raise ValueError('offline preview output must be .png')
            from PIL import Image, ImageOps
            import io
            import numpy as np
            with Image.open(args.image) as source:
                icc = source.info.get('icc_profile')
                if icc:
                    from PIL import ImageCms
                    image = ImageCms.profileToProfile(ImageOps.exif_transpose(source).convert('RGB'),
                                                      ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                                      ImageCms.createProfile('sRGB'), outputMode='RGB')
                else:
                    image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1280, 1280))
                rgb = np.asarray(image, dtype=np.float64) / 255
                graded = np.rint(np.clip(cube.apply(rgb, args.strength), 0, 1) * 255).astype('uint8')
                result = Image.fromarray(graded)
                buffer = io.BytesIO()
                result.save(buffer, format='PNG')
                exclusive_write(args.output, buffer.getvalue())
            print(f'Offline sRGB preview: {Path(args.output).resolve()}')
        return 0
    except (ValueError, OSError, UnicodeError, ET.ParseError, zlib.error) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
