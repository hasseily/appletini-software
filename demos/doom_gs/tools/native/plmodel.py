#!/usr/bin/env python3
"""The //e input's host model and its scripted sequences (milestone 11,
part plinput; docs/SCREENS.md 2.4, 6.5; docs/m11-parts/plinput.md).

The model is the specification src/native/pl_input.s and pl_keys.s are
compared with, written from the design, not from the 65C02 code: the
devices as a2vm has them (tools/a2vm/a2vm.c: the keyboard's latch and
taps, $C010's "a key is down", the Apple keys, the mouse card's X, buttons
and sequence byte) and the poll's rules (SCREENS.md 2.4):

  - a new code that is the held key while $C010 says down is the //e's
    auto-repeat: nothing; any other new code is a press: held, its
    character posted, a menu arrow starts upstream's repeat; no new code
    and $C010 clear: the held key goes up; a tap stays held one poll;
  - the Apple keys and the buttons are the pseudo-keys $72, $73, $71, $70;
  - a Doom key is down while any source down maps to it (upstream's counts,
    recomputed each poll); the changes posted from Doom key 22 to 0, then
    the press's character, then the repeat (11 tics, then every 4, while a
    menu is up and the arrow held);
  - a poll with fewer than 7 free events posts nothing and counts a
    deferral; the mouse is read in every poll;
  - the key setup (PL_BIND $FF) takes the first press, no event;
  - the mouse: X between two reads of the sequence byte (a second read when
    it changed), the motion added to PL_MDX, X outside $2000-$DFFF back to
    $8000.

The state is the input block's 59 bytes as pl_input.inc lays them out
(s2layout's INPUT, with PL_MLX and PL_BIND since wave 5's integration)
and the key table's Doom keys (PL_KEYTAB, 128 B: s2layout's KEYTAB_PLACE).

A sequence is a list of polls; before each poll, a2vm input events
(`key`, `hold`, `release`, `mouse`, `buttons`, `oa`, `ca`); after it, what
the consumer does (the queue drained, PL_MDX taken, a rebinding, the
defaults, the key setup's wait, I_ActionKeys). One poll may have a mouse
report between its two reads of X (a2vm `pc pl_xhi@N`). The polls come at
6, 10 or 35 a second: poll k at tic floor(k x 35 / rate) + 1.
"""

import random
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from native import plkeys as K, s2layout as S

# the input block (s2layout.INPUT: requests PLINPUT-1 to -3 applied)
LO = S.INPUT_LO
SIZE = S.INPUT_END - S.INPUT_LO                 # 59
OFF = {n: a - LO for n, a in S.INPUT.items()}
KEYTAB = S.KEYTAB_PLACE[0]                      # $1F80 (PLINPUT-1)
QBYTES = S.QUEUE_EVENTS * S.EVENT_SIZE          # 45
QROOM = 7                                       # a poll's events
EV_KEYDOWN, EV_KEYUP = 0, 1
BIND_WAIT, BIND_IDLE = 0xFF, 0x80
REP_DELAY, REP_RATE = 11, 4
CENTRE = 0x8000
RATES = (6, 10, 35)


class Devices:
    """The //e's keyboard and Apple keys and the mouse card, as a2vm."""

    def __init__(self):
        self.taps: List[int] = []
        self.latch = 0
        self.held = False
        self.oa = self.ca = False
        self.x = CENTRE                         # after pl_init
        self.buttons = 0                        # bit 0 left, bit 1 right
        self.seq = 0
        self.xhi_visits = 0

    def act(self, action: Tuple) -> None:
        verb = action[0]
        if verb == 'key':
            self.taps.append(action[1] & 0x7F)
        elif verb == 'hold':
            self.latch = (action[1] & 0x7F) | 0x80
            self.held = True
        elif verb == 'release':
            self.held = False
        elif verb == 'oa':
            self.oa = bool(action[1])
        elif verb == 'ca':
            self.ca = bool(action[1])
        elif verb == 'mouse':
            self.x = max(0, min(0xFFFF, self.x + action[1]))
            self.seq = (self.seq + 1) & 0xFF
        elif verb == 'buttons':
            self.buttons = (1 if action[1] else 0) | (2 if action[2] else 0)
            self.seq = (self.seq + 1) & 0xFF
        else:
            raise ValueError('no action %r' % (action,))

    def kbd(self) -> int:                       # $C000
        if not self.latch & 0x80 and self.taps:
            self.latch = self.taps.pop(0) | 0x80
        return self.latch

    def kbdstrb(self) -> int:                   # $C010 (a read)
        v = (0x80 if self.held else 0) | (self.latch & 0x7F)
        self.latch &= 0x7F
        return v


