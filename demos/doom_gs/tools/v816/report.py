"""The Markdown report of the front end: docs/FRONTEND_STATS.md.

The report is written by tools/v816/frontend.py and never by hand;
tests/test_frontend.py checks that the file in docs/ is what this
module writes. The explanations in it are fixed text. Where one states
a number, the number is computed; where it states a fact about
upstream's sources, a test checks the fact.

One upstream file, cal_integer.s, is a copy of a Calypsi library file
under a licence that does not allow the port to keep anything derived
from it. It is parsed like the others and its errors are reported, but
no count of its content goes into the report. `restricted=True` puts it
back in; frontend.py allows that for the console only.
"""

import glob
import os
from collections import Counter

from . import stats

RESTRICTED = ('cal_integer.s',)
LINK_UNITS = ('game', 'boot', 'loader')

# docs/research/iigs-platform.md, section 6, and docs/ARCHITECTURE.md,
# section 0: counts of source lines over all of src/iigs.
RESEARCH_LINES = 82470
RESEARCH_INSTRUCTION_LINES = 58691
RESEARCH_MACRO_LINES = 131
RESEARCH_EXPANDED = 67235
RESEARCH_CONSTRUCTS = (
    ('rep/sep', 1107), ('jsl', 1120), ('jsr', 2243), ('long:', 4678),
    ('[dp]', 2872), (',s', 316), ('## immediate', 8151), ('.near', 9106),
    ('phb/plb', 275), ('xba', 620), ('mvn', 33), ('pei', 151),
    ('pea', 29), ('phd/pld', 34), ('tcd', 23), ('tsc/tcs', 54),
    ('txy/tyx', 122), ('brl', 534), ('jmp long:', 189), ('stz', 606),
    ('bra', 905), ('phx/phy/plx/ply', 387),
)
RESEARCH_PREPROCESSOR = (('include', 152), ('if', 127), ('define', 126),
                         ('undef', 93))

MODE_NAMES = {
    '': 'no operand', 'a': '`a`', '#': '`#e`', '##': '`##e`', 'e': '`e`',
    'e,x': '`e,x`', 'e,y': '`e,y`', 'e,s': '`e,s`', '(e)': '`(e)`',
    '(e,x)': '`(e,x)`', '(e),y': '`(e),y`', '(e,s),y': '`(e,s),y`',
    '[e]': '`[e]`', '[e],y': '`[e],y`',
}


def _number(value):
    return '{:,}'.format(value)


def _table(header, rows, right=()):
    """A Markdown table; `right` are the indices of the columns that
    hold numbers."""
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '|'.join('---:' if index in right else '---'
                            for index in range(len(header))) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(
            _number(cell) if isinstance(cell, int) else str(cell)
            for cell in row) + ' |')
    return lines


def _relative(path, root):
    return os.path.relpath(str(path), str(root))


def _is_restricted(path):
    return os.path.basename(str(path)) in RESTRICTED


def upstream_sources(results):
    """All *.s and *.inc files of upstream's source directory."""
    directory = os.path.dirname(str(results[0].source.path))
    return sorted(glob.glob(os.path.join(directory, '*.s'))
                  + glob.glob(os.path.join(directory, '*.inc')))


