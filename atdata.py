# Auckland Transport data, fetched and worked out on the board itself.
# The PC (netproxy.py) only relays the HTTP requests.
import time, re, json, gc, math
import net
import railgeo as G
import config as C

API = "https://api.at.govt.nz"
UNIX = 946684800            # MicroPython's ESP32 clock counts from 2000-01-01


# ---------- NZ time (daylight saving included) ----------
def _sunday(y, m, first):
    days = range(1, 8) if first else range(30 if m == 9 else 31, 23, -1)
    for d in days:
        if time.gmtime(time.mktime((y, m, d, 12, 0, 0, 0, 0)))[6] == 6:
            return d


_off_cache = [0, 0]


def nz_offset(utc):
    if abs(utc - _off_cache[0]) < 600:
        return _off_cache[1]
    y = time.gmtime(utc)[0]
    start = time.mktime((y, 9, _sunday(y, 9, False), 2, 0, 0, 0, 0)) - 12 * 3600
    end = time.mktime((y, 4, _sunday(y, 4, True), 3, 0, 0, 0, 0)) - 13 * 3600
    off = 13 * 3600 if (utc >= start or utc < end) else 12 * 3600
    _off_cache[0], _off_cache[1] = utc, off
    return off


def local(utc=None):
    utc = time.time() if utc is None else utc
    return time.gmtime(utc + nz_offset(utc))


def clock():
    t = local()
    return "%d:%02d" % (t[3], t[4])


def hour():
    t = local()
    return t[3] + t[4] / 60


def service_epoch(date, hms):
    y, m, d = (int(p) for p in date.split("-"))
    h, mi, s = (int(p) for p in hms.split(":"))
    midnight = time.mktime((y, m, d, 0, 0, 0, 0, 0))
    return midnight + h * 3600 + mi * 60 + s - nz_offset(midnight)


def get_json(path):
    gc.collect()
    st, body = net.request(API + path)
    if st == 404:
        return None                   # stoptrips: 404 means no services in the window
    if st != 200:
        raise OSError("AT %d" % st)
    j = json.loads(body)
    del body
    gc.collect()
    return j


# ---------- buses ----------
def _headsign(a):
    # "Waikowhai To Britomart Via Hillsborough Rd ..." -> "to Britomart"
    h = a.get("trip_headsign") or a.get("stop_headsign") or ""
    low = h.lower()
    i = low.find(" to ")
    if i >= 0:
        h = h[i + 4:]
    i = h.lower().find(" via ")
    if i >= 0:
        h = h[:i]
    h = " ".join(w[:1].upper() + w[1:].lower() for w in h.split())
    return "to " + h if h else ""


