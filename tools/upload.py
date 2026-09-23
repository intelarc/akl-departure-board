# Copy the board's code and baked assets onto the ESP32.
#
#   python tools/upload.py            code + assets (first time, ~2 min)
#   python tools/upload.py --code     just the .py files (quick)
#
# netproxy.py must not be running (it holds the USB port).
import os, subprocess, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CODE = ["st7789.py", "gfx.py", "net.py", "atdata.py", "busscreen.py", "railscreen.py",
        "railgeo.py", "busart.py", "config.py", "main.py"]
PORT = None


def port():
    import serial.tools.list_ports
    for p in serial.tools.list_ports.comports():
        if p.vid == 0x1A86 or "CH340" in (p.description or ""):
            return p.device
    sys.exit("board not found")


def quiet_board(dev):
    """Reset the board and stop main.py so mpremote can get in."""
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = dev, 115200, 1
    s.dtr = s.rts = False
    s.open()
    s.rts = True
    time.sleep(0.2)
    s.rts = False
    time.sleep(2.5)
    s.read(100000)
    s.write(b"\x03")
    time.sleep(0.3)
    s.write(b"\x03")
    time.sleep(0.3)
    s.close()


def mp(dev, *args):
    for attempt in range(6):
        r = subprocess.run([sys.executable, "-m", "mpremote", "connect", dev, *args],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        time.sleep(1)
    sys.exit("mpremote failed: " + r.stderr[-400:])


def main():
    dev = port()
    quiet_board(dev)
    args = []
    for f in CODE:
        if os.path.exists(os.path.join(ROOT, f)):
            args += ["fs", "cp", f, ":" + f, "+"]
    if "--code" not in sys.argv:
        mp(dev, "exec", "import os\ntry: os.mkdir('assets')\nexcept OSError: pass")
        for f in sorted(os.listdir(os.path.join(ROOT, "assets"))):
            if not f.endswith(".png"):
                args += ["fs", "cp", "assets/" + f, ":assets/" + f, "+"]
    print(mp(dev, *args, "reset"))


if __name__ == "__main__":
    main()
