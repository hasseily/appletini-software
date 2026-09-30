#!/usr/bin/env python3
"""The WAD directory and the MUS songs of DOOM (DMX's music format).

Usage:  python3 tools/sound/mus.py [--wad FILE] [SONG ...]

Lists the songs of the WAD (default: build/upstream/data/DOOM1.WAD, put
there by tools/fetch_upstream.py) and, for each song, its header and the
count of each kind of event.

Written from the published layouts, with no code from upstream.

A WAD: "IWAD" or "PWAD", a little-endian u32 lump count, a u32 offset of
the directory; the directory has 16 bytes a lump: u32 offset, u32 size,
8 bytes of name padded with NULs.

A MUS lump, all numbers little-endian:

    0  "MUS" $1A
    4  u16 score length          bytes of events
    6  u16 score start           offset of the first event
    8  u16 primary channels      count of channels 0.. used
   10  u16 secondary channels    count of channels 10.. used
   12  u16 instrument count
   14  u16 reserved
   16  u16 instrument numbers    GENMIDI programs, 135 and up for drums

An event starts with a byte L TTT CCCC: L set means a delay follows the
event, TTT is the type and CCCC the channel (15 is percussion).

    type 0  release note   1 byte: note (bit 7 clear)
    type 1  play note      1 byte: note, bit 7 set when a volume byte
                           (0-127) follows; else the channel's last volume
    type 2  pitch bend     1 byte: 0-255, 128 is no bend
    type 3  system event   1 byte: 10 all sounds off, 11 all notes off,
                           12 mono, 13 poly, 14 reset all controllers
    type 4  controller     2 bytes: number 0-9, value 0-127. 0 program,
                           1 bank, 2 modulation, 3 volume, 4 pan,
                           5 expression, 6 reverb, 7 chorus, 8 sustain
                           pedal, 9 soft pedal
    type 5  end of measure no byte
    type 6  score end      no byte
    type 7  (none)         an error

A delay is a number in base 128, most significant group first, with bit 7
set on every byte but the last. Its unit is a tick of 1/140 s.

The "last volume" of a channel starts at 127 before its first volume byte
(an assumption shared by the MUS-to-MIDI converters; DMX's own start value
is not documented). The parser is strict: anything outside the ranges
above is a MusError with the offset of the byte.
"""

import argparse
import struct
import sys
from collections import Counter, namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAD_PATH = ROOT / 'build' / 'upstream' / 'data' / 'DOOM1.WAD'

TICK_HZ = 140
MAGIC = b'MUS\x1a'
HEADER_SIZE = 16
PERCUSSION = 15
FIRST_VOLUME = 127
MAX_DELAY_BYTES = 4

# Upstream's song numbers: 0-8 E1M1-E1M9, 9 INTER, 10 INTRO, 11 VICTOR,
# 12 INTROA (build/upstream/src/iigs/s_sound65.s:1298-1300). INTROA has no
# DOC song unit upstream; here every song comes from its MUS lump.
UPSTREAM_SONGS = ('D_E1M1', 'D_E1M2', 'D_E1M3', 'D_E1M4', 'D_E1M5',
                  'D_E1M6', 'D_E1M7', 'D_E1M8', 'D_E1M9', 'D_INTER',
                  'D_INTRO', 'D_VICTOR', 'D_INTROA')

KINDS = ('off', 'on', 'bend', 'sys', 'ctrl', 'measure', 'end')
CONTROLLERS = ('program', 'bank', 'modulation', 'volume', 'pan',
               'expression', 'reverb', 'chorus', 'sustain', 'soft')
SYSTEM_EVENTS = {10: 'all sounds off', 11: 'all notes off', 12: 'mono',
                 13: 'poly', 14: 'reset all controllers'}


class MusError(ValueError):
    """A MUS lump that does not follow the format."""

    def __init__(self, message, offset=None):
        if offset is not None:
            message = '%s (offset %d)' % (message, offset)
        super().__init__(message)
        self.offset = offset


class WadError(ValueError):
    """A WAD file that does not follow the format."""


# One event. tick: absolute, in 1/140 s. kind: one of KINDS. chan: 0-15.
#   off      a = note
#   on       a = note, b = velocity (the volume byte, or the channel's
#            last volume), volume = the volume byte or None
#   bend     a = 0-255
#   sys      a = 10-14
#   ctrl     a = controller number 0-9, b = value
#   measure, end: a = b = 0
# offset: where the event's first byte is in the lump.
Event = namedtuple('Event', 'tick kind chan a b volume offset')


class Song:
    """A parsed MUS lump."""

    def __init__(self, name, score_length, score_start, primary, secondary,
                 instruments, events, size):
        self.name = name
        self.score_length = score_length
        self.score_start = score_start
        self.primary = primary
        self.secondary = secondary
        self.instruments = instruments
        self.events = events
        self.size = size

    @property
    def length_ticks(self):
        """The tick of the score end."""
        return self.events[-1].tick

    @property
    def seconds(self):
        return self.length_ticks / TICK_HZ

    def counts(self):
        """Events by kind, controllers as 'ctrl N', system as 'sys N'."""
        counts = Counter()
        for e in self.events:
            counts[e.kind] += 1
            if e.kind in ('ctrl', 'sys'):
                counts['%s %d' % (e.kind, e.a)] += 1
        return counts


