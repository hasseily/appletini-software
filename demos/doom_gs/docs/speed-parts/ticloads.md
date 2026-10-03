# Speed plan, wave 2, part `ticloads`: fewer bytes loaded for the tic phase

Written 2026-10-03 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, items 4, 12 and the tic image's half of 11. It changes only time: the game's state and the demo's sync are the same (checked below).

Files: `src/native/gcall.s` (gr_load and the group directory), `src/native/dl_kern.s`, `src/native/dl_disp.s`, `tools/native/grun.py`, `tools/native/playdisk.py`, and the new `tests/test_ticloads.py`. `src/native/gthink.s` is unchanged: the dirty flag it would have held was built, measured and dropped (section 2).

## Results (a2vm f121, card-equivalent, `playtime.py`)

| Scene | Before (HEAD, the owner's disk `90635ac1…`) | After | Change |
| --- | ---: | ---: | ---: |
| still, 15-25 s | 88.4 ms, 11.32 FPS; K_TIC 24.78 | **85.0 ms, 11.77 FPS**; K_TIC 21.44 | −3.4 ms |
| demo3, gametics 1052-1796 | 272.1 ms, 3.67 FPS; K_TIC 188.90 | **267.1 ms, 3.75 FPS**; K_TIC 183.85 | −5.0 ms |

By item (K_TIC, ms a frame, measured on builds with and without each):

| Item | still | demo3 | Expected (SPEED.md 4) |
| --- | ---: | ---: | --- |
| (1) the last page's used bytes | −0.75 | −3.6 | −2 to −4 still, −10 to −16 demo3 |
| (2) planes below G_MOHWM, one RAMWRT window, plus (3) the core from `$66` | −2.6 | −1.4 | (2) about −2 still, −1 demo3; (3) −0.4 |

Commands (each in a scratch APFS clone of HEAD with only these files changed; other parts' uncommitted edits left out):

```
python3 tools/native/playdisk.py
python3 tools/native/playtime.py --scene still --profile f121
python3 tools/native/playtime.py --scene demo3 --profile f121
```

Item (1) gains less than the estimate because the placement fills groups close to 2,048 B, so the groups demo3 loads most leave little of their last page unused: 1,976 B leaves 72, 1,963 B leaves 93, 1,936 B leaves 120.

## What it does

### 1. The last page's used bytes (gcall.s gr_load, the directory)

- **The directory** gets `grp_tail` beside `grp_pages`. `grp_pages` is now the whole pages (at least 1), and `grp_tail` is the number of bytes gr_load copies of the page after them: the group's length rounded up to an even count, or 0 when the page is copied whole. `grun.group_entry` decides this for both the test images (grun.py) and the disk (playdisk.py `tic_segments`). It copies the page whole for a group under 256 B (see below), and for a tail over `TAIL_MAX` (224) bytes, where the second window costs more than the bytes it skips.
- **gr_load** copies the whole pages with `far_gcopy` as before (Y = 0), then, when `grp_tail` is not 0, makes one more `far_gcopy` call of one page from byte `256 - grp_tail` of the last whole page. FA_SRC and FA_DST are the page before the tail's page, with low byte `grp_tail`, so the copy ends exactly at the tail's last byte.
- **The kernel's far_gcopy** (`dl_kern.s`) drops its `ldy #0`: it copies FA_N pages from FA_SRC + Y to FA_DST + Y. That costs 2 bytes less in the kernel.
- **The test driver's far_gcopy** (`gdriver.s`, unchanged) starts every page at byte 0. For the tail it therefore copies the Y bytes before the tail again. Those are the group's own bytes, copied a moment earlier from the same bank addresses, so the result is the same. This is why a group needs a whole page before its tail (the rule for groups under 256 B): otherwise the test driver would write before the slot. The lockstep images therefore load every group correctly with gdriver.s as it is.
- **The tables** shrink from 64 to 49 entries (`MAXGRP = 43 + 5 + 1`: gplace's MAX_GROUPS, then the glue's 5 or the test builds' 3 TEST_GROUPS). That pays for most of `grp_tail`. The core grows 15 B in every build: play `$98CE` → `$98DD`, game `$99DD` → `$99EC`, gprof `$99E7` → `$99F6` (9 B under `$99FF`, inside gplace's CORE_MARGIN of 16), release, skel. playdisk.py checks that the play build's groups plus the glue's fit.
- **No group reads past its length.** `playdisk.group_problems` runs at every disk build and fails the build if any of these is false:
  - every segment loaded into a group's memory area is stored (none is bss);
  - the group's file ends where its last segment ends, so `.res` bytes are inside the copied length;
  - every label in a slot lies inside some group's segments or at its end.
  
  It holds today. The lockstep's poisoned fills also never relied on the bytes past a group: they were `$A5` there before this change.

### 2. The planes (dl_disp.s planes_out, dl_kern.s k_planes)

- **planes_out** writes back each plane's pages below G_MOHWM, P = ⌈G_MOHWM / 256⌉. P is clamped to 1-3: 1 when G_MOHWM is 0, and 3 when the value is past the planes, as at the boot before any level has set it. It writes all four planes in **one RAMWRT window**. The window runs from DLG_D's own code in W: with RAMWRT on, instruction fetches still read main, and the IRQ contract allows any RAMWRT (`pl_irq.s`). So it needs no card room. Before, it was 12 `far_put` calls at 131.8 µs a page.
- **k_planes** is now four runs, one per plane (9 B). planes_out writes their counts (`kpl_set`) for the next K_TIC. `c_loadlist` sets all three pages per plane after its `c_out`, because nl_setup sets a new G_MOHWM. The boot's list is the whole planes. Slots past G_MOHWM keep another image's bytes in W and are never read: gt_pooltake raises G_MOHWM before gt_mosave writes a new slot's planes.
- **The dirty flag (TNL, TNH and KIND written back only when changed): built, measured, dropped.** Every write of those planes goes through gobj.s's `pl_put` and `pl_setn`, which gt_add, gt_mosave, gt_zfree and the parts call. `pl_put` also writes TICS, and the walk calls it for every tic count, so the flag has to compare in `pl_put`. That costs about 1,200 compares a frame in demo3. Measured on the same build with and without the flag:
  - demo3: K_TIC 184.76 with the flag against 183.85 without, **+0.9 ms**;
  - still: 21.30 against 21.44, −0.14 ms.
  
  It loses on the benchmark, so it is not in the tree. The version that was measured, for the record (gobj.s, not this part's file): in `pl_put`'s non-LOADIMG branch, before each of the first three stores, `lda (GO_P) / eor PL_N(+1, PL_K) / tsb pl_dirty`; in `pl_setn`, `lda #$80 / tsb pl_dirty`; a core byte `pl_dirty` in gthink.s, first value 0, reloaded at each K_TIC; planes_out skips TNL, TNH and KIND when it is 0 and clears it after the window.
- **Kernel room.** The kernel's slot reset is now a loop over `SLOT_GRP`, `SLOT_NEED` (5 contiguous bytes, asserted), which saves 7 B. That pays for k_planes' 6 extra bytes. The lists sit at a fixed place, `KLISTS = BT_REPLAY - 12` (`$FFB8`: k_core then k_planes), because dl_disp.s in the tic image writes them, and the tic image is linked before the card. `dl_kern.s` asserts the place (lderror) and so does `playdisk.shared_w_problems`. `$FFB7` is one byte of padding. With the 2 B saved in far_gcopy, the kernel has 3 B free.

### 3. The tic image's core from `$66` (dl_disp.s st_load, kc_from)

- **st_load** decides the next K_TIC's first page from the list's last image load:
  - P2DW's: `$66`, with the core's page count 6 less;
  - any other: `$60`, the whole tic image's W and core.
  
  `kc_from` writes k_core's first page and adjusts its count by the same amount, so dl_disp.s needs no core size. Every level frame and the title's poll end with P2DW; the intermission, the finale, the menu, the automap's responder, the load and the boot do not.
- **The build-time assert** (`playdisk.shared_w_problems`, run by `problems()` at every disk build) checks:
  - the tic image, P2DW and WCODE link MATHW (`$6000-$6500`) and AUXW (`$6501-$6592`) at the same places with the same bytes, and nothing else below `$6600`, except WCODE's RENDERW, which starts at `$6593`;
  - a linear 65C02 sweep of P2DW's MATHW, AUXW and S2CODE, the kernel (`$FF00-$FFF9`) and its menu loop (KMAIN, KMAIN2) finds no absolute store or read-modify-write into `$6000-$65FF`, except AUXW's self-set window operands (`axv_rd` … `ax4_b3`, +1 and +2) and `ax_out`. AUXW's own routines write those before they read them. These are the steps from P2DW's load to K_TIC: s2_frame or s2_poll, then bt_mark.
  
  It does not check indirect stores. P2DW makes them through the far layer and its screen pointers, never into W.
- **Strictly identical bytes are `$6000-$6592`.** `$6593-$65FF` is RENDERW code in WCODE, padding in the tic image and unstored in P2DW; the tic image and P2DW never use it. Part frontend's `wl_front` from `$65` reloads that page, so it relies only on `$6000-$64FF`, which this assert covers.

## Exactness

- **The lockstep** (the owner's one check for game code and paging), in the clone: `python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2`. Result: **ok**. 2,134 tics were compared with 0 failures (gametics 1051-3185, G_MOHWM up to 337, the same-pair hits 1,009 on both sides), in 110 s.
- **The planted bug** (gr_load's tail pointer: `dec FA_DST+1` left out, so the tail lands one page late): **caught**. With `--tics 300`, all 300 tics failed: the machine broke at once and gave no readable native state. The same bounded run of the real build gave 300 tics compared, 0 failures.
- **The play build's own path.** The kernel's far_gcopy from Y, planes_out and the kernel's lists run only in the play build; gdriver.s has its own copies, so the lockstep cannot see them. I checked them with a scripted demo3 run of both disks on a2vm f121, stopped at the same gametic (`--stop-word` on G_GAMETIC), then compared the snapshots. The script was scratch and has been deleted.
  - Compared: the 13 aux banks the E1M7 manifest names, with MOBJP below G_MOHWM; W's four planes below G_MOHWM; the mobj, sector and line caches; the globals `$1C80-$1EFF`; and the lockstep's canonical digests (gcanon, through the manifest).
  - Gametic 1501: identical. The manifest reader cannot read this mid-tic state on either disk, because a cache line is not yet written back, so the comparison there is raw bytes only.
  - Gametic 1797: identical, including all 22 digests. G_MOHWM is 337 on both, so the planes use 2 of their 3 pages.
  - A planted floor instead of ceiling in planes_out's page count (1 page for G_MOHWM 337) is **caught**: the demo breaks from its first frame and the run never reaches gametic 1501 within 150 s of model time. The good builds reach 1797 at about 87 s.
- **The asserts:** `tests/test_ticloads.py` (8 tests: the directory over every size 1-2,048, the sweep, both link checks on the current play build, one planted fault for each check). Run from `tests/`: `python3 -m unittest test_ticloads`.

## Requests to the integrator

1. **testpar.py / tests/README.md race table:** `test_ticloads` reads `build/native/play` and the render obj (as `test_playtime` does). It writes nothing.
2. **The core grew 15 B in every build.** The gprof core now ends at `$99F6`. Run step 1 (`gplace.py --write`) as usual. Part glue's `s2t_hu.o` in the play core makes that step necessary anyway. gplace.py's comment "gcall.s's MAXGRP 64" (line 771) now reads 49.
3. **Optional, measured, about −1.2 ms more in demo3: one window per group.** Change gdriver.s's far_gcopy to start at byte Y. gr_load then makes a single `far_gcopy` call: FA_N = pages + 1, FA_SRC and FA_DST one page before, with low byte `grp_tail`, and Y = 256 − `grp_tail`. That copies exactly the group's even length, and groups under a page work too. Measured on the play build: demo3 K_TIC 182.62 against 183.85, still 21.29 against 21.44. It needs gdriver.s, which is why it is not in the tree: today's gdriver would write the Y bytes before the slot. The two changes:
   - gr_load's copy becomes:
     ```
             ldy #0
             lda grp_tail,x
             sta FA_SRC
             sta FA_DST
             beq :+
             dec FA_SRC+1
             dec FA_DST+1
             inc FA_N
             eor #$FF
             inc a
             tay
     :       jsr far_gcopy
     ```
     (with `stz FA_SRC` / `stz FA_DST` removed, and grun.group_entry no longer forcing a whole page for groups under 256 B).
   - gdriver.s far_gcopy starts at Y:
     ```
     far_gcopy:                      ; FA_N pages from FA_SRC + Y, FA_DST + Y
             lda FA_N
             sta FC_PS
             tya
             beq @whole
             jsr gc_add              ; both pointers on by Y
             tya
             eor #$FF
             inc a
             sta FA_N                ; the first page's 256 - Y bytes
             jsr far_get
             lda FA_N
             jsr gc_add              ; on past them
             dec FC_PS
             beq @done
     @whole: stz FA_N
     :       jsr far_get
             inc FA_SRC+1
             inc FA_DST+1
             dec FC_PS
             bne :-
     @done:  rts
     gc_add: pha
             clc
             adc FA_SRC
             sta FA_SRC
             bcc :+
             inc FA_SRC+1
     :       pla
             clc
             adc FA_DST
             sta FA_DST
             bcc :+
             inc FA_DST+1
     :       rts
     ```
   That needs one lockstep run.
4. **Documents:**
   - PLAY.md 3, K_TIC's row: "the core (and W unless the list ended with P2DW), each plane's pages below G_MOHWM".
   - PLAY.md 4, the kernel row: `$FF00-$FFB6` code, `$FFB8-$FFC3` the load lists (KLISTS), `$FFB7` padding.
   - PLAY.md 5: the tic image's load.
   - GAME.md 1.3: the planes are copied below G_MOHWM, as written; the write-back is now one window.
   - SPEED.md 4, items 4, 11 (ticloads' half) and 12: built, with the figures above. Item 12's dirty flag is measured as a loss; record the numbers.
