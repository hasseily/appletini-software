# Speed plan, wave 2, part `objapi`: the object API's far windows

Written 2026-10-03 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, item 5. It changes only time: the game's state stays exact (the lockstep run below).

Files: `src/native/gobj.s`, `tools/native/glayout.py` (one range and its check), `tests/test_objapi.py` (new), this note. No cache size changed (section 2 says why).

## Results

a2vm f121, card-equivalent (`playtime.py`, exact idle), `build/native/DOOM.hdv` built in a scratch clone of HEAD with this part and the placement of step 1 below:

| Scene | Before (HEAD) | After | Change |
| --- | ---: | ---: | ---: |
| demo3, gametics 1052-1796, 186 frames | 272.1 ms, **3.67 FPS**; K_TIC 188.90 | 258.7 ms, **3.87 FPS**; K_TIC 175.61 | **−13.4 ms a frame** (K_TIC −13.3) |
| E1M1 standing still, 15-25 s | 88.4 ms, **11.32 FPS**; K_TIC 24.78 | 87.6 ms, **11.41 FPS**; K_TIC 24.02 | **−0.8 ms a frame** |

- Median demo3 271.8 → 256.4 ms. The heaviest frame reads 634.5 → 682.3 ms; the cut's last frame ends at gametic 1795 instead of 1796, so the frames group different tics and the maximum is not like for like. I did not chase it further.
- Every other step is unchanged to 0.1 ms (K_WLOAD, nr_frame, nm_masked, nb_frame, P2DW). The gain is all in the tic phase. At the card's 1.14 (SPEED.md 5) that is about −15 ms a frame of the card's TIC row in the benchmark.
- **Short of the plan's −20 to −35 ms (demo3) and −3 to −5 (still).** The model (section 2) shows why. Bigger caches buy almost nothing in the room that exists. Standing still, the whole object API is about 2.5 ms a frame, so −3 to −5 was never reachable there. Section 5 lists what would reach further: each item needs a change outside this part's files.
- Lockstep exactness, the owner's one check, in the clone with the placement of step 1: `python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2`. **ok: 2,134 tics compared (1051-3185), 0 failures, same-pair hits 1,009 = 1,009.**
- The object API's own tests: `python3 tools/native/gselftest.py` (fill a5 and 00), every check ok (api, spawn, fcall, planes, free, unbuilt, load). `--plants`: all five caught. `python3 tools/native/glayout.py --check`: ok. `tests/test_objapi.py`: 3 tests ok. One planted bug: a descriptor table too large for page 1 (`PW_MAX` 6) fails to assemble on the window's assert.
- The bug that the play run caught during the work: bl_get's second-half address took the first add's carry. Lines past the level's end were fetched, a write-back went into the card's kernel, and the play run hung at an IRQ bound. Fixed before the measurements above. The lockstep run was not run on that version.

## 1. Where the time went (measured)

The profile is a2vm `--pclog` at far_get's and far_put's entries and returns, and at the new window's. It counts the tic image's K_TIC only, demo3, gametics 1052-1400, 89 frames. The figures are ms a frame.

| | HEAD | This part |
| --- | ---: | ---: |
| K_TIC (this cut) | 177.4 | 165.1 |
| far windows (far_get, far_put, the page-1 window) | 54.6 (3,503 calls) | 44.9 (2,260 calls) |
| mobj miss: 4 groups | 4 windows × 13.7 µs, 190 a frame: 10.5 | 1 window, 38.0 µs: 7.25 |
| line miss: record, 2 sector bytes | 17.1 + 2 × 5.7 µs: 5.4 | 1 window, 22.5 µs: 4.27 |
| sector miss: 2 records | 10.8 + 17.0 µs: 2.6 | 1 window, 22.1 µs: 2.07 |
| bl_get, 256 B, 99 a frame | 99.8 µs: 9.88 | 2 descriptors of 128, 74.0 µs: 7.32 |
| mobj write-backs, 150 lines a frame | one far_put a group, 17 µs each: 5.99 | one window a line (26.4 µs for 2 groups): 4.47 |
| line write-back, 32 B | 21.2 µs | 18.6 µs |
| special fetch / write-back, 32 B | 17.2 / 21.8 µs | 16.2 / 18.6 µs |

Per call, f121:
- A soft-switch access costs about 1.3 µs (4 a far_get).
- A byte costs about 0.3 µs through far_get's `(zp),y` loop with its `cpy`.
- It costs about 0.21 µs through the new loop, `abs,y` with operands patched per descriptor, `dey`, `bpl`.
- What remains is the bytes and RamWorks' line misses.

The window's descriptor set-up costs more than far_get's for tiny records. A 4-byte subsector through it was 9.6 µs against far_get's 6.7, and a 24-byte seg 13.9 against 13.6. So the uncached fetches but bl_get stay with far_get (`fetch_to`).

## 2. Sizing: the tags replayed through a model of the caches

