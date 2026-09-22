# Live Auckland rail map in the style of AT's official post-CRL network map
# ("Nga Tereina"): light land/harbour background, the red City Rail Link loop,
# green and blue running side by side out west, every train as a moving dot.
# Rendered on the PC with Pillow.
import json, math, os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 320, 240
SS = 4                       # supersampling for smooth lines
HEAD_H = 20

# ---------- palette (taken from AT's network map) ----------
AT_BLUE = (35, 94, 168)
WATER = (205, 225, 243)
LAND = (250, 251, 253)
CONE = (232, 236, 242)
NAVY = (26, 39, 68)
INK = (70, 84, 110)
WHITE = (255, 255, 255)
LIVE = (76, 199, 106)
WARN = (245, 166, 35)

LINES = [   # id, name, colour (AT's), station order (AT's longest trip pattern)
    ("E-W", "East West", (0x8C, 0xC6, 0x3F), [
        "Swanson", "Ranui", "Sturges Rd", "Henderson", "Sunnyvale", "Glen Eden",
        "Fruitvale", "New Lynn", "Avondale", "Mt Albert", "Baldwin Ave",
        "Morningside", "Kingsland", "Maungawhau", "Karanga-a-Hape",
        "Te Waihorotiu", "Waitemata", "Orakei", "Meadowbank", "Glen Innes",
        "Panmure", "Sylvia Park", "Otahuhu", "Middlemore", "Papatoetoe",
        "Puhinui", "Manukau"]),
    ("S-C", "South City", (0xDA, 0x29, 0x1C), [
        "Pukekohe", "Paerata", "Drury", "Papakura", "Takaanini", "Te Mahia",
        "Manurewa", "Homai", "Puhinui", "Papatoetoe", "Middlemore", "Otahuhu",
        "Penrose", "Ellerslie", "Greenlane", "Remuera", "Newmarket", "Grafton",
        "Karanga-a-Hape", "Te Waihorotiu", "Waitemata", "Parnell", "Newmarket"]),
    ("O-W", "Onehunga West", (0x1D, 0x9B, 0xD7), [
        "Onehunga", "Te Papapa", "Penrose", "Ellerslie", "Greenlane", "Remuera",
        "Newmarket", "Grafton", "Maungawhau", "Kingsland", "Morningside",
        "Baldwin Ave", "Mt Albert", "Avondale", "New Lynn", "Fruitvale",
        "Glen Eden", "Sunnyvale", "Henderson"]),
]
LINE_IDS = [l[0] for l in LINES]
EW, SC, OW = 0, 1, 2