class Stop:
    def __init__(self, cfg):
        self.code, self.route, self.label = cfg["stop"], cfg.get("route", ""), cfg.get("label", "")
        self.stop_id = None
        self.trips = {}
        self.t_sched = self.t_rt = -10**9
        self.ok_at = 0
        self.error = None

    def update(self):
        now = time.time()
        try:
            if self.stop_id is None:
                j = get_json("/gtfs/v3/stops?filter%5Bstop_code%5D=" + self.code)
                self.stop_id = j["data"][0]["attributes"]["stop_id"]
            if now - self.t_sched >= (300 if self.trips else 60):
                self.t_sched = now
                self._schedule()
            if now - self.t_rt >= 30:
                self.t_rt = now
                self._realtime()
                self.ok_at = now
            self.error = None
        except Exception as e:
            self.error = str(e)
            print("stop", self.code, repr(e))

    def _schedule(self):
        now = time.time()
        t = local(now)
        queries = [("%04d-%02d-%02d" % t[:3], t[3])]
        if t[3] < 3:                         # after midnight: late trips are yesterday's
            y = local(now - 86400)
            queries.append(("%04d-%02d-%02d" % y[:3], t[3] + 24))
        trips = {}
        for date, hr in queries:
            j = get_json("/gtfs/v3/stops/%s/stoptrips?filter%%5Bdate%%5D=%s"
                         "&filter%%5Bstart_hour%%5D=%d&hour_range=2" % (self.stop_id, date, hr))
            for e in (j or {}).get("data", ()):
                a = e["attributes"]
                route = a["route_id"].split("-")[0]
                if a.get("pickup_type") == 1 or (self.route and route != self.route):
                    continue
                old = self.trips.get(a["trip_id"])
                trips[a["trip_id"]] = [route, _headsign(a), a["stop_sequence"],
                                       service_epoch(a["service_date"], a["departure_time"]),
                                       old[4] if old else 0,          # delay
                                       old[5] if old else False,      # live
                                       old[6] if old else False,      # cancelled
                                       old[7] if old else False]      # gone past
            del j
        self.trips = trips

    def _realtime(self):
        now = time.time()
        ids = [k for k, v in self.trips.items() if -600 < v[3] - now < 3 * 3600][:20]
        if not ids:
            return
        j = get_json("/realtime/legacy/tripupdates?tripid=" + ",".join(ids))
        for ent in j["response"].get("entity") or ():
            tu = ent.get("trip_update")
            if not tu:
                continue
            tr = self.trips.get(tu["trip"]["trip_id"])     # the filter is inexact
            if tr is None:
                continue
            if ent.get("is_deleted") or tu["trip"].get("schedule_relationship") == 3:
                tr[6] = True
                continue
            stu = tu.get("stop_time_update") or {}
            if isinstance(stu, list):
                stu = stu[-1] if stu else {}
            ev = stu.get("departure") or stu.get("arrival") or {}
            seq = stu.get("stop_sequence", 0)
            if seq > tr[2]:
                tr[7] = True
                continue
            if seq == tr[2] and ev.get("time"):
                tr[4] = ev["time"] - UNIX - tr[3]
            else:
                tr[4] = ev.get("delay", tu.get("delay", 0)) or 0
            tr[5] = True

    def lane(self):
        """(route, headsign, [(eta_s, live, cancelled)...], message)"""
        now = time.time()
        deps, route, head = [], self.route, self.label
        for v in sorted(self.trips.values(), key=lambda v: v[3] + v[4]):
            eta = v[3] + v[4] - now
            if v[7] or eta < -30:
                continue
            route = route or v[0]
            head = head or v[1]
            deps.append((eta, v[5], v[6]))
            if len(deps) == 3:
                break
        msg = "no data" if self.error and not self.trips else None
        return (route or "?")[:4], head or ("stop " + self.code), deps, msg


# ---------- trains ----------
_TOKEN = re.compile(b'"(id|route_id|latitude|longitude)": ?"?([-0-9A-Za-z.]+)')
_KX = math.cos(math.radians(36.9))

# per line: [(polyline, cumulative lengths, total, ax, ay, dx, dy, L2)]
_LINES = [[] for _ in G.IDS]
for _li, _poly, _la0, _lo0, _la1, _lo1 in G.SEGS:
    _cum = [0.0]
    for _i in range(len(_poly) - 1):
        _cum.append(_cum[-1] + math.sqrt((_poly[_i + 1][0] - _poly[_i][0]) ** 2
                                         + (_poly[_i + 1][1] - _poly[_i][1]) ** 2))
    _ax, _ay = _lo0 * _KX, _la0
    _dx, _dy = _lo1 * _KX - _ax, _la1 - _ay
    _LINES[_li].append((_poly, _cum, _ax, _ay, _dx, _dy, _dx * _dx + _dy * _dy))
del _li, _poly, _la0, _lo0, _la1, _lo1, _cum, _ax, _ay, _dx, _dy


