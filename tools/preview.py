# Render a screen to PNG on the PC using the real board code + live AT data.
#   python tools/preview.py rail out.png
#   python tools/preview.py bus out.png
import sys, os, types, time, calendar, json, urllib.request, urllib.error

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PIL import Image, ImageDraw

# --- MicroPython shims ---
time.sleep_ms = lambda ms: None
import gc; gc.mem_free = lambda: 0
time.mktime = lambda t: calendar.timegm(tuple(t[:6]) + (0, 0, 0))


class _Pin:
    OUT = IN = PULL_UP = IRQ_FALLING = 1
    def __init__(s, *a, **k): pass
    def init(s, *a, **k): pass
    def irq(s, *a, **k): pass
    def __call__(s, *a): pass


m = types.ModuleType("machine")
m.Pin = _Pin
m.SPI = lambda *a, **k: None
sys.modules["machine"] = m
n = types.ModuleType("network")
n.STA_IF, n.STAT_CONNECTING = 0, 1
n.WLAN = lambda *a: types.SimpleNamespace(isconnected=lambda: True)
sys.modules["network"] = n
sys.modules["ntptime"] = types.ModuleType("ntptime")
mp = types.ModuleType("micropython")
mp.const = lambda x: x
sys.modules["micropython"] = mp
sys.modules["framebuf"] = types.ModuleType("framebuf")


class _Resp:
    def __init__(s, url, headers):
        try:
            s.r = urllib.request.urlopen(urllib.request.Request(url, headers=headers))
            s.status_code = 200
        except urllib.error.HTTPError as e:
            s.r, s.status_code = e, e.code
        s.raw = s.r
    def json(s): return json.load(s.r)
    def close(s): pass


rq = types.ModuleType("requests")
rq.get = lambda url, headers=None, timeout=None: _Resp(url, headers)
sys.modules["requests"] = rq


# --- fake display drawing into an image ---
class FakeTFT:
    def __init__(s, *a, **k):
        s.img = Image.new("RGB", (320, 240))
        s.d = ImageDraw.Draw(s.img)
        s.width, s.height = 320, 240

    @staticmethod
    def _c(c):
        return ((c >> 11) << 3, ((c >> 5) & 0x3F) << 2, (c & 0x1F) << 3)

    def fill_rect(s, x, y, w, h, c):
        if w > 0 and h > 0:
            s.d.rectangle([x, y, x + w - 1, y + h - 1], fill=s._c(c))

    def fill(s, c): s.fill_rect(0, 0, 320, 240, c)
    def hline(s, x, y, w, c): s.fill_rect(x, y, w, 1, c)

    @staticmethod
    def text_width(t, scale=1): return len(t) * 8 * scale

    def text(s, t, x, y, fg, bg=0, scale=1):
        # approximate the 8x8 font with PIL's bitmap font
        from PIL import ImageFont
        t = t[:min(40, 320 // (8 * scale))]
        s.fill_rect(x, y, len(t) * 8 * scale, 8 * scale, bg)
        f = ImageFont.load_default(size=9 * scale)
        for i, ch in enumerate(t):
            s.d.text((x + i * 8 * scale, y - scale), ch, fill=s._c(fg), font=f)


import st7789
st7789.ST7789 = FakeTFT


def main():
    # messages from the real bridge code, drawn by the real board screens
    which = sys.argv[1] if len(sys.argv) > 1 else "rail"
    out = sys.argv[2] if len(sys.argv) > 2 else "preview.png"
    import bridge, ui, rail, bus
    if which == "rail":
        src, scr = bridge.Trains(), rail.RailScreen()
    else:
        src, scr = bridge.Buses(), bus.BusScreen()
    src.update()
    scr.start()
    scr.render(json.loads(json.dumps(src.message())))
    img = ui.tft.img.resize((960, 720), Image.NEAREST)
    img.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
