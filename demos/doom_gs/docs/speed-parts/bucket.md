# Speed plan, wave 1, part `bucket`: the bucket pass and the record flush

Written 2026-10-02 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, item 8, and RENDER-MASKED.md 6.2, optimisation 10. It changes only time. Every frame, every batch the replay is handed and every pixel stay the same: the checks below compare them byte for byte.

## Results (a2vm `f121`, render only)

| Frame | Render before | Render after | Change | Render-only FPS | Bucket pass (frame8 `bucket`) | `segs` (holds `rec_flush`) |
| --- | ---: | ---: | ---: | --- | --- | --- |
| still-1 (E1M1, standing still) | 64.14 ms | 59.36 ms | **−4.78 ms** | 15.59 → 16.85 | 9.36 → 4.76 | 12.46 → 11.90 |
| demo3-325 (demo3's median render) | 72.40 ms | 67.87 ms | **−4.53 ms** | 13.81 → 14.73 | 8.41 → 4.28 | 8.90 → 8.45 |
| demo3-277 (demo3's median bucket pass) | 70.10 ms | 66.31 ms | −3.79 ms | 14.27 → 15.08 | 7.34 → 3.78 | 8.51 → 8.14 |
| demo3-036 (the heaviest frame) | 164.38 ms | 151.14 ms | **−13.25 ms** | 6.08 → 6.62 | 30.13 → 17.06 | 16.24 → 15.55 |

- The 23 demo3 frames of the sample went from a mean of 103.70 ms to 96.58 ms. The gains ranged from 1.7 to 13.3 ms a frame.
- The bucket pass alone (`bucketcheck.py --timing`, cost phase 18, the pass without the replay):

  | Frame | f121 | fastpath |
  | --- | --- | --- |
  | still-1 | 9.18 → 4.62 ms | 8.81 → 4.43 ms |
  | demo3-325 | 8.23 → 4.13 ms | 7.92 → 3.97 ms |
  | demo3-277 | 7.16 → 3.63 ms | 6.89 → 3.49 ms |
  | demo3-036 | 30.10 → 17.04 ms | 27.16 → 15.59 ms |

- **Against the plan's expectation.** The plan expected −4.2 to −4.9 ms still for (a) to (c) together. The pass measured −4.56. For the heaviest frame the plan expected −11.5 to −13; the pass measured −13.07. For (d), the plan expected −0.7 to −1.1 ms still. It measured −0.56 ms in `segs`. That is net of the 18 cycles a record that rec_room's count now costs: −31,032 cycles still, −40,779 in demo3-036.
- **What else moved.**
  - `setup` +1,600 cycles: `rec_start` zeroes the counts.
  - `dscopy` +4,001 cycles: `nm_masked` copies the counts.
  - `mwindow` +3,724 cycles: an interrupt now lands in that phase. The masked image's page count is unchanged.
- **The whole frame (derived, not measured on the game).** The render is part of every view frame, so the game frame shortens by the same milliseconds:

  | Scene | Basis | Before | After |
  | --- | --- | --- | --- |
  | Still | SPEED.md section 2, today's 180.7 ms | 5.53 FPS | about 5.68 FPS (175.9 ms) |
  | Still | wave 1's E1 build, 100.2 ms | 9.98 FPS | about 10.5 FPS (95.4 ms) |
  | demo3 | E1, 308 ms | 3.25 FPS | about 3.30 FPS (303.5 ms) at the median frame |
  | Heaviest demo3 frame | E1, 689 ms | | about 676 ms |

  Part `measure`'s `playtime.py` gives the integrated figures.
- **Commands.** Both builds are in their own directories.
  - The timing: `python3 tools/native/frame8.py --no-build --obj OBJ --frames <the 24 below> --fills a5 --jobs 2 --timing --json OUT.json`, run on the base build (HEAD's sources) and on this part's build, one after the other, with the same a2vm binary.
  - The bucket pass alone: `python3 tools/native/bucketcheck.py --no-build --obj OBJ --frames still-1,demo3-325,demo3-277,demo3-036 --fills a5 --timing`.
  - The builds: `make -s -C src/native -f render.mk OUT=OBJ ROOT=$PWD`.

## What changed

### (a) Optimisation 10: the counts come from the producers, and walk 1 goes

- **rrec.s.** `REC_ROOM` adds each record's bytes in W (its native size less the column byte) to a 16-bit count for its column.
  - The front end's counts are `FCNTLO`/`FCNTHI`, in W at `$AD00-$AD9F` and `$AE00-$AE9F`.
  - The masked copy's counts are `MCNTLO`/`MCNTHI`, in W at `$6600-$669F` and `$6700-$679F`.
  - The cost is 18 cycles a record.
  - A count past `$FFFF` keeps its high byte at `$FF`, so such a column stays past every batch.
  - `rec_start` zeroes `FCNT` in the loop that zeroes `UPOFS`.
- **mmain.s.** `nm_masked` first copies `FCNT` into `MCNT` (4,000 cycles). `mrec_room` then goes on adding to `MCNT`, and so does OVLW's copy of `mrec_room` (the automap overlay).
- **Where the counts live, and why no far copy is needed.**
  - `FCNT` sits after the front end's code. `WCODE_END` is now `$AD00`; the front end ends at `$A3BB` in rcard.
  - The masked image's load does not touch `FCNT`. That load covers only its code pages, which end below `$9C00`, and the TXMP pages `$B2-$B3`.
  - The drawseg copy and the vissprites take those bytes only after `nm_masked`'s copy.
  - `MCNT` is the front end's dead first code bytes, after `MATHW`/`AUXW` (`$6592`) and below `MCODE`. OVLW's load (from `$6800`) leaves it in place, and so does `s2_ovd`'s poison of OVLW's room.
  - The task's `far_put`/`far_get` around the image switch was therefore not needed, and `rframe.s` is unchanged. Two link-time asserts guard the places:
    - `rrec.s`: `RENDERW`'s end ≤ `FCNTLO`;
    - `mmain.s`: `AUXW`'s end ≤ `MCNTLO`.
- **bucket.s `nb_bucket`.**
  - It makes the batches from `MCNT`, with no walk.
  - The cursor loop writes `COLLO`/`COLHI` from `MCNT` directly; the old push/pull swap is gone.
  - `COLLO`/`COLHI` are no longer zeroed first. Every entry is written before it is read.
- **RENDER-MASKED.md 6.1, game build only (`-D RELEASE`).** The counts include records the producers counted but the staging does not hold. Two cases trigger a recount:
  - a dropped batch (`RECDROP`);
  - a column past a batch (`@full` with one column).

  In either case `nb_bucket` zeroes `MCNT` and runs walk 1 through `scan` (`BK_MODE` bit 7). Walk 1 counts the staging again and cuts the column exactly as before. The batches are then made again. After a recount no column passes a batch, so it cannot loop. The test build stops at such a column (`ST_BUCKET`, `BRK`) as before.
- **CVDONE.** `nb_bucket` now starts each column at 0 (a covered range whose record is not found yet) or 1 (no covered range). Walk 2 and the end-of-scatter clear therefore no longer call `covered`, and that routine is gone. Walk 1's cut ORs bit 7 in, instead of storing `$80`.

### (b) The chunk copy: patched absolute,y, Y counting to 0

- **ZLOOP** is 10 bytes of code in the bucket pass's zero page at `$A0-$A9` (`rlayout.BK_ZLOOP`, after the batch list `$71-$9E`):

  ```
  lda abs,y / sta abs,y / iny / bne / rts
  ```

  - `nb_bucket` writes it through `zl_put` (BKFAR2) once a frame.
  - Each run of a chunk sets the two operands, with Y running from −n to 0.
  - Zero page reads main memory inside the RAMRD window, so the loop needs no card bytes.
  - The cost is 15 cycles a byte; the old loop took 20.
  - Its writes fall in `$70-$AF`, which the bucket pass was already allowed.
- **The chunk is split in two:**
  - The prelude (moving the cut record, the chunk's size, and `BK_REM` less the chunk, once a chunk rather than once a run) is `chunk` in BKFAR, with RAMRD off.
  - The window part is `cwin` in BKNEAR.
  - `BK_PTR` is advanced from the patched operand.

### (c) Walk 2

- The walk and walk 2 are now one loop, `scan`. It has no handler call through `jmp (BK_WALK)` and computes the next record's offset only once.
- Each record's size comes from its kind's fixed size (`ssize`). The record is copied by two zero-page pointers counting Y down: `BK_V` points into page 1, and `BK_P` is the column's cursor. That takes 16 cycles a byte; the old loop took 20.
- With the `CVDONE` preset, an uncovered column's record skips the range test (24 cycles).
- The fully unrolled copy per kind was not built (see Open problems).

### (d) rec_flush and mrec_flush

- The flush is one loop, `lda BATCH,y / sta (FA_DST),y / iny / cpy RBV / bne`, at 18 cycles a byte; the old loop took 25.
- A batch that reaches or passes its area's end (`$C000`) is copied in two runs. The first run covers the bytes before `$C000`. Then comes the next area: aux 0, then the spill banks. A full staging still stops at `@over` (`ST_RECORDS`, `BRK`). The rest goes to `$0200`, through `FA_DST = $0200 − n`.
- `STG_PTR` is written only outside the RAMWRT window, and only once the batch has fitted. A stop at `@over` therefore leaves it as before.
- The RELEASE drop checks are unchanged.

### Sizes

| Segment (room) | Before | After (test and game build) | After, RELEASE | After, RELEASE + RPROF |
| --- | ---: | ---: | ---: | ---: |
| BKNEAR (rcard: to `$FE7A`, 238 B) | 238 | **190** (`$FD8D-$FE4A`) | 305 of 309 (ftest) | 305 |
| BKFAR (768) | 714 (RPROF 724) | 699 (RPROF 709) | 757 | **767** |
| BKFAR2 (256) | 233 | 233 | 233 | 233 |
| MASKW (rcard) | to `$8A34` | to `$8A79` | | |
| RENDERW (rcard) | to `$A381` | to `$A3BB` | | |

- **Card bytes freed.** The game's card has 48 B free at `$FE4B-$FE7A`, between BKNEAR and the kernel's `KVARS`. `playlayout.check()` only asks that rcard end below `$FE7B`.
- **Zero page.** New: `BK_MODE` `$34` (RELEASE), `BK_V` `$35-$36`, ZLOOP `$A0-$A9`. All three are in the bucket pass's overlay 1 and `$70-$AF`. The replay keeps to `$48-$6F`.

### Files

| File | Change |
| --- | --- |
| `src/native/rrec.s` | the counts in REC_ROOM and rec_start; REC_FLUSH rewritten |
| `src/native/mmain.s` | FCNT into MCNT; the assert |
| `src/native/bucket.s` | nb_bucket, scan (walk + walk 2), chunk/cwin, zl_put, walk1 for RELEASE only, in the card; `covered` removed |
| `tools/native/rlayout.py` | FCNTLO/HI, MCNTLO/HI, BK_ZLOOP; WCODE_END = FCNTLO; regions; allowed writes: the front end FCNT, the masked phase MCNT, the bucket pass MCNT (the RELEASE recount) |
| `tools/native/bucketcheck.py` | the image holds MCNT as the producers leave it (`counts()`) and RECDROP 0; `--obj` |

`src/native/rframe.s` and `src/native/render.cfg` are unchanged.

## The checks (the owner's rule)

All commands ran from `demos/doom_gs`, with the builds in my own `build/tmp-bucket-wave1/` (deleted afterwards).

1. `python3 tools/native/bucketcheck.py --no-build --obj OBJ --jobs 2`: 200 frames and 400 runs (fills a5 and 5a); **0 frames differ**. This covers every batch's W bytes, the column starts, the covered records' W addresses, the batch list, and the write log.
2. `python3 tools/native/frame8.py --no-build --obj OBJ --fills a5 --jobs 2 --timing --frames still-1,demo3-325,demo3-277,demo3-036,demo3-052,demo3-114,demo3-343,demo3-344,demo3-257,demo3-345,demo3-256,demo3-258,demo3-054,demo3-000,demo3-050,demo3-100,demo3-150,demo3-200,demo3-250,demo3-300,demo3-350,demo3-400,demo3-450,demo3-500`. These are the ten heaviest by report8.md (demo3-036 among them), every 50th demo3 frame, still-1 and the two median frames. Result: **24 of 24 equal**, 22,990 records and 199 clip-log calls compared; screens, SHR writes, write logs and stack all held.
3. The game build's paths that this part changed (the recount, the area's end), each with its existing check:
   - `python3 -m unittest test_native_frame8.ReleasePolicy` (3 tests, OK): the dropped batches (`RECDROP`, now a recount), `rec_flush` at the last area's end before, at and past `$C000` (the new split), and the replay's cut.
   - BucketLimits' two cases, run against my builds rather than through `RC.make()` into the shared obj directory:
     - the 45-batch frame: equal, 45 batches;
     - a column past a batch: the test build BRKs; the RELEASE build cuts column 3 with ST_RECORDS, and its batches equal the loader's.
4. Planted bugs, both caught:
   - scan's cursor one byte short: bucketcheck reports both frames;
   - REC_FLUSH's next-area base off by one: frame8 fails demo3-036, the frame that crosses `$C000`.
5. The existing planted-bug anchors in these files still apply once each. These are the integrator's full-suite tests, not run here: `test_native_frame8`'s bucket bugs, `test_native_masked`'s `BUCKET_BUGS`, and `test_native_masked_b`'s UPOFS bugs. Two details keep them applying:
   - `walk2:` labels scan's walk 2 part (the head uses normal labels `scan_nx`, `scan_rf` and `scan_bad`);
   - `beq @stop ; walk 1)` is kept, with the MAXB overflow on `@maxb`.

   The relabelled build is byte-identical to the build that was checked.
6. OVLW built from these sources (`make -f m11.mk part P=s2ovl`, into a scratch M11). `s2ovl.image_problems()` is `[]`: OVLW's BKFAR and BKFAR2 equal the frame image's.

## For the integrator (files this part does not own)

1. **`tools/native/s2ovl.py` `ovlw_allowed()`.** In the `'rrec'` list, after `('main', 0, R.UPOFS, R.UPOFS + R.VIEWWIDTH),`, add:

   ```python
                    ('main', 0, R.MCNTLO, R.MCNTLO + R.VIEWWIDTH),
                    ('main', 0, R.MCNTHI, R.MCNTHI + R.VIEWWIDTH),
   ```

   OVLW's `mrec_room` now counts its K_OVL records into MCNT. Without this, `test_m11_s2ovl`'s write check reports those stores as stray.
2. **Rebuild OVLW with rcard, every time.**
   - Run `make -f render.mk` (or `RC.make()`) and `make -f m11.mk part P=s2ovl` before `playdisk.py`.
   - OVLW carries its own copies of `mrec_room` and of BKFAR/BKFAR2. A stale OVLW with the new card BKNEAR would call the old `chunk` entry, and would not count its records, so the overlay frames would break.
   - `s2ovl.image_problems()` must be `[]`.
3. **docs/MEMORY_MAP.md section 13.** Add these rows:
   - `| W | $AD00-$AD9F, $AE00-$AE9F | Speed wave 1: FCNTLO, FCNTHI, each column's count of W bytes of the front end's records (rec_room; zeroed by rec_start), after the front end's code (WCODE_END = $AD00); left by the masked image's load and copied by nm_masked into MCNT |`
   - `| W | $6600-$669F, $6700-$679F | Speed wave 1: MCNTLO, MCNTHI, the masked phase's counts (nm_masked's copy, then mrec_room and OVLW's mrec_room), over the front end's dead first code bytes; nb_bucket makes the batches from them (walk 1 gone; the game build counts again from the staging after a drop or at a column past a batch) |`
   - `| zero page | $34-$36, $A0-$A9 | Speed wave 1: the bucket pass's BK_MODE (game build) and BK_V (scan's page-1 pointer); ZLOOP, the chunk's 10-byte copy loop (written by zl_put each frame) |`
   - Correct the `card $E000 part` row: BKNEAR is 190 B (`$FD8D-$FE4A`). It holds the chunk's window part `cwin`, the parking and bring-back, `bstop`, and in the game build `bk_cut`, `bk_kept` and `walk1`. With RCODE, `$F900-$FE4A`.
4. **docs/RENDER-MASKED.md.**
   - In 3.4, item 2 (Walk 1), add: "*Speed wave 1 (2026-10-02):* the producers keep the counts (rrec.s rec_room, MCNT); walk 1 runs only in the game build's recount (a dropped batch, a column past a batch)."
   - In 6.2, optimisation 10, add: "Built in speed wave 1 (docs/speed-parts/bucket.md): the 320 B are W, FCNT after the front end's code and MCNT below MCODE."
5. **src/native/bucket.cfg header comment.** Its sizes are now out of date: BKNEAR is 190 B in the test build and 305 B with `-D RELEASE`. NEAR's size (`$0173`) still fits.
6. **SPEED.md section 4, row 8.** Measured: −4.8 ms still, −4.5 at demo3's median, −13.2 in the heaviest frame (render, f121).

## Open problems

- **(c) as asked: an unrolled per-kind copy.** That would be a chain of `lda P1+1+j,x / sta (BK_P),y / dey`, entered per kind through `jmp (table,x)`. It needs about 85-100 B in one segment. The test and game build have 48 B free in BKNEAR, 59 B in BKFAR (49 with RPROF) and 23 B in BKFAR2; the RELEASE builds have no room at all. Its estimated gain over the two-pointer loop is about 0.3 ms still and 0.7 ms in the heaviest frame. I left it out. The 48 B of card freed at `$FE4B-$FE7A` seemed better kept for other parts.
- **RELEASE + RPROF BKFAR is at 767 of 768 B.** Any code added to BKFAR's RELEASE paths needs room found first. The RELEASE ftest BKNEAR is at 305 of 309.
- **The game build is not `-D RELEASE`.** This is unchanged by this part: rcard links the test build's bucket pass. A staging that fills, or a column past a batch, therefore stops the game with a BRK. The RELEASE variant's card parts (RCODE + BKNEAR) end at `$FEFB`, past the kernel's `$FE7B`.
- **A column holding more than 64 KB of records.** It now saturates and stops (test build) or is counted again (game build). The old walk 1 let the 16-bit count wrap. No frame can stage that much in one column: the heaviest stages 17 KB in all.
