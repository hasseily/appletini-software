"""The play disk without the memory API (docs/PLAY.md 19): a2vm with no
--amem is a //e with RamWorks, the mouse card, the Phasor and SHR, and an
empty slot 7. DOOM.SYSTEM's probe finds no API, says so on the boot
screen, goes on, and writes the transport's CPU version over the card and
each W image's walker over its transport (tools/native/amcpu.py); every
request is then done by the CPU.

One run, bounded (playdisk.run), from the boot through the title, a new
game (the menu, E1M1's load), then the menu's BENCHMARK (E1M7's load,
demo3 cut short as test_play_bench cuts it) to its result page, with
test_play_bench's checks: the colormaps right at every replay (the frame
slots' loads and restores by the CPU), W holding its image at every
K_CALL of the render front end, the masked phase and the status bar (the
kernel's K_LOADs by far_pload); and two more: W's core and the walk's
planes as GCODE0 and MOBJP hold them at every K_TIC (the core's and the
planes' loads, the planes put back the frame before), and DLINIT's static
tables in main and aux 0 as the disk's sources (its request by the CPU).

Run by name: python3 tools/testpar.py tests/test_play_noamem.py
"""

import struct
import unittest

import support  # noqa: F401  (sys.path)

import test_play_bench as B

from native import amcpu, llayout as LL, playdisk as P  # noqa: E402

KEY_RETURN, KEY_SPACE = 13, 32


