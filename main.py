# AT departure board -- everything runs here on the ESP32: fetching, parsing,
# placing trains and drawing. The 2.4 GHz WiFi in the house doesn't reach
# the board, so it goes online over USB instead: the PC is only its internet
# connection (netproxy.py relays HTTP over the cable).
#
# BOOT button: switch between the bus stop and the live train map.
# No PC for SLEEP_AFTER_MIN minutes: screen off, deep sleep. netproxy.py
# wakes it again when it starts (it pulses the reset line).
import gc, time, machine, esp32, micropython
from machine import Pin
import config as C
from st7789 import ST7789
import gfx
from gfx import rgb
# import everything up front, while the heap is empty: compiling the bigger
# modules needs a lot of room
import net, atdata
from busscreen import BusScreen
from railscreen import RailScreen
gc.collect()

spi = machine.SPI(2, baudrate=getattr(C, "SPI_HZ", 20_000_000), polarity=0, phase=0,
                  sck=Pin(C.PIN_SCK), mosi=Pin(C.PIN_MOSI))
tft = ST7789(spi, Pin(C.PIN_CS), Pin(C.PIN_DC), Pin(C.PIN_RST), 320, 240,
             madctl=C.MADCTL, invert=C.INVERT)

AT_BLUE, PAGE = rgb(35, 94, 168), rgb(226, 236, 247)
NAVY, INK = rgb(26, 39, 68), rgb(86, 100, 126)
SLEEP_MIN = getattr(C, "SLEEP_AFTER_MIN", 5)

gc.collect()
pool = bytearray(38 * 1024)                    # shared drawing canvas
fonts = {n: gfx.Font("assets/%s.fnt" % n)
         for n in ("big", "clock", "title", "head", "small", "smallb")}

_pressed = False


def _on_button(pin):
    global _pressed
    _pressed = True


btn = Pin(0, Pin.IN, Pin.PULL_UP)               # BOOT button
btn.irq(_on_button, Pin.IRQ_FALLING)


def splash(line1, line2=""):
    tft.fill_rect(0, 30, 320, 210, PAGE)
    cv = gfx.Canvas(memoryview(pool)[:320 * 30 * 2], 320, 30)
    cv.fill(AT_BLUE)
    cv.text(fonts["title"], "AT Departures", 10, 8, 0xFFFF)
    tft.blit(cv.buf, 0, 0, 320, 30)
    cv = gfx.Canvas(memoryview(pool)[:300 * 60 * 2], 300, 60)
    cv.fill(PAGE)
    cv.ellipse(150, 12, 11, 11, 0xFFFF)          # an AT stop roundel
    cv.ellipse(150, 12, 9, 9, AT_BLUE)
    cv.rect(145, 9, 10, 5, 0xFFFF)
    for i, (s, f, c) in enumerate(((line1, fonts["head"], NAVY), (line2, fonts["small"], INK))):
        if s:
            cv.text(f, s, (300 - f.width(s)) // 2, 30 + i * 16, c)
    tft.blit(cv.buf, 10, 95, 300, 60)


def deep_sleep():
    splash("PC is off - sleeping", "wakes when the PC starts, or press BOOT")
    time.sleep(3)
    tft.sleep()
    esp32.wake_on_ext0(pin=btn, level=esp32.WAKEUP_ALL_LOW)
    machine.deepsleep()


splash("Waiting for the PC...", "sleeping in %s min if the PC is off" % SLEEP_MIN)
if not net.hello(int(SLEEP_MIN * 60_000)):
    deep_sleep()
net.set_header("Ocp-Apim-Subscription-Key", C.AT_API_KEY)
net.set_header("Accept", "application/json")
net.sync_clock()
splash("Connected", "fetching live data...")

gc.collect()
stops = [atdata.Stop(w) for w in C.WATCHES[:4]]
trains = atdata.Trains()
screens = {"bus": BusScreen(tft, fonts, pool, len(stops), getattr(C, "LOCATION", "Auckland")),
           "rail": RailScreen(tft, fonts, pool)}
order = ("bus", "rail")
cur = getattr(C, "START_SCREEN", "bus")
screens[cur].start()
t0 = switched = last_frame = time.ticks_ms()
auto = getattr(C, "AUTO_SWITCH", 0)


def frame():
    """Draw one frame of whichever screen is showing."""
    global _pressed, cur, switched, last_frame
    start = last_frame = time.ticks_ms()
    if _pressed or (auto and time.ticks_diff(start, switched) > auto * 1000):
        time.sleep_ms(40)                       # debounce
        _pressed = False
        cur = order[(order.index(cur) + 1) % len(order)]
        switched = time.ticks_ms()
        screens[cur].start()
    t = time.ticks_diff(start, t0) / 1000
    now = time.time()
    if cur == "bus":
        stale = all(s.ok_at for s in stops) and now - min(s.ok_at for s in stops) > 120
        screens["bus"].frame([s.lane() for s in stops], atdata.clock(), atdata.hour(),
                             stale, t)
    else:
        stale = bool(trains.ok_at) and now - trains.ok_at > 90
        screens["rail"].frame(trains.positions(), trains.counts, atdata.clock(), stale)


def idle():
    # called by net while it waits on the PC, so fetches never freeze the screen
    if time.ticks_diff(time.ticks_ms(), last_frame) >= 150:
        frame()


net.idle = idle
report = time.ticks_ms()
while True:
    frame()
    if time.ticks_diff(time.ticks_ms(), report) > 60_000:
        report = time.ticks_ms()
        print("status: %s screen, %d trains, %d bytes free" %
              (cur, len(trains.now), gc.mem_free()))
    for s in stops:                             # each only fetches when it's due
        s.update()
    trains.update()
    if time.ticks_diff(time.ticks_ms(), net.last_ok) > SLEEP_MIN * 60_000:
        deep_sleep()                            # the PC has gone away
    gc.collect()
    time.sleep_ms(max(10, 150 - time.ticks_diff(time.ticks_ms(), last_frame)))
