"""Self-test for hp_turntable driver. WATCH THE TABLE - it will move!"""
from hp_turntable import HPTurntable

with HPTurntable("COM3") as tt:
    print("name:   ", tt.get_name())
    print("version:", tt.get_version())
    assert tt.get_name() == "DAVID TT-1", "unexpected device!"
    print("status: ", tt.get_status())
    assert tt.get_status() == "stopped"

    assert tt.move(0) == 0.0, "move(0) must be a no-op"
    print("move 3 true deg (90 units) ...")
    dt = tt.move(3)
    print(f"  ok in {dt:.2f}s, angle={tt.angle}")
    assert abs(tt.angle - 3.0) < 0.01, tt.angle
    print("raw_move 30 units (=1 deg) ...")
    dt = tt.raw_move(30)
    assert abs(tt.angle - 4.0) < 0.01, tt.angle
    print(f"  ok, angle={tt.angle}")

    print("goto 0 ...")
    tt.goto_angle(0)
    assert tt.angle == 0.0, tt.angle
    print("  ok, angle=0")

    print("scan 4 x 90 deg ...")
    visited = tt.scan_360(steps=4, dwell=0.2,
                          callback=lambda i, a: print(f"  step {i}: {a:.0f} deg"))
    assert len(visited) == 4 and tt.angle == 0.0, (visited, tt.angle)

    print("ALL TESTS PASSED")
