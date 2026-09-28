"""Reader of a Calypsi linker rules file (src/iigs/iigs.scm and others).

The file is Scheme data (manual, 23.8):

    (define memories
      '((memory NAME (address (#xFIRST . #xLAST))
                (section RULE ...))
        (block NAME (size #xSIZE))
        (base-address SYMBOL MEMORY OFFSET)))

A section RULE is a name (free placement in the memory), (NAME #xADDRESS)
(fixed placement) or (NAME (#xFIRST . #xLAST)) (restricted placement).
A memory can have several (section ...) lists.

Only what upstream's files use is understood; placement groups, scatter
rules and memory types are an error, so that a change of upstream's
rules cannot pass without notice.
"""

import re
from typing import Dict, List, NamedTuple, Optional, Tuple


class ScmError(ValueError):
    """The text is not a rules file that this reader understands."""


class SectionRule(NamedTuple):
    """A section that a memory accepts. `first` and `last` bound the
    addresses the section may take; for a fixed placement `fixed` is
    true and `first` is the address of the section."""
    name: str
    first: int
    last: int
    fixed: bool


class Memory(NamedTuple):
    """A memory region: `first` and `last` are its first and last
    address."""
    name: str
    first: int
    last: int
    sections: Tuple[SectionRule, ...]

    def rule(self, section: str) -> Optional[SectionRule]:
        """The rule for `section`, or None when the memory does not
        accept it."""
        for rule in self.sections:
            if rule.name == section:
                return rule
        return None


class Rules(NamedTuple):
    """A rules file. `blocks` maps the name of a block (a section that
    the linker makes) to its size; `base_addresses` maps a symbol to
    its value."""
    memories: Tuple[Memory, ...]
    blocks: Dict[str, int]
    base_addresses: Dict[str, int]

    def memory(self, name: str) -> Memory:
        for memory in self.memories:
            if memory.name == name:
                return memory
        raise ScmError('no memory %s' % name)

    def accepting(self, section: str) -> List[Tuple[Memory, SectionRule]]:
        """The memories that accept `section`, each with its rule, in
        the order of the file."""
        found = []
        for memory in self.memories:
            rule = memory.rule(section)
            if rule is not None:
                found.append((memory, rule))
        return found


_TOKEN_RE = re.compile(r"""
    (?P<space>\s+)
  | (?P<comment>;[^\n]*)
  | (?P<open>\()
  | (?P<close>\))
  | (?P<quote>')
  | (?P<atom>[^\s()';]+)
""", re.VERBOSE)

_DOT = '.'


def _atom(text):
    lower = text.lower()
    try:
        if lower.startswith('#x'):
            return int(lower[2:], 16)
        if lower.startswith('#b'):
            return int(lower[2:], 2)
        if lower.startswith('#o'):
            return int(lower[2:], 8)
        if lower.startswith('#d'):
            return int(lower[2:], 10)
        if re.fullmatch(r'[-+]?[0-9]+', text):
            return int(text, 10)
    except ValueError:
        raise ScmError('bad number %s' % text)
    return text


def read(text):
    """The expressions of `text`: lists are Python lists, numbers are
    integers, symbols are strings, a dotted pair (a . b) is the tuple
    (a, b). A quote is dropped: the file holds data only."""
    stack = [[]]
    for match in _TOKEN_RE.finditer(text):
        kind = match.lastgroup
        if kind == 'open':
            stack.append([])
        elif kind == 'close':
            if len(stack) == 1:
                raise ScmError('")" without "("')
            items = stack.pop()
            stack[-1].append(_pair(items))
        elif kind == 'atom':
            stack[-1].append(_atom(match.group()))
    if len(stack) != 1:
        raise ScmError('"(" without ")"')
    return stack[0]


def _pair(items):
    if _DOT not in items:
        return items
    if len(items) != 3 or items[1] != _DOT:
        raise ScmError('bad dotted pair')
    return (items[0], items[2])


def _range(value, what):
    if (not isinstance(value, tuple) or not isinstance(value[0], int)
            or not isinstance(value[1], int) or value[0] > value[1]):
        raise ScmError('%s: an address range (first . last) expected'
                       % what)
    return value


def _section_rule(item, memory_name, first, last):
    if isinstance(item, str):
        return SectionRule(item, first, last, False)
    what = 'memory %s' % memory_name
    if (isinstance(item, list) and len(item) == 2
            and isinstance(item[0], str)):
        name, place = item
        if isinstance(place, int):
            if not first <= place <= last:
                raise ScmError('%s: section %s at $%06X is outside the '
                               'memory' % (what, name, place))
            return SectionRule(name, place, last, True)
        low, high = _range(place, '%s, section %s' % (what, name))
        if low < first or high > last:
            raise ScmError('%s: the range of section %s is outside the '
                           'memory' % (what, name))
        return SectionRule(name, low, high, False)
    raise ScmError('%s: bad section rule %r' % (what, item))


def _memory(form):
    if len(form) < 3 or not isinstance(form[1], str):
        raise ScmError('bad memory rule %r' % (form,))
    name = form[1]
    address = None
    sections = []
    for clause in form[2:]:
        if not isinstance(clause, list) or not clause:
            raise ScmError('memory %s: bad clause %r' % (name, clause))
        if clause[0] == 'address' and len(clause) == 2:
            address = _range(clause[1], 'memory %s' % name)
        elif clause[0] == 'section':
            sections.append(clause[1:])
        else:
            raise ScmError('memory %s: the clause "%s" is not supported'
                           % (name, clause[0]))
    if address is None:
        raise ScmError('memory %s has no address' % name)
    rules = tuple(_section_rule(item, name, *address)
                  for group in sections for item in group)
    return Memory(name, address[0], address[1], rules)


def parse(text):
    """The Rules of the rules file `text`."""
    forms = read(text)
    if (len(forms) != 1 or not isinstance(forms[0], list)
            or len(forms[0]) != 3 or forms[0][:2] != ['define', 'memories']
            or not isinstance(forms[0][2], list)):
        raise ScmError('the file must be one (define memories \'(...))')
    memories = []
    blocks = {}
    bases = []
    for form in forms[0][2]:
        if not isinstance(form, list) or not form:
            raise ScmError('bad rule %r' % (form,))
        if form[0] == 'memory':
            memory = _memory(form)
            if any(memory.name == other.name for other in memories):
                raise ScmError('memory %s is defined twice' % memory.name)
            memories.append(memory)
        elif (form[0] == 'block' and len(form) == 3
                and isinstance(form[1], str)
                and isinstance(form[2], list) and len(form[2]) == 2
                and form[2][0] == 'size' and isinstance(form[2][1], int)):
            blocks[form[1]] = form[2][1]
        elif (form[0] == 'base-address' and len(form) == 4
                and isinstance(form[3], int)):
            bases.append(form[1:])
        else:
            raise ScmError('the rule "%s" is not supported' % form[0])
    rules = Rules(tuple(memories), blocks, {})
    for symbol, memory, offset in bases:
        rules.base_addresses[symbol] = rules.memory(memory).first + offset
    return rules


def load(path):
    """The Rules of the file `path`."""
    with open(path) as stream:
        return parse(stream.read())
