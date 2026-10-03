"""The playable game's glue without a machine run (docs/PLAY.md 10): the
layout, the hooks' parity with ghook.s, the HUD's ticker in the tic
image's core (speed wave 2), the boot's copies of the render tables,
SPRBOUND by upstream's rule, and play.mk's rebuild of milestone 9's load
image (LCODE).
"""

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from pathlib import Path

from support import BUILD, ROOT  # noqa: F401

sys.path.insert(0, str(ROOT / 'tools'))

SRC = ROOT / 'src' / 'native'


def exports(path):
    """The names a source .exports (its .export lines)."""
    out = set()
    for line in path.read_text().splitlines():
        line = line.split(';', 1)[0]
        m = re.match(r'\s*\.export\s+(.*)$', line)
        if m:
            out.update(n.strip() for n in m.group(1).split(',')
                       if n.strip())
    return out


class Layout(unittest.TestCase):
    def test_playlayout_check(self):
        from native import playlayout as PL
        self.assertEqual(PL.check(), [])

    def test_groups_fit_their_slots(self):
        from native import playlayout as PL
        self.assertEqual(sorted(slot for _, _, slot in PL.DL_GROUPS
                                if slot not in (1, 2)), [])
        self.assertEqual(len({off for _, off, _ in PL.DL_GROUPS}),
                         len(PL.DL_GROUPS))


class Hooks(unittest.TestCase):
    def test_dl_hook_exports_every_ghook_entry(self):
        """The play link replaces ghook.o by dl_hook.o: every entry the
        game's parts import from ghook.s must be there."""
        ghook = exports(SRC / 'ghook.s')
        mine = exports(SRC / 'dl_hook.s')
        self.assertTrue(ghook)
        self.assertEqual(sorted(ghook - mine), [])

    def test_license_notice(self):
        """Every glue source says it is GPL-2 (the directory's licence: the
        port's own code, or a derivative of upstream's named there)."""
        for p in sorted(SRC.glob('dl_*.s')):
            text = p.read_text()
            self.assertIn('GPL-2', text[:2000], p.name)


class Tickers(unittest.TestCase):
    """Speed wave 2, part glue (docs/speed-parts/glue.md): the HUD's
    ticker, which runs on every tic, is in the tic image's core (s2t_hu.s
    assembled with play.mk's PLAY_TIC), and HU_TickerHook jumps to it, so
    no tic loads DLG_HOOK for it; fx_chan's scratch block is in the core
    too, so DLG_HOOK, which the brain loads at each frame for
    S_UpdateSounds, is 7 pages."""

    def setUp(self):
        from native import playdisk as P
        if not (P.PLAY / 'tic' / 'tic.map').exists():
            self.skipTest('needs the play link (make -f play.mk)')

    def test_hud_ticker_in_the_core(self):
        from native import glayout as GL, playdisk as P, playlink as PK
        b = PK.tic_build(P.PLAY)
        lo, hi = GL.WR['CORE']
        for name in ('hu_ticker', 'hu_start', 'HU_TickerHook', 'fxc_scr'):
            self.assertTrue(lo <= b.labels[name] < hi,
                            '%s $%04X' % (name, b.labels[name]))
        core = (b.obj / 'tic.core').read_bytes()
        at = b.labels['HU_TickerHook'] - lo
        hu = b.labels['hu_ticker']
        self.assertEqual(core[at:at + 3], bytes([0x4C, hu & 0xFF, hu >> 8]))


def _static_missing():
    from native import playdisk as P, render_check as RC
    out = []
    if not (RC.OBJ / 'rcard.map').exists():
        out.append('milestone 8\'s rcard build (make -f render.mk)')
    if not (P.PLAY / 'card' / 'plboot.k08').exists():
        out.append('the play link (make -f play.mk)')
    if not (RC.TABLES / 'tables.img').exists():
        out.append('milestone 7\'s tables (rtables.py)')
    return out


