"""Tests of tools/v816/frontend.py and report.py: the build description,
and the front end on all sources of upstream's default build."""

import contextlib
import io
import unittest

import support
from v816 import cpp, expr, frontend, ir, lexer, parse, report, stats

MAKEFILE = '''\
TICSTEP  ?= 1
ASFLAGS  := --code-model=large -D TICSTEP=$(TICSTEP)
IIGS_S   := src/iigs/crt0.s src/iigs/m_menu65.s \\
            src/iigs/p_map65.s \\
            src/iigs/w_level65.s

OBJS     := $(patsubst src/iigs/%.s,$(OBJ)/%.o,$(IIGS_S))
MUSIC_MENU ?= 1
'''

STATS_FILE = support.ROOT / 'docs' / 'FRONTEND_STATS.md'

# What the counts of source lines differ by from the research notes
# (docs/research/iigs-platform.md, section 6) when all files are counted;
# docs/FRONTEND_STATS.md, section 9, gives the reasons.
KNOWN_DIFFERENCES = {'rep/sep': 3, 'long:': 3, 'brl': 1, 'mvn': -1}
LINKER_SCRIPT_LINES = 239
INSTRUCTION_LINE_DIFFERENCE = -17


class MakefileSettings(unittest.TestCase):
    def test_settings(self):
        self.assertEqual(frontend.makefile_settings(MAKEFILE), {
            'sources': ['src/iigs/crt0.s', 'src/iigs/m_menu65.s',
                        'src/iigs/p_map65.s', 'src/iigs/w_level65.s'],
            'TICSTEP': '1', 'MUSIC_MENU': '1'})

    def test_makefile_without_the_list(self):
        with self.assertRaises(frontend.BuildError):
            frontend.makefile_settings('TICSTEP ?= 1\nMUSIC_MENU ?= 1\n')


class CommandLine(unittest.TestCase):
    def refused(self, arguments):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                frontend.main(arguments)

    def test_ir_must_stay_inside_build(self):
        self.refused(['--json', str(support.ROOT / 'docs' / 'ir')])

    def test_restricted_counts_cannot_be_written(self):
        self.refused(['--with-restricted', '--stats',
                      str(support.BUILD / 'stats.md')])


@support.needs_upstream
class Sources(unittest.TestCase):
    def setUp(self):
        self.sources = frontend.sources()

    def test_units(self):
        names = [source.path.name for source in self.sources]
        self.assertEqual(len(names), 64)
        self.assertEqual(names[0], 'crt0.s')
        self.assertEqual(names[-3:], ['drawcol.s', 'boot.s', 'loader.s'])
        self.assertEqual(
            [source.link_unit for source in self.sources],
            ['game'] * 62 + ['boot', 'loader'])

    def test_flags(self):
        by_name = {source.path.name: source for source in self.sources}
        self.assertEqual(by_name['crt0.s'].defines, {'TICSTEP': '1'})
        self.assertEqual(by_name['m_menu65.s'].defines,
                         {'TICSTEP': '1', 'MUSIC_MENU': '1'})
        self.assertEqual(by_name['boot.s'].defines, {})
        self.assertEqual(by_name['loader.s'].defines, {})
        self.assertEqual(by_name['loader.s'].include_paths,
                         (frontend.GEN,))
        self.assertIn(frontend.UPSTREAM / 'src' / 'iigs',
                      by_name['drawcol.s'].include_paths)

    def test_generated_sources_are_not_in_the_clone(self):
        generated = [source.path for source in self.sources
                     if frontend.UPSTREAM not in source.path.parents]
        self.assertEqual(generated, [frontend.GEN / 'drawcol.s'])


