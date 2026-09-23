# The board's internet connection: netproxy.py on the PC, over USB.
#
# The ESP32 does all the fetching logic itself; the PC only relays bytes.
#   board -> PC:  GET <id> <url>        PC fetches it, answers  <id> <status> <length>
#                 READ <id> <n>         PC sends the next n bytes of that body, raw
#                 TIME <id> / HEADER <id> <name>: <value>   (small replies, inline)
#
# The board *pulls* bodies a piece at a time, so the PC never sends anything
# unasked. That matters: the ESP32's serial input buffer is tiny, and the
# board wants to keep animating (idle()) between pieces and while the PC is
# busy fetching. Every reply carries the request id, so stray lines (a
# repeated HELLO, boot noise, a late answer) are simply skipped.
#
# One speed, 115200: the ESP32's TX garbles bytes at higher rates.
import sys, select, time, machine, gc

CHUNK = 1024
_poll = select.poll()
_poll.register(sys.stdin, select.POLLIN)
_rd = sys.stdin.buffer.readinto
_wr = sys.stdout.buffer.write
_id = 0
idle = None                     # called while waiting, e.g. to draw a frame
last_ok = time.ticks_ms()       # last time the PC answered (the board sleeps if it stops)


def _line(timeout_ms):
    if not _poll.poll(timeout_ms):
        return None
    return sys.stdin.readline()


def hello(timeout_ms):
    """Wait for the PC's proxy to say hello."""
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
        line = _line(1000)
        if line and line.strip() == "HELLO":
            _wr(b"READY\n")
            time.sleep_ms(300)       # let the PC finish its side first
            return True
    return False


def _read_into(mv, n):
    got = 0
    while got < n:
        if not _poll.poll(10000):
            raise OSError("proxy timed out")
        got += _rd(mv[got:n])


def _send(verb, rest=""):
    global _id
    _id = (_id + 1) % 100000
    _wr(("%s %d %s\n" % (verb, _id, rest)).encode())
    return _id


def _reply(rid, timeout_ms, animate):
    """Wait for the reply line tagged rid, skipping anything else."""
    end = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        if not _poll.poll(30):
            if animate and idle:
                idle()
            continue
        parts = sys.stdin.readline().split()
        if len(parts) != 3:
            continue                      # HELLO, noise, ...
        try:
            got, st, n = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if got == rid:
            return st, n
    raise OSError("no answer from the proxy")


def _pull(rid, n, sink, buf):
    """Fetch a body n bytes long, a CHUNK at a time, animating in between."""
    mv = memoryview(buf)
    left = n
    while left:
        k = min(left, len(buf))
        _wr(("READ %d %d\n" % (rid, k)).encode())
        _read_into(mv, k)
        sink(mv[:k])
        left -= k
        if idle:
            idle()


def request(url, on_chunk=None):
    """GET a url through the PC. Returns (status, body) or, with on_chunk,
    (status, length) having streamed the body past on_chunk."""
    global last_ok
    rid = _send("GET", url)
    st, n = _reply(rid, 30000, True)
    if on_chunk is None:
        gc.collect()
        body = bytearray(n)
        pos = [0]

        def into(b):
            body[pos[0]:pos[0] + len(b)] = b
            pos[0] += len(b)
        _pull(rid, n, into, bytearray(min(CHUNK, max(n, 1))))
        last_ok = time.ticks_ms()
        return st, body              # a bytearray: json.loads takes it without a copy
    _pull(rid, n, on_chunk, bytearray(CHUNK))
    last_ok = time.ticks_ms()
    return st, n


def _small(verb, rest=""):
    rid = _send(verb, rest)
    st, n = _reply(rid, 3000, False)
    body = bytearray(n)
    if n:
        _wr(("READ %d %d\n" % (rid, n)).encode())
        _read_into(memoryview(body), n)
    return st, bytes(body)


def set_header(name, value):
    """Ask the proxy to send this header on every request."""
    for _ in range(4):                    # the first line after hello can be lost
        try:
            return _small("HEADER", "%s: %s" % (name, value))[0] == 200
        except OSError:
            pass
    return False


def sync_clock():
    """Set the RTC from the PC's clock (UTC)."""
    for _ in range(3):
        try:
            epoch = int(_small("TIME")[1])
        except (OSError, ValueError):
            continue
        tm = time.gmtime(epoch - 946684800)    # the ESP32 counts from 2000-01-01
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
        return True
    return False
