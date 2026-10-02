"""The playable game on a2vm (docs/PLAY.md 10): build/native/DOOM.hdv's
link booted and played with scripted input on the f121 profile.

The boot to the title page with its music; the title loop's demo (demo3
on E1M7, P_Ticker running); the menu; a new game's first frame of E1M1
against the reference machine's picture of the same view; the tic
command from held keys and the motion it makes (forward, turn, strafe);
a pickup and its HUD message's timeout; the automap; the quit.

Every run is bounded (playdisk.run: bounded.run, its time, its files'
sizes) in a directory under build/ deleted after it.
"""

import math
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from support import BUILD, ROOT

sys.path.insert(0, str(ROOT / 'tools'))

from native import playdisk as P  # noqa: E402

GONE = P.missing()
WHY = 'build/ lacks: %s' % '; '.join(GONE) if GONE else ''
needs_build = unittest.skipUnless(not GONE, WHY)

FABRIC_HZ = 133333333.33       # the f121 profile's cycles a second
KEY_RETURN, KEY_ESCAPE = 13, 27
UP, DOWN, LEFT = '0x0B', '0x0A', '0x08'
NEW_GAME = 'cycle %d key 13\ncycle %d key 13\n'
# the reference machine's first frame of a new game (tools/ref816's
# calls-newgame run: E1M1, the player at its start, (1056, -3616), 90
# degrees, viewz 41)
REF_FIRST = BUILD / 'ref816' / 'shots' / 'calls-newgame' / 'still-00s.png'


def at(seconds):
    return 'cycle %d' % int(seconds * FABRIC_HZ)


def new_game():
    """RETURN on the title page (the menu, NEW GAME), RETURN on the skill
    page: "Hurt me plenty" (sk_medium), E1M1 (the only episode)."""
    return '%s key 13\n%s key 13\n' % (at(8), at(9))


def png_rows(path):
    """An 8-bit RGB PNG's rows (shot.py's and ref816's: no interlace)."""
    data = Path(path).read_bytes()
    pos, idat, width, height = 8, b'', 0, 0
    while pos < len(data):
        n, kind = struct.unpack_from('>I4s', data, pos)
        chunk = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b'IHDR':
            width, height, depth, colour = struct.unpack_from('>IIBB', chunk)
            assert (depth, colour) == (8, 2)
        elif kind == b'IDAT':
            idat += chunk
    raw = zlib.decompress(idat)
    stride = 3 * width + 1
    rows, prev = [], bytearray(3 * width)
    for y in range(height):
        f, row = raw[y * stride], bytearray(raw[y * stride + 1:(y + 1) *
                                                stride])
        for x in range(len(row)):
            a = row[x - 3] if x >= 3 else 0
            b = prev[x]
            c = prev[x - 3] if x >= 3 else 0
            if f == 1:
                row[x] = (row[x] + a) & 255
            elif f == 2:
                row[x] = (row[x] + b) & 255
            elif f == 3:
                row[x] = (row[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else
                                    b if pb <= pc else c)) & 255
        rows.append(bytes(row))
        prev = row
    return width, height, rows


class PlayRun(unittest.TestCase):
    """The game's disk, made once for the class."""
    disk = None
    sym = None

    @classmethod
    def setUpClass(cls):
        if GONE:
            raise unittest.SkipTest(WHY)
        play = P.make()
        out = Path(tempfile.mkdtemp(prefix='tmp-play-test-', dir=str(BUILD)))
        cls.tmp = out
        cls.disk = P.build(play, out / 'DOOM.hdv')
        cls.sym = P.symbols(play)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def play(self, script, seconds):
        work = Path(tempfile.mkdtemp(prefix='run-', dir=str(self.tmp)))
        try:
            return P.run(self.disk, script, work, 'f121', seconds,
                         timeout=900)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)

    def main(self, run, name):
        return run.images[name][(0, 0)]

    def u8(self, mem, name):
        return mem[self.sym[name]]

    def u16(self, mem, name):
        return struct.unpack_from('<H', mem, self.sym[name])[0]

    def s32(self, mem, name):
        return struct.unpack_from('<i', mem, self.sym[name])[0]

    def player(self, mem):
        """(x, y) in map units and the angle in degrees of the view."""
        return (self.s32(mem, 'VIEWX') / 65536.0,
                self.s32(mem, 'VIEWY') / 65536.0,
                struct.unpack_from('<I', mem, self.sym['VIEWANGLE'])[0] *
                360.0 / 2 ** 32)

    def pl16(self, mem, field):
        return struct.unpack_from('<h', mem, self.sym['G_PLAYER'] +
                                  self.sym[field])[0]

    def cmd(self, mem):
        """The player's command: forwardmove, sidemove, angleturn."""
        self.assertEqual(self.sym['PL_CMD_SIDEMOVE'],
                         self.sym['PL_CMD_FORWARDMOVE'] + 1)
        return struct.unpack_from('<bbh', mem, self.sym['G_PLAYER'] +
                                  self.sym['PL_CMD_FORWARDMOVE'])

    def render(self, shot):
        from a2vm import shot as S
        return S.render(shot[9:9 + 0x8000], shot[9 + 0x8000:], shot[8])

    def colours(self, shot, rows=range(0, 200)):
        pixels = self.render(shot)
        return len({p for r in rows for p in pixels[2 * r]}), shot[8]


