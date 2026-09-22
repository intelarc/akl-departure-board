# AT departure board (board side): a plain USB display. bridge.py on the PC
# renders every frame and sends only the rectangles that changed.
#
# Boot: 115200 baud, normal REPL behaviour, "Waiting for the PC" splash.
# The PC sends "HELLO"; we answer "READY" and switch to 230400-baud binary:
#   PC -> board: A5 5A | kind (0 raw, 1 RLE) | x y w h len (big-endian u16) | data
#     raw: w*h RGB565 pixels;  RLE: (count u8, RGB565 u16) runs
#   board -> PC: "K" after each rectangle is on screen, "B" on BOOT button press
# If the PC goes quiet the board resets itself (back to 115200, so mpremote
# can reach it again).
import sys, select, struct, time, machine, micropython
from ui import tft, splash

FAST = 230_400             # faster loses bytes: stdin is drained one char at a time
IDLE_MS = 20_000
MAX_PX = 8192              # biggest rectangle the PC sends (16KB buffer)
MAX_RLE = 8192             # biggest compressed payload

_pressed = False


def _on_button(pin):
    global _pressed
    _pressed = True


btn = machine.Pin(0, machine.Pin.IN, machine.Pin.PULL_UP)   # BOOT button
btn.irq(_on_button, machine.Pin.IRQ_FALLING)


@micropython.viper
def unrle(src: ptr8, n: int, dst: ptr8, cap: int) -> int:
    # expand (count, hi, lo) runs; stops at cap bytes so bad data cannot overrun
    i = 0
    o = 0
    while i + 2 < n:
        c = src[i]
        hi = src[i + 1]
        lo = src[i + 2]
        i += 3
        while c > 0 and o < cap:
            dst[o] = hi
            dst[o + 1] = lo
            o += 2
            c -= 1
    return o


def wait_hello():
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    while True:
        if poll.poll(1000) and sys.stdin.readline().strip() == "HELLO":
            return


def serve():
    global _pressed
    print("READY")
    time.sleep_ms(30)
    try:
        machine.UART(0, baudrate=FAST)
    except OSError:
        # MicroPython 1.29 applies the new baud to the REPL UART, then fails
        # a later driver step (ESP_ERR_INVALID_STATE). The baud change sticks.
        pass
    micropython.kbd_intr(-1)            # pixel data can contain Ctrl-C bytes
    rd = sys.stdin.buffer.readinto
    out = sys.stdout.buffer.write
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    one = bytearray(1)
    hdr = bytearray(11)
    buf = bytearray(MAX_PX * 2)
    mv = memoryview(buf)
    rle = bytearray(MAX_RLE)
    rmv = memoryview(rle)
    last = time.ticks_ms()
    synced = False
    while True:
        if _pressed:
            _pressed = False
            out(b"B")
        if not poll.poll(100):
            if time.ticks_diff(time.ticks_ms(), last) > IDLE_MS:
                return
            continue
        last = time.ticks_ms()
        rd(one)
        # hunt for the A5 5A sync bytes
        if not synced:
            synced = one[0] == 0xA5
            continue
        synced = False
        if one[0] != 0x5A:
            synced = one[0] == 0xA5
            continue
        got = 0
        while got < 11:
            got += rd(memoryview(hdr)[got:])
        kind, x, y, w, h, ln = struct.unpack(">BHHHHH", hdr)
        n = w * h * 2
        bad = not 0 < n <= MAX_PX * 2 or x + w > 320 or y + h > 240
        if bad or ln > (n if kind == 0 else MAX_RLE):
            continue
        dst = mv if kind == 0 else rmv
        got = 0
        while got < ln:
            got += rd(dst[got:ln])
        if kind == 1 and unrle(rle, ln, buf, n) != n:
            continue
        tft.blit(mv[:n], x, y, w, h)
        out(b"K")


splash("Waiting for the PC...", "run: python bridge.py")
print("board ready")
wait_hello()
try:
    serve()
finally:
    micropython.kbd_intr(3)
    machine.reset()
