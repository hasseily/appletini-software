#!/usr/bin/env python3
"""Check tools/wad2a2.py, the WAD converter (docs/DESIGN.md section 6).

Run:  python3 tests/test_wad2a2.py        (from the project directory)

The whole of episode 1 is converted once into a temporary directory and
read back only through the data files' headers (as the kernel's loader
does), then checked against the WAD with code written independently of
the converter's: textures, flats and sprites decoded from the banks equal
a straightforward composite-and-halve of the WAD's patches; every map
array has the WAD's record count and its elements, reached through the
far-array formula of section 4, carry the WAD's values; nothing crosses
or overlaps within a bank; every graphics bank starts with the colormaps;
the headers rebuild the converter's bank images byte for byte; a second
run gives identical files; the include files assemble and compile.

The WAD is looked for at $FREEDOOM_WAD, then build/wad/freedoom1.wad
(tools/fetch_freedoom.py puts it there); without it the tests are skipped.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import wad2a2  # noqa: E402
import wadlib  # noqa: E402

WAD = Path(os.environ.get("FREEDOOM_WAD", PROJECT / "build/wad/freedoom1.wad"))
MAPS = [f"E1M{i}" for i in range(1, 10)]


def reference_halve(cols, w, h, sx, sy, rgb):
    """Independent restatement of the halving rule of section 6."""
    out = []
    for X in range((w + sx - 1) // sx):
        col = []
        for Y in range((h + sy - 1) // sy):
            vals = [cols[x][y] for x in range(sx * X, min(w, sx * X + sx))
                    for y in range(sy * Y, min(h, sy * Y + sy))]
            opaque = [v for v in vals if v is not None]
            if len(opaque) * 2 < len(vals):
                col.append(None)
            elif len(set(opaque)) == 1 and opaque[0] != 247:
                col.append(opaque[0])
            else:
                n = len(opaque)
                s = [sum(rgb[v][c] for v in opaque) for c in range(3)]
                best = min((i for i in range(256) if i != 247),
                           key=lambda i: (sum((n * rgb[i][c] - s[c]) ** 2 for c in range(3)), i))
                col.append(best)
        out.append(col)
    return out


def reference_composite(wad, tdef):
    canvas = [[None] * tdef.height for _ in range(tdef.width)]
    for ox, oy, pname in tdef.patches:
        pic = wadlib.decode_patch(wad.read(pname))
        for x in range(pic.width):
            for y in range(pic.height):
                v = pic.columns[x][y]
                tx, ty = ox + x, oy + y
                if v is not None and 0 <= tx < tdef.width and 0 <= ty < tdef.height:
                    canvas[tx][ty] = v
    return canvas


def far_element(banks, desc, i):
    """Element i of a far array: bank FIRST + (i >> k), BASE + (i & mask) * size."""
    k = desc["log2"]
    bank = desc["bank"] + (i >> k)
    addr = desc["addr"] + (i & ((1 << k) - 1)) * desc["elsize"]
    assert addr + desc["elsize"] <= wad2a2.BANK_HI
    return bytes(banks[bank][addr:addr + desc["elsize"]])


@unittest.skipUnless(WAD.exists(), f"no WAD at {WAD} (run tools/fetch_freedoom.py)")
class Wad2A2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wad2a2_"))
        cls.out = cls.tmp / "data"
        cls.conv = wad2a2.Conversion(WAD, MAPS, verbose=False)
        cls.manifest = cls.conv.write(cls.out, preview=False)
        cls.wad = wadlib.Wad(WAD)
        cls.rgb = [tuple(cls.wad.read("PLAYPAL")[3 * i:3 * i + 3]) for i in range(256)]
        # the loader's view: DIR + GFX + each map separately
        cls.common = wad2a2.load_banks(cls.out, ["DIR", "GFX"])
        cls.dirb = cls.conv.dir_bank
        cls.layout = cls.manifest["directory"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def rec(self, tag, table, index):
        return wad2a2.read_record(self.common, tag, self.dirb, self.layout[table]["addr"], index)

    # --- files and banks ---------------------------------------------------
    def test_all_maps_kept(self):
        self.assertEqual(sorted(self.manifest["maps"]), MAPS)
        self.assertEqual(self.manifest["skipped"], {})

    def test_files_rebuild_bank_images(self):
        regions = {}
        for f in self.manifest["files"]:
            raw = (self.out / f["name"]).read_bytes()
            self.assertLessEqual(len(raw), wad2a2.FILE_MAX, f["name"])
            self.assertEqual(raw[:4], b"A2DM")
            for b, a, data in wad2a2.parse_data_file(raw):
                img = regions.setdefault(f["region"], {}).setdefault(b, bytearray(0x10000))
                self.assertGreaterEqual(a, wad2a2.BANK_LO)
                self.assertLessEqual(a + len(data), wad2a2.BANK_HI)
                img[a:a + len(data)] = data
        for region, images, banks in self.conv.region_list():
            self.assertEqual(sorted(regions[region]), sorted(banks), region)
            for b in banks:
                self.assertEqual(bytes(regions[region][b]), bytes(images.image[b]),
                                 f"{region} bank {b}")

    def test_banks_contiguous_and_bounded(self):
        m = self.manifest["banks"]
        used = {self.conv.dir_bank} | set(self.conv.gfx_banks)
        for v in self.conv.maps.values():
            used |= set(v["banks"])
        self.assertEqual(sorted(used), list(range(m["first"], m["last"] + 1)))
        self.assertGreaterEqual(m["first"], 2)

    def test_colormaps_in_every_graphics_bank(self):
        cmap = self.wad.read("COLORMAP")
        want = b"".join(cmap[512 * k:512 * k + 256] for k in range(16))
        for b in self.conv.gfx_banks:
            self.assertEqual(bytes(self.common[b][0x0200:0x1200]), want, f"bank {b}")
        inv = self.layout["INVULMAP"]["addr"]
        self.assertEqual(bytes(self.common[self.dirb][inv:inv + 256]), cmap[32 * 256:33 * 256])

    def test_graphics_objects_do_not_cross_or_overlap(self):
        spans = {}
        for o in self.conv.gfx_objects:
            self.assertGreaterEqual(o.addr, wad2a2.GFX_DATA, o.name)
            self.assertLessEqual(o.addr + len(o.data), wad2a2.BANK_HI, o.name)
            spans.setdefault(o.bank, []).append((o.addr, o.addr + len(o.data)))
        for b, lst in spans.items():
            lst.sort()
            for (a0, a1), (b0, _) in zip(lst, lst[1:]):
                self.assertLessEqual(a1, b0, f"overlap in bank {b}")

    def test_map_chunks_do_not_cross_or_overlap(self):
        for m, info in self.conv.maps.items():
            spans = {}
            for name, d in info["arrays"].items():
                total = d["count"] * d["elsize"]
                per = d["elsize"] << d["log2"]
                self.assertEqual(d["chunks"], max(1, -(-total // per)), (m, name))
                if d["chunks"] == 1:
                    self.assertLessEqual(d["count"], 1 << d["log2"], (m, name))
                for c in range(d["chunks"]):
                    n = min(per, total - c * per)
                    b = d["bank"] + c
                    self.assertIn(b, info["banks"])
                    self.assertGreaterEqual(d["addr"], wad2a2.BANK_LO)
                    self.assertLessEqual(d["addr"] + n, wad2a2.BANK_HI, (m, name, c))
                    spans.setdefault(b, []).append((d["addr"], d["addr"] + n))
            for b, lst in spans.items():
                lst.sort()
                for (a0, a1), (b0, _) in zip(lst, lst[1:]):
                    self.assertLessEqual(a1, b0, f"{m}: overlap in bank {b}")

    # --- graphics round trips ------------------------------------------------
    def test_textures_round_trip(self):
        tdefs = {t.name: t for t in reversed(self.wad.texture_defs())}
        names = self.conv.tex_names
        # every masked texture, every multi-patch one up to a sample, the sky
        pick = [i for i in range(1, len(names))
                if self.conv.textures[i]["masked"] or names[i].startswith("SKY")]
        pick += [i for i in range(1, len(names)) if len(tdefs[names[i]].patches) > 1][::6]
        pick += list(range(1, len(names), 17))
        for i in sorted(set(pick)):
            td = tdefs[names[i]]
            ref = reference_halve(reference_composite(self.wad, td), td.width, td.height,
                                  2, 2, self.rgb)
            w0, h0 = len(ref), len(ref[0])
            t, cols = wad2a2.decode_texture(self.common, self.dirb, self.layout["TEXDIR"]["addr"], i)
            W, H = t["wmask"] + 1, t["hmask"] + 1
            self.assertEqual((W & (W - 1), H & (H - 1)), (0, 0))
            self.assertEqual((1 << t["log2w"], 1 << t["log2h"]), (W, H))
            self.assertEqual((t["width"], t["height"]), (td.width, td.height))
            masked = any(v is None for c in ref for v in c)
            self.assertEqual(bool(t["flags"] & wad2a2.TEXF_MASKED), masked, names[i])
            for x in range(W):
                want = [247 if v is None else v for v in
                        (ref[x % w0][y % h0] for y in range(H))]
                self.assertEqual(cols[x], want, f"{names[i]} column {x}")

    def test_flats_round_trip(self):
        for i, name in enumerate(self.conv.flat_names):
            if i % 5 and name != "F_SKY1":
                continue
            raw = self.wad.read(name)
            ref = reference_halve([[raw[64 * y + x] for y in range(64)] for x in range(64)],
                                  64, 64, 2, 2, self.rgb)
            r = self.rec("FLAT", "FLATDIR", i)
            data = self.common[r["bank"]][r["addr"]:r["addr"] + 1024]
            self.assertEqual(list(data), [ref[x][y] for y in range(32) for x in range(32)], name)
            self.assertEqual(bool(r["flags"] & wad2a2.FLATF_SKY), name == "F_SKY1")

    def test_sprites_round_trip(self):
        for i, s in enumerate(self.conv.sprlumps):
            if i % 7:
                continue
            pic = wadlib.decode_patch(self.wad.read(s["name"]))
            ref = reference_halve(pic.columns, pic.width, pic.height, 2, 2, self.rgb)
            r = self.rec("SPRLUMP", "SPRLUMP", i)
            w, h, left, top, cols = wad2a2.decode_sprite(self.common[r["bank"]], r["addr"])
            self.assertEqual((w, left, top), (r["width"], r["left"], r["top"]))
            self.assertEqual((w, h), (len(ref), len(ref[0])))
            self.assertEqual((left, top), (pic.left // 2, pic.top // 2))
            self.assertEqual(cols, ref, s["name"])

    def test_sprite_frames(self):
        spr = {s: i for i, s in enumerate(self.conv.sprite_names)}
        lumps = [s["name"] for s in self.conv.sprlumps]
        for name in ("POSS", "TROO", "PISG", "BAR1", "SARG"):
            d = self.rec("SPRDEF", "SPRDEF", spr[name])
            wad_frames = {n[4] for n in lumps if n[:4] == name} | \
                {n[6] for n in lumps if n[:4] == name and len(n) == 8}
            self.assertEqual(d["numframes"], max(ord(c) for c in wad_frames) - 64, name)
            for f in range(d["numframes"]):
                fr = self.rec("SPRFRAME", "SPRFRAME", d["firstframe"] + f)
                letter = chr(65 + f)
                for r in range(8):
                    e = fr[f"rot{r}"]
                    lump = lumps[e & 0x3FFF]
                    rotates = bool(e & 0x4000)
                    flip = bool(e & 0x8000)
                    if not rotates:
                        self.assertEqual(lump, f"{name}{letter}0")
                    elif not flip:
                        self.assertEqual(lump[4:6], f"{letter}{r + 1}")
                    else:
                        self.assertEqual(lump[6:8], f"{letter}{r + 1}")

    def test_palette(self):
        pp = self.wad.read("PLAYPAL")
        addr = self.layout["PLAYPAL"]["addr"]
        img = self.common[self.dirb]
        for p in (0, 1, 13):
            for i in (0, 100, 176, 255):
                r, g, b = (round(v * 15 / 255) for v in pp[768 * p + 3 * i:768 * p + 3 * i + 3])
                lo, hi = img[addr + 512 * p + 2 * i], img[addr + 512 * p + 2 * i + 1]
                self.assertEqual((lo, hi), (g << 4 | b, 0x20 | r))

    # --- level data --------------------------------------------------------
    def test_map_counts_and_contents(self):
        sizes = {"VERTEXES": 4, "SEGS": 12, "SSECTORS": 4, "NODES": 28, "SIDEDEFS": 30,
                 "LINEDEFS": 14, "SECTORS": 26, "THINGS": 10}
        for m in MAPS:
            lumps = self.wad.map_lumps(m)
            info = self.manifest["maps"][m]
            banks = wad2a2.load_banks(self.out, [m])
            banks.update(self.common)
            arrays = info["arrays"]
            for name, size in sizes.items():
                self.assertEqual(arrays[name]["count"], len(lumps[name]) // size, (m, name))
            nsec = arrays["SECTORS"]["count"]
            self.assertEqual(arrays["REJECT"]["count"], (nsec * nsec + 7) // 8)
            self.assertEqual(arrays["BLOCKMAP"]["count"] * 2, len(lumps["BLOCKMAP"]))
            # every element through the far formula
            R = wad2a2.RECORDS
            verts = list(struct.iter_unpack("<hh", lumps["VERTEXES"]))
            for i, v in enumerate(verts):
                self.assertEqual(R["VERTEX"].unpack(far_element(banks, arrays["VERTEXES"], i)),
                                 {"x": v[0], "y": v[1]})
            lines = list(struct.iter_unpack("<HHHHHHH", lumps["LINEDEFS"]))
            sides = [struct.unpack_from("<hh8s8s8sH", lumps["SIDEDEFS"], 30 * i)
                     for i in range(len(lumps["SIDEDEFS"]) // 30)]
            for i, (v1, v2, angle, ld, side, off) in enumerate(
                    struct.iter_unpack("<HHHHHh", lumps["SEGS"])):
                s = R["SEG"].unpack(far_element(banks, arrays["SEGS"], i))
                self.assertEqual((s["v1"], s["v2"], s["angle"], s["linedef"], s["offset"]),
                                 (v1, v2, angle, ld, off))
                sd = lines[ld][5 + side]
                self.assertEqual(s["sidedef"], sd)
                self.assertEqual(s["frontsector"], sides[sd][5])
            for i, l in enumerate(lines):
                r = R["LINEDEF"].unpack(far_element(banks, arrays["LINEDEFS"], i))
                self.assertEqual((r["v1"], r["v2"], r["flags"], r["side0"], r["side1"]),
                                 (l[0], l[1], l[2], l[5], l[6]))
                self.assertEqual((r["dx"], r["dy"]), (verts[l[1]][0] - verts[l[0]][0],
                                                     verts[l[1]][1] - verts[l[0]][1]))
            for i, sd in enumerate(sides):
                r = R["SIDEDEF"].unpack(far_element(banks, arrays["SIDEDEFS"], i))
                self.assertEqual((r["xoffset"], r["yoffset"], r["sector"]), (sd[0], sd[1], sd[5]))
                for field, raw in (("toptexture", sd[2]), ("midtexture", sd[4])):
                    n = wadlib.lump_name(raw)
                    want = 0 if n == "-" else self.conv.texindex[n]
                    self.assertEqual(r[field], want)
            nodes = list(struct.iter_unpack("<hhhh4h4hHH", lumps["NODES"]))
            for i, nd in enumerate(nodes):
                raw = far_element(banks, arrays["NODES"], i)
                self.assertEqual(struct.unpack_from("<hhhh4h4hHH", raw), nd)
            rej = b"".join(far_element(banks, arrays["REJECT"], i)
                           for i in range(arrays["REJECT"]["count"]))
            self.assertEqual(rej[:len(lumps["REJECT"])], lumps["REJECT"][:len(rej)])
            bm = b"".join(far_element(banks, arrays["BLOCKMAP"], i)
                          for i in range(arrays["BLOCKMAP"]["count"]))
            self.assertEqual(bm, lumps["BLOCKMAP"])
            # sector line lists cover every line's sectors
            seen = set()
            for s in range(nsec):
                r = R["SECTOR"].unpack(far_element(banks, arrays["SECTORS"], s))
                for j in range(r["linecount"]):
                    ln = R["SECLINE"].unpack(far_element(banks, arrays["SECLINES"],
                                                         r["firstline"] + j))["line"]
                    seen.add((s, ln))
            want = set()
            for i, l in enumerate(lines):
                want.add((sides[l[5]][5], i))
                if l[6] != 0xFFFF:
                    want.add((sides[l[6]][5], i))
            self.assertEqual(seen, want, m)
            # the map record in the directory
            slot = self.rec("MAP", "MAPDIR", info["slot"])
            self.assertEqual(slot["name"].rstrip(b"\0").decode(), m)
            for k, name in enumerate(wad2a2.MAP_ARRAYS):
                d = R["DESC"].unpack(slot["arrays"], 8 * k)
                self.assertEqual(d, arrays[name])

    # --- determinism and include files --------------------------------------
    def test_deterministic(self):
        out2 = self.tmp / "again"
        wad2a2.Conversion(WAD, MAPS, verbose=False).write(out2, preview=False)
        names = sorted(p.name for p in self.out.iterdir() if p.is_file())
        self.assertEqual(names, sorted(p.name for p in out2.iterdir() if p.is_file()))
        for n in names:
            self.assertEqual((self.out / n).read_bytes(), (out2 / n).read_bytes(), n)

    @unittest.skipUnless(shutil.which("ca65"), "ca65 not installed")
    def test_include_assembles(self):
        src = self.tmp / "inc_test.s"
        src.write_text('.include "doomdata.inc"\n.byte DD_DIR_BANK\n.word DD_TEXDIR\n'
                       ".word TEX_SIZE, SEG_FRONTSECTOR, SPR_POSS\nDD_FILE_TABLE\n")
        r = subprocess.run(["ca65", "-I", str(self.out), "-o", str(self.tmp / "inc_test.o"),
                            str(src)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("cc65"), "cc65 not installed")
    def test_header_compiles(self):
        src = self.tmp / "h_test.c"
        src.write_text('#include "doomdata.h"\n'
                       "int f(unsigned char c) {\n"
                       "  switch (c) {\n"      # a wrong size makes two "case 0"
                       "  case 0: case sizeof(linedef_t) - LINEDEF_SIZE + 1:\n"
                       "  case sizeof(map_t) - MAP_SIZE + 2: case sizeof(tex_t) - TEX_SIZE + 3:\n"
                       "  case sizeof(seg_t) - SEG_SIZE + 4: break;\n"
                       "  }\n"
                       "  return DD_NUM_TEXTURES + SPR_TROO;\n"
                       "}\n")
        r = subprocess.run(["cc65", "-I", str(self.out), "-o", str(self.tmp / "h_test.s"),
                            str(src)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
