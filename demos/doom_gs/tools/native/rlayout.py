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

Milestone 8 (docs/RENDER-MASKED.md 1.3-1.10), stage A, adds the sprite
data (the patch store, the sprite tables, the render things), the masked
phase's W map, zero page and image, the listed sectors (SPRSEC), the
frame block's and render inputs' new fields, and the moved record spill.

Milestone 7's stage A (this file's first version) owns the level layout,
the frame block, overlay 1 of the zero page, the far layer's bytes and
the W scratch of the BSP walk. Stage B adds overlay 2 (the seg page, the hot
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
# The record spill (stage B), consecutive banks: milestone 8 moves it to
# four banks (RENDER-MASKED.md 6.1), 9 and 10 are free
RECSP = (51, 52, 53, 54)
DRAWSEGS = 0x0200               #   RENDB: 128 drawsegs of DS_SIZE bytes
MAXDRAWSEGS = 128
OPENHI = 0x1200                 #   RENDB: the openings' high bytes
MAXOPENINGS = 2560
OPENLO = 0x0C00                 # aux 0: the openings' low bytes
STAGE, STAGE_END = 0xA000, 0xC000       # aux 0: the record staging
TEX_FIRST, TEX_LAST = 11, 30    # texel slots, sky slots
SEAM = 31                       # harness only: checkpoint A's lockstep
                                #   data (milestone 8's stage C made the
                                #   weapon's clip pass native: the seam of
                                #   floorclip, FR_VIS and MM_WPOK went)
SEAM_HDR = 0x0200               #   +0: the reference's wall calls
SEAM_CALLS = 0x0400             #   the stub's call records
SEAM_CALLREC = 16
SEAM_MAXCALLS = 256
SEAM_SOLID = SEAM_CALLS + SEAM_CALLREC * SEAM_MAXCALLS
SEAM_SOLID_MAX = (0xC000 - SEAM_SOLID) // 160
# milestone 8, stage B (RENDER-MASKED.md 4.2): the clip log of the test
# builds (-D CLIPLOG), where the walk's lockstep build keeps SEAM_SOLID (the
# two builds are exclusive): each nm_vis call's vissprite index (2 bytes,
# $FFxx for the weapon's draw of psprite xx) and all of FLOORCLIP and
# CEILCLIP as it starts
SEAM_CLIPLOG = SEAM_SOLID
CLIPLOG_REC = 2 + 2 * 160
CLIPLOG_MAX = 80 + 2
CODE = (112, 113, 114, 115)     # the render window image (stage C):
WCODE_BANK = CODE[0]            #   the image at its own addresses in the
                                #   first (one bank holds it)
MCODE_BANK = CODE[1]            # milestone 8: the masked phase's image
MRTN_BANK = CODE[2]             # harness only (stage B's routine mode):
                                #   W's drawseg copy and vissprites, loaded
                                #   after the images
# milestone 8 (RENDER-MASKED.md 1.10): the sprite data of a level
SPR_FIRST, SPR_LAST = 32, 47    # the patch store: lumps and their tails
SPRT = 48                       # scale records, SPRBOUND, PHDR, SPRFR
WPRO = 49                       # the weapons' profiles (stage C)
RTH = 50                        # the render things (RTHING)
RECW = 55                       # a group's batches 2 and 3 parked (stage C)
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
       'VALID': 11, 'THINGS': 13}      # milestone 8: the thing list's head
SEC_SIZE = 16                          #   (a RTHING slot, $FFFF: none)
# Side, render part, 8 bytes: texture offset, row offset (words), top,
# bottom, mid texture (bytes), and (milestone 9, docs/LEVELS.md 1.3:
# "render-level 3") the side's sector, which the level load's GROUP step
# reads (its pad until then; the renderer does not read it).
SIDE = {'TEXOFS': 0, 'ROWOFS': 2, 'TOP': 4, 'BOTTOM': 5, 'MID': 6,
        'SECTOR': 7}
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

# ---- milestone 8: the sprite data (RENDER-MASKED.md 1.3-1.8) -----------
# SPRT: one 16-byte record a distance d = tz >> 16 (0-1280): xscale,
# yscale, iscale (4 each), FQ's q (2) and r (1); SPRBOUND (4 x 55: E, E /
# 2 + 2, as upstream's, injected each frame); PHDR, 16 bytes a patch of
# the store (index 0: upstream's placeholder); SPRFR, 24 bytes a sprite
# frame (SFIRST[s] + f).
SCALE = {'XS': 0, 'YS': 4, 'IS': 8, 'Q': 12, 'R': 14}
SCALE_SIZE = 16
MAXZ = 1280
SCALES = Array('scale', SPRT, 0x0200, SCALE_SIZE, MAXZ + 1)
NUMSPRITES = 55                 # CONST_NUMSPRITES (offsets.inc)
SPRBOUND_T = 0x5400             # SPRT: SPRBOUND, 4 x NUMSPRITES
PHDR = {'WIDTH': 0, 'LEFT': 2, 'TOP': 4, 'BANK': 6, 'ADDR': 7, 'LUMP': 9}
PHDR_SIZE = 16
PHDRS = Array('patch header', SPRT, 0x5600, PHDR_SIZE, 640)
# SPRFR: rotate, flipmask, the store index of each of the 8 rotations,
# flags (bit 0: upstream's frame is not a real one, garbage past the
# sprite's frames that no map thing takes: ST_SPRFRAME if one is
# projected)
SPRFR = {'ROT': 0, 'FLIP': 1, 'LUMPS': 2, 'FLAGS': 18}
SPRFR_SIZE = 24
SPRFR_BAD = 1
SPRFRS = Array('sprite frame', SPRT, PHDRS.end, SPRFR_SIZE, 400)
assert SCALES.end <= SPRBOUND_T and SPRBOUND_T + 4 * NUMSPRITES <= \
    PHDRS.base and SPRFRS.end <= BANK_ROOM[1]
