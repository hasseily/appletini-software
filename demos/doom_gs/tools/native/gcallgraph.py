#!/usr/bin/env python3
"""The call graph of upstream's game units (milestone 10, docs/GAME.md 2.1,
2.2, 4.5): a read of the sources with the release's conditionals, keyed
file:label, for the part table's rule, the routine harness's eligibility
and the placement.

Usage:  python3 tools/native/gcallgraph.py --check [--built PART,...]
        python3 tools/native/gcallgraph.py --reach FILE:LABEL
        python3 tools/native/gcallgraph.py --stack [--built PART,...]
        python3 tools/native/gcallgraph.py --json OUT

The sources are read by our own front end (tools/v816/frontend.py: the
preprocessor with the Makefile's TICSTEP, the macros expanded), never
upstream's assembler; src/iigs/cal_integer.s is never read (the ground
rules: the vendor runtime): a call into it is a call of milestone 6's math
by the callee's name only.

A routine is a head: an exported label, the target of a jsr, jsl or jml,
or a code label another routine names as a function pointer (an
immediate, a relocation or a data word); every other code label belongs
to the head before it. An edge is a call (jsr, jsl, jml, or a jmp, brl or
bra to another head: a tail call); a function pointer named in an operand
is a reference, which the reachability follows (a dispatch) but the rule
of 2.2 does not. The game units are p_*.s, g_game65.s, d_main65.s,
m_cheat65.s and m_random65.s; the graph follows calls out of them into
r_list65.s, w_level65.s, hu_stuff65.s, st_stuff65.s and wi_stuff65.s.

--check: every routine the tic reaches (from g_game65.s:G_Ticker, through
calls and references) is owned by a part of glayout.PARTS, milestone 9's
game core (glayout.CORE), a ghook.s hook (glayout.HOOKS), milestone 6's
math (glayout.MATH) or named out (glayout.OUT, GAME.md 0.1); each part's
routines are heads or labels of its files; and the rule of 2.2: a part's
direct callees are its own, an earlier wave's, the core's, math or hooks
(with --built, the built parts' callees are built). The exit status is 1
when any fails.

--reach R: the dispatch targets (glayout.DISPATCH's tables) R can reach.
--stack: the static depth of every call chain in bytes (2 a return, 5 an
FCALL across images: glayout.FCALL_STACK; what a routine keeps on the stack
across its calls: glayout.OWN_STACK; each strongly connected group
counted once), with the IRQ's 24, against the tic budget of 160 (GAME.md
4.5).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, \
    Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
UPSTREAM = BUILD / 'upstream' / 'src' / 'iigs'
CACHE = BUILD / 'native' / 'game' / 'shared' / 'callgraph.json'
FORBIDDEN = 'cal_integer.s'
GAME_UNITS_FIXED = ('g_game65.s', 'd_main65.s', 'm_cheat65.s',
                    'm_random65.s')
FOLLOWED = ('r_list65.s', 'w_level65.s', 'hu_stuff65.s', 'st_stuff65.s',
            'wi_stuff65.s')
# info65.s: the states, whose action pointers ACTTAB numbers
INFO = 'info65.s'
CALLS = ('jsr', 'jsl', 'jml')
JUMPS = ('jmp', 'brl', 'bra')
ROOTS = ('g_game65.s:G_Ticker',)


class GraphError(Exception):
    pass


def game_unit(name: str) -> bool:
    return (name.startswith('p_') and name.endswith('.s')) or \
        name in GAME_UNITS_FIXED


def in_scope(name: str) -> bool:
    return game_unit(name) or name in FOLLOWED or name == INFO


def symbols_in(tree: Any) -> List[str]:
    """The symbol names of an expression tree."""
    from v816 import expr as E
    out: List[str] = []

    def walk(t: Any) -> None:
        if isinstance(t, E.Symbol):
            out.append(t.name)
        elif isinstance(t, E.Reloc):
            walk(t.operand)
        elif isinstance(t, E.Unary):
            walk(t.operand)
        elif isinstance(t, E.Binary):
            walk(t.left)
            walk(t.right)
    walk(tree)
    return out


class Head:
    def __init__(self, unit: str, label: str):
        self.unit = unit
        self.label = label
        self.labels: List[str] = [label]
        self.calls: Set[str] = set()        # file:label (or ?:name)
        self.refs: Set[str] = set()         # function pointers named
        self.indirect = False               # jsr (a,x), jml [dp], ...
        self.size = 0

    @property
    def key(self) -> str:
        return '%s:%s' % (self.unit, self.label)

    def to_json(self) -> Dict[str, Any]:
        return {'labels': self.labels, 'calls': sorted(self.calls),
                'refs': sorted(self.refs), 'indirect': self.indirect,
                'size': self.size}


class Graph:
    """heads: file:label -> Head; labels: file:label -> its head's key."""

    def __init__(self):
        self.heads: Dict[str, Head] = {}
        self.label_head: Dict[str, str] = {}
        self.states_actions: List[str] = []

    # -- reading --
    @classmethod
    def read(cls) -> 'Graph':
        from v816 import frontend, ir
        from bridge.linkmap import Symbols
        g = cls()
        units: Dict[str, Any] = {}
        for src in frontend.sources():
            name = src.path.name
            if name == FORBIDDEN or not in_scope(name):
                continue
            r = frontend.process(src)
            if r.unit.errors:
                raise GraphError('%s: %s' % (name, r.unit.errors[0]))
            units[name] = r.unit
        # code labels and exports by unit
        code: Dict[str, List[str]] = {}
        public: Dict[str, str] = {}
        for name, unit in units.items():
            code[name] = []
            for f in unit.fragments:
                if (f.kind or 'text') != 'text':
                    continue
                for it in f.items:
                    if isinstance(it, ir.Label) and not it.local:
                        code[name].append(it.name)
            for d in unit.declarations:
                if d.directive == 'public':
                    public[d.name] = name

        def resolve(unit: str, sym: str) -> Optional[str]:
            if sym in code.get(unit, ()):
                return '%s:%s' % (unit, sym)
            if sym in public:
                u = public[sym]
                if sym in code.get(u, ()):
                    return '%s:%s' % (u, sym)
                return None             # (a data label)
            return '?:%s' % sym
        heads: Set[str] = set()
        for name in units:
            for sym, u in public.items():
                if u == name and sym in code[name]:
                    heads.add('%s:%s' % (name, sym))
        # targets of calls and function pointers make heads
        for name, unit in units.items():
            for f in unit.fragments:
                kind = f.kind or 'text'
                for it in f.items:
                    if isinstance(it, ir.Instruction) and it.operand is \
                            not None:
                        syms = symbols_in(it.operand)
                        if it.mnemonic in CALLS and it.mode not in (
                                'absx_ind', 'abs_ind', 'abs_ind_long',
                                'abs_ind_l'):
                            for s in syms:
                                k = resolve(name, s)
                                if k and not k.startswith('?'):
                                    heads.add(k)
                        elif it.mnemonic not in JUMPS and \
                                it.mnemonic[0] != 'b':
                            for s in syms:
                                k = resolve(name, s)
                                if k and not k.startswith('?') and \
                                        k.split(':')[1] in code[k.split(
                                            ':')[0]]:
                                    heads.add(k)
                    elif isinstance(it, ir.Data) and kind != 'bss' and \
                            it.directive in ('word', 'long', 'address'):
                        for v in it.values:
                            for s in symbols_in(v):
                                k = resolve(name, s)
                                if k and not k.startswith('?') and \
                                        name != INFO:
                                    heads.add(k)
        # the edges, head by head in source order
        for name, unit in units.items():
            if name == INFO:
                continue
            cur: Optional[Head] = None
            for f in unit.fragments:
                if (f.kind or 'text') != 'text':
                    continue
                for it in f.items:
                    if isinstance(it, ir.Label) and not it.local:
                        key = '%s:%s' % (name, it.name)
                        if key in heads:
                            cur = g.heads.setdefault(key, Head(name,
                                                               it.name))
                        elif cur is not None:
                            cur.labels.append(it.name)
                        if cur is not None:
                            g.label_head[key] = cur.key
                        continue
                    if cur is None or not isinstance(it, ir.Instruction) or \
                            it.operand is None:
                        if cur is not None and isinstance(it, ir.Data):
                            for v in it.values if it.directive in (
                                    'word', 'long', 'address') else ():
                                for s in symbols_in(v):
                                    k = resolve(name, s)
                                    if k and k in heads:
                                        cur.refs.add(k)
                        continue
                    syms = symbols_in(it.operand)
                    indirect = it.mode in ('absx_ind', 'abs_ind',
                                           'abs_ind_long', 'abs_ind_l',
                                           'dp_ind_long', 'dp_ind')
                    if it.mnemonic in CALLS + ('jmp',) and indirect:
                        cur.indirect = True
                        continue
                    if it.mnemonic in CALLS:
                        for s in syms:
                            k = resolve(name, s)
                            if k:
                                cur.calls.add(k)
                    elif it.mnemonic in JUMPS or it.mnemonic.startswith('b'):
                        for s in syms:
                            k = resolve(name, s)
                            if k and k in heads and k != cur.key:
                                cur.calls.add(k)
                    else:
                        for s in syms:
                            k = resolve(name, s)
                            if k and k in heads:
                                cur.refs.add(k)
        # sizes from the link map (each label to the next of its fragment)
        try:
            sym = Symbols()
        except (OSError, ValueError):
            sym = None
        if sym is not None:
            for h in g.heads.values():
                total = 0
                for lab in h.labels:
                    try:
                        total += sym.label('%s:%s' % (h.unit, lab)).size
                    except KeyError:
                        pass
                h.size = total
        # the states' actions (ACTTAB): info65.s's states, in order
        info = units.get(INFO)
        if info is not None:
            seen: List[str] = []
            for f in info.fragments:
                for it in f.items:
                    if isinstance(it, ir.Data):
                        for v in it.values:
                            for s in symbols_in(v):
                                if s.startswith('A_') and s not in seen:
                                    seen.append(s)
            g.states_actions = seen
        return g

    # -- the JSON cache --
    def to_json(self) -> Dict[str, Any]:
        return {'format': 'game-callgraph 1',
                'heads': {k: h.to_json() for k, h in
                          sorted(self.heads.items())},
                'label_head': self.label_head,
                'actions': self.states_actions}

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> 'Graph':
        g = cls()
        for k, v in d['heads'].items():
            unit, label = k.split(':', 1)
            h = Head(unit, label)
            h.labels = v['labels']
            h.calls = set(v['calls'])
            h.refs = set(v['refs'])
            h.indirect = v['indirect']
            h.size = v['size']
            g.heads[k] = h
        g.label_head = d['label_head']
        g.states_actions = d['actions']
        return g

    # -- queries --
    def head_of(self, key: str) -> Optional[str]:
        return self.label_head.get(key, key if key in self.heads else None)

    def reach(self, roots: Iterable[str], refs: bool = True) -> Set[str]:
        out: Set[str] = set()
        todo = [r for r in roots]
        while todo:
            k = todo.pop()
            if k in out:
                continue
            out.add(k)
            h = self.heads.get(k)
            if h is None:
                continue
            todo += list(h.calls)
            if refs:
                todo += list(h.refs)
        return out


