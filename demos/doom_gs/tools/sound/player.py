#!/usr/bin/env python3
"""Model of the 65C02 music player: a song file in, AY register writes out.

Usage:  python3 tools/sound/player.py SONGFILE [--machine pal-native]
                [--seconds S] [--loop] [--log OUT.log]

This is the specification of the 65C02 player and the oracle of milestone
S2: the 65C02 code keeps the same state, runs the same steps in the same
order with the same integer arithmetic, and must write the same AY
registers, in the same order, after every interrupt. Every quantity of
the state below is a byte or a 16-bit word, and every operation is one
the 65C02 does directly: add or subtract with carry, compare, shift,
table lookup, and one 12 x 8 bit multiply (the pitch bend). That product
is the one wider value: up to 4095 x 251, 20 bits, so the bend needs 3
bytes of scratch for the product, the rounding add of 1024 and the
shift by 11 (tables.bent_period).

The song file (written by mus2ay.py; tools/sound/README.md has the
format) holds an envelope table, a drum-recipe table and the stream of
voice commands. The player also has tables that depend on the machine,
not on the song (tables.py): the note periods for the PSG clock, the
bend magnitudes, the attenuation-to-level table and the tempo.

State (NV voices: the layout's melodic voices, then its drum voices):

    pos        u16  stream position
    wait       u8   ticks until the next commands
    frac       u16  tempo fraction
    ended      flag the stream met $FF with looping off
    matt       u8   music attenuation (0-80), the volume setting
    phase[v]   u8   0 idle, 1 attack, 2 decay, 3 sustain, 4 release,
                    5 drum on the chip's envelope, 6 drum soft decay
    eatt[v]    u16  envelope attenuation, 1/256 units (0 to 80 x 256)
    natt[v]    u8   note attenuation (velocity, volume, instrument)
    env[v]     u8   envelope index into the song's table
    note[v]    u8
    bend[v]    u8   128 is no bend
    flags[v]   u8   bit 0 JUST_ON: started in this interrupt
                    bit 1 OFF_PENDING: released in the interrupt it
                    started, so the release waits for the next one
    dstep[v]   u16  soft drum decay a tick
    hit[v]     u8   drum hit latched in this interrupt: recipe + 1, or 0
    want[c][r] u8   registers the player wants on chip c
    shadow[c][r] u8 registers the chip holds
    retrig[c]  flag R13 must be written even when equal (restarts the
                    envelope)

Units: an attenuation step is 0.5 dB; 80 (40 dB) is silent.
"""

import argparse
import struct
import sys
from collections import namedtuple
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import tables  # noqa: E402

FORMAT_VERSION = 1
HEADER = struct.Struct('<BBBBHH')
ENVELOPE = struct.Struct('<HHHBB')
DRUM = struct.Struct('<BBHH')

JUST_ON = 1
OFF_PENDING = 2

IDLE, ATTACK, DECAY, SUSTAIN, RELEASE, DRUM_HW, DRUM_SOFT = range(7)

ENV_SUSTAINED = 1          # envelope flag: the level holds while the key
                           # is down (else the release starts after decay)
SILENT = tables.ATT_MAX << 8

# Stream commands: the high nibble of the op byte; the low nibble is the
# voice. See tools/sound/README.md.
(NOTE, NOTE_ATT, NOTE_ATT_ENV, NOTE_OFF, ATTENUATION, BEND, DRUM_HIT,
 CUT) = range(8)
WAIT = 0x80                # $81-$FE: wait 1-126 ticks
END = 0xFF
OPERANDS = (1, 2, 3, 0, 1, 1, 2, 0)

Envelope = namedtuple('Envelope', 'attack decay release sustain flags')
DrumRecipe = namedtuple('DrumRecipe', 'tone noise period step')


class SongFileError(ValueError):
    """A song file or stream that does not follow the format."""


