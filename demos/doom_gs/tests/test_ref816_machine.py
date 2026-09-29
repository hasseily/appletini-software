"""Tests of the reference machine around the core: tools/ref816/make_image.py,
tools/ref816/shot.py, the command line of ref816 (main.c), and the
release image booting to its title screen.

make_image and shot are tested on synthetic data. The machine is built
with make into a temporary directory and run on small hand-made images.
The release tests need build/release/doom-hd.hdv and build/linkmap.json;
they run the game for up to 120 seconds of machine time (a few seconds
of host time) and skip when those files are missing.
"""

import contextlib
import io
import json
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

import support
from ref816 import make_image, run_script, script, shot, title
from v816 import hdv, prodos

have_tools = unittest.skipUnless(
    shutil.which('cc') and shutil.which('make'), 'cc or make is missing')
needs_linkmap = unittest.skipUnless(
    make_image.LINKMAP.exists(),
    '%s is missing: run python3 tools/v816/imgmatch.py first'
    % make_image.LINKMAP.relative_to(support.ROOT))

BLOCK = hdv.BLOCK
# Synthetic grey tables: the grey of $0RGB is GRAYS[G] = $0GGG.
TABLES = make_image.GreyTables(
    blue=bytes(16), green=bytes(range(0, 256, 16)), red=bytes(16),
    greys=tuple(0x111 * i for i in range(16)))


def picture_record():
    """A picture: pixel byte i is i & $FF, each row has the control
    byte of its number & $0F, colour c of palette p is $0pc0 + p."""
    record = bytearray(i & 0xff for i in range(make_image.SCREEN_SIZE))
    for row in range(200):
        record[make_image.PIXELS_END + row] = row & 15
    for number in range(16):
        for colour in range(16):
            struct.pack_into('<H', record,
                             make_image.PALETTES + 32 * number + 2 * colour,
                             number << 8 | colour << 4 | number)
    return bytes(record)


def synthetic_disk():
    """(disk bytes, parsed disk, picture) with every kind of segment."""
    picture = picture_record()
    order = support.picture_order()
    on_disk = b''.join(picture[b * BLOCK:(b + 1) * BLOCK] for b in order)
    stream, plain = support.B1_ABABAB
    data = support.make_disk([
        (0x2a0000, hdv.SEG_PIC, on_disk),
        (0x030000, 0, b'\xea' * 600),
        (0x400000, 0, b'S' * (3 * BLOCK)),
        (0x2a8000, hdv.SEG_B1, struct.pack('<H', len(plain)) + stream),
    ])
    return data, hdv.parse(data), picture


def loads_of(data, banks=make_image.RAM_BANKS):
    disk = hdv.parse(data)
    return make_image.records(disk, prodos.Volume(data), TABLES, banks)


class BootInfo(unittest.TestCase):
    def setUp(self):
        self.data, self.disk, _ = synthetic_disk()
        header = prodos.Volume(self.data).block(hdv.HEADER_BLOCK)
        self.header = header
        self.info = make_image.boot_info(self.disk, header, 0x80)

    def test_drive_and_files(self):
        info = self.info
        self.assertEqual(len(info), 100)
        self.assertEqual(info[0:2], b'DB')
        self.assertEqual((info[2], info[3]), (0x70, 1))
        self.assertEqual(struct.unpack_from('<HHH', info, 4),
                         (0xc70a, 0xc70d, self.disk.settings_block))
        self.assertEqual(info[10:12], b'\x01\x00')
        self.assertEqual(struct.unpack_from('<I', info, 12)[0], 0x12345678)

    def test_store_and_banks(self):
        info = self.info
        self.assertEqual(list(info[16:20]), [1, 1, 1, 1])
        self.assertEqual(info[20:36], b'\xff' * 16)
        self.assertEqual(info[36:100], self.header[368:432])
        self.assertNotEqual(info[36:100], bytes(64))

    def test_four_megabytes(self):
        info = make_image.boot_info(self.disk, self.header, 0x40)
        self.assertEqual(info[16], 0)
        self.assertEqual(info[20:36], b'\xff' * 8 + bytes(8))

    def test_bank_bitmap(self):
        self.assertEqual(make_image.ram_bitmap(10), b'\xff\x03' + bytes(14))

    def test_addresses_match_the_machine(self):
        text = (support.ROOT / 'tools' / 'ref816' / 'iigs.h').read_text()
        entry = re.search(r'IIGS_DRIVER_ENTRY = (0x[0-9a-f]+)', text)
        slot = re.search(r'IIGS_DISK_SLOT = (\d+)', text)
        self.assertEqual(int(entry.group(1), 16), make_image.DRIVER_ENTRY)
        self.assertEqual(int(slot.group(1)), make_image.DISK_SLOT)
        self.assertIn('SMARTPORT_ENTRY = IIGS_DRIVER_ENTRY + 3', text)


