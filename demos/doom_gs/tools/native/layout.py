"""The addresses and formats of the native record replay.

One source for the host tools and the 65C02 code: rowgen.py writes the
ca65 include layout.inc from this module, so the assembler and the loader
and harness always agree.

The addresses are docs/MEMORY_MAP.md section 8 (the F1.2.1 placement of
milestone 5), with the departures listed there by the milestone's report
(src/native/README.md): the fill row blocks are two chains by row parity,
the replay keeps its gather descriptors in page 1, the fuzz drawer
steps its position itself (no FZMOD50 table), and the fuzz records wait
in a queue in aux 0 $02C0-$03FF to be drawn after each strip's columns.

The record format is upstream's (build/upstream/src/iigs/lists.inc), the
kinds and field offsets below; tests/test_native_replay.py checks them
against the link map when build/linkmap.json exists.
"""

# ---- upstream's records (lists.inc) ----

K_TEX, K_FILL, K_TEXC, K_FUZZ, K_OVL, K_NEXT = 0, 2, 6, 8, 10, 12
KIND_NAMES = {K_TEX: 'K_TEX', K_FILL: 'K_FILL', K_TEXC: 'K_TEXC',
              K_FUZZ: 'K_FUZZ', K_OVL: 'K_OVL', K_NEXT: 'K_NEXT'}
SIZES = {K_TEX: 11, K_FILL: 5, K_TEXC: 7, K_FUZZ: 4, K_OVL: 4, K_NEXT: 2}
FIELDS = {
    'R_KIND': 0, 'R_ROW': 1, 'R_END': 2,
    'R_B1': 3, 'R_B2': 4,                                   # K_FILL
    'R_TF': 3, 'R_TI': 4, 'R_SF': 5, 'R_SI': 6, 'R_SRC': 7,
    'R_CMP': 10,                                             # K_TEX
    'R_TCSRC': 5,                                            # K_TEXC
    'R_COUNT': 2, 'R_POS': 3,                                # K_FUZZ
    'R_KEEP': 2, 'R_COLOR': 3,                               # K_OVL
    'R_PAGE': 1,                                             # K_NEXT
}
# The port's own kind, in W only (the loader writes it, upstream never
# does; lists.inc has no kind 4): a K_FUZZ record the replay must draw in
# place, because a later record of its column paints one of the rows it
# reads or writes (row - 1 to row + count). The replay queues every other
# K_FUZZ record and draws the queue after the strip's columns
# (src/native/README.md, "The fuzz queue"). Same fields as K_FUZZ.
K_FUZZNOW = 4
SIZES[K_FUZZNOW] = SIZES[K_FUZZ]
COLUMNS = 160
VIEW_ROWS = 168                 # rows 0-167; row 168 is the landing
ROW_BYTES = 160
CMAP_LEVELS = 34                # upstream's R_CMP: $46 + the light level
CMAP_FIRST = 0x46
PAGE_ROOM = 254                 # a record ends at this offset or before

# ---- main memory ----

ZP_FIRST, ZP_END = 0x48, 0x70   # the replay's zero page, $48-$6F
PAGE1 = 0x0100
DESC = 0x0100                   # gather descriptors, 12 x 12 bytes
DESC_SIZE = 12
MAXDESC = 12
P1CODE = 0x0190                 # the per-row copy loop, copied here
P1CODE_END = 0x01B5             # the loop ends before this
STACK_FLOOR = 0x01C0            # the stack stays at or above this

CMPA = 0x0800                   # colormap A page by light level (34)
CMPB = 0x0822
TEXLO = 0x0900                  # entry of the texture row block of row r
TEXHI = 0x0A4A
MAIN_TABLES = 0x0800            # $0800-$0BFF as one image (the build's
MAIN_TABLES_END = 0x0C00        #   .main0800), of which only the tables
                                #   (MAIN_TABLE_RANGES) are ever loaded

