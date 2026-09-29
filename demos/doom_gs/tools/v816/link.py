"""The linker: names across units, the bytes of holes, the built image.

A Program is the set of units of one link with the names resolved:
every hole of every fragment has a value in terms of the atoms that
only the placement decides (the addresses of fragments, the section
operators, and symbols that no unit defines). The symbols of the rules
file (_DirectPageStart, _NearBaseAddress) are constants.

stored() gives the bytes that belong in a hole once the atoms have
numbers; the layout recovery (tools/v816/place.py) uses it to test a
candidate address, and link() uses it to build the image.

Range checks. The manual says what .tiny, .near and .kbank check, and
a branch has the range of its instruction; link() reports a value
outside them. What the vendor's linker checks for an address without an
operator in a 16-bit operand is not known, so nothing is checked there
and the low bits are stored.
"""

from typing import NamedTuple, Optional

from . import asm816, linear, memimage

DIRECT_PAGE_BASE = '_DirectPageStart'
NEAR_BASE = '_NearBaseAddress'
PROGRAM_ROOT = '__program_root_section'
INITIALIZATION_NEEDED = '__data_initialization_needed'
BANK_MASK = 0xff0000
_PARTS = {'byte0': (0, 0xff), 'byte1': (8, 0xff), 'byte2': (16, 0xff),
          'word0': (0, 0xffff), 'word2': (16, 0xffff)}


class Problem(NamedTuple):
    """Something that the link found wrong. `key` and `offset` give the
    place, a fragment and an offset in it, when there is one."""
    message: str
    key: Optional[tuple] = None
    offset: Optional[int] = None


class Program:
    """The units of one link.

    fragments   ObjectFragment by key
    holes       by key, the holes of the fragment with the names of
                other units resolved
    symbols     by unit name, the Value of each name of the unit
    exports     the Value of each exported name
    bases       the value of DIRECT_PAGE_BASE and NEAR_BASE, where the
                rules file defines them
    problems    names that are exported twice, sections whose kind was
                assumed where it matters, and the like
    """

    def __init__(self, objects, rules):
        self.objects = objects
        self.rules = rules
        self.bases = dict(rules.base_addresses)
        self.problems = []
        self.exports = {}
        self._definitions = {
            (linear.SYMBOL, name): linear.Linear(value)
            for name, value in rules.base_addresses.items()}
        for unit in objects:
            for name in unit.exports:
                self._export(unit, name)
        self.fragments = {fragment.key: fragment
                          for unit in objects for fragment in unit.fragments}
        self.problems += self._assumed_kinds()
        self.holes = {
            key: [hole._replace(value=self.resolved(hole.value))
                  for hole in fragment.holes]
            for key, fragment in self.fragments.items()}
        self.symbols = {
            unit.name: {name: self.resolved(value)
                        for name, value in unit.symbols.items()}
            for unit in objects}

    def _assumed_kinds(self):
        """Problems for the fragments whose .section gave no kind, in a
        section that other fragments give a kind other than text: the
        assembler took text for them (objfile.ObjectFragment), which
        may not be what the vendor's tools do. Kinds that fragments
        give explicitly are the source's own choice and are not
        compared with each other."""
        given = {}
        for fragment in self.fragments.values():
            if fragment.kind_given and fragment.kind != 'text':
                given.setdefault(fragment.section, set()).add(fragment.kind)
        return [Problem('the section %s has no kind here, and the kind %s '
                        'elsewhere: text was assumed'
                        % (fragment.section,
                           ', '.join(sorted(given[fragment.section]))),
                        key, 0)
                for key, fragment in sorted(self.fragments.items())
                if not fragment.kind_given and fragment.section in given]

    def _export(self, unit, name):
        atom = (linear.SYMBOL, name)
        value = unit.symbols[name]
        if value.reloc:
            self.problems.append(Problem(
                '%s: the exported name %s has a relocation operator'
                % (unit.name, name)))
        elif atom in self._definitions:
            self.problems.append(Problem(
                '%s: %s is exported by another unit too'
                % (unit.name, name)))
        else:
            self._definitions[atom] = value.linear
            self.exports[name] = value

    def resolved(self, value):
        """`value` with the names of other units replaced. An exported
        name can be an equate of an imported one, so the replacement
        repeats until nothing changes."""
        for _ in range(len(self._definitions) + 1):
            replaced = value.substitute(self._definitions)
            if replaced == value:
                return value
            value = replaced
        self.problems.append(Problem('exported names that depend on '
                                     'each other'))
        return value

    def _references(self, key):
        """The atoms of fragments that the fragment `key` refers to:
        in its holes and by .require."""
        atoms = []
        for hole in self.holes[key]:
            atoms += hole.value.linear.atoms()
        for name in self.fragments[key].requires:
            if name in self.exports:
                atoms += self.resolved(self.exports[name]).linear.atoms()
        return [atom for atom in atoms if atom[0] == linear.FRAGMENT]

    def reachable(self):
        """The keys of the fragments that are part of the program.

        The vendor's linker leaves out every fragment that the root of
        the program does not refer to, directly or through others
        ("tree shaking"; manual, 23.6.4 and --no-tree-shaking). The
        roots are the fragments with the modifier root and the fragment
        with the label PROGRAM_ROOT. When the program has a section
        that the startup code must clear, the linker also refers to
        INITIALIZATION_NEEDED (the comment in upstream's crt0.s).
        """
        roots = [key for key, fragment in self.fragments.items()
                 if 'root' in fragment.modifiers]
        found = set()

        def follow(atoms):
            todo = [atom[1:] for atom in atoms]
            while todo:
                key = todo.pop()
                if key not in found:
                    found.add(key)
                    todo += [atom[1:] for atom in self._references(key)]

        follow((linear.FRAGMENT,) + key for key in roots)
        if PROGRAM_ROOT in self.exports:
            follow(self.exports[PROGRAM_ROOT].linear.atoms())
        if (INITIALIZATION_NEEDED in self.exports
                and any(self.fragments[key].cleared for key in found)):
            follow(self.exports[INITIALIZATION_NEEDED].linear.atoms())
        return found

    def undefined(self):
        """The names that units import and no unit exports."""
        names = set()
        for holes in self.holes.values():
            for hole in holes:
                names.update(atom[1] for atom in hole.value.linear.atoms()
                             if atom[0] == linear.SYMBOL)
        return sorted(names)