class StaticTables(unittest.TestCase):
    def test_boot_copies_hold_every_render_table(self):
        """DLINIT's PRIVATE copies (playdisk.static_sources) put every main
        and aux 0 table that milestone 8's runs load below the card
        (render_check.base_records: the link's tables and rtables.py's,
        xtoviewangle among them) at its place, byte for byte; only aux 0's
        FUZZDARK, each level's, is outside them. (Without XTVLO and XTVHI
        every column of a wall took one texture column.)"""
        gone = _static_missing()
        if gone:
            self.skipTest('build/ lacks: %s' % '; '.join(gone))
        from native import playdisk as P, render_check as RC, \
            playlayout as PL, layout as L5
        src = P.static_sources(P.PLAY)
        rc = RC.load_build(RC.OBJ, 'rcard')
        checked = 0
        for kind, bank, address, data in RC.base_records(rc, 0x5A,
                                                         window=True):
            if kind not in (0, 1) or bank != 0 or address >= 0xC000 or \
                    len(data) >= 0x4000:
                continue                # (the fills, the card, other banks)
            if kind == 1 and address == L5.FUZZDARK:
                continue
            ranges = PL.STATIC_MAIN if kind == 0 else PL.STATIC_AUX0
            lo = next((lo for lo, hi in ranges
                       if lo <= address and address + len(data) <= hi), None)
            self.assertIsNotNone(lo, '%d $%04X+%d' % (kind, address,
                                                       len(data)))
            blk = src[(kind, lo)]
            self.assertEqual(blk[address - lo:address - lo + len(data)],
                             bytes(data), '%d $%04X' % (kind, address))
            checked += 1
        self.assertGreater(checked, 6)


READY = all(p.exists() for p in (
    BUILD / 'release' / 'doom-hd.hdv',
    BUILD / 'native' / 'render' / 'levels' / 'src'))


@unittest.skipUnless(READY, 'needs build/release (tools/fetch_upstream.py) '
                     'and milestone 8\'s level sources '
                     '(build/native/render/levels/src)')
class SprBound(unittest.TestCase):
    def test_upstream_rule_on_reference_sources(self):
        """SPRBOUND (playdisk.sprbound: every lump of the WAD) equals the
        reference's (ref816's RAM at a rendered frame, bank $22:7800) for
        every sprite whose lumps the reference's level set holds (its
        value is not the non-resident (0, 2)) and whose frames the states
        use all exist (a sprite whose states name a frame past its lumps:
        upstream reads past its frames, no thing shows it)."""
        from native import playdisk as P, rtables as T, umodel as U, \
            wadconv as WC, levelconv as LC, rlayout as R
        mine = P.sprbound()
        self.assertEqual(len(mine), 4 * R.NUMSPRITES)
        gd = U.game_data()
        defs = WC.sprite_defs(gd)
        nframes = LC.sprite_frames(gd.rel.memory, U.symbols())
        checked = 0
        sources = sorted(T.SOURCES.glob('*.ram.z'))
        self.assertTrue(sources)
        for path in sources:
            ref = T.rd(T.ram_of(path), 0x227800, 4 * R.NUMSPRITES)
            if ref == bytes(len(ref)):
                continue                # (no frame made it there)
            for s in range(R.NUMSPRITES):
                pair = struct.unpack_from('<HH', ref, 4 * s)
                if pair == (0, 2) or nframes[s] > len(defs[s]):
                    continue
                self.assertEqual(struct.unpack_from('<HH', mine, 4 * s),
                                 pair, '%s sprite %d' % (path.name, s))
                checked += 1
        self.assertGreater(checked, 100)


HAVE_CC65 = bool(shutil.which('make') and shutil.which('ca65') and
                 shutil.which('ld65'))