class Records(unittest.TestCase):
    def setUp(self):
        self.data, self.disk, self.picture = synthetic_disk()
        self.loads = loads_of(self.data)
        self.addresses = [address for address, _ in self.loads]

    def test_memory_probe_comes_first(self):
        probes = self.loads[:0x7e]
        self.assertEqual(probes[0], (0x7f8000, b'\x7f\x80'))
        self.assertEqual(probes[-1], (0x028000, b'\x02\xfd'))

    def test_order_of_the_loader(self):
        after = self.addresses[0x7e:]
        self.assertEqual(after[:3], [0x006000, 0x007800, 0x2a0000])
        self.assertEqual(after[-3:], [0x007a00, 0x007e00, 0xe12000])
        self.assertIn(0x400000, after)
        # The B1 stream goes to the stage bank just before its decoding.
        stage = after.index(0x300000)
        self.assertEqual(after[stage + 1], 0x2a8000)

    def test_contents(self):
        loads = dict(self.loads[0x7e:])
        self.assertEqual(loads[0x2a0000], self.picture)
        self.assertEqual(loads[0x2a8000], support.B1_ABABAB[1])
        self.assertEqual(loads[0x006000], self.disk.loader)
        self.assertEqual(loads[0x007800][:6], b'DOOMGS')
        self.assertEqual(loads[0x007a00], b'S' * BLOCK)   # the settings

    def test_store_needs_its_banks(self):
        addresses = [address for address, _ in loads_of(self.data, 0x40)]
        self.assertNotIn(0x400000, addresses)

    def test_one_disk_only(self):
        data = bytearray(self.data)
        data[BLOCK + hdv.HDR_DISKS] = 2
        with self.assertRaises(ValueError):
            loads_of(bytes(data))


class Screen(unittest.TestCase):
    def setUp(self):
        self.picture = picture_record()
        self.screen = make_image.loader_screen(self.picture, TABLES)

    def test_pixels_without_the_strip(self):
        strip = make_image.STRIP
        self.assertEqual(self.screen[:strip], self.picture[:strip])
        self.assertEqual(self.screen[strip:make_image.PIXELS_END],
                         bytes(make_image.PIXELS_END - strip))

    def test_control_bytes(self):
        start = make_image.PIXELS_END
        self.assertEqual(self.screen[start:start + 200],
                         self.picture[start:start + 200])

    def test_palettes_0_to_14_grey(self):
        def colour(number, index):
            return struct.unpack_from(
                '<H', self.screen,
                make_image.PALETTES + 32 * number + 2 * index)[0]
        self.assertEqual(colour(3, 5), 0x555)
        self.assertEqual(colour(14, 15), 0xfff)
        self.assertEqual(colour(15, 7), 0xf7f)      # palette 15 kept

    def test_tables_from_the_link_map(self):
        data, disk, _ = synthetic_disk()
        labels = {'GRAY_B': 0x6000, 'GRAY_G': 0x6010, 'GRAY_R': 0x6020,
                  'GRAYS': 0x6030}
        linkmap = {'loader': {'units': {'loader.s': labels}}}
        tables = make_image.grey_tables(disk, linkmap)
        self.assertEqual(tables.blue, b'\x60' * 16)
        self.assertEqual(tables.greys, (0x6060,) * 16)
        labels['GRAYS'] = 0x6000 + len(disk.loader) - 8
        with self.assertRaises(ValueError):
            make_image.grey_tables(disk, linkmap)


