#!/usr/bin/env python3
"""MUS to a standard MIDI file: the second, independent decoder of MUS.

Usage:  python3 tools/sound/mus2mid.py SONG OUT.mid [--wad FILE]

This module shares no code with mus.py on purpose: it reads the MUS
bytes with its own loop, and its output goes through midi.py, a MIDI
reader, before tests compare the result with mus.py's events
(tests/test_sound_decoders.py). Only the WAD directory reader is shared
(it is not part of the MUS decoding).

The MIDI file is format 0, one track, 70 ticks a quarter note at
500,000 us a quarter note: one MIDI tick is one MUS tick of 1/140 s.

Mapping (the usual one of MUS-to-MIDI converters, written here from the
MIDI 1.0 specification and the MUS layout):

    MUS channel 15 -> MIDI channel 9; MUS 9-14 -> MIDI 10-15; others equal
    release note          -> note off (8n), velocity 64
    play note             -> note on (9n), velocity = the volume byte, or
                             the channel's last volume, 127 at first
    pitch bend b          -> pitch bend (En), 14 bits: b * 64
    system 10/11/12/13/14 -> controller 120/123/126/127/121, value 0
    controller 0          -> program change (Cn)
    controllers 1-9       -> controllers 0, 1, 7, 10, 11, 91, 93, 64, 67
    end of measure        -> marker meta event "measure C" (C the MUS
                             channel), so that it survives the trip
    score end             -> end of track meta event
"""

import argparse
import struct
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TICKS_PER_QUARTER = 70
MICROSECONDS_PER_QUARTER = 500000
CONTROLLER_OF = {1: 0, 2: 1, 3: 7, 4: 10, 5: 11, 6: 91, 7: 93, 8: 64, 9: 67}
SYSTEM_OF = {10: 120, 11: 123, 12: 126, 13: 127, 14: 121}


class ConvertError(ValueError):
    """The MUS bytes cannot be converted."""


def midi_channel(mus_channel):
    if mus_channel == 15:
        return 9
    if mus_channel >= 9:
        return mus_channel + 1
    return mus_channel


def variable_length(value):
    """A MIDI variable-length quantity."""
    groups = [value & 0x7f]
    value >>= 7
    while value:
        groups.append(0x80 | (value & 0x7f))
        value >>= 7
    return bytes(reversed(groups))


class _Cursor:
    def __init__(self, data, position, limit):
        self.data = data
        self.position = position
        self.limit = limit

    def take(self):
        if self.position >= self.limit:
            raise ConvertError('MUS score ends inside an event at %d'
                               % self.position)
        value = self.data[self.position]
        self.position += 1
        return value


def convert(mus_bytes):
    """The bytes of a standard MIDI file for the MUS lump."""
    if mus_bytes[0:4] != b'MUS\x1a':
        raise ConvertError('no MUS magic')
    length, start = struct.unpack_from('<HH', mus_bytes, 4)
    cursor = _Cursor(mus_bytes, start, start + length)
    track = bytearray()
    track += b'\x00\xff\x51\x03' + MICROSECONDS_PER_QUARTER.to_bytes(3, 'big')
    velocity = {}
    pending = 0          # MUS ticks since the last MIDI event

    def emit(message):
        nonlocal pending
        track.extend(variable_length(pending))
        track.extend(message)
        pending = 0

    finished = False
    while not finished:
        descriptor = cursor.take()
        event_type = (descriptor & 0x70) >> 4
        channel = descriptor & 0x0f
        out = midi_channel(channel)
        if event_type == 0:
            emit(bytes([0x80 | out, cursor.take() & 0x7f, 64]))
        elif event_type == 1:
            key = cursor.take()
            if key >= 0x80:
                velocity[channel] = cursor.take() & 0x7f
            emit(bytes([0x90 | out, key & 0x7f, velocity.get(channel, 127)]))
        elif event_type == 2:
            wheel = cursor.take() * 64
            emit(bytes([0xe0 | out, wheel & 0x7f, wheel >> 7]))
        elif event_type == 3:
            number = cursor.take()
            if number not in SYSTEM_OF:
                raise ConvertError('system event %d' % number)
            emit(bytes([0xb0 | out, SYSTEM_OF[number], 0]))
        elif event_type == 4:
            number = cursor.take()
            value = cursor.take()
            if number == 0:
                emit(bytes([0xc0 | out, value & 0x7f]))
            elif number in CONTROLLER_OF:
                emit(bytes([0xb0 | out, CONTROLLER_OF[number],
                            value & 0x7f]))
            else:
                raise ConvertError('controller %d' % number)
        elif event_type == 5:
            text = ('measure %d' % channel).encode('ascii')
            emit(b'\xff\x06' + variable_length(len(text)) + text)
        elif event_type == 6:
            emit(b'\xff\x2f\x00')
            finished = True
            continue
        else:
            raise ConvertError('event type 7')
        if descriptor & 0x80:
            ticks = 0
            while True:
                group = cursor.take()
                ticks = ticks * 128 + (group & 0x7f)
                if group < 0x80:
                    break
            pending += ticks
    header = b'MThd' + struct.pack('>IHHH', 6, 0, 1, TICKS_PER_QUARTER)
    return header + b'MTrk' + struct.pack('>I', len(track)) + bytes(track)


def main(argv=None):
    from sound import mus
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('song')
    parser.add_argument('out')
    parser.add_argument('--wad', default=str(mus.WAD_PATH))
    args = parser.parse_args(argv)
    data = convert(mus.Wad.open(args.wad).lump(args.song))
    Path(args.out).write_bytes(data)
    print('%s: %d bytes' % (args.out, len(data)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
