"""The song file of the 65C02 music player (src/sound), as mus2ay.py
writes it: a header, the envelope table, the drum-recipe table and the
stream of voice commands (tools/sound/README.md has the format). The
player's tables that depend on the machine, not on the song, are
tables.py's.

Units: an attenuation step is 0.5 dB; 80 (40 dB) is silent.
"""

import struct
from collections import namedtuple

FORMAT_VERSION = 1
HEADER = struct.Struct('<BBBBHH')
ENVELOPE = struct.Struct('<HHHBB')
DRUM = struct.Struct('<BBHH')

ENV_SUSTAINED = 1          # envelope flag: the level holds while the key
                           # is down (else the release starts after decay)

# Stream commands: the high nibble of the op byte; the low nibble is the
# voice. See tools/sound/README.md.
(NOTE, NOTE_ATT, NOTE_ATT_ENV, NOTE_OFF, ATTENUATION, BEND, DRUM_HIT,
 CUT) = range(8)
WAIT = 0x80                # $81-$FE: wait 1-126 ticks
END = 0xFF

Envelope = namedtuple('Envelope', 'attack decay release sustain flags')
DrumRecipe = namedtuple('DrumRecipe', 'tone noise period step')


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
