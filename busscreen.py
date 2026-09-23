# The bus stop screen, drawn on the board: the baked page (header + cards),
# then per lane the route/minutes row and a little live scene -- sky that
# follows the time of day, drifting clouds, and the bus sliding toward the
# stop as it gets closer. Each scene is composed in RAM, then blitted once.
import math, time
from array import array
import gfx
from gfx import rgb
import busart

W, H, HEAD_H = 320, 240, 22
AT_BLUE = rgb(35, 94, 168)
NAVY = rgb(26, 39, 68)
INK = rgb(86, 100, 126)
LIVE = rgb(60, 190, 96)
WARN = rgb(232, 150, 20)
BUS = rgb(0, 150, 214)
WHITE = 0xFFFF
HORIZON = 20 * 60            # a bus enters its lane 20 minutes out


def _mix(a, b, f):
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


# (hour, sky top, sky bottom, far hills, near buildings)
SKY = (
    (0.0, (10, 18, 44), (30, 44, 84), (26, 36, 64), (36, 48, 80)),
    (5.5, (20, 30, 70), (70, 76, 120), (40, 48, 80), (50, 60, 92)),
    (6.8, (110, 150, 210), (255, 196, 150), (150, 150, 170), (120, 128, 156)),
    (8.5, (120, 180, 240), (210, 234, 252), (170, 196, 176), (160, 176, 200)),
    (16.5, (110, 172, 236), (214, 236, 252), (170, 196, 176), (160, 176, 200)),
    (18.3, (90, 110, 190), (255, 170, 120), (140, 130, 150), (110, 110, 140)),
    (19.5, (30, 40, 90), (110, 80, 120), (50, 52, 84), (60, 62, 96)),
    (21.0, (10, 18, 44), (30, 44, 84), (26, 36, 64), (36, 48, 80)),
    (24.0, (10, 18, 44), (30, 44, 84), (26, 36, 64), (36, 48, 80)),
)


def sky_at(h):
    for i in range(len(SKY) - 1):
        a, b = SKY[i], SKY[i + 1]
        if a[0] <= h <= b[0]:
            f = (h - a[0]) / (b[0] - a[0])
            return [_mix(a[k], b[k], f) for k in range(1, 5)]
    return list(SKY[0][1:])


def night(h):
    return h < 6.3 or h > 19.6


class _Rng:
    # tiny LCG so each lane's scenery is the same every time it's rebuilt
    def __init__(self, seed):
        self.s = (seed * 1664525 + 1013904223) & 0xFFFFFFFF

    def below(self, n):
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return ((self.s >> 16) * n) >> 16

    def between(self, a, b):
        return a + self.below(b - a + 1)


def lane_boxes(n):
    gap = 6
    top = HEAD_H + gap
    ch = (H - top - gap * n) // n
    return [(6, top + i * (ch + gap), W - 6, top + i * (ch + gap) + ch) for i in range(n)]