# RTHING (RTH): the render part of a mobj, by pool slot (1.8): x, y, z (4
# each), the angle's high word, sprite, frame (bit 15 FF_FULLBRIGHT),
# flags (bit 0 MF_SHADOW), snext (a slot, $FFFF: none)
RTHING = {'X': 0, 'Y': 4, 'Z': 8, 'ANG': 12, 'SPR': 14, 'FRAME': 15,
          'FLAGS': 17, 'SNEXT': 18}
RTHING_SIZE = 24
# milestone 9 (docs/LEVELS.md 3.1): a slot is its mobj's: the pool's
# slots, then the zone mobjs; 2,026 fill RTH's $0200-$BFFF (768 before)
RTHINGS = Array('render thing', RTH, 0x0200, RTHING_SIZE, 2026)
NO_THING = 0xFFFF
# WPRO (stage C, RENDER-MASKED.md 1.5): WPIDX, each patch store index's
# weapon profile (its address in WPRO; $FFFF: none, upstream's WP_NONE:
# the draw takes R_DrawVisSprite), then the profiles, each upstream's
# layout (r_sprite65.s:746-754) at its WPRO address: +0 width, +2 the
# minimum a, +4 +6 the columns of each parity, +8 +10 their tables (2 bytes
# a column: the address of its list), +12 the list of a column with no post
# (0, 0), +16 the tables, then the lists: the posts of a column from the
# lowest up, 5 bytes each (a + 1, b + 1, the a of its run, the offset of
# its texels in the patch), then a byte 0
WPIDX = 0x0200
WPROF, WPROF_END = WPIDX + 2 * 640, BANK_ROOM[1]
WPH = {'WIDTH': 0, 'MINA': 2, 'NEVEN': 4, 'NODD': 6, 'TEVEN': 8,
       'TODD': 10, 'EMPTY': 12}
WPH_SIZE = 16
WP_POST = 5
WP_MAXPOSTS = 14                # wbMake: a 15th post of a column: none
NO_PROFILE = 0xFFFF

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
# The weapon's vissprite (milestone 8, stage C: RENDER-MASKED.md 1.7 as
# built): pspSprite's fields, native, 12 bytes: the patch store index
# ($FFFF in WPREV: none, upstream's lump $FFFF), texturemid, x1, x2 (two
# bytes: pspSprite stores it before the off-screen test, unclamped), the
# high word of startfrac, the colormap as its record page (0: the shadow
# weapon). FRVIS is persistent (upstream's FR_VIS keeps the fields a frame
# does not write: an off-screen or absent weapon writes some or none, and
# weaponClipSame compares all of them), next to WPREV in the weapon skip's
# persistent area (MEMORY_MAP.md 3.3)
FRVIS = 0x18B0
FV = {'PATCH': 0, 'TMID': 2, 'X1': 6, 'X2': 7, 'SFRAC': 9, 'PAGE': 11}
FV_SIZE = 12
WPREV_USED = FV_SIZE
NO_PATCH = 0xFFFF
FLOORCLIP, CEILCLIP, SOLIDCOL = 0x0C00, 0x0D00, 0x0E00
FSTOP, FSBOT = L5.FSTOP, L5.FSBOT       # fill spans (persistent)
SPANS, SPANS_END = 0x0F00, 0x1400
CVFIRST, CV_END = L5.CVFIRST, 0x1680    # covered ranges
WCLIP, WPREV, WTMP = L5.WCLIP, L5.WPREV, L5.WTMP
DSX1, DSX2 = 0x1980, 0x1A00
TEXTRANS = 0x1A80               # texturetranslation as bytes
LNMAP = 0x1B80                  # ML_MAPPED of each line, a bit, 2,048
LNMAP_LINES = 2048
# milestone 8: in milestone 5's COLLO area until the bucket pass (the
# replay's COLLO/COLHI are written after the masked phase)
UPOFS = 0x1680                  # upstream's page offset of each column's
                                #   list (stage B)
FRORD = 0x1720                  # the sort's order: vissprite indexes
SPRSEC, SPRSEC_END = 0x1600, 0x1700     # aux 0: the listed sectors

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

# ---- W in the masked phase (RENDER-MASKED.md 1.10) ----------------------
# The front end's image starts with what both images run (MATHW, AUXW:
# the math's render subset and the aux card's reads), which the masked
# phase's load leaves in place; the masked code follows from MCODE.
MCODE, MCODE_END = 0x6800, 0x9C00
DSW, DSW_MAX = 0x9C00, 64       # the drawsegs that clip sprites or hold
                                #   masked columns, DS_SIZE bytes each
VIS = 0xA400                    # the vissprites (VISREC)
MAXVIS = 80                     # MAXVISSPRITES
SPRB = 0xB080                   # SPRBOUND for the frame
FETCH, FETCH_END = 0xB160, 0xB200       # fetch buffers
TXMP = 0xB200                   # per level: each texture's first patch
                                #   (the store index, low and high planes)
YHTAB, YHTAB_END = 0xBA00, 0xBE02       # stage B; the projection keeps the
SECLIST = YHTAB                         #   listed sectors there (SPRSEC)
# stage B: YHTAB as two planes of 512 (the high word of E - 1 of texel row
# t, 0-511: its low byte, its high byte; no YHTABM, the running E - 1 is
# kept in zero page)
YHL, YHH = YHTAB, YHTAB + 0x200
CLIPBUF = 0xBE02
MTCLO, MTCHI = 0xBEA2, 0xBF42
MTC_END = 0xBFE2
MCCLIP = 0x0E00                 # main SOLIDCOL: a masked range's
                                #   mceilingclip (dead once the walk ends)
