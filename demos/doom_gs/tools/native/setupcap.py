#!/usr/bin/env python3
"""The setup captures of milestone 9 (docs/LEVELS.md 5.1): upstream's
state at each P_SetupLevel entry (E), at the end of the setup (R: the
RTL of P_MapEnd that P_SetupLevel's last instruction jumps to), and, for a
new map, at the end of W_LevelDone (W: its last instruction, the jump to
bmSignOff).

Usage:  python3 tools/native/setupcap.py [--runs tour-sk0,...] [--jobs 2]
        python3 tools/native/setupcap.py --check [--runs ...]

The runs (RUNS below):

    tour-sk0 .. tour-sk4   coverage/tour.script with the new-game menu's
                           skill item changed (the script generated into
                           the run's temporary directory; nightmare's
                           "are you sure" answered with y; each script
                           waits for _g_gameskill to be its skill): nine
                           setups each, E1M1 by a new game, the others
                           after an exit
    demo1, demo2, demo3    the title loop with DEMO1 and DEMO2 placed under
                           DEMO3 (tools/ref816/lumps.py) and DEMO3 as it
                           is, stopped after the demo's first tic
    reborn-e1m1            a new game, then _g_player.playerstate poked to
                           PST_REBORN in E1M1: G_Ticker reloads the map
                           (upstream's RL_ON path): two setups, one W
    reborn-e1m6            the tour to E1M6, then the same: the first load
                           of E1M6 and its reload are kept (the way there,
                           E1M1 to E1M5, is the tour's own)
    reborn-kit             (the verification of stage C) as reborn-e1m1,
                           but the player is given a kit first (KIT below:
                           health, armour, powers, cards, the backpack,
                           weapons, ammunition and its maxima, bob,
                           didsecret), so G_PlayerReborn's resets differ
                           from the player at E: two setups, one W
    newgame                coverage/newgame.script: one setup
    wrap                   (stage C, docs/LEVELS.md 3.4) newgame.script with
                           validcount poked to WRAP_VALIDCOUNT at the first
                           P_SetupLevel entry (--poke-file): upstream's
                           setup across validcount's wrap, the truth of the
                           lockstep build and the comparand of the release
                           build's wrap fix
    secorder               (the verification of stage C) newgame.script
                           with map things of E1M1 moved, at the first
                           P_SpawnMapThing (--poke-file into upstream's
                           THINGS lump), to block corners where the order
                           of P_CreateSecNodeList's block walk shows
                           (tools/native/secorder.py; needs newgame-01);
                           its setup.json lists the moves ("things"),
                           which the native run's store takes too

(The design's count of 51 is the 45 tour setups, the 3 demos, the two
reloads and newgame's; the reborn runs' first loads of their maps are
kept too, the comparands of the reloads: 53 setups, 51 W points. Stage
C added wrap and, at its verification, reborn-kit: 56 setups, 53 W
points.)

Each run goes twice on ref816: the first marks every P_SetupLevel entry,
every RTL of P_MapEnd, the end of every W_LevelDone and every
R_MakeTextureColumns entry; the second dumps, at each setup, E (banks
$00, $02, $0D and the pool map $0A:8000-$805F), R and W (all RAM), and
must end with the first's RAM and marks. Output, per setup, in
build/native/levels/setups/RUN-NN/ (NN from 1 in the run's order):

    e.dump.z     the E dump (rendercap.py's stored form: the dump's JSON
                 line, then its bytes, zlib)
    r.ram.z      all RAM (banks $00-$7F, $E0, $E1) at R, zlib
    w.ram.z      the same at W (a new map only)
    setup.json   the run, the setup, gamemap, gameskill, the kind (new or
                 reload), the hits and cycles of E, R and W, the textures
                 R_MakeTextureColumns made at the load and in play after
                 it (until the next setup)

--check reads every R and W dump with the bridge (tools/bridge/upstream.py
Reader): 0 problems each, and each W dump's canonical state equal to its
R dump's (W_LevelDone changes no game unit). Its report goes to
build/native/levels/setups/check.json.

All runs are under nice, bounded in host time, in stream size and in file
size; free disk space is checked first (20 GB at least).
"""

