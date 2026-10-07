"""PHS1 sparse-time, side-effect ordering and malformed-input checks."""

import random
import unittest

from phasor.stream import HEADER, RECORD, decode, encode


class StreamTests(unittest.TestCase):
    def test_long_gaps_split_into_wait_records_without_moving_writes(self):
        events = [(0, 4, 3, 128), (140_000, 4, 0, 14), (200_000, 4, 3, 128)]
        encoded = encode(events, 100, 200_000)
        decoded, info = decode(encoded)
        self.assertEqual(decoded, events)
        self.assertEqual(info["duration_ticks"], 200_000)
        self.assertEqual(info["record_count"], 5)

    def test_same_tick_register_pulses_and_duplicates_round_trip_in_order(self):
        events = [(0, 4, 3, 128), (0, 4, 0, 128), (0, 4, 3, 0),
                  (0, 4, 3, 128), (0, 4, 0, 0), (0, 4, 3, 0),
                  (10, 4, 0, 14), (10, 4, 0, 14)]
        decoded, _ = decode(encode(events, 100, 20))
        self.assertEqual(decoded, events)

    def test_silence_has_a_terminal_wait(self):
        decoded, info = decode(encode([], 100, 70_000))
        self.assertEqual(decoded, [])
        self.assertEqual(info["record_count"], 2)
        self.assertEqual(info["duration_ticks"], 70_000)

    def test_player_write_budget_is_aggregate_per_tick(self):
        events = [(0, 4, 1, value % 256) for value in range(255)]
        self.assertEqual(decode(encode(events, 100, 1))[0], events)
        with self.assertRaises(ValueError):
            encode(events + [(0, 4, 1, 0)], 100, 1)
        # Different records with zero delta still share the player's budget.
        first = RECORD.pack(0, 255) + bytes((0x41, 0)) * 255
        second = RECORD.pack(0, 1) + bytes((0x41, 0))
        terminal = RECORD.pack(1, 0)
        with self.assertRaises(ValueError):
            decode(HEADER.pack(b"PHS1", 100, 0, 1, 3) + first + second + terminal)

    def test_random_valid_streams_preserve_all_events(self):
        rng = random.Random(263)
        for _ in range(50):
            events = []
            tick = 0
            for _ in range(100):
                tick += rng.randrange(0, 100000)
                target = rng.randrange(6)
                register = rng.randrange(14 if target < 4 else 5)
                events.append((tick, target, register, rng.randrange(256)))
            self.assertEqual(decode(encode(events, 100, tick + 123))[0], events)

    def test_every_truncation_and_trailing_data_is_rejected(self):
        data = encode([(0, 4, 3, 128), (5, 4, 0, 14)], 100, 10)
        for length in range(len(data)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                decode(data[:length])
        with self.assertRaises(ValueError):
            decode(data + b"\x00")

    def test_invalid_header_fields_and_opcode_rejected(self):
        for magic, hz, flags, duration, records in (
            (b"NOPE", 100, 0, 1, 1), (b"PHS1", 0, 0, 1, 1),
            (b"PHS1", 401, 0, 1, 1), (b"PHS1", 100, 1, 1, 1),
            (b"PHS1", 100, 0, 0, 1), (b"PHS1", 100, 0, 1, 0),
        ):
            with self.subTest(header=(magic, hz, flags, duration, records)), self.assertRaises(ValueError):
                decode(HEADER.pack(magic, hz, flags, duration, records) + RECORD.pack(1, 0))
        for opcode in (0x0E, 0x45, 0x60, 0xFF):
            with self.subTest(opcode=opcode), self.assertRaises(ValueError):
                decode(HEADER.pack(b"PHS1", 100, 0, 1, 1)
                       + RECORD.pack(1, 1) + bytes((opcode, 0)))

    def test_bad_event_times_and_nonbyte_controls_rejected(self):
        invalid = [(-1, 4, 1, 0), (2, 4, 1, 0), (0, 4, 1, -1),
                   (0, 4, 1, 256), (0, 6, 1, 0), (0, 4, 5, 0),
                   (0, 4, 1, True), (False, 4, 1, 0)]
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(ValueError):
                encode([event], 100, 1)
        with self.assertRaises(ValueError):
            encode([(1, 4, 1, 0), (0, 4, 1, 0)], 100, 1)

    def test_excess_zero_delta_records_rejected(self):
        records = RECORD.pack(0, 0) * 65 + RECORD.pack(1, 0)
        with self.assertRaises(ValueError):
            decode(HEADER.pack(b"PHS1", 100, 0, 1, 66) + records)


if __name__ == "__main__":
    unittest.main()
