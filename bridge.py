# PC side of the AT departure board. Fetches live bus + train data from
# Auckland Transport, renders each frame, and streams the changed pixels to
# the ESP32 over USB.
#
#   python bridge.py                  run the board (leave it going)
#   python bridge.py --preview        just save bus.png + rail.png here
#
# Bus screen: busview.py (bus sprites from MSMGreen/at-departure-board, MIT,
# vendored in atboard/). Rail screen: railview.py, styled after AT's map.
import json, math, struct, sys, threading, time, calendar, urllib.request, urllib.error
import numpy as np
import config as C
import railview
import busview

API = "https://api.at.govt.nz"
FPS = 5
BUS_SCHEDULE_EVERY = 300
BUS_REALTIME_EVERY = 30
RAIL_EVERY = 20
REDISCOVER = 1800


# ---------- AT API ----------
def get(path):
    req = urllib.request.Request(API + path, headers={
        "Ocp-Apim-Subscription-Key": C.AT_API_KEY, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:           # stoptrips: 404 = no services in window
            return None
        raise


# ---------- NZ time (independent of the PC's timezone) ----------
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


def clock():
    t = local()
    return "%d:%02d" % (t[3], t[4])


def service_epoch(date, hms):
    y, m, d = (int(p) for p in date.split("-"))
    h, mi, s = (int(p) for p in hms.split(":"))
    midnight = calendar.timegm((y, m, d, 0, 0, 0))
    return midnight + h * 3600 + mi * 60 + s - nz_offset(midnight)


# ---------- buses: one lane per configured stop/route ----------
def _headsign(a):
    # "Waikowhai To Britomart Via Hillsborough Rd ..." -> "to Britomart"
    h = a.get("trip_headsign") or a.get("stop_headsign") or ""
    low = h.lower()
    if " to " in low:
        h = h[low.index(" to ") + 4:]
    if " via " in h.lower():
        h = h[:h.lower().index(" via ")]
    return "to " + h.strip().title() if h.strip() else ""


class StopWatch:
    def __init__(self, cfg):
        self.code, self.route, self.label = cfg["stop"], cfg.get("route", ""), cfg.get("label", "")
        self.stop_id = None
        self.trips = {}
        self.t_sched = self.t_rt = 0
        self.ok_at = 0          # last successful realtime refresh
        self.error = None

    def update(self):
        now = time.time()
        try:
            if self.stop_id is None:
                j = get("/gtfs/v3/stops?filter%5Bstop_code%5D=" + self.code)
                self.stop_id = j["data"][0]["attributes"]["stop_id"]
            if now - self.t_sched >= (BUS_SCHEDULE_EVERY if self.trips else 60):
                self.t_sched = now
                self._schedule()
            if now - self.t_rt >= BUS_REALTIME_EVERY:
                self.t_rt = now
                self._realtime()
                self.ok_at = now
            self.error = None
        except Exception as e:
            print("stop %s: %s" % (self.code, e))
            self.error = str(e)

    def _schedule(self):
        utc = time.time()
        t = local(utc)
        queries = [("%04d-%02d-%02d" % t[:3], t[3])]
        if t[3] < 3:    # after midnight, late trips belong to yesterday
            y = local(utc - 86400)
            queries.append(("%04d-%02d-%02d" % y[:3], t[3] + 24))
        trips = {}
        for date, hour in queries:
            j = get("/gtfs/v3/stops/%s/stoptrips?filter%%5Bdate%%5D=%s"
                    "&filter%%5Bstart_hour%%5D=%d&hour_range=3" % (self.stop_id, date, hour))
            for e in (j or {}).get("data", []):
                a = e["attributes"]
                route = a["route_id"].split("-")[0]
                if a.get("pickup_type") == 1 or (self.route and route != self.route):
                    continue
                old = self.trips.get(a["trip_id"], {})
                trips[a["trip_id"]] = dict(
                    route=route, headsign=_headsign(a), seq=a["stop_sequence"],
                    sched=service_epoch(a["service_date"], a["departure_time"]),
                    delay=old.get("delay", 0), live=old.get("live", False),
                    cancel=old.get("cancel", False), gone=old.get("gone", False))
        self.trips = trips

    def _realtime(self):
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
                tr["gone"] = True          # already past our stop
                continue
            if seq == tr["seq"] and ev.get("time"):
                tr["delay"] = ev["time"] - tr["sched"]
            else:
                tr["delay"] = ev.get("delay", tu.get("delay", 0)) or 0
            tr["live"] = True

    def lane(self):
        now = time.time()
        deps, route, head = [], self.route or "", self.label
        for v in sorted(self.trips.values(), key=lambda v: v["sched"] + v["delay"]):
            eta = v["sched"] + v["delay"] - now
            if v["gone"] or eta < -30:
                continue
            route = route or v["route"]
            head = head or v["headsign"]
            deps.append((eta, v["live"], v["cancel"]))
        msg = "no data" if self.error and not self.trips else None
        return dict(route=(route or "?")[:4], headsign=head or ("stop " + self.code),
                    deps=deps[:3], message=msg)


# ---------- trains ----------
class Trains:
    # every AT train has a 59xxx vehicle id; asking for those by id turns
    # the 600KB all-vehicles feed into ~30KB
    def __init__(self):
        self.ids, self.t_disc, self.t = None, 0, 0
        self.trains, self.counts, self.ok_at = {}, None, 0
        self.before, self.t_moved = {}, 0

    def positions(self, now):
        """Each train glides from its last position to the new one."""
        f = min(1.0, (now - self.t_moved) / (RAIL_EVERY * 0.8))
        f = f * f * (3 - 2 * f)                         # ease in/out
        out = {}
        for vid, (x, y, li) in self.trains.items():
            if vid in self.before and self.before[vid][2] == li:
                bx, by, _ = self.before[vid]
                if abs(bx - x) + abs(by - y) < 40:      # jumps (new trips) just appear
                    x, y = bx + (x - bx) * f, by + (y - by) * f
            out[vid] = (x, y, li)
        return out

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
            trains = {}
            for e in j["response"]["entity"] or []:
                v = e.get("vehicle", {})
                route = v.get("trip", {}).get("route_id", "").rsplit("-", 1)[0]
                pos = v.get("position")
                if route in railview.LINE_IDS and pos:
                    li = railview.LINE_IDS.index(route)
                    p = railview.place(li, pos["latitude"], pos["longitude"])
                    if p:
                        trains[e["id"]] = (p[0], p[1], li)
            self.before = self.positions(now)       # glide from wherever they are now
            self.trains, self.t_moved = trains, now
            self.counts = [sum(1 for t in trains.values() if t[2] == i)
                           for i in range(len(railview.LINES))]
            self.ok_at = now
        except Exception as e:
            print("trains:", e)


# ---------- the two screens ----------
class Screens:
    def __init__(self):
        self.stops = [StopWatch(w) for w in C.WATCHES[:4]]
        self.trains = Trains()

    def fetch_forever(self):
        while True:
            for s in self.stops:
                s.update()
            self.trains.update()
            time.sleep(1)

    def bus(self, t):
        now = time.time()
        stale = all(s.ok_at for s in self.stops) and now - min(s.ok_at for s in self.stops) > 120
        lt = local(now)
        return busview.render(getattr(C, "LOCATION", "Auckland"), clock(),
                              lt[3] + lt[4] / 60, [s.lane() for s in self.stops], t, stale)

    def rail(self, t):
        tr = self.trains
        stale = int(time.time() - tr.ok_at) if tr.ok_at else 0
        return railview.render(list(tr.positions(time.time()).values()), tr.counts,
                               clock(), stale, t)


# ---------- USB link ----------
class LinkError(Exception):
    pass


def rle(p):
    """(count, hi, lo) runs of a flat uint16 pixel array."""
    starts = np.concatenate(([0], np.flatnonzero(p[1:] != p[:-1]) + 1))
    lens = np.diff(np.append(starts, len(p)))
    reps = (lens + 254) // 255                 # runs longer than 255 get split
    vals = np.repeat(p[starts], reps)
    counts = np.full(len(vals), 255, np.uint8)
    counts[np.cumsum(reps) - 1] = lens - (reps - 1) * 255
    out = np.empty((len(vals), 3), np.uint8)
    out[:, 0], out[:, 1], out[:, 2] = counts, vals >> 8, vals & 0xFF
    return out.tobytes()


class Link:
    FAST = 230_400          # the board loses bytes any faster
    MAX_PX = 8192
    MAX_RLE = 8192

    def __init__(self):
        self.ser = None
        self.prev = None
        self.button = False
        self.sent = 0
        self.last_tx = 0

    def connect(self):
        import serial, serial.tools.list_ports
        while True:
            port = getattr(C, "SERIAL_PORT", "") or next(
                (p.device for p in serial.tools.list_ports.comports()
                 if p.vid == 0x1A86 or "CH340" in (p.description or "")), None)
            if not port:
                print("board not found - plug in the ESP32")
                time.sleep(5)
                continue
            try:
                s = serial.Serial()
                s.port, s.baudrate, s.timeout = port, 115200, 0.2
                s.dtr = s.rts = False
                s.open()
                s.rts = True                   # reset the board into a known state
                time.sleep(0.15)
                s.rts = False
                if not self._wait(s, b"board ready", 10):
                    raise LinkError("board didn't start (is main.py on it?)")
                s.write(b"HELLO\n")
                if not self._wait(s, b"READY", 3):
                    raise LinkError("board didn't answer HELLO")
                time.sleep(0.06)
                s.baudrate = self.FAST
                s.timeout = 2
                s.reset_input_buffer()
                self.ser, self.prev = s, None
                print("board connected on", port)
                return
            except Exception as e:
                print("connect failed:", e)
                try:
                    s.close()
                except Exception:
                    pass
                time.sleep(3)

    @staticmethod
    def _wait(s, token, secs):
        end, seen = time.time() + secs, b""
        while time.time() < end:
            seen = (seen + s.read(256))[-400:]
            if token in seen:
                return True
        return False

    def _acks(self, need_k):
        # board replies: "K" once a rectangle is on screen, "B" = BOOT button
        while need_k or self.ser.in_waiting:
            b = self.ser.read(1)
            if not b:
                raise LinkError("board stopped answering")
            if b == b"B":
                self.button = True
            elif b == b"K" and need_k:
                return

    def show(self, img):
        a = np.asarray(img.convert("RGB"), dtype=np.uint16)
        px = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
        diff = np.ones(px.shape, bool) if self.prev is None else px != self.prev
        rows = np.flatnonzero(diff.any(axis=1))
        i = 0
        while i < len(rows):                        # runs of changed rows
            j = i
            while j + 1 < len(rows) and rows[j + 1] == rows[j] + 1:
                j += 1
            y0, y1 = rows[i], rows[j] + 1
            cols = np.flatnonzero(diff[y0:y1].any(axis=0))
            x0, x1 = cols[0], cols[-1] + 1
            step = max(1, self.MAX_PX // (x1 - x0))
            for y in range(y0, y1, step):
                h = min(step, y1 - y)
                block = px[y:y + h, x0:x1]
                data, kind = rle(block.ravel()), 1
                if len(data) > min(self.MAX_RLE, block.size * 2):
                    data, kind = block.astype(">u2").tobytes(), 0
                self.ser.write(b"\xA5\x5A" + struct.pack(
                    ">BHHHHH", kind, x0, y, x1 - x0, h, len(data)) + data)
                self.sent += len(data)
                self._acks(True)
            i = j + 1
        if len(rows) == 0 and time.time() - self.last_tx > 5:
            # nothing changed for a while: resend one pixel so the board
            # knows the PC is still here (it resets after 20s of silence)
            self.ser.write(b"\xA5\x5A" + struct.pack(">BHHHHH", 0, 0, 0, 1, 1, 2)
                           + px[0:1, 0:1].astype(">u2").tobytes())
            self._acks(True)
            self.last_tx = time.time()
        elif len(rows):
            self.last_tx = time.time()
        self._acks(False)
        self.prev = px


def main():
    screens = Screens()
    if "--preview" in sys.argv:
        for s in screens.stops:
            s.update()
        screens.trains.update()
        screens.bus(0).save("bus.png")
        screens.rail(0).save("rail.png")
        print("saved bus.png and rail.png")
        return
    threading.Thread(target=screens.fetch_forever, daemon=True).start()
    order = ["bus", "rail"]
    cur = getattr(C, "START_SCREEN", "bus")
    link = Link()
    link.connect()
    t0 = t_stat = time.time()
    frames = 0
    while True:
        start = time.time()
        if start - t_stat >= 30:
            print("%s screen: %.1f fps, %.1f KB/s to the board"
                  % (cur, frames / (start - t_stat), link.sent / 1024 / (start - t_stat)))
            t_stat, frames, link.sent = start, 0, 0
        if link.button:
            link.button = False
            cur = order[(order.index(cur) + 1) % len(order)]
        try:
            img = screens.bus(start - t0) if cur == "bus" else screens.rail(start - t0)
            link.show(img)
            frames += 1
        except Exception as e:
            print("lost the board:", e)
            try:
                link.ser.close()
            except Exception:
                pass
            link.connect()
        time.sleep(max(0, 1 / FPS - (time.time() - start)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