@support.needs_upstream
class DefaultBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = support.frontend_results()
        cls.by_name = {result.source.path.name: result
                       for result in cls.results}

    def test_no_errors(self):
        errors = [str(error) for result in self.results
                  for error in result.unit.errors]
        self.assertEqual(errors, [])

    def test_every_source_has_content(self):
        for result in self.results:
            with self.subTest(source=result.source.path.name):
                self.assertGreater(len(result.lines), 50)
                self.assertGreater(len(list(result.unit.items())), 10)

    def test_stats_file_is_what_the_tool_writes(self):
        self.assertEqual(STATS_FILE.read_text(),
                         report.markdown(self.results, support.ROOT) + '\n',
                         'run python3 tools/v816/frontend.py --stats '
                         'docs/FRONTEND_STATS.md')

    def test_report_has_nothing_of_the_restricted_file(self):
        emptied = [
            result._replace(lines=[], unit=ir.Unit(result.unit.path),
                            counts=dict(result.counts, expansions={},
                                        source_instructions=0, scopes=0),
                            included=[])
            if result.source.path.name in report.RESTRICTED else result
            for result in self.results]
        self.assertNotEqual(emptied, self.results)
        self.assertEqual(report.markdown(emptied, support.ROOT),
                         report.markdown(self.results, support.ROOT))

    def test_macro_lines(self):
        counts = stats.source_counts(report.upstream_sources(self.results))
        self.assertEqual(len(counts['macro_definitions']),
                         report.RESEARCH_MACRO_LINES)
        self.assertEqual(report.RESEARCH_MACRO_LINES, 131)

    def test_source_counts_against_the_research_notes(self):
        counts = stats.source_counts(report.upstream_sources(self.results))
        for name, research in report.RESEARCH_CONSTRUCTS:
            with self.subTest(construct=name):
                self.assertEqual(counts['constructs'][name] - research,
                                 KNOWN_DIFFERENCES.get(name, 0))
        for name, research in report.RESEARCH_PREPROCESSOR:
            with self.subTest(directive=name):
                self.assertEqual(counts['preprocessor'][name], research)
        self.assertEqual(counts['lines'] + LINKER_SCRIPT_LINES,
                         report.RESEARCH_LINES)
        self.assertEqual(
            counts['instruction_lines'] - report.RESEARCH_INSTRUCTION_LINES,
            INSTRUCTION_LINE_DIFFERENCE)

    def test_instructions_after_labels_made_by_the_preprocessor(self):
        # point 2 of section 9 of the report
        words = []
        for path in report.upstream_sources(self.results):
            with open(path, errors='surrogateescape') as file:
                lines = [line.rstrip('\n') for line in file
                         if line.startswith('L(')]
            words += [stats._statement_tokens(line)[0].text
                      for line in lines if stats._statement_tokens(line)]
        instructions = [word for word in words if not word.startswith('.')]
        self.assertEqual(len(instructions), 27)
        self.assertEqual(
            [instructions.count(name) for name in ('rep', 'sep', 'brl')],
            [3, 0, 1])

    def test_each_expansion_has_its_own_local_labels(self):
        # WALKBANKW of p_tick65.s has a label 1$ and a branch to it
        labels = []
        branches = []
        for item in self.by_name['p_tick65.s'].unit.items():
            expansions = getattr(item, 'where').expansions
            if not expansions or expansions[-1].macro != 'WALKBANKW':
                continue
            if isinstance(item, ir.Label):
                labels.append((expansions[-1].line, item.name, item.scope))
            elif item.operand is not None:
                branches += [(expansions[-1].line, node.name, node.scope)
                             for node in expr.walk(item.operand)
                             if isinstance(node, expr.Local)]
        uses = self.by_name['p_tick65.s'].counts['expansions']['WALKBANKW']
        self.assertGreater(uses, 1)
        self.assertEqual(len(labels), uses)
        self.assertEqual(labels, branches)
        self.assertEqual({name for _, name, _ in labels}, {'1$'})
        self.assertEqual(len({scope for _, _, scope in labels}), uses)

    def test_position_equate_of_the_architecture_document(self):
        # "c17Return .equ ." then ".byte 0x60, 0, .byte1 (drawMid+7)"
        items = list(self.by_name['r_seg65.s'].unit.items())
        index = [position for position, item in enumerate(items)
                 if isinstance(item, ir.Equate)
                 and item.name == 'c17Return'][0]
        self.assertTrue(items[index].position)
        self.assertEqual(items[index].value, expr.Dot())
        data = items[index + 1]
        self.assertEqual(data.directive, 'byte')
        self.assertEqual(data.values[:2],
                         [expr.Number(0x60), expr.Number(0)])
        self.assertEqual(data.values[2].op, 'byte1')

    def test_paste_makes_the_labels_of_the_wall_variants(self):
        labels = {item.name
                  for item in self.by_name['r_seg65.s'].unit.items()
                  if isinstance(item, ir.Label)}
        self.assertIn('v04entry', labels)
        self.assertFalse([name for name in labels if name.startswith('L')
                          and name[1:2] == '('])

    def test_comments_of_define_bodies_change_nothing(self):
        """The IR is the same when #define bodies lose their ";"
        comments: no such macro is used inside a line."""
        class WithoutComments(cpp.Preprocessor):
            def _define(self, rest, fail):
                cpp.Preprocessor._define(
                    self, lexer.strip_comment(rest), fail)

        for result in self.results:
            source = result.source
            if not any(';' in line.text for line in result.lines):
                continue
            with self.subTest(source=source.path.name):
                lines = WithoutComments(
                    source.include_paths,
                    source.defines).process_file(source.path)
                unit, _ = parse.parse_lines(lines, str(source.path))
                self.assertEqual(ir.to_plain(unit),
                                 ir.to_plain(result.unit))

    def test_no_number_swallows_a_name(self):
        """No text like 0x1e+NAME, which is one token for a C
        preprocessor."""
        found = []
        files = {str(result.source.path) for result in self.results}
        for result in self.results:
            files.update(str(path) for path in result.included)
        for path in sorted(files):
            with open(path, errors='surrogateescape') as file:
                for number, line in enumerate(file, 1):
                    found += [
                        (path, number, token.text)
                        for token in cpp._tokens(lexer.strip_comment(line))
                        if token.kind == 'num'
                        and ('+' in token.text or '-' in token.text)]
        self.assertEqual(found, [])

    def test_call_of_the_stand_in_header(self):
        """macros.h of tools/v816/include gives "call" and "return"."""
        unit = self.by_name['cal_integer.s'].unit
        macros = {expansion.macro for item in unit.items()
                  for expansion in item.where.expansions}
        self.assertLessEqual({'call', 'return'}, macros)
        sections = {fragment.section for fragment in unit.fragments}
        self.assertIn('farcode', sections)
        self.assertNotIn('libcode', sections)


if __name__ == '__main__':
    unittest.main()
