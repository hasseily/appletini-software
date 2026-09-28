#!/usr/bin/env python3
"""Image match: build upstream's programs and compare with the release.

Usage:  python3 tools/v816/imgmatch.py [--image FILE] [--no-generate]

For each of the three programs of the release (tools/v816/release.py)
the tool assembles the units (objfile), resolves the names (link),
recovers the layout from the release image (place), adds what the
linker makes (sections), builds the image (link) and compares it with
the release byte by byte. It writes

    build/match-report.json   the comparison
    build/linkmap.json        addresses and symbol values (linkmap)

and prints a summary. The exit status is 0 when the images are equal
and nothing else is wrong, else 1.

How the bytes are counted, for each program:

    total_bytes      the bytes of the release: its segments of code and
                     initialised data (whole disk blocks, so with the
                     zeros after the end of a segment), the boot block
                     and the loader
    mismatch_bytes   the bytes of the release that differ from the
                     built image, where the built image has 0 in every
                     place without a fragment; plus the bytes of built
                     fragments that lie where the release has nothing;
                     plus the sizes of the fragments of the program
                     that have bytes and no address (unplaced or
                     ambiguous). The last part can count a byte that
                     the first part has counted already.

The report has, for each fragment with bytes that differ, the first
such bytes with the source line; the bytes of the release that are not
0 and in no fragment; the fragments that are unplaced, ambiguous or
placed without passing every test; names without a value; values that
the image contradicts; and the errors of the assembler and the linker.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v816 import (frontend, link, linkmap, objfile, place,  # noqa: E402
                  release, scm, sections)

ROOT = frontend.ROOT
BUILD = frontend.BUILD
DEFAULT_IMAGE = BUILD / 'release' / 'doom-hd.hdv'
REPORT = BUILD / 'match-report.json'
LINKMAP = BUILD / 'linkmap.json'
# Bytes of an example in the report, at most.
EXAMPLE_BYTES = 16


def assemble(results, program_name):
    """The ObjectFiles of the front end results that belong to the
    program `program_name`."""
    return [objfile.assemble(result.unit, result.source.path.name)
            for result in results
            if result.source.link_unit == program_name]


def _where(fragment, offset):
    """The source of the byte at `offset` of `fragment`, for the
    report."""
    span = fragment.span_at(offset)
    if span is None:
        return {'file': None, 'line': None, 'item_offset': offset,
                'item_length': fragment.size - offset}
    place_ = {'file': span.where.file, 'line': span.where.line,
              'item_offset': span.offset, 'item_length': span.length}
    if span.where.expansions:
        place_['macros'] = [
            {'macro': use.macro, 'file': use.file, 'line': use.line}
            for use in span.where.expansions]
    return place_


def _runs(addresses):
    """`addresses`, sorted, as runs (first, length)."""
    runs = []
    for address in addresses:
        if runs and runs[-1][0] + runs[-1][1] == address:
            runs[-1][1] += 1
        else:
            runs.append([address, 1])
    return runs


def differing(expected, built):
    """The addresses where the memory `expected` has a byte that
    differs from `built`; a place where `built` has nothing counts as
    0."""
    addresses = []
    for bank in expected.banks():
        ours = built.bank_bytes(bank)
        for first, end in expected.extents(bank):
            theirs = expected.read(first, end - first)
            low = first & 0xffff
            if theirs == ours[low:low + len(theirs)]:
                continue
            addresses += [first + index
                          for index, byte in enumerate(theirs)
                          if byte != ours[low + index]]
    return addresses


def outside(expected, built):
    """How many bytes `built` has where `expected` has none."""
    count = 0
    for region in built.regions:
        for address in range(region.address, region.end):
            if expected.region_at(address) is None:
                count += 1
    return count


def _example(memory, address, length):
    try:
        return memory.read(address, min(length, EXAMPLE_BYTES)).hex()
    except KeyError:
        return None


def mismatches(program, finished, linked, expected, addresses):
    """The entries of the report for the bytes at `addresses` (from
    differing()): one for each fragment, and one for each run of bytes
    in no fragment."""
    by_key = {}
    loose = []
    for address in addresses:
        key = linked.key_at(address)
        if key is None:
            loose.append(address)
        else:
            by_key.setdefault(key, []).append(address)
    entries = []
    for key, found in sorted(by_key.items()):
        fragment = program.fragments[key]
        base = finished.addresses[key]
        entry = {'fragment': link.key_text(key),
                 'section': fragment.section,
                 'fragment_address': base,
                 'mismatch_bytes': len(found),
                 'address': found[0]}
        entry.update(_where(fragment, found[0] - base))
        start = base + entry['item_offset']
        entry['expected'] = _example(expected, start, entry['item_length'])
        entry['produced'] = _example(linked.memory, start,
                                     entry['item_length'])
        entries.append(entry)
    for first, length in _runs(loose):
        entries.append({'fragment': None, 'address': first,
                        'mismatch_bytes': length,
                        'expected': _example(expected, first, length),
                        'produced': None})
    return entries


def _dropped(program, memory, finished, linked, part_of_program):
    """The fragments with bytes that are not part of the program, each
    with the addresses where the release has its bytes all the same
    in a place without a built fragment (there should be none)."""
    entries = []
    for key, fragment in sorted(program.fragments.items()):
        if (key in part_of_program or key in finished.addresses
                or not fragment.initialised or not fragment.size):
            continue
        ranges = [(rule.first, rule.last)
                  for _, rule in program.rules.accepting(fragment.section)]
        found = place.search(memory, place.pattern(fragment), ranges)
        if found is not None:
            found = [address for address in found
                     if all(linked.key_at(address + offset) is None
                            for offset in range(fragment.size))]
        entries.append({
            'fragment': link.key_text(key), 'section': fragment.section,
            'size': fragment.size,
            'file': fragment.where.file if fragment.where else None,
            'line': fragment.where.line if fragment.where else None,
            'found_at': found})
    return entries


def _fragment_list(program, keys, layout):
    entries = []
    for key in keys:
        fragment = program.fragments[key]
        entries.append({
            'fragment': link.key_text(key), 'section': fragment.section,
            'size': fragment.size, 'initialised': fragment.initialised,
            'file': fragment.where.file if fragment.where else None,
            'line': fragment.where.line if fragment.where else None,
            'addresses': layout.ambiguous.get(key, [])})
    return entries


def _problem(problem):
    entry = {'message': problem.message}
    if problem.key is not None:
        entry['fragment'] = link.key_text(problem.key)
        entry['offset'] = problem.offset
    return entry


def _unsolved(program, finished):
    """The names that holes of placed fragments need and that have no
    number."""
    names = set()
    for key in finished.addresses:
        for hole in program.holes[key]:
            names.update(link.atom_text(atom)
                         for atom in hole.value.linear.atoms()
                         if atom not in finished.known)
    return sorted(names)


def match(objects, rules, memory):
    """Builds the program of `objects` (ObjectFiles) with `rules`
    (scm.Rules) and compares it with `memory`, the memory of the
    release. Returns (report, link map), both for json."""
    program = link.Program(objects, rules)
    part_of_program = program.reachable()
    layout = place.recover(program, memory)
    finished = sections.finish(program, layout)
    linked = link.link(program, finished.addresses, finished.known)
    addresses = differing(memory, linked.memory)
    homeless = [key for key in layout.unplaced + sorted(layout.ambiguous)
                if program.fragments[key].initialised]
    inexact = sorted(key for key, placement in layout.placements.items()
                     if not placement.exact)
    report = {
        'total_bytes': sum(memory.loaded_bytes(bank)
                           for bank in memory.banks()),
        'mismatch_bytes': (
            len(addresses) + outside(memory, linked.memory)
            + sum(program.fragments[key].size for key in homeless)),
        'differing_bytes': len(addresses),
        'fragments': {
            'in_the_units': len(program.fragments)
            - (sections.INIT_TABLE_KEY in program.fragments),
            'part_of_the_program': len(part_of_program),
            'placed': len(layout.placements),
            'placed_with_every_test_passed': len(layout.placements)
            - len(inexact),
            'made_by_the_linker': len(finished.addresses)
            - len(layout.placements)},
        'mismatches': mismatches(program, finished, linked, memory,
                                 addresses),
        'unplaced': _fragment_list(program, layout.unplaced, layout),
        'ambiguous': _fragment_list(program, sorted(layout.ambiguous),
                                    layout),
        'placed_inexactly': _fragment_list(program, inexact, layout),
        'not_part_of_the_program': _dropped(program, memory, finished,
                                            linked, part_of_program),
        'unsolved_symbols': _unsolved(program, finished),
        'undefined_symbols': program.undefined(),
        'inconsistent': [_problem(problem)
                         for problem in finished.problems],
        'link_problems': [_problem(problem)
                          for problem in program.problems + linked.problems],
        'assembler_errors': [str(error) for unit in objects
                             for error in unit.errors],
    }
    return report, linkmap.make(program, layout, finished)


def clean(report):
    """True when the report of a program has nothing wrong."""
    return not (report['mismatch_bytes'] or report['unplaced']
                or report['ambiguous'] or report['placed_inexactly']
                or report['unsolved_symbols'] or report['inconsistent']
                or report['link_problems'] or report['assembler_errors'])


def run(image_path, results, upstream=frontend.UPSTREAM):
    """The report and the link map of all programs for the release
    image `image_path` and the front end `results`."""
    with open(image_path, 'rb') as stream:
        data = stream.read()
    report = {'image': str(image_path),
              'image_sha256': hashlib.sha256(data).hexdigest(),
              'programs': {}}
    maps = {}
    for target in release.targets(data):
        rules = scm.load(upstream / 'src' / 'iigs' / target.rules_file)
        report['programs'][target.name], maps[target.name] = match(
            assemble(results, target.name), rules, target.memory)
    programs = report['programs'].values()
    report['total_bytes'] = sum(each['total_bytes'] for each in programs)
    report['mismatch_bytes'] = sum(each['mismatch_bytes']
                                   for each in programs)
    report['equal'] = all(clean(each) for each in programs)
    return report, maps


def summary(report):
    """The lines that say what the report holds."""
    lines = []
    for name, program in report['programs'].items():
        counts = program['fragments']
        lines.append(
            '%-7s %7d bytes, %d differ; fragments: %d placed of %d, '
            '%d not part of the program'
            % (name, program['total_bytes'], program['mismatch_bytes'],
               counts['placed'], counts['part_of_the_program'],
               counts['in_the_units'] - counts['part_of_the_program']))
        for title in ('unplaced', 'ambiguous', 'placed_inexactly',
                      'unsolved_symbols', 'inconsistent', 'link_problems',
                      'assembler_errors'):
            if program[title]:
                lines.append('        %s: %d' % (title.replace('_', ' '),
                                                 len(program[title])))
        for entry in program['mismatches']:
            lines.append(
                '        $%06X %s:%s expected %s produced %s (%d bytes of '
                '%s)' % (entry['address'], entry.get('file'),
                         entry.get('line'), entry['expected'],
                         entry['produced'], entry['mismatch_bytes'],
                         entry['fragment'] or 'no fragment'))
    lines.append('mismatch_bytes %d' % report['mismatch_bytes'])
    lines.append('total_bytes %d' % report['total_bytes'])
    return lines


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--image', type=Path, default=DEFAULT_IMAGE,
                        help='the release image')
    parser.add_argument('--no-generate', action='store_true',
                        help='use the generated sources that are there')
    options = parser.parse_args(arguments)
    if not options.image.exists():
        print('imgmatch: %s is missing: run tools/fetch_upstream.py'
              % options.image, file=sys.stderr)
        return 1
    try:
        if not options.no_generate:
            frontend.generate()
        results = frontend.run()
    except frontend.BuildError as error:
        print('imgmatch: %s' % error, file=sys.stderr)
        return 1
    report, maps = run(options.image, results)
    BUILD.mkdir(exist_ok=True)
    for path, content in ((REPORT, report), (LINKMAP, maps)):
        with open(path, 'w') as stream:
            json.dump(content, stream, indent=1)
            stream.write('\n')
    print('\n'.join(summary(report)))
    print('written: %s, %s' % (REPORT.relative_to(ROOT),
                               LINKMAP.relative_to(ROOT)))
    return 0 if report['equal'] else 1


if __name__ == '__main__':
    sys.exit(main())