class Input:
    """The input block and the key table."""

    def __init__(self):
        self.mem = bytearray(SIZE)
        self.keys = K.doom_keys()

    def get(self, name: str, n: int = 1) -> int:
        o = OFF[name]
        return int.from_bytes(bytes(self.mem[o:o + n]), 'little')

    def put(self, name: str, value: int, n: int = 1) -> None:
        o = OFF[name]
        self.mem[o:o + n] = (value & ((1 << (8 * n)) - 1)).to_bytes(
            n, 'little')

    def init(self) -> None:
        """pl_init: the block 0, PL_BIND idle, X at the centre, the
        defaults (no source down: no event)."""
        self.mem = bytearray(SIZE)
        self.put('PL_BIND', BIND_IDLE)
        self.put('PL_MLX', CENTRE, 2)
        self.keys = K.doom_keys()

    def post(self, kind: int, data1: int) -> None:
        tail = self.get('PL_QTAIL')
        q = OFF['PL_QUEUE'] + tail
        self.mem[q:q + 3] = bytes([kind, data1, 0])
        nxt = tail + 3
        if nxt >= QBYTES:
            nxt = 0
        if nxt != self.get('PL_QHEAD'):
            self.put('PL_QTAIL', nxt)

    def mask(self, held: int, buttons: int, skip: int = 0) -> int:
        m = 0
        for code in [held] + [K.PSEUDO[i] for i in range(4)
                              if buttons >> i & 1]:
            if code and code != skip and self.keys[code] < K.NUMKEYS:
                m |= 1 << self.keys[code]
        return m

    def diff(self, old: int, new: int) -> None:
        for k in range(K.NUMKEYS - 1, -1, -1):
            if (old ^ new) >> k & 1:
                self.post(EV_KEYDOWN if new >> k & 1 else EV_KEYUP, k)

    def events(self) -> List[Tuple[int, int]]:
        """The events queued (head to tail)."""
        out = []
        h, t = self.get('PL_QHEAD'), self.get('PL_QTAIL')
        while h != t:
            q = OFF['PL_QUEUE'] + h
            out.append((self.mem[q], self.mem[q + 1] | self.mem[q + 2] << 8))
            h = (h + 3) % QBYTES
        return out

    # -- pl_poll ------------------------------------------------------------
    def poll(self, dev: Devices, menu: int, time: int,
             torn: Optional[int] = None, torn_visit: int = 0) -> None:
        used = (self.get('PL_QTAIL') - self.get('PL_QHEAD')) % QBYTES
        if used > QBYTES - S.EVENT_SIZE - 3 * QROOM:
            self.put('PL_DEFER', self.get('PL_DEFER') + 1)
            self.mouse(dev, torn, torn_visit)
            return
        held, buttons = self.get('PL_HELD'), self.get('PL_BUTTONS')
        bind = self.get('PL_BIND')
        old = self.mask(held, buttons)
        nh, ch, skip = held, 0, 0
        latch = dev.kbd()
        if latch & 0x80:
            code = K.fold(latch)
            down = dev.kbdstrb() & 0x80
            if not (down and code == held):
                nh = code
                if bind == BIND_WAIT:
                    self.put('PL_BIND', code)
                    skip = code
                else:
                    ch = K.char(code)
                    if K.KEYC['UP'] <= ch < K.KEYC['ENTER']:
                        self.put('PL_REPCH', ch)
                        self.put('PL_REPKEY', code)
                        self.put('PL_REPTIC', time + REP_DELAY, 2)
        elif not dev.kbdstrb() & 0x80:
            nh = 0
        nb = (8 if dev.ca else 0) | (4 if dev.oa else 0) | \
            (2 if dev.buttons & 1 else 0) | (1 if dev.buttons & 2 else 0)
        if self.get('PL_BIND') == BIND_WAIT:
            arrived = nb & ~buttons & 0x0F
            if arrived:
                i = (arrived & -arrived).bit_length() - 1
                self.put('PL_BIND', 0x70 + i)
                skip = 0x70 + i
        self.diff(old, self.mask(nh, nb, skip))
        if ch:
            self.post(EV_KEYDOWN, ch)
        if self.get('PL_REPCH'):
            if self.get('PL_REPKEY') != nh:
                self.put('PL_REPCH', 0)
            elif menu:
                d = (time - self.get('PL_REPTIC', 2)) & 0xFFFF
                if d < 0x8000:
                    self.put('PL_REPTIC', self.get('PL_REPTIC', 2) + REP_RATE,
                             2)
                    self.post(EV_KEYDOWN, self.get('PL_REPCH'))
        self.put('PL_HELD', nh)
        self.put('PL_BUTTONS', nb)
        self.mouse(dev, torn, torn_visit)

    def mouse(self, dev: Devices, torn: Optional[int], torn_visit: int
              ) -> None:
        tries = 2
        while True:
            s1 = dev.seq
            lo = dev.x & 0xFF
            dev.xhi_visits += 1
            if torn is not None and dev.xhi_visits == torn_visit:
                dev.act(('mouse', torn))
            hi = dev.x >> 8
            s2 = dev.seq
            tries -= 1
            if s1 == s2 or tries == 0:
                break
        x = hi << 8 | lo
        motion = (x - self.get('PL_MLX', 2)) & 0xFFFF
        self.put('PL_MDX', self.get('PL_MDX', 2) + motion, 2)
        self.put('PL_MLX', x, 2)
        if hi < 0x20 or hi >= 0xE0:
            dev.x = CENTRE
            self.put('PL_MLX', CENTRE, 2)

    # -- pl_keys.s ----------------------------------------------------------
    def recount(self, change) -> None:
        held, buttons = self.get('PL_HELD'), self.get('PL_BUTTONS')
        old = self.mask(held, buttons)
        change()
        self.diff(old, self.mask(held, buttons))

    def bind(self, key: int, code: int) -> None:
        def change():
            self.keys = [K.NOKEY if k == key else k for k in self.keys]
            self.keys[code] = key
        self.recount(change)

    def defaults(self) -> None:
        def change():
            self.keys = K.doom_keys()
        self.recount(change)

    def action(self, key: int) -> Tuple[int, int]:
        found = [c for lo, hi in ((0x30, 0x40), (0x20, 0x30), (0x00, 0x20),
                                  (0x40, 0x80)) for c in range(lo, hi)
                 if self.keys[c] == key]
        found += [0xFF, 0xFF]
        return found[0], found[1]


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

