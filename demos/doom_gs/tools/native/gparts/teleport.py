#!/usr/bin/env python3
"""Part teleport's checkpoint (milestone 10, docs/GAME.md 2.4 row teleport,
3.5; docs/game-parts/teleport.md): routine mode on the part's entries
(EV_Teleport, P_TeleportMove, stompThing under it, lnTele through
P_CrossSpecialLine), times20's random check and the planted bugs, in the
lean form the owner asked for on 2026-10-02 (at most LEAN calls a routine,
one poisoned machine, $A5).

Usage:  python3 tools/native/gparts/teleport.py --capture
        python3 tools/native/gparts/teleport.py --synthetic [--jobs 2]
        python3 tools/native/gparts/teleport.py --check [--jobs 2]
        python3 tools/native/gparts/teleport.py --random [--count N]
        python3 tools/native/gparts/teleport.py --plants
        python3 tools/native/gparts/teleport.py --report

No run of the survey (demo3, DEMO1, DEMO2, newgame, tour) calls a routine
of the part (docs/game-parts/teleport.md section 1: 0 calls of each
entry), so the checkpoint is synthetic, as GAME.md 2.4 says: on an in-play
state of each of the nine maps (a captured P_UpdateSpecials of the tour,
as parts lines and evworld take them), ref816 --call of upstream's routine
with its arguments poked, each call on the state the calls before it in
its sequence left.

Everything it writes is under build/native/game/teleport/ (the part's own
directory): the bases (cases/tour/P_UpdateSpecials/hNNNNNNNN.case.z and
the run's base.ram.z, through tools/native/gamecap.py with its case
directory pointed here), the synthetic calls (synthetic/), report.json.
The shared outputs (build/native/game/shared/) are read only.

--capture: the tour's P_UpdateSpecials every TOUR_STEP-th call (part
lines' choice), the in-play states of the nine maps.

--synthetic: on each map with teleport lines (special 97, crosstab's
lnTele, p_switch65.s:598), ref816 --call of
  - on the first line of each map, a sequence: a monster crosses (moved,
    its reaction time untouched), a second one with the first made not
    shootable (no stomp: moved), the player onto it (telefrag:
    P_DamageMobj kills it), a third monster onto the player (a shootable
    thing in the way and no telefrag: blocked), the player from the back
    side (EV_Teleport's side test: nothing);
  - P_CrossSpecialLine of every other teleport line by the player (the
    destination's fogs, angle, momentum, viewz, reaction time), then by a
    monster while the budget lasts (LEAN calls of the routine);
  - EV_Teleport of a missile (a monster with MF_MISSILE poked: nothing,
    the crossing filters the missiles of E1 before EV_Teleport);
  - P_TeleportMove with boss set: a zombieman, then a second monster, beside
    the destination (a telefrag by a monster), then the player's crossing
    onto both: its first stomp's kill drops an item, which upstream's
    P_CreateSecNodeList makes the later stomps' tmx, tmy (request R4).

--check: the synthetic calls from the poisoned machine $A5 under f121 and
fastpath, compared with ref816 in gcanon.py's routine mode (R1-R7), the
declared outputs of src/native/game/teleport/args.json (the result;
tmthing, tmx, tmy, tmfloorz, tmceilingz, tmdropoffz, numspechit,
ceilingline), the teleport's sound events (two sfx_telept, at the fogs:
R6's events, compared), no stray write. A call that reaches an unbuilt
routine stops at its FCALL or DCALL (GS_UNBUILT, GS_UNBUILTD): "waiting",
never counted equal. Writes report.json.

--random: times20 on 100,000 inputs (0, +-1, the extremes, then random),
upstream's (mathref batch on a base's machine) against the native
(tptest.s tp_bulk), and against 20 v mod 2^32.

--plants: each planted bug built from a scratch copy of the part's sources
in a temporary directory (deleted), run on its named check, which must
fail.
"""

import argparse
import json
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))

import secfind as SF  # noqa: E402  (wave 1's machinery)
import lines as LN  # noqa: E402  (wave 2's: the bases, the tables)
import mobjstate as MS  # noqa: E402  (the shared stray rule)
import evworld as EW  # noqa: E402  (wave 3's: the stray rule, ref_call)
import checkpos as CP  # noqa: E402  (wave 3's: gw: places and outputs)
from bridge.port import PortReader  # noqa: E402
from native import gamecap as GC, gameroutine as GR, gcanon, \
    glayout as GL, grun as G, llayout as LL  # noqa: E402
from ref816 import calls as CL  # noqa: E402

ROOT = TOOLS.parent
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
PART = 'teleport'
OUT = GL.GAME / PART
CASES = OUT / 'cases'
SYN = OUT / 'synthetic'
REPORT = OUT / 'report.json'
ARGS = SRC / 'game' / PART / 'args.json'
IMAGE = 'ptest'
GC.CASES = CASES                # the part's own case directory (the
#                                 imports pointed it at theirs)

TELEPORT = 'p_telept65.s:EV_Teleport'
MOVE = 'p_map65.s:P_TeleportMove'
STOMP = 'p_map65.s:stompThing'
CROSS = LN.CROSS                # p_switch65.s:P_CrossSpecialLine
ENTRIES = (TELEPORT, MOVE, STOMP)
KEYS = (CROSS, TELEPORT, MOVE)  # the routines the synthetic calls enter
BASE_KEY = LN.BASE_KEY          # the tour's P_UpdateSpecials
TOUR_STEP = LN.TOUR_STEP
LEAN = 40                       # calls a routine (the owner's lean checks)
FILLS = (0xA5,)                 # one poisoned machine (lean)
PROFILES = SF.PROFILES
BATCH = 40
SYN_FORMAT = 'teleport-synthetic 1'
TELE_SPECIAL = 97               # crosstab's lnTele (p_switch65.s:598)


class PartError(Exception):
    pass


def say(text: str) -> None:
    print(text, flush=True)


def uconst() -> Dict[str, int]:
    return SF.uconst()


def missing() -> Optional[str]:
    """Why the checkpoint cannot run (None: it can)."""
    return SF.missing()


