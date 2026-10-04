#!/usr/bin/env python3
"""DOOM.hdv, the game's boot disk (milestone 11, part plboot; docs/SCREENS.md
2.5, 4.5, 6.5; docs/m11-parts/plboot.md): DOOM.SYSTEM (src/native/pl_boot.s)
loads every bank file into RamWorks, checks every segment's CRC-32 in its
bank, installs the card images, gives up ProDOS and reaches the ready
state with the tic clock running.

Usage:  python3 tools/native/pldisk.py [--out FILE] [--check] [--planted]
                [--jobs N] [--no-build] [--json FILE]
        python3 tools/native/pldisk.py --cfg FILE      (the link's map)

The disk (a ProDOS 2.4.3 volume DOOM, written by the existing port's
disk writer demos/doom/tools/build_disk.py, as ldisk.py and musicdisk.py
do) holds, in this order:

  DOOM.SYSTEM  the boot (build/native/m11/plboot/plboot.boot, $2000-$2FFF)
  PRODOS
  CATALOG      the bank files' names (+0 their count, +16 a name of 16
               bytes each: length, name)
  CRCLIST      the count (a word), then 9 bytes an entry: bank, address,
               length, zlib's CRC-32 (bank 0: main memory), every segment
               of the bank files in the catalog's order, then LC.BIN's two
               halves as the boot stages them (main $6000, 16 KB each)
  LC.BIN       the card images, 16 KB each: the aux card's (milestone 8's
               trig tables, rtables.py's tables.img), then the main card's:
               bank 1 $D000-$DFFF and bank 2 $D000-$DFFF and the replay's
               $F900-$FEFF from milestone 8's card link (build rcard, read
               only: the quarter squares, the math, the far layer, the
               phase loader, the masked phase's card loops; the row blocks
               and the dispatcher; the replay's and the bucket pass's card
               parts), $E900-$F8FF and $FF00-$FFFF from this part's link
               (S2's player, pl_vbl and the effects' card part, the ready
               loop, the vectors); $E000-$E8FF is zero (the player's ring,
               lists and state, the clock, the voices, the 2D blocks, the
               effects' state and rings, the channels: all written at run
               time)
  TEXELS.n, PATCHES.n, MAPS.n, TABLES.n
               the level store (wadconv.py --store, read only)
  CODE.1       the code library: the load phase's image (milestone 9's
               lcard, bank LCODE), the render images (milestone 8's rcard:
               the front end's W in WCODE_BANK, the masked image in
               MCODE_BANK), the 2D images in their code banks
               (s2layout.image_banks(); IMAGE_BUILDS) and OVLW in bank 93
  RTABLES.1    milestone 8's constant tables in RamWorks (rtables.py's
               tables.img banks, the math's tables), as its runs lay them
               out (render_check.base_records)
  SONGS.1      the 13 songs (converted from the WAD now, musicdisk.songs)
               packed into banks 100-102, a directory first (SONG_DIR)
  SFX.1        part fxconv's SFX.1 as a bank file (bank 103 at $0200)
  GFX.1        part s2data's 2D store
  HUDTXT.1     part s2hud's message texts (bank 104 at SS_HUDMSG)

--check runs the disk on a2vm under its MLI trap, the memory API (--amem)
and the mouse card's VBL clock, with --cost-timed and the interrupt bounds
of docs/SCREENS.md 2.3, from a machine whose card holds a pattern (ProDOS's
card) and whose persistent places and zero page hold $A5:

  boot-f121, boot-fastpath   (the Doom profile, window 32): the boot
               reaches pl_ready; at bt_installed the card equals LC.BIN
               byte for byte, main $0200-$03EF, $0C00-$1FFF, $BF00-$BFFF
               and zero page $00-$17 (the pair $06-$07 with them) are 0;
               at the ready loop and 50 VBLs later PL_STATUS is PL_READY,
               every byte of every bank file is in its bank, the card is
               LC.BIN but at its run-time places, ProDOS's global page and
               the pair still 0, the key table is plkeys', the effect
               player on (FX_ON 1, FX_INVAL 1, FX_HOLD 0), the clock PAL
               and running: the tics equal the VBL count times the step
               over 65,536 (plclock's model) after 50 VBLs; the AY writes
               snd_probe's two alone; the boot's time reported, to the
               bank files read (loaded), their CRCs (checked), the card
               (installed) and the ready state
  boot-ntsc    the same at 60 Hz (f121's NTSC variant): pl_detect's NTSC,
               the step 38,229
  nomusic      --phasor-mb-only: the same ready state with the message, the
               effect player off (FX_ON 0) and no AY register written
  noamem, amemoff
               no --amem (slot 7 empty), --amem --amem-unavailable (the
               Appletini's ROM, its STATUS without the available bit): the
               same ready state with the message "NO MEMORY API: COPIES BY
               THE CPU" and the answer ($FF, $FE): the memory API is
               optional since 2026-10-03 (docs/PLAY.md 19; this disk's
               DOOM.SYSTEM has no patch to write, the play disk's does)
  nomouse, banks
               --no-mouse, --banks 64: the boot stops at bt_halt with
               PL_NOMOUSE, PL_BANKS (the first missing bank 64) in
               PL_STATUS and its message on the screen (without the
               Appletini's mouse card the clock is the Phasor's VIA-B
               timer 1, which a2vm has only with --via-timers: here
               neither, so no clock; docs/PLAY.md 20)

--planted builds each planted bug of PLANTED in a scratch copy (of
pl_boot.s, or of this file for the disk's table) and runs the checks it
must fail. Every run is bounded (bounded.run: time, file sizes) in a
directory of its own under build/, deleted after.
"""

import argparse
import importlib.util
import json
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from native import levelconv as LC, llayout as LL, lrun, lstore, \
    plkeys, rlayout as R, s2layout as S, s2run  # noqa: E402
from native import render_check as RC  # noqa: E402
from ref816 import bounded  # noqa: E402

BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
PART = M11 / 'plboot'
OUT = PART / 'DOOM.hdv'
RESULTS = PART / 'pldisk.json'
SOURCE = ROOT / 'src' / 'native'
SOUND65 = BUILD / 'sound65'
RCARD = RC.OBJ                  # milestone 8's rcard (read only)
LCARD = lrun.OBJ                # milestone 9's lcard (read only)
A2VM = lrun.A2VM
DOOM_TOOLS = ROOT.parent / 'doom' / 'tools'

VOLUME = 'DOOM'
SYSTEM = 'DOOM.SYSTEM'
BOOT_LO, BOOT_HI = 0x2000, 0x3400           # pl_boot.s BOOT_END
STAGE, HALF = 0x6000, 0x4000                # pl_boot.s STAGE, STAGE_SIZE
CAT_MAX, C_NAMES = 0x0100, 16               # pl_boot.s CATALOG
MAX_FILES = (CAT_MAX - C_NAMES) // 16
CRC_MAX = 0xBF00 - 0xAB00                   # pl_boot.s CRCBUF, CRC_MAX
ENTRY = 9
BANKS = 126
# the disk's stop (request PLBOOT-1, applied in wave 8)
PL_DISK = S.PL['DISK']
# the songs' directory (request PLBOOT-2, applied in wave 8): 3 bytes a
# song (bank, address) in mus.UPSTREAM_SONGS' order, at bank SONGS0 $0200
SONG_DIR = S.SONG_DIR
SONG_DIR_ENTRY = S.SONG_DIR_ENTRY
# STAND-IN (requests PLBOOT-3): the 2D images of the code library, as the
# parts built them, until the release images with the frame glue exist:
# image -> (part, build)
IMAGE_BUILDS = {'P2DW': ('s2stbar', 's2sb'), 'MENUW': ('s2menu2', 's2m2'),
                'AMAPW': ('s2amap', 'amw'), 'WIW': ('s2wi', 'wiw'),
                'FINW': ('s2fin', 'finw'), 'PALW': ('s2pal', 'palw')}
