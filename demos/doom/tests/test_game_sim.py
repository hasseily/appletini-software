#!/usr/bin/env python3
"""The whole game on a 65C02 against its C reference (docs/DESIGN.md section 9).

The flat harness (tests/host/gamesim.py) runs GAME.FLAT, the cc65 build
of src/game (the assembly core, a_*.s, and the C that stays C) on py65,
far memory served from the converter's banks; the host build of the same
sources with the C reference modules (tests/test_game_core.py) runs
beside it. Both boot (game_init: E1M1, "hurt me plenty") and get the same
input every tic; after every tic the tests compare what the play
simulation is:

  - the random number index, leveltime, the sound hook's count and last
    sounds;
  - the player: position, momentum, angle, view height and bob, health,
    weapons, ammo, the weapon layers (state, tics, sx, sy);
  - every thing, actors and statics (type, position, state, tics, health,
    flags, sector, angle, momentum, floor and ceiling), as sorted lists
    (the pools are laid out differently);
  - after the tics of a frame, the render packet (the things as a set:
    their order within a distance band follows the pool order).

The scripted input walks, turns, strafes, runs into walls, fires the
pistol, punches, changes weapons and uses lines (SimDiffTest); the
pistol then shoots a barrel until it explodes, from 96 units
(SimBarrelTest: a static woken, damage, death states, the radius
attack); and game_tic loads E1M8 (the set-up overlay read back, the
actor pool grown again) where the player walks and shoots (SimMapTest;
the harness's 64 KB holds the level memory of E1M1 and E1M8 only). The
cycles of each tic and frame are the measurements of DESIGN.md section
9 (far accesses charged what the kernel's cost in GAME space).

Run:  python3 tests/test_game_sim.py [-v]      (needs build/data; minutes)
"""

from __future__ import annotations

import os
import re
import struct
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
sys.path.insert(0, str(PROJECT / "tests/host"))
import gamesim  # noqa: E402
import test_game_core as core  # noqa: E402

MEASURE = {}


