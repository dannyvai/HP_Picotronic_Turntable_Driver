# HP 3D Automatic Turntable — Python driver

Driver for the **HP 3D Automatic Turntable** (= DAVID TT-1, Picotronic OEM,
USB `VID 2AD1 / PID 7AB8`) on `COM3 @ 9600 baud`.

Protocol was reverse-engineered (no public docs exist). Commands are
lowercase words + `\n`:

| Command        | Reply                                      |
|----------------|--------------------------------------------|
| `status`       | `status stopped` / `status running`        |
| `version`      | `version 1.785`                            |
| `name`         | `name DAVID TT-1`                          |
| `move <units>` | `status running` … `status stopped`        |

> **Key finding: the `move` argument is firmware units, NOT degrees.**
> Calibrated live against the table's physical dial (Oct 2026):
>
> | Raw command | Dial before → after | Real motion | Scale |
> |-------------|---------------------|-------------|-------|
> | `move 10`   | 70° → 69°           | ~1°         | ~10 u/° (outlier, sub-degree misread) |
> | `move 100`  | 69° → 66°           | 3°          | ~33 u/° |
> | `move 90`   | 66° → 63°           | 3°          | 30 u/° |
> | `move 600` (= `move(20)`) | 63° → ~44° | ~19° | ~31 u/° |
> | `move -600` (= `move(-20)`) | ~44° → 63° | ~19–20° back | symmetric ✓ |
>
> Conclusion: **≈ 30 firmware units = 1°** (`UNITS_PER_DEGREE = 30.0`
> in the driver). The first `move 10` point is an outlier — a 1/3°
> move is below what the dial resolves. Large single commands verified:
> 500 units → 1.26 s, 1000 units → 2.52 s, i.e. **~400 units/s ≈ 12–13°/s**.
>
> Other findings:
> * Positive units **decrease** the dial reading (70 → 63 on `+` moves).
> * Negative units reverse symmetrically (`-20°` returned 44° → 63° exactly).
> * `move 0` gets **no reply** from firmware → driver treats it as a no-op.
> * No position/angle query exists (every read-only word besides
>   `status`/`version`/`name` replies `error`) → the driver tracks a
>   software angle (mod 360). Calibrate it to the real dial with
>   `angle --set 63` (no motion).

## Install

```powershell
python -m pip install -r requirements.txt
```

## Library use

```python
from hp_turntable import HPTurntable

with HPTurntable("COM3") as tt:
    print(tt.get_name(), tt.get_version())  # DAVID TT-1 1.785
    print(tt.get_status())                  # stopped
    tt.set_angle(63)                        # calibrate to dial, no motion
    tt.move(20)                             # 20 TRUE degrees, blocking
    tt.move(-20)                            # symmetric back
    tt.raw_move(90)                         # raw firmware units (~3 deg)
    tt.goto_angle(63)                       # shortest path to soft angle
    tt.zero()                               # redefine zero here
    tt.spin(cycles=1)                       # full turn
    # photogrammetry: 12 stops around a full circle
    tt.scan_360(steps=12, dwell=0.5,
                callback=lambda i, a: print(f"photo {i} at {a:.1f}°"))
```

Note: `move()`/`goto()`/`spin()`/`scan_360()` take **true degrees**;
`raw_move()` takes firmware units. One CLI `move`/`goto`/`scan`/`spin`
invocation starts its software angle at 0 — use `angle --set <dial>`
to calibrate, or drive longer sessions from Python.

## CLI

```powershell
python hp_turntable.py --port COM3 version
python hp_turntable.py --port COM3 status
python hp_turntable.py --port COM3 angle              # read software angle, no motion
python hp_turntable.py --port COM3 angle --set 44    # calibrate to dial, no motion
python hp_turntable.py --port COM3 move 90
python hp_turntable.py --port COM3 move -90
python hp_turntable.py --port COM3 raw 90            # firmware units (30 = ~1 deg)
python hp_turntable.py --port COM3 goto 0
python hp_turntable.py --port COM3 spin 1
python hp_turntable.py --port COM3 scan 12 --dwell 0.5
```

## Self-test

```powershell
python test_hp_turntable.py
```

Small moves only (3° + 1° + 4-step scan returning to start).
Watch the hardware.
