"""The memory API's CPU version (docs/PLAY.md 19, tools/native/amcpu.py).

Without build/: the walker's bytes (against ca65's assembly of the same
source when cc65 is on PATH), the patch table's format and bound.

With the play build (build/native/play: python3 tools/native/playdisk.py)
and a2vm: the card's CPU version (the tic link's AMEMCPU, AMEMCPUD,
AMEMCPUF records) and a walker run on a2vm with no memory API, over a
request of sixteen descriptors of every kind the API takes (COPY from
AUX to MAIN, MAIN to AUX, AUX to AUX of two banks, of one bank, from aux
0's SHR screen, MAIN to MAIN; FILL in AUX and in MAIN; one byte, part
pages, page crossings, 8 KB, odd addresses), each reading what an earlier
one wrote: main and the banks after it must be, byte for byte, what the
API's model (a2vm's FakeSmartPortMemory: each descriptor in order, a copy
or a fill) leaves, and nothing else written; the far layer's zero page
kept; RAMRD, RAMWRT and $C073 off at the end.
"""

import json
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import BUILD

from native import amcpu, lrun, pldisk, playlink as PK  # noqa: E402
from native import render_check as RC  # noqa: E402
from ref816 import bounded  # noqa: E402

PLAY = BUILD / 'native' / 'play'
TIC = PLAY / 'tic' / 'tic.amemcpu'
HAVE = TIC.exists() and lrun.A2VM.exists()
WHY = 'needs the play build (python3 tools/native/playdisk.py) and a2vm'

REQ, WALK, DRIVER = 0x9000, 0x9200, 0x9300
BANKS = (0, 3, 5)
ZP = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
COPY, FILL = 1, 2


def desc(op, src, dst, n, value=0):
    """A descriptor: src and dst (space, bank, address); PRIVATE on."""
    s = src if op == COPY else (0, 0, 0)
    return (struct.pack('<BBBBH', op, 1, s[0], s[1], s[2]) +
            struct.pack('<BBHHB', dst[0], dst[1], dst[2], n, value) +
            bytes(3))


def request(descs):
    n = len(descs)
    head = bytes([4, 3, 0, 0, 0, 0x80, 0, 0, 0, 0]) + \
        struct.pack('<H', 8 + 16 * n) + b'AMEM' + bytes([1, n, 0, 0])
    return head + b''.join(descs)


def model(mem, descs):
    """The API's model: each descriptor in order."""
    for d in descs:
        op, _, ss, sb, sa, ds, db, da, n, v = struct.unpack(
            '<BBBBHBBHHB', d[:13])
        dst = mem[(ds, db)]
        if op == COPY:
            dst[da:da + n] = bytes(mem[(ss, sb)][sa:sa + n])
        else:
            dst[da:da + n] = bytes([v]) * n


class Pure(unittest.TestCase):

    def test_walker_is_its_source(self):
        code = amcpu.walker(0xA000, 0xDB5C, 0xDBAF)
        self.assertEqual(len(code), amcpu.WALKER_SIZE)
        if not shutil.which('ca65') or not shutil.which('ld65'):
            self.skipTest('no cc65')
        src = amcpu.walker.__doc__.split('\n\n', 2)[1]
        lines = ['        .setcpu "65C02"', 'req = $A000', 'cq = $DB5C',
                 'cx_exec = $DBAF', '        .segment "CODE"']
        lines += [ln for ln in src.splitlines() if ln.strip()]
        tmp = Path(tempfile.mkdtemp(prefix='tmp-amcpu-', dir=str(BUILD)))
        try:
            (tmp / 'w.s').write_text('\n'.join(lines) + '\n')
            (tmp / 'w.cfg').write_text(
                'MEMORY { M: start = $6000, size = $100, file = "%O"; }\n'
                'SEGMENTS { CODE: load = M, type = ro; }\n')
            for cmd in (['ca65', 'w.s', '-o', 'w.o'],
                        ['ld65', '-C', 'w.cfg', '-o', 'w.bin', 'w.o']):
                r = subprocess.run(cmd, cwd=str(tmp), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   universal_newlines=True)
                self.assertEqual(r.returncode, 0, r.stdout)
            self.assertEqual((tmp / 'w.bin').read_bytes(), code)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_table(self):
        records = [(0, 0xDB80, bytes(range(128))), (98, 0x697E, b'\xEA' * 300)]
        t = amcpu.table(records)
        self.assertEqual(len(t), amcpu.PATCH_SIZE)
        self.assertEqual(t[:4], bytes([128, 0, 0x80, 0xDB]))
        at = 4 + 128
        self.assertEqual(t[at:at + 4], bytes([255, 98, 0x7E, 0x69]))
        at += 4 + 255
        self.assertEqual(t[at:at + 4], bytes([45, 98, 0x7D, 0x6A]))
        self.assertEqual(t[at + 4 + 45], 0)
        with self.assertRaises(amcpu.PatchError):
            amcpu.table([(5, 0x0200, bytes(amcpu.PATCH_SIZE))])


