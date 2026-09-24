#!/usr/bin/env python3
"""The game's info tables against their sources (docs/DESIGN.md section 9).

tools/gen_info.py writes src/game/info.h, info.c and gtables.s from a
compact source written in vanilla's terms (names, order, values); these
tests check that source:

  - the generated files are up to date (gen_info.py --check), and so are
    the assembly's struct offsets (gen_offsets.py --check);
  - every state the port keeps is vanilla's (sprite, frame, full bright,
    tics, action, next state) and every thing type's record is vanilla's
    (all 22 fields but the dropped raise state), compared with a vanilla
    info.c: chocolate-doom's src/doom/info.c (GPL), in the directory
    named by DOOM_VANILLA_SRC;
  - the frame sequences of the E1 monsters, projectiles, effects and the
    weapons, and the monsters' properties, against ZDoom's actor
    definitions (DECORATE, now ZScript with the same States syntax), in
    the directory named by DOOM_ZDOOM_ACTORS (wadsrc/static/zscript/doom
    of ZDoom or GZDoom). ZDoom's own additions are not compared: states
    of the TNT1 sprite after vanilla's end, zero-tic states with ZDoom's
    own actions (A_PlayerSkinCheck), and a label's states after a `Goto`
    (ZDoom routes some through shared ones).

The vanilla and ZDoom comparisons are skipped when their sources are not
at hand. Run:  python3 tests/test_game_info.py [-v]
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import gen_info  # noqa: E402

VANILLA = os.environ.get("DOOM_VANILLA_SRC")
ZDOOM = os.environ.get("DOOM_ZDOOM_ACTORS")
MI_FIELDS = ("doomednum", "spawnstate", "spawnhealth", "seestate", "seesound", "reactiontime",
             "attacksound", "painstate", "painchance", "painsound", "meleestate", "missilestate",
             "deathstate", "xdeathstate", "deathsound", "speed", "radius", "height", "mass",
             "damage", "activesound", "flags", "raisestate")


def ours():
    states = {s.name: s for s in gen_info.parse_states()}
    mobjs = dict(gen_info.parse_mobjs())
    return states, mobjs


class GeneratedTest(unittest.TestCase):
    def test_up_to_date(self):
        for tool in ("gen_info.py", "gen_offsets.py"):
            r = subprocess.run([sys.executable, str(PROJECT / "tools" / tool), "--check"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{tool} --check: {r.stdout}{r.stderr}")


def vanilla_tables(path: Path):
    text = (path / "info.c").read_text(errors="replace")
    states = {}
    for m in re.finditer(r"\{SPR_(\w+),\s*(\d+),\s*(-?\d+),\s*\{(\w+)\},\s*(\w+),[^}]*\},?\s*//\s*(\w+)",
                         text):
        spr, frame, tics, action, nxt, name = m.groups()
        frame = int(frame)
        states[name] = (spr, frame & 0x7FFF, bool(frame & 0x8000), int(tics),
                        None if action == "NULL" else action, nxt)
    mobjs = {}
    for m in re.finditer(r"\{\s*//\s*(MT_\w+)(.*?)\n\s*\}", text, re.S):
        vals = re.findall(r"^\s*(.*?),?\s*//\s*(\w+)\s*$", m.group(2), re.M)
        mobjs[m.group(1)] = {k: v.strip() for v, k in vals}
    return states, mobjs


@unittest.skipUnless(VANILLA and (Path(VANILLA) / "info.c").is_file(),
                     "no vanilla info.c (set DOOM_VANILLA_SRC)")
class VanillaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vstates, cls.vmobjs = vanilla_tables(Path(VANILLA))
        cls.states, cls.mobjs = ours()

    def test_states(self):
        self.assertGreater(len(self.vstates), 900)
        for name, s in self.states.items():
            self.assertIn(name, self.vstates)
            want = self.vstates[name]
            got = (s.sprite, s.frame, s.bright, s.tics, s.action, s.next)
            self.assertEqual(got, want, name)

    def test_types(self):
        def num(v):
            v = v.replace("*FRACUNIT", "").replace("FRACUNIT", "1")
            return int(eval(v))                 # "20", "8*FRACUNIT", "-1"
        for name, f in self.mobjs.items():
            self.assertIn(name, self.vmobjs)
            v = self.vmobjs[name]
            for key in MI_FIELDS:
                if key == "raisestate":
                    continue                    # dropped (no arch-vile in E1)
                want, got = v[key], f[key]
                if key.endswith("state"):
                    self.assertEqual(got, "S_NULL" if want == "0" else want, f"{name}.{key}")
                elif key.endswith("sound"):
                    self.assertEqual(got, "None" if want == "0" else want[4:], f"{name}.{key}")
                elif key == "flags":
                    wf = set() if want == "0" else {x.strip()[3:] for x in want.split("|")}
                    gf = set() if got == "0" else set(got.split("|"))
                    self.assertEqual(gf, wf, f"{name}.flags")
                elif key == "speed":
                    # the port gives a missile's speed in map units (p_mobj scales it)
                    self.assertEqual(int(got), num(want), f"{name}.speed")
                else:
                    self.assertEqual(num(got), num(want), f"{name}.{key}")


# --- ZDoom's actor definitions ----------------------------------------------------------------
ZCLASSES = {                    # class: (file, MT_)
    "DoomPlayer": ("doomplayer.txt", "MT_PLAYER"),
    "ZombieMan": ("possessed.txt", "MT_POSSESSED"),
    "ShotgunGuy": ("possessed.txt", "MT_SHOTGUY"),
    "DoomImp": ("doomimp.txt", "MT_TROOP"),
    "DoomImpBall": ("doomimp.txt", "MT_TROOPSHOT"),
    "Demon": ("demon.txt", "MT_SERGEANT"),
    "Spectre": ("demon.txt", "MT_SHADOWS"),
    "LostSoul": ("lostsoul.txt", "MT_SKULL"),
    "Cacodemon": ("cacodemon.txt", "MT_HEAD"),
    "CacodemonBall": ("cacodemon.txt", "MT_HEADSHOT"),
    "BaronOfHell": ("bruiser.txt", "MT_BRUISER"),
    "BaronBall": ("bruiser.txt", "MT_BRUISERSHOT"),
    "ExplosiveBarrel": ("doommisc.txt", "MT_BARREL"),
    "Rocket": ("weaponrlaunch.txt", "MT_ROCKET"),
    "PlasmaBall": ("weaponplasma.txt", "MT_PLASMA"),
}
LABELS = {"Spawn": "spawnstate", "See": "seestate", "Pain": "painstate", "Melee": "meleestate",
          "Missile": "missilestate", "Death": "deathstate", "XDeath": "xdeathstate"}
WEAPONS = {                     # class: (file, wp_ index in weaponinfo)
    "Fist": ("weaponfist.txt", 0), "Pistol": ("weaponpistol.txt", 1),
    "Shotgun": ("weaponshotgun.txt", 2), "Chaingun": ("weaponchaingun.txt", 3),
    "RocketLauncher": ("weaponrlaunch.txt", 4), "PlasmaRifle": ("weaponplasma.txt", 5),
    "Chainsaw": ("weaponchainsaw.txt", 7),
}
WLABELS = {"Select": 1, "Deselect": 2, "Ready": 3, "Fire": 4, "Flash": 5}
ACTION_NAMES = {                              # ZDoom's name: vanilla's
    "A_NoBlocking": "A_Fall", "A_SposAttackUseAtkSound": "A_SPosAttack",
    "A_SetFloorClip": None,                   # ZDoom's own, on vanilla states
}
ZDOOM_ONLY = {"A_PlayerSkinCheck"}
# properties ZDoom changed from vanilla (the port keeps vanilla's: VanillaTest)
ZDOOM_PROPS = {("BaronBall", "height")}
# sequences whose tics ZDoom changed (the barrel's explosion: 10 -> 5)
ZDOOM_TICS = {"ExplosiveBarrel.Death"}            # zero-tic states of ZDoom's own


def zclass(text: str, name: str):
    """(parent, properties, {label: [(sprite, frame, tics, bright, action), ..., end]})"""
    m = re.search(r"class\s+" + name + r"\s*(?::\s*(\w+))?\s*(?:replaces\s+\w+\s*)?\{", text)
    if not m:
        raise KeyError(name)
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    body = re.sub(r"//[^\n]*", "", text[m.end():i - 1])
    props = {}
    dm = re.search(r"Default\s*\{(.*?)\}", body, re.S)
    if dm:
        for line in dm.group(1).split(";"):
            p = line.strip().split()
            if len(p) == 2 and re.fullmatch(r"-?\d+", p[1]):
                props[p[0].lower()] = int(p[1])
    labels = {}
    sm = re.search(r"States\s*\{(.*)\}", body, re.S)
    if sm:
        cur = []
        for raw in sm.group(1).split("\n"):
            line = raw.strip()
            while True:
                lm = re.match(r"(\w+)\s*:\s*(.*)", line)
                if not lm or lm.group(1).lower() in ("goto",):
                    break
                cur = []
                labels[lm.group(1)] = cur
                line = lm.group(2).strip()
            line = line.rstrip(";").strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith(("loop", "stop", "wait", "goto", "fail")):
                cur.append(("END", line.split()[0].lower(), " ".join(line.split()[1:])))
                continue
            tok = line.split(None, 3)
            if len(tok) < 3 or len(tok[0]) != 4:
                continue
            spr, frames, tics = tok[0].upper(), tok[1], tok[2]
            rest = tok[3] if len(tok) > 3 else ""
            bright = bool(re.search(r"\bbright\b", rest, re.I))
            rest = re.sub(r"\b(bright|fast|slow|nodelay|canraise)\b", "", rest, flags=re.I)
            rest = re.sub(r"\b(light|offset)\s*\([^)]*\)", "", rest, flags=re.I).strip()
            am = re.match(r"(A_\w+)", rest)
            action = am.group(1) if am else None
            action = ACTION_NAMES.get(action, action)
            if not re.fullmatch(r"-?\d+", tics):
                continue
            if int(tics) == 0 and action in ZDOOM_ONLY:
                continue
            for f in frames.strip('"'):
                cur.append((spr, ord(f.upper()) - ord("A"), int(tics), bright, action))
    return (m.group(1), props, labels)


def zchain(states, start, n):
    """n states of our chain from start: (sprite, frame, tics, bright, action)"""
    out, s = [], start
    for _ in range(n):
        if s == "S_NULL":
            break
        st = states[s]
        out.append((st.sprite, st.frame, st.tics, st.bright, st.action))
        s = st.next
    return out


@unittest.skipUnless(ZDOOM and (Path(ZDOOM) / "possessed.txt").is_file(),
                     "no ZDoom actor definitions (set DOOM_ZDOOM_ACTORS)")
class ZDoomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.states, cls.mobjs = ours()
        cls.dir = Path(ZDOOM)

    def resolve(self, cname):
        fname = ZCLASSES.get(cname, (None,))[0] or f"{cname.lower()}.txt"
        parent, props, labels = zclass((self.dir / fname).read_text(errors="replace"), cname)
        if parent and parent in ZCLASSES:
            pp, plabels = self.resolve(parent)
            props = {**pp, **props}
            labels = {**plabels, **labels}
        return props, labels

    def compare_seq(self, where, seq, start):
        frames = [x for x in seq if x[0] != "END"]
        # ZDoom's additions: TNT1 states at the end
        while frames and frames[-1][0] == "TNT1":
            frames.pop()
        got = zchain(self.states, start, len(frames))
        if where in ZDOOM_TICS:
            got = [(a, b, 0, d, e) for a, b, c, d, e in got]
            frames = [(a, b, 0, d, e) for a, b, c, d, e in frames]
        self.assertEqual(got[:len(frames)], frames[:len(got)], where)
        end = [x for x in seq if x[0] == "END"]
        if end and end[0][1] == "loop" and len(got) == len(frames) and frames:
            last = self.states[start]
            for _ in range(len(frames) - 1):
                last = self.states[last.next]
            if last.tics != -1:                 # (a state that lasts forever does not loop)
                self.assertEqual(last.next, start, where + ": loops")

    def test_things(self):
        n = 0
        for cname, (fname, mt) in ZCLASSES.items():
            props, labels = self.resolve(cname)
            info = self.mobjs[mt]
            for key in ("health", "radius", "height", "speed", "painchance", "mass", "damage"):
                if key in props and not (cname == "DoomPlayer" and key == "speed") \
                        and (cname, key) not in ZDOOM_PROPS:
                    # (ZDoom's player Speed is a factor on the movement)
                    ours_key = "spawnhealth" if key == "health" else key
                    self.assertEqual(int(info[ours_key]), props[key], f"{cname} {key}")
            for label, field in LABELS.items():
                if label in labels and info[field] != "S_NULL":
                    self.compare_seq(f"{cname}.{label}", labels[label], info[field])
                    n += 1
        self.assertGreater(n, 40)

    def test_weapons(self):
        text = (PROJECT / "src/game/p_pspr.c").read_text()
        rows = re.findall(r"\{\s*(am_\w+),\s*(S_\w+),\s*(S_\w+),\s*(S_\w+),\s*(S_\w+),\s*(S_\w+)\s*\}", text)
        self.assertEqual(len(rows), 8)
        for cname, (fname, wp) in WEAPONS.items():
            _, _, labels = zclass((self.dir / fname).read_text(errors="replace"), cname)
            for label, col in WLABELS.items():
                if label in labels and rows[wp][col] != "S_NULL":
                    seq = labels[label]
                    if label == "Flash":        # ZDoom repeats its flash sequences
                        seq = seq[:next((i for i, x in enumerate(seq) if x[0] == "END"), len(seq))]
                    self.compare_seq(f"{cname}.{label}", seq, rows[wp][col])


if __name__ == "__main__":
    unittest.main()