def load(rebuild: bool = False, write: bool = True) -> Graph:
    """The graph, from its cache in build/native/game/shared (the shared
    outputs', made by make -f game.mk shared), else read again (and the
    cache written only with write: a part's build never writes it)."""
    if not rebuild and CACHE.exists():
        return Graph.from_json(json.loads(CACHE.read_text()))
    g = Graph.read()
    if write:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(g.to_json(), indent=0, sort_keys=True))
    return g


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def owners() -> Dict[str, str]:
    """file:label -> its owner: a part's name, "core", "math", "hook",
    "out:<why>"."""
    from native import glayout as GL
    out: Dict[str, str] = {}
    for p in GL.PARTS:
        for key in p['routines'] + p['helpers']:
            if key in out:
                raise GraphError('%s is owned twice: %s and %s' % (
                    key, out[key], p['name']))
            out[key] = p['name']
    for key in GL.CORE:
        out.setdefault(key, 'core')
    for key in GL.HOOKS:
        out.setdefault(key, 'hook')
    for key, why in GL.OUT.items():
        out.setdefault(key, 'out:' + why)
    return out


def classify(key: str, own: Dict[str, str]) -> str:
    """A routine's owner: a part, "core", "math", "hook", "out:<why>", or
    '' (nobody)."""
    from native import glayout as GL
    if key in own:
        return own[key]
    name = key.split(':', 1)[1]
    if name in GL.MATH_NAMES or key.split(':')[0] in GL.MATH_UNITS:
        return 'math'
    if name in GL.HOOK_NAMES:
        return 'hook'
    if name in GL.OUT_NAMES:
        return 'out:' + GL.OUT_NAMES[name]
    return ''


