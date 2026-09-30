# Native replay on the card, 2026-09-30

The owner ran `build/native/REPLAY.hdv` (milestone 5, `src/native/runner.s`)
on the Appletini: TURBO, PAL (50 Hz), memory API present. The runner times
32 replays of each frame by the mouse card's VBL count.

**Every CRC matched the reference** (upstream's `R_DrawLists` on `ref816`).

| Frame | CRC-32 | OK | Card ms | a2vm f121 ms (harness) | Card / a2vm | Fuzz records |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| demo-01 | 2931B3C0 | OK | 34.3 | 33.24 | 1.03 | 0 |
| demo-02 | E44E867B | OK | 33.7 | 32.28 | 1.04 | 0 |
| demo-03 | 062213CE | OK | 30.0 | 29.27 | 1.03 | 0 |
| demo-04 | 64ED64FF | OK | 27.5 | 26.82 | 1.03 | 0 |
| demo-05 | 03124646 | OK | 29.3 | 29.17 | 1.00 | 0 |
| demo-06 | FB8D8E46 | OK | 31.8 | 31.30 | 1.02 | 0 |
| demo-07 | EDD08191 | OK | 32.5 | 31.55 | 1.03 | 0 |
| demo-08 | 3E77786F | OK | 29.3 | 26.38 | 1.11 | 12 |
| demo-09 | 7CCDA57D | OK | 25.0 | 21.45 | 1.17 | 26 |
| demo-10 | 60478D38 | OK | 48.1 | 34.34 | 1.40 | 59 |
| demo-11 | 78C62006 | OK | 49.3 | 35.09 | 1.40 | 91 |
| e1m3-1 | ACC7E07F | OK | 30.0 | 28.25 | 1.06 | 0 |
| still-1 | F197F453 | OK | 18.1 | 16.90 | 1.07 | 0 |
| still-2 | F7F59AF7 | OK | 18.1 | 16.90 | 1.07 | 0 |
| still-3 | F197F453 | OK | 18.1 | 16.90 | 1.07 | 0 |

The CRCs are read from the owner's photo of the result screen. The a2vm
column is the harness's (`build/native/check.json`), not the runner's own
a2vm run, which adds the runner's per-run work.

- Frames with no fuzz: within 0-7% of a2vm, the second hardware anchor of
  its cost model after the existing port's frame.
- Frames with fuzz: 11-40% slower than a2vm, about 1 us more per fuzz
  pixel. demo-10 and demo-11 fail milestone 5's 25% acceptance. The cause
  is under investigation (`build/fuzz-timing/`).

## Second run: the fuzz fix (`build/fuzz-timing/REPLAY-defer.hdv`)

The same frames, with the fuzz records drawn after each strip in one
RAMRD window (`docs/results/fuzz-timing-2026-09-30.md`, section 5b).
**Every CRC matched again.** Card ms, first run against this one:

| Frame | First run | Fuzz deferred | Predicted |
| --- | ---: | ---: | --- |
| demo-01 | 34.3 | 34.3 | unchanged |
| demo-02 | 33.7 | 33.7 | unchanged |
| demo-03 | 30.0 | 30.0 | unchanged |
| demo-04 | 27.5 | 27.5 | unchanged |
| demo-05 | 29.3 | 29.3 | unchanged |
| demo-06 | 31.8 | 33.1 | a2vm's run of the same disk: +1 VBL count |
| demo-07 | 32.5 | 33.7 | a2vm: +2 VBL counts |
| demo-08 | 29.3 | 26.8 | about 26-28 |
| demo-09 | 25.0 | 23.1 | about 21-23 |
| demo-10 | 48.1 | 36.2 | about 33-35 |
| demo-11 | 49.3 | 36.2 | about 34-36 |
| e1m3-1 | 30.0 | 30.0 | unchanged |
| still-1..3 | 18.1 | 19.3 | a2vm: +2 VBL counts |

- The fix works as predicted: the fuzz frames lose 1.9 to 13.1 ms. Every
  frame is now within 25% of a2vm, so milestone 5's timing acceptance is met.
- The +1.2 ms on still-1..3 and demo-06/07 is the runner's resolution, not
  the replay: it counts VBLs over 32 runs (0.625 ms a count) and subtracts
  a second VBL-counted loop. a2vm running the same disk predicts the same
  +2 counts (26 to 28 standing still); its unquantised harness gives +0.1 ms.
  The adopted runner will use 200 runs and print both loops.
