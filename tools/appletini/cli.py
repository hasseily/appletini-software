# SPDX-License-Identifier: GPL-2.0-only
"""Headless Appletini runner. Python handles commands; C executes whole batches."""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1] / 'demos' / 'doom_gs' / 'tools' / 'a2vm'
SCHEMA = 'appletini-cli-1'
CPU_HZ = 133_333_333.333333 / 10
FIXED_HZ = {'mhz1': 1_000_000.0, 'ultrawarp': CPU_HZ, 'vtw26': 133_333_333.333333 / 5,
            'vtw33': 133_333_333.333333 / 4}
PROFILES = (*FIXED_HZ, 'turbo-f122')
VIDEO = {'ntsc': (63.695246, 262), 'pal': (64.0, 312)}
KINDS = {'main': 0, 'aux': 1, 'lc': 2, 'lc1': 3}
SWITCHES = ('store80 ramrd ramwrt intcxrom altzp slotc3rom '
            'col80 altchar text mixed page2 hires').split()
REASONS = {0: 'steps', 1: 'cycles', 2: 'breakpoint', 3: 'halt', 4: 'stp', 5: 'quit',
           6: 'audio-full'}
STATE_KEYS = ('pc a x y s p cycles ticks steps frame_ticks io_reads io_writes '
              'io_accesses video_writes shr_writes bank newvideo sw stopped '
              'waiting irqs dhires').split()


class RunnerError(ValueError):
    pass


def integer(value, low=0, high=(1 << 63) - 1):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RunnerError('expected an integer or a decimal/0x-prefixed string')
    try:
        result = int(value, 0) if isinstance(value, str) else value
    except ValueError as exc:
        raise RunnerError('invalid integer: %r' % value) from exc
    if not low <= result <= high:
        raise RunnerError('integer must be in %d..%d' % (low, high))
    return result


def positive(value):
    return integer(value, 1)


def timeout_value(value):
    result = float(value)
    if not math.isfinite(result) or not 0 < result <= 3600:
        raise RunnerError('timeout must be finite and in (0, 3600] seconds')
    return result


def hexbytes(value):
    if not isinstance(value, str):
        raise RunnerError('data must be a hexadecimal string')
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise RunnerError('invalid hexadecimal data') from exc


def area(value):
    if value.startswith('aux') and value != 'aux':
        return 1, integer(value[3:], 0, 127)
    if value not in KINDS:
        raise RunnerError('memory space must be main, auxN, lc or lc1')
    return KINDS[value], 0


def encode_path(value):
    return os.fsencode(Path(value).expanduser().resolve()) if value else None


def build_library():
    library = HERE / 'build' / ('libappletini.dylib' if sys.platform == 'darwin'
                               else 'libappletini.so')
    try:
        # The makefile publishes the completed library with an atomic rename.
        subprocess.run(['make', '-s', '-C', str(HERE)], check=True,
                       stdout=sys.stderr, stderr=sys.stderr)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunnerError('native build failed; install make and a C11 compiler') from exc
    return library


def library_api(path):
    lib = C.CDLL(str(path))
    p, s, u, n, q = C.c_void_p, C.c_char_p, C.c_uint, C.c_size_t, C.c_uint64
    signatures = {
        'new': (p, [s, s, C.c_double, C.c_double, u, u, p, n]),
        'free': (None, [p]),
        'run': (C.c_int, [p, q, q, C.POINTER(C.c_uint16), u]),
        'get': (q, [p, s]), 'halt': (s, [p]), 'error': (s, [p]),
        'set_reg': (C.c_int, [p, s, u]),
        'read': (C.c_int, [p, u, u, u, p, n]),
        'write': (C.c_int, [p, u, u, u, p, n]),
        'bus_read': (C.c_int, [p, u]), 'bus_write': (C.c_int, [p, u, u]),
        'input': (C.c_int, [p, s, C.c_int, C.c_int]),
        'prodos': (C.c_int, [p, s, s]),
        'file': (C.c_int, [p, s, u, u, p, n]),
        'cost_report': (C.c_int, [p, s]),
        'slot2': (C.c_int, [p, s]), 'slot7': (C.c_int, [p, s]),
        'mount_disk': (C.c_int, [p, s]), 'card_read': (C.c_int, [p, s, u, p, n]),
        'audio_enable': (C.c_int, [p, u]), 'audio_available': (n, [p]),
        'audio_read': (n, [p, p, n]), 'audio_event_read': (n, [p, p, n]),
        'boot': (C.c_int, [p, p, n, p, n]),
        'acceleration': (C.c_int, [p, s]),
    }
    for name, (restype, argtypes) in signatures.items():
        fn = getattr(lib, 'ap_' + name)
        fn.restype, fn.argtypes = restype, argtypes
    return lib