# the consumer's flags after a poll (pl_it.s's schedule, +3)
F_DRAIN, F_TAKE, F_BIND, F_DEFAULTS, F_WAIT, F_TAKEN, F_ACTION = \
    1, 2, 4, 8, 16, 32, 64
F_CONSUME = F_DRAIN | F_TAKE


class Poll(NamedTuple):
    before: Tuple[Tuple, ...] = ()      # a2vm events before the poll
    menu: int = 0
    flags: int = F_CONSUME
    a4: int = 0                         # pl_bind's key, pl_action's key
    a5: int = 0                         # pl_bind's code
    torn: Optional[int] = None          # a report between X's reads


class Sequence_(NamedTuple):
    name: str
    polls: Tuple[Poll, ...]


def tics(rate: int, n: int) -> List[int]:
    """The tic of each poll at `rate` polls a second (35 tics a second);
    the first at tic 1, after the clock's first tic."""
    return [k * 35 // rate + 1 for k in range(n)]


class Result(NamedTuple):
    blocks: List[bytes]             # the block after each poll
    tables: List[List[int]]         # the key table after each poll
    actions: Dict[int, Tuple[int, int]]     # poll: pl_action's A, X
    events: List[List[Tuple[int, int]]]     # the queue after each poll


def run(seq: Sequence_, rate: int) -> Result:
    """The model over a sequence: the state after each poll (before the
    consumer's flags), and pl_action's answers."""
    dev, st = Devices(), Input()
    st.init()
    times = tics(rate, len(seq.polls))
    blocks, tables, evs = [], [], []
    actions: Dict[int, Tuple[int, int]] = {}
    for k, p in enumerate(seq.polls):
        for a in p.before:
            dev.act(a)
        st.poll(dev, p.menu, times[k], p.torn,
                dev.xhi_visits + 1 if p.torn is not None else 0)
        blocks.append(bytes(st.mem))
        tables.append(list(st.keys))
        evs.append(st.events())
        if p.flags & F_DRAIN:
            st.put('PL_QHEAD', st.get('PL_QTAIL'))
        if p.flags & F_TAKE:
            st.put('PL_MDX', 0, 2)
        if p.flags & F_BIND:
            st.bind(p.a4, p.a5)
        if p.flags & F_DEFAULTS:
            st.defaults()
        if p.flags & F_WAIT:
            st.put('PL_BIND', BIND_WAIT)
        if p.flags & F_TAKEN:
            st.put('PL_BIND', BIND_IDLE)
        if p.flags & F_ACTION:
            actions[k] = st.action(p.a4)
    return Result(blocks, tables, actions, evs)


def torn_visit(seq: Sequence_) -> Optional[Tuple[int, int]]:
    """(the poll, pl_xhi's visit) of the sequence's report between the
    reads (at most one a sequence: each poll visits once, and once more
    after a report there)."""
    torn = [k for k, p in enumerate(seq.polls) if p.torn is not None]
    if not torn:
        return None
    if len(torn) > 1:
        raise ValueError('%s: one torn read a sequence' % seq.name)
    return torn[0], torn[0] + 1


def a2vm_events(seq: Sequence_, xhi: int) -> List[str]:
    """The sequence's a2vm input lines: poll k's events after boundary k
    (the snapshot of poll k - 1, 1-based); the torn read at pl_xhi."""
    out = []
    for k, p in enumerate(seq.polls):
        if p.before and k == 0:
            raise ValueError('%s: events before the first poll' % seq.name)
        for a in p.before:
            words = [a[0]] + ['0x%02X' % v if a[0] in ('key', 'hold')
                              else str(v) for v in a[1:]]
            if a[0] == 'mouse':
                words.append('0')
            out.append('boundary %d %s' % (k, ' '.join(words)))
    tv = torn_visit(seq)
    if tv:
        out.append('pc %X@%d mouse %d 0' % (xhi, tv[1],
                                            seq.polls[tv[0]].torn))
    return out


# -- the scripted sequences -------------------------------------------------

def _c(x) -> int:
    return ord(x) if isinstance(x, str) else x


def key(x) -> Tuple:
    return ('key', _c(x))


def hold(x) -> Tuple:
    return ('hold', _c(x))


REL = ('release',)


def quiet(n: int, **kw) -> List[Poll]:
    return [Poll(**kw) for _ in range(n)]


def steps(*events_lists, **kw) -> List[Poll]:
    return [Poll(before=tuple(e), **kw) for e in events_lists]


def sq(name: str, *parts) -> Sequence_:
    polls: List[Poll] = [Poll()]                # the first: nothing before
    for p in parts:
        polls += p if isinstance(p, list) else [p]
    return Sequence_(name, tuple(polls))


def random_sequence(seed: int, n: int = 60) -> Sequence_:
    rnd = random.Random(seed)
    codes = [c for c in range(1, 128) if not 0x61 <= c <= 0x7A] + \
        [ord(c) for c in 'wasdepq']
    polls: List[Poll] = [Poll()]
    torn_done = False
    for k in range(1, n):
        ev: List[Tuple] = []
        for _ in range(rnd.choice((0, 0, 1, 1, 2, 3))):
            r = rnd.random()
            if r < 0.25:
                ev.append(key(rnd.choice(codes)))
            elif r < 0.45:
                ev.append(hold(rnd.choice(codes)))
            elif r < 0.55:
                ev.append(REL)
            elif r < 0.7:
                ev.append(('mouse', rnd.randint(-3000, 3000)))
            elif r < 0.8:
                ev.append(('buttons', rnd.randint(0, 1), rnd.randint(0, 1)))
            elif r < 0.9:
                ev.append(('oa', rnd.randint(0, 1)))
            else:
                ev.append(('ca', rnd.randint(0, 1)))
        flags = F_CONSUME if rnd.random() < 0.8 else rnd.choice(
            (0, F_DRAIN, F_TAKE))
        torn = None
        if not torn_done and k > n // 2 and rnd.random() < 0.1:
            torn, torn_done = rnd.choice((-700, 900, 300)), True
        polls.append(Poll(tuple(ev), menu=rnd.randint(0, 1), flags=flags,
                          torn=torn))
    return Sequence_('random %d' % seed, tuple(polls))


def sequences() -> List[Sequence_]:
    """The checkpoint's scripted sequences (SCREENS.md 7.3 plinput: taps,
    holds, the //e's auto-repeat, two keys overlapping, a tap between
    polls, the Apple keys, the mouse moving, re-centring, both buttons, the
    menu's arrow repeat, a rebinding, lower-case keys, a nearly full queue
    deferring a key)."""
    W, D, A, SP, UP, DN, LT, RT = 'W', 'D', 'A', K.SPACE, K.UP, K.DOWN, \
        K.LEFT, K.RIGHT
    out = [
        sq('tap', steps([key(W)], [], [key(D)], [])),
        sq('hold and release', steps([hold(W)], [], [], [], [REL], [])),
        sq('the //e auto-repeat', steps([hold(W)], [], [hold(W)], [hold(W)],
                                        [], [hold(W)], [REL], [])),
        sq('auto-repeat of an arrow', steps([hold(UP)], [hold(UP)], [],
                                            [hold(UP)], [REL], [])),
        sq('two keys overlapping', steps([hold(W)], [], [hold(D)], [],
                                         [REL], [])),
        sq('overlap: the same Doom key', steps([hold(W)], [hold(UP)], [],
                                               [hold('S')], [REL], [])),
        sq('a tap between polls', steps([hold(A), REL], [], [hold(W)],
                                        [hold(SP), REL], [])),
        sq('two taps between polls', steps([key(W), key(D)], [], [], [])),
        sq('the same key again after its release', steps(
            [hold(W)], [], [REL, key(W)], [], [])),
        sq('a key held, a tap of another', steps(
            [hold(W)], [], [key(SP)], [], [], [REL])),
        sq('Open Apple', steps([('oa', 1)], [], [('oa', 0)], [])),
        sq('Solid Apple', steps([('ca', 1)], [], [], [('ca', 0)], [])),
        sq('both Apple keys', steps([('oa', 1), ('ca', 1)], [],
                                    [('oa', 0)], [('ca', 0)], [])),
        sq('fire shared: Open Apple and mouse 1', steps(
            [('oa', 1)], [('buttons', 1, 0)], [('oa', 0)], [],
            [('buttons', 0, 0)], [])),
        sq('use shared: Space, Solid Apple, Return', steps(
            [hold(SP)], [('ca', 1)], [hold(K.RETURN)], [REL], [('ca', 0)],
            [])),
        sq('both buttons', steps([('buttons', 1, 1)], [],
                                 [('buttons', 0, 1)], [('buttons', 0, 0)],
                                 [])),
        sq('everything down, then up', steps(
            [hold(SP)], [('oa', 1)], [('ca', 1)], [('buttons', 1, 0)],
            [('buttons', 1, 1)], [('buttons', 0, 1)], [('ca', 0)],
            [('oa', 0)], [REL], [('buttons', 0, 0)], [])),
        sq('the mouse moving', steps(*[[('mouse', 5)] for _ in range(6)],
                                     [], [('mouse', -9)], [('mouse', -9)])),
        sq('the mouse fast, both ways', steps(
            [('mouse', 400)], [('mouse', -1200)], [('mouse', 700),
                                                   ('mouse', 50)], [])),
        sq('re-centring to the right', steps(
            [('mouse', 0x3000)], [('mouse', 0x2000)], [('mouse', 0x1000)],
            [('mouse', 10)], [])),
        sq('re-centring to the left', steps(
            [('mouse', -0x5000)], [('mouse', -0x1200)], [('mouse', -10)],
            [])),
        sq('the mouse at the window\'s end', steps(
            [('mouse', 0x7F00)], [('mouse', 0x7FFF)], [('mouse', -0x8000)],
            [('mouse', -0x8000)], [])),
        sq('the motion kept', steps([('mouse', 3000)], [('mouse', -200)],
                                    [('mouse', 30000)], flags=0) +
           steps([], [('mouse', 1)])),
        sq('a report between the reads', steps(
            [('mouse', 20)], [], [('mouse', 5)]) +
           [Poll(torn=300)] + steps([], [('mouse', -2)])),
        sq('a report between the reads, re-centred', steps(
            [('mouse', 0x5800)]) + [Poll(torn=0x500)] + steps([])),
        sq('the menu\'s arrow repeat', steps([hold(DN)], menu=1) +
           quiet(24, menu=1) + steps([REL], menu=1) + quiet(2, menu=1)),
        sq('no repeat without a menu', steps([hold(DN)]) + quiet(16) +
           steps([REL])),
        sq('the menu closes in a repeat', steps([hold(UP)], menu=1) +
           quiet(14, menu=1) + quiet(6) + quiet(4, menu=1) + steps([REL])),
        sq('a repeat stopped by another key', steps([hold(LT)], menu=1) +
           quiet(14, menu=1) + steps([hold(W)], menu=1) +
           quiet(8, menu=1)),
        sq('an arrow tapped', steps([key(RT)], [], [key(RT)], [],
                                    menu=1)),
        sq('the auto-repeat of a menu arrow', steps([hold(RT)], menu=1) +
           steps(*[[hold(RT)] for _ in range(12)], menu=1) +
           steps([REL], menu=1)),
        sq('a rebinding', [Poll(flags=F_CONSUME | F_BIND, a4=K.KEY['FIRE'],
                                a5=ord('Q'))] +
           steps([key('Q')], [], [('oa', 1)], [], [('oa', 0)], [])),
        sq('a rebinding of the held key', steps([hold(W)]) +
           [Poll(flags=F_CONSUME | F_BIND, a4=K.KEY['FIRE'], a5=ord('W')),
            Poll(), Poll(before=(REL,))] + quiet(2)),
        sq('a rebinding while fire is held', steps([('oa', 1)]) +
           [Poll(flags=F_CONSUME | F_BIND, a4=K.KEY['FIRE'],
                 a5=ord('F'))] + steps([('oa', 0)], [hold('F')], [REL])),
        sq('the defaults back', [Poll(flags=F_CONSUME | F_BIND,
                                      a4=K.KEY['UP'], a5=ord('I'))] +
           steps([hold('I')], [], [REL]) +
           [Poll(before=(hold('W'),), flags=F_CONSUME | F_DEFAULTS)] +
           steps([], [REL], [])),
        sq('I_ActionKeys', [Poll(flags=F_CONSUME | F_ACTION, a4=k)
                            for k in range(K.NUMKEYS)] +
           [Poll(flags=F_CONSUME | F_BIND, a4=K.KEY['USE'], a5=ord('U')),
            Poll(flags=F_CONSUME | F_ACTION, a4=K.KEY['USE']),
            Poll(flags=F_CONSUME | F_ACTION, a4=K.NOKEY)]),
        sq('the key setup takes a key', [Poll(flags=F_CONSUME | F_WAIT)] +
           steps([hold('K')], [hold('K')], [], [REL]) +
           [Poll(flags=F_CONSUME | F_TAKEN)] + steps([key('K')], [])),
        sq('the key setup takes a held arrow', steps([hold(W)]) +
           [Poll(flags=F_CONSUME | F_WAIT, menu=1)] +
           steps([hold(UP)], [hold(UP)], [], menu=1) +
           [Poll(flags=F_CONSUME | F_TAKEN, menu=1)] + steps([REL], [])),
        sq('the key setup takes a button', [Poll(flags=F_CONSUME | F_WAIT)] +
           steps([('buttons', 0, 1), ('ca', 1)], [], [('buttons', 0, 0)],
                 [('ca', 0)]) + [Poll(flags=F_CONSUME | F_TAKEN)] +
           steps([('buttons', 0, 1)], [('buttons', 0, 0)])),
        sq('the key setup takes Open Apple', steps([('buttons', 1, 0)]) +
           [Poll(flags=F_CONSUME | F_WAIT)] +
           steps([('oa', 1)], [('oa', 0)], [('buttons', 0, 0)])),
        sq('lower-case keys', steps([key('w')], [hold('p')], [], [REL],
                                    [key('q')], [hold('s')], [hold('S')],
                                    [REL], [key('r')], [])),
        sq('typing p (not MOUSE 2)', steps([key('p')], [], [hold('p')],
                                           [hold('p')], [REL], [])),
        sq('every lower-case letter', steps(
            *[[key(chr(c))] for c in range(ord('a'), ord('z') + 1)], [])),
        sq('every code', steps(*[[key(c)] for c in range(0, 128)], [])),
        sq('the control keys', steps(*[[hold(c), REL] for c in
                                       (1, 3, 8, 9, 0x0D, 0x1B, 0x7F, 0x15,
                                        0x0B, 0x0A)], [])),
        sq('a nearly full queue defers a key', steps(
            [key(W)], [key(D)], [key(A)], [key('S')], [key('E')], [], [],
            flags=0) + [Poll(flags=F_CONSUME)] + quiet(4)),
        sq('a deferred poll keeps the Apple keys and the mouse', steps(
            [hold(W), ('oa', 1)], [hold(D), ('mouse', 77)],
            [hold(SP), ('ca', 1), ('mouse', -20)],
            [hold(A), ('oa', 0), ('mouse', 3)], [('ca', 0), REL], [],
            flags=0) + [Poll(flags=F_CONSUME)] + quiet(3)),
        sq('a full queue in the menu', steps([hold(DN)], menu=1, flags=0) +
           quiet(30, menu=1, flags=0) + [Poll(menu=1)] + quiet(8, menu=1) +
           steps([REL])),
        sq('Ctrl-@ and the folded codes', steps(
            [key(0)], [key(0x60)], [key(0x7B)], [key(0x7F)], [hold(0x70)],
            [hold(0x74)], [REL], [])),
    ]
    out += [random_sequence(seed) for seed in (1, 2, 3, 4, 5, 6)]
    for s in out:
        if len(s.polls) > 255:
            raise ValueError('%s: %d polls' % (s.name, len(s.polls)))
        torn_visit(s)
    return out