The recorder logged every get, dirty, store, flush and reset of the tic image's K_TIC in the play build: a2vm `--pclog` at the API's entries with A:X, GC_MO and GC_H. Recorded: still (124 frames), walk (155) and demo3 (gametics 1052-1400, 89 frames). A host model of gobj.s's LRU, dirty bits and flush replayed them for every size. Figures are a frame. A frame is one flush, so a cache never holds across frames: the render phases reuse its memory.

| Cache, lines | 8 | 12 | 16 | 24 | Room a line |
| --- | ---: | ---: | ---: | ---: | --- |
| mobj misses, demo3 / walk / still | 190 / 34 / 27 | 183 / 32 / 26 | 179 / 32 / 26 | 172 / 32 / 26 | 96 B main (MOC is all of `$0C00-$0EFF`) |
| line misses, demo3 / walk / still | 190 / 16 / 0.6 | 182 / 14 / 0.6 | 177 / 12 / 0.6 | 167 / 12 / 0.6 | 34 B W |
| sector misses, demo3 / walk / still | 93 / 7 / 5 | 88 / 7 / 5 | 78 / 7 / 5 | 59 / 7 / 5 | 48 B main (SCC is all of `$1680-$17FF`) |
| special misses (5 lines today), demo3 / walk / still | 79 / 45 / 37 | 79 / 12 / 12 | 79 / 12 / 12 | 20 / 12 / 12 | 32 B W |

- **mobjs and lines are near their compulsory misses.** Most of a frame's mobjs and lines are touched once a frame. 24 lines would save about 18 mobj and 23 line misses in demo3 (about 1.5 ms) for 1.5 KB of main and 544 B of W that do not exist. Main has no render-dead range left that glayout.py's check accepts: MOC, SCC, BL_BUF and RT fill the rows of MEMORY_MAP.md 13 that are not persistent. W's GW has 168 B free (`$B358-$B3FF`).
- **Specials cycle.** A frame's light thinkers, about 12 standing still and 20 in demo3, each get their record twice a tic. With 5 lines every first get misses. 12 lines would remove 25-33 misses a frame standing still or walking (about 0.4-0.6 ms with the write-backs). 24 lines would remove 59 in demo3 (about 1.7 ms). That needs 224 B (12) or 608 B (24) more in W. It does not fit GW's 168 B.
- **Uncached fetches**, LRU over the same tags:
  - nodes: 272 a frame in demo3, 122 misses with 16 lines, 448 B;
  - direct-mapped nodes in GW's 168 B: 35-71 hits, under 0.7 ms;
  - subsectors: 4 lines, 64 hits of 130;
  - mobjinfo words: the last type hits 65 of 88.
  None pays its bytes in core and memory.
- **Hits.** In demo3, 55% of mo_gets are of the line last got, and 20% of the one before. A get now searches the recency order from its front and moves the line to the front in the same pass. Before, it searched by line number, then searched the order again and shifted it.

So the sizes stay: 8, 8, 8, 5. The gain comes from the misses' windows.

## 3. What changed in gobj.s

1. **The window in page 1** (`pw_go`, 55 B of code at `PW_AT` = `$0100`, then 4 descriptors of 6 B, to `$014F`).
   - Each descriptor is a bank, a source, a destination and a length − 1 (1-128 B).
   - It turns RAMRD (pw_get) or RAMWRT (pw_put) on once. Each descriptor writes RWBANK and copies with `lda abs,y / sta abs,y / dey / bpl`, its operands patched from the descriptor. Then the switch goes off and RWBANK to 0, as every window.
   - Page 1 is near in every RAMRD/RAMWRT state, as the replay's gather uses it (MEMORY_MAP.md 2). The card had no room.
   - `go_reset` copies the code there. Every tic phase and the load image run go_reset or go_flush (which ends in go_reset) before any get: dl_brain at every K_TIC, gdriver's drv_game and after each frame, lsetup's nl_setup. The page-1 bytes are the same in every image.
2. **Misses in one window.**
   - A mobj's four groups (4 descriptors).
   - A line's record and its two sectors (3).
   - A sector's two records (2).
   - A victim's dirty groups or records in one write window.
   - bl_get's 256 B as two descriptors of 128.
   - A special's record, and a line's or special's write-back, as one descriptor (faster loop).
   - Coherence is as before: the victim is written back before its line is retagged, flush writes every dirty line, and the dirty bits are unchanged.
