"""Parser: preprocessed lines in, a Unit of tools/v816/ir.py out.

A line is "[label[:]] [instruction [operands]] [; comment]" (manual,
21.2.1). A name in the first column is a label, the name of an equate
or the name of a macro definition. An instruction is a mnemonic, a
directive or the use of a macro, and never starts in the first column.
A label after leading spaces needs its colon.

Local labels. Each "N$" label belongs to a scope, and scopes have
numbers that are unique in the unit:
- a label that is not local starts a new scope (21.8.1);
- each macro expansion has a scope of its own, and the scope of the
  place of use is back in force after it (21.11.2);
- an equate does not start a scope. The manual speaks of labels only;
  the sources decide it: they have references to local labels with an
  equate between the reference and the label (the parser counts them).
After the last line, each reference to a local label must have its
definition in the same scope, and a scope must not define a name twice.

Errors do not stop the parser. They are collected in Unit.errors, each
with its place, so that one run shows all of them.
"""

from . import cpp, expr, ir, lexer, macro
from .mnemonics import ACCUMULATOR, MNEMONICS

SECTION_KINDS = ('text', 'data', 'rodata', 'bss')
SECTION_MODIFIERS = ('root', 'noroot', 'reorder', 'noreorder', 'noinit')
DECLARATIONS = ('.public', '.global', '.globl', '.pubweak', '.extern',
                '.require')
NUMERIC_DATA = ('.byte', '.word', '.address', '.long', '.quad')
STRING_DATA = ('.ascii', '.asciz')
MAX_EXPANSION_DEPTH = 64


class ParseError(ValueError):
    """One line is wrong. The parser adds the place."""


class _Source:
    """Lines that are being read: the file, or one macro expansion."""

    def __init__(self, lines, outer_scope, outer_equates):
        self.lines = lines          # pairs (text, ir.Where)
        self.position = 0
        self.outer_scope = outer_scope      # None for the file
        self.outer_equates = outer_equates


def split_list(tokens):
    """`tokens` split at the commas that are outside brackets."""
    parts = [[]]
    depth = 0
    for token in tokens:
        if token.kind == 'op' and token.text in '([':
            depth += 1
        elif token.kind == 'op' and token.text in ')]':
            depth -= 1
        if token.kind == 'op' and token.text == ',' and depth == 0:
            parts.append([])
        else:
            parts[-1].append(token)
    return parts


def _closing(tokens, opening, closing):
    """The index of the bracket that closes tokens[0], or None."""
    depth = 0
    for index, token in enumerate(tokens):
        if token.kind != 'op':
            continue
        if token.text == opening:
            depth += 1
        elif token.text == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _register(tokens, names):
    """The register of a tail ", x"; None when `tokens` is not one."""
    if (len(tokens) == 2 and tokens[0].text == ','
            and tokens[1].kind == 'ident'
            and tokens[1].text.lower() in names):
        return tokens[1].text.lower()
    return None


def _inside(tokens, scope, modes):
    """An address inside brackets, with an optional register from
    `modes` (a map from register, or '' for none, to the mode)."""
    prefix, tree, position = expr.parse_address(tokens, 0, scope)
    tail = tokens[position:]
    if not tail and '' in modes:
        return modes[''], prefix, tree
    register = _register(tail, modes)
    if register is None:
        raise ParseError('unexpected "%s" in the operand' % tail[0].text)
    return modes[register], prefix, tree


