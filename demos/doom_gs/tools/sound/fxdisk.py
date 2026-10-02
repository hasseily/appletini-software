#!/usr/bin/env python3
"""The effects' test disk SOUNDS.hdv (milestone 11, part fxdisk) and its
checks on a2vm.

Usage (from demos/doom_gs):
  python3 tools/sound/fxdisk.py [--out FILE]
      SFX.1 (part fxconv's make, so an edited tools/sound/fxtune.txt is
      taken), SOUNDS.SYSTEM (make -f m11.mk part P=fxdisk) and the disk,
      build/sound/SOUNDS.hdv by default.
  python3 tools/sound/fxdisk.py --check [--jobs N]
      The disk, then the checkpoint on a2vm (below).
  python3 tools/sound/fxdisk.py --planted [--jobs N]
      Each planted bug in a scratch copy of sounds.s: its check must fail.
  python3 tools/sound/fxdisk.py --inc OUT
      The 52 effects' names for sounds.s (the build's sfxnames.inc).

The disk, a ProDOS volume SOUNDS made with the existing port's disk
writer (demos/doom/tools/build_disk.py with appletini-one's
ProDOS_2_4_3.po, as tools/sound/musicdisk.py makes MUSIC.hdv), holds:

  SOUNDS.SYSTEM  src/sound/sounds.s with S2's player and probe, pl_irq.s
                 and fx.s, linked by src/sound/sounds.cfg: $2000-$3FFF the
                 program, $4000-$56FF the card image $E900-$FFFF
  SFX.1          the game's bank file of bank SFX (part fxconv), the ten
                 tuned effects tuned
  SFXAUTO.1      the same with every script automatic: SOUNDS.SYSTEM puts
                 the ten automatic scripts after SFX.1 in the bank, for T
  E1M1.AY        D_E1M1's song file (mus2ay.py, now), for M
  PROFILE.TXT    the Doom configuration profile (musicdisk.py's text)

What SOUNDS.SYSTEM does is in src/sound/sounds.s; tools/sound/README.md
"The test disk SOUNDS.hdv" says how the owner uses it.

--check runs the disk's SOUNDS.SYSTEM on a2vm: the MLI trap serves the
disk's files, the exact W65C02S core, the cost model on the model's clock
with the Phasor's slowdown in the Doom profile (f121+phasor+window32),
every interrupt held to the game's contract (--irq-bounds 00D8-01FF,
C0A0-C0AF,C400-C4FF,E000-FFFF), the AY log, a write log of the effects'
card state, the rings, S2's snd_playing and the program's step marker
sds_mark. Keys are a2vm input events at the Nth visit of sds_service,
the main loop's once-a-VBL service.

The oracle. UiModel, written from the README's key table (not from the
65C02 code), turns the key events into the steps the program must take,
each with its arguments (the mailbox starts with their sound, volume and
separation, the stops, the volume changes, the services, the tuned or
automatic entry, the standard, the song's start and stop) and the visit
it falls in. The machine's sds_mark gives each step's time and the
frames' (fx_service, snd_refill); its steps must be the model's, in
order, kind for kind, each in its visit. Taken in time order with the
interrupts of the AY log, the models run them: an interrupt is S2's music
(run65.RingPlayer, the song of the latest start) then fxplay.FxPlayer.
step(); a frame is fx_service, then snd_refill. Every interrupt's AY
writes must equal the models', write for write (chips 0-2, then chip 3);
the main loop's writes too (the chips' resets, each song start's burst);
the chips at the end; the publish order of the rings (fxrun65's). The
effects' model reads a bank of its own: SFX.1 at $0200 and SFXAUTO.1's
bytes $8000 higher, its directory entry of a tuned effect switched by T
to the automatic script there: the same script bytes as the program's,
at other addresses.

The checks (each a2vm run, at most `--jobs` at a time, each bounded in
time and file size, in a build/tmp-fxdisk-* directory deleted after):

  left      every effect on the left and centre voices (RETURN: C, A:
            A, C: C by the fallback, in turn), at the
            three distances in turn, PAL; the boot's screen; the bank
            SFX and the song's bank after the boot, byte for byte
  right     every effect on voice B, the distances in turn
  tuned     each of the ten tuned effects tuned on A, then T and its
            automatic script on B, then T back; the effect line (TUNED or
            AUTO, the script's checksum, the distance, the voice) and the
            list's marks after each T
  music     M (D_E1M1), every effect over it by RETURN, A, B, C in turn,
            then V (NTSC tables: the song again, the effects' tempo), more
            effects, M again (silence)
  ntsc      an NTSC machine (pl_detect): effects, a volume change while
            one plays (1, 2, 3), the repeat (R) for 3 s, S stopping it,
            then ESC: the quit
  quit      an effect and the music, then q: snd_init's resets the last AY
            events, the card's former contents back byte for byte, the
            Phasor in Mockingboard mode, ProDOS's QUIT
  nonative  --phasor-mb-only: the second line says NO EFFECTS: NO NATIVE
            MODE; every key (RETURN, A, B, C, 1-3, T, R, M, V, S) writes no
            AY register (the probe's and snd_init's only); no song file
            opened; Q quits

Standard library only.
"""

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
if str(HERE.parent / 'native') not in sys.path:
    sys.path.insert(0, str(HERE.parent / 'native'))

from sound import fxconv, fxplay, mus, mus2ay, musicdisk, player, run65  # noqa: E402,E501
from sound import tables  # noqa: E402
from a2vm import costs  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = HERE.parents[1]
BUILD = ROOT / 'build'
M11 = BUILD / 'native' / 'm11'
PART = M11 / 'fxdisk'
FXCONV_OUT = M11 / 'fxconv'
OUT = BUILD / 'sound' / 'SOUNDS.hdv'
SRC = ROOT / 'src' / 'sound'
NATIVE_SRC = ROOT / 'src' / 'native'
SOUND65 = BUILD / 'sound65'
A2VM = run65.A2VM

VOLUME = 'SOUNDS'
SYSTEM = 'SOUNDS.SYSTEM'
MAIN_SIZE, LC_SIZE = 0x2000, 0x1700     # sounds.cfg: $2000-$3FFF, $E900-
A2LI = bytes((0xC1, 0xB2, 0xCC, 0xE9))   # docs/MEMORY_MAP.md rule 8
IRQ_BOUNDS = '00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF'   # MEMORY_MAP rule 2
VARIANTS = ('phasor', 'window32')       # the Doom profile (NATIVE.md 15.1)
TIMEOUT = 600.0                         # a run's wall-time bound (seconds)
BUILD_TIMEOUT = 600.0
MAX_BYTES = 256 << 20                   # the largest file a run may write
WRITE_LOG_LIMIT = 2_000_000
JOBS = 2

NSFX = fxplay.SOUNDS                    # 52
COLROWS = 18
SONG_NAME = 'D_E1M1'
SONG_BANK, SONG_AT = 100, 0x1000        # sounds.s (s2layout SONGS[0])
SFX_BANK = 103                          # s2layout SFX
SFX_AT = fxplay.BANK_BASE               # $0200
SFX_END = 0x4000                        # s2layout SFX_ROOM
AUTO_OFF = 0x8000                       # the model's automatic scripts
VOLS = (127, 63, 6)                     # 1 near, 2 mid, 3 far
SEP = {'return': 128, 'A': 64, 'B': 200, 'C': 64}
SONG_LOOP, SONG_NTSC = 0x01, 0x80

