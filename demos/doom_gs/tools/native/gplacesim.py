#!/usr/bin/env python3
"""The placement's model (docs/speed-parts/place.md): recorded call
traffic (gplacerec.py's scenes) replayed by gsim (tools/gplace/gsim.c, a
model of gcall.s's paging) under any placement, and the cost of the
machine: the pages copied at the measured cost of a page, plus a cost a
call that goes through fc_call.

Usage:  python3 tools/native/gplacesim.py --check [SCENE ...]
            (each scene replayed under its own build's placement: the
             loads the model finds must be the loads the run recorded)
        python3 tools/native/gplacesim.py --eval FILE [SCENE ...]
                [--page-us 80] [--call-us 5] [--restore lazy|eager]
                [--fpage-us F] [--request-us R]
            (a placement.json's loads and ms a tic in each scene)

Every load is a memory-API PRIVATE request since the copy engine
(docs/SPEED.md 10): a W slot's load costs --load-us and its pages at
--page-us; a frame slot's (slots 3 and up, main $2000-$5FFF: docs/SPEED.md
9) --request-us and its pages at --fpage-us; a phase's restores are one
request (--request-us), a descriptor each (--desc-us) and their pages at
--fpage-us. The defaults are F1.2.2's as a2vm's profile f122+nod2 prices
them (AMEM_PROFILE: amem_prices); --page-us 80 --load-us 0 --fpage-us 85
--request-us 10 --desc-us 10 were the model of the frame slots on F1.2.1.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs as COSTS  # noqa: E402
from native import gplacerec as REC  # noqa: E402

PAGE_US_NOW = 100.3         # gr_load today, f121 (SPEED.md 2: far_get and
#                             a RAMRD window a page)
PAGE_US_GCOPY = 63.8        # with part paging's far_gcopy (one window)
PAGE_US_CARD = 80.0         # far_gcopy on the card (CALIB.hdv's GC RW
#                             lines, docs/results/calib.md: 79.6-85.3 us a
#                             page; a2vm corrected by them, 2026-10-03)
CALL_US = 5.0               # a call through fc_call / fc_go and fc_ret
# the frame slots' first prices (F1.2.1, docs/SPEED.md 9): a page of a
# PRIVATE copy and a request's own cost as a2vm's f121 modelled them
FPAGE_US_F121 = 85.0
REQUEST_US_F121 = 10.0
# F1.2.2 (docs/SPEED.md 10): every load a PRIVATE request on the copy
# engine, as a2vm's profile prices it (tools/a2vm/costs/appletini.json,
# f122 with the card's setting nod2; tools/a2vm/cost.c a2vm_cost_amem,
# copy_engine, amem_transfer)
AMEM_PROFILE = 'f122+nod2'
# a2vm's own figures on CALIB.hdv's page 2 with that profile (docs/results/
# calib.md, "The card on F1.2.2", the f122+nod2 column): one request of one
# COPY from a RamWorks bank to main, 256 B and 2,048 B (PR2 256, PR2 2K),
# the CPU's part with the PS's (the FIFO, the dispatch, the hold, the
# caches refilled after it)
CALIB_PR2_256_US = 56.123
CALIB_PR2_2K_US = 125.046


def amem_prices(profile: str = AMEM_PROFILE) -> Tuple[float, float, float]:
    """(us a request of one descriptor, us each further descriptor, us a
    byte) of a PRIVATE copy from a RamWorks bank to main, from the
    profile's values: a byte, copy_engine's aligned 8-byte line (two
    4-byte steps of NEXT, SOURCE, DEST, SH_WRITE and ADVANCE, the line's
    read copy_read_wait clocks from PS_REQ, SOURCE again) at fabric_mhz;
    a further descriptor, hw_transfer's AXI accesses (amem_copy_setup_axi
    and amem_copy_end_axi reads, a poll amem_copy_poll_axi, the request's
    read of its 16 bytes, one a word as amem_request_axi's dispatch
    counts them, at axi_us; amem_copy_start_axi writes at axi_write_us);
    a request, CALIB's PR2 256 less its bytes (the CPU's part is not a
    value of the profile but what a2vm runs; PR2 2K checks the byte's
    price)."""
    p = COSTS.parameters(profile)
    byte = (2 * 5 + p['copy_read_wait'] + 1) / 8.0 / p['fabric_mhz']
    slope = (CALIB_PR2_2K_US - CALIB_PR2_256_US) / (2048 - 256)
    if abs(slope - byte) > 0.01 * byte:
        raise SimError('the profile\'s byte %.5f us against CALIB\'s %.5f'
                       % (byte, slope))
    desc = (p['axi_us'] * (p['amem_copy_setup_axi'] + p['amem_copy_poll_axi'] +
                           p['amem_copy_end_axi'] + 16 // 4) +
            p['axi_write_us'] * p['amem_copy_start_axi'])
    return CALIB_PR2_256_US - 256 * byte, desc, byte


class SimError(Exception):
    pass


_REQ, _DESC, _BYTE = amem_prices()
PAGE_US = 256 * _BYTE           # a W slot's page (9.84 us)
LOAD_US = _REQ                  # a W slot's load: its request (46.3 us)
FPAGE_US = PAGE_US              # a frame slot's page, loaded or restored
REQUEST_US = _REQ               # a frame slot's load; a phase's restores
DESC_US = _DESC                 # each further restore (3.5 us)
OUT_GROUP, EMPTY = 254, 255
NG = 256
POLICIES = {'eager': 0, 'lazy': 1}


def scene_meta(scene: str, out: Path = REC.OUT) -> Dict[str, Any]:
    p = out / ('%s.json' % scene)
    if not p.exists():
        raise SimError('no recording of %s (python3 tools/native/'
                       'gplacerec.py %s)' % (scene, scene))
    m = json.loads(p.read_text())
    if m.get('format') != 'gplace-trace 1':
        raise SimError('%s: not a recording' % p)
    return m


def recorded(out: Path = REC.OUT) -> List[str]:
    return sorted(p.stem for p in out.glob('*.json')
                  if (out / (p.stem + '.ev')).exists())


class Model:
    """gsim on some scenes: a common numbering of their units."""

    def __init__(self, scenes: Sequence[str], out: Path = REC.OUT):
        REC.make_tools()
        self.out = out
        self.scenes = list(scenes)
        self.meta = [scene_meta(s, out) for s in scenes]
        self.units: List[str] = [REC.OUTSIDE, REC.CORE]
        self.uid = {REC.OUTSIDE: 0, REC.CORE: 1}
        for m in self.meta:
            for u in m['units']:
                if u not in self.uid:
                    self.uid[u] = len(self.units)
                    self.units.append(u)
        self.tmp = tempfile.TemporaryDirectory(prefix='tmp-gplacesim-',
                                               dir=str(REC.BUILD))
        args = [str(REC.GSIM), str(len(self.units)),
                str(self.uid.get(REC.TIC_UNIT, 0))]
        for s, m in zip(scenes, self.meta):
            mp = Path(self.tmp.name) / ('%s.map' % s)
            mp.write_text(''.join('%d %d\n' % (i, self.uid[u])
                                  for i, u in enumerate(m['units'])))
            args += [str(out / ('%s.ev' % s)), str(mp)]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     universal_newlines=True)
        self.glue = {}
        for m in self.meta:
            for name, g in m['facts'].get('glue', {}).items():
                gl = self.glue.setdefault(name, {})
                gl['slot'] = int(m['facts']['slots'][str(g)])
                gl['pages'] = int(m['facts']['pages'][str(g)])

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=60)
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _ask(self, mode: str, policy: int, grp: Sequence[int],
             slot: Sequence[int], pages: Sequence[int]) -> List[str]:
        line = '%s %d %s %s %s\n' % (mode, policy, ' '.join(map(str, grp)),
                                     ' '.join(map(str, slot)),
                                     ' '.join(map(str, pages)))
        self.proc.stdin.write(line)
        self.proc.stdin.flush()
        if mode == 'D':
            out = []
            while True:
                r = self.proc.stdout.readline()
                if not r:
                    raise SimError('gsim ended')
                r = r.strip()
                if r == 'end':
                    return out
                out.append(r)
        r = self.proc.stdout.readline()
        if not r:
            raise SimError('gsim ended')
        return r.split()

    def vectors(self, routines: Dict[str, int], groups: Sequence[Dict],
                pages_of: Sequence[int], glue_base: Optional[int] = None,
                build_glue: Optional[Dict[str, int]] = None
                ) -> Tuple[List[int], List[int], List[int]]:
        """gsim's arrays: each unit's group (a table routine by
        `routines`, 0 when it names none: the core), each group's slot and
        pages. groups: [{'slot': s}] numbered from 1; the glue's groups
        after them (glue_base + offset, as the play link numbers them) or
        at their build's numbers."""
        from native import playlayout as PL
        n = len(groups)
        slot = [0] * NG
        pages = [0] * NG
        for i, g in enumerate(groups, 1):
            slot[i] = int(g['slot'])
            pages[i] = int(pages_of[i - 1])
        glue_g = {}
        for name, off, s in PL.DL_GROUPS:
            if build_glue is not None and name in build_glue:
                gg = int(build_glue[name])
            else:
                gg = (glue_base if glue_base is not None else n) + off
            glue_g['@glue:' + name] = gg
            if name in self.glue:
                slot[gg] = self.glue[name]['slot']
                pages[gg] = self.glue[name]['pages']
        grp = []
        for u in self.units:
            if u == REC.OUTSIDE:
                grp.append(OUT_GROUP)
            elif u == REC.CORE:
                grp.append(0)
            elif u in glue_g:
                grp.append(glue_g[u])
            elif u.startswith('@group:'):
                raise SimError('the recording has code of group %s that '
                               'no routine of the table holds' % u[7:])
            else:
                grp.append(int(routines.get(u, 0)))
        for i, g in enumerate(grp):
            if g not in (0, OUT_GROUP) and slot[g] == 0:
                raise SimError('%s: group %d has no slot' % (
                    self.units[i], g))
        return grp, slot, pages

    def run(self, vec, policy: int = 0) -> List[Dict[str, float]]:
        f = list(map(int, self._ask('P', policy, *vec)))
        out = []
        for i in range(len(self.scenes)):
            (loads, pages, cross, tics, phases, fpages, rpages, floads,
             restores, rreqs) = f[10 * i:10 * i + 10]
            out.append({'loads': loads, 'pages': pages, 'cross': cross,
                        'tics': tics, 'phases': phases, 'fpages': fpages,
                        'rpages': rpages, 'floads': floads,
                        'restores': restores, 'rreqs': rreqs})
        return out

    def check(self, vec, policy: int = 0) -> List[Dict[str, int]]:
        f = list(map(int, self._ask('V', policy, *vec)))
        return [dict(zip(('bad_phases', 'rec_loads', 'sim_loads', 'rec_sum',
                          'sim_sum'), f[5 * i:5 * i + 5]))
                for i in range(len(self.scenes))]

    def causes(self, vec, policy: int = 0) -> List[Tuple]:
        out = []
        for line in self._ask('D', policy, *vec):
            t, kind, a, b, loads, pages = map(int, line.split())
            out.append((self.scenes[t], 'return' if kind else 'call',
                        self.units[a], self.units[b], loads, pages))
        return out


