#!/usr/bin/env python3
"""Tests of the table file format and of the disk menu (src/files.s).

The format tests use the Python reference encoder/decoder of
tools/make_tables.py (the RLE, the overlay chunk, the file split). The
simulator tests boot build/PCS.SYSTEM in tools/a2sim.py's machine with
the fake ProDOS (tools/run_editor.py's Runner with a FakeProDOS instead
of a directory), click through the title into the editor, open the disk
tool and drive the menu with the mouse and the keyboard:

  * the catalog lists the volume's *.PCS files (BIN) and nothing else;
  * a click selects an entry, LOAD loads it (the database bytes are the
    file's, the overlay tiles land in RamWorks bank 1, the menu returns
    to the editor);
  * SAVE with a typed name writes a file the reference decoder reads back
    to the current database and overlay (round trip: the overlay poked
    into bank 1 survives a save and a load);
  * a file that is not a table, or a truncated one, reports an error and
    leaves the current table alone;
  * PLAY GAME asks for the number of players, the game starts, Space
    launches the ball, Z moves the left flipper, Esc returns to the menu;
  * QUIT needs a second QUIT and calls the MLI's QUIT;
  * the title screen waits for a click or a key;
  * without ProDOS the menu says so and EDIT still returns to the editor.

Needs a build (make) and the enhanced //e ROM (APPLETINI_ROOT or the
default next to this tree). Run:  python3 tests/test_files.py
"""

import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))

import a2sim  # noqa: E402
import make_tables as mt  # noqa: E402
import run_editor  # noqa: E402

BUILD = ROOT / "build"
SYSTEM = BUILD / "PCS.SYSTEM"
TABLE1 = BUILD / "tables" / "TABLE1.PCS"
ROM = run_editor.DEFAULT_ROM
HAVE_BUILD = SYSTEM.is_file() and TABLE1.is_file() and Path(ROM).is_file()

# the panel layout of src/files.s (screen pixels)
DISK_TOOL = (305, 76)           # EDIT's DISKB box
LOAD_ITEM, SAVE_ITEM, EDIT_ITEM, QUIT_ITEM = (172, 68), (210, 68), (252, 68), (300, 68)
PLAY_ITEM = (172, 78)
CAT_Y0, CAT_PITCH = 90, 9
PLAYER_BOX = (174 + 30 * 1, 193)   # the "2" box of the player prompt
ST_EDIT, ST_DISK, ST_PLAY, ST_TITLE = 1, 4, 5, 7
ERR_FORMAT, ERR_NOMLI = 0xF0, 0xF2
KEY_RETURN, KEY_ESC, KEY_SPACE = 13, 27, 32
MAILBOX = 0x0300
def _pbbase():
    """PBBASE from the linked labels (src/pcs.cfg places the database)."""
    try:
        for line in (BUILD / "PCS.lbl").read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2] == ".PBBASE":
                return int(parts[1], 16)
    except OSError:
        pass
    return 0xA000


PBBASE = _pbbase()
PLAYERCNT_ZP = 0x28             # RUN2's PLAYERCNT (src/pcs.inc)
OVERLAY_BANK, OVERLAY_ROW = 1, 160


def canon_db(image):
    """A database image with the L-record bytes the loader rewrites (5-7,
    10-15) zeroed, so a saved table compares with make_tables' file."""
    out = bytearray(image)
    count = out[28]
    sizes = out[29:29 + count]
    offset = 29 + count
    for size in sizes:
        if out[offset] == 3:                        # a library object
            lrec = offset + 3 + 2 * out[offset + 2]
            for k in (5, 6, 7, 10, 11, 12, 13, 14, 15):
                out[lrec + k] = 0
        offset += size
    return bytes(out)


def sample_pixels():
    """An overlay with a few edited tiles: a diagonal in tile (0, 0), a
    solid tile (5, 7), two pixels at the table's right edge (tile 19)."""
    pixels = [[0] * 154 for _ in range(192)]
    for k in range(8):
        pixels[k][k] = 4                            # tile (0, 0)
    for y in range(40, 48):
        for x in range(56, 64):
            pixels[y][x] = 6                        # tile (5, 7), one value
    pixels[100][152] = 8                            # tile (12, 19)
    pixels[101][153] = 12
    return pixels


