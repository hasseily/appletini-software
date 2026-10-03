#!/usr/bin/env python3
"""build/native/CALIB.hdv, the calibration disk (docs/SPEED.md 5,
docs/results/calib.md): CALIB.SYSTEM (src/native/calib.s) times 52
microbenchmarks on the card with the Phasor's timers and shows each
beside a2vm's f121 prediction, on the 80-column text screen: 44 on text
page 1, the memory API's PRIVATE copies on page 2 (SPACE on the card).

Usage:  python3 tools/native/calibdisk.py [--play DIR] [--out FILE]
            [--doc] [--keep DIR]

The steps:

  1. gen: the play build's bytes (--play, default build/native/play) into
     build/native/calib/gen: far.bin (the card's bank 1 $DC00-$DFFF: far.s's
     far_get, far_put, far_pload, as pldisk.card_images puts them in
     LC.BIN), kern.bin (the kernel's far_gcopy, $FFD5-$FFF9), pw.bin
     (gobj.s's page-1 window, from the tic image's core), calibplay.inc
     (their addresses and the layout's constants), calibpred.inc (a2vm's
     figures, zero at first); checked against each other and, when it is
     there, against build/native/DOOM.hdv's LC.BIN and CODE.2;
  2. make -f src/native/calib.mk;
  3. a2vm f121 (playdisk's f121: f121+phasor+window32), --via-timers,
     --amem, the exact core, --cost-timed: the run ends when the screen
     shows the results; check() reads them back;
  4. the figures into calibpred.inc, make again, the disk; the same run
     again (its figures must equal the first's, and its screen shows
     them in the A2VM column), fastpath, f121 with the default window
     of 512 (f121+phasor), and f121 before the card corrected it (the
     cost variant precal), each checked. --doc compares them with the
     card's figures (CARD: the owner's photo of 2026-10-03).

check() (the checks of tests/test_calib.py too): the run ended on the
screen; every operation measured with both timers agreeing and D > 0;
each E equals the host's computation from the timer reads stored with
it, and equals a2vm's own clock between the measurement's PCs (the PC
log) within CLOCK_SLACK (1 bus cycle; the PAL runs come within 0.01);
the PC log's unit calls in each measurement equal the count the program
used for its arithmetic (n, then 2n); the
figures equal the host's computation from the E's; the screen equals the
host's rendering of them; the game's bytes are in place in the card and
page 1; the memory API ran every request the lines and their setups
send (a2vm's count) and none was refused, and main $2000-$9FFF, which
the PRIVATE lines rewrite from bank 17, still holds the program, as bank
17 does (the setups' copy). --doc writes docs/results/calib.md. Every
a2vm run is bounded
(bounded.run) in a directory deleted after it (--keep keeps them).
"""

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from native import lrun, pldisk, playdisk, \
    render_check as RC  # noqa: E402
from ref816 import bounded  # noqa: E402

BUILD = ROOT / 'build'
NATIVE = BUILD / 'native'
CALIB = NATIVE / 'calib'
GEN = CALIB / 'gen'
OBJ = CALIB / 'obj'
OUT = NATIVE / 'CALIB.hdv'
PLAY = NATIVE / 'play'
DOOM_HDV = NATIVE / 'DOOM.hdv'
SOURCE = ROOT / 'src' / 'native'
MAKEFILE = SOURCE / 'calib.mk'
DOC = ROOT / 'docs' / 'results' / 'calib.md'
A2VM = lrun.A2VM
VOLUME = 'CALIB'
SYSTEM = 'CALIB.SYSTEM'

# a2vm's profiles: playdisk's (the game's f121 and fastpath, with the Phasor's
# slowdown window of the DOOM profile, 32 cycles), and f121 with the
# default window of 512
PROFILES = {'f121': playdisk.PROFILES['f121'],
            'fastpath': playdisk.PROFILES['fastpath'],
            'f121w512': 'f121+phasor',
            # the model before the card's figures corrected it (the cost
            # variant precal), for the comparison of docs/results/calib.md
            'f121pre': playdisk.PROFILES['f121-precal']}
SECONDS = 40.0                  # model time a run may take (it takes ~9 s)
TIMEOUT = 600.0
MAX_BYTES = 256 << 20
PCLOG_LIMIT = 900000            # lines (about 40 MB): a run logs ~570,000
SNAP_RANGES = 'main:0000-BFFF,lc,lc1,aux0:0400-0BFF,aux17:2000-9FFF'

NOPS = 52
NOPS1 = 44                      # page 1's lines; the rest are page 2's
R_SIZE = 64
OP_REG, OP_SPIN, OP_WIN = 0, 20, 21
OP_PR = 44                      # the memory API's PRIVATE lines
RWS = 17                        # their source bank
UC_REG, UC_SPIN = 1313, 837     # calib.s's
BPS = {'PAL': 984615, 'NTSC': 979927}
PAL_CUT = 18655
DELTA_MAX = 24
CLOCK_SLACK = 1                 # bus cycles: E against a2vm's clock
PW_MAX = 4                      # gobj.s

# What each line measures (docs/results/calib.md), by the name on screen
WHAT = {
    'REG': 'a register-only loop: one `dey / bne` turn (5 cycles), in the '
           'card',
    'MAIN RD': '`lda abs,y / iny / bne` over 16 pages of main memory '
               '($A000-$AFFF): one byte',
    'MAIN WR': '`sta abs,y / iny / bne` over the same pages: one byte',
    'AUX RD': 'MAIN RD in aux bank 0 (RAMRD on, `$C073` = 0, the loop in '
              'the card)',
    'AUX WR': 'MAIN WR in aux bank 0 (RAMWRT on)',
    'RW HIT': 'MAIN RD\'s loop shape on RamWorks bank 16 (RAMRD on), but '
              '`lda abs,x` with X = 0: every read the same byte, the line '
              'cache\'s hit',
    'RW SEQ': 'MAIN RD in bank 16: in order, one line miss every 8 bytes',
    'RW UHIT': '64 unrolled `lda abs` of one byte of bank 16 (hits): the '
               'base of the next two',
    'RW S64': '64 unrolled `lda abs` of bank 16 at a stride of 64 bytes: '
              'every read a miss',
    'RW S256': 'the same at a stride of 256 bytes (64 pages)',
    'RW WHIT': 'RW HIT\'s loop with `sta abs,x` (RAMWRT on): every write '
               'the same byte',
    'RW WSEQ': 'MAIN WR in bank 16: in order, a dirty line every 8 bytes',
    'RW WS64': '64 unrolled `sta abs` at a stride of 64 bytes: every '
               'write a miss with a dirty victim',
    'GC RW 1': 'far_gcopy (the kernel\'s, `$FFD5`) of 1 page from bank 16 '
               'to main, called as gr_load calls it',
    'GC RW 4': 'far_gcopy of 4 pages from bank 16',
    'GC RW 8': 'far_gcopy of 8 pages from bank 16',
    'GC AX 1': 'far_gcopy of 1 page from aux bank 0',
    'GC AX 4': 'far_gcopy of 4 pages from aux bank 0',
    'GC AX 8': 'far_gcopy of 8 pages from aux bank 0',
    'PLOAD 4': 'far_pload (far.s) of a list of one run of 4 pages from '
               'bank 16 to the same main pages',
    'SPIN': 'a main read then 160 turns of `dey / bne` (837 cycles with '
            'the driver)',
    'WIN': 'SPIN with a read of VIA-A\'s DDRA (`$C413`) in place of the '
           'main read: the slot-4 window it opens (the header\'s WIN)',
    'GET RW 4': 'far_get (far.s) of 4 bytes from bank 16 to main',
    'GET RW24': 'far_get of 24 bytes from bank 16',
    'GET RW96': 'far_get of 96 bytes from bank 16',
    'GET AX 4': 'far_get of 4 bytes from aux bank 0',
    'GET AX24': 'far_get of 24 bytes from aux bank 0',
    'GET AX96': 'far_get of 96 bytes from aux bank 0',
    'PUT RW 4': 'far_put (far.s) of 4 bytes from main to bank 16',
    'PUT RW24': 'far_put of 24 bytes to bank 16',
    'PUT RW96': 'far_put of 96 bytes to bank 16',
    'PUT AX 4': 'far_put of 4 bytes to aux bank 0',
    'PUT AX24': 'far_put of 24 bytes to aux bank 0',
    'PUT AX96': 'far_put of 96 bytes to aux bank 0',
    'MO GET': 'gobj.s\'s page-1 window (`pw_go`) with mo_fetch\'s four '
              'descriptors: a mobj\'s RTHING, A, B and C groups (4 x 24 '
              'bytes, four banks) into a cache line; the descriptors\' '
              'setup excluded',
    'MO PUT': 'the same window as mo_wback writes it: the four groups '
              'back (RAMWRT)',
    'LN GET': 'the window with ln_miss\'s three descriptors: a line\'s '
              'record (32 bytes, LVG0) and its two sector bytes (LVS)',
    'SW NONE': '`jsr` to 16 `lda abs,x` in main and back: the base of the '
               'switches',
    'SW RAMRD': '`sta $C003 / sta $C002` (from the card) then SW NONE\'s '
                'main code',
    'SW RAMWR': '`sta $C005 / sta $C004` then the main code',
    'SW C073': '`stz $C073` then the main code',
    'SW ALTZP': '`sta $C009 / sta $C008` then the main code',
    'SHR SEQ': 'RAMWRT on, 256 contiguous bytes to aux `$2000` (SHR), '
               'RAMWRT off, `lda $C000`: the burst and its drain',
    'SHR COL': 'the same with a column: 96 bytes 160 apart',
    'PR2 256': 'the memory API (slot 7): one request of one PRIVATE COPY of '
               '256 bytes from RamWorks bank 17 to main `$2000` (the '
               'colormaps\' place in the game), sent through the '
               '`$CFF0-$CFF2` FIFO as lload.s\'s am_send sends one: the '
               'request\'s 36 bytes pushed, executed, its result popped',
    'PR2 2K': 'the same, 2 KB',
    'PR2 16K': 'the same, 16 KB (`$2000-$5FFF`)',
    'PR2 8X2K': 'the same 16 KB as eight requests of 2 KB, one after the '
                'other (us/op: a request)',
    'PR6 256': 'PR2 256 to main `$6000`',
    'PR6 2K': 'PR2 2K to main `$6000`',
    'PR6 16K': 'PR2 16K to main `$6000-$9FFF`',
    'PR6 8X2K': 'PR2 8X2K to main `$6000-$9FFF`',
}

