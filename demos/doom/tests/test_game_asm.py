#!/usr/bin/env python3
"""The game's assembly against its C (docs/DESIGN.md section 9).

The hot parts of the game core exist twice: in C (src/game/p_*.c, the
reference, compiled on the host) and in 65C02 assembly (src/game/a_*.s,
what GAME.BIN runs). These tests run the assembly on py65 in the flat
harness (tests/host/gamesim.py: the modules under test linked alone, far
memory served from the converter's banks) and compare every result with
the host build of the C, or with values computed here from the data:

  - fixed.s: FixedMul and FixedDiv against vanilla's 64-bit definitions
    on random and edge operands; fine_sine/fine_cosine at every angle;
  - a_levdata.s: P_LevAddr for every level array, P_Line for every line
    of E1M1, the blockmap line list of every cell, R_PointInSector at
    random points, P_RejectVisible for random sector pairs, the sector
    setters (near mirror and far record).

Run:  python3 tests/test_game_asm.py [-v]    (needs build/data)
"""

from __future__ import annotations

import ctypes
import json
import os
import random
import struct
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
sys.path.insert(0, str(PROJECT / "tests/host"))
sys.path.insert(0, str(PROJECT / "tools"))
import gamesim  # noqa: E402
import test_game_core as core  # noqa: E402

DATA = PROJECT / "build/data"
MEASURE = {}
MAPARR = ["VERTEXES", "SEGS", "SSECTORS", "NODES", "SIDEDEFS", "LINEDEFS", "SECTORS",
          "SECLINES", "THINGS", "BLOCKMAP", "REJECT"]


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def s8(v):
    return v - 256 if v & 0x80 else v


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def vanilla_mul(a, b):
    return s32((a * b) >> 16)


