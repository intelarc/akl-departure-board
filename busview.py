# Bus departures in AT's visual style: blue header, white cards, and a little
# live scene per lane -- the sky follows the real time of day, clouds drift,
# and the bus (pixel art from MSMGreen/at-departure-board) slides toward the
# stop as it gets closer. Rendered on the PC with Pillow.
import math, os, random
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from atboard import layout, sprites, themes

W, H = 320, 240
HEAD_H = 22
AT_BLUE = (35, 94, 168)
PAGE = (226, 236, 247)
NAVY = (26, 39, 68)
INK = (86, 100, 126)
WHITE = (255, 255, 255)
LIVE = (60, 190, 96)
WARN = (232, 150, 20)
BUS = (0, 150, 214)               # AT's bus teal-blue
HORIZON_S = layout.HORIZON_S      # a bus enters the lane 20 minutes out

_FONTS = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
_fc = {}


def font(name, size):
    if (name, size) not in _fc:
        try:
            _fc[name, size] = ImageFont.truetype(os.path.join(_FONTS, name), size)
        except OSError:
            _fc[name, size] = ImageFont.load_default()
    return _fc[name, size]


_TH = themes.get("transit")


# ---------- time of day ----------
def _mix(a, b, f):
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


# (hour, sky top, sky bottom, far hills, near city) -- blended between keys
SKY = [
    (0.0, (10, 18, 44), (30, 44, 84), (26, 36, 64), (36, 48, 80)),
    (5.5, (20, 30, 70), (70, 76, 120), (40, 48, 80), (50, 60, 92)),
    (6.8, (110, 150, 210), (255, 196, 150), (150, 150, 170), (120, 128, 156)),
    (8.5, (120, 180, 240), (210, 234, 252), (170, 196, 176), (160, 176, 200)),
    (16.5, (110, 172, 236), (214, 236, 252), (170, 196, 176), (160, 176, 200)),
    (18.3, (90, 110, 190), (255, 170, 120), (140, 130, 150), (110, 110, 140)),
    (19.5, (30, 40, 90), (110, 80, 120), (50, 52, 84), (60, 62, 96)),
    (21.0, (10, 18, 44), (30, 44, 84), (26, 36, 64), (36, 48, 80)),
    (24.0, (10, 18, 44), (30, 44, 84), (26, 36, 64), (36, 48, 80)),
]


def sky_at(hour):
    for (h0, *a), (h1, *b) in zip(SKY, SKY[1:]):
        if h0 <= hour <= h1:
            f = (hour - h0) / (h1 - h0)
            return [_mix(x, y, f) for x, y in zip(a, b)]
    return SKY[0][1:]


def is_night(hour):
    return hour < 6.3 or hour > 19.6


# ---------- one lane's scenery (cached; only rebuilt when the sky shifts) ----------
_cache = {}


