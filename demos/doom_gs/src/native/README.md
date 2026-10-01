# src/native: the native record replay (milestone 5), the math (milestone 6), the front end (milestone 7)

The replay is described first; the math has its own
[`MATH.md`](MATH.md); the renderer's front end is the last section, "The
front end (milestone 7)".

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
| `loader.py` | A capture directory into an a2vm image placed per MEMORY_MAP section 8 (below); refuses records the replay cannot draw safely; marks the fuzz records that must be drawn in place; models upstream's screen stores and the replay's strips, copy groups and fuzz queue |
| `a2run.py` | Runs an image on a2vm with snapshots around each replay call and the cost model; compares snapshots for stray writes |
| `replay_check.py` | The harness: every frame, captured and poisoned screen, against the reference; times |
| `synth.py` | Synthetic record streams with upstream's truth from `ref816 --call` |
| `disk.py` | The card disk `build/native/REPLAY.hdv` (200 timed runs a frame), and its run on a2vm (`--check`, with the memory API) |
| `sizes.py` | Each area's bytes used and left (`make sizes`) |

## Commands

From `demos/doom_gs`, with the captures of `tools/ref816/capture.py`
(which now also keeps the fuzz table, `fuzz.bin`), a2vm and ref816 built:

```
make -C src/native                                  # the three builds
make -C src/native sizes                            # the areas
python3 tools/native/replay_check.py --breakdown    # the 15 captured frames
python3 tools/native/synth.py                       # 12 synthetic streams
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
   - `K_OVL`: RAMRD on, the drawer in aux 0 `$0200` (it reads the
     screen), RAMRD off;
   - `K_FUZZ`: its column, first row, count and fuzz position go into
     the fuzz queue (aux 0 `$02C0-$03FF`, written with RAMWRT on), while
     it has room for them (80 records a strip);
   - `K_FUZZNOW` (a `K_FUZZ` the loader marked), and a `K_FUZZ` the full
     queue has no room for: drawn in place, as a `K_OVL`.

   After the strip's last column: RAMRD on, the queued fuzz records
   drawn in their order, RAMRD off (below, "The fuzz queue"). RAMWRT off
   (the bus cycle waits for the mirror's drain on F1.2.1), then the
   covered ranges of the strip's columns are zeroed.

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

### The fuzz queue

A fuzz record reads the screen, so it runs with RAMRD on. On F1.2.1 a
RAMRD write (`$C002`, `$C003`) is a `$Cxxx` access, and it waits until
the firmware's coalescer has sent every screen byte written so far to
the motherboard. The coalescer scans each 256-byte page it sends whole,
two clocks a byte, so the scattered bytes of a column (one a 160-byte
row) drain at about 4 Apple cycles each against one for a full page
(`docs/results/fuzz-timing-2026-09-30.md`). Drawn in place, a fuzz record
waits twice on scattered bytes: at `RDAUX` for the columns drawn since
the last wait, at `RDMAIN` for its own. That made the frames with fuzz
11-40% slower on the card than a2vm predicted before its model had the
scan.

So the draw queues them, and after the strip's columns draws the queue
in one RAMRD window: its `RDAUX` waits for the strip's dense backlog,
and the fuzz columns' scattered bytes drain once, at the strip's
`WRMAIN`. demo-10 went from 48.1 to 36.2 ms on the card
(`docs/results/replay-card-2026-09-30.md`).

Drawing a fuzz record late is right unless a later record of its column
paints one of the rows it reads or writes, rows `R_ROW - 1` to
`R_ROW + R_COUNT`. The loader finds those (`loader.mark_fuzz`) and
writes them into W as the port's own kind **`K_FUZZNOW` (4)**, which
upstream never uses (`lists.inc` has no kind 4); its fields are
`K_FUZZ`'s, and the replay draws it in place. Later fuzz records count
too, so that the order never matters: two unmarked fuzz records of a
column touch neither's rows, and a record drawn in place because the
queue is full may go before the queued ones. In the captures 3 of 188
fuzz records are marked, all in demo-09; drawing those late too changes
1 byte of demo-09. In the game the producers (milestone 7) set the mark.

The queue is four arrays of 80 bytes (column, first row, count,
position) in aux 0 `$02C0-$03FF`, beside the drawers: written in the
draw pass with RAMWRT on, read with RAMRD on, never a video window. Its
count is zero page `gdx`, the gather's, which is free during the draw.
The captures queue at most 65 records a strip (demo-11); a full queue
only costs time.

## Memory

MEMORY_MAP section 8's addresses, and how much of each area the build
takes (`make sizes`):

| Area | Content | Used of |
| --- | --- | ---: |
| zero page `$48-$6F` | the replay's state; the gather and the drawers alias the draw's temporaries, the fuzz queue's count the gather's `gdx` | 39 of 40 |
| page 1 `$0100-$01B4` | 12 gather descriptors of 12 bytes, the per-row copy loop (37 bytes); the stack stays at or above `$01C0` | 181 of 192 |
| main `$0800-$0BFF` | `CMPA`, `CMPB`, `TEXLO`, `TEXHI` | 406 bytes of tables |
| main `$17C2-$17FF` | gather scratch | 9 of 62 |
| W `$6000-$7FFF` | a batch of records (the replay only reads it) | up to 8,192 |
| W `$8000-$BFFF` | the texel stage, and its pointer list from the top | 16,384 |
| card bank 2 `$D000-$DBD0` | texture row pairs, landing `RTS` | 3,025 of 3,072 |
| card bank 2 `$DC00-$DCFC`, `$DD00-$DDFC` | fill chains, even and odd rows | 253 + 253 of 512 |
| card bank 2 `$DE00-$DFFF` | the draw pass | 509 of 512 |
| card `$F900-$FEFF` | batches, strips, gather, cold draw helpers, the fuzz queue's code | 1,165 of 1,536 |
| aux 0 `$0200-$02BF` | the fuzz and overlay drawers | 113 of 192 |
| aux 0 `$02C0-$03FF` | the fuzz queue: 80 records of 4 bytes, as four arrays | 320 |
| aux 0 `$0800-$0BFF` | `FUZZDARK` (per level), `ROWLO`, `FZDIR`, `ROWHI` | 706 bytes of tables |

The replay writes only its zero page, page 1 `$0100-$01B4` and the stack
from `$01C0` up to its caller's S (it takes 14 bytes below it, measured),
main `$1400-$153F` (the covered ranges it clears), main `$17C2-$17FF`, W
`$8000-$BFFF`, aux 0 `$02C0-$03FF` (the fuzz queue) and aux 0
`$2000-$88FF`; the row-block patches are restored
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
| Fuzz records queued and drawn after each strip's columns; the loader marks the ones that must be drawn in place (`K_FUZZNOW`) | Upstream draws each in place: on the IIgs a screen read costs nothing more. On F1.2.1 the RAMRD writes around each would wait for the coalescer's scan of scattered bytes ("The fuzz queue") |
| One column needing more than the 16 KB stage stops the replay (`BRK`, code 1) | It needs over 125 texture records in one column; the loader's stage model refuses such a frame first. Upstream has no such limit. In the renderer's game build (`-D RELEASE`, milestone 8, `docs/RENDER-MASKED.md` 6.1) the column is cut instead: drawn with the records gathered before the first that did not fit, its covered range cleared, `STATUS` = `ST_RECORDS` (through the bucket pass's `bk_cut`) |
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

`synth.py` makes 12 synthetic streams (every kind, `K_OVL` and `K_TEXC`
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
outside the range, so every row it keeps or loses shows. Two streams
test the fuzz queue. `fuzzedge` puts a shadow in each column over two
walls, then a later record of each kind (texture, fill, automap pixel,
shadow) that paints the row just above it, the row just below it, rows
inside it, or one row clear of it above or below; the shadow's first
(last) row reads the row above (below), so drawing it late shows in the
pixels whenever it was due in place. In half of the columns where that
later record is a shadow above or below, a one-row fill on its far side
makes it be drawn in place: the first shadow must then be drawn in place
too when they touch (a mark that ignored later shadows would draw it
after), and may wait when they do not. Its three strips never fill the
queue: 112 shadows are marked, 107 queued. `fuzzfull` puts 3-4 shadows
in each column over a wall, two strips of several times 80 queued
records, some of them under a later record: with the default seed 160
queued, 375 in place because the queue was full, 33 marked.

`tests/test_native_replay.py` runs all of it, checks the generated code
byte by byte (every row block's entry opcode and store address, both fill
chains, the tables), the loader's refusals and its fuzz mark at every
edge, the image's fill, and plants 19 bugs in a scratch copy of the
sources and two in the loader to show the checks fail (differing bytes
captured / poisoned; stray bytes; SHR writes against the model):

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
| a `K_FUZZNOW` queued as a `K_FUZZ` | synth-fuzzedge | 166 / 166 differing |
| the loader's mark missing (every shadow queued) | synth-fuzzedge | 166 / 166 differing |
| the loader's mark blind to later shadows | synth-fuzzedge | 13 / 13 differing |
| the queue never full | synth-fuzzfull | 5,966 / 5,967 differing, 858 / 859 stray bytes (aux 0 from `$0400`) |
| a record the full queue has no room for dropped | synth-fuzzfull | 3,731 / 3,731 differing |
| the queue never drawn | synth-fuzzfull | 1,816 / 1,816 differing |

The same five cut bugs on the `rows` stream of `synth.py`'s default seed:
0 / 0 differing (the cut skipped; 8,945 SHR writes for 7,335), 249, 241,
16 and 23 differing bytes.

`disk.py --check` runs the card disk on a2vm with its memory API, and
checks the first frame's load with snapshots around it: no video write
outside the screen (the old runner, which restored main `$0200-$5FFF` by
CPU, makes over 16,000: the test plants it back), main `$0878-$087F`
(a sentinel there) untouched, one memory-API request, colormap B's level
0 at `$4078-$407F` put by it. It exits 1 when a CRC differs, the load
check fails, the runner's table does not show its VBL counts' times, or
the loop without the replay takes as many VBLs as the loop with it (a
base loop that calls the replay: the test plants a `SEC` before
`timed`'s `ROR withrep`).

## Results

a2vm's cost model (not yet measured on the card: milestone 0), f121 and
fastpath, the replay's calls from entry to return (the return's bank
switch waits for the mirror's drain on F1.2.1). Since 2026-09-30 the f121
profile models the coalescer's page scan (`tools/a2vm/README.md`, "The
video mirror"); "no scan" is the same run with `coalescer 0`, the model
before (fastpath has no barrier on SHR bytes, so the scan does not change
it). Walk, copy, the copies' soft-switch writes and draw are the
profiling build's (`--breakdown`, f121 with the scan), with the count of
those writes (`copy_switch_writes`, from `loader.copy_groups`). The fuzz
records: queued, marked `K_FUZZNOW`, drawn in place because the queue was
full (`loader.stage_plan`). 0 differing bytes, 0 stray writes and the SHR
writes equal to the model on every frame, both runs, in both models.

| Frame | Records | Bytes | Batches / strips | Fuzz queued / marked / full | f121 ms | f121 ms, no scan | fastpath ms | walk / copy / switches / draw, f121 | Switch writes | Screen stores |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| still-1, still-2, still-3 | 721 | 5,969 | 1 / 1 |  | 17.09 | 17.02 | 15.96 | 2.98 / 5.25 / 0.29 / 8.68 | 176 | 8,519 |
| demo-01 | 361 | 3,119 | 1 / 2 |  | 33.44 | 33.27 | 22.34 | 2.24 / 6.05 / 0.15 / 25.13 | 88 | 25,615 |
| demo-02 | 267 | 2,787 | 1 / 2 |  | 32.52 | 32.31 | 23.80 | 2.33 / 7.91 / 0.17 / 22.25 | 100 | 22,586 |
| demo-03 | 329 | 2,881 | 1 / 2 |  | 29.47 | 29.30 | 20.00 | 2.13 / 4.68 / 0.13 / 22.62 | 86 | 22,792 |
| demo-04 | 214 | 2,228 | 1 / 2 |  | 27.00 | 26.84 | 18.82 | 1.96 / 4.50 / 0.13 / 20.51 | 76 | 20,610 |
| demo-05 | 181 | 1,991 | 1 / 1 |  | 29.27 | 29.18 | 19.31 | 1.85 / 2.79 / 0.11 / 24.60 | 69 | 24,833 |
| demo-06 | 248 | 2,386 | 1 / 2 |  | 31.65 | 31.32 | 21.23 | 1.97 / 4.39 / 0.12 / 25.28 | 75 | 25,280 |
| demo-07 | 468 | 4,134 | 1 / 2 |  | 31.77 | 31.58 | 23.52 | 2.71 / 7.36 / 0.23 / 21.61 | 141 | 21,719 |
| demo-08 | 668 | 5,350 | 1 / 2 | 12 / 0 / 0 | 26.46 | 26.34 | 19.09 | 2.90 / 6.92 / 0.24 / 16.52 | 151 | 16,597 |
| demo-09 | 785 | 5,987 | 1 / 2 | 23 / 3 / 0 | 21.86 | 21.25 | 18.90 | 2.95 / 6.38 / 0.25 / 12.43 | 154 | 11,657 |
| demo-10 | 1,227 | 8,944 | 2 / 3 | 59 / 0 / 0 | 33.28 | 32.89 | 30.11 | 3.91 / 8.93 / 0.37 / 20.26 | 221 | 19,339 |
| demo-11 | 1,198 | 8,755 | 2 / 3 | 91 / 0 / 0 | 34.06 | 33.67 | 30.23 | 3.98 / 8.89 / 0.35 / 20.99 | 213 | 20,184 |
| e1m3-1 | 520 | 3,806 | 1 / 2 |  | 28.44 | 28.29 | 19.39 | 2.16 / 6.23 / 0.13 / 20.05 | 83 | 20,230 |

Against NATIVE.md's 9.2-16.9 ms standing still and 23.8-39.7 ms in the
demo on F1.2.1: still at the top of its range; the demo frames 21.9-34.1,
at or below theirs. The strips are those of `loader.stage_plan`, a model
of the gather. The screen stores count every store, rows painted twice
included; the capture's "screen bytes written" (8,443 still) counts
bytes.

The fuzz queue on the frames with fuzz, ms. On the frames without, the
queue costs +0.01-0.04 ms, and +0.12 on still-1, most of it in the copy
phase, whose code did not change but moved (other TURBO cache sets:
not checked further); the scan adds 0.06-0.33 ms to them.

| Frame | Milestone 5 replay, no scan | Milestone 5 replay, scan | Queue, no scan | Queue, scan | Card, milestone 5 disk | Card, queue |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| demo-08 | 26.38 | 27.78 | 26.34 | 26.46 | 29.3 | 26.8 |
| demo-09 | 21.45 | 23.87 | 21.25 | 21.86 | 25.0 | 23.1 |
| demo-10 | 34.34 | 46.04 | 32.89 | 33.28 | 48.1 | 36.2 |
| demo-11 | 35.09 | 47.66 | 33.67 | 34.06 | 49.3 | 36.2 |

The milestone 5 replay under the scan is `docs/results/fuzz-timing-2026-
09-30.md` section 4 (the same model); the card's are the runner's 32
runs a frame (`docs/results/replay-card-2026-09-30.md`), VBL-quantised to
0.625 ms, the second one the prototype of this queue
(`build/fuzz-timing/REPLAY-defer.hdv`), which draws the same records in
the same order. The card stays 0.0-2.9 ms above the model on every
frame, with or without fuzz: that residual has no established cause (the
fuzz timing report, "Adversarial check"); the runner's new BASE column
is the test it proposes.

On F1.2.1 the draw is bound by the mirror's drain (0.985 µs a screen
byte: 8.3 ms still, 24.9 ms on demo-01); the same draw on fastpath takes
8.3 and 14.7 ms. The copies need RAMRD and `$C073` writes, which wait for
the drain, so they cannot overlap it: on F1.2.1 this scheme's floor is
the drain plus the copies, and the replay is one walk (2-4 ms) above it.

The synthetic streams (the same checks, all passed):

| Stream | Records | Bytes | Batches / strips | Fuzz queued / marked / full | f121 ms | f121 ms, no scan | fastpath ms | walk / copy / switches / draw, f121 | Switch writes | Screen stores |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| synth-batches | 1,773 | 14,225 | 2 / 4 | 30 / 79 / 0 | 118.95 | 84.93 | 67.95 | 9.09 / 23.05 / 1.10 / 86.35 | 670 | 63,743 |
| synth-chains | 795 | 6,211 | 1 / 2 |  | 27.12 | 26.74 | 22.84 | 4.69 / 8.63 / 0.53 / 13.54 | 321 | 17,905 |
| synth-colormaps | 475 | 4,577 | 1 / 2 |  | 31.11 | 30.16 | 25.72 | 3.00 / 10.75 / 0.36 / 17.20 | 219 | 24,986 |
| synth-fuzz | 477 | 2,954 | 1 / 1 | 80 / 119 / 42 | 59.96 | 36.44 | 29.73 | 1.51 / 4.34 / 0.14 / 54.02 | 82 | 27,455 |
| synth-fuzzedge | 675 | 5,276 | 1 / 3 | 107 / 112 / 0 | 97.10 | 64.88 | 49.27 | 2.56 / 11.38 / 0.35 / 83.08 | 209 | 56,097 |
| synth-fuzzfull | 751 | 4,176 | 1 / 2 | 160 / 33 / 375 | 79.76 | 44.57 | 32.34 | 1.62 / 5.55 / 0.16 / 72.56 | 97 | 32,898 |
| synth-mixed | 1,018 | 7,451 | 1 / 2 | 16 / 45 / 0 | 62.36 | 43.10 | 32.98 | 4.71 / 9.96 / 0.52 / 47.48 | 318 | 32,354 |
| synth-overlay | 1,051 | 5,566 | 1 / 1 |  | 49.27 | 29.17 | 16.66 | 2.04 / 4.75 / 0.16 / 42.42 | 95 | 22,745 |
| synth-pages | 1,079 | 8,611 | 2 / 3 |  | 47.12 | 46.62 | 41.78 | 4.46 / 15.04 / 0.51 / 27.41 | 308 | 57,340 |
| synth-rows | 535 | 4,657 | 1 / 1 |  | 15.78 | 15.63 | 14.69 | 3.15 / 5.36 / 0.36 / 7.12 | 220 | 7,335 |
| synth-steps | 549 | 5,391 | 1 / 2 |  | 36.84 | 35.64 | 30.05 | 3.30 / 14.55 / 0.43 / 18.81 | 257 | 28,682 |
| synth-strips | 316 | 3,476 | 1 / 2 |  | 24.90 | 24.49 | 21.37 | 2.91 / 8.65 / 0.30 / 13.29 | 183 | 15,119 |

With the scan, the streams with many records that toggle RAMRD in place
are much slower: synth-overlay (637 automap pixels) 29.2 to 49.3 ms,
synth-fuzz (119 marked shadows, 42 in place for want of room) 36.4 to
60.0, synth-mixed 43.1 to 62.4. The captures have no automap pixels; the
automap's overlay mode has one a pixel of each automap line over the
view (not captured, so how many is not known), each a RAMRD pair around
one byte. They could be queued the same way (one pixel, so the
mark's rows are its own row only); that is not done.

The card disk (`disk.py --check`, 200 runs a frame, VBL-timed by the
runner itself on a2vm's clock, f121 with the scan): every CRC equal to
the reference's. The runner now prints the loop with the replay, the
loop without it and their difference, each in ms a run at 50 Hz; at 200
runs one VBL is 0.1 ms a run:

| Frame | Loop | Base | Replay | Harness, f121 | Replay, no scan |
| --- | ---: | ---: | ---: | ---: | ---: |
| demo-01 | 34.5 | 0.9 | 33.6 | 33.44 | 33.2 |
| demo-02 | 33.5 | 0.8 | 32.7 | 32.52 | 32.3 |
| demo-03 | 30.4 | 0.9 | 29.5 | 29.47 | 29.3 |
| demo-04 | 27.8 | 0.7 | 27.1 | 27.00 | 26.9 |
| demo-05 | 30.0 | 0.7 | 29.3 | 29.27 | 29.3 |
| demo-06 | 32.5 | 0.8 | 31.7 | 31.65 | 31.3 |
| demo-07 | 33.1 | 1.2 | 31.9 | 31.77 | 31.6 |
| demo-08 | 28.0 | 1.5 | 26.5 | 26.46 | 26.3 |
| demo-09 | 23.6 | 1.6 | 22.0 | 21.86 | 21.2 |
| demo-10 | 36.1 | 2.5 | 33.6 | 33.28 | 33.1 |
| demo-11 | 36.7 | 2.4 | 34.3 | 34.06 | 33.8 |
| e1m3-1 | 29.7 | 1.1 | 28.6 | 28.44 | 28.3 |
| still-1..3 | 18.8 | 1.7 | 17.1 | 17.09 | 17.0 |

The runner's replay time is 0.0-0.4 ms above the harness's (the
difference of two loops, each also loading the batches' records and
restoring the covered ranges every run, and the runner's own
interrupts). On the card it needs the memory API (F1.1.4 or later) and
says so when it is missing.

## The record layout

The replay reads **upstream's record format** (`lists.inc`: the kinds,
fields and sizes, bank `$1D`'s records as captured), packed by column
into W with `K_NEXT` dropped; the loader changes only each texture
record's texel source (upstream's 24-bit address to a RamWorks
bank:address of a copy of its 128 bytes) and turns the covering record
of each covered range into its W address. That is the shipping replay
code and placement for F1.2.1, but not the shipping record layout, which
the native producers (milestone 7) would change:

- the fuzz mark, `K_FUZZNOW` (kind 4, "The fuzz queue"), set by the
  producer on a shadow already written when a later record of its
  column comes over or next to its rows (the loader does it here, from
  the whole column);
- records written in production order to the aux-0 staging area with a
  column tag, bucketed into W by column (MEMORY_MAP section 8);
- texture sources as the level loader places texture columns: a
  RamWorks bank and an address in `$0200-$BFFF`, never an IIgs address;
- the gather's request (the stage bytes and the way to copy) emitted by
  the producer with the record: the walk (2-4 ms a frame) would go;
- a fill's bytes by row parity (even rows', odd rows'), not first row's
  and second row's;
- `R_CMP` could hold the native colormap page.

## The front end (milestone 7)

The renderer's front end, from `R_FillStamps` to `drawMasked`, designed
in [`docs/RENDER.md`](../../docs/RENDER.md) and built in three stages.
**Stage A** is built: the level converter, the tables, frame setup, the
frame-start clears, the BSP walk and its clipping, the sector light and
the plane colours, and the harness to checkpoint A. **Stage B** is built:
`R_StoreWallRange` (the drawseg, the scales, the heights, marks and
textures, the texture edges, the silhouettes and the clips saved for the
sprites), `R_RenderSegLoop` with our own generator of its 13 loops,
genColumn and the masked-only loop, texCol with its exact texture u, the
K_TEX and K_FILL records with the fill spans, and the routine mode of the
harness to checkpoint B (acceptance 2). **Stage C** is built: the plane
stamps (`R_FillStamps`), the weapon skip (`weaponClipSame`'s
bookkeeping), the sky columns and the patchless texture columns, the
whole frame from `R_FillStamps` to `drawMasked` with the render window
loaded by the phase loader, frame mode of the harness to checkpoint C
(acceptance 1) with its timing report, and the milestone 5 replay run on
the records the native front end made. It is a GPL-2 derivative of
upstream's `r_frame65.s`, `r_bsp65.s`, `r_iigs65.s`, `r_wall65.s`,
`r_seg65.s`, `segvar.inc` and `r_list65.s` (the same walk, drawsegs,
openings, records, clips, spans and stamps, written for the 65C02).

| File | What it is |
| --- | --- |
| `rframe.s` | `nr_frame` (the plane stamps, setup, clears, the weapon's clip pass through the seam, the weapon skip, the walk, the last batch), `nr_fillstamps`, `nr_setup`, `nr_clear`, `nr_wskip` |
| `rbsp.s` | `nr_bsp`, the recursion over node frames in W, `nr_side`, `nr_checkbox` (with upstream's `boxPre`), `nr_scan0`/`nr_scan1`, `nr_sub`, the seg loop and `clipwall`, the vertex-angle cache |
| `rlight.s` | `nr_planes` (the sector into the sector frame, its plane colormap row, worldbottom, the floor and ceiling colours), `nr_walllight` (for stage B) |
| `auxlc.s` | The aux card's reads in `ALTZP` windows from W: `ax_vtox`, `ax_tanto`, `ax_tan3`, `ax_tan4` |
| `far.s` | Card bank 1 from `$DC43`: `far_get`, `far_put`, the vertex-angle gather and write-back, the stamp clear, the `FSTEP` gather (stage B); the phase loader `far_wload` (stage C, segment `RLOAD`) |
| `rwall.s` | `nr_storewall` (stage B): `R_StoreWallRange` with its helpers (the axis differences and distAny, scaleFast with normD and sinA, scaleSlow with `R_ScaleFromGlobalAngle`, rowMod, edgeAL, the edges and edgeSlow, saveClip, the silhouettes); the drawseg built in W and put into `RENDB` |
| `rseg.s`, `rseg.inc` | `nr_segloop` (stage B): `R_RenderSegLoop`'s prologue and the choice of its loop, genColumn, the masked-only loop, segDone, texCol and tcExact, the tiers and their K_TEX records, the ceiling and floor fills with their spans and K_FILL records; the loops' macros |
| `rsky.s` | Stage C: `sky_col` (skyColumn, ceilSky: a K_TEX record of the sky's slot) and `tier_flat` (tierFlat: a column without a patch as a K_FILL of the texture's colour, with its span cut) |
| `rrec.s` | The record batch in W and its staging (aux 0 `$A000`, then the spill banks); `rec_start` at the frame's start |
| `gen/segloops.s` | The 13 loops of `segvar.inc`, written by `tools/native/seggen.py` (build output) |
| `rdriver.s` | The a2vm test driver (not the game): one frame with the mouse card's VBL interrupt on (`drv_frame`; `drv_wframe` loads the render window first), the seam's `wclip_pass` (floorclip, `FR_VIS`, `MM_WPOK`), checkpoint A's lockstep `nr_storewall` and staging stubs (`-D LOCKSTEP`), routine mode's `drv_wall` and `drv_seg`, and a descriptor loop for bulk cases (`rt_side`, the aux reads) |
| `render.cfg`, `render.mk` | The ld65 map and the builds into `build/native/render/obj`: `rtest` and `rprof` (checkpoint A's, with the lockstep stub; phases marked), `rwall` and `rwprof` (the whole front end: stages A, B and C); `math.s` is assembled again with `-D RENDER` (the renderer's subset; `pta16` reads `tantoangle` from the aux card). `rwall.w` with a level's `wtables.img` is the render window's image |

The host tools, in [`tools/native`](../../tools/native):

| Tool | What it does |
| --- | --- |
| `rlayout.py` | Every address, bank, record and zero-page byte of the front end; writes `rlayout.inc`; checks overlaps and budgets |
| `rendercap.py` | The captures: five ref816 runs, each twice (choose, then capture), the frames' dumps at `R_FillStamps`, the seam, `R_RenderBSPNode`, early flushes and `drawMasked`, and the call logs, stored compressed per frame; a full dump of each level as the converter's source |
| `levelconv.py` | A reference state into the native level (`render-level 1`): segs, nodes, subsectors, sectors, sides, the vertex cache, one 128-byte texel slot per texture column and the sky's, the W tables; its checks |
| `rtables.py` | The constant tables from the reference's RAM, checked against their formulas; the aux card's and `FSTEP`'s images |
| `framestate.py` | A captured frame into a2vm records: the render inputs, the frame block, the dynamic level fields, the vertex cache from upstream's, the seam |
| `rcanon.py` | Both machines' outputs in one canonical form, and their diff |
| `render_check.py` | The harness: checkpoint A on the frames, routine mode (`--routines checkpoint` or `all`, `--cases`: checkpoint B), frame mode (`--frame-mode`: checkpoint C, acceptance 1), both poisoned fills, the write-log filter, the timing (`--timing`, `--routine-timing`, `--frame-mode --timing --report`), the sizes (`--sizes`) |
| `sidecheck.py` | Check A3: upstream's `viewSide` in `mathref batch` against `nr_side` on a2vm |
| `routinecap.py` | Stage B's captures: for each run of `rendercap.py`, a survey (a call log of the wall calls, their seg loop calls, early flushes and the paths they take) and a dump run: every wall call of the captured frames at its entry and return, and its seg loop's, stored as one case |
| `routinesynth.py` | Synthetic cases for the paths no capture reaches: a captured call recorded whole (`--capture`), changed by pokes, upstream's truth by `--call` |
| `segdesc.py` | A case's entry state as the native's: the frame block, the clips, spans and plane state, the wall's arguments, the seg descriptor |
| `seggen.py` | The 13 seg loops (`gen/segloops.s`) |
| `framesynth.py` | Stage C's synthetic frames: a captured frame's `R_FillStamps` recorded whole (`--capture`), changed by pokes, the frame run by `--call` from display's `JSL` to each point; for patchless columns the level converted again with the same pokes |
| `render_replay.py` | The milestone 5 replay (`loader.py`, `replay.s`) on the native front end's records and texel slots with upstream's masked-phase records after them: the SHR bytes against ref816's |

### Commands

From `demos/doom_gs`, with ref816, a2vm, cc65, `tools/native`'s mathref
(`make -C tools/native`) and the link map:

```
python3 tools/native/rendercap.py          # 177 frames, 13 level sources, ~1 min
python3 tools/native/levelconv.py --all    # every level source, all checks
python3 tools/native/rtables.py            # the tables, checked
make -C src/native -f render.mk            # rtest and rprof
make -C src/native -f render.mk sizes
python3 tools/native/render_check.py       # checkpoint A, 354 runs, ~15 s
python3 tools/native/render_check.py --fills a5 --timing
python3 tools/native/sidecheck.py          # check A3, 9 maps, ~80 s
python3 tools/native/routinecap.py         # 3,595 wall calls, 162 MB, ~30 s
python3 tools/native/routinesynth.py       # 13 synthetic cases, ~40 s
python3 tools/native/render_check.py --routines checkpoint   # ~90 s
python3 tools/native/render_check.py --routines all          # ~5 min
python3 tools/native/render_check.py --routine-timing        # ~90 s
python3 tools/native/framesynth.py         # 11 synthetic frames, ~20 s
python3 tools/native/render_check.py --frame-mode            # 188 frames, ~90 s
python3 tools/native/render_check.py --frame-mode --timing \
    --report build/native/render/report.md                   # ~2 min
