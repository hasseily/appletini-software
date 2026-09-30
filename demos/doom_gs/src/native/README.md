# src/native: the native record replay (milestone 5)

The first hand-written kernel of the native rewrite: upstream's column
records in, the 3D view's SHR bytes out, in 65C02 assembly for ca65
(cc65 2.18). Milestone 5 of [`docs/NATIVE.md`](../../docs/NATIVE.md)
section 13, from its section 5 and
[`docs/research/native-memory.md`](../../docs/research/native-memory.md)
5.2, at the addresses of
[`docs/MEMORY_MAP.md`](../../docs/MEMORY_MAP.md) section 8. It is a GPL-2
derivative of upstream's `r_list65.s` and `lists.inc` (the same records,
the same pixels); the row blocks come from our own generator,
`tools/native/rowgen.py`, not from upstream's `gendraw.py`.

| File | What it is |
| --- | --- |
| `replay.s` | The replay: batches and strips, the gather (walk, texel copies), the draw pass, the row-block patching, the fuzz and overlay drawers; it includes the generated `rows.s` |
| `driver.s` | The a2vm test driver: loads each batch into W and calls the replay between two labels a2vm snapshots; not part of the game |
| `runner.s` | `REPLAY.SYSTEM` for the card: loads frames into RamWorks under ProDOS, then for each loads its state as the game will (CPU stores for main `$0200-$03FF`, `$0C00-$1FFF` and the screen; one memory-API request of PRIVATE copies for the colormaps, the tables and the drawers), runs it, shows it, prints CRCs and times; not part of the game |
| `replay.cfg`, `runner.cfg` | ld65's maps: every area of MEMORY_MAP section 8, so an overflow fails the link |
| `Makefile` | Builds into `build/native/obj`: `test.*` (with the driver), `prof.*` (the same, marking its parts as cost phases), `card.*` (with the runner) |

The host tools are in [`tools/native`](../../tools/native):

| Tool | What it does |
| --- | --- |
| `layout.py` | Every address and constant, one source: `rowgen.py` writes `layout.inc` and the runner's `restore.inc` from it |
| `rowgen.py` | The texture row pairs, the fill chains, the entry and colormap tables, the aux-0 tables |
| `loader.py` | A capture directory into an a2vm image placed per MEMORY_MAP section 8 (below); refuses records the replay cannot draw safely; models upstream's screen stores and the replay's strips and copy groups |
| `a2run.py` | Runs an image on a2vm with snapshots around each replay call and the cost model; compares snapshots for stray writes |
| `replay_check.py` | The harness: every frame, captured and poisoned screen, against the reference; times |
| `synth.py` | Synthetic record streams with upstream's truth from `ref816 --call` |
| `disk.py` | The card disk `build/native/REPLAY.hdv`, and its run on a2vm (`--check`, with the memory API) |
| `sizes.py` | Each area's bytes used and left (`make sizes`) |

## Commands

From `demos/doom_gs`, with the captures of `tools/ref816/capture.py`
(which now also keeps the fuzz table, `fuzz.bin`), a2vm and ref816 built:

```
make -C src/native                                  # the three builds
make -C src/native sizes                            # the areas
python3 tools/native/replay_check.py --breakdown    # the 15 captured frames
python3 tools/native/synth.py                       # 10 synthetic streams
python3 tools/native/replay_check.py build/native/synth/synth-*
python3 tools/native/disk.py --check                # the card disk, run on a2vm
python3 -m unittest discover -s tests -p 'test_native_replay.py'
```

`synth.py` needs `build/native/base-entry.img`, all of RAM at a real
`R_DrawLists` entry (`--make-base` captures it again, about 10 s).

## How it runs

