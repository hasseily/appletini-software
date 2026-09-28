"""Tests of tools/v816/cpp.py: directives, expansion and corner cases."""

import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)
from v816 import cpp


def run(text, defines=None):
    """The output lines of `text`, as strings."""
    lines = cpp.Preprocessor(defines=defines).process_text(text)
    return [line.text for line in lines]


class PlainText(unittest.TestCase):
    def test_text_passes_with_its_white_space(self):
        self.assertEqual(run('label:\tlda  #1\n   rts\n'),
                         ['label:\tlda  #1', '   rts'])

    def test_immediate_markers_are_untouched(self):
        self.assertEqual(run('    lda ##0x1234\n    ldx #N\n'),
                         ['    lda ##0x1234', '    ldx #N'])

    def test_file_and_line_of_each_line(self):
        lines = cpp.Preprocessor().process_text('a\n#define X 1\nb\n',
                                                name='f.s')
        self.assertEqual([(line.file, line.line) for line in lines],
                         [('f.s', 1), ('f.s', 3)])

    def test_last_line_without_newline(self):
        self.assertEqual(run('a\nb'), ['a', 'b'])


class Comments(unittest.TestCase):
    def test_block_comment_becomes_a_blank(self):
        self.assertEqual(run('a/* x */b\n'), ['a b'])

    def test_block_comment_keeps_the_line_numbers(self):
        lines = cpp.Preprocessor().process_text('/* one\ntwo */\nx\n')
        self.assertEqual([(line.text, line.line) for line in lines],
                         [(' ', 1), ('', 2), ('x', 3)])

    def test_line_comment(self):
        self.assertEqual(run('a // b\n'), ['a  '])

    def test_comment_marks_inside_a_string_are_text(self):
        self.assertEqual(run('.ascii "/* no */ // no"\n'),
                         ['.ascii "/* no */ // no"'])

    def test_quote_without_end_takes_the_rest_of_the_line(self):
        self.assertEqual(run("#define N 5\n; N don't /* stay */ N\nN\n"),
                         ["; 5 don't /* stay */ N", '5'])

    def test_quotes_in_pairs_are_constants(self):
        self.assertEqual(run("#define N 5\n; it's N and N's N\n"),
                         ["; it's N and N's 5"])

    def test_comment_without_end(self):
        with self.assertRaises(cpp.CppError) as caught:
            run('a\n/* b\n')
        self.assertEqual(caught.exception.line, 2)

    def test_semicolon_comment_is_not_known(self):
        self.assertEqual(run('#define N 5\n  nop ; N bytes\n'),
                         ['  nop ; 5 bytes'])


class ObjectMacros(unittest.TestCase):
    def test_define_and_use(self):
        self.assertEqual(run('#define N 5\n lda #N\n'), [' lda #5'])

    def test_define_without_body(self):
        self.assertEqual(run('#define N\n[N]\n'), ['[]'])

    def test_body_keeps_its_semicolon_comment(self):
        self.assertEqual(run('#define R W_YL   ; no top wall\n lda dp:R\n'),
                         [' lda dp:W_YL   ; no top wall'])

    def test_undef(self):
        self.assertEqual(run('#define N 5\n#undef N\nN\n'), ['N'])

    def test_undef_of_unknown_name(self):
        self.assertEqual(run('#undef N\nN\n'), ['N'])

    def test_redefinition_replaces(self):
        self.assertEqual(run('#define N 1\n#define N 2\nN\n'), ['2'])

    def test_chain(self):
        self.assertEqual(run('#define A B\n#define B 3\nA\n'), ['3'])

    def test_no_endless_recursion(self):
        self.assertEqual(run('#define A B\n#define B A\nA B\n'), ['A B'])

    def test_self_reference(self):
        self.assertEqual(run('#define A A+1\nA\n'), ['A+1'])

    def test_no_expansion_in_strings_and_characters(self):
        self.assertEqual(run('#define N 5\n "N" \'N\' N\n'),
                         [' "N" \'N\' 5'])

    def test_no_expansion_inside_longer_names(self):
        self.assertEqual(run('#define N 5\nNN N_ _N N1 N\n'),
                         ['NN N_ _N N1 5'])

    def test_dollar_ends_an_identifier(self):
        self.assertEqual(run('#define loop 5\nloop$\n'), ['5$'])

    def test_hexadecimal_digits_are_not_names(self):
        self.assertEqual(run('#define x1F 5\n0x1F x1F\n'), ['0x1F 5'])

    def test_number_with_exponent_sign_is_one_token(self):
        self.assertEqual(run('#define N 5\n0x1e+N 0x1f+N\n'),
                         ['0x1e+N 0x1f+5'])

    def test_command_line_definitions(self):
        self.assertEqual(run('T S\n', {'T': 1, 'S': 'a b'}), ['1 a b'])

    def test_line_continuation(self):
        self.assertEqual(run('#define N 1 + \\\n 2\nN\nx\n'),
                         ['1 +  2', 'x'])

    def test_macro_argument_names_of_the_assembler(self):
        self.assertEqual(run('#define reg 5\n de\\reg\n'), [' de\\5'])