def build(game: Optional[Path] = None, source: Path = SRC,
          test: bool = True) -> Path:
    """The part's test image (make -f game.mk part P=teleport TP_TEST=1);
    its directory."""
    variables = ['P=%s' % PART]
    if test:
        variables.append('TP_TEST=1')
    if game is not None:
        variables.append('GAME=%s' % game)
    G.make('part', variables, source)
    return (game or GL.GAME) / PART


def args() -> Dict[str, Dict[str, Any]]:
    """The part's declarations: its entries, and the caller it is reached
    through in the synthetic calls (P_CrossSpecialLine: part lines'
    inputs, this part's outputs)."""
    d = json.loads(ARGS.read_text())
    if d.get('format') != GR.ARGS_FORMAT:
        raise PartError('%s is not %s' % (ARGS, GR.ARGS_FORMAT))
    out = dict(d['entries'])
    out.update(d['callers'])
    return out


# ---------------------------------------------------------------------------
# The bases: the tour's in-play states (lines' and evworld's choice)
# ---------------------------------------------------------------------------

def case_path(run: str, key: str, hit: int) -> Path:
    return GC.case_dir(run, key) / ('h%08d.case.z' % hit)


def survey_calls(key: str) -> List[Tuple[str, int, int]]:
    """Every call of an entry over the survey's runs: (run, hit, tic)."""
    out = []
    for run in GC.RUNS:
        sv = GC.survey_of(run)
        r = sv['routines'].get(key) if sv else None
        if r:
            out += [(run, h, r['tic'][h - 1]) for h in
                    range(1, r['calls'] + 1)]
    return out


def capture() -> int:
    hits = {hit: tic for _, hit, tic in LN.base_calls()}
    todo = sorted(h for h in hits if not case_path('tour', BASE_KEY,
                                                   h).exists())
    if not todo:
        return capture_full()
    top = max(hits)
    tics = [hits.get(h, -1) for h in range(1, top + 1)]
    start = time.time()
    got = GC.capture('tour', BASE_KEY, todo, tics, batch=BATCH, say=say)
    say('tour %s: %d cases (%.0f s)' % (BASE_KEY, len(got),
                                        time.time() - start))
    return len(got) + capture_full()


def map_bases() -> Dict[int, Path]:
    """A captured P_UpdateSpecials of the tour on each map (the first)."""
    out: Dict[int, Path] = {}
    a = CL.Linkmap().address(GR.TIC_GAMEMAP)
    for run, hit, _ in LN.base_calls():
        p = case_path(run, BASE_KEY, hit)
        if not p.exists():
            continue
        gm = GC.load_case(p).entry.u16(a)
        if gm not in out:
            out[gm] = p
    return out


# The synthetic calls need the whole machine of their map, not only the
# pages P_UpdateSpecials' capture keeps (the reader's and the call's: a
# case's other pages are the run's first hit's, E1M1's): P_SpawnMobj's
# pool bits, the zone, the sight hints are read by the teleport's calls.
# So the bases of the maps with teleport lines are captured again with
# every page of RAM (FULL_KEY's directory, about 1 MB a case).
FULL_KEY = 'p_spec65.s:P_UpdateSpecials#full'


def full_path(hit: int) -> Path:
    return CASES / 'tour' / 'P_UpdateSpecials_full' / ('h%08d.case.z' % hit)


def distil_full(raw: Path, tic: int, base) -> bytes:
    """A raw capture as a case with every page of RAM (gamecap.distil's
    format)."""
    call = json.loads((raw / 'call.json').read_text())
    entry = GC.bmem.Memory.from_image(raw / 'entry.img')
    writes = GC.image_records(raw / 'exit.img')
    pages = [b << 8 | k for b in GC.RAM_BANKS for k in range(0x100)]
    payload = bytearray()
    for pg in pages:
        at = pg << 8
        mine = entry.read(at, GC.PAGE)
        theirs = base.read(at, GC.PAGE)
        payload += bytes(x ^ y for x, y in zip(mine, theirs))
    wbytes = bytearray()
    for _, d in writes:
        wbytes += d
    header = {'format': GC.CASE_FORMAT, 'run': 'tour', 'routine': BASE_KEY,
              'hit': call['hit'], 'tic': tic, 'note': call.get('note'),
              'cycles': call['cycles'], 'call': call['call'],
              'image_header': entry.header.hex(),
              'pages': GC._compress_pages(pages),
              'writes': GC._ranges(writes), 'reads': [], 'full': 1}
    head = json.dumps(header, separators=(',', ':')).encode() + b'\n'
    return zlib.compress(head + bytes(payload) + bytes(wbytes), 6)


def capture_full() -> int:
    """The whole-RAM bases of the maps with teleport lines."""
    hits = {}
    tics = {hit: tic for _, hit, tic in LN.base_calls()}
    for m, p in map_bases().items():
        if Base.tele_count(p):
            hit = int(p.name[1:9])
            hits[hit] = tics[hit]
    todo = sorted(h for h in hits if not full_path(h).exists())
    if not todo:
        return 0
    GC.check_disk()
    entry = CL.Linkmap().address(BASE_KEY)
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-teleport-cap-',
                                 dir=str(BUILD)))
    try:
        raw = work / 'raw'
        raw.mkdir()
        opts = ['--capture', str(raw), '--capture-entry', '%06X' % entry]
        for h in todo:
            opts += ['--capture-hit', str(h)]
        r = GC.machine('tour', work, opts)
        if r['problems']:
            raise PartError('tour: %s' % '; '.join(r['problems']))
        base = GC.load_base('tour')
        for h in todo:
            out = full_path(h)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(distil_full(raw / ('hit-%08d' % h), hits[h],
                                       base))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return len(todo)


def full_bases() -> Dict[int, Path]:
    """The whole-RAM base of each map with teleport lines."""
    out = {}
    for m, p in map_bases().items():
        f = full_path(int(p.name[1:9]))
        if f.exists():
            out[m] = f
    return out


# ---------------------------------------------------------------------------
# The synthetic calls (ref816 --call on an in-play state of each map)
# ---------------------------------------------------------------------------

