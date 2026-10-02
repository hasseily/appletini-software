#!/usr/bin/env python3
"""The canonical comparison of milestone 10 (docs/GAME.md 3.5, 3.6): the
routine mode and the tic mode, with their exclusions, each named here with
its reason and counted in every report.

    compare(ref, nat, mode, window=None, front=False)
                            the differences of two canonical states (the
                            bridge's canonical.diff) after the mode's
                            exclusions; window: the T3 zone window is open
                            (tic mode)
    digests(state, mode, window)
                            one SHA-256 a kind (and one of the globals) of
                            the state as the mode compares it: the tic
                            mode's per-tic record (ticcap.py, ticrun.py)
    strip(state, skip)      the state without the skipped globals and
                            fields (the port writer's input: the layout
                            holds no excluded field)
    exclusions(mode)        the table: number, what, why

Usage:  python3 tools/native/gcanon.py --table [routine|tic]
        python3 tools/native/gcanon.py A.json B.json [--mode tic]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import canonical, schema  # noqa: E402
from bridge.fields import R, to_json  # noqa: E402
from bridge.port import STALE  # noqa: E402

MODES = ('routine', 'tic')

# (number, what, why): GAME.md 3.5's R1-R6 and 3.6's T1-T8. The ones that
# are not canonical fields (scratch, zero page, the stack, the zone's
# headers, the sound channels, the command ring's other entries) are kept
# out by the bridge's model itself; they are listed for the report.
ROUTINE_EXCLUSIONS = [
    ('R1', 'tic scratch, zero page outside the persistent bytes, W, the '
     'stack below the caller', 'the routine\'s own scratch: not state '
     'between calls (outside the canonical model)'),
    ('R2', 'upstream\'s scratch of the game units but the declared outputs',
     'the bridge\'s exclusions; a result returned in scratch is an output '
     'and compared (args.json)'),
    ('R3', 'the kind cache (the CLEAN bit of KIND)', 'a cache by '
     'construction (outside the canonical model: the manifest\'s enum '
     'mask)'),
    ('R4', 'line.gstamp, GW_TAG, G_ID', 'written only by the dead guard, '
     'which the release never calls'),
    ('R5', 'TP_HW, PI_PREV*', 'upstream\'s caches that change no result'),
    ('R6', 'the sound channels', 'outside the canonical model; the sound '
     'events are compared as a report'),
]
TIC_EXCLUSIONS = [
    ('T1', 'line.r_validcount; line.r_flags in FRONT runs', 'the '
     'renderer\'s fields: no game unit reads them'),
    ('T2', 'R2-R5', 'as in routine mode'),
    ('T3', 'the zone window: mobj.sightline, the hint (sighthint), the '
     'lines\' validcount stamps as "equal to validcount" or "older", '
     'CS_PREV1/2 as "stale or not"', 'upstream keys the hint and CS_PREV '
     'by the zone mobj\'s address; from the first tic after a zone mobj '
     'is t1 of P_CheckSight or a zone mobj CS_PREV names is removed, to '
     'the next setup'),
    ('T4', 'the tic command ring (g_game65.s:cmds)', 'input built ahead of '
     'the tic; the entry read is compared as player.cmd'),
    ('T5', 'the zone allocator\'s headers, slack and free bytes', 'the '
     'bridge\'s exclusion (outside the canonical model)'),
    ('T6', 'sound, music, the status bar, the HUD but player.message, the '
     'automap, menus, the title page', 'milestone 11 (outside the '
     'canonical model)'),
    ('T7', 'in FULL runs a frame whose RULES is not 0: its records and SHR',
     'owner question 13 (frame level, not game state)'),
    ('T8', 'a tic in which the native divides by zero (GT_DIV0)', 'owner '
     'question 5: the comparison of the run ends at that tic, reported '
     'by name; a new run continues from the reference\'s next tic'),
]

PI_PREFIX = 'PI_PREV'


def exclusions(mode: str) -> List[Tuple[str, str, str]]:
    if mode == 'routine':
        return list(ROUTINE_EXCLUSIONS)
    if mode == 'tic':
        return list(TIC_EXCLUSIONS)
    raise ValueError(mode)


def skips(mode: str, state: Optional[Dict[str, Any]] = None,
          front: bool = False) -> List[str]:
    """canonical.diff's skip names of the mode (schema.compare_skips, the
    PI_PREV caches of R5 present in the state, T1's r_flags in FRONT
    runs)."""
    out = list(schema.compare_skips(None, mode))
    if state is not None:
        out += [g for g in state.get('globals', {})
                if g.split(':')[-1].startswith(PI_PREFIX)]
    if mode == 'tic' and front:
        out.append('line.r_flags')
    return out


def strip(state: Dict[str, Any], skip: Iterable[str]) -> Dict[str, Any]:
    """The state without the skipped globals and fields."""
    skip = set(skip)
    out = {k: v for k, v in state.items() if k not in ('globals',
                                                       'objects')}
    out['globals'] = {k: v for k, v in state.get('globals', {}).items()
                      if k not in skip}
    objects = {}
    for kind, table in state.get('objects', {}).items():
        drop = {s.split('.', 1)[1] for s in skip
                if s.startswith(kind + '.') or s.startswith('*.')}
        if drop:
            objects[kind] = {i: {f: v for f, v in o.items()
                                 if f not in drop}
                             for i, o in table.items()}
        else:
            objects[kind] = table
    out['objects'] = objects
    return out


def windowed(state: Dict[str, Any]) -> Dict[str, Any]:
    """T3: the state as the zone window compares it: no sightline, no
    hint; the lines' stamps as "equal" or "older" than validcount;
    CS_PREV1/2 as "stale" or "set"."""
    vc = state.get('globals', {}).get('p_map65.s:validcount')
    out = strip(state, ['mobj.sightline', 'zmobj.sightline'])
    out['objects'] = dict(out['objects'])
    out['objects'].pop('sighthint', None)
    lines = out['objects'].get('line')
    if lines is not None:
        out['objects']['line'] = {
            i: dict(o, validcount=('equal' if o.get('validcount') == vc
                                   else 'older'))
            if 'validcount' in o else o for i, o in lines.items()}
    g = dict(out['globals'])
    for name in ('p_sight65.s:CS_PREV1', 'p_sight65.s:CS_PREV2'):
        if name in g:
            g[name] = 'stale' if g[name] == STALE else 'set'
    out['globals'] = g
    return out


def compare(ref: Dict[str, Any], nat: Dict[str, Any], mode: str,
            window: bool = False, front: bool = False,
            limit: int = 40) -> List[str]:
    """The differences of nat against ref after the mode's exclusions."""
    if mode not in MODES:
        raise ValueError(mode)
    skip = skips(mode, ref, front)
    a, b = ref, nat
    if mode == 'tic' and window:
        a, b = windowed(ref), windowed(nat)
    return canonical.diff(a, b, skip=skip, limit=limit)


