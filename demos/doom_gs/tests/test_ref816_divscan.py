"""Tests of the scan for division by zero (tools/ref816/divscan.py).

A synthetic call log checks how divisors are read. On the release
(skipped without build/): the 46 call sites of the sources are the 46 JSL
instructions to the divides in the image, each placed on its line; the
scan of the title script finds no zero divisor; and no step of it opens
upstream's cal_integer.s.
"""

import json
import pathlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support
from ref816 import divscan, make_image
from test_ref816_machine import have_tools, needs_linkmap

HEAD = {'format': 'ref816-call-log 1', 'routines': [
    {'index': i, 'name': d.name} for i, d in enumerate(divscan.DIVIDES)]}


def call(routine, a, x, p, dp, site=0x031234):
    return {'call': 1, 'routine': routine, 'hit': 1, 'from': site,
            'via': 'jsl', 'parent': 0, 'depth': 0, 'irq': 0, 'frame': 7,
            'cycles': 100, 'instructions': 10,
            'in': {'pc': 0, 'a': a, 'x': x, 'y': 0, 's': 0x1ff, 'd': 0x900,
                   'dbr': 2, 'p': p, 'e': 0, 'mem': [dp.hex()]},
            'out': None}


class CallsOf(unittest.TestCase):
    def test_divisors(self):
        names = [d.name for d in divscan.DIVIDES]
        lines = [HEAD,
                 call(names.index('_Div16'), 0x1234, 0x0000, 0x00,
                      bytes(8)),
                 call(names.index('_Mod16'), 0x1234, 0x0003, 0x00,
                      bytes(8)),
                 # 8-bit index registers: X is its low byte
                 call(names.index('_UDivMod16'), 0x0010, 0x0100, 0x10,
                      bytes(8)),
                 call(names.index('_Div32'), 0, 0,
                      0x00, bytes([1, 2, 3, 4, 0, 0, 1, 0])),
                 call(names.index('_UDivMod32'), 0, 5, 0x00,
                      bytes([9, 0, 0, 0, 0, 0, 0, 0])),
                 {'end': True, 'calls': 5, 'arrivals': [1, 1, 1, 1, 1]}]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'x.calls'
            log.write_text(''.join(json.dumps(line) + '\n'
                                   for line in lines))
            calls, arrivals = divscan.calls_of(log, 'run')
        self.assertEqual([(c.routine, c.divisor, c.dividend) for c in calls],
                         [('_Div16', 0, 0x1234), ('_Mod16', 3, 0x1234),
                          ('_UDivMod16', 0, 0x0010),
                          ('_Div32', 0x10000, 0x04030201),
                          ('_UDivMod32', 0, 9)])
        self.assertEqual(sum(arrivals.values()), 5)

    def test_the_conventions_name_their_evidence(self):
        for divide in divscan.DIVIDES:
            self.assertIn(divide.divisor, ('x', 'dp'))
            self.assertIn('jsl %s' % divide.name, divide.evidence)
            self.assertNotIn(divscan.VENDOR_FILE, divide.evidence)


def refuse_the_vendor_file(real):
    def read_text(self, *arguments, **keywords):
        if self.name == divscan.VENDOR_FILE:
            raise AssertionError('%s was opened' % self)
        return real(self, *arguments, **keywords)
    return read_text


@have_tools
@needs_linkmap
@support.needs_release
@unittest.skipUnless(divscan.SOURCES.exists(),
                     'build/upstream is missing: run python3 '
                     'tools/fetch_upstream.py first')
class Release(unittest.TestCase):
    def setUp(self):
        divscan.title.build_machine()
        divscan.title.ensure_image()
        patcher = mock.patch.object(
            pathlib.Path, 'read_text',
            refuse_the_vendor_file(pathlib.Path.read_text))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_call_site_is_placed(self):
        sources = divscan.source_sites()
        self.assertEqual(len(sources), 46)
        self.assertEqual({s.callee for s in sources}, set(divscan.BY_NAME))
        with open(str(make_image.LINKMAP)) as handle:
            code = divscan.Code(json.load(handle))
        matched = divscan.matched_sites(code)
        self.assertEqual(len(matched), 46)
        self.assertNotIn(None, matched.values())
        self.assertEqual(set(matched.values()), set(sources))

    def test_title_has_no_zero_divisor(self):
        result = divscan.scan(['title'], jobs=1,
                              out=make_image.OUT_DIR / 'test-divscan')
        run, = result['runs']
        self.assertEqual(run['problems'], [])
        self.assertEqual(run['end']['reason'], 'stop')
        self.assertGreater(result['calls'], 1000)
        self.assertEqual(result['calls'], run['calls'])
        self.assertEqual(result['calls_from_unknown_sites'], [])
        self.assertEqual(result['zero_divisors'], [])
        self.assertEqual(len(result['sites']), 46)
        self.assertTrue(all(row['line'] for row in result['sites']))
        self.assertEqual(sum(run['arrivals'].values()),
                         result['calls'] +
                         result['calls_inside_vendor_runtime'])


if __name__ == '__main__':
    unittest.main()
