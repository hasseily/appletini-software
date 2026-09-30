#!/usr/bin/env python3
"""All songs: converter and player statistics, song files and WAV renders.

Usage:  python3 tools/sound/report.py [--render] [--update-readme]
                [--seconds 60] [--jobs N] [--wad FILE]

Converts every song of the WAD (layout native12, the only one), runs the
player model on a PAL and an NTSC machine in native mode, and prints
Markdown tables. --update-readme writes them between the report markers
of tools/sound/README.md. --render also writes build/sound/SONG.wav (PAL,
stereo with the menu's default pans) for the first --seconds seconds of
each song, or the whole song and one second of release when it is
shorter, and the song files build/sound/SONG.native12.ay, with at most
--jobs (default 4) renders at a time.

Bus cost columns use native-sound.md 2.3: on F1.2.1 (slot-4 slowdown
window 512) a burst costs a 504 us tail and a write 40.4 us; with the
proposed FW-S1 a write costs about 8.4 us and a burst no tail.

The loudness table gives each song's gain (mus2ay.song_gain) and, at
gain 0 and as shipped, the AY levels of its first --seconds seconds in
the player model (PAL): the loudest level of a melodic voice, the mean
level of the melodic voices that sound and of all the music voices that
sound (a drum on the chip's envelope counts the envelope's level, from
15 down to 0 over its recipe's decay), and the share of the interrupts
with a melodic voice sounding whose loudest is at 15. "Clamped" is the
share of the melodic held note time the gain brings below attenuation 0
(mus2ay.clamped_share): it plays at level 15 and loses its dynamics.
The drum columns compare the whole song at gain 0 and as shipped: the
share of drum hits on the chip's envelope, and the drums against the
melody, the mean change of a drum hit's peak less the mean change of a
melodic note's, in dB at the AY's levels (peak_changes).
"""

import argparse
import multiprocessing
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import ayrender, mus, mus2ay, player, tables  # noqa: E402

README = Path(__file__).resolve().parent / 'README.md'
BEGIN = '<!-- report:begin (python3 tools/sound/report.py --update-readme) -->'
END = '<!-- report:end -->'
TAIL_US = 512 * 1e6 / tables.PAL_NATIVE.bus_hz
WRITE_US_F121 = tables.CYCLES_PER_WRITE * 1e6 / tables.PAL_NATIVE.bus_hz
WRITE_US_FWS1 = 8.4


def percentile(values, q):
    """The value at index int(q * n) of the sorted values (the design
    prototype's rule), 0 for none."""
    s = sorted(values)
    if not s:
        return 0
    return s[min(len(s) - 1, int(q * len(s)))]


def burst_stats(bursts, machine):
    counts = [len(b) for b in bursts]
    busy = [c for c in counts if c]
    seconds = len(counts) / tables.vbl_hz(machine)
    writes = sum(counts)
    return {
        'interrupts': len(counts),
        'writes': writes,
        'writes_s': writes / seconds,
        'bursts_s': len(busy) / seconds,
        'mean': writes / len(counts),
        'p99': percentile(counts, 0.99),
        'mean_busy': writes / len(busy) if busy else 0.0,
        'p99_busy': percentile(busy, 0.99),
        'max': max(counts) if counts else 0,
        'f121_ms': (len(busy) * TAIL_US + writes * WRITE_US_F121)
        / seconds / 1000,
        'fws1_ms': writes * WRITE_US_FWS1 / seconds / 1000,
    }


class _EnvelopeClock(player.Player):
    """The player model, noting for each drum voice on the chip's envelope
    the interrupt its hit started and its recipe's decay (the one-shot
    decay lasts 256 x period / PSG clock): the player itself keeps such a
    voice at level $10 until its next hit or cut."""

    def __init__(self, song, machine):
        super().__init__(song, machine)
        self.count = 0
        self.decay = tables.vbl_hz(machine) * 256 / tables.psg_clock(machine)
        self.hw = {}

    def drum_start(self, v, index):
        super().drum_start(v, index)
        if self.phase[v] == player.DRUM_HW:
            self.hw[v] = (self.count,
                          self.song.drums[index].period * self.decay)

    def envelope_level(self, v):
        """The AY envelope's level of drum voice v at the start of this
        interrupt's frame: 15 at the hit, one step down each 1/16 of the
        decay, 0 after it."""
        start, frames = self.hw[v]
        return max(0, 15 - int(16 * (self.count - start) / frames))


