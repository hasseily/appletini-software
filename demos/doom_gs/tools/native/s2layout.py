#!/usr/bin/env python3
"""The places of milestone 11's first half (docs/SCREENS.md 4): the 2D
images in W and their rooms, the size table, the packing of the images'
stored pages into banks, main's input block, the zero page, the card's
blocks (with their per-build addresses), the RamWorks banks, the cost
phases, the regions of the screen and the field map of 6.2; check(), and
the generated include s2.inc and the images' ld65 maps.

Every address is a starting allocation [A] of docs/SCREENS.md 4, held
here and checked against tools/native/rlayout.py, llayout.py and, when it
exists, glayout.py (milestone 10's; all three read only). Where the
design could not be held as written, part s2lay's requests
(docs/m11-parts/s2lay.md S2LAY-1 to -3) changed it; the wave 1
integration applied them to docs/SCREENS.md 4 (its "Wave 1 as
integrated").

Usage:  python3 tools/native/s2layout.py --check
        python3 tools/native/s2layout.py --inc [--build B] OUT/s2.inc
        python3 tools/native/s2layout.py --cfg IMAGE [--build B] OUT.cfg
        python3 tools/native/s2layout.py --check-map IMAGE MAP [MAP...]
        python3 tools/native/s2layout.py --report
        python3 tools/native/s2layout.py --rlayout-inc OUT/rlayout.inc

--check-map fails (status 1) when an image's stored bytes pass its room
(docs/SCREENS.md 4.1: "an image over its room fails the build") and
prints the size table's rows for that image (an object over its budget
is reported, not fatal: the budgets are [A]).
"""

import os
import re
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
LAYOUT_NAME = 's2layout'          # (also when run as __main__)
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R  # noqa: E402

ROOT = HERE.parent.parent
SRC = ROOT / 'src'
GLAYOUT = HERE / 'glayout.py'


def glayout_module():
    """Milestone 10's layout when its file exists (imported read only; an
    import error is an error, not a skip)."""
    if not GLAYOUT.exists():
        return None
    from native import glayout
    return glayout


# ---------------------------------------------------------------------------
# W: the images (4.1)
# ---------------------------------------------------------------------------

W_LO, W_HI = 0x6000, 0xC000
# MATHW then AUXW, the render images' shared bytes, linked into every 2D
# image and stored once a bank [R MEMORY_MAP.md 13: $6000-$6592]
MATHW_LO, MATHW_END = 0x6000, 0x6593
IMAGE_LO = 0x6600


class Image(NamedTuple):
    name: str
    stored: Tuple[int, int]     # the room of its code and data [lo, hi)
    runtime: Tuple[Tuple[int, int, str], ...]   # W it uses, not stored
    state: Optional[Tuple[int, int]]    # its state block in W [lo, hi)
    shared: Tuple[str, ...]     # the shared objects it links (size table)
    own: int                    # the budget of its own code and data
    own_parts: str              # whose
    packed: bool                # in the code banks' packing (OVLW: no)
    frame: bool                 # a frame image: pl_poll, fx_service


# the shared objects of the size table and their budgets (bytes); the
# patch drawer and the publish have one budget, AMAPW links s2_pub alone
SHARED_BUDGETS = {'s2_draw+s2_pub': 1200, 's2_pub': 200, 's2_pal': 800,
                  's2_nib': 400, 'pl_poll': 600, 'fx_service': 400,
                  'fx_chan': 1100,   # (700 until wave 4: FXCHAN-5)
                  # the boot's and the key setup's input routines
                  # (pl_init, pl_defaults, pl_bind, pl_action; part
                  # plinput, request PLINPUT-5: 228 B [M])
                  'pl_keys': 300}
# an object file's stem (its module in ld65's map) to its row of the table;
# MATHW's modules are not counted (stored once a bank, outside the room).
# fx_pcache (the channels' sound cache, 85 B) is fx_chan's (S2MENU1-2).
MODULE_ROW = {'s2_draw': 's2_draw+s2_pub', 's2_pub': 's2_draw+s2_pub',
              's2_pal': 's2_pal', 's2_nib': 's2_nib',
              'pl_input': 'pl_poll', 'fx': 'fx_service',
              'fx_chan': 'fx_chan', 'fx_pcache': 'fx_chan',
              'pl_keys': 'pl_keys'}
MATHW_MODULES = ('math', 'auxlc')

IMAGES: Tuple[Image, ...] = (
    Image('P2DW', (0x6600, 0x8300),
          ((0x8300, 0x9700, 'the band (rows 168-199, then 0-9)'),
           (0x9700, 0x9800, 'marks'),
           (0x9800, 0xB800, 'eight nibble slots'),
           (0xB800, 0xBC00, 'patch fetch buffer'),
           (0xBC00, 0xC000, 'the state block')),
          (0xBC00, 0xC000),
          ('s2_draw+s2_pub', 's2_pal', 'pl_poll', 'fx_service'), 3900,
          's2stbar 2,000, s2hud 1,700 (its texts in S2STATE since wave 4: '
          '1,411 B), glue 200', True, True),
    # (request S2MENU1-2, wave 5: the room shrinks to $A4FF for PALST,
    # which s2_pal's s2_begin and s2_finish need in W; the drawers' marks
    # page; fx_chan's scratch fxc_scr is the fetch buffer's last 32 B,
    # never live during a draw: FXCHAN-4)
    Image('MENUW', (0x6600, 0xA500),
          ((0xA500, 0xA800, 'PALST'),
           (0xA800, 0xB700, 'a 24-row band'),
           (0xB700, 0xB800, 'UI_GRAY'),
           (0xB800, 0xB900, 'marks'),
           (0xB900, 0xBD00, 'the menu palette\'s nibble slot'),
           (0xBD00, 0xBF00, 'fetch buffer'),
           (0xBF00, 0xC000, 'the state block')),
          (0xBF00, 0xC000),
          ('s2_draw+s2_pub', 's2_pal', 's2_nib', 'pl_poll', 'fx_service',
           'fx_chan', 'pl_keys'), 11328,
          's2menu1 5,000, s2menu2 4,000, names and strings 2,328 (2,500 '
          'until wave 5: the room of S2MENU1-2 with PLINPUT-5\'s pl_keys)',
          True, True),
    Image('AMAPW', (0x6600, 0x8E00),
          ((0x8E00, 0xA840, 'a 42-row band'),
           (0xA840, 0xAC00, 'marks'),
           (0xAC00, 0xB000, 'the state block'),
           (0xB000, 0xC000, 'the new byte list (2,048 entries)')),
          (0xAC00, 0xB000),
          ('s2_pub',), 7000, 's2amap', True, False),
    # (requests S2WI-2 and S2WI-6, wave 5: the own budget 1,950; the
    # nibble tables as 16 units of 2 pages, a palette and a parity)
    Image('WIW', (0x6600, 0x8000),
          ((0x8000, 0x9900, 'a 40-row band'),
           (0x9900, 0x9A00, 'marks'),
           (0x9A00, 0xBA00, '16 nibble units of 2 pages'),
           (0xBA00, 0xBC00, 'fetch buffer'),
           (0xBC00, 0xC000, 'the state block')),
          (0xBC00, 0xC000),
          ('s2_draw+s2_pub', 's2_pal', 's2_nib', 'pl_poll', 'fx_service'),
          1950, 's2wi 1,400, data 550', True, True),
    Image('FINW', (0x6600, 0x8000),
          ((0x8000, 0x9900, 'a 40-row band'),
           (0x9900, 0x9A00, 'marks'),
           (0x9A00, 0xBA00, '16 nibble units of 2 pages (bands of 16 rows)'),
           (0xBA00, 0xBC00, 'fetch buffer'),
           (0xBC00, 0xC000, 'the state block')),
          (0xBC00, 0xC000),
          ('s2_draw+s2_pub', 's2_pal', 's2_nib', 'pl_poll', 'fx_service'),
          # (requests S2FIN-3 and S2FIN-6, wave 6: the own budget 2,300 with
          # the end text and the font's table; the units as WIW's)
          2300, 's2fin 1,600, data 700', True, True),
    Image('PALW', (0x6600, 0x8000),
          ((0x8000, 0xC000, 'the build\'s buffers'),),
          None, ('s2_nib',), 1500, 's2pal', True, False),
    # the automap overlay's producer, in MASKW's code room, loaded by
    # far_pload of its page runs from its own bank (not packed); milestone
    # 8's W ranges outside it are untouched [R MEMORY_MAP.md 13]. Its run
    # time places are inside its room, above its stored bytes (request
    # S2OVL-3, wave 7: problems_of and size_rows check both)
    Image('OVLW', (R.MCODE, R.MCODE_END),
          ((0x9400, 0x9C00, 'the nibble pages, NCACHE, RBASE, the '
            'variables, s2_amline\'s W variables (AMW $9A00), the state '
            'block (AMST $9B00)'),),
          None, (), 5500,
          's2_ovl 1,214 [M] and s2_amline 3,708 [M] (part s2amap\'s, with '
          'S2OVL-1\'s hook): 4,919 [M]; rrec.s 198, nm_bkload 48, '
          'BKFAR/BKFAR2 947 [M] (not in the S2 segments): 6,115 of 13,312 B '
          'stored',
          False, False),
)
IMAGE = {im.name: im for im in IMAGES}
# the design's totals (4.1's last row), checked against the sums above
DESIGN_TOTALS = {'P2DW': 6900, 'MENUW': 16128, 'AMAPW': 7200, 'WIW': 5350,
                 'FINW': 5700, 'PALW': 1900}


# each drawing image's places for the drawers (part s2draw, request
# S2DRAW-1), exported by the image's glue as s2_marks, s2_fbuf and
# s2_fbpages: (the marks page: DRB, DRE, ROWL, ROWR; the fetch buffer or
# None; its pages). MENUW's marks page has no room yet (its runtime
# ranges were full): part s2menu1 placed them (request S2MENU1-2, wave 5).
DRAW_PLACES = {'P2DW': (0x9700, 0xB800, 4),
               'MENUW': (0xB800, 0xBD00, 2),
               'AMAPW': (0xA900, None, 0),
               'WIW': (0x9900, 0xBA00, 2),
               'FINW': (0x9900, 0xBA00, 2)}


def budget_total(im: Image) -> int:
    return sum(SHARED_BUDGETS[s] for s in im.shared) + im.own


# ---------------------------------------------------------------------------
# RamWorks banks (4.5)
# ---------------------------------------------------------------------------

SONGS = (100, 101, 102)
# the songs' directory (part plboot, PLBOOT-2): at bank SONGS[0] $0200,
# 3 bytes a song in tools/sound/mus.py UPSTREAM_SONGS' order (D_E1M1
# .. D_E1M9, D_INTER, D_INTRO, D_VICTOR, D_INTROA): its bank, its
# address; the songs after it, first-fit, largest first, never across
# a bank
SONG_DIR = (SONGS[0], 0x0200)
SONG_DIR_ENTRY = 3
SONG_COUNT = 13                 # len(mus.UPSTREAM_SONGS)
SFX = 103
S2STATE = 104
S2VIEW = 105
S2PAL = 106
S2CODE0, S2CODE1 = 107, 108
GFX = (109, 110, 114, 115)
OVLW_BANK = 93
S2CODE2 = 94
# the first design's three code banks (SCREENS.md 4.1 before wave 1)
FIRST_CODE_BANKS = (S2CODE0, S2CODE1, S2CODE2)
# Request S2LAY-1, applied (SCREENS.md 4.1 "Packing", 4.5): every packed
# image's stored pages start at $6600, and far_pload copies a bank's pages
# to the same addresses, so no two images can share a bank and the first
# design's three code banks hold three of the six; three of the spare banks
# of GAME.md 1.10 take the other three, one image a bank.
S2CODE3_5 = (95, 96, 97)
CODE_BANKS = FIRST_CODE_BANKS + S2CODE3_5
# the banks milestones 9 and 10 left spare (GAME.md 1.10: 1-3, 93-97, 125,
# 126; 4 and 5 hold milestone 9's test data: ldisk.py's CRC_BANK and
# PRE_BANK)
SPARE_FREE = (1, 2, 3, 93, 94, 95, 96, 97, 125, 126)
# rlayout's CODE banks 114 and 115: the release uses 112 (WCODE_BANK) and
# 113 (MCODE_BANK) only; 114 is MRTN_BANK, written by milestone 8's
# routine-mode harness alone (never in a 2D run), 115 is unused
CODE_REUSED = {114: 'MRTN_BANK (milestone 8\'s routine-mode harness only)',
               115: 'unused'}


def banks() -> List[Tuple[int, str]]:
    out = [(b, 'SONGS%d' % i) for i, b in enumerate(SONGS)]
    out += [(SFX, 'S2SFX'), (S2STATE, 'S2STATE'), (S2VIEW, 'S2VIEW'),
            (S2PAL, 'S2PAL'), (S2CODE0, 'S2CODE0'), (S2CODE1, 'S2CODE1')]
    out += [(b, 'GFX%d' % i) for i, b in enumerate(GFX)]
    out += [(OVLW_BANK, 'S2OVLW'), (S2CODE2, 'S2CODE2')]
    out += [(b, 'S2CODE%d' % (3 + i)) for i, b in enumerate(S2CODE3_5)]
    return out


# ---- S2STATE (bank 104): the 2D state between frames (4.6) ----------------
# The state blocks are NOT at their W addresses in the bank (P2DW's, WIW's
# and FINW's are all at W $BC00): they are fetched with far_get and written
# back with far_put, 256 bytes a call (request S2LAY-2, applied: SCREENS.md
# 4.6).
PALST_SIZE = 768                # the palette state (1.3: scb, palette, flags)
S2STATE_FIELDS = [
    ('SS_PALST', PALST_SIZE),   # shared by every image that publishes
    ('SS_P2DW', 0x0100),        # P2DW's own (its W block: PALST, then this)
    ('SS_MENUW', 0x0100),
    ('SS_AMAPW', 0x0400),
    ('SS_WIW', 0x0100),
    ('SS_FINW', 0x0100),
    ('SS_SETTINGS', 0x0020),    # the menu's settings that persist
    ('SS_STCACHE', 5120),       # STCACHE: rows 168-199 of the status bar
    ('SS_HUDTXT', 2 * 4096),    # the HUD's two text slots' records (1.4)
    ('SS_AMOLD', 2 * 2048),     # the automap's old byte list
    ('SS_SIGN', 4096),          # the busy sign's saved rows
    # the status bar's rows 168-199 as published, upstream's back buffer's
    # (part s2stbar, request S2STBAR-2)
    ('SS_STBUF', 5120),
    # the HUD's texts, an index of 256 words then 36-byte entries (part
    # s2hud, request S2HUD-3: the bank file HUDTXT.1, 2,672 B)
    ('SS_HUDMSG', 0x0C00),
    # the full map's lines clipped on the screen, 8 bytes each (part
    # s2amap, request S2AMAP-2)
    ('SS_AMSEG', 0x3000),
]
SS = R.allocate(S2STATE_FIELDS, LL.ROOM[0], LL.ROOM[1])
SS_SIZE = dict(S2STATE_FIELDS)

