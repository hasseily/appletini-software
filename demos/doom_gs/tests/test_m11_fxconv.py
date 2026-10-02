"""Milestone 11, part fxconv: the effects converter (S4).

tools/sound/fxconv.py against the second model tools/sound/fxmodel.py and
the third decoder tools/sound/fxdec.py (tools/sound/README.md "Effects
(S4)"; docs/SCREENS.md 7.3; docs/m11-parts/fxconv.md):

- hand-made states through the encoder and the decoder (no build/ needed);
- the checkpoint on DOOM1.WAD: all 52 game sounds convert, in sfxenum_t
  order; every automatic script decodes to the model's per-tick states
  (and the converter's quantization stage is the model's); the ten tuned
  scripts decode to fxtune.txt's states as the model reads them; every
  42 ticks of every script within 128 bytes, counted on the bytes by a
  walker of this file; SFX.1 within one bank, read back equal; the PC
  speaker table equal to the model's copy of the published one, and the
  quarter-tone reconstruction within 8 cents of it; one render;
- the planted bugs, each in a scratch copy of fxconv.py, each caught.

Skips without build/ (the WAD and upstream's offsets.inc).
"""

import contextlib
import importlib.util
import io
import math
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import support
from sound import ayrender, fxconv, fxdec, fxmodel, mus, tables

WAD = fxmodel.WAD_FILE
OFFSETS = fxmodel.OFFSETS_INC
S_SOUND = support.UPSTREAM / 'src' / 'iigs' / 's_sound65.s'
needs_wad = unittest.skipUnless(
    WAD.exists() and OFFSETS.exists(),
    '%s or %s is missing: run python3 tools/fetch_upstream.py first'
    % (WAD.relative_to(support.ROOT), OFFSETS.relative_to(support.ROOT)))

SILENT = (0, 80, 0)


def walk_bytes(script):
    """The bytes the player reads at each tick of a script, walked on its
    bytes (the header at tick 0, a set and its wait at the wait's first
    tick, the end at the tick after the last)."""
    reads = [4]
    pc = 4
    tick = 0
    pending = 0
    ending = False
    while True:
        op = script[pc]
        if op <= 0x3F:
            while len(reads) <= tick:
                reads.append(0)
            reads[tick] += pending + 1
            pending = 0
            pc += 1
            tick += op + 1
            if ending:
                break
        elif op == 0xFF:
            while len(reads) <= tick:
                reads.append(0)
            reads[tick] += pending + 1
            break
        else:
            size = 1 + 2 * (op & 1) + (op >> 1 & 1) + (op >> 2 & 1)
            pending += size
            pc += size
            ending = bool(op & 8)
    while len(reads) <= tick:
        reads.append(0)
    return reads


def worst(reads, window=42):
    return max(sum(reads[w:w + window]) for w in range(len(reads)))


def checkpoint(conv, model, tune_path=fxconv.TUNE_PATH):
    """{check: None or what failed} of a converter module `conv` (the
    tree's or a planted copy) against the model."""
    out = {}
    wad = mus.Wad.open(WAD)
    tune = conv.parse_tune(Path(tune_path).read_text())
    try:
        effects = conv.convert_all(wad, tune)
        auto = conv.convert_all(wad, None)
        data = conv.bank_file(effects)
    except Exception as e:                      # noqa: BLE001
        return {'convert': '%s: %s' % (type(e).__name__, e)}
    out['convert'] = None
    if [e.name for e in effects] != model.names or len(effects) != 52:
        out['convert'] = 'not the 52 game sounds in sfxenum_t order'

    def first_diff(a, b):
        for t, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return 'tick %d: %s, model %s' % (t, x, y)
        return '%d ticks, model %d' % (len(a), len(b))

    bad = []
    for e in auto:
        try:
            flags, states = fxdec.decode(e.script)
        except fxdec.DecodeError as err:
            bad.append('%s: %s' % (e.name, err))
            continue
        stage, want = model.auto[e.name]
        if flags & 1 or states != want:
            bad.append('%s: %s' % (e.name, first_diff(states, want)))
        elif e.stage != stage:
            bad.append('%s: stage %s, model %d' % (e.name, e.stage, stage))
    out['auto = model'] = '; '.join(bad[:4]) or None

    bad = []
    for e in effects:
        tuned = e.name in model.tuned
        try:
            flags, states = fxdec.decode(e.script)
        except fxdec.DecodeError as err:
            bad.append('%s: %s' % (e.name, err))
            continue
        if bool(flags & 1) != tuned:
            bad.append('%s: tuned flag %d' % (e.name, flags & 1))
        elif tuned and states != model.tuned[e.name]:
            bad.append('%s: %s' % (e.name, first_diff(states,
                                                       model.tuned[e.name])))
        elif not tuned and states != model.auto[e.name][1]:
            bad.append('%s: automatic, not the model' % e.name)
    out['tuned = fxtune.txt'] = '; '.join(bad[:4]) or None

    bad = ['%s: %d bytes in 42 ticks' % (e.name, worst(walk_bytes(e.script)))
           for e in effects + auto if worst(walk_bytes(e.script)) > 128]
    out['ring budget'] = '; '.join(bad[:4]) or None

    try:
        directory, vatt, scripts = fxdec.read_bank(data)
        problem = None
        if len(data) > 48640:
            problem = '%d bytes' % len(data)
        elif scripts != [e.script for e in effects]:
            problem = 'the scripts read back differ'
        elif vatt != bytes(tables.ATTENUATION_OF_VALUE):
            problem = 'VATT differs from the music law'
        elif directory[0][0] != 0x0200 + 4 * 52 + 128:
            problem = 'the first script at $%04X' % directory[0][0]
        out['bank'] = problem
    except fxdec.DecodeError as err:
        out['bank'] = str(err)
    return out