@B.needs_build
class NoMemoryApi(B.BenchRun, unittest.TestCase):
    """The benchmark's disk run on a //e with no memory API."""

    AMEM = False
    LIMIT = 1500                # the @* snapshots of an event, at most

    def brain_event(self):
        """A snapshot 'brain-NNNN' at every K_TIC's call of the brain
        (k_tbrain: the core and the planes loaded), and the ranges of
        GCODE0's W and core and MOBJP's planes."""
        return ('pc %X@* snapshot brain\n' % self.lab['k_tbrain'],
                'aux%d:6000-99FF,aux%d:B400-BFFF' % (LL.GCODE0, LL.MOBJP))

    def tic_loads_wrong(self, run):
        """The K_TICs whose W differs from GCODE0 on the core's runs or
        from MOBJP on the planes' (the kernel's lists at KLISTS, in the
        card): (how many were checked, the wrong ones)."""
        out, n = [], 0
        for snap in sorted(k for k in run.images if k.startswith('brain-')):
            img = run.images[snap]
            lc, main = img[(2, 0)], img[(0, 0)]
            n += 1
            for at, bank in ((P.KLISTS, LL.GCODE0),
                             (P.KLISTS + 3, LL.MOBJP)):
                aux = img[(1, bank)]
                while lc[at]:
                    lo, hi = lc[at] << 8, (lc[at] + lc[at + 1]) << 8
                    if bytes(main[lo:hi]) != bytes(aux[lo:hi]):
                        bad = next(a for a in range(lo, hi)
                                   if main[a] != aux[a])
                        out.append('%s: bank %d at $%04X' % (snap, bank,
                                                             bad))
                    at += 2
        return n, out

    def test_new_game_and_benchmark(self):
        """The boot without the API: its row 3 message, PL_STATUS ready,
        the card's transport replaced (am_begin an RTS, the CPU version's
        bytes as amcpu's records); DLINIT's static tables right; a new
        game reaches E1M1 at skill 2; OPTIONS, BENCHMARK plays demo3 on
        E1M7 to its result page with FPS = 35000 x frames / realtics; the
        colormaps, the K_CALL images and the K_TIC loads right
        throughout."""
        script = B.at(5) + ' snapshot boot\n'
        script += B.at(8) + ' key %d\n' % KEY_RETURN
        script += B.at(9) + ' key %d\n' % KEY_RETURN
        script += B.at(16) + ' snapshot level\n'
        bench, go = B.to_benchmark(17)
        script += bench
        script += '%s snapshot run\n' % B.at(go + 3)
        script += '%s snapshot result\n' % B.at(go + 40)
        script += '%s key %d\n%s snapshot after\n' % (
            B.at(go + 41), KEY_SPACE, B.at(go + 43))
        event, ranges = self.replay_event()
        event2, ranges2 = self.loads_event()
        event3, ranges3 = self.brain_event()
        script = event + event2 + event3 + script
        ranges = ','.join((ranges.replace('aux0:2000-9FFF',
                                          'aux0:0200-9FFF'),
                           ranges2, ranges3))
        run = self.play(script, go + 43.5, ranges,
                        extra=['--every-limit', str(self.LIMIT)])
        self.assertEqual(run.state['end'], 'cycles', run.out)
        level = run.images['level']
        main, lc1 = level[(0, 0)], level[(3, 0)]
        # the boot: no API, its message (the text page, before the level's
        # colormaps take it), the CPU's version in the card
        rows = P.pldisk.text_rows(run.images['boot'][(0, 0)])
        self.assertTrue(rows[3].startswith('NO MEMORY API: COPIES BY THE '
                                           'CPU $FF'), rows)
        self.assertEqual(main[self.sym['PL_STATUS']], P.S.PL['READY'])
        self.assertEqual(lc1[self.lab['am_begin']], 0x60)
        lc = level[(2, 0)]
        for bank, address, data in amcpu.card_patches(
                P.PK.tic_build(P.PLAY)):
            mem = lc1 if 0xD000 <= address < 0xE000 else lc
            if address == amcpu.GL.AM_REQ[0]:
                continue                # (cq: the last descriptor done)
            self.assertEqual(bytes(mem[address:address + len(data)]), data,
                             'the card at $%04X' % address)
        # DLINIT's request: the static tables as the disk's sources
        aux0 = level[(1, 0)]
        for (space, lo), data in sorted(
                P.static_sources(P.PLAY).items()):
            got = bytes((main if space == 0 else aux0)[lo:lo + len(data)])
            self.assertEqual(got, data, '%s $%04X' % (
                'main' if space == 0 else 'aux 0', lo))
        # the new game
        self.assertEqual(self.u8(main, 'G_GAMEMAP'), 1)
        self.assertEqual(self.u8(main, 'G_GAMESKILL'), 2)
        self.assertEqual(self.u8(main, 'G_GAMESTATE'),
                         self.sym['UC_GS_LEVEL'])
        # the benchmark to its result
        menu, mid = run.images['menu'][(0, 0)], run.images['run'][(0, 0)]
        res = run.images['result'][(0, 0)]
        self.assertEqual(self.u8(mid, 'G_MENUACTIVE'), 0)
        self.assertEqual(self.u16(mid, 'G_TIMINGDEMO'), 1)
        self.assertEqual(self.u8(mid, 'G_GAMEMAP'), 7)
        self.assertEqual(self.u8(res, 'M_MSGKIND'), B.MSG_BENCH)
        self.assertEqual(self.u8(res, 'DL_BENCH'), 0)
        frames = self.u16(res, 'DL_VIEWS') - self.u16(menu, 'DL_VIEWS')
        realtics = self.u32(res, 'DL_BRT')
        self.assertGreater(frames, 5)
        self.assertGreaterEqual(realtics, B.DEMO_TICS // 4)
        self.assertEqual(self.text(res), B.fps_text(frames, realtics))
        # the frame slots, the kernel's loads, K_TIC's loads
        replays, wrong = self.colormaps_wrong(run)
        self.assertGreater(len(replays), 20)
        self.assertEqual(wrong, [], '%d of %d replays' % (len(wrong),
                                                         len(replays)))
        checked, bad = self.loads_wrong(run)
        self.assertGreater(checked, 3 * 20)
        self.assertEqual(bad, [], '%d of %d loads' % (len(bad), checked))
        tics, bad = self.tic_loads_wrong(run)
        self.assertGreater(tics, 20)
        self.assertEqual(bad, [], '%d of %d K_TICs' % (len(bad), tics))
        print('\nno memory API: benchmark %d frames, %d realtics, FPS %s; '
              'the colormaps right at %d replays, the images at %d loads, '
              'K_TIC\'s at %d' % (frames, realtics, self.text(res),
                                  len(replays), checked, tics))


if __name__ == '__main__':
    unittest.main()
