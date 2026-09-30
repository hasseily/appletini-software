#!/usr/bin/env python3
"""All songs: converter and player statistics, song files and WAV renders.

Usage:  python3 tools/sound/report.py [--render] [--update-readme]
                [--seconds 60] [--jobs N] [--wad FILE]

Converts every song of the WAD for both layouts, runs the player model on
a PAL machine (native12 in native mode, mb6 in Mockingboard mode) and on
an NTSC one, and prints Markdown tables. --update-readme writes them
between the report markers of tools/sound/README.md. --render also writes
build/sound/SONG.wav (native12, PAL, stereo with the menu's default pans)
for the first --seconds seconds of each song, or the whole song and one
second of release when it is shorter, and the song files
build/sound/SONG.native12.ay and SONG.mb6.ay.

Bus cost columns use native-sound.md 2.3: on F1.2.1 (slot-4 slowdown
window 512) a burst costs a 504 us tail and a write 40.4 us; with the
proposed FW-S1 a write costs about 8.4 us and a burst no tail.
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


def song_stats(song, instruments, layout, machines):
    """Converter counts and, for each machine, burst statistics over the
    whole song (no loop) and one second after its end."""
    song_file, counts = mus2ay.convert(song, instruments, layout)
    out = {'counts': counts, 'file': song_file,
           'stream_bytes': len(song_file.stream),
           'file_bytes': len(song_file.to_bytes())}
    for machine in machines:
        init, bursts = player.run(song_file, machine)
        out[machine.name] = burst_stats(bursts, machine)
        out[machine.name]['init'] = len(init)
    return out


def collect(wad):
    instruments = mus2ay.load_instruments(wad)
    rows = []
    for name in wad.songs():
        song = wad.song(name)
        c = song.counts()
        row = {'name': name, 'bytes': song.size, 'seconds': song.seconds,
               'events': len(song.events), 'on': c['on']}
        for layout in ('native12', 'mb6'):
            row[layout] = song_stats(song, instruments, layout,
                                     tables.LAYOUT_MACHINES[layout])
        rows.append(row)
    return rows


def tables_markdown(rows):
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
    add('Fallback, Mockingboard mode, 6 voices (3 melodic, 1 drum, 2 '
        'effects left free), PAL //e:')
    add('')
    add('| Song | Steals | Drum steals | Release cuts | Stream bytes | '
        'Writes/s | Writes/interrupt mean | p99 | p99 of bursts | Max |')
    add('| --- |' + ' ---: |' * 9)
    total_mb = 0
    for r in rows:
        s = r['mb6']
        c = s['counts']
        b = s['pal-mockingboard']
        add('| %s | %d | %d | %d | %d | %.0f | %.2f | %d | %d | %d |' % (
            r['name'], c['steals'], c['drum steals'], c['release cuts'],
            s['stream_bytes'], b['writes_s'], b['mean'], b['p99'],
            b['p99_busy'], b['max']))
        total_mb += s['stream_bytes']
    add('| All | | | | %d | | | | | |' % total_mb)
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
    peak = ayrender.write_wav(path, result)
    return name, seconds, peak, result.clipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--wad', default=str(mus.WAD_PATH))
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--update-readme', action='store_true')
    parser.add_argument('--seconds', type=float, default=60.0)
    parser.add_argument('--jobs', type=int, default=0)
    parser.add_argument('--out', default=str(mus2ay.BUILD_SOUND))
    args = parser.parse_args(argv)
    wad = mus.Wad.open(args.wad)
    rows = collect(wad)
    text = tables_markdown(rows)
    print(text)
    if args.update_readme:
        update_readme(text)
        print('\nupdated %s' % README)
    if args.render:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        jobs = []
        for r in rows:
            for layout in ('native12', 'mb6'):
                (out / ('%s.%s.ay' % (r['name'], layout))).write_bytes(
                    r[layout]['file'].to_bytes())
            seconds = min(args.seconds, r['seconds'] + 1.0)
            jobs.append((r['name'], r['native12']['file'].to_bytes(),
                         seconds, str(out)))
        workers = args.jobs or min(len(jobs), multiprocessing.cpu_count())
        with multiprocessing.Pool(workers) as pool:
            for name, seconds, peak, clipped in pool.imap(render_song, jobs):
                print('%s/%s.wav: %.1f s, peak %d, %d saturated samples'
                      % (out, name, seconds, peak, clipped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
