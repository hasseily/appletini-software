#!/usr/bin/env python3
"""The 6502 renderer's masked phase against the reference (docs/DESIGN.md 7.2).

The linked program (the renderer track's build) runs in the py65 test
machine through tools/doomdbg.py, as in tests/test_render_core.py, but the
render packet now carries things and weapon layers: the view buffer must
equal tools/refrender.py's full Renderer.render (sprites, two-sided middle
textures, the weapon), byte for byte. The things are the map's, as
refrender.spawn_things places them, the RV_MAXTHINGS nearest to the eye in
the packet, nearest first (what the game sends); the reference gets the same
list. Covered:

  - the 36 deliverable views and 40 random views with things and the pistol
  - synthetic things: sprites straddling walls and behind two-sided middles
    (grates), at the screen edges, very close and very far, all eight
    rotations and flipped frames, full bright, the spectre (fuzz), a
    sprite with more things than MAXVISSPRITES in view
  - the weapon at several sx/sy, its flash (full bright) on a second layer,
    extralight and the fixed colormap
  - MAXVISSPRITES and MAXBSPDEPTH forced low (the eye's sector for the
    weapon's light then comes from R_PointInSubsector)

and the cycles of render_frame for every view (-v: mean, p90, max).

    python3 tests/test_render_masked.py [-v]
    python3 tests/test_render_masked.py --view E1M1 X Y Z ANGLE [--tic N] [--no-things]
                                        [--no-weapon]   one view: diff, cycles, PNGs
    python3 tests/test_render_masked.py --measure        the cycle table for DESIGN.md
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))

import refrender as R  # noqa: E402
import test_render_core as C  # noqa: E402

RV_MAXTHINGS = 128
RV_THINGS = 40
RT_SIZE = 20
MEASURE = {}


# --- the packet ---------------------------------------------------------------------------

def packet_things(view: R.View, things, n=RV_MAXTHINGS):
    """The n things nearest to the eye, nearest first (the game's choice)."""
    return sorted(things, key=lambda t: (t.x - view.x) ** 2 + (t.y - view.y) ** 2)[:n]


def rthing(t: R.Thing) -> bytes:
    b = bytearray(RT_SIZE)
    for off, v in ((0, t.x), (4, t.y), (8, t.z)):
        b[off:off + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")
    b[12:14] = (t.angle & 0xFFFF).to_bytes(2, "little")
    b[14] = t.sprite
    b[15] = (t.frame & 0x7F) | (0x80 if t.frame & R.FF_FULLBRIGHT else 0)
    b[16] = 1 if t.flags & R.MF_SHADOW else 0
    b[18:20] = t.sector.to_bytes(2, "little")
    return bytes(b)


def rpsprite(p: R.PSprite | None) -> bytes:
    b = bytearray(10)
    if p is None:
        b[0] = 0xFF
        return bytes(b)
    b[0] = p.sprite
    b[1] = (p.frame & 0x7F) | (0x80 if p.frame & R.FF_FULLBRIGHT else 0)
    b[2:6] = (p.sx & 0xFFFFFFFF).to_bytes(4, "little")
    b[6:10] = (p.sy & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(b)


class MaskedSim(C.RenderSim):
    def set_scene(self, mapname, view, things=(), psprites=(), tic=0, extralight=0,
                  fixedcolormap=None, shaded=False):
        self.set_view(mapname, view, tic, extralight, fixedcolormap, shaded)
        rv = self.packet_address
        mem = self.m.bank_memory(self.packet_bank)
        mem[rv + 18] = len(things)
        mem[rv + 19] = len(psprites)
        for i, p in enumerate(list(psprites)[:2]):
            mem[rv + 20 + 10 * i:rv + 30 + 10 * i] = rpsprite(p)
        for i, t in enumerate(things):
            a = rv + RV_THINGS + RT_SIZE * i
            mem[a:a + RT_SIZE] = rthing(t)


def reference(mapname, view, things=(), psprites=(), tic=0, extralight=0, fixedcolormap=None,
              shaded=False):
    r = R.Renderer(C.game_data(mapname), shaded=shaded)
    buf, st = r.render(view, list(things), [p for p in psprites if p is not None], tic=tic,
                       extralight=extralight, fixedcolormap=fixedcolormap)
    return bytes(buf), st


# --- scenes ---------------------------------------------------------------------------------

_things = {}


def map_things(mapname, tic=0):
    key = (mapname, tic)
    if key not in _things:
        _things[key] = R.spawn_things(C.game_data(mapname), tic=tic)
    return _things[key]


def pistol(d, frame=0, sx=1 << 16, sy=R.WEAPONTOP):
    return R.PSprite(d.sprite_index["PISG"], frame, sx, sy)


def flash(d, frame=0, sx=1 << 16, sy=R.WEAPONTOP):
    return R.PSprite(d.sprite_index["PISF"], frame | R.FF_FULLBRIGHT, sx, sy)


class Scene:
    """A view with its things and weapon layers."""

    def __init__(self, name, mapname, view, things=(), psprites=(), tic=0, extralight=0,
                 fixed=None, shaded=False):
        self.name, self.mapname, self.view = name, mapname, view
        self.things = list(things)
        self.psprites = list(psprites)
        self.tic, self.extralight, self.fixed, self.shaded = tic, extralight, fixed, shaded

    def job(self):
        return self


def map_scenes(setname, n=None):
    """The core test's views with the map's things (packet order) and the pistol."""
    out = []
    for name, mapname, view, tic, ex, fx, sh in C.view_sets()[setname][:n]:
        d = C.game_data(mapname)
        th = packet_things(view, map_things(mapname, tic))
        out.append(Scene(f"{setname}: {name}", mapname, view, th, [pistol(d)], tic, ex, fx, sh))
    return out


def thing_at(d, x, y, z=None, angle=0, sprite="POSS", frame=0, flags=0, above=0):
    """A thing at map (x, y) (units), on the floor (+ above) unless z given."""
    r = R.Renderer(d)
    x16, y16 = round(x * 16), round(y * 16)
    sector = r.point_sector(x16, y16)
    if z is None:
        z = d.sectors[sector].floorheight + above
    t = R.Thing(x16, y16, round(z * 16), round(angle * 65536 / 360) & 0xFFFF,
                d.sprite_index[sprite], frame, flags)
    t.sector = sector
    return t


def masked_lines(d):
    """Two-sided lines with a middle texture (grates, fences)."""
    return [l for l in d.lines if l.side1 != R.NONE16 and d.sides[l.side0].midtexture]


def synthetic_scenes():
    """Hand-made scenes for the cases the maps' things may not reach."""
    out = []
    d = C.game_data("E1M1")
    start = R.player_start(d)
    ex, ey = start.x / 16, start.y / 16
    a = start.angle * 2 * math.pi / 65536
    fx, fy = math.cos(a), math.sin(a)
    rx, ry = math.sin(a), -math.cos(a)
    pis = [pistol(d)]

    def ahead(dist, side=0.0):
        return ex + fx * dist + rx * side, ey + fy * dist + ry * side

    # rotations 1..8 (a thing seen from 8 directions) and the flipped frames
    for k in range(8):
        x, y = ahead(96, -60 + 17 * k)
        ang = (start.angle * 360 / 65536 + 180 + 45 * k) % 360
        th = [thing_at(d, x, y, angle=ang, sprite="TROO", frame=0)]
        out.append(Scene(f"rotation {k}", "E1M1", start, th, pis))
    # very close (just past MINZ, and inside it), very far, the screen edges
    for dist in (4.2, 5, 8, 16, 3.9):
        x, y = ahead(dist)
        out.append(Scene(f"close {dist}", "E1M1", start,
                         [thing_at(d, x, y, sprite="SARG", angle=90)], []))
    for dist, side in ((64, 70), (64, -70), (40, 45), (40, -45), (200, 210), (200, -212)):
        x, y = ahead(dist, side)
        out.append(Scene(f"edge {dist} {side}", "E1M1", start,
                         [thing_at(d, x, y, sprite="POSS", angle=30)], []))
    # far along the start's corridor, and floating above / below the eye
    for dist in (400, 800, 1500):
        x, y = ahead(dist)
        out.append(Scene(f"far {dist}", "E1M1", start,
                         [thing_at(d, x, y, z=d.sectors[0].floorheight, sprite="BAR1")], pis))
    for above in (-80, 30, 100, 400):
        x, y = ahead(60)
        out.append(Scene(f"z {above}", "E1M1", start,
                         [thing_at(d, x, y, sprite="SKUL", frame=R.FF_FULLBRIGHT, above=above)],
                         []))
    # the spectre (fuzz), alone and in front of a lit thing
    x, y = ahead(70)
    x2, y2 = ahead(120, 10)
    out.append(Scene("spectre", "E1M1", start,
                     [thing_at(d, x, y, sprite="SARG", flags=R.MF_SHADOW, angle=200),
                      thing_at(d, x2, y2, sprite="BAR1")], pis))
    x, y = ahead(20)
    out.append(Scene("spectre close", "E1M1", start,
                     [thing_at(d, x, y, sprite="SARG", flags=R.MF_SHADOW, angle=10)], pis))
    # sprites straddling walls and behind masked middles, from views around
    # two-sided middle textures of several maps
    for mapname in ("E1M1", "E1M2", "E1M3", "E1M5", "E1M7"):
        dm = C.game_data(mapname)
        ml = masked_lines(dm)
        rnd = random.Random(mapname)
        rnd.shuffle(ml)
        for l in ml[:3]:
            v1, v2 = dm.vertexes[l.v1], dm.vertexes[l.v2]
            mx, my = (v1.x + v2.x) / 2, (v1.y + v2.y) / 2
            L = math.hypot(l.dx, l.dy) or 1
            nx, ny = l.dy / L, -l.dx / L
            for side in (1, -1):
                vx, vy = mx + nx * 90 * side, my + ny * 90 * side
                r = R.Renderer(dm)
                if not R._inside(r, dm, vx, vy):
                    continue
                view = R.view_at(dm, vx, vy, math.degrees(math.atan2(-ny * side, -nx * side)))
                things = []
                for k, (dd, off) in enumerate(((-40, 0), (-40, 24), (-8, -30), (-60, 40),
                                                (0, 12))):
                    tx = mx + nx * dd * side + l.dx / L * off
                    ty = my + ny * dd * side + l.dy / L * off
                    if not R._inside(r, dm, tx, ty):
                        continue
                    things.append(thing_at(dm, tx, ty, sprite=("POSS", "TROO", "BAR1",
                                                               "SARG", "COLU")[k],
                                           angle=45 * k,
                                           flags=R.MF_SHADOW if k == 3 else 0))
                out.append(Scene(f"masked {mapname} line {dm.lines.index(l)} {side}", mapname,
                                 view, things, pis))
    # the weapon at several positions, with its flash, extralight, fixed colormap
    for sx, sy in ((1 << 16, R.WEAPONTOP), (-20 << 16, R.WEAPONTOP), (30 << 16, 60 << 16),
                   (310 << 16, 40 << 16), (160 << 16, 120 << 16), (1 << 16, 128 << 16),
                   (400 << 16, R.WEAPONTOP), (-200 << 16, R.WEAPONTOP),
                   ((7 << 16) + 12345, (33 << 16) + 54321)):
        out.append(Scene(f"weapon {sx / 65536:.2f} {sy / 65536:.2f}", "E1M1", start, [],
                         [pistol(d, 1, sx, sy)]))
    for fr in range(2):
        out.append(Scene(f"flash {fr}", "E1M1", start, [],
                         [pistol(d, 2 + fr), flash(d, fr)], extralight=2))
    out.append(Scene("weapon fixed", "E1M1", start, [], [pistol(d, 0), flash(d, 0)], fixed=0))
    out.append(Scene("weapon shotgun", "E1M1", start, [],
                     [R.PSprite(d.sprite_index["SHTG"], 0)]))
    # a crowd: more things in view than MAXVISSPRITES
    crowd = []
    for i in range(120):
        x, y = ahead(40 + 6 * (i % 12), -40 + 8 * (i // 12))
        if R._inside(R.Renderer(d), d, x, y):
            crowd.append(thing_at(d, x, y, sprite=("CLIP", "BON1", "STIM")[i % 3]))
    out.append(Scene("crowd", "E1M1", start, crowd[:RV_MAXTHINGS], pis))
    return out


# --- running ----------------------------------------------------------------------------------

_sim = None


def _run(scene: Scene):
    global _sim
    if _sim is None:
        _sim = MaskedSim()
    _sim.set_scene(scene.mapname, scene.view, scene.things, scene.psprites, scene.tic,
                   scene.extralight, scene.fixed, scene.shaded)
    got, cycles = _sim.render()
    want, st = reference(scene.mapname, scene.view, scene.things, scene.psprites, scene.tic,
                         scene.extralight, scene.fixed, scene.shaded)
    dd = C.diff(got, want)
    return scene.name, len(dd), cycles, dd[:5], st.get("vissprites", 0)


def run_scenes(scenes, workers=None):
    workers = workers or int(os.environ.get("RENDER_WORKERS", "3"))
    if workers <= 1:
        return [_run(s) for s in scenes]
    import multiprocessing as mp
    with mp.get_context("fork").Pool(workers) as pool:
        return pool.map(_run, scenes, chunksize=1)


def setUpModule():
    C.ensure_build()


def tearDownModule():
    cyc = MEASURE.get("cycles")
    if cyc and ("-v" in sys.argv or os.environ.get("RENDER_MEASURE")):
        report(cyc)


def report(cyc):
    groups = {}
    for k, v in cyc.items():
        groups.setdefault(k.split(":")[0], []).append(v)
    for g, vals in sorted(groups.items()):
        vals.sort()
        n = len(vals)
        print(f"{g:<14} n={n:3d}  mean {sum(vals) / n:>11,.0f}  p90 {vals[int(n * 0.9)]:>11,}  "
              f"max {vals[-1]:>11,}")


class Masked(unittest.TestCase):
    def check(self, scenes):
        res = run_scenes(scenes)
        cyc = MEASURE.setdefault("cycles", {})
        bad = []
        for name, ndiff, cycles, first, nvis in res:
            cyc[name] = cycles
            if ndiff:
                bad.append(f"{name}: {ndiff} pixels differ, first {first}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_deliverables(self):
        self.check(map_scenes("deliverables"))

    def test_random(self):
        self.check(map_scenes("random"))

    def test_synthetic(self):
        self.check(synthetic_scenes())

    def test_fixed_shaded(self):
        # things under the fixed colormap and extralight, and in flat-shaded mode
        self.check(map_scenes("fixed") + map_scenes("shaded"))

    def test_anim_things(self):
        # animated things (their frames at other tics) and the textures' animation
        scenes = []
        for name, mapname, view, tic, ex, fx, sh in C.view_sets()["anim"][:5]:
            d = C.game_data(mapname)
            th = packet_things(view, map_things(mapname, tic))
            scenes.append(Scene(f"anim: {name}", mapname, view, th, [pistol(d)], tic, ex, fx))
        self.check(scenes)


class Limits(unittest.TestCase):
    """MAXVISSPRITES and MAXBSPDEPTH forced low in both the program (its
    immediate operands patched in memory) and the reference: the degraded
    views are the same."""

    def run_limit(self, name, value, scene, patch):
        sim = MaskedSim()
        patch(sim)
        saved = getattr(R, name)
        setattr(R, name, value)
        try:
            want, st = reference(scene.mapname, scene.view, scene.things, scene.psprites)
        finally:
            setattr(R, name, saved)
        sim.set_scene(scene.mapname, scene.view, scene.things, scene.psprites)
        got, cycles = sim.render()
        MEASURE.setdefault("cycles", {})[f"limits: {name} = {value}"] = cycles
        return C.diff(got, want), st

    def test_maxvissprites(self):
        scene = [s for s in synthetic_scenes() if s.name == "crowd"][0]
        for value in (1, 20):
            dd, st = self.run_limit(
                "MAXVISSPRITES", value, scene,
                lambda sim: patch_lc1(sim, "project", [0xE0, R.MAXVISSPRITES], 1, value))
            self.assertIn("vissprite_overflow", st)
            self.assertEqual(dd, [], f"{value}: {len(dd)} differ, {dd[:5]}")

    def test_maxbspdepth(self):
        # the weapon's light from R_PointInSubsector when the walk overflows
        # before it reaches the eye's subsector
        d = C.game_data("E1M1")
        view = R.player_start(d)
        scene = Scene("bspdepth", "E1M1", view, packet_things(view, map_things("E1M1")),
                      [pistol(d)])
        for depth in (2, 8):
            dd, st = self.run_limit("MAXBSPDEPTH", depth, scene,
                                    lambda sim: C.set_limit(sim, "MAXBSPDEPTH", depth))
            self.assertIn("bsp_overflow", st)
            self.assertEqual(dd, [], f"depth {depth}: {len(dd)} differ, {dd[:5]}")

    def test_maxdrawsegs_openings(self):
        # the sprite clipper and the masked middles with drawsegs and openings short
        d = C.game_data("E1M1")
        view = R.player_start(d)
        scene = Scene("limits", "E1M1", view, packet_things(view, map_things("E1M1")),
                      [pistol(d)])
        used = reference(scene.mapname, scene.view, scene.things, scene.psprites)[1]["openings"]
        for name, value in (("MAXDRAWSEGS", 40), ("MAXOPENINGS", used // 4),
                            ("MAXOPENINGS", used * 3 // 4)):
            dd, st = self.run_limit(name, value, scene,
                                    lambda sim: C.set_limit(sim, name, value))
            self.assertTrue(any(k.endswith("overflow") for k in st), name)
            self.assertEqual(dd, [], f"{name} = {value}: {len(dd)} differ, {dd[:5]}")


def patch_lc1(sim, label, pattern, offset, value, window=4000):
    """Patch an immediate operand in code that lives in LC bank 1 ($D000)."""
    mem = sim.m.lc_bank1[False]
    a0 = sim.L[label]
    assert 0xD000 <= a0 < 0xE000, hex(a0)
    for a in range(a0 - 0xD000, min(a0 - 0xD000 + window, 0x1000 - len(pattern))):
        if all(p is None or mem[a + k] == p for k, p in enumerate(pattern)):
            mem[a + offset] = value
            return
    raise LookupError(f"{pattern} not found after {label}")


# --- the profile ------------------------------------------------------------------------------

PHASES = [
    ("masked: sprite pixels (session)", "dv_cols"),
    ("masked: sprite tables", "build_rows"),
    ("masked: sprite tables", "build_yf"),
    ("masked: sprite setup", "draw_vis"),
    ("masked: middles, pixels", "ms_draw"),
    ("masked: middles, columns", "msr_range"),
    ("masked: middles, setup", "msr_setup"),
    ("masked: clipping", "draw_sprite"),
    ("masked: the rest", "r_masked"),
    ("masked: weapon", "draw_psprites"),
    ("things: projection", "project"),
    ("things: hash, replay", "r_things"),
] + C.PHASES


def profile(scenes, top=40):
    def setup(sim, sc):
        sim.set_scene(sc.mapname, sc.view, sc.things, sc.psprites, sc.tic, sc.extralight,
                      sc.fixed, sc.shaded)
    return C.profile(scenes, top, MaskedSim(), setup, PHASES)


# --- command line -----------------------------------------------------------------------------

def main_view(args):
    sim = MaskedSim()
    d = C.game_data(args.map)
    view = R.View.from_units(*args.view) if args.view else R.player_start(d)
    th = [] if args.no_things else packet_things(view, map_things(args.map, args.tic))
    psp = [] if args.no_weapon else [pistol(d)]
    sim.set_scene(args.map, view, th, psp, args.tic, args.extralight)
    got, cycles = sim.render()
    want, st = reference(args.map, view, th, psp, args.tic, args.extralight)
    dd = C.diff(got, want)
    print(f"{args.map} {view!r}: {cycles:,} cycles, {len(dd)} pixels differ, "
          f"{st.get('vissprites', 0)} vissprites")
    for x, y, g, w in dd[:20]:
        print(f"  x={x} y={y} got {g} want {w}")
    out = Path(os.environ.get("RENDER_OUT", "/tmp"))
    C.save_png(args.map, got, out / "got.png")
    C.save_png(args.map, want, out / "want.png")
    return 0 if not dd else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", nargs="*", type=float)
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--tic", type=int, default=0)
    ap.add_argument("--extralight", type=int, default=0)
    ap.add_argument("--no-things", action="store_true")
    ap.add_argument("--no-weapon", action="store_true")
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--views", type=int, default=12, help="with --profile: scenes of each set")
    ap.add_argument("--sets", default="deliverables,random", help="with --profile")
    a, rest = ap.parse_known_args()
    if a.profile:
        profile([sc for k in a.sets.split(",") for sc in map_scenes(k, a.views)])
        sys.exit(0)
    if a.view is not None:
        sys.exit(main_view(a))
    unittest.main(argv=[sys.argv[0]] + rest)
