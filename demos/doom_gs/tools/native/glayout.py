#!/usr/bin/env python3
"""The layouts of milestone 10, the game logic (docs/GAME.md 1, 3.2, 4), in
tools/native/llayout.py's and rlayout.py's family: one source of every
address, as milestone 9's llayout.py is.

llayout.py holds the game state's final layouts (the mobj groups and the
planes bank MOBJP, the specials and their free lists, the globals of 1.5,
LVS, the object API's places, which the load image and the tic images
share); this module adds the tic phase: W's map (4.1), the main ranges and
the zero page of 4.4, the runtime's state, the parts' scratch blocks, the
part table of 2.4 as data (keyed file:label), the dispatch tables (2.2),
the stop codes, the GTEST bank's layout, and writes:

    gen/ggame.inc       the tic phase's places, the zero page (GA_*, GT_*,
                        the API's pointers), the scratch blocks, the stop
                        codes, upstream's constants (UC_*, UO_*: offsets.inc
                        and info.inc through the bridge's incfile.py)
    gen/gplace.inc      each routine's image and group (gplace.py's
                        placement), the FCALL and ROUTINE macros
    gen/gdisp.inc       the five dispatch tables: each entry the target's
                        group and address when its part is built, else the
                        unbuilt stop and the entry's number
    native-game-1.json  the bridge manifest's index; manifests/ one a map
    game.cfg            ld65's map of the tic images

into build/native/game/shared/ (the integrator's; parts read them) or,
with --out and --built, a part's own GEN (make -f game.mk part).

Usage:  python3 tools/native/glayout.py [--out DIR] [--built PART,...]
                                         [--test-place]
        python3 tools/native/glayout.py --check
        python3 tools/native/glayout.py --report

check(): no region used twice; every tic range dead between the replay's
end and the next frame's front end in rlayout.py's region list; every
canonical field placed or excluded by name (with build/).
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, \
    Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import llayout as LL, rlayout as R  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
GAME = BUILD / 'native' / 'game'
SHARED = GAME / 'shared'
SRC = ROOT / 'src' / 'native'
INTEGRATED = SRC / 'game' / 'integrated.txt'

# ---------------------------------------------------------------------------
# W in the tic phase, F1.2.1 (docs/GAME.md 4.1, as revised by review 11;
# wave 2 as integrated: the core takes 512 B of slot 1, whose groups the
# placement cuts at slot 2's 2,048 B, to hold the game's math, damage.md
# R1)
# ---------------------------------------------------------------------------
W_MAP = [
    ('MATHW', 0x6000, 0x6600, 'MATHW, AUXW: the render images\' bytes'),
    ('CORE', 0x6600, 0x9A00, 'the core image'),
    ('SCRATCH', 0x9A00, 0x9E00, 'the parts\' scratch blocks'),
    ('SLOT1', 0x9E00, 0xA600, 'slot 1: one paged group'),
    ('SLOT2', 0xA600, 0xAE00, 'slot 2: one paged group'),
    ('GW', LL.GW, LL.GW_END, 'the API\'s caches, the intercepts, the '
     'core\'s buffers'),
    ('PLANES', LL.PL_TNL, LL.PL_TICS + LL.PLANE_SLOTS,
     'the thinker walk\'s planes'),
]
WR = {name: (lo, hi) for name, lo, hi, _ in W_MAP}
SLOTS = {1: WR['SLOT1'], 2: WR['SLOT2']}
# The frame slots (docs/GAME.md 4.1, 4.3; docs/SPEED.md 9): main
# $2000-$5FFF holds the replay's colormaps A and B, light levels 0-31
# (MEMORY_MAP.md 3.4), which only the replay reads. During the tic phase
# the placement's pinned groups (slots FRAME_FIRST and up, one group a
# slot) run there, each in a place of its own: gcall.s's gr_load copies a
# pinned group in by one memory-API PRIVATE request at its first call in
# a frame (a CPU store there would be a video write: MEMORY_MAP.md rule
# 3), and fs_restore copies the colormap bytes it covered back from the
# level's copy in LVC (lg_cmaps's) before the tic phase ends. A slot
# never crosses $4000, so its restore is one copy from one of LVC's two
# colormaps: (main range, its source in LVC)
FRAME_REGION = (LL.MAIN_CMAPA, LL.MAIN_CMAPB + LL.CMAP_LOW)
FRAME_HALVES = ((LL.MAIN_CMAPA, LL.MAIN_CMAPA + LL.CMAP_LOW, LL.LVC_CMAPA),
                (LL.MAIN_CMAPB, LL.MAIN_CMAPB + LL.CMAP_LOW, LL.LVC_CMAPB))
FRAME_FIRST = 3                 # the first frame slot's number
FS_MAX = 16                     # frame slots at most (the runtime's state)
AM_MAX = 15                     # descriptors a memory-API request (gcall.s
#                                 AM_MAX: the list's length 8 + 16 N a
#                                 byte): fs_restore's one request takes a
#                                 descriptor a loaded frame slot
FRAME_MARGIN = 96               # a frame slot's room past its group's bytes
#                                 (gplace.py's GROUP_MARGIN: the planted
#                                 bugs' copies link the same placement)


def frame_pages(group: Dict[str, Any]) -> int:
    """A frame slot's pages: its group's bytes (the placement's measure;
    a W slot's when it has none) and FRAME_MARGIN, at most a W slot's."""
    room = SLOTS[1][1] - SLOTS[1][0]
    n = min(room, int(group.get('bytes', room)) + FRAME_MARGIN)
    return (n + 0xFF) >> 8


def frame_slots(groups: Sequence[Dict[str, Any]]
                ) -> Dict[int, Tuple[int, int]]:
    """slot -> (lo, hi) of a placement's frame slots: slots FRAME_FIRST and
    up, one group each, numbered with no gap; none across $4000 (each half
    of FRAME_HALVES restores from one colormap of LVC), packed first fit
    in the order of their pages, the largest first (then their numbers),
    so whether they fit depends on their sizes alone. ValueError when they
    break a rule or do not fit."""
    pinned = sorted((int(g['slot']), i) for i, g in enumerate(groups)
                    if int(g['slot']) >= FRAME_FIRST)
    slots = [s for s, _ in pinned]
    if slots != list(range(FRAME_FIRST, FRAME_FIRST + len(slots))):
        raise ValueError('the frame slots %s: one group each, from %d' % (
            slots, FRAME_FIRST))
    if len(slots) > min(FS_MAX, AM_MAX):
        raise ValueError('%d frame slots (at most %d)' % (
            len(slots), min(FS_MAX, AM_MAX)))
    at = [lo for lo, _, _ in FRAME_HALVES]
    out = {}
    for n, s in sorted(((frame_pages(groups[i]) << 8, s) for s, i in pinned),
                       key=lambda x: (-x[0], x[1])):
        for h, (_, hi, _) in enumerate(FRAME_HALVES):
            if at[h] + n <= hi:
                out[s] = (at[h], at[h] + n)
                at[h] += n
                break
        else:
            raise ValueError('the frame slots pass main $%04X-$%04X (slot '
                             '%d, %d pages)' % (FRAME_REGION[0],
                                                FRAME_REGION[1] - 1, s,
                                                n >> 8))
    return dict(sorted(out.items()))


def frame_source(lo: int) -> int:
    """The address in LVC of main `lo`'s colormap byte (the restore's
    source)."""
    for a, b, src in FRAME_HALVES:
        if a <= lo < b:
            return src + lo - a
    raise ValueError('$%04X is not in the frame slots\' region' % lo)


def slot_range(groups: Sequence[Dict[str, Any]], slot: int
               ) -> Tuple[int, int]:
    """A slot's addresses: a W slot's, or a frame slot's (frame_slots)."""
    if slot in SLOTS:
        return SLOTS[slot]
    return frame_slots(groups)[slot]
# main, the tic phase (4.1): in rows MEMORY_MAP.md 3.3 marks not
# persistent across frames, dead between the replay's end and the next
# front end
MAIN_TIC = [
    ('MOC', LL.MOC, LL.MOC + LL.MOC_LINES * LL.MOC_LINE, 'the mobj cache'),
    ('SCC', LL.SCC, LL.SCC + LL.SCC_LINES * LL.SCC_LINE,
     'the sector cache'),
    ('BL_BUF', LL.BL_BUF, LL.BL_BUF + 0x100, 'bl_get\'s block list'),
    ('RT', LL.RT_STATE, LL.RT_END, 'the runtime\'s state'),
]
# the renderer's regions that live across frames (MEMORY_MAP.md 3.3:
# FS_*, the covered ranges, the weapon skip and its state, FRVIS;
# rlayout.py's region names), which no tic range may overlay
PERSISTENT = ('fill spans', 'covered ranges', 'weapon skip', 'WPREV',
              'FRVIS', 'WTMP', 'TEXTRANS', 'LNMAP', 'frame block',
              'render inputs', 'level counts', 'cost phase')
GLOBALS = (LL.GBLOCK, LL.GLOBALS_END)

# ---------------------------------------------------------------------------
# The zero page of the tic phase (4.4)
# ---------------------------------------------------------------------------
ZP_API = [('GC_MP', 2), ('GC_SP', 2), ('GC_LP', 2), ('GC_XP', 2)]
ZP_API_RANGE = (0x38, 0x40)
ZP_CALL = [('FC_GRP', 1), ('FC_SLOT', 1)]
ZP_CALL_RANGE = (0x40, 0x42)
GA_RANGE, GT_RANGE = (0x48, 0x5C), (0x5C, 0x75)
ZP_GA = [('GA_%d' % i, 1) for i in range(GA_RANGE[1] - GA_RANGE[0])]
ZP_GT = [('GT_%d' % i, 1) for i in range(GT_RANGE[1] - GT_RANGE[0])]
# the runtime's temporaries among GT_* (any call may change a GT_* byte,
# the API's included): the planes' values, fc_call's registers and inline
# pointer, the API's pointer and counters
API_GT = [('PL_N', 2), ('PL_K', 1), ('PL_T', 1), ('FC_P', 2), ('FC_A', 1),
          ('FC_X', 1), ('FC_Y', 1), ('FC_T', 2), ('FC_PS', 1), ('GO_P', 2),
          ('GO_I', 1), ('GO_J', 1), ('GO_T', 2)]
API_GT_AT = GT_RANGE[1] - sum(n for _, n in API_GT)
ZA = R.allocate(ZP_API, *ZP_API_RANGE)
ZC = R.allocate(ZP_CALL, *ZP_CALL_RANGE)
ZGA = R.allocate(ZP_GA, *GA_RANGE)
ZGT = R.allocate(ZP_GT, *GT_RANGE)
ZAT = R.allocate(API_GT, API_GT_AT, GT_RANGE[1])
# P_SpawnMobj's arguments (gs_spawnmobj): x, y, z, the type; the result's
# slot comes back in A:X and GC_MO; P_CreateSecNodeList's mode
GA_NAMES = {'GA_X': 0, 'GA_Y': 4, 'GA_Z': 8, 'GA_TYPE': 12,
            # the object of a dispatched call (wave 1, docs/game-parts/
            # mobjstate.md R4): a mobj's ACTTAB action and a THTAB thinker
            # function take their mobj or thinker handle in GA_0-1, an
            # ITTAB callback its line or mobj, an LSTAB handler its line
            # (upstream's _Dp)
            'GA_MO': 0}

# ---------------------------------------------------------------------------
# The tic phase's own places in GW (wave 1 as integrated, docs/GAME.md):
# after llayout's GW_FIELDS, never in the load image. p_map65.s's near
# scratch that several parts read after a call (docs/game-parts/geom.md
# R3: opentop, openbottom, openrange; tmfloorz, tmceilingz, tmdropoffz;
# MV_SS, MV_SEC; numspechit; blockRange's bounds), never overlaid; the
# object API's side buffer and its address (secfind.md request 1), its
# sector node buffer (mobjstate.md R2) and its word (API_W: the value of
# bk_put, sn_putw, hn_put, the result of bk_get, mi_get)
# ---------------------------------------------------------------------------
TIC_GW_FIELDS = [('GM_OPENTOP', 4), ('GM_OPENBOT', 4), ('GM_OPENRANGE', 4),
                 ('GM_TMFLOORZ', 4), ('GM_TMCEILZ', 4), ('GM_TMDROPZ', 4),
                 ('GM_SS', 2), ('GM_SEC', 1), ('GM_NSPEC', 1),
                 ('GM_BXL', 1), ('GM_BXH', 1), ('GM_BYL', 1), ('GM_BYH', 1),
                 ('SD_BUF', R.SIDE_SIZE), ('SD_AT', 2),
                 ('SN_BUF', LL.SN_SIZE), ('API_W', 2),
                 # the trace's state (wave 2: docs/game-parts/tracel.md
                 # R1): _g_trace, TR_LONG, the intercepts' count and the
                 # last one in, IV_ON, IV_ML/IV_MH, VT_INVB's bit 15
                 ('GM_TRACE', 16), ('GM_TRLONG', 1), ('GM_ICN', 1),
                 ('GM_ICLAST', 1), ('GM_IVON', 1), ('GM_IVM', 8),
                 ('GM_INVB', 1),
                 # attackrange (p_attack65.s AT_RANGE: part attack writes
                 # it, part spawn reads it; docs/game-parts/spawn.md
                 # request 1)
                 ('GM_ATRANGE', 4),
                 # SIDE1's constants of the trace (wave 3: docs/game-parts/
                 # tracet.md R4): VT_RR (not 0: the fast vertex sides),
                 # then the axis, VT_P1, VT_P2, VT_CV, VT_CT, VT_OXC,
                 # VT_OYC, VT_SGN's and VT_DYF's high bytes; they live
                 # from sideSetup to a trace's last block step, across the
                 # traverser's calls, and part path reads VT_RR
                 ('GM_RR', 1), ('GM_SIDE1', 15),
                 # p_map65.s's near scratch that checkpos writes and
                 # trymove, teleport and chasemove read (wave 3:
                 # checkpos.md R1): tmthing, tmx, tmy (cpCopy's), the box
                 # _g_tmbbox (top, bottom, left, right: UC_BOX* order,
                 # fixed_t each), _g_spechit (4 line numbers; their count
                 # GM_NSPEC), MP_TRY (1 when P_TryMove calls checkPos)
                 ('GM_TMTHING', 2), ('GM_TMX', 4), ('GM_TMY', 4),
                 ('GM_TMBBOX', 16), ('GM_SPECHIT', 8), ('GM_MPTRY', 1),
                 # linetarget (p_map.c's _g_linetarget: P_AimLineAttack
                 # writes it, parts wfire and chase read it after the
                 # call; a mobj handle, $FFFF none; wave 5:
                 # docs/game-parts/attack.md R1; last, so that the fields
                 # before it keep their places)
                 ('GM_LINETARGET', 2)]
