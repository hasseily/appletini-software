#!/usr/bin/env python3
"""build/native/DOOM.hdv, the playable game's boot disk (docs/PLAY.md 4,
7): DOOM.SYSTEM (milestone 11's boot, src/native/pl_boot.s) with the
kernel in pl_ready's place, and every image and table of the game in
RamWorks, from play.mk's links and the other milestones' builds (read
only, but milestone 9's load image: play.mk runs level.mk first, which
rebuilds it when a layout change left it out of date; --no-build skips
that too).

Usage:  python3 tools/native/playdisk.py [--play DIR] [--out FILE]
                [--no-build]
        python3 tools/native/playdisk.py --run SCRIPT [--out FILE]
                [--profile f121|fastpath] [--seconds S] [--keep DIR]

The disk (a ProDOS 2.4.3 volume DOOM, pldisk.py's writer) holds DOOM.SYSTEM,
PRODOS, CATALOG, CRCLIST, LC.BIN (the card images: pldisk.card_images of
the play link: S2's player, the effects' card part, pl_vbl, the kernel at
$FF00; milestone 8's math, far layer, phase loader, replay), then the bank
files:

  the level store     milestone 9's TEXELS.n, PATCHES.n, MAPS.n, TABLES.n
  CODE.1              the load image (LCODE), the render images
                      (WCODE_BANK, MCODE_BANK), the 2D images (MENUW,
                      AMAPW, WIW, FINW, PALW: milestone 11's parts' builds;
                      P2DW: the play link's, with the frame glue), OVLW
  CODE.2              the tic image: W and the core in GCODE0 at W's
                      addresses, its groups packed after it (GCODE0 $0200,
                      then GCODE1), the group directory written into the
                      core (grp_bank, grp_src, grp_pages, grp_tail: each
                      group's byte length; grp_slot for the glue's groups)
  PLAY.1              DLBANK (DLINIT's image, the static tables' PRIVATE
                      request and their sources, the kernel's menu loop),
                      DEMOB (the title loop's demo3: DOOM1.WAD's DEMO3
                      under the name upstream's D_DoAdvanceDemo gives it),
                      the 2D state's first values in S2STATE (the palette
                      state, the settings' defaults, the automap's, the
                      save slots' text), SPRBOUND in SPRT (sprbound())
  RTABLES.1, SONGS.1, SFX.1, GFX.1, HUDTXT.1   as pldisk.py's

--run boots the disk on a2vm (its MLI trap, the memory API, the mouse
card's VBL clock, --cost-timed under the Doom profile, the interrupt
bounds of SCREENS.md 2.3) and plays SCRIPT: a2vm's input events (tools/
a2vm/README.md "Input events"), with the names of the play link's labels
for pc events (pc @dl_halt ...). Every run is bounded (bounded.run: its
time, its files' sizes) in a directory deleted after it (--keep keeps
it).
"""

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from a2vm import costs  # noqa: E402
from native import glayout as GL, levelconv as LC, llayout as LL, lrun, \
    lstore, maplumps, playlayout as PL, playlink as PK, pldisk, \
    render_check as RC, rlayout as R, s2layout as S, s2run, \
    umodel, wadconv  # noqa: E402
from ref816 import bounded  # noqa: E402

BUILD = ROOT / 'build'
NATIVE = BUILD / 'native'
OUT = NATIVE / 'DOOM.hdv'
SOURCE = ROOT / 'src' / 'native'
A2VM = lrun.A2VM
PLAY = NATIVE / 'play'
PROFILES = {'f121': 'f121+phasor+window32',
            'fastpath': 'fastpath+phasor+window32'}
IRQ_BOUNDS = pldisk.IRQ_BOUNDS
MAX_BYTES = 512 << 20
GROUP_FIRST = 0x0200
GCODE0_GROUP_END = 0x6000

Segment = Tuple[int, int, bytes]


class PlayError(Exception):
    pass


# ---------------------------------------------------------------------------
# The links
# ---------------------------------------------------------------------------

