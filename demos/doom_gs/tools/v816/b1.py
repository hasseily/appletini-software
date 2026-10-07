"""Decoder for B1, upstream's compression of disk segments and level data.

The format is defined by upstream's tools/b1.py (encoder and reference
decoder) and by b1Seg in src/iigs/loader.s (the 65816 decoder). This is an
independent decoder, so that reading the release image needs nothing from
the upstream clone.

The stream:
- Bits come from 16-bit little-endian words, most significant bit first.
  A word sits in the byte stream at the point where the decoder runs out
  of bits, so bits and bytes share one read position.
- Numbers are interlaced Elias gamma codes: a control bit of 1 ends the
  number, a control bit of 0 is followed by one more data bit.
- The stream starts with a literal run: gamma(count), then the bytes.
- After a literal run, one bit: 0 is a match at the previous offset with
  gamma(length); 1 is a match at a new offset.
- After a match, one bit: 0 is a literal run; 1 is a match at a new offset.
- A new offset is gamma(high) and a byte b. The offset is
  ((high - 1) << 7 | b >> 1) + 1. Bit 0 of b is the first control bit of
  gamma(length - 1).
- There is no end marker. The decoder stops when it has produced the
  output length, which the container stores outside the stream.
"""


class B1Error(ValueError):
    """The stream is not a valid B1 stream for the requested length."""


class _Reader:
    """The read position shared by the bit words and the bytes."""

    def __init__(self, stream: bytes):
        self.stream = stream
        self.position = 0
        self.word = 0
        self.bits_left = 0

    def byte(self) -> int:
        if self.position >= len(self.stream):
            raise B1Error('the stream ends inside a token')
        value = self.stream[self.position]
        self.position += 1
        return value

    def bytes(self, count: int) -> bytes:
        if self.position + count > len(self.stream):
            raise B1Error('the stream ends inside a literal run')
        start = self.position
        self.position += count
        return self.stream[start:self.position]

    def bit(self) -> int:
        if self.bits_left == 0:
            self.word = self.byte() | self.byte() << 8
            self.bits_left = 16
        self.bits_left -= 1
        return self.word >> self.bits_left & 1

    def gamma(self, control=None) -> int:
        """A gamma code; `control` is its first control bit when the
        caller has it already (from the offset byte)."""
        value = 1
        if control is None:
            control = self.bit()
        while not control:
            value = value << 1 | self.bit()
            control = self.bit()
        return value


def decode(stream: bytes, length: int) -> bytes:
    """The `length` bytes that `stream` decodes to.

    Raises B1Error when the stream ends early, refers to data before the
    start of the output, or has a token that crosses the output length.
    The 65816 decoder tests for the end by equality, so such a token would
    make it run on; a valid stream never has one.
    """
    reader = _Reader(stream)
    out = bytearray()
    offset = 1

    def copy(count: int) -> None:
        if offset > len(out):
            raise B1Error('match offset %d at output position %d'
                          % (offset, len(out)))
        for _ in range(count):
            out.append(out[-offset])

    out += reader.bytes(reader.gamma())
    after_literals = True
    while len(out) < length:
        new_offset = reader.bit()
        if new_offset:
            high = reader.gamma()
            low = reader.byte()
            offset = ((high - 1) << 7 | low >> 1) + 1
            copy(reader.gamma(low & 1) + 1)
            after_literals = False
        elif after_literals:
            copy(reader.gamma())
            after_literals = False
        else:
            out += reader.bytes(reader.gamma())
            after_literals = True
    if len(out) != length:
        raise B1Error('decoded %d bytes, expected %d' % (len(out), length))
    return bytes(out)
