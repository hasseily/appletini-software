"""Every address, bank, record layout and zero-page byte of the native
renderer front end (milestone 7, docs/RENDER.md sections 1.3, 1.7, 1.8,
2.1, 3.3 and 3.4), in one place.

`include_text()` writes rlayout.inc for ca65 (src/native/render.mk runs
`python3 tools/native/rlayout.py OUT/rlayout.inc`), so the assembler, the
level converter (levelconv.py), the frame injection (framestate.py) and
the harness (render_check.py) always agree. `check()` fails on an overlap
between regions, on a zero-page byte outside its owner's range, on a
frame block past 96 bytes, and on a region that collides with milestone
5's (tools/native/layout.py); the build runs it.

Stage A (this file's first version) owns the level layout, the frame
block, overlay 1 of the zero page, the far layer's bytes and the W
scratch of the BSP walk. Stage B adds overlay 2 (the seg page, the hot
part of the seg descriptor SEGD), the spill of the wall setup and the
seg descriptor's cold part, the drawsegs and openings, the record
staging and the W scratch of the seg loops. Stage C adds the frame's
own parts: the sky's slots in the frame block, the seam's weapon
vissprite, the weapon skip's and the plane stamps' writes, and the
render window image (the CODE bank and the ranges the phase loader
copies).
"""

import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import layout as L5  # noqa: E402

# ---------------------------------------------------------------------------
# RamWorks banks of the harness (RENDER.md 1.8). The game's allocation is
# milestone 11's; a move is one edit here.
# ---------------------------------------------------------------------------
LVSEG = 6                       # segs
LVMAP = 7                       # nodes, subsectors, vertex cache, sectors,
                                #   sides, patchless bitmaps
RENDB = 8                       # drawsegs, OPENHI (stage B)
RECSP = (9, 10)                 # record spill (stage B): consecutive
DRAWSEGS = 0x0200               #   RENDB: 128 drawsegs of DS_SIZE bytes
MAXDRAWSEGS = 128
OPENHI = 0x1200                 #   RENDB: the openings' high bytes
MAXOPENINGS = 2560
OPENLO = 0x0C00                 # aux 0: the openings' low bytes
STAGE, STAGE_END = 0xA000, 0xC000       # aux 0: the record staging
TEX_FIRST, TEX_LAST = 11, 30    # texel slots, sky slots
SEAM = 31                       # harness only: the weapon-clip seam and
                                #   checkpoint A's lockstep data
SEAM_HDR = 0x0200               #   +0: the reference's wall calls
SEAM_FLOOR = 0x0300             #   floorclip after the clip pass (160)
SEAM_FRVIS = 0x03A0             #   FR_VIS after the clip pass (42)
SEAM_WPOK = 0x03CA              #   MM_WPOK after it: 1 when $5AA5
SEAM_CALLS = 0x0400             #   the stub's call records
SEAM_CALLREC = 16
SEAM_MAXCALLS = 256
SEAM_SOLID = SEAM_CALLS + SEAM_CALLREC * SEAM_MAXCALLS
SEAM_SOLID_MAX = (0xC000 - SEAM_SOLID) // 160
CODE = (112, 113, 114, 115)     # the render window image (stage C):
WCODE_BANK = CODE[0]            #   the image at its own addresses in the
                                #   first (one bank holds it)
FSTEP_BANKS = (116, 117, 118, 119)
MT_TBANK, MT_RLO, MT_RHI = 120, 121, 122        # src/native/math.inc
BANK_ROOM = (0x0200, 0xC000)    # what RAMRD reaches of a RamWorks bank


class Array(NamedTuple):
    """An array of records in a RamWorks bank."""
    name: str
    bank: int
    base: int
    stride: int
    capacity: int

    @property
    def end(self) -> int:
        return self.base + self.stride * self.capacity

    def address(self, index: int) -> int:
        if not 0 <= index < self.capacity:
            raise IndexError('%s %d: capacity %d' % (self.name, index,
                                                     self.capacity))
        return self.base + self.stride * index


# ---- the records (RENDER.md 1.3) ----------------------------------------
# Seg, 24 bytes: the end points, offset, angle, side, line (2 each), the
# front and back sectors (1 each, $FF: one sided), the native numbers of
# v1 and v2 (2 each), the line's peg flags (ML_DONTPEGTOP, ML_DONTPEGBOTTOM),
# a pad byte.
SEG = {'V1X': 0, 'V1Y': 2, 'V2X': 4, 'V2Y': 6, 'OFFSET': 8, 'ANGLE': 10,
       'SIDE': 12, 'LINE': 14, 'FRONT': 16, 'BACK': 17, 'V1N': 18,
       'V2N': 20, 'PEGS': 22}
SEG_SIZE = 24
# Node, 32 bytes: x, y, dx, dy, bbox[0] (top, bottom, left, right),
# bbox[1], children[0], children[1] (bit 15: a subsector), pad.
NODE = {'X': 0, 'Y': 2, 'DX': 4, 'DY': 6, 'BOX0': 8, 'BOX1': 16,
        'CH0': 24, 'CH1': 26}