# the PRIVATE lines: the requests a unit (k), its bytes a request (b)
PR_LINES = ('PR2 256', 'PR2 2K', 'PR2 16K', 'PR2 8X2K',
            'PR6 256', 'PR6 2K', 'PR6 16K', 'PR6 8X2K')
PAGE2_HEAD = 'CALIB PAGE 2: THE MEMORY API  SPACE: PAGE 1  R: RUN AGAIN'
PAGE2_LEGEND = (
    'PR2: ONE PRIVATE COPY FROM RAMWORKS BANK 17 TO MAIN $2000 (THE '
    'COLORMAPS)',
    'PR6: THE SAME TO MAIN $6000. EACH LINE A MEMORY-API REQUEST, FIFO '
    'INCLUDED',
    '256, 2K, 16K: ONE REQUEST OF THAT SIZE; 8X2K: EIGHT REQUESTS OF 2K IN '
    'A ROW',
    'US/OP: A REQUEST; US/B: A BYTE; A2VM F121: THE MODEL\'S US/OP')
PAGE2_NOAMEM = ('NO MEMORY API IN SLOT 7 (APPLETINI F1.1.4 OR LATER, VTW '
                'ON): NOT MEASURED')


# The card's figures: the owner's photo of the screen (PAL //e, the DOOM
# profile's window of 32), 2026-10-03, CALIB.hdv SHA-1 e692b6e4: us an
# operation, by line, in thousandths (the screen's digits). The header read
# CPU 66.690 MHZ, TIME 8.417 S.
CARD_DATE = '2026-10-03'
CARD_DISK = 'e692b6e441367274cec3c4513bc4bfd2a9b7c4bb'
CARD_MHZ, CARD_TIME = '66.690', '8.417'
CARD = {
    'REG': 77, 'MAIN RD': 141, 'MAIN WR': 150, 'AUX RD': 141, 'AUX WR': 150,
    'RW HIT': 158, 'RW SEQ': 246, 'RW UHIT': 100, 'RW S64': 985,
    'RW S256': 985, 'RW WHIT': 173, 'RW WSEQ': 369, 'RW WS64': 1969,
    'GC RW 1': 85339, 'GC RW 4': 321688, 'GC RW 8': 636442,
    'GC AX 1': 64000, 'GC AX 4': 237271, 'GC AX 8': 468422,
    'PLOAD 4': 322480, 'SPIN': 12595, 'WIN': 45292,
    'GET RW 4': 6892, 'GET RW24': 13785, 'GET RW96': 40369,
    'GET AX 4': 6890, 'GET AX24': 12800, 'GET AX96': 33477,
    'PUT RW 4': 8828, 'PUT RW24': 18667, 'PUT RW96': 54152,
    'PUT AX 4': 7860, 'PUT AX24': 13711, 'PUT AX96': 34462,
    'MO GET': 45038, 'MO PUT': 54155, 'LN GET': 23579,
    'SW NONE': 1429, 'SW RAMRD': 4923, 'SW RAMWR': 4922, 'SW C073': 2954,
    'SW ALTZP': 4923, 'SHR SEQ': 259152, 'SHR COL': 238771,
}


class CalibError(Exception):
    pass


# ---------------------------------------------------------------------------
# The play build's bytes
# ---------------------------------------------------------------------------

class Parts(NamedTuple):
    far: bytes                  # $DC00-$DFFF of the card's bank 1
    kern: bytes                 # far_gcopy .. $FFF9
    pw: bytes                   # pw_go .. pw_code_end
    consts: Dict[str, int]      # calibplay.inc


def card_offset(address: int) -> int:
    return pldisk.card_offset(address, True)


def play_parts(play: Path = PLAY) -> Parts:
    """The game's routines as the play build links them (read only)."""
    boot = pldisk.load_boot(play / 'card')
    _, main = pldisk.card_images(boot)
    tic = RC.load_build(play / 'tic', 'tic')
    lab = tic.labels
    for name in ('far_get', 'far_put', 'far_pload', 'far_gcopy'):
        if name in boot.labels and boot.labels[name] != lab[name]:
            raise CalibError('%s: the card has $%04X, the tic image $%04X'
                             % (name, boot.labels[name], lab[name]))
    far_lo = 0xDC00
    far = main[card_offset(far_lo):card_offset(far_lo) + 0x400]
    # the code (up to RLOAD's lists, each image's own: pldisk.area_problems)
    tic_far = (play / 'tic' / 'tic.far').read_bytes()
    code = lab['wl_front'] - far_lo
    if far[:code] != tic_far[:code]:
        raise CalibError('the card\'s far area differs from the tic link\'s')
    for name in ('far_get', 'far_put', 'far_pload'):
        if not far_lo <= lab[name] < far_lo + 0x400:
            raise CalibError('%s at $%04X, outside $DC00-$DFFF'
                             % (name, lab[name]))
    gcopy = boot.labels['far_gcopy']
    kern = main[card_offset(gcopy):card_offset(0xFFFA)]
    core = (play / 'tic' / 'tic.core').read_bytes()
    pw_go, pw_end = lab['pw_go'], lab['pw_code_end']
    at = lab['pw_image'] - 0x6600
    pw = core[at:at + pw_end - pw_go]
    if pw[:3] != bytes([0x8D, 0x03, 0xC0]):
        raise CalibError('pw_go does not start with sta RAMRDON')
    off = pw.rfind(bytes([0x8D, 0x02, 0xC0]))
    byte = lab['pw_byte'] - pw_go
    if off < 0 or pw[byte] != 0xB9 or pw[byte + 3] != 0x99:
        raise CalibError('pw_go is not lda abs,y / sta abs,y with a '
                         'sta RAMRDOFF after it')
    sym = playdisk.symbols(play)
    pw_end_room = sym['PW_END']
    if pw_end + 6 * PW_MAX > pw_end_room:
        raise CalibError('the descriptors pass PW_END')
    consts = {'FAR_GET': lab['far_get'], 'FAR_PUT': lab['far_put'],
              'FAR_PLOAD': lab['far_pload'], 'FAR_GCOPY': gcopy,
              'FAR_LO': far_lo, 'FAR_LEN': len(far), 'KERN_LO': gcopy,
              'KERN_LEN': len(kern), 'PW_GO': pw_go, 'PW_LEN': len(pw),
              'PW_ON': pw_go + 1, 'PW_OFF': pw_go + off + 1}
    for i, name in enumerate(('PW_BANK', 'PW_SL', 'PW_SH', 'PW_DL', 'PW_DH',
                              'PW_N')):
        consts[name] = pw_end + PW_MAX * i
    for name in ('FA_DST', 'FA_SRC', 'FA_BANK', 'FA_N', 'RTH', 'MOBJA',
                 'MOBJB', 'MOBJC', 'MO_SIZE', 'RTHBASE', 'MOC', 'LVG0', 'LVS',
                 'LINE_BASE', 'LINE_SIZE', 'LVS_LNSECF', 'LVS_LNSECB', 'LNC'):
        consts[name] = sym[name]
    return Parts(bytes(far), bytes(kern), bytes(pw), consts)


def doom_problems(parts: Parts, hdv: Path = DOOM_HDV) -> List[str]:
    """The parts against the game's disk: LC.BIN's main card holds far.bin
    and kern.bin at their places, CODE.2 (the tic image) holds pw.bin."""
    bd = pldisk.disk_writer()
    image = bd.Image(hdv.read_bytes())
    _, entries, _ = bd.list_volume(image)
    lc = bd.read_file(image, bd.find_entry(entries, 'LC.BIN'))
    main = lc[pldisk.HALF:]
    out = []
    at = card_offset(parts.consts['FAR_LO'])
    if main[at:at + len(parts.far)] != parts.far:
        out.append('%s: LC.BIN\'s far area differs' % hdv.name)
    at = card_offset(parts.consts['KERN_LO'])
    if main[at:at + len(parts.kern)] != parts.kern:
        out.append('%s: LC.BIN\'s far_gcopy differs' % hdv.name)
    code2 = bd.read_file(image, bd.find_entry(entries, 'CODE.2'))
    if parts.pw not in code2:
        out.append('%s: CODE.2 lacks the page-1 window' % hdv.name)
    return out