TGW = R.allocate(TIC_GW_FIELDS, LL.GW_USED, LL.GW_END)
TIC_GW_USED = max(TGW[n] + k for n, k in TIC_GW_FIELDS)
# The tic phase's own persistent globals (main, after llayout's globals
# block, so that milestone 9's pre-state records keep their size): the
# map the level window holds (upstream's W_SET, w_level65.s LV_SET: the
# map of the last load, 0 none; bmLoad runs W_LevelDone only for another
# map, m_menu65.s:1780-1789), which g_resume needs for the textures the
# load made (wave 1 as integrated); idrate's frame rate flag (upstream's
# d_main65.s _g_fps_show, its low byte: no canonical state, but it lives
# across tics and loads; the harnesses write the reference's at a run's
# start, as G_WSET: docs/game-parts/pickup.md P4); the player's onground
# (upstream's p_user65.s PU_ONGROUND, its low byte: movePlayer and the
# death think write it, calcHeight reads the last tic's while the
# reaction time counts; wave 5: docs/game-parts/player.md R1)
TIC_MAIN_FIELDS = [('G_WSET', 1), ('G_FPSSHOW', 1), ('G_ONGROUND', 1)]
TGM = R.allocate(TIC_MAIN_FIELDS, LL.GLOBALS_END, LL.GBLOCK_END)
TIC_MAIN_END = max(TGM[n] + k for n, k in TIC_MAIN_FIELDS)

# ---------------------------------------------------------------------------
# The demo bank DEMOB (docs/GAME.md 1.10; docs/game-parts/flow.md request
# 1): a directory at DM_DIR: a count byte, then DM_ESIZE bytes an entry:
# the name (the manifest's symbol number and the offset of the reference
# defdemoname holds, 2 + 2), the lump's number in the WAD directory (2),
# its length (2), its address in DEMOB (2); the lumps from DM_LUMPS
# ---------------------------------------------------------------------------
DEMOB_LAYOUT = [('DM_DIR', 0x0200), ('DM_ESIZE', 10), ('DME_NAME', 0),
                ('DME_LUMP', 4), ('DME_LEN', 6), ('DME_ADDR', 8),
                ('DM_LUMPS', 0x0300)]

# ---------------------------------------------------------------------------
# The runtime's state, main $1980-$1A7F (4.1): the object API's tags,
# dirty bits and recency orders, gcall.s's slots, the thinker walk's
# state, P_CreateSecNodeList's mode, the API's counters (the tests read
# them)
# ---------------------------------------------------------------------------
RT_FIELDS = [
    ('MOC_TL', LL.MOC_LINES), ('MOC_TH', LL.MOC_LINES),
    ('MOC_DT', LL.MOC_LINES), ('MOC_ORD', LL.MOC_LINES),
    ('SCC_TAG', LL.SCC_LINES), ('SCC_DT', LL.SCC_LINES),
    ('SCC_ORD', LL.SCC_LINES),
    ('LNC_TL', LL.LNC_LINES), ('LNC_TH', LL.LNC_LINES),
    ('LNC_DT', LL.LNC_LINES), ('LNC_ORD', LL.LNC_LINES),
    ('SPC_TL', LL.SPC_LINES), ('SPC_TH', LL.SPC_LINES),
    ('SPC_DT', LL.SPC_LINES), ('SPC_ORD', LL.SPC_LINES),
    ('SLOT_GRP', FRAME_FIRST + FS_MAX),     # the group each slot holds
                                #   (1, 2, the frame slots 3 and up), $FF
                                #   none; a frame slot's group is also the
                                #   colormap bytes fs_restore puts back
    ('SLOT_NEED', FRAME_FIRST - 1 + FS_MAX),    # the group each slot's
                                #   innermost active FCALL frame needs
                                #   (slot s at SLOT_NEED - 1 + s), $FF
                                #   none: gcall.s's lazy restore
    ('FS_DIRTY', 1),            # bit 7 clear: a frame slot was loaded in
                                #   this tic phase (fs_restore has work);
                                #   K_TIC sets SLOT_GRP .. FS_DIRTY to $FF
                                #   (SLOT_CLR bytes), as the test drivers'
                                #   core_in
    ('RT_TH', 2), ('RT_NEXT', 2),   # the walk's thinker and its next
    ('MP_MODE', 1),             # P_CreateSecNodeList's walk mode (1)
    ('GO_HITS', 2), ('GO_MISS', 2), ('GO_WBACK', 2), ('FC_LOADS', 2),
    ('GO_LAST', 4),             # each kind's line last got (mo, sec, ln,
                                #   sp), $FF none
]
RT = R.allocate(RT_FIELDS, LL.RT_STATE, LL.RT_END)
RT_USED = max(RT[n] + k for n, k in RT_FIELDS) - LL.RT_STATE
SLOT_CLR = RT['FS_DIRTY'] + 1 - RT['SLOT_GRP']   # K_TIC's $FF bytes

# ---------------------------------------------------------------------------
# The stops (3.4): GS_STATUS (main, after the level's LV_STATUS and
# LV_AMEM), its argument (a routine's or an entry's number), then BRK
# ---------------------------------------------------------------------------
GS_STATUS, GS_ARG = 0x03B0, 0x03B1
GS = {'OK': 0, 'UNBUILT': 1, 'PLANES': 2, 'SPECIALS': 3, 'FINALE': 4,
      'ERROR': 5, 'ZONE': 6, 'NODES': 7, 'API': 8, 'DRIVER': 9,
      'SAVEGAME': 10, 'GROUP': 11, 'STREAM': 12, 'UNBUILTD': 13,
      'ACTION': 14, 'DEMOEND': 15,
      # recursiveSound's flood deeper than its work stack (512 levels),
      # GS_ARG the sector (wave 3: docs/game-parts/pspr.md R4)
      'FLOOD': 16,
      # the memory API refused a frame slot's PRIVATE copy (gcall.s
      # fs_send), GS_ARG its result
      'AMEM': 17}
# far_gcopy, the play kernel's one-window copy of a group (dl_kern.s, at
# this address): gr_load's copy until the copy engine took it (docs/
# SPEED.md 10); kept for CALIB.hdv's GC lines (calibdisk.py), no game
# code calls it
KERN_GCOPY = 0xFFD5
# the memory API's transport (gcall.s AMEMLC: am_req, am_begin, am_push,
# am_fin, am_runs; docs/SPEED.md 10) in the main card's bank 1, after the
# products (MATHLC, $D800-$DB5B in every image) to the bank's $DC00: the
# kernel's loads replace W and the core, and the request's wait must
# survive them. The play disk's card takes it from the tic image
# (playdisk.card_main), the test images' from their own (lrun.card_records)
AMEM_LC = (0xDB5C, 0xDC00)
# its first bytes, am_req (the request's head and descriptor, which the
# callers patch: the transport's working memory), and the main card's bank
# 1 for a write log without them (gparts' stray checks)
AM_REQ = (AMEM_LC[0], AMEM_LC[0] + 36)
LC1_LOG = 'lc1:D000-%04X,lc1:%04X-DFFF' % (AM_REQ[0] - 1, AM_REQ[1])
# the tic phase's stack (4.5), the IRQ's, an FCALL across images' cost
TIC_STACK, IRQ_STACK, FCALL_STACK = 160, R.IRQ_STACK, 5
# page 1 below the stack (speed wave 2, part objapi, docs/speed-parts/
# objapi.md): the object API's window code and its descriptors (gobj.s
# pw_go), copied there by go_reset in the tic images and the load image;
# the tic stack (TIC_STACK, the IRQ's included, as gcallgraph.py counts
# it) from the drivers' S ($01EF; the play kernel's is higher) stays above
TIC_PAGE1 = (0x0100, 0x0150)
DRIVER_S = 0xEF
# the bytes a built routine keeps on the stack across its calls, beyond
# their returns (gcallgraph.py --stack; wave 1 as integrated): P_CheckSight's
# waiting children, 2 a level over a 2-byte marker, E1's trees 19 deep at
# most (sight.md R6); the mobj P_SetMobjState and explode keep across an
# action (mobjstate.md); a block iterator's walk across its callback (geom:
# giter.s, 3 bytes)
OWN_STACK = {'p_sight65.s:P_CheckSight': 40, 'p_tick65.s:P_SetMobjState': 2,
             'p_mobj65.s:explode': 2, 'p_map65.s:P_BlockLinesIterator': 3,
             'p_map65.s:P_BlockThingsIterator': 3,
             # wave 3: the things' walk's state and PIT_CheckThing's
             # result across checkThing (checkpos.md R3); the radius
             # attack's block loop across P_BlockThingsIterator, A_Look's
             # type across mi_get and the sound (look.md request 4)
             'p_map65.s:checkPos': 12, 'p_attack65.s:P_RadiusAttack': 10,
             'p_enemy65.s:A_Look': 1,
             # wave 4: the return address of a local jsr (mvNodes, spec,
             # the fogs) under the callees they FCALL (trymove.md R2); the
             # teleport's block loop across P_BlockThingsIterator
             # (teleport.md R3)
             'p_map65.s:P_TryMove': 2,
             'p_spawn65.s:P_NightmareRespawn': 2,
             'p_map65.s:P_TeleportMove': 5,
             # wave 5: the return address of a local jsr under the callees
             # it reaches (player.md R4: pm_thrust, @hurt, pu_run,
             # pu_line, pn_line, pt_mo, ch_mo; xymove.md R4: sm_try;
             # chasemove.md R3: cm_try); a byte pushed across an FCALL
             # (xymove.md R4); the missile kept across checkMissile and
             # P_TryMove (missile.md R3)
             'p_user65.s:P_PlayerThink': 2, 'p_user65.s:movePlayer': 2,
             'p_user65.s:calcHeight': 2, 'p_user65.s:specialSector': 2,
             'p_use65.s:P_UseLines': 2, 'p_use65.s:PTR_UseTraverse': 2,
             'p_use65.s:PTR_NoWayTraverse': 2,
             'p_mobj65.s:slideMove': 2, 'p_mobj65.s:frictionAP': 1,
             'p_mobj65.s:frictionNear': 1, 'p_mobj65.s:bobClip': 1,
             'p_mobj65.s:hitSlideLine': 1,
             'p_spawn65.s:P_SpawnMissile': 2,
             'p_spawn65.s:checkMissile': 2,
             'p_enemy65.s:doNewChaseDir': 2,
             # wave 6: the return address of a local jsr (dr_move, pl_move)
             # under the plane movers and partLight (movers.md request 3);
             # mt_still's return under pl_get (tic.md R3); A_Chase's byte
             # pushed over a call of the object API (chase.md R3)
             'p_doors65.s:T_VerticalDoor': 2, 'p_plats65.s:T_PlatRaise': 2,
             'p_tick65.s:P_MobjThinker': 2, 'p_enemy65.s:A_Chase': 1}

# ---------------------------------------------------------------------------
# The test bank GTEST (test builds, 3.4, 3.6): the schedule (the gametic
# of each frame and its kind: FRONT or FULL), the stream (each tic's
# command and events), the I_GetTime values, the re-key records (one a
# setup), the sound event log and the same-pair hit log (emptied after
# each snapshot), the routine mode's arguments
# ---------------------------------------------------------------------------
# (the final integration: the schedule 0x1000, 1,365 frames, DEMO1's 1,257
# the most; the re-key records 0x2C00, 10 setups, the tour's 9 the most
# (0x1800 held 5); GT_LEVELS the frame block's level fields by map, which
# the driver copies after each load in runs with frames: docs/GAME.md
# "Acceptance")
GT_LAYOUT = [('GT_ARGS', 0x0100), ('GT_SCHEDULE', 0x1000),
             ('GT_STREAMB', 0x5800), ('GT_TIMES', 0x0800),
             ('GT_REKEYS', 0x2C00), ('GT_SOUNDS', 0x0C00),
             ('GT_HITS', 0x0400), ('GT_RECORD', 0x0800),
             ('GT_LEVELS', 0x0100)]
GTB = R.allocate(GT_LAYOUT, LL.ROOM[0], LL.ROOM[1])
GT_LEVEL_RECORD = 7     # a map's NUMNODES 2, NVERT 2, SKYBANK, SKYLO, SKYHI
SOUND_EVENT, HIT_EVENT = 6, 6       # (tic 2, kind 1, sound 1, origin 2);
                                    #   (tic 2, t1 2, t2 2)
REKEY_RECORD = 6 + 2 * LL.POOL_MAX  # map, CS_PREV1, CS_PREV2, 1 pad, then
                                    #   the hint by pool slot
# the driver's modes (gdriver.s DM_*)
MODES = {'LOCKSTEP': 1, 'ROUTINE': 2, 'ROUTINE_LOAD': 3, 'LOADTEST': 4,
         'SELFTEST': 5}
# the frame kinds of the schedule (FRAME_FULL + 1: a full frame with the
# driver's snapshot points); the kind byte's bit 7 (FRAME_STRIP): the
# display's message strip, viewtop VIEW_STRIPTOP for the frame, else none
# ($FF: upstream's -1; d_main65.s dmLevel78): the final integration
FRAME_NONE, FRAME_FRONT, FRAME_FULL = 0, 1, 2
FRAME_KIND, FRAME_STRIP, VIEW_STRIPTOP = 0x03, 0x80, 9
# gameaction values (g_game65.s's ga_*: CONST_GA_*), the ones the load
# protocol continues
LOAD_ACTIONS = ('GA_LOADLEVEL', 'GA_NEWGAME', 'GA_PLAYDEMO',
                'GA_WORLDDONE')
GT_LOAD = 2                         # G_Ticker's "a load" return (gt_tick)