# stage B's fetch buffers (FETCH, after the projection's sprite frame and
# listed sector): a patch header, a seg, a side, the front and back
# sectors, a drawseg past DSW
PHB = FETCH + 0x28              # 16
SEGB = PHB + 16                 # 24 (SEG_SIZE)
SIDEB = SEGB + 24               # 8
MSEC_F = SIDEB + 8              # 16
MSEC_B = MSEC_F + 16            # 16
DSB = MSEC_B + 16               # 32
assert DSB + 32 <= FETCH_END
MTABLES_PAGE, MTABLES_PAGES = TXMP >> 8, 2      # the masked load's tables
# stage C: the weapon (RENDER-MASKED.md 1.5, 3.2). Its profile's table
# entries of the columns drawn (2 bytes a column, at most 160) and one
# column's list (at most 14 posts and the end byte) in W: in the front end
# the node frames' (the clip pass runs before the walk), in the masked
# phase YHTAB's (the weapon's profile draw uses no YHTAB; the sprites are
# done); the weapon's vissprite for nm_vis (40 bytes: the fallback
# R_DrawVisSprite) over the seg, side and front sector fetch buffers (the
# masked walls are done)
WPENT = 0xBA00
WPLST = WPENT + 2 * 160
WPLST_END = WPLST + 72         # (the fetch of a list takes 16, then 56)
WPHB = WPLST_END                # the psprite's patch header (16)
WSFR = WPHB + PHDR_SIZE         # its sprite frame (SPRFR_SIZE)
WPHD = WSFR + SPRFR_SIZE        # its profile's header (WPH_SIZE)
WPBUF_END = WPHD + WPH_SIZE
assert NODEF <= WPENT and WPBUF_END <= NODEF_END
assert YHTAB <= WPENT and WPBUF_END <= YHTAB_END
WVIS = SEGB
assert WVIS + 40 <= DSB

# ---- after the masked phase (RENDER-MASKED.md 1.10, 3.4; stage C) -------
# The bucket pass, then the replay. Main memory the masked phase leaves
# dead: the bucket pass's code that runs with RAMRD off, copied there from
# the masked image by nm_bkload: BKFAR at $0C00-$0EFF (FLOORCLIP, CEILCLIP,
# SOLIDCOL and the render scratch after each) and BKFAR2 at $0200-$02FF
# (the walk's bounce buffer and the spill); CVDONE, the covered columns
# whose record the scatter found (bit 0) and, in the game build, the
# columns cut at the batch's limit (bit 7, RENDER-MASKED.md 6.1), over
# DSX1; the batch list's sizes after it, over DSX2; its first columns in
# zero page after its count BK_NB ($70).
# The design's CVW arrays (over WTMP, which is persistent: RENDER-MASKED.md
# 2.1) are gone: the scatter writes the record's W address into CVRECLO/HI
# at once and marks the column in CVDONE, so no later sequence number is
# taken for one.
BKFAR_RUN, BKFAR_END = 0x0C00, 0x0F00
BKFAR2_RUN, BKFAR2_END = 0x0200, 0x0300
STAGING_BYTES = (STAGE_END - STAGE) + len(RECSP) * (BANK_ROOM[1] -
                                                    BANK_ROOM[0])
