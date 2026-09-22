# Bus departures screen (board side) -- draws what bridge.py sends:
# {"t": "bus", "name": ..., "code": ..., "clock": "5:28", "status": ...,
#  "rows": [[route, dest, big, big_col, info, info_col, live], ...]}
from ui import tft, rgb, BG, HEAD, AT_BLUE, WHITE, GREY, DIM, GREEN, AMBER, RED, W, H

ROW_Y, ROW_H, ROWS = 46, 44, 4
COL = {"w": WHITE, "g": GREEN, "a": AMBER, "r": RED, "y": GREY}


class BusScreen:
    def start(self):
        self.name = self.clock = self.status = None
        self.rows = [None] * ROWS
        tft.fill(BG)

    def render(self, m):
        if (m["name"], m["code"]) != self.name:
            self.name = (m["name"], m["code"])
            tft.fill_rect(0, 0, W, 40, HEAD)
            tft.text(m["name"][:13], 8, 6, WHITE, HEAD, 2)   # stops short of the clock
            tft.text("Stop " + m["code"], 8, 27, rgb(170, 200, 230), HEAD)
            self.clock = None
        if m["clock"] != self.clock:
            self.clock = s = m["clock"]
            tft.fill_rect(W - 90, 8, 90, 20, HEAD)
            tft.text(s, W - 8 - tft.text_width(s, 2), 12, WHITE, HEAD, 2)
        rows = m["rows"]
        for i in range(ROWS):
            self.row(i, rows[i] if i < len(rows) else None)
        st = (m["status"], m.get("err", False))
        if st != self.status:
            self.status = st
            tft.fill_rect(0, H - 18, W, 18, BG)
            tft.text(st[0][:40], 8, H - 13, RED if st[1] else GREY, BG)

    def row(self, i, r):
        key = r if r else ("-" if i else "none")
        if key == self.rows[i]:
            return
        self.rows[i] = key
        y = ROW_Y + i * ROW_H
        tft.fill_rect(0, y, W, ROW_H, BG)
        if i:
            tft.hline(8, y - 2, W - 16, DIM)
        if not r:
            if i == 0:
                tft.text("No buses in the next 3h", 8, y + 14, GREY, BG)
            return
        route, dest, big, big_col, info, info_col, live = r
        tft.fill_rect(8, y + 4, 56, 32, AT_BLUE)
        route = route[:3]
        tft.text(route, 8 + (56 - tft.text_width(route, 2)) // 2, y + 12, WHITE, AT_BLUE, 2)
        tft.text(dest[:9], 72, y + 5, WHITE, BG, 2)
        tft.text(info, 72, y + 27, COL.get(info_col, GREY), BG)
        tft.text(big, W - 8 - tft.text_width(big, 3), y + 8, COL.get(big_col, WHITE), BG, 3)
        if live:
            tft.fill_rect(W - 14, y + 36, 6, 4, GREEN)   # live indicator
