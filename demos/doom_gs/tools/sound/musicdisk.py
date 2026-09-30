#!/usr/bin/env python3
"""The music disk of milestone S3 (build/sound/MUSIC.hdv), its checks on a2vm.

Usage:
  python3 tools/sound/musicdisk.py [--out FILE]
      Build the disk.
  nice -n 10 python3 tools/sound/musicdisk.py --check [--jobs N]
          [--seconds S] [--keep DIR]
      Build it, then run the disk's own MUSIC.SYSTEM on a2vm (below).

The disk, a ProDOS volume MUSIC made with the existing port's disk writer
(demos/doom/tools/build_disk.py: the boot blocks and PRODOS of
appletini-one's ProDOS_2_4_3.po, as tools/native/disk.py makes the
replay's), holds:

  MUSIC.SYSTEM   src/sound/music.s and aytime.s with the S2 player
                 (player.s, irq.s, probe.s), linked by src/sound/music.cfg:
                 $2000-$3FFF the program, $4000-$56FF the card image
                 $E900-$FFFF
  E1M1.AY ...    the 13 song files (tools/sound/README.md, "The song
                 file"), converted from the WAD's MUS lumps by mus2ay.py
                 now, in upstream's song order (mus.UPSTREAM_SONGS): keys
                 A to M
  PROFILE.TXT    the Doom configuration profile: its key and how to
                 install it (also DOOM_PROFILE.TXT beside the disk image,
                 build/sound/ by default, to copy beside the disk on the
                 SD card, where the Appletini's menu shows text files)

What MUSIC.SYSTEM does is in src/sound/music.s; the timing test (key T) is
src/sound/aytime.s. src/sound/README.md and tools/sound/README.md say how
to run it on the card.

--check runs the disk's MUSIC.SYSTEM on a2vm, its MLI trap serving the
disk's files (as tools/native/disk.py --check), on the exact W65C02S core,
under the cost model on the model's clock with the Phasor's slot-4
slowdown (f121+phasor, window 512), every interrupt held to the game's
contract (docs/MEMORY_MAP.md rule 2: zero page $D8-$FF and the stack, the
mouse card, the Phasor, $E000-$FFFF; a2vm --irq-bounds). Keys come from
a2vm input events at the Nth visit of mus_service, the main loop's once-a-
VBL service. The checks:

  songs    the boot (the probe says music, the 13 songs in RamWorks banks
           1-13 at $1000, byte for byte), then S seconds (20) of each song,
           A playing from the boot and B to M by key: every interrupt's
           AY writes and every start's first burst equal player.py's
           (tools/sound/run65.py's comparison, RingPlayer for the ring),
           each start at the VBL of its key, the chips' registers at the
           end equal the model's, and the status row (the song, its clock
           at 50 VBLs a second, its length, LOOP) in the last song
  keys     lower case, stop (SPACE), next (N), previous (P), M, the right
           arrow (M to A) and the left arrow (A to M), PAL/NTSC (V), play
           all (R: each song once, the next GAP VBLs after its end), T
           while a song plays (the music stops at its VBL, the test's
           writes and nothing else, the status row STOPPED at its time on
           the NTSC clock), then ESC: the same comparison, then the quit
  quit     q while A plays; the quit (ESC's too): snd_init's resets last,
           the card's former contents (a pattern loaded at the start) back
           byte for byte, the Phasor back in Mockingboard mode, ProDOS's
           QUIT
  nomusic  the Phasor locked to Mockingboard mode (--phasor-mb-only): the
           probe says no music, the screen says so and why, no song file
           is opened, a song key changes nothing on the screen, no AY
           write but the probe's and snd_init's, Q quits
  aytime   the timing test (T) under f121+phasor (window 512),
           +window32, +fws1, and PAL and NTSC: its write time equals the
           AY log's own spacing of the writes, its window equals the
           variant's, its verdict agrees, and rows 17-23 of its screen
           read exactly what the measured values and the design's
           expected ones give (aytime_rows)
"""

import argparse
import importlib.util
import json
import random
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import mus, mus2ay, player, run65, tables  # noqa: E402
from a2vm import costs  # noqa: E402
from ref816 import bounded  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
BUILD = ROOT / 'build'
OUT = BUILD / 'sound' / 'MUSIC.hdv'
PROFILE_OUT = BUILD / 'sound' / 'DOOM_PROFILE.TXT'
SRC = ROOT / 'src' / 'sound'
DOOM_TOOLS = ROOT.parent / 'doom' / 'tools'
A2VM = run65.A2VM

VOLUME = 'MUSIC'
SYSTEM = 'MUSIC.SYSTEM'
SONGS = mus.UPSTREAM_SONGS          # keys A to M
SONG_ADDRESS = 0x1000               # music.s SONG_ADDR, bank = index + 1
SAVE_BANK = len(SONGS) + 1
MAIN_SIZE, LC_SIZE = 0x2000, 0x1700  # music.cfg: $2000-$3FFF, $E900-$FFFF
A2LI = bytes((0xC1, 0xB2, 0xCC, 0xE9))   # docs/MEMORY_MAP.md rule 8
GAP = 50                            # music.s: VBLs from an end to the next
CLOCK_RATE = {False: 50, True: 60}  # the screen's clock: VBLs a second
IRQ_BOUNDS = '00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF'   # MEMORY_MAP rule 2
TIMEOUT = 900.0                     # a run's wall-time bound (seconds)
BUILD_TIMEOUT = 600.0               # a build step's (make, ca65, ld65)
MAX_BYTES = 64 << 20                # the largest file a run may write