# ---------------------------------------------------------------------------
# The part table (docs/GAME.md 2.4), keyed file:label: each part's wave,
# upstream's bytes and its native budget, its routines (the entries and
# the labels of the table's rows) and helpers. gcallgraph.py --check
# holds it to the rule of 2.2.
# ---------------------------------------------------------------------------
PARTS: List[Dict[str, Any]] = [
    {'name': 'geom', 'wave': 1, 'up': 1707, 'native': 2200,
     'routines': ['p_map65.s:P_PointOnLineSide',
         'p_map65.s:P_BoxOnLineSide', 'p_map65.s:P_LineOpening',
         'p_map65.s:P_LineOpeningXY', 'p_map65.s:pointSector',
         'p_map65.s:posMul', 'p_map65.s:sectorFloor',
         'p_map65.s:baseFloor', 'p_map65.s:baseFloorL',
         'p_map65.s:baseLite', 'p_map65.s:P_BlockLinesIterator',
         'p_map65.s:P_BlockThingsIterator', 'p_map65.s:blockRange'],
     'helpers': ['p_map65.s:argLine4', 'p_map65.s:box1', 'p_map65.s:box2',
         'p_map65.s:posPub', 'p_map65.s:walk1', 'p_map65.s:walk2',
         'p_map65.s:callLN', 'p_map65.s:callLN2']},
    {'name': 'mobjstate', 'wave': 1, 'up': 1397, 'native': 1900,
     'routines': ['p_map65.s:P_UnsetThingPosition',
         'p_map65.s:P_DelSeclist', 'p_map65.s:P_DelSecnode',
         'p_think65.s:P_RemoveThinker', 'p_think65.s:P_RemoveThing',
         'p_think65.s:P_RemoveThinkerDelayed',
         'p_think65.s:P_RemoveThingDelayed', 'p_think65.s:P_NextThinker',
         'p_spawn65.s:P_RemoveMobj', 'p_spawn65.s:poolFree',
         'r_list65.s:linkRemove', 'p_tick65.s:P_SetMobjState',
         'p_tick65.s:rocketCheat', 'p_tick65.s:P_MobjBrainlessThinker',
         'p_mobj65.s:P_ExplodeMissile', 'p_mobj65.s:explode',
         'p_mobj65.s:P_MobjIsPlayer'],
     'helpers': ['p_map65.s:unlist', 'p_map65.s:link',
         'p_map65.s:mvSector', 'p_map65.s:mvBlock', 'p_map65.s:blockOf',
         'p_map65.s:snLink', 'p_think65.s:unlink', 'p_spawn65.s:rmArg']},
    {'name': 'secfind', 'wave': 1, 'up': 1363, 'native': 1800,
     'routines': ['p_spec65.s:getNextSector',
         'p_spec65.s:P_FindLowestFloorSurrounding',
         'p_spec65.s:P_FindHighestFloorSurrounding',
         'p_spec65.s:P_FindLowestCeilingSurrounding',
         'p_spec65.s:P_FindSectorFromLineTag', 'p_spec65.s:P_CheckTag',
         'p_spec65.s:P_UpdateSpecials', 'p_spec65.s:T_Scroll',
         'p_floor65.s:P_FindNextHighestFloor', 'p_lights65.s:T_LightFlash',
         'p_lights65.s:T_StrobeFlash', 'p_lights65.s:T_Glow',
         'p_lights65.s:EV_LightTurnOn'],
     'helpers': ['p_lights65.s:secArg', 'p_lights65.s:ltSector',
         'p_lights65.s:nextSector', 'p_spec65.s:sideSector',
         'p_spec65.s:secArg', 'p_spec65.s:lineOf', 'p_spec65.s:buttonDone',
         'p_spec65.s:mod3', 'p_floor65.s:nextOther',
         'p_floor65.s:aboveCurrent', 'p_spec65.s:around']},
    {'name': 'flow', 'wave': 1, 'up': 1800, 'native': 2300,
     'routines': ['g_game65.s:loadLevel', 'g_game65.s:victory',
         'g_game65.s:doNewGame', 'g_game65.s:doWorldDone',
         'g_game65.s:doPlayDemo', 'g_game65.s:doCompleted',
         'g_game65.s:doLoadLevel', 'g_game65.s:G_ExitLevel',
         'g_game65.s:G_SecretExitLevel', 'g_game65.s:G_WorldDone',
         'g_game65.s:G_DeferedInitNew', 'g_game65.s:G_ReloadDefaults',
         'g_game65.s:initNew', 'g_game65.s:readDemoTiccmd',
         'g_game65.s:G_DeferedPlayDemo', 'g_game65.s:readDemoHeader',
         'g_game65.s:checkOverrun', 'g_game65.s:G_CheckDemoStatus',
         'wi_stuff65.s:WI_Start', 'wi_stuff65.s:WI_End',
         'wi_stuff65.s:WI_checkForAccelerate', 'wi_stuff65.s:WI_Ticker',
         'st_stuff65.s:ST_Ticker', 'hu_stuff65.s:HU_Ticker'],
     'helpers': ['g_game65.s:signLong', 'g_game65.s:div1000']},
    {'name': 'sight', 'wave': 1, 'up': 2738, 'native': 3600,
     'routines': ['p_sight65.s:P_CheckSight', 'p_sight65.s:zSetup',
         'p_sight65.s:sightSlope', 'p_sight65.s:interceptFrac',
         'p_sight65.s:opening'],
     'helpers': ['p_sight65.s:hintOf', 'p_sight65.s:half',
         'p_sight65.s:qbd', 'p_sight65.s:nodeDone', 'p_sight65.s:lineDone',
         'p_sight65.s:pick', 'p_sight65.s:sameHeight', 'p_sight65.s:st32',
         'p_sight65.s:shr8V', 'p_sight65.s:smul48', 'p_sight65.s:bitTab']},
    {'name': 'tracel', 'wave': 2, 'up': 2136, 'native': 2800,
     'routines': ['p_trace65.s:PIT_AddLineIntercepts',
         'p_trace65.s:interceptVector3', 'p_trace65.s:divlineSide',
         'p_trace65.s:addIntercept', 'p_trace65.s:icInsert',
         'p_trace65.s:ivSetup'],
     'helpers': ['p_trace65.s:ivTest', 'p_trace65.s:ivProd',
         'p_trace65.s:ivAxis', 'p_trace65.s:lineCross',
         'p_trace65.s:lineCrossL', 'p_trace65.s:vtxSlow',
         'p_trace65.s:vtxSlowL', 'p_trace65.s:vtxSlowR',
         'p_trace65.s:icInsertL', 'p_trace65.s:gOf', 'p_trace65.s:smul',
         'p_trace65.s:vsC']},
    {'name': 'damage', 'wave': 2, 'up': 1363, 'native': 1800,
     'routines': ['p_inter65.s:P_DamageMobj', 'p_inter65.s:killMobj',
         'p_pspr65.s:P_DropWeapon', 'p_pspr65.s:lowerWeapon',
         'p_pspr65.s:wInfo', 'p_pspr65.s:wInfoOf'],
     'helpers': ['p_inter65.s:targetArg', 'p_inter65.s:setTarget',
         'p_inter65.s:setState', 'p_inter65.s:lastEnemy',
         'p_inter65.s:thrust', 'p_inter65.s:addThrust',
         'p_inter65.s:playerDamage']},
    {'name': 'pickup', 'wave': 2, 'up': 1611, 'native': 2100,
     'routines': ['p_inter65.s:P_TouchSpecialThing', 'p_inter65.s:pickTab',
         'p_inter65.s:P_GivePower', 'm_cheat65.s:C_Responder',
         'm_cheat65.s:power', 'm_cheat65.s:giveAmmo'],
     'helpers': ['p_inter65.s:specialArg', 'p_inter65.s:playerMo',
         'p_inter65.s:giveBody', 'p_inter65.s:giveAmmo',
         'p_inter65.s:giveWeapon', 'p_inter65.s:givePower']},
    {'name': 'lines', 'wave': 2, 'up': 1042, 'native': 1400,
     'routines': ['p_switch65.s:P_CrossSpecialLine',
         'p_switch65.s:P_UseSpecialLine', 'p_switch65.s:findSpecial',
         'p_switch65.s:P_ChangeSwitchTexture', 'p_switch65.s:usetab',
         'p_switch65.s:crosstab'],
     'helpers': ['p_switch65.s:swLine', 'p_switch65.s:swSide',
         'p_switch65.s:isPlayer']},
    {'name': 'spawn', 'wave': 2, 'up': 842, 'native': 1100,
     'routines': ['p_spawn65.s:P_SpawnPuff', 'p_spawn65.s:P_SpawnBlood',
         'p_attack65.s:P_IsAttackRangeMeleeRange',
         'p_mobj65.s:P_ZMovement', 'p_mobj65.s:missileHit',
         'p_mobj65.s:shr3', 'p_mobj65.s:isPlayer'],
     'helpers': ['p_spawn65.s:moArg', 'p_spawn65.s:saveXYZ',
         'p_spawn65.s:zNoise', 'p_spawn65.s:spawnXYZ',
         'p_spawn65.s:ticsNoise', 'p_spawn65.s:thArg']},
    {'name': 'tracet', 'wave': 3, 'up': 2189, 'native': 2800,
     'routines': ['p_trace65.s:traceLines', 'p_trace65.s:traceThings',
         'p_trace65.s:sideSetup', 'p_trace65.s:longTrace',
         'p_trace65.s:ptT1', 'p_trace65.s:ptT2', 'p_trace65.s:vsPatch',
         'p_trace65.s:ptPatch'],
     'helpers': ['p_trace65.s:thFast', 'p_trace65.s:thFastL',
         'p_trace65.s:thSide']},
    {'name': 'checkpos', 'wave': 3, 'up': 2019, 'native': 2600,
     'routines': ['p_map65.s:P_CheckPosition', 'p_map65.s:checkPos',
         'p_map65.s:setBox', 'p_map65.s:setBoxL', 'p_map65.s:above',
         'p_map65.s:checkThing', 'p_map65.s:lineBlocks',
         'p_map65.s:lCross', 'p_map65.s:walkRange', 'p_map65.s:loadRad',
         'p_map65.s:cpCopy', 'p_map65.s:ps32'],
     'helpers': []},
    {'name': 'pspr', 'wave': 3, 'up': 894, 'native': 1200,
     'routines': ['p_pspr65.s:P_MovePsprites', 'p_pspr65.s:tickPsprite',
         'p_pspr65.s:A_WeaponReady', 'p_pspr65.s:A_ReFire',
         'p_pspr65.s:A_Lower', 'p_pspr65.s:A_GunFlash',
         'p_pspr65.s:A_Light0', 'p_pspr65.s:A_Light1',
         'p_pspr65.s:A_Light2', 'p_pspr65.s:fireWeapon',
         'p_pspr65.s:checkAmmo', 'p_pspr65.s:recursiveSound',
         'p_pspr65.s:P_CheckAmmo'],
     'helpers': ['p_pspr65.s:startSound', 'p_pspr65.s:argMo',
         'p_pspr65.s:setMoState', 'p_pspr65.s:signExt4',
         'p_pspr65.s:signExt0', 'p_pspr65.s:fireSomething']},
    {'name': 'evworld', 'wave': 3, 'up': 1223, 'native': 1600,
     'routines': ['p_doors65.s:EV_DoDoor', 'p_doors65.s:EV_VerticalDoor',
         'p_doors65.s:newDoor', 'p_plats65.s:EV_DoPlat'],
     'helpers': ['p_plats65.s:platArg', 'p_plats65.s:sectorArg',
         'p_plats65.s:platSound', 'p_plats65.s:setHigh',
         'p_plats65.s:setLow', 'p_plats65.s:plSec', 'p_doors65.s:doorArg',
         'p_doors65.s:setDir', 'p_doors65.s:topLowest',
         'p_doors65.s:setTop', 'p_doors65.s:edLine', 'p_doors65.s:edSec',
         'p_doors65.s:edSound', 'p_doors65.s:sectorArg']},
    {'name': 'look', 'wave': 3, 'up': 1729, 'native': 2300,
     'routines': ['p_enemy65.s:A_Look', 'p_enemy65.s:lookForPlayers',
         'p_enemy65.s:behindFast', 'p_enemy65.s:A_FaceTarget',
         'p_enemy65.s:checkMeleeRange', 'p_enemy65.s:checkMissileRange',
         'p_enemy65.s:P_CheckMeleeRange',
         'p_enemy65.s:P_CheckMissileRange', 'p_enemy65.s:A_Scream',
         'p_enemy65.s:A_XScream', 'p_enemy65.s:A_Pain',
         'p_enemy65.s:A_Fall', 'p_enemy65.s:A_PlayerScream',
         'p_attack65.s:P_RadiusAttack', 'p_attack65.s:PIT_RadiusAttack'],
     'helpers': ['p_attack65.s:blockPair', 'p_attack65.s:absDelta',
         'p_enemy65.s:angleToAT', 'p_enemy65.s:distanceAT',
         'p_enemy65.s:faceTarget', 'p_enemy65.s:loadTarget',
         'p_enemy65.s:randMod', 'p_enemy65.s:startSound']},
    {'name': 'path', 'wave': 4, 'up': 1239, 'native': 1600,
     'routines': ['p_path65.s:P_PathTraverse', 'p_path65.s:ptBody',
         'p_path65.s:traverseTo', 'p_path65.s:ptStuck',
         'p_path65.s:offLine', 'p_path65.s:axisStep', 'p_path65.s:early'],
     'helpers': ['p_path65.s:fromOrigin', 'p_path65.s:a1Shr7',
         'p_path65.s:callTrav']},
    {'name': 'trymove', 'wave': 4, 'up': 1164, 'native': 1500,
     'routines': ['p_map65.s:P_TryMove', 'p_map65.s:overStep',
         'p_map65.s:mvNodes', 'p_map65.s:spec', 'p_map65.s:lessHeight',
         'p_map65.s:specLine', 'p_spawn65.s:P_NightmareRespawn'],
     'helpers': ['p_spawn65.s:nmArg', 'p_spawn65.s:nmXY',
         'p_spawn65.s:subFloor', 'p_spawn65.s:fog']},
    {'name': 'planes', 'wave': 4, 'up': 1222, 'native': 1600,
     'routines': ['p_floor65.s:T_MovePlaneFloor',
         'p_floor65.s:T_MovePlaneCeiling', 'p_floor65.s:checkSector',
         'p_floor65.s:changeSector', 'p_floor65.s:heightClip',
         'p_floor65.s:T_MoveFloor'],
     'helpers': ['p_floor65.s:restore', 'p_floor65.s:planeArgs',
         'p_floor65.s:minusSpeed', 'p_floor65.s:plusSpeed',
         'p_floor65.s:saveLast', 'p_floor65.s:setPlaneT',
         'p_floor65.s:secArg', 'p_floor65.s:loadNode',
         'p_floor65.s:nodeArg', 'p_floor65.s:thingArg',
         'p_floor65.s:floorArg', 'p_floor65.s:floorSector',
         'p_floor65.s:floorSpeed', 'p_floor65.s:sectorSound']},
    {'name': 'evfloor', 'wave': 4, 'up': 1159, 'native': 1500,
     'routines': ['p_floor65.s:EV_DoFloor', 'p_floor65.s:EV_BuildStairs',
         'p_floor65.s:EV_DoDonut', 'p_floor65.s:newFloor'],
     'helpers': ['p_floor65.s:lineStart', 'p_floor65.s:nextTagged',
         'p_floor65.s:secOf', 'p_floor65.s:secArg2',
         'p_floor65.s:floorField', 'p_floor65.s:floorDown',
         'p_floor65.s:floorUp', 'p_floor65.s:floorArgFL',
         'p_floor65.s:setDest', 'p_floor65.s:sameAsFloor',
         'p_floor65.s:underCeiling', 'p_floor65.s:stairStep',
         'p_floor65.s:nextStep', 'p_floor65.s:lineSector',
         'p_floor65.s:sectorNum', 'p_floor65.s:s2Arg', 'p_floor65.s:s3Arg',
         'p_floor65.s:s3Floor', 'p_floor65.s:halfSpeed']},
    {'name': 'teleport', 'wave': 4, 'up': 1130, 'native': 1500,
     'routines': ['p_telept65.s:EV_Teleport', 'p_map65.s:P_TeleportMove',
         'p_map65.s:stompThing'],
     'helpers': ['p_map65.s:tpThing', 'p_map65.s:farFrom',
         'p_telept65.s:fogSound', 'p_telept65.s:times20',
         'p_telept65.s:thingArg', 'p_telept65.s:destArg',
         'p_telept65.s:destination']},
    {'name': 'attack', 'wave': 5, 'up': 1877, 'native': 2500,
     'routines': ['p_attack65.s:P_AimLineAttack',
         'p_attack65.s:PTR_AimTraverse', 'p_attack65.s:P_LineAttack',
         'p_attack65.s:PTR_ShootTraverse', 'p_attack65.s:shootSpecial',
         'p_attack65.s:puffPos'],
     'helpers': ['p_attack65.s:traceSetup', 'p_attack65.s:endPoint',
         'p_attack65.s:traceRun', 'p_attack65.s:loadIntercept',
         'p_attack65.s:opening', 'p_attack65.s:rangeDist',
         'p_attack65.s:rangeMul', 'p_attack65.s:lineSectors',
         'p_attack65.s:sideAddr', 'p_attack65.s:sideSectors',
         'p_attack65.s:sectorsDiffer', 'p_attack65.s:shootable',
         'p_attack65.s:rawSlope', 'p_attack65.s:thingHead',
         'p_attack65.s:thingFoot', 'p_attack65.s:thingPtr',
         'p_attack65.s:mul3', 'p_attack65.s:thingTop',
         'p_attack65.s:thingTopRaw', 'p_attack65.s:ceilBelowZ',
         'p_attack65.s:thingBottom', 'p_attack65.s:thingBottomRaw',
         'p_attack65.s:slopeTo', 'p_attack65.s:slopeOf',
         'p_attack65.s:traceAt', 'p_attack65.s:puffArgs',
         'p_attack65.s:spawnPuff']},
    {'name': 'player', 'wave': 5, 'up': 2131, 'native': 2800,
     'routines': ['p_user65.s:P_PlayerThink', 'p_user65.s:fixedSquare',
         'p_user65.s:specialSector', 'p_user65.s:movePlayer',
         'p_user65.s:calcHeight', 'p_user65.s:angleToAttacker',
         'p_use65.s:P_UseLines', 'p_use65.s:PTR_UseTraverse',
         'p_use65.s:PTR_NoWayTraverse'],
     'helpers': ['p_use65.s:times64', 'p_use65.s:useRun',
         'p_use65.s:useArg', 'p_use65.s:lineArg', 'p_user65.s:countDown',
         'p_user65.s:blink', 'p_user65.s:argMo', 'p_user65.s:moSector',
         'p_user65.s:onGround', 'p_user65.s:bobAndThrust',
         'p_user65.s:addMom', 'p_user65.s:thrustMul', 'p_user65.s:hurt32']},
    {'name': 'xymove', 'wave': 5, 'up': 2367, 'native': 3100,
     'routines': ['p_mobj65.s:P_XYMovement', 'p_mobj65.s:slideMove',
         'p_mobj65.s:PTR_SlideTraverse', 'p_mobj65.s:hitSlideLine'],
     'helpers': ['p_mobj65.s:clampMove', 'p_mobj65.s:isBig',
         'p_mobj65.s:wholeMove', 'p_mobj65.s:halfMove',
         'p_mobj65.s:skyHit', 'p_mobj65.s:quarterOut', 'p_mobj65.s:slow',
         'p_mobj65.s:frictionAP', 'p_mobj65.s:frictionNear',
         'p_mobj65.s:friction', 'p_mobj65.s:corners',
         'p_mobj65.s:slideTrace', 'p_mobj65.s:bestMul',
         'p_mobj65.s:addCoord', 'p_mobj65.s:bobClip', 'p_mobj65.s:labs']},
    {'name': 'missile', 'wave': 5, 'up': 593, 'native': 800,
     'routines': ['p_spawn65.s:P_SpawnMissile', 'p_spawn65.s:checkMissile'],
     'helpers': ['p_spawn65.s:srcArg', 'p_spawn65.s:srcAbove',
         'p_spawn65.s:seeTarget', 'p_spawn65.s:thSpeed',
         'p_spawn65.s:destDelta', 'p_spawn65.s:angleMom',
         'p_spawn65.s:speedMom', 'p_spawn65.s:halfMom']},
    {'name': 'chasemove', 'wave': 5, 'up': 2211, 'native': 2900,
     'routines': ['p_enemy65.s:pMove', 'p_enemy65.s:P_TryWalk',
         'p_enemy65.s:P_NewChaseDir', 'p_enemy65.s:doNewChaseDir',
         'p_enemy65.s:avoidDropoff', 'p_enemy65.s:PIT_AvoidDropoff',
         'p_enemy65.s:speedStep'],
     'helpers': ['p_enemy65.s:mulSpeed', 'p_enemy65.s:umul16x',
         'p_enemy65.s:speedTab', 'p_enemy65.s:speeds',
         'p_enemy65.s:tryWalk', 'p_enemy65.s:newChaseDir',
         'p_enemy65.s:setDir', 'p_enemy65.s:absGreater',
         'p_enemy65.s:absD', 'p_enemy65.s:boxPlus', 'p_enemy65.s:boxMinus',
         'p_enemy65.s:blockOf', 'p_enemy65.s:boxAbove',
         'p_enemy65.s:boxBelow', 'p_enemy65.s:sideFloor',
         'p_enemy65.s:signed', 'p_enemy65.s:times32']},
    {'name': 'movers', 'wave': 6, 'up': 1094, 'native': 1400,
     'routines': ['p_doors65.s:T_VerticalDoor', 'p_doors65.s:partLight',
         'p_plats65.s:T_PlatRaise'],
     'helpers': ['p_plats65.s:movePlat', 'p_plats65.s:stopWait',
         'p_plats65.s:waitStatus', 'p_plats65.s:setStatus',
         'p_doors65.s:doorSound', 'p_doors65.s:moveCeiling',
         'p_doors65.s:dlSec', 'p_doors65.s:mulExt']},
    {'name': 'wfire', 'wave': 6, 'up': 964, 'native': 1300,
     'routines': ['p_spawn65.s:P_SpawnPlayerMissile',
         'p_pspr65.s:A_FirePistol', 'p_pspr65.s:A_FireShotgun',
         'p_pspr65.s:A_FireCGun', 'p_pspr65.s:A_FireMissile',
         'p_pspr65.s:A_Punch', 'p_pspr65.s:A_Saw', 'p_pspr65.s:gunShot',
         'p_pspr65.s:bulletSlope'],
     'helpers': ['p_pspr65.s:meleeAngle', 'p_pspr65.s:spread',
         'p_pspr65.s:meleeAttack', 'p_pspr65.s:angleToTarget',
         'p_pspr65.s:randMod', 'p_pspr65.s:useAmmo', 'p_pspr65.s:aimAt',
         'p_pspr65.s:notRefire', 'p_spawn65.s:aim']},
    {'name': 'tic', 'wave': 6, 'up': 1155, 'native': 1500,
     'routines': ['g_game65.s:G_Ticker', 'p_map65.s:P_MapEnd',
         'p_think65.s:P_Ticker', 'p_tick65.s:P_RunThinkers',
         'p_tick65.s:P_MobjThinker'],
     'helpers': ['p_tick65.s:mobjArg', 'p_tick65.s:stillMobjThinker']},
    {'name': 'chase', 'wave': 6, 'up': 1400, 'native': 1800,
     'routines': ['p_enemy65.s:A_Chase', 'p_enemy65.s:A_PosAttack',
         'p_enemy65.s:A_SPosAttack', 'p_enemy65.s:A_TroopAttack',
         'p_enemy65.s:A_SargAttack', 'p_enemy65.s:A_CyberAttack',
         'p_enemy65.s:A_BruisAttack', 'p_enemy65.s:A_Explode',
         'p_enemy65.s:A_BossDeath'],
     'helpers': ['p_enemy65.s:lineAttack', 'p_enemy65.s:aimLine',
         'p_enemy65.s:spreadAngle', 'p_enemy65.s:damageTarget',
         'p_enemy65.s:spawnMissile']},
]
PART_NAMES = [p['name'] for p in PARTS]
# the line special handlers of p_switch65.s (LSTAB's entries): each one
# the owner of the routine it calls (2.2)
LSTAB_OWNERS = {'p_switch65.s:lnDoor': 'evworld',
                'p_switch65.s:lnPlat': 'evworld',
                'p_switch65.s:lnVDoor': 'evworld',
                'p_switch65.s:lnFloor': 'evfloor',
                'p_switch65.s:lnStairs': 'evfloor',
                'p_switch65.s:lnDonut': 'evfloor',
                'p_switch65.s:lnLight': 'secfind',
                'p_switch65.s:lnTele': 'teleport',
                'p_switch65.s:lnExit': 'lines'}
