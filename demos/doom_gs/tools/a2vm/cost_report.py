#!/usr/bin/env python3
"""The cost model's report on the existing Doom port (MILESTONES.md 3.1,
acceptance item 4).

Usage:  python3 tools/a2vm/cost_report.py [--frames 20] [--out DIR]
            [--markdown FILE] [--no-sensitivity]

Runs the existing port's banked build (demos/doom, tools/a2vm/doom.py) on
a2vm with the exact W65C02S core, the memory API and no input (E1M1,
standing still), on the cost model's clock ("timed"), once per profile of
tools/a2vm/costs/appletini.json. The first frame loads the level; the
report covers the --frames frames after it. For each profile it gives
the time per frame (mean, median, range) and per phase (the phases the
port's profiling build marks with its profile_stage byte), and compares
the F1.2.1 profile ("f121") with the hardware measurement of the same
build (v12, e2676d7e, E1M1 standing still, PAL, F1.1.4): 248 ms a frame,
the per-phase times of docs/research/existing-port.md section 5, and the
counters of the card's own `vtw status` before and after that capture.

It also runs the F1.2.1 profile on the compatibility core with the model
only observing (the run that must still match a2sim.py), and, unless
--no-sensitivity, twice more with other values of the memory API's AXI
latency (axi_us), the parameter the copy phases depend on. axi_us is
fitted to the hardware measurement, so the frame total is not an
independent check; the phases that do not copy are.

Writes OUT/cost-report.json and prints the tables as Markdown.
Standard library only.
"""

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import costs  # noqa: E402
import doom  # noqa: E402

PHASES = ('idle', 'game_copy', 'game_tics', 'packet', 'debug',
          'render_copy', 'setup', 'walls', 'planes', 'things', 'masked',
          'present_wait', 'blit')

# The hardware measurement (docs/research/existing-port.md section 5, from
# demos/doom/build/profiles/e1m1-idle-turbo-v12-amem-batch-pal.json):
# 242 frames in 60.007 s of host time, VBL-sampled phases.
HARDWARE_MS = 248.0
# MILESTONES.md 3.1: the F1.2.1 profile must come within 25% of it, or
# the report must name the parameter it suspects.
TOLERANCE = 0.25
# axi_us is fitted to this measurement (tools/a2vm/costs/appletini.json):
# with every other parameter fixed, the f121 frame matches HARDWARE_MS.
# The only figure in the firmware documents, a code review's "~16K added
# register reads add ~5-16ms" (0.305 to 0.98 us a read), is kept for the
# sensitivity runs.
REVIEW_AXI_US = (0.305, 0.98)
# The VBL-sampled phases lose the time the ARM holds the core: the card's
# VBL counter lost 1.7 s of the 60 s capture, 6.9 ms a frame
# (tools/a2vm/README.md). The holds are in the copy phases.
HARDWARE_LOST_MS = 6.9
HARDWARE_PHASES_MS = {
    'walls': 78.6, 'planes': 33.6, 'game_tics': 32.5, 'blit': 24.0,
    'render_copy': 22.3, 'game_copy': 18.2, 'masked': 16.3, 'packet': 9.4,
    'things': 4.0, 'debug': 1.5, 'setup': 0.7, 'idle': 0.0,
    'present_wait': 0.0}
# The card's `vtw status` counters (vtw_core_top.sv perf_count, bus engine
# counts) before and after that capture, in the same profile JSON
# ("transport.status" and "transport.status_end"). They are 32-bit and
# wrap; the fabric counter wrapped once more than the difference shows
# (60.6 s of 133.333 MHz is 8.07e9 clocks), the others never.
HARDWARE_STATUS = {
    'fabric': (4199733319, 3683995973, 1),
    'steps': (3367337568, 692265880, 0),
    'read_hits': (2349191234, 3494585639, 0),
    'misses': (685012663, 1023064563, 0),
    'invalidations': (13569558, 19840096, 0),
    'video_wait': (2310532405, 3383953422, 0),
    'bus_cycles': (2759883, 4126675, 0),
    'posted': (19131521, 28158821, 0)}
MODEL_COUNTER = {'steps': 'accesses'}


def hardware_per_frame():
    """Each counter's change per frame of 248 ms."""
    def delta(name):
        start, end, wraps = HARDWARE_STATUS[name]
        return (end - start) % (1 << 32) + (wraps << 32)
    fabric = delta('fabric')
    frame = HARDWARE_MS * 1e-3 * 133.333333e6
    return {name: delta(name) * frame / fabric
            for name in HARDWARE_STATUS if name != 'fabric'}


