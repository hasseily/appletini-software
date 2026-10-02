# Milestone 11, part `s2draw`: the drawers and the publish

Part `s2draw` of wave 2 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), the
patch drawer into a band, the raw, background and rectangle drawers, the
marks and the publish, written from upstream's `src/iigs/patch65.s` and
`i_viigs65.s`. 2026-10-01. Labels as in `NATIVE.md`: [M] measured,
[R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/s2_draw.s` | The shared object `s2_draw` (1,027 B): `s2_patch` (`IIGS_DrawPatch` with `markPatch` and `capPost` [R `patch65.s:53-276`]), `s2_vpatch` (`V_DrawPatchNotScaled` [R `i_viigs65.s:1770-1782`]), `s2_raw` (`drawRawData` of whole rows with `pairByte` [R `:1371-1445`]), `s2_back` (`V_DrawBackground` [R `:1468-1521`]), `s2_rect` (`copyToBuffer` by rows with `rectOffset` and `markVP`: `I_RestoreStatusRect`'s copy, `drawPicture`'s pixels [R `:1226-1240`, `:1670-1762`]), `s2_mark` (`markRect`, `markRows` [R `:416-457`]), `s2_unmark` |
| `src/native/s2_pub.s` | The shared object `s2_pub` (145 B): `s2_publish` (`showDirty` [R `:462-498`]: the marked bytes of the band to aux 0 in one `RAMWRT` window, then the marks cleared; `s2_begin` before the frame's first band) and `s2_mul160` |
| `src/native/s2_beginstub.s` | **STANDIN**, test images only: `s2_begin` writing SCB n = `$50 \| (n & $0F)` to aux 0 `$9D00-$9DC7`, until part `s2pal` |
| `src/native/s2_draw.inc` | The drawers' zero page (`S2_*`, `$48-$77`) and the image interface (below); **STANDIN** until `s2.inc` carries it (S2DRAW-1) |
| `src/native/s2_drawt.s` | The test image `s2dt` in `P2DW`'s room with `P2DW`'s runtime places: `s2x_case` (a case's bands: rows, marks, nibble slots and row tables from RamWorks, the drawer in phase 30 alone, the band back to RamWorks, the case's number last) and `s2x_pub` |
| `src/native/s2_pubt.s` | The test image `s2pt`: `s2_pub.s` alone in `AMAPW`'s room, as `AMAPW` links it |
| `src/native/m11/s2draw.mk` | Both images into `build/native/m11/s2draw/` (`make -f m11.mk part P=s2draw`) |
| `tools/native/s2draw.py` | The host model of upstream's rules (16-bit arithmetic as theirs): `draw_patch` (and CAPVAL/CAPMSK), `mark_patch`, `mark_rect`, `draw_raw` (any offset and length), `draw_back`, `copy_rect`, `publish`; `--columns` checks every 2D patch against the 256-byte column contract |
| `tools/native/s2drawcase.py` | The cases: the base state, the truth by ref816 `--call` (synthetic) and `--capture` (the tour), the model against the truth, the native runs on a2vm, the publish runs and their write logs, `--timing` |
| `tests/wip_test_m11_s2draw.py` | 14 tests (below) |

Build output: `build/native/m11/s2draw/` (26 MB: the images, `base.img`
6.6 MB, the synthetic truth 18 MB and the captured 1.3 MB, both zlib'd,
cached under a hash of their inputs and of `s2drawcase.py`). Every run's
directory is a `tempfile` directory under `build/`, deleted after it.

### 1.1 The interface

**The band.** `S2_BAND` (W address of its first row), `S2_Y0` (that
row's screen row), `S2_Y1` (the row after its last, at most 200; at most
64 rows). Every drawer clips to the band's rows as upstream clips to 200,
so a patch crossing three bands is drawn three times, each with its rows.

**The image exports** (ld65 resolves them; each image places them):
`s2_marks`, a page: `DRB` `+$00`, `DRE` `+$40` (upstream's marks of each
band row), `ROWL` `+$80`, `ROWR` `+$C0` (each band row's nibble table
page in W for the left and the right pixel: upstream's
`iigs_rowpageL/R` with the palette's slot in place of `NIBTAB`;
`pairByte` reads `ROWL` for the left pixel and `ROWR` for the right,
upstream's `rowbase` and `rowbase + $200`); `s2_fbuf` (page aligned) and
`s2_fbpages` (`.exportzp`, at least 2); `s2_begun`; `s2_begin`.
`S2_DRY0`/`S2_DRY1` are band rows (`S2_DRY1` 0: none).

**Arguments.** `S2_X`, `S2_Y` (signed, a patch's place; `s2_vpatch`
subtracts the offsets), the source `S2_PBANK:S2_PADDR`; `s2_raw` and
`s2_rect` take rows `S2_RY0 .. S2_RY1 - 1` (and `s2_rect` the bytes
`S2_RB0 .. S2_RB1`, with `S2_PADDR` the address of screen row 0, byte 0:
`STCACHE`'s minus 168 × 160); `S2_CAP` bit 7 records CAPVAL at the band
byte's address + `S2_CAPD` and CAPMSK at CAPVAL's + `S2_CAPM` (the
strip's spare band rows hold them in `P2DW`).

**The contracts** (each checked by the host tools, none by the drawer):

1. A source lies in its bank's `$0200-$BFFF` (a `RAMRD` window reaches
   nothing else of a bank: a read of `$C000-$FFFF` reads the I/O page and
   the main card, which the first test run showed by switching the card
   and running wild), and a patch's last column starts at least the fetch
   buffer's size (`s2_fbpages` × 256) before `$C000`: the buffer is
   refilled from a column's start.
2. A column of a 2D patch is at most 256 bytes: every one of DOOM1.WAD's
   306 2D patches but `WIMAP0` (a 36,864-byte picture in the release [M:
   `umodel.Release`], drawn by `s2_rect`) holds it; the longest are 65 B
   (`M_DOOM`, `WIKILRS`) [M: `s2draw.py --columns`].
3. `s2_raw` draws whole rows: upstream's `V_DrawRaw(num, offset)` with
   offset a multiple of 320 and the lump's length too. Its callers are
   the status bar (`STBAR` at 168 × 320, 10,240 B [R
   `st_stuff65.s:749-755`]) and `V_DrawRawFullScreen` (offset 0 [R
   `r_data65.s:586-588`]), whose lumps in the release are pictures (`s2_rect`).
   `tools/native/s2draw.py`'s `draw_raw` models any offset; the captured
   calls refuse one outside the contract (none came).
4. A band uses at most the image's slots' palettes (8 in `P2DW`): the
   row tables are the caller's (`s2pal`'s `setRows` natively).

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
make -C src/native -f m11.mk part P=s2draw      # no warning
make -C src/native -f m11.mk sizes
python3 tools/native/s2draw.py --columns
python3 tools/native/s2drawcase.py              # truth, model, native
python3 tools/native/s2drawcase.py --timing
python3 tools/testpar.py tests/wip_test_m11_s2draw.py
```

Results [M, 2026-10-01]: `wip_test_m11_s2draw` 14 tests OK in 21.7 s with
the truth cached (the first run makes it: about 2 minutes); also on
Python 3.9.6 with `-W error::ResourceWarning`. `tests/test_sound_*`
unchanged and green (7 modules, 152 tests); `wip_test_m11_s2lay` green
(25).

| Check | Result |
| --- | --- |
| The truth, synthetic | 2,483 ref816 `--call`s on the base state (all RAM at the tour's 50th call of `V_DrawNumPatchNotScaled`) with a background set poked (random back buffer, marks before, 16 random nibble tables, rows over 8 of the 16 palettes, random CAPVAL/CAPMSK and `STCACHE`): every 2D patch of DOOM1.WAD (306: 165 `ST*` with the font `STCFN*`, 45 `M_*`, 96 `WI*`) at 8 places (two even x, two odd, clipped at the left, right, top and bottom edges, parities alternating), half by `IIGS_DrawPatch` and half by `V_DrawPatchNotScaled`, 816 recording CAPVAL/CAPMSK; `V_DrawRaw` of the resident `STBAR` (its bytes poked) at rows 0, 1, 50, 99, 168, 170, 180; `V_DrawBackground` of `FLOOR4_8`, `FLAT5_4`, `CEIL3_5`, `FLOOR7_2` (poked over `STBAR`); 24 `I_RestoreStatusRect`. Every call returned; no byte changed outside the case's rows |
| The truth, captured | 65 calls of the tour by `--capture` and `--call` on each entry: `V_DrawPatchNotScaled` 40 (the HUD's two texts, hits 2-21 and 423-436, all 34 recording; menus), `V_DrawNumPatchNotScaled` 7 (status bar), `V_DrawNumPatchScaled` 6 (intermission), `V_DrawRaw` 6 (`STBAR`, pictures, the `STCACHE` copy), `V_DrawBackground` 3, `I_RestoreStatusRect` 3 |
| The model against ref816 | 0 problems on all 2,548 cases (pixels, `DRB`, `DRE`, CAPVAL, CAPMSK) |
| The native against ref816 | 0 problems on all 2,548 cases, drawn in about 4,000 bands (at most 32 rows, 10 recording; the first band of a case cut at a row that varies with the case, so posts and rectangles are split at every phase): every band's bytes, `DRB`, `DRE`, and `S2_DRY0/1` equal to its marked rows; the texts' CAPVAL and CAPMSK after each character, so the record after the last equals upstream's |
| The publish | 16 bands of random bytes and marks (the first with none) in one frame, from the `$A5` and the `$5A` machine: aux 0 `$2000-$9FFF` equal to the host copy (5,739 and 7,977 bytes published); 0 stray writes on the write log (the driver, the loader, the far layer, the test image, `s2_draw`, `s2_pub`, the stand-in, each with its own set, by the map's module ranges); `s2_begin` once, its 200 SCB stores all before the first band store, and `s2check.order` passes; every band's marks cleared; a frame whose `s2_begin` ran writes no SCB |
| A drawing run's write log | 6 cases: 0 stray writes of 249,022 (the band, the marks page, its own operands, zero page `$48-$77` for `s2_draw`) |

## 3. Planted bugs (each in a scratch copy of the sources) and the check that caught it

| Bug | Caught by | The first failure |
| --- | --- | --- |
| The odd pixel's mask `$0F` (for `$F0`) | the native cases | 134 problems: "M_DOOM-in-even band 35-44: the byte of row 35, $18: $BD, ref816 $B9" (a `vpatch` whose offset makes x odd) |
| The post's row table a row off (parity) | the native cases | 104 problems: "M_DOOM-in-even band 35-44: the byte of row 35, $18: $BF, ref816 $B9" |
| The clip at x = 320 not taken (`cmp #$80`) | the right-edge cases | 24 problems: "M_DOOM-right band 105-129: the byte of row 106, $01: $AB, ref816 $AC" (the pixels past 319 land in the next row) |
| `pairByte`'s right table at `+$100` | the raw and background cases | 43 problems: "STBAR-raw-0 band 0-6: the byte of row 0, $00: $E7, ref816 $EF" |
| The publish ending a byte early | the host copy | "the screen at $2D1F: $A5, the host copy $92" |
| The publish not calling `s2_begin` | the host copy and the write log | "the screen at $9D00: $A5, the host copy $50", "s2_begin wrote 0 SCBs, not once its 200" |

## 4. Sizes against the budget

| Item | Size [M] | Budget |
| --- | ---: | ---: |
| `s2_draw` + `s2_pub` in `P2DW` (`s2dt.sizes`) | 1,172 B | 1,200 B |
| of which `s2_pub` (also alone in `AMAPW`'s room, `s2pt`) | 145 B | about 200 B |
| `s2_beginstub` (test only) | 22 B | |
| zero page | `$48-$77` (48 B: 18 arguments and band state, 30 temporaries) | `S2_*` `$48-$7F` |

The first version was 1,306 B: `drawRawData` for any offset and length
took 223 B; whole rows (contract 3) take 80 B.

## 5. Timing (SCREENS.md 6.4)

`python3 tools/native/s2drawcase.py --timing` [M]: the drawer alone
(phase 30 around the call only: its header and column fetches, every
band a case is drawn in), over the first 128 in-screen patch cases
(recording off; 177,533 pixels):

| | `f121` | `fastpath` |
| --- | ---: | ---: |
| µs a patch pixel | 4.17 | 3.27 |
| µs a published byte (16 bands of whole marked rows, 38,560 bytes; `s2_begin` already run) | 0.991 | 0.991 |

The published byte is the SHR drain (`NATIVE.md` 8: about 31.5 ms for 32
KB, 0.96 µs a byte); the patch pixel is the inner loop's about 60 cycles
(row table, nibble table, read, mask, or, write, the next row). A status
bar digit (about 80 pixels) is about 0.35 ms on `f121`; a full status bar
redraw is bounded by lever L2 (pre-rendered glyphs), as SCREENS.md 1.4
plans.

## 6. Requests (for the integrator; the stand-ins are marked `STANDIN`)

### S2DRAW-1. `tools/native/s2layout.py` (and so `s2.inc`): the drawers' places

**Evidence.** SCREENS.md 4.3 gives `$48-$7F` to `S2_*` but names none;
`s2_draw.s` and `s2_pub.s` need fixed places shared with their callers.
**Stand-in.** `src/native/s2_draw.inc`. **What.** Move its table into
`s2layout.py` as constants (the same names and addresses, `S2_BAND` `$48`
to `S2_MB1` `$77`) written into `s2.inc`, `check()` keeping them inside
`ZP_S2`; and give each drawing image its `s2_marks` page, `s2_fbuf`,
`s2_fbpages` (`P2DW`: `$9700`, `$B800`, 4; `MENUW`: a page of its 24-row
band's marks, `$BD00`, 2; `WIW`, `FINW`: `$9900`, `$BA00`, 2; `AMAPW`:
`$A900`, none), exported by the image's glue. Then `s2_draw.inc` becomes
an `.include "s2.inc"` and is deleted.

### S2DRAW-2. `tools/native/s2layout.py`: `AMAPW`'s size table row for `s2_pub`

**Evidence.** `module_row('s2_pub')` is `'s2_draw+s2_pub'` in every
image, and `AMAPW`'s shared list is `('s2_pub',)`, so an `AMAPW` image
that links `s2_pub.o` fails its size check: "AMAPW links s2_draw+s2_pub
(145 B), which its size table does not list" [M: the first `s2pt`
build]. **Stand-in.** `s2draw.mk` assembles `s2_pub.s` as `s2pubalone.o`
for `s2pt` (counted in `own`; the test checks it against 200 B). **What.**
In `size_rows`, after `row = module_row(stem)`:

```python
        if row == 's2_draw+s2_pub' and row not in im.shared and \
                's2_pub' in im.shared and stem.split('-')[0] == 's2_pub':
            row = 's2_pub'
```

then `s2pt` links `s2_pub.o` (the `STANDIN` rule in `s2draw.mk` goes).

### S2DRAW-3. `src/native/s2_drv.s`: one snapshot a call

**Evidence.** The driver's snapshot point `s2d_called` is visited twice
when the VBL interrupt is taken there (once at the step that reaches it,
once at the `RTI` back to it), so `pc s2d_called@* snapshot call` takes
two snapshots of one call and `s2run.Run.calls()` shifts every later call
by one [M: a run of 32 cases, calls 18 and 19 both showed case 18's
descriptor; each case passed alone]. **Stand-in.** `s2_drawt.s` writes
the case's number last and `s2drawcase.call_snapshots` drops a repeated
snapshot. **What.** In `s2_drv.s`, replace

```
        jsr s2d_jump
        stz PHASE
s2d_called:                     ; (the snapshot point after each call)
        inc s2d_k
```

with

```
        jsr s2d_jump
        stz PHASE
        sei                     ; (no interrupt returns to the point:
s2d_called:                     ;   one snapshot a call)
        cli
        inc s2d_k
```

(an interrupt pending at the `sei` is taken after the `cli`'s next
instruction, past the point).

### S2DRAW-4. `docs/SCREENS.md` 1.4 and 4.5 (for `s2data`): the store's contracts

Replace in 1.4 "`s2_raw` is `V_DrawRaw` (the `STBAR` raw lump through
`pairByte` [R `:1311-1445`]) and `s2_picture` is `drawPicture` [R
`:1226-1295`]" with "`s2_raw` is `drawRawData` of whole rows (the
`STBAR` raw lump through `pairByte` [R `:1311-1445`]), `s2_rect` is
`copyToBuffer` by rows (`drawPicture`'s pixels [R `:1226-1240`] and
`I_RestoreStatusRect`'s copy); `s2_vpatch` is `V_DrawPatchNotScaled`", and
add to 4.5 after the store's row: "The 2D store keeps every source in its
bank's `$0200-$BFFF` (a `RAMRD` window reaches nothing else), a patch's
last column at least 1 KB before `$C000` (the fetch buffer is refilled
from a column), every column at most 256 bytes and every raw lump whole
rows of 320 bytes (`docs/m11-parts/s2draw.md` 1.1)". A full-screen raw
lump of 64,000 B would not fit one bank's `$0200-$BFFF`; the release has
none (its full screens are pictures), and `s2data` checks it.

### S2DRAW-5. Where `s2_begun` lives, and `AMAPW`'s `s2_begin`

**Evidence.** `s2_publish` needs a byte that survives from one image to
the next within a frame (a full-automap frame publishes in `AMAPW`, then
in `P2DW`: SCREENS.md 1.5.4) and that the frame's end clears (`s2_finish`,
`s2pal`); a byte in an image's stored data would be reloaded 0 with each
image. And `AMAPW` links `s2_pub` but not `s2_pal` (4.1's size table), so
its `s2_publish` has no `s2_begin` to call, though 1.3 says the frame's
first band (the map's, in such a frame) comes after `s2_begin`.
**Stand-in.** The test images export `s2_begun` from their own data.
**What** (the owner's or the integrator's choice, with `s2pal`): a field
`PS_BEGUN` at `PALST` offset `$02D1` (free: the fields end at `$02D0`),
which `s2_finish` clears, every publishing image exporting `s2_begun =
PALST_W + PS_BEGUN`; and either `AMAPW` links `s2_pal` (800 B: its room
then holds 8,000 B of budget in 10,240) and fetches `PALST`, or the frame
driver runs `s2_begin` (`P2DW`'s) before `AMAPW` in a full-automap
frame.

## 7. Decisions where the design left a choice

- **The marks per band row**, not per screen row: `DRB`, `DRE` of the
  band's rows and `S2_DRY0/1` in band rows. A band's marks are upstream's
  for the same rows; `DRY0/1` differ (upstream's is the whole screen's
  hull), so the tests compare it with the band's marked rows.
- **The column fetch**: each column's offset by a 2-byte `far_get`, its
  posts from the fetch buffer, refilled (`s2_fbpages` pages from the
  column's start) only when the column's 256 bytes are not in it. A
  status bar patch is one fill; `M_DOOM` (6,772 B) about 7 with 1 KB.
- **Self-modified operands** in the inner loops (the row table, the
  nibble table page, the mask, `pairByte`'s tables): W is RAM, loaded
  every frame.
- **Upstream's quirk kept**: a post whose row is off the screen (`>=
  200`, negative included) ends its column [R `patch65.s:106-110`: `jmp
  nextCol`], so later posts of that column are not drawn. The first
  model skipped the post only and differed from ref816 on the top-clipped
  cases; the model and the drawer now both end the column.
- **The test's band** is `P2DW`'s 32 rows; `MENUW`'s 24, `WIW`'s and
  `FINW`'s 40 and `AMAPW`'s 42 use the same code (a band of up to 64
  rows).

## 8. Open problems

1. The patch pixel costs 4.2 µs on `f121`: a status bar of many widgets
   redrawn in one frame is a few ms; lever L2 (pre-rendered glyphs) or a
   faster inner loop (a 64-entry row address table instead of `+160` a
   row, about 10 cycles) if `s2stbar`'s frame time needs it.
2. Bands of 40 and 42 rows were not run (the test image has `P2DW`'s 32);
   `s2wi`, `s2fin` and `s2amap` run their own.
3. `CAPLO`/`CAPHI` (upstream's bounds of a record) are not kept: the
   HUD's cached drawer (`s2hud`) scans its strip's 10 rows of CAPMSK.
4. S2DRAW-1, -2, -3, -5 are stand-ins until the integrator applies or
   changes them.

## 9. The wave 2 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.6, "Wave
2 as integrated"):

| Request | Outcome |
| --- | --- |
| S2DRAW-1 | Applied: `s2layout.py` `S2_ZP` (the same names and addresses, written into `s2.inc`'s zero page; `check()` keeps them in `ZP_S2` and disjoint but for `S2_RY0`, `S2_RY1` in `S2_X` and `S2_RB0`, `S2_RB1` in `S2_Y`) and `DRAW_PLACES`, written as `P2DW_MARKS`, `P2DW_FBUF`, `P2DW_FBPAGES` (and `WIW_*`, `FINW_*`, `AMAPW_MARKS`), each checked to be a page of its image's marks range and inside its fetch buffer range. `s2_draw.inc` deleted; `s2_draw.s` includes `s2.inc` and carries the interface text; `s2_drawt.s` and `s2_pubt.s` use the new names (the same values). `MENUW` has no places yet: its runtime ranges ($A800-$BFFF) are all taken, so its marks page is `s2menu1`'s to place |
| S2DRAW-2 | Applied in `size_rows`; `s2draw.mk`'s `s2pubalone.o` rule removed and its stale objects deleted; `test_sizes` now checks `AMAPW`'s `s2_pub` row (145 of 200 B) |
| S2DRAW-3 | Applied to `s2_drv.s` as written; `s2drawcase.call_snapshots` no longer drops a repeated snapshot but fails on one, so the fix is checked on every run |
| S2DRAW-4 | Applied: SCREENS.md 1.4 and 4.5 |
| S2DRAW-5 | Partly: the place `PS_BEGUN` (`PALST` `$02D1`, `s2layout.PALST_NATIVE`) for `P2DW`, `WIW`, `FINW`. `AMAPW`'s `s2_begin` and `MENUW`'s `s2_begun` (neither holds `PALST`) are left to `s2pal` and `s2menu1`; the test images keep their own `s2_begun` |

After it: `s2drawcase.py` 2,548 cases, the model and the native 0 problems
against ref816 (the truth recaptured, 1 min 19 s, because the cache key
holds the tool); `--timing` 4.174 / 3.265 µs a pixel, 0.991 µs a published
byte; `wip_test_m11_s2draw` 14 tests OK (also on Python 3.9.6, the planted
bugs caught as before).

## The final integration of the first half (2026-10-02)

`s2_beginstub.s` stays in `s2dt` and `s2pt` as `s2_publish`'s unit-test double (relabelled from STANDIN): its stores are what the publish test predicts; every other image links part s2pal's `s2_pal.o`, and `s2_publish` with the real `s2_begin` is part s2pal's checkpoint. The test is `tests/test_m11_s2draw.py`. (`docs/SCREENS.md` 8.13.)
