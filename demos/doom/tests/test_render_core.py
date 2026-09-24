#!/usr/bin/env python3
"""The 6502 renderer's core against the reference (docs/DESIGN.md section 7).

The linked program (the renderer track's build, BUILD below) runs in the
py65 test machine through tools/doomdbg.py: a view goes into the render
packet (_rview in bank 1, nthings = npsprites = 0), render_map selects the
map, render_frame runs, and the view buffer must equal, byte for byte,
tools/refrender.py's Renderer.render of the same view with no things and no
weapon (walls, planes, sky and the two-sided middle textures;
tests/test_render_masked.py has the things and the weapon). Covered:

  - the 36 deliverable views (every map: player start + pick_views)
  - the 6 golden views of tests/test_refrender.py (eye, tic, extralight,
    flat-shaded as there)
  - flat-shaded mode (render_shaded = 1) on a view of every map
  - 40 random views (refrender.random_views over the nine maps)
  - animation: textures and flats of E1M1 at several tics

and the cycles of render_frame (Dbg.call) for every view: mean, p90, max.

    python3 tests/test_render_core.py            the tests
    python3 tests/test_render_core.py -v         + the cycle statistics
    python3 tests/test_render_core.py --view E1M1 X Y Z ANGLE [--tic N] [--shaded]
                                                 one view: diff, cycles, PNGs
    python3 tests/test_render_core.py --profile [--views N]
                                                 cycles by routine (labels)
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))

import doomdbg  # noqa: E402
import refrender as R  # noqa: E402

BUILD = Path(os.environ.get("RENDER_BUILD", ROOT / "build/rtrack"))
DATA = ROOT / "build/data"
VIEWBUF = 0x8B80
MAPS = [f"E1M{i}" for i in range(1, 10)]
MEASURE = {}


def slot_of(mapname: str) -> int:
    return 9 * (int(mapname[1]) - 1) + int(mapname[3]) - 1


class RenderSim:
    """The booted program with the renderer, driven view by view."""

    def __init__(self, build: Path = BUILD):
        self.dbg = doomdbg.Dbg(frames=0, build=build, data=DATA)
        self.m = self.dbg.m
        self.L = self.dbg.L

    # the language card as the renderer sees it ($E000 area and bank 1 $D000)
    def lc_write(self, label: str, value: int) -> None:
        a = self.L[label]
        assert a >= 0xE000, label
        self.m.lc[False][a - 0xC000] = value & 0xFF

    def set_view(self, mapname: str, view: R.View, tic=0, extralight=0, fixedcolormap=None,
                 shaded=False) -> None:
        self.lc_write("render_map", slot_of(mapname))
        self.lc_write("render_shaded", 1 if shaded else 0)
        pk = bytearray(R.RV_HEADER if hasattr(R, "RV_HEADER") else 40)
        for off, v in ((0, view.x), (4, view.y), (8, view.z)):
            pk[off:off + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")
        pk[12:14] = view.angle.to_bytes(2, "little")
        pk[14] = extralight
        pk[15] = 0xFF if fixedcolormap is None else fixedcolormap
        pk[16:18] = (tic & 0xFFFF).to_bytes(2, "little")
        pk[18] = 0          # nthings
        pk[19] = 0          # npsprites
        rv = self.L["_rview"]
        self.m.bank_memory(1)[rv:rv + len(pk)] = pk

    def render(self) -> tuple[bytes, int]:
        cycles = self.dbg.call("render_frame", limit=200_000_000)
        return bytes(self.m.main[VIEWBUF:VIEWBUF + R.VIEW_W * R.VIEW_H]), cycles


_data = {}


def game_data(mapname):
    if mapname not in _data:
        _data[mapname] = R.GameData(DATA, mapname)
    return _data[mapname]


def reference(mapname, view, tic=0, extralight=0, fixedcolormap=None, shaded=False):
    r = R.Renderer(game_data(mapname), shaded=shaded)
    buf, st = r.render(view, (), (), tic=tic, extralight=extralight,
                       fixedcolormap=fixedcolormap)
    return bytes(buf), st


def diff(a: bytes, b: bytes) -> list[tuple[int, int, int, int]]:
    """[(x, y, got, want)] of the differing pixels."""
    out = []
    for i, (p, q) in enumerate(zip(a, b)):
        if p != q:
            out.append((i // R.VIEW_H, i % R.VIEW_H, p, q))
    return out


def save_png(mapname, buf, path):
    R.to_png(buf, game_data(mapname).rgb, path)


def view_sets():
    """{set name: [(name, map, View, tic, extralight, fixedcolormap, shaded)]},
    cached in BUILD/render_views.json (pick_views renders candidates)."""
    cache = BUILD / "render_views.json"
    if cache.exists():
        raw = json.loads(cache.read_text())
    else:
        raw = {"deliverables": [], "golden": [], "shaded": [], "random": [], "anim": [],
               "fixed": []}
        rnd = {}
        for mapname in MAPS:
            d = game_data(mapname)
            views = [("start", R.player_start(d))] + R.pick_views(d)
            for n, (label, v) in enumerate(views):
                raw["deliverables"].append((f"{mapname}_{n} {label}", mapname,
                                            (v.x, v.y, v.z, v.angle), 0, 0, None, False))
            raw["shaded"].append((f"{mapname} start shaded", mapname,
                                  (views[0][1].x, views[0][1].y, views[0][1].z,
                                   views[0][1].angle), 0, 0, None, True))
            rnd[mapname] = [(v.x, v.y, v.z, v.angle) for v in R.random_views(d, 5, seed=1)]
        # 40 of --sweep's random views (seed 1), the maps in turn
        for i in range(40):
            mapname = MAPS[i % 9]
            raw["random"].append((f"{mapname} random {i // 9}", mapname, rnd[mapname][i // 9],
                                  0, 0, None, False))
        import test_refrender as TR
        for name, mapname, eye, tic, extra, shaded, _ in TR.GOLDEN:
            raw["golden"].append((name, mapname, eye, tic, extra, None, shaded))
        # animation: views whose picture changes between tics 0 and 8
        found = []
        for name, mapname, eye, *_ in raw["deliverables"] + raw["random"]:
            v = R.View(*eye)
            if reference(mapname, v, 0)[0] != reference(mapname, v, 8)[0]:
                found.append((name, mapname, eye))
            if len(found) == 3:
                break
        for name, mapname, eye in found:
            for tic in (8, 16, 24, 37, 1000):
                raw["anim"].append((f"{name} tic {tic}", mapname, eye, tic, 0, None, False))
        # a fixed colormap (the invulnerability-style full bright) and extralight
        e = raw["deliverables"][1]
        raw["fixed"].append((e[0] + " fixed 0", e[1], e[2], 0, 0, 0, False))
        raw["fixed"].append((e[0] + " extralight 2", e[1], e[2], 0, 2, None, False))
        raw["fixed"].append((e[0] + " fixed 5 shaded", e[1], e[2], 0, 0, 5, True))
        cache.write_text(json.dumps(raw, indent=1))
    return {k: [(n, m, R.View(*eye), tic, ex, fx, sh) for n, m, eye, tic, ex, fx, sh in v]
            for k, v in raw.items()}


# --- running views in worker processes ----------------------------------------------------

_sim = None


def _run_one(job):
    """(name, map, eye, tic, extralight, fixed, shaded) -> (name, diffs, cycles, first diffs)"""
    global _sim
    if _sim is None:
        _sim = RenderSim()
    name, mapname, eye, tic, extra, fixed, shaded = job
    view = R.View(*eye)
    _sim.set_view(mapname, view, tic, extra, fixed, shaded)
    got, cycles = _sim.render()
    want, _ = reference(mapname, view, tic, extra, fixed, shaded)
    dd = diff(got, want)
    return name, len(dd), cycles, dd[:5]


def run_views(views, workers=None):
    jobs = [(n, m, (v.x, v.y, v.z, v.angle), tic, ex, fx, sh) for n, m, v, tic, ex, fx, sh in views]
    workers = workers or int(os.environ.get("RENDER_WORKERS", "3"))
    if workers <= 1:
        return [_run_one(j) for j in jobs]
    import multiprocessing as mp
    with mp.get_context("fork").Pool(workers) as pool:
        return pool.map(_run_one, jobs, chunksize=1)


def ensure_build():
    """The renderer track's build (make BUILD=build/rtrack/), against the
    GAME sources in RENDER_GAMESRC if set (a snapshot while they change)."""
    if os.environ.get("RENDER_NO_MAKE"):
        return
    cmd = ["make", "-s", f"BUILD={BUILD}/"]
    if os.environ.get("RENDER_GAMESRC"):
        cmd.append(f"GAMESRC={os.environ['RENDER_GAMESRC']}")
    subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def setUpModule():
    ensure_build()


def tearDownModule():
    cyc = MEASURE.get("cycles")
    if cyc and ("-v" in sys.argv or os.environ.get("RENDER_MEASURE")):
        vals = sorted(cyc.values())
        n = len(vals)
        print(f"\nrender_frame cycles over {n} views: mean {sum(vals) / n:,.0f}  "
              f"p50 {vals[n // 2]:,}  p90 {vals[int(n * 0.9)]:,}  max {vals[-1]:,}")
        for k in sorted(cyc, key=cyc.get, reverse=True)[:8]:
            print(f"  {cyc[k]:>12,}  {k}")
    out = os.environ.get("RENDER_CYCLES_JSON")
    if cyc and out:
        Path(out).write_text(json.dumps(cyc, indent=1))


# --- the arithmetic routines on their own --------------------------------------------------

class Arithmetic(unittest.TestCase):
    """The renderer's arithmetic against the reference's, case by case (the
    views reach most paths; these reach the rare ones: signs, quadrants,
    24-bit divisors, zero)."""

    @classmethod
    def setUpClass(cls):
        cls.sim = RenderSim()
        cls.sim.dbg.call("mul_init")
        cls.rnd = random.Random(7)

    def put(self, label, value, n):
        a = self.sim.L[label]
        self.sim.m.main[a:a + n] = (value & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    def get(self, label, n, signed=False):
        a = self.sim.L[label]
        v = int.from_bytes(bytes(self.sim.m.main[a:a + n]), "little")
        return v - (1 << (8 * n)) if signed and v >> (8 * n - 1) else v

    def test_sin_bam(self):
        t = R.tables()
        angles = list(range(0, 65536, 97)) + [0, 15, 16, 0x3FFF, 0x4000, 0x7FF1, 0x8000,
                                              0xBFFF, 0xC000, 0xFFFF]
        for a in angles:
            self.put("s_ang", a, 2)
            self.sim.dbg.call("sin_bam")
            self.assertEqual(self.get("s_val", 2, True), t.sin_bam(a), hex(a))

    def test_point_to_angle(self):
        r = R.Renderer(game_data("E1M1"))
        r.stats = R.Stats()
        vals = [0, 1, -1, 255, 256, -256, 65535, 65536, -65536, 1 << 20, -(1 << 20)]
        cases = [(x, y) for x in vals for y in vals]
        for _ in range(600):
            e = self.rnd.choice([8, 16, 21])
            cases.append((self.rnd.randint(-(1 << e), 1 << e), self.rnd.randint(-(1 << e), 1 << e)))
        for x, y in cases:
            self.put("pa_x", x, 3)
            self.put("pa_y", y, 3)
            self.sim.dbg.call("point_to_angle")
            self.assertEqual(self.get("pa_r", 2), r.point_to_angle(x, y), (x, y))

    def test_divisions(self):
        n = 0
        while n < 600:
            num = self.rnd.randint(1, (1 << 21) - 1)
            den = self.rnd.choice([self.rnd.randint(1, 255), self.rnd.randint(1, 65535),
                                   self.rnd.randint(1, (1 << 23) - 1)])
            q = (num << 6) // den
            if q >= 1 << 22:
                continue
            n += 1
            self.put("d_n", num, 3)
            self.put("d_d", den, 3)
            self.sim.dbg.call("div_scale")
            self.assertEqual(self.get("d_n", 3), q, (num, den))
        for _ in range(400):
            v = self.rnd.randint(-(1 << 22), 1 << 22)
            d = self.rnd.randint(1, 159)
            self.put("d_n", v, 3)
            self.sim.dbg.call("div_step", a=d)
            self.assertEqual(self.get("d_n", 3, True), R.div_trunc(v, d), (v, d))


# --- forced limits ------------------------------------------------------------------------

# name: (routine label, instruction bytes with None for "any", offsets of the
# limit's bytes in them (low byte, high byte or None))
LIMIT_SITES = {
    "MAXVISPLANES": [("new_plane", [0xE0, R.MAXVISPLANES], (1, None))],
    "MAXDRAWSEGS": [("store_wall_range", [0xC9, R.MAXDRAWSEGS], (1, None))],
    "MAXBSPDEPTH": [("bsp_walk", [0xC9, R.MAXBSPDEPTH], (1, None))],
    "MAXOPENINGS": [("store_wall_range", [0xA9, R.MAXOPENINGS & 255, 0xC5, None, 0xA9,
                                          R.MAXOPENINGS >> 8, 0xE5, None], (1, 5)),
                    ("ds_prepare", [0xA9, R.MAXOPENINGS & 255, 0xC5, None, 0xA9,
                                    R.MAXOPENINGS >> 8, 0xE5, None], (1, 5))],
}


def find_code(sim, label, pattern, window=6000):
    """The address of the first match of pattern (None: any byte) in main
    memory from label on."""
    mem = sim.m.main
    a0 = sim.L[label]
    for a in range(a0, a0 + window):
        if all(p is None or mem[a + i] == p for i, p in enumerate(pattern)):
            return a
    raise LookupError(f"{pattern} not found after {label}")


def set_limit(sim, name, value):
    """Patch a per-frame limit of the loaded program (its immediates)."""
    for label, pattern, (lo, hi) in LIMIT_SITES[name]:
        a = find_code(sim, label, pattern)
        sim.m.main[a + lo] = value & 255
        if hi is not None:
            sim.m.main[a + hi] = value >> 8


class Limits(unittest.TestCase):
    """Every limit forced low (the program patched, the reference's constant
    set alike): the degraded view is still the reference's."""

    VIEW = ("E1M1", "start")
    LIMITS = {"MAXVISPLANES": 20, "MAXDRAWSEGS": 40, "MAXOPENINGS": 200,
              "MAXBSPDEPTH": 8}

    def test_limits(self):
        mapname = self.VIEW[0]
        view = R.player_start(game_data(mapname))
        bad = []
        for name, value in self.LIMITS.items():
            sim = RenderSim()
            set_limit(sim, name, value)
            saved = getattr(R, name)
            setattr(R, name, value)
            try:
                want, st = reference(mapname, view)
            finally:
                setattr(R, name, saved)
            self.assertTrue(any(k.endswith("overflow") for k in st), f"{name}: no overflow")
            sim.set_view(mapname, view)
            got, cycles = sim.render()
            MEASURE.setdefault("cycles", {})[f"limits: {name} = {value}"] = cycles
            dd = diff(got, want)
            if dd:
                bad.append(f"{name} = {value}: {len(dd)} pixels differ, first {dd[:5]}")
        self.assertEqual(bad, [], "\n".join(bad))


