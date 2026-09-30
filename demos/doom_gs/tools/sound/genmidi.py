"""The GENMIDI lump: DMX's OPL2 instrument bank, as the converter uses it.

Written from the published layout: "#OPL_II#", then 175 records of 36
bytes (the 128 General MIDI programs, then the percussion notes 35-81),
then 175 names of 32 bytes. A record:

    u16 flags        bit 0 fixed pitch, bit 2 two voices
    u8  fine tune    (of the second voice)
    u8  fixed note
    voice 0, then voice 1, 16 bytes each:
        modulator: characteristic, attack/decay, sustain/release,
                   waveform, key scale, level        (6 bytes)
        feedback/connection                          (1 byte)
        carrier: the same six                        (6 bytes)
        unused                                       (1 byte)
        s16 note offset                              (2 bytes)

The converter keeps, of voice 0: the carrier's envelope (attack rate,
decay rate, sustain level, release rate, the EG-type bit that says
whether the level is held while the key is down), the carrier's level,
and the note offset. The second voice, the modulator and the fine tune
are not used (tools/sound/README.md, "What needs the owner's ear").

OPL envelope times, from the YM3812 application manual's table for a
key-scale rate of 0 (an assumption: the chip's figures as commonly
quoted, not measured): attack from silence to full, decay and release
over 96 dB, in ms, by rate 0-15. Rate 0 never moves.
"""

import struct

ATTACK_MS = (None, 2826.24, 1413.12, 706.56, 353.28, 176.64, 88.32, 44.16,
             22.08, 11.04, 5.52, 2.76, 1.40, 0.70, 0.38, 0.0)
DECAY_MS = (None, 39280.64, 19640.32, 9820.16, 4910.08, 2455.04, 1227.52,
            613.76, 306.88, 153.44, 76.72, 38.36, 19.20, 9.60, 4.80, 2.40)
RECORDS = 175
RECORD_SIZE = 36
NAME_SIZE = 32


class GenmidiError(ValueError):
    """Not a GENMIDI lump."""


class Instrument:
    """Voice 0 of one GENMIDI record."""

    def __init__(self, index, record, name):
        flags, _fine, fixed = struct.unpack_from('<HBB', record, 0)
        carrier = record[4 + 7:4 + 13]
        self.index = index
        self.name = name
        self.fixed = bool(flags & 1)
        self.double = bool(flags & 4)
        self.fixed_note = fixed
        (self.note_offset,) = struct.unpack_from('<h', record, 4 + 14)
        characteristic, attack_decay, sustain_release = carrier[0:3]
        self.sustained = bool(characteristic & 0x20)
        self.attack_rate = attack_decay >> 4
        self.decay_rate = attack_decay & 15
        self.sustain_level = sustain_release >> 4     # 3 dB steps
        self.release_rate = sustain_release & 15
        self.level = carrier[5] & 63                  # 0.75 dB steps

    def __repr__(self):
        return 'Instrument(%d, %r)' % (self.index, self.name)


def read(lump):
    """The 175 Instruments of a GENMIDI lump."""
    lump = bytes(lump)
    if lump[:8] != b'#OPL_II#':
        raise GenmidiError('not a GENMIDI lump')
    names_at = 8 + RECORDS * RECORD_SIZE
    if len(lump) < names_at + RECORDS * NAME_SIZE:
        raise GenmidiError('GENMIDI lump truncated')
    out = []
    for i in range(RECORDS):
        record = lump[8 + RECORD_SIZE * i:8 + RECORD_SIZE * (i + 1)]
        raw = lump[names_at + NAME_SIZE * i:names_at + NAME_SIZE * (i + 1)]
        name = raw.split(b'\0')[0].decode('latin-1')
        out.append(Instrument(i, record, name))
    return out
