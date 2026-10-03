# Speed plan, wave 2, part `frontend`: the phase loader, the walk's box corners, the weapon's clip pass

Written 2026-10-03 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, items 11 (the front end's half) and 13, and RENDER-MASKED.md 6.2, optimisations 1 (in part), 2 and 8. It changes only time. Every frame the renderer draws stays byte for byte the same; the checks below compare them.

## Results (a2vm `f121`, the play disk)

Both disks were built in scratch clones of the tree: "before" is HEAD (`b894fb5c`, `DOOM.hdv` SHA-1 `90635ac1…`, the owner's disk), "after" is HEAD with this part's four files and the kernel's one-line change of request 1 below. `playtime.py`, card-equivalent (exact idle), ms a frame:

| Scene | Before | After | Change |
| --- | --- | --- | --- |
| still, 15-25 s, f121 | 88.4 mean, 87.4 median, **11.32 FPS**; K_WLOAD 4.95, nr_frame 25.94, nm_masked 3.89 | 86.0 mean, 85.2 median, **11.63 FPS**; K_WLOAD 4.70, nr_frame 24.40, nm_masked 3.81 | **−2.4 ms** (+0.31 FPS) |
| still, fastpath | 84.7, 11.81 FPS | 82.8, 12.07 FPS | −1.9 ms |
| demo3, gametics 1052-1796, f121 | 272.1 mean, 271.8 median, 3.67 FPS; K_WLOAD 4.96, nr_frame 21.92, nm_masked 7.70 | 271.7 mean, 271.5 median, 3.68 FPS; K_WLOAD 4.72, nr_frame 21.87, nm_masked 7.60 | −0.4 ms |
| The menu's BENCHMARK (all of demo3, 534 frames), f121 | FPS 3.294 (5,673 realtics); page rows 3D 23.2, MASK 14.2 | FPS 3.298 (5,667 realtics); 3D 22.9, MASK 14.1 | −0.3 ms a frame |
| walk, 14-32 s, f121 | 136.6 ms, 7.32 FPS | 143.1 ms, 6.99 FPS | not like for like: the route diverges (K_TIC 78.1 against 83.5, 30.3 against 32.1 loads a tic); the render's steps: K_WLOAD 4.95 → 4.71, nr_frame 10.85 → 11.07, nm_masked 2.05 → 1.68 |

By item:

- **(2) far_wloadt**: K_WLOAD −0.25 ms every frame (5 pages fewer at 64 µs, less the page item 3 adds).
- **(3) the box corner cache**: −1.15 ms of the walk at a still view (nr_frame −1.54 with item 4). A frame at a new map unit pays about +0.02 to +0.07 ms in the walk (frame8, single frames: cc_frame's two windows and a test a node, less 20 cycles a node that bspnode's address now saves) and the W page below.
- **(4) the weapon's clip pass** at a weapon-skip frame: 0.459 → 0.073 ms (frame8 `clip` phase, still-2, demo3-185, demo3-200).
- **The cost**: the front end's code is 317 B larger (rbsp.s +276 B, wpsp.s's front end copy +41 B; its masked copy −7 B), so the front end's image is one page longer (69 pages, RENDERW to `$A4F8` in rcard): +0.063 ms of K_WLOAD every frame, included in the figures above.
- **(1) not built**: see "Item 1" below. On F1.2.1 the four loads are bound by the RamWorks reads, not the CPU.

Render only (`frame8.py --timing`, f121, ms; the `sprites`, `weapon` and `replay` phases move by up to 2.6 ms with 0 cycles and 0 I/O changed: VBL and drain alignment, not code):

| Frame | Total before | Total after | window | walk | clip |
| --- | ---: | ---: | --- | --- | --- |
| still-1 (first skipping frame) | 59.36 | 59.33 | 4.924 → 4.987 | 7.297 → 7.328 | 0.459 → 0.459 |
| still-2 (skip run) | 59.31 | 58.82 | 4.924 → 4.987 | 7.291 → 7.329 | 0.459 → 0.073 |
| demo3-185 (standing) | 64.31 | 63.76 | 4.924 → 4.987 | 5.103 → 5.141 | 0.613 → 0.073 |
| demo3-036 (heaviest) | 151.14 | 150.91 | 4.924 → 4.987 | 9.503 → 9.536 | 0.613 → 0.613 |
| demo3-300 | 49.30 | 49.38 | 4.924 → 4.987 | 1.467 → 1.482 | 0.612 → 0.612 |

frame8 injects each frame into a fresh machine, so it never reaches the corner cache's reads (the walk's gain shows only from the second frame at one map unit: the play disk's still scene, and the RENDER disk's chained and full runs below).