class RenderCore(unittest.TestCase):
    """Every view of a set: the 6502 view buffer equals the reference's."""

    def check(self, setname):
        views = view_sets()[setname]
        res = run_views(views)
        cyc = MEASURE.setdefault("cycles", {})
        bad = []
        for name, ndiff, cycles, first in res:
            cyc[f"{setname}: {name}"] = cycles
            if ndiff:
                bad.append(f"{name}: {ndiff} pixels differ, first {first}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_deliverables(self):
        self.check("deliverables")

    def test_golden(self):
        self.check("golden")

    def test_shaded(self):
        self.check("shaded")

    def test_random(self):
        self.check("random")

    def test_animation(self):
        self.assertGreater(len(view_sets()["anim"]), 0, "no view shows an animation")
        self.check("anim")

    def test_fixed_colormap_extralight(self):
        self.check("fixed")


# --- the profile ------------------------------------------------------------------------

# the phases of a frame: the innermost of these on the call stack gets the cycles
PHASES = [
    ("pixels: wall/sky columns", "q_flush"),
    ("pixels: spans", "span_draw"),
    ("planes: span setup", "map_plane"),
    ("planes: visplanes, make_spans", "draw_planes"),
    ("walls: columns (seg loop)", "seg_loop"),
    ("walls: range setup", "store_wall_range"),
    ("segs: add_line, clipping", "add_line"),
    ("bsp: subsectors", "subsector"),
    ("bsp: bbox checks", "check_bbox"),
    ("bsp: walk", "bsp_walk"),
    ("frame: setup", "frame_setup"),
    ("frame: packet, map", "read_packet"),
    ("frame: packet, map", "map_load"),
]


def profile(views, top=40, sim=None, setup=None, phases=None):
    """Cycles by routine (self) and by phase (inclusive) over the views
    (setup(sim, view) loads one: tests/test_render_masked.py's scenes)."""
    sim = sim or RenderSim()
    m, mpu, L = sim.m, sim.m.mpu, sim.L
    # the language card's $D000 banks share addresses: the labels of each,
    # from the debug file's segments (KLC2/RLC2 bank 2, the others bank 1)
    lc2 = set()
    dbg = Path(sim.dbg.d.build if hasattr(sim.dbg.d, "build") else BUILD) / "doom.dbg"
    if not dbg.exists():
        dbg = BUILD / "doom.dbg"
    segs = {}
    for line in dbg.read_text().splitlines():
        f = dict(kv.split("=", 1) for kv in line.split("\t", 1)[-1].split(",") if "=" in kv)
        if line.startswith("seg\t"):
            segs[f["id"]] = f["name"].strip('"')
        elif line.startswith("sym\t") and f.get("type") == "lab" and "seg" in f:
            if segs.get(f["seg"]) in ("KLC2", "RLC2"):
                lc2.add(f["name"].strip('"'))
    names1 = sorted((a, n) for n, a in L.items()
                    if not n.startswith("__") and not n.startswith("@") and a >= 0x0200
                    and n not in lc2)
    names2 = sorted((a, n) for n, a in L.items()
                    if not n.startswith("__") and not n.startswith("@") and a >= 0x0200
                    and (n in lc2 or not 0xD000 <= a < 0xE000))
    addrs1 = [a for a, _ in names1]
    addrs2 = [a for a, _ in names2]
    names, addrs = names1, addrs1
    phase_by_name = {r: p for p, r in (phases or PHASES) if r in L}
    selfc, phasec, incl, phase_rt = {}, {}, {}, {}
    total = 0
    for item in views:
        if setup:
            setup(sim, item)
        else:
            name, mapname, view, tic, ex, fx, sh = item
            sim.set_view(mapname, view, tic, ex, fx, sh)
        driver = doomdbg.DRIVER
        code = bytes((0x20,)) + L["render_frame"].to_bytes(2, "little") + bytes((0xEA,))
        m.main[driver:driver + len(code)] = code
        pc0, sp0, p0 = mpu.pc, mpu.sp, mpu.p
        mpu.pc, mpu.sp = driver, (sp0 - 8) & 0xFF
        mpu.p |= mpu.INTERRUPT
        stack = []          # (return sp, phase or None, callee)
        cache = {}
        while mpu.pc != driver + 3:
            pc = mpu.pc
            c0 = mpu.processorCycles
            op = m[pc] if pc >= 0xC000 else (m.aux if m.sw["ramrd"] and 0x200 <= pc < 0xC000
                                              else m.main)[pc]
            m.step()
            dc = mpu.processorCycles - c0
            total += dc
            b2 = 0xD000 <= pc < 0xE000 and m.lc_bank2
            names, addrs = (names2, addrs2) if b2 else (names1, addrs1)
            r = cache.get((pc, b2))
            if r is None:
                i = bisect.bisect_right(addrs, pc) - 1
                r = cache[(pc, b2)] = names[i][1] if i >= 0 else "?"
            selfc[r] = selfc.get(r, 0) + dc
            ph = next((p for _, p, _ in reversed(stack) if p), "frame: render_frame")
            phasec[ph] = phasec.get(ph, 0) + dc
            pr = phase_rt.setdefault(ph, {})
            pr[r] = pr.get(r, 0) + dc
            for callee in {e[2] for e in stack}:
                incl[callee] = incl.get(callee, 0) + dc
            if op == 0x20:                          # JSR: the callee's phase, if one
                b2 = 0xD000 <= mpu.pc < 0xE000 and m.lc_bank2
                names, addrs = (names2, addrs2) if b2 else (names1, addrs1)
                i = bisect.bisect_right(addrs, mpu.pc) - 1
                callee = names[i][1] if i >= 0 else "?"
                stack.append((mpu.sp, phase_by_name.get(callee), callee))
            elif op == 0x60 and stack and mpu.sp > stack[-1][0]:
                stack.pop()
            elif stack and op == 0x4C:              # a phase entered by a jump
                b2 = 0xD000 <= mpu.pc < 0xE000 and m.lc_bank2
                names, addrs = (names2, addrs2) if b2 else (names1, addrs1)
                i = bisect.bisect_right(addrs, mpu.pc) - 1
                if i >= 0 and names[i][0] == mpu.pc and names[i][1] in phase_by_name:
                    stack[-1] = (stack[-1][0], phase_by_name[names[i][1]], stack[-1][2])
            while stack and mpu.sp > stack[-1][0] + 2:      # left by a jump
                stack.pop()
        mpu.pc, mpu.sp, mpu.p = pc0, sp0, p0
    n = len(views)
    print(f"{n} views, {total / n:,.0f} cycles per view")
    print("by phase (inclusive, per view):")
    for k, v in sorted(phasec.items(), key=lambda kv: -kv[1]):
        print(f"  {v / n:>12,.0f}  {100 * v / total:5.1f}%  {k}")
    for ph, v in sorted(phasec.items(), key=lambda kv: -kv[1])[:int(os.environ.get("PROFILE_PHASES", "6"))]:
        print(f"  {ph}: " + ", ".join(f"{k} {c / n:,.0f}" for k, c in
                                      sorted(phase_rt[ph].items(), key=lambda kv: -kv[1])[:int(os.environ.get("PROFILE_TOP", "10"))]))
    print("by routine (self, per view):")
    for k, v in sorted(selfc.items(), key=lambda kv: -kv[1])[:top]:
        print(f"  {v / n:>12,.0f}  {100 * v / total:5.1f}%  {k}")
    print("by routine (inclusive, per view):")
    for k, v in sorted(incl.items(), key=lambda kv: -kv[1])[:top]:
        print(f"  {v / n:>12,.0f}  {100 * v / total:5.1f}%  {k}")
    return phasec, selfc, total


def main_view(args):
    sim = RenderSim()
    d = game_data(args.map)
    view = R.View.from_units(*args.view) if args.view else R.player_start(d)
    sim.set_view(args.map, view, args.tic, args.extralight, None, args.shaded)
    got, cycles = sim.render()
    want, st = reference(args.map, view, args.tic, args.extralight, None, args.shaded)
    dd = diff(got, want)
    print(f"{args.map} {view!r}: {cycles} cycles, {len(dd)} pixels differ")
    for x, y, g, w in dd[:20]:
        print(f"  x={x} y={y} got {g} want {w}")
    out = Path(os.environ.get("RENDER_OUT", "/tmp"))
    save_png(args.map, got, out / "got.png")
    save_png(args.map, want, out / "want.png")
    return 0 if not dd else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", nargs="*", type=float)
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--tic", type=int, default=0)
    ap.add_argument("--extralight", type=int, default=0)
    ap.add_argument("--shaded", action="store_true")
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--views", type=int, default=12, help="with --profile: views of each set")
    ap.add_argument("--sets", default="deliverables,random", help="with --profile")
    a, rest = ap.parse_known_args()
    if a.profile:
        vs = view_sets()
        views = [v for k in a.sets.split(",") for v in vs[k][:a.views]]
        profile(views)
        sys.exit(0)
    if a.view is not None:
        sys.exit(main_view(a))
    unittest.main(argv=[sys.argv[0]] + rest)
