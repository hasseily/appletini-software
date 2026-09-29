"""Tests of tools/a2vm, stage 3.1b: the machine around the core.

  - the memory map: every combination of 80STORE, RAMRD, RAMWRT, ALTZP,
    PAGE2 and HIRES with every language-card state and several RamWorks
    banks, against a small Python model, through the page tables and
    through reads and writes on the bus; the language card's switch
    sequence; the video and SHR write counts;
  - the devices: status reads, $C019 against the clock (with a2sim.py's
    I/O surcharge counted before the read), the keyboard, the buttons,
    the mouse card and its VBL interrupt;
  - the memory API: every validation error of README_MEMORY_API.md
    version 1, successful COPY and FILL, the FIFO transport;
  - the MLI trap: a program making ProDOS calls, with hand-made
    expectations, and the volume directory against the existing port's
    tools/build_disk.py;
  - shot.py on hand-made screens.

With build/venv (py65 and Pillow, see tools/a2vm/README.md) the same
programs and bus operations also run on demos/doom/tools/a2sim.py and
must leave the same state and RAM; the compatibility core is compared
with py65 on random cases; and a short run of the existing Doom port is
compared with a2sim.py. Those tests skip without build/venv.
"""

import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import support
from a2vm import compare_a2sim, doom, shot

VENV = support.BUILD / 'venv' / 'bin' / 'python'
DOOM_TOOLS = doom.DOOM / 'tools'

have_tools = unittest.skipUnless(
    shutil.which('cc') and shutil.which('make'), 'cc or make is missing')