import argparse
import hashlib
import json
import shutil
import struct
import sys
import tempfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ref816 import dumps, lumps, make_image, marks, run_script, script, \
    title  # noqa: E402
from native import rendercap  # noqa: E402

BUILD = make_image.BUILD
SETUPS = BUILD / 'native' / 'levels' / 'setups'
FORMAT = 'level-setup-capture 1'
RUN_TIMEOUT = 3600.0
LIMIT_SECONDS = 900             # machine seconds of a run
RAM_BYTES = 130 * 0x10000
E_RANGES = '00+02+0D+0A8000:96'
E_BYTES = 3 * 0x10000 + 96
SKILLS = 5
PST_REBORN = 2                  # offsets.inc CONST_PST_REBORN
OFS_PL_PLAYERSTATE = 4          # offsets.inc
# reborn-kit's player before PST_REBORN: (offsets.inc OFS_PL_*, size,
# value), every one a field G_PlayerReborn sets (to 0 or its own value)
# and P_SetupLevel does not write otherwise, so a reset the native
# G_PlayerReborn misses leaves E's value and differs from ref816's R
KIT = (
    (23, 'long', 0x00034000),   # bob
    (19, 'long', 0x00008000),   # deltaviewheight
    (35, 'word', 57),           # health (G_PlayerReborn: 100)
    (37, 'word', 42),           # armorpoints
    (39, 'word', 1),            # armortype
    (41 + 2 * 3, 'word', 700),  # powers[pw_ironfeet]
    (41 + 2 * 4, 'word', 1),    # powers[pw_allmap]
    (53 + 2 * 0, 'word', 1),    # cards[0]
    (53 + 2 * 2, 'word', 1),    # cards[2]
    (59, 'word', 1),            # backpack
    (65 + 2 * 2, 'word', 1),    # weaponowned[shotgun]
    (65 + 2 * 3, 'word', 1),    # weaponowned[chaingun]
    (83 + 2 * 0, 'word', 77),   # ammo[clip] (G_PlayerReborn: 50)
    (83 + 2 * 1, 'word', 13),   # ammo[shells]
    (83 + 2 * 2, 'word', 40),   # ammo[cells]
    (91 + 2 * 0, 'word', 400),  # maxammo[clip] (the backpack's double)
    (91 + 2 * 1, 'word', 100),  # maxammo[shells]
    (91 + 2 * 2, 'word', 600),  # maxammo[cells]
    (91 + 2 * 3, 'word', 100),  # maxammo[rockets]
    (153, 'word', 1))           # didsecret


class RunSpec(NamedTuple):
    key: str
    kind: str                   # tour, demo, reborn, newgame
    arg: int                    # the skill, the demo, the reborn map


RUNS = tuple([RunSpec('tour-sk%d' % k, 'tour', k) for k in range(SKILLS)] +
             [RunSpec('demo%d' % k, 'demo', k) for k in (1, 2, 3)] +
             [RunSpec('reborn-e1m1', 'reborn', 1),
              RunSpec('reborn-e1m6', 'reborn', 6),
              RunSpec('reborn-kit', 'rebornkit', 1),
              RunSpec('newgame', 'newgame', 0),
              RunSpec('wrap', 'wrap', 0),
              RunSpec('secorder', 'secorder', 0)])
# the wrap run's validcount at its first setup: E1M1's spawn raises it 92
# times (each thing with a sector), so it wraps to 0 for the 32nd thing,
# the first whose box crosses lines (3 sector nodes in newgame-01): its
# walk then skips every line never stamped (upstream's wrap)
WRAP_VALIDCOUNT = 0xFFFF - 31
DEMO_MAPS = {1: 5, 2: 3, 3: 7}


# ---------------------------------------------------------------------------
# The scripts
# ---------------------------------------------------------------------------

def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError('%d lines %r in the script' % (text.count(old), old))
    return text.replace(old, new)