# the labels of the table's rows that are tables, cases of a jump table or
# templates rather than callable routines, and the helpers the rows do not
# name: each with the owner of the routine that uses it
EXTRA_LABELS = dict(LSTAB_OWNERS, **{
    'g_game65.s:actions': 'tic',                # G_Ticker's action table
    'p_inter65.s:pickTab_end': 'pickup', 'p_inter65.s:pkAmmo': 'pickup',
    'p_inter65.s:pkArmor': 'pickup', 'p_inter65.s:pkArmorBonus': 'pickup',
    'p_inter65.s:pkBackpack': 'pickup', 'p_inter65.s:pkBody': 'pickup',
    'p_inter65.s:pkCard': 'pickup', 'p_inter65.s:pkClip': 'pickup',
    'p_inter65.s:pkHealthBonus': 'pickup', 'p_inter65.s:pkPower': 'pickup',
    'p_inter65.s:pkSoul': 'pickup', 'p_inter65.s:pkWeapon': 'pickup',
    'm_cheat65.s:cheats': 'pickup',             # C_Responder's table
    'p_enemy65.s:bfD0': 'look', 'p_enemy65.s:bfD1': 'look',
    'p_enemy65.s:bfD2': 'look', 'p_enemy65.s:bfD3': 'look',
    'p_enemy65.s:bfD4': 'look', 'p_enemy65.s:bfD5': 'look',
    'p_enemy65.s:bfD6': 'look', 'p_enemy65.s:bfD7': 'look',
    'p_enemy65.s:SPD47': 'chasemove',           # speedStep's
    'p_sight65.s:straceDone': 'sight',          # lineDone's
    'p_switch65.s:spectab': 'lines', 'p_switch65.s:usetab_end': 'lines',
    'p_switch65.s:crosstab_end': 'lines',
    'p_trace65.s:tlP1': 'tracet', 'p_trace65.s:tlP2': 'tracet',
    'p_trace65.s:thP': 'tracet', 'p_trace65.s:gtP1': 'tracet',
    'p_trace65.s:gtP2': 'tracet',
    # P_UpdateAnimatedFlat (r_data65.s, a unit the graph does not read):
    # secfind's (GAME.md 0.1: NUKAGE)
    '?:P_UpdateAnimatedFlat': 'secfind'})
for _k, _o in EXTRA_LABELS.items():
    _p = next(p for p in PARTS if p['name'] == _o)
    if _k not in _p['routines'] + _p['helpers']:
        _p['helpers'].append(_k)

# Milestone 9's game core (docs/GAME.md 0.1), with the skeleton's
# extensions: the upstream routines it implements (their helpers inside
# it), the labels each one's native code takes in (core_inlines) and the
# routines of parts it calls (CORE_CALLS, through FCALL)
CORE = ['p_spawn65.s:P_SpawnMapThing', 'p_spawn65.s:P_SpawnMobj',
        'p_spawn65.s:newMobj', 'p_spawn65.s:poolTake',
        'p_spawn65.s:clearMo', 'p_spawn65.s:spawnPlayer',
        'p_map65.s:P_SetThingPosition', 'p_map65.s:P_CreateSecNodeList',
        'p_map65.s:getSectors', 'p_map65.s:addSecnode',
        'p_map65.s:addSecnodeL', 'p_map65.s:newSecnode',
        'p_think65.s:P_AddThinker', 'p_spec65.s:P_SpawnSpecials',
        'p_lights65.s:P_SpawnLightFlash', 'p_lights65.s:P_SpawnStrobeFlash',
        'p_lights65.s:P_SpawnGlowingLight',
        'p_lights65.s:P_FindMinSurroundingLight',
        'g_game65.s:G_PlayerReborn', 'p_pspr65.s:P_SetupPsprites',
        'p_pspr65.s:bringUpWeapon', 'p_pspr65.s:setPsprite',
        'p_pspr65.s:A_Raise', 'r_list65.s:addIfFunc',
        # the zone's sector-node pools freed at a load (lsetup.s gt_init)
        'p_map65.s:P_SetSecnodeFirstpoolToNull', 'p_map65.s:nodeAt',
        'p_map65.s:nodeAtY',
        # upstream's dispatch helpers: natively gcall.s's DCALL (2.2)
        'p_tick65.s:callFn', 'p_pspr65.s:callAction']
CORE_CALLS = ['p_map65.s:P_DelSecnode']
CORE_INLINES = {
    # P_CreateSecNodeList's walk is gpos.s's own (LEVELS.md 2.4): the box,
    # lineBlocks' PIT_GetSectors mode and its LR_USE path, walkRange
    'p_map65.s:P_CreateSecNodeList': ('p_map65.s:setBoxL',
                                      'p_map65.s:lineBlocks',
                                      'p_map65.s:setBox',
                                      'p_map65.s:walkRange'),
    'p_map65.s:P_SetThingPosition': ('p_map65.s:link',),
    'p_map65.s:newSecnode': ('p_map65.s:nodeAt', 'p_map65.s:nodeAtY'),
    # upstream's argument and table helpers, which the core's own code
    # does in place
    'p_spawn65.s:P_SpawnMapThing': ('p_spawn65.s:thArg',),
    'p_spawn65.s:P_SpawnMobj': ('p_spawn65.s:moArg',),
    'p_spec65.s:P_SpawnSpecials': ('p_spec65.s:secArg',),
    'p_pspr65.s:bringUpWeapon': ('p_pspr65.s:startSound',
                                 'p_pspr65.s:wInfoOf'),
    'p_pspr65.s:A_Raise': ('p_pspr65.s:wInfo',),
}


def core_inlines(core: str, callee: str) -> bool:
    return callee in CORE_INLINES.get(core, ())