def _u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def parse(data, name=None):
    """The Song of a MUS lump; a MusError when it is malformed."""
    data = bytes(data)
    if len(data) < HEADER_SIZE:
        raise MusError('header truncated: %d bytes of %d'
                       % (len(data), HEADER_SIZE))
    if data[:4] != MAGIC:
        raise MusError('not a MUS lump: magic %r' % data[:4], 0)
    score_length = _u16(data, 4)
    score_start = _u16(data, 6)
    primary = _u16(data, 8)
    secondary = _u16(data, 10)
    count = _u16(data, 12)
    list_end = HEADER_SIZE + 2 * count
    if list_end > len(data):
        raise MusError('instrument list of %d runs past the end of the '
                       'lump' % count, 12)
    if score_start < list_end:
        raise MusError('score starts at %d, inside the header or the '
                       'instrument list (which ends at %d)'
                       % (score_start, list_end), 6)
    score_end = score_start + score_length
    if score_end > len(data):
        raise MusError('score of %d bytes from %d runs past the end of the '
                       'lump (%d bytes)' % (score_length, score_start,
                                            len(data)), 4)
    instruments = [_u16(data, HEADER_SIZE + 2 * i) for i in range(count)]

    def byte(position, what, start):
        if position >= score_end:
            raise MusError('event truncated: %s missing' % what, start)
        return data[position]

    events = []
    last_volume = [FIRST_VOLUME] * 16
    tick = 0
    position = score_start
    while True:
        if position >= score_end:
            raise MusError('no score end event before the end of the score',
                           position)
        start = position
        head = data[position]
        position += 1
        kind = (head >> 4) & 7
        chan = head & 15
        a = b = 0
        volume = None
        if kind == 0:
            a = byte(position, 'note', start)
            position += 1
            if a & 0x80:
                raise MusError('release note with bit 7 set', start + 1)
        elif kind == 1:
            a = byte(position, 'note', start)
            position += 1
            if a & 0x80:
                a &= 0x7f
                volume = byte(position, 'volume', start)
                position += 1
                if volume & 0x80:
                    raise MusError('volume above 127', position - 1)
                last_volume[chan] = volume
            b = last_volume[chan]
        elif kind == 2:
            a = byte(position, 'bend', start)
            position += 1
        elif kind == 3:
            a = byte(position, 'system event', start)
            position += 1
            if a not in SYSTEM_EVENTS:
                raise MusError('unknown system event %d' % a, start + 1)
        elif kind == 4:
            a = byte(position, 'controller number', start)
            b = byte(position + 1, 'controller value', start)
            position += 2
            if a >= len(CONTROLLERS):
                raise MusError('unknown controller %d' % a, start + 1)
            if b & 0x80:
                raise MusError('controller value above 127', start + 2)
        elif kind == 7:
            raise MusError('unknown event type 7', start)
        events.append(Event(tick, KINDS[kind], chan, a, b, volume, start))
        if kind == 6:
            break
        if head & 0x80:
            delay = 0
            for _ in range(MAX_DELAY_BYTES):
                x = byte(position, 'delay', start)
                position += 1
                delay = (delay << 7) | (x & 0x7f)
                if not x & 0x80:
                    break
            else:
                raise MusError('delay longer than %d bytes'
                               % MAX_DELAY_BYTES, start)
            tick += delay
    return Song(name, score_length, score_start, primary, secondary,
                instruments, events, len(data))


class Wad:
    """The directory of a WAD file and its lumps."""

    def __init__(self, data):
        data = bytes(data)
        if len(data) < 12:
            raise WadError('WAD header truncated')
        kind, count, directory = struct.unpack_from('<4sII', data, 0)
        if kind not in (b'IWAD', b'PWAD'):
            raise WadError('not a WAD: %r' % kind)
        if directory + 16 * count > len(data):
            raise WadError('directory runs past the end of the file')
        self.kind = kind.decode('ascii')
        self.data = data
        self.lumps = []
        for i in range(count):
            offset, size, raw = struct.unpack_from('<II8s', data,
                                                   directory + 16 * i)
            name = raw.split(b'\0')[0].decode('ascii', 'replace')
            if offset + size > len(data):
                raise WadError('lump %s runs past the end of the file' % name)
            self.lumps.append((name, offset, size))

    @classmethod
    def open(cls, path=WAD_PATH):
        with open(path, 'rb') as f:
            return cls(f.read())

    def names(self, prefix=''):
        return [n for n, _, _ in self.lumps if n.startswith(prefix)]

    def lump(self, name):
        """The bytes of the first lump of that name; KeyError if none."""
        for n, offset, size in self.lumps:
            if n == name:
                return self.data[offset:offset + size]
        raise KeyError(name)

    def songs(self):
        """The names of the music lumps (D_*), in directory order."""
        return self.names('D_')

    def song(self, name):
        return parse(self.lump(name), name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--wad', default=str(WAD_PATH))
    parser.add_argument('songs', nargs='*')
    args = parser.parse_args(argv)
    wad = Wad.open(args.wad)
    names = args.songs or wad.songs()
    print('%s: %s, %d lumps, %d songs'
          % (args.wad, wad.kind, len(wad.lumps), len(wad.songs())))
    print('upstream song list: %s' % ' '.join(
        '%d=%s' % (i, n) for i, n in enumerate(UPSTREAM_SONGS)))
    print()
    print('%-9s %6s %7s %6s %6s %6s %5s %5s  %s' % (
        'song', 'bytes', 'seconds', 'events', 'on', 'off', 'bends', 'ctrls',
        'instruments'))
    for name in names:
        song = wad.song(name)
        c = song.counts()
        print('%-9s %6d %7.1f %6d %6d %6d %5d %5d  %s' % (
            name, song.size, song.seconds, len(song.events), c['on'],
            c['off'], c['bend'], c['ctrl'],
            ' '.join(str(i) for i in song.instruments)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