class Lane:
    def __init__(self, box, idx):
        x0, y0, x1, y1 = box
        self.box, self.idx = box, idx
        self.row = (x0 + 8, y0 + 4, x1 - x0 - 16, 32)             # text row
        sh = min(y1 - y0 - 44, 64)                                  # RAM caps the height
        self.scene = (x0 + 6, y1 - 6 - sh, x1 - x0 - 12, sh)        # scene box
        self.key = None
        self.plan = None

    def build(self, city, h):
        """Work out this lane's scenery (a list of shapes) for the hour."""
        sw, sh = self.scene[2], self.scene[3]
        ground = sh - 12
        top, bottom, hills, near = sky_at(h)
        nt = night(h)
        rnd = _Rng(self.idx * 7 + 3)
        rows = [rgb(*_mix(top, bottom, y / sh)) for y in range(ground)]
        stars = [(rnd.below(sw), rnd.below(max(1, ground - 16))) for _ in range(26)] if nt else []
        pts = [0, ground]
        seed = self.idx * 7 + 3
        for x in range(0, sw + 8, 4):
            pts += [x, int(ground - 8 - 4 * math.sin(x / 23 + seed) - 2 * math.sin(x / 9 + seed * 2))]
        pts += [sw, ground]
        shapes = []                      # (kind, args..., colour)
        nc, lit = rgb(*near), rgb(255, 214, 120)
        roof = rgb(*_mix(near, (0, 0, 0), 0.15))
        if city:
            x = 5
            while x < sw - 60:
                bw, bh = rnd.between(8, 15), rnd.between(8, 20)
                shapes.append((0, x, ground - bh, bw, bh, nc))
                if nt:
                    for wy in range(ground - bh + 3, ground - 2, 4):
                        for wx in range(x + 2, x + bw - 1, 3):
                            if rnd.below(10) < 4:
                                shapes.append((0, wx, wy, 1, 1, lit))
                x += bw + rnd.between(1, 4)
            tx = int(sw * 0.42)                  # the Sky Tower
            shapes += [(0, tx - 1, ground - 34, 3, 34, nc), (2, tx, ground - 36, 4, 3, nc),
                       (0, tx, ground - 47, 1, 12, nc)]
            if nt:
                shapes.append((0, tx, ground - 48, 1, 1, rgb(255, 90, 90)))
        else:
            x = 4
            while x < sw - 60:
                if rnd.below(100) < 55:              # a house
                    hw, hh = rnd.between(9, 13), rnd.between(6, 8)
                    shapes.append((0, x, ground - hh, hw, hh, nc))
                    shapes.append((3, array("h", [x - 1, ground - hh, x + hw + 1, ground - hh,
                                                  x + hw // 2, ground - hh - 5]), roof))
                    if nt and rnd.below(10) < 7:
                        shapes.append((0, x + 3, ground - 4, 2, 2, lit))
                    x += hw + rnd.between(3, 7)
                else:                                # a pohutukawa
                    r = rnd.between(4, 6)
                    shapes.append((0, x + r - 1, ground - 4, 2, 4, rgb(*_mix(near, (0, 0, 0), 0.3))))
                    shapes.append((2, x + r, ground - 3 - r, r, r,
                                   rgb(*_mix((70, 130, 80), near, 0.8 if nt else 0.55))))
                    x += 2 * r + rnd.between(2, 6)
        road = (34, 38, 50) if nt else (58, 64, 76)
        self.plan = (rows, stars, array("h", pts), rgb(*hills), shapes, ground,
                     rgb(*road), rgb(*_mix(road, (255, 255, 255), 0.25)),
                     rgb(170, 160, 120) if nt else rgb(236, 224, 170), nt, rgb(*top))

    def draw_scene(self, tft, pool, dep, sub, t):
        sx, sy, sw, sh = self.scene
        cv = gfx.Canvas(memoryview(pool)[:sw * sh * 2], sw, sh)
        rows, stars, hill, hc, shapes, ground, road, kerb, dash, nt, top = self.plan
        fb = cv.fb
        for y, c in enumerate(rows):
            fb.hline(0, y, sw, gfx.sw(c))
        for x, y in stars:
            fb.pixel(x, y, 0xFFFF)
        if nt:
            cv.ellipse(sw - 55, 10, 5, 5, rgb(250, 244, 220))
            cv.ellipse(sw - 52, 9, 5, 5, rgb(*top))
        else:
            for k in range(3):                       # drifting clouds
                span = sw + 30
                cx = int((t * (1.2 + 0.5 * k) + k * 97 + self.idx * 53) % span) - 15
                cy = 7 + (k * 7 + self.idx * 5) % max(1, ground - 30)
                r = 4 + k % 2
                cv.ellipse(cx, cy + 1, r + 2, r - 1, WHITE)
                cv.ellipse(cx + r + 1, cy - 1, r + 1, r, WHITE)
                cv.ellipse(cx + 2 * r + 2, cy + 1, r, r - 1, WHITE)
        fb.poly(0, 0, hill, gfx.sw(hc), True)
        for s in shapes:
            if s[0] == 0:
                fb.fill_rect(s[1], s[2], s[3], s[4], gfx.sw(s[5]))
            elif s[0] == 2:
                fb.ellipse(s[1], s[2], s[3], s[4], gfx.sw(s[5]), True)
            else:
                fb.poly(0, 0, s[1], gfx.sw(s[2]), True)
        cv.rect(0, ground, sw, sh - ground, road)
        cv.rect(0, ground, sw, 1, kerb)
        for x in range(-4, sw, 14):
            cv.rect(x, ground + 6, 7, 1, dash)
        stop_x = sw - 38                              # AT bus stop sign
        cv.rect(stop_x, ground - 22, 2, 23, rgb(120, 128, 140))
        cv.ellipse(stop_x + 1, ground - 27, 6, 6, WHITE)
        cv.ellipse(stop_x + 1, ground - 27, 5, 5, AT_BLUE)
        cv.rect(stop_x - 2, ground - 29, 6, 4, WHITE)
        if sub:
            f = self.font_small
            tw = f.width(sub)
            cv.rrect(4, 3, tw + 12, 13, 6, WHITE)
            cv.text(f, sub, 10, 3, NAVY)
        if dep is not None:
            art = busart.LARGE if sh >= 50 else busart.COMPACT
            eta = max(0, min(HORIZON, dep[0]))
            bx = int(4 + (1 - eta / HORIZON) * (stop_x - 10 - art[0]))
            bob = 1 if (dep[0] > 30 and math.sin(t * 6 + self.idx) > 0.6) else 0
            gfx.runs(cv, art, bx, ground + 8, bob)
        for (x, y, n) in _CORNERS[sw, sh]:            # round the scene's corners
            cv.rect(x, y, n, 1, WHITE)
        tft.blit(cv.buf, sx, sy, sw, sh)


def _corner_mask(sw, sh, r=6):
    out = []
    for y in range(r):
        n = r - int(math.sqrt(r * r - (r - y - 0.5) ** 2) + 0.5)
        if n > 0:
            out += [(0, y, n), (sw - n, y, n), (0, sh - 1 - y, n), (sw - n, sh - 1 - y, n)]
    return out


_CORNERS = {}


class BusScreen:
    def __init__(self, tft, fonts, pool, n, location):
        self.tft, self.f, self.pool = tft, fonts, pool
        self.n, self.location = n, location
        self.lanes = [Lane(b, i) for i, b in enumerate(lane_boxes(n))]
        for ln in self.lanes:
            ln.font_small = fonts["small"]
            _CORNERS.setdefault((ln.scene[2], ln.scene[3]),
                                _corner_mask(ln.scene[2], ln.scene[3]))

    def start(self):
        gfx.stream_bg(self.tft, "assets/bus%d.bin" % self.n, self.pool)
        self.head = None
        for ln in self.lanes:
            ln.key = ln.plan = None
            ln.text = None

    def frame(self, lanes, clock, hour, stale, t):
        pulse = int(t * 2) % 2
        head = (clock, stale, pulse)
        if head != self.head:
            self.head = head
            self._header(clock, stale, pulse)
        for ln, data in zip(self.lanes, lanes):
            route, headsign, deps, msg = data
            city = "britomart" in headsign.lower() or "city" in headsign.lower()
            key = (city, int(hour * 12))              # rebuild scenery every 5 min
            if key != ln.key:
                ln.key = key
                ln.build(city, hour)
            nxt = None if msg else (deps[0] if deps else None)
            txt = self._row_state(route, headsign, deps, msg, nxt)
            if txt != ln.text:
                ln.text = txt
                self._row(ln, txt)
            ln.draw_scene(self.tft, self.pool, nxt, txt[4], t)

    @staticmethod
    def _row_state(route, headsign, deps, msg, nxt):
        if msg:
            return (route, headsign, "--", INK, msg, "", INK)
        if nxt is None:
            return (route, headsign, "--", INK, "", "none soon", INK)
        m = max(0, int(nxt[0]) // 60)
        if nxt[2]:
            big, col = "X", WARN
        elif m == 0:
            big, col = "Due", LIVE
        else:
            big, col = str(m), NAVY
        rest = [str(max(0, int(e) // 60)) for e, _, c in deps[1:3] if not c]
        sub = ("then " + ", ".join(rest)) if rest else ""
        status = "cancelled" if nxt[2] else ("live" if nxt[1] else "scheduled")
        return (route, headsign, big, col, sub, status, LIVE if nxt[1] and not nxt[2] else INK)

    def _row(self, ln, s):
        route, headsign, big, col, sub, status, scol = s
        x, y, w, h = ln.row
        cv = gfx.Canvas(memoryview(self.pool)[:w * h * 2], w, h)
        cv.fill(WHITE)
        ft, fh, fb, fs = self.f["title"], self.f["head"], self.f["big"], self.f["small"]
        bw = ft.width(route) + 14
        cv.rrect(0, 3, bw, 19, 9, BUS)
        cv.text(ft, route, (bw - ft.width(route)) // 2, 3 + (19 - ft.h) // 2, WHITE)
        cv.text(fh, headsign, bw + 8, 3, NAVY)
        if status:
            if status == "live":
                cv.ellipse(bw + 11, 23, 2, 2, LIVE)
                cv.text(fs, "live", bw + 16, 17, scol)
            else:
                cv.text(fs, status, bw + 8, 17, scol)
        if big in ("--", "Due", "X"):
            cv.text(fb, big, w - 2 - fb.width(big), 0, col)
        else:
            fm = self.f["smallb"]
            cv.text(fm, "min", w - 2 - fm.width("min"), 14, INK)
            cv.text(fb, big, w - 26 - fb.width(big), 0, col)
        self.tft.blit(cv.buf, x, y, w, h)

    def _header(self, clock, stale, pulse):
        cv = gfx.Canvas(memoryview(self.pool)[:W * HEAD_H * 2], W, HEAD_H)
        cv.fill(AT_BLUE)
        cv.text(self.f["title"], self.location, 8, (HEAD_H - self.f["title"].h) // 2, WHITE)
        fc = self.f["clock"]
        cx = W - 8 - fc.width(clock)
        cv.text(fc, clock, cx, (HEAD_H - fc.h) // 2, WHITE)
        dot = WARN if stale else (LIVE if pulse else rgb(170, 240, 180))
        cv.ellipse(cx - 11, HEAD_H // 2, 3, 3, dot)
        fs = self.f["smallb"]
        lab = "STALE" if stale else "LIVE"
        cv.text(fs, lab, cx - 17 - fs.width(lab), (HEAD_H - fs.h) // 2, rgb(200, 220, 245))
        self.tft.blit(cv.buf, 0, 0, W, HEAD_H)