def write_if_changed(path: Path, data: bytes) -> None:
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def write_gen(parts: Parts, pred: Optional[Sequence[int]] = None,
              gen: Path = GEN) -> None:
    gen.mkdir(parents=True, exist_ok=True)
    write_if_changed(gen / 'far.bin', parts.far)
    write_if_changed(gen / 'kern.bin', parts.kern)
    write_if_changed(gen / 'pw.bin', parts.pw)
    lines = ['; Generated by tools/native/calibdisk.py from the play build. '
             'Do not edit.']
    for name in sorted(parts.consts):
        lines.append('%-12s = $%04X' % (name, parts.consts[name]))
    write_if_changed(gen / 'calibplay.inc',
                     ('\n'.join(lines) + '\n').encode())
    pred = list(pred) if pred is not None else [0] * NOPS
    if len(pred) != NOPS:
        raise CalibError('%d predictions' % len(pred))
    lines = ['; Generated by tools/native/calibdisk.py: a2vm f121\'s ns an '
             'operation. Do not edit.']
    for i in range(0, NOPS, 4):
        lines.append('        .dword ' + ', '.join(
            '%d' % min(v, 0xFFFFFFFF) for v in pred[i:i + 4]))
    write_if_changed(gen / 'calibpred.inc',
                     ('\n'.join(lines) + '\n').encode())


# ---------------------------------------------------------------------------
# The program and the disk
# ---------------------------------------------------------------------------

class Program(NamedTuple):
    obj: Path
    system: bytes
    labels: Dict[str, int]


def make(obj: Path = OBJ, gen: Path = GEN, src: Optional[Path] = None
         ) -> Program:
    """calib.mk; a warning of ca65 or ld65 is an error."""
    args = ['make', '-s', '-f', str(MAKEFILE), 'ROOT=%s' % ROOT,
            'GEN=%s' % gen, 'OUT=%s' % obj]
    if src is not None:
        args.append('SRC=%s' % src)
    result = subprocess.run(args, cwd=str(SOURCE), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            universal_newlines=True, timeout=120)
    if result.returncode or result.stdout.strip():
        raise CalibError('make: %s' % result.stdout.strip()[-2000:])
    labels = {}
    for line in (obj / 'calib.lbl').read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'al':
            labels[parts[2].lstrip('.')] = int(parts[1], 16)
    return Program(obj, (obj / SYSTEM).read_bytes(), labels)


def write_disk(system: bytes, out: Path = OUT) -> bytes:
    """A ProDOS 2.4.3 volume CALIB: PRODOS, CALIB.SYSTEM."""
    bd = pldisk.disk_writer()
    bd.VOLUME_NAME = VOLUME
    master = bd.DEFAULT_MASTER
    if not master.is_file():
        raise CalibError('%s is missing (appletini-one\'s ProDOS)' % master)
    boot, prodos = bd.extract_prodos(master)
    files = [('PRODOS', bd.FILE_TYPE_SYS, 0x0000, prodos),
             (SYSTEM, 0xFF, 0x2000, system)]
    writer = bd.VolumeWriter(VOLUME, bd.volume_size([f[3] for f in files]))
    writer.set_boot_blocks(boot)
    for name, file_type, aux, data in files:
        writer.add_file(name, data, file_type, aux)
    image = writer.finish()
    bd.verify_image(image, {n: (t, a, d) for n, t, a, d in files},
                    order=[f[0] for f in files])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image)
    return image


def disk_system(hdv: Path) -> bytes:
    bd = pldisk.disk_writer()
    bd.VOLUME_NAME = VOLUME
    image = bd.Image(hdv.read_bytes())
    _, entries, _ = bd.list_volume(image)
    return bd.read_file(image, bd.find_entry(entries, SYSTEM))


# ---------------------------------------------------------------------------
# A run on a2vm
# ---------------------------------------------------------------------------

class Run(NamedTuple):
    profile: str
    state: Dict[str, Any]
    image: Dict[Tuple[int, int], bytearray]
    pclog: List[Tuple[int, int, List[int]]]     # (clock, pc, bytes)
    bus_per_clock: float
    out: str


