"""Find max single-command arg. WATCH THE TABLE. Usage: calib_max.py <units>."""
import serial
import sys
import time

PORT = "COM3"
arg = sys.argv[1] if len(sys.argv) > 1 else "500"

s = serial.Serial(PORT, 9600, timeout=1.0, write_timeout=1)
time.sleep(0.3)
s.reset_input_buffer()
s.write(("move " + arg + "\n").encode())
s.flush()
t0 = time.time()
out = b""
while time.time() - t0 < 25:
    time.sleep(0.05)
    if s.in_waiting:
        out += s.read(s.in_waiting)
        if b"stopped" in out or b"error" in out:
            break
print("arg=%r total=%.2fs reply=%r" % (arg, time.time() - t0, out))
s.close()
