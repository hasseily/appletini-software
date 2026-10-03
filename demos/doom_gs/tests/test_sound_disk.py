"""Tests of milestone S3: the music disk (tools/sound/musicdisk.py,
src/sound/music.s, aytime.s, music.cfg) and its checks on a2vm.

  - the disk: a ProDOS volume MUSIC whose first file is MUSIC.SYSTEM,
    then PRODOS, the 13 song files as mus2ay.py converts them now, and
    PROFILE.TXT with the Doom profile's key; MUSIC.SYSTEM without the
    firmware's A2Li signature at $4078;
  - the program's map: the player where docs/MEMORY_MAP.md 4.2 puts it
    (zero page $D8-$FF, ring $E000, write lists $E480, state $E500,
    code and tables $E900-$F8FF, the IRQ vector at $FFFE), its own data
    outside the video pages;
  - on a2vm, the disk's own MUSIC.SYSTEM through the MLI trap, every
    interrupt held to the game's contract (--irq-bounds): the boot and
    20 s of each song equal player.py, the song clock; the keys (stop,
    next, previous, the arrows and their wrap, PAL/NTSC, play all, the
    timing test while music plays, ESC and Q with ProDOS's card put back
    and the Phasor in Mockingboard mode); no music on a
    card locked to Mockingboard mode; the AY timing test under window
    512, window 32, FW-S1 and NTSC against the model;
  - the checks can fail: copies of music.s whose keys pick the wrong song,
    whose PAL clock counts 60 VBLs a second, or whose song keys work
    without music, or whose quit leaves the Phasor native, and copies of
    aytime.s whose burst loop is one cycle longer or whose microseconds
    are 1% off, are caught.

They skip without DOOM1.WAD (tools/fetch_upstream.py), without cc65 (ca65,
ld65), or without the existing port's disk tools (demos/doom/tools/
build_disk.py and appletini-one's ProDOS_2_4_3.po).
"""

import atexit
import shutil
import tempfile
import unittest
from pathlib import Path

import support
from sound import musicdisk

WAD_MISSING = ('build/upstream/data/DOOM1.WAD is missing: run python3 '
               'tools/fetch_upstream.py first')
needs_all = unittest.skipUnless(
    musicdisk.have_wad() and musicdisk.have_cc65() and
    musicdisk.have_disk_tools(),
    'the music disk needs DOOM1.WAD (tools/fetch_upstream.py), cc65 2.18 '
    '(ca65, ld65) and the existing port\'s disk tools (demos/doom/tools/'
    'build_disk.py, appletini-one/software/ProDOS_2_4_3.po)')

_built = {}


def built():
    """The songs, program and disk, built once into a directory of their
    own under build/, removed when the tests end; and a2vm."""
    if not _built:
        work = Path(tempfile.mkdtemp(prefix='test-musicdisk-',
                                     dir=str(support.BUILD))).resolve()
        atexit.register(shutil.rmtree, str(work), True)
        program, songs, everything = musicdisk.build(
            work / 'obj', work / 'MUSIC.hdv', work / 'DOOM_PROFILE.TXT')
        a2vm_dir, _ = support.a2vm_build()
        _built.update(work=work, program=program, songs=songs,
                      everything=everything, a2vm=a2vm_dir / 'a2vm')
    return _built


class Workspace(unittest.TestCase):
    def setUp(self):
        b = built()
        self.program, self.songs = b['program'], b['songs']
        self.everything, self.a2vm = b['everything'], b['a2vm']
        self.work = Path(tempfile.mkdtemp(dir=str(b['work'])))
        self.addCleanup(shutil.rmtree, str(self.work), True)


