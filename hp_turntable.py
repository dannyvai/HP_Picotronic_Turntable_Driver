"""
Driver for the HP 3D Automatic Turntable (DAVID TT-1, Picotronic OEM
USB VID 2AD1 / PID 7AB8, e.g. COM3 @ 9600 baud).

Protocol (reverse-engineered, lowercase words + ``\\n``):
    status\\n   -> status stopped\\n | status running\\n
    version\\n  -> version 1.785\\n
    name\\n     -> name DAVID TT-1\\n
    move <deg>\\n -> status running\\n ... status stopped\\n   (relative move)

Notes:
    * The ``move`` argument is in FIRMWARE UNITS, not degrees. Calibrated
      against the physical dial: ~30 units = 1 degree (``move 100`` -> 3
      deg, ``move 90`` -> 3 deg; ~12 deg/s). ``UNITS_PER_DEGREE`` holds
      the ratio; :meth:`HPTurntable.move` converts true degrees for you
      while :meth:`HPTurntable.raw_move` sends units directly.
    * Positive units DECREASE the dial reading (verified 70 -> 63).
    * ``move 0`` gets NO reply from the firmware (hangs) -> no-op here.
    * No absolute position exists on device; the driver keeps a software
      angle (mod 360) for ``goto_angle`` / scan helpers. Calibrate it
      with ``set_angle()`` (no motion).

Requires: pyserial  (python -m pip install pyserial)

Example:
    from hp_turntable import HPTurntable

    with HPTurntable("COM3") as tt:
        print(tt.get_name(), tt.get_version())
        tt.move(90)                 # blocking relative move
        tt.goto_angle(0)            # shortest-path back to software zero
        tt.scan_360(steps=8, dwell=0.5,
                    callback=lambda i, a: print(i, a))
"""

import threading
import time

import serial

DEFAULT_PORT = "COM3"
DEFAULT_BAUDRATE = 9600
# Calibrated against the physical dial (deg, firmware units):
#   move 10 -> 1 deg, move 100 -> 3 deg, move 90 -> 3 deg.
# Points 2+3 agree on ~30 units/deg; point 1 (10 units -> 1 deg) is an
# outlier, likely a dial misread of a sub-degree move at this coarse
# scale. So 1 firmware unit ~= 1/30 deg. Fine moves need small units.
UNITS_PER_DEGREE = 30.0
# Measured: ~360 firmware units/s => ~12 deg/s at the calibrated scale.
_UNITS_PER_SEC = 360.0
_TIMEOUT_MARGIN = 5.0


class TurntableError(Exception):
    """Base error for turntable driver failures."""


class TurntableTimeout(TurntableError):
    """Raised when the turntable does not answer in time."""