class Machine:
    def __init__(self, args):
        self.lib = library_api(build_library())
        self.handle = None
        self.audio = None
        self.temp = tempfile.TemporaryDirectory(prefix='appletini-')
        self.profile, self.video = args.profile, args.video
        self.clock_profile = args.profile
        self.clock_scaled = False
        self.banks = args.banks
        self.video_rom = Path(args.video_rom).expanduser().read_bytes() if args.video_rom else None
        if self.video_rom is not None and len(self.video_rom) != 4096:
            raise RunnerError('--video-rom needs a 4096-byte enhanced //e character ROM')
        line_us, lines = VIDEO[args.video]
        cost_path = None
        self.clock_hz = FIXED_HZ.get(args.profile, CPU_HZ)
        self.cpu_hz = self.clock_hz
        self.timing = 'functional-cpu-cycles-no-hardware-waits'
        self.cost_profile = None
        if args.profile == 'turbo-f122':
            spec = importlib.util.spec_from_file_location('appletini_costs', CORE / 'costs.py')
            costs = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(costs)
            self.cost_profile = 'f122+nod2+phasor' + ('+ntsc' if args.video == 'ntsc' else '')
            path = Path(self.temp.name) / 'cost.txt'
            path.write_text(costs.text(self.cost_profile))
            cost_path = os.fsencode(path)
            self.clock_hz = costs.parameters(self.cost_profile)['fabric_mhz'] * 1e6
            self.timing = 'historical-turbo-cost-model'
        error = C.create_string_buffer(1024)
        self.handle = self.lib.ap_new(encode_path(args.rom), cost_path, self.cpu_hz,
                                     line_us, lines, args.banks, error, len(error))
        if not self.handle:
            self.temp.cleanup()
            raise RunnerError(error.value.decode(errors='replace'))
        try:
            self.slot2, self.slot7 = args.slot2, args.slot7
            self.check(self.lib.ap_slot2(self.handle, args.slot2.encode()))
            if args.disk:
                self.check(self.lib.ap_mount_disk(self.handle, encode_path(args.disk)))
            if args.boot:
                from boot import load_roms
                slot_rom, c8_rom, rom_info = load_roms(args.slot7_rom, args.slot7_c8_rom)
                self.check(self.lib.ap_boot(self.handle, slot_rom, len(slot_rom), c8_rom, len(c8_rom)))
                motherboard_rom = Path(args.rom).expanduser().resolve()
                rom_info['motherboard_rom'] = {
                    'path': str(motherboard_rom), 'bytes': motherboard_rom.stat().st_size,
                    'sha256': hashlib.sha256(motherboard_rom.read_bytes()).hexdigest()}
                disk_path = Path(args.disk).expanduser()
                self.program = {'name': disk_path.name, 'path': str(disk_path.resolve()),
                                'sha256': hashlib.sha256(disk_path.read_bytes()).hexdigest(),
                                'bytes': disk_path.stat().st_size, 'launch': 'rom-boot',
                                'roms': rom_info}
            else:
                self.program = self.load_program(args)
            self.check(self.lib.ap_slot7(self.handle, args.slot7.encode()))
            if (getattr(args, 'wav', None) or getattr(args, 'audio', False) or
                    (args.command == 'play' and not getattr(args, 'no_audio', False))):
                from output_audio import AudioOutput
                self.audio = AudioOutput(self, wav_path=getattr(args, 'wav', None),
                                         retain=args.command == 'play',
                                         speech=not getattr(args, 'no_speech', False))
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.audio:
            self.audio.close()
            self.audio = None
        if self.handle:
            self.lib.ap_free(self.handle)
            self.handle = None
        self.temp.cleanup()

    def check(self, result):
        if not result:
            raise RunnerError(self.lib.ap_error(self.handle).decode(errors='replace'))

    def get(self, name):
        return self.lib.ap_get(self.handle, name.encode())

    def validate_acceleration(self, profile):
        if not isinstance(profile, str) or profile not in PROFILES:
            raise RunnerError('unknown acceleration profile')
        if profile != self.profile and (self.cost_profile or profile == 'turbo-f122'):
            raise RunnerError('switching to or from TURBO requires restarting the program')

    def acceleration(self, profile):
        self.validate_acceleration(profile)
        if profile == self.profile:
            return
        if self.audio:
            self.audio.drain()
        self.check(self.lib.ap_acceleration(self.handle, profile.encode()))
        self.profile = profile
        self.cpu_hz = FIXED_HZ[profile]
        self.clock_scaled = True

    def reg(self, name, value):
        limit = 65535 if name == 'pc' else 255
        self.check(self.lib.ap_set_reg(self.handle, name.encode(), integer(value, 0, limit)))

    def read(self, space, address, length):
        kind, bank = area(space)
        address, length = integer(address, 0, 65535), integer(length, 0, 65536)
        buffer = C.create_string_buffer(length)
        self.check(self.lib.ap_read(self.handle, kind, bank, address, buffer, length))
        return buffer.raw

    def write(self, space, address, data):
        kind, bank = area(space)
        address = integer(address, 0, 65535)
        self.check(self.lib.ap_write(self.handle, kind, bank, address, data, len(data)))

    def card_read(self, kind, offset, length):
        length = integer(length, 0, 65536)
        buffer = C.create_string_buffer(length)
        self.check(self.lib.ap_card_read(self.handle, kind.encode(),
                                        integer(offset, 0, 65535), buffer, length))
        return buffer.raw

    def load_program(self, args):
        load_at = args.load_address
        data, label = b'', None
        if args.disk:
            from disk import read_disk
            volume, files = read_disk(Path(args.disk).expanduser())
            systems = [f for f in files if f['type'] == 0xff]
            if args.system:
                systems = [f for f in systems if f['name'] == args.system.upper()]
            if len(systems) != 1:
                names = ', '.join(f['name'] for f in files if f['type'] == 0xff)
                raise RunnerError('select one SYSTEM file with --system; available: ' + names)
            launch = systems[0]
            self.check(self.lib.ap_prodos(self.handle, volume.encode(), launch['name'].encode()))
            for f in files:
                if f['name'] == 'PRODOS':
                    continue
                self.check(self.lib.ap_file(self.handle, f['name'].encode(), f['type'], f['aux'],
                                            f['data'], len(f['data'])))
            data, label = launch['data'], '%s/%s' % (volume, launch['name'])
        elif args.binary:
            path = Path(args.binary).expanduser()
            data, label = path.read_bytes(), str(path.resolve())
        elif args.hex is not None:
            data, label = hexbytes(args.hex), 'inline-hex'
        if label is not None:
            if not data:
                raise RunnerError('program is empty')
            if load_at + len(data) > 0xc000:
                raise RunnerError('program must fit below $C000; use debug write for banked data')
            self.write('main', load_at, data)
        self.reg('pc', args.entry if args.entry is not None else load_at)
        self.reg('s', 0xff)
        for assignment in args.reg:
            name, value = assignment.split('=', 1)
            self.reg(name, value)
        return {'name': label, 'sha256': hashlib.sha256(data).hexdigest(),
                'bytes': len(data), 'load_address': load_at,
                'launch': 'prodos-mli' if args.disk else 'raw'}

    def metadata(self):
        return {'profile': self.profile, 'core': 'w65c02s', 'video': self.video,
                'ram_bytes': self.banks * 65536,
                'slot2': self.slot2, 'slot4': 'phasor', 'slot7': self.slot7,
                'clock_hz': self.clock_hz,
                'clock_unit': ('fabric-clock' if self.cost_profile else
                               'machine-tick' if self.clock_scaled else 'cpu-cycle'),
                'clock_profile': self.clock_profile,
                'nominal_cpu_hz': self.cpu_hz if not self.cost_profile else None,
                'timing': self.timing, 'hardware_timing_validated': False,
                'cost_profile': self.cost_profile,
                'cost_firmware_commit': '3101934' if self.cost_profile else None,
                'target_firmware_commit': '1a3e8d38c57814471640c748879af28dbf16b266',
                'program': self.program}

    def state(self):
        values = {k: self.get(k) for k in STATE_KEYS}
        values['registers'] = {k: values.pop(k) for k in ('pc', 'a', 'x', 'y', 's', 'p')}
        bits = values.pop('sw')
        values['switches'] = {key: bool(bits & (1 << i)) for i, key in enumerate(SWITCHES)}
        values['halt'] = self.lib.ap_halt(self.handle).decode(errors='replace')
        values['modeled_seconds'] = values['ticks'] / self.clock_hz
        if self.audio:
            values['audio'] = self.audio.state()
        return values

    def run(self, *, steps=0, cycles=0, frames=0, breakpoints=(), timeout=30):
        steps, cycles, frames = integer(steps), integer(cycles), integer(frames)
        timeout = timeout_value(timeout)
        if frames:
            frame_limit = integer(frames * self.get('frame_ticks'))
            cycles = min(cycles, frame_limit) if cycles else frame_limit
        if not steps and not cycles:
            steps = 100_000
        if not isinstance(breakpoints, (list, tuple)) or len(breakpoints) > 256:
            raise RunnerError('breakpoints must be a list of at most 256 addresses')
        stops = (C.c_uint16 * len(breakpoints))(*(integer(p, 0, 65535) for p in breakpoints))
        start_steps, start_ticks = self.get('steps'), self.get('ticks')
        started = time.perf_counter()
        reason = 'timeout'
        while time.perf_counter() - started < timeout:
            used_steps, used_ticks = self.get('steps') - start_steps, self.get('ticks') - start_ticks
            if cycles and used_ticks >= cycles:
                reason = 'cycles'
                break
            if steps and used_steps >= steps:
                reason = 'steps'
                break
            chunk = min(100_000, steps - used_steps) if steps else 100_000
            result = self.lib.ap_run(self.handle, chunk, cycles - used_ticks if cycles else 0,
                                     stops, len(stops))
            if self.audio:
                self.audio.drain()
            if result < 0:
                self.check(0)
            reason = REASONS[result]
            if result not in (0, 6):
                break
        else:
            reason = 'timeout'
        elapsed = time.perf_counter() - started
        count = self.get('steps') - start_steps
        return {'reason': reason, 'state': self.state(),
                'execution': {'steps': count, 'ticks': self.get('ticks') - start_ticks,
                              'host_seconds': elapsed,
                              'host_steps_per_second': count / elapsed if elapsed else 0}}

    def expect(self, space, address, data):
        actual = self.read(space, address, len(data))
        return {'space': space, 'address': integer(address, 0, 65535),
                'expected': data.hex(), 'actual': actual.hex(), 'passed': actual == data}