def offsets() -> dict[str, int]:
    """The constants of src/game/goffsets.inc (struct offsets, enums)."""
    out = {}
    for line in (PROJECT / "src/game/goffsets.inc").read_text().splitlines():
        m = re.match(r"(\w+)\s*=\s*(-?\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


O = offsets()
KM_FORWARD, KM_BACK, KM_LEFT, KM_RIGHT, KM_STRAFEL, KM_STRAFER = 1, 2, 4, 8, 16, 32
KB_FIRE, KB_USE, KB_RUN = 1, 2, 0x80


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


class Flat(gamesim.FlatGame):
    """Readers of the game's state in the flat memory."""

    def u8(self, a):
        return self.mem[a]

    def u16(self, a):
        return self.mem[a] | self.mem[a + 1] << 8

    def i32(self, a):
        return s32(int.from_bytes(self.mem[a:a + 4], "little"))

    def player(self) -> dict:
        pl = self.L["_player"]
        mo = self.u16(pl + O["PL_MO"])
        return dict(
            x=self.i32(mo + O["MO_X"]), y=self.i32(mo + O["MO_Y"]), z=self.i32(mo + O["MO_Z"]),
            angle=self.u16(mo + O["MO_ANGLE"]), viewz=self.i32(pl + O["PL_VIEWZ"]),
            momx=self.i32(mo + O["MO_MOMX"]), momy=self.i32(mo + O["MO_MOMY"]),
            health=s16(self.u16(pl + O["PL_HEALTH"])),
            floorz=s16(self.u16(mo + O["MO_FLOORZ"])), ceilingz=s16(self.u16(mo + O["MO_CEILINGZ"])),
            sector=self.u16(mo + O["MO_SECTOR"]), readyweapon=self.u8(pl + O["PL_READYWEAPON"]),
            clip=s16(self.u16(pl + O["PL_AMMO"])), state=self.u16(mo + O["MO_STATE"]),
            playerstate=self.u8(pl + O["PL_PLAYERSTATE"]),
            wstate=self.u16(pl + O["PL_PSPRITES"] + O["PS_STATE"]))

    def player_more(self) -> dict:
        pl = self.L["_player"]
        ps = pl + O["PL_PSPRITES"]
        layers = []
        for i in range(2):
            p = ps + i * O["PS_SIZE"]
            layers.append((self.u16(p + O["PS_STATE"]), self.u8(p + O["PS_TICS"]),
                           self.i32(p + O["PS_SX"]), self.i32(p + O["PS_SY"])))
        return dict(viewheight=self.i32(pl + O["PL_VIEWHEIGHT"]),
                    deltaviewheight=self.i32(pl + O["PL_DELTAVIEWHEIGHT"]),
                    bob=self.i32(pl + O["PL_BOB"]), refire=self.u8(pl + O["PL_REFIRE"]),
                    pendingweapon=self.u8(pl + O["PL_PENDINGWEAPON"]),
                    attackdown=self.u8(pl + O["PL_ATTACKDOWN"]),
                    usedown=self.u8(pl + O["PL_USEDOWN"]), extralight=self.u8(pl + O["PL_EXTRALIGHT"]),
                    layers=layers)

    def things(self) -> list[tuple]:
        L = self.L
        out = []
        think = L["_P_MobjThinker"]
        a, end = self.u16(L["_mobjs"]), self.u16(L["_mobjs_end"])
        while a < end:
            if self.u16(a + O["TH_FUNCTION"]) == think:
                out.append((0, self.u8(a + O["MO_TYPE"]), self.i32(a + O["MO_X"]),
                            self.i32(a + O["MO_Y"]), self.i32(a + O["MO_Z"]),
                            self.u16(a + O["MO_STATE"]), s16(self.u16(a + O["MO_HEALTH"])),
                            self.i32(a + O["MO_FLAGS"]), self.u16(a + O["MO_SECTOR"]), 0,
                            self.u8(a + O["MO_TICS"]), self.u16(a + O["MO_ANGLE"]),
                            self.i32(a + O["MO_MOMX"]), self.i32(a + O["MO_MOMY"]),
                            self.i32(a + O["MO_MOMZ"]),
                            s32(self.u16(a + O["MO_FLOORZ"]) << 16 | self.u16(a + O["MO_CEILINGZ"]))))
            a += O["MO_SIZE"]
        a, end = self.u16(L["_statics"]), self.u16(L["_statics_end"])
        while a < end:
            sf = self.u8(a + O["SO_SFLAGS"])
            if not sf & 1:
                flags = self.ccall("_P_StaticFlags", (a, 2))
                out.append((1, self.u8(a + O["SO_TYPE"]), s16(self.u16(a + O["SO_X"])) << 16,
                            s16(self.u16(a + O["SO_Y"])) << 16, s16(self.u16(a + O["SO_Z"])) << 16,
                            self.u16(a + O["SO_STATE"]), 0, s32(flags), self.u16(a + O["SO_SECTOR"]),
                            sf, self.u8(a + O["SO_TICS"]), self.u8(a + O["SO_ANGLE"]) << 8,
                            0, 0, 0, 0))
            a += O["SO_SIZE"]
        return sorted(out)

    def actor_extras(self) -> list[tuple]:
        """The actors' monster fields (type, x, y, movedir, movecount,
        reactiontime, threshold, lastlook, the target as (type, x, y))."""
        out = []
        a, end = self.u16(self.L["_mobjs"]), self.u16(self.L["_mobjs_end"])
        think = self.L["_P_MobjThinker"]
        while a < end:
            if self.u16(a + O["TH_FUNCTION"]) == think:
                t = self.u16(a + O["MO_TARGET"])
                tt = None
                if t:
                    tt = (self.u8(t + O["MO_TYPE"]), self.i32(t + O["MO_X"]), self.i32(t + O["MO_Y"]))
                out.append((self.u8(a + O["MO_TYPE"]), self.i32(a + O["MO_X"]),
                            self.i32(a + O["MO_Y"]), self.u8(a + O["MO_MOVEDIR"]),
                            self.u8(a + O["MO_MOVECOUNT"]), self.u8(a + O["MO_REACTIONTIME"]),
                            self.u8(a + O["MO_THRESHOLD"]), self.u8(a + O["MO_LASTLOOK"]), tt))
            a += O["MO_SIZE"]
        return sorted(out, key=repr)

    def inventory(self) -> list[int]:
        """The player's inventory as host_inventory gives it."""
        pl = self.L["_player"]
        mo = self.u16(pl + O["PL_MO"])
        w = lambda o: s16(self.u16(pl + o))  # noqa: E731
        v = [w(O["PL_HEALTH"]), w(O["PL_ARMORPOINTS"]), self.u8(pl + O["PL_ARMORTYPE"])]
        v += [w(O["PL_AMMO"] + 2 * i) for i in range(4)] + [w(O["PL_MAXAMMO"] + 2 * i) for i in range(4)]
        v += [self.u8(pl + O["PL_CARDS"] + i) for i in range(6)]
        v += [w(O["PL_POWERS"] + 2 * i) for i in range(6)]
        v += [self.u8(pl + O["PL_WEAPONOWNED"] + i) for i in range(8)]
        v += [self.u8(pl + O["PL_PENDINGWEAPON"]), self.u8(pl + O["PL_READYWEAPON"]),
              self.u8(pl + O["PL_BACKPACK"]), w(O["PL_KILLCOUNT"]), w(O["PL_ITEMCOUNT"]),
              self.u8(pl + O["PL_BONUSCOUNT"]), self.u8(pl + O["PL_DAMAGECOUNT"]),
              self.u8(pl + O["PL_MESSAGE"]), s16(self.u16(mo + O["MO_HEALTH"]))]
        return v

    def rview(self) -> dict:
        a = self.L["_rview"]
        raw = bytes(self.mem[a:a + 40 + 20 * 128])
        x, y, z, angle, extra, cmap, tic, nth, nps = struct.unpack_from("<iiiHBBHBB", raw, 0)
        ps = [struct.unpack_from("<BBii", raw, 20 + 10 * i) for i in range(2)]
        things = [struct.unpack_from("<iiiHBBBBH", raw, 40 + 20 * i) for i in range(nth)]
        return dict(x=x, y=y, z=z, angle=angle, extralight=extra, colormap=cmap, tic=tic,
                    psprites=ps[:nps], things=things)


def host_things(h) -> list[tuple]:
    out = []
    for t in h.things():
        v = [t[k] for k in core.THING_KEYS]
        if v[0] == 1:                       # a static's angle is BAM8 << 8
            v[11] &= 0xFF00
        v[15] = s32(v[15] & 0xFFFFFFFF)
        v[7] = s32(v[7] & 0xFFFFFFFF)
        out.append(tuple(v))
    return sorted(out)


def host_actor_extras(h) -> list[tuple]:
    """actor_extras of the host build (through tests/host/host.c)."""
    import ctypes
    L = h.lib
    L.host_mobj.restype = ctypes.c_void_p
    L.host_mobj_get.restype = ctypes.c_void_p
    L.host_mobj_get.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    L.host_is_actor.argtypes = [ctypes.c_void_p]
    size, n = h.counts()["sizeof_mobj"], h.counts()["nummobjs"]
    base = L.host_mobj(0)
    v = (ctypes.c_int32 * 20)()
    t = (ctypes.c_int32 * 20)()
    out = []
    for i in range(n):
        p = base + i * size
        if not L.host_is_actor(p):
            continue
        target = L.host_mobj_get(p, v)
        tt = None
        if target:
            L.host_mobj_get(target, t)
            tt = (t[0], t[1], t[2])
        out.append((v[0], v[1], v[2], v[8], v[9] & 0xFF, v[10], v[11], v[18], tt))
    return sorted(out, key=repr)


def host_inventory(h) -> list[int]:
    import ctypes
    v = (ctypes.c_int32 * 40)()
    h.lib.host_inventory(v)
    return list(v)


def host_more(h) -> dict:
    """The host's player fields that host_player does not give, read
    through ctypes from its player_t (the host's layout: offsets from
    the C, sizeof and alignment of the host compiler)."""
    import ctypes

    class Psp(ctypes.Structure):
        _fields_ = [("state", ctypes.c_uint16), ("tics", ctypes.c_uint8),
                    ("sx", ctypes.c_int32), ("sy", ctypes.c_int32)]

    class Cmd(ctypes.Structure):
        _fields_ = [("forwardmove", ctypes.c_int8), ("sidemove", ctypes.c_int8),
                    ("angleturn", ctypes.c_int16), ("buttons", ctypes.c_uint8)]

    class Player(ctypes.Structure):
        _fields_ = [("mo", ctypes.c_void_p), ("playerstate", ctypes.c_uint8), ("cmd", Cmd),
                    ("viewz", ctypes.c_int32), ("viewheight", ctypes.c_int32),
                    ("deltaviewheight", ctypes.c_int32), ("bob", ctypes.c_int32),
                    ("health", ctypes.c_int16), ("armorpoints", ctypes.c_int16),
                    ("armortype", ctypes.c_uint8), ("powers", ctypes.c_int16 * 6),
                    ("cards", ctypes.c_uint8 * 6), ("backpack", ctypes.c_uint8),
                    ("readyweapon", ctypes.c_uint8), ("pendingweapon", ctypes.c_uint8),
                    ("weaponowned", ctypes.c_uint8 * 8), ("ammo", ctypes.c_int16 * 4),
                    ("maxammo", ctypes.c_int16 * 4), ("attackdown", ctypes.c_uint8),
                    ("usedown", ctypes.c_uint8), ("cheats", ctypes.c_uint8),
                    ("refire", ctypes.c_uint8), ("killcount", ctypes.c_int16),
                    ("itemcount", ctypes.c_int16), ("secretcount", ctypes.c_int16),
                    ("damagecount", ctypes.c_uint8), ("bonuscount", ctypes.c_uint8),
                    ("attacker", ctypes.c_void_p), ("extralight", ctypes.c_uint8),
                    ("fixedcolormap", ctypes.c_uint8), ("psprites", Psp * 2)]
    p = Player.in_dll(h.lib, "player")
    return dict(viewheight=p.viewheight, deltaviewheight=p.deltaviewheight, bob=p.bob,
                refire=p.refire, pendingweapon=p.pendingweapon, attackdown=p.attackdown,
                usedown=p.usedown, extralight=p.extralight,
                layers=[(q.state, q.tics, q.sx, q.sy) for q in p.psprites])


def script():
    """The scripted input: (move, buttons, mouse, weapon) per tic."""
    seq = []
    seq += [(0, 0, 0, 0)] * 10                         # idle
    seq += [(KM_FORWARD, 0, 0, 0)] * 40                # walk
    seq += [(KM_FORWARD | KM_LEFT, 0, 0, 0)] * 20      # turn while walking
    seq += [(0, KB_FIRE, 0, 0)] * 30                   # fire the pistol
    seq += [(KM_STRAFER, KB_RUN, 0, 0)] * 25           # run sideways
    seq += [(0, 0, -40, 0)] * 12                       # mouse turn
    seq += [(KM_FORWARD, KB_RUN | KB_FIRE, 0, 0)] * 40  # run and fire
    seq += [(0, KB_USE, 0, 0)] * 4                     # use
    seq += [(0, 0, 0, 1)] + [(0, 0, 0, 0)] * 30        # the fist
    seq += [(KM_BACK | KM_RIGHT, 0, 30, 0)] * 30
    seq += [(0, KB_FIRE, 0, 0)] * 20                   # punch
    seq += [(0, 0, 0, 2)] + [(0, 0, 0, 0)] * 20        # the pistol back
    return seq


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimDiffTest(unittest.TestCase):
    """The 6502 game and the host game tic by tic."""

    @classmethod
    def setUpClass(cls):
        cls.g = Flat()
        cls.boot_cycles = cls.g.boot()
        MEASURE["boot + E1M1 set-up (cycles)"] = cls.boot_cycles
        cls.h = core.Game()
        cls.h.lib.host_inventory_set(34, 0)
        cls.h.lib.host_inventory_set(35, 0)
        cls.h.init()
        cls.snd0 = (cls.g.byte("_snd_count"), core.ctypes.c_uint8.in_dll(cls.h.lib, "snd_count").value)

    def compare(self, tic):
        g, h = self.g, self.h
        where = f"tic {tic}"
        self.assertEqual(g.byte("_prndindex"), core.ctypes.c_uint8.in_dll(h.lib, "prndindex").value,
                         where + ": the random index")
        self.assertEqual(g.word("_leveltime"), core.ctypes.c_uint16.in_dll(h.lib, "leveltime").value,
                         where)
        self.assertEqual(g.player(), h.player(), where + ": the player")
        self.assertEqual(g.player_more(), host_more(h), where + ": the player")
        gt, ht = g.things(), host_things(h)
        if gt != ht:
            only_g = [t for t in gt if t not in ht][:5]
            only_h = [t for t in ht if t not in gt][:5]
            self.fail(f"{where}: things differ\n  6502 only: {only_g}\n  host only: {only_h}")
        ga, ha = g.actor_extras(), host_actor_extras(h)
        if ga != ha:
            only_g = [t for t in ga if t not in ha][:5]
            only_h = [t for t in ha if t not in ga][:5]
            self.fail(f"{where}: monsters differ\n  6502 only: {only_g}\n  host only: {only_h}")
        self.assertEqual(g.inventory(), host_inventory(h), where + ": the inventory")
        # (the host library is loaded once per process: its sound count
        # carries on from earlier tests, so the counts are compared from
        # where each test started)
        self.assertEqual((g.byte("_snd_count") - self.snd0[0]) & 0xFF,
                         (core.ctypes.c_uint8.in_dll(h.lib, "snd_count").value - self.snd0[1]) & 0xFF,
                         where + ": sounds")

    def test_script(self):
        g, h = self.g, self.h
        self.compare(0)
        costs = {"idle": [], "walk": [], "fire": [], "all": []}
        frames = []
        for tic, (move, buttons, mouse, weapon) in enumerate(script(), 1):
            c = g.tic(move, buttons, mouse, weapon)
            h.tic(move, buttons, mouse, weapon)
            costs["all"].append(c)
            if not move and not buttons and not mouse and not weapon:
                costs["idle"].append(c)
            elif buttons & KB_FIRE and not move:
                costs["fire"].append(c)
            elif move == KM_FORWARD and not buttons:
                costs["walk"].append(c)
            self.compare(tic)
            if tic % 7 == 0:
                frames.append(g.frame())
                gv, hv = g.rview(), h.rview()
                self.assertEqual({k: v for k, v in gv.items() if k != "things"},
                                 {k: v for k, v in hv.items() if k != "things"}, f"tic {tic}: rview")
                self.assertEqual(sorted(gv["things"]), sorted(hv["things"]), f"tic {tic}: rview things")
        for k, v in costs.items():
            if v:
                MEASURE[f"tic cycles, {k}: mean / max"] = f"{sum(v) // len(v)} / {max(v)}"
        MEASURE["game_frame (render packet) cycles: mean / max"] = \
            f"{sum(frames) // len(frames)} / {max(frames)}"


def flat_place(g, x, y, angle):
    """As host_place_player: the player at (x, y) map units, on the floor
    there, facing angle (BAM16), still."""
    pl = g.L["_player"]
    mo = g.u16(pl + O["PL_MO"])
    g.ccall("_P_UnsetThingPosition", (mo, 2))
    mem = g.mem

    def put(a, v, n=4):
        mem[a:a + n] = (v & ((1 << 8 * n) - 1)).to_bytes(n, "little")
    put(mo + O["MO_X"], x << 16)
    put(mo + O["MO_Y"], y << 16)
    put(mo + O["MO_ANGLE"], angle, 2)
    for f in ("MO_MOMX", "MO_MOMY", "MO_MOMZ"):
        put(mo + O[f], 0)
    g.ccall("_P_SetThingPosition", (mo, 2))
    g.ccall("_P_CheckPosition", (mo, 2), (x << 16, 4), (y << 16, 4))
    floorz, ceilingz = g.long("_tmfloorz"), g.long("_tmceilingz")
    put(mo + O["MO_FLOORZ"], floorz >> 16, 2)
    put(mo + O["MO_CEILINGZ"], ceilingz >> 16, 2)
    put(mo + O["MO_Z"], floorz)
    put(pl + O["PL_VIEWZ"], floorz + (41 << 16))
    put(pl + O["PL_VIEWHEIGHT"], 41 << 16)
    put(pl + O["PL_DELTAVIEWHEIGHT"], 0)


class Lockstep(unittest.TestCase):
    """Both games driven together, compared after every tic."""

    compare = SimDiffTest.compare

    @classmethod
    def setUpClass(cls):
        cls.g = Flat()
        cls.g.boot()
        cls.h = core.Game()
        # (the host library lives as long as the process: a new game keeps
        # the counts of the last, as G_PlayerReborn does)
        cls.h.lib.host_inventory_set(34, 0)
        cls.h.lib.host_inventory_set(35, 0)
        cls.h.init()
        cls.snd0 = (cls.g.byte("_snd_count"), core.ctypes.c_uint8.in_dll(cls.h.lib, "snd_count").value)

    def run_tics(self, seq, start=0):
        for n, (move, buttons, mouse, weapon) in enumerate(seq, start + 1):
            self.g.tic(move, buttons, mouse, weapon)
            self.h.tic(move, buttons, mouse, weapon)
            self.compare(n)

    def load(self, mapnum):
        """Both to map mapnum through game_tic's level loading."""
        g, h = self.g, self.h
        g.mem[g.L["_gamemap"]] = mapnum
        g.mem[g.L["_gameaction"]] = 1                   # ga_loadlevel
        core.ctypes.c_uint8.in_dll(h.lib, "gamemap").value = mapnum
        core.ctypes.c_uint8.in_dll(h.lib, "gameaction").value = 1
        self.run_tics([(0, 0, 0, 0)])


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimMapTest(Lockstep):
    """Another map: E1M8 (the harness's 64 KB holds the level memory of
    E1M1 and E1M8 only, DESIGN.md section 9) loaded by game_tic, then
    walking, turning and shooting."""

    def test_e1m8(self):
        self.load(8)
        self.assertEqual(self.g.byte("_gamemap"), 8)
        seq = ([(KM_FORWARD, 0, 0, 0)] * 30 + [(KM_LEFT, KB_FIRE, 0, 0)] * 20
               + [(KM_FORWARD | KM_STRAFEL, KB_RUN, 25, 0)] * 30 + [(KM_BACK, KB_USE, 0, 0)] * 10)
        self.run_tics(seq)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimBarrelTest(Lockstep):
    """The pistol at a barrel until it explodes: waking a static, damage,
    the death states, the radius attack on the things around (and on the
    player standing near enough)."""

    def test_barrel(self):
        import math
        g, h = self.g, self.h
        geo = core.MapGeo("E1M1")
        barrels = [t for t in h.things() if t["type"] == core.TYPE["MT_BARREL"]]
        spot = None
        for b in barrels:
            bx, by = b["x"] / 65536, b["y"] / 65536
            for k in range(8):
                a = k * math.pi / 4
                px, py = bx + 96 * math.cos(a), by + 96 * math.sin(a)
                if h.sector_at(px, py) == b["sector"] and core.lines_clear(geo, px, py, bx, by):
                    spot = (round(px), round(py), core.bam(bx - px, by - py) & 0xFFFF)
                    break
            if spot:
                break
        self.assertIsNotNone(spot, "no barrel with a clear shot")
        flat_place(g, *spot)
        h.place(*spot)
        self.compare(0)
        self.run_tics([(0, KB_FIRE, 0, 0)] * 70)
        dead = [t for t in h.things() if t["type"] == core.TYPE["MT_BARREL"]
                and t["state"] >= core.STATES["S_BEXP"]]
        self.assertTrue(dead, "the barrel exploded")


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimMonstersTest(Lockstep):
    """The monsters part in lockstep: the pistol fired at a few spots of
    E1M1 wakes the monsters that hear it (and those that see the player),
    then the player stands still while they come, chase, shoot, claw and
    throw fireballs, fight each other, and maybe kill him. The cycles of
    those tics are the many-monster measurement of DESIGN.md section 9."""

    def spots(self):
        """Item positions spread over the map (walkable places)."""
        items = [t for t in self.h.things() if t["static"] and t["type"] in
                 (core.TYPE["MT_MISC2"], core.TYPE["MT_MISC3"])]
        items.sort(key=lambda t: (t["x"], t["y"]))
        pick = [items[i * (len(items) - 1) // 3] for i in range(4)]
        return [(t["x"] >> 16, t["y"] >> 16) for t in pick]

    def test_monsters(self):
        g, h = self.g, self.h
        n = 0
        for x, y in self.spots():
            flat_place(g, x, y, 0)
            h.place(x, y, 0)
            seq = [(0, KB_FIRE, 0, 0)] * 24
            self.run_tics(seq, n)
            n += len(seq)
        woke = sum(1 for t in h.things() if not t["static"] and t["type"] in
                   (core.TYPE[k] for k in ("MT_POSSESSED", "MT_SHOTGUY", "MT_TROOP", "MT_SERGEANT")))
        costs = []
        for tic in range(300):
            costs.append(g.tic())
            h.tic()
            self.compare(n + tic + 1)
        MEASURE["monsters awake after the shots (E1M1)"] = woke
        MEASURE["tic cycles, monsters awake: mean / p90 / max"] = \
            f"{sum(costs) // len(costs)} / {sorted(costs)[len(costs) * 9 // 10]} / {max(costs)}"
        self.assertGreater(woke, 5)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimPickupTest(Lockstep):
    """Every kind of pickup E1M1 has, walked onto in turn (statics seen
    through P_StaticView, removed), in lockstep."""

    def test_pickups(self):
        g, h = self.g, self.h
        kinds = {}
        for t in h.things():
            if t["static"] and t["flags"] & 1:          # MF_SPECIAL
                kinds.setdefault(t["type"], []).append(t)
        n = 0
        for typ, ts in sorted(kinds.items()):
            for t in ts[:3]:
                flat_place(g, t["x"] >> 16, t["y"] >> 16, 0)
                h.place(t["x"] >> 16, t["y"] >> 16, 0)
                n += 1
                self.run_tics([(0, 0, 0, 0)], n)
        MEASURE["pickup kinds walked onto (E1M1)"] = len(kinds)
        self.assertGreater(len(kinds), 10)


def tearDownModule():
    if MEASURE and ("-v" in sys.argv or os.environ.get("DOOM_MEASURE")):
        print("\nmeasurements (6502 cycles, far accesses charged as the kernel's):")
        for k, v in MEASURE.items():
            print(f"  {k:60s} {v}")


if __name__ == "__main__":
    unittest.main()
