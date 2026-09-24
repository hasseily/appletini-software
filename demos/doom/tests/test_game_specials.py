#!/usr/bin/env python3
"""Tests of the SPECIALS part and the level flow (docs/DESIGN.md section 9).

The host build (the game's C with tests/host/, as tests/test_game_core.py,
plus tests/host/host_spec.c; its own library, build/host/spec) is driven
through game_init and game_tic, as the kernel drives the 6502 build, with
the player placed in front of the lines to use or cross:

  - E1M1's first door (the one nearest the start) opens with use (2 units
    a tic), stays open VDOORWAIT tics, closes, and is free again; the
    renderer's far sector record follows the near heights every tic;
  - a lift (E1M1's SR 62 on the lift's own side, and the WR 88 lines
    around it): down to the lowest neighbouring floor, 3 s, back up; a
    button (E1M3's SR 62 switch 928) shows its other texture for a second;
  - a manual door turned around while it moves;
  - a once-only switch (E1M1's 753, S1 23) changes its texture for good,
    clears its special and lowers its three tagged floors;
  - the exit switch ends the level: the intermission with the tally
    (kills, items, secrets, time, par), a press loads E1M2; E1M3's secret
    exit leads to E1M9; E1M8's exit ends the episode, and a press there
    starts a new game at E1M1;
  - a blue door refuses the player without the key (the "you need a blue
    key" message queued, no mover) and opens with the blue skull key;
  - nukage hurts 5 every 32 tics, not with the radiation suit; a secret
    sector counts once and loses its special;
  - lights: E1M1's strobes and flickers, E1M3's glows and fire flickers,
    change as vanilla's thinkers do; E1M2's scrolling walls move one unit
    a tic;
  - E1M4's teleporter moves the player to its destination with fog;
    E1M3's stairs (S1 7) build step by step;
  - a restart (the player dies and uses) puts the level back as it was:
    heights, textures, line specials, offsets.

The 6502 build of the part (a_spec.s, a_movers.s) runs in lockstep with
the host (the flat py65 harness, tests/host/gamesim.py), compared after
every tic: E1M1's door, switch, floors, lift, blazing door, blue door,
nukage and secret, E1M8's exit and a new game back on E1M1
(SimSpecialsTest, with the cycles of tics with several sectors moving:
the measurements of DESIGN.md section 9); E1M1's exit to E1M2 and E1M2's
lights, scrolling walls, lifts, floors, doors and teleporter
(SimFlowTest); 23 rounds of rewritten line specials for the EV_ routines
E1 does not use, and sector specials spawned at run time
(SimCoverageTest).

Run:  python3 tests/test_game_specials.py [-v]      (needs build/data; minutes)
      python3 tests/test_game_specials.py --profile   (the 6502 routines' cycles)
"""

from __future__ import annotations

import ctypes
import math
import os
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
sys.path.insert(0, str(PROJECT / "tests/host"))
sys.path.insert(0, str(PROJECT / "tools"))
import test_game_core as core  # noqa: E402

DATA = PROJECT / "build/data"
SPECDIR = PROJECT / "build/host/spec"
LIB = SPECDIR / "libspec.so"
MEASURE = {}
KM_FORWARD, KM_BACK = 1, 2
KB_FIRE, KB_USE = 1, 2
GS_LEVEL, GS_INTERMISSION, GS_FINALE = 0, 1, 2
VDOORWAIT = 150
SFX = None


def msg_numbers() -> dict[str, int]:
    """MSG_ names -> numbers, from p_local.h's enum."""
    import re
    text = (PROJECT / "src/game/p_local.h").read_text()
    body = text[text.index("enum { MSG_NONE"):]
    body = body[:body.index("};")]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return {n: i for i, n in enumerate(re.findall(r"(MSG_\w+)", body))}


MSG = msg_numbers()


def build_lib() -> Path:
    """gcc the game with host.c and host_spec.c into build/host/spec."""
    SPECDIR.mkdir(parents=True, exist_ok=True)
    sources = (sorted((PROJECT / "src/game").glob("*.c"))
               + [PROJECT / "tests/host/host.c", PROJECT / "tests/host/host_spec.c"])
    headers = sorted((PROJECT / "src/game").glob("*.h")) + sorted((PROJECT / "tests/host").glob("*.h"))
    newest = max(p.stat().st_mtime for p in sources + headers + [DATA / "doomdata.h"])
    if LIB.is_file() and LIB.stat().st_mtime >= newest:
        return LIB
    tmp = SPECDIR / f"libspec.{os.getpid()}.so"
    cmd = ["gcc", "-shared", "-fPIC", "-O1", "-g", "-Wall", "-Werror", "-Wno-unused-function",
           "-include", str(PROJECT / "tests/host/kernel.h"),
           "-I", str(PROJECT / "tests/host"), "-I", str(PROJECT / "src/game"), "-I", str(DATA),
           "-o", str(tmp)] + [str(s) for s in sources] + ["-lm"]
    subprocess.run(cmd, check=True)
    tmp.replace(LIB)
    return LIB


