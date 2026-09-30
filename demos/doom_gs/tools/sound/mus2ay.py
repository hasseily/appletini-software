#!/usr/bin/env python3
"""MUS to a song file of AY voice commands for the Phasor.

Usage:  python3 tools/sound/mus2ay.py [SONG ...] [--out DIR] [--wad FILE]

Writes DIR/SONG.native12.ay (default DIR: build/sound) and prints the
converter's counts. native12 (tables.py) is the only voice layout: the
music plays with the card in native mode, 12 voices on 4 AY chips. The
design is docs/research/native-sound.md section 3; tools/sound/README.md
has the file format and what departs from the design.

What the converter decides on the host, so that the 65C02 player does
not have to:

- Voices. The layout's melodic voices are allocated to notes here: the
  same channel and note still held takes its voice again; else an idle
  voice (its release over); else the voice whose release ends first (a
  "release cut"); else a steal: the lowest sounding note (the bass) is
  kept, and the oldest note of the channel that holds the most voices is
  taken. Among idle voices, one that already holds the note's pitch is
  preferred, then one with the note's envelope, then the one idle the
  longest (allocate() says why). Drums take an idle drum voice, else
  the one of the oldest hit (a "drum steal"; a hit counts as over
  when it has decayed by 20 dB, half its decay time); of idle drum voices,
  one that last played the same recipe is preferred, as it needs no
  register writes but the level (and R13 for a loud hit).
- Pitch. The note number goes in the stream; the player looks up the
  period for its clock. GENMIDI's note offset of the program is added,
  and a fixed-pitch program plays its fixed note. The MUS bend byte goes
  in the stream as it is.
- Loudness. Velocity, channel volume (controller 3) and expression
  (controller 5) each follow 40 log10(v / 127) dB, and the program's
  carrier level adds 0.75 dB a step; the sum, in 0.5 dB steps, is the
  note attenuation. A volume or expression change is sent to a voice
  holding a note of the channel only when it changes the AY level of that
  attenuation.
- Instruments. Each program used gets a software envelope from its
  GENMIDI carrier (genmidi.py): attack, decay and release steps a tick,
  the sustain level, and whether the level is held while the key is down.
- Percussion. Each drum note used gets a recipe from DRUMS: a tone note or
  none, a noise period or none, and a decay time. A loud hit uses the
  chip's envelope generator, a quiet one a software decay.
- Edge cases of MUS that the WAD's songs do not use: a note of volume 0
  is a note off (as a MIDI note on of velocity 0); system event 10 (all
  sounds off) cuts the channel's voices at once with the $7v command, on
  channel 15 the drum voices; 11 (all notes off) releases the channel's
  held notes; 14 (reset all controllers) sets expression to 127, with
  the level change sent to the held notes, and the bend to the centre.
"""

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import genmidi, mus, player, tables  # noqa: E402

BUILD_SOUND = mus.ROOT / 'build' / 'sound'
TICK_MS = 1000.0 / tables.TICK_HZ
MAX_WAIT = 126
PENDING_OFF_TICKS = 3      # a release can start up to one interrupt late

# Drum recipes: GM drum note -> (tone note or 0, noise period or 0, decay
# in ms). Hand-made first guesses, to tune by ear.
DRUMS = {
    35: (33, 0, 160),    # acoustic bass drum
    36: (33, 0, 160),    # bass drum
    37: (72, 4, 30),     # side stick
    38: (50, 6, 180),    # acoustic snare
    39: (0, 3, 120),     # hand clap
    40: (50, 6, 180),    # electric snare
    41: (40, 12, 250),   # low floor tom
    42: (0, 1, 50),      # closed hi-hat
    43: (43, 12, 250),   # high floor tom
    44: (0, 1, 70),      # pedal hi-hat
    45: (47, 12, 250),   # low tom
    46: (0, 1, 350),     # open hi-hat
    47: (50, 12, 250),   # low-mid tom
    48: (53, 12, 250),   # hi-mid tom
    49: (0, 2, 1200),    # crash cymbal 1
    50: (57, 12, 250),   # high tom
    51: (84, 1, 600),    # ride cymbal 1
    52: (0, 2, 900),     # chinese cymbal
    53: (88, 1, 500),    # ride bell
    55: (0, 1, 500),     # splash cymbal
    57: (0, 2, 1200),    # crash cymbal 2
    59: (84, 1, 600),    # ride cymbal 2
    75: (84, 0, 40),     # claves
    80: (96, 0, 80),     # mute triangle
    81: (96, 0, 500),    # open triangle
}
DEFAULT_DRUM = (0, 3, 150)


