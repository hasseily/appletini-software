#!/usr/bin/env python3
"""Build checks for the game module (main.c, game.c, game.h, prodos_quit.s).

This is not a simulation. It runs the real cc65 toolchain on the game
sources and checks that:

  1. every C file compiles with the project flags and prints no warning,
  2. prodos_quit.s assembles,
  3. every function the C code calls, every extern it reads and every
     SPR_/SFX_/SAY_/MUSIC_/EV_/ST_/IN_/C_ constant it uses is declared in
     bosco.h (or in game.h / the C files themselves),
  4. every MAILBOX-> field used exists in struct Mailbox,
  5. (only when ld65 is available) the objects link against a stub that
     exports the bosco.h symbols, so no symbol is misspelled.

Run:  python3 tests/test_game_logic.py        (from the project directory)
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

C_FILES = ["main.c", "game.c"]
ASM_FILES = ["prodos_quit.s"]
HEADERS = ["bosco.h", "game.h"]

C_FLAGS = ["-t", "none", "--cpu", "65c02", "--standard", "c99", "-Oirs", "-c"]
ASM_FLAGS = ["-t", "none", "--cpu", "65c02", "-c"]

C_KEYWORDS = {
    "if", "for", "while", "switch", "return", "sizeof", "case", "do", "else",
    "defined",
}

# externs bosco.h declares as variables (checked by name)
PREFIXES = ("SPR_", "SFX_", "SAY_", "MUSIC_", "EV_", "ST_", "IN_", "C_")


def read(name):
    with open(os.path.join(ROOT, name)) as f:
        return f.read()


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def strip_strings(text):
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def declared_functions(header):
    """Names of the functions a header declares (prototype lines)."""
    names = set()
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*;", strip_comments(header)):
        names.add(m.group(1))
    return names


def declared_externs(header):
    names = set()
    for m in re.finditer(r"\bextern\b[^;]*?\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;",
                         strip_comments(header)):
        names.add(m.group(1))
    return names


def defined_functions(source):
    """Functions defined (with a body) in a C file."""
    names = set()
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", strip_comments(source)):
        names.add(m.group(1))
    return names


def called_functions(source):
    text = strip_strings(strip_comments(source))
    names = set()
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", text):
        n = m.group(1)
        if n not in C_KEYWORDS:
            names.add(n)
    return names


def defines(header):
    return set(re.findall(r"^\s*#define\s+([A-Za-z_]\w*)", header, flags=re.M))


class ToolchainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="bosco_game_")
        cls.cl65 = shutil.which("cl65")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, args):
        proc = subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        return proc.returncode, proc.stdout

    def test_c_files_compile_without_warnings(self):
        if not self.cl65:
            self.skipTest("cl65 not installed")
        for name in C_FILES:
            obj = os.path.join(self.tmp, name[:-2] + ".o")
            rc, out = self._run([self.cl65] + C_FLAGS + ["-o", obj, name])
            self.assertEqual(rc, 0, "%s failed to compile:\n%s" % (name, out))
            self.assertEqual(out.strip(), "", "%s printed warnings:\n%s" % (name, out))
            self.assertTrue(os.path.exists(obj))

    def test_asm_files_assemble(self):
        if not self.cl65:
            self.skipTest("cl65 not installed")
        for name in ASM_FILES:
            obj = os.path.join(self.tmp, name[:-2] + ".o")
            rc, out = self._run([self.cl65] + ASM_FLAGS + ["-o", obj, name])
            self.assertEqual(rc, 0, "%s failed to assemble:\n%s" % (name, out))
            self.assertEqual(out.strip(), "", "%s printed warnings:\n%s" % (name, out))

    def test_link_against_stub(self):
        if not self.cl65 or not shutil.which("ld65"):
            self.skipTest("ld65 not installed")
        bosco = read("bosco.h")
        funcs = declared_functions(bosco)
        variables = declared_externs(bosco)
        stub = [".export " + ",".join("_" + n for n in sorted(funcs))]
        stub.append(".export " + ",".join("_" + n for n in sorted(variables)))
        stub.append(".code")
        for n in sorted(funcs):
            stub.append("_%s:" % n)
        stub.append("        rts")
        stub.append(".bss")
        for n in sorted(variables):
            stub.append("_%s: .res 8" % n)
        cfg = """
