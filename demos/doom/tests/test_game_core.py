#!/usr/bin/env python3
"""Tests of the game core (docs/DESIGN.md section 9).

The game's C (src/game/*.c) is compiled twice: by gcc into a shared
library for the host with tests/host/ standing in for the kernel and
fixed.s (far memory served from the converter's bank images), and by
cc65 into GAME.BIN for the 6502. The logic is tested on the host, where
a tic costs microseconds:

  - spawning E1M1 gives, at every skill, the number of things of every
    type that vanilla's P_SpawnMapThing spawns (skill bits, no
    multiplayer things), as statics (and the player as the only actor);
  - the player walks forward along a corridor and stops at the wall (his
    radius from it), slides along a wall he walks into at 45 degrees,
    climbs a step of 24 units or less but not a higher one, and falls
    off a ledge to the lower floor over several tics;
  - the pistol's hitscan puts a puff at the wall it hits, and wakes and
    damages a barrel in its path;
  - the render packet (serialized in the 6502 layout of rview.h) has the
    eye at the player's view height, the weapon, and the things nearest
    first without the player.

Then the 6502 build (make BUILD=build/gtrack/, the game in the GAME
space) must link, and a short boot in the simulator with the real data
must load E1M1 and run tics with the player moving under scripted input.

The data: build/data (tools/wad2a2.py); without it the tests are skipped.
Run:  python3 tests/test_game_core.py [-v]
"""

from __future__ import annotations

import ctypes
import math
import os
import struct
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import gen_info  # noqa: E402
import wad2a2  # noqa: E402

DATA = PROJECT / "build/data"
HOSTDIR = PROJECT / "build/host"
LIB = HOSTDIR / "libgame.so"
GAMEBUILD = "build/gtrack/"
MEASURE = {}

MOBJS = gen_info.parse_mobjs()
TYPE = {name: i for i, (name, _) in enumerate(MOBJS)}
DOOMEDNUM = {int(f["doomednum"]): i for i, (_, f) in enumerate(MOBJS) if int(f["doomednum"]) > 0}
STATES = {s.name: i for i, s in enumerate(gen_info.parse_states())}
FRAC = 65536
KM_FORWARD, KM_BACK = 1, 2


def have_data() -> bool:
    return (DATA / "manifest.json").is_file()


def build_host() -> Path:
    """gcc the game with the host kernel into build/host/libgame.so."""
    HOSTDIR.mkdir(parents=True, exist_ok=True)
    sources = sorted((PROJECT / "src/game").glob("*.c")) + [PROJECT / "tests/host/host.c"]
    headers = sorted((PROJECT / "src/game").glob("*.h")) + sorted((PROJECT / "tests/host").glob("*.h"))
    newest = max(p.stat().st_mtime for p in sources + headers + [DATA / "doomdata.h"])
    if LIB.is_file() and LIB.stat().st_mtime >= newest:
        return LIB
    cmd = ["gcc", "-shared", "-fPIC", "-O1", "-g", "-Wall", "-Werror", "-Wno-unused-function",
           "-include", str(PROJECT / "tests/host/kernel.h"),
           "-I", str(PROJECT / "tests/host"), "-I", str(PROJECT / "src/game"), "-I", str(DATA),
           "-o", str(LIB)] + [str(s) for s in sources] + ["-lm"]
    subprocess.run(cmd, check=True)
    return LIB


