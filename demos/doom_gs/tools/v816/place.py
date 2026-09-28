"""Layout recovery: where the vendor's linker put each fragment.

The linker may place the fragments of a section in any order (manual,
21.4.2), so the layout of the release cannot be computed from the
sources. It is recovered from the image instead. The unknowns are the
atoms of tools/v816/linear.py: the address of each fragment, the
section operators, and symbols that no unit defines.

Two sources of knowledge:

  the bytes    An initialised fragment is searched in the memories that
               accept its section (tools/v816/scm.py): the bytes that
               the assembler knows must be equal, and so must every
               hole whose value is known for the address that is tried.
  the holes    A hole of a placed fragment holds a value in the image.
               When the value has one atom without a number, the
               stored bytes give the number, or its low 16 bits: a
               Constraint. Fragments without bytes (bss) get their
               address this way only.

recover() repeats three steps, each only when the one before it finds
nothing more:

  1. exact: a fragment with one address that passes every test is
     placed there. New constraints follow from its holes.
  2. by reference: a fragment that has constraints and no address that
     passes the tests is placed where most constraints put it.
  3. approximate: a fragment that is found nowhere is placed where
     most of its bytes are found. A fragment of less than PIECE bytes
     between its holes is not placed this way.

Steps 2 and 3 exist to show what is wrong: the image comparison
(tools/v816/imgmatch.py) then reports the bytes that differ, with the
source line. Placement.exact tells the placements of step 1 from the
others.
"""

import bisect
import re
from collections import Counter, deque
from typing import NamedTuple

from . import asm816, link, linear

ADDRESS_MASK = 0xffffff
LOW_MASK = 0xffff
# A fragment with more raw matches than this is mostly holes; it waits
# for a constraint.
MAX_CANDIDATES = 4096
# Step 3 looks for the known bytes in pieces of this length.
PIECE = 8

METHOD_MATCH = 'match'
METHOD_REFERENCE = 'reference'
METHOD_APPROXIMATE = 'approximate'


class Constraint(NamedTuple):
    """The bits `mask` of the number of `atom` are `value`, because of
    the hole at `offset` of the fragment `key`."""
    atom: tuple
    value: int
    mask: int
    key: tuple
    offset: int


class Placement(NamedTuple):
    """Where a fragment is. `exact` is true when the address passed
    every test when the fragment was placed."""
    address: int
    method: str
    exact: bool


class Layout(NamedTuple):
    """What recover() found.

    placements   Placement by key
    known        the number of each atom that has one; the addresses of
                 the placed fragments are among them
    constraints  by atom, the Constraints that the holes gave
    ambiguous    by key, the addresses that pass every test, for the
                 fragments with more than one
    unplaced     the keys of the fragments of the program with bytes
                 or with constraints that have no address
    """
    placements: dict
    known: dict
    constraints: dict
    ambiguous: dict
    unplaced: list

    def addresses(self):
        return {key: placement.address
                for key, placement in self.placements.items()}


def conflicts(constraints, known):
    """The Constraints of `constraints` (by atom) that the numbers of
    `known` do not satisfy. For an atom without a number, all its
    constraints when two of them contradict each other."""
    found = []
    for atom, given in sorted(constraints.items()):
        if atom in known:
            found += [constraint for constraint in given
                      if known[atom] & constraint.mask != constraint.value]
        elif any((one.value ^ other.value) & one.mask & other.mask
                 for one in given for other in given):
            found += given
    return found


class _Trial:
    """The known atoms and one more, for the address that is tried."""

    def __init__(self, known, atom, number):
        self.known = known
        self.atom = atom
        self.number = number

    def get(self, atom):
        if atom == self.atom:
            return self.number
        return self.known.get(atom)


def pattern(fragment):
    """A regular expression for the bytes of `fragment` with any bytes
    in its holes."""
    parts = []
    position = 0
    for hole in sorted(fragment.holes):
        parts.append(re.escape(fragment.data[position:hole.offset]))
        parts.append(b'.{%d}' % hole.width)
        position = hole.offset + hole.width
    parts.append(re.escape(fragment.data[position:]))
    return re.compile(b''.join(parts), re.DOTALL)


def loaded_runs(memory, first, last):
    """The parts of first..last that `memory` has bytes for, as
    (address, bytes)."""
    runs = []
    for bank in range(first >> 16, (last >> 16) + 1):
        for start, end in memory.extents(bank):
            start = max(start, first)
            end = min(end, last + 1)
            if start < end:
                runs.append((start, memory.read(start, end - start)))
    return runs


def search(memory, compiled, ranges):
    """The addresses in `ranges`, a list of (first, last), where the
    bytes of `memory` match the pattern `compiled`; None when they are
    more than MAX_CANDIDATES."""
    found = set()
    ahead = re.compile(b'(?=' + compiled.pattern + b')', re.DOTALL)
    for first, last in ranges:
        for start, data in loaded_runs(memory, first, last):
            for match in ahead.finditer(data):
                found.add(start + match.start())
                if len(found) > MAX_CANDIDATES:
                    return None
    return sorted(found)


