#!/usr/bin/env python3
"""Check tools/make_tables.py and table_normalise (docs/DESIGN.md sections
6 and 11).

Run:  python3 tests/test_tables.py        (from the project directory)

The generator is run on build/parts.json into a temporary directory and
its output compared with the build's (build/tables/TABLE1.PCS and
build/default_table.s; make is run when they are missing). The file is
parsed with the test's own reader: the PCS1 chunk (LOGIC, WSET, PBDATA:
count, sizes, records) and the OVL1 chunk (tile map and RLE end). Every
object record must parse, every polygon must start with a downward edge
(the scan converter's requirement), every vertex must lie on the table,
object 0 must be the border, and every L-record must hold (kind, frame)
in its first two bytes with the template bytes zero.

Then the port is booted in the py65 machine (tools/pcsdbg.py) and the
installed default table is walked: table_normalise must have turned every
L-record's (kind, frame) into the sprite pointer spr_dir + 4 *
(SPR_<KIND>_FIRST + frame) of build/assets.inc and copied bytes 5-7 and
10-15 from the kind's template in RUN.S, which is checked both against
the template in memory (kind_tmpl + kind_loff) and against the text of
build/port/RUN.s; bytes 2-4 and 8-9 must be the file's.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
BUILD = PROJECT / "build"
MAKE_TABLES = TOOLS / "make_tables.py"
sys.path.insert(0, str(TOOLS))

import run_editor  # noqa: E402

try:
    import pcsdbg  # noqa: E402
except ImportError:      # pragma: no cover
    pcsdbg = None

TABLE_W, TABLE_H = 154, 192
OBJ_POLYGON, OBJ_BPOLYGON, OBJ_LIBOBJ = 1, 2, 3
KIND_COUNT = 43
LREC_MIN = 16
OVL_TILES = 72              # ov_tiles: 24 tile rows x 3 bytes (render.s)
WSET_DEFAULT = [4, 4, 3, 4]
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
PBDATA = PBBASE + 0x1C


def ensure_build() -> None:
    needed = [BUILD / "PCS.SYSTEM", BUILD / "PCS.lbl", BUILD / "parts.json",
              BUILD / "tables" / "TABLE1.PCS", BUILD / "default_table.s", BUILD / "assets.inc"]
    if not all(p.exists() for p in needed):
        subprocess.run(["make", "all", str(BUILD / "tables")], cwd=PROJECT, check=True, capture_output=True)


def rom_fallback() -> None:
    if not Path(run_editor.DEFAULT_ROM).exists():
        blank = Path(tempfile.gettempdir()) / "pcs_test_blank_rom.bin"
        if not blank.exists() or blank.stat().st_size != 0x4000:
            blank.write_bytes(bytes(0x4000))
        run_editor.DEFAULT_ROM = blank


def parse_inc(path: Path) -> dict[str, int]:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def parse_database(db: bytes):
    """LOGIC, WSET, [(kind, colour, xs, ys, lrec bytes or None)] from a PBBASE image."""
    logic, wset = db[:24], list(db[24:28])
    count = db[28]
    sizes = list(db[29:29 + count])
    pos = 29 + count
    objs = []
    for size in sizes:
        rec = db[pos:pos + size]
        if len(rec) != size:
            raise ValueError("record past the end of the data")
        kind, colour, n = rec[0], rec[1], rec[2]
        xs, ys = list(rec[3:3 + n]), list(rec[3 + n:3 + 2 * n])
        lrec = rec[3 + 2 * n:] if kind == OBJ_LIBOBJ else None
        if kind != OBJ_LIBOBJ and len(rec) != 3 + 2 * n:
            raise ValueError("polygon record with trailing bytes")
        objs.append((kind, colour, xs, ys, lrec))
        pos += size
    return logic, wset, objs, pos


def parse_pcs_file(data: bytes):
    if data[:4] != b"PCS1":
        raise ValueError("no PCS1 magic")
    logic, wset, objs, end = parse_database(data[4:])
    rest = data[4 + end:]
    if rest[:4] != b"OVL1":
        raise ValueError("no OVL1 chunk after the database")
    tiles = rest[4:4 + OVL_TILES]
    rle = rest[4 + OVL_TILES:]
    return logic, wset, objs, tiles, rle


def parse_default_table_s(path: Path) -> bytes:
    data = bytearray()
    length = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith(".byte"):
            data += bytes(int(v.strip()[1:], 16) for v in line[5:].split(","))
        elif line.startswith("default_table_len:"):
            length = int(line.split(".word")[1])
    if length is None or length != len(data):
        raise ValueError("default_table_len does not match the data")
    return bytes(data)


def run_templates(path: Path) -> dict[str, list]:
    """RUN.s templates: label -> flat list of data items, .byte values as
    ints and .word operands as strings (two list slots)."""
    lines = path.read_text().splitlines()
    out = {}
    label = None
    for line in lines:
        m = re.match(r"^([A-Z][A-Z0-9_]*):(.*)$", line)
        if m:
            label = m.group(1)
            out[label] = []
            line = m.group(2)
        if label is None:
            continue
        s = line.strip()
        if s.startswith(".byte"):
            for v in s[5:].split(";")[0].split(","):
                v = v.strip()
                if v.startswith("$"):
                    out[label].append(int(v[1:], 16))
                elif v.isdigit():
                    out[label].append(int(v))
                else:
                    out[label].append(v)            # a symbolic byte (<label)
        elif s.startswith(".word"):
            out[label] += [s[5:].split(";")[0].strip(), None]
        elif s and not s.startswith(";"):
            label = None                # code: the template ended
    return out


class TestGenerator(unittest.TestCase):
    """tools/make_tables.py writes a valid database and reproduces the build."""

    @classmethod
    def setUpClass(cls):
        ensure_build()
        cls.tmp = tempfile.TemporaryDirectory(prefix="pcs_tables_")
        out = Path(cls.tmp.name)
        r = subprocess.run([sys.executable, str(MAKE_TABLES), "--parts", str(BUILD / "parts.json"),
                            "--out", str(out / "tables"), "--default", str(out / "default_table.s")],
                           capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(f"make_tables.py failed:\n{r.stdout}\n{r.stderr}")
        cls.file = (out / "tables" / "TABLE1.PCS").read_bytes()
        cls.default = parse_default_table_s(out / "default_table.s")
        cls.parts = json.loads((BUILD / "parts.json").read_text())["parts"]
        cls.inc = parse_inc(BUILD / "assets.inc")
        cls.logic, cls.wset, cls.objs, cls.tiles, cls.rle = parse_pcs_file(cls.file)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_matches_the_build(self):
        self.assertEqual(self.file, (BUILD / "tables" / "TABLE1.PCS").read_bytes())
        self.assertEqual(self.default, parse_default_table_s(BUILD / "default_table.s"))

    def test_chunks(self):
        self.assertEqual(self.file[:4], b"PCS1")
        self.assertEqual(self.file[4:4 + len(self.default)], self.default,
                         "the built-in table is the file's database")
        self.assertEqual(len(self.tiles), OVL_TILES)
        self.assertEqual(self.tiles, bytes(OVL_TILES), "a seed table has no overlay edits")
        self.assertEqual(self.rle, b"\x00", "an empty RLE stream ends the file")

    def test_header(self):
        self.assertEqual(self.logic, bytes(24), "no wiring in the seed table")
        self.assertEqual(self.wset, WSET_DEFAULT)
        self.assertEqual(self.default[28], len(self.objs))
        self.assertLessEqual(len(self.objs), 127)

    def test_records_parse_and_fit_the_table(self):
        self.assertGreater(len(self.objs), 10)
        for i, (kind, colour, xs, ys, lrec) in enumerate(self.objs):
            self.assertIn(kind, (OBJ_POLYGON, OBJ_BPOLYGON, OBJ_LIBOBJ), f"object {i}")
            self.assertGreaterEqual(len(xs), 3, f"object {i}")
            self.assertTrue(all(0 <= x < TABLE_W for x in xs), f"object {i}: x {xs}")
            self.assertTrue(all(0 <= y < TABLE_H for y in ys), f"object {i}: y {ys}")
            if kind == OBJ_LIBOBJ:
                self.assertEqual(colour, 0x10, f"object {i}: parts are inviso")
                self.assertTrue(all(1 <= y <= 190 for y in ys), f"object {i}: part y {ys}")
            else:
                self.assertLess(colour, 16, f"object {i}: palette index")

    def test_polygons_start_with_a_downward_edge(self):
        for i, (_kind, _colour, xs, ys, _l) in enumerate(self.objs):
            self.assertLess(ys[0], ys[1], f"object {i}: first edge must go down ({xs}, {ys})")

    def test_object_zero_is_the_border(self):
        self.assertEqual(self.objs[0][0], OBJ_BPOLYGON)
        self.assertEqual(sum(1 for o in self.objs if o[0] == OBJ_BPOLYGON), 1)

    def test_lrecords_hold_kind_and_frame(self):
        parts = self.parts
        for i, (kind, _colour, xs, ys, lrec) in enumerate(self.objs):
            if kind != OBJ_LIBOBJ:
                continue
            self.assertGreaterEqual(len(lrec), LREC_MIN, f"object {i}")
            k, frame = lrec[0], lrec[1]
            self.assertLess(k, KIND_COUNT, f"object {i}")
            part = parts[k]
            self.assertEqual(part["kind"], k)
            self.assertLess(frame, self.inc[f"SPR_{part['name']}_FRAMES"], f"object {i}: frame")
            self.assertEqual(len(lrec) + 3 + 2 * len(xs), part["objlen"], f"object {i}: record length")
            self.assertEqual(lrec[5:8], bytes(3), f"object {i}: bytes 5-7 are the loader's")
            self.assertEqual(lrec[10:16], bytes(6), f"object {i}: bytes 10-15 are the loader's")
            self.assertEqual(lrec[4], 0, f"object {i}: x high byte")
            self.assertEqual((lrec[8], lrec[9]), (part["time"], part["score"]), f"object {i}")
            # the sprite box sits on the table at (x, y - hoty)
            x, y = lrec[3], lrec[2]
            w, h = part["box"]
            self.assertLessEqual(x + w, TABLE_W, f"object {i}: box right edge")
            self.assertLessEqual(y - part["hoty"] + h, TABLE_H, f"object {i}: box bottom")
            self.assertGreaterEqual(y - part["hoty"], 0, f"object {i}: box top")

    def test_parts_present(self):
        names = [self.parts[o[4][0]]["name"] for o in self.objs if o[0] == OBJ_LIBOBJ]
        for needed in ("LEFTFLIPPER", "RIGHTFLIPPER", "LAUNCHER", "BALL"):
            self.assertIn(needed, names)


@unittest.skipUnless(pcsdbg, "py65 not installed")
class TestNormalise(unittest.TestCase):
    """table_normalise resolves every L-record of the installed default table."""

    @classmethod
    def setUpClass(cls):
        ensure_build()
        rom_fallback()
        with contextlib.redirect_stdout(io.StringIO()):
            cls.d = pcsdbg.Dbg(frames=1)
        cls.parts = json.loads((BUILD / "parts.json").read_text())["parts"]
        cls.inc = parse_inc(BUILD / "assets.inc")
        cls.default = parse_default_table_s(BUILD / "default_table.s")
        cls.file_objs = parse_database(cls.default)[2]
        cls.templates = run_templates(BUILD / "port" / "RUN.s")

    def memory_objects(self):
        d = self.d
        n = d.mem[PBDATA]
        sizes = d.mem[PBDATA + 1:PBDATA + 1 + n]
        a = PBDATA + 1 + n
        out = []
        for size in sizes:
            rec = bytes(d.mem[a:a + size])
            out.append((a, rec))
            a += size
        return out

    def template(self, kind):
        d = self.d
        L = d.L
        addr = d.mem[L["kind_tmpl_lo"] + kind] | (d.mem[L["kind_tmpl_hi"] + kind] << 8)
        return addr, addr + d.mem[L["kind_loff"] + kind]

    def test_header_installed(self):
        d = self.d
        self.assertEqual(bytes(d.mem[PBBASE:PBBASE + 28]), self.default[:28], "LOGIC and WSET")
        self.assertEqual(d.mem[PBDATA], len(self.file_objs))

    def test_kind_table_matches_assets_inc(self):
        d = self.d
        L = d.L
        for k, part in enumerate(self.parts):
            name = part["name"]
            self.assertEqual(d.mem[L["kind_spr0"] + k], self.inc[f"SPR_{name}_FIRST"], name)
            self.assertEqual(d.mem[L["kind_frames"] + k], self.inc[f"SPR_{name}_FRAMES"], name)
            self.assertEqual(d.mem[L["kind_len"] + k], part["objlen"], name)
            tmpl, lrec = self.template(k)
            self.assertEqual(lrec - tmpl, 3 + 2 * len(part["x"]), f"{name}: L-record offset")
            self.assertEqual(d.mem[tmpl], OBJ_LIBOBJ if "bitmap" in part else OBJ_POLYGON,
                             f"{name}: polygon-only kinds are plain polygons")

    def test_every_lrecord_is_resolved(self):
        d = self.d
        spr_dir = d.L["spr_dir"]
        objs = self.memory_objects()
        self.assertEqual(len(objs), len(self.file_objs))
        checked = 0
        for i, ((addr, rec), (kind, _c, xs, ys, file_l)) in enumerate(zip(objs, self.file_objs)):
            self.assertEqual(rec[0], kind, f"object {i}")
            self.assertEqual(list(rec[3:3 + rec[2]]), xs, f"object {i}: vertices")
            if kind != OBJ_LIBOBJ:
                self.assertEqual(rec, bytes([kind, _c, len(xs)] + xs + ys), f"object {i}")
                continue
            l = rec[3 + 2 * rec[2]:]
            k, frame = file_l[0], file_l[1]
            part = self.parts[k]
            first = self.inc[f"SPR_{part['name']}_FIRST"]
            self.assertEqual(l[0] | (l[1] << 8), spr_dir + 4 * (first + frame),
                             f"object {i} ({part['name']}): sprite pointer")
            self.assertEqual(l[2:5], file_l[2:5], f"object {i}: y, x unchanged")
            self.assertEqual(l[8:10], file_l[8:10], f"object {i}: TIME mask and score unchanged")
            self.assertEqual(l[16:], file_l[16:], f"object {i}: state unchanged")
            _tmpl, tl = self.template(k)
            tmpl_l = bytes(d.mem[tl:tl + 16])
            self.assertEqual(l[5:8], tmpl_l[5:8], f"object {i}: box and stride from the template")
            self.assertEqual(l[10:16], tmpl_l[10:16], f"object {i}: vectors from the template")
            self.assertEqual((l[5], l[6], l[7]),
                             (self.inc[f"SPR_{part['name']}_H"], self.inc[f"SPR_{part['name']}_W"], 4),
                             f"object {i}: height, width, stride")
            checked += 1
        self.assertGreater(checked, 10)

    def test_templates_in_run_s(self):
        """Bytes 5-7 of every kind's L-record in build/port/RUN.s are its sprite
        box and stride, and its frame-0 pointer is spr_dir + 4*FIRST."""
        d = self.d
        labels = {}
        for line in (BUILD / "PCS.lbl").read_text().splitlines():
            p = line.split()
            if len(p) == 3 and p[0] == "al":
                labels.setdefault(p[2].lstrip("."), set()).add(int(p[1], 16))
        for k, part in enumerate(self.parts):
            if "bitmap" not in part:
                continue                                    # polygon-only kinds have no L-record
            name = part["name"]
            items = self.templates[name]
            n = items[2]
            l = items[3 + 2 * n:]
            first = self.inc[f"SPR_{name}_FIRST"]
            self.assertEqual(l[0], f"spr_dir+{4 * first}", f"{name}: frame-0 pointer")
            self.assertEqual(l[5:8], [self.inc[f"SPR_{name}_H"], self.inc[f"SPR_{name}_W"], 4], name)
            _tmpl, tl = self.template(k)
            mem_l = bytes(d.mem[tl:tl + 16])
            self.assertEqual(l[5:8], list(mem_l[5:8]), f"{name}: template in memory")
            for j, off in ((10, 0), (12, 0), (14, 0)):
                vector = l[j]
                self.assertIsInstance(vector, str, f"{name}: vector at +{j}")
                value = mem_l[j] | (mem_l[j + 1] << 8)
                self.assertIn(value, labels.get(vector, set()), f"{name}: {vector} at +{j} = ${value:04X}")

    def test_unknown_kind_is_left_alone(self):
        """A record with a kind beyond the table keeps its bytes (a file from a
        newer build does not crash the loader)."""
        d = self.d
        objs = self.memory_objects()
        addr, rec = next((a, r) for a, r in objs if r[0] == OBJ_LIBOBJ)
        l = addr + 3 + 2 * rec[2]
        before = bytes(d.mem[l:l + 16])
        d.mem[l] = KIND_COUNT + 5
        d.mem[l + 1] = 0
        d.call("table_normalise")
        self.assertEqual(bytes(d.mem[l + 2:l + 16]), before[2:16])
        self.assertEqual(d.mem[l], KIND_COUNT + 5)
        d.mem[l:l + 16] = before                         # put the table back

    def test_normalise_is_idempotent_on_kind_frame(self):
        """Re-running after resetting bytes 0-1 to (kind, frame) gives the same
        table (the load path of a saved file)."""
        d = self.d
        spr_dir = d.L["spr_dir"]
        before = bytes(d.mem[PBBASE:PBBASE + len(self.default)])
        for (addr, rec), (kind, _c, _x, _y, file_l) in zip(self.memory_objects(), self.file_objs):
            if kind == OBJ_LIBOBJ:
                l = addr + 3 + 2 * rec[2]
                d.mem[l], d.mem[l + 1] = file_l[0], file_l[1]
                d.mem[l + 5:l + 8] = bytes(3)
                d.mem[l + 10:l + 16] = bytes(6)
        d.call("table_normalise")
        self.assertEqual(bytes(d.mem[PBBASE:PBBASE + len(self.default)]), before)
        # a frame beyond the kind's count falls back to frame 0
        addr, rec = next((a, r) for a, r in self.memory_objects()
                         if r[0] == OBJ_LIBOBJ and self.parts[self.kind_of(a, r)].get("frames", 0) > 1)
        l = addr + 3 + 2 * rec[2]
        k = self.kind_of(addr, rec)
        d.mem[l], d.mem[l + 1] = k, 200
        d.call("table_normalise")
        first = self.inc[f"SPR_{self.parts[k]['name']}_FIRST"]
        self.assertEqual(d.w(l), spr_dir + 4 * first)

    def kind_of(self, addr, rec):
        l = addr + 3 + 2 * rec[2]
        ptr = self.d.w(l)
        sid = (ptr - self.d.L["spr_dir"]) // 4
        for k, part in enumerate(self.parts):
            first = self.inc[f"SPR_{part['name']}_FIRST"]
            if part.get("frames") and first <= sid < first + part["frames"]:
                return k
        raise AssertionError(f"no kind for sprite {sid}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
