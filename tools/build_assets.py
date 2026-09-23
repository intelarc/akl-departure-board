# Bakes everything the ESP32 can't draw itself into files it can blit:
#   assets/*.fnt       anti-aliased fonts (2 bits/pixel) from the fonts on this PC
#   assets/map.bin     the rail map background (RGB565, 320x240)
#   assets/bus<N>.bin  the bus page background for N lanes (cards, shadows, header)
#   assets/marker<L>.spr  train markers with soft edges, one per line
#   railgeo.py         track geometry for snapping GPS onto the map
#   busart.py          the bus pixel art (from MSMGreen/at-departure-board)
#
#   python tools/build_assets.py      then upload with tools/upload.py
#
# The outputs are built from your own Windows fonts, so they aren't committed.
import os, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import railview as R
from atboard import themes

OUT = os.path.join(ROOT, "assets")
FONTS = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
W, H = 320, 240
AT_BLUE = (35, 94, 168)
PAGE = (226, 236, 247)
NAVY = (26, 39, 68)
INK = (86, 100, 126)
WHITE = (255, 255, 255)
BUS = (0, 150, 214)
EXTRA = "āēīōūĀĒĪŌŪ–·"


def rgb565(c):
    r, g, b = c[:3]
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def to565(img):
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    px = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
    return px.astype(">u2").tobytes()


