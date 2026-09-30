#!/usr/bin/env python3
"""The 65C02 music player (src/sound) on a2vm, against tools/sound/player.py.

Usage:
  python3 tools/sound/run65.py [SONG ...] [--seconds S] [--ntsc]
          [--no-loop] [--jobs N] [--keep DIR]
      Play each song file build/sound/SONG.native12.ay (default: all 13,
      60 s, PAL, looping) on a2vm with the mouse card's VBL interrupt and
      compare the AY writes of every interrupt with player.py's.
  python3 tools/sound/run65.py --sizes
      The player's code and data against native-sound.md 4.3.
  python3 tools/sound/run65.py --cost [SONG ...] [--seconds S] [--jobs N]
          [--update-readme]
      The player's time a second in the cost model (f121 with the Phasor
      on: window 512, window 32, FW-S1), each song played once to its end
      plus one second (or S seconds of it): the table of
      src/sound/README.md.
  --jobs N runs at most N a2vm runs at a time (default 4, the ground
  rules' limit; run the tool under nice -n 10).

What a run is. src/sound/Makefile assembles the player (the voice layout
native12, the only one) and its test driver (src/sound/driver.s). This
tool writes an a2vm image: the player in the main language card
($E000-$FFFF, with the IRQ vector at $FFFE), the driver at $0800 with its
parameters (drv_mode, drv_actions), each song file in a RamWorks bank of
its own at $1000. a2vm runs it on the exact W65C02S core with the cost
model on the model's clock (--cost-timed; the PAL frame, or NTSC with the
ntsc variant), the slot-4 slowdown on (the phasor variant), --ay-log, and
--irq-bounds: an interrupt that reads or writes outside the zero page,
the stack, the mouse card, the Phasor and the language card ends the run
(the IRQ contract, native-sound.md 4.3). The driver starts the song, then
serves each VBL interrupt: its actions, then snd_refill.

The AY log is grouped as the machine ran: the writes and chip resets
before the first interrupt (snd_init's resets, the start's first burst),
then for each interrupt the writes between its entry and its RTI (the
player's burst), then the writes of the main loop after it (a start's
first burst). A comparison needs every group equal, write for write and
in order: chip, register, value; a chip reset is expected only from
snd_init (and snd_probe), before everything else. At the end of the run
the chips' registers (state.json) must be the model's shadow.

The probe. With `probe` the driver runs snd_probe first. On the Phasor it
answers SND_MUSIC and the run goes on as above; with `mb_only` (a2vm
--phasor-mb-only, the Phasor locked to Mockingboard mode) it answers
SND_NO_MUSIC: the driver keeps the answer in drv_found, calls snd_init,
and never starts the player (its song actions are ignored), as the game
runs with no music on a card that cannot switch to native mode. A run
can start with the player's state in the card's $D000 bank already
written (`card`: the garbage a real machine holds at power-on, which
snd_init must clear) and can end early at any of the labels `stop_at`
(a call the no-music driver must never make).

The oracle. For a song played from its start, player.Player itself:
reset() is the first group, and interrupt() k is the burst of interrupt
k, as tools/sound/README.md specifies. For the ring's own behaviour (a
refill across the end of a looping song, an underrun, a stop, a new
song while one plays), RingPlayer: player.Player with the stream read
through the 65C02 player's ring, refilled as the driver refills it, and
the two rules player.py leaves out (native-sound.md 4.3): an underrun
silences every music voice and holds the position; a stop silences them
at the next interrupt and ends the player. Standard library only.
"""

import argparse
import copy
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import player, tables  # noqa: E402
from a2vm import costs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD = ROOT / 'build'
SONGS = BUILD / 'sound'
OUT = BUILD / 'sound65'
A2VM = BUILD / 'a2vm' / 'a2vm'
SRC = ROOT / 'src' / 'sound'
README = SRC / 'README.md'

LAYOUT = tables.NATIVE12      # the only voice layout
SONG_BANK0 = 1              # the first song's RamWorks bank
SONG_ADDRESS = 0x1000
MAIN_BASE = 0x0800
LC_BASE = 0xE000
LC_BSS_BASE = 0xD000        # the card's bank 2: ring, write lists, state