# S2PAL (bank 106, SCREENS.md 4.5): part s2pal's places (request
# S2PAL-1); each in the bank's $0200-$BFFF (a RAMRD window reaches nothing
# else), S2P_NIB page aligned (a palette's table at S2P_NIB + p * $400).
# GSSTAT and GSOVL are the 2D store's lumps put at these places by part
# s2data's GFX.1 (their handles name them here; S2DATA-3 as integrated).
S2PAL_PLACES = [('S2P_TINTPAL', 0x0200, 14 * 384),
                ('S2P_NIB', 0x1800, 16 * 0x400),
                ('S2P_GSSTAT', 0x5800, 5664),
                ('S2P_GSOVL', 0x6E20, 2112),
                ('S2P_GRAYMAP', 0x7700, 256)]
S2PAL_AT = {n: a for n, a, _ in S2PAL_PLACES}
S2PAL_SIZE = {n: z for n, _, z in S2PAL_PLACES}

# bank 103: SFX.1 at $0200 (part fxconv: 11,385 B; its room about 15 KB);
# the 2D store takes the rest (part s2data; request S2DATA-1)
SFX_ROOM = (0x0200, 0x4000)
# bank 105: the menu's saved screen (SCREENS.md 1.5.3); the 2D store
# takes $0200-$1FFF and $A000-$BFFF around it (part s2data)
S2VIEW_SAVE = (0x2000, 0xA000)
# the 2D store's handles table (part s2data)
GFXDIR_PLACE = (GFX[0], 0x0200)


# ---------------------------------------------------------------------------
# Main memory (4.2)
# ---------------------------------------------------------------------------

PL_STATUS = 0x03AE              # LV_STATUS's byte (llayout), the stops
INPUT_FIELDS = [
    ('PL_QUEUE', 15 * 3),       # the event queue: type, Doom key, character
    ('PL_QHEAD', 1), ('PL_QTAIL', 1),
    ('PL_HELD', 1),             # the held //e key
    ('PL_BUTTONS', 1),          # the Apple keys' and the buttons' state
    ('PL_MDX', 2),              # upstream's iigs_mousedx
    # the mouse's last X (low, high); the sequence byte needs no
    # persistent byte (part plinput, request PLINPUT-2)
    ('PL_MLX', 2),
    ('PL_REPKEY', 1), ('PL_REPCH', 1), ('PL_REPTIC', 2),   # the repeat
    ('PL_DEFER', 1),            # the deferred polls' count
    # the key setup: $FF waits, a //e code taken, $80 idle (upstream's
    # iigs_bindwait and iigs_bindcode; part plinput, request PLINPUT-3)
    ('PL_BIND', 1),
]
# PL_BIND's values (pl_input.inc's BIND_WAIT, BIND_IDLE; the menu's key
# setup writes PLB_WAIT and, once it has bound the code, PLB_IDLE)
PL_BIND_VALUES = (('PLB_WAIT', 0xFF), ('PLB_IDLE', 0x80))
# Request S2LAY-3, applied (SCREENS.md 2.4, 4.2): the first design's $03B2
# met milestone 10's GS_ARG, a word at $03B1-$03B2 (glayout.regions():
# $03B0-$03B2; gcall.s stores GS_ARG and GS_ARG+1), so the block starts at
# $03B3 (59 bytes used since wave 5's PLINPUT-3)
INPUT_LO, INPUT_END = 0x03B3, 0x03EE
INPUT = R.allocate(INPUT_FIELDS, INPUT_LO, INPUT_END)
# the //e key table's Doom keys, 128 B (part plinput, request PLINPUT-1):
# persistent, written by pl_keys.s only (the boot, the key setup), read by
# every poll
KEYTAB_PLACE = (0x1F80, 0x2000)
QUEUE_EVENTS, EVENT_SIZE = 15, 3
# page 1: the publish loop's descriptors may use $0100-$01B4 outside the
# replay; the stack stays at or above $01C0 [A, as the replay's gather]
PAGE1_DESC = (0x0100, 0x01B5)
STACK_FLOOR = 0x01C0
STACK_2D = 64                   # MEMORY_MAP.md 2: 2D phases
IRQ_STACK = R.IRQ_STACK         # 24

# The stop codes in PL_STATUS: the test driver's (S2S_*) and the boot's
# (PL_*, part plboot). The load's LS codes share the byte in other builds.
S2S = {'RUN': 0x80, 'DONE': 0x81, 'BRK': 0x82}
PL = {'READY': 0xC0, 'NOMOUSE': 0xC1, 'BANKS': 0xC2, 'NOAMEM': 0xC3,
      'CRC': 0xC4,
      'MENUAMEM': 0xC5,         # the menu's save failed (S2MENU1-2)
      'SIGNAMEM': 0xC6,         # the busy sign's save failed (S2FIN-1)
      'DISK': 0xC7,             # DOOM.SYSTEM: a ProDOS error, not a bank
                                #   file, a segment outside banks 1-126 or
                                #   $0200-$BFFF (part plboot, PLBOOT-1)
      # a full-map frame whose lines' rows use more than 4 palettes, or
      # more clipped lines than SS_AMSEG holds (both impossible upstream;
      # part s2amap, request S2AMAP-4)
      'AMPALS': 0xD1, 'AMSEGS': 0xD2}

# ---------------------------------------------------------------------------
# Zero page (4.3)
# ---------------------------------------------------------------------------

ZP_S2 = (0x48, 0x80)            # S2_*: the band, the patch, the publish
ZP_S2M = (0x80, 0xB0)           # S2M_*, S2A_*: the menu's, the automap's
                                #   ($80-$AE, S2AMAP-5);
                                #   S2W_* $80-$AD, WIW's temporaries
                                #   (S2WI-1; nothing kept between frames);
                                #   FZ_* $80-$A4, FINW's (S2FIN-2; nothing
                                #   kept between calls)
# pl_poll's temporaries PLZ (part plinput, request PLINPUT-4): the
# drawers' S2_W .. S2_O, never live across a drawer's call; the poll runs
# first in a frame, before any drawer (2.1)
PL_ZP = (0x5A, 0x6A)
ZP_MATH = (0xB0, 0xD8)          # the math block [R src/native/MATH.md]
ZP_MUSIC = (0xD8, 0xD8 + 31)    # S2's player [R src/sound/README.md]
# the effect player's interrupt: the ring of the voice it runs and four
# temporaries (part fxplay, request FXPLAY-1)
ZP_FXRING = (0xF7, 0xFD)
ZP_SPARE = (0xFD, 0x100)
ZP_IRQ = (0xD8, 0x100)          # MEMORY_MAP.md rule 2
FX_ZP = {'FXZ_RING': 0xF7, 'FXZ_N': 0xF9, 'FXZ_T': 0xFA, 'FXZ_AV': 0xFB,
         'FXZ_OP': 0xFC}
# the 2D drawers' zero page in ZP_S2 (src/native/s2_draw.s, s2_pub.s; part
# s2draw, request S2DRAW-1): (name, address, bytes). The arguments and the
# band's state, kept between calls, then the temporaries, free between
# calls. S2_RY0..S2_RB1 (s2_rect, s2_raw) share S2_X and S2_Y's bytes.
S2_ZP = [
    ('S2_BAND', 0x48, 2),       # the band's first row in W
    ('S2_Y0', 0x4A, 1),         # the band's first screen row
    ('S2_Y1', 0x4B, 1),         # the row after its last (<= 200)
    ('S2_X', 0x4C, 2),          # a patch's x (signed)
    ('S2_Y', 0x4E, 2),          # a patch's y (signed)
    ('S2_RY0', 0x4C, 1),        # s2_rect, s2_raw: the rows S2_RY0 ..
    ('S2_RY1', 0x4D, 1),        #   S2_RY1 - 1,
    ('S2_RB0', 0x4E, 1),        #   the bytes S2_RB0 .. S2_RB1
    ('S2_RB1', 0x4F, 1),
    ('S2_PBANK', 0x50, 1),      # the source: its RamWorks bank
    ('S2_PADDR', 0x51, 2),      # and its address (s2_rect: of row 0, byte 0)
    ('S2_CAP', 0x53, 1),        # bit 7: the patch drawer records CAPVAL
    ('S2_CAPD', 0x54, 2),       # CAPVAL's address less the band byte's
    ('S2_CAPM', 0x56, 2),       # CAPMSK's address less CAPVAL's
    ('S2_DRY0', 0x58, 1),       # the band rows with marks: S2_DRY0 ..
    ('S2_DRY1', 0x59, 1),       #   S2_DRY1 - 1 (S2_DRY1 0: none)
    ('S2_W', 0x5A, 2),          # the temporaries: the patch header's width,
    ('S2_H', 0x5C, 2),          #   height,
    ('S2_LOFS', 0x5E, 2),       #   left offset,
    ('S2_TOFS', 0x60, 2),       #   top offset
    ('S2_COL', 0x62, 2),        # the column
    ('S2_COLP', 0x64, 2),       # the column's post in W; s2_pub: band row
    ('S2_DEST', 0x66, 2),       # the byte written; s2_pub: the screen row
    ('S2_O', 0x68, 2),          # an offset in the source
    ('S2_BLO', 0x6A, 2),        # the source offset at the fetch buffer
    ('S2_CP', 0x6C, 2),         # CAPVAL, CAPMSK's byte
    ('S2_T', 0x6E, 1),
    ('S2_CNT', 0x6F, 1),
    ('S2_MASK', 0x70, 1),       # the nibble a pixel keeps
    ('S2_LEFT', 0x71, 1),       # the column's byte in the row
    ('S2_ROW', 0x72, 1),
    ('S2_RT', 0x73, 1),         # ROWL's or ROWR's low byte
    ('S2_M', 0x74, 2),          # s2_mul160
    ('S2_MB0', 0x76, 1),        # s2_mark: the first byte,
    ('S2_MB1', 0x77, 1),        #   the last
    # s2_pal's and s2_nib's temporaries (part s2pal, request S2PAL-3),
    # never live across a drawer's call (s2_begin keeps S2_BAND..S2_DRY1)
    ('S2P_A', 0x78, 2),
    ('S2P_B', 0x7A, 2),
    ('S2P_C', 0x7C, 1),
    ('S2P_D', 0x7D, 1),
    ('S2P_E', 0x7E, 1),
    ('S2P_F', 0x7F, 1),
]
S2_ZP_ALIASES = {'S2_RY0': 'S2_X', 'S2_RY1': 'S2_X', 'S2_RB0': 'S2_Y',
                 'S2_RB1': 'S2_Y'}

# ---------------------------------------------------------------------------
# The main card (4.4)
# ---------------------------------------------------------------------------

CARD_LO = 0xE000
# what is not ours there [R MEMORY_MAP.md 4.2; tools/sound/README.md
# "MUSIC.SYSTEM"]
S2_CARD = (('the song ring and its mirror', 0xE000, 0xE403),
           ('the player\'s write lists', 0xE480, 0xE500),
           ('the player\'s state', 0xE500, 0xE737),
           ('S2\'s code and tables', 0xE900, 0xF505))
REPLAY_CARD = ('the replay\'s $E000 part', 0xF900, 0xFF00)
PLATFORM_CARD = ('platform: phase switch, crash stub, bridge', 0xFF00,
                 0xFFFA)
VECTORS = ('the vectors', 0xFFFA, 0x10000)

# the VBL count is S2's vbl_count in the IRQ's zero page (part plclock,
# request PLCLOCK-1); CLK_STEP the fraction a VBL (45,743 PAL, 38,229
# NTSC), CLK_STD 0 PAL or $80 NTSC (S2's SONG_NTSC), CLK_TIME3 pl_time's
# bits 24-31
CLOCK_FIELDS = [('CLK_STEP', 2), ('CLK_FRAC', 2), ('CLK_TICS', 4),
                ('CLK_STD', 1), ('CLK_TIME3', 1), ('CLK_SPARE', 6)]
CLOCK = R.allocate(CLOCK_FIELDS, 0xE403, 0xE413)
# the effect voices, 16 bytes each (part fxplay, src/sound/fx.s: V_WPOS
# the main loop's bytes put in the ring and V_RPOS the interrupt's taken
# from it, both mod 256; V_LEVEL the step's attenuation; V_ATT the
# volume's, VATT[volume]; request FXPLAY-1)
VOICE_FIELDS = [('V_FLAGS', 1), ('V_HEAD', 2), ('V_LEFT', 2), ('V_WPOS', 1),
                ('V_RUN', 1), ('V_PER', 2), ('V_LEVEL', 1), ('V_NOISE', 1),
                ('V_RPOS', 1), ('V_CHAN', 1), ('V_ATT', 1), ('V_SOUND', 1),
                ('V_SPARE', 1)]
VOICE_SIZE = 16
VOICE = R.allocate(VOICE_FIELDS, 0, VOICE_SIZE)
VOICES = 3
FXV_BASE = 0xE413
FXV_END = FXV_BASE + VOICES * VOICE_SIZE      # $E443
# FX_SVC: fx_service's temporaries, main loop only (FXS_C, FXS_V, FXS_N,
# FXS_P; request FXPLAY-1)
FX_FIELDS = [('FX_ON', 1), ('FX_HOLD', 1), ('FX_INVAL', 1), ('FX_TEMPO', 2),
             ('FX_SVC', 4)]
