# Live Auckland rail map, rendered on the PC (PIL) in the style of AT's
# network map: post-CRL lines with every train as a dot.
import json, math, os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 320, 240
SS = 3                      # supersampling for smooth lines
STATUS_H = 18

# colours match the bus screen's "transit" theme
BG = (12, 16, 24)
PANEL = (22, 29, 42)
TEXT = (233, 238, 245)
DIM = (128, 143, 165)
LIVE = (120, 220, 130)
WARN = (245, 176, 66)
CRL_GLOW = (255, 206, 84)

LINES = [   # id, colour (AT's route colours), station order (AT's longest trip)
    ("E-W", (0x97, 0xC9, 0x3D), [
        "Swanson", "Ranui", "Sturges Rd", "Henderson", "Sunnyvale", "Glen Eden",
        "Fruitvale", "New Lynn", "Avondale", "Mt Albert", "Baldwin Ave",
        "Morningside", "Kingsland", "Maungawhau", "Karanga-a-Hape",
        "Te Waihorotiu", "Waitemata", "Orakei", "Meadowbank", "Glen Innes",
        "Panmure", "Sylvia Park", "Otahuhu", "Middlemore", "Papatoetoe",
        "Puhinui", "Manukau"]),
    ("S-C", (0xD5, 0x29, 0x23), [
        "Pukekohe", "Paerata", "Drury", "Papakura", "Takaanini", "Te Mahia",
        "Manurewa", "Homai", "Puhinui", "Papatoetoe", "Middlemore", "Otahuhu",
        "Penrose", "Ellerslie", "Greenlane", "Remuera", "Newmarket", "Grafton",
        "Karanga-a-Hape", "Te Waihorotiu", "Waitemata", "Parnell", "Newmarket"]),
    ("O-W", (0x00, 0xAE, 0xEF), [
        "Onehunga", "Te Papapa", "Penrose", "Ellerslie", "Greenlane", "Remuera",
        "Newmarket", "Grafton", "Maungawhau", "Kingsland", "Morningside",
        "Baldwin Ave", "Mt Albert", "Avondale", "New Lynn", "Fruitvale",
        "Glen Eden", "Sunnyvale", "Henderson"]),
]
LINE_IDS = [l[0] for l in LINES]

# schematic positions (screen px), arranged like AT's official map
POS = {
    # City Rail Link
    "Waitemata": (200, 40), "Te Waihorotiu": (170, 40),
    "Karanga-a-Hape": (156, 58), "Maungawhau": (142, 72),
    # inner
    "Grafton": (184, 72), "Parnell": (222, 58), "Newmarket": (222, 88),
    # east
    "Orakei": (246, 40), "Meadowbank": (270, 40), "Glen Innes": (290, 54),
    "Panmure": (298, 72), "Sylvia Park": (298, 102),
    # south
    "Remuera": (231, 97), "Greenlane": (240, 106), "Ellerslie": (249, 115),
    "Penrose": (258, 124), "Otahuhu": (266, 134), "Middlemore": (266, 145),
    "Papatoetoe": (266, 155), "Puhinui": (266, 165), "Manukau": (290, 189),
    "Homai": (266, 175), "Manurewa": (266, 183), "Te Mahia": (266, 191),
    "Takaanini": (266, 199), "Papakura": (266, 207), "Drury": (266, 215),
    "Paerata": (266, 223), "Pukekohe": (266, 232),
    # Onehunga branch
    "Te Papapa": (246, 136), "Onehunga": (234, 148),
    # west
    "Kingsland": (132, 82), "Morningside": (122, 92), "Baldwin Ave": (112, 102),
    "Mt Albert": (102, 112), "Avondale": (82, 112), "New Lynn": (62, 112),
    "Fruitvale": (42, 112), "Glen Eden": (32, 102), "Sunnyvale": (22, 92),
    "Henderson": (14, 84), "Sturges Rd": (14, 70), "Ranui": (14, 56),
    "Swanson": (14, 42),
}
CRL = ("Waitemata", "Te Waihorotiu", "Karanga-a-Hape", "Maungawhau")