class Base(EW.Base):
    """An in-play state (evworld's Base): its teleport lines, their
    destinations, its live monsters."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.o = self.ref.s_in['objects']
        self.s = self.case.regs_in['s']

    @staticmethod
    def tele_count(path: Path) -> int:
        b = SF.MapBase(path)
        return sum(1 for i in range(b.nlines)
                   if b.line_special(i) == TELE_SPECIAL)

    def tele_lines(self) -> List[int]:
        return [i for i in range(self.nlines)
                if self.line_special(i) == TELE_SPECIAL]

    def mobj_at(self, ident: int) -> int:
        return self.ref.r_in.placement.address('mobj', ident)

    def destination(self, tag: int) -> Optional[Dict[str, Any]]:
        """The teleport destination of a tag (a TELEPORTMAN in a sector
        with the tag; the first in the order of the thinkers is the
        routine's business: any one serves the plan's positions)."""
        for ident in sorted(self.o['mobj']):
            mo = self.o['mobj'][ident]
            if mo.get('free') or mo['type'] != self.c['UC_MT_TELEPORTMAN']:
                continue
            ss = self.o['subsector'][mo['subsector'].id]
            if self.o['sector'][ss['sector'].id]['tag'] == tag:
                return mo
        return None

    def monsters(self) -> List[Tuple[int, int]]:
        """The live monsters (MF_COUNTKILL, not the player, not a
        missile): (slot, type), in slot order."""
        c = self.c
        kill = c['UC_MF_COUNTKILL_LO'] | c['UC_MF_COUNTKILL_HI'] << 16
        missiles = [c[m] for m in LN.MISSILES]
        pmo = LN.player_mo(self.ref.s_in)
        out = []
        for ident in sorted(self.o['mobj']):
            mo = self.o['mobj'][ident]
            if mo.get('free') or mo['health'] <= 0 or \
                    mo['type'] in missiles or not mo['flags'] & kill or \
                    (pmo is not None and pmo.id == ident):
                continue
            out.append((ident, mo['type']))
        return out

    def other_tag(self, not_tag: int) -> Optional[int]:
        """A sector tag other than 0 and not_tag with no destination in
        its sectors (EV_Teleport's search finds nothing)."""
        for i in sorted(self.o['sector']):
            t = self.o['sector'][i]['tag']
            if t and t != not_tag and self.destination(t) is None:
                return t
        return None


def dp_pokes(base: Base, *values: int) -> List[Tuple[int, bytes]]:
    """_Dp[4k..4k+3] = each value (a pointer or a fixed_t)."""
    return [(base.dp + 4 * k, (v & 0xFFFFFFFF).to_bytes(4, 'little'))
            for k, v in enumerate(values)]


def s32(v: int) -> int:
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def plan_map(base: Base, budget: Dict[str, int], phase: int
             ) -> List[List[Dict[str, Any]]]:
    """The map's sequences of one phase (the module's docstring): 0 the
    first line's sequences (monsters, the telefrag, the blocked monster,
    the back side; EV_Teleport alone; P_TeleportMove with boss set and the
    player onto a dropper), 1 the player on the other lines, 2 a monster
    on the other lines. budget counts the calls left of each routine (LEAN
    each), so that every map gets its first phases."""
    c = base.c
    lines = base.tele_lines()
    if not lines:
        return []
    mons = base.monsters()
    if len(mons) < 3:
        raise PartError('E1M%d: fewer than 3 monsters' % base.gamemap)
    player = base.player_mo
    seqs: List[List[Dict[str, Any]]] = []

    def take(key: str) -> bool:
        if budget[key] <= 0:
            return False
        budget[key] -= 1
        return True

    def cross(line: int, thing: int, side: int, note: str,
              extra: Sequence[Tuple[int, bytes]] = ()) -> Dict[str, Any]:
        return {'key': CROSS, 'pokes': dp_pokes(base, base.line(line),
                                                thing) + list(extra),
                'regs': {'a': side}, 'note': note}

    def line_note(line: int) -> str:
        return 'E1M%d line %d (tag %d)' % (base.gamemap, line,
                                           base.line_tag(line))
    if phase == 1:
        for line in lines[1:]:
            if take(CROSS):
                seqs.append([cross(line, player, 0, line_note(line) +
                                   ', the player')])
        return seqs
    if phase == 2:
        for k, line in enumerate(lines[1:]):
            i, t = mons[3 + k % (len(mons) - 3)] if len(mons) > 3 \
                else mons[0]
            if take(CROSS):
                seqs.append([cross(line, base.mobj_at(i), 0, line_note(line) +
                                   ', monster %d (type %d)' % (i, t))])
        return seqs
    first = lines[0]
    tag = base.line_tag(first)
    dest = base.destination(tag)
    if dest is None:
        raise PartError('E1M%d: no destination of tag %d' % (base.gamemap,
                                                              tag))
    (a, ta), (b, tb), (cc, tc) = mons[0], mons[1], mons[2]
    pa, pb, pc_ = base.mobj_at(a), base.mobj_at(b), base.mobj_at(cc)
    flags_a = pa + c['UO_MO_FLAGS']
    fa = base.m.u32(flags_a)
    pre = line_note(first)
    seq = []
    for step in (
            cross(first, pa, 0, pre + ', monster %d (type %d) moved' % (a, ta)),
            cross(first, pb, 0, pre + ', monster %d (type %d) past monster %d '
                  'made not shootable' % (b, tb, a),
                  [(flags_a, (fa & ~c['UC_MF_SHOOTABLE_LO']).to_bytes(
                      4, 'little'))]),
            cross(first, player, 0, pre + ', the player onto monster %d '
                  '(telefrag)' % b),
            cross(first, pc_, 0, pre + ', monster %d (type %d) onto the '
                  'player (blocked)' % (cc, tc)),
            cross(first, player, 1, pre + ', the player from the back side')):
        if take(CROSS):
            seq.append(step)
    if seq:
        seqs.append(seq)
    # EV_Teleport alone: a missile (MF_MISSILE poked on a monster), a line
    # whose tag has no destination, the player
    if take(TELEPORT):
        seqs.append([{'key': TELEPORT, 'pokes': dp_pokes(
            base, base.line(first), pa) + [
                (flags_a + 2, ((fa >> 16) | c['UC_MF_MISSILE_HI']).to_bytes(
                    2, 'little'))],
            'regs': {'a': 0}, 'note': pre + ', monster %d as a missile' % a}])
    other = base.other_tag(tag)
    if other is not None and take(TELEPORT):
        seqs.append([{'key': TELEPORT, 'pokes': dp_pokes(
            base, base.line(first), player) + [
                (base.line(first) + c['UO_LINE_TAG'], other.to_bytes(
                    2, 'little'))],
            'regs': {'a': 0}, 'note': pre + ' with tag %d (no destination), '
            'the player' % other}])
    if take(TELEPORT):
        seqs.append([{'key': TELEPORT, 'pokes': dp_pokes(
            base, base.line(first), player), 'regs': {'a': 0},
            'note': pre + ', the player'}])
    # P_TeleportMove with boss set: a monster, then a dropper, beside the
    # destination, then the player onto both (request R4: the drop)
    droppers = [(i, t) for i, t in mons if t in (c['UC_MT_POSSESSED'],
                                                 c['UC_MT_SHOTGUY'])]
    others = [(i, t) for i, t in mons if t not in (c['UC_MT_POSSESSED'],
                                                   c['UC_MT_SHOTGUY'])]
    if not (droppers and others):
        return seqs
    (z, tz), (q, tq) = droppers[0], others[0]
    pz, pq = base.mobj_at(z), base.mobj_at(q)
    u = 1 << 16

    def move(at: int, who: str, dx: int, dy: int) -> Dict[str, Any]:
        x, y = dest['x'] + dx * u, dest['y'] + dy * u
        return {'key': MOVE, 'pokes': dp_pokes(base, at, y) + [
            ((base.s + 4) & 0xFFFF, (1).to_bytes(2, 'little'))],
            'regs': {'a': x & 0xFFFF, 'x': (x >> 16) & 0xFFFF},
            'note': '%s, P_TeleportMove(%s, %+d, %+d from the destination, '
                    'boss)' % (pre, who, dx, dy)}
    for dx, dy in ((30, 0), (0, -30)):
        seq = []
        if take(MOVE):
            seq.append(move(pq, 'monster %d (type %d)' % (q, tq), dx, dy))
        if take(MOVE):
            seq.append(move(pz, 'monster %d (type %d, a dropper)' % (z, tz),
                            -dx, -dy))
        if take(CROSS):
            seq.append(cross(first, player, 0, pre + ', the player onto '
                             'monsters %d and %d (%+d, %+d)' % (q, z, dx, dy)))
        if seq:
            seqs.append(seq)
    return seqs


def plan_all(bases: Dict[int, Path]) -> List[Tuple[int, str, List[List[
        Dict[str, Any]]]]]:
    """Every map's sequences, phase by phase over the maps (LEAN calls a
    routine)."""
    budget = {k: LEAN for k in KEYS}
    got: Dict[int, List[List[Dict[str, Any]]]] = {}
    made = {m: Base(p) for m, p in bases.items()}
    for phase in (0, 1, 2):
        for m in sorted(bases):
            got.setdefault(m, []).extend(plan_map(made[m], budget, phase))
    return [(m, str(bases[m]), got[m]) for m in sorted(got) if got[m]]


def ref_call(address: int, pre: Sequence[Tuple[int, bytes]],
             pokes: Sequence[Tuple[int, bytes]], regs: Dict[str, int],
             base: 'GC.Case', work: Path):
    return EW.ref_call(address, pre, pokes, regs, base, work)


def make_synthetic(base_path: Path, seqs: List[List[Dict[str, Any]]]
                   ) -> List[Dict[str, Any]]:
    """The planned sequences run on ref816: each call on the state the
    calls before it in its sequence left."""
    base = Base(base_path)
    t = base.table
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-teleport-syn-',
                                 dir=str(BUILD)))
    out: List[Dict[str, Any]] = []
    try:
        for n, seq in enumerate(seqs):
            pre: List[Tuple[int, bytes]] = []
            for k, rec in enumerate(seq):
                address = t.address(rec['key'])
                call, writes = ref_call(address, pre, rec['pokes'],
                                        rec['regs'], base.case, work)
                out.append(dict(rec, seq=n, step=k, address=address,
                                call=call,
                                pre=[[a, d.hex()] for a, d in pre],
                                pokes=[[a, d.hex()] for a, d in rec['pokes']],
                                writes=[[a, d.hex()] for a, d in writes],
                                base=str(base_path.relative_to(OUT))))
                pre = list(pre) + list(rec['pokes']) + list(writes)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    return out


