#!/usr/bin/env python3
"""The constant render tables of the native front end (docs/RENDER.md),
from the reference's RAM, checked.

Usage:  python3 tools/native/rtables.py [--ram SOURCE] [--out DIR]

SOURCE is a level source of tools/native/rendercap.py (all RAM at an
R_FillStamps, .ram.z), default the first of build/native/render/levels/
src; every other level source is checked to hold the same tables. The
release builds FSTEP_TABLE and the square tables at boot
(m_recip65.s:355-396), so they are read from the RAM of the running game,
like the rest. Output in build/native/render/tables/ (Doom's and
upstream's data: build/ only):

    tables.img    A2VMIMG1 records: the aux card (F1.2.1, docs/MEMORY_MAP.md
                  with docs/RENDER.md's correction): finetangent part 3
                  (bank 1 $D000, low and high planes), viewangletox (bank 1
                  $D800, one plane of 2,042 bytes), finetangent part 4
                  (bank 2 $D000, four planes), tantoangle 0-2047 ($E000,
                  four planes); xtoviewangle (main $09A9 low, $0AF3 high);
                  FSTEP_TABLE (RamWorks banks 116-119: entries 16,384 k to
                  16,384 k + 16,383 in bank 116 + k, low plane $2000-$5FFF,
                  high plane $6000-$9FFF); the sprite scale records in
                  bank SPRT (docs/RENDER-MASKED.md: for each d =
                  tz >> 16, SPRXSCALE, SPRYSCALE, SPRISCALE and FQ's q
                  and r, 16 bytes)
    *.bin         the tables the W code includes (.incbin): smap.bin (64),
                  pcmolo.bin, pcmohi.bin (69 each), pgt.bin (88),
                  c26rev.bin (85: c26Reverse, derived from PGT and compared
                  with upstream's copy), kslo.bin, kshi.bin (161 each),
                  bxr0lo.bin, bxr0hi.bin, bxlimlo.bin, bxlimhi.bin (9 each:
                  checkBox's arcs, r_bsp65.s BXR0, BXLIM); the
                  masked image's: cmop.bin (85: the record page of CMO[i],
                  $46 + CMO[i] / 256), sfirst.bin (55 low bytes, then 55
                  high: the first SPRFR record of each sprite, from the
                  frames the states use)
    math/         src/native/math.inc's tables (tools/native/mathtables.py
                  on the same RAM): the squares, the sine, tantoangle and
                  the quarter sine of the tables bank, RECIP_TABLE
    tables.json   the checks

Checks, each a failure: every table equal to the reference's RAM (read
back from the files written); FSTEP entries for L >= 512 equal to
33,554,431 / L; SMAP, PCMO, CMO and PGT equal to their formulas; the
derived c26Reverse equal to upstream's; tantoangle entry 2,048 is ANG45;
the tables equal in every level source; SPRXSCALE[d] =
PROJECTION / d, SPRYSCALE[d] = PROJECTIONY * FRACUNIT / d, SPRISCALE[d]
= the recip of SPRXSCALE[d] (mathdefs.m_recip), FQ[d] = (16 d / 5,
16 d % 5), for d = 4..1280, read from a level source whose frame made them (PR_IOK: upstream
makes SPRISCALE and FQ at the first frame after each level load) and
equal in every other such source.
"""

import argparse
import json
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from bridge import linkmap as blink  # noqa: E402
from native import mathtables, rlayout as R  # noqa: E402
from native.levelconv import Image, SOURCES  # noqa: E402

ROOT = HERE.parent.parent
TABLES = ROOT / 'build' / 'native' / 'render' / 'tables'
MM_FSTEP = 0x1B0000
FSTEP_ENTRIES = 65536
XTVLO, XTVHI = 0x09A9, 0x0AF3           # docs/MEMORY_MAP.md
CMAPA_PAGE = 0x46                       # iigs_shrcmapA at $0D:4600
# the sprite tables (memmap.inc bank $22, r_thing65.s:33-37)
MM_SPRXSCALE, MM_SPRYSCALE = 0x220000, 0x222000
MM_SPRISCALE, MM_FQ = 0x224000, 0x226000
MM_RECIP = 0x1E0000
PROJECTION = 80 << 16                   # CENTERX * FRACUNIT
PROJECTIONY = 160
NUMSTATES, STATE_SIZE = 314, 16         # offsets.inc, info.inc
CMO_ENTRIES = 85                        # r_bsp65.s:1009-1020


