#!/usr/bin/env python3
"""The generated tic streams G1-G10 (milestone 10, docs/GAME.md 3.7): demo
lumps written from a seeded policy, played on ref816, measured, and kept
only when the reference passes them exactly.

Usage:  python3 tools/native/ticgen.py --stream G1 [--seed N]
        python3 tools/native/ticgen.py --search G1 --seeds 1-20
        python3 tools/native/ticgen.py --report

A lump has DEMO3's header (version 1.9: the skill and the map of the
stream, episode 1, single player) and TICS tics of 4 bytes (forward,
side, the angle's high byte, the buttons), then 0x80. The policy (a
random.Random of the seed) walks, runs, strafes and turns in spans,
fires in bursts, uses often, changes weapons through BT_CHANGE, and after
a span with no move presses use (a reborn after a death).

Each stream is played on ref816 with the lump placed as DEMO3
(lumps.py's --wad/--lump, the title loop to the demo's end) and scanned
(ticcap.scan: call logs only): its coverage (ticcap.COVERAGE's calls,
the zone mobjs made), its T3 windows and validcount's wraps, and the
game's divides by zero. **A seed is rejected** when a wrap falls in a T3
window or the run divides by zero (GAME.md 3.7, review 10). An accepted
stream's lump goes to build/native/game/shared/streams/GN.lmp with its
scan in GN.json; ticcap.py makes its tic reference like the fixed
runs'.
"""

import argparse
import json
import random
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import gamecap as GC, glayout as GL, ticcap as TC  # noqa: E402
from ref816 import lumps  # noqa: E402

OUT = GL.SHARED / 'streams'
TICS = 2000
VERSION = 109
# (stream, map, skill, what it aims at: GAME.md 3.7's table). The skills
# as the game numbers them: 0 baby, 1 easy, 2 medium, 3 hard (UV,
# upstream's sk_hard), 4 nightmare
UV, NIGHTMARE, HARD, MEDIUM, EASY, BABY = 3, 4, 3, 2, 1, 0
STREAMS = {
    'G1': (1, UV, 'zone mobjs from the first shot, barrels'),
    'G2': (9, UV, 'zone mobjs, a fight'),
    'G3': (2, NIGHTMARE, 'deaths and reborns, nightmare respawn'),
    'G4': (3, HARD, 'the deepest flood, switches'),
    'G5': (4, MEDIUM, 'lifts, doors, strafing runs'),
    'G6': (5, MEDIUM, 'teleporters, slides along walls'),
    'G7': (6, HARD, 'the largest pool, long traces'),
    'G8': (7, EASY, 'damage floors, pickups of every kind'),
    'G9': (8, UV, 'barons, A_BossDeath'),
    'G10': (1, BABY, 'weapon changes and ammo, use on every line'),
}
BT_ATTACK, BT_USE, BT_CHANGE = 1, 2, 4
BT_WEAPONSHIFT = 3


def make_lump(seed: int, gamemap: int, skill: int, tics: int = TICS
              ) -> bytes:
    """A demo lump from the seeded policy."""
    rnd = random.Random(seed)
    out = bytearray([VERSION, skill, 1, gamemap, 0, 0, 0, 0, 0, 1, 0, 0, 0])
    span = 0
    fwd = side = turn = 0
    still = 0
    fire = 0
    for t in range(tics):
        if span <= 0:
            span = rnd.randint(8, 70)
            kind = rnd.random()
            run = rnd.random() < 0.4
            speed = 50 if run else 25
            fwd = speed if kind < 0.55 else (-speed if kind < 0.65 else 0)
            side = rnd.choice((0, 0, 24, -24, 40, -40))
            turn = rnd.choice((0, 0, 0, 3, -3, 8, -8))
            still = 6 if rnd.random() < 0.08 else 0
        span -= 1
        buttons = 0
        if fire > 0:
            buttons |= BT_ATTACK
            fire -= 1
        elif rnd.random() < 0.05:
            fire = rnd.randint(3, 25)
        if rnd.random() < 0.08 or still:
            buttons |= BT_USE
        if rnd.random() < 0.01:
            buttons |= BT_CHANGE | (rnd.randint(0, 6) << BT_WEAPONSHIFT)
            buttons &= ~BT_ATTACK
        f, s_, a = (0, 0, 0) if still else (fwd, side, turn)
        if still:
            still -= 1
        out += struct.pack('<bbbB', f, s_, a, buttons & 0xFF)
    out.append(lumps.DEMO_END)
    return bytes(out)


def lump_options(path: Path, dest: int = lumps.DEST) -> List[str]:
    return ['--wad', '%06X' % lumps.wad_address(GC.symbols()),
            '--lump', '%s:%06X:%s' % (lumps.ENTRY, dest, path)]


def play(name: str, seed: int, out: Path = OUT, say=print
         ) -> Dict[str, Any]:
    gamemap, skill, aim = STREAMS[name]
    lump = make_lump(seed, gamemap, skill)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / ('%s-seed%d.lmp' % (name, seed))
    tmp.write_bytes(lump)
    try:
        res = TC.scan('demo3', lumps.demo_script(gamemap, GC.DEMO_SECONDS),
                      lump_options(tmp), say=say)
    finally:
        pass
    res.update(stream=name, seed=seed, gamemap=gamemap, skill=skill,
               aim=aim, tics_in_lump=TICS)
    res['rejected'] = []
    if res['wraps_in_windows']:
        res['rejected'].append('validcount wraps in a T3 window')
    if res['div0']:
        res['rejected'].append('divides by zero (%d)' % len(res['div0']))
    if res['problems']:
        res['rejected'].append('the run: %s' % '; '.join(res['problems']))
    if res['rejected']:
        tmp.unlink()
    else:
        tmp.replace(out / (name + '.lmp'))
        (out / (name + '.json')).write_text(json.dumps(res, indent=1) + '\n')
    return res


def parse_seeds(text: str) -> List[int]:
    out: List[int] = []
    for part in text.split(','):
        if '-' in part:
            a, b = part.split('-')
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--stream')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--search')
    parser.add_argument('--seeds', default='1-10')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args(argv)
    if args.report:
        for name in STREAMS:
            p = OUT / (name + '.json')
            if p.exists():
                r = json.loads(p.read_text())
                print('%s: seed %d, E1M%d skill %d, %d tics, coverage %s, '
                      'zone mobjs %d' % (name, r['seed'], r['gamemap'],
                                         r['skill'], r['tics'],
                                         r['coverage'], r['zone_mobjs']))
        return 0
    name = args.stream or args.search
    if not name or name not in STREAMS:
        parser.error('--stream or --search one of %s' % ', '.join(STREAMS))
    seeds = [args.seed] if args.stream else parse_seeds(args.seeds)
    for seed in seeds:
        r = play(name, seed)
        print('%s seed %d: %d tics, %d setups, windows %d, wraps %d (%d in '
              'a window), div0 %d, zone mobjs %d, coverage %s: %s' % (
                  name, seed, r['tics'], len(r['setups']),
                  len(r['windows']), len(r['wraps']), r['wraps_in_windows'],
                  len(r['div0']), r['zone_mobjs'], r['coverage'],
                  'REJECTED: ' + '; '.join(r['rejected']) if r['rejected']
                  else 'accepted'))
        if not r['rejected']:
            return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
