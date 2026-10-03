#!/usr/bin/env python3
"""The cost profiles of a2vm: tools/a2vm/costs/appletini.json.

Usage:  python3 tools/a2vm/costs.py PROFILE[+VARIANT...] [OUT]

Writes the parameters of PROFILE (the "common" values, then the
profile's own, then those of each VARIANT in order) as the "name value"
lines a2vm's --cost option reads, to OUT or to standard output.
`profile(name)` does the same for other tools. The profiles: f121,
f122 (F1.2.2: the PSRAM admitted at the driver's rate while the vTW owns
the bus, the memory API's copy engine), fastpath, f121zp, fastzp. The
variants (the "variants" section: phasor, window32, fws1, ntsc, nod2,
precal) are settings of the firmware or the machine on top of a profile,
for instance f121+phasor+window32 (precal: the model before the card's
calibration of 2026-10-03, for comparison; f122+nod2: the card as it ran
F1.2.2, its virtual Disk II's acceleration off). Standard library only.
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


def variants(path=COSTS):
    return sorted(key for key in load(path).get('variants', {})
                  if key != 'about')


def parameters(name, path=COSTS):
    """{parameter: value} of profile `name`, or of PROFILE+VARIANT..."""
    data = load(path)
    name, *extra = name.split('+')
    if name not in data['profiles']:
        raise KeyError('no cost profile %r (there are %s)'
                       % (name, ', '.join(sorted(data['profiles']))))
    values = {key: entry['value'] for key, entry in data['common'].items()}
    for key, entry in data['profiles'][name]['params'].items():
        values[key] = entry['value']
    for variant in extra:
        known = data.get('variants', {})
        if variant not in known or variant == 'about':
            raise KeyError('no cost variant %r (there are %s)'
                           % (variant, ', '.join(variants(path))))
        for key, entry in known[variant]['params'].items():
            if key not in values:
                raise KeyError('variant %s sets an unknown parameter %s'
                               % (variant, key))
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
