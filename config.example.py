# Settings for bridge.py (PC) and the board. Copy to the ESP32 too (pins).

# Auckland Transport developer key (dev-portal.at.govt.nz)
AT_API_KEY = "your-at-api-key"

# 4-digit number on the bus stop sign. 8669 = Aldersgate Road (27H to Britomart)
STOP_CODE = "8669"
STOP_NAME = ""        # leave "" to use AT's name for the stop
ROUTE = ""            # e.g. "27H" to show only that route; "" = every route

# Display wiring (GMT020-02 2.0" ST7789, 240x320)
PIN_SCK = 18   # display SCL
PIN_MOSI = 23  # display SDA
PIN_CS = 5
PIN_DC = 16
PIN_RST = 17

# If the picture is mirrored/upside-down, try 0xA0, 0x20 or 0xE0.
MADCTL = 0x60
# SPI speed: 40MHz glitches over breadboard jumper wires
SPI_HZ = 20_000_000
# If colours look inverted (black background shows white), set False.
INVERT = True

# USB port of the board; "" = find the CH340 automatically
SERIAL_PORT = ""

# How often to ask AT for data (seconds)
SCHEDULE_EVERY = 300
REALTIME_EVERY = 30

# Screen shown at power-up: "bus" or "rail". The BOOT button switches.
START_SCREEN = "bus"
