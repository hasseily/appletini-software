#!/usr/bin/env python3
"""Tests for tools/build_disk.py (the Doom hard-disk image).

Checks the images with the small reader below, written independently of
the one in build_disk.py (adapted from the PCS port's test): directory
walk, header fields, seedling/sapling/tree index blocks, a bitmap spread
over several blocks, block ownership and every file read back. Covers:

  - the stand-in build (make STANDIN=1) as a disk: DOOM.SYSTEM is the
    first entry (ProDOS runs the first *.SYSTEM file), PRODOS from the
    master image, the images with their load addresses as aux types, the
    data files as BIN aux $0000; the volume is sized to its contents;
  - large files (tree files over 128 KB) and large volumes (more than
    4,096 blocks: several bitmap blocks), up to the 65,535-block limit;
  - the 51-entry volume directory limit and bad names;
  - booting from the image: the files read back from the image are served
    by a2sim's fake ProDOS, DOOM.SYSTEM loads them and the kernel runs;
  - the fake ProDOS serves the directory blocks this builder writes.

Run:  python3 tests/test_disk.py
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))

import a2sim  # noqa: E402
import build_disk  # noqa: E402
import make_standin  # noqa: E402
import run_doom  # noqa: E402

BLOCK = 512
MASTER = build_disk.DEFAULT_MASTER
BUILD = ROOT / "build/standin"


def setUpModule():
    subprocess.run(["make", "-s", "STANDIN=1"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# independent minimal ProDOS reader
# ---------------------------------------------------------------------------
def blk(image, n):
    return image[n * BLOCK:(n + 1) * BLOCK]


def le16(b, o):
    return b[o] + 256 * b[o + 1]


def walk_directory(image):
    n, chain, entries, header = 2, [], [], None
    while n:
        chain.append(n)
        b = blk(image, n)
        for i in range(13):
            e = b[4 + i * 39:4 + (i + 1) * 39]
            kind = e[0] >> 4
            if n == 2 and i == 0:
                header = dict(kind=kind, name=e[1:1 + (e[0] & 15)].decode(),
                              file_count=le16(e, 33), bitmap=le16(e, 35), total=le16(e, 37),
                              entry_length=e[31], entries_per_block=e[32])
                continue
            if kind:
                entries.append(dict(kind=kind, name=e[1:1 + (e[0] & 15)].decode(), type=e[16],
                                    key=le16(e, 17), blocks=le16(e, 19),
                                    eof=e[21] + 256 * e[22] + 65536 * e[23], aux=le16(e, 31)))
        n = le16(b, 2)
    return header, entries, chain


def pointers(image, n):
    b = blk(image, n)
    return [b[i] + 256 * b[256 + i] for i in range(256)]


def layout(image, e):
    if e["kind"] == 1:
        return [], [e["key"]]
    if e["kind"] == 2:
        return [e["key"]], pointers(image, e["key"])
    idx, data = [e["key"]], []
    for p in pointers(image, e["key"])[:128]:
        if p:
            idx.append(p)
            data.extend(pointers(image, p))
    return idx, data


def contents(image, e):
    _, data = layout(image, e)
    need = (e["eof"] + BLOCK - 1) // BLOCK
    return b"".join(blk(image, p) for p in data[:need])[:e["eof"]]


def check_volume(tc, image, expected):
    """expected: [(name, type, aux, bytes)] in directory order."""
    header, entries, chain = walk_directory(image)
    total = len(image) // BLOCK
    tc.assertEqual((header["kind"], header["name"]), (0xF, "DOOM"))
    tc.assertEqual((header["entry_length"], header["entries_per_block"]), (0x27, 0x0D))
    tc.assertEqual(header["total"], total)
    tc.assertEqual(header["bitmap"], 6)
    tc.assertEqual(chain, [2, 3, 4, 5])
    tc.assertEqual([e["name"] for e in entries], [x[0] for x in expected])
    tc.assertEqual(header["file_count"], len(expected))
    nbitmap = (total + 4095) // 4096
    owner = {0: "boot", 1: "boot", 2: "dir", 3: "dir", 4: "dir", 5: "dir"}
    for i in range(nbitmap):
        owner[6 + i] = "bitmap"
    for e, (name, ftype, aux, data) in zip(entries, expected):
        tc.assertEqual((e["type"], e["aux"]), (ftype, aux), name)
        tc.assertEqual(e["kind"], 1 if len(data) <= 512 else 2 if len(data) <= 131072 else 3, name)
        idx, ptrs = layout(image, e)
        used = [p for p in ptrs[:(len(data) + 511) // 512]]
        tc.assertEqual(e["blocks"], len(idx) + len(used), name)
        for p in idx + used:
            tc.assertNotIn(p, owner, f"{name}: block {p} also {owner.get(p)}")
            owner[p] = name
        tc.assertEqual(contents(image, e), data, name)
    bitmap = b"".join(blk(image, 6 + i) for i in range(nbitmap))
    for n in range(total):
        free = bool(bitmap[n // 8] & (0x80 >> (n % 8)))
        tc.assertEqual(free, n not in owner, f"bitmap block {n}")
    return header, entries


# ---------------------------------------------------------------------------
@unittest.skipUnless(MASTER.is_file(), f"no ProDOS master at {MASTER}")
class DiskTest(unittest.TestCase):
    def build(self, data: dict, tmp: Path) -> bytes:
        images = {name: (BUILD / name).read_bytes() for name, _a in build_disk.IMAGES}
        system = (BUILD / "DOOM.SYSTEM").read_bytes()
        out = tmp / "doom.hdv"
        build_disk.build(system, images, data, MASTER, out)
        return out.read_bytes()

    def expected(self, data: dict) -> list:
        _boot, prodos = build_disk.extract_prodos(MASTER)
        out = [("DOOM.SYSTEM", 0xFF, 0x2000, (BUILD / "DOOM.SYSTEM").read_bytes()),
               ("PRODOS", 0xFF, 0x0000, prodos)]
        for name, address in build_disk.IMAGES:
            out.append((name, 0x06, address, (BUILD / name).read_bytes()))
        out += [(name, 0x06, 0x0000, blob) for name, blob in data.items()]
        return out

    def test_standin_disk(self):
        data = build_disk.data_files(BUILD / "data")
        self.assertEqual(sorted(data), ["DIR.1", "PROBE.1"])
        with tempfile.TemporaryDirectory() as tmp:
            image = self.build(data, Path(tmp))
        check_volume(self, image, self.expected(data))
        boot, _ = build_disk.extract_prodos(MASTER)
        self.assertEqual(image[:1024], boot)
        used = sum(build_disk.file_block_count(len(x[3])) for x in self.expected(data))
        self.assertLessEqual(len(image) // BLOCK, max(280, 7 + used + build_disk.FREE_BLOCKS + 1))

    def test_large_files_and_volume(self):
        # a 5 MB file (tree), a 200 KB file (tree), a 100 KB one (sapling):
        # over 4,096 blocks, so the bitmap takes several blocks
        big = bytes((i * 7 + (i >> 9)) & 255 for i in range(5 * 1024 * 1024))
        data = {"BIG.1": make_standin.data_file([(2, 0x0200, b"a" * 100)]) + big,
                "MID.1": big[:200_000], "SMALL.1": big[:100_000]}
        with tempfile.TemporaryDirectory() as tmp:
            image = self.build(data, Path(tmp))
        header, entries = check_volume(self, image, self.expected(data))
        self.assertGreater(header["total"], 2 * 4096)          # three bitmap blocks
        kinds = {e["name"]: e["kind"] for e in entries}
        self.assertEqual((kinds["BIG.1"], kinds["MID.1"], kinds["SMALL.1"]), (3, 3, 2))

    def test_limits(self):
        with self.assertRaises(build_disk.DiskError):
            build_disk.volume_size([bytes(16 * 1024 * 1024 - 1), bytes(16 * 1024 * 1024 - 1)])
        data = {f"F{i}.1": b"z" for i in range(47)}
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(build_disk.DiskError):
            self.build(data, Path(tmp))
        data = {f"F{i}.1": b"z" for i in range(46)}          # 51 entries: fits
        with tempfile.TemporaryDirectory() as tmp:
            self.build(data, Path(tmp))
        for bad in ("1ABC", "TOO.LONG.A.NAME.X", "A-B", ""):
            with self.assertRaises(build_disk.DiskError):
                build_disk.encode_name(bad)

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "d.hdv"
            result = subprocess.run([sys.executable, str(ROOT / "tools/build_disk.py"),
                                     "--build", str(BUILD), "--data", str(BUILD / "data"),
                                     "--output", str(out), "--master", str(MASTER), "--quiet"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("2 data files", result.stdout)
            self.assertTrue(out.is_file())

    def test_boot_from_image(self):
        """The files as the image holds them, served by the fake ProDOS."""
        data = build_disk.data_files(BUILD / "data")
        with tempfile.TemporaryDirectory() as tmp:
            image = self.build(data, Path(tmp))
        img = build_disk.Image(image)
        _h, entries, _c = build_disk.list_volume(img)
        prodos = a2sim.FakeProDOS(volume="DOOM", launched="DOOM.SYSTEM")
        for e in entries:
            if e["name"] != "PRODOS":
                prodos.add(e["name"], (e["file_type"], e["aux"], build_disk.read_file(img, e)))
        doom = run_doom.Doom(BUILD, fast=True)            # labels, files
        m = a2sim.Machine(run_doom.DEFAULT_ROM, speed="turbo", prodos=prodos)
        system = prodos.files["DOOM.SYSTEM"][2]
        m.load(0x2000, system)
        m.mpu.pc = 0x2000
        self.assertTrue(m.run(50_000_000, stop_pc=doom.label("kernel_start")))
        m.run(5 * m.frame_cycles)
        kframes = doom.label("kframes")
        self.assertGreater(m.lc[False][kframes - 0xC000], 0)
        self.assertTrue(m.pal256_active())

    def test_fake_prodos_directory(self):
        files = {"DOOM.SYSTEM": (0xFF, 0x2000, b"\xD8" * 600), "X.1": (0x06, 0, b"x" * 70000)}
        fake = a2sim.FakeProDOS(files)
        blocks = fake.directory_blocks()
        writer = build_disk.VolumeWriter("DOOM", build_disk.volume_size([f[2] for f in files.values()]))
        for name, (t, a, d) in files.items():
            writer.add_file(name, d, t, a)
        image = writer.finish()
        self.assertEqual(blocks, image[2 * BLOCK:6 * BLOCK])


if __name__ == "__main__":
    unittest.main()