3. **Gets search the recency order** (mo_get, sec_get, ln_get, sp_find) and move the line to the front in the same pass (`mo_top`, `sec_top`, `ln_top`, `sp_top`). The LRU is exactly the old one, so the "four most recently got are never evicted" guarantee holds.
4. **mo_store gets the line through mo_get.** A miss reads the slot's old record once, and the copy then overwrites it with every group dirty. The final state is the same. It costs one window on about 4 stores a frame.
5. **Test-only parts.**
   - The counters (GO_HITS, GO_MISS, GO_WBACK) and mo_tagged exist only in TESTBUILD images. Only gtest.s imports mo_tagged, and only gselftest.py reads the counters. They live in the test driver's card segment `DRIVER`, so the core holds only the `jsr` sites.
   - GO_WBACK now counts write-back windows. gselftest's expected 4, 20, 1 still holds: one dirty group, one window.
   - GO_LAST is no longer written; nothing read it. Its RT bytes stay in glayout.py's list.
6. ln_dirty's code is unchanged, word for word. gameroutine.py's plant `missed-write-back` edits it.

Core sizes (gobj.o's LOADW): HEAD 2,369 B in every build. Now 2,406 B without TESTBUILD (play, release, the load image) and 2,433 B with it (game, gprof, skel), +37 and +64.

## 4. For the integrator

1. **The placement must be redone** (SPEED.md 7, step 1).
   - With HEAD's placement the lockstep build `game` overflows the core by 54 B (gprof's fixed core is the binding one).
   - `python3 tools/native/gplace.py --write`, from the current placement, found a placement that fits. The model's cost against HEAD's placement, ms a tic:
     - demo3 21.339 → 21.392;
     - still 3.169 → 3.296 (one load a tic more);
     - walk 7.062 → 7.189;
     - lock3a 35.128 → 35.143.
   - The measurements above include that cost. Other wave-2 parts change sizes too, so run it once after merging them all.
   - A first version of this part grew the test builds' core by 183 B. The search's best then cost +2.2 ms a tic in demo3. Keep the core growth of later changes small.
2. **Page 1 in the tic phase and the load image.**
   - MEMORY_MAP.md 2 and GAME.md 4.5 should say: `$0100-$014F` holds the object API's window (glayout.py `TIC_PAGE1`, ggame.inc `PW_AT`, `PW_END`).
   - glayout.py's check now requires `PW_END <= $0100 + $EF + 1 − TIC_STACK` (160 B, the IRQ's 24 included, as gcallgraph.py counts it, from the drivers' S `$EF`; the play kernel's is higher).
   - Measured in demo3 with this part, the play build's lowest S was `$A7` (the IRQ in the card) and `$AA` in the tic image, 88 B above the window. HEAD's was `$A5`.
   - Nothing else of the tic phase uses page 1. The replay's and the 2D phases' page-1 buffers are other phases, and K_TIC's go_reset rewrites the window after them.
   - If a later part puts the tic phase's or the load's code or data in page 1, it must stay above `$014F`.
3. **GAME.md 3.4** (the API's table): the counters are test-only. mo_tagged is test-only. mo_store reads the old record on a miss.
4. **tests/README.md**: `test_objapi` reads `build/native/game/skel/gen` (the prebuild's) and writes nothing shared.

## 5. Open problems: what would reach further (each outside this part's files)

Estimates from the profile above, demo3, ms a frame:

| Change | Files | Saves (est.) |
| --- | --- | ---: |
| `bl_word`: one blockmap word (2 B) for the list's place `bl_get(4 + block)` reads. Callers read only `BL_BUF[0..1]` there. checkpos keeps that window and sometimes finds the list in it (6.8 a frame), so it would refetch. | gobj.s (`bl_word`), giter.s, tracet.s, checkpos.s (`lb_word`'s window) | about 3 |
| `ln_stamped`: a line whose only change is its validcount stamp writes back 2 B, not 32 (ln_wback: DT bit 1 alone). It covers 183 write-backs a frame, nearly all of them stamps. The four stamp-only sites (sight.s:354, checkpos.s:654, giter.s:153, tracet.s:152) would call it instead of ln_dirty. gpos.s keeps ln_dirty, so the plant `missed-write-back` still bites. | gobj.s (+about 40 B), the four parts | about 2 |
| A state cache: state_at fetches a 16-B state record from GTAB 234 times a frame (10.6 µs each). | gspawn.s | up to 2.5 |
| 12-24 special lines (about 2 KB of W) | glayout/llayout, W's map | 0.5-1.7 |
| The planes out (one 256-B far_put a page, 1.6) | the loader's (ticloads) | |

Not built here. Each needs a part's own files and one lockstep run, and the owner's rule allows one.

## Commands

```
python3 tools/native/playtime.py --scene still|demo3          # before, after
python3 tools/native/gplace.py --write                        # the placement (step 1)
make -s -C src/native -f game.mk shared game gprof release skel ROOT=$PWD
make -s -C src/native -f level.mk ROOT=$PWD
python3 tools/native/playdisk.py
python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2
python3 tools/native/gselftest.py [--fill 00] [--plants]
python3 -m unittest test_objapi            # from tests/
```

The tag recorder, the cache model and the window profiler were scratch scripts (a2vm `--pclog` through `playtime.py`'s machinery). They are not in the tree.