FX = R.allocate(FX_FIELDS, 0xE737, 0xE740)
FX_RING, RING_SIZE = 0xE740, 128
FX_RING_END = FX_RING + VOICES * RING_SIZE      # $E8C0
FX_CODE = (0xF505, 0xF900)      # pl_vbl, the clock (244 B, part plclock);
                                #   fx.s's card part (739 B, part fxplay);
                                #   983 of 1,019 B
# the tic-side 2D state (S2T_BASE), 61 bytes: the status bar's, the HUD's,
# the finale's, the mail, the fake mobj FM, the listener's last position
S2T_FIELDS = [
    ('ST_FACEINDEX', 1), ('ST_FACECOUNT', 2), ('ST_PRIORITY', 1),
    ('ST_OLDHEALTH', 2), ('ST_LASTATTACK', 1), ('ST_OLDHEALTHPO', 2),
    ('ST_LASTCALC', 1), ('ST_RANDOM', 1), ('ST_KEYBOXES', 3),
    ('ST_OLDWEAPONS', 9), ('ST_REFRESHED', 1),
    ('HU_ON', 1), ('HU_NEW', 1), ('HU_COUNTER', 2), ('HU_MSGID', 2),
    ('HU_TITLEMAP', 1), ('HU_SPARE', 1),
    ('F_STAGE', 1), ('F_COUNT', 4), ('F_MID', 1),
    ('S2_MAIL', 1),
    ('FM_X', 4), ('FM_Y', 4),
    ('LS_X', 4), ('LS_Y', 4), ('LS_ANGLE', 4),
    # W_READY's value pointer as readyNum sets it at the tic (an ammo
    # index, $FD none: before the first ST_Start, $FE LARGEAMMO, $FF the
    # frame rate) and ST_Start's st_running
    # (part s2stbar, request S2STBAR-1)
    ('ST_READY', 1), ('ST_RUNNING', 1),
]
S2T_SIZE = 61
S2T = R.allocate(S2T_FIELDS, 0, S2T_SIZE)
S2T_USED = sum(n for _, n in S2T_FIELDS)
MAIL_AMSTOP = 0x02              # S2_MAIL bit 1: the automap stopped (R6)
MAIL_AMSTRIP = 0x04             # S2_MAIL bit 2: AMAPW published rows 0-9
                                #   black (hu_drawer's A bit 1; S2AMAP-3)
MAIL_AMTITLE = 0x08             # bit 3: rows 160-167 black (A bit 2)
MAIL_AMVIEW = 0x10              # bit 4: a frame drew the view without the
                                #   overlay since the automap last ran
# the channels (SC_BASE): the table, NUM_CHANNELS x 12 B, then the
# mailboxes, NUM_CHANNELS x 4 B, then SC_EXTRA. A record (part fxchan,
# request FXCHAN-1): the sound, the origin's kind with the pickup flag in
# bit 7, its handle, its last x and y (fixed point, 4 B each: 3 B cannot
# hold the low byte that moves units' borrow)
CHAN_FIELDS = [('CH_SFX', 1), ('CH_KIND', 1), ('CH_HANDLE', 2),
               ('CH_X', 4), ('CH_Y', 4)]
CHF_PICKUP, CHF_KIND = 0x80, 0x03      # in CH_KIND: the pickup flag, the kind
CHAN_SIZE = 12
CHAN = R.allocate(CHAN_FIELDS, 0, CHAN_SIZE)
# after the mailboxes (part fxchan, request FXCHAN-2, placed here in wave
# 4: the tic-side block's two spare bytes went to S2STBAR-1): whether the
# listener exists (bit 7, for fx_pcache) and upstream's snd_SfxVolume
# (0-15; the defaults, a loaded game and the menu's sound page write it)
SC_EXTRA_FIELDS = [('LS_ON', 1), ('SND_SFXVOL', 1)]
SC_EXTRA_SIZE = sum(n for _, n in SC_EXTRA_FIELDS)
SC_EXTRA = R.allocate(SC_EXTRA_FIELDS, 0, SC_EXTRA_SIZE)
MAIL_FIELDS = [('MX_FLAGS', 1), ('MX_SOUND', 1), ('MX_VOL', 1), ('MX_SEP', 1)]
MAIL_SIZE = 4
MAIL = R.allocate(MAIL_FIELDS, 0, MAIL_SIZE)
MX_STOP, MX_START, MX_VOLUME = 0x01, 0x02, 0x04
# the origin kinds of a channel
ORIGIN = {'NONE': 0, 'MOBJ': 1, 'PLAYER': 2, 'FM': 3}


class CardBuild(NamedTuple):
    name: str
    s2t_base: Optional[int]     # None: the build has no tic-side block
    sc_base: int
    channels: int
    room: Tuple[int, int]       # where the two blocks must lie
    why: str


BUILDS = {
    'release': CardBuild('release', 0xE443, 0xE8C0, 3, (0xE443, 0xE900),
                         'the game (4.4)'),
    # this half's tests: the test driver s2_drv at $F900-$FEFF in place of
    # the replay's part; the blocks where the release has them
    'test': CardBuild('test', 0xE443, 0xE8C0, 3, (0xE443, 0xE900),
                      'this half\'s test images (s2_drv)'),
    # milestone 10's M11 test build: gdriver.s at $E000-$EDFF (request R4)
    'm11': CardBuild('m11', 0xEE00, 0xEE40, 3, (0xEE00, 0xEE80),
                     'milestone 10\'s M11 test build (request R4)'),
    # the channel logic's comparison build: 8 channels, in the song ring's
    # place (no music in that image)
    'fxch8': CardBuild('fxch8', 0xE443, 0xE000, 8, (0xE000, 0xE100),
                       'fxchan\'s FXCH8 (8 channels, no music)'),
}


def sc_size(channels: int) -> int:
    """The channel block's bytes: the table, the mailboxes, SC_EXTRA."""
    return channels * (CHAN_SIZE + MAIL_SIZE) + SC_EXTRA_SIZE


def sc_extra_base(sc_base: int, channels: int) -> int:
    """Where SC_EXTRA starts in a channel block."""
    return sc_base + channels * (CHAN_SIZE + MAIL_SIZE)


def card_blocks(build: str) -> List[Tuple[str, int, int]]:
    """Our card blocks in a build: (name, lo, hi)."""
    b = BUILDS[build]
    out = [('the clock', 0xE403, 0xE413),
           ('the effect voices', FXV_BASE, FXV_END),
           ('the effects\' flags', 0xE737, 0xE740),
           ('the effect rings', FX_RING, FX_RING_END)]
    if b.s2t_base is not None:
        out.append(('the tic-side 2D state', b.s2t_base,
                    b.s2t_base + S2T_SIZE))
    out.append(('the channels and mailboxes', b.sc_base,
                b.sc_base + max(64, sc_size(b.channels))
                if build in ('release', 'test', 'm11')
                else b.sc_base + sc_size(b.channels)))
    if build == 'fxch8':        # the ring's place: no music in that image
        out = [o for o in out if o[0] != 'the effect rings']
    return out


# ---------------------------------------------------------------------------
# The test driver (s2_drv.s) in the card
# ---------------------------------------------------------------------------

DRV = (0xF900, 0xFF00)          # the replay's place (no 2D test has one)
DRV_CODE_BUDGET = 600
DRV_STACK = 0xEF                # S at the start (page 1 $01EF down)
DRV_CALLS = 32                  # the call list's entries
CALL_SIZE = 5                   # the routine (2), A, X, Y
DRV_LOADS = 4                   # far_pload loads: bank, the runs' offset
CALL_BUDGET_CYCLES = 400_000_000

# ---------------------------------------------------------------------------
# Cost phases (4.8): a2vm counts PHASE's value / 2 (cost.c phase_to)
# ---------------------------------------------------------------------------

PHASE_2D = 30                   # the 2D frame side: P2DW, the mode images
PHASE_PLATFORM = 31             # input poll, effect service, boot
PHASE_DRIVER = 0                # the test driver, the image's load
PHASES = {PHASE_DRIVER: 'the driver and the image\'s load',
          PHASE_2D: 'the 2D frame side', PHASE_PLATFORM: 'the platform'}
COST_PHASES = 32                # a2vm (larger values count in 31)
# the sources whose code is the platform's: only they may mark phase 31
PLATFORM_CONSTANTS = ('s2layout.PHASE_PLATFORM', 's2layout.PHASES[31]')
PLATFORM_SOURCES = (re.compile(r'^src/native/(pl|fx)_[\w-]+\.s$'),
                    re.compile(r'^src/sound/fx[\w-]*\.s$'))

# ---------------------------------------------------------------------------
# The screen (aux 0): regions (6.3)
# ---------------------------------------------------------------------------

SHR, ROW_BYTES, ROWS = 0x2000, 160, 200
SCB = 0x9D00
RESERVED = (0x9DC8, 0x9E00)     # MEMORY_MAP.md rule 10: stays zero
PALETTES = 0x9E00
SCREEN_END = 0xA000
VIEWHEIGHT = R.VIEWHEIGHT       # 168
STRIP_ROWS = 10                 # the message strip, rows 0-9
TITLE_Y, FONT_HEIGHT = VIEWHEIGHT - 1 - 7, 7   # HU_TITLEY [R hu_stuff65.s:22]


class Region(NamedTuple):
    """Rows and byte ranges of the screen, SCBs, palettes (all inclusive
    bounds)."""
    name: str
    owner: str
    rows: Tuple[Tuple[int, int, int, int], ...]  # (row0, row1, byte0, byte1)
    scbs: Optional[Tuple[int, int]] = None      # (row0, row1)
    palettes: Tuple[int, ...] = ()

    def offsets(self) -> List[int]:
        out = set()
        for r0, r1, b0, b1 in self.rows:
            for r in range(r0, r1 + 1):
                base = SHR + ROW_BYTES * r
                out.update(range(base + b0, base + b1 + 1))
        if self.scbs is not None:
            out.update(range(SCB + self.scbs[0], SCB + self.scbs[1] + 1))
        for p in self.palettes:
            out.update(range(PALETTES + 32 * p, PALETTES + 32 * p + 32))
        return sorted(out)

    def bounds_ok(self) -> bool:
        return all(0 <= r0 <= r1 < ROWS and 0 <= b0 <= b1 < ROW_BYTES
                   for r0, r1, b0, b1 in self.rows) and \
            (self.scbs is None or 0 <= self.scbs[0] <= self.scbs[1] < ROWS) \
            and all(0 <= p < 16 for p in self.palettes)


def rows(name: str, owner: str, r0: int, r1: int) -> Region:
    return Region(name, owner, ((r0, r1, 0, ROW_BYTES - 1),))


REGIONS = {
    # the renderer's (exclusion X1): milestones 8 and 10 compare them
    'view': rows('view', 'renderer (X1)', STRIP_ROWS, VIEWHEIGHT - 1),
    'view-full': rows('view-full', 'renderer (X1)', 0, VIEWHEIGHT - 1),
    'strip': rows('strip', 's2hud', 0, STRIP_ROWS - 1),
    # 8 rows: STCFN036, STCFN064, STCFN081 are 8 high, so a title at 160
    # can draw row 167 (part s2hud, request S2HUD-5)
    'title': rows('title', 's2hud', TITLE_Y, TITLE_Y + FONT_HEIGHT),
    'stbar': rows('stbar', 's2stbar', VIEWHEIGHT, ROWS - 1),
    'colors': Region('colors', 's2pal', (), (0, ROWS - 1), tuple(range(16))),
    'amap': rows('amap', 's2amap', 0, VIEWHEIGHT - 1),
    'menu': rows('menu', 's2menu1, s2menu2', 0, ROWS - 1),
    'wi': rows('wi', 's2wi', 0, ROWS - 1),
    'fin': rows('fin', 's2fin', 0, ROWS - 1),
}
# the regions each kind of frame shows: pairwise disjoint but for the named
# overlays (one region drawn over another in that frame, as upstream)
FRAME_KINDS = {
    'level, strip on': (('view', 'strip', 'stbar', 'colors'), ()),
    'level, strip off': (('view-full', 'stbar', 'colors'), ()),
    'level, overlay': (('view-full', 'stbar', 'colors', 'title'),
                       (('title', 'view-full',
                         'the map\'s title over the view (HU_Drawer)'),)),
    'automap': (('amap', 'strip', 'stbar', 'colors', 'title'),
                (('strip', 'amap', 'the message over the map'),
                 ('title', 'amap', 'the map\'s title over the map'))),
    'menu': (('menu', 'colors'), ()),
    'intermission': (('wi', 'colors'), ()),
    'finale': (('fin', 'colors'), ()),
}

# ---------------------------------------------------------------------------
# The field map (6.2): each upstream field a screen reads (1.6) and its
# native place. Kinds: 'game' (milestones 9-10's places, read only: a name
# of llayout.G, of rlayout's frame block or render inputs, or 'player.F'
# through llayout.player_layout, or 'GTAB'), 'card' (S2T_*), 'state' (an
# image's state block in W, allocated below), 'bank' (S2STATE).
# Encodings: word, byte, sxbyte (a signed byte), flag (0 or 256 as 0 or 1,
# a byte), long, bytes, dropped, gfx (upstream's lump numbers, words, each
# as its 2D store handle, a byte, $FFFF as $FF: s2data.handles_of; request
# S2DATA-4), readysrc (W_READY's value pointer as ST_READY: an ammo
# index k for &ammo[k] (k < $FD), $FD NULL, $FE &largeammo, $FF
# &_g_fps_framerate; request
# S2STBAR-1), msgid (an hu_textline's text as its message id in s2msgs's
# table, $FFFF the empty line; request S2HUD-6).
# ---------------------------------------------------------------------------


class Field(NamedTuple):
    screen: str
    ref: str                    # unit:label[+offset] of upstream
    size: int                   # upstream's bytes
    enc: str
    kind: str
    place: str                  # the native name
    native: int                 # its native bytes


