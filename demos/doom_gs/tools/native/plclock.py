#!/usr/bin/env python3
"""The tic clock's host model and part plclock's a2vm runs (milestone 11;
docs/SCREENS.md 2.2, 2.3, 6.5, 7.3; docs/m11-parts/plclock.md).

The model (SCREENS.md 2.2, 0.1 F2). The mouse card's VBL adds a 16-bit
fraction a VBL to the clock; a carry out of it is a tic. The fraction is
round(34.955 x 65,536 / the VBL's rate): 45,743 on a PAL //e (1,015,625
bus cycles a second, 312 lines of 65 cycles a VBL) and 38,229 on NTSC
(1,020,484, 262 lines) [R tools/sound/README.md:63-73]. After the clock's
start, at VBL n the fraction is n x F mod 65,536 and the tics n x F >> 16.
PAL or NTSC: VIA-A's timer 1 over one VBL, the nearer of 20,280 and 17,030
(the cut 18,655, as MUSIC.SYSTEM).

The runs (each in a directory the caller gives, under build/ or a tempfile
directory, bounded in cycles, wall time and file size):

  clock_run    the clock's test image (build/native/m11/plclock/plct) under
               the test driver s2_drv with pl_vbl the handler: plt_clock
               logs the tics' low word and the fraction after each of N
               VBLs; the AY log gives each interrupt's time; optional
               button presses with the button interrupt on (a second entry
               with no VBL pending)
  music_run    S2's test driver and player with pl_vbl
               (build/native/m11/plclock/music) playing a song file;
               s2_music_run the same with S2's own build (build/sound65,
               tools/sound/run65.py's run), the reference
  bridge_run   the bridge's synthetic machine (build/native/m11/plclock/
               bridge): the main loop with ALTZP on, the aux card only the
               bridge

Usage:
  python3 tools/native/plclock.py --model          the fractions and rates
  python3 tools/native/plclock.py --cfg music|bridge OUT   an ld65 map
  python3 tools/native/plclock.py --checkpoint [--seconds S] [--songs N]
          [--jobs J]    the part's checkpoint (SCREENS.md 6.5's clock and
                        IRQ rows, the music, the bridge) and its report
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from a2vm import costs  # noqa: E402
from native import lrun, s2layout as S, s2run as SR  # noqa: E402
from ref816 import bounded  # noqa: E402
from sound import run65  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
PART = BUILD / 'native' / 'm11' / 'plclock'
SOUND65 = BUILD / 'sound65'
SONGS = BUILD / 'sound'
A2VM = SR.A2VM

# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

STD_PAL, STD_NTSC = 0x00, 0x80          # CLK_STD (S2's SONG_NTSC bit)
STANDARDS = (STD_PAL, STD_NTSC)
NAMES = {STD_PAL: 'PAL', STD_NTSC: 'NTSC'}
BUS_HZ = {STD_PAL: 1015625, STD_NTSC: 1020484}
VBL_CYCLES = {STD_PAL: 312 * 65, STD_NTSC: 262 * 65}
TIC_RATE = 34.955               # upstream's [M: MILESTONES.md 2]
TIC_FRAC = {STD_PAL: 45743, STD_NTSC: 38229}     # SCREENS.md 2.2
PAL_NTSC_CUT = (VBL_CYCLES[STD_PAL] + VBL_CYCLES[STD_NTSC]) // 2
RATE_RANGE = (34.9, 35.0)       # the acceptance's tics a second


def vbl_hz(std: int) -> float:
    return BUS_HZ[std] / VBL_CYCLES[std]


def tic_frac(std: int) -> int:
    """The fraction a VBL, from the rates."""
    return int(round(TIC_RATE * 65536 / vbl_hz(std)))


def tic_rate(std: int, frac: Optional[int] = None) -> float:
    return vbl_hz(std) * (TIC_FRAC[std] if frac is None else frac) / 65536


def clock_at(n: int, std: int) -> Tuple[int, int]:
    """(the fraction, the tics) after n VBLs from the clock's start."""
    x = n * TIC_FRAC[std]
    return x & 0xFFFF, x >> 16


def detect(count: int) -> int:
    """The standard of a VBL `count` bus cycles long."""
    return STD_PAL if count >= PAL_NTSC_CUT else STD_NTSC


def check_model() -> List[str]:
    out = []
    for std in STANDARDS:
        if tic_frac(std) != TIC_FRAC[std]:
            out.append('%s: the rates give %d, the design %d' % (
                NAMES[std], tic_frac(std), TIC_FRAC[std]))
        r = tic_rate(std)
        if not RATE_RANGE[0] <= r <= RATE_RANGE[1]:
            out.append('%s: %.4f tics a second' % (NAMES[std], r))
        if detect(VBL_CYCLES[std]) != std:
            out.append('%s: detected as the other' % NAMES[std])
    # the step form equals the closed form
    for std in STANDARDS:
        frac = tics = 0
        for n in range(1, 70000):
            frac += TIC_FRAC[std]
            tics += frac >> 16
            frac &= 0xFFFF
            if (frac, tics) != clock_at(n, std):
                out.append('%s: the step form leaves the closed form at %d'
                           % (NAMES[std], n))
                break
    return out


# ---------------------------------------------------------------------------
# The ld65 maps of the music's image and the bridge's machine
# ---------------------------------------------------------------------------

DRV_MAIN = 0x0800               # S2's driver and probe; pl_bt.s
DRVZP = 0x80                    # S2's driver's zero page (the main loop's)


def _card() -> Dict[str, Tuple[int, int]]:
    places = {name: (lo, hi) for name, lo, hi in S.S2_CARD}
    return {'ring': places['the song ring and its mirror'],
            'list': places['the player\'s write lists'],
            'state': places['the player\'s state'],
            'snd': places['S2\'s code and tables']}