BOX = {'TOP': 0, 'BOTTOM': 2, 'LEFT': 4, 'RIGHT': 6}
NODE_SIZE = 32
# Subsector, 4 bytes: sector, seg count, first seg.
SUB = {'SECTOR': 0, 'COUNT': 1, 'FIRST': 2}
SUB_SIZE = 4
# Sector, render part, 16 bytes: floor and ceiling heights (fixed_t),
# floor and ceiling pics, light level (bytes), validcount (a word), pad.
SEC = {'FLOOR': 0, 'CEIL': 4, 'FPIC': 8, 'CPIC': 9, 'LIGHT': 10,
       'VALID': 11}
SEC_SIZE = 16
# Side, render part, 8 bytes: texture offset, row offset (words), top,
# bottom, mid texture (bytes), pad.
SIDE = {'TEXOFS': 0, 'ROWOFS': 2, 'TOP': 4, 'BOTTOM': 5, 'MID': 6}
SIDE_SIZE = 8
NO_SECTOR = 0xFF                # a seg's back sector when one sided
# Drawseg, 32 bytes (RENDB): the seg (its number), x1, x2, scale1, scale2,
# scalestep, silhouette, bsilheight, tsilheight, sprtopclip, sprbottomclip
# (an opening index less x1, or DS_SCREENH: screenheightarray, DS_NEGONE:
# negonearray), maskedtexturecol (the same, or DS_NULL). The opening
# index less x1 lies in -160..2560, so the markers cannot be one
DS = {'SEG': 0, 'X1': 2, 'X2': 3, 'SCALE1': 4, 'SCALE2': 8, 'STEP': 12,
      'SIL': 16, 'BSIL': 17, 'TSIL': 21, 'TOPCLIP': 25, 'BOTCLIP': 27,
      'MASKED': 29}
DS_SIZE = 32
DS_SCREENH, DS_NEGONE, DS_NULL = 0x7FFF, 0x7FFE, 0x8000