def run(prog: Program, profile: str, work: Path, *, timed: bool = True,
        pclog: bool = True, seconds: float = SECONDS,
        a2vm: Path = A2VM, amem: bool = True) -> Run:
    """CALIB.SYSTEM at $2000 as ProDOS starts it, until the screen shows
    the results (`done`) or a crash; with the memory API in slot 7 (as
    the card has it) unless `amem` is false."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / SYSTEM).write_bytes(prog.system)
    lab = prog.labels
    prof = PROFILES.get(profile, profile)
    params = costs.parameters(prof)
    fabric_hz = params['fabric_mhz'] * 1e6
    args = [str(a2vm), '--rom', str(work / 'rom.bin'), '--core', 'w65c02s',
            '--via-ora-nh', '--via-timers'] + (['--amem'] if amem else []) + [
            '--load', '2000:%s' % (work / SYSTEM),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--stop-pc', '%X' % lab['done'],
            '--stop-pc', '%X' % lab['crash'],
            '--snapshot-dir', str(work), '--snapshot-ranges', SNAP_RANGES,
            '--final-snapshot', '--state', str(work / 'state.json')]
    if timed:
        (work / 'cost.txt').write_text(costs.text(prof))
        args += ['--cost', str(work / 'cost.txt'), '--cost-timed',
                 '--cycles', str(int(seconds * fabric_hz))]
    else:
        args += ['--cycles', str(int(seconds * 60e6))]
    if pclog:
        zp = [lab['opx'], lab['cnt'], lab['cnt'] + 1]
        args += ['--pclog', str(work / 'pc.log'), '--pclog-pcs',
                 ','.join('%X' % lab[n] for n in ('m_go', 'm_call', 'm_end',
                                                   't_bok')),
                 '--pclog-bytes', ','.join('%X' % a for a in zp),
                 '--pclog-limit', str(PCLOG_LIMIT)]
    try:
        result = bounded.run(args, timeout=TIMEOUT, max_bytes=MAX_BYTES,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise CalibError('a2vm did not finish in %d s' % TIMEOUT)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise CalibError('a2vm failed (%d): %s' % (result.returncode,
                                                   result.stdout[-1500:]))
    state = json.loads(state_path.read_text())
    image = pldisk.read_snapshot(work / 'final.img')
    lines = []
    if pclog:
        with open(str(work / 'pc.log')) as handle:
            for line in handle:
                if line.startswith('#'):
                    continue
                f = line.split()
                lines.append((int(f[0]), int(f[1], 16),
                              [int(x, 16) for x in f[7:]]))
    # the bus clock a fabric clock (a2vm_bus_clock: PAL's Apple cycle is
    # 131.28 fabric clocks, a2vm's frame_1mhz / frame_cycles)
    bus = 1.0
    if timed:
        bus = 1015625.0 / fabric_hz
    return Run(profile, state, image, lines, bus, result.stdout[-4000:])


# ---------------------------------------------------------------------------
# The results and the host's computation
# ---------------------------------------------------------------------------

def u32(b: bytes, at: int) -> int:
    return struct.unpack_from('<I', b, at)[0]


def u16(b: bytes, at: int) -> int:
    return struct.unpack_from('<H', b, at)[0]


def elapsed(ts: bytes) -> Tuple[int, int, int]:
    """calib.s t_elapsed: (E, the timers' difference (signed), bad)."""
    b0, a0, b1, a1 = (u16(ts, i) for i in (0, 2, 4, 6))
    eb = (b0 - b1) & 0xFFFF
    a0 = 0xFEFF if a0 == 0xFFFF else a0
    a1 = 0xFEFF if a1 == 0xFFFF else a1
    ea = (a0 - a1) & 0xFFFF
    if a0 < a1:
        ea = (ea - 0x100) & 0xFFFF
    xx = (ea - eb) & 0xFFFF
    if ea < eb:
        xx = (xx - 0x100) & 0xFFFF
    if xx >= 0xFE80:
        qq, dlt = 0, xx & 0xFF
    else:
        s = xx + 0x80
        qq, dlt = s >> 8, ((s & 0xFF) - 0x80) & 0xFF
    sdlt = dlt - 256 if dlt >= 128 else dlt
    return (qq << 16) | eb, sdlt, int(abs(sdlt) > DELTA_MAX)


def divr(num: int, den: int) -> int:
    """calib.s divr64: round(num / den), halves up, 64 bits."""
    num &= (1 << 64) - 1
    return (((num + (den >> 1)) & ((1 << 64) - 1)) // den) & ((1 << 64) - 1)


def r4(value: int) -> int:
    """store_r4: a quotient past 32 bits is $FFFFFFFF."""
    return value if value <= 0xFFFFFFFF else 0xFFFFFFFF


class Op(NamedTuple):
    name: str
    n: int
    k: int
    b: int
    mode: int
    bank: int
    unit: int


class Rec(NamedTuple):
    e1: int
    e2: int
    d: int
    v: int
    vb: int
    err: int
    dlt1: int
    dlt2: int
    n: int
    ts1: bytes
    ts2: bytes


class Results(NamedTuple):
    ops: List[Op]
    recs: List[Rec]
    bps: int
    vbl: int
    verr: int
    w10: int
    wbad: int
    mhz: int
    runs: int
    done: int
    pred: List[int]
    tts: bytes
    time: int
    terr: int
    tms: int
    amem: int                   # the probe: 0 the API is there


def ops_of(prog: Program) -> List[Op]:
    """The operation table, from the program's own bytes."""
    lab, sysb = prog.labels, prog.system

    def at(name: str, i: int) -> int:
        return sysb[lab[name] - 0x2000 + i]
    out = []
    for i in range(NOPS):
        name = bytes(sysb[lab['op_names'] - 0x2000 + 8 * i:
                          lab['op_names'] - 0x2000 + 8 * i + 8]).decode()
        out.append(Op(name.rstrip(), at('op_n_lo', i) | at('op_n_hi', i) << 8,
                      at('op_k_lo', i) | at('op_k_hi', i) << 8,
                      at('op_b_lo', i) | at('op_b_hi', i) << 8,
                      at('op_mode', i), at('op_bank', i),
                      at('op_unit_lo', i) | at('op_unit_hi', i) << 8))
    return out


def results(prog: Program, r: Run) -> Results:
    lab = prog.labels
    main = r.image[(0, 0)]
    recs = []
    for i in range(NOPS):
        b = bytes(main[lab['res'] + R_SIZE * i:lab['res'] + R_SIZE * (i + 1)])
        recs.append(Rec(u32(b, 0), u32(b, 4), u32(b, 8), u32(b, 12),
                        u32(b, 16), b[20], b[21], b[22], u16(b, 24),
                        b[32:40], b[40:48]))
    pred_at = lab['pred_v'] - 0x2000
    pred = [u32(prog.system, pred_at + 4 * i) for i in range(NOPS)]
    return Results(ops_of(prog), recs, u32(main, lab['g_bps']),
                   u32(main, lab['g_vbl']), main[lab['g_verr']],
                   u32(main, lab['g_w10']), main[lab['g_wbad']],
                   u32(main, lab['g_mhz']), main[lab['g_runs']],
                   main[lab['g_done']], pred,
                   bytes(main[lab['g_tts']:lab['g_tts'] + 8]),
                   u32(main, lab['g_time']), main[lab['g_terr']],
                   u32(main, lab['g_tms']), main[lab['g_amem']])


def figures(op: Op, d: int, bps: int) -> Tuple[int, int]:
    """calib.s calc_op: (ns an operation, ns a byte)."""
    num = (d * bps) & ((1 << 64) - 1)
    den = (op.n * op.k * 1000) & ((1 << 64) - 1)
    v = r4(divr(num, den))
    vb = 0
    if op.b:
        vb = r4(divr(num, (den * op.b) & ((1 << 64) - 1)))
    return v, vb


def globals_of(res: Results) -> Tuple[int, int, int]:
    """calib.s calc_globals: (MHz x 100, the window x 10, bad)."""
    reg = res.recs[OP_REG]
    mhz = divr(res.ops[OP_REG].n * UC_REG * 10 ** 8, reg.d * res.bps) \
        & 0xFFFFFFFF
    ds, dw = res.recs[OP_SPIN].d, res.recs[OP_WIN].d
    ns, nw = res.ops[OP_SPIN].n, res.ops[OP_WIN].n
    t = dw * ns - ds * nw
    if t < 0 or t - nw * ns < 0:
        return mhz, 0, 0
    t -= nw * ns
    x = UC_SPIN * ns - ds
    if x < 0 or x * nw == 0:
        return mhz, 0, 1
    return mhz, divr(10 * UC_SPIN * t, x * nw) & 0xFFFFFFFF, 0


def fix(value: int, wid: int) -> str:
    """put_fix: thousandths as d.ddd, right-aligned in wid."""
    digits = '%010d' % value
    i = 0
    while i < 6 and digits[i] == '0':
        i += 1
    s = digits[i:7] + '.' + digits[7:]
    return ' ' * max(0, wid - len(s)) + s


def integer(value: int) -> str:
    digits = '%010d' % value
    i = 0
    while i < 9 and digits[i] == '0':
        i += 1
    return digits[i:]


def window_text(w10: int, wbad: int) -> str:
    """show_window: 512, 32, NONE or the window in whole cycles."""
    if wbad:
        return '?'
    if not w10 >> 16:
        if 4800 <= w10 < 5401:
            return '512'
        if 240 <= w10 < 441:
            return '32'
        if w10 < 50:
            return 'NONE'
    return integer(((w10 + 5) & 0xFFFFFFFF) // 10)


class Grid:
    """The 80-column text screen as calib.s's put_char writes it."""

    def __init__(self) -> None:
        self.grid = [[' '] * 80 for _ in range(24)]
        self.over: List[Tuple[int, int]] = []

    def put(self, row: int, col: int, text: str) -> int:
        for ch in text:
            if col >= 80:
                self.over.append((row, col))
            else:
                self.grid[row][col] = ch
            col += 1
        return col

    def op(self, res: 'Results', i: int, row: int, col: int) -> None:
        """show_op's line of operation i at row, col."""
        op, rec = res.ops[i], res.recs[i]
        col = self.put(row, col, '%-8s' % op.name)
        if rec.err:
            col = self.put(row, col, '      ERR       ')
        else:
            col = self.put(row, col, fix(rec.v, 9))
            col = self.put(row, col, fix(rec.vb, 7) if rec.vb else ' ' * 7)
        p = res.pred[i]
        self.put(row, col, fix(p, 10) if p else ' ' * 9 + '-')

    def rows(self) -> List[str]:
        if self.over:
            raise CalibError('the screen passes column 79 at %s'
                             % self.over[:3])
        return [''.join(r) for r in self.grid]


COLS = 'OP          US/OP   US/B A2VM F121'


def screen_expected(res: Results) -> List[str]:
    """calib.s show (text page 1), rendered by the host from the
    results."""
    g = Grid()
    put = g.put
    video = 'PAL' if res.bps == BPS['PAL'] else 'NTSC'
    head = ('CALIB ' + video + ' ' + integer(res.vbl) + '  WIN ' +
            window_text(res.w10, res.wbad) + '  CPU ' +
            fix((res.mhz * 10) & 0xFFFFFFFF, 0) + ' MHZ  TIME ' +
            ('?' if res.terr else fix(res.tms, 0)) + ' S  RUN ' +
            integer(res.runs) + '  SPACE: MORE')
    put(0, 0, head)
    put(1, 0, COLS)
    put(1, 40, COLS)
    for i in range(NOPS1):
        g.op(res, i, *((i + 2, 0) if i < 22 else (i - 20, 40)))
    return g.rows()


def screen2_expected(res: Results) -> List[str]:
    """calib.s show2 (text page 2): the PRIVATE lines, PR2 left and PR6
    right on rows 2-5, the legend on rows 7-10, row 12 when the probe found
    no memory API."""
    g = Grid()
    g.put(0, 0, PAGE2_HEAD)
    g.put(1, 0, COLS)
    g.put(1, 40, COLS)
    for i in range(OP_PR, NOPS):
        j = i - OP_PR
        g.op(res, i, 2 + j % 4, 0 if j < 4 else 40)
    for j, text in enumerate(PAGE2_LEGEND):
        g.put(7 + j, 0, text)
    if res.amem:
        g.put(12, 0, PAGE2_NOAMEM)
    return g.rows()


def screen_of(r: Run, page: int = 1) -> List[str]:
    """Text page 1 or 2 (80 columns: the even ones in aux)."""
    main, aux = r.image[(0, 0)], r.image[(1, 0)]
    rows = []
    for row in range(24):
        base = 0x400 * page + (row % 8) * 0x80 + (row // 8) * 0x28
        line = []
        for c in range(80):
            b = (aux if c % 2 == 0 else main)[base + c // 2] & 0x7F
            line.append(chr(b) if 0x20 <= b < 0x60 else '?')
        rows.append(''.join(line))
    return rows


def measurements(prog: Program, r: Run) -> List[Dict[str, Any]]:
    """The PC log cut into measurements: m_go (op, count), the start's
    read (its clock: t_bok, once VIA-B's read held), the units, m_end, the
    end's read (t_bok)."""
    lab = prog.labels
    go, call, end, bok = lab['m_go'], lab['m_call'], lab['m_end'], \
        lab['t_bok']
    out: List[Dict[str, Any]] = []
    cur = None
    ending = None
    for clock, pc, b in r.pclog:
        if pc == go:
            if cur is not None or ending is not None:
                raise CalibError('m_go inside a measurement')
            cur = {'op': b[0], 'count': b[1] | b[2] << 8, 'calls': 0,
                   'start': None}
        elif pc == bok:
            if cur is not None and cur['start'] is None:
                cur['start'] = clock
            elif ending is not None:
                ending['end'] = clock
                out.append(ending)
                ending = None
        elif pc == call:
            if cur is None or cur['start'] is None:
                raise CalibError('a unit called outside a measurement')
            cur['calls'] += 1
        elif pc == end:
            if cur is None:
                raise CalibError('m_end outside a measurement')
            ending, cur = cur, None
    return out


def amem_expected(ops: Sequence[Op]) -> Tuple[int, int]:
    """The memory API's requests and completed descriptors in one run of
    the list: the probe's STATUS; for each PRIVATE line two setups' copies
    (E(n), E(2n)) and 3n units of k requests of one descriptor."""
    requests = 1
    done = 0
    for op in ops[OP_PR:]:
        requests += 2 + 3 * op.n * op.k
        done += 2 + 3 * op.n * op.k
    return requests, done


def check(prog: Program, r: Run, parts: Optional[Parts] = None,
          pred: Optional[Sequence[int]] = None) -> List[str]:
    """Every problem of a run (the module docstring)."""
    out = []
    lab = prog.labels
    end = r.state.get('end')
    pc = r.state.get('cpu', {}).get('pc', r.state.get('pc'))
    if end != 'stop-pc' or pc != lab['done']:
        return ['the run ended %s at %s, not at the screen (done $%04X)'
                % (end, pc, lab['done'])]
    res = results(prog, r)
    if not res.done:
        out.append('g_done is 0')
    if res.verr:
        out.append('the frame\'s measure: the timers disagree')
    video = 'PAL' if res.vbl >= PAL_CUT else 'NTSC'
    if res.bps != BPS[video]:
        out.append('a bus cycle of %d ps for %s' % (res.bps, video))
    meas = measurements(prog, r) if r.pclog else []
    if r.pclog and len(meas) != 2 * NOPS:
        out.append('%d measurements in the PC log, not %d'
                   % (len(meas), 2 * NOPS))
    for i, (op, rec) in enumerate(zip(res.ops, res.recs)):
        tag = '%s (%d)' % (op.name, i)
        if rec.err:
            out.append('%s: error flags %d' % (tag, rec.err))
        if rec.n != op.n:
            out.append('%s: the arithmetic used n = %d, the table %d'
                       % (tag, rec.n, op.n))
        for which, ts, e in (('E(n)', rec.ts1, rec.e1),
                             ('E(2n)', rec.ts2, rec.e2)):
            he, _, bad = elapsed(ts)
            if he != e or bad:
                out.append('%s: %s is %d, the host computes %d from the '
                           'timer reads%s' % (tag, which, e, he,
                                              ' (bad)' if bad else ''))
        if rec.d != (rec.e2 - rec.e1) & 0xFFFFFFFF or not \
                0 < rec.d < 0x80000000:
            out.append('%s: D %d from E %d, %d' % (tag, rec.d, rec.e1,
                                                   rec.e2))
        v, vb = figures(op, rec.d, res.bps)
        if (v, vb) != (rec.v, rec.vb):
            out.append('%s: figures %d, %d; the host computes %d, %d'
                       % (tag, rec.v, rec.vb, v, vb))
        if op.mode and not 0xD000 <= op.unit:
            out.append('%s: a unit in a window outside the card' % tag)
        if meas:
            for j, (m, want, e) in enumerate(
                    ((meas[2 * i], rec.n, rec.e1),
                     (meas[2 * i + 1], 2 * rec.n, rec.e2))):
                if m['op'] != i:
                    out.append('%s: measurement %d is of operation %d'
                               % (tag, j + 1, m['op']))
                if m['count'] != want or m['calls'] != want:
                    out.append('%s: measurement %d ran %d units (count %d), '
                               'the arithmetic assumed %d'
                               % (tag, j + 1, m['calls'], m['count'], want))
                if r.bus_per_clock != 1.0:
                    ce = (m['end'] - m['start']) * r.bus_per_clock
                    if abs(ce - e) > CLOCK_SLACK:
                        out.append('%s: E %d, a2vm\'s clock %.1f bus cycles'
                                   % (tag, e, ce))
    te, _, tbad = elapsed(res.tts)
    if (te, tbad) != (res.time, res.terr) or res.terr:
        out.append('the run\'s time: E %d (%d), the host computes %d (%d)'
                   % (res.time, res.terr, te, tbad))
    if res.tms != r4(divr(res.time * res.bps, 10 ** 9)):
        out.append('the run\'s time: %d ms from E %d' % (res.tms, res.time))
    mhz, w10, wbad = globals_of(res)
    if (mhz, w10, wbad) != (res.mhz, res.w10, res.wbad):
        out.append('globals: MHz %d, window %d (%d); the host computes '
                   '%d, %d (%d)' % (res.mhz, res.w10, res.wbad, mhz, w10,
                                    wbad))
    if pred is not None and list(res.pred) != list(pred):
        out.append('the program\'s predictions are not the given ones')
    for page, render in ((1, screen_expected), (2, screen2_expected)):
        try:
            want = render(res)
            have = screen_of(r, page)
            for row, (a, b) in enumerate(zip(have, want)):
                if a != b:
                    out.append('screen %d row %d: %r, expected %r'
                               % (page, row, a.rstrip(), b.rstrip()))
        except CalibError as e:
            out.append(str(e))
    if res.amem:
        out.append('the program found no memory API (probe %d)' % res.amem)
    amem = r.state.get('amem') or {}
    want_rq, want_done = amem_expected(res.ops)
    if (amem.get('requests'), amem.get('completed')) != (want_rq, want_done):
        out.append('the memory API ran %s requests, %s descriptors; the '
                   'list sends %d, %d' % (amem.get('requests'),
                                          amem.get('completed'), want_rq,
                                          want_done))
    main = r.image[(0, 0)]
    if bytes(main[0x2000:0x2000 + len(prog.system)]) != prog.system:
        out.append('main $2000 no longer holds the program after the '
                   'PRIVATE copies')
    rws = r.image.get((1, RWS))
    if rws is None or bytes(rws[0x2000:0xA000]) != bytes(main[0x2000:0xA000]):
        out.append('bank %d $2000-$9FFF differs from main\'s' % RWS)
    if parts is not None:
        lc1, lc = r.image[(3, 0)], r.image[(2, 0)]
        c = parts.consts
        if bytes(lc1[c['FAR_LO']:c['FAR_LO'] + len(parts.far)]) != parts.far:
            out.append('the card\'s far area is not the play build\'s')
        if bytes(lc[c['KERN_LO']:c['KERN_LO'] + len(parts.kern)]) != \
                parts.kern:
            out.append('far_gcopy is not the play build\'s')
        page1 = bytearray(r.image[(0, 0)][c['PW_GO']:c['PW_GO'] +
                                          len(parts.pw)])
        want = bytearray(parts.pw)
        byte = c['PW_GO'] + parts.pw.index(bytes([0xB9]), 3) - c['PW_GO']
        for a in (c['PW_ON'], c['PW_OFF']):     # pw_get, pw_put's patches
            page1[a - c['PW_GO']] = want[a - c['PW_GO']] = 0
        for a in (byte + 1, byte + 2, byte + 4, byte + 5):  # pw_src, pw_dst
            page1[a] = want[a] = 0
        if page1 != want:
            out.append('page 1\'s window is not gobj.s\'s')
    return out


def core_cycles(prog: Program, work: Path) -> Dict[str, int]:
    """The nominal cycles of one unit of REG and SPIN, the driver's loop
    included: a2vm's core cycles between two unit calls, untimed."""
    r = run(prog, 'f121', work, timed=False, pclog=True, seconds=20)
    meas = measurements(prog, r)
    out = {}
    for name, op in (('REG', OP_REG), ('SPIN', OP_SPIN)):
        m = [x for x in meas if x['op'] == op][0]
        calls = [c for c, pc, _ in r.pclog
                 if pc == prog.labels['m_call'] and m['start'] <= c <=
                 m['end']]
        steps: Dict[int, int] = {}
        for a, b in zip(calls, calls[1:]):
            steps[b - a] = steps.get(b - a, 0) + 1
        # the unit's own; once in 256 the driver's high byte (+4)
        out[name] = max(steps, key=lambda k: steps[k])
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def us(ns: int) -> str:
    return '%.3f' % (ns / 1000.0)


def pct(model: int, card: int) -> str:
    return '%+.1f%%' % (100.0 * (model / card - 1))


def table_rows(runs: Dict[str, Results]) -> List[str]:
    f121 = runs['f121']
    rows = ['| # | Line | What it measures | n | Card us/op | Card us/byte | '
            'a2vm f121 us/op | against the card | before %s us/op | '
            'against the card | fastpath us/op |' % CARD_DATE,
            '| --: | --- | --- | --: | --: | --: | --: | --: | --: | --: '
            '| --: |']
    for i, op in enumerate(f121.ops):
        a = f121.recs[i]
        fp = runs['fastpath'].recs[i] if 'fastpath' in runs else None
        pre = runs['f121pre'].recs[i] if 'f121pre' in runs else None
        card = CARD.get(op.name)
        rows.append('| %d | `%s` | %s | %d | %s | %s | %s | %s | %s | %s '
                    '| %s |' % (
                        i + 1, op.name, WHAT.get(op.name, ''), op.n,
                        us(card) if card else '',
                        '%.3f' % (card / 1000.0 / op.b)
                        if card and op.b else '',
                        us(a.v), pct(a.v, card) if card else '',
                        us(pre.v) if pre else '',
                        pct(pre.v, card) if pre and card else '',
                        us(fp.v) if fp else ''))
    return rows


def card_fit(runs: Dict[str, Results]) -> Tuple[float, str, int, float,
                                                 str]:
    """f121's largest difference from the card (%, the line), its lines
    within 1%, and the largest difference of the model before the
    correction (%, the line)."""
    f121 = runs['f121']
    devs = [(abs(r.v / CARD[op.name] - 1) * 100, op.name)
            for op, r in zip(f121.ops, f121.recs) if op.name in CARD]
    worst = max(devs)
    pre = (max((abs(r.v / CARD[op.name] - 1) * 100, op.name)
               for op, r in zip(f121.ops, runs['f121pre'].recs)
               if op.name in CARD)
           if 'f121pre' in runs else (0.0, '?'))
    return (worst[0], worst[1], sum(1 for d, _ in devs if d <= 1.0),
            pre[0], pre[1])


def w512_moves(runs: Dict[str, Results]) -> Tuple[int, float, int]:
    """The lines but WIN with the window of 512 against f121's: the
    largest change of D (bus cycles, % of D), the figures that change."""
    a, b = runs['f121'].recs, runs['f121w512'].recs
    others = [i for i in range(NOPS) if i != OP_WIN]
    most = max(abs(b[i].d - a[i].d) for i in others)
    pct = max(100.0 * abs(b[i].d - a[i].d) / a[i].d for i in others)
    return most, pct, sum(1 for i in others if a[i].v != b[i].v)


def report(runs: Dict[str, Results], disk: Path, image: bytes,
           seconds: Dict[str, float]) -> str:
    f121 = runs['f121']
    sha = hashlib.sha1(image).hexdigest()
    mhz = f121.mhz / 100.0
    lines = [
        '# CALIB.hdv: the card\'s per-operation costs',
        '',
        'Written by `tools/native/calibdisk.py --doc` (docs/SPEED.md 5: '
        'the card\'s TIC row fell 9.6 ms where a2vm predicted 24.1 after '
        'speed wave 2, so a2vm\'s costs of the tic phase\'s RamWorks work '
        'are checked against the card before wave 3).',
        '',
        '**The card** (the owner\'s photo, %s, PAL //e, WIN 32, the disk '
        'of SHA-1 `%s`, whose A2VM column held the model before the '
        'correction): CPU %s MHz, TIME %s s. Its figures are the Card '
        'columns below. They corrected a2vm\'s cost model the same day '
        '(**The fit**, below): a2vm f121 now comes within %.1f%% of the '
        'card on every line it measured (%s the farthest), %d of the %d '
        'within 1%%; before, up to %.1f%% (%s). The memory API\'s PRIVATE '
        'lines (45-52, page 2) came after that photo: they have no card '
        'figures yet.' % ((CARD_DATE, CARD_DISK[:8], CARD_MHZ, CARD_TIME) +
                          card_fit(runs)[:3] + (len(CARD),) +
                          card_fit(runs)[3:]),
        '',
        '**The disk:** `build/native/CALIB.hdv`, %d bytes, SHA-1 `%s`, '
        'with the corrected model\'s figures in its A2VM column. '
        'Boot it on the Appletini (PAL //e, TURBO, the Phasor in slot 4 '
        'and RamWorks on, as for DOOM.hdv); it shows "CALIB: MEASURING", '
        'runs the %d lines once, then shows the first 44 (text page 1); '
        'SPACE shows the memory API\'s 8 (text page 2) and SPACE again page '
        '1; R runs them all again, CTRL-RESET reboots (the program '
        'overwrites ProDOS\'s card). The run takes %s s on a2vm f121 with '
        'the DOOM profile\'s window of 32 and %s s with the default window '
        'of 512 (TIME in the header, measured by the program itself; the '
        'card took %s s for the 44 lines of the earlier disk). A photo of '
        'each page gives the card\'s columns.' % (
            len(image), sha, NOPS, fix(runs['f121'].tms, 0),
            fix(runs['f121w512'].tms, 0) if 'f121w512' in runs else '?',
            CARD_TIME),
        '',
        '**The screen** (80 columns): row 0 `%s` (the video '
        'standard and its frame in bus cycles, the slot-4 window, REG\'s '
        'nominal 65C02 cycles a second, the run\'s time, the runs since the '
        'boot, the key to page 2); row 1 the heads; rows 2-23 the first '
        '44 lines, 22 a side: the name, the card\'s us an operation, its us '
        'a byte (where an operation moves bytes), a2vm f121\'s us an '
        'operation. Page 2 (SPACE): row 0 `%s`, row 1 the heads, rows 2-5 '
        'the PRIVATE lines (PR2 left, PR6 right), rows 7-10 a legend, row '
        '12 `%s` when the program found no memory API in slot 7. ERR in '
        'place of the figures: the two timers disagreed or D was not '
        'positive, or (a PRIVATE line) there is no memory API or a request '
        'was refused or got no reply.'
        % (screen_expected(f121)[0].rstrip(), PAGE2_HEAD, PAGE2_NOAMEM),
        '',
        '## How it measures',
        '',
        '- **The clock.** Timer 1 of the Phasor\'s VIA-B, free-running with '
        'the latch `$FFFE` (a period of exactly 65,536 bus cycles: 1,015,625 '
        'a second on PAL, 1,020,484 on NTSC, told apart by one frame between '
        'two blankings of `$C019`, the figure after PAL in the header). It '
        'is '
        'read at the start and the end of each measurement only: the low '
        'byte, the high byte, the low byte again (a read whose low bytes '
        'wrapped is taken again). VIA-A\'s timer 1 runs beside it with the '
        'latch `$FEFE` (65,280 cycles): the difference of the two elapsed '
        'counts, 256 a VIA-B wrap, gives the wraps, so a measurement may run '
        '16 s; a difference off a multiple of 256 by more than 24 marks it '
        'ERR.',
        '- **The reads cancel.** Each line is measured with n and with 2n '
        'repetitions of its unit in the same loop (`measure` in the card); '
        'the figure is (E(2n) - E(n)) / n, so the timer reads and the slot-4 '
        'window they open (512 CPU cycles at 1 MHz by default, 32 with the '
        'DOOM profile) cancel exactly. n is chosen so that E(n) is about '
        '55,000 bus cycles on a2vm f121: the reads\' window is under 1% of '
        'each measurement even before it cancels. Interrupts are masked.',
        '- **The game\'s code.** far_get, far_put and far_pload are the '
        'bytes of the card\'s far area (`$DC00-$DFFF` of bank 1) and '
        'far_gcopy the kernel\'s (`$FFD5`), as the play build puts them in '
        'DOOM.hdv\'s LC.BIN; the object API\'s window is gobj.s\'s `pw_go`, '
        'copied from the tic image into page 1 as go_reset does. They run at '
        'the game\'s addresses: far_gcopy, far_pload and the window are '
        'called from main code as the game calls them (gr_load\'s FA_* and Y '
        'for far_gcopy); far_get and far_put are the units themselves, '
        'called by the driver\'s `jsr` in the card (the game calls them from '
        'main code). `calibdisk.py` checks '
        'the bytes against DOOM.hdv and against the card and page 1 after '
        'the run.',
        '- **The units.** A line\'s unit is called by the driver\'s loop '
        '(`jsr`, a 16-bit count: 26 cycles with the call); the figure is '
        'per operation: per byte for the memory loops, per call for the '
        'routines, with "us/byte" the call over its bytes. The driver\'s '
        'loop and the loops that read or write another bank run in the '
        'card, as far.s\'s do; the setups (FA_*, the descriptors) run before '
        'the timing.',
        '- **The header.** WIN: the slot-4 window from SPIN and WIN (the '
        'T test of the music disk, with the timers instead of frame '
        'counts), W = (t_WIN - t_SPIN - 1) / (1 - t_SPIN / 837) CPU cycles '
        '(the read\'s own bus cycle aside, the window\'s W cycles at 1 MHz '
        'less the time TURBO would have taken them), shown as 512 '
        '(480-540), 32 (24-44), NONE (below 5) or the whole cycles; CPU: '
        'REG\'s nominal 65C02 cycles a second (1313 a unit, checked on '
        'a2vm\'s core; TURBO shows tens of MHz, a //e at 1 MHz about 1).',
        '- **The memory API.** The PRIVATE lines time what the frame '
        'slots will do (docs/MEMORY_MAP.md rule 3: CPU stores into main '
        '`$2000-$5FFF` are video writes, so a group of code is put there by '
        'one memory-API request): each unit sends one request (eight for '
        '8X2K) of one descriptor, COPY with the PRIVATE flag from RamWorks '
        'bank 17 to main, through slot 7\'s raw FIFO as '
        'appletini-one\'s README_MEMORY_API.md section 7 specifies and as '
        'lload.s\'s am_send sends one: `$CFFF` and `$C700` read, the '
        'request\'s 36 bytes (the CONTROL command, its nine parameter '
        'bytes, the list\'s length, its header, the descriptor) written to '
        '`$CFF0`, `$02` to `$CFF1`, `$CFF1` polled, the result read from '
        '`$CFF0` and popped at `$CFF2`, `$CFFF` read; the requests are '
        'built before the timing (the game\'s are built once too). The '
        'units and the transport run in the card. Main `$2000-$9FFF` holds '
        'the program itself, so each setup first copies main\'s 16 KB at '
        'the destination into bank 17 (one untimed request): the timed '
        'copies rewrite main with the bytes it holds, and `calibdisk.py` '
        'checks after the run that main still holds the program and bank '
        '17 the same bytes, and that a2vm\'s memory API ran every request '
        'the list sends (%d in a run). At the start a STATUS request finds '
        'the API (as pl_boot.s does); without it the PRIVATE lines show '
        'ERR and page 2 says why.' % amem_expected(f121.ops)[0],
        '- **Noise and steps.** A timer read whose low bytes wrapped is '
        'retaken about 15 bus cycles later, which moves that E by as much '
        '(0.03%); a2vm\'s run shows its E equal to its own clock between '
        'the reads that held. A unit bound to the bus (a soft switch, a '
        'slot-4 read, a far window) takes a whole number of bus cycles or '
        'alternates between two, so its figure moves by up to a bus cycle '
        '(0.985 us) with where its code falls against the bus: compare the '
        'card and a2vm line by line, not the SW lines among themselves '
        'below a bus cycle.',
        '',
        '## The lines',
        '',
        'a2vm: `%s` (`f121`, the game\'s profile in `playdisk.py`: the '
        'DOOM profile\'s window of 32; "before": `%s`, the model before '
        'the card corrected it) and `%s`, `--via-timers`, the exact '
        'core, `--cost-timed`. Header on a2vm f121: %s, frame %d bus '
        'cycles, WIN %s (%.1f cycles), CPU %.2f MHz; with the default '
        'window of 512 (`%s`) WIN %s (%.1f) and the WIN line %s us; the '
        'other lines\' D move by %d bus cycles at most (%.3f%%: a timer '
        'read retaken, or where the code falls against the bus), which '
        'changes the third decimal of %d of them.' % ((
            PROFILES['f121'], PROFILES['f121pre'], PROFILES['fastpath'],
            'PAL' if f121.bps == BPS['PAL'] else 'NTSC', f121.vbl,
            window_text(f121.w10, f121.wbad), f121.w10 / 10.0, mhz,
            PROFILES['f121w512'],
            window_text(runs['f121w512'].w10, runs['f121w512'].wbad),
            runs['f121w512'].w10 / 10.0,
            us(runs['f121w512'].recs[OP_WIN].v)) + w512_moves(runs)),
        '',
    ]
    lines += table_rows(runs)
    lines += [
        '',
        'The card\'s us/byte is its us/op over the bytes (the screen\'s '
        'quotient). The screen shows the card\'s us/op, us/byte and a2vm '
        'f121\'s us/op side by side; on a2vm f121 it reads:',
        '',
        '```',
    ] + [row.rstrip() for row in screen_expected(f121)] + [
        '```',
        '',
    ] + private_section(runs) + [
        '## The fit (%s)' % CARD_DATE,
        '',
        'Before the card\'s figures, every line that runs code between '
        'its memory accesses was 7-39% faster on a2vm than on the card '
        '(REG -39%, MAIN WR -30%, RW WSEQ -33%, GC -17 to -20%), and the '
        'lines bound to the bus matched exactly (RW S64, RW WS64, GET RW, '
        'SW C073, SHR), except four families: the RAMRD, RAMWRT and ALTZP '
        'switches (-13%), far_put\'s short calls (PUT RW 4 -13%, PUT AX 4 '
        '-11%) and the object API\'s mobj fetch (MO GET -18%, of which -8% '
        'remained once the CPU was right). One new parameter and four '
        'corrected readings of the RTL account for all of it (a fifth, '
        '`slow_done`, follows from the same registers; no line can tell '
        'it); each '
        'parameter\'s source in `tools/a2vm/costs/appletini.json` names the '
        'lines and the card\'s figures. The variant `precal` keeps the model '
        'before them ("before" above; `playtime.py --profile f121-precal`).',
        '',
        '| Parameter | Before | Now | Why (the RTL; the card) | Lines it '
        'moves |',
        '| --- | --: | --: | --- | --- |',
        '| `d2_replay` (new) | 0 | 1 | The virtual Disk II in slot 6 is '
        'active on the card (`disk2.slot6.enabled` on; the firmware\'s '
        'default is off) and replays, one a clock, the 65C02 cycles each '
        'TURBO step stands for; until it has, `d2_time_ready` holds the '
        'core\'s next step (`disk2_card.sv:374-412`, `apple_top.sv:2065-2068`, '
        '`vtw_core_top.sv:1524`, `:1907`). A step that omitted k dummy reads '
        'delays the next one k + 1 clocks: the TURBO core\'s free dummy reads '
        'cost 2 clocks each (1 for the second of a pair, as in `rts`). REG\'s '
        '`dey / bne`, 3 accesses and 2 such steps: 10.3 clocks on the card, '
        '6.3 before | every line with dummy reads: REG, MAIN, AUX, RW HIT, '
        'RW SEQ, RW WHIT, RW WSEQ, GC, PLOAD, SPIN, WIN, GET AX, PUT, MO, LN, '
        'SW NONE |',
        '| `bus_drive_tap` | 8 | 9 | drive_en is `addr_pipe[8]` registered '
        '(`apple_bus_wrapper.sv:622`): the engine launches a sync cycle at '
        'tap 9 (`vtw_bus_engine.sv:810`, `:848-858`) | SW RAMRD, SW RAMWR, '
        'SW ALTZP, PUT RW 4, PUT RW24, PUT AX 4 |',
        '| `bus_done` | 2 | 4 | data_en is registered from the data snap '
        '(`apple_bus_wrapper.sv:657-659`), resp_valid_q from data_en '
        '(`vtw_bus_engine.sv:726`, `:764-767`), then X_BUS and X_BUS_DONE '
        '(`vtw_core_top.sv:2125-2159`). With `bus_drive_tap` 9 a switch write '
        'right after another\'s response misses the next Apple cycle: the '
        'switch lines take 5.0 Apple cycles on the card, 4.33 before; one '
        'write (SW C073) had slack and was already right | as above |',
        '| `admit_offset` | 6 | 30 | addr_en is `TAP_ADDR_SNAP` 25 '
        '(`apple_bus_wrapper.sv:101`, `:625-639`), not tap 3; the PSRAM\'s '
        'background window opens three edges later (`psram_simple.sv:313-325`) '
        '| GC RW 1 (+1.5% with 6, +0.4% with 30) |',
        '| `admit_window` | 40 | 37 | `ADMIT_WINDOW_TAPS` 40 counts from '
        'addr_en, not from the arming (`psram_simple.sv:239`, `:318-328`): '
        'the last admission is at tap 66 | MO GET: the third line miss of '
        'each descriptor comes 43 clocks into the window and waits a cycle '
        '(41.353 us with 40, 45.292 with 37, the card 45.038) |',
        '| `slow_done` | 1 | 3 | A cycle paced at 1 MHz ends on the third '
        'clock after the data snap: data_en and `pace_tick_pending_q` are '
        'registered (`apple_bus_wrapper.sv:657-659`, `vtw_core_top.sv:1850-1856`, '
        '`:1514`), as for `bus_done` | WIN by 0.011 us; the slot-4 window\'s '
        'tests (`test_sound_player65`) |',
        '',
        'The other families followed from these, with no parameter of '
        'their own: main and aux writes (`sta abs,y` has a dummy read, and '
        'so `iny` and the taken `bne`: 3 a byte); RamWorks sequential reads '
        'and writes, whose line misses fall one admission window later once '
        'the loop takes its real time (RW SEQ 2 Apple cycles a line, RW WSEQ '
        '3, as on the card, with every PSRAM parameter unchanged); far_gcopy '
        'and far_pload (their loops\' dummy reads, and the same windows). '
        'The SHR drain lines were right and stay right (the coalescer\'s '
        'scan, modelled from the RTL on 2026-09-30).',
        '',
        'The benchmark checks the fit on the game: on the corrected model '
        'the menu\'s BENCHMARK of both waves\' DOOM.hdv comes within 0.4% '
        'of the card\'s FPS and each of its five rows within 1.6% '
        '(docs/SPEED.md 5). With the virtual Disk II inactive (the variant '
        '`nod2`: `disk2.slot6.enabled=off`, or '
        '`vtw.disk2.acceleration.disabled=on`, in the DOOM profile), a2vm '
        'predicts wave 2\'s benchmark at 3.609 FPS against 3.004 as the card '
        'is set (+20%; docs/SPEED.md 5); not yet measured on the card.',
        '',
        '## Reading the card against a2vm',
        '',
        '- REG, MAIN RD and MAIN WR set the CPU\'s speed in fast memory; '
        'AUX RD and AUX WR the same through RAMRD and RAMWRT.',
        '- RW HIT and RW UHIT are the line cache\'s hits; RW SEQ against '
        'RW HIT gives a sequential miss (one every 8 bytes: 8 x the '
        'difference); RW S64 and RW S256 against RW UHIT give a random '
        'miss, and their difference any PSRAM row effect; RW WSEQ and '
        'RW WS64 the same for writes with dirty victims.',
        '- GC (far_gcopy) per page against RW SEQ gives the copy\'s cost '
        'beyond its reads; GET and PUT at 4, 24 and 96 bytes split into a '
        'fixed cost a call (the window: two switches, two `$C073` writes and '
        'the cache refills) and a cost a byte.',
        '- MO GET, MO PUT and LN GET are the object API\'s misses as the '
        'tic phase runs them; SW lines less SW NONE are each switch\'s cost '
        'with the refill of the main code after it.',
        '- SHR SEQ against the known card figure (0.985 us a byte, one '
        'Apple cycle) checks the drain of contiguous bytes; SHR COL the '
        'coalescer\'s page scan on a column (about 4 Apple cycles a byte).',
        '- PR2 and PR6 (page 2): the card\'s us/op is one request\'s '
        'whole cost as the game will pay it (the FIFO, the ARM\'s hold, '
        'the copy, the CPU\'s caches refilled after it). 2K and 16K give '
        'the fixed cost of a request and the cost of a byte (**The memory '
        'API\'s PRIVATE copy**, above); 256 checks the fixed cost; 8X2K '
        'against 2K checks that requests in a row cost no more than one '
        'alone, and 8X2K against 16K what splitting 16 KB into eight '
        'requests costs. PR2 against PR6: whether the colormap area costs '
        'more than other main memory (a2vm charges them alike).',
        '',
        '## Commands',
        '',
        '```',
        'python3 tools/native/calibdisk.py --doc     # gen, make, a2vm, '
        'the disk, this page',
        'python3 -m unittest test_calib              # from tests/: about '
        '20 s',
        '```',
        '',
    ]
    return '\n'.join(lines)


# ---------------------------------------------------------------------------

def pr_fit(res: Results, dest: str) -> Tuple[float, float]:
    """A request's fixed cost and a byte's cost (us) from the 2K and 16K
    lines to `dest` ('2' or '6')."""
    by = {op.name: rec.v for op, rec in zip(res.ops, res.recs)}
    small, big = by['PR%s 2K' % dest], by['PR%s 16K' % dest]
    byte = (big - small) / (16384 - 2048) / 1000.0
    return small / 1000.0 - 2048 * byte, byte


def private_section(runs: Dict[str, Results]) -> List[str]:
    """docs/results/calib.md's section on the PRIVATE lines."""
    f121 = runs['f121']
    by = {op.name: (op, rec) for op, rec in zip(f121.ops, f121.recs)}
    fixed, byte = pr_fit(f121, '2')
    fixed6, byte6 = pr_fit(f121, '6')
    out = [
        '## The memory API\'s PRIVATE copy (page 2)',
        '',
        'Lines 45-52 time the frame slots\' load before they are built: '
        'the tic phase\'s code paging cost about 138 ms of the card\'s '
        '332 ms benchmark frame, and putting pinned groups in main '
        '`$2000-$5FFF` (colormaps A and B, which only the replay reads) '
        'with one PRIVATE request at a group\'s first call in a frame, the '
        'colormaps\' pages restored after the tic phase, was simulated at '
        'about 28 ms. That estimate rests on a2vm\'s model of a request, '
        'which no card figure has checked yet; these lines are that check. '
        'On a2vm f121:',
        '',
        '| Line | Requests a unit | Bytes a request | n | a2vm f121 us a '
        'request | us a byte | fastpath us a request |',
        '| --- | --: | --: | --: | --: | --: | --: |',
    ]
    for name in PR_LINES:
        op, rec = by[name]
        fp = runs['fastpath'].recs[f121.ops.index(op)] \
            if 'fastpath' in runs else None
        out.append('| `%s` | %d | %d | %d | %s | %s | %s |' % (
            name, op.k, op.b, op.n, us(rec.v), us(rec.vb),
            us(fp.v) if fp else ''))
    eight = by['PR2 8X2K'][1].v
    whole = by['PR2 16K'][1].v
    out += [
        '',
        'a2vm\'s model of a request (`a2vm_cost_amem` in '
        '`tools/a2vm/cost.c`, the parameters `amem_*` and `axi_us` of '
        '`costs/appletini.json`): the request\'s bytes popped by the ARM, '
        'the hold (the mirror and the caches flushed), the copy in chunks '
        'of 504 bytes (a DMA read of the RamWorks bank, then AXI writes of '
        'main\'s shadow word by word), the release; the FIFO\'s own writes '
        'are served inside the fabric. From the 2K and 16K lines a request '
        'costs %.1f us plus %.4f us a byte into `$2000` (%.1f plus %.4f '
        'into `$6000`: a2vm charges main alike everywhere), so 16 KB is '
        '%.3f ms in one request and %.3f ms in eight (%+.1f%%). Read the '
        'card\'s photo of page 2 against these: its 2K and 16K give its '
        'own fixed cost and cost a byte, and the frame slots\' estimate '
        'scales with them.' % (fixed, byte, fixed6, byte6, whole / 1e6,
                               8 * eight / 1e6,
                               100.0 * (8 * eight / whole - 1)),
        '',
        'Page 2 on a2vm f121:',
        '',
        '```',
    ]
    rows = [row.rstrip() for row in screen2_expected(f121)]
    while rows and not rows[-1]:
        rows.pop()
    out += rows + [
        '```',
        '',
    ]
    return out


def build(play: Path = PLAY, out: Path = OUT, keep: Optional[Path] = None,
          profiles: Sequence[str] = ('fastpath', 'f121w512', 'f121pre'),
          jobs: int = 3,
          log=print) -> Tuple[bytes, Dict[str, Results], Dict[str, float]]:
    """The whole pipeline (the module docstring); raises CalibError with
    every problem found."""
    parts = play_parts(play)
    if DOOM_HDV.exists():
        bad = doom_problems(parts)
        if bad:
            raise CalibError('; '.join(bad))
    write_gen(parts)
    prog0 = make()
    base = keep or Path(tempfile.mkdtemp(prefix='tmp-calib-', dir=str(BUILD)))
    timed: Dict[str, float] = {}
    try:
        r0 = run(prog0, 'f121', base / 'pass1')
        bad = check(prog0, r0, parts)
        if bad:
            raise CalibError('pass 1: ' + '; '.join(bad[:8]))
        res0 = results(prog0, r0)
        pred = [rec.v for rec in res0.recs]
        write_gen(parts, pred)
        prog = make()
        image = write_disk(prog.system, out)
        log('%s: %d B, SHA-1 %s' % (out, len(image),
                                    hashlib.sha1(image).hexdigest()))
        names = ['f121'] + list(profiles)

        def one(name):
            r = run(prog, name, base / name)
            return name, r
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            done = list(pool.map(one, names))
        runs: Dict[str, Results] = {}
        problems = []
        for name, r in done:
            bad = check(prog, r, parts, pred)
            problems += ['%s: %s' % (name, b) for b in bad]
            runs[name] = results(prog, r)
            timed[name] = r.state.get('cycles', 0) / \
                (costs.parameters(PROFILES[name])['fabric_mhz'] * 1e6)
        a, b = res0.recs, runs['f121'].recs
        if [(x.e1, x.e2) for x in a] != [(x.e1, x.e2) for x in b]:
            problems.append('f121: the final disk\'s times differ from '
                            'pass 1\'s')
        if problems:
            raise CalibError('; '.join(problems[:10]))
        return image, runs, timed
    finally:
        if not keep:
            shutil.rmtree(str(base), ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--play', type=Path, default=PLAY)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--doc', action='store_true')
    parser.add_argument('--keep', type=Path)
    parser.add_argument('--jobs', type=int, default=3,
                        help='a2vm runs at once (default 3)')
    args = parser.parse_args(argv)
    if not (args.play / 'tic' / 'tic.core').exists() or not A2VM.exists():
        print('calibdisk: build/ lacks the play build or a2vm',
              file=sys.stderr)
        return 2
    try:
        image, runs, timed = build(args.play, args.out, args.keep,
                                   jobs=args.jobs)
    except CalibError as e:
        print('calibdisk: %s' % e, file=sys.stderr)
        return 1
    f121 = runs['f121']
    print('a2vm f121: %s, frame %d, WIN %s, CPU %.2f MHz, TIME %s s; '
          'WIN 512: TIME %s s' % (
              'PAL' if f121.bps == BPS['PAL'] else 'NTSC', f121.vbl,
              window_text(f121.w10, f121.wbad), f121.mhz / 100.0,
              fix(f121.tms, 0), fix(runs['f121w512'].tms, 0)))
    for i, op in enumerate(f121.ops):
        cols = ['%-8s n %5d' % (op.name, op.n)]
        for name in ('f121', 'fastpath'):
            rec = runs[name].recs[i]
            cols.append('%s %9s %7s' % (name, us(rec.v),
                                        us(rec.vb) if op.b else ''))
        print('  '.join(cols))
    if args.doc:
        DOC.parent.mkdir(parents=True, exist_ok=True)
        DOC.write_text(report(runs, args.out, image, timed))
        print('wrote %s' % DOC)
    return 0


if __name__ == '__main__':
    sys.exit(main())
