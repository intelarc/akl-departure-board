# AT Bus Departure Board

Live Auckland Transport departures for one stop on an ESP32 + 2.0" ST7789
colour display (GMT020-02, 320x240), written in MicroPython. Inspired by
[MSMGreen/at-departure-board](https://github.com/MSMGreen/at-departure-board).

Default stop: **8669 Aldersgate Road** (27H to Britomart).

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
2. `cp config.example.py config.py` and fill in WiFi, AT API key
   (dev-portal.at.govt.nz; the "GTFS" product covers the realtime feed too), stop code.
3. Upload and reset:

       python -m mpremote connect COM13 fs cp st7789.py :st7789.py + fs cp config.py :config.py + fs cp main.py :main.py + reset

## Notes

- WiFi txpower is capped at 8 dBm: full power browned the board out on USB power.
- Display text is drawn through small preallocated buffers. Large temporary
  buffers fragment the heap and the TLS handshake then fails with
  `MBEDTLS_ERR_MPI_ALLOC_FAILED`.
- The serial console prints each refresh and any errors.