python3 tools/native/render_replay.py      # 15 frames through the replay
python3 -m unittest discover -s tests -p 'test_native_render*.py'
```

`render_replay.py` also needs milestone 5's captures and build
(`tools/ref816/capture.py`, `make -C src/native`).

### How it runs

On F1.2.1 the tics run in W before the frame, so the frame starts with
the phase loader (`far_wload`, in the card): one RAMRD window on the
render window's image in RamWorks bank 112, which copies the code's pages
(from `$6000` to the page after the end of `MATHW`, 61 pages) and the
per-level tables' pages (`$AF00-$B8FF`: `FLATCM`, `TXBANK` ... `TXHT`)
into main W, 18,176 bytes.

`nr_frame` first makes the plane stamps (`nr_fillstamps`, upstream's
`R_FillStamps`): the stamp of this frame `W_FSC` + 1, `W_FSP` the frame
before's when its view shows (`W_FSW`) with the same first row and row
after it (`W_TOPR`, `W_BOTR`, set to this view's), no plane colour of
the fill bytes (`W_LCC`, `W_LFC` get `$80` in the high byte), and every
128 frames all span stamps refreshed (`fsFill`). It copies the player's
view from the render inputs (`$0370`),
computes viewangle16, the light numbers `LT_BASE` and `LT_FIXED`, the
view's approximate sine and cosine (the math's `sineapprox`, a tables-bank
window) and adds 1 to `validcount`; clears `SOLIDCOL`, the clip arrays
(the clips + 1 as bytes), the drawseg count and `lastopening`; lets the
seam put the weapon's clip pass into `FLOORCLIP` and `FRVIS` (milestone
8's sprite code); keeps the weapon skip (`nr_wskip`, `weaponClipSame`'s
bookkeeping: `FR_SKIP` = `W_FSW` when there is a weapon without a flash,
no automap overlay, not the shadow weapon, and the same vissprite as the
frame before's in `WPREV`, which becomes this one; `WCLIP` = `FLOORCLIP`
at the first frame that skips; `W_WSK`); empties the staging
(`rec_start`); then walks the tree from `numnodes - 1` and flushes the
last batch of records.

The walk fetches each node whole (32 bytes, one `far_get` from `LVMAP`)
into a node frame of W (`$BA00` + 32 a level), decides the side (the
tests for dx or dy 0, else viewSide's sign test, else the two shiftMul
products: always the products, never `c14Bounds`, see "Check A3"),
recurses into the front child with `JSR` (2 bytes of stack a level),
checks the back box (the view's case, `boxPre`, the corners' angles by
`pta16`, `viewangletox` from the aux card, `nr_scan0`) and continues
into the back child in the same frame. A subsector's record (4 bytes)
names its sector: unless it is the sector of the subsector before
(upstream's `CN_LSEC`), the sector's 16 bytes come into the sector frame,
the plane colours are computed from its light (`SMAP`, `PCMO`, `FLATCM`)
or the fixed colormap, and its `validcount` is stamped (a 2-byte
`far_put`) with a call of `nr_addsprites` (a stub until milestone 8).
Its segs come five at a time (24 bytes each) into the bounce buffer at
`$0200`, their vertices' angles and stamps in one read window (the card's
gather), missing angles by `pta16` (the rtest counter `VA_COUNT`), new
ones written back in one write window; each seg is clipped to the view's
columns and `clipwall` calls `nr_storewall` for each open run of
columns, as upstream calls `R_StoreWallRange`.

`nr_storewall` (stage B) takes the walk's arguments (the start and stop
columns, the seg's record in the bounce buffer, the front sector in the
sector frame, the plane colours, worldbottom), marks the line in
`LNMAP`, checks the drawsegs and the openings, fetches the side (and the
back sector) into the sector frame, and makes what upstream's
`R_StoreWallRange` makes, step for step: the distance and offset of the
view from the seg's line (differences along an axis, else distAny's
products), the scales (scaleFast: `qmulh`'s "+ 0 or 1", normD's
`RECIP_TABLE`, the 1.001 step; scaleSlow with `R_ScaleFromGlobalAngle`
and a divide for the step), the heights, the marks, the three textures
with rowMod, the masked columns' openings, and the four edges of the
tiers (edgeAL's shared low word, or FixedMul). The drawseg is built in
W's `DSBUF` and put into `RENDB` (32 bytes) when the wall ends; the seg
descriptor goes into the seg page (zero page `$48-$AE`: the edges, the
flags, the rows of a column, texCol's state) and the spill (`SD_*`).
rw_scalestep is kept in the frame block from wall to wall (`RW_STEP`):
scaleSlow leaves it for a wall of one column, as upstream does, and the
edges of that wall use it.

`nr_segloop` computes the wall light (`nr_walllight`, then one colormap
page for the seg, or `W_LV` when the light varies along it), the tiers'
texturemid >> 7, and each column's `FSTEP` and light distance d:
`far_fstep`, in the card, steps the seg's scale from rw_scale -
rw_scalestep 24 bits a column (as upstream's `STEP8` and `STEP24W` do)
and reads the table in the four `FSTEP` banks, one RAMRD window a seg,
a `$C073` write when the bank changes; the loops read each column's
from W. Then the fill bytes (colormap B's and A's byte of level 0 for
the plane colours, kept from seg to seg as upstream's `W_LCC`, `W_LFC`)
and the loop of the seg's kind: one of the 13 generated loops, genColumn
for every column (`genloop`), the masked-only loop (`vmask`), or none.
A generated loop is segvar.inc's: the rows as bytes, the edges stepped
by bytes 1-3 (`STEP8E`), a closed column (floor clip + 1 of 0) through
genColumn, whose rows are signed words and whose edges step 32 bits. A
tier calls `texcol` when its column has none yet: the texture u exact
(`tcexact`: `finetangent` from the aux card, the products of TANPROD) at
a span's ends, 8, 2 or 1 columns apart, and linear between with 8 bits
of fraction; then `tierdraw`: the column's texel slot, frac = (row - 85)
fracstep + texturemid >> 7 (two `mul8`), the K_TEX record. The fills
check the span of the frame before (`W_FSP`, the same bytes: only the
other rows) and make the span of this frame (`W_FSC`), then the K_FILL
record. A sky ceiling (stage C, `sky_col`) is a K_TEX record of the
sky's texel column ((viewangle >> 16) + xtoviewangle[x]) >> 6, its slot
in the level's sky slots (`SKYBANK`, `SKYLO`, `SKYHI` of the frame
block), one texel a row from texturemid 100, the page of the fixed
colormap or of colormap A's full light; as upstream, the wall's yl goes
through `DC_ROW` and the column's step is left at the sky's. A texture
flagged with patchless columns (bit 7 of `TXBANK`) looks its column up in
the level's `TXFLAT` bitmap (`LVMAP`, two 1-byte `far_get`s); a column
without a patch (`tier_flat`) becomes a K_FILL of the texture's colour
(colormap A's and B's full-light bytes) after the span cut of
`R_DrawColumnFlat`'s `fillCol`. Records go into the 256-byte batch in W
with their column byte and are flushed into the staging (aux 0 `$A000`,
then banks 9-10) with one RAMWRT window an area. After the loop the masked columns go into the
openings (low bytes in aux 0, high bytes in `OPENHI`), a single sided
wall with marks makes its columns solid, and `DIDSOLID` tells the wall.
Back in `nr_storewall`: the silhouettes for a two sided wall that made a
column solid, the clips saved into the openings for the sprites
(`saveceil`, `savefloor`: one RAMWRT window each), the drawseg's columns
(`DSX1`, `DSX2`).

Not reproduced: a column seen from behind (a grazing view: a wall's
first or last column just past the seg's end), where upstream reads past
its tables, into its own code (scaleSlow's sine of a negative index)
and live data (`tcExact`'s texture angle past `finetangent` part 4). The
native code takes a rule of its own there (RENDER.md 3.9): the scale
256, vanilla DOOM's (`RULE_SINE`), and the tangent table's nearer end
(`RULE_TANGENT`), and sets the rule's bit in the frame block's `RULES`;
the harness reports any run with a rule. Stage B stopped the frame
there. A texture without slots stops the frame (`ST_TEXTURE`, `BRK` in
every build; a level `levelconv.py` accepts has none), as do full node
frames (`ST_DEPTH`) and a full staging (`ST_RECORDS`, milestone 8's
decision). (Stage B's `ST_SKY` and `ST_FLAT` are gone: stage C draws
both.)

### Memory

As [`docs/MEMORY_MAP.md`](../../docs/MEMORY_MAP.md) section 12 lists it
(RENDER.md risk 13's proposals, taken): zero page `$00-$05` (far layer),
`$18-$38` (overlay 1, 33 of 42 bytes) and `$48-$AE` (overlay 2, the seg
page, 103 of 104 bytes; stage B), the spill `$0280-$02BE` (63 of 128
bytes: the walk's, the seg descriptor's cold part, genColumn's words),
the frame block `$0310-$036F` (86 of 96 bytes; stage C adds the sky's
slot), the render inputs
`$0370-$039F`, the level's counts `$03A0-$03A3`, `FRVIS` `$0CA0-$0CC9`
(stage C: the seam's weapon vissprite), the wall setup's
variables `$0DA0-$0DE1` (stage B), `WCLIP` and `WPREV` (stage C: the
weapon skip, `$1800`, `$18A0`), W code from `$6000`, the node frames
`$BA00-$BC7F`, each column's `FSTEP` `$BC80` and masked texture column
`$BDC0`, the sector frame `$BF00`, each column's light distance `$BF28`
and the drawseg being built `$BFC8` (stage B), the far layer at card
bank 1 `$DC43-$DE4C` and the phase loader `$DE4D-$DE81` (stage C); the
drawsegs and `OPENHI` in RamWorks bank 8, the
openings' low bytes at aux 0 `$0C00`, the record staging at aux 0
`$A000`, then banks 9 and 10; the render window's image in RamWorks bank
112 (stage C). Sizes (`make -f render.mk sizes`; the whole front end,
build `rwall`):

| Area | Used | Budget (RENDER.md 3.8) |
| --- | ---: | ---: |
| `rframe.s` | 428 | 500 (stage A), and stage C's part of the 900 below |
| `rbsp.s` + `rlight.s` (with `SMAP`, `PCMO`, the box tables) | 2,688 | 3,400 |
| `auxlc.s` | 146 | 200 |
| `MATHW`, render subset | 1,281 | 1,700 |
| `rwall.s` (with `KS`) | 5,368 | 5,500 |
| `rseg.s` + `rrec.s` (with `PGT`) | 2,946 | 3,800 |
| `segloops.s` (13 loops) | 2,482 | 2,860 |
| stage C: `rsky.s` 273, `nr_fillstamps` and `nr_wskip` in `rframe.s` 201, `rec_start` 13 | 487 | 900 |
| W code, all stages | 15,612 | 20,416 (4,804 left) |
| `far.s` in card bank 1 (the phase loader 53) | 575 | 850 (far layer 500, vertex gather 100, `FSTEP` gather 250) |
| Card bank 1 `$DC00-$DFFF` in all | 642 | 1,024 |

The walk's stack is at most 64 bytes below the driver's S (a2vm's
`--lowest-s-in` over the render code, all 177 frames, the lockstep
build); a wall call, with its seg loop and the math, at most 20 (routine
mode, every case); the whole frame, at most 79 (frame mode, all 188
frames; the interrupt handler's own pushes are not counted). With
MEMORY_MAP's 24 B IRQ allowance that is 103 B, within the render budget
of 112 B (MEMORY_MAP section 2; 96 B before milestone 7's verification,
which found it too small); `render_check.py` and the tests check depth +
24 against it.

### Verification (checkpoint A, RENDER.md 5.1)

**1. The level converter** on all nine maps (13 level sources: E1M1 and
E1M7 from three runs each, the tour's nine maps): every count within its
native limit (the largest, E1M6: 250 sectors, 1,862 segs, 605 nodes,
1,207 vertices; BSP depth at most 19); no sector address with a low word
of 0 (bspSub's "no sector"); the native level decoded back through
`rlayout.py` equal to the bridge Reader's canonical objects in every
rendered field (1,563 objects on E1M1, 3,083 on E1M7); every made texture
column's
slot equal to the reference's 128 bytes at its texel pointer, read again
from `COLDIR` (1,896-5,736 slots a map, the sky's 256 included);
`skypatchnum` a lump of the WAD directory; the sectors' and sides' render
fields read back by the bridge's port reader through the level's
manifest (records with the bridge's new `stride`); the static fields
equal to the bridge's tour dump of the same level load. No slot is
open-ended and no texture of E1 has a patchless column. Texels take 7 to
19 banks a map (E1M2-E1M4 the most).

**2. The tables**: every table read back equal to the reference's RAM;
`FSTEP` entries 512-65,535 equal to 33,554,431 / L; `SMAP`, `PCMO`,
`CMO`, `PGT` equal to their formulas and `c26Reverse` to `PGT` reversed;
`tantoangle[2048]` is ANG45; the same tables in all 13 sources.

**3. Check A3, `c14Bounds`**: upstream's `viewSide` (with `c14Bounds`) on
ref816's machine (`mathref batch`, which now outputs P), from a real
call's registers and return address, X = node × 4 and ND the node's
address (checked: `CORE_NODEADR` is `nodes` + 28 n), against `nr_side`
(the products only) on a2vm: **0 differences in 4,994,932 cases** on the
nine maps: 3,600,000 random (100,000 views a map, each at the four
corners of the fraction byte shiftMul keeps) and 1,394,932 edge cases
(views within 5 of the log difference ±417 on the 23-173 nodes a map that
`c14Bounds` decides, |x| and |y| of 15, 16 and 17, offsets of -32,768).
Every branch the maps' nodes allow was reached (greater, less, the
threshold miss, both small-offset misses, both -32,768 misses, the
fall-backs for |dx| or |dy| over 255); every such node with offsets at
log differences 416 and 417 (computed from `LOGTAB` and `SIGHTLOG`, not
from the generator) had cases at them. The overflow branch cannot be
reached in E1: it needs |K| of at least 10,240 and the nodes' K lie in
-8,192 to 9,504. So upstream's claim holds on these cases and
`c14Bounds` is dropped as RENDER.md 1.9 planned.

**4. The frames**: 177 frames (the 15 of milestone 5, 50 of `newgame`, 50
of the title loop's demo3, 50 of the tour over E1M1-E1M9, and 12 of a
`lights` run that no coverage script replaces: the fixed colormaps 1 and
32 and gamma 2, through upstream's own cheats), each run twice (every
undefined byte `$A5`, then `$5A`), the walk's wall calls going to the
lockstep stub: **354 runs, 0 differences**. Equal to ref816: the list of
3,595 wall calls (start, stop, seg, front sector, floor and ceiling
colour, worldbottom), `validcount` and every sector's stamp at
`drawMasked`, the 4,012 vertex angles computed (ref816's `vtxAngle`
calls, 0-119 a frame), the clears and derived values at the walk's entry
(`CEILCLIP`, `FLOORCLIP` after the seam, `SOLIDCOL`, the drawseg count,
`lastopening`, `LT_BASE`, `LT_FIXED`, viewsin, viewcos, validcount, the
cache's map unit) and the map unit at the end; no write outside the
allowed set (a2vm's write log of every storage but the stack page,
filtered by the writing PC); 2-31 interrupts taken a run.

**Planted bugs** (`tests/test_native_render*.py`, each in a scratch copy):

| Bug | Frame or check | Caught |
| --- | --- | --- |
| a texel slot one column off (`levelconv.py`) | E1M1 | the slot check: "the slot differs from the reference" |
| viewSide's side flipped for dy < 0 (dx 0) | still-1 | the call list from call 0 (start, stop, seg, sector, colours) |
| viewSide's products compared the wrong way | A3 on E1M1; still-1 | 28,320 of 29,436 sides; calls 5 and 6 swapped |
| the plane colours with extralight | title-22 (extralight 2) | the calls' floor and ceiling colours (243, 107 for 245, 111) |
| the fixed colormap ignored by the planes | lights-08 | the calls' colours |
| a sector not stamped | still-1 | 8 sectors' stamps at `drawMasked` |
| the vertex stamp advanced every frame | still-2 | vertex angles computed: 64 for 0 |
| A3's edges aimed at ±317 | A3 on E1M1 | the coverage check: no case at log differences 416 and 417 |
| a store into the hot game globals | still-1 | 48 stray writes (`$1A80`) |
| `R_WallLight`'s contrast + 1 along x | `nr_walllight` against upstream | the offsets and `LT_I` differ |

`nr_walllight` (for stage B) equals upstream's `R_WallLight` (`mathref
batch`) on 64,000 cases: every light level, the fake contrast's angles,
extralight 0-2, gamma 0-4, the fixed colormaps (`sidecheck.py
--walllight`). `ax_tan3` and `ax_tan4` (for stage B) and `ax_vtox`,
`ax_tanto` equal the tables on 160-300 indexes each, the ends included
(bulk runs).

### Verification (checkpoint B = acceptance 2, RENDER.md 5.2)

**Routine mode.** A case is one call of `R_StoreWallRange` of a captured
frame (`routinecap.py`: all 3,595 wall calls of the 177 frames), with
the `R_RenderSegLoop` call it makes. For each routine, twice (every byte
the state does not define `$A5`, then `$5A`), `segdesc.py` builds the
native state from the reference's at the call's entry (the frame's P0
for the level, the zone and the colormaps; the entry's dump for the view,
the light numbers, the clips, `solidcol`, the spans, the drawseg count,
lastopening, rw_scalestep and the plane state; the walk's arguments, or
the seg descriptor), the driver syncs to a VBL and waits so that the
next falls inside the call (the calls are often shorter than a VBL
period), calls `nr_storewall` or `nr_segloop` and flushes the batch; the
outputs (`rcanon.py`) must equal the reference's at the return: the
records the call made by column in order (upstream's walked from each
list's end at the entry through `K_NEXT`; a texture's texels through the
level's texture map), `FLOORCLIP`, `CEILCLIP`, `SOLIDCOL`, didsolidcol,
the spans and covered ranges, `W_LCC`, `W_LFC`, `W_CEILW`, `W_FLOORW`;
for a wall also the drawseg it made (the fields upstream defines: its
scalestep only for two columns or more, a silhouette's height and clip
only with that silhouette), the openings its fields name (the masked
columns 16 bits, the clips their low bytes), `dsX1`/`dsX2`, the count,
lastopening, rw_scalestep and the line's `ML_MAPPED` (set unless the
drawsegs are full; the line must be mapped at `drawMasked`, P3, and no
other bit of `LNMAP` may change); and no write outside stage B's allowed
set (`rlayout.allowed_writes_b`, by the writing PC).

**The synthetic cases** (`routinesynth.py`) for the paths no capture
takes: a captured call recorded whole by ref816's `--capture`, changed by
pokes, run alone by `--call` to its return and stopped at its seg loop's
entry and return. `edgeslow` (a back floor with a fraction of its own:
edgeSlow), `mod16` and `mod16neg` (a row offset of ±45 on a texture 72
high: rowMod's remainder, the vendor's `_Mod16` upstream, `sdiv16`
natively: an indirect comparison, RENDER.md 5.2), `vmask` (a two sided
line with nothing to draw given a mid texture), `closed` (a floor clip of
-1 in a column of a generated loop: genColumn from it), `onecolslow` (a
scaleSlow wall cut to one column: its scalestep and its edges from the
wall before's), `dsfull`, `openfull` (the early returns), `fsgeneral` (a
scale of 80.0) and `segearly` (a seg loop that returns at once); and
`negsine`, a view that sees the wall's first column, and so all of it,
from behind, which stage B refused (`ST_SINE`). Since verification
`negsine`, `grazefirst` and `grazelast` (only the first or last column
behind) are the ruled cases of RENDER.md 3.9: each takes its rules and
equals upstream wherever upstream stays in its tables.

**Results** (2026-09-30, `render_check.py --routines checkpoint`, then
`all`):

| Set | Wall calls equal | Seg loop calls equal | Deferred (a sky column) | Runs |
| --- | ---: | ---: | ---: | ---: |
| checkpoint: 1,000 calls evenly over the calls without a sky, the calls a path of the coverage needed (a v02 loop, scaleSlow), every call with a sky, the synthetic cases | 1,010 | 1,010 | 62 | 4,288 |
| all: every captured call and synthetic case | 3,541 | 3,542 | 62 | 14,416 |

0 differences, 0 stray writes, in both fills; `negsine` refused as it
must be; 91% (checkpoint) and 95% (all) of the runs took an interrupt
inside the call. Every
loop ran: in the checkpoint v02 1, v04 39, v05 24, v06 4, v07 3, v08
23, v10 61, v12 124, v13 59, v14 23, v15 95, v20 28, v28 499 seg loop
calls, genColumn's loop 22, the masked-only loop 1, none (segDone) 4;
and every path of upstream's the captures reach (scaleFast 1,001 walls,
scaleSlow 1 (2 in all), distAny 235, `R_WallLight`'s varying light 198,
fstepHigh 109, tcExact 773, genColumn 22) with the synthetic ones. The
62 deferred calls stop at their first sky column with `ST_SKY` (their
ceiling colour is the sky's); stage C closes them.

**Planted bugs** (`tests/test_native_render_walls.py`, each in a scratch
copy, each case run once, `$A5`):

| Bug | Cases | Caught by |
| --- | --- | --- |
| `qmulh` without its carry | 20 of 40 walls with scaleFast | the drawseg: scale1 14,246 for 14,247 |
| `STEP8E` stepping all four bytes | 3 of 12 seg loops | the records: a fill ending a row off |
| `W_FSP` compared where `W_FSC` is due | 2 of 12 seg loops of `still-2` | the records: 91 columns (fills upstream's spans spared) |
| `W_LV` not set for a seg of one light (upstream's C26 base kept) | 4 of 4 | the records' colormap pages |
| saveClip one column short | 1 of 1 | the openings of `sprtopclip` |
| the fill bytes of an odd first row not swapped | 1 of 1 | the records' B1, B2 |
| the texture u exact every 4 columns, not 8 | 3 of 4 | the records' texels |
| the line not mapped | 2 of 2 | `ML_MAPPED` |
| rw_scalestep of a one-column scaleSlow wall set | `onecolslow` | rw_scalestep |
| edgeSlow with the step and the scale swapped | `edgeslow` | the clips |
| rowMod's negative remainder not corrected | `mod16neg` | the records' texels |
| a closed column not given to genColumn (the generator) | `closed` | the clips |
| fsGeneral shifted one too few | `fsgeneral` | the records' steps |
| a store into the hot game globals | 1 of 1 | the write log |

Two rounding bugs are not in the list because the checks cannot see
them, and neither can a frame: an edge rounded with FRACUNIT for
FRACUNIT - 1 (or the reverse), and `qmulh`'s carry on the scales of far
walls. The loops step an edge's bytes 1-3 only, so its byte 0 (where the
rounding lies) reaches a row only through genColumn's 32-bit steps, and a
difference of 1/65,536 of a row reaches no row in the captures; the
scale of a wall beyond 256 map units is `qmulh`'s result shifted right,
which mostly drops the extra 1 (the bug above shows on nearer walls).

### Verification (checkpoint C = acceptance 1, RENDER.md 5.3)

**Frame mode** (`render_check.py --frame-mode`). Each captured frame,
twice (every byte the frame does not define `$A5`, then `$5A`), on the
whole front end (`rwall`): the render window's image (`rwall.w`'s code,
the level's W tables) in RamWorks bank 112 and W itself filled, so the
frame runs only if the phase loader brings in every byte it needs; the
driver's `drv_wframe` turns the VBL interrupt on (`--speed 1`), loads
the window and calls `nr_frame`. At the walk's entry (`nr_bsp`) the
clears and derived values of checkpoint A, the span stamps and plane
state after `R_FillStamps` and the weapon skip after `weaponClipSame`
must equal P0b's; at the end every output of RENDER.md 2.4 must equal
the reference's at `drawMasked` (`rcanon.frame_truth`): every record of
the frame by column in the order made (upstream's lists walked from
their first page through `K_NEXT`, those of any early flush first; the
native staging and spill by the column byte; a K_TEX's texels through
the level's texture map), `FLOORCLIP`, `CEILCLIP`, `SOLIDCOL`,
didsolidcol, the drawseg count, every drawseg's defined fields and
columns and the openings they name, lastopening, the 8 span planes, the
covered ranges (0), `W_FSC`, `W_FSP`, `W_TOPR`, `W_BOTR`, `W_LCC`,
`W_LFC`, `W_CEILW`, `W_FLOORW`, rw_scalestep, `FR_SKIP`, `W_WSK`,
`WPREV`, `WCLIP`, `validcount` and every sector's, `ML_MAPPED` of every
line, and the vertex angles computed (ref816's `vtxAngle` calls); the
write log (every storage but the stack page, and every soft-switch
write) must hold no write outside the allowed set, by the writing PC:
the render code's (`rlayout.allowed_writes_b`), the phase loader's (W
and its pointer only), the driver's.

**Synthetic frames** (`framesynth.py`) for the paths no capture takes:
`noweapon`, `shadow` (the shadow weapon), `automap` (the overlay:
`automapmode` 3 and the view's row after it 160), `fsfill` and `fswrap`
(the stamps' refresh at 128 and at the wrap), `skyfixed` (the sky under
the fixed colormap 1), `skyodd` (the player's angle's high word ending
in 63: captured angles are multiples of 64, so only this frame shows a
sky column one angle unit off), and `flat`, `flatsky`, `flatv06`, `flatv14` (a
third of every made texture's columns without a patch, on frames with a
sky and with loops of kind 6 and 14; the level converted again from its
source with the same pokes). Each is a captured frame's `R_FillStamps`
recorded whole by ref816's `--capture`, the pokes, then `--call` from
display's `JSL R_FillStamps` to each point (P0, the seam, P0b,
`drawMasked`); the P0 so reached must equal the captured frame's with the
pokes applied. They have no call log (ref816's `--call` and
`--call-log` exclude each other): the vertex-angle count is not
compared and checkpoint A does not run on them.

**The replay on the native records** (`render_replay.py`): for the 15
frames milestone 5 captured, the native frame's staged records, their
texels read from the native level's slots, then upstream's records of
the masked phase (each column's list at `R_DrawLists` after its end at
`drawMasked`; the part before must be the list at `drawMasked`), through
milestone 5's loader and replay on a2vm from the captured screen, both
fills: the SHR bytes must equal the screen after upstream's
`R_DrawLists`, with no stray write and the model's screen stores.

**Results** (2026-09-30):

| Check | Result |
| --- | --- |
| Frame mode (`render_check.py --frame-mode`) | 188 frames (15 `m5`, 50 `newgame`, 50 `title`, 50 `tour`, 12 `lights`, 11 synthetic), 376 runs, **0 differences**, 0 stray writes, no rule of our own taken: 104,011 records (396 of them sky columns, in 14 frames; in the four synthetic flat frames 107-146 texture records a frame become fills of patchless columns), 3,950 drawsegs, 4,012 vertex angles; 31-138 interrupts a run; at most 79 bytes of stack, 103 with the IRQ's 24 (budget 112) |
| Checkpoint A (`render_check.py`) | 177 frames, 354 runs, 0 differences, the stamps and weapon skip at the walk's entry included |
| Routine mode (`--routines all`) | 3,608 cases, 14,424 runs: 3,603 wall calls and 3,604 seg loop calls equal, the 62 with a sky (stage B's deferred) among them; the ruled cases (`negsine`, `grazefirst`, `grazelast`: 3 walls, 2 seg loops) with their rules, equal where upstream stays in its tables; the checkpoint set, 1,072 of each, equal |
| The replay on the native records (`render_replay.py`) | 15 frames, both fills: **0 differing SHR bytes**, 0 stray writes, the SHR writes equal to the screen stores of the model (8,519 still, 11,657-25,615 demo); 7,597 native records, 1,032 of the masked phase |

What the frames reach: 15 frames where the weapon skip starts (`WCLIP`
copied), 41 that keep it, 12 that stop it, 109 without; a flash in 5;
the spans' refresh in 1 captured frame (`newgame-50`) and 2 synthetic;
the view of the frame before not shown or moved (`W_FSP` = `W_FSC`) in
14; the message rows (`viewtop` 9) in 55; the sky in 10 captured frames
and 3 synthetic; 25 masked drawsegs, every silhouette kind, clips of
`screenheightarray`, `negonearray` and the openings. Not reached: an
early flush before `drawMasked` (no captured frame's lists use even one
extra page by then: the largest column list is 139 of 254 bytes), a
texture made in play, a view size other than the full one.

**Planted bugs** (`tests/test_native_render_frame.py`, each in a scratch
copy, each frame run once, `$A5`):

| Bug | Frame | Caught by |
| --- | --- | --- |
| `fsFill` every 64 frames | `tour-24` | the stamps at the walk's entry (320 differ), the records, the spans |
| the first skipping frame's `WCLIP` copy missing | `still-1` | `WCLIP` at the walk's entry and at `drawMasked` |
| the sky's column one texel column off | `tour-46` | the records' texels (35 columns) |
| the sky's column one angle unit off (`sec` for `clc` at `sky_col`) | `synth-skyodd` | the records' texels |
| the sky always colormap A's page | `synth-skyfixed` | the records' pages (`$46` for `$47`) |
| `tier_flat` writing `DC_ROW` (upstream's does not) | `synth-flatv06`, `synth-flatv14` | the drawsegs, their openings, the clips |
| the flat colour's rows swapped | `synth-flatv06`, `synth-flatv14` | the records' fill bytes |
| a patchless column's bit read one column off | `synth-flat` | a record naming no slot |
| the automap overlay ignored by the weapon skip | `synth-automap` | `FR_SKIP`, `W_WSK`, `WPREV` |
| the shadow weapon not tested | `synth-shadow` | `WPREV`, `FR_SKIP` |
| no plane colours reset by `R_FillStamps` | `still-1`, `demo-10` | `W_LCC` at the walk's entry |
| the last batch not flushed | `still-1` | the records (5 columns) |
| the phase loader one page of code short | `still-1` | the run never ends |
| the phase loader without the per-level tables | `still-1` | a record naming no slot |
| a store into the hot game globals | `tour-46` | the write log |
| a store into the phase loader's code (`far_wload`) at `nr_frame`'s entry | `still-1` | the write log (card bank 1 allows only the gather's entries) |

and in the replay check, one texel of each native slot wrong: the SHR
bytes differ. The first version of `tier_flat` had the `DC_ROW` bug in
this list; `flatv06` and `flatv14` found it (upstream runs
`R_DrawColumnFlat` on the C code's direct page).

### Timing (a2vm's cost model, not the card)

The profiling build, per frame (ms; median and range; f121 is F1.2.1,
fastpath the firmware design without the pair). "Wall calls" is the
lockstep stub, a harness cost, not wall setup.

| Set | Frames | Setup and clears, f121 | BSP walk, f121 | BSP walk, fastpath |
| --- | ---: | ---: | ---: | ---: |
| still (E1M1) | 3 | 0.12 | 7.20 | 5.01 |
| newgame | 50 | 0.12 | 5.95 (0.44-8.87) | 4.14 (0.33-6.20) |
| m5 demo | 11 | 0.12 | 4.57 (0.77-9.84) | 3.30 (0.56-6.85) |
| title (demo3) | 50 | 0.12 | 3.76 (0.53-12.18) | 2.69 (0.40-8.67) |
| tour | 50 | 0.12 | 3.29 (0.46-15.62) | 2.32 (0.33-10.97) |

Against RENDER.md 4.4 (from `docs/research/native-memory.md` 7): setup
0.2-0.5 ms estimated, 0.12 measured; the walk 3.4-7.1 ms standing still
estimated, 7.20 measured (the top of the range); 0.8-1.6 ms in the demo
estimated, 3.76 median measured (above). A one-off profile (phases
around the calls, a scratch build) of still-1 and title-25: far windows
2.9 and 3.5 ms (node fetches, subsectors, segs, the vertex gather), the
box corners' `pta16` 1.3 and 2.8 ms, the walk's own code 2.5 and 3.8 ms,
`viewangletox` windows 0.5 ms. The corners' angles depend only on the
view's map unit and the box, as the vertex angles do, so a corner cache
(same results) is the first candidate; stage C measures the whole front
end.

Stage B, routine mode (`render_check.py --routine-timing`, the profiling
build `rwprof`): wall setup (phase 9) and seg loops (phase 10) of each
frame, the sum over its wall calls, each call with the model's caches
cold (a little above what a frame would take); frames with a sky wall
are left out (stage C). ms, median and range, f121:

| Set | Frames | Wall setup | Seg loops | Wall setup, fastpath | Seg loops, fastpath |
| --- | ---: | ---: | ---: | ---: | ---: |
| still (E1M1) | 3 | 6.01 | 10.85 | 4.82 | 9.99 |
| newgame | 47 | 5.90 (0.24-8.84) | 10.54 (3.60-16.51) | 4.76 | 9.66 |
| m5 demo | 11 | 1.27 (0.68-8.21) | 4.66 (3.93-13.18) | 1.05 | 4.35 |
| title (demo3) | 48 | 2.82 (0.37-8.86) | 6.72 (3.85-18.64) | 2.32 | 6.15 |
| tour | 45 | 3.19 (0.59-9.86) | 9.41 (4.06-15.26) | 2.56 | 8.81 |
| lights | 12 | 5.36 (4.76-7.52) | 10.64 (8.36-12.18) | 4.40 | 9.90 |

Against RENDER.md 4.4 (`docs/research/native-memory.md` 7), F1.2.1:
standing still, wall setup 4.0-8.7 ms estimated, 6.01 measured, and seg
loops 7.4-14.8 estimated, 10.85 measured; in the demo, 0.7-1.5 and
3.1-6.2 estimated, medians 2.82 and 6.72 measured (demo3's frames have
more walls than the estimate's median frame: up to 43). A wall's setup
costs about 0.18 ms: its far windows (the side, the back sector, the
drawseg, the sines and `RECIP_TABLE`) and the exact products; stage C
measures the whole front end.

Stage C, frame mode (`render_check.py --frame-mode --timing --report
build/native/render/report.md`, the profiling build `rwprof`, each frame
from `R_FillStamps` to `drawMasked` on the model's clock): ms, median
and range, f121 (the report has fastpath, the 65C02 cycles and the
soft-switch accesses of each phase, and the windows):

| Set | Frames | Window load | Setup | BSP walk | Wall setup | Seg loops | Window + front end |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| still (E1M1) | 3 | 4.54 | 0.14 | 7.21 | 5.99 | 11.92 | 29.82 |
| newgame | 50 | 4.54 | 0.14 | 5.97 (0.49-8.93) | 5.88 (0.24-8.80) | 11.69 (3.66-18.30) | 28.25 (9.11-40.39) |
| m5 demo | 11 | 4.54 | 0.14 | 4.65 (0.79-9.91) | 1.26 (0.68-8.18) | 4.65 (4.01-14.71) | 15.08 (10.24-36.91) |
| title (demo3) | 50 | 4.54 | 0.14 | 3.82 (0.58-12.18) | 2.98 (0.37-8.82) | 7.18 (3.85-19.65) | 19.97 (9.50-43.04) |
| tour | 50 | 4.54 | 0.14 | 3.35 (0.51-15.65) | 3.18 (0.59-9.82) | 7.12 (4.16-17.06) | 20.71 (10.06-46.49) |
| lights | 12 | 4.54 | 0.14 | 6.61 (5.59-9.08) | 5.35 (4.74-7.49) | 11.47 (8.96-13.07) | 28.12 (25.30-33.50) |

(After verification; before it the seg loops were 0.05-0.15 ms slower,
12.07 ms still, with nearly the same cycles: RENDER.md "Stage C as
built".) Against RENDER.md 4.4 on F1.2.1: standing still, 29.82 ms for
these phases against 20.0-38.2 estimated (the window load 4.54 against
5.0-7.1, setup 0.14 against 0.2-0.5, the walk 7.21 at the top of
3.4-7.1, wall setup 5.99 in 4.0-8.7, seg loops 11.92 in 7.4-14.8); in
the demo (title's medians) 19.97 ms against 10.8-18.3 (walk 3.82 against
0.8-1.6, wall setup 2.98 against 0.7-1.5, seg loops 7.18 against
3.1-6.2), up to 43.0 ms. The 65C02 code takes 3.1, 2.4 and 1.9 times
upstream's 65816 cycles for the walk, the wall setup and the seg loops
standing still, where `NATIVE.md` 1.2 assumed 1.37. The phases here are
the frame's own (the caches warm from the walk into the walls), close to
the sums of stage B's routine mode (cold caches per call). Standing
still a frame opens 362 read windows, 117 write windows and 322 aux-card
windows and writes `$C073` 971 times.

## The masked phase (milestone 8)

Design: `docs/RENDER-MASKED.md`; what was built and why it differs:
its "Stage A as built" and "Stage B as built"; the regions:
`docs/MEMORY_MAP.md` section 13. Stage A (2026-09-30) builds the sprite
data, the projection in walk order, the vissprites and their sort, and a
prototype of the bucket pass. Stage B (2026-09-30) builds the masked
phase's drawing: the sprites clipped against the drawsegs, their records
(the magnified runs, the shadows with the fuzz position), the masked mid
textures in the middle of the sprites and after them, the model of
upstream's list pages, the covered ranges and spans. Stage C
(2026-10-01) builds the weapon (its clip pass in the front end, its draw
at the masked phase's end), finishes the bucket pass, and runs the whole
frame into the SHR through milestone 5's replay; `rrunner.s` runs it on
the card from a disk image.

| File | What |
| --- | --- |
| `rbsp.s` | `nr_addsprites`: the walk appends the sector's number to `SPRSEC` (aux 0 `$1600`, one `RAMWRT` window), `SPRN` counts; upstream projects there, natively the masked phase does in the same order |
| `mmain.s` | `nm_masked`: the drawsegs whose `DSX1` is not 255 copied into W's `DSW` (`far_dscopy`), `SPRBOUND` into W, then `nm_project` and `nm_sort`; stage B: `drawMasked`'s loops (the sprites back to front, then the drawsegs' masked columns, the last first) and the last batch; routine mode's entries `nm_rsetup`, `nm_visx` |
| `msprite.s` | Stage B: `nm_drawsprite` (`R_DrawSprite`: the clips of the sprite's columns, the drawsegs from the last to the first with their scales and `nm_ptseg`'s side test, the masked range of a drawseg behind the sprite drawn at once, the silhouettes on the columns not clipped yet, `dsVisible`, then `nm_vis`), `md_dsptr` (a drawseg in `DSW`, or fetched past `DSW_MAX`), `md_cliprun` (a clip run through `far_get`, or a marker's constant), `md_phdr` |
| `mvis.s` | Stage B: `nm_vis` (`R_DrawVisSprite`: the loop page, `wclipSprite`, then `visCol`/`visPost`, the magnified `vrCol`/`vrPost` runs, or the shadows' `visColF`), `YHTAB` filled lazily, `FSCUT`, `CVSET`, the clip log of the test builds |
| `mwall.s` | Stage B: `nm_mwall` (`R_RenderMaskedSegRange`: `rw_scalestep`, spryscale, the seg, side and sectors, texturemid by the peg flag, `R_WallLight`, `TXMP`'s patch, `smul48`'s 48-bit products, one or each column's light, the masked columns and both clips, the posts as `K_TEX` and `K_TEXC` by the page model, the drawn marks back into the openings) |
| `rrec.s` | Stage B: `rec_room` models upstream's list pages (`UPOFS`, `XPUSED`, `UPFLUSH`) and counts the records (`RECSEQ`); assembled again with `-D MREC` for the masked image (`mrec_room`, `mrec_flush`) |
| `mproj.s` | `nm_project`: for each listed sector, its things (the `RTHING` chain from the sector record's head) projected exactly as upstream's `R_AddSprites` and `R_ProjectSprite` (the G parts with `qmulh` for fractional things and exact for whole ones, the `TZTEST` and `SPRBOUND` rejections, `labsTZ`, the rotation and flip, the width test, `xl`/`xr` with the `FixedMul` fallbacks, the clip to 160, `MAXVISSPRITES`, the scale record's `xiscale` and `FSTEP`, the colormap page from `CMOP`); `nm_sort`: the stable insertion sort largest scale first into `FRORD`, and `sortSkip` (a shadow clears `FR_SKIP` and `W_WSK`) |
| `mfar.s` | Card bank 1 (`MFAR`): `far_mload` (the masked image's page runs from `MCODE_BANK` through `far_pload`) and `far_dscopy`; stage B: `far_posts`, `far_postsc` (a patch column's posts in one read window) |
| `far.s` | `far_pload`: the phase loader takes a bank and a list of page runs; `far_wload` passes the front end's |
| `rdriver.s` | `-D MASKED`: `drv_mframe`, the front end then `far_mload` and `nm_masked`; stage B: `drv_mroutine` (routine mode: one call of the masked phase from the reference's state); stage C (`-D FRAME8`, builds `ftest`, `fprof`): `drv_fframe`, the whole frame (the front end with the weapon's clip pass, the masked phase with the weapon's draw, `nm_bkload`, `nb_frame`: the bucket pass and each batch's replay) |
| `wclip.s` | Stage C: `nw_clip`, the weapon's clip pass in the front end (upstream's `weaponClip`: `psSetup`/`pspSprite` into `FRVIS`, the shadow weapon skipped, `MM_WPOK`, the profile's runs `wcProf` into `FLOORCLIP`, or the unit-scale `visCol`/`visPost` fallback when the lump has no profile or `wpStart` refuses it) |
| `wpsp.s` | Stage C: the weapon code both phases share, assembled twice (`-D MPSP` with `m` names for the masked image): `ps_vis` (`pspSprite` into the 12-byte `FRVIS`), `wp_head`, `wp_find`, `wp_start` (the profile's column entries fetched into `WPENT`), `wp_list` (a column's posts) |
| `mpsp.s` | Stage C: `nm_psp` (`playerSkip`/`playerSprites`: the weapon by `wdDraw` from its profile, `wdProf`'s records from each column's lowest post up, or `R_DrawVisSprite` of `FRVIS` through `nm_vis`; then the flash by `pspSprite`) |
| `rrunner.s` | Stage C: `RENDER.SYSTEM`, the card test of acceptance 2 (boot under ProDOS: `CATALOG`, `LEVEL`, `FRAMES` into RamWorks, the card image into the language card; then the static tables by one PRIVATE request, and for each frame its data, the whole frame, its VBLs and the CRC of aux 0 `$2000-$9FFF`; a table at the end; C chained, F full) |
| `bucket.s`, `bdriver.s`, `bucket.cfg` | Stage C: the bucket pass finished (RENDER-MASKED.md 3.4): `nm_bkload` copies `BKFAR` (main `$0C00`, 709 B) and `BKFAR2` (main `$0200`, 253 B) from the masked image; `nb_frame` counts, cuts the batches (whole columns, at most `RECBUF_SPAN`, 26), scatters them three at a time into W's regions, parks batches 2 and 3 in `RECW`, turns each covered range's record into its W address (`CVDONE`), marks `K_FUZZNOW`, and calls milestone 5's `nat_replay` for each batch; `BKNEAR` (238 B, the card) copies the staging's chunks into page 1. Stage A's prototype: |
| `bucket.s` (stage A) | The bucket pass's prototype (RENDER-MASKED.md 3.4): the staging read in chunks of 180 B into page 1 (`BKNEAR`, in the card), with `RAMRD` off a count walk and a scatter walk into up to three W regions (`BKFAR`, main `$0C00-$0EFF`), the covered ranges turned into W addresses, batches 2 and 3 parked in `RECW` and brought back, the `K_FUZZNOW` marks; `bdriver.s` drives it on a2vm |

Host tools: `levelconv.py` (the patch store with 128-byte tails,
`PHDR`, `SPRFR`, `TXMP`, the sectors' thing heads; `--overrun`),
`rtables.py` (the scale records, `CMOP`, `SFIRST`), `framestate.py` (the
render things, psprites, the player's sector light and invisibility,
`SPRBOUND`, `FZ_POS`), `rendercap.py` (points P3s, P3w, PS, P4, P5, the
call logs of `R_AddSprites`, `R_DrawVisSprite`,
`R_RenderMaskedSegRange`, `maskedSeg`, `wcProf`, `wdProf`; the `demo3`
set), `rcanon.py` (the vissprites, order and skip), `projmodel.py` (the
host model of upstream's projection and sort, and its path coverage),
`bucketcheck.py` (the prototype against `loader.py`),
`render_check.py --masked`. Stage B: `maskmodel.py` (the host model of
upstream's masked phase from P3s to P3w, and its path coverage),
`maskcap.py` (routine captures: every masked-phase call of milestone 7's
captured frames at its entry and return), `maskroutine.py` (routine mode
on a2vm), `rcanon.py` (the records of every kind by column with the
patch map, the covered ranges and their records, the spans, the page
model, the clips, the marks, the clip log against the call log),
`framesynth.py` (`synth-mwlong`, `pagefull`, `mwclose`, `mwlight`; a spec
whose early flushes are its point keeps their P2 dumps), `framestate.py`
(`WTMP`), `levelconv.py` (`TXWM` of the masked textures; the lines' peg
flags in the level's key).

### Commands

```
python3 tools/native/rendercap.py          # all sets, demo3 included (309 MB of frames)
python3 tools/native/framesynth.py         # 16 synthetic frames
python3 tools/native/levelconv.py --all    # 18 level sources, every check
python3 tools/native/levelconv.py --overrun
python3 tools/native/rtables.py
make -C src/native -f render.mk            # mtest, mprof, btest among the rest
python3 tools/native/projmodel.py --coverage build/native/render/proj-coverage.json
python3 tools/native/render_check.py --masked                 # 193 frames, both fills
python3 tools/native/render_check.py --masked --sets demo3    # 533 frames
python3 tools/native/render_check.py --masked --timing --jobs 2
python3 tools/native/bucketcheck.py --timing                  # 192 frames
python3 tools/native/maskmodel.py --coverage FILE             # the host model, 197 frames (--sets demo3)
python3 tools/native/maskcap.py            # stage B's routine captures (72 MB)
python3 tools/native/maskroutine.py --jobs 2                  # routine mode, every captured call
python3 tools/native/render_check.py --frame-mode             # milestone 7 again, with the page model
python3 -m unittest discover -s tests -p 'test_native_masked*.py'
# stage C
python3 tools/native/framesynth.py --specs invis,flash,skipwall,wphigh
python3 tools/native/frame8.py                                # the whole frame, 201 frames, both fills
python3 tools/native/frame8.py --sets demo3 --json build/native/render/frame8-demo3.json
python3 tools/native/frame8.py --sets m7,demo3 --timing --poisoned --report build/native/render/report8.md
python3 tools/native/rdisk.py --check                         # RENDER.hdv, 100 demo3 frames on a2vm
python3 -m unittest discover -s tests -p 'test_native_frame8.py'
```

### Verification (checkpoint A, RENDER-MASKED.md 5.1)

- **Converter and tables:** all 17 level sources (18 since stage B) pass every check; the
  scale records, `CMOP` and `SFIRST` equal the reference's. The overrun:
  up to 127 texels past a post and 124 bytes past a lump's end in
  70,446 records, so the tails are kept whole.
- **Frames:** 193 frames (milestone 7's 188 and 5 synthetic) and 533
  `demo3` frames, both fills: 1,452 runs, every vissprite (15,930), the
  order, `FR_SKIP`, `W_WSK` and the listed sectors equal `ref816`'s,
  milestone 7's outputs at the walk's end unchanged, no stray write,
  at most 82 B of stack. No frame takes milestone 7's rules.
- **Model:** `projmodel.py` equals P3 and P3s on 725 frames and reaches
  every path of the projection.
- **Bucket prototype:** 192 frames, 384 runs equal to `loader.py`
  (records by column, `COLLO`/`COLHI`, covered ranges, 133 `K_FUZZNOW`
  marks).
- **Planted bugs**, in scratch copies under `build/`, each caught
  (`tests/test_native_masked.py`): ten in the walk's append, the
  projection, the sort and the masked image, three in the bucket pass,
  two in the converter (RENDER-MASKED.md "Stage A as built" names them).

### Verification (checkpoint B, RENDER-MASKED.md 5.2)

- **Routine mode:** 2,145 captured calls (`R_DrawSprite` 1,391,
  `R_DrawVisSprite` 719, `R_RenderMaskedSegRange` 10 and
  `maskedSeg` 25), both fills, 4,290 runs equal, 27,834 records.
- **Frames:** 197 frames, both fills, 394 runs equal (3,598 vissprites,
  245,734 records, 2,014 clip-log calls against the call log); `demo3`
  533 frames, 1,066 runs equal (12,554 vissprites, 589,770 records). Records by column with their kinds, `UPOFS`/`XPUSED`
  against `COLW`/`XPNEXT`, covered ranges, spans, `FZ_POS`, no stray
  write. Milestone 7's frame mode: 197 frames, 394 runs, 0 failed.
- **Page model:** `synth-mwlong` (a `K_TEXC` refused at a page's end)
  and `synth-pagefull` (50 extra pages and a flush) equal.
- **Model:** `maskmodel.py` equals P3w on 730 frames, 26 paths.
- **Planted bugs:** 14 on frames, one in routine mode, each caught; the
  fallbacks (`DSW` of 4, a post buffer of 2) equal
  (`tests/test_native_masked_b.py`).

### Verification (checkpoint C, RENDER-MASKED.md 5.3)

- **Acceptance 1** (`frame8.py --sets m7,demo3 --timing --poisoned`):
  734 frames (milestone 7's 188, 13 synthetic, 533 `demo3`), both
  fills, 1,468 runs equal: the clip pass at P1, the front end, the
  masked phase at the weapon and at its end (926,390 records, 9,137
  clip-log calls), each batch against `loader.py`, all of aux 0
  `$2000-$9FFF` against P5, the SHR writes against the model, 0 stray
  writes, at most 83 B of stack; 0 frames with `RULES` ≠ 0; the 69
  poisoned screens equal their `--call` truth.
- **Acceptance 2** (`rdisk.py --check`): `RENDER.hdv`, 100 `demo3`
  frames (`demo3-020` .. `119`), every CRC equal to `ref816`'s chained and
  full, `f121` and `fastpath`; the CRCs in `build/native/render/
  rdisk.json` for the owner's card run (milestone 12).
- **Tests** (`tests/test_native_frame8.py`): the whole frame on 10
  frames, both fills; the poisoned screen; the timing; 2 KB batches (a
  scratch build: groups of three, parked batches); the release build's
  `ST_RECORDS` policy; the disk's first 3 frames in both modes; 11
  planted bugs and the runner's one, each caught (RENDER-MASKED.md
  "Stage C as built").
- **Verified** 2026-10-01 (RENDER-MASKED.md "Verification of stage C"):
  the game build's last area taken to its last byte (`rrec.s`), the
  batch list's bound (45 batches, proved in `rlayout.py`; `BK_FIRST` in
  zero page `$71-$9E`), 6.1's column cuts in the game build (`bucket.s`
  `bk_cut`/`bk_kept`, `replay.s` under `-D RELEASE`), the bucket check
  after a stop, `W_WSK` captured at P4, the staging margin measured by
  `frame8.py`. After them acceptance 1 1,537 runs equal, acceptance 2
  400 of 400 CRCs, 1,289 tests OK; 12 planted bugs and the runner's one
  caught; the new tests `ReleasePolicy` (3), `BucketLimits` (2),
  `StagingMargin`.

### Sizes

Stage C: the front end's `wclip.s` 420 B and `wpsp.s` 1,097 B (`RENDERW`
15,793 B to `$A343`); the masked image's `mpsp.s` 421 B, `wpsp.s` 902 B,
`nm_bkload` 48 B (`MASKW` 8,810 B, 9,772 with the bucket pass's parts as
data, of 13,312); the bucket pass `BKNEAR` 238 B (card), `BKFAR` 709 B
(main `$0C00`), `BKFAR2` 253 B (main `$0200`); `RENDER.SYSTEM`'s runner
1,993 B and 4,007 B of data at `$E000-$F76F`.

Stage B: `msprite.s` 1,157 B, `mvis.s` 1,417 (1,333 without the clip
log), `mwall.s` 1,778, `mmain.s` 260, `rrec.s` again 198: the masked
image 7,425 of 13,312 B (`$6800-$8500`). Card bank 1 989 of 1,024 B
(`mfar.s` 334 B), 35 left. The front end's `rec_room` grew by 77 B.
Stage A:

`mproj.s` 2,615 B (427 of constants), `mmain.s` 68 B: the masked image
2,683 of 13,312 B (`$6800-$727A`). Card bank 1 818 of 1,024 B (`mfar.s`
163 B). The bucket prototype 1,073 B: 366 of 371 B in the card's `$F900`
part, 707 B in main `$0C00-$0EFF`.

### Timing (a2vm's cost model, not the card)

Milliseconds on `f121`, median (worst); the bucket pass median (range):

| Set | Frames | Masked window | Drawseg copy, `SPRBOUND` | Projection and sort | Bucket pass | Staged bytes, median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| still (E1M1) | 3 | 0.83 | 0.36 | 1.33 | 8.88 | 6,690 |
| newgame | 50 | 0.83 | 0.29 (0.36) | 1.13 (1.87) | 8.58 (2.71-18.35) | 6,501 |
| m5 demo | 11 | 0.83 | 0.15 (0.34) | 1.60 (4.43) | 4.86 (3.01-15.51) | 3,480 |
| title (demo3) | 50 | 0.83 | 0.22 (0.40) | 2.38 (5.35) | 6.54 (2.68-19.25) | 4,818 |
| tour | 50 | 0.83 | 0.24 (0.43) | 1.20 (5.93) | 7.20 (2.71-15.86) | 5,116 |

`fastpath` is 4-20% faster. The bucket pass costs 1.37 µs a staged byte
(1.26-1.77), about 96 cycles; the projection 0.19 ms a vissprite, mostly
the card's windows. RENDER-MASKED.md 6.2 carries these into the whole
frame: 5.9-6.2 FPS in the heaviest fight by the estimate. Over all 533
`demo3` frames (`--masked --sets demo3 --timing`) the projection and
sort take 2.44 ms (median, worst 6.19), the masked phase so far 3.48 ms
(worst 7.37).

Stage B (`--masked --timing`, fill `$A5`): the masked window 1.96 ms
(29 pages); the sprites and masked walls median (worst): `still` 1.59,
`newgame` 1.56 (2.42), `demo` 1.84 (7.18), `title` 2.01 (12.61), `tour`
1.77 (5.74), `demo3` 2.55 (17.34); `synth-crowd` 55.5 ms, `synth-pagefull`
64.7 ms.

Stage C, the whole frame (`frame8.py --timing`, `build/native/render/
report8.md`), `f121` median (worst): `still` 64.26 ms, `demo3` 72.54
(164.53, `demo3-036`), `tour` 57.15, `newgame` 64.26; `fastpath` 8-15%
less. The clip pass 0.46-0.61 ms, the weapon's draw 0.63-0.97, the
bucket pass 7.39 at `demo3`'s median (30.27 worst), the replay 33.80
(80.90). With `NATIVE.md` 6's tics: 14.1-14.9 FPS still, 8.8-11.0 at the
`demo3` median, 4.9 at its worst frame (3 to 10 of 533 frames under 6
FPS). The disk's 100 frames by VBL count: 10.5 FPS `f121`, 12.1
`fastpath`, render only.