def parse_operand(tokens, scope, mnemonic):
    """The operand of an instruction: (mode, prefix, expression tree).

    An operand that starts with "(" is indirect when its ")" ends the
    operand or is followed by ",y". Otherwise the bracket is part of an
    expression, as in "(table+2),x".
    """
    if not tokens:
        return '', None, None
    first = tokens[0]
    if (len(tokens) == 1 and first.kind == 'ident'
            and first.text.lower() == 'a' and mnemonic in ACCUMULATOR):
        return 'a', None, None
    if first.kind == 'op' and first.text in ('#', '##'):
        return first.text, None, expr.parse_all(tokens[1:], scope)
    if first.kind == 'op' and first.text == '(':
        close = _closing(tokens, '(', ')')
        if close is None:
            raise ParseError('"(" without ")"')
        tail = tokens[close + 1:]
        if not tail:
            return _inside(tokens[1:close], scope,
                           {'': '(e)', 'x': '(e,x)'})
        if _register(tail, ('y',)):
            return _inside(tokens[1:close], scope,
                           {'': '(e),y', 's': '(e,s),y'})
    if first.kind == 'op' and first.text == '[':
        close = _closing(tokens, '[', ']')
        if close is None:
            raise ParseError('"[" without "]"')
        tail = tokens[close + 1:]
        if not tail:
            return _inside(tokens[1:close], scope, {'': '[e]'})
        if _register(tail, ('y',)):
            return _inside(tokens[1:close], scope, {'': '[e],y'})
        raise ParseError('unexpected "%s" after "]"' % tail[0].text)
    return _inside(tokens, scope,
                   {'': 'e', 'x': 'e,x', 'y': 'e,y', 's': 'e,s'})


def statement_word(text):
    """The word that says what the line does: its first token after the
    label, in lower case when it is a directive; None for a line with a
    label only or with nothing. Used to find the end of a macro body
    and to count its instructions; a body is not parsed until it is
    used, and the backslash of its arguments is no token."""
    try:
        tokens = lexer.tokenize(lexer.strip_comment(text).replace('\\', ''))
    except lexer.LexError:
        return None
    if tokens and tokens[0].column == 0:
        tokens = tokens[1:]
        if tokens and tokens[0].text == ':':
            tokens = tokens[1:]
    elif len(tokens) > 1 and tokens[1].text == ':':
        tokens = tokens[2:]
    return tokens[0].text if tokens else None


