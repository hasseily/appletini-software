#!/usr/bin/env python3
"""Run the existing Appletini Doom port (demos/doom) on a2vm.

Usage:  python3 tools/a2vm/doom.py [--build DIR] [--data DIR] [--rom FILE]
            [--prodos] [--frames N] [--speed turbo|N] [--core py65|w65c02s]
            [--amem] [--input FILE] [--out DIR] [--shot]
            [--cost PROFILE [--timed]]

The same start as the existing port's tools/run_doom.py:

  - by default ("fast"), what run_doom.Doom.install_fast leaves: the data
    files in their RamWorks banks, GAME.BIN in its home bank, each code
    bank's language card from its staging bank, RENDER.BIN in main
    memory, LC.BIN in the main language card (bank 2 read and write), and
    the CPU at kernel_start with S = $FF, A = the bank count and I set;
  - with --prodos, the MLI trap holds DOOM.SYSTEM, the three images and
    every data file, and the CPU starts DOOM.SYSTEM at $2000, whose loader
    loads and installs everything;

and the same model hooks: the idle loops idle_wait (for the next VBL)
and present_wait (for line 0) are skipped while they would wait. A frame
ends when the CPU reaches present_done with ALTZP off. The run stops
after --frames rendered frames; a2vm's state goes to OUT/state.json and,
with --shot, the last screen to OUT/final.png.

With --cost, a2vm charges every access with a profile of
tools/a2vm/costs/appletini.json (tools/a2vm/costs.py), marks phases by the
port's profile_stage byte, and writes OUT/cost.jsonl, a line a frame;
--timed runs the machine on the model's clock. tools/a2vm/cost_report.py
reads those lines.

This module is standard library only. tools/a2vm/compare_a2sim.py uses it
to give a2vm the same start as a2sim.py.
"""

import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOFTWARE = ROOT.parents[1]
DOOM = SOFTWARE / 'demos' / 'doom'
DEFAULT_BUILD = DOOM / 'build' / 'hardware-20260926-textured-pal'
DEFAULT_DATA = DOOM / 'build' / 'data'
DEFAULT_ROM = Path(os.environ.get(
    'APPLETINI_ROOT', str(SOFTWARE.parent / 'appletini-one'))) / \
    'docs' / 'Apple2e_Enhanced.rom'
A2VM = ROOT / 'build' / 'a2vm' / 'a2vm'

IMAGES = (('RENDER.BIN', 0x0200), ('LC.BIN', 0xd000), ('GAME.BIN', 0x0200))
DATA_MAGIC = b'A2DM'
RAMWORKS_BANKS = 128


def labels_from(path):
    """The labels of a ca65 .lbl file (run_doom.labels_from)."""
    labels = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == 'al':
            labels.setdefault(parts[2].lstrip('.'), int(parts[1], 16))
    return labels


def prodos_name(name):
    """build_disk.encode_name's rule."""
    return (1 <= len(name) <= 15 and name[0].isalpha() and
            all(c.isalnum() or c == '.' for c in name))


def data_files(directory):
    """build_disk.data_files: the files of `directory` with ProDOS names
    and the A2DM magic, sorted by name, names in upper case."""
    out = {}
    for path in sorted(Path(directory).iterdir()):
        if not path.is_file() or not prodos_name(path.name.upper()):
            continue
        with path.open('rb') as handle:
            if handle.read(4) != DATA_MAGIC:
                continue
        out[path.name.upper()] = path.read_bytes()
    return out


def parse_data_file(data):
    """The (bank, address, bytes) segments of an A2DM data file
    (run_doom.parse_data_file)."""
    if data[:4] != DATA_MAGIC or data[4] != 1:
        raise ValueError('not a data file')
    out, offset = [], 256
    for i in range(data[5]):
        base = 8 + 5 * i
        bank, address, length = data[base], data[base + 1] | \
            data[base + 2] << 8, data[base + 3] | data[base + 4] << 8
        out.append((bank, address, data[offset:offset + length]))
        offset += length
    return out