def skill_edit(text: str, skill: int) -> str:
    """The new-game part of a coverage script (tour.script's lines) at
    `skill`: the skill menu's cursor moved from the default item (2), the
    item checked, nightmare's message answered y, and the game's skill
    checked once the game has started."""
    if not 0 <= skill < SKILLS:
        raise ValueError('skill %d' % skill)
    anchor = 'wait m_menu65.s:itemOn == 2 within 1\nat +1s press return\n'
    moves = ''
    key = 'up' if skill < 2 else 'down'
    for _ in range(abs(skill - 2)):
        moves += 'at +1s press %s\n' % key
    new = 'wait m_menu65.s:itemOn == 2 within 1\n' + moves + \
        'wait m_menu65.s:itemOn == %d within 2s\n' % skill + \
        'at +1s press return\n'
    if skill == 4:
        # M_ChooseSkill's "are you sure" (m_menu65.s chooseSkill): only y
        new += 'wait m_menu65.s:messageToPrint == 1 within 5s\n' \
               'at +1s press y\n'
    text = _replace_once(text, anchor, new)
    return _replace_once(
        text, 'wait _g_usergame == 1 within 10s\n',
        'wait _g_usergame == 1 within 10s\n'
        'wait _g_gameskill == %d within 10s\n' % skill)


def tour_text(skill: int) -> str:
    text = (run_script.COVERAGE / 'tour.script').read_text()
    return '# setupcap.py: tour.script at skill %d\n' % skill + \
        skill_edit(text, skill)


def demo_text(demo: int) -> str:
    return '\n'.join((
        '# setupcap.py: the title loop to demo%d\'s first tic' % demo,
        'wait d_main65.s:pagedrawn == 1 within 90s   # the title page',
        'wait _g_demoplayback == 1 within 60s',
        'wait _g_gamestate == 0 within 60s       # GS_LEVEL',
        'wait _g_gamemap == %d within 1' % DEMO_MAPS[demo],
        'wait long _g_gametic grows 1 within 60s',
        'at +1s stop', ''))


def reborn_text(gamemap: int, kit: bool = False) -> str:
    """The tour (at the default skill) to `gamemap`, then the player
    poked to PST_REBORN: G_Ticker's G_DoReborn loads the map again. With
    `kit`, the player's fields of KIT are poked first, in the same frame
    (G_Ticker's reborn and the load come before the tic's P_PlayerThink,
    so they are the player at P_SetupLevel's entry)."""
    text = (run_script.COVERAGE / 'tour.script').read_text()
    anchor = 'wait _g_gamemap == %d within 1' % gamemap
    head, found, _ = text.partition(anchor)
    if not found:
        raise ValueError('tour.script has no %r' % anchor)
    pokes = ''.join('poke %s _g_player+%d %d\n' % (size, at, value)
                    for at, size, value in KIT) if kit else ''
    return ('# setupcap.py: the tour to E1M%d, then a reload of it%s\n'
            % (gamemap, ' with the player given a kit' if kit else '') +
            head + anchor + '\n'
            'at +2s note reborn\n' + pokes +
            'poke word _g_player+%d %d\n' % (OFS_PL_PLAYERSTATE, PST_REBORN) +
            'wait _g_player+%d == 0 within 30s      # PST_LIVE again\n'
            % OFS_PL_PLAYERSTATE +
            'wait long _g_gametic grows 1 within 60s\n'
            'at +1s stop\n')


def newgame_text() -> str:
    return (run_script.COVERAGE / 'newgame.script').read_text()


def script_text(spec: RunSpec) -> str:
    if spec.kind == 'tour':
        return tour_text(spec.arg)
    if spec.kind == 'demo':
        return demo_text(spec.arg)
    if spec.kind in ('reborn', 'rebornkit'):
        return reborn_text(spec.arg, kit=spec.kind == 'rebornkit')
    return newgame_text()           # newgame, wrap, secorder