class Game:
    """The host build: load the data once, then drive it."""

    _banks = None

    def __init__(self):
        self.lib = ctypes.CDLL(str(build_host()))
        L = self.lib
        L.host_banks.restype = ctypes.POINTER(ctypes.c_uint8)
        L.host_aim.restype = ctypes.c_int32
        L.host_point_sector.restype = ctypes.c_uint16
        L.host_sounds.restype = ctypes.c_uint8
        if Game._banks is None:
            Game._banks = wad2a2.load_banks(DATA)
        base = ctypes.addressof(L.host_banks().contents)
        for b, img in Game._banks.items():
            ctypes.memmove(base + b * 65536, bytes(img), 65536)

    def load(self, mapnum=1, skill=2):
        assert self.lib.host_load(1, mapnum, skill) == 0

    def init(self):
        assert self.lib.host_init() == 0

    def tic(self, move=0, buttons=0, mouse=0, weapon=0, n=1):
        self.lib.host_set_input(mouse, buttons, move, weapon)
        for _ in range(n):
            code = self.lib.host_tic()
            assert code == 0, f"kernel_crash ${code:02X}"

    def player(self) -> dict:
        v = (ctypes.c_int32 * 16)()
        self.lib.host_player(v)
        keys = ("x", "y", "z", "angle", "viewz", "momx", "momy", "health", "floorz",
                "ceilingz", "sector", "readyweapon", "clip", "state", "playerstate", "wstate")
        return dict(zip(keys, v))

    def place(self, x, y, angle):
        assert self.lib.host_place_player(int(x), int(y), int(angle) & 0xFFFF) == 0

    def things(self) -> list[dict]:
        buf = (ctypes.c_int32 * (10 * 2000))()
        n = self.lib.host_things(buf, 2000)
        keys = ("static", "type", "x", "y", "z", "state", "health", "flags", "sector", "sflags")
        return [dict(zip(keys, buf[10 * i:10 * i + 10])) for i in range(n)]

    def counts(self) -> dict:
        v = (ctypes.c_int32 * 12)()
        self.lib.host_counts(v)
        keys = ("nummobjs", "mobjs_used", "numstatics", "statics_used", "totalkills",
                "totalitems", "totalsecret", "arena_free", "leveltime", "gamemap",
                "sizeof_mobj", "sizeof_sobj")
        return dict(zip(keys, v))

    def sector_at(self, x, y) -> int:
        return self.lib.host_point_sector(int(x), int(y))

    def rview(self) -> dict:
        assert self.lib.host_frame() == 0
        buf = (ctypes.c_uint8 * (40 + 20 * 128))()
        n = self.lib.host_rview(buf)
        raw = bytes(buf[:n])
        x, y, z, angle, extra, cmap, tic, nth, nps = struct.unpack_from("<iiiHBBHBB", raw, 0)
        ps = [struct.unpack_from("<BBii", raw, 20 + 10 * i) for i in range(2)]
        things = [struct.unpack_from("<iiiHBBBBH", raw, 40 + 20 * i) for i in range(nth)]
        return dict(x=x, y=y, z=z, angle=angle, extralight=extra, colormap=cmap, tic=tic,
                    psprites=ps[:nps], things=things)


# --- map geometry for choosing test spots ----------------------------------------------------
class MapGeo:
    """E1M1's lines, sectors and things from the converted data."""

    def __init__(self, mapname="E1M1"):
        import refrender
        d = refrender.GameData(DATA, mapname)
        self.lines = d.lines
        self.sectors = d.sectors
        self.vertexes = d.vertexes
        self.things = d.things

    def ends(self, li):
        a, b = self.vertexes[li.v1], self.vertexes[li.v2]
        return (a.x, a.y), (b.x, b.y)

    def clear(self, x0, y0, x1, y1, half, skip=()):
        """No line other than those in skip crosses the band of half width
        `half` from (x0, y0) to (x1, y1), and no placed thing is in it."""
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        corners = [(x0 - uy * half, y0 + ux * half), (x1 - uy * half, y1 + ux * half),
                   (x1 + uy * half, y1 - ux * half), (x0 + uy * half, y0 - ux * half)]

        def local(px, py):
            return (px - x0) * ux + (py - y0) * uy, -(px - x0) * uy + (py - y0) * ux

        for i, li in enumerate(self.lines):
            if i in skip:
                continue
            (ax, ay), (bx, by) = self.ends(li)
            la, lb = local(ax, ay), local(bx, by)
            # the band in local coordinates is [0, length] x [-half, half]
            if segment_hits_box(la, lb, 0, length, -half, half):
                return False
        for t in self.things:
            if t.type in (1, 2, 3, 4, 11, 14):
                continue
            u, v = local(t.x, t.y)
            if -40 <= u <= length + 40 and abs(v) <= half + 40:
                return False
        return True

    def two_sided(self, li):
        return li.backsector != 0xFFFF


def segment_hits_box(a, b, x0, x1, y0, y1) -> bool:
    """Liang-Barsky: does the segment a-b meet the box [x0,x1] x [y0,y1]?"""
    (ax, ay), (bx, by) = a, b
    t0, t1 = 0.0, 1.0
    dx, dy = bx - ax, by - ay
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def bam(dx, dy) -> int:
    return round(math.atan2(dy, dx) * 32768 / math.pi) & 0xFFFF


