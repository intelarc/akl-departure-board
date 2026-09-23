# The PC's only job: be the ESP32's internet connection over USB. The 2.4 GHz
# WiFi in the house doesn't reach the board, so it uses the USB cable instead.
#
#   python netproxy.py            (leave it running; Ctrl+C to stop)
#   python netproxy.py -v         also log every line the board sends
#
# The board does all the fetching logic, parsing and drawing itself. It asks
# for what it needs, one line per request, and pulls each response body in
# pieces so this end never sends anything it wasn't asked for:
#
#   board -> PC:  GET <id> <url>          PC -> board:  <id> <status> <length>
#                 READ <id> <n>                          the next n body bytes, raw
#                 TIME <id>                              <id> 200 <length>  (then READ)
#                 HEADER <id> <name>: <value>            <id> 200 0
import sys, time, urllib.error, urllib.request

VERBOSE = "-v" in sys.argv
BAUD = 115_200          # the board's TX corrupts bytes above this
UA = "akl-departure-board/2 (ESP32 via USB)"


def find_port():
    import serial.tools.list_ports
    try:
        import config as C
        if getattr(C, "SERIAL_PORT", ""):
            return C.SERIAL_PORT
    except Exception:
        pass
    for p in serial.tools.list_ports.comports():
        if p.vid == 0x1A86 or "CH340" in (p.description or ""):
            return p.device
    return None


def fetch(url, headers):
    try:
        req = urllib.request.Request(url, headers=dict(headers, **{"User-Agent": UA}))
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:2000]
    except Exception as e:
        return 0, str(e).encode()[:200]


def handshake(ser):
    """Say hello until the board answers."""
    ser.reset_input_buffer()
    end = time.time() + 30
    seen = b""
    while time.time() < end:
        ser.write(b"HELLO\n")
        t = time.time() + 1.0
        while time.time() < t:
            seen = (seen + ser.read(max(1, ser.in_waiting)))[-200:]
            if b"READY" in seen:
                time.sleep(0.1)
                ser.reset_input_buffer()    # start the session on a clean line
                return True
    return False


def serve(ser):
    """Answer the board's requests. Returns if the board rebooted or went
    quiet, so main() can say hello again."""
    headers, bodies = {}, {}
    last = time.time()
    while True:
        line = ser.readline()
        if not line:
            if time.time() - last > 90:
                print("board went quiet - reconnecting", flush=True)
                return
            continue
        last = time.time()
        if b"rst:" in line or b"ets " in line:
            print("board rebooted - reconnecting", flush=True)
            return
        try:
            line = line.decode().strip()
        except UnicodeDecodeError:
            continue
        if not line:
            continue
        if VERBOSE:
            print("<<", line[:90], flush=True)
        verb, _, rest = line.partition(" ")
        rid, _, rest = rest.partition(" ")
        if verb not in ("GET", "READ", "TIME", "HEADER") or not rid.isdigit():
            print("board:", line[:120], flush=True)       # anything it prints
            continue
        if verb == "READ":
            n = int(rest or 0)
            body = bodies.get(rid, b"")
            chunk, bodies[rid] = body[:n], body[n:]
            ser.write(chunk + b"\0" * (n - len(chunk)))    # always exactly n bytes
            if not bodies[rid]:
                del bodies[rid]
            continue
        if verb == "TIME":
            status, body = 200, str(int(time.time())).encode()
        elif verb == "HEADER":
            k, _, v = rest.partition(":")
            headers[k.strip()] = v.strip()
            status, body = 200, b""
        else:
            status, body = fetch(rest, headers)
            print("%s %s -> %s %d bytes" % (time.strftime("%H:%M:%S"), rest[:70],
                                            status, len(body)), flush=True)
        if len(bodies) > 20:                               # forget abandoned bodies
            bodies.clear()
        if body:
            bodies[rid] = body
        ser.write(b"%s %d %d\n" % (rid.encode(), status, len(body)))


def main():
    import serial
    first = True
    while True:
        port = find_port()
        if not port:
            print("board not found - plug in the ESP32", flush=True)
            time.sleep(5)
            continue
        try:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = port, BAUD, 1
            ser.dtr = ser.rts = False
            ser.open()
            if first:
                # reset the board once at start-up: wakes it from deep sleep
                # and gives both ends a clean start
                ser.rts = True
                time.sleep(0.15)
                ser.rts = False
                first = False
            while True:
                if not handshake(ser):
                    raise OSError("the board did not answer (is main.py on it?)")
                print("connected to the board on", port, flush=True)
                serve(ser)
        except Exception as e:
            print("serial:", e, flush=True)
            time.sleep(3)


def _single_instance():
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 47813))
    except OSError:
        print("netproxy.py is already running")
        sys.exit(0)
    return s


if __name__ == "__main__":
    import os
    if sys.stdout is None:          # started with pythonw: log to a file instead
        sys.stdout = sys.stderr = open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "netproxy.log"),
            "a", buffering=1, encoding="utf-8")
        print("---- started", time.strftime("%Y-%m-%d %H:%M:%S"))
    lock = _single_instance()
    try:
        main()
    except KeyboardInterrupt:
        pass