# ---------- corridors: centre-lines of shared track, in screen px ----------
# Names starting with "_" are bends, not stations.
CORRIDORS = {
    "W1": [("Swanson", 20, 54), ("Ranui", 20, 67), ("Sturges Rd", 20, 80),
           ("Henderson", 20, 94)],
    "W2": [("Henderson", 20, 94), ("Sunnyvale", 34, 108), ("Glen Eden", 48, 122),
           ("Fruitvale", 63, 122), ("New Lynn", 78, 122), ("Avondale", 92, 122),
           ("Mt Albert", 106, 122), ("Baldwin Ave", 114.5, 113.5),
           ("Morningside", 123, 105), ("Kingsland", 131.5, 96.5), ("Maungawhau", 140, 88)],
    "CRLM": [("Maungawhau", 140, 88), ("Karanga-a-Hape", 158, 70)],
    "CRLT": [("Karanga-a-Hape", 158, 70), ("Te Waihorotiu", 158, 53), ("_NW", 158, 38),
             ("Waitemata", 186, 38)],
    "TOP": [("Waitemata", 186, 38), ("_NE", 216, 38)],
    "RIGHT": [("_NE", 216, 38), ("Parnell", 216, 62), ("Newmarket", 216, 88)],
    "BOTTOM": [("Newmarket", 216, 88), ("Grafton", 188, 88)],
    "LOOPL": [("Grafton", 188, 88), ("_SW", 158, 88), ("Karanga-a-Hape", 158, 70)],
    "MID": [("Grafton", 188, 88), ("Maungawhau", 140, 88)],
    "EAST": [("_NE", 216, 38), ("Orakei", 240, 38), ("Meadowbank", 264, 38),
             ("_E1", 294, 38), ("Glen Innes", 294, 62), ("Panmure", 294, 86),
             ("Sylvia Park", 294, 112), ("_E2", 268, 138), ("Otahuhu", 268, 142)],
    "SOUTH": [("Newmarket", 216, 88), ("Remuera", 226, 98), ("Greenlane", 236, 108),
              ("Ellerslie", 246, 118), ("Penrose", 256, 128)],
    "SOUTH2": [("Penrose", 256, 128), ("Otahuhu", 268, 142)],
    "ONE": [("Penrose", 256, 128), ("Te Papapa", 246, 138), ("Onehunga", 236, 148)],
    "TAIL": [("Otahuhu", 268, 142), ("Middlemore", 268, 153), ("Papatoetoe", 268, 164),
             ("Puhinui", 268, 175)],
    "STAIL": [("Puhinui", 268, 175), ("Homai", 268, 183), ("Manurewa", 268, 190),
              ("Te Mahia", 268, 197), ("Takaanini", 268, 204), ("Papakura", 268, 211),
              ("Drury", 268, 218), ("Paerata", 268, 225), ("Pukekohe", 268, 233)],
    "MNK": [("Puhinui", 268, 175), ("Manukau", 292, 199)],
}
# each line: (corridor, from, to, lane). Lane = offset to the LEFT of the
# corridor's own drawing direction, so it is the same whichever way a line runs.
L = 2.1
ROUTES = {
    EW: [("W1", "Swanson", "Henderson", 0), ("W2", "Henderson", "Maungawhau", L),
         ("CRLM", "Maungawhau", "Karanga-a-Hape", L),
         ("CRLT", "Karanga-a-Hape", "Waitemata", L), ("TOP", "Waitemata", "_NE", L),
         ("EAST", "_NE", "Otahuhu", L), ("TAIL", "Otahuhu", "Puhinui", L),
         ("MNK", "Puhinui", "Manukau", L)],
    SC: [("STAIL", "Pukekohe", "Puhinui", -L), ("TAIL", "Puhinui", "Otahuhu", -L),
         ("SOUTH2", "Otahuhu", "Penrose", L), ("SOUTH", "Penrose", "Newmarket", L),
         ("BOTTOM", "Newmarket", "Grafton", -L), ("LOOPL", "Grafton", "Karanga-a-Hape", -L),
         ("CRLT", "Karanga-a-Hape", "Waitemata", -L), ("TOP", "Waitemata", "_NE", -L),
         ("RIGHT", "_NE", "Newmarket", -L)],
    OW: [("ONE", "Onehunga", "Penrose", 0), ("SOUTH", "Penrose", "Newmarket", -L),
         ("BOTTOM", "Newmarket", "Grafton", L), ("MID", "Grafton", "Maungawhau", L),
         ("W2", "Maungawhau", "Henderson", -L)],
}
CRL = ("Waitemata", "Te Waihorotiu", "Karanga-a-Hape", "Maungawhau")

# label text, offset from the station, PIL anchor
LABELS = {
    "Swanson": ("Swanson", (6, 0), "lm"),
    "Henderson": ("Henderson", (6, -1), "lm"),
    "New Lynn": ("New Lynn", (0, 7), "mt"),
    "Mt Albert": ("Mt Albert", (3, 7), "lt"),
    "Kingsland": ("Kingsland", (-6, 1), "rm"),
    "Maungawhau": ("Maungawhau", (-7, -3), "rm"),
    "Karanga-a-Hape": ("Karanga-a-Hape", (-7, 0), "rm"),
    "Te Waihorotiu": ("Te Waihorotiu", (-7, 0), "rm"),
    "Waitemata": ("Waitematā", (0, -7), "mb"),
    "Parnell": ("Parnell", (-7, 0), "rm"),
    "Grafton": ("Grafton", (0, 7), "mt"),
    "Newmarket": ("Newmarket", (6, -3), "lm"),
    "Orakei": ("Ōrākei", (0, -7), "mb"),
    "Meadowbank": ("Meadowbank", (0, 7), "mt"),
    "Glen Innes": ("Glen Innes", (-6, 0), "rm"),
    "Sylvia Park": ("Sylvia Park", (-6, -4), "rb"),
    "Penrose": ("Penrose", (-6, 1), "rm"),
    "Onehunga": ("Onehunga", (-6, 0), "rm"),
    "Otahuhu": ("Ōtāhuhu", (7, 0), "lm"),
    "Puhinui": ("Puhinui", (-7, 0), "rm"),
    "Manukau": ("Manukau", (0, 7), "mt"),
    "Papakura": ("Papakura", (-7, 0), "rm"),
    "Pukekohe": ("Pukekohe", (-7, 0), "rm"),
}