@needs_all
class Disk(Workspace):
    def test_volume(self):
        bd = musicdisk.disk_writer()
        image = bd.Image((built()['work'] / 'MUSIC.hdv').read_bytes())
        header, entries, _ = bd.list_volume(image)
        self.assertEqual(header['name'], 'MUSIC')
        names = [e['name'] for e in entries]
        self.assertEqual(names, ['MUSIC.SYSTEM', 'PRODOS'] +
                         [s.path for s in self.songs] + ['PROFILE.TXT'])
        system = bd.find_entry(entries, 'MUSIC.SYSTEM')
        self.assertEqual((system['file_type'], system['aux']), (0xFF, 0x2000))
        self.assertEqual(bd.read_file(image, system), self.program.system)
        for s in self.songs:
            entry = bd.find_entry(entries, s.path)
            self.assertEqual(bd.read_file(image, entry), s.data, s.name)
            self.assertEqual(entry['aux'], 0x1000)
        text = bd.read_file(image, bd.find_entry(entries, 'PROFILE.TXT'))
        self.assertIn(b'vtw.slowdown.cycles=32', text)
        self.assertNotIn(b'\n', text)       # ProDOS text: CR line ends
        self.assertIn('vtw.slowdown.cycles=32',
                      (built()['work'] / 'DOOM_PROFILE.TXT').read_text())

    def test_songs(self):
        self.assertEqual([s.name for s in self.songs],
                         list(musicdisk.SONGS))
        self.assertEqual([s.key for s in self.songs], list('ABCDEFGHIJKLM'))
        self.assertEqual(len({s.path for s in self.songs}), 13)

    def test_system_file(self):
        system = self.program.system
        self.assertEqual(len(system), 0x3700)
        self.assertNotEqual(system[0x2078:0x207C], musicdisk.A2LI)
        # ProDOS loads it at $2000-$56FF, below the program's buffers
        self.assertLessEqual(0x2000 + len(system), 0x5C00)


@needs_all
class Map(Workspace):
    def test_player_where_the_map_puts_it(self):
        seg = self.program.segments
        self.assertEqual(seg['SNDRING'][0], 0xE000)
        self.assertEqual(seg['SNDLIST'][0], 0xE480)
        self.assertEqual(seg['SNDBSS'][0], 0xE500)
        self.assertLessEqual(sum(seg['SNDBSS']), 0xE737)
        start, size = seg['SNDCODE']
        self.assertEqual(start, 0xE900)
        self.assertLessEqual(start + size + seg['SNDRODATA'][1], 0xF900)
        zp_start, zp_size = seg['SNDZP']
        self.assertGreaterEqual(zp_start, 0xD8)
        self.assertLessEqual(zp_start + zp_size, 0x100)
        vector = self.program.lc[0xFFFE - 0xE900:0x10000 - 0xE900]
        self.assertEqual(int.from_bytes(vector, 'little'),
                         self.program.labels['snd_vbl'])

    def test_program_data_outside_the_video_pages(self):
        seg = self.program.segments
        start, size = seg['MUSBSS']
        self.assertGreaterEqual(start, 0x0C00)
        self.assertLessEqual(start + size, 0x2000)
        start, size = seg['MUSZP']
        self.assertLess(start + size, 0xD8)


@needs_all
class OnA2vm(Workspace):
    def test_songs(self):
        got = musicdisk.check_songs(self.program, self.songs,
                                    self.everything, self.work, 20.0,
                                    self.a2vm)
        self.assertEqual(len(got['starts']), 13)
        # detect_video's timer 1 over one VBL: PAL's 20,280 cycles, give
        # or take the bus cycle the two reads fall in after their VBLs:
        # 20,279 on a2vm f121 since the card's calibration of 2026-10-03,
        # 20,280 before
        self.assertEqual(got['vblcyc'], 312 * 65 - 1)

    def test_keys(self):
        got = musicdisk.check_keys(self.program, self.songs,
                                   self.everything, self.work, self.a2vm)
        self.assertEqual(got['songs'], ['D_E1M1', 'D_E1M2', 'D_E1M3',
                                        'D_E1M2', 'D_INTROA', 'D_E1M1',
                                        'D_INTROA', 'D_INTROA', 'D_INTRO',
                                        'D_VICTOR'])
        self.assertEqual(got['test_writes'], 32 * (16 + 208))

    def test_quit(self):
        got = musicdisk.check_quit(self.program, self.songs,
                                   self.everything, self.work, self.a2vm)
        self.assertGreater(got['interrupts'], 20)

    def test_no_music(self):
        got = musicdisk.check_nomusic(self.program, self.songs,
                                      self.everything, self.work,
                                      self.a2vm)
        self.assertTrue(got['screen'][2].startswith('NO MUSIC.'))

    def test_aytime(self):
        for case in musicdisk.AYT_CASES:
            with self.subTest(case[0]):
                got = musicdisk.check_aytime(self.program, self.songs,
                                             self.everything, self.work,
                                             case, self.a2vm)
                self.assertEqual(got['verdict'], case[3])


