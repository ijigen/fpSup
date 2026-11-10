"""Strict, dependency-free verifier for pristine QR Model 2 V5-L byte symbols.

This is NOT an optical decoder: no finder search in photos, perspective/rotation
handling, thresholding, BCH repair or Reed-Solomon correction. It verifies the
integer-scaled black/white matrices produced by the offline QS harness. OpenCV
remains an optional independent image decoder and phone scanning is unverified.

QR layout cross-check: Project Nayuki's primary reference implementation:
https://www.nayuki.io/page/qr-code-generator-library
https://github.com/nayuki/QR-Code-generator/blob/master/python/qrcodegen.py
The RS check below evaluates 26 syndromes, independently of slqs.c's generator
polynomial construction and encoder remainder algorithm.
"""

N = 37
DATA_WORDS = 108
EC_WORDS = 26
FORMAT_L = (0x77C4, 0x72F3, 0x7DAA, 0x789D, 0x662F, 0x6318, 0x6C41, 0x6976)
FORMAT_A = ([(8, y) for y in range(6)] + [(8, 7), (8, 8), (7, 8)]
            + [(x, 8) for x in range(5, -1, -1)])
FORMAT_B = [(x, 8) for x in range(36, 28, -1)] + [(8, y) for y in range(30, 37)]


def function_modules():
    """Expected fixed patterns, with None at the two format-bit copies."""
    fixed = {}
    for ox, oy in ((0, 0), (30, 0), (0, 30)):
        for y in range(max(0, oy - 1), min(N, oy + 8)):
            for x in range(max(0, ox - 1), min(N, ox + 8)):
                dx, dy = x - ox, y - oy
                fixed[x, y] = (0 <= dx <= 6 and 0 <= dy <= 6
                               and (dx in (0, 6) or dy in (0, 6)
                                    or (2 <= dx <= 4 and 2 <= dy <= 4)))
    for k in range(8, 29):
        fixed[6, k] = fixed[k, 6] = k % 2 == 0
    for y in range(28, 33):
        for x in range(28, 33):
            fixed[x, y] = x in (28, 32) or y in (28, 32) or (x, y) == (30, 30)
    for xy in FORMAT_A + FORMAT_B:
        fixed[xy] = None
    fixed[8, 29] = True
    return fixed


def data_coordinates():
    fixed = function_modules()
    right, upward = 36, True
    while right > 0:
        if right == 6:
            right -= 1
        rows = range(36, -1, -1) if upward else range(37)
        for y in rows:
            for x in (right, right - 1):
                if (x, y) not in fixed:
                    yield x, y
        right -= 2
        upward = not upward


def mask_at(mask, x, y):
    return ((x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0,
            (x // 3 + y // 2) % 2 == 0, x * y % 2 + x * y % 3 == 0,
            (x * y % 2 + x * y % 3) % 2 == 0,
            ((x + y) % 2 + x * y % 3) % 2 == 0)[mask]


def _gf_tables():
    exp, log, value = [], [0] * 256, 1
    for power in range(255):
        exp.append(value)
        log[value] = power
        value <<= 1
        if value & 256:
            value ^= 0x11D
    return exp * 2, log


EXP, LOG = _gf_tables()


def syndromes(words):
    out = []
    for power in range(EC_WORDS):
        acc = 0
        for word in words:
            acc = (EXP[LOG[acc] + power] if acc else 0) ^ word
        out.append(acc)
    return out


def decode_modules(matrix):
    """Return bytes and selected mask, rejecting any non-canonical pristine code."""
    m = [list(row) for row in matrix]
    if len(m) != N or any(len(row) != N for row in m):
        raise ValueError('expected a 37 x 37 V5 matrix')
    if any(v not in (0, 1, False, True) for row in m for v in row):
        raise ValueError('modules must be boolean/dark=1')
    for (x, y), want in function_modules().items():
        if want is not None and bool(m[y][x]) != want:
            raise ValueError(f'fixed QR pattern differs at {x},{y}')
    fmt = [sum(int(bool(m[y][x])) << bit for bit, (x, y) in enumerate(coords))
           for coords in (FORMAT_A, FORMAT_B)]
    if fmt[0] != fmt[1] or fmt[0] not in FORMAT_L:
        raise ValueError('format copies must agree exactly and declare ECC L')
    mask = FORMAT_L.index(fmt[0])
    bits = [int(bool(m[y][x]) ^ mask_at(mask, x, y)) for x, y in data_coordinates()]
    if len(bits) != 1079 or any(bits[1072:]):
        raise ValueError('incorrect V5 data length or remainder bits')
    words = bytes(sum(bits[i + j] << (7 - j) for j in range(8)) for i in range(0, 1072, 8))
    if any(syndromes(words)):
        raise ValueError('nonzero Reed-Solomon syndrome')
    data = bits[:DATA_WORDS * 8]
    number = lambda pos, size: sum(data[pos + j] << (size - 1 - j) for j in range(size))
    if number(0, 4) != 4:
        raise ValueError('expected one byte-mode segment')
    count = number(4, 8)
    if count > 106:
        raise ValueError('byte count exceeds V5-L capacity')
    payload = bytes(number(12 + 8 * i, 8) for i in range(count))
    end = 12 + count * 8
    if any(data[end:end + 4]):
        raise ValueError('nonzero byte-mode terminator')
    pad_start = (end + 4 + 7) // 8
    if any(data[end + 4:pad_start * 8]):
        raise ValueError('nonzero byte alignment padding')
    if words[pad_start:DATA_WORDS] != bytes((0xEC, 0x11)[i % 2] for i in range(DATA_WORDS - pad_start)):
        raise ValueError('non-canonical byte padding')
    return payload, mask


def decode_pristine_image(gray):
    """Read a binary, upright, integer-scaled V5 matrix with a white border.

    The border width is not a scan-quality assertion; the display test checks
    its separately specified quiet-zone geometry. No image library is needed.
    """
    rows = [list(row) for row in gray]
    if not rows or not rows[0] or any(len(r) != len(rows[0]) for r in rows):
        raise ValueError('expected a rectangular image')
    if any(v not in (0, 255) for row in rows for v in row):
        raise ValueError('only pristine black/white images are supported')
    black = [(x, y) for y, row in enumerate(rows) for x, v in enumerate(row) if v == 0]
    if not black:
        raise ValueError('no dark modules')
    left, right = min(x for x, _ in black), max(x for x, _ in black)
    top, bottom = min(y for _, y in black), max(y for _, y in black)
    width, height = right - left + 1, bottom - top + 1
    if width != height or width % N:
        raise ValueError('not an integer-scaled square V5 matrix')
    scale = width // N
    m = [[rows[top + y * scale][left + x * scale] == 0 for x in range(N)] for y in range(N)]
    for y in range(height):
        for x in range(width):
            if (rows[top + y][left + x] == 0) != m[y // scale][x // scale]:
                raise ValueError('nonuniform module pixels')
    return decode_modules(m)[0].decode('utf-8')
