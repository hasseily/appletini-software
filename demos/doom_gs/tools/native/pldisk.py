#!/usr/bin/env python3
"""The boot disk's pieces (part plboot): DOOM.SYSTEM (src/native/pl_boot.s)
loads every bank file into RamWorks, checks every segment's CRC-32 in its
bank, installs the card images, gives up ProDOS and reaches the ready
state with the tic clock running. playdisk.py builds DOOM.hdv from these
functions.

Usage:  python3 tools/native/pldisk.py --cfg FILE      (the link's map)

The disk (a ProDOS 2.4.3 volume DOOM, written by prodosvol.py) holds,
in this order:

  DOOM.SYSTEM  the boot ($2000-$37FF)
  PRODOS
  CATALOG      the bank files' names (+0 their count, +16 a name of 16
               bytes each: length, name)
  CRCLIST      the count (a word), then 9 bytes an entry: bank, address,
               length, zlib's CRC-32 (bank 0: main memory), every segment
               of the bank files in the catalog's order, then LC.BIN's two
               halves as the boot stages them (main $6000, 16 KB each)
  LC.BIN       the card images, 16 KB each (card_images): the aux card's
               (rtables.py's trig tables), then the main card's: bank 1
               $D000-$DFFF and bank 2 $D000-$DFFF and $F900-$FEFF from the
               render card link (the quarter squares, the math, the far
               layer, the phase loader, the card loops), $E900-$F8FF and
               $FF00-$FFFF from the boot's link (S2's player, pl_vbl and
               the effects' card part, the ready loop, the vectors);
               $E000-$E8FF is zero (written at run time)
  TEXELS.n, PATCHES.n, MAPS.n, TABLES.n
               the level store (wadconv.py --store)
  CODE.1       the code library: the load image, the render images, the
               2D images (IMAGE_BUILDS) and OVLW
  RTABLES.1    the render tables in RamWorks (render_segments)
  SONGS.1      the 13 songs (songs.songs) packed into banks 100-102, a
               directory first (SONG_DIR)
  SFX.1        part fxconv's SFX.1 as a bank file (bank 103 at $0200)
  GFX.1        part s2data's 2D store
  HUDTXT.1     part s2hud's message texts (bank 104 at SS_HUDMSG)
  DOOM.SETTINGS  the settings, one block (settings_file: the defaults;
               docs/PLAY.md, "The settings file"): DOOM.SYSTEM reads it,
               SAVE SETTINGS writes its block in place
"""

import argparse
import random
import shutil
import struct
import sys
import zlib
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from native import levelconv as LC, llayout as LL, lrun, lstore, \
    s2layout as S, s2run  # noqa: E402
from native import prodosvol, render_check as RC  # noqa: E402

BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
PART = M11 / 'plboot'
SOUND65 = BUILD / 'sound65'
RCARD = RC.OBJ                  # render.mk's rcard (read only)
LCARD = lrun.OBJ                # level.mk's lcard (read only)
A2VM = lrun.A2VM

VOLUME = 'DOOM'
SYSTEM = 'DOOM.SYSTEM'
BOOT_LO, BOOT_HI = 0x2000, 0x3800           # pl_boot.s BOOT_END
STAGE, HALF = 0x6000, 0x4000                # pl_boot.s STAGE, STAGE_SIZE
CAT_MAX, C_NAMES = 0x0100, 16               # pl_boot.s CATALOG
MAX_FILES = (CAT_MAX - C_NAMES) // 16
CRC_MAX = 0xBF00 - 0xAB00                   # pl_boot.s CRCBUF, CRC_MAX
BANKS = 126
# the songs' directory: 3 bytes a
# song (bank, address) in mus.UPSTREAM_SONGS' order, at bank SONGS0 $0200
SONG_DIR = S.SONG_DIR
SONG_DIR_ENTRY = S.SONG_DIR_ENTRY
# the 2D images of the code library as the parts built them (m11.mk):
# image -> (part, build); playlink.py's M11_IMAGES takes the same builds,
# with P2DW play.mk's own link (the frame glue)
IMAGE_BUILDS = {'P2DW': ('s2stbar', 's2sb'), 'MENUW': ('s2menu2', 's2m2'),
                'AMAPW': ('s2amap', 'amw'), 'WIW': ('s2wi', 'wiw'),
                'FINW': ('s2fin', 'finw'), 'PALW': ('s2pal', 'palw')}
OVLW_BUILD = ('s2ovl', 'ovlw')

IRQ_BOUNDS = '00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF'  # docs/SCREENS.md
# (no handler runs inside a block driver's call: DOOM.SYSTEM's reads and
# SAVE SETTINGS's write mask interrupts around it, docs/PLAY.md 7.1, so
# the bounds need no slot ROM or $C800 range)
# DOOM.SETTINGS (s2layout's SET_* and SETF_*; docs/PLAY.md): its name,
# ProDOS type (upstream's mkdisk.py TYPE_CFG) and the defaults it holds:
# the game's own at the boot (dl_brain.s b_boot: showMessages 1, the
# effects' volume 15; GAMMA 0; SS_SETTINGS's first values, playdisk.py's
# s2state_segment; pl_keys.s's default keys, plkeys.DEFAULTS)
SETTINGS = 'DOOM.SETTINGS'
SETTINGS_TYPE = 0x5A
SETTINGS_DEFAULTS = {'SETF_GAMMA': 0, 'SETF_RUN': 0, 'SETF_MESSAGES': 1,
                     'SETF_SFXVOL': 15, 'SETF_MUSICVOL': 12,
                     'SETF_MOUSE': 1, 'SETF_MSPEED': 5, 'SETF_MMOVE': 0,
                     'SETF_DETAIL': 0}
