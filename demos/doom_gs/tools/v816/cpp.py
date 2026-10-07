"""C-style preprocessor for the upstream assembly sources.

The Calypsi assembler runs its input through "a full-featured C
preprocessor" (manual, 21.2.3). A system cpp is not safe for these
sources, because "##" is the assembler's 16-bit immediate marker, so the
port has its own.

What is implemented, with C semantics:
- #include "file" and <file>; #define (object-like and function-like);
  #undef; #if, #ifdef, #ifndef, #elif, #else, #endif; #error
- "defined NAME" and "defined(NAME)" and integer expressions in #if
- "#" before a parameter (stringify) and "##" (paste), in #define bodies
- /* */ and // comments; backslash-newline

What is particular to assembly:
- Outside #define bodies "#" and "##" are ordinary text.
- "$" is not an identifier character, so the local label "loop$" is the
  identifier "loop" followed by "$".
- A ";" comment means nothing here: it is text, as it is for a C
  preprocessor. A #define body therefore keeps its ";" comment, and the
  assembler drops it where the macro is used.
- A quote without a closing quote on its line makes the rest of the
  line one piece of text ("don't" in a ";" comment): nothing after it is
  expanded, and no comment starts there. C calls this an error; clang
  in its assembler mode does what is described here.

Not implemented, because the sources do not need it: variadic macros,
__FILE__ and __LINE__, #line, #pragma, and a macro call whose argument
list continues on the next line (an error here).
"""

import re
from collections import namedtuple
from pathlib import Path

SourceLine = namedtuple('SourceLine', 'text file line')
SourceLine.__doc__ = """One line of preprocessor output.

`file` and `line` say where the line came from: the line that holds the
text, not the place of a #define that contributed to it."""

_Token = namedtuple('_Token', 'kind text hidden')
# kind: 'id', 'num', 'str' (string or character constant), 'open' (from a
# quote without its closing quote to the end of the line), 'ws', 'paste',
# 'stringify' or 'other'. `hidden` is the set of macro names that must not
# be expanded in this token again.

_Macro = namedtuple('_Macro', 'name params body')
# params is None for an object-like macro, else a tuple of names.

_TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\f\v]+)
  | (?P<id>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<num>\.?[0-9](?:[eEpP][+-]|[A-Za-z_0-9.])*)
  | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<open>["'][^\n]*)
  | (?P<other>.)
""", re.VERBOSE | re.DOTALL)

_DIRECTIVE_RE = re.compile(r'[ \t]*#[ \t]*([A-Za-z_]+)(.*)', re.DOTALL)
_NO_HIDDEN = frozenset()


class CppError(Exception):
    """An error in the input, with its file and line."""

    def __init__(self, message, file, line):
        Exception.__init__(self, '%s:%d: %s' % (file, line, message))
        self.file = file
        self.line = line


def _tokens(text):
    """The preprocessing tokens of a line of text."""
    return [_Token(match.lastgroup, match.group(), _NO_HIDDEN)
            for match in _TOKEN_RE.finditer(text)]


def _text(tokens):
    return ''.join(token.text for token in tokens)


def _strip(tokens):
    """`tokens` without white space at its ends."""
    start, end = 0, len(tokens)
    while start < end and tokens[start].kind == 'ws':
        start += 1
    while end > start and tokens[end - 1].kind == 'ws':
        end -= 1
    return tokens[start:end]


def strip_comments(text):
    """`text` with each C comment replaced by one space.

    Newlines inside a comment are kept, so the line numbers stay right.
    Returns the text and the offset of a comment that does not end, or
    None.
    """
    out = []
    position = 0
    length = len(text)
    while position < length:
        char = text[position]
        if char in '"\'':
            match = _TOKEN_RE.match(text, position)
            out.append(match.group())
            position = match.end()
        elif text.startswith('/*', position):
            end = text.find('*/', position + 2)
            if end < 0:
                return ''.join(out), position
            out.append(' ' + '\n' * text.count('\n', position, end))
            position = end + 2
        elif text.startswith('//', position):
            end = text.find('\n', position)
            position = length if end < 0 else end
            out.append(' ')
        else:
            out.append(char)
            position += 1
    return ''.join(out), None


def logical_lines(text):
    """Pairs (line number, text) of `text` after line splicing and the
    removal of comments. A spliced line has the number of its first
    line."""
    text = text.replace('\r\n', '\n')
    spliced = []
    number = 1
    pending = None
    for line in text.split('\n'):
        if pending is not None:
            pending = (pending[0], pending[1] + line)
        else:
            pending = (number, line)
        number += 1
        if pending[1].endswith('\\'):
            pending = (pending[0], pending[1][:-1])
        else:
            spliced.append(pending)
            pending = None
    if pending is not None:
        spliced.append(pending)
    if spliced and spliced[-1][1] == '':
        spliced.pop()           # the text after the last newline
    joined, open_comment = strip_comments(
        '\n'.join(line for _, line in spliced))
    if open_comment is not None:
        index = joined.count('\n')
        return None, spliced[index][0]
    return list(zip((number for number, _ in spliced),
                    joined.split('\n'))), None


class _Condition:
    """One open #if: whether its group is read, and what may follow."""

    def __init__(self, parent_active, active, line):
        self.parent_active = parent_active
        self.active = parent_active and active
        self.taken = active          # a group of this #if has been read
        self.seen_else = False
        self.line = line


class Preprocessor:
    """Preprocesses files with one set of include paths and definitions.

    `include_paths` are the -I directories, in order. `defines` maps the
    names of the -D flags to their values (strings or integers). The
    macro table is reset for each call of process_file, as it is for each
    run of the assembler.
    """

    MAX_INCLUDE_DEPTH = 32

    def __init__(self, include_paths=(), defines=None):
        self.include_paths = [Path(path) for path in include_paths]
        self.defines = dict(defines or {})
        self.macros = {}
        self.included = []

    # ----- entry points

    def process_file(self, path):
        """The output lines for the source file `path`."""
        path = Path(path)
        self._reset(path.parent)
        return self._file(path, [])

    def _reset(self, directory):
        self.main_directory = directory
        self.included = []
        self.macros = {}
        for name, value in self.defines.items():
            self.macros[name] = _Macro(name, None, _tokens(str(value)))

    # ----- files and lines

    def _file(self, path, stack):
        try:
            text = path.read_text(encoding='utf-8', errors='surrogateescape')
        except OSError as error:
            raise CppError('cannot read: %s' % error.strerror, str(path), 0)
        return self._lines(text, str(path), path.parent, stack)

    def _lines(self, text, name, directory, stack):
        lines, bad_line = logical_lines(text)
        if lines is None:
            raise CppError('comment without end', name, bad_line)
        out = []
        conditions = []
        for number, line in lines:
            active = not conditions or conditions[-1].active
            match = _DIRECTIVE_RE.match(line)
            if match:
                self._directive(match.group(1), match.group(2), name,
                                number, directory, stack, conditions, out)
            elif active:
                try:
                    expanded = self._expand(_tokens(line))
                except _ExpansionError as error:
                    raise CppError(str(error), name, number)
                out.append(SourceLine(_text(expanded), name, number))
        if conditions:
            raise CppError('#if without #endif', name, conditions[-1].line)
        return out

    def _directive(self, word, rest, name, number, directory, stack,
                   conditions, out):
        active = not conditions or conditions[-1].active

        def fail(message):
            raise CppError(message, name, number)

        if word in ('if', 'ifdef', 'ifndef'):
            value = False
            if active:
                value = self._condition(word, rest, fail)
            conditions.append(_Condition(active, value, number))
        elif word in ('elif', 'else', 'endif'):
            if not conditions:
                fail('#%s without #if' % word)
            condition = conditions[-1]
            if word == 'endif':
                conditions.pop()
                return
            if condition.seen_else:
                fail('#%s after #else' % word)
            if word == 'else':
                condition.seen_else = True
                value = True
            else:
                value = (condition.parent_active and not condition.taken
                         and self._condition('if', rest, fail))
            condition.active = (condition.parent_active
                                and not condition.taken and value)
            condition.taken = condition.taken or condition.active
        elif not active:
            return
        elif word == 'define':
            self._define(rest, fail)
        elif word == 'undef':
            names = rest.split()
            if len(names) != 1:
                fail('#undef takes one name')
            self.macros.pop(names[0], None)
        elif word == 'include':
            out.extend(self._include(rest, name, directory, stack, fail))
        elif word == 'error':
            fail('#error ' + rest.strip())
        else:
            fail('unknown directive #%s' % word)

    def _condition(self, word, rest, fail):
        if word == 'if':
            try:
                return self._if_value(rest) != 0
            except _ExpansionError as error:
                fail(str(error))
        names = rest.split()
        if len(names) != 1:
            fail('#%s takes one name' % word)
        return (names[0] in self.macros) == (word == 'ifdef')

    def _include(self, rest, name, directory, stack, fail):
        try:
            target = _text(_strip(self._expand(_tokens(rest))))
        except _ExpansionError as error:
            fail(str(error))
        if len(target) > 2 and target[0] == '"' and target[-1] == '"':
            places = [directory, self.main_directory] + self.include_paths
        elif len(target) > 2 and target[0] == '<' and target[-1] == '>':
            places = self.include_paths
        else:
            fail('#include needs "file" or <file>')
        if len(stack) >= self.MAX_INCLUDE_DEPTH:
            fail('#include nested too deeply')
        for place in places:
            path = place / target[1:-1]
            if path.is_file():
                self.included.append(path)
                return self._file(path, stack + [name])
        fail('cannot find the include file %s' % target)

    # ----- definitions

    def _define(self, rest, fail):
        tokens = _tokens(rest.lstrip())
        if not tokens or tokens[0].kind != 'id':
            fail('#define needs a name')
        name = tokens[0].text
        params = None
        position = 1
        if position < len(tokens) and tokens[position].text == '(':
            params, position = self._parameters(tokens, position + 1, fail)
        body = self._body(_strip(tokens[position:]), params or (), fail)
        self.macros[name] = _Macro(name, params, body)

    @staticmethod
    def _parameters(tokens, position, fail):
        names = []
        expect_name = True
        while position < len(tokens):
            token = tokens[position]
            position += 1
            if token.kind == 'ws':
                continue
            if token.text == ')' and (not expect_name or not names):
                return tuple(names), position
            if expect_name and token.kind == 'id':
                if token.text in names:
                    fail('parameter %s twice' % token.text)
                names.append(token.text)
                expect_name = False
            elif not expect_name and token.text == ',':
                expect_name = True
            else:
                break
        fail('bad parameter list in #define')

    @staticmethod
    def _body(tokens, params, fail):
        """The body with its "#" and "##" operators marked."""
        body = []
        position = 0
        while position < len(tokens):
            token = tokens[position]
            following = tokens[position + 1:position + 2]
            if token.text == '#' and following and following[0].text == '#':
                while body and body[-1].kind == 'ws':
                    body.pop()
                position += 2
                while position < len(tokens) and tokens[position].kind == 'ws':
                    position += 1
                if not body or position >= len(tokens):
                    fail('"##" at the start or end of a #define body')
                body.append(_Token('paste', '##', _NO_HIDDEN))
                continue
            if token.text == '#' and following:
                after = position + 1
                while after < len(tokens) and tokens[after].kind == 'ws':
                    after += 1
                if after < len(tokens) and tokens[after].text in params:
                    body.append(_Token('stringify', tokens[after].text,
                                       _NO_HIDDEN))
                    position = after + 1
                    continue
            body.append(token)
            position += 1
        return body

    # ----- expansion

    def _expand(self, tokens):
        """`tokens` with all macros expanded."""
        out = []
        tokens = list(tokens)
        position = 0
        while position < len(tokens):
            token = tokens[position]
            macro = self.macros.get(token.text) if token.kind == 'id' \
                else None
            if macro is None or token.text in token.hidden:
                out.append(token)
                position += 1
                continue
            if macro.params is None:
                hidden = token.hidden | {macro.name}
                replaced = self._substitute(macro, [], hidden)
                tokens[position:position + 1] = replaced
                continue
            open_paren = position + 1
            while (open_paren < len(tokens)
                   and tokens[open_paren].kind == 'ws'):
                open_paren += 1
            if open_paren >= len(tokens) or tokens[open_paren].text != '(':
                out.append(token)       # the name without a call
                position += 1
                continue
            arguments, end = self._arguments(macro, tokens, open_paren + 1)
            hidden = (token.hidden & tokens[end - 1].hidden) | {macro.name}
            replaced = self._substitute(macro, arguments, hidden)
            tokens[position:end] = replaced
        return out

    @staticmethod
    def _arguments(macro, tokens, position):
        """The arguments of a call and the position after its ")"."""
        arguments = [[]]
        depth = 0
        while position < len(tokens):
            token = tokens[position]
            position += 1
            if token.text == ')' and depth == 0:
                arguments = [_strip(argument) for argument in arguments]
                if len(macro.params) == 0 and arguments == [[]]:
                    arguments = []
                if len(arguments) != len(macro.params):
                    raise _ExpansionError(
                        'macro %s takes %d arguments, not %d'
                        % (macro.name, len(macro.params), len(arguments)))
                return arguments, position
            if token.text == ',' and depth == 0:
                arguments.append([])
                continue
            if token.text == '(':
                depth += 1
            elif token.text == ')':
                depth -= 1
            arguments[-1].append(token)
        raise _ExpansionError('the call of macro %s does not end on its line'
                              % macro.name)

    def _substitute(self, macro, arguments, hidden):
        """The body of `macro` with its arguments put in."""
        values = dict(zip(macro.params or (), arguments))
        body = macro.body
        out = []
        for index, token in enumerate(body):
            if token.kind == 'paste':
                continue
            if token.kind == 'stringify':
                out.append(_Token('str', _stringify(values[token.text]),
                                  _NO_HIDDEN))
                continue
            pasted = index > 0 and body[index - 1].kind == 'paste'
            pastes = (index + 1 < len(body)
                      and body[index + 1].kind == 'paste')
            if token.kind == 'id' and token.text in values:
                value = values[token.text]
                if not (pasted or pastes):
                    value = self._expand(value)
                piece = list(value)
            else:
                piece = [token]
            if pasted:
                piece = self._paste(out, piece)
            out.extend(piece)
        return [token._replace(hidden=token.hidden | hidden)
                for token in out]

    @staticmethod
    def _paste(out, piece):
        """`piece` with its first token joined to the last of `out`,
        which is removed from `out`."""
        if not out or not piece:
            return piece            # an empty argument: nothing to join
        left = out.pop()
        joined = _tokens(left.text + piece[0].text)
        if len(joined) != 1:
            raise _ExpansionError('pasting "%s" and "%s" does not give one '
                                  'token' % (left.text, piece[0].text))
        return joined + piece[1:]

    # ----- #if expressions

    def _if_value(self, text):
        tokens = self._defined(_tokens(text))
        tokens = [token for token in self._expand(tokens)
                  if token.kind != 'ws']
        parser = _IfParser(tokens)
        value = parser.conditional()
        if parser.position != len(tokens):
            raise _ExpansionError('unexpected "%s" in #if'
                                  % tokens[parser.position].text)
        return value

    def _defined(self, tokens):
        """`tokens` with each "defined" operator replaced by 0 or 1."""
        words = [token for token in tokens if token.kind != 'ws']
        out = []
        position = 0
        while position < len(words):
            token = words[position]
            position += 1
            if token.kind != 'id' or token.text != 'defined':
                out.append(token)
                continue
            texts = [word.text for word in words[position:position + 3]]
            if len(texts) == 3 and texts[0] == '(' and texts[2] == ')':
                name = words[position + 1]
                position += 3
            elif texts:
                name = words[position]
                position += 1
            else:
                raise _ExpansionError('"defined" without a name')
            if name.kind != 'id':
                raise _ExpansionError('"defined" without a name')
            out.append(_Token('num', '1' if name.text in self.macros
                              else '0', _NO_HIDDEN))
        return out


class _ExpansionError(Exception):
    """An error found below the level that knows the file and line."""


def _stringify(tokens):
    text = re.sub(r'\s+', ' ', _text(tokens))
    return '"%s"' % text.replace('\\', '\\\\').replace('"', '\\"')


def _integer(text):
    """The value of an integer constant of C."""
    digits = text.rstrip('uUlL')
    try:
        if digits[:2] in ('0x', '0X'):
            return int(digits[2:], 16)
        if digits[:2] in ('0b', '0B'):
            return int(digits[2:], 2)
        if len(digits) > 1 and digits[0] == '0':
            return int(digits, 8)
        return int(digits, 10)
    except ValueError:
        raise _ExpansionError('bad number "%s" in #if' % text)


_BINARY_LEVELS = (
    ('||',), ('&&',), ('|',), ('^',), ('&',), ('==', '!='),
    ('<', '>', '<=', '>='), ('<<', '>>'), ('+', '-'), ('*', '/', '%'))


def _c_divide(left, right):
    """Division that rounds towards zero, as in C."""
    quotient = abs(left) // abs(right)
    return quotient if (left < 0) == (right < 0) else -quotient


_BINARY = {
    '||': lambda a, b: int(bool(a) or bool(b)),
    '&&': lambda a, b: int(bool(a) and bool(b)),
    '|': lambda a, b: a | b,
    '^': lambda a, b: a ^ b,
    '&': lambda a, b: a & b,
    '==': lambda a, b: int(a == b),
    '!=': lambda a, b: int(a != b),
    '<': lambda a, b: int(a < b),
    '>': lambda a, b: int(a > b),
    '<=': lambda a, b: int(a <= b),
    '>=': lambda a, b: int(a >= b),
    '<<': lambda a, b: a << b,
    '>>': lambda a, b: a >> b,
    '+': lambda a, b: a + b,
    '-': lambda a, b: a - b,
    '*': lambda a, b: a * b,
    '/': _c_divide,
    '%': lambda a, b: a - b * _c_divide(a, b),
}


class _IfParser:
    """Evaluates the tokens of a #if expression.

    Both sides of && and || and all parts of ?: are evaluated; the only
    visible effect is that a division by zero in a part that C would skip
    is an error here.
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def _peek(self, length=1):
        return ''.join(token.text for token
                       in self.tokens[self.position:self.position + length])

    def _operator(self, operators):
        """The operator of `operators` at the position, or None."""
        for length in (2, 1):
            text = self._peek(length)
            if len(text) == length and text in operators:
                # "<" must not match the start of "<<" or "<="
                longer = self._peek(2)
                if length == 1 and len(longer) == 2 and longer in _BINARY:
                    return None
                self.position += length
                return text
        return None

    def conditional(self):
        value = self.binary(0)
        if self._peek() == '?':
            self.position += 1
            if_true = self.conditional()
            if self._peek() != ':':
                raise _ExpansionError('"?" without ":" in #if')
            self.position += 1
            if_false = self.conditional()
            return if_true if value else if_false
        return value

    def binary(self, level):
        if level == len(_BINARY_LEVELS):
            return self.unary()
        value = self.binary(level + 1)
        while True:
            operator = self._operator(_BINARY_LEVELS[level])
            if operator is None:
                return value
            right = self.binary(level + 1)
            if operator in '/%' and right == 0:
                raise _ExpansionError('division by zero in #if')
            value = _BINARY[operator](value, right)

    def unary(self):
        if self.position >= len(self.tokens):
            raise _ExpansionError('#if expression ends early')
        token = self.tokens[self.position]
        self.position += 1
        if token.text == '(':
            value = self.conditional()
            if self._peek() != ')':
                raise _ExpansionError('missing ")" in #if')
            self.position += 1
            return value
        if token.text == '!':
            return int(not self.unary())
        if token.text == '~':
            return ~self.unary()
        if token.text == '-':
            return -self.unary()
        if token.text == '+':
            return self.unary()
        if token.kind == 'id':
            return 0                # a name that is not a macro
        if token.kind == 'num':
            return _integer(token.text)
        if token.kind == 'str' and token.text[0] == "'":
            return _character(token.text)
        raise _ExpansionError('unexpected "%s" in #if' % token.text)


_ESCAPES = {'n': 10, 't': 9, 'r': 13, '0': 0, 'a': 7, 'b': 8, 'f': 12,
            'v': 11, '\\': 92, "'": 39, '"': 34}


def _character(text):
    inner = text[1:-1]
    if len(inner) == 1:
        return ord(inner)
    if len(inner) == 2 and inner[0] == '\\' and inner[1] in _ESCAPES:
        return _ESCAPES[inner[1]]
    raise _ExpansionError('bad character constant %s in #if' % text)