class TableError(Exception):
    pass


def ram_of(path: Path) -> bytes:
    data = zlib.decompress(Path(path).read_bytes())
    if len(data) != 130 * 0x10000:
        raise TableError('%s is not a whole RAM' % path)
    return data


def rd(ram: bytes, address: int, length: int) -> bytes:
    return ram[address:address + length]


def words(data: bytes, size: int = 2) -> List[int]:
    return [int.from_bytes(data[i:i + size], 'little')
            for i in range(0, len(data), size)]


def planes(values: Sequence[int], count: int) -> List[bytes]:
    return [bytes((v >> (8 * k)) & 0xFF for v in values)
            for k in range(count)]


def formulas() -> Dict[str, List[int]]:
    smap = [(15 - min(max(i - 16, 0), 15)) * 4 + 24 for i in range(64)]
    pcmo = [min(max(k - 24, 0), 31) * 32 for k in range(69)]
    cmo = [min(max(k - 24, 0), 31) * 256 for k in range(CMO_ENTRIES)]
    pgt = [CMAPA_PAGE + min(max(i - 24, 0), 31) for i in range(88)]
    return {'SMAP': smap, 'PCMO': pcmo, 'CMO': cmo, 'PGT': pgt}


def read_tables(ram: bytes, sym: blink.Symbols) -> Dict[str, bytes]:
    a = sym.address
    return {
        'xtoviewangle': rd(ram, a('xtoviewangleTable'), 161 * 2),
        'viewangletox': rd(ram, a('viewangletoxTable'), R.VTOX_ENTRIES),
        'tan3': rd(ram, a('finetangentTable_part_3'), 1024 * 2),
        'tan4': rd(ram, a('finetangentTable_part_4'), 1024 * 4),
        'tanto': rd(ram, a('tantoangleTable'), 2049 * 4),
        'fstep': rd(ram, MM_FSTEP, FSTEP_ENTRIES * 2),
        'SMAP': rd(ram, a('SMAP'), 64 * 2),
        'PCMO': rd(ram, a('PCMO'), 69 * 2),
        'CMO': rd(ram, a('CMO'), CMO_ENTRIES * 2),
        'states': rd(ram, a('states'), NUMSTATES * STATE_SIZE),
        'SPRXSCALE': rd(ram, MM_SPRXSCALE, 4 * (R.MAXZ + 1)),
        'SPRYSCALE': rd(ram, MM_SPRYSCALE, 4 * (R.MAXZ + 1)),
        'PGT': rd(ram, a('PGT'), 88),
        'c26Reverse': rd(ram, a('r_seg65.s:c26Reverse'), 85),
        'KS': rd(ram, a('r_wall65.s:KS'), 161 * 2),
        'BXR0': rd(ram, a('r_bsp65.s:BXR0'), 9 * 2),
        'BXLIM': rd(ram, a('r_bsp65.s:BXLIM'), 9 * 2),
    }


def sprite_frames(states: bytes) -> List[int]:
    """The frames of each sprite the states use (boundInit's rule,
    r_thing65.s:887-913): the largest (frame & $7FFF) + 1."""
    count = [0] * R.NUMSPRITES
    for i in range(NUMSTATES):
        s = int.from_bytes(states[STATE_SIZE * i:STATE_SIZE * i + 2],
                           'little')
        f = int.from_bytes(states[STATE_SIZE * i + 2:STATE_SIZE * i + 4],
                           'little')
        if s >= R.NUMSPRITES:
            raise TableError('state %d has sprite %d' % (i, s))
        count[s] = max(count[s], (f & 0x7FFF) + 1)
    return count


def sprite_first(states: bytes) -> List[int]:
    """SFIRST: the SPRFR index of each sprite's frame 0."""
    out, at = [], 0
    for n in sprite_frames(states):
        out.append(at)
        at += n
    if at > R.SPRFRS.capacity:
        raise TableError('%d sprite frames: SPRFR holds %d'
                         % (at, R.SPRFRS.capacity))
    return out