def steps(units, ms):
    """A 16-bit step a tick that covers `units` attenuation steps in `ms`,
    at least 1."""
    ticks = ms / TICK_MS
    if ticks <= 0:
        return 0xffff
    return max(1, min(0xffff, int(math.floor(units * 256 / ticks + 0.5))))


def envelope_of(instrument):
    """The player's envelope (attack, decay, release, sustain, flags) for a
    GENMIDI instrument. OPL rates follow genmidi.ATTACK_MS and DECAY_MS;
    decay and release are linear in dB over 96 dB, attack over the
    player's 40 dB. A rate of 0 is taken as 1 (an OPL rate 0 never moves:
    no program in the WAD's songs uses it for attack or release)."""
    attack = steps(tables.ATT_MAX,
                   genmidi.ATTACK_MS[instrument.attack_rate or 1])
    if instrument.decay_rate:
        decay = steps(96 / tables.ATT_UNIT_DB,
                      genmidi.DECAY_MS[instrument.decay_rate])
    else:
        decay = 0
    release = steps(96 / tables.ATT_UNIT_DB,
                    genmidi.DECAY_MS[instrument.release_rate or 1])
    sustain = min(tables.ATT_MAX,
                  int(round(3.0 * instrument.sustain_level
                            / tables.ATT_UNIT_DB)))
    flags = player.ENV_SUSTAINED if instrument.sustained else 0
    return (attack, decay, release, sustain, flags)


def drum_recipe(note, machine):
    """(tone, noise, envelope period, soft step) of a GM drum note; the
    envelope period is for `machine`'s PSG clock (the converter uses the
    PAL one): the envelope generator's one-shot decay lasts 256 x period
    / clock."""
    tone, noise, ms = DRUMS.get(note, DEFAULT_DRUM)
    period = int(math.floor(ms / 1000.0 * tables.psg_clock(machine) / 256
                            + 0.5))
    return (tone, noise, max(1, min(0xffff, period)),
            steps(tables.ATT_MAX, ms))