# ---------- fonts ----------
def build_font(name, ttf, size):
    f = ImageFont.truetype(os.path.join(FONTS, ttf), size)
    ascent, descent = f.getmetrics()
    h = ascent + descent
    chars = [chr(c) for c in range(32, 127)] + list(EXTRA)
    index, blob = [], bytearray()
    for ch in chars:
        adv = max(1, int(round(f.getlength(ch))))
        img = Image.new("L", (adv + 2, h), 0)
        ImageDraw.Draw(img).text((0, ascent), ch, font=f, fill=255, anchor="ls")
        a = np.asarray(img)[:, :adv]
        lv = (a.astype(np.uint16) * 3 + 127) // 255          # 0..3
        stride = (adv + 3) // 4
        rows = bytearray(stride * h)
        for y in range(h):
            for x in range(adv):
                if lv[y, x]:
                    rows[y * stride + x // 4] |= int(lv[y, x]) << ((3 - x % 4) * 2)
        index.append((ord(ch), adv, len(blob)))
        blob += rows
    with open(os.path.join(OUT, name + ".fnt"), "wb") as fh:
        fh.write(b"F2" + struct.pack(">BBH", h, ascent, len(index)))
        for code, adv, off in index:
            fh.write(struct.pack(">HBI", code, adv, off))
        fh.write(blob)
    return len(blob)


# ---------- rail map ----------
def _mute(c, f=0.28):
    return tuple(int(v + (255 - v) * f) for v in c)


def build_map():
    # tone the lines down a little so the train markers read clearly on top
    full = [l[2] for l in R.LINES]
    for i, l in enumerate(R.LINES):
        R.LINES[i] = (l[0], l[1], _mute(l[2]), l[3])
    img = R._static()
    for i, l in enumerate(R.LINES):
        R.LINES[i] = (l[0], l[1], full[i], l[3])
    d = ImageDraw.Draw(img)
    # header bar (the board adds the clock)
    d.rectangle((0, 0, W, R.HEAD_H), fill=AT_BLUE)
    d.text((7, R.HEAD_H / 2), "Ngā Tereina", font=R.font("arialbd.ttf", 12), fill=WHITE, anchor="lm")
    d.text((82, R.HEAD_H / 2 + 1), "Trains", font=R.font("arial.ttf", 10),
           fill=(190, 212, 240), anchor="lm")
    # legend card (the board adds the counts)
    x0, y0, x1, y1 = 5, 180, 122, 236
    sh = Image.new("L", img.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((x0 + 1, y0 + 2, x1 + 1, y1 + 2), radius=6, fill=80)
    img.paste((140, 158, 186), (0, 0), sh.filter(ImageFilter.GaussianBlur(2)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=WHITE)
    for i, li in enumerate((R.SC, R.EW, R.OW)):
        code, name, col, _ = R.LINES[li]
        y = y0 + 9 + i * 13
        d.rounded_rectangle((x0 + 5, y - 5, x0 + 29, y + 5), radius=5, fill=col)
        d.text((x0 + 17, y), code, font=R.font("arialbd.ttf", 8), fill=WHITE, anchor="mm")
        d.text((x0 + 34, y), name, font=R.font("arial.ttf", 8), fill=INK, anchor="lm")
    img.save(os.path.join(OUT, "map-preview.png"))
    open(os.path.join(OUT, "map.bin"), "wb").write(to565(img))


MARK = 15          # train marker size (px)


def build_markers():
    for li, l in enumerate(R.LINES):
        k = 8
        big = Image.new("RGBA", (MARK * k, MARK * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        c = MARK * k / 2
        for r, fill in ((6.9, (20, 30, 56)), (5.6, WHITE), (3.9, l[2])):
            d.ellipse((c - r * k, c - r * k, c + r * k, c + r * k), fill=fill)
        img = big.resize((MARK, MARK), Image.LANCZOS)
        a = np.asarray(img)
        out = bytearray()
        for y in range(MARK):
            for x in range(MARK):
                r, g, b, al = (int(v) for v in a[y, x])
                lv = (al * 3 + 127) // 255
                out += struct.pack(">HB", rgb565((r, g, b)) if lv else 0, lv)
        open(os.path.join(OUT, "marker%d.spr" % li), "wb").write(out)


def build_railgeo():
    lines = ["# generated by tools/build_assets.py -- track geometry for the board",
             "MARK = %d" % MARK,
             "COLOURS = %r" % [rgb565(l[2]) for l in R.LINES],
             "IDS = %r" % R.LINE_IDS,
             "# (line, ((x, y), ...), lat0, lon0, lat1, lon1)",
             "SEGS = ("]
    for li, a, b, poly, (la0, lo0), (la1, lo1) in R.SEGS:
        pts = tuple((round(x, 1), round(y, 1)) for x, y in poly)
        lines.append("    (%d, %r, %.5f, %.5f, %.5f, %.5f)," % (li, pts, la0, lo0, la1, lo1))
    lines.append(")")
    open(os.path.join(ROOT, "railgeo.py"), "w").write("\n".join(lines) + "\n")


# ---------- bus page ----------
HEAD_H = 22


def lane_boxes(n):
    gap = 6
    top = HEAD_H + gap
    ch = (H - top - gap * n) // n
    return [(6, top + i * (ch + gap), W - 6, top + i * (ch + gap) + ch) for i in range(n)]


def build_bus_pages():
    for n in range(1, 5):
        img = Image.new("RGB", (W, H), PAGE)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, HEAD_H), fill=AT_BLUE)
        for box in lane_boxes(n):
            sh = Image.new("L", img.size, 0)
            x0, y0, x1, y1 = box
            ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 2, x1, y1 + 3), radius=9, fill=90)
            img.paste((150, 166, 196), (0, 0), sh.filter(ImageFilter.GaussianBlur(3)))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle(box, radius=9, fill=WHITE)
        open(os.path.join(OUT, "bus%d.bin" % n), "wb").write(to565(img))


def build_busart():
    th = themes.get("transit")
    out = ["# generated by tools/build_assets.py -- bus pixel art from",
           "# MSMGreen/at-departure-board (MIT), as packed colour runs: x, y, len (u8), rgb565 (u16)"]
    for size in ("large", "compact"):
        spr = th.sprite(size, "bus")
        colours = th.role_colours(BUS)
        runs = []
        for y, row in enumerate(spr.rows):
            x = 0
            while x < spr.width:
                role = row[x]
                k = x
                while k < spr.width and row[k] == role:
                    k += 1
                if role in colours:
                    runs.append((x, y, k - x, rgb565(colours[role])))
                x = k
        packed = b"".join(struct.pack(">BBBH", x, y, n, c) for x, y, n, c in runs)
        out.append("%s = (%d, %d, %r)" % (size.upper(), spr.width, spr.height, packed))
    open(os.path.join(ROOT, "busart.py"), "w").write("\n".join(out) + "\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    sizes = {}
    for name, ttf, px in (("big", "arialbd.ttf", 24), ("clock", "arialbd.ttf", 14),
                          ("title", "arialbd.ttf", 13), ("head", "arialbd.ttf", 11),
                          ("small", "arial.ttf", 9), ("smallb", "arialbd.ttf", 9)):
        sizes[name] = build_font(name, ttf, px)
    build_map()
    build_markers()
    build_railgeo()
    build_bus_pages()
    build_busart()
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if not f.endswith(".png"))
    print("fonts:", sizes)
    print("assets: %d files, %.0f KB" % (len(os.listdir(OUT)), total / 1024))


if __name__ == "__main__":
    main()
