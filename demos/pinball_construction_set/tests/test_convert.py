#!/usr/bin/env python3
"""Check tools/merlin2ca65.py against the upstream binaries and the port's
patch files (docs/DESIGN.md section 5).

Run:  python3 tests/test_convert.py        (from the project directory)

Baseline layout: the converter is run with --layout baseline into a
temporary directory, every module is assembled with ca65 and linked with
ld65 at its original ORG, and the binaries are compared with the sizes
and MD5 checksums of the upstream programs (the nine modules of
https://github.com/billbudge/PCS_AppleII assembled by Merlin). Port
layout: the converter is run with the real drops, patches and exports, the
six converted modules must assemble, and every patch's "expect" line must
still be the upstream line it names (drift there would silently change
what the port runs). The upstream clone is looked for where the Makefile
looks (upstream/ in the tree, then /home/user/billbudge/pcs_appleii, or
$UPSTREAM); without it, or without ca65/ld65, the tests are skipped.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
SRC = PROJECT / "src"
BUILD = PROJECT / "build"
CONVERTER = TOOLS / "merlin2ca65.py"

sys.path.insert(0, str(TOOLS))
import merlin2ca65  # noqa: E402

CA65 = os.environ.get("CA65", "ca65")
LD65 = os.environ.get("LD65", "ld65")


def find_upstream() -> Path | None:
    candidates = [os.environ.get("UPSTREAM"), PROJECT / "upstream", "/home/user/billbudge/pcs_appleii"]
    for c in candidates:
        if c and (Path(c) / "source_disc1" / "EDIT.S").exists():
            return Path(c)
    return None


UPSTREAM = find_upstream()
HAVE_TOOLS = shutil.which(CA65) is not None and shutil.which(LD65) is not None

# the upstream programs as Merlin assembled them: module -> (size, md5)
BASELINE = {
    "BOOT2": (253, "c187498da43119f1a0d98edf21399517"),
    "CDRAW": (1641, "0f33718102e5005119f0357e8e33c600"),
    "DISK": (1922, "2886353c08d8f24bd736eb895ebeb003"),
    "EDIT": (5100, "b68db440504cf9ee601f6875f181fbd1"),
    "PPAK": (1731, "626429577fb6997c2c8fbe9dbde060a5"),
    "RUN": (5907, "45567bbdac1cfb04154197a316ca03fd"),
    "RUN2": (2389, "86d1d1bb85291ae0f078b96fe59dffa7"),
    "SWAP": (251, "fccffc2a3ba3e9848c68137f89e5f162"),
    "WIRE": (2316, "4ac167fdec5bbd57440a5c8c05fff6e4"),
}
PORT_MODULES = ["CDRAW", "EDIT", "PPAK", "RUN", "RUN2", "WIRE"]
# the patch files the Makefile passes, in its order
PATCH_FILES = [SRC / "patches.json", BUILD / "layout_patches.json", BUILD / "kind_patches.json"]


def run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def assemble_at_org(source: Path, org: int) -> Path:
    """Assemble one converted module standalone at ORG and return the binary."""
    obj = source.with_suffix(".o")
    cfg = source.with_suffix(".cfg")
    binary = source.with_suffix(".bin")
    cfg.write_text("MEMORY { M: start=$%04X, size=$%04X, file=%%O; }\n"
                   "SEGMENTS { CODE: load=M, type=rw; }\n" % (org, 0x10000 - org))
    r = run([CA65, "-g", "-o", obj, source])
    if r.returncode:
        raise AssertionError(f"ca65 failed on {source.name}:\n{r.stderr}")
    r = run([LD65, "-C", cfg, "-o", binary, obj])
    if r.returncode:
        raise AssertionError(f"ld65 failed on {source.name}:\n{r.stderr}")
    return binary


def org_of(source: Path) -> int:
    for line in source.read_text().splitlines():
        if line.startswith(".org "):
            return int(line.split("$")[1], 16)
    raise AssertionError(f"{source.name} has no .org line")


@unittest.skipUnless(UPSTREAM, "upstream clone of PCS_AppleII not found (set UPSTREAM)")
@unittest.skipUnless(HAVE_TOOLS, "ca65/ld65 not installed")
class TestBaseline(unittest.TestCase):
    """--layout baseline reproduces the nine upstream binaries byte for byte."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pcs_baseline_")
        cls.out = Path(cls.tmp.name)
        r = run([sys.executable, CONVERTER, UPSTREAM, "--layout", "baseline", "--output", cls.out])
        if r.returncode:
            raise AssertionError(f"converter failed:\n{r.stdout}\n{r.stderr}")
        cls.report = r.stdout

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_module_is_converted(self):
        for module in BASELINE:
            self.assertTrue((self.out / f"{module}.s").exists(), f"{module}.s missing")
            self.assertIn(module, self.report)

    def test_origins_match_the_upstream(self):
        expected = {"CDRAW": 0x1780}       # ORG HI+$C0 (HI = $16C0); the others say ORG $xxxx
        for module, path in merlin2ca65.MODULES.items():
            org = org_of(self.out / f"{module}.s")
            if module in expected:
                self.assertEqual(org, expected[module], module)
                continue
            for line in (UPSTREAM / path).read_text().splitlines():
                fields = merlin2ca65.split_fields(line)
                if fields[1] == "ORG":
                    self.assertEqual(org, int(fields[2].replace("$", ""), 16), module)
                    break
            else:
                self.fail(f"{module}: no ORG in the upstream source")

    def test_sizes_and_checksums(self):
        failures = []
        for module, (size, md5) in BASELINE.items():
            source = self.out / f"{module}.s"
            binary = assemble_at_org(source, org_of(source))
            data = binary.read_bytes()
            got = hashlib.md5(data).hexdigest()
            if len(data) != size or got != md5:
                failures.append(f"{module}: {len(data)} bytes {got} (expected {size} bytes {md5})")
        self.assertFalse(failures, "baseline binaries differ from the upstream:\n" + "\n".join(failures))

    def test_baseline_symbols_helper_agrees(self):
        """The converter's own symbol pass (used by the port layout) sees the
        same sizes."""
        with tempfile.TemporaryDirectory(prefix="pcs_syms_") as tmp:
            symbols = merlin2ca65.baseline_symbols(UPSTREAM, tmp)
        for module, (size, _md5) in BASELINE.items():
            org, end, labels = symbols[module]
            self.assertEqual(end - org, size, module)
            self.assertTrue(labels, f"{module}: no labels")
        # a few landmarks the port relies on (docs/DESIGN.md section 5)
        self.assertEqual(symbols["CDRAW"][0], 0x1780)
        self.assertIn("DOMENU", symbols["CDRAW"][2])
        self.assertIn("PLAY", symbols["RUN"][2])
        self.assertIn("DRAGO6", symbols["EDIT"][2])


