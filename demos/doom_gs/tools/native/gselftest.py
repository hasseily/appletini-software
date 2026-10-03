#!/usr/bin/env python3
"""The skeleton's checks of its runtime on hand-made data (milestone 10,
docs/GAME.md 3.9, S5): the skeleton's test image (make -f game.mk skel,
src/native/game/gtest.s) on a2vm through tools/native/grun.py.

Usage:  python3 tools/native/gselftest.py [--fill a5] [--json OUT]

    api       the object API: hits, misses, write-back, the LRU guarantee
              (mobjs, sectors, lines, specials)
    spawn     a spawn into a slot whose cached line is dirty from a removal
    fcall     FCALL in its own slot, slot 1 -> core -> slot 1, slot 1 ->
              slot 2 -> slot 1
    planes    the planes in and out
    free      the zone's and the specials' free lists
    unbuilt   an FCALL of an unbuilt routine, an unbuilt entry of each
              dispatch table
    load      the load protocol with a stub G_Ticker and a stub
              continuation for GA_LOADLEVEL, GA_NEWGAME, GA_PLAYDEMO and
              GA_WORLDDONE (each run once, the action loop re-entered), a
              re-key record applied after nl_setup, the setup's canonical
              state against ref816's

Each check returns a list of failures (empty: it passes). The planted
bugs of S7 rebuild the test image from a copy of the sources (`obj`).
"""

import argparse
import json
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import glayout as GL, grun as G, llayout as LL, \
    rlayout as R  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'


def skel_build(obj: Optional[Path] = None):
    return G.load_build(obj or (G.GAME / 'skel'), 'skel')


def work_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix='tmp-m10-skel-', dir=str(BUILD)))


def results(b, m) -> bytes:
    lab = b.labels
    n = m.main[lab['gt_ri']]
    return bytes(m.main[lab['gt_res']:lab['gt_res'] + n])


def routine(b, entry: str, fill: int, extra=(), regs=(0, 0, 0, 0x34),
            banks: Sequence[int] = (), pre=None) -> Tuple[Any, Any]:
    """One routine-mode run of the test image: (the run, its last
    snapshot)."""
    img = G.Image(b, fill, store=False)
    lab = b.labels
    img.poke_label('gt_ri', b'\0')
    for rec in extra:
        img.recs.append(rec)
    if pre is not None:
        pre(img)
    work = work_dir()
    try:
        r = G.run(img, work, GL.MODES['ROUTINE'], entry, regs=regs,
                  banks=banks)
        name = 'done' if r.ended() == 'halt' else 'crash'
        p = work / (name + '.img')
        m = G.load_snapshot(p) if p.exists() else None
        return r, m
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


# ---------------------------------------------------------------------------
# The hand-made data
# ---------------------------------------------------------------------------

def pattern(bank: int, i: int, k: int) -> int:
    return ((i * 7 + k) ^ bank) & 0xFF


def api_records() -> List[Tuple[int, int, int, bytes]]:
    out = []
    for bank in (R.RTH,) + LL.MOBJ_BANKS:
        data = bytes(pattern(bank, s, k) for s in range(64)
                     for k in range(LL.MO_SIZE))
        out.append((1, bank, R.RTHINGS.base, data))
    out.append((1, R.LVMAP, R.SECTORS.base,
                bytes(pattern(R.LVMAP, s, k) for s in range(24)
                      for k in range(R.SEC_SIZE))))
    out.append((1, LL.LVG1, LL.SECGS.base,
                bytes(pattern(LL.LVG1, s, k) for s in range(24)
                      for k in range(LL.SECG_SIZE))))
    out.append((1, LL.LVG0, LL.LINES.base,
                bytes(pattern(LL.LVG0, s, k) for s in range(128)
                      for k in range(LL.LINE_SIZE))))
    out.append((1, LL.LVS, LL.LVS_LNSECF, bytes((s ^ 0x11) & 0xFF
                                                for s in range(128))))
    out.append((1, LL.LVS, LL.LVS_LNSECB, bytes((s ^ 0x22) & 0xFF
                                                for s in range(128))))
    out.append((1, LL.ZONE0, LL.SPECS.base,
                bytes(pattern(LL.ZONE0, s, k) for s in range(24)
                      for k in range(LL.SPEC_SIZE))))
    return out


