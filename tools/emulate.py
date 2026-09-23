# Run the board's own code (atdata, busscreen, railscreen, gfx) on the PC with
# live AT data and save what the ESP32 would draw. The panel is write-only,
# so this is how the screenshots in docs/ are made -- and a way to preview
# changes without the hardware.
#
#   python tools/emulate.py              -> docs/bus-day.png, bus-dusk.png,
#                                           bus-night.png, rail.png
#   python tools/emulate.py --out DIR    -> somewhere else
#
# MicroPython-only pieces are shimmed: framebuf (drawn with numpy/Pillow),
# the viper decorator (plain Python runs the same code), the 2000-based
# clock, and net (fetches directly instead of through netproxy).
import builtins, calendar, json, os, sys, time as _time, types, urllib.request
import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)                       # the board code opens "assets/..."
UNIX = 946684800


# ---------- micropython ----------
mp = types.ModuleType("micropython")
mp.viper = mp.native = lambda f: f
mp.const = lambda x: x
sys.modules["micropython"] = mp
builtins.ptr8 = builtins.ptr16 = object          # viper's annotations


# ---------- framebuf (RGB565, stored little-endian like the ESP32) ----------
fbm = types.ModuleType("framebuf")
fbm.RGB565 = 1


class FrameBuffer:
    def __init__(self, buf, w, h, fmt):
        self.a = np.frombuffer(buf, dtype="<u2", count=w * h).reshape(h, w)
        self.w, self.h = w, h

    def fill(self, c):
        self.a[:, :] = c

    def fill_rect(self, x, y, w, h, c):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 > x0 and y1 > y0:
            self.a[y0:y1, x0:x1] = c

    def hline(self, x, y, w, c):
        self.fill_rect(x, y, w, 1, c)

    def pixel(self, x, y, c=None):
        if 0 <= x < self.w and 0 <= y < self.h:
            if c is None:
                return int(self.a[y, x])
            self.a[y, x] = c

    def _mask(self, draw):
        m = Image.new("L", (self.w, self.h), 0)
        draw(ImageDraw.Draw(m))
        return np.asarray(m) > 127

    def ellipse(self, x, y, xr, yr, c, f=False, m=0xF):
        mask = self._mask(lambda d: d.ellipse((x - xr, y - yr, x + xr, y + yr), fill=255))
        self.a[mask] = c

    def poly(self, x, y, coords, c, f=False):
        pts = [(x + coords[i], y + coords[i + 1]) for i in range(0, len(coords), 2)]
        self.a[self._mask(lambda d: d.polygon(pts, fill=255))] = c


fbm.FrameBuffer = FrameBuffer
sys.modules["framebuf"] = fbm


# ---------- the ESP32's clock (seconds since 2000-01-01) ----------
bt = types.ModuleType("time")
bt.time = lambda: int(_time.time()) - UNIX
bt.gmtime = lambda t=None: tuple(_time.gmtime((bt.time() if t is None else t) + UNIX))[:8]
bt.mktime = lambda tm: calendar.timegm(tuple(tm[:6]) + (0, 0, 0)) - UNIX
bt.ticks_ms = lambda: int(_time.monotonic() * 1000)
bt.ticks_diff = lambda a, b: a - b
bt.ticks_add = lambda a, b: a + b
bt.sleep_ms = lambda ms: _time.sleep(ms / 1000)


# ---------- net: fetch directly ----------
import config as C
nm = types.ModuleType("net")
nm.last_ok, nm.idle = 0, None


def _request(url, on_chunk=None):
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": C.AT_API_KEY,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            st, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        st, body = e.code, e.read()
    if on_chunk is None:
        return st, bytearray(body)
    for i in range(0, len(body), 1024):
        on_chunk(memoryview(body)[i:i + 1024])
    return st, len(body)


nm.request = _request
sys.modules["net"] = nm


def _import_board():
    """Import the board modules with the MicroPython clock swapped in."""
    real = sys.modules["time"]
    sys.modules["time"] = bt
    try:
        import gfx, atdata, busscreen, railscreen
    finally:
        sys.modules["time"] = real
    return gfx, atdata, busscreen, railscreen


# ---------- the panel ----------
class Panel:
    def __init__(self):
        self.px = np.zeros((240, 320), dtype=np.uint16)

    def blit(self, buf, x, y, w, h):
        self.px[y:y + h, x:x + w] = np.frombuffer(bytes(buf), dtype=">u2").reshape(h, w)

    def fill_rect(self, x, y, w, h, c):
        self.px[y:y + h, x:x + w] = c

    def image(self, scale=2):
        p = self.px.astype(np.uint32)
        rgb = np.dstack(((p >> 11) << 3, ((p >> 5) & 63) << 2, (p & 31) << 3)).astype(np.uint8)
        img = Image.fromarray(rgb, "RGB")
        return img.resize((320 * scale, 240 * scale), Image.NEAREST)


def main():
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "docs")
    os.makedirs(out, exist_ok=True)
    gfx, atdata, busscreen, railscreen = _import_board()
    fonts = {n: gfx.Font("assets/%s.fnt" % n)
             for n in ("big", "clock", "title", "head", "small", "smallb")}
    pool = bytearray(38 * 1024)

    stops = [atdata.Stop(w) for w in C.WATCHES[:4]]
    for s in stops:
        s.update()
    trains = atdata.Trains()
    trains.update()
    lanes = [s.lane() for s in stops]
    print("buses:", [(l[0], l[1], [int(d[0] // 60) for d in l[2]]) for l in lanes])
    print("trains:", trains.counts)

    # the bus screen now (live), and the same data under dusk and night skies
    now_hour, now_clock = atdata.hour(), atdata.clock()
    shots = [("bus-day", now_hour if 8.5 <= now_hour <= 16.5 else 12.0, None),
             ("bus-dusk", 18.6, "18:36"), ("bus-night", 22.2, "22:12")]
    for name, hour, clk in shots:
        panel = Panel()
        scr = busscreen.BusScreen(panel, fonts, pool, len(stops), getattr(C, "LOCATION", "Auckland"))
        scr.start()
        scr.frame(lanes, clk or now_clock, hour, False, 7.5)
        panel.image().save(os.path.join(out, name + ".png"))
        print("saved", name)

    panel = Panel()
    scr = railscreen.RailScreen(panel, fonts, pool)
    scr.start()
    trains.t_moved -= 60_000                 # glide finished: markers at their fixes
    scr.frame(trains.positions(), trains.counts, now_clock, False)
    panel.image().save(os.path.join(out, "rail.png"))
    print("saved rail")


if __name__ == "__main__":
    main()