class Stored(NamedTuple):
    """The bytes of a hole, and what is wrong with the value (None when
    nothing is)."""
    data: bytes
    problem: Optional[str]


def relocated(reloc, number, origin, bases):
    """What the relocation operator `reloc` makes of `number` in an
    item at the address `origin`: (value, problem)."""
    if reloc is None:
        return number, None
    if reloc in _PARTS:
        shift, mask = _PARTS[reloc]
        return number >> shift & mask, None
    if reloc == 'kbank':
        if (number ^ origin) & BANK_MASK:
            return number & 0xffff, ('.kbank: $%06X is not in the bank of '
                                     'the instruction' % number)
        return number & 0xffff, None
    name, limit = {'tiny': (DIRECT_PAGE_BASE, 0x100),
                   'near': (NEAR_BASE, 0x10000)}[reloc]
    if name not in bases:
        return number, 'the rules file does not define %s' % name
    offset = number - bases[name]
    if not 0 <= offset < limit:
        return offset, ('.%s: $%06X is outside the area at $%06X'
                        % (reloc, number, bases[name]))
    return offset, None


def stored(hole, base, known, bases):
    """The Stored of `hole`, which is in a fragment at the address
    `base`; `known` maps atoms to numbers. None when the value has an
    atom that `known` does not have."""
    value = hole.value.linear.substitute(known)
    if not value.is_constant:
        return None
    number, problem = relocated(hole.value.reloc, value.constant,
                                base + hole.origin, bases)
    if hole.kind == asm816.KIND_BRANCH and problem is None:
        limit = 1 << 8 * hole.width - 1
        if not -limit <= number < limit:
            problem = 'the target is %d bytes away' % number
    return Stored(asm816.little_endian(number, hole.width), problem)


class Linked(NamedTuple):
    """The built image. Each fragment is a region of `memory`; `keys`
    has the key of the fragment of each region, by the index of the
    region."""
    memory: memimage.MemoryImage
    keys: list
    problems: list

    def key_at(self, address):
        """The key of the fragment with the byte at `address`, or
        None."""
        region = self.memory.region_at(address)
        return None if region is None else self.keys[region.index]


def link(program, addresses, known):
    """Builds the image of `program`.

    `addresses` maps the key of each placed fragment to its address;
    `known` maps atoms to numbers and has the atoms of the placed
    fragments among them. A hole with an atom that is not known stays
    0 and is a problem.
    """
    memory = memimage.MemoryImage()
    keys = []
    problems = []
    for key in sorted(addresses, key=lambda key: (addresses[key], key)):
        fragment = program.fragments[key]
        if not fragment.initialised or not fragment.size:
            continue
        base = addresses[key]
        data = bytearray(fragment.data)
        for hole in program.holes[key]:
            result = stored(hole, base, known, program.bases)
            if result is None:
                missing = [atom for atom in hole.value.linear.atoms()
                           if atom not in known]
                problems.append(Problem(
                    'no value for %s' % ', '.join(map(atom_text, missing)),
                    key, hole.offset))
                continue
            if result.problem:
                problems.append(Problem(result.problem, key, hole.offset))
            data[hole.offset:hole.offset + hole.width] = result.data
        memory.load(base, bytes(data), key_text(key))
        keys.append(key)
    for overlap in memory.overlaps:
        problems.append(Problem(
            '%d bytes at $%06X are in two fragments: %s and %s'
            % (overlap.length, overlap.address,
               memory.regions[overlap.earlier].label,
               memory.regions[overlap.later].label)))
    return Linked(memory, keys, problems)


def key_text(key):
    """The key of a fragment for a message: "unit#number"."""
    return '%s#%d' % key


def atom_text(atom):
    """An atom for a message."""
    if atom[0] == linear.FRAGMENT:
        return 'the address of ' + key_text(atom[1:])
    if atom[0] == linear.SECTION:
        return '.%s %s' % atom[1:]
    return atom[1]
