#!/usr/bin/env python3
"""Division by zero in the game: every call of the game's integer divides
with a zero divisor, in the coverage scripts and the three demos.

Usage:  python3 tools/ref816/divscan.py [--jobs N] [--runs NAME,...]
                                       [--sites]

The owner decided (docs/NATIVE.md section 15.1, row 5) that the port's
divides are our own, with our own defined result for a zero divisor, and
that the vendor routines are not tested as black boxes. This scan tells
whether the case occurs at all. Nothing of upstream's
src/iigs/cal_integer.s is read: the routines, their call sites and where
each takes its divisor come from the game's own sources (the lines
`jsl long:NAME` outside cal_integer.s) and from build/linkmap.json.

The routines are the ones the game's sources call (docs/research/
native-modules.md section 4.2), with the divisor where the call sites
put it (DIVIDES, each with a call site as its evidence):

  _UDivMod16, _Div16, _Mod16   dividend in A, divisor in X, 16 bits
  _UDivMod32, _Div32           dividend in _Dp[0-3], divisor in _Dp[4-7],
                               32 bits, through the direct page

A call site writes `dp:.tiny (_Dp+4)`: the direct page register D plus
_Dp's offset from the base of the direct page (the section ztiny of the
link map; tools/v816/expr.py, `.tiny`). The call log reads those 8 bytes
at each call's entry, so it holds what the call site wrote whatever D is.

Each run is logged with ref816 --call-log, entry=1 (the inputs only: no
result of a vendor routine is recorded) for the five entries. Only calls
from the game's code count: a call from inside the vendor runtime is
counted apart and not listed. Each call site found in the log is placed
in its source file and line: the nearest label of the link map
(codemap.py), then the k-th `jsl long:NAME` line after that label's
definition, where k counts the JSL instructions to NAME in the code of
the release image from the label to the site. `--sites` prints the call
sites of the sources and of the image, matched, and exits.

The runs (RUNS): the four coverage scripts as they are, and the title
loop to the end of each demo (lumps.demo_script): DEMO3 as the release
has it, DEMO1 and DEMO2 placed by lumps.py. The report goes to
build/ref816/divscan/report.json and to the terminal. Exit status 0 when
every run ran without a problem (whatever the zero divisors), 1
otherwise.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import codemap, lumps, make_image, refimage, run_script, \
    script, title  # noqa: E402

SOURCES = make_image.BUILD / 'upstream' / 'src' / 'iigs'
OUT = make_image.OUT_DIR / 'divscan'
VENDOR_FILE = codemap.VENDOR_UNIT       # never opened
DP_SYMBOL = '_Dp'
DP_SECTION = 'ztiny'
OP_JSL = 0x22


class Divide(NamedTuple):
    name: str
    width: int          # bits of the divisor
    divisor: str        # 'x' or 'dp': X, or _Dp[4-7]
    evidence: str       # a call site that shows it


DIVIDES = (
    Divide('_UDivMod16', 16, 'x',
           'i_viigs65.s:1371-1373: lda VD_OFFSET; ldx ##320; '
           'jsl _UDivMod16 ("C = x, X = y" of offset % 320, offset / 320)'),
    Divide('_Div16', 16, 'x',
           'p_floor65.s:1222-1224 (sectorNum): C = sector - _g_sectors; '
           'ldx ##SIZEOF_SEC; jsl _Div16'),
    Divide('_Mod16', 16, 'x',
           'p_enemy65.s:592-594: jsl P_Random; ldx ##3; jsl _Mod16 '
           '("P_Random() % 3")'),
    Divide('_UDivMod32', 32, 'dp',
           'g_game65.s:808-816: _Dp[0-3] = leveltime; _Dp+4 = TICRATE, '
           '_Dp+6 = 0; jsl _UDivMod32 (to whole seconds)'),
    Divide('_Div32', 32, 'dp',
           's_sound65.s:643-647 (divAtt): "C = _Dp[0-3] / S_ATTENUATOR"; '
           'S_ATTENUATOR to _Dp+4, 0 to _Dp+6; jsl _Div32'),
)
BY_NAME = {d.name: d for d in DIVIDES}
COVERAGE = ('title', 'newgame', 'viewsize', 'tour')
DEMOS = ('DEMO1', 'DEMO2', 'DEMO3')
RUNS = COVERAGE + DEMOS
DEMO_LIMIT_SECONDS = 3000
JSL = re.compile(r'^\s*(?:[A-Za-z0-9_$]+:)?\s*jsl\s+long:(\w+)\s*(?:;.*)?$')
LABEL = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):')


class Site(NamedTuple):
    unit: str
    line: int
    callee: str


# ---- call sites ----

def source_sites(sources: Path = SOURCES) -> List[Site]:
    """Every `jsl long:NAME` of a divide in the game's sources (every
    .s file but the vendor's)."""
    found = []
    for path in sorted(sources.glob('*.s')):
        if path.name == VENDOR_FILE:
            continue
        for number, line in enumerate(
                path.read_text(errors='replace').splitlines(), 1):
            match = JSL.match(line)
            if match and match.group(1) in BY_NAME:
                found.append(Site(path.name, number, match.group(1)))
    return found


