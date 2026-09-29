"""What the linker makes itself: section extents and data_init_table.

After the layout recovery (tools/v816/place.py) the address of every
fragment is known. finish() adds what follows from the addresses:

Section operators. .sectionStart and .sectionEnd are the first address
of the first fragment of the section and the last address of its last
fragment; .sectionSize is 1 + end - start (manual, 21.10.2). A block of
the rules file (the stack) is a section without fragments; its extent
is known here only when the block fills its memory, which is the case
in upstream's rules. For a section that has neither, the number that
the image gave to the recovery is used, if there is one.

data_init_table. With --hosted the linker writes a table of the
sections that the startup code must fill with zeros (upstream's crt0.s
reads it). The release image has these entries, which init_table()
makes again: for each section of the kind bss, without noinit, in the
order of the names,

    4 bytes   .sectionStart of the section
    4 bytes   0: there is no data to copy
    2 bytes   .sectionSize

The vendor's manual does not describe the table; its form is that of
the image and of crt0.s, and it was read from one image only, the
release (INIT_TABLE_NOTE, which the match report repeats). That image
has no entry that copies data (the second field is always 0) and its
entries are in the order of the names; a program with initialised
data in RAM, or a linker that orders the entries otherwise, would need
more than this. tests/test_sections.py checks both against the release.
The address of the table comes from the recovery (the holes of crt0.s
hold .sectionStart data_init_table), because the linker is free to put
the table anywhere in the memories that accept the section.

Fixed placement. A section with a fixed address in the rules file must
start there; finish() reports a section whose placed fragments do not.
"""

import struct
from typing import NamedTuple

from . import link, linear, objfile, place

LINKER_UNIT = '(linker)'
INIT_TABLE = 'data_init_table'
INIT_TABLE_KEY = (LINKER_UNIT, 0)
INIT_ENTRY = struct.Struct('<IIH')
INIT_TABLE_NOTE = (
    'data_init_table is made again from its form in one image (the '
    'release): entries that clear bss only, in the order of the section '
    'names. An entry that copies data is not supported.')


class Finished(NamedTuple):
    """The layout with what the linker makes.

    addresses   the address of each placed fragment, by key
    known       the number of each atom
    extents     (first address, last address) by section name
    problems    link.Problems
    """
    addresses: dict
    known: dict
    extents: dict
    problems: list


def extents(program, addresses):
    """(first address, last address) of each section that has placed
    fragments with a size."""
    found = {}
    for key, address in addresses.items():
        fragment = program.fragments[key]
        if not fragment.size:
            continue
        last = address + fragment.size - 1
        first, end = found.get(fragment.section, (address, last))
        found[fragment.section] = (min(first, address), max(end, last))
    return found


def init_table(program, addresses):
    """The bytes of data_init_table for the placed fragments."""
    cleared = [key for key in addresses if program.fragments[key].cleared]
    found = extents(program, {key: addresses[key] for key in cleared})
    return b''.join(
        INIT_ENTRY.pack(first, 0, 1 + last - first)
        for _, (first, last) in sorted(found.items()))


def blocks(rules):
    """The extents of the blocks that fill their memory."""
    found = {}
    for name, size in rules.blocks.items():
        accepting = rules.accepting(name)
        if len(accepting) == 1:
            first, last = accepting[0][1].first, accepting[0][1].last
            if 1 + last - first == size:
                found[name] = (first, last)
    return found


def operators(found):
    """The numbers of the section operators for the extents `found`."""
    numbers = {}
    for name, (first, last) in found.items():
        numbers[(linear.SECTION, 'sectionStart', name)] = first
        numbers[(linear.SECTION, 'sectionEnd', name)] = last
        numbers[(linear.SECTION, 'sectionSize', name)] = 1 + last - first
    return numbers


def _misplaced(rules, found):
    """Problems for the sections of `found` (extents by name) that have
    a fixed address in `rules` and do not start there."""
    problems = []
    for name, (first, _) in sorted(found.items()):
        fixed = [rule.first for _, rule in rules.accepting(name)
                 if rule.fixed]
        if fixed and first not in fixed:
            problems.append(link.Problem(
                'the section %s starts at $%06X, its fixed address is $%s'
                % (name, first, ', $'.join('%06X' % address
                                          for address in fixed))))
    return problems


def finish(program, layout):
    """The Finished of `layout` (place.Layout). Adds the fragment of
    data_init_table to `program` when the table has entries."""
    addresses = layout.addresses()
    problems = []
    table = init_table(program, addresses)
    start = layout.known.get((linear.SECTION, 'sectionStart', INIT_TABLE))
    if table and start is None:
        problems.append(link.Problem(
            '%s has %d bytes and no address' % (INIT_TABLE, len(table))))
    elif table:
        program.fragments[INIT_TABLE_KEY] = objfile.ObjectFragment(
            INIT_TABLE_KEY, INIT_TABLE, 'rodata', (), None,
            size=len(table), data=table)
        program.holes[INIT_TABLE_KEY] = []
        addresses[INIT_TABLE_KEY] = start
    found = blocks(program.rules)
    found.update(extents(program, addresses))
    problems += _misplaced(program.rules, found)
    known = dict(layout.known)
    known.update(operators(found))
    for atom, constraints in sorted(layout.constraints.items()):
        if atom not in known and atom[0] != linear.FRAGMENT:
            known[atom] = constraints[0].value
            problems.append(link.Problem(
                'the image gives only the low 16 bits of %s'
                % link.atom_text(atom), constraints[0].key,
                constraints[0].offset))
    for constraint in place.conflicts(layout.constraints, known):
        problems.append(link.Problem(
            'the image has $%X in the bits $%X of %s'
            % (constraint.value, constraint.mask,
               link.atom_text(constraint.atom)),
            constraint.key, constraint.offset))
    return Finished(addresses, known, found, problems)
