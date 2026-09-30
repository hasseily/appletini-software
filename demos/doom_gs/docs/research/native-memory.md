# Memory and code plan for a native 65C02 rewrite

Status: research, 2026-09-30. Nothing here is built. It answers the owner's
direction of 2026-09-30: every routine of upstream becomes native 65C02
code, upstream's SHR techniques stay, and music goes to the Phasor. This
file plans where code and data live on the Appletini, how far data is
reached on today's firmware (F1.2.1) and with the zero-page bank pair, and
what a frame would cost.

Tags:

- **[M]** measured: I ran it. "Model" means a2vm's cost model
  (`build/a2vm/a2vm`, not rebuilt), whose parameters come from the RTL,
  not from the card. "Traces" means the `ref816` traces of `PROFILE.md`
  (`build/a2vm/interp/still.trace`, `demo.trace`).
- **[R place]** read at that place.
- **[A]** assumed, with the range used.

Times use `tools/a2vm/costs/appletini.json` with `axi_us` at **0.14 µs**
(the value being recalibrated; the file still says 0.305) unless a row
says 0.305. "F1.2.1" is profile `f121`. "Design + pair" is profile
`fastpath` (relaxed admission, 16-line RamWorks cache, TURBO caches that
survive switches, quiet switches, lazy SHR mirror) with the zero-page bank
pair of `firmware/zpbank-spec.md` as corrected by `zpbank-review.md` in
place of the `$C069` read bank.

## 0. Summary

| Question | Answer |
|---|---|
| Native code size | Upstream places 170,564 code bytes [M]. About 145 KB of it serves the full-view game; at the 1.35 to 1.96 expansion measured on the executed code, that is **180 to 270 KB of 65C02 code**, kept in RamWorks as a code library. The per-frame hot set (99% of instructions) is **23 to 35 KB native**. |
| Fast memory | 95 KB in all, but only main (63.5 KB) serves code that also reaches far data. 18 KB of main (`$0400-$0BFF`, `$2000-$5FFF`) is write-expensive: every CPU store there leaves a mirror byte. Only memory-API PRIVATE writes fill it cheaply. |
| Memory API against the CPU | In the model the CPU copies as fast or faster whenever fast memory is one end: PSRAM to main 0.246 µs/B by CPU against 0.345 µs/B by the API (F1.2.1). The API wins for PSRAM to PSRAM (0.26 µs/B; 0.067 on the design) and PSRAM fills. It is the only cheap way to fill the write-expensive pages. It cannot write the language card, zero page or stack. |
| F1.2.1 | The replay is bound by the SHR drain: 0.985 µs a screen byte, 8.4 ms standing still and 21.4 ms in the demo [M, model]. Far data needs RAMRD/RAMWRT/`$C073` switches of about 1 µs each, and code in the language card while RAMRD is on. `$C073` cannot move while ALTZP is on, so the aux language card cannot hold tic code. One 24 KB code window in main is reloaded every frame: 6 to 18 ms. |
| Design + pair | The lazy mirror removes the drain. The pair reaches any RamWorks bank with one zero-page store while code keeps running from main. Tic code can live in the aux language card, so per-frame code loads fall to 0 to 4 ms. |
| Frame, 4 tics | Standing still: **37 to 72 ms on F1.2.1** (14 to 27 FPS), **22 to 42 ms with design + pair** (24 to 45 FPS). Title demo: **62 to 118 ms** (8.5 to 16 FPS) and **33 to 56 ms** (18 to 31 FPS). [A] on top of [M]: section 7. |
| a2vm | Needs the pair (state, `$C069`, zero-page watch, data-cycle redirect, a new cycle kind for JMP-indirect pointers), a cost path and two profiles, the slot-4 slowdown, and tests. Section 8. |

The ranges cover the hand-rewrite factor, the clocks per 65C02 cycle, far
batching and gather volume. They do not cover a memory plan that fails to
fit (section 3.4) or the hardware departing from the model (milestone 0).

## 1. The ground: what the target is fast and slow at

### 1.1 Memory map as the core sees it

| Region | Size | Speed | Notes |
|---|---:|---|---|
| Main `$0000-$01FF` | 0.5 KB | fast | Zero page and stack. The pair bytes live here (`$06/$07` suggested) [R `firmware/zpbank-review.md:180`]. |
| Main `$0200-$03FF`, `$0C00-$1FFF`, `$6000-$BFFF` | 29.5 KB | fast | Free to write. |
| Main `$0400-$0BFF`, `$2000-$5FFF` | 18 KB | fast to read, **slow to write** | Text and HGR pages: a CPU store is a video write, 6 clocks plus a mirror byte, drained at about 1 µs, now or at the next exposure access [R `tools/a2vm/a2vm.c:617-623`, `cost.c:785-791`, `research/appletini-hardware.md:66`]. Memory-API PRIVATE writes skip the mirror [R `README_MEMORY_API.md:173-188`]. |
| Main language card | 16 KB | fast | 12 KB visible, plus a second 4 KB `$D000` bank behind a `$C08x` switch. Not a memory-API endpoint [R `README_MEMORY_API.md:162`]. |
| Aux bank 0 `$2000-$9FFF` | 32 KB | the screen | SHR pixels, SCBs, palettes. Not usable for code or data. |
| Aux bank 0 `$0200-$1FFF`, `$A000-$BFFF` | 15.5 KB | fast | Reached through RAMRD/RAMWRT (a bus cycle each on F1.2.1, quiet on the design). The pair cannot name bank 0 [R `zpbank-review.md:132-135`]. `$0400-$0BFF` is write-expensive here too. |
| Aux language card, aux zero page | 16.5 KB | fast | Through ALTZP. ALTZP routes zero page, stack and card to the `$C073` bank [R `appletini-hardware.md:109`], so `$C073` must stay 0 while ALTZP is on. |
| RamWorks banks 1-126 | 8 MB | slow | PSRAM behind one 8-byte line (16 lines on the design). Bank 127 is excluded by the memory API and by the corrected pair [R `zpbank-review.md:23-30`]. |

