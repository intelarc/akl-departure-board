# Settings for bridge.py (PC). The board only needs the display pins.

# Auckland Transport developer key (dev-portal.at.govt.nz, "GTFS" product)
AT_API_KEY = "your-at-api-key"

# Bus board: 1-4 lanes. stop = the number on the stop sign; route "" = any.
# label "" = work it out from AT's headsign ("to Britomart").
WATCHES = [
    {"stop": "8669", "route": "27H", "label": ""},   # Aldersgate Rd, to Britomart
    {"stop": "8664", "route": "27H", "label": ""},   # across the road, the other way
]
LOCATION = "Hillsborough"     # top-left of the bus screen
THEME = "transit"             # "transit" or "ghibli"

# Screen at start-up: "bus" or "rail". The BOOT button on the ESP32 switches.
START_SCREEN = "bus"

# USB port of the board; "" = find the CH340 automatically
SERIAL_PORT = ""

# Display wiring (GMT020-02 2.0" ST7789, 240x320) -- used on the board
PIN_SCK = 18   # display SCL
PIN_MOSI = 23  # display SDA
PIN_CS = 5
PIN_DC = 16
PIN_RST = 17
MADCTL = 0x60             # mirrored/upside-down? try 0xA0, 0x20 or 0xE0
INVERT = True             # colours inverted? set False
SPI_HZ = 20_000_000       # 40MHz glitches over breadboard jumper wires
