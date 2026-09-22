# Live Auckland train map (board side) -- post-CRL network, every train a dot.
# Draws what bridge.py sends:
# {"t": "rail", "clock": "5:28", "msg": "upd 5:28", "counts": [n, n, n],
#  "trains": [[x, y, line], ...]}      (positions already snapped to the map)
import railmap as M
from ui import tft, rgb, BG, HEAD, WHITE, GREY, RED, W, H

TOP = 18                    # title bar height
LABEL = rgb(190, 200, 215)
CRL_GOLD = rgb(255, 200, 60)

def _pts(x0, y0, x1, y1):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _hit(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def draw_seg(s, clip=None):
    li, x0, y0, x1, y1 = s[0], s[1], s[2], s[3], s[4]
    c = M.LINES[li][1]
    if clip and not _hit(min(x0, x1) - 1, min(y0, y1) - 1, abs(x1 - x0) + 3,
                         abs(y1 - y0) + 3, *clip):
        return
    if x0 == x1 or y0 == y1:
        x, y = min(x0, x1) - 1, min(y0, y1) - 1
        w, h = abs(x1 - x0) + 3, abs(y1 - y0) + 3
        if clip:
            cx, cy, cw, ch = clip
            nx, ny = max(x, cx), max(y, cy)
            w, h = min(x + w, cx + cw) - nx, min(y + h, cy + ch) - ny
            x, y = nx, ny
        tft.fill_rect(x, y, w, h, c)
        return
    for x, y in _pts(x0, y0, x1, y1):
        if clip and not _hit(x - 1, y - 1, 3, 3, *clip):
            continue
        tft.fill_rect(x - 1, y - 1, 3, 3, c)


def draw_station(st):
    x, y, crl = st
    if crl:
        tft.fill_rect(x - 4, y - 4, 9, 9, WHITE)
        tft.fill_rect(x - 2, y - 2, 5, 5, CRL_GOLD)
    else:
        tft.fill_rect(x - 2, y - 2, 5, 5, WHITE)


def draw_label(lb):
    t, x, y, crl = lb
    tft.text(t, x, y, CRL_GOLD if crl else LABEL, BG)


def redraw_area(x, y, w, h):
    # put back whatever map sits under a train that has moved on
    tft.fill_rect(x, y, w, h, BG)
    clip = (x, y, w, h)
    for s in M.SEGS:
        draw_seg(s, clip)
    for st in M.STATIONS:
        if _hit(st[0] - 4, st[1] - 4, 9, 9, x, y, w, h):
            draw_station(st)
    for lb in M.LABELS:
        if _hit(lb[1], lb[2], len(lb[0]) * 8, 8, x, y, w, h):
            draw_label(lb)


class RailScreen:
    def start(self):
        self.marks = []
        self.clock = self.leg = None
        tft.fill(BG)
        tft.fill_rect(0, 0, W, TOP, HEAD)
        tft.text("AKL TRAINS", 6, 1, WHITE, HEAD, 2)
        tft.text("LIVE", 170, 5, RED, HEAD)
        for s in M.SEGS:
            draw_seg(s)
        for st in M.STATIONS:
            draw_station(st)
        for lb in M.LABELS:
            draw_label(lb)

    def render(self, m):
        if m["clock"] != self.clock:
            self.clock = s = m["clock"]
            tft.fill_rect(W - 90, 0, 90, TOP, HEAD)
            tft.text(s, W - 6 - len(s) * 16, 1, WHITE, HEAD, 2)
        self.draw_trains([tuple(t) for t in m["trains"]])
        leg = (tuple(m["counts"]) if m["counts"] else None, m["msg"])
        if leg != self.leg:
            self.leg = leg
            self.legend(*leg)

    def legend(self, counts, msg=""):
        x, y = 6, 164
        tft.fill_rect(x, y, 116, 56, BG)
        for i, (name, col) in enumerate(M.LINES):
            yy = y + i * 12
            tft.fill_rect(x, yy, 14, 8, col)
            n = "" if counts is None else "%2d" % counts[i]
            tft.text("%s %s" % (name, n), x + 20, yy, LABEL, BG)
        tft.text("CRL", x, y + 38, CRL_GOLD, BG)
        tft.text(msg[:14], x + 32, y + 38, GREY, BG)

    def draw_trains(self, new):
        keep = set(new)
        for x, y, _ in set(self.marks) - keep:
            redraw_area(x - 3, y - 3, 7, 7)
        # redraw all, not just movers: an erase can clip a neighbouring train
        for x, y, li in new:
            tft.fill_rect(x - 3, y - 3, 7, 7, WHITE)
            tft.fill_rect(x - 2, y - 2, 5, 5, M.LINES[li][1])
        self.marks = new
