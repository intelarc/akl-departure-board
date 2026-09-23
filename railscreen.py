# The live train map, drawn on the board: the baked map background from
# flash, then every train as a bold marker that glides between GPS fixes.
# Only the little squares that change get redrawn.
import time
import gfx
from gfx import rgb
import railgeo as G

MAP = "assets/map.bin"
AT_BLUE = rgb(35, 94, 168)
NAVY = rgb(26, 39, 68)
INK = rgb(86, 100, 126)
LIVE = rgb(60, 190, 96)
WARN = rgb(232, 150, 20)
M = G.MARK
HALF = M // 2
LEG = (5, 180, 122, 236)          # legend card (baked); counts drawn on top


class RailScreen:
    def __init__(self, tft, fonts, pool):
        self.tft, self.f, self.pool = tft, fonts, pool
        self.marks = [gfx.Sprite("assets/marker%d.spr" % i, M, M) for i in range(len(G.IDS))]
        self.bg = open(MAP, "rb")

    def start(self):
        gfx.stream_bg(self.tft, MAP, self.pool)
        self.drawn = {}            # vid -> (x, y, line) as last drawn
        self.clock = self.leg = None

    def _bg(self, cv, x, y):
        mv = memoryview(cv.buf)
        f, w = self.bg, cv.w
        for r in range(cv.h):
            f.seek(((y + r) * 320 + x) * 2)
            f.readinto(mv[r * w * 2:(r + 1) * w * 2])

    def _box(self, x, y, trains):
        """Repaint one marker-sized square: map, then every train touching it."""
        x = max(0, min(320 - M, x))
        y = max(20, min(240 - M, y))
        cv = gfx.Canvas(memoryview(self.pool)[:M * M * 2], M, M)
        self._bg(cv, x, y)
        for tx, ty, li in trains:
            if abs(tx - x) < M and abs(ty - y) < M:
                self.marks[li].draw(cv, tx - x, ty - y)
        self.tft.blit(cv.buf, x, y, M, M)

    def frame(self, trains, counts, clock, stale):
        # trains: {vid: (x, y, line)} -> whole-pixel marker corners
        now = {v: (int(x + 0.5) - HALF, int(y + 0.5) - HALF, li) for v, (x, y, li) in trains.items()}
        # the South City line draws on top, as on AT's map
        order = sorted(now.values(), key=lambda t: t[2] == 1)
        dirty = []
        for vid in set(self.drawn) | set(now):
            a, b = self.drawn.get(vid), now.get(vid)
            if a != b:
                if a:
                    dirty.append((a[0], a[1]))
                if b:
                    dirty.append((b[0], b[1]))
        for x, y in dirty:
            self._box(x, y, order)
        self.drawn = now
        if clock != self.clock:
            self.clock = clock
            cv = gfx.Canvas(memoryview(self.pool)[:60 * 20 * 2], 60, 20)
            cv.fill(AT_BLUE)
            f = self.f["clock"]
            cv.text(f, clock, 60 - 6 - f.width(clock), 1, 0xFFFF)
            self.tft.blit(cv.buf, 260, 0, 60, 20)
        leg = (tuple(counts) if counts else None, stale)
        if leg != self.leg:
            self.leg = leg
            self._legend(counts, stale)

    def _legend(self, counts, stale):
        x0, y0, x1, y1 = LEG
        f = self.f["smallb"]
        # stays clear of the card's rounded corner (radius 6)
        cv = gfx.Canvas(memoryview(self.pool)[:20 * 40 * 2], 20, 40)
        cv.fill(0xFFFF)
        for i, li in enumerate((1, 0, 2)):          # S-C, E-W, O-W, as baked
            n = "-" if counts is None else str(counts[li])
            # centred on the baked rows at y0 + 9 + 13i
            cv.text(f, n, 18 - f.width(n), 8 + i * 13 - f.h // 2, NAVY)
        self.tft.blit(cv.buf, x1 - 26, y0 + 1, 20, 40)
        cv = gfx.Canvas(memoryview(self.pool)[:110 * 12 * 2], 110, 12)
        cv.fill(0xFFFF)
        cv.ellipse(3, 6, 2, 2, WARN if stale else LIVE)
        cv.text(self.f["small"], "data is stale" if stale else "trains running now",
                9, 0, INK)
        self.tft.blit(cv.buf, x0 + 4, y1 - 13, 110, 12)