# label text, offset from the station, PIL anchor
LABELS = {
    "Swanson": ("Swanson", (7, 0), "lm"),
    "Henderson": ("Henderson", (7, -3), "lb"),
    "New Lynn": ("New Lynn", (0, 6), "mt"),
    "Mt Albert": ("Mt Albert", (4, 6), "lt"),
    "Kingsland": ("Kingsland", (-6, -1), "rm"),
    "Maungawhau": ("Maungawhau", (-7, -2), "rm"),
    "Karanga-a-Hape": ("Karanga-a-Hape", (-7, -1), "rm"),
    "Te Waihorotiu": ("Te Waihorotiu", (-7, 0), "rm"),
    "Waitemata": ("Waitematā", (0, -7), "mb"),
    "Orakei": ("Ōrākei", (0, -6), "mb"),
    "Parnell": ("Parnell", (-6, 0), "rm"),
    "Grafton": ("Grafton", (0, 6), "mt"),
    "Newmarket": ("Newmarket", (-5, 4), "rt"),
    "Glen Innes": ("Glen Innes", (-6, -2), "rm"),
    "Panmure": ("Panmure", (-6, 0), "rm"),
    "Sylvia Park": ("Sylvia Park", (-6, -2), "rb"),
    "Penrose": ("Penrose", (-6, -1), "rm"),
    "Otahuhu": ("Ōtāhuhu", (6, 2), "lt"),
    "Onehunga": ("Onehunga", (-6, 0), "rm"),
    "Puhinui": ("Puhinui", (-6, 0), "rm"),
    "Manukau": ("Manukau", (0, 6), "mt"),
    "Papakura": ("Papakura", (-7, 0), "rm"),
    "Pukekohe": ("Pukekohe", (-7, 0), "rm"),
}
INTERCHANGE = {"Waitemata", "Te Waihorotiu", "Karanga-a-Hape", "Maungawhau",
               "Grafton", "Newmarket", "Penrose", "Otahuhu", "Puhinui", "Henderson"}
GAP = 3.2                   # px between parallel lines on shared track
LINE_W = 3

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
def _build():
    real = json.load(open(os.path.join(HERE, "tools", "stations.json")))
    users = {}
    for li, (_, _, seq) in enumerate(LINES):
        for a, b in zip(seq, seq[1:]):
            users.setdefault(frozenset((a, b)), set()).add(li)
    segs = []       # (line, (x0,y0), (x1,y1), (lat0,lon0), (lat1,lon1)) offset applied
    paths = []      # per line: list of runs of screen points
    for li, (_, _, seq) in enumerate(LINES):
        pts = []
        for a, b in zip(seq, seq[1:]):
            u = sorted(users[frozenset((a, b))])
            p, q = sorted((a, b), key=lambda n: POS[n])
            (x0, y0), (x1, y1) = POS[p], POS[q]
            ln = math.hypot(x1 - x0, y1 - y0)
            nx, ny = -(y1 - y0) / ln, (x1 - x0) / ln
            off = (u.index(li) - (len(u) - 1) / 2) * GAP
            A = (POS[a][0] + nx * off, POS[a][1] + ny * off)
            B = (POS[b][0] + nx * off, POS[b][1] + ny * off)
            segs.append((li, A, B, real[a], real[b]))
            if pts and math.dist(pts[-1], A) < 4:
                pts[-1] = ((pts[-1][0] + A[0]) / 2, (pts[-1][1] + A[1]) / 2)
            else:
                if pts:
                    paths.append((li, pts))
                pts = [A]
            pts.append(B)
        paths.append((li, pts))
    return segs, paths


SEGS, PATHS = _build()