def level_stats(song_file, machine, seconds):
    """AY levels of the first `seconds` of a song in the player model:
    the loudest level of a melodic voice, the mean level of the melodic
    voices that sound and of all the music voices that sound (a drum on
    the chip's envelope counts the envelope's level, _EnvelopeClock), and
    the share of the interrupts with a melodic voice sounding whose
    loudest melodic voice is at 15."""
    p = _EnvelopeClock(song_file, machine)
    p.reset()
    melodic = len(song_file.layout.melodic)
    top = frames = frames15 = 0
    total = sounding = mtotal = msounding = 0
    for p.count in range(int(seconds * tables.vbl_hz(machine))):
        p.interrupt()
        loudest = 0
        for v, (chip, channel) in enumerate(p.slots):
            level = p.want[chip][8 + channel]
            if level & 0x10:
                level = p.envelope_level(v)
            if level:
                total += level
                sounding += 1
                if v < melodic:
                    mtotal += level
                    msounding += 1
                    loudest = max(loudest, level)
        if loudest:
            frames += 1
            frames15 += loudest == 15
            top = max(top, loudest)
    return {'top': top, 'mean': total / sounding if sounding else 0.0,
            'melodic': mtotal / msounding if msounding else 0.0,
            'share15': frames15 / frames if frames else 0.0}


def note_peaks(song_file):
    """[(drum, peak dB)] of every note on and drum hit of a stream, in
    order: the AY level its envelope starts from (a melodic note's attack
    reaches its note attenuation; a hit of attenuation HW_DRUM_ATT or less
    plays on the chip's envelope from level 15, a softer one decays from
    the level of its attenuation), in dB below full, None when silent."""
    att = {}
    out = []
    for _, c, v, ops in player.decode_stream(song_file.stream):
        if c in (player.NOTE_ATT, player.NOTE_ATT_ENV):
            att[v] = ops[1]
        elif c == player.ATTENUATION:
            att[v] = ops[0]
        if c <= player.NOTE_ATT_ENV:
            level = tables.LEVEL[att.get(v, 0)]
            out.append((False, tables.AY_DB[level] if level else None))
        elif c == player.DRUM_HIT:
            level = 15 if ops[1] <= tables.HW_DRUM_ATT else \
                tables.LEVEL[ops[1]]
            out.append((True, tables.AY_DB[level] if level else None))
    return out


def peak_changes(plain, shipped):
    """Gain 0 (`plain`) against the shipped song file of the same song:
    {'drum_db', 'melodic_db'}, the mean change of the peak of a drum hit
    and of a melodic note that sound in both, and {'env0', 'env'}, the
    share of drum hits on the chip's envelope in each (None without
    hits). The two files hold the same notes and hits in the same order
    (the voices do not depend on loudness)."""
    a, b = note_peaks(plain), note_peaks(shipped)
    if [d for d, _ in a] != [d for d, _ in b]:
        raise ValueError('the two song files hold different notes')
    changes = {True: [], False: []}
    for (drum, p0), (_, p1) in zip(a, b):
        if p0 is not None and p1 is not None:
            changes[drum].append(p1 - p0)

    def mean(xs):
        return sum(xs) / len(xs) if xs else None

    def on_envelope(song_file):
        hits = [ops[1] for _, c, _, ops in
                player.decode_stream(song_file.stream)
                if c == player.DRUM_HIT]
        return mean([h <= tables.HW_DRUM_ATT for h in hits])
    return {'drum_db': mean(changes[True]),
            'melodic_db': mean(changes[False]),
            'env0': on_envelope(plain), 'env': on_envelope(shipped)}


