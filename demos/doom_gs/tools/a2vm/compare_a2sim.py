#!/usr/bin/env python3
"""Run the existing Doom port on a2vm and on a2sim.py and compare them.

Usage (with the Python of build/venv, which has py65 and Pillow):

    build/venv/bin/python tools/a2vm/compare_a2sim.py
        [--mode fast|prodos] [--frames N] [--cycles N] [--every N]
        [--amem] [--speed turbo|N] [--build DIR] [--data DIR] [--rom FILE]
        [--no-input] [--cost PROFILE] [--report FILE]

Both machines start as the existing port's tools/run_doom.py starts them
(tools/a2vm/doom.py says how): "fast" places the images and the data and
starts at kernel_start; "prodos" boots DOOM.SYSTEM through the MLI trap,
so its loader loads and installs everything. a2sim.py runs through
run_doom.Doom (its machine, its fake ProDOS and its idle-loop hooks);
--amem attaches a2sim.FakeSmartPortMemory to it, as the port's hardware
smoke test does, and the memory API to a2vm.

The two are compared, byte for byte and field for field:

  - at the start;
  - at every frame boundary: the CPU at present_done with ALTZP off, the
    end of a rendered frame (run_doom.py's frame rows);
  - with --every N, every N cycles;
  - in prodos mode, when the CPU first reaches kernel_start (main);

and each comparison covers the RAM of main memory, of the main language
card, of every RamWorks bank, every soft switch, the registers, the cycle
count, the time bookkeeping (next VBL, idle cycles, interrupts, I/O
accesses, video and SHR writes), the keyboard, game port, mouse card,
Phasor, memory API and fake ProDOS (open files, calls, file contents).
At the last boundary the screen a2vm's shot.py renders is compared with
a2sim's shr_image(), pixel for pixel.

The run stops after --frames boundaries (or --cycles), or at the first
difference. Unless --no-input, both machines get the same input at the
same frame boundaries: W held (walk), the mouse moved, the fire button,
Open Apple and a key tap (DEFAULT_INPUT).

With --cost, a2vm runs with the cost model on (a profile of
tools/a2vm/costs/appletini.json), only observing: the comparison checks
that charging every access leaves the run exactly as a2sim.py's.

At the end it prints the time each took for the run (a2vm is run a second
time without snapshots for that) and the ratio. --report writes it all as
JSON.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import doom  # noqa: E402
import shot  # noqa: E402

DEFAULT_INPUT = """\
boundary 1 hold 87
boundary 3 mouse 48 0
boundary 5 buttons 1 0
boundary 6 buttons 0 0
boundary 8 release
boundary 9 mouse -32 0
boundary 10 oa 1
boundary 12 oa 0
boundary 13 key 32
boundary 15 hold 83
boundary 17 release
"""

SWITCHES = ('store80', 'ramrd', 'ramwrt', 'intcxrom', 'altzp', 'slotc3rom',
            'col80', 'altchar', 'text', 'mixed', 'page2', 'hires')
BANK = 0x10000


class Difference(Exception):
    pass


def a2sim_modules(doom_tools):
    sys.path.insert(0, str(doom_tools))
    try:
        import a2sim
        import run_doom
    except ImportError as error:
        raise SystemExit('cannot import a2sim.py (%s): run this with '
                         'build/venv/bin/python, which has py65 and Pillow'
                         % error)
    return a2sim, run_doom


def a2sim_state(m):
    """The fields of a2vm's state JSON, from an a2sim Machine."""
    mpu = m.mpu
    card, phasor = m.mouse, m.phasor
    state = dict(
        core='py65', cycles=mpu.processorCycles, pc=mpu.pc, a=mpu.a, x=mpu.x,
        y=mpu.y, sp=mpu.sp, p=mpu.p, waiting=int(mpu.waiting),
        next_vbl=m.next_vbl, idle_cycles=m.idle_cycles, irqs=m.irqs,
        io_accesses=m.io_accesses, video_writes=m.video_writes,
        shr_writes=m.shr_writes, speaker_toggles=m.speaker_toggles)
    switches = {name: int(m.sw[name]) for name in SWITCHES}
    switches.update(lc_read=int(m.lc_read), lc_write=int(m.lc_write),
                    lc_prewrite=int(m.lc_prewrite), lc_bank2=int(m.lc_bank2),
                    bank=m.bank, newvideo=m.newvideo)
    state['switches'] = switches
    state['keyboard'] = dict(latch=m.key_latch, held=int(m.key_held),
                             queue=[[w, k] for w, k in m.keys])
    state['buttons'] = list(m.buttons)
    state['paddles'] = list(m.paddles)
    state['paddle_trigger'] = m.paddle_trigger
    state['mli_hi'] = list(m._mli_hi) if m._mli_hi is not None else None
    state['mouse'] = None if card is None else dict(
        x=card.x, y=card.y, buttons=card.buttons,
        prev_buttons=card.prev_buttons, moved=int(card.moved),
        move_irq=int(card.move_irq), button_pending=int(card.button_pending),
        vbl_pending=int(card.vbl_pending), irq=int(card.irq), mode=card.mode,
        clamp_axis=card.clamp_axis, clamp=[list(w) for w in card.clamp],
        seq=card.seq, connected=int(card.connected), ps_x=card.ps_x,
        ps_y=card.ps_y, ps_buttons=card.ps_buttons, log_len=len(card.log))
    state['phasor'] = dict(
        t1_start=list(phasor.t1_start), mode=phasor.mode,
        via=[[v.orb, v.ora, v.ddrb, v.ddra] for v in phasor.via],
        ay=[list(chip) for chip in phasor.ay], latched=list(phasor.latched),
        selected=[[int(s) for s in pair] for pair in phasor.selected],
        ssi_dur=phasor.ssi_dur, ssi_rate=phasor.ssi_rate,
        ssi_started=phasor.ssi_started, ssi_phonemes=phasor.ssi_phonemes,
        log_len=len(phasor.log))
    amem = m.smartport
    state['amem'] = None if amem is None else dict(
        selected=int(amem.selected), ready=int(amem.ready),
        input_len=len(amem.input), input_crc=zlib.crc32(bytes(amem.input)),
        output=list(amem.output), requests=len(amem.requests),
        completed=len(amem.completed))
    prodos = m.prodos
    if prodos is None:
        state['prodos'] = None
    else:
        pairs = bytes(b for number, error in prodos.calls
                      for b in (number, error))
        state['prodos'] = dict(
            quit=int(prodos.quit), calls=len(prodos.calls),
            calls_crc=zlib.crc32(pairs), prefix=prodos.prefix,
            open={str(ref): [entry['name'], entry['pos'], int(entry['dirty'])]
                  for ref, entry in prodos.open_files.items()},
            files=[[name, t, a, len(data), zlib.crc32(bytes(data))]
                   for name, (t, a, data) in prodos.files.items()])
    return state