def _static():
    big = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(big)
    S = lambda p: (p[0] * SS, p[1] * SS)
    # the City Rail Link tunnel sits in a slate casing
    crl = [S(POS[n]) for n in ("Maungawhau", "Karanga-a-Hape", "Te Waihorotiu", "Waitemata")]
    d.line(crl, fill=(52, 60, 76), width=12 * SS, joint="curve")
    for li, pts in PATHS:
        d.line([S(p) for p in pts], fill=LINES[li][1], width=LINE_W * SS, joint="curve")
        for p in (pts[0], pts[-1]):
            r = LINE_W * SS / 2
            d.ellipse((p[0] * SS - r, p[1] * SS - r, p[0] * SS + r, p[1] * SS + r),
                      fill=LINES[li][1])
    for n, (x, y) in POS.items():
        x, y = x * SS, y * SS
        if n in INTERCHANGE:
            r = 3.6 * SS
            d.ellipse((x - r, y - r, x + r, y + r), fill=(250, 250, 250),
                      outline=(20, 24, 30), width=int(0.9 * SS))
        else:
            r = 1.7 * SS
            d.ellipse((x - r, y - r, x + r, y + r), fill=(250, 250, 250))
    img = big.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    for n, (text, (dx, dy), anchor) in LABELS.items():
        x, y = POS[n]
        crl = n in CRL
        d.text((x + dx, y + dy), text, anchor=anchor,
               font=font("arialbd.ttf" if crl else "arial.ttf", 9),
               fill=CRL_GLOW if crl else (190, 200, 215))
    return img


_STATIC = None


def static_map():
    global _STATIC
    if _STATIC is None:
        _STATIC = _static()
    return _STATIC


# ---------- trains ----------
_KX = math.cos(math.radians(36.9))


def place(line, lat, lon):
    """Snap a GPS fix onto the nearest piece of that line's track."""
    px, py = lon * _KX, lat
    best, bd = None, 1e9
    for li, A, B, (la0, lo0), (la1, lo1) in SEGS:
        if li != line:
            continue
        ax, ay, bx, by = lo0 * _KX, la0, lo1 * _KX, la1
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
        dd = (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2
        if dd < bd:
            bd, best = dd, (A, B, t)
    if best is None or bd > 0.015 ** 2:        # >~1.5km off the line: depot/yard
        return None
    A, B, t = best
    return A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t


# ---------- frame ----------
def render(trains, counts, clock, stale_s=0):
    """trains: [(x, y, line_index)] from place(); counts per line or None."""
    img = static_map().copy()
    d = ImageDraw.Draw(img)
    # status bar, same as the bus screen
    d.rectangle((0, 0, W, STATUS_H), fill=PANEL)
    mid = STATUS_H / 2
    d.text((6, mid), "Auckland trains", font=font("arial.ttf", 11), fill=DIM, anchor="lm")
    d.text((W - 6, mid), clock, font=font("consolab.ttf", 12), fill=TEXT, anchor="rm")
    stale = stale_s > 90
    d.text((W - 54, mid), "stale" if stale else "live", font=font("arial.ttf", 10),
           fill=DIM, anchor="rm")
    d.ellipse((W - 49, mid - 3, W - 43, mid + 3), fill=WARN if stale else LIVE)
    # trains
    for x, y, li in trains:
        d.ellipse((x - 3.5, y - 3.5, x + 3.5, y + 3.5), fill=(255, 255, 255))
        d.ellipse((x - 2.3, y - 2.3, x + 2.3, y + 2.3), fill=LINES[li][1])
    # legend
    x0, y0 = 8, 150
    d.rounded_rectangle((x0 - 4, y0 - 6, x0 + 118, y0 + 74), radius=5, fill=PANEL)
    d.text((x0, y0), "Trains running", font=font("arialbd.ttf", 10), fill=TEXT)
    for i, (name, col, _) in enumerate(LINES):
        yy = y0 + 18 + i * 14
        d.rounded_rectangle((x0, yy - 4, x0 + 26, yy + 5), radius=3, fill=col)
        d.text((x0 + 13, yy + 1), name, font=font("arialbd.ttf", 8), fill=(20, 24, 30),
               anchor="mm")
        n = "-" if counts is None else str(counts[i])
        d.text((x0 + 110, yy + 1), n, font=font("consolab.ttf", 11), fill=TEXT, anchor="rm")
    d.rounded_rectangle((x0, y0 + 60, x0 + 26, y0 + 68), radius=4, fill=(52, 60, 76))
    d.text((x0 + 32, y0 + 64), "City Rail Link", font=font("arial.ttf", 9), fill=DIM,
           anchor="lm")
    return img