class Code:
    """The release's code as the image loads it, the link map, and the
    call sites of the divides in it."""

    def __init__(self, linkmap: Dict, image: Path = title.MEMORY,
                 sources: Path = SOURCES):
        self.linkmap = linkmap
        self.symbols = script.Symbols(linkmap)
        self.places = codemap.CodeMap(linkmap)
        self.memory = refimage.Memory(refimage.read(image).records)
        self.sources = sources
        self.entries = {self.symbols.address('%s:%s' % (VENDOR_FILE, d.name)):
                        d.name for d in DIVIDES}
        self.lines: Dict[str, List[str]] = {}

    def text(self, unit: str) -> List[str]:
        if unit == VENDOR_FILE:
            raise ValueError('the vendor runtime is not read')
        if unit not in self.lines:
            self.lines[unit] = (self.sources / unit).read_text(
                errors='replace').splitlines()
        return self.lines[unit]

    def binary_sites(self) -> List[Tuple[int, str]]:
        """(address, callee) of each JSL to a divide in the game's code
        fragments (not the vendor's)."""
        found = []
        for f in self.places.fragments:
            if f['kind'] != 'text' or f['unit'] == VENDOR_FILE:
                continue
            data = self.memory.get(f['address'], f['size'])
            for i in range(len(data) - 3):
                if data[i] == OP_JSL:
                    target = data[i + 1] | data[i + 2] << 8 | \
                        data[i + 3] << 16
                    if target in self.entries:
                        found.append((f['address'] + i,
                                      self.entries[target]))
        return found

    def line_of(self, address: int, callee: str) -> Optional[Site]:
        """The source line of the JSL to `callee` at `address`, or None
        when it cannot be told (see the module's docstring)."""
        place = self.places.place(address)
        if place.unit in (codemap.VENDOR, codemap.OUTSIDE) or \
                not place.label:
            return None
        start = address - place.offset
        data = self.memory.get(start, place.offset + 4)
        target = self.symbols.address('%s:%s' % (VENDOR_FILE, callee))
        k = sum(1 for i in range(place.offset + 1) if data[i] == OP_JSL and
                (data[i + 1] | data[i + 2] << 8 | data[i + 3] << 16) ==
                target)
        lines = self.text(place.unit)
        definition = [n for n, line in enumerate(lines, 1)
                      if line.startswith(place.label + ':')]
        if len(definition) != 1:
            return None
        seen = 0
        label = place.label
        for number in range(definition[0], len(lines) + 1):
            line = lines[number - 1]
            found = LABEL.match(line)
            if found and number > definition[0] and \
                    found.group(1) in self.fragment_labels(start):
                label = found.group(1)
            match = JSL.match(line)
            if match and match.group(1) == callee:
                seen += 1
                if seen == k:
                    # the line must still be under the same label
                    return Site(place.unit, number, callee) \
                        if label == place.label else None
        return None

    def fragment_labels(self, address: int) -> set:
        """The labels of the link map in the fragment at `address`."""
        for f in self.places.fragments:
            if f['address'] <= address < f['address'] + f['size']:
                return set(f['labels'])
        return set()


def matched_sites(code: Code) -> Dict[int, Optional[Site]]:
    """Each JSL to a divide in the image, with its source line."""
    return {address: code.line_of(address, callee)
            for address, callee in code.binary_sites()}


# ---- runs ----

def log_options(code: Code, path: Path) -> List[str]:
    """--call-log of the five divides, their inputs only, into `path`."""
    base = code.linkmap['game']['sections'][DP_SECTION]['first']
    offset = code.symbols.address(DP_SYMBOL) - base
    options = ['--call-log-file', str(path)]
    for d in DIVIDES:
        options += ['--call-log', '%06X,name=%s,entry=1,in=d+%X:8'
                    % (code.symbols.address('%s:%s' % (VENDOR_FILE, d.name)),
                       d.name, offset)]
    return options


