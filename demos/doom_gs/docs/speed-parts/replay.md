# Speed plan, wave 2, part `replay`: fewer texel bytes copied

Written 2026-10-03 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, item 10. It changes only time: every pixel, every SHR write, every batch and every strip stay the same, and the stage holds the same bytes wherever the draw reads them.

Of the three items asked for, (a) is built. (b) was built as a prototype and measured slower, so it is not in the tree. (c) has no place to keep its result (see "Not built").

## Results (a2vm, render only, `frame8.py --timing`)

The render shortens by the replay's gain; nothing else in the frame changed (the front end's `ftest.w` is byte-identical before and after).

| Frame | f121 render before | after | change | of which the replay | fastpath change | Render-only FPS, f121 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| still-1 | 59.36 ms | 58.93 | **−0.43** | 17.37 → 16.91 | −0.35 | 16.85 → 16.97 |
| demo3-325 (demo3's median render) | 67.87 | 65.91 | **−1.97** | 33.64 → 31.65 | −1.89 | 14.73 → 15.17 |
| demo3-036 (the heaviest) | 151.14 | 137.01 | **−14.12** | 71.05 → 56.83 | −12.48 | 6.62 → 7.30 |
| demo3-052 | 148.80 | 138.40 | −10.40 | 80.91 → 70.44 | −9.34 | |
| demo3-114 | 136.96 | 110.81 | **−26.16** | 75.40 → 49.16 | −23.76 | 7.30 → 9.02 |
| demo3-343 | 133.94 | 117.27 | −16.67 | 59.58 → 42.82 | −14.97 | |
| demo3-344 | 133.12 | 117.20 | −15.92 | 59.15 → 43.15 | −14.83 | |
| demo3-257 | 123.58 | 114.09 | −9.49 | 50.93 → 41.36 | −9.03 | |
| demo3-345 | 121.87 | 108.84 | −13.02 | 51.98 → 38.90 | −11.94 | |
| demo3-256 | 118.91 | 110.63 | −8.28 | 47.80 → 39.44 | −8.29 | |
| demo3-258 | 116.96 | 107.41 | −9.55 | 46.18 → 36.56 | −8.84 | |
| demo3-054 | 117.17 | 106.53 | −10.64 | 51.69 → 40.99 | −9.91 | |
| demo3-000, -050 ... -500 (every 50th) | | | −0.87 to −16.15 | | | |

- **demo3 as a whole.** On every tenth demo3 frame (54 frames), f121: the replay's mean is 34.89 → 31.17 ms and its median 33.98 → 31.78. The render's mean is 71.52 → 67.82 (**−3.69 ms a frame**) and its median 68.57 → 66.03. On fastpath the render's mean drops 3.44 ms.
- **Against the plan.** The plan expected −2 to −3 ms at demo3's median and −6 to −15 in the heaviest frames for (a). It measured −2.0 at the median frame and −8.3 to −26.2 in the ten heaviest.
- **The game's frame (derived, not measured on the game).** The replay is the benchmark's DRAW row, and every view frame runs it once, so the game frame shortens by the same milliseconds:

  | Scene, f121 | Before (wave 1 as integrated) | After, derived |
  | --- | --- | --- |
  | E1M1 standing still | 87.9 ms, 11.37 FPS | about 87.5 ms, **11.43 FPS** |
  | The benchmark, all of demo3 (the page's 303.9 ms a frame) | DRAW 35.7, FPS 3.294 | DRAW about 32.0, about 300.2 ms, **FPS about 3.33** |
  | demo3, gametics 1052-1796 (`playtime.py`) | 271.6 ms, 3.68 FPS | about 267.9 ms, **3.73 FPS** |

  `playtime.py --scene bench` on the integrated disk gives the measured figure.

- **The replay alone** (`replay_check.py --breakdown`, milestone 5's captures, f121, ms). The texel bytes come from `loader.texel_copies`; "before" counts each wrap as 128.

  | Frame | Wraps | Texel bytes copied, before → after | Copy before | Copy after | Replay before | Replay after | Change |
  | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
  | still-1 | 27 | 9,339 → 7,547 | 5.25 | 4.82 | 17.09 | 16.74 | −0.35 |
  | demo-01 | 162 | 22,552 → 17,876 | 6.05 | 5.05 | 33.44 | 32.54 | −0.90 |
  | demo-02 | 223 | 29,840 → 16,972 | 7.91 | 4.96 | 32.52 | 29.70 | −2.83 |
  | demo-03 | 47 | 17,048 → 13,028 | 4.68 | 3.70 | 29.47 | 28.54 | −0.93 |
  | demo-04 | 39 | 16,452 → 12,924 | 4.50 | 3.63 | 27.00 | 26.19 | −0.82 |
  | demo-05 | 45 | 9,544 → 7,576 | 2.79 | 2.34 | 29.27 | 28.86 | −0.41 |
  | demo-06 | 99 | 16,016 → 7,752 | 4.39 | 2.41 | 31.65 | 29.77 | −1.89 |
  | demo-07 | 158 | 24,579 → 12,467 | 7.36 | 4.51 | 31.77 | 29.04 | −2.73 |
  | demo-08 | 151 | 21,316 → 11,052 | 6.92 | 4.56 | 26.46 | 24.22 | −2.24 |
  | demo-09 | 127 | 18,304 → 10,088 | 6.38 | 4.50 | 21.86 | 20.14 | −1.72 |
  | demo-10 | 129 | 22,309 → 10,613 | 8.93 | 6.18 | 33.28 | 30.74 | −2.54 |
  | demo-11 | 139 | 23,000 → 12,432 | 8.89 | 6.44 | 34.06 | 31.78 | −2.28 |
  | e1m3-1 | 178 | 23,484 → 13,416 | 6.23 | 3.97 | 28.44 | 26.33 | −2.11 |

  The gather's walk is unchanged within 0.06 ms (+0.03 typical: the wrap test); the switches and the draw are unchanged.
- **Commands** (from `demos/doom_gs`; builds in my own `build/tmp-replay/`, deleted afterwards; the base built from `git archive HEAD src/native`):
  - `make -s -C src/native -f render.mk OUT=OBJ ROOT=$PWD` and `make -s -C src/native OUT=M5 ROOT=$PWD`;
  - `python3 tools/native/frame8.py --no-build --obj OBJ --fills a5 --jobs 2 --timing --json OUT.json --frames still-1,demo3-325,demo3-036,demo3-052,demo3-114,demo3-343,demo3-344,demo3-257,demo3-345,demo3-256,demo3-258,demo3-054,demo3-000,demo3-050,demo3-100,demo3-150,demo3-200,demo3-250,demo3-300,demo3-350,demo3-400,demo3-450,demo3-500`, on the base build and on this part's, with the same a2vm binary;
  - the demo3 mean: the same with `--frames demo3-000,demo3-010,...,demo3-530`;
  - `python3 tools/native/replay_check.py --obj M5 --out DIR --jobs 2 --breakdown --json OUT.json`.

## What changed

### (a) A wrap-only span copies its two runs (`replay.s` gather_texture, run_one)

- **What a wrap is.** The draw's texel position wraps at 128 (every row block does `and #$7F`). A span is the run of texels its rows can reach: from TI, `count` = n × csi + hi(TF + n × csf) + 2, rounded up to 4. When TI + count passes 128 but count does not, the texels read are [TI, 128) and [0, TI + count − 128). Before, such a record copied all 128 texels. It now copies only those two runs, each widened to whole groups of 4: [TI & $FC, 128) and [0, (TI + count − 128 + 3) & $FC).
- **The stage is unchanged.** The record still takes 128 bytes of the stage, with texel t at its place + t, exactly as "all 128" did. So the strips, the stage pointers, the descriptor groups and the RELEASE cut are the same as before. The hole between the two runs is never read.
- **The descriptor.** +6 now holds the second run's first texel, TI & $FC (4-124), which marks a wrap. +5 holds the first run's count. run_one copies [0, +5) from the two bases, moves both bases by +6, and copies [+6, 128) with Y from 127 − +6. It uses the same unrolled `(zp),y` loop. A wrap from TI 0-3 copies all 128.
- **span_length** no longer tests TI. It returns C set only when the count passes 128, and gather_texture now tells the wrap apart. All of its branches already carry C set, so `@far` is a bare `rts`.

### Room in the card (`replay.s`, `render.cfg`)

- **p1_image moved to card bank 2.** It is the per-row copy's image (37 B), which nat_replay copies into page 1 with bank 2 already selected. `jtent` (3 B), which only the draw calls (bank 2 selected), went with it. Both now sit in `TEXBLK`'s slack after the row blocks' landing, at `$DBD1-$DBF8`; `$DBF9-$DBFF` (7 B) is left. Every tool copies `TEXBLK` by its map range or copies the whole `.lc2`, and frame8 already counts `TEXBLK` as the replay's code.
- **The rollback restores pl, gtop, gdx with a 10-byte loop.** The column-does-not-fit path (once a strip) used 30 B. The zero page now orders `pl`, `gtop`, `gdx` together, and the scratch orders `cpl`, `cgtop`, `cgdx` the same way. Asserts guard both orders. The save at each column's start stays unrolled, since it runs once a column.
- **Sizes:**

  | Segment | Before | After |
  | --- | --- | --- |
  | RCODE | `$F900-$FD8C` (1,165 B) | `$F900-$FD86` (1,159 B) |
  | BKNEAR (test and game build) | `$FD8D-$FE4A` | `$FD87-$FE44` (unchanged, 190 B) |
  | The game's card free before `KVARS` | 48 B, `$FE4B-$FE7A` | 54 B, `$FE45-$FE7A` |
  | RCODE + BKNEAR, `-D RELEASE` | to `$FEFB` (4 B free) | to `$FEF5` (10 B free) |
  | TEXBLK | `$D000-$DBD0` | `$D000-$DBF8` |
  | RHOT | `$DE00-$DFFC` | unchanged |

  Every build links with no warnings: rtest/rprof/rwall/mtest/ftest/fprof/rcard; the RELEASE variant of all of them (`ASFLAGS = -D RELEASE`, the way test_native_frame8 plants it); and milestone 5's test/prof/card.

### Tools

- **`tools/native/loader.py`.** New `texel_copies(data, csf, csi)` gives the runs the replay copies, a wrap's two included. `stage_plan` and the package counts gain `wrap` and `copy_bytes`. `stage_need` is unchanged: a wrap is still 'all' and still needs 128 bytes, so `copy_groups` and the strips are unchanged too.
- **`tools/native/replay_check.py`.**
  - New `--obj DIR`, so a scratch build can be checked: `make -C src/native OUT=DIR`. It defaults to `build/native/obj`.
  - The `--breakdown` line now also prints the texel bytes copied.

## The check (the owner's rule)

1. `python3 tools/native/replay_check.py --obj M5 --out DIR --jobs 2 --breakdown`: **15 frames, 15 passed.** Every frame's pixels, stray writes (snapshots and the write log), SHR stores and switches held, in the captured and poisoned runs. This includes demo-02 (223 wraps) and the two-batch frames demo-10 and demo-11.
2. `python3 tools/native/frame8.py --no-build --obj OBJ --fills a5 --jobs 2 --timing --frames <the 23 above>`: **23 frames, 23 equal**, 22,398 records and 197 clip-log calls compared. The 23 are demo3-036, the ten heaviest by `report8.md`, every 50th demo3 frame, still-1 and demo3-325. The timing sample of every tenth demo3 frame also ran the check: 54 of 54 equal.
3. **Two planted bugs, both caught** by `replay_check.py` on demo-02, demo-07 and e1m3-1:
   - the wrap's second run starting 4 texels late (`ora #4` on TI & $FC): 119-167 differing bytes;
   - its first run one group short (`sbc #128 + 1`): 27-145 differing bytes.
4. **The final sources were rebuilt and compared.** After the last comment edits, `test.lc`, `prof.lc`, `card.lc` and the `.lc2`, `.rc` and `.a02` of `ftest`, `fprof` and `rcard` are byte-identical to the checked builds.
5. **Every test anchor in `replay.s` still matches once.** These are `test_native_replay.BUGS`, the three stage-shrink edits of `test_native_frame8.ReleasePolicy`, and nat_replay's first instruction (`sta gcol`), which the benchmark's timing jumps over.

## Not built

- **(b) `lda abs,y / sta abs,y` with patched operands.** It was prototyped in a scratch copy: the span loop unrolled 4 times, its 8 operands (16 bytes) set before each run. `replay_check --breakdown` measured it **slower**: the copy took +0.10 ms (still-1) to +0.49 ms (demo-02).
  - Each run pays about 90 cycles of patching. The loop saves at most 2 cycles a byte (`lda abs,y` 4 against `(zp),y` 5; `sta` 5 against 6), and after (a) a run averages about 60 bytes.
  - It has no home either. frame8 lets the replay write only page 1 and card `$D000-$DDFF`. Page 1's code room (`$0190-$01B4`) is full with the per-row loop, and a patched loop in bank 2 needs 31 B of the 7 left. `replay_check` would also need the patch bytes listed as allowed card writes (RENDER.md 3.7).
- **(c) Walk 2 computing each texture record's stage need.** The need has nowhere to go.
  - A W record has no spare byte: `K_TEX` has 11, `K_TEXC` 7, and every field is read by the gather or the draw (TF and TI by both).
  - Making a record longer changes the W byte counts the producers keep (rrec.s `REC_ROOM`, FCNT/MCNT), and with them the batch splits.
  - A side stream in production order would need its own per-column cursors (320 B of main during the render) and code in BKFAR, which has 1 B free in the RELEASE + RPROF build.
  - The gather's walk (2.0-4.0 ms, unchanged) is about 330 cycles a texture record: the record's fields, the descriptor, the stage pointer, and for spans the 8-step multiply in span_length. An unrolled multiply would save about 40 cycles a span record, but needs about 60 B, which the RELEASE card does not have (10 B).

## For the integrator (files this part does not own)

1. **docs/MEMORY_MAP.md.**
   - Section 4's bank 2 table: replace the row `| $DBD1-$DBFF | 47 | generator slack | |` with:
     - `| $DBD1-$DBF8 | 40 | the replay's per-row copy image p1_image (37 B, copied to page 1 $0190 by nat_replay) and jtent (3 B); speed wave 2 | |`
     - `| $DBF9-$DBFF | 7 | free | |`
   - Section 13's card `$E000` part row: RCODE `$F900-$FD86`, BKNEAR `$FD87-$FE44`, 54 B free at `$FE45-$FE7A` before the kernel's `KVARS`.
2. **src/native/bucket.cfg header comment.** Change "`$F900-$FD8C: 1,165 bytes; 371 left`" to "`$F900-$FD86: 1,159 bytes; 377 left`", and "`$F900-$FEFB`" to "`$F900-$FEF5`". NEAR's start is unaffected: bucket.cfg links BKNEAR alone.
3. **src/native/README.md (the replay).**
   - In its list of how a texture record's texels reach the stage, add the wrap as replay.s's header now has it.
   - In "Results", note that since speed wave 2 a wrap copies only its two runs (this document's replay_check table).
4. **docs/RENDER-MASKED.md 6.2, optimisation 4.** Add: "*Speed wave 2 (docs/speed-parts/replay.md):* the copies only: a wrap-only span copies its two runs; the stage plan in the bucket pass was not built (no spare record byte)."
5. **SPEED.md section 4, row 10.** Measured, render f121:
   - −0.43 ms still;
   - −1.97 at demo3's median frame, and −3.69 on demo3's mean (every tenth frame);
   - −8.3 to −26.2 in the ten heaviest (demo3-036 −14.1);
   - (b) measured slower and not built; (c) not built.
6. **`playlayout.check()`** needs nothing: rcard's card part now ends at `$FE44`, below `$FE7B`.
7. **Rebuild OVLW with rcard (`make -f m11.mk part P=s2ovl`, or m11.mk's images) before `playdisk.py`.** RCODE is 6 B shorter, so BKNEAR moved from `$FD8D` to `$FD87`. OVLW carries its own BKFAR, linked against rcard's `__BKNEAR_LOAD__`, and a stale OVLW would call `cwin`, `park` and `back` 6 B too high. `s2ovl.image_problems()` must be `[]` (bucket.md's integrator note 2; SPEED.md 7 step 2 already orders it).
8. **`tests/test_native_replay.py`, `test_the_image_fills_what_the_frame_leaves` (line 429).** It checks that a byte the build leaves undefined takes the fill, and it used `$DBD1`, the first byte of bank 2's generator slack. The build now defines `$DBD1-$DBF8` (p1_image and jtent), so that byte holds `$98` (`tya`) and the assert fails. The same check on the slack's first byte still free keeps the test's meaning: change `a2run.LC + 0xDBD1 - 0xC000,` to `a2run.LC + 0xDBF9 - 0xC000,`. Checked on this part's build: `$DBF9` and `$DBFF` take `$A5`.
9. **bucket.cfg's `NEAR: start = $FD8D`** may become `$FD87` to mirror rcard. Nothing needs it: btest links the bucket pass without the replay.

## Open problems

- **The derived game figures are not measured.** No `DOOM.hdv` was built and no `playtime.py` run was made, because other parts of the wave are changing the tree. The game figures above are the render's measured gain added to wave 1's measured frame.
- **The card is still tight.** The RELEASE build's card has 10 B free, and bank 2's slack 7 B. A later part that needs card room for the replay must find it first. Candidates: the save at the column's start as a loop (−20 B, about +35 cycles a column), or `fill_offset` (11 B) into bank 2 once it has the room.
