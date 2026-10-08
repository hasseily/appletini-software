"""Real reset/slot firmware boot and coherent guest ProDOS block storage."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/appletini'))
from boot import load_roms
from cli import Machine, build_library, library_api, parser


class BootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = library_api(build_library())

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='appletini-boot-')
        self.addCleanup(self.work.cleanup)
        self.directory = Path(self.work.name)
        # Original synthetic motherboard and card firmware; no licensed ROM
        # fixture needed to verify reset, mapping or disabled service traps.
        rom = bytearray([0x99] * 16384)
        rom[0x1000:0x1003] = bytes.fromhex('4c00c7')
        rom[0x3ffc:0x3ffe] = bytes.fromhex('00d0')
        self.rom = self.directory / 'mother.rom'
        self.rom.write_bytes(rom)
        self.disk = self.directory / 'disk.po'
        self.disk.write_bytes(bytes(1024))
        self.slot = bytearray(256)
        self.slot[:3] = bytes.fromhex('4c0ac7')
        self.slot[10:18] = bytes.fromhex('a9418d00034c00c8')
        self.c8 = bytearray(2048)
        self.c8[:6] = bytes.fromhex('a9428d0103db')
        error = C.create_string_buffer(256)
        self.machine = self.lib.ap_new(str(self.rom).encode(), None,
                                       13333333.333333, 63.695246, 262, 128,
                                       error, len(error))
        self.assertTrue(self.machine, error.value)
        self.addCleanup(self.lib.ap_free, self.machine)
        self.assertEqual(self.lib.ap_mount_disk(self.machine, str(self.disk).encode()), 1)

    def boot(self, slot=None, c8=None):
        slot, c8 = bytes(self.slot if slot is None else slot), bytes(self.c8 if c8 is None else c8)
        return self.lib.ap_boot(self.machine, slot, len(slot), c8, len(c8))

    def read(self, address, length):
        output = C.create_string_buffer(length)
        self.assertEqual(self.lib.ap_read(self.machine, 0, 0, address, output, length), 1)
        return output.raw

    def br(self, address):
        return self.lib.ap_bus_read(self.machine, address)

    def bw(self, address, value=0):
        self.assertEqual(self.lib.ap_bus_write(self.machine, address, value), 1)

    def test_reset_executes_both_roms_and_no_c70a_service_trap(self):
        self.assertEqual(self.boot(), 1)
        self.assertEqual(self.lib.ap_get(self.machine, b'pc'), 0xd000)
        self.assertEqual(self.lib.ap_get(self.machine, b'cycles'), 7)
        self.assertEqual(self.lib.ap_run(self.machine, 100, 0, None, 0), 4)
        self.assertEqual(self.read(0x300, 2), b'AB')
        self.assertEqual(self.lib.ap_get(self.machine, b'steps'), 8)

    def test_internal_c8_is_sticky_until_cfff_including_intcxrom(self):
        self.assertEqual(self.boot(), 1)
        self.assertEqual(self.br(0xc700), 0x4c)
        self.assertEqual(self.br(0xc800), 0xa9)
        self.assertEqual(self.br(0xc300), 0x99)
        self.assertEqual(self.br(0xc700), 0x4c)
        self.assertEqual(self.br(0xc800), 0x99)
        self.bw(0xc007)             # internal ROM enabled
        self.assertEqual(self.br(0xc700), 0x99)
        self.bw(0xc006)             # disabling it does not clear internal C8
        self.assertEqual(self.br(0xc800), 0x99)
        self.br(0xcfff)
        self.br(0xc700)
        self.assertEqual(self.br(0xc800), 0xa9)
        self.bw(0xc300)             # writes also claim internal C8
        self.assertEqual(self.br(0xc800), 0x99)
        self.bw(0xcfff)
        self.bw(0xc700)
        self.assertEqual(self.br(0xc800), 0xa9)
        self.br(0xc300)
        self.assertEqual(self.lib.ap_slot7(self.machine, b'supersprite'), 1)
        self.assertEqual(self.br(0xc800), 0x99)  # card swap cannot own internal C8

    def test_invalid_boot_is_atomic_and_started_machine_rejects_boot(self):
        self.assertEqual(self.lib.ap_write(self.machine, 0, 0, 0x300, b'KEEP', 4), 1)
        self.assertEqual(self.boot(slot=self.slot[:-1]), 0)
        self.assertEqual(self.read(0x300, 4), b'KEEP')
        self.assertEqual(self.lib.ap_get(self.machine, b'cycles'), 0)
        self.assertEqual(self.boot(), 1)
        self.assertEqual(self.read(0x300, 4), bytes(4))
        self.assertEqual(self.boot(), 0)
        self.assertEqual(self.lib.ap_get(self.machine, b'cycles'), 7)

    def test_load_supplied_binary_and_readmemh_with_provenance(self):
        slot = self.directory / 'slot.mem'
        c8 = self.directory / 'c8.bin'
        slot.write_text('// supplied firmware\n' + '\n'.join('%02X' % v for v in self.slot))
        c8.write_bytes(self.c8)
        first, second, meta = load_roms(slot, c8)
        self.assertEqual(first, self.slot)
        self.assertEqual(second, self.c8)
        self.assertEqual(meta['slot7_rom']['sha256'], hashlib.sha256(self.slot).hexdigest())
        self.assertTrue(meta['firmware_execution'])
        self.assertFalse(meta['prodos_mli_traps'])
        slot.write_text('@0000\n' + '00\n' * 256)
        with self.assertRaises(ValueError):
            load_roms(slot, c8)
        slot.write_bytes(bytes(40000))
        with self.assertRaises(ValueError):
            load_roms(slot, c8)

    def test_cli_requires_rom_boot_inputs_and_rejects_launch_overrides(self):
        for extra in ([], ['--rom', str(self.rom), '--system', 'GAME.SYSTEM'],
                      ['--rom', str(self.rom), '--entry', '0x2000']):
            result = subprocess.run([str(ROOT / 'emulator' / 'appletini'), 'run', '--boot',
                                     '--disk', str(self.disk), *extra],
                                    cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)['ok'])


class RealProDOSBootTests(unittest.TestCase):
    def test_bosconian_boot_and_real_filesystem_reads_smartport_write(self):
        target = ROOT.parent / 'appletini-one'
        rom = target / 'Assets/ROMs/Apple2e_Enhanced.rom'
        disk = ROOT / 'demos/appletini_bosconian/Appletini-Bosconian.hdv'
        required = [rom, disk,
                    target / 'hdl/apple/smartport_a2retronet_style_c700.mem',
                    target / 'hdl/apple/smartport_a2retronet_style_c800.mem']
        if not all(p.is_file() for p in required):
            self.skipTest('requires supplied motherboard/SmartPort ROMs and built Bosconian disk')
        original = disk.read_bytes()
        m = Machine(parser().parse_args(['run', '--boot', '--disk', str(disk), '--rom', str(rom)]))
        self.addCleanup(m.close)
        self.assertEqual(m.run(steps=5000000)['reason'], 'steps')
        self.assertEqual(m.read('main', 0x300, 5), b'A13B\1')
        self.assertEqual(m.read('main', 0xbf00, 1), b'\x4c')  # actual ProDOS JMP
        self.assertFalse(m.program['roms']['prodos_mli_traps'])

        # Locate BOSCO.SPR's first data block through the on-disk directory
        # and sapling index. Change it through the same FIFO the real slot
        # firmware uses; ProDOS OPEN/READ must see this session disk change.
        entries = [original[1028 + i * 39:1028 + (i + 1) * 39] for i in range(13)]
        entry = next(e for e in entries if e[1:1 + (e[0] & 15)] == b'BOSCO.SPR')
        self.assertEqual(entry[0] >> 4, 2)
        index = int.from_bytes(entry[17:19], 'little') * 512
        block = original[index] | original[index + 256] << 8
        payload = bytearray(original[block * 512:(block + 1) * 512])
        payload[:8] = b'BOOTTEST'
        m.lib.ap_bus_read(m.handle, 0xc700)
        for byte in bytes([2, 0x70, 0, 0x14, block & 255, block >> 8]) + payload:
            m.check(m.lib.ap_bus_write(m.handle, 0xcff0, byte))
        m.check(m.lib.ap_bus_write(m.handle, 0xcff1, 1))
        self.assertEqual(m.lib.ap_bus_read(m.handle, 0xcff0), 0)

        name = b'/A13BOSCO/BOSCO.SPR'
        m.write('main', 0xb80, bytes([len(name)]) + name)
        m.write('main', 0xb00, bytes.fromhex('03 800b 0010 00'))  # OPEN
        m.write('main', 0xb08, bytes.fromhex('04 00 0014 1000 0000'))  # READ
        m.write('main', 0xb10, bytes.fromhex('01 00'))  # CLOSE
        # SEI; JSR BF00 OPEN; save status; copy refnum to READ/CLOSE;
        # JSR BF00 READ and CLOSE; save status; stop before final loop.
        code = bytes.fromhex('78 2000bf c8 000b 8df00b ad050b 8d090b 8d110b '
                             '2000bf ca 080b 8df10b 2000bf cc 100b 8df20b')
        m.write('main', 0xa00, code + b'\x80\xfe')
        m.reg('pc', 0xa00)
        m.reg('s', 0xff)
        self.assertEqual(m.run(steps=1000000, breakpoints=[0xa00 + len(code)])['reason'],
                         'breakpoint')
        self.assertEqual(m.read('main', 0xbf0, 3), bytes(3))
        self.assertEqual(m.read('main', 0x1400, 16), bytes(payload[:16]))
        self.assertEqual(disk.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
