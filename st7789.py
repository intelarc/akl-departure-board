# Minimal ST7789 driver for MicroPython (no full framebuffer -- the ESP32
# has no PSRAM, and 320x240x2 = 150KB would not fit). Draws rects and
# scaled text straight to the panel.
import time, framebuf
from micropython import const

_SWRESET = const(0x01)
_SLPOUT = const(0x11)
_NORON = const(0x13)
_INVON = const(0x21)
_INVOFF = const(0x20)
_DISPON = const(0x29)
_CASET = const(0x2A)
_RASET = const(0x2B)
_RAMWR = const(0x2C)
_MADCTL = const(0x36)
_COLMOD = const(0x3A)


def rgb(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def _swap(c):
    # framebuf stores RGB565 little-endian, the panel wants big-endian
    return ((c & 0xFF) << 8) | (c >> 8)


class ST7789:
    def __init__(self, spi, cs, dc, rst, width=320, height=240,
                 madctl=0x60, invert=True, xoff=0, yoff=0):
        self.spi, self.cs, self.dc, self.rst = spi, cs, dc, rst
        self.width, self.height = width, height
        self.xoff, self.yoff = xoff, yoff
        self._fillbuf = bytearray(512)
        self._fillmv = memoryview(self._fillbuf)
        self._mono = bytearray(40 * 8)
        self._line = bytearray(width * 2)
        self._linemv = memoryview(self._line)
        cs.init(cs.OUT, value=1)
        dc.init(dc.OUT, value=0)
        rst.init(rst.OUT, value=1)
        self._reset()
        self._cmd(_SWRESET)
        time.sleep_ms(150)
        self._cmd(_SLPOUT)
        time.sleep_ms(120)
        self._cmd(_COLMOD, b"\x55")        # 16-bit colour
        self._cmd(_MADCTL, bytes([madctl]))
        self._cmd(_INVON if invert else _INVOFF)
        self._cmd(_NORON)
        self.fill(0)
        self._cmd(_DISPON)
        time.sleep_ms(20)

    def _reset(self):
        self.rst(1); time.sleep_ms(10)
        self.rst(0); time.sleep_ms(20)
        self.rst(1); time.sleep_ms(150)

    def _cmd(self, c, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes([c]))
        if data:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _window(self, x, y, w, h):
        x0, y0 = x + self.xoff, y + self.yoff
        x1, y1 = x0 + w - 1, y0 + h - 1
        self._cmd(_CASET, bytes([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
        self._cmd(_RASET, bytes([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes([_RAMWR]))
        self.dc(1)

    def fill_rect(self, x, y, w, h, c):
        if w <= 0 or h <= 0:
            return
        self._window(x, y, w, h)
        total = w * h
        mv = self._fillbuf
        hi, lo = c >> 8, c & 0xFF
        for i in range(0, 256 * 2, 2):
            mv[i] = hi
            mv[i + 1] = lo
        while total > 0:
            n = min(total, 256)
            self.spi.write(self._fillmv[:n * 2])
            total -= n
        self.cs(1)

    def fill(self, c):
        self.fill_rect(0, 0, self.width, self.height, c)

    def hline(self, x, y, w, c):
        self.fill_rect(x, y, w, 1, c)

    def blit(self, buf, x, y, w, h):
        self._window(x, y, w, h)
        self.spi.write(buf)
        self.cs(1)

    @staticmethod
    def text_width(s, scale=1):
        return len(s) * 8 * scale

    def text(self, s, x, y, fg, bg=0, scale=1):
        # built-in 8x8 font, scaled up one pixel-row at a time into small
        # preallocated buffers (big temporary buffers fragment the heap and
        # starve the TLS handshake)
        s = s[:min(40, self.width // (8 * scale))]
        if not s:
            return
        w = len(s) * 8
        W = w * scale
        mfb = framebuf.FrameBuffer(self._mono, w, 8, framebuf.MONO_HLSB)
        mfb.fill(0)
        mfb.text(s, 0, 0, 1)
        lfb = framebuf.FrameBuffer(self._line, W, 1, framebuf.RGB565)
        b, f = _swap(bg), _swap(fg)
        line = self._linemv[:W * 2]
        px = mfb.pixel
        self._window(x, y, W, 8 * scale)
        for yy in range(8):
            lfb.fill(b)
            for xx in range(w):
                if px(xx, yy):
                    lfb.hline(xx * scale, 0, scale, f)
            for _ in range(scale):
                self.spi.write(line)
        self.cs(1)
