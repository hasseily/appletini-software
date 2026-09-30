"""Tests of ref816's call log (--call-log, tools/ref816/calllog.c).

The machine runs small hand-made routines: calls by JSL, JSR and
JSR (a,x) nested in each other, a thinker entered by JML [dp] from a
trampoline, and the selection keys. On the release (skipped without
build/), FixedMul is logged through the title demo and each call's result
is checked against the exact product of its arguments.
"""

import json
import unittest

import support
from ref816 import calls, make_image, run_script, title
from test_ref816_call import Machine
from test_ref816_machine import have_tools, needs_linkmap

REGISTERS = make_image.Registers(pc=0x1000, pbr=3, dbr=0, a=0, x=0, y=0,
                                 s=0x01ff, d=0, p=0x04, e=0)
MAIN, OUTER, INNER, JSR_X, TRAMPOLINE, THINKER = (
    0x031000, 0x032000, 0x032100, 0x033000, 0x035000, 0x036000)
END = 0x031011
CODE = {
    MAIN: [0xe2, 0x30,                  # 1000 sep #$30
           0xa9, 0x05,                  # 1002 lda #$05
           0x22, 0x00, 0x20, 0x03,      # 1004 jsl OUTER
           0xa2, 0x00,                  # 1008 ldx #$00
           0xfc, 0x00, 0x40,            # 100A jsr ($4000,x): JSR_X
           0x22, 0x00, 0x50, 0x03,      # 100D jsl TRAMPOLINE
           0xea],                       # 1011 nop (END)
    OUTER: [0x1a,                       # inc a
            0x8f, 0x00, 0x00, 0x7e,     # sta $7E0000
            0x20, 0x00, 0x21,           # 2005 jsr INNER
            0x20, 0x00, 0x21,           # 2008 jsr INNER
            0x6b],                      # 200B rtl
    INNER: [0x1a,                       # inc a
            0x8f, 0x01, 0x00, 0x7e,     # sta $7E0001
            0x60],                      # rts
    JSR_X: [0x60],                      # rts
    0x034000: [0x00, 0x30],             # the table of jsr ($4000,x)
    TRAMPOLINE: [0xdc, 0x10, 0x00],     # jml [$0010]
    THINKER: [0xa9, 0x42,               # lda #$42
              0x6b],                    # rtl
    0x000010: [0x00, 0x60, 0x03],       # the pointer of jml [$0010]
}


def loads():
    return [(address, bytes(data)) for address, data in CODE.items()]


def read_log(path):
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return lines[0], lines[1:-1], lines[-1]