def cost_of(r: Dict[str, float], page_us: float, call_us: float,
            fpage_us: float = FPAGE_US, request_us: float = REQUEST_US,
            load_us: float = LOAD_US, desc_us: float = DESC_US) -> float:
    """us a tic: the W slots' loads (a request each) and their pages, the
    calls through fc_call, the frame slots' PRIVATE copies (each load a
    request; a phase's restores one request, a descriptor each; the
    pages of both)."""
    floads = r.get('floads', 0)
    restores = r.get('restores', 0)
    rreqs = r.get('rreqs', restores)
    return ((r['loads'] - floads) * load_us + r['pages'] * page_us +
            r['cross'] * call_us +
            (r.get('fpages', 0) + r.get('rpages', 0)) * fpage_us +
            (floads + rreqs) * request_us +
            (restores - rreqs) * desc_us) / max(r['tics'], 1)


def build_vectors(model: Model, scene_index: int):
    """The scene's own build's placement as gsim's arrays (its groups at
    their numbers)."""
    m = model.meta[scene_index]
    f = m['facts']
    place = f['placement']
    ng = max([int(k) for k in f['slots']] + [0])
    groups = []
    pages = []
    for g in range(1, ng + 1):
        groups.append({'slot': int(f['slots'].get(str(g), 1))})
        pages.append(int(f['pages'].get(str(g), 0)))
    return model.vectors(place, groups, pages,
                         build_glue={k: int(v) for k, v in
                                     f.get('glue', {}).items()})