def tic_reach(g: 'Graph') -> Set[str]:
    """What the tic reaches: from G_Ticker, through calls, references and
    the dispatch tables, not into a hook, math or a routine named out."""
    from native import glayout as GL
    own = owners()
    entries = GL.dispatch_entries(g)
    extra: Dict[str, List[str]] = {}
    for t, d in GL.DISPATCH.items():
        for disp in d['dispatchers']:
            extra.setdefault(disp, []).extend(entries[t])
    out: Set[str] = set()
    todo = list(ROOTS)
    while todo:
        k = todo.pop()
        if k in out:
            continue
        out.add(k)
        c = classify(k, own)
        if c in ('hook', 'math') or c.startswith('out'):
            continue
        h = g.heads.get(k)
        if h is not None:
            todo += list(h.calls) + list(h.refs)
        todo += extra.get(k, [])
    return out


def check(g: Graph, built: Sequence[str] = ()) -> List[str]:
    """The failures of --check (an empty list: it passes)."""
    from native import glayout as GL
    out: List[str] = []
    own = owners()
    waves = {p['name']: p['wave'] for p in GL.PARTS}
    for b in built:
        if b not in waves:
            out.append('--built: no part %s' % b)
    # every owned routine is a head or a label of the graph
    for key, o in own.items():
        if o.startswith('out') or o in ('hook', 'math') or \
                key.startswith('?:'):
            continue
        if key not in g.label_head and key not in g.heads:
            out.append('%s (%s): no such code label' % (key, o))
    # every reachable routine is owned, the core's, math, a hook or out
    reach = tic_reach(g)
    for key in sorted(reach):
        if not classify(key, own) and key in g.heads:
            out.append('%s: reachable from the tic and owned by nobody'
                       % key)
        elif not classify(key, own) and key.startswith('?:'):
            out.append('%s: reachable and outside every unit read'
                       % key)
    # the rule of 2.2
    for p in GL.PARTS:
        mine = set(p['routines'] + p['helpers'])
        for key in mine:
            h = g.heads.get(g.head_of(key) or '')
            if h is None or h.key != key:
                continue
            for c in sorted(h.calls):
                c = g.head_of(c) or c
                o = classify(c, own)
                if o == p['name'] or o in ('core', 'math', 'hook'):
                    continue
                if o.startswith('out'):
                    continue        # (notes(): the part ports its effect)
                if o not in waves:
                    out.append('%s (%s) calls %s, owned by nobody' % (
                        key, p['name'], c))
                    continue
                if waves[o] >= waves[p['name']]:
                    out.append('%s (%s, wave %d) calls %s (%s, wave %d): '
                               'not an earlier wave' % (
                                   key, p['name'], waves[p['name']], c, o,
                                   waves[o]))
                elif p['name'] in built and o not in built:
                    out.append('%s (%s, built) calls %s (%s, not built)'
                               % (key, p['name'], c, o))
    # the core's calls into parts are the named ones (GL.CORE_CALLS)
    for key in GL.CORE:
        h = g.heads.get(key)
        if h is None:
            continue
        for c in sorted(h.calls):
            c = g.head_of(c) or c
            o = classify(c, own)
            if o in waves and c not in GL.CORE_CALLS and \
                    o not in ('core',):
                if not GL.core_inlines(key, c):
                    out.append('the core\'s %s calls %s (%s): not one of '
                               'glayout.CORE_CALLS' % (key, c, o))
    return out