def cfg_text(kind: str) -> str:
    """The ld65 map of the music's image (kind 'music': S2's driver,
    player and probe, fx.s's card part, pl_irq.s) or of the bridge's
    machine ('bridge': pl_bt.s, the player, fx.s's card part, pl_irq.s, the
    bridge at $FF00 and the aux card's vectors), at the game's places
    (s2layout.py: S2's card areas, FX_CODE, the platform's $FF00)."""
    c = _card()
    zp_lo = S.ZP_MUSIC[0]
    fx_lo, fx_hi = S.FX_CODE
    plat_lo, plat_hi = S.PLATFORM_CARD[1], S.PLATFORM_CARD[2]
    rep_lo, rep_hi = S.REPLAY_CARD[1], S.REPLAY_CARD[2]

    def area(name, lo, hi, file, extra=''):
        return '    %-7s start = $%04X, size = $%04X, %sfile = %s;\n' % (
            name + ':', lo, hi - lo, extra, file)
    head = ('# Generated by tools/native/plclock.py --cfg %s (part plclock;\n'
            '# s2layout.py\'s places). Do not edit.\n' % kind)
    mem = 'MEMORY {\n'
    if kind == 'music':
        mem += area('DRVZP', DRVZP, DRVZP + 0x40, '""', 'type = rw, ')
    mem += area('SNDZP', zp_lo, 0x100, '""', 'type = rw, ')
    mem += area('MAIN', DRV_MAIN, DRV_MAIN + 0x1000,
                '"%O.main"', 'type = rw, ')
    mem += area('RING', c['ring'][0], c['ring'][1], '""', 'type = rw, ')
    mem += area('LIST', c['list'][0], c['list'][1], '""', 'type = rw, ')
    mem += area('STATE', c['state'][0], c['state'][1], '""', 'type = rw, ')
    mem += area('SND', c['snd'][0], c['snd'][1], '"%O.lc"', 'fill = yes, ')
    mem += area('FXC', fx_lo, fx_hi, '"%O.lc"', 'fill = yes, ')
    mem += area('REST', rep_lo, rep_hi, '"%O.lc"', 'fill = yes, ')
    if kind == 'bridge':
        mem += area('BRIDGE', plat_lo, plat_hi, '"%O.lc"', 'fill = yes, ')
    else:
        mem += area('PLAT', plat_lo, plat_hi, '"%O.lc"', 'fill = yes, ')
    mem += area('VEC', 0xFFFA, 0x10000, '"%O.lc"')
    if kind == 'bridge':
        mem += area('AUXVEC', 0xFFFA, 0x10000, '"%O.auxvec"')
    mem += '}\n'
    seg = 'SEGMENTS {\n'
    rows = [('SNDZP', 'SNDZP', 'type = zp')]
    if kind == 'music':
        rows += [('DRVZP', 'DRVZP', 'type = zp'),
                 ('DRVCODE', 'MAIN', 'type = rw'),
                 ('DRVDATA', 'MAIN', 'type = rw'),
                 ('SNDBOOT', 'MAIN', 'type = rw')]
    else:
        rows += [('BTCODE', 'MAIN', 'type = rw'),
                 ('BTDATA', 'MAIN', 'type = rw')]
    rows += [('SNDRING', 'RING', 'type = bss, align = $100'),
             ('SNDLIST', 'LIST', 'type = bss'),
             ('SNDBSS', 'STATE', 'type = bss'),
             ('SNDCODE', 'SND', 'type = ro'),
             ('SNDRODATA', 'SND', 'type = ro'),
             ('FXCODE', 'FXC', 'type = ro, define = yes'),
             ('VECTORS', 'VEC', 'type = ro')]
    if kind == 'bridge':
        rows += [('PLBRIDGE', 'BRIDGE', 'type = ro, define = yes'),
                 ('AUXVEC', 'AUXVEC', 'type = ro')]
    for name, load, extra in rows:
        seg += '    %-10s load = %s, %s;\n' % (name + ':', load, extra)
    seg += '}\n'
    return head + mem + seg


# ---------------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------------

class Linked(NamedTuple):
    """A build of plclock's own maps: its files and labels."""
    dir: Path
    name: str
    labels: Dict[str, int]
    segments: Dict[str, Tuple[int, int]]        # (start, size)

    def file(self, suffix: str) -> bytes:
        return (self.dir / ('%s.%s' % (self.name, suffix))).read_bytes()


def load_linked(directory: Path, name: str) -> Linked:
    return Linked(Path(directory), name,
                  run65.read_labels(Path(directory) / (name + '.lbl')),
                  run65.segments(Path(directory) / (name + '.map')))


def make(m11: Optional[Path] = None, source: Optional[Path] = None) -> None:
    """make -f m11.mk part P=plclock (into `m11`; a copy of the sources in
    `source` takes the others from the tree); fails on a warning."""
    SR.make('plclock', m11=m11 or SR.M11, source=source or SR.SOURCE)


def have_build(part: Path = PART) -> bool:
    return all(p.exists() for p in (
        part / 'plct.map', part / 'music' / 'sound.map',
        part / 'bridge' / 'plbr.map'))


# ---------------------------------------------------------------------------
# The clock's runs
# ---------------------------------------------------------------------------

IRQ_BOUNDS = SR.IRQ_BOUNDS      # '00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF'
RUN_TIMEOUT = 600.0
MAX_FILE = 64 << 20
DETECT = 0xFF                   # plt_clock's Y: detect the standard
MODE_VBL, MODE_VBL_BUTTON = 0x09, 0x0D
PLT_MISSED = 0x7C