@unittest.skipUnless(UPSTREAM, "upstream clone of PCS_AppleII not found (set UPSTREAM)")
class TestPatches(unittest.TestCase):
    """Every patch names the upstream line it replaces; drops name real labels."""

    def patch_files(self):
        present = [p for p in PATCH_FILES if p.exists()]
        if not present:
            self.skipTest("no patch files (run make)")
        return present

    def test_expect_lines_match_the_upstream(self):
        mismatches = []
        for path in self.patch_files():
            for p in json.loads(path.read_text()):
                lines = (UPSTREAM / merlin2ca65.MODULES[p["module"]]).read_text().splitlines()
                actual = lines[p["line"] - 1] if p["line"] <= len(lines) else "<past the end>"
                if actual.rstrip() != p["expect"].rstrip():
                    mismatches.append(f"{path.name}: {p['module']}.S line {p['line']}\n"
                                      f"    expected {p['expect']!r}\n    found    {actual!r}")
        self.assertFalse(mismatches, "patches no longer match the upstream:\n" + "\n".join(mismatches))

    def test_converter_check_passes(self):
        try:
            merlin2ca65.check_patches(UPSTREAM, self.patch_files())
        except ValueError as e:
            self.fail(f"check_patches: {e}")

    def test_patch_ranges_are_sane(self):
        for path in self.patch_files():
            for p in json.loads(path.read_text()):
                end = p.get("end", p["line"])
                self.assertGreaterEqual(end, p["line"], f"{path.name}: {p['module']}:{p['line']}")
                self.assertIsInstance(p["replace"], (str, list), f"{path.name}: {p['module']}:{p['line']}")

    def test_drops_name_labels_of_their_modules(self):
        drops = json.loads((SRC / "drops.json").read_text())
        for module, first, end in drops:
            src = (UPSTREAM / merlin2ca65.MODULES[module]).read_text().splitlines()
            labels = merlin2ca65.defined_labels(src)
            self.assertIn(first, labels, f"{module}: drop start {first}")
            if end != "__END__":
                self.assertIn(end, labels, f"{module}: drop end {end}")

    def test_exports_name_kept_labels(self):
        """Every exported label survives the drops (patches may add labels,
        such as PPAK's GETINFO)."""
        exports = json.loads((SRC / "exports.json").read_text())
        drops = merlin2ca65.load_json(SRC / "drops.json", "drops")
        patches = {}
        for path in self.patch_files():
            patches.update(merlin2ca65.load_json(path, "patches"))
        for module, names in exports.items():
            src = (UPSTREAM / merlin2ca65.MODULES[module]).read_text().splitlines()
            _org, _items, _used, local = merlin2ca65.convert_lines(
                module, src, "port",
                {first: end for (m, first), end in drops.items() if m == module},
                {ln: repl for (m, ln), repl in patches.items() if m == module})
            for name in names:
                self.assertIn(name, local, f"{module} exports {name}, which is dropped or undefined")


