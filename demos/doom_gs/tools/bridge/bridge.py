#!/usr/bin/env python3
"""The state bridge: upstream's game state and the port's, in one model.

Usage:
    python3 tools/bridge/bridge.py check [DUMP...] [--a2vm] [--json FILE]
    python3 tools/bridge/bridge.py decode DUMP [-o STATE.json]
    python3 tools/bridge/bridge.py upstream STATE.json --base DUMP -o IMG
    python3 tools/bridge/bridge.py layout [-o MANIFEST.json]
    python3 tools/bridge/bridge.py port STATE.json [--manifest M] -o IMG
    python3 tools/bridge/bridge.py from-port SNAPSHOT.ram [--manifest M]
                                             -o STATE.json

check     the acceptance checks (checks.py) on the dumps of
          tools/bridge/dumps.py (default: every dump in build/bridge/dumps)
          and, when present, the liveness check over the footprints of
          build/bridge/sweep; --a2vm also loads each port image into a2vm
          and reads it back. Exit status 0 when every check passes.
decode    a dump (a directory of dumps.py, or a ref816 image or --dump-ram
          file) to its canonical state, as JSON
upstream  a canonical state into upstream's layout, at the placement of
          the base dump (its objects' addresses): a ref816 memory image
layout    writes the native-v1 manifest (layout.py) to
          build/bridge/native-v1.json or -o
port      a canonical state into the port's layout: an a2vm --image file
from-port an a2vm snapshot's RAM (NAME.ram) back to a canonical state

tools/bridge/README.md describes the model, the schema, the manifest
format and the checks.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))

from bridge import canonical, checks, dumps  # noqa: E402
from bridge.layout import Manifest  # noqa: E402
from bridge.memory import Memory, PortMemory  # noqa: E402
from bridge.port import PortReader, PortWriter  # noqa: E402
from bridge.upstream import Problem, Reader, Schema, Writer  # noqa: E402

BUILD = HERE.parent.parent / 'build'
OUT = BUILD / 'bridge'
A2VM = BUILD / 'a2vm' / 'a2vm'
ROM = Path(os.environ.get('APPLETINI_ROOT', str(
    HERE.parents[4] / 'appletini-one'))) / 'docs' / 'Apple2e_Enhanced.rom'


def need_build() -> Optional[str]:
    for path in (BUILD / 'linkmap.json',
                 BUILD / 'upstream' / 'src' / 'iigs' / 'offsets.inc'):
        if not path.exists():
            return ('%s is missing: run python3 tools/fetch_upstream.py and '
                    'python3 tools/v816/imgmatch.py first' % path)
    return None


def load_memory(path: Path) -> Memory:
    path = Path(path)
    if path.is_dir():
        path = path / 'entry.img'
    if path.read_bytes()[:8] == b'REF816I1':
        return Memory.from_image(path)
    return Memory.from_dump(path)


def manifest_arg(sch: Schema, path: Optional[Path]) -> Manifest:
    return Manifest.load(path) if path else checks.manifest_for(sch)


def summary_line(r) -> str:
    rt = r['upstream_roundtrip']
    info = r['info']
    line = ('%-12s map %d tic %5d: %6d bytes, unclaimed %d, raw pointers '
            '%d, problems %d, dead bytes read %d, unknown writes %d; '
            'upstream round trip %d differ, port round trip %d differ' % (
                r['name'], info.get('gamemap', 0), info.get('gametic', 0),
                r['bytes'], r['unclaimed'], len(r['raw_pointers']),
                len(r['problems']), len(r['liveness'] or ()),
                len(r.get('outside_unknown') or ()), rt['differing'] +
                rt['outside'], len(r['port_roundtrip'])))
    if 'a2vm_roundtrip' in r:
        line += ', through a2vm %d differ' % len(r['a2vm_roundtrip'])
    return line + ('' if r['ok'] else '  FAIL')


def command_check(args) -> int:
    sch = Schema()
    manifest = checks.manifest_for(sch)
    directories = [Path(d) for d in args.dumps] or dumps.dump_directories()
    if not directories:
        print('no dumps: run python3 tools/bridge/dumps.py first',
              file=sys.stderr)
        return 1
    a2vm = None
    if args.a2vm:
        if not A2VM.exists() or not ROM.exists():
            print('--a2vm needs %s and %s' % (A2VM, ROM), file=sys.stderr)
            return 1
        a2vm = (A2VM, ROM, OUT / 'a2vm')
    results = []
    start = time.time()
    for d in directories:
        r = checks.check_dump(d, sch, manifest, a2vm)
        results.append(r)
        print(summary_line(r))
        for what in ('problems', 'raw_pointers', 'liveness',
                     'outside_unknown', 'port_roundtrip', 'a2vm_roundtrip'):
            for line in (r.get(what) or [])[:5]:
                print('    %s: %s' % (what, line))
        for line in r['upstream_roundtrip']['first'][:5]:
            print('    upstream: %s' % line)
    if a2vm:
        try:
            a2vm[2].rmdir()     # each dump's files are already deleted
        except OSError:
            pass
    ok = all(r['ok'] for r in results)
    load, pairs = checks.constancy(results)
    if not pairs and not args.dumps:
        load.append('no two dumps of one level load to compare')
    for line in load:
        print('level tables: %s' % line)
    print('level tables: %d pairs of dumps of one level load compared'
          % pairs)
    ok = ok and not load
    sweep = dumps.sweep_directories()
    sweep_result = None
    if sweep and not args.dumps:
        n, violations = checks.check_sweep(sweep, sch)
        sweep_result = {'tics': n, 'violations': violations}
        print('sweep: %d tics, %d dead bytes read before written%s' % (
            n, len(violations), ''.join('\n    ' + v for v in violations)))
        ok = ok and not violations
    kinds = {}
    for r in results:
        for k, v in r['counts'].items():
            kinds[k] = kinds.get(k, 0) + v
    functions = sorted({f for r in results for f in r['functions']
                        if f is not None})
    print('%d dumps in %.1f s: %d pass; objects by kind over all dumps: %s'
          % (len(results), time.time() - start,
             sum(r['ok'] for r in results), ', '.join(
                 '%s %d' % kv for kv in sorted(kinds.items()))))
    print('thinker functions met: %s' % ', '.join(functions))
    if args.json:
        Path(args.json).write_text(json.dumps({
            'dumps': results, 'level_tables': {'differ': load,
                                               'pairs': pairs},
            'sweep': sweep_result,
            'ok': ok}, indent=1, default=str) + '\n')
    print('all checks pass' if ok else 'SOME CHECKS FAIL')
    return 0 if ok else 1


def command_decode(args) -> int:
    reader = Reader(load_memory(args.dump), Schema())
    state = reader.read()
    for line in reader.problems + reader.raw_pointers:
        print(line, file=sys.stderr)
    out = Path(args.out) if args.out else OUT / (Path(args.dump).name +
                                                  '.canonical.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    canonical.save(state, out)
    print('%s: %s' % (out, ', '.join('%s %d' % kv for kv in sorted(
        canonical.counts(state).items()))))
    return 1 if reader.problems or reader.raw_pointers else 0


def command_upstream(args) -> int:
    base = load_memory(args.base)
    reader = Reader(base, Schema())
    reader.read()
    if reader.problems:
        for line in reader.problems:
            print(line, file=sys.stderr)
        return 1
    try:
        state = canonical.load(Path(args.state))
        memory = Writer(reader).write(state, base, poison=False)
    except (Problem, ValueError) as e:
        print('%s: %s' % (args.state, e), file=sys.stderr)
        return 1
    Path(args.out).write_bytes(memory.image_bytes())
    print('%s: the state at the placement of %s' % (args.out, args.base))
    return 0


def command_layout(args) -> int:
    manifest = checks.manifest_for(Schema())
    out = Path(args.out) if args.out else OUT / 'native-v1.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest.save(out)
    print('%s: %d kinds, aux banks $%02X-$%02X' % (
        out, len(manifest.kinds), manifest.data['banks'][0],
        manifest.data['banks'][1]))
    return 0


def command_port(args) -> int:
    sch = Schema()
    manifest = manifest_arg(sch, args.manifest)
    state = canonical.load(Path(args.state))
    memory = PortWriter(manifest).write(state)
    Path(args.out).write_bytes(memory.image_bytes())
    print('%s: an a2vm --image of the state in %s' % (args.out,
                                                      manifest.name))
    return 0


def command_from_port(args) -> int:
    sch = Schema()
    manifest = manifest_arg(sch, args.manifest)
    state = PortReader(manifest).read(PortMemory.from_snapshot(
        Path(args.snapshot)))
    canonical.save(state, Path(args.out))
    print('%s: %s' % (args.out, ', '.join('%s %d' % kv for kv in sorted(
        canonical.counts(state).items()))))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command')
    p = sub.add_parser('check')
    p.add_argument('dumps', nargs='*')
    p.add_argument('--a2vm', action='store_true')
    p.add_argument('--json')
    p = sub.add_parser('decode')
    p.add_argument('dump')
    p.add_argument('-o', '--out')
    p = sub.add_parser('upstream')
    p.add_argument('state')
    p.add_argument('--base', required=True)
    p.add_argument('-o', '--out', required=True)
    p = sub.add_parser('layout')
    p.add_argument('-o', '--out')
    p = sub.add_parser('port')
    p.add_argument('state')
    p.add_argument('--manifest')
    p.add_argument('-o', '--out', required=True)
    p = sub.add_parser('from-port')
    p.add_argument('snapshot')
    p.add_argument('--manifest')
    p.add_argument('-o', '--out', required=True)
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    missing = need_build()
    if missing:
        print(missing, file=sys.stderr)
        return 1
    return {'check': command_check, 'decode': command_decode,
            'upstream': command_upstream, 'layout': command_layout,
            'port': command_port, 'from-port': command_from_port
            }[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
