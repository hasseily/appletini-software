"""The link map: the address of every fragment, the value of every
symbol.

Later stages of the port need to know where upstream's code and data
are. make() gives the map of one program as dictionaries and lists
that json can write:

    fragments   each fragment of the program: unit, number, section,
                kind, size, the place in the source, and when it is
                placed its address, the method and whether the
                placement is exact (tools/v816/place.py), its
                support (tools/v816/evidence.py: how many independent
                things in the image give the address; 1 means that a
                single reading does) and the address of each label
    dropped     the fragments that are not part of the program
                (link.Program.reachable)
    sections    first and last address of each section
    exported    the value of each exported name
    units       by unit, the value of each name that the unit defines
    linker      the symbols of the rules file, and the names that no
                unit defines with the number that the image gave

A value is a number, or null when it is not known: a name in a
fragment without an address, or an equate with a relocation operator.
The map holds names and numbers of upstream's program, so its place is
build/.
"""

from . import evidence as evidence_
from . import linear


def number(value, known):
    """The number of the linear.Value `value`, or None."""
    if value.reloc:
        return None
    result = value.linear.substitute(known)
    return result.constant if result.is_constant else None


def _fragment(fragment, placement, address, support):
    entry = {
        'unit': fragment.key[0], 'number': fragment.key[1],
        'section': fragment.section, 'kind': fragment.kind,
        'modifiers': list(fragment.modifiers), 'size': fragment.size,
        'initialised': fragment.initialised,
        'file': fragment.where.file if fragment.where else None,
        'line': fragment.where.line if fragment.where else None,
        'address': address}
    if placement is not None:
        entry['method'] = placement.method
        entry['exact'] = placement.exact
    if address is not None:
        entry['support'] = support
        entry['labels'] = {name: address + offset
                           for name, offset in sorted(fragment.labels.items())}
    return entry


def make(program, layout, finished, evidence):
    """The map of `program` (link.Program) for the place.Layout
    `layout`, the sections.Finished `finished` and the
    evidence.Evidence `evidence`."""
    part_of_program = program.reachable()
    fragments = []
    dropped = []
    for key in sorted(program.fragments):
        entry = _fragment(program.fragments[key],
                          layout.placements.get(key),
                          finished.addresses.get(key),
                          evidence_.fragment_support(evidence, key))
        if key in part_of_program or key in finished.addresses:
            fragments.append(entry)
        else:
            dropped.append(entry)
    return {
        'fragments': fragments,
        'dropped': dropped,
        'sections': {name: {'first': first, 'last': last}
                     for name, (first, last)
                     in sorted(finished.extents.items())},
        'exported': {name: number(program.resolved(value), finished.known)
                     for name, value in sorted(program.exports.items())},
        'units': {unit: {name: number(value, finished.known)
                         for name, value in sorted(symbols.items())}
                  for unit, symbols in sorted(program.symbols.items())},
        'linker': dict(sorted(
            list(program.bases.items())
            + [(atom[1], value) for atom, value in finished.known.items()
               if atom[0] == linear.SYMBOL])),
    }
