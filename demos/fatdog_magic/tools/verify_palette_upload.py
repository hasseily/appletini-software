"""Execute the assembled loader, filter its writes, and verify rendered pixels.

Uses py65 for the actual 6502 instructions. ProDOS file I/O and LINTXT CPU
acknowledgements are modeled; normal capture ranges come from the firmware RTL.
The unchanged Appletini renderer consumes only the resulting capture shadows.
This is a host test, never part of MAGIC.SYSTEM or the shipped disk.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

from py65.devices.mpu6502 import MPU
from PIL import Image
from prodos import raw_files
from verify_brooks_capture import capture_ranges, compile_harness, reference_rgb

DEMO = Path(__file__).resolve().parents[1]


class AppleMemory:
    def __init__(self, ranges, interface=True, fault=None, descriptor_only=False):
        self.main = bytearray(65536)
        self.aux = bytearray(65536)
        self.shadow = bytearray(131072)
        self.ramrd = self.ramwrt = False
        self.interface = interface
        self.descriptor_only = descriptor_only
        self.ranges = ranges
        self.regs = bytearray(256)
        self.index = self.status = self.pending = 0
        self.armed = False
        self.bank = self.base = self.limit = 0
        self.commands = []
        self.uploads = []
        self.trace = []
        self.fault = fault
        self.injected = False

    def __getitem__(self, address):
        address &= 65535
        if 0xC7B0 <= address < 0xC7B8:
            return (b'LINTXT\x4c\x10' if self.interface or self.descriptor_only else b'\xff' * 8)[address - 0xC7B0]
        if 0xC0F8 <= address < 0xC100 and self.interface:
            return b'LINTXT\x4c\x10'[address - 0xC0F8]
        if address == 0xC015:
            return 0
        if address == 0xC0F4 and self.interface:
            if self.pending:
                self.pending -= 1
                if not self.pending:
                    if self.status & 0x80:
                        self.trace.append(('A', 1, 0, 0))
                        if self.fault == 'arm_error':
                            self.status = 0x20
                        else:
                            self.status = 2
                            self.armed = True
                    else:
                        self.trace.append(('A', 8, 0, 0))
                        self.status &= 0x60
                        self.armed = False
            if self.fault == 'busy_timeout':
                return 0x80
            self.trace.append(('R', self.status, 0, 0))
            return self.status
        return (self.aux if self.ramrd and 0x0200 <= address < 0xC000 else self.main)[address]

    def __setitem__(self, address, value):
        address &= 65535
        value &= 255
        if 0xC000 <= address < 0xC100:
            self.trace.append(('I', address, value, 0))
            if address in (0xC002, 0xC003):
                self.ramrd = address == 0xC003
            if address in (0xC004, 0xC005):
                self.ramwrt = address == 0xC005
            if address == 0xC0F0:
                assert self.interface, 'Touched unrelated DEVSEL'
                self.index = value
            if address == 0xC0F2:
                self.regs[self.index] = value
                self.index = (self.index + 1) & 255
            if address == 0xC0F3:
                assert not self.status & 0x90, 'Command sent while BUSY/PENDING'
                assert value in (0, 1), 'Loader must never SHOW or HIDE'
                self.commands.append(value)
                if value == 1:
                    self.base = self.regs[0] | self.regs[1] << 8
                    self.limit = self.base + 2 * self.regs[3] * self.regs[4]
                    self.bank = self.regs[2] & 1
                    assert (self.base, self.limit, self.regs[9]) == (0x0400, 0x1D00, 0x11)
                    self.uploads.append({'bank': self.bank, 'addresses': set()})
                    self.status, self.pending = 0x80, 3
                    self.armed = False
                else:
                    self.status |= 0x10
                    self.pending = 3
            return
        bank = int(self.ramwrt and 0x0200 <= address < 0xC000)
        (self.aux if bank else self.main)[address] = value
        decoded = bank * 65536 + address
        extra = self.armed and bank == self.bank and self.base <= address < self.limit
        if extra:
            self.uploads[-1]['addresses'].add(address)
            if self.fault == 'capture_drop' and not self.injected and address == 0x1000:
                self.armed = False
                self.status = 0x40
                self.injected = True
                extra = False
        captured = extra or any(a <= decoded < b for a, b in self.ranges)
        if captured:
            self.shadow[decoded] = value
        self.trace.append(('W', decoded, value, int(captured)))


def execute(program, sym, payload, ranges, interface=True, fault=None, descriptor_only=False):
    mem = AppleMemory(ranges, interface, fault, descriptor_only)
    mem.main[0xA000:0xA000 + len(program)] = program
    catalog = bytes((i * 53 + 7) & 255 for i in range(0x1100))
    mem.main[0x0900:0x1A00] = catalog
    mem.main[sym['image_kind']] = 0x70 if len(payload) == 78336 else 0x60
    mem.main[sym['read_ref']] = mem.main[sym['close_ref']] = 1
    cpu = MPU(memory=mem)
    position = 0
    reads = 0

    def call(label, expect_error=False):
        nonlocal position, reads
        cpu.pc = sym[label]
        cpu.sp = 0xFD
        mem.main[0x01FE:0x0200] = b'\xfe\x02'  # RTS -> sentinel $02FF
        steps = 0
        while cpu.pc != 0x02FF:
            assert steps < 4_000_000, f'{label}: hung at {cpu.pc:04x}'
            steps += 1
            if cpu.pc == sym['fatal']:
                assert expect_error, f'{label}: fatal, status={mem.status:02x}'
                return False
            if cpu.pc == 0xBF00:
                assert not mem.ramrd and not mem.ramwrt, 'ProDOS called with AUX selected'
                assert not any(u['bank'] == 0 for u in mem.uploads), 'Disk call after MAIN palette upload'
                mem[0x07F8] = 0xC7  # SmartPort slot workspace must not damage final palette
                ret = mem.main[0x100 + ((cpu.sp + 1) & 255)] | mem.main[0x100 + ((cpu.sp + 2) & 255)] << 8
                op = mem.main[ret + 1]
                params = mem.main[ret + 2] | mem.main[ret + 3] << 8
                if op == 0xCA:
                    buffer = mem.main[params + 2] | mem.main[params + 3] << 8
                    length = mem.main[params + 4] | mem.main[params + 5] << 8
                    data = payload[position:position + length]
                    assert len(data) == length
                    assert buffer >= 0x1D00, 'Palette DMA bypasses CPU upload'
                    for i, value in enumerate(data):
                        mem[buffer + i] = value
                    mem.main[params + 6:params + 8] = length.to_bytes(2, 'little')
                    position += length
                    reads += 1
                else:
                    assert op == 0xCC, f'Unexpected MLI ${op:02x}'
                cpu.sp = (cpu.sp + 2) & 255
                cpu.pc = ret + 4
                cpu.p &= ~cpu.CARRY
                cpu.a = 0
                continue
            cpu.step()
        assert not expect_error, 'Fault did not reach error handler'
        return True

    if not call('load_picture', expect_error=bool(fault)):
        # Execute the real bounded cleanup separately, without waiting at the UI.
        call('capture_release')
        if fault != 'busy_timeout':
            assert not mem.armed
        return None
    assert position == len(payload)
    assert not mem.armed and not mem.status & 0x93
    assert mem.aux[0x2000:0xA000] == payload[:32768]
    assert mem.main[0x2000:0xA000] == payload[39168:71936]
    assert mem.aux[0x0400:0x1D00] == payload[32768:39168]
    assert mem.main[0x0400:0x1D00] == (payload[71936:] if len(payload) == 78336 else payload[32768:39168])
    if interface:
        assert mem.commands == [0, 1, 0, 1, 0], mem.commands
        assert [u['bank'] for u in mem.uploads] == [1, 0]
        assert all(u['addresses'] == set(range(0x0400, 0x1D00)) for u in mem.uploads)
    else:
        assert not mem.commands
    shadow = bytes(mem.shadow)
    trace = list(mem.trace)
    call('restore_catalog')
    assert mem.main[0x0900:0x1A00] == catalog
    assert mem.main[0x07F8] == 0xC7, 'SmartPort workspace not restored'
    assert not mem.ramrd and not mem.ramwrt
    assert mem.main[sym['catalog_saved']] == 0
    assert not mem.armed
    return shadow, trace, reads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--image', type=Path, default=DEMO / 'dist/FATDOG_MAGIC.po')
    parser.add_argument('--output', type=Path, default=DEMO / 'validation/palette-upload')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = raw_files(args.image)
    program = files['MAGIC.SYSTEM']
    assert program == (DEMO / 'build/MAGIC.SYSTEM').read_bytes()
    sym = {name: int(value, 16) for name, value in re.findall(r'^\s*(\w+)\s*=\s*\$([0-9a-f]+)', (DEMO / 'build/magic.sym').read_text(), re.M | re.I)}
    ranges = capture_ranges(args.firmware_root)
    exe = compile_harness(args.firmware_root.resolve(), output)
    cases = [(path.split('/')[1], data) for path, data in files.items() if path.startswith('BROOKS.SHR.3200/')]
    assert len(cases) == 20
    separate = bytearray(next(data for _, data in cases if len(data) == 78336))
    for i in range(71936, len(separate), 2):
        separate[i] ^= 0xFF  # distinct second-field colors detect table swaps
    cases.append(('DISTINCT.SECOND.PALETTE', bytes(separate)))
    report = []
    for name, payload in cases:
        shadow, trace, reads = execute(program, sym, payload, ranges)
        (output / 'main.bin').write_bytes(shadow[:65536])
        (output / 'aux.bin').write_bytes(shadow[65536:])
        subprocess.run([str(exe), str(output), 'main.bin', 'BANKS', str(output)], check=True, capture_output=True)
        actual = Image.frombytes('RGBA', (640, 400), (output / 'frame.bgra').read_bytes(), 'raw', 'BGRA').convert('RGB')
        assert actual.tobytes() == reference_rgb(payload), name + ': captured pixels differ'
        if not report or len(payload) == 78336:
            actual.save(output / (name + '.png'))
            (output / (name + '.trace')).write_text(''.join(f'{kind} {a:x} {b:x} {c:x}\n' for kind, a, b, c in trace))
        report.append({'name': name, 'pixel_match': True, 'palette_cpu_writes': 12800,
                       'windows_disabled_after_upload': True, 'catalog_restored': True, 'file_reads': reads})
        print('PASS:', name, flush=True)
    for fault in ('arm_error', 'capture_drop', 'busy_timeout'):
        execute(program, sym, cases[0][1], ranges, fault=fault)
        print('PASS: bounded error path', fault, flush=True)
    execute(program, sym, cases[0][1], ranges, interface=False)
    print('PASS: absent interface performs no DEVSEL writes', flush=True)
    execute(program, sym, cases[0][1], ranges, interface=False, descriptor_only=True)
    print('PASS: ROM descriptor alone does not enable absent interface', flush=True)
    (output / 'report.json').write_text(json.dumps({
        'result': 'PASS', 'disk_sha256': hashlib.sha256(args.image.read_bytes()).hexdigest(),
        'viewer_sha256': hashlib.sha256(program).hexdigest(), 'cases': report,
        'renderer_sha256': hashlib.sha256((args.firmware_root / 'ps_sources/frontend/apple_cycle_renderer.c').read_bytes()).hexdigest(),
        'normal_capture_ranges': ranges, 'faults': ['arm_error', 'capture_drop', 'busy_timeout'],
        'physical_hardware_tested': False,
        'method': 'Actual assembled 6502 loader; modeled ProDOS/LINTXT acknowledgements; source-derived capture filter; unchanged Appletini renderer'
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
