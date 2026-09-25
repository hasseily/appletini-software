#!/usr/bin/env python3
"""Profile complete rendered DOOM frames in the real Apple memory mapper.

This is an instruction/cycle profiler, not a hardware TURBO simulator. The
33 MHz preset is the default. The historical synthetic 'turbo' preset does
not model batched video writes, synchronization, PSRAM or cache behavior.
--do uses run_doom's VBL-relative input schedule. --frames and --warmup count
completed rendered frames, not VBLs. JSON retains every executed PC with its
physical code context; function rows are exclusive nearest-label totals
(scoped cc65 procedures are grouped), never inclusive call-stack estimates.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

import run_doom

TIMING_SCOPE = ("test-model instruction cycles; synthetic I/O surcharge and skipped idle "
                "reported separately; no hardware TURBO timing estimate")
FIELDS = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|[^,]*)')


def dbg_fields(text):
    return {key: json.loads(value) if value.startswith('"') else value
            for key, value in FIELDS.findall(text)}


class Symbols:
    """Resolve linked symbols only inside the physical image they belong to."""
    def __init__(self, path):
        self.segments, self.scopes, self.modules, self.symbols = {}, {}, {}, []
        for line in Path(path).read_text().splitlines():
            kind, _, body = line.partition('\t')
            if kind not in ('seg', 'scope', 'mod', 'sym'):
                continue
            fields = dbg_fields(body)
            if kind == 'seg':
                fields['start'] = int(fields['start'], 0)
                fields['size'] = int(fields['size'], 0)
                self.segments[int(fields['id'])] = fields
            elif kind == 'scope':
                self.scopes[int(fields['id'])] = fields
            elif kind == 'mod':
                self.modules[int(fields['id'])] = fields
            elif fields.get('type') == 'lab' and 'seg' in fields and 'val' in fields:
                fields['val'] = int(fields['val'], 0)
                self.symbols.append(fields)
        self.by_context = defaultdict(list)
        self.by_segment = defaultdict(list)
        for seg_id, segment in self.segments.items():
            context = self.segment_context(segment)
            if context:
                self.by_context[context].append((seg_id, segment))
        self.named = {}
        for symbol in self.symbols:
            name = symbol['name']
            segment = self.segments[int(symbol['seg'])]
            context = self.segment_context(segment)
            if not context:
                continue
            self.named[name] = (context, symbol['val'])
            # Drop compiler/cheap-local branch labels; keep named assembly
            # loops because they provide useful optimization locations.
            if name.startswith(('@', '.', '$')) or re.fullmatch(r'L[0-9A-F]+', name):
                continue
            owner = self.scopes.get(int(symbol['scope']), {})
            while 'parent' in owner and 'sym' not in owner:
                owner = self.scopes.get(int(owner['parent']), {})
            if 'sym' in owner and not owner.get('name', '').startswith('$'):
                name = owner['name']
            root = owner
            while 'mod' not in root and 'parent' in root:
                root = self.scopes.get(int(root['parent']), {})
            module = self.modules.get(int(root.get('mod', -1)), {}).get('name', '?')
            self.by_segment[int(symbol['seg'])].append((symbol['val'], name, module))
        for segment_id, values in self.by_segment.items():
            # Prefer named procedure labels over aliases at a shared address.
            values.sort(key=lambda x: (x[0], x[1].startswith('_'), x[1]))
        self.starts = {key: [item[0] for item in values]
                       for key, values in self.by_segment.items()}

    @staticmethod
    def segment_context(segment):
        name, address = segment['name'], segment['start']
        if re.fullmatch(r'GB\d+', name):
            return f'bank:{int(name[2:])}:lc2'
        image = Path(segment.get('oname', '')).name
        if image == 'GAME.BIN':
            return 'main:game'
        if image == 'RENDER.BIN':
            return 'main:render'
        if image == 'LC.BIN':
            if address >= 0xE000:
                return 'main:lc'
            return 'main:lc1' if int(segment.get('ooffs', '0'), 0) >= 0x3000 else 'main:lc2'
        return None

    def lookup(self, context, pc):
        for segment_id, segment in self.by_context.get(context, ()):
            if segment['start'] <= pc < segment['start'] + segment['size']:
                values = self.by_segment.get(segment_id, ())
                index = bisect_right(self.starts.get(segment_id, ()), pc) - 1
                if index >= 0:
                    address, name, module = values[index]
                else:
                    address, name, module = segment['start'], '<unlabelled>', '?'
                return dict(context=context, segment=segment['name'], symbol=name,
                            module=module, symbol_address=address, offset=pc - address)
        return dict(context=context, segment='<unmapped>', symbol='<unknown>', module='?',
                    symbol_address=pc, offset=0)


def context_at(machine, pc, kspace):
    """Instruction storage, including the alternate D000 LC half."""
    if pc >= 0xD000:
        if not machine.lc_read:
            return 'rom'
        half = 'lc1' if pc < 0xE000 and not machine.lc_bank2 else 'lc2'
        if machine.sw['altzp']:
            return f'bank:{machine.bank}:{half}'
        return 'main:lc' if pc >= 0xE000 else f'main:{half}'
    if pc >= 0xC000:
        return 'io-rom'
    if (pc < 0x200 and machine.sw['altzp']) or (
            pc >= 0x200 and machine._aux_selected(pc, 'ramrd')):
        return f'bank:{machine.bank}:lower'
    return 'main:game' if machine.main[kspace] else 'main:render'


def peek(machine, address):
    """Read physical storage without triggering I/O or timing side effects."""
    if address < 0x200:
        return (machine.aux if machine.sw['altzp'] else machine.main)[address]
    if address < 0xC000:
        return (machine.aux if machine._aux_selected(address, 'ramrd') else machine.main)[address]
    if address < 0xD000 or not machine.lc_read:
        return machine.rom[address - 0xC000]
    if machine.sw['altzp']:
        physical = address - 0x1000 if address < 0xE000 and not machine.lc_bank2 else address
        return machine.aux[physical]
    if address < 0xE000 and not machine.lc_bank2:
        return machine.lc_bank1[False][address - 0xD000]
    return machine.lc[False][address - 0xC000]


def costs(cpu=0, io=0, idle=0, instructions=0):
    return dict(cpu_cycles=cpu, io_surcharge_cycles=io, idle_cycles=idle,
                work_cycles=cpu + io, elapsed_cycles=cpu + io + idle,
                instructions=instructions)


class Profile:
    """Non-mutating execution observer; the existing machine owns scheduling."""
    def __init__(self, doom, frames=10, warmup=2, actions=(), map_number=1):
        self.doom, self.machine, self.cpu = doom, doom.machine, doom.mpu
        self.symbols = Symbols(doom.build / 'doom.dbg')
        self.frames, self.warmup, self.map_number = frames, warmup, map_number
        self.actions = sorted((run_doom.parse_action(a) for a in actions), key=lambda a: a[0])
        self.action_log = []
        self.phase = 'frame_control'
        self.active, self.finished, self.started = False, False, False
        self.completed = 0
        self.rows = []
        self.histogram = defaultdict(lambda: [0, 0, 0])
        self.phases = defaultdict(lambda: [0, 0, 0, 0])
        self.frame_phases = defaultdict(lambda: [0, 0, 0, 0])
        self.gates = defaultdict(int)
        self.far = defaultdict(lambda: [0, 0])
        self.far_by_bank = defaultdict(lambda: [0, 0])
        self.bank_selects = defaultdict(int)
        self.context_entries = defaultdict(int)
        self.last_context = None
        self.start_snapshot = None
        self.last_snapshot = None
        self.crash = None
        self.kspace = doom.label('kspace')
        self.events = {}
        for name, phase in [('frame_top', 'frame_control'), ('space_game', 'enter_game'),
                            ('space_render', 'leave_game'), ('render_frame', 'render_setup'),
                            ('bsp_walk', 'bsp_walls'), ('draw_planes', 'planes'),
                            ('r_things', 'thing_projection'), ('r_masked', 'masked_sprites'),
                            ('present', 'present_wait'), ('present_blit', 'blit'),
                            ('debug_sample', 'debug_readout')]:
            if name in self.symbols.named:
                self.events[self.symbols.named[name]] = phase
        self.named_events = {self.symbols.named[name]: name for name in
                             ('frame_top', 'present_done', 'kernel_crash_stop',
                              'call_game_active', 'gb_call', 'far_read', 'far_write', 'far_copy')
                             if name in self.symbols.named}

    def snapshot(self):
        m = self.machine
        return (self.cpu.processorCycles, m.idle_cycles, m.io_accesses, m.shr_writes,
                self.doom.word('ktics'), m.irqs)

    def start(self):
        self.active = True
        self.start_snapshot = self.last_snapshot = self.snapshot()

    def main_event(self, key):
        name = self.named_events.get(key)
        if name == 'kernel_crash_stop':
            self.crash = dict(code=self.doom.byte('kcrash'), pc=self.cpu.pc,
                              cycle=self.cpu.processorCycles)
            self.finished = True
        elif name == 'frame_top':
            if not self.started:
                self.started = True
                # Use the game's ordinary load-level action after initialization.
                # E1M1 needs no injected state; map changes are recorded in JSON.
                if self.map_number != 1:
                    m = self.machine
                    home = m.bank_memory(self.doom.banked['game_home'])
                    home[self.doom.label('_gamemap')] = self.map_number
                    home[self.doom.label('_gameaction')] = 1  # ga_loadlevel
                if self.warmup == 0:
                    self.start()
            now = self.doom.vbl_frame()
            while self.actions and self.actions[0][0] <= now:
                scheduled, words = self.actions.pop(0)
                self.apply(words)
                self.action_log.append(dict(scheduled_vbl=scheduled, applied_vbl=now, action=words))
        elif name == 'present_done':
            self.completed += 1
            if self.active:
                now, previous = self.snapshot(), self.last_snapshot
                stage_rows = {stage: costs(*values[:3], instructions=values[3])
                              for stage, values in self.frame_phases.items()}
                self.rows.append(dict(frame=len(self.rows), model_vbl=self.doom.vbl_frame(),
                                      elapsed_cycles=now[0] - previous[0],
                                      idle_cycles=now[1] - previous[1],
                                      work_cycles=now[0] - previous[0] - now[1] + previous[1],
                                      cpu_cycles=sum(row['cpu_cycles'] for row in stage_rows.values()),
                                      io_surcharge_cycles=sum(row['io_surcharge_cycles'] for row in stage_rows.values()),
                                      io_accesses=now[2] - previous[2],
                                      shr_writes=now[3] - previous[3],
                                      tics=(now[4] - previous[4]) & 0xFFFF,
                                      interrupts=now[5] - previous[5], phases=stage_rows))
                self.last_snapshot = now
                self.frame_phases.clear()
                if len(self.rows) == self.frames:
                    self.finished = True
                    self.active = False
            elif self.completed == self.warmup:
                self.start()
        elif name == 'call_game_active':
            address = self.machine.main[self.doom.label('kcall')]
            address |= self.machine.main[self.doom.label('kcall') + 1] << 8
            self.phase = 'render_packet' if address == self.doom.label('_game_frame') else 'game_tics'
        if not self.active:
            return
        if name == 'gb_call':
            m, cpu = self.machine, self.cpu
            stack = m.aux if m.sw['altzp'] else m.main
            address = (stack[0x100 + ((cpu.sp + 1) & 0xFF)] |
                       stack[0x100 + ((cpu.sp + 2) & 0xFF)] << 8) + 1
            target_bank = peek(m, address)
            target = peek(m, address + 1) | peek(m, address + 2) << 8
            source = m.main[self.doom.label('gb_current')]
            if target_bank == 128:
                target_context = 'main:game' if target < 0xC000 else 'main:lc2' if target < 0xE000 else 'main:lc'
            else:
                target_context = f'bank:{target_bank}:lc2'
            self.gates[(source, target_bank, target_context, target)] += 1
        elif name in ('far_read', 'far_write', 'far_copy'):
            m, L = self.machine, self.doom.labels
            length = m.main[L['far_len']] | m.main[L['far_len'] + 1] << 8
            self.far[name][0] += 1
            self.far[name][1] += length
            bank = m.main[L['far_dst' if name == 'far_write' else 'far_src'] + 2]
            self.far_by_bank[(name, bank)][0] += 1
            self.far_by_bank[(name, bank)][1] += length
            if name == 'far_copy':
                bank = m.main[L['far_dst'] + 2]
                self.far_by_bank[('far_copy_destination', bank)][0] += 1
                self.far_by_bank[('far_copy_destination', bank)][1] += length

    def apply(self, words):
        # Reuse precisely the normal runner's input implementation. Screenshots
        # are deliberately excluded from profile input scripts.
        if words[0] == 'shot':
            raise ValueError('profile --do supports input actions, not screenshots')
        run_doom.Runner.apply(self, words)

    @property
    def mpu(self):
        return self.cpu

    def charge(self, cpu=0, io=0, idle=0, instructions=0, phase=None):
        for table in (self.phases, self.frame_phases):
            row = table[phase or self.phase]
            row[0] += cpu
            row[1] += io
            row[2] += idle
            row[3] += instructions

    def run(self, limit=2_000_000_000):
        d, m, cpu = self.doom, self.machine, self.cpu
        d.boot()
        d.start_cycle = cpu.processorCycles
        end = cpu.processorCycles + limit
        original_step = cpu.step

        def instruction():
            pc = cpu.pc
            context = context_at(m, pc, self.kspace)
            key = (context, pc)
            self.phase = self.events.get(key, self.phase)
            self.main_event(key)
            if self.finished:
                return cpu
            if not self.active:
                return original_step()
            if context != self.last_context:
                self.context_entries[context] += 1
                self.last_context = context
            before, bank, waiting = cpu.processorCycles, m.bank, cpu.waiting
            opcode = peek(m, pc)
            result = original_step()
            # py65 exposes the actual branch/page-crossing extension. The
            # difference includes all synthetic I/O penalties, including slot
            # ROM accesses which a2sim.io_accesses does not count.
            core = 1 if waiting else cpu.cycletime[opcode] + cpu.excycles
            surcharge = cpu.processorCycles - before - core
            row = self.histogram[key]
            row[0] += 1
            row[1] += core
            row[2] += surcharge
            self.charge(core, surcharge, instructions=1)
            if m.bank != bank:
                self.bank_selects[(bank, m.bank)] += 1
            return result

        original_interrupt, original_idle = m._interrupt, m._skip_idle

        def interrupt():
            before = cpu.processorCycles
            original_interrupt()
            if self.active:
                self.charge(cpu=cpu.processorCycles - before, phase='irq_entry')

        def idle_skip(idle):
            before = m.idle_cycles
            original_idle(idle)
            if self.active:
                self.charge(idle=m.idle_cycles - before)

        cpu.step, m._interrupt, m._skip_idle = instruction, interrupt, idle_skip
        try:
            while not self.finished and cpu.processorCycles < end:
                m.step()
        finally:
            cpu.step, m._interrupt, m._skip_idle = original_step, original_interrupt, original_idle
        return self.report('kernel_crash' if self.crash else
                           'frame_limit' if self.finished else 'cycle_limit')

    def report(self, exit_reason):
        functions, contexts, modules = defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0]), defaultdict(lambda: [0, 0, 0])
        pcs = []
        for (context, pc), values in self.histogram.items():
            symbol = self.symbols.lookup(context, pc)
            pcs.append(dict(pc=pc, **symbol, **costs(values[1], values[2], instructions=values[0])))
            for table, key in ((functions, (context, symbol['segment'], symbol['module'], symbol['symbol'])),
                               (contexts, context), (modules, (context, symbol['module']))):
                for index, value in enumerate(values):
                    table[key][index] += value
        phase_rows = {stage: costs(*values[:3], instructions=values[3]) for stage, values in self.phases.items()}
        total = {key: sum(row[key] for row in phase_rows.values()) for key in costs()}
        sort = lambda rows: sorted(rows, key=lambda row: row['work_cycles'], reverse=True)
        function_rows = sort([dict(context=c, segment=s, module=m, symbol=f,
                                   **costs(v[1], v[2], instructions=v[0]))
                              for (c, s, m, f), v in functions.items()])
        hashes = {name: hashlib.sha256((self.doom.build / name).read_bytes()).hexdigest()
                  for name in ('GAME.BIN', 'RENDER.BIN', 'LC.BIN', 'DOOM.BANKS', 'doom.dbg', 'banked.json')
                  if (self.doom.build / name).is_file()}
        return dict(format=1, timing_scope=TIMING_SCOPE, exit_reason=exit_reason, crash=self.crash,
                    build=str(self.doom.build.resolve()), data=str(self.doom.data.resolve()), image_sha256=hashes,
                    speed=self.machine.speed, model_frame_cycles=self.machine.frame_cycles,
                    io_surcharge_per_access=self.machine.io_cycles, fast=self.doom.fast,
                    map=f'E1M{self.map_number}', warmup_rendered_frames=self.warmup,
                    requested_rendered_frames=self.frames, measured_rendered_frames=len(self.rows),
                    actions=self.action_log, pending_actions=self.actions,
                    boot_cycles=self.doom.boot_cycles, totals=total, phases=phase_rows,
                    frames=self.rows, functions=function_rows,
                    symbol_attribution='exclusive scoped procedure or nearest named assembly label within physical segment',
                    phase_attribution='elapsed between entry markers, including callees and I/O; IRQ entry separate',
                    contexts=sort([dict(context=c, entries=self.context_entries[c],
                                        **costs(v[1], v[2], instructions=v[0])) for c, v in contexts.items()]),
                    modules=sort([dict(context=c, module=m, **costs(v[1], v[2], instructions=v[0]))
                                  for (c, m), v in modules.items()]),
                    gateway_calls=sum(self.gates.values()), gateway_edges=[
                        dict(source_bank=s, target_bank=t, target_address=a, calls=n,
                             target_symbol=self.symbols.lookup(c, a)['symbol'])
                        for (s, t, c, a), n in sorted(self.gates.items(), key=lambda x: -x[1])],
                    far_transfers={name: dict(calls=v[0], bytes=v[1]) for name, v in self.far.items()},
                    far_by_bank=[dict(operation=op, bank=bank, calls=v[0], bytes=v[1])
                                 for (op, bank), v in sorted(self.far_by_bank.items())],
                    bank_selections=[dict(source=s, target=t, changes=n)
                                     for (s, t), n in sorted(self.bank_selects.items(), key=lambda x: -x[1])],
                    pc_histogram=sort(pcs))


def print_report(report, top=20):
    print(TIMING_SCOPE)
    print(f"{report['measured_rendered_frames']} measured rendered frames, "
          f"{report['warmup_rendered_frames']} warmup, {report['map']}; {report['exit_reason']}")
    total = report['totals']['work_cycles'] or 1
    print('\nPhase                         CPU cycles    I/O surcharge    Idle skipped   Work %')
    for phase, row in sorted(report['phases'].items(), key=lambda item: -item[1]['work_cycles']):
        print(f"{phase:27} {row['cpu_cycles']:12,d} {row['io_surcharge_cycles']:16,d} "
              f"{row['idle_cycles']:15,d} {100 * row['work_cycles'] / total:7.2f}")
    print('\nExclusive procedures / nearest named assembly labels:')
    for row in report['functions'][:top]:
        print(f"{100 * row['work_cycles'] / total:6.2f}% {row['work_cycles']:12,d} "
              f"{row['context']:16} {row['module']}:{row['symbol']}")
    print(f"\nGateway calls: {report['gateway_calls']:,}")
    for operation, values in report['far_transfers'].items():
        print(f"{operation}: {values['calls']:,} calls, {values['bytes']:,} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--build', type=Path, default=run_doom.default_build())
    parser.add_argument('--data', type=Path)
    parser.add_argument('--rom', type=Path, default=run_doom.DEFAULT_ROM)
    parser.add_argument('--speed', default='33', help="fixed MHz preset, or historical synthetic 'turbo'")
    parser.add_argument('--banks', type=int, default=128)
    parser.add_argument('--frames', type=int, default=10, help='completed rendered frames to measure')
    parser.add_argument('--warmup', type=int, default=2, help='completed rendered frames to discard')
    parser.add_argument('--map', type=int, choices=range(1, 10), default=1, dest='map_number')
    parser.add_argument('--do', action='append', default=[], metavar='VBL:ACTION')
    parser.add_argument('--fast', action='store_true', help='skip ProDOS loading, retain normal game initialization')
    parser.add_argument('--max-cycles', type=int, default=2_000_000_000)
    parser.add_argument('--top', type=int, default=20)
    parser.add_argument('--json', '--jsonout', type=Path, dest='jsonout', required=True)
    args = parser.parse_args()
    if args.frames < 1 or args.warmup < 0 or args.max_cycles < 1:
        parser.error('frames and max-cycles must be positive; warmup cannot be negative')
    speed = args.speed if args.speed == 'turbo' else int(args.speed)
    doom = run_doom.Doom(args.build, args.data, args.rom, speed, args.banks, args.fast)
    if not doom.banked:
        parser.error('requires a banked DOOM build with doom.dbg and banked.json')
    report = Profile(doom, args.frames, args.warmup, args.do, args.map_number).run(args.max_cycles)
    args.jsonout.parent.mkdir(parents=True, exist_ok=True)
    args.jsonout.write_text(json.dumps(report, indent=2) + '\n')
    print_report(report, args.top)
    print(f'\nSaved {args.jsonout}')
    return 0 if report['exit_reason'] == 'frame_limit' else 1


if __name__ == '__main__':
    raise SystemExit(main())
