"""The canonical model: its JSON form and its comparison.

A canonical state is

    {"format": "bridge-canonical 1",
     "globals": {"unit:label": value, ...},
     "objects": {kind: {identity: {field: value, ...}, ...}, ...}}

Values are numbers, strings (thinker functions as "unit:label", raw
bytes as hexadecimal), lists, dicts (a structure inside a structure), None
(a null pointer) and references R(kind, id, field) (fields.R), which JSON
writes as {"ref": [kind, id, field]}. A list of the game (the thinkers, a
sector's things, a thing's sector nodes, the free nodes) is a JSON list of
references in its head: the global or the field that holds the list's
head in upstream (schema.LISTS).

`diff` compares two states: objects by kind and identity, fields by name,
lists as sequences. Its `skip` names fields not to compare, as
"kind.field" or a global's name ("*.field" for every kind).
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from bridge.fields import R, from_json, to_json

FORMAT = 'bridge-canonical 1'


def normalise(state: Dict[str, Any]) -> Dict[str, Any]:
    """Object identities as ints where they are numbers (JSON keys are
    strings)."""
    objects = {}
    for kind, table in state.get('objects', {}).items():
        objects[kind] = {(int(k) if isinstance(k, str) and
                          k.lstrip('-').isdigit() else k): v
                         for k, v in table.items()}
    out = dict(state)
    out['objects'] = objects
    return out


def save(state: Dict[str, Any], path: Path) -> None:
    Path(path).write_text(json.dumps(to_json(state), indent=1,
                                     sort_keys=True) + '\n')


def load(path: Path) -> Dict[str, Any]:
    state = normalise(from_json(json.loads(Path(path).read_text())))
    if state.get('format') != FORMAT:
        raise ValueError('%s: not a canonical state' % path)
    return state


def roundtrip_json(state: Dict[str, Any]) -> Dict[str, Any]:
    """The state as it comes back from a file."""
    return normalise(from_json(json.loads(json.dumps(to_json(state)))))


def diff(a: Dict[str, Any], b: Dict[str, Any],
         skip: Iterable[str] = (), limit: int = 50) -> List[str]:
    """The differences between two canonical states, as lines."""
    skip = set(skip)
    out: List[str] = []

    def add(line: str) -> None:
        if len(out) < limit:
            out.append(line)
        elif len(out) == limit:
            out.append('...')

    ga, gb = a.get('globals', {}), b.get('globals', {})
    for name in sorted(set(ga) | set(gb)):
        if name in skip:
            continue
        if name not in ga or name not in gb:
            add('global %s: only in %s' % (name, 'a' if name in ga
                                            else 'b'))
        elif ga[name] != gb[name]:
            add('global %s: %s != %s' % (name, short(ga[name]),
                                         short(gb[name])))
    oa, ob = a.get('objects', {}), b.get('objects', {})
    for kind in sorted(set(oa) | set(ob)):
        ta, tb = oa.get(kind, {}), ob.get(kind, {})
        if set(ta) != set(tb):
            add('%s: identities %s only in a, %s only in b' % (
                kind, sorted(set(ta) - set(tb), key=str)[:8],
                sorted(set(tb) - set(ta), key=str)[:8]))
        for ident in sorted(set(ta) & set(tb), key=str):
            fa, fb = ta[ident], tb[ident]
            for field in sorted(set(fa) | set(fb)):
                if '%s.%s' % (kind, field) in skip or '*.%s' % field in skip:
                    continue
                if fa.get(field, MISSING) != fb.get(field, MISSING):
                    add('%s[%s].%s: %s != %s' % (
                        kind, ident, field, short(fa.get(field, MISSING)),
                        short(fb.get(field, MISSING))))
    return out


class _Missing:
    def __repr__(self) -> str:
        return '(missing)'


MISSING = _Missing()


def short(value: Any, n: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= n else text[:n - 3] + '...'


def counts(state: Dict[str, Any]) -> Dict[str, int]:
    return {k: len(v) for k, v in state.get('objects', {}).items()}


def references(value: Any) -> Iterable[R]:
    """Every reference inside a value."""
    if isinstance(value, R):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from references(v)
    elif isinstance(value, list):
        for v in value:
            yield from references(v)


def dangling(state: Dict[str, Any], constant_kinds: Set[str]) -> List[str]:
    """References to objects the state does not have (constants such as
    states and lumps apart)."""
    objects = state.get('objects', {})
    out = []
    for where, value in list(state.get('globals', {}).items()) + [
            ('%s[%s]' % (k, i), o) for k, t in objects.items()
            for i, o in t.items()]:
        for ref in references(value):
            if ref.kind in constant_kinds:
                continue
            if ref.id not in objects.get(ref.kind, {}):
                out.append('%s -> %r' % (where, ref))
    return out


def get(state: Dict[str, Any], kind: str, ident: Any) -> Optional[Dict]:
    return state.get('objects', {}).get(kind, {}).get(ident)
