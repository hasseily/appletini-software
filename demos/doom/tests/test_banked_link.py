#!/usr/bin/env python3
"""Bounded regressions for banked-link packaging and partition boundaries."""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import bank_game
import check_link


class BankedLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="doom-link-")
        self.addCleanup(self.tmp.cleanup)
        self.build = Path(self.tmp.name)
        b = self.build
        (b / "banks").mkdir()
        metadata = {"format": 1, "banks": {"control": 96}, "game_home": 125,
                    "render_home": 122, "packet_bank": 124, "packet_address": 512,
                    "tables_bank": 127, "info_bank": 1, "preload_file": "DOOM.BANKS",
                    "code_staging": {"96": 96}}
        (b / "banked.json").write_text(json.dumps(metadata))
        (b / "banks/banks.json").write_text(json.dumps({
            "format": 1, "banks": metadata["banks"], "code_staging": metadata["code_staging"],
            "lc_packet": {"bank": 96, "segment": "GVIEW", "bytes": 2600},
            "entries": [{"public": "function", "private": "body", "group": "control"}]}))
        (b / "doom-banked.cfg").write_text('''MEMORY {
    GAME: file = "%OGAME.BIN", start = $0200, size = $B180;
    ISCRATCH: file = "", start = $B380, size = $0480, type = rw, define = yes;
    GZPMEM: file = "", start = $0040, size = $0008;
    TABLES: file = "%OGAME.TABLES", start = $0200, size = $BDF0;
    INFO: file = "%OGAME.INFO", start = $6000, size = $1000;
    LOADER: file = "%ODOOM.SYSTEM", start = $2000, size = $2000;
    RMAIN: file = "%ORENDER.BIN", start = $0200, size = $8980;
    LC2: file = "%OLC.BIN", start = $D000, size = $1000, fill = yes;
    LCHI: file = "%OLC.BIN", start = $E000, size = $1FFA, fill = yes;
    LCVEC: file = "%OLC.BIN", start = $FFFA, size = $0006, fill = yes;
    LC1: file = "%OLC.BIN", start = $D000, size = $1000, fill = yes;
    GB96: file = "%OGBANK96.BIN", start = $D000, size = $2FFA, fill = yes;
    GBV96: file = "%OGBANK96.BIN", start = $FFFA, size = $0006, fill = yes;
}
SEGMENTS {
    GBSTUBS: load = GAME, type = ro;
    GBANKCODE: load = GAME, type = rw;
    BSS: load = GAME, type = bss;
    GINTERCEPTS: load = ISCRATCH, type = bss, define = yes;
    GFAR: load = TABLES, type = ro;
    GINFO: load = INFO, type = ro;
    LDRCODE: load = LOADER, type = ro;
    RCODE: load = RMAIN, type = ro;
    KJT: load = LCHI, type = ro;
    KVECTORS: load = LCVEC, type = ro;
    GB96: load = GB96, type = ro;
    GBV96: load = GBV96, type = ro;
    GVIEW: load = GB96, type = bss;
}
''')
        self.segments = {"GBSTUBS": (0x200, 6), "GBANKCODE": (0x206, 26),
                         "BSS": (0x1000, 0x0B80), "GINTERCEPTS": (0xB380, 0x0480),
                         "GFAR": (0x200, 2),
                         "GINFO": (0x6000, 34), "LDRCODE": (0x2000, 32),
                         "RCODE": (0x200, 1), "KJT": (0xE000, 3),
                         "KVECTORS": (0xFFFA, 6), "GB96": (0xD000, 32),
                         "GBV96": (0xFFFA, 6), "GVIEW": (0xD020, 2600)}
        self.write_map()
        self.labels = {"gb_call": 0x206, "gb_irq": 0x20A, "gb_nmi": 0x20B,
                  "function": 0x200, "body": 0xD000, "__STACKSTART__": 0xC000,
                  "__STACKSIZE__": 0x800, "__BSS_RUN__": 0x1000, "__BSS_SIZE__": 0x0B80,
                  "_arena_bounds": 0x210, "_intercepts": 0xB380,
                  "__GINTERCEPTS_RUN__": 0xB380, "__GINTERCEPTS_SIZE__": 0x480,
                  "__ISCRATCH_START__": 0xB380, "__ISCRATCH_SIZE__": 0x480,
                  "CODE_BANK_COUNT": 1, "lc_install_sources": 0x2008,
                  "lc_install_targets": 0x2010,
                  "_rview": 0xD020, "__GVIEW_RUN__": 0xD020, "__GVIEW_SIZE__": 2600}
        self.write_labels()
        game = bytearray(b"\x20\x06\x02\x60\x00\xD0" + b"\xEA" * 26)
        game[0x10:0x1A] = struct.pack("<HHHHH", 0x1B80, 0xB380, 0, 0, 0)
        (b / "GAME.BIN").write_bytes(game)
        (b / "GAME.TABLES").write_bytes(b"\x01\x02")
        (b / "GAME.INFO").write_bytes(bytes(34))
        loader = bytearray(32)
        loader[0], loader[8], loader[16] = 0xD8, 96, 96
        (b / "DOOM.SYSTEM").write_bytes(loader)
        (b / "RENDER.BIN").write_bytes(b"\x60")
        lc = bytearray(0x4000)
        lc[0x1000] = 0x4C
        lc[0x2FFE:0x3000] = b"\x00\xD0"
        (b / "LC.BIN").write_bytes(lc)
        bank = bytearray(0x3000)
        bank[-6:] = struct.pack("<HHH", 0x20B, 0, 0x20A)
        (b / "GBANK96.BIN").write_bytes(bank)
        payloads = [(96, 0x200, bank), (127, 0x200, b"\x01\x02"), (1, 0x6000, bytes(34))]
        header = bytearray(b"A2DM\x01\x03\0\0")
        for bank, address, data in payloads:
            header += struct.pack("<BHH", bank, address, len(data))
        (b / "DOOM.BANKS").write_bytes(bytes(header).ljust(256, b"\0") + b"".join(p[2] for p in payloads))

    def write_map(self):
        text = "Segment list:\n-------------\nName Start End Size Align\n"
        for name, (start, size) in self.segments.items():
            text += f"{name} {start:06X} {start+size-1:06X} {size:06X} 00001\n"
        (self.build / "doom.map").write_text(text + "Exports list by name:\n")

    def errors(self):
        return check_link.banked_report(self.build)[1]

    def write_labels(self):
        (self.build / "doom.lbl").write_text("".join(
            f"al {value:06X} .{name}\n" for name, value in self.labels.items()))

    def use_base_control(self):
        for name in ("banked.json", "banks/banks.json"):
            path = self.build / name
            data = json.loads(path.read_text())
            data["banks"]["control"] = 0
            data["code_staging"] = {"0": 96}
            if "lc_packet" in data:
                data["lc_packet"]["bank"] = 0
            path.write_text(json.dumps(data))
        p = self.build / "doom-banked.cfg"
        p.write_text(p.read_text().replace("GBANK96", "GBANK0")
                     .replace("GBV96", "GBV0").replace("GB96", "GB0"))
        self.segments["GB0"] = self.segments.pop("GB96")
        self.segments["GBV0"] = self.segments.pop("GBV96")
        self.write_map()
        (self.build / "GBANK96.BIN").rename(self.build / "GBANK0.BIN")
        p = self.build / "GAME.BIN"
        game = bytearray(p.read_bytes())
        game[3] = 0
        p.write_bytes(game)
        p = self.build / "DOOM.SYSTEM"
        loader = bytearray(p.read_bytes())
        loader[16] = 0
        p.write_bytes(loader)

    def add_memory_api(self):
        path = self.build / "banked.json"
        metadata = json.loads(path.read_text())
        metadata["memory_api_optional"] = True
        path.write_text(json.dumps(metadata))
        names = ("AMEMCOPY", "AMEMPROBE", "AMEMFILL")
        path = self.build / "doom-banked.cfg"
        cfg = path.read_text().replace("MEMORY {", "MEMORY {\n"
            '    AMEMSTORE: file = "%OAMEM.BIN", start = $B800, size = $0300;\n' +
            "".join(f'    {name}RUN: file = "", start = $E100, size = $0100;\n'
                    for name in names))
        cfg = cfg.replace("SEGMENTS {", "SEGMENTS {\n" + "".join(
            f"    {name}: load = AMEMSTORE, run = {name}RUN, type = rw;\n" for name in names))
        path.write_text(cfg)
        self.labels.update(kbuf=0xE100, __KBSS_RUN__=0xE100, __KBSS_SIZE__=0x100)
        for i, name in enumerate(names):
            self.segments[name] = (0xE100, 256)
            self.labels[f"__{name}_LOAD__"] = 0xB800 + 256*i
        self.write_map()
        self.write_labels()
        blob = bytes(range(256))*3
        (self.build / "AMEM.BIN").write_bytes(blob)
        path = self.build / "DOOM.BANKS"
        package = bytearray(path.read_bytes())
        count = package[5]
        package[8+5*count:13+5*count] = struct.pack("<BHH", 122, 0xB800, len(blob))
        package[5] += 1
        path.write_bytes(package + blob)

    def test_memory_api_overlays_use_kbuf_and_exact_preloaded_bytes(self):
        self.add_memory_api()
        self.assertEqual(self.errors(), [])
        path = self.build / "AMEM.BIN"
        blob = bytearray(path.read_bytes())
        blob[10] ^= 1
        path.write_bytes(blob)
        self.assertTrue(any("stale preload" in error for error in self.errors()))

    def test_memory_api_overlay_cannot_leave_kbuf_or_backing_tail(self):
        self.add_memory_api()
        self.labels["__AMEMCOPY_LOAD__"] = 0x8800
        self.write_labels()
        self.assertTrue(any("immutable backing address" in error for error in self.errors()))
        self.labels["__AMEMCOPY_LOAD__"] = 0xB800
        self.labels["__KBSS_SIZE__"] = 255
        self.write_labels()
        self.assertTrue(any("resident 256-byte kbuf" in error for error in self.errors()))
        self.labels["__KBSS_SIZE__"] = 256
        self.segments["AMEMFILL"] = (0xE101, 256)
        self.write_map()
        self.write_labels()
        self.assertTrue(any("overlay extent" in error for error in self.errors()))

    def test_consistent_link_and_arena_include_bss_and_gaps(self):
        report, errors = check_link.banked_report(self.build)
        self.assertEqual(errors, [])
        # Moving 1152 bytes out of ordinary BSS and below the stack must
        # preserve the arena capacity it had before the relocation.
        self.assertEqual(report["main_arena"]["bytes"], 0xB800 - 0x2000)
        self.assertEqual(report["main_arena"]["end"], 0xB380)
        self.assertEqual(report["main_arena"]["stack_bytes"], 0x800)
        self.assertEqual(report["GAME"]["occupied"], 0x1B80 - 0x200)
        self.assertEqual(report["ISCRATCH"]["used"], 1152)
        self.assertEqual(report["ISCRATCH"]["free"], 0)
        self.assertEqual(report["GB96"]["used"], 32 + 2600)
        self.assertEqual(report["lc_packet"]["start"], 0xD020)

    def test_packet_requires_complete_lc_storage_and_matching_pointer(self):
        self.segments["GVIEW"] = (0xF800, 2599)
        self.write_map()
        errors = self.errors()
        self.assertTrue(any("complete 2600-byte" in error for error in errors))
        self.assertTrue(any("before LC vectors" in error for error in errors))
        self.assertTrue(any("_rview does not point" in error for error in errors))

    def test_base_auxiliary_control_uses_distinct_preload_staging_bank(self):
        self.use_base_control()
        report, errors = check_link.banked_report(self.build)
        self.assertEqual(errors, [])
        self.assertEqual(report["lc_packet"]["bank"], 0)
        self.assertEqual(report["banked"]["code_staging"], {"0": 96})
        p = self.build / "DOOM.BANKS"
        package = bytearray(p.read_bytes())
        package[8] = 0
        p.write_bytes(package)
        self.assertTrue(any("unexpected segment 0:$0200" in error for error in self.errors()))

    def test_only_control_can_run_in_base_auxiliary(self):
        self.use_base_control()
        p = self.build / "banked.json"
        data = json.loads(p.read_text())
        data["banks"] = {"weapons": 0}
        p.write_text(json.dumps(data))
        self.assertTrue(any("only control optionally resident" in error for error in self.errors()))

    def test_staging_inventory_cannot_be_missing_or_stale(self):
        p = self.build / "banked.json"
        data = json.loads(p.read_text())
        data.pop("code_staging")
        p.write_text(json.dumps(data))
        self.assertTrue(any("name exactly every runtime code bank" in error for error in self.errors()))
        data["code_staging"] = {"96": 97}
        p.write_text(json.dumps(data))
        errors = self.errors()
        self.assertTrue(any("stale code staging" in error for error in errors))
        self.assertTrue(any("same staging bank" in error for error in errors))

    def test_staging_banks_must_be_safe_distinct_and_contiguous(self):
        p = self.build / "banked.json"
        data = json.loads(p.read_text())
        for staging in ({"96": 0}, {"96": 122}, {"96": 96, "97": 96},
                        {"96": 96, "98": 98}):
            with self.subTest(staging=staging):
                data["code_staging"] = staging
                p.write_text(json.dumps(data))
                self.assertTrue(any("staging banks must" in error for error in self.errors()))

    def test_loader_tables_must_match_runtime_and_staging_inventory(self):
        self.use_base_control()
        p = self.build / "DOOM.SYSTEM"
        original = p.read_bytes()
        for offset, wrong in ((8, 0), (16, 96)):
            with self.subTest(offset=offset):
                loader = bytearray(original)
                loader[offset] = wrong
                p.write_bytes(loader)
                self.assertTrue(any("LC installation tables disagree" in error for error in self.errors()))
        p.write_bytes(original)
        self.labels["CODE_BANK_COUNT"] = 2
        self.write_labels()
        self.assertTrue(any("CODE_BANK_COUNT" in error for error in self.errors()))
        self.labels["CODE_BANK_COUNT"] = 1
        self.labels["lc_install_sources"] = 0xFFFF
        self.write_labels()
        self.assertTrue(any("outside the loader image" in error for error in self.errors()))

    def test_packet_cannot_be_assigned_to_main_or_missing(self):
        p = self.build / "doom-banked.cfg"
        p.write_text(p.read_text().replace("GVIEW: load = GB96", "GVIEW: load = GAME"))
        self.assertTrue(any("BSS in the control LC bank" in error for error in self.errors()))
        del self.segments["GVIEW"]
        self.write_map()
        self.assertTrue(any("complete 2600-byte" in error for error in self.errors()))

    def test_intercepts_must_fit_reserved_nonvideo_window(self):
        for start, size in ((0x2000, 1152), (0xB380, 1151), (0xB380, 1153)):
            with self.subTest(start=start, size=size):
                self.segments["GINTERCEPTS"] = (start, size)
                self.write_map()
                errors = self.errors()
                self.assertTrue(any("GINTERCEPTS" in error for error in errors))
                self.assertTrue(any("stack boundary" in error for error in errors))

    def test_intercept_segment_requires_dedicated_bss_and_cannot_be_missing(self):
        p = self.build / "doom-banked.cfg"
        original = p.read_text()
        for replacement in ("load = GAME, type = bss, define = yes",
                            "load = ISCRATCH, type = ro, define = yes",
                            "load = ISCRATCH, type = bss, define = no"):
            with self.subTest(assignment=replacement):
                p.write_text(original.replace("load = ISCRATCH, type = bss, define = yes", replacement))
                self.assertTrue(any("defined BSS in the dedicated ISCRATCH" in error
                                    for error in self.errors()))
        p.write_text(original)
        del self.segments["GINTERCEPTS"]
        self.write_map()
        self.assertTrue(any("complete 1152-byte" in error for error in self.errors()))

    def test_intercept_labels_and_memory_declaration_must_match(self):
        for name in ("_intercepts", "__GINTERCEPTS_RUN__", "__GINTERCEPTS_SIZE__",
                     "__ISCRATCH_START__", "__ISCRATCH_SIZE__"):
            with self.subTest(label=name):
                self.labels[name] += 1
                self.write_labels()
                self.assertTrue(any("intercepts does not point" in error or
                                    "map and label values disagree" in error or
                                    "configuration and label values disagree" in error
                                    for error in self.errors()))
                self.labels[name] -= 1
        self.write_labels()
        p = self.build / "doom-banked.cfg"
        original = p.read_text()
        for replacement in ('file = "%OSCRATCH.BIN"', "type = ro", "define = no"):
            with self.subTest(memory_property=replacement):
                declaration = 'file = "", start = $B380, size = $0480, type = rw, define = yes'
                needle = ('file = ""' if replacement.startswith("file") else
                          "type = rw" if replacement.startswith("type") else "define = yes")
                p.write_text(original.replace(declaration, declaration.replace(needle, replacement)))
                self.assertTrue(any("ISCRATCH must be defined writable RAM" in error
                                    for error in self.errors()))

    def test_arena_cannot_reclaim_intercepts_or_reduce_software_stack(self):
        p = self.build / "GAME.BIN"
        game = bytearray(p.read_bytes())
        game[0x12:0x14] = struct.pack("<H", 0xB800)  # stale pre-relocation arena end
        p.write_bytes(game)
        self.assertTrue(any("arena bounds" in error for error in self.errors()))
        self.labels["__STACKSIZE__"] = 0x0400
        self.write_labels()
        self.assertTrue(any("2048-byte software stack" in error for error in self.errors()))

    def test_arena_bounds_label_is_required(self):
        del self.labels["_arena_bounds"]
        self.write_labels()
        self.assertTrue(any("arena bounds label is missing" in error for error in self.errors()))

    def test_preload_must_match_current_image_bytes(self):
        p = self.build / "DOOM.BANKS"
        contents = bytearray(p.read_bytes())
        contents[256] ^= 1
        p.write_bytes(contents)
        self.assertTrue(any("stale preload" in error for error in self.errors()))

    def test_vectors_and_entry_descriptors_are_checked(self):
        p = self.build / "GBANK96.BIN"
        contents = bytearray(p.read_bytes())
        contents[-1] ^= 1
        p.write_bytes(contents)
        p = self.build / "GAME.BIN"
        contents = bytearray(p.read_bytes())
        contents[3] = 97
        p.write_bytes(contents)
        errors = self.errors()
        self.assertTrue(any("vectors" in error for error in errors))
        self.assertTrue(any("descriptor" in error for error in errors))

    def test_overflow_and_stale_bank_files_fail(self):
        self.segments["GB96"] = (0xD000, 0x3000)
        self.segments["BSS"] = (0x1000, 0xA800)
        self.write_map()
        (self.build / "GBANK97.BIN").write_bytes(bytes(0x3000))
        errors = self.errors()
        self.assertTrue(any("exceeds GB96" in error for error in errors))
        self.assertTrue(any("stale code-bank" in error for error in errors))
        self.assertTrue(any("main arena" in error for error in errors))

    def test_truncated_images_and_preload_are_rejected(self):
        for name in ("GAME.INFO", "DOOM.BANKS"):
            p = self.build / name
            p.write_bytes(p.read_bytes()[:-1])
        errors = self.errors()
        self.assertTrue(any("map/config require" in error for error in errors))
        self.assertTrue(any("truncated" in error for error in errors))