class FunctionMacros(unittest.TestCase):
    def test_arguments(self):
        self.assertEqual(run('#define F(a, b) b-a\nF(1, 2)\n'), ['2-1'])

    def test_no_parameters(self):
        self.assertEqual(run('#define F() 7\nF() F\n'), ['7 F'])

    def test_name_without_call_is_text(self):
        self.assertEqual(run('#define F(a) a\nF + 1\n'), ['F + 1'])

    def test_blank_before_the_call_bracket(self):
        self.assertEqual(run('#define F(a) <a>\nF (1)\n'), ['<1>'])

    def test_blank_before_the_bracket_in_define_makes_an_object(self):
        self.assertEqual(run('#define F (a) a\nF\n'), ['(a) a'])

    def test_nested_brackets_and_commas(self):
        self.assertEqual(run('#define F(a, b) a|b\nF((1, 2), (3))\n'),
                         ['(1, 2)|(3)'])

    def test_arguments_are_expanded(self):
        self.assertEqual(run('#define N 5\n#define F(a) a+a\nF(N)\n'),
                         ['5+5'])

    def test_empty_argument(self):
        self.assertEqual(run('#define F(a, b) [a|b]\nF(, 2)\n'), ['[|2]'])

    def test_wrong_number_of_arguments(self):
        with self.assertRaises(cpp.CppError):
            run('#define F(a, b) a\nF(1)\n')

    def test_call_that_does_not_end(self):
        with self.assertRaises(cpp.CppError):
            run('#define F(a) a\nF(1\n')

    def test_immediate_markers_in_arguments(self):
        self.assertEqual(run('#define F(a) lda a\nF(##12) F(#1)\n'),
                         ['lda ##12 lda #1'])

    def test_immediate_marker_in_a_body(self):
        self.assertEqual(run('#define LOAD(r) ld##r #0\nLOAD(x)\n'),
                         ['ldx #0'])

    def test_stringify(self):
        self.assertEqual(run('#define S(a) .ascii #a\nS(x  "y")\n'),
                         ['.ascii "x \\"y\\""'])

    def test_recursion_through_arguments(self):
        self.assertEqual(run('#define F(a) a\nF(F(F(1)))\n'), ['1'])


