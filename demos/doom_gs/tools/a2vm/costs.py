#!/usr/bin/env python3
"""The cost profiles of a2vm: tools/a2vm/costs/appletini.json.

Usage:  python3 tools/a2vm/costs.py PROFILE [OUT]

Writes the parameters of PROFILE (the "common" values, then the
profile's own) as the "name value" lines a2vm's --cost option reads, to
OUT or to standard output. `profile(name)` does the same for other
tools. Standard library only.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COSTS = HERE / 'costs' / 'appletini.json'


def load(path=COSTS):
    return json.loads(Path(path).read_text())


def profiles(path=COSTS):
    return sorted(load(path)['profiles'])


def parameters(name, path=COSTS):
    """{parameter: value} of profile `name`."""
    data = load(path)
    if name not in data['profiles']:
        raise KeyError('no cost profile %r (there are %s)'
                       % (name, ', '.join(sorted(data['profiles']))))
    values = {key: entry['value'] for key, entry in data['common'].items()}
    for key, entry in data['profiles'][name]['params'].items():
        values[key] = entry['value']
    return values


def text(name, path=COSTS):
    lines = ['# a2vm cost profile %s, from %s' % (name, Path(path).name)]
    for key, value in parameters(name, path).items():
        lines.append('%s %s' % (key, repr(value) if isinstance(value, float)
                                else value))
    return '\n'.join(lines) + '\n'


def write(name, out, path=COSTS):
    Path(out).write_text(text(name, path))
    return Path(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or len(argv) > 2:
        print(__doc__, file=sys.stderr)
        return 2
    if len(argv) == 2:
        write(argv[0], argv[1])
    else:
        sys.stdout.write(text(argv[0]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
