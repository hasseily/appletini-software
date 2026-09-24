#!/usr/bin/env python3
"""End-to-end smoke tests of the port in the py65 machine, through
tools/run_editor.py's Runner (docs/DESIGN.md sections 4, 8 and 9).

Run:  python3 tests/test_editor.py        (from the project directory)

Each test boots build/PCS.SYSTEM (make is run when it is missing) and
drives it with the action strings run_editor.py accepts, sampling the
mailbox and the object database after every frame:

  boot     the editor is reached (MB_STATE), the mouse card is found, the
           table and the kit are drawn, the --stats JSON is written
  drag     a part pressed in the kit and dragged onto the table (at most
           63 pixels per frame, docs/DESIGN.md section 5) becomes a new
           object with its L-record x on the table; one dropped back on
           the panel is deleted again
  play     the Play tool enters test play (MB_STATE), the plunger launches
           the ball, which then moves, a flipper key reaches the mailbox,
           Esc returns to the editor, and after a mode's first frames no
           frame's work exceeds the 60 Hz budget
  shots    the screenshots of the run are not blank and the play screen
           shows the logo band instead of the kit

The //e ROM comes from $APPLETINI_ROOT/docs/Apple2e_Enhanced.rom; a blank
ROM stands in when it is missing (the port never reads it here).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
BUILD = PROJECT / "build"
sys.path.insert(0, str(TOOLS))

import run_editor  # noqa: E402

try:
    from PIL import Image
except ImportError:      # pragma: no cover
    Image = None

# src/pcs.inc
MAILBOX = 0x0300
MB_STATE, MB_INPUT, MB_HAVEMOUSE = 0x0304, 0x030F, 0x0311
ST_EDIT, ST_PLAY = 1, 5
def _pbbase():
    """PBBASE from the linked labels (src/pcs.cfg places the database)."""
    try:
        for line in (BUILD / "PCS.lbl").read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2] == ".PBBASE":
                return int(parts[1], 16)
    except OSError:
        pass
    return 0xA000


PBBASE = _pbbase()
PBDATA = PBBASE + 0x1C
OBJ_LIBOBJ = 3
L_Y, L_X, L_X1, L_Y1 = 2, 3, 17, 18
TABLE_W, TABLE_H, PANEL_X = 154, 192, 154
SHR_BASE, SHR_ROW = 0x2000, 160
COL_PANEL = 1
SPR_BALL_FIRST, SPR_BMP1_FIRST, SPR_BMP2_FIRST = 22, 23, 25
# tools/layout.py: the Play tool's box (y 34..51, x 292..319)
PLAY_TOOL = (306, 43)
KEY_ESC, KEY_SPACE, KEY_Z = 27, 32, ord("Z")
MAX_DRAG_STEP = 63          # step size of the staged drag fixture below
GRACE_BEFORE, GRACE_AFTER = 1, 3    # frames around a mode switch that may run long


def ensure_build() -> None:
    if not (BUILD / "PCS.SYSTEM").exists() or not (BUILD / "PCS.lbl").exists():
        subprocess.run(["make"], cwd=PROJECT, check=True, capture_output=True)


def rom_path() -> Path:
    rom = Path(run_editor.DEFAULT_ROM)
    if rom.exists():
        return rom
    blank = Path(tempfile.gettempdir()) / "pcs_test_blank_rom.bin"
    if not blank.exists() or blank.stat().st_size != 0x4000:
        blank.write_bytes(bytes(0x4000))
    return blank


class Probe(run_editor.Runner):
    """A Runner that samples memory words after every frame."""

    def __init__(self, args, watch=(), screen_watch=()):
        super().__init__(args)
        self.watch = list(watch)            # (name, address, width)
        self.screen_watch = list(screen_watch)  # (name, x, y)
        self.samples = []

    def frame_done(self) -> None:
        super().frame_done()
        m = self.machine.main
        sample = {name: (m[a] | (m[a + 1] << 8)) if w == 2 else m[a]
                  for name, a, w in self.watch}
        for name, x, y in self.screen_watch:
            b = self.machine.aux_banks[0][SHR_BASE + SHR_ROW * y + x // 2]
            sample[name] = b >> 4 if x % 2 == 0 else b & 15
        self.samples.append(sample)


def make_args(out: Path, frames: int, do=(), stats=True):
    return argparse.Namespace(rom=rom_path(), speed=33, frames=frames, out=str(out), do=list(do), skip_title=True,
                              shot=[], quiet=True, trace=[], trace_limit=0,
                              stats=str(out / "stats.json") if stats else None)


def run(out: Path, frames: int, do=(), watch=(), screen_watch=()) -> Probe:
    ensure_build()
    runner = Probe(make_args(out, frames, do), watch, screen_watch)
    with contextlib.redirect_stdout(io.StringIO()):
        runner.run()
    return runner


def objects(main) -> list[tuple[int, bytes]]:
    """[(address, record)] of the database's objects."""
    n = main[PBDATA]
    sizes = main[PBDATA + 1:PBDATA + 1 + n]
    a = PBDATA + 1 + n
    out = []
    for size in sizes:
        out.append((a, bytes(main[a:a + size])))
        a += size
    return out


