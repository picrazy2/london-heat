"""A PNG writer in forty lines, because the alternative is a dependency.

The site needs exactly two raster images — an apple-touch icon and a social
card — and both are flat rectangles on a solid ground. zlib and struct are in
the standard library, so pulling in Pillow to draw some bars would add an
install step to a build that currently has none.
"""
import struct
import zlib


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


def write(path, w, h, buf):
    raw = b"".join(b"\x00" + bytes(buf[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    hdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", hdr)
                + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def canvas(w, h, hexcol):
    return bytearray(bytes(rgb(hexcol)) * (w * h))


def fill(buf, w, h, x0, y0, x1, y1, col):
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    if x1 <= x0:
        return
    px = bytes(col)
    for y in range(y0, y1):
        buf[(y * w + x0) * 3:(y * w + x1) * 3] = px * (x1 - x0)


def vgrad(buf, w, h, x0, y0, x1, y1, top, bot):
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    span = max(1, y1 - y0)
    for y in range(y0, y1):
        fill(buf, w, h, x0, y, x1, y + 1, lerp(top, bot, (y - y0) / span))


def bar(buf, w, h, x0, x1, y0, y1, col, r=4, round_top=True):
    """A bar with one rounded end; the baseline end stays square."""
    x0, x1, y0, y1 = int(x0), int(x1), int(y0), int(y1)
    if y1 <= y0:
        return
    r = max(0, min(r, (x1 - x0) // 2, y1 - y0))
    for y in range(y0, y1):
        d = (y - y0) if round_top else (y1 - 1 - y)
        inset = r - int((r * r - (r - 1 - d) ** 2) ** 0.5) if d < r else 0
        fill(buf, w, h, x0 + inset, y, x1 - inset, y + 1, col)


def rrect(buf, w, h, x0, y0, x1, y1, col, r=12):
    """A rounded rectangle — the squircle the brand mark and cards are built on."""
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    for y in range(y0, y1):
        dy = min(y - y0, y1 - 1 - y)
        inset = r - int((r * r - (r - 1 - dy) ** 2) ** 0.5) if dy < r else 0
        fill(buf, w, h, x0 + inset, y, x1 - inset, y + 1, col)


# ── a 5x7 bitmap font ───────────────────────────────────────────────────────
# The social card is the first thing anyone sees when a link is shared, and an
# unlabelled chart makes the reader guess which city is which. Rendering text
# means either a font dependency or thirty lines of bitmap, and thirty lines of
# bitmap keeps `python3 build.py` working on a clean machine with nothing
# installed. Uppercase, digits and a little punctuation is all the card needs.
_FONT = {
    "A": "01110100011000111111100011000110001", "B": "11110100011000111110100011000111110",
    "C": "01110100011000010000100001000101110", "D": "11110100011000110001100011000111110",
    "E": "11111100001000011110100001000011111", "F": "11111100001000011110100001000010000",
    "G": "01110100011000010111100011000101111", "H": "10001100011000111111100011000110001",
    "I": "11111001000010000100001000010011111", "J": "00111000010000100001100011000101110",
    "K": "10001100101010011000101001001010001", "L": "10000100001000010000100001000011111",
    "M": "10001110111010110001100011000110001", "N": "10001110011010110011100011000110001",
    "O": "01110100011000110001100011000101110", "P": "11110100011000111110100001000010000",
    "Q": "01110100011000110001101011001001101", "R": "11110100011000111110101001001010001",
    "S": "01111100001000001110000011000111110", "T": "11111001000010000100001000010000100",
    "U": "10001100011000110001100011000101110", "V": "10001100011000110001100010101000100",
    "W": "10001100011000110001101011101110001", "X": "10001100010101000100010101000110001",
    "Y": "10001100010101000100001000010000100", "Z": "11111000010001000100010001000011111",
    "0": "01110100011001110101110011000101110", "1": "00100011000010000100001000010001110",
    "2": "01110100010000100010001000100011111", "3": "11111000100010000010000011000101110",
    "4": "00010001100101010010111110001000010", "5": "11111100001111000001000011000101110",
    "6": "00110010001000011110100011000101110", "7": "11111000010001000100001000010000100",
    "8": "01110100011000101110100011000101110", "9": "01110100011000101111000010001001100",
    ".": "00000000000000000000000000110001100", ",": "00000000000000000000001100011000100",
    "-": "00000000000000001110000000000000000",
    "·": "00000000000110001100000000000000000", "/": "00001000100010001000100010001000000",
    "µ": "00000000001000110001100011001110110", "%": "11001110010001000100010001001100011",
    " ": "00000000000000000000000000000000000",
}


def text(buf, w, h, x, y, s, col, scale=2, tracking=1):
    """Draw `s` at (x, y) with the 5x7 font. Returns the width drawn."""
    cx = x
    for ch in s.upper():
        bits = _FONT.get(ch)
        if bits is None or len(bits) != 35:
            cx += (5 + tracking) * scale
            continue
        for row in range(7):
            for colx in range(5):
                if bits[row * 5 + colx] == "1":
                    fill(buf, w, h, cx + colx * scale, y + row * scale,
                         cx + (colx + 1) * scale, y + (row + 1) * scale, col)
        cx += (5 + tracking) * scale
    return cx - x