class ImageFile(unittest.TestCase):
    def test_header(self):
        registers = make_image.entry_registers(0x030000)
        image = make_image.image_bytes(registers, [(0x1234, b'ab')])
        self.assertEqual(image[:8], b'REF816I1')
        self.assertEqual(struct.unpack_from('<HBBHHHHHBB', image, 8),
                         (0, 3, 0, 3, 0, 0, 0x1fb, 0, 0x05, 0))
        self.assertEqual(list(image[24:28]), [0xc1, 0, 0x08, 0x80])
        self.assertEqual(image[32:], struct.pack('<II', 0x1234, 2) + b'ab')

    def test_loader_starts_as_the_boot_block_leaves_it(self):
        _, disk, _ = synthetic_disk()
        registers = make_image.loader_registers(disk)
        self.assertEqual((registers.pbr, registers.pc), (0, 0x6000))
        self.assertEqual((registers.e, registers.x), (1, 0x70))

    def test_shadow_copies(self):
        data = bytes(range(256)) * 3
        self.assertEqual(make_image.with_shadow(0x003f00, data), [
            (0x003f00, data), (0xe03f00, data)])
        self.assertEqual(make_image.with_shadow(0x010300, data[:0x200]), [
            (0x010300, data[:0x200]), (0xe10400, data[0x100:0x200])])
        self.assertEqual(make_image.with_shadow(0x005f00, data), [
            (0x005f00, data), (0xe05f00, data[:0x100])])
        self.assertEqual(make_image.with_shadow(0x024000, data),
                         [(0x024000, data)])
        with self.assertRaises(ValueError):
            make_image.with_shadow(0x00ff00, data)