def make(play: Optional[Path] = None) -> Path:
    """make -f play.mk (the links), with no warning. play.mk first runs
    level.mk on build/native/levels/obj, so milestone 9's load image
    (LCODE, which links the runtime's state) is never stale on the
    disk."""
    play = play or PLAY
    result = bounded.run(['make', '-s', '-C', str(SOURCE), '-f', 'play.mk',
                          'all', 'ROOT=%s' % ROOT, 'PLAY=%s' % play],
                         timeout=900,
                         max_bytes=64 << 20, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise PlayError('make -f play.mk failed:\n' + result.stdout[-4000:])
    if 'arning' in result.stdout:
        raise PlayError('make -f play.mk warns:\n' + result.stdout[-4000:])
    return play


def missing() -> List[str]:
    """What the disk needs and build/ lacks (empty: everything there)."""
    out = pldisk.missing()
    for part, name in list(PK.M11_IMAGES.values()):
        if not (pldisk.M11 / part / ('%s.map' % name)).exists():
            out.append('milestone 11\'s %s/%s (make -f m11.mk)' % (part,
                                                                   name))
    if not umodel.WAD_PATH.exists():
        out.append('DOOM1.WAD (tools/fetch_upstream.py)')
    return out


# ---------------------------------------------------------------------------
# The tic image (GCODE0, GCODE1)
# ---------------------------------------------------------------------------

def group_problems(play: Path) -> List[str]:
    """The tic link's groups against their files (gcall.s's gr_load copies
    a group's byte length, not its last page's padding, so the slot's
    bytes past it are the group before's: docs/SPEED.md 4, item 4): each
    group's segments are stored (none bss) and end at its file's end, and
    every label in a slot lies in a group's segment or at its end (no
    name for the slot's bytes past a group)."""
    b = PK.tic_build(play)
    cfg = (play / 'tic' / 'play.cfg').read_text()
    areas = {m.group(1): int(m.group(2), 16) for m in re.finditer(
        r'^\s*(G\d+):\s+start = \$([0-9A-F]+),', cfg, re.M)}
    out = []
    spans: List[Tuple[int, int]] = []
    for m in re.finditer(r'^\s*(\w+):\s+load = (G\d+), type = (\w+)',
                         cfg, re.M):
        name, area, kind = m.groups()
        if kind == 'bss':
            out.append('group segment %s is bss' % name)
        if name in b.segments:
            lo, hi = b.segments[name]
            spans.append((lo, hi + 1))
    for area, start in sorted(areas.items()):
        path = b.obj / ('tic.g%s' % area[1:])
        size = len(path.read_bytes()) if path.exists() else 0
        ends = [hi + 1 for m in re.finditer(
            r'^\s*(\w+):\s+load = %s, type' % area, cfg, re.M)
            for lo, hi in [b.segments.get(m.group(1), (0, -1))] if hi >= lo]
        if size and max(ends, default=start) != start + size:
            out.append('group %s: its segments end at $%04X, its file at '
                       '$%04X' % (area, max(ends, default=start),
                                  start + size))
    slots = sorted(set(areas.values()))
    for name, a in b.labels.items():
        if any(s <= a < s + PK.GROUP_SIZE for s in slots) and \
                not any(lo <= a <= hi for lo, hi in spans):
            out.append('label %s $%04X is in a slot past every group' % (
                name, a))
    return out


def tic_segments(play: Path) -> List[Segment]:
    """W and the core in GCODE0 at W's addresses, the groups packed, the
    group directory in the core (as tools/native/grun.py packs a test
    image: grun.group_entry, each group's byte length), the glue's groups'
    slots in grp_slot."""
    from native import grun
    b = PK.tic_build(play)
    lab = b.labels
    groups = PK.gplace_groups(play / 'tic' / 'gen' / 'gplace.inc')
    mine = {groups + off: slot for _, off, slot in PL.DL_GROUPS}
    maxgrp = lab['grp_bank'] - lab['grp_slot']
    if groups + len(PL.DL_GROUPS) >= maxgrp or \
            lab['grp_tail'] - lab['grp_pages'] != maxgrp:
        raise PlayError('%d groups and the glue\'s %d: gcall.s\'s directory '
                        'holds %d' % (groups, len(PL.DL_GROUPS), maxgrp - 1))
    bad = group_problems(play)
    if bad:
        raise PlayError('; '.join(bad[:6]))
    w = (b.obj / 'tic.w').read_bytes()
    if len(w) > 0x600:
        raise PlayError('the tic image\'s W is %d B' % len(w))
    core = bytearray((b.obj / 'tic.core').read_bytes())
    end = PK.core_end(b)
    core = core[:end - 0x6600]
    at = {LL.GCODE0: GROUP_FIRST, LL.GCODE1: GROUP_FIRST}
    out: List[Segment] = []
    for n in range(1, groups + len(PL.DL_GROUPS) + 1):
        path = b.obj / ('tic.g%d' % n)
        data = path.read_bytes() if path.exists() else b''
        if not data:
            continue
        if len(data) > PK.GROUP_SIZE:
            raise PlayError('group %d is %d B' % (n, len(data)))
        pages = (len(data) + 0xFF) >> 8
        bank = LL.GCODE0
        if at[bank] + (pages << 8) > GCODE0_GROUP_END:
            bank = LL.GCODE1
        if at[bank] + (pages << 8) > (LL.ROOM[1] if bank == LL.GCODE1
                                      else GCODE0_GROUP_END):
            raise PlayError('the groups pass GCODE1')
        out.append((bank, at[bank], data))
        for name, v in grun.group_entry(bank, at[bank] >> 8, len(data)):
            core[lab[name] + n - 0x6600] = v
        if n in mine:
            core[lab['grp_slot'] + n - 0x6600] = mine[n]
        at[bank] += pages << 8
    out.append((LL.GCODE0, 0x6000, w + bytes(0x600 - len(w)) + bytes(core)))
    return out


# ---------------------------------------------------------------------------
# PLAY.1: DLBANK, DEMOB, S2STATE's first values
# ---------------------------------------------------------------------------

def static_sources(play: Path) -> Dict[Tuple[int, int], bytes]:
    """(space, address) -> bytes of every PRIVATE copy of DLINIT: the
    static tables (rcard's main and aux 0 tables, MEMORY_MAP.md 3.2, 5) and
    the kernel's menu loop (the play card link's KMAIN, KMAIN2)."""
    rc = RC.load_build(RC.OBJ, 'rcard')
    from native import layout as L5
    m08 = (rc.obj / 'rcard.m08').read_bytes()
    a02 = (rc.obj / 'rcard.a02').read_bytes()
    a08 = (rc.obj / 'rcard.a08').read_bytes()
    out = {}
    for lo, hi in PL.STATIC_MAIN:
        out[(0, lo)] = m08[lo - L5.MAIN_TABLES:hi - L5.MAIN_TABLES]
    lo, hi = PL.STATIC_AUX0[0]
    if (lo, hi) != (L5.AUXCODE, L5.AUXCODE_END):
        raise PlayError('the aux drawers\' range')
    out[(1, lo)] = a02[:hi - lo] + bytes(max(0, hi - lo - len(a02)))
    for lo, hi in PL.STATIC_AUX0[1:]:
        out[(1, lo)] = a08[lo - L5.AUX_TABLES:hi - L5.AUX_TABLES]
    # rtables.py's main and aux 0 tables below the card (tables.img, as
    # milestone 8's runs load them over the link's: xtoviewangle's XTVLO
    # and XTVHI in main $09A9, $0AF3); each must lie in a copied range
    for kind, bank, address, data in LC.Image.parse(
            (RC.TABLES / 'tables.img').read_bytes()):
        if bank != 0 or kind not in (0, 1) or address >= 0xC000:
            continue
        ranges = PL.STATIC_MAIN if kind == 0 else PL.STATIC_AUX0
        for lo, hi in ranges:
            if lo <= address and address + len(data) <= hi:
                blk = bytearray(out[(kind, lo)])
                blk[address - lo:address - lo + len(data)] = data
                out[(kind, lo)] = bytes(blk)
                break
        else:
            raise PlayError('tables.img\'s %s $%04X+%d is in no static '
                            'range' % ('main' if kind == 0 else 'aux 0',
                                       address, len(data)))
    card = play / 'card'
    for suffix, (lo, hi) in (('k08', PL.KMAIN), ('k0b', PL.KMAIN2)):
        data = (card / ('plboot.%s' % suffix)).read_bytes()
        if len(data) > hi - lo:
            raise PlayError('the kernel\'s %s is %d B' % (suffix, len(data)))
        out[(0, lo)] = data
    return out


def priv_request(sources: Dict[Tuple[int, int], bytes]
                 ) -> Tuple[bytes, List[Segment]]:
    """DLINIT's request (its length first: lload.s's run_req's layout) and
    the sources' segments in DLBANK."""
    descs, segs = [], []
    at = PL.DLB_TABLES
    for (space, lo), data in sorted(sources.items()):
        if not data:
            continue
        segs.append((PL.DLBANK, at, data))
        dst = (0, 0, lo) if space == 0 else (1, 0, lo)
        descs.append(lstore.descriptor(LL.AMEM_COPY, (1, PL.DLBANK, at), dst,
                                       len(data)))
        at += len(data)
    if at > 0x2000 or len(descs) > LL.AMEM_MAX:
        raise PlayError('the static tables\' request')
    n = len(descs)
    head = bytes([4, 3, 0, 0, 0, 0x80, 0, 0, 0, 0]) + \
        struct.pack('<H', 8 + 16 * n) + b'AMEM' + bytes([1, n, 0, 0])
    req = head + b''.join(descs)
    if len(req) != 20 + 16 * n:
        raise PlayError('the request\'s header')
    blob = struct.pack('<H', len(req)) + req
    if len(blob) > 256:
        raise PlayError('the request is %d B' % len(blob))
    return blob, segs


def demob_segments() -> List[Segment]:
    """DEMOB (glayout.DEMOB_LAYOUT): the title loop's demo, DOOM1.WAD's
    DEMO3, named as D_DoAdvanceDemo names it (G_DeferedPlayDemo's
    reference: d_main65.s's strDemo3, the manifest's symbol), its lump
    number its index in the WAD's directory."""
    lay = dict(GL.DEMOB_LAYOUT)
    wad = maplumps.read_wad(umodel.WAD_PATH.read_bytes())
    names = [n for n, _ in wad]
    if 'DEMO3' not in names:
        raise PlayError('DOOM1.WAD has no DEMO3')
    index = names.index('DEMO3')
    data = wad[index][1]
    syms = LL.symbol_list()
    sym = syms.index('d_main65.s:strDemo3')
    at = lay['DM_LUMPS']
    if at + len(data) > LL.ROOM[1]:
        raise PlayError('DEMO3 passes DEMOB')
    entry = struct.pack('<HHHHH', sym, 0, index, len(data), at)
    if len(entry) != lay['DM_ESIZE']:
        raise PlayError('DEMOB\'s entry')
    return [(LL.DEMOB, lay['DM_DIR'], bytes([1]) + entry),
            (LL.DEMOB, at, data)]


SAVE_TEXT = ('NOT IN', 'THIS', 'VERSION')


def s2_symbols(play: Path) -> Dict[str, int]:
    """The play build's s2.inc (s2layout.py's release places)."""
    out = {}
    for line in (play / 'gen' / 's2.inc').read_text().splitlines():
        name, sep, value = line.partition('=')
        if sep and value.strip().startswith('$'):
            out[name.strip()] = int(value.split(';')[0].strip()[1:], 16)
    return out


def s2state_segment(play: Path) -> Segment:
    """S2STATE's state blocks' first values ($0200 to the settings' end):
    the palette state (upstream's i_viigs65.s data: picturenum -1, the
    rest 0), the automap's (am_map65.s's data: scale_mtof .2, stopped 1,
    the zooms 1.0, lastlevel -1), the HUD's lines nothing fetched, the
    menu's save slots' strings ("NOT IN THIS VERSION": no saves this
    afternoon), the settings' defaults (m_menu65.s's and s_sound65.s's
    data: no always run, high detail, the mouse on at speed 5, no mouse
    move, music volume 12)."""
    sym = s2_symbols(play)
    lo = sym['SS_PALST']
    hi = sym['SS_SETTINGS'] + sym['SS_SETTINGS_SIZE']
    blk = bytearray(hi - lo)

    def put(address: int, data: bytes) -> None:
        blk[address - lo:address - lo + len(data)] = data
    put(sym['SS_PALST'] + sym['PS_PICTURE'], b'\xff\xff')
    am = sym['SS_AMAPW'] - sym['A_MX']          # the block at W $AC00
    put(am + sym['A_SCALEMTOF'], struct.pack('<I', 13107))
    put(am + sym['A_STOPPED'], struct.pack('<H', 1))
    put(am + sym['A_MTOFZOOMMUL'], struct.pack('<I', 0x10000))
    put(am + sym['A_FTOMZOOMMUL'], struct.pack('<I', 0x10000))
    put(am + sym['A_LASTLEVEL'], b'\xff\xff')
    own = sym['SS_P2DW'] - sym['P_FPS']         # P2DW's own block, $BF00
    put(own + sym['P_MSGFILL'], b'\xff\xff')
    put(own + sym['P_MAPFILL'], b'\xff')
    menu = sym['SS_MENUW'] - sym['M_CURRENT']   # MENUW's block, $BF00
    for i, text in enumerate(SAVE_TEXT):
        put(menu + sym['M_SAVESTR'] + 8 * i, text.encode('ascii'))
    put(sym['SS_SETTINGS'], bytes([0, 0, 1, 5, 0, 12]))
    return (S.S2STATE, lo, bytes(blk))


def sprbound() -> bytes:
    """SPRBOUND (rlayout.SPRBOUND_T in SPRT, 4 x NUMSPRITES: E, E / 2 + 2)
    by upstream's rule (r_thing65.s's boundInit and frameInit): of each
    sprite, over the frames the states use and each frame's lumps (8
    rotations, or 1), E = the largest of the patches' leftoffset (when not
    negative) and width - leftoffset (when not negative; a difference past
    32,767 makes E $3FFF), at most $3FFF; a sprite with no frames (the
    release lacks its lumps) $3FFF. From DOOM1.WAD's patches: every lump
    of the game, where upstream's level set reads the resident ones only
    (docs/PLAY.md 9: a sprite no thing of the level shows)."""
    gd = umodel.game_data()
    defs = wadconv.sprite_defs(gd)
    nframes = LC.sprite_frames(gd.rel.memory, umodel.symbols())
    out = bytearray()
    for s in range(R.NUMSPRITES):
        e = 0
        if not defs[s] or not nframes[s]:
            e = 0x3FFF
        for f in range(nframes[s] if e == 0 else 0):
            if f >= len(defs[s]):
                continue                # (upstream reads past: no thing)
            fr = defs[s][f]
            for lump in (fr.lumps[::-1] if fr.rotate else fr.lumps[:1]):
                patch = gd.wad_by_name[gd.rel.names[lump]]
                width = struct.unpack_from('<H', patch, 0)[0]
                left = struct.unpack_from('<h', patch, 4)[0]
                if left >= 0:
                    e = max(e, left)
                d = width - left
                if d > 0x7FFF:
                    e = 0x3FFF
                    break
                if d >= 0:
                    e = max(e, d)
            if e == 0x3FFF:
                break
        e = min(e, 0x3FFF)
        out += struct.pack('<HH', e, (e >> 1) + 2)
    return bytes(out)


def play_segments(play: Path) -> List[Segment]:
    blob, segs = priv_request(static_sources(play))
    out = [(PL.DLBANK, PL.DLB_PRIV, blob)] + segs
    out.append((PL.DLBANK, PL.DLINIT_LO, PK.init_bytes(play)))
    out += demob_segments()
    out.append(s2state_segment(play))
    out.append((R.SPRT, R.SPRBOUND_T, sprbound()))
    return out


# ---------------------------------------------------------------------------
# The code library and the disk
# ---------------------------------------------------------------------------

def code_segments(play: Path) -> List[Segment]:
    """CODE.1: the load image, the render images, the 2D images (P2DW
    the play link's), OVLW, the tic image."""
    out: List[Segment] = []
    lb = lrun.load_build(pldisk.LCARD, 'lcard')
    out += [(bank, address, data) for _, bank, address, data
            in lrun.load_image(lb)]
    out += [(b, a, d) for b, a, d in pldisk.render_segments()
            if b in (R.WCODE_BANK, R.MCODE_BANK)]
    p2 = PK.p2dw_build(play)
    out += [(bank, address, data) for _, bank, address, data
            in s2run.image_records(p2)]
    for image in PK.M11_IMAGES:
        b = PK.m11_build(image)
        out += [(bank, address, data) for _, bank, address, data
                in s2run.image_records(b)]
    out.append((S.OVLW_BANK, S.IMAGE['OVLW'].stored[0], PK.ovlw_bytes()))
    return out


def bank_files(play: Path) -> List[Tuple[str, bytes]]:
    out = [(p.name, p.read_bytes()) for p in lrun.store_files()]
    out.append(('CODE.1', lstore.bank_file(code_segments(play))))
    out.append(('CODE.2', lstore.bank_file(tic_segments(play))))
    out.append(('PLAY.1', lstore.bank_file(play_segments(play))))
    out.append(('RTABLES.1', lstore.bank_file([
        s for s in pldisk.render_segments()
        if s[0] not in (R.WCODE_BANK, R.MCODE_BANK)])))
    out.append(('SONGS.1', lstore.bank_file(pldisk.song_segments())))
    out.append(('SFX.1', lstore.bank_file(pldisk.sfx_segments())))
    out.append(('GFX.1', (pldisk.M11 / 's2data' / 'GFX.1').read_bytes()))
    out.append(('HUDTXT.1', (pldisk.M11 / 's2hud' / 'HUDTXT.1')
                .read_bytes()))
    return out


class Disk(NamedTuple):
    play: Path
    path: Path
    boot: Any                   # pldisk.Boot of the play card link
    files: List[Tuple[str, int, int, bytes]]
    bank_files: List[Tuple[str, bytes]]
    aux: bytes
    main: bytes


# The tic image's shared W (docs/SPEED.md 4, item 11): the kernel loads the
# tic image's core from page $66 when the frame's list ended with P2DW
# (dl_disp.s kc_from), keeping P2DW's $6000-$65FF, so the two images must
# link the same bytes there (MATHW and AUXW: the render front end's WCODE
# links them too, which part frontend's wl_front relies on the same way),
# and nothing after P2DW's load may write there but the bytes AUXW's own
# routines set before they read them (their windows' operands, ax_out).
SHARED_W = (0x6000, 0x6600)
SHARED_SEGMENTS = ('MATHW', 'AUXW')
SELF_SET = ('axv_rd', 'axt_b2', 'axt_b3', 'ax3_lo', 'ax3_hi', 'ax4_b0',
            'ax4_b1', 'ax4_b2', 'ax4_b3')
KLISTS = PL.BT_REPLAY - 12      # the kernel's k_core (3 B) and k_planes
#                                 (9 B): dl_kern.s, written by dl_disp.s
# the 65C02's absolute-mode stores and read-modify-writes (W65C02S)
ABS_WRITES = frozenset((0x8D, 0x9D, 0x99, 0x8E, 0x8C, 0x9C, 0x9E, 0xEE,
                        0xFE, 0xCE, 0xDE, 0x0E, 0x1E, 0x4E, 0x5E, 0x2E,
                        0x3E, 0x6E, 0x7E, 0x0C, 0x1C))


def op_length(op: int) -> int:
    """A W65C02S instruction's bytes from its opcode."""
    hi, lo = op >> 4, op & 15
    if lo == 0:
        return 3 if op == 0x20 else 1 if op in (0x00, 0x40, 0x60) else 2
    if lo == 9:
        return 3 if hi & 1 else 2
    return {3: 1, 8: 1, 10: 1, 11: 1, 12: 3, 13: 3, 14: 3, 15: 3}.get(lo, 2)


def abs_writes(code: bytes, base: int, lo: int, hi: int) -> List[Tuple[int,
                                                                       int]]:
    """(pc, target) of each absolute-mode write into [lo, hi) in a linear
    sweep of the code at base (the base of an indexed one)."""
    out, i = [], 0
    while i < len(code):
        op = code[i]
        if op in ABS_WRITES and i + 2 < len(code):
            a = code[i + 1] | code[i + 2] << 8
            if lo <= a < hi:
                out.append((base + i, a))
        i += op_length(op)
    return out


def shared_w_problems(play: Path, main: bytes) -> List[str]:
    """SHARED_W's rule: the tic image, P2DW and WCODE link MATHW and AUXW
    at the same places with the same bytes and nothing else below $6600 but
    WCODE's RENDERW (the tic image's and P2DW's bytes past AUXW are not
    used); no absolute write into SHARED_W in P2DW's code, the kernel or
    its menu loop (the steps from P2DW's load to K_TIC: s2_frame or
    s2_poll, bt_mark) but AUXW's self-set operands and ax_out; the
    kernel's lists at KLISTS. (Indirect writes are not checked: P2DW's go
    through the far layer and its screen pointers, none to W.)"""
    out = []
    tic = PK.tic_build(play)
    p2 = PK.p2dw_build(play)
    rc = RC.load_build(pldisk.RCARD, 'rcard')
    wcode = b''.join(d for bank, a, d in pldisk.render_segments()
                     if bank == R.WCODE_BANK and a == SHARED_W[0])
    links = (('the tic image', tic, (tic.obj / 'tic.w').read_bytes()),
             ('P2DW', p2, (p2.obj / 'p2dw.w').read_bytes()),
             ('WCODE', rc, wcode))
    first = None
    for name, b, w in links:
        segs = {n: r for n, r in b.segments.items()
                if SHARED_W[0] <= r[0] < SHARED_W[1]}
        extra = set(segs) - set(SHARED_SEGMENTS) - (
            {'RENDERW'} if name == 'WCODE' else set())
        if extra:
            out.append('%s links %s below $%04X' % (
                name, ', '.join(sorted(extra)), SHARED_W[1]))
        ranges = tuple(segs.get(n) for n in SHARED_SEGMENTS)
        lo = SHARED_W[0]
        hi = max(r[1] for r in ranges if r) + 1 if any(ranges) else lo
        data = w[:hi - lo]
        if first is None:
            first = (name, ranges, data)
        elif (ranges, data) != first[1:]:
            out.append('%s\'s MATHW, AUXW differ from %s\'s' % (name,
                                                                first[0]))
    auxw = p2.segments.get('AUXW', (0, -1))
    allowed = set(range(p2.labels['ax_out'], p2.labels['ax_out'] + 4))
    for label in SELF_SET:
        allowed |= {p2.labels[label] + 1, p2.labels[label] + 2}
    scans = []
    for seg in ('MATHW', 'AUXW', 'S2CODE'):
        lo, hi = p2.segments[seg]
        area = 'W' if lo < SHARED_W[1] else 'IMG'
        base = p2.areas[area][0]
        scans.append(('P2DW ' + seg, lo, s2run.area_bytes(p2, area)[
            lo - base:hi + 1 - base]))
    off = 0x2000 - 0xE000           # (the card image: $E000-$FFFF last)
    scans.append(('the kernel', PL.KERNEL[0],
                  main[PL.KERNEL[0] + off:PL.KERNEL[1] + off]))
    card = play / 'card'
    for suffix, (lo, hi) in (('k08', PL.KMAIN), ('k0b', PL.KMAIN2)):
        scans.append(('the kernel\'s menu loop', lo,
                      (card / ('plboot.%s' % suffix)).read_bytes()))
    for name, base, code in scans:
        for pc, a in abs_writes(code, base, *SHARED_W):
            if not (auxw[0] <= a <= auxw[1] and a in allowed):
                out.append('%s writes $%04X at $%04X' % (name, a, pc))
    boot = pldisk.load_boot(card)
    for label, at in (('k_core', KLISTS), ('k_planes', KLISTS + 3)):
        if boot.labels.get(label) != at:
            out.append('the kernel\'s %s is not at $%04X' % (label, at))
    return out


def problems(play: Path, main: bytes) -> List[str]:
    """The links against each other: the card's symbols, the images'
    card parts (pldisk.image_problems), the tic image's card part, the
    tic image's shared W (shared_w_problems)."""
    out = PK.card_problems(play)
    out += pldisk.image_problems(main)
    p2 = PK.p2dw_build(play)
    rc = RC.load_build(RC.OBJ, 'rcard')
    card = {n: a for n, a in rc.labels.items() if 0xD000 <= a < 0xE000}
    boot = pldisk.load_boot(play / 'card')
    card.update({n: a for n, a in boot.labels.items()
                 if 0xE900 <= a < 0xF900})
    out += pldisk.area_problems('P2DW (play)', p2.obj, 'p2dw', main,
                                p2.segments, p2.labels, card)
    tb = PK.tic_build(play)
    out += pldisk.area_problems('the tic image', tb.obj, 'tic', main,
                                tb.segments, tb.labels, card)
    out += shared_w_problems(play, main)
    return out


def build(play: Path, out: Path = OUT) -> Disk:
    boot = pldisk.load_boot(play / 'card')
    system = boot.area('boot')
    if len(system) != pldisk.BOOT_HI - pldisk.BOOT_LO:
        raise PlayError('DOOM.SYSTEM is %d bytes' % len(system))
    aux, main = pldisk.card_images(boot)
    bad = problems(play, main)
    if bad:
        raise PlayError('; '.join(bad[:6]))
    files = bank_files(play)
    bad = pldisk.layout_problems(files)
    if bad:
        raise PlayError('; '.join(bad[:6]))
    entries = pldisk.crc_entries(files, aux, main)
    disk = [(pldisk.SYSTEM, 0xFF, 0x2000, system),
            ('CATALOG', 0x06, 0x0000, pldisk.catalog([n for n, _ in files])),
            ('CRCLIST', 0x06, 0x0000, pldisk.crc_file(entries)),
            ('LC.BIN', 0x06, 0x0000, aux + main)]
    disk += [(n, 0x06, 0x0000, d) for n, d in files]
    everything = pldisk.write_disk(disk, out)
    return Disk(play, out, boot, everything, files, aux, main)


# ---------------------------------------------------------------------------
# A run on a2vm
# ---------------------------------------------------------------------------

class Run(NamedTuple):
    state: Dict[str, Any]
    images: Dict[str, Dict[Tuple[int, int], bytearray]]
    shots: Dict[str, bytes]
    ay_writes: int
    out: str


def labels(disk: Disk) -> Dict[str, int]:
    """The labels a script may name (@name): the card link's (the kernel,
    the boot), the tic image's, P2DW's, DLINIT's."""
    lab = dict(disk.boot.labels)
    lab.update(PK.tic_build(disk.play).labels)
    return lab


def symbols(play: Path) -> Dict[str, int]:
    """Every NAME = value of the play build's generated includes (gen/,
    tic/gen/: the layouts, the game's globals and constants, the routine
    numbers), for the tests and the reports."""
    out: Dict[str, int] = {}
    for d in (play / 'gen', play / 'tic' / 'gen'):
        for p in sorted(d.glob('*.inc')):
            for line in p.read_text().splitlines():
                m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
                             r'(\$[0-9A-Fa-f]+|[0-9]+)\s*(;.*)?$', line)
                if m:
                    v = m.group(2)
                    out[m.group(1)] = int(v[1:], 16) if v[0] == '$' \
                        else int(v)
    return out


