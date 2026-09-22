# Auckland Transport bus departure board -- ESP32 + 2.0" ST7789 (320x240)
import time, gc, network, ntptime, machine
import requests
import config as C
from st7789 import ST7789, rgb

API = "https://api.at.govt.nz"
HDR = {"Ocp-Apim-Subscription-Key": C.AT_API_KEY, "Accept": "application/json"}

# MicroPython on ESP32 counts from 2000-01-01, AT sends unix (1970) times
UNIX_OFS = 946684800 if time.gmtime(0)[0] == 2000 else 0

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
ROW_Y, ROW_H, ROWS = 46, 44, 4

spi = machine.SPI(2, baudrate=40_000_000, polarity=0, phase=0,
                  sck=machine.Pin(C.PIN_SCK), mosi=machine.Pin(C.PIN_MOSI))
tft = ST7789(spi, machine.Pin(C.PIN_CS), machine.Pin(C.PIN_DC),
             machine.Pin(C.PIN_RST), W, H, madctl=C.MADCTL, invert=C.INVERT)
wlan = network.WLAN(network.STA_IF)


# ---------- time (NZ, with daylight saving) ----------
def _sunday(y, m, first):
    days = range(1, 8) if first else range(30 if m == 9 else 31, 23, -1)
    for d in days:
        if time.gmtime(time.mktime((y, m, d, 12, 0, 0, 0, 0)))[6] == 6:
            return d


def nz_offset(utc):
    y = time.gmtime(utc)[0]
    # NZDT: last Sunday Sept 02:00 NZST -> first Sunday April 03:00 NZDT
    start = time.mktime((y, 9, _sunday(y, 9, False), 2, 0, 0, 0, 0)) - 12 * 3600
    end = time.mktime((y, 4, _sunday(y, 4, True), 3, 0, 0, 0, 0)) - 13 * 3600
    return 13 * 3600 if (utc >= start or utc < end) else 12 * 3600


def local(utc=None):
    utc = time.time() if utc is None else utc
    return time.gmtime(utc + nz_offset(utc))


def service_epoch(date, hms):
    # GTFS time "HH:MM:SS" (may exceed 24h) on service date "YYYY-MM-DD" -> utc
    y, m, d = (int(p) for p in date.split("-"))
    h, mi, s = (int(p) for p in hms.split(":"))
    noon = time.mktime((y, m, d, 12, 0, 0, 0, 0))
    return noon - 12 * 3600 + h * 3600 + mi * 60 + s - nz_offset(noon - 12 * 3600)


# ---------- screen ----------
def footer(msg, colour=GREY):
    tft.fill_rect(0, H - 18, W, 18, BG)
    tft.text(msg[:40], 8, H - 13, colour, BG)


def splash(line1, line2=""):
    tft.fill(BG)
    tft.text("AT Departures", 56, 80, WHITE, BG, 2)
    tft.text(line1[:40], 8, 130, GREY, BG)
    if line2:
        tft.text(line2[:40], 8, 146, GREY, BG)


def header(name):
    tft.fill_rect(0, 0, W, 40, HEAD)
    for a, b in ((" Road", " Rd"), (" Street", " St"), (" Avenue", " Ave")):
        name = name.replace(a, b)
    tft.text(name[:13], 8, 6, WHITE, HEAD, 2)   # 13 chars stops short of the clock
    tft.text("Stop " + C.STOP_CODE, 8, 27, rgb(170, 200, 230), HEAD)


_clock = None


def draw_clock():
    global _clock
    t = local()
    s = "%d:%02d" % ((t[3] % 12) or 12, t[4])
    if s != _clock:
        _clock = s
        tft.fill_rect(W - 90, 8, 90, 20, HEAD)
        tft.text(s, W - 8 - tft.text_width(s, 2), 12, WHITE, HEAD, 2)


_rows = [None] * ROWS