def poke_options(spec: RunSpec, symbols: script.Symbols, work: Path
                 ) -> List[str]:
    """The wrap run's poke: validcount at the first P_SetupLevel entry.
    The secorder run's: the moved things' x and y into upstream's THINGS
    lump at the first P_SpawnMapThing (the lump is loaded then)."""
    if spec.kind == 'secorder':
        work.mkdir(parents=True, exist_ok=True)
        point = dumps.resolve('pc=P_SpawnMapThing,hits=1', symbols)
        sec = secorder_moves()
        path = work / 'secorder.pokes'
        path.write_text(''.join(
            '%s %06X %s\n' % (point, sec['things_at'] + 8 * m['thing'],
                              struct.pack('<hh', m['x'], m['y']).hex())
            for m in sec['moves']))
        return ['--poke-file', str(path)]
    if spec.kind != 'wrap':
        return []
    work.mkdir(parents=True, exist_ok=True)
    point = dumps.resolve('pc=P_SetupLevel,hits=1', symbols)
    path = work / 'wrap.pokes'
    path.write_text('%s %06X %s\n' % (
        point, symbols.address('p_map65.s:validcount'),
        WRAP_VALIDCOUNT.to_bytes(2, 'little').hex()))
    return ['--poke-file', str(path)]


_SECORDER: List[Dict] = []


def secorder_moves() -> Dict:
    """secorder.py's moves (from newgame-01's R dump), once a process."""
    if not _SECORDER:
        from native import secorder
        if not (SETUPS / secorder.BASE_SETUP / 'r.ram.z').exists():
            raise RuntimeError('the run secorder needs %s: python3 '
                               'tools/native/setupcap.py --runs newgame'
                               % secorder.BASE_SETUP)
        _SECORDER.append(secorder.choose(SETUPS))
    return _SECORDER[0]


def lump_options(spec: RunSpec, symbols: script.Symbols, work: Path
                 ) -> List[str]:
    if spec.kind == 'demo' and spec.arg in (1, 2):
        return lumps.options('DEMO%d' % spec.arg, symbols, out=work)
    return []


# ---------------------------------------------------------------------------
# The addresses
# ---------------------------------------------------------------------------

def _find(mem, start: int, want: bytes, span: int, what: str) -> int:
    code = mem.get(start, span)
    at = code.find(want)
    if at < 0:
        raise RuntimeError('no %s within %d bytes of $%06X' % (what, span,
                                                               start))
    return start + at


def routines(symbols: script.Symbols) -> Dict[str, int]:
    """P_SetupLevel's entry; the RTL of P_MapEnd (found by its byte after
    the label: P_MapEnd is two stz and an rtl, p_map65.s:3293-3298); the
    jump to bmSignOff that ends W_LevelDone (w_level65.s:519, a JML found
    by its bytes); R_MakeTextureColumns' entry."""
    from ref816 import refimage
    mem = refimage.load(refimage.read(title.MEMORY))
    mapend = symbols.address('P_MapEnd')
    rtl = _find(mem, mapend, b'\x6b', 16, 'RTL after P_MapEnd')
    if mem.get(mapend, rtl - mapend) != bytes([0x9C]) + mem.get(
            mapend + 1, 2) + bytes([0x9C]) + mem.get(mapend + 4, 2) or \
            rtl != mapend + 6:
        raise RuntimeError('P_MapEnd is not two stz and an rtl')
    done = symbols.address('W_LevelDone')
    signoff = symbols.address('bmSignOff')
    jml = _find(mem, done, bytes([0x5C]) + signoff.to_bytes(3, 'little'),
                64, 'JML bmSignOff in W_LevelDone')
    return {'setup': symbols.address('P_SetupLevel'), 'mapend': rtl,
            'done': jml, 'tex': symbols.address('R_MakeTextureColumns')}


class Setup(NamedTuple):
    index: int                  # from 1, in the run's order
    e_hit: int
    e_cycles: int
    r_hit: int                  # the RTL of P_MapEnd
    r_cycles: int
    w_hit: int                  # 0: no W (a reload)
    w_cycles: int
    made_load: int              # R_MakeTextureColumns calls, E to W (or R)
    made_play: int              #   and after it until the next setup