def check_api(b, fill: int) -> List[str]:
    r, m = routine(b, 'gt_t_api', fill, api_records(),
                   banks=(R.RTH,) + LL.MOBJ_BANKS)
    if r.ended() != 'halt' or m is None:
        return ['api: the run ended %s %s' % (r.ended(), G.stop_codes(m)
                                              if m else '')]
    got = results(b, m)
    want = bytes([1, 1, 1, 1, 0, 0, 1, 1, 1, 1,      # the LRU
                  0x42,                              # slot 20's type
                  pattern(LL.MOBJA, 30, LL.MA['HEALTH']),   # 30's: no
                  4, 20, 1,                          # hits, misses, wback
                  0xC3, 0xD4,                        # the sectors
                  5 ^ 0x11, 5 ^ 0x22, 0x34, 0x12,    # the line
                  0x87,                              # the special
                  4, 1])                             # its LRU
    if got != want:
        return ['api: results %s, expected %s' % (got.hex(), want.hex())]
    return []


def check_spawn(b, fill: int) -> List[str]:
    r, m = routine(b, 'gt_t_spawn', fill, api_records())
    if r.ended() != 'halt' or m is None:
        return ['spawn: the run ended %s' % r.ended()]
    got = results(b, m)
    want = bytes([0x55, LL.FN['MOBJ'], 5, 0xFF, 0xFF])
    if got != want:
        return ['spawn: results %s, expected %s (the spawned record must '
                'survive the eviction of the dirty line)' % (got.hex(),
                                                              want.hex())]
    return []


def test_group_base(b) -> int:
    """The groups before the test groups (the placement's: gplace.inc's
    GROUPS less TEST_GROUPS)."""
    text = (b.obj / 'gen' / 'gplace.inc').read_text()
    n = int(next(x for x in text.splitlines()
                 if x.startswith('GROUPS =')).split('=')[1])
    return n - len(GL.TEST_GROUPS)


def fcall_expected(base: int = 0) -> bytes:
    # each marker with the group slot 1 holds (TEST_GROUPS after the
    # placement's base groups: gt_fa, gt_fa2 the first, gt_fc the second,
    # gt_fd the third)
    a, d = base + 1, base + 3
    seq = [('A', a), ('2', a), ('a', a), ('K', a), ('D', d), ('B', a),
           ('k', a), ('b', a), ('C', a), ('D', d), ('k', a), ('c', a)]
    return b''.join(bytes([ord(c), g]) for c, g in seq) + b'E'


def check_fcall(b, fill: int) -> List[str]:
    r, m = routine(b, 'gt_t_fcall', fill)
    if r.ended() != 'halt' or m is None:
        return ['fcall: the run ended %s' % r.ended()]
    got = results(b, m)
    want = fcall_expected(test_group_base(b))
    if got != want:
        return ['fcall: markers %r, expected %r' % (got, want)]
    return []


def check_planes(b, fill: int) -> List[str]:
    recs = [(1, LL.MOBJP, LL.PL_TNL + 5, b'\x11'),
            (1, LL.MOBJP, LL.PL_TNH + 5, b'\x22'),
            (1, LL.MOBJP, LL.PL_KIND + 5, b'\x03'),
            (1, LL.MOBJP, LL.PL_TICS + 5, b'\x04')]
    r, m = routine(b, 'gt_t_planes', fill, recs, banks=(LL.MOBJP,))
    if r.ended() != 'halt' or m is None:
        return ['planes: the run ended %s' % r.ended()]
    out = []
    if results(b, m) != bytes([0x11, 0x22, 0x03, 0x04]):
        out.append('planes: pl_get %s' % results(b, m).hex())
    back = bytes(m.aux[LL.MOBJP][a + 6] for a in (
        LL.PL_TNL, LL.PL_TNH, LL.PL_KIND, LL.PL_TICS))
    if back != bytes([0x23, 0x01, 0x0A, 0x07]):
        out.append('planes: slot 6 in MOBJP after the run %s' % back.hex())
    return out


