"""How much of the release image stands behind each number of the layout.

The layout recovery (tools/v816/place.py) takes numbers from the image.
A number that two things give has been checked: if one of them had been
misread, the other would disagree and sections.finish() would report
the conflict. A number that one hole gives has not: a wrong reading of
that hole would go unnoticed. Later stages of the port build on these
addresses, so they need to know which ones rest on a single reading.

The things that count, for the number of an atom:

  a reference    a hole of a placed fragment whose bytes give the
                 number, or its low 16 bits (a place.Constraint), and
                 agree with the number that was kept
  the bytes      for the address of a fragment with bytes, placed with
                 every test passed: the bytes of the image there are
                 those of the fragment. For the linker's data_init_table
                 (sections.py), whose address is .sectionStart
                 data_init_table: the image has the bytes of the table
                 that was made from the other fragments
  the extent     for a section operator, the fragments of the section
                 (placed by their own evidence, the table included when
                 its bytes are there) or the block of the rules file
                 that fills its memory

An atom whose number rests on exactly one reference and nothing else is
"single evidence". The support of the address of the linker's table
is that of .sectionStart data_init_table.
"""

from typing import NamedTuple

from . import linear, sections


class Evidence(NamedTuple):
    """support  by atom, how many things give its number
    single   the atoms whose number rests on one reference, each as
             (atom, the place.Constraint of that reference), sorted"""
    support: dict
    single: list


def _agreeing(constraints, number):
    return [constraint for constraint in constraints
            if number & constraint.mask == constraint.value]


def _table_in_image(program, finished, memory):
    """True when `memory` has the bytes of the linker's table where it
    was placed."""
    address = finished.addresses.get(sections.INIT_TABLE_KEY)
    if address is None:
        return False
    table = program.fragments[sections.INIT_TABLE_KEY].data
    try:
        return memory.read(address, len(table)) == table
    except KeyError:
        return False


def weigh(program, layout, finished, memory):
    """The Evidence for `layout` (place.Layout) and `finished`
    (sections.Finished) of `program` (link.Program) in `memory`, the
    memimage.MemoryImage of the release."""
    checked = layout.addresses()
    table = _table_in_image(program, finished, memory)
    if table:
        checked[sections.INIT_TABLE_KEY] = \
            finished.addresses[sections.INIT_TABLE_KEY]
    extent_atoms = set(sections.operators(
        sections.blocks(program.rules)))
    extent_atoms.update(sections.operators(
        sections.extents(program, checked)))
    table_start = (linear.SECTION, 'sectionStart', sections.INIT_TABLE)
    support = {}
    single = []
    atoms = set(layout.constraints)
    atoms.update(program.fragments[key].atom for key in layout.placements)
    for atom in sorted(atoms):
        number = finished.known.get(atom)
        if number is None:
            continue
        references = _agreeing(layout.constraints.get(atom, ()), number)
        others = 0
        if atom[0] == linear.FRAGMENT:
            fragment = program.fragments[atom[1:]]
            placement = layout.placements.get(fragment.key)
            if (placement is not None and placement.exact
                    and fragment.initialised and fragment.size):
                others = 1
        elif atom == table_start:
            others = int(table)
        elif atom in extent_atoms:
            others = 1
        support[atom] = len(references) + others
        if len(references) == 1 and not others:
            single.append((atom, references[0]))
    return Evidence(support, single)


def fragment_support(evidence, key):
    """The support of the address of the fragment `key`: for the
    linker's table, that of the .sectionStart it is placed at."""
    if key == sections.INIT_TABLE_KEY:
        atom = (linear.SECTION, 'sectionStart', sections.INIT_TABLE)
    else:
        atom = (linear.FRAGMENT,) + key
    return evidence.support.get(atom, 0)