def decode_png(data):
    """(width, height, rows of RGB bytes) of a PNG from shot.png."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    position, idat = 8, b''
    while position < len(data):
        length = struct.unpack_from('>I', data, position)[0]
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        crc = struct.unpack_from('>I', data, position + 8 + length)[0]
        assert crc == zlib.crc32(kind + body) & 0xffffffff
        if kind == b'IHDR':
            width, height = struct.unpack_from('>II', body)
            assert body[8:] == bytes([8, 2, 0, 0, 0])
        elif kind == b'IDAT':
            idat += body
        position += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + 3 * width
    rows = [raw[y * stride:(y + 1) * stride] for y in range(height)]
    assert all(row[0] == 0 for row in rows)
    return width, height, [row[1:] for row in rows]


def dump(control=0, fill_pixels=b'', border=None):
    """A screen dump: palette p colour c is $0pc0 + ... as in
    picture_record; every row has control byte `control`."""
    screen = bytearray(picture_record())
    screen[shot.SCB:shot.SCB + 200] = bytes([control]) * 200
    screen[:len(fill_pixels)] = fill_pixels
    if border is not None:
        screen += bytes([border, 0xc1])
    return bytes(screen)


class Shot(unittest.TestCase):
    def test_320_mode(self):
        picture = shot.render(dump(control=2, fill_pixels=b'\x12\x30'))
        self.assertEqual((picture.width, picture.height), (320, 200))
        # Palette 2: colour c is $02c2.
        self.assertEqual(picture.rows[0][:4], [
            shot.rgb(0x212), shot.rgb(0x222), shot.rgb(0x232),
            shot.rgb(0x202)])

    def test_fill_mode(self):
        picture = shot.render(dump(control=0x22, fill_pixels=b'\x12\x30'))
        self.assertEqual(picture.rows[0][3], shot.rgb(0x232))

    def test_640_mode_doubles_the_other_rows(self):
        screen = bytearray(dump(control=1, fill_pixels=b'\x1b'))
        screen[shot.SCB] = 0x81             # row 0 in 640 mode
        picture = shot.render(bytes(screen))
        self.assertEqual((picture.width, picture.height), (640, 400))
        # $1B = 00 01 10 11: colours 8, 13, 2 and 7 of palette 1.
        self.assertEqual(picture.rows[0][:4], [
            shot.rgb(0x181), shot.rgb(0x1d1), shot.rgb(0x121),
            shot.rgb(0x171)])
        self.assertEqual(picture.rows[1], picture.rows[0])
        self.assertEqual(picture.rows[2][0], picture.rows[2][1])

    def test_border(self):
        picture = shot.render(dump(border=0x19), border=4)
        self.assertEqual((picture.width, picture.height), (328, 208))
        self.assertEqual(picture.rows[0][0], shot.rgb(0xf60))   # orange
        self.assertEqual(picture.rows[4][3], shot.rgb(0xf60))
        self.assertEqual(picture.rows[4][4], shot.rgb(0x000))
        black = shot.render(dump(), border=1)
        self.assertEqual(black.rows[0][0], (0, 0, 0))

    def test_png_round_trip(self):
        picture = shot.render(dump(control=5, fill_pixels=b'\xf0'))
        width, height, rows = decode_png(shot.png(picture))
        self.assertEqual((width, height), (320, 200))
        self.assertEqual(rows[0][:6], bytes(shot.rgb(0x5f5) +
                                            shot.rgb(0x505)))

    def test_stats(self):
        info = shot.stats(shot.render(dump(control=3)))
        self.assertEqual((info.width, info.height), (320, 200))
        self.assertEqual(info.colours, 16)
        self.assertAlmostEqual(info.commonest_share, 1 / 16)

    def test_wrong_size(self):
        with self.assertRaises(ValueError):
            shot.render(bytes(100))


def tiny_image(code, x=0x1111, s=0x2345):
    """A memory image that starts `code` at $03:0000 in native mode."""
    registers = make_image.Registers(pc=0, pbr=3, dbr=0, a=0, x=x, y=0,
                                     s=s, d=0, p=0x04, e=0)
    return make_image.image_bytes(registers, [(0x030000, bytes(code))])


@have_tools
class CommandLine(unittest.TestCase):
    def setUp(self):
        out, _ = support.ref816_build()
        self.machine = out / 'ref816'
        self.directory = Path(tempfile.mkdtemp(dir=str(out)))
        self.addCleanup(shutil.rmtree, str(self.directory))

    def machine_run(self, image, *arguments):
        path = self.directory / 'test.img'
        path.write_bytes(image)
        return subprocess.run(
            [str(self.machine), str(path)] + [str(a) for a in arguments],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)

    def state(self, image, *arguments):
        result = self.machine_run(image, *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    # rep #$30 / txa / sta $7F0000 / tsc / sta $7F0002 / stp
    STORE_X_S = [0xc2, 0x30, 0x8a, 0x8f, 0, 0, 0x7f, 0x3b,
                 0x8f, 2, 0, 0x7f, 0xdb]

    def test_registers_and_records(self):
        state = self.state(tiny_image(self.STORE_X_S), '--cycles', 1000,
                           '--peek', '7F0000:4')
        self.assertEqual(state['peek']['7F0000'], '11114523')
        self.assertEqual(state['cpu']['state'], 'stopped')
        self.assertEqual(state['cpu']['pc'], 0x03000d)
        self.assertEqual(state['switches']['shadow'], 0x08)
        self.assertEqual(state['cycles'], 1000)

    def test_frames_and_time(self):
        state = self.state(tiny_image([0x80, 0xfe]), '--frames', 60)
        self.assertEqual(state['frames'], 60)
        self.assertAlmostEqual(state['seconds'], 60 / 59.92, places=3)
        # One oscillator enabled at power-on: a sample every 48 clocks.
        self.assertAlmostEqual(state['doc']['samples'],
                               state['master_clocks'] // 48, delta=1)

    def test_same_run_same_state(self):
        image = tiny_image(self.STORE_X_S)
        first = self.state(image, '--frames', 3)
        self.assertEqual(first, self.state(image, '--frames', 3))
        other = self.state(tiny_image(self.STORE_X_S, x=0x2222),
                           '--frames', 3)
        self.assertNotEqual(first['ram_fnv1a64'], other['ram_fnv1a64'])

    def test_screen_dumps(self):
        # lda ##$4321 / sta $E12000 / stp, in native mode.
        code = [0xc2, 0x30, 0xa9, 0x21, 0x43, 0x8f, 0x00, 0x20, 0xe1, 0xdb]
        self.state(tiny_image(code), '--frames', 3, '--shot-frame', 2,
                   '--shot-cycle', 1, '--shot-dir', self.directory)
        early = (self.directory / 'cycle-000000000001.shr').read_bytes()
        late = (self.directory / 'frame-000002.shr').read_bytes()
        self.assertEqual(len(late), 0x8002)
        self.assertEqual(late[:2], b'\x21\x43')
        self.assertEqual(early[:2], b'\x00\x00')
        self.assertEqual(late[-2:], b'\x00\xc1')    # $C034, $C029

    def test_errors(self):
        image = tiny_image([0xdb])
        for arguments, message in [
                ((), 'give --frames or --cycles'),
                (('--frames', 'x'), 'not a number'),
                (('--frames', 1, '--bogus', 1), 'unknown option'),
                (('--frames', 1, '--disk-out', 'x'), '--disk-out needs')]:
            result = self.machine_run(image, *arguments)
            self.assertEqual(result.returncode, 2, arguments)
            self.assertIn(message, result.stderr)
        result = self.machine_run(b'NOTANIMAGE' + bytes(30), '--frames', 1)
        self.assertIn('not a ref816 memory image', result.stderr)
        cut = tiny_image([0xdb])[:-1]
        result = self.machine_run(cut, '--frames', 1)
        self.assertIn('cut short', result.stderr)

    def test_disk_out_keeps_the_input(self):
        disk = self.directory / 'disk.po'
        disk.write_bytes(bytes(range(256)) * 4)
        copy = self.directory / 'copy.po'
        self.state(tiny_image([0xdb]), '--frames', 1, '--disk', disk,
                   '--disk-out', copy)
        self.assertEqual(copy.read_bytes(), disk.read_bytes())


@have_tools
@support.needs_release
@needs_linkmap
class Release(unittest.TestCase):
    """The release image on the machine, from make_image.py's memory."""

    @classmethod
    def setUpClass(cls):
        title.build_machine()
        with contextlib.redirect_stdout(io.StringIO()):
            if make_image.main([]):
                raise AssertionError('make_image.py failed')

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(dir=str(title.OUT)))
        self.addCleanup(shutil.rmtree, str(self.scratch))

    def test_title_screen(self):
        path, info = title.title_picture()
        self.assertEqual((info.width, info.height), (320, 200))
        self.assertGreater(info.colours, 8)
        self.assertLess(info.commonest_share, 0.5)
        # The loader left the picture grey; the title page has colour.
        _, _, rows = decode_png(path.read_bytes())
        coloured = sum(1 for row in rows for x in range(0, len(row), 3)
                       if not row[x] == row[x + 1] == row[x + 2])
        self.assertGreater(coloured, 320 * 200 // 2)

    def test_clock_runs_at_35_tics_a_second(self):
        rate = title.tic_rate()
        self.assertGreater(rate, 34.5)
        self.assertLess(rate, 35.5)

    def test_same_arguments_same_run(self):
        self.assertEqual(title.run(2200), title.run(2200))

    def input_run(self, script):
        """The key ring and the menu flag at frame 2700 after `script`,
        which acts on the title page (any key or button opens the menu
        there)."""
        ring = title.symbol('iigs_asm.s', 'iigs_adbq')
        menu = title.symbol('m_menu65.s', '_g_menuactive')
        path = self.scratch / 'input.txt'
        path.write_text(script)
        state = title.run(2700, peeks=[(ring, 4), (menu, 2)],
                          input_file=path)
        return state['peek']['%06X' % ring], title.peeked(state, menu)

    def test_keys_reach_the_game(self):
        ring, menu = self.input_run('2500 key 0x35 down\n'
                                    '2505 key 0x35 up\n')
        self.assertEqual(ring, '35b50000')       # Escape down and up
        self.assertEqual(menu, 1)

    def test_mouse_buttons_reach_the_game(self):
        ring, menu = self.input_run('2500 button 0 down\n'
                                    '2500 mouse 30 -20\n'
                                    '2510 button 0 up\n')
        self.assertEqual(ring, '7efe0000')       # the fire key down, up
        self.assertEqual(menu, 1)

    def test_settings_save_writes_one_block(self):
        """The menu's SAVE SETTINGS, after MESSAGES is turned off, writes
        DOOM.SETTINGS through the block driver; the disk file given to
        the machine stays as it was."""
        keys = [(0x35, 2500), (0x3d, 2530), (0x24, 2560), (0x24, 2590)]
        keys += [(0x3d, 2620 + 30 * i) for i in range(4)]
        keys += [(0x24, 2740)]
        path = self.scratch / 'input.txt'
        path.write_text(''.join('%d key %d down\n%d key %d up\n'
                                % (frame, code, frame + 5, code)
                                for code, frame in keys))
        saved = self.scratch / 'saved.hdv'
        before = title.DISK.read_bytes()
        state = title.run(3000, input_file=path,
                          options=['--disk-out', str(saved)])
        self.assertTrue(state['firmware']['disk_written'])
        self.assertEqual(state['firmware']['errors'], 0)
        self.assertEqual(title.DISK.read_bytes(), before)
        after = saved.read_bytes()
        changed = {i // BLOCK for i in range(0, len(after), 64)
                   if after[i:i + 64] != before[i:i + 64]}
        block = hdv.parse(before).settings_block
        self.assertEqual(changed, {block})
        settings = after[block * BLOCK:(block + 1) * BLOCK]
        self.assertEqual(settings[:7], b'DOOMSET')
        self.assertEqual(settings[14], 0)           # messages off

    def test_four_megabytes_reads_levels_from_disk(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(make_image.main(
                ['--banks', '64', '--out', str(self.scratch)]), 0)
        demo = title.symbol('g_game65.s', '_g_demoplayback')
        state = title.run(7200, peeks=[(demo, 2)], image_dir=self.scratch)
        self.assertGreater(state['firmware']['driver_calls'], 1000)
        self.assertEqual(state['firmware']['errors'], 0)
        self.assertEqual(title.peeked(state, demo), 1)

    def test_memory_is_what_the_real_loader_leaves(self):
        """Upstream's loader, run on the machine from the boot block's
        state to the entry point, leaves the memory of memory.img but
        for its direct page and stack, its own variables and the load
        strip, which make_image.py does not draw."""
        loader_dump = self.scratch / 'loader.bin'
        image_dump = self.scratch / 'image.bin'
        loader = title.run_image(
            title.OUT / 'loader.img',
            ['--stop-pc', '030000', '--cycles', '1000000000',
             '--dump-ram', str(loader_dump)])
        image = title.run_image(
            title.MEMORY, ['--cycles', '0', '--dump-ram', str(image_dump)])
        self.assertTrue(loader['stopped_at_pc'])
        self.assertEqual(loader['firmware']['errors'], 0)
        for name in ('pc', 'x', 's', 'd', 'dbr', 'p', 'e'):
            self.assertEqual(loader['cpu'][name], image['cpu'][name], name)
        self.assertEqual(loader['cpu']['a'] & 0xff, image['cpu']['a'])
        self.assertEqual(loader['switches'], image['switches'])
        first, second = loader_dump.read_bytes(), image_dump.read_bytes()
        allowed = [(0x000000, 0x000200), (0x006000, 0x006c00),
                   (0xe19760, 0xe19d00)]
        page = 256
        for start in range(0, len(first), page):
            if first[start:start + page] == second[start:start + page]:
                continue
            for offset in range(page):
                if first[start + offset] != second[start + offset]:
                    at = start + offset
                    address = at if at < 0x800000 else at + 0xe00000 - 0x800000
                    self.assertTrue(
                        any(low <= address < high for low, high in allowed),
                        'memory differs at $%06X' % address)

    def test_only_known_gaps_in_the_model(self):
        """A run into the first demo meets no hardware the model lacks
        but the serial controller, which the game only switches off, and
        the ROM and bank $BC reads of run_script.KNOWN_READS, each as
        often as it says."""
        state = title.run(7200)
        missing = state['unmodelled']
        self.assertEqual(set(missing['io_reads']) | set(missing['io_writes']),
                         {'C039'})
        with open(str(make_image.LINKMAP)) as handle:
            symbols = script.Symbols(json.load(handle))
        self.assertEqual(run_script.unexplained_reads(missing, symbols), [])
        for kind in ('rom', 'unmapped'):
            known = [k for k in run_script.KNOWN_READS if k.kind == kind]
            self.assertEqual(missing[kind + '_reads'],
                             sum(k.count for k in known), kind)
            self.assertEqual(
                sorted(run_script.function_of(symbols, site['pc'])
                       for site in missing[kind + '_read_sites']),
                sorted('%s:%s' % (k.unit, k.label) for k in known), kind)
        self.assertEqual(missing['rom_writes'], 0)
        self.assertEqual(missing['slot_rom_reads'], 0)
        self.assertEqual(missing['unmapped_writes'], 0)
        self.assertEqual(missing['adb_unknown_commands'], 0)
        self.assertEqual(state['firmware']['errors'], 0)
        self.assertGreater(state['interrupts'], 0)



if __name__ == '__main__':
    unittest.main()
