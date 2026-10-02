"""The identity rules of the canonical model, applied to a canonical state.

Some kinds are numbered by where upstream keeps them (a pool slot, an
index into a level table); the others are numbered from the lists, so
that two machines that keep them in different places still give each
object the same identity (schema.KINDS, tools/bridge/README.md):

    specials, removed  their rank among the thinkers of their kind
    zmobj              first those on the thinker list, in its order; then
                       the others in the order the sectors' thing lists
                       reach them (sector by sector), then the blocks'
                       chains; then any left, in their present order
    secnode            the order of first reach: the things' node lists
                       (pool slots, then zone mobjs), the sectors' node
                       lists, _s_sector_list, the free list; then any left

`renumber` gives every such object its identity by these rules and
rewrites every reference. upstream.Reader numbers this way already, so
its states come out unchanged; the port's reader numbers by its slots,
and renumbers.
"""

from typing import Any, Dict, List, Tuple

from bridge import schema
from bridge.fields import R

RANKED = tuple(schema.SPECIAL_KINDS) + ('removed',)


def order(state: Dict[str, Any]) -> Dict[str, List[Any]]:
    """For each renumbered kind, its present identities in the new
    order."""
    objects = state['objects']
    gl = state['globals']
    thinkers = gl.get('p_think65.s:_g_thinkerclasscap', [])
    out: Dict[str, List[Any]] = {}
    for kind in RANKED:
        seq = [r.id for r in thinkers if r.kind == kind]
        rest = [i for i in objects.get(kind, {}) if i not in set(seq)]
        out[kind] = seq + sorted(rest)
    # zone mobjs
    zm = objects.get('zmobj', {})
    seen: List[Any] = []

    def add(ident: Any) -> None:
        if ident in zm and ident not in seen:
            seen.append(ident)

    for r in thinkers:
        if r.kind == 'zmobj':
            add(r.id)
    for s in sorted(objects.get('sector', {})):
        for r in objects['sector'][s].get('thinglist', []):
            if r.kind == 'zmobj':
                add(r.id)
    for b in sorted(objects.get('blocklink', {})):
        for r in objects['blocklink'][b].get('things', []):
            if r.kind == 'zmobj':
                add(r.id)
    out['zmobj'] = seen + sorted(i for i in zm if i not in seen)
    # sector nodes
    nodes = objects.get('secnode', {})
    reached: List[Any] = []
    got = set()

    def walk(seq) -> None:
        for r in seq or []:
            if r.kind == 'secnode' and r.id in nodes and r.id not in got:
                got.add(r.id)
                reached.append(r.id)

    # (the zone mobjs in their identity's order, out['zmobj'], not their
    # present identities': the port reader's are its slots, whose order
    # can differ from the thinker list's; upstream.Reader's are the ranks
    # already, so its order is the same: the final integration of
    # milestone 10, generated stream G1)
    for i in sorted(objects.get('mobj', {})):
        walk(objects['mobj'][i].get('touching_sectorlist'))
    for i in out['zmobj']:
        walk(zm[i].get('touching_sectorlist'))
    for s in sorted(objects.get('sector', {})):
        walk(objects['sector'][s].get('touching_thinglist'))
    walk(gl.get('p_map65.s:_s_sector_list'))
    walk(gl.get('p_map65.s:SN_FREE'))
    out['secnode'] = reached + sorted(i for i in nodes if i not in got)
    return out


def mapping(state: Dict[str, Any]) -> Dict[Tuple[str, Any], Any]:
    """(kind, old identity): new identity, for the renumbered kinds."""
    out = {}
    for kind, ids in order(state).items():
        # zmobj: renumbered only after the list ranks of the thinkers
        for new, old in enumerate(ids):
            out[(kind, old)] = new
    return out


def rewrite(value: Any, table: Dict[Tuple[str, Any], Any]) -> Any:
    if isinstance(value, R):
        key = (value.kind, value.id)
        if key in table:
            return R(value.kind, table[key], value.field)
        return value
    if isinstance(value, dict):
        return {k: rewrite(v, table) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite(v, table) for v in value]
    return value


def renumber(state: Dict[str, Any]) -> Dict[str, Any]:
    """The state with the identities of the rules (a new state)."""
    table = mapping(state)
    objects = {}
    for kind, objs in state['objects'].items():
        new = {}
        for ident, o in objs.items():
            new[table.get((kind, ident), ident)] = rewrite(o, table)
        objects[kind] = dict(sorted(new.items(), key=lambda kv: str(kv[0])
                                    if not isinstance(kv[0], int) else
                                    '%012d' % kv[0]))
    out = dict(state)
    out['objects'] = objects
    out['globals'] = rewrite(state['globals'], table)
    return out