def notes(g: Graph) -> List[str]:
    """The parts' calls into routines named out (GAME.md 0.1): each part
    ports the caller's game effect only (flow's st_tick of ST_Ticker,
    doLoadLevel's split at bmLoad)."""
    from native import glayout as GL
    own = owners()
    out = []
    for p in GL.PARTS:
        for key in p['routines'] + p['helpers']:
            h = g.heads.get(key)
            if h is None:
                continue
            for c in sorted(h.calls):
                o = classify(g.head_of(c) or c, own)
                if o.startswith('out'):
                    out.append('%s (%s) calls %s: %s' % (key, p['name'], c,
                                                         o[4:]))
    return out


def reach_targets(g: Graph, key: str) -> Dict[str, List[str]]:
    """The dispatch targets each table can deliver from key: a dispatcher
    of a table (glayout.DISPATCH) that key reaches can deliver every
    target of the table, and what those reach too (wave 1 as integrated:
    the static references alone gave P_SetMobjState only the rocket
    cheat's A_CyberAttack, so the survey never logged its actions;
    docs/game-parts/mobjstate.md R6, geom.md R10)."""
    from native import glayout as GL
    entries = GL.dispatch_entries(g)
    r = set(g.reach([key]))
    while True:
        more = set()
        for t, d in GL.DISPATCH.items():
            if any(x in r for x in d['dispatchers']):
                more |= {k for k in entries[t] if k not in r}
        if not more:
            break
        r |= set(g.reach(sorted(more)))
    return {t: sorted(k for k in entries[t] if k in r)
            for t in GL.DISPATCH}