def lrecord(addr: int, rec: bytes) -> int:
    return addr + 3 + 2 * rec[2]


def find_part(runner, first_sprite: int) -> int | None:
    """The L-record address of the first object whose sprite is `first_sprite`."""
    ptr = runner.labels["spr_dir"] + 4 * first_sprite
    for a, rec in objects(runner.machine.main):
        if rec[0] == OBJ_LIBOBJ:
            l = lrecord(a, rec)
            if runner.machine.main[l] | (runner.machine.main[l + 1] << 8) == ptr:
                return l
    return None


def kit_press_point(name: str) -> tuple[int, int]:
    """The centre of a part's icon in the kit (build/parts.json keeps the
    original template positions, docs/DESIGN.md section 3)."""
    parts = json.loads((BUILD / "parts.json").read_text())["parts"]
    p = next(q for q in parts if q["name"] == name)
    w, h = p["box"]
    return p["x0"] + w // 2, p["y0"] - p["hoty"] + h // 2


def pixel(runner, x: int, y: int) -> int:
    b = runner.machine.aux_banks[0][SHR_BASE + SHR_ROW * y + x // 2]
    return b >> 4 if x % 2 == 0 else b & 15


def colours_in(path: Path) -> int:
    if Image is None:
        return 99
    with Image.open(path) as im:
        return len(im.convert("RGB").getcolors(maxcolors=1 << 20) or [])


def check_budget(test, stats: dict) -> None:
    """After a mode's first frames, every frame's work fits the frame."""
    rows = stats["frames"]
    budget = stats["frame_cycles"]
    switches = [t["frame"] for t in stats["transitions"]]
    exempt = set()
    for t in switches:
        exempt.update(range(t - GRACE_BEFORE, t + GRACE_AFTER + 1))
    over = [(r["frame"], r["state"], r["work"]) for r in rows
            if r["frame"] not in exempt and r["work"] > budget]
    test.assertEqual(over, [], f"frames over the {budget}-cycle budget (state, work): {over}")


class EditorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pcs_editor_")
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def stats(self) -> dict:
        path = self.out / "stats.json"
        self.assertTrue(path.exists(), "--stats file missing")
        return json.loads(path.read_text())


class TestBoot(EditorCase):
    def test_reaches_the_editor(self):
        r = run(self.out, 4, watch=[("state", MB_STATE, 1)])
        main = r.machine.main
        self.assertEqual(bytes(main[MAILBOX:MAILBOX + 4]), b"PCS1")
        self.assertEqual([s["state"] for s in r.samples], [ST_EDIT] * 4)
        self.assertEqual(main[MB_HAVEMOUSE], 1, "the mouse card was not found")
        self.assertEqual(r.machine.bank, 0, "RamWorks bank 0 must be selected between frames")
        self.assertEqual(r.machine.newvideo, 0xC1, "SHR 320 mode")
        self.assertEqual(main[PBDATA], objects(main).__len__())
        self.assertIsNotNone(find_part(r, SPR_BALL_FIRST), "the default table has no ball")
        # the table shows the default table, the panel the kit
        table = {pixel(r, x, y) for y in range(0, TABLE_H, 4) for x in range(0, TABLE_W, 4)}
        self.assertGreater(len(table), 3, "the table region is flat")
        panel = {pixel(r, x, y) for y in range(0, TABLE_H, 3) for x in range(160, 320, 3)}
        self.assertGreater(len(panel - {COL_PANEL}), 3, "the kit is not drawn")
        self.assertTrue((self.out / "final.png").exists())
        self.assertGreater(colours_in(self.out / "final.png"), 8)

    def test_stats_file(self):
        r = run(self.out, 6, do=["2:move 100 100"])
        s = self.stats()
        self.assertEqual(s["speed"], 33)
        self.assertEqual(s["frame_cycles"], r.machine.frame_cycles)
        self.assertEqual(len(s["frames"]), 6)
        for i, row in enumerate(s["frames"]):
            self.assertEqual(row["frame"], i)
            self.assertEqual(row["state"], "edit")
            for key in ("work", "bus", "io", "writes", "rects"):
                self.assertIsInstance(row[key], int, key)
        self.assertEqual([(st[0], st[1], st[2], st[3], st[4], st[5]) for st in r.stats],
                         [(1, row["work"], row["bus"], row["io"], row["writes"], row["rects"])
                          for row in s["frames"]])
        self.assertEqual(s["transitions"], [{"frame": 0, "state": "edit"}])
        self.assertEqual(s["summary"]["frames"], 6)
        self.assertEqual(s["summary"]["work"]["max"], max(row["work"] for row in s["frames"]))
        self.assertIn("frame 2: move 100 100", s["log"])
        # an idle editor frame is cheap: a cursor save-under and the input
        idle = s["frames"][-1]
        self.assertLess(idle["work"], s["frame_cycles"] // 10)
        self.assertLess(idle["bus"], 1000)
        self.assertLess(idle["io"], 100)


class TestDrag(EditorCase):
    def drag_actions(self, press, path, t0=3):
        """Press at `press`, then move along `path` one point every three
        frames, then release; every step is at most MAX_DRAG_STEP pixels."""
        actions = [f"{t0}:move {press[0]} {press[1]}", f"{t0 + 2}:down"]
        last = press
        t = t0 + 5
        for x, y in path:
            self.assertLessEqual(max(abs(x - last[0]), abs(y - last[1])), MAX_DRAG_STEP, "drag step too long")
            actions.append(f"{t}:drag {x} {y}")
            last = (x, y)
            t += 3
        actions.append(f"{t + 1}:up")
        return actions, t + 1

    def test_add_object_keeps_scan_gap_at_capacity_boundary(self):
        r = run(self.out, 4)
        main, cpu = r.machine.main, r.machine.mpu
        word = lambda a: main[a] | main[a + 1] << 8
        midbtm = word(0xA1)
        count = main[PBDATA]
        # BMP1 has OBJLEN=$23, so ADDOBJ moves 36 bytes including its size
        # byte. The remaining gap must still hold the converter's 32 bytes.
        self.assertEqual(main[r.labels["OBJLEN"] + 5], 35)

        def enter_with_gap(gap):
            top = midbtm + gap
            main[0xA3], main[0xA4] = top & 0xFF, top >> 8
            main[top:top + 4] = b"GUAR"   # first bytes of the upper span region
            cpu.pc = r.labels["ADDOBJ"]
            cpu.a, cpu.x, cpu.y, cpu.sp = 35, 0, 0, 0xFB
            main[0x1FC], main[0x1FD] = 0x33, 0x12  # RTS destination $1234
            return top

        for gap in (32, 67):
            top = enter_with_gap(gap)
            for _ in range(32):
                if cpu.pc == 0x1234:
                    break
                cpu.step()
            self.assertEqual(cpu.pc, 0x1234, f"gap {gap} accepted a 36-byte object")
            self.assertEqual(word(0xA1), midbtm)
            self.assertEqual(main[PBDATA], count)
            self.assertEqual(bytes(main[top:top + 4]), b"GUAR")

        top = enter_with_gap(68)
        for _ in range(20_000):
            if cpu.pc == r.labels["ADDOBJ2"]:
                break
            cpu.step()
        self.assertEqual(cpu.pc, r.labels["ADDOBJ2"], "the exact-fit case was rejected")
        self.assertEqual(word(0xA1), midbtm + 36)
        self.assertEqual(top - word(0xA1), 32)
        self.assertEqual(bytes(main[top:top + 4]), b"GUAR")

    def test_scanline_rejects_insufficient_gap_before_writing(self):
        r = run(self.out, 4)
        main, cpu = r.machine.main, r.machine.mpu
        word = lambda a: main[a] | main[a + 1] << 8
        midbtm = word(0xA1)
        row = 40
        pbdx = r.labels["PBDX"] + row
        abort = r.labels["ABORTSCN2"]
        abort_overflow = r.labels["ABORTSCN3"]
        write = r.labels["DOSCN5"]

        def enter_with_gap(gap, row_bytes=0):
            top = midbtm + gap
            main[0xA3], main[0xA4] = top & 0xFF, top >> 8
            main[top:top + 4] = b"GUAR"
            main[0x9E] = 0                 # SCANMODE: normal scan
            main[0x1F] = row               # SCANLINE
            main[0x25] = 4                 # HCNT: one four-byte span
            main[pbdx] = row_bytes
            cpu.pc = r.labels["DOSCN4"]
            cpu.sp = 0xFB
            for _ in range(64):
                if cpu.pc in (abort, abort_overflow, write):
                    break
                cpu.step()
            return top

        for gap in (2, 35):
            top = enter_with_gap(gap)
            self.assertEqual(cpu.pc, abort, f"gap {gap} wrote before rejecting the row")
            self.assertEqual(word(0xA1), midbtm)
            self.assertEqual(main[pbdx], 0)
            self.assertEqual(bytes(main[top:top + 4]), b"GUAR")

        top = enter_with_gap(36)           # four bytes of span plus 32 spare
        self.assertEqual(cpu.pc, write, "a row that exactly fits was rejected")
        self.assertEqual(main[pbdx], 4)
        self.assertEqual(bytes(main[top:top + 4]), b"GUAR")

        top = enter_with_gap(36, row_bytes=252)
        self.assertEqual(cpu.pc, abort_overflow, "an overflowing row reached the span write")
        self.assertEqual(main[pbdx], 252)
        self.assertEqual(bytes(main[top:top + 4]), b"GUAR")

    def test_part_from_the_kit_lands_on_the_table(self):
        press = kit_press_point("BMP1")
        self.assertGreaterEqual(press[0], PANEL_X)
        actions, released = self.drag_actions(press, [(120, 50), (70, 45), (60, 40)])
        r = run(self.out, released + 8, do=actions, watch=[("count", PBDATA, 1), ("state", MB_STATE, 1)])
        counts = [s["count"] for s in r.samples]
        self.assertEqual(counts[-1], counts[0] + 1, f"object count per frame: {counts}")
        self.assertTrue(all(s["state"] == ST_EDIT for s in r.samples))
        addr, rec = objects(r.machine.main)[-1]
        self.assertEqual(rec[0], OBJ_LIBOBJ)
        l = lrecord(addr, rec)
        main = r.machine.main
        self.assertEqual(main[l] | (main[l + 1] << 8), r.labels["spr_dir"] + 4 * SPR_BMP1_FIRST,
                         "the new object is not a BMP1")
        x, y = main[l + L_X], main[l + L_Y]
        self.assertLess(x, TABLE_W, "L-record x is not on the table")
        self.assertLess(x + 21, TABLE_W)
        self.assertLess(y, TABLE_H)
        # its vertices moved with it
        xs = rec[3:3 + rec[2]]
        self.assertTrue(all(v < TABLE_W for v in xs), f"vertices {list(xs)}")
        # and it is drawn there: bumper colours inside its box
        box = {pixel(r, x + dx, y + dy) for dx in range(0, 21, 2) for dy in range(0, 14, 2)}
        self.assertGreater(len(box - {0}), 1, "the dropped bumper is not on the screen")
        self.assertGreater(colours_in(self.out / "final.png"), 8)
        check_budget(self, self.stats())

    def test_direct_mouse_jump_from_kit_to_table(self):
        """A mouse may cross the panel/table boundary in one frame."""
        press = kit_press_point("BMP1")
        target = (60, 40)
        self.assertGreater(abs(press[0] - target[0]), MAX_DRAG_STEP)
        actions = [f"3:move {press[0]} {press[1]}", "5:down",
                   f"8:drag {target[0]} {target[1]}", "11:up"]
        r = run(self.out, 20, do=actions, watch=[("count", PBDATA, 1)])
        counts = [s["count"] for s in r.samples]
        self.assertEqual(counts[-1], counts[0] + 1, f"object count per frame: {counts}")
        _addr, rec = objects(r.machine.main)[-1]
        self.assertEqual(rec[0], OBJ_LIBOBJ)
        xs = rec[3:3 + rec[2]]
        self.assertTrue(all(x < TABLE_W for x in xs), f"vertices {list(xs)}")

    def test_part_dropped_on_the_panel_is_deleted(self):
        press = kit_press_point("BMP2")
        actions, released = self.drag_actions(press, [(130, 60), (100, 70), (150, 70), (200, 70)])
        r = run(self.out, released + 8, do=actions, watch=[("count", PBDATA, 1)])
        counts = [s["count"] for s in r.samples]
        self.assertEqual(max(counts), counts[0] + 1, "the part was never picked up")
        self.assertEqual(counts[-1], counts[0], f"object count per frame: {counts}")

    def test_polygon_drag_refreshes_vertex_fringe_and_brush_fills_it(self):
        # POLY is deliberately black in the kit. It must still show its
        # complete 3x3 vertex dots, and a second drag must erase the old
        # ones. The red swatch chooses a colour; the Brush applies it.
        actions = ["3:move 173 35", "5:down", "8:drag 125 55", "11:drag 80 80", "14:up",
                   "20:move 80 80", "22:down", "25:drag 110 100", "28:up",
                   "34:click 300 94", "40:click 278 43", "46:click 110 100",
                   "50:move 300 150"]
        r = run(self.out, 55, do=actions,
                screen_watch=[("old_dot", 72, 71), ("new_dot", 102, 91),
                              ("interior", 110, 100)])
        self.assertEqual(r.samples[18]["old_dot"], 4, "placed polygon lost the dot's top row")
        self.assertEqual(r.samples[32]["old_dot"], 0, "drag left the old dot behind")
        self.assertEqual(r.samples[32]["new_dot"], 4, "drag clipped the new dot's top row")
        _addr, rec = objects(r.machine.main)[-1]
        self.assertEqual(rec[0:3], bytes([1, 6, 4]), "Brush did not paint the new polygon red")
        self.assertEqual(r.samples[-1]["interior"], 6, "polygon's red fill is missing")

    def test_pointer_moves_a_polygon_vertex(self):
        actions = ["3:move 173 35", "5:down", "8:drag 125 55", "11:drag 80 80", "14:up",
                   "20:click 306 9", "27:move 73 72", "29:down", "32:drag 65 64", "35:up"]
        r = run(self.out, 43, do=actions)
        _addr, rec = objects(r.machine.main)[-1]
        self.assertEqual(rec[0:3], bytes([1, 0, 4]))
        self.assertEqual((rec[6], rec[10]), (65, 64), "Pointer did not move the selected vertex")


class TestPlay(EditorCase):
    ESC_AT = 230

    def test_elasticity_tables_point_to_relocated_coefficients(self):
        r = run(self.out, 15, do=[f"3:click {PLAY_TOOL[0]} {PLAY_TOOL[1]}"])
        self.assertEqual(r.machine.main[MB_STATE], ST_PLAY)
        main, labels = r.machine.main, r.labels
        expected = ["C84375", "C7875", "C675", "C675",
                    "C45", "C225", "C1125", "C05625"]
        for module in ("RUN", "RUN2"):
            low = labels[f"{module}_ELASTLO"]
            high = labels[f"{module}_ELASTHI"]
            actual = [main[low + i] | main[high + i] << 8 for i in range(8)]
            self.assertEqual(actual, [labels[name] for name in expected], module)
        # Default elasticity is 4, and INITWORLD patches BOUNCE's lookup.
        wmod2 = labels["RUN_WMOD2"]
        self.assertEqual(main[wmod2] | main[wmod2 + 1] << 8, labels["C45"])

    def play_run(self):
        actions = [f"3:click {PLAY_TOOL[0]} {PLAY_TOOL[1]}",
                   f"30:hold {KEY_SPACE}", "55:release",            # pull and release the plunger
                   f"150:hold {KEY_Z}", "158:release",             # left flipper
                   f"{self.ESC_AT}:key {KEY_ESC}"]
        # the ball's L-record: bytes 17/18 hold its live position in play
        ensure_build()
        probe = Probe(make_args(self.out, 2), [])
        with contextlib.redirect_stdout(io.StringIO()):
            probe.run()
        ball = find_part(probe, SPR_BALL_FIRST)
        self.assertIsNotNone(ball)
        watch = [("state", MB_STATE, 1), ("input", MB_INPUT, 1), ("bx", ball + L_X1, 1), ("by", ball + L_Y1, 1)]
        return run(self.out, self.ESC_AT + 20, do=actions, watch=watch)

    def test_play_launch_flipper_and_esc(self):
        r = self.play_run()
        states = [s["state"] for s in r.samples]
        first_play = states.index(ST_PLAY)
        self.assertLess(first_play, 12, "the Play tool did not enter play")
        self.assertTrue(all(st == ST_PLAY for st in states[first_play:self.ESC_AT]),
                        "play was left before Esc")
        back = next(i for i in range(self.ESC_AT, len(states)) if states[i] == ST_EDIT)
        self.assertLess(back, self.ESC_AT + 8, "Esc did not return to the editor")
        self.assertTrue(all(st == ST_EDIT for st in states[back:]))
        # the ball rests in the launcher lane, is kicked up, and moves
        rest = (r.samples[first_play + 4]["bx"], r.samples[first_play + 4]["by"])
        seen = {(s["bx"], s["by"]) for s in r.samples[60:self.ESC_AT]}
        self.assertGreater(len(seen), 8, f"the ball did not move: {seen}")
        held = [s["by"] for s in r.samples[42:55]]
        self.assertEqual(len(set(held)), 1, "the ball left the launcher before Space was released")
        self.assertLess(r.samples[60]["by"], held[0] - 8,
                        "releasing Space did not launch the charged ball")
        top = min(s["by"] for s in r.samples[55:120])
        self.assertLess(top, rest[1] - 8, "the plunger did not launch the ball upwards")
        # the flipper key reaches the runtime's input
        flips = [s["input"] & 0x40 for s in r.samples[151:158]]
        self.assertTrue(any(flips), "Z did not set the left flipper bit")
        self.assertFalse(any(s["input"] & 0x40 for s in r.samples[170:200]))
        # ticks per frame follow the speed slider (WSET+1 = 4: 4 ticks)
        self.assertEqual(r.machine.main[MAILBOX + 16], 4)
        check_budget(self, self.stats())
        s = self.stats()
        self.assertEqual([t["state"] for t in s["transitions"]], ["edit", "play", "edit"])
        play_rows = [row for row in s["frames"] if row["state"] == "play"][GRACE_AFTER:]
        self.assertLess(max(row["work"] for row in play_rows), s["frame_cycles"])
        self.assertLess(max(row["bus"] for row in play_rows), 4000, "play frames must write little")

    def test_screenshots(self):
        r = self.play_run()
        shots = sorted(self.out.glob("*.png"))
        names = [p.name for p in shots]
        self.assertIn("final.png", names)
        play = [p for p in shots if p.name.startswith("state_play_")]
        edit = [p for p in shots if p.name.startswith("state_edit_")]
        self.assertEqual(len(play), 1, names)
        self.assertEqual(len(edit), 1, names)
        for p in shots:
            self.assertGreater(colours_in(p), 8, f"{p.name} is blank")
        if Image is None:
            self.skipTest("Pillow not installed")
        # the play screen shows the logo band where the editor shows the kit
        with Image.open(play[0]) as a, Image.open(edit[0]) as b:
            band_a = a.convert("RGB").crop((320, 0, 640, 128)).tobytes()
            band_b = b.convert("RGB").crop((320, 0, 640, 128)).tobytes()
        self.assertNotEqual(band_a, band_b)
        del r


if __name__ == "__main__":
    unittest.main(verbosity=2)