class SongFile:
    """A song file: layout, envelope and drum tables, stream."""

    def __init__(self, layout, envelopes, drums, stream, loop=0):
        self.layout = layout
        self.envelopes = [Envelope(*e) for e in envelopes]
        self.drums = [DrumRecipe(*d) for d in drums]
        self.stream = bytes(stream)
        self.loop = loop

    def to_bytes(self):
        out = bytearray(HEADER.pack(FORMAT_VERSION, self.layout.ident,
                                    len(self.envelopes), len(self.drums),
                                    len(self.stream), self.loop))
        for e in self.envelopes:
            out += ENVELOPE.pack(*e)
        for d in self.drums:
            out += DRUM.pack(*d)
        return bytes(out + self.stream)

    @classmethod
    def from_bytes(cls, data):
        data = bytes(data)
        if len(data) < HEADER.size:
            raise SongFileError('song file header truncated')
        version, ident, ne, nd, length, loop = HEADER.unpack_from(data)
        if version != FORMAT_VERSION:
            raise SongFileError('song file version %d' % version)
        if ident not in tables.LAYOUT_BY_IDENT:
            raise SongFileError('unknown layout %d' % ident)
        at = HEADER.size
        envelopes = []
        for _ in range(ne):
            envelopes.append(ENVELOPE.unpack_from(data, at))
            at += ENVELOPE.size
        drums = []
        for _ in range(nd):
            drums.append(DRUM.unpack_from(data, at))
            at += DRUM.size
        stream = data[at:at + length]
        if len(stream) != length or at + length != len(data):
            raise SongFileError('stream length %d does not match the file'
                                % length)
        return cls(tables.LAYOUT_BY_IDENT[ident], envelopes, drums, stream,
                   loop)


def decode_stream(stream):
    """[(tick, op, voice, operands)] of a stream, op the command number
    (0-6), up to and including END as (tick, END, None, ())."""
    out = []
    tick = 0
    pos = 0
    while True:
        if pos >= len(stream):
            raise SongFileError('stream ends without $FF')
        op = stream[pos]
        if op == END:
            out.append((tick, END, None, ()))
            return out
        if op & 0x80:
            if op == WAIT:
                raise SongFileError('wait of 0 ticks at %d' % pos)
            tick += op & 0x7f
            pos += 1
            continue
        command = op >> 4
        if command >= len(OPERANDS):
            raise SongFileError('unknown command $%02X at %d' % (op, pos))
        count = OPERANDS[command]
        operands = tuple(stream[pos + 1:pos + 1 + count])
        if len(operands) != count:
            raise SongFileError('command $%02X truncated' % op)
        out.append((tick, command, op & 15, operands))
        pos += 1 + count