@needs_build
class Boot(PlayRun):
    def test_boot_title_page_and_music(self):
        """The boot reaches the title page (D_StartTitle, then the demo
        sequence's first step: TITLEPIC, the D_INTRO song) with nothing
        stopped: GS_DEMOSCREEN, the demo sequence at 0, the SHR screen on
        with the title's colours, AY writes from the song."""
        run = self.play('%s snapshot t8\n%s shot t8\n' % (at(8), at(8)), 8.5)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        mem = self.main(run, 't8')
        self.assertEqual(self.u8(mem, 'G_GAMESTATE'),
                         self.sym['UC_GS_DEMOSCREEN'])
        self.assertEqual(self.u8(mem, 'DL_DEMOSEQ'), 0)
        self.assertEqual(self.u8(mem, 'G_MENUACTIVE'), 0)
        n, newvideo = self.colours(run.shots['t8'])
        self.assertTrue(newvideo & 0x80)
        self.assertGreater(n, 8)
        self.assertGreater(run.ay_writes, 100)

    def test_title_loop_plays_demo3(self):
        """The title page's 1,050 tics (30 s), then D_AdvanceDemo's next
        step: demo3 on E1M7 (G_DeferedPlayDemo), played by the game: its
        tics run (P_Ticker), its player moves, nothing stops."""
        script = '%s snapshot a\n%s snapshot b\n' % (at(42), at(56))
        run = self.play(script, 56.5)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        a, b = self.main(run, 'a'), self.main(run, 'b')
        for mem in (a, b):
            self.assertEqual(self.u8(mem, 'G_GAMEMAP'), 7)
            self.assertEqual(self.u8(mem, 'G_GAMESTATE'),
                             self.sym['UC_GS_LEVEL'])
            self.assertNotEqual(self.u16(mem, 'G_DEMOPLAY'), 0)
        self.assertGreater(self.u16(b, 'G_GAMETIC') -
                           self.u16(a, 'G_GAMETIC'), 30)
        self.assertGreater(self.u16(b, 'DL_VIEWS') -
                           self.u16(a, 'DL_VIEWS'), 5)
        (xa, ya, _), (xb, yb, _) = self.player(a), self.player(b)
        self.assertGreater(abs(xb - xa) + abs(yb - ya), 64)

    def test_menu_opens_and_closes(self):
        """ESC on the title page opens the main menu (M_StartControlPanel),
        ESC again closes it; the title loop goes on."""
        script = '%s key %d\n%s snapshot open\n%s shot open\n' \
            '%s key %d\n%s snapshot closed\n' % (
                at(7), KEY_ESCAPE, at(8), at(8), at(9), KEY_ESCAPE, at(10))
        run = self.play(script, 10.5)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        self.assertEqual(self.u8(self.main(run, 'open'), 'G_MENUACTIVE'), 1)
        mem = self.main(run, 'closed')
        self.assertEqual(self.u8(mem, 'G_MENUACTIVE'), 0)
        self.assertEqual(self.u8(mem, 'G_GAMESTATE'),
                         self.sym['UC_GS_DEMOSCREEN'])

    def test_quit_ends_on_the_text_screen(self):
        """QUIT GAME (the fifth item), Y: the run ends at the kernel's halt
        on the text page's last words."""
        script = '%s key %d\n' % (at(7), KEY_ESCAPE)
        for k in range(4):
            script += '%s key %s\n' % (at(8 + 0.5 * k), DOWN)
        script += '%s key 13\n%s key 121\n' % (at(10), at(11.5))
        run = self.play(script, 30.0)
        self.assertEqual(run.state['end'], 'stop-pc', run.out)
        self.assertEqual(run.state['pc'], self.disk.boot.labels['dl_halt'])
        self.assertTrue(run.state['switches']['text'])
        mem = self.main(run, 'final')
        text = ''.join(chr(mem[0x480 + x] & 0x7F) for x in range(40))
        self.assertIn('DOOM HAS ENDED', text)