class Report:
    """The numbers of one run, and the text made from them."""

    def __init__(self, results, root, restricted=False):
        self.results = results
        self.root = root
        self.counted = [result for result in results
                        if restricted or not _is_restricted(
                            result.source.path)]
        self.left_out = [result for result in results
                         if result not in self.counted]
        self.source_files = [path for path in upstream_sources(results)
                             if restricted or not _is_restricted(path)]
        self.source = stats.source_counts(self.source_files)
        self.units = stats.unit_counts(
            [result.unit for result in self.counted])
        self.expansions = Counter()
        for result in self.counted:
            self.expansions.update(result.counts['expansions'])

    # ----- sections

    def lines(self):
        parts = (self._head(), self._result(), self._files(),
                 self._macros(), self._instructions(), self._mnemonics(),
                 self._modes(), self._sections(), self._other(),
                 self._research(), self._preprocessor())
        lines = []
        for part in parts:
            lines += part + ['']
        return lines[:-1]

    def _head(self):
        lines = [
            '# Front end statistics',
            '',
            'Written by `python3 tools/v816/frontend.py --stats '
            'docs/FRONTEND_STATS.md`. Do not edit it:',
            '`tests/test_frontend.py` compares this file with what the '
            'tool writes.',
            '',
            'The input is upstream at the pinned commit '
            '(`tools/fetch_upstream.py`), built as upstream\'s Makefile',
            'builds it by default: `-D TICSTEP=1` for the game, '
            '`-D MUSIC_MENU=1` for `m_menu65.s`, no flags for',
            '`boot.s` and `loader.s`. `drawcol.s` and `loadfont.s` are '
            'made by upstream\'s `gendraw.py` and `loadfont.py`.',
        ]
        if self.left_out:
            names = ', '.join('`%s`' % result.source.path.name
                              for result in self.left_out)
            lines += [
                '',
                '**Left out of all counts:** %s. It is a copy of a '
                'Calypsi library file, and its licence does not' % names,
                'allow the port to keep anything derived from it. The '
                'front end parses it like the other files, and',
                'section 1 says whether it has errors. '
                '`frontend.py --with-restricted` prints the counts with '
                'it, on the console only.',
            ]
        return lines

    def _result(self):
        errors = [error for result in self.results
                  for error in result.unit.errors]
        unknown = [error for error in errors
                   if error.message.startswith('unknown')]
        by_link = Counter(result.source.link_unit
                          for result in self.results)
        rows = [
            ('Sources (runs of the assembler)', len(self.results)),
            ('of them in the game / boot / loader',
             ' / '.join(str(by_link[name]) for name in LINK_UNITS)),
            ('Sources with errors',
             sum(1 for result in self.results if result.unit.errors)),
            ('Errors', len(errors)),
            ('Unknown directives, mnemonics or macros', len(unknown)),
        ]
        lines = ['## 1. Result', ''] + _table(('', 'Count'), rows, (1,))
        lines += ['', 'An unknown directive or mnemonic is an error; '
                  'the parser has no way to skip a line.']
        for error in errors[:50]:
            lines += ['', '    ' + str(error).replace('\n', '\n    ')]
        return lines

    def _files(self):
        rows = []
        for name in LINK_UNITS:
            chosen = [result for result in self.counted
                      if result.source.link_unit == name]
            files = {str(result.source.path) for result in chosen}
            for result in chosen:
                files.update(str(path) for path in result.included)
            rows.append((name, len(chosen), len(files),
                         stats.source_counts(sorted(files))['lines'],
                         sum(len(result.lines) for result in chosen)))
        every = {str(result.source.path) for result in self.counted}
        for result in self.counted:
            every.update(str(path) for path in result.included)
        rows.append(('all', len(self.counted), len(every),
                     stats.source_counts(sorted(every))['lines'],
                     sum(len(result.lines) for result in self.counted)))
        unread = [path for path in self.source_files if path not in every]
        lines = ['## 2. Files and lines', ''] + _table(
            ('Link unit', 'Sources', 'Files read', 'Lines of those files',
             'Lines after the preprocessor'), rows, (1, 2, 3, 4))
        lines += [
            '',
            '"Files read" counts each file once, include files too; '
            '`memmap.inc` and other include files are read by the',
            'boot and loader as well, so the rows do not add up to the '
            'last one. The lines after the preprocessor count an',
            'include file each time it is read, and leave out the '
            'preprocessor lines and the groups that `#if` skips.',
            '',
            'Upstream\'s `src/iigs` has %s files `*.s` and `*.inc` with '
            '%s lines (not counting the file that is left out).'
            % (_number(len(self.source_files)),
               _number(self.source['lines'])),
            'Files of `src/iigs` that the default build does not read: '
            + (', '.join('`%s`' % os.path.basename(path)
                         for path in unread) or 'none') + '.',
            '',
            'Preprocessor lines in `src/iigs`: '
            + ', '.join('`#%s` %s' % (name, _number(count))
                        for name, count in sorted(
                            self.source['preprocessor'].items())) + '.',
        ]
        return lines

    def _macros(self):
        written = self.source['macro_definitions']
        parsed = {}
        uses = 0
        for result in self.counted:
            uses += len(result.unit.macros)
            for definition in result.unit.macros:
                parsed[(definition.where.file, definition.where.line)] = \
                    definition.name
        written_places = {(path, line) for path, line, _ in written}
        unused = sorted((path, line, name) for path, line, name in written
                        if (path, line) not in parsed)
        ours = sorted((path, line, name)
                      for (path, line), name in parsed.items()
                      if (path, line) not in written_places)
        nested = Counter()
        for result in self.counted:
            for item in result.unit.items():
                where = getattr(item, 'where', None)
                if where is not None and len(where.expansions) > 1:
                    nested[len(where.expansions)] += 1
        rows = [
            ('`.macro` lines in `src/iigs`', len(written)),
            ('Definitions that the default build reads', len(parsed)),
            ('Definitions read, counted once for each source that reads '
             'them', uses),
            ('Macro expansions', sum(self.expansions.values())),
            ('Macros that are used', len(self.expansions)),
            ('Deepest nesting of expansions',
             max(nested) if nested else 1),
        ]
        lines = ['## 3. Macros', ''] + _table(('', 'Count'), rows, (1,))
        lines += ['']
        if self.left_out:
            lines += [
                'With the file that is left out, `src/iigs` has %d '
                '`.macro` lines, the number that' % RESEARCH_MACRO_LINES,
                '`docs/ARCHITECTURE.md` (section 0) expects '
                '(`tests/test_frontend.py` checks it).',
                '']
        lines += ['`.macro` lines that the default build does not read, '
                  'because an `#if` skips them:', '']
        lines += ['- `%s:%d` %s' % (_relative(path, self.root), line, name)
                  for path, line, name in unused] or ['- none']
        if ours:
            lines += ['', 'Definitions read from files that are not '
                      'upstream\'s:', '']
            lines += ['- `%s:%d` %s' % (_relative(path, self.root), line,
                                        name)
                      for path, line, name in ours]
        lines += ['', 'The macros with the most uses:', '']
        lines += _table(('Macro', 'Uses'),
                        self.expansions.most_common(20), (1,))
        return lines

    def _instructions(self):
        rows = []
        for name in LINK_UNITS + ('all',):
            chosen = [result for result in self.counted
                      if name in ('all', result.source.link_unit)]
            after = stats.unit_counts(
                [result.unit for result in chosen])['instructions']
            before = sum(result.counts['source_instructions']
                         for result in chosen)
            rows.append((name, before, after, after - before))
        lines = ['## 4. Instructions before and after macro expansion',
                 '']
        lines += _table(('Link unit', 'Before', 'After', 'Difference'),
                        rows, (1, 2, 3))
        lines += [
            '',
            '"Before" counts the instruction lines of the preprocessed '
            'text: a macro body counts once for each source that',
            'reads its definition, and a use of a macro does not count. '
            '"After" counts the instructions of the IR, which is',
            'what the encoder will see. Both include the generated '
            '`drawcol.s` and `loadfont.s`.',
            '',
            'Instruction lines in the files of `src/iigs` as they are '
            'written (no preprocessor, each file once): %s.'
            % _number(self.source['instruction_lines']),
        ]
        return lines

    def _mnemonics(self):
        names = sorted(set(self.units['mnemonics'])
                       | set(self.source['mnemonics']),
                       key=lambda name: (-self.units['mnemonics'][name],
                                         name))
        rows = [(name, self.source['mnemonics'][name],
                 self.units['mnemonics'][name]) for name in names]
        rows.append(('**total**', self.source['instruction_lines'],
                     self.units['instructions']))
        lines = ['## 5. Instructions by mnemonic', '']
        lines += _table(('Mnemonic', 'Lines in `src/iigs`',
                         'Instructions in the IR'), rows, (1, 2))
        lines += ['', '%d different mnemonics are used.'
                  % len(self.units['mnemonics'])]
        return lines

    def _modes(self):
        modes = self.units['modes']
        rows = [(MODE_NAMES[mode], modes[mode])
                for mode in sorted(modes, key=lambda mode: -modes[mode])]
        sizes = self.units['sizes']
        size_rows = [('`%s`' % size if size else 'nothing', sizes[size])
                     for size in sorted(sizes,
                                        key=lambda size: -sizes[size])]
        lines = ['## 6. Instructions by addressing-mode syntax', '',
                 'The syntax as written, in the IR (after expansion). '
                 '`e` stands for an expression.', '']
        lines += _table(('Syntax', 'Instructions'), rows, (1,))
        lines += [
            '',
            'How the operands say their size: the prefix, and the '
            'relocation operator at the top of the expression.',
            'Immediate operands are in the row "nothing" unless they '
            'have an operator.', '']
        lines += _table(('Written', 'Operands'), size_rows, (1,))
        lines += [
            '',
            'Relocation operators below the top of an expression, which '
            'the manual does not allow ("they must appear at',
            'the top level"): %d. They have the form `.word0 NAME + 2`, '
            'which is `(.word0 NAME) + 2` by the precedence of the'
            % self.units['nested_relocations'],
            'manual. The image match will show what the assembler makes '
            'of them.',
        ]
        return lines

    def _sections(self):
        fragments = self.units['fragments']
        kinds = self.units['section_kinds']
        filled = self.units['filled_fragments']
        rows = [(name, ', '.join(sorted(kinds[name])), fragments[name],
                 filled[name])
                for name in sorted(fragments,
                                   key=lambda name: (-fragments[name],
                                                     name))]
        rows.append(('**total**', '', sum(fragments.values()),
                     sum(filled.values())))
        lines = [
            '## 7. Section fragments by section name', '',
            'Each `.section` directive starts a fragment, and each '
            'source starts in a fragment of the section `code`',
            '(manual, 21.4). The kind is as written; "(none)" means '
            'that no directive gave one. "With content" leaves',
            'out the fragments that hold nothing but equates, which '
            'the linker has nothing to place for: the fragment at',
            'the start of most sources is one.', '']
        lines += _table(('Section', 'Kind', 'Fragments', 'With content'),
                        rows, (2, 3))
        lines += ['', '%d section names.' % len(fragments)]
        return lines

    def _other(self):
        data = self.units['data']
        declarations = self.units['declarations']
        rows = [
            ('Labels', self.units['labels']),
            ('Local labels (`N$`)', self.units['local_labels']),
            ('Local label scopes',
             sum(result.counts['scopes'] for result in self.counted)),
            ('References to a local label across an equate',
             sum(result.counts['across_equates']
                 for result in self.counted)),
            ('Equates', self.units['equates']),
            ('of them code positions (the value uses `.`)',
             self.units['position_equates']),
        ]
        rows += [('`%s`' % name, data[name]) for name in sorted(data)]
        rows += [('`.%s` names' % name, declarations[name])
                 for name in sorted(declarations)]
        lines = ['## 8. Other items of the IR', '']
        lines += _table(('Item', 'Count'), rows, (1,))
        lines += [
            '',
            'Equates are counted for each source that reads them; most '
            'are in include files.',
            '',
            '**Local labels and equates.** The manual says that a local '
            'label is visible between two labels that are not',
            'local. It does not say whether the name of an equate is '
            'such a label. The sources decide it: the references',
            'counted above have an equate between the reference and its '
            'label, in the same scope, so an equate cannot end',
            'a scope. With that rule every reference finds its label, '
            'and no scope defines a label twice.',
        ]
        return lines

    def _research(self):
        constructs = self.source['constructs']
        after = self.units['constructs']
        rows = [(name, research, constructs[name],
                 constructs[name] - research, after[name])
                for name, research in RESEARCH_CONSTRUCTS]
        lines = [
            '## 9. Comparison with the research notes',
            '',
            '`docs/research/iigs-platform.md` (section 6) counted source '
            'lines with awk and grep: no preprocessor, a macro',
            'body once, no generated file, and with the file that this '
            'report leaves out. "Lines" below is the same kind',
            'of count by `tools/v816/stats.py`; "IR" is the count after '
            'the preprocessor and macro expansion, with the',
            'generated files.',
            '',
        ]
        lines += _table(('Construct', 'Research', 'Lines', 'Difference',
                         'IR'), rows, (1, 2, 3, 4))
        lines += ['']
        lines += _table(
            ('', 'Research', 'Here'),
            [('Lines of `src/iigs`', RESEARCH_LINES, self.source['lines']),
             ('Instruction lines', RESEARCH_INSTRUCTION_LINES,
              self.source['instruction_lines']),
             ('`.macro` lines', RESEARCH_MACRO_LINES,
              len(self.source['macro_definitions'])),
             ('Instructions after expansion, game only',
              RESEARCH_EXPANDED, stats.unit_counts(
                  [result.unit for result in self.counted
                   if result.source.link_unit == 'game'])['instructions'])]
            + [('`#%s` lines' % name, research,
                self.source['preprocessor'][name])
               for name, research in RESEARCH_PREPROCESSOR], (1, 2))
        lines += [''] + self._research_text()
        return lines

    def _research_text(self):
        if not self.left_out:
            return ['All files are counted in this run.']
        return [
            'Why the numbers differ:',
            '',
            '1. **The file that is left out.** Every "Lines" number '
            'above is without `cal_integer.s`; the research counted',
            '   it. With it, the counts of this tool equal the research '
            'for all constructs of the table except the four of',
            '   points 2 and 3, and the `.macro` lines are 131 and the '
            '`#include` lines 152. `tests/test_frontend.py` checks',
            '   these equalities in memory, so that no number of the '
            'file is written here.',
            '2. **Labels made by the preprocessor.** `segvar.inc` and '
            '`segclip.inc` have instructions after labels of the',
            '   form `L(name):`. The research did not count those '
            'lines; this tool does. They hold 3 `rep`, 3 `long:` and',
            '   1 `brl`, which are the differences of +3, +3 and +1 '
            'that remain for `rep/sep`, `long:` and `brl` when the',
            '   file of point 1 is counted.',
            '3. **MVN.** The research counted the 33 `.byte` lines that '
            'start with `0x54`. One of them is a table',
            '   (`r_list65.s:3816`, 16 values). This tool counts a line '
            'as MVN when it has the opcode alone or the opcode',
            '   and two bank bytes: 32 lines.',
            '4. **Lines.** The research total of %s includes the three '
            'linker scripts (`iigs.scm`, `boot.scm`,' %
            _number(RESEARCH_LINES),
            '   `loader.scm`: 239 lines). Without them it is 82,231, '
            'which is the number of this tool with the file of',
            '   point 1.',
            '5. **Instruction lines.** With the file of point 1 this '
            'tool counts 17 instruction lines fewer than',
            '   the research, although it counts the 27 instruction '
            'lines of point 2 that the research did not. The',
            '   research script is not in the repository, so the 44 '
            'lines that it counted and this tool does not are not',
            '   identified; uses of macros with names in lower case, '
            'which look like mnemonics, may be among them. The',
            '   difference is 0.07 percent, and the counts of all '
            'single mnemonics of the table agree.',
            '6. **Macro count.** 131 is the number of `.macro` lines. '
            'The 105 of the research notes is not reproduced by',
            '   any count of this tool; the notes do not say how it was '
            'made.',
            '7. **Instructions after expansion.** `docs/ARCHITECTURE.md` '
            '(section 2.2) reports %s from a prototype' %
            _number(RESEARCH_EXPANDED),
            '   that is not in the repository. The number here is '
            'without `cal_integer.s`; what the prototype counted is',
            '   not known, so the difference is not explained.',
            '8. **IR against lines.** The IR has more of most constructs '
            'because macro uses are expanded, `segvar.inc` is',
            '   read for each wall variant, and `drawcol.s` is '
            'generated code (`xba` and `[dp]` grow most). It has',
            '   fewer where an `#if` of the default build skips code.',
        ]

    def _preprocessor(self):
        return [
            '## 10. Preprocessor cross-check',
            '',
            '`python3 tools/v816/cppcheck.py` compares the output of '
            '`tools/v816/cpp.py` with that of',
            '`clang -E -P -x assembler-with-cpp` for every source, with '
            'the same `-I` and `-D`. The outputs must be equal',
            'line by line after runs of white space are made one blank '
            'and empty lines are dropped.',
            '`tests/test_cppcheck.py` runs the comparison where clang '
            'is installed: all %d sources are equal.'
            % len(self.results),
            '',
            'clang is not part of the build. The release image, not '
            'clang, decides whether the preprocessor of the Calypsi',
            'assembler behaves the same; the known risks are:',
            '',
            '- a `#define` body keeps its `;` comment (C knows no such '
            'comment), so the comment arrives where the macro is',
            '  used. The sources use such macros at the end of a line '
            'only: the IR is the same when the comments are',
            '  dropped from the bodies (`tests/test_frontend.py`);',
            '- the text after `#else` and `#endif` is ignored '
            '(`segvar.inc:245` has a `;` comment there);',
            '- a number like `0x1e+NAME` is one preprocessing token in '
            'C, so `NAME` would not be expanded. The sources',
            '  have no such text (`tests/test_frontend.py`).',
        ]


def markdown(results, root, restricted=False):
    """The report as one text."""
    return '\n'.join(Report(results, root, restricted).lines())