START, STOP, GATE_OFF, GATE_ON = 1, 2, 3, 4
# The IRQ contract (native-sound.md 4.3): the zero page and the stack, the
# mouse card in slot 2, the Phasor in slot 4, the main language card.
IRQ_BOUNDS = '0000-01FF,C0A0-C0AF,C400-C4FF,D000-FFFF'
# The chip resets of snd_init in the AY log: ORB 0 on VIA-A (chips 0 and
# 1), then on VIA-B (chips 2 and 3); a2vm logs both chips of a VIA.
INIT_RESETS = (('reset', 0), ('reset', 1), ('reset', 2), ('reset', 3))
# snd_probe's (probe.s) events, keyed by mb_only: VIA-A's chips reset, R0
# of chip 0 = $55, R0 of chip 1 = $AA (on chip 0 when the card is locked
# to Mockingboard mode), the chips reset again.
PROBE_EVENTS = {
    False: (('reset', 0), ('reset', 1), (0, 0, 0x55), (1, 0, 0xAA),
            ('reset', 0), ('reset', 1)),
    True: (('reset', 0), ('reset', 1), (0, 0, 0x55), (0, 0, 0xAA),
           ('reset', 0), ('reset', 1))}
# snd_probe's answer (sound.inc), in the driver's drv_found
SND_MUSIC, SND_NO_MUSIC = 0, 1
# a2vm's phasor.mode: native (four AYs), or the Mockingboard mode a card
# locked to it keeps
NATIVE_MODE, MOCKINGBOARD_MODE = 5, 0
MAX_ACTIONS = 32
SONG_LOOP, SONG_NTSC = 0x01, 0x80
IDLE_MODE, COUNT_MODE = 0, 1


# ---------------------------------------------------------------------------
# building
# ---------------------------------------------------------------------------

def have_cc65():
    return bool(shutil.which('ca65') and shutil.which('ld65'))


def build(out=OUT, source=SRC):
    """Assemble the player with src/sound/Makefile (or the Makefile of a
    copy of the sources in `source`) into `out`. Returns what make said;
    raises RuntimeError when it fails or when ca65 or ld65 warns (the
    ground rules: builds with no warnings)."""
    result = subprocess.run(
        ['make', '-C', str(source), 'OUT=%s' % out, 'ROOT=%s' % ROOT],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True)
    if result.returncode:
        raise RuntimeError('make failed:\n' + result.stdout)
    warnings = [line for line in result.stdout.splitlines()
                if 'warning' in line.lower()]
    if warnings:
        raise RuntimeError('the build warns:\n' + '\n'.join(warnings))
    return result.stdout