def setups_of(log: Sequence[marks.Entry], r: Dict[str, int]) -> List[Setup]:
    names = {'%06X' % v: k for k, v in r.items()}
    counts = {k: 0 for k in r}
    events = []
    for e in log:
        if e.kind != 'mark' or e.what not in names:
            continue
        key = names[e.what]
        counts[key] += 1
        events.append((key, counts[key], e.cycles))
    out = []
    starts = [i for i, ev in enumerate(events) if ev[0] == 'setup']
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(events)
        part = events[i:end]
        r_ev = next((ev for ev in part if ev[0] == 'mapend'), None)
        if r_ev is None:
            raise RuntimeError('setup %d: no P_MapEnd after it' % (n + 1))
        w_ev = next((ev for ev in part if ev[0] == 'done'), None)
        k_r = part.index(r_ev)
        if w_ev is not None:
            k_w = part.index(w_ev)
            if k_w < k_r:
                raise RuntimeError('setup %d: W_LevelDone before P_MapEnd'
                                   % (n + 1))
            # no tic between the setup and W_LevelDone: one P_MapEnd
            if any(ev[0] == 'mapend' for ev in part[k_r + 1:k_w]):
                raise RuntimeError('setup %d: a tic before W_LevelDone'
                                   % (n + 1))
            cut = k_w
        else:
            cut = k_r
        made_load = sum(1 for ev in part[:cut] if ev[0] == 'tex')
        made_play = sum(1 for ev in part[cut:] if ev[0] == 'tex')
        out.append(Setup(n + 1, events[i][1], events[i][2], r_ev[1],
                         r_ev[2], w_ev[1] if w_ev else 0,
                         w_ev[2] if w_ev else 0, made_load, made_play))
    return out


def mark_options(r: Dict[str, int]) -> List[str]:
    out = []
    for key in ('setup', 'mapend', 'done', 'tex'):
        out += ['--mark', '%06X' % r[key]]
    return out