# milestone 6's math: by unit and by name (cal_integer.s is never read:
# its routines are math by their names at the call sites)
MATH_UNITS = ('m_fixed65.s', 'm_random65.s', 'm_recip65.s')
MATH_NAMES = ('FixedMul', 'FixedDiv', 'FixedMul3216', 'FixedApproxDiv',
              'FixedMulAngle', 'IIGS_MulLo16', 'umul16', 'umul16lo',
              '_Mul16', '_Mul32', '_UDivMod16', '_UDivMod32', '_Div16',
              '_Div32', '_Mod16', 'P_Random', 'M_Random', 'M_ClearRandom',
              'P_AproxDistance', 'R_PointToAngle3', 'R_PointToAngle2',
              'FixedReciprocal', 'FixedReciprocalSmall',
              'R_PointInSubsector', 'finesine', 'finecosine', 'memset')
# the hooks of ghook.s (3.4), by name: the sound events, the 2D screens'
# starts and tickers, the zone's allocators (the native pools), I_Error and
# I_GetTime; W_StartInter's pictures and music (then flow's WI_Start),
# W_StartFinale and F_Ticker (stops); P_UpdateAnimatedFlat is part
# secfind's (P_UpdateSpecials writes NUKAGE)
HOOK_NAMES = ('S_StartSound', 'S_StartSound2', 'S_StopSound', 'AM_Stop',
              'ST_Start', 'HU_Start', 'AM_Ticker', 'F_LoadScreen',
              'Z_CheckHeap', 'D_AdvanceDemo', 'D_PageTicker',
              'W_StartInter', 'W_StartFinale', 'F_Ticker', 'I_Error',
              'I_GetTime', 'Z_MallocLevel', 'Z_CallocLevel',
              'Z_CallocLevSpec', 'Z_Free', 'Z_MallocStatic')
HOOKS: List[str] = []
# named out (GAME.md 0.1), by file:label or by name, with the reason
OUT_NAMES = {
    # the dead path guard: `early` branches over its only call (p_path65.s
    # :612-614)
    'guardL': 'the dead path guard', 'gRun': 'the dead path guard',
    'gBlk': 'the dead path guard', 'gBlockL': 'the dead path guard',
    'gBlockW': 'the dead path guard', 'gCheck': 'the dead path guard',
    'gNewId': 'the dead path guard', 'gwMiss': 'the dead path guard',
    'gwList': 'the dead path guard', 'gBlockT': 'the dead path guard',
    # the saves: milestone 11
    'doLoadGame': 'milestone 11 (saves)', 'doSaveGame':
    'milestone 11 (saves)', 'G_UpdateSaveGameStrings':
    'milestone 11 (saves)', 'slotOffset': 'milestone 11 (saves)',
    'slotSave': 'milestone 11 (saves)',
    # the level load (doLoadLevel's bmLoad): milestone 9's native load,
    # which the driver runs (the load protocol, 3.4)
    'bmLoad': 'milestone 9 (the load: the load protocol)',
    'bmDone': 'milestone 9', 'bmDiskAsk': 'milestone 9',
    'bmDiskOff': 'milestone 9', 'bmDiskOn': 'milestone 9',
    'bmSignLoading': 'milestone 9', 'bmSignOff': 'milestone 9',
    'bmSignSaving': 'milestone 11 (saves)',
    'P_SetupLevel': 'milestone 9 (nl_setup)',
    'W_LoadSet': 'milestone 9', 'W_ZeroBank': 'milestone 9',
    'musLoad': 'milestone S4 (music)',
    # the status bar's face and the 2D screens (ST_Ticker's game effect is
    # flow's st_tick: M_Random)
    'updateFace': 'milestone 11 (the status bar)',
    'ouch': 'milestone 11 (the status bar)',
    'muchPain': 'milestone 11 (the status bar)',
    'turnHead': 'milestone 11 (the status bar)',
    'painOffset': 'milestone 11 (the status bar)',
    'tallNum': 'milestone 11 (the status bar)',
    'readyNum': 'milestone 11 (the status bar)',
    'mulXY': 'milestone 11 (the status bar)',
    'printf': 'milestone 11', 'IIGS_CopyHuge': 'milestone 11',
    'I_SetPalette': 'milestone 11', 'W_GetLumpByNum': 'milestone 11',
    'W_GetNumForName': 'milestone 11', 'W_LumpLength': 'milestone 11',
    'R_GetTexture': 'every texture is resident (LEVELS.md 1.2)',
    'R_CheckTextureNumForName': 'every texture is resident',
    'G_BuildTiccmd': 'milestone 11 (input)',
}
OUT: Dict[str, str] = {}
# the dispatch tables (2.2): name -> the dispatchers and the targets
# (file:label); ACTTAB's targets are the states' actions (info65.s, in
# order) and A_CyberAttack (the rocket cheat)
DISPATCH = {
    'ACTTAB': {'dispatchers': ['p_tick65.s:P_SetMobjState',
                               'p_pspr65.s:setPsprite'],
               'targets': 'actions'},
    'THTAB': {'dispatchers': ['p_tick65.s:P_RunThinkers'],
              'targets': [f for f in LL.FUNCS[1:-1]]},
    'ITTAB': {'dispatchers': ['p_map65.s:P_BlockLinesIterator',
                              'p_map65.s:P_BlockThingsIterator'],
              'targets': ['p_trace65.s:PIT_AddLineIntercepts',
                          'p_enemy65.s:PIT_AvoidDropoff',
                          'p_attack65.s:PIT_RadiusAttack',
                          'p_map65.s:stompThing']},
    'TRVTAB': {'dispatchers': ['p_path65.s:P_PathTraverse'],
               'targets': ['p_attack65.s:PTR_AimTraverse',
                           'p_attack65.s:PTR_ShootTraverse',
                           'p_mobj65.s:PTR_SlideTraverse',
                           'p_use65.s:PTR_UseTraverse',
                           'p_use65.s:PTR_NoWayTraverse']},
    'LSTAB': {'dispatchers': ['p_switch65.s:findSpecial',
                              'p_switch65.s:P_CrossSpecialLine',
                              'p_switch65.s:P_UseSpecialLine'],
              'targets': list(LSTAB_OWNERS)},
}
# the harness's own entries (3.5): the recording callback and traverser
HARNESS_ENTRIES = {'ITTAB': 'gt_record_it', 'TRVTAB': 'gt_record_trv'}


def dispatch_entries(graph=None) -> Dict[str, List[str]]:
    """Each table's targets in their order (an entry's number is its index
    + 1; 0 is none)."""
    out: Dict[str, List[str]] = {}
    for t, d in DISPATCH.items():
        if d['targets'] == 'actions':
            names = list(graph.states_actions) if graph is not None else []
            if 'A_CyberAttack' not in names:
                names.append('A_CyberAttack')
            keys = []
            for n in names:
                found = [k for k in (graph.heads if graph else {})
                         if k.endswith(':' + n)]
                keys.append(found[0] if len(found) == 1 else '?:' + n)
            out[t] = keys
        else:
            out[t] = list(d['targets'])
    return out


def owner_of(key: str) -> Optional[str]:
    for p in PARTS:
        if key in p['routines'] or key in p['helpers']:
            return p['name']
    if key in CORE:
        return 'core'
    return None


def native_names() -> Dict[str, str]:
    """file:label -> its native label: the label itself when no other
    routine of the table or the core has it, else STEM_label (STEM the
    file's name without 65.s)."""
    keys = [k for p in PARTS for k in p['routines'] + p['helpers']] + CORE
    count: Dict[str, int] = {}
    for k in keys:
        count[k.split(':', 1)[1]] = count.get(k.split(':', 1)[1], 0) + 1
    out = {}
    for k in keys:
        unit, label = k.split(':', 1)
        out[k] = label if count[label] == 1 else '%s_%s' % (
            unit.replace('65.s', ''), label)
    return out