SYMBOLS {
    __STACKSIZE__:  type = weak, value = $0800;
    __STACKSTART__: type = weak, value = $BF00;
}
MEMORY {
    ZP:   file = "", define = yes, start = $0080, size = $0020;
    LOW:  file = "", define = yes, start = $0C00, size = $1400;
    MAIN: file = %O, define = yes, start = $2000, size = $9700;
}
SEGMENTS {
    ZEROPAGE: load = ZP,   type = zp;
    STARTUP:  load = MAIN, type = ro,  optional = yes;
    ONCE:     load = MAIN, type = ro,  optional = yes;
    CODE:     load = MAIN, type = ro;
    RODATA:   load = MAIN, type = ro;
    DATA:     load = MAIN, run = LOW, type = rw, define = yes;
    BSS:      load = LOW,  type = bss, define = yes;
}
FEATURES {
    CONDES: type = constructor, label = __CONSTRUCTOR_TABLE__, count = __CONSTRUCTOR_COUNT__, segment = ONCE;
    CONDES: type = destructor, label = __DESTRUCTOR_TABLE__, count = __DESTRUCTOR_COUNT__, segment = RODATA;
}
"""
        stub_s = os.path.join(self.tmp, "stub.s")
        cfg_path = os.path.join(self.tmp, "stub.cfg")
        with open(stub_s, "w") as f:
            f.write("\n".join(stub) + "\n")
        with open(cfg_path, "w") as f:
            f.write(cfg)
        objs = []
        for name in C_FILES:
            obj = os.path.join(self.tmp, "link_" + name[:-2] + ".o")
            rc, out = self._run([self.cl65] + C_FLAGS + ["-o", obj, name])
            self.assertEqual(rc, 0, out)
            objs.append(obj)
        for name in ASM_FILES:
            obj = os.path.join(self.tmp, "link_" + name[:-2] + ".o")
            rc, out = self._run([self.cl65] + ASM_FLAGS + ["-o", obj, name])
            self.assertEqual(rc, 0, out)
            objs.append(obj)
        stub_o = os.path.join(self.tmp, "stub.o")
        rc, out = self._run([self.cl65] + ASM_FLAGS + ["-o", stub_o, stub_s])
        self.assertEqual(rc, 0, out)
        binary = os.path.join(self.tmp, "link.bin")
        rc, out = self._run([self.cl65, "-t", "none", "--cpu", "65c02", "-C", cfg_path,
                             "-o", binary] + objs + [stub_o])
        self.assertEqual(rc, 0, "link against the bosco.h stub failed:\n" + out)


class InterfaceTest(unittest.TestCase):
    def setUp(self):
        self.bosco = read("bosco.h")
        self.game_h = read("game.h")
        self.sources = {name: read(name) for name in C_FILES}

    def test_every_called_function_is_declared(self):
        known = declared_functions(self.bosco) | declared_functions(self.game_h)
        known |= {"prodos_quit", "REG8", "MAILBOX"}
        for src in self.sources.values():
            known |= defined_functions(src)
            known |= declared_functions(src)
        for name, src in self.sources.items():
            missing = sorted(called_functions(src) - known)
            self.assertEqual(missing, [], "%s calls undeclared functions: %s" % (name, missing))

    def test_used_externs_exist(self):
        bosco_vars = declared_externs(self.bosco)
        for var in ("dl_items", "dl_count", "star_x", "star_y", "star_color",
                    "star_count", "video_frame_writes", "sound_current_sfx",
                    "sound_current_track", "speech_current", "spr_width", "spr_height"):
            self.assertIn(var, bosco_vars, "bosco.h no longer declares " + var)
        game_vars = declared_externs(self.game_h)
        defined = set()
        for src in self.sources.values():
            defined |= set(re.findall(r"^\s*(?:u8|s8|u16|s16|u32)\s+([A-Za-z_]\w*)",
                                      strip_comments(src), flags=re.M))
            defined |= set(re.findall(r"^\s*(?:u8|s8|u16|s16|u32)\s+[^;]*?,\s*([A-Za-z_]\w*)\s*;",
                                      strip_comments(src), flags=re.M))
        missing = sorted(game_vars - defined)
        self.assertEqual(missing, [], "game.h externs without a definition: %s" % missing)

    def test_constants_come_from_bosco_h(self):
        known = defines(self.bosco) | defines(self.game_h)
        for name, src in self.sources.items():
            used = set()
            for m in re.finditer(r"\b((?:%s)[A-Z0-9_]+)\b" % "|".join(PREFIXES),
                                 strip_strings(strip_comments(src))):
                used.add(m.group(1))
            missing = sorted(used - known)
            self.assertEqual(missing, [], "%s uses unknown constants: %s" % (name, missing))

    def test_mailbox_fields_exist(self):
        m = re.search(r"struct Mailbox\s*\{(.*?)\};", strip_comments(self.bosco), flags=re.S)
        self.assertIsNotNone(m, "struct Mailbox missing from bosco.h")
        fields = set(re.findall(r"\b([A-Za-z_]\w*)\s*(?:\[\d+\])?\s*;", m.group(1)))
        for name, src in self.sources.items():
            used = set(re.findall(r"MAILBOX->([A-Za-z_]\w*)", src))
            missing = sorted(used - fields)
            self.assertEqual(missing, [], "%s uses unknown mailbox fields: %s" % (name, missing))
        # every field in the struct is written by mailbox_tick or mailbox_init
        used = set(re.findall(r"MAILBOX->([A-Za-z_]\w*)", self.sources["main.c"]))
        unused = sorted(fields - used)
        self.assertEqual(unused, [], "mailbox fields never written: %s" % unused)

    def test_frame_order_in_main_loop(self):
        text = strip_comments(self.sources["main.c"])
        loop = text[text.index("for (;;)"):]
        order = ["video_wait_vbl", "input_keys", "video_render", "sound_update", "mailbox_tick"]
        positions = [loop.index(n) for n in order]
        self.assertEqual(positions, sorted(positions), "main loop order is wrong")

    def test_prodos_quit_helper(self):
        asm = read("prodos_quit.s")
        self.assertIn(".export _prodos_quit", asm)
        self.assertRegex(asm, r"jsr\s+(MLI|\$BF00)")
        self.assertRegex(asm, r"\.byte\s+\$65")


if __name__ == "__main__":
    unittest.main(verbosity=2)