_FONTS = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
_fc = {}


def font(name, size):
    if (name, size) not in _fc:
        try:
            _fc[name, size] = ImageFont.truetype(os.path.join(_FONTS, name), size)
        except OSError:
            _fc[name, size] = ImageFont.load_default()
    return _fc[name, size]


# ---------- geometry ----------
def _offset(pts, d):
    """Offset a polyline d px to the left of its direction, mitred corners."""
    if d == 0:
        return list(pts)
    out = []
    for i, (x, y) in enumerate(pts):
        segs = []
        if i > 0:
            segs.append((pts[i - 1], pts[i]))
        if i + 1 < len(pts):
            segs.append((pts[i], pts[i + 1]))
        ns = []
        for (ax, ay), (bx, by) in segs:
            ln = math.hypot(bx - ax, by - ay)
            ns.append(((by - ay) / ln, -(bx - ax) / ln))
        nx = sum(n[0] for n in ns) / len(ns)
        ny = sum(n[1] for n in ns) / len(ns)
        k = math.hypot(nx, ny)
        nx, ny = nx / k, ny / k
        cos = nx * ns[0][0] + ny * ns[0][1]
        out.append((x + nx * d / cos, y + ny * d / cos))
    return out


def _sub(corr, a, b):
    """Named points of a corridor from a to b (either direction)."""
    pts = CORRIDORS[corr]
    names = [p[0] for p in pts]
    i, j = names.index(a), names.index(b)
    return (pts[i:j + 1], False) if i <= j else (pts[j:i + 1], True)


def _build():
    real = json.load(open(os.path.join(HERE, "tools", "stations.json")))
    lines = {}           # line -> [(name, x, y)] along its route
    for li, legs in ROUTES.items():
        path = []
        for corr, a, b, lane in legs:
            pts, rev = _sub(corr, a, b)
            off = _offset([(x, y) for _, x, y in pts], lane)
            leg = [(n, x, y) for (n, _, _), (x, y) in zip(pts, off)]
            if rev:
                leg.reverse()
            if path and path[-1][0] == leg[0][0]:
                path.pop()           # the join point: keep the new leg's copy
            path.extend(leg)
        lines[li] = path
    stations = {}        # station -> [(x, y)] of every line serving it
    for li, path in lines.items():
        for n, x, y in path:
            if not n.startswith("_"):
                stations.setdefault(n, []).append((x, y))
    # per line, the polyline between consecutive stations plus the real
    # coordinates of both ends (for snapping GPS onto it)
    segs = []
    for li, path in lines.items():
        cur = None
        for n, x, y in path:
            if cur is None:
                cur = [n, [(x, y)]]
                continue
            cur[1].append((x, y))
            if not n.startswith("_"):
                segs.append((li, cur[0], n, cur[1], real[cur[0]], real[n]))
                cur = [n, [(x, y)]]
    return lines, stations, segs


LINE_PATHS, STATIONS, SEGS = _build()


def _fillet(pts, r):
    """Round the corners of a polyline with radius r (drawing only)."""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        (ax, ay), (bx, by), (cx, cy) = pts[i - 1], pts[i], pts[i + 1]
        v1, v2 = (ax - bx, ay - by), (cx - bx, cy - by)
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        u1, u2 = (v1[0] / l1, v1[1] / l1), (v2[0] / l2, v2[1] / l2)
        ang = math.acos(max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1])))
        if ang > math.radians(175):
            out.append((bx, by))
            continue
        t = min(r / math.tan(ang / 2), l1 / 2, l2 / 2)
        p1 = (bx + u1[0] * t, by + u1[1] * t)
        p2 = (bx + u2[0] * t, by + u2[1] * t)
        for k in range(9):                        # quadratic bezier through the bend
            s = k / 8
            out.append(((1 - s) ** 2 * p1[0] + 2 * (1 - s) * s * bx + s * s * p2[0],
                        (1 - s) ** 2 * p1[1] + 2 * (1 - s) * s * by + s * s * p2[1]))
    out.append(pts[-1])
    return out