@unittest.skipUnless(HAVE, WHY)
class OnA2vm(unittest.TestCase):

    def test_every_kind_byte_for_byte(self):
        tb = PK.tic_build(PLAY)
        lab = tb.labels
        rng = random.Random(19)
        mem = {(0, 0): bytearray(rng.randrange(256) for _ in range(0x10000))}
        for b in BANKS:
            mem[(1, b)] = bytearray(rng.randrange(256)
                                    for _ in range(0x10000))
        main, a0, a3, a5 = (0, 0), (1, 0), (1, 3), (1, 5)
        descs = [
            desc(COPY, (1, 5, 0x0203), (0, 0, 0x4007), 1),
            desc(COPY, (1, 5, 0x10F1), (0, 0, 0x2033), 300),
            desc(COPY, (0, 0, 0x8001), (1, 3, 0x1234), 700),
            desc(COPY, (1, 3, 0x1200), (1, 5, 0x3381), 513),
            desc(COPY, (1, 0, 0x2000), (1, 5, 0x6000), 4096),
            desc(FILL, None, (1, 3, 0x5000), 1000, 0xFF),
            desc(FILL, None, (0, 0, 0x6011), 255, 0x5A),
            desc(COPY, (1, 3, 0x5300), (1, 3, 0x7000), 256),
            desc(COPY, (0, 0, 0x6000), (0, 0, 0x7105), 100),
            desc(COPY, (1, 5, 0x3300), (1, 0, 0x0800), 256),
            desc(COPY, (1, 5, 0x6000), (0, 0, 0xA000), 0x2000),
            desc(FILL, None, (1, 0, 0x0A80), 17, 0x00),
            desc(COPY, (0, 0, 0x2033), (1, 5, 0xBF00), 0x100),
            desc(COPY, (1, 3, 0x1234), (0, 0, 0x0400), 2),
            desc(COPY, (1, 0, 0x9DFF), (0, 0, 0xBE01), 0x1FF),
            desc(FILL, None, (1, 5, 0x0200), 1, 0x77)]
        req = request(descs)
        code = amcpu.walker(REQ, lab['cq'], lab['cx_exec'])
        driver = bytes([0x20, WALK & 0xFF, WALK >> 8, 0x80, 0xFE])
        m = mem[main]
        m[0:6] = ZP
        m[REQ:REQ + len(req)] = req
        m[WALK:WALK + len(code)] = code
        m[DRIVER:DRIVER + len(driver)] = driver
        want = {k: bytearray(v) for k, v in mem.items()}
        model(want, descs)
        want[main][REQ + 10] = 0            # (the walker's count)
        recs = [(0, 0, 0, bytes(m[:0xC000]))]
        recs += [(1, b, 0, bytes(mem[(1, b)])) for b in BANKS]
        recs += [(2, 0, 0xC000, bytes([0xA5]) * 0x4000),
                 (3, 0, 0xD000, bytes([0xA5]) * 0x1000)]
        for _, address, data in amcpu.card_patches(tb):
            recs.append((3 if address < 0xE000 else 2, 0, address, data))
        tmp = Path(tempfile.mkdtemp(prefix='tmp-amcpu-', dir=str(BUILD)))
        try:
            (tmp / 'image.bin').write_bytes(RC.image_bytes(recs))
            (tmp / 'rom.bin').write_bytes(bytes(0x4000))
            (tmp / 'events.txt').write_text('pc %X snapshot done\n'
                                            % (DRIVER + 3))
            args = [str(lrun.A2VM), '--rom', str(tmp / 'rom.bin'),
                    '--core', 'w65c02s', '--image', str(tmp / 'image.bin'),
                    '--switch', 'lc_read=1', '--switch', 'lc_write=1',
                    '--switch', 'lc_bank2=0',
                    '--reg', 'pc=%X' % DRIVER, '--reg', 's=FF',
                    '--reg', 'p=34', '--stop-pc', '%X' % (DRIVER + 3),
                    '--cycles', '50000000', '--state',
                    str(tmp / 'state.json'), '--snapshot-dir', str(tmp),
                    '--snapshot-ranges',
                    'main,' + ','.join('aux%d:0000-FFFF' % b for b in BANKS),
                    '--input', str(tmp / 'events.txt')]
            r = bounded.run(args, timeout=120, max_bytes=16 << 20,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True)
            state = json.loads((tmp / 'state.json').read_text())
            self.assertEqual(state.get('pc'), DRIVER + 3, r.stdout[-800:])
            got = pldisk.read_snapshot(tmp / 'done.img')
            sw = state.get('switches', {})
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        g = got[(0, 0)]
        self.assertEqual(bytes(g[0:6]), ZP)
        for key in [main] + [(1, b) for b in BANKS]:
            for lo, hi in ((0x0200, 0x8F00), (0x9400, 0xC000)):
                diff = [a for a in range(lo, hi)
                        if got[key][a] != want[key][a]]
                self.assertEqual(diff[:4], [], '%s: %d bytes differ' % (
                    key, len(diff)))
        self.assertEqual(g[REQ:REQ + len(req)], want[main][REQ:REQ + len(req)])
        for name in ('ramrd', 'ramwrt'):
            if name in sw:
                self.assertFalse(sw[name], name)


if __name__ == '__main__':
    unittest.main()