### 1.2 Costs measured in the model

All from bus scripts on `build/a2vm/a2vm` [M, model]; each figure is one
run, deterministic.

| Operation | F1.2.1 | Design | Notes |
|---|---:|---:|---|
| Soft switch write (`$C073`, RAMRD on/off) | 127-131 clocks (0.95-0.98 µs) | 3 clocks | Plus a TURBO cache refill on F1.2.1. The documented range is 122-253 clocks by bus phase [R `a2vm/README.md:440`]. |
| 4,000 SHR bytes, then one `$C000` read | 0.37 ms loop + 3.57 ms wait | 0.37 ms + 0.002 ms | The drain is 0.985 µs a byte. A `$C073` write waits the same. |
| Textured pixel byte (native row kernel, 168 rows × 160 columns) | 0.564 µs, 75 clocks | 0.564 µs | Texel and colormap in main, store to SHR. 31.5 65C02 cycles a row: 2.4 clocks a cycle. |
| Same frame with the drain | 26.5 ms total (15.2 ms loop, 11.3 ms wait) | 15.2 ms | 26,880 bytes. |
| Fill pixel byte | 0.157 µs | 0.157 µs | 26,880 fill bytes: 4.2 ms loop, then 22.2 ms drain wait on F1.2.1. |
| CPU copy main to main | 0.188 µs/B | 0.188 µs/B | `lda (zp),y / sta (zp),y / iny`, 8 times unrolled. |
| CPU copy PSRAM to main (RAMRD, code in the LC) | 0.246 µs/B | 0.231 µs/B | Sequential; the line misses hide behind the loop. |
| CPU copy main to PSRAM (RAMWRT) | 0.369 µs/B | 0.260 µs/B | Write-allocate line: a fill and a write-back a line. |
| CPU read PSRAM, sequential | 0.185 µs/B | 0.145 µs/B | Against 0.101 µs/B from main. |

Memory-API requests, one descriptor, time of the request alone (the FIFO
transport adds 1.7 µs):

| Direction, 16 KB | F1.2.1, axi 0.14 | F1.2.1, axi 0.305 | Design, axi 0.14 |
|---|---:|---:|---:|
| PSRAM to main | 0.343 µs/B | 0.602 µs/B | 0.250 µs/B |
| main to PSRAM | 0.551 µs/B | 1.055 µs/B | 0.450 µs/B |
| PSRAM to PSRAM | 0.258 µs/B | 0.273 µs/B | 0.065 µs/B |
| main or aux 0 to main | 0.636 µs/B | 1.385 µs/B | 0.636 µs/B |
| FILL main | 0.214 µs/B | 0.466 µs/B | 0.214 µs/B |
| FILL PSRAM | 0.129 µs/B | 0.137 µs/B | 0.029 µs/B |
| Fixed cost of a request | about 7-8 µs | about 16 µs | about 7 µs |
| 16 descriptors of 128 B, PSRAM to main | 0.377 µs/B | 0.676 µs/B | 0.284 µs/B |

The only hardware anchor: the existing port moves 120,192 bytes a frame in
three requests, half saves and half loads, and its two copy phases took
40.5 ms on the card, 0.34 µs/B, VBL-sampled [R `tools/a2vm/README.md:498-517`].
The model gives 0.45 µs/B for that mix at 0.14 and 0.83 at 0.305. The
card is at least as fast as the 0.14 figures (its VBL sampling may
undercount holds).

**What this means.** Reading fast memory costs the ARM four AXI accesses
per 4 bytes, so the memory API is slow whenever main or base aux is the
source. Code loads are one-way (PSRAM to main) and never saved back:
0.25-0.35 µs/B either way. Data that changes in fast memory and must
persist should be written back rarely.

## 2. Code size per subsystem

### 2.1 Upstream bytes and heat

Upstream sizes from `build/linkmap.json` [M]; heat from `PROFILE.md`
section 3. A group's heat is the sum of its phases' rows, taken over all
frames together, which counts shared helpers more than once [R
`PROFILE.md:452-468`, `:533-547`]; the All row is the per-frame median
[R `PROFILE.md:391-396`, `:472-477`].

| Subsystem | Upstream code bytes | Executed, still / demo | 99% set, still / demo | Native estimate, all code | Native hot set (99%) |
|---|---:|---:|---:|---:|---:|
| Record replay and drawers (`drawcol.s`, `r_list65.s`) | 32,444 | 2,083 / 5,839 | 1,539 / 4,135 | 7-9 KB (hand-written, full view only) | 6-8 KB |
| Render front end (`r_seg65`, `r_wall65`, `r_bsp65`, `r_thing65`, `r_sprite65`, `r_frame65`, `r_iigs65`, `m_fixed65`, `m_recip65`, `tables65`, vendor runtime) | 36,816 | 12,556 / 21,551 | 11,079 / 15,261 | 50-72 KB | 19-26 KB |
| Game logic (the 21 `p_*.s`, `g_game65`, `m_random65`) | 50,550 | 3,861 / 28,371 | 3,210 / 15,804 | 68-101 KB | 5.7-28 KB |
| Level load and zone (`w_level65`, `p_setup65`, `r_data65`, `w_wad65`, `z_zone65`) | 12,854 | not per frame | | 17-26 KB | none |
| 2D, UI and video (`st_stuff65`, `hu_stuff65`, `m_menu65`, `am_map65`, `wi_stuff65`, `f_finale65`, `m_cheat65`, `patch65`, `i_viigs65`, `m_config65`) | 24,731 | 1,626 / 3,448 | 1,162 / 1,947 | 33-49 KB | 2-3.5 KB |
| Sound and music on the DOC (`s_sound65`, `i_snd65`, `i_doc65`, `irq65`) | 9,025 | | | replaced: Phasor player and effects, about 3-5 KB of code plus 14.8 KB of effect scripts [R `native-sound.md:27`] | 1-2 KB |
| Platform (`i_iigs65`, `iigs_asm`, `d_main65`, `crt0`, `string65`) | 4,144 | | | 4-6 KB, new code for the //e | 2-3 KB |
| **All** | **170,564** | 19,165 / 28,360 | 13,591 / 20,818 | **180-270 KB** | **23-35 KB** |