# The batches a frame can take (verified 2026-10-01). nb_bucket packs
# whole columns: a batch ends when its next column would take it past
# RECBUF_SPAN (8,192 W bytes), so two adjacent batches hold more than
# 8,192 bytes between them; in the game build a batch also ends after a
# column cut at the limit (6.1), which keeps at least 8,192 - 10 bytes (the
# first record it refused had at most 11). A staged record of s bytes
# takes s - 1 in W, s at most 12: W gets at most 11/12 of the staging. So
# n batches hold at least (n // 2) * 8,182 bytes, and n is at most MAXB.
RECBUF_SPAN = 0x2000
BK_PAIR_MIN = RECBUF_SPAN - 10
W_BYTES_MAX = STAGING_BYTES * 11 // 12
MAXB = 2 * (W_BYTES_MAX // BK_PAIR_MIN) + 1
CVDONE = 0x1980
BK_NB_ZP = 0x70                 # bucket.s BK_NB
BK_FIRST = BK_NB_ZP + 1         # each batch's first column (MAXB + 1)
BK_LIST = CVDONE + 160
BK_SZLO = BK_LIST               # its bytes
BK_SZHI = BK_SZLO + MAXB
BK_LIST_END = BK_SZHI + MAXB
assert MAXB == 45
assert BK_FIRST + MAXB + 1 <= 0xB0      # (the bucket pass's $70-$AF)
assert BKFAR2_RUN == SEGBUF and BKFAR2_END == SPILL_END
assert BK_LIST_END <= DSX2 + 0x80
assert CVDONE == DSX1
# RENDER-MASKED.md 6.1 item 1 (as restated 2026-10-01): the staging holds
# at least STAGING_MARGIN times the largest staging of the captured frames
# of acceptance 1; frame8.py measures it on every run and fails a report
# under it (the synthetic extremes, upstream's pages all taken, must fit)
STAGING_MARGIN = 8
# The native vissprite (1.7), 40 bytes
VISREC = {'X1': 0, 'X2': 1, 'SCALE': 2, 'GZ': 6, 'GZT': 10, 'TX': 12,
          'TY': 16, 'STARTFRAC': 20, 'XISCALE': 24, 'TMID': 28,
          'FSTEP': 32, 'PATCH': 34, 'PAGE': 36, 'SLOT': 37}
VISREC_SIZE = 40
assert VIS + MAXVIS * VISREC_SIZE <= SPRB and SPRB + 4 * NUMSPRITES <= \
    FETCH

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
    # milestone 8 (RENDER-MASKED.md 1.10): the listed sectors, the fuzz
    # position (persistent), the vissprites, the page model (stage B), the
    # records staged (their sequence number) and the sticky drop (6.1)
    ('SPRN', 1), ('FZPOS', 1), ('NVIS', 1), ('XPUSED', 1), ('UPFLUSH', 1),
    ('RECSEQ', 2), ('RECDROP', 1),
]
FRAME_BLOCK_SIZE = FB_END - FB
# The render inputs, $0370-$039F: the player's view and settings, from
# the game state (upstream: player_t, mobj_t, _g_gamma).
RENDER_INPUTS = [
    ('PL_X', 4), ('PL_Y', 4), ('PL_ANGLE', 4), ('PL_VIEWZ', 4),
    ('PL_XLIGHT', 2), ('PL_FIXCM', 2), ('GAMMA', 2),
    # milestone 8 (RENDER-MASKED.md 1.10, 2.1): each psprite's sprite,
    # frame, sx (16 bits) and sy (32 bits), the player's sector light,
    # powers[pw_invisibility] (stage C reads them)
    ('PSP0_SPR', 1), ('PSP0_FRAME', 2), ('PSP0_SX', 2), ('PSP0_SY', 4),
    ('PSP1_SPR', 1), ('PSP1_FRAME', 2), ('PSP1_SX', 2), ('PSP1_SY', 4),
    ('PL_SECLIGHT', 1), ('PL_INVIS', 2),
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
# milestone 8: a projected thing's frame that upstream reads past its
# sprite's frames (levelconv.py flags it: no map thing takes one)
ST_SPRFRAME = 8
# the bucket pass's prototype (stage A): more than 3 batches, a column past
# a batch, a broken staging (RENDER-MASKED.md 3.4)
ST_BUCKET = 9
# stage B: a masked post that ends after texture row 255 (upstream's mwTall:
# I_Error; no texture of the game has one)
ST_TALL = 10
# the records (lists.inc): upstream's kinds, the native sizes with the
# column byte, the page model (RENDER-MASKED.md 3.4)
K_TEXC, K_FUZZ = 6, 8
TEXCREC_SIZE, FUZZREC_SIZE = 8, 5
PAGE_ROOM = 254
XP_PAGES = 50                   # the extra pages ($CE-$FF)

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


# The masked phase's zero page (RENDER-MASKED.md 3.6): overlays 1 and 2,
# free once the walk ends. Stage A: the projection and the sort.
OVM1 = [
    ('MP_SEC', 1),      # the listed sector being projected (its index)
    ('MP_S', 1),        # SMAP[(light >> 4) + LT_BASE]: the sector's start
    ('MP_SLOT', 2),     # the thing (its RTHING slot)
    ('MP_VP', 2),       # the vissprite being made (W)
    ('MP_FLIP', 1),     # flip (the frame's flipmask & 1 << rot)
    ('MP_ROT', 1),      # the rotation
    ('MP_PATCH', 2),    # the patch store index
    ('MP_X1', 2),       # x1 (signed)
    ('MP_W', 4),        # W = width * xscale
    ('MP_T4', 4),       # products, 4 bytes each
    ('MP_T5', 4),
    ('MP_DS', 1),       # the drawseg copy: the drawseg, copies made
    ('MP_DSN', 1),
    ('MP_K', 1),        # the sort: i, j
    ('MP_J', 1),
    ('MP_TMP', 1),      # temporaries
    ('MP_TMP2', 1),
]
OVM2 = [
    ('MP_TH', RTHING_SIZE),     # the thing's RTHING
    ('MP_SC', SCALE_SIZE),      # its distance's scale record
    ('MP_PH', PHDR_SIZE),       # its patch's header
    ('MP_TRX', 4), ('MP_TRY', 4),       # tr_x, tr_y
    ('MP_TZ', 4), ('MP_TX', 4),         # tz, tx
    ('MP_GZ', 4), ('MP_GX', 4),         # the G parts of a fractional thing
    ('MP_GZ0', 4), ('MP_GX0', 4),       # R_WallFrame's, whole map units
    ('MP_XL', 4), ('MP_XR', 4),         # xl (CENTERX << 16 added), xr
    ('MP_FT', 4),                       # the scale for the sort (temp)
    ('MP_SGN', 1),                      # the signs of viewcos, viewsin
]
OVM3 = []                               # (the spill: none yet)
# Stage B, the draw phase (drawMasked's loops, after the sort: the
# projection's bytes are dead): overlay 1, R_DrawSprite's and the masked
# range's state, the record allocation's, the clip log's
OVD1 = [
    ('MRB', 1),         # the record batch's bytes (the masked copy of rrec.s)
    ('RSEQ', 2),        # the sequence number of the record just allocated
    ('MD_I', 1),        # drawMasked: the sort index, the drawseg
    ('DS_IDX', 1),      # the vissprite: its index, its record (W)
    ('DS_VP', 2),
    ('SP_X1', 1), ('SP_X2', 1),        # the sprite's x1, x2
    ('DS_K', 1),        # the drawseg index of the scan
    ('DS_SLOT', 1),     # its slot among the drawsegs that clip (DSW)
    ('DS_R1', 1), ('DS_R2', 1),
    ('DS_P', 2),        # the drawseg (W: DSW or DSB)
    ('DS_TOT', 1),      # the drawsegs whose DSX1 is not 255
    ('SPRTOP', 1),      # viewtop + 1, viewbottom + 1 (R_DrawSprite's
    ('SPRBOT', 1),      #   "not set yet", screenheightarray's bytes)
    ('MW_X', 1), ('MW_X2', 1),  # a masked range's columns
    ('MW_I', 1),        # the column's index in the range
    ('MW_LVF', 1),      # startmap + 24 when each column takes its light
    ('MW_CMP', 1),      # the page of the records
    ('MW_CONT', 1),     # bit 7: the post before made the column's last record
    ('MW_TEX', 1),      # the texture, its width mask
    ('MW_WM', 1),
    ('CL_N', 1),        # the clip log: calls so far, the next place (SEAM)
    ('CL_PTR', 2),
    ('MD_T', 4),        # temporaries
]
# overlay 2: R_DrawVisSprite's state (the loop page of upstream's WPAGE
# names, wpage.inc:105-137) and the masked range's
OVD2 = [
    ('V_FRAC', 4), ('V_XIS', 4), ('V_X', 1),
    ('V_SS', 4),        # spryscale
    ('V_E', 4),         # E - 1 of the last texel row in YHTAB
    ('V_TN', 2),        # YHTAB holds rows 0 .. V_TN - 1
    ('V_UNIT', 1), ('V_YH0', 2),
    ('V_PB', 1), ('V_PA', 2), ('V_W', 2),       # the patch: bank, address,
    ('V_TM7', 2), ('V_F', 2), ('V_S2', 2),      #   width; texturemid >> 7,
    ('V_K', 2),                                 #   fracstep, its half, K
    ('V_CMP', 1), ('V_HI', 1), ('V_LO', 1),
    ('V_TD', 1), ('V_LEN', 1), ('V_YL', 1), ('V_YH1', 1),
    ('V_COL', 2),       # the post
    ('V_REP', 1),       # a magnified run's columns after the first
    ('V_FCP', 2), ('V_CCP', 2),                 # the clip arrays
    ('V_PI', 1),        # the post of the far_posts buffer
    ('V_T', 4),         # temporaries
    ('V_FZ', 1),        # the fuzz position in the loop
    ('MW_SC', 4),       # spryscale of the column, and its step
    ('MW_STEP', 4),
    ('MW_P', 6),        # texturemid * spryscale, bits 0-47, and its step
    ('MW_B', 6),
    ('MW_TMID', 4),     # texturemid
    ('MW_CL', 4),       # sprtopscreen + $FFFF of the column
    ('MW_ST', 2),       # the texture step of the column, its half
    ('MW_S2', 2),
]

# Stage C, the weapon (both images: the clip pass before the walk, the
# draw after the drawsegs' masked columns): overlay 2 from the masked
# range's state (MW_SC on, dead once the drawsegs are done; in the front
# end the seg page, free before the walk). nm_vis's V_* and the record
# allocation's MRB, RSEQ stay untouched (the fallback draw and wdProf's
# records use them).
OVW = [
    ('WP_K', 2),        # the profile (its WPRO address)
    ('WP_YH0', 2),      # V_YH0: (sprtopscreen - 1) >> 16, signed
    ('WP_VHI', 1),      # V_HI: the view's last row + 1 - 1 (viewbottom)
    ('WP_HI', 1),       # hi = V_HI - V_YH0 (1-254)
    ('WP_N', 1),        # the columns to do, the one being done
    ('WP_I', 1),
    ('WP_X', 1),        # its screen column
    ('WP_TF', 2),       # the records' TF, TI
    ('WP_YM1', 1),      # V_YH0 - 1 (a byte)
    ('WP_E', 2),        # the column's table entry (W), a post (RamWorks)
    ('WP_C', 2),        # the patch column
    ('WP_X1', 2),       # pspSprite's x1 (signed), tx
    ('WP_TX', 2),
    ('WP_T', 4),        # temporaries
    ('WP_PSP', 1),      # the psprite (0, 1)
    ('WP_SKIP', 1),     # the draw: mfloorclip is WCLIP (a frame that skips)
    ('WP_PYH', 1),      # the clip pass's R_DrawVisSprite: the run, the last
    ('WP_RUN', 1),      #   row of the post above, the post's rows
    ('WP_YL', 1), ('WP_YH1', 1),
]

FAR = allocate(FAR_ZP, *ZP_FAR)
ZP = allocate(OV1_A, *ZP_OV1)
ZP2 = allocate(OV2_B, *ZP_OV2)
ZPM1 = allocate(OVM1, *ZP_OV1)
ZPM2 = allocate(OVM2, *ZP_OV2)
ZPM = dict(ZPM1, **ZPM2)
ZPD1 = allocate(OVD1, *ZP_OV1)
ZPD2 = allocate(OVD2, *ZP_OV2)
ZPD = dict(ZPD1, **ZPD2)
ZPW = allocate(OVW, ZPD2['MW_SC'], ZP_OV2[1])
ZPW_END = ZPW[OVW[-1][0]] + OVW[-1][1]
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
        Region('main', CEILCLIP, CEILCLIP + VIEWWIDTH, 'CEILCLIP'),
        Region('main', SOLIDCOL, SOLIDCOL + VIEWWIDTH, 'SOLIDCOL'),
        Region('main', SPANS, SPANS_END, 'fill spans'),
        Region('main', CVFIRST, CV_END, 'covered ranges'),
        Region('main', WCLIP, WCLIP + VIEWWIDTH, 'weapon skip'),
        Region('main', WPREV, WPREV + WPREV_USED, 'WPREV'),
        Region('main', FRVIS, FRVIS + FV_SIZE, 'FRVIS'),
        Region('main', WTMP, WTMP + VIEWWIDTH, 'WTMP'),
        Region('main', DSX1, DSX2 + 0x80, 'DSX1, DSX2'),
        Region('main', TEXTRANS, TEXTRANS + 256, 'TEXTRANS'),
        Region('main', LNMAP, LNMAP + LNMAP_LINES // 8, 'LNMAP'),
        Region('main', UPOFS, UPOFS + VIEWWIDTH, 'UPOFS'),
        Region('main', FRORD, FRORD + MAXVIS, 'FRORD'),
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
        # milestone 8: the masked phase's W (an overlay of the front end's
        # W: the phases never overlap), in its own space
        Region('wm', MCODE, MCODE_END, 'masked code'),
        Region('wm', DSW, DSW + DSW_MAX * DS_SIZE, 'DSW'),
        Region('wm', VIS, VIS + MAXVIS * VISREC_SIZE, 'vissprites'),
        Region('wm', SPRB, SPRB + 4 * NUMSPRITES, 'SPRBOUND'),
        Region('wm', FETCH, FETCH_END, 'fetch buffers'),
        Region('wm', TXMP, TXMP + 512, 'TXMP'),
        Region('wm', TXBANK, TXTAB_END, 'TX tables (kept)'),
        Region('wm', BATCH, BATCH + 256, 'record batch (kept)'),
        Region('wm', YHTAB, YHTAB_END, 'YHTAB'),
        Region('wm', CLIPBUF, MTCLO, 'CLIPBUF'),
        Region('wm', MTCLO, MTC_END, 'MTCLO, MTCHI'),
        Region('aux0', SPRSEC, SPRSEC_END, 'SPRSEC'),
    ]
    out.append(Region('bank%d' % WPRO, WPIDX, WPROF, 'WPIDX'))
    for a in (NODES, SUBS, SECTORS, SIDES, SCALES, PHDRS, SPRFRS,
              RTHINGS):
        out.append(Region('bank%d' % a.bank, a.base, a.end, a.name + 's'))
    out.append(Region('bank%d' % SPRT, SPRBOUND_T,
                      SPRBOUND_T + 4 * NUMSPRITES, 'SPRBOUND (SPRT)'))
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


def after_masked() -> List[Tuple[int, int, str]]:
    """Main memory the bucket pass takes after the masked phase (stage C:
    RENDER-MASKED.md 1.10 as built)."""
    return [(BKFAR_RUN, BKFAR_END, 'BKFAR'),
            (BKFAR2_RUN, BKFAR2_END, 'BKFAR2'),
            (BK_LIST, BK_LIST_END, 'the batch list\'s sizes'),
            (CVDONE, CVDONE + VIEWWIDTH, 'CVDONE')]


# Regions in milestone 5's COLLO/COLHI during the render: the bucket pass
# writes COLLO/COLHI after the masked phase (RENDER-MASKED.md 1.10)
MASKED_OVER_COL = ('UPOFS', 'FRORD')


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
    for name, at in list(ZPM.items()) + list(ZPD.items()):
        if not (ZP_OV1[0] <= at < ZP_OV1[1] or ZP_OV2[0] <= at < ZP_OV2[1]):
            raise ValueError('%s outside the masked phase\'s overlays'
                             % name)
    if SEAM_CLIPLOG + CLIPLOG_REC * CLIPLOG_MAX > BANK_ROOM[1]:
        raise ValueError('the clip log passes the SEAM bank')
    banks = [LVSEG, LVMAP, RENDB, SEAM, SPRT, WPRO, RTH, RECW] + \
        list(RECSP) + list(range(TEX_FIRST, TEX_LAST + 1)) + \
        list(range(SPR_FIRST, SPR_LAST + 1)) + list(CODE) + \
        list(FSTEP_BANKS) + [MT_TBANK, MT_RLO, MT_RHI]
    if len(set(banks)) != len(banks):
        raise ValueError('two uses of one RamWorks bank')
    if max(banks) > 126:
        raise ValueError('a RamWorks bank past 126')
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
                L5.COLLO < a.end and a.what not in MASKED_OVER_COL:
            raise ValueError('%s is in COLLO/COLHI' % a.what)
    # stage C: what the bucket pass and the replay take after the masked
    # phase must not touch the renderer's persistent state (the spans, the
    # covered ranges but by their owners, the weapon skip, the hot
    # globals, the frame block and the render inputs) nor milestone 5's
    # regions the replay reads
    persistent = [(SPANS, SPANS_END), (WCLIP, WCLIP + VIEWWIDTH),
                  (WPREV, WPREV + WPREV_USED), (FRVIS, FRVIS + FV_SIZE),
                  (WTMP, WTMP + VIEWWIDTH), (TEXTRANS, 0x2000),
                  (PHASE, RIN_END), (L5.COLLO, L5.COLHI + 161),
                  (CVFIRST, CV_END), (L5.SCRATCH, L5.SCRATCH_END)]
    for lo, hi, what in after_masked():
        for a, b in persistent:
            if lo < b and a < hi:
                raise ValueError('%s ($%04X-$%04X) meets persistent state or '
                                 'the replay\'s ($%04X-$%04X)' % (
                                     what, lo, hi - 1, a, b - 1))


# ---------------------------------------------------------------------------
# rlayout.inc
# ---------------------------------------------------------------------------

def constants() -> List[Tuple[str, int]]:
    out = [
        ('LVSEG', LVSEG), ('LVMAP', LVMAP), ('SEAM', SEAM),
        ('SEAM_HDR', SEAM_HDR),
        ('FV_SIZE', FV_SIZE), ('NO_PATCH', NO_PATCH),
        ('WCLIP', WCLIP), ('WPREV', WPREV),
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
        # milestone 8, stage A
        ('SPRT', SPRT), ('RTH', RTH), ('MCODE_BANK', MCODE_BANK),
        ('SCALEBASE', SCALES.base), ('SCALE_SIZE', SCALE_SIZE),
        ('SPRBOUND_T', SPRBOUND_T), ('PHDRBASE', PHDRS.base),
        ('PHDR_SIZE', PHDR_SIZE), ('SPRFRBASE', SPRFRS.base),
        ('SPRFR_SIZE', SPRFR_SIZE), ('SPRFR_BAD', SPRFR_BAD),
        ('RTHBASE', RTHINGS.base), ('RTHING_SIZE', RTHING_SIZE),
        ('NO_THING', NO_THING), ('NUMSPRITES', NUMSPRITES),
        ('MAXZ', MAXZ), ('ST_SPRFRAME', ST_SPRFRAME),
        ('UPOFS', UPOFS), ('FRORD', FRORD), ('SPRSEC', SPRSEC),
        ('MCODE', MCODE), ('MCODE_END', MCODE_END), ('DSW', DSW),
        ('DSW_MAX', DSW_MAX), ('VIS', VIS), ('MAXVIS', MAXVIS),
        ('VISREC_SIZE', VISREC_SIZE), ('SPRB', SPRB), ('FETCH', FETCH),
        ('TXMP', TXMP), ('YHTAB', YHTAB), ('SECLIST', SECLIST),
        ('MTABLES_PAGE', MTABLES_PAGE), ('MTABLES_PAGES', MTABLES_PAGES),
        ('RECW', RECW), ('ST_BUCKET', ST_BUCKET), ('MRTN_BANK', MRTN_BANK),
        # stage B
        ('ST_TALL', ST_TALL), ('K_TEXC', K_TEXC), ('K_FUZZ', K_FUZZ),
        ('TEXCREC_SIZE', TEXCREC_SIZE), ('FUZZREC_SIZE', FUZZREC_SIZE),
        ('PAGE_ROOM', PAGE_ROOM), ('XP_PAGES', XP_PAGES),
        ('YHL', YHL), ('YHH', YHH), ('CLIPBUF', CLIPBUF), ('MTCLO', MTCLO),
        ('MTCHI', MTCHI), ('MCCLIP', MCCLIP), ('PHB', PHB), ('SEGB', SEGB),
        ('SIDEB', SIDEB), ('MSEC_F', MSEC_F), ('MSEC_B', MSEC_B),
        ('DSB', DSB), ('WTMP', WTMP), ('CVFIRST', CVFIRST),
        ('CVEND', L5.CVEND), ('CVRECLO', L5.CVRECLO),
        ('CVRECHI', L5.CVRECHI), ('SEAM_CLIPLOG', SEAM_CLIPLOG),
        ('CLIPLOG_REC', CLIPLOG_REC), ('CLIPLOG_MAX', CLIPLOG_MAX),
        # stage C
        ('WPRO', WPRO), ('WPIDX', WPIDX), ('WPH_SIZE', WPH_SIZE),
        ('WP_POST', WP_POST), ('NO_PROFILE', NO_PROFILE),
        ('WPENT', WPENT), ('WPLST', WPLST), ('WVIS', WVIS),
        ('WPHB', WPHB), ('WSFR', WSFR), ('WPHD', WPHD),
        ('BKFAR_RUN', BKFAR_RUN), ('BKFAR_END', BKFAR_END), ('MAXB', MAXB),
        ('BKFAR2_RUN', BKFAR2_RUN), ('BKFAR2_END', BKFAR2_END),
        ('BK_FIRST', BK_FIRST), ('BK_SZLO', BK_SZLO), ('BK_SZHI', BK_SZHI),
        ('BK_NB_ZP', BK_NB_ZP),
        ('CVDONE', CVDONE), ('COLLO', L5.COLLO), ('COLHI', L5.COLHI),
        ('RECBUF', L5.RECBUF),
    ]
    out += [('DS_' + k, v) for k, v in DS.items()]
    out += [('SEG_' + k, v) for k, v in SEG.items()]
    out += [('ND_' + k, v) for k, v in NODE.items()]
    out += [('BX_' + k, v) for k, v in BOX.items()]
    out += [('SUB_' + k, v) for k, v in SUB.items()]
    out += [('SEC_' + k, v) for k, v in SEC.items()]
    out += [('SIDE_' + k, v) for k, v in SIDE.items()]
    out += [('SC_' + k, v) for k, v in SCALE.items()]
    out += [('PH_' + k, v) for k, v in PHDR.items()]
    out += [('SF_' + k, v) for k, v in SPRFR.items()]
    out += [('TH_' + k, v) for k, v in RTHING.items()]
    out += [('VR_' + k, v) for k, v in VISREC.items()]
    out += [('FV_' + k, v) for k, v in FV.items()]
    out += [('WPH_' + k, v) for k, v in WPH.items()]
    out += sorted(SPILLS.items(), key=lambda x: x[1])
    out += sorted(SWV.items(), key=lambda x: x[1])
    out += sorted(FRAME.items(), key=lambda x: x[1])
    out += sorted(RINS.items(), key=lambda x: x[1])
    return out


def zeropage() -> List[Tuple[str, int]]:
    return sorted(FAR.items(), key=lambda x: x[1]) + \
        sorted(ZP.items(), key=lambda x: x[1]) + \
        sorted(ZP2.items(), key=lambda x: x[1]) + \
        sorted(ZPM.items(), key=lambda x: x[1]) + \
        sorted(ZPD.items(), key=lambda x: x[1]) + \
        sorted(ZPW.items(), key=lambda x: x[1])


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
        # milestone 8, stage C: the weapon's clip pass (its vissprite, its
        # zero page in overlay 2, its profile's buffers in the node
        # frames: allowed above)
        ('main', 0, FRVIS, FRVIS + FV_SIZE, 'FRVIS'),
        ('main', 0, min(ZPW.values()), ZPW_END, 'the weapon\'s zero page'),
        # milestone 8: the walk lists the sectors (SPRSEC)
        ('aux', 0, SPRSEC, SPRSEC_END, 'SPRSEC'),
    ]
    return out