@have_tools
class CallLog(Machine):
    def log(self, *routines, stop=END, extra=()):
        path = self.directory / 'calls.log'
        arguments = ['--call-log-file', path, '--cycles', 100000,
                     '--stop-pc', '%06X' % stop] + list(extra)
        for routine in routines:
            arguments += ['--call-log', routine]
        state = self.state(self.image(loads(), REGISTERS), *arguments)
        self.assertEqual(state['end']['reason'], 'stop-pc')
        return read_log(path)

    def test_nested_calls_and_jumps(self):
        head, calls, end = self.log(
            '032000,name=outer,mem=7E0000:2',
            '032100,name=inner,hits=2,mem=7E0001:1',
            '033000,name=jsrx',
            '035000,name=trampoline,entry=1',
            '036000,name=thinker,jumps=1,in=d+10:3+s+1:3')
        self.assertEqual(head['format'], 'ref816-call-log 1')
        self.assertEqual([r['name'] for r in head['routines']],
                         ['outer', 'inner', 'jsrx', 'trampoline', 'thinker'])
        self.assertEqual(head['routines'][4]['in'], [
            {'base': 'd', 'offset': 0x10, 'length': 3},
            {'base': 's', 'offset': 1, 'length': 3}])
        self.assertTrue(head['routines'][3]['entry_only'])
        self.assertEqual(end, {'end': True, 'calls': 5,
                               'arrivals': [1, 2, 1, 1, 1]})
        # A line at each return: the inner call before its caller; the
        # trampoline's at its entry, before the thinker it jumps to.
        self.assertEqual([c['call'] for c in calls], [2, 1, 3, 4, 5])
        inner, outer, jsrx, trampoline, thinker = calls

        self.assertEqual(outer['routine'], 0)
        self.assertEqual((outer['from'], outer['via'], outer['parent'],
                          outer['depth'], outer['irq']),
                         (0x031004, 'jsl', 0, 0, 0))
        self.assertEqual(outer['in']['pc'], OUTER)
        self.assertEqual((outer['in']['a'], outer['in']['p'],
                          outer['in']['s']), (5, 0x34, 0x01fc))
        self.assertEqual(outer['in']['mem'], ['0000'])
        self.assertEqual(outer['out']['exit'], 'rtl')
        self.assertEqual((outer['out']['pc'], outer['out']['a'],
                          outer['out']['s']), (0x031008, 8, 0x01ff))
        self.assertEqual(outer['out']['mem'], ['0608'])
        self.assertTrue(outer['returned'])
        # 11 instructions from the entry to the return, the RTL included.
        self.assertEqual(outer['out']['instructions'] - outer['instructions'],
                         11)

        self.assertEqual((inner['hit'], inner['from'], inner['via'],
                          inner['parent'], inner['depth']),
                         (2, 0x032008, 'jsr', 1, 1))
        self.assertEqual((inner['in']['a'], inner['in']['s'],
                          inner['in']['mem']), (7, 0x01fa, ['07']))
        self.assertEqual((inner['out']['exit'], inner['out']['pc'],
                          inner['out']['a'], inner['out']['mem']),
                         ('rts', 0x03200b, 8, ['08']))

        self.assertEqual((jsrx['from'], jsrx['via'], jsrx['in']['pc']),
                         (0x03100a, 'jsr_x', JSR_X))
        self.assertEqual((jsrx['out']['exit'], jsrx['out']['pc']),
                         ('rts', 0x03100d))

        self.assertEqual((trampoline['from'], trampoline['via']),
                         (0x03100d, 'jsl'))
        self.assertIsNone(trampoline['out'])
        self.assertNotIn('returned', trampoline)

        self.assertEqual((thinker['from'], thinker['via'], thinker['parent'],
                          thinker['in']['s']),
                         (TRAMPOLINE, 'jml_ind', 0, 0x01fc))
        # The pointer, and the return address the JSL pushed (the address
        # of its last byte, then the bank).
        self.assertEqual(thinker['in']['mem'], ['006003', '101003'])
        self.assertEqual((thinker['out']['exit'], thinker['out']['pc'],
                          thinker['out']['a']), ('rtl', END, 0x42))
        self.assertEqual(thinker['out']['mem'], [])

    def test_one_return_ends_the_trampoline_and_its_thinker(self):
        _, calls, end = self.log('035000,name=trampoline',
                                 '036000,name=thinker,jumps=1')
        self.assertEqual(end['calls'], 2)
        thinker, trampoline = calls
        self.assertEqual((thinker['call'], thinker['parent'],
                          thinker['depth']), (2, 1, 1))
        self.assertEqual([c['out']['exit'] for c in calls], ['rtl', 'rtl'])
        self.assertEqual({c['out']['pc'] for c in calls}, {END})

    def test_a_jump_is_no_call_without_jumps(self):
        _, calls, end = self.log('036000,name=thinker')
        self.assertEqual((calls, end['arrivals']), ([], [0]))

    def test_calls_open_at_the_end(self):
        _, calls, end = self.log('032000,name=outer', '032100,name=inner',
                                 stop=INNER)
        self.assertEqual([c['call'] for c in calls], [2, 1])
        for call in calls:
            self.assertFalse(call['returned'])
            self.assertIsNone(call['out']['exit'])
            self.assertEqual(call['out']['pc'], INNER)

    def test_if_and_hits(self):
        # $7E0001 is 7 at the second entry of INNER only.
        _, calls, end = self.log('032100,if=7E0001:1:eq:7,hits=1')
        self.assertEqual(end['arrivals'], [1])
        self.assertEqual([(c['hit'], c['in']['a']) for c in calls], [(1, 7)])
        _, calls, _ = self.log('032100,if=7E0000:1:ge:6')
        self.assertEqual([c['in']['a'] for c in calls], [6, 7])

    def test_after_a_note(self):
        program = self.directory / 'input.txt'
        program.write_text('0 note start\n')
        _, calls, _ = self.log('032000,after=start',
                               extra=['--input', program])
        self.assertEqual(len(calls), 1)
        _, calls, end = self.log('032000,after=later',
                                 extra=['--input', program])
        self.assertEqual((calls, end['arrivals']), ([], [0]))

    def test_errors(self):
        image = self.image(loads(), REGISTERS)
        for arguments in (
                ['--call-log', '032000'],
                ['--call-log-file', self.directory / 'x.log'],
                ['--call-log', 'nowhere', '--call-log-file', 'x.log'],
                ['--call-log', '032000,in=900000:2', '--call-log-file', 'x'],
                ['--call-log', '032000,in=d+10', '--call-log-file', 'x'],
                ['--call-log', '032000,entry=1,out=7E0000:1',
                 '--call-log-file', 'x'],
                ['--call-log', '032000,hits=0', '--call-log-file', 'x'],
                ['--call-log', '032000,colour=red', '--call-log-file', 'x'],
                ['--call-log', '032000', '--call-log-file', 'x',
                 '--call', '032000']):
            result = self.run_machine(image, '--cycles', 100, *arguments)
            self.assertEqual(result.returncode, 2, arguments)
            self.assertIn('ref816: ', result.stderr)

    def test_the_log_changes_nothing(self):
        image = self.image(loads(), REGISTERS)
        plain = self.state(image, '--cycles', 100000, '--stop-pc',
                           '%06X' % END)
        logged = self.state(image, '--cycles', 100000, '--stop-pc',
                            '%06X' % END, '--call-log-file',
                            self.directory / 'x.log', '--call-log',
                            '032000,mem=7E0000:2')
        self.assertEqual(plain, logged)

    def test_the_log_limit_ends_the_run(self):
        """--call-log-limit: a loop that calls for ever fills the log to
        the limit (and one line more at most), then the run fails."""
        import test_ref816_dump as loop
        image = self.image(loop.loads(), loop.REGISTERS, name='loop.img')
        path = self.directory / 'x.log'
        result = self.run_machine(image, '--cycles', 10000000,
                                  '--call-log-file', path, '--call-log',
                                  '032000,mem=7E0000:2',
                                  '--call-log-limit', 4000)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('passed --call-log-limit, 4000 bytes', result.stderr)
        lines = path.read_text().splitlines()
        self.assertLess(path.stat().st_size, 4000 + 1000)
        self.assertGreater(len(lines), 5)
        self.assertLess(json.loads(lines[-1])['cycles'], 100000)