class PartitionRegressionTest(unittest.TestCase):
    def test_static_loop_moves_without_changing_actor_call_context(self):
        source = '''.export _P_RunStatics
.segment "CODE"
st_tics_of: rts
_P_RunStatics:
@loop: jsr st_tics_of
       bne :+
:      nop
       jsr may_wake
       jsr cold_action
       bne @loop
       rts
may_wake: rts
cold_action: rts
caller: jsr _P_RunStatics
        rts
'''
        lines = bank_game.segments("a_mobj", source)
        own = bank_game.entries("a_mobj", lines, {"_P_RunStatics"})
        self.assertEqual(set(own), {"_P_RunStatics"}, "local helpers must not acquire gates")
        self.assertEqual(own["_P_RunStatics"].group, "actors")
        result = bank_game.transform("a_mobj", lines, own, {}, {"actors": 97}, {})
        self.assertIn('gbbody_a_mobj__P_RunStatics:\n'
                      '    jmp gbmain_a_mobj__P_RunStatics\n'
                      '.segment "CODE"\ngbmain_a_mobj__P_RunStatics:', result)
        body, tail = result.split('gbmain_a_mobj__P_RunStatics:', 1)[1].split(
            '.segment "GB97"', 1)
        self.assertIn('@loop: jsr st_tics_of', body)
        self.assertIn('jsr may_wake', body)
        self.assertIn('jsr cold_action', body)
        self.assertIn('bne @loop', body)
        self.assertIn('may_wake: rts', tail)
        self.assertIn('caller: jsr gbbody_a_mobj__P_RunStatics', tail)
        self.assertNotIn('gbptr_', result)

    def test_static_loop_extraction_rejects_changed_scope_or_missing_boundary(self):
        for body in ('_P_RunStatics: rts\n',
                     '_P_RunStatics: rts\nnew_helper: rts\nmay_wake: rts\n',
                     '_P_RunStatics: rts\n.segment "BSS"\nmay_wake: rts\n'):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, 'P_RunStatics'):
                bank_game.segments("a_mobj", '.segment "CODE"\n' + body)

    def test_partition_cannot_use_renderer_backing_bank(self):
        with tempfile.TemporaryDirectory(prefix="doom-bank-range-") as directory:
            base = Path(directory)
            (base / "doomdata.inc").write_text("DD_LAST_BANK = 95\n")
            args = SimpleNamespace(source=base, data=base, out=base / "out", first_bank=116)
            with self.assertRaisesRegex(ValueError, r"platform banks \(122\.\.127\)"):
                bank_game.prepare(args)

    def test_private_call_between_runtime_and_setup_uses_gate(self):
        source = '''.segment "CODE"
far_to: rts
runtime: jsr far_to
         rts
.segment "GOVL"
setup: jsr far_to
       rts
'''
        lines = bank_game.segments("a_spec", source)
        own = bank_game.entries("a_spec", lines, set())
        result = bank_game.transform("a_spec", lines, own, {}, {"specials": 99, "setup": 101}, {})
        self.assertIn("runtime: jsr gbbody_a_spec_far_to", result)
        self.assertIn("setup: jsr gbptr_a_spec_far_to", result)

    def test_new_shared_cache_exports_are_namespaced(self):
        sources = {"a_levdata": '''.export line_get, rp_x
.segment "BSS"
nodebuf: .res 32
rp_x: .res 4
.segment "CODE"
line_get: lda nodebuf
          rts
'''}
        clones = bank_game.clone_level_accessors(sources, {"collision": 96})
        self.assertIn("a_levdata_g96", clones)
        self.assertIn("gbshared_levdata_nodebuf: .res 32", sources["a_levdata"])
        self.assertIn("rp_x: .res 4", sources["a_levdata"])
        self.assertIn("lda gbshared_levdata_nodebuf", sources["a_levdata_g96"])


if __name__ == "__main__":
    unittest.main()