The vendor runtime is 447 bytes of the render row; the port replaces its
divides from the call sites, never from the file (MILESTONES ground rules).

The replay row excludes view-size and detail variants that only a smaller
view uses (`thirdimg`, `fourimg`, `fourlist`, `thirdlist`, `halflist`,
`onelist`, about 16 KB) [M, linkmap sections]. Smaller views load their
own drawer set when the view size changes, not per frame.

### 2.2 Evidence for the expansion

The task allowed 1.3 to 2 times unless better evidence appears. I
measured a transliteration on the traces [M]: every executed 65816
instruction (by opcode and the M and X widths it ran with) mapped to an
equivalent 65C02 sequence, with an assumed table of 65C02 cycles and bytes
per case [A: 16-bit operations cost two 8-bit ones plus 1 to 3 cycles for
carries and compares; REP/SEP vanish; XBA costs 8 cycles; direct page is
zero page; long and near data are absolute, with far costs added
separately in section 5].

| Phase | 65816 cycles a frame (still) | 65C02 cycles (still) | Ratio still / demo | Share 16-bit A (still) | Bytes, 65C02 / 65816, still / demo |
|---|---:|---:|---:|---:|---:|
| Tics | 51,624 | 81,025 | 1.57 / 1.59 | 76% | 1.81 / 1.78 |
| Frame setup | 10,641 | 16,726 | 1.57 / 1.57 | 48% | 1.67 / 1.75 |
| BSP walk | 99,575 | 176,772 | 1.78 / 1.80 | 100% | 1.80 / 1.80 |
| Wall setup | 115,381 | 195,810 | 1.70 / 1.67 | 94% | 1.81 / 1.83 |
| Seg loops | 367,549 | 488,984 | 1.33 / 1.41 | 33% | 1.54 / 1.39 |
| Sprite projection | 17,880 | 32,418 | 1.81 / 1.80 | 100% | 1.96 / 1.96 |
| Masked drawing | 55,465 | 78,878 | 1.42 / 1.41 | 47% | 1.69 / 1.61 |
| Record replay | 389,768 | 450,252 | 1.16 / 1.13 | 4% | 1.35 / 1.37 |
| **Frame** | 1,121,166 | 1,539,640 | **1.37 / 1.32** | | |

So the code grows 1.35 times where upstream is 8-bit (the replay) and
about 1.8 times where it is 16-bit (logic, BSP, walls, sprites). I used
1.7 for the hot sets and 1.35 to 2.0 for the ranges. The hand-written
replay kernel confirms the low end: 36 bytes a row pair in 65C02 against
34 in upstream's pair image [M; R `research/iigs-renderer.md:161-163`].

One cost the transliteration misses: upstream multiplies through 512 KB
of quarter-square tables in banks `$13-$1A`, which a 65C02 cannot index.
A native multiply from 2 KB of fast tables costs about 100 to 150 cycles
more a product [A]. The traces show 3,960 reads of those banks a frame
standing still and 3,246 in the demo [M]. Corrected after review: a product
reads 8 bytes (`r_wall65.s:1732-1776`), so 485 to 530 products, the
experiment's count, not 1,000 to 1,300. Section 7 adds the older, higher
cost; the F1.2.1 still estimate drops by about 0.6-1.3 ms [A].

## 3. The plan: resident code, windows and loads

### 3.1 Principles

1. Code is immutable: load it, never save it back.
2. A phase's hot set is loaded once per phase change, not per call. Cold
   routines come through a small paging slot on first call.
3. The write-expensive pages hold read-only data loaded by the memory API
   with PRIVATE (colormaps, constant tables), never data the CPU updates.
4. Anything that switches `$C073`, RAMRD or RAMWRT runs from the language
   card or zero page on F1.2.1.
5. On F1.2.1, nothing touches `$Cxxx` while SHR bytes drain, except where
   a wait is intended.

### 3.2 Layout, both variants