def _syn_job(item: Tuple[str, List[List[Dict[str, Any]]]]):
    path, seqs = item
    return make_synthetic(Path(path), seqs)


def write_synthetic(jobs: int = 2) -> Dict[str, int]:
    SYN.mkdir(parents=True, exist_ok=True)
    absent = sorted(set(range(1, 10)) - set(map_bases()))
    if absent:
        raise PartError('no in-play state of E1M%s (--capture)' % absent)
    bases = full_bases()
    if not bases:
        raise PartError('no whole-RAM base (--capture)')
    plans = plan_all(bases)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        got = list(pool.map(_syn_job, [(p, s) for _, p, s in plans]))
    counts = {}
    for old in SYN.glob('e1m*.json.z'):
        old.unlink()
    for (m, _, _), recs in zip(plans, got):
        (SYN / ('e1m%d.json.z' % m)).write_bytes(zlib.compress(json.dumps(
            {'format': SYN_FORMAT, 'map': m, 'records': recs},
            separators=(',', ':')).encode(), 6))
        counts['E1M%d' % m] = len(recs)
    return counts


def synthetic_names() -> List[str]:
    return sorted(p.name[:-len('.json.z')] for p in SYN.glob('e1m*.json.z'))


def load_synthetic(name: str) -> List[Dict[str, Any]]:
    p = SYN / (name + '.json.z')
    if not p.exists():
        raise PartError('no synthetic cases %s (--synthetic)' % p)
    d = json.loads(zlib.decompress(p.read_bytes()))
    if d.get('format') != SYN_FORMAT:
        raise PartError('%s is not %s' % (p, SYN_FORMAT))
    return d['records']


_BASE_CASES: Dict[str, GC.Case] = {}


