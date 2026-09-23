# Drawing on the board: an RGB565 canvas in RAM (so nothing flickers while
# it's being composed), anti-aliased text from the baked fonts, soft-edged
# train markers, and blitting slices of the baked backgrounds from flash.
#
# Canvas bytes are stored big-endian, the way the ST7789 wants them. The
# framebuf module writes little-endian, so colours handed to it are
# byte-swapped first (sw()).
import framebuf, struct, micropython

W, H = 320, 240


def rgb(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def sw(c):
    return ((c & 0xFF) << 8) | (c >> 8)


class Canvas:
    def __init__(self, buf, w, h):
        self.buf, self.w, self.h = buf, w, h
        self.fb = framebuf.FrameBuffer(buf, w, h, framebuf.RGB565)

    def fill(self, c):
        self.fb.fill(sw(c))

    def rect(self, x, y, w, h, c):
        self.fb.fill_rect(x, y, w, h, sw(c))

    def rrect(self, x, y, w, h, r, c):
        """Filled rounded rectangle."""
        c = sw(c)
        fb = self.fb
        fb.fill_rect(x + r, y, w - 2 * r, h, c)
        fb.fill_rect(x, y + r, w, h - 2 * r, c)
        for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r),
                       (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
            fb.ellipse(cx, cy, r, r, c, True)

    def ellipse(self, x, y, rx, ry, c):
        self.fb.ellipse(x, y, rx, ry, sw(c), True)

    def text(self, font, s, x, y, c):
        """Draw s with its top-left at (x, y); returns the x after it."""
        return font.draw(self, s, x, y, c)


class View:
    """A canvas that's a window onto a bigger shared buffer."""
    def __init__(self, pool, w, h):
        self.c = Canvas(memoryview(pool)[:w * h * 2], w, h)


# ---------- anti-aliased text ----------
@micropython.viper
def _glyph(dst: ptr8, dw: int, dh: int, x0: int, y0: int,
           src: ptr8, off: int, gw: int, gh: int, fr: int, fg: int, fb: int):
    # blend each 2-bit coverage level over what's already in the canvas
    stride = (gw + 3) >> 2
    for y in range(gh):
        yy = y0 + y
        if yy < 0 or yy >= dh:
            continue
        row = off + y * stride
        for x in range(gw):
            lv = (src[row + (x >> 2)] >> ((3 - (x & 3)) << 1)) & 3
            if lv == 0:
                continue
            xx = x0 + x
            if xx < 0 or xx >= dw:
                continue
            p = (yy * dw + xx) << 1
            r = fr
            g = fg
            b = fb
            if lv != 3:
                c = (dst[p] << 8) | dst[p + 1]
                br = c >> 11
                bg = (c >> 5) & 63
                bb = c & 31
                # mix = bg + (fg - bg) * lv / 3   (x/3 ~= x*85 >> 8)
                r = br + (((fr - br) * lv * 85) >> 8)
                g = bg + (((fg - bg) * lv * 85) >> 8)
                b = bb + (((fb - bb) * lv * 85) >> 8)
            v = (r << 11) | (g << 5) | b
            dst[p] = v >> 8
            dst[p + 1] = v & 0xFF


class Font:
    # Only the index lives in RAM; each glyph's pixels are read from flash
    # when it's drawn (text changes rarely, and RAM is tight).
    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(6)
        self.h, self.ascent, n = struct.unpack(">BBH", hdr[2:])
        idx = self.f.read(n * 7)
        self.base = 6 + n * 7
        self.map = {}
        for i in range(n):
            code, adv, off = struct.unpack_from(">HBI", idx, i * 7)
            self.map[code] = (adv, off)
        self.gbuf = bytearray(((max(a for a, _ in self.map.values()) + 3) // 4) * self.h)

    def width(self, s):
        m = self.map
        return sum(m.get(ord(ch), (4, 0))[0] for ch in s)

    def draw(self, cv, s, x, y, c):
        fr, fg, fb = c >> 11, (c >> 5) & 63, c & 31
        m, h, f, g = self.map, self.h, self.f, self.gbuf
        mv = memoryview(g)
        for ch in s:
            e = m.get(ord(ch))
            if e is None:
                x += 4
                continue
            adv, off = e
            f.seek(self.base + off)
            f.readinto(mv[:((adv + 3) // 4) * h])
            _glyph(cv.buf, cv.w, cv.h, x, y, g, 0, adv, h, fr, fg, fb)
            x += adv
        return x


# ---------- baked backgrounds and markers ----------
def bg_rect(path, cv, x, y, w=None, h=None):
    """Fill a canvas with the (x, y) slice of a 320-wide baked background."""
    w, h = w or cv.w, h or cv.h
    mv = memoryview(cv.buf)
    with open(path, "rb") as f:
        for r in range(h):
            f.seek(((y + r) * W + x) * 2)
            f.readinto(mv[r * cv.w * 2:(r * cv.w + w) * 2])


def stream_bg(tft, path, pool):
    """Paint a whole baked background onto the panel, a band at a time."""
    rows = len(pool) // (W * 2)
    mv = memoryview(pool)
    with open(path, "rb") as f:
        y = 0
        while y < H:
            n = min(rows, H - y)
            f.readinto(mv[:n * W * 2])
            tft.blit(mv[:n * W * 2], 0, y, W, n)
            y += n


@micropython.viper
def _sprite(dst: ptr8, dw: int, dh: int, x0: int, y0: int, src: ptr8, sw_: int, sh_: int):
    # src: per pixel (rgb565 hi, lo, alpha 0..3)
    for y in range(sh_):
        yy = y0 + y
        if yy < 0 or yy >= dh:
            continue
        for x in range(sw_):
            xx = x0 + x
            if xx < 0 or xx >= dw:
                continue
            s = (y * sw_ + x) * 3
            a = src[s + 2]
            if a == 0:
                continue
            p = (yy * dw + xx) << 1
            if a == 3:
                dst[p] = src[s]
                dst[p + 1] = src[s + 1]
                continue
            fc = (src[s] << 8) | src[s + 1]
            bc = (dst[p] << 8) | dst[p + 1]
            fr = fc >> 11
            fg = (fc >> 5) & 63
            fb = fc & 31
            br = bc >> 11
            bg = (bc >> 5) & 63
            bb = bc & 31
            r = br + (((fr - br) * a * 85) >> 8)
            g = bg + (((fg - bg) * a * 85) >> 8)
            b = bb + (((fb - bb) * a * 85) >> 8)
            v = (r << 11) | (g << 5) | b
            dst[p] = v >> 8
            dst[p + 1] = v & 0xFF


class Sprite:
    def __init__(self, path, w, h):
        self.data = open(path, "rb").read()
        self.w, self.h = w, h

    def draw(self, cv, x, y):
        _sprite(cv.buf, cv.w, cv.h, x, y, self.data, self.w, self.h)


def runs(cv, art, x, y, lift=0):
    """Draw pixel art stored as packed colour runs (busart.py), bottom-left at (x, y)."""
    w, h, rs = art
    top = y - h - lift
    fb = cv.fb
    for i in range(0, len(rs), 5):
        # the colour is stored big-endian, which is already the swapped form
        fb.hline(x + rs[i], top + rs[i + 1], rs[i + 2], rs[i + 3] | (rs[i + 4] << 8))