def _canon_json(value: Any) -> bytes:
    return json.dumps(to_json(value), sort_keys=True,
                      separators=(',', ':')).encode()


def digests(state: Dict[str, Any], mode: str = 'tic',
            window: bool = False, front: bool = False) -> Dict[str, str]:
    """One SHA-256 (hex, 16 digits) a kind and one for the globals, of
    the state as `mode` compares it."""
    s = strip(state, skips(mode, state, front))
    if mode == 'tic' and window:
        s = windowed(s)
    out = {'globals': hashlib.sha256(_canon_json(s['globals'])).hexdigest()[
        :16]}
    for kind, table in sorted(s['objects'].items()):
        out[kind] = hashlib.sha256(_canon_json(
            {str(k): v for k, v in table.items()})).hexdigest()[:16]
    return out


# a kind's digest when the state holds none of it: canonical.diff takes a
# missing kind as an empty table (the reference's Reader leaves a kind with
# no object out, the port reader can give it empty: the final integration,
# a door made and removed)
EMPTY_TABLE = hashlib.sha256(_canon_json({})).hexdigest()[:16]


def differing_kinds(a: Dict[str, str], b: Dict[str, str]) -> List[str]:
    return sorted(k for k in set(a) | set(b)
                  if a.get(k, EMPTY_TABLE) != b.get(k, EMPTY_TABLE))


def ref_value(value: Any) -> Any:
    """A declared output's value for the report."""
    if isinstance(value, R):
        return '%s[%s]%s' % (value.kind, value.id, '.' + value.field
                             if value.field else '')
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('states', nargs='*', type=Path)
    parser.add_argument('--mode', default='routine', choices=MODES)
    parser.add_argument('--window', action='store_true')
    parser.add_argument('--table', nargs='?', const='both')
    args = parser.parse_args(argv)
    if args.table:
        for mode in (MODES if args.table == 'both' else (args.table,)):
            print('%s mode:' % mode)
            for n, what, why in exclusions(mode):
                print('  %-3s %s: %s' % (n, what, why))
        return 0
    if len(args.states) != 2:
        parser.error('two canonical states, or --table')
    a, b = (canonical.load(p) for p in args.states)
    diff = compare(a, b, args.mode, window=args.window)
    for line in diff:
        print(line)
    print('%d differences' % len(diff))
    return 1 if diff else 0


if __name__ == '__main__':
    sys.exit(main())
