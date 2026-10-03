#!/usr/bin/env python3
"""The places of the playable game's glue (docs/PLAY.md 3): the main loop's
resident kernel in the main card, its step buffer, the persistent block
the main loop keeps in main memory, the bank DLBANK, the entry codes of
the brain (the main loop's part in the tic image) and the kernel's step
codes; check() against tools/native/rlayout.py, llayout.py, glayout.py and
s2layout.py (all read only), and the generated include play.inc.

Usage:  python3 tools/native/playlayout.py --check
        python3 tools/native/playlayout.py --inc OUT/play.inc
        python3 tools/native/playlayout.py --report

Every address here is the port's own allocation (docs/PLAY.md 3), taken
from what MEMORY_MAP.md sections 3.3, 4.2, 17 and 18 leave free:

  main $1F00-$1F7F   DLM, the main loop's persistent block (the boot clears
                     $0C00-$1FFF; milestone 10's globals end at $1EFB,
                     milestone 11's key table starts at $1F80)
  card $FE7B-$FE7F   the kernel's five bytes (after the replay's BKNEAR,
                     which rcard's link ends at $FE7A: checked against the
                     link when it exists)
  card $FE80-$FEFF   DLBUF, the step list the kernel runs (one page: a
                     LOAD step's page runs are read by far_pload inside its
                     RAMRD window, so they must be in the card)
  card $FF00-$FFF9   the kernel (pl_ready's place: DOOM.SYSTEM's boot ends
                     with jmp pl_ready, $FF00, which the second half
                     replaces with the title loop: SCREENS.md 2.5), with
                     the benchmark timing's bt_replay at BT_REPLAY
  main $0844-$0877   the benchmark timing's bt_ext (BT_EXT: MEMORY_MAP.md
                     3.2's free bytes; the brain writes it at each
                     benchmark's start; docs/PLAY.md 15); its bt_mark in the
                     menu loop's main bytes (BT_MARK, BT_MARK2)
  bank 1            DLBANK: the static tables' PRIVATE request and their
                     sources, DLINIT's image (a spare bank: llayout.SPARE,
                     s2layout.SPARE_FREE)
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
PLAY = BUILD / 'native' / 'play'

# ---------------------------------------------------------------------------
# The kernel (main card) and its step buffer
# ---------------------------------------------------------------------------
KERNEL = (0xFF00, 0xFFFA)       # pl_ready's place, to the vectors
DLBUF = (0xFE80, 0xFF00)        # the step list (one page)
KVARS = (0xFE7B, 0xFE80)        # the kernel's own bytes
KMAIN = (0x0880, 0x0900)        # the kernel's menu loop: read-only code in
KMAIN2 = (0x0B94, 0x0C00)       #   main's free $0880-$08FF and $0B94-$0BFF
                                #   (MEMORY_MAP.md 3.2), DLINIT's PRIVATE
                                #   copy
KVAR_FIELDS = [('KV_PTR', 1), ('KV_BANK', 1), ('KV_N', 1), ('KV_T', 2)]

# the kernel's steps (dl_kern.s): the code, then its operands
STEPS = [
    ('K_END', 0),       # the step list's end: the next frame (TIC E_FRAME)
    ('K_LOAD', 1),      # bank, then page runs (first page, count; 0 ends):
                        #   far_pload
    ('K_CALL', 2),      # address (2), A, X: jsr (Y 0); A into DL_RES
    ('K_WLOAD', 3),     # far_wload (the render front end's window)
    ('K_MLOAD', 4),     # far_mload (the masked phase's image)
    ('K_TIC', 5),       # code: the tic image and its planes into W, then
                        #   the brain with DL_CODE = code; the brain writes
                        #   the next step list
    ('K_MENU', 6),      # the menu's paused frames (MENUW in W): events to
                        #   m_responder (a key it does not eat: gamekeydown),
                        #   m_ticker for each new tic, m_frame, until the
                        #   menu closes or makes a request (its code in main
                        #   $0880, KMAIN)
    ('K_HALT', 7),      # interrupts off, stop (the quit's end)
]
STEP = dict(STEPS)

# the brain's entry codes (DL_CODE)
ENTRIES = [
    ('E_BOOT', 0),      # the first entry: the settings, D_StartTitle, the
                        #   boot list (DLINIT, the 2D images' inits)
    ('E_FRAME', 1),     # a frame: the events, the tics, the frame's list
    ('E_RESUME', 2),    # after a level load: g_resume, the tic again
    ('E_EVENT', 3),     # after AMAPW's am_responder took or left an event
    ('E_MENU', 4),      # after the menu's frames: its request
]
ENTRY = dict(ENTRIES)

# ---------------------------------------------------------------------------
# DLM: the main loop's persistent block, main $1F00-$1F7F
# ---------------------------------------------------------------------------
DLM = (0x1F00, 0x1F80)
NUMKEYS = 23                    # keys.inc's Doom keys (gamekeydown)
NUMCHEATS = 15                  # m_cheat65.s's sequences
DLM_FIELDS = [
    ('DL_CODE', 1),             # the brain's entry code (the kernel's)
    ('DL_LASTM', 2),            # lastmadetic: I_GetTime's low word
    ('DL_MAKETIC', 2),          # maketic's low word
    ('DL_RUN', 1),              # the tics left to run in this frame
    ('DL_ADVDEMO', 1),          # advancedemo
    ('DL_DEMOSEQ', 1),          # demosequence
    ('DL_PAGETIC', 2),          # pagetic (signed)
    ('DL_OLDGS', 1),            # display's oldgamestate
    ('DL_WIPEGS', 1),           # wipegamestate
    ('DL_PAGEDRAWN', 1),        # pagedrawn
    ('DL_KEYS', NUMKEYS),       # gamekeydown
    ('DL_TURNF', 1),            # turnframes
    ('DL_NEWFRAME', 1),         # iigs_newframe
    ('DL_FUDGE', 1),            # fudgecount
    ('DL_CHT', NUMCHEATS),      # CHT_P: each cheat's next character
    ('DL_RES', 1),              # K_CALL's A after the call
    ('DL_EVST', 1),             # the head event's routing: 1 AM asked
    ('DL_EV', 3),               # the event being routed (type, data1)
    ('DL_STP', 1),              # the step list's next byte (the writer)
    ('DL_LEFT', 1),             # display: a level was left (bit 0)
    ('DL_WIPE', 1),             # display: gamestate != wipegamestate
    ('DL_P2F', 1),              # display: s2_frame's flags (dl_p2d.s)
    ('DL_FLAGS', 1),            # DF_* below
    ('DL_TICS', 1),             # the frame's tics (am_frame, am_ovl)
    ('DL_SONG', 1),             # the song that plays ($FF none)
    ('DL_SETRUN', 1),           # the settings' always run (SS_SETTINGS+0)
    ('DL_SETMOUSE', 1),         # mouse on (+2)
    ('DL_SETMSPD', 1),          # mouse speed (+3)
    ('DL_FPSN', 2),             # idrate: the frames since the last second
    ('DL_FPST', 2),             #   and its start (I_GetTime's low word)
    ('DL_VIEWS', 2),            # the 3D views drawn (the frame rate's count)
    ('DL_BENCH', 1),            # the menu benchmark: 0 none, 1 runs, $80 its result to show
    ('DL_BVIEW', 2),            #   DL_VIEWS at its start; at its end the frames
    ('DL_BRT', 4),              #   at its end the realtics
    # the benchmark's phase timing (docs/PLAY.md 15): VIA-A's timer 1
    # read at the frame's phase boundaries while the benchmark runs
    ('BT_PH', 1),               # the phase being timed (PH_*), 0: off
    ('BT_NX', 1),               #   the phase after the tic phase's close
    ('BT_T', 2),                # the timer at the last boundary
    ('BT_V', 1),                #   vbl_count's low byte there
    ('BT_CT', 2),               # the timer at the last close (the tic
    ('BT_CV', 1),               #   phase's end), vbl_count's low byte
    ('BT_S', 20),               # the five phases' bus cycles (4 B each,
                                #   PH_TIC .. PH_REST)
    ('BT_SS', 4),               # the four short sums at the last close
    ('BT_OVF', 1),              # turns lost no long interval explains,
                                #   or two long intervals in one span
    ('BT_J', 6),                # nat_replay's first instruction, jmp past it
    ('BT_LP', 1),               # the phase of the span's interval of 3
                                #   VBLs or more (bt_mark's), 0: none
]
# the phases' offsets into BT_S + 4 (0: no timing)
PHASES = [('PH_TIC', 4), ('PH_3D', 8), ('PH_MASK', 12), ('PH_DRAW', 16),
          ('PH_REST', 20)]
BT_MARK = 0x08CA                # the kernel's bt_mark (main KMAIN, after
                                #   the menu loop's first part), its last
BT_MARK2 = 0x0BE1               #   part (KMAIN2, after the loop's second)
BT_EXT = (0x0844, 0x0878)       # its middle part: main's free $0844-$0877
                                #   (MEMORY_MAP.md 3.2), which the brain's
                                #   bt_start writes before the timing
BT_REPLAY = 0xFFC4              # its bt_replay (the card, after the
                                #   kernel's step code)
FLAGS = [
    ('DF_PALLEVEL', 0x01),      # PALW palw_level before the next 2D
    ('DF_PALGAMMA', 0x02),      # PALW palw_gamma (the menu's M_RELOAD)
    ('DF_LOADSCR', 0x04),       # F_LoadScreen: FINW's fin_load at the load
    ('DF_QUIT', 0x08),          # the quit's request
    ('DF_INIT', 0x10),          # the boot's inits ran
]

# ---------------------------------------------------------------------------
# DLBANK
# ---------------------------------------------------------------------------
DLBANK = 1
DLB_PRIV = 0x0200               # the static tables' PRIVATE request: its
DLB_PRIVMAX = 0x0100            #   20-byte header, then its descriptors
DLB_TABLES = 0x1000             # the static tables' sources (their bytes)
DLB_TABLES_END = 0x2000
DLINIT_LO = 0x6600              # DLINIT's image at its W addresses
DLINIT_HI = 0x7000

# the static tables (MEMORY_MAP.md 3.2, 5: "boot, PRIVATE"; design.md R7
# item 15): main's CMPA, CMPB, TEXLO, XTVLO, TEXHI, XTVHI and aux 0's
# drawers, ROWLO, FZDIR, ROWHI. The colormaps and FUZZDARK are each
# level's (the load's PRIVATE requests).
STATIC_MAIN = ((0x0800, 0x0844), (0x0900, 0x0B94))
STATIC_AUX0 = ((0x0200, 0x02C0), (0x0900, 0x09FA), (0x0A00, 0x0AC8))

# my groups in the tic image: their offsets after glayout's GROUPS, their
# slots (gcall.s's grp_slot is written by the disk builder for them)
DL_GROUPS = [('DLG_B', 1, 2),   # the brain: events, the tics, the loads
             ('DLG_C', 2, 1),   # the tic command (G_BuildTiccmd)
             ('DLG_D', 3, 1),   # the frame's list (display), the inputs
             ('DLG_H', 4, 1),   # the hooks' bodies, the channels, the
                                #   finale's ticker
             ('DLG_S', 5, 1)]   # the status bar's ticker, the songs, the
                                #   title loop, the renderer's boot state
# (the brain alone in slot 2: every group it calls is in slot 1, so a call
# of the brain's never evicts it; game code's calls of the hooks evict and
# restore their caller's group, gcall.s's fc_call. Each tic loads DLG_S
# for the status bar's ticker; the HUD's ticker, s2t_hu.s, is in the core
# since speed wave 2 (play.mk's PLAY_TIC), so no tic loads DLG_H for it:
# docs/speed-parts/glue.md)

# MAXTICS (upstream's tics.inc), the command ring (G_CMDS: CMDS of 8 B)
MAXTICS = 4
CMDS = 8

# the HUD's and the song directory's songs (mus.UPSTREAM_SONGS' order)
SONG_E1M1, SONG_INTER, SONG_INTRO, SONG_VICTOR = 0, 9, 10, 11
SONG_LOOP = 1                   # src/sound/player.s SONG_LOOP


def allocate(fields, lo: int, hi: int) -> Dict[str, int]:
    out, at = {}, lo
    for name, size in fields:
        out[name] = at
        at += size
    if at > hi:
        raise ValueError('the block passes $%04X: $%04X' % (hi, at))
    return out


DLMA = allocate(DLM_FIELDS, *DLM)
KVA = allocate(KVAR_FIELDS, *KVARS)
DLM_USED = max(DLMA[n] + k for n, k in DLM_FIELDS) - DLM[0]


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------

class Region(NamedTuple):
    space: str
    start: int
    end: int
    what: str


def regions() -> List[Region]:
    return [Region('main', DLM[0], DLM[1], 'the main loop\'s block'),
            Region('main', KMAIN[0], KMAIN[1], 'the kernel\'s menu loop'),
            Region('main', KMAIN2[0], KMAIN2[1], 'its second part'),
            Region('card', KVARS[0], KVARS[1], 'the kernel\'s bytes'),
            Region('card', DLBUF[0], DLBUF[1], 'the step list'),
            Region('card', KERNEL[0], KERNEL[1], 'the kernel')]


def rcard_end() -> Optional[int]:
    """The last card byte of milestone 8's rcard link in $F900-$FEFF (its
    BKNEAR), when the link exists."""
    try:
        from native import render_check as RC
        rc = RC.load_build(RC.OBJ, 'rcard')
    except Exception:
        return None
    ends = [hi for name, (lo, hi) in rc.segments.items()
            if 0xF900 <= lo < 0xFF00]
    return max(ends) if ends else None


def check() -> List[str]:
    """The problems ([] when none): a place over another layout's region,
    a block over its room, a bank in use."""
    out = []
    if DLM_USED > DLM[1] - DLM[0]:
        out.append('DLM uses %d of %d B' % (DLM_USED, DLM[1] - DLM[0]))
    # milestone 10's main regions (the globals, G_WSET, G_FPSSHOW after
    # them) and milestone 11's key table
    try:
        from native import glayout as GL
        for r in GL.regions():
            if r.space == 'main' and r.start < DLM[1] and DLM[0] < r.end:
                out.append('DLM $%04X-$%04X meets glayout\'s %s $%04X-$%04X'
                           % (DLM[0], DLM[1] - 1, r.what, r.start, r.end - 1))
        if GL.TIC_MAIN_END > DLM[0]:
            out.append('glayout\'s main globals end at $%04X, past DLM'
                       % GL.TIC_MAIN_END)
    except ImportError:
        out.append('glayout.py is missing')
    from native import s2layout as S
    if DLM[1] > S.KEYTAB_PLACE[0] and DLM[0] < S.KEYTAB_PLACE[1]:
        out.append('DLM meets PL_KEYTAB $%04X' % S.KEYTAB_PLACE[0])
    if DLBANK in dict(LL.bank_map()):
        out.append('DLBANK %d is %s' % (DLBANK, dict(LL.bank_map())[DLBANK]))
    if DLBANK not in S.SPARE_FREE:
        out.append('DLBANK %d is not among s2layout\'s spare banks %r'
                   % (DLBANK, S.SPARE_FREE))
    if (DLBUF[0] & 0xFF) != 0x80 or (DLBUF[1] - DLBUF[0]) != 0x80:
        out.append('DLBUF must be the page\'s upper half (a LOAD\'s runs '
                   'are addressed as $80 | offset)')
    if S.PLATFORM_CARD[1] != KERNEL[0]:
        out.append('the kernel is not at the platform\'s $%04X'
                   % S.PLATFORM_CARD[1])
    if KERNEL[1] > S.VECTORS[1]:
        out.append('the kernel meets the vectors')
    end = rcard_end()
    if end is not None and end >= KVARS[0]:
        out.append('rcard\'s replay part ends at $%04X, at the kernel\'s '
                   'bytes $%04X' % (end, KVARS[0]))
    for lo, hi in STATIC_MAIN + (KMAIN, KMAIN2):
        if lo < 0x0880 and hi > 0x0878:
            out.append('a static main range over $0878-$087F (rule 8)')
    for lo, hi in STATIC_MAIN:
        for klo, khi in (KMAIN, KMAIN2):
            if lo < khi and klo < hi:
                out.append('the kernel\'s menu loop meets a static table')
    if not (KMAIN[0] <= BT_MARK < KMAIN[1]):
        out.append('bt_mark $%04X is not in the menu loop\'s $%04X-$%04X'
                   % (BT_MARK, KMAIN[0], KMAIN[1] - 1))
    if not (KMAIN2[0] <= BT_MARK2 < KMAIN2[1]):
        out.append('bt_mark2 $%04X is not in $%04X-$%04X'
                   % (BT_MARK2, KMAIN2[0], KMAIN2[1] - 1))
    for lo, hi in STATIC_MAIN + (KMAIN, KMAIN2, (0x0878, 0x0880)):
        if lo < BT_EXT[1] and BT_EXT[0] < hi:
            out.append('BT_EXT $%04X-$%04X meets $%04X-$%04X'
                       % (BT_EXT[0], BT_EXT[1] - 1, lo, hi - 1))
    if not (KERNEL[0] <= BT_REPLAY < KERNEL[1]):
        out.append('bt_replay $%04X is not in the kernel' % BT_REPLAY)
    size = sum(hi - lo for lo, hi in STATIC_MAIN + STATIC_AUX0 +
               (KMAIN, KMAIN2))
    if DLB_TABLES + size > DLB_TABLES_END:
        out.append('the static tables pass their room in DLBANK')
    return out


# ---------------------------------------------------------------------------
# play.inc
# ---------------------------------------------------------------------------

def constants() -> List[Tuple[str, int]]:
    out = [('DLM', DLM[0]), ('DLM_END', DLM[1]),
           ('DLBUF', DLBUF[0]), ('DLBUF_SIZE', DLBUF[1] - DLBUF[0]),
           ('KERNEL', KERNEL[0]), ('DLBANK', DLBANK),
           ('DLB_PRIV', DLB_PRIV), ('DLB_TABLES', DLB_TABLES),
           ('DLINIT_LO', DLINIT_LO), ('DLINIT_HI', DLINIT_HI),
           ('NUMKEYS', NUMKEYS), ('KMAIN', KMAIN[0]),
           ('NUMCHEATS', NUMCHEATS), ('MAXTICS', MAXTICS), ('CMDS', CMDS),
           ('SONG_E1M1', SONG_E1M1), ('SONG_INTER', SONG_INTER),
           ('SONG_INTRO', SONG_INTRO), ('SONG_VICTOR', SONG_VICTOR),
           ('SONG_LOOP', SONG_LOOP),
           ('PL_LH_SKY', LL.LH_SKY), ('PL_DIR_ENTRY', LL.STORE_DIR_ENTRY),
           ('PL_FB_END', R.FB_END), ('PL_SPANS', R.SPANS),
           ('PL_SPANS_END', R.SPANS_END),
           ('BT_MARK', BT_MARK), ('BT_MARK2', BT_MARK2),
           ('BT_EXT', BT_EXT[0]), ('BT_EXT_END', BT_EXT[1]),
           ('BT_REPLAY', BT_REPLAY)]
    out += PHASES
    out += sorted(DLMA.items(), key=lambda kv: kv[1])
    out += sorted(KVA.items(), key=lambda kv: kv[1])
    out += STEPS + ENTRIES + FLAGS
    out += [(name, off) for name, off, _ in DL_GROUPS]
    return out


def inc_text() -> str:
    lines = ['; Generated by tools/native/playlayout.py (docs/PLAY.md 3). '
             'Do not edit.', '']
    for name, value in constants():
        lines.append('%-16s= $%04X' % (name, value))
    lines.append('; my groups: GROUPS (gplace.inc) + their offsets, slots')
    for name, off, slot in DL_GROUPS:
        lines.append('%s_SLOT = %d' % (name, slot))
    return '\n'.join(lines) + '\n'


def report() -> List[str]:
    out = ['DLM $%04X-$%04X: %d of %d B' % (DLM[0], DLM[1] - 1, DLM_USED,
                                          DLM[1] - DLM[0])]
    for name, size in DLM_FIELDS:
        out.append('  $%04X %-14s %d' % (DLMA[name], name, size))
    out.append('kernel $%04X-$%04X, step list $%04X-$%04X, its bytes '
               '$%04X-$%04X' % (KERNEL[0], KERNEL[1] - 1, DLBUF[0],
                                DLBUF[1] - 1, KVARS[0], KVARS[1] - 1))
    out.append('DLBANK %d' % DLBANK)
    return out


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--inc', type=Path)
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args(argv)
    problems = check()
    if problems:
        for p in problems:
            print('playlayout: %s' % p, file=sys.stderr)
        return 1
    if args.inc:
        write_if_changed(args.inc, inc_text())
    if args.report:
        print('\n'.join(report()))
    if args.check:
        print('playlayout check: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
