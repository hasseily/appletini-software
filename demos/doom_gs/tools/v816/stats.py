"""Counts over the sources and over the IR, for docs/FRONTEND_STATS.md.

Two kinds of count, because the research notes counted source lines and
the translator works on expanded instructions:

- source_counts reads files as they are written. Nothing is
  preprocessed or expanded: both sides of each #if count, an include
  file counts once, a macro body counts once and its uses do not.
- unit_counts reads the IR of the default build: what the assembler
  encodes.

Both use the same names for the constructs, so that the tables can stand
side by side.
"""

import re
from collections import Counter

from . import expr, ir, lexer, parse
from .mnemonics import MNEMONICS

# Constructs that are counted by mnemonic: name -> mnemonics.
MNEMONIC_GROUPS = (
    ('rep/sep', ('rep', 'sep')),
    ('jsl', ('jsl',)),
    ('jsr', ('jsr',)),
    ('phb/plb', ('phb', 'plb')),
    ('xba', ('xba',)),
    ('pei', ('pei',)),
    ('pea', ('pea',)),
    ('phd/pld', ('phd', 'pld')),
    ('tcd', ('tcd',)),
    ('tsc/tcs', ('tsc', 'tcs')),
    ('txy/tyx', ('txy', 'tyx')),
    ('brl', ('brl',)),
    ('stz', ('stz',)),
    ('bra', ('bra',)),
    ('phx/phy/plx/ply', ('phx', 'phy', 'plx', 'ply')),
)
# Constructs that are counted by the form of the operand.
OPERAND_CONSTRUCTS = ('long:', '[dp]', ',s', '## immediate', '.near',
                      'jmp long:')
# MVN is never written as a mnemonic. It is counted where a .byte line
# starts with the opcode and has three values (the instruction with its
# two bank bytes) or one (the bank bytes are on the next lines). Other
# lines that start with the value are tables.
MVN_OPCODE = 0x54
MVN_LENGTHS = (1, 3)

_MACRO_ARGUMENT_RE = re.compile(r'\\([A-Za-z_])')


def _group_counts(mnemonics):
    """Counter of MNEMONIC_GROUPS names from a Counter of mnemonics."""
    return Counter({name: sum(mnemonics[member] for member in members)
                    for name, members in MNEMONIC_GROUPS})


def _statement_tokens(text):
    """The tokens of a source line after its label; [] when the line
    cannot be read as assembly (a preprocessor line, for one)."""
    if text.lstrip().startswith('#'):
        return []
    # "\name" in a macro body: count the line as if the name were there
    text = _MACRO_ARGUMENT_RE.sub(r'\1', lexer.strip_comment(text))
    try:
        tokens = lexer.tokenize(text)
    except lexer.LexError:
        return []
    if tokens and tokens[0].column == 0:
        # a label, or a label made by a preprocessor macro: "L(name):"
        position = 1
        if position < len(tokens) and tokens[position].text == '(':
            while (position < len(tokens)
                   and tokens[position].text != ')'):
                position += 1
            position += 1
        if position < len(tokens) and tokens[position].text == ':':
            position += 1
        return tokens[position:]
    if len(tokens) > 1 and tokens[1].text == ':':
        return tokens[2:]
    return tokens


def _source_constructs(mnemonic, operand):
    """The OPERAND_CONSTRUCTS of one instruction line, from tokens."""
    found = []
    texts = [token.text for token in operand]
    lowered = [text.lower() for text in texts]
    if any(lowered[index] == 'long' and texts[index + 1] == ':'
           for index in range(len(texts) - 1)):
        found.append('long:')
        if mnemonic == 'jmp':
            found.append('jmp long:')
    if texts[:1] == ['[']:
        found.append('[dp]')
    if any(lowered[index:index + 2] == [',', 's']
           for index in range(len(lowered))):
        found.append(',s')
    if texts[:1] == ['##']:
        found.append('## immediate')
    if '.near' in lowered:
        found.append('.near')
    return found


def source_counts(paths):
    """Counts over the text of the files `paths`.

    Returns a dictionary: 'lines', 'macro_definitions' (a list of
    (path, line number, name) of the .macro lines), 'instruction_lines',
    'mnemonics' (Counter), 'constructs' (Counter with the names of
    MNEMONIC_GROUPS and OPERAND_CONSTRUCTS and 'mvn'), 'preprocessor'
    (Counter of directive names).
    """
    lines = 0
    macro_definitions = []
    mnemonics = Counter()
    constructs = Counter()
    preprocessor = Counter()
    for path in paths:
        with open(path, encoding='utf-8', errors='surrogateescape') as file:
            content = file.read().split('\n')
        if content and content[-1] == '':
            content.pop()
        lines += len(content)
        for number, line in enumerate(content, 1):
            directive = re.match(r'\s*#\s*([a-z]+)', line)
            if directive:
                preprocessor[directive.group(1)] += 1
                continue
            tokens = _statement_tokens(line)
            if not tokens:
                continue
            word = tokens[0].text.lower()
            if word == '.macro':
                macro_definitions.append(
                    (str(path), number, line.split()[0]))
            if tokens[0].kind == 'ident' and word in MNEMONICS:
                mnemonics[word] += 1
                constructs.update(_source_constructs(word, tokens[1:]))
            elif word == '.byte':
                values = parse.split_list(tokens[1:])
                if (len(values) in MVN_LENGTHS and len(values[0]) == 1
                        and values[0][0].value == MVN_OPCODE):
                    constructs['mvn'] += 1
    constructs.update(_group_counts(mnemonics))
    return {'lines': lines, 'macro_definitions': macro_definitions,
            'instruction_lines': sum(mnemonics.values()),
            'mnemonics': mnemonics, 'constructs': constructs,
            'preprocessor': preprocessor}