@unittest.skipUnless(HAVE_CC65, 'needs make and cc65 (ca65, ld65)')
class LoadImage(unittest.TestCase):
    """play.mk rebuilds milestone 9's load image (lcard, LCODE on the
    disk) when it is out of date: LCODE links the runtime's state, and
    speed wave 1's first disk held a stale one (docs/SPEED.md 6)."""

    def play_mk(self, *args, timeout=300):
        from ref816 import bounded
        return bounded.run(['make', '-s', '-C', str(SRC), '-f', 'play.mk',
                            'ROOT=%s' % ROOT] + list(args), timeout=timeout,
                           max_bytes=64 << 20, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True)

    def test_the_links_follow_the_load_image(self):
        """In play.mk's rules (make -p, nothing run): the load image is
        lrun.OBJ's, which playlink.py and playdisk.py read, it is remade
        by level.mk on every run, and the play link's symbols follow it."""
        from native import lrun, playlink as PK, pldisk
        self.assertEqual(PK.LCARD, lrun.OBJ)
        self.assertEqual(pldisk.LCARD, lrun.OBJ)
        play = '/nonexistent-play'
        r = self.play_mk('-p', '-q', 'PLAY=%s' % play, 'no-such-target',
                         timeout=60)
        rules = {}
        lines = r.stdout.splitlines()
        for i, line in enumerate(lines):
            target, colon, rest = line.partition(': ')
            if colon and not line.startswith(('#', '\t')):
                recipe = []
                for x in lines[i + 1:]:
                    if x.startswith('#'):
                        continue        # (make's notes on the rule)
                    if not x.startswith('\t'):
                        break
                    recipe.append(x)
                rules[target] = (rest.split(), recipe)
        lcode = str(lrun.OBJ / 'lcard.lw')
        self.assertIn(lcode, rules[play + '/gen/playsym.inc'][0])
        deps, recipe = rules[lcode]
        self.assertEqual(deps, ['FORCE'])
        self.assertTrue(any('-f level.mk' in x and 'OUT=$(LEVELS)' in x
                            for x in recipe), recipe)

    def test_a_stale_load_image_is_rebuilt(self):
        """A copy of build/native/levels/obj made stale as a layout change
        leaves it (an older ggame.inc, an lcard.lw from before it): play.mk
        remakes it (its target lcode, LEVELS the copy), and level.mk then
        finds it up to date."""
        from native import glayout as GL, lrun
        from ref816 import bounded
        if not (lrun.OBJ / 'lcard.lw').exists():
            self.skipTest('needs milestone 9\'s build: make -s -C src/native '
                          '-f level.mk ROOT=$PWD')
        tmp = Path(tempfile.mkdtemp(prefix='tmp-lcode-', dir=str(BUILD)))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        obj = tmp / 'obj'
        shutil.copytree(str(lrun.OBJ), str(obj))
        old = (ROOT / 'tools' / 'native' / 'glayout.py').stat().st_mtime \
            - 3600
        for name, data in (('gen/ggame.inc', b'; a stale layout\n'),
                           ('lcard.lw', b'stale')):
            (obj / name).write_bytes(data)
            os.utime(str(obj / name), (old, old))
        r = self.play_mk('lcode', 'LEVELS=%s' % obj)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:])
        self.assertNotIn('arning', r.stdout)
        self.assertEqual((obj / 'gen' / 'ggame.inc').read_text(),
                         GL.ggame_text())
        self.assertGreater(len((obj / 'lcard.lw').read_bytes()), 1000)
        self.assertGreater((obj / 'lcard.lw').stat().st_mtime, old)
        self.assertIn('nl_setup', (obj / 'lcard.lbl').read_text())
        q = bounded.run(['make', '-q', '-s', '-C', str(SRC), '-f',
                         'level.mk', 'ROOT=%s' % ROOT, 'OUT=%s' % obj],
                        timeout=60, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(q.returncode, 0, 'level.mk still finds it out of '
                         'date')


if __name__ == '__main__':
    unittest.main()
