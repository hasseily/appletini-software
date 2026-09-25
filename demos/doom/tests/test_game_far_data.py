#!/usr/bin/env python3
"""Run the existing gameplay equivalence sessions with far mutable heads
and far object metadata. The CPU executes the real assembly accessors;
only the flat harness's established far transport is simulated here.
LC bank switching is tested separately by the platform suites.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
import test_game_sim as sim

gamesim = sim.gamesim
ORIGINAL_FLAT = sim.Flat
ORIGINAL_CFLAGS = gamesim.CFLAGS
ORIGINAL_ASMDEFS = gamesim.ASMDEFS


class FarFlat(ORIGINAL_FLAT):
    def __init__(self):
        super().__init__(PROJECT / "build/host/fardata-small")
        # The banked loader installs GINFO here. In the flat image the
        # table also has a near source so the ordinary linker still works.
        lo, hi = self.L["_mobjinfo"], self.L["_mi_doomednum"]
        self.bank(1)[0x6000:0x6000 + hi - lo] = self.mem[lo:hi]


def setUpModule():
    defs = ["-D", "FAR_BLOCKLINKS", "-D", "FAR_MOBJINFO"]
    gamesim.CFLAGS = [*ORIGINAL_CFLAGS, *defs]
    gamesim.ASMDEFS = [*ORIGINAL_ASMDEFS, *defs, "-D", "SMALL_GAME_CACHES"]
    sim.Flat = FarFlat


def tearDownModule():
    sim.Flat = ORIGINAL_FLAT
    gamesim.CFLAGS = ORIGINAL_CFLAGS
    gamesim.ASMDEFS = ORIGINAL_ASMDEFS


class FarDataScriptTest(sim.SimDiffTest):
    """Movement, walls, weapons and the render packet stay equal to C."""


class FarDataBarrelTest(sim.SimBarrelTest):
    """Static-to-actor chain replacement, damage and explosion callbacks."""


class FarDataMonstersTest(sim.SimMonstersTest):
    """Monster movement, targeting and nested damage stay equal to C."""


class FarDataMapTest(sim.SimMapTest):
    """Changing levels clears the far heads and preserves level behavior."""


class HarvardAliasingTest(unittest.TestCase):
    def test_data_read_at_current_opcode_address(self):
        mem = bytearray(65536)
        mem[0x0300] = 8
        cpu = gamesim.HarvardMPU(memory=mem)
        cpu.setup_windows([(0x0300, bytes((0xAD, 0x00, 0x03)))])  # LDA $0300
        cpu.pc = 0x0300
        cpu.step()
        self.assertEqual(cpu.a, 8)

    def test_two_byte_instruction_does_not_fetch_a_third_code_byte(self):
        mem = bytearray(65536)
        mem[0x10:0x12] = bytes((0x02, 0x03))
        mem[0x0302] = 12
        cpu = gamesim.HarvardMPU(memory=mem)
        cpu.setup_windows([(0x0300, bytes((0xB1, 0x10, 0xA9)))])  # LDA ($10),Y
        cpu.pc = 0x0300
        cpu.y = 0
        cpu.step()
        self.assertEqual(cpu.a, 12)


if __name__ == "__main__":
    unittest.main()