def _f(screen, ref, size, enc, kind, place, native=None):
    if native is None:
        native = {'word': 2, 'byte': 1, 'sxbyte': 1, 'flag': 1, 'long': 4,
                  'dropped': 0, 'gfx': size // 2}.get(enc, size)
    return Field(screen, ref, size, enc, kind, place, native)


PLAYER_FIELDS = ('health', 'armorpoints', 'ammo', 'maxammo', 'readyweapon',
                 'weaponowned', 'cards', 'powers', 'cheats', 'damagecount',
                 'bonuscount', 'attackdown', 'mo', 'attacker')
NW_OLDNUM, NW_SIZE = 6, 12      # st_stuff65.s's widgets [R :43-56]
IW_OLDINUM, IW_SIZE = 4, 10


def _stbar() -> List[Field]:
    s, st = 'stbar', 'st_stuff65.s:'
    out = [_f(s, 'g_game65.s:_g_player.' + n, 0, 'player', 'game',
              'player.' + n, 0) for n in PLAYER_FIELDS]
    out += [_f(s, 'weaponinfo.ammo', 0, 'table', 'game', 'GTAB', 0),
            _f(s, 'm_menu65.s:_g_menuactive', 2, 'word', 'game',
               'G_MENUACTIVE'),
            _f(s, 'd_main65.s:_g_fps_show', 2, 'byte', 'state', 'P_FPS')]
    widgets = [('W_READY', NW_OLDNUM, 1, NW_SIZE, 'P_OLDREADY'),
               ('W_HEALTH', NW_OLDNUM, 1, NW_SIZE, 'P_OLDHEALTH'),
               ('W_ARMOR', NW_OLDNUM, 1, NW_SIZE, 'P_OLDARMOR'),
               ('W_AMMO', NW_OLDNUM, 4, NW_SIZE, 'P_OLDAMMO'),
               ('W_MAXAMMO', NW_OLDNUM, 4, NW_SIZE, 'P_OLDMAXAMMO'),
               ('W_ARMS', IW_OLDINUM, 6, IW_SIZE, 'P_OLDARMS'),
               ('W_FACES', IW_OLDINUM, 1, IW_SIZE, 'P_OLDFACE'),
               ('W_KEYBOXES', IW_OLDINUM, 3, IW_SIZE, 'P_OLDKEYS')]
    for label, off, n, stride, place in widgets:
        for k in range(n):
            out.append(_f(s, '%s%s+%d' % (st, label, k * stride + off), 2,
                          'word', 'state', '%s+%d' % (place, 2 * k)))
    out += [_f(s, st + 'st_palette', 2, 'sxbyte', 'state', 'P_STPALETTE'),
            _f(s, 'i_viigs65.s:STCACHE', 5120, 'bytes', 'bank',
               'SS_STCACHE')]
    # stHide's VW_MHID and the frame rate the fps cheat shows (part
    # s2stbar, request S2STBAR-3; the frame rate is the second half's)
    out += [_f(s, 'VW_MHID', 2, 'byte', 'state', 'P_MHID'),
            _f(s, 'd_main65.s:_g_fps_framerate', 2, 'word', 'state',
               'P_FPSRATE')]
    card = [('st_faceindex', 'byte', 'ST_FACEINDEX'),
            ('st_facecount', 'word', 'ST_FACECOUNT'),
            ('st_priority', 'byte', 'ST_PRIORITY'),
            ('st_oldhealth', 'word', 'ST_OLDHEALTH'),
            ('st_lastattackdown', 'sxbyte', 'ST_LASTATTACK'),
            ('st_oldhealthPO', 'word', 'ST_OLDHEALTHPO'),
            ('st_lastcalc', 'byte', 'ST_LASTCALC'),
            ('st_randomnumber', 'byte', 'ST_RANDOM'),
            ('st_refreshed', 'byte', 'ST_REFRESHED'),
            ('st_running', 'byte', 'ST_RUNNING')]
    out += [_f(s, st + n, 2, e, 'card', p) for n, e, p in card]
    out += [_f(s, '%skeyboxes+%d' % (st, 2 * k), 2, 'sxbyte', 'card',
               'ST_KEYBOXES+%d' % k) for k in range(3)]
    out += [_f(s, '%soldweaponsowned+%d' % (st, 2 * k), 2, 'byte', 'card',
               'ST_OLDWEAPONS+%d' % k) for k in range(9)]
    # the widgets' value pointers: the native widget names its field, but
    # the ready number's, which readyNum sets at the tic (an ammo index,
    # $FE LARGEAMMO, $FF the frame rate: encoding readysrc; S2STBAR-1)
    out.append(_f(s, st + 'W_READY+8', 2, 'readysrc', 'card', 'ST_READY'))
    out += [_f(s, '%s%s+%d' % (st, w, 8), 2, 'dropped', 'state', '-')
            for w in ('W_HEALTH', 'W_ARMOR')]
    return out


def _hud() -> List[Field]:
    s, hu = 'hud', 'hu_stuff65.s:'
    return [
        _f(s, 'm_menu65.s:showMessages', 2, 'word', 'game', 'G_SHOWMSG'),
        _f(s, hu + '_g_message_dontfuckwithme', 2, 'word', 'game',
           'G_MSGKEEP'),
        _f(s, 'g_game65.s:_g_gamemap', 2, 'word', 'game', 'G_GAMEMAP'),
        _f(s, 'frame.AUTOMAP', 1, 'byte', 'game', 'AUTOMAP'),
        _f(s, hu + 'w_title', 39, 'bytes', 'state', 'P_TITLE'),
        _f(s, hu + 'w_message', 39, 'bytes', 'state', 'P_MESSAGE'),
        _f(s, 'i_viigs65.s:textValid', 4, 'bytes', 'state', 'P_TXTVALID'),
        _f(s, 'i_viigs65.s:textLen', 4, 'bytes', 'state', 'P_TXTLEN'),
        _f(s, 'i_viigs65.s:textY', 4, 'bytes', 'state', 'P_TXTY'),
        # the cache's key, compared every frame a line is up (S2HUD-1)
        _f(s, 'i_viigs65.s:textText', 80, 'bytes', 'state', 'P_TXTTEXT'),
        _f(s, 'i_viigs65.s:iigs_textShown', 4, 'bytes', 'state',
           'P_TXTSHOWN'),
        _f(s, hu + 'message_on', 2, 'byte', 'card', 'HU_ON'),
        _f(s, hu + 'message_new', 2, 'byte', 'card', 'HU_NEW'),
        _f(s, hu + 'message_counter', 2, 'word', 'card', 'HU_COUNTER'),
        # the line's message id (the text of w_message: s2msgs's table,
        # $FFFF an empty line; S2HUD-6); player.message is the player's
        # field, milestone 10's reference (tag, symbol index)
        _f(s, hu + 'w_message', 39, 'msgid', 'card', 'HU_MSGID', 2),
        _f(s, 'g_game65.s:_g_player.message', 0, 'player', 'game',
           'player.message', 0),
        _f(s, 'g_game65.s:_g_gamemap(title)', 2, 'byte', 'card',
           'HU_TITLEMAP'),
    ]


def _palettes() -> List[Field]:
    s, v = 'palettes', 'i_viigs65.s:'
    out = [_f(s, 'GSVIEWn', LL.GSVIEW_SIZE, 'bytes', 'game', 'LVC_GSVIEW'),
           _f(s, 'm_menu65.s:_g_gamma', 2, 'word', 'game', 'GAMMA'),
           _f(s, v + 'TINTPAL', 5376, 'bytes', 'bank', 'S2PAL:TINTPAL')]
    st = [('scb', 200, 'bytes', 'PS_SCB'), ('palette', 512, 'bytes',
                                              'PS_PALETTE'),
          ('newpal', 2, 'byte', 'PS_NEWPAL'), ('curtint', 2, 'byte',
                                                 'PS_CURTINT'),
          ('levelcopy', 2, 'byte', 'PS_LEVELCOPY'),
          # upstream's palettecount is 0 or 256 only [R i_viigs65.s:404,
          # :1274-1275, :2124, :2187]: natively a flag (request S2PAL-5)
          ('palettecount', 2, 'flag', 'PS_PALCOUNT'),
          ('scbchanged', 2, 'byte', 'PS_SCBCHANGED'),
          ('picturenum', 2, 'word', 'PS_PICTURE'),
          ('viewpal', 2, 'byte', 'PS_VIEWPAL'),
          ('strippal', 2, 'byte', 'PS_STRIPPAL')]
    out += [_f(s, v + n, z, e, 'palst', p) for n, z, e, p in st]
    return out


def _menus() -> List[Field]:
    s, m, d = 'menus', 'm_menu65.s:', 'd_main65.s:'
    out = [_f(s, 'g_game65.s:_g_usergame', 2, 'word', 'game', 'G_USERGAME'),
           _f(s, 'g_game65.s:_g_demoplayback', 2, 'word', 'game',
              'G_DEMOPLAY'),
           _f(s, 'g_game65.s:_g_gamestate', 2, 'word', 'game',
              'G_GAMESTATE'),
           _f(s, m + '_g_menuactive', 2, 'word', 'game', 'G_MENUACTIVE'),
           _f(s, m + '_g_gamma', 2, 'word', 'game', 'GAMMA'),
           _f(s, m + 'showMessages', 2, 'word', 'game', 'G_SHOWMSG'),
           _f(s, m + '_g_alwaysRun', 2, 'byte', 'bank', 'SS_SETTINGS+0'),
           _f(s, m + 'detailLevel', 2, 'byte', 'bank', 'SS_SETTINGS+1'),
           _f(s, m + 'iigs_mouseon', 2, 'byte', 'bank', 'SS_SETTINGS+2'),
           _f(s, m + 'iigs_mousespeed', 2, 'byte', 'bank', 'SS_SETTINGS+3'),
           _f(s, m + 'iigs_mousemove', 2, 'byte', 'bank', 'SS_SETTINGS+4'),
           # the release's MUSIC_MENU is 1: the display page's music row
           # (part s2menu2, request S2MENU2-2; drawn and saved, it changes
           # no AY write)
           _f(s, 's_sound65.s:snd_MusicVolume', 2, 'byte', 'bank',
              'SS_SETTINGS+5')]
    st = [('currentMenu', 'byte', 'M_CURRENT'), ('itemOn', 'byte',
                                                  'M_ITEMON'),
          ('skullAnimCounter', 'byte', 'M_SKULLCOUNT'),
          ('whichSkull', 'byte', 'M_WHICHSKULL'),
          ('messageToPrint', 'byte', 'M_MSGPRINT'),
          ('messageKind', 'byte', 'M_MSGKIND'),
          ('messageLastMenuActive', 'byte', 'M_MSGLAST'),
          ('menuversion', 'word', 'M_MENUVER'),
          ('skullversion', 'word', 'M_SKULLVER')]
    out += [_f(s, m + n, 2, e, 'state', p) for n, e, p in st]
    out.append(_f(s, m + '_g_savegamestrings', 64, 'bytes', 'state',
                  'M_SAVESTR'))
    dd = [('screenmenuversion', 'word', 'M_SCRMENUVER'),
          ('screenskullversion', 'word', 'M_SCRSKULLVER'),
          ('skullshown', 'byte', 'M_SKSHOWN'), ('skx', 'word', 'M_SKX'),
          ('sky', 'byte', 'M_SKY'), ('skw', 'byte', 'M_SKW'),
          ('skh', 'byte', 'M_SKH'), ('viewsaved', 'byte', 'M_VIEWSAVED'),
          ('DD_PAUSED', 'byte', 'M_PAUSED')]
    out += [_f(s, d + n, 2, e, 'state', p) for n, e, p in dd]
    return out


def _automap() -> List[Field]:
    s, a = 'automap', 'am_map65.s:'
    out = [_f(s, 'LVG0 lines', 0, 'table', 'game', 'LVG0'),
           _f(s, 'LNMAP', 0, 'table', 'game', 'LNMAP'),
           _f(s, 'g_game65.s:_g_player.mo', 0, 'player', 'game',
              'player.mo', 0),
           _f(s, 'g_game65.s:_g_player.cheats', 0, 'player', 'game',
              'player.cheats', 0),
           _f(s, 'g_game65.s:_g_gamemap', 2, 'word', 'game', 'G_GAMEMAP')]
    st = [('m_x', 4), ('m_y', 4), ('m_w', 4), ('m_h', 4), ('m_x2', 4),
          ('m_y2', 4), ('min_x', 4), ('min_y', 4), ('max_x', 4),
          ('max_y', 4), ('max_w', 4), ('max_h', 4), ('min_scale_mtof', 4),
          ('max_scale_mtof', 4), ('scale_mtof', 4), ('scale_ftom', 4),
          ('mtof_zoommul', 4), ('ftom_zoommul', 4), ('m_paninc', 8),
          ('f_oldloc', 8), ('stopped', 2), ('lastlevel', 2),
          ('automapmode', 2), ('am_valid', 2), ('am_band', 2)]
    for n, z in st:
        enc = 'long' if z == 4 else ('bytes' if z == 8 else 'word')
        out.append(_f(s, a + n, z, enc, 'state',
                      'A_' + n.upper().replace('_', '')))
    out.append(_f(s, a + 'AM_LISTS', 12000, 'bytes', 'bank', 'SS_AMOLD',
                  2 * 2048))
    return out


def _intermission() -> List[Field]:
    s, w = 'intermission', 'wi_stuff65.s:'
    g = [('_g_acceleratestage', 'WI_ACCEL'), ('state', 'WI_STATE'),
         ('cnt', 'WI_CNT'), ('bcnt', 'WI_BCNT'), ('cnt_time', 'WI_CNTTIME'),
         ('cnt_total_time', 'WI_CNTTOTAL'), ('cnt_par', 'WI_CNTPAR'),
         ('cnt_pause', 'WI_CNTPAUSE'), ('sp_state', 'WI_SPSTATE'),
         ('cnt_kills', 'WI_CNTKILLS'), ('cnt_items', 'WI_CNTITEMS'),
         ('cnt_secret', 'WI_CNTSECRET'), ('snl_pointeron', 'WI_SNLPTR')]
    out = [_f(s, w + n, 0, 'game', 'game', p, 0) for n, p in g]
    out.append(_f(s, 'g_game65.s:_g_wminfo', 40, 'bytes', 'game',
                  'G_WMINFO'))
    out.append(_f(s, w + 'lumps', 66, 'gfx', 'state', 'W_LUMPS'))
    return out


def _finale() -> List[Field]:
    s, f = 'finale', 'f_finale65.s:'
    return [_f(s, 'g_game65.s:_g_gameaction', 2, 'word', 'game',
               'G_GAMEACTION'),
            _f(s, 'wi_stuff65.s:_g_acceleratestage', 0, 'game', 'game',
               'WI_ACCEL', 0),
            _f(s, f + 'finalestage', 2, 'byte', 'card', 'F_STAGE'),
            _f(s, f + 'finalecount', 4, 'long', 'card', 'F_COUNT'),
            _f(s, f + 'midstage', 2, 'byte', 'card', 'F_MID'),
            _f(s, f + 'help2num', 2, 'gfx', 'state', 'F_HELP2'),
            _f(s, f + 'backgroundnum', 2, 'gfx', 'state', 'F_BACKGROUND')]


def field_map() -> List[Field]:
    return _stbar() + _hud() + _palettes() + _menus() + _automap() + \
        _intermission() + _finale()


# the state fields' places: each image's own part of its state block
# (P2DW, WIW, FINW: PALST at the block's start, then their own 256 bytes;
# MENUW: its own 256; AMAPW: its own 1 KB) and PALST
SCREEN_IMAGE = {'stbar': 'P2DW', 'hud': 'P2DW', 'menus': 'MENUW',
                'automap': 'AMAPW', 'intermission': 'WIW', 'finale': 'FINW'}
OWN_STATE = {'P2DW': ('SS_P2DW', 0xBF00), 'MENUW': ('SS_MENUW', 0xBF00),
             'AMAPW': ('SS_AMAPW', 0xAC00), 'WIW': ('SS_WIW', 0xBF00),
             'FINW': ('SS_FINW', 0xBF00)}
PALST_W = 0xBC00                # where P2DW, WIW, FINW keep PALST in W
PALST_IMAGES = ('P2DW', 'WIW', 'FINW')


def _place_list(kind: str, image: Optional[str] = None
                ) -> List[Tuple[str, int]]:
    """The (name, bytes) of the places of one block, in the field map's
    order, each name once (an indexed place, NAME+k, grows NAME)."""
    sizes: Dict[str, int] = {}
    order: List[str] = []
    for f in field_map():
        if f.kind != kind or f.place == '-' or (
                kind == 'state' and SCREEN_IMAGE[f.screen] != image):
            continue
        name, _, k = f.place.partition('+')
        top = (int(k) if k else 0) + f.native
        if name not in sizes:
            order.append(name)
        sizes[name] = max(sizes.get(name, 0), top)
    return [(n, sizes[n]) for n in order]


def state_places(image: str) -> Dict[str, int]:
    """Each state field of an image at its W address (its own part)."""
    block, w = OWN_STATE[image]
    return R.allocate(_place_list('state', image) +
                      OWN_NATIVE.get(image, []), w, w + SS_SIZE[block])


# PALST's native fields after upstream's (no upstream counterpart, so not
# in the field map): PS_BEGUN, s2_begin has run in this frame (s2_publish
# sets it, s2_finish clears it; part s2draw, request S2DRAW-5);
# PS_TXTINV: the HUD's text cache is invalid (upstream's textInvalidate:
# s2_setrows, s2_nibtab and s2_picpal set it; s2hud clears both slots'
# textValid and iigs_textShown, then it; part s2pal, request S2PAL-2)
PALST_NATIVE = [('PS_BEGUN', 1), ('PS_TXTINV', 1)]


# P2DW's own fields with no upstream counterpart (part s2hud, request
# S2HUD-1): the message id P_MESSAGE's text was fetched for, the map
# P_TITLE's was; allocated after the field map's
P2DW_NATIVE = [('P_MSGFILL', 2), ('P_MAPFILL', 1)]
# MENUW's own fields with no upstream counterpart (part s2menu1, request
# S2MENU1-1): UI_PALON, UI_PICTURE, UI_VIEWPAL, UI_STRIPPAL, UI_GAMMA,
# menuNum's main row, bindRow, G_SettingsChanged's answer (the second
# half's), the request to the second half and its argument, PALW due
# after the close, UI_FONTBUF. The input layer's bind state (upstream's
# iigs_bindwait, iigs_bindcode) is the input block's PL_BIND, which the
# shared pl_poll writes (wave 5's integration: S2MENU1-4 with PLINPUT-3)
MENUW_NATIVE = [('M_PALON', 1), ('M_PICTURE', 2), ('M_VIEWPAL', 1),
                ('M_STRIPPAL', 1), ('M_UIGAMMA', 1), ('M_MAINN', 1),
                ('M_BINDROW', 1), ('M_SETCHG', 1), ('M_REQ', 1),
                ('M_REQARG', 1), ('M_RELOAD', 1), ('M_FONTBUF', 16),
                # the benchmark's FPS text, 0-terminated, at most 7
                # characters (bmDone's second line of VW_BTXT, x.xxx; the
                # second half writes it; part s2menu2, request S2MENU2-1)
                ('M_BFPS', 8)]
# AMAPW's own fields with no upstream counterpart (part s2amap, request
# S2AMAP-1): AM_MODE, AM_OLDTOP (bytes), the old byte list's entries
# (AM_ON as entries) and its four bands' first entries
AMAPW_NATIVE = [('A_MODE', 1), ('A_OLDTOP', 1), ('A_ON', 2), ('A_OB', 8)]
# FINW's own fields with no upstream counterpart (part s2fin, request
# S2FIN-1): the busy sign is on (upstream's VW_SGON)
FINW_NATIVE = [('F_SIGNON', 1)]
OWN_NATIVE = {'P2DW': P2DW_NATIVE, 'MENUW': MENUW_NATIVE,
              'AMAPW': AMAPW_NATIVE, 'FINW': FINW_NATIVE}
# the menu's requests to the second half in M_REQ (S2MENU1-1)
MENU_REQUESTS = (('REQ_NONE', 0), ('REQ_NEWGAME', 1), ('REQ_QUIT', 2),
                 ('REQ_ENDGAME', 3), ('REQ_LOAD', 4), ('REQ_SAVE', 5),
                 ('REQ_BENCH', 6), ('REQ_SAVESET', 7))
# MENUW keeps PALST in W at $A500, just above its room (S2MENU1-2); P2DW,
# WIW and FINW at PALST_W
MENUW_PALST = 0xA500


def palst_places() -> Dict[str, int]:
    """The palette state's fields as offsets from PALST's start."""
    return R.allocate(_place_list('palst') + PALST_NATIVE, 0, PALST_SIZE)


def resolve_game(place: str) -> Optional[Tuple[str, int]]:
    """A 'game' place: ('main', address), ('bank', bank), or None for the
    places resolved elsewhere (the player, GTAB)."""
    if place.startswith('player.') or place == 'GTAB':
        return None
    if place in LL.G:
        return ('main', LL.G[place])
    if place in R.FRAME:        # absolute already [R rlayout.py] (S2HUD-5)
        return ('main', R.FRAME[place])
    if place in R.RINS:
        return ('main', R.RINS[place])
    if place == 'LVC_GSVIEW':
        return ('bank', LL.LVC)
    if place == 'LVG0':
        return ('bank', LL.LVG0)
    if place == 'LNMAP':
        return ('main', R.LNMAP)
    raise ValueError('the field map\'s game place %s is unknown' % place)


# ---------------------------------------------------------------------------
# The packing of the images' stored pages (4.1)
# ---------------------------------------------------------------------------

class PackError(ValueError):
    pass


def page_run(lo: int, end: int) -> Tuple[int, int]:
    """[lo, end) as (first page, page count)."""
    first, last = lo >> 8, (end - 1) >> 8
    return first, last - first + 1


def pack(extents: Dict[str, Tuple[int, int]],
         bank_list: Sequence[int] = CODE_BANKS) -> Dict[str, int]:
    """Each image's stored run [lo, end) into the first bank of bank_list
    whose runs it does not meet (MATHW's pages, $60-$65, once a bank);
    images in IMAGES' order. Raises PackError naming the image that has no
    bank."""
    placed: Dict[int, List[Tuple[int, int, str]]] = {b: [] for b in
                                                     bank_list}
    mathw = page_run(MATHW_LO, MATHW_END)
    out = {}
    for name in [im.name for im in IMAGES if im.name in extents]:
        lo, end = extents[name]
        first, count = page_run(lo, end)
        if first < mathw[0] + mathw[1]:
            raise PackError('%s\'s pages from $%02X meet MATHW\'s' % (
                name, first))
        for b in bank_list:
            if all(first + count <= f or f + c <= first
                   for f, c, _ in placed[b]):
                placed[b].append((first, count, name))
                out[name] = b
                break
        else:
            raise PackError(
                '%s ($%04X-$%04X) has no bank: %s' % (
                    name, lo, end - 1, '; '.join(
                        'bank %d holds %s' % (b, ', '.join(
                            '%s $%02X00-$%02XFF' % (n, f, f + c - 1)
                            for f, c, n in placed[b])) for b in bank_list)))
    return out


def budget_extents() -> Dict[str, Tuple[int, int]]:
    """Each packed image's stored bytes by its budget (before it is
    built): from its room's start, the size table's total."""
    return {im.name: (im.stored[0], im.stored[0] + budget_total(im))
            for im in IMAGES if im.packed}


def image_banks() -> Dict[str, int]:
    out = pack(budget_extents())
    out['OVLW'] = OVLW_BANK
    return out


# ---------------------------------------------------------------------------
# The phase constants (4.8)
# ---------------------------------------------------------------------------

PHASE_NAME = re.compile(r'^(PHASE_\w+|\w+_PHASE)$')


def layout_phases(modules: Sequence[Any]) -> List[Tuple[str, int]]:
    """The named phase constants of the layouts (PHASE_* or *_PHASE, ints;
    rlayout's PHASE is the byte's address and is not one; dicts named
    PHASES or *_PHASES give their keys)."""
    out = []
    for m in modules:
        mod = getattr(m, 'LAYOUT_NAME', m.__name__.rsplit('.', 1)[-1])
        for name in sorted(vars(m)):
            v = getattr(m, name)
            if name == 'PHASE' or isinstance(v, bool):
                continue
            if PHASE_NAME.match(name) and isinstance(v, int):
                out.append(('%s.%s' % (mod, name), v))
            elif re.match(r'^(\w+_)?PHASES$', name) and isinstance(v, dict):
                out += [('%s.%s[%r]' % (mod, name, k), k) for k in v
                        if isinstance(k, int)]
    return out


EXPR = re.compile(r'^[\s\d$%()*+\-/a-fA-F]+$')


def _value(expr: str, n: Optional[str] = None) -> Optional[int]:
    """A ca65 constant expression of numbers ($hex, %bin, decimal) and
    + - * / ( ); n substituted for the macro's parameter."""
    if n is not None:
        expr = re.sub(r'\bn\b', '(%s)' % n, expr)
    # the phase values of s2.inc (PHV_*)
    expr = re.sub(r'\bPHV_(2D|PLATFORM|DRIVER)\b', lambda m: str(
        2 * {'2D': PHASE_2D, 'PLATFORM': PHASE_PLATFORM,
             'DRIVER': PHASE_DRIVER}[m.group(1)]), expr)
    text = expr.strip()
    if not EXPR.match(text) or re.search(r'[a-fA-F]', re.sub(
            r'\$[0-9a-fA-F]+', '', text)):
        return None
    text = re.sub(r'\$([0-9a-fA-F]+)', lambda m: str(int(m.group(1), 16)),
                  text)
    text = re.sub(r'%([01]+)', lambda m: str(int(m.group(1), 2)), text)
    text = text.replace('/', '//')
    try:
        return int(eval(text, {'__builtins__': {}}, {}))  # noqa: S307
    except (SyntaxError, ZeroDivisionError, TypeError, NameError):
        return None


def _strip(line: str) -> str:
    return line.split(';', 1)[0].strip()


def _local(expr: str, local: Dict[str, int]) -> str:
    """expr with the names a file defines replaced by their values."""
    return re.sub(r'\b[A-Za-z_]\w*\b', lambda m: str(local[m.group(0)])
                  if m.group(0) in local else m.group(0), expr)


# Milestone 10's test builds (game.mk's TEST_FLAGS: -D TESTBUILD) hold
# harness entries that time one routine alone in phases of their own
# (gflow.s's fl_timed, fl_tresume: 30, 31 [R docs/game-parts/flow.md
# "Checkpoint"]); only milestone 10's routine-mode drivers call them, in
# runs that time that routine and nothing of this half. Their stores are
# the harness's (source_phases(harness=True)): checked in 0-31 and
# readable, not against 4.8's owners, which are the game's (wave 4 as
# integrated, SCREENS.md 8.8).
HARNESS_SYMBOL = 'TESTBUILD'
_COND_OPEN = re.compile(r'^\.if(\w*)\b\s*(.*)$', re.I)


def _harness_branch(kind: str, arg: str) -> Optional[bool]:
    """Whether a conditional's first branch is the test builds' only
    (True), never theirs (False), or not decided by HARNESS_SYMBOL
    (None)."""
    kind, arg = kind.lower(), arg.strip()
    named = re.fullmatch(r'\(?\s*%s\s*\)?' % HARNESS_SYMBOL, arg)
    if kind == 'def' and named:
        return True
    if kind == 'ndef' and named:
        return False
    if kind == '' and re.fullmatch(
            r'\.(def|defined)\s*\(\s*%s\s*\)' % HARNESS_SYMBOL, arg, re.I):
        return True
    if kind == '' and re.fullmatch(
            r'\.not\s*\.(def|defined)\s*\(\s*%s\s*\)|!\s*\.(def|defined)'
            r'\s*\(\s*%s\s*\)' % (HARNESS_SYMBOL, HARNESS_SYMBOL), arg,
            re.I):
        return False
    return None


def source_phases(root: Path = ROOT, harness: bool = False
                  ) -> Tuple[List[Tuple[str, int]], List[str]]:
    """The cost phases the 65C02 sources write to PHASE: (file:line,
    phase) and the stores whose value cannot be read (file:line). Forms:
    `lda #E` then `sta PHASE` (or `jsr mark`, rwall.s's: its `mark:`
    stores the caller's A), with only directives and `pha` between them;
    `stz PHASE`; a macro whose body stores `lda #E(n)` to PHASE, invoked
    with a constant. E may name a constant the same file defines (`NAME =
    expression`, read in the file's order). The phase is the value / 2
    (a2vm's cost.c: a phase over 31 counts in 31). harness False: the
    stores outside milestone 10's test-build branches (`.ifdef TESTBUILD`
    and its forms); True: only those inside them (HARNESS_SYMBOL)."""
    found, unread = [], []
    for path in sorted((root / 'src').rglob('*.s')):
        rel = path.relative_to(root).as_posix()
        lines = [_strip(x) for x in
                 path.read_text(errors='replace').splitlines()]
        code = []               # (line number, instruction text, label)
        in_harness: set = set()     # the line numbers in test-build branches
        conds: List[List[Optional[bool]]] = []  # [first branch, current]
        macros: Dict[str, str] = {}
        local: Dict[str, int] = {}  # the file's own NAME = constant
        cur, body_lda, depth = None, None, 0
        for i, t in enumerate(lines, 1):
            m = _COND_OPEN.match(t)
            if m:
                first = _harness_branch(m.group(1), m.group(2))
                conds.append([first, first])
                continue
            if re.match(r'^\.else\b', t, re.I) and conds:
                f = conds[-1][0]
                conds[-1][1] = None if f is None else not f
                continue
            if re.match(r'^\.elseif\b', t, re.I) and conds:
                conds[-1][1] = None if conds[-1][0] is None else False
                continue
            if re.match(r'^\.endif\b', t, re.I) and conds:
                conds.pop()
                continue
            if any(c[1] for c in conds):
                in_harness.add(i)
            m = re.match(r'^\.macro\s+(\w+)\s*(\w*)', t, re.I)
            if m:
                cur, body_lda = m.group(1), None
                continue
            if cur is not None:
                if re.match(r'^\.endmacro\b', t, re.I):
                    cur = None
                    continue
                m = re.match(r'^lda\s+#(.+)$', t, re.I)
                if m:
                    body_lda = m.group(1)
                elif re.match(r'^[sS][tT][aA]\s+PHASE$', t) and body_lda:
                    macros[cur] = body_lda
                continue
            m = re.match(r'^(\w+)\s*:?=\s*(.+)$', t)
            if m:
                v = _value(_local(m.group(2), local))
                if v is not None:
                    local[m.group(1)] = v
                continue
            label = ''
            m = re.match(r'^([@\w]*):(?!=)\s*(.*)$', t)
            if m:
                label, t = m.group(1) or ':', m.group(2).strip()
            code.append((i, t, label))
        del depth
        # rwall.s's mark: (its body stores the caller's A to PHASE): only
        # in a file with such a label is `jsr mark` a phase store
        has_mark = any(lb == 'mark' and any(
            re.match(r'^[sS][tT][aA]\s+PHASE$', t2)
            for _, t2, _ in code[n:n + 3]) for n, (_, _, lb) in
            enumerate(code))

        def is_store(text: str) -> bool:
            return bool(re.match(r'^[sS][tT][aA]\s+PHASE$', text) or (
                has_mark and re.match(r'^[jJ][sS][rR]\s+mark$', text)))
        for k, (i, t, label) in enumerate(code):
            where = '%s:%d' % (rel, i)
            if (i in in_harness) != harness:
                continue
            if re.match(r'^[sS][tT][zZ]\s+PHASE$', t):
                found.append((where, 0))
                continue
            if is_store(t):
                value, j = None, k
                while j > 0:
                    j -= 1
                    pi, pt, pl = code[j]
                    if pl and not pt and re.match(r'^mark$', pl):
                        value = 'mark'
                        break
                    if not pt or pt.startswith('.') or \
                            re.match(r'^pha$', pt, re.I):
                        if pl == 'mark':
                            value = 'mark'
                            break
                        continue
                    m = re.match(r'^lda\s+#(.+)$', pt, re.I)
                    value = m.group(1) if m else None
                    break
                if value == 'mark' or (label == 'mark'):
                    continue    # rwall.s's mark: A from its callers
                v = _value(_local(value, local)) if value else None
                if v is None:
                    unread.append(where)
                else:
                    found.append((where, v >> 1))
                continue
            m = re.match(r'^(\w+)\s+(.+)$', t)
            if m and m.group(1) in macros:
                v = _value(macros[m.group(1)], m.group(2))
                if v is None:
                    unread.append(where)
                else:
                    found.append((where, v >> 1))
    return found, unread


def this_module():
    """This module (a copy loaded without sys.modules gets its globals)."""
    m = sys.modules.get(__name__)
    if m is None:
        m = types.ModuleType(__name__)
        m.__dict__.update(globals())
    return m


def is_platform(where: str) -> bool:
    path = where.rsplit(':', 1)[0]
    return path.startswith('s2layout.') or \
        any(p.match(path) for p in PLATFORM_SOURCES)


def phase_problems(layouts: Sequence[Any], root: Path = ROOT) -> List[str]:
    """Every phase constant of the layouts and every phase the sources
    write in 0-31; 31 only from the platform's code (4.8)."""
    out = []
    consts = layout_phases(layouts)
    for name, v in consts:
        if not 0 <= v < COST_PHASES:
            out.append('the phase constant %s is %d, outside 0-31' % (name, v))
        elif v == COST_PHASES - 1 and name not in PLATFORM_CONSTANTS:
            out.append('%s is 31, the platform\'s phase' % name)
    found, unread = source_phases(root)
    for where, v in found:
        if not 0 <= v < COST_PHASES:
            out.append('%s writes the phase %d (counted in 31)' % (where, v))
        elif v == COST_PHASES - 1 and not is_platform(where):
            out.append('%s writes the phase 31, the platform\'s' % where)
    out += ['%s writes PHASE with a value the check cannot read' % w
            for w in unread]
    # milestone 10's test-build harness (HARNESS_SYMBOL): 0-31, readable
    found, unread = source_phases(root, harness=True)
    out += ['%s (a test build\'s harness) writes the phase %d (counted in '
            '31)' % (where, v) for where, v in found
            if not 0 <= v < COST_PHASES]
    out += ['%s (a test build\'s harness) writes PHASE with a value the '
            'check cannot read' % w for w in unread]
    return out


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------

def _overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def check(g=None, root: Path = ROOT) -> None:
    """Raises ValueError on the first problem: a place out of its space or
    over another, a place of rlayout, llayout or glayout taken, a bank used
    twice or not ours, an image's budgets over its room, a packing that
    fails, a phase constant outside 0-31 or 31 not the platform's, a field
    of the map without a place."""
    if g is None:
        g = glayout_module()
    problems = problems_of(g, root)
    if problems:
        raise ValueError(problems[0] if len(problems) == 1 else
                         '%s (and %d more: %s)' % (problems[0],
                                                   len(problems) - 1,
                                                   '; '.join(problems[1:4])))


def problems_of(g=None, root: Path = ROOT) -> List[str]:
    out: List[str] = []
    # ---- W: the images' rooms and runtime ranges
    for im in IMAGES:
        lo, hi = im.stored
        if not (W_LO <= lo < hi <= W_HI):
            out.append('%s\'s room is outside W' % im.name)
        if lo < MATHW_END and im.name != 'OVLW':
            out.append('%s\'s room meets MATHW' % im.name)
        # OVLW's run time places are inside its room (MASKW's code room),
        # above its stored bytes (size_rows); every other image's are
        # outside its room
        inner = im.name == 'OVLW'
        if inner and not all(lo <= a < b <= hi for a, b, _ in im.runtime):
            out.append('OVLW: a run time range outside its room')
        spans = ([] if inner else [(lo, hi, 'room')]) + list(im.runtime)
        for i, a in enumerate(spans):
            if not (W_LO <= a[0] < a[1] <= W_HI):
                out.append('%s: %s outside W' % (im.name, a[2]))
            for b in spans[i + 1:]:
                if _overlap(a[:2], b[:2]):
                    out.append('%s: %s overlaps %s' % (im.name, a[2], b[2]))
        if im.state and not any(s[:2] == im.state for s in im.runtime):
            out.append('%s: its state block is not a runtime range'
                       % im.name)
        if budget_total(im) > hi - lo:
            out.append('%s: budgets %d B over its room of %d B' % (
                im.name, budget_total(im), hi - lo))
        if im.name in DESIGN_TOTALS and \
                budget_total(im) != DESIGN_TOTALS[im.name]:
            out.append('%s: the size table gives %d B, the design %d B' % (
                im.name, budget_total(im), DESIGN_TOTALS[im.name]))
        if im.frame and not {'pl_poll', 'fx_service'} <= set(im.shared):
            out.append('%s is a frame image without pl_poll, fx_service'
                       % im.name)
    ovl = IMAGE['OVLW']
    if ovl.stored != (R.MCODE, R.MCODE_END):
        out.append('OVLW is not MASKW\'s code room')
    # ---- banks
    try:
        uses = dict(LL.bank_map())
    except ValueError as error:
        out.append('llayout.bank_map(): %s' % error)
        uses = {}
    seen: Dict[int, str] = {}
    for b, name in banks():
        if b in seen:
            out.append('bank %d: %s and %s' % (b, seen[b], name))
        seen[b] = name
        use = uses.get(b)
        if b in (R.WCODE_BANK, R.MCODE_BANK):
            out.append('bank %d (%s) is the render\'s image' % (b, name))
        elif use is None:
            if b not in SPARE_FREE:
                out.append('bank %d (%s) is not spare' % (b, name))
        elif use == 'CODE':
            if b not in CODE_REUSED:
                out.append('bank %d (%s) is rlayout\'s %s' % (b, name, use))
        elif use not in ('songs', '2D'):
            out.append('bank %d (%s) is %s\'s' % (b, name, use))
    if max(SS[n] + z for n, z in S2STATE_FIELDS) > LL.ROOM[1]:
        out.append('S2STATE past $BFFF')
    # ---- the packing
    try:
        image_banks()
    except PackError as error:
        out.append('the packing: %s' % error)
    # ---- the packing's result, checked on its own: in each bank, the
    # images' stored runs disjoint and clear of MATHW's pages
    try:
        placed = image_banks()
        ext = budget_extents()
        for i, (n1, b1) in enumerate(sorted(placed.items())):
            if n1 not in ext:
                continue
            r1 = page_run(*ext[n1])
            if r1[0] < MATHW_END >> 8 or r1[0] + r1[1] > W_HI >> 8:
                out.append('%s\'s stored pages leave W or meet MATHW' % n1)
            for n2, b2 in sorted(placed.items())[i + 1:]:
                if n2 not in ext or b1 != b2:
                    continue
                r2 = page_run(*ext[n2])
                if r1[0] < r2[0] + r2[1] and r2[0] < r1[0] + r1[1]:
                    out.append('bank %d: the stored pages of %s and %s '
                               'overlap' % (b1, n1, n2))
        if set(placed) != {im.name for im in IMAGES}:
            out.append('the packing leaves an image out')
        if any(b not in CODE_BANKS for n, b in placed.items()
               if n != 'OVLW'):
            out.append('the packing uses a bank that is not a code bank')
    except PackError:
        pass                    # (reported above)
    # ---- the state blocks: own parts inside each image's block, PALST
    for name, (block, w) in OWN_STATE.items():
        st = IMAGE[name].state
        if not (st and st[0] <= w and w + SS_SIZE[block] <= st[1]):
            out.append('%s\'s own state ($%04X, %d B) is not in its state '
                       'block' % (name, w, SS_SIZE[block]))
        if name in PALST_IMAGES and not (
                st and st[0] <= PALST_W and PALST_W + PALST_SIZE <= w):
            out.append('%s\'s PALST is not before its own state' % name)
        try:
            state_places(name)
        except ValueError as error:
            out.append('%s\'s state: %s' % (name, error))
    try:
        palst_places()
    except ValueError as error:
        out.append('PALST: %s' % error)
    # ---- S2PAL's places (S2PAL-1): in $0200-$BFFF, disjoint, S2P_NIB
    # page aligned
    spans = sorted((a, a + z, n) for n, a, z in S2PAL_PLACES)
    for lo, hi, n in spans:
        if not (LL.ROOM[0] <= lo < hi <= LL.ROOM[1]):
            out.append('S2PAL: %s outside $0200-$BFFF' % n)
    for x, y in zip(spans, spans[1:]):
        if y[0] < x[1]:
            out.append('S2PAL: %s and %s overlap' % (x[2], y[2]))
    if S2PAL_AT['S2P_NIB'] & 0xFF:
        out.append('S2PAL: S2P_NIB is not page aligned')
    if not (LL.ROOM[0] <= SFX_ROOM[0] < SFX_ROOM[1] <= LL.ROOM[1]) or \
            not (LL.ROOM[0] < S2VIEW_SAVE[0] < S2VIEW_SAVE[1] < LL.ROOM[1]):
        out.append('SFX_ROOM or S2VIEW_SAVE outside $0200-$BFFF')
    # the songs' directory (PLBOOT-2): in the first song bank's room
    dir_end = SONG_DIR[1] + SONG_DIR_ENTRY * SONG_COUNT
    if SONG_DIR[0] not in SONGS or \
            not LL.ROOM[0] <= SONG_DIR[1] < dir_end <= LL.ROOM[1]:
        out.append('SONG_DIR outside the song banks\' $0200-$BFFF')
    # ---- main: the input block and PL_STATUS
    if PL_STATUS != LL.LV_STATUS:
        out.append('PL_STATUS is not LV_STATUS\'s byte')
    # the stop codes that share PL_STATUS's byte: every one its own
    codes = list(S2S.values()) + list(PL.values()) + list(LL.LS.values())
    if len(set(codes)) != len(codes):
        out.append('PL_STATUS: two stops share a code')
    used = max(INPUT[n] + s for n, s in INPUT_FIELDS)
    if used > INPUT_END:
        out.append('the input block passes $%04X' % INPUT_END)
    block = (INPUT_LO, INPUT_END)
    taken = [(r.start, r.end, 'rlayout ' + r.what) for r in R.regions()
             if r.space == 'main']
    taken += [(LL.LV_VARMAP, LL.LV_VARMAP + 1, 'LV_VARMAP'),
              (LL.LVCOUNT2, LL.LVCOUNT2_END, 'the level counts (llayout)'),
              (LL.LV_STATUS, LL.LV_AMEM + 1, 'LV_STATUS, LV_AMEM'),
              (LL.PRND, LL.MRND + 1, 'PRND, MRND'),
              (LL.GBLOCK, LL.GLOBALS_END, 'the game globals'),
              (0x03F0, 0x0400, 'the ROM\'s soft vectors')]
    if g is not None:
        taken += [(r.start, r.end, 'glayout ' + r.what) for r in g.regions()
                  if r.space == 'main']
    for lo, hi, what in taken:
        if _overlap(block, (lo, hi)):
            out.append('the input block $%04X-$%04X overlaps %s ($%04X-'
                       '$%04X)' % (INPUT_LO, INPUT_END - 1, what, lo, hi - 1))
        if _overlap(KEYTAB_PLACE, (lo, hi)):
            out.append('the key table $%04X-$%04X overlaps %s ($%04X-$%04X)'
                       % (KEYTAB_PLACE[0], KEYTAB_PLACE[1] - 1, what, lo,
                          hi - 1))
    if not (0x0300 <= INPUT_LO and INPUT_END <= 0x03F0):
        out.append('the input block is outside the persistent globals')
    # the key table (PLINPUT-1): in MEMORY_MAP.md 3.3's persistent
    # $1A80-$1FFF, so never in rule 3's $0400-$0BFF; clear of rlayout's,
    # llayout's and glayout's main places (the loop above)
    if not (0x1A80 <= KEYTAB_PLACE[0] and KEYTAB_PLACE[1] <= 0x2000) or \
            KEYTAB_PLACE[1] - KEYTAB_PLACE[0] != 128:
        out.append('the key table is not 128 B in $1A80-$1FFF')
    if INPUT['PL_QUEUE'] + QUEUE_EVENTS * EVENT_SIZE != INPUT['PL_QHEAD']:
        out.append('the queue is not 15 events of 3 bytes')
    # ---- zero page
    if not (R.ZP_OV2[0] <= ZP_S2[0] and ZP_S2M[1] <= R.ZP_OV2[1]):
        out.append('the 2D zero page is outside overlay 2')
    if _overlap(ZP_S2, R.ZP_FORBIDDEN) or _overlap(ZP_S2M, R.ZP_FORBIDDEN):
        out.append('the 2D zero page meets $42-$47')
    if ZP_MATH != LL.MATH_ZP:
        out.append('the math block moved')
    if not (ZP_IRQ[0] <= ZP_MUSIC[0] and ZP_FXRING[1] <= ZP_IRQ[1]) or \
            _overlap(ZP_MUSIC, ZP_FXRING):
        out.append('the IRQ\'s zero page')
    if FX_ZP != {'FXZ_RING': ZP_FXRING[0], 'FXZ_N': ZP_FXRING[0] + 2,
                 'FXZ_T': ZP_FXRING[0] + 3, 'FXZ_AV': ZP_FXRING[0] + 4,
                 'FXZ_OP': ZP_FXRING[0] + 5}:
        out.append('the ring pointers')
    for a, b in ((ZP_S2, ZP_S2M), (ZP_S2M, ZP_MATH), (ZP_MATH, ZP_IRQ)):
        if a[1] > b[0]:
            out.append('zero-page ranges overlap')
    # the drawers' places: inside ZP_S2, disjoint but for the named aliases
    zp_named = {n: (a, a + z) for n, a, z in S2_ZP}
    if len(zp_named) != len(S2_ZP):
        out.append('a drawer zero-page name twice')
    for i, (n1, a1, z1) in enumerate(S2_ZP):
        if not (ZP_S2[0] <= a1 and a1 + z1 <= ZP_S2[1]):
            out.append('%s ($%02X) is outside S2_*\'s zero page' % (n1, a1))
        for n2, a2, z2 in S2_ZP[i + 1:]:
            if _overlap((a1, a1 + z1), (a2, a2 + z2)) and \
                    S2_ZP_ALIASES.get(n1) != n2 and \
                    S2_ZP_ALIASES.get(n2) != n1:
                out.append('%s and %s share zero page' % (n1, n2))
    for alias, of in S2_ZP_ALIASES.items():
        a, b = zp_named.get(alias), zp_named.get(of)
        if a is None or b is None or not (b[0] <= a[0] and a[1] <= b[1]):
            out.append('%s is not inside %s' % (alias, of))
    # pl_poll's PLZ (PLINPUT-4): inside ZP_S2 and over the drawers'
    # temporaries S2_W .. S2_O only, never the band's kept state
    if not (ZP_S2[0] <= PL_ZP[0] < PL_ZP[1] <= ZP_S2[1]) or \
            PL_ZP != (zp_named['S2_W'][0], zp_named['S2_O'][1]):
        out.append('PLZ is not the drawers\' temporaries S2_W .. S2_O')
    # ---- each drawing image's marks page and fetch buffer (S2DRAW-1)
    for name, (marks, fbuf, pages) in DRAW_PLACES.items():
        im = IMAGE[name]
        ranges = {r[2]: r[:2] for r in im.runtime}

        def inside(lo, hi):
            return any(r[0] <= lo and hi <= r[1] for r in im.runtime)
        if marks & 0xFF or not inside(marks, marks + 0x100) or \
                not any(w == 'marks' and r[0] <= marks < r[1]
                        for w, r in ranges.items()):
            out.append('%s: the marks page $%04X is not a page of its marks'
                       % (name, marks))
        if fbuf is None:
            if pages:
                out.append('%s: fetch pages without a buffer' % name)
            continue
        if 's2_draw+s2_pub' not in im.shared:
            out.append('%s has a fetch buffer but no drawer' % name)
        fr = ranges.get('fetch buffer') or ranges.get('patch fetch buffer')
        if fbuf & 0xFF or pages < 2 or fr is None or \
                not (fr[0] <= fbuf and fbuf + 256 * pages <= fr[1]):
            out.append('%s: the fetch buffer $%04X, %d pages, is not in its '
                       'fetch buffer range' % (name, fbuf, pages))
    # ---- the card
    if S2T_USED > S2T_SIZE:
        out.append('the tic-side block takes %d of %d B' % (S2T_USED,
                                                            S2T_SIZE))
    if CHF_PICKUP & CHF_KIND or max(ORIGIN.values()) & ~CHF_KIND:
        out.append('the pickup flag meets the origin kinds in CH_KIND')
    if sum(n for _, n in VOICE_FIELDS) != VOICE_SIZE or \
            sum(n for _, n in CHAN_FIELDS) != CHAN_SIZE or \
            sum(n for _, n in MAIL_FIELDS) != MAIL_SIZE:
        out.append('a record format does not fill its size')
    if FXV_END != 0xE443 or FX_RING_END != 0xE8C0:
        out.append('the voices or the rings moved')
    others = list(S2_CARD) + [PLATFORM_CARD, VECTORS]
    lce = None
    if g is not None:
        m = re.search(r'LCE:\s*start = \$([0-9A-F]+), size = \$([0-9A-F]+)',
                      g.game_cfg())
        if m:
            lce = (int(m.group(1), 16),
                   int(m.group(1), 16) + int(m.group(2), 16))
    for build, cb in BUILDS.items():
        blocks = card_blocks(build)
        if build == 'release':
            blocks.append(('the effect code', FX_CODE[0], FX_CODE[1]))
        for i, (n, lo, hi) in enumerate(blocks):
            if not (CARD_LO <= lo < hi <= 0x10000):
                out.append('%s: %s outside $E000-$FFFF' % (build, n))
            for n2, lo2, hi2 in blocks[i + 1:]:
                if _overlap((lo, hi), (lo2, hi2)):
                    out.append('%s: %s overlaps %s' % (build, n, n2))
            if build == 'm11':  # gdriver.s's $E000 part, the replay's
                stays = [('gdriver.s', 0xE000, 0xEE00), REPLAY_CARD,
                         PLATFORM_CARD, VECTORS]
                if lce is not None:
                    stays[0] = ('gdriver.s', lce[0], lce[1])
            else:
                stays = [o for o in others if not (
                    build == 'fxch8' and o[0].startswith('the song ring'))]
                stays.append(REPLAY_CARD if build == 'release' else
                             ('the test driver', DRV[0], DRV[1]))
            for n2, lo2, hi2 in stays:
                if build == 'm11' and n in ('the clock', 'the effect voices',
                                            'the effects\' flags',
                                            'the effect rings'):
                    continue    # (no sound in milestone 10's M11 build)
                if _overlap((lo, hi), (lo2, hi2)):
                    out.append('%s: %s overlaps %s' % (build, n, n2))
        s2t = cb.s2t_base
        sc = (cb.sc_base, cb.sc_base + sc_size(cb.channels))
        if s2t is not None and not (cb.room[0] <= s2t and
                                    s2t + S2T_SIZE <= cb.room[1]) and \
                build != 'fxch8':
            out.append('%s: the tic-side block outside its room' % build)
        if not (cb.room[0] <= sc[0] and sc[1] <= cb.room[1]):
            out.append('%s: the channels outside their room' % build)
        if build == 'm11' and lce is not None and (
                _overlap((s2t, s2t + S2T_SIZE), lce) or _overlap(sc, lce)):
            out.append('m11: the blocks meet gdriver\'s $E000 part')
    # (3 channels in the release's 64 B, 14 spare since wave 4's SC_EXTRA;
    # FXCH8's 8 in the song ring's place)
    if sc_size(3) > 64 or sc_size(8) != 8 * (CHAN_SIZE + MAIL_SIZE) + \
            SC_EXTRA_SIZE:
        out.append('the channel blocks\' sizes')
    if DRV != REPLAY_CARD[1:]:
        out.append('the test driver is not in the replay\'s place')
    # ---- the regions
    for name, rg in REGIONS.items():
        if not rg.bounds_ok() or rg.name != name:
            out.append('the region %s is out of the screen' % name)
    for kind, (names, overlays) in FRAME_KINDS.items():
        allowed = {frozenset((a, b)) for a, b, _ in overlays}
        sets = {n: set(REGIONS[n].offsets()) for n in names}
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if frozenset((a, b)) in allowed:
                    continue
                both = sets[a] & sets[b]
                if both:
                    out.append('%s: the regions %s and %s overlap at aux 0 '
                               '$%04X' % (kind, a, b, min(both)))
    # ---- the phases
    layouts = [R, LL, this_module()] + ([g] if g is not None else [])
    out += phase_problems(layouts, root)
    if PHASE_2D == PHASE_PLATFORM:
        out.append('the 2D and platform phases are one')
    # ---- the field map
    for f in field_map():
        try:
            if f.kind == 'game':
                resolve_game(f.place)
            elif f.kind == 'card':
                if f.place.partition('+')[0] not in S2T:
                    out.append('field %s: no card place %s' % (f.ref,
                                                               f.place))
            elif f.kind == 'bank':
                name = f.place.partition('+')[0]
                if name not in SS and not name.startswith('S2PAL:'):
                    out.append('field %s: no S2STATE place %s' % (f.ref,
                                                                  f.place))
            elif f.kind not in ('state', 'palst'):
                out.append('field %s: kind %s' % (f.ref, f.kind))
            if f.enc not in ('word', 'byte', 'sxbyte', 'flag', 'long',
                             'bytes', 'dropped', 'player', 'table', 'game',
                             'gfx', 'readysrc', 'msgid'):
                out.append('field %s: encoding %s' % (f.ref, f.enc))
        except ValueError as error:
            out.append(str(error))
    screens = {f.screen for f in field_map()}
    if screens != {'stbar', 'hud', 'palettes', 'menus', 'automap',
                   'intermission', 'finale'}:
        out.append('the field map\'s screens: %s' % sorted(screens))
    return out


def linkmap_problems(sym) -> List[str]:
    """Every upstream field of the map that names a unit's label exists in
    the link map with at least its offset + size bytes (bridge.linkmap's
    Symbols; needs build/linkmap.json)."""
    out = []
    for f in field_map():
        m = re.match(r'^(\w+65\.s):(\w+)(?:\+(\d+))?$', f.ref)
        if not m or f.ref.startswith('i_viigs65.s:STCACHE'):
            continue
        unit, label, off = m.group(1), m.group(2), int(m.group(3) or 0)
        try:
            lab = sym.label('%s:%s' % (unit, label))
        except KeyError:
            out.append('%s is not in the link map' % f.ref)
            continue
        if f.size and off + f.size > lab.size:
            out.append('%s: %d + %d bytes, the label has %d' % (
                f.ref, off, f.size, lab.size))
    return out


# ---------------------------------------------------------------------------
# Sizes against an image's ld65 map (4.1's size table)
# ---------------------------------------------------------------------------

IMG_SEGMENTS = ('S2CODE', 'S2RODATA', 'S2DATA')


class MapSizes(NamedTuple):
    extent: Optional[Tuple[int, int]]   # the room's segments [lo, end)
    modules: Dict[str, int]             # module stem -> bytes in the room


def read_map(text: str) -> MapSizes:
    segs = {}
    for m in re.finditer(r'^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+'
                         r'([0-9A-F]{6})', text, re.M):
        segs[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16),
                            int(m.group(4), 16))
    room = [segs[s] for s in IMG_SEGMENTS if s in segs and segs[s][2]]
    extent = (min(s[0] for s in room), max(s[1] for s in room) + 1) \
        if room else None
    modules: Dict[str, int] = {}
    part = text.split('Modules list:', 1)[-1].split('Segment list:', 1)[0]
    module = None
    for line in part.splitlines():
        if line and not line.startswith(' ') and line.rstrip().endswith(':'):
            module = Path(line.strip()[:-1].split('(')[0]).stem
            continue
        f = line.split()
        if module and f and f[0] in IMG_SEGMENTS:
            size = next(int(x[5:], 16) for x in f if x.startswith('Size='))
            modules[module] = modules.get(module, 0) + size
    return MapSizes(extent, modules)