OVLW_BUILD = ('s2ovl', 'ovlw')
FX_NREGS = 11                   # fx.s NREGS: fx_want .. fx_wval, 11 each

PROFILES = ('f121+phasor+window32', 'fastpath+phasor+window32')
IRQ_BOUNDS = '00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF'  # SCREENS.md 2.3
LATER_VBLS = 50
BOOT_TIMEOUT = 900.0
STOP_TIMEOUT = 120.0
MAX_BYTES = 256 << 20
CYCLE_SECONDS = 20              # model seconds a run may take (the boot
                                #   about 5.5 and 50 VBLs)
JOBS = 2
POISON = 0xA5


class DiskError(Exception):
    pass


# ---------------------------------------------------------------------------
# The link (src/native/m11/plboot.mk)
# ---------------------------------------------------------------------------

def cfg_text() -> str:
    """ld65's map of the boot and the card's code, from s2layout's places
    (SCREENS.md 4.4): the boot at $2000, S2's ring, lists and state, S2's
    code at $E900, pl_vbl and the effects at FX_CODE, the ready loop in the
    platform's $FF00-$FFF9, the vectors."""
    card = {name: (lo, hi) for name, lo, hi in S.S2_CARD}
    ring = card['the song ring and its mirror']
    lists = card['the player\'s write lists']
    state = card['the player\'s state']
    code = card['S2\'s code and tables']
    plat = S.PLATFORM_CARD[1:]

    def area(name, lo, hi, rest):
        return '    %-6s start = $%04X, size = $%04X, %s;' % (
            name + ':', lo, hi - lo, rest)
    return '\n'.join([
        '# Generated by tools/native/pldisk.py --cfg (part plboot,',
        '# docs/m11-parts/plboot.md): DOOM.SYSTEM and the card. Do not edit.',
        'MEMORY {',
        area('SNDZP', S.ZP_IRQ[0], S.ZP_IRQ[1], 'type = rw, file = ""'),
        area('BOOT', BOOT_LO, BOOT_HI, 'file = "%O.boot", fill = yes'),
        area('RING', ring[0], ring[1], 'type = rw, file = ""'),
        area('LIST', lists[0], lists[1], 'type = rw, file = ""'),
        area('STATE', state[0], state[1], 'type = rw, file = ""'),
        area('SND', code[0], code[1], 'file = "%O.snd", fill = yes'),
        area('FXC', S.FX_CODE[0], S.FX_CODE[1], 'file = "%O.fxc", fill = yes'),
        area('PLAT', plat[0], plat[1], 'file = "%O.plat", fill = yes'),
        area('VEC', S.VECTORS[1], S.VECTORS[2], 'file = "%O.vec"'),
        '}',
        'SEGMENTS {',
        '    PLBOOT:    load = BOOT,  type = rw, define = yes;',
        '    S2CODE:    load = BOOT,  type = ro, define = yes;',
        '    S2RODATA:  load = BOOT,  type = ro, define = yes;',
        '    SNDBOOT:   load = BOOT,  type = ro, define = yes;',
        '    PLAMEM:    load = BOOT,  type = rw, define = yes;',
        '    PLMOUSE:   load = BOOT,  type = rw, define = yes;',
        '    SNDZP:     load = SNDZP, type = zp;',
        '    SNDRING:   load = RING,  type = bss, align = $100;',
        '    SNDLIST:   load = LIST,  type = bss;',
        '    SNDBSS:    load = STATE, type = bss;',
        '    SNDCODE:   load = SND,   type = ro, define = yes;',
        '    SNDRODATA: load = SND,   type = ro, define = yes;',
        '    FXCODE:    load = FXC,   type = ro, define = yes;',
        '    PLRES:     load = PLAT,  type = ro, define = yes;',
        '    VECTORS:   load = VEC,   type = ro;',
        '}', ''])


def tool(args, what: str, cwd=None) -> str:
    result = bounded.run(args, timeout=600, max_bytes=MAX_BYTES,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True, cwd=cwd)
    if result.returncode:
        raise DiskError('%s failed:\n%s' % (what, result.stdout))
    if 'arning' in result.stdout:
        raise DiskError('%s warns:\n%s' % (what, result.stdout))
    return result.stdout


def make(m11: Path = M11, src: Path = SOURCE) -> Path:
    """make -f m11.mk part P=plboot into m11/plboot, pl_boot.s from src."""
    tool(['make', '-s', '-C', str(SOURCE), '-f', 'm11.mk', 'part',
          'P=plboot', 'M11=%s' % m11, 'ROOT=%s' % ROOT,
          'PLBOOT_SRC=%s' % src], 'make part P=plboot')
    return m11 / 'plboot'


def have_tools() -> bool:
    return bool(shutil.which('ca65') and shutil.which('ld65') and
                shutil.which('make')) and A2VM.exists() and \
        all((SOUND65 / n).exists() for n in ('player.o', 'probe.o',
                                             'tables.inc'))


def missing(m11: Path = M11) -> List[str]:
    """What the disk needs and build/ lacks (empty: everything there)."""
    out = []
    if not (shutil.which('ca65') and shutil.which('ld65') and
            shutil.which('make')):
        out.append('cc65 and make on PATH')
    if not A2VM.exists():
        out.append('build/a2vm/a2vm (make -C tools/a2vm)')
    for n in ('player.o', 'probe.o', 'tables.inc'):
        if not (SOUND65 / n).exists():
            out.append('S2\'s %s (make -C src/sound)' % n)
            break
    if not (RCARD / 'rcard.map').exists() or \
            not (RC.TABLES / 'tables.img').exists():
        out.append('milestone 8\'s rcard and tables (render.mk, rtables.py)')
    if not (LCARD / 'lcard.map').exists() or \
            not (lstore.STORE / 'store.json').exists():
        out.append('milestone 9\'s lcard and store (level.mk, wadconv.py '
                   '--store)')
    needs = [m11 / part / ('%s.map' % name) for part, name in
             list(IMAGE_BUILDS.values()) + [OVLW_BUILD]]
    needs += [m11 / 'fxconv' / 'SFX.1', m11 / 's2data' / 'GFX.1',
              m11 / 's2hud' / 'HUDTXT.1']
    absent = [str(n.relative_to(ROOT)) for n in needs if not n.exists()]
    if absent:
        out.append('the parts\' builds (make -f src/native/m11.mk): %s'
                   % ', '.join(absent[:3]))
    sys.path.insert(0, str(TOOLS / 'sound'))
    from sound import musicdisk
    if not musicdisk.have_wad():
        out.append('the WAD (tools/fetch_upstream.py)')
    if not musicdisk.have_disk_tools():
        out.append('appletini-one\'s ProDOS (APPLETINI_ROOT)')
    return out