def command(machine, req):
    if not isinstance(req, dict) or not isinstance(req.get('cmd'), str):
        raise RunnerError('request must be an object with a string cmd')
    cmd = req['cmd']
    allowed = {
        'state': (), 'run': ('steps', 'cycles', 'frames', 'breakpoints', 'timeout'),
        'step': ('steps',), 'read': ('space', 'address', 'length'),
        'write': ('space', 'address', 'data'), 'registers': ('values',),
        'input': ('kind', 'x', 'y'), 'assert': ('space', 'address', 'data'),
        'bus-read': ('address',), 'bus-write': ('address', 'value'), 'quit': (),
        'screenshot': ('path',), 'cost-report': ('path',),
        'configure': ('slot2', 'slot7', 'profile'), 'keyboard-state': ('codes',),
        'card-read': ('kind', 'offset', 'length'),
    }
    if cmd not in allowed:
        raise RunnerError('unknown command: ' + cmd)
    unknown = set(req) - set(allowed[cmd]) - {'id', 'cmd'}
    if unknown:
        raise RunnerError('unknown fields: ' + ', '.join(sorted(unknown)))
    if cmd == 'state':
        return {'state': machine.state(), 'machine': machine.metadata()}
    if cmd == 'configure':
        if 'slot2' in req and req['slot2'] not in ('off', 'mouse', '4play', 'snes'):
            raise RunnerError('slot2 must be off, mouse, 4play or snes')
        if 'slot7' in req and req['slot7'] not in ('smartport', 'supersprite'):
            raise RunnerError('slot7 must be smartport or supersprite')
        if 'profile' in req:
            machine.acceleration(req['profile'])
        for slot in ('slot2', 'slot7'):
            if slot in req:
                machine.check(getattr(machine.lib, 'ap_' + slot)(machine.handle, req[slot].encode()))
                setattr(machine, slot, req[slot])
        return {'machine': machine.metadata()}
    if cmd == 'keyboard-state':
        from controls import events
        mapped = events(req['codes'])
        for item in mapped:
            machine.check(machine.lib.ap_input(machine.handle, item['kind'].encode(), item['x'], item['y']))
        return {'inputs': mapped}
    if cmd == 'card-read':
        return {'data': machine.card_read(req['kind'], req.get('offset', 0), req['length']).hex()}
    if cmd in ('run', 'step'):
        options = {key: req[key] for key in allowed[cmd] if key in req}
        if cmd == 'step':
            options['steps'] = integer(req.get('steps', 1), 1)
        result = machine.run(**options)
        result['ok'] = result['reason'] not in ('halt', 'timeout')
        return result
    if cmd in ('read', 'write', 'assert'):
        space, address = req.get('space', 'main'), req['address']
        if cmd == 'read':
            return {'data': machine.read(space, address, req['length']).hex()}
        data = hexbytes(req['data'])
        if cmd == 'write':
            machine.write(space, address, data)
            return {'written': len(data)}
        assertion = machine.expect(space, address, data)
        return {'ok': assertion['passed'], 'assertion': assertion}
    if cmd == 'registers':
        values = req.get('values', {})
        if not isinstance(values, dict):
            raise RunnerError('values must be a register object')
        # Validate all before any mutation.
        for name, value in values.items():
            if name not in ('pc', 'a', 'x', 'y', 's', 'sp', 'p'):
                raise RunnerError('unknown register: ' + name)
            integer(value, 0, 65535 if name == 'pc' else 255)
        for name, value in values.items():
            machine.reg(name, value)
        return {'registers': machine.state()['registers']}
    if cmd == 'input':
        machine.check(machine.lib.ap_input(machine.handle, req['kind'].encode(),
                                           integer(req.get('x', 0), -(1 << 31), (1 << 31) - 1),
                                           integer(req.get('y', 0), -(1 << 31), (1 << 31) - 1)))
        return {}
    if cmd == 'screenshot':
        from video import screenshot
        return {'screenshot': screenshot(machine, req['path'])}
    if cmd == 'cost-report':
        machine.check(machine.lib.ap_cost_report(machine.handle, encode_path(req['path'])))
        return {'path': str(Path(req['path']).expanduser().resolve())}
    if cmd.startswith('bus-'):
        address = integer(req['address'], 0, 65535)
        if cmd == 'bus-read':
            value = machine.lib.ap_bus_read(machine.handle, address)
            if value < 0:
                machine.check(0)
            return {'value': value}
        machine.check(machine.lib.ap_bus_write(machine.handle, address, integer(req['value'], 0, 255)))
    return {}