def module_row(stem: str) -> str:
    base = stem.split('-')[0]
    if base in MATHW_MODULES:
        return 'MATHW'
    return MODULE_ROW.get(base, 'own')


def size_rows(image: str, ms: MapSizes) -> Tuple[List[str], List[str]]:
    """The image's size table rows and its fatal problems (the room)."""
    im = IMAGE[image]
    rows_out, problems = [], []
    by_row: Dict[str, int] = {}
    for stem, n in ms.modules.items():
        row = module_row(stem)
        # an image that links the publish alone (AMAPW) counts it in its
        # own row (part s2draw, request S2DRAW-2)
        if row == 's2_draw+s2_pub' and row not in im.shared and \
                's2_pub' in im.shared and stem.split('-')[0] == 's2_pub':
            row = 's2_pub'
        by_row[row] = by_row.get(row, 0) + n
    for row in list(im.shared) + ['own']:
        budget = SHARED_BUDGETS[row] if row != 'own' else im.own
        n = by_row.pop(row, 0)
        rows_out.append('%-6s %-15s %6d of %6d B%s' % (
            image, row, n, budget, '  OVER BUDGET' if n > budget else ''))
    for row, n in sorted(by_row.items()):
        if row == 'MATHW':
            continue
        problems.append('%s links %s (%d B), which its size table does '
                        'not list' % (image, row, n))
    lo, hi = im.stored
    # stored bytes stay below a run time range inside the room (OVLW's)
    hi = min([hi] + [a for a, b, _ in im.runtime if lo < a < hi])
    if ms.extent is not None:
        used = ms.extent[1] - lo
        rows_out.append('%-6s %-15s %6d of %6d B ($%04X-$%04X)' % (
            image, 'room', used, hi - lo, ms.extent[0], ms.extent[1] - 1))
        if ms.extent[0] < lo or ms.extent[1] > hi:
            problems.append('%s: $%04X-$%04X is over its room $%04X-$%04X '
                            'by %d B' % (image, ms.extent[0],
                                         ms.extent[1] - 1, lo, hi - 1,
                                         max(ms.extent[1] - hi,
                                             lo - ms.extent[0])))
    return rows_out, problems


