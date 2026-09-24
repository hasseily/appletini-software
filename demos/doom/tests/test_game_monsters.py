#!/usr/bin/env python3
"""Tests of the monsters part (docs/DESIGN.md section 9): sight, the
monsters' minds and attacks, damage, death and pickups.

The host build of the game (tests/test_game_core.py: gcc, far memory from
the converter's banks) runs the C reference (p_sight.c, p_enemy.c,
p_inter.c) in real maps, driven through tests/host/host.c:

  - sight: P_CheckSight agrees with an independent floating-point
    line-of-sight test (REJECT, then every linedef the sight line crosses:
    one-sided lines block, openings narrow the slopes to the target) over
    random pairs of points of E1M1; every pair REJECT marks is refused
    without a look, and none of them would have been visible; the BSP of
    every map fits the walk's stack;
  - a zombieman placed in E1M1 wakes when the player stands in front of
    it, chases and shoots him (sounds, attack states, health lost);
  - an imp's fireball leaves toward the player, travels at its speed,
    hits him for 3-24 and explodes;
  - a monster that walks into a door line asks the specials part to use
    it (P_UseSpecialLine, as vanilla's P_Move does);
  - the player kills a zombieman with the pistol: it wakes, the death
    states run, the kill counts, a clip drops, the corpse and the clip go
    back to sleep as statics, and walking over the clip gives half a clip;
  - every pickup of episode 1 with vanilla's limits (health, armour, ammo
    and its maxima, the backpack, weapons, keys, powers; double ammo on
    skills 1 and 5; a pickup refused stays on the floor);
  - damage: armour absorption, the baby skill's halving, the thrust,
    infighting (a monster hurt by another turns on it);
  - barrels: one shot barrel sets off the next ones along a row;
  - noise: the pistol's alert floods exactly the sectors vanilla's
    P_RecursiveSound reaches (checked against a Python flood of the map);
  - a lost soul's charge flies at the player and hurts him;
  - E1M8: the floors tagged 666 lower only when the last baron dies.

Run:  python3 tests/test_game_monsters.py [-v]      (needs build/data)
"""

from __future__ import annotations

import ctypes
import math
import os
import random
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
sys.path.insert(0, str(PROJECT / "tools"))
import test_game_core as core  # noqa: E402

TYPE, STATES, FRAC = core.TYPE, core.STATES, core.FRAC
KB_FIRE = 1
KM_FORWARD = 1
MF_SOLID, MF_SHOOTABLE, MF_AMBUSH, MF_JUSTHIT = 0x2, 0x4, 0x20, 0x40
MF_SKULLFLY, MF_DROPPED, MF_SHADOW, MF_CORPSE = 0x01000000, 0x20000, 0x40000, 0x100000
ONFLOORZ = -0x80000000
SF_CORPSE, SF_DROPPED = 0x08, 0x04
MEASURE = {}


def sfx() -> dict[str, int]:
    """sfx_ names -> numbers, from info.h."""
    import re
    text = (PROJECT / "src/game/info.h").read_text()
    body = text[text.index("#define NUMSFX"):]
    body = body[body.index("enum {") + 6:body.index("};")]
    names = re.findall(r"(sfx_\w+)", body)
    return {n: i for i, n in enumerate(names)}


SFX = sfx()
MOBJ_KEYS = ("type", "x", "y", "z", "state", "tics", "health", "flags", "movedir", "movecount",
             "reactiontime", "threshold", "momx", "momy", "momz", "angle", "sector", "height",
             "lastlook", "radius")
INV_KEYS = (["health", "armorpoints", "armortype"] + [f"ammo{i}" for i in range(4)]
            + [f"maxammo{i}" for i in range(4)] + [f"card{i}" for i in range(6)]
            + [f"power{i}" for i in range(6)] + [f"owned{i}" for i in range(8)]
            + ["pendingweapon", "readyweapon", "backpack", "killcount", "itemcount",
               "bonuscount", "damagecount", "message", "mohealth"])
AM_CLIP, AM_SHELL, AM_CELL, AM_MISL = 0, 1, 2, 3
WP_FIST, WP_PISTOL, WP_SHOTGUN, WP_CHAINGUN, WP_MISSILE, WP_PLASMA = 0, 1, 2, 3, 4, 5
WP_CHAINSAW, WP_NOCHANGE = 7, 10