def venv_ready():
    if not VENV.exists():
        return False
    result = subprocess.run([str(VENV), '-c', 'import py65, PIL'],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return result.returncode == 0 and (DOOM_TOOLS / 'a2sim.py').exists()


VENV_READY = venv_ready()
needs_venv = unittest.skipUnless(
    VENV_READY, '%s with py65 and Pillow, or %s, is missing (see '
    'tools/a2vm/README.md)' % (VENV.relative_to(support.ROOT),
                               DOOM_TOOLS / 'a2sim.py'))
needs_doom = unittest.skipUnless(
    (doom.DEFAULT_BUILD / 'doom.lbl').exists() and
    doom.DEFAULT_DATA.is_dir() and doom.DEFAULT_ROM.exists(),
    'the existing port\'s build %s, its data or the ROM %s is missing'
    % (doom.DEFAULT_BUILD, doom.DEFAULT_ROM))

SWITCH_ADDRESSES = {        # name: (off, on), written
    'store80': (0xc000, 0xc001), 'ramrd': (0xc002, 0xc003),
    'ramwrt': (0xc004, 0xc005), 'altzp': (0xc008, 0xc009),
    'page2': (0xc054, 0xc055), 'hires': (0xc056, 0xc057)}


def synthetic_rom(directory):
    path = Path(directory) / 'rom.bin'
    path.write_bytes(bytes((i * 7 + 3) & 0xff for i in range(0x4000)))
    return path


class Workspace(unittest.TestCase):
    """A build of a2vm and a directory of its own under build/."""

    def setUp(self):
        self.out, _ = support.a2vm_build()
        self.directory = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.directory), True)
        self.rom = synthetic_rom(self.directory)

    def bus(self, lines, *arguments):
        """Run a bus script; its output lines."""
        script = self.directory / 'bus.txt'
        script.write_text('\n'.join(lines) + '\n')
        result = subprocess.run(
            [str(self.out / 'a2vm'), '--rom', str(self.rom)] +
            [str(a) for a in arguments] + ['--bus-script', str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result.stdout.splitlines()

    @staticmethod
    def reads(lines):
        return [int(line.split()[2], 16) for line in lines
                if line.startswith('read ')]

    @staticmethod
    def peeks(lines):
        return [int(line.split()[4], 16) for line in lines
                if line.startswith('peek ')]

    @staticmethod
    def state(lines):
        start = max(i for i, line in enumerate(lines) if line == '{')
        return json.loads('\n'.join(lines[start:]))


# ---- the memory map -------------------------------------------------------

class MapModel:
    """The //e memory map as a2sim.py describes it, written from its rules:
    where a read and a write of an address go."""

    def __init__(self, banks=128):
        self.banks = banks
        self.sw = dict(store80=0, ramrd=0, ramwrt=0, altzp=0, page2=0,
                       hires=0)
        self.lc_read = self.lc_write = self.lc_prewrite = 0
        self.lc_bank2 = 1
        self.bank = 0

    def lc_switch(self, low, is_read):
        self.lc_bank2 = int(not low & 8)
        self.lc_read = int((low & 3) in (0, 3))
        if low & 1:
            if is_read:
                if self.lc_prewrite:
                    self.lc_write = 1
                self.lc_prewrite = 1
            else:
                self.lc_prewrite = 0
        else:
            self.lc_write = self.lc_prewrite = 0

    def aux(self, address, flag):
        if self.sw['store80']:
            if 0x0400 <= address < 0x0800:
                return self.sw['page2']
            if self.sw['hires'] and 0x2000 <= address < 0x4000:
                return self.sw['page2']
        return self.sw[flag]

    def target(self, address, write):
        """('main'|'aux'|'lc'|'lc1'|'rom', bank, address in that storage),
        None for a write the card protects, 'io' for $C000-$CFFF."""
        if address < 0x0200:
            return ('aux', self.bank, address) if self.sw['altzp'] \
                else ('main', 0, address)
        if address < 0xc000:
            if self.aux(address, 'ramwrt' if write else 'ramrd'):
                return ('aux', self.bank, address)
            return ('main', 0, address)
        if address < 0xd000:
            return 'io'
        if not (self.lc_write if write else self.lc_read):
            return None if write else ('rom', 0, address)
        bank1 = address < 0xe000 and not self.lc_bank2
        if self.sw['altzp']:
            return ('aux', self.bank, address - 0x1000 if bank1 else address)
        if bank1:
            return ('lc1', 0, address)
        return ('lc', 0, address)

    def describe(self, page, write):
        t = self.target(page << 8, write)
        if t == 'io' or t is None:
            return '-'
        kind, bank, address = t
        prefix = {'main': 'M', 'lc': 'L', 'lc1': '1', 'rom': 'R'}.get(kind)
        return '%s:%02X' % (prefix or 'A%d' % bank, address >> 8)


LC_SETTINGS = {         # (read, write, bank2): the accesses that set it
    (1, 1, 1): ['read C083', 'read C083'],
    (0, 1, 1): ['read C081', 'read C081'],
    (1, 0, 1): ['read C080'],
    (0, 0, 1): ['read C082'],
    (1, 1, 0): ['read C08B', 'read C08B'],
    (0, 1, 0): ['read C089', 'read C089'],
    (1, 0, 0): ['read C088'],
    (0, 0, 0): ['read C08A'],
}
PROBES = (0x0000, 0x00ff, 0x0100, 0x01ff, 0x0200, 0x03ff, 0x0400, 0x07ff,
          0x0800, 0x0bff, 0x1fff, 0x2000, 0x3fff, 0x4000, 0x5fff, 0x6000,
          0x9fff, 0xa000, 0xbfff, 0xd000, 0xdfff, 0xe000, 0xffff)
STORAGE = {'main': 'main', 'aux': 'aux', 'lc': 'lc', 'lc1': 'lc1'}


@have_tools
class MemoryMap(Workspace):
    """Every switch and bank combination against MapModel."""

    def check_combinations(self, banks, bank_values):
        model = MapModel(banks)
        lines, expected_map, expected_reads, expected_peeks = [], [], [], []
        video = shr = 0
        value = 0
        for combination in range(64):
            for lc, accesses in LC_SETTINGS.items():
                for bank_value in bank_values:
                    for bit, name in enumerate(SWITCH_ADDRESSES):
                        on = combination >> bit & 1
                        lines.append('write %04X 00'
                                     % SWITCH_ADDRESSES[name][on])
                        model.sw[name] = on
                    lines.append('write C073 %02X' % bank_value)
                    model.bank = (bank_value & 0x7f) % banks
                    for access in accesses:
                        lines.append(access)
                        model.lc_switch(int(access[-1], 16), True)
                        expected_reads.append(0)
                    self.assertEqual((model.lc_read, model.lc_write,
                                      model.lc_bank2), lc)
                    lines.append('map')
                    expected_map.append(
                        ('map ' + ' '.join(model.describe(p, False)
                                           for p in range(256)),
                         'wmap ' + ' '.join(model.describe(p, True)
                                            for p in range(256))))
                    for address in PROBES:
                        value = (value + 37) & 0xff
                        source = model.target(address, False)
                        if source[0] != 'rom':
                            lines.append('poke %s %d %04X %02X' % (
                                STORAGE[source[0]], source[1], source[2],
                                value))
                            expected = value
                        else:
                            expected = (((address - 0xc000) * 7 + 3) & 0xff)
                        lines.append('read %04X' % address)
                        expected_reads.append(expected)
                        value = (value + 37) & 0xff
                        lines.append('write %04X %02X' % (address, value))
                        target = model.target(address, True)
                        if target is not None:
                            lines.append('peek %s %d %04X' % (
                                STORAGE[target[0]], target[1], target[2]))
                            expected_peeks.append(value)
                            if 0x0200 <= address < 0xc000:
                                if target[0] == 'aux':
                                    if model.bank == 0 and (
                                            0x400 <= address < 0xc00 or
                                            0x2000 <= address < 0xa000):
                                        video += 1
                                        shr += address >= 0x2000
                                elif 0x400 <= address < 0xc00 or \
                                        0x2000 <= address < 0x6000:
                                    video += 1
        lines.append('counts')
        output = self.bus(lines, '--banks', banks)
        maps = [line for line in output if line.startswith(('map', 'wmap'))]
        self.assertEqual(len(maps), 2 * len(expected_map))
        for i, (read_map, write_map) in enumerate(expected_map):
            self.assertEqual(maps[2 * i], read_map, 'combination %d' % i)
            self.assertEqual(maps[2 * i + 1], write_map, 'combination %d' % i)
        self.assertEqual(self.reads(output), expected_reads)
        self.assertEqual(self.peeks(output), expected_peeks)
        counts = [line for line in output if line.startswith('counts')][0]
        self.assertEqual([int(x) for x in counts.split()[2:4]], [video, shr])

    def test_every_combination_128_banks(self):
        self.check_combinations(128, (0x00, 0x01, 0x7f, 0x85))

    def test_bank_aliasing_with_3_banks(self):
        # $C073 values past the last bank alias modulo the bank count
        self.check_combinations(3, (0x02, 0x05, 0x83))

    def test_hand_made_cases(self):
        lines = self.bus([
            # ALTZP with LC bank 1: $D000 is the selected bank's $C000
            'write C073 05', 'write C009 00', 'read C08B', 'read C08B',
            'poke aux 5 C000 5A', 'read D000',
            'write D001 A5', 'peek aux 5 C001',
            # ALTZP off, bank 2: main LC $D000
            'write C008 00', 'read C083', 'poke lc 0 D000 C3', 'read D000',
            # 80STORE with PAGE2 wins over RAMRD for $0400-$07FF
            'write C003 00', 'write C001 00', 'write C054 00',
            'poke main 0 0400 11', 'poke aux 5 0400 22', 'read 0400',
            'poke aux 5 0800 33', 'read 0800',
            # $C071 selects too, bit 7 ignored
            'write C071 86', 'poke aux 6 0800 44', 'read 0800',
        ])
        self.assertEqual(self.reads(lines),
                         [0, 0, 0x5a, 0, 0xc3, 0x11, 0x33, 0x44])
        self.assertEqual(self.peeks(lines), [0xa5])


@have_tools
class LanguageCard(Workspace):
    def test_switch_sequences(self):
        rng = random.Random(3)
        model = MapModel()
        lines, expected = [], []
        for _ in range(600):
            low = 0x80 + rng.randrange(16)
            is_read = rng.random() < 0.7
            lines.append(('read C0%02X' if is_read else 'write C0%02X 00')
                         % low)
            lines.append('lc')
            model.lc_switch(low, is_read)
            expected.append('lc %d %d %d %d' % (
                model.lc_read, model.lc_write, model.lc_prewrite,
                model.lc_bank2))
        output = self.bus(lines)
        self.assertEqual([line for line in output if line.startswith('lc')],
                         expected)


# ---- devices ------------------------------------------------------------

@have_tools
class Devices(Workspace):
    def test_status_reads(self):
        lines = ['hold 41']
        expected = []
        for name, (off, on) in SWITCH_ADDRESSES.items():
            status = {'store80': 0x18, 'ramrd': 0x13, 'ramwrt': 0x14,
                      'altzp': 0x16, 'page2': 0x1c, 'hires': 0x1d}[name]
            lines += ['write %04X 00' % on, 'read C0%02X' % status,
                      'write %04X 00' % off, 'read C0%02X' % status]
            expected += [0x80 | 0x41, 0x41]
        self.assertEqual(self.reads(self.bus(lines)), expected)

    def test_vbl_counts_the_surcharge_first(self):
        # turbo: 1,250,000 cycles a frame, VBL from cycle 916,030; the
        # 73 cycles of the access are added before $C019 is read
        lines = self.bus(['clock 0', 'read C019', 'clock 915956',
                          'read C019', 'clock 915957', 'read C019',
                          'clock 1249926', 'read C019', 'clock 1249927',
                          'read C019', 'counts'])
        self.assertEqual(self.reads(lines), [0x80, 0x80, 0x00, 0x00, 0x80])
        lines = self.bus(['clock 12479', 'read C019', 'clock 12480',
                          'read C019'], '--speed', 1)
        self.assertEqual(self.reads(lines), [0x80, 0x00])

    def test_keyboard(self):
        lines = self.bus([
            'press 41 1000', 'clock 0', 'read C000', 'clock 1000',
            'read C000', 'read C010', 'read C000',
            'hold 57', 'read C000', 'read C010', 'release', 'read C010',
            'read C000'], '--io-cycles', 0)
        self.assertEqual(self.reads(lines),
                         [0x00, 0xc1, 0x41, 0x41, 0xd7, 0xd7, 0x57, 0x57])

    def test_buttons_and_paddles(self):
        lines = self.bus(['button 0 80', 'button 1 80', 'read C061',
                          'read C062', 'button 1 0', 'read C062',
                          'clock 0', 'write C070 00', 'clock 1300',
                          'read C064', 'clock 1500', 'read C064'],
                         '--speed', 1)
        self.assertEqual(self.reads(lines), [0x80, 0x80, 0x00, 0x80, 0x00])

    def test_mouse_card(self):
        lines = self.bus([
            'read C205', 'read C207', 'read C20B', 'read C20C',
            'write C0AE 09',                    # enable, VBL interrupt
            'mouse 10 0', 'read C0A0', 'read C0A1', 'read C0A6',
            'write C0AF 03', 'read C0A0',
            'mouse-to 70000 5', 'read C0A1', 'read C0A2',   # clamped
            'write C0A7 00', 'write C0A8 00', 'write C0A9 00',
            'write C0AA 00', 'write C0AB 01', 'write C0AC 02',
            'mouse 0 0', 'read C0A2',
            'buttons 1 0', 'read C0A5'])
        self.assertEqual(self.reads(lines), [
            0x38, 0x18, 0x01, 0x20,
            0x20, 10, 1, 0x00,
            0xff, 0x03, 0x01, 0x01])

    def test_vbl_interrupt_reaches_the_program(self):
        # $0300: CLI; JMP $0301. The IRQ handler at $0400 acknowledges
        # the card and counts in $10.
        code = [0x58, 0x4c, 0x01, 0x03]
        handler = [0xad, 0xa0, 0xc0,            # LDA $C0A0
                   0x29, 0x08, 0xf0, 0x02,      # AND #8; BEQ +2
                   0xe6, 0x10,                  # INC $10
                   0xa9, 0x03, 0x8d, 0xaf, 0xc0,  # LDA #3; STA $C0AF
                   0x40]                        # RTI
        lines = ['poke main 0 %04X %02X' % (0x300 + i, b)
                 for i, b in enumerate(code)]
        lines += ['poke main 0 %04X %02X' % (0x400 + i, b)
                  for i, b in enumerate(handler)]
        lines += ['poke lc 0 FFFE 00', 'poke lc 0 FFFF 04',
                  'write C0AE 09', 'reg pc=0300', 'run 30000',
                  'peek main 0 0010', 'state']
        output = self.bus(lines, '--speed', 1, '--switch', 'lc_read=1')
        state = self.state(output)
        frames = state['cycles'] // 17030
        self.assertGreaterEqual(frames, 3)
        self.assertEqual(self.peeks(output), [state['irqs']])
        self.assertIn(state['irqs'], (frames, frames + 1))


# ---- the memory API -------------------------------------------------------

def descriptor(op, flags, source, destination, count, fill=0,
               reserved=b'\0\0\0'):
    return (bytes([op, flags]) + bytes(source[:2]) +
            struct.pack('<H', source[2]) + bytes(destination[:2]) +
            struct.pack('<H', destination[2]) + struct.pack('<H', count) +
            bytes([fill]) + reserved)


def control(descriptors, count=None, magic=b'AMEM', version=1, flags=0,
            reserved=0, selector=0x80, command=4):
    payload = magic + bytes([version, len(descriptors) if count is None
                             else count, flags, reserved]) + \
        b''.join(descriptors)
    return bytes([command, 3, 0, 0, 0, selector, 0, 0, 0, 0]) + \
        struct.pack('<H', len(payload)) + payload


STATUS = bytes([0, 3, 0, 0, 0, 0x80, 0, 0, 0, 0])
MAIN, AUX = 0, 1


def transaction(request, reply_length):
    lines = ['read CFFF', 'read C700']
    lines += ['write CFF0 %02X' % b for b in request]
    lines += ['write CFF1 02', 'read CFF1']
    for _ in range(reply_length):
        lines += ['read CFF0', 'write CFF2 00']
    return lines


@have_tools
class MemoryApi(Workspace):
    def call(self, request, reply_length=1, *arguments, before=(), after=()):
        lines = list(before) + transaction(request, reply_length) + \
            list(after)
        output = self.bus(lines, '--amem', *arguments)
        values = self.reads(output)
        return values[2], values[3:], output

    def result(self, request, *arguments):
        status, reply, _ = self.call(request, 1, *arguments)
        self.assertEqual(status, 0xa0)          # ready, private port
        return reply[0]

    def test_status(self):
        status, reply, _ = self.call(STATUS, 35)
        self.assertEqual(status, 0xa0)
        self.assertEqual(reply[:3], [0, 0x20, 0])
        caps = bytes(reply[3:])
        self.assertEqual(caps[:16], b'AMEM\1\0\x10\x10\7\0\0\2\0\xc0\x7e\1')
        self.assertEqual(caps[20:22], b'\0\2')
        _, reply, _ = self.call(STATUS, 35, '--amem-unavailable')
        self.assertEqual(reply[3 + 15], 0)

    def test_unsupported_selector_and_command(self):
        self.assertEqual(self.result(STATUS[:5] + b'\x81' + STATUS[6:]), 0x21)
        self.assertEqual(self.result(STATUS, '--amem-unsupported'), 0x21)
        copy = descriptor(1, 0, (AUX, 3, 0x1000), (AUX, 4, 0x1000), 16)
        self.assertEqual(self.result(control([copy], selector=0x81)), 0x21)
        self.assertEqual(self.result(control([copy], command=5)), 0x21)
        self.assertEqual(self.result(control([copy]), '--amem-unavailable'),
                         0x60)
        self.assertEqual(self.result(control([copy]), '--amem-unsupported'),
                         0x60)

    def test_bad_header(self):
        copy = descriptor(1, 0, (AUX, 3, 0x1000), (AUX, 4, 0x1000), 16)
        for request in (control([copy], magic=b'AMEX'),
                        control([copy], version=2),
                        control([], count=0),
                        control([copy] * 17),
                        control([copy], flags=1),
                        control([copy], reserved=1),
                        control([copy], count=2)):
            self.assertEqual(self.result(request), 0x61, request.hex())

    def test_bad_descriptor(self):
        good = (AUX, 3, 0x1000), (AUX, 4, 0x1000)
        for d in (descriptor(3, 0, *good, 16),
                  descriptor(1, 2, *good, 16),
                  descriptor(1, 0, *good, 16, reserved=b'\0\1\0'),
                  descriptor(1, 0, *good, 16, fill=7),
                  descriptor(2, 0, (AUX, 1, 0), good[1], 16)):
            self.assertEqual(self.result(control([d])), 0x62, d.hex())

    def test_range(self):
        for source, destination, count in (
                ((2, 3, 0x1000), (AUX, 4, 0x1000), 16),
                ((MAIN, 1, 0x1000), (AUX, 4, 0x1000), 16),
                ((AUX, 127, 0x1000), (AUX, 4, 0x1000), 16),
                ((AUX, 3, 0x1000), (AUX, 4, 0x1000), 0),
                ((AUX, 3, 0x1000), (AUX, 4, 0x01ff), 16),
                ((AUX, 3, 0xbf00), (AUX, 4, 0x1000), 0x101),
                ((AUX, 3, 0x0100), (AUX, 4, 0x1000), 16)):
            self.assertEqual(self.result(control([descriptor(
                1, 1, source, destination, count)])), 0x63)
        # the largest descriptor is fine
        self.assertEqual(self.result(control([descriptor(
            1, 0, (AUX, 3, 0x0200), (AUX, 4, 0x0200), 0xbe00)])), 0)

    def test_overlap(self):
        self.assertEqual(self.result(control([descriptor(
            1, 0, (AUX, 5, 0x1000), (AUX, 5, 0x1080), 0x100)])), 0x64)
        self.assertEqual(self.result(control([descriptor(
            1, 0, (AUX, 5, 0x1000), (AUX, 5, 0x1000), 0x100)])), 0x64)
        self.assertEqual(self.result(control([descriptor(
            1, 0, (AUX, 5, 0x1000), (AUX, 5, 0x1100), 0x100)])), 0)
        # the same address in two banks does not overlap
        self.assertEqual(self.result(control([descriptor(
            1, 0, (AUX, 5, 0x1000), (AUX, 6, 0x1000), 0x100)])), 0)

    def test_private_required(self):
        for destination in ((MAIN, 0, 0x2000), (AUX, 0, 0x2000)):
            self.assertEqual(self.result(control([descriptor(
                2, 0, (0, 0, 0), destination, 16, fill=1)])), 0x65)
            self.assertEqual(self.result(control([descriptor(
                2, 1, (0, 0, 0), destination, 16, fill=1)])), 0)

    def test_copy_and_fill(self):
        before = ['poke main 0 %04X %02X' % (0x2000 + i, 0x40 + i)
                  for i in range(16)]
        request = control([
            descriptor(1, 0, (MAIN, 0, 0x2000), (AUX, 3, 0x4000), 16),
            descriptor(2, 0, (0, 0, 0), (AUX, 4, 0x5001), 8, fill=0xaa),
            descriptor(1, 1, (AUX, 3, 0x4004), (MAIN, 0, 0x6000), 4)])
        after = ['peek aux 3 %04X' % (0x4000 + i) for i in range(16)]
        after += ['peek aux 4 %04X' % (0x5000 + i) for i in range(10)]
        after += ['peek main 0 %04X' % (0x6000 + i) for i in range(5)]
        after += ['state']
        _, reply, output = self.call(request, 1, before=before, after=after)
        self.assertEqual(reply, [0])
        self.assertEqual(self.peeks(output),
                         list(range(0x40, 0x50)) + [0] + [0xaa] * 8 + [0] +
                         [0x44, 0x45, 0x46, 0x47, 0])
        amem = self.state(output)['amem']
        self.assertEqual((amem['requests'], amem['completed']), (1, 3))

    def test_nothing_is_written_before_everything_is_checked(self):
        request = control([
            descriptor(2, 0, (0, 0, 0), (AUX, 6, 0x3000), 4, fill=0x55),
            descriptor(2, 0, (0, 0, 0), (MAIN, 0, 0x3000), 4, fill=0x55)])
        _, reply, output = self.call(request, 1,
                                     after=['peek aux 6 3000', 'state'])
        self.assertEqual(reply, [0x65])
        self.assertEqual(self.peeks(output), [0])
        self.assertEqual(self.state(output)['amem']['completed'], 0)

    def test_transport(self):
        output = self.bus([
            'read CFF1',                        # not selected: the ROM
            'read C700', 'read CFF1',           # selected, nothing yet
            'read CFF0',                        # empty reply reads 0
            'write C007 00', 'read CFF1',       # INTCXROM: the ROM again
            'write C006 00', 'read C701', 'read C705', 'read C7FF',
            'read C400', 'read CFF1',           # another slot deselects
        ], '--amem')
        rom = lambda address: ((address - 0xc000) * 7 + 3) & 0xff  # noqa
        self.assertEqual(self.reads(output), [
            rom(0xcff1), 0, 0x20, 0, rom(0xcff1), 0x20, 3, 0x0a,
            0x00,                               # the Phasor's ORB
            rom(0xcff1)])

    def test_malformed_requests_halt(self):
        for request, reason in (
                (STATUS[:9] + b'\1', 'parameter padding is not zero'),
                (STATUS + b'\0', 'STATUS request with trailing bytes'),
                (control([])[:-1], 'CONTROL payload length')):
            _, _, output = self.call(request, 0)
            self.assertTrue(any(line.startswith('halt amem-malformed: ' +
                                                reason) for line in output),
                            output)
        output = self.bus(['read C700', 'write CFF2 00'], '--amem')
        self.assertIn('halt amem-malformed: SmartPort caller popped an empty '
                      'reply', output)


# ---- the MLI trap ---------------------------------------------------------

class Assembler:
    """Just enough 65C02 to write the ProDOS test program."""

    def __init__(self, origin):
        self.origin = origin
        self.code = bytearray()
        self.results = 0

    @property
    def here(self):
        return self.origin + len(self.code)

    def emit(self, *data):
        self.code.extend(data)

    def call(self, number, parms):
        """JSR $BF00 with the MLI's inline bytes, then A to $5000+n and P
        to $5100+n."""
        n = self.results
        self.results += 1
        self.emit(0x20, 0x00, 0xbf, number, parms & 0xff, parms >> 8)
        self.emit(0x8d, n, 0x50, 0x08, 0x68, 0x8d, n, 0x51)

    def copy(self, source, destination):
        self.emit(0xad, source & 0xff, source >> 8,
                  0x8d, destination & 0xff, destination >> 8)


def counted(text):
    return bytes([len(text)]) + text.encode('ascii')


FILE1 = bytes((i * 13 + 5) & 0xff for i in range(700))
BIG = bytes((i * 3) & 0xff for i in range(140000))
FILES = [('FILE1', 0x06, 0x0000, FILE1), ('FILE2', 0x04, 0x0300, b'\x42'),
         ('BIG', 0x06, 0x2000, BIG), ('EMPTY', 0x06, 0x0000, b'')]
EXPECTED_ERRORS = [0, 0, 0, 0, 0, 0, 0, 0, 0x4c, 0, 0x4d, 0, 0x46, 0x45,
                   0x44, 0x40, 0x43, 0x01, 0, 0x47, 0, 0, 0, 0, 0, 0, 0,
                   0x44, 0, 0x46, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x42, 0]


def prodos_program():
    """The code at $0800 and its data at $6000: every MLI call FakeProDOS
    implements, their errors, and QUIT."""
    data = bytearray()
    base = 0x6000

    def put(blob):
        address = base + len(data)
        data.extend(blob)
        return address

    def block(*fields):
        return put(bytes(fields))

    def pointer(address):
        return (address & 0xff, address >> 8)

    a = Assembler(0x0800)
    get_prefix = block(1, *pointer(0x3000))
    a.call(0xc7, get_prefix)                                    # 0
    open_dir = block(3, *pointer(put(counted('/DOOM'))), 0, 0x58, 0)
    a.call(0xc8, open_dir)                                      # 1
    read_dir = block(4, 0, 0x00, 0x40, 0x00, 0x08, 0, 0)
    a.copy(open_dir + 5, read_dir + 1)
    a.call(0xca, read_dir)                                      # 2
    close_dir = block(1, 0)
    a.copy(open_dir + 5, close_dir + 1)
    a.call(0xcc, close_dir)                                     # 3
    open1 = block(3, *pointer(put(counted('FILE1'))), 0, 0x58, 0)
    a.call(0xc8, open1)                                         # 4
    read1 = block(4, 0, 0x00, 0x31, 100, 0, 0, 0)
    a.copy(open1 + 5, read1 + 1)
    a.call(0xca, read1)                                         # 5
    mark = block(2, 0, 0x8a, 0x02, 0)                           # 650
    a.copy(open1 + 5, mark + 1)
    a.call(0xce, mark)                                          # 6
    read2 = block(4, 0, 0x00, 0x32, 100, 0, 0, 0)
    a.copy(open1 + 5, read2 + 1)
    a.call(0xca, read2)                                         # 7
    read3 = block(4, 0, 0x00, 0x33, 10, 0, 0xff, 0xff)
    a.copy(open1 + 5, read3 + 1)
    a.call(0xca, read3)                                         # 8
    eof = block(2, 0, 0, 0, 0)
    a.copy(open1 + 5, eof + 1)
    a.call(0xd1, eof)                                           # 9
    mark2 = block(2, 0, 0xbd, 0x02, 0)                          # 701
    a.copy(open1 + 5, mark2 + 1)
    a.call(0xce, mark2)                                         # 10
    close1 = block(1, 0)
    a.copy(open1 + 5, close1 + 1)
    a.call(0xcc, close1)                                        # 11
    for path in ('NOPE', '/OTHER/X', 'A/B', '1BAD'):            # 12-15
        a.call(0xc8, block(3, *pointer(put(counted(path))), 0, 0x58, 0))
    a.call(0xca, block(4, 7, 0, 0x34, 1, 0, 0, 0))              # 16
    a.call(0x99, block(0))                                      # 17
    create = block(7, *pointer(put(counted('NEW.FILE'))), 0xc3, 0x06, 0x34,
                   0x12, 1, 0, 0, 0, 0)
    a.call(0xc0, create)                                        # 18
    a.call(0xc0, create)                                        # 19
    open_new = block(3, *pointer(put(counted('new.file'))), 0, 0x58, 0)
    a.call(0xc8, open_new)                                      # 20
    write = block(4, 0, 0x00, 0x08, 0x2c, 0x01, 0, 0)           # 300 bytes
    a.copy(open_new + 5, write + 1)
    a.call(0xcb, write)                                         # 21
    truncate = block(2, 0, 0x22, 0x01, 0)                       # 290
    a.copy(open_new + 5, truncate + 1)
    a.call(0xd0, truncate)                                      # 22
    close_new = block(1, 0)
    a.copy(open_new + 5, close_new + 1)
    a.call(0xcc, close_new)                                     # 23
    info = block(10, *pointer(put(counted('NEW.FILE'))), *([0] * 15))
    a.call(0xc4, info)                                          # 24
    a.call(0xc5, block(2, 0, *pointer(0x3300)))                 # 25
    a.call(0xc6, block(1, *pointer(put(counted('/DOOM')))))     # 26
    a.call(0xc6, block(1, *pointer(put(counted('/DOOM/FILE1')))))  # 27
    a.call(0xc1, block(1, *pointer(put(counted('FILE2')))))     # 28
    a.call(0xc8, block(3, *pointer(put(counted('FILE2'))), 0, 0x58, 0))  # 29
    open_dir2 = block(3, *pointer(put(counted('/DOOM/'))), 0, 0x58, 0)
    a.call(0xc8, open_dir2)                                     # 30
    read_dir2 = block(4, 0, 0x00, 0x48, 0x00, 0x08, 0, 0)
    a.copy(open_dir2 + 5, read_dir2 + 1)
    a.call(0xca, read_dir2)                                     # 31
    many = block(3, *pointer(put(counted('FILE1'))), 0, 0x58, 0)
    for _ in range(8):                                          # 32-39
        a.call(0xc8, many)
    a.call(0xcc, block(1, 0))                                   # 40
    a.call(0x65, block(4, 0, 0, 0, 0, 0, 0, 0))                 # QUIT
    a.emit(0x4c, a.here & 0xff, a.here >> 8)
    return bytes(a.code), bytes(data), info, read1, read2, read3, eof


def build_disk_directory(files):
    """The volume directory build_disk writes for `files`."""
    sys.path.insert(0, str(DOOM_TOOLS))
    try:
        import build_disk
    finally:
        sys.path.remove(str(DOOM_TOOLS))
    contents = {name: data or b'\0' for name, _, _, data in files}
    total = build_disk.volume_size(contents.values())
    writer = build_disk.VolumeWriter('DOOM', total)
    for name, file_type, aux, _ in files:
        writer.add_file(name, contents[name], file_type, aux)
    image = build_disk.Image(writer.finish())
    _, _, chain = build_disk.list_volume(image)
    return b''.join(image.read(number) for number in chain)


@have_tools
class Prodos(Workspace):
    STEPS = 2000

    def run_program(self):
        code, data, *_ = prodos_program()
        manifest = []
        for name, file_type, aux, contents in FILES:
            path = self.directory / name
            path.write_bytes(contents)
            manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
        (self.directory / 'files.txt').write_text('\n'.join(manifest) + '\n')
        lines = ['poke main 0 %04X %02X' % (0x0800 + i, b)
                 for i, b in enumerate(code)]
        lines += ['poke main 0 %04X %02X' % (0x6000 + i, b)
                  for i, b in enumerate(data)]
        ram = self.directory / 'prodos.ram'
        lines += ['reg pc=0800', 'run %d' % self.STEPS, 'dump %s' % ram,
                  'state']
        output = self.bus(lines, '--prodos', self.directory / 'files.txt',
                          '--speed', 1)
        return self.state(output), ram.read_bytes()

    def test_calls(self):
        state, ram = self.run_program()
        _, _, info, read1, read2, read3, eof = prodos_program()
        main = ram[:0x10000]
        errors = list(main[0x5000:0x5000 + len(EXPECTED_ERRORS)])
        self.assertEqual(errors, EXPECTED_ERRORS)
        carries = [p & 1 for p in main[0x5100:0x5100 + len(EXPECTED_ERRORS)]]
        self.assertEqual(carries, [int(e != 0) for e in EXPECTED_ERRORS])
        self.assertEqual(main[0x3000:0x3007], b'\x06/DOOM/')
        self.assertEqual(main[0x3100:0x3164], FILE1[:100])
        self.assertEqual(main[0x3200:0x3232], FILE1[650:700])
        self.assertEqual(main[read2 + 6:read2 + 8], b'\x32\x00')
        self.assertEqual(main[read3 + 6:read3 + 8], b'\x00\x00')
        self.assertEqual(main[eof + 2:eof + 5], b'\xbc\x02\x00')    # 700
        self.assertEqual(main[info + 3:info + 10],
                         b'\xc3\x06\x34\x12\x01\x01\x00')
        self.assertEqual(main[0x3300:0x3305], b'\x74DOOM')
        prodos = state['prodos']
        self.assertTrue(prodos['quit'])
        self.assertEqual(prodos['calls'], len(EXPECTED_ERRORS) + 1)
        self.assertEqual(prodos['open'], {})
        files = {f[0]: f[1:] for f in prodos['files']}
        self.assertNotIn('FILE2', files)
        code = main[0x0800:0x0800 + 290]
        self.assertEqual(files['NEW.FILE'],
                         [6, 0x1234, 290, zlib.crc32(code)])
        self.assertEqual(state['pc'], 0xbf00)       # QUIT spins there
        # each serviced call drops the return address its JSR pushed;
        # only QUIT's stays
        self.assertEqual(state['sp'], 0xfd)

    @unittest.skipUnless((DOOM_TOOLS / 'build_disk.py').exists(),
                         'the existing port\'s tools/build_disk.py is missing')
    def test_directory_is_build_disks(self):
        _, ram = self.run_program()
        main = ram[:0x10000]
        self.assertEqual(main[0x4000:0x4800], build_disk_directory(FILES))
        after = [f for f in FILES if f[0] != 'FILE2']
        after.append(('NEW.FILE', 0x06, 0x1234, main[0x0800:0x0800 + 290]))
        self.assertEqual(main[0x4800:0x5000], build_disk_directory(after))


# ---- screens ----------------------------------------------------------------

class Screens(unittest.TestCase):
    @staticmethod
    def screen():
        return bytearray(0x8000)

    def test_standard_320_and_640(self):
        aux = self.screen()
        aux[0x7e00:0x7e04] = b'\x00\x0f\xf0\x00'     # colour 0 red, 1 green
        aux[0] = 0x01                                # row 0: colours 0, 1
        aux[0x7d01] = 0x80                           # row 1: 640 mode
        aux[0x7e00 + 16:0x7e00 + 18] = b'\x0f\x00'   # colour 8 blue
        aux[160] = 0x00                              # colours 8, 12, 0, 4
        rows = shot.render(aux, bytes(0x8000), 0)
        self.assertEqual((len(rows), len(rows[0])), (400, 640))
        self.assertEqual(rows[0][:4], [(240, 0, 0)] * 2 + [(0, 240, 0)] * 2)
        self.assertEqual(rows[1], rows[0])
        self.assertEqual(rows[2][:4], [(0, 0, 240), (0, 0, 0), (240, 0, 0),
                                       (0, 0, 0)])
        self.assertEqual(rows[3], rows[2])
        grey = shot.render(aux, bytes(0x8000), 0x20)
        self.assertEqual(grey[0][0], ((240 * 77) >> 8,) * 3)

    def test_pal256_modes(self):
        aux, main = self.screen(), self.screen()
        aux[0x7dfc:0x7e00] = shot.SHR4_MAGIC
        aux[0x7e02:0x7e04] = b'\x0f\x20'             # colour 1: selector 2
        main[0x7e02:0x7e04] = b'\xf0\x20'
        aux[0] = main[0] = 1
        rows = shot.render(aux, main, 0)
        self.assertEqual(rows[0][:3], [(0, 0, 240), (0, 0, 240), (0, 0, 0)])
        self.assertEqual(rows[3][0], (0, 0, 240))
        self.assertEqual(rows[4][0], (0, 0, 0))
        aux[0x7df8] = 1                              # interlace
        rows = shot.render(aux, main, 0)
        self.assertEqual(rows[200][0], (0, 240, 0))
        self.assertEqual(rows[2][0], (0, 0, 0))
        aux[0x7df8] = 2                              # merged
        rows = shot.render(aux, main, 0)
        self.assertEqual(rows[0][0], (0, 120, 120))

    def test_png(self):
        rows = [[(1, 2, 3)] * 2] * 2
        data = shot.png(rows)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        width, height = struct.unpack('>II', data[16:24])
        self.assertEqual((width, height), (2, 2))


# ---- comparisons with a2sim.py (build/venv) --------------------------------

def image(loads):
    return b'A2VMIMG1' + b''.join(
        struct.pack('<BBHI', kind, bank, address, len(data)) + data
        for kind, bank, address, data in loads)


@have_tools
@needs_venv
class AgainstA2sim(Workspace):
    """The same operations on a2vm and on a2sim.py."""

    def both(self, loads=(), ops=(), registers=None, switches=None,
             files=None, speed='turbo', amem=False, amem_options=None):
        registers = registers or {}
        switches = switches or {}
        ram_a2sim = self.directory / 'a2sim.ram'
        spec = dict(rom=str(self.rom), speed=speed, amem=amem,
                    amem_options=amem_options or {},
                    files=None if files is None else
                    [[n, t, a, d.hex()] for n, t, a, d in files],
                    loads=[[k, b, a, d.hex()] for k, b, a, d in loads],
                    switches=switches, registers=registers, ops=list(ops),
                    ram=str(ram_a2sim))
        result = subprocess.run(
            [str(VENV), str(support.ROOT / 'tests' / 'a2sim_driver.py')],
            input=json.dumps(spec), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.loads(result.stdout)

        arguments = ['--speed', speed]
        if amem:
            arguments.append('--amem')
            options = amem_options or {}
            if not options.get('supported', True):
                arguments.append('--amem-unsupported')
            if not options.get('available', True):
                arguments.append('--amem-unavailable')
        if files is not None:
            manifest = []
            for name, file_type, aux, data in files:
                path = self.directory / ('file-' + name)
                path.write_bytes(data)
                manifest.append('%s %02X %04X %s' % (name, file_type, aux,
                                                     path))
            (self.directory / 'files.txt').write_text('\n'.join(manifest) +
                                                      '\n')
            arguments += ['--prodos', self.directory / 'files.txt']
        if loads:
            (self.directory / 'start.img').write_bytes(image(loads))
            arguments += ['--image', self.directory / 'start.img']
        for name, value in switches.items():
            arguments += ['--switch', '%s=%d' % (name, value)]
        for name, value in registers.items():
            arguments += ['--reg', '%s=%X' % (name, value)]
        lines = []
        for op in ops:
            verb = op[0]
            if verb == 'r':
                lines.append('read %04X' % op[1])
            elif verb == 'w':
                lines.append('write %04X %02X' % (op[1], op[2]))
            elif verb in ('run', 'clock'):
                lines.append('%s %d' % (verb, op[1]))
            elif verb == 'hold':
                lines.append('hold %02X' % op[1])
            elif verb == 'release':
                lines.append('release')
            elif verb == 'press':
                lines.append('press %02X %d' % (op[1], op[2]))
            elif verb in ('mouse', 'mouse-to', 'buttons'):
                lines.append('%s %d %d' % tuple(op))
            elif verb == 'button':
                lines.append('button %d %02X' % (op[1], op[2]))
        ram_a2vm = self.directory / 'a2vm.ram'
        lines += ['dump %s' % ram_a2vm, 'state']
        output = self.bus(lines, *arguments)
        self.assertFalse([line for line in output if line.startswith('halt')])
        self.assertEqual(self.reads(output), expected['reads'])
        state = self.state(output)
        actual = {key: state[key] for key in expected['state']}
        self.assertEqual(compare_a2sim.compare_fields(expected['state'],
                                                      actual), [])
        regions = []
        data = ram_a2sim.read_bytes()
        offset = 0
        for name, size in [('main', 0x10000), ('main LC', 0x4000),
                           ('main LC bank 1', 0x1000)] + \
                [('aux bank %d' % b, 0x10000) for b in range(128)]:
            regions.append((name, data[offset:offset + size]))
            offset += size
        self.assertEqual(compare_a2sim.compare_ram(
            regions, ram_a2vm.read_bytes()), [])
        return expected

    def test_py65_core(self):
        out, _ = support.a2vm_build()
        result = subprocess.run(
            [str(VENV), str(support.ROOT / 'tools' / 'a2vm' / 'py65_diff.py'),
             '--py65check', str(out / 'py65check')],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, r'5180 cases .* 0 failures')

    def switch_program(self, rng, count):
        """Random loads, stores and read-modify-writes over the soft
        switches, the slots and memory, from $0800, copied into main and
        the aux banks the program selects."""
        code = bytearray([0x78])                    # SEI
        io = ([0xc000 + i for i in range(0x20)] + [0xc029, 0xc030] +
              [0xc050 + i for i in range(8)] + [0xc061 + i for i in range(7)] +
              [0xc070] + [0xc080 + i for i in range(16)] +
              [0xc0a0 + i for i in range(16)] + [0xc0c0 + i for i in range(16)])
        slots = ([0xc400 + (i | f) for i in range(16)
                  for f in (0x00, 0x10, 0x80, 0x90, 0x40)] +
                 [0xc205, 0xc20c, 0xc700, 0xc701, 0xcff0, 0xcff1, 0xcfff,
                  0xc100, 0xc300, 0xc800, 0xcc00])
        for _ in range(count):
            r = rng.random()
            if r < 0.08:
                code += bytes([0xa9, rng.choice((0, 1, 2, 0x7f, 0x80, 0x81)),
                               0x8d, 0x73, 0xc0])
                continue
            if r < 0.45:
                address = rng.choice(io)
            elif r < 0.55:
                address = rng.choice(slots)
            else:
                address = rng.choice((
                    rng.randrange(0x0000, 0x0800),
                    rng.randrange(0x2000, 0xc000),
                    rng.randrange(0xd000, 0x10000)))
            opcode = rng.choice((0xad, 0x8d, 0x2c, 0xee, 0x9c, 0x8e))
            if address >= 0xcff0 and address < 0xd000 or \
                    (0xc071 <= address <= 0xc073 and opcode != 0xad) or \
                    (address in (0xc0ae,) and opcode in (0xee, 0x8d, 0x8e)):
                opcode = 0xad
            if rng.random() < 0.3:
                code += bytes([0xa9, rng.getrandbits(8)])
            if opcode == 0x8e:
                code += bytes([0xa2, rng.getrandbits(8)])
            code += bytes([opcode, address & 0xff, address >> 8])
        end = 0x0800 + len(code)
        code += bytes([0x4c, end & 0xff, end >> 8])
        self.assertLess(end, 0x2000)
        loads = [(0, 0, 0x0800, bytes(code))]
        loads += [(1, bank, 0x0800, bytes(code)) for bank in (0, 1, 2, 127)]
        return loads, len(code)

    def test_switch_programs(self):
        rng = random.Random(1987)
        for speed in ('turbo', '1', '4'):
            for trial in range(3):
                loads, size = self.switch_program(rng, 1200)
                ops = []
                for chunk in range(12):
                    ops.append(['run', 120])
                    choice = rng.randrange(7)
                    if choice == 0:
                        ops.append(['hold', rng.choice((0x41, 0x57, 0x20))])
                    elif choice == 1:
                        ops.append(['release'])
                    elif choice == 2:
                        ops.append(['press', rng.choice((0x31, 0x1b)),
                                    rng.randrange(0, 400000)])
                    elif choice == 3:
                        ops.append(['mouse', rng.randrange(-300, 300),
                                    rng.randrange(-300, 300)])
                    elif choice == 4:
                        ops.append(['buttons', rng.randrange(2),
                                    rng.randrange(2)])
                    elif choice == 5:
                        ops.append(['button', rng.randrange(3),
                                    rng.choice((0, 0x80))])
                    else:
                        ops.append(['r', rng.choice((0xc000, 0xc010, 0xc019,
                                                     0xc0a0, 0xc404))])
                with self.subTest(speed=speed, trial=trial):
                    self.both(loads, ops, registers=dict(pc=0x0800),
                              speed=speed)

    def test_prodos_program(self):
        code, data, *_ = prodos_program()
        self.both([(0, 0, 0x0800, code), (0, 0, 0x6000, data)],
                  [['run', 2000]], registers=dict(pc=0x0800), files=FILES,
                  speed='1')

    def test_memory_api_requests(self):
        rng = random.Random(42)
        loads = [(1, bank, 0x0200, bytes(rng.getrandbits(8)
                                         for _ in range(0xbe00)))
                 for bank in (0, 3, 4, 126)]
        loads.append((0, 0, 0x0200, bytes(rng.getrandbits(8)
                                          for _ in range(0xbe00))))

        def endpoint():
            space = rng.choice((0, 1, 1, 1, 2))
            bank = rng.choice((0, 0, 3, 4, 126, 127)) if space else \
                rng.choice((0, 0, 0, 1))
            return space, bank, rng.choice((0x0200, 0x1000, 0x1080, 0x0100,
                                            0xbf00, 0xb000))

        ops, reply_at = [], []
        for _ in range(60):
            items = []
            for _ in range(rng.choice((1, 1, 2, 3))):
                op = rng.choice((1, 1, 2, 2, 3))
                source = endpoint() if op != 2 or rng.random() < 0.1 \
                    else (0, 0, 0)
                destination = endpoint()
                if op == 1 and rng.random() < 0.3:      # the same bank
                    destination = source[:2] + (
                        source[2] + rng.choice((0, 0x40, 0x100)),)
                items.append(descriptor(
                    op, rng.choice((0, 1, 1, 2)), source, destination,
                    rng.choice((0, 1, 0x80, 0x100, 0x1000)),
                    fill=rng.getrandbits(8) if op == 2 or rng.random() < 0.1
                    else 0))
            request = control(items, count=None if rng.random() < 0.9 else
                              len(items) + 1)
            if rng.random() < 0.1:
                request = STATUS
            reply_at.append(sum(1 for op in ops if op[0] == 'r') + 3)
            ops += [['r', 0xcfff], ['r', 0xc700]]
            ops += [['w', 0xcff0, b] for b in request]
            ops += [['w', 0xcff1, 2], ['r', 0xcff1]]
            for _ in range(35 if request == STATUS else 1):
                ops += [['r', 0xcff0], ['w', 0xcff2, 0]]
        reads = self.both(loads, ops, amem=True)['reads']
        codes = {reads[i] for i in reply_at}
        self.assertLessEqual({0, 0x61, 0x62, 0x63, 0x64, 0x65}, codes)


@have_tools
@needs_venv
@needs_doom
class ShortComparison(unittest.TestCase):
    """A few million cycles of the existing Doom port on a2vm and a2sim.py
    (tools/a2vm/compare_a2sim.py; the 20-frame run is `make compare`)."""

    def compare(self, *arguments):
        out, _ = support.a2vm_build()
        result = subprocess.run(
            [str(VENV), str(support.ROOT / 'tools' / 'a2vm' /
                            'compare_a2sim.py'), '--a2vm', str(out / 'a2vm'),
             '--frames', '0'] + [str(a) for a in arguments],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        return result

    def test_fast_start_matches(self):
        result = self.compare('--cycles', 3000000, '--every', 1000000)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('MATCH: 5 comparisons', result.stdout)

    def test_loader_boot_matches(self):
        result = self.compare('--mode', 'prodos', '--cycles', 3000000,
                              '--every', 1000000, '--amem')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('MATCH: 5 comparisons', result.stdout)

    def test_a_difference_is_seen(self):
        result = self.compare('--cycles', 1000000, '--every', 500000,
                              '--a2vm-arg=--io-cycles', '--a2vm-arg=72')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('DIFFERENCE: cycle-500000', result.stdout)


class HarnessHelpers(unittest.TestCase):
    def test_compare_fields(self):
        self.assertEqual(compare_a2sim.compare_fields(
            {'a': 1, 'b': [1, 2], 'c': {'d': True}},
            {'a': 1, 'b': [1, 2], 'c': {'d': 1}}), [])
        self.assertEqual(compare_a2sim.compare_fields(
            {'a': 1, 'b': [1, 2]}, {'a': 2, 'b': [1, 3]}),
            ['a: a2sim 1, a2vm 2', 'b.1: a2sim 2, a2vm 3'])

    def test_compare_ram(self):
        self.assertEqual(compare_a2sim.compare_ram(
            [('main', b'\0\1\2')], b'\0\1\2'), [])
        self.assertEqual(compare_a2sim.compare_ram(
            [('main', b'\0\1\2')], b'\0\5\2'),
            ['main: 1 bytes differ, first at $0001 (a2sim 01, a2vm 05)'])

    @needs_doom
    def test_fast_image_is_run_doom_install(self):
        build = doom.Build()
        data = build.image()
        self.assertEqual(data[:8], b'A2VMIMG1')
        kinds = set()
        at = 8
        while at < len(data):
            kind, bank, address, length = struct.unpack_from('<BBHI', data, at)
            kinds.add(kind)
            at += 8 + length
        self.assertEqual(at, len(data))
        self.assertEqual(kinds, {0, 1, 2, 3})


if __name__ == '__main__':
    unittest.main()