def a2sim_ram(m):
    """The regions of a2vm's .ram file, from an a2sim Machine."""
    regions = [('main', bytes(m.main)), ('main LC', bytes(m.lc[False])),
               ('main LC bank 1', bytes(m.lc_bank1[False]))]
    zero = bytes(BANK)
    for bank in range(128):
        memory = m.aux_banks.get(bank)
        regions.append(('aux bank %d' % bank,
                        bytes(memory) if memory is not None else zero))
    return regions


def compare_fields(expected, actual, path=''):
    """The differences between two JSON-like values, as strings."""
    out = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                out.append('%s%s: missing in a2vm' % (path, key))
            elif key not in expected:
                out.append('%s%s: only in a2vm' % (path, key))
            else:
                out += compare_fields(expected[key], actual[key],
                                      '%s%s.' % (path, key))
        return out
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            return ['%s: %d items in a2sim, %d in a2vm'
                    % (path.rstrip('.'), len(expected), len(actual))]
        for i, (e, a) in enumerate(zip(expected, actual)):
            out += compare_fields(e, a, '%s%d.' % (path, i))
        return out
    if isinstance(expected, bool):
        expected = int(expected)
    if expected != actual:
        out.append('%s: a2sim %r, a2vm %r' % (path.rstrip('.'), expected,
                                              actual))
    return out