def vanilla_div(a, b):
    if (abs(a) >> 14) >= abs(b):
        return -0x80000000 if (a ^ b) < 0 else 0x7FFFFFFF
    q = (abs(a) << 16) // abs(b)
    return s32(-q if (a < 0) != (b < 0) else q)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class FixedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = gamesim.FlatGame(out=PROJECT / "build/host/asm_fixed", only=["fixed.s", "gtables.s", "gwork.s"])
        cls.g.call("game_boot")
        cls.g.call("_game_farinit")

    def put32(self, name, v):
        a = self.g.L[name]
        self.g.mem[a:a + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")

    def get32(self, name):
        a = self.g.L[name]
        return s32(int.from_bytes(self.g.mem[a:a + 4], "little"))

    def test_mul_div(self):
        rnd = random.Random(1)
        edges = [0, 1, -1, 0x10000, -0x10000, 0x7FFFFFFF, -0x80000000, 0xE800, 12345678, -987654]
        cyc, dcyc = [], []
        for i in range(600):
            a = rnd.choice(edges) if i < 150 else rnd.randint(-2 ** 31, 2 ** 31 - 1) >> rnd.randint(0, 24)
            b = rnd.choice(edges) if i % 3 == 0 else rnd.randint(-2 ** 31, 2 ** 31 - 1) >> rnd.randint(0, 24)
            self.put32("fxa", a)
            self.put32("fxb", b)
            cyc.append(self.g.call("fx_mul"))
            self.assertEqual(self.get32("fxr"), vanilla_mul(a, b), f"FixedMul({a}, {b})")
            if b:
                c = self.g.call("fx_div")
                if abs(a) >> 14 < abs(b):       # (not the overflow shortcut)
                    dcyc.append(c)
                self.assertEqual(self.get32("fxr"), vanilla_div(a, b), f"FixedDiv({a}, {b})")
            # the C entry points agree with the assembly ones
            if i % 50 == 0:
                r = self.g.ccall("_FixedMul", (a, 4), (b, 4))
                self.assertEqual(s32(r), vanilla_mul(a, b))
        MEASURE["FixedMul cycles (random 32-bit operands): mean / max"] = \
            f"{sum(cyc) // len(cyc)} / {max(cyc)}"
        MEASURE["FixedDiv cycles (no overflow): mean / max"] = f"{sum(dcyc) // len(dcyc)} / {max(dcyc)}"

    def test_sine(self):
        host = core.Game()
        lib = host.lib
        lib.fine_sine.restype = ctypes.c_int32
        lib.fine_cosine.restype = ctypes.c_int32
        for a in range(0, 8192, 3):
            self.assertEqual(s32(self.g.ccall("_fine_sine", (a, 2))), lib.fine_sine(a))
            self.assertEqual(s32(self.g.ccall("_fine_cosine", (a, 2))), lib.fine_cosine(a))
        MEASURE["fine_sine cycles (a far read)"] = self.g.cycles


def map_record(mapname="E1M1"):
    manifest = json.loads((DATA / "manifest.json").read_text())
    return manifest["maps"][mapname]


def flat_level(cls, out, only):
    """Build the flat harness with the modules `only`, load E1M1's level
    arrays as P_SetupLevel would (levarr, counts, sector mirrors in
    lev_scratch) and a host game on the same map; sets cls.g, rec, nsec,
    floorh, ceilh, special, host, geo."""
    g = cls.g = gamesim.FlatGame(out=PROJECT / out, only=only)
    g.call("game_boot")
    g.call("_game_farinit")
    cls.rec = map_record("E1M1")
    arrays = cls.rec["arrays"]
    L, mem = g.L, g.mem
    la = L["_levarr"]
    for i, name in enumerate(MAPARR):
        d = arrays[name]
        size = d["elsize"]
        shift = size.bit_length() - 1 if size & (size - 1) == 0 else 0xFF
        mask = 0xFFFF if d["log2"] >= 16 else (1 << d["log2"]) - 1
        mem[la + 10 * i:la + 10 * i + 10] = struct.pack(
            "<BHBBBHH", d["bank"], d["addr"], size, shift, d["log2"], mask, d["count"])
    cls.nsec = arrays["SECTORS"]["count"]
    cls.put16("_numnodes", arrays["NODES"]["count"])
    cls.put16("_numsectors", cls.nsec)
    scratch = L["_lev_scratch"]
    cls.floorh, cls.ceilh = scratch, scratch + 2 * cls.nsec
    cls.special = scratch + 4 * cls.nsec
    cls.rknown = cls.special + cls.nsec
    cls.rbits = cls.rknown + 128
    for name, addr in (("_sec_floorh", cls.floorh), ("_sec_ceilh", cls.ceilh),
                       ("_sec_special", cls.special), ("_rej_known", cls.rknown),
                       ("_rej_bits", cls.rbits)):
        cls.put16(name, addr)
    g.call("_P_ClearCaches")
    cls.host = core.Game()
    cls.host.load(1, 2)
    import refrender
    cls.geo = refrender.GameData(DATA, "E1M1")


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class LevDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flat_level(cls, "build/host/asm_levdata",
                   ["fixed.s", "gtables.s", "gwork.s", "a_levdata.s", "flat_levglobals.c"])

    @classmethod
    def put16(cls, name, v):
        a = cls.g.L[name]
        cls.g.mem[a:a + 2] = (v & 0xFFFF).to_bytes(2, "little")

    def far(self, bank, addr, n):
        return bytes(self.g.bank(bank)[addr:addr + n])

    def test_lev_addr(self):
        rnd = random.Random(2)
        for i, name in enumerate(MAPARR):
            d = self.rec["arrays"][name]
            for idx in [0, d["count"] - 1] + [rnd.randrange(d["count"]) for _ in range(20)]:
                r = self.g.ccall("_P_LevAddr", (i, 1), (idx, 2))
                k = d["log2"]
                want = ((d["bank"] + (idx >> k)) << 16) | (d["addr"] + (idx & ((1 << k) - 1)) * d["elsize"])
                self.assertEqual(r & 0xFFFFFF, want, f"{name}[{idx}]")

    def test_lines(self):
        g = self.g
        for i, li in enumerate(self.geo.lines):
            p = g.ccall("_P_Line", (i, 2)) & 0xFFFF
            raw = bytes(g.mem[p:p + 27])
            index, v1x, v1y, dx, dy, top, bottom, left, right, front, back, tag, flags, special, slope = \
                struct.unpack("<HhhhhhhhhHHHBBB", raw)
            a, b = self.geo.vertexes[li.v1], self.geo.vertexes[li.v2]
            self.assertEqual((index, v1x, v1y, dx, dy), (i, a.x, a.y, b.x - a.x, b.y - a.y))
            self.assertEqual((top, bottom, left, right),
                             (max(a.y, b.y), min(a.y, b.y), min(a.x, b.x), max(a.x, b.x)))
            self.assertEqual((front, back, tag, flags, special, slope),
                             (li.frontsector, li.backsector, li.tag, li.flags & 0xFF, li.special,
                              li.slopetype))
            if i == 5:
                MEASURE["P_Line miss (a 26-byte far read)"] = g.cycles
        g.ccall("_P_Line", (5, 2))
        g.ccall("_P_Line", (5, 2))
        MEASURE["P_Line hit"] = g.cycles

    def test_point_in_sector(self):
        rnd = random.Random(3)
        xs = [v.x for v in self.geo.vertexes]
        ys = [v.y for v in self.geo.vertexes]
        cyc = []
        for _ in range(1500):
            x = rnd.randint(min(xs), max(xs)) * 65536 + rnd.randrange(65536)
            y = rnd.randint(min(ys), max(ys)) * 65536 + rnd.randrange(65536)
            r = self.g.ccall("_R_PointInSector", (x, 4), (y, 4)) & 0xFFFF
            cyc.append(self.g.cycles)
            self.host.lib.R_PointInSector.restype = ctypes.c_uint16
            want = self.host.lib.R_PointInSector(ctypes.c_int32(x), ctypes.c_int32(y))
            self.assertEqual(r, want, f"({x / 65536}, {y / 65536})")
        # warm cache: the same point again
        self.g.ccall("_R_PointInSector", (x, 4), (y, 4))
        MEASURE["R_PointInSector cycles: random points mean / same point again"] = \
            f"{sum(cyc) // len(cyc)} / {self.g.cycles}"

    def blockmap_lists(self):
        d = self.rec["arrays"]["BLOCKMAP"]
        img = self.g.bank(d["bank"])
        words = struct.unpack_from(f"<{d['count']}H", img, d["addr"])
        w, h = words[2], words[3]
        out = []
        for cell in range(w * h):
            off = words[4 + cell]
            lst = []
            while words[off] != 0xFFFF:
                lst.append(words[off])
                off += 1
            out.append(lst)
        return out

    def test_block_lines(self):
        g, L = self.g, self.g.L
        lists = self.blockmap_lists()
        longest = 0
        for cell, want in enumerate(lists):
            for rep in range(2):                    # fetched, then cached
                self.put16("blk_cell", cell)
                self.put16("blk_pos", 0)
                got = []
                while True:
                    g.call("blk_lines")
                    n = g.mpu.a
                    if n == 0:
                        break
                    buf = L["blk_buf"]
                    got += list(struct.unpack_from(f"<{n}H", g.mem, buf))
                self.assertEqual(got, want, f"cell {cell}")
            longest = max(longest, len(want))
        MEASURE["E1M1 blockmap: cells / longest list"] = f"{len(lists)} / {longest}"

    def test_reject(self):
        rnd = random.Random(4)
        d = self.rec["arrays"]["REJECT"]
        img = self.g.bank(d["bank"])
        n = self.nsec
        for rep in range(400):
            s2 = rnd.randrange(n) if rep % 40 == 0 else rnd.choice([3, 7, 50])
            s1 = rnd.randrange(n)
            pnum = s1 * n + s2
            bit = (img[d["addr"] + (pnum >> 3)] >> (pnum & 7)) & 1
            r = self.g.ccall("_P_RejectVisible", (s1, 2), (s2, 2)) & 0xFF
            self.assertEqual(r, 0 if bit else 1, f"{s1} {s2}")

    def test_sector_setters(self):
        g = self.g
        d = self.rec["arrays"]["SECTORS"]
        for sec, h in ((0, 123), (17, -45), (self.nsec - 1, 300)):
            g.ccall("_P_SetSectorFloor", (sec, 2), (h, 2))
            g.ccall("_P_SetSectorCeiling", (sec, 2), (h + 64, 2))
            g.ccall("_P_SetSectorSpecial", (sec, 2), (9, 1))
            self.assertEqual(s16(int.from_bytes(g.mem[self.floorh + 2 * sec:self.floorh + 2 * sec + 2],
                                                "little")), h)
            self.assertEqual(g.mem[self.special + sec], 9)
            k = d["log2"]
            bank, addr = d["bank"] + (sec >> k), d["addr"] + (sec & ((1 << k) - 1)) * 16
            fh, ch = struct.unpack("<hh", self.far(bank, addr, 4))
            self.assertEqual((fh, ch), (h, h + 64))
            self.assertEqual(self.far(bank, addr + 9, 1)[0], 9)


def mt_index(name):
    """The value of an MT_ enumerator of src/game/info.h."""
    text = (PROJECT / "src/game/info.h").read_text()
    body = text[text.index("MT_PLAYER,"):]
    names = [w.strip().rstrip(",") for w in body.split("\n")]
    return [n for n in names if n.startswith("MT_")].index(name)


class HostIntercept(ctypes.Structure):
    _fields_ = [("frac", ctypes.c_int32), ("isaline", ctypes.c_uint8),
                ("line", ctypes.c_uint16), ("thing", ctypes.c_void_p)]


HOST_TRAV = ctypes.CFUNCTYPE(ctypes.c_uint8, ctypes.POINTER(HostIntercept))


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class MapUtlTest(unittest.TestCase):
    """a_maputl.s against p_maputl.c on E1M1."""

    @classmethod
    def setUpClass(cls):
        flat_level(cls, "build/host/asm_maputl",
                   ["fixed.s", "gtables.s", "gwork.s", "a_levdata.s", "a_maputl.s", "flat_mobjinfo.c",
                    "flat_levglobals.c", "flat_trav.s"])
        g, lib = cls.g, cls.host.lib
        lib.P_Line.restype = ctypes.c_void_p
        lib.P_Line.argtypes = [ctypes.c_uint16]
        for name in ("P_PointOnLineSide", "P_PointOnDivlineSide"):
            getattr(lib, name).argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_void_p]
            getattr(lib, name).restype = ctypes.c_uint8
        lib.P_BoxOnLineSide.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.P_BoxOnLineSide.restype = ctypes.c_int8
        lib.P_InterceptVector.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.P_InterceptVector.restype = ctypes.c_int32
        lib.P_AproxDistance.argtypes = [ctypes.c_int32, ctypes.c_int32]
        lib.P_AproxDistance.restype = ctypes.c_int32
        for name in ("P_BlockX", "P_BlockY"):
            getattr(lib, name).argtypes = [ctypes.c_int32]
            getattr(lib, name).restype = ctypes.c_int16
        lib.P_PathTraverse.argtypes = [ctypes.c_int32] * 4 + [ctypes.c_uint8, HOST_TRAV]
        lib.P_PathTraverse.restype = ctypes.c_uint8
        # the level's globals, as the host set them up
        for name, ct, size in (("numlines", ctypes.c_uint16, 2), ("bmaporgx", ctypes.c_int16, 2),
                               ("bmaporgy", ctypes.c_int16, 2), ("bmapwidth", ctypes.c_uint8, 1),
                               ("bmapheight", ctypes.c_uint8, 1)):
            v = ct.in_dll(lib, name).value
            a = g.L["_" + name]
            g.mem[a:a + size] = (v & ((1 << 8 * size) - 1)).to_bytes(size, "little")
        cls.bw, cls.bh = g.byte("_bmapwidth"), g.byte("_bmapheight")
        cls.orgx, cls.orgy = s16(g.word("_bmaporgx")), s16(g.word("_bmaporgy"))
        nsec = cls.nsec
        fh = ctypes.cast(ctypes.c_void_p.in_dll(lib, "sec_floorh").value, ctypes.POINTER(ctypes.c_int16))
        ch = ctypes.cast(ctypes.c_void_p.in_dll(lib, "sec_ceilh").value, ctypes.POINTER(ctypes.c_int16))
        for sec in range(nsec):
            g.mem[cls.floorh + 2 * sec:cls.floorh + 2 * sec + 2] = (fh[sec] & 0xFFFF).to_bytes(2, "little")
            g.mem[cls.ceilh + 2 * sec:cls.ceilh + 2 * sec + 2] = (ch[sec] & 0xFFFF).to_bytes(2, "little")
        arena = g.L["_lev_arena"]
        cls.blocklinks = arena + 4096
        cls.put16("_blocklinks", cls.blocklinks)
        cls.box = arena + 7000
        cls.dl1, cls.dl2 = arena + 7100, arena + 7200
        cls.objs = arena + 7300
        g.call("_P_InitLineMarks")
        cls.nlines = len(cls.geo.lines)
        xs = [v.x for v in cls.geo.vertexes]
        ys = [v.y for v in cls.geo.vertexes]
        cls.xr, cls.yr = (min(xs), max(xs)), (min(ys), max(ys))

    @classmethod
    def put16(cls, name, v):
        a = cls.g.L[name] if isinstance(name, str) else name
        cls.g.mem[a:a + 2] = (v & 0xFFFF).to_bytes(2, "little")

    def put32s(self, addr, *vals):
        for k, v in enumerate(vals):
            self.g.mem[addr + 4 * k:addr + 4 * k + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")

    def rnd_fixed(self, rnd, r):
        return rnd.randint(r[0] - 64, r[1] + 64) * 65536 + rnd.randrange(65536)

    def test_sides(self):
        g, lib = self.g, self.host.lib
        rnd = random.Random(5)
        for rep in range(1500):
            i = rnd.randrange(self.nlines)
            li = self.geo.lines[i]
            a = self.geo.vertexes[li.v1]
            if rep % 3 == 0:        # near the line
                x = (a.x + rnd.randint(-40, 40)) * 65536 + rnd.randrange(65536)
                y = (a.y + rnd.randint(-40, 40)) * 65536 + rnd.randrange(65536)
            else:
                x, y = self.rnd_fixed(rnd, self.xr), self.rnd_fixed(rnd, self.yr)
            if rep % 7 == 0:
                x = a.x * 65536
            p = g.ccall("_P_Line", (i, 2)) & 0xFFFF
            r = g.ccall("_P_PointOnLineSide", (x, 4), (y, 4), (p, 2)) & 0xFF
            self.assertEqual(r, lib.P_PointOnLineSide(x, y, lib.P_Line(i)), f"line {i} ({x}, {y})")
            # a box around (x, y)
            h = rnd.choice([1, 16, 20, 32, 64]) * 65536
            box = (y + h, y - h, x - h, x + h)
            self.put32s(self.box, *box)
            p = g.ccall("_P_Line", (i, 2)) & 0xFFFF
            r = s8(g.ccall("_P_BoxOnLineSide", (self.box, 2), (p, 2)) & 0xFF)
            hb = (ctypes.c_int32 * 4)(*box)
            self.assertEqual(r, lib.P_BoxOnLineSide(hb, lib.P_Line(i)), f"box line {i}")
        MEASURE["P_BoxOnLineSide (last)"] = g.cycles

    def test_divlines(self):
        g, lib = self.g, self.host.lib
        rnd = random.Random(6)
        for rep in range(1500):
            v = [self.rnd_fixed(rnd, self.xr), self.rnd_fixed(rnd, self.yr),
                 rnd.randint(-2048, 2048) * 65536 + rnd.randrange(65536),
                 rnd.randint(-2048, 2048) * 65536 + rnd.randrange(65536)]
            if rep % 5 == 0:
                v[2 + rep % 2] = 0
            w = [self.rnd_fixed(rnd, self.xr), self.rnd_fixed(rnd, self.yr),
                 rnd.randint(-512, 512) * 65536, rnd.randint(-512, 512) * 65536]
            self.put32s(self.dl1, *v)
            self.put32s(self.dl2, *w)
            hv, hw = (ctypes.c_int32 * 4)(*v), (ctypes.c_int32 * 4)(*w)
            x, y = w[0], w[1]
            r = g.ccall("_P_PointOnDivlineSide", (x, 4), (y, 4), (self.dl1, 2)) & 0xFF
            self.assertEqual(r, lib.P_PointOnDivlineSide(x, y, hv), f"{v} ({x}, {y})")
            r = s32(g.ccall("_P_InterceptVector", (self.dl1, 2), (self.dl2, 2)))
            self.assertEqual(r, lib.P_InterceptVector(hv, hw), f"{v} {w}")
        MEASURE["P_InterceptVector (last)"] = g.cycles
        for rep in range(300):
            dx, dy = rnd.randint(-(1 << 28), 1 << 28), rnd.randint(-(1 << 28), 1 << 28)
            r = s32(g.ccall("_P_AproxDistance", (dx, 4), (dy, 4)))
            self.assertEqual(r, lib.P_AproxDistance(dx, dy))
            x = self.rnd_fixed(rnd, self.xr)
            self.assertEqual(s16(g.ccall("_P_BlockX", (x, 4)) & 0xFFFF), lib.P_BlockX(x))
            self.assertEqual(s16(g.ccall("_P_BlockY", (x, 4)) & 0xFFFF), lib.P_BlockY(x))
        for i in range(self.nlines):
            p = g.ccall("_P_Line", (i, 2)) & 0xFFFF
            g.ccall("_P_LineOpening", (p, 2))
            lib.P_LineOpening(ctypes.c_void_p(lib.P_Line(i)))
            got = [g.long("_opentop"), g.long("_openbottom"), g.long("_openrange")]
            want = [ctypes.c_int32.in_dll(lib, n).value for n in ("opentop", "openbottom", "openrange")]
            if self.geo.lines[i].backsector == 0xFFFF:
                got, want = got[2:], want[2:]
            else:
                got.append(g.long("_lowfloor"))
                want.append(ctypes.c_int32.in_dll(lib, "lowfloor").value)
            self.assertEqual(got, want, f"line {i}")

    def flat_traverse(self, x1, y1, x2, y2, flags, stop=0):
        g = self.g
        g.mem[g.L["rec_n"]] = 0
        g.mem[g.L["rec_stop"]] = stop
        r = g.ccall("_P_PathTraverse", (x1, 4), (y1, 4), (x2, 4), (y2, 4), (flags, 1),
                    (g.L["_rec_trav"], 2)) & 0xFF
        n = g.byte("rec_n")
        buf = g.L["rec_buf"]
        out = [struct.unpack_from("<iBHH", g.mem, buf + 9 * k) for k in range(n)]
        out = [(f, a, ln) if a else (f, a, th) for f, a, ln, th in out]
        return r, out

    def test_path_traverse(self):
        lib = self.host.lib
        rnd = random.Random(7)
        cyc = []
        for rep in range(250):
            x1, y1 = self.rnd_fixed(rnd, self.xr), self.rnd_fixed(rnd, self.yr)
            ang = rnd.random() * 6.2832
            import math
            dist = rnd.choice([64, 256, 1024, 2048])
            x2, y2 = x1 + int(dist * 65536 * math.cos(ang)), y1 + int(dist * 65536 * math.sin(ang))
            if rep % 10 == 0:
                x1 = (self.orgx + 128 * rnd.randint(1, 8)) * 65536
            flags = 1 | (4 if rep % 3 == 0 else 0)
            stop = rnd.choice([0, 0, 1, 3])
            want = []

            def trav(p):
                want.append((p.contents.frac, p.contents.isaline, p.contents.line))
                return 0 if len(want) == stop else 1
            r_want = lib.P_PathTraverse(x1, y1, x2, y2, flags, HOST_TRAV(trav))
            r, got = self.flat_traverse(x1, y1, x2, y2, flags, stop)
            cyc.append(self.g.cycles)
            self.assertEqual((r, got), (r_want, want), f"({x1}, {y1}) -> ({x2}, {y2}) flags {flags}")
        MEASURE["P_PathTraverse (lines) cycles: mean / max"] = f"{sum(cyc) // len(cyc)} / {max(cyc)}"

    def test_things(self):
        """Actors and statics in the blockmap: link, iterate, trace, unlink."""
        g, L, mem = self.g, self.g.L, self.g.mem
        mem[self.blocklinks:self.blocklinks + 2 * self.bw * self.bh] = bytes(2 * self.bw * self.bh)
        st = self.objs
        self.put16("_statics", st)
        self.put16("_statics_end", st + 3 * 16)
        actors = st + 3 * 16
        cx, cy = self.orgx + 128 * 5 + 64, self.orgy + 128 * 6 + 64    # the middle of cell (5, 6)
        # statics: a barrel, a gibbed corpse, a lamp; the barrel at the cell's centre
        barrel = mt_index("MT_BARREL")
        mem[L["_mobjinfo"] + 34 * barrel + 31] = 10         # its radius (MI_RADIUS)
        items = [(cx, cy, barrel, 0), (cx - 40, cy + 20, barrel, 0x10), (cx + 30, cy - 30, barrel, 0)]
        for k, (x, y, t, fl) in enumerate(items):
            a = st + 16 * k
            mem[a:a + 16] = bytes(16)
            struct.pack_into("<hh", mem, a, x, y)
            mem[a + 12] = t
            mem[a + 14] = fl
            g.ccall("_P_LinkStatic", (a, 2))
        # actors: radius 16, at the cell's centre offset
        for k in range(2):
            a = actors + 63 * k
            mem[a:a + 63] = bytes(63)
            struct.pack_into("<ii", mem, a + 6, (cx + 10 + 20 * k) * 65536, (cy + 5) * 65536)
            mem[a + 58] = 16
            g.ccall("_P_SetThingPosition", (a, 2))
            want_sec = self.host.sector_at(cx + 10 + 20 * k, cy + 5)
            self.assertEqual(int.from_bytes(mem[a + 50:a + 52], "little"), want_sec)
        def cell_things():
            mem[L["rec_n"]] = 0
            g.ccall("_P_BlockThingsIterator", (5, 2), (6, 2), (L["_rec_thing"], 2))
            return list(struct.unpack_from(f"<{g.byte('rec_n')}H", mem, L["rec_buf"]))
        everything = [actors + 63, actors, st + 32, st + 16, st]
        self.assertEqual(cell_things(), everything)
        # a trace through the cell from the west: things only
        r, got = self.flat_traverse((cx - 100) * 65536, (cy + 5) * 65536, (cx + 100) * 65536,
                                    (cy + 5) * 65536, 2)
        hit = [t for f, a, t in got]
        fr = [f for f, a, t in got]
        self.assertEqual(fr, sorted(fr))
        # the barrel (radius 10) at y = cy is crossed, the gibbed corpse is not
        self.assertIn(st, hit)
        self.assertNotIn(st + 16, hit)
        self.assertIn(actors, hit)
        self.assertEqual(r, 1)
        # radius of a gibbed static is 0, an actor's its own
        self.assertEqual(g.ccall("_P_ThingRadius", (st + 16, 2)) & 0xFF, 0)
        self.assertEqual(g.ccall("_P_ThingRadius", (actors, 2)) & 0xFF, 16)
        # unlink the middle ones
        g.ccall("_P_UnlinkStatic", (st + 16, 2))
        g.ccall("_P_UnsetThingPosition", (actors, 2))
        self.assertEqual(cell_things(), [actors + 63, st + 32, st])
        g.ccall("_P_UnsetThingPosition", (actors + 63, 2))
        g.ccall("_P_UnlinkStatic", (st, 2))
        self.assertEqual(cell_things(), [st + 32])

    def test_line_marks(self):
        g = self.g
        g.call("_P_NewValidcount")
        rnd = random.Random(8)
        for many in (5, 30, 200):
            seen = set()
            for _ in range(many):
                i = rnd.randrange(self.nlines)
                r = g.ccall("_P_LineChecked", (i, 2)) & 0xFF
                self.assertEqual(r, 1 if i in seen else 0)
                seen.add(i)
            g.call("_P_NewValidcount")
            for i in range(self.nlines):
                self.assertEqual(g.ccall("_P_LineChecked", (i, 2)) & 0xFF, 0, f"{many} line {i}")
            g.call("_P_NewValidcount")


def tearDownModule():
    if MEASURE and ("-v" in sys.argv or os.environ.get("DOOM_MEASURE")):
        print("\nmeasurements (6502 cycles, far accesses charged as the kernel's):")
        for k, v in MEASURE.items():
            print(f"  {k:62s} {v}")


if __name__ == "__main__":
    unittest.main()