class Boot(NamedTuple):
    dir: Path
    labels: Dict[str, int]
    segments: Dict[str, Tuple[int, int]]

    def area(self, suffix: str) -> bytes:
        return (self.dir / ('plboot.%s' % suffix)).read_bytes()


def load_boot(part: Path = PART) -> Boot:
    b = RC.load_build(part, 'plboot')
    return Boot(part, b.labels, b.segments)


def sizes(boot: Boot) -> Dict[str, int]:
    """Bytes a segment of the link (0 when absent)."""
    out = {}
    for name in ('PLBOOT', 'S2CODE', 'S2RODATA', 'SNDBOOT', 'SNDCODE',
                 'SNDRODATA', 'FXCODE', 'PLRES'):
        lo, hi = boot.segments.get(name, (0, -1))
        out[name] = hi + 1 - lo
    return out


# ---------------------------------------------------------------------------
# The card images (LC.BIN)
# ---------------------------------------------------------------------------

def card_images(boot: Boot, rcard_obj: Path = RCARD) -> Tuple[bytes, bytes]:
    """(the aux card, the main card): 16 KB each, bank 1 $D000-$DFFF, bank 2
    $D000-$DFFF, $E000-$FFFF (pl_boot.s lc_put's order)."""
    rc = RC.load_build(rcard_obj, 'rcard')
    main = bytearray(HALF)
    squares = (RC.TABLES / 'math' / 'squares.bin').read_bytes()
    main[:len(squares)] = squares
    for name, part, base in (('MATHLC', 'lc1', 0xD800),
                             ('MATHFAR', 'far', 0xDC00),
                             ('RFAR', 'far', 0xDC00),
                             ('RLOAD', 'far', 0xDC00),
                             ('MFAR', 'far', 0xDC00)):
        lo, hi = rc.segments[name]
        data = (rc.obj / ('rcard.%s' % part)).read_bytes()
        main[lo - 0xD000:hi + 1 - 0xD000] = data[lo - base:hi + 1 - base]
    lc2 = (rc.obj / 'rcard.lc2').read_bytes()
    main[0x1000:0x1000 + min(len(lc2), 0x1000)] = lc2[:0x1000]
    high = 0x2000 - 0xE000           # an $E000-$FFFF address's offset
    for name in ('RCODE', 'BKNEAR', 'BKCARD'):
        if name not in rc.segments:
            continue
        lo, hi = rc.segments[name]
        if not (S.REPLAY_CARD[1] <= lo and hi < S.REPLAY_CARD[2]):
            raise DiskError('rcard\'s %s outside $F900-$FEFF' % name)
        data = (rc.obj / 'rcard.rc').read_bytes()
        main[lo + high:hi + 1 + high] = data[lo - 0xF900:hi + 1 - 0xF900]
    for suffix, lo in (('snd', 0xE900), ('fxc', S.FX_CODE[0]),
                       ('plat', S.PLATFORM_CARD[1]), ('vec', 0xFFFA)):
        data = boot.area(suffix)
        main[lo + high:lo + high + len(data)] = data
    aux = bytearray(HALF)
    for kind, bank, address, data in LC.Image.parse(
            (RC.TABLES / 'tables.img').read_bytes()):
        if kind == 1 and bank == 0 and address >= 0xC000:
            aux[address - 0xC000:address - 0xC000 + len(data)] = data
    return bytes(aux), bytes(main)


def runtime_ranges(boot: Boot) -> List[Tuple[int, int]]:
    """The main card's places written after the install ([lo, hi) of
    $E000-$FFFF): S2's ring, lists and state with this half's blocks
    between them (SCREENS.md 4.4: $E000-$E8FF), and fx.s's chip-3 lists
    in FXCODE (fx_want .. fx_wval)."""
    lab = boot.labels
    want, wval = lab['fx_want'], lab['fx_wval']
    if lab['fx_shadow'] != want + FX_NREGS or wval != want + 3 * FX_NREGS + 1:
        raise DiskError('fx.s\'s lists are not fx_want, fx_shadow, fx_wn, '
                        'fx_wreg, fx_wval of %d' % FX_NREGS)
    return [(0xE000, 0xE900), (want, wval + FX_NREGS)]


def card_offset(address: int, bank1: bool) -> int:
    """An address's offset in a card image (bank 1 or 2 for $D000)."""
    if address >= 0xE000:
        return address - 0xE000 + 0x2000
    return address - 0xD000 + (0 if bank1 else 0x1000)


# ---------------------------------------------------------------------------
# The bank files
# ---------------------------------------------------------------------------

Segment = Tuple[int, int, bytes]


def code_segments(lcard_obj: Path = LCARD, rcard_obj: Path = RCARD,
                  m11: Path = M11) -> List[Segment]:
    """The code library: the load image, the render images, the 2D
    images, OVLW."""
    out: List[Segment] = []
    lb = lrun.load_build(lcard_obj, 'lcard')
    out += [(bank, address, data) for _, bank, address, data
            in lrun.load_image(lb)]
    out += [(b, a, d) for b, a, d in render_segments(rcard_obj)
            if b in (R.WCODE_BANK, R.MCODE_BANK)]
    for image, (part, name) in IMAGE_BUILDS.items():
        b = s2run.load_build(m11 / part, name, image)
        out += [(bank, address, data) for _, bank, address, data
                in s2run.image_records(b)]
    part, name = OVLW_BUILD
    out.append((S.OVLW_BANK, S.IMAGE['OVLW'].stored[0],
                (m11 / part / ('%s.ovw' % name)).read_bytes()))
    return out


def render_segments(rcard_obj: Path = RCARD) -> List[Segment]:
    """Milestone 8's RamWorks records as its own runs lay them out
    (render_check.base_records, window mode, read only): the front end's
    W image in WCODE_BANK, the masked image in MCODE_BANK, the constant
    tables of rtables.py (tables.img's banks, the math's tables in
    MT_TBANK, MT_RLO, MT_RHI). Not its main or aux 0 tables (MEMORY_MAP.md
    3.2, 5: PRIVATE copies; request PLBOOT-7) nor the aux card's (LC.BIN)."""
    rc = RC.load_build(rcard_obj, 'rcard')
    return [(bank, address, bytes(data)) for kind, bank, address, data
            in RC.base_records(rc, 0, window=True)
            if kind == 1 and bank != 0 and len(data) < 0x10000]


def song_segments(song_list=None) -> List[Segment]:
    """The 13 songs packed first-fit, largest first, into banks 100-102
    ($0200-$BFFF; a song never crosses a bank: S2's snd_start reads one
    bank [R src/sound/README.md "snd_start"]), after the directory at
    SONG_DIR: 3 bytes a song in upstream's order, its bank and address."""
    if song_list is None:
        sys.path.insert(0, str(TOOLS / 'sound'))
        from sound import musicdisk
        song_list = [(s.name, s.data) for s in musicdisk.songs()]
        if len(song_list) != S.SONG_COUNT:
            raise DiskError('%d songs, s2layout.SONG_COUNT %d' % (
                len(song_list), S.SONG_COUNT))
    free = {b: LL.ROOM[0] for b in S.SONGS}
    free[SONG_DIR[0]] = SONG_DIR[1] + SONG_DIR_ENTRY * len(song_list)
    place: Dict[int, Tuple[int, int]] = {}
    for k in sorted(range(len(song_list)), key=lambda k: (
            -len(song_list[k][1]), k)):
        n = len(song_list[k][1])
        bank = next((b for b in S.SONGS if free[b] + n <= LL.ROOM[1]), None)
        if bank is None:
            raise DiskError('%s (%d B) fits no song bank' % (
                song_list[k][0], n))
        place[k] = (bank, free[bank])
        free[bank] += n
    directory = b''.join(struct.pack('<BH', *place[k])
                         for k in range(len(song_list)))
    out: List[Segment] = [(SONG_DIR[0], SONG_DIR[1], directory)]
    out += [(place[k][0], place[k][1], song_list[k][1])
            for k in range(len(song_list))]
    return out