**Commands** (`OBJ` a render build, `CLONE` a scratch clone with the play disk built):

- `python3 tools/native/playtime.py --scene still|demo3|walk|bench --profile f121|fastpath [--disk D --play P] --json OUT`
- `python3 tools/native/frame8.py --no-build --obj OBJ --frames F --fills a5 --jobs 2 --timing --json OUT`, F = still-1, still-2, demo3-036, synth-pagefull, synth-crowd, demo3-052, -114, -343, -344, -257, -345, -256 (report8.md's ten heaviest), demo3-000, -050, …, -500 (every 50th), demo3-472 (a turn in place), demo3-185 (a skip run).

## The checks (the owner's rule: the renderer's)

- **frame8**, the 25 frames above, fill `a5`: **25 of 25 equal**, 0 failed (25,348 records, 348 clip log calls), before and after.
- **The RENDER disk** (`rdisk.py --no-build --check`, far.s changed), the default window demo3-020 … demo3-119: f121 and fastpath, chained and full: **100 of 100 CRCs equal** in each of the four runs.
- **The corner cache's hits**, which only a run of frames reaches: `rdisk.py --first 440 --frames 45 --profiles f121 --check` (demo3-440 … -484: the view stands at one map unit over 443-451 and 470-479, turning in place at 449-451 and 470-479): **45 of 45** chained and full.
- **One planted bug**: a hit that keeps the box before's angles (`jmp cc_get` → `rts`). The same window gave 28 of 45 in both modes, with the standing frames from demo3-444 on named. So the hits run and the check sees them.
- `python3 tools/native/s2layout.py --check`, `llayout.check()`, `rlayout.check()`, `tests/test_native_render_level`: pass. The builds (render, m11 images, level, play) have no warnings.
- **No lockstep run**: no game code changed. The walk now writes each node record's pad (bytes 28-29), which the game never reads (`gobj.s` `nd_get` fetches `NODEB_SIZE` = 28 bytes). The level's load writes those bytes as 0.

## What changed

### Item 1: far_pload's loop (not built)

The planned loop (`lda $xx00,y / sta $xx00,y / iny`, twice, the operands' high bytes patched per page) was built and timed in two forms:

| far_wload (77 pages) | 65C02 cycles | f121 ms | fastpath ms |
| --- | ---: | ---: | ---: |
| HEAD's `(zp),y` loop | 290,591 | 4.924 | 4.621 |
| abs,y, patched operands in the card | 251,927 | 4.924 | 4.037 |
| abs,y, the loop copied to page 1 (as the replay's row loop) | 253,100 | 4.926 | 4.057 |

The patched loop runs 13% fewer cycles. On f121 the time does not change: a page costs its RamWorks reads, about 64 µs (250 ns a byte), and HEAD's loop already ran at that speed. The task's "CPU-bound" holds for fastpath only (−0.57 ms for this load; about −1.7 ms a frame over the four). Two more reasons not to build it now:

- The card version writes the card from the loader's PCs. The page-1 version writes W from PCs in page 1. Each would need every stray checker to allow it: `render_check.stray` and `stray_masked` (`LOADER_WRITES`), `lrun.stray`, `s2run`'s loader owner.
- The card version uses 29 of the FAR area's 34 free bytes. The page-1 version needs 15 more bytes than the card has.

`far.s` keeps its loop. The comment there says why. Fewer pages are the f121 gain (item 2).

(The task's note that wave 1's far_gcopy sits at the FAR area's end does not match the tree: far_gcopy is the kernel's, at `KERN_GCOPY` `$FFD5`. far.s holds nothing of it.)

### Item 2: far_wloadt (far.s)

- A second entry, `far_wloadt`, loads the front end's image from page `$65` (`WL_TIC`) instead of `$60`, with the same tables. `far_wload` is unchanged. The RENDER disk's runner, the test drivers and frame8's frame mode still use it, because there nothing else leaves MATHW in `$6000-$64FF`: the replay's batches (`RECBUF` `$6000`) overwrite it every frame.
- Both lists follow `wl_front`, so `pldisk.area_problems`, which compares RLOAD up to `wl_front`, still holds for every image.
- An assert checks that the front end's code reaches past `$6500`.
- RLOAD grows by 9 B (`$DE4D-$DE97`). MFAR moves to `$DE98-$DFE5` in rcard (`$DFE6` in ftest/mtest), which leaves 25 B free at the card area's end.
- Verified: the tic image's `tic.w` (`$6000-$6592`) is byte for byte rcard.w's. MATHW has no self-modified bytes (AUXW in `$65xx` is loaded again by far_wloadt).

### Item 3: the box corner cache (rbsp.s, rlayout.py)

A corner's angle (`pta16` of the corner from the view's map unit) depends only on the box and the unit. The walk keeps, per node, the two angles of the box and case it last checked:

- **The tag** is in the node record's pad: `ND_CCT` holds the stamp, then the key. The walk fetches the tag with the node.
  - The key is the low byte of the box's pointer, EOR the case. The node's frame depth is fixed by the tree, so the byte is the same at every visit: 8 ^ k for box 0, 16 ^ k for box 1, disjoint for k 0-8.
  - The level's records have 0 there, and 0 is no stamp.
- **The angles**: `CCANG` in RENDB, `$2040 + 4 n` (`$2040-$2C3F`). The address of node n's angles is the node's address / 8 + `$2000`.
- **The state**: `CCSTATE` (RENDB `$1C00-$1C04`) holds the unit the entries belong to and its stamp. `cc_frame` reads it once a frame (one RAMRD window).
  - At the same unit, with a nonzero stamp, the cache is on (`CC_ON` `$C0`).
  - Otherwise it is off, and CCSTATE takes the new unit and the next stamp (one RAMWRT window). After stamp 255, `cc_clear` zeroes every node's stamp first, so stamps run 1-255.
  - The state is the cache's own, not the frame block's (95 of 96 B are taken). No harness injects it, so a frame injected whole (frame8, the RENDER disk's full mode) never meets entries that its own view did not make. With VA_STAMP, which full mode injects, a stale entry was possible.
- **The walk**: bspnode puts the node's address in its frame (`ND_CCN`, the frame's bytes 30-31) when the cache is on. nr_checkbox's corners now come from `cc_corners`:
  - when on and the tag matches: the angles, one RAMRD window (`cc_get` → far_get);
  - else: computed as before, then, when on, written back with the tag (one RAMWRT window, RENDB then LVMAP).
- **Smaller and faster code** (to stay within one more W page):
  - bspnode's 32 n is `(n << 8) >> 3`: 20 cycles a node fewer.
  - nr_sub's two bases are page aligned, so only the high byte is added.
  - bspnode no longer masks a subsector's bit 15: `SUBBASE + 4 n` drops it.
- **rlayout.py**:
  - `NODE` gets `CCT` (28) and `CCN` (30).
  - New: `CCSTATE`, `CCST_SIZE`, `CCANG`, `CCANG_END`, the constant `NODE_CAP`.
  - Overlay 1 gets `CC_ON`, `CC_K` and `CC_A`, at `$39-$3E`, after `T0`, unused until now.
  - The spill gets `CC_ST` (`$02BF`).
  - Regions: RENDB's state and angles.
  - The allowed writes: `corner_cache_writes()` (the state, the angles, each node's 2 tag bytes), last in `allowed_writes` and `allowed_writes_b` (the new `walk_writes` is the old body).

### Item 4: the weapon's clip pass at a skip frame (wpsp.s, rlayout.py)

In a run of frames that skip the weapon rows, WCLIP is FLOORCLIP after the clip pass of the run's first frame. The clip pass is a function of FRVIS, the view's bottom and the patch's profile.

So the front end's `wp_start` (the RENDERW copy only: `.ifndef MPSP`) copies WCLIP into FLOORCLIP and returns 1 ("nothing more", so nw_clip ends) when all of these hold:

- the frame before skipped (`FR_SKIP`);
- this frame's FRVIS equals WPREV (all 12 bytes);
- FRVIS's x1 is not 0;
- WCLIP's column 0, outside the weapon, equals this frame's viewbottom + 1.

This replaces about 33 far windows (the profile's header, the entries, a list per column). Every other case runs the clip pass as before.

`ps_vis` keeps the psprite's input offset in a new zero-page byte, `WP_PO` (OVW's last, `$9D`), instead of reloading it three times (−9 B in both images). The masked phase's draw is unchanged. At a skip frame it draws through R_DrawVisSprite with WCLIP, upstream's rule, and its records must stay that path's.

### Files

`src/native/far.s` (far_wloadt, wl_tic, the loader's comments), `src/native/rbsp.s`, `src/native/wpsp.s`, `tools/native/rlayout.py`, this file. `mpsp.s`, `mproj.s` and `mfar.s` are unchanged.

## For the integrator

1. **The kernel** (`src/native/dl_kern.s`, part ticloads' file), `k_wload`: `jsr XS_far_wload` → `jsr XS_far_wloadt`. Also `tools/native/playlink.py` `RCARD_SYMS`: add `'far_wloadt'` (after `'far_wload'`).
   - Measured with both changes in a clone: K_WLOAD 4.95 → 4.70 standing still.
   - This needs `$6000-$64FF` to hold MATHW's bytes at every K_WLOAD. K_TIC loads the tic image (or ticloads' P2DW-left bytes) just before, so ticloads' assert of identical bytes covers it.
   - Without this change the game still runs exactly, but loads from `$60`, and keeps the extra page item 3 costs.
2. **MEMORY_MAP.md** rows:
   - RENDB `$1C00-$1C04` CCSTATE and `$2040-$2C3F` CCANG (the corner cache);
   - LVMAP: each node record's bytes 28-29, the cache's tag, written by the walk;
   - the node frames' bytes 30-31, the node's address;
   - zero page `$39-$3E` in the front end (`CC_ON`, `CC_K`, `CC_A`);
   - spill `$02BF-$02C3` (`CC_ST`);
   - overlay 2 `$9D` (`WP_PO`) in both phases.
3. **RENDER-MASKED.md 6.2**: optimisations 2 and 8 built (8 as the clip pass's reuse), 1 in part (far_wloadt).
4. **SPEED.md section 4**:
   - items 11 and 13: the figures above;
   - item 11's loop: "no gain on F1.2.1, 13% fewer cycles, fastpath −0.57 ms a WCODE load".
5. **The W page budget**: RENDERW ends at `$A4F8` in rcard, 7 B before page `$A5`. Any part that adds 8 B or more to the front end's image adds a page, 64 µs a frame.
6. **A test for the cache** (optional): frame8 cannot reach its hits. The RENDER disk window `--first 440 --frames 45` does, and the planted bug above fails it.

## Open problems

- **The corner cache pays off only where the view stands.** 39 of demo3's 533 frames are at the map unit of the frame before. Every other frame pays the extra W page (0.063 ms) and 0.02-0.07 ms in the walk. The benchmark gains 0.3 ms a frame, mostly from far_wloadt.
- **Item 1** waits for the fast path (fastpath, or the firmware design), and for the harnesses' loader rule (above).
- **The walk scene** cannot compare two builds: its input runs on model time. Its render steps are given above.
- `rdisk.py --check` reports "2 memory-API requests" for the static load and passes. Its docstring says one. This part does not touch the static load; the base build was not run to compare.