class HandMade(unittest.TestCase):
    def roundtrip(self, states, flags=0):
        script, per_tick = fxconv.encode(states, flags)
        got_flags, got = fxdec.decode(script)
        self.assertEqual(got, states)
        self.assertEqual(per_tick, walk_bytes(script))
        self.assertEqual(per_tick, fxmodel.bytes_by_tick(states))
        return script, got_flags

    def test_one_set_and_the_ending_flag(self):
        script, flags = self.roundtrip([(300, 10, 0)] * 5)
        self.assertEqual(script, bytes([1, 0, 5, 0, 0x4B, 44, 1, 10, 4]))
        self.assertEqual(flags, 0)

    def test_long_runs_split_at_64_and_end_with_ff(self):
        script, _ = self.roundtrip([(0, 20, 7)] * 130)
        self.assertEqual(script[4:], bytes([0x46, 20, 7, 63, 63, 1, 0xFF]))

    def test_a_silent_start_has_no_set(self):
        script, flags = self.roundtrip([SILENT] * 3 + [(0, 0, 31)] * 2,
                                       fxconv.FLAG_TUNED)
        self.assertEqual(script[4:], bytes([2, 0x4E, 0, 31, 1]))
        self.assertEqual(flags, fxconv.FLAG_TUNED | fxconv.FLAG_NOISE)

    def test_only_changed_fields(self):
        self.roundtrip([(100, 0, 0), (100, 6, 0), (200, 6, 0), (200, 6, 9),
                        (0, 80, 0), (4095, 3, 31)])

    def test_decoder_is_strict(self):
        good, _ = fxconv.encode([(300, 10, 0)] * 5, 0)
        for bad in (good[:-1], good + b'\0', bytes([2]) + good[1:],
                    good[:4] + bytes([0x50]) + good[5:],
                    bytes([1, 2]) + good[2:]):
            with self.assertRaises(fxdec.DecodeError):
                fxdec.decode(bad)

    def test_quantize_holds_and_steps(self):
        raw = [(100, 10, 5, False), (0, 11, 5, False), (120, 30, 5, True),
               (120, 31, 9, True), (120, 80, 9, True)]
        self.assertEqual(fxconv.quantize(raw, (3, 2, 2)),
                         [(100, 10, 0), (100, 10, 0), (120, 30, 5),
                          (120, 30, 9)])
        self.assertEqual(fxconv.quantize(raw, (0, 1, 0)),
                         [(100, 10, 0), (0, 11, 5), (120, 30, 5),
                          (120, 31, 9)])

    def test_tune_parser(self):
        text = 'PISTOL\n2 tone=440 att=1.5 noise=3\n1 period=0\nend\n'
        p = (2 * fxconv.PSG + 16 * 440) // (32 * 440)
        want = [(p, 3, 3)] * 2 + [(0, 3, 3)]
        self.assertEqual(fxconv.parse_tune(text), {'PISTOL': want})
        for bad in ('PISTOL\n2 att=41\nend\n', 'PISTOL\n2 att=0.25\nend\n',
                    'NOPE\n1 att=0\nend\n', 'PISTOL\n0 att=0\nend\n',
                    'PISTOL\n1 noise=32\nend\n', 'PISTOL\n1 att=0\n',
                    'PISTOL\n1 volume=3\nend\n'):
            with self.assertRaises(fxconv.FxError, msg=bad):
                fxconv.parse_tune(bad)