@unittest.skipUnless(UPSTREAM, "upstream clone of PCS_AppleII not found (set UPSTREAM)")
@unittest.skipUnless(HAVE_TOOLS, "ca65/ld65 not installed")
class TestPortLayout(unittest.TestCase):
    """--layout port converts with the real drops/patches/exports and assembles."""

    @classmethod
    def setUpClass(cls):
        missing = [p.name for p in PATCH_FILES if not p.exists()]
        if missing or not (BUILD / "assets.inc").exists():
            raise unittest.SkipTest(f"build files missing ({', '.join(missing) or 'assets.inc'}): run make")
        cls.tmp = tempfile.TemporaryDirectory(prefix="pcs_port_")
        cls.out = Path(cls.tmp.name)
        cmd = [sys.executable, CONVERTER, UPSTREAM, "--layout", "port", "--drops", SRC / "drops.json"]
        for p in PATCH_FILES:
            cmd += ["--patches", p]
        cmd += ["--exports", SRC / "exports.json", "--output", cls.out]
        r = run(cmd)
        if r.returncode:
            raise AssertionError(f"converter failed:\n{r.stdout}\n{r.stderr}")
        cls.report = r.stdout

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_modules_written_and_marked_generated(self):
        for module in PORT_MODULES:
            text = (self.out / f"{module}.s").read_text()
            self.assertTrue(text.startswith("; Generated by tools/merlin2ca65.py"), module)
            self.assertIn('.segment "CODE"', text)
            self.assertNotIn(".org", text, f"{module}: a port module must be relocatable")

    def test_exports_are_emitted(self):
        exports = json.loads((SRC / "exports.json").read_text())
        for module, names in exports.items():
            text = (self.out / f"{module}.s").read_text()
            for name in names:
                self.assertIn(f".export {module}_{name} = {name}", text, f"{module}: {name}")

    def test_dropped_ranges_leave_a_marker(self):
        drops = json.loads((SRC / "drops.json").read_text())
        for module, first, _end in drops:
            text = (self.out / f"{module}.s").read_text()
            self.assertIn("dropped, replaced by the port", text, f"{module}: {first}")
            self.assertNotRegex(text, rf"(?m)^{first}:", f"{module}: {first} should be dropped")

    def test_modules_assemble(self):
        for module in PORT_MODULES:
            source = self.out / f"{module}.s"
            r = run([CA65, "--cpu", "65c02", "-I", SRC, "-I", BUILD, "-g", "-o", source.with_suffix(".o"), source])
            self.assertEqual(r.returncode, 0, f"{module}.s does not assemble:\n{r.stderr}")

    def test_output_matches_the_build(self):
        """The Makefile's build/port/*.s came from the same inputs."""
        for module in PORT_MODULES:
            built = BUILD / "port" / f"{module}.s"
            if not built.exists():
                self.skipTest("build/port missing: run make")
            self.assertEqual((self.out / f"{module}.s").read_text(), built.read_text(),
                             f"{module}.s differs from build/port (stale build?)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