class Parser:
    """Parses the lines of one unit. Use parse_lines."""

    def __init__(self, path):
        self.unit = ir.Unit(path)
        self.macros = {}
        self.scope = 0
        self.scope_count = 1
        self.sources = []
        self.local_definitions = {}     # (scope, name) -> (where, equates)
        self.local_references = []      # (node, where, equates)
        self.equates = 0                # equates so far, in this source
        self.across_equates = 0
        self.fragment = ir.Fragment('code', None, (), None)
        self.unit.fragments.append(self.fragment)
        self.expansion_counts = {}
        self.source_instructions = 0
        self.where = None

    # ----- the loop

    def run(self, lines):
        file_lines = [(line.text, ir.Where(line.file, line.line))
                      for line in lines]
        self.sources = [_Source(file_lines, None, 0)]
        while self.sources:
            source = self.sources[-1]
            if source.position >= len(source.lines):
                self.sources.pop()
                if source.outer_scope is not None:
                    self.scope = source.outer_scope
                    self.equates = source.outer_equates
                continue
            text, self.where = source.lines[source.position]
            source.position += 1
            try:
                if self._line(text) == 'end':
                    break
            except (ParseError, lexer.LexError, expr.ExprError,
                    macro.MacroError) as error:
                self._error(str(error))
        self._check_locals()
        if not self.unit.fragments[0].items:
            del self.unit.fragments[0]      # the implied "code", unused
        return self.unit

    def _error(self, message, where=None):
        self.unit.errors.append(ir.Error(message, where or self.where))

    def _new_scope(self):
        self.scope = self.scope_count
        self.scope_count += 1

    def _add(self, item):
        self.fragment.items.append(item)

    # ----- lines

    def _line(self, text):
        tokens = lexer.tokenize(text)
        if not tokens:
            return None
        first = tokens[0]
        named = first.kind in ('ident', 'local')
        if named and first.column == 0:
            rest = tokens[1:]
            if rest and rest[0].text == ':':
                rest = rest[1:]
            if rest and rest[0].kind == 'word':
                if rest[0].text in ('.equ', '.equlab'):
                    return self._equate(first, rest)
                if rest[0].text == '.macro':
                    return self._define_macro(first, text, rest[0])
            self._label(first)
            tokens = rest
        elif named and len(tokens) > 1 and tokens[1].text == ':':
            self._label(first)
            tokens = tokens[2:]
        if not tokens:
            return None
        return self._statement(tokens, text)

    def _statement(self, tokens, text):
        first = tokens[0]
        if first.kind == 'word':
            return self._directive(first.text, tokens[1:])
        if first.kind != 'ident':
            raise ParseError('unexpected "%s"' % first.text)
        if first.text in self.macros:
            return self._use_macro(self.macros[first.text],
                                   text[first.column + len(first.text):])
        mnemonic = first.text.lower()
        if mnemonic not in MNEMONICS:
            raise ParseError('unknown instruction or macro "%s"'
                             % first.text)
        mode, prefix, tree = parse_operand(tokens[1:], self.scope, mnemonic)
        self._references(tree)
        if not self.where.expansions:
            self.source_instructions += 1
        self._add(ir.Instruction(mnemonic, mode, prefix, tree, self.where))
        return None

    # ----- labels and equates

    def _check_name(self, token):
        if token.kind == 'ident' and (token.text.lower() in MNEMONICS
                                      or token.text in self.macros):
            raise ParseError('"%s" in the label column is an instruction; '
                             'instructions need leading space' % token.text)

    def _label(self, token):
        self._check_name(token)
        if token.kind == 'local':
            key = (self.scope, token.text)
            if key in self.local_definitions:
                first = self.local_definitions[key][0]
                raise ParseError('local label %s is defined twice (first '
                                 'at %s:%d)' % (token.text, first.file,
                                                first.line))
            self.local_definitions[key] = (self.where, self.equates)
            self._add(ir.Label(token.text, self.scope, self.where))
        else:
            self._new_scope()
            self._add(ir.Label(token.text, None, self.where))

    def _equate(self, name, rest):
        self._check_name(name)
        if name.kind != 'ident':
            raise ParseError('a local label cannot be the name of an '
                             'equate')
        tree = expr.parse_all(rest[1:], self.scope)
        self._references(tree)
        self.equates += 1
        position = any(isinstance(node, expr.Dot)
                       for node in expr.walk(tree))
        self._add(ir.Equate(name.text, tree, position,
                            rest[0].text == '.equlab', self.where))

    def _references(self, tree):
        if tree is None:
            return
        for node in expr.walk(tree):
            if isinstance(node, expr.Local):
                self.local_references.append((node, self.where,
                                              self.equates))

    def _check_locals(self):
        for node, where, equates in self.local_references:
            definition = self.local_definitions.get((node.scope, node.name))
            if definition is None:
                self._error('local label %s is not defined in its scope'
                            % node.name, where)
            elif definition[1] != equates:
                self.across_equates += 1

    # ----- macros

    def _macro_body(self, name):
        """The lines up to .endm, which are read and not parsed."""
        source = self.sources[-1]
        body = []
        while source.position < len(source.lines):
            line, self.where = source.lines[source.position]
            source.position += 1
            word = statement_word(line)
            if word == '.endm':
                return body
            if word == '.macro':
                raise ParseError('.macro inside the macro %s' % name)
            body.append(cpp.SourceLine(line, self.where.file,
                                       self.where.line))
        raise ParseError('.macro %s without .endm' % name)

    def _define_macro(self, name, text, directive):
        start = self.where
        body = self._macro_body(name.text)
        self.where = start          # errors below are about the first line
        if name.kind != 'ident' or name.text.lower() in MNEMONICS:
            raise ParseError('"%s" cannot be the name of a macro'
                             % name.text)
        if name.text in self.macros:
            raise ParseError('macro %s is defined twice' % name.text)
        after = lexer.strip_comment(text)[directive.column + len('.macro'):]
        names = macro.parameters(after)
        self.source_instructions += sum(
            1 for line in body
            if (statement_word(line.text) or '').lower() in MNEMONICS)
        self.macros[name.text] = macro.Macro(name.text, names, body,
                                             start.file, start.line)
        self.unit.macros.append(ir.MacroInfo(name.text, names, len(body),
                                             start))
        return None

    def _use_macro(self, definition, argument_text):
        if len(self.sources) > MAX_EXPANSION_DEPTH:
            raise ParseError('macro %s: expansions nested too deeply'
                             % definition.name)
        values = macro.arguments(argument_text)
        lines = macro.expand(definition, values)
        expansions = self.where.expansions + (ir.Expansion(
            definition.name, self.where.file, self.where.line),)
        self.expansion_counts[definition.name] = \
            self.expansion_counts.get(definition.name, 0) + 1
        self.sources.append(_Source(
            [(text, ir.Where(line.file, line.line, expansions))
             for text, line in lines],
            self.scope, self.equates))
        self._new_scope()
        return None

    # ----- directives

    def _directive(self, word, tokens):
        if word == '.section':
            return self._section(tokens)
        if word in DECLARATIONS:
            for part in split_list(tokens):
                if len(part) != 1 or part[0].kind != 'ident':
                    raise ParseError('%s needs a list of names' % word)
                self.unit.declarations.append(
                    ir.Declaration(word[1:], part[0].text, self.where))
            return None
        if word in NUMERIC_DATA:
            values = []
            for part in split_list(tokens):
                tree = expr.parse_all(part, self.scope)
                self._references(tree)
                values.append(tree)
            self._add(ir.Data(word[1:], values, self.where))
            return None
        if word in STRING_DATA:
            values = []
            for part in split_list(tokens):
                if len(part) != 1 or part[0].kind != 'string':
                    raise ParseError('%s needs a list of strings' % word)
                values.append(part[0].value)
            self._add(ir.Data(word[1:], values, self.where))
            return None
        if word in ('.space', '.fillto'):
            first, fill = self._one_or_two(word, tokens)
            kind = ir.Space if word == '.space' else ir.FillTo
            self._add(kind(first, fill, self.where))
            return None
        if word == '.align':
            tree = expr.parse_all(tokens, self.scope)
            self._add(ir.Align(tree, self.where))
            return None
        if word == '.incbin':
            if len(tokens) != 1 or tokens[0].kind != 'string':
                raise ParseError('.incbin needs a file name in quotes')
            self._add(ir.IncBin(tokens[0].text[1:-1], self.where))
            return None
        if word == '.rtmodel':
            return self._rtmodel(tokens)
        if word == '.end':
            return 'end'
        if word == '.endm':
            raise ParseError('.endm without .macro')
        if word in ('.equ', '.equlab', '.macro'):
            raise ParseError('%s needs a name in the first column' % word)
        raise ParseError('unknown directive %s' % word)

    def _one_or_two(self, word, tokens):
        parts = split_list(tokens)
        if len(parts) > 2:
            raise ParseError('%s takes one or two values' % word)
        trees = [expr.parse_all(part, self.scope) for part in parts]
        for tree in trees:
            self._references(tree)
        return trees[0], trees[1] if len(trees) == 2 else None

    def _section(self, tokens):
        parts = split_list(tokens)
        for part in parts:
            if len(part) != 1 or part[0].kind != 'ident':
                raise ParseError('.section needs a name, then a kind and '
                                 'modifiers')
        name = parts[0][0].text
        kind = None
        modifiers = []
        for part in parts[1:]:
            word = part[0].text.lower()
            if word in SECTION_KINDS and kind is None:
                kind = word
            elif word in SECTION_MODIFIERS:
                modifiers.append(word)
            else:
                raise ParseError('unknown section kind or modifier "%s"'
                                 % part[0].text)
        self.fragment = ir.Fragment(name, kind, tuple(modifiers),
                                    self.where)
        self.unit.fragments.append(self.fragment)
        return None

    def _rtmodel(self, tokens):
        if (len(tokens) != 3 or tokens[0].kind != 'ident'
                or tokens[1].text != ',' or tokens[2].kind != 'string'):
            raise ParseError('.rtmodel needs a name and a string')
        self.unit.rtmodels.append(
            ir.RtModel(tokens[0].text, tokens[2].text[1:-1], self.where))
        return None


def parse_lines(lines, path):
    """The Unit for the preprocessed `lines` (cpp.SourceLine) of the
    source file `path`, and the counts that only the parser knows:
    a dictionary with

      expansions            uses of each macro, by name
      source_instructions   instruction lines as written: macro bodies
                            count once, their uses do not count. A
                            body line counts when its mnemonic is
                            written out; upstream makes no mnemonic
                            from a macro argument.
      scopes                number of local label scopes
      across_equates        references to a local label with an equate
                            between the reference and the label
    """
    parser = Parser(path)
    unit = parser.run(lines)
    counts = {'expansions': parser.expansion_counts,
              'source_instructions': parser.source_instructions,
              'scopes': parser.scope_count,
              'across_equates': parser.across_equates}
    return unit, counts
