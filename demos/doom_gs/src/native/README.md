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