class Mon(core.Game):
    """The host build with the monsters part's hooks."""

    def __init__(self):
        super().__init__()
        L = self.lib
        vp = ctypes.c_void_p
        for name in ("host_mobj", "host_static", "host_player_mo", "host_mobj_get", "host_wake",
                     "host_spawn_at", "host_view", "host_player_attacker"):
            getattr(L, name).restype = vp
        L.host_mobj_set.argtypes = [vp, ctypes.c_int, ctypes.c_int32, vp]
        L.host_mobj_get.argtypes = [vp, ctypes.c_void_p]
        L.host_set_state.argtypes = [vp, ctypes.c_int]
        L.host_wake.argtypes = [vp]
        L.host_view.argtypes = [vp]
        L.host_sight.argtypes = [vp, vp]
        L.host_damage.argtypes = [vp, vp, vp, ctypes.c_int]
        L.host_touch.argtypes = [vp]
        L.host_remove.argtypes = [vp]
        L.host_is_actor.argtypes = [vp]
        L.host_move.argtypes = [vp, ctypes.c_int, ctypes.c_int]
        L.host_action.argtypes = [vp, ctypes.c_int]
        L.host_spawn_at.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int32]
        self.sounds_seen = []
        self._snd = self.snd_count()

    # --- things -------------------------------------------------------------------------
    def mobj(self, ptr) -> dict:
        v = (ctypes.c_int32 * 20)()
        target = self.lib.host_mobj_get(ptr, v)
        d = dict(zip(MOBJ_KEYS, v))
        d["target"] = target
        d["flags"] &= 0xFFFFFFFF
        return d

    def set(self, ptr, field, value=0, other=None):
        fields = {"target": 0, "angle": 1, "health": 2, "movedir": 3, "movecount": 4,
                  "reactiontime": 5, "threshold": 6, "flags": 7, "lastlook": 8, "tics": 9}
        self.lib.host_mobj_set(ptr, fields[field], ctypes.c_int32(value & 0xFFFFFFFF
                                                                   if value >= 0 else value),
                               other)

    def set_state(self, ptr, state):
        assert self.lib.host_set_state(ptr, STATES[state] if isinstance(state, str) else state) == 0

    def player_mo(self):
        return self.lib.host_player_mo()

    def statics_of(self, type_name) -> list[int]:
        """Pointers of the live statics of a type."""
        t = TYPE[type_name]
        size = self.counts()["sizeof_sobj"]
        base = self.lib.host_static(0)
        out = []
        for i in range(self.lib.host_num_statics()):
            p = base + i * size
            f = self.static_fields(p)
            if not f["sflags"] & 1 and f["type"] == t:
                out.append(p)
        return out

    def static_fields(self, p) -> dict:
        v = (ctypes.c_int32 * 9)()
        self.lib.host_static_get(ctypes.c_void_p(p), v)
        return dict(zip(("x", "y", "z", "sector", "state", "type", "tics", "sflags", "angle"), v))

    def actors(self, type_name=None) -> list[int]:
        out = []
        size = self.counts()["sizeof_mobj"]
        base = self.lib.host_mobj(0)
        for i in range(self.counts()["nummobjs"]):
            p = base + i * size
            if self.lib.host_is_actor(p) and (type_name is None
                                              or self.mobj(p)["type"] == TYPE[type_name]):
                out.append(p)
        return out

    def spawn(self, type_name, x, y, z=ONFLOORZ):
        p = self.lib.host_spawn_at(TYPE[type_name], int(x), int(y), z)
        assert p, "spawn"
        return p

    def sight(self, a, b) -> bool:
        r = self.lib.host_sight(a, b)
        assert r >= 0
        return bool(r)

    def damage(self, target, inflictor, source, amount):
        assert self.lib.host_damage(target, inflictor, source, amount) == 0

    def inv(self) -> dict:
        v = (ctypes.c_int32 * 40)()
        self.lib.host_inventory(v)
        return dict(zip(INV_KEYS, v))

    def inv_set(self, field, value):
        idx = {"health": 0, "armorpoints": 1, "armortype": 2, "ammo0": 3, "ammo1": 4,
               "ammo2": 5, "ammo3": 6, "pendingweapon": 31, "readyweapon": 32, "skill": 99}
        self.lib.host_inventory_set(idx[field], value)

    # --- sounds ---------------------------------------------------------------------------
    def snd_count(self):
        return ctypes.c_uint8.in_dll(self.lib, "snd_count").value

    def poll_sounds(self):
        """The sounds started since the last poll (at most 8 at a time)."""
        buf = (ctypes.c_uint8 * 8)()
        count = self.lib.host_sounds(buf)
        new = (count - self._snd) & 0xFF
        self._snd = count
        got = [buf[(count - new + i) & 7] for i in range(min(new, 8))]
        self.sounds_seen += got
        return got

    def tic(self, *a, **k):
        n = k.pop("n", 1)
        for _ in range(n):
            super().tic(*a, **k)
            self.poll_sounds()

    def load(self, mapnum=1, skill=2, seed=0):
        """The map, with the random index at seed (the library is shared by
        the tests of a run: each starts from the same point)."""
        ctypes.c_uint8.in_dll(self.lib, "prndindex").value = seed
        super().load(mapnum, skill)
        self._snd = self.snd_count()
        self.sounds_seen = []


def unit(dx, dy):
    n = math.hypot(dx, dy)
    return dx / n, dy / n


class Scenes:
    """Spots in a map, from its geometry and the host's point-in-sector."""

    def __init__(self, g: Mon, mapname="E1M1"):
        self.g = g
        self.geo = core.MapGeo(mapname)

    def open_line(self, x0, y0, x1, y1, half=24):
        """No line and no placed thing in the band from (x0, y0) to (x1, y1)."""
        return self.geo.clear(x0, y0, x1, y1, half)

    def room(self, x, y, need=72):
        s = self.g.sector_at(x, y)
        sec = self.geo.sectors[s]
        return s if sec.ceilingheight - sec.floorheight >= need else None

    def open_pair(self, dist, half=28, need=80, seed=1):
        """Two spots dist apart in one sector with nothing between them."""
        geo = self.geo
        xs = [v.x for v in geo.vertexes]
        ys = [v.y for v in geo.vertexes]
        rnd = random.Random(seed)
        for _ in range(4000):
            x, y = rnd.randint(min(xs), max(xs)), rnd.randint(min(ys), max(ys))
            s = self.room(x, y, need)
            if s is None or near_line(geo, x, y, half + 8):
                continue
            for k in range(8):
                a = k * math.pi / 4
                qx, qy = x + dist * math.cos(a), y + dist * math.sin(a)
                if self.g.sector_at(qx, qy) == s and self.open_line(x, y, qx, qy, half) \
                        and not near_line(geo, qx, qy, half + 8):
                    return (x, y), (round(qx), round(qy))
        return None

    def facing_spot(self, x, y, angle_bam, dmin, dmax, half=24):
        """A spot in front of (x, y) (within 40 degrees of angle), clear of
        lines and things, in a room; None if there is none."""
        a0 = angle_bam * math.pi / 32768
        for dist in range(dmin, dmax + 1, 16):
            for da in (0, -0.3, 0.3, -0.6, 0.6):
                px, py = x + dist * math.cos(a0 + da), y + dist * math.sin(a0 + da)
                if self.room(px, py) is None:
                    continue
                if self.g.sector_at(px, py) != self.g.sector_at(x, y):
                    continue
                if self.open_line(px, py, x, y, half):
                    return round(px), round(py)
        return None


