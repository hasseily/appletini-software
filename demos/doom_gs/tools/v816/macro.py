"""Assembler macros: NAME .macro parameters ... .endm

Section 21.11 of the Calypsi manual. A use of the macro is replaced by
its body, in which "\\name" stands for the argument of the parameter
`name`. Where two parameter names match, the longer one wins ("\\aa"
before "\\a"); nothing marks the end of a name, so "\\regx" with a
parameter "reg" is the argument followed by "x".

Substitution works on the text of the line, before it is split into
tokens, which is how "de\\reg" can become the mnemonic "dex".

Arguments are separated by commas; the manual has no way to put a comma
in an argument other than .argdelim, which the sources do not use. A
comma inside a string or character constant does not separate. The
manual does not say what a use with too few arguments means, and every
use in the sources has as many arguments as the macro has parameters,
so any other number is an error here.

The local labels of an expansion are the business of the parser: this
module only produces the lines.
"""

import re
from collections import namedtuple

from . import lexer

Macro = namedtuple('Macro', 'name parameters body file line')
Macro.__doc__ = """A definition. `body` is a list of cpp.SourceLine;
`file` and `line` are the place of the .macro directive."""

_QUOTED_RE = re.compile(r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)[^']*\'''')


class MacroError(ValueError):
    """A definition or a use of a macro is wrong."""


def parameters(text):
    """The parameter names of the text after ".macro"."""
    text = text.strip()
    if not text:
        return ()
    names = tuple(name.strip() for name in text.split(','))
    for name in names:
        if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', name):
            raise MacroError('bad macro parameter "%s"' % name)
    if len(set(names)) != len(names):
        raise MacroError('a macro parameter is named twice')
    return names


def arguments(text):
    """The arguments of a use: the text after the macro name, split at
    the commas, without the ";" comment."""
    text = lexer.strip_comment(text).strip()
    if not text:
        return []
    found = []
    start = 0
    position = 0
    while position < len(text):
        quoted = _QUOTED_RE.match(text, position)
        if quoted:
            position = quoted.end()
        elif text[position] == ',':
            found.append(text[start:position].strip())
            position += 1
            start = position
        else:
            position += 1
    found.append(text[start:].strip())
    return found


def substitute(line, values):
    """`line` with each "\\name" replaced by values[name].

    The ";" comment of the line is dropped first, so that a backslash in
    a comment means nothing. A backslash that no parameter follows stays
    (it may be an escape in a string).
    """
    line = lexer.strip_comment(line)
    if '\\' not in line or not values:
        return line
    names = sorted(values, key=len, reverse=True)
    pattern = re.compile(r'\\(%s)' % '|'.join(map(re.escape, names)))
    return pattern.sub(lambda match: values[match.group(1)], line)


def expand(macro, argument_list):
    """The lines of one use of `macro`, as pairs (text, body line)."""
    if len(argument_list) != len(macro.parameters):
        raise MacroError('macro %s takes %d arguments, not %d'
                         % (macro.name, len(macro.parameters),
                            len(argument_list)))
    values = dict(zip(macro.parameters, argument_list))
    return [(substitute(line.text, values), line) for line in macro.body]