def _top_relocation(tree):
    """The relocation operator at the top of `tree`, or None."""
    return tree.op if isinstance(tree, expr.Reloc) else None


def _size_syntax(instruction):
    """How the operand size is written: a prefix, a relocation operator
    at the top of the expression, both, or '' for neither."""
    parts = []
    if instruction.prefix:
        parts.append(instruction.prefix + ':')
    relocation = _top_relocation(instruction.operand)
    if relocation:
        parts.append('.' + relocation)
    return ' '.join(parts)


def unit_counts(units):
    """Counts over the IR of `units`.

    Returns a dictionary: 'instructions', 'mnemonics', 'modes',
    'sizes' (Counter of how the operand size is written), 'constructs',
    'fragments' (Counter of section names), 'filled_fragments' (the
    same without the fragments that hold nothing but equates),
    'section_kinds' (section name -> set of kinds as written),
    'labels', 'local_labels', 'equates', 'position_equates', 'data'
    (Counter of directive names), 'declarations' (Counter),
    'nested_relocations' (relocation operators below the top of an
    expression).
    """
    mnemonics = Counter()
    modes = Counter()
    sizes = Counter()
    constructs = Counter()
    fragments = Counter()
    filled_fragments = Counter()
    section_kinds = {}
    data = Counter()
    declarations = Counter()
    counts = Counter()
    for unit in units:
        for declaration in unit.declarations:
            declarations[declaration.directive] += 1
        for fragment in unit.fragments:
            fragments[fragment.section] += 1
            if any(not isinstance(item, ir.Equate)
                   for item in fragment.items):
                filled_fragments[fragment.section] += 1
            section_kinds.setdefault(fragment.section, set()).add(
                fragment.kind or '(none)')
            for item in fragment.items:
                _count_item(item, mnemonics, modes, sizes, constructs,
                            data, counts)
    constructs.update(_group_counts(mnemonics))
    return {'instructions': sum(mnemonics.values()),
            'mnemonics': mnemonics, 'modes': modes, 'sizes': sizes,
            'constructs': constructs, 'fragments': fragments,
            'filled_fragments': filled_fragments,
            'section_kinds': section_kinds, 'data': data,
            'declarations': declarations,
            'labels': counts['labels'],
            'local_labels': counts['local_labels'],
            'equates': counts['equates'],
            'position_equates': counts['position_equates'],
            'nested_relocations': counts['nested_relocations']}


def _count_item(item, mnemonics, modes, sizes, constructs, data, counts):
    if isinstance(item, ir.Instruction):
        mnemonics[item.mnemonic] += 1
        modes[item.mode] += 1
        if item.operand is not None:
            sizes[_size_syntax(item)] += 1
            _count_operand(item, constructs, counts)
    elif isinstance(item, ir.Label):
        counts['local_labels' if item.local else 'labels'] += 1
    elif isinstance(item, ir.Equate):
        counts['equates'] += 1
        if item.position:
            counts['position_equates'] += 1
    elif isinstance(item, ir.Data):
        data['.' + item.directive] += 1
        if (item.directive == 'byte' and len(item.values) in MVN_LENGTHS
                and item.values[0] == expr.Number(MVN_OPCODE)):
            constructs['mvn'] += 1
    else:
        data['.' + type(item).__name__.lower()] += 1


def _count_operand(item, constructs, counts):
    if item.prefix == 'long':
        constructs['long:'] += 1
        if item.mnemonic == 'jmp':
            constructs['jmp long:'] += 1
    if item.mode in ('[e]', '[e],y'):
        constructs['[dp]'] += 1
    if item.mode in ('e,s', '(e,s),y'):
        constructs[',s'] += 1
    if item.mode == '##':
        constructs['## immediate'] += 1
    nodes = list(expr.walk(item.operand))
    if any(isinstance(node, expr.Reloc) and node.op == 'near'
           for node in nodes):
        constructs['.near'] += 1
    counts['nested_relocations'] += sum(
        isinstance(node, expr.Reloc) for node in nodes[1:])