def output(value):
    print(json.dumps({'schema': SCHEMA, 'ok': True, **value}, separators=(',', ':')), flush=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('profiles', help='describe supported target/timing profiles')
    for name in ('run', 'debug', 'play'):
        s = sub.add_parser(name, help={'run': 'bounded batch run', 'debug': 'persistent JSONL session',
                                      'play': 'local browser display and laptop inputs'}[name])
        source = s.add_mutually_exclusive_group(required=name != 'debug')
        source.add_argument('--binary', help='raw binary, loaded into main RAM')
        source.add_argument('--hex', help='inline hexadecimal machine code')
        source.add_argument('--disk', help='read-only ProDOS-order .po/.hdv image; launch a SYSTEM file')
        s.add_argument('--system', help='SYSTEM file name inside --disk')
        s.add_argument('--boot', action='store_true', help='boot the mounted disk through supplied Apple and slot-7 ROMs')
        s.add_argument('--slot7-rom', help='256-byte SmartPort slot ROM (.mem or binary), used by --boot')
        s.add_argument('--slot7-c8-rom', help='2048-byte SmartPort expansion ROM (.mem or binary), used by --boot')
        s.add_argument('--load-address', type=lambda v: integer(v, 0, 65535), default=0x2000)
        s.add_argument('--entry', type=lambda v: integer(v, 0, 65535))
        s.add_argument('--reg', action='append', default=[], metavar='NAME=VALUE')
        s.add_argument('--rom', help='optional 16 KiB enhanced //e ROM')
        s.add_argument('--video-rom', help='optional 4 KiB enhanced //e character ROM for exact glyphs')
        s.add_argument('--profile', choices=PROFILES, default='ultrawarp')
        s.add_argument('--video', choices=tuple(VIDEO), default='ntsc')
        s.add_argument('--banks', type=lambda v: integer(v, 1, 128), default=128)
        s.add_argument('--slot2', choices=('off', 'mouse', '4play', 'snes'), default='mouse')
        s.add_argument('--slot7', choices=('smartport', 'supersprite'), default='smartport')
        s.add_argument('--wav', metavar='PATH', help='stream deterministic 48 kHz stereo sound to a WAV file')
        s.add_argument('--audio', action='store_true', help='synthesize sound and report its PCM digest')
        s.add_argument('--no-speech', action='store_true', help='omit SSI-263 speech synthesis')
        if name == 'debug':
            s.add_argument('--script', help='JSONL command file; default stdin')
        elif name == 'play':
            s.add_argument('--port', type=lambda v: integer(v, 0, 65535), default=0)
            s.add_argument('--no-open', action='store_true', help='print URL without opening the browser')
            s.add_argument('--no-audio', action='store_true', help='disable browser audio synthesis')
        else:
            s.add_argument('--steps', type=positive, default=0)
            s.add_argument('--cycles', type=positive, default=0,
                           help='active clock ticks: CPU cycles or TURBO fabric clocks')
            s.add_argument('--frames', type=positive, default=0,
                           help='relative video-frame durations; default 60 if no bound supplied')
            s.add_argument('--timeout', type=timeout_value, default=30.0)
            s.add_argument('--breakpoint', action='append', type=lambda v: integer(v, 0, 65535), default=[])
            s.add_argument('--expect', action='append', default=[], metavar='SPACE:ADDRESS=HEX')
            s.add_argument('--dump', action='append', default=[], metavar='SPACE:ADDRESS:LENGTH:FILE')
            s.add_argument('--screenshot', help='write an Apple, SHR or SuperSprite memory preview as PNG')
            s.add_argument('--cost-report', help='write detailed historical TURBO cost counters as JSON')
            s.add_argument('--require-stop', action='store_true', help='fail if a budget ends before STP/breakpoint')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'profiles':
        output({'profiles': [
            *({'name': name, 'default': name == 'ultrawarp', 'nominal_cpu_hz': hz,
             'timing': 'functional CPU cycles; no motherboard, video-mirror or PSRAM waits',
             'hardware_timing_validated': False} for name, hz in FIXED_HZ.items()),
            {'name': 'turbo-f122', 'default': False, 'timing': 'f122+nod2+phasor cost model',
             'firmware_commit': '3101934', 'hardware_timing_validated': False,
             'notes': 'historical calibration; batched video and synchronization; Disk II acceleration off'}]})
        return 0
    machine = None
    try:
        if args.system and not args.disk:
            raise RunnerError('--system requires --disk')
        if args.boot:
            if not args.disk or not args.rom:
                raise RunnerError('--boot requires --disk and a supplied --rom')
            if args.system or args.entry is not None or args.reg or args.slot7 != 'smartport':
                raise RunnerError('--boot starts at the reset vector with slot-7 SmartPort; omit --system, --entry and --reg')
        elif args.slot7_rom or args.slot7_c8_rom:
            raise RunnerError('--slot7-rom and --slot7-c8-rom require --boot')
        if args.disk and (args.load_address != 0x2000 or args.entry not in (None, 0x2000)):
            raise RunnerError('ProDOS SYSTEM launch uses load address and entry $2000')
        if args.command == 'run' and args.cost_report and args.profile != 'turbo-f122':
            raise RunnerError('--cost-report requires --profile turbo-f122')
        machine = Machine(args)
        if args.command == 'play':
            from play import serve
            return serve(machine, args)
        if args.command == 'debug':
            stream = open(args.script, encoding='utf-8') if args.script else sys.stdin
            status = 0
            try:
                for line in stream:
                    if not line.strip():
                        continue
                    req = None
                    try:
                        if len(line) > 1_048_576:
                            raise RunnerError('command exceeds 1 MiB')
                        req = json.loads(line)
                        reply = command(machine, req)
                        if machine.audio:
                            machine.audio.drain()
                        if not reply.get('ok', True):
                            status = max(status, 1)
                        output({'id': req.get('id'), **reply})
                        if req['cmd'] == 'quit':
                            break
                    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
                        output({'ok': False, 'id': req.get('id') if isinstance(req, dict) else None,
                                'error': str(exc)})
                        status = 2
            finally:
                if args.script:
                    stream.close()
            return status
        # Parse artifact/assertion specifications before executing the guest.
        expects, dumps = [], []
        for spec in args.expect:
            location, data = spec.split('=', 1)
            space, address = location.split(':', 1)
            expected = hexbytes(data)
            machine.read(space, address, len(expected))
            expects.append((space, address, expected))
        for spec in args.dump:
            space, address, length, path = spec.split(':', 3)
            machine.read(space, address, length)
            dumps.append((space, address, length, Path(path).expanduser()))
        frames = args.frames or (60 if not args.steps and not args.cycles else 0)
        result = machine.run(steps=args.steps, cycles=args.cycles, frames=frames,
                             breakpoints=args.breakpoint, timeout=args.timeout)
        assertions = [machine.expect(*item) for item in expects]
        for space, address, length, path in dumps:
            path.write_bytes(machine.read(space, address, length))
        if args.screenshot:
            from video import screenshot
            result['screenshot'] = screenshot(machine, args.screenshot)
        if args.cost_report:
            machine.check(machine.lib.ap_cost_report(machine.handle, encode_path(args.cost_report)))
            result['cost_report'] = str(Path(args.cost_report).expanduser().resolve())
        ok = result['reason'] not in ('halt', 'timeout') and all(a['passed'] for a in assertions)
        require_stop = args.require_stop or bool(args.breakpoint)
        capped = require_stop and result['reason'] in ('steps', 'cycles')
        output({'ok': ok and not capped, 'machine': machine.metadata(), **result,
                'assertions': assertions, 'dumps': [str(p.resolve()) for *_, p in dumps]})
        return 3 if capped or result['reason'] == 'timeout' else (0 if ok else 1)
    except (ValueError, OSError, TypeError) as exc:
        output({'ok': False, 'error': str(exc)})
        return 2
    except KeyboardInterrupt:
        output({'ok': False, 'error': 'interrupted'})
        return 130
    finally:
        if machine:
            machine.close()


if __name__ == '__main__':
    raise SystemExit(main())