def compare_ram(regions, data):
    out = []
    offset = 0
    for name, expected in regions:
        actual = data[offset:offset + len(expected)]
        offset += len(expected)
        if expected != actual:
            diffs = [i for i in range(len(expected)) if expected[i] != actual[i]]
            first = diffs[0]
            out.append('%s: %d bytes differ, first at $%04X (a2sim %02X, '
                       'a2vm %02X)' % (name, len(diffs), first,
                                       expected[first], actual[first]))
    if offset != len(data):
        out.append('the a2vm snapshot has %d bytes, a2sim %d'
                   % (len(data), offset))
    return out


class Comparison:
    def __init__(self, arguments):
        self.arguments = arguments
        self.build = doom.Build(arguments.build, arguments.data)
        self.a2sim, self.run_doom = a2sim_modules(doom.DOOM / 'tools')
        self.work = Path(tempfile.mkdtemp(prefix='compare-',
                                          dir=str(arguments.a2vm.parent)))
        self.checks = []            # (name, cycles)
        self.compare_seconds = 0.0

    # -- the events both machines run -------------------------------------
    def events(self):
        a = self.arguments
        lines = ['start snapshot start']
        if a.mode == 'prodos':
            lines.append('pc %04X:main snapshot kernel_start'
                         % self.build.label('kernel_start'))
        if a.every:
            limit = a.cycles or a.every * 400
            lines += ['cycle %d snapshot cycle-%d' % (c, c)
                      for c in range(a.every, limit + 1, a.every)]
        if not a.no_input:
            lines += DEFAULT_INPUT.splitlines()
        if a.frames:
            lines.append('boundary %d shot final' % a.frames)
        return lines

    def a2vm_command(self, snapshots, events_path):
        a = self.arguments
        command = [str(a.a2vm), '--rom', str(a.rom), '--speed', a.speed,
                   '--core', 'py65']
        if a.amem:
            command.append('--amem')
        if a.mode == 'prodos':
            files = self.work / 'files'
            files.mkdir(exist_ok=True)
            command += self.build.prodos_arguments(files)
        else:
            image = self.work / 'fast.img'
            image.write_bytes(self.build.image())
            command += self.build.fast_arguments(image)
        command += self.build.hook_arguments()
        if a.cost:
            command += self.build.cost_arguments(a.cost, self.work)
        command += ['--input', str(events_path)] + a.a2vm_arg
        if a.frames:
            command += ['--boundaries', str(a.frames)]
        if a.cycles:
            command += ['--cycles', str(a.cycles)]
        if snapshots:
            command += ['--snapshot-dir', str(self.work),
                        '--snapshot-boundaries', '--final-snapshot']
        return command

    def run_a2vm(self, snapshots):
        events = self.events()
        if not snapshots:
            events = [e for e in events if 'snapshot' not in e and
                      'shot' not in e]
        path = self.work / ('events.txt' if snapshots else 'events-bare.txt')
        path.write_text('\n'.join(events) + '\n')
        state = self.work / ('state.json' if snapshots else 'state-bare.json')
        command = self.a2vm_command(snapshots, path) + ['--state', str(state)]
        started = time.perf_counter()
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                universal_newlines=True)
        wall = time.perf_counter() - started
        if result.returncode:
            raise SystemExit('a2vm failed:\n' + result.stdout)
        return json.loads(state.read_text()), wall

    # -- a2sim -----------------------------------------------------------
    def a2sim_machine(self):
        a = self.arguments
        speed = a.speed if a.speed == 'turbo' else int(a.speed)
        d = self.run_doom.Doom(a.build, a.data, a.rom, speed=speed,
                               fast=a.mode == 'fast')
        m = d.machine
        if a.amem:
            m.smartport = self.a2sim.FakeSmartPortMemory()
        if a.mode == 'fast':
            d.install_fast()
        else:
            m.load(0x2000, d.files['DOOM.SYSTEM'])
            d.mpu.pc = 0x2000
            d.mpu.sp = 0xff
        return d, m

    def check(self, name, m, extra=None):
        """Compare a2sim now with a2vm's snapshot `name`."""
        started = time.perf_counter()
        base = self.work / name
        if not base.with_suffix('.json').exists():
            raise Difference('%s: a2vm has no snapshot here (it reached '
                             'fewer points)' % name)
        actual = json.loads(base.with_suffix('.json').read_text())
        expected = a2sim_state(m)
        if extra:
            expected.update(extra)
        actual = {key: actual[key] for key in expected if key in actual}
        problems = compare_fields(expected, actual)
        problems += compare_ram(a2sim_ram(m),
                                base.with_suffix('.ram').read_bytes())
        self.checks.append((name, m.mpu.processorCycles))
        base.with_suffix('.ram').unlink()
        self.compare_seconds += time.perf_counter() - started
        if problems:
            raise Difference('%s (cycle %d): %s' % (
                name, m.mpu.processorCycles, '; '.join(problems[:12])))

    def check_screen(self, m):
        started = time.perf_counter()
        rows = shot.render(*shot.load(self.work / 'final.shr'))
        ours = shot.rgb_bytes(rows)
        theirs = m.shr_image().tobytes()
        self.compare_seconds += time.perf_counter() - started
        if ours != theirs:
            differing = sum(1 for i in range(0, len(ours), 3)
                            if ours[i:i + 3] != theirs[i:i + 3])
            raise Difference('the screen: %d pixels differ' % differing)
        return len({ours[i:i + 3] for i in range(0, len(ours), 3)})

    def apply(self, m, words):
        """The action of an event line on a2sim (main.c's act)."""
        verb, args = words[0], words[1:]
        if verb == 'key':
            text = args[0]
            code = ord(text) if len(text) == 1 else int(text, 0)
            m.press(chr(code & 0x7f), at_cycle=m.mpu.processorCycles)
        elif verb == 'hold':
            text = args[0]
            m.hold(ord(text) if len(text) == 1 else int(text, 0))
        elif verb == 'release':
            m.release()
        elif verb == 'mouse':
            m.mouse_delta(int(args[0], 0), int(args[1], 0))
        elif verb == 'mouse-to':
            m.mouse_move(int(args[0], 0), int(args[1], 0))
        elif verb == 'buttons':
            m.mouse_buttons(args[0] != '0', args[1] != '0')
        elif verb in ('oa', 'ca'):
            m.buttons[0 if verb == 'oa' else 1] = 0x80 if args[0] != '0' else 0
        elif verb == 'snapshot':
            self.check(args[0], m)
        elif verb == 'shot':
            self.screen_colours = self.check_screen(m)
        else:
            raise SystemExit('unknown action %s' % verb)

    def run_a2sim(self):
        """a2sim through the loop of main.c's run, comparing on the way.
        Returns (end, boundaries, seconds of running)."""
        a = self.arguments
        d, m = self.a2sim_machine()
        mpu = m.mpu
        parsed = []
        for line in self.events():
            words = line.split()
            if words[0] == 'start':
                parsed.append(['start', None, False, words[1:]])
            elif words[0] == 'pc':
                address, _, suffix = words[1].partition(':')
                parsed.append(['pc', int(address, 16), suffix == 'main',
                               words[2:]])
            else:
                parsed.append([words[0], int(words[1], 0), False, words[2:]])
        done = [False] * len(parsed)
        boundary_pc = self.build.label('present_done')
        pcs = {event[1] for event in parsed if event[0] == 'pc'}
        started = time.perf_counter()
        for i, event in enumerate(parsed):
            if event[0] == 'start':
                self.apply(m, event[3])
                done[i] = True
        boundaries = 0
        end = None
        limit = a.cycles or float('inf')
        next_cycle = min([event[1] for event in parsed if event[0] == 'cycle'],
                         default=float('inf'))
        step = m.step
        prodos = m.prodos
        while end is None:
            if mpu.processorCycles >= limit:
                end = 'cycles'
                break
            step()
            pc = mpu.pc
            if pc == boundary_pc or pc in pcs:
                main_zp = not m.sw['altzp']
                if pc == boundary_pc and main_zp:
                    boundaries += 1
                    self.check('boundary-%04d' % boundaries, m,
                               dict(boundary=boundaries))
                    for i, event in enumerate(parsed):
                        if not done[i] and event[0] == 'boundary' and \
                                event[1] == boundaries:
                            done[i] = True
                            self.apply(m, event[3])
                for i, event in enumerate(parsed):
                    if not done[i] and event[0] == 'pc' and event[1] == pc \
                            and (main_zp or not event[2]):
                        done[i] = True
                        self.apply(m, event[3])
            if mpu.processorCycles >= next_cycle:
                next_cycle = float('inf')
                for i, event in enumerate(parsed):
                    if done[i] or event[0] != 'cycle':
                        continue
                    if mpu.processorCycles >= event[1]:
                        done[i] = True
                        self.apply(m, event[3])
                    else:
                        next_cycle = min(next_cycle, event[1])
            if prodos is not None and prodos.quit:
                end = 'quit'
            elif a.frames and boundaries >= a.frames:
                end = 'boundaries'
        seconds = time.perf_counter() - started - self.compare_seconds
        self.check('final', m, dict(boundaries=boundaries))
        return end, boundaries, seconds, m

    def run(self):
        a = self.arguments
        report = dict(mode=a.mode, amem=a.amem, speed=a.speed, cost=a.cost,
                      frames=a.frames, cycle_limit=a.cycles, every=a.every,
                      input=not a.no_input)
        state, _ = self.run_a2vm(snapshots=True)
        report['a2vm_end'] = state['end']
        report['a2vm_boundaries'] = state['boundaries']
        if state['end'] == 'halt':
            raise SystemExit('a2vm halted: %s' % state['halt'])
        try:
            end, boundaries, seconds, m = self.run_a2sim()
            report.update(match=True, end=end, boundaries=boundaries,
                          cycles=m.mpu.processorCycles,
                          compared=len(self.checks))
        except Difference as difference:
            report.update(match=False, difference=str(difference),
                          compared=len(self.checks))
            return report
        report['screen_colours'] = getattr(self, 'screen_colours', None)
        bare, wall = self.run_a2vm(snapshots=False)
        if bare['cycles'] != report['cycles']:
            report.update(match=False, difference=(
                'a2vm without snapshots ended at cycle %d, not %d'
                % (bare['cycles'], report['cycles'])))
            return report
        report.update(a2sim_seconds=round(seconds, 3),
                      a2vm_seconds=round(bare['host_seconds'], 3),
                      a2vm_wall_seconds=round(wall, 3),
                      a2vm_instructions=bare['instructions'],
                      ratio=round(seconds / max(bare['host_seconds'], 1e-9), 1),
                      ratio_wall=round(seconds / max(wall, 1e-9), 1))
        return report

    def close(self):
        if not self.arguments.keep:
            shutil.rmtree(str(self.work), ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--mode', choices=('fast', 'prodos'), default='fast')
    parser.add_argument('--frames', type=int, default=20,
                        help='rendered frames (0: no limit, give --cycles)')
    parser.add_argument('--cycles', type=int, default=0,
                        help='stop at this cycle')
    parser.add_argument('--every', type=int, default=0,
                        help='also compare every N cycles')
    parser.add_argument('--amem', action='store_true')
    parser.add_argument('--speed', default='turbo')
    parser.add_argument('--build', type=Path, default=doom.DEFAULT_BUILD)
    parser.add_argument('--data', type=Path, default=doom.DEFAULT_DATA)
    parser.add_argument('--rom', type=Path, default=doom.DEFAULT_ROM)
    parser.add_argument('--a2vm', type=Path, default=doom.A2VM)
    parser.add_argument('--no-input', action='store_true')
    parser.add_argument('--cost', metavar='PROFILE',
                        help='run a2vm with this cost profile (observing)')
    parser.add_argument('--a2vm-arg', action='append', default=[],
                        help='an extra argument for a2vm (to check that the '
                        'comparison sees a difference)')
    parser.add_argument('--keep', action='store_true',
                        help='keep the work directory')
    parser.add_argument('--report', type=Path)
    arguments = parser.parse_args(argv)
    if not arguments.frames and not arguments.cycles:
        parser.error('give --frames or --cycles')
    comparison = Comparison(arguments)
    try:
        report = comparison.run()
    finally:
        comparison.close()
    text = json.dumps(report, indent=1)
    if arguments.report:
        arguments.report.write_text(text + '\n')
    print(text)
    if report['match']:
        print('MATCH: %d comparisons, %s' % (report['compared'], (
            'a2vm %.1fx faster than a2sim.py (%.3f s against %.3f s)'
            % (report['ratio'], report['a2vm_seconds'],
               report['a2sim_seconds']))))
        return 0
    print('DIFFERENCE: %s' % report['difference'])
    return 1


if __name__ == '__main__':
    sys.exit(main())