def song_stats(song, instruments, machines, seconds):
    """Converter counts and, for each machine, burst statistics over the
    whole song (no loop) and one second after its end; the levels of the
    first `seconds` on the first machine, as shipped and at gain 0."""
    song_file, counts = mus2ay.convert(song, instruments)
    plain, _ = mus2ay.convert(song, instruments, gain=0)
    probe = mus2ay.Converter(song, instruments)
    probe.convert()
    out = {'counts': counts, 'file': song_file,
           'stream_bytes': len(song_file.stream),
           'file_bytes': len(song_file.to_bytes()),
           'loud': mus2ay.loud_attenuation(probe.loudness),
           'clamped': mus2ay.clamped_share(probe.loudness, counts['gain']),
           'peaks': peak_changes(plain, song_file),
           'levels': level_stats(song_file, machines[0], seconds),
           'levels0': level_stats(plain, machines[0], seconds)}
    for machine in machines:
        init, bursts = player.run(song_file, machine)
        out[machine.name] = burst_stats(bursts, machine)
        out[machine.name]['init'] = len(init)
    return out


def collect(wad, seconds=60.0):
    instruments = mus2ay.load_instruments(wad)
    rows = []
    for name in wad.songs():
        song = wad.song(name)
        c = song.counts()
        row = {'name': name, 'bytes': song.size, 'seconds': song.seconds,
               'events': len(song.events), 'on': c['on']}
        row['native12'] = song_stats(song, instruments,
                                     (tables.PAL_NATIVE, tables.NTSC_NATIVE),
                                     seconds)
        rows.append(row)
    return rows


def tables_markdown(rows, seconds=60.0):
    lines = []
    add = lines.append
    add('Native mode, 12 voices (7 melodic, 2 drums, 3 effects left free), '
        'PAL //e: interrupts at %.3f Hz, %d or %d MUS ticks each.'
        % (tables.vbl_hz(tables.PAL_NATIVE),
           tables.tempo(tables.PAL_NATIVE)[0],
           tables.tempo(tables.PAL_NATIVE)[0] + 1))
    add('')
    add('| Song | MUS bytes | Seconds | Events | Notes | Drum hits | Voices '
        'used (most held) | Steals | Drum steals | Release cuts | Stream '
        'bytes | Stream B/s | File bytes | Writes/s | Writes/interrupt mean '
        '| p99 | p99 of bursts | Max | F1.2.1 ms/s | FW-S1 ms/s |')
    add('| --- |' + ' ---: |' * 19)
    total = {'bytes': 0, 'stream': 0, 'file': 0}
    for r in rows:
        s = r['native12']
        c = s['counts']
        b = s['pal-native']
        add('| %s | %d | %.1f | %d | %d | %d | %d (%d) | %d | %d | %d | %d | '
            '%.0f | %d | %.0f | %.2f | %d | %d | %d | %.1f | %.2f |' % (
                r['name'], r['bytes'], r['seconds'], r['events'],
                c['notes'], c['drum hits'], c['voices used'],
                c['max voices'], c['steals'], c['drum steals'],
                c['release cuts'], s['stream_bytes'],
                s['stream_bytes'] / r['seconds'], s['file_bytes'],
                b['writes_s'], b['mean'], b['p99'], b['p99_busy'], b['max'],
                b['f121_ms'], b['fws1_ms']))
        total['bytes'] += r['bytes']
        total['stream'] += s['stream_bytes']
        total['file'] += s['file_bytes']
    add('| All | %d | | | | | | | | | %d | | %d | | | | | | | |'
        % (total['bytes'], total['stream'], total['file']))
    add('')
    add('NTSC //e (%.3f Hz), native mode: writes/s and p99 of bursts per '
        'song: %s.' % (tables.vbl_hz(tables.NTSC_NATIVE), ', '.join(
            '%s %.0f/%d' % (r['name'], r['native12']['ntsc-native']
                            ['writes_s'], r['native12']['ntsc-native']
                            ['p99_busy']) for r in rows)))
    add('')
    add('Loudness: the song gain (percentile %g of the melodic note time, '
        'boost %+.1f dB, cap %+.1f dB); the AY levels of the first %.0f s '
        '(PAL) and the drums over the whole song, at gain 0 and as shipped.'
        % (mus2ay.PERCENTILE, mus2ay.BOOST * tables.ATT_UNIT_DB,
           mus2ay.CAP * tables.ATT_UNIT_DB, seconds))
    add('')
    add('| Song | Loud notes at | Gain | Clamped | Loudest level | Mean '
        'level, melodic | Mean level, all | Interrupts at 15 | Hits on the '
        'envelope | Drums against melody |')
    add('| --- |' + ' ---: |' * 9)

    def signed(x):
        return '-' if x is None else '%+.1f dB' % x

    def share(x):
        return '-' if x is None else '%.0f%%' % (100 * x)
    for r in rows:
        s = r['native12']
        a, b = s['levels0'], s['levels']
        k = s['peaks']
        balance = None if k['drum_db'] is None or k['melodic_db'] is None \
            else k['drum_db'] - k['melodic_db']
        add('| %s | %s | %+.1f dB | %.0f%% | %d to %d | %.1f to %.1f | '
            '%.1f to %.1f | %.0f%% to %.0f%% | %s to %s | %s |'
            % (r['name'], '-' if s['loud'] is None else
               '%.1f dB' % (-s['loud'] * tables.ATT_UNIT_DB),
               s['counts']['gain'] * tables.ATT_UNIT_DB,
               100 * s['clamped'], a['top'], b['top'],
               a['melodic'], b['melodic'], a['mean'], b['mean'],
               100 * a['share15'], 100 * b['share15'],
               share(k['env0']), share(k['env']), signed(balance)))
    return '\n'.join(lines)


