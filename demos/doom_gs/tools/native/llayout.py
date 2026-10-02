"""The game layout of milestone 9 (docs/LEVELS.md 1.3, 1.6, 2.2, 3.2):
the RamWorks bank map, the level window's records, the level store's
format, in one place, in tools/native/rlayout.py's family (rlayout.py
keeps the banks milestones 7 and 8 fixed; this module takes them from it
and places the rest around them; check() fails on a bank used twice or a
record past its region).

The banks (docs/LEVELS.md 1.6 as stage A measured it: 112 of 126 with
the later milestones' budgets):

    1-5, 72-74, 91-97, 125, 126  spare (17; bank 5 holds the test
                        pre-states of the harness and the test disk)
    6, 7, 8             LVSEG, LVMAP, RENDB (rlayout.py)
    9-31, 56-63         TEX: the texel store (one canonical slot block a
                        texture, 128 bytes a column: 31 banks, first fit
                        of the 116 blocks; the design's 30 had no room for
                        the textures made only in play)
    32-47, 64           SPR: the patch store (each lump whole, then its
                        128-byte tail)
    48, 49, 50          SPRT, WPRO, RTH (rlayout.py)
    51-55               RECSP, RECW (rlayout.py)
    65-68               LVG0 (lines), LVG1 (sectors' game part, line
                        tables, blocklinks, flood lists), LVG2 (blockmap,
                        reject), LVC (colormaps A and B, GSVIEWn, FUZZDARK)
    69-71, 75, 76       MOBJA-C, ZONE0, ZONE1 (the game state: stage C's
                        mobjs' game parts, the specials, the sector nodes;
                        72-74 spare since stage C)
    77-90               STORE: the nine level parts, their directory, the
                        load programs and the variant lists (the texel
                        banks' slack first: 14 banks after it, the
                        design's 21 estimated without it)
    98, 99              LCODE (the load phase's image), GTAB (the game's
                        constant tables)
    100-104, 105-110    songs and effects, 2D (milestone 11)
    111                 LVS (milestone 10's sight and move tables)
    112-115             CODE (rlayout.py)
    116-122             FSTEP, MT_TBANK, MT_RLO, MT_RHI (rlayout.py)
    123, 124            LOGTAB (milestone 10)

Milestone 10's skeleton (docs/GAME.md 1, "Skeleton as built") makes these
layouts final: banks 72, 73 (GCODE0, GCODE1: the tic phase's images), 74
(MOBJP: the thinker walk's planes and the sight hint planes), 91 (DEMOB),
92 (GTEST, test builds); the mobj's thinker next, function and tics leave
group A for the planes; the specials get free lists; LVS gets LNSECF,
LNSECB and RJROW (the GTABS step); the globals block gains section 1.5's
globals; validcount is one count, the frame block's VALIDCOUNT (G_VALID
is its alias). tools/native/glayout.py adds the tic phase.
"""

import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import rlayout as R  # noqa: E402

BANKS_TOTAL = 126               # RamWorks banks 1-126 (NATIVE.md 15.1 row
                                #   8: 8 MB, bank 127 excluded; 0 is aux 0)
ROOM = R.BANK_ROOM              # $0200-$BFFF of a bank
ROOM_BYTES = ROOM[1] - ROOM[0]

LVSEG, LVMAP, RENDB = R.LVSEG, R.LVMAP, R.RENDB
TEX_BANKS = tuple(range(9, 32)) + tuple(range(56, 64))
SPR_BANKS = tuple(range(32, 48)) + (64,)
SPRT, WPRO, RTH = R.SPRT, R.WPRO, R.RTH
RECSP, RECW = R.RECSP, R.RECW
LVG0, LVG1, LVG2, LVC = 65, 66, 67, 68
MOBJ = tuple(range(69, 72))     # stage C: 3 banks
ZONE0, ZONE1 = 75, 76
# milestone 10 (docs/GAME.md 1.10): the tic phase's code images, the
# planes, the demo that plays, the test bank
GCODE0, GCODE1 = 72, 73
MOBJP = 74
DEMOB, GTEST = 91, 92
STORE_BANKS = tuple(range(77, 91))
LCODE, GTAB = 98, 99
SONGS = tuple(range(100, 105))
TWOD = tuple(range(105, 111))
LVS = 111
CODE = R.CODE
TABLES = R.FSTEP_BANKS + (R.MT_TBANK, R.MT_RLO, R.MT_RHI)
LOGTAB = (123, 124)
# (1-5 stay first: ldisk.py's CRC_BANK is SPARE[3], PRE_BANK SPARE[4]: the
# test data of milestone 9)
SPARE = (1, 2, 3, 4, 5, 93, 94, 95, 96, 97, 125, 126)

# The persistent globals (MEMORY_MAP.md 3.1): the map whose variant
# columns and tails are in the shared stores (0: the canonical ones); the
# level's counts (words) after rlayout.LVCOUNT's sectors and sides: the
# lines, subsectors, segs and nodes (the bridge manifest's counts; the
# load program copies them from the level's header)
LV_VARMAP = 0x03A4
LVCOUNT2 = 0x03A6
LVCOUNT2_END = LVCOUNT2 + 8

# ---- LVG0: the lines, 32 bytes (docs/LEVELS.md 3.2) -----------------------
LINE = {'V1X': 0, 'V1Y': 2, 'V2X': 4, 'V2Y': 6, 'DX': 8, 'DY': 10,
        'SIDE0': 12, 'SIDE1': 14, 'TOP': 16, 'BOTTOM': 18, 'LEFT': 20,
        'RIGHT': 22, 'TAG': 24, 'SPECIAL': 25, 'FLAGS': 26, 'SLOPE': 27,
        'VALID': 28, 'RVALID': 30}