def solve(hole, base, data, known, bases):
    """The Constraint that the bytes `data` of `hole` give, or None.

    The hole is in a fragment at `base`. The value must have one atom
    that `known` does not have, with the coefficient 1 or -1, and the
    hole must hold enough of the value: 16 bits at least.
    """
    value = hole.value.linear.substitute(known)
    if len(value.terms) != 1 or abs(value.terms[0][1]) != 1:
        return None
    atom, sign = value.terms[0]
    number = int.from_bytes(data, 'little')
    reloc = hole.value.reloc
    mask = ADDRESS_MASK
    if reloc == 'near' and link.NEAR_BASE in bases:
        number += bases[link.NEAR_BASE]
    elif reloc == 'tiny' and link.DIRECT_PAGE_BASE in bases:
        number += bases[link.DIRECT_PAGE_BASE]
    elif reloc == 'kbank':
        number |= (base + hole.origin) & link.BANK_MASK
    elif reloc == 'word0' or (reloc is None and hole.width == 2
                              and hole.kind != asm816.KIND_BRANCH):
        mask = LOW_MASK
    elif reloc is None and hole.kind == asm816.KIND_BRANCH:
        limit = 1 << 8 * hole.width - 1
        number = (number ^ limit) - limit        # the sign
    elif reloc is not None or hole.width < 3:
        return None
    return Constraint(atom, (number - value.constant) * sign & mask, mask,
                      None, hole.offset)