def check_map(image: str, text: str) -> Tuple[List[str], List[str]]:
    return size_rows(image, read_map(text))


# ---------------------------------------------------------------------------
# s2.inc and the images' ld65 maps
# ---------------------------------------------------------------------------

def constants(build: str = 'test') -> List[Tuple[str, int]]:
    cb = BUILDS[build]
    banks_ = image_banks()
    out: List[Tuple[str, int]] = []
    for im in IMAGES:
        n = im.name
        out += [(n + '_LO', im.stored[0]), (n + '_HI', im.stored[1]),
                (n + '_BANK', banks_[n])]
        if im.state:
            out += [(n + '_STATE', im.state[0]),
                    (n + '_STATE_END', im.state[1])]
        for k, (lo, hi, _) in enumerate(im.runtime):
            out += [('%s_RT%d' % (n, k), lo), ('%s_RT%d_END' % (n, k), hi)]
        if n in DRAW_PLACES:
            marks, fbuf, pages = DRAW_PLACES[n]
            out += [(n + '_MARKS', marks)]
            if fbuf is not None:
                out += [(n + '_FBUF', fbuf), (n + '_FBPAGES', pages)]
    out += [('MATHW_LO', MATHW_LO), ('MATHW_END', MATHW_END)]
    out += [(name.split(' ')[0], b) for b, name in banks()]
    out += [('SONG_DIR_BANK', SONG_DIR[0]), ('SONG_DIR', SONG_DIR[1]),
            ('SONG_DIR_ENTRY', SONG_DIR_ENTRY)]
    out += sorted(SS.items(), key=lambda x: x[1])
    out += [(k + '_SIZE', v) for k, v in S2STATE_FIELDS]
    out += [('PALST_W', PALST_W), ('PALST_SIZE', PALST_SIZE)]
    out += [(n, a) for n, a, _ in S2PAL_PLACES]
    out += [(n + '_SIZE', z) for n, _, z in S2PAL_PLACES]
    out += sorted(palst_places().items(), key=lambda x: x[1])
    for name in OWN_STATE:
        out += sorted(state_places(name).items(), key=lambda x: x[1])
    out += [('MENUW_PALST', MENUW_PALST)]
    out += list(MENU_REQUESTS)
    out += [('PL_STATUS', PL_STATUS)]
    out += sorted(INPUT.items(), key=lambda x: x[1])
    out += [('PL_EVENTS', QUEUE_EVENTS), ('PL_EVENT_SIZE', EVENT_SIZE)]
    out += [('PL_KEYTAB', KEYTAB_PLACE[0])] + list(PL_BIND_VALUES)
    out += [('S2S_' + k, v) for k, v in S2S.items()]
    out += [('PL_' + k, v) for k, v in PL.items()]
    out += sorted(CLOCK.items(), key=lambda x: x[1])
    out += [('FXV_BASE', FXV_BASE), ('VOICE_SIZE', VOICE_SIZE),
            ('VOICES', VOICES)]
    out += sorted(VOICE.items(), key=lambda x: x[1])
    out += sorted(FX.items(), key=lambda x: x[1])
    out += [('FX_RING', FX_RING), ('RING_SIZE', RING_SIZE)]
    s2t = cb.s2t_base if cb.s2t_base is not None else 0
    out += [('S2T_BASE', s2t), ('S2T_SIZE', S2T_SIZE)]
    out += [(k, s2t + v) for k, v in sorted(S2T.items(), key=lambda x: x[1])]
    out += [('MAIL_AMSTOP', MAIL_AMSTOP), ('MAIL_AMSTRIP', MAIL_AMSTRIP),
            ('MAIL_AMTITLE', MAIL_AMTITLE), ('MAIL_AMVIEW', MAIL_AMVIEW)]
    out += [('SC_BASE', cb.sc_base), ('NUM_CHANNELS', cb.channels),
            ('CHAN_SIZE', CHAN_SIZE), ('MAIL_SIZE', MAIL_SIZE),
            ('SC_MAIL', cb.sc_base + cb.channels * CHAN_SIZE)]
    out += sorted(CHAN.items(), key=lambda x: x[1])
    out += [('CHF_PICKUP', CHF_PICKUP), ('CHF_KIND', CHF_KIND)]
    out += sorted(MAIL.items(), key=lambda x: x[1])
    sx = sc_extra_base(cb.sc_base, cb.channels)
    out += [(k, sx + v) for k, v in sorted(SC_EXTRA.items(),
                                           key=lambda x: x[1])]
    out += [('MX_STOP', MX_STOP), ('MX_START', MX_START),
            ('MX_VOLUME', MX_VOLUME)]
    out += [('ORG_' + k, v) for k, v in ORIGIN.items()]
    out += [('PHV_2D', 2 * PHASE_2D), ('PHV_PLATFORM', 2 * PHASE_PLATFORM),
            ('PHV_DRIVER', 2 * PHASE_DRIVER)]
    out += [('DRV_CALLS', DRV_CALLS), ('CALL_SIZE', CALL_SIZE),
            ('DRV_LOADS', DRV_LOADS), ('STACK_FLOOR', STACK_FLOOR)]
    out += [('SHR', SHR), ('SCB', SCB), ('PALETTES', PALETTES),
            ('ROW_BYTES', ROW_BYTES)]
    return out