def run(build, profile, out, frames, core='w65c02s', timed=True,
        parameters=None):
    """One run of the port; the report's lines after the first frame."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    image = out / 'fast.img'
    image.write_bytes(build.image())
    command = [str(doom.A2VM), '--rom', str(doom.DEFAULT_ROM), '--speed',
               'turbo', '--core', core, '--amem']
    command += build.fast_arguments(image) + build.hook_arguments()
    command += build.cost_arguments(profile, out, timed)
    if parameters:
        path = out / ('cost-%s.txt' % profile)
        text = path.read_text()
        for key, value in parameters.items():
            lines = [line for line in text.splitlines()
                     if not line.startswith(key + ' ')]
            text = '\n'.join(lines + ['%s %r' % (key, value)]) + '\n'
        path.write_text(text)
    command += ['--boundaries', str(frames + 1), '--state',
                str(out / 'state.json')]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            universal_newlines=True)
    if result.returncode:
        raise SystemExit('a2vm failed:\n' + result.stdout)
    lines = (out / 'cost.jsonl').read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.startswith('{"boundary')]
    if len(rows) != frames + 1:
        raise SystemExit('%d frames reported, not %d' % (len(rows), frames + 1))
    state = json.loads((out / 'state.json').read_text())
    return rows[1:], state


def summary(rows, mhz):
    ms = [row['clocks'] / mhz / 1e3 for row in rows]
    phases = {name: statistics.mean(row['phases'][i] / mhz / 1e3
                                    for row in rows)
              for i, name in enumerate(PHASES)}
    counters = {key: statistics.mean(row[key] for row in rows)
                for key in rows[0] if key not in ('boundary', 't', 'phases')}
    irqs = rows[-1]['irqs'] - rows[0]['irqs']
    return dict(frames=len(rows), mean_ms=statistics.mean(ms),
                median_ms=statistics.median(ms), min_ms=min(ms),
                max_ms=max(ms), frame_ms=ms, phases_ms=phases,
                counters=counters,
                irqs_per_frame=irqs / max(len(rows) - 1, 1))


def markdown(report):
    f121, fast = report['profiles']['f121'], report['profiles']['fastpath']
    hw = report['hardware']
    out = []
    add = out.append
    add('| Profile | Mean ms a frame | Median | Range | Frames a second | '
        'Against 248 ms measured |')
    add('| --- | ---: | ---: | --- | ---: | ---: |')
    for name in ('f121', 'fastpath'):
        s = report['profiles'][name]
        add('| %s | %.1f | %.1f | %.1f-%.1f | %.2f | %+.1f%% |' % (
            name, s['mean_ms'], s['median_ms'], s['min_ms'], s['max_ms'],
            1000 / s['mean_ms'], 100 * (s['mean_ms'] / HARDWARE_MS - 1)))
    add('')
    add('| Phase | Hardware ms (v12, sampled) | f121 ms | f121 / hardware | '
        'fastpath ms |')
    add('| --- | ---: | ---: | ---: | ---: |')
    order = sorted(PHASES, key=lambda p: -HARDWARE_PHASES_MS[p])
    for phase in order:
        h = HARDWARE_PHASES_MS[phase]
        m = f121['phases_ms'][phase]
        ratio = '%.2f' % (m / h) if h else '-'
        add('| %s | %.1f | %.1f | %s | %.1f |' % (
            phase, h, m, ratio, fast['phases_ms'][phase]))
    add('| **total** | **%.1f** (%.1f by host time) | **%.1f** | %.2f | '
        '**%.1f** |' % (sum(HARDWARE_PHASES_MS.values()), HARDWARE_MS,
                        f121['mean_ms'], f121['mean_ms'] / HARDWARE_MS,
                        fast['mean_ms']))
    add('')
    add('| Counter a frame | Hardware (`vtw status`) | f121 | f121 / hardware |'
        ' fastpath |')
    add('| --- | ---: | ---: | ---: | ---: |')
    for name, value in hw['counters_per_frame'].items():
        key = MODEL_COUNTER.get(name, name)
        m = f121['counters'][key]
        add('| %s | %.0f | %.0f | %.2f | %.0f |' % (
            name, value, m, m / value, fast['counters'][key]))
    add('')
    compat = report.get('compatibility')
    if compat:
        add('Compatibility core, model only observing (the a2sim.py timeline, '
            'no dummy reads, idle skips not charged): f121 %.1f ms a frame.'
            % compat['mean_ms'])
    sens = report.get('sensitivity')
    if sens:
        add('')
        add('| axi_us | f121 ms a frame | game_copy + render_copy ms |')
        add('| ---: | ---: | ---: |')
        for row in sens['runs']:
            add('| %.3f | %.1f | %.1f |' % (row['axi_us'], row['mean_ms'],
                                           row['copy_ms']))
        add('')
        add('Linear fits over the first two rows: the f121 frame matches the '
            '%.1f ms measured by host time at axi_us = %.3f, and the copy '
            'phases match the hardware\'s %.1f ms (%.1f sampled, %.1f lost '
            'to sampling during the ARM\'s holds) at %.3f.' % (
                HARDWARE_MS, sens['axi_us_matching_frame'],
                sens['hardware_copy_ms'], sens['hardware_copy_ms'] -
                HARDWARE_LOST_MS, HARDWARE_LOST_MS,
                sens['axi_us_matching_copy']))
    add('')
    add(axi_dependency(report))
    return '\n'.join(out) + '\n'


def within(ms):
    return abs(ms / HARDWARE_MS - 1) <= TOLERANCE


def axi_dependency(report):
    """What the agreement with the hardware rests on."""
    f121 = report['profiles']['f121']
    base = costs.parameters('f121')['axi_us']
    low, high = REVIEW_AXI_US
    text = ('**axi_us is fitted to this capture, not measured.** It is the '
            'latency of the ARM\'s AXI register accesses, which the memory '
            'API\'s copies rest on. The f121 profile takes %.3f us, the value '
            'at which its frame matches the %.0f ms measured by host time; '
            'at it the f121 frame is %.1f ms (%+.1f%%). So the frame total '
            'is not an independent check of the model; the phases that do '
            'not copy, and the card\'s counters, are. Only milestone 0 can '
            'measure axi_us.' % (
                base, HARDWARE_MS, f121['mean_ms'],
                100 * (f121['mean_ms'] / HARDWARE_MS - 1)))
    sens = report.get('sensitivity')
    if sens:
        text += (' The copy phases alone give %.3f us. The code review\'s '
                 'estimate of %.3f to %.2f us a read does not fit the '
                 'capture:' % (sens['axi_us_matching_copy'], low, high))
        for r in sens['runs'][1:]:
            text += ' %.1f ms (%+.1f%%) at %.3f us;' % (
                r['mean_ms'], 100 * (r['mean_ms'] / HARDWARE_MS - 1),
                r['axi_us'])
        text = text[:-1] + '.'
    else:
        text += (' The sensitivity runs (without --no-sensitivity) give the '
                 'frame at the code review\'s %.3f and %.2f us.' % (low, high))
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--frames', type=int, default=20)
    parser.add_argument('--out', type=Path,
                        default=doom.ROOT / 'build' / 'a2vm' / 'cost')
    parser.add_argument('--markdown', type=Path)
    parser.add_argument('--no-sensitivity', action='store_true')
    arguments = parser.parse_args(argv)
    build = doom.Build()
    out = arguments.out
    out.mkdir(parents=True, exist_ok=True)
    report = dict(frames=arguments.frames, core='w65c02s', timed=True,
                  scene='E1M1, standing still, memory API on, no input',
                  build=str(doom.DEFAULT_BUILD), profiles={},
                  hardware=dict(ms_per_frame=HARDWARE_MS,
                                phases_ms=HARDWARE_PHASES_MS,
                                counters_per_frame=hardware_per_frame()))
    for profile in costs.profiles():
        mhz = costs.parameters(profile)['fabric_mhz']
        rows, state = run(build, profile, out / profile, arguments.frames)
        s = summary(rows, mhz)
        s['host_seconds'] = state['host_seconds']
        report['profiles'][profile] = s
    rows, _ = run(build, 'f121', out / 'compat', arguments.frames,
                  core='py65', timed=False)
    report['compatibility'] = summary(rows, costs.parameters('f121')
                                      ['fabric_mhz'])
    f121, fast = report['profiles']['f121'], report['profiles']['fastpath']
    report['fastpath_gain'] = f121['mean_ms'] / fast['mean_ms'] - 1
    if not arguments.no_sensitivity:
        base = costs.parameters('f121')['axi_us']
        runs = []
        for value in (base,) + REVIEW_AXI_US:
            if value == base:
                s = f121
            else:
                rows, _ = run(build, 'f121', out / ('axi-%g' % value),
                              arguments.frames, parameters=dict(
                                  axi_us=value, axi_write_us=value))
                s = summary(rows, costs.parameters('f121')['fabric_mhz'])
            runs.append(dict(axi_us=value, mean_ms=s['mean_ms'],
                             copy_ms=s['phases_ms']['game_copy'] +
                             s['phases_ms']['render_copy']))
        hw_copy = HARDWARE_PHASES_MS['game_copy'] + \
            HARDWARE_PHASES_MS['render_copy'] + HARDWARE_LOST_MS

        def matching(key, target):
            (x0, y0), (x1, y1) = [(r['axi_us'], r[key]) for r in runs[:2]]
            return x0 + (target - y0) * (x1 - x0) / (y1 - y0)
        report['sensitivity'] = dict(
            runs=runs, hardware_copy_ms=hw_copy,
            axi_us_matching_frame=matching('mean_ms', HARDWARE_MS),
            axi_us_matching_copy=matching('copy_ms', hw_copy))
    (out / 'cost-report.json').write_text(json.dumps(report, indent=1) + '\n')
    text = markdown(report)
    if arguments.markdown:
        arguments.markdown.write_text(text)
    print(text)
    print('fastpath against f121: %+.1f%% frames a second' %
          (100 * report['fastpath_gain']))
    print('wrote %s' % (out / 'cost-report.json'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
