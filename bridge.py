# PC side of the AT departure board: fetches bus times + live train positions
# from Auckland Transport and streams them to the ESP32 over USB serial.
#
#   python bridge.py            (leave it running; Ctrl+C to stop)
import json, math, sys, threading, time, calendar, urllib.request, urllib.error
import serial, serial.tools.list_ports
import config as C
import railmap as M

API = "https://api.at.govt.nz"
SEND_EVERY = 5          # s between screen updates sent to the board
RAIL_EVERY = 20         # s between train position fetches
REDISCOVER = 1800       # s between rescans for which train ids exist


# ---------- AT API ----------
def get(path, raw=False):
    req = urllib.request.Request(API + path, headers={
        "Ocp-Apim-Subscription-Key": C.AT_API_KEY, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:           # stoptrips: 404 = no services in window
            return None
        raise


# ---------- NZ time (standalone, so the PC's own timezone doesn't matter) ----------
def _sunday(y, m, first):
    days = range(1, 8) if first else range(30 if m == 9 else 31, 23, -1)
    for d in days:
        if time.gmtime(calendar.timegm((y, m, d, 12, 0, 0)))[6] == 6:
            return d


def nz_offset(utc):
    y = time.gmtime(utc)[0]
    start = calendar.timegm((y, 9, _sunday(y, 9, False), 2, 0, 0)) - 12 * 3600
    end = calendar.timegm((y, 4, _sunday(y, 4, True), 3, 0, 0)) - 13 * 3600
    return 13 * 3600 if (utc >= start or utc < end) else 12 * 3600


def local(utc=None):
    utc = time.time() if utc is None else utc
    return time.gmtime(utc + nz_offset(utc))


def hm(t):
    return "%d:%02d" % ((t[3] % 12) or 12, t[4])


def service_epoch(date, hms):
    y, m, d = (int(p) for p in date.split("-"))
    h, mi, s = (int(p) for p in hms.split(":"))
    midnight = calendar.timegm((y, m, d, 0, 0, 0))
    return midnight + h * 3600 + mi * 60 + s - nz_offset(midnight)


# ---------- buses ----------
class Buses:
    def __init__(self):
        j = get("/gtfs/v3/stops?filter%5Bstop_code%5D=" + C.STOP_CODE)
        a = j["data"][0]["attributes"]
        self.stop_id = a["stop_id"]
        name = C.STOP_NAME or a["stop_name"]
        for x, y in ((" Road", " Rd"), (" Street", " St"), (" Avenue", " Ave")):
            name = name.replace(x, y)
        self.name = name
        self.trips = {}
        self.t_sched = self.t_rt = 0
        self.status, self.err = "Starting...", False

    def schedule(self):
        utc = time.time()
        t = local(utc)
        queries = [("%04d-%02d-%02d" % t[:3], t[3])]
        if t[3] < 3:     # after midnight, late trips still belong to yesterday
            y = local(utc - 86400)
            queries.append(("%04d-%02d-%02d" % y[:3], t[3] + 24))
        trips = {}
        for date, hour in queries:
            j = get("/gtfs/v3/stops/%s/stoptrips?filter%%5Bdate%%5D=%s"
                    "&filter%%5Bstart_hour%%5D=%d&hour_range=3" % (self.stop_id, date, hour))
            for e in (j or {}).get("data", []):
                a = e["attributes"]
                if a.get("pickup_type") == 1:
                    continue
                route = a["route_id"].split("-")[0]
                if C.ROUTE and route != C.ROUTE:
                    continue
                dest = (a.get("stop_headsign") or a.get("trip_headsign") or "").strip().title()
                old = self.trips.get(a["trip_id"], {})
                trips[a["trip_id"]] = {
                    "route": route, "dest": dest, "seq": a["stop_sequence"],
                    "sched": service_epoch(a["service_date"], a["departure_time"]),
                    "delay": old.get("delay", 0), "live": old.get("live", False),
                    "cancel": old.get("cancel", False), "gone": old.get("gone", False)}
        self.trips = trips

    def realtime(self):
        now = time.time()
        ids = [k for k, v in self.trips.items() if -600 < v["sched"] - now < 3 * 3600][:20]
        if not ids:
            return
        j = get("/realtime/legacy/tripupdates?tripid=" + ",".join(ids))
        for ent in j["response"].get("entity") or []:
            tu = ent.get("trip_update")
            if not tu or tu["trip"]["trip_id"] not in self.trips:   # filter is inexact
                continue
            tr = self.trips[tu["trip"]["trip_id"]]
            if ent.get("is_deleted") or tu["trip"].get("schedule_relationship") == 3:
                tr["cancel"] = True
                continue
            stu = tu.get("stop_time_update") or {}
            if isinstance(stu, list):
                stu = stu[-1] if stu else {}
            ev = stu.get("departure") or stu.get("arrival") or {}
            seq = stu.get("stop_sequence", 0)
            if seq > tr["seq"]:
                tr["gone"] = True          # already went past our stop
                continue
            if seq == tr["seq"] and ev.get("time"):
                tr["delay"] = ev["time"] - tr["sched"]
            else:
                tr["delay"] = ev.get("delay", tu.get("delay", 0)) or 0
            tr["live"] = True

    def update(self):
        now = time.time()
        try:
            if now - self.t_sched >= (C.SCHEDULE_EVERY if self.trips else 60):
                self.t_sched = now
                self.schedule()
            if now - self.t_rt >= C.REALTIME_EVERY:
                self.t_rt = now
                self.realtime()
                t = local()
                self.status, self.err = "Updated %s:%02d" % (hm(t), t[5]), False
        except Exception as e:
            print("bus fetch failed:", e)
            self.status, self.err = "Error: %s" % e, True

    def message(self):
        now = time.time()
        deps = []
        for v in self.trips.values():
            v["eta"] = v["sched"] + v["delay"]
            if not v["gone"] and v["eta"] >= now - 30:
                deps.append(v)
        deps.sort(key=lambda v: v["eta"])
        rows = []
        for d in deps[:4]:
            mins = int((d["eta"] - now) // 60)
            sched = hm(local(d["eta"]))
            late = int(d["delay"] // 60)
            if d["cancel"]:
                info, ic, big, bc = "CANCELLED", "r", "--", "r"
            else:
                if not d["live"]:
                    info, ic = sched + " scheduled", "y"
                elif late >= 2:
                    info, ic = "%s  %d min late" % (sched, late), "a"
                elif late <= -2:
                    info, ic = "%s  %d min early" % (sched, -late), "a"
                else:
                    info, ic = sched + "  on time", "g"
                big, bc = ("Due", "g") if mins <= 0 else ("%dm" % mins, "w" if d["live"] else "y")
            rows.append([d["route"], d["dest"], big, bc, info, ic, d["live"] and not d["cancel"]])
        return {"t": "bus", "name": self.name, "code": C.STOP_CODE, "clock": hm(local()),
                "status": self.status, "err": self.err, "rows": rows}


# ---------- trains ----------
_KX = math.cos(math.radians(36.9))     # lon->distance squash at Auckland
LINE_IDS = [n for n, _ in M.LINES]


def place(line, lat, lon):
    # snap a GPS fix onto the nearest piece of that line's track on the map
    px, py = lon * _KX, lat
    best, bd = None, 1e9
    for s in M.SEGS:
        if s[0] != line:
            continue
        ax, ay, bx, by = s[6] * _KX, s[5], s[8] * _KX, s[7]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
        d = (ax + t * dx - px) ** 2 + (ay + t * dy - py) ** 2
        if d < bd:
            bd, best = d, (s, t)
    if best is None or bd > 0.015 ** 2:      # >~1.5km off the line: depot/yard
        return None
    s, t = best
    return round(s[1] + (s[3] - s[1]) * t), round(s[2] + (s[4] - s[2]) * t)


class Trains:
    # every AT train has a 59xxx vehicle id; asking for those by id turns the
    # 600KB all-vehicles feed into ~30KB
    def __init__(self):
        self.ids, self.t_disc, self.t = None, 0, 0
        self.trains, self.counts, self.msg = [], None, "loading"

    def update(self):
        now = time.time()
        if now - self.t < RAIL_EVERY:
            return
        self.t = now
        try:
            if not self.ids or now - self.t_disc >= REDISCOVER:
                j = get("/realtime/legacy/vehiclelocations?vehicleid="
                        + ",".join(str(i) for i in range(59000, 60000)))
                self.ids = ",".join(sorted(e["id"] for e in j["response"]["entity"] or []))
                self.t_disc = now
            else:
                j = get("/realtime/legacy/vehiclelocations?vehicleid=" + self.ids)
            trains = []
            for e in j["response"]["entity"] or []:
                v = e.get("vehicle", {})
                route = v.get("trip", {}).get("route_id", "").rsplit("-", 1)[0]
                pos = v.get("position")
                if route not in LINE_IDS or not pos:
                    continue
                li = LINE_IDS.index(route)
                p = place(li, pos["latitude"], pos["longitude"])
                if p:
                    trains.append([p[0], p[1], li])
            self.trains = trains
            self.counts = [sum(1 for t in trains if t[2] == i) for i in range(len(LINE_IDS))]
            self.msg = "upd " + hm(local())
        except Exception as e:
            print("train fetch failed:", e)
            self.msg = "error"

    def message(self):
        return {"t": "rail", "clock": hm(local()), "msg": self.msg,
                "counts": self.counts, "trains": self.trains}


# ---------- serial link ----------
def find_port():
    port = getattr(C, "SERIAL_PORT", "")
    if port:
        return port
    for p in serial.tools.list_ports.comports():
        if "CH340" in (p.description or "") or p.vid == 0x1A86:
            return p.device
    return None


def open_port():
    while True:
        port = find_port()
        if port:
            try:
                s = serial.Serial()
                s.port, s.baudrate, s.timeout = port, 115200, 0.5
                s.dtr = s.rts = False          # don't reset the board on open
                s.open()
                print("connected to board on", port)
                return s
            except serial.SerialException as e:
                print("can't open %s (%s) - is something else using it?" % (port, e))
        else:
            print("board not found - plug in the ESP32")
        time.sleep(5)


ack = threading.Event()


def echo(ser):
    # "ok" = board finished the last line; print anything else it says
    while True:
        try:
            line = ser.readline()
        except Exception:
            return
        if line.strip() == b"ok":
            ack.set()
        elif line.strip():
            print("board:", line.decode(errors="replace").rstrip())


def send(ser, m):
    ack.clear()
    ser.write((json.dumps(m, separators=(",", ":")) + "\n").encode())
    ack.wait(3)           # its input buffer is small: one line at a time


def main():
    buses, trains = Buses(), Trains()
    ser = open_port()
    threading.Thread(target=echo, args=(ser,), daemon=True).start()
    while True:
        buses.update()
        trains.update()
        try:
            for m in (buses.message(), trains.message()):
                send(ser, m)
        except serial.SerialException as e:
            print("lost the board:", e)
            ser.close()
            ser = open_port()
            threading.Thread(target=echo, args=(ser,), daemon=True).start()
        time.sleep(SEND_EVERY)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