# ---------- the static map ----------
def _background():
    img = Image.new("RGB", (W * SS, H * SS), WATER)
    d = ImageDraw.Draw(img)
    S = lambda pts: [(x * SS, y * SS) for x, y in pts]
    # stylised land, like the soft blocks on AT's map
    land = [(0, 46), (110, 46), (140, 28), (330, 28), (330, 250), (206, 250),
            (190, 200), (150, 178), (96, 170), (40, 186), (0, 176)]
    d.polygon(S(land), fill=LAND)
    d.rounded_rectangle(S([(-10, 48), (60, 152)]), radius=18 * SS, fill=LAND)
    # Tamaki estuary and Manukau harbour inlets
    d.polygon(S([(300, 60), (330, 50), (330, 150), (310, 124), (304, 90)]), fill=WATER)
    d.polygon(S([(170, 250), (180, 186), (214, 170), (232, 182), (236, 250)]), fill=WATER)
    # volcanic cones, as soft circles (Maungawhau, Maungakiekie, ...)
    for cx, cy, r in ((150, 104, 9), (218, 138, 10), (110, 104, 6), (246, 72, 7),
                      (190, 116, 6), (286, 162, 8), (56, 150, 7), (232, 58, 5)):
        d.ellipse(S([(cx - r, cy - r), (cx + r, cy + r)]), fill=CONE)
    return img