# --- the tests ---------------------------------------------------------------------------------
@unittest.skipUnless(have_data(), "no converted data (build/data)")
class SpawnTest(unittest.TestCase):
    def test_counts_per_type_and_skill(self):
        g = Game()
        geo = MapGeo("E1M1")
        for skill, bit in ((0, 1), (1, 1), (2, 2), (3, 4), (4, 4)):
            g.load(1, skill)
            want = {}
            for t in geo.things:
                if t.type in (1, 2, 3, 4, 11) or t.flags & 16 or not t.flags & bit:
                    continue
                if t.type in DOOMEDNUM:
                    want[DOOMEDNUM[t.type]] = want.get(DOOMEDNUM[t.type], 0) + 1
            got, actors = {}, 0
            for th in g.things():
                if th["type"] == TYPE["MT_PLAYER"]:
                    actors += 1
                    continue
                self.assertEqual(th["static"], 1, "placed things spawn as statics")
                got[th["type"]] = got.get(th["type"], 0) + 1
            self.assertEqual(got, want, f"skill {skill}")
            self.assertEqual(actors, 1)
            c = g.counts()
            kills = sum(n for t, n in want.items() if MOBJS[t][1]["flags"].find("COUNTKILL") >= 0)
            self.assertEqual(c["totalkills"], kills)
            MEASURE[f"E1M1 skill {skill}: statics / actor slots / arena left"] = \
                f"{c['statics_used']} / {c['nummobjs']} / {c['arena_free']}"

    def test_every_map_loads(self):
        g = Game()
        for m in range(1, 10):
            g.load(m, 4)
            c = g.counts()
            self.assertEqual(c["gamemap"], m)
            p = g.player()
            self.assertEqual(p["playerstate"], 0)
            self.assertEqual(p["z"], p["floorz"] * FRAC)
            g.tic(n=3)