`nat_replay` (A = the batch's first column, X = the column after its last)
draws one batch of records, in strips of whole columns:

1. **Gather: walk.** RAMRD off. For each column of the strip, each
   texture record (`K_TEX`, `K_TEXC`) gets its place in the texel stage
   (W `$8000-$BFFF`) and a 12-byte copy descriptor in page 1; the stage
   pointer the draw will use is pushed on a list at the stage's top. A
   column that does not fit the stage left ends the strip before it (the
   walk rolls back to the column's start).
2. **Gather: copies.** Every 12 descriptors (`MAXDESC`: all page 1 has
   room for) and at the strip's end: RAMRD on; for each RamWorks bank
   present one `$C073` write and all its copies; `$C073` 0, RAMRD off. A
   record's texels are copied one of two ways:
   - *one texel a row* when its chain's whole step is 2 or more and it
     has at most 128 rows: the copy steps the position exactly as the
     row blocks do (below) and stores the texel of each row; the draw
     then uses a unit step from 127.0. The loop runs from page 1 with
     its absolute operands set per record;
   - *a span* otherwise: the texels the rows can reach, TI to
     TI + n × step + 1 (the even rows' rounding can pass the exact
     position by one), rounded up to 4 for the unrolled copy, or all 128
     when that passes texel 127; the draw uses the record's own step.
3. **Draw.** RAMWRT on (`$C073` 0: the screen). For each column: its
   covered-range cut (upstream's `cvCol`, `cutTex`, `cutFill`,
   `texStart`), then each record by kind:
   - `K_TEX`, `K_TEXC`: the chain's step and colormap pages (from
     `CMPA`/`CMPB` by upstream's `R_CMP`) for a `K_TEX`, the stage
     pointer popped, the position one row before the first as upstream's
     `pairPrepare` (an odd first row: one fraction step back, the rounded
     carry ahead), then the row blocks from the first row's entry
     (`TEXLO`/`TEXHI`) to the exit row, patched to `RTS` and restored;
   - `K_FILL`: the even rows through the even chain, the odd rows
     through the odd chain, each with its row parity's byte;
   - `K_FUZZ`, `K_OVL`: RAMRD on, the drawer in aux 0 `$0200` (it reads
     the screen), RAMRD off.

   RAMWRT off (the bus cycle waits for the mirror's drain on F1.2.1),
   then the covered ranges of the strip's columns are zeroed.

The texture row pair (36 bytes, `rowgen.py`): the even row adds `si2`
(the whole step plus the rounded carry of twice the fraction step) to the
texel, the odd row adds twice the fraction step to the fraction and the
whole step plus that carry to the texel, so each pair advances exactly
twice the step and an even row takes the rounded half-way texel, as
upstream's pair image does. Each row reads its texel from the stage
`(src),y`, puts it in the low byte of the colormap pointer (A for even
rows, B for odd) and stores `(cma)` or `(cmb)` at `$2000 + 160 × row, X`.
31.5 cycles a row.

The replay enters with `$D000` bank 1 selected and selects bank 2 (the
row blocks and the draw pass) for its run, as MEMORY_MAP rule 1 says.

## Memory

MEMORY_MAP section 8's addresses, and how much of each area the build
takes (`make sizes`):

| Area | Content | Used of |
| --- | --- | ---: |
| zero page `$48-$6F` | the replay's state; the gather and the drawers alias the draw's temporaries | 39 of 40 |
| page 1 `$0100-$01B4` | 12 gather descriptors of 12 bytes, the per-row copy loop (37 bytes); the stack stays at or above `$01C0` | 181 of 192 |
| main `$0800-$0BFF` | `CMPA`, `CMPB`, `TEXLO`, `TEXHI` | 406 bytes of tables |
| main `$17C2-$17FF` | gather scratch | 9 of 62 |
| W `$6000-$7FFF` | a batch of records (the replay only reads it) | up to 8,192 |
| W `$8000-$BFFF` | the texel stage, and its pointer list from the top | 16,384 |
| card bank 2 `$D000-$DBD0` | texture row pairs, landing `RTS` | 3,025 of 3,072 |
| card bank 2 `$DC00-$DCFC`, `$DD00-$DDFC` | fill chains, even and odd rows | 253 + 253 of 512 |
| card bank 2 `$DE00-$DFFF` | the draw pass | 509 of 512 |
| card `$F900-$FEFF` | batches, strips, gather, cold draw helpers | 1,079 of 1,536 |
| aux 0 `$0200-$03FF` | the fuzz and overlay drawers | 113 of 512 |
| aux 0 `$0800-$0BFF` | `FUZZDARK` (per level), `ROWLO`, `FZDIR`, `ROWHI` | 706 bytes of tables |

The replay writes only its zero page, page 1 `$0100-$01B4` and the stack
from `$01C0` up to its caller's S (it takes 14 bytes below it, measured),
main `$1400-$153F` (the covered ranges it clears), main `$17C2-$17FF`, W
`$8000-$BFFF` and aux 0 `$2000-$88FF`; the row-block patches are restored
before each record ends. `replay_check.py` checks exactly that (below).

It relies on what upstream's producers guarantee of the records, and the
loader refuses a frame that breaks it (`loader.check_record`): a
texture or fill record has rows (`R_ROW < R_END <= 168`), a shadow has at
least one row, all of them in 1-166, an automap pixel is in the view.
Without rows, a texture record at a whole step of 2 or more would make the
gather copy 256 texels below its stage place (into the batch's records
for a strip's first record), and a shadow of no rows would draw 256.

## Departures from NATIVE.md and MEMORY_MAP.md

`docs/MEMORY_MAP.md` now records the memory ones (sections 2, 4.2, 5 and
8).

| What | Why |
| --- | --- |
| Fill blocks: two chains, even rows at `$DC00 + 3 × (r >> 1)` and odd rows at `$DD00 + 3 × (r >> 1)`, each row `STA $2000 + 160r,X`, landings `$DCFC`, `$DDFC`; a fill record runs both chains, each with its parity's byte | The map's "`STA` or `STY abs,X`" cannot be: the 65C02 has no `STY abs,X` (nor `STX abs,Y`). Still 3 bytes a row, 506 bytes; one more patch and call a fill record |
| Page 1 holds the gather's descriptors (`$0100-$018F`) and the per-row copy loop (`$0190-$01B4`, copied there at each call, its operands patched per record); the stack stays at or above `$01C0` | Page 1, like zero page, is near whatever RAMRD says, so code and data there serve the copies that run with RAMRD on; the card had no room. The map reserved page 1's bottom only for the pair build's bounce buffer |
| The stage pointer of each texture record goes on a list at the stage's top; the records in W are never written | The map had the gather rewrite each record's source. Unchanged records let a column that does not fit the stage be walked again in the next strip |
| Two ways of copying texels (one texel a row, or a span), chosen by the chain's whole step | The map's rule. Measured costs on a2vm (f121): a row about 0.75 µs (a third of the texel reads miss the RamWorks line), a span byte about 0.35 µs |
| No `FZMOD50` table | The fuzz drawer steps its position 0-49 itself |
| The replay does not write into records nor reset `COLW` or `XPNEXT` | Upstream writes back `R_TF` (`texStart`) and swaps `R_B1`/`R_B2` (`fillStart`); the native replay keeps those in zero page. Resetting the lists is the producers' business |
| The covered ranges are zeroed after each strip's draw, for its columns | Upstream zeroes each column's range as it starts it; the map says after the last batch; per strip is the same state at the end |
| One column needing more than the 16 KB stage stops the replay (`BRK`, code 1) | It needs over 125 texture records in one column; the loader's stage model refuses such a frame first. Upstream has no such limit |
| The copies run in groups of 12 descriptors, each group with its own RAMRD window and one `$C073` write for each texel bank it copies from; NATIVE.md 5.2 says "open one window per texel bank" | One window a bank for a whole strip would need its queue near in every RAMRD state: 100 or more descriptors of 12 bytes, and neither page 1 nor the card has room. Measured (the profiling build's "switches" phase): 69-221 soft-switch writes a captured frame, 0.10-0.34 ms on f121 (0.27 still, 0.34 on demo-10), 0.01-0.05 ms on fastpath; one group a strip would take about 7 writes a strip, 0.01 ms |

## Verification

`replay_check.py`, for each frame, runs the native replay on a2vm (exact
W65C02S core, SHR on) twice: from the captured screen, against the
captured screen after upstream's `R_DrawLists`; and from a poisoned
screen (a pattern in the pixels, the captured SCBs and palettes), against
`ref816 --call` of upstream's `R_DrawLists` on the same poisoned screen
and buffer. In both runs every byte the frame and the build do not define
(all of main, the card outside the build's segments, the free and
forbidden bytes between the tables, every aux bank) is filled, `$A5` in
the captured run and `$5A` in the poisoned one, so a stray store of any
constant, zero included, changes a byte in at least one of them. The
driver calls the replay with S = `$EF`, so `$01F0-$01FF` stands for a
caller's frame. Each run takes a snapshot of the whole machine (main, both
card parts, all 128 aux banks) just before and just after each call and
checks:

- the run ends at the driver's halt;
- all of aux 0 `$2000-$9FFF` equals the truth;
- every byte of every bank outside the replay's areas above is
  unchanged across each call, the card and the caller's frame included;
- the soft switches and the stack pointer are as before the call;
- its SHR writes (a2vm's count) equal the screen stores upstream makes
  for the frame (`loader.screen_stores`: the rows each texture or fill
  record keeps after the covered-range cut, the shadows' rows, one a
  pixel of the automap), and it makes no other video write (MEMORY_MAP
  rule 3). The pixels cannot show that the cut is made at all: the
  covering record paints its range again. The count can, and the cut is
  there to save time.

A store of the value a byte already holds is not seen (a2vm has no write
log).

`synth.py` makes 10 synthetic streams (every kind, `K_OVL` and `K_TEXC`
chains included; `K_TEX` and `K_TEXC` covering records; rows 0 and 167;
whole steps 0-127 and fractions at their extremes; all 50 fuzz positions;
all 34 light levels; `K_NEXT` into the extra pages; several batches;
several strips) within what upstream's producers make, on a real
`R_DrawLists` entry state, with upstream's truth by `--call`; the harness
checks them the same way. Its `rows` style puts one covered-range case in
a column (before the range, ending in it or at its end, spanning it,
inside it, exactly it, starting in it, after it, the whole column, a
`K_TEXC` chain behind a `K_TEX` the range hides, a start in the range with
all 128 texels copied, an odd first row and an even end of the range), its
edges at random parities, then the covering record (a `K_TEX`, or a
`K_TEXC` of the case's chain), then a record inside the range, which the
cut must no longer touch; nothing after the case's record paints its rows
outside the range, so every row it keeps or loses shows.

`tests/test_native_replay.py` runs all of it, checks the generated code
byte by byte (every row block's entry opcode and store address, both fill
chains, the tables), the loader's refusals, the image's fill, and plants
15 bugs in a scratch copy of the sources to show the checks fail
(differing bytes captured / poisoned; stray bytes; SHR writes against the
model):

| Bug | Frame | Caught |
| --- | --- | --- |
| fill bytes by the wrong parity | demo-01 | 65 / 70 differing |
| a store into the fill spans | still-1 | 1 stray byte each run, pixels equal |
| a row block left patched | still-1 | 35 stray bytes in the card |
| an odd first row without its rounded carry | demo-01 | 97 / 97 differing |
| `STZ` into main `$1A80`, aux 0 `$A000` (in the draw), the card's `$E480` | still-1 | 1 stray byte each run |
| a store into the caller's frame (`$01F0`), below the stack floor (`$01B8`) | still-1 | 1 stray byte each run |
| no covered-range cut at all | still-1 | 8,614 SHR writes for 8,519, pixels equal |
| the cut skipped | synth-rows | 8,784 for 7,293, pixels equal |
| `texStart`: no advance; one row too many | synth-rows | 221 / 221; 213 / 213 differing |
| `fillStart`: the bytes swapped at a new first row | synth-rows | 15 / 15 differing |
| a texture ending in the range cut one row short | synth-rows | 20 / 21 differing, 7,272 SHR writes |

The same five cut bugs on the `rows` stream of `synth.py`'s default seed:
0 / 0 differing (the cut skipped; 8,945 SHR writes for 7,335), 249, 241,
16 and 23 differing bytes.

`disk.py --check` runs the card disk on a2vm with its memory API, and
checks the first frame's load with snapshots around it: no video write
outside the screen (the old runner, which restored main `$0200-$5FFF` by
CPU, makes over 16,000: the test plants it back), main `$0878-$087F`
(a sentinel there) untouched, one memory-API request, colormap B's level
0 at `$4078-$407F` put by it.

## Results

a2vm's cost model (not yet measured on the card: milestone 0), f121 and
fastpath, the replay's calls from entry to return (the return's bank
switch waits for the mirror's drain on F1.2.1). Walk, copy, the copies'
soft-switch writes and draw are the profiling build's (`--breakdown`,
f121), with the count of those writes (`copy_switch_writes`, from
`loader.copy_groups`). 0 differing bytes, 0 stray writes and the SHR
writes equal to the model on every frame, both runs.

| Frame | Records | Bytes | Batches / strips | f121 ms | fastpath ms | walk / copy / switches / draw, f121 | Switch writes | Screen stores |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| still-1, still-2, still-3 | 721 | 5,969 | 1 / 1 | 16.90 | 15.86 | 2.99 / 5.19 / 0.27 / 8.66 | 176 | 8,519 |
| demo-01 | 361 | 3,119 | 1 / 2 | 33.24 | 22.30 | 2.24 / 6.07 / 0.13 / 24.96 | 88 | 25,615 |
| demo-02 | 267 | 2,787 | 1 / 2 | 32.28 | 23.78 | 2.34 / 7.93 / 0.15 / 22.03 | 100 | 22,586 |
| demo-03 | 329 | 2,881 | 1 / 2 | 29.27 | 19.98 | 2.13 / 4.70 / 0.13 / 22.45 | 86 | 22,792 |
| demo-04 | 214 | 2,228 | 1 / 2 | 26.82 | 18.80 | 1.97 / 4.52 / 0.11 / 20.35 | 76 | 20,610 |
| demo-05 | 181 | 1,991 | 1 / 1 | 29.17 | 19.30 | 1.86 / 2.79 / 0.10 / 24.51 | 69 | 24,833 |
| demo-06 | 248 | 2,386 | 1 / 2 | 31.30 | 21.21 | 1.97 / 4.39 / 0.11 / 24.96 | 75 | 25,280 |
| demo-07 | 468 | 4,134 | 1 / 2 | 31.55 | 23.48 | 2.71 / 7.34 / 0.21 / 21.43 | 141 | 21,719 |
| demo-08 | 668 | 5,350 | 1 / 2 | 26.38 | 19.00 | 2.90 / 6.91 / 0.23 / 16.50 | 151 | 16,597 |
| demo-09 | 785 | 5,987 | 1 / 2 | 21.45 | 18.76 | 2.95 / 6.37 / 0.23 / 12.11 | 154 | 11,657 |
| demo-10 | 1,227 | 8,944 | 2 / 3 | 34.34 | 29.88 | 3.92 / 8.89 / 0.34 / 21.48 | 221 | 19,339 |
| demo-11 | 1,198 | 8,755 | 2 / 3 | 35.09 | 29.96 | 3.99 / 8.84 / 0.32 / 22.20 | 213 | 20,184 |
| e1m3-1 | 520 | 3,806 | 1 / 2 | 28.25 | 19.34 | 2.16 / 6.26 / 0.13 / 19.90 | 83 | 20,230 |

Against NATIVE.md's 9.2-16.9 ms standing still and 23.8-39.7 ms in the
demo on F1.2.1: still at the top of its range; the demo frames 21.5-35.1,
at or below theirs. The strips are those of `loader.stage_plan`, a model
of the gather. The screen stores count every store, rows painted twice
included; the capture's "screen bytes written" (8,443 still) counts
bytes.

On F1.2.1 the draw is bound by the mirror's drain (0.985 µs a screen
byte: 8.3 ms still, 24.9 ms on demo-01); the same draw on fastpath takes
8.3 and 14.7 ms. The copies need RAMRD and `$C073` writes, which wait for
the drain, so they cannot overlap it: on F1.2.1 this scheme's floor is
the drain plus the copies, and the replay is one walk (2-4 ms) above it.

The synthetic streams (the same checks, all passed):

| Stream | Records | Batches / strips | f121 ms | fastpath ms | walk / copy / switches / draw, f121 | Screen stores |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| synth-batches | 1,773 | 2 / 4 | 85.38 | 67.76 | 9.10 / 22.90 / 1.02 / 53.02 | 63,743 |
| synth-chains | 795 | 1 / 2 | 26.66 | 22.77 | 4.71 / 8.56 / 0.49 / 13.18 | 17,905 |
| synth-colormaps | 475 | 1 / 2 | 30.10 | 25.67 | 3.01 / 10.69 / 0.33 / 16.26 | 24,986 |
| synth-fuzz | 477 | 1 / 1 | 37.12 | 29.57 | 1.50 / 4.32 / 0.13 / 31.26 | 27,455 |
| synth-mixed | 1,018 | 1 / 2 | 43.37 | 32.89 | 4.72 / 9.89 / 0.49 / 28.58 | 32,354 |
| synth-overlay | 1,051 | 1 / 1 | 29.14 | 16.65 | 2.04 / 4.72 / 0.14 / 22.34 | 22,745 |
| synth-pages | 1,079 | 2 / 3 | 46.47 | 41.66 | 4.48 / 14.95 / 0.46 / 26.96 | 57,340 |
| synth-rows | 535 | 1 / 1 | 15.55 | 14.63 | 3.16 / 5.31 / 0.34 / 6.99 | 7,335 |
| synth-steps | 549 | 1 / 2 | 35.58 | 29.98 | 3.32 / 14.49 / 0.40 / 17.60 | 28,682 |
| synth-strips | 316 | 1 / 2 | 24.45 | 21.36 | 2.92 / 8.63 / 0.28 / 12.88 | 15,119 |

The card disk (`disk.py --check`, 32 runs a frame, VBL-timed by the
runner itself on a2vm's clock): every CRC equal to the reference's; 16.2
ms standing still, 21.8-35.0 ms in the demo, within a VBL's resolution
(0.6 ms) of the harness. On the card it needs the memory API (F1.1.4 or
later) and says so when it is missing.

## The record layout

The replay reads **upstream's record format** (`lists.inc`: the kinds,
fields and sizes, bank `$1D`'s records as captured), packed by column
into W with `K_NEXT` dropped; the loader changes only each texture
record's texel source (upstream's 24-bit address to a RamWorks
bank:address of a copy of its 128 bytes) and turns the covering record
of each covered range into its W address. That is the shipping replay
code and placement for F1.2.1, but not the shipping record layout, which
the native producers (milestone 7) would change:

- records written in production order to the aux-0 staging area with a
  column tag, bucketed into W by column (MEMORY_MAP section 8);
- texture sources as the level loader places texture columns: a
  RamWorks bank and an address in `$0200-$BFFF`, never an IIgs address;
- the gather's request (the stage bytes and the way to copy) emitted by
  the producer with the record: the walk (2-4 ms a frame) would go;
- a fill's bytes by row parity (even rows', odd rows'), not first row's
  and second row's;
- `R_CMP` could hold the native colormap page.
