"""Original DOS .PB database decoding and conversion to PCS1 records."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'tools'))

import make_tables as mt  # noqa: E402
import parts  # noqa: E402
import pb2pcs  # noqa: E402


def original_library(kind: int, frame: int, x: int = 91, y: int = 47,
                     *, state: bytes = b'\x23\x42', fill: int = 0x10) -> bytes:
    pointer = next(p for p, kf in pb2pcs.original_sprite_frames().items()
                   if kf == (kind, frame))
    xs, ys = (x, x + 4, x + 4, x), (y, y, y + 4, y + 4)
    lrec = bytearray(16)
    lrec[0:2] = pointer.to_bytes(2, 'little')
    lrec[2] = y
    lrec[3], lrec[4] = divmod(x, 7)
    lrec[5:10] = bytes((7, 3, 12, 0x3F, 0x55))
    lrec[10:16] = b'\x11\x22\x33\x44\x55\x66'
    return bytes((3, fill, 4, *xs, *ys)) + bytes(lrec) + state


def original_pb(records: list[bytes], *, artwork: bytes = b'\x01\x01',
                header: bool = True) -> bytes:
    logic = bytes(range(24))
    wset = bytes((4, 5, 6, 7))
    db = logic + wset + bytes((len(records), *map(len, records))) + b''.join(records)
    payload = db + artwork
    return b'\x00\x40' + len(payload).to_bytes(2, 'little') + payload if header else payload


class TestPBConversion(unittest.TestCase):
    def test_all_original_frames_have_unique_sprite_pointer(self):
        mappings = pb2pcs.original_sprite_frames()
        expected = sum(parts.FRAMES.values())
        self.assertEqual(len(mappings), expected)
        self.assertEqual(set(mappings.values()), {
            (parts.KIT_ORDER.index(name), frame)
            for name, frames in parts.FRAMES.items() for frame in range(frames)
        })
        # FXLEN is variable. A small flipper's frame 6 is after these
        # original frame lengths, rather than 6 times its starting stride.
        symbols = pb2pcs.bitmap_symbols(parts.read_source(pb2pcs.UPSTREAM, 'RUN.S'))
        small_frame_6 = symbols['LFLIP2B'] + sum((0x10, 0x0C, 0x0C, 0x0C, 0x0A, 0x08))
        self.assertEqual(mappings[small_frame_6], (parts.KIT_ORDER.index('LFLIPPER2'), 6))

    def test_header_split_excludes_artwork_and_padding(self):
        polygon = bytes((2, 6, 4, 2, 2, 100, 100, 2, 98, 98, 2))
        library = original_library(parts.KIT_ORDER.index('ROLL2'), 1)
        raw = original_pb([polygon, library], artwork=b'\x01\x00\x01\x01')
        table = pb2pcs.parse_pb(raw + bytes(256))
        self.assertEqual(table.address, 0x4000)
        self.assertEqual(table.length, len(raw) - 4)
        self.assertEqual(table.records, (polygon, library))
        self.assertEqual(table.artwork, b'\x01\x00\x01\x01')
        self.assertEqual(pb2pcs.parse_pb(raw[4:], header=False).database, table.database)

    def test_library_state_wiring_and_settings_survive(self):
        polygon = bytes((2, 6, 4, 2, 2, 100, 100, 2, 98, 98, 2))
        library = original_library(parts.KIT_ORDER.index('ROLL2'), 1)
        source = pb2pcs.parse_pb(original_pb([polygon, library])).database
        converted = pb2pcs.convert_database(source)
        self.assertEqual(converted[:28], source[:28])  # LOGIC and WSET
        self.assertEqual(converted[28:31], source[28:31])  # count and sizes
        self.assertEqual(converted[31:31 + len(polygon)], bytes((2, 4)) + polygon[2:])
        new_lib = converted[31 + len(polygon):]
        self.assertEqual(new_lib[:11], library[:11])
        self.assertEqual(new_lib[11:27], bytes((parts.KIT_ORDER.index('ROLL2'), 1,
                                                 47, 91, 0, 0, 0, 0, 0x3F, 0x55,
                                                 0, 0, 0, 0, 0, 0)))
        self.assertEqual(new_lib[27:], b'\x23\x42')

    def test_hgr_even_colour_codes(self):
        self.assertEqual([pb2pcs.port_colour(c) for c in range(0, 16, 2)],
                         [0, 10, 14, 4, 0, 7, 12, 4])
        self.assertEqual(pb2pcs.port_colour(0x10), 0x10)
        with self.assertRaises(ValueError):
            pb2pcs.port_colour(5)

    def test_upstream_polygon_template_uses_same_colour_conversion(self):
        with tempfile.TemporaryDirectory(prefix='pcs_pb_kinds_') as temp:
            patches = Path(temp) / 'patches.json'
            subprocess.run([
                sys.executable, str(PROJECT / 'tools' / 'kinds.py'),
                str(PROJECT / 'upstream'), '--parts', str(PROJECT / 'build' / 'parts.json'),
                '--assets', str(PROJECT / 'build' / 'assets.inc'),
                '--patches', str(patches), '--out', str(Path(temp) / 'kinds.s'),
            ], check=True, capture_output=True)
            generated = json.loads(patches.read_text())
            poly1 = next(p for p in generated if p['module'] == 'RUN'
                         and p['expect'].startswith('POLY1 HEX'))
            self.assertTrue(poly1['expect'].startswith('POLY1 HEX 010604'))
            self.assertTrue(poly1['replace'].startswith('POLY1 HEX 010404'))

    def test_full_pcs_file_with_zero_hgr_page(self):
        polygon = bytes((2, 6, 4, 2, 2, 100, 100, 2, 98, 98, 2))
        # The original COMPRESS emits 32 1/256 zero-page records for an
        # empty 8192-byte HGR page, followed by its 1/1 end marker.
        original_art = b'\x01\x00' * 32 + b'\x01\x01'
        pcs = pb2pcs.convert_pb(original_pb([polygon], artwork=original_art))
        db, overlay = mt.split_pcs_file(pcs)
        self.assertEqual(db[29], len(polygon))
        self.assertEqual(db[31], 4)  # original white -> port white
        tiles, decoded = mt.decode_overlay(overlay)
        self.assertFalse(any(tiles))
        self.assertEqual(decoded, {})

    def test_make_tables_converts_every_pb_in_directory(self):
        polygon = bytes((2, 6, 4, 2, 2, 100, 100, 2, 98, 98, 2))
        original_art = b'\x01\x00' * 32 + b'\x01\x01'
        with tempfile.TemporaryDirectory(prefix='pcs_pb_build_') as temp:
            base = Path(temp)
            source = base / 'original_pb'
            source.mkdir()
            for name in ('DEMO1', 'DEMO2'):
                (source / (name + '.PB')).write_bytes(original_pb(
                    [polygon], artwork=original_art))
            out = base / 'tables'
            out.mkdir()
            (out / 'STALE.PCS').write_bytes(b'old generated table')
            subprocess.run([
                sys.executable, str(PROJECT / 'tools' / 'make_tables.py'),
                '--parts', str(PROJECT / 'build' / 'parts.json'),
                '--out', str(out), '--pb-dir', str(source),
            ], check=True, capture_output=True)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ['DEMO1.PCS', 'DEMO2.PCS', 'TABLE1.PCS'])
            for name in ('DEMO1', 'DEMO2'):
                db, overlay = mt.split_pcs_file((out / (name + '.PCS')).read_bytes())
                self.assertEqual(db[31], 4)
                self.assertEqual(overlay[:4], b'OVL1')
            (source / 'DEMO2.PB').unlink()
            subprocess.run([
                sys.executable, str(PROJECT / 'tools' / 'make_tables.py'),
                '--parts', str(PROJECT / 'build' / 'parts.json'),
                '--out', str(out), '--pb-dir', str(source),
            ], check=True, capture_output=True)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ['DEMO1.PCS', 'TABLE1.PCS'])

    def test_corrupt_records_and_unknown_pointer_rejected(self):
        bad = original_pb([b'\x03\x10\x04' + bytes(9)])
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            pb2pcs.parse_pb(bad)
        good = original_library(parts.KIT_ORDER.index('BALL'), 0)
        bad_pointer = bytearray(good)
        bad_pointer[11:13] = b'\xFF\x7F'
        db = pb2pcs.parse_pb(original_pb([bytes(bad_pointer)])).database
        with self.assertRaisesRegex(ValueError, 'unknown bitmap pointer'):
            pb2pcs.convert_database(db)
        with self.assertRaisesRegex(ValueError, 'length exceeds'):
            pb2pcs.parse_pb(b'\x00\x40\xFF\x7F' + bytes(10))


if __name__ == '__main__':
    unittest.main()