def run_one(name: str, code: Code, out: Path) -> Dict:
    """Run `name` with the call log; the run's report and the log's
    path."""
    out.mkdir(parents=True, exist_ok=True)
    log = out / (name.lower() + '.calls')
    extra = log_options(code, log)
    limit = run_script.DEFAULT_LIMIT_SECONDS
    if name in DEMOS:
        lump = lumps.read_wad()[name]
        info = lumps.demo_info(lump)
        path = out / ('%s.script' % name.lower())
        path.write_text(lumps.demo_script(info['map'], DEMO_LIMIT_SECONDS))
        if name != 'DEMO3':
            extra += lumps.options(name, code.symbols, out=out)
        limit = DEMO_LIMIT_SECONDS + 120
    else:
        path = run_script.script_path(name)
    report = run_script.run(path, limit_seconds=limit, extra=extra,
                            name='divscan-' + name.lower())
    return {'name': name, 'report': report, 'log': log}


class Call(NamedTuple):
    run: str
    routine: str
    site: int
    divisor: int
    dividend: int
    d: int
    frame: int
    cycles: int


def calls_of(log: Path, run: str) -> Tuple[List[Call], Dict[str, int]]:
    """The calls of a log, and the arrivals of each routine."""
    lines = log.read_text().splitlines()
    head = json.loads(lines[0])
    names = [r['name'] for r in head['routines']]
    calls, arrivals = [], {}
    for line in lines[1:]:
        entry = json.loads(line)
        if 'end' in entry:
            arrivals = dict(zip(names, entry['arrivals']))
            continue
        routine = names[entry['routine']]
        divide = BY_NAME[routine]
        registers = entry['in']
        dp = bytes.fromhex(registers['mem'][0])
        if divide.divisor == 'x':
            mask = 0xff if registers['p'] & 0x10 else 0xffff
            divisor = registers['x'] & mask
            dividend = registers['a'] & (0xff if registers['p'] & 0x20
                                         else 0xffff)
        else:
            divisor = int.from_bytes(dp[4:8], 'little')
            dividend = int.from_bytes(dp[0:4], 'little')
        calls.append(Call(run, routine, entry['from'], divisor, dividend,
                          registers['d'], entry['frame'], entry['cycles']))
    return calls, arrivals