@needs_wad
class Checkpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = fxmodel.Model()
        cls.wad = mus.Wad.open(WAD)

    def test_checkpoint(self):
        result = checkpoint(fxconv, self.model)
        self.assertEqual(result, {k: None for k in result}, result)
        self.assertEqual(len(result), 5)

    def test_game_sounds_and_upstream_order(self):
        self.assertEqual(list(fxconv.NAMES), self.model.names)
        if S_SOUND.exists():
            text = S_SOUND.read_text()
            start = text.index('sfxPriority:')
            names = []
            for line in text[start:].splitlines()[:7]:
                names += line.split(';')[1].split()
            self.assertEqual(names[0], 'none')
            self.assertEqual([n.upper() for n in names[1:]],
                             list(fxconv.NAMES))

    def test_the_ten_tuned(self):
        self.assertEqual(set(self.model.tuned), set(fxconv.TUNED))
        self.assertEqual(set(fxconv.TUNED), fxmodel.TUNED_TEN)
        self.assertEqual(set(fxconv.load_tune()), set(fxconv.TUNED))

    def test_budget_failure_names_the_effect(self):
        churn = [(100 + (t % 2), t % 2, 0) for t in range(60)]
        with self.assertRaisesRegex(fxconv.FxError, 'SHOTGN'):
            fxconv.convert(self.wad, 'SHOTGN', 2, {'SHOTGN': churn})

    def test_bank_file_written_and_read_back(self):
        tmp = Path(tempfile.mkdtemp(prefix='fxconv-'))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fxconv.main(['--out', str(tmp)]), 0)
            data = (tmp / 'SFX.1').read_bytes()
            self.assertLessEqual(len(data), 48640)
            directory, vatt, scripts = fxdec.read_bank(data)
            address = 0x0200 + 4 * 52 + 128
            for (a, n), s in zip(directory, scripts):
                self.assertEqual((a, n), (address, len(s)))
                address += n
            self.assertEqual(address - 0x0200, len(data))
            effects = fxconv.convert_all(self.wad, fxconv.load_tune())
            self.assertEqual(scripts, [e.script for e in effects])
            auto = fxdec.read_bank((tmp / 'SFXAUTO.1').read_bytes())[2]
            for name, s in zip(self.model.names, auto):
                self.assertEqual(fxdec.decode(s)[1], self.model.auto[name][1])
            self.assertIn('PISTOL  tuned', (tmp / 'SFX.lst').read_text())
        finally:
            shutil.rmtree(tmp)

    def test_pc_speaker_table(self):
        model = [0] + [fxmodel.PC_DIVISOR[i] for i in range(1, 128)]
        self.assertEqual(list(fxconv.DIVISORS), model)
        cents = [1200 * math.log2(fxconv.PIT / fxconv.DIVISORS[i]
                                  / (175 * 2 ** ((i - 1) / 24)))
                 for i in range(1, 128)]
        self.assertLess(max(abs(c) for c in cents), 8.0)
        steps = [1200 * math.log2(fxconv.DIVISORS[i] / fxconv.DIVISORS[i + 1])
                 for i in range(1, 127)]
        self.assertTrue(all(40 < s < 60 for s in steps))
        self.assertEqual(fxconv.PSG, 2031250)

    def test_one_render(self):
        tmp = Path(tempfile.mkdtemp(prefix='fxconv-'))
        try:
            states = self.model.tuned['PISTOL']
            peak = fxmodel.render(states, tmp / 'p.ay', tmp / 'p.wav')
            self.assertGreater(peak, 1000)
            with wave.open(str(tmp / 'p.wav')) as w:
                self.assertEqual((w.getnchannels(), w.getframerate()),
                                 (2, 44100))
                self.assertGreater(w.getnframes(), 44100 * len(states)
                                   // 140 // 2)
            _, _, writes = ayrender.read_log(tmp / 'p.ay')
            self.assertEqual({w[1] for w in writes}, {3})
            self.assertTrue({w[2] for w in writes} <= {0, 1, 6, 7, 8, 9, 10})
        finally:
            shutil.rmtree(tmp)


# Each planted bug: the text of fxconv.py it replaces (exactly once) and
# its replacement.
PLANTED = {
    'DP pitch a quarter tone off': (
        '    d = DIVISORS[tone]\n',
        '    d = DIVISORS[min(tone + 1, len(DIVISORS) - 1)]\n'),
    'level from the peak, not the RMS': (
        '    return attenuation_of_rms(math.sqrt(total / len(seg)))\n',
        '    return attenuation_of_rms(max(abs(s - 128) for s in seg))\n'),
    'noise threshold inverted': (
        'c * rate > NOISE_CROSSINGS * n))',
        'c * rate <= NOISE_CROSSINGS * n))'),
    'run length counted from 0': (
        '            steps.append(k - 1)\n',
        '            steps.append(k)\n'),
    'a tuned entry ignored': (
        '    if tune is not None and name in tune:\n',
        '    if tune is not None and name in tune and name != TUNED[-1]:\n'),
}


@needs_wad
class Planted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = fxmodel.Model()
        cls.tmp = Path(tempfile.mkdtemp(prefix='fxconv-planted-'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def planted(self, label):
        old, new = PLANTED[label]
        source = Path(fxconv.__file__).read_text()
        self.assertEqual(source.count(old), 1, label)
        path = self.tmp / ('fxconv_%d.py' % list(PLANTED).index(label))
        path.write_text(source.replace(old, new))
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_each_planted_bug_is_caught(self):
        caught = {}
        for label in PLANTED:
            result = checkpoint(self.planted(label), self.model)
            failed = [k for k, v in result.items() if v]
            self.assertTrue(failed, '%s was not caught' % label)
            caught[label] = (failed[0], result[failed[0]])
        if '-v' in sys.argv:
            for label, (check, why) in caught.items():
                print('%s: %s: %s' % (label, check, why[:100]))


if __name__ == '__main__':
    unittest.main()
