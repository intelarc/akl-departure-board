# AT departure board (board side). No WiFi: bridge.py on the PC fetches
# everything and sends one JSON line per update over the USB cable.
# Press the BOOT button to switch between the bus stop and the train map.
import sys, select, json, time, machine
import config as C
from ui import splash
from bus import BusScreen
from rail import RailScreen

SCREENS = ("bus", "rail")
STALE_MS = 90_000          # no data this long -> show "waiting for PC"

_pressed = False


def _on_button(pin):
    global _pressed
    _pressed = True


btn = machine.Pin(0, machine.Pin.IN, machine.Pin.PULL_UP)   # BOOT button
btn.irq(_on_button, machine.Pin.IRQ_FALLING)


def main():
    global _pressed
    screens = {"bus": BusScreen(), "rail": RailScreen()}
    cur = getattr(C, "START_SCREEN", "bus")
    latest = {}
    started = dirty = False
    last_rx = time.ticks_ms()
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    splash("Waiting for the PC...", "run: python bridge.py")
    print("board ready")
    while True:
        if _pressed:
            time.sleep_ms(50)                 # debounce
            _pressed = False
            cur = SCREENS[(SCREENS.index(cur) + 1) % len(SCREENS)]
            started = False
            dirty = True
        got = False
        if poll.poll(50):
            got = True
            line = sys.stdin.readline()
            try:
                m = json.loads(line)
                latest[m["t"]] = m
                last_rx = time.ticks_ms()
                if m["t"] == cur:
                    dirty = True
            except Exception as e:
                print("bad line:", repr(e))
        if time.ticks_diff(time.ticks_ms(), last_rx) > STALE_MS and latest:
            latest.clear()
            started = False
            splash("Lost the PC...", "run: python bridge.py")
        if dirty and cur in latest:
            dirty = False
            try:
                if not started:
                    screens[cur].start()
                    started = True
                screens[cur].render(latest[cur])
            except Exception as e:
                print("draw error:", repr(e))
                started = False
        if got:
            print("ok")        # flow control: the PC waits for this before sending more


main()