def lines_crossing(geo, x1, y1, x2, y2):
    """Linedefs that properly cross the segment, with the fraction along it."""
    out = []
    dx, dy = x2 - x1, y2 - y1
    for li in geo.lines:
        (ax, ay), (bx, by) = geo.ends(li)
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if den == 0:
            continue
        t = ((ax - x1) * ey - (ay - y1) * ex) / den
        u = ((ax - x1) * dy - (ay - y1) * dx) / den
        if 0 < t < 1 and 0 < u < 1:
            out.append((t, li))
    return out


def ref_sight(geo, reject, nsec, a, b) -> bool:
    """Floating-point line of sight between two things a, b (dicts of x, y,
    z, height, sector in map units): REJECT, then the lines crossed."""
    s1, s2 = a["sector"], b["sector"]
    pnum = s1 * nsec + s2
    if reject[pnum >> 3] & (1 << (pnum & 7)):
        return False
    zs = a["z"] + a["height"] - a["height"] / 4
    top, bottom = b["z"] + b["height"] - zs, b["z"] - zs
    for t, li in sorted(lines_crossing(geo, a["x"], a["y"], b["x"], b["y"]), key=lambda v: v[0]):
        if li.backsector == 0xFFFF or not li.flags & 4:
            return False
        f, k = geo.sectors[li.frontsector], geo.sectors[li.backsector]
        if f.floorheight == k.floorheight and f.ceilingheight == k.ceilingheight:
            continue
        otop, obot = min(f.ceilingheight, k.ceilingheight), max(f.floorheight, k.floorheight)
        if obot >= otop:
            return False
        if f.floorheight != k.floorheight:
            bottom = max(bottom, (obot - zs) / t)
        if f.ceilingheight != k.ceilingheight:
            top = min(top, (otop - zs) / t)
        if top <= bottom:
            return False
    return True


def wad_reject(mapname):
    import wadlib
    w = wadlib.Wad(str(PROJECT / "build/wad/freedoom1.wad"))
    r = w.map_lumps(mapname)["REJECT"]
    return r if isinstance(r, (bytes, bytearray)) else w.read(r)


def have_wad():
    return (PROJECT / "build/wad/freedoom1.wad").is_file()


def path_clear(geo, x0, y0, x1, y1, half=24):
    """No wall on the segment, and no placed thing near it but at its ends."""
    if not core.lines_clear(geo, x0, y0, x1, y1):
        return False
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    for t in geo.things:
        if t.type in (1, 2, 3, 4, 11, 14):
            continue
        u = (t.x - x0) * ux + (t.y - y0) * uy
        v = -(t.x - x0) * uy + (t.y - y0) * ux
        if 30 < u < length - 30 and abs(v) < half + 20:
            return False
    return True


def near_line(geo, x, y, dist):
    for li in geo.lines:
        (ax, ay), (bx, by) = geo.ends(li)
        ex, ey = bx - ax, by - ay
        n2 = ex * ex + ey * ey
        t = max(0.0, min(1.0, ((x - ax) * ex + (y - ay) * ey) / n2))
        if math.hypot(ax + t * ex - x, ay + t * ey - y) < dist:
            return True
    return False


