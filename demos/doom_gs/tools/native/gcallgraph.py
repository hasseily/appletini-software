"""The call graph of upstream's game units (docs/GAME.md): a read of the
sources with the release's conditionals, keyed file:label; glayout.py's
dispatch tables take the states' actions and the heads from it.

The sources are read by our own front end (tools/v816/frontend.py: the
preprocessor with the Makefile's TICSTEP, the macros expanded), never
upstream's assembler; src/iigs/cal_integer.s is never read (the ground
rules: the vendor runtime): a call into it is a call of the native math
(src/native/math.s) by the callee's name only.

A routine is a head: an exported label, the target of a jsr, jsl or jml,
or a code label another routine names as a function pointer (an
immediate, a relocation or a data word); every other code label belongs
to the head before it. An edge is a call (jsr, jsl, jml, or a jmp, brl or
bra to another head: a tail call); a function pointer named in an operand
is a reference. The game units are p_*.s, g_game65.s, d_main65.s,
m_cheat65.s and m_random65.s; the graph follows calls out of them into
r_list65.s, w_level65.s, hu_stuff65.s, st_stuff65.s and wi_stuff65.s.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
UPSTREAM = BUILD / 'upstream' / 'src' / 'iigs'
FORBIDDEN = 'cal_integer.s'
GAME_UNITS_FIXED = ('g_game65.s', 'd_main65.s', 'm_cheat65.s',
                    'm_random65.s')
FOLLOWED = ('r_list65.s', 'w_level65.s', 'hu_stuff65.s', 'st_stuff65.s',
            'wi_stuff65.s')
# info65.s: the states, whose action pointers ACTTAB numbers
INFO = 'info65.s'
CALLS = ('jsr', 'jsl', 'jml')
JUMPS = ('jmp', 'brl', 'bra')


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


def load() -> Graph:
    """The graph, read from upstream's sources."""
    return Graph.read()