SEGS = Array('seg', LVSEG, 0x0200, SEG_SIZE,
             (BANK_ROOM[1] - 0x0200) // SEG_SIZE)
NODES = Array('node', LVMAP, 0x0200, NODE_SIZE, 768)
SUBS = Array('subsector', LVMAP, NODES.end, SUB_SIZE, 768)
VTX_CAP = 1536
VAL = SUBS.end                  # vertex angle, low bytes (by native number)
VAH = VAL + VTX_CAP             #   high bytes
VAS = VAH + VTX_CAP             #   stamps
VTX_STRIDE = VTX_CAP
SECTORS = Array('sector', LVMAP, 0x8000, SEC_SIZE, 255)
SIDES = Array('side', LVMAP, 0x9000, SIDE_SIZE, 1024)
TXFLAT = 0xB000                 # patchless-column bitmaps (stage B)
TXFLAT_END = 0xC000
assert VAS + VTX_CAP <= SECTORS.base
assert SECTORS.end <= SIDES.base and SIDES.end <= TXFLAT

# ---------------------------------------------------------------------------
# Main memory (RENDER.md 1.7)
# ---------------------------------------------------------------------------
SEGBUF = 0x0200                 # far bounce buffer: 5 segs of 24 bytes
SEGBUF_SEGS = 5
SPILL, SPILL_END = 0x0280, 0x0300
PHASE = L5.PHASE                # $0300: the cost phase (test builds)
FB, FB_END = 0x0310, 0x0370     # the render frame block, 96 bytes
RIN, RIN_END = 0x0370, 0x03A0   # the render inputs: the player's view,
                                #   which milestone 10's game state
                                #   will keep (framestate.py writes it)
LVCOUNT = 0x03A0                # the level's counts of sectors and sides
                                #   (words), for the bridge manifest of
                                #   levelconv.py (sectors-sides.json)
FRVIS = 0x0CA0                  # this frame's weapon vissprite (stage C)
VIS_SIZE = 42                   # upstream's vissprite_t (offsets.inc)
VIS_LUMP, VIS_COLORMAP = 34, 38
WPREV_USED = VIS_SIZE           # WPREV holds upstream's vissprite
FLOORCLIP, CEILCLIP, SOLIDCOL = 0x0C00, 0x0D00, 0x0E00
FSTOP, FSBOT = L5.FSTOP, L5.FSBOT       # fill spans (persistent)
SPANS, SPANS_END = 0x0F00, 0x1400
CVFIRST, CV_END = L5.CVFIRST, 0x1680    # covered ranges
WCLIP, WPREV, WTMP = L5.WCLIP, L5.WPREV, L5.WTMP
DSX1, DSX2 = 0x1980, 0x1A00
TEXTRANS = 0x1A80               # texturetranslation as bytes
LNMAP = 0x1B80                  # ML_MAPPED of each line, a bit, 2,048
LNMAP_LINES = 2048

# W, the render window (RENDER.md 3.4)
WCODE, WCODE_END = 0x6000, 0xAFC0
FLATCM, FLATCM_END = 0xAFC0, 0xB400     # 34 x 32
TXBANK, TXLO, TXHI, TXWM, TXHT = 0xB400, 0xB500, 0xB600, 0xB700, 0xB800
TXTAB_END = 0xB900
# The render window image the phase loader copies from WCODE_BANK each
# frame (RENDER.md 3.4): the code from $6000 to its end, and the per-level
# tables. Whole pages: the tables' pages start at $AF00 (FLATCM at $AFC0)
WTABLES_PAGE = 0xAF
WTABLES_PAGES = (TXTAB_END >> 8) - WTABLES_PAGE
BATCH = 0xB900                  # the record batch buffer (stage B)
NODEF, NODEF_END = 0xBA00, 0xBC80       # node frames: 20 x 32
NODEF_DEPTH = 20
FSTEPW = 0xBC80                 # stage B
MASKW = 0xBDC0                  # stage B
FSTEPLO, FSTEPHI = FSTEPW, FSTEPW + 160    # each column's FSTEP
MASKLO, MASKHI = MASKW, MASKW + 160        # each column's masked texture
FSEC = 0xBF00                   # the wall's front sector (16)
FSIDE = 0xBF10                  #   its side (8, stage B)
BSEC = 0xBF18                   #   its back sector (16, stage B)
WSCR, WSCR_END = 0xBF28, 0xC000
DLW = 0xBF28                    # each column's light distance d (160)
DSBUF = 0xBFC8                  # the drawseg being built (DS_SIZE)
SWVAR, SWVAR_END = 0x0DA0, 0x0E00       # main: the wall setup's variables

# The card: MATHFAR at $DC00 (67 bytes, src/native/MATH.md), then far.s
FAR_CARD = 0xDC43
FAR_CARD_END = 0xE000

# The aux card, F1.2.1 (RENDER.md 1.6; MEMORY_MAP.md 4.3 with the
# viewangletox correction): read in ALTZP windows from W.
AX_TAN3 = 0xD000                # finetangent part 3: low, high planes
AX_VTOX = 0xD800                # viewangletox, 2,042 bytes, one plane
VTOX_ENTRIES = 2042
AX_TAN4 = 0xD000                # part 4, card bank 2: four planes
AX_TANTO = 0xE000               # tantoangle 0-2047: four planes of 2,048

# ---------------------------------------------------------------------------
# Constants of upstream's renderer (offsets.inc, r_bsp65.s)
# ---------------------------------------------------------------------------
VIEWWIDTH = 160
VIEWHEIGHT = 168
CENTERY = 84
PROJECTIONY = 160
XTVLO, XTVHI = 0x09A9, 0x0AF3   # xtoviewangle (MEMORY_MAP.md 3.2)
CLIPANGLE = 0x2008              # xtoviewangleTable[0]
VIEWANGLETOXMAX = 1032
PLANE_D = 10
NF_SUBSECTOR = 0x8000

# ---------------------------------------------------------------------------
# Zero page (RENDER.md 3.3)
# ---------------------------------------------------------------------------
ZP_FAR = (0x00, 0x06)
ZP_PLATFORM = (0x08, 0x18)
ZP_OV1 = (0x18, 0x42)           # overlay 1: the BSP and wall setup
ZP_FORBIDDEN = (0x42, 0x48)     # no symbol (MEMORY_MAP.md)
ZP_OV2 = (0x48, 0xB0)           # overlay 2: the seg page (stage B)
ZP_MATH = (0xB0, 0xD8)          # src/native/math.inc
ZP_IRQ = (0xD8, 0x100)

FAR_ZP = [('FA_DST', 2), ('FA_SRC', 2), ('FA_BANK', 1), ('FA_N', 1)]
# Overlay 1, stage A: the walk's state, all of it live across the call of
# nr_storewall (stage B's wall setup takes the bytes after it).
OV1_A = [
    ('FRP', 2),         # the node frame of this level of the walk (W)
    ('BP', 2),          # a box of that node (checkbox), a table pointer
    ('BS_F', 1),        # the first column not solid (160: all solid)
    ('BS_FIRST', 1),    # clipwall's first, last, to (columns 0-160)
    ('BS_LAST', 1),
    ('BS_TO', 1),
    ('BS_A1', 2),       # checkbox: angle1 + $8000; the segs: angle2
    ('BS_SPAN', 2),     # angle1 - angle2
    ('BS_T1', 2),       # tspan of angle1
    ('BS_SEG', 2),      # the seg (its number)
    ('SEGR', 2),        # its record in the bounce buffer
    ('BS_SUBN', 2),     # the next seg of the subsector to fetch
    ('BS_LEFT', 1),     # the subsector's segs not yet fetched
    ('BS_BATCH', 1),    # segs in the bounce buffer
    ('BS_K', 1),        # the seg of the batch
    ('SC_CUR', 1),      # the sector of the subsector
    ('CN_LSEC', 1),     # the sector of the subsector before ($FF: none)
    ('FPC', 2),         # floor, ceiling plane colour ($FFFF none, $FFFE
    ('CPC', 2),         #   sky, else the FLATCM byte)
    ('T0', 4),          # temporaries of the walk
]
# Overlay 2, stage B: the seg loop's page, the hot part of the seg
# descriptor SEGD (RENDER.md 3.2, 3.3). The edges keep upstream's forms
# (topfrac FRACUNIT - 1 more, bottomfrac and pixhigh FRACUNIT more, pixlow
# FRACUNIT - 1 more, each one step early: r_seg65.s:15-17), each start
# then its step, as in WPAGE.
OV2_B = [
    ('TF', 4), ('TS', 4), ('BF', 4), ('BS', 4),
    ('PH', 4), ('PHS', 4), ('PL', 4), ('PLS', 4),
    # the rows of a column (bytes, segvar.inc)
    ('YL', 1), ('YH1', 1), ('CT', 1), ('FC', 1), ('FCR', 1), ('CB1', 1),
    ('FT', 1), ('CC1', 1), ('FC1', 1), ('MID1', 1), ('MID', 1),
    ('DCROW', 1), ('DCCOUNT', 1), ('DCFSTEP', 2),
    ('X2END', 1),       # rw_stopx: the column after the seg
    # texCol's state
    ('TCX', 1), ('TEXCOL', 2), ('UF8', 1), ('UDI', 2), ('UDF', 1),
    ('UC', 1), ('UI', 4), ('UN', 4), ('UF', 2), ('TAN', 4),
    # the seg's flags and light
    ('WCMP', 1), ('WLV', 1), ('WSKY', 1),
    ('WMC', 1), ('WMF', 1), ('WSEGTEX', 1),
    ('WMIDTEX', 1), ('WTOPTEX', 1), ('WBOTTEX', 1), ('WMASKED', 1),
    ('MIDTM', 2), ('TOPTM', 2), ('BOTTM', 2),
    ('RB', 1),          # the record batch's bytes (W BATCH)
    ('FRAC', 2), ('SRC', 3), ('GT', 4),
    ('GSC', 3), ('GSS', 3),     # far_fstep: the scale (one step early),
                                #   its step (24 bits, as STEP8)
    ('WDID', 1),                # upstream's W_DIDSOLID: a column became
]                               #   solid in this seg
# The spill, stage A (absolute: one cycle more an access)
SPILL_A = [
    ('WBOT', 4),        # worldbottom: floorheight - viewz
    ('BS_CM', 2),       # the plane colormap row of the sector (cm * 32)
    ('SD_L', 4),        # viewSide: the first product
    ('SUBREC', 4),      # the subsector's record
    ('NB_N', 2),        # nr_bsp: the root
    # stage B: the seg descriptor's cold part (what R_RenderSegLoop reads
    # of R_StoreWallRange's globals), genColumn's words
    ('SD_X', 1),        # rw_x
    ('SD_SCALE', 4),    # rw_scale (= the drawseg's scale1)
    ('SD_SCALE2', 4),   # the drawseg's scale2
    ('SD_DIST', 2),     # rw_distance
    ('SD_LIGHT', 1),    # rw_lightlevel
    ('SD_NORMAL', 2),   # rw_normalangle
    ('SD_OFFSET', 2),   # rw_offset
    ('SD_CANGLE', 2),   # rw_centerangle
    ('SD_MIDMID', 4), ('SD_TOPMID', 4), ('SD_BOTMID', 4),  # texturemids
    ('SD_MASKB', 2),    # maskedtexturecol: its opening index - rw_x
    ('GYL', 2), ('GYH', 2), ('GTOP', 2), ('GCC', 2), ('GFC', 2),
    ('GBOT', 2), ('GMID', 2),
    ('GFLAG', 1),       # far_fstep: a column's scale past 64.0
]
# The wall setup's variables (main $0DA0-$0DFF, RENDER.md 1.7's render
# scratch): what R_StoreWallRange keeps in its znear
SWVARS = [
    ('SW_START', 1), ('SW_LF', 1), ('SW_SIL', 1), ('SW_OPEN', 1),
    ('SW_EDGES', 1), ('SW_EO', 1), ('SW_ER', 1), ('SW_LZ', 1),
    ('SW_OFF', 2), ('SW_TH', 2), ('SW_R', 2), ('SW_AL', 2),
    ('SW_D', 4), ('SW_CS', 4), ('SW_CSS', 4),
    ('WTOP', 4), ('WHIGH', 4), ('WLOW', 4),
    ('SW_DX', 2), ('SW_DY', 2), ('SW_M', 2), ('SW_BS', 1), ('SW_O', 4),
    ('SW_P', 4), ('SW_Q', 4), ('SW_T', 4), ('SW_S1', 2), ('SW_EQ', 1),
]


# The frame block, $0310-$036F (RENDER.md 2.1): what the frame's code
# computes and the persistent state of the renderer. Offsets from FB.
FRAME_BLOCK = [
    ('VIEWX', 4), ('VIEWY', 4), ('VIEWZ', 4), ('VIEWANGLE', 4),
    ('VIEWA16', 2), ('VIEWSIN', 4), ('VIEWCOS', 4),
    ('EXTRALIGHT', 2), ('LT_BASE', 2), ('LT_FIXED', 2), ('LT_I', 2),
    ('VALIDCOUNT', 2), ('NUMNODES', 2),
    ('VIEWTOP', 1), ('VIEWBOT', 1), ('NUKAGE', 1), ('SKYFLAT', 1),
    ('AUTOMAP', 1), ('PSPF', 1),
    ('W_FSC', 1), ('W_FSP', 1), ('W_TOPR', 1), ('W_BOTR', 1),
    ('W_FSG', 1), ('W_FSW', 1),
    ('FR_SKIP', 2), ('W_WSK', 1), ('MM_WPOK', 1),
    ('VA_VX', 2), ('VA_VY', 2), ('VA_STAMP', 1), ('NVERT', 2),
    ('STG_PTR', 2),
    ('DSCOUNT', 1), ('LASTOPEN', 2),
    ('STATUS', 1), ('VA_COUNT', 2),
    # the rules of our own the frame ran (RULE_*; 0 when upstream stays in
    # its tables)
    ('RULES', 1),
    # stage B: the plane colours of the fill bytes and the fill bytes
    # (upstream's W_LCC, W_LFC, W_CEILW, W_FLOORW: kept from wall to wall,
    # reset by R_FillStamps), didsolidcol, rw_scalestep (kept from wall to
    # wall: a one-column wall of scaleSlow reads the last one, RENDER.md
    # "Stage B as built"), the staging's bank (0: aux 0)
    ('W_LCC', 2), ('W_LFC', 2), ('W_CEILW', 2), ('W_FLOORW', 2),
    ('DIDSOLID', 1), ('RW_STEP', 4), ('STG_BANK', 1),
    # stage C: the sky's 256 slots (the level's: RENDER.md 1.4), bank and
    # address of slot 0
    ('SKYBANK', 1), ('SKYLO', 1), ('SKYHI', 1),
]
FRAME_BLOCK_SIZE = FB_END - FB
# The render inputs, $0370-$039F: the player's view and settings, from
# the game state (upstream: player_t, mobj_t, _g_gamma).
RENDER_INPUTS = [
    ('PL_X', 4), ('PL_Y', 4), ('PL_ANGLE', 4), ('PL_VIEWZ', 4),
    ('PL_XLIGHT', 2), ('PL_FIXCM', 2), ('GAMMA', 2),
]

# Frame status codes (STATUS). Every build (there is no other yet)
# stops the frame with BRK and the code after it. ST_DEPTH the node frames
# are full and ST_TEXTURE a texture the level has no slots for: neither
# happens on a level levelconv.py accepts (it checks the BSP's depth, and
# converts the textures the level source made; RENDER.md 1.4). ST_RECORDS
# the staging and the spill are full: the game's behaviour is milestone
# 8's decision (RENDER.md 3.6, risk 14). Codes 3 and 4 were stage B's hooks
# for the sky and the patchless columns, 6 (ST_TANGENT) and 7 (ST_SINE)
# its refusals of a column seen from behind: all four are no longer used.
ST_OK, ST_DEPTH, ST_RECORDS = 0, 1, 2
ST_TEXTURE = 5

# The rules of our own (RULES, a bit each; RENDER.md 3.9): where upstream
# leaves its tables for a column seen from behind (a grazing view), the
# native code takes a defined value and sets its bit. RULE_SINE:
# R_ScaleFromGlobalAngle with sin(angleb) < 0 (upstream's sineLow reads its
# own code in bank 3) gives the scale 256, vanilla DOOM's result.
# RULE_TANGENT: a texture angle of 4096 or more (upstream's tcExact reads
# past finetangent part 4) is clamped to the table's end, 4095 below 6144
# and 0 from 6144.
RULE_SINE, RULE_TANGENT = 1, 2

# The render phase's stack budget with the IRQ's allowance on top
# (MEMORY_MAP.md 2; the tests check the measured depth + IRQ_STACK)
RENDER_STACK, IRQ_STACK = 112, 24

# The card's data of the far layer (far.s): the vertex-angle gather
VG_MAX = 2 * SEGBUF_SEGS


def allocate(fields: Sequence[Tuple[str, int]], start: int, end: int
             ) -> Dict[str, int]:
    out, at = {}, start
    for name, size in fields:
        if name in out:
            raise ValueError('%s twice' % name)
        out[name] = at
        at += size
    if at > end:
        raise ValueError('%s past $%04X (%d bytes of %d)' % (
            fields[-1][0], end, at - start, end - start))
    return out


FAR = allocate(FAR_ZP, *ZP_FAR)
ZP = allocate(OV1_A, *ZP_OV1)
ZP2 = allocate(OV2_B, *ZP_OV2)
SPILLS = allocate(SPILL_A, SPILL, SPILL_END)
SWV = allocate(SWVARS, SWVAR, SWVAR_END)
FBO = allocate(FRAME_BLOCK, 0, FRAME_BLOCK_SIZE)
FRAME = {k: FB + v for k, v in FBO.items()}
RINS = allocate(RENDER_INPUTS, RIN, RIN_END)
OV1_USED = max(ZP.values()) + dict(OV1_A)[max(ZP, key=ZP.get)] - ZP_OV1[0]


def frame_block_used() -> int:
    return sum(size for _, size in FRAME_BLOCK)


# ---------------------------------------------------------------------------
# Regions, and their checks
# ---------------------------------------------------------------------------

class Region(NamedTuple):
    space: str                  # main, w, card1, aux-card, bankN
    start: int
    end: int
    what: str


def regions() -> List[Region]:
    out = [
        Region('main', SEGBUF, SEGBUF + SEGBUF_SEGS * SEG_SIZE,
               'bounce buffer: 5 segs'),
        Region('main', SPILL, SPILL_END, 'zero-page spill'),
        Region('main', PHASE, PHASE + 1, 'cost phase'),
        Region('main', FB, FB_END, 'frame block'),
        Region('main', RIN, RIN_END, 'render inputs'),
        Region('main', LVCOUNT, LVCOUNT + 4, 'level counts'),
        Region('main', FLOORCLIP, FLOORCLIP + VIEWWIDTH, 'FLOORCLIP'),
        Region('main', FRVIS, FRVIS + VIS_SIZE, 'FRVIS'),
        Region('main', CEILCLIP, CEILCLIP + VIEWWIDTH, 'CEILCLIP'),
        Region('main', SOLIDCOL, SOLIDCOL + VIEWWIDTH, 'SOLIDCOL'),
        Region('main', SPANS, SPANS_END, 'fill spans'),
        Region('main', CVFIRST, CV_END, 'covered ranges'),
        Region('main', WCLIP, WCLIP + 0x180, 'weapon skip'),
        Region('main', DSX1, DSX2 + 0x80, 'DSX1, DSX2'),
        Region('main', TEXTRANS, TEXTRANS + 256, 'TEXTRANS'),
        Region('main', LNMAP, LNMAP + LNMAP_LINES // 8, 'LNMAP'),
        Region('w', WCODE, WCODE_END, 'render code'),
        Region('w', FLATCM, FLATCM_END, 'FLATCM'),
        Region('w', TXBANK, TXTAB_END, 'TX tables'),
        Region('w', BATCH, BATCH + 256, 'record batch'),
        Region('w', NODEF, NODEF_END, 'node frames'),
        Region('w', FSTEPW, MASKW, 'FSTEP of the seg'),
        Region('w', MASKW, FSEC, 'masked columns'),
        Region('w', FSEC, WSCR, 'sector frame'),
        Region('w', DLW, DLW + VIEWWIDTH, 'DLW'),
        Region('w', DSBUF, DSBUF + DS_SIZE, 'drawseg buffer'),
        Region('main', SWVAR, SWVAR_END, 'wall setup variables'),
        Region('card1', FAR_CARD, FAR_CARD_END, 'far layer'),
    ]
    for a in (NODES, SUBS, SECTORS, SIDES):
        out.append(Region('bank%d' % a.bank, a.base, a.end, a.name + 's'))
    out.append(Region('bank%d' % LVMAP, VAL, VAS + VTX_CAP, 'vertex cache'))
    out.append(Region('bank%d' % LVMAP, TXFLAT, TXFLAT_END, 'TXFLAT'))
    out.append(Region('bank%d' % LVSEG, SEGS.base, SEGS.end, 'segs'))
    out.append(Region('bank%d' % RENDB, DRAWSEGS,
                      DRAWSEGS + DS_SIZE * MAXDRAWSEGS, 'drawsegs'))
    out.append(Region('bank%d' % RENDB, OPENHI, OPENHI + MAXOPENINGS,
                      'OPENHI'))
    out.append(Region('aux0', OPENLO, OPENLO + MAXOPENINGS, 'openings'))
    out.append(Region('aux0', STAGE, STAGE_END, 'record staging'))
    return out


def check() -> None:
    """Overlaps, bounds and collisions with milestone 5's regions."""
    rs = regions()
    for i, a in enumerate(rs):
        if a.end <= a.start:
            raise ValueError('%s is empty' % a.what)
        if a.space.startswith('bank') and not (
                BANK_ROOM[0] <= a.start and a.end <= BANK_ROOM[1]):
            raise ValueError('%s is outside $0200-$BFFF' % a.what)
        for b in rs[i + 1:]:
            if a.space == b.space and a.start < b.end and b.start < a.end:
                raise ValueError('%s overlaps %s' % (a.what, b.what))
    if frame_block_used() > FRAME_BLOCK_SIZE:
        raise ValueError('the frame block takes %d of %d bytes'
                         % (frame_block_used(), FRAME_BLOCK_SIZE))
    for name, at in ZP.items():
        if not ZP_OV1[0] <= at < ZP_OV1[1]:
            raise ValueError('%s outside overlay 1' % name)
    for name, at in ZP2.items():
        if not ZP_OV2[0] <= at < ZP_OV2[1]:
            raise ValueError('%s outside overlay 2' % name)
    if SWV and max(SWV.values()) >= SWVAR_END:
        raise ValueError('the wall variables past $%04X' % SWVAR_END)
    if RECSP != tuple(range(RECSP[0], RECSP[0] + len(RECSP))):
        raise ValueError('the spill banks are not consecutive')
    # milestone 5: the replay's tables and the spans/ranges/weapon places
    # this layout shares must be where layout.py has them
    if (FSTOP, CVFIRST, WCLIP) != (L5.FSTOP, L5.CVFIRST, L5.WCLIP):
        raise ValueError('the spans moved from layout.py')
    for a in rs:
        if a.space == 'main' and a.start < L5.MAIN_TABLES_END and \
                L5.MAIN_TABLES < a.end:
            raise ValueError('%s is in the replay tables' % a.what)
        if a.space == 'main' and a.start < L5.SCRATCH_END and \
                L5.SCRATCH < a.end and a.what not in ('weapon skip',):
            raise ValueError('%s is in the replay scratch' % a.what)
        if a.space == 'main' and a.start < L5.COLHI + 161 and \
                L5.COLLO < a.end:
            raise ValueError('%s is in COLLO/COLHI' % a.what)


# ---------------------------------------------------------------------------
# rlayout.inc
# ---------------------------------------------------------------------------

def constants() -> List[Tuple[str, int]]:
    out = [
        ('LVSEG', LVSEG), ('LVMAP', LVMAP), ('SEAM', SEAM),
        ('SEAM_HDR', SEAM_HDR), ('SEAM_FLOOR', SEAM_FLOOR),
        ('SEAM_FRVIS', SEAM_FRVIS), ('SEAM_WPOK', SEAM_WPOK),
        ('VIS_SIZE', VIS_SIZE), ('VIS_LUMP', VIS_LUMP),
        ('VIS_COLORMAP', VIS_COLORMAP), ('WCLIP', WCLIP), ('WPREV', WPREV),
        ('WCODE_BANK', WCODE_BANK), ('WTABLES_PAGE', WTABLES_PAGE),
        ('WTABLES_PAGES', WTABLES_PAGES),
        ('TXFLAT_INDEX', TXFLAT), ('TXFLAT_MAPS', TXFLAT + 0x100),
        ('SEAM_CALLS', SEAM_CALLS), ('SEAM_CALLREC', SEAM_CALLREC),
        ('SEAM_MAXCALLS', SEAM_MAXCALLS), ('SEAM_SOLID', SEAM_SOLID),
        ('SEGBASE', SEGS.base), ('NODEBASE', NODES.base),
        ('SUBBASE', SUBS.base), ('SECBASE', SECTORS.base),
        ('SIDEBASE', SIDES.base),
        ('VAL', VAL), ('VAH', VAH), ('VAS', VAS), ('VTX_STRIDE', VTX_STRIDE),
        ('SEG_SIZE', SEG_SIZE), ('NODE_SIZE', NODE_SIZE),
        ('SUB_SIZE', SUB_SIZE), ('SEC_SIZE', SEC_SIZE),
        ('SIDE_SIZE', SIDE_SIZE), ('NO_SECTOR', NO_SECTOR),
        ('SEGBUF', SEGBUF), ('SEGBUF_SEGS', SEGBUF_SEGS),
        ('PHASE', PHASE), ('FB', FB), ('RIN', RIN),
        ('FLOORCLIP', FLOORCLIP), ('CEILCLIP', CEILCLIP),
        ('SOLIDCOL', SOLIDCOL), ('FRVIS', FRVIS),
        ('TEXTRANS', TEXTRANS), ('LNMAP', LNMAP),
        ('FLATCM', FLATCM), ('NODEF', NODEF), ('NODEF_END', NODEF_END),
        ('FSEC', FSEC), ('FSIDE', FSIDE), ('BSEC', BSEC),
        ('AX_VTOX', AX_VTOX), ('AX_TANTO', AX_TANTO), ('AX_TAN3', AX_TAN3),
        ('AX_TAN4', AX_TAN4),
        ('VIEWWIDTH', VIEWWIDTH), ('CLIPANGLE', CLIPANGLE),
        ('VIEWANGLETOXMAX', VIEWANGLETOXMAX), ('PLANE_D', PLANE_D),
        ('ST_OK', ST_OK), ('ST_DEPTH', ST_DEPTH),
        ('ST_RECORDS', ST_RECORDS), ('VG_MAX', VG_MAX),
        ('ST_TEXTURE', ST_TEXTURE),
        ('RULE_SINE', RULE_SINE), ('RULE_TANGENT', RULE_TANGENT),
        ('RENDB', RENDB), ('RECSP_FIRST', RECSP[0]),
        ('RECSP_LAST', RECSP[-1]), ('DRAWSEGS', DRAWSEGS),
        ('MAXDRAWSEGS', MAXDRAWSEGS), ('OPENHI', OPENHI),
        ('MAXOPENINGS', MAXOPENINGS), ('OPENLO', OPENLO),
        ('STAGE', STAGE), ('STAGE_END', STAGE_END),
        ('BATCH', BATCH), ('FSTEPLO', FSTEPLO), ('FSTEPHI', FSTEPHI),
        ('MASKLO', MASKLO), ('MASKHI', MASKHI), ('DLW', DLW),
        ('DSBUF', DSBUF), ('DS_SIZE', DS_SIZE),
        ('DS_SCREENH', DS_SCREENH), ('DS_NEGONE', DS_NEGONE),
        ('DS_NULL', DS_NULL),
        ('FSTOP', FSTOP), ('FSBOT', FSBOT), ('FSEVT', L5.FSEVT),
        ('FSEVB', L5.FSEVB), ('FSODT', L5.FSODT), ('FSODB', L5.FSODB),
        ('FSSTT', L5.FSSTT), ('FSSTB', L5.FSSTB),
        ('DSX1', DSX1), ('DSX2', DSX2),
        ('FSTEP0', FSTEP_BANKS[0]), ('XTVLO', XTVLO), ('XTVHI', XTVHI),
        ('CMAPA0', 0x2000), ('CMAPB0', 0x4000), ('CMAPA_PAGE', 0x46),
        ('VIEWHEIGHT', VIEWHEIGHT), ('CENTERY', CENTERY),
        ('PROJECTIONY', PROJECTIONY),
        ('TXBANK', TXBANK), ('TXLO', TXLO), ('TXHI', TXHI),
        ('TXWM', TXWM), ('TXHT', TXHT),
        ('SIL_BOTTOM', 1), ('SIL_TOP', 2), ('SIL_BOTH', 3),
        ('ML_DONTPEGTOP', 8), ('ML_DONTPEGBOTTOM', 16),
        ('K_TEX', 0), ('K_FILL', 2), ('TEXREC_SIZE', 12),
        ('FILLREC_SIZE', 6),
    ]
    out += [('DS_' + k, v) for k, v in DS.items()]
    out += [('SEG_' + k, v) for k, v in SEG.items()]
    out += [('ND_' + k, v) for k, v in NODE.items()]
    out += [('BX_' + k, v) for k, v in BOX.items()]
    out += [('SUB_' + k, v) for k, v in SUB.items()]
    out += [('SEC_' + k, v) for k, v in SEC.items()]
    out += [('SIDE_' + k, v) for k, v in SIDE.items()]
    out += sorted(SPILLS.items(), key=lambda x: x[1])
    out += sorted(SWV.items(), key=lambda x: x[1])
    out += sorted(FRAME.items(), key=lambda x: x[1])
    out += sorted(RINS.items(), key=lambda x: x[1])
    return out


def zeropage() -> List[Tuple[str, int]]:
    return sorted(FAR.items(), key=lambda x: x[1]) + \
        sorted(ZP.items(), key=lambda x: x[1]) + \
        sorted(ZP2.items(), key=lambda x: x[1])


def include_text() -> str:
    check()
    lines = ['; Generated by tools/native/rlayout.py. Do not edit.', '']
    for name, value in constants():
        lines.append('%-16s= $%04X' % (name, value))
    lines.append('')
    lines.append('; zero page')
    for name, value in zeropage():
        lines.append('%-16s= $%02X' % (name, value))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# What the render code may write (render_check.py filters a2vm's write log
# with it): storage, bank, [start, end) with the reason.
# ---------------------------------------------------------------------------

def allowed_writes(nsectors: int, nvertices: int
                   ) -> List[Tuple[str, int, int, int, str]]:
    """The fixed part. The card's own bytes the render code may write are
    labels of the build (render_check.allowed_sets adds them: the vertex
    gather's entries vg_n .. vg_d, the math's self-modified operands): the
    rest of card bank 1 $DC00-$DFFF is code, the phase loader's included."""
    out = [
        ('main', 0, ZP_FAR[0], ZP_FAR[1], 'far layer arguments'),
        ('main', 0, ZP_OV1[0], ZP_OV1[1], 'overlay 1'),
        ('main', 0, ZP_MATH[0], ZP_MATH[1], 'the math block'),
        ('main', 0, SEGBUF, SEGBUF + SEGBUF_SEGS * SEG_SIZE,
         'bounce buffer'),
        ('main', 0, SPILL, SPILL_END, 'spill'),
        ('main', 0, PHASE, PHASE + 1, 'cost phase'),
        ('main', 0, FB, FB_END, 'frame block'),
        ('main', 0, FLOORCLIP, FLOORCLIP + VIEWWIDTH, 'FLOORCLIP'),
        ('main', 0, CEILCLIP, CEILCLIP + VIEWWIDTH, 'CEILCLIP'),
        ('main', 0, SOLIDCOL, SOLIDCOL + VIEWWIDTH, 'SOLIDCOL'),
        ('main', 0, NODEF, NODEF_END, 'node frames'),
        ('main', 0, FSEC, FSEC + SEC_SIZE, 'sector frame'),
        ('aux', LVMAP, VAL, VAL + nvertices, 'vertex angles'),
        ('aux', LVMAP, VAH, VAH + nvertices, 'vertex angles'),
        ('aux', LVMAP, VAS, VAS + nvertices, 'vertex stamps'),
    ]
    for s in range(nsectors):
        a = SECTORS.address(s) + SEC['VALID']
        out.append(('aux', LVMAP, a, a + 2, 'sector %d validcount' % s))
    # stage C, the frame's own parts before the walk: the plane stamps
    # (R_FillStamps: the stamps of the spans, every 128 frames) and the
    # weapon skip (weaponClipSame: WPREV, WCLIP)
    out += [
        ('main', 0, L5.FSSTT, L5.FSSTT + VIEWWIDTH, 'top span stamps'),
        ('main', 0, L5.FSSTB, L5.FSSTB + VIEWWIDTH, 'bottom span stamps'),
        ('main', 0, WCLIP, WCLIP + VIEWWIDTH, 'WCLIP'),
        ('main', 0, WPREV, WPREV + WPREV_USED, 'WPREV'),
    ]
    return out


def allowed_writes_b(nsectors: int, nvertices: int
                     ) -> List[Tuple[str, int, int, int, str]]:
    """What the front end with stage B's wall setup and seg loops may
    write: stage A's set, and the seg page, the wall setup's variables,
    the spans (not the covered ranges), the drawseg columns, LNMAP, the
    record batch, W's scratch of the seg, the openings, the staging and
    spill, the drawsegs and OPENHI."""
    return allowed_writes(nsectors, nvertices) + [
        ('main', 0, ZP_OV2[0], ZP_OV2[1], 'overlay 2'),
        ('main', 0, SWVAR, SWVAR_END, 'wall setup variables'),
        ('main', 0, SPANS, SPANS_END, 'fill spans'),
        ('main', 0, DSX1, DSX2 + 0x80, 'DSX1, DSX2'),
        ('main', 0, LNMAP, LNMAP + LNMAP_LINES // 8, 'LNMAP'),
        ('main', 0, BATCH, BATCH + 256, 'record batch'),
        ('main', 0, FSTEPW, WSCR_END, 'W scratch of the seg'),
        ('aux', 0, OPENLO, OPENLO + MAXOPENINGS, 'openings'),
        ('aux', 0, STAGE, STAGE_END, 'record staging'),
        ('aux', RENDB, DRAWSEGS, OPENHI + MAXOPENINGS, 'drawsegs, OPENHI'),
    ] + [('aux', b, 0x0200, STAGE_END, 'record spill') for b in RECSP]


def main(argv: Sequence[str]) -> int:
    if len(argv) != 1:
        print('usage: rlayout.py OUT/rlayout.inc', file=sys.stderr)
        return 2
    Path(argv[0]).parent.mkdir(parents=True, exist_ok=True)
    Path(argv[0]).write_text(include_text())
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
