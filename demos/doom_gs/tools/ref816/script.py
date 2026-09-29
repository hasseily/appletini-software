"""Input scripts for ref816: read one and turn it into the machine's
input program (tools/ref816/program.h).

The format is in tools/ref816/README.md. In short, each line is

    [at WHEN] ACTION ...

WHEN is N or Nf (video frame N), Ns (N seconds of machine time) or Nt
(game tic N, the count _g_gametic), and +N, +Nf, +Ns, +Nt for that long
after the line before; a line without "at" happens right after the one
before. Seconds become whole frames; tics become waits on _g_gametic,
since only the game knows when its tics happen. Symbols (for wait,
poke) are names of the link map, "unit:name" where a name is not
unique, with "+offset"; the size is word unless byte or long comes
first.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ref816 import keys  # noqa: E402

MASTER_HZ = 14318180
FRAME_CLOCKS = 912 * 262
FRAME_RATE = MASTER_HZ / FRAME_CLOCKS           # 59.92 frames a second

GAMETIC = ('g_game65.s', '_g_gametic')
GAMETIC_SIZE = 4
SIZES = {'byte': 1, 'word': 2, 'long': 4}
TESTS = {'==': 'eq', '!=': 'ne', '>=': 'ge', '<': 'lt', 'grows': 'gain'}

PRESS_FRAMES = 6        # how long press holds a key down by default
TYPE_FRAMES = 4         # type: each key down this long, then up as long
WAIT_LIMIT_SECONDS = 120    # a wait without "within"
# The limit of a wait for tics: a tic takes 1/35 s of game time, and a
# slow machine runs at most 4 tics a frame of the game, so allow half a
# second a tic, and 10 seconds at least.
TIC_LIMIT_FRAMES = 30
TIC_LIMIT_MIN_FRAMES = 600
NAME = re.compile(r'[A-Za-z0-9_-]{1,63}$')


class ScriptError(ValueError):
    pass


class When(NamedTuple):
    relative: bool
    unit: str           # 'f', 's' or 't'
    amount: float


class Symbols:
    """The addresses of the game's labels, from the link map of
    tools/v816/imgmatch.py."""

    def __init__(self, linkmap: Dict):
        self.units = linkmap['game']['units']

    def address(self, reference: str) -> int:
        """The address of "name" or "unit:name", or a number, with an
        optional "+offset"."""
        base, plus, offset = reference.partition('+')
        extra = 0
        if plus:
            try:
                extra = int(offset, 0)
            except ValueError:
                raise ScriptError('%s: the offset is not a number'
                                  % reference) from None
        try:
            return int(base, 0) + extra
        except ValueError:
            pass
        unit, _, name = base.rpartition(':')
        if unit:
            value = self.units.get(unit, {}).get(name)
            if not isinstance(value, int):
                raise ScriptError('%s has no label %s' % (unit, name))
            return value + extra
        found = [labels[name] for labels in self.units.values()
                 if isinstance(labels.get(name), int)]
        if not found:
            raise ScriptError('no label is called %s' % name)
        if len(set(found)) > 1:
            raise ScriptError('%s is in more than one unit: say which'
                              % name)
        return found[0] + extra


def frames(seconds: float) -> int:
    """Seconds of machine time as whole video frames."""
    return int(round(seconds * FRAME_RATE))


def parse_when(text: str) -> When:
    match = re.match(r'(\+?)(\d+(?:\.\d+)?)([fst]?)$', text)
    if not match:
        raise ScriptError('a time is N, Nf, Ns or Nt, with + for one '
                          'after the line before: not %s' % text)
    relative, amount, unit = match.groups()
    unit = unit or 'f'
    value = float(amount)
    if unit != 's' and value != int(value):
        raise ScriptError('%s: frames and tics are whole' % text)
    return When(bool(relative), unit, value)


class Compiler:
    """Turns script lines into program lines. The program's own
    notion of time does the rest: each step counts from the one before,
    and `pending` is the WHEN of the next step."""

    def __init__(self, symbols: Symbols, source: str):
        self.symbols = symbols
        self.source = source
        self.lines: List[str] = []
        self.line = 0
        self.pending = '+0'

    def emit(self, action: str, after: Optional[int] = None) -> None:
        """A step, at the pending time or `after` frames after the step
        before."""
        when = self.pending if after is None else '+%d' % after
        self.pending = '+0'
        self.lines.append('%s %s  # %s:%d' % (when, action, self.source,
                                              self.line))

    def at(self, when: When) -> None:
        """Make `when` the time of the next step."""
        if when.unit == 't':
            gametic = self.symbols.address(':'.join(GAMETIC))
            tics = int(when.amount)
            test = 'gain' if when.relative else 'ge'
            limit = max(TIC_LIMIT_MIN_FRAMES, tics * TIC_LIMIT_FRAMES)
            self.emit('wait 0x%06X %d %s %d %d' % (
                gametic, GAMETIC_SIZE, test, tics, limit))
            return
        count = (frames(when.amount) if when.unit == 's'
                 else int(when.amount))
        self.pending = ('+%d' if when.relative else '%d') % count

    def compile_line(self, words: List[str]) -> None:
        if words[0] == 'at':
            if len(words) < 3:
                raise ScriptError('expected at WHEN ACTION')
            self.at(parse_when(words[1]))
            words = words[2:]
        action, arguments = words[0], words[1:]
        handler = getattr(self, 'do_' + action, None)
        if handler is None:
            raise ScriptError('unknown action %s' % action)
        handler(arguments)

    # ---- actions ----

    def do_key(self, arguments: List[str]) -> None:
        if len(arguments) != 2 or arguments[0] not in ('down', 'up'):
            raise ScriptError('expected key down|up NAME')
        self.emit('key %d %s' % (self.key(arguments[1]), arguments[0]))

    def do_press(self, arguments: List[str]) -> None:
        if len(arguments) not in (1, 2):
            raise ScriptError('expected press NAME [FRAMES]')
        hold = self.count(arguments[1]) if len(arguments) == 2 \
            else PRESS_FRAMES
        code = self.key(arguments[0])
        self.emit('key %d down' % code)
        self.emit('key %d up' % code, after=hold)

    def do_type(self, arguments: List[str]) -> None:
        if len(arguments) != 1:
            raise ScriptError('expected type TEXT (letters and digits)')
        for character in arguments[0].lower():
            if character not in keys.CHARACTERS:
                raise ScriptError('type takes letters and digits, not %r'
                                  % character)
            code = keys.CHARACTERS[character]
            self.emit('key %d down' % code)
            self.emit('key %d up' % code, after=TYPE_FRAMES)
            self.pending = '+%d' % TYPE_FRAMES

    def do_mouse(self, arguments: List[str]) -> None:
        if len(arguments) != 2:
            raise ScriptError('expected mouse DX DY')
        try:
            dx, dy = (int(a, 0) for a in arguments)
        except ValueError:
            raise ScriptError('mouse takes two whole numbers') from None
        self.emit('mouse %d %d' % (dx, dy))

    def do_button(self, arguments: List[str]) -> None:
        if not 1 <= len(arguments) <= 2 or arguments[0] not in ('down', 'up') \
                or arguments[1:] not in ([], ['0'], ['1']):
            raise ScriptError('expected button down|up [0|1]')
        number = arguments[1] if len(arguments) == 2 else '0'
        self.emit('button %s %s' % (number, arguments[0]))

    def do_shot(self, arguments: List[str]) -> None:
        self.named('shot', arguments)

    def do_note(self, arguments: List[str]) -> None:
        self.named('note', arguments)

    def do_wait(self, arguments: List[str]) -> None:
        size, arguments = self.size(arguments)
        limit = frames(WAIT_LIMIT_SECONDS)
        if len(arguments) == 5 and arguments[3] == 'within':
            within = parse_when(arguments[4])
            if within.relative or within.unit == 't':
                raise ScriptError('within takes frames or seconds')
            limit = (frames(within.amount) if within.unit == 's'
                     else int(within.amount))
            arguments = arguments[:3]
        if len(arguments) != 3 or arguments[1] not in TESTS:
            raise ScriptError('expected wait [byte|word|long] SYMBOL '
                              '==|!=|>=|<|grows VALUE [within TIME]')
        self.emit('wait 0x%06X %d %s %d %d' % (
            self.symbols.address(arguments[0]), size, TESTS[arguments[1]],
            self.value(arguments[2], size), limit))

    def do_poke(self, arguments: List[str]) -> None:
        size, arguments = self.size(arguments)
        if len(arguments) != 2:
            raise ScriptError('expected poke [byte|word|long] SYMBOL VALUE')
        self.emit('poke 0x%06X %d %d' % (
            self.symbols.address(arguments[0]), size,
            self.value(arguments[1], size)))

    def do_stop(self, arguments: List[str]) -> None:
        if arguments:
            raise ScriptError('stop takes nothing')
        self.emit('stop')

    # ---- words ----

    def named(self, action: str, arguments: List[str]) -> None:
        if len(arguments) != 1 or not NAME.match(arguments[0]):
            raise ScriptError('expected %s NAME (letters, digits, - and _)'
                              % action)
        self.emit('%s %s' % (action, arguments[0]))

    @staticmethod
    def key(name: str) -> int:
        try:
            return keys.code(name)
        except KeyError as error:
            raise ScriptError(error.args[0]) from None

    @staticmethod
    def count(text: str) -> int:
        if not text.isdigit():
            raise ScriptError('expected a number of frames, not %s' % text)
        return int(text)

    @staticmethod
    def size(arguments: List[str]) -> Tuple[int, List[str]]:
        if arguments and arguments[0] in SIZES:
            return SIZES[arguments[0]], arguments[1:]
        return SIZES['word'], arguments

    @staticmethod
    def value(text: str, size: int) -> int:
        try:
            value = int(text, 0)
        except ValueError:
            raise ScriptError('not a number: %s' % text) from None
        if not 0 <= value < 1 << (8 * size):
            raise ScriptError('%s does not fit in %d bytes' % (text, size))
        return value


def compile_script(text: str, symbols: Symbols, source: str = 'script'
                   ) -> str:
    """The machine's input program for the script `text`."""
    compiler = Compiler(symbols, source)
    for number, line in enumerate(text.splitlines(), 1):
        compiler.line = number
        words = line.split('#', 1)[0].split()
        if not words:
            continue
        try:
            compiler.compile_line(words)
        except ScriptError as error:
            raise ScriptError('%s:%d: %s' % (source, number, error)) from None
    return ''.join(line + '\n' for line in compiler.lines)