def update_readme(text):
    content = README.read_text()
    head, _, rest = content.partition(BEGIN)
    _, _, tail = rest.partition(END)
    if not rest or END not in rest:
        raise SystemExit('README.md has no report markers')
    README.write_text(head + BEGIN + '\n' + text + '\n' + END + tail)


def render_song(job):
    name, data, seconds, out_dir = job
    song_file = player.SongFile.from_bytes(data)
    machine = tables.PAL_NATIVE
    init, bursts = player.run(song_file, machine,
                              seconds=seconds + 1.0 / tables.vbl_hz(machine))
    log = player.register_log(init, bursts, machine)
    result = ayrender.render(log, machine.bus_hz, machine.psg_multiplier,
                             seconds)
    path = Path(out_dir) / ('%s.wav' % name)
    mix = max(max(result.left, default=0), max(result.right, default=0))
    peak = ayrender.write_wav(path, result)
    return name, seconds, peak, result.clipped, mix / 32768.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--wad', default=str(mus.WAD_PATH))
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--update-readme', action='store_true')
    parser.add_argument('--seconds', type=float, default=60.0)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--out', default=str(mus2ay.BUILD_SOUND))
    args = parser.parse_args(argv)
    wad = mus.Wad.open(args.wad)
    rows = collect(wad, args.seconds)
    text = tables_markdown(rows, args.seconds)
    print(text)
    if args.update_readme:
        update_readme(text)
        print('\nupdated %s' % README)
    if args.render:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        jobs = []
        for r in rows:
            (out / mus2ay.song_file_name(r['name'])).write_bytes(
                r['native12']['file'].to_bytes())
            seconds = min(args.seconds, r['seconds'] + 1.0)
            jobs.append((r['name'], r['native12']['file'].to_bytes(),
                         seconds, str(out)))
        workers = max(1, min(args.jobs, len(jobs)))
        with multiprocessing.Pool(workers) as pool:
            for name, seconds, peak, clipped, mix in pool.imap(render_song,
                                                                jobs):
                print('%s/%s.wav: %.1f s, peak %d, %d saturated samples, '
                      'the mix at most %.0f%% of its saturation'
                      % (out, name, seconds, peak, clipped, 100 * mix))
    return 0


if __name__ == '__main__':
    sys.exit(main())