def release_ticks(envelope):
    """Ticks from full level to silence at the envelope's release rate."""
    return -(-(tables.ATT_MAX << 8) // envelope[2])


class _Voice:
    def __init__(self, index):
        self.index = index
        self.key = None          # (MUS channel, MUS note) while held
        self.chan = None         # MUS channel of its last note
        self.on_tick = 0
        self.free_tick = 0       # the tick it may be taken again (melodic:
                                 # its release is over; drum: 20 dB down)
        self.end_tick = 0        # drum: the tick its decay is over
        self.note = None         # what the player holds: None = unknown
        self.natt = None
        self.env = None
        self.bend = None
        self.vel_att = 0         # parts of the note attenuation
        self.level_att = 0


class Converter:
    """One song. convert() returns (SongFile, Counter)."""

    def __init__(self, song, instruments):
        self.song = song
        self.instruments = instruments
        self.layout = layout = tables.NATIVE12
        self.machine = tables.PAL_NATIVE
        nm = len(layout.melodic)
        self.voices = [_Voice(i) for i in range(nm)]
        self.drum_voices = [_Voice(nm + i) for i in range(len(layout.drums))]
        self.program = [0] * 16
        self.volume = [127] * 16
        self.expression = [127] * 16
        self.chan_bend = [128] * 16
        self.envelopes = []          # entries of the song's table
        self.env_index = {}          # program -> index
        self.drum_notes = []
        self.drum_index = {}
        self.out = bytearray()
        self.now = 0                 # tick of the next command
        self.written = 0             # tick the stream has reached
        self.stats = Counter()
        self.max_voices = 0
        self.used = set()

    # -- stream -----------------------------------------------------------

    def emit(self, *data):
        while self.written < self.now:
            n = min(MAX_WAIT, self.now - self.written)
            self.out.append(player.WAIT + n)
            self.written += n
        self.out.extend(data)

    # -- helpers ----------------------------------------------------------

    def channel_att(self, chan):
        return (tables.ATTENUATION_OF_VALUE[self.volume[chan]]
                + tables.ATTENUATION_OF_VALUE[self.expression[chan]])

    def note_att(self, voice, chan):
        return min(tables.ATT_MAX, voice.vel_att + voice.level_att
                   + self.channel_att(chan))

    def envelope(self, program):
        if program not in self.env_index:
            self.env_index[program] = len(self.envelopes)
            self.envelopes.append(envelope_of(self.instruments[program]))
        return self.env_index[program]

    def voices_of(self, chan):
        """The voices holding a note of the channel. Volume and bend
        changes are sent to these only: a note in its release keeps the
        loudness and pitch it had at its note off."""
        return [v for v in self.voices
                if v.key is not None and v.key[0] == chan]

    # -- events -----------------------------------------------------------

    def note_on(self, chan, note, velocity):
        instrument = self.instruments[self.program[chan]]
        if instrument.fixed:
            played = instrument.fixed_note
        else:
            played = min(127, max(0, note + instrument.note_offset))
        env = self.envelope(self.program[chan])
        key = (chan, note)
        voice = next((v for v in self.voices if v.key == key), None)
        if voice is None:
            voice = self.allocate(env, played, self.chan_bend[chan])
        voice.key = key
        voice.chan = chan
        voice.on_tick = self.now
        voice.vel_att = tables.ATTENUATION_OF_VALUE[velocity]
        # the carrier level, 0.75 dB a step = 1.5 units, rounded half up
        voice.level_att = (3 * instrument.level + 1) // 2
        natt = self.note_att(voice, chan)
        if natt >= tables.ATT_MAX:
            self.stats['silent notes'] += 1
        op = voice.index
        if voice.env != env:
            self.emit(0x20 | op, played, natt, env)
        elif voice.natt != natt:
            self.emit(0x10 | op, played, natt)
        else:
            self.emit(op, played)
        voice.env, voice.natt, voice.note = env, natt, played
        if voice.bend != self.chan_bend[chan]:
            voice.bend = self.chan_bend[chan]
            self.emit(0x50 | op, voice.bend)
        self.stats['notes'] += 1
        self.used.add(voice.index)
        held = sum(1 for v in self.voices if v.key is not None)
        self.max_voices = max(self.max_voices, held)

    def allocate(self, env, played, bend):
        """A voice for a new note. Among idle voices, the one that needs
        the fewest register writes and stream bytes: same pitch (no tone
        write), then same envelope, then the one idle the longest. With 7
        melodic voices this saves tone writes: 158,353 writes for the 13
        songs on PAL against 162,548 with the design's plain longest-idle
        rule (D_E1M1 122 a second against 132), and 135,903 stream bytes
        against 139,183 (measured 2026-09-30). Among releasing voices,
        the release that ends first. A steal keeps the lowest note (of
        equal ones, the one on the lowest voice) and takes the oldest note
        of the channel holding the most voices."""
        def pitch_differs(v):
            return v.note != played or v.bend != bend
        idle = [v for v in self.voices
                if v.key is None and v.free_tick <= self.now]
        if idle:
            return min(idle, key=lambda v: (pitch_differs(v), v.env != env,
                                            v.free_tick, v.index))
        releasing = [v for v in self.voices if v.key is None]
        if releasing:
            self.stats['release cuts'] += 1
            return min(releasing, key=lambda v: (v.free_tick, v.index))
        self.stats['steals'] += 1
        bass = min(self.voices, key=lambda v: (v.key[1], v.index))
        per_channel = Counter(v.key[0] for v in self.voices)
        victims = [v for v in self.voices if v is not bass]
        victim = min(victims, key=lambda v: (-per_channel[v.key[0]],
                                             v.on_tick, v.index))
        victim.key = None
        return victim

    def note_off(self, chan, note):
        voice = next((v for v in self.voices if v.key == (chan, note)), None)
        if voice is None:
            self.stats['lost offs'] += 1
            return
        self.release(voice)

    def release(self, voice):
        voice.key = None
        voice.free_tick = (self.now + PENDING_OFF_TICKS
                           + release_ticks(self.envelopes[voice.env]))
        self.emit(0x30 | voice.index)
        self.stats['offs'] += 1

    def drum(self, note, velocity):
        if note not in self.drum_index:
            self.drum_index[note] = len(self.drum_notes)
            self.drum_notes.append(note)
        recipe = DRUMS.get(note, DEFAULT_DRUM)
        idle = [v for v in self.drum_voices if v.free_tick <= self.now]
        if idle:
            # the idle voice that last played this recipe needs no tone,
            # noise, mixer or envelope period writes; else the first
            voice = min(idle, key=lambda v: (v.note != recipe, v.index))
        else:
            voice = min(self.drum_voices, key=lambda v: (v.on_tick, v.index))
            self.stats['drum steals'] += 1
        voice.note = recipe
        voice.on_tick = self.now
        ms = recipe[2]
        voice.free_tick = self.now + max(1, int(math.ceil(ms / TICK_MS / 2)))
        voice.end_tick = self.now + max(1, int(math.ceil(ms / TICK_MS)))
        natt = min(tables.ATT_MAX, tables.ATTENUATION_OF_VALUE[velocity]
                   + self.channel_att(mus.PERCUSSION))
        self.emit(0x60 | voice.index, self.drum_index[note], natt)
        self.stats['drum hits'] += 1
        if natt > tables.HW_DRUM_ATT:
            self.stats['soft drum hits'] += 1

    def controller(self, chan, number, value):
        if number == 0:
            self.program[chan] = value
            return
        if number not in (3, 5):
            self.stats['ignored controllers'] += 1
            return
        if number == 3:
            self.volume[chan] = value
        else:
            self.expression[chan] = value
        self.stats['volume events'] += 1
        self.channel_loudness(chan)

    def channel_loudness(self, chan):
        """After a volume or expression change: the new attenuation to the
        voices holding a note of the channel whose AY level it changes.
        A drum hit takes the channel's loudness when it starts."""
        if chan == mus.PERCUSSION:
            return
        for voice in self.voices_of(chan):
            natt = self.note_att(voice, chan)
            if tables.LEVEL[natt] != tables.LEVEL[voice.natt]:
                voice.natt = natt
                self.emit(0x40 | voice.index, natt)
                self.stats['volume commands'] += 1

    def pitch_bend(self, chan, value):
        self.chan_bend[chan] = value
        self.stats['bend events'] += 1
        for voice in self.voices_of(chan):
            if voice.bend != value:
                voice.bend = value
                self.emit(0x50 | voice.index, value)
                self.stats['bend commands'] += 1

    def system(self, chan, number):
        """10, all sounds off: every voice still sounding a note of the
        channel (held or in its release; on channel 15 the drum voices)
        is cut at once. 11, all notes off: the channel's held notes are
        released. 14, reset all controllers: expression back to 127 and
        the bend to the centre, as MIDI's reset; the channel volume
        stays."""
        if number == 10:
            if chan == mus.PERCUSSION:
                cut = [v for v in self.drum_voices if v.end_tick > self.now]
            else:
                cut = [v for v in self.voices if v.chan == chan and
                       (v.key is not None or v.free_tick > self.now)]
            for voice in cut:
                voice.key = None
                voice.free_tick = voice.end_tick = self.now
                self.emit(0x70 | voice.index)
                self.stats['cuts'] += 1
        elif number == 11:
            for voice in self.voices_of(chan):
                self.release(voice)
                self.stats['released by 11'] += 1
        elif number == 14:
            self.expression[chan] = 127
            self.channel_loudness(chan)
            if chan != mus.PERCUSSION:
                self.pitch_bend(chan, 128)
        else:
            self.stats['ignored system events'] += 1

    # -- the song -----------------------------------------------------------

    def convert(self):
        for event in self.song.events:
            self.now = event.tick
            kind, chan = event.kind, event.chan
            if kind == 'on' and event.b == 0:
                # a note of volume 0 is a note off, as in MIDI (a note on
                # of velocity 0) and DMX; for a drum, nothing to play
                kind = 'off'
            if kind == 'on':
                if chan == mus.PERCUSSION:
                    self.drum(event.a, event.b)
                else:
                    self.note_on(chan, event.a, event.b)
            elif kind == 'off':
                if chan != mus.PERCUSSION:
                    self.note_off(chan, event.a)
            elif kind == 'bend':
                if chan != mus.PERCUSSION:
                    self.pitch_bend(chan, event.a)
            elif kind == 'ctrl':
                self.controller(chan, event.a, event.b)
            elif kind == 'sys':
                self.system(chan, event.a)
            elif kind == 'end':
                for voice in self.voices:
                    if voice.key is not None:
                        self.release(voice)
                        self.stats['offs at the end'] += 1
                self.now = max(self.now, 1)
                self.emit(player.END)
        drums = [drum_recipe(n, self.machine) for n in self.drum_notes]
        song = player.SongFile(self.layout, self.envelopes, drums,
                               bytes(self.out))
        self.stats['max voices'] = self.max_voices
        self.stats['voices used'] = len(self.used)
        return song, self.stats


def convert(song, instruments):
    """(SongFile, Counter of counts) of a mus.Song."""
    return Converter(song, instruments).convert()


def song_file_name(name):
    """The song file of a song: SONG.native12.ay."""
    return '%s.%s.ay' % (name, tables.NATIVE12.name)


def load_instruments(wad):
    return genmidi.read(wad.lump('GENMIDI'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('songs', nargs='*')
    parser.add_argument('--out', default=str(BUILD_SOUND))
    parser.add_argument('--wad', default=str(mus.WAD_PATH))
    args = parser.parse_args(argv)
    wad = mus.Wad.open(args.wad)
    instruments = load_instruments(wad)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in args.songs or wad.songs():
        song_file, stats = convert(wad.song(name), instruments)
        data = song_file.to_bytes()
        path = out / song_file_name(name)
        path.write_bytes(data)
        print('%-9s %6d bytes  %s' % (name, len(data), ', '.join(
            '%s %d' % item for item in sorted(stats.items()))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