class _Recovery:
    def __init__(self, program, memory):
        self.program = program
        self.memory = memory
        self.bases = program.bases
        self.known = {}
        self.placements = {}
        self.constraints = {}           # atom -> list of Constraint
        self.waiting = {}               # atom -> list of (key, hole)
        self.taken = []                 # sorted (first, end) of fragments
        self.candidates = {}            # key -> addresses, from the bytes
        self.patterns = {}
        self.todo = deque()             # (key, hole) to look at
        self.fragments = {key: program.fragments[key]
                          for key in sorted(program.reachable())}
        self.ranges = {key: self._ranges(fragment)
                       for key, fragment in self.fragments.items()}

    # ----- where a fragment may be

    def _ranges(self, fragment):
        """The (first, last) addresses that the rules allow for the
        first and the last byte of `fragment`."""
        accepting = self.program.rules.accepting(fragment.section)
        others = [other for other in self.fragments.values()
                  if other.section == fragment.section and other.size
                  and other.key != fragment.key]
        ranges = []
        for _, rule in accepting:
            last = rule.last
            if rule.fixed and not others:
                last = rule.first + max(fragment.size, 1) - 1
            ranges.append((rule.first, last))
        return ranges

    def _allowed(self, fragment, address):
        if address % fragment.alignment:
            return False
        end = address + fragment.size
        if not any(first <= address and end <= last + 1
                   for first, last in self.ranges[fragment.key]):
            return False
        if not fragment.size:
            return True
        index = bisect.bisect_right(self.taken, (address, ADDRESS_MASK + 1))
        if index and self.taken[index - 1][1] > address:
            return False
        return index == len(self.taken) or self.taken[index][0] >= end

    def _image(self, address, size):
        """The bytes of the image, or None where it has none."""
        try:
            return self.memory.read(address, size)
        except KeyError:
            return None

    def _pattern(self, fragment):
        if fragment.key not in self.patterns:
            self.patterns[fragment.key] = pattern(fragment)
        return self.patterns[fragment.key]

    def _passes(self, fragment, address, bytes_known=False):
        """True when `fragment` can be at `address` by all that is
        known. `bytes_known`: the address comes from the search, so
        the bytes outside the holes are equal."""
        if not self._allowed(fragment, address):
            return False
        for constraint in self.constraints.get(fragment.atom, ()):
            if address & constraint.mask != constraint.value:
                return False
        if not fragment.initialised or not fragment.size:
            return True
        data = self._image(address, fragment.size)
        if data is None:
            return False
        if not bytes_known and \
                not self._pattern(fragment).fullmatch(data):
            return False
        trial = _Trial(self.known, fragment.atom, address)
        for hole in self.program.holes[fragment.key]:
            result = link.stored(hole, address, trial, self.bases)
            if result is not None and result.data != \
                    data[hole.offset:hole.offset + hole.width]:
                return False
        return True

    def _search(self, fragment):
        return search(self.memory, self._pattern(fragment),
                      self.ranges[fragment.key])

    def _from_constraints(self, fragment):
        """The addresses that the constraints of `fragment` allow, by
        the constraint that says most; None without constraints."""
        constraints = self.constraints.get(fragment.atom)
        if not constraints:
            return None
        addresses = set()
        for constraint in constraints:
            if constraint.mask == ADDRESS_MASK:
                addresses.add(constraint.value)
        if addresses:
            return sorted(addresses)
        for constraint in constraints:
            for first, last in self.ranges[fragment.key]:
                for bank in range(first >> 16, (last >> 16) + 1):
                    addresses.add(bank << 16 | constraint.value)
        return sorted(addresses)

    def _passing(self, fragment):
        """The addresses where `fragment` can be; None when nothing
        limits them yet."""
        key = fragment.key
        addresses = self._from_constraints(fragment)
        if addresses is not None:
            return [address for address in addresses
                    if self._passes(fragment, address)]
        if not fragment.initialised or not fragment.size:
            return None
        if key not in self.candidates:
            self.candidates[key] = self._search(fragment)
        if self.candidates[key] is None:
            return None
        self.candidates[key] = [
            address for address in self.candidates[key]
            if self._passes(fragment, address, bytes_known=True)]
        return self.candidates[key]

    # ----- placing, and what follows from it

    def _place(self, fragment, address, method, exact):
        self.placements[fragment.key] = Placement(address, method, exact)
        if fragment.size:
            bisect.insort(self.taken, (address, address + fragment.size))
        self._learn(fragment.atom, address)
        if fragment.initialised:
            self.todo.extend((fragment.key, hole)
                             for hole in self.program.holes[fragment.key])
        self._harvest()

    def _learn(self, atom, number):
        self.known[atom] = number
        self.todo.extend(self.waiting.pop(atom, ()))

    def _harvest(self):
        """Looks at the holes of placed fragments for constraints."""
        while self.todo:
            key, hole = self.todo.popleft()
            base = self.placements[key].address
            unknown = [atom for atom in hole.value.linear.atoms()
                       if atom not in self.known]
            if not unknown:
                continue
            data = self._image(base + hole.offset, hole.width)
            found = None
            if data is not None and len(unknown) == 1:
                found = solve(hole, base, data, self.known, self.bases)
            if found is None:
                for atom in unknown:
                    self.waiting.setdefault(atom, []).append((key, hole))
                continue
            found = found._replace(key=key)
            self.constraints.setdefault(found.atom, []).append(found)
            if found.atom[0] != linear.FRAGMENT \
                    and found.mask == ADDRESS_MASK:
                self._learn(found.atom, found.value)

    # ----- the three steps

    def _unplaced(self):
        return [fragment for key, fragment in self.fragments.items()
                if key not in self.placements]

    def _exact(self):
        progress = True
        while progress:
            progress = False
            for fragment in self._unplaced():
                addresses = self._passing(fragment)
                if addresses is not None and len(addresses) == 1:
                    method = METHOD_MATCH
                    if fragment.atom in self.constraints:
                        method = METHOD_REFERENCE
                    self._place(fragment, addresses[0], method, True)
                    progress = True

    def _by_reference(self):
        """Step 2 for one fragment: True when one was placed."""
        for fragment in self._unplaced():
            addresses = self._from_constraints(fragment)
            if addresses is None or self._passing(fragment):
                continue
            votes = Counter()
            for address in addresses:
                if self._allowed(fragment, address):
                    votes[address] = sum(
                        address & constraint.mask == constraint.value
                        for constraint in self.constraints[fragment.atom])
            best = votes.most_common(2)
            if best and (len(best) == 1 or best[0][1] > best[1][1]):
                self._place(fragment, best[0][0], METHOD_REFERENCE, False)
                return True
        return False

    def _approximate(self):
        """Step 3 for one fragment: True when one was placed."""
        for fragment in self._unplaced():
            if (not fragment.initialised or not fragment.size
                    or self.candidates.get(fragment.key) != []):
                continue
            votes = self._votes(fragment)
            best = votes.most_common(2)
            if best and (len(best) == 1 or best[0][1] > best[1][1]):
                self._place(fragment, best[0][0], METHOD_APPROXIMATE, False)
                return True
        return False

    def _votes(self, fragment):
        """For each allowed address, how many known bytes of `fragment`
        the image has there, counted in pieces of PIECE bytes."""
        pieces = []
        position = 0
        for hole in sorted(fragment.holes) + [None]:
            end = hole.offset if hole else fragment.size
            pieces += range(position, end - PIECE + 1, PIECE)
            position = hole.offset + hole.width if hole else end
        votes = Counter()
        for first, last in self.ranges[fragment.key]:
            for start, data in loaded_runs(self.memory, first, last):
                for offset in pieces:
                    piece = fragment.data[offset:offset + PIECE]
                    at = data.find(piece)
                    while at >= 0:
                        votes[start + at - offset] += PIECE
                        at = data.find(piece, at + 1)
        for address in list(votes):
            if not self._allowed(fragment, address):
                del votes[address]
        return votes

    def run(self):
        self._exact()
        while self._by_reference() or self._approximate():
            self._exact()
        return self._layout()

    def _layout(self):
        ambiguous = {}
        unplaced = []
        for fragment in self._unplaced():
            addresses = self._passing(fragment)
            if addresses and len(addresses) > 1:
                ambiguous[fragment.key] = addresses
            elif addresses is not None or (fragment.initialised
                                           and fragment.size):
                unplaced.append(fragment.key)
        return Layout(self.placements, self.known, self.constraints,
                      ambiguous, sorted(unplaced))


def recover(program, memory):
    """The Layout of `program` (link.Program) in `memory`, the
    memimage.MemoryImage of the release. Only the fragments of
    program.reachable() are looked for."""
    return _Recovery(program, memory).run()