def sfx_segments(m11: Path = M11) -> List[Segment]:
    data = (m11 / 'fxconv' / 'SFX.1').read_bytes()
    if S.SFX_ROOM[0] + len(data) > S.SFX_ROOM[1]:
        raise DiskError('SFX.1 is %d B, its room %d' % (
            len(data), S.SFX_ROOM[1] - S.SFX_ROOM[0]))
    return [(S.SFX, S.SFX_ROOM[0], data)]


def bank_files(m11: Path = M11, songs=None) -> List[Tuple[str, bytes]]:
    """Every bank file of the disk, in the catalog's order."""
    out = [(p.name, p.read_bytes()) for p in lrun.store_files()]
    out.append(('CODE.1', lstore.bank_file(code_segments(m11=m11))))
    out.append(('RTABLES.1', lstore.bank_file([
        s for s in render_segments()
        if s[0] not in (R.WCODE_BANK, R.MCODE_BANK)])))
    out.append(('SONGS.1', lstore.bank_file(song_segments(songs))))
    out.append(('SFX.1', lstore.bank_file(sfx_segments(m11))))
    out.append(('GFX.1', (m11 / 's2data' / 'GFX.1').read_bytes()))
    out.append(('HUDTXT.1', (m11 / 's2hud' / 'HUDTXT.1').read_bytes()))
    return out


def segments_of(files: Sequence[Tuple[str, bytes]]) -> List[Segment]:
    return [seg for _, data in files for seg in lstore.read_bank_file(data)]


def layout_problems(files: Sequence[Tuple[str, bytes]]) -> List[str]:
    """Every segment in a bank of the game (1-126), in $0200-$BFFF, and no
    two segments of the disk sharing a byte."""
    out = []
    spans: Dict[int, List[Tuple[int, int, str]]] = {}
    for name, data in files:
        for bank, address, seg in lstore.read_bank_file(data):
            if not 1 <= bank <= BANKS or address < LL.ROOM[0] or \
                    address + len(seg) > LL.ROOM[1]:
                out.append('%s: bank %d $%04X+%d outside the game\'s banks'
                           % (name, bank, address, len(seg)))
            spans.setdefault(bank, []).append((address, address + len(seg),
                                               name))
    for bank, items in sorted(spans.items()):
        items.sort()
        for (a0, a1, n0), (b0, b1, n1) in zip(items, items[1:]):
            if b0 < a1:
                out.append('bank %d: %s $%04X-$%04X meets %s $%04X-$%04X'
                           % (bank, n0, a0, a1 - 1, n1, b0, b1 - 1))
    return out


def catalog(names: Sequence[str]) -> bytes:
    if len(names) > MAX_FILES:
        raise DiskError('%d bank files: the catalog holds %d' % (
            len(names), MAX_FILES))
    cat = bytearray(C_NAMES)
    cat[0] = len(names)
    for n in names:
        if len(n) > 15:
            raise DiskError('the name %s' % n)
        cat += bytes([len(n)]) + n.encode('ascii') + bytes(15 - len(n))
    return bytes(cat) + bytes(CAT_MAX - len(cat))


def crc_entries(files: Sequence[Tuple[str, bytes]], aux: bytes,
                main: bytes) -> List[Tuple[int, int, int, int]]:
    """CRCLIST's entries: (bank, address, length, CRC-32) of every segment
    in the catalog's order, then LC.BIN's halves as staged."""
    out = [(bank, address, len(data), zlib.crc32(data) & 0xFFFFFFFF)
           for bank, address, data in segments_of(files)]
    out += [(0, STAGE, HALF, zlib.crc32(half) & 0xFFFFFFFF)
            for half in (aux, main)]
    return out


def crc_file(entries: Sequence[Tuple[int, int, int, int]]) -> bytes:
    data = struct.pack('<H', len(entries)) + b''.join(
        struct.pack('<BHHI', *e) for e in entries)
    if len(data) > CRC_MAX:
        raise DiskError('CRCLIST is %d bytes, the boot holds %d' % (
            len(data), CRC_MAX))
    return data


# ---------------------------------------------------------------------------
# What the images expect of the card
# ---------------------------------------------------------------------------

def area_problems(name: str, obj: Path, stem: str, main: bytes,
                  segs: Dict[str, Tuple[int, int]], labels: Dict[str, int],
                  card_labels: Dict[str, int]) -> List[str]:
    """An image's card parts against the main card image: its bank 1 code
    (MATHLC, a tic image's memory-API transport AMEMLC, MATHFAR, RFAR, and
    RLOAD up to far_wload's run list
    wl_front, which is the render image's: the others never call
    far_wload) byte for byte; its S2 and FXCODE areas when it links them;
    and every label it has in bank 1 or $E900-$F8FF at the card's address
    of that name."""
    out = []
    parts = [('MATHLC', 'lc1', 0xD800), ('AMEMLC', 'lc1', 0xD800),
             ('MATHFAR', 'far', 0xDC00), ('RFAR', 'far', 0xDC00),
             ('RLOAD', 'far', 0xDC00)]
    for seg, suffix, base in parts:
        if seg not in segs:
            continue
        lo, hi = segs[seg]
        if seg == 'RLOAD' and 'wl_front' in labels:
            hi = labels['wl_front'] - 1
        data = (obj / ('%s.%s' % (stem, suffix))).read_bytes()
        got = data[lo - base:hi + 1 - base]
        want = main[card_offset(lo, True):card_offset(hi, True) + 1]
        if got != want:
            out.append('%s: its %s $%04X-$%04X differs from the card\'s' % (
                name, seg, lo, hi))
    for suffix, lo in (('snd', 0xE900), ('fxc', S.FX_CODE[0])):
        path = obj / ('%s.%s' % (stem, suffix))
        if not path.exists() or not path.stat().st_size:
            continue
        data = path.read_bytes()
        want = main[card_offset(lo, True):card_offset(lo, True) + len(data)]
        if data != want:
            at = next(i for i in range(len(data)) if data[i] != want[i])
            out.append('%s: its %s area differs from the card\'s at $%04X'
                       % (name, suffix, lo + at))
    moved = sorted(n for n, a in labels.items()
                   if (0xD000 <= a < 0xE000 or 0xE900 <= a < 0xF900) and
                   not n.startswith('@') and n in card_labels and
                   card_labels[n] != a)
    if moved:
        out.append('%s: %d card labels elsewhere in the card (%s at $%04X, '
                   'the card\'s $%04X)' % (name, len(moved), moved[0],
                                           labels[moved[0]],
                                           card_labels[moved[0]]))
    return out


