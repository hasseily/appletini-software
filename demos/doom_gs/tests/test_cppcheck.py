"""Tests of tools/v816/cppcheck.py: cpp.py against clang -E on the
sources of upstream's default build."""

import unittest

import support
from v816 import cppcheck, frontend

needs_clang = unittest.skipUnless(
    cppcheck.clang_path(), 'there is no clang on this machine')


class Normalise(unittest.TestCase):
    def test_white_space(self):
        self.assertEqual(
            cppcheck.normalise('a:\t lda   #1  \n\n   \n  rts\n'),
            ['a: lda #1', 'rts'])

    def test_blank_inside_a_token_is_kept(self):
        self.assertNotEqual(cppcheck.normalise('a b'),
                            cppcheck.normalise('ab'))


@support.needs_upstream
@needs_clang
class AgainstClang(unittest.TestCase):
    def test_every_source_of_the_default_build(self):
        support.frontend_results()      # makes the generated sources
        clang = cppcheck.clang_path()
        sources = frontend.sources()
        self.assertGreaterEqual(len(sources), 10)
        for source in sources:
            with self.subTest(source=source.path.name):
                self.assertEqual(cppcheck.differences(source, clang), [])


if __name__ == '__main__':
    unittest.main()