def allowed_writes_masked(cliplog: bool = False
                          ) -> List[Tuple[str, int, int, int, str]]:
    """What the masked phase's code may write (stage A: the drawseg copy,
    the projection and the sort; stage B: the sprites' and masked walls'
    records, clips and marks), besides the card's own data
    (render_check.allowed_sets adds those by label): its zero page, the
    math block and FA_*, the frame block, the sort's order, its W data;
    the clips, spans, covered ranges, the page model, WTMP, MCCLIP, the
    record batch, staging and spill, the masked columns' marks in the
    openings; the clip log of a test build."""
    out = [
        ('main', 0, FLOORCLIP, FLOORCLIP + VIEWWIDTH, 'FLOORCLIP'),
        ('main', 0, CEILCLIP, CEILCLIP + VIEWWIDTH, 'CEILCLIP'),
        ('main', 0, MCCLIP, MCCLIP + VIEWWIDTH, 'MCCLIP (SOLIDCOL)'),
        ('main', 0, FSTOP, FSBOT + VIEWWIDTH, 'the spans\' rows'),
        ('main', 0, CVFIRST, CV_END, 'covered ranges'),
        ('main', 0, UPOFS, UPOFS + VIEWWIDTH, 'UPOFS'),
        ('main', 0, WTMP, WTMP + VIEWWIDTH, 'WTMP'),
        ('main', 0, BATCH, BATCH + 256, 'record batch'),
        ('main', 0, YHTAB, MTC_END, 'YHTAB, CLIPBUF, MTCLO, MTCHI'),
        # stage C: the weapon's draw (pspSprite of the flash writes FRVIS)
        ('main', 0, FRVIS, FRVIS + FV_SIZE, 'FRVIS'),
        ('aux', 0, OPENLO, OPENLO + MAXOPENINGS, 'masked columns (marks)'),
        ('aux', RENDB, OPENHI, OPENHI + MAXOPENINGS, 'masked columns'),
        ('aux', 0, STAGE, STAGE_END, 'record staging'),
    ] + [('aux', b, 0x0200, STAGE_END, 'record spill') for b in RECSP]
    if cliplog:
        out.append(('aux', SEAM, SEAM_CLIPLOG,
                    SEAM_CLIPLOG + CLIPLOG_REC * CLIPLOG_MAX, 'clip log'))
    return out + [
        ('main', 0, ZP_FAR[0], ZP_FAR[1], 'far layer arguments'),
        ('main', 0, ZP_OV1[0], ZP_OV1[1], 'overlay 1'),
        ('main', 0, ZP_OV2[0], ZP_OV2[1], 'overlay 2'),
        ('main', 0, ZP_MATH[0], ZP_MATH[1], 'the math block'),
        ('main', 0, PHASE, PHASE + 1, 'cost phase'),
        ('main', 0, FB, FB_END, 'frame block'),
        ('main', 0, FRORD, FRORD + MAXVIS, 'FRORD'),
        ('main', 0, DSW, DSW + DSW_MAX * DS_SIZE, 'DSW'),
        ('main', 0, VIS, VIS + MAXVIS * VISREC_SIZE, 'vissprites'),
        ('main', 0, SPRB, SPRB + 4 * NUMSPRITES, 'SPRBOUND'),
        ('main', 0, FETCH, FETCH_END, 'fetch buffers'),
        ('main', 0, SECLIST, SECLIST + 256, 'the listed sectors (W)'),
    ]


