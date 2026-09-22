# Bus departure board settings -- edit these, then copy to the ESP32.

WIFI_SSID = "your-wifi"
WIFI_PASSWORD = "your-password"

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
# If colours look inverted (black background shows white), set False.
INVERT = True

# How often to ask AT for data (seconds)
SCHEDULE_EVERY = 300
REALTIME_EVERY = 30