class HPTurntable:
    """Blocking driver for the HP 3D / DAVID TT-1 automatic turntable."""

    def __init__(self, port=DEFAULT_PORT, baudrate=DEFAULT_BAUDRATE,
                 timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser = None
        self._lock = threading.Lock()
        self._angle = 0.0  # software-tracked position, degrees [0, 360)

    # ---------------- connection ----------------
    def connect(self):
        """Open the serial port. Returns self for chaining."""
        if self._ser is not None and self._ser.is_open:
            return self
        try:
            self._ser = serial.Serial(
                self.port, baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout, write_timeout=self.timeout)
        except serial.SerialException as exc:
            raise TurntableError(
                f"Cannot open {self.port} @ {self.baudrate}: {exc}") from exc
        time.sleep(0.3)  # let USB-CDC settle
        self._ser.reset_input_buffer()
        return self

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _ensure_open(self):
        if self._ser is None or not self._ser.is_open:
            raise TurntableError("Not connected - call connect() first")

    # ---------------- low-level ----------------
    def _write_line(self, text):
        self._ensure_open()
        self._ser.write((text + "\n").encode("ascii"))

    def raw_move(self, units, wait=True, timeout=30.0):
        """Send a raw ``move <units>`` in firmware units. Returns elapsed s.

        Mainly for calibration. Tracks the software angle using
        ``UNITS_PER_DEGREE``. Prefer :meth:`move` (true degrees).
        """
        units = int(units)
        if units == 0:
            return 0.0
        t0 = time.time()
        with self._lock:
            self._ser.reset_input_buffer()
            self._write_line(f"move {units}")
            if not wait:
                return 0.0
            deadline = t0 + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TurntableTimeout(
                        f"move {units} did not finish within {timeout:.1f}s")
                line = self._read_line(timeout=min(remaining, 2.0))
                if line == "status stopped":
                    break
        elapsed = time.time() - t0
        self._angle = (self._angle + units / UNITS_PER_DEGREE) % 360.0
        return elapsed

    def _read_line(self, timeout=None):
        """Read one newline-terminated reply line (stripped)."""
        self._ensure_open()
        old = self._ser.timeout
        if timeout is not None:
            self._ser.timeout = timeout
        try:
            raw = self._ser.readline()
        finally:
            self._ser.timeout = old
        if not raw:
            raise TurntableTimeout("No reply from turntable")
        text = raw.decode("ascii", errors="replace").strip()
        if text == "error":
            raise TurntableError("Turntable replied 'error' (bad command?)")
        return text

    def _query(self, cmd, expect_prefix=None, timeout=None):
        """Send a command, return its single-line reply."""
        with self._lock:
            self._ser.reset_input_buffer()
            self._write_line(cmd)
            reply = self._read_line(timeout=timeout)
        if expect_prefix and not reply.startswith(expect_prefix):
            raise TurntableError(f"Unexpected reply to {cmd!r}: {reply!r}")
        return reply

    # ---------------- basic commands ----------------
    def get_status(self):
        """Return 'stopped' or 'running'."""
        reply = self._query("status", expect_prefix="status ")
        return reply.split(" ", 1)[1]

    @property
    def is_moving(self):
        return self.get_status() == "running"

    def get_version(self):
        """Firmware version string, e.g. '1.785'."""
        return self._query("version", expect_prefix="version ").split(" ", 1)[1]

    def get_name(self):
        """Device name, e.g. 'DAVID TT-1'."""
        return self._query("name", expect_prefix="name ").split(" ", 1)[1]

    # ---------------- motion ----------------
    @staticmethod
    def _move_timeout(degrees):
        return abs(float(degrees)) * UNITS_PER_DEGREE / _UNITS_PER_SEC \
            + _TIMEOUT_MARGIN

    def move(self, degrees, wait=True, timeout=None):
        """Relative move by ``degrees`` (signed true degrees). Returns s.

        Converts to firmware units (``UNITS_PER_DEGREE`` per degree) and
        blocks until the table reports 'stopped'. Small moves (< ~0.5 deg)
        round to a few units; ``move(0)`` is a no-op (firmware never
        replies to it).
        """
        degrees = float(degrees)
        if degrees == 0.0:
            return 0.0
        units = int(round(degrees * UNITS_PER_DEGREE))
        if units == 0:
            units = 1 if degrees > 0 else -1
        if timeout is None:
            timeout = self._move_timeout(degrees)
        t0 = time.time()
        with self._lock:
            self._ser.reset_input_buffer()
            self._write_line(f"move {units}")
            if not wait:
                return 0.0
            deadline = t0 + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TurntableTimeout(
                        f"move {units} did not finish within {timeout:.1f}s")
                line = self._read_line(timeout=min(remaining, 2.0))
                if line == "status stopped":
                    break
        elapsed = time.time() - t0
        self._angle = (self._angle + units / UNITS_PER_DEGREE) % 360.0
        return elapsed

    def move_async(self, degrees):
        """Start a relative move and return immediately (no waiting)."""
        return self.move(degrees, wait=False)

    def wait_until_stopped(self, timeout=30.0):
        """Poll status until 'stopped'. Raises TurntableTimeout on expiry."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.get_status() == "stopped":
                return True
            time.sleep(0.05)
        raise TurntableTimeout(
            f"Turntable still running after {timeout:.1f}s")

    # ---------------- software position + helpers ----------------
    @property
    def angle(self):
        """Software-tracked angle in [0, 360). 0 = driver start."""
        return self._angle

    def zero(self):
        """Reset software angle reference to 0 at current position."""
        self._angle = 0.0

    def set_angle(self, angle):
        """Tell the driver the CURRENT physical position (no motion).

        Use when you know the real table angle (e.g. you read ~70 deg
        off a dial/mark and want ``angle``/``goto_angle``/``scan_360``
        to be correct from there). Returns the normalized angle.
        """
        self._angle = float(angle) % 360.0
        return self._angle

    def goto_angle(self, target, wait=True, timeout=None):
        """Shortest-path move to software angle ``target`` (mod 360)."""
        delta = (float(target) - self._angle + 540.0) % 360.0 - 180.0
        return self.move(delta, wait=wait, timeout=timeout)

    def spin(self, cycles=1, wait=True, timeout=None):
        """Rotate ``cycles`` full turns (negative = opposite direction)."""
        return self.move(360.0 * cycles, wait=wait, timeout=timeout)

    def scan_360(self, steps=8, dwell=1.0, callback=None, timeout=None):
        """Step a full turn for scanning/photogrammetry.

        Splits 360 deg into ``steps`` equal moves; after each move waits
        ``dwell`` seconds (camera settle time) then calls
        ``callback(step_index, angle)`` - e.g. trigger a photo/scan.
        Returns the list of visited angles.
        """
        if steps < 1:
            raise ValueError("steps must be >= 1")
        step_angle = 360.0 / steps
        visited = []
        for i in range(steps):
            self.move(step_angle, wait=True, timeout=timeout)
            visited.append(self._angle)
            if dwell > 0:
                time.sleep(dwell)
            if callback is not None:
                callback(i, self._angle)
        return visited


def _cli():
    import argparse
    ap = argparse.ArgumentParser(
        description="HP 3D automatic turntable driver")
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUDRATE)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="print stopped/running")
    sub.add_parser("version", help="print name + firmware version")

    p_angle = sub.add_parser(
        "angle", help="show software angle (no motion; calibrate with --set)")
    p_angle.add_argument("--set", type=float, default=None, metavar="DEG",
                         help="tell driver the current physical angle, no motion")

    p_move = sub.add_parser("move", help="relative move in TRUE degrees")
    p_move.add_argument("degrees", type=float)
    p_move.add_argument("--no-wait", action="store_true")

    p_raw = sub.add_parser("raw", help="relative move in firmware units")
    p_raw.add_argument("units", type=int)

    p_goto = sub.add_parser("goto", help="go to software angle (mod 360)")
    p_goto.add_argument("angle", type=float)

    p_scan = sub.add_parser("scan", help="step a full 360 turn")
    p_scan.add_argument("steps", type=int)
    p_scan.add_argument("--dwell", type=float, default=1.0,
                        help="settle seconds per step")

    p_spin = sub.add_parser("spin", help="full turns (neg = CCW)")
    p_spin.add_argument("cycles", type=float, default=1.0)

    args = ap.parse_args()
    with HPTurntable(args.port, args.baud) as tt:
        if args.cmd == "status":
            print(tt.get_status())
        elif args.cmd == "angle":
            if args.set is not None:
                tt.set_angle(args.set)
            print(f"{tt.angle:.1f}")
        elif args.cmd == "version":
            print(f"{tt.get_name()} firmware {tt.get_version()}")
        elif args.cmd == "move":
            dt = tt.move(args.degrees, wait=not args.no_wait)
            print(f"moved {args.degrees} deg in {dt:.2f}s "
                  f"(angle={tt.angle:.1f})")
        elif args.cmd == "raw":
            dt = tt.raw_move(args.units)
            print(f"moved {args.units} units in {dt:.2f}s")
        elif args.cmd == "goto":
            dt = tt.goto_angle(args.angle)
            print(f"at {tt.angle:.1f} deg ({dt:.2f}s)")
        elif args.cmd == "spin":
            dt = tt.spin(args.cycles)
            print(f"spun {args.cycles} cycle(s) in {dt:.2f}s")
        elif args.cmd == "scan":
            visited = tt.scan_360(
                args.steps, dwell=args.dwell,
                callback=lambda i, a: print(f"step {i}: {a:.1f} deg"))
            print(f"done, {len(visited)} steps")


if __name__ == "__main__":
    _cli()