def sprite_tables(ram: bytes) -> Dict[str, List[int]]:
    """SPRXSCALE, SPRYSCALE, SPRISCALE, FQ (q, r) for d = 0..1280."""
    n = R.MAXZ + 1
    return {'xs': words(rd(ram, MM_SPRXSCALE, 4 * n), 4),
            'ys': words(rd(ram, MM_SPRYSCALE, 4 * n), 4),
            'is': words(rd(ram, MM_SPRISCALE, 4 * n), 4),
            'q': words(rd(ram, MM_FQ, 4 * n), 4)}


def sprite_made(ram: bytes, sym: blink.Symbols) -> bool:
    """The source's frame made SPRISCALE and FQ (PR_IOK)."""
    return rd(ram, sym.address('PR_IOK'), 2) != b'\0\0'


def made_source(ram: bytes, sym: blink.Symbols) -> bytes:
    """ram when its frame made SPRISCALE and FQ, else the first level
    source whose frame did."""
    if sprite_made(ram, sym):
        return ram
    for path in sorted(SOURCES.glob('*.ram.z')):
        other = ram_of(path)
        if sprite_made(other, sym):
            return other
    raise TableError('no level source whose frame made SPRISCALE and FQ '
                     '(PR_IOK)')


def check_sprite_tables(tab: Dict[str, List[int]], recip: List[int]
                        ) -> None:
    from native.mathdefs import m_recip
    for d in range(4, R.MAXZ + 1):
        if tab['xs'][d] != PROJECTION // d:
            raise TableError('SPRXSCALE[%d] is not PROJECTION / d' % d)
        if tab['ys'][d] != (PROJECTIONY << 16) // d:
            raise TableError('SPRYSCALE[%d] is not PROJECTIONY * '
                             'FRACUNIT / d' % d)
        if tab['is'][d] != m_recip(tab['xs'][d], recip):
            raise TableError('SPRISCALE[%d] is not the recip of '
                             'SPRXSCALE[%d]' % (d, d))
        q = tab['q'][d]
        if (q & 0xFFFF, q >> 16) != divmod(16 * d, 5):
            raise TableError('FQ[%d] is not (16 d / 5, 16 d %% 5)' % d)


def scale_records(tab: Dict[str, List[int]]) -> bytes:
    """The native records of bank SPRT, d = 0..1280 (docs/RENDER-MASKED.md):
    d < 4 is never read (tz below 4.0 is rejected first)."""
    out = bytearray()
    for d in range(R.MAXZ + 1):
        rec = bytearray(R.SCALE_SIZE)
        rec[R.SCALE['XS']:R.SCALE['XS'] + 4] = tab['xs'][d].to_bytes(
            4, 'little')
        rec[R.SCALE['YS']:R.SCALE['YS'] + 4] = tab['ys'][d].to_bytes(
            4, 'little')
        rec[R.SCALE['IS']:R.SCALE['IS'] + 4] = tab['is'][d].to_bytes(
            4, 'little')
        q = tab['q'][d]
        if (q >> 16) > 255:
            raise TableError('FQ[%d]\'s r past a byte' % d)
        rec[R.SCALE['Q']:R.SCALE['Q'] + 2] = (q & 0xFFFF).to_bytes(
            2, 'little')
        rec[R.SCALE['R']] = q >> 16
        out += rec
    return bytes(out)


