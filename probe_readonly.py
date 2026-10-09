"""Read-only probe: NO move/go/run/start commands. Safe, table must NOT move."""
import serial, time
ser = serial.Serial("COM3", baudrate=9600, timeout=0.5, write_timeout=1)
time.sleep(0.3)
ser.reset_input_buffer()

queries = [
    # position-like
    "position", "pos", "angle", "a", "p", "get pos", "get position",
    "get angle", "read pos", "read position", "?pos", "?p",
    "counter", "count", "steps", "step", "encoder", "enc",
    # info-like
    "status", "version", "name", "info", "id", "help", "list",
    "config", "settings", "params", "state",
    # single letters (read-only sounding)
    "q", "w", "e", "r", "t", "y", "u", "o", "l", "k", "j",
    "Q", "W", "E", "R", "T", "Y", "U", "O", "L", "K", "J",
]
for q in queries:
    ser.reset_input_buffer()
    ser.write((q + "\n").encode())
    ser.flush()
    time.sleep(0.3)
    data = ser.read(ser.in_waiting or 1)
    time.sleep(0.1)
    if ser.in_waiting:
        data += ser.read(ser.in_waiting)
    txt = data.strip()
    if txt not in (b"error", b""):
        print(f"TX {q!r:16} -> RX: {data!r}  *** NON-ERROR ***")
print("done - anything not listed replied 'error' (no such command). Table should NOT have moved.")
ser.close()