def _static():
    img = _background()
    d = ImageDraw.Draw(img)
    lw = 3.6 * SS
    # City Rail Link: a warm glow under the loop
    halo = Image.new("L", img.size, 0)
    crl = [(158, 70), (158, 38), (216, 38), (216, 88), (158, 88), (158, 70)]
    ImageDraw.Draw(halo).line([(x * SS, y * SS) for x, y in _fillet(crl, 7)], fill=255,
                              width=int(13 * SS), joint="curve")
    halo = halo.filter(ImageFilter.GaussianBlur(3 * SS)).point(lambda v: int(v * 0.55))
    img.paste(Image.new("RGB", img.size, (255, 222, 150)), (0, 0), halo)
    # lines: E-W, O-W, then S-C on top (as on AT's map)
    for li in (EW, OW, SC):
        pts = [(x, y) for _, x, y in LINE_PATHS[li]]
        d.line([(x * SS, y * SS) for x, y in _fillet(pts, 6)], fill=LINES[li][2],
               width=int(lw), joint="curve")
        for x, y in (pts[0], pts[-1]):             # rounded ends
            d.ellipse(((x - 1.8) * SS, (y - 1.8) * SS, (x + 1.8) * SS, (y + 1.8) * SS),
                      fill=LINES[li][2])
    # stations: white pills across interchanges, small rings elsewhere
    for n, pts in STATIONS.items():
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if len(pts) > 1 or n in CRL:
            r = 2.9
            d.rounded_rectangle(((min(xs) - r) * SS, (min(ys) - r) * SS,
                                 (max(xs) + r) * SS, (max(ys) + r) * SS),
                                radius=r * SS, fill=WHITE, outline=NAVY, width=int(0.9 * SS))
        else:
            x, y = pts[0]
            r = 1.9
            d.ellipse(((x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS), fill=WHITE,
                      outline=NAVY, width=int(0.7 * SS))
    img = img.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    for n, (text, (dx, dy), anchor) in LABELS.items():
        pts = STATIONS[n]
        x = sum(p[0] for p in pts) / len(pts)
        y = sum(p[1] for p in pts) / len(pts)
        bold = n in CRL
        d.text((x + dx, y + dy), text, anchor=anchor,
               font=font("arialbd.ttf" if bold else "arial.ttf", 9 if bold else 8),
               fill=NAVY if bold else INK)
    return img


_STATIC = None


def static_map():
    global _STATIC
    if _STATIC is None:
        _STATIC = _static()
    return _STATIC


# ---------- trains ----------
_KX = math.cos(math.radians(36.9))


def _along(poly, t):
    lens = [math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
    goal = t * sum(lens)
    for (a, b), ln in zip(zip(poly, poly[1:]), lens):
        if goal <= ln and ln > 0:
            f = goal / ln
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        goal -= ln
    return poly[-1]


def place(line, lat, lon):
    """Snap a GPS fix onto the nearest station-to-station stretch of its line."""
    px, py = lon * _KX, lat
    best, bd = None, 1e9
    for li, a, b, poly, (la0, lo0), (la1, lo1) in SEGS:
        if li != line:
            continue
        ax, ay, bx, by = lo0 * _KX, la0, lo1 * _KX, la1
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
        dd = (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2
        if dd < bd:
            bd, best = dd, (poly, t)
    if best is None or bd > 0.015 ** 2:        # >~1.5km off the line: depot/yard
        return None
    return _along(*best)


# ---------- frame ----------
def _header(d, clock):
    d.rectangle((0, 0, W, HEAD_H), fill=AT_BLUE)
    d.text((7, HEAD_H / 2), "Ngā Tereina", font=font("arialbd.ttf", 12), fill=WHITE, anchor="lm")
    d.text((82, HEAD_H / 2 + 1), "Trains", font=font("arial.ttf", 10),
           fill=(190, 212, 240), anchor="lm")
    d.text((W - 7, HEAD_H / 2), clock, font=font("arialbd.ttf", 13), fill=WHITE, anchor="rm")


def _legend(img, counts, stale):
    x0, y0, x1, y1 = 5, 180, 122, 236
    shadow = Image.new("L", img.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x0 + 1, y0 + 2, x1 + 1, y1 + 2), radius=6, fill=80)
    img.paste((140, 158, 186), (0, 0), shadow.filter(ImageFilter.GaussianBlur(2)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=WHITE)
    for i, li in enumerate((SC, EW, OW)):
        code, name, col, _ = LINES[li]
        y = y0 + 9 + i * 13
        d.rounded_rectangle((x0 + 5, y - 5, x0 + 29, y + 5), radius=5, fill=col)
        d.text((x0 + 17, y), code, font=font("arialbd.ttf", 8), fill=WHITE, anchor="mm")
        d.text((x0 + 34, y), name, font=font("arial.ttf", 8), fill=INK, anchor="lm")
        n = "–" if counts is None else str(counts[li])
        d.text((x1 - 6, y), n, font=font("arialbd.ttf", 10), fill=NAVY, anchor="rm")
    msg, col = ("data is stale", WARN) if stale else ("trains running now", LIVE)
    d.ellipse((x0 + 6, y1 - 11, x0 + 11, y1 - 6), fill=col)
    d.text((x0 + 15, y1 - 8), msg, font=font("arial.ttf", 8), fill=INK, anchor="lm")


def _dot(col):
    """A smooth train marker (navy rim, white ring, line colour), 13x13 RGBA."""
    k = 8
    big = Image.new("RGBA", (13 * k, 13 * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    c = 6.5 * k
    for r, fill in ((4.4, NAVY), (3.7, WHITE), (2.5, col)):
        d.ellipse((c - r * k, c - r * k, c + r * k, c + r * k), fill=fill)
    return big.resize((13, 13), Image.LANCZOS)


_DOTS = [_dot(l[2]) for l in LINES]
_legend_cache = {}


def render(trains, counts, clock, stale_s=0, t=0.0):
    """trains: [(x, y, line)] positions on the map (see place())."""
    key = (tuple(counts) if counts else None, stale_s > 90)
    if key not in _legend_cache:
        _legend_cache.clear()
        base = static_map().copy()
        _legend(base, counts, stale_s > 90)
        _legend_cache[key] = base
    img = _legend_cache[key].copy()
    # whole-pixel positions: a dot only costs USB bandwidth when it really moves
    for x, y, li in sorted(trains, key=lambda tr: tr[2] == SC):
        img.paste(_DOTS[li], (int(round(x)) - 6, int(round(y)) - 6), _DOTS[li])
    _header(ImageDraw.Draw(img), clock)
    return img