class Player:
    """The 65C02 player, step by step."""

    def __init__(self, song, machine, loop=False, music_attenuation=0):
        if isinstance(song, (bytes, bytearray)):
            song = SongFile.from_bytes(song)
        self.song = song
        self.layout = song.layout
        self.machine = machine
        self.loop = loop
        self.slots = tables.voices(self.layout)
        self.owned = tables.owned_registers(self.layout)
        self.period = tables.period_table(machine)
        self.tempo_int, self.tempo_frac = tables.tempo(machine)
        self.matt = music_attenuation
        nv = len(self.slots)
        self.phase = [IDLE] * nv
        self.eatt = [SILENT] * nv
        self.natt = [0] * nv
        self.env = [0] * nv
        self.note = [0] * nv
        self.bend = [128] * nv
        self.flags = [0] * nv
        self.dstep = [0] * nv
        self.hit = [0] * nv
        self.pos = 0
        self.wait = 0
        self.frac = 0
        self.ended = False
        self.want = {c: [0] * 14 for c in self.layout.chips}
        self.shadow = {c: [0] * 14 for c in self.layout.chips}
        self.retrig = {c: False for c in self.layout.chips}

    # -- start ------------------------------------------------------------

    def reset(self):
        """The first burst: every chip of the layout gets R0-R12. All
        levels 0, all periods 0, the mixer $38 (tones on, noises off, as
        the Bilestoad driver starts). The effects player owns its
        channels after this."""
        for chip in self.layout.chips:
            self.want[chip] = [0] * 14
            self.want[chip][7] = 0x38
        writes = []
        for chip in self.layout.chips:
            for reg in range(13):
                writes.append((chip, reg, self.want[chip][reg]))
            self.shadow[chip] = list(self.want[chip])
        return writes

    # -- one interrupt ------------------------------------------------------

    def interrupt(self):
        """One VBL interrupt: the AY writes of its burst, in order."""
        # 1. A note that started and ended in the last interrupt was shown
        #    for that one; its release starts now. Then clear the flags.
        for v in range(len(self.slots)):
            if self.flags[v] & OFF_PENDING and ATTACK <= self.phase[v] <= \
                    SUSTAIN:
                self.phase[v] = RELEASE
            self.flags[v] = 0
        # 2. The ticks due: TEMPO_INT plus the carry of the fraction.
        total = self.frac + self.tempo_frac
        self.frac = total & 0xffff
        for _ in range(self.tempo_int + (total >> 16)):
            self.tick()
        # 3. Levels, 4. the burst.
        self.compose()
        return self.flush()

    def tick(self):
        """One MUS tick: the stream commands due, then the envelopes."""
        if not self.ended:
            self.commands()
        self.envelopes()

    def commands(self):
        if self.wait:
            self.wait -= 1
            if self.wait:
                return
        s = self.song.stream
        wrapped = False
        while True:
            op = s[self.pos]
            if op == END:
                if not self.loop:
                    self.ended = True
                    return
                if wrapped:
                    raise SongFileError('a looping stream without a wait')
                wrapped = True
                self.pos = self.song.loop
                continue
            if op & 0x80:
                if op == WAIT:
                    raise SongFileError('wait of 0 ticks at %d' % self.pos)
                self.wait = op & 0x7f
                self.pos += 1
                return
            command = op >> 4
            v = op & 15
            if v >= len(self.slots):
                raise SongFileError('voice %d at %d' % (v, self.pos))
            if command <= NOTE_ATT_ENV:
                self.note_on(v, s[self.pos + 1],
                             s[self.pos + 2] if command >= NOTE_ATT else None,
                             s[self.pos + 3] if command == NOTE_ATT_ENV
                             else None)
                self.pos += 2 + command
            elif command == NOTE_OFF:
                if self.flags[v] & JUST_ON:
                    self.flags[v] |= OFF_PENDING
                elif ATTACK <= self.phase[v] <= SUSTAIN:
                    self.phase[v] = RELEASE
                self.pos += 1
            elif command == ATTENUATION:
                self.natt[v] = s[self.pos + 1]
                self.pos += 2
            elif command == BEND:
                self.bend[v] = s[self.pos + 1]
                self.set_tone(v, tables.bent_period(
                    self.period[self.note[v]], self.bend[v]))
                self.pos += 2
            elif command == DRUM_HIT:
                self.hit[v] = s[self.pos + 1] + 1    # latched: the last
                self.natt[v] = s[self.pos + 2]       # hit of the interrupt
                self.pos += 3                        # sounds (compose)
            elif command == CUT:
                self.phase[v] = IDLE                 # silent at the next
                self.eatt[v] = SILENT                # compose, drums too;
                self.flags[v] = 0                    # a latched hit is
                self.hit[v] = 0                      # dropped
                self.pos += 1
            else:
                raise SongFileError('unknown command $%02X at %d'
                                    % (op, self.pos))

    def note_on(self, v, note, natt, env):
        if natt is not None:
            self.natt[v] = natt
        if env is not None:
            self.env[v] = env
        self.note[v] = note
        self.set_tone(v, tables.bent_period(self.period[note], self.bend[v]))
        self.phase[v] = ATTACK          # from the current eatt, as an OPL
        self.flags[v] = JUST_ON         # clears OFF_PENDING

    def set_tone(self, v, period):
        chip, channel = self.slots[v]
        self.want[chip][2 * channel] = period & 0xff
        self.want[chip][2 * channel + 1] = period >> 8

    def drum_start(self, v, index):
        """The drum hit latched in this interrupt starts: tone, noise and
        mixer from its recipe, then the chip's envelope (a loud hit) or a
        software decay (a quiet one), from full level."""
        chip, channel = self.slots[v]
        recipe = self.song.drums[index]
        want = self.want[chip]
        mixer = want[7] | (9 << channel)          # tone and noise off
        if recipe.tone:
            self.set_tone(v, self.period[recipe.tone])
            mixer &= ~(1 << channel)
        if recipe.noise:
            want[6] = recipe.noise
            mixer &= ~(8 << channel)
        want[7] = mixer
        if self.natt[v] + self.matt <= tables.HW_DRUM_ATT:
            period = recipe.period
            want[11] = period & 0xff
            want[12] = period >> 8
            want[13] = 0                           # shape \___ : one decay
            self.retrig[chip] = True
            self.phase[v] = DRUM_HW
        else:
            self.eatt[v] = 0
            self.dstep[v] = recipe.step
            self.phase[v] = DRUM_SOFT

    def envelopes(self):
        """Each voice's envelope moves one tick. A 16-bit add that carries
        is past every limit, like a sum at or above it."""
        for v in range(len(self.slots)):
            phase = self.phase[v]
            a = self.eatt[v]
            if phase == DRUM_SOFT:
                a += self.dstep[v]
                if a >= SILENT:                    # (carry or >= limit)
                    a = SILENT
                    phase = IDLE
            elif phase == ATTACK:
                e = self.song.envelopes[self.env[v]]
                a -= e.attack
                if a <= 0:                         # (borrow or zero)
                    a = 0
                    phase = DECAY
            elif phase == DECAY:
                e = self.song.envelopes[self.env[v]]
                a += e.decay
                if a >= e.sustain << 8:
                    a = e.sustain << 8
                    phase = SUSTAIN if e.flags & ENV_SUSTAINED else RELEASE
            elif phase == RELEASE:
                e = self.song.envelopes[self.env[v]]
                a += e.release
                if a >= SILENT:
                    a = SILENT
                    phase = IDLE
            self.eatt[v] = a
            self.phase[v] = phase

    def compose(self):
        """Start the latched drum hits, then set the level register of
        every music voice."""
        for v, (chip, channel) in enumerate(self.slots):
            if self.hit[v]:
                self.drum_start(v, self.hit[v] - 1)
                self.hit[v] = 0
            phase = self.phase[v]
            if phase == IDLE:
                level = 0
            elif phase == DRUM_HW:
                level = 0x10
            else:
                # each term is at most 80: the byte sum cannot carry
                a = self.natt[v] + (self.eatt[v] >> 8) + self.matt
                level = tables.LEVEL[tables.ATT_MAX if a > tables.ATT_MAX
                                     else a]
            self.want[chip][8 + channel] = level

    def flush(self):
        """Owned registers that differ from the shadow, chips in ascending
        order, registers in ascending order; R13 also when retriggered."""
        writes = []
        for chip, regs in self.owned.items():
            want = self.want[chip]
            shadow = self.shadow[chip]
            for reg in regs:
                if want[reg] != shadow[reg] or (reg == 13 and
                                                self.retrig[chip]):
                    writes.append((chip, reg, want[reg]))
                    shadow[reg] = want[reg]
            self.retrig[chip] = False
        return writes