class ClockRun(NamedTuple):
    state: Dict[str, Any]
    work: Path
    status: Optional[int]
    ended: str
    log: List[Tuple[int, int]]                  # (tics' low word, fraction)
    std: int                                    # plt_std at the end
    count: int                                  # pl_detect's count
    irqs: List[Tuple[int, int]]                 # (entry, rti) clocks
    vbl_count: int
    tics: int                                   # CLK_TICS at the stop
    stack: Dict[str, Optional[int]]             # lowest S: idle, handler


def clock_run(work: Path, n: int, std: int = DETECT,
              profile: str = 'f121', mode: int = MODE_VBL,
              buttons: Sequence[int] = (), part: Path = PART,
              irq_bounds: Optional[str] = IRQ_BOUNDS,
              fill: int = 0xA5, idle: bool = True) -> ClockRun:
    """plt_clock over n VBLs under `profile` (--cost-timed). `buttons`:
    a2vm cycles at which the mouse's button is pressed, then released
    half a frame later (with mode MODE_VBL_BUTTON each is an interrupt
    with no VBL pending). idle: plt_idle is an a2vm idle loop (the clock
    skips to the next VBL); a run with buttons needs it off, or a press
    due during a skip would come with the VBL's interrupt."""
    b = SR.load_build(part, 'plct', 'P2DW')
    lab = b.labels
    if n > lab['PLT_MAX']:
        raise SR.RunError('%d VBLs: the log holds %d' % (n, lab['PLT_MAX']))
    work.mkdir(parents=True, exist_ok=True)
    calls = [SR.Call('plt_mode', mode),
             SR.Call('plt_clock', n & 0xFF, n >> 8, std)]
    loads = (SR.image_load(b),)
    recs = SR.base_records(b, fill) + [SR.descriptor_record(b, loads, calls)]
    (work / 'image.bin').write_bytes(lrun.RC.image_bytes(recs))
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    (work / 'cost.txt').write_text(costs.text(profile))
    fabric = costs.parameters(profile)['fabric_mhz'] * 1e6
    std_hz = vbl_hz(STD_NTSC if 'ntsc' in profile.split('+') else STD_PAL)
    seconds = (n + 8) / std_hz + 0.5
    loop = lab['plt_idle']
    hand = [(b.segments[s][0], b.segments[s][1])
            for s in ('FXCODE', 'SNDCODE')]
    lowest = [(loop, loop + 5)] + hand
    log_lo = lab['PLT_LOG']        # the log and plt_* in W
    args = [str(A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--amem', '--via-ora-nh',
            '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--switch', 'lc_bank2=0',
            '--reg', 'pc=%X' % lab['s2d_start'],
            '--reg', 's=%X' % S.DRV_STACK, '--reg', 'p=34',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--cycles', str(int(seconds * fabric)),
            '--lowest-s-in', ','.join('%X-%X' % r for r in lowest),
            '--ay-log', str(work / 'ay.log'),
            '--state', str(work / 'state.json'),
            '--snapshot-dir', str(work),
            '--snapshot-ranges', 'main:0000-03FF,main:6000-BFFF,'
            'lc:E400-E41F',
            '--stop-pc', '%X' % lab['pl_crash'],
            '--stop-pc', '%X' % lab['s2d_stop']]
    if idle:
        args += ['--idle', '%X:vbl:eq=%X,%X' % (loop, lab['vbl_count'],
                                                lab['plt_seen'])]
    events = ['pc %X snapshot stop' % lab['pl_crash'],
              'pc %X snapshot stop' % lab['s2d_stop']]
    period = int(fabric / std_hz)
    for at in buttons:
        events += ['cycle %d buttons 1 0' % at,
                   'cycle %d buttons 0 0' % (at + period // 2)]
    (work / 'events.txt').write_text('\n'.join(events) + '\n')
    args += ['--input', str(work / 'events.txt')]
    if irq_bounds:
        args += ['--irq-bounds', irq_bounds]
    try:
        result = bounded.run(args, timeout=RUN_TIMEOUT, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise SR.RunError('a2vm did not finish in %d s' % RUN_TIMEOUT)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise SR.RunError('a2vm failed: %s' % result.stdout[-2000:])
    state = json.loads(state_path.read_text())
    pc = state.get('pc')
    ended = 'stop' if state.get('end') == 'stop-pc' and pc in (
        lab['pl_crash'], lab['s2d_stop']) else '%s at $%04X%s' % (
        state.get('end'), pc or 0,
        (': ' + state['halt']) if state.get('halt') else '')
    snap = work / 'stop.img'
    log: List[Tuple[int, int]] = []
    status = std_end = count = vbl = tics = None
    if snap.exists():
        m = SR.read_snapshot(snap)
        status = m.main[S.PL_STATUS]
        seen = m.main[lab['plt_seen']] | m.main[lab['plt_seen'] + 1] << 8
        for k in range(seen):
            at = log_lo + 4 * k
            log.append((m.main[at] | m.main[at + 1] << 8,
                        m.main[at + 2] | m.main[at + 3] << 8))
        std_end = m.main[lab['plt_std']]
        count = m.main[lab['plt_count']] | m.main[lab['plt_count'] + 1] << 8
        vz = lab['vbl_count']
        vbl = m.main[vz] | m.main[vz + 1] << 8
        t = S.CLOCK['CLK_TICS'] - 0xC000
        tics = int.from_bytes(bytes(m.lc[t:t + 4]), 'little')
    irqs = _irq_times(work / 'ay.log')
    low = state.get('lowest_s', {}).get('ranges', [])
    stack = {'idle': low[0].get('s') if low else None,
             'handler': min((x['s'] for x in low[1:]
                             if x.get('s') is not None), default=None)}
    return ClockRun(state, work, status, ended, log,
                    std_end if std_end is not None else -1, count or 0,
                    irqs, vbl or 0, tics or 0, stack)


def _irq_times(path: Path) -> List[Tuple[int, int]]:
    out, entry = [], None
    if not path.exists():
        return out
    for e in run65.read_log(path):
        if e[0] == 'irq':
            entry = e[3] if e[3] is not None else e[2]
        elif e[0] == 'rti' and entry is not None:
            out.append((entry, e[2] if e[2] is not None else e[1]))
            entry = None
    return out


def clock_problems(r: ClockRun, n: int, std: int) -> List[str]:
    """SCREENS.md 6.5's clock row on one run: stopped by the driver, every
    VBL logged, the standard `std`, the fraction and the tics equal the
    model at every VBL."""
    out = []
    if r.ended != 'stop':
        out.append('the run ended %s' % r.ended)
    if r.status != S.S2S['DONE']:
        out.append('the stop code is %s' % (
            'missing' if r.status is None else '$%02X' % r.status))
    if len(r.log) != n:
        out.append('%d VBLs logged, expected %d' % (len(r.log), n))
    if r.std != std:
        out.append('the standard is $%02X, expected $%02X' % (r.std & 0xFF,
                                                               std))
    bad = 0
    for k, (tics, frac) in enumerate(r.log, 1):
        want_frac, want_tics = clock_at(k, std)
        if (tics, frac) != (want_tics & 0xFFFF, want_frac):
            bad += 1
            if bad <= 3:
                out.append('VBL %d: tics %d, fraction %d; the model %d, %d'
                           % (k, tics, frac, want_tics & 0xFFFF, want_frac))
    if bad > 3:
        out.append('%d VBLs differ from the model' % bad)
    want_tics = clock_at(r.vbl_count, std)[1]
    if r.tics != want_tics:
        out.append('at the stop %d tics for %d VBLs, the model %d' % (
            r.tics, r.vbl_count, want_tics))
    return out


def measured_rate(r: ClockRun, n: int, profile: str) -> Tuple[float, float]:
    """(tics a second, VBLs a second) over the logged VBLs, from the AY
    log's interrupt times (the machine's clock). The last n interrupts
    are the logged VBLs' (plt_clock's start reset the count)."""
    fabric = costs.parameters(profile)['fabric_mhz'] * 1e6
    times = r.irqs[-n:]
    seconds = (times[-1][0] - times[0][0]) / fabric
    tics = (r.log[-1][0] - r.log[0][0]) & 0xFFFF
    return tics / seconds, (n - 1) / seconds


def second_entry_buttons(n: int, profile: str = 'f121',
                         presses: int = 10) -> List[int]:
    """The cycles of `presses` button presses spread over n VBLs, each a
    third of a frame after a VBL (its release half a frame later)."""
    fabric = costs.parameters(profile)['fabric_mhz'] * 1e6
    period = fabric / vbl_hz(STD_PAL)
    step = max(2, n // (presses + 2))
    return [int(period * (8 + step * k + 0.3)) for k in range(presses)]


def second_entry_problems(plain: ClockRun, pressed: ClockRun,
                          profile: str = 'f121') -> List[str]:
    """Interrupts with no VBL pending (the button's) count nothing: the
    pressed run took more interrupts than the plain one, yet logged the
    same clock and stopped at the same VBL (within a quarter frame)."""
    fabric = costs.parameters(profile)['fabric_mhz'] * 1e6
    period = fabric / vbl_hz(STD_PAL)
    out = []
    if len(pressed.irqs) <= len(plain.irqs):
        out.append('no interrupt without a VBL came (%d and %d)' % (
            len(pressed.irqs), len(plain.irqs)))
    if pressed.log != plain.log:
        out.append('the logs differ')
    late = plain.state['cycles'] - pressed.state['cycles']
    if abs(late) > period / 4:
        out.append('the pressed run stopped %.2f frames %s' % (
            abs(late) / period, 'early' if late > 0 else 'late'))
    if pressed.vbl_count != plain.vbl_count or \
            pressed.tics != plain.tics:
        out.append('at the stop %d VBLs and %d tics, the plain run %d, %d'
                   % (pressed.vbl_count, pressed.tics, plain.vbl_count,
                      plain.tics))
    return out


# ---------------------------------------------------------------------------
# Sizes
# ---------------------------------------------------------------------------

CARD_BUDGET = 150               # pl_vbl, the clock, pl_time (SCREENS.md 7.3)


def sizes(part: Path = PART) -> Dict[str, Any]:
    """The bytes of each piece, from the bridge machine's labels (it links
    everything): pl_vbl with pl_vbody, the crash stop and pl_time (the
    budget's 150 B); pl_clkset, pl_detect, pl_wait (the boot's); fx.s's
    card part before them (FXCODE's order in the release: request
    PLBOOT-4); the bridge in $FF00-$FFF9."""
    d = load_linked(part / 'bridge', 'plbr')
    lab, seg = d.labels, d.segments
    fx_lo = seg['FXCODE'][0]
    fx_end = fx_lo + seg['FXCODE'][1]
    br_lo, br_size = seg['PLBRIDGE']
    out = {'irq': lab['pl_clkset'] - lab['pl_vbl'],
           'boot': fx_end - lab['pl_clkset'],
           'fx': lab['pl_vbl'] - fx_lo,
           'fxcode': seg['FXCODE'][1],
           'fxcode_at': fx_lo,
           'bridge': br_size, 'bridge_at': br_lo,
           'room': S.FX_CODE[1] - S.FX_CODE[0]}
    return out


def size_problems(z: Dict[str, Any]) -> List[str]:
    out = []
    if z['irq'] > CARD_BUDGET:
        out.append('pl_vbl, the clock and pl_time: %d B of %d' % (
            z['irq'], CARD_BUDGET))
    if z['fxcode_at'] != S.FX_CODE[0] or \
            z['fxcode_at'] + z['fxcode'] > S.FX_CODE[1]:
        out.append('FXCODE $%04X + %d outside $%04X-$%04X' % (
            z['fxcode_at'], z['fxcode'], S.FX_CODE[0], S.FX_CODE[1] - 1))
    lo, hi = S.PLATFORM_CARD[1], S.PLATFORM_CARD[2]
    if z['bridge_at'] != lo or z['bridge_at'] + z['bridge'] > hi:
        out.append('the bridge $%04X + %d outside $%04X-$%04X' % (
            z['bridge_at'], z['bridge'], lo, hi - 1))
    return out


# ---------------------------------------------------------------------------
# The music's runs
# ---------------------------------------------------------------------------

MUSIC_PROFILE = 'f121+phasor+window32'     # the Doom profile (NATIVE.md 15.1)
LC_LO = 0xE900                  # sound.lc's first byte


class MusicRun(NamedTuple):
    run: Any                    # run65.Run: the AY log's groups, state.json
    stack: Dict[str, Optional[int]]


def song_paths() -> List[Path]:
    return sorted(SONGS.glob('D_*.native12.ay'))


def music_run(work: Path, song: bytes, seconds: float, ntsc: bool = False,
              profile: str = MUSIC_PROFILE, part: Path = PART,
              irq_bounds: Optional[str] = IRQ_BOUNDS,
              std: Optional[int] = None) -> MusicRun:
    """S2's driver plays `song` from VBL 0 (looping) with pl_vbl the
    handler; the clock's step and standard set as pl_clkset would (std:
    PAL or NTSC as `ntsc`, unless given)."""
    d = load_linked(part / 'music', 'sound')
    lab = d.labels
    work.mkdir(parents=True, exist_ok=True)
    main = bytearray(d.file('main'))
    main[lab['drv_mode'] - DRV_MAIN] = run65.IDLE_MODE
    main[lab['drv_probe'] - DRV_MAIN] = 0
    table = run65.actions_bytes([run65.start_action(0, 0, ntsc=ntsc)])
    at = lab['drv_actions'] - DRV_MAIN
    main[at:at + len(table)] = table
    std = (STD_NTSC if ntsc else STD_PAL) if std is None else std
    image = bytearray(b'A2VMIMG1')

    def record(kind, bank, address, data):
        image.extend(run65.struct.pack('<BBHI', kind, bank, address,
                                       len(data)))
        image.extend(data)
    record(2, 0, LC_LO, d.file('lc'))
    clock = bytearray(16)               # CLK_STEP, CLK_STD
    step = TIC_FRAC[std]
    at = S.CLOCK['CLK_STEP'] - 0xE403
    clock[at:at + 2] = step.to_bytes(2, 'little')
    clock[S.CLOCK['CLK_STD'] - 0xE403] = std
    record(2, 0, 0xE403, bytes(clock))
    # the effect player as fx_init leaves it with the effects on (S2's
    # driver does not call it): FX_ON 1, FX_HOLD 0, FX_INVAL 1, the tempo
    # 0, and the voices idle (the card's other bytes are 0 here)
    fx = bytearray(S.FX_RING - min(S.FX.values()))
    fx[S.FX['FX_ON'] - min(S.FX.values())] = 1
    fx[S.FX['FX_INVAL'] - min(S.FX.values())] = 1
    record(2, 0, min(S.FX.values()), bytes(fx))
    record(0, 0, DRV_MAIN, bytes(main))
    record(1, run65.SONG_BANK0, run65.SONG_ADDRESS, bytes(song))
    (work / 'sound.img').write_bytes(bytes(image))
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    variants = profile.split('+')
    name = '+'.join(variants + (['ntsc'] if ntsc and 'ntsc' not in variants
                                else []))
    (work / 'cost.txt').write_text(costs.text(name))
    fabric = costs.parameters(name)['fabric_mhz'] * 1e6
    hand = [(d.segments[s][0], d.segments[s][0] + d.segments[s][1] - 1)
            for s in ('FXCODE', 'SNDCODE')]
    idle = lab['drv_idle']
    lowest = [(idle, idle + 5)] + hand
    args = [str(A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--via-ora-nh',
            '--image', str(work / 'sound.img'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--reg', 'pc=%X' % lab['drv_start'], '--reg', 's=FF',
            '--reg', 'p=34',
            '--cost', str(work / 'cost.txt'), '--cost-timed',
            '--cycles', str(int(round(seconds * fabric))),
            '--ay-log', str(work / 'ay.log'),
            '--state', str(work / 'state.json'),
            '--lowest-s-in', ','.join('%X-%X' % r for r in lowest),
            '--stop-pc', '%X' % lab['drv_halt'],
            '--stop-pc', '%X' % lab['pl_crash'],
            '--idle', '%X:vbl:eq=%X,%X' % (idle, lab['vbl_count'],
                                           lab['drv_seen'])]
    if irq_bounds:
        args += ['--irq-bounds', irq_bounds]
    try:
        result = bounded.run(args, timeout=RUN_TIMEOUT, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise SR.RunError('a2vm did not finish in %d s' % RUN_TIMEOUT)
    state_path = work / 'state.json'
    if result.returncode or not state_path.exists():
        halt = ''
        if state_path.exists():
            halt = json.loads(state_path.read_text()).get('halt', '')
        raise SR.RunError('a2vm failed: %s\n%s' % (halt,
                                                   result.stdout[-2000:]))
    out = run65.Run(work, lab)
    if out.state['end'] != 'cycles':
        raise SR.RunError('the run ended early (%s at $%04X)' % (
            out.state['end'], out.state['pc']))
    low = out.state.get('lowest_s', {}).get('ranges', [])
    stack = {'idle': low[0].get('s') if low else None,
             'handler': min((x['s'] for x in low[1:]
                             if x.get('s') is not None), default=None)}
    return MusicRun(out, stack)


def s2_music_run(work: Path, song: bytes, seconds: float, ntsc: bool = False,
                 profile: str = MUSIC_PROFILE) -> Any:
    """S2's own build (build/sound65: snd_vbl the handler), the
    reference."""
    variants = [v for v in profile.split('+')[1:] if v != 'ntsc']
    return run65.run(run65.Player65(SOUND65), [song],
                     [run65.start_action(0, 0, ntsc=ntsc)], seconds, work,
                     ntsc=ntsc, variants=tuple(variants),
                     profile=profile.split('+')[0])


def music_problems(mine: Any, s2: Any) -> List[str]:
    """pl_vbl's AY log equal to S2's: every group (before the first
    interrupt, each interrupt's burst, the main loop after each), write
    for write, and the chips at the end."""
    out = []
    if len(mine.bursts) != len(s2.bursts):
        out.append('%d interrupts, S2 %d' % (len(mine.bursts),
                                             len(s2.bursts)))
    n = min(len(mine.main), len(s2.main))
    for k in range(n):
        if mine.main[k] != s2.main[k]:
            out.append('main loop after interrupt %d: %s' % (
                k, run65.first_difference(mine.main[k], s2.main[k])))
            break
        if k < min(len(mine.bursts), len(s2.bursts)) and \
                mine.bursts[k] != s2.bursts[k]:
            out.append('interrupt %d: %s' % (k + 1, run65.first_difference(
                mine.bursts[k], s2.bursts[k])))
            break
    if mine.partial != s2.partial:
        out.append('the interrupt the run cut: %s, S2 %s' % (
            (mine.partial or [])[:3], (s2.partial or [])[:3]))
    if mine.state['phasor'] != s2.state['phasor']:
        out.append('the Phasor at the end differs')
    return out


def irq_stats(times: Sequence[Tuple[int, int]], profile: str
              ) -> Dict[str, float]:
    """The interrupts' lengths: worst, median (us), the share of the
    machine's time (the cost a second)."""
    fabric = costs.parameters(profile)['fabric_mhz']
    lengths = sorted(b - a for a, b in times)
    if not lengths:
        return {}
    span = times[-1][1] - times[0][0]
    return {'n': len(lengths), 'worst_us': lengths[-1] / fabric,
            'median_us': lengths[len(lengths) // 2] / fabric,
            'p99_us': lengths[min(len(lengths) - 1,
                                  int(len(lengths) * 0.99))] / fabric,
            'share': sum(lengths) / span if span else 0.0}


# ---------------------------------------------------------------------------
# The bridge
# ---------------------------------------------------------------------------

BRIDGE_BOUNDS = '00D8-01FF,C008-C009,C0A0-C0AF,C400-C4FF,E000-FFFF'
ALTZP_COUNT = 0x10              # pl_bt.s's count in the aux zero page
MARKERS = bytes(0xB0 + k for k in range(8))     # main $01F8-$01FF


class BridgeRun(NamedTuple):
    state: Dict[str, Any]
    ended: str
    main: bytearray
    lc: bytearray
    aux0: bytearray
    aux_card0: bytes            # the aux card as loaded (bank 0 $C000-$FFFF)
    irqs: int
    stack: Dict[str, Optional[int]]


def bridge_run(work: Path, frames: int = 100, brkat: int = 0,
               part: Path = PART, irq_bounds: Optional[str] = BRIDGE_BOUNDS
               ) -> BridgeRun:
    """The synthetic machine for `frames` VBLs at a2vm's --speed 1 (17,030
    cycles a VBL), no cost model; brkat: pl_bt.s's bt_brkat."""
    d = load_linked(part / 'bridge', 'plbr')
    lab = d.labels
    work.mkdir(parents=True, exist_ok=True)
    main = bytearray(d.file('main'))
    main[lab['bt_brkat'] - DRV_MAIN] = brkat
    lc = bytearray(0x4000)
    data = d.file('lc')
    lc[LC_LO - 0xC000:LC_LO - 0xC000 + len(data)] = data
    aux_card = bytearray(0x4000)        # only the bridge and its vectors
    bridge = S.PLATFORM_CARD[1] - 0xC000, S.PLATFORM_CARD[2] - 0xC000
    aux_card[bridge[0]:bridge[1]] = lc[bridge[0]:bridge[1]]
    aux_card[0x3FFA:0x4000] = d.file('auxvec')
    recs = [(0, 0, 0x0000, bytes(0xC000)),
            (0, 0, DRV_MAIN, bytes(main)),
            (2, 0, 0xC000, bytes(lc)),
            (1, 0, 0xC000, bytes(aux_card))]
    (work / 'image.bin').write_bytes(lrun.RC.image_bytes(recs))
    (work / 'rom.bin').write_bytes(bytes(0x4000))
    hand = [(d.segments[s][0], d.segments[s][0] + d.segments[s][1] - 1)
            for s in ('FXCODE', 'SNDCODE', 'PLBRIDGE')]
    loop = (lab['bt_loop'], lab['bt_fail'])
    args = [str(A2VM), '--rom', str(work / 'rom.bin'),
            '--core', 'w65c02s', '--via-ora-nh', '--speed', '1',
            '--image', str(work / 'image.bin'),
            '--switch', 'lc_read=1', '--switch', 'lc_write=1',
            '--reg', 'pc=%X' % lab['bt_start'], '--reg', 's=FF',
            '--reg', 'p=34',
            '--cycles', str(17030 * frames + 5000),
            '--state', str(work / 'state.json'),
            '--lowest-s-in', ','.join('%X-%X' % r for r in [loop] + hand),
            '--snapshot-dir', str(work), '--final-snapshot',
            '--stop-pc', '%X' % lab['bt_fail'],
            '--stop-pc', '%X' % lab['pl_crash']]
    if irq_bounds:
        args += ['--irq-bounds', irq_bounds]
    try:
        result = bounded.run(args, timeout=RUN_TIMEOUT, max_bytes=MAX_FILE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True)
    except subprocess.TimeoutExpired:
        raise SR.RunError('a2vm did not finish in %d s' % RUN_TIMEOUT)
    state_path = work / 'state.json'
    if not state_path.exists():
        raise SR.RunError('a2vm failed: %s' % result.stdout[-2000:])
    state = json.loads(state_path.read_text())
    pc = state.get('pc')
    names = {lab['bt_fail']: 'bt_fail', lab['pl_crash']: 'pl_crash'}
    ended = names.get(pc, '?') if state.get('end') == 'stop-pc' else \
        '%s at $%04X%s' % (state.get('end'), pc or 0,
                           (': ' + state['halt']) if state.get('halt')
                           else '')
    ram = (work / 'final.ram').read_bytes()
    mainr = bytearray(ram[:0x10000])
    lcr = bytearray(ram[0x10000:0x14000])
    aux0 = bytearray(ram[0x15000:0x25000])
    low = state.get('lowest_s', {}).get('ranges', [])
    stack = {'loop': low[0].get('s') if low else None,
             'handler': min((x['s'] for x in low[1:]
                             if x.get('s') is not None), default=None)}
    return BridgeRun(state, ended, mainr, lcr, aux0, bytes(aux_card),
                     int(state.get('irqs', 0)), stack)


def bridge_problems(r: BridgeRun, part: Path = PART) -> List[str]:
    """The bridge's run: the loop ran on the aux zero page and stack, every
    interrupt went through the bridge to the main handler (the VBL count,
    the tics as the model's), the main stack's markers, the aux zero page's
    IRQ bytes and the aux card unchanged."""
    d = load_linked(part / 'bridge', 'plbr')
    out = []
    if r.state.get('end') != 'cycles':
        out.append('the run ended %s' % r.ended)
    vz = d.labels['vbl_count']
    vbl = r.main[vz] | r.main[vz + 1] << 8
    if vbl == 0 or vbl != r.irqs:
        out.append('%d VBLs counted for %d interrupts' % (vbl, r.irqs))
    t = S.CLOCK['CLK_TICS'] - 0xC000
    tics = int.from_bytes(bytes(r.lc[t:t + 4]), 'little')
    if tics != clock_at(vbl, STD_PAL)[1]:
        out.append('%d tics for %d VBLs, the model %d' % (
            tics, vbl, clock_at(vbl, STD_PAL)[1]))
    count = r.aux0[ALTZP_COUNT] | r.aux0[ALTZP_COUNT + 1] << 8
    if count == 0:
        out.append('the loop counted nothing in the aux zero page')
    if r.main[ALTZP_COUNT:ALTZP_COUNT + 2] != b'\0\0':
        out.append('the loop\'s count reached the main zero page')
    if bytes(r.main[0x01F8:0x0200]) != MARKERS:
        out.append('the main stack\'s markers changed: %s' %
                   bytes(r.main[0x01F8:0x0200]).hex())
    if any(r.aux0[S.ZP_IRQ[0]:S.ZP_IRQ[1]]):
        out.append('the handler wrote the aux zero page\'s $D8-$FF')
    if bytes(r.aux0[0xC000:0x10000]) != r.aux_card0:
        out.append('the aux card changed')
    return out


# ---------------------------------------------------------------------------
# The checkpoint
# ---------------------------------------------------------------------------

def checkpoint(seconds: float = 60.0, music_seconds: float = 20.0,
               songs: Optional[int] = None, jobs: int = 2,
               out=print) -> List[str]:
    """Every run of the part's checkpoint, its report printed; returns the
    problems."""
    problems: List[str] = ['model: ' + p for p in check_model()]
    work = Path(tempfile.mkdtemp(prefix='tmp-m11-plclock-', dir=str(BUILD)))
    try:
        out('== the clock: %g s of machine time' % seconds)
        for profile, std in (('f121', STD_PAL), ('f121+ntsc', STD_NTSC)):
            n = int(seconds * vbl_hz(std))
            r = clock_run(work / ('clock-' + profile), n, DETECT, profile)
            p = clock_problems(r, n, std)
            problems += ['clock %s: %s' % (profile, x) for x in p]
            rate, vhz = measured_rate(r, n, profile)
            if not RATE_RANGE[0] <= rate <= RATE_RANGE[1]:
                problems.append('clock %s: %.4f tics a second' % (profile,
                                                                   rate))
            st = irq_stats(r.irqs[-n:], profile)
            out('%-10s detected %s (%d bus cycles a VBL), %d VBLs, %d tics'
                ' (the model %d), %.4f tics/s, %.4f VBL/s; idle IRQ %.2f us'
                ' (worst %.2f), stack %s B; %s' % (
                    profile, NAMES.get(r.std, '?'), r.count, len(r.log),
                    r.tics, clock_at(r.vbl_count, std)[1], rate, vhz,
                    st.get('median_us', 0), st.get('worst_us', 0),
                    _depth(r.stack), 'ok' if not p else p[0]))
        n = 150
        plain = clock_run(work / 'se-plain', n, STD_PAL, 'f121',
                          mode=MODE_VBL_BUTTON, idle=False)
        pressed = clock_run(work / 'se-pressed', n, STD_PAL, 'f121',
                            mode=MODE_VBL_BUTTON, idle=False,
                            buttons=second_entry_buttons(n))
        p = clock_problems(plain, n, STD_PAL) + \
            clock_problems(pressed, n, STD_PAL) + \
            second_entry_problems(plain, pressed)
        problems += ['second entry: %s' % x for x in p]
        out('second entry: %d interrupts with no VBL pending among %d; '
            'the clock unchanged: %s' % (len(pressed.irqs) - len(plain.irqs),
                                         len(pressed.irqs),
                                         'yes' if not p else p[0]))
        r = clock_run(work / 'clock-fastpath', 100, DETECT, 'fastpath')
        st = irq_stats(r.irqs[-100:], 'fastpath')
        out('fastpath   idle IRQ %.2f us (worst %.2f), stack %s B' % (
            st.get('median_us', 0), st.get('worst_us', 0), _depth(r.stack)))
        out('== the music through pl_vbl: %g s of each song, %s' % (
            music_seconds, MUSIC_PROFILE))
        paths = song_paths()[:songs] if songs else song_paths()

        def one(path: Path):
            data = path.read_bytes()
            name = path.name.split('.')[0]
            mine = music_run(work / ('m-' + name), data, music_seconds)
            ref = s2_music_run(work / ('s-' + name), data, music_seconds)
            return name, mine, ref
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(one, paths))
        worst = (0.0, '')
        for name, mine, ref in results:
            p = music_problems(mine.run, ref)
            problems += ['music %s: %s' % (name, x) for x in p]
            st = irq_stats(mine.run.times, MUSIC_PROFILE)
            st2 = irq_stats(ref.times, MUSIC_PROFILE)
            depth = _depth(mine.stack)
            if depth is None or depth > S.IRQ_STACK:
                problems.append('music %s: the interrupt\'s stack %s B' % (
                    name, depth))
            if st['worst_us'] > worst[0]:
                worst = (st['worst_us'], name)
            out('%-9s %4d interrupts, AY log %s; worst %.1f us (S2 %.1f),'
                ' median %.1f us (S2 %.1f), %.2f%% of the time; stack %s B'
                % (name, len(mine.run.bursts), 'equal' if not p else p[0],
                   st['worst_us'], st2['worst_us'], st['median_us'],
                   st2['median_us'], 100 * st['share'], depth))
        out('worst interrupt with music alone: %.1f us (%s)' % worst)
        worst512 = (0.0, '')
        for path in paths:
            name = path.name.split('.')[0]
            mine = music_run(work / ('w-' + name), path.read_bytes(),
                             music_seconds, profile='f121+phasor')
            st = irq_stats(mine.run.times, 'f121+phasor')
            if st['worst_us'] > worst512[0]:
                worst512 = (st['worst_us'], name)
        out('the same in f121+phasor (window 512): %.1f us (%s)' % worst512)
        out('== the bridge')
        r = bridge_run(work / 'bridge')
        p = bridge_problems(r)
        problems += ['bridge: %s' % x for x in p]
        out('%d interrupts through the bridge, %s; aux stack from $%02X, '
            'handler lowest S $%02X' % (r.irqs, 'ok' if not p else p[0],
                                        r.stack['loop'] or 0,
                                        r.stack['handler'] or 0))
        r = bridge_run(work / 'bridge-brk', frames=40, brkat=1)
        if r.ended != 'pl_crash':
            problems.append('bridge: a BRK with ALTZP on ended %s' % r.ended)
        out('a BRK with ALTZP on: %s' % r.ended)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    z = sizes()
    problems += ['sizes: %s' % x for x in size_problems(z)]
    out('== sizes: pl_vbl, the clock, pl_time %d B of %d; pl_clkset, '
        'pl_detect, pl_wait %d B; fx.s\'s card part %d B; FXCODE %d of '
        '%d B; '
        'the bridge %d B at $%04X' % (z['irq'], CARD_BUDGET, z['boot'],
                                     z['fx'], z['fxcode'], z['room'],
                                     z['bridge'], z['bridge_at']))
    out('problems: %d' % len(problems))
    for p in problems:
        out('  ' + p)
    return problems


def _depth(stack: Dict[str, Optional[int]]) -> Optional[int]:
    """The interrupt's stack depth: S where it came less the lowest S in
    the handler's code. The interrupts land in the idle loop, which pushes
    nothing, so the lowest S a2vm gives for the loop's range is an
    interrupt's entry, 3 bytes (P and the return) below the loop's S."""
    top = stack.get('idle')
    low = stack.get('handler')
    if top is None or low is None:
        return None
    return top + 3 - low


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--model', action='store_true')
    parser.add_argument('--cfg', nargs=2, metavar=('KIND', 'OUT'))
    parser.add_argument('--checkpoint', action='store_true')
    parser.add_argument('--seconds', type=float, default=60.0)
    parser.add_argument('--music-seconds', type=float, default=20.0)
    parser.add_argument('--songs', type=int)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args(argv)
    if args.cfg:
        kind, path = args.cfg
        if kind not in ('music', 'bridge'):
            parser.error('--cfg music or bridge')
        text = cfg_text(kind)
        path = Path(path)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(text)
        tmp.replace(path)
        return 0
    if args.model:
        for std in STANDARDS:
            print('%-4s VBL %.4f Hz, fraction %d (the rates give %d), '
                  '%.4f tics a second' % (NAMES[std], vbl_hz(std),
                                          TIC_FRAC[std], tic_frac(std),
                                          tic_rate(std)))
        p = check_model()
        print('model: %s' % ('ok' if not p else '; '.join(p)))
        return 1 if p else 0
    if args.checkpoint:
        if not args.no_build:
            make()
        p = checkpoint(args.seconds, args.music_seconds, args.songs,
                       args.jobs)
        return 1 if p else 0
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