# sds_mark: fxrun65.py's action codes and the program's own
SONG, SONGSTOP, START, STOP, VOLUME_, STOPALL, SERVICE = 1, 2, 3, 4, 5, 7, 10
TOGGLE, STD, QUIT = 11, 12, 0xFF
FRAME, REFILL = 0x80, 0x81
KIND_NAMES = {SONG: 'SONG', SONGSTOP: 'SONGSTOP', START: 'START',
              STOP: 'STOP', VOLUME_: 'VOLUME', STOPALL: 'STOPALL',
              SERVICE: 'SERVICE', TOGGLE: 'TOGGLE', STD: 'STD',
              QUIT: 'QUIT'}

# a2vm's key codes
KEY_CODES = {'up': '0x0B', 'down': '0x0A', 'left': '0x08', 'right': '0x15',
             'return': '0x0D', 'esc': '0x1B', 'space': '32'}


class CheckFailed(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


# ---------------------------------------------------------------------------
# the program's include, the checksum, the screen
# ---------------------------------------------------------------------------

def names_inc() -> str:
    lines = ['; Generated by tools/sound/fxdisk.py --inc (fxconv.py NAMES).'
             ' Do not edit.', '.macro SFX_NAMES', 'sfx_names:']
    for name in fxconv.NAMES:
        if len(name) > 6:
            raise ValueError('%s: a name has at most 6 characters' % name)
        lines.append('        .byte   "%s"' % name.ljust(6))
    lines += ['.endmacro', '']
    return '\n'.join(lines)


def script_sum(data: bytes) -> int:
    """The screen's checksum of a script (its header included): for each
    byte, the 16-bit sum rotated left one bit, then the byte added."""
    s = 0
    for b in data:
        s = ((s << 1) | (s >> 15)) & 0xFFFF
        s = (s + b) & 0xFFFF
    return s


def entry(bank_file: bytes, sound: int) -> Tuple[int, int]:
    at = 4 * (sound - 1)
    return struct.unpack_from('<HH', bank_file, at)


def script_of(bank_file: bytes, sound: int) -> bytes:
    a, n = entry(bank_file, sound)
    return bank_file[a - SFX_AT:a - SFX_AT + n]


def tuned_of(bank_file: bytes) -> List[bool]:
    return [bool(script_of(bank_file, s)[1] & fxconv.FLAG_TUNED)
            for s in range(1, NSFX + 1)]


def place(row: List[str], column: int, text: str) -> None:
    row[column:column + len(text)] = list(text)


def machine_row(ntsc: bool, native: bool, songon: bool, rep: bool) -> str:
    row = [' '] * 40
    place(row, 0, 'NTSC //E' if ntsc else 'PAL //E')
    if not native:
        place(row, 9, 'NO EFFECTS: NO NATIVE MODE')
    else:
        place(row, 9, 'PHASOR NATIVE  CHIP 3')
        if songon:
            place(row, 31, 'MUSIC')
        if rep:
            place(row, 37, 'REP')
    return ''.join(row).rstrip()


def list_rows(cur: int, tuned: Sequence[bool], ver: Sequence[int]
              ) -> List[str]:
    rows = [[' '] * 40 for _ in range(COLROWS)]
    for i, name in enumerate(fxconv.NAMES):
        row, x = rows[i % COLROWS], 13 * (i // COLROWS)
        mark = ' ' if not tuned[i] else ('T' if ver[i] == 0 else 'A')
        place(row, x, '%s %-6s %s' % ('>' if i == cur else ' ', name, mark))
    return [''.join(r).rstrip() for r in rows]


def effect_row(cur: int, version: str, total: int, dist: int,
               voice: Optional[str]) -> str:
    row = [' '] * 40
    place(row, 0, fxconv.NAMES[cur])
    place(row, 7, version)
    place(row, 13, 'SUM %04X' % total)
    place(row, 22, ('NEAR', 'MID', 'FAR')[dist])
    if voice is not None:
        place(row, 27, voice)
    return ''.join(row).rstrip()


TITLE = 'DOOM GS: THE EFFECTS ON THE PHASOR'
KEY_ROWS = ['ARROWS CHOOSE  RETURN PLAY  A B C VOICE',
            '1 NEAR 2 MID 3 FAR  T TUNED  R REPEAT',
            'M MUSIC  S STOP  V PAL/NTSC  Q QUIT']
# the screen's voice names, from chip 3's table (tables.FX_VOICES)
VOICE_TEXT: Dict[Optional[int], str] = {
    k: '%s %s' % (v.name, v.side.upper())
    for k, v in enumerate(tables.FX_VOICES)}
VOICE_TEXT[None] = '-'


# ---------------------------------------------------------------------------
# the build and the disk
# ---------------------------------------------------------------------------

def tool(args, what, cwd=None):
    """A build step under bounded.run; RuntimeError when it fails or
    warns."""
    result = bounded.run(args, timeout=BUILD_TIMEOUT, max_bytes=MAX_BYTES,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True, cwd=cwd)
    if result.returncode:
        raise RuntimeError('%s failed:\n%s' % (what, result.stdout))
    warnings = [line for line in result.stdout.splitlines()
                if 'warning' in line.lower()]
    if warnings:
        raise RuntimeError('%s warns:\n%s' % (what, '\n'.join(warnings)))
    return result.stdout


def have_tools() -> bool:
    return run65.have_cc65() and bool(shutil.which('make')) and \
        musicdisk.have_wad() and musicdisk.have_disk_tools() and \
        all((SOUND65 / n).exists() for n in ('player.o', 'probe.o',
                                             'tables.inc'))


def make_sfx() -> Tuple[bytes, bytes]:
    """SFX.1 and SFXAUTO.1 by part fxconv's make (remade when
    fxtune.txt or the converter changed)."""
    tool(['make', '-s', '-f', str(NATIVE_SRC / 'm11' / 'fxconv.mk'),
          'fxconv'], 'make fxconv', cwd=str(ROOT))
    return ((FXCONV_OUT / 'SFX.1').read_bytes(),
            (FXCONV_OUT / 'SFXAUTO.1').read_bytes())


def make_program(m11: Path = M11, src: Path = SRC) -> Path:
    """make -f m11.mk part P=fxdisk into m11/fxdisk, sounds.s and
    sounds.cfg from src; fails on a warning."""
    tool(['make', '-s', '-C', str(NATIVE_SRC), '-f', 'm11.mk', 'part',
          'P=fxdisk', 'M11=%s' % m11, 'ROOT=%s' % ROOT,
          'FXDISK_SRC=%s' % src], 'make part P=fxdisk')
    return m11 / 'fxdisk'


class Program:
    """SOUNDS.SYSTEM, linked: its bytes, labels, segments."""

    def __init__(self, part: Path = PART):
        self.dir = Path(part)
        self.labels = run65.read_labels(self.dir / 'sounds.lbl')
        self.main = (self.dir / 'sounds.main').read_bytes()
        self.lc = (self.dir / 'sounds.lc').read_bytes()
        self.segments = run65.segments(self.dir / 'sounds.map')
        if len(self.main) != MAIN_SIZE or len(self.lc) != LC_SIZE:
            raise ValueError('sounds.main is $2000 bytes and sounds.lc $1700')
        self.system = self.main + self.lc
        if self.system[0x4078 - 0x2000:0x407C - 0x2000] == A2LI:
            raise ValueError('SOUNDS.SYSTEM holds the A2Li signature at $4078')


def place_problems(program: Program) -> List[str]:
    """The program's places against s2layout.py's (the game's): S2's code
    at $E900 below FX_CODE, the card part and pl_vbl in FX_CODE, S2's
    ring, lists and state where S2_CARD has them, the zero page."""
    from native import s2layout as S
    seg = program.segments
    card = {name: (lo, hi) for name, lo, hi in S.S2_CARD}
    out = []

    def within(name, lo, hi):
        if name not in seg:
            out.append('no segment %s' % name)
            return
        a, n = seg[name]
        if not (lo <= a and a + n <= hi):
            out.append('%s $%04X-$%04X outside $%04X-$%04X' % (
                name, a, a + n - 1, lo, hi - 1))
    code = card['S2\'s code and tables']
    if seg['SNDCODE'][0] != code[0]:
        out.append('S2\'s code at $%04X, not $%04X' % (seg['SNDCODE'][0],
                                                       code[0]))
    within('SNDCODE', *code)
    within('SNDRODATA', *code)
    within('FXCODE', *S.FX_CODE)
    within('SNDRING', *card['the song ring and its mirror'])
    within('SNDLIST', *card['the player\'s write lists'])
    within('SNDBSS', *card['the player\'s state'])
    within('SNDZP', S.ZP_MUSIC[0], S.ZP_FXRING[0])
    within('SDSZP', 0x0002, S.ZP_MUSIC[0])
    within('SDSCODE', 0x2000, 0x4000)
    within('S2CODE', 0x2000, 0x4000)
    lab = program.labels
    if lab.get('pl_vbl') != struct.unpack_from('<H', program.lc,
                                               0xFFFE - 0xE900)[0]:
        out.append('the IRQ vector is not pl_vbl')
    return out


def song_data() -> bytes:
    """D_E1M1's song file, converted from the WAD now."""
    wad = mus.Wad.open(mus.WAD_PATH)
    return mus2ay.convert(wad.song(SONG_NAME),
                          mus2ay.load_instruments(wad))[0].to_bytes()


class Disk(NamedTuple):
    program: Program
    sfx: bytes
    auto: bytes
    song: bytes
    files: List[Tuple[str, int, int, bytes]]     # PRODOS included


def disk_files(program: Program, sfx: bytes, auto: bytes, song: bytes):
    return [(SYSTEM, 0xFF, 0x2000, program.system),
            ('SFX.1', 0x06, SFX_AT, sfx),
            ('SFXAUTO.1', 0x06, SFX_AT, auto),
            ('E1M1.AY', 0x06, SONG_AT, song),
            ('PROFILE.TXT', 0x04, 0x0000, musicdisk.profile_bytes())]


def build_disk(files, output: Path):
    bd = musicdisk.disk_writer()
    bd.VOLUME_NAME = VOLUME         # (this copy of the module only)
    master = bd.DEFAULT_MASTER
    if not master.is_file():
        raise FileNotFoundError('%s is missing (appletini-one\'s ProDOS; '
                                'set APPLETINI_ROOT)' % master)
    boot, prodos = bd.extract_prodos(master)
    everything = [files[0], ('PRODOS', bd.FILE_TYPE_SYS, 0x0000, prodos)] + \
        list(files[1:])
    writer = bd.VolumeWriter(VOLUME, bd.volume_size([f[3] for f in
                                                     everything]))
    writer.set_boot_blocks(boot)
    for name, file_type, aux, data in everything:
        writer.add_file(name, data, file_type, aux)
    image = writer.finish()
    expected = {name: (t, aux, data) for name, t, aux, data in everything}
    bd.verify_image(image, expected, order=[f[0] for f in everything])
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(image)
    return everything


def build(output: Path = OUT, m11: Path = M11, src: Path = SRC,
          sfx_files: Optional[Tuple[bytes, bytes]] = None) -> Disk:
    sfx, auto = sfx_files or make_sfx()
    program = Program(make_program(m11, src))
    song = song_data()
    everything = build_disk(disk_files(program, sfx, auto, song), output)
    return Disk(program, sfx, auto, song, everything)


# ---------------------------------------------------------------------------
# a run on a2vm
# ---------------------------------------------------------------------------

class Write(NamedTuple):
    clock: int
    pc: int
    addr: int
    old: int
    new: int


def read_writes(path: Path) -> List[Write]:
    out = []
    with open(path) as log:
        for line in log:
            if line.startswith('w '):
                f = line.split()
                out.append(Write(int(f[1]), int(f[3], 16), int(f[4], 16),
                                 int(f[8], 16), int(f[9], 16)))
    return out


def read_image(path: Path) -> Dict[Tuple[int, int], Dict[int, bytes]]:
    """An A2VMIMG1 snapshot: {(kind, bank): {address: bytes}}."""
    data = path.read_bytes()
    if data[:8] != b'A2VMIMG1':
        raise ValueError('%s is not an A2VMIMG1 image' % path)
    out: Dict[Tuple[int, int], Dict[int, bytes]] = {}
    at = 8
    while at < len(data):
        kind, bank, address, n = struct.unpack_from('<BBHI', data, at)
        at += 8
        out.setdefault((kind, bank), {})[address] = data[at:at + n]
        at += n
    return out


def image_bytes(img, kind: int, bank: int, address: int, n: int) -> bytes:
    for base, chunk in img.get((kind, bank), {}).items():
        if base <= address and address + n <= base + len(chunk):
            return chunk[address - base:address - base + n]
    raise KeyError('no %d bytes at $%04X of (%d, %d)' % (n, address, kind,
                                                         bank))


MAIN_K, AUX_K, LC_K, LC1_K = 0, 1, 2, 3
SNAP_RANGES = 'main,lc,lc1,aux%d:%04X-%04X,aux%d:%04X-%04X' % (
    SFX_BANK, SFX_AT, SFX_END - 1, SONG_BANK, SONG_AT, 0x6FFF)


class Run:
    """One run of SOUNDS.SYSTEM: its end state, AY log groups, write log,
    final and named snapshots (range images)."""

    def __init__(self, directory: Path, labels: Dict[str, int],
                 names: Sequence[str]):
        self.directory = Path(directory)
        self.labels = labels
        self.state = json.loads((self.directory / 'state.json').read_text())
        self.events = run65.read_log(self.directory / 'ay.log')
        self.main, self.bursts, self.times, self.partial = \
            run65.group(self.events)
        self.writes = read_writes(self.directory / 'writes.log')
        self.final = read_image(self.directory / 'final.img')
        self.snaps = {n: read_image(self.directory / (n + '.img'))
                      for n in names
                      if (self.directory / (n + '.img')).exists()}
        self.ram = image_bytes(self.final, MAIN_K, 0, 0, 0x10000)

    def byte(self, label: str, offset: int = 0, img=None) -> int:
        a = self.labels[label] + offset
        img = self.final if img is None else img
        if a >= 0xE000:
            return image_bytes(img, LC_K, 0, a, 1)[0]
        return image_bytes(img, MAIN_K, 0, a, 1)[0]

    def screen(self, img=None) -> List[str]:
        img = self.final if img is None else img
        ram = image_bytes(img, MAIN_K, 0, 0x0400, 0x400)
        rows = []
        for r in range(24):
            at = (r % 8) * 0x80 + (r // 8) * 0x28
            rows.append(''.join(musicdisk.text_char(b)
                                for b in ram[at:at + 40]).rstrip())
        return rows


def run(disk: Disk, directory: Path, events=(), seconds=10.0, ntsc=False,
        mb_only=False, snapshots=(), variants=VARIANTS,
        timeout=TIMEOUT) -> Run:
    """Boot the disk's SOUNDS.SYSTEM on a2vm. `events`: (visit of
    sds_service, key) pairs; `snapshots`: (visit, name) pairs."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lab = disk.program.labels
    manifest = []
    for name, file_type, aux, data in disk.files:
        if name == 'PRODOS':
            continue
        path = directory / name
        path.write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
    (directory / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (directory / 'rom.bin').write_bytes(bytes(0x4000))
    lc2, lc1 = musicdisk.lc_pattern()
    image = bytearray(b'A2VMIMG1')
    image += struct.pack('<BBHI', 2, 0, 0xD000, len(lc2)) + lc2
    image += struct.pack('<BBHI', 3, 0, 0xD000, len(lc1)) + lc1
    (directory / 'card.img').write_bytes(bytes(image))
    service = lab['sds_service']
    lines = ['pc %X@%d key %s' % (service, v, KEY_CODES.get(k, k))
             for v, k in sorted(events, key=lambda e: e[0])]
    lines += ['pc %X@%d snapshot %s' % (service, v, n) for v, n in snapshots]
    (directory / 'events.txt').write_text('\n'.join(lines) + '\n')
    name = run65.cost_profile(ntsc, variants)
    (directory / 'cost.txt').write_text(costs.text(name))
    fabric_hz = costs.parameters(name)['fabric_mhz'] * 1e6
    from native import s2layout as S
    ranges = ','.join([
        'lc:%04X-%04X' % (S.FXV_BASE, S.FXV_END - 1),
        'lc:%04X-%04X' % (S.FX['FX_ON'], S.FX_RING - 1),
        'lc:%04X-%04X' % (S.FX_RING, S.FX_RING_END - 1),
        'lc:%04X' % lab['snd_playing'], 'main:%04X' % lab['sds_mark']])
    args = [str(A2VM), '--rom', str(directory / 'rom.bin'),
            '--core', 'w65c02s', '--via-ora-nh',
            '--image', str(directory / 'card.img'),
            '--prodos', str(directory / 'prodos.txt'),
            '--volume', VOLUME, '--launched', SYSTEM,
            '--load', '2000:%s' % (directory / SYSTEM),
            '--reg', 'pc=2000', '--reg', 's=FF',
            '--cost', str(directory / 'cost.txt'), '--cost-timed',
            '--cycles', str(int(round(seconds * fabric_hz))),
            '--ay-log', str(directory / 'ay.log'),
            '--state', str(directory / 'state.json'),
            '--irq-bounds', IRQ_BOUNDS,
            '--idle', '%X:vbl:eq=%X,%X' % (lab['sds_idle'],
                                           lab['vbl_count'], lab['seen']),
            '--stop-pc', '%X' % lab['pl_crash'],
            '--input', str(directory / 'events.txt'),
            '--write-log', ranges,
            '--write-log-file', str(directory / 'writes.log'),
            '--write-log-limit', str(WRITE_LOG_LIMIT),
            '--snapshot-ranges', SNAP_RANGES,
            '--snapshot-dir', str(directory), '--final-snapshot']
    if mb_only:
        args.append('--phasor-mb-only')
    try:
        result = bounded.run(args, timeout=timeout, max_bytes=MAX_BYTES,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise CheckFailed('a2vm did not finish in %d s' % timeout)
    state_path = directory / 'state.json'
    if result.returncode or not state_path.exists():
        halt = ''
        if state_path.exists():
            halt = json.loads(state_path.read_text()).get('halt', '')
        raise CheckFailed('a2vm failed (%d): %s\n%s' % (
            result.returncode, halt, result.stdout[-2000:]))
    return Run(directory, lab, [n for _, n in snapshots])


# ---------------------------------------------------------------------------
# the model of the keys (tools/sound/README.md, "The test disk")
# ---------------------------------------------------------------------------

class Step(NamedTuple):
    visit: int
    kind: int
    args: Tuple[Any, ...] = ()


class UiModel:
    """What SOUNDS.SYSTEM must do for each key, from the README's key
    table and sounds.s's header: the steps (Step) in order, each in its
    visit; the screen's state."""

    def __init__(self, tuned: Sequence[bool], native: bool, ntsc: bool):
        self.tuned = list(tuned)
        self.native = native
        self.ntsc = ntsc
        self.cur = 0
        self.dist = 0
        self.rep = False
        self.rcount = 0
        self.lastkey: Optional[str] = None
        self.lastch: Optional[int] = None
        self.songon = False
        self.ver = [0 if t else 1 for t in tuned]
        self.steps: List[Step] = []
        self.quit: Optional[int] = None
        self.plays: List[Tuple[int, str, int]] = []   # (visit, key, sound)

    @property
    def rate(self) -> int:
        return 60 if self.ntsc else 50

    def visit(self, v: int, key: Optional[str]) -> None:
        if self.quit is not None:
            return
        if self.rep and self.lastkey:
            self.rcount += 1
            if self.rcount >= self.rate:
                self.play(v, self.lastkey)
        if key is not None:
            self.key(v, key)

    def add(self, v, kind, *args):
        self.steps.append(Step(v, kind, tuple(args)))

    def play(self, v: int, key: str) -> None:
        self.lastkey = key
        self.rcount = 0
        s, vol = self.cur + 1, VOLS[self.dist]
        self.plays.append((v, key, s))
        self.add(v, STOPALL)
        if key == 'C':          # A taken by channel 0 so that C is chosen
            self.add(v, START, 0, s, vol, SEP['C'])
            self.add(v, START, 1, s, vol, SEP['C'])
            self.add(v, SERVICE)
            self.add(v, STOP, 0)
            self.add(v, SERVICE)
            self.lastch = 1
        else:
            self.add(v, START, 0, s, vol, SEP[key])
            self.lastch = 0

    def key(self, v: int, k: str) -> None:
        if k in ('Q', 'q', 'esc'):
            self.quit = v
            self.add(v, QUIT)
        elif k == 'up':
            self.cur = (self.cur - 1) % NSFX
        elif k == 'down':
            self.cur = (self.cur + 1) % NSFX
        elif k == 'left':
            if self.cur >= COLROWS:
                self.cur -= COLROWS
        elif k == 'right':
            if self.cur + COLROWS < NSFX:
                self.cur += COLROWS
        elif k in SEP:
            self.play(v, k)
        elif k in ('1', '2', '3'):
            self.dist = int(k) - 1
            if self.lastch is not None:
                self.add(v, VOLUME_, self.lastch, VOLS[self.dist])
        elif k == 'T':
            if self.tuned[self.cur]:
                self.ver[self.cur] ^= 1
                self.add(v, TOGGLE, self.cur + 1, self.ver[self.cur])
        elif k == 'R':
            self.rep = not self.rep
            self.rcount = 0
        elif k == 'M':
            if self.native:
                if self.songon:
                    self.add(v, SONGSTOP)
                    self.songon = False
                else:
                    self.add(v, SONG, self.ntsc)
                    self.songon = True
        elif k == 'S':
            self.add(v, STOPALL)
            self.rep = False
        elif k == 'V':
            self.ntsc = not self.ntsc
            self.add(v, STD, self.ntsc)
            if self.songon:
                self.add(v, SONG, self.ntsc)
        else:
            raise ValueError('no key %r' % k)


def model_steps(events, visits: int, tuned, native, ntsc) -> UiModel:
    keys: Dict[int, str] = {}
    for v, k in events:
        if v in keys:
            raise ValueError('two keys at visit %d' % v)
        keys[v] = k
    ui = UiModel(tuned, native, ntsc)
    for v in range(1, visits + 1):      # (the last: the one that ran no frame)
        ui.visit(v, keys.get(v))
    return ui


# ---------------------------------------------------------------------------
# the oracle
# ---------------------------------------------------------------------------

class Event(NamedTuple):
    value: int
    start: int
    end: int


def mark_events(res: Run) -> List[Event]:
    """sds_mark's steps: each store of a non-zero value starts one (and
    ends the one before), a store of 0 ends it."""
    mark = res.labels['sds_mark']
    out, cur = [], None
    for w in res.writes:
        if w.addr != mark:
            continue
        if cur is not None:
            out.append(Event(cur[0], cur[1], w.clock))
            cur = None
        if w.new:
            cur = (w.new, w.clock)
    if cur is not None:
        out.append(Event(cur[0], cur[1], 1 << 62))
    return out


class MutBank(fxplay.Bank):
    """The model's bank: SFX.1 at $0200, SFXAUTO.1 AUTO_OFF higher; T
    switches a tuned effect's directory entry."""

    def __init__(self, sfx: bytes, auto: bytes):
        data = bytearray(sfx)
        data += bytes(AUTO_OFF - len(data))
        data += auto
        self.data = data
        self.sfx, self.auto = sfx, auto

    def switch(self, sound: int, to_auto: int) -> None:
        if to_auto:
            a, n = entry(self.auto, sound)
            a += AUTO_OFF
        else:
            a, n = entry(self.sfx, sound)
        struct.pack_into('<HH', self.data, 4 * (sound - 1), a, n)


class Expect(NamedTuple):
    gaps: List[List[Any]]
    bursts: List[List[Any]]
    inside: bool
    problems: List[str]
    fx: fxplay.FxPlayer
    quit: Optional[int]             # the quit's clock


def expect(disk: Disk, res: Run, ui: UiModel, mb_only: bool,
           ntsc: bool) -> Expect:
    native = not mb_only
    bank = MutBank(disk.sfx, disk.auto)
    fx = fxplay.FxPlayer(bank, ntsc=ntsc)
    fx.init(fxplay.SND_MUSIC if native else fxplay.SND_NO_MUSIC)
    problems: List[str] = []
    gaps: List[List[Any]] = [list(run65.init_events(True, mb_only))]
    bursts: List[List[Any]] = []
    events = mark_events(res)
    frames = [e for e in events if e.value == FRAME]
    steps = [e for e in events if e.value not in (FRAME, REFILL)]
    if len(steps) != len(ui.steps):
        problems.append('%d steps ran, the keys make %d: %s, the model %s' % (
            len(steps), len(ui.steps),
            [KIND_NAMES.get(e.value, e.value) for e in steps[:12]],
            [KIND_NAMES[s.kind] for s in ui.steps[:12]]))
    starts = [f.start for f in frames]
    from native import s2layout as S
    hold_at = S.FX['FX_HOLD']
    play_at = res.labels['snd_playing']
    points: List[Tuple[int, int, str, Any]] = []
    for k, (entry_clock, _) in enumerate(res.times, 1):
        points.append((entry_clock, 1, 'irq', k))
    for f in frames:
        points.append((f.start, 0, 'frame', None))
    inside = False
    for e, step in zip(steps, ui.steps):
        if e.value != step.kind:
            problems.append('visit %d: the step %s ran as %s' % (
                step.visit, KIND_NAMES[step.kind],
                KIND_NAMES.get(e.value, e.value)))
            break
        visit = sum(1 for s in starts if s < e.start) + 1
        if visit != step.visit:
            problems.append('the step %s of visit %d ran in visit %d' % (
                KIND_NAMES[step.kind], step.visit, visit))
            break
        n_in = [k for k, (c, _) in enumerate(res.times, 1)
                if e.start < c < e.end]
        if step.kind == SONG and native:
            within = [w for w in res.writes if e.start <= w.clock <= e.end]
            seq = [(w.clock, 'hold' if w.new else 'release')
                   for w in within if w.addr == hold_at] + \
                  [(w.clock, 'on' if w.new else 'off')
                   for w in within if w.addr == play_at]
            if sorted(x[1] for x in seq) != ['hold', 'off', 'on', 'release']:
                problems.append('a song start without its four steps: %s'
                                % seq)
            for clock, what in seq:
                points.append((clock, 0, 'song-' + what, step))
            inside = inside or bool(n_in)
        else:
            points.append((e.start, 0, 'step', step))
            if n_in:
                problems.append('interrupt %d inside the step %s' % (
                    n_in[0], KIND_NAMES[step.kind]))
    for f in frames:
        n_in = [k for k, (c, _) in enumerate(res.times, 1)
                if f.start < c < f.end]
        if n_in:
            problems.append('interrupt %d inside a frame\'s service' %
                            n_in[0])
            break
    points.sort(key=lambda p: (p[0], p[1]))
    state: Dict[str, Any] = {'cur': None, 'new': None}
    song_file = player.SongFile.from_bytes(disk.song)

    for clock, _, what, arg in points:
        if what == 'irq':
            cur = state['cur']
            mus_w = cur.interrupt() if cur is not None else []
            bursts.append(list(mus_w) + list(fx.step()))
            gaps.append([])
        elif what == 'frame':
            fx.service()
            cur = state['cur']
            if native and cur is not None and cur.playing:
                cur.refill()
        elif what == 'step':
            k, a = arg.kind, arg.args
            if k == STOPALL:
                fx.stopall()
            elif k == START:
                fx.mail_start(*a)
            elif k == STOP:
                fx.mail_stop(a[0])
            elif k == VOLUME_:
                fx.mail_volume(*a)
            elif k == SERVICE:
                fx.service()
            elif k == TOGGLE:
                bank.switch(*a)
            elif k == STD:
                fx.ntsc = bool(a[0])
            elif k == SONGSTOP:
                if state['cur'] is not None:
                    state['cur'].stop()
            elif k == QUIT:     # snd_init's resets, then no interrupt
                gaps[-1].extend(run65.INIT_RESETS)
                state['quit'] = clock
        elif what == 'song-hold':
            fx.song_begin()
        elif what == 'song-off':
            state['cur'] = None
            p = run65.RingPlayer(song_file, run65.machine_of(bool(arg.args[0])),
                                 loop=True, music_attenuation=0)
            gaps[-1].extend(p.start())
            state['new'] = p
        elif what == 'song-on':
            state['cur'] = state['new']
        elif what == 'song-release':
            fx.song_end()
    return Expect(gaps, bursts, inside, problems, fx, state.get('quit'))


class _Pub(NamedTuple):
    times: List[Tuple[int, int]]
    writes: List[Write]
    ram: bytes


def compare(res: Run, ex: Expect, mb_only: bool) -> List[str]:
    from sound import fxrun65
    out = list(ex.problems)
    if len(res.bursts) != len(ex.bursts):
        out.append('%d interrupts, the model %d' % (len(res.bursts),
                                                    len(ex.bursts)))
    for k, (got, want) in enumerate(zip(res.bursts, ex.bursts), 1):
        chips = [w[0] for w in got if w[0] != 'reset']
        if 3 in chips and any(c != 3 for c in chips[chips.index(3):]):
            out.append('interrupt %d: a write of chip 0-2 after chip 3\'s' %
                       k)
            break
        if got != want:
            which = 'chips 0-2' if [w for w in got if w[0] != 3] != \
                [w for w in want if w[0] != 3] else 'chip 3'
            out.append('interrupt %d (%s): %s' % (
                k, which, run65.first_difference(got, want)))
            break
    if ex.inside:
        flat = [w for g in res.main for w in g]
        want = [w for g in ex.gaps for w in g]
        if flat != want:
            out.append('the main loop\'s writes: %s' %
                       run65.first_difference(flat, want))
    else:
        if len(res.main) != len(ex.gaps):
            out.append('%d main-loop groups, the model %d' % (
                len(res.main), len(ex.gaps)))
        for k, (got, want) in enumerate(zip(res.main, ex.gaps)):
            if got != want:
                out.append('main loop after interrupt %d: %s' % (
                    k, run65.first_difference(got, want)))
                break
    regs = [[0] * 16 for _ in range(4)]
    for g in [ex.gaps[0]] + [w for k, b in enumerate(ex.bursts)
                             for w in (b, ex.gaps[k + 1]
                                       if k + 1 < len(ex.gaps) else [])]:
        for w in g:
            if w[0] == 'reset':
                regs[w[1]] = [0] * 16
            else:
                regs[w[0]][w[1]] = w[2]
    for w in res.partial or []:
        if w[0] == 'reset':
            regs[w[1]] = [0] * 16
        else:
            regs[w[0]][w[1]] = w[2]
    if not mb_only:
        for chip in range(4):
            if res.state['phasor']['ay'][chip] != regs[chip]:
                out.append('at the end chip %d holds %s, the model %s' % (
                    chip, res.state['phasor']['ay'][chip], regs[chip]))
    # the publish order up to the quit (whose restore of ProDOS's card
    # rewrites the card's state)
    end = ex.quit if ex.quit is not None else 1 << 62
    out += fxrun65.publish_problems(_Pub(
        res.times, [w for w in res.writes if w.clock < end], res.ram))
    return out


# ---------------------------------------------------------------------------
# the checks
# ---------------------------------------------------------------------------

class Keys:
    """Key events, one a visit."""

    def __init__(self, first: int = 3):
        self.events: List[Tuple[int, str]] = []
        self.v = first

    def key(self, k: str, gap: int = 1) -> int:
        at = self.v
        self.events.append((at, k))
        self.v += gap
        return at

    def wait(self, n: int) -> None:
        self.v += n


def lengths(bank_file: bytes, ntsc: bool = False) -> List[int]:
    from sound import fxrun65
    return [fxrun65.effect_length(bank_file, s, ntsc)
            for s in range(1, NSFX + 1)]


def vbl_hz(ntsc: bool) -> float:
    return musicdisk.vbl_rate(ntsc)


def checked(disk: Disk, work: Path, tag: str, keys: Keys, ntsc=False,
            mb_only=False, snapshots=(), tail: int = 40,
            extra_seconds: float = 0.0):
    """Run, model, compare. Returns (problems, run, model)."""
    seconds = (keys.v + tail) / vbl_hz(ntsc) + 0.6 + extra_seconds
    res = run(disk, work / tag, keys.events, seconds, ntsc=ntsc,
              mb_only=mb_only, snapshots=snapshots)
    nframes = sum(1 for e in mark_events(res) if e.value == FRAME)
    ui = model_steps(keys.events, nframes + 1, tuned_of(disk.sfx),
                     not mb_only, ntsc)
    ex = expect(disk, res, ui, mb_only, ntsc)
    return compare(res, ex, mb_only), res, ui


def boot_problems(disk: Disk, res: Run) -> List[str]:
    """The bank SFX and the songs' bank after the boot; the boot's
    screen (the snapshot 'boot')."""
    out = []
    bank = image_bytes(res.final, AUX_K, SFX_BANK, SFX_AT, SFX_END - SFX_AT)
    tuned = tuned_of(disk.sfx)
    # the directory entries as they stand at the end (no T in this run)
    if bank[:len(disk.sfx)] != disk.sfx:
        out.append('bank %d does not hold SFX.1 at $%04X' % (SFX_BANK,
                                                               SFX_AT))
    at = SFX_AT + len(disk.sfx)
    for s in range(1, NSFX + 1):
        if not tuned[s - 1]:
            continue
        script = script_of(disk.auto, s)
        got = bank[at - SFX_AT:at - SFX_AT + len(script)]
        if got != script:
            out.append('%s\'s automatic script is not at $%04X of bank %d' % (
                fxconv.NAMES[s - 1], at, SFX_BANK))
            break
        at += len(script)
    nxt = res.byte('sds_next') | res.byte('sds_next', 1) << 8
    if nxt != at:
        out.append('the bank\'s next free byte $%04X, expected $%04X' % (
            nxt, at))
    song = image_bytes(res.final, AUX_K, SONG_BANK, SONG_AT, len(disk.song))
    if song != disk.song:
        out.append('E1M1.AY is not in bank %d at $%04X' % (SONG_BANK,
                                                            SONG_AT))
    if 'boot' in res.snaps:
        scr = res.screen(res.snaps['boot'])
        want = [TITLE, machine_row(False, True, False, False)] + \
            list_rows(0, tuned, [0 if t else 1 for t in tuned]) + \
            [effect_row(0, 'TUNED' if tuned[0] else 'AUTO',
                        script_sum(script_of(disk.sfx, 1)), 0, None)] + \
            KEY_ROWS
        for r, (g, w) in enumerate(zip(scr, want)):
            if g != w:
                out.append('the boot\'s row %d: %r, expected %r' % (r, g, w))
                break
    return out


def check_play(disk: Disk, work: Path, tag: str, keys_of, ntsc=False):
    """Every effect, each by the key keys_of(e), the distances in turn."""
    lens = lengths(disk.sfx, ntsc)
    # the voice each key's play must get (A left, B right, C centre:
    # RETURN's separation 128 is the centre's), its name on the screen
    voices = {'return': 2, 'A': 0, 'B': 1, 'C': 2}
    keys = Keys()
    snaps = [(2, 'boot')] if tag == 'left' else []
    for e in range(NSFX):
        if e:
            keys.key('down')
        keys.key('123'[e % 3])
        v = keys.key(keys_of(e), gap=lens[e] + 4)
        if e < 3:
            snaps.append((v + 1, 'play%d' % e))
    problems, res, ui = checked(disk, work, tag, keys, ntsc=ntsc,
                                snapshots=snaps)
    if tag == 'left':
        problems += boot_problems(disk, res)
    tuned = tuned_of(disk.sfx)
    for e in range(3):
        name = 'play%d' % e
        if name not in res.snaps:
            problems.append('no snapshot %s' % name)
            continue
        want = effect_row(e, 'TUNED' if tuned[e] else 'AUTO',
                          script_sum(script_of(disk.sfx, e + 1)), e % 3,
                          VOICE_TEXT[voices[keys_of(e)]])
        got = res.screen(res.snaps[name])[20]
        if got != want:
            problems.append('%s: the effect line %r, expected %r' % (
                name, got, want))
    used = sorted({voices[k] for _, k, _ in ui.plays})
    return problems, '%d plays (%d effects; voices %s), %d interrupts, %d ' \
        'chip-3 writes' % (len(ui.plays), len({s for _, _, s in ui.plays}),
                           ''.join('ABC'[v] for v in used), len(res.bursts),
                           sum(1 for b in res.bursts for w in b
                               if w[0] == 3))


def check_tuned(disk: Disk, work: Path):
    tuned = tuned_of(disk.sfx)
    sounds = [s for s in range(1, NSFX + 1) if tuned[s - 1]]
    tl, al = lengths(disk.sfx), lengths(disk.auto)
    keys = Keys()
    cur = 0
    snaps, wants = [], []
    ver = [0 if t else 1 for t in tuned]
    for n, s in enumerate(sounds):
        while cur < s - 1:
            keys.key('down')
            cur += 1
        keys.key('2' if n % 2 else '1')
        dist = 1 if n % 2 else 0
        v = keys.key('A', gap=tl[s - 1] + 4)
        if n < 3:
            snaps.append((v + 1, 'tuned%d' % n))
            wants.append(('tuned%d' % n, cur, 'TUNED',
                          script_sum(script_of(disk.sfx, s)), dist, 0,
                          list(ver)))
        keys.key('T')
        ver[s - 1] = 1
        v = keys.key('B', gap=al[s - 1] + 4)
        if n < 3:
            snaps.append((v + 1, 'auto%d' % n))
            wants.append(('auto%d' % n, cur, 'AUTO',
                          script_sum(script_of(disk.auto, s)), dist, 1,
                          list(ver)))
        keys.key('T')
        ver[s - 1] = 0
    problems, res, ui = checked(disk, work, 'tuned', keys, snapshots=snaps)
    for name, cur, version, total, dist, voice, v in wants:
        if name not in res.snaps:
            problems.append('no snapshot %s' % name)
            continue
        scr = res.screen(res.snaps[name])
        want = effect_row(cur, version, total, dist, VOICE_TEXT[voice])
        if scr[20] != want:
            problems.append('%s: the effect line %r, expected %r' % (
                name, scr[20], want))
        rows = list_rows(cur, tuned, v)
        if scr[2:20] != rows:
            problems.append('%s: the list %r, expected %r' % (
                name, scr[2:20], rows))
    toggles = sum(1 for s in ui.steps if s.kind == TOGGLE)
    return problems, '%d tuned effects, tuned then automatic: %d T, %d ' \
        'plays, %d interrupts' % (len(sounds), toggles, len(ui.plays),
                                  len(res.bursts))


def check_music(disk: Disk, work: Path):
    """Every effect over D_E1M1 (each for half its length, the next one
    cutting it), RETURN, A, B, C in turn; V half way (the song again on
    the NTSC tables, the effects' tempo NTSC); M again: silence."""
    lens = lengths(disk.sfx)
    keys = Keys()
    on = keys.key('M', gap=20)
    play_keys = ('return', 'A', 'B', 'C')
    snaps = [(on + 1, 'music')]
    for e in range(NSFX):
        if e:
            keys.key('down')
        keys.key(play_keys[e % 4], gap=lens[e] // 2 + 3)
        if e == NSFX // 2:
            v = keys.key('V', gap=10)   # NTSC tables: the song again
            snaps.append((v + 1, 'ntsc'))
    off = keys.key('M', gap=30)         # silence
    snaps.append((off + 1, 'silence'))
    keys.key('up')
    keys.key('B', gap=lens[NSFX - 2] + 4)
    problems, res, ui = checked(disk, work, 'music', keys, snapshots=snaps)
    for name, ntsc, songon in (('music', False, True), ('ntsc', True, True),
                               ('silence', True, False)):
        want = machine_row(ntsc, True, songon, False)
        got = res.screen(res.snaps[name])[1] if name in res.snaps else None
        if got != want:
            problems.append('%s: the second row %r, expected %r' % (
                name, got, want))
    songs = sum(1 for s in ui.steps if s.kind == SONG)
    music = sum(1 for b in res.bursts for w in b if w[0] != 3)
    return problems, '%d plays over D_E1M1 (%d song starts, V at the %dth), ' \
        '%d interrupts: %d music writes, %d chip-3 writes' % (
            len(ui.plays), songs, NSFX // 2 + 1, len(res.bursts), music,
            sum(1 for b in res.bursts for w in b if w[0] == 3))


def require_quit(res: Run) -> List[str]:
    """MUSIC.SYSTEM's quit: ProDOS's QUIT, snd_init's resets the last AY
    events, the chips reset, the card's former contents back, the Phasor
    in Mockingboard mode."""
    out = []
    if res.state['end'] != 'quit':
        return ['the run did not quit: %s' % res.state['end']]
    if res.state['prodos']['quit'] != 1:
        out.append('no ProDOS QUIT')
    if not res.main or res.main[-1][-4:] != list(run65.INIT_RESETS):
        out.append('the quit wrote %s' % (res.main[-1][-6:] if res.main
                                          else None))
    lc2, lc1 = musicdisk.lc_pattern()
    if image_bytes(res.final, LC_K, 0, 0xD000, 0x3000) != lc2 or \
            image_bytes(res.final, LC1_K, 0, 0xD000, 0x1000) != lc1:
        out.append('the card after the quit is not what ProDOS had')
    if any(v for chip in res.state['phasor']['ay'] for v in chip):
        out.append('the chips are not reset after the quit')
    if res.state['phasor']['mode'] != run65.MOCKINGBOARD_MODE:
        out.append('the quit left the Phasor in mode %s' %
                   res.state['phasor']['mode'])
    return out


def check_ntsc(disk: Disk, work: Path):
    lens = lengths(disk.sfx, True)
    keys = Keys()
    for _ in range(14):         # DORCLS (15): long
        keys.key('down')
    keys.key('A', gap=8)
    keys.key('2', gap=8)        # its volume, while it plays
    keys.key('3', gap=8)
    keys.key('1', gap=lens[14])
    keys.key('right', gap=2)    # BGSIT1 (33)
    keys.key('C', gap=3)
    r = keys.key('R', gap=60 * 3 + 7)   # three repeats and a part
    s = keys.key('S', gap=lens[32] + 4)
    keys.key('left')
    keys.key('up')
    keys.key('B', gap=lens[13] + 4)
    keys.key('esc', gap=10)
    problems, res, ui = checked(disk, work, 'ntsc', keys, ntsc=True,
                                snapshots=[(r + 1, 'repeat'), (s + 1, 'stop')])
    problems += require_quit(res)
    for name, rep in (('repeat', True), ('stop', False)):
        want = machine_row(True, True, False, rep)
        got = res.screen(res.snaps[name])[1] if name in res.snaps else None
        if got != want:
            problems.append('%s: the second row %r, expected %r' % (
                name, got, want))
    reps = sum(1 for v, k, s in ui.plays if k == 'C') - 1
    return problems, 'NTSC: %d volume mails, %d repeats, S, then ESC: %d ' \
        'interrupts, %s' % (sum(1 for s in ui.steps if s.kind == VOLUME_),
                            reps, len(res.bursts), res.state['end'])


def check_quit(disk: Disk, work: Path):
    keys = Keys()
    keys.key('M', gap=5)
    keys.key('return', gap=10)
    keys.key('q', gap=10)
    problems, res, _ = checked(disk, work, 'quit', keys)
    problems += require_quit(res)
    return problems, 'q while D_E1M1 and PISTOL play: %d interrupts, then ' \
        'the quit' % len(res.bursts)


def check_nonative(disk: Disk, work: Path):
    keys = Keys()
    for k in ('return', 'A', 'B', 'C', '2', 'T', 'R', 'M', 'down', 'C',
              'V', '3', 'S', 'B'):
        keys.key(k, gap=12)
    keys.key('Q', gap=10)
    snaps = [(keys.events[3][0] + 1, 'mid')]
    problems, res, ui = checked(disk, work, 'nonative', keys, mb_only=True,
                                snapshots=snaps)
    problems += require_quit(res)
    seen = [e[1:4] if e[0] == 'w' else e for e in res.events
            if e[0] in ('w', 'reset')]
    want = list(run65.init_events(True, True)) + list(run65.INIT_RESETS)
    if seen != want:
        problems.append('AY events %s, expected %s' % (seen[:12], want))
    calls = res.state['prodos']['calls']
    if calls != 7:      # OPEN, READ, CLOSE of SFX.1 and SFXAUTO.1, QUIT
        problems.append('%d MLI calls, expected 7 (no song file)' % calls)
    if 'mid' in res.snaps:
        scr = res.screen(res.snaps['mid'])
        if scr[1] != machine_row(False, False, False, False):
            problems.append('the second row %r' % scr[1])
        want = effect_row(0, 'TUNED', script_sum(script_of(disk.sfx, 1)), 0,
                          VOICE_TEXT[None])
        if scr[20] != want:
            problems.append('the effect line %r, expected %r' % (scr[20],
                                                                 want))
    else:
        problems.append('no snapshot mid')
    return problems, '%d keys, %d steps: no AY write but the probe\'s and ' \
        'snd_init\'s; %d MLI calls; %s' % (
            len(keys.events), len(ui.steps), calls,
            res.screen(res.snaps['mid'])[1] if 'mid' in res.snaps else '')


CHECKS = ('left', 'right', 'tuned', 'music', 'ntsc', 'quit', 'nonative')


def one_check(name: str, disk: Disk, work: Path):
    if name == 'left':
        return check_play(disk, work, 'left',
                          lambda e: ('return', 'A', 'C')[e % 3])
    if name == 'right':
        return check_play(disk, work, 'right', lambda e: 'B')
    return {'tuned': check_tuned, 'music': check_music, 'ntsc': check_ntsc,
            'quit': check_quit, 'nonative': check_nonative}[name](disk, work)


def tmpdir(tag: str) -> Path:
    BUILD.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='tmp-fxdisk-%s-' % tag,
                                 dir=str(BUILD)))


def check_all(disk: Disk, jobs: int = JOBS, names: Sequence[str] = CHECKS,
              out=print) -> List[str]:
    work = tmpdir('check')
    problems: List[str] = []

    def one(name):
        try:
            return name, one_check(name, disk, work)
        except (CheckFailed, RuntimeError, KeyError, ValueError) as e:
            return name, (['%s: %s' % (type(e).__name__, e)], '')
        finally:
            shutil.rmtree(str(work / name), ignore_errors=True)
    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(one, names))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    pp = place_problems(disk.program)
    out('%-9s %s' % ('places', 'ok' if not pp else pp[0]))
    problems += ['places: %s' % p for p in pp]
    for name, (p, note) in results:
        out('%-9s %s%s' % (name, 'ok' if not p else 'FAIL ' + p[0],
                           ('  (%s)' % note) if note else ''))
        problems += ['%s: %s' % (name, x) for x in p]
    return problems


def sizes(program: Program) -> Dict[str, int]:
    seg = program.segments
    text = (program.dir / 'sounds.map').read_text()
    mods = text.split('Modules list:', 1)[1].split('Segment list:', 1)[0]
    own, module = {}, None
    for line in mods.splitlines():
        if line and not line.startswith(' '):
            module = Path(line.strip().rstrip(':')).stem
            continue
        f = line.split()
        if module == 'sounds' and f and f[0].startswith('SDS') and \
                f[0] != 'SDSZP':
            own[f[0]] = int(next(x for x in f if x.startswith('Size='))[5:],
                            16)
    return {'SDSCODE': own.get('SDSCODE', 0), 'SDSDATA': own.get('SDSDATA', 0),
            'SDSBSS': own.get('SDSBSS', 0),
            'main_end': max(a + n for k, (a, n) in seg.items()
                            if 0x2000 <= a < 0x4000),
            'FXCODE': seg['FXCODE'][1]}


# ---------------------------------------------------------------------------
# the planted bugs
# ---------------------------------------------------------------------------

# (name, the text in sounds.s, its replacement, the checks that must fail)
PLANTED = (
    ('a key playing the next effect',
     '        lda     sds_cur\n        inc     a\n        sta     snd\n',
     '        lda     sds_cur\n        inc     a\n        inc     a\n'
     '        sta     snd\n', ('left',)),
    ('the side keys swapped',
     'sep_of: .byte   SEP_AHEAD, SEP_LEFT, SEP_RIGHT',
     'sep_of: .byte   SEP_AHEAD, SEP_RIGHT, SEP_LEFT', ('right',)),
    ('the tuned version not loaded',
     '        lda     #<p_sfx\n        ldx     #>p_sfx\n',
     '        lda     #<p_auto\n        ldx     #>p_auto\n', ('tuned', 'left')),
    ('effects played without native mode',
     '        pla\n        jsr     fx_init',
     '        pla\n        lda     #SND_MUSIC\n        jsr     fx_init',
     ('nonative',)),
)


def planted(disk: Disk, jobs: int = JOBS, out=print) -> List[str]:
    """Each planted bug in a scratch copy of sounds.s, built apart, must
    fail its checks. Returns the bugs not caught."""
    text = (SRC / 'sounds.s').read_text()

    def one(bug):
        name, old, new, checks = bug
        root = tmpdir('planted')
        try:
            if text.count(old) != 1:
                return name, ['(its text is not in sounds.s once)'], False
            src = root / 'src'
            src.mkdir()
            (src / 'sounds.s').write_text(text.replace(old, new))
            shutil.copy(str(SRC / 'sounds.cfg'), str(src / 'sounds.cfg'))
            bad = build(root / 'SOUNDS.hdv', root / 'm11', src,
                        (disk.sfx, disk.auto))
            caught = []
            for c in checks:
                try:
                    p, _ = one_check(c, bad, root / 'runs')
                except (CheckFailed, RuntimeError) as e:
                    p = ['%s' % str(e).splitlines()[0]]
                if p:
                    caught.append('%s: %s' % (c, p[0]))
            return name, caught, True
        except (CheckFailed, RuntimeError) as e:
            return name, ['(the build) %s' % str(e).splitlines()[0]], False
        finally:
            shutil.rmtree(str(root), ignore_errors=True)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        done = list(pool.map(one, PLANTED))
    missed = []
    for name, caught, built in done:
        if caught and built:
            for k, c in enumerate(caught):
                out('%-38s %s' % (name if not k else '', c[:160]))
        else:
            out('%-38s NOT CAUGHT%s' % (name, ' ' + caught[0] if caught
                                        else ''))
        if not caught or not built:
            missed.append(name)
    return missed


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--inc', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--planted', action='store_true')
    parser.add_argument('--only', nargs='*', choices=CHECKS)
    parser.add_argument('--jobs', type=int, default=JOBS)
    args = parser.parse_args(argv)
    if args.inc:
        args.inc.parent.mkdir(parents=True, exist_ok=True)
        text = names_inc()
        if not args.inc.exists() or args.inc.read_text() != text:
            args.inc.write_text(text)
        return 0
    if not have_tools():
        print('needs cc65, make, the WAD (tools/fetch_upstream.py), '
              'appletini-one\'s ProDOS and S2\'s player (make -C src/sound)',
              file=sys.stderr)
        return 2
    disk = build(args.out)
    size = args.out.stat().st_size
    print('%s: %d bytes (%d blocks), volume %s' % (args.out, size,
                                                   size // 512, VOLUME))
    for name, file_type, aux, data in disk.files:
        print('  %-13s type $%02X aux $%04X %6d bytes' % (
            name, file_type, aux, len(data)))
    z = sizes(disk.program)
    print('  SOUNDS.SYSTEM: code %d B, data %d B (main $2000-$%04X of '
          '$3FFF); FXCODE %d B' % (z['SDSCODE'], z['SDSDATA'],
                                    z['main_end'] - 1, z['FXCODE']))
    bad = 0
    if args.check or args.planted:
        if not A2VM.exists():
            print('no %s: make -C tools/a2vm' % A2VM, file=sys.stderr)
            return 2
    if args.check:
        bad += len(check_all(disk, args.jobs, args.only or CHECKS))
    if args.planted:
        bad += len(planted(disk, args.jobs))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
