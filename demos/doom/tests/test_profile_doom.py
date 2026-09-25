#!/usr/bin/env python3
"""Profiler attribution and execution-preservation tests."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import profile_doom
import run_doom


class SymbolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'doom.dbg'
        self.path.write_text('''seg\tid=0,name="GB96",start=0xD000,size=0x0200,oname="GBANK96.BIN",ooffs=0
seg\tid=1,name="GB97",start=0xD000,size=0x0200,oname="GBANK97.BIN",ooffs=0
seg\tid=2,name="KLC2",start=0xD000,size=0x0200,oname="LC.BIN",ooffs=0
seg\tid=3,name="RLC1",start=0xD000,size=0x0200,oname="LC.BIN",ooffs=12288
seg\tid=4,name="CODE",start=0x2000,size=0x0100,oname="GAME.BIN",ooffs=0
seg\tid=5,name="RCODE",start=0x2000,size=0x0100,oname="RENDER.BIN",ooffs=0
seg\tid=6,name="GB0",start=0xD000,size=0x0200,oname="GBANK0.BIN",ooffs=0
mod\tid=0,name="test.o",file=0
scope\tid=0,name="",mod=0
sym\tid=0,name="collision",scope=0,val=0xD000,seg=0,type=lab
sym\tid=1,name="actor",scope=0,val=0xD000,seg=1,type=lab
sym\tid=2,name="kernel",scope=0,val=0xD000,seg=2,type=lab
sym\tid=3,name="renderer_lc",scope=0,val=0xD000,seg=3,type=lab
sym\tid=4,name="game",scope=0,val=0x2000,seg=4,type=lab
sym\tid=5,name="renderer",scope=0,val=0x2000,seg=5,type=lab
sym\tid=6,name="@loop",scope=0,val=0xD008,seg=0,type=lab
sym\tid=7,name="control",scope=0,val=0xD000,seg=6,type=lab
''')
        self.symbols = profile_doom.Symbols(self.path)

    def test_shared_addresses_resolve_only_in_the_correct_image(self):
        cases = [('bank:96:lc2', 0xD010, 'collision'), ('bank:97:lc2', 0xD010, 'actor'),
                 ('bank:0:lc2', 0xD010, 'control'),
                 ('main:lc1', 0xD010, 'renderer_lc'), ('main:lc2', 0xD010, 'kernel'),
                 ('main:game', 0x2010, 'game'), ('main:render', 0x2010, 'renderer')]
        for context, pc, expected in cases:
            with self.subTest(context=context):
                self.assertEqual(self.symbols.lookup(context, pc)['symbol'], expected)
        self.assertEqual(self.symbols.lookup('bank:96:lc1', 0xD010)['symbol'], '<unknown>')
        self.assertEqual(self.symbols.lookup('bank:96:lc2', 0xD300)['symbol'], '<unknown>')

    def test_actual_mapper_context_not_logical_call_bank(self):
        machine = SimpleNamespace(main=bytearray(65536), sw={'altzp': False}, bank=97,
                                  lc_read=True, lc_bank2=True,
                                  _aux_selected=lambda _pc, _flag: False)
        machine.main[7] = 1
        self.assertEqual(profile_doom.context_at(machine, 0xD010, 7), 'main:lc2')
        machine.sw['altzp'] = True
        self.assertEqual(profile_doom.context_at(machine, 0xD010, 7), 'bank:97:lc2')
        machine.bank = 0
        self.assertEqual(profile_doom.context_at(machine, 0xD010, 7), 'bank:0:lc2')
        machine.bank = 97
        machine.lc_bank2 = False
        self.assertEqual(profile_doom.context_at(machine, 0xD010, 7), 'bank:97:lc1')
        self.assertEqual(profile_doom.context_at(machine, 0xE010, 7), 'bank:97:lc2')
        self.assertEqual(profile_doom.context_at(machine, 0x2010, 7), 'main:game')
        machine.main[7] = 0
        self.assertEqual(profile_doom.context_at(machine, 0x2010, 7), 'main:render')


BUILD = Path(os.environ.get('DOOM_PROFILE_BUILD', ROOT / 'build'))
DATA = ROOT / 'build/data'
READY = (BUILD / 'banked.json').is_file() and (BUILD / 'doom.dbg').is_file() \
    and (DATA / 'manifest.json').is_file() and run_doom.DEFAULT_ROM.is_file()


@unittest.skipUnless(READY, 'requires a current linked banked image, converted data and Apple ROM')
class ExecutionTest(unittest.TestCase):
    def test_observer_preserves_instruction_execution_and_accounts_every_cycle(self):
        # Two independent machines perform precisely the same workload. The
        # profiled one must have identical CPU/memory/clock state, including
        # the synthetic I/O penalty, interrupts and the screen contents.
        profiled = run_doom.Doom(BUILD, DATA, speed=33, io_cycles=11, fast=True)
        report = profile_doom.Profile(profiled, frames=1, warmup=0).run(200_000_000)
        self.assertEqual(report['exit_reason'], 'frame_limit')
        self.assertEqual(report['measured_rendered_frames'], 1)
        self.assertGreater(report['gateway_calls'], 0)
        self.assertGreater(report['far_transfers']['far_read']['bytes'], 0)
        self.assertGreater(report['totals']['io_surcharge_cycles'], 0)
        self.assertEqual(report['totals']['elapsed_cycles'], report['frames'][0]['elapsed_cycles'])
        self.assertEqual(report['totals']['work_cycles'], report['frames'][0]['work_cycles'])
        self.assertEqual(sum(row['cpu_cycles'] for row in report['pc_histogram']) +
                         report['phases']['irq_entry']['cpu_cycles'], report['totals']['cpu_cycles'])
        self.assertEqual(sum(row['io_surcharge_cycles'] for row in report['pc_histogram']),
                         report['totals']['io_surcharge_cycles'])
        contexts = {row['context'] for row in report['contexts']}
        control_bank = profiled.banked['banks']['control']
        self.assertIn(f'bank:{control_bank}:lc2', contexts)
        self.assertIn('main:lc1', contexts)
        self.assertIn('main:lc2', contexts)
        self.assertEqual(json.loads(json.dumps(report))['totals'], report['totals'])

        reference = run_doom.Doom(BUILD, DATA, speed=33, io_cycles=11, fast=True)
        reference.boot()
        reference.start_cycle = reference.mpu.processorCycles
        self.assertTrue(reference.run_to('present_done', 200_000_000))
        for register in ('pc', 'a', 'x', 'y', 'p', 'sp', 'processorCycles'):
            self.assertEqual(getattr(profiled.mpu, register), getattr(reference.mpu, register), register)
        self.assertEqual(profiled.machine.main, reference.machine.main)
        self.assertEqual(profiled.machine.aux_banks, reference.machine.aux_banks)
        self.assertEqual(profiled.machine.lc[False], reference.machine.lc[False])
        self.assertEqual(profiled.machine.lc_bank1[False], reference.machine.lc_bank1[False])
        self.assertEqual(profiled.machine.sw, reference.machine.sw)


if __name__ == '__main__':
    unittest.main()