class Build:
    """A linked build of the existing port and its data."""

    def __init__(self, build=DEFAULT_BUILD, data=DEFAULT_DATA):
        self.build = Path(build)
        self.data = Path(data)
        self.labels = labels_from(self.build / 'doom.lbl')
        metadata = self.build / 'banked.json'
        self.banked = json.loads(metadata.read_text()) \
            if metadata.is_file() else None
        self.files = {name: (self.build / name).read_bytes()
                      for name in ('DOOM.SYSTEM',) + tuple(n for n, _ in IMAGES)}
        self.data_files = data_files(self.data)
        if self.banked:
            name = self.banked['preload_file']
            self.data_files[name] = (self.build / name).read_bytes()

    def label(self, name):
        return self.labels[name]

    # -- fast install ------------------------------------------------------
    def image(self):
        """The A2VMIMG1 records of run_doom.Doom.install_fast."""
        banks = {}

        def bank(number):
            return banks.setdefault(number, bytearray(0x10000))

        records = []

        def record(kind, number, address, data):
            records.append(struct.pack('<BBHI', kind, number, address,
                                       len(data)) + bytes(data))

        for contents in self.data_files.values():
            for number, address, blob in parse_data_file(contents):
                bank(number)[address:address + len(blob)] = blob
        home = self.banked['game_home'] if self.banked else 1
        game = self.files['GAME.BIN']
        bank(home)[0x0200:0x0200 + len(game)] = game
        if self.banked:
            staging = self.banked.get('code_staging', {})
            for number in self.banked['banks'].values():
                stage = staging.get(str(number), number)
                bank(number)[0xd000:0x10000] = bytes(bank(stage)[0x0200:0x3200])
        for number in sorted(banks):
            record(1, number, 0, banks[number][:0x8000])
            record(1, number, 0x8000, banks[number][0x8000:])
        record(0, 0, 0x0200, self.files['RENDER.BIN'])
        lc = self.files['LC.BIN']
        record(2, 0, 0xd000, lc[:0x3000])
        record(3, 0, 0xd000, lc[0x3000:0x4000])
        return b'A2VMIMG1' + b''.join(records)

    def fast_arguments(self, image_path):
        return ['--image', str(image_path),
                '--switch', 'lc_read=1', '--switch', 'lc_write=1',
                '--switch', 'lc_bank2=1',
                '--reg', 'pc=%04X' % self.label('kernel_start'),
                '--reg', 's=FF', '--reg', 'a=%02X' % RAMWORKS_BANKS,
                '--reg', 'p=34']

    # -- ProDOS boot -------------------------------------------------------
    def prodos_files(self):
        """(name, type, aux, bytes) in FakeProDOS's order (run_doom.Doom)."""
        out = [('DOOM.SYSTEM', 0xff, 0x2000, self.files['DOOM.SYSTEM'])]
        out += [(name, 0x06, address, self.files[name])
                for name, address in IMAGES]
        out += [(name, 0x06, 0x0000, contents)
                for name, contents in self.data_files.items()]
        return out

    def prodos_arguments(self, directory):
        """Write the manifest and the files it names into `directory`."""
        directory = Path(directory)
        lines = []
        for name, file_type, aux, contents in self.prodos_files():
            path = directory / ('file-' + name)
            path.write_bytes(contents)
            lines.append('%s %02X %04X %s' % (name, file_type, aux, path))
        manifest = directory / 'prodos.txt'
        manifest.write_text('\n'.join(lines) + '\n')
        system = directory / 'file-DOOM.SYSTEM'
        return ['--prodos', str(manifest), '--volume', 'DOOM',
                '--launched', 'DOOM.SYSTEM', '--load', '2000:%s' % system,
                '--reg', 'pc=2000', '--reg', 's=FF']

    # -- the model hooks ---------------------------------------------------
    def cost_arguments(self, profile, directory, timed=False):
        """a2vm's options for the cost model: the profile's parameters,
        the phase byte (profile_stage) and the report."""
        sys.path.insert(0, str(HERE))
        import costs
        directory = Path(directory)
        parameters = costs.write(profile, directory / ('cost-%s.txt' % profile))
        out = ['--cost', str(parameters), '--cost-report',
               str(directory / 'cost.jsonl')]
        if 'profile_stage' in self.labels:
            out += ['--cost-phase', '%04X' % self.label('profile_stage')]
        if timed:
            out.append('--cost-timed')
        return out

    def hook_arguments(self):
        L = self.labels
        return ['--idle', '%04X:vbl:main:eq=%04X,%04X' % (
                    L['idle_wait'], L['vbl_count'], L['clk_last']),
                '--idle', '%04X:line0:main:invbl' % L['present_wait'],
                '--boundary', '%04X' % L['present_done']]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--build', type=Path, default=DEFAULT_BUILD)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--rom', type=Path, default=DEFAULT_ROM)
    parser.add_argument('--a2vm', type=Path, default=A2VM)
    parser.add_argument('--prodos', action='store_true')
    parser.add_argument('--frames', type=int, default=20)
    parser.add_argument('--speed', default='turbo')
    parser.add_argument('--core', default='py65')
    parser.add_argument('--amem', action='store_true')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--shot', action='store_true')
    parser.add_argument('--cost', metavar='PROFILE',
                        help='charge accesses with a cost profile')
    parser.add_argument('--timed', action='store_true',
                        help='run the machine on the cost model\'s clock')
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'build' / 'a2vm' / 'doom')
    arguments = parser.parse_args(argv)
    build = Build(arguments.build, arguments.data)
    out = arguments.out
    out.mkdir(parents=True, exist_ok=True)
    command = [str(arguments.a2vm), '--rom', str(arguments.rom),
               '--speed', arguments.speed, '--core', arguments.core]
    if arguments.amem:
        command.append('--amem')
    if arguments.prodos:
        command += build.prodos_arguments(out)
    else:
        image = out / 'fast.img'
        image.write_bytes(build.image())
        command += build.fast_arguments(image)
    command += build.hook_arguments()
    if arguments.cost:
        command += build.cost_arguments(arguments.cost, out, arguments.timed)
    elif arguments.timed:
        parser.error('--timed needs --cost')
    events = arguments.input.read_text() if arguments.input else ''
    if arguments.shot:
        events += '\nboundary %d shot final\n' % arguments.frames
    (out / 'events.txt').write_text(events)
    command += ['--input', str(out / 'events.txt'), '--snapshot-dir',
                str(out), '--boundaries', str(arguments.frames),
                '--state', str(out / 'state.json')]
    result = subprocess.run(command)
    if result.returncode:
        return result.returncode
    state = json.loads((out / 'state.json').read_text())
    print('%s: %d frames, %d cycles, %d instructions, %.3f s on the host'
          % (state['end'], state['boundaries'], state['run_cycles'],
             state['instructions'], state['host_seconds']))
    if arguments.shot:
        sys.path.insert(0, str(HERE))
        import shot
        rows = shot.render(*shot.load(out / 'final.shr'))
        (out / 'final.png').write_bytes(shot.png(rows))
        print('saved %s' % (out / 'final.png'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