def image_problems(main: bytes, m11: Path = M11) -> List[str]:
    """Every image of the code library linked against the card the boot
    installs: the same far layer, math and phase loader; the 2D images
    the same player and effects' card part; OVLW's imported addresses."""
    out = []
    rc = RC.load_build(RCARD, 'rcard')
    boot = load_boot()
    card = {n: a for n, a in rc.labels.items() if 0xD000 <= a < 0xE000}
    card.update({n: a for n, a in boot.labels.items()
                 if 0xE900 <= a < 0xF900})
    lb = RC.load_build(LCARD, 'lcard')
    out += area_problems('the load image (lcard)', LCARD, 'lcard', main,
                         lb.segments, lb.labels, card)
    for image, (part, name) in IMAGE_BUILDS.items():
        b = s2run.load_build(m11 / part, name, image)
        out += area_problems('%s (%s/%s)' % (image, part, name),
                             m11 / part, name, main, b.segments, b.labels,
                             card)
    part, name = OVLW_BUILD
    import re
    cfg = (m11 / part / ('%s.cfg' % name)).read_text()
    for m in re.finditer(r'^\s*(\w+):\s*type = export, value = \$([0-9A-F]+)'
                         r';', cfg, re.M):
        sym, value = m.group(1), int(m.group(2), 16)
        if sym in rc.labels and rc.labels[sym] != value:
            out.append('OVLW imports %s at $%04X, the card has $%04X' % (
                sym, value, rc.labels[sym]))
    return out


# ---------------------------------------------------------------------------
# The disk
# ---------------------------------------------------------------------------

class Disk(NamedTuple):
    boot: Boot
    files: List[Tuple[str, int, int, bytes]]    # PRODOS included
    bank_files: List[Tuple[str, bytes]]
    aux: bytes
    main: bytes
    entries: List[Tuple[int, int, int, int]]


def disk_writer():
    path = DOOM_TOOLS / 'build_disk.py'
    spec = importlib.util.spec_from_file_location('doom_build_disk_pl', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_disk(files, output: Path) -> List[Tuple[str, int, int, bytes]]:
    bd = disk_writer()
    bd.VOLUME_NAME = VOLUME         # (this copy of the module only)
    master = bd.DEFAULT_MASTER
    if not master.is_file():
        raise FileNotFoundError('%s is missing (appletini-one\'s ProDOS; '
                                'set APPLETINI_ROOT)' % master)
    boot, prodos = bd.extract_prodos(master)
    everything = [files[0], ('PRODOS', bd.FILE_TYPE_SYS, 0x0000, prodos)] + \
        list(files[1:])
    writer = bd.VolumeWriter(VOLUME, bd.volume_size([f[3] for f in
                                                     everything]))
    writer.set_boot_blocks(boot)
    for name, file_type, aux, data in everything:
        writer.add_file(name, data, file_type, aux)
    image = writer.finish()
    expected = {name: (t, aux, data) for name, t, aux, data in everything}
    bd.verify_image(image, expected, order=[f[0] for f in everything])
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)
    return everything


def build(output: Path = OUT, m11: Path = M11, src: Path = SOURCE,
          songs=None, files: Optional[List[Tuple[str, bytes]]] = None,
          no_build: bool = False) -> Disk:
    """The link (make, unless no_build), the files, the disk."""
    part = m11 / 'plboot' if no_build else make(m11, src)
    boot = load_boot(part)
    system = boot.area('boot')
    if len(system) != BOOT_HI - BOOT_LO:
        raise DiskError('plboot.boot is %d bytes' % len(system))
    aux, main = card_images(boot)
    if files is None:
        files = bank_files(M11, songs)
    problems = layout_problems(files)
    if problems:
        raise DiskError('; '.join(problems[:4]))
    entries = crc_entries(files, aux, main)
    disk = [(SYSTEM, 0xFF, 0x2000, system),
            ('CATALOG', 0x06, 0x0000, catalog([n for n, _ in files])),
            ('CRCLIST', 0x06, 0x0000, crc_file(entries)),
            ('LC.BIN', 0x06, 0x0000, aux + main)]
    disk += [(n, 0x06, 0x0000, d) for n, d in files]
    everything = write_disk(disk, output)
    return Disk(boot, everything, list(files), aux, main, entries)


# ---------------------------------------------------------------------------
# A run on a2vm
# ---------------------------------------------------------------------------

class Run(NamedTuple):
    state: Dict[str, Any]
    snaps: Dict[str, Dict[str, Any]]    # name -> its json
    images: Dict[str, Any]              # name -> (kind, bank) -> bytearray
    ay_writes: List[Tuple[int, int, int]]   # (chip, register, value)


def read_snapshot(path: Path) -> Dict[Tuple[int, int], bytearray]:
    """A snapshot's records as 64 KB spaces: (0, 0) main, (1, bank) an aux
    bank, (2, 0) the main card $C000-$FFFF (bank 2 at $D000), (3, 0) its
    bank 1 at $D000."""
    out: Dict[Tuple[int, int], bytearray] = {}
    for kind, bank, address, data in LC.Image.parse(path.read_bytes()):
        space = out.setdefault((kind, bank), bytearray(0x10000))
        space[address:address + len(data)] = data
    return out


def snap_ranges(disk: Disk) -> str:
    banks = sorted({b for b, _, _ in segments_of(disk.bank_files)})
    return ','.join(['main:0000-BFFF', 'lc', 'lc1', 'aux0:C000-FFFF'] +
                    ['aux%d:0200-BFFF' % b for b in banks])


def poison_image() -> bytes:
    """The machine before the boot: ProDOS's card (a pattern, as
    musicdisk.py's), the aux card a pattern, zero page $00-$17, the
    persistent places and ProDOS's global page $A5 (what the boot must
    clear)."""
    rng = random.Random(2026)
    img = bytearray(b'A2VMIMG1')

    def rec(kind, bank, address, data):
        img.extend(struct.pack('<BBHI', kind, bank, address, len(data)))
        img.extend(data)
    rec(2, 0, 0xD000, bytes(rng.randrange(256) for _ in range(0x3000)))
    rec(3, 0, 0xD000, bytes(rng.randrange(256) for _ in range(0x1000)))
    rec(1, 0, 0xC000, bytes(rng.randrange(256) for _ in range(0x4000)))
    rec(0, 0, 0x0000, bytes([POISON]) * 0x18)
    rec(0, 0, 0x0300, bytes([POISON]) * 0xF0)
    rec(0, 0, 0x0C00, bytes([POISON]) * 0x1400)
    rec(0, 0, 0xBF03, bytes([POISON]) * 0xFD)
    return bytes(img)