class Resolve(unittest.TestCase):
    LINKMAP = {'game': {
        'units': {'m_fixed65.s': {'FixedMul': 0x0563a8, '_Dp': 0x0009eb},
                  'g_game65.s': {'_g_gametic': 0x02c6af}},
        'sections': {'ztiny': {'first': 0x0900, 'last': 0x09ea}}}}

    def test_symbols_and_the_direct_page(self):
        table = calls.Linkmap(self.LINKMAP)
        self.assertEqual(
            calls.resolve('FixedMul,in=dp:_Dp:4+dp:_Dp+4:4+d+10:2+s+1:3,'
                          'out=_g_gametic+2:2,if=_g_gametic:4:ge:9,hits=2',
                          table),
            '0563A8,in=d+EB:4+d+EF:4+d+10:2+s+1:3,out=02C6B1:2,'
            'if=02C6AF:4:ge:9,hits=2,name=FixedMul')
        self.assertEqual(calls.resolve('0563A8,name=mul', table),
                         '0563A8,name=mul')
        with self.assertRaises(ValueError):
            calls.resolve('FixedMul,in=_g_gametic', table)

    def test_read(self):
        path = support.BUILD / 'test-calls.log'
        path.parent.mkdir(exist_ok=True)
        self.addCleanup(path.unlink)
        path.write_text(json.dumps({'format': 'ref816-call-log 1',
                                    'routines': [{'name': 'f'}]}) + '\n' +
                        json.dumps({'call': 1, 'routine': 0,
                                    'in': {'a': 1, 'mem': ['0102']},
                                    'out': {'a': 2, 'mem': ['03']}}) +
                        '\n{"end": true, "calls": 1, "arrivals": [1]}\n')
        call, = calls.calls(path)
        self.assertEqual((call.name, call.memory_in, call.memory_out,
                          call.registers_in, call.registers_out),
                         ('f', [b'\x01\x02'], [b'\x03'], {'a': 1},
                          {'a': 2}))


def exact_fixed_mul(a, b):
    """FixedMul (build/upstream/src/iigs/m_fixed65.s): (a * b) >> 16 of
    signed 32-bit values, modulo 2^32."""
    def signed(v):
        return v - (1 << 32) if v & 0x80000000 else v
    return (signed(a) * signed(b) >> 16) & 0xffffffff


@have_tools
@needs_linkmap
@support.needs_release
class Release(unittest.TestCase):
    def test_fixed_mul_is_exact_on_every_call_of_the_title_demo(self):
        title.build_machine()
        title.ensure_image()
        symbols = run_script.script.Symbols(
            json.loads(make_image.LINKMAP.read_text()))
        base = json.loads(make_image.LINKMAP.read_text())['game'][
            'sections']['ztiny']['first']
        dp = symbols.address('_Dp') - base
        log = make_image.OUT_DIR / 'test-calllog' / 'fixedmul.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        report = run_script.run(
            run_script.script_path('title'), name='test-calllog',
            extra=['--call-log-file', str(log), '--call-log',
                   '%06X,name=FixedMul,in=d+%X:4' % (
                       symbols.address('FixedMul'), dp)])
        self.assertEqual(report['problems'], [])
        _, calls, end = read_log(log)
        self.assertGreater(len(calls), 100)
        self.assertEqual(end['calls'], len(calls))
        for call in calls:
            registers = call['in']
            # In: a in X:C, b in _Dp[0-3]. Out: X:C.
            a = registers['x'] << 16 | registers['a']
            b = int.from_bytes(bytes.fromhex(registers['mem'][0]), 'little')
            result = call['out']['x'] << 16 | call['out']['a']
            self.assertTrue(call['returned'])
            self.assertEqual(result, exact_fixed_mul(a, b), call)
        log.unlink()


if __name__ == '__main__':
    unittest.main()
