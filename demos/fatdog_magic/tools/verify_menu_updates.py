#!/usr/bin/env python3
"""Execute assembled menu navigation; verify pixels and every HGR write."""
from pathlib import Path
import hashlib
import json
import re

from py65.devices.mpu6502 import MPU

DEMO = Path(__file__).resolve().parents[1]


class Memory:
    def __init__(self, program):
        self.ram = bytearray(65536)
        self.ram[0xA000:0xA000 + len(program)] = program
        self.key = 0
        self.writes = []
        self.io_writes = []

    def __getitem__(self, address):
        if address == 0xC000:
            return self.key
        if address == 0xC010:
            self.key = 0
        return self.ram[address]

    def __setitem__(self, address, value):
        self.ram[address] = value
        if 0x2000 <= address < 0x4000:
            self.writes.append(address)
        if 0xC000 <= address < 0xC100:
            self.io_writes.append(address)


def offset(row):
    return (row & 7) * 1024 + ((row >> 3) & 7) * 128 + (row >> 6) * 40


def rectangle(first_row, end_row, first_col, end_col):
    return {0x2000 + offset(row) + col for row in range(first_row, end_row)
            for col in range(first_col, end_col)}


def exercise(program, sym, count):
    mem = Memory(program)
    mem.ram[sym['folder_count']] = count
    labels = [('Longest name %02d' % i if i % 3 == 0 else
               'Folder %02d' % i if i % 3 == 1 else 'Z') for i in range(count)]
    for i, label in enumerate(labels):
        record = sym['folder_labels'] + 16 * i
        mem.ram[record:record + 16] = bytes([len(label)]) + label.encode().ljust(15, b'\0')
    cpu = MPU(memory=mem)

    def run(label, key=0):
        mem.key = key
        mem.writes.clear()
        mem.io_writes.clear()
        cpu.pc = sym[label]
        cycles = cpu.processorCycles
        for _ in range(200_000):
            cpu.step()
            if cpu.pc == sym['menu_wait'] and not mem.key:
                return cpu.processorCycles - cycles
        raise AssertionError(f'Menu did not return to wait: ${cpu.pc:04X}')

    full_cycles = run('menu_redraw')
    full_writes = len(mem.writes)
    initial = bytes(mem.ram[0x2000:0x4000])
    font = (DEMO / 'assets/font7x8.bin').read_bytes()

    def expected_screen(selected, top):
        # Build the changing pixels independently from the font and UI layout.
        # Keep the original title/credits/footer and HGR holes byte-for-byte.
        page = bytearray(initial)
        if not count:
            return page
        for address in rectangle(48, 144, 1, 39):
            page[address - 0x2000] = 0

        def text(value, band, column):
            for col, char in enumerate(value, column):
                for row in range(8):
                    page[offset(band * 8 + row) + col] = font[(ord(char) - 32) * 8 + row]

        for index in range(top, min(top + 12, count)):
            text(labels[index], 6 + index - top, 3)
        for address in rectangle(48 + (selected - top) * 8, 56 + (selected - top) * 8, 1, 39):
            page[address - 0x2000] ^= 0x7F
        text(f'{selected + 1:3}', 18, 28)
        text('of', 18, 32)
        text(f'{count:3}', 18, 35)
        return page

    selected = top = 0
    assert initial == expected_screen(selected, top), f'Initial menu, {count} folders'
    cases = []
    # Both directions across all boundaries, wraps, and the 9/10 counter change.
    # Rotate through every supported navigation key (arrows and P/N).
    for direction, keys in ((1, (0x0A, 0x15, ord('N'), ord('n'))),
                            (-1, (0x0B, 0x08, ord('P'), ord('p')))):
        for step in range(max(2, count * 2)):
            old_selected, old_top = selected, top
            if count:
                selected = (selected + direction) % count
                top = min(top, selected)
                top = max(top, selected - 11)
            cycles = run('menu_wait', keys[step % len(keys)] | 0x80)
            assert mem.ram[sym['selected']] == selected
            assert mem.ram[sym['folder_top']] == top
            assert mem.ram[sym['screen_state']] == 1
            assert not mem.io_writes, 'Navigation changed video softswitches'
            actual = bytes(mem.ram[0x2000:0x4000])
            assert actual == expected_screen(selected, top), (count, direction, step, 'pixels')
            if selected == old_selected:
                kind, allowed = 'unchanged', set()
                assert not mem.writes, 'No selection change should mean no HGR writes'
            elif top == old_top:
                kind = 'stationary'
                allowed = rectangle(144, 152, 28, 31)
                for index in (old_selected, selected):
                    row = 48 + (index - top) * 8
                    allowed |= rectangle(row, row + 8, 1, 39)
                assert len(mem.writes) == 632, 'Expected two highlight bands plus three digits'
                assert set(mem.writes) == allowed
            else:
                kind = 'scroll'
                allowed = rectangle(48, 144, 1, 39) | rectangle(144, 152, 28, 31)
            assert set(mem.writes) <= allowed, (count, direction, step, 'write outside changing rows')
            cases.append((kind, len(mem.writes), cycles))
    return {
        'folders': count, 'navigation_steps': len(cases),
        'full_redraw_writes': full_writes, 'full_redraw_cpu_cycles': full_cycles,
        'updates': {kind: {
            'cases': len(group), 'hgr_writes_min': min(row[1] for row in group),
            'hgr_writes_max': max(row[1] for row in group),
            'cpu_cycles_min': min(row[2] for row in group),
            'cpu_cycles_max': max(row[2] for row in group),
        } for kind in ('unchanged', 'stationary', 'scroll')
            if (group := [row for row in cases if row[0] == kind])},
    }


def main():
    program = (DEMO / 'build/MAGIC.SYSTEM').read_bytes()
    sym = {name: int(value, 16) for name, value in re.findall(
        r'^\s*(\w+)\s*=\s*\$([0-9a-f]+)',
        (DEMO / 'build/magic.sym').read_text(), re.M | re.I)}
    cases = [exercise(program, sym, count) for count in (0, 1, 2, 12, 13, 18, 64)]
    report = {
        'result': 'PASS', 'viewer_sha256': hashlib.sha256(program).hexdigest(),
        'method': 'Assembled 6502 instructions with keyboard input and every HGR store traced',
        'checks': ['Independent pixel reference after every navigation step',
                   'Only old/new highlight bands and current number written without scrolling',
                   'Only list rectangle and current number written when scrolling',
                   'No video softswitch writes during navigation',
                   'Empty/single folder, 12-row boundary, 64-folder limit, wrap, 9/10 digits, all arrow/P/N keys'],
        'cases': cases, 'physical_hardware_tested': False,
    }
    output = DEMO / 'validation/menu-updates.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: {sum(case["navigation_steps"] for case in cases)} menu updates; '
          '632 HGR writes per stationary selection change; pixels and write scope verified')


if __name__ == '__main__':
    main()