class Paste(unittest.TestCase):
    def test_paste(self):
        self.assertEqual(run('#define CAT(a, b) a ## b\nCAT(v04, row)\n'),
                         ['v04row'])

    def test_paste_does_not_expand_its_operands(self):
        text = ('#define N v04\n#define CAT2(a, b) a ## b\n'
                'CAT2(N, x)\n')
        self.assertEqual(run(text), ['Nx'])

    def test_paste_through_a_second_macro_expands_them(self):
        # upstream's L(x), src/iigs/r_seg65.s
        text = ('#define CAT2(a, b) a ## b\n#define CAT(a, b) CAT2(a, b)\n'
                '#define L(x) CAT(V_NAME, x)\n#define V_NAME v04\n'
                'L(row73):    lda ##1\n'
                '#undef V_NAME\n#define V_NAME v12\nL(entry)  .equ .\n')
        self.assertEqual(run(text), ['v04row73:    lda ##1',
                                     'v12entry  .equ .'])

    def test_result_of_paste_is_expanded(self):
        self.assertEqual(run('#define AB 9\n#define C(a, b) a##b\nC(A, B)\n'),
                         ['9'])

    def test_paste_in_an_object_macro(self):
        self.assertEqual(run('#define N a ## 1\nN\n'), ['a1'])

    def test_paste_with_an_empty_argument(self):
        self.assertEqual(run('#define C(a, b) a ## b\nC(, x) C(x, )\n'),
                         ['x x'])

    def test_paste_that_gives_no_token(self):
        with self.assertRaises(cpp.CppError):
            run('#define C(a, b) a ## b\nC(+, x)\n')

    def test_paste_at_the_end_of_a_body(self):
        with self.assertRaises(cpp.CppError):
            run('#define C(a) a ##\n')

    def test_outside_a_body_it_is_the_immediate_marker(self):
        self.assertEqual(run('#define a 1\n#define b 2\n lda a ## b\n'),
                         [' lda 1 ## 2'])


class Conditions(unittest.TestCase):
    def check(self, condition, expected, defines=None):
        text = '#if %s\nyes\n#else\nno\n#endif\n' % condition
        self.assertEqual(run(text, defines), ['yes' if expected else 'no'],
                         condition)

    def test_numbers(self):
        self.check('1', True)
        self.check('0', False)
        self.check('0x10 == 16', True)
        self.check('010 == 8', True)
        self.check("'A' == 65", True)
        self.check('10U == 10L', True)

    def test_unknown_name_is_zero(self):
        self.check('NOTHING', False)
        self.check('NOTHING == 0', True)

    def test_defined(self):
        defines = {'A': 0}
        self.check('defined A', True, defines)
        self.check('defined(A)', True, defines)
        self.check('defined ( A )', True, defines)
        self.check('!defined B', True, defines)
        self.check('defined A && !defined B', True, defines)

    def test_defined_does_not_expand_its_name(self):
        self.check('defined A', True, {'A': 'B'})

    def test_arithmetic(self):
        self.check('1 + 2 * 3 == 7', True)
        self.check('(1 + 2) * 3 == 9', True)
        self.check('7 / 2 == 3 && 7 % 2 == 1', True)
        self.check('-7 / 2 == -3 && -7 % 2 == -1', True)
        self.check('1 << 4 == 16 && 256 >> 4 == 16', True)
        self.check('-1 < 0 && +1 > 0', True)

    def test_comparisons(self):
        self.check('1 < 2 && 2 <= 2 && 3 > 2 && 3 >= 3 && 1 != 2', True)
        self.check('2 < 1 || 3 <= 2 || 2 > 3 || 2 >= 3 || 1 != 1', False)

    def test_bit_operators(self):
        self.check('(6 & 3) == 2 && (6 | 3) == 7 && (6 ^ 3) == 5', True)
        self.check('~0 == -1', True)
        self.check('1 | 2 == 2', True)      # == binds more strongly

    def test_logic(self):
        self.check('1 && 0 || 1', True)
        self.check('!1 || !0', True)
        self.check('0 || 0', False)

    def test_conditional_operator(self):
        self.check('(1 ? 5 : 6) == 5 && (0 ? 5 : 6) == 6', True)

    def test_macros_in_the_expression(self):
        defines = {'TICSTEP': 1, 'V_TOP': 0, 'V_BOT': 1, 'V_ONE': 0}
        self.check('TICSTEP > 1', False, defines)
        self.check('V_ONE || (V_TOP != V_BOT)', True, defines)
        self.check('MAXTICS < 1 || MAXTICS > 15', False, {'MAXTICS': 4})

    def test_division_by_zero(self):
        with self.assertRaises(cpp.CppError):
            run('#if 1 / 0\n#endif\n')

    def test_text_after_the_expression(self):
        with self.assertRaises(cpp.CppError):
            run('#if 1 2\n#endif\n')

    def test_ifdef_and_ifndef(self):
        text = ('#ifdef A\na\n#endif\n#ifndef A\nnot a\n#endif\n'
                '#ifdef B\nb\n#endif\n#ifndef B\nnot b\n#endif\n')
        self.assertEqual(run(text, {'A': 1}), ['a', 'not b'])

    def test_elif_takes_the_first_true_group(self):
        text = ('#if N == 1\none\n#elif N == 2\ntwo\n#elif N >= 2\nmore\n'
                '#else\nnone\n#endif\n')
        self.assertEqual(run(text, {'N': 1}), ['one'])
        self.assertEqual(run(text, {'N': 2}), ['two'])
        self.assertEqual(run(text, {'N': 3}), ['more'])
        self.assertEqual(run(text, {'N': 0}), ['none'])

    def test_nesting(self):
        text = ('#if 0\n#if 1\na\n#else\nb\n#endif\n#else\n'
                '#if 1\nc\n#else\nd\n#endif\n#endif\n')
        self.assertEqual(run(text), ['c'])

    def test_skipped_group_is_not_read(self):
        text = ('#if 0\n#define N 1\n#error no\n#include "nothing"\n'
                '#if 1 /\n#endif\n#nonsense\n#endif\nN\n')
        self.assertEqual(run(text), ['N'])

    def test_elif_after_a_taken_group_is_not_evaluated(self):
        self.assertEqual(run('#if 1\na\n#elif 1 / 0\nb\n#endif\n'), ['a'])

    def test_text_after_else_and_endif_is_ignored(self):
        text = '#if 0\na\n#else   ; comment\nb\n#endif  ; comment\n'
        self.assertEqual(run(text), ['b'])

    def test_structure_errors(self):
        for text in ('#endif\n', '#else\n', '#elif 1\n', '#if 1\n',
                     '#if 1\n#else\n#else\n#endif\n',
                     '#if 1\n#else\n#elif 1\n#endif\n'):
            with self.assertRaises(cpp.CppError, msg=text):
                run(text)