def build_a2vm(out=None):
    args = ['make', '-C', str(ROOT / 'tools' / 'a2vm')]
    if out:
        args.append('OUT=%s' % out)
    args.append(str(Path(out or A2VM.parent) / 'a2vm'))
    result = subprocess.run(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        raise RuntimeError('make failed:\n' + result.stdout)
    return Path(out or A2VM.parent) / 'a2vm'


def read_labels(path):
    """{name: address} of an ld65 -Ln file."""
    labels = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'al':
            labels[parts[2].lstrip('.')] = int(parts[1], 16)
    return labels


def segments(map_path):
    """{segment: (start, size)} of an ld65 map file."""
    out = {}
    lines = Path(map_path).read_text().splitlines()
    start = lines.index('Segment list:')
    for line in lines[start + 4:]:
        parts = line.split()
        if len(parts) != 5:
            break
        out[parts[0]] = (int(parts[1], 16), int(parts[3], 16))
    return out


class Player65:
    """The assembled player: its files and labels."""

    def __init__(self, out=OUT):
        self.dir = Path(out)
        self.labels = read_labels(self.dir / 'sound.lbl')
        self.lc = (self.dir / 'sound.lc').read_bytes()
        self.main = (self.dir / 'sound.main').read_bytes()
        self.segments = segments(self.dir / 'sound.map')

    def lc_bytes(self, label, count):
        start = self.labels[label] - LC_BASE
        return self.lc[start:start + count]


# ---------------------------------------------------------------------------
# a run on a2vm
# ---------------------------------------------------------------------------

def actions_bytes(actions):
    """drv_actions: (kind, vbl, bank, address, flags, matt) records."""
    if len(actions) > MAX_ACTIONS:
        raise ValueError('at most %d actions' % MAX_ACTIONS)
    out = bytearray()
    for kind, vbl, bank, address, flags, matt in actions:
        out += struct.pack('<BHBHBB', kind, vbl, bank, address, flags, matt)
    return bytes(out + b'\0')


def start_action(vbl, song_index, loop=True, ntsc=False, matt=0):
    return (START, vbl, SONG_BANK0 + song_index, SONG_ADDRESS,
            (SONG_LOOP if loop else 0) | (SONG_NTSC if ntsc else 0), matt)


def other_action(kind, vbl):
    return (kind, vbl, 0, 0, 0, 0)


def cost_profile(ntsc=False, variants=('phasor',), profile='f121'):
    return '+'.join([profile] + list(variants) + (['ntsc'] if ntsc else []))


class Run:
    """The result of one a2vm run: the AY log's groups, the end state."""

    def __init__(self, directory, labels):
        self.directory = Path(directory)
        self.labels = labels
        self.state = json.loads((self.directory / 'state.json').read_text())
        self.events = read_log(self.directory / 'ay.log')
        self.main, self.bursts, self.times, self.partial = group(self.events)

    def ram(self):
        """main 64 KB, then the main card $C000-$FFFF (a2vm snapshot)."""
        data = (self.directory / 'final.ram').read_bytes()
        return data[:0x10000], data[0x10000:0x14000]

    def word(self, label, size=2):
        main, lc = self.ram()
        address = self.labels[label]
        memory, offset = (lc, address - 0xC000) if address >= 0xC000 \
            else (main, address)
        return int.from_bytes(memory[offset:offset + size], 'little')


def run(p65, songs, actions, seconds, directory, ntsc=False,
        variants=('phasor',), mode=IDLE_MODE, a2vm=A2VM, snapshot=False,
        profile='f121', probe=False, mb_only=False, card=None,
        stop_at=()):
    """Run the driver with `actions` for `seconds` of machine time. With
    `probe` the driver runs snd_probe first; with `mb_only` the card is
    locked to Mockingboard mode (a2vm --phasor-mb-only), so the probe
    answers SND_NO_MUSIC and the driver starts no song. `card` (bytes)
    is loaded at $D000 in the main language card's bank 2, where the
    player keeps its ring, write lists and state, before the run; a2vm
    starts that RAM at zero. The run ends early (RuntimeError) when the
    65C02 reaches any of the labels in `stop_at`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    labels = p65.labels
    main = bytearray(p65.main)
    main[labels['drv_mode'] - MAIN_BASE] = mode
    main[labels['drv_probe'] - MAIN_BASE] = 1 if probe else 0
    table = actions_bytes(actions)
    at = labels['drv_actions'] - MAIN_BASE
    main[at:at + len(table)] = table
    image = bytearray(b'A2VMIMG1')

    def record(kind, bank, address, data):
        image.extend(struct.pack('<BBHI', kind, bank, address, len(data)))
        image.extend(data)

    record(2, 0, LC_BASE, p65.lc)
    if card is not None:
        if len(card) > LC_BASE - LC_BSS_BASE:
            raise ValueError('the card data is more than $D000-$DFFF')
        record(2, 0, LC_BSS_BASE, bytes(card))
    record(0, 0, MAIN_BASE, bytes(main))
    for index, data in enumerate(songs):
        record(1, SONG_BANK0 + index, SONG_ADDRESS, bytes(data))
    (directory / 'sound.img').write_bytes(bytes(image))
    (directory / 'rom.bin').write_bytes(bytes(0x4000))
    name = cost_profile(ntsc, variants, profile)
    (directory / 'cost.txt').write_text(costs.text(name))
    fabric_hz = costs.parameters(name)['fabric_mhz'] * 1e6
    args = [str(a2vm), '--rom', str(directory / 'rom.bin'),
            '--core', 'w65c02s', '--via-ora-nh',
            '--image', str(directory / 'sound.img'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--reg', 'pc=%X' % labels['drv_start'], '--reg', 's=FF',
            '--reg', 'p=34',
            '--cost', str(directory / 'cost.txt'), '--cost-timed',
            '--cycles', str(int(round(seconds * fabric_hz))),
            '--ay-log', str(directory / 'ay.log'),
            '--state', str(directory / 'state.json'),
            '--irq-bounds', IRQ_BOUNDS,
            '--stop-pc', '%X' % labels['drv_halt'],
            '--stop-pc', '%X' % labels['snd_crash']]
    for label in stop_at:
        args += ['--stop-pc', '%X' % labels[label]]
    if mb_only:
        args.append('--phasor-mb-only')
    if mode == IDLE_MODE:
        args += ['--idle', '%X:vbl:eq=%X,%X' % (
            labels['drv_idle'], labels['vbl_count'], labels['drv_seen'])]
    if snapshot:
        args += ['--snapshot-dir', str(directory), '--final-snapshot']
    result = subprocess.run(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, universal_newlines=True)
    if result.returncode:
        halt = ''
        state = directory / 'state.json'
        if state.exists():
            halt = json.loads(state.read_text()).get('halt', '')
        raise RuntimeError('a2vm failed: %s\n%s' % (halt, result.stdout))
    out = Run(directory, labels)
    if out.state['end'] != 'cycles':
        raise RuntimeError('the run ended early (%s at $%04X, A=$%02X)'
                           % (out.state['end'], out.state['pc'],
                              out.state['a']))
    return out


def read_log(path):
    """The AY log (tools/a2vm/README.md, "The AY log") as tuples:
    ('w', chip, reg, value, cycles, clock), ('reset', chip),
    ('irq', n, cycles, clock), ('rti', cycles, clock)."""
    events = []
    with open(path) as log:
        for line in log:
            if line.startswith('#'):
                continue
            f = line.split()
            if f[0] == 'w':
                events.append(('w', int(f[4]), int(f[5]), int(f[6]),
                               int(f[1]), clock_of(f[3])))
            elif f[0] == 'irq':
                events.append(('irq', int(f[1]), int(f[2]), clock_of(f[4])))
            elif f[0] == 'rti':
                events.append(('rti', int(f[1]), clock_of(f[3])))
            elif f[0] == 'reset':
                events.append(('reset', int(f[4])))
            else:
                raise ValueError('%s: unknown line %r' % (path, line))
    return events


def clock_of(text):
    return None if text == '-' else int(text)


def group(events):
    """(main, bursts, times, partial): main[0] the writes (chip, reg,
    value) and chip resets ('reset', chip) before the first interrupt,
    main[k] those after interrupt k; bursts[k - 1] those of interrupt k,
    between its entry and its RTI; times[k - 1] its (entry clock, RTI
    clock). An interrupt the run cut is left out of them: partial is what
    it wrote, or None."""
    main, bursts, times = [[]], [], []
    current = None
    for event in events:
        if event[0] == 'irq':
            if current is not None:
                raise ValueError('an interrupt inside an interrupt')
            current, entry = [], event[3]
        elif event[0] == 'rti':
            if current is None:
                raise ValueError('an RTI outside an interrupt')
            bursts.append(current)
            times.append((entry, event[2]))
            main.append([])
            current = None
        elif event[0] == 'w':
            (main[-1] if current is None else current).append(event[1:4])
        elif event[0] == 'reset':
            (main[-1] if current is None else current).append(event)
    return main, bursts, times, current


# ---------------------------------------------------------------------------
# the oracle
# ---------------------------------------------------------------------------

class RingPlayer(player.Player):
    """player.Player reading its stream through the 65C02 player's ring
    (src/sound/player.s: commands, refill, copy_page) instead of from
    memory. Its commands() is Player.commands with the ring's two
    differences: after the $FF of a looping song the refill has put the
    loop's bytes, so the stream reads on; and when the bytes of the next
    command are not all in the ring, every music voice is silenced and the
    position held (native-sound.md 4.3). stop() is snd_stop."""

    RING = 1024
    PAGE = 256

    def __init__(self, song, machine, loop=False, music_attenuation=0):
        super().__init__(song, machine, loop, music_attenuation)
        self.rpos = 0               # bytes consumed
        self.wpos = 0               # bytes in the ring (whole pages)
        self.src = 0                # the next byte to copy
        self.exhausted = False
        self.playing = True
        self.stopping = False
        self.underruns = 0

    def byte(self, position):
        s = self.song.stream
        if position < len(s):
            return s[position]
        if not self.loop:
            return 0                # past the end: never read
        span = len(s) - self.song.loop
        return s[self.song.loop + (position - len(s)) % span]

    def copy_page(self):
        end = len(self.song.stream)
        if self.loop:
            self.src += self.PAGE
        elif self.src >= end:
            self.exhausted = True
        elif self.src + self.PAGE > end:
            self.src = end
            self.exhausted = True
        else:
            self.src += self.PAGE
        self.wpos += self.PAGE

    def refill(self):
        while not self.exhausted and self.wpos - self.rpos <= 512:
            self.copy_page()
            if not self.exhausted:
                self.copy_page()

    def start(self):
        """snd_start: fill the ring, then the first burst."""
        self.refill()
        return self.reset()

    def stop(self):
        if self.playing:
            self.stopping = True

    def silence(self):
        for v in range(len(self.slots)):
            self.phase[v] = player.IDLE
            self.eatt[v] = player.SILENT
            self.flags[v] = 0
            self.hit[v] = 0

    def interrupt(self):
        if not self.playing:
            return []
        if self.stopping:
            self.silence()
            self.compose()
            writes = self.flush()
            self.playing = self.stopping = False
            return writes
        return super().interrupt()

    def commands(self):
        if self.wait:
            self.wait -= 1
            if self.wait:
                return
        wrapped = False
        while True:
            avail = self.wpos - self.rpos
            if avail == 0:
                self.underruns += 1
                self.silence()
                return
            op = self.byte(self.rpos)
            if op == player.END:
                if not self.loop:
                    self.ended = True
                    return
                if wrapped:
                    raise player.SongFileError('a looping stream without '
                                               'a wait')
                wrapped = True
                self.rpos += 1
                continue
            if op & 0x80:
                if op == player.WAIT:
                    raise player.SongFileError('wait of 0 ticks')
                self.wait = op & 0x7f
                self.rpos += 1
                return
            command, v = op >> 4, op & 15
            length = 1 + player.OPERANDS[command]
            if length > avail:
                self.underruns += 1
                self.silence()
                return
            if v >= len(self.slots):
                raise player.SongFileError('voice %d' % v)
            a = [self.byte(self.rpos + i) for i in range(1, length)]
            if command <= player.NOTE_ATT_ENV:
                self.note_on(v, a[0], a[1] if command >= player.NOTE_ATT
                             else None,
                             a[2] if command == player.NOTE_ATT_ENV else None)
            elif command == player.NOTE_OFF:
                if self.flags[v] & player.JUST_ON:
                    self.flags[v] |= player.OFF_PENDING
                elif player.ATTACK <= self.phase[v] <= player.SUSTAIN:
                    self.phase[v] = player.RELEASE
            elif command == player.ATTENUATION:
                self.natt[v] = a[0]
            elif command == player.BEND:
                self.bend[v] = a[0]
                self.set_tone(v, tables.bent_period(
                    self.period[self.note[v]], self.bend[v]))
            elif command == player.DRUM_HIT:
                self.hit[v] = a[0] + 1
                self.natt[v] = a[1]
            elif command == player.CUT:
                self.phase[v] = player.IDLE
                self.eatt[v] = player.SILENT
                self.flags[v] = 0
                self.hit[v] = 0
            self.rpos += length


def machine_of(ntsc):
    return tables.NTSC_NATIVE if ntsc else tables.PAL_NATIVE


def expected(songs, actions, count):
    """(main, bursts) the driver and the player should write for
    `actions`, over `count` interrupts, with RingPlayer as the player."""
    main, bursts = [[]], []
    state = {'player': None, 'gate': True}
    pending = sorted(actions, key=lambda a: a[1])

    def service(n, refill):
        while pending and pending[0][1] <= n:
            kind, _, bank, _, flags, matt = pending.pop(0)
            if kind == START:
                machine = machine_of(bool(flags & SONG_NTSC))
                p = RingPlayer(songs[bank - SONG_BANK0], machine,
                               loop=bool(flags & SONG_LOOP),
                               music_attenuation=matt)
                main[-1].extend(p.start())
                state['player'] = p
            elif kind == STOP:
                if state['player']:
                    state['player'].stop()
            elif kind == GATE_OFF:
                state['gate'] = False
            elif kind == GATE_ON:
                state['gate'] = True
        p = state['player']
        if refill and state['gate'] and p and p.playing:
            p.refill()

    service(0, False)
    for k in range(1, count + 1):
        p = state['player']
        bursts.append(p.interrupt() if p else [])
        main.append([])
        service(k, True)
    return main, bursts, state['player']


def player_model(song, machine, count, loop=True, matt=0):
    """player.Player itself: (the first burst, the bursts of `count`
    interrupts, the player after them)."""
    p = player.Player(song, machine, loop=loop, music_attenuation=matt)
    init = p.reset()
    return init, [p.interrupt() for _ in range(count)], p


def player_py(song, machine, count, loop=True, matt=0):
    """(the first burst, the bursts of `count` interrupts)."""
    init, bursts, _ = player_model(song, machine, count, loop, matt)
    return init, bursts


def init_events(probe=False, mb_only=False):
    """The chip resets and writes the driver makes before snd_start (with
    no music, all it makes): the probe's, then snd_init's."""
    return (PROBE_EVENTS[mb_only] if probe else ()) + INIT_RESETS


def compare(actual_main, actual_bursts, want_main, want_bursts,
            prefix=INIT_RESETS):
    """None when equal, else a description of the first difference.
    actual_main[0] must begin with `prefix` (snd_init's chip resets);
    a reset anywhere else is a difference."""
    if len(actual_bursts) != len(want_bursts):
        return '%d interrupts, expected %d' % (len(actual_bursts),
                                               len(want_bursts))
    prefix = list(prefix)
    head = actual_main[0][:len(prefix)] if actual_main else []
    if head != prefix:
        return 'before the start: %s, expected %s' % (head, prefix)
    actual_main = [actual_main[0][len(prefix):]] + list(actual_main[1:])
    for k in range(len(want_main)):
        got = actual_main[k] if k < len(actual_main) else None
        if got != want_main[k]:
            return 'main loop after interrupt %d: %s' % (
                k, first_difference(got or [], want_main[k]))
        if k < len(want_bursts) and actual_bursts[k] != want_bursts[k]:
            return 'interrupt %d: %s' % (
                k + 1, first_difference(actual_bursts[k], want_bursts[k]))
    return None


def first_difference(got, want):
    for i, (a, b) in enumerate(zip(got, want)):
        if a != b:
            return 'write %d is %s, expected %s (chip, reg, value)' % (
                i, a, b)
    return '%d writes, expected %d (%s)' % (len(got), len(want),
                                            (got[len(want):] or
                                             want[len(got):])[:3])


def final_difference(result, model, mode=NATIVE_MODE):
    """None when the chips' registers at the end of the run (a2vm's
    state.json, phasor.ay) are what `model` (a player.Player or
    RingPlayer after the interrupts compared, or None when no song
    started) holds in its shadow, the chips it does not hold all 0, and
    the card in `mode` (a2vm's phasor.mode); else the difference. When the run
    ended inside an interrupt, what that interrupt wrote must begin the
    model's next burst, and counts."""
    want = [[0] * 16 for _ in range(4)]
    if model is not None:
        for chip, registers in model.shadow.items():
            want[chip][:len(registers)] = registers
    if result.partial:
        following = copy.deepcopy(model).interrupt() if model else []
        if result.partial != following[:len(result.partial)]:
            return ('the interrupt the run cut: %s, expected the start of %s'
                    % (result.partial[:4], following[:4]))
        for chip, reg, value in result.partial:
            want[chip][reg] = value
    phasor = result.state['phasor']
    for chip in range(4):
        if phasor['ay'][chip] != want[chip]:
            return 'at the end chip %d holds %s, expected %s' % (
                chip, phasor['ay'][chip], want[chip])
    if phasor['mode'] != mode:
        return 'at the end the card is in mode %d, expected %d' % (
            phasor['mode'], mode)
    return None


def compare_song(p65, song_path, seconds, directory, ntsc=False, loop=True,
                 a2vm=A2VM, variants=('phasor',), probe=False):
    """Play one song file from its start (after snd_probe with `probe`)
    and compare every interrupt with player.py, then the chips' registers
    at the end with its shadow. Returns (difference or None, interrupts
    compared)."""
    data = Path(song_path).read_bytes()
    song = player.SongFile.from_bytes(data)
    result = run(p65, [data], [start_action(0, 0, loop=loop, ntsc=ntsc)],
                 seconds, directory, ntsc=ntsc, a2vm=a2vm, variants=variants,
                 probe=probe)
    machine = machine_of(ntsc)
    count = len(result.bursts)
    nominal = int(seconds * tables.vbl_hz(machine))
    if abs(count - nominal) > 1:
        return ('%d interrupts in %g s, expected %d' % (count, seconds,
                                                         nominal), count)
    init, bursts, model = player_model(song, machine, count, loop=loop)
    difference = compare(result.main, result.bursts,
                         [init] + [[] for _ in bursts], bursts,
                         init_events(probe))
    return difference or final_difference(result, model), count


# ---------------------------------------------------------------------------
# sizes and cost
# ---------------------------------------------------------------------------

# native-sound.md 4.3 (the player's budget in the card) and NATIVE.md 4.3
BUDGET = (
    ('SNDCODE', 'code (music, bursts, refill, the IRQ entry)', 2000,
     'native-sound.md 4.3: about 2,000 with the effects; NATIVE.md 4.3: '
     'player and effects 3-5 KB'),
    ('SNDRODATA', 'tables: periods PAL and NTSC, bend, levels, layout', 800,
     'native-sound.md 4.3: about 800'),
    ('SNDBSS', 'state: voices, shadows, song tables', 500,
     'native-sound.md 4.3: voices and shadows about 200, song tables <= 300'),
    ('SNDLIST', 'write lists (in one page)', None, 'not in the design'),
    ('SNDRING', 'the song ring (and its 3-byte mirror)', 1024,
     'native-sound.md 4.3: 1,024'),
    ('SNDZP', 'zero page (player and IRQ entry)', None,
     'the IRQ contract: the card or the zero page'),
)


# the player's segments in the card's $D000 bank, not loaded
CARD_DATA = ('SNDRING', 'SNDLIST', 'SNDBSS')


def sizes(out=OUT):
    """[('Bytes', {segment: size, 'PAD': the alignment gaps between the
    card's data segments})]: one column, the player's one build."""
    seg = segments(Path(out) / 'sound.map')
    row = {name: seg.get(name, (0, 0))[1] for name, *_ in BUDGET}
    spans = [seg[name] for name in CARD_DATA]
    extent = max(s + n for s, n in spans) - min(s for s, _ in spans)
    row['PAD'] = extent - sum(n for _, n in spans)
    return [('Bytes', row)]


def sizes_table(out=OUT):
    rows = sizes(out)
    lines = ['| Part | ' + ' | '.join(l for l, _ in rows) +
             ' | Budget | Source of the budget |',
             '| --- | ' + ' | '.join('---:' for _ in rows) + ' | ---: | --- |']
    for name, what, budget, source in BUDGET:
        lines.append('| %s (`%s`) | %s | %s | %s |' % (
            what, name, ' | '.join('{:,}'.format(r[name]) for _, r in rows),
            '{:,}'.format(budget) if budget else '-', source))
    lines.append('| alignment padding in the card (between `SNDRING`, '
                 '`SNDLIST`, `SNDBSS`) | %s | - | the ring is page aligned |'
                 % ' | '.join('{:,}'.format(r['PAD']) for _, r in rows))
    data = ['{:,}'.format(sum(r[n] for n, *_ in BUDGET
                              if n not in ('SNDZP', 'SNDCODE')) + r['PAD'])
            for _, r in rows]
    lines.append('| **Data in the card** | %s | 2,324 | native-sound.md '
                 '4.3 without the effect buffers (800 + 200 + 1,024 + 300); '
                 'NATIVE.md 4.1 gives the player 4.2 KB with them |'
                 % ' | '.join(data))
    return '\n'.join(lines)


VARIANTS = (('F1.2.1, window 512', ('phasor',)),
            ('window 32', ('phasor', 'window32')),
            ('FW-S1', ('phasor', 'fws1')))
# native-sound.md 2.3 and 4.2: a write 40.4 us at 1 MHz (8.4 us with
# FW-S1), a burst's tail 504 us (window 512) or 31.5 us (window 32)
DESIGN_COSTS = ((40.4, 504.0), (40.4, 31.5), (8.4, 0.0))
# native-sound.md 4.2's table (native12, 50 Hz): ms a second
DESIGN_TABLE = {'D_E1M1': (23.9, 6.6, 1.12), 'D_E1M3': (25.6, 5.3, 0.81),
                'D_E1M5': (12.9, 2.6, 0.39), 'D_E1M6': (27.5, 7.1, 1.20),
                'D_E1M8': (11.5, 2.5, 0.40), 'D_INTER': (24.7, 6.5, 1.11)}


BASE_SECONDS = 60.0


def counted(p65, songs, actions, seconds, directory, variants, a2vm=A2VM):
    """A count-mode run: {count: the driver loop's iterations, irq: the
    clocks spent between the interrupts' entries and RTIs, interrupts,
    bursts (interrupts that wrote), writes}."""
    result = run(p65, songs, actions, seconds, directory, variants=variants,
                 mode=COUNT_MODE, a2vm=a2vm, snapshot=True)
    writes = [[e for e in b if e[0] != 'reset'] for b in result.bursts]
    out = {'count': result.word('drv_counter', 4),
           'irq': sum(b - a for a, b in result.times),
           'interrupts': len(result.bursts),
           'bursts': sum(1 for b in writes if b),
           'writes': sum(len(b) for b in writes)}
    shutil.rmtree(str(result.directory), True)
    return out


def song_seconds(song, machine):
    """The song once to its end, plus one second (tools/sound/report.py's
    span, and the design's)."""
    _, bursts = player.run(song, machine)
    return len(bursts) / tables.vbl_hz(machine)


def measure(names, work, jobs=4, a2vm=A2VM, out=OUT, seconds=None):
    """The player's cost for each song file (each played once, not
    looping, or `seconds` of it) under the three settings of VARIANTS:
    [(song, {label: row})]. Its time is what it takes from the
    main loop: 1 - (the loop's count with the song) / (the count with no
    song over the same time), the interrupt entry, the acknowledge and the
    VBL count being in both runs. 'in the IRQ' is the part spent between
    the interrupts' entries and RTIs, the rest being the slow window's
    tail and the refills."""
    fabric = costs.parameters('f121')['fabric_mhz'] * 1e6
    machine = machine_of(False)
    tasks = []
    for label, variants in VARIANTS:
        tasks.append((None, label, variants, BASE_SECONDS))
    for path in song_files(names):
        song = player.SongFile.from_bytes(path.read_bytes())
        span = seconds or song_seconds(song, machine)
        for label, variants in VARIANTS:
            tasks.append((path, label, variants, span))
    tasks.sort(key=lambda t: -t[3])
    p65 = Player65(out)

    def one(task):
        path, label, variants, span = task
        name = path.name.split('.')[0] if path else 'none'
        directory = Path(work) / ('%s-%s' % (name, '+'.join(variants)))
        songs = [path.read_bytes()] if path else []
        actions = [start_action(0, 0, loop=False)] if path else []
        return task, counted(p65, songs, actions, span, directory, variants,
                             a2vm)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        done = list(pool.map(one, tasks))
    base = {t[1]: r for t, r in done if t[0] is None}
    results = {}
    for (path, label, variants, span), r in done:
        if path is None:
            continue
        b = base[label]
        rate = b['count'] / BASE_SECONDS
        irq_each = b['irq'] / b['interrupts']
        key = path.name.split('.')[0]
        results.setdefault(key, {})[label] = {
            'seconds': span,
            'ms_per_s': 1000.0 * (1.0 - r['count'] / (rate * span)),
            'irq_ms_per_s': 1000.0 * (r['irq'] - irq_each *
                                      r['interrupts']) / fabric / span,
            'bursts_per_s': r['bursts'] / span,
            'writes_per_s': r['writes'] / span}
    order = [p.name.split('.')[0] for p in song_files(names)]
    return [(key, results[key]) for key in order]


def cost_table(results):
    lines = ['| Song | Seconds | Bursts/s | Writes/s | ' +
             ' | '.join('%s: ms/s (in the IRQ) | formula | 4.2' % label
                        for label, _ in VARIANTS) + ' |',
             '| --- | ---: | ---: | ---: | ' + ' | '.join(
                 '---: | ---: | ---:' for _ in VARIANTS) + ' |']
    for name, rows in results:
        first = rows[VARIANTS[0][0]]
        cells = []
        for i, (label, _) in enumerate(VARIANTS):
            r = rows[label]
            per_write, tail = DESIGN_COSTS[i]
            formula = (r['bursts_per_s'] * tail +
                       r['writes_per_s'] * per_write) / 1000.0
            table = DESIGN_TABLE.get(name)
            cells.append('%.2f (%.2f) | %.2f | %s' % (
                r['ms_per_s'], r['irq_ms_per_s'], formula,
                '%.2f' % table[i] if table else '-'))
        lines.append('| %s | %.1f | %.1f | %.1f | %s |' % (
            name, first['seconds'], first['bursts_per_s'],
            first['writes_per_s'], ' | '.join(cells)))
    return '\n'.join(lines)


def update_readme(marker, text):
    content = README.read_text()
    begin = '<!-- %s:begin -->' % marker
    end = '<!-- %s:end -->' % marker
    head, rest = content.split(begin, 1)
    _, tail = rest.split(end, 1)
    README.write_text(head + begin + '\n' + text + '\n' + end + tail)


# ---------------------------------------------------------------------------

def song_files(names):
    """build/sound/SONG.native12.ay of each name, or every song file."""
    if not names:
        names = [p.name.split('.')[0]
                 for p in sorted(SONGS.glob('*.%s.ay' % LAYOUT.name))]
    return [SONGS / ('%s.%s.ay' % (n, LAYOUT.name)) for n in names]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('songs', nargs='*')
    parser.add_argument('--seconds', type=float)
    parser.add_argument('--ntsc', action='store_true')
    parser.add_argument('--no-loop', action='store_true')
    parser.add_argument('--sizes', action='store_true')
    parser.add_argument('--cost', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--update-readme', action='store_true')
    parser.add_argument('--keep', help='keep the runs in this directory')
    args = parser.parse_args(argv)
    build()
    if not A2VM.exists():
        build_a2vm()
    if args.sizes:
        text = sizes_table()
        print(text)
        if args.update_readme:
            update_readme('sizes', text)
        return 0
    work = Path(args.keep) if args.keep else Path(
        tempfile.mkdtemp(prefix='run65-', dir=str(BUILD)))
    try:
        if args.cost:
            results = measure(args.songs, work / 'cost', args.jobs,
                              seconds=args.seconds)
            text = cost_table(results)
            print(text)
            if args.update_readme:
                update_readme('cost', text)
            return 0
        seconds = args.seconds or (20.0 if args.ntsc else 60.0)
        failures = 0
        p65 = Player65()
        jobs = [(p65, path) for path in song_files(args.songs)]

        def one(job):
            p65, path = job
            directory = work / ('%s-%s' % (path.stem, 'ntsc' if args.ntsc
                                           else 'pal'))
            return job, compare_song(p65, path, seconds, directory,
                                     ntsc=args.ntsc, loop=not args.no_loop)

        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for (p65, path), (difference, count) in pool.map(one, jobs):
                print('%-24s %5d interrupts  %s' % (
                    path.name, count, difference or 'equal'), flush=True)
                failures += difference is not None
        return 1 if failures else 0
    finally:
        if not args.keep:
            shutil.rmtree(str(work), True)


if __name__ == '__main__':
    sys.exit(main())
