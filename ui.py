# Display + colours shared by the screens (board side)
import machine
import config as C
from st7789 import ST7789, rgb

BG = rgb(8, 12, 24)
HEAD = rgb(0, 60, 120)
AT_BLUE = rgb(0, 114, 188)
WHITE = rgb(255, 255, 255)
GREY = rgb(140, 150, 165)
DIM = rgb(40, 48, 64)
GREEN = rgb(60, 220, 110)
AMBER = rgb(255, 180, 40)
RED = rgb(255, 80, 80)

W, H = 320, 240

# 20MHz: 40MHz corrupts long transfers over breadboard jumper wires
spi = machine.SPI(2, baudrate=getattr(C, "SPI_HZ", 20_000_000), polarity=0, phase=0,
                  sck=machine.Pin(C.PIN_SCK), mosi=machine.Pin(C.PIN_MOSI))
tft = ST7789(spi, machine.Pin(C.PIN_CS), machine.Pin(C.PIN_DC),
             machine.Pin(C.PIN_RST), W, H, madctl=C.MADCTL, invert=C.INVERT)


def splash(line1, line2=""):
    # shown until the PC connects: AT-blue title bar, bus-stop roundel
    page, blue = rgb(226, 236, 247), rgb(35, 94, 168)
    tft.fill(page)
    tft.fill_rect(0, 0, W, 30, blue)
    tft.text("AT Departures", 8, 7, WHITE, blue, 2)
    tft.fill_rect(150, 70, 20, 20, blue)          # stop sign
    tft.fill_rect(146, 74, 28, 12, blue)
    tft.fill_rect(154, 76, 12, 6, WHITE)
    tft.fill_rect(159, 90, 2, 40, rgb(120, 128, 140))
    tft.text(line1[:40], (W - len(line1[:40]) * 8) // 2, 150, rgb(26, 39, 68), page)
    if line2:
        tft.text(line2[:40], (W - len(line2[:40]) * 8) // 2, 166, rgb(86, 100, 126), page)