def synthetic_case(rec: Dict[str, Any]) -> GC.Case:
    base = rec['base']
    if base not in _BASE_CASES:
        _BASE_CASES.clear()
        _BASE_CASES[base] = GC.load_case(OUT / base)
    b = _BASE_CASES[base]
    entry = b.entry.copy()
    entry.header = b.entry.header
    for a, d in rec['pre'] + rec['pokes']:
        entry.write(a, bytes.fromhex(d))
    after = entry.copy()
    for a, d in rec['writes']:
        after.write(a, bytes.fromhex(d))
    header = dict(b.header, routine=rec['key'], note=rec['note'],
                  call=rec['call'], hit=0,
                  writes=[[a, len(d) // 2] for a, d in rec['writes']])
    return GC.Case(header, entry, after, None)


# ---------------------------------------------------------------------------
# The paths (the branches a call takes), from the reference's states
# ---------------------------------------------------------------------------

def _ptr(ref: 'SF.Ref', text: str, when: str = 'in') -> int:
    return int.from_bytes(ref.source(text, when), 'little') & 0xFFFFFF


def new_mobjs(ref: 'SF.Ref') -> List[Tuple[str, int, Dict[str, Any]]]:
    """The mobjs the call made: (kind, identity, its record)."""
    out = []
    for kind in ('mobj', 'zmobj'):
        o0 = ref.s_in['objects'].get(kind, {})
        o1 = ref.s_out['objects'].get(kind, {})
        for k in sorted(o1):
            if not o1[k].get('free') and (k not in o0 or o0[k].get('free')):
                out.append((kind, k, o1[k]))
    return out


def killed(ref: 'SF.Ref') -> List[int]:
    o0 = ref.s_in['objects']['mobj']
    o1 = ref.s_out['objects']['mobj']
    return [k for k in sorted(o1) if k in o0 and not o0[k].get('free') and
            not o1[k].get('free') and o0[k]['health'] > 0 >= o1[k]['health']]


def path_of(rec: Dict[str, Any], ref: 'SF.Ref') -> str:
    """The branch the reference took (for the coverage report)."""
    c = uconst()
    made = new_mobjs(ref)
    fogs = sum(1 for _, _, m in made if m['type'] == c['UC_MT_TFOG'])
    drops = len(made) - fogs
    dead = killed(ref)
    key = rec['key']
    if key == MOVE:
        return 'move boss=1: %s%s' % (
            'moved' if rec['call']['end']['a'] & 0xFF else 'blocked',
            ', %d killed' % len(dead) if dead else '')
    if fogs:
        what = 'teleported'
    elif 'back side' in rec['note']:
        what = 'back side'
    elif 'missile' in rec['note']:
        what = 'missile'
    elif 'no destination' in rec['note']:
        what = 'no destination'
    else:
        what = 'blocked'
    th = ref.ref(_ptr(ref, 'dp:_Dp+4:4'), SF.kinds_of('mobj'))
    who = 'player' if LN.is_player(ref.s_in, th) else 'monster'
    out = '%s %s' % (who, what)
    if dead:
        out += ', telefrag x%d' % len(dead)
    if drops:
        out += ', a drop'
    if 'not shootable' in rec['note']:
        out += ', past a thing not shootable'
    return out


# ---------------------------------------------------------------------------
# The sound events: the teleport's own (R6's events, compared): two
# sfx_telept, at the fog of the old place, then at the destination's
# ---------------------------------------------------------------------------

def expected_sounds(prep: 'SF.Prep') -> List[Tuple[int, int, int, int]]:
    ref = prep.ref
    c = uconst()
    tic = ref.s_in['globals']['g_game65.s:_g_gametic'] & 0xFFFF
    fogs = [(kind, k, m) for kind, k, m in new_mobjs(ref)
            if m['type'] == c['UC_MT_TFOG']]
    if not fogs:
        return []
    if len(fogs) != 2:
        raise PartError('%d fogs made' % len(fogs))
    th = ref.ref(_ptr(ref, 'dp:_Dp+4:4'), SF.kinds_of('mobj'))
    old = ref.s_in['objects'][th.kind][th.id]
    fogs.sort(key=lambda f: (f[2]['x'], f[2]['y']) != (old['x'], old['y']))
    out = []
    for kind, k, _ in fogs:
        r = ref.ref(ref.r_out.placement.address(kind, k), SF.kinds_of('mobj'),
                    'out')
        out.append((tic, 0, c['UC_SFX_TELEPT'],
                    SF.native_value(prep.mf, 'mobj', r)))
    return out


# ---------------------------------------------------------------------------
# One run (checkpos's run_one with this part's sound events)
# ---------------------------------------------------------------------------

WAITING = CP.WAITING


def run_one(prep: 'CP.Prep', nat: 'SF.Native', fill: int, profile: str
            ) -> Dict[str, Any]:
    """One run of a case: the canonical state after the call against the
    reference's (routine mode), the declared outputs, the teleport's sound
    events, mobjstate's native checks, the stray writes; the cycles from
    the routine's entry to its return, the lowest S; a stop at an unbuilt
    routine is "waiting"."""
    spec = prep.spec
    res: Dict[str, Any] = {'entry': prep.key, 'fill': '%02x' % fill,
                           'profile': profile, 'ok': False}
    if prep.ref.problems:
        res['error'] = 'bridge: ' + '; '.join(prep.ref.problems[:3])
        return res
    img = prep.image(nat, fill)
    pre, canon = prep.pre_state(img, fill)
    entry = nat.b.labels[spec['native']]
    img.poke_word('dg_entry', entry)
    img.poke_label('dg_grp', bytes([nat.group(spec['native'])]))
    events = ['pc %X@1 snapshot start' % entry,
              'pc %X@1 snapshot ret' % nat.ret]
    work = Path(tempfile.mkdtemp(prefix='tmp-m10-teleport-', dir=str(BUILD)))
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], None,
                  regs=tuple(prep.regs), events=events,
                  banks=list(prep.banks) + [LL.GTEST],
                  profile=profile, write_log=SF.LOG_RANGES,
                  cycles=SF.RUN_CYCLES)
        ended = r.ended()
        res['ended'] = ended
        res['lowest_s'] = r.state.get('lowest_s')
        if ended != 'halt':
            p = work / 'crash.img'
            if p.exists():
                stop = G.stop_codes(G.load_snapshot(p))
                res['stop'] = stop
                if stop[0] in WAITING:
                    res['waiting'] = True
            return res
        c0, c1 = SF.snapshot_cycles(work, 'start'), \
            SF.snapshot_cycles(work, 'ret')
        res['cycles'] = c1 - c0 if c0 is not None and c1 is not None \
            else None
        if c0 is None:
            raise PartError('no snapshot at the routine\'s entry')
        w = CP.check_writes(work / 'writes.log', canon, c0, prep.header)
        res['stray'] = w.strays
        res['stray_first'] = w.stray
        m = G.load_snapshot(work / 'done.img')
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if w.canonical:
        from native import setupcheck as SC
        nat_state = PortReader(prep.mf).read(SC.port_memory(m))
    else:
        nat_state = pre
    diff = gcanon.compare(prep.ref.s_out, nat_state, 'routine')
    diff += CP.outputs(prep, nat, m)
    diff += MS.native_checks(m)
    c = uconst()
    got = SF.sounds(m)
    mine = [e for e in got if e[2] == c['UC_SFX_TELEPT']]
    want = expected_sounds(prep)
    res['sounds'] = len(got)
    res['other_sounds'] = len(got) - len(mine)
    if mine != want:
        diff.append('sound events %s, expected %s' % (mine[:4], want[:4]))
    if w.strays:
        diff.append('%d stray writes: %s' % (w.strays, w.stray))
    res['diff'] = diff[:12]
    res['ok'] = not diff
    return res


# ---------------------------------------------------------------------------
# The checkpoint (--check)
# ---------------------------------------------------------------------------

def records(names: Optional[Sequence[str]] = None, select=None
            ) -> List[Dict[str, Any]]:
    out = []
    for name in (names or synthetic_names()):
        out += [r for r in load_synthetic(name)
                if select is None or select(r)]
    return out


def _check_job(job) -> List[Dict[str, Any]]:
    items, obj, fills, profiles = job
    nat = SF.Native(Path(obj))
    CP.Prep.nat = nat
    spec_all = args()
    out: List[Dict[str, Any]] = []
    for rec in items:
        key = rec['key']
        name = '%s #%d.%d: %s' % (Path(rec['base']).name, rec['seq'],
                                  rec['step'], rec['note'])
        try:
            case = synthetic_case(rec)
            prep = CP.Prep(case, key, spec_all[key])
            path = path_of(rec, prep.ref)
        except Exception as error:      # reported per case, never hidden
            out.append({'case': name, 'entry': key, 'ok': False,
                        'error': '%s: %s' % (type(error).__name__, error)})
            continue
        for fill in fills:
            for profile in profiles:
                try:
                    r = run_one(prep, nat, fill, profile)
                except Exception as error:
                    r = {'entry': key, 'fill': '%02x' % fill,
                         'profile': profile, 'ok': False,
                         'error': '%s: %s' % (type(error).__name__, error)}
                r.update(case=name, path=path)
                out.append(r)
    return out


def check_jobs(recs: Sequence[Dict[str, Any]], obj: Path = OUT,
               fills: Sequence[int] = FILLS,
               profiles: Sequence[str] = PROFILES, chunk: int = 6
               ) -> List[Tuple]:
    return [(list(recs[i:i + chunk]), str(obj), tuple(fills),
             tuple(profiles)) for i in range(0, len(recs), chunk)]


def run_jobs(jobs: List[Tuple], workers: int = 2) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if workers <= 1:
        for j in jobs:
            out += _check_job(j)
        return out
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for got in pool.map(_check_job, jobs):
            out += got
    return out


def _stats(values: Sequence[int]) -> Dict[str, Any]:
    v = sorted(values)
    return {'median': v[len(v) // 2], 'worst': v[-1],
            'unit': 'fabric clocks, from the routine\'s entry to its '
                    'return, every slot empty at the call'} if v else {}


def summarize(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per routine the synthetic calls entered there, and for the part's
    entries reached through them (stompThing under P_TeleportMove,
    EV_Teleport under P_CrossSpecialLine) the calls that reach them."""
    out: Dict[str, Any] = {}
    for key in KEYS:
        rs = [r for r in results if r.get('entry') == key]
        if not rs:
            continue
        waiting = [r for r in rs if r.get('waiting')]
        run = [r for r in rs if not r.get('waiting')]
        bad = [r for r in run if not r.get('ok')]
        paths: Dict[str, int] = {}
        for r in run:
            if r.get('profile') == PROFILES[0]:
                paths[r.get('path', '?')] = paths.get(r.get('path', '?'),
                                                      0) + 1
        ls = [r['lowest_s']['s'] for r in run
              if isinstance(r.get('lowest_s'), dict)]
        out[key] = {
            'calls_in_survey': len(survey_calls(key)),
            'cases_eligible': len({r['case'] for r in rs}),
            'cases_run': len({r['case'] for r in run}),
            'cases_waiting': sorted({r['case'] for r in waiting}),
            'runs': len(run), 'failures': len(bad),
            'stray_writes': sum(r.get('stray') or 0 for r in run),
            'cycles': {p: _stats([r['cycles'] for r in run
                                  if r.get('profile') == p and
                                  r.get('cycles')]) for p in PROFILES},
            'lowest_s': min(ls) if ls else None,
            'paths': paths,
            'first_failures': [{k: r.get(k) for k in (
                'case', 'fill', 'profile', 'diff', 'error', 'ended', 'stop')}
                for r in bad[:4]]}
    return out


# ---------------------------------------------------------------------------
# times20's random check (GAME.md 2.4 "Arithmetic")
# ---------------------------------------------------------------------------

BULK_IN, BULK_OUT = 93, 94
BULK_ROOM = 0xC000 - 0x0200
EDGES = (0, 1, -1, 2, -2, 0x7FFFFFFF, -0x80000000, -0x7FFFFFFF, 0xFFFF,
         0x10000, -0x10000, 0x8000, -0x8000, 0x7FFF, 0xFFFFFFF, 0x6666666,
         0x6666667, -0x6666667, 0xCCCCCCC, 0x3FFFFFFF, -0x40000000)


def times20_inputs(n: int, seed: int = 1) -> List[int]:
    rnd = random.Random(seed)
    out = list(EDGES)
    while len(out) < n:
        k = len(out) % 3
        if k == 0:
            out.append(rnd.randint(-0x80000000, 0x7FFFFFFF))
        elif k == 1:
            out.append(rnd.randint(-0x10000, 0x10000))     # finesine's
        else:
            out.append(rnd.choice((1, -1)) * (1 << rnd.randint(0, 30)) +
                       rnd.randint(-4, 4))
    return [s32(v) for v in out[:n]]


def native_bulk(b, values: Sequence[int]) -> List[int]:
    per = BULK_ROOM // 4
    out: List[int] = []
    for start in range(0, len(values), per):
        chunk = values[start:start + per]
        img = G.Image(b, 0xA5, store=False)
        img.aux(BULK_IN, 0x0200, b''.join(struct.pack('<i', v)
                                          for v in chunk))
        work = Path(tempfile.mkdtemp(prefix='tmp-m10-teleport-bulk-',
                                     dir=str(BUILD)))
        try:
            k = len(chunk)
            r = G.run(img, work, GL.MODES['ROUTINE'], 'tp_bulk',
                      regs=(0, k & 0xFF, k >> 8, 0x34), banks=[BULK_OUT])
            if r.ended() != 'halt':
                raise PartError('tp_bulk ended %s' % r.ended())
            m = G.load_snapshot(work / 'done.img')
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        data = bytes(m.aux[BULK_OUT][0x0200:0x0200 + 4 * len(chunk)])
        out += [struct.unpack('<i', data[i:i + 4])[0]
                for i in range(0, len(data), 4)]
    return out


def random_check(n: int = 100_000, seed: int = 1,
                 obj: Path = OUT) -> Dict[str, Any]:
    """times20 on n inputs: upstream's (mathref batch on a base's machine:
    A the low word, X the high word in; TP_T out) against the native
    (tp_bulk) and against 20 v mod 2^32."""
    import sight as SG
    bases = full_bases()
    if not bases:
        raise PartError('no base (python3 tools/native/gparts/teleport.py '
                        '--capture)')
    case = GC.load_case(bases[min(bases)])
    t = CL.Linkmap()
    vals = times20_inputs(n, seed)
    recs = b''.join(struct.pack('<HH', v & 0xFFFF, (v >> 16) & 0xFFFF)
                    for v in vals)
    pc = t.address('p_telept65.s:times20')
    tp_t = t.address('p_telept65.s:TP_T')
    ups = SG.mathref(case, 'times20', pc, ['a', 'x'],
                     ['%06X 4' % tp_t], recs, 4)
    upv = [struct.unpack('<i', u)[0] for u in ups]
    b = G.load_build(obj, IMAGE)
    nat = native_bulk(b, vals)
    bad = [(v, u, m_) for v, u, m_ in zip(vals, upv, nat) if u != m_]
    model = sum(1 for v, u in zip(vals, upv) if u == s32(20 * v))
    return {'inputs': len(vals), 'compared': min(len(upv), len(nat)),
            'different': len(bad) + abs(len(upv) - len(nat)),
            'first': bad[:5], 'edges': len(EDGES),
            'upstream_is_20v': model, 'seed': seed}


# ---------------------------------------------------------------------------
# The planted bugs (lean: the three most likely mistakes)
# ---------------------------------------------------------------------------

PLANTS: Dict[str, Tuple[str, List[Tuple[str, str]]]] = {
    # the second fog at the old z, not the thing's z after the move
    'fog-z': ('player', [(
        '''        MOGET TP_THING          ; P_SpawnMobj(x, y, thing->z, MT_TFOG)
        ldy #TH_Z + 3
        ldx #3
:       lda (GC_MP),y''',
        '''        MOGET TP_THING          ; (planted: the old z)
        ldy #TH_Z + 3
        ldx #3
:       lda TP_OZ,x''')]),
    # the reaction time given to a monster too
    'react-monster': ('monster', [(
        '''        IS_PLAYER TP_THING      ; the player waits 18 tics
        bne @dirty''',
        '''        IS_PLAYER TP_THING      ; (planted: every thing waits)
        nop
        nop''')]),
    # a stomp of a thing that is not shootable
    'stomp-not-shootable': ('stomp', [(
        '''        and #<UC_MF_SHOOTABLE_LO
        jeq @on''',
        '''        and #<UC_MF_SHOOTABLE_LO      ; (planted: no test)''')]),
}


def plant_select(check: str):
    if check == 'player':
        return lambda r: r['key'] == CROSS and r['note'].endswith(
            ', the player')
    if check == 'monster':
        return lambda r: r['key'] == CROSS and r['step'] == 0 and \
            'moved' in r['note']
    if check == 'stomp':
        return lambda r: 'not shootable' in r['note']
    raise PartError('no check %s' % check)


def plant_build(name: str, tmp: Path) -> Path:
    _, edits = PLANTS[name]
    src = tmp / 'src'
    files = list(G.PLANT_COPY) + ['game/%s/%s' % (PART, f) for f in
                                  ('part.mk', 'teleport.s')]
    for f in files:
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(SRC / f), str(src / f))
    target = src / 'game' / PART / 'teleport.s'
    text = target.read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise PartError('the planted bug %s no longer applies: %r' % (
                name, old[:60]))
        text = text.replace(old, new)
    target.write_text(text)
    return build(game=tmp / 'game', source=src)


def plants(names: Optional[Sequence[str]] = None, workers: int = 2
           ) -> Dict[str, Any]:
    out = {}
    for name in (names or list(PLANTS)):
        check = PLANTS[name][0]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-teleport-plant-',
                                    dir=str(BUILD)))
        try:
            obj = plant_build(name, tmp)
            recs = records(select=plant_select(check))
            res = run_jobs(check_jobs(recs, obj=obj, fills=(FILLS[0],),
                                      profiles=(PROFILES[0],)), workers)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        bad = [r for r in res if not r.get('ok')]
        r = {'check': check, 'runs': len(res), 'failed': len(bad),
             'caught': bool(bad),
             'first': (bad[0].get('diff') or [bad[0].get('error') or
                                              bad[0].get('ended')])[:2]
             if bad else None}
        out[name] = r
        say('%-20s %-8s %s' % (name, check, 'caught: %d of %d runs fail, %s'
                               % (r['failed'], r['runs'], r['first'])
                               if r['caught'] else 'NOT CAUGHT (%d runs)' %
                               r['runs']))
    return out


# ---------------------------------------------------------------------------
# Sizes (docs/GAME.md 4.7: the part's budget)
# ---------------------------------------------------------------------------

BUDGET = next(p['native'] for p in GL.PARTS if p['name'] == PART)
UPSTREAM_BYTES = next(p['up'] for p in GL.PARTS if p['name'] == PART)
LABELS = ('EV_Teleport', 'lnTele', 'fogSound', 'times20', 'destination',
          'P_TeleportMove', 'stompThing', 'farFrom')


def sizes(obj: Path = OUT) -> Dict[str, Any]:
    """The part's bytes (teleport.o) against its budget; each routine's
    bytes and group."""
    b = G.load_build(obj, IMAGE)
    text = (obj / (IMAGE + '.map')).read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    chunks: List[Tuple[str, int, int]] = []
    module = None
    for line in mods.splitlines():
        if line and not line.startswith(' ') and line.endswith('.o:'):
            module = Path(line[:-1]).stem
            continue
        f = line.split()
        if module == PART and f and f[0] in b.segments:
            off = next(int(x[5:], 16) for x in f if x.startswith('Offs='))
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            lo = b.segments[f[0]][0] + off
            chunks.append((f[0], lo, lo + size))
    nat = SF.Native(obj)
    routines = {}
    for seg, lo, hi in chunks:
        g = int(seg[4:]) if seg.startswith('GGRP') else 0
        inside = sorted((b.labels[n], n) for n in LABELS
                        if lo <= b.labels[n] < hi and nat.group(n) == g)
        for k, (a, n) in enumerate(inside):
            end = inside[k + 1][0] if k + 1 < len(inside) else hi
            routines[n] = {'bytes': end - a, 'group': nat.group(n),
                           'segment': seg}
    total = sum(hi - lo for _, lo, hi in chunks)
    return {'bytes': total, 'budget': BUDGET, 'upstream': UPSTREAM_BYTES,
            'over_10_percent': total > BUDGET * 1.1, 'routines': routines}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def du_kb(path: Path) -> int:
    r = subprocess.run(['du', '-sk', str(path)], stdout=subprocess.PIPE,
                       universal_newlines=True)
    return int(r.stdout.split()[0]) if r.returncode == 0 else -1


def write_report(results: Optional[Sequence[Dict[str, Any]]] = None,
                 **parts) -> Dict[str, Any]:
    rep: Dict[str, Any] = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text())
    rep.update(format='game-part-report 1', part=PART,
               wave=next(p['wave'] for p in GL.PARTS if p['name'] == PART),
               lean='at most %d calls a routine, fill $A5 only (the owner\'s '
                    'lean checks of 2026-10-02)' % LEAN,
               fills=['%02x' % f for f in FILLS], profiles=list(PROFILES),
               exclusions=[n for n, _, _ in gcanon.ROUTINE_EXCLUSIONS],
               reached='EV_Teleport through P_CrossSpecialLine (lnTele) and '
                       'alone; stompThing through P_TeleportMove\'s '
                       'P_BlockThingsIterator (ITTAB); no survey run calls '
                       'any of them')
    if results is not None:
        rep['entries'] = summarize(results)
        rep['runs'] = len(results)
        rep['failures'] = sum(1 for r in results if not r.get('ok') and
                              not r.get('waiting'))
        rep['waiting'] = sum(1 for r in results if r.get('waiting'))
        rep['stray_writes'] = sum(r.get('stray') or 0 for r in results)
        ls = [r['lowest_s']['s'] for r in results
              if isinstance(r.get('lowest_s'), dict)]
        rep['lowest_s'] = min(ls) if ls else None
    rep.update(parts)
    rep['build_kb'] = du_kb(OUT)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=1, default=str) + '\n')
    return rep


def print_report(rep: Dict[str, Any]) -> None:
    for key, e in rep.get('entries', {}).items():
        cyc = '; '.join('%s %s/%s' % (p, c.get('median'), c.get('worst'))
                        for p, c in e['cycles'].items())
        say('%-34s %3d cases %4d runs %d failed %d waiting %d stray, S %s; '
            '%s' % (key, e['cases_run'], e['runs'], e['failures'],
                    len(e['cases_waiting']), e['stray_writes'],
                    e['lowest_s'], cyc))
        for p, n in sorted(e['paths'].items()):
            say('    %3d  %s' % (n, p))
    if 'sizes' in rep:
        sz = rep['sizes']
        say('bytes %d of %d (upstream %d)' % (sz['bytes'], sz['budget'],
                                             sz['upstream']))
    if 'random' in rep:
        say('times20: %s' % rep['random'])
    for name, r in rep.get('plants', {}).items():
        say('planted %-20s %s' % (name, 'caught' if r['caught'] else
                                  'NOT CAUGHT'))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--random', action='store_true')
    parser.add_argument('--count', type=int, default=100_000)
    parser.add_argument('--plants', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--keys', default=None)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--json', type=Path)
    a = parser.parse_args(argv)
    why = missing()
    if why:
        print('cannot run: %s' % why, file=sys.stderr)
        return 2
    if a.capture:
        say('%d cases made' % capture())
        return 0
    if a.synthetic:
        start = time.time()
        counts = write_synthetic(a.jobs)
        say('synthetic calls: %s (%.0f s)' % (counts, time.time() - start))
        return 0
    if a.check:
        start = time.time()
        build()
        recs = records()
        if a.keys:
            recs = [r for r in recs if r['key'] in a.keys.split(',')]
        res = run_jobs(check_jobs(recs), a.jobs)
        rep = write_report(res, sizes=sizes(), check_seconds=round(
            time.time() - start))
        if a.json:
            a.json.write_text(json.dumps(res, indent=1) + '\n')
        print_report(rep)
        return 1 if rep['failures'] else 0
    if a.random:
        build()
        r = random_check(a.count)
        write_report(random=r)
        say('times20: %s' % r)
        return 1 if r['different'] else 0
    if a.plants:
        build()
        r = plants(a.keys.split(',') if a.keys else None, a.jobs)
        write_report(plants=r)
        return 0 if all(x['caught'] for x in r.values()) else 1
    if a.report:
        print_report(json.loads(REPORT.read_text()))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