class Game(core.Game):
    """The host build with the specials' readers (host_spec.c)."""

    def __init__(self):
        self.lib = ctypes.CDLL(str(build_lib()))
        L = self.lib
        L.host_banks.restype = ctypes.POINTER(ctypes.c_uint8)
        L.host_aim.restype = ctypes.c_int32
        L.host_point_sector.restype = ctypes.c_uint16
        L.host_sounds.restype = ctypes.c_uint8
        L.host_player_mo.restype = ctypes.c_void_p
        L.host_damage.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_int]
        if core.Game._banks is None:
            import wad2a2
            core.Game._banks = wad2a2.load_banks(DATA)
        # (the converter's banks afresh; the specials' own bank keeps the
        # sector snapshots of earlier tests in this process, which are the
        # converter's sectors too: the part's state lives as long as the
        # library)
        base = ctypes.addressof(L.host_banks().contents)
        for b, img in core.Game._banks.items():
            ctypes.memmove(base + b * 65536, bytes(img), 65536)
        self.snd = self.snd_count()
        self.sounds_seen = []

    # --- state ------------------------------------------------------------------------------
    def sector(self, s) -> dict:
        v = (ctypes.c_int32 * 10)()
        self.lib.host_sector(s, v)
        return dict(zip(("floor", "ceil", "ffloor", "fceil", "light", "fspecial", "floorpic",
                         "special", "busy", "tag"), v))

    def side(self, sd) -> dict:
        v = (ctypes.c_int32 * 4)()
        self.lib.host_side(sd, v)
        return dict(zip(("xoffset", "top", "bottom", "mid"), v))

    def line_special(self, li) -> int:
        return self.lib.host_line_special(li)

    def line_side(self, li, side=0) -> int:
        return self.lib.host_line_side(li, side)

    def movers(self) -> dict:
        v = (ctypes.c_int32 * 4)()
        self.lib.host_movers(v)
        return dict(zip(("doors", "floors", "plats", "ceilings"), v))

    def flow(self) -> dict:
        v = (ctypes.c_int32 * 21)()
        self.lib.host_flow(v)
        return dict(zip(("gamestate", "gamemap", "gameaction", "wi_tics", "epsd", "last", "next",
                         "didsecret", "maxkills", "maxitems", "maxsecret", "kills", "items",
                         "secret", "time", "partime", "pkills", "pitems", "psecret",
                         "totalsecret", "leveltics"), v))

    def messages(self) -> list[int]:
        out = []
        while (m := self.lib.host_next_message()):
            out.append(m)
        return out

    def snd_count(self) -> int:
        return ctypes.c_uint8.in_dll(self.lib, "snd_count").value

    def tic(self, move=0, buttons=0, mouse=0, weapon=0, n=1):
        for _ in range(n):
            super().tic(move, buttons, mouse, weapon)
            c = self.snd_count()
            last = (ctypes.c_uint8 * 8).in_dll(self.lib, "snd_last")
            for k in range((c - self.snd) & 0xFF):
                self.sounds_seen.append(last[(self.snd + k) & 7])
            self.snd = c

    def init(self):
        """game_init, then a tic without buttons: the new player's use and
        fire count as held until released (G_PlayerReborn)."""
        super().init()
        self.tic()

    def use(self):
        """One tic with use pressed, one released (a new press each call)."""
        self.tic(buttons=KB_USE)
        self.tic()

    def map_banks_changed(self, mapname) -> list[int]:
        """The banks of a map that differ from the converter's images."""
        import json
        banks = json.loads((DATA / "manifest.json").read_text())["maps"][mapname]["banks"]
        base = ctypes.addressof(self.lib.host_banks().contents)
        return [b for b in banks
                if ctypes.string_at(base + b * 65536, 65536) != bytes(core.Game._banks[b])]

    def goto_map(self, mapnum):
        """game_tic's own level load (as a restart of that map)."""
        ctypes.c_uint8.in_dll(self.lib, "gamemap").value = mapnum
        ctypes.c_uint8.in_dll(self.lib, "gameaction").value = 1        # ga_loadlevel
        self.tic()
        assert self.flow()["gamemap"] == mapnum


def sfx_numbers() -> dict[str, int]:
    import re
    text = (PROJECT / "src/game/info.h").read_text()
    body = text[text.index("#define NUMSFX"):]
    body = body[body.index("enum {") + 6:body.index("};")]
    return {n: i for i, n in enumerate(re.findall(r"(sfx_\w+)", body))}


SFX = sfx_numbers()


class Geo(core.MapGeo):
    def use_spot(self, line, dist=24):
        """A point dist units in front of the line's middle (its front side)
        and the angle facing the line."""
        li = self.lines[line]
        (ax, ay), (bx, by) = self.ends(li)
        length = math.hypot(bx - ax, by - ay)
        # vanilla's front side is on the right of v1 -> v2
        nx, ny = (by - ay) / length, -(bx - ax) / length
        mx, my = (ax + bx) / 2, (ay + by) / 2
        return round(mx + nx * dist), round(my + ny * dist), core.bam(-nx, -ny)

    def lines_with(self, special):
        return [i for i, li in enumerate(self.lines) if li.special == special]

    def inside(self, g, sector, margin=20):
        """A point well inside the sector (the player fits there)."""
        s = self.sectors[sector]
        pts = []
        for li in self.lines:
            if sector in (li.frontsector, li.backsector):
                pts += list(self.ends(li))
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        best = None
        for i in range(1, 16):
            for j in range(1, 16):
                x, y = x0 + (x1 - x0) * i / 16, y0 + (y1 - y0) * j / 16
                if all(g.sector_at(x + dx, y + dy) == sector
                       for dx in (-margin, 0, margin) for dy in (-margin, 0, margin)):
                    d = abs(i - 8) + abs(j - 8)
                    if best is None or d < best[0]:
                        best = (d, round(x), round(y))
        assert best, f"no room in sector {sector} ({s})"
        return best[1], best[2]


def nearest_door(geo) -> int:
    """E1M1's door (special 1) nearest the player's start."""
    start = next(t for t in geo.things if t.type == 1)
    best = None
    for i in geo.lines_with(1):
        (ax, ay), (bx, by) = geo.ends(geo.lines[i])
        d = math.hypot((ax + bx) / 2 - start.x, (ay + by) / 2 - start.y)
        if geo.sectors[geo.lines[i].frontsector].floorheight != \
                geo.sectors[geo.lines[i].backsector].floorheight:
            continue
        if best is None or d < best[0]:
            best = (d, i)
    return best[1]