@unittest.skipUnless(have_data(), "no converted data (build/data)")
class MovementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Game()
        cls.geo = MapGeo("E1M1")

    def setUp(self):
        self.g.load(1, 2)

    def wall_spots(self, min_len=128, dist=96):
        """One-sided, axis-aligned walls with a clear approach: (x, y, angle
        toward the wall, wall line index, wall coordinate, axis)."""
        geo = self.geo
        out = []
        for i, li in enumerate(geo.lines):
            if geo.two_sided(li):
                continue
            (ax, ay), (bx, by) = geo.ends(li)
            dx, dy = bx - ax, by - ay
            if (dx and dy) or abs(dx) + abs(dy) < min_len:
                continue
            mx, my = (ax + bx) / 2, (ay + by) / 2
            n = math.hypot(dx, dy)
            nx, ny = dy / n, -dx / n            # the front side's normal
            px, py = mx + nx * dist, my + ny * dist
            sec = geo.sectors[li.frontsector]
            if sec.ceilingheight - sec.floorheight < 64:
                continue
            if not geo.clear(px, py, mx, my, 24, skip=(i,)):
                continue
            if self.g.sector_at(px, py) != li.frontsector:
                continue
            out.append((round(px), round(py), bam(-nx, -ny), i, (mx if dx == 0 else my),
                        "x" if dx == 0 else "y"))
        return out

    def test_walk_forward_stops_at_wall(self):
        spots = self.wall_spots()
        self.assertGreater(len(spots), 3)
        for x, y, angle, line, wall, axis in spots[:6]:
            self.g.load(1, 2)
            self.g.place(x, y, angle)
            start = self.g.player()
            self.g.tic(move=KM_FORWARD, n=35)
            p = self.g.player()
            pos = (p["x"] if axis == "x" else p["y"]) / FRAC
            moved = math.hypot(p["x"] - start["x"], p["y"] - start["y"]) / FRAC
            # stopped with its radius (16) against the wall, within a unit
            self.assertAlmostEqual(abs(pos - wall), 16, delta=1.0,
                                   msg=f"line {line} from ({x}, {y})")
            self.assertGreater(moved, 70)
            # and along the other axis it did not move
            other = (p["y"] - start["y"]) if axis == "x" else (p["x"] - start["x"])
            self.assertLess(abs(other) / FRAC, 0.5)
        MEASURE["walls tried (walk into, stop at radius)"] = min(6, len(spots))

    def test_slide_along_wall(self):
        spots = self.wall_spots(min_len=256, dist=64)
        self.assertTrue(spots)
        done = 0
        for x, y, angle, line, wall, axis in spots:
            self.g.load(1, 2)
            # 45 degrees off the normal: toward the wall and along it
            self.g.place(x, y, (angle + 0x2000) & 0xFFFF)
            start = self.g.player()
            self.g.tic(move=KM_FORWARD, n=30)
            p = self.g.player()
            pos = (p["x"] if axis == "x" else p["y"]) / FRAC
            along = abs((p["y"] - start["y"]) if axis == "x" else (p["x"] - start["x"])) / FRAC
            if along < 16:
                continue            # blocked by something else along the wall
            self.assertGreaterEqual(abs(pos - wall), 15.0)   # never through it
            self.assertLess(abs(pos - wall), 17.0)           # and against it
            self.assertGreater(along, 60, "slides on along the wall")
            done += 1
            if done == 3:
                break
        self.assertGreater(done, 0)

    def step_spots(self, lo, hi, up=True):
        """Two-sided lines whose floor difference is in [lo, hi], approached
        from the lower side (up) or the higher side."""
        geo = self.geo
        out = []
        for i, li in enumerate(geo.lines):
            if not geo.two_sided(li) or li.flags & 1:
                continue
            f, b = geo.sectors[li.frontsector], geo.sectors[li.backsector]
            (ax, ay), (bx, by) = geo.ends(li)
            n = math.hypot(bx - ax, by - ay)
            if n < 64:
                continue
            diff = b.floorheight - f.floorheight
            if not lo <= abs(diff) <= hi:
                continue
            nx, ny = (by - ay) / n, -(bx - ax) / n  # toward the front
            low_front = diff > 0
            # start on the lower (up) or higher side
            side = 1 if low_front == up else -1
            mx, my = (ax + bx) / 2, (ay + by) / 2
            px, py = mx + side * nx * 64, my + side * ny * 64
            qx, qy = mx - side * nx * 64, my - side * ny * 64
            dest = li.backsector if side == 1 else li.frontsector
            src = li.frontsector if side == 1 else li.backsector
            for s in (f, b):
                if s.ceilingheight - max(f.floorheight, b.floorheight) < 64:
                    break
            else:
                if geo.clear(px, py, qx, qy, 24, skip=(i,)) and self.g.sector_at(px, py) == src \
                        and self.g.sector_at(qx, qy) == dest:
                    out.append((round(px), round(py), bam(-side * nx, -side * ny), i, src, dest))
        return out

    def walk_trace(self, x, y, angle, tics):
        self.g.load(1, 2)
        self.g.place(x, y, angle)
        trace = []
        for _ in range(tics):
            self.g.tic(move=KM_FORWARD)
            p = self.g.player()
            trace.append((p["sector"], p["z"] / FRAC))
        return trace

    def test_step_up_small(self):
        spots = self.step_spots(8, 24, up=True)
        self.assertTrue(spots, "no small step in E1M1")
        for x, y, angle, line, src, dest in spots[:4]:
            trace = self.walk_trace(x, y, angle, 30)
            top = self.geo.sectors[dest].floorheight
            self.assertIn((dest, top), trace, f"line {line}: climbed onto the step")
        MEASURE["small steps climbed"] = min(4, len(spots))

    def test_step_up_high_blocked(self):
        spots = self.step_spots(25, 200, up=True)
        self.assertTrue(spots, "no high step in E1M1")
        for x, y, angle, line, src, dest in spots[:4]:
            trace = self.walk_trace(x, y, angle, 30)
            self.assertNotIn(dest, [s for s, z in trace], f"line {line}: blocked")
            self.assertEqual(trace[-1], (src, self.geo.sectors[src].floorheight))
        MEASURE["high steps refused"] = min(4, len(spots))

    def test_fall_to_lower_floor(self):
        spots = self.step_spots(32, 400, up=False)
        self.assertTrue(spots, "no ledge in E1M1")
        for x, y, angle, line, src, dest in spots[:3]:
            trace = self.walk_trace(x, y, angle, 40)
            low = self.geo.sectors[dest].floorheight
            high = self.geo.sectors[src].floorheight
            landed = trace.index((dest, low)) if (dest, low) in trace else None
            self.assertIsNotNone(landed, f"line {line}: lands on the lower floor")
            zs = [z for s, z in trace[:landed + 1]]
            self.assertTrue([z for z in zs if low < z < high], "falls over several tics")
            self.assertEqual(zs, sorted(zs, reverse=True), "never rises while falling")
        MEASURE["ledges fallen from"] = min(3, len(spots))