def build(ram: bytes, sym: blink.Symbols, out: Path,
          sprite_ram: Optional[bytes] = None) -> Dict:
    t = read_tables(ram, sym)
    checks = []
    f = formulas()
    for name in ('SMAP', 'PCMO', 'CMO'):
        if words(t[name]) != f[name]:
            raise TableError('%s differs from its formula' % name)
    # the sprite tables, from a source whose frame made them
    if sprite_ram is None:
        sprite_ram = made_source(ram, sym)
    stab = sprite_tables(sprite_ram)
    recip = words(rd(ram, MM_RECIP, 65536))
    check_sprite_tables(stab, recip)
    checks.append('SPRXSCALE, SPRYSCALE, SPRISCALE, FQ equal PROJECTION / '
                  'd, PROJECTIONY * FRACUNIT / d, the recip of SPRXSCALE, '
                  '(16 d / 5, 16 d % 5) for d = 4..1280')
    sfirst = sprite_first(t['states'])
    cmop = bytes(CMAPA_PAGE + v // 256 for v in words(t['CMO']))
    if list(t['PGT']) != f['PGT']:
        raise TableError('PGT differs from its formula')
    c26 = bytes(t['PGT'][84 - i] for i in range(85))
    if c26 != t['c26Reverse']:
        raise TableError('c26Reverse is not PGT reversed')
    checks.append('SMAP, PCMO, CMO, PGT equal their formulas; c26Reverse '
                  'is PGT reversed')
    fstep = words(t['fstep'])
    bad = [L for L in range(512, FSTEP_ENTRIES)
           if fstep[L] != (33554431 // L) & 0xFFFF]
    if bad:
        raise TableError('FSTEP: %d entries from 512 differ from '
                         '33554431 / L (the first %d)' % (len(bad), bad[0]))
    checks.append('FSTEP entries 512-65535 equal 33554431 / L')
    tanto = words(t['tanto'], 4)
    if tanto[2048] != 0x20000000:
        raise TableError('tantoangle[2048] is not ANG45')
    checks.append('tantoangle[2048] is ANG45')
    vtox = t['viewangletox']
    if max(vtox) > R.VIEWWIDTH:
        raise TableError('viewangletox has a value above 160')

    out.mkdir(parents=True, exist_ok=True)
    img = Image()
    # the aux card, aux bank 0's $C000-$FFFF (card bank 1 at $C000-$CFFF,
    # bank 2 at $D000-$DFFF: tools/a2vm/README.md)
    lo, hi = planes(words(t['tan3']), 2)
    img.add(1, 0, R.AX_TAN3 - 0x1000, lo)
    img.add(1, 0, R.AX_TAN3 - 0x1000 + 0x400, hi)
    img.add(1, 0, R.AX_VTOX - 0x1000, vtox)
    for k, p in enumerate(planes(words(t['tan4'], 4), 4)):
        img.add(1, 0, R.AX_TAN4 + 0x400 * k, p)
    for k, p in enumerate(planes(tanto[:2048], 4)):
        img.add(1, 0, R.AX_TANTO + 0x800 * k, p)
    xtv = words(t['xtoviewangle'])
    if any((x + 0x4000) & 0xFFFF >= 0x8000 for x in xtv[:R.VIEWWIDTH]):
        raise TableError('ANG90 + xtoviewangle leaves 0 .. ANG180 '
                         '(rwall.s sinelow needs it)')
    checks.append('ANG90 + xtoviewangle[x] lies in 0 .. ANG180 for every '
                  'column (rsga\'s anglea)')
    xlo, xhi = planes(xtv, 2)
    img.add(0, 0, XTVLO, xlo)
    img.add(0, 0, XTVHI, xhi)
    for k, bank in enumerate(R.FSTEP_BANKS):
        part = fstep[16384 * k:16384 * (k + 1)]
        plo, phi = planes(part, 2)
        img.add(1, bank, 0x2000, plo)
        img.add(1, bank, 0x6000, phi)
    scales = scale_records(stab)
    img.add(1, R.SPRT, R.SCALES.base, scales)
    (out / 'tables.img').write_bytes(img.bytes())

    files = {
        'smap.bin': bytes(words(t['SMAP'])),
        'pcmolo.bin': planes(words(t['PCMO']), 2)[0],
        'pcmohi.bin': planes(words(t['PCMO']), 2)[1],
        'pgt.bin': t['PGT'], 'c26rev.bin': c26,
        'kslo.bin': planes(words(t['KS']), 2)[0],
        'kshi.bin': planes(words(t['KS']), 2)[1],
        'bxr0lo.bin': planes(words(t['BXR0']), 2)[0],
        'bxr0hi.bin': planes(words(t['BXR0']), 2)[1],
        'bxlimlo.bin': planes(words(t['BXLIM']), 2)[0],
        'bxlimhi.bin': planes(words(t['BXLIM']), 2)[1],
        'cmop.bin': cmop,
        'sfirst.bin': bytes(v & 0xFF for v in sfirst) +
        bytes(v >> 8 for v in sfirst),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)

    # read back: every native table equals the reference
    back = {(k, b, a): d for k, b, a, d in
            Image.parse((out / 'tables.img').read_bytes())}
    got_vtox = back[(1, 0, R.AX_VTOX - 0x1000)]
    if got_vtox != vtox:
        raise TableError('viewangletox written wrongly')
    rebuilt = [back[(1, 0, R.AX_TANTO + 0x800 * k)] for k in range(4)]
    if [sum(rebuilt[k][i] << (8 * k) for k in range(4))
            for i in range(2048)] != tanto[:2048]:
        raise TableError('tantoangle written wrongly')
    lo_b, hi_b = back[(1, 0, R.AX_TAN3 - 0x1000)], \
        back[(1, 0, R.AX_TAN3 - 0x1000 + 0x400)]
    if [lo_b[i] | hi_b[i] << 8 for i in range(1024)] != words(t['tan3']):
        raise TableError('finetangent part 3 written wrongly')
    parts4 = [back[(1, 0, R.AX_TAN4 + 0x400 * k)] for k in range(4)]
    if [sum(parts4[k][i] << (8 * k) for k in range(4))
            for i in range(1024)] != words(t['tan4'], 4):
        raise TableError('finetangent part 4 written wrongly')
    xl, xh = back[(0, 0, XTVLO)], back[(0, 0, XTVHI)]
    if [xl[i] | xh[i] << 8 for i in range(161)] != xtv:
        raise TableError('xtoviewangle written wrongly')
    for k, bank in enumerate(R.FSTEP_BANKS):
        plo, phi = back[(1, bank, 0x2000)], back[(1, bank, 0x6000)]
        if [plo[i] | phi[i] << 8 for i in range(16384)] != \
                fstep[16384 * k:16384 * (k + 1)]:
            raise TableError('FSTEP bank %d written wrongly' % bank)
    for name, data in files.items():
        if (out / name).read_bytes() != data:
            raise TableError('%s written wrongly' % name)
    got = back[(1, R.SPRT, R.SCALES.base)]
    for d in range(4, R.MAXZ + 1):
        rec = got[R.SCALE_SIZE * d:R.SCALE_SIZE * (d + 1)]
        if (int.from_bytes(rec[0:4], 'little'), int.from_bytes(
                rec[4:8], 'little'), int.from_bytes(rec[8:12], 'little'),
                int.from_bytes(rec[12:14], 'little'), rec[14]) != (
                stab['xs'][d], stab['ys'][d], stab['is'][d],
                stab['q'][d] & 0xFFFF, stab['q'][d] >> 16):
            raise TableError('the scale record of %d written wrongly' % d)
    checks.append('every table read back equals the reference RAM')
    # the math tables (src/native/math.inc) from the same RAM
    with tempfile.TemporaryDirectory(dir=str(out)) as tmp:
        path = Path(tmp) / 'base.ram'
        path.write_bytes(ram)
        report = mathtables.build(mathtables.load(path), out / 'math')
    checks.append('the math tables: %d cosine exceptions, RECIP_TABLE '
                  'equals its formula' % len(report['cosine_exceptions']))
    return {'checks': checks, 'sprite_frames': sprite_frames(t['states']),
            'sfirst': sfirst}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--ram', type=Path)
    parser.add_argument('--out', type=Path, default=TABLES)
    args = parser.parse_args(argv)
    sources = sorted(SOURCES.glob('*.ram.z'))
    if args.ram is None:
        if not sources:
            print('no level sources in %s: run python3 '
                  'tools/native/rendercap.py first' % SOURCES,
                  file=sys.stderr)
            return 1
        args.ram = sources[0]
    sym = blink.Symbols()
    try:
        ram = ram_of(args.ram)
        made = [s for s in sources if sprite_made(ram_of(s), sym)]
        if sprite_made(ram, sym):
            made.insert(0, args.ram)
        sprite_ram = ram_of(made[0]) if made else None
        report = build(ram, sym, args.out, sprite_ram)
        first = read_tables(ram, sym)
        for other in sources:
            if other == args.ram:
                continue
            if read_tables(ram_of(other), sym) != first:
                raise TableError('%s holds other tables' % other.name)
        report['checks'].append('the same tables in %d level sources'
                                % len(sources))
        stab = sprite_tables(sprite_ram)
        for other in made[1:]:
            if sprite_tables(ram_of(other)) != stab:
                raise TableError('%s holds other sprite tables'
                                 % other.name)
        report['checks'].append('the same sprite tables in the %d level '
                                'sources whose frame made them (%s)' % (
                                    len(set(made)), made[0].name))
    except TableError as error:
        print('rtables: FAILED: %s' % error, file=sys.stderr)
        return 1
    report['source'] = args.ram.name
    (args.out / 'tables.json').write_text(json.dumps(report, indent=1) +
                                          '\n')
    for line in report['checks']:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