# --- the tests -------------------------------------------------------------------------------
@unittest.skipUnless(core.have_data() and have_wad(), "no converted data or WAD")
class SightTest(unittest.TestCase):
    def test_sight_against_reference(self):
        g = Mon()
        g.load(1, 2)
        geo = core.MapGeo("E1M1")
        reject = wad_reject("E1M1")
        nsec = len(geo.sectors)
        # two probes (zombiemen: their height, radius 20) moved around
        a = g.spawn("MT_POSSESSED", -416, 256)
        b = g.spawn("MT_POSSESSED", -416, 300)
        xs = [v.x for v in geo.vertexes]
        ys = [v.y for v in geo.vertexes]
        rnd = random.Random(7)

        def point():
            while True:
                x, y = rnd.randint(min(xs), max(xs)), rnd.randint(min(ys), max(ys))
                s = g.sector_at(x, y)
                sec = geo.sectors[s]
                if sec.ceilingheight - sec.floorheight < 16 or near_line(geo, x, y, 8):
                    continue
                return x, y, s

        n = agree = rejected = seen = hidden = 0
        disagree = []
        while n < 400:
            (ax, ay, sa), (bx, by, sb) = point(), point()
            g.lib.host_move(a, ax, ay)
            g.lib.host_move(b, bx, by)
            ma, mb = g.mobj(a), g.mobj(b)
            ta = dict(x=ax, y=ay, z=ma["z"] / FRAC, height=ma["height"] / FRAC, sector=sa)
            tb = dict(x=bx, y=by, z=mb["z"] / FRAC, height=mb["height"] / FRAC, sector=sb)
            got = g.sight(a, b)
            pnum = sa * nsec + sb
            rej = bool(reject[pnum >> 3] & (1 << (pnum & 7)))
            ref = ref_sight(geo, reject, nsec, ta, tb)
            n += 1
            if rej:
                rejected += 1
                self.assertFalse(got, "REJECT refuses the pair")
                # (the WAD's REJECT is the nodebuilder's: a pair it refuses
                # may still have a line of sight; Doom trusts it anyway)
                hidden += ref_sight(geo, bytes(len(reject)), nsec, ta, tb)
            seen += got
            if got == ref:
                agree += 1
            else:
                disagree.append((ta, tb, got, ref))
        MEASURE["sight pairs: total / REJECT-refused (open without it) / visible / agree"] = \
            f"{n} / {rejected} ({hidden}) / {seen} / {agree}"
        self.assertGreater(rejected, 100)
        self.assertGreater(seen, 20)
        self.assertGreaterEqual(agree, n - 4, f"disagreements: {disagree[:4]}")

    def test_bsp_depth_fits_stack(self):
        import refrender
        worst = 0
        for m in range(1, 10):
            d = refrender.GameData(core.DATA, f"E1M{m}")
            nodes = d.nodes

            def depth(n):
                if n & 0x8000:
                    return 0
                nd = nodes[n]
                return 1 + max(depth(nd.child0), depth(nd.child1))
            worst = max(worst, depth(len(nodes) - 1))
        MEASURE["deepest BSP of E1"] = worst
        self.assertLess(worst, 64)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class ZombieTest(unittest.TestCase):
    """A zombieman wakes, chases, shoots; the pistol kills one."""

    @classmethod
    def setUpClass(cls):
        cls.g = Mon()
        cls.g.load(1, 2)
        cls.sc = Scenes(cls.g)

    def pick(self, dmin, dmax):
        """A zombieman and a spot in front of it from which it sees the
        player (placed there)."""
        g, sc = self.g, self.sc
        for p in g.statics_of("MT_POSSESSED"):
            s = g.static_fields(p)
            a0 = s["angle"] * math.pi / 32768
            for dist in range(dmin, dmax + 1, 16):
                for da in (0, -0.3, 0.3, -0.6, 0.6):
                    px, py = round(s["x"] + dist * math.cos(a0 + da)), \
                        round(s["y"] + dist * math.sin(a0 + da))
                    if sc.room(px, py) is None or near_line(sc.geo, px, py, 20) \
                            or not path_clear(sc.geo, px, py, s["x"], s["y"]):
                        continue
                    g.place(px, py, core.bam(s["x"] - px, s["y"] - py))
                    if g.sight(g.lib.host_view(p), g.player_mo()):
                        return p, s, (px, py)
        self.skipTest("no zombieman with a spot in front")

    def alone(self, keep):
        """Every other monster removed (no infighting, no other attacker)."""
        g = self.g
        for t in ("MT_POSSESSED", "MT_SHOTGUY", "MT_TROOP", "MT_SERGEANT", "MT_SHADOWS",
                  "MT_HEAD", "MT_BRUISER", "MT_SKULL"):
            for q in g.statics_of(t):
                if q != keep:
                    assert g.lib.host_remove(q) == 0

    def test_wakes_and_attacks(self):
        g = self.g
        g.load(1, 2)
        p, s, (px, py) = self.pick(160, 320)
        self.alone(p)
        health0 = g.inv()["health"]
        woke = attacked = hit = None
        for tic in range(600):
            g.tic()
            if woke is None:
                act = g.actors("MT_POSSESSED")
                if act:
                    woke = (tic, act[0])
                    m = g.mobj(act[0])
                    self.assertLess(math.hypot((m["x"] >> 16) - s["x"], (m["y"] >> 16) - s["y"]), 16)
                    self.assertEqual(m["target"], g.player_mo(), "it targets the player")
                    self.assertTrue(STATES["S_POSS_RUN1"] <= m["state"] <= STATES["S_POSS_RUN8"])
            elif attacked is None:
                st = g.mobj(woke[1])["state"]
                if STATES["S_POSS_ATK1"] <= st <= STATES["S_POSS_ATK3"]:
                    attacked = tic
            if g.inv()["health"] < health0 and g.lib.host_player_attacker() == woke[1]:
                hit = tic
                break
        self.assertIsNotNone(woke, "the zombieman woke")
        self.assertIsNotNone(attacked, "it attacked")
        self.assertIsNotNone(hit, "the player was hit")
        self.assertTrue(set(g.sounds_seen) & {SFX["sfx_posit1"], SFX["sfx_posit2"],
                                               SFX["sfx_posit3"]}, "sight sound")
        self.assertIn(SFX["sfx_pistol"], g.sounds_seen)
        MEASURE["zombieman: woke / first attack / hit (tic)"] = f"{woke[0]} / {attacked} / {hit}"

    def test_pistol_kills_zombieman(self):
        g = self.g
        g.load(1, 2)
        p, s, (px, py) = self.pick(96, 200)
        self.alone(p)
        kills0 = g.inv()["killcount"]
        dead = None
        for tic in range(300):
            g.tic(buttons=KB_FIRE)
            z = g.actors("MT_POSSESSED")
            if z and g.mobj(z[0])["health"] <= 0:
                dead = z[0]
                break
            self.assertGreater(g.inv()["health"], 0)
        self.assertIsNotNone(dead, "the zombieman died")
        m = g.mobj(dead)
        self.assertTrue(STATES["S_POSS_DIE1"] <= m["state"] <= STATES["S_POSS_XDIE9"])
        self.assertFalse(m["flags"] & MF_SHOOTABLE)
        self.assertTrue(m["flags"] & MF_CORPSE)
        self.assertEqual(g.inv()["killcount"], kills0 + 1)
        # a clip dropped (an actor that sleeps as a static once it lies still)
        clips = [(g.mobj(a)["x"] >> 16, g.mobj(a)["y"] >> 16) for a in g.actors("MT_CLIP")
                 if g.mobj(a)["flags"] & MF_DROPPED]
        clips += [(f["x"], f["y"]) for f in map(g.static_fields, g.statics_of("MT_CLIP"))
                  if f["sflags"] & SF_DROPPED]
        self.assertEqual(len(clips), 1, "a clip dropped")
        self.assertLess(math.hypot(clips[0][0] - (m["x"] >> 16), clips[0][1] - (m["y"] >> 16)), 8,
                        "where it died (the corpse slides a little)")
        # the death states run to the corpse frame; corpse and clip then sleep
        g.tic(n=80)
        corpses = [g.static_fields(q) for q in g.statics_of("MT_POSSESSED")
                   if g.static_fields(q)["sflags"] & SF_CORPSE]
        self.assertEqual(len(corpses), 1, "the corpse sleeps as a static")
        self.assertEqual(corpses[0]["state"], STATES["S_POSS_DIE5"])
        dropped = [g.static_fields(q) for q in g.statics_of("MT_CLIP")
                   if g.static_fields(q)["sflags"] & SF_DROPPED]
        self.assertEqual(len(dropped), 1, "the dropped clip is a static")
        # walk onto it: half a clip (skill 2)
        ammo = g.inv()["ammo0"]
        # (placing checks the position, which touches it, as vanilla's
        # PIT_CheckThing does; G_Ticker clears player.message at each tic)
        g.place(dropped[0]["x"], dropped[0]["y"], 0)
        self.assertEqual(g.inv()["ammo0"], ammo + 5)
        self.assertEqual(g.inv()["message"], 21)          # MSG_GOTCLIP
        g.tic()
        self.assertFalse([q for q in g.statics_of("MT_CLIP")
                          if g.static_fields(q)["sflags"] & SF_DROPPED])
        MEASURE["zombieman killed with the pistol at tic"] = tic


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class ImpTest(unittest.TestCase):
    def test_fireball_travels_and_hurts(self):
        g = Mon()
        g.load(1, 2)
        sc = Scenes(g)
        # the player and an imp 320 units apart in the open
        pair = sc.open_pair(320)
        found = pair and (*pair[0], *pair[1])
        self.assertIsNotNone(found)
        px, py, ix, iy = found
        g.place(px, py, core.bam(ix - px, iy - py))
        imp = g.spawn("MT_TROOP", ix, iy)
        g.set(imp, "target", other=g.player_mo())
        g.set_state(imp, "S_TROO_ATK1")
        health0 = g.inv()["health"]
        ball = None
        track = []
        for tic in range(80):
            g.tic()
            balls = g.actors("MT_TROOPSHOT")
            if balls and ball is None:
                ball = balls[0]
            if ball is not None:
                b = g.mobj(ball)
                track.append((b["x"] / FRAC, b["y"] / FRAC, b["state"]))
                if b["state"] >= STATES["S_TBALLX1"]:
                    break
        self.assertIsNotNone(ball, "a fireball was spawned")
        self.assertIn(SFX["sfx_firsht"], g.sounds_seen)
        # it flew toward the player, 10 units a tic
        (x0, y0, _), (x1, y1, _) = track[0], track[1]
        self.assertAlmostEqual(math.hypot(x1 - x0, y1 - y0), 10, delta=0.2)
        d0 = math.hypot(px - x0, py - y0)
        d1 = math.hypot(px - track[-2][0], py - track[-2][1])
        self.assertLess(d1, d0 - 200)
        self.assertGreaterEqual(track[-1][2], STATES["S_TBALLX1"], "it exploded")
        lost = health0 - g.inv()["health"]
        self.assertIn(lost, range(3, 25, 3), "3 x (1..8)")
        self.assertIn(SFX["sfx_firxpl"], g.sounds_seen)
        MEASURE["imp fireball: tics in flight / damage"] = f"{len(track)} / {lost}"


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class DoorTest(unittest.TestCase):
    def test_monster_uses_door_line(self):
        """vanilla P_Move: blocked with special lines in spechit, it asks to
        use them (the specials part opens doors for monsters)."""
        g = Mon()
        g.load(1, 2)
        geo = core.MapGeo("E1M1")
        tried = 0
        for i, li in enumerate(geo.lines):
            if li.special != 1 or li.backsector == 0xFFFF:
                continue
            (ax, ay), (bx, by) = geo.ends(li)
            if (ax != bx and ay != by) or math.hypot(bx - ax, by - ay) < 96:
                continue
            door = geo.sectors[li.backsector]
            if door.ceilingheight != door.floorheight:
                continue
            nx, ny = unit(by - ay, -(bx - ax))          # toward the front side
            mx, my = (ax + bx) / 2, (ay + by) / 2
            dx, dy = mx + nx * 36, my + ny * 36         # a demon (radius 30) at the door
            if g.sector_at(dx, dy) != li.frontsector:
                continue
            movedir = {(1, 0): 0, (0, 1): 2, (-1, 0): 4, (0, -1): 6}[(round(-nx), round(-ny))]
            g.load(1, 2)
            demon = g.spawn("MT_SERGEANT", round(dx), round(dy))
            g.set(demon, "target", other=g.player_mo())
            g.set(demon, "movedir", movedir)
            g.set(demon, "movecount", 5)
            g.set(demon, "angle", movedir << 13)
            calls0 = ctypes.c_uint16.in_dll(g.lib, "use_calls").value
            before = g.mobj(demon)
            assert g.lib.host_action(demon, 0) == 0      # A_Chase: P_Move into the door
            calls = ctypes.c_uint16.in_dll(g.lib, "use_calls").value - calls0
            tried += 1
            if calls:
                self.assertEqual(ctypes.c_uint16.in_dll(g.lib, "use_last_line").value, i)
                self.assertEqual(ctypes.c_void_p.in_dll(g.lib, "use_last_thing").value, demon)
                # (the stand-in refuses monsters: P_Move fails, a new direction)
                after = g.mobj(demon)
                self.assertNotEqual(after["movedir"], movedir)
                self.assertEqual((before["x"], before["y"]) != (after["x"], after["y"]),
                                 after["movedir"] != 8)
                MEASURE["door line used by a demon"] = i
                return
        self.fail(f"no door tried worked ({tried} tried)")


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class PickupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Mon()

    def fresh(self, skill=2):
        g = self.g
        g.load(1, skill)
        p = g.mobj(g.player_mo())
        self.px, self.py = p["x"] >> 16, p["y"] >> 16
        return g

    def touch(self, type_name):
        g = self.g
        item = g.spawn(type_name, self.px, self.py)
        assert g.lib.host_touch(item) == 0
        g.poll_sounds()
        return g.lib.host_is_actor(item)       # still there: refused

    def test_health(self):
        g = self.fresh()
        g.inv_set("health", 50)
        self.assertFalse(self.touch("MT_MISC10"))         # stimpack +10
        self.assertEqual(g.inv()["health"], 60)
        self.assertFalse(self.touch("MT_MISC11"))         # medikit +25
        self.assertEqual(g.inv()["health"], 85)
        self.assertFalse(self.touch("MT_MISC11"))
        self.assertEqual(g.inv()["health"], 100)          # capped at 100
        self.assertTrue(self.touch("MT_MISC10"), "not needed: left")
        self.assertEqual(g.inv()["health"], 100)
        self.assertFalse(self.touch("MT_MISC2"))          # bonus: over 100
        self.assertEqual(g.inv()["health"], 101)
        self.assertEqual(g.inv()["mohealth"], 101)
        self.assertFalse(self.touch("MT_MISC12"))         # soul sphere +100, max 200
        self.assertEqual(g.inv()["health"], 200)
        self.assertFalse(self.touch("MT_MISC2"))
        self.assertEqual(g.inv()["health"], 200)
        self.assertIn(SFX["sfx_getpow"], g.poll_sounds() or g.sounds_seen)

    def test_armour(self):
        g = self.fresh()
        self.assertFalse(self.touch("MT_MISC3"))          # armour bonus
        i = g.inv()
        self.assertEqual((i["armorpoints"], i["armortype"]), (1, 1))
        self.assertFalse(self.touch("MT_MISC0"))          # green: 100, class 1
        self.assertEqual((g.inv()["armorpoints"], g.inv()["armortype"]), (100, 1))
        self.assertTrue(self.touch("MT_MISC0"), "no better: left")
        self.assertFalse(self.touch("MT_MISC1"))          # blue: 200, class 2
        self.assertEqual((g.inv()["armorpoints"], g.inv()["armortype"]), (200, 2))
        self.assertFalse(self.touch("MT_MISC3"))
        self.assertEqual(g.inv()["armorpoints"], 200)     # bonus capped at 200

    def test_ammo_and_backpack(self):
        g = self.fresh()
        i0 = g.inv()
        self.assertEqual(i0["ammo0"], 50)
        for t, am, n in (("MT_CLIP", 0, 10), ("MT_MISC17", 0, 50), ("MT_MISC22", 1, 4),
                         ("MT_MISC23", 1, 20), ("MT_MISC18", 3, 1), ("MT_MISC19", 3, 5),
                         ("MT_MISC20", 2, 20), ("MT_MISC21", 2, 100)):
            before = g.inv()[f"ammo{am}"]
            self.assertFalse(self.touch(t), t)
            self.assertEqual(g.inv()[f"ammo{am}"], before + n, t)
        # to the maximum, then refused
        for _ in range(3):
            self.touch("MT_MISC17")
        self.assertEqual(g.inv()["ammo0"], 200)
        self.assertTrue(self.touch("MT_CLIP"), "full: left")
        # the backpack doubles the maxima and gives a clip of each
        self.assertFalse(self.touch("MT_MISC24"))
        i = g.inv()
        self.assertEqual([i[f"maxammo{k}"] for k in range(4)], [400, 100, 600, 100])
        self.assertEqual(i["ammo0"], 210)
        self.assertEqual(i["backpack"], 1)
        self.assertFalse(self.touch("MT_MISC24"))         # a second: ammo only
        self.assertEqual(g.inv()["maxammo0"], 400)

    def test_double_ammo_skills(self):
        for skill in (0, 4):
            g = self.fresh(skill)
            self.touch("MT_CLIP")
            self.assertEqual(g.inv()["ammo0"], 70, f"skill {skill}")

    def test_weapons(self):
        g = self.fresh()
        self.assertFalse(self.touch("MT_SHOTGUN"))
        i = g.inv()
        self.assertEqual((i["owned2"], i["pendingweapon"], i["ammo1"]), (1, WP_SHOTGUN, 8))
        self.assertIn(SFX["sfx_wpnup"], g.sounds_seen)
        self.assertFalse(self.touch("MT_SHOTGUN"), "owned: its ammo still counts")
        self.assertEqual(g.inv()["ammo1"], 16)
        for t, w in (("MT_CHAINGUN", WP_CHAINGUN), ("MT_MISC27", WP_MISSILE),
                     ("MT_MISC28", WP_PLASMA), ("MT_MISC26", WP_CHAINSAW)):
            self.assertFalse(self.touch(t), t)
            self.assertEqual(g.inv()[f"owned{w}"], 1)
            self.assertEqual(g.inv()["pendingweapon"], w)
        self.assertTrue(self.touch("MT_MISC26"), "a second chainsaw is left")
        # a dropped shotgun gives one load (4 shells)
        g = self.fresh()
        item = g.spawn("MT_SHOTGUN", self.px, self.py)
        g.set(item, "flags", g.mobj(item)["flags"] | MF_DROPPED)
        g.lib.host_touch(item)
        self.assertEqual(g.inv()["ammo1"], 4)

    def test_keys_and_powers(self):
        g = self.fresh()
        for k, t in enumerate(("MT_MISC4", "MT_MISC6", "MT_MISC5", "MT_MISC9", "MT_MISC7",
                               "MT_MISC8")):
            self.assertFalse(self.touch(t), t)
            self.assertEqual(g.inv()[f"card{k}"], 1, t)
        self.assertEqual(g.inv()["bonuscount"], 12)       # = 6 by the card, += 6
        self.assertFalse(self.touch("MT_INV"))
        self.assertEqual(g.inv()["power0"], 30 * 35)
        g.inv_set("health", 40)
        self.assertFalse(self.touch("MT_MISC13"))         # berserk
        i = g.inv()
        self.assertEqual((i["health"], i["power1"], i["pendingweapon"]), (100, 1, WP_FIST))
        self.assertFalse(self.touch("MT_INS"))
        self.assertEqual(g.inv()["power2"], 60 * 35)
        self.assertTrue(g.mobj(g.player_mo())["flags"] & MF_SHADOW)
        self.assertFalse(self.touch("MT_MISC14"))         # radiation suit
        self.assertEqual(g.inv()["power3"], 60 * 35)
        self.assertFalse(self.touch("MT_MISC15"))         # computer map
        self.assertEqual(g.inv()["power4"], 1)
        self.assertTrue(self.touch("MT_MISC15"), "already got it")
        self.assertFalse(self.touch("MT_MISC16"))         # light amplification
        self.assertEqual(g.inv()["power5"], 120 * 35)

    def test_items_counted_and_out_of_reach(self):
        g = self.fresh()
        items = g.inv()["itemcount"]
        self.touch("MT_MISC2")                            # COUNTITEM
        self.assertEqual(g.inv()["itemcount"], items + 1)
        # an item 16 units above the player's head is out of reach
        mo = g.mobj(g.player_mo())
        item = g.spawn("MT_MISC10", self.px, self.py, mo["z"] + mo["height"] + 16 * FRAC)
        g.inv_set("health", 50)
        g.lib.host_touch(item)
        self.assertEqual(g.inv()["health"], 50)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class DamageTest(unittest.TestCase):
    def test_armour_skill_and_thrust(self):
        g = Mon()
        g.load(1, 2)
        pm = g.player_mo()
        imp = g.spawn("MT_TROOP", (g.mobj(pm)["x"] >> 16) + 100, g.mobj(pm)["y"] >> 16)
        g.inv_set("armorpoints", 100)
        g.inv_set("armortype", 1)
        g.damage(pm, imp, imp, 30)                  # green armour takes a third
        i = g.inv()
        self.assertEqual((i["health"], i["armorpoints"], i["damagecount"]), (80, 90, 20))
        m = g.mobj(pm)
        # pushed away from the imp (thrust 30 * 8192 * 100 / 100 along -x)
        self.assertAlmostEqual(m["momx"], -30 * 8192 * 100 // 100, delta=8)
        g.inv_set("armortype", 2)
        g.damage(pm, imp, imp, 30)                  # blue: a half, until used up
        self.assertEqual((g.inv()["health"], g.inv()["armorpoints"]), (65, 75))
        g.load(1, 0)
        pm = g.player_mo()
        g.damage(pm, None, None, 31)                # baby: half damage
        self.assertEqual(g.inv()["health"], 85)

    def test_infighting(self):
        g = Mon()
        g.load(1, 2)
        pm = g.mobj(g.player_mo())
        x, y = pm["x"] >> 16, pm["y"] >> 16
        zombie = g.spawn("MT_POSSESSED", x + 100, y)
        imp = g.spawn("MT_TROOP", x + 200, y)
        g.set(zombie, "target", other=g.player_mo())
        g.damage(zombie, imp, imp, 1)
        z = g.mobj(zombie)
        self.assertEqual(z["target"], imp, "turns on the imp")
        # BASETHRESHOLD; if it did not flinch it went from its spawn state to
        # its see state, whose A_Chase ran at once (vanilla P_SetMobjState)
        # and counted one down (which one depends on the random index, which
        # the specials' set-up also draws from)
        chased = not (STATES["S_POSS_PAIN"] <= z["state"] <= STATES["S_POSS_PAIN2"])
        self.assertEqual(z["threshold"], 99 if chased else 100)
        self.assertEqual(z["reactiontime"], 0)
        g.damage(zombie, g.player_mo(), g.player_mo(), 1)
        self.assertEqual(g.mobj(zombie)["target"], imp, "threshold: keeps its target")


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class BarrelTest(unittest.TestCase):
    def test_chain(self):
        g = Mon()
        g.load(1, 2)
        barrels = [g.static_fields(p) | {"p": p} for p in g.statics_of("MT_BARREL")]
        row = sorted([b for b in barrels if b["x"] == 2512], key=lambda b: -b["y"])
        self.assertGreater(len(row), 4, "E1M1's row of barrels")
        first = g.lib.host_wake(row[0]["p"])
        self.assertTrue(first)
        g.damage(first, g.player_mo(), g.player_mo(), 100)
        went, last = [], {}                        # tics at which a barrel went off
        for tic in range(400):
            g.tic()
            now = {}
            for b in g.actors("MT_BARREL"):
                now[b] = g.mobj(b)["state"] >= STATES["S_BEXP"]
                if now[b] and not last.get(b):
                    went.append(tic)
            last = now
        rowset = {(b["x"], b["y"]) for b in row}
        MEASURE["barrels set off (row of)"] = f"{len(went)} ({len(row)})"
        self.assertGreaterEqual(len(went), len(row), "the row went off")
        self.assertGreater(len(set(went)), 3,
                           "one after the other, not all at once")
        self.assertEqual(len(rowset), len(row))
        self.assertIn(SFX["sfx_barexp"], g.sounds_seen)


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class NoiseTest(unittest.TestCase):
    def flood(self, geo, start):
        """vanilla P_RecursiveSound on the map's data (heights as loaded)."""
        seclines = {}
        for i, li in enumerate(geo.lines):
            for s in {li.frontsector, li.backsector} - {0xFFFF}:
                seclines.setdefault(s, []).append(li)
        trav = {}
        sys.setrecursionlimit(10000)

        def rec(sec, blocks):
            if sec in trav and trav[sec] <= blocks + 1:
                return
            trav[sec] = blocks + 1
            for li in seclines.get(sec, []):
                if not li.flags & 4 or li.backsector == 0xFFFF:
                    continue
                f, b = geo.sectors[li.frontsector], geo.sectors[li.backsector]
                if min(f.ceilingheight, b.ceilingheight) - max(f.floorheight, b.floorheight) <= 0:
                    continue
                other = li.backsector if li.frontsector == sec else li.frontsector
                if li.flags & 64:
                    if not blocks:
                        rec(other, 1)
                else:
                    rec(other, blocks)
        rec(start, 0)
        return set(trav)

    def test_flood_matches_vanilla(self):
        g = Mon()
        geo = core.MapGeo("E1M1")
        for spot in ((-416, 256), (2400, -400), (900, 1100)):
            g.load(1, 2)
            if g.sector_at(*spot) is None:
                continue
            g.place(*spot, 0)
            assert g.lib.host_noise() == 0
            got = {s for s in range(len(geo.sectors)) if g.lib.host_soundtarget(s)}
            want = self.flood(geo, g.mobj(g.player_mo())["sector"])
            self.assertEqual(got, want, f"from {spot}")
            self.assertLess(len(got), len(geo.sectors))
        MEASURE["E1M1 sectors reached by the pistol's noise (last spot)"] = \
            f"{len(got)} of {len(geo.sectors)}"

    def test_shot_wakes_the_sector(self):
        """A dormant monster that cannot see the player hears his shot and
        wakes at its next look, targeting him."""
        g = Mon()
        g.load(1, 2)
        sc = Scenes(g)
        for p in g.statics_of("MT_POSSESSED") + g.statics_of("MT_SHOTGUY"):
            s = g.static_fields(p)
            if s["sflags"] & 0x02:
                continue                            # (an ambusher only wakes by sight)
            # behind it (it looks 180 degrees in front), beyond melee range
            spot = None
            back = (s["angle"] / 32768 + 1) * math.pi
            for dist in range(96, 400, 16):
                for da in (0, -0.5, 0.5, -1.0, 1.0):
                    x, y = s["x"] + dist * math.cos(back + da), s["y"] + dist * math.sin(back + da)
                    if sc.room(x, y) is not None and not near_line(sc.geo, x, y, 20) \
                            and path_clear(sc.geo, x, y, s["x"], s["y"]):
                        spot = (round(x), round(y))
                        break
                if spot:
                    break
            if spot:
                break
        else:
            self.skipTest("no dormant monster with room behind it")
        g.place(*spot, (s["angle"] + 0x8000) & 0xFFFF)
        def it():
            return [a for t in ("MT_POSSESSED", "MT_SHOTGUY") for a in g.actors(t)
                    if math.hypot((g.mobj(a)["x"] >> 16) - s["x"],
                                  (g.mobj(a)["y"] >> 16) - s["y"]) < 32]
        for _ in range(12):                         # quiet: it stays put (an actor
            g.tic()                                 # maybe, if REJECT let it look)
        self.assertFalse([a for a in it() if g.mobj(a)["target"]])
        for _ in range(40):                         # until the pistol is up and fires
            g.tic(buttons=KB_FIRE)
            if SFX["sfx_pistol"] in g.sounds_seen:
                break
        self.assertTrue(g.lib.host_soundtarget(s["sector"]))
        g.tic(n=12)
        woke = it()
        self.assertTrue(woke, "it heard the shot")
        self.assertEqual(g.mobj(woke[0])["target"], g.player_mo())
        MEASURE["woken by the pistol's noise: monster at"] = f"({s['x']}, {s['y']})"


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class SkullTest(unittest.TestCase):
    def test_charge(self):
        g = Mon()
        g.load(1, 2)
        sc = Scenes(g)
        pair = sc.open_pair(200, seed=5)
        self.assertIsNotNone(pair)
        (x, y), spot = pair
        g.place(x, y, core.bam(spot[0] - x, spot[1] - y))
        self.assertIsNotNone(spot)
        skull = g.spawn("MT_SKULL", *spot)
        g.set(skull, "target", other=g.player_mo())
        g.set_state(skull, "S_SKULL_ATK1")
        health0 = g.inv()["health"]
        flew = False
        for tic in range(60):
            g.tic()
            m = g.mobj(skull)
            flew |= bool(m["flags"] & MF_SKULLFLY)
            if g.inv()["health"] < health0:
                break
        self.assertTrue(flew)
        self.assertIn(SFX["sfx_sklatk"], g.sounds_seen)
        self.assertIn(health0 - g.inv()["health"], range(3, 25, 3), "3 x (1..8)")
        self.assertFalse(g.mobj(skull)["flags"] & MF_SKULLFLY, "stopped by the hit")


@unittest.skipUnless(core.have_data(), "no converted data (build/data)")
class BossTest(unittest.TestCase):
    def test_e1m8_barons(self):
        g = Mon()
        g.load(8, 2)
        barons = g.statics_of("MT_BRUISER")
        self.assertTrue(barons, "E1M8 has barons")
        calls = lambda: ctypes.c_uint16.in_dll(g.lib, "ev_floortag_calls").value  # noqa: E731
        c0 = calls()
        actors = [g.lib.host_wake(p) for p in list(barons)]
        for n, b in enumerate(actors):
            g.damage(b, g.player_mo(), g.player_mo(), 2000)
            g.tic(n=60)                               # the death states reach A_BossDeath
            if n < len(actors) - 1:
                self.assertEqual(calls(), c0, "a baron still lives")
        self.assertEqual(calls(), c0 + 1)
        self.assertEqual(ctypes.c_uint16.in_dll(g.lib, "ev_floortag_tag").value, 666)
        MEASURE["E1M8 barons"] = len(actors)


def tearDownModule():
    if MEASURE and ("-v" in sys.argv or os.environ.get("DOOM_MEASURE")):
        print("\nmeasurements:")
        for k, v in MEASURE.items():
            print(f"  {k:60s} {v}")


if __name__ == "__main__":
    unittest.main()