def zeropage() -> List[Tuple[str, int]]:
    return [('S2ZP_LO', ZP_S2[0]), ('S2ZP_END', ZP_S2[1]),
            ('S2MZP_LO', ZP_S2M[0]), ('S2MZP_END', ZP_S2M[1]),
            ('PLZ', PL_ZP[0])] + \
        sorted(FX_ZP.items(), key=lambda x: x[1]) + \
        [(n, a) for n, a, _ in S2_ZP]


def include_text(build: str = 'test') -> str:
    check()
    lines = ['; Generated by tools/native/s2layout.py (docs/SCREENS.md 4), '
             'build %s. Do not edit.' % build, '']
    seen = set()
    for name, value in constants(build):
        if name in seen:
            raise ValueError('%s twice in s2.inc' % name)
        seen.add(name)
        lines.append('%-16s= $%04X' % (name, value))
    lines += ['', '; zero page']
    for name, value in zeropage():
        if name in seen:
            raise ValueError('%s twice in s2.inc' % name)
        seen.add(name)
        lines.append('%-16s= $%02X' % (name, value))
    return '\n'.join(lines) + '\n'


# the card areas of a 2D image's map (as src/sound/music.cfg places S2's
# player in the game, MEMORY_MAP.md 4.2), all optional
CFG_CARD = """\
    SNDZP:  start = $00D8, size = $0028, type = rw, file = "";
    RING:   start = $E000, size = $0403, type = rw, file = "";
    LIST:   start = $E480, size = $0080, type = rw, file = "";
    STATE:  start = $E500, size = $0240, type = rw, file = "";
    SND:    start = $E900, size = $0C05, file = "%O.snd";
    FXC:    start = $F505, size = $03FB, file = "%O.fxc";
"""