| Region | Size | Content | Loaded |
|---|---:|---|---|
| Main zero page and stack | 0.5 KB | Hot variables of the running phase, pair bytes, a 128-byte texel bounce buffer in the stack page (`$0100-$017F`; the frame stack uses at most 86 bytes [R `PROFILE.md:686-688`]) | |
| Main `$0200-$03FF` | 0.5 KB | Globals, the IRQ vector at `$03FE` | once |
| Main `$0400-$0BFF` (write-expensive) | 2 KB | Colormap pages of light levels 32-33 (1 KB), constant tables such as `xtoviewangle` (1 KB) | per level, memory API |
| Main `$0C00-$1FFF` | 5 KB | Per-frame renderer arrays: clip arrays, `solidcol`, `COLW`, fill spans, covered ranges, weapon clip (about 3.5 KB [A]), hot game globals | scratch |
| Main `$2000-$5FFF` (write-expensive) | 16 KB | `shrcmapA`/`shrcmapB`, light levels 0-31 | per level, memory API (17,408 B: 6 ms) |
| Main `$6000-$BFFF` | 24 KB | Window W: code of the running phase (section 3.3) | per phase or resident |
| Main language card | 16 KB | Resident: IRQ entry and vectors, Phasor player and effects, input, far layer and bounce routines, phase loader and memory-API transport, 16-bit multiply and divide with their square tables, texture and fill row blocks and the record dispatcher | once |
| Aux 0 `$0200-$03FF`, `$0C00-$1FFF`, `$A000-$BFFF` | 13.5 KB | Renderer per-frame data: drawsegs, vissprites, openings; on F1.2.1 part of the records | scratch |
| Aux 0 `$0400-$0BFF` (write-expensive) | 2 KB | Read-only tables | per level |
| Aux language card | 16 KB | Design + pair: the tic window (12 KB visible, 4 KB behind `$C08x`). F1.2.1: read-only tables only | per level |
| RamWorks | up to 126 banks | Code library (3-5 banks), level window (22-24 banks, as upstream [R `iigs-renderer.md:510`]), level store, zone, big tables (FSTEP, reciprocal, log, sine, tangent, sprite scales, about 6 banks), songs and effect scripts (about 268 KB [R `native-sound.md:342`]), records (pair variant) | per level |

The language card budget is tight: platform about 6 KB, math about 4 KB,
row blocks and dispatcher about 5.5 KB [A]. Corrected after review: that
is 15.5 KB against 12 KB visible (plus 4 KB behind `$C08x`), before the
player's 4.2 KB of data; the card is oversubscribed and needs a byte-level
budget. The IRQ vector is `$FFFE` in the card, not `$03FE`; the bounce
buffer lives only during the pair build's replay. The fuzz blocks (2.2 KB
native) page into W when a spectre is visible.

### 3.3 Windows by phase

| Phase | F1.2.1 | Design + pair |
|---|---|---|
| Tics | Tic hot set loaded into W (5.5 KB still, 24-27 KB in a fight, the rest paged). Far data by switches from LC routines. | Tic hot set resident in the aux language card, ALTZP on, its own zero page. Pair writes go through a 20-byte trampoline present at the same address in both cards (ALTZP off, store, ALTZP on: quiet switches). Overflow paged each frame by CPU copy (the memory API cannot write the card). |
| Setup, BSP, walls, segs, sprites, masked | Render hot set loaded into W (about 20 KB still, 24 KB demo, overflow paged). | Render hot set resident in W; only overflow paged. |
| Replay | Row blocks and dispatcher resident in the LC. Texel gather into main, then drawing. | Same code; texels bounced per record into the stack page through the pair. |
| Status bar, HUD, finish | Small: in the LC or paged into W. Draws directly to SHR; nibble read-modify-write needs RAMRD on, so its inner loop is in the LC. | Same. |
| Menus, automap, intermission, level load | Loaded into W when the mode starts. | Same. |

Why the aux language card cannot hold tic code on F1.2.1: tics reach far
data 3,300 to 19,700 times a frame (section 5). With ALTZP on, a `$C073`
change also moves zero page, stack and the card itself, so each far batch
would need ALTZP off, `$C073`, RAMRD, then the reverse: six bus cycles,
about 6 µs [A from 1.2]. With the pair, `$C073` stays 0 and the trampoline
costs about 23 cycles. Corrected after review: with ALTZP on, the main
card (multiply, far layer, transport, IRQ handler) is unreachable, so the
aux card needs about 4-5 KB of duplicates, and the demo overflow becomes
13-16 KB (3.0-3.7 ms) [A].

### 3.4 Per-frame code loads

| Load | Bytes a frame, still / demo | Tool | F1.2.1 ms, still / demo | Design + pair ms, still / demo |
|---|---:|---|---:|---:|
| Tic window into W | 5.5 KB / 24-27 KB | CPU copy (0.246 µs/B) or memory API (0.345) | 1.4-1.9 / 6.0-9.5 | |
| Render window into W | 20 KB / 24 KB | same | 5.0-7.1 / 6.0-8.5 | |
| Tic overflow into the aux card | 0 / 8-11 KB | CPU copy only (0.231) | | 0 / 1.9-2.8 |
| Render overflow into W | 0 / 3.4 KB | CPU or memory API (0.231-0.252) | | 0 / 0.8-0.9 |
| **Total** | | | **6.4-9.0 / 12.0-18.0** | **0 / 2.7-3.7** |

With the memory API at `axi_us` 0.305, the F1.2.1 loads would be 15.7 ms
still and 29 to 31 ms in the demo; the CPU copy does not depend on it.

**Budget risk.** Adding up what the render phases want in fast memory:
code 26-40 KB, colormaps 17 KB, trig tables (`tantoangle` 8 KB,
`finetangent` 6 KB, `finesine` 4.4 KB, `viewangletox` 2 KB [M, linkmap]),
per-frame arrays and records 15-30 KB, game globals 8-16 KB. That is 90 to
130 KB against 63.5 KB of main plus 31.5 KB of aux (on F1.2.1 only main
counts: aux needs a switch that waits for the drain; see NATIVE.md §4.2).
Something must give:
shrink the trig tables to 16-bit entries (about 10 KB) [A], keep drawsegs,
openings and vissprites in aux 0, put records in RamWorks on the pair
variant, and page the colder 9% of render code. The estimates of section 7
assume this works out; a shortfall shows up as more paging (0.25 µs a
byte) or as switch-bound table lookups on F1.2.1 (about 2 µs each).