# ---------------------------------------------------------------------------
class TestFormat(unittest.TestCase):
    def test_rle_round_trip(self):
        for data in (b"", b"\x01", b"\x07" * 5, bytes(range(200)),
                     b"\x00" * 300 + b"\x11\x22\x33" + b"\x44" * 130,
                     os.urandom(1000), b"ab" * 100 + b"c" * 3 + b"ab"):
            encoded = mt.rle_encode(data)
            self.assertEqual(encoded[-1], 0)
            decoded, end = mt.rle_decode(encoded)
            self.assertEqual(decoded, data)
            self.assertEqual(end, len(encoded))
        # runs of three or more are coded as repeats, shorter ones as literals
        self.assertEqual(mt.rle_encode(b"\x09" * 4), b"\x84\x09\x00")
        self.assertEqual(mt.rle_encode(b"\x09\x09"), b"\x02\x09\x09\x00")
        self.assertEqual(mt.rle_encode(b"\x05" * 200), bytes([0x80 | 127, 5, 0x80 | 73, 5, 0]))

    def test_overlay_chunk(self):
        chunk = mt.overlay_chunk(None)
        self.assertEqual(chunk, b"OVL1" + bytes(72) + b"\x00")
        tiles, decoded = mt.decode_overlay(chunk)
        self.assertEqual((tiles, decoded), (bytes(72), {}))
        pixels = sample_pixels()
        chunk = mt.overlay_chunk(pixels)
        tiles, decoded = mt.decode_overlay(chunk)
        self.assertEqual(sorted(decoded), [(0, 0), (5, 7), (12, 19)])
        self.assertEqual(tiles[0], 1)                        # row 0, col 0
        self.assertEqual(tiles[3 * 5], 1 << 7)               # row 5, col 7
        self.assertEqual(tiles[3 * 12 + 2], 1 << 3)          # row 12, col 19
        self.assertEqual(decoded[(0, 0)][0], 0x40)            # pixel (0,0) = 4
        self.assertEqual(decoded[(0, 0)][4], 0x04)            # pixel (1,1) = 4
        self.assertEqual(decoded[(5, 7)], b"\x66" * 32)
        self.assertEqual(decoded[(12, 19)][16:20], b"\x80\x00\x00\x00")   # (100, 152)
        self.assertEqual(decoded[(12, 19)][20:24], b"\x0C\x00\x00\x00")   # (101, 153)
        for tile in decoded.values():
            self.assertEqual(len(tile), 32)

    def test_decode_rejects_bad_chunks(self):
        with self.assertRaises(ValueError):
            mt.decode_overlay(b"OVL2" + bytes(72) + b"\x00")
        with self.assertRaises(ValueError):                  # a tile set, no data
            mt.decode_overlay(b"OVL1" + b"\x01" + bytes(71) + b"\x00")
        with self.assertRaises(ValueError):                  # data, no tile
            mt.decode_overlay(b"OVL1" + bytes(72) + mt.rle_encode(bytes(32)))

    def test_pcs_file_split(self):
        db = bytes(range(24)) + bytes([4, 4, 3, 4]) + bytes([2, 11, 11]) + bytes(22)
        data = mt.pcs_file(db, sample_pixels())
        image, chunk = mt.split_pcs_file(data)
        self.assertEqual(image, db)
        self.assertEqual(chunk, mt.overlay_chunk(sample_pixels()))
        with self.assertRaises(ValueError):
            mt.split_pcs_file(b"PCS2" + db)

    @unittest.skipUnless(TABLE1.is_file(), "no build/tables/TABLE1.PCS")
    def test_seed_table_file(self):
        data = TABLE1.read_bytes()
        image, chunk = mt.split_pcs_file(data)
        self.assertEqual(image[28], 24)                      # objects
        self.assertEqual(mt.decode_overlay(chunk), (bytes(72), {}))
        self.assertEqual(len(data), 4 + len(image) + 4 + 72 + 1)


