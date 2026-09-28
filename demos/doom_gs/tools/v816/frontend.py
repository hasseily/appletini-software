#!/usr/bin/env python3
"""Front end driver: every source of upstream's default build, to IR.

Usage:  python3 tools/v816/frontend.py [--stats FILE] [--json DIR]
                                       [--no-generate] [--with-restricted]

Reads the fetched clone in build/upstream (tools/fetch_upstream.py) and
does what upstream's Makefile does before it links:

  game     the files of IIGS_S and the generated build/gen/drawcol.s,
           with -D TICSTEP=1, and -D MUSIC_MENU=1 for m_menu65.s
  boot     src/iigs/boot.s, without flags
  loader   src/iigs/loader.s with -I build/gen, where the generated
           loadfont.s is

The generated files are made by upstream's own tools, run from the
clone, and written to build/gen of this port.

The Makefile's "-I tools/calypsi/src/lib/lowlevel" is the directory of a
header of the Calypsi installation. The port has tools/v816/include in
its place (see macros.h there).

Prints the statistics. --stats also writes them as a Markdown report
(docs/FRONTEND_STATS.md is that file). --json writes the IR of each
unit as JSON; the directory must be inside build/, because the IR holds
upstream's code. --with-restricted counts the file that the report
leaves out for its licence (tools/v816/report.py); it cannot be used
with --stats. The exit status is 1 when a source has errors.
"""

import argparse
import re
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v816 import cpp, ir, parse, report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD = ROOT / 'build'
UPSTREAM = BUILD / 'upstream'
GEN = BUILD / 'gen'
STAND_IN_INCLUDE = Path(__file__).resolve().parent / 'include'

Source = namedtuple('Source', 'path link_unit include_paths defines')
Source.__doc__ = """One run of the assembler: the file, the program it
is linked into (game, boot or loader), the -I directories and the -D
definitions."""

Result = namedtuple('Result', 'source lines unit counts included')
Result.__doc__ = """What the front end made of a Source: the
preprocessed lines, the ir.Unit, the counts of parse.parse_lines and
the include files that were read."""


class BuildError(Exception):
    """The clone is not as the driver expects, or a tool failed."""


def makefile_settings(makefile_text):
    """What the driver takes from upstream's Makefile: the list IIGS_S
    and the defaults of TICSTEP and MUSIC_MENU."""
    joined = makefile_text.replace('\\\n', ' ')
    sources = re.search(r'^IIGS_S\s*:=(.*)$', joined, re.MULTILINE)
    ticstep = re.search(r'^TICSTEP\s*\?=\s*(\S+)', joined, re.MULTILINE)
    music_menu = re.search(r'^MUSIC_MENU\s*\?=\s*(\S+)', joined,
                           re.MULTILINE)
    if not (sources and ticstep and music_menu):
        raise BuildError('the Makefile has no IIGS_S, TICSTEP or '
                         'MUSIC_MENU')
    return {'sources': sources.group(1).split(),
            'TICSTEP': ticstep.group(1),
            'MUSIC_MENU': music_menu.group(1)}


def generate(upstream=UPSTREAM, gen=GEN):
    """Make drawcol.s and loadfont.s with upstream's tools, with the
    arguments of the Makefile. -B keeps Python from writing into the
    clone."""
    gen.mkdir(parents=True, exist_ok=True)
    commands = (
        ['tools/gendraw.py', str(gen / 'drawcol.s'), '0', '0', '84'],
        ['tools/loadfont.py', 'data/DOOM1.WAD', str(gen / 'loadfont.s')],
    )
    for command in commands:
        result = subprocess.run(
            [sys.executable, '-B'] + command, cwd=str(upstream),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        if result.returncode:
            raise BuildError('%s failed:\n%s' % (command[0], result.stdout))


def sources(upstream=UPSTREAM, gen=GEN):
    """The Sources of the default build, in the order of the link."""
    makefile = upstream / 'Makefile'
    if not makefile.exists():
        raise BuildError('%s is missing: run tools/fetch_upstream.py'
                         % makefile)
    settings = makefile_settings(makefile.read_text())
    flags = {'TICSTEP': settings['TICSTEP']}
    game = []
    for name in settings['sources']:
        defines = dict(flags)
        if name.endswith('/m_menu65.s'):
            defines['MUSIC_MENU'] = settings['MUSIC_MENU']
        game.append(Source(upstream / name, 'game', (STAND_IN_INCLUDE,),
                           defines))
    source_directory = upstream / 'src' / 'iigs'
    game.append(Source(gen / 'drawcol.s', 'game',
                       (STAND_IN_INCLUDE, source_directory), dict(flags)))
    return game + [
        Source(source_directory / 'boot.s', 'boot', (), {}),
        Source(source_directory / 'loader.s', 'loader', (gen,), {}),
    ]


def process(source):
    """Preprocess and parse one Source. A preprocessor error becomes the
    only error of an empty unit."""
    preprocessor = cpp.Preprocessor(source.include_paths, source.defines)
    try:
        lines = preprocessor.process_file(source.path)
    except cpp.CppError as error:
        unit = ir.Unit(str(source.path))
        unit.errors.append(ir.Error(
            str(error).split(': ', 1)[1], ir.Where(error.file, error.line)))
        counts = {'expansions': {}, 'source_instructions': 0, 'scopes': 0,
                  'across_equates': 0}
        return Result(source, [], unit, counts, [])
    unit, counts = parse.parse_lines(lines, str(source.path))
    return Result(source, lines, unit, counts, preprocessor.included)


def run(upstream=UPSTREAM, gen=GEN):
    """The Results of all sources of the default build."""
    return [process(source) for source in sources(upstream, gen)]


def _inside_build(path):
    resolved = path.resolve()
    return resolved == BUILD or BUILD in resolved.parents


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--stats', type=Path, metavar='FILE',
                        help='write the statistics as Markdown')
    parser.add_argument('--json', type=Path, metavar='DIR',
                        help='write the IR of each unit (inside build/)')
    parser.add_argument('--no-generate', action='store_true',
                        help='use the generated files that are there')
    parser.add_argument('--with-restricted', action='store_true',
                        help='count the restricted file too (console only)')
    options = parser.parse_args(arguments)
    if options.stats and options.with_restricted:
        parser.error('--with-restricted: these counts must not be written '
                     'to a file')
    if options.json and not _inside_build(options.json):
        parser.error('--json: the directory must be inside %s' % BUILD)
    try:
        if not options.no_generate:
            generate()
        results = run()
    except BuildError as error:
        print('frontend: %s' % error, file=sys.stderr)
        return 1
    text = report.markdown(results, ROOT, options.with_restricted)
    print(text)
    if options.stats:
        options.stats.write_text(text + '\n')
    if options.json:
        options.json.mkdir(parents=True, exist_ok=True)
        for result in results:
            name = result.source.path.stem + '.json'
            with open(options.json / name, 'w') as stream:
                ir.dump_json(result.unit, stream)
    errors = [error for result in results for error in result.unit.errors]
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