def check_scenes(scenes: Sequence[str], out: Path = REC.OUT) -> List[str]:
    """Each scene under its own build's placement and restore (gcall.s's,
    as the recording names it): the model's loads against the recorded
    ones."""
    lines = []
    for s in scenes:
        with Model([s], out) as model:
            policy = POLICIES[model.meta[0]['facts'].get('restore',
                                                         'eager')]
            r = model.check(build_vectors(model, 0), policy)[0]
            lines.append('%s: %d recorded loads, %d modelled (groups\' sums '
                         '%d, %d), %d phases differ' % (
                             s, r['rec_loads'], r['sim_loads'], r['rec_sum'],
                             r['sim_sum'], r['bad_phases']))
            if r['bad_phases'] or r['rec_loads'] != r['sim_loads']:
                lines[-1] += '  MISMATCH'
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('scenes', nargs='*')
    parser.add_argument('--out', type=Path, default=REC.OUT)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--eval', type=Path)
    parser.add_argument('--page-us', type=float, default=PAGE_US)
    parser.add_argument('--call-us', type=float, default=CALL_US)
    parser.add_argument('--fpage-us', type=float, default=FPAGE_US)
    parser.add_argument('--request-us', type=float, default=REQUEST_US)
    parser.add_argument('--load-us', type=float, default=LOAD_US)
    parser.add_argument('--desc-us', type=float, default=DESC_US)
    parser.add_argument('--restore', choices=sorted(POLICIES),
                        default='lazy')
    args = parser.parse_args(argv)
    scenes = args.scenes or recorded(args.out)
    if args.check:
        lines = check_scenes(scenes, args.out)
        print('\n'.join(lines))
        return 1 if any('MISMATCH' in x for x in lines) else 0
    if args.eval:
        from native import gplace as GP
        place = json.loads(args.eval.read_text())
        with Model(scenes, args.out) as model:
            for s, r in zip(scenes, GP.evaluate(model, place,
                                                POLICIES[args.restore],
                                                args.page_us,
                                                args.call_us, args.fpage_us,
                                                args.request_us,
                                                args.load_us, args.desc_us)):
                print('%-7s %7.2f loads a tic %8.1f pages a tic %7.1f cross '
                      'calls a tic %6.1f PRIVATE pages, %4.1f requests a '
                      'tic  %8.2f ms a tic' % (
                          s, r['loads_a_tic'], r['pages_a_tic'],
                          r['cross_a_tic'], r['private_pages_a_tic'],
                          r['requests_a_tic'], r['ms_a_tic']))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