def _scene(w, h, city, hour, seed):
    key = (w, h, city, round(hour * 12) / 12, seed)       # 5-minute steps
    if key in _cache:
        return _cache[key]
    top, bottom, hills, near = sky_at(hour)
    night = is_night(hour)
    SS = 3
    img = Image.new("RGB", (w * SS, h * SS))
    d = ImageDraw.Draw(img)
    for y in range(h * SS):                                 # sky gradient
        d.line((0, y, w * SS, y), fill=_mix(top, bottom, y / (h * SS)))
    rnd = random.Random(seed)
    ground = h - 13
    if night:
        for _ in range(28):
            x, y = rnd.uniform(0, w), rnd.uniform(0, ground - 18)
            r = rnd.choice((0.35, 0.5, 0.7))
            c = rnd.choice(((255, 255, 255), (200, 214, 255), (255, 240, 210)))
            d.ellipse(((x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS), fill=c)
        d.ellipse(((w - 60) * SS, 5 * SS, (w - 50) * SS, 15 * SS), fill=(250, 244, 220))
        d.ellipse(((w - 57) * SS, 4 * SS, (w - 47) * SS, 14 * SS), fill=top)   # crescent
    # far hills
    pts = [(0, ground)]
    for x in range(0, w + 8, 4):
        pts.append((x, ground - 9 - 5 * math.sin(x / 23 + seed) - 3 * math.sin(x / 9 + seed * 2)))
    pts.append((w, ground))
    d.polygon([(x * SS, y * SS) for x, y in pts], fill=hills)
    if city:
        # Auckland's skyline, with the Sky Tower
        x = 6
        while x < w - 70:
            bw, bh = rnd.randint(8, 16), rnd.randint(8, 22)
            d.rectangle((x * SS, (ground - bh) * SS, (x + bw) * SS, ground * SS), fill=near)
            if night:
                for wy in range(ground - bh + 3, ground - 2, 4):
                    for wx in range(x + 2, x + bw - 1, 3):
                        if rnd.random() < 0.4:
                            d.rectangle((wx * SS, wy * SS, (wx + 1) * SS - 1, (wy + 1) * SS - 1),
                                        fill=(255, 214, 120))
            x += bw + rnd.randint(1, 4)
        tx = w * 0.42
        d.polygon([((tx - 2.2) * SS, ground * SS), ((tx + 2.2) * SS, ground * SS),
                   ((tx + 1.1) * SS, (ground - 36) * SS), ((tx - 1.1) * SS, (ground - 36) * SS)],
                  fill=near)
        d.ellipse(((tx - 3.6) * SS, (ground - 40) * SS, (tx + 3.6) * SS, (ground - 34) * SS),
                  fill=near)
        d.rectangle(((tx - 0.5) * SS, (ground - 50) * SS, (tx + 0.5) * SS, (ground - 38) * SS),
                    fill=near)
        if night:
            d.ellipse(((tx - 1) * SS, (ground - 51) * SS, (tx + 1) * SS, (ground - 49) * SS),
                      fill=(255, 90, 90))
    else:
        # suburb: houses and pohutukawa
        x = 4
        while x < w - 64:
            if rnd.random() < 0.55:
                hw = rnd.randint(9, 13)
                hh = rnd.randint(6, 8)
                d.rectangle((x * SS, (ground - hh) * SS, (x + hw) * SS, ground * SS), fill=near)
                d.polygon([((x - 1) * SS, (ground - hh) * SS), ((x + hw + 1) * SS, (ground - hh) * SS),
                           ((x + hw / 2) * SS, (ground - hh - 5) * SS)], fill=_mix(near, (0, 0, 0), 0.15))
                if night and rnd.random() < 0.7:
                    d.rectangle(((x + 3) * SS, (ground - 4) * SS, (x + 5) * SS, (ground - 2) * SS),
                                fill=(255, 214, 120))
                x += hw + rnd.randint(3, 7)
            else:
                r = rnd.randint(4, 6)
                green = _mix((70, 130, 80), near, 0.55 if not night else 0.8)
                d.rectangle(((x + r - 0.8) * SS, (ground - 4) * SS, (x + r + 0.8) * SS, ground * SS),
                            fill=_mix(near, (0, 0, 0), 0.3))
                d.ellipse((x * SS, (ground - 3 - 2 * r) * SS, (x + 2 * r) * SS, (ground - 3) * SS),
                          fill=green)
                x += 2 * r + rnd.randint(2, 6)
    # road
    road = (58, 64, 76) if not night else (34, 38, 50)
    d.rectangle((0, ground * SS, w * SS, h * SS), fill=road)
    d.rectangle((0, ground * SS, w * SS, (ground + 1) * SS), fill=_mix(road, (255, 255, 255), 0.25))
    for x in range(-4, w, 14):
        d.rectangle((x * SS, (ground + 6) * SS, (x + 7) * SS, (ground + 7) * SS),
                    fill=(236, 224, 170) if not night else (170, 160, 120))
    img = img.resize((w, h), Image.LANCZOS)
    _cache.clear() if len(_cache) > 16 else None
    _cache[key] = img
    return img


def _cloud(r):
    c = Image.new("RGBA", (int(r * 5), int(r * 2.4)), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    for cx, cy, rr in ((r * 1.2, r * 1.4, r * 0.9), (r * 2.3, r * 1.0, r * 1.1),
                       (r * 3.5, r * 1.4, r * 0.85), (r * 2.4, r * 1.55, r * 0.8)):
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(255, 255, 255, 215))
    return c


_CLOUDS = [_cloud(5), _cloud(4), _cloud(6)]


def _stop_sign(d, x, ground):
    # AT bus stop: grey pole, round blue sign with a white bus glyph
    d.rectangle((x, ground - 22, x + 1, ground + 1), fill=(120, 128, 140))
    d.ellipse((x - 5, ground - 32, x + 6, ground - 21), fill=AT_BLUE, outline=WHITE)
    d.rectangle((x - 2, ground - 29, x + 3, ground - 25), fill=WHITE)
    d.point([(x - 1, ground - 24), (x + 2, ground - 24)], fill=WHITE)


def _card_shadow(img, box, r):
    sh = Image.new("L", img.size, 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 2, x1, y1 + 3), radius=r, fill=90)
    img.paste((150, 166, 196), (0, 0), sh.filter(ImageFilter.GaussianBlur(3)))


def _mins(eta):
    return max(0, int(eta) // 60)


def render(location, clock_str, hour, lanes, t, stale=False):
    """lanes: [dict(route, headsign, deps=[(eta_s, live, cancelled)], message)]"""
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    # header
    d.rectangle((0, 0, W, HEAD_H), fill=AT_BLUE)
    d.text((8, HEAD_H / 2), location, font=font("arialbd.ttf", 13), fill=WHITE, anchor="lm")
    d.text((W - 8, HEAD_H / 2), clock_str, font=font("arialbd.ttf", 14), fill=WHITE, anchor="rm")
    cw = d.textlength(clock_str, font=font("arialbd.ttf", 14))
    pulse = 0.5 + 0.5 * math.sin(t * 3)
    lx = W - 16 - cw
    col = WARN if stale else _mix(LIVE, (170, 240, 180), pulse)
    d.ellipse((lx - 7, HEAD_H / 2 - 3.5, lx, HEAD_H / 2 + 3.5), fill=col)
    d.text((lx - 11, HEAD_H / 2 + 0.5), "STALE" if stale else "LIVE",
           font=font("arialbd.ttf", 8), fill=(200, 220, 245), anchor="rm")

    n = max(1, len(lanes))
    gap = 6
    top = HEAD_H + gap
    ch = (H - top - gap * n) // n
    for i, ln in enumerate(lanes):
        y0 = top + i * (ch + gap)
        box = (6, y0, W - 6, y0 + ch)
        _card_shadow(img, box, 9)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, radius=9, fill=WHITE)
        _lane(img, d, box, ln, hour, t, i)
    return img