def allowed_writes_bucket() -> List[Tuple[str, int, int, int, str]]:
    """What the bucket pass (stage C: bucket.s, its card parts and BKFAR)
    may write: its zero page (overlay 1, $70-$AF), the far layer's
    arguments, the batch list, COLLO/COLHI, the covered ranges (the
    records' W addresses, a range cleared), CVDONE, page 1's bounce
    buffer, W (the batches), RECW (a group's parked batches), the status
    of a stop."""
    return [
        ('main', 0, ZP_OV1[0], ZP_OV1[1], 'overlay 1'),
        ('main', 0, 0x70, 0xB0, 'the batch count, $70-$AF'),
        ('main', 0, 0x0100, 0x01B4, 'the bounce buffer'),
        ('main', 0, BK_LIST, BK_LIST_END, 'the batch list'),
        ('main', 0, L5.COLLO, L5.COLHI + 161, 'COLLO, COLHI'),
        ('main', 0, CVFIRST, CV_END, 'covered ranges'),
        ('main', 0, CVDONE, CVDONE + VIEWWIDTH, 'CVDONE'),
        ('main', 0, WCODE, 0xC000, 'the batches (W)'),
        ('aux', RECW, 0x8000, 0xC000, 'the parked batches'),
        ('main', 0, FB + FBO['STATUS'], FB + FBO['STATUS'] + 1, 'STATUS'),
        ('main', 0, PHASE, PHASE + 1, 'cost phase'),
    ]


def allowed_writes_bkload() -> List[Tuple[str, int, int, int, str]]:
    """nm_bkload (the masked image): BKFAR into main $0C00."""
    return [('main', 0, BKFAR_RUN, BKFAR_END, 'BKFAR'),
            ('main', 0, BKFAR2_RUN, BKFAR2_END, 'BKFAR2'),
            ('main', 0, ZP_OV1[0], ZP_OV1[1], 'overlay 1')]


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
        ('main', 0, UPOFS, UPOFS + VIEWWIDTH, 'UPOFS (milestone 8)'),
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