class OtherDirectives(unittest.TestCase):
    def test_error(self):
        with self.assertRaises(cpp.CppError) as caught:
            run('x\n#error "MAXTICS: 1 to 15 tics"\n')
        self.assertIn('MAXTICS', str(caught.exception))
        self.assertEqual(caught.exception.line, 2)

    def test_unknown_directive(self):
        with self.assertRaises(cpp.CppError):
            run('#pragma once\n')

    def test_directive_with_blanks(self):
        self.assertEqual(run('  #  define N 5\nN\n'), ['5'])

    def test_hash_inside_a_line_is_no_directive(self):
        self.assertEqual(run(' lda #define\n'), [' lda #define'])


class Includes(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'src').mkdir()
        (self.root / 'inc').mkdir()
        (self.root / 'gen').mkdir()

    def write(self, name, text):
        (self.root / name).write_text(text)
        return self.root / name

    def process(self, name, include_paths=()):
        preprocessor = cpp.Preprocessor(
            [self.root / path for path in include_paths])
        lines = preprocessor.process_file(self.root / name)
        return preprocessor, lines

    def test_include_beside_the_source(self):
        self.write('src/a.inc', '#define N 5\nin a\n')
        main = self.write('src/main.s', 'x\n#include "a.inc"\nN\n')
        _, lines = self.process('src/main.s')
        self.assertEqual(
            [(line.text, Path(line.file).name, line.line)
             for line in lines],
            [('x', 'main.s', 1), ('in a', 'a.inc', 2), ('5', 'main.s', 3)])
        self.assertEqual(lines[0].file, str(main))

    def test_include_path_in_order(self):
        self.write('inc/a.inc', 'from inc\n')
        self.write('gen/a.inc', 'from gen\n')
        self.write('src/main.s', '#include "a.inc"\n')
        _, lines = self.process('src/main.s', ['gen', 'inc'])
        self.assertEqual([line.text for line in lines], ['from gen'])

    def test_directory_of_the_source_comes_first(self):
        self.write('src/a.inc', 'from src\n')
        self.write('inc/a.inc', 'from inc\n')
        self.write('src/main.s', '#include "a.inc"\n')
        _, lines = self.process('src/main.s', ['inc'])
        self.assertEqual([line.text for line in lines], ['from src'])

    def test_angle_brackets_skip_the_directory_of_the_source(self):
        self.write('src/a.inc', 'from src\n')
        self.write('inc/a.inc', 'from inc\n')
        self.write('src/main.s', '#include <a.inc>\n')
        _, lines = self.process('src/main.s', ['inc'])
        self.assertEqual([line.text for line in lines], ['from inc'])

    def test_generated_source_includes_from_the_include_path(self):
        # upstream's drawcol.s: in build/gen, includes from src/iigs
        self.write('src/lists.inc', 'lists\n')
        self.write('gen/drawcol.s', '#include "lists.inc"\n')
        _, lines = self.process('gen/drawcol.s', ['src'])
        self.assertEqual([line.text for line in lines], ['lists'])

    def test_include_in_an_include_file_looks_beside_that_file(self):
        self.write('inc/outer.inc', '#include "inner.inc"\n')
        self.write('inc/inner.inc', 'inner\n')
        self.write('src/main.s', '#include "outer.inc"\n')
        preprocessor, lines = self.process('src/main.s', ['inc'])
        self.assertEqual([line.text for line in lines], ['inner'])
        self.assertEqual([path.name for path in preprocessor.included],
                         ['outer.inc', 'inner.inc'])

    def test_same_file_twice_with_other_definitions(self):
        # upstream's segvar.inc
        self.write('src/v.inc', '#if V_ONE\none V_NAME\n#else\n'
                   'two V_NAME\n#endif\n')
        self.write('src/main.s',
                   '#define V_NAME a\n#define V_ONE 1\n#include "v.inc"\n'
                   '#undef V_NAME\n#undef V_ONE\n'
                   '#define V_NAME b\n#define V_ONE 0\n#include "v.inc"\n')
        _, lines = self.process('src/main.s')
        self.assertEqual([line.text for line in lines], ['one a', 'two b'])

    def test_guarded_include_file(self):
        self.write('src/m.inc', '#if !defined M_INC\n#define M_INC\n'
                   'once\n#endif\n')
        self.write('src/main.s', '#include "m.inc"\n#include "m.inc"\n')
        _, lines = self.process('src/main.s')
        self.assertEqual([line.text for line in lines], ['once'])

    def test_include_through_a_macro(self):
        self.write('src/a.inc', 'a\n')
        self.write('src/main.s', '#define FILE "a.inc"\n#include FILE\n')
        _, lines = self.process('src/main.s')
        self.assertEqual([line.text for line in lines], ['a'])

    def test_missing_file(self):
        self.write('src/main.s', 'x\n#include "macros.h"\n')
        with self.assertRaises(cpp.CppError) as caught:
            self.process('src/main.s')
        self.assertEqual(caught.exception.line, 2)

    def test_file_that_includes_itself(self):
        self.write('src/main.s', '#include "main.s"\n')
        with self.assertRaises(cpp.CppError):
            self.process('src/main.s')

    def test_open_condition_at_the_end_of_an_include_file(self):
        self.write('src/a.inc', '#if 1\n')
        self.write('src/main.s', '#include "a.inc"\n#endif\n')
        with self.assertRaises(cpp.CppError):
            self.process('src/main.s')

    def test_definitions_do_not_pass_to_the_next_file(self):
        self.write('src/a.s', '#define N 5\nN\n')
        self.write('src/b.s', 'N\n')
        preprocessor = cpp.Preprocessor()
        first = preprocessor.process_file(self.root / 'src/a.s')
        second = preprocessor.process_file(self.root / 'src/b.s')
        self.assertEqual([first[0].text, second[0].text], ['5', 'N'])


class Render(unittest.TestCase):
    def test_render(self):
        lines = cpp.Preprocessor().process_text('a\nb\n')
        self.assertEqual(cpp.render(lines), 'a\nb\n')


if __name__ == '__main__':
    unittest.main()