# SS_SETTINGS' first values (+0 always run, +1 detail, +2 the mouse, +3
# its speed, +4 mouse move, +5 the music's volume)
SS_SETTINGS_FIRST = ('SETF_RUN', 'SETF_DETAIL', 'SETF_MOUSE', 'SETF_MSPEED',
                     'SETF_MMOVE', 'SETF_MUSICVOL')


def settings_file(values: Optional[Dict[str, int]] = None,
                  keys: Optional[Sequence[int]] = None) -> bytes:
    """DOOM.SETTINGS's block (upstream's m_config65.s layout, the //e's
    key codes): "DOOMSET", the version, the sum of bytes 12-511, the
    settings (SETTINGS_DEFAULTS by default), the full view's size, the
    Doom key of each key code 0-127 (plkeys.doom_keys by default)."""
    from native import plkeys
    lay = dict(S.SETTINGS_LAYOUT)
    v = dict(SETTINGS_DEFAULTS)
    v.update(values or {})
    out = bytearray(S.SET_SIZE)
    out[0:len(S.SET_MAGIC)] = S.SET_MAGIC
    out[lay['SETF_VERSION']] = lay['SET_VERSION']
    for name, value in v.items():
        out[lay[name]] = value & 0xFF
    out[lay['SETF_VSIZE']] = lay['SET_FULLVIEW']
    k = list(keys if keys is not None else plkeys.doom_keys())
    out[lay['SETF_KEYS']:lay['SETF_KEYS'] + len(k)] = bytes(k)
    total = sum(out[lay['SETF_GAMMA']:]) & 0xFFFF
    out[lay['SETF_SUM']:lay['SETF_SUM'] + 2] = struct.pack('<H', total)
    return bytes(out)
POISON = 0xA5


class DiskError(Exception):
    pass


# ---------------------------------------------------------------------------
# The link (src/native/m11/plboot.mk)
# ---------------------------------------------------------------------------

def cfg_text() -> str:
    """ld65's map of the boot and the card's code, from s2layout's places
    (docs/SCREENS.md): the boot at $2000, S2's ring, lists and state, S2's
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
        '# docs/PLAY.md): DOOM.SYSTEM and the card. Do not edit.',
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
        '    PLVIDHD:   load = BOOT,  type = rw, define = yes;',
        '    PLSET:     load = BOOT,  type = rw, define = yes;',
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
        out.append('the renderer\'s rcard and tables (render.mk, rtables.py)')
    if not (LCARD / 'lcard.map').exists() or \
            not (lstore.STORE / 'store.json').exists():
        out.append('the levels\' lcard and store (level.mk, wadconv.py '
                   '--store)')
    needs = [m11 / part / ('%s.map' % name) for part, name in
             list(IMAGE_BUILDS.values()) + [OVLW_BUILD]]
    needs += [m11 / 'fxconv' / 'SFX.1', m11 / 's2data' / 'GFX.1',
              m11 / 's2hud' / 'HUDTXT.1']
    absent = [str(n.relative_to(ROOT)) for n in needs if not n.exists()]
    if absent:
        out.append('the parts\' builds (make -f src/native/m11.mk): %s'
                   % ', '.join(absent[:3]))
    from sound import songs
    if not songs.have_wad():
        out.append('the WAD (tools/fetch_upstream.py)')
    if not prodosvol.DEFAULT_MASTER.is_file():
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



def card_offset(address: int, bank1: bool) -> int:
    """An address's offset in a card image (bank 1 or 2 for $D000)."""
    if address >= 0xE000:
        return address - 0xE000 + 0x2000
    return address - 0xD000 + (0 if bank1 else 0x1000)


# ---------------------------------------------------------------------------
# The bank files
# ---------------------------------------------------------------------------

Segment = Tuple[int, int, bytes]


def render_segments(rcard_obj: Path = RCARD) -> List[Segment]:
    """The renderer's RamWorks records as its own runs lay them out
    (render_check.base_records, window mode, read only): the front end's
    W image in WCODE_BANK, the masked image in MCODE_BANK, the constant
    tables of rtables.py (tables.img's banks, the math's tables in
    MT_TBANK, MT_RLO, MT_RHI). Not its main or aux 0 tables
    (docs/MEMORY_MAP.md: PRIVATE copies) nor the aux card's (LC.BIN)."""
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
        from sound import songs
        song_list = songs.songs()
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

def write_disk(files, output: Path) -> List[Tuple[str, int, int, bytes]]:
    bd = prodosvol
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
    bd.verify_image(image, VOLUME, expected,
                    order=[f[0] for f in everything])
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)
    return everything


# ---------------------------------------------------------------------------
# A run on a2vm
# ---------------------------------------------------------------------------

def read_snapshot(path: Path) -> Dict[Tuple[int, int], bytearray]:
    """A snapshot's records as 64 KB spaces: (0, 0) main, (1, bank) an aux
    bank, (2, 0) the main card $C000-$FFFF (bank 2 at $D000), (3, 0) its
    bank 1 at $D000."""
    out: Dict[Tuple[int, int], bytearray] = {}
    for kind, bank, address, data in LC.Image.parse(path.read_bytes()):
        space = out.setdefault((kind, bank), bytearray(0x10000))
        space[address:address + len(data)] = data
    return out


def poison_image() -> bytes:
    """The machine before the boot: ProDOS's card a pattern, the aux card
    a pattern, zero page $00-$17, the
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cfg', type=Path, required=True)
    args = parser.parse_args(argv)
    S.write_if_changed(args.cfg, cfg_text())
    return 0


if __name__ == '__main__':
    sys.exit(main())