def check_free(b, fill: int) -> List[str]:
    G_ = LL.G
    recs = [(0, 0, G_['G_POOLN'], struct.pack('<H', 4)),
            (0, 0, G_['G_TPBITS'], bytes(LL.POOL_MAX // 8)),
            (0, 0, G_['G_ZMN'], b'\0\0'),
            (0, 0, G_['G_SPFREE'], b'\xff' * (2 * len(LL.SPEC_KINDS) + 2)),
            (0, 0, G_['G_MOHWM'], struct.pack('<H', 4)),
            (0, 0, G_['G_SPN'], bytes(2 * len(LL.SPEC_KINDS))),
            (0, 0, G_['GT_ZPREV'], b'\0')]
    r, m = routine(b, 'gt_t_free', fill, recs)
    if r.ended() != 'halt' or m is None:
        return ['free: the run ended %s %s' % (r.ended(), G.stop_codes(m)
                                               if m else '')]
    door = LL.SPEC_HANDLE + LL.SPEC_RANGE['door'][0]
    want = bytes([4, 0, 5, 0xFE, 0xFF, 1, LL.FN['FREE'], 5, 2, 6,
                  door & 0xFF, door >> 8, door & 0xFF, door & 0xFF, 0xFF,
                  1])
    got = results(b, m)
    if got != want:
        return ['free: results %s, expected %s' % (got.hex(), want.hex())]
    return []


def check_unbuilt(b, fill: int) -> List[str]:
    out = []
    names = GL.native_names()
    keys = [k for p in GL.PARTS for k in p['routines'] + p['helpers']]
    number = (keys + GL.CORE).index('p_map65.s:P_DelSecnode') + 1
    r, m = routine(b, 'gt_t_unb', fill)
    codes = G.stop_codes(m) if m else None
    if r.ended() != 'crash' or codes[:2] != (GL.GS['UNBUILT'], number):
        out.append('unbuilt: FCALL P_DelSecnode ended %s, stop %r (want '
                   'GS_UNBUILT %d)' % (r.ended(), codes, number))
    del names
    from native import gcallgraph as CG
    entries = GL.dispatch_entries(CG.load(write=False))
    for t_index, (table, keys) in enumerate(entries.items(), 1):
        k = next(i for i, key in enumerate(keys, 1)
                 if GL.owner_of(key) != 'core')

        def pre(img, t=t_index):
            img.poke_label('dg_t', bytes([t]))
        r, m = routine(b, 'gt_t_dcall', fill, regs=(0, k, 0, 0x34),
                       pre=pre)
        codes = G.stop_codes(m) if m else None
        if r.ended() != 'crash' or codes[:2] != (GL.GS['UNBUILTD'],
                                                 k | t_index << 8):
            out.append('unbuilt: %s entry %d ended %s, stop %r' % (
                table, k, r.ended(), codes))
    return out


# ---------------------------------------------------------------------------
# The load protocol
# ---------------------------------------------------------------------------

LOAD_CASES = (('GA_NEWGAME', 'newgame-01'), ('GA_PLAYDEMO', 'demo3-01'),
              ('GA_LOADLEVEL', 'reborn-e1m1-02'),
              ('GA_WORLDDONE', 'newgame-01'))


def rekey_record(gamemap: int) -> bytes:
    hints = [k * 3 & 0xFFFF for k in range(LL.POOL_MAX)]
    return (bytes([gamemap]) + struct.pack('<HH', 5, 7) + b'\0' +
            bytes(h & 0xFF for h in hints) + bytes(h >> 8 for h in hints))


def check_load(b, level, fill: int, cases=LOAD_CASES,
               compare: bool = True) -> List[str]:
    """Each case: the setup's pre-state (its E dump, as milestone 9's
    checks write it), the stub ticker starting a load of the action, the
    stub continuation; the run's end, the counters, the action's tail, the
    re-key record, and (when the action is the E dump's own) the setup's
    canonical state against the R dump's."""
    from bridge import upstream
    from bridge.upstream import Schema
    from native import levelconv as LC, setupcap, setupcheck as SC
    out = []
    sch = Schema()
    meta = SC.store_meta()
    acts = {n: sch.c.local('g_game65.s', n) for n, _ in cases}
    for action, setup in cases:
        d = setupcap.SETUPS / setup
        if not d.exists():
            out.append('load: no setup %s' % setup)
            continue
        info = json.loads((d / 'setup.json').read_text())
        gamemap = info['gamemap']
        rm = LC.load_memory(d / 'r.ram.z')
        ref = upstream.Reader(rm).read()
        pre = SC.prestate(SC.manifest_of(gamemap, meta), d, ref, rm, fill,
                          sch)
        img = G.Image(b, fill, level=level)
        lab = b.labels
        img.main(LL.GBLOCK, pre[:LL.PRE_RND])
        img.main(LL.PRND, pre[LL.PRE_RND:LL.PRE_RND + 2])
        img.main(LL.G_VALID, pre[LL.PRE_VALID:LL.PRE_VALID + 2])
        img.poke_label('gt_act', bytes([acts[action]]))
        img.poke_label('gt_cont', bytes(9))
        img.poke_label('gt_reent', b'\0')
        img.poke_label('gt_tphase', b'\0')
        img.poke_label('gt_ri', b'\0')
        img.poke_word('dg_ticker', lab['gt_tstub'])
        img.poke_word('dg_resume', lab['gt_rstub'])
        img.poke_word('dg_frame', 0)
        tic = struct.unpack_from('<I', pre, LL.G['G_GAMETIC'] - LL.GBLOCK)[0]
        img.poke_label('dg_stop', struct.pack('<I', tic + 1))
        img.poke_label('dg_rekey', b'\0')
        img.poke_word('dg_tcount', 1)
        img.gtest(GL.GTB['GT_TIMES'] + 4, struct.pack('<I', 0x123456))
        img.gtest(GL.GTB['GT_SCHEDULE'], bytes(3))
        img.gtest(GL.GTB['GT_REKEYS'], rekey_record(gamemap))
        img.recs += SC.thing_records([info], meta)
        work = work_dir()
        try:
            banks = (G.lrun.WINDOW_BANKS + G.lrun.GAME_BANKS)
            r = G.run(img, work, GL.MODES['LOCKSTEP'],
                      events=['pc %X snapshot loaded' % lab['drv_loaded'],
                              'pc %X snapshot end' % lab['drv_end']],
                      banks=banks)
            what = '%s (%s)' % (action, setup)
            if r.ended() != 'halt':
                p = work / 'crash.img'
                codes = G.stop_codes(G.lrun.SnapMachine.from_image(p)) \
                    if p.exists() else None
                out.append('load %s: the run ended %s, stop %r' % (
                    what, r.ended(), codes))
                continue
            m = G.load_snapshot(work / 'end.img')
            G_ = LL.G
            ga = acts[action]
            loads = G.card_byte(m, lab['dg_loads'])
            if loads != 1:
                out.append('load %s: %d loads' % (what, loads))
            cont = bytes(m.main[lab['gt_cont']:lab['gt_cont'] + 9])
            if cont != bytes(1 if i == ga else 0 for i in range(9)):
                out.append('load %s: the continuations ran %s' % (
                    what, cont.hex()))
            if m.main[lab['gt_reent']] != 1:
                out.append('load %s: the action loop entered %d times' % (
                    what, m.main[lab['gt_reent']]))
            if m.main[G_['G_GAMEACTION']] or m.main[G_['G_GAMEACTION'] + 1]:
                out.append('load %s: gameaction left' % what)
            if m.main[G_['G_LOADACT']] != ga:
                out.append('load %s: G_LOADACT %d' % (
                    what, m.main[G_['G_LOADACT']]))
            if action == 'GA_PLAYDEMO':
                demo = m.main[G_['G_DEMOPLAY']] | m.main[G_['G_DEMOPLAY'] +
                                                         1] << 8
                user = m.main[G_['G_USERGAME']] | m.main[G_['G_USERGAME'] +
                                                         1] << 8
                start = struct.unpack_from('<I', m.main, G_['G_STARTTIME'])[0]
                cheats = m.main[G_['G_PLAYER'] + _pl('cheats')]
                if (demo, user, start, cheats) != (1, 0, 0x123456, 0):
                    out.append('load %s: demoplayback %d, usergame %d, '
                               'starttime $%X, cheats %d' % (
                                   what, demo, user, start, cheats))
            prev = struct.unpack_from('<HH', m.main, G_['CS_PREV1'])
            if prev != (5, 7):
                out.append('load %s: CS_PREV %r after the re-key' % (what,
                                                                     prev))
            hint = m.aux[LL.MOBJP]
            rec = rekey_record(gamemap)[6:]
            if bytes(hint[LL.PL_HINTL:LL.PL_HINTL + LL.POOL_MAX]) != \
                    rec[:LL.POOL_MAX] or \
                    bytes(hint[LL.PL_HINTH:LL.PL_HINTH + LL.POOL_MAX]) != \
                    rec[LL.POOL_MAX:]:
                out.append('load %s: the hint planes after the re-key'
                           % what)
            if compare:
                lm = G.lrun.SnapMachine.from_image(work / 'loaded.img')
                nat = SC.native_state(lm, SC.manifest_of(gamemap, meta))
                skip = SC.skips(sch)
                if acts[action] != SC.e_memory(d).u16(
                        sch.symbols.address('g_game65.s:_g_gameaction')):
                    skip = skip + ['g_game65.s:_g_gameaction']
                diff = SC.compare(ref, nat, skip)
                if diff:
                    out.append('load %s: the setup differs from ref816\'s: '
                               '%s' % (what, '; '.join(diff[:4])))
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return out


def _pl(field: str) -> int:
    return dict((p[0], at) for p, _, at in LL.player_layout())[field]


CHECKS = ('api', 'spawn', 'fcall', 'planes', 'free', 'unbuilt', 'load')


# ---------------------------------------------------------------------------
# The planted bugs (S7): each (the check that must catch it, the edits of
# src/native files: (file, old, new), applied once to a scratch copy)
# ---------------------------------------------------------------------------

MOSAVE_PAST_CACHE = """gt_mosave:
        lda GC_MO               ; (planted: g_put past the cache: the
        sta GO_P                ;   record to its four banks, a cache
        lda GC_MO+1             ;   line holding the slot left as is)
        asl GO_P
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        sta GO_P+1
        lda GO_P
        sta GO_I
        lda GO_P+1
        pha
        asl GO_P
        rol GO_P+1
        clc
        lda GO_P
        adc GO_I
        sta GO_P
        pla
        adc GO_P+1
        sta GO_P+1
        clc
        lda GO_P
        adc #<RTHBASE
        sta GO_P
        lda GO_P+1
        adc #>RTHBASE
        sta GO_P+1
        ldx #0
:       lda mv_bank,x
        sta FA_BANK
        lda GO_P
        sta FA_DST
        lda GO_P+1
        sta FA_DST+1
        phx
        clc
        lda #<LW_MOB
        adc mv_ofs,x
        pha
        lda #>LW_MOB
        adc #0
        tax
        pla
        ldy #MO_SIZE
        jsr g_put
        plx
        inx
        cpx #4
        bne :-
        lda #$FF"""

PLANTS = {
    # FCALL's return leaves the callee's group in the slot (S5 fcall)
    'fcall-no-reload': ('fcall', [('gcall.s', """        beq @back
        jsr gr_load             ; (FC_PS, the callee's P, stays)
@back:""", """        beq @back
        nop                     ; (planted: the caller's group not
        nop                     ;   reloaded)
        nop
@back:""")]),
    # FCALL's return reloads the saved group only when the caller runs in
    # that slot (S5 fcall's nested slot 1 -> slot 2 -> slot 1)
    'fcall-same-slot': ('fcall', [('gcall.s', """        beq @back
        jsr gr_load             ; (FC_PS, the callee's P, stays)
@back:""", """        beq @back
        stx FC_T+1              ; (planted: only a caller in that slot:
        tsx                     ;   its return's high byte)
        lda $0102,x
        cmp #>TW_SLOT2
        lda #1
        adc #0
        sta FC_T
        cpy FC_T
        bne @back
        lda FC_T+1
        jsr gr_load
@back:""")]),
    # FCALL's return through a restore loses the callee's flags (S5 fcall:
    # gt_fd's carry back in gt_fc; wave 1 as integrated, secfind.md
    # request 11)
    # (since the copy engine, docs/SPEED.md 10, no load writes FC_PS: the
    # plant is a load that does, as the test driver's far_gcopy did)
    'fcall-flags-lost': ('fcall', [('gcall.s', """        jsr gr_load             ; (FC_PS, the callee's P, stays)
@back:""", """        jsr gr_load             ; (planted: P lost in FC_PS)
        stz FC_PS
@back:""")]),
    # the spawn's record written to the banks with g_put, past a cache
    # line that holds the slot (S5 spawn)
    'mosave-past-cache': ('spawn', [('gthink.s', """gt_mosave:
        jsr mo_store
        lda #$FF""", MOSAVE_PAST_CACHE), ('gthink.s', """        jmp pl_put

; ---------------------------------------------------------------------------
; gt_poolinit:""", """        jmp pl_put
mv_bank: .byte RTH, MOBJA, MOBJB, MOBJC
mv_ofs: .byte 0, MO_SIZE, 2 * MO_SIZE, 3 * MO_SIZE

; ---------------------------------------------------------------------------
; gt_poolinit:""")]),
    # GA_PLAYDEMO's continuation without demoplayback = 1 (S5 load)
    'playdemo-no-demoplayback': ('load', [('game/gtest.s', """        lda #1
        sta G_DEMOPLAY""", """        lda #0                  ; (planted: no demoplayback)
        sta G_DEMOPLAY""")]),
}


def run_plant(name: str, fill: int = 0xA5) -> List[str]:
    """The planted bug's check on its scratch build (in build/, deleted
    after): the check's failures (a caught bug gives some)."""
    check, bugs = PLANTS[name]
    tmp = Path(tempfile.mkdtemp(prefix='tmp-m10-plant-', dir=str(BUILD)))
    try:
        obj = G.planted(tmp, bugs)
        b = G.load_build(obj, 'skel')
        if check == 'load':
            level = G.lrun.load_build(G.lrun.OBJ, 'ltest')
            cases = [c for c in LOAD_CASES if c[0] == 'GA_PLAYDEMO']
            return check_load(b, level, fill, cases, compare=False)
        return globals()['check_' + check](b, fill)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


def run_all(fill: int = 0xA5, obj: Optional[Path] = None,
            level_obj: Optional[Path] = None,
            only: Sequence[str] = CHECKS) -> Dict[str, List[str]]:
    b = skel_build(obj)
    out: Dict[str, List[str]] = {}
    for name in only:
        if name == 'load':
            level = G.lrun.load_build(level_obj or G.lrun.OBJ, 'ltest')
            out[name] = check_load(b, level, fill)
        else:
            out[name] = globals()['check_' + name](b, fill)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--fill', default='a5')
    parser.add_argument('--only', default=','.join(CHECKS))
    parser.add_argument('--json', type=Path)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--plants', action='store_true',
                        help='run the planted bugs (each must be caught)')
    args = parser.parse_args(argv)
    if not args.no_build:
        G.make('skel')
        G.lrun.make()
    if args.plants:
        bad = 0
        for name in PLANTS:
            fails = run_plant(name, int(args.fill, 16))
            bad += not fails
            print('%-26s %s' % (name, ('caught: ' + fails[0][:100]) if fails
                                else 'NOT CAUGHT'))
        return 1 if bad else 0
    res = run_all(int(args.fill, 16), only=args.only.split(','))
    for k, v in res.items():
        print('%-8s %s' % (k, 'ok' if not v else '; '.join(v)))
    if args.json:
        args.json.write_text(json.dumps(res, indent=1) + '\n')
    return 1 if any(res.values()) else 0


if __name__ == '__main__':
    sys.exit(main())
