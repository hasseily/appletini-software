"""Tests of tools/v816/b1.py, alone and against upstream's decoder."""

import random
import unittest

import support
from v816 import b1, hdv


class HandMadeStreams(unittest.TestCase):
    def test_match_at_new_offset(self):
        stream, plain = support.B1_ABABAB
        self.assertEqual(b1.decode(stream, len(plain)), plain)

    def test_match_at_previous_offset_then_literal(self):
        stream, plain = support.B1_AAAAZ
        self.assertEqual(b1.decode(stream, len(plain)), plain)

    def test_stops_at_length_without_reading_on(self):
        stream, plain = support.B1_AAAAZ
        self.assertEqual(b1.decode(stream[:3], 4), plain[:4])

    def test_trailing_bytes_are_ignored(self):
        stream, plain = support.B1_ABABAB
        self.assertEqual(b1.decode(stream + bytes(40), len(plain)), plain)

    def test_token_across_the_end_is_an_error(self):
        stream, _ = support.B1_ABABAB
        with self.assertRaises(b1.B1Error):
            b1.decode(stream, 5)

    def test_truncated_stream(self):
        stream, plain = support.B1_ABABAB
        for cut in range(len(stream)):
            with self.assertRaises(b1.B1Error):
                b1.decode(stream[:cut], len(plain))

    def test_offset_before_start_of_output(self):
        # literal "a", then a match at the new offset 2
        stream = bytes([0x00, 0xf0]) + b'a' + bytes([0x03])
        with self.assertRaises(b1.B1Error):
            b1.decode(stream, 3)


@support.needs_upstream
class AgainstUpstream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = support.upstream_module('b1')

    def samples(self):
        rng = random.Random(8086)
        yield b'x'
        yield bytes(1000)
        yield bytes(range(256)) * 3
        yield b'DOOM' * 200 + bytes(rng.randrange(256) for _ in range(300))
        # long offsets and long matches
        block = bytes(rng.randrange(256) for _ in range(700))
        yield block + bytes(2000) + block + block[:300]
        # few symbols: many short matches
        yield bytes(rng.choice(b'ab\0') for _ in range(3000))

    def test_decodes_what_upstream_encodes(self):
        for plain in self.samples():
            stream = self.reference.compress(plain)
            self.assertEqual(b1.decode(stream, len(plain)), plain)

    @support.needs_release
    def test_release_streams_decode_as_upstream_decodes_them(self):
        image = support.RELEASE_IMAGE.read_bytes()
        found = 0
        for segment in hdv.parse(image).segments:
            if segment.flags & hdv.SEG_B1:
                start = segment.first_block * hdv.BLOCK
                raw = image[start:start + segment.block_count * hdv.BLOCK]
                self.assertEqual(
                    self.reference.decode(raw[2:], len(segment.data)),
                    segment.data)
                found += 1
        self.assertEqual(found, 2)


if __name__ == '__main__':
    unittest.main()