# ---------------------------------------------------------------------------
class Sim:
    """The port booted with a fake ProDOS, driven a frame at a time."""

    def __init__(self, files=None, prodos=True):
        class Args:
            pass
        args = Args()
        args.rom, args.speed, args.frames, args.out = ROM, 33, 0, str(BUILD / "run_test")
        args.do, args.shot, args.quiet, args.trace, args.trace_limit = [], [], True, [], 0
        args.prodos = a2sim.FakeProDOS(files or {}) if prodos else None
        self.r = run_editor.Runner(args)
        self.r.work_start = self.r.mpu.processorCycles
        self.m = self.r.machine
        self.mpu = self.m.mpu
        self.mem = self.m.main
        self.L = self.r.labels
        self.prodos = self.m.prodos
        self.left = False

    # -- running -----------------------------------------------------------
    def frames(self, n):
        """Run n frames; False once the program left (QUIT or a crash)."""
        r, mpu, m = self.r, self.mpu, self.m
        target = r.frames + n
        limit = 4_000_000 * m.speed
        while r.frames < target:
            mpu.step()
            if mpu.pc == r.wait:
                r.frame_done()
                r.frames += 1
                mpu.processorCycles = (mpu.processorCycles // m.frame_cycles + 1) * m.frame_cycles
                mpu.pc = r.wait_rts
                r.work_start = mpu.processorCycles
                continue
            if (mpu.pc < 0x0C00 and not 0x0110 <= mpu.pc < 0x0180) or 0xBF00 <= mpu.pc < 0xC000:
                self.left = True
                return False
            if mpu.processorCycles - r.work_start > limit:
                raise AssertionError("no frame end after %d cycles at $%04X (%s)"
                                     % (limit, mpu.pc, r.nearest(mpu.pc)))
        return True

    def click(self, x, y, held=3, settle=4):
        self.m.mouse_move(x, y)
        self.frames(1)
        self.m.mouse_buttons(True, False)
        self.frames(held)
        self.m.mouse_buttons(False, False)
        self.frames(settle)

    def key(self, code, settle=2):
        self.m.press(chr(code & 0x7F), at_cycle=self.mpu.processorCycles)
        self.frames(settle)

    def type_text(self, text):
        for char in text:
            self.key(ord(char))

    # -- state -------------------------------------------------------------
    def state(self):
        return self.mem[MAILBOX + 4]

    def var(self, name, width=1):
        a = self.L[name]
        return self.mem[a] if width == 1 else self.mem[a] | (self.mem[a + 1] << 8)

    def pixel(self, x, y):
        value = self.m.aux_banks[0][0x2000 + 160 * y + x // 2]
        return value >> 4 if x % 2 == 0 else value & 15

    def db_image(self):
        """The database in memory (LOGIC, WSET, PBDATA), L-records with
        their sprite pointers."""
        count = self.mem[PBBASE + 28]
        sizes = self.mem[PBBASE + 29:PBBASE + 29 + count]
        end = PBBASE + 29 + count + sum(sizes)
        return bytes(self.mem[PBBASE:end])

    def kind_of(self, ptr):
        """(kind, frame) of a sprite directory pointer, as table_denorm."""
        sid = (ptr - self.L["spr_dir"]) // 4
        spr0, frames = self.L["kind_spr0"], self.L["kind_frames"]
        for kind in range(43):
            n = self.mem[frames + kind]
            if n and 0 <= sid - self.mem[spr0 + kind] < n:
                return kind, sid - self.mem[spr0 + kind]
        return 0, 0

    def db_file_image(self):
        """The database as a table file would hold it: (kind, frame) in
        the L-records, the template bytes zeroed (canon_db)."""
        out = bytearray(self.db_image())
        count = out[28]
        offset = 29 + count
        for size in out[29:29 + count]:
            if out[offset] == 3:
                lrec = offset + 3 + 2 * out[offset + 2]
                out[lrec], out[lrec + 1] = self.kind_of(out[lrec] | (out[lrec + 1] << 8))
            offset += size
        return canon_db(out)

    def catalog(self):
        names = self.L["fm_names"]
        out = []
        for i in range(self.var("fm_count")):
            rec = self.mem[names + 16 * i:names + 16 * i + 16]
            out.append(bytes(rec[1:1 + rec[0]]).decode("ascii"))
        return out

    def ov_tiles(self):
        a = self.L["ov_tiles"]
        return bytes(self.mem[a:a + 72])

    def bank1_tile(self, row, col):
        bank = self.m.aux_banks.setdefault(OVERLAY_BANK, bytearray(0x10000))
        out = bytearray()
        for y in range(8 * row, 8 * row + 8):
            base = 0x2000 + OVERLAY_ROW * y + 4 * col
            out += bank[base:base + 4]
        return bytes(out)

    def poke_overlay(self, pixels):
        """The overlay pixels into bank 1 and the tile map, as the
        magnifier would leave them."""
        bank = self.m.aux_banks.setdefault(OVERLAY_BANK, bytearray(0x10000))
        tiles = bytearray(72)
        for row in range(24):
            for col in range(20):
                tile = mt.tile_bytes(pixels, row, col)
                if any(tile):
                    tiles[3 * row + col // 8] |= 1 << (col % 8)
                for k in range(8):
                    base = 0x2000 + OVERLAY_ROW * (8 * row + k) + 4 * col
                    bank[base:base + 4] = tile[4 * k:4 * k + 4]
        a = self.L["ov_tiles"]
        self.mem[a:a + 72] = tiles
        self.mem[self.L["ov_enabled"]] = 1 if any(tiles) else 0
        return bytes(tiles)

    def l_record(self, kind):
        """(address, bytes) of the first library object of a kind: the
        kind is recovered from the sprite pointer as table_denorm does."""
        spr_dir = self.L["spr_dir"]
        spr0, frames = self.L["kind_spr0"], self.L["kind_frames"]
        count = self.mem[PBBASE + 28]
        sizes = self.mem[PBBASE + 29:PBBASE + 29 + count]
        offset = PBBASE + 29 + count
        for size in sizes:
            if self.mem[offset] == 3:
                lrec = offset + 3 + 2 * self.mem[offset + 2]
                ptr = self.mem[lrec] | (self.mem[lrec + 1] << 8)
                sid = (ptr - spr_dir) // 4
                if self.mem[frames + kind] and 0 <= sid - self.mem[spr0 + kind] < self.mem[frames + kind]:
                    return lrec, bytes(self.mem[lrec:lrec + 20])
            offset += size
        raise AssertionError("no object of kind %d" % kind)

    # -- the flows -----------------------------------------------------------
    def boot_to_editor(self):
        self.frames(3)
        assert self.state() == ST_TITLE, self.state()
        self.key(ord("A"), settle=6)
        assert self.state() == ST_EDIT, self.state()

    def open_menu(self):
        self.click(*DISK_TOOL, settle=6)
        assert self.state() == ST_DISK, self.state()

    def entry_pos(self, index):
        return (200, CAT_Y0 + CAT_PITCH * index + 3)


def table_files(**extra):
    files = {"TABLE1.PCS": TABLE1.read_bytes()}
    files.update(extra)
    return files


@unittest.skipUnless(HAVE_BUILD, "needs build/PCS.SYSTEM, build/tables and the ROM")
class TestDiskMenu(unittest.TestCase):
    def test_cursor_is_visible_in_the_disk_menu(self):
        sim = Sim(table_files())
        sim.boot_to_editor()
        self.assertEqual((sim.var("cur_want"), sim.var("cur_vis")), (0x80, 0x80))
        sim.open_menu()
        self.assertEqual((sim.var("cur_want"), sim.var("cur_vis")), (0x80, 0x80))
        sim.frames(3)
        self.assertEqual((sim.var("cur_want"), sim.var("cur_vis")), (0x80, 0x80))

    def test_catalog_select_load_save(self):
        # a second table: TABLE1 with its speed changed and an overlay
        image, _ = mt.split_pcs_file(TABLE1.read_bytes())
        image2 = bytearray(image)
        image2[25] = 6                                  # WSET+1: the speed
        pixels = sample_pixels()
        sim = Sim(table_files(**{
            "SECOND.PCS": mt.pcs_file(bytes(image2), pixels),
            "NOTES.TXT": (0x04, 0, b"a text file"),
            "OTHER.BIN": (0x06, 0x2000, b"\x00" * 10),
            "PICTURE.PIC": (0x06, 0, b"\x00" * 10),
        }))
        sim.boot_to_editor()
        self.assertEqual(sim.db_file_image(), image)    # the built-in table
        sim.open_menu()
        self.assertEqual(sim.var("fm_err"), 0)
        self.assertEqual(sim.catalog(), ["TABLE1.PCS", "SECOND.PCS"])
        # nothing selected: LOAD complains and stays
        sim.click(*LOAD_ITEM)
        self.assertEqual(sim.state(), ST_DISK)
        self.assertEqual(sim.var("fm_sel"), 0xFF)
        # select SECOND, load it
        sim.click(*sim.entry_pos(1))
        self.assertEqual(sim.var("fm_sel"), 1)
        sim.click(*LOAD_ITEM, settle=8)
        self.assertEqual(sim.var("fm_err"), 0)
        self.assertEqual(sim.state(), ST_EDIT)
        self.assertEqual(sim.db_file_image(), bytes(image2))
        self.assertEqual(sim.mem[PBBASE + 25], 6)
        # the overlay: the tile map and bank 1
        tiles, decoded = mt.decode_overlay(mt.overlay_chunk(pixels))
        self.assertEqual(sim.ov_tiles(), tiles)
        self.assertEqual(sim.var("ov_enabled"), 1)
        for (row, col), tile in decoded.items():
            self.assertEqual(sim.bank1_tile(row, col), tile, (row, col))
        self.assertEqual(sim.bank1_tile(1, 1), bytes(32))       # an unset tile
        # the L-records are resolved: the ball's sprite pointer is the directory's
        _, ball = sim.l_record(4)
        self.assertEqual(ball[5:8], bytes([5, 5, 4]))           # h, w, stride
        # save it under a new name: the file reads back to the same table
        sim.open_menu()
        self.assertEqual(sim.catalog(), ["TABLE1.PCS", "SECOND.PCS"])
        sim.click(*SAVE_ITEM)
        self.assertEqual(sim.state(), ST_DISK)
        sim.type_text("my.copy2")                                # lower case, a period
        self.assertEqual(sim.var("fm_name"), 8)
        sim.key(0x08)                                            # left arrow: delete
        sim.type_text("3")
        sim.key(KEY_RETURN, settle=8)
        self.assertEqual(sim.var("fm_err"), 0)
        self.assertIn("MY.COPY3.PCS", sim.prodos.files)
        saved = bytes(sim.prodos.files["MY.COPY3.PCS"][2])
        simage, schunk = mt.split_pcs_file(saved)
        self.assertEqual(canon_db(simage), bytes(image2))
        self.assertEqual(mt.decode_overlay(schunk), (tiles, decoded))
        self.assertEqual(sim.prodos.files["MY.COPY3.PCS"][:2], [0x06, 0])
        self.assertEqual(sim.catalog(), ["TABLE1.PCS", "SECOND.PCS", "MY.COPY3.PCS"])
        # the table in memory is untouched by the save
        self.assertEqual(sim.db_file_image(), bytes(image2))
        # overwrite it, then the second click on a selected entry loads
        sim.click(*sim.entry_pos(2))
        sim.click(*SAVE_ITEM)
        sim.key(KEY_RETURN, settle=8)                            # the default name
        self.assertEqual(sim.var("fm_err"), 0)
        self.assertEqual(bytes(sim.prodos.files["MY.COPY3.PCS"][2]), saved)
        sim.click(*sim.entry_pos(0))
        sim.click(*sim.entry_pos(0), settle=8)
        self.assertEqual(sim.state(), ST_EDIT)
        self.assertEqual(sim.db_file_image(), image)
        self.assertEqual(sim.var("ov_enabled"), 0)
        self.assertEqual(sim.bank1_tile(5, 7), bytes(32))        # cleared

    def test_catalog_pages_mouse_and_keys_reach_entries_after_11(self):
        original, _ = mt.split_pcs_file(TABLE1.read_bytes())
        special = bytearray(original)
        special[25] = 6                 # a loaded final entry is observable
        files = {}
        for index in range(25):
            db = bytes(special) if index == 24 else original
            files[f"T{index:02d}.PCS"] = mt.pcs_file(db)
        sim = Sim(files)
        sim.boot_to_editor()
        sim.open_menu()
        self.assertEqual(sim.var("fm_count"), 25)
        self.assertEqual(sim.catalog(), [f"T{i:02d}.PCS" for i in range(25)])
        self.assertEqual(sim.var("fm_page"), 0)
        # NEXT is clickable beside the first catalog row. The selected
        # absolute index, not its on-screen row, is retained for LOAD.
        sim.click(304, CAT_Y0 + 3)
        self.assertEqual(sim.var("fm_page"), 11)
        sim.click(*sim.entry_pos(0))
        self.assertEqual(sim.var("fm_sel"), 11)
        sim.key(ord("N"))
        self.assertEqual(sim.var("fm_page"), 22)
        self.assertEqual(sim.var("fm_sel"), 0xFF)
        sim.click(*sim.entry_pos(2))
        self.assertEqual(sim.var("fm_sel"), 24)
        sim.click(*LOAD_ITEM, settle=8)
        self.assertEqual(sim.state(), ST_EDIT)
        self.assertEqual(sim.mem[PBBASE + 25], 6)
        sim.open_menu()
        self.assertEqual(sim.var("fm_page"), 0)
        sim.key(ord("n"))             # lower-case shortcuts also work
        self.assertEqual(sim.var("fm_page"), 11)
        sim.click(270, CAT_Y0 + 3)     # PREV is clickable
        self.assertEqual(sim.var("fm_page"), 0)
        sim.key(ord("B"))              # no wrap before page one
        self.assertEqual(sim.var("fm_page"), 0)

    @unittest.skipUnless((ROOT / "assets" / "original_pb").is_dir(),
                         "original .PB tables are not staged")
    def test_every_converted_original_table_loads_from_paged_catalog(self):
        paths = sorted((BUILD / "tables").glob("*.PCS"))
        files = {path.name: path.read_bytes() for path in paths}
        expected = sorted(["TABLE1.PCS"] + [p.stem + ".PCS" for p in
                                           (ROOT / "assets" / "original_pb").glob("*.PB")])
        self.assertEqual(list(files), expected)
        sim = Sim(files)
        sim.boot_to_editor()
        for index, name in enumerate(expected):
            sim.open_menu()
            self.assertEqual(sim.catalog(), expected)
            if index >= 11:
                sim.key(ord("N"))
                self.assertEqual(sim.var("fm_page"), 11)
            sim.click(*sim.entry_pos(index % 11))
            self.assertEqual(sim.var("fm_sel"), index)
            sim.click(*LOAD_ITEM, settle=8)
            self.assertEqual(sim.state(), ST_EDIT, name)
            db, overlay = mt.split_pcs_file(files[name])
            self.assertEqual(sim.db_file_image(), db, name)
            tiles, artwork = mt.decode_overlay(overlay)
            self.assertEqual(sim.ov_tiles(), tiles, name)
            for (row, col), tile in artwork.items():
                self.assertEqual(sim.bank1_tile(row, col), tile,
                                 f"{name} artwork tile ({row}, {col})")
            sim.open_menu()
            sim.click(*PLAY_ITEM, settle=2)
            self.assertEqual(sim.state(), ST_PLAY, name)
            sim.frames(66)               # the original shell's title delay
            sim.key(ord("1"), settle=6) # the user's number-key start path
            self.assertEqual(sim.state(), ST_PLAY, name)
            sim.frames(6)
            ball_addr, ball = sim.l_record(4)
            x, y = ball[17], ball[18]
            self.assertIn(4, (sim.pixel(x + dx, y + dy)
                              for dy in range(5) for dx in range(5)), name)
            sim.key(KEY_ESC, settle=6)
            self.assertEqual(sim.state(), ST_DISK, name)
            sim.key(ord("E"), settle=6)
            self.assertEqual(sim.state(), ST_EDIT, name)

    def test_overlay_round_trip_from_memory(self):
        """An overlay poked into bank 1 (as the magnifier leaves it) is
        saved with the program's encoder and read back by the reference
        decoder, then loaded again."""
        pixels = sample_pixels()
        sim = Sim(table_files())
        sim.boot_to_editor()
        tiles = sim.poke_overlay(pixels)
        sim.open_menu()
        sim.click(*SAVE_ITEM)
        sim.type_text("OV")
        sim.key(KEY_RETURN, settle=8)
        self.assertEqual(sim.var("fm_err"), 0)
        saved = bytes(sim.prodos.files["OV.PCS"][2])
        image, chunk = mt.split_pcs_file(saved)
        expected_tiles, expected = mt.decode_overlay(mt.overlay_chunk(pixels))
        self.assertEqual(mt.decode_overlay(chunk), (expected_tiles, expected))
        self.assertEqual(tiles, expected_tiles)
        # the program codes a one-value tile as a run, the others as literals
        stream, _ = mt.rle_decode(chunk, 4 + 72)
        self.assertEqual(len(stream), 32 * 3)
        self.assertIn(bytes([0x80 | 32, 0x66]), chunk)
        # forget the overlay, load the file: it is back
        sim.poke_overlay([[0] * 154 for _ in range(192)])
        self.assertEqual(sim.var("ov_enabled"), 0)
        sim.click(*sim.entry_pos(1))                              # OV.PCS
        sim.click(*LOAD_ITEM, settle=8)
        self.assertEqual(sim.state(), ST_EDIT)
        self.assertEqual(sim.ov_tiles(), expected_tiles)
        self.assertEqual(sim.var("ov_enabled"), 1)
        for (row, col), tile in expected.items():
            self.assertEqual(sim.bank1_tile(row, col), tile, (row, col))

    def test_corrupt_files_keep_the_table(self):
        good = TABLE1.read_bytes()
        good_image, _ = mt.split_pcs_file(good)
        last_size = 29 + good_image[28] - 1
        last_record = last_size + 1 + sum(good_image[29:last_size])
        tiny_record = bytearray(good_image[:last_record + 1])
        tiny_record[last_size] = 1                  # the last library object is one byte
        sim = Sim(table_files(**{
            "BAD.PCS": b"\x00" * 300,                           # not a table
            "SHORT.PCS": good[:120],                            # cut inside the records
            "NOMAP.PCS": good[:len(good) - 40],                 # cut inside the overlay map
            "TINY.PCS": mt.pcs_file(bytes(tiny_record)),       # complete file, invalid record
        }))
        sim.boot_to_editor()
        before = sim.db_image()
        sim.open_menu()
        self.assertEqual(sim.catalog(), ["TABLE1.PCS", "BAD.PCS", "SHORT.PCS", "NOMAP.PCS", "TINY.PCS"])
        for index in (1, 2, 3, 4):
            sim.click(*sim.entry_pos(index))
            sim.click(*LOAD_ITEM, settle=8)
            self.assertEqual(sim.state(), ST_DISK, index)
            self.assertEqual(sim.var("fm_err"), ERR_FORMAT, index)
            self.assertEqual(sim.db_image(), before, index)
            self.assertEqual(sim.var("ov_enabled"), 0)
        self.assertEqual(sim.prodos.open_files, {})              # everything closed
        # a ProDOS error shows its code: the volume directory is not readable as a file
        sim.click(*sim.entry_pos(0))
        sim.click(*LOAD_ITEM, settle=8)
        self.assertEqual(sim.state(), ST_EDIT)                   # TABLE1 itself loads

    def test_unknown_library_kind_keeps_the_table(self):
        good = TABLE1.read_bytes()
        image, _ = mt.split_pcs_file(good)
        last_size = 29 + image[28] - 1
        last_record = last_size + 1 + sum(image[29:last_size])
        self.assertEqual(image[last_record], 3)                 # library object
        bad = bytearray(good)
        l_record = last_record + 3 + 2 * image[last_record + 2]
        bad[4 + l_record] = 43                                  # first unknown kind
        sim = Sim(table_files(**{"BADKIND.PCS": bytes(bad)}))
        sim.boot_to_editor()
        before = sim.db_image()
        sim.open_menu()
        sim.click(*sim.entry_pos(1))
        sim.click(*LOAD_ITEM, settle=8)
        self.assertEqual(sim.state(), ST_DISK)
        self.assertEqual(sim.var("fm_err"), ERR_FORMAT)
        self.assertEqual(sim.db_image(), before)
        self.assertEqual(sim.prodos.open_files, {})

    def test_play_game_and_esc(self):
        sim = Sim(table_files())
        sim.boot_to_editor()
        # Add a bumper before leaving the editor: the game must initialize
        # from the edited object table, not just the built-in seed table.
        count = sim.mem[PBBASE + 28]
        sim.m.mouse_move(176, 55)                         # BMP1 in the kit
        sim.frames(2)
        sim.m.mouse_buttons(True, False)
        sim.frames(3)
        sim.m.mouse_move(120, 50)
        sim.frames(3)
        sim.m.mouse_move(70, 45)
        sim.frames(3)
        sim.m.mouse_buttons(False, False)
        sim.frames(6)
        self.assertEqual(sim.mem[PBBASE + 28], count + 1)
        sim.m.mouse_move(173, 35)                        # POLY in the kit
        sim.frames(2)
        sim.m.mouse_buttons(True, False)
        sim.frames(3)
        sim.m.mouse_move(125, 55)
        sim.frames(3)
        sim.m.mouse_move(80, 37)
        sim.frames(3)
        sim.m.mouse_buttons(False, False)
        sim.frames(6)
        self.assertEqual(sim.mem[PBBASE + 28], count + 2)
        sim.open_menu()
        sim.click(*PLAY_ITEM, settle=2)
        self.assertEqual(sim.state(), ST_PLAY)
        sim.frames(66)                                           # the shell's one-second wait
        # Editing leaves the span rows split at MIDY. Game setup must map
        # rows above it to MIDTOP, not continue through the unused gap.
        self.assertEqual(sim.mem[0xA5], 44)
        upper = sim.mem[0xA3] | sim.mem[0xA4] << 8
        lengths = sim.L["PBDX"]
        def span_row(y):
            return (sim.mem[sim.L["PBTBLO"] + y] |
                    sim.mem[sim.L["PBTBHI"] + y] << 8)
        self.assertEqual(span_row(45), upper)
        self.assertEqual(span_row(55),
                         upper + sum(sim.mem[lengths + y] for y in range(45, 55)))
        # the prompt: choose two players with the number key
        sim.key(ord("2"), settle=6)
        self.assertEqual(sim.mem[PLAYERCNT_ZP], 2)
        self.assertEqual(sim.state(), ST_PLAY)
        # RUN2's PBASES forms four 128-byte slices. Their pointers must
        # use the relocated P1STATE's actual low byte; assuming $00/$80
        # overwrites the editor's polygon scan tables.
        state_base = sim.L["P1STATE"]
        for zp, offset in ((0x2B, 0), (0x2D, 0x80),
                           (0x2F, 0x100), (0x31, 0x180)):
            self.assertEqual(sim.mem[zp] | sim.mem[zp + 1] << 8,
                             state_base + offset)
        ball_addr, ball = sim.l_record(4)
        x0, y0 = ball[17], ball[18]
        self.assertIn(4, (sim.pixel(x0 + dx, y0 + dy)
                          for dy in range(5) for dx in range(5)),
                      "the first ball did not appear after selecting players")
        sim.frames(10)
        self.assertNotEqual(sim.mem[ball_addr + 18], y0,
                            "the first ball did not begin moving")
        flip_addr, flip = sim.l_record(2)                        # the left flipper
        rest_ptr = flip[0] | (flip[1] << 8)
        # pull the plunger and release it: the ball moves
        sim.m.hold(KEY_SPACE)
        sim.frames(12)
        sim.m.release()
        sim.frames(40)
        moved = (sim.mem[ball_addr + 17], sim.mem[ball_addr + 18])
        self.assertNotEqual(moved, (x0, y0))
        # the left flipper: Z held advances its frame
        sim.m.hold("Z")
        sim.frames(6)
        ptr = sim.mem[flip_addr] | (sim.mem[flip_addr + 1] << 8)
        self.assertNotEqual(ptr, rest_ptr)
        sim.m.release()
        sim.frames(12)
        ptr = sim.mem[flip_addr] | (sim.mem[flip_addr + 1] << 8)
        self.assertEqual(ptr, rest_ptr)
        # Esc: back to the menu, the catalog read again
        sim.key(KEY_ESC, settle=6)
        self.assertEqual(sim.state(), ST_DISK)
        self.assertEqual(sim.catalog(), ["TABLE1.PCS"])
        # a second game: Esc at the prompt also returns
        sim.click(*PLAY_ITEM, settle=2)
        self.assertEqual(sim.state(), ST_PLAY)
        sim.frames(66)
        sim.key(KEY_ESC, settle=6)
        self.assertEqual(sim.state(), ST_DISK)
        # and the editor is still there
        sim.key(ord("E"), settle=6)
        self.assertEqual(sim.state(), ST_EDIT)

    def test_player_click_with_held_mouse_button_starts_first_ball(self):
        sim = Sim(table_files())
        sim.boot_to_editor()
        sim.open_menu()
        sim.click(*PLAY_ITEM, settle=2)
        sim.frames(66)
        sim.m.mouse_move(*PLAYER_BOX)
        sim.frames(1)
        sim.m.mouse_buttons(True, False)
        sim.frames(24)                 # the card still reports the button down
        self.assertEqual(sim.mem[PLAYERCNT_ZP], 2)
        self.assertGreater(sim.mem[0xC5], 0, "the game is stuck waiting for button release")
        ball_addr, ball = sim.l_record(4)
        x, y = sim.mem[ball_addr + 17], sim.mem[ball_addr + 18]
        self.assertIn(4, (sim.pixel(x + dx, y + dy)
                          for dy in range(5) for dx in range(5)))
        sim.m.mouse_buttons(False, False)
        sim.key(KEY_ESC, settle=6)
        self.assertEqual(sim.state(), ST_DISK)

    def test_crowded_edited_table_starts_with_number_key(self):
        # This arrangement used to turn a scan-row gap byte into object ID
        # $8D, then call its bogus $0303 hit vector on the first game tick.
        sim = Sim(table_files())
        sim.boot_to_editor()
        parts = json.loads((BUILD / "parts.json").read_text())["parts"]
        selected = [p for p in parts if p["name"] not in
                    ("POLY1", "POLY2", "POLY3", "POLY4")]
        for i, p in enumerate(selected[:36]):
            if "box" in p:
                w, h = p["box"]
                x = p["x0"] + w // 2
                y = p["y0"] - p.get("hoty", 0) + h // 2
            else:
                x = sum(p["x"]) // len(p["x"])
                y = sum(p["y"]) // len(p["y"])
            tx, ty = 70 + (i % 4) * 16, 35 + (i // 4 % 8) * 17
            sim.m.mouse_move(x, y)
            sim.frames(2)
            sim.m.mouse_buttons(True, False)
            sim.frames(3)
            sim.m.mouse_move(128, max(20, min(170, y)))
            sim.frames(3)
            sim.m.mouse_move(tx, ty)
            sim.frames(3)
            sim.m.mouse_buttons(False, False)
            sim.frames(6)
        self.assertEqual(sim.mem[PBBASE + 28], 57)
        self.assertEqual(sim.mem[0xA5], 44)
        sim.open_menu()
        sim.click(*PLAY_ITEM, settle=2)
        sim.frames(66)
        upper = sim.mem[0xA3] | sim.mem[0xA4] << 8
        self.assertEqual(sim.mem[sim.L["PBTBLO"] + 45] |
                         sim.mem[sim.L["PBTBHI"] + 45] << 8, upper)
        sim.key(ord("1"), settle=8)
        self.assertFalse(sim.left, "play jumped out of the game after the number key")
        ball_addr, ball = sim.l_record(4)
        x, y = ball[17], ball[18]
        self.assertIn(4, (sim.pixel(x + dx, y + dy)
                          for dy in range(5) for dx in range(5)))
        self.assertTrue(sim.frames(6), "play left the game during the first ball")
        self.assertNotEqual(sim.mem[ball_addr + 18], y)
        sim.key(KEY_ESC, settle=6)
        self.assertEqual(sim.state(), ST_DISK)

    def test_horizontal_scan_skips_empty_row(self):
        sim = Sim(table_files())
        sim.boot_to_editor()
        # Call RUN's CHECKHORIZ as a subroutine on an empty row. Without
        # the guard, the zero byte count wraps and scans 256 phantom bytes.
        row = 0
        sim.mem[sim.L["PBDX"] + row] = 0
        sim.mem[sim.L["PBTBLO"] + row] = 0
        sim.mem[sim.L["PBTBHI"] + row] = 0x1F
        sim.mem[0x1F00:0x2000] = bytes(256)
        cpu = sim.mpu
        cpu.pc = sim.L["CHECKHORIZ"]
        cpu.y, cpu.a, cpu.sp = row, 127, 0xFB
        cpu.p |= 1                                      # caller enters with carry set
        sim.mem[0x1FC] = 0x33                           # RTS destination $1234
        sim.mem[0x1FD] = 0x12
        for _ in range(12):
            if cpu.pc == 0x1234:
                break
            cpu.step()
        self.assertEqual(cpu.pc, 0x1234)
        self.assertEqual(cpu.p & 1, 0)                   # no hit: carry clear

    def test_quit_needs_confirmation(self):
        sim = Sim(table_files())
        sim.boot_to_editor()
        sim.open_menu()
        sim.click(*QUIT_ITEM)
        self.assertEqual(sim.state(), ST_DISK)
        self.assertTrue(sim.var("fm_flags") & 0x40)
        sim.click(*EDIT_ITEM)                                     # disarms
        self.assertEqual(sim.state(), ST_EDIT)
        sim.open_menu()
        self.assertFalse(sim.var("fm_flags") & 0x40)
        sim.key(ord("q"))
        self.assertTrue(sim.var("fm_flags") & 0x40)
        sim.key(ord("Q"), settle=4)
        self.assertTrue(sim.left)
        self.assertTrue(sim.prodos.quit)
        self.assertEqual(sim.prodos.calls[-1], (0x65, 0))
        self.assertEqual(sim.m.newvideo, 0x01)                    # SHR off

    def test_title_and_no_prodos(self):
        sim = Sim(prodos=False)
        sim.frames(3)
        self.assertEqual(sim.state(), ST_TITLE)
        sim.frames(20)
        self.assertEqual(sim.state(), ST_TITLE)                   # it waits
        sim.click(100, 100, settle=6)
        self.assertEqual(sim.state(), ST_EDIT)
        sim.open_menu()
        self.assertEqual(sim.var("fm_err"), ERR_NOMLI)
        self.assertEqual(sim.var("fm_count"), 0)
        sim.key(KEY_ESC, settle=6)
        self.assertEqual(sim.state(), ST_EDIT)

    def test_title_click_with_held_mouse_button_enters_editor(self):
        sim = Sim(table_files())
        sim.frames(3)
        self.assertEqual(sim.state(), ST_TITLE)
        sim.m.mouse_move(100, 100)
        sim.frames(1)
        sim.m.mouse_buttons(True, False)
        sim.frames(18)
        self.assertEqual(sim.state(), ST_EDIT)
        sim.m.mouse_buttons(False, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