def scan(runs: Sequence[str] = RUNS, jobs: int = 2,
         out: Path = OUT) -> Dict:
    with open(str(make_image.LINKMAP)) as handle:
        linkmap = json.load(handle)
    code = Code(linkmap)
    sites = matched_sites(code)
    with ThreadPoolExecutor(max(1, jobs)) as pool:
        results = list(pool.map(lambda n: run_one(n, code, out), runs))
    per_site: Dict[int, Counter] = defaultdict(Counter)
    zero: List[Dict] = []
    vendor = Counter()
    report_runs = []
    d_values = Counter()
    for result in results:
        calls, arrivals = calls_of(result['log'], result['name'])
        game_calls = 0
        for c in calls:
            place = code.places.place(c.site)
            if place.unit == codemap.VENDOR:
                vendor[c.routine] += 1
                continue
            game_calls += 1
            d_values[c.d] += 1
            per_site[c.site]['calls'] += 1
            per_site[c.site]['run:' + c.run] += 1
            if c.divisor == 0:
                per_site[c.site]['zero'] += 1
                site = sites.get(c.site)
                zero.append({
                    'run': c.run, 'routine': c.routine, 'site': c.site,
                    'place': str(place),
                    'line': '%s:%d' % (site.unit, site.line) if site
                    else None,
                    'dividend': c.dividend, 'frame': c.frame,
                    'cycles': c.cycles})
        report = result['report']
        report_runs.append({
            'name': result['name'], 'problems': report['problems'],
            'end': report['end'], 'seconds': report['seconds'],
            'calls': game_calls, 'arrivals': arrivals})
        result['log'].unlink()
    site_rows = []
    for address, callee in code.binary_sites():
        site = sites.get(address)
        counts = per_site.get(address, Counter())
        site_rows.append({
            'address': address, 'callee': callee,
            'place': str(code.places.place(address)),
            'line': '%s:%d' % (site.unit, site.line) if site else None,
            'calls': counts['calls'], 'zero': counts['zero'],
            'runs': {k[4:]: v for k, v in counts.items()
                     if k.startswith('run:')}})
    unknown = sorted(set(per_site) - {a for a, _ in code.binary_sites()})
    result = {
        'divides': [d._asdict() for d in DIVIDES],
        'runs': report_runs,
        'sources': len(source_sites()),
        'sites': site_rows,
        'sites_called': sum(1 for r in site_rows if r['calls']),
        'calls': sum(r['calls'] for r in site_rows),
        'calls_from_unknown_sites': [
            {'address': a, 'place': str(code.places.place(a)),
             'calls': per_site[a]['calls']} for a in unknown],
        'calls_inside_vendor_runtime': sum(vendor.values()),
        'direct_page': {'%04X' % d: n for d, n in sorted(d_values.items())},
        'zero_divisors': zero,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def summary(result: Dict) -> str:
    lines = ['Division by zero in %d runs: %d calls of the divides from '
             'the game\'s code, at %d of %d call sites (%d in the sources); '
             '%d with a zero divisor.'
             % (len(result['runs']), result['calls'], result['sites_called'],
                len(result['sites']), result['sources'],
                len(result['zero_divisors']))]
    for run in result['runs']:
        lines.append('  %-9s %s after %6.1f s, %6d calls%s'
                     % (run['name'], run['end']['reason'], run['seconds'],
                        run['calls'], ''.join('; PROBLEM: ' + p
                                              for p in run['problems'])))
    lines.append('  direct page at the calls: %s' % ', '.join(
        '$%s (%d)' % item for item in result['direct_page'].items()))
    by_callee = Counter()
    for row in result['sites']:
        by_callee[row['callee']] += row['calls']
    lines.append('  calls by routine: %s' % ', '.join(
        '%s %d' % item for item in sorted(by_callee.items())))
    lines.append('  calls from inside the vendor runtime (not listed): %d'
                 % result['calls_inside_vendor_runtime'])
    for row in result['sites']:
        if row['calls']:
            lines.append('  %-11s %-22s %-34s %6d calls, %d zero'
                         % (row['callee'], row['line'] or '?', row['place'],
                            row['calls'], row['zero']))
    idle = [row['line'] or row['place'] for row in result['sites']
            if not row['calls']]
    if idle:
        lines.append('  call sites no run reached (%d): %s'
                     % (len(idle), ', '.join(idle)))
    for z in result['zero_divisors']:
        lines.append('  ZERO: %s %s at %s (%s), dividend %d, frame %d'
                     % (z['run'], z['routine'], z['line'], z['place'],
                        z['dividend'], z['frame']))
    for u in result['calls_from_unknown_sites']:
        lines.append('  a call site not found in the image: %s, %d calls'
                     % (u['place'], u['calls']))
    return '\n'.join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--runs', default=','.join(RUNS))
    parser.add_argument('--sites', action='store_true')
    arguments = parser.parse_args(argv)
    for path in (make_image.RELEASE_IMAGE, make_image.LINKMAP, lumps.WAD):
        if not path.exists():
            print('%s is missing: run python3 tools/fetch_upstream.py and '
                  'python3 tools/v816/imgmatch.py first' % path,
                  file=sys.stderr)
            return 1
    title.build_machine()
    title.ensure_image()
    if arguments.sites:
        with open(str(make_image.LINKMAP)) as handle:
            code = Code(json.load(handle))
        source = source_sites()
        matched = matched_sites(code)
        for address, site in sorted(matched.items()):
            print('$%06X %-34s %s' % (address, code.places.place(address),
                                     '%s:%d %s' % site if site else '?'))
        found = {(s.unit, s.line) for s in matched.values() if s}
        missing = [s for s in source if (s.unit, s.line) not in found]
        print('%d sites in the sources, %d in the image, %d matched; '
              'not in the image: %s'
              % (len(source), len(matched), len(found),
                 ', '.join('%s:%d' % (s.unit, s.line) for s in missing)
                 or 'none'))
        return 0 if len(found) == len(source) == len(matched) else 1
    runs = [r for r in arguments.runs.split(',') if r]
    unknown = [r for r in runs if r not in RUNS]
    if unknown:
        print('unknown runs: %s (known: %s)' % (', '.join(unknown),
                                               ', '.join(RUNS)),
              file=sys.stderr)
        return 1
    result = scan(runs, arguments.jobs)
    print(summary(result))
    return 1 if any(r['problems'] for r in result['runs']) else 0


if __name__ == '__main__':
    sys.exit(main())
