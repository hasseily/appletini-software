#!/usr/bin/env python3
"""Tests for tools/build_disk.py.

Builds an image from a dummy SYS payload into a temporary directory and
checks the ProDOS structure with the small reader below, which is written
independently of the one in build_disk.py (it shares no code with it):
directory walk, header fields, index blocks, bitmap consistency and file
read back. A second test drives the writer with a file large enough to
need tree storage.

Run:  python3 tests/test_disk.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_disk  # noqa: E402

BLOCK = 512
MASTER = build_disk.DEFAULT_MASTER


# ---------------------------------------------------------------------------
# independent minimal ProDOS reader
# ---------------------------------------------------------------------------
def blk(image, n):
    return image[n * BLOCK:(n + 1) * BLOCK]


def le16(b, o):
    return b[o] + 256 * b[o + 1]


def walk_directory(image):
    """Return (header dict, [entry dict], [directory block numbers])."""
    n = 2
    chain = []
    entries = []
    header = None
    while n:
        chain.append(n)
        b = blk(image, n)
        prev, nxt = le16(b, 0), le16(b, 2)
        if len(chain) > 1 and prev != chain[-2]:
            raise AssertionError(f"block {n} prev link {prev} != {chain[-2]}")
        if len(chain) == 1 and prev != 0:
            raise AssertionError("key block prev link is not 0")
        for i in range(13):
            e = b[4 + i * 39:4 + (i + 1) * 39]
            kind = e[0] >> 4
            if n == 2 and i == 0:
                header = {
                    "kind": kind,
                    "name": e[1:1 + (e[0] & 15)].decode(),
                    "reserved": e[16:24],
                    "creation": e[24:28],
                    "version": e[28], "min_version": e[29], "access": e[30],
                    "entry_length": e[31], "entries_per_block": e[32],
                    "file_count": le16(e, 33), "bitmap": le16(e, 35),
                    "total": le16(e, 37),
                }
                continue
            if kind == 0:
                continue
            entries.append({
                "kind": kind,
                "name": e[1:1 + (e[0] & 15)].decode(),
                "type": e[16], "key": le16(e, 17), "blocks": le16(e, 19),
                "eof": e[21] + 256 * e[22] + 65536 * e[23],
                "creation": e[24:28], "version": e[28], "min_version": e[29],
                "access": e[30], "aux": le16(e, 31), "mod": e[33:37],
                "header": le16(e, 37),
            })
        n = nxt
    return header, entries, chain


def index_pointers(image, n):
    b = blk(image, n)
    return [b[i] + 256 * b[256 + i] for i in range(256)]


def file_layout(image, entry):
    """Return (index blocks, data block pointers (0 = hole))."""
    kind, key = entry["kind"], entry["key"]
    if kind == 1:
        return [], [key]
    if kind == 2:
        return [key], index_pointers(image, key)
    if kind == 3:
        idx = [key]
        data = []
        for p in index_pointers(image, key)[:128]:
            if p:
                idx.append(p)
                data.extend(index_pointers(image, p))
            else:
                data.extend([0] * 256)
        return idx, data
    raise AssertionError(f"storage type {kind}")


def read_contents(image, entry):
    _, data = file_layout(image, entry)
    out = b""
    for p in data[:(entry["eof"] + BLOCK - 1) // BLOCK]:
        out += blk(image, p) if p else bytes(BLOCK)
    return out[:entry["eof"]]


def bitmap_free(image, bitmap_block, n):
    return bool(blk(image, bitmap_block)[n // 8] & (0x80 >> (n % 8)))


def check_volume(tc, image, expected_files, total_blocks):
    """Full structural check; expected_files: name -> (type, aux, data)."""
    header, entries, chain = walk_directory(image)
    tc.assertEqual(header["kind"], 0xF)
    tc.assertEqual(header["name"], "A13BOSCO")
    tc.assertEqual(header["entry_length"], 0x27)
    tc.assertEqual(header["entries_per_block"], 0x0D)
    tc.assertEqual(header["file_count"], len(expected_files))
    tc.assertEqual(header["bitmap"], 6)
    tc.assertEqual(header["total"], total_blocks)
    tc.assertEqual(header["access"], 0xC3)
    tc.assertEqual(header["version"], 0)
    tc.assertEqual(header["min_version"], 0)
    tc.assertEqual(header["creation"], bytes(4))
    tc.assertEqual(header["reserved"], bytes(8))
    tc.assertEqual(chain, [2, 3, 4, 5])

    used = {0, 1, 2, 3, 4, 5, 6}
    names = []
    for entry in entries:
        names.append(entry["name"])
        tc.assertIn(entry["name"], expected_files)
        ftype, aux, data = expected_files[entry["name"]]
        tc.assertEqual(entry["type"], ftype)
        tc.assertEqual(entry["aux"], aux)
        tc.assertEqual(entry["eof"], len(data))
        tc.assertEqual(entry["access"], 0xC3)
        tc.assertEqual(entry["header"], 2)
        tc.assertEqual(entry["version"], 0)
        tc.assertEqual(entry["min_version"], 0)
        tc.assertEqual(entry["creation"], bytes(4))
        tc.assertEqual(entry["mod"], bytes(4))
        data_blocks = (len(data) + BLOCK - 1) // BLOCK
        if data_blocks == 1:
            tc.assertEqual(entry["kind"], 1)
        elif data_blocks <= 256:
            tc.assertEqual(entry["kind"], 2)
        else:
            tc.assertEqual(entry["kind"], 3)
        idx, pointers = file_layout(image, entry)
        live = [p for p in pointers if p]
        tc.assertEqual(len(live), data_blocks, entry["name"])
        tc.assertEqual(entry["blocks"], len(idx) + len(live))
        for p in idx + live:
            tc.assertGreaterEqual(p, 7)
            tc.assertLess(p, total_blocks)
            tc.assertNotIn(p, used, f"block {p} referenced twice")
            used.add(p)
        # pointers past the file must be zero
        tc.assertFalse(any(pointers[data_blocks:]), "stale pointers after EOF")
        tc.assertEqual(read_contents(image, entry), data)
    tc.assertCountEqual(names, list(expected_files))

    for n in range(total_blocks):
        tc.assertEqual(bitmap_free(image, 6, n), n not in used, f"bitmap bit {n}")
    tc.assertFalse(any(blk(image, 6)[total_blocks // 8:]),
                   "bits beyond the volume must be marked used")


# ---------------------------------------------------------------------------
class TestBuildDisk(unittest.TestCase):
    @unittest.skipUnless(MASTER.is_file(), f"ProDOS master not found: {MASTER}")
    def test_build_from_dummy_sys(self):
        payload = bytes([0x78, 0xD8]) + os.urandom(20 * 1024 + 123)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.hdv"
            build_disk.build(payload, MASTER, out)
            image = out.read_bytes()
        self.assertEqual(len(image), 1600 * BLOCK)
        master = MASTER.read_bytes()
        self.assertEqual(image[:2 * BLOCK], master[:2 * BLOCK], "boot blocks")

        # PRODOS as read from the master with this test's own reader
        _, master_entries, _ = walk_directory(master)
        prodos_entry = next(e for e in master_entries if e["name"] == "PRODOS")
        prodos = read_contents(master, prodos_entry)
        self.assertGreater(len(prodos), 8192)

        check_volume(self, image, {
            "PRODOS": (0xFF, 0x0000, prodos),
            "BOSCO.SYSTEM": (0xFF, 0x2000, payload),
        }, 1600)

    @unittest.skipUnless(MASTER.is_file(), f"ProDOS master not found: {MASTER}")
    def test_build_with_sprite_file(self):
        payload = bytes([0x78, 0xD8]) + os.urandom(3000)
        sprites = b"BSPR" + bytes([1, 0x00, 0xD0, 0x00, 0x10, 0x04]) + os.urandom(0x1000)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.hdv"
            build_disk.build(payload, MASTER, out, sprites=sprites)
            image = out.read_bytes()
        master = MASTER.read_bytes()
        _, master_entries, _ = walk_directory(master)
        prodos = read_contents(master, next(e for e in master_entries if e["name"] == "PRODOS"))
        check_volume(self, image, {
            "PRODOS": (0xFF, 0x0000, prodos),
            "BOSCO.SYSTEM": (0xFF, 0x2000, payload),
            "BOSCO.SPR": (0x06, 0xD000, sprites),
        }, 1600)

    @unittest.skipUnless(MASTER.is_file(), f"ProDOS master not found: {MASTER}")
    def test_cli(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            sys_path = Path(tmp) / "dummy.sys"
            sys_path.write_bytes(bytes([0x4C, 0x03, 0x20]) + bytes(2000))
            out = Path(tmp) / "cli.hdv"
            r = subprocess.run([sys.executable, str(ROOT / "tools/build_disk.py"),
                                "--system", str(sys_path), "--output", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("BOSCO.SYSTEM", r.stdout)
            self.assertIn("1600 blocks", r.stdout)
            self.assertEqual(out.stat().st_size, 800 * 1024)

    def test_writer_storage_types(self):
        """seedling, sapling and tree files through the writer API."""
        small = b"S" * 100                       # 1 block: seedling
        medium = os.urandom(256 * BLOCK)         # 256 blocks: still sapling
        large = os.urandom(300 * BLOCK + 7)      # 301 blocks: tree
        writer = build_disk.VolumeWriter()
        writer.set_boot_blocks(bytes(1024))
        writer.add_file("SMALL", small, 0x06, 0x0800)
        writer.add_file("MEDIUM", medium, 0xFF, 0x2000)
        writer.add_file("LARGE", large, 0x06, 0x1234)
        image = writer.finish()
        check_volume(self, image, {
            "SMALL": (0x06, 0x0800, small),
            "MEDIUM": (0xFF, 0x2000, medium),
            "LARGE": (0x06, 0x1234, large),
        }, 1600)
        # the builder's own verifier must agree with this reader
        build_disk.verify_image(image, {
            "SMALL": (0x06, 0x0800, small),
            "MEDIUM": (0xFF, 0x2000, medium),
            "LARGE": (0x06, 0x1234, large),
        })

    def test_bad_names(self):
        writer = build_disk.VolumeWriter()
        with self.assertRaises(build_disk.DiskError):
            writer.add_file("1BAD", b"x", 0x06, 0)
        with self.assertRaises(build_disk.DiskError):
            writer.add_file("TOO.LONG.NAME.HERE", b"x", 0x06, 0)
        with self.assertRaises(build_disk.DiskError):
            writer.add_file("EMPTY", b"", 0x06, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