# aytime.s
AYT_FRAMES, AYT_K1, AYT_K2 = 32, 16, 208
WRITE_MC = 41000                    # 41 bus cycles a write
# the Apple bus cycle in picoseconds: 10^12 / 1,015,625 Hz (PAL) and
# 10^12 / 1,020,484 Hz (NTSC), the model's clocks
BUS_PS = {False: 10 ** 12 // 1015625, True: 10 ** 12 // 1020484}
# what the design expects (native-sound.md 2.3), as the screen prints it
EXPECTED_ROWS = {
    False: ('AY TIMING, PAL (1,015,625 HZ)', '40.4', '504.1', '31.5'),
    True: ('AY TIMING, NTSC (1,020,484 HZ)', '40.2', '501.7', '31.4')}
VERDICTS = {0: 'another window', 1: 'window 512', 2: 'window 32',
            3: 'FW-S1'}

PROFILE_KEY = 'vtw.slowdown.cycles=32'
PROFILE_TEXT = """\
DOOM CONFIGURATION PROFILE FOR THE APPLETINI (DOOM GS, MILESTONE S3)

THE KEY
    vtw.slowdown.cycles=32

WHY
    With the virtual Phasor on, every access to slot 4 runs the CPU at
    1 MHz for the next vtw.slowdown.cycles CPU cycles: 512 by default
    (504 us after each burst of AY writes). 32 cuts that tail to 31.5 us,
    and the music's cost from 13-30 ms a second to 4-10 ms. The menu's
    presets start at 256, so 32 is set in a profile's file by hand.
    Mockingboard detection loops time the VIA timers 8 cycles apart; 32
    still covers them.

WHERE PROFILES LIVE (firmware F1.2.1, ps_sources/frontend)
    A profile is a folder on the card's SD volume, 0:/profiles/NAME/,
    holding appletini_cfg.txt (profile_manager.h). Loading one first
    resets every setting to its default, then applies the file's keys
    (config_menu.c, config_menu_read_settings_from_path), then saves the
    result as 0:/appletini_cfg.txt, so it stays after a reboot. A file
    holding only the key above would therefore turn off the Phasor, the
    mouse card, RamWorks and TURBO: start from a full profile instead.

INSTALL
    1. Boot into the Appletini menu with the setup DOOM needs: TURBO on,
       RamWorks on (8 MB), the mouse card in slot 2, the Phasor in slot 4
       on and its Mockingboard only option off.
    2. Profiles tab: Save As, name DOOM. This writes every current setting
       to 0:/profiles/DOOM/appletini_cfg.txt.
    3. Open that file on the SD volume (the SD card in a computer, or the
       menu's USB or FTP SD sharing) and change the line
           vtw.slowdown.cycles=512
       to
           vtw.slowdown.cycles=32
       Check these lines while there:
           phasor.slot4.enabled=ON
           phasor.mockingboard.only=OFF
           slot2.card=MOUSE
           vtw.turbo.enabled=ON
    4. Profiles tab: Choose profile, DOOM. The status line says LOADED
       PROFILE DOOM. (Between steps 2 and 4, change no bezel or video ROM
       setting: the menu also writes those into the selected profile,
       with the window it holds, 512.)
    5. Do not step the slowdown window in the menu afterwards: its presets
       are 256 to 65535, and a step replaces 32 with one of them.

CHECK IT
    Boot MUSIC.HDV and press T: the timing test prints the window. It
    says "THE WINDOW IS 32: THE DOOM PROFILE" with the profile, and "THE
    WINDOW IS 512: THE DEFAULT" without it.

UNDO
    Choose another profile, or set the line back to 512 and choose DOOM
    again.
"""


# ---------------------------------------------------------------------------
# the song files
# ---------------------------------------------------------------------------

class Song:
    def __init__(self, index, name, data, seconds):
        self.index, self.name, self.data = index, name, data
        self.seconds = seconds
        self.path = name.split('_', 1)[1] + '.AY'     # a ProDOS name
        self.label = name.ljust(8)[:8]
        self.bank = index + 1
        self.key = chr(ord('A') + index)
        self.file = player.SongFile.from_bytes(data)


def have_wad():
    return mus.WAD_PATH.exists()


def songs(wad_path=mus.WAD_PATH):
    """The 13 songs, converted from the WAD now, in upstream's order."""
    wad = mus.Wad.open(wad_path)
    instruments = mus2ay.load_instruments(wad)
    out = []
    for index, name in enumerate(SONGS):
        lump = wad.song(name)
        data = mus2ay.convert(lump, instruments)[0].to_bytes()
        out.append(Song(index, name, data, int(round(lump.seconds))))
    return out


def songs_inc(song_list):
    """build/.../songs.inc: the program's song tables."""
    lines = ['; Generated by tools/sound/musicdisk.py. Do not edit.',
             'NSONGS          = %d' % len(song_list),
             'MAX_SONG        = %d' % max(len(s.data) for s in song_list),
             '', '.macro SONG_TABLES', 'song_path:']
    for s in song_list:
        name = s.path.encode('ascii')
        padded = bytes([len(name)]) + name + bytes(15 - len(name))
        lines.append('        .byte   %s' % ', '.join('$%02X' % b
                                                      for b in padded))
    lines.append('song_label:')
    for s in song_list:
        lines.append('        .byte   "%s"' % s.label)
    for field, values in (
            ('song_secs_lo', [s.seconds & 0xFF for s in song_list]),
            ('song_secs_hi', [s.seconds >> 8 for s in song_list]),
            ('song_size_lo', [len(s.data) & 0xFF for s in song_list]),
            ('song_size_hi', [len(s.data) >> 8 for s in song_list])):
        lines.append('%s:' % field)
        lines.append('        .byte   %s' % ', '.join(str(v) for v in values))
    lines += ['.endmacro', '']
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# the program
# ---------------------------------------------------------------------------

class Program:
    """MUSIC.SYSTEM, assembled: its bytes and labels."""

    def __init__(self, obj):
        self.obj = Path(obj)
        self.labels = run65.read_labels(self.obj / 'music.lbl')
        self.main = (self.obj / 'music.main').read_bytes()
        self.lc = (self.obj / 'music.lc').read_bytes()
        self.segments = run65.segments(self.obj / 'music.map')
        if len(self.main) != MAIN_SIZE or len(self.lc) != LC_SIZE:
            raise ValueError('music.main is $2000 bytes and music.lc $1700')
        self.system = self.main + self.lc
        # ProDOS loads the file at $2000 with CPU stores, so its bytes at
        # $4078 reach the firmware's shadow of main: never its signature
        if self.system[0x4078 - 0x2000:0x407C - 0x2000] == A2LI:
            raise ValueError('MUSIC.SYSTEM holds the A2Li signature at $4078')


def have_cc65():
    return run65.have_cc65() and bool(shutil.which('make'))


def tool(args, what):
    """A build step under bounded.run (the ground rules: every run has a
    time limit); RuntimeError when it fails or warns."""
    result = bounded.run(args, timeout=BUILD_TIMEOUT, max_bytes=MAX_BYTES,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True)
    if result.returncode:
        raise RuntimeError('%s failed:\n%s' % (what, result.stdout))
    warnings = [line for line in result.stdout.splitlines()
                if 'warning' in line.lower()]
    if warnings:
        raise RuntimeError('%s warns:\n%s' % (what, '\n'.join(warnings)))
    return result.stdout


def build_program(song_list, obj, source=SRC):
    """Assemble and link MUSIC.SYSTEM into `obj` (the S2 player's objects
    by src/sound/Makefile, then music.s and aytime.s); no warning is
    accepted (the ground rules)."""
    obj = Path(obj).resolve()
    obj.mkdir(parents=True, exist_ok=True)
    # the S2 player (run65.build's make, here with a time limit)
    tool(['make', '-C', str(source), 'OUT=%s' % obj,
          'ROOT=%s' % run65.ROOT], 'make (the player)')
    (obj / 'songs.inc').write_text(songs_inc(song_list))
    for name in ('music', 'aytime'):
        tool(['ca65', '--cpu', '65C02', '-g', '-I', str(source),
              '-I', str(obj), '-o', str(obj / (name + '.o')),
              '-l', str(obj / (name + '.lst')), str(source / (name + '.s'))],
             'ca65 %s.s' % name)
    tool(['ld65', '-C', str(source / 'music.cfg'), '-o', str(obj / 'music'),
          '-Ln', str(obj / 'music.lbl'), '-m', str(obj / 'music.map')] +
         [str(obj / (n + '.o'))
          for n in ('player', 'irq', 'probe', 'music', 'aytime')],
         'ld65 music.cfg')
    return Program(obj)


# ---------------------------------------------------------------------------
# the disk
# ---------------------------------------------------------------------------

def disk_writer():
    """demos/doom/tools/build_disk.py, the existing port's writer."""
    path = DOOM_TOOLS / 'build_disk.py'
    spec = importlib.util.spec_from_file_location('doom_build_disk_music',
                                                  path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def have_disk_tools():
    if not (DOOM_TOOLS / 'build_disk.py').exists():
        return False
    return disk_writer().DEFAULT_MASTER.is_file()


def profile_bytes():
    """PROFILE.TXT: a ProDOS text file, CR line ends."""
    return PROFILE_TEXT.replace('\n', '\r').encode('ascii')


def files_of(program, song_list):
    """(name, ProDOS type, aux, bytes) of the disk's files but PRODOS, in
    the volume directory's order (ProDOS runs the first *.SYSTEM)."""
    out = [(SYSTEM, 0xFF, 0x2000, program.system)]
    for s in song_list:
        out.append((s.path, 0x06, SONG_ADDRESS, s.data))
    out.append(('PROFILE.TXT', 0x04, 0x0000, profile_bytes()))
    return out


def build_disk(files, output):
    bd = disk_writer()
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


def profile_path(output):
    """DOOM_PROFILE.TXT, beside the disk image `output`."""
    return Path(output).parent / PROFILE_OUT.name


def build(obj, output=OUT, profile_out=None):
    """Songs, program and disk: (program, songs, the disk's files). The
    profile's text goes to `profile_out`, by default beside the disk."""
    song_list = songs()
    program = build_program(song_list, obj)
    everything = build_disk(files_of(program, song_list), output)
    profile_out = Path(profile_out or profile_path(output))
    profile_out.parent.mkdir(parents=True, exist_ok=True)
    profile_out.write_text(PROFILE_TEXT)
    return program, song_list, everything


# ---------------------------------------------------------------------------
# a run on a2vm
# ---------------------------------------------------------------------------

class Run:
    """One run of MUSIC.SYSTEM on a2vm: its end state, AY log groups, final
    RAM (a2vm's snapshot layout, tools/native/a2run.py) and events."""

    MAIN, LC, LC1, AUX = 0, 0x10000, 0x14000, 0x15000

    def __init__(self, directory, labels, snapshots):
        self.directory = Path(directory)
        self.labels = labels
        self.state = json.loads((self.directory / 'state.json').read_text())
        self.events = run65.read_log(self.directory / 'ay.log')
        self.raw_writes = read_write_clocks(self.directory / 'ay.log')
        self.main, self.bursts, self.times, self.partial = \
            run65.group(self.events)
        self.ram = (self.directory / 'final.ram').read_bytes()
        self.snapshots = {}
        for name in snapshots:
            path = self.directory / (name + '.ram')
            if path.exists():
                self.snapshots[name] = path.read_bytes()

    def byte(self, label, ram=None):
        return self.bytes(label, 1, ram)[0]

    def bytes(self, label, count, ram=None):
        ram = self.ram if ram is None else ram
        address = self.labels[label]
        if address >= 0xE000:
            at = self.LC + address - 0xC000
        elif address >= 0xD000:
            raise ValueError('a $D000 label: which bank?')
        else:
            at = self.MAIN + address
        return ram[at:at + count]

    def word(self, label, size=4, signed=False):
        return int.from_bytes(self.bytes(label, size), 'little',
                              signed=signed)

    def aux(self, bank, address, count):
        at = self.AUX + bank * 0x10000 + address
        return self.ram[at:at + count]

    def screen(self, ram=None):
        ram = self.ram if ram is None else ram
        rows = []
        for r in range(24):
            at = 0x0400 + (r % 8) * 0x80 + (r // 8) * 0x28
            rows.append(''.join(text_char(b)
                                for b in ram[at:at + 40]).rstrip())
        return rows


def text_char(b):
    """A byte of the text page: normal ($80-$FF), inverse ($00-$3F),
    flashing ('?')."""
    if b >= 0x80:
        return chr(b & 0x7F)
    if b < 0x20:
        return chr(b | 0x40)
    return chr(b) if b < 0x40 else '?'


def read_write_clocks(path):
    """[(clock, chip, reg, value)] of the AY log's writes."""
    out = []
    with open(path) as log:
        for line in log:
            f = line.split()
            if f and f[0] == 'w':
                out.append((int(f[3]), int(f[4]), int(f[5]), int(f[6])))
    return out


def lc_pattern(seed=2026):
    """What the card holds before the boot (for the quit's restore check):
    kind 2 ($C000-$FFFF, bank 2 at $D000) and kind 3 (bank 1 $D000)."""
    rng = random.Random(seed)
    return (bytes(rng.randrange(256) for _ in range(0x3000)),
            bytes(rng.randrange(256) for _ in range(0x1000)))


def run(program, everything, directory, events=(), seconds=10.0,
        variants=('phasor',), ntsc=False, mb_only=False, stop_at=(),
        snapshots=(), a2vm=A2VM, timeout=TIMEOUT):
    """Boot the disk's MUSIC.SYSTEM on a2vm. `events`: (visit of
    mus_service, action) pairs, for instance (50, 'key B'); `snapshots`:
    (visit, name) pairs. The run ends after `seconds` of machine time, at
    ProDOS's QUIT, or at a label of `stop_at`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    labels = program.labels
    manifest = []
    for name, file_type, aux, data in everything:
        if name == 'PRODOS':
            continue
        path = directory / name
        path.write_bytes(data)
        manifest.append('%s %02X %04X %s' % (name, file_type, aux, path))
    (directory / 'prodos.txt').write_text('\n'.join(manifest) + '\n')
    (directory / 'rom.bin').write_bytes(bytes(0x4000))
    lc2, lc1 = lc_pattern()
    image = bytearray(b'A2VMIMG1')
    image += struct.pack('<BBHI', 2, 0, 0xD000, len(lc2)) + lc2
    image += struct.pack('<BBHI', 3, 0, 0xD000, len(lc1)) + lc1
    (directory / 'card.img').write_bytes(bytes(image))
    lines = []
    service = labels['mus_service']
    for visit, action in sorted(events, key=lambda e: e[0]):
        lines.append('pc %X@%d %s' % (service, visit, action))
    for visit, name in snapshots:
        lines.append('pc %X@%d snapshot %s' % (service, visit, name))
    (directory / 'events.txt').write_text('\n'.join(lines) + '\n')
    name = run65.cost_profile(ntsc, variants)
    (directory / 'cost.txt').write_text(costs.text(name))
    fabric_hz = costs.parameters(name)['fabric_mhz'] * 1e6
    args = [str(a2vm), '--rom', str(directory / 'rom.bin'),
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
            '--idle', '%X:vbl:eq=%X,%X' % (labels['mus_idle'],
                                           labels['vbl_count'],
                                           labels['seen']),
            '--stop-pc', '%X' % labels['snd_crash'],
            '--input', str(directory / 'events.txt'),
            '--snapshot-dir', str(directory), '--final-snapshot']
    for label in stop_at:
        args += ['--stop-pc', '%X' % labels[label]]
    if mb_only:
        args.append('--phasor-mb-only')
    result = bounded.run(args, timeout=timeout, max_bytes=MAX_BYTES,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True)
    state_path = directory / 'state.json'
    if result.returncode or not state_path.exists():
        halt = ''
        if state_path.exists():
            halt = json.loads(state_path.read_text()).get('halt', '')
        raise RuntimeError('a2vm failed (%d): %s\n%s' % (
            result.returncode, halt, result.stdout[-2000:]))
    return Run(directory, labels, [n for _, n in snapshots])


# ---------------------------------------------------------------------------
# the checks
# ---------------------------------------------------------------------------

class CheckFailed(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def starts_of(result, prefix=run65.init_events(probe=True)):
    """The interrupt indexes k whose main-loop group (after interrupt k,
    before k + 1; for k = 0 after the probe's and snd_init's events,
    `prefix`) wrote registers: a song's start (its first burst)."""
    groups = [result.main[0][len(prefix):]] + list(result.main[1:])
    return [k for k, g in enumerate(groups)
            if any(e[0] != 'reset' for e in g)]


def vbl_rate(ntsc=False):
    return tables.vbl_hz(run65.machine_of(ntsc))


def compare_plays(result, song_list, plays, prefix):
    """Every interrupt against RingPlayer: `plays` are run65 actions
    (kind, interrupt, bank, address, flags, attenuation). Returns (the
    difference or None, the model's last player)."""
    files = [s.file for s in song_list]
    main, bursts, last = run65.expected(files, plays, len(result.bursts))
    difference = run65.compare(result.main, result.bursts, main, bursts,
                               prefix)
    return difference, last


def check_songs(program, song_list, everything, work, seconds=20.0,
                a2vm=A2VM):
    """Boot, then `seconds` of each song: A from the boot, then each
    other by its key. Returns a summary dict; raises CheckFailed."""
    per = int(round(seconds * vbl_rate()))
    events = [(1 + k * per, 'key %s' % s.key)
              for k, s in enumerate(song_list) if k]
    total = (len(song_list) * per + 20) / vbl_rate()
    # the status row, VBLs into the last song: at that visit of
    # mus_service the clock has served `into` - 1 VBLs of it
    into = per - 10
    result = run(program, everything, Path(work) / 'songs', events,
                 seconds=total, snapshots=[(events[-1][0] + into, 'last')],
                 a2vm=a2vm)
    require(result.state['end'] == 'cycles',
            'the run ended early: %s at $%04X' % (result.state['end'],
                                                 result.state['pc']))
    require(result.byte('mus_loaded') == len(song_list),
            '%d songs loaded' % result.byte('mus_loaded'))
    for s in song_list:
        require(result.aux(s.bank, SONG_ADDRESS, len(s.data)) == s.data,
                '%s is not in bank %d' % (s.name, s.bank))
    starts = starts_of(result)
    require(len(starts) == len(song_list),
            '%d starts, expected %d' % (len(starts), len(song_list)))
    offset = starts[1] - events[0][0]
    for (visit, _), k in zip(events, starts[1:]):
        require(k == visit + offset, 'a start at interrupt %d, expected %d'
                % (k, visit + offset))
    plays = [(run65.START, k, s.bank, SONG_ADDRESS, run65.SONG_LOOP, 0)
             for k, s in zip(starts, song_list)]
    difference, model = compare_plays(
        result, song_list, plays, run65.init_events(probe=True))
    require(difference is None, 'songs: %s' % difference)
    difference = run65.final_difference(result, model)
    require(difference is None, 'songs, at the end: %s' % difference)
    screen = result.screen()
    require(screen[0].startswith('DOOM GS: THE MUSIC ON THE PHASOR'),
            'the title: %r' % screen[0])
    require(screen[1].startswith('PAL //E: TIMER 1 COUNTS'),
            'the machine line: %r' % screen[1])
    last = song_list[-1]
    status = result.screen(result.snapshots['last'])[12]
    want = status_row(True, last, (into - 1) // CLOCK_RATE[False], False)
    require(status == want, 'the status row %d VBLs into %s: %r, expected '
            '%r' % (into, last.name, status, want))
    require(result.byte('mus_playing') == len(song_list),
            'the last song is not playing')
    vblcyc = result.word('vblcyc', 2)
    require(abs(vblcyc - 312 * 65) < 64, 'timer 1: %d cycles a VBL' % vblcyc)
    shutil.rmtree(str(result.directory), True)
    return {'interrupts': len(result.bursts), 'starts': starts,
            'seconds_each': per / vbl_rate(), 'vblcyc': vblcyc,
            'screen': screen}


def put_time(seconds):
    """music.s's put_time: M:SS."""
    return '%d:%02d' % divmod(seconds, 60)


def status_row(playing, song, seconds, through):
    """Row 12 of MUSIC.SYSTEM's screen (draw_status, draw_time): the
    song, its time on the clock, its length, the mode."""
    row = [' '] * 40

    def put(column, text):
        row[column:column + len(text)] = text

    put(0, ('PLAYING ' if playing else 'STOPPED ') + song.label)
    put(17, put_time(seconds) + ' ')
    put(24, 'OF ' + put_time(song.seconds))
    put(34, 'ALL' if through else 'LOOP')
    return ''.join(row).rstrip()


def ended_at(song, start, ntsc, loop=False):
    """The interrupt at which RingPlayer of `song`, started after
    interrupt `start` and refilled after each interrupt, reaches its end."""
    p = run65.RingPlayer(song.file, run65.machine_of(ntsc), loop=loop)
    p.start()
    k = start
    while not p.ended:
        k += 1
        p.interrupt()
        p.refill()
    return k


def check_keys(program, song_list, everything, work, a2vm=A2VM):
    """The keys: b (lower case), SPACE, N, P, M, the right arrow (M to A),
    the left arrow (A to M), V, R, K and the next song by itself in "play
    all" mode, T while that song plays (the music stops, the test runs),
    then ESC (Q is check_quit)."""
    intro = song_list[SONGS.index('D_INTRO')]
    after = song_list[SONGS.index('D_INTRO') + 1]
    last = song_list[-1]
    events = [(50, 'key b'), (150, 'key 32'), (250, 'key N'),
              (350, 'key P'), (400, 'key %s' % last.key),
              (420, 'key 0x15'), (440, 'key 0x08'), (450, 'key V'),
              (550, 'key R'), (560, 'key %s' % intro.key)]
    # T 100 VBLs into the song after D_INTRO, the quit 50 visits after the
    # test (the main loop does not run during it)
    into = 100
    t_visit = 560 + ended_at(intro, 0, True) + GAP - 1 + into
    events += [(t_visit, 'key T'), (t_visit + 50, 'key 0x1B')]
    seconds = (t_visit + 50 + 400) / vbl_rate()
    result = run(program, everything, Path(work) / 'keys',
                 events, seconds=seconds,
                 snapshots=[(t_visit + 5, 'timed')], a2vm=a2vm)
    require_quit(result)
    result.main[-1] = []
    offset = starts_of(result)[1] - 50
    # the timing test's writes (R8 of chip 0 = 0, from the main loop after
    # T's interrupt), taken out before the comparison with the player
    t_k = t_visit + offset
    test_writes = 0
    for k in range(t_k + 1, len(result.main)):
        kept = [e for e in result.main[k] if e != (0, 8, 0)]
        test_writes += len(result.main[k]) - len(kept)
        result.main[k] = kept
    want_writes = AYT_FRAMES * (AYT_K1 + AYT_K2)
    require(test_writes == want_writes, 'T: %d writes of the timing test, '
            'expected %d' % (test_writes, want_writes))
    starts = starts_of(result)
    b, c = song_list[1], song_list[2]
    loop, ntsc = run65.SONG_LOOP, run65.SONG_NTSC

    def start(visit, song, flags):
        return (run65.START, visit + offset, song.bank, SONG_ADDRESS,
                flags, 0)

    stop = (run65.STOP, 0, 0, 0, 0, 0)
    plays = [(run65.START, starts[0], song_list[0].bank, SONG_ADDRESS,
              loop, 0),
             start(50, b, loop),
             stop[:1] + (150 + offset,) + stop[2:],
             start(250, c, loop),
             start(350, b, loop),
             start(400, last, loop),                 # M
             start(420, song_list[0], loop),         # right arrow: M to A
             start(440, last, loop),                 # left arrow: A to M
             start(450, last, loop | ntsc),          # V: M again, NTSC
             start(560, intro, ntsc)]                # R, then K
    end = ended_at(intro, 560 + offset, True)
    plays.append((run65.START, end + GAP - 1, after.bank, SONG_ADDRESS,
                  ntsc, 0))
    plays.append(stop[:1] + (t_k,) + stop[2:])       # T stops the music
    want = [p[1] for p in plays if p[0] == run65.START]
    require(starts == want, 'starts at %s, expected %s' % (starts, want))
    difference, _ = compare_plays(result, song_list, plays,
                                  run65.init_events(probe=True))
    require(difference is None, 'keys: %s' % difference)
    # during the test: the song stopped at its time on the NTSC clock (60
    # VBLs a second after V), "play all", and the test's heading
    screen = result.screen(result.snapshots['timed'])
    status = status_row(False, after, (into - 1) // CLOCK_RATE[True], True)
    require(screen[12] == status, 'T: the status row %r, expected %r' % (
        screen[12], status))
    require(screen[17] == EXPECTED_ROWS[True][0],
            'T: row 17 %r' % screen[17])
    shutil.rmtree(str(result.directory), True)
    return {'starts': starts, 'songs': [
        SONGS[p[2] - 1] for p in plays if p[0] == run65.START],
        'play_all_next': end + GAP - 1, 'stop_t': t_k,
        'test_writes': test_writes}


def require_quit(result):
    """The quit (ESC or Q): ProDOS's QUIT, snd_init's resets the last AY
    events, the chips reset, the card's former contents back byte for
    byte, the Phasor back in Mockingboard mode."""
    require(result.state['end'] == 'quit',
            'the run did not quit: %s' % result.state['end'])
    require(result.state['prodos']['quit'] == 1, 'no ProDOS QUIT')
    require(result.main[-1] == list(run65.INIT_RESETS),
            'the quit wrote %s' % result.main[-1][:6])
    lc2, lc1 = lc_pattern()
    require(result.ram[Run.LC + 0x1000:Run.LC + 0x4000] == lc2 and
            result.ram[Run.LC1:Run.LC1 + 0x1000] == lc1,
            'the card after the quit is not what ProDOS had')
    require(all(v == 0 for chip in result.state['phasor']['ay']
                for v in chip), 'the chips are not reset after the quit')
    require(result.state['phasor']['mode'] == run65.MOCKINGBOARD_MODE,
            'the quit left the Phasor in mode %s, not Mockingboard mode' %
            result.state['phasor']['mode'])


def check_quit(program, song_list, everything, work, a2vm=A2VM):
    """q (lower case) while A plays: the same quit as ESC's."""
    result = run(program, everything, Path(work) / 'quit',
                 [(30, 'key q')], seconds=5.0, a2vm=a2vm)
    require_quit(result)
    result.main[-1] = []
    starts = starts_of(result)
    plays = [(run65.START, starts[0], song_list[0].bank, SONG_ADDRESS,
              run65.SONG_LOOP, 0)]
    require(len(starts) == 1, 'starts at %s' % starts)
    difference, _ = compare_plays(result, song_list, plays,
                                  run65.init_events(probe=True))
    require(difference is None, 'quit: %s' % difference)
    shutil.rmtree(str(result.directory), True)
    return {'interrupts': len(result.bursts)}


def check_nomusic(program, song_list, everything, work, a2vm=A2VM):
    """The Phasor locked to Mockingboard mode."""
    events = [(20, 'key A'), (60, 'key Q')]
    result = run(program, everything, Path(work) / 'nomusic', events,
                 seconds=5.0, mb_only=True,
                 snapshots=[(10, 'before'), (40, 'mid')], a2vm=a2vm)
    require(result.state['end'] == 'quit',
            'the run did not quit: %s' % result.state['end'])
    prodos = result.state['prodos']
    require(prodos['calls'] == 1, '%d MLI calls, expected 1 (QUIT): a song '
            'file was opened' % prodos['calls'])
    require(result.byte('mus_loaded') == 0, 'songs were loaded')
    screen = result.screen(result.snapshots['mid'])
    text = '\n'.join(screen)
    require('NO MUSIC. THE CARD IN SLOT 4 DID NOT' in text and
            'MOCKINGBOARD ONLY' in text, 'the screen:\n' + text)
    # the song key did nothing: the screen is as it was before it, with
    # no message on the last row (a refused song would put one there)
    before = result.screen(result.snapshots['before'])
    require(screen == before and not screen[23],
            'the song key changed the screen:\n%s\nbefore it:\n%s' % (
                text, '\n'.join(before)))
    events_seen = [e[1:4] if e[0] == 'w' else e for e in result.events
                   if e[0] in ('w', 'reset')]
    want = list(run65.init_events(probe=True, mb_only=True)) + \
        list(run65.INIT_RESETS)
    require(events_seen == want, 'AY events %s, expected %s' % (
        events_seen[:12], want))
    require(result.state['phasor']['mode'] == run65.MOCKINGBOARD_MODE,
            'the card left Mockingboard mode')
    shutil.rmtree(str(result.directory), True)
    return {'screen': screen}


AYT_CASES = (('window 512', ('phasor',), False, 1, 512),
             ('window 32', ('phasor', 'window32'), False, 2, 32),
             ('FW-S1', ('phasor', 'fws1'), False, 3, None),
             ('window 512, NTSC', ('phasor',), True, 1, 512))


def check_aytime(program, song_list, everything, work, case, a2vm=A2VM):
    """The timing test under one variant: (label, variants, ntsc,
    verdict, window). Returns what it measured."""
    label, variants, ntsc, verdict, window = case
    tag = label.replace(' ', '').replace(',', '-')
    result = run(program, everything, Path(work) / ('aytime-' + tag),
                 [(5, 'key T')], seconds=12.0, variants=variants,
                 ntsc=ntsc, stop_at=('ayt_done',), a2vm=a2vm)
    require(result.state['end'] == 'stop-pc' and
            result.state['pc'] == program.labels['ayt_done'],
            'the test did not end: %s at $%04X' % (result.state['end'],
                                                   result.state['pc']))
    got = {name: result.word('ayt_' + name, 4, signed=(name == 'e'))
           for name in ('cf', 'c1', 'c2', 'd1', 'd2', 'tw', 'e', 's',
                        'w10')}
    got['verdict'] = result.byte('ayt_verdict')
    require(got['verdict'] == verdict, '%s: verdict %s, expected %s' % (
        label, VERDICTS.get(got['verdict']), VERDICTS[verdict]))
    # the write, against the AY log: the mean spacing of the writes in
    # phase 2's bursts (AYT_K2 writes each; with FW-S1 a write takes 9 or
    # 10 bus cycles by its alignment to the bus, so a mean, not a median)
    params = costs.parameters(run65.cost_profile(ntsc, variants))
    fabric_per_cycle = params['line_us'] * params['fabric_mhz'] / 65.0
    writes = [w[0] for w in result.raw_writes if w[1:] == (0, 8, 0)]
    bursts, current = [], [writes[0]]
    for clock in writes[1:]:
        if clock - current[-1] > 200 * fabric_per_cycle:
            bursts.append(current)
            current = []
        current.append(clock)
    bursts.append(current)
    long = [b for b in bursts if len(b) == AYT_K2]
    require(len(long) == AYT_FRAMES, '%s: %d bursts of %d writes in the AY '
            'log, expected %d' % (label, len(long), AYT_K2, AYT_FRAMES))
    log_mc = 1000.0 * statistics.mean(
        (b[-1] - b[0]) / (len(b) - 1) for b in long) / fabric_per_cycle
    got['log_tw'] = log_mc
    require(abs(got['tw'] - log_mc) <= 0.01 * log_mc,
            '%s: a write %d mc, the AY log spaces them %.0f mc' % (
                label, got['tw'], log_mc))
    if window is not None:
        require(abs(got['tw'] - WRITE_MC) <= 150,
                '%s: a write %d mc, expected %d' % (label, got['tw'],
                                                    WRITE_MC))
        # the slow cycles after a burst, as aytime.s's arithmetic finds
        # them: the window, give or take what the formula leaves out (an
        # instruction that began slow keeps its cycles when the window
        # closes inside it, tools/a2vm/README.md "The slot-4 slowdown";
        # the burst's first bus cycle, counted as 1, is 0.93 to 1.93).
        # On a2vm the result lies 0.1 under to 1.3 over the window and
        # moves by about a cycle with where the code falls against the
        # bus clock (a build that adds a byte to music.s changes it), so
        # the check accepts 0.5 under to 3 over.
        require(10 * window - 5 <= got['w10'] <= 10 * window + 30,
                '%s: the window %.1f cycles, expected %.1f to %d' % (
                    label, got['w10'] / 10.0, window - 0.5, window + 3))
    # the screen, rows 17-23, exactly: the figures the owner reads,
    # computed here from the measured values (ayt_tw, ayt_w10, ayt_e) and
    # the design's expected ones
    screen = result.screen()[17:24]
    want = aytime_rows(got, ntsc)
    for row, (have, should) in enumerate(zip(screen, want), 17):
        require(have == should, '%s: row %d of the screen is %r, expected '
                '%r' % (label, row, have, should))
    got['screen'] = screen
    shutil.rmtree(str(result.directory), True)
    return got


def muldiv(a, b, d):
    """aytime.s's muldiv: a x b / d, rounded (half up)."""
    return (a * b + (d >> 1)) // d


def dec1(tenths):
    """aytime.s's put_dec1: tenths as 'N.N'."""
    return '%d.%d' % divmod(tenths, 10)


def aytime_rows(got, ntsc):
    """Rows 17-23 of the timing test's screen, as they must read for the
    measured `got` (ayt_tw, ayt_w10, ayt_e in mc or tenths, ayt_verdict):
    microseconds are cycles x the bus cycle, one decimal, rounded."""
    head, write, tail512, tail32 = EXPECTED_ROWS[ntsc]
    bps = BUS_PS[ntsc]
    rows = [head, 'A WRITE %s US, EXPECTED %s' % (
        dec1(muldiv(got['tw'], bps, 10 ** 8)), write)]
    if got['verdict'] == 3:
        e = got['e']
        rows.append("NO TAIL. A BURST'S EXTRA US: %s%s" % (
            '-' if e < 0 else '', dec1(muldiv(abs(e), bps, 10 ** 8))))
    else:
        w10 = got['w10']
        rows.append('TAIL %s CYCLES = %s US' % (
            dec1(w10), dec1(muldiv(w10, bps, 10 ** 6))))
    rows += ['EXPECTED 512 = %s US: DEFAULT' % tail512,
             '      OR  32 = %s US: DOOM PROFILE' % tail32,
             {0: 'ANOTHER WINDOW THAN 512 OR 32',
              1: 'SO THE WINDOW IS 512: THE DEFAULT',
              2: 'SO THE WINDOW IS 32: THE DOOM PROFILE',
              3: 'PORT WRITES ARE NOT SLOWED: FW-S1'}[got['verdict']],
             '(FW-S1: A WRITE ABOUT 8.4 US, NO TAIL)']
    return rows


def check_all(program, song_list, everything, work, jobs=2, seconds=20.0,
              a2vm=A2VM):
    tasks = [('songs', lambda: check_songs(program, song_list, everything,
                                           work, seconds, a2vm)),
             ('keys', lambda: check_keys(program, song_list, everything,
                                         work, a2vm)),
             ('quit', lambda: check_quit(program, song_list, everything,
                                         work, a2vm)),
             ('nomusic', lambda: check_nomusic(program, song_list,
                                               everything, work, a2vm))]
    for case in AYT_CASES:
        tasks.append(('aytime ' + case[0],
                      lambda case=case: check_aytime(
                          program, song_list, everything, work, case, a2vm)))

    def one(task):
        name, fn = task
        try:
            return name, fn(), None
        except (CheckFailed, RuntimeError) as error:
            return name, None, str(error)
        except subprocess.TimeoutExpired as error:
            return name, None, 'a run passed its time limit: %s' % error

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, tasks))


def report(results):
    failures = 0
    for name, got, error in results:
        if error:
            failures += 1
            print('FAIL %-22s %s' % (name, error))
            continue
        if name == 'songs':
            print('ok   %-22s %d interrupts, 13 songs x %.1f s equal '
                  'player.py; timer 1: %d cycles a VBL' % (
                      name, got['interrupts'], got['seconds_each'],
                      got['vblcyc']))
        elif name == 'keys':
            print('ok   %-22s starts %s: %s; T stops at %d, %d test '
                  'writes; ESC quits' % (name, got['starts'],
                                         ' '.join(got['songs']),
                                         got['stop_t'], got['test_writes']))
        elif name == 'quit':
            print('ok   %-22s q after %d interrupts: ProDOS\'s card back, '
                  'the Phasor in Mockingboard mode' % (name,
                                                       got['interrupts']))
        elif name == 'nomusic':
            print('ok   %-22s %s' % (name, got['screen'][2]))
        else:
            print('ok   %-22s a write %.3f cycles (AY log %.3f), window '
                  '%.1f cycles, E %.3f cycles, s %.4f, %s' % (
                      name, got['tw'] / 1000.0, got['log_tw'] / 1000.0,
                      got['w10'] / 10.0, got['e'] / 1000.0,
                      got['s'] / 1000.0, VERDICTS[got['verdict']]))
            for row in got['screen']:
                if row:
                    print('       | ' + row)
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--seconds', type=float, default=20.0)
    parser.add_argument('--keep', type=Path,
                        help='keep the objects and runs in this directory')
    args = parser.parse_args(argv)
    work = (args.keep or Path(tempfile.mkdtemp(prefix='tmp-musicdisk-',
                                               dir=str(BUILD)))).resolve()
    try:
        program, song_list, everything = build(work / 'obj', args.out)
        size = args.out.stat().st_size
        print('%s: %d bytes (%d blocks), volume %s' % (
            args.out, size, size // 512, VOLUME))
        for name, file_type, aux, data in everything:
            print('  %-12s type $%02X aux $%04X %6d bytes' % (
                name, file_type, aux, len(data)))
        seg = program.segments
        code = seg['SNDCODE'][1] + seg['SNDRODATA'][1]
        print('  the card: player code and tables $E900-$%04X (%d of 4096 '
              'bytes), program $2000-$%04X' % (
                  0xE900 + code - 1, code,
                  max(s + n for s, n in (seg['MUSCODE'], seg['MUSDATA'],
                                         seg['SNDBOOT'])) - 1))
        print('%s: the profile\'s instructions' % profile_path(args.out))
        if not args.check:
            return 0
        if not A2VM.exists():       # (run65.build_a2vm, with a time limit)
            tool(['make', '-C', str(run65.ROOT / 'tools' / 'a2vm'),
                  str(A2VM)], 'make (a2vm)')
        results = check_all(program, song_list, everything, work,
                            args.jobs, args.seconds)
        return 1 if report(results) else 0
    finally:
        if not args.keep:
            shutil.rmtree(str(work), True)


if __name__ == '__main__':
    sys.exit(main())