def run(disk: Disk, work: Path, profile: str = PROFILES[0], *,
        mouse: bool = True, banks: Optional[int] = None, amem: bool = True,
        amem_off: bool = False, mb_only: bool = False, ready: bool = True,
        timeout: float = BOOT_TIMEOUT) -> Run:
    """Boot the disk's DOOM.SYSTEM on a2vm (the module docstring)."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    lab = disk.boot.labels
    manifest = []
    for name, file_type, aux, data in disk.files:
        if name == 'PRODOS':
            continue
        path = work / name
        path.write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
    (work / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / 'poison.img').write_bytes(poison_image())
    (work / 'cost.txt').write_text(costs.text(profile))
    fabric_hz = costs.parameters(profile)['fabric_mhz'] * 1e6
    events = ['pc %X snapshot loaded' % lab['check_files'],
              'pc %X snapshot checked' % lab['load_card'],
              'pc %X snapshot installed' % lab['bt_installed'],
              'pc %X snapshot ready' % lab['pl_ready'],
              'pc %X@%d snapshot later' % (lab['pl_rvbl'], LATER_VBLS),
              'pc %X@%d stop' % (lab['pl_rvbl'], LATER_VBLS)]
    (work / 'events.txt').write_text('\n'.join(events) + '\n')
    args = [str(A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--via-ora-nh',
            '--image', str(work / 'poison.img'),
            '--prodos', str(work / 'prodos.txt'),
            '--volume', VOLUME, '--launched', SYSTEM,
            '--load', '2000:%s' % (work / SYSTEM),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--irq-bounds', IRQ_BOUNDS,
            '--idle', '%X:vbl' % lab['pl_ridle'],
            '--stop-pc', '%X' % lab['bt_halt'],
            '--stop-pc', '%X' % lab['pl_crash'],
            '--cycles', str(int(CYCLE_SECONDS * fabric_hz)),
            '--snapshot-dir', str(work),
            '--snapshot-ranges', snap_ranges(disk) if ready
            else 'main:0000-BFFF',
            '--input', str(work / 'events.txt'),
            '--ay-log', str(work / 'ay.log'),
            '--state', str(work / 'state.json'), '--final-snapshot']
    if amem:
        args.append('--amem')
        if amem_off:
            args.append('--amem-unavailable')
    if not mouse:
        args.append('--no-mouse')
    if banks is not None:
        args += ['--banks', str(banks)]
    if mb_only:
        args.append('--phasor-mb-only')
    try:
        result = bounded.run(['nice', '-n', '10'] + args, timeout=timeout,
                             max_bytes=MAX_BYTES, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise DiskError('a2vm did not finish in %d s' % timeout)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise DiskError('a2vm failed (%d): %s' % (result.returncode,
                                                  result.stdout[-1500:]))
    state = json.loads(state_path.read_text())
    snaps, images = {}, {}
    for name in ('loaded', 'checked', 'installed', 'ready', 'later'):
        if (work / ('%s.json' % name)).exists():
            snaps[name] = json.loads((work / ('%s.json' % name)).read_text())
        if (work / ('%s.img' % name)).exists():
            images[name] = read_snapshot(work / ('%s.img' % name))
    writes = []
    if (work / 'ay.log').exists():
        with open(str(work / 'ay.log')) as handle:
            for line in handle:
                f = line.split()
                if f and f[0] == 'w':           # w CPU APPLE CLOCK CHIP REG V
                    writes.append((int(f[4]), int(f[5]), int(f[6])))
    if (work / 'final.img').exists():
        images['final'] = read_snapshot(work / 'final.img')
    return Run(state, snaps, images, writes)


def text_rows(space: bytearray, rows: int = 8) -> List[str]:
    out = []
    for r in range(rows):
        base = 0x0400 + (r % 8) * 0x80 + (r // 8) * 0x28
        out.append(''.join(chr(b & 0x7F) if 0x20 <= (b & 0x7F) < 0x7F
                           else '.' for b in space[base:base + 40]).rstrip())
    return out


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def card_problems(disk: Disk, img, when: str, exact: bool) -> List[str]:
    """The main and aux cards against LC.BIN (exact: every byte; else
    outside runtime_ranges)."""
    out = []
    lc, lc1 = img.get((2, 0)), img.get((3, 0))
    aux0 = img.get((1, 0))
    if lc is None or lc1 is None or aux0 is None:
        return ['%s: the snapshot holds no card' % when]
    got_main = bytes(lc1[0xD000:0xE000]) + bytes(lc[0xD000:0xE000]) + \
        bytes(lc[0xE000:0x10000])
    got_aux = bytes(aux0[0xC000:0x10000])
    skip = set()
    if not exact:
        for lo, hi in runtime_ranges(disk.boot):
            skip.update(range(card_offset(lo, True), card_offset(hi - 1, True)
                              + 1))
    for name, got, want, sk in (('main', got_main, disk.main, skip),
                                ('aux', got_aux, disk.aux, set())):
        bad = [i for i in range(HALF) if got[i] != want[i] and i not in sk]
        if bad:
            i = bad[0]
            where = ('bank 1 $%04X' % (0xD000 + i) if i < 0x1000 else
                     'bank 2 $%04X' % (0xC000 + i) if i < 0x2000 else
                     '$%04X' % (0xC000 + i))
            out.append('%s: the %s card differs from LC.BIN at %d bytes, '
                       'first %s ($%02X, the image $%02X)' % (
                           when, name, len(bad), where, got[i], want[i]))
    return out


def ready_problems(disk: Disk, r: Run, music: bool,
                   ntsc: bool = False, amem: bool = True) -> List[str]:
    """The checks of a run that must reach the ready state (amem: the
    memory API there, else the boot's message that it is not)."""
    out = []
    lab = disk.boot.labels
    if r.state.get('pc') in (lab['bt_halt'], lab['pl_crash']) or \
            'later' not in r.images:
        main = r.images.get('final') or next(iter(r.images.values()), {})
        screen = text_rows(main.get((0, 0), bytearray(0x10000))) if main \
            else []
        if r.state.get('pc') == lab['bt_halt'] and main:
            out = ['the boot stopped, PL_STATUS $%02X: %s' % (
                main[(0, 0)][S.PL_STATUS],
                ' | '.join(s for s in screen[2:] if s))]
        else:
            out = ['the boot did not reach 50 VBLs of pl_ready (pc $%04X, '
                   '%s, snapshots %s)%s' % (
                       r.state.get('pc', -1), r.state.get('end'),
                       sorted(r.images), ': ' + ' | '.join(
                           s for s in screen if s) if screen else '')]
        if 'installed' in r.images:
            out += card_problems(disk, r.images['installed'],
                                 'at bt_installed', True)
        return out
    inst = r.images['installed']
    out += card_problems(disk, inst, 'at bt_installed', True)
    m = inst[(0, 0)]
    for lo, hi, what in ((0x0000, 0x0018, 'zero page $00-$17'),
                         (0x0200, 0x03F0, 'main $0200-$03EF'),
                         (0x0C00, 0x2000, 'main $0C00-$1FFF'),
                         (0xBF00, 0xC000, 'ProDOS\'s global page')):
        bad = [a for a in range(lo, hi) if m[a]]
        if bad:
            out.append('at bt_installed: %s not cleared: %d bytes, first '
                       '$%04X = $%02X' % (what, len(bad), bad[0], m[bad[0]]))
    for name in ('ready', 'later'):
        img = r.images[name]
        m = img[(0, 0)]
        lc = img[(2, 0)]
        out += card_problems(disk, img, 'at %s' % name, False)
        if m[S.PL_STATUS] != S.PL['READY']:
            out.append('%s: PL_STATUS $%02X' % (name, m[S.PL_STATUS]))
        if m[0x06] or m[0x07]:
            out.append('%s: the pair $%02X $%02X' % (name, m[6], m[7]))
        if any(m[0xBF00:0xC000]):
            out.append('%s: ProDOS\'s global page not 0' % name)
        if list(m[S.KEYTAB_PLACE[0]:S.KEYTAB_PLACE[1]]) != \
                plkeys.doom_keys():
            out.append('%s: PL_KEYTAB is not plkeys\'' % name)
        fx_on, fx_hold, fx_inval = (lc[S.FX['FX_ON']], lc[S.FX['FX_HOLD']],
                                    lc[S.FX['FX_INVAL']])
        if (fx_on, fx_hold, fx_inval) != (1 if music else 0, 0, 1):
            out.append('%s: FX_ON %d, FX_HOLD %d, FX_INVAL %d (music %s)' % (
                name, fx_on, fx_hold, fx_inval, music))
    img = r.images['later']
    m, lc = img[(0, 0)], img[(2, 0)]
    vbl = m[lab['vbl_count']] | m[lab['vbl_count'] + 1] << 8
    step = lc[S.CLOCK['CLK_STEP']] | lc[S.CLOCK['CLK_STEP'] + 1] << 8
    frac = lc[S.CLOCK['CLK_FRAC']] | lc[S.CLOCK['CLK_FRAC'] + 1] << 8
    tics = int.from_bytes(bytes(lc[S.CLOCK['CLK_TICS']:
                                   S.CLOCK['CLK_TICS'] + 4]), 'little')
    std = lc[S.CLOCK['CLK_STD']]
    from native import plclock
    std_want = plclock.STD_NTSC if ntsc else plclock.STD_PAL
    want = (plclock.TIC_FRAC[std_want], std_want)
    if (step, std) != want:
        out.append('later: the clock\'s step %d, standard $%02X (%s: %d, '
                   '$%02X)' % (step, std, 'NTSC' if ntsc else 'PAL', *want))
    if vbl < LATER_VBLS or tics != vbl * step >> 16 or \
            frac != vbl * step & 0xFFFF:
        out.append('later: %d VBLs, %d tics, fraction %d: the model %d, %d'
                   % (vbl, tics, frac, vbl * step >> 16, vbl * step & 0xFFFF))
    for bank, address, data in segments_of(disk.bank_files):
        got = bytes(img[(1, bank)][address:address + len(data)]) \
            if (1, bank) in img else b''
        if got != data:
            at = next((i for i in range(len(data)) if i >= len(got) or
                       got[i] != data[i]), 0)
            out.append('later: bank %d $%04X: the boot left $%02X, the file '
                       '$%02X' % (bank, address + at,
                                  got[at] if at < len(got) else -1, data[at]))
            break
    screen = text_rows(m)
    if not any(row.startswith('READY') for row in screen):
        out.append('later: no READY on the screen: %s' % ' | '.join(screen))
    said = any(row.startswith('NO MUSIC') for row in screen)
    if said == music:
        out.append('later: the no-music message %s' % (
            'shown with music' if said else 'missing'))
    said = any(row.startswith('NO MEMORY API') for row in screen)
    if said == amem:
        out.append('later: the no-API message %s' % (
            'shown with the API' if said else 'missing'))
    # snd_probe's two writes (R0 of chip 0, then of chip 1: in Mockingboard
    # mode both reach chip 0 [R src/sound/probe.s]), then none: no song
    # plays before the second half's, no effect without a start, and
    # without native mode the effect player is off
    probe = [(0, 0, 0x55), (1 if music else 0, 0, 0xAA)]
    if r.ay_writes != probe:
        out.append('the AY writes %s, not snd_probe\'s %s' % (
            r.ay_writes[:4], probe))
    return out


def boot_ms(disk: Disk, r: Run, profile: str,
            name: str = 'ready') -> Optional[float]:
    """The model's ms from the boot's start to the snapshot `name`
    (loaded: the probes and the bank files read; checked: their CRCs;
    installed: the card images; ready: the state of SCREENS.md 2.5)."""
    snap = r.snaps.get(name)
    if not snap:
        return None
    return round(snap.get('cycles', 0) * 1000.0 /
                 (costs.parameters(profile)['fabric_mhz'] * 1e6), 1)


class Check(NamedTuple):
    name: str
    profile: str
    options: Dict[str, Any]
    stop: Optional[str]         # the stop's PL key, None: the ready state
    message: str                # the stop's (or no music's) screen text


CHECKS = (
    Check('boot-f121', PROFILES[0], {}, None, ''),
    Check('boot-fastpath', PROFILES[1], {}, None, ''),
    Check('boot-ntsc', PROFILES[0] + '+ntsc', {}, None, ''),
    Check('nomusic', PROFILES[0], {'mb_only': True}, None, 'NO MUSIC'),
    Check('nomouse', PROFILES[0], {'mouse': False}, 'NOMOUSE',
          'NO CLOCK: NO MOUSE CARD OR PHASOR'),
    Check('banks', PROFILES[0], {'banks': 64}, 'BANKS',
          '8 MB OF RAMWORKS NEEDED: NO BANK $40'),
    Check('noamem', PROFILES[0], {'amem': False}, None,
          'NO MEMORY API: COPIES BY THE CPU $FF'),
    Check('amemoff', PROFILES[0], {'amem_off': True}, None,
          'NO MEMORY API: COPIES BY THE CPU $FE'),
)
CHECK = {c.name: c for c in CHECKS}


def one_check(check: Check, disk: Disk, work: Path) -> Dict[str, Any]:
    ready = check.stop is None
    r = run(disk, work, check.profile, ready=ready,
            timeout=BOOT_TIMEOUT if ready else STOP_TIMEOUT,
            **check.options)
    out: Dict[str, Any] = {'check': check.name, 'profile': check.profile,
                           'end': r.state.get('end'),
                           'pc': r.state.get('pc')}
    lab = disk.boot.labels
    if ready:
        amem = check.options.get('amem', True) and \
            not check.options.get('amem_off')
        problems = ready_problems(disk, r, 'mb_only' not in check.options,
                                  check.profile.endswith('+ntsc'), amem)
        if check.message and 'later' in r.images and not any(
                row.startswith(check.message)
                for row in text_rows(r.images['later'][(0, 0)])):
            problems.append('no "%s" on the screen' % check.message)
        out['boot_ms'] = boot_ms(disk, r, check.profile)
        out['phases_ms'] = {n: boot_ms(disk, r, check.profile, n) for n in
                            ('loaded', 'checked', 'installed', 'ready')}
        out['boot_cycles'] = r.snaps.get('ready', {}).get('cycles')
        if 'later' in r.images:
            out['screen'] = [s for s in text_rows(r.images['later'][(0, 0)])
                             if s]
    else:
        problems = []
        if r.state.get('pc') != lab['bt_halt']:
            problems.append('the boot did not stop at bt_halt (pc $%04X, %s)'
                            % (r.state.get('pc', -1), r.state.get('end')))
        m = r.images['final'][(0, 0)] if 'final' in r.images else None
        if m is None:
            problems.append('no snapshot of the stop')
        else:
            code = S.PL[check.stop]
            if m[S.PL_STATUS] != code:
                problems.append('PL_STATUS $%02X, not $%02X' % (
                    m[S.PL_STATUS], code))
            screen = text_rows(m)
            out['screen'] = [s for s in screen if s]
            if not any(row.startswith(check.message) for row in screen):
                problems.append('no "%s" on the screen: %s' % (
                    check.message, ' | '.join(screen)))
    out['problems'] = problems
    return out


def tmpdir(tag: str) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='tmp-plboot-%s-' % tag,
                                 dir=str(BUILD)))