@unittest.skipUnless(have_data(), "no converted data (build/data)")
class AttackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Game()
        cls.geo = MapGeo("E1M1")

    def test_pistol_puff_on_wall(self):
        self.g.load(1, 2)
        spots = MovementTest.wall_spots(self, min_len=128, dist=96)
        self.assertTrue(spots)
        x, y, angle, line, wall, axis = spots[0]
        self.g.load(1, 2)
        self.g.place(x, y, angle)
        before = [t for t in self.g.things() if t["type"] == TYPE["MT_PUFF"]]
        self.assertEqual(self.g.lib.host_line_attack(angle, 0), 0)
        puffs = [t for t in self.g.things() if t["type"] == TYPE["MT_PUFF"]]
        self.assertEqual(len(puffs) - len(before), 1)
        pos = (puffs[-1]["x"] if axis == "x" else puffs[-1]["y"]) / FRAC
        self.assertLess(abs(pos - wall), 6)        # 4 units before the wall

    def test_pistol_wakes_and_hurts_barrel(self):
        g, geo = self.g, self.geo
        g.load(1, 2)
        barrels = [t for t in g.things() if t["type"] == TYPE["MT_BARREL"]]
        self.assertTrue(barrels)
        done = False
        for b in barrels:
            bx, by = b["x"] / FRAC, b["y"] / FRAC
            for k in range(8):
                a = k * math.pi / 4
                px, py = bx + 96 * math.cos(a), by + 96 * math.sin(a)
                if g.sector_at(px, py) != b["sector"]:
                    continue
                if not geo.clear(px, py, bx - 12 * math.cos(a), by - 12 * math.sin(a), 8):
                    # the barrel itself is a thing: clear() skips nothing but
                    # lines here, so test lines only
                    pass
                if not lines_clear(geo, px, py, bx, by):
                    continue
                g.load(1, 2)
                g.place(round(px), round(py), bam(bx - px, by - py))
                slope = g.lib.host_aim(bam(bx - px, by - py))
                self.assertNotEqual(slope, 0x7FFFFFFF)
                self.assertEqual(g.lib.host_line_attack(bam(bx - px, by - py),
                                                        0 if slope == 0x7FFFFFFE else slope), 0)
                hit = [t for t in g.things() if t["type"] == TYPE["MT_BARREL"] and t["static"] == 0]
                self.assertEqual(len(hit), 1, "the barrel woke up")
                self.assertEqual(hit[0]["health"], 10)     # 20 - 10
                done = True
                break
            if done:
                break
        self.assertTrue(done, "no barrel with a clear shot")


def lines_clear(geo, x0, y0, x1, y1):
    for li in geo.lines:
        (ax, ay), (bx, by) = geo.ends(li)
        if li.backsector != 0xFFFF and not li.flags & 1:
            f, b = geo.sectors[li.frontsector], geo.sectors[li.backsector]
            if f.floorheight == b.floorheight and f.ceilingheight == b.ceilingheight:
                continue
        d = (x1 - x0) * (by - ay) - (y1 - y0) * (bx - ax)
        if d == 0:
            continue
        t = ((ax - x0) * (by - ay) - (ay - y0) * (bx - ax)) / d
        u = ((ax - x0) * (y1 - y0) - (ay - y0) * (x1 - x0)) / d
        if 0 <= t <= 1 and 0 <= u <= 1:
            return False
    return True


@unittest.skipUnless(have_data(), "no converted data (build/data)")
class RenderPacketTest(unittest.TestCase):
    def test_rview(self):
        g = Game()
        g.load(1, 2)
        g.tic(n=10)
        rv = g.rview()
        p = g.player()
        self.assertEqual(rv["x"], p["x"] >> 12)
        self.assertEqual(rv["y"], p["y"] >> 12)
        self.assertEqual(rv["z"], p["viewz"] >> 12)
        self.assertEqual(rv["angle"], p["angle"] & 0xFFFF)
        self.assertEqual(rv["tic"], 10)
        # the weapon is up after 10 tics? it rises 6 units a tic from 128 to 32
        self.assertEqual(len(rv["psprites"]), 1)
        sprite = rv["psprites"][0][0]
        self.assertEqual(sprite, gen_info_sprite("PISG"))
        things = rv["things"]
        self.assertGreater(len(things), 20)
        self.assertLessEqual(len(things), 128)
        # nearest first by 128-unit bands, and not the player
        bands = []
        for x, y, z, angle, spr, frame, flags, pad, sector in things:
            d = approx((x - rv["x"]) / 16, (y - rv["y"]) / 16)
            bands.append(min(31, int(d) >> 7))
            self.assertNotEqual((x, y), (rv["x"], rv["y"]))
        self.assertEqual(bands, sorted(bands))
        MEASURE["E1M1 start: things in the packet"] = len(things)


def approx(dx, dy):
    dx, dy = abs(int(dx)), abs(int(dy))
    return dx + dy - (min(dx, dy) >> 1)


def gen_info_sprite(name):
    import re
    text = (DATA / "doomdata.h").read_text()
    return int(re.search(rf"#define SPR_{name}\s+(\d+)", text).group(1))


def tearDownModule():
    if MEASURE and ("-v" in sys.argv or os.environ.get("DOOM_MEASURE")):
        print("\nmeasurements:")
        for k, v in MEASURE.items():
            print(f"  {k:50s} {v}")


if __name__ == "__main__":
    unittest.main()