# ---------------------------------------------------------------------------
# The stack (GAME.md 4.5)
# ---------------------------------------------------------------------------

def sccs(nodes: Sequence[str], edges: Dict[str, Set[str]]
         ) -> List[List[str]]:
    """Tarjan's strongly connected components, iteratively."""
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    stack: List[str] = []
    on: Set[str] = set()
    out: List[List[str]] = []
    counter = [0]
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(edges.get(root, ()))))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(edges.get(nxt, ())))))
                elif nxt in on:
                    low[v] = min(low[v], index[nxt])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(comp)
    return out


def stack_depth(g: Graph, image_of: Optional[Dict[str, str]] = None
                ) -> Dict[str, Any]:
    """The deepest chain from the roots (calls and dispatches), each
    strongly connected group once: 2 bytes a call, FCALL_STACK an FCALL
    across images (image_of: file:label -> its image; without it every
    call between two parts counts as one)."""
    from native import glayout as GL
    own = owners()
    reach = g.reach(ROOTS)
    edges: Dict[str, Set[str]] = {}
    for k in reach:
        h = g.heads.get(k)
        if h is not None:
            edges[k] = {g.head_of(c) or c for c in h.calls | h.refs}
    comps = sccs(sorted(reach), edges)
    comp_of = {k: i for i, c in enumerate(comps) for k in c}

    def cost(a: str, b: str) -> int:
        if image_of is not None:
            ia, ib = image_of.get(a, 'CORE'), image_of.get(b, 'CORE')
            cross = ia != ib and ib != 'CORE'
        else:
            oa, ob = classify(a, own), classify(b, own)
            cross = oa != ob and ob not in ('core', 'math', 'hook', '')
        return GL.FCALL_STACK if cross else 2
    # longest path on the condensation (Tarjan gives a reverse topological
    # order: callees' components first)
    best: Dict[int, Tuple[int, List[str]]] = {}
    for i, comp in enumerate(comps):
        top = (max(GL.OWN_STACK.get(v, 0) for v in comp), [comp[0]])
        for v in comp:
            own_v = GL.OWN_STACK.get(v, 0)     # (kept across its calls)
            if own_v > top[0]:
                top = (own_v, [v])
            for w in edges.get(v, ()):
                j = comp_of.get(w)
                if j is None or j == i:
                    continue
                d, path = best[j]
                c = d + cost(v, w) + own_v
                if c > top[0]:
                    top = (c, [v] + path)
        best[i] = top
    root = comp_of[ROOTS[0]]
    depth, path = best[root]
    return {'bytes': depth, 'irq': GL.IRQ_STACK,
            'total': depth + GL.IRQ_STACK, 'budget': GL.TIC_STACK,
            'ok': depth + GL.IRQ_STACK <= GL.TIC_STACK, 'chain': path,
            'groups': sum(1 for c in comps if len(c) > 1)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--built', default='')
    parser.add_argument('--reach')
    parser.add_argument('--stack', action='store_true')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--rebuild', action='store_true',
                        help='read the sources again (the cache is '
                             'build/native/game/shared/callgraph.json)')
    args = parser.parse_args(argv)
    if not (UPSTREAM / 'p_map65.s').exists():
        print('no upstream sources in %s: run python3 tools/'
              'fetch_upstream.py' % UPSTREAM, file=sys.stderr)
        return 2
    g = load(args.rebuild)
    status = 0
    built = [b for b in args.built.split(',') if b]
    if args.json:
        args.json.write_text(json.dumps(g.to_json(), indent=1,
                                        sort_keys=True))
    if args.check:
        fails = check(g, built)
        reach = tic_reach(g)
        print('%d heads, %d reachable from the tic; %d failures' % (
            len(g.heads), len(reach), len(fails)))
        for f in fails[:200]:
            print('  ' + f)
        status |= 1 if fails else 0
    if args.reach:
        for t, ks in reach_targets(g, args.reach).items():
            print('%s: %s' % (t, ', '.join(ks) or '-'))
    if args.stack:
        s = stack_depth(g)
        print('static depth %d B + %d IRQ = %d of %d: %s' % (
            s['bytes'], s['irq'], s['total'], s['budget'],
            'ok' if s['ok'] else 'OVER'))
        print('  ' + ' -> '.join(s['chain']))
        status |= 0 if s['ok'] else 1
    return status


if __name__ == '__main__':
    sys.exit(main())
