#!/usr/bin/env python3
"""Struct field offsets of the game's C headers for its assembly.

    python3 tools/gen_offsets.py            # writes src/game/goffsets.inc
    python3 tools/gen_offsets.py --check    # exit 1 if it is stale

The game's assembly modules (src/game/*.s) share structs with its C
(p_local.h, info.h): mobj_t, sobj_t, line_t, player_t... The offsets are
not written by hand: the fields are read from the headers, a probe C file
asks cc65 itself for offsetof() and sizeof() of each, and the answers
become ca65 constants (MO_X = offsetof(mobj_t, x), MO_SIZE, ...). cc65
lays structs out without padding, so these are the 6502's offsets.
The enumerators and macros named in CONSTANTS (states, types, sounds of
info.h, limits of p_local.h, the specials' enums of p_spec.h) are asked
for the same way, under their own names.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src/game"
OUT = SRC / "goffsets.inc"
DATA = PROJECT / "build/data"

# typedef name -> prefix of its constants
STRUCTS = {
    "thinker_t": "TH", "line_t": "LI", "divline_t": "DL", "intercept_t": "IN",
    "mobj_t": "MO", "sobj_t": "SO", "ticcmd_t": "TC", "pspdef_t": "PS",
    "weaponinfo_t": "WI", "player_t": "PL", "mobjinfo_t": "MI", "levarr_t": "LA",
}

# info.h / p_local.h constants the assembly uses, under their C names
CONSTANTS = [
    "MT_PLAYER", "MT_PUFF", "MT_BLOOD", "MT_SKULL", "MT_TFOG", "MT_TELEPORTMAN",
    "NUMMOBJTYPES", "S_NULL", "S_GIBS", "S_PLAY", "S_PLAY_RUN1", "S_PLAY_ATK1",
    "S_PUFF3", "S_BLOOD2", "S_BLOOD3", "sfx_noway", "sfx_oof",
    "MAXACTORS", "THINKER_BLOCK", "THINKER_BLOCKS", "MT_IFOG", "AC_Look",
    "sk_nightmare", "CF_NOMOMENTUM", "CRASH_MOBJS", "CRASH_ARENA", "ARENA_RESERVE",
    "AC_FIRST_WEAPON", "S_PLAY_ATK2", "S_SAW", "S_CHAIN1",
    "sfx_sawup", "sfx_sawidl", "sfx_punch", "sfx_sawful", "sfx_sawhit", "sfx_pistol",
    "sfx_shotgn", "MT_ROCKET", "MT_PLASMA",
    "wp_fist", "wp_pistol", "wp_shotgun", "wp_chaingun", "wp_missile", "wp_plasma", "wp_bfg",
    "wp_chainsaw", "NUMWEAPONS", "wp_nochange", "am_clip", "am_shell", "am_cell", "am_misl",
    "am_noammo", "pw_invulnerability", "pw_strength", "pw_invisibility", "pw_ironfeet",
    "pw_infrared", "PST_LIVE", "PST_DEAD", "PST_REBORN", "BT_ATTACK", "BT_USE", "BT_CHANGE",
    "BT_WEAPONMASK", "BT_WEAPONSHIFT", "CF_NOCLIP", "ps_weapon", "ps_flash", "NUMPSPRITES",
    # the monsters part (a_sight.s, a_enemy.s, a_inter.s)
    "MT_POSSESSED", "MT_SHOTGUY", "MT_BRUISER", "MT_CLIP", "MT_SHOTGUN", "MT_TROOPSHOT",
    "MT_HEADSHOT", "MT_BRUISERSHOT", "sfx_posit1", "sfx_posit2", "sfx_posit3", "sfx_bgsit1",
    "sfx_bgsit2", "sfx_podth1", "sfx_podth2", "sfx_podth3", "sfx_bgdth1", "sfx_bgdth2",
    "sfx_claw", "sfx_slop", "sfx_pldeth", "sfx_itemup", "sfx_getpow", "sfx_wpnup",
    "sk_baby", "pw_allmap", "NUMAMMO", "BASETHRESHOLD", "MAXHEALTH", "CF_GODMODE",
    "INVULNTICS", "INVISTICS", "INFRATICS", "IRONTICS", "DI_NODIR", "lowerFloorToLowest",
    "it_bluecard", "it_yellowcard", "it_redcard", "it_blueskull", "it_yellowskull", "it_redskull",
    "MSG_GOTARMOR", "MSG_GOTMEGA", "MSG_GOTHTHBONUS", "MSG_GOTARMBONUS", "MSG_GOTSUPER",
    "MSG_GOTBLUECARD", "MSG_GOTYELWCARD", "MSG_GOTREDCARD", "MSG_GOTBLUESKUL",
    "MSG_GOTYELWSKUL", "MSG_GOTREDSKULL", "MSG_GOTSTIM", "MSG_GOTMEDINEED", "MSG_GOTMEDIKIT",
    "MSG_GOTINVUL", "MSG_GOTBERSERK", "MSG_GOTINVIS", "MSG_GOTSUIT", "MSG_GOTMAP",
    "MSG_GOTVISOR", "MSG_GOTCLIP", "MSG_GOTCLIPBOX", "MSG_GOTROCKET", "MSG_GOTROCKBOX",
    "MSG_GOTCELL", "MSG_GOTCELLBOX", "MSG_GOTSHELLS", "MSG_GOTSHELLBOX", "MSG_GOTBACKPACK",
    "MSG_GOTCHAINGUN", "MSG_GOTCHAINSAW", "MSG_GOTLAUNCHER", "MSG_GOTPLASMA", "MSG_GOTSHOTGUN",
    # the specials part (a_spec.s, a_movers.s)
    "MSG_PD_BLUEO", "MSG_PD_REDO", "MSG_PD_YELLOWO", "MSG_PD_BLUEK", "MSG_PD_REDK",
    "MSG_PD_YELLOWK", "sfx_doropn", "sfx_dorcls", "sfx_bdopn", "sfx_bdcls", "sfx_pstart",
    "sfx_pstop", "sfx_stnmov", "sfx_swtchn", "sfx_telept",
    "vld_normal", "vld_close30ThenOpen", "vld_close", "vld_open", "vld_raiseIn5Mins",
    "vld_blazeRaise", "vld_blazeOpen", "vld_blazeClose", "lowerFloor", "turboLower",
    "raiseFloor", "raiseFloorToNearest", "raiseToTexture", "lowerAndChange", "raiseFloor24",
    "raiseFloor24AndChange", "raiseFloorCrush", "raiseFloorTurbo", "donutRaise", "raiseFloor512",
    "perpetualRaise", "downWaitUpStay", "raiseAndChange", "raiseToNearestAndChange", "blazeDWUS",
    "lowerToFloor", "raiseToHighest", "lowerAndCrush", "crushAndRaise", "fastCrushAndRaise",
    "silentCrushAndRaise", "build8", "turbo16",
]


def fields(text: str, typedef: str) -> list[str]:
    m = re.search(r"typedef struct\s*\w*\s*\{([^{}]*)\}\s*" + re.escape(typedef) + r"\s*;", text, re.S)
    if not m:
        raise ValueError(f"no struct {typedef}")
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    out = []
    for decl in body.split(";"):
        decl = decl.strip()
        if not decl:
            continue
        if "(" in decl:                      # function pointer: ret (*name)(args)
            out.append(re.search(r"\(\s*\*\s*(\w+)\s*\)", decl).group(1))
            continue
        parts = decl.replace("*", " ").split(",")
        # the first part is "type name", the others just names
        parts[0] = parts[0].split()[-1]
        for part in parts:
            name = re.sub(r"\[.*?\]", "", part).strip()
            if name:
                out.append(name)
    return out


def generate() -> str:
    text = (SRC / "p_local.h").read_text() + (SRC / "info.h").read_text()
    probe = ["#include <stddef.h>", '#include "p_spec.h"', "const unsigned int probe[] = {"]
    names = []
    for typedef, prefix in STRUCTS.items():
        for f in fields(text, typedef):
            probe.append(f"    offsetof({typedef}, {f}),")
            names.append(f"{prefix}_{f.upper()}")
        probe.append(f"    sizeof({typedef}),")
        names.append(f"{prefix}_SIZE")
    for c in CONSTANTS:
        probe.append(f"    (unsigned int)({c}),")
        names.append(c)
    probe.append("};")
    with tempfile.TemporaryDirectory() as tmp:
        c = Path(tmp) / "probe.c"
        s = Path(tmp) / "probe.s"
        c.write_text("\n".join(probe) + "\n")
        subprocess.run(["cc65", "-t", "none", "--cpu", "65c02", "--standard", "c99", "-O",
                        "-I", str(SRC), "-I", str(DATA), "-o", str(s), str(c)], check=True)
        values = [int(v, 16) for v in re.findall(r"\.word\s+\$([0-9A-F]+)", s.read_text())]
    if len(values) != len(names):
        raise ValueError(f"{len(values)} values for {len(names)} names")
    lines = ["; Generated by tools/gen_offsets.py from src/game/p_local.h and info.h",
             "; (cc65's own offsetof/sizeof) -- do not edit.", ""]
    for n, v in zip(names, values):
        lines.append(f"{n:24s} = {v}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = generate()
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print(f"stale: {OUT}")
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
