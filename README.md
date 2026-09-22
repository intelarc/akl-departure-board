# AT Departure Board

An ESP32 with a 2.0" ST7789 colour display (GMT020-02, 320x240) showing live
Auckland Transport data, driven by your PC over USB:

- **Bus**: approach lanes where each bus slides toward the stop as it gets
  closer. Default: the 27H both ways at Aldersgate Rd, Hillsborough (stops
  8669 and 8664). The UI is from
  [MSMGreen/at-departure-board](https://github.com/MSMGreen/at-departure-board)
  (MIT, vendored in `atboard/`).
- **Rail**: a live map of the post-CRL network (E-W, S-C, O-W) in the style of
  AT's network map, with every train drawn as a dot.

Press **BOOT** on the ESP32 to switch screens.

## How it works

The ESP32 has no WiFi and does no fetching. It's a plain USB display.
`bridge.py` on the PC fetches from the AT API, renders each 320x240 frame with
Pillow, and sends only the changed rectangles, run-length encoded, at
230400 baud. The board decodes them with a viper function and replies `K`
after each rectangle (`B` when BOOT is pressed).

## Wiring

| Display | ESP32 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SCL | GPIO 18 |
| SDA | GPIO 23 |
| CS  | GPIO 5 |
| DC  | GPIO 16 |
| RST | GPIO 17 |

## Setup

1. Flash MicroPython (ESP32_GENERIC, v1.29) at 0x1000.
2. `cp config.example.py config.py`, then add your AT API key
   (dev-portal.at.govt.nz, "GTFS" product) and your stops.
3. Upload the board files (bridge.py must not be running):

       python -m mpremote connect COM13 fs cp st7789.py :st7789.py + fs cp config.py :config.py + fs cp ui.py :ui.py + fs cp main.py :main.py + reset

4. On the PC: `pip install pyserial pillow numpy`, then `python bridge.py`
   and leave it running. `python bridge.py --preview` saves bus.png and
   rail.png without the board.

## Files

| File | Where | What |
|---|---|---|
| `bridge.py` | PC | AT data, frame rendering, USB link |
| `railview.py` | PC | the rail map and GPS-to-map train placement |
| `atboard/` | PC | bus-lane renderer from MSMGreen/at-departure-board (MIT) |
| `main.py`, `ui.py`, `st7789.py` | board | USB display |
| `tools/stations.json` | PC | station coordinates from AT GTFS |

## Notes

- The board resets itself 20 s after the PC stops sending, which puts it back
  at 115200 baud so mpremote can reach it.
- Links faster than 230400 baud drop bytes: MicroPython drains stdin one
  character at a time. MicroPython 1.29 also throws `ESP_ERR_INVALID_STATE`
  when the REPL UART's baud is changed, but the change still takes effect.
- SPI runs at 20 MHz. At 40 MHz, breadboard jumper wires corrupt long fills.
