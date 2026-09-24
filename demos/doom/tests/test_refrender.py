#!/usr/bin/env python3
"""Check tools/refrender.py, the renderer's specification (docs/DESIGN.md 7).

Run:  python3 tests/test_refrender.py        (from the project directory)

The reference renderer is the contract the 6502 renderer is tested
against byte for byte, so these tests pin it and check it against things
it must satisfy:

  - determinism: the same view gives the same buffer, in a fresh renderer
    too, and the golden SHA-256 of a few view buffers is unchanged (a
    change here is a change of the specification: update the hashes on
    purpose, and the 6502 renderer with them);
  - the invariant of Doom's clipping: before the masked phase (sprites,
    two-sided middles, the weapon) every pixel of the view is written
    exactly once by walls, planes and the sky, for the start of every map
    and three more views per map, textured and flat-shaded;
  - limits: tiny MAXVISPLANES, MAXDRAWSEGS, MAXOPENINGS, MAXVISSPRITES and
    MAXBSPDEPTH overflow without an exception, and the write-once invariant
    still holds while only the planes/drawsegs/openings/sprites overflow;
  - geometry against an independent floating-point column raycaster
    written here from Doom's rules (walls, pegging, texture columns,
    planes, sky; no sprites): most pixels agree (they differ at edges and
    on texel boundaries, by rounding);
  - the tables: tools/gen_tables.py's output assembles with ca65 and its
    bytes are the reference's tables; the angle tables are consistent.

The data: build/data (tools/wad2a2.py's output), else converted into a
temporary directory from $FREEDOOM_WAD or build/wad/freedoom1.wad; without
either the tests are skipped.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import refrender as R  # noqa: E402
import gen_tables  # noqa: E402

WAD = Path(os.environ.get("FREEDOOM_WAD", PROJECT / "build/wad/freedoom1.wad"))
DATA = PROJECT / "build/data"
MAPS = [f"E1M{i}" for i in range(1, 10)]

# sha256 of the view buffer (160*84 bytes) of fixed views: map, eye (x, y, z
# in sub-units, BAM16 angle), tic, extralight, flat-shaded; things spawned
# at skill 4 (at that tic) and the pistol up
GOLDEN = [
    ("E1M1 start", "E1M1", (-6656, 4096, 656, 0), 0, 0, False,
     "e898d0ae5adf974cce85144e68c7769abbaf59d298f659cf27e11c343a237e28"),
    ("E1M1 start shaded", "E1M1", (-6656, 4096, 656, 0), 0, 0, True,
     "a802fbd114fe2fdca74669c9f49fb13ff21c90adce29ae11554bd7dc19afa5c5"),
    ("E1M1 odd", "E1M1", (-6405, 4012, 668, 0x1234), 5, 0, False,
     "ae2e8bdb45e4711bfa2fd1a2e0c487ff600ac2f7ee31a0553a86985a5780609e"),
    ("E1M2 corridor", "E1M2", (44528, 4608, 16, 0xC000), 0, 0, False,
     "d84f632e4dcf8f5646819ea70b5fd8c98c97c589af87e284c574d6f5ebdbdd83"),
    ("E1M5 steps", "E1M5", (25088, 13312, -112, 0x4000), 37, 1, False,
     "2614723ca2112d64fdcd629dbd791d6a1532c0bbd00ed931a07b419caea25c4c"),
    ("E1M7 door", "E1M7", (7168, 23040, 784, 0xC000), 0, 0, False,
     "1c957b25dbe60e2ed0519c77e5d625ba3331e922a570edd6083d41334a76dc85"),
]

_tmp = None
_cache = {}


def data_dir():
    global _tmp
    if (DATA / "manifest.json").exists():
        return DATA
    if not WAD.exists():
        return None
    if _tmp is None:
        _tmp = Path(tempfile.mkdtemp(prefix="refrender_"))
        import wad2a2
        wad2a2.main(["--wad", str(WAD), "--out", str(_tmp), "--no-preview"])
    return _tmp


def game_data(mapname):
    if mapname not in _cache:
        _cache[mapname] = R.GameData(data_dir(), mapname)
    return _cache[mapname]


def views_of(mapname):
    key = ("views", mapname)
    if key not in _cache:
        d = game_data(mapname)
        _cache[key] = [("start", R.player_start(d))] + R.pick_views(d)
    return _cache[key]


def golden_views():
    out = {}
    for name, mapname, eye, tic, extra, shaded, _ in GOLDEN:
        d = game_data(mapname)
        r = R.Renderer(d, shaded=shaded)
        buf, _ = r.render(R.View(*eye), R.spawn_things(d, tic=tic), [R.weapon(d)], tic=tic,
                          extralight=extra)
        out[name] = hashlib.sha256(buf).hexdigest()
    return out


# --- an independent floating-point raycaster ---------------------------------------------

def float_render(d, view):
    """Walls, planes and the sky of a view by casting one ray per column
    through every linedef, nearest first, with Doom's rules in floating
    point: the column's angle is the reference's xtoviewangle (Doom's
    column convention), a pixel row y spans heights from its top edge,
    walls cover rows ceil(top)..floor(bottom), planes sample the row centre.
    Returns the 160*84 buffer (0 where nothing was drawn)."""
    t = R.tables()
    vx, vy, vz, va = view.x / 16, view.y / 16, view.z / 16, view.angle
    V = d.vertexes
    buf = bytearray(R.VIEW_W * R.VIEW_H)
    sky = d.textures[d.sky]
    lines = [(l, V[l.v1].x, V[l.v1].y, V[l.v2].x, V[l.v2].y) for l in d.lines]

    def texel(tex, u, v):
        return d.banks[tex.bank][tex.addr + ((u & tex.wmask) << tex.log2h) + (v & tex.hmask)]

    def cmap(bank, k, c):
        return d.banks[bank][0x200 + 256 * k + c]

    for x in range(R.VIEW_W):
        xa = t.xtoviewangle[x]
        ang = ((va + xa) & 0xFFFF) * 2 * math.pi / 65536
        cxa = math.cos(xa * 2 * math.pi / 65536)
        dx, dy = math.cos(ang), math.sin(ang)
        hits = []
        for l, x1, y1, x2, y2 in lines:
            ex, ey = x2 - x1, y2 - y1
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            wx, wy = x1 - vx, y1 - vy
            tt = (wx * ey - wy * ex) / den
            uu = (wx * dy - wy * dx) / den
            if tt > 0.01 and 0 <= uu <= 1:
                front = (ex * (vy - y1) - ey * (vx - x1)) < 0      # viewer on the right
                hits.append((tt, l, uu, front))
        hits.sort(key=lambda h: h[0])
        wtop, wbot = 0, R.VIEW_H - 1

        def plane(y0, y1, s, ceiling):
            h = s.ceilingheight if ceiling else s.floorheight
            pic = s.ceilingpic if ceiling else s.floorpic
            for y in range(max(0, y0), min(R.VIEW_H - 1, y1) + 1):
                if pic == d.skyflat:
                    col = ((va + xa) & 0xFFFF) >> 7
                    buf[84 * x + y] = cmap(sky.bank, 0, texel(sky, col, y + 8))
                    continue
                dyr = y + 0.5 - R.CENTERY
                dist = abs(h - vz) * R.PROJ / abs(dyr)
                px, py = vx + dist / cxa * dx, vy + dist / cxa * dy
                fl = d.flats[pic]
                k = t.zlight[max(0, min(15, s.lightlevel >> 4))][min(int(dist / 16), 127)]
                c = d.banks[fl.bank][fl.addr + 32 * (math.floor(-py / 2) & 31)
                                     + (math.floor(px / 2) & 31)]
                buf[84 * x + y] = cmap(fl.bank, k, c)

        def wall(y0, y1, texnum, u, top, s, lightnum):
            if not texnum:
                return
            tex = d.textures[texnum]
            k = t.scalelight[max(0, min(15, lightnum))][min(int(s * 65536) >> 11, 47)]
            for y in range(y0, y1 + 1):
                v = top - (vz - (y - R.CENTERY) / s)
                buf[84 * x + y] = cmap(tex.bank, k, texel(tex, math.floor(u / 2),
                                                          math.floor(v / 2)))

        for tt, l, uu, front in hits:
            if wtop > wbot:
                break
            if l.side1 == R.NONE16 and not front:
                continue
            side = d.sides[l.side0 if front else l.side1]
            fs = d.sectors[side.sector]
            bs = None
            if l.side1 != R.NONE16:
                bs = d.sectors[l.backsector if front else l.frontsector]
            s = R.PROJ / (tt * cxa)
            L = math.hypot(l.dx, l.dy)
            u = (uu if front else 1 - uu) * L + side.xoffset
            fc, ff = fs.ceilingheight, fs.floorheight
            worldtop = fc
            if bs is not None and fs.ceilingpic == d.skyflat and bs.ceilingpic == d.skyflat:
                worldtop = bs.ceilingheight
            yl = max(math.ceil(R.CENTERY - (worldtop - vz) * s), wtop)
            yh = min(math.floor(R.CENTERY - (ff - vz) * s), wbot)
            lightnum = fs.lightlevel >> 4
            if V[l.v1].y == V[l.v2].y:
                lightnum -= 1
            elif V[l.v1].x == V[l.v2].x:
                lightnum += 1
            if fc > vz or fs.ceilingpic == d.skyflat:
                plane(wtop, min(yl - 1, wbot, yh), fs, True)
            if ff < vz:
                plane(max(yh + 1, wtop), wbot, fs, False)
            if bs is None:
                top = (ff + d.textures[side.midtexture].height
                       if l.flags & R.ML_DONTPEGBOTTOM else fc)
                wall(yl, yh, side.midtexture, u, top + side.yoffset, s, lightnum)
                break
            ntop, nbot = yl, yh
            if bs.ceilingheight < worldtop:
                mid = min(math.floor(R.CENTERY - (bs.ceilingheight - vz) * s), yh)
                top = (fc if l.flags & R.ML_DONTPEGTOP
                       else bs.ceilingheight + d.textures[side.toptexture].height)
                if mid >= yl:
                    wall(yl, mid, side.toptexture, u, top + side.yoffset, s, lightnum)
                    ntop = mid + 1
            if bs.floorheight > ff:
                mid = max(math.ceil(R.CENTERY - (bs.floorheight - vz) * s), ntop)
                top = fc if l.flags & R.ML_DONTPEGBOTTOM else bs.floorheight
                if mid <= yh:
                    wall(mid, yh, side.bottomtexture, u, top + side.yoffset, s, lightnum)
                    nbot = mid - 1
            if bs.ceilingheight <= ff or bs.floorheight >= fc:
                break
            wtop, wbot = ntop, nbot
    return buf


# --- the tests ------------------------------------------------------------------------------

@unittest.skipIf(data_dir() is None, "no converted data and no WAD")
class RefRender(unittest.TestCase):

    def test_determinism(self):
        d = game_data("E1M3")
        view = views_of("E1M3")[1][1]
        things = R.spawn_things(d)
        a, sa = R.Renderer(d).render(view, things, [R.weapon(d)])
        r = R.Renderer(d)
        b, sb = r.render(view, things, [R.weapon(d)])
        c, _ = r.render(view, things, [R.weapon(d)])      # the same renderer again
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(sa, sb)

    def test_golden(self):
        got = golden_views()
        for name, *_, want in GOLDEN:
            self.assertEqual(got[name], want, f"view buffer of {name!r} changed")

    def test_write_once(self):
        """Walls, planes and sky write every pixel exactly once, in all views."""
        for mapname in MAPS:
            d = game_data(mapname)
            for label, view in views_of(mapname):
                for shaded in (False, True):
                    r = R.Renderer(d, shaded=shaded, check_writes=True)
                    r.render(view, R.spawn_things(d), [R.weapon(d)])
                    w = r.plane_writes
                    bad = [(i // R.VIEW_H, i % R.VIEW_H) for i in range(len(w)) if w[i] != 1]
                    self.assertEqual(bad, [], f"{mapname} {label} shaded={shaded}: "
                                              f"pixels (x, y) not written once")

    def test_limits(self):
        """Tiny limits degrade the picture without an exception."""
        names = ["MAXVISPLANES", "MAXDRAWSEGS", "MAXOPENINGS", "MAXVISSPRITES", "MAXBSPDEPTH"]
        saved = {n: getattr(R, n) for n in names}
        try:
            R.MAXVISPLANES, R.MAXDRAWSEGS, R.MAXOPENINGS, R.MAXVISSPRITES = 3, 5, 40, 2
            for mapname in ("E1M1", "E1M7"):
                d = game_data(mapname)
                for label, view in views_of(mapname):
                    r = R.Renderer(d, check_writes=True)
                    buf, st = r.render(view, R.spawn_things(d), [R.weapon(d)])
                    self.assertEqual(len(buf), R.VIEW_W * R.VIEW_H)
                    self.assertTrue(all(v == 1 for v in r.plane_writes), f"{mapname} {label}")
                    self.assertLessEqual(st["visplanes"], 3)
                    self.assertLessEqual(st["drawsegs"], 5)
                    self.assertLessEqual(st["openings"], 40)
                    self.assertLessEqual(st["vissprites"], 2)
                    if label == "start":
                        self.assertGreater(st.get("visplane_overflow", 0), 0)
                        self.assertGreater(st.get("drawseg_overflow", 0), 0)
            R.MAXBSPDEPTH = 4
            d = game_data("E1M1")
            buf, st = R.Renderer(d).render(views_of("E1M1")[0][1])
            self.assertGreater(st.get("bsp_overflow", 0), 0)
        finally:
            for n, v in saved.items():
                setattr(R, n, v)

    def test_against_float_raycaster(self):
        """Walls, pegging, texture columns, planes and sky agree with an
        independent floating-point raycaster on most pixels."""
        worst = []
        for mapname in MAPS:
            d = game_data(mapname)
            for label, view in views_of(mapname)[:2]:
                buf, _ = R.Renderer(d, masked=False).render(view)
                ref = float_render(d, view)
                diff = sum(1 for a, b in zip(buf, ref) if a != b) / len(buf)
                worst.append((diff, mapname, label))
        worst.sort(reverse=True)
        mean = sum(w[0] for w in worst) / len(worst)
        self.assertLess(mean, 0.12, worst[:3])
        self.assertLess(worst[0][0], 0.20, worst[:3])

    def test_things(self):
        d = game_data("E1M1")
        things = R.spawn_things(d)
        self.assertGreater(len(things), 20)
        r = R.Renderer(d)
        for th in things:
            self.assertIsNotNone(r.sprite_lump(th.sprite, th.frame, 0),
                                 f"sprite {th.sprite} frame {th.frame}")
        start = R.player_start(d)
        sec = d.sectors[r.point_sector(start.x, start.y)]
        self.assertEqual(start.z, (sec.floorheight + R.VIEWHEIGHT) << R.SUBBITS)


class Tables(unittest.TestCase):

    def test_angles(self):
        t = R.tables()
        xa = [(a - 0x10000 if a >= 0x8000 else a) for a in t.xtoviewangle]
        self.assertTrue(all(xa[i] > xa[i + 1] for i in range(R.VIEW_W)))
        self.assertAlmostEqual(t.clipangle * 360 / 65536, 45, delta=0.2)
        # each column's angle maps back to that column
        for x in range(R.VIEW_W):
            self.assertEqual(t.vatx(t.xtoviewangle[x]), x)
        for i in range(R.FINEANGLES):
            self.assertEqual(t.sin(i), -t.sin(i + R.FINEANGLES // 2))
            self.assertAlmostEqual(t.sin(i) / R.SINE_ONE, math.sin(i * 2 * math.pi / 4096),
                                   delta=1e-4)
        for a in range(R.TANHALF):
            self.assertEqual(t.tan(a), -t.tan(R.TANHALF - 1 - a))
        for scale in (256, 300, 511, 512, 65536, 123457, R.SCALE_MAX):
            self.assertAlmostEqual(t.iscale(scale) / (2 ** 31 / scale), 1, delta=1 / 256)

    def test_generated(self):
        """gen_tables writes the reference's tables, and ca65 assembles them."""
        out = Path(tempfile.mkdtemp(prefix="tables_"))
        try:
            self.assertEqual(gen_tables.main(["--out", str(out), "-q"]), 0)
            src = (out / "render/tables.s").read_text()
            data, label = {}, None
            for line in src.splitlines():
                m = re.match(r"^(\w+):$", line)
                if m:
                    label = m.group(1)
                    data[label] = []
                elif line.strip().startswith(".byte") and label:
                    data[label] += [int(b.strip()[1:], 16) for b in line.split(None, 1)[1].split(",")]
            t = R.tables()

            def join(name, n, signed=False):
                parts = ["lo", "hi"] if n == 2 else ["lo", "mid", "hi"]
                vals = [sum(data[f"{name}_{p}"][i] << (8 * k) for k, p in enumerate(parts))
                        for i in range(len(data[f"{name}_lo"]))]
                if signed:
                    vals = [v - (1 << (8 * n)) if v >> (8 * n - 1) else v for v in vals]
                return vals

            self.assertEqual(join("finesine", 2), t.sine_q)
            self.assertEqual(join("tantoangle", 2), t.tantoangle)
            self.assertEqual(join("finetangent", 3), t.tan_pos)
            self.assertEqual(join("recip", 3), t.recip)
            self.assertEqual(join("xtoviewangle", 2), t.xtoviewangle)
            self.assertEqual(join("distscale", 2), t.distscale)
            self.assertEqual(join("yslope", 2), t.yslope)
            self.assertEqual(join("mul_sqr", 2), t.mul_sqr)
            self.assertEqual(join("mul_nsqr", 2), t.mul_nsqr)
            self.assertEqual(data["viewangletox"], t.viewangletox)
            self.assertEqual(data["scalelight"], [k for row in t.scalelight for k in row])
            self.assertEqual(data["zlight"], [k for row in t.zlight for k in row])
            self.assertEqual([b - 256 if b > 127 else b for b in data["fuzzoffset"]],
                             t.fuzzoffset)
            if shutil.which("ca65"):
                subprocess.run(["ca65", "--cpu", "65c02", "-I", str(out / "render"),
                                "-o", str(out / "tables.o"), str(out / "render/tables.s")],
                               check=True)
        finally:
            shutil.rmtree(out)


def tearDownModule():
    if _tmp is not None:
        shutil.rmtree(_tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--golden" in sys.argv:          # print the current hashes (to update GOLDEN)
        for k, v in golden_views().items():
            print(f"{k}: {v}")
        sys.exit(0)
    unittest.main()