def check_one(name: str, disk: Disk) -> Dict[str, Any]:
    work = tmpdir(name)
    try:
        return one_check(CHECK[name], disk, work)
    except DiskError as error:
        return {'check': name, 'problems': [str(error)]}
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def check_all(disk: Disk, jobs: int = JOBS,
              names: Sequence[str] = tuple(CHECK)) -> List[Dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return list(pool.map(lambda n: check_one(n, disk), names))


# ---------------------------------------------------------------------------
# The planted bugs
# ---------------------------------------------------------------------------

# (name, the file, [(its text, the replacement)], the checks that must fail)
PLANTED = (
    ('a segment into the next bank', 'pl_boot.s',
     [('        lda hdr\n        sta RWBANK              ; its RamWorks bank',
       '        lda hdr\n        inc a\n        sta RWBANK')],
     ('boot-f121',)),
    ('the CRC table one entry short', 'pldisk.py',
     [('    return out\n\n\ndef crc_file(',
       '    return out[1:]\n\n\ndef crc_file(')],
     ('boot-f121',)),
    ('ProDOS\'s card not overwritten', 'pl_boot.s',
     [('        lda #0\n        jsr lc_put              ; the main card\n',
       '')],
     ('boot-f121',)),
    ('the pair not zeroed', 'pl_boot.s',
     [('        stz ZP_PAIR             ; the pair zeroed [R NATIVE.md 10]\n'
       '        stz ZP_PAIR + 1\n', '')],
     ('boot-f121',)),
    # (fx_init takes bt_music before snd_probe's answer is stored there:
    # the probe's answer comes after it)
    ('fx_init called before snd_probe\'s answer', 'pl_boot.s',
     [('        jsr snd_probe           ; native mode or not\n'
       '        sta bt_music\n',
       '        jsr snd_probe           ; native mode or not\n'),
      ('        jsr fx_init             ; A: snd_probe\'s answer\n',
       '        jsr fx_init             ; A: snd_probe\'s answer\n'
       '        jsr snd_probe\n        sta bt_music\n')],
     ('boot-f121', 'nomusic')),
)


def planted_tool(root: Path, text: str):
    """A scratch copy of this module, loaded apart."""
    path = root / 'pldisk_planted.py'
    here = 'HERE = Path(__file__).resolve().parent\n'
    if text.count(here) != 1:
        raise DiskError('pldisk.py\'s HERE line')
    path.write_text(text.replace(here, 'HERE = Path(%r)\n' % str(HERE)))
    spec = importlib.util.spec_from_file_location('pldisk_planted_%d' %
                                                  id(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def planted(disk: Disk, jobs: int = JOBS, out=print) -> List[str]:
    """Each planted bug in a scratch copy, built apart, must fail its
    checks. Returns the bugs not caught."""
    sources = {'pl_boot.s': (SOURCE / 'pl_boot.s').read_text(),
               'pldisk.py': Path(__file__).read_text()}

    def one(bug):
        name, where, edits, checks = bug
        root = tmpdir('planted')
        try:
            text = sources[where]
            for old, new in edits:
                if text.count(old) != 1:
                    return name, ['(its text is not in %s once)' % where], \
                        False
                text = text.replace(old, new)
            if where == 'pl_boot.s':
                src = root / 'src'
                src.mkdir()
                (src / 'pl_boot.s').write_text(text)
                bad = build(root / 'DOOM.hdv', root / 'm11', src,
                            files=disk.bank_files)
            else:
                mod = planted_tool(root, text)
                bad = mod.build(root / 'DOOM.hdv', disk.boot.dir.parent,
                                files=disk.bank_files, no_build=True)
            caught = []
            for c in checks:
                work = root / c
                try:
                    res = one_check(CHECK[c], bad, work)
                    p = res['problems']
                except DiskError as e:
                    p = [str(e).splitlines()[0]]
                finally:
                    shutil.rmtree(str(work), ignore_errors=True)
                if p:
                    caught.append('%s: %s' % (c, p[0]))
            return name, caught, bool(caught)
        except DiskError as e:
            return name, ['(the build) %s' % str(e).splitlines()[0]], False
        finally:
            shutil.rmtree(str(root), ignore_errors=True)
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        done = list(pool.map(one, PLANTED))
    missed = []
    for name, caught, ok in done:
        for k, c in enumerate(caught or ['NOT CAUGHT']):
            out('%-42s %s' % (name if not k else '', c[:150]))
        if not ok:
            missed.append(name)
    return missed


# ---------------------------------------------------------------------------

def report(disk: Disk, out=print) -> None:
    z = sizes(disk.boot)
    own = z['PLBOOT']
    out('DOOM.SYSTEM: pl_boot.s %d B (budget 2,048), with pl_init and the '
        'poll it calls %d B, snd_probe %d B: %d of %d B ($2000-$2FFF)' % (
            own, z['S2CODE'] + z['S2RODATA'], z['SNDBOOT'],
            own + z['S2CODE'] + z['S2RODATA'] + z['SNDBOOT'],
            BOOT_HI - BOOT_LO))
    out('the card: S2 %d B at $E900, FXCODE %d of %d B, the ready loop %d '
        'of %d B at $FF00' % (z['SNDCODE'] + z['SNDRODATA'], z['FXCODE'],
                              S.FX_CODE[1] - S.FX_CODE[0], z['PLRES'],
                              S.PLATFORM_CARD[2] - S.PLATFORM_CARD[1]))
    segs = segments_of(disk.bank_files)
    out('%d bank files, %d segments, %d bytes; CRCLIST %d entries' % (
        len(disk.bank_files), len(segs), sum(len(d) for _, _, d in segs),
        len(disk.entries)))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cfg', type=Path)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--only', nargs='*', choices=sorted(CHECK))
    parser.add_argument('--planted', action='store_true')
    parser.add_argument('--jobs', type=int, default=JOBS)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--json', type=Path, default=RESULTS)
    args = parser.parse_args(argv)
    if args.cfg:
        S.write_if_changed(args.cfg, cfg_text())
        return 0
    lack = missing()
    if lack:
        print('needs %s' % '; '.join(lack), file=sys.stderr)
        return 2
    disk = build(args.out, no_build=args.no_build)
    size = args.out.stat().st_size
    print('%s: %d bytes (%d blocks), volume %s, %d files' % (
        args.out, size, size // 512, VOLUME, len(disk.files)))
    report(disk)
    problems = image_problems(disk.main)
    for p in problems:
        print('  ' + p)
    bad = len(problems)
    results: List[Dict[str, Any]] = []
    if args.check:
        results = check_all(disk, args.jobs, args.only or tuple(CHECK))
        for r in results:
            print('%-14s %s%s; %d problems' % (
                r['check'], 'boot %s ms' % r['boot_ms'] if r.get('boot_ms')
                else 'stop', '' if 'screen' not in r else ' | ' +
                ' / '.join(r['screen'][:4]), len(r['problems'])))
            for p in r['problems'][:6]:
                print('    ' + p)
            bad += len(r['problems'])
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=1) + '\n')
    if args.planted:
        bad += len(planted(disk, args.jobs))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