def place(li, lat, lon):
    """Snap a GPS fix onto the nearest station-to-station stretch of its line."""
    px, py = lon * _KX, lat
    best, bd = None, 1e9
    for seg in _LINES[li]:
        _, _, ax, ay, dx, dy, L2 = seg
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        ex, ey = ax + t * dx - px, ay + t * dy - py
        d = ex * ex + ey * ey
        if d < bd:
            bd, best = d, (seg, t)
    if best is None or bd > 0.015 ** 2:      # >~1.5km off the line: depot/yard
        return None
    seg, t = best
    poly, cum = seg[0], seg[1]
    goal = t * cum[-1]
    for i in range(len(poly) - 1):
        if goal <= cum[i + 1] or i == len(poly) - 2:
            span = cum[i + 1] - cum[i]
            f = 0 if span == 0 else (goal - cum[i]) / span
            return (poly[i][0] + (poly[i + 1][0] - poly[i][0]) * f,
                    poly[i][1] + (poly[i + 1][1] - poly[i][1]) * f)
    return poly[-1]


class _Scanner:
    # pulls (vehicle, route, lat, lon) out of the feed as it streams in, so
    # the ~30KB of JSON never has to sit in RAM
    def __init__(self):
        self.buf = b""
        self.vid = self.route = self.lat = None
        self.out = []

    def feed(self, chunk):
        buf = self.buf + bytes(chunk)
        while True:
            m = _TOKEN.search(buf)
            if not m:
                buf = buf[-48:]
                break
            tok = m.group(0)
            at = buf.find(tok)
            end = at + len(tok)
            if end >= len(buf) - 1:            # value may be cut off: wait for more
                buf = buf[at:]
                break
            k, v = m.group(1), m.group(2)
            if k == b"id":
                if self.lat is None:           # the entity's own id comes first
                    self.vid = v
            elif k == b"route_id":
                self.route = v
            elif k == b"latitude":
                self.lat = float(v)
            else:
                if self.route and self.lat is not None:
                    self.out.append((self.vid, self.route, self.lat, float(v)))
                self.route = self.lat = None
            buf = buf[end:]
        self.buf = buf


class Trains:
    GLIDE = 16                              # seconds to glide to a new fix

    def __init__(self):
        self.ids = None
        self.t_disc = self.t = -10**9
        self.now = {}                        # vid -> (x, y, line)
        self.before = {}
        self.t_moved = 0
        self.counts = None
        self.ok_at = 0

    def update(self):
        tnow = time.time()
        if tnow - self.t < 20:
            return
        self.t = tnow
        try:
            sc = _Scanner()
            path = API + "/realtime/legacy/vehiclelocations?vehicleid="
            if not self.ids or tnow - self.t_disc > 1800:
                # find which 59xxx train ids exist, 200 at a time (a single
                # 1000-id URL is a 6KB string -- too big for a fragmented heap)
                for a in range(59000, 60000, 200):
                    gc.collect()
                    st, _ = net.request(path + ",".join(str(i) for i in range(a, a + 200)),
                                        sc.feed)
                    if st != 200:
                        raise OSError("AT %d" % st)
                self.ids = ",".join(sorted(set(v.decode() for v, _, _, _ in sc.out)))
                self.t_disc = tnow
            else:
                gc.collect()
                st, _ = net.request(path + self.ids, sc.feed)
                if st != 200:
                    raise OSError("AT %d" % st)
            fresh = {}
            for vid, route, lat, lon in sc.out:
                code = route.decode().rsplit("-", 1)[0]
                if code in G.IDS:
                    li = G.IDS.index(code)
                    p = place(li, lat, lon)
                    if p:
                        fresh[vid] = (p[0], p[1], li)
            self.before = self.positions()
            self.now, self.t_moved = fresh, time.ticks_ms()
            self.counts = [sum(1 for v in fresh.values() if v[2] == i) for i in range(len(G.IDS))]
            self.ok_at = tnow
        except Exception as e:
            print("trains", repr(e))

    def positions(self):
        f = min(1.0, time.ticks_diff(time.ticks_ms(), self.t_moved) / (self.GLIDE * 1000))
        f = f * f * (3 - 2 * f)
        out = {}
        for vid, (x, y, li) in self.now.items():
            b = self.before.get(vid)
            if b and b[2] == li and abs(b[0] - x) + abs(b[1] - y) < 40:
                x, y = b[0] + (x - b[0]) * f, b[1] + (y - b[1]) * f
            out[vid] = (x, y, li)
        return out