def run(song, machine, seconds=None, loop=False, music_attenuation=0,
        tail_seconds=1.0):
    """(init writes, [writes of each interrupt]) for `seconds` of music, or
    for the whole song plus `tail_seconds` when seconds is None."""
    if seconds is None and loop:
        raise ValueError('a looping song needs a length in seconds')
    player = Player(song, machine, loop=loop,
                    music_attenuation=music_attenuation)
    init = player.reset()
    rate = tables.vbl_hz(machine)
    bursts = []
    if seconds is not None:
        for _ in range(int(seconds * rate)):
            bursts.append(player.interrupt())
        return init, bursts
    tail = int(tail_seconds * rate)
    while tail > 0:
        bursts.append(player.interrupt())
        if player.ended:
            tail -= 1
    return init, bursts


def register_log(init, bursts, machine):
    """[(bus cycle, chip, reg, value)]: the init burst at cycle 0, burst k
    at the k+1-th interrupt, one write every CYCLES_PER_WRITE cycles."""
    out = []
    for i, (chip, reg, value) in enumerate(init):
        out.append((i * tables.CYCLES_PER_WRITE, chip, reg, value))
    for k, burst in enumerate(bursts):
        base = (k + 1) * machine.vbl_cycles
        for i, (chip, reg, value) in enumerate(burst):
            out.append((base + i * tables.CYCLES_PER_WRITE, chip, reg,
                        value))
    return out


def write_log(path, log, machine):
    with open(path, 'w') as f:
        f.write('# bus_hz %d psg_multiplier %d\n'
                % (machine.bus_hz, machine.psg_multiplier))
        for cycle, chip, reg, value in log:
            f.write('%d %d %d %d\n' % (cycle, chip, reg, value))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('song')
    parser.add_argument('--machine', default='pal-native',
                        choices=sorted(tables.MACHINES))
    parser.add_argument('--seconds', type=float)
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--log')
    args = parser.parse_args(argv)
    machine = tables.MACHINES[args.machine]
    song = SongFile.from_bytes(Path(args.song).read_bytes())
    init, bursts = run(song, machine, args.seconds, args.loop)
    counts = [len(b) for b in bursts]
    print('%d interrupts, %d writes (+%d at init), at most %d a burst'
          % (len(bursts), sum(counts), len(init), max(counts or [0])))
    if args.log:
        write_log(args.log, register_log(init, bursts, machine), machine)
    return 0


if __name__ == '__main__':
    sys.exit(main())