def _lane(img, d, box, ln, hour, t, idx):
    x0, y0, x1, y1 = box
    ch = y1 - y0
    compact = ch < 80
    # top row: route badge, headsign, big minutes
    bf = font("arialbd.ttf", 13)
    bw = d.textlength(ln["route"], font=bf) + 14
    d.rounded_rectangle((x0 + 8, y0 + 7, x0 + 8 + bw, y0 + 25), radius=9, fill=BUS)
    d.text((x0 + 8 + bw / 2, y0 + 16), ln["route"], font=bf, fill=WHITE, anchor="mm")
    d.text((x0 + 16 + bw, y0 + 16), ln["headsign"], font=font("arialbd.ttf", 11), fill=NAVY,
           anchor="lm")
    deps = ln["deps"]
    nxt = None if ln.get("message") else (deps[0] if deps else None)
    if ln.get("message"):
        big, sub, bcol = "--", ln["message"], INK
    elif nxt is None:
        big, sub, bcol = "--", "none soon", INK
    else:
        m = _mins(nxt[0])
        if nxt[2]:
            big, bcol = "✕", WARN
        elif m == 0:
            big, bcol = "Due", LIVE
        else:
            big, bcol = str(m), NAVY
        rest = [str(_mins(e)) for e, _, c in deps[1:3] if not c]
        sub = ("then " + ", ".join(rest)) if rest else ""
    bfnt = font("arialbd.ttf", 22)
    if big in ("--", "Due", "✕"):
        d.text((x1 - 10, y0 + 5), big, font=bfnt, fill=bcol, anchor="ra")
    else:
        d.text((x1 - 10, y0 + 24), "min", font=font("arialbd.ttf", 9), fill=INK, anchor="rs")
        d.text((x1 - 30, y0 + 5), big, font=bfnt, fill=bcol, anchor="ra")
    if nxt and nxt[1] and not nxt[2]:
        d.text((x0 + 16 + bw, y0 + 26), "● live", font=font("arial.ttf", 8), fill=LIVE, anchor="lt")
    elif nxt and not nxt[2]:
        d.text((x0 + 16 + bw, y0 + 26), "scheduled", font=font("arial.ttf", 8), fill=INK, anchor="lt")

    # the scene
    sx0, sy0, sx1, sy1 = x0 + 6, y0 + 38, x1 - 6, y1 - 6
    sw, sh = int(sx1 - sx0), int(sy1 - sy0)
    city = "britomart" in ln["headsign"].lower() or "city" in ln["headsign"].lower()
    scene = _scene(sw, sh, city, hour, idx * 7 + 3).copy()
    sd = ImageDraw.Draw(scene)
    ground = sh - 13
    if not is_night(hour):                          # drifting clouds
        for k, c in enumerate(_CLOUDS):
            span = sw + c.width
            cx = int((t * (1.2 + 0.5 * k) + k * 97 + idx * 53) % span) - c.width
            cy = 2 + (k * 7 + idx * 5) % max(1, ground - 30)
            scene.paste(c, (cx, cy), c)
    stop_x = sw - 40
    _stop_sign(sd, stop_x, ground)
    if sub:
        pill_f = font("arial.ttf", 9)
        tw = sd.textlength(sub, font=pill_f)
        sd.rounded_rectangle((4, 3, tw + 14, 16), radius=6, fill=(255, 255, 255))
        sd.text((9, 9.5), sub, font=pill_f, fill=NAVY, anchor="lm")
    # the bus: x is its time to arrival
    spr = _TH.sprite("compact" if compact else "large", "bus")
    body = BUS if not (nxt and nxt[2]) else (150, 160, 175)
    colours = _TH.role_colours(body)
    if nxt is not None:
        eta = max(0, min(HORIZON_S, nxt[0]))
        progress = 1 - eta / HORIZON_S
        bx = int(4 + progress * (stop_x - 6 - spr.width - 4))
        bob = 1 if (nxt[0] > 30 and math.sin(t * 6 + idx) > 0.6) else 0
        sprites.blit(sd, spr, bx, ground + 8 - bob, colours)
    # rounded mask so the scene sits inside the card
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=6, fill=255)
    img.paste(scene, (int(sx0), int(sy0)), mask)