@needs_all
class PlantedBugs(Workspace):
    def planted(self, name, old, new):
        """A program built from a copy of src/sound with `old` replaced by
        `new` in `name`."""
        source = self.work / 'src'
        shutil.copytree(str(musicdisk.SRC), str(source))
        path = source / name
        text = path.read_text()
        self.assertEqual(text.count(old), 1)
        path.write_text(text.replace(old, new))
        return musicdisk.build_program(self.songs, self.work / 'obj',
                                       source)

    def test_wrong_song_is_caught(self):
        program = self.planted('music.s', "sbc     #'A' - 1",
                               "sbc     #'A' - 2")
        with self.assertRaises(musicdisk.CheckFailed):
            musicdisk.check_songs(program, self.songs,
                                  musicdisk.files_of(program, self.songs),
                                  self.work, 2.0, self.a2vm)

    def test_slow_burst_is_caught(self):
        program = self.planted('aytime.s', '        dex\n        bne     '
                               'ayt_burst', '        nop\n        dex\n'
                               '        bne     ayt_burst')
        with self.assertRaises(musicdisk.CheckFailed) as caught:
            musicdisk.check_aytime(program, self.songs,
                                   musicdisk.files_of(program, self.songs),
                                   self.work, musicdisk.AYT_CASES[0],
                                   self.a2vm)
        self.assertIn('a write 43', str(caught.exception))

    def test_wrong_microseconds_are_caught(self):
        # the screen's conversion of cycles to microseconds 1% off
        program = self.planted('aytime.s', 'LOAD32  md, 100000000',
                               'LOAD32  md, 99000000')
        with self.assertRaises(musicdisk.CheckFailed) as caught:
            musicdisk.check_aytime(program, self.songs,
                                   musicdisk.files_of(program, self.songs),
                                   self.work, musicdisk.AYT_CASES[0],
                                   self.a2vm)
        self.assertIn('row 18', str(caught.exception))

    def test_slow_clock_is_caught(self):
        # the PAL clock counting 60 VBLs a second
        program = self.planted('music.s', 'set_rate:\n        lda     #50',
                               'set_rate:\n        lda     #60')
        with self.assertRaises(musicdisk.CheckFailed) as caught:
            musicdisk.check_songs(program, self.songs,
                                  musicdisk.files_of(program, self.songs),
                                  self.work, 6.0, self.a2vm)
        self.assertIn('the status row', str(caught.exception))

    def test_song_key_without_music_is_caught(self):
        # no guard: a song key reaches snd_start, which refuses the song
        program = self.planted('music.s', 'ldx     music\n        beq     '
                               '@none', 'ldx     music\n        nop\n'
                               '        nop')
        with self.assertRaises(musicdisk.CheckFailed) as caught:
            musicdisk.check_nomusic(program, self.songs,
                                    musicdisk.files_of(program, self.songs),
                                    self.work, self.a2vm)
        self.assertIn('the song key changed the screen',
                      str(caught.exception))

    def test_native_mode_after_the_quit_is_caught(self):
        # the quit leaves the Phasor with its 4 AY chips
        program = self.planted('music.s', 'quit_prodos:\n        bit     '
                               'PHASOR_MB\n', 'quit_prodos:\n')
        with self.assertRaises(musicdisk.CheckFailed) as caught:
            musicdisk.check_quit(program, self.songs,
                                 musicdisk.files_of(program, self.songs),
                                 self.work, self.a2vm)
        self.assertIn('not Mockingboard mode', str(caught.exception))

    def test_unchanged_copy_passes(self):
        program = self.planted('music.s', "sbc     #'A' - 1",
                               "sbc     #'A' - 1")
        got = musicdisk.check_songs(program, self.songs,
                                    musicdisk.files_of(program, self.songs),
                                    self.work, 2.0, self.a2vm)
        self.assertEqual(len(got['starts']), 13)


if __name__ == '__main__':
    unittest.main()