LINE_SIZE = 32
LINES = R.Array('line', LVG0, ROOM[0], LINE_SIZE, ROOM_BYTES // LINE_SIZE)

# ---- LVG1: the sectors' game part, 32 bytes, then the tables ------------
SECG = {'SOUNDX': 0, 'SOUNDY': 4, 'TARGET': 8, 'LCOUNT': 10, 'LFIRST': 12,
        'FLOORD': 14, 'CEILD': 16, 'TOUCH': 18, 'SPECIAL': 20,
        'OLDSPECIAL': 21, 'TAG': 22, 'TRAVERSED': 24}
SECG_SIZE = 32
SECGS = R.Array('sector game part', LVG1, ROOM[0], SECG_SIZE,
                R.SECTORS.capacity)
# after the records, in this order and each from the previous one's end
# (their sizes are the map's): the line tables (2 bytes an entry: a line),
# the flood index (8 bytes a sector: the first entry, the end of the
# entries without ML_SOUNDBLOCK (filled up from the first), the first
# entry with it (filled down from the end), the end: entry numbers), the
# flood entries (a byte: the other sector), the blocklinks (2 bytes a
# block: a mobj handle, $FFFF none). Their bases are per map
# (store.json; the load program's FILL and the steps take them).
FLIDX_SIZE = 8
NO_HANDLE = 0xFFFF

# ---- LVG2: the blockmap and reject, the game lumps verbatim -------------
BLOCKMAP = ROOM[0]              # REJECT follows it

# ---- LVC: the colormaps, the GSVIEWn record, FUZZDARK ---------------------
CMAP_SIZE = 34 * 256
LVC_CMAPA = ROOM[0]
LVC_CMAPB = LVC_CMAPA + CMAP_SIZE
LVC_GSVIEW = LVC_CMAPB + CMAP_SIZE
GSVIEW_SIZE = 1216              # 14 tints x 16 colours x 2, the pairs
                                #   (256), A and B (256 each)
LVC_FUZZ = LVC_GSVIEW + GSVIEW_SIZE
LVC_END = LVC_FUZZ + 256
# where the colormaps and FUZZDARK go (PRIVATE; MEMORY_MAP.md 3.2, 3.4,
# 5): light levels 0-31 of A at main $2000, of B at $4000; levels 32 and
# 33 of A at $0400, of B at $0600; FUZZDARK at aux 0 $0800 (the replay's)
MAIN_CMAPA, MAIN_CMAPB = 0x2000, 0x4000
MAIN_CMAPA_HI, MAIN_CMAPB_HI = 0x0400, 0x0600
CMAP_LOW = 32 * 256             # levels 0-31
AUX0_FUZZ = 0x0800

# ---- GTAB: the game's constant tables -------------------------------------
NUMSTATES, STATE_SIZE = 314, 16
NUMMOBJTYPES, INFO_SIZE = 50, 64
NUMSW2 = 38
GT = {}


def _gtab() -> Dict[str, Tuple[int, int]]:
    out, at = {}, ROOM[0]
    for name, size in (('STATES', NUMSTATES * STATE_SIZE),
                       ('MOBJINFO', NUMMOBJTYPES * INFO_SIZE),
                       ('COLORMAP', 34 * 256),
                       ('SWITCHLIST', 2 * NUMSW2),
                       ('SW_IDX', 256),
                       ('BASEPIC', 2)):
        out[name] = (at, size)
        at += size
    return out


GT = _gtab()

# ---- the level part's map things (docs/LEVELS.md 1.3), 8 bytes ----------
MTHING = {'X': 0, 'Y': 2, 'ANGLE': 4, 'OPTIONS': 5, 'KIND': 6}
MTHING_SIZE = 8
MT_PLAYER_START = 0xFE          # KIND: type 1, the player's start
MT_NEVER = 0xFF                 #   a thing no skill spawns
# the level part's compact sector (the game's form: special, tag)
SECC_SIZE = 3

# ---- the store (lstore.py) -----------------------------------------------
STORE_MAGIC = b'LVST'
STORE_VERSION = 1
CODEC_RAW = 0
# memory-API requests (appletini-one README_MEMORY_API.md, version 1, as
# a2vm models it): "AMEM" 1, a count (1-16), 0, 0, then 16-byte
# descriptors: op (1 COPY, 2 FILL), flags (bit 0 PRIVATE), the source
# (space, bank, address), the destination, the length, the fill byte
AMEM_MAGIC = b'AMEM\x01'
AMEM_MAX = 16
AMEM_COPY, AMEM_FILL, AMEM_PRIVATE = 1, 2, 1
REQUEST_BYTES = 45 * 1024       # the data of one request at most
# the load program's steps (docs/LEVELS.md 2.2)
STEPS = {'END': 0, 'COPYREQ': 1, 'VARIANTS': 2, 'LINES': 3, 'GROUP': 4,
         'FLOOD': 5, 'CMAPS': 6, 'PRIVREQ': 7, 'SPAWN': 8, 'SPECIALS': 9,
         # milestone 10: LVS's tables (lgeom.s lg_gtabs), a game step
         'GTABS': 10}
# the bank file format (demos/doom/src/kernel/loader.s): "A2DM", a
# segment count, segments of bank, address, length, then the bytes
BANKFILE_MAGIC = b'A2DM'
BANKFILE_MAX_SEGS = 49


# the store's directory: STORE0's first bytes, a fixed place the loader
# knows ("LVST", the version, the map count, 10 bytes of 0, then 4 bytes
# a map: its number, its header's bank and address); room for 12 maps
STORE_DIR_BANK = STORE_BANKS[0]
STORE_DIR = ROOM[0]
STORE_DIR_HEAD = 16
STORE_DIR_ENTRY = 4
STORE_DIR_MAPS = 12
STORE_DIR_SIZE = STORE_DIR_HEAD + STORE_DIR_ENTRY * STORE_DIR_MAPS
# a level's header (lstore.header_bytes): "LH", the map, 0; the counts
# (words) from LH_COUNTS in HEADER_COUNTS' order; each block of
# BLOCK_KINDS from LH_BLOCKS, 6 bytes (bank, codec, address, length);
# the LVG1 bases (LTAB, FLIDX, FLENT, BLINKS), REJECT's address, the
# blockmap's origin and size, the sky's bank and address
HEADER_COUNTS = ('sectors', 'sides', 'lines', 'subsectors', 'segs',
                 'nodes', 'vertices', 'things', 'blocks', 'linetable',
                 'flood')
BLOCK_KINDS = ('SEGS', 'NODES', 'SUBS', 'SECTORS', 'SIDES', 'TXFLAT',
               'LINES', 'SECC', 'BLOCKMAP', 'REJECT', 'THINGS', 'WTAB',
               'TXMP', 'SPRFR', 'GSVIEW', 'FUZZ', 'APPLY', 'UNDO',
               'APPLYREQ', 'UNDOREQ', 'PROGRAM')
LH_COUNTS = 4
LH_BLOCKS = LH_COUNTS + 2 * len(HEADER_COUNTS)
LH_BLOCK = 6
LH_LVG1 = LH_BLOCKS + LH_BLOCK * len(BLOCK_KINDS)
LH_REJECT = LH_LVG1 + 8
LH_BLOCKMAP = LH_REJECT + 2
LH_SKY = LH_BLOCKMAP + 8
# stage C: the lump numbers of the map's BLOCKMAP and REJECT in the
# release's directory (the bridge's identity of those two objects, which
# the setup copies into the game globals)
LH_LUMPS = LH_SKY + 3
LH_SIZE = LH_LUMPS + 4
# a load program (lstore.program_bytes): "LP", the map, the step count,
# the request count, 0; the steps (an opcode, an argument word); the
# requests (a descriptor count, the descriptors)
LP_HEAD = 6
LP_STEP = 3
# the compact forms of the level part (the game lumps' fields)
LINEC = {'V1X': 0, 'V1Y': 2, 'V2X': 4, 'V2Y': 6, 'SIDE0': 8, 'SIDE1': 10,
         'FLAGS': 12, 'SPECIAL': 13, 'TAG': 14}
LINEC_SIZE = 15
SECC_FIELDS = {'SPECIAL': 0, 'TAG': 1}
ML_TWOSIDED, ML_SOUNDBLOCK = 4, 64
GSVIEW_A = 14 * 16 * 2 + 256    # the GSVIEWn record's table A (B follows)

# ---- stage B: the load phase (docs/LEVELS.md 2.2, 2.3, 4.2, 4.3) --------
# Its stop codes, in LV_STATUS (main $03AE, after the level's counts): the
# loader stores the code there and executes BRK (the renderer's rule)
LV_STATUS = 0x03AE
LV_AMEM = 0x03AF                # the memory API's result of a failed request
LS = {'OK': 0, 'DIR': 1, 'MAP': 2, 'CODEC': 3, 'PROGRAM': 4, 'AMEM': 5,
      'NOSIDE': 6, 'LINES': 7, 'SECTORS': 8, 'REQUESTS': 9, 'STEPS': 10,
      # stage C: more map things than POOL_MAX, the zone mobjs' room, a
      # kind's specials, the sector nodes, a thing's sectors past SECL_MAX,
      # a state action the setup does not know, a blockmap of 256 columns
      # or rows or more (P_InitBlockRows' I_Error)
      'THINGS': 11, 'ZONE': 12, 'SPECIALS': 13, 'NODES': 14, 'SECL': 15,
      'ACTION': 16, 'BLOCKMAP': 17,
      # milestone 10: the game core in the load image: a slot past the
      # planes, the object API misused (a dirty mark with no line got)
      'PLANES': 18, 'API': 19}
# W in the load phase (MEMORY_MAP.md 3.5's mode window): MATHW and AUXW
# from $6000 (the render images' bytes), the load code from $6600 (to
# $9FFF), then the data
LW_CODE, LW_CODE_END = 0x6600, 0xA000
LW_REQ = 0xA000                 # a request: 20 bytes of SmartPort and
REQ_HEAD = 20                   #   "AMEM" header, then 16 descriptors
LW_REQ_END = LW_REQ + REQ_HEAD + 16 * 16
# the static steps' scratch (GROUP, FLOOD), over the request buffer and
# stage C's mobjinfo (no request runs inside a step; the spawn copies
# mobjinfo after them): each line's front and back sector (the back is
# the front for a line with one side), each sector's line count, first
# entry and two running positions
LINE_ROOM = 0x0600              # the lines a load can take (LVG0: 1,520)
LW_LFRONT = 0xA000
LW_LBACK = LW_LFRONT + LINE_ROOM
LW_CNTLO, LW_CNTHI = 0xAC00, 0xAD00
LW_FSTLO, LW_FSTHI = 0xAE00, 0xAF00
LW_POSLO, LW_POSHI = 0xB000, 0xB100
LW_DNLO, LW_DNHI = 0xB200, 0xB300
# CMAPS's pages and FLOOD's zeros (after GROUP's scratch)
LW_CMA, LW_CMB, LW_CMI, LW_CMO = 0xB400, 0xB500, 0xB600, 0xB700
LW_ZERO = 0xB400
LW_MOBJINFO = 0xB000            # reserved (4.2); stage C reads a record a spawn
#                                 (LW_MINFO, from GTAB) instead
# the buffers (docs/LEVELS.md 4.2's $BC80-$BFFF)
LW_HDR = 0xBC80                 # the map's header (LH_SIZE)
LW_DIR = LW_HDR + 0xC0          # the store's directory (STORE_DIR_SIZE)
LW_STEPS = LW_DIR + 0x40        # the program's head and steps
LSTEP_MAX = 60
LW_REQLO = LW_STEPS + LP_HEAD + LP_STEP * LSTEP_MAX     # each request's
LREQ_MAX = 32                                           #   place
LW_REQHI = LW_REQLO + LREQ_MAX
LW_LR = LW_REQHI + LREQ_MAX     # a line record (32)
LW_LC = LW_LR + 32              # a compact line (16)
LW_SR = LW_LC + 16              # a sector's game record (32)
LW_SUB = LW_SR + 32             # a subsector record (4)
LW_BE = LW_SUB + 4              # a block entry, a word (8)
LW_END = LW_BE + 8
# the load's zero page (docs/LEVELS.md 4.3): $38-$41 the program, $48-$AF
# the steps and the transport
LZP1 = [('LP_MAP', 1), ('LP_STEP', 1), ('LP_NSTEP', 1), ('LP_NREQ', 1),
        ('LP_PB', 1), ('LP_ARG', 1), ('LP_P', 2), ('LP_N', 2)]
LZP2 = [('AM_P', 2), ('AM_N', 2), ('AM_W', 1),
        ('LG_I', 2), ('LG_N', 2), ('LG_SB', 1), ('LG_SA', 2),
        ('LG_DA', 2), ('LG_PF', 2), ('LG_PB', 2), ('LG_F', 1),
        ('LG_B', 1), ('LG_S', 1), ('LG_NS', 1), ('LG_K', 2), ('LG_KN', 2),
        ('LG_BOX', 8),          # right, left, top, bottom (high words)
        ('LG_FRESH', 1), ('LG_A', 4), ('LG_E', 2), ('LG_C', 2), ('LG_V', 2)]
LZP1_RANGE = (0x38, 0x42)
LZP2_RANGE = (0x48, 0xB0)
LOAD_STACK = 128                # MEMORY_MAP.md 2: the level load's budget
# the a2vm test driver's map list (ldriver.s, DESC): at most this many
DL_MAX = 32

# ---- stage C: the game state (docs/LEVELS.md 2.4-3.3) ---------------------
# The mobjs: a slot is a RTHING slot (rlayout.RTHINGS: the render part, 24
# bytes in RTH, its four spare bytes the angle's low word) and three game
# parts of 24 bytes at the same address in MOBJA, MOBJB, MOBJC (slot i at
# $0200 + 24 i, as RTHING: 2,026 fill a bank). The pool's slots come
# first (poolsize = the map's things, at most POOL_MAX), then the zone
# mobjs. MOBJ's other three banks of the design (72-74) are spare.
MOBJA, MOBJB, MOBJC = MOBJ[0], MOBJ[1], MOBJ[2]
MOBJ_BANKS = (MOBJA, MOBJB, MOBJC)
MOBJ_CAP = R.RTHINGS.capacity
POOL_MAX = 512                  # TP_MAX (p_spawn65.s)
MO_SIZE = 24
TH_ANGLO = 20                   # RTHING: the angle's low word
# group A (milestone 10, docs/GAME.md 1.2: the thinker next, the function
# and the tics are the planes' (MOBJP); their bytes 2-4 and 18-19 are
# spare, so every other field keeps milestone 9's offset)
MA = {'THPREV': 0, 'TYPE': 5, 'SPREV': 6,
      'BNEXT': 8, 'BPREV': 10, 'SUBSEC': 12, 'TOUCH': 14, 'STATE': 16,
      'HEALTH': 20, 'TARGET': 22}
MA_SPARE = (2, 3, 4, 18, 19)
MB = {'FLOORZ': 0, 'CEILZ': 4, 'DROPZ': 8, 'RADIUS': 12, 'HEIGHT': 16,
      'FLAGS': 20}
MC = {'MOMX': 0, 'MOMY': 4, 'MOMZ': 8, 'MOVEDIR': 12, 'THRESH': 13,
      'PURSUE': 14, 'MOVEC': 16, 'REACT': 18, 'LASTEN': 20, 'SIGHT': 22}
# the specials (ZONE0): 32 bytes a record, one range of slots a kind; a
# special's handle is SPEC_HANDLE + its slot (the thinker handles: 0-2,025
# the mobjs, SPEC_HANDLE up the specials, $FFFF none)
SPEC_SIZE = 32
SPEC_HANDLE = 0x0800
SPEC_KINDS = (('plat', 256), ('door', 256), ('floor', 256),
              ('lightflash', 128), ('strobe', 128), ('glow', 128),
              ('scroll', 128))
SPEC_RANGE: Dict[str, Tuple[int, int]] = {}
_at = 0
for _k, _n in SPEC_KINDS:
    SPEC_RANGE[_k] = (_at, _n)
    _at += _n
SPEC_CAP = _at
SPECS = R.Array('special', ZONE0, ROOM[0], SPEC_SIZE, SPEC_CAP)
SP = {'THPREV': 0, 'THNEXT': 2, 'FUNC': 4, 'SECTOR': 5}
SP_KIND = {
    'lightflash': {'COUNT': 6, 'MAXLIGHT': 8, 'MINLIGHT': 10},
    'strobe': {'COUNT': 6, 'MINLIGHT': 8, 'MAXLIGHT': 10, 'DARKTIME': 12},
    'glow': {'MINLIGHT': 6, 'MAXLIGHT': 8, 'DIRECTION': 10},
    'scroll': {'SIDE': 6},
    'plat': {'SPEED': 6, 'LOW': 10, 'HIGH': 14, 'WAIT': 18, 'COUNT': 20,
             'STATUS': 22, 'TAG': 24, 'TYPE': 26, 'LIST': 28},
    'door': {'TYPE': 6, 'TOPHEIGHT': 8, 'SPEED': 12, 'DIRECTION': 16,
             'TOPCOUNTDOWN': 17, 'LINE': 19, 'LIGHTTAG': 21},
    'floor': {'TYPE': 6, 'DIRECTION': 8, 'TEXTURE': 9, 'DEST': 11,
              'SPEED': 15}}
# the sector nodes (ZONE1): 16 bytes, taken as upstream's newSecnode does
# (a pool of SN_POOL nodes when the free list is empty: the free list's
# length is upstream's); free = 1 on the free list
SN_SIZE = 16
SN_CAP = 2048
SN_POOL = 32
SNODES = R.Array('sector node', ZONE1, ROOM[0], SN_SIZE, SN_CAP)
SN = {'SECTOR': 0, 'FREE': 1, 'THING': 2, 'TPREV': 4, 'TNEXT': 6,
      'SPREV': 8, 'SNEXT': 10, 'VISITED': 12}
# The planes (milestone 10, docs/GAME.md 1.3, 1.6): bank MOBJP. The thinker
# walk's four planes of PLANE_SLOTS bytes at the W addresses the tic phase
# holds them at (far_pload copies their pages into W at the tic phase's
# start; the load image reaches them far): TNL, TNH (the next thinker's
# handle), KIND (the function's FN number, bit 7 CLEAN: the kind cache),
# TICS (a byte, $FF for -1); a slot past PLANE_SLOTS - 1 is a stop
# (GS_PLANES). The sight hint planes HINTL, HINTH (a line + 1 by pool slot,
# 0 none: upstream's SIGHTHINT) of HINT_SLOTS.
PLANE_SLOTS = 768
PL_TNL, PL_TNH, PL_KIND, PL_TICS = 0xB400, 0xB700, 0xBA00, 0xBD00
PLANES_W = (PL_TNL, PL_TICS + PLANE_SLOTS)
HINT_SLOTS = 2048
PL_HINTL, PL_HINTH = ROOM[0], ROOM[0] + HINT_SLOTS
KIND_CLEAN = 0x80
# LVS (milestone 10, docs/GAME.md 1.6): each line's front and back sector
# (a byte each, the front twice for a one-sided line: upstream's LNSEC),
# each sector's REJECT row (sector x numsectors, 2 bytes: upstream's
# SS_ROW by sector), made by the load's GTABS step
LVS_LNSECF = ROOM[0]
LVS_LNSECB = LVS_LNSECF + LINE_ROOM
LVS_RJROW = LVS_LNSECB + LINE_ROOM
LVS_END = LVS_RJROW + 2 * 256
# the thinker functions (a byte: the manifest's enum in this order); FREE
# marks a free zone mobj slot (on G_ZMFREE's list: no object)
FUNCS = (None, 'p_tick65.s:P_MobjThinker',
         'p_tick65.s:P_MobjBrainlessThinker',
         'p_think65.s:P_RemoveThingDelayed',
         'p_think65.s:P_RemoveThinkerDelayed', 'p_plats65.s:T_PlatRaise',
         'p_doors65.s:T_VerticalDoor', 'p_floor65.s:T_MoveFloor',
         'p_lights65.s:T_LightFlash', 'p_lights65.s:T_StrobeFlash',
         'p_lights65.s:T_Glow', 'p_spec65.s:T_Scroll', '(free)')
FN = {'NONE': 0, 'MOBJ': 1, 'BRAINLESS': 2, 'REMOVETHING': 3,
      'REMOVETHINKER': 4, 'PLAT': 5, 'DOOR': 6, 'FLOOR': 7, 'FLASH': 8,
      'STROBE': 9, 'GLOW': 10, 'SCROLL': 11, 'FREE': 12}
FN_FREE_NAME = '(free)'
# each special kind's function
SPEC_FN = {'plat': 'PLAT', 'door': 'DOOR', 'floor': 'FLOOR',
           'lightflash': 'FLASH', 'strobe': 'STROBE', 'glow': 'GLOW',
           'scroll': 'SCROLL'}
# The game globals (MEMORY_MAP.md 3.3's hot game globals, after TEXTRANS
# and LNMAP): main $1C80-$1FFF, the player first. P_Random's and
# M_Random's indexes stay at main $03EE, $03EF (MATH.md).
LNMAP = R.LNMAP                 # rlayout: ML_MAPPED, a bit a line (2,048:
LNMAP_END = R.LNMAP + R.LNMAP_LINES // 8    # $1B80-$1C7F)
GBLOCK, GBLOCK_END = LNMAP_END, 0x2000
GLOBAL_FIELDS = [
    ('G_PLAYER', 148), ('G_BUTTONS', 36), ('G_TPBITS', POOL_MAX // 8),
    ('G_THFIRST', 2), ('G_THLAST', 2), ('G_SNFREE', 2), ('G_SECLIST', 2),
    ('G_SNHWM', 2), ('G_SPN', 2 * len(SPEC_KINDS)), ('G_ZMN', 2),
    ('G_POOLN', 2), ('G_BLOCKS', 2), ('G_LTABN', 2),
    ('G_BMW', 2), ('G_BMH', 2), ('G_BMORGX', 4), ('G_BMORGY', 4),
    ('G_BMAP', 2), ('G_BMLEN', 2), ('G_REJLEN', 2), ('G_BMLUMP', 2),
    ('G_REJLUMP', 2), ('G_LOGP', 2), ('G_CEILLINE', 2),
    ('G_MPCLOB', 2), ('G_LEVELTIME', 4),
    ('G_GAMEACTION', 2), ('G_GAMESTATE', 2), ('G_GAMESKILL', 2),
    ('G_GAMEMAP', 2), ('G_GAMETIC', 4), ('G_BASETIC', 4),
    ('G_TOTALKILLS', 4), ('G_TOTALLIVE', 4), ('G_TOTALITEMS', 4),
    ('G_TOTALSECRET', 4), ('G_WMINFO', 40), ('G_RESPAWN', 2),
    ('G_USERGAME', 2), ('G_TIMINGDEMO', 2), ('G_DEMOPLAY', 2),
    ('G_SINGLEDEMO', 2), ('G_DEMOBUF', 5), ('G_DEMOLEN', 2),
    ('G_DEMOP', 5), ('G_STARTTIME', 4), ('G_TOTALTIMES', 4),
    ('G_DSKILL', 2), ('G_SAVESLOT', 2), ('G_SECRETEXIT', 2),
    ('G_DEFDEMO', 5), ('G_CMDS', 64), ('G_PREVSTATE', 2),
    ('G_MENUACTIVE', 2),
    # milestone 10 (docs/GAME.md 1.5): each special kind's free list (a
    # head, $FFFF none), the zone mobjs' free list (through the TNL, TNH
    # planes) and the planes' high-water slot; P_CheckSight's last pair
    # and answer ($FFFE: stale, names no object); the line record of
    # lineBlocks (LR_N lines * 2 or $FF, LR_LINES 2 * the line, as
    # upstream's); the action that started a load (the load protocol);
    # showMessages and _g_message_dontfuckwithme; wi_stuff65.s's game-side
    # counters (WI_*); the lockstep and test state (GT_*)
    ('G_SPFREE', 2 * len(SPEC_KINDS)), ('G_ZMFREE', 2), ('G_MOHWM', 2),
    ('CS_PREV1', 2), ('CS_PREV2', 2), ('CS_PREVR', 1),
    ('G_LROK', 1), ('G_LRUSE', 1), ('G_LRN', 1), ('G_LRLINES', 48),
    ('G_LOADACT', 1), ('G_SHOWMSG', 2), ('G_MSGKEEP', 2),
    # the map's places in LVG1 and LVG2 the tic phase needs (the setup
    # copies them from the map's header): the line tables, the flood
    # index and entries, the blocklinks, REJECT
    ('G_LTABAT', 2), ('G_FLIDXAT', 2), ('G_FLENTAT', 2), ('G_BLINKSAT', 2),
    ('G_REJECTAT', 2),
    ('WI_ACCEL', 2), ('WI_STATE', 2), ('WI_CNT', 2), ('WI_BCNT', 2),
    ('WI_CNTTIME', 4), ('WI_CNTTOTAL', 4), ('WI_CNTPAR', 2),
    ('WI_CNTPAUSE', 2), ('WI_SPSTATE', 2), ('WI_CNTKILLS', 2),
    ('WI_CNTITEMS', 2), ('WI_CNTSECRET', 2), ('WI_SNLPTR', 2),
    ('GT_DIV0', 2), ('GT_HINT', 1), ('GT_ZPREV', 1), ('GT_SCHED', 2),
    ('GT_STREAM', 2), ('GT_TIMEP', 2), ('GT_SNDLOG', 2), ('GT_HITLOG', 2),
    ('GT_REKEY', 2), ('GT_TIC', 4), ('GT_FLAGS', 1)]
G = R.allocate(GLOBAL_FIELDS, GBLOCK, GBLOCK_END)
# validcount is one count (docs/GAME.md 1.7): the frame block's VALIDCOUNT;
# G_VALID is its name in the game's sources
G_VALID = R.FRAME['VALIDCOUNT']
GLOBALS_END = max(G[n] + s for n, s in GLOBAL_FIELDS)
PRND, MRND = 0x03EE, 0x03EF     # math.inc MT_PRND, MT_MRND
# the canonical globals and where they are: (field, size) or a level
# count's address, or a GTAB table (the boot's constants)
GLOBAL_PLACE = {
    'g_game65.s:_g_gameaction': 'G_GAMEACTION',
    'g_game65.s:_g_gamestate': 'G_GAMESTATE',
    'g_game65.s:_g_gameskill': 'G_GAMESKILL',
    'g_game65.s:_g_gamemap': 'G_GAMEMAP',
    'g_game65.s:_g_gametic': 'G_GAMETIC', 'g_game65.s:_g_basetic': 'G_BASETIC',
    'g_game65.s:_g_totalkills': 'G_TOTALKILLS',
    'g_game65.s:_g_totallive': 'G_TOTALLIVE',
    'g_game65.s:_g_totalitems': 'G_TOTALITEMS',
    'g_game65.s:_g_totalsecret': 'G_TOTALSECRET',
    'g_game65.s:_g_wminfo': 'G_WMINFO',
    'g_game65.s:_g_respawnmonsters': 'G_RESPAWN',
    'g_game65.s:_g_usergame': 'G_USERGAME',
    'g_game65.s:_g_timingdemo': 'G_TIMINGDEMO',
    'g_game65.s:_g_demoplayback': 'G_DEMOPLAY',
    'g_game65.s:_g_singledemo': 'G_SINGLEDEMO',
    'g_game65.s:demobuffer': 'G_DEMOBUF', 'g_game65.s:demolength': 'G_DEMOLEN',
    'g_game65.s:demo_p': 'G_DEMOP', 'g_game65.s:starttime': 'G_STARTTIME',
    'g_game65.s:totalleveltimes': 'G_TOTALTIMES',
    'g_game65.s:d_skill': 'G_DSKILL', 'g_game65.s:savegameslot': 'G_SAVESLOT',
    'g_game65.s:secretexit': 'G_SECRETEXIT',
    'g_game65.s:defdemoname': 'G_DEFDEMO', 'g_game65.s:cmds': 'G_CMDS',
    'g_game65.s:prevgamestate': 'G_PREVSTATE',
    'm_menu65.s:_g_menuactive': 'G_MENUACTIVE',
    'p_think65.s:_g_leveltime': 'G_LEVELTIME',
    'p_think65.s:_g_thinkerclasscap': 'G_THFIRST',
    'p_map65.s:validcount': 'G_VALID',
    'p_map65.s:LR_OK': 'G_LROK', 'p_map65.s:LR_USE': 'G_LRUSE',
    'p_map65.s:LR_N': 'G_LRN', 'p_map65.s:LR_LINES': 'G_LRLINES',
    'p_sight65.s:CS_PREV1': 'CS_PREV1', 'p_sight65.s:CS_PREV2': 'CS_PREV2',
    'p_sight65.s:CS_PREVR': 'CS_PREVR',
    'p_map65.s:_g_ceilingline': 'G_CEILLINE',
    'p_map65.s:_s_sector_list': 'G_SECLIST', 'p_map65.s:SN_FREE': 'G_SNFREE',
    'p_map65.s:MP_CLOB': 'G_MPCLOB',
    'p_setup65.s:_g_bmapwidth': 'G_BMW', 'p_setup65.s:_g_bmapheight': 'G_BMH',
    'p_setup65.s:_g_bmaporgx': 'G_BMORGX',
    'p_setup65.s:_g_bmaporgy': 'G_BMORGY',
    'p_setup65.s:_g_blockmap': 'G_BMAP',
    'p_setup65.s:_g_thingPoolSize': 'G_POOLN',
    'p_sight65.s:LOGP': 'G_LOGP'}
# the canonical caches the native layout does not keep (docs/LEVELS.md 5.2
# exclusion 4: no leaf; the comparison skips them). Milestone 10 keeps the
# line record (LR_*), P_CheckSight's pair (CS_PREV*) and mobj.sightline
# (docs/GAME.md 0.3 facts 2-4); TP_HW and the dead guard's state stay out
# (GAME.md 3.5, R4 and R5)
NOT_KEPT = ('p_spawn65.s:TP_HW', 'p_path65.s:GW_TAG', 'p_path65.s:G_ID')
NOT_KEPT_FIELDS = ('line.gstamp',)
# the native's "stale" handle (docs/GAME.md 1.8): a CS_PREV that names no
# object
STALE = 0xFFFE
# the test pre-states (harness and test disk only: the game has none): the
# game globals block, then P_Random's and M_Random's indexes, one record a
# setup in a spare bank (docs/LEVELS.md 5.4)
PRE_BANK = SPARE[4]
PRE_RECORD = 0x0410
PRE_RND = GLOBALS_END - GBLOCK      # (the block's used part)
# milestone 10: then validcount (the frame block's VALIDCOUNT, G_VALID)
PRE_VALID = PRE_RND + 2
PRE_MAX = (ROOM_BYTES) // PRE_RECORD
# ---- milestone 10: the object API and the game core's buffers --------------
# (docs/GAME.md 3.4, 4.1). The game core runs in the load image (nl_setup)
# and in the tic images, so its buffers and the API's caches have the same
# places in both: main $0C00-$0EFF (the mobj cache, 8 lines of RTHING and
# groups A, B, C), $1680-$17FF (the sector cache, 8 lines of the render
# and game records), $0200-$02FF (bl_get's block list), $1980-$1A7F (the
# runtime's state: tags, LRU, dirty bits; gcall.s's slots), and W
# $AE00-$B3FF (the line cache, 8 lines of the record and its two sectors;
# the special cache, 4 lines; the intercepts and their chain; the spawn's
# mobj, mobjinfo and state; the fetch buffers of nd_get, sg_get, ss_get;
# the setup's map thing; a sector node). In the load image $AE00-$B3FF is
# GROUP's and FLOOD's scratch (LW_FSTLO .. LW_DNHI), dead once GTABS has
# run: nl_setup flushes and empties the caches first, and nothing of the
# load writes there after GTABS's lg_prep.
MOC, MOC_LINES, MOC_LINE = 0x0C00, 8, 4 * MO_SIZE
SCC, SCC_LINES, SCC_LINE = 0x1680, 8, 16 + 32
BL_BUF = 0x0200
RT_STATE, RT_END = 0x1980, 0x1A80
LNC_LINES, LNC_LINE = 8, LINE_SIZE + 2
SPC_LINES, SPC_LINE = 5, SPEC_SIZE   # (5: the four most recently got stay)
MAXINTERCEPTS, ICPT_SIZE = 64, 6
GW, GW_END = 0xAE00, 0xB400
NODEB_SIZE = 28                 # a node's record up to its children
GW_FIELDS = [('LNC', LNC_LINES * LNC_LINE), ('SPC', SPC_LINES * SPC_LINE),
             ('ICPT', MAXINTERCEPTS * ICPT_SIZE),
             ('ICHAIN', MAXINTERCEPTS + 1),
             # the mobj being made (RTHING, A, B, C: a mobj cache line's
             # form), then the spawn's working tics (2) and function (1)
             ('LW_MOB', 4 * MO_SIZE + 3),
             ('LW_MINFO', INFO_SIZE), ('LW_STATE', STATE_SIZE),
             ('LW_NODEB', NODEB_SIZE), ('SG_BUF', R.SEG_SIZE),
             ('SS_BUF', R.SUB_SIZE), ('LW_MT', MTHING_SIZE),
             ('LW_SREC', 16), ('LW_SPEC', SPEC_SIZE), ('LW_SN', SN_SIZE),
             # a line's record and its two sectors (a line cache line's
             # copy: the block walk's)
             ('LW_LINEB', LINE_SIZE + 2)]
GWA = R.allocate(GW_FIELDS, GW, GW_END)
GW_USED = max(GWA[n] + k for n, k in GW_FIELDS)
LW_MOB, LW_MINFO, LW_STATE = GWA['LW_MOB'], GWA['LW_MINFO'], GWA['LW_STATE']
LW_NODEB, LW_MT, LW_SREC = GWA['LW_NODEB'], GWA['LW_MT'], GWA['LW_SREC']
LW_SPEC, LW_SN, LW_LINEB = GWA['LW_SPEC'], GWA['LW_SN'], GWA['LW_LINEB']
MO_XTICS, MO_XFUNC = 4 * MO_SIZE, 4 * MO_SIZE + 2   # (LW_MOB + offset)
LW_GAME_END = GW_USED
# stage C's zero page: the game core's ($18-$37: the same bytes in
# milestone 10's tic phase) and the spawn's (after the load's LZP2)
LZPG = [('GC_MO', 2), ('GC_H', 2), ('GC_T', 2), ('GC_P', 2), ('GC_SEC', 1),
        ('GC_K', 1), ('GC_X', 4), ('GC_Y', 4), ('GC_V', 4), ('GC_W', 4),
        ('GC_PREV', 2), ('GC_N', 2), ('GC_S', 2)]
LZPG_RANGE = (0x18, 0x38)
LZPS = [('GS_I', 2), ('GS_N', 2), ('GS_SB', 1), ('GS_SA', 2),
        ('GS_XL', 1), ('GS_XH', 1), ('GS_YL', 1), ('GS_YH', 1),
        ('GS_BX', 1), ('GS_BY', 1), ('GS_LIST', 2), ('GS_LN', 2),
        ('GS_RF', 2), ('GS_TF', 2), ('GS_LH', 2), ('GS_BH', 2),
        ('GS_TOP', 4), ('GS_BOT', 4), ('GS_LEFT', 4), ('GS_RIGHT', 4),
        ('GS_SIDE', 1), ('GS_NSEC', 1), ('GS_BP', 1), ('GS_BLEFT', 2),
        ('GS_PSP', 1), ('GS_ST', 2), ('GS_CNT', 1), ('GS_GAME', 1),
        ('GS_L', 4), ('GS_S1', 1), ('GS_K', 2)]
GAME_STACK = LOAD_STACK         # the setup's budget: the load's
MATH_ZP = (0xB0, 0xD8)          # math.inc's block (the spawn's products)


class Use(NamedTuple):
    first: int
    last: int
    name: str


def bank_map() -> List[Tuple[int, str]]:
    """Every bank 1-126 with its use."""
    uses: Dict[int, str] = {}

    def put(banks: Sequence[int], name: str) -> None:
        for b in banks:
            if b in uses:
                raise ValueError('bank %d: %s and %s' % (b, uses[b], name))
            if not 1 <= b <= BANKS_TOTAL:
                raise ValueError('bank %d of %s outside 1-126' % (b, name))
            uses[b] = name
    put([LVSEG], 'LVSEG')
    put([LVMAP], 'LVMAP')
    put([RENDB], 'RENDB')
    put(TEX_BANKS, 'TEX')
    put(SPR_BANKS, 'SPR')
    put([SPRT], 'SPRT')
    put([WPRO], 'WPRO')
    put([RTH], 'RTH')
    put(RECSP, 'RECSP')
    put([RECW], 'RECW')
    put([LVG0], 'LVG0')
    put([LVG1], 'LVG1')
    put([LVG2], 'LVG2')
    put([LVC], 'LVC')
    put(MOBJ, 'MOBJ')
    put([ZONE0], 'ZONE0')
    put([ZONE1], 'ZONE1')
    put(STORE_BANKS, 'STORE')
    put([LCODE], 'LCODE')
    put([GTAB], 'GTAB')
    put(SONGS, 'songs')
    put(TWOD, '2D')
    put([LVS], 'LVS')
    put(CODE, 'CODE')
    put(TABLES, 'tables')
    put(LOGTAB, 'LOGTAB')
    # milestone 10 (docs/GAME.md 1.10)
    put((GCODE0, GCODE1), 'GCODE')
    put([MOBJP], 'MOBJP')
    put([DEMOB], 'DEMOB')
    put([GTEST], 'GTEST (test builds)')
    for b in SPARE:
        if b in uses:
            raise ValueError('spare bank %d is used by %s' % (b, uses[b]))
    return sorted(uses.items())


def check() -> None:
    bank_map()
    if LVC_END > ROOM[1]:
        raise ValueError('LVC past $BFFF')
    last = max(a + n for a, n in GT.values())
    if last > ROOM[1]:
        raise ValueError('GTAB past $BFFF')
    if SECGS.end > ROOM[1]:
        raise ValueError('the sectors\' game part past $BFFF')
    # milestones 7 and 8's banks are where rlayout.py has them
    if (R.LVSEG, R.LVMAP, R.RENDB, R.SPRT, R.WPRO, R.RTH) != \
            (6, 7, 8, 48, 49, 50):
        raise ValueError('a bank of milestones 7 and 8 moved')
    if not 0x03A4 >= R.LVCOUNT + 4:
        raise ValueError('LV_VARMAP overlaps the level counts')
    if not LVCOUNT2_END <= LV_STATUS < LV_AMEM < 0x03EE:
        raise ValueError('LV_STATUS overlaps the persistent globals')
    # stage B's W: the code, the request, the scratch, the buffers
    if LW_REQ_END > LW_LBACK or LW_LBACK + LINE_ROOM > LW_CNTLO:
        raise ValueError('the request or the lines\' sectors overlap')
    if LINES.capacity > LINE_ROOM:
        raise ValueError('LVG0 holds more lines than the load\'s scratch')
    if LW_DNHI + 0x100 > LW_CMA or LW_CMO + 0x100 > LW_HDR:
        raise ValueError('the load\'s scratch reaches its buffers')
    if LW_MOBJINFO + NUMMOBJTYPES * INFO_SIZE > LW_HDR:
        raise ValueError('mobjinfo reaches the load\'s buffers')
    if LW_DIR < LW_HDR + LH_SIZE or LW_STEPS < LW_DIR + STORE_DIR_SIZE or \
            LW_END > 0xC000:
        raise ValueError('the load\'s buffers overlap or pass $BFFF')
    if LP_HEAD + LP_STEP * LSTEP_MAX > 255:
        raise ValueError('the steps pass one far_get')
    if STORE_DIR_HEAD + STORE_DIR_ENTRY * STORE_DIR_MAPS > 255:
        raise ValueError('the directory passes one far_get')
    # stage C
    if MOBJ_CAP * MO_SIZE > ROOM_BYTES or SPECS.end > ROOM[1] or \
            SNODES.end > ROOM[1]:
        raise ValueError('a game array passes its bank')
    if LNMAP_END > GBLOCK or GLOBALS_END > GBLOCK_END:
        raise ValueError('the game globals pass $1FFF')
    if TH_ANGLO + 2 > R.RTHING_SIZE or TH_ANGLO < R.RTHING['SNEXT'] + 2:
        raise ValueError('the angle\'s low word is not in RTHING\'s pad')
    for table in (MA, MB, MC):
        if max(table.values()) + 2 > MO_SIZE:
            raise ValueError('a mobj game part passes 24 bytes')
    for kind, fields in SP_KIND.items():
        if max(fields.values()) + 4 > SPEC_SIZE:
            raise ValueError('a %s passes its record' % kind)
    if SPEC_HANDLE <= MOBJ_CAP or SPEC_HANDLE + SPEC_CAP >= 0xFFFF:
        raise ValueError('the thinker handles overlap')
    # milestone 10: the API's W in the load image's dead scratch (GROUP's
    # and FLOOD's), the main caches in render scratch MEMORY_MAP.md 3.3
    # marks not persistent (glayout.py checks the tic phase's map)
    if GW < LW_FSTLO or GW_END > LW_DNHI + 0x100 or GW_END > LW_CMA:
        raise ValueError('the API\'s W is not the load\'s dead scratch')
    if MOC + MOC_LINES * MOC_LINE > 0x0F00 or \
            SCC + SCC_LINES * SCC_LINE > 0x1800 or RT_END > R.DSX2 + 0x80:
        raise ValueError('a cache past its main room')
    if PL_TNL < ROOM[0] or PL_TICS + PLANE_SLOTS > ROOM[1] or \
            PL_HINTH + HINT_SLOTS > PL_TNL or \
            PL_TNH != PL_TNL + PLANE_SLOTS or \
            PL_KIND != PL_TNH + PLANE_SLOTS or \
            PL_TICS != PL_KIND + PLANE_SLOTS or PLANE_SLOTS & 0xFF:
        raise ValueError('the planes')
    if POOL_MAX > HINT_SLOTS or LVS_END > ROOM[1] or \
            LINE_ROOM < LINES.capacity:
        raise ValueError('LVS or the hints')
    if FN['FREE'] != len(FUNCS) - 1 or FUNCS[-1] != FN_FREE_NAME or \
            FN['FREE'] & KIND_CLEAN:
        raise ValueError('the free function')
    if PRE_VALID + 2 > PRE_RECORD or PRE_MAX < 9:
        raise ValueError('the pre-states')
    if len(FUNCS) != len(FN) or any(FUNCS.index(f) != i for i, f in
                                    enumerate(FUNCS)):
        raise ValueError('the thinker functions')


def used_banks() -> int:
    return len(bank_map())


# ---------------------------------------------------------------------------
# llayout.inc (stage B: the load phase's sources, after rlayout.inc)
# ---------------------------------------------------------------------------

ZP_LOAD1 = R.allocate(LZP1, *LZP1_RANGE)
ZP_LOAD2 = R.allocate(LZP2, *LZP2_RANGE)
# stage C: the game core's ($18-$37) and the spawn's (from LZP2's end)
ZP_GAME = R.allocate(LZPG, *LZPG_RANGE)
LZPS_RANGE = (max(ZP_LOAD2[n] + s for n, s in LZP2), LZP2_RANGE[1])
ZP_SPAWN = R.allocate(LZPS, *LZPS_RANGE)


def constants() -> List[Tuple[str, int]]:
    out = [('LVG0', LVG0), ('LVG1', LVG1), ('LVG2', LVG2), ('LVC', LVC),
           ('LCODE', LCODE), ('GTAB', GTAB),
           ('LV_VARMAP', LV_VARMAP), ('LVCOUNT2', LVCOUNT2),
           ('LV_STATUS', LV_STATUS), ('LV_AMEM', LV_AMEM),
           ('STORE_DIR_BANK', STORE_DIR_BANK), ('STORE_DIR', STORE_DIR),
           ('STORE_DIR_HEAD', STORE_DIR_HEAD),
           ('STORE_DIR_MAPS', STORE_DIR_MAPS),
           ('LH_COUNTS', LH_COUNTS), ('LH_BLOCKS', LH_BLOCKS),
           ('LH_BLOCK', LH_BLOCK), ('LH_LVG1', LH_LVG1),
           ('LH_SIZE', LH_SIZE), ('LP_HEAD', LP_HEAD),
           ('LINEC_SIZE', LINEC_SIZE),
           ('LINE_BASE', LINES.base), ('LINE_SIZE', LINE_SIZE),
           ('LINE_CAP', LINES.capacity), ('SEC_CAP', R.SECTORS.capacity),
           ('SECG_BASE', SECGS.base), ('SECG_SIZE', SECG_SIZE),
           ('FLIDX_SIZE', FLIDX_SIZE),
           ('ML_TWOSIDED', ML_TWOSIDED), ('ML_SOUNDBLOCK', ML_SOUNDBLOCK),
           ('LVC_CMAPA', LVC_CMAPA), ('LVC_CMAPB', LVC_CMAPB),
           ('LVC_GSVIEW', LVC_GSVIEW), ('GSVIEW_A', GSVIEW_A),
           ('CMAP_PAGES', CMAP_SIZE // 256),
           ('GT_COLORMAP', GT['COLORMAP'][0]),
           ('LW_CODE', LW_CODE), ('LW_CODE_END', LW_CODE_END),
           ('LW_REQ', LW_REQ), ('REQ_HEAD', REQ_HEAD),
           ('LINE_ROOM', LINE_ROOM),
           ('LW_LFRONT', LW_LFRONT), ('LW_LBACK', LW_LBACK),
           ('LW_CNTLO', LW_CNTLO), ('LW_CNTHI', LW_CNTHI),
           ('LW_FSTLO', LW_FSTLO), ('LW_FSTHI', LW_FSTHI),
           ('LW_POSLO', LW_POSLO), ('LW_POSHI', LW_POSHI),
           ('LW_DNLO', LW_DNLO), ('LW_DNHI', LW_DNHI),
           ('LW_CMA', LW_CMA), ('LW_CMB', LW_CMB), ('LW_CMI', LW_CMI),
           ('LW_CMO', LW_CMO), ('LW_ZERO', LW_ZERO),
           ('LW_HDR', LW_HDR), ('LW_DIR', LW_DIR), ('LW_STEPS', LW_STEPS),
           ('LSTEP_MAX', LSTEP_MAX), ('LW_REQLO', LW_REQLO),
           ('LW_REQHI', LW_REQHI), ('LREQ_MAX', LREQ_MAX),
           ('LW_LR', LW_LR), ('LW_LC', LW_LC), ('LW_SR', LW_SR),
           ('LW_SUB', LW_SUB), ('LW_BE', LW_BE),
           ('NO_HANDLE', NO_HANDLE), ('DL_MAX', DL_MAX),
           ('AMEM_MAX', AMEM_MAX)]
    out += [('LHC_' + k.upper(), LH_COUNTS + 2 * i)
            for i, k in enumerate(HEADER_COUNTS)]
    out += [('LB_' + k, i) for i, k in enumerate(BLOCK_KINDS)]
    out += [('LHV_' + k, LH_LVG1 + 2 * i)
            for i, k in enumerate(('LTAB', 'FLIDX', 'FLENT', 'BLINKS'))]
    out += [('LST_' + k, v) for k, v in sorted(STEPS.items(),
                                                key=lambda x: x[1])]
    out += [('LS_' + k, v) for k, v in sorted(LS.items(), key=lambda x: x[1])]
    out += [('LN_' + k, v) for k, v in LINE.items()]
    out += [('LC_' + k, v) for k, v in LINEC.items()]
    out += [('SG_' + k, v) for k, v in SECG.items()]
    return out


def zeropage() -> List[Tuple[str, int]]:
    return sorted(ZP_LOAD1.items(), key=lambda x: x[1]) + \
        sorted(ZP_LOAD2.items(), key=lambda x: x[1])


def include_text() -> str:
    check()
    lines = ['; Generated by tools/native/llayout.py. Do not edit.', '']
    for name, value in constants():
        lines.append('%-16s= $%04X' % (name, value))
    lines.append('')
    lines.append('; zero page')
    for name, value in zeropage():
        lines.append('%-16s= $%02X' % (name, value))
    return '\n'.join(lines) + '\n'


def allowed_writes_load(counts: Dict[str, int], lvg1: Dict[str, int]
                        ) -> List[Tuple[str, int, int, int, str]]:
    """What the load's CPU code (the steps, the transport, the far layer
    it calls) may write in a load of a map with these counts and LVG1
    bases (docs/LEVELS.md 6.2: no stray write): storage, bank, [start,
    end), why. The memory API's copies are not CPU writes: the harness
    checks them against window.img."""
    nsec, nsub = counts['sectors'], counts['subsectors']
    out = [('main', 0, R.ZP_FAR[0], R.ZP_FAR[1], 'far layer arguments'),
           ('main', 0, LZP1_RANGE[0], LZP1_RANGE[1], 'the load\'s zero page'),
           ('main', 0, LZP2_RANGE[0], LZP2_RANGE[1], 'the load\'s zero page'),
           ('main', 0, LV_VARMAP, LV_VARMAP + 1, 'LV_VARMAP'),
           ('main', 0, LV_STATUS, LV_AMEM + 1, 'the stop code'),
           ('main', 0, LW_REQ, 0xC000, 'the load\'s W data'),
           ('aux', LVG0, LINES.base, LINES.address(counts['lines']),
            'LINES'),
           ('aux', LVG1, SECGS.base, lvg1['BLINKS'], 'GROUP, FLOOD'),
           ('aux', LVC, LVC_CMAPA, LVC_GSVIEW, 'CMAPS')]
    for i in range(nsub):
        a = R.SUBS.address(i) + R.SUB['SECTOR']
        out.append(('aux', LVMAP, a, a + 1, 'GROUP: subsector %d' % i))
    if nsec > R.SECTORS.capacity:
        raise ValueError('%d sectors' % nsec)
    return out


def main(argv: Sequence[str]) -> int:
    if len(argv) == 2 and argv[0] == '--game':
        Path(argv[1]).parent.mkdir(parents=True, exist_ok=True)
        Path(argv[1]).write_text(game_include_text())
        return 0
    if len(argv) != 1:
        print('usage: llayout.py OUT/llayout.inc | --game OUT/lgame.inc',
              file=sys.stderr)
        return 2
    Path(argv[0]).parent.mkdir(parents=True, exist_ok=True)
    Path(argv[0]).write_text(include_text())
    return 0


# ---------------------------------------------------------------------------
# native-level 1: the bridge manifest of the level's static kinds
# ---------------------------------------------------------------------------

def manifest_static() -> Dict:
    """A bridge-port-layout 1 manifest (tools/bridge/layout.py: records
    with a stride) of the static fields of the level window's records, as
    the load leaves them: segs, nodes, subsectors (their counts and first
    segs), lines, sides (offsets and textures), sectors (heights, pics,
    light from the render part; the sound origin, line count, tag and
    old special from the game part). The references (a side's and a
    subsector's sector as a byte, a sector's line table, the flood lists
    in their pool) need encodings of their own (docs/LEVELS.md 3.3: stage
    C); lderive.py and lstore.HostMachine check them meanwhile."""
    def planes(bank: int, base: int, offset: int, size: int) -> List[str]:
        return ['aux:%02X:%04X' % (bank, base + offset + k)
                for k in range(size)]

    def leaf(path, bank, base, stride, offset, size, signed):
        return {'path': list(path), 'enc': {'enc': 'int', 'bytes': size,
                                            'signed': signed},
                'planes': planes(bank, base, offset, size),
                'stride': stride}

    def count(at: int) -> List[str]:
        return ['main:%04X' % at, 'main:%04X' % (at + 1)]
    S, N, U = R.SEGS, R.NODES, R.SUBS
    seg = [leaf(('v1', 0), LVSEG, S.base, S.stride, 0, 2, True),
           leaf(('v1', 1), LVSEG, S.base, S.stride, 2, 2, True),
           leaf(('v2', 0), LVSEG, S.base, S.stride, 4, 2, True),
           leaf(('v2', 1), LVSEG, S.base, S.stride, 6, 2, True),
           leaf(('offset',), LVSEG, S.base, S.stride, 8, 2, True),
           leaf(('angle',), LVSEG, S.base, S.stride, 10, 2, False),
           leaf(('sidenum',), LVSEG, S.base, S.stride, 12, 2, True),
           leaf(('linenum',), LVSEG, S.base, S.stride, 14, 2, True),
           leaf(('frontsectornum',), LVSEG, S.base, S.stride, 16, 1, False),
           leaf(('backsectornum',), LVSEG, S.base, S.stride, 17, 1, False)]
    node = [leaf((k,), LVMAP, N.base, N.stride, 2 * i, 2, True)
            for i, k in enumerate(('x', 'y', 'dx', 'dy'))]
    node += [leaf(('bbox', i), LVMAP, N.base, N.stride, 8 + 2 * i, 2, True)
             for i in range(8)]
    node += [leaf(('children', i), LVMAP, N.base, N.stride, 24 + 2 * i, 2,
                  False) for i in range(2)]
    sub = [leaf(('numlines',), LVMAP, U.base, U.stride, 1, 1, False),
           leaf(('firstline',), LVMAP, U.base, U.stride, 2, 2, False)]
    L = LINE
    line = [leaf(('v1', 0), LVG0, LINES.base, LINE_SIZE, L['V1X'], 2, True),
            leaf(('v1', 1), LVG0, LINES.base, LINE_SIZE, L['V1Y'], 2, True),
            leaf(('v2', 0), LVG0, LINES.base, LINE_SIZE, L['V2X'], 2, True),
            leaf(('v2', 1), LVG0, LINES.base, LINE_SIZE, L['V2Y'], 2, True),
            leaf(('dx',), LVG0, LINES.base, LINE_SIZE, L['DX'], 2, True),
            leaf(('dy',), LVG0, LINES.base, LINE_SIZE, L['DY'], 2, True),
            leaf(('sidenum', 0), LVG0, LINES.base, LINE_SIZE, L['SIDE0'], 2,
                 True),
            leaf(('sidenum', 1), LVG0, LINES.base, LINE_SIZE, L['SIDE1'], 2,
                 True)]
    line += [leaf(('bbox', i), LVG0, LINES.base, LINE_SIZE, L[k], 2, True)
             for i, k in enumerate(('TOP', 'BOTTOM', 'LEFT', 'RIGHT'))]
    line += [leaf(('tag',), LVG0, LINES.base, LINE_SIZE, L['TAG'], 1, True),
             leaf(('special',), LVG0, LINES.base, LINE_SIZE, L['SPECIAL'],
                  1, True),
             leaf(('flags',), LVG0, LINES.base, LINE_SIZE, L['FLAGS'], 1,
                  False),
             leaf(('slopetype',), LVG0, LINES.base, LINE_SIZE, L['SLOPE'],
                  1, False)]
    D, E = R.SIDES, R.SECTORS
    side = [leaf(('textureoffset',), LVMAP, D.base, D.stride, 0, 2, True),
            leaf(('rowoffset',), LVMAP, D.base, D.stride, 2, 2, True),
            leaf(('toptexture',), LVMAP, D.base, D.stride, R.SIDE['TOP'], 1,
                 False),
            leaf(('bottomtexture',), LVMAP, D.base, D.stride,
                 R.SIDE['BOTTOM'], 1, False),
            leaf(('midtexture',), LVMAP, D.base, D.stride, R.SIDE['MID'], 1,
                 False)]
    G = SECG
    sector = [leaf(('floorheight',), LVMAP, E.base, E.stride, 0, 4, True),
              leaf(('ceilingheight',), LVMAP, E.base, E.stride, 4, 4, True),
              leaf(('floorpic',), LVMAP, E.base, E.stride, R.SEC['FPIC'], 1,
                   True),
              leaf(('ceilingpic',), LVMAP, E.base, E.stride, R.SEC['CPIC'],
                   1, True),
              leaf(('lightlevel',), LVMAP, E.base, E.stride,
                   R.SEC['LIGHT'], 1, False),
              leaf(('soundorg', 0), LVG1, SECGS.base, SECG_SIZE,
                   G['SOUNDX'], 4, True),
              leaf(('soundorg', 1), LVG1, SECGS.base, SECG_SIZE,
                   G['SOUNDY'], 4, True),
              leaf(('linecount',), LVG1, SECGS.base, SECG_SIZE, G['LCOUNT'],
                   2, True),
              leaf(('oldspecial',), LVG1, SECGS.base, SECG_SIZE,
                   G['OLDSPECIAL'], 1, True),
              leaf(('tag',), LVG1, SECGS.base, SECG_SIZE, G['TAG'], 2,
                   True)]
    kinds = {
        'seg': {'capacity': S.capacity, 'count': count(LVCOUNT2 + 4),
                'leaves': seg},
        'node': {'capacity': N.capacity, 'count': count(LVCOUNT2 + 6),
                 'leaves': node},
        'subsector': {'capacity': U.capacity, 'count': count(LVCOUNT2 + 2),
                      'leaves': sub},
        'line': {'capacity': LINES.capacity, 'count': count(LVCOUNT2),
                 'leaves': line},
        'side': {'capacity': D.capacity, 'count': count(R.LVCOUNT + 2),
                 'leaves': side},
        'sector': {'capacity': E.capacity, 'count': count(R.LVCOUNT),
                   'leaves': sector},
    }
    return {'format': 'bridge-port-layout 1', 'name': 'native-level-1',
            'note': 'the static fields of the native level window '
                    '(tools/native/llayout.py; milestone 9 stage A)',
            'symbols': [], 'tables': [], 'lists': {}, 'pools': {},
            'kinds': kinds, 'globals': {'leaves': []}}



# ---------------------------------------------------------------------------
# Stage C: native-level 1 whole (docs/LEVELS.md 3.2, 3.3): every canonical
# object and global the setup leaves, per map
# ---------------------------------------------------------------------------

def _schema():
    """The bridge's schema (needs build/linkmap.json and upstream's
    includes)."""
    from bridge import upstream
    return upstream.Schema()


def _hex_planes(storage: str, bank: int, address: int, n: int) -> List[str]:
    if storage == 'main':
        return ['main:%04X' % (address + k) for k in range(n)]
    return ['aux:%02X:%04X' % (bank, address + k) for k in range(n)]


def _int(size: int, signed: bool) -> Dict[str, Any]:
    return {'enc': 'int', 'bytes': size, 'signed': signed}


def handle(ranges: List[Dict[str, Any]], size: int = 2) -> Dict[str, Any]:
    return {'enc': 'handle', 'bytes': size, 'ranges': ranges}


def _width(enc: Dict[str, Any]) -> int:
    from bridge.layout import Leaf
    return Leaf((), enc).width


def native_struct(st, refenc, path: Tuple = ()) -> List[Tuple[Tuple,
                                                              Dict, int]]:
    """A structure of upstream laid out natively in its field order: (path,
    encoding, offset) of each leaf; numbers and raw bytes at their size,
    references as refenc(path, Ref) gives them, excluded fields left out.
    The offsets of an all-number structure are upstream's."""
    from bridge.fields import Array, Int, Raw, Ref, Sub
    out: List[Tuple[Tuple, Dict, int]] = []

    def walk(t, p, at: int) -> int:
        if isinstance(t, Int):
            out.append((p, _int(t.size, t.signed), at))
            return at + t.size
        if isinstance(t, Raw):
            out.append((p, {'enc': 'raw', 'bytes': t.size}, at))
            return at + t.size
        if isinstance(t, Ref):
            enc = refenc(p, t)
            out.append((p, enc, at))
            return at + _width(enc)
        if isinstance(t, Array):
            for i in range(t.count):
                at = walk(t.elem, p + (i,), at)
            return at
        if isinstance(t, Sub):
            for f in t.struct.fields:
                if f.cls == 'excluded':
                    continue
                at = walk(f.type, p + (f.name,), at)
            return at
        raise TypeError(t)
    walk(Sub(st), path, 0)
    return out


def _ref_any(codes: List[str]) -> Dict[str, Any]:
    from bridge import schema
    return {'enc': 'ref', 'codes': [[k, None] for k in codes],
            'offset': any(k in schema.BYTE_KINDS for k in codes)}


def mobj_ranges(poolsize: int) -> List[Dict[str, Any]]:
    return [{'lo': 0, 'n': poolsize, 'kind': 'mobj'},
            {'lo': poolsize, 'n': MOBJ_CAP - poolsize, 'kind': 'zmobj'}]


def special_ranges() -> List[Dict[str, Any]]:
    return [{'lo': SPEC_HANDLE + lo, 'n': n, 'kind': k}
            for k, (lo, n) in SPEC_RANGE.items()]


STATE_RANGE = [{'lo': 0, 'n': NUMSTATES, 'kind': 'state'}]
SECTOR_RANGE = [{'lo': 0, 'n': R.SECTORS.capacity, 'kind': 'sector'}]
SECNODE_RANGE = [{'lo': 0, 'n': SN_CAP, 'kind': 'secnode'}]


def player_layout(poolsize: int = 1) -> List[Tuple[Tuple, Dict, int]]:
    """The player's native record (G_PLAYER): upstream's fields in order,
    the mobj references as mobj handles, the psprites' states as state
    numbers, the message as a reference to a symbol."""
    sch = _schema()

    def refenc(path, t):
        if set(t.targets) <= {'mobj', 'zmobj'}:
            return handle(mobj_ranges(poolsize))
        if t.targets == ('state',):
            return handle(STATE_RANGE)
        return _ref_any(list(t.targets))
    return native_struct(sch.structs['PL'], refenc)


def button_layout(nlines: int = 1) -> List[Tuple[Tuple, Dict, int]]:
    sch = _schema()

    def refenc(path, t):
        if t.targets == ('line',):
            return handle([{'lo': 0, 'n': nlines, 'kind': 'line'}])
        if t.targets == ('sector',):
            return handle([{'lo': 0, 'n': R.SECTORS.capacity,
                            'kind': 'sector', 'field': 'soundorg'}], 1)
        raise ValueError('a button\'s %s' % (t,))
    return native_struct(sch.structs['BTN'], refenc)


def _size_of(layout: List[Tuple[Tuple, Dict, int]]) -> int:
    return max(at + _width(enc) for _, enc, at in layout)


def offset_names(prefix: str, layout) -> List[Tuple[str, int]]:
    """PL_MO, PL_PSPRITES_0_STATE, ...: each leaf's offset by its path."""
    return [(prefix + '_'.join(str(x) for x in path).upper(), at)
            for path, _, at in layout]


def manifest(header: Dict[str, Any], symbols: Sequence[str] = ()
             ) -> Dict[str, Any]:
    """native-level 1 for a loaded and set-up map with this store header
    (store.json's): a bridge-port-layout 1 manifest of every canonical
    object and global the native layout holds. The caches the native
    layout does not keep (NOT_KEPT, NOT_KEPT_FIELDS) have no leaf."""
    from bridge import schema
    sch = _schema()
    c = header['counts']
    v = header['lvg1']
    pool = c['things']
    nlines, nsides, nsubs = c['lines'], c['sides'], c['subsectors']
    kinds: Dict[str, Any] = {}

    def L(path, enc, storage, bank, address, stride=1, when=None,
          planes=None):
        n = _width(enc)
        out = {'path': list(path), 'enc': enc,
               'planes': planes if planes is not None else
               _hex_planes(storage, bank, address, n)}
        if stride != 1:
            out['stride'] = stride
        if when:
            out['when'] = list(when)
        return out

    def count(address: int) -> List[str]:
        return ['main:%04X' % address, 'main:%04X' % (address + 1)]
    mref = handle(mobj_ranges(pool))
    thref = handle(mobj_ranges(pool) + special_ranges())
    spref = handle(special_ranges())
    sec1 = handle(SECTOR_RANGE, 1)
    node2 = handle(SECNODE_RANGE)
    line2 = handle([{'lo': 0, 'n': nlines, 'kind': 'line'}])

    def lst(name, ranges):
        return {'enc': 'list', 'list': name, 'bytes': 2, 'ranges': ranges}
    # -- the static kinds of stage B, with their references
    st = manifest_static()['kinds']
    for k in ('seg', 'node'):
        kinds[k] = st[k]
    U, E, D = R.SUBS, R.SECTORS, R.SIDES
    kinds['subsector'] = st['subsector']
    kinds['subsector']['leaves'].append(L(
        ('sector',), sec1, 'aux', R.LVMAP, U.base + R.SUB['SECTOR'],
        U.stride))
    kinds['side'] = st['side']
    kinds['side']['leaves'].append(L(
        ('sector',), sec1, 'aux', R.LVMAP, D.base + R.SIDE['SECTOR'],
        D.stride))
    LN = LINE
    line = [x for x in st['line']['leaves']
            if x['path'] not in (['tag'], ['special'])]
    line += [L(('tag',), {'enc': 'sxbyte'}, 'aux', LVG0,
               LINES.base + LN['TAG'], LINE_SIZE),
             L(('special',), {'enc': 'sxbyte'}, 'aux', LVG0,
               LINES.base + LN['SPECIAL'], LINE_SIZE),
             L(('validcount',), _int(2, False), 'aux', LVG0,
               LINES.base + LN['VALID'], LINE_SIZE),
             L(('r_validcount',), _int(2, False), 'aux', LVG0,
               LINES.base + LN['RVALID'], LINE_SIZE),
             L(('r_flags',), {'enc': 'bit',
                              'value': sch.c['CONST_ML_MAPPED']},
               'main', 0, LNMAP)]
    kinds['line'] = dict(st['line'], leaves=line)
    G2 = SECG
    sector = [x for x in st['sector']['leaves']
              if x['path'] not in (['oldspecial'],)]
    sector += [
        L(('validcount',), _int(2, False), 'aux', R.LVMAP,
          E.base + R.SEC['VALID'], E.stride),
        L(('thinglist',), lst('sector_things', mobj_ranges(pool)), 'aux',
          R.LVMAP, E.base + R.SEC['THINGS'], E.stride),
        L(('soundtarget',), mref, 'aux', LVG1, SECGS.base + G2['TARGET'],
          SECG_SIZE),
        L(('lines',), handle([{'lo': 0, 'n': max(c['linetable'], 1),
                                'kind': 'linebuf'}]), 'aux', LVG1,
          SECGS.base + G2['LFIRST'], SECG_SIZE),
        L(('floordata',), spref, 'aux', LVG1, SECGS.base + G2['FLOORD'],
          SECG_SIZE),
        L(('ceilingdata',), spref, 'aux', LVG1, SECGS.base + G2['CEILD'],
          SECG_SIZE),
        L(('touching_thinglist',), lst('sector_nodes', SECNODE_RANGE),
          'aux', LVG1, SECGS.base + G2['TOUCH'], SECG_SIZE),
        L(('special',), {'enc': 'sxbyte'}, 'aux', LVG1,
          SECGS.base + G2['SPECIAL'], SECG_SIZE),
        L(('oldspecial',), {'enc': 'sxbyte'}, 'aux', LVG1,
          SECGS.base + G2['OLDSPECIAL'], SECG_SIZE),
        L(('soundtraversed',), _int(1, True), 'aux', LVG1,
          SECGS.base + G2['TRAVERSED'], SECG_SIZE),
        L(('flood',), {'enc': 'seq', 'pool': 'flood', 'form': 'end'}, 'aux',
          LVG1, v['FLIDX'], FLIDX_SIZE),
        L(('flood_sb',), {'enc': 'seq', 'pool': 'flood', 'form': 'end'},
          'aux', LVG1, v['FLIDX'] + 4, FLIDX_SIZE)]
    kinds['sector'] = dict(st['sector'], leaves=sector)
    kinds['blocklink'] = {
        'capacity': 0x10000, 'count': count(G['G_BLOCKS']),
        'leaves': [L(('things',), lst('block_things', mobj_ranges(pool)),
                     'aux', LVG1, v['BLINKS'], 2)]}
    kinds['linebuf'] = {
        'capacity': 0x10000, 'count': count(G['G_LTABN']),
        'leaves': [L(('line',), line2, 'aux', LVG1, v['LTAB'], 2)]}
    for kind, length, lump, base in (
            ('blockmap', 'G_BMLEN', 'G_BMLUMP', BLOCKMAP),
            ('reject', 'G_REJLEN', 'G_REJLUMP', header['reject'])):
        kinds[kind] = {'capacity': 1, 'count': 1, 'leaves': [
            {'path': ['bytes'], 'enc': {'enc': 'blob', 'max': ROOM_BYTES},
             'planes': ['main:%04X' % G[length],
                        'main:%04X' % (G[length] + 1),
                        'aux:%02X:%04X' % (LVG2, base)]},
            L(('lump',), _int(2, False), 'main', 0, G[lump])]}
    # -- the mobjs: RTHING and the three game parts, by slot
    T = R.RTHING
    RB = R.RTHINGS.base

    def mobj_leaves(first: int, pooled: bool) -> List[Dict[str, Any]]:
        b = RB + MO_SIZE * first

        def plane(*bases: int) -> List[str]:
            return ['aux:%02X:%04X' % (MOBJP, a + first) for a in bases]
        out = [
            L(('function',), {'enc': 'enum', 'values': list(FUNCS),
                              'mask': 0xFF ^ KIND_CLEAN}, 'aux', MOBJP, 0,
              planes=plane(PL_KIND)),
            L(('x',), _int(4, True), 'aux', R.RTH, b + T['X'], MO_SIZE),
            L(('y',), _int(4, True), 'aux', R.RTH, b + T['Y'], MO_SIZE),
            L(('z',), _int(4, True), 'aux', R.RTH, b + T['Z'], MO_SIZE),
            L(('angle',), _int(4, False), 'aux', R.RTH, b, MO_SIZE, planes=[
                'aux:%02X:%04X' % (R.RTH, b + a) for a in
                (TH_ANGLO, TH_ANGLO + 1, T['ANG'], T['ANG'] + 1)]),
            L(('sprite',), _int(1, False), 'aux', R.RTH, b + T['SPR'],
              MO_SIZE),
            L(('frame',), _int(2, True), 'aux', R.RTH, b + T['FRAME'],
              MO_SIZE),
            L(('subsector',), handle([{'lo': 0, 'n': nsubs,
                                       'kind': 'subsector'}]), 'aux',
              MOBJA, b + MA['SUBSEC'], MO_SIZE)]
        for name, k in (('floorz', 'FLOORZ'), ('ceilingz', 'CEILZ'),
                        ('dropoffz', 'DROPZ'), ('radius', 'RADIUS'),
                        ('height', 'HEIGHT')):
            out.append(L((name,), _int(4, True), 'aux', MOBJB, b + MB[k],
                         MO_SIZE))
        for name, k in (('momx', 'MOMX'), ('momy', 'MOMY'),
                        ('momz', 'MOMZ')):
            out.append(L((name,), _int(4, True), 'aux', MOBJC, b + MC[k],
                         MO_SIZE))
        out += [
            L(('health',), _int(2, True), 'aux', MOBJA, b + MA['HEALTH'],
              MO_SIZE),
            L(('type',), _int(1, False), 'aux', MOBJA, b + MA['TYPE'],
              MO_SIZE),
            L(('tics',), {'enc': 'sxbyte'}, 'aux', MOBJP, 0,
              planes=plane(PL_TICS)),
            L(('state',), handle(STATE_RANGE), 'aux', MOBJA,
              b + MA['STATE'], MO_SIZE),
            L(('flags',), _int(4, False), 'aux', MOBJB, b + MB['FLAGS'],
              MO_SIZE),
            L(('target',), mref, 'aux', MOBJA, b + MA['TARGET'], MO_SIZE),
            L(('movedir',), _int(1, False), 'aux', MOBJC,
              b + MC['MOVEDIR'], MO_SIZE),
            L(('threshold',), _int(1, False), 'aux', MOBJC,
              b + MC['THRESH'], MO_SIZE),
            L(('pursuecount',), _int(2, True), 'aux', MOBJC,
              b + MC['PURSUE'], MO_SIZE),
            L(('movecount',), _int(2, True), 'aux', MOBJC,
              b + MC['MOVEC'], MO_SIZE),
            L(('reactiontime',), _int(2, True), 'aux', MOBJC,
              b + MC['REACT'], MO_SIZE),
            L(('lastenemy',), mref, 'aux', MOBJC, b + MC['LASTEN'],
              MO_SIZE),
            L(('sightline',), _int(2, False), 'aux', MOBJC, b + MC['SIGHT'],
              MO_SIZE),
            L(('touching_sectorlist',), lst('thing_nodes', SECNODE_RANGE),
              'aux', MOBJA, b + MA['TOUCH'], MO_SIZE,
              when=('free', 0) if pooled else None),
            L(('@thinkers.next',), thref, 'aux', MOBJP, 0,
              planes=plane(PL_TNL, PL_TNH)),
            L(('@thinkers.prev',), thref, 'aux', MOBJA, b + MA['THPREV'],
              MO_SIZE),
            L(('@sector_things.next',), mref, 'aux', R.RTH,
              b + T['SNEXT'], MO_SIZE),
            L(('@sector_things.prev',), mref, 'aux', MOBJA,
              b + MA['SPREV'], MO_SIZE),
            L(('@block_things.next',), mref, 'aux', MOBJA, b + MA['BNEXT'],
              MO_SIZE),
            L(('@block_things.prev',), mref, 'aux', MOBJA, b + MA['BPREV'],
              MO_SIZE)]
        if pooled:
            out.append(L(('free',), {'enc': 'bit', 'value': 1}, 'main', 0,
                         G['G_TPBITS']))
        return out
    kinds['mobj'] = {'capacity': POOL_MAX, 'count': count(G['G_POOLN']),
                     'leaves': mobj_leaves(0, True)}
    kinds['zmobj'] = {'capacity': MOBJ_CAP - pool,
                      'count': count(G['G_ZMN']),
                      'leaves': mobj_leaves(pool, False),
                      # a zone slot on G_ZMFREE's list is no object
                      'select': {'path': ['function'],
                                 'not': [FN_FREE_NAME]}}
    # -- the sector nodes
    S = SNODES.base
    free0 = ('free', 0)
    kinds['secnode'] = {'capacity': SN_CAP, 'count': count(G['G_SNHWM']),
                        'leaves': [
        L(('m_sector',), sec1, 'aux', ZONE1, S + SN['SECTOR'], SN_SIZE,
          when=free0),
        L(('m_thing',), mref, 'aux', ZONE1, S + SN['THING'], SN_SIZE,
          when=free0),
        L(('visited',), _int(2, True), 'aux', ZONE1, S + SN['VISITED'],
          SN_SIZE, when=free0),
        L(('free',), _int(1, False), 'aux', ZONE1, S + SN['FREE'],
          SN_SIZE)] + [
        L(('@%s.%s' % (name, d),), node2, 'aux', ZONE1, S + SN[f], SN_SIZE)
        for name, d, f in (('thing_nodes', 'next', 'TNEXT'),
                           ('thing_nodes', 'prev', 'TPREV'),
                           ('sector_nodes', 'next', 'SNEXT'),
                           ('sector_nodes', 'prev', 'SPREV'),
                           ('sector_list', 'next', 'TNEXT'),
                           ('sector_list', 'prev', 'TPREV'),
                           ('sn_free', 'next', 'TNEXT'))]}
    # -- the specials, a range of slots a kind
    types = {'lightflash': 'LIGHTFLASH', 'strobe': 'STROBE', 'glow': 'GLOW',
             'scroll': 'SCROLL', 'plat': 'PLAT', 'door': 'DOOR',
             'floor': 'FLOOR'}
    for k, (lo, n) in SPEC_RANGE.items():
        b = SPECS.base + SPEC_SIZE * lo
        st_ = sch.structs[types[k]]
        leaves = [L(('function',), {'enc': 'enum', 'values': list(FUNCS)},
                    'aux', ZONE0, b + SP['FUNC'], SPEC_SIZE),
                  L(('@thinkers.next',), thref, 'aux', ZONE0,
                    b + SP['THNEXT'], SPEC_SIZE),
                  L(('@thinkers.prev',), thref, 'aux', ZONE0,
                    b + SP['THPREV'], SPEC_SIZE)]
        offs = dict(SP_KIND[k], SECTOR=SP['SECTOR'])
        for f in st_.fields:
            if f.cls == 'thinker':
                continue
            at = b + offs[f.name.upper().replace('TEXTUREOFFSET', 'SIDE')]
            t_ = f.type
            from bridge.fields import Int, Ref
            if isinstance(t_, Int):
                enc = _int(t_.size, t_.signed)
            elif isinstance(t_, Ref) and t_.targets == ('sector',):
                enc = sec1
            elif isinstance(t_, Ref) and t_.targets == ('side',):
                enc = handle([{'lo': 0, 'n': nsides, 'kind': 'side',
                               'field': 'textureoffset'}])
            elif isinstance(t_, Ref) and t_.targets == ('line',):
                enc = line2
            elif isinstance(t_, Ref) and t_.targets == ('',):
                enc = handle([], 1)
            else:
                raise ValueError('%s.%s: %r' % (k, f.name, t_))
            leaves.append(L((f.name,), enc, 'aux', ZONE0, at, SPEC_SIZE))
        kinds[k] = {'capacity': n,
                    'count': count(G['G_SPN'] + 2 * list(SPEC_RANGE).index(
                        k)),
                    'leaves': leaves,
                    # a slot is an object of the kind while its function is
                    # the kind's: a free slot (on G_SPFREE's list) has
                    # none, a special waiting for its removal is "removed"
                    'select': {'path': ['function'],
                               'in': [FUNCS[FN[SPEC_FN[k]]]]}}
    # -- the player and the buttons
    pl = player_layout(pool)
    kinds['player'] = {'capacity': 1, 'count': 1, 'leaves': [
        L(path, enc, 'main', 0, G['G_PLAYER'] + at) for path, enc, at in pl]}
    bl = button_layout(nlines)
    bsize = _size_of(bl)
    kinds['button'] = {'capacity': sch.c['CONST_MAXBUTTONS'],
                       'count': sch.c['CONST_MAXBUTTONS'], 'leaves': [
        L(path, enc, 'main', 0, G['G_BUTTONS'] + at, bsize)
        for path, enc, at in bl]}
    # -- the globals
    gl: List[Dict[str, Any]] = []
    counts_at = {'p_setup65.s:_g_numsectors': R.LVCOUNT,
                 'p_setup65.s:numsides': R.LVCOUNT + 2,
                 'p_setup65.s:_g_numlines': LVCOUNT2,
                 'p_setup65.s:numsubsectors': LVCOUNT2 + 2,
                 'p_setup65.s:numnodes': LVCOUNT2 + 6}
    gtab_at = {'p_switch65.s:switchlist': GT['SWITCHLIST'][0],
               'p_switch65.s:SW_IDX': GT['SW_IDX'][0],
               'p_spec65.s:animated_texture_basepic': GT['BASEPIC'][0]}
    lists = {'p_think65.s:_g_thinkerclasscap': ('thinkers', thref),
             'p_map65.s:_s_sector_list': ('sector_list', node2),
             'p_map65.s:SN_FREE': ('sn_free', node2)}
    for unit, labels in list(schema.GLOBALS.items()) + list(
            schema.EXTERNAL_GLOBALS.items()):
        for label, text in labels.items():
            name = '%s:%s' % (unit, label)
            if name in NOT_KEPT or text.startswith('object:'):
                continue
            if text.startswith('cache:'):
                text = text[6:]
            if name in ('p_sight65.s:CS_PREV1', 'p_sight65.s:CS_PREV2'):
                gl.append(L((name,), dict(mref, stale=STALE), 'main', 0,
                            gplace(GLOBAL_PLACE[name])))
                continue
            if name in ('p_sight65.s:CS_PREVR', 'p_map65.s:LR_OK',
                        'p_map65.s:LR_USE', 'p_map65.s:LR_N'):
                gl.append(L((name,), _int(1, False), 'main', 0,
                            gplace(GLOBAL_PLACE[name])))
                continue
            if name == 'p_map65.s:LR_LINES':
                for i in range(24):
                    gl.append(L((name, i), _int(2, False), 'main', 0,
                                G['G_LRLINES'] + 2 * i))
                continue
            if text.startswith('table:'):
                gl.append({'path': [name], 'enc': {'enc': 'table',
                                                   'kind': text[6:]},
                           'planes': []})
                continue
            if name in lists:
                lname, enc = lists[name]
                gl.append(L((name,), dict(enc, enc='list', list=lname),
                            'main', 0, gplace(GLOBAL_PLACE[name])))
                continue
            if name == 'm_random65.s:prndindex':
                gl.append(L((name,), _int(1, False), 'main', 0, PRND))
                continue
            if name == 'm_random65.s:rndindex':
                gl.append(L((name,), _int(1, False), 'main', 0, MRND))
                continue
            if name in counts_at:
                gl.append(L((name,), _int(2, False), 'main', 0,
                            counts_at[name]))
                continue
            t_ = sch.structs[text] if text in sch.structs else \
                schema.field_type(text, sch.structs)
            if name in gtab_at:
                for path, enc, at in native_struct_type(t_, (name,)):
                    gl.append(L(path, enc, 'aux', GTAB, gtab_at[name] + at))
                continue
            if name == 'p_setup65.s:_g_blockmap':
                enc = handle([{'lo': BLOCKMAP, 'n': ROOM[1] - BLOCKMAP,
                               'kind': 'blockmap', 'id': 0}])
            elif name == 'p_sight65.s:LOGP':
                enc = handle([{'lo': 0, 'n': 1, 'kind': 'table',
                               'id': 'MM_LOGTAB'}])
            elif name == 'p_map65.s:_g_ceilingline':
                enc = line2
            else:
                enc = None
            place = gplace(GLOBAL_PLACE[name])
            if enc is not None:
                gl.append(L((name,), enc, 'main', 0, place))
                continue
            for path, enc2, at in native_struct_type(
                    t_, (name,), refenc=lambda p_, r_: _ref_any(
                        list(r_.targets))):
                gl.append(L(path, enc2, 'main', 0, place + at))
    symbol_list = list(symbols)
    lists_json = {name: {'elements': list(d.elements),
                         'prev': d.prev is not None}
                  for name, d in schema.LISTS.items()}
    return {'format': 'bridge-port-layout 1', 'name': 'native-level-1',
            'note': 'the native level window and game state of E1M%d after '
                    'nl_setup (tools/native/llayout.py; milestone 9 '
                    'stage C, the final layouts of milestone 10\'s '
                    'skeleton)' % header['map'],
            # a special waiting for its removal (function
            # P_RemoveThinkerDelayed) stays in its kind's slot: the reader
            # gives it the kind "removed"; the writer puts a removed
            # special after the home kind's objects
            'removed': {'function': FUNCS[FN['REMOVETHINKER']],
                        'kinds': list(SPEC_RANGE), 'home': 'scroll'},
            'symbols': symbol_list, 'tables': [], 'lists': lists_json,
            'pools': {'flood': {
                'capacity': max(c['flood'], 1),
                'codes': [['sector', None]], 'enc': sec1,
                'planes': ['aux:%02X:%04X' % (LVG1, v['FLENT'])],
                'count': []}},
            'kinds': kinds, 'globals': {'leaves': gl}}


def native_struct_type(t, path: Tuple, refenc=None) -> List[Tuple]:
    """native_struct for any type (a structure, an array or a number)."""
    from bridge.fields import Sub
    from bridge.fields import Struct as BStruct
    from bridge.fields import Field as BField
    if isinstance(t, Sub):
        return native_struct(t.struct, refenc, path)
    if isinstance(t, BStruct):
        return native_struct(t, refenc, path)
    wrapper = BStruct('wrap', t.length, [BField('x', 0, t)])
    out = native_struct(wrapper, refenc, ())
    return [(path + p[1:], enc, at) for p, enc, at in out]


def gplace(name: str) -> int:
    """A game global's main address (G_VALID: the frame block's
    VALIDCOUNT)."""
    return G_VALID if name == 'G_VALID' else G[name]


def symbol_list() -> List[str]:
    """The labelled constants a reference to a symbol can name (the
    manifest's "symbols", as native_v1's)."""
    from bridge.linkmap import Symbols
    sym = Symbols()
    return sorted(lb.ref for f in sym.fragments if f.kind == 'rodata'
                  for lb in f.labels)


def allowed_writes_setup(header: Dict[str, Any]
                         ) -> List[Tuple[str, int, int, int, str]]:
    """What nl_setup's CPU code may write (the load's, allowed_writes_load,
    and the setup's): storage, bank, [start, end), why."""
    c = header['counts']
    v = header['lvg1']
    out = list(allowed_writes_load(c, v))
    out += [('main', 0, LZPG_RANGE[0], LZPG_RANGE[1], 'the game core\'s ZP'),
            ('main', 0, MATH_ZP[0], MATH_ZP[1], 'the math\'s block'),
            ('main', 0, GBLOCK, GLOBALS_END, 'the game globals'),
            ('main', 0, LNMAP, LNMAP_END, 'LNMAP (r_flags)'),
            ('main', 0, PRND, PRND + 1, 'P_Random\'s index'),
            # milestone 10: validcount (the frame block's), the object
            # API's caches and state, the planes, LVS (GTABS)
            ('main', 0, G_VALID, G_VALID + 2, 'validcount'),
            ('main', 0, MOC, MOC + MOC_LINES * MOC_LINE, 'the mobj cache'),
            ('main', 0, SCC, SCC + SCC_LINES * SCC_LINE,
             'the sector cache'),
            ('main', 0, RT_STATE, RT_END, 'the runtime\'s state'),
            ('main', 0, BL_BUF, BL_BUF + 0x100, 'bl_get\'s buffer'),
            ('aux', MOBJP, PL_TNL, PL_TICS + PLANE_SLOTS, 'the planes'),
            ('aux', LVS, LVS_LNSECF, LVS_END, 'GTABS')]
    for bank in (R.RTH,) + MOBJ_BANKS:
        out.append(('aux', bank, R.RTHINGS.base, R.RTHINGS.end,
                    'the mobjs'))
    nb = c['blocks']
    out += [('aux', LVG1, v['BLINKS'], v['BLINKS'] + 2 * nb, 'the blocks\' '
             'thing lists'),
            ('aux', ZONE0, SPECS.base, SPECS.end, 'the specials'),
            ('aux', ZONE1, SNODES.base, SNODES.end, 'the sector nodes')]
    # (milestone 10: the object API writes a sector's render record back
    # whole, the values it did not change included)
    out.append(('aux', R.LVMAP, R.SECTORS.base,
                R.SECTORS.address(c['sectors'] - 1) + R.SEC_SIZE,
                'the sectors\' render records (the object API\'s '
                'write-backs)'))
    for i in range(c['lines']):
        a = LINES.address(i) + LINE['VALID']
        out.append(('aux', LVG0, a, a + 2, 'line %d\'s stamp' % i))
    return out


def game_constants() -> List[Tuple[str, int]]:
    """lgame.inc's values: stage C's layout and the facts of upstream the
    game core takes (offsets.inc, info.inc, the source files' .equ through
    the link map; the weapons' and the ammunition's tables from the
    release)."""
    from native import umodel as U
    sch = _schema()
    c = sch.c
    out: List[Tuple[str, int]] = [
        ('MOBJA', MOBJA), ('MOBJB', MOBJB), ('MOBJC', MOBJC),
        ('ZONE0', ZONE0), ('ZONE1', ZONE1), ('PRE_BANK', PRE_BANK),
        ('MO_SIZE', MO_SIZE), ('MOBJ_CAP', MOBJ_CAP),
        ('POOL_MAX', POOL_MAX), ('TH_ANGLO', TH_ANGLO),
        ('SPEC_SIZE', SPEC_SIZE), ('SPEC_HANDLE', SPEC_HANDLE),
        ('SPEC_BASE', SPECS.base), ('SN_SIZE', SN_SIZE), ('SN_CAP', SN_CAP),
        ('SN_POOL', SN_POOL), ('SN_BASE', SNODES.base),
        ('GBLOCK', GBLOCK), ('GLOBALS_END', GLOBALS_END),
        ('LNMAP_END', LNMAP_END), ('PRE_RECORD', PRE_RECORD),
        ('PRE_RND', PRE_RND),
        ('LH_LUMPS', LH_LUMPS),
        ('LH_BLOCKMAP', LH_BLOCKMAP), ('LH_REJECT', LH_REJECT),
        ('BLOCKMAP_AT', BLOCKMAP),
        ('LW_MOB', LW_MOB), ('LW_MINFO', LW_MINFO), ('LW_STATE', LW_STATE),
        ('LW_NODEB', LW_NODEB), ('LW_MT', LW_MT),
        ('LW_SREC', LW_SREC), ('LW_SPEC', LW_SPEC), ('LW_SN', LW_SN),
        ('LW_LINEB', LW_LINEB),
        # milestone 10: the final layouts' and the object API's places
        ('MOBJP', MOBJP), ('LVS', LVS), ('PLANE_SLOTS', PLANE_SLOTS),
        ('PL_TNL', PL_TNL), ('PL_TNH', PL_TNH), ('PL_KIND', PL_KIND),
        ('PL_TICS', PL_TICS), ('PL_HINTL', PL_HINTL), ('PL_HINTH', PL_HINTH),
        ('KIND_CLEAN', KIND_CLEAN), ('LVS_LNSECF', LVS_LNSECF),
        ('LVS_LNSECB', LVS_LNSECB), ('LVS_RJROW', LVS_RJROW),
        ('MOC', MOC), ('MOC_LINES', MOC_LINES), ('MOC_LINE', MOC_LINE),
        ('SCC', SCC), ('SCC_LINES', SCC_LINES), ('SCC_LINE', SCC_LINE),
        ('LNC', GWA['LNC']), ('LNC_LINES', LNC_LINES),
        ('LNC_LINE', LNC_LINE), ('SPC', GWA['SPC']),
        ('SPC_LINES', SPC_LINES), ('SPC_LINE', SPC_LINE),
        ('ICPT', GWA['ICPT']), ('ICHAIN', GWA['ICHAIN']),
        ('MAXINTERCEPTS', MAXINTERCEPTS), ('ICPT_SIZE', ICPT_SIZE),
        ('SG_BUF', GWA['SG_BUF']), ('SS_BUF', GWA['SS_BUF']),
        ('BL_BUF', BL_BUF), ('RT_STATE', RT_STATE), ('RT_END', RT_END),
        ('MO_XTICS', MO_XTICS), ('MO_XFUNC', MO_XFUNC),
        ('NODEB_SIZE', NODEB_SIZE), ('G_VALID', G_VALID), ('STALE', STALE),
        ('PRE_VALID', PRE_VALID), ('SEG_SIZE_G', R.SEG_SIZE),
        ('GT_STATES', GT['STATES'][0]), ('GT_MOBJINFO', GT['MOBJINFO'][0]),
        ('STATE_SIZE', STATE_SIZE), ('INFO_SIZE', INFO_SIZE),
        ('NUMSTATES', NUMSTATES), ('MTHING_SIZE', MTHING_SIZE),
        ('LVCOUNT', R.LVCOUNT), ('PRND', PRND)]
    out += [('NODE_' + k, x) for k, x in R.NODE.items()]
    out += [('MA_' + k, x) for k, x in MA.items()]
    out += [('MB_' + k, x) for k, x in MB.items()]
    out += [('MC_' + k, x) for k, x in MC.items()]
    out += [('SP_' + k, x) for k, x in SP.items()]
    for k, fields in SP_KIND.items():
        out += [('SP%s_%s' % (k[0:2].upper(), f), x) for f, x in
                fields.items()]
        lo, n = SPEC_RANGE[k]
        out += [('SPK_%s' % k.upper(), list(SPEC_RANGE).index(k)),
                ('SPK_%s_LO' % k.upper(), lo), ('SPK_%s_N' % k.upper(), n)]
    out += [('SN_' + k, x) for k, x in SN.items()]
    out += [('FN_' + k, x) for k, x in FN.items()]
    out += sorted(G.items(), key=lambda kv: kv[1])
    out += [('MT_' + k, x) for k, x in MTHING.items()]
    out += [('MT_PLAYER_START', MT_PLAYER_START), ('MT_NEVER', MT_NEVER)]
    pl = player_layout()
    if _size_of(pl) != dict(GLOBAL_FIELDS)['G_PLAYER']:
        raise ValueError('the player is %d bytes' % _size_of(pl))
    out += offset_names('PL_', pl)
    out.append(('PL_SIZE', _size_of(pl)))
    # (rlayout.inc's PL_VIEWZ is the render inputs' copy: the game's is
    # PL_VIEWZ_G)
    out = [(('PL_VIEWZ_G' if n == 'PL_VIEWZ' else n), v) for n, v in out]
    bl = button_layout()
    if 4 * _size_of(bl) != dict(GLOBAL_FIELDS)['G_BUTTONS']:
        raise ValueError('a button is %d bytes' % _size_of(bl))
    out += offset_names('BT_', bl)
    out.append(('BT_SIZE', _size_of(bl)))
    wm = native_struct(sch.structs['WBSTART'], None)
    out += offset_names('WM_', wm)
    # upstream's facts
    for name in ('OFS_MI_SPAWNSTATE', 'OFS_MI_SPAWNHEALTH',
                 'OFS_MI_REACTIONTIME', 'OFS_MI_RADIUS', 'OFS_MI_HEIGHT',
                 'OFS_MI_FLAGS', 'OFS_ST_SPRITE', 'OFS_ST_FRAME',
                 'OFS_ST_TICS', 'OFS_ST_ACTION', 'OFS_ST_NEXTSTATE',
                 'CONST_MF_SHADOW_HI', 'CONST_MF_COUNTKILL_HI',
                 'CONST_MF_COUNTITEM_HI', 'CONST_MF_NOSECTOR',
                 'CONST_MF_NOBLOCKMAP', 'CONST_MF_AMBUSH_LO',
                 'CONST_MF_POOLED_HI', 'CONST_MT_PLAYER', 'CONST_MT_MISC0',
                 'CONST_MT_NOTHING', 'CONST_SK_EASY', 'CONST_SK_HARD',
                 'CONST_SK_NIGHTMARE', 'CONST_PST_LIVE', 'CONST_PST_REBORN',
                 'CONST_WP_PISTOL', 'CONST_WP_FIST', 'CONST_WP_NOCHANGE',
                 'CONST_WP_CHAINSAW', 'CONST_AM_CLIP', 'CONST_NUMAMMO',
                 'CONST_NUMWEAPONS', 'CONST_VIEWHEIGHT_LO',
                 'CONST_VIEWHEIGHT_HI', 'CONST_S_NULL', 'CONST_ML_MAPPED',
                 'CONST_ST_VERTICAL',
                 'CONST_ST_POSITIVE', 'CONST_ST_NEGATIVE',
                 'CONST_MAXBUTTONS'):
        out.append((name.replace('OFS_', 'U_').replace('CONST_', 'U_'),
                    c[name] & 0xFFFF))
    for unit, name in (('p_spawn65.s', 'MTF_EASY'),
                       ('p_spawn65.s', 'MTF_NORMAL'),
                       ('p_spawn65.s', 'MTF_HARD'),
                       ('p_spawn65.s', 'MTF_AMBUSH'),
                       ('p_pspr65.s', 'LOWERSPEED_HI'),
                       ('p_pspr65.s', 'WEAPONBOTTOM_HI'),
                       ('p_pspr65.s', 'WEAPONTOP_HI'),
                       ('g_game65.s', 'INITIAL_HEALTH'),
                       ('g_game65.s', 'INITIAL_BULLETS'),
                       ('p_spec65.s', 'FASTDARK'),
                       ('p_spec65.s', 'SLOWDARK'),
                       # the pickups' and the cheats' (milestone 10, wave 2
                       # as integrated: docs/game-parts/pickup.md P1)
                       ('p_inter65.s', 'BONUSADD'),
                       ('m_cheat65.s', 'GOD_HEALTH'),
                       ('m_cheat65.s', 'IDFA_ARMOR'),
                       ('m_cheat65.s', 'IDFA_ARMOR_CLASS'),
                       ('m_cheat65.s', 'NUMCHEATS')):
        out.append(('U_' + name, c.local(unit, name) & 0xFFFF))
    out.append(('U_A_RAISE', sch.symbols.address('p_pspr65.s:A_Raise')))
    # the weapons (weaponinfo's six fields: milestone 10's part damage
    # writes its table from them, docs/game-parts/damage.md R2) and the
    # ammunition maxima, the release's tables (p_pspr65.s weaponinfo: 6
    # words a weapon; p_inter65.s maxammo)
    rel = U.Release()
    nw = c['CONST_NUMWEAPONS']
    wi = rel.table('p_pspr65.s:weaponinfo', 12 * nw)
    for w in range(nw):
        ammo, up, down, ready, atk, flash = struct.unpack_from('<6H', wi,
                                                               12 * w)
        out += [('U_WI_UP_%d' % w, up), ('U_WI_READY_%d' % w, ready),
                ('U_WI_AMMO_%d' % w, ammo), ('U_WI_DOWN_%d' % w, down),
                ('U_WI_ATK_%d' % w, atk), ('U_WI_FLASH_%d' % w, flash)]
    na = c['CONST_NUMAMMO']
    mx = rel.table('p_inter65.s:maxammo', 2 * na)
    for k in range(na):
        out.append(('U_MAXAMMO_%d' % k, struct.unpack_from('<H', mx,
                                                           2 * k)[0]))
    # the pickups' tables (p_inter65.s clipAmmo, halfClip, powerTics: the
    # release's; docs/game-parts/pickup.md P1)
    for name, sym in (('U_CLIPAMMO', 'clipAmmo'), ('U_HALFCLIP', 'halfClip')):
        t = rel.table('p_inter65.s:' + sym, 2 * na)
        for k in range(na):
            out.append(('%s_%d' % (name, k),
                        struct.unpack_from('<H', t, 2 * k)[0]))
    npw = c['CONST_NUMPOWERS']
    t = rel.table('p_inter65.s:powerTics', 2 * npw)
    for k in range(npw):
        out.append(('U_POWERTICS_%d' % k, struct.unpack_from('<H', t,
                                                             2 * k)[0]))
    return out


def game_include_text() -> str:
    lines = ['; Generated by tools/native/llayout.py --game (stage C: the '
             'game core). Do not edit.', '']
    for name, value in game_constants():
        lines.append('%-24s= $%X' % (name, value))
    lines.append('')
    lines.append('; zero page')
    for name, value in sorted(list(ZP_GAME.items()) +
                              list(ZP_SPAWN.items()), key=lambda x: x[1]):
        lines.append('%-24s= $%02X' % (name, value))
    return '\n'.join(lines) + '\n'


check()

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