def draw_row(i, dep, now):
    if dep is None:
        key = ("-" if i else "none")
    else:
        mins = (dep["eta"] - now) // 60
        key = (dep["route"], dep["dest"], mins, dep["live"], dep["delay"] // 60, dep["cancel"])
    if key == _rows[i]:
        return
    _rows[i] = key
    y = ROW_Y + i * ROW_H
    tft.fill_rect(0, y, W, ROW_H, BG)
    if i:
        tft.hline(8, y - 2, W - 16, DIM)
    if dep is None:
        if i == 0:
            tft.text("No buses in the next 3h", 8, y + 14, GREY, BG)
        return
    # route badge
    tft.fill_rect(8, y + 4, 56, 32, AT_BLUE)
    r = dep["route"][:3]
    tft.text(r, 8 + (56 - tft.text_width(r, 2)) // 2, y + 12, WHITE, AT_BLUE, 2)
    # destination + detail line
    tft.text(dep["dest"][:9], 72, y + 5, WHITE, BG, 2)
    t = local(dep["eta"])
    sched = "%d:%02d" % ((t[3] % 12) or 12, t[4])
    if dep["cancel"]:
        info, col = "CANCELLED", RED
    elif not dep["live"]:
        info, col = sched + " scheduled", GREY
    else:
        d = dep["delay"] // 60
        if d >= 2:
            info, col = "%s  %d min late" % (sched, d), AMBER
        elif d <= -2:
            info, col = "%s  %d min early" % (sched, -d), AMBER
        else:
            info, col = sched + "  on time", GREEN
    tft.text(info, 72, y + 27, col, BG)
    # countdown
    if dep["cancel"]:
        big, col = "--", RED
    elif mins <= 0:
        big, col = "Due", GREEN
    else:
        big, col = "%dm" % mins, (WHITE if dep["live"] else GREY)
    tft.text(big, W - 8 - tft.text_width(big, 3), y + 8, col, BG, 3)
    if dep["live"] and not dep["cancel"]:
        tft.fill_rect(W - 14, y + 36, 6, 4, GREEN)   # live indicator


# ---------- network ----------
def wifi():
    if wlan.isconnected():
        return True
    if not wlan.active():
        wlan.active(True)
        try:
            wlan.config(txpower=8)   # full power browns out on weak USB supplies
        except Exception:
            pass
    if wlan.status() != network.STAT_CONNECTING:
        try:
            wlan.disconnect()
        except Exception:
            pass
        wlan.connect(C.WIFI_SSID, C.WIFI_PASSWORD)
    for _ in range(60):
        if wlan.isconnected():
            return True
        time.sleep_ms(500)
    print("wifi status", wlan.status())
    return False


def get(path):
    gc.collect()
    r = requests.get(API + path, headers=HDR, timeout=20)
    try:
        if r.status_code == 404:        # stoptrips: 404 = no services in window
            return None
        if r.status_code != 200:
            raise OSError("HTTP %d" % r.status_code)
        return r.json()
    finally:
        r.close()
        gc.collect()


def find_stop():
    j = get("/gtfs/v3/stops?filter%5Bstop_code%5D=" + C.STOP_CODE)
    a = j["data"][0]["attributes"]
    return a["stop_id"], (C.STOP_NAME or a["stop_name"])


def _title(s):
    return " ".join(w[:1].upper() + w[1:].lower() for w in s.split())


def fetch_schedule(stop_id):
    utc = time.time()
    t = local(utc)
    queries = [("%04d-%02d-%02d" % t[:3], t[3])]
    if t[3] < 3:   # after midnight, late trips still belong to yesterday
        y = local(utc - 86400)
        queries.append(("%04d-%02d-%02d" % y[:3], t[3] + 24))
    trips = {}
    for date, hour in queries:
        j = get("/gtfs/v3/stops/%s/stoptrips?filter%%5Bdate%%5D=%s"
                "&filter%%5Bstart_hour%%5D=%d&hour_range=3" % (stop_id, date, hour))
        for e in (j or {}).get("data", []):
            a = e["attributes"]
            if a.get("pickup_type") == 1:
                continue
            route = a["route_id"].split("-")[0]
            if C.ROUTE and route != C.ROUTE:
                continue
            dest = (a.get("stop_headsign") or a.get("trip_headsign") or "").strip()
            trips[a["trip_id"]] = {
                "route": route, "dest": _title(dest), "seq": a["stop_sequence"],
                "sched": service_epoch(a["service_date"], a["departure_time"]),
                "delay": 0, "live": False, "cancel": False, "gone": False,
            }
    return trips


def fetch_realtime(trips, now):
    ids = [k for k, v in trips.items() if -600 < v["sched"] - now < 3 * 3600][:8]
    if not ids:
        return
    j = get("/realtime/legacy/tripupdates?tripid=" + ",".join(ids))
    for ent in j["response"].get("entity") or []:
        tu = ent.get("trip_update")
        if not tu:
            continue
        tid = tu["trip"]["trip_id"]
        if tid not in trips:           # the tripid filter is inexact
            continue
        tr = trips[tid]
        if ent.get("is_deleted") or tu["trip"].get("schedule_relationship") == 3:
            tr["cancel"] = True
            continue
        stu = tu.get("stop_time_update") or {}
        if isinstance(stu, list):
            stu = stu[-1] if stu else {}
        ev = stu.get("departure") or stu.get("arrival") or {}
        seq = stu.get("stop_sequence", 0)
        if seq > tr["seq"]:
            tr["gone"] = True          # bus already went past our stop
            continue
        if seq == tr["seq"] and ev.get("time"):
            tr["delay"] = ev["time"] - UNIX_OFS - tr["sched"]
        else:
            tr["delay"] = ev.get("delay", tu.get("delay", 0)) or 0
        tr["live"] = True


def upcoming(trips, now):
    out = []
    for v in trips.values():
        v["eta"] = v["sched"] + v["delay"]
        if not v["gone"] and v["eta"] >= now - 30:
            out.append(v)
    out.sort(key=lambda v: v["eta"])
    return out[:ROWS]


# ---------- main loop ----------
def main():
    splash("Connecting to WiFi", C.WIFI_SSID)
    while not wifi():
        splash("WiFi: can't find " + C.WIFI_SSID, "retrying... (move closer to router?)")
    print("wifi up", wlan.ifconfig()[0])
    splash("Setting clock...")
    for _ in range(10):
        try:
            ntptime.settime()
            break
        except Exception:
            time.sleep(2)
    splash("Finding stop " + C.STOP_CODE)
    while True:
        try:
            stop_id, name = find_stop()
            break
        except Exception as e:
            splash("Stop lookup failed", str(e))
            time.sleep(10)

    tft.fill(BG)
    header(name)
    trips, t_sched, t_rt, status = {}, -10**9, -10**9, ""
    while True:
        now = time.time()
        try:
            if not wifi():
                raise OSError("WiFi down")
            if now - t_sched >= (C.SCHEDULE_EVERY if trips else 60):
                old = trips
                trips = fetch_schedule(stop_id)
                for k, v in old.items():      # keep live data across refresh
                    if k in trips:
                        for f in ("delay", "live", "cancel", "gone"):
                            trips[k][f] = v[f]
                t_sched = now
            if now - t_rt >= C.REALTIME_EVERY:
                fetch_realtime(trips, now)
                t_rt = now
                t = local()
                msg, col = "Updated %d:%02d:%02d" % ((t[3] % 12) or 12, t[4], t[5]), GREY
                print(msg, gc.mem_free(), [(v["route"], (v["eta"] - now) // 60, v["live"]) for v in upcoming(trips, now)])
                if msg != status:
                    footer(msg, col)
                    status = msg
        except Exception as e:
            print("error:", repr(e))
            footer("Error: " + str(e), RED)
            status = ""
            t_rt = now      # back off before retrying
            t_sched = max(t_sched, now - C.SCHEDULE_EVERY + 30)
        deps = upcoming(trips, now)
        draw_clock()
        for i in range(ROWS):
            draw_row(i, deps[i] if i < len(deps) else None, now)
        time.sleep(1)


main()