@needs_build
class Level(PlayRun):
    def test_new_game_first_frame_is_the_reference_s(self):
        """A new game reaches E1M1 at skill 2 ("Hurt me plenty"); its view
        at the start, the player not moved, is the reference machine's
        first frame (ref816's calls-newgame still-00s.png), every pixel's
        colour ($0RGB) equal but for a handful of an animated sprite's: the
        renderer's static tables, levels, textures and lights as
        upstream's."""
        script = new_game() + '%s snapshot s\n%s shot s\n' % (at(13), at(13))
        run = self.play(script, 13.2)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        mem = self.main(run, 's')
        self.assertEqual(self.u8(mem, 'G_GAMEMAP'), 1)
        self.assertEqual(self.u8(mem, 'G_GAMESKILL'), 2)
        self.assertEqual(self.u8(mem, 'G_GAMESTATE'), self.sym['UC_GS_LEVEL'])
        self.assertEqual(self.u8(mem, 'G_USERGAME'), 1)
        x, y, angle = self.player(mem)
        self.assertEqual((x, y, angle), (1056.0, -3616.0, 90.0))
        if not REF_FIRST.exists():
            self.skipTest('no %s (tools/ref816\'s calls-newgame run)'
                          % REF_FIRST)
        mine = self.render(run.shots['s'])
        width, height, ref = png_rows(REF_FIRST)
        self.assertEqual((width, height), (320, 200))
        differ = 0
        for row in range(168):                  # the view, not the bar
            for col in range(320):
                a = tuple(v >> 4 for v in mine[2 * row][2 * col])
                b = tuple(v // 17 for v in ref[row][3 * col:3 * col + 3])
                differ += a != b
        self.assertLess(differ, 64)

    def test_keys_move_turn_and_strafe(self):
        """G_BuildTiccmd's commands reach the player and move it: the up
        arrow held, forwardmove 25 (ALWAYS RUN off) and the player goes
        north; the left arrow held past SLOWTURNTICS, angleturn 640 and the
        angle grows; A held, sidemove -24 and the player goes west."""
        s = new_game()
        s += '%s snapshot a\n%s hold %s\n%s snapshot up\n%s release\n' % (
            at(11.9), at(12), UP, at(13.5), at(14.0))
        s += '%s snapshot b\n%s hold %s\n%s snapshot left\n%s release\n' % (
            at(14.5), at(14.6), LEFT, at(15.6), at(15.7))
        s += '%s snapshot c\n%s hold 65\n%s snapshot strafe\n' \
            '%s release\n%s snapshot d\n' % (at(16.5), at(16.6), at(17.6),
                                             at(17.7), at(18.5))
        run = self.play(s, 18.7)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        m = {n: self.main(run, n) for n in ('a', 'up', 'b', 'left', 'c',
                                            'strafe', 'd')}
        self.assertEqual(self.cmd(m['up']), (25, 0, 0))
        self.assertEqual(self.cmd(m['left']), (0, 0, 640))
        self.assertEqual(self.cmd(m['strafe']), (0, -24, 0))
        self.assertEqual(self.cmd(m['d']), (0, 0, 0))
        (xa, ya, aa), (xb, yb, ab) = self.player(m['a']), self.player(m['b'])
        self.assertGreater(yb - ya, 100)
        self.assertEqual(aa, 90.0)
        _, _, ac = self.player(m['c'])
        self.assertGreater(ac, ab + 20)
        xc, yc, _ = self.player(m['c'])
        xd, yd, _ = self.player(m['d'])
        # A strafes to the view's left: along the angle + 90 degrees. The
        # angle the held left arrow reached depends on the frames a second
        # (the input runs on model time): about 130 degrees before speed
        # wave 1, more since, so the direction comes from the angle at c.
        left = math.radians(ac + 90)
        self.assertGreater((xd - xc) * math.cos(left) +
                           (yd - yc) * math.sin(left), 10)

    def test_pickup_and_message_timeout(self):
        """The health bonus north-east of the start (1312, -3520): picked
        up (health 101, an item), its HUD message on (milestone 11's
        hu_ticker through flow's hu_tick: docs/m11-parts/design.md R5),
        then off after HU_MSGTIMEOUT (140 tics)."""
        s = new_game() + '%s mouse 421 0\n%s hold %s\n%s release\n' % (
            at(11), at(11.3), UP, at(13.4))
        s += '%s snapshot on\n%s snapshot off\n' % (at(15), at(26))
        run = self.play(s, 26.2)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        on, off = self.main(run, 'on'), self.main(run, 'off')
        self.assertEqual(self.pl16(on, 'PL_HEALTH'), 101)
        self.assertEqual(on[self.sym['G_PLAYER'] + self.sym['PL_ITEMCOUNT']],
                         1)
        card_on = run.images['on'][(2, 0)]
        card_off = run.images['off'][(2, 0)]
        self.assertEqual(card_on[self.sym['HU_ON']], 1)
        self.assertEqual(card_off[self.sym['HU_ON']], 0)
        self.assertGreater(self.u16(off, 'G_GAMETIC') -
                           self.u16(on, 'G_GAMETIC'), 140)

    def test_automap_opens(self):
        """TAB in a level opens the automap (AM_ACTIVE), TAB again turns it
        into the overlay (AM_OVERLAY), as upstream's map key cycles."""
        s = new_game() + '%s key 0x09\n%s snapshot full\n%s shot full\n' \
            '%s key 0x09\n%s snapshot overlay\n' % (at(12), at(13), at(13),
                                                    at(14), at(15))
        run = self.play(s, 15.2)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        full = self.u8(self.main(run, 'full'), 'AUTOMAP')
        over = self.u8(self.main(run, 'overlay'), 'AUTOMAP')
        self.assertTrue(full & 1)
        self.assertFalse(full & 2)
        self.assertTrue(over & 1 and over & 2)


if __name__ == '__main__':
    unittest.main()