def peek_globals(symbols: script.Symbols, ram: bytes) -> Dict[str, int]:
    def word(name: str, size: int = 2) -> int:
        a = symbols.address(name)
        bank = a >> 16
        index = bank if bank < 0x80 else 0x80 + bank - 0xE0
        at = index * 0x10000 + (a & 0xFFFF)
        return int.from_bytes(ram[at:at + size], 'little')
    return {'gamemap': word('_g_gamemap'), 'gameskill': word('_g_gameskill'),
            'gametic': word('_g_gametic', 4),
            'demoplayback': word('_g_demoplayback')}


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def run_one(spec: RunSpec, symbols: script.Symbols, out: Path,
            log_file=None) -> Dict:
    def say(text):
        line = '[%s] %s' % (spec.key, text)
        print(line, flush=True)
        if log_file:
            log_file.write(line + '\n')
            log_file.flush()

    rendercap.check_disk(out)
    tmp = Path(tempfile.mkdtemp(prefix='tmp-setup-%s-' % spec.key,
                                dir=str(BUILD)))
    try:
        text = script_text(spec)
        prog = script.compile_script(text, symbols, spec.key + '.script')
        r = routines(symbols)
        lump_opts = lump_options(spec, symbols, tmp / 'lumps') + \
            poke_options(spec, symbols, tmp / 'pokes')

        # -- the first run: the marks
        w1 = tmp / 'first'
        w1.mkdir()
        (w1 / 'input.txt').write_text(prog)
        start = time.time()
        cmd = rendercap.machine_command(
            w1 / 'input.txt', w1, symbols, LIMIT_SECONDS,
            mark_options(r) + lump_opts)
        run = rendercap.Streamed(cmd, RUN_TIMEOUT)
        run.finish()
        state1 = json.loads((w1 / 'state.json').read_text())
        log1 = marks.read(w1 / 'marks.txt')
        problems = run_script.problems(state1, log1, symbols, prog)
        if problems:
            raise RuntimeError('first run: ' + '; '.join(problems))
        found = setups_of(log1, r)
        if not found:
            raise RuntimeError('no setup in the run')
        say('first run: %d setups (%d with W), %.0f s'
            % (len(found), sum(1 for s in found if s.w_hit),
               time.time() - start))

        # -- the second run: the dumps
        points = [('E', dumps.resolve('pc=P_SetupLevel,ranges=%s'
                                      % E_RANGES, symbols))]
        for s in found:
            points.append(('R', 'pc=%06X,hits=%d' % (r['mapend'], s.r_hit)))
        points.append(('W', 'pc=%06X' % r['done']))
        if len(points) > rendercap.MAX_POINTS:
            raise RuntimeError('%d points' % len(points))
        nw = sum(1 for s in found if s.w_hit)
        limit = len(found) * (E_BYTES + 4096) + (len(found) + nw) * \
            (RAM_BYTES + 4096) + (1 << 20)
        w2 = tmp / 'second'
        w2.mkdir()
        (w2 / 'input.txt').write_text(prog)
        extra = mark_options(r) + lump_opts
        for _, text_point in points:
            extra += ['--dump-at', text_point]
        extra += ['--dump-stream', '-', '--dump-limit', str(limit),
                  '--dump-max', str(2 * len(found) + nw)]
        start = time.time()
        rendercap.check_disk(out)
        run = rendercap.Streamed(rendercap.machine_command(
            w2 / 'input.txt', w2, symbols, LIMIT_SECONDS, extra),
            RUN_TIMEOUT)
        kinds = [k for k, _ in points]
        staging = tmp / 'setups'
        staging.mkdir()
        by_e = {s.e_hit: s for s in found}
        by_r = {s.r_hit: s for s in found}
        by_w = {s.w_hit: s for s in found if s.w_hit}
        got: Dict[int, Dict[str, Dict]] = {s.index: {} for s in found}
        for d in run.dumps():
            kind = kinds[d.header['point']]
            hit = d.header['hit']
            table = {'E': by_e, 'R': by_r, 'W': by_w}[kind]
            s = table.get(hit)
            if s is None:
                raise RuntimeError('a %s dump at hit %d of no setup'
                                   % (kind, hit))
            directory = staging / ('%s-%02d' % (spec.key, s.index))
            directory.mkdir(exist_ok=True)
            info = {'cycles': d.header['cycles'], 'hit': hit,
                    'cpu': d.header.get('cpu'),
                    'switches': d.header.get('switches')}
            if kind == 'E':
                rendercap.write_dump(directory / 'e.dump.z', d)
            else:
                if len(d.data) != RAM_BYTES:
                    raise RuntimeError('%s dump of %d bytes' % (kind,
                                                               len(d.data)))
                name = 'r.ram.z' if kind == 'R' else 'w.ram.z'
                (directory / name).write_bytes(zlib.compress(d.data, 6))
                info['sha256'] = hashlib.sha256(d.data).hexdigest()
                info.update(peek_globals(symbols, d.data))
            got[s.index][kind] = info
        run.finish()
        state2 = json.loads((w2 / 'state.json').read_text())
        if state2['ram_fnv1a64'] != state1['ram_fnv1a64'] or \
                (w2 / 'marks.txt').read_bytes() != \
                (w1 / 'marks.txt').read_bytes():
            raise RuntimeError('the dumping run differs from the first')
        problems = run_script.problems(state2, marks.read(w2 / 'marks.txt'),
                                       symbols, prog)
        if problems:
            raise RuntimeError('second run: ' + '; '.join(problems))
        results = []
        for s in found:
            if spec.kind in ('reborn', 'rebornkit') and \
                    got[s.index]['R']['gamemap'] != spec.arg:
                continue        # (the way there: the tour's own setups)
            want = {'E', 'R'} | ({'W'} if s.w_hit else set())
            if set(got[s.index]) != want:
                raise RuntimeError('setup %d: dumps %s, not %s' % (
                    s.index, sorted(got[s.index]), sorted(want)))
            name = '%s-%02d' % (spec.key, s.index)
            g = got[s.index]['R']
            meta = {'format': FORMAT, 'name': name, 'run': spec.key,
                    'kind': 'new' if s.w_hit else 'reload',
                    'gamemap': g['gamemap'], 'gameskill': g['gameskill'],
                    'demoplayback': g['demoplayback'],
                    'setup': s._asdict(), 'dumps': got[s.index]}
            if spec.kind == 'secorder':
                # the map things moved (setupcheck.py moves them in the
                # native run's store too): index, x, y
                meta['synthetic'] = True
                meta['things'] = [[m['thing'], m['x'], m['y']]
                                  for m in secorder_moves()['moves']]
            directory = staging / name
            (directory / 'setup.json').write_text(json.dumps(
                meta, indent=1) + '\n')
            target = out / name
            if target.exists():
                shutil.rmtree(str(target))
            shutil.move(str(directory), str(target))
            results.append({'name': name, 'gamemap': g['gamemap'],
                            'gameskill': g['gameskill'],
                            'kind': meta['kind'],
                            'made_load': s.made_load,
                            'made_play': s.made_play})
        say('second run: %d setups stored, %.0f s'
            % (len(results), time.time() - start))
        (out / ('%s.script' % spec.key)).write_text(text)
        return {'run': spec.key, 'setups': results}
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