def integrated_waves() -> int:
    """The waves the integrator merged (src/native/game/integrated.txt)."""
    try:
        return int(INTEGRATED.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


def built_set(waves: Optional[int] = None, extra: Sequence[str] = ()
              ) -> List[str]:
    """The parts built: those of the integrated waves, and extra (a part's
    own test image: the earlier waves and itself)."""
    w = integrated_waves() if waves is None else waves
    out = [p['name'] for p in PARTS if p['wave'] <= w]
    for e in extra:
        if e not in PART_NAMES:
            raise ValueError('no part %s' % e)
        if e not in out:
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# The parts' scratch blocks (4.4): SCRATCH_DEFAULT bytes each, in W
# $9A00-$9DFF; two parts share bytes only if no routine of one can be
# active while one of the other is (gcallgraph.py's reachability, the
# dispatch tables included). With every part's default the blocks fit
# without sharing (29 x 32 = 928 of 1,024).
# ---------------------------------------------------------------------------
SCRATCH_DEFAULT = 32
SCRATCH_REQUESTS: Dict[str, int] = {        # part -> bytes (requests, 3.8)
    # P_CheckSight's state across its calls (docs/game-parts/sight.md R1)
    'sight': 106,
    # P_PathTraverse's walk across the block steps and the traverser's
    # calls (docs/game-parts/path.md R1; wave 4 as integrated)
    'path': 44}

# The helpers that have no native code of their own: each part does their
# work in place, in the routine that calls them (each part's record says
# where), so the placement gives them no bytes (wave 1 as integrated:
# mobjstate.md R10, secfind.md request 4, sight.md "the helpers", geom's)
INLINED = {
    'geom': ('p_map65.s:argLine4', 'p_map65.s:box1', 'p_map65.s:box2',
             'p_map65.s:posPub', 'p_map65.s:walk1', 'p_map65.s:walk2',
             'p_map65.s:callLN', 'p_map65.s:callLN2'),
    'mobjstate': ('p_map65.s:snLink', 'p_spawn65.s:rmArg'),
    'secfind': ('p_spec65.s:sideSector', 'p_spec65.s:secArg',
                'p_spec65.s:lineOf', 'p_lights65.s:secArg',
                'p_lights65.s:ltSector', 'p_floor65.s:nextOther',
                'p_floor65.s:aboveCurrent'),
    'sight': ('p_sight65.s:hintOf', 'p_sight65.s:half', 'p_sight65.s:qbd',
              'p_sight65.s:nodeDone', 'p_sight65.s:lineDone',
              'p_sight65.s:pick', 'p_sight65.s:sameHeight',
              'p_sight65.s:st32', 'p_sight65.s:shr8V', 'p_sight65.s:bitTab',
              'p_sight65.s:straceDone'),
    # wave 2 as integrated (docs/GAME.md): upstream's long-call wrappers,
    # whose callers FCALL the routine itself (vtxSlow, lineCross, icInsert:
    # tracel.md R3); argument loaders done in place and tables assembled in
    # their reader's bytes (damage.md R3, pickup.md P2, lines.md request 4,
    # spawn.md request 3)
    'tracel': ('p_trace65.s:vtxSlowL', 'p_trace65.s:lineCrossL',
               'p_trace65.s:icInsertL'),
    'damage': ('p_inter65.s:targetArg', 'p_inter65.s:setTarget',
               'p_inter65.s:addThrust'),
    'pickup': ('p_inter65.s:specialArg', 'p_inter65.s:playerMo',
               'p_inter65.s:pickTab', 'p_inter65.s:pickTab_end',
               'm_cheat65.s:cheats'),
    'lines': ('p_switch65.s:swLine', 'p_switch65.s:swSide',
              'p_switch65.s:isPlayer', 'p_switch65.s:usetab',
              'p_switch65.s:crosstab', 'p_switch65.s:spectab',
              'p_switch65.s:usetab_end', 'p_switch65.s:crosstab_end'),
    'spawn': ('p_spawn65.s:moArg', 'p_spawn65.s:saveXYZ',
              'p_spawn65.s:thArg'),
    # wave 3 as integrated (docs/GAME.md): upstream's patched templates
    # and their patchers are data natively (TT_AX; part path tests its
    # flags itself), thFastL a long-call wrapper of the dead guard's
    # (tracet.md R1); a JSL wrapper, geom's inline above, lineBlocks' own
    # code, a load done in place (checkpos.md R4); argMo read in place
    # (pspr.md R1); argument loaders and field stores done in place
    # (evworld.md request 1: movers does sectorArg in place too);
    # behindFast's jump table's cases and the radius attack's local
    # helpers (look.md request 1)
    'tracet': ('p_trace65.s:ptT1', 'p_trace65.s:ptT2',
               'p_trace65.s:vsPatch', 'p_trace65.s:ptPatch',
               'p_trace65.s:thFastL', 'p_trace65.s:tlP1',
               'p_trace65.s:tlP2', 'p_trace65.s:thP', 'p_trace65.s:gtP1',
               'p_trace65.s:gtP2'),
    'checkpos': ('p_map65.s:setBoxL', 'p_map65.s:above',
                 'p_map65.s:lCross', 'p_map65.s:ps32',
                 'p_map65.s:loadRad'),
    'pspr': ('p_pspr65.s:argMo',),
    'evworld': ('p_plats65.s:platArg', 'p_plats65.s:sectorArg',
                'p_plats65.s:platSound', 'p_plats65.s:setHigh',
                'p_plats65.s:setLow', 'p_plats65.s:plSec',
                'p_doors65.s:doorArg', 'p_doors65.s:setDir',
                'p_doors65.s:topLowest', 'p_doors65.s:setTop',
                'p_doors65.s:edLine', 'p_doors65.s:edSec',
                'p_doors65.s:edSound', 'p_doors65.s:sectorArg'),
    'look': ('p_enemy65.s:bfD0', 'p_enemy65.s:bfD1', 'p_enemy65.s:bfD2',
             'p_enemy65.s:bfD3', 'p_enemy65.s:bfD4', 'p_enemy65.s:bfD5',
             'p_enemy65.s:bfD6', 'p_enemy65.s:bfD7',
             'p_attack65.s:blockPair', 'p_attack65.s:absDelta'),
    # wave 4 as integrated (docs/GAME.md): upstream's jml [PT_JMP] is
    # traverseTo's DCALL TRVTAB (path.md R3); P_TryMove's tests, mvNodes,
    # spec and specLine and P_NightmareRespawn's loaders, subFloor and fog
    # are local code of the routine that calls them (trymove.md R1); the
    # movers' direct-page loaders and plane copies (planes.md request 1);
    # the floors' argument loaders, field stores and compares, floorDown
    # being floorUp with A = $FF (evfloor.md request 1); the teleport's
    # argument loaders, handles of its scratch block (teleport.md R1)
    'path': ('p_path65.s:callTrav',),
    'trymove': ('p_map65.s:overStep', 'p_map65.s:lessHeight',
                'p_map65.s:mvNodes', 'p_map65.s:spec',
                'p_map65.s:specLine', 'p_spawn65.s:nmArg',
                'p_spawn65.s:nmXY', 'p_spawn65.s:subFloor',
                'p_spawn65.s:fog'),
    'planes': ('p_floor65.s:restore', 'p_floor65.s:planeArgs',
               'p_floor65.s:minusSpeed', 'p_floor65.s:plusSpeed',
               'p_floor65.s:saveLast', 'p_floor65.s:setPlaneT',
               'p_floor65.s:secArg', 'p_floor65.s:loadNode',
               'p_floor65.s:nodeArg', 'p_floor65.s:thingArg',
               'p_floor65.s:floorArg', 'p_floor65.s:floorSector',
               'p_floor65.s:floorSpeed', 'p_floor65.s:sectorSound'),
    'evfloor': ('p_floor65.s:lineStart', 'p_floor65.s:nextTagged',
                'p_floor65.s:secOf', 'p_floor65.s:secArg2',
                'p_floor65.s:floorField', 'p_floor65.s:floorDown',
                'p_floor65.s:floorArgFL', 'p_floor65.s:sameAsFloor',
                'p_floor65.s:underCeiling', 'p_floor65.s:lineSector',
                'p_floor65.s:sectorNum', 'p_floor65.s:s2Arg',
                'p_floor65.s:s3Arg', 'p_floor65.s:s3Floor'),
    'teleport': ('p_telept65.s:thingArg', 'p_telept65.s:destArg',
                 'p_map65.s:tpThing'),
    # wave 5 as integrated (docs/GAME.md): the shot's and the aim's setup,
    # end point and run, the traversers' tests, slopes and the puff's
    # arguments are local code of the routine that calls them, some under
    # the helper's name (attack.md R3); the player's argument loaders and
    # local subroutines (player.md R2); the move's big-move test, whole
    # and half steps, the slide's corners and coordinate sum (xymove.md
    # R2); P_SpawnMissile's argument loader, its delta and angleMom's
    # speed (missile.md R1); pMove's speed steps and products, the chase
    # direction's and the drop-off's local helpers (chasemove.md R1)
    'attack': ('p_attack65.s:traceSetup', 'p_attack65.s:endPoint',
               'p_attack65.s:traceRun', 'p_attack65.s:loadIntercept',
               'p_attack65.s:opening', 'p_attack65.s:rangeDist',
               'p_attack65.s:lineSectors', 'p_attack65.s:sideAddr',
               'p_attack65.s:sideSectors', 'p_attack65.s:sectorsDiffer',
               'p_attack65.s:shootable', 'p_attack65.s:rawSlope',
               'p_attack65.s:thingHead', 'p_attack65.s:thingFoot',
               'p_attack65.s:thingPtr', 'p_attack65.s:thingTop',
               'p_attack65.s:thingTopRaw', 'p_attack65.s:ceilBelowZ',
               'p_attack65.s:thingBottom', 'p_attack65.s:thingBottomRaw',
               'p_attack65.s:slopeTo', 'p_attack65.s:slopeOf',
               'p_attack65.s:traceAt', 'p_attack65.s:puffArgs',
               'p_attack65.s:spawnPuff'),
    'player': ('p_user65.s:argMo', 'p_user65.s:moSector',
               'p_user65.s:countDown', 'p_user65.s:blink',
               'p_user65.s:bobAndThrust', 'p_user65.s:addMom',
               'p_use65.s:useRun', 'p_use65.s:useArg', 'p_use65.s:lineArg'),
    'xymove': ('p_mobj65.s:isBig', 'p_mobj65.s:wholeMove',
               'p_mobj65.s:halfMove', 'p_mobj65.s:corners',
               'p_mobj65.s:addCoord'),
    'missile': ('p_spawn65.s:srcArg', 'p_spawn65.s:destDelta',
                'p_spawn65.s:speedMom'),
    'chasemove': ('p_enemy65.s:speedStep', 'p_enemy65.s:mulSpeed',
                  'p_enemy65.s:umul16x', 'p_enemy65.s:speedTab',
                  'p_enemy65.s:speeds', 'p_enemy65.s:SPD47',
                  'p_enemy65.s:setDir', 'p_enemy65.s:absGreater',
                  'p_enemy65.s:absD', 'p_enemy65.s:boxPlus',
                  'p_enemy65.s:boxMinus', 'p_enemy65.s:blockOf',
                  'p_enemy65.s:boxAbove', 'p_enemy65.s:boxBelow',
                  'p_enemy65.s:sideFloor', 'p_enemy65.s:signed',
                  'p_enemy65.s:times32'),
    # wave 6 as integrated (docs/GAME.md): the movers' plane-move loaders,
    # status stores and sector sounds are local code of the thinker that
    # calls them (movers.md request 1); the aims of bulletSlope and
    # P_SpawnPlayerMissile are a loop in their routine, !refire two loads
    # and a branch (wfire.md R1); P_MobjThinker's local subroutines and
    # G_Ticker's chain of compares in place of upstream's action table
    # (tic.md R1)
    'movers': ('p_plats65.s:movePlat', 'p_plats65.s:stopWait',
               'p_plats65.s:waitStatus', 'p_plats65.s:setStatus',
               'p_doors65.s:doorSound', 'p_doors65.s:moveCeiling',
               'p_doors65.s:dlSec'),
    'wfire': ('p_pspr65.s:aimAt', 'p_pspr65.s:notRefire',
              'p_spawn65.s:aim'),
    'tic': ('p_tick65.s:mobjArg', 'p_tick65.s:stillMobjThinker',
            'g_game65.s:actions'),
}


def inlined(key: str) -> bool:
    return any(key in v for v in INLINED.values())


def scratch_blocks(conflicts: Optional[Set[Tuple[str, str]]] = None
                   ) -> Dict[str, Tuple[int, int]]:
    """part -> (address, size), first fit; a part conflicts with every
    other unless conflicts (pairs that can be active together) says
    otherwise."""
    lo, hi = WR['SCRATCH']
    placed: List[Tuple[str, int, int]] = []
    out: Dict[str, Tuple[int, int]] = {}
    for p in PARTS:
        name = p['name']
        size = SCRATCH_REQUESTS.get(name, SCRATCH_DEFAULT)
        at = lo
        while True:
            clash = [q for q, a, n in placed
                     if a < at + size and at < a + n and
                     (conflicts is None or (name, q) in conflicts or
                      (q, name) in conflicts)]
            if not clash:
                break
            at = max(a + n for q, a, n in placed if q in clash)
        if at + size > hi:
            raise ValueError('the scratch blocks pass $%04X at %s' % (hi,
                                                                    name))
        placed.append((name, at, size))
        out[name] = (at, size)
    return out


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------

class Region(NamedTuple):
    space: str
    start: int
    end: int
    what: str


def regions() -> List[Region]:
    out = [Region('w', lo, hi, what) for _, lo, hi, what in W_MAP]
    out += [Region('main', lo, hi, what) for _, lo, hi, what in MAIN_TIC]
    out.append(Region('main', GLOBALS[0], GLOBALS[1], 'the game globals'))
    out.append(Region('main', GS_STATUS, GS_ARG + 2, 'the stop codes'))
    return out


def check() -> None:
    """Raises ValueError on a region used twice or out of its space, a
    tic range over a persistent byte of the renderer, a zero-page byte out
    of its owner's range."""
    LL.check()
    rs = regions()
    for i, a in enumerate(rs):
        if a.end <= a.start:
            raise ValueError('%s is empty' % a.what)
        if a.space == 'w' and not (0x6000 <= a.start and a.end <= 0xC000):
            raise ValueError('%s is outside W' % a.what)
        for b in rs[i + 1:]:
            if a.space == b.space and a.start < b.end and b.start < a.end:
                raise ValueError('%s overlaps %s' % (a.what, b.what))
    # W is the tic phase's, whole
    if [lo for _, lo, _, _ in W_MAP] != sorted(lo for _, lo, _, _ in W_MAP):
        raise ValueError('W\'s map is not in order')
    for (_, _, hi, _), (_, lo, _, _) in zip(W_MAP, W_MAP[1:]):
        if hi != lo:
            raise ValueError('W\'s map has a hole at $%04X' % hi)
    if W_MAP[-1][2] != 0xC000:
        raise ValueError('W\'s map ends at $%04X' % W_MAP[-1][2])
    if (LL.GW, LL.GW_END) != WR['GW'] or LL.GW_USED > LL.GW_END:
        raise ValueError('the API\'s W')
    # every tic range of main is dead between the replay's end and the
    # next frame's front end: no persistent region of the renderer in it
    persist = [r for r in R.regions() if r.space == 'main' and
               r.what in PERSISTENT]
    if len({r.what for r in persist}) != len(PERSISTENT):
        raise ValueError('rlayout.py lacks a persistent region: %s' % (
            sorted(set(PERSISTENT) - {r.what for r in persist}),))
    for _, lo, hi, what in MAIN_TIC:
        for r in persist:
            if lo < r.end and r.start < hi:
                raise ValueError('%s overlays the renderer\'s persistent %s'
                                 % (what, r.what))
        if lo < LL.GBLOCK_END and LL.LNMAP < hi:
            raise ValueError('%s overlays the game globals' % what)
    # the zero page
    for table, (lo, hi) in ((ZA, ZP_API_RANGE), (ZC, ZP_CALL_RANGE),
                            (ZGA, GA_RANGE), (ZGT, GT_RANGE),
                            (ZAT, GT_RANGE)):
        for name, at in table.items():
            if not lo <= at < hi:
                raise ValueError('%s outside $%02X-$%02X' % (name, lo, hi))
    for lo, hi in (ZP_API_RANGE, ZP_CALL_RANGE, GA_RANGE, GT_RANGE):
        if lo < LL.LZPG_RANGE[1] and LL.LZPG_RANGE[0] < hi:
            raise ValueError('a tic zero-page range over the game core\'s')
        if lo < R.ZP_FORBIDDEN[1] and R.ZP_FORBIDDEN[0] < hi:
            raise ValueError('a tic zero-page range in $42-$47')
        if hi > LL.ZP_SPAWN['GS_I']:
            raise ValueError('a tic zero-page range over the spawn\'s')
    if TIC_GW_USED > LL.GW_END or min(TGW.values()) < LL.GW_USED:
        raise ValueError('the tic phase\'s GW fields')
    if TIC_MAIN_END > LL.GBLOCK_END or min(TGM.values()) < LL.GLOBALS_END:
        raise ValueError('the tic phase\'s globals')
    if TIC_PAGE1[0] < 0x0100 or \
            TIC_PAGE1[1] > 0x0100 + DRIVER_S + 1 - TIC_STACK:
        raise ValueError('the API\'s page-1 window under the tic stack')
    if RT_USED > LL.RT_END - LL.RT_STATE:
        raise ValueError('the runtime\'s state passes $%04X' % LL.RT_END)
    # the slots' bytes in a row (K_TIC and core_in set SLOT_CLR of them)
    if RT['SLOT_NEED'] != RT['SLOT_GRP'] + FRAME_FIRST + FS_MAX or \
            RT['FS_DIRTY'] != RT['SLOT_NEED'] + FRAME_FIRST - 1 + FS_MAX \
            or SLOT_CLR > 0x80:
        raise ValueError('SLOT_GRP, SLOT_NEED, FS_DIRTY')
    # the frame slots' region: colormaps A and B of levels 0-31, two
    # halves of one main range, their copies in LVC
    if FRAME_HALVES[0][1] != FRAME_HALVES[1][0] or \
            (FRAME_HALVES[0][0], FRAME_HALVES[1][1]) != FRAME_REGION or \
            any(lo & 0xFF or src & 0xFF or src + hi - lo > LL.LVC_GSVIEW
                for lo, hi, src in FRAME_HALVES) or \
            FRAME_REGION[1] > WR['MATHW'][0]:
        raise ValueError('the frame slots\' region')
    if GS_ARG + 2 > LL.PRND or GS_STATUS <= LL.LV_AMEM:
        raise ValueError('the stop codes')
    scratch_blocks()
    # the parts: one owner a routine, waves 1-6, at most 5 a wave
    seen: Dict[str, str] = {}
    for p in PARTS:
        if not 1 <= p['wave'] <= 6:
            raise ValueError('%s: wave %d' % (p['name'], p['wave']))
        for k in p['routines'] + p['helpers']:
            if k in seen:
                raise ValueError('%s: %s and %s' % (k, seen[k], p['name']))
            seen[k] = p['name']
    for w in range(1, 7):
        if sum(1 for p in PARTS if p['wave'] == w) > 5:
            raise ValueError('wave %d has more than 5 parts' % w)
    if len(PARTS) != 29:
        raise ValueError('%d parts' % len(PARTS))
    if REKEY_RECORD > GTB['GT_SOUNDS'] - GTB['GT_REKEYS'] or \
            GTB['GT_HITS'] + 0x0400 > LL.ROOM[1]:
        raise ValueError('GTEST')


def check_manifest(header: Dict[str, Any], numtextures: int = 125
                   ) -> List[str]:
    """Every canonical field of the tic mode placed or excluded by name
    (needs build/): the manifest's leaves against the bridge's fields of
    each kind and the globals; the names it leaves out."""
    from bridge import layout as BL, schema, upstream
    sch = upstream.Schema()
    mf = BL.Manifest(manifest(header, numtextures=numtextures))
    out: List[str] = []
    excluded = set(LL.NOT_KEPT) | {'kind:%s' % k for k in ('removed',)}
    for kind in schema.KINDS:
        if kind in ('state', 'lump', 'symbol', 'table', 'removed'):
            continue
        want = {lf.path for lf in BL.kind_leaves(kind, sch.structs)
                if not lf.path[0].startswith('@')}
        have = {lf.path for lf in mf.kinds.get(kind, {}).get('leaves', [])}
        for path in sorted(want - have, key=str):
            name = '%s.%s' % (kind, '.'.join(map(str, path)))
            if name not in LL.NOT_KEPT_FIELDS and \
                    path[0] not in ('free', 'gstamp'):
                out.append('%s: no leaf' % name)
    gnames = {lf.path[0] for lf in mf.globals}
    for unit, labels in list(schema.GLOBALS.items()) + list(
            schema.EXTERNAL_GLOBALS.items()) + list(
                schema.TIC_GLOBALS.items()):
        for label, text in labels.items():
            name = '%s:%s' % (unit, label)
            if text.startswith('object:') or name in excluded:
                continue
            if name not in gnames:
                out.append('%s: no leaf' % name)
    if schema.TIC_TEXTURES not in gnames:
        out.append('%s: no leaf' % schema.TIC_TEXTURES)
    del excluded
    return out


# ---------------------------------------------------------------------------
# The manifest native-game-1 (1.11): native-level-1 and the tic mode's
# globals and the derived kind "sighthint"
# ---------------------------------------------------------------------------
TIC_PLACE = {
    'wi_stuff65.s:_g_acceleratestage': ('WI_ACCEL', 2),
    'wi_stuff65.s:state': ('WI_STATE', 2), 'wi_stuff65.s:cnt': ('WI_CNT', 2),
    'wi_stuff65.s:bcnt': ('WI_BCNT', 2),
    'wi_stuff65.s:cnt_time': ('WI_CNTTIME', 4),
    'wi_stuff65.s:cnt_total_time': ('WI_CNTTOTAL', 4),
    'wi_stuff65.s:cnt_par': ('WI_CNTPAR', 2),
    'wi_stuff65.s:cnt_pause': ('WI_CNTPAUSE', 2),
    'wi_stuff65.s:sp_state': ('WI_SPSTATE', 2),
    'wi_stuff65.s:cnt_kills': ('WI_CNTKILLS', 2),
    'wi_stuff65.s:cnt_items': ('WI_CNTITEMS', 2),
    'wi_stuff65.s:cnt_secret': ('WI_CNTSECRET', 2),
    'wi_stuff65.s:snl_pointeron': ('WI_SNLPTR', 2),
    'hu_stuff65.s:_g_message_dontfuckwithme': ('G_MSGKEEP', 2),
    'm_menu65.s:showMessages': ('G_SHOWMSG', 2),
}


def manifest(header: Dict[str, Any], symbols: Sequence[str] = (),
             numtextures: int = 125) -> Dict[str, Any]:
    """native-game-1 for a map (its store header): llayout.manifest's
    level and game state, the tic mode's globals (WI_*, showMessages,
    _g_message_dontfuckwithme in the globals block; nukage in the frame
    block, a byte; texturetranslation's entries in TEXTRANS, a byte each)
    and the kind "sighthint" (HINTL, HINTH by pool slot)."""
    from bridge import schema
    m = LL.manifest(header, symbols)
    m['name'] = 'native-game-1'
    m['note'] = ('the native game state of E1M%d (tools/native/glayout.py, '
                 'milestone 10\'s skeleton; native-level-1 and the tic '
                 'mode\'s globals and sight hints)' % header['map'])
    gl = m['globals']['leaves']

    def main(at: int, n: int) -> List[str]:
        return ['main:%04X' % (at + k) for k in range(n)]
    for name, (field, size) in TIC_PLACE.items():
        unit, label = name.split(':')
        text = schema.TIC_GLOBALS[unit][label]
        signed = text.startswith('i')
        gl.append({'path': [name], 'enc': {'enc': 'int', 'bytes': size,
                                           'signed': signed},
                   'planes': main(LL.G[field], size)})
    gl.append({'path': ['r_data65.s:nukage'],
               'enc': {'enc': 'int', 'bytes': 1, 'signed': False},
               'planes': main(R.FRAME['NUKAGE'], 1)})
    for t in range(numtextures + 1):
        gl.append({'path': [schema.TIC_TEXTURES, t],
                   'enc': {'enc': 'int', 'bytes': 1, 'signed': False},
                   'planes': main(R.TEXTRANS + t, 1)})
    pool = header['counts']['things']
    m['kinds']['sighthint'] = {
        'capacity': LL.POOL_MAX, 'count': ['main:%04X' % LL.G['G_POOLN'],
                                           'main:%04X' % (LL.G['G_POOLN'] +
                                                          1)],
        'leaves': [{'path': ['line'], 'enc': {'enc': 'int', 'bytes': 2,
                                              'signed': False},
                    'planes': ['aux:%02X:%04X' % (LL.MOBJP, LL.PL_HINTL),
                               'aux:%02X:%04X' % (LL.MOBJP, LL.PL_HINTH)]}]}
    del pool
    return m


# ---------------------------------------------------------------------------
# The textures a load makes (wave 1 as integrated; docs/game-parts/flow.md
# request 6): upstream's R_GetTexture sets texturetranslation[n] = n for each
# texture it makes (r_data65.s:458): at every P_SetupLevel each side's
# textures and a switch texture's partner (P_LoadTexture, p_setup65.s:684-
# 688: the PU_LEVEL textures were freed by its Z_FreeTags, :122), and for
# another map than the window's W_LevelDone's moreColumns makes (bmLoad,
# m_menu65.s:1780-1789; umodel.py's Columns.more). Only P_UpdateSpecials
# writes another value, into basepic .. basepic + 2 (p_spec65.s:328-336),
# so only those three entries can change: per map a mask of them for the
# setup (TXR_Ln) and for W_LevelDone (TXR_Mn), bit k basepic + k, from the
# upstream model of the load (umodel.py), kept in shared/txreset.json.
# ---------------------------------------------------------------------------
TXRESET = SHARED / 'txreset.json'


def txr_compute() -> Dict[str, Any]:
    from native import umodel as U
    gd = U.game_data()
    base = gd.basepic
    out: Dict[str, Any] = {'format': 'game-txreset 1', 'basepic': base,
                           'load': {}, 'more': {}}
    for m in range(1, 10):
        ld = U.load(gd, m)
        made = set()
        for top, mid, bottom in U.map_sides(ld.game):
            for tx in (mid, top, bottom):
                made.add(tx)
                if 0 <= tx < 256 and gd.sw_idx[tx]:
                    k = gd.sw_idx[tx] - 1
                    made.add(gd.switchlist[(k >> 1) ^ 1])
        out['load'][str(m)] = sum(1 << k for k in range(3)
                                  if base + k in made)
        out['more'][str(m)] = sum(1 << k for k in range(3)
                                  if base + k in ld.made_more)
    return out


def txr_masks() -> Dict[str, Any]:
    """The masks (shared/txreset.json, made from the model when missing:
    needs build/'s WAD and release)."""
    if TXRESET.exists():
        data = json.loads(TXRESET.read_text())
        if data.get('format') == 'game-txreset 1':
            return data
    data = txr_compute()
    TXRESET.parent.mkdir(parents=True, exist_ok=True)
    tmp = TXRESET.with_name('txreset.json.%d' % os.getpid())
    tmp.write_text(json.dumps(data, indent=1) + '\n')
    os.replace(str(tmp), str(TXRESET))
    return data


def txr_constants() -> List[Tuple[str, int]]:
    d = txr_masks()
    out = [('TXR_BASE', d['basepic'])]
    for m in range(1, 10):
        out += [('TXR_L%d' % m, d['load'][str(m)]),
                ('TXR_M%d' % m, d['more'][str(m)])]
    return out


# ---------------------------------------------------------------------------
# The includes
# ---------------------------------------------------------------------------

def upstream_constants() -> List[Tuple[str, int]]:
    """CONST_* of offsets.inc and info.inc as UC_*, OFS_* as UO_*, SIZEOF_*
    as US_* (the bridge's incfile.py: never typed in)."""
    from bridge import incfile
    out: Dict[str, int] = {}
    inc = BUILD / 'upstream' / 'src' / 'iigs'
    given: Dict[str, int] = {}
    for name in ('offsets.inc', 'info.inc'):
        values = incfile.as_dict(incfile.parse(inc / name, given))
        given.update(values)
        for k, v in values.items():
            if not isinstance(v, int):
                continue
            if k.startswith('CONST_'):
                out['UC_' + k[6:]] = v
            elif k.startswith('OFS_'):
                out['UO_' + k[4:]] = v
            elif k.startswith('SIZEOF_'):
                out['US_' + k[7:]] = v
    # the source files' own equates the parts and the driver need (through
    # the link map, as llayout.py's): the game actions (g_game65.s)
    from bridge import schema
    from bridge.linkmap import Symbols
    c = schema.Constants(Symbols())
    for unit, names in (('g_game65.s', ('GA_NOTHING', 'GA_LOADLEVEL',
                                        'GA_NEWGAME', 'GA_LOADGAME',
                                        'GA_SAVEGAME', 'GA_PLAYDEMO',
                                        'GA_COMPLETED', 'GA_VICTORY',
                                        'GA_WORLDDONE')),
                        # the lights' steps (secfind.md request 5)
                        ('p_lights65.s', ('GLOWSPEED', 'STROBEBRIGHT'))):
        for name in names:
            out['U' + name] = c.local(unit, name)
    return sorted(out.items())


def constants() -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = [
        ('GCODE0', LL.GCODE0), ('GCODE1', LL.GCODE1), ('DEMOB', LL.DEMOB),
        ('GTEST', LL.GTEST), ('GS_STATUS', GS_STATUS), ('GS_ARG', GS_ARG),
        ('TIC_STACK', TIC_STACK), ('FCALL_STACK', FCALL_STACK),
        ('KERN_GCOPY', KERN_GCOPY), ('AM_REQ', AM_REQ[0]),
        ('FS_FIRST', FRAME_FIRST), ('FS_MAX', FS_MAX),
        ('SLOT_CLR', SLOT_CLR),
        ('FS_LO', FRAME_REGION[0]), ('FS_HI', FRAME_REGION[1]),
        ('PW_AT', TIC_PAGE1[0]), ('PW_END', TIC_PAGE1[1]),
        ('GT_LOAD', GT_LOAD), ('FRAME_NONE', FRAME_NONE),
        ('FRAME_FRONT', FRAME_FRONT), ('FRAME_FULL', FRAME_FULL),
        ('FRAME_KIND', FRAME_KIND), ('FRAME_STRIP', FRAME_STRIP),
        ('VIEW_STRIPTOP', VIEW_STRIPTOP),
        ('SOUND_EVENT', SOUND_EVENT), ('HIT_EVENT', HIT_EVENT),
        ('REKEY_RECORD', REKEY_RECORD), ('SCRATCH_DEFAULT',
                                         SCRATCH_DEFAULT),
        ('GT_LEVEL_RECORD', GT_LEVEL_RECORD)]
    for name, lo, hi, _ in W_MAP:
        out += [('TW_' + name, lo), ('TW_' + name + '_END', hi)]
    out += sorted(('GS_' + k, v) for k, v in GS.items())
    out += sorted(('DM_' + k, v) for k, v in MODES.items())
    out += sorted(GTB.items(), key=lambda kv: kv[1])
    out += sorted(RT.items(), key=lambda kv: kv[1])
    for p, (at, n) in scratch_blocks().items():
        out += [('SB_' + p.upper(), at), ('SB_' + p.upper() + '_SIZE', n)]
    out += sorted(TGW.items(), key=lambda kv: kv[1])
    out += sorted(TGM.items(), key=lambda kv: kv[1])
    out += DEMOB_LAYOUT
    # GTAB's animated_texture_basepic (secfind.md request 3)
    out.append(('GT_BASEPIC', LL.GT['BASEPIC'][0]))
    # GTAB's switchlist and SW_IDX (lines.md request 1)
    out.append(('GT_SWLIST', LL.GT['SWITCHLIST'][0]))
    out.append(('GT_SWIDX', LL.GT['SW_IDX'][0]))
    # the sky's ceiling pic: upstream's skyflatnum ($FFFE) as the native
    # byte pic (levelconv.pic_byte); parts attack and xymove compare a
    # sector's SEC_CPIC with it (wave 5: attack.md R2, xymove.md R3)
    from native import levelconv
    out.append(('SKY_PIC', levelconv.SKY_PIC))
    # the entry numbers of the dispatch tables whose targets are labels:
    # <TABLE>_<label> (lines.md request 2: spectab names its handlers by
    # LSTAB number; ITTAB's and TRVTAB's for their callers alike)
    for table in ('ITTAB', 'TRVTAB', 'LSTAB'):
        for i, key in enumerate(DISPATCH[table]['targets'], 1):
            out.append(('%s_%s' % (table, key.split(':', 1)[1]), i))
    return out


def symbol_name(key: str) -> str:
    """SYM_<unit stem>_<label> of a symbol of the manifest's list."""
    unit, label = key.split(':', 1)
    return 'SYM_%s_%s' % (unit.split('.')[0].replace('65', ''), label)


def symbol_constants() -> List[Tuple[str, int]]:
    """Each symbol's number in the game manifest's "symbols"
    (llayout.symbol_list()): what a player's message holds natively (the
    bridge's "ref" encoding: tag 1, the number, the offset; pickup.md
    P1)."""
    return [(symbol_name(k), i) for i, k in enumerate(LL.symbol_list())]


def zeropage() -> List[Tuple[str, int]]:
    out = sorted(list(ZA.items()) + list(ZC.items()) + list(ZGA.items()) +
                 list(ZGT.items()) + list(ZAT.items()), key=lambda x: x[1])
    out += [(k, GA_RANGE[0] + v) for k, v in GA_NAMES.items()]
    return out


def ggame_text(with_upstream: bool = True) -> str:
    check()
    lines = ['; Generated by tools/native/glayout.py (docs/GAME.md 3.2). '
             'Do not edit.', '']
    for name, value in constants():
        lines.append('%-20s= $%04X' % (name, value))
    lines += ['', '; zero page']
    for name, value in zeropage():
        lines.append('%-20s= $%02X' % (name, value))
    if with_upstream:
        lines += ['', '; the symbols\' numbers (the manifest\'s "symbols")']
        for name, value in symbol_constants():
            lines.append('%-32s = $%04X' % (name, value))
        lines += ['', '; the textures a load makes (txreset.json)']
        for name, value in txr_constants():
            lines.append('%-20s= $%02X' % (name, value))
        lines += ['', '; upstream\'s constants (offsets.inc, info.inc)']
        for name, value in upstream_constants():
            lines.append('%-32s= $%X' % (name, value & 0xFFFFFFFF))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# gplace.inc and gdisp.inc
# ---------------------------------------------------------------------------

def placement_of(place: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The placement (gplace.py's JSON: groups and each routine's group),
    or the default: everything in the core."""
    if place is None:
        path = SHARED / 'placement.json'
        if path.exists():
            place = json.loads(path.read_text())
        else:
            place = {'groups': [], 'routines': {}}
    return place


def gplace_text(built: Sequence[str], place: Optional[Dict[str, Any]] = None,
                test_place: bool = False) -> str:
    """gplace.inc: GP_<native>_G (its group, 0 the core), _B (built), _N
    (its number, for the unbuilt stop) for every routine of the table and
    of the core; the groups' slots, banks and image places; the FCALL and
    ROUTINE macros."""
    place = placement_of(place)
    names = native_names()
    groups = list(place['groups'])
    if test_place:
        groups = groups + TEST_GROUPS
    lines = ['; Generated by tools/native/glayout.py (docs/GAME.md 4.3). '
             'Do not edit.', '; built parts: %s' % (
                 ', '.join(built) or 'none'), '']
    lines.append('GROUPS = %d' % len(groups))
    for i, g in enumerate(groups, 1):
        lines.append('GRP%d_SLOT = %d' % (i, g['slot']))
    # the frame slots (FRAME_FIRST ..): each one's first page in main, its
    # colormap bytes' first page in LVC (the restore's source), its group
    fs = frame_slots(groups)
    owner = {int(g['slot']): i for i, g in enumerate(groups, 1)
             if int(g['slot']) >= FRAME_FIRST}
    lines.append('FSLOTS = %d' % len(fs))
    for s, (lo, hi) in sorted(fs.items()):
        lines += ['FSLOT%d_PAGE = $%02X' % (s, lo >> 8),
                  'FSLOT%d_SRC = $%02X' % (s, frame_source(lo) >> 8),
                  'FSLOT%d_GRP = %d' % (s, owner[s])]
    lines.append('')
    routines = [k for p in PARTS for k in p['routines'] + p['helpers']]
    for number, key in enumerate(routines + CORE, 1):
        n = names[key]
        o = owner_of(key)
        b = 1 if o == 'core' or o in built else 0
        grp = place['routines'].get(key, 0)
        lines.append('GP_%s_G = %d' % (n, grp))
        lines.append('GP_%s_B = %d' % (n, b))
        lines.append('GP_%s_N = %d' % (n, number))
    if test_place:
        for i, g in enumerate(TEST_GROUPS, len(place['groups']) + 1):
            for n in g['routines']:
                lines += ['GP_%s_G = %d' % (n, i), 'GP_%s_B = 1' % n,
                          'GP_%s_N = %d' % (n, 0)]
        for n in TEST_CORE:
            lines += ['GP_%s_G = 0' % n, 'GP_%s_B = 1' % n,
                      'GP_%s_N = 0' % n]
    lines += ['', MACROS.replace('@SEGMENTS@', segment_chain(len(groups)))]
    return '\n'.join(lines) + '\n'


def segment_chain(n: int) -> str:
    out = ['  .if .ident(.concat("GP_", .string(name), "_G")) = 0',
           '        .segment "GCORE"']
    for i in range(1, n + 1):
        out += ['  .elseif .ident(.concat("GP_", .string(name), "_G")) = '
                '%d' % i, '        .segment "GGRP%d"' % i]
    out.append('  .endif')
    return '\n'.join(out)


MACROS = r'''; ROUTINE name: the routine's code in its group's segment (the core's:
; GCORE), and the callers' group for FCALL below
.macro ROUTINE name
@SEGMENTS@
FC_HERE .set .ident(.concat("GP_", .string(name), "_G"))
name:
.endmacro

; FCALL target: a call that the placement decides: jsr when the target is
; in the core or in the caller's own group, else through fc_call with its
; group and address inline (gcall.s: 5 bytes of stack, the target slot's
; group saved and restored); a target whose part is not built: the
; unbuilt stop with its number (GS_UNBUILT). A built target is .global:
; imported, or exported where it is defined (wave 1 as integrated:
; mobjstate.md R1, flow.md request 2)
.macro FCALL target
  .if .ident(.concat("GP_", .string(target), "_B")) = 0
        jsr fc_unbuilt
        .word .ident(.concat("GP_", .string(target), "_N"))
  .elseif .ident(.concat("GP_", .string(target), "_G")) = 0
        .global target
        jsr target
  .elseif .ident(.concat("GP_", .string(target), "_G")) = FC_HERE
        .global target
        jsr target
  .else
        .global target
        jsr fc_call
        .byte .ident(.concat("GP_", .string(target), "_G"))
        .word target
  .endif
.endmacro
FC_HERE .set 0

; DCALL table: a call through a dispatch table (gcall.s dc_call), the
; entry's number in A (1 up; 0 none: no call)
.macro DCALL table
        ldx #<table
        ldy #>table
        jsr dc_call
.endmacro
'''
# the test groups of the skeleton's checks (S5: FCALL across slots), in the
# test image only (gtest.s): A and D in slot 1, C in slot 2
TEST_GROUPS = [{'slot': 1, 'routines': ['gt_fa', 'gt_fa2']},
               {'slot': 2, 'routines': ['gt_fc']},
               {'slot': 1, 'routines': ['gt_fd']}]
TEST_CORE = ['gt_fcore', 'gt_fb']


def gdisp_text(built: Sequence[str], graph=None,
               place: Optional[Dict[str, Any]] = None,
               test_place: bool = False) -> str:
    """gdisp.inc: each table's entries (3 bytes: the group, the address;
    an unbuilt entry the group $FE and its number); the actions' upstream
    addresses (ACT_ADDR, 3 bytes each, ACTTAB's order) for act_num."""
    place = placement_of(place)
    names = native_names()
    entries = dispatch_entries(graph)
    lines = ['; Generated by tools/native/glayout.py (docs/GAME.md 2.2). '
             'Do not edit.', '; built parts: %s' % (
                 ', '.join(built) or 'none'), '',
             '        .segment "GCORE"']
    imports = []
    for t_index, (table, keys) in enumerate(entries.items(), 1):
        lines.append('%s_N = %d' % (table, len(keys)))
        lines.append('%s:' % table)
        for i, key in enumerate(keys, 1):
            o = owner_of(key)
            n = names.get(key)
            if n and (o == 'core' or o in built):
                grp = place['routines'].get(key, 0)
                lines.append('        .byte %d, <%s, >%s   ; %d %s' % (
                    grp, n, n, i, key))
                imports.append(n)
            else:
                lines.append('        .byte $FE, %d, %d   ; %d %s '
                             '(unbuilt)' % (i, t_index, i, key))
        if test_place and table in HARNESS_ENTRIES:
            n = HARNESS_ENTRIES[table]
            lines.append('        .byte 0, <%s, >%s   ; the harness\'s'
                         % (n, n))
            imports.append(n)
            lines.append('%s_HARNESS = %d' % (table, len(keys) + 1))
    # the actions' upstream addresses (the states' action field)
    act = entries['ACTTAB']
    lines.append('ACT_ADDR:')
    if graph is not None:
        from bridge.linkmap import Symbols
        sym = Symbols()
        for key in act:
            try:
                a = sym.address(key) if not key.startswith('?') else 0
            except KeyError:
                a = 0
            lines.append('        .byte $%02X, $%02X, $%02X   ; %s' % (
                a & 0xFF, a >> 8 & 0xFF, a >> 16 & 0xFF, key))
    lines.append('ACT_ADDR_N = %d' % len(act))
    if imports:
        lines.insert(4, '        .import ' + ', '.join(sorted(set(
            imports))))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# game.cfg
# ---------------------------------------------------------------------------

def game_cfg(place: Optional[Dict[str, Any]] = None,
             test_place: bool = False) -> str:
    """ld65's map of the tic images: W's MATHW and AUXW, the core
    ($6600-$97FF: GCORE), each group at its slot's address with its own
    output file, the card's segments as the render images have them, the
    test driver's $E000 part; the memory API's transport AMEMLC in LC1
    at AMEM_LC."""
    place = placement_of(place)
    groups = list(place['groups']) + (TEST_GROUPS if test_place else [])
    lines = ['# Generated by tools/native/glayout.py (docs/GAME.md 3.2, '
             '4.1). Do not edit.', 'MEMORY {',
             '    W:    start = $6000, size = $0600, file = "%O.w";',
             '    CORE: start = $%04X, size = $%04X, file = "%%O.core";' % (
                 WR['CORE'][0], WR['CORE'][1] - WR['CORE'][0])]
    for i, g in enumerate(groups, 1):
        lo, hi = slot_range(groups, int(g['slot']))
        lines.append('    G%d:   start = $%04X, size = $%04X, file = '
                     '"%%O.g%d";' % (i, lo, hi - lo, i))
    lines += ['    LC1:  start = $D800, size = $0400, file = "%O.lc1";',
              '    FAR:  start = $DC00, size = $0400, file = "%O.far";',
              '    LCE:  start = $E000, size = $0E00, file = "%O.lce";',
              '    VEC:  start = $FFFA, size = $0006, file = "%O.vec";',
              '}', 'SEGMENTS {',
              '    MATHLC:  load = LC1, type = ro;',
              '    AMEMLC:  load = LC1, type = rw, start = $%04X, define = '
              'yes;' % AMEM_LC[0],
              '    MATHFAR: load = FAR, type = ro;',
              '    RFAR:    load = FAR, type = rw;',
              '    RLOAD:   load = FAR, type = ro;',
              '    MATHW:   load = W,   type = ro, define = yes;',
              '    AUXW:    load = W,   type = rw, define = yes;',
              '    GCORE:   load = CORE, type = rw, define = yes;',
              '    LOADW:   load = CORE, type = rw, define = yes, '
              'optional = yes;']
    for i in range(1, len(groups) + 1):
        lines.append('    GGRP%d:   load = G%d, type = rw, define = yes, '
                     'optional = yes;' % (i, i))
    lines += ['    DRIVER:  load = LCE, type = rw;',
              # (aligned: gdriver.s's page lists may not cross a page)
              '    DESC:    load = LCE, type = bss, align = $20, '
              'define = yes;',
              '    VECTORS: load = VEC, type = ro, optional = yes;', '}',
              'SYMBOLS {',
              '    __RENDERW_RUN__:  type = export, value = $6600;',
              '    __RENDERW_SIZE__: type = export, value = 0;',
              '}']
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def write_all(out: Path, built: Sequence[str], test_place: bool = False,
              manifests: bool = True) -> List[Path]:
    from native import gcallgraph as CG
    gen = out / 'gen'
    gen.mkdir(parents=True, exist_ok=True)
    graph = CG.load(write=out.resolve() == SHARED.resolve())
    files = []
    for name, text in (('ggame.inc', ggame_text()),
                       ('gplace.inc', gplace_text(built,
                                                  test_place=test_place)),
                       ('gdisp.inc', gdisp_text(built, graph,
                                                test_place=test_place))):
        p = gen / name
        if not p.exists() or p.read_text() != text:
            p.write_text(text)
        files.append(p)
    p = out / 'game.cfg'
    text = game_cfg(test_place=test_place)
    if not p.exists() or p.read_text() != text:
        p.write_text(text)
    files.append(p)
    if manifests:
        files += write_manifests(out)
    if out.resolve() == SHARED.resolve():
        # the shared outputs are made now, whether or not their text
        # changed: the part tests' freshness checks compare their times
        # with the layouts' (a part's own GEN keeps its times: make's)
        for f in files:
            os.utime(str(f), None)
    return files


def write_manifests(out: Path) -> List[Path]:
    from native import lstore
    meta_path = lstore.STORE / 'store.json'
    if not meta_path.exists():
        return []
    meta = json.loads(meta_path.read_text())
    syms = LL.symbol_list()
    index = {'format': 'native-game-manifests 1', 'maps': {}}
    d = out / 'manifests'
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for m in range(1, 10):
        key = 'E1M%d' % m
        if key not in meta['maps']:
            continue
        h = dict(meta['maps'][key]['header'], map=m)
        p = d / ('native-game-1-e1m%d.json' % m)
        text = json.dumps(manifest(h, syms), indent=0) + '\n'
        if not p.exists() or p.read_text() != text:
            p.write_text(text)
        index['maps'][key] = str(p.relative_to(out))
        files.append(p)
    p = out / 'native-game-1.json'
    p.write_text(json.dumps(index, indent=1) + '\n')
    return files + [p]


def report() -> List[str]:
    out = ['W in the tic phase (docs/GAME.md 4.1):']
    for name, lo, hi, what in W_MAP:
        out.append('  %-8s $%04X-$%04X %6d B  %s' % (name, lo, hi - 1,
                                                    hi - lo, what))
    out.append('  the API\'s W: %d of %d B used' % (LL.GW_USED - LL.GW,
                                                  LL.GW_END - LL.GW))
    groups = placement_of()['groups']
    fs = frame_slots(groups)
    out.append('main $%04X-$%04X, the frame slots (the colormaps\' place '
               'in the tic phase): %d of %d pages' % (
                   FRAME_REGION[0], FRAME_REGION[1] - 1,
                   sum(hi - lo for lo, hi in fs.values()) >> 8,
                   (FRAME_REGION[1] - FRAME_REGION[0]) >> 8))
    for s, (lo, hi) in sorted(fs.items()):
        g = next(i for i, x in enumerate(groups, 1) if x['slot'] == s)
        out.append('  slot %-3d $%04X-$%04X  group %d (%s B)' % (
            s, lo, hi - 1, g, groups[g - 1].get('bytes', '?')))
    out.append('main:')
    for name, lo, hi, what in MAIN_TIC:
        out.append('  %-8s $%04X-$%04X %6d B  %s' % (name, lo, hi - 1,
                                                    hi - lo, what))
    out.append('  globals $%04X-$%04X (%d B of $%04X-$1FFF)' % (
        LL.GBLOCK, LL.GLOBALS_END - 1, LL.GLOBALS_END - LL.GBLOCK,
        LL.GBLOCK))
    out.append('  runtime state %d of %d B' % (RT_USED,
                                               LL.RT_END - LL.RT_STATE))
    uses = dict(LL.bank_map())
    out.append('banks: %d of %d used (test builds), spare %s' % (
        len(uses), LL.BANKS_TOTAL, ', '.join(str(b) for b in LL.SPARE)))
    sb = scratch_blocks()
    out.append('scratch blocks: %d parts, $%04X-$%04X' % (
        len(sb), min(a for a, _ in sb.values()),
        max(a + n for a, n in sb.values()) - 1))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=SHARED)
    parser.add_argument('--built', default=None,
                        help='the built parts, separated by "+" ("none": '
                             'none; default: the integrated waves\', '
                             'src/native/game/integrated.txt)')
    parser.add_argument('--no-manifests', action='store_true')
    parser.add_argument('--part', default=None,
                        help='a part\'s own GEN: the earlier waves, the '
                             'integrated waves and the part counted as '
                             'built')
    parser.add_argument('--test-place', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--ggame', type=Path,
                        help='write gen/ggame.inc alone (level.mk: the '
                             'load image\'s game core)')
    args = parser.parse_args(argv)
    if args.ggame:
        args.ggame.parent.mkdir(parents=True, exist_ok=True)
        text = ggame_text()
        if not args.ggame.exists() or args.ggame.read_text() != text:
            args.ggame.write_text(text)
        return 0
    if args.check:
        check()
        print('glayout check: ok')
        return 0
    if args.report:
        check()
        print('\n'.join(report()))
        return 0
    if args.part:
        p = next((q for q in PARTS if q['name'] == args.part), None)
        if p is None:
            print('no part %s' % args.part, file=sys.stderr)
            return 2
        # the earlier waves, the integrated waves (a part of an integrated
        # wave is rerun with its wave's other parts and every later wave
        # integrated: wave 1 as integrated) and the part
        built = built_set(max(p['wave'] - 1, integrated_waves()),
                          [args.part])
    elif args.built is not None:
        built = [b for b in args.built.replace(',', '+').split('+')
                 if b and b != 'none']
    else:
        built = built_set()
    for f in write_all(args.out, built, args.test_place,
                       manifests=args.part is None and
                       not args.no_manifests):
        print(f)
    return 0


if __name__ == '__main__':
    sys.exit(main())