def cfg_text(image: str) -> str:
    """ld65's map of a 2D image (and this half's test driver): MATHW and
    AUXW at $6000, the image's room (the S2CODE, S2RODATA, S2DATA
    segments), the card's math and far layer as the render images have
    them, S2's player and the effects' card code (optional), the test
    driver at $F900-$FEFF (s2_drv.s: DRIVER, DESC), the vectors."""
    im = IMAGE[image]
    lo, hi = im.stored
    return '\n'.join([
        '# Generated by tools/native/s2layout.py (docs/SCREENS.md 4.1, 4.4):',
        '# the image %s. Do not edit.' % image,
        'MEMORY {',
        '    W:      start = $6000, size = $%04X, file = "%%O.w";' % (
            IMAGE_LO - 0x6000),
        '    IMG:    start = $%04X, size = $%04X, file = "%%O.img";' % (
            lo, hi - lo),
        '    LC1:    start = $D800, size = $0400, file = "%O.lc1";',
        '    FAR:    start = $DC00, size = $0400, file = "%O.far";',
        CFG_CARD.rstrip('\n'),
        '    LCE:    start = $%04X, size = $%04X, file = "%%O.lce";' % (
            DRV[0], DRV[1] - DRV[0]),
        '    VEC:    start = $FFFA, size = $0006, file = "%O.vec";',
        '}',
        'SEGMENTS {',
        '    MATHLC:    load = LC1, type = ro;',
        '    MATHFAR:   load = FAR, type = ro;',
        '    RFAR:      load = FAR, type = rw;',
        '    RLOAD:     load = FAR, type = ro;',
        '    MATHW:     load = W,   type = ro, define = yes;',
        '    AUXW:      load = W,   type = rw, define = yes;',
        '    S2CODE:    load = IMG, type = ro, define = yes, optional = yes;',
        '    S2RODATA:  load = IMG, type = ro, define = yes, optional = yes;',
        '    S2DATA:    load = IMG, type = rw, define = yes, optional = yes;',
        '    SNDZP:     load = SNDZP, type = zp, optional = yes;',
        '    SNDRING:   load = RING, type = bss, align = $100, optional = yes;',
        '    SNDLIST:   load = LIST, type = bss, optional = yes;',
        '    SNDBSS:    load = STATE, type = bss, optional = yes;',
        '    SNDCODE:   load = SND, type = ro, optional = yes;',
        '    SNDRODATA: load = SND, type = ro, optional = yes;',
        '    FXCODE:    load = FXC, type = ro, define = yes, optional = yes;',
        '    DRIVER:    load = LCE, type = rw, define = yes;',
        '    DESC:      load = LCE, type = bss, define = yes, align = $100;',
        '    VECTORS:   load = VEC, type = ro, optional = yes;',
        '}',
        'SYMBOLS {',
        '    __RENDERW_RUN__:  type = export, value = $6600;',
        '    __RENDERW_SIZE__: type = export, value = 0;',
        '}', ''])


def write_if_changed(path: Path, text: str) -> None:
    """Write text atomically, and only when it differs (several makes may
    share build/native/m11/shared)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=str(path.parent))
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)
    os.replace(tmp, str(path))


def report() -> List[str]:
    out = ['The 2D images (docs/SCREENS.md 4.1), budgets against rooms:']
    banks_ = image_banks()
    for im in IMAGES:
        out.append('  %-6s $%04X-$%04X  %6d of %6d B  bank %d' % (
            im.name, im.stored[0], im.stored[1] - 1, budget_total(im),
            im.stored[1] - im.stored[0], banks_[im.name]))
    try:
        pack(budget_extents(), FIRST_CODE_BANKS)
        out.append('The first design\'s code banks 107, 108, 94 hold the '
                   'images.')
    except PackError as error:
        out.append('The first design\'s code banks 107, 108, 94 do not '
                   '(S2LAY-1): %s' % error)
    last = S2STATE_FIELDS[-1][0]
    out.append('S2STATE (bank %d): $%04X-$%04X used' % (
        S2STATE, LL.ROOM[0], SS[last] + SS_SIZE[last] - 1))
    out.append('Card: the tic-side block %d of %d B; the channels %d of 64 B'
               % (S2T_USED, S2T_SIZE, sc_size(3)))
    found, unread = source_phases()
    out.append('Phases written by the sources: %s; unread: %d' % (
        ', '.join(str(v) for v in sorted({v for _, v in found})),
        len(unread)))
    found, unread = source_phases(harness=True)
    out.append('Phases written by test builds\' harnesses (%s): %s; '
               'unread: %d' % (HARNESS_SYMBOL, ', '.join(
                   '%s %d' % (w, v) for w, v in found if v) or 'none',
                   len(unread)))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    build = 'test'
    if '--build' in argv:
        k = argv.index('--build')
        build = argv[k + 1]
        del argv[k:k + 2]
        if build not in BUILDS:
            print('no build %s (%s)' % (build, ', '.join(BUILDS)),
                  file=sys.stderr)
            return 2
    if argv == ['--check']:
        check()
        print('s2layout: check passed')
        return 0
    if argv == ['--report']:
        print('\n'.join(report()))
        return 0
    if len(argv) == 2 and argv[0] == '--inc':
        write_if_changed(Path(argv[1]), include_text(build))
        return 0
    if len(argv) == 2 and argv[0] == '--rlayout-inc':
        write_if_changed(Path(argv[1]), R.include_text())
        return 0
    if len(argv) == 3 and argv[0] == '--cfg' and argv[1] in IMAGE:
        write_if_changed(Path(argv[2]), cfg_text(argv[1]))
        return 0
    if len(argv) >= 3 and argv[0] == '--check-map' and argv[1] in IMAGE:
        bad = 0
        for path in argv[2:]:
            rows_, problems = check_map(argv[1], Path(path).read_text())
            print('\n'.join(rows_))
            for p in problems:
                print('error: ' + p, file=sys.stderr)
            bad += len(problems)
        return 1 if bad else 0
    print(__doc__.split('\n\n')[2], file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