# ---------------------------------------------------------------------------
# --check: the bridge on every R and W dump
# ---------------------------------------------------------------------------

def setup_dirs(runs: Optional[Sequence[str]] = None) -> List[Path]:
    if not SETUPS.exists():
        return []
    out = []
    for d in sorted(SETUPS.iterdir()):
        if not (d / 'setup.json').exists():
            continue
        if runs and json.loads((d / 'setup.json').read_text())['run'] \
                not in runs:
            continue
        out.append(d)
    return out


def check(dirs: Sequence[Path]) -> Dict:
    from bridge import canonical, upstream
    from native import levelconv
    report = {'setups': {}, 'problems': 0, 'w_differs': 0}
    for d in dirs:
        meta = json.loads((d / 'setup.json').read_text())
        row = {}
        states = {}
        for kind, name in (('R', 'r.ram.z'), ('W', 'w.ram.z')):
            path = d / name
            if not path.exists():
                continue
            reader = upstream.Reader(levelconv.load_memory(path))
            states[kind] = reader.read()
            row[kind + '_problems'] = list(reader.problems)
            report['problems'] += len(reader.problems)
        if 'W' in states:
            diff = canonical.diff(states['R'], states['W'])
            row['w_equals_r'] = not diff
            row['w_diff'] = [str(x) for x in diff[:10]]
            if diff:
                report['w_differs'] += 1
        row['gamemap'] = meta['gamemap']
        row['gameskill'] = meta['gameskill']
        row['kind'] = meta['kind']
        report['setups'][d.name] = row
        print('%s: E1M%d skill %d %s: R %d problems%s' % (
            d.name, meta['gamemap'], meta['gameskill'], meta['kind'],
            len(row['R_problems']),
            '' if 'W' not in states else ', W %d problems, W %s R' % (
                len(row['W_problems']),
                '==' if row['w_equals_r'] else '!=')), flush=True)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', default=','.join(s.key for s in RUNS))
    parser.add_argument('--out', type=Path, default=SETUPS)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    wanted = args.runs.split(',')
    specs = [s for s in RUNS if s.key in wanted]
    if len(specs) != len(wanted):
        parser.error('unknown run in %s' % args.runs)
    if args.check:
        report = check(setup_dirs(wanted))
        (args.out / 'check.json').write_text(json.dumps(report, indent=1) +
                                             '\n')
        print('%d setups: %d bridge problems, %d W dumps differ from R'
              % (len(report['setups']), report['problems'],
                 report['w_differs']))
        return 1 if report['problems'] or report['w_differs'] else 0
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py and '
                  'python3 tools/v816/imgmatch.py first' % path,
                  file=sys.stderr)
            return 1
    title.build_machine()
    title.ensure_image()
    symbols = dumps.symbols()
    args.out.mkdir(parents=True, exist_ok=True)
    rendercap.check_disk(args.out)
    with open(str(args.out / 'setupcap.log'), 'a') as log_file:
        with ThreadPoolExecutor(max(1, min(2, args.jobs))) as pool:
            results = list(pool.map(
                lambda s: run_one(s, symbols, args.out, log_file), specs))
    report_path = args.out / 'setupcap.json'
    report = json.loads(report_path.read_text()) if report_path.exists() \
        else {}
    for res in results:
        report[res['run']] = res
    report_path.write_text(json.dumps(report, indent=1) + '\n')
    for res in results:
        print('%s: %s' % (res['run'], ', '.join(
            '%s E1M%d sk%d %s' % (x['name'], x['gamemap'], x['gameskill'],
                                  x['kind']) for x in res['setups'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
