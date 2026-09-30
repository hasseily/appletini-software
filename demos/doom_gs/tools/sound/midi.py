"""A minimal standard MIDI file reader (formats 0 and 1).

Written from the MIDI 1.0 file specification for the independent check of
the MUS decoders: mus2mid.py converts a MUS lump, this module reads the
result back, and as_mus_events() maps it to the tuples tests compare with
mus.py's events.

read(data) returns (format, division, events); an event is
(tick, track, kind, channel, data) with kind one of 'note_off',
'note_on', 'aftertouch', 'controller', 'program', 'pressure', 'bend',
'meta', 'sysex'. Running status is supported. Tracks of format 1 are
merged by tick, in track order within a tick.
"""

import struct


class MidiError(ValueError):
    """Bytes that are not a standard MIDI file."""


_CHANNEL_KINDS = {0x8: 'note_off', 0x9: 'note_on', 0xa: 'aftertouch',
                  0xb: 'controller', 0xc: 'program', 0xd: 'pressure',
                  0xe: 'bend'}
_DATA_BYTES = {0x8: 2, 0x9: 2, 0xa: 2, 0xb: 2, 0xc: 1, 0xd: 1, 0xe: 2}


def _chunks(data):
    position = 0
    while position < len(data):
        if position + 8 > len(data):
            raise MidiError('chunk header truncated at %d' % position)
        kind = data[position:position + 4]
        (size,) = struct.unpack_from('>I', data, position + 4)
        body = data[position + 8:position + 8 + size]
        if len(body) != size:
            raise MidiError('chunk %r truncated' % kind)
        yield kind, body
        position += 8 + size


def _number(body, position):
    value = 0
    for _ in range(4):
        if position >= len(body):
            raise MidiError('variable-length number truncated')
        byte = body[position]
        position += 1
        value = (value << 7) | (byte & 0x7f)
        if byte < 0x80:
            return value, position
    raise MidiError('variable-length number longer than 4 bytes')


def _track(body, index):
    events = []
    position = 0
    tick = 0
    status = None
    while position < len(body):
        delta, position = _number(body, position)
        tick += delta
        if position >= len(body):
            raise MidiError('event missing after a delta time')
        first = body[position]
        if first == 0xff:
            if position + 1 >= len(body):
                raise MidiError('meta event truncated')
            meta_type = body[position + 1]
            size, position = _number(body, position + 2)
            payload = body[position:position + size]
            position += size
            events.append((tick, index, 'meta', None, (meta_type, payload)))
            if meta_type == 0x2f:
                break
            continue
        if first in (0xf0, 0xf7):
            size, position = _number(body, position + 1)
            events.append((tick, index, 'sysex', None,
                           body[position:position + size]))
            position += size
            status = None
            continue
        if first & 0x80:
            status = first
            position += 1
        elif status is None:
            raise MidiError('data byte without a running status')
        high = status >> 4
        count = _DATA_BYTES[high]
        values = tuple(body[position:position + count])
        if len(values) != count:
            raise MidiError('channel message truncated')
        position += count
        events.append((tick, index, _CHANNEL_KINDS[high], status & 15,
                       values))
    return events


def read(data):
    """(format, division, events) of a standard MIDI file."""
    chunks = list(_chunks(bytes(data)))
    if not chunks or chunks[0][0] != b'MThd' or len(chunks[0][1]) < 6:
        raise MidiError('no MThd header')
    file_format, tracks, division = struct.unpack_from('>HHH', chunks[0][1])
    bodies = [body for kind, body in chunks[1:] if kind == b'MTrk']
    if len(bodies) != tracks:
        raise MidiError('header says %d tracks, file has %d'
                        % (tracks, len(bodies)))
    events = []
    for index, body in enumerate(bodies):
        events.extend(_track(body, index))
    events.sort(key=lambda e: (e[0], e[1]))    # stable: file order kept
    return file_format, division, events


_CONTROLLER_TO_MUS = {0: 1, 1: 2, 7: 3, 10: 4, 11: 5, 91: 6, 93: 7, 64: 8,
                      67: 9}
_MODE_TO_MUS = {120: 10, 123: 11, 126: 12, 127: 13, 121: 14}


def _mus_channel(channel):
    if channel == 9:
        return 15
    if channel >= 10:
        return channel - 1
    return channel


def as_mus_events(events):
    """The events of mus2mid.py's output as MUS-shaped tuples:
    (tick, kind, channel, a, b) with the kinds and fields of mus.Event
    (velocity in b of 'on', 'measure' with the channel of its marker)."""
    out = []
    for tick, _, kind, channel, data in events:
        if kind == 'meta':
            meta_type, payload = data
            if meta_type == 0x06 and payload.startswith(b'measure '):
                out.append((tick, 'measure', int(payload[8:]), 0, 0))
            elif meta_type == 0x2f:
                out.append((tick, 'end', 0, 0, 0))
            continue
        if kind == 'sysex':
            continue
        c = _mus_channel(channel)
        if kind == 'note_on' and data[1] > 0:
            out.append((tick, 'on', c, data[0], data[1]))
        elif kind in ('note_on', 'note_off'):
            out.append((tick, 'off', c, data[0], 0))
        elif kind == 'bend':
            wheel = data[0] | (data[1] << 7)
            out.append((tick, 'bend', c, wheel >> 6, 0))
        elif kind == 'program':
            out.append((tick, 'ctrl', c, 0, data[0]))
        elif kind == 'controller':
            if data[0] in _MODE_TO_MUS:
                out.append((tick, 'sys', c, _MODE_TO_MUS[data[0]], 0))
            elif data[0] in _CONTROLLER_TO_MUS:
                out.append((tick, 'ctrl', c, _CONTROLLER_TO_MUS[data[0]],
                            data[1]))
            else:
                raise MidiError('controller %d has no MUS meaning' % data[0])
        else:
            raise MidiError('%s has no MUS meaning' % kind)
    return out