FSTOP, FSBOT = 0x0F00, 0x0FA0   # fill spans (not read by the replay)
FSEVT, FSEVB = 0x1040, 0x10E0
FSODT, FSODB = 0x1180, 0x1220
FSSTT, FSSTB = 0x12C0, 0x1360
CVFIRST = 0x1400                # covered ranges
CVEND = 0x14A0
CVRECLO = 0x1540
CVRECHI = 0x15E0
COLLO = 0x1680                  # first record of column c; entry 160: end
COLHI = 0x1721
COL_TABLES = COLLO              # COLLO then COLHI, 322 bytes
COL_TABLES_SIZE = 2 * (COLUMNS + 1)
SCRATCH, SCRATCH_END = 0x17C2, 0x1800
WCLIP = 0x1800                  # weapon skip (not read by the replay)
WPREV = 0x18A0
WTMP = 0x18E0
WPREV_SIZE = 64

RECBUF = 0x6000                 # W: one batch of records
RECBUF_SIZE = 0x2000
STAGE = 0x8000                  # W: the texel stage; its top holds the
STAGE_END = 0xC000              # stage pointer of each texture record

# ---- the main language card ----

TEXBLK = 0xD000                 # bank 2: texture row pairs, 36 bytes
PAIR_BYTES = 36
EVEN_BYTES = 15                 # the odd row of a pair starts at +15
TEXLAND = TEXBLK + PAIR_BYTES * (VIEW_ROWS // 2)    # $DBD0: RTS
FILLE = 0xDC00                  # even rows: row r at FILLE + 3 * (r >> 1)
FILLO = 0xDD00                  # odd rows: row r at FILLO + 3 * (r >> 1)
FILL_LAND = 3 * (VIEW_ROWS // 2)                    # +$FC: RTS
HOT, HOT_END = 0xDE00, 0xE000   # bank 2: the draw pass
RCODE, RCODE_END = 0xF900, 0xFF00   # $E000 part: batches, gather

# ---- aux bank 0 ----

AUXCODE, AUXCODE_END = 0x0200, 0x02C0   # fuzz and overlay drawers
FUZZQ, FUZZQ_END = 0x02C0, 0x0400       # the fuzz queue: written with
FQMAX = 80                              #   RAMWRT on (the draw), read with
FQCOL = FUZZQ                           #   RAMRD on; FQMAX records of four
FQROW = FUZZQ + FQMAX                   #   fields as four arrays: the
FQCNT = FUZZQ + 2 * FQMAX               #   column, first row, count of
FQPOS = FUZZQ + 3 * FQMAX               #   rows, fuzz position
AUX_TABLES = 0x0800
AUX_TABLES_END = 0x0C00
FUZZDARK = 0x0800               # per level (the capture's fuzz.bin)
ROWLO = 0x0900                  # SHR row address, rows 0-199
FZDIR = 0x09C8                  # the fuzz direction by position: 1 below
ROWHI = 0x0A00
SCREEN = 0x2000                 # aux 0 $2000-$9FFF
SCREEN_SIZE = 0x8000
VIEW_END = SCREEN + VIEW_ROWS * ROW_BYTES           # $8900
PIXELS = 200 * ROW_BYTES        # $2000-$9CFF

# ---- soft switches ----

RDMAIN, RDAUX, WRMAIN, WRAUX = 0xC002, 0xC003, 0xC004, 0xC005
BANKSEL = 0xC073
LCBANK2, LCBANK1 = 0xC083, 0xC08B

# ---- the test and card images ----

TEXEL_BANKS = 4                 # texels in banks base .. base + 3
RECORDS_BANK = 4                # records in bank base + 4
BANK_ROOM = (0x0200, 0xC000)    # what RAMRD reaches in a RamWorks bank
MAX_BATCHES = 4
DRVDATA = 0x0200                # the driver's batch table (main)
PHASE = 0x0300                  # the cost phase byte (a2vm --cost-phase)
                                #   in main; aux $0300 is FQCOL + 64, so
                                #   a tool that reads phases from writes
                                #   to $0300 must take main writes only
                                #   (RAMWRT off), as a2vm does
DRV_STACK = 0xEF                # the driver's S: $01F0-$01FF above it is a
                                #   caller's frame the replay must not touch

# The a2vm test images fill every byte the frame does not define with one
# of these (tools/native/loader.py build_package): the captured run with
# the first, the poisoned run with the second, so a stray store of any
# constant shows in at least one of them.
FILL_CAPTURED, FILL_POISONED = 0xA5, 0x5A

# Doom's fuzzoffset (r_draw.c): +FUZZOFF, the row below, is 1. Upstream
# keeps the same table as fuzzDir (i_viigs65.s); the tests compare them.
FUZZ_DIR = (1, 0, 1, 0, 1, 1, 0,
            1, 1, 0, 1, 1, 1, 0,
            1, 1, 1, 0, 0, 0, 0,
            1, 0, 0, 1, 1, 1, 1, 0,
            1, 0, 1, 1, 0, 0, 1,
            1, 0, 0, 0, 0, 1, 1,
            1, 1, 0, 1, 1, 0, 1)
assert len(FUZZ_DIR) == 50


def cmap_page_a(level):
    """The main page of colormap A, light level 0-33."""
    return 0x20 + level if level < 32 else 0x04 + level - 32


def cmap_page_b(level):
    return 0x40 + level if level < 32 else 0x06 + level - 32


# The bytes of the table images that hold tables, as [start, end): only
# these are loaded, so the free and forbidden bytes between them (main
# $0878-$087F, docs/MEMORY_MAP.md rule 8; the XTVLO and XTVHI slots) are
# never written from the build.
MAIN_TABLE_RANGES = ((CMPA, CMPB + CMAP_LEVELS),
                     (TEXLO, TEXLO + VIEW_ROWS + 1),
                     (TEXHI, TEXHI + VIEW_ROWS + 1))
AUX_TABLE_RANGES = ((FUZZDARK, FUZZDARK + 256), (ROWLO, ROWLO + 200),
                    (FZDIR, FZDIR + len(FUZZ_DIR)), (ROWHI, ROWHI + 200))
FORBIDDEN_MAIN = ((0x0878, 0x0880), (0x4078, 0x4080))   # rule 8


# What the card runner (src/native/runner.s) loads by memory-API PRIVATE
# copies before each frame, from the frame's copies in RamWorks, as the
# game loads it (docs/MEMORY_MAP.md rules 3 and 8): main's colormaps and
# tables, aux 0's drawers and tables. [start, end) ranges, the tables'
# contiguous ranges merged. The rest of main $0200-$1FFF the runner
# restores by CPU (never $0400-$0BFF); aux 0's screen by CPU (rule 4).
def _merged(ranges):
    out = []
    for start, end in sorted(ranges):
        if out and out[-1][1] == start:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return tuple(out)


PRIVATE_MAIN = _merged(((0x0400, 0x0800),) + MAIN_TABLE_RANGES +
                       ((0x2000, 0x6000),))
PRIVATE_AUX0 = _merged(((AUXCODE, AUXCODE_END),) + AUX_TABLE_RANGES)
CPU_MAIN = ((0x0200, 0x0400), (0x0C00, 0x2000))


def restore_include():
    """restore.inc for ca65: the runner's PRIVATE copy descriptors
    (appletini-one README_MEMORY_API.md section 3), the source bank (byte
    3) left 0 for the runner to set: the frame's main copy for the first
    RESTORE_MAIN, its aux-0 copy for the others."""
    lines = ['; Generated by tools/native/rowgen.py from tools/native/'
             'layout.py. Do not edit.', '',
             'RESTORE_N       = %d' % (len(PRIVATE_MAIN) + len(PRIVATE_AUX0)),
             'RESTORE_MAIN    = %d' % len(PRIVATE_MAIN), '',
             '.macro RESTORE_LIST']
    for space, ranges in ((0, PRIVATE_MAIN), (1, PRIVATE_AUX0)):
        for start, end in ranges:
            lines += ['        .byte   1, 1, 1, 0      ; COPY, PRIVATE, '
                      'from AUX bank (set)',
                      '        .word   $%04X' % start,
                      '        .byte   %d, 0            ; to %s' % (
                          space, 'MAIN' if space == 0 else 'AUX bank 0'),
                      '        .word   $%04X, $%04X    ; $%04X-$%04X' % (
                          start, end - start, start, end - 1),
                      '        .byte   0, 0, 0, 0']
    lines += ['.endmacro']
    return '\n'.join(lines) + '\n'


def tex_entry(row):
    """The texture row block of row 0-168 (168: the landing)."""
    return TEXBLK + PAIR_BYTES * (row >> 1) + (EVEN_BYTES if row & 1 else 0)


def row_address(row):
    return SCREEN + ROW_BYTES * row


# The replay may write these, and nothing else (the harness checks every
# byte of every bank outside them): its zero page, the gather descriptors
# and the copy loop in page 1, the stack from STACK_FLOOR up to the
# caller's S (allowed_main below), the covered ranges it clears, its main
# scratch, the texel stage with its pointer list, the fuzz queue and the
# 3D view of the screen. The language card is not listed: its row-block
# patches are restored.
ALLOWED_MAIN = ((ZP_FIRST, ZP_END), (DESC, P1CODE_END),
                (CVFIRST, CVRECLO), (SCRATCH, SCRATCH_END),
                (STAGE, STAGE_END))
ALLOWED_AUX0 = ((FUZZQ, FUZZQ_END), (SCREEN, VIEW_END))
assert FUZZQ == AUXCODE_END and FUZZQ + 4 * FQMAX == FUZZQ_END


def allowed_main(sp):
    """ALLOWED_MAIN with the stack the replay may use when called with S
    = sp (before the JSR): STACK_FLOOR to $0100 + sp. The bytes above sp
    are the caller's."""
    if PAGE1 + sp < STACK_FLOOR:
        raise ValueError('S $%02X is below the stack floor' % sp)
    return tuple(sorted(ALLOWED_MAIN + ((STACK_FLOOR, PAGE1 + sp + 1),)))

CONSTANTS = [
    ('K_TEX', K_TEX), ('K_FILL', K_FILL), ('K_TEXC', K_TEXC),
    ('K_FUZZ', K_FUZZ), ('K_OVL', K_OVL), ('K_NEXT', K_NEXT),
    ('K_FUZZNOW', K_FUZZNOW),
    ('TEX_SIZE', SIZES[K_TEX]), ('FILL_SIZE', SIZES[K_FILL]),
    ('TEXC_SIZE', SIZES[K_TEXC]), ('FUZZ_SIZE', SIZES[K_FUZZ]),
    ('OVL_SIZE', SIZES[K_OVL]),
] + sorted(FIELDS.items()) + [
    ('COLUMNS', COLUMNS), ('VIEW_ROWS', VIEW_ROWS),
    ('CMAP_FIRST', CMAP_FIRST),
    ('DESC', DESC), ('DESC_SIZE', DESC_SIZE), ('MAXDESC', MAXDESC),
    ('P1CODE', P1CODE), ('P1CODE_END', P1CODE_END),
    ('STACK_FLOOR', STACK_FLOOR),
    ('CMPA', CMPA), ('CMPB', CMPB), ('TEXLO', TEXLO), ('TEXHI', TEXHI),
    ('CVFIRST', CVFIRST), ('CVEND', CVEND), ('CVRECLO', CVRECLO),
    ('CVRECHI', CVRECHI), ('COLLO', COLLO), ('COLHI', COLHI),
    ('RECBUF', RECBUF), ('STAGE', STAGE), ('STAGE_END', STAGE_END),
    ('TEXBLK', TEXBLK), ('FILLE', FILLE), ('FILLO', FILLO),
    ('FUZZDARK', FUZZDARK), ('ROWLO', ROWLO), ('ROWHI', ROWHI),
    ('FZDIR', FZDIR), ('AUXCODE_END', AUXCODE_END),
    ('FQMAX', FQMAX), ('FQCOL', FQCOL), ('FQROW', FQROW), ('FQCNT', FQCNT),
    ('FQPOS', FQPOS),
    ('RDMAIN', RDMAIN), ('RDAUX', RDAUX), ('WRMAIN', WRMAIN),
    ('WRAUX', WRAUX), ('BANKSEL', BANKSEL), ('LCBANK2', LCBANK2),
    ('LCBANK1', LCBANK1),
    ('DRVDATA', DRVDATA), ('PHASE', PHASE), ('MAX_BATCHES', MAX_BATCHES),
    ('DRV_STACK', DRV_STACK),
]


def include_text():
    """layout.inc for ca65: every constant above."""
    lines = ['; Generated by tools/native/rowgen.py from tools/native/'
             'layout.py. Do not edit.', '']
    for name, value in CONSTANTS:
        lines.append('%-16s= $%04X' % (name, value))
    return '\n'.join(lines) + '\n'