## 4. Where hot data lives

| Data | Size | Accesses a frame (still / demo, main phase) [M, traces] | F1.2.1 | Design + pair |
|---|---:|---|---|---|
| Colormaps A/B | 17 KB | 6,314 / 19,882 reads (replay) | main, write-expensive pages | same |
| Records | ≤ 53,760 B; 6 KB / 3 KB written | 5,975 / 3,080 writes (segs, masked), as many reads (replay) | main (about 8-9 KB, early flush beyond, as upstream's `flush` [R `iigs-renderer.md:54`]) | RamWorks bank through `zp_wr`/`zp_rd`, or aux 0 with quiet switches |
| Texel stage | 3-6 KB / 10-20 KB | one read per textured byte | main, filled per bank before drawing | 128 B in the stack page per record |
| Clip arrays, spans, covered ranges, `COLW` | about 3.5 KB [A] | thousands | main `$0C00-$1FFF` | same |
| drawsegs, vissprites, openings | up to 14.8 KB upstream [M, linkmap `r_state65.s`] | seg and sprite phases | aux 0 (bus cycle per switch) or main | aux 0, quiet switches |
| Trig and angle tables | 20 KB (10 KB with 16-bit entries) | BSP, walls, segs | main | main or RamWorks |
| `states`, `mobjinfo`, `sprnames` | 8.4 KB [M, linkmap `info65.s`] | tics | RamWorks, batched | RamWorks through the pair |
| Mobjs, thinkers, sectors (zone) | 20-54 KB touched a frame (77 / 213 pages) [R `PROFILE.md:208`, `:284-286`] | 2,649 r + 606 w / 13,896 r + 2,666 w (tics) | hot fields as arrays in main where they fit, the rest RamWorks | RamWorks through the pair, 16-line cache |
| Level geometry, texture column tables | per map, up to 1.5 MB with textures [R `iigs-renderer.md:517`] | BSP 1,592 / 365, segs 1,460 / 640 (level window) | RamWorks, batched per record | RamWorks through the pair |
| Texels, patches, sprites | in the level window | 6,314 / 19,882 (replay) | RamWorks, gathered | RamWorks, bounced |
| FSTEP, reciprocal, log, sine, B3F | about 380 KB upstream | 1,000 / 2,000 reads | RamWorks, or computed | RamWorks through the pair |
| Quarter squares `$13-$1A` | 512 KB upstream | 3,960 / 3,246 reads | dropped: CPU multiply | same |
| Music (DOC) `$27-$29`, `$6A-$72` | 184 KB+ | | dropped: MUS on the Phasor [R `native-sound.md`] | same |

## 5. Reaching far data

### 5.1 Far traffic that remains

After the layout of section 4 (near data, colormaps, records and tables in
fast memory; multiply on the CPU), the traces give these far accesses a
frame, medians [M, traces, grouped by bank: level window, zone, FSTEP,
reciprocal/log/sine/B3F, sprite tables, weapon profiles]:

| Phase | Still: reads / writes | Demo: reads / writes | PROFILE.md far total, still / demo |
|---|---:|---:|---:|
| Tics | 2,723 / 606 | 17,069 / 2,666 | 3,886 / 23,677 |
| BSP walk | 2,286 / 16 | 465 / 4 | 3,626 / 704 |
| Wall setup | 1,546 / 0 | 223 / 0 | 6,200 / 1,019 |
| Seg loops | 2,056 / 0 | 960 / 0 | 11,845 / 5,163 |
| Sprites | 608 / 0 | 386 / 0 | 1,116 / 729 |
| Masked | 829 / 0 | 738 / 0 | 2,327 / 2,507 |
| Replay (texels) | 6,314 / 0 | 19,882 / 0 | 32,817 / 68,850 |
| **All but the replay** | **about 10,700** | **about 22,500** | 29,949 / 47,345 [R `PROFILE.md:737`] |

The seg loops lose most of their far traffic (records, fill spans and the
multiply tables become fast). The tics keep theirs: the zone.

### 5.2 F1.2.1: switch batching, bounce buffers, memory-API gathers

- **Switch batching.** A far window is RAMRD on (or RAMWRT on), with
  `$C073` set to the bank, around a loop. Two to four bus cycles a window,
  about 2.4-4 µs with the TURBO refill [M model, 1.2]. Code in the window
  runs from the LC or zero page, because RAMRD also moves opcode fetches
  from `$0200-$BFFF`. RAMRD and RAMWRT share one `$C073` bank, so a
  window cannot read bank N and write the screen (bank 0) at once.
- **Bounce buffers.** Copy a whole record (a node, a seg, a sector, a
  mobj's hot fields, a texel span) into zero page or main, close the
  window, work on it there. With 3 to 8 far reads per window, a far access
  costs 0.55 to 1.35 µs [A from the switch cost plus 0.25 µs a byte].
  Upstream's own changes of bank are 5,885 a frame standing still and
  9,832 in the demo outside the replay [R `PROFILE.md:383-385`]; sorting
  work by bank is the main lever.
- **The replay.** Gather first, draw second. For each bank in use, open
  one window and copy every texel span the frame needs into a main stage;
  then draw all columns with RAMWRT on and no `$Cxxx` access, so the drain
  overlaps the drawing. If the stage fills, draw a strip and continue; the
  next `$C073` write then waits for that strip's drain. Colormaps stay in
  main, because the draw reads them per pixel.
- **The drain floor.** Every SHR byte costs 0.985 µs of wall time on
  F1.2.1 unless the CPU works meanwhile without touching `$Cxxx`. The
  replay is at least 8.4 ms standing still and 21.4 ms in the demo.
  Upstream's own replay is written for this ("the drawers do the slow
  screen writes while the accelerator goes on") [R `iigs-renderer.md:62`].
- **Memory-API gathers.** Up to 16 descriptors a request, about 7-8 µs a
  request plus 0.34 µs/B into main [M model]. A 128-byte texel column
  costs 52 µs this way against about 33 µs by CPU (with its two switches). Not worth it per
  frame. Worth it for: level-time relayout of lumps into 65C02 layouts
  (PSRAM to PSRAM, 0.26 µs/B), zone and record-bank clears (FILL PSRAM,
  0.13 µs/B), and colormaps into the write-expensive pages.

### 5.3 With the zero-page bank pair

The corrected specification [R `zpbank-review.md:113-193`]: a write to
`$C069` names a pair of main zero-page bytes; a store of 1-126 into the
first byte sends data reads of `$0200-$BFFF` to that RamWorks bank, into
the second byte data writes; 0 (or 127-255) follows the switches. Code
fetches, zero page, stack, `$C000-$FFFF` and JMP-indirect pointers are
never redirected. Only main zero-page writes load the pair.

- **A far window is one store:** `lda #bank / sta zp_rd`, 3 cycles, no
  bus cycle, no TURBO invalidation, no drain wait.
- **Code keeps running from main,** so far loops need not live in the LC.
- **Separate read and write banks:** a copy between two RamWorks banks is
  a plain loop, though the single line of F1.2.1 thrashes when both are
  PSRAM [R `zpbank-spec.md:380`]; the design's 16 lines absorb it.
- **The catch:** every data read of `$0200-$BFFF` inside a window goes to
  the far bank, the colormaps included. Tables used inside a window belong
  in zero page, the stack page or the language card, or are duplicated in
  the far bank [R `zpbank-spec.md:395`]. Hence the replay bounces each
  record's texel span into the stack page (128 bytes, about 10 cycles a
  byte), then draws from there with `zp_rd` = 0.
- **Cost of an access:** the RamWorks path, 5 clocks on a line hit, about
  35 clocks on a miss with relaxed admission, about 131 on F1.2.1 [R
  `appletini.json:21-26`]. For scattered level and zone reads I used 0.08
  to 0.3 µs an access on the design [A].
- **Interrupts:** the port owns `$FFFE` in the language card; its handler
  saves both pair bytes, zeroes them, and restores them before RTI [R
  `zpbank-review.md:180-183`]. The //e ROM is never called with the pair
  set.
- **ALTZP:** writes to aux zero page do not load the pair, hence the
  trampoline of section 3.3. The owner's question 4 of the review (D4)
  decides this; the logical watch of the original D4 would remove the
  trampoline.

**The pair alone on F1.2.1** (no other design change) removes the switch
bus cycles and the drain waits of far windows, but not the drain floor of
the replay, nor the 131-clock line misses, nor the 1-line thrash. The
replay stays near its F1.2.1 figure; tics and render gain most of the
difference between the two columns of section 7 [A].

## 6. One far-access interface, two back ends

The port's code sees one interface; a build flag or a boot-time probe
picks the back end.

| Call | Meaning | F1.2.1 back end | Pair back end |
|---|---|---|---|
| `FAR_RD bank` | open a read window | `sta $C073` if changed (shadow in zero page, the register is write-only [R `appletini-hardware.md:106`]); `sta $C003` | `sta zp_rd` |
| `FAR_WR bank` | open a write window | `sta $C073` if changed; `sta $C005` | `sta zp_wr` |
| `FAR_END` | close | `sta $C002` / `sta $C004`; `$C073` left as is until needed | `stz zp_rd` / `stz zp_wr` |
| `FAR_GET dst, bank:src, n` | copy a record into zero page or main | LC routine: window, loop, close | loop with `zp_rd` set |
| `FAR_PUT bank:dst, src, n` | write a record back | LC routine with RAMWRT | loop with `zp_wr` set |
| `FAR_LOAD dst, bank:src, n` | bulk load | CPU copy from the LC, or memory API when the destination is write-expensive | same rule |
| `FAR_MOVE bank:dst, bank:src, n` | bank to bank | memory API COPY | memory API COPY (or a loop on the design) |
| `FAR_FILL bank:dst, n, v` | clear | memory API FILL | memory API FILL |

Rules the interface enforces (checked by a link-time or assembler check):

1. Inside a window only zero page, the stack page and the language card
   are near. All other `$0200-$BFFF` data goes to the far bank. This is
   the common subset of both back ends.
2. Code inside a read window lives in the language card or zero page.
   The pair does not need it, but the common contract does, so both builds
   run the same code.
3. No window opens while SHR bytes are pending, except where a drain wait
   is intended (F1.2.1).
4. Windows stay open across loops; callers sort work by bank.
5. The interrupt handler saves and closes the window state and restores
   it.

What differs between the builds is placement, not code: F1.2.1 keeps
records and the texel stage in main; the pair build may move records to
RamWorks and the stage to the stack page.

## 7. Time per phase

Method [A on top of M]:

- CPU: the transliterated 65C02 cycles of section 2.2 [M], times a
  hand-rewrite factor of 0.85 to 1.15 [A], times 1.9 to 2.6 fabric clocks
  a cycle [M model: 1.87 in the copy loop, 1.98 in the interpreter, 2.4
  in the row kernel], plus 100 to 150 cycles a multiply product [A].
- Far: section 5.1's counts times 0.55-1.35 µs (F1.2.1) or 0.08-0.30 µs
  (design + pair) [A].
- Replay: textured bytes at 0.564 µs, fill bytes at 0.157 µs [M model],
  750 records standing still and 486 in the demo (derived from upstream's
  replay cycles) at 150 to 200 cycles each [A], texel gather of 0.5 to 1
  byte per texel read at the copy rates of 1.2 [M model]. F1.2.1 adds the
  drain: low end max(draw, drain), high end draw plus drain.
- Loads: section 3.4.
- Music and effects: 1.2 to 2.8% of wall time for music on F1.2.1 with
  the 512-cycle slot-4 slowdown, plus up to 1% for effects [R
  `native-sound.md:23-26`]; I applied the same share to the design, which
  does not change slot 4.
- 4 tics a frame, as measured. Above 8.75 FPS the game runs fewer tics a
  frame, so the tic rows shrink.

### Standing still in E1M1 (ms a frame)

| Phase | 65816 cycles [R PROFILE] | F1.2.1 | Design + pair |
|---|---:|---:|---:|
| Tics | 51,624 | 3.0-6.7 | 1.4-3.2 |
| Tic window load | | 1.4-1.9 | 0 |
| Frame setup | 10,641 | 0.2-0.5 | 0.2-0.4 |
| Render window load | | 5.0-7.1 | 0 |
| BSP walk | 99,575 | 3.4-7.1 | 2.3-4.7 |
| Wall setup | 115,381 | 4.0-8.7 | 3.3-7.0 |
| Seg loops | 367,549 | 7.4-14.8 | 6.5-12.7 |
| Sprite projection | 17,880 | 0.9-2.0 | 0.6-1.4 |
| Masked drawing | 55,465 | 1.5-3.0 | 1.1-2.2 |
| Record replay | 389,768 | 9.2-16.9 | 6.2-8.4 |
| Status, menu, finish, other | 9,955 | 0-0.1 | 0-0.1 |
| Music, effects, IRQ | 2,790 | 0.4-2.7 | 0.3-1.6 |
| **Frame** | 1,123,634 | **37-72** | **22-42** |
| **Frames a second** | | **14-27** | **24-45** |

### Title demo, E1M3 (ms a frame)

| Phase | 65816 cycles [R PROFILE] | F1.2.1 | Design + pair |
|---|---:|---:|---:|
| Tics | 357,427 | 18.4-41.3 | 9.2-20.6 |
| Tic window load | | 6.0-9.5 | 1.9-2.8 |
| Frame setup | 11,472 | 0.2-0.5 | 0.2-0.4 |
| Render window load | | 6.0-8.5 | 0.8-0.9 |
| BSP walk | 23,056 | 0.8-1.6 | 0.5-1.1 |
| Wall setup | 21,364 | 0.7-1.5 | 0.6-1.3 |
| Seg loops | 143,498 | 3.1-6.2 | 2.6-5.2 |
| Sprite projection | 12,034 | 0.6-1.4 | 0.4-0.9 |
| Masked drawing | 51,410 | 1.3-2.7 | 1.0-1.9 |
| Record replay | 772,688 | 23.8-39.7 | 14.8-18.4 |
| Status, menu, finish, other | 22,073 | 0.2-0.5 | 0.2-0.5 |
| Music, effects, IRQ | 2,250 | 0.7-4.5 | 0.4-2.1 |
| **Frame** | 1,604,459 | **62-118** | **33-56** |
| **Frames a second** | | **8.5-16** | **18-31** |

What drives each column:

- **F1.2.1:** the drain (replay), the far switches of the tics (the zone:
  19,700 accesses in the demo), and 25 to 51 KB of code loaded every
  frame.
- **Design + pair:** CPU time. Standing still, the tics and the render
  front end (segs, walls, BSP) are 60 to 65% of the frame; in the demo
  the replay and the tics are 70 to 80%. The replay is CPU-bound at about
  0.56 µs a textured byte.
- Status bar redraws, the first frame of a level and menus cost more than
  these medians: upstream's status phase reaches 70,728 cycles standing
  still and 1.45 M in the demo's first frame [R `PROFILE.md:104`, `:148`],
  and on F1.2.1 each 2D SHR byte adds about 1 µs.

## 8. What a2vm must add for the zero-page pair

Read in `tools/a2vm/a2vm.c`, `a2vm.h`, `cost.c`, `cost.h`,
`cpu65c02.h`, `cpu65c02_core.h`, `costs/appletini.json`.

### 8.1 Function

| # | Change | Where |
|---|---|---|
| 1 | State: pair address (0 = off), `zp_rd` and `zp_wr` values (0 or 1-126), armed flag (kill switch, default off per review finding 3), counters. Save it in the state JSON and snapshots, so determinism checks and comparisons cover it. | `a2vm.h:132-202` (struct `a2vm`), `main.c` state writer |
| 2 | `--zpbank` option to arm it (like `--amem`). | `main.c:215-320` |
| 3 | `$C069` write: value 0 or `$FF` turns the pair off; otherwise address = value, write byte = value+1; both registers cleared. It stays a normal I/O write (no private serve). Reads of `$C069` unchanged. | `a2vm.c:747-776` (`io_write`) |
| 4 | Watch: a CPU write to `$0000-$00FF` with ALTZP off, while the pair is on, loads the register whose byte it hits; value 1-126 sets it, anything else means follow. Pokes and the memory API never load it (the API cannot reach zero page). | `a2vm.c:872-894` (`bus_write`) |
| 5 | Redirect: a read or write of kind DATA to `$0200-$BFFF`, with the register of its direction nonzero, goes to `aux_banks + value × 64 KB + address` (a2vm's aux bank n is `$C073` = n, physical n+1). It beats RAMRD, RAMWRT, 80STORE and PAGE2. Redirected writes set no video flag. The fast `rpage`/`wpage` path must be bypassed for DATA cycles while either register is nonzero. | `a2vm.c:849-894` (`bus_read`, `bus_write`), `a2vm.c:603-637` (`a2vm_remap` untouched) |
| 6 | A cycle kind for JMP `(a)` and `(a,X)` pointer reads, which the spec classes as code space (D1). a2vm tags them DATA today. Add a kind (for example `CPU65C02_POINTER`) and charge it like DATA in the cost model. Stack, zero-page pointer and vector reads are DATA but outside `$0200-$BFFF`, so the address test already excludes them. | `cpu65c02.h:55-57`, `cpu65c02_core.h:615-633`, `cost.c:731-745` |
| 7 | The same-page `STA abs,X` false read is DUMMY in a2vm and must stay unredirected (review finding 8); nothing to do but a test. | `cpu65c02_core.h:100-110` |
| 8 | The compatibility core (`py65core.h`) has no cycle kinds: arm the pair only with `--core w65c02s`, and fail clearly otherwise. | `a2vm.c:908-915` |
| 9 | Diagnostics: count redirected accesses made while the PC is in ROM or the `$C1xx-$CFxx` firmware (a contract breach: firmware called with the pair set), and SmartPort calls with the pair set (the ROM writes `$07F8` [R `README_MEMORY_API.md` section 1]). | `a2vm.c` bus hooks |
| 10 | Bus-script verbs to print and set the pair, for tests. | `main.c:823-945` |

### 8.2 Cost

| # | Change | Where |
|---|---|---|
| 1 | Pass the redirected page to the cost hooks; `where()` then classes it RamWorks and `ramworks()` charges 5 clocks on a line hit and a PSRAM operation on a miss, the path of the spec (CAPTURE, TURBO_DONE, ROUTE, RW_LOOKUP, RW_DONE) [R `zpbank-spec.md:315`]. | `a2vm.c:851-852`, `879-880`; `cost.c:363-390`, `493-535` |
| 2 | The pair must not invalidate the TURBO caches: keep it out of `mapping_of()`. Redirected accesses never fill the caches, which `ramworks()` already guarantees. | `cost.c:346-355` |
| 3 | The `$C069` write is a real bus cycle, not the private serve that `read_bank` models; add a `zp_pair` parameter and set `read_bank` 0 in the pair profiles. | `cost.c:651-718`, `cost.h:49-83`, `cost.c:28-45` |
| 4 | Two profiles: `f121zp` (F1.2.1 plus the pair) and `fastzp` (the design with the pair in place of the read bank), each value citing `zpbank-spec.md` and `zpbank-review.md`. | `costs/appletini.json` |
| 5 | Counters: redirected reads and writes, pair loads, `$C069` writes, in the per-frame JSON. | `cost.h:85-100`, `cost.c:951-966` |
| 6 | The slot-4 slowdown of the virtual Phasor (1 MHz for 512 Apple cycles after each `$C4xx` access, a parameter), which the music will hit every tic [R `native-sound.md:23-33`; `a2vm/README.md:594-596` says it is not modelled]. Not pair-specific, but the far and music estimates depend on it. | `cost.c` `io_access` |

### 8.3 Tests

- The detection probe of the spec [R `zpbank-spec.md:350-363`] as a bus
  script: present when armed, absent when not.
- Read-modify-write with `zp_rd ≠ zp_wr`; `JMP ($4000)` with the pair set
  reads main; `$FF` disables; 127-255 follow; a write to aux zero page
  (ALTZP on) does not load; a nonzero value beats 80STORE and PAGE2;
  redirected writes to `$2000` under RAMWRT are not posted.
- Cost: a redirected read on a line hit costs 5 clocks; no invalidation
  is counted; the `$C069` write is one bus cycle; F1.2.1's single line
  thrashes on a two-bank copy and `fastzp`'s 16 lines do not.
- With the pair off, every existing test and the a2sim comparison stay
  byte-for-byte identical.

## 9. Open points

1. **Fit.** Section 3.4's budget is 90-130 KB against 95 KB. The first
   concrete step is a byte-level allocation of main and aux 0 from the
   hot sets and tables, before any code is written.
2. **The drain.** On F1.2.1 the replay cannot beat 0.985 µs a screen byte.
   Standing still, 152 of 8,519 bytes change [R `PROFILE.md:699`]; a
   compare-before-store needs RAMRD toggles (screen reads) and is only
   worth it if the lazy mirror is not built.
3. **D4 and the trampoline.** Whether the pair may be loaded from aux zero
   page decides where tic code lives on the pair variant.
4. **Milestone 0.** Every time here rests on model parameters: `axi_us`,
   the admission window, the switch cycle. The memory-API figures move 1.8
   times between `axi_us` 0.14 and 0.305; the CPU-copy figures do not.
5. **Tics per frame.** At the frame rates above 8.75 FPS, the game runs
   fewer tics a frame; a fight then costs less per frame than the demo
   rows show, but the tic window still loads every frame on F1.2.1.

## Appendix: how the numbers were made

Scripts in the session scratchpad (not in the repository):
`bench.py` (memory API, CPU copies, switches, SHR bursts as a2vm bus
scripts under the four cost files: `f121` and `fastpath` at `axi_us` 0.14
and 0.305), `replay_bench.py` (a native texture and fill kernel, 168 rows
by 160 columns, driver in the LC, texels and colormaps in main, stores to
SHR through RAMWRT), `xlate.py` (the transliteration over the traces'
`op` and `heat` records and the release image), `banks.py` (per-phase far
accesses by bank group from the traces' `access` records) and
`estimate.py` (section 7). The kernel follows upstream's row-block
technique and is kept out of the repository.