# --- the tests ---------------------------------------------------------------------------------
@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class DoorTest(unittest.TestCase):
    def test_first_door(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        line = nearest_door(geo)
        li = geo.lines[line]
        door = li.backsector
        s0 = g.sector(door)
        self.assertEqual(s0["floor"], s0["ceil"], "the door is closed")
        top = min(geo.sectors[l.frontsector if l.backsector == door else l.backsector].ceilingheight
                  for l in geo.lines if door in (l.frontsector, l.backsector)
                  and l.backsector != 0xFFFF and l.frontsector != l.backsector) - 4
        g.place(*geo.use_spot(line))
        g.tic(buttons=KB_USE)
        self.assertEqual(g.movers()["doors"], 1)
        self.assertIn(SFX["sfx_doropn"], g.sounds_seen)
        heights = [g.sector(door)]
        for _ in range(400):
            g.tic()
            heights.append(g.sector(door))
            if not heights[-1]["busy"]:
                break
        ceils = [h["ceil"] for h in heights]
        for h in heights:
            self.assertEqual((h["ffloor"], h["fceil"]), (h["floor"], h["ceil"]),
                             "the renderer's record follows")
        self.assertEqual(ceils[0], s0["ceil"] + 2, "2 units a tic from the first tic")
        self.assertEqual(max(ceils), top, "4 below the lowest neighbouring ceiling")
        at_top = sum(1 for c in ceils if c == top)
        self.assertEqual(at_top, VDOORWAIT + 2, "opened, waited VDOORWAIT tics, then closed")
        self.assertEqual(ceils[-1], s0["floor"], "closed again")
        self.assertFalse(heights[-1]["busy"])
        self.assertEqual(g.movers()["doors"], 0)
        self.assertIn(SFX["sfx_dorcls"], g.sounds_seen)
        MEASURE["E1M1 first door: line / tics open-wait-close"] = f"{line} / {len(ceils)}"

    def test_door_turns_around(self):
        """Using a closing raise door sends it back up; the player under a
        closing door stops it (it goes back up)."""
        g, geo = Game(), Geo("E1M1")
        g.init()
        line = nearest_door(geo)
        door = geo.lines[line].backsector
        g.place(*geo.use_spot(line))
        g.use()
        g.tic(n=20)
        c = g.sector(door)["ceil"]
        g.use()                         # rising: the player closes it
        g.tic(n=3)
        self.assertLess(g.sector(door)["ceil"], c + 2)
        g.use()                         # closing: back up
        g.tic(n=3)
        self.assertGreater(g.sector(door)["ceil"], g.sector(door)["floor"])
        rising = g.sector(door)["ceil"]
        g.tic()
        self.assertEqual(g.sector(door)["ceil"], rising + 2)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class LiftTest(unittest.TestCase):
    def test_switch_lift(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        line = 594                      # SR 62 on tag 1: the lift sector 98
        self.assertEqual(geo.lines[line].special, 62)
        lift = geo.lines[line].backsector
        f0 = g.sector(lift)["floor"]
        low = min(geo.sectors[l.frontsector if l.backsector == lift else l.backsector].floorheight
                  for l in geo.lines if lift in (l.frontsector, l.backsector)
                  and l.backsector != 0xFFFF and l.frontsector != l.backsector)
        side = g.line_side(line)
        tex0 = g.side(side)
        g.place(*geo.use_spot(line))
        g.tic(buttons=KB_USE)
        # (Freedoom's lift side is PLAT1, no switch texture: nothing to swap)
        self.assertEqual(g.side(side), tex0)
        self.assertEqual(g.movers()["plats"], 1)
        floors = [g.sector(lift)["floor"]]
        for _ in range(300):
            g.tic()
            floors.append(g.sector(lift)["floor"])
            if not g.sector(lift)["busy"]:
                break
        self.assertEqual(floors[0], f0 - 4, "down 4 units a tic")
        self.assertEqual(min(floors), low)
        self.assertEqual(sum(1 for f in floors if f == low), 35 * 3 + 2, "waits 3 s")
        self.assertEqual(floors[-1], f0, "back up")
        self.assertEqual(g.movers()["plats"], 0)
        self.assertEqual(g.line_special(line), 62, "a repeatable switch keeps its special")
        # and it works again
        g.use()
        self.assertTrue(g.sector(lift)["busy"])

    def test_button(self):
        """E1M3's SR 62 switch 928 (SW1COMP): pressed, the other texture for
        a second, then back; the lift it starts runs meanwhile."""
        g = Game()
        g.init()
        g.goto_map(3)
        geo = Geo("E1M3")
        line = 928
        self.assertEqual(geo.lines[line].special, 62)
        side = g.line_side(line)
        tex0 = g.side(side)
        g.place(*geo.use_spot(line))
        g.tic()
        g.tic(buttons=KB_USE)
        tex1 = g.side(side)
        self.assertNotEqual(tex1["mid"], tex0["mid"], "the switch shows its other texture")
        self.assertGreaterEqual(g.movers()["plats"], 1)
        texs = []
        for _ in range(40):
            g.tic()
            texs.append(g.side(side))
        back = next(i for i, t in enumerate(texs) if t == tex0)
        # BUTTONTIME (35) counts the tic of the press, as vanilla's
        self.assertEqual(back, 35 - 2, "the button comes back after BUTTONTIME tics")
        self.assertIn(SFX["sfx_swtchn"], g.sounds_seen)

    def test_walk_over_lift(self):
        """WR 88 around the same lift: a monster or the player crossing it."""
        g, geo = Game(), Geo("E1M1")
        g.init()
        line = 593
        self.assertEqual(geo.lines[line].special, 88)
        x, y, a = geo.use_spot(line, 40)
        g.place(x, y, a)
        for _ in range(40):
            g.tic(move=KM_FORWARD)
            if g.sector(98)["busy"]:
                break
        self.assertTrue(g.sector(98)["busy"], "crossing started the lift")
        self.assertEqual(g.line_special(line), 88)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SwitchTest(unittest.TestCase):
    def test_once_switch_lowers_tagged_floors(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        line = 753                      # S1 23: lower floors to lowest, tag 3
        self.assertEqual((geo.lines[line].special, geo.lines[line].tag), (23, 3))
        tagged = [i for i, s in enumerate(geo.sectors) if s.tag == 3]
        before = {s: g.sector(s)["floor"] for s in tagged}
        side = g.line_side(line)
        tex0 = g.side(side)
        g.place(*geo.use_spot(line))
        g.use()
        self.assertNotEqual(g.side(side), tex0)
        self.assertEqual(g.line_special(line), 0, "used up")
        self.assertEqual(g.movers()["floors"], len(tagged))
        g.tic(n=400)
        for s in tagged:
            want = min(geo.sectors[l.frontsector if l.backsector == s else l.backsector].floorheight
                       for l in geo.lines if s in (l.frontsector, l.backsector)
                       and l.backsector != 0xFFFF and l.frontsector != l.backsector)
            want = min(want, before[s])
            self.assertEqual(g.sector(s)["floor"], want, f"sector {s}")
            self.assertEqual(g.sector(s)["ffloor"], want)
        self.assertEqual(g.movers()["floors"], 0)
        self.assertNotEqual(g.side(side), tex0, "stays switched")
        self.assertIn(SFX["sfx_swtchn"], g.sounds_seen)
        self.assertIn(SFX["sfx_pstop"], g.sounds_seen)
        # used up: nothing more
        g.use()
        self.assertEqual(g.movers()["floors"], 0)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class LevelFlowTest(unittest.TestCase):
    def test_exit_intermission_next_map(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        line = geo.lines_with(11)[0]
        side = g.line_side(line)
        tex0 = g.side(side)
        g.place(*geo.use_spot(line))
        g.tic(n=10)
        g.tic(buttons=KB_USE)
        self.assertEqual(g.flow()["gameaction"], 2, "ga_completed")
        self.assertNotEqual(g.side(side), tex0)
        g.tic(buttons=KB_USE)           # (still held)
        f = g.flow()
        self.assertEqual(f["gamestate"], GS_INTERMISSION)
        self.assertEqual((f["epsd"], f["last"], f["next"], f["didsecret"]), (1, 1, 2, 0))
        self.assertEqual(f["partime"], 30)
        self.assertEqual(f["time"], 12)
        self.assertEqual(f["maxsecret"], 4)
        self.assertEqual(f["maxkills"], g.counts()["totalkills"])
        self.assertEqual(f["maxitems"], g.counts()["totalitems"])
        g.tic(buttons=KB_USE, n=30)     # held: no new press
        self.assertEqual(g.flow()["gamestate"], GS_INTERMISSION)
        g.tic()
        g.tic(buttons=KB_FIRE)          # a new press
        g.tic()
        f = g.flow()
        self.assertEqual((f["gamestate"], f["gamemap"]), (GS_LEVEL, 2))
        self.assertGreater(g.counts()["statics_used"], 50, "E1M2's things")
        # E1M1's lines and sidedefs are as the converter made them again
        # (its sectors come back from their snapshot when it is loaded)
        sectors_bank = __import__("json").loads((DATA / "manifest.json").read_text())[
            "maps"]["E1M1"]["arrays"]["SECTORS"]["bank"]
        self.assertEqual(set(g.map_banks_changed("E1M1")) - {sectors_bank}, set())

    def test_secret_exit_e1m3_to_e1m9(self):
        g = Game()
        g.init()
        g.goto_map(3)
        geo = Geo("E1M3")
        line = geo.lines_with(51)[0]
        g.place(*geo.use_spot(line))
        g.use()
        g.tic()
        f = g.flow()
        self.assertEqual((f["gamestate"], f["last"], f["next"], f["didsecret"]),
                         (GS_INTERMISSION, 3, 9, 1))
        g.use()
        g.tic()
        self.assertEqual(g.flow()["gamemap"], 9)
        self.assertEqual(g.flow()["gamestate"], GS_LEVEL)

    def test_e1m8_ends_episode(self):
        g = Game()
        g.init()
        g.goto_map(8)
        geo = Geo("E1M8")
        line = geo.lines_with(52)[0]
        g.place(*geo.use_spot(line, 20))
        for _ in range(30):
            g.tic(move=KM_FORWARD)
            if g.flow()["gamestate"] != GS_LEVEL:
                break
        f = g.flow()
        self.assertEqual(f["gamestate"], GS_FINALE, "E1M8's exit ends the episode")
        self.assertEqual(f["last"], 8)
        g.tic(n=10)
        self.assertEqual(g.flow()["gamestate"], GS_FINALE, "waits for a press")
        g.tic(buttons=KB_USE)
        g.tic()
        f = g.flow()
        self.assertEqual((f["gamestate"], f["gamemap"]), (GS_LEVEL, 1), "a new game")
        p = g.player()
        self.assertEqual((p["health"], p["readyweapon"], p["clip"]), (100, 1, 50))

    def test_restart_restores_the_level(self):
        """Things changed, then the player dies and restarts: the far
        records are as the converter made them."""
        g, geo = Game(), Geo("E1M1")
        g.init()
        banks0 = {b: bytes(img) for b, img in core.Game._banks.items()}
        door_line = nearest_door(geo)
        door = geo.lines[door_line].backsector
        g.place(*geo.use_spot(door_line))
        g.use()
        g.tic(n=10)
        g.place(*geo.use_spot(753))     # the once-only switch
        g.use()
        g.place(*geo.use_spot(594))     # the lift's button
        g.use()
        g.tic(n=5)
        self.assertNotEqual(g.sector(door)["ceil"], geo.sectors[door].ceilingheight)
        self.assertEqual(g.line_special(753), 0)
        # dies, uses: reborn, the level again
        self.assertEqual(g.lib.host_damage(g.lib.host_player_mo(), None, None, 1000), 0)
        g.tic(n=40)
        self.assertEqual(g.player()["playerstate"], 1, "dead")
        g.tic(buttons=KB_USE)
        g.tic()
        self.assertEqual(g.player()["playerstate"], 0)
        self.assertEqual(g.player()["health"], 100)
        self.assertEqual(g.flow()["gamemap"], 1)
        # every bank as the converter made it, but for what the new level's
        # first tic did: the lights (their level, and the special that
        # their spawn clears), in the sectors that have them
        import json
        sec = json.loads((DATA / "manifest.json").read_text())["maps"]["E1M1"]["arrays"]["SECTORS"]
        lit = {i for i, s in enumerate(geo.sectors) if s.special in (1, 2, 3, 4, 8, 12, 13, 17)}
        base = ctypes.addressof(g.lib.host_banks().contents)
        for b, img in banks0.items():
            now = ctypes.string_at(base + b * 65536, 65536)
            for a in (a for a in range(65536) if now[a] != img[a]):
                i, off = divmod(a - sec["addr"], 16)
                self.assertTrue(b == sec["bank"] and i in lit and off in (8, 9),
                                f"bank {b} ${a:04X} differs")


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class LockedDoorTest(unittest.TestCase):
    def test_blue_door(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        line = 421
        self.assertEqual(geo.lines[line].special, 26)
        door = geo.lines[line].backsector
        g.place(*geo.use_spot(line))
        g.messages()
        g.use()
        self.assertFalse(g.sector(door)["busy"])
        self.assertEqual(g.movers()["doors"], 0)
        self.assertEqual(g.messages(), [MSG["MSG_PD_BLUEK"]])
        self.assertIn(SFX["sfx_oof"], g.sounds_seen)
        g.lib.host_card(3, 1)           # the blue skull key opens it too
        g.use()
        self.assertTrue(g.sector(door)["busy"])
        self.assertEqual(g.messages(), [])
        g.tic(n=30)
        self.assertGreater(g.sector(door)["ceil"], g.sector(door)["floor"])


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SectorTest(unittest.TestCase):
    def test_nukage(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        nukage = [i for i, s in enumerate(geo.sectors) if s.special == 7]
        x, y = geo.inside(g, nukage[0])
        g.place(x, y, 0)

        def hits(n):
            """the floor's damage: health lost in tics that end with
            leveltime % 32 == 1 (the monsters may hurt too, at other tics)"""
            out = []
            for _ in range(n):
                h = g.lib.host_health()
                g.tic()
                if g.counts()["leveltime"] % 32 == 1:
                    out.append(h - g.lib.host_health())
            return out

        self.assertEqual(hits(64), [5, 5], "5 every 32 tics")
        g.lib.host_power(3, 1000)       # pw_ironfeet
        self.assertEqual(hits(64), [0, 0], "the radiation suit protects")

    def test_secret(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        self.assertEqual(g.flow()["totalsecret"], 4)
        secret = [i for i, s in enumerate(geo.sectors) if s.special == 9][0]
        x, y = geo.inside(g, secret, 16)
        g.place(x, y, 0)
        g.tic()
        self.assertEqual(g.flow()["psecret"], 1)
        s = g.sector(secret)
        self.assertEqual((s["special"], s["fspecial"]), (0, 0))
        g.tic(n=5)
        self.assertEqual(g.flow()["psecret"], 1, "counted once")

    def test_lights(self):
        g, geo = Game(), Geo("E1M1")
        g.init()
        strobe = [i for i, s in enumerate(geo.sectors) if s.special == 12][0]
        flicker = [i for i, s in enumerate(geo.sectors) if s.special == 1][0]
        seq, fl = [], []
        for _ in range(200):
            g.tic()
            seq.append(g.sector(strobe)["light"])
            fl.append(g.sector(flicker)["light"])
        hi = geo.sectors[strobe].lightlevel
        self.assertEqual(max(seq), hi)
        runs = []
        for v in seq:
            if runs and runs[-1][0] == v:
                runs[-1][1] += 1
            else:
                runs.append([v, 1])
        # sync strobe slow: dark 35 tics, bright 5 (the first run is partial)
        self.assertEqual({(v == hi, n) for v, n in runs[1:-1]}, {(True, 5), (False, 35)})
        self.assertEqual(g.sector(strobe)["special"], 0, "no special during play")
        self.assertEqual(len(set(fl)), 2, "a flicker between two levels")

    def test_glow_and_fire(self):
        g = Game()
        g.init()
        g.goto_map(3)
        geo = Geo("E1M3")
        def darkest(i):
            return min(geo.sectors[l.frontsector if l.backsector == i else l.backsector].lightlevel
                       for l in geo.lines if i in (l.frontsector, l.backsector)
                       and l.backsector != 0xFFFF and l.frontsector != l.backsector)
        glow = [i for i, s in enumerate(geo.sectors) if s.special == 8
                and darkest(i) < s.lightlevel][0]
        fire = [i for i, s in enumerate(geo.sectors) if s.special == 17][0]
        gs, fs = [], []
        for _ in range(120):
            g.tic()
            gs.append(g.sector(glow)["light"])
            fs.append(g.sector(fire)["light"])
        steps = {abs(a - b) for a, b in zip(gs, gs[1:])}
        self.assertEqual(steps, {0, 8}, "a glow moves 8 a tic (and waits a tic to turn)")
        self.assertLess(max(gs), geo.sectors[glow].lightlevel)
        self.assertGreaterEqual(max(gs), geo.sectors[glow].lightlevel - 8)
        self.assertGreater(min(gs), darkest(glow))
        self.assertLessEqual(min(gs), darkest(glow) + 8)
        # vanilla T_FireFlicker: max - 16 * (0..3), or its minimum (the
        # darkest neighbour + 16, which vanilla lets exceed the maximum)
        fire_max = geo.sectors[fire].lightlevel
        fire_min = min(fire_max, darkest(fire)) + 16
        self.assertTrue(all(v == fire_min or (fire_max - v) in (0, 16, 32, 48) for v in fs))
        self.assertGreater(len(set(fs)), 1)

    def test_scrolling_walls(self):
        g = Game()
        g.init()
        g.goto_map(2)
        geo = Geo("E1M2")
        lines = geo.lines_with(48)
        self.assertTrue(lines)
        sides = [g.line_side(li) for li in lines]
        x0 = [g.side(sd)["xoffset"] for sd in sides]
        g.tic(n=10)
        x1 = [g.side(sd)["xoffset"] for sd in sides]
        self.assertEqual([b - a for a, b in zip(x0, x1)], [10] * len(sides))


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class TeleportStairsTest(unittest.TestCase):
    def test_teleport(self):
        g = Game()
        g.init()
        g.goto_map(4)
        geo = Geo("E1M4")
        for line in geo.lines_with(97):
            g.goto_map(4)
            x, y, a = geo.use_spot(line, 24)
            if g.sector_at(x, y) != geo.lines[line].frontsector:
                continue
            g.place(x, y, a)
            p0 = g.player()
            for _ in range(10):
                g.tic(move=KM_FORWARD)
                if math.hypot(g.player()["x"] - p0["x"], g.player()["y"] - p0["y"]) > 128 * 65536:
                    break
            p = g.player()
            if math.hypot(p["x"] - p0["x"], p["y"] - p0["y"]) > 128 * 65536:
                fogs = [t for t in g.things() if t["type"] == core.TYPE["MT_TFOG"]]
                self.assertEqual(len(fogs), 2)
                self.assertIn(SFX["sfx_telept"], g.sounds_seen)
                self.assertEqual(g.line_special(line), 97, "a WR teleporter stays")
                MEASURE["E1M4 teleporter used"] = line
                return
        self.fail("no teleporter line took the player")

    def test_stairs(self):
        g = Game()
        g.init()
        g.goto_map(3)
        geo = Geo("E1M3")
        line = geo.lines_with(7)[0]
        tag = geo.lines[line].tag
        first = [i for i, s in enumerate(geo.sectors) if s.tag == tag]
        g.place(*geo.use_spot(line))
        g.use()
        n = g.movers()["floors"]
        self.assertGreaterEqual(n, 2, "a step and the next")
        g.tic(n=40 * n)
        self.assertEqual(g.movers()["floors"], 0)
        for s in first:
            self.assertEqual(g.sector(s)["floor"], geo.sectors[s].floorheight + 8)
        MEASURE["E1M3 stairs: steps"] = n



# --- the 6502 build in lockstep ---------------------------------------------------------------
# The whole game with the specials' assembly, in the flat harness
# (tests/host/gamesim.py, flat.cfg: the specials' code shares the C
# modules' code window, aspec.inc SPECCODE). With GAME.BIN's level-data
# caches only E1M1 and E1M8 fit the 64 KB with their level memory; with
# the half-size caches of the core's first measurements, E1M2 and E1M5
# fit too (tic costs pessimistic for that).
FLATDIR = PROJECT / "build/host/spec_flat"
FLATDIR_HALF = PROJECT / "build/host/spec_flat_half"
HALF_CACHES = ["-D", "LINECACHE=32", "-D", "CELLCACHE=8", "-D", "NODECACHE=64"]


def build_flat(half=False) -> Path:
    import gamesim
    out = FLATDIR_HALF if half else FLATDIR
    gamesim.build(out, asmdefs=gamesim.ASMDEFS + (HALF_CACHES if half else []))
    return out


def _flat_class():
    import test_game_sim as sim

    class SpecFlat(sim.Flat):
        """The flat 6502 game with the specials' readers (as host_spec.c's)."""

        def levarr(self, arr):
            a = self.L["_levarr"] + 10 * arr
            m = self.mem
            return m[a], m[a + 1] | m[a + 2] << 8, m[a + 3], m[a + 5], m[a + 6] | m[a + 7] << 8

        def far(self, arr, i, off, n):
            bank, addr, size, log2, mask = self.levarr(arr)
            b = self.bank(bank + (i >> log2))
            a = addr + (i & mask) * size + off
            return bytes(b[a:a + n])

        def sector(self, s):
            fl = sim.s16(self.u16(self.u16(self.L["_sec_floorh"]) + 2 * s))
            ce = sim.s16(self.u16(self.u16(self.L["_sec_ceilh"]) + 2 * s))
            r = self.far(6, s, 0, 12)               # MAPARR_SECTORS
            busy = self.u8(self.u16(self.L["_sec_busy"]) + (s >> 3)) >> (s & 7) & 1
            return dict(floor=fl, ceil=ce, ffloor=sim.s16(r[0] | r[1] << 8),
                        fceil=sim.s16(r[2] | r[3] << 8), light=r[8], fspecial=r[9],
                        floorpic=r[4] | r[5] << 8,
                        special=self.u8(self.u16(self.L["_sec_special"]) + s), busy=busy,
                        tag=r[10] | r[11] << 8)

        def side(self, sd):
            r = self.far(4, sd, 0, 10)              # MAPARR_SIDEDEFS
            w = [r[k] | r[k + 1] << 8 for k in range(0, 10, 2)]
            return dict(xoffset=sim.s16(w[0]), top=w[2], bottom=w[3], mid=w[4])

        def line_special(self, li):
            return self.far(5, li, 6, 1)[0]         # LINEDEF_SPECIAL

        def flow(self):
            L, m = self.L, self.mem
            w = L["_wminfo"]
            s16w = lambda o: sim.s16(self.u16(w + o))   # noqa: E731
            return dict(gamestate=m[L["_gamestate"]], gamemap=m[L["_gamemap"]],
                        gameaction=m[L["_gameaction"]], epsd=m[w], last=m[w + 1], next=m[w + 2],
                        didsecret=m[w + 3], maxkills=s16w(4), maxitems=s16w(6),
                        maxsecret=s16w(8), kills=s16w(10), items=s16w(12), secret=s16w(14),
                        time=int.from_bytes(m[w + 16:w + 20], "little"), partime=self.u16(w + 20))

    return sim, SpecFlat


class Lockstep(unittest.TestCase):
    """The flat 6502 build and the host C booted together (game_init),
    driven with the same input and places, compared after every tic: what
    tests/test_game_sim.py compares (the player, every thing, the random
    index, sounds), and every sector (near heights; the far record's
    heights, light, special, flat), every sidedef and special of the lines
    with specials, the level flow."""

    half = False                    # the half-size level-data caches (more maps fit)

    @classmethod
    def setUpClass(cls):
        sim, SpecFlat = _flat_class()
        cls.sim = sim
        cls.g = SpecFlat(build_flat(cls.half))
        cls.boot = cls.g.boot()
        cls.h = Game()
        cls.h.lib.host_inventory_set(34, 0)
        cls.h.lib.host_inventory_set(35, 0)
        cls.h.init()
        cls.g.tic()                                 # (Game.init's idle tic)
        cls.snd0 = (cls.g.byte("_snd_count"), cls.h.snd_count())
        cls.n = 0

    def compare(self, what=""):
        g, h = self.g, self.h
        where = f"tic {self.n}{': ' + what if what else ''}"
        self.sim.SimDiffTest.compare(self, self.n)
        for s in range(self.nsectors):
            self.assertEqual(g.sector(s), h.sector(s), f"{where}: sector {s}")
        for sd in self.sides:
            self.assertEqual(g.side(sd), h.side(sd), f"{where}: sidedef {sd}")
        for li in self.special_lines:
            self.assertEqual(g.line_special(li), h.line_special(li), f"{where}: line {li}")
        # (the tally only once a level ended: the host library's carries
        # over from the earlier tests of the process)
        hf, gf = h.flow(), g.flow()
        keys = gf if gf["gamestate"] != GS_LEVEL else ("gamestate", "gamemap", "gameaction")
        self.assertEqual({k: gf[k] for k in keys}, {k: hf[k] for k in keys},
                         where + ": the level flow")

    def watch(self, mapname):
        """The sectors, and the lines with specials and their sidedefs."""
        geo = Geo(mapname)
        self.nsectors = len(geo.sectors)
        self.special_lines = [i for i, li in enumerate(geo.lines) if li.special]
        self.sides = sorted({self.h.line_side(i) for i in self.special_lines})
        return geo

    def run_tics(self, seq, costs=None):
        for move, buttons in seq:
            c = self.g.tic(move, buttons)
            self.h.tic(move, buttons)
            self.n += 1
            if costs is not None:
                costs.append(c)
            self.compare()

    def place(self, x, y, a):
        self.sim.flat_place(self.g, x, y, a)
        self.h.place(x, y, a)

    def use_line(self, geo, line):
        self.place(*geo.use_spot(line))
        self.run_tics([(0, 0), (0, KB_USE), (0, 0)])



@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimSpecialsTest(Lockstep):
    """The 6502 build (a_spec.s, a_movers.s) against the host C, tic by
    tic: E1M1's first door, its once-only switch and the floors it lowers,
    its lift, its blazing door, the blue door refused, nukage and a
    secret; then E1M8's exit, the episode's end and a new game back on
    E1M1 (P_ResetLevelData: the journal played back, the sectors from
    their snapshot, and E1M1's banks equal on both sides). The cycles of
    tics with several sectors moving are the measurements of DESIGN.md
    section 9."""

    def test_e1m1_then_e1m8_and_back(self):
        MEASURE["6502 boot + E1M1 set-up (cycles)"] = self.boot
        geo = self.watch("E1M1")
        self.compare("start")
        idle = []
        self.run_tics([(0, 0)] * 30, idle)
        door = nearest_door(geo)
        self.use_line(geo, door)
        self.use_line(geo, 753)                     # S1 23: three floors
        self.use_line(geo, 594)                     # SR 62: the lift
        self.use_line(geo, 1162)                    # DR 117: a blazing door
        self.use_line(geo, 421)                     # the blue door, no key
        movers = self.h.movers()
        moving = []
        self.run_tics([(0, 0)] * 120, moving)
        MEASURE["E1M1 movers started (doors, floors, plats)"] = \
            f"{movers['doors']}, {movers['floors']}, {movers['plats']}"
        MEASURE["tic cycles, idle: mean / max"] = f"{sum(idle) // len(idle)} / {max(idle)}"
        MEASURE["tic cycles, 6 sectors moving (first 60 tics): mean / max"] = \
            f"{sum(moving[:60]) // 60} / {max(moving[:60])}"
        self.assertGreaterEqual(sum(movers.values()), 6)
        # nukage, a secret
        nukage = [i for i, s in enumerate(geo.sectors) if s.special == 7][0]
        self.place(*geo.inside(self.h, nukage), 0)
        self.run_tics([(0, 0)] * 40)
        secret = [i for i, s in enumerate(geo.sectors) if s.special == 9][0]
        self.place(*geo.inside(self.h, secret, 16), 0)
        self.run_tics([(0, 0)] * 3)
        self.assertEqual(self.h.flow()["psecret"], 1)
        # E1M8: its exit ends the episode; a press, a new game on E1M1
        self.g.mem[self.g.L["_gamemap"]] = 8
        self.g.mem[self.g.L["_gameaction"]] = 1
        ctypes.c_uint8.in_dll(self.h.lib, "gamemap").value = 8
        ctypes.c_uint8.in_dll(self.h.lib, "gameaction").value = 1
        load = []
        self.run_tics([(0, 0)], load)
        MEASURE["tic cycles, E1M8 loaded by game_tic (undo E1M1, snapshot, set-up)"] = load[0]
        geo8 = self.watch("E1M8")
        self.compare("E1M8")
        exit_line = geo8.lines_with(52)[0]
        self.place(*geo8.use_spot(exit_line, 20))
        for _ in range(30):
            self.run_tics([(KM_FORWARD, 0)])
            if self.h.flow()["gamestate"] != GS_LEVEL:
                break
        self.assertEqual(self.h.flow()["gamestate"], GS_FINALE)
        self.run_tics([(0, 0)] * 5 + [(0, KB_USE)])
        load = []
        self.run_tics([(0, 0)], load)
        MEASURE["tic cycles, a new game: E1M1 back from its snapshot"] = load[0]
        self.assertEqual((self.h.flow()["gamestate"], self.h.flow()["gamemap"]), (GS_LEVEL, 1))
        self.watch("E1M1")
        self.compare("E1M1 again")
        import json
        base = ctypes.addressof(self.h.lib.host_banks().contents)
        for b in json.loads((DATA / "manifest.json").read_text())["maps"]["E1M1"]["banks"]:
            self.assertEqual(bytes(self.g.bank(b)), ctypes.string_at(base + b * 65536, 65536),
                             f"E1M1's bank {b} on both sides")
        self.run_tics([(0, 0)] * 10)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimFlowTest(Lockstep):
    """The 6502 build against the host C again: E1M1's exit switch, the
    intermission (a press), E1M2 loaded by game_tic, then E1M2's own
    specials: glows, fire flickers and strobes, the scrolling walls, the
    blazing lift and a door by switch, floors by switch and by walking
    over lines, the red door refused, a teleporter crossed. (The
    half-size caches: E1M2's level memory does not fit the harness with
    GAME.BIN's.)"""

    half = True

    def test_exit_to_e1m2(self):
        geo = self.watch("E1M1")
        exit_line = geo.lines_with(11)[0]
        self.use_line(geo, exit_line)
        self.run_tics([(0, 0)] * 3)
        self.assertEqual(self.h.flow()["gamestate"], GS_INTERMISSION)
        self.run_tics([(0, KB_FIRE), (0, 0)])
        self.assertEqual((self.h.flow()["gamestate"], self.h.flow()["gamemap"]), (GS_LEVEL, 2))
        geo = self.watch("E1M2")
        self.compare("E1M2")
        idle = []
        self.run_tics([(0, 0)] * 40, idle)
        MEASURE["E1M2 tic cycles, lights and scrolling walls only: mean"] = sum(idle) // len(idle)
        for line in (350, 1529, 1202, 1284, 34, 93, 147):   # switches, a door, the red door
            self.use_line(geo, line)
        for line in (628, 267, 1210, 182, 1215):             # walked over
            self.place(*geo.use_spot(line, 30))
            self.run_tics([(KM_FORWARD, 0)] * 8)
        movers = self.h.movers()
        MEASURE["E1M2 movers running after the lines (doors, floors, plats)"] = \
            f"{movers['doors']}, {movers['floors']}, {movers['plats']}"
        busy = []
        self.run_tics([(0, 0)] * 150, busy)
        MEASURE["E1M2 tic cycles, sectors moving (150 tics): mean / max"] = \
            f"{sum(busy) // len(busy)} / {max(busy)}"

def tearDownModule():
    if MEASURE and ("-v" in sys.argv or os.environ.get("DOOM_MEASURE")):
        print("\nmeasurements:")
        for k, v in MEASURE.items():
            print(f"  {k:60s} {v}")


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SimCoverageTest(Lockstep):
    """The EV_ routines E1M1 and E1M2 do not use, on the 6502 against the
    host C: E1M1 is loaded again for every round (game_tic's level load,
    which also undoes the last round), the special of the switch 753
    (tag 3: three sectors) and of the walk-over line 593 (tag 1: the
    lift's sector) are rewritten alike in both far memories, the switch
    is used and the line crossed, and the sectors run for a while. Then
    sector specials 10 and 14 and the lights 2, 3, 4, 13 and 17 are
    spawned at run time (P_SpawnSectorSpecial) and run."""

    ROUNDS = [  # (switch 753's special, line 593's special)
        (7, 53), (9, 54), (14, 6), (20, 57), (29, 25), (41, 44), (49, 141), (55, 40),
        (102, 30), (111, 37), (113, 59), (122, 119), (127, 130), (133, 12), (138, 104),
        (140, 17), (71, 16), (50, 2), (15, 22), (131, 39), (43, 73), (70, 77), (132, 87),
    ]

    def patch_special(self, line, special):
        import json
        a = json.loads((DATA / "manifest.json").read_text())["maps"]["E1M1"]["arrays"]["LINEDEFS"]
        bank = a["bank"] + (line >> a["log2"])
        addr = a["addr"] + (line & ((1 << a["log2"]) - 1)) * a["elsize"] + 6
        self.g.bank(bank)[addr] = special
        base = ctypes.addressof(self.h.lib.host_banks().contents)
        ctypes.memset(base + bank * 65536 + addr, special, 1)

    def load_e1m1(self):
        self.g.mem[self.g.L["_gamemap"]] = 1
        self.g.mem[self.g.L["_gameaction"]] = 1
        ctypes.c_uint8.in_dll(self.h.lib, "gamemap").value = 1
        ctypes.c_uint8.in_dll(self.h.lib, "gameaction").value = 1
        self.run_tics([(0, 0)])

    def test_rounds(self):
        geo = self.watch("E1M1")
        self.compare("start")
        # the blue key opens 133's door (before the rounds: they may kill the player)
        self.load_e1m1()
        self.patch_special(753, 133)
        self.h.lib.host_card(0, 1)
        self.g.mem[self.g.L["_player"] + self.sim.O["PL_CARDS"]] = 1
        self.use_line(geo, 753)
        self.run_tics([(0, 0)] * 20)
        # (to 4 below the lowest neighbouring ceiling: for sector 76, whose
        # neighbours are lower, that is down, as in vanilla)
        for i in (i for i, sec in enumerate(geo.sectors) if sec.tag == 3):
            self.assertNotEqual(self.h.sector(i)["ceil"], geo.sectors[i].ceilingheight,
                                f"blazing door {i} moved")
        self.h.lib.host_card(0, 0)
        self.g.mem[self.g.L["_player"] + self.sim.O["PL_CARDS"]] = 0
        started = {}
        for switch_special, walk_special in self.ROUNDS:
            self.load_e1m1()
            self.patch_special(753, switch_special)
            self.patch_special(593, walk_special)
            self.special_lines = sorted(set(self.special_lines) | {753, 593})
            tagged = [i for i, sec in enumerate(geo.sectors) if sec.tag in (1, 3)]
            before = [self.h.sector(i) for i in tagged]
            self.use_line(geo, 753)
            self.place(*geo.use_spot(593, 30))
            self.run_tics([(KM_FORWARD, 0)] * 8)
            self.run_tics([(0, 0)] * 110)
            after = [self.h.sector(i) for i in tagged]
            started[(switch_special, walk_special)] = sum(
                (a["floor"], a["ceil"], a["light"]) != (b["floor"], b["ceil"], b["light"])
                for a, b in zip(after, before))
        # the sector specials that spawn things, at run time
        for sector, special in ((10, 10), (98, 14), (23, 2), (38, 3), (173, 4), (32, 13),
                                (33, 17)):
            self.g.ccall("_P_SpawnSectorSpecial", (sector, 2), (special, 1))
            self.h.lib.host_spawn_sector_special(sector, special)
            self.compare(f"sector {sector} special {special}")
        self.run_tics([(0, 0)] * 80)
        self.patch_special(753, 23)                 # (as the converter made them)
        self.patch_special(593, 88)
        busy = [k for k, v in started.items() if v]
        MEASURE["coverage rounds that changed a tag 1 or 3 sector"] = f"{len(busy)} of {len(started)}"
        self.assertGreaterEqual(len(busy), 18)


# --- python3 tests/test_game_specials.py --profile -------------------------------------------
PROFILED = ("_P_UpdateSpecials", "run_lights", "run_buttons", "_P_PlayerInSpecialSector",
            "move_plane", "_P_ChangeSector", "_P_SectorBlockBox", "outside_sector",
            "static_height_clip", "mp_setnow", "_P_SetSectorLight", "_P_RunThinkers",
            "_P_RunStatics", "_P_PlayerThink", "look_for_players", "check_sight")


def profile(tics=60):
    """E1M1 on the 6502 (GAME.BIN's caches) with the six movers of
    SimSpecialsTest running: the cycles of each routine called by JSR,
    inclusive, per tic (far accesses charged as the kernel's)."""
    import bisect
    import collections
    sim, SpecFlat = _flat_class()
    g = SpecFlat(build_flat())
    g.boot()
    geo = Geo("E1M1")
    g.tic()
    for line in (nearest_door(geo), 753, 594, 1162, 421):
        sim.flat_place(g, *geo.use_spot(line))
        g.tic()
        g.tic(0, KB_USE)
        g.tic()
    names = {}
    for k, v in g.L.items():
        names.setdefault(v, k)
    addrs = sorted(names)
    incl, calls = collections.Counter(), collections.Counter()
    m, L = g.mpu, g.L
    total = []
    for _ in range(tics):
        g.set_input(0, 0)
        hc = L["hcall"]
        g.mem[hc], g.mem[hc + 1] = L["_game_tic"] & 0xFF, L["_game_tic"] >> 8
        m.pc, m.sp = L["host_call"], 0xFF
        stack, extra, start = [], 0, m.processorCycles
        while m.pc != L["host_stop"]:
            pc = m.pc
            t = g.traps.get(pc)
            if t is not None:
                cyc, _ = t()
                extra += cyc
                for fr in stack:
                    fr[2] += cyc
            code = m.view.code if m.inwin[pc] else g.mem
            op = code[pc]
            if op == 0x20:                          # JSR
                stack.append([code[pc + 1] | code[pc + 2] << 8, m.processorCycles, 0, m.sp])
            elif op == 0x60 and stack and m.sp >= stack[-1][3] - 2:     # RTS
                fr = stack.pop()
                i = bisect.bisect_right(addrs, fr[0]) - 1
                name = names[addrs[i]]
                incl[name] += m.processorCycles - fr[1] + fr[2] + 6
                calls[name] += 1
            m.step()
        total.append(m.processorCycles - start + extra)
    print(f"{tics} tics of E1M1 after SimSpecialsTest's lines (a door, three floors, the lift, "
          f"a blazing door): mean {sum(total) // tics}, max {max(total)} cycles")
    print(f"{'routine (inclusive, per tic)':32s} {'cycles':>9s} {'calls':>7s}")
    for k in PROFILED:
        print(f"{k:32s} {incl[k] // tics:9d} {calls[k] / tics:7.2f}")


if __name__ == "__main__":
    if "--profile" in sys.argv:
        profile()
    else:
        unittest.main()
