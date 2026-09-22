# AT Departure Board

An ESP32 with a 2.0" ST7789 colour display (GMT020-02, 320x240) that shows:

- **Bus**: live Auckland Transport departures for one stop (default **8669
  Aldersgate Rd**, 27H to Britomart)
- **Rail**: a live map of the post-CRL train network (E-W, S-C, O-W lines) with
  every train drawn as a moving dot

Press the **BOOT** button to switch screens. Inspired by
[MSMGreen/at-departure-board](https://github.com/MSMGreen/at-departure-board).

## How it works

The ESP32 doesn't use WiFi. `bridge.py` runs on the PC. It fetches from the AT
API, works out the countdowns and train positions, and sends one JSON line per
screen over the USB cable every 5 s. The board only draws, and it replies `ok`
after each line so its small serial buffer never overflows.

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
2. `cp config.example.py config.py` and add your AT API key
   (dev-portal.at.govt.nz, "GTFS" product) and stop code.
3. Upload the board files:

       python -m mpremote connect COM13 fs cp st7789.py :st7789.py + fs cp config.py :config.py + fs cp ui.py :ui.py + fs cp bus.py :bus.py + fs cp rail.py :rail.py + fs cp railmap.py :railmap.py + fs cp main.py :main.py + reset

4. On the PC: `pip install pyserial`, then `python bridge.py` (leave it running).

## Files

| File | Where | What |
|---|---|---|
| `bridge.py` | PC | AT API fetching, bus countdowns, snaps train GPS onto the map |
| `main.py` | board | serial reader, BOOT-button screen switch |
| `bus.py`, `rail.py`, `ui.py`, `st7789.py` | board | drawing |
| `railmap.py` | both | generated map data (`python tools/gen_railmap.py`) |
| `tools/preview.py` | PC | render a screen to PNG with live data, no hardware needed |

## Notes

- SPI runs at 20 MHz. At 40 MHz, breadboard jumper wires corrupt long fills.
- Trains are found by vehicle ID (all AT trains are 59xxx). That cuts the
  600 KB all-vehicle feed down to about 30 KB.
- Each train's GPS position is snapped to the nearest straight segment between
  two stations on its line. Trains more than 1.5 km from their line (depots)
  are hidden.