def script_events(disk: Disk, text: str) -> str:
    """a2vm's events from a script: @name is the label's address (hex)."""
    lab = labels(disk)
    out = []
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        words = []
        for w in line.split():
            if w.startswith('@'):
                name = re.split(r'[:@]', w[1:])[0]
                if name not in lab:
                    raise PlayError('no label %s' % name)
                words.append('%X%s' % (lab[name], w[1 + len(name):]))
            else:
                words.append(w)
        out.append(' '.join(words))
    return '\n'.join(out) + '\n'


def run(disk: Disk, script: str, work: Path, profile: str = 'f121',
        seconds: float = 60.0, timeout: float = 1800.0,
        snap_ranges: str = 'main:0000-BFFF,lc,lc1,aux0:2000-9FFF',
        extra: Sequence[str] = (), a2vm: Path = A2VM,
        idle: str = 'exact') -> Run:
    """Boot the disk and play the script for at most `seconds` of model
    time; the run's state, its snapshots and shots. `extra`: more a2vm
    options (playtime.py's --pclog); `a2vm`: the machine to run.

    `idle`: how a2vm skips the two loops that wait for a tic, the
    kernel's menu wait (dl_mwait) and the brain's frame wait (dl_bwait).
    'exact' (the default) skips to the next VBL only while the loop would
    spin on the card: no tic due (I_GetTime's low word, CLK_TICS in the
    main card, equal to DL_LASTM, the word both loops compare) and, for
    dl_bwait, the brain's group in the slot that holds that address
    (another group's code may sit there). 'old' is the unconditioned
    skip of milestone 11 (docs/SPEED.md 1, "The measurement artifact"),
    kept to measure it; 'none' skips nothing (the loops run)."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, file_type, aux, data in disk.files:
        if name == 'PRODOS':
            continue
        path = work / name
        path.write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
    (work / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / 'poison.img').write_bytes(pldisk.poison_image())
    prof = PROFILES[profile]
    (work / 'cost.txt').write_text(costs.text(prof))
    fabric_hz = costs.parameters(prof)['fabric_mhz'] * 1e6
    (work / 'events.txt').write_text(script_events(disk, script))
    lab = labels(disk)
    sym = symbols(disk.play)
    bwait = lab['dl_bwait']
    slot = [n for n in (1, 2) if sym['TW_SLOT%d' % n] <= bwait <
            sym['TW_SLOT%d_END' % n]]
    if len(slot) != 1:
        raise PlayError('dl_bwait $%04X is in no slot' % bwait)
    no_tic = 'eq=lc.%X,%X' % (sym['CLK_TICS'], sym['DL_LASTM'])
    idles = {'exact': ['%X:vbl:main:%s' % (lab['dl_mwait'], no_tic),
                       '%X:vbl:main:byte=%X,%X:%s' % (
                           bwait, sym['SLOT_GRP'] + slot[0],
                           sym['XS_DLG_BRAIN'], no_tic)],
             'old': ['%X:vbl' % lab['dl_mwait'], '%X:vbl' % bwait],
             'none': []}[idle]
    args = [str(a2vm), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--via-ora-nh',
            '--image', str(work / 'poison.img'),
            '--prodos', str(work / 'prodos.txt'),
            '--volume', pldisk.VOLUME, '--launched', pldisk.SYSTEM,
            '--load', '2000:%s' % (work / pldisk.SYSTEM),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--irq-bounds', IRQ_BOUNDS,
            '--stop-pc', '%X' % lab['bt_halt'],
            '--stop-pc', '%X' % lab['pl_crash'],
            '--stop-pc', '%X' % lab['dl_halt'],
            '--cycles', str(int(seconds * fabric_hz)),
            '--snapshot-dir', str(work),
            '--snapshot-ranges', snap_ranges,
            '--every-limit', '400',
            '--input', str(work / 'events.txt'),
            '--ay-log', str(work / 'ay.log'),
            '--amem',
            '--state', str(work / 'state.json'), '--final-snapshot']
    for spec in idles:
        args += ['--idle', spec]
    args += list(extra)
    try:
        result = bounded.run(args, timeout=timeout, max_bytes=MAX_BYTES,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise PlayError('a2vm did not finish in %d s' % timeout)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise PlayError('a2vm failed (%d): %s' % (result.returncode,
                                                  result.stdout[-1500:]))
    state = json.loads(state_path.read_text())
    images = {}
    for p in sorted(work.glob('*.img')):
        if p.name == 'poison.img':
            continue
        images[p.stem] = pldisk.read_snapshot(p)
    shots = {p.stem: p.read_bytes() for p in sorted(work.glob('*.shr'))}
    writes = 0
    if (work / 'ay.log').exists():
        with open(str(work / 'ay.log')) as handle:
            writes = sum(1 for line in handle if line.startswith('w '))
    return Run(state, images, shots, writes, result.stdout[-4000:])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--play', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--run', type=Path)
    parser.add_argument('--profile', default='f121',
                        choices=sorted(PROFILES))
    parser.add_argument('--seconds', type=float, default=60.0)
    parser.add_argument('--keep', type=Path)
    args = parser.parse_args(argv)
    gone = missing()
    if gone:
        print('playdisk: build/ lacks: %s' % '; '.join(gone),
              file=sys.stderr)
        return 2
    play = args.play or PLAY
    out = args.out or OUT
    try:
        if not args.no_build:
            make(play)
        disk = build(play, out)
        print('%s: %d B, %d bank files' % (out, out.stat().st_size,
                                           len(disk.bank_files)))
        if args.run:
            work = args.keep or Path(tempfile.mkdtemp(prefix='tmp-play-',
                                                      dir=str(BUILD)))
            try:
                r = run(disk, args.run.read_text(), work, args.profile,
                        args.seconds)
                print(json.dumps(r.state, indent=1)[:2000])
            finally:
                if not args.keep:
                    shutil.rmtree(str(work), ignore_errors=True)
    except PlayError as e:
        print('playdisk: %s' % e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
