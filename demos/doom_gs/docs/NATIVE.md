# Native 65C02 rewrite: architecture

Status: proposal for the owner's review, 2026-09-30. Nothing here is built.
It answers the owner's direction of 2026-09-30: "fully rewrite and optimize
the 65816 code into 65c02 code", music "directly to the phasor", "don't use
the ensonic as a base".

**What it replaces.** This file replaces the end state of
[`ARCHITECTURE.md`](ARCHITECTURE.md) (a virtual 65816 machine).

| From ARCHITECTURE.md | Kept or dropped |
| --- | --- |
| §0 facts settled from the source | Kept |
| §7 verification discipline: a deterministic reference, lockstep comparison, coverage scripts, the kernel checks (records, then SHR bytes) | Kept, extended by a state bridge (§11) |
| §4 renderer techniques: records in `lists.inc` kinds, fill spans, covered ranges, weapon skip, two colormaps, row blocks with computed entry and patched exit, even/odd row pairing | Kept (§5) |
| §3.1 principles: code runs only from fast memory; the write-expensive pages hold immutable data; the IRQ handler touches only the language card and its own cells | Kept (§4) |
| §5 platform: ProDOS `DOOM.SYSTEM`, `input.s`, the VBL clock, the IRQ in the language card, saves through the slot-7 driver with `$42-$47` and `$07F8` kept clear, reuse of `amem.s` and `profile.s` | Kept, ProDOS at boot only (§10) |
| D9 code only from BRAM, D10 immutable phase windows by the memory API, D11 exact multiply without the 512 KB tables | Kept |
| Virtual 24-bit space, translator tiers, interpreter as tier 0, soft stack, original code addresses, entry table, patch catalogue and write-watch, the F2 line cache, granule mapping | Dropped |
| Replay in four passes R, G, S, F; records always in RamWorks (D12) | Replaced (§5) |
| §6 estimate (2.4 FPS), §8 and §12 milestones, sound stage 3 (upstream's DOC song units) | Replaced (§1, §13, §9) |

**Labels.** Every number carries one.

- **[M: source]** measured by running something. The source is a report
  of this design run, all in `docs/research/`: `modules`
  (`native-modules.md`), `verification` (`native-verification.md`),
  `memory` (`native-memory.md`), `experiment` (`native-experiment.md`),
  `sound` (`native-sound.md`); or `PROFILE`, `MILESTONES`.
  "Model" means a2vm's cost model, derived from the RTL, not yet checked on
  the card except by one frame of the existing port.
- **[R file:line]** read there. Upstream files are in `build/upstream/src/iigs/`.
- **[A]** assumed, or arithmetic on labelled numbers.

"Design" means the firmware design of `docs/firmware/` (lazy SHR mirror,
relaxed PSRAM admission, 16-line RamWorks cache, quiet switches) with the
zero-page bank pair of `zpbank-spec.md` as corrected by `zpbank-review.md`.
It is a2vm profile `fastpath` with the pair [M: memory §0].

**Title demo.** It plays DEMO3 in **E1M7**, not E1M3 [M: verification §0:
demo header `6d 02 01 07`, 170 sectors, 958 lines]. `PROFILE.md`,
`MILESTONES.md` and the ref816 scripts said E1M3; they were corrected on
2026-09-30. Their figures were right; only the map name was wrong.

## 1. Summary

The port rewrites all 60 game modules as 65C02 code. It keeps upstream's SHR
renderer design, its game behaviour bit for bit, and its data flow. It drops
the DOC sound. It runs on F1.2.1 and uses the zero-page pair when present,
through one far-access interface with two back ends (§4.5).

### 1.1 Expected frame rate

| Scene | Firmware | 4 tics a frame | Tics a frame = 35 / FPS, 1 to 4 |
| --- | --- | ---: | ---: |
| Standing still, E1M1 | F1.2.1 | 36-75 ms, 13-28 FPS | 34-72 ms, 14-29 FPS |
| Standing still, E1M1 | Design + pair | 21-41 ms, 24-47 FPS | 25-35 FPS (35 is the cap) |
| Title demo, E1M7 | F1.2.1 | 61-127 ms, 7.9-16 FPS | 52-127 ms, 7.9-19 FPS |
| Title demo, E1M7 | Design + pair | 34-57 ms, 18-29 FPS | 22-35 FPS |

- The "4 tics" column is `memory` §7 [A on top of M], revised after review
  [A]: far accesses at 0.4-1.6 µs (§1.2); on F1.2.1 the records copied
  into W before the replay, +1-2 ms still and +2-3 ms demo (§4.2); 485-530
  products, not 1,000-1,300, −0.6 to −1.3 ms still; on the design the
  aux-card duplicates, +0.9-1.1 ms demo (§4.3). Four tics a frame is what
  the reference ran [M: PROFILE §1].
- At its slow end the F1.2.1 demo drops below 8.75 FPS, so game time slows.
- The last column is my arithmetic [A]. The game runs 35 tics a second
  [R `tics.inc:14-21`; the clock rate is §10's], so a
  frame at F FPS runs 35 / F tics, at least 1 and at most 4. I scaled each
  estimate's tic rows linearly and solved for the frame time.
- **35 FPS is a hard cap.** With no new tic the main loop waits for one
  [R `d_main65.s:260-296`].
- **Below 8.75 FPS game time slows** (the 4-tic cap) [R `tics.inc:14-21`].
- For scale: the IIgs release does 2.5 FPS still and 1.6 in the demo at
  2.86 MHz [M: MILESTONES]. The existing cc65 port does 4.03 FPS on the card
  [M: MILESTONES].

### 1.2 What the numbers rest on

| Input | Value | Label |
| --- | --- | --- |
| 65816 cycles a frame, by phase | 1,123,634 still; 1,604,459 demo | M: PROFILE §1 |
| 65C02 cycles for the same work, transliterated per executed instruction | 1.37 times still, 1.32 demo | M: memory §2.2 (per-case cycle table A) |
| Hand-rewrite factor on that | 0.85 to 1.15 | A |
| Three routines written natively | 0.95 (8-bit seg loop), 1.19 to 1.3 (16/32-bit logic), 2.1 to 2.5 (16 × 16 multiply) times upstream's cycles | M: experiment |
| Fabric clocks per 65C02 cycle in fast memory | 1.9 to 2.6 | M: model |
| Native textured pixel byte | 0.564 µs; fill byte 0.157 µs | M: model, memory §1.2 |
| SHR drain on F1.2.1 | 0.985 µs a byte; 8,519 bytes still, 21,881 demo | M: model; PROFILE §7 |
| Far accesses left after the layout of §4 | about 10,700 still, 22,500 demo, plus replay texels | M: memory §5.1 |
| Cost of a far access, F1.2.1 | 0.4-1.6 µs (8 to 3 reads a window); a window 3.0-4.7 µs; a `$C073` write 122-253 clocks by phase | M: a2vm, review `far.py`; R `tools/a2vm/README.md:590-591` |
| Cost of a far access, design | 0.06-0.30 µs | M: review `far.py`; A |
| Reads a window | 3-8 assumed; upstream averages about 5 a bank change | A; M: PROFILE P6/P6' |
| 16 × 16 products | 485-530 a frame | M: experiment (8 byte reads a product [R `r_wall65.s:1732-1776`]) |
| Code loaded each frame | 6.4-9.0 ms still, 12-18 ms demo on F1.2.1; 0-4.6 ms design | M rates, A volumes: memory §3.4, §4.3 |
| Music and effects | 1.2% to 2.8% of wall time on F1.2.1, up to 3.4% with 3 effects | A on M counts: sound §4 (a2vm does not model the slot-4 slowdown [R `tools/a2vm/README.md:594-596`]) |

The experiment's whole-frame factor, 1.1 to 1.2 [A: experiment], sits at the
low end of the transliteration range (1.16 to 1.58). The ranges do **not**
cover two risks: the fast-memory plan failing to fit (§4.2), and the card
departing from the model (milestone 0 not run).

### 1.3 What bounds each variant

| Variant | Bound |
| --- | --- |
| F1.2.1 | The drain in the replay (8,519 B and 21,881 B at 0.985 µs: 8.4 ms still, 21.5 ms demo, a floor). Far switches in the tics (19,700 zone accesses a frame in the demo). 25 to 51 KB of code loaded each frame. Fast memory is main only (§4.2). [M: memory §7; A] |
| Design + pair | CPU time. Still: tics plus segs, walls and BSP are 60-65% of the frame. Demo: replay plus tics are 70-80%. [A: memory §7] |
| F1.2.1 + pair only | Not estimated. The replay stays near its F1.2.1 time; tics and render gain most of the difference [A: memory §5.3]. |

## 2. Subsystems and rewrite strategy

Per-module shares are of all cycles, mean over the frames [M: modules §2].

| Subsystem | Modules | Code bytes | Share still / demo | Strategy | Contract |
| --- | --- | ---: | ---: | --- | --- |
| Record replay | `r_list65`, `drawcol` | 32,444 | 33.8% / 42.1% | Hand-written kernel; own row-block generator | SHR bytes from the same records |
| Seg loops, planes | `r_seg65` | 12,804 | 34.7% / 14.8% | Redesign; variants generated by our own script | Records per column, clip arrays, fill spans, covered ranges |
| Front end | `r_bsp65`, `r_wall65`, `r_iigs65`, `r_frame65`, `r_state65` | 13,419 | 20.3% / 9.6% | Redesign, 65C02 layouts | Same records; drawsegs |
| Sprites, masked | `r_thing65`, `r_sprite65` | 8,050 | 2.6% / 4.1% | Redesign | Records, covered ranges, weapon skip |
| Game logic | 21 `p_*`, `g_game65`, `d_main65`, `m_cheat65`, `info65` | 52,484 | 4.0% / 20.1% | Close transliteration, bit-exact; layouts may change | Game state after every tic |
| Math and tables | `m_fixed65`, `m_recip65`, `tables65`, `m_random65`, `string65` | 2,215 | 1.0% / 2.3% | Redesign, outputs bit-exact | Whole-domain or random tests |
| Level loading | `w_level65`, `w_wad65`, `z_zone65`, `p_setup65`, `r_data65` | 12,854 | 0.1% / 0.0% | Redesign: host converter plus loader | Canonical level after `P_SetupLevel` |
| 2D | `i_viigs65`, `patch65`, `st_stuff65`, `hu_stuff65`, `m_menu65`, `am_map65`, `wi_stuff65`, `f_finale65` | 23,216 | 0.7% / 3.6% | Transliteration; the shown screen written by CPU stores only (§8) | Screen bytes |
| Sound | `s_sound65`, `i_snd65`, `i_doc65` (+ music in `irq65`) | 8,081 | 2.5% / 2.5% | Channel logic kept; DOC code dropped; new Phasor player | AY register stream; `S_StartSound` events |
| Platform | `crt0`, `i_iigs65`, `iigs_asm`, `irq65`, `m_config65` | 4,550 | 0.3% / 0.9% | New code for the //e | Scripts, clock rate |

- **Size.** 170,117 code bytes, plus 447 of vendor runtime [M: modules §0].
  The four coverage scripts run 58% of it [M: modules §0].
- **16-bit work.** 58-80% of instructions in the front end and game logic,
  0-16% in the replay [M: modules §0]. That is where code grows.
- **Vendor divides.** 46 call sites, 5 callees, 4.2 calls a frame still and
  9.4 in the demo [M: modules §4.2]. Our replacements are written from the
  call sites and C semantics only (ground rules).
- **Self-modification** stays where it is cheap: per record and per seg, in
  fast memory [M: modules §4.1]. Patched code never lives in RamWorks.

## 3. Numbers and arithmetic

### 3.1 Representations

| Quantity | Upstream | Native |
| --- | --- | --- |
| Fixed point | 16.16 in 4 bytes | Same, 4 bytes little-endian |
| Pointers | 24 bits plus a pad byte | A handle (kind, index) or bank + 16-bit offset [M: verification §3.2, round trip lossless] |
| Per-column arrays | Words indexed by X = 2 × column | Split low/high byte arrays, X = column 0-159 |
| Mobjs | 120-byte records | Hot fields as byte planes in fast memory where they fit, the rest in RamWorks [A] |
| Multiply | 512 KB of 16-bit quarter squares (banks `$13-$1A`) | 8 × 8 quarter squares, 2 KB in fast memory: 208-212 cycles a 16 × 16 product against 86-98 [M: experiment] |
| Sine, cosine | Two full 8,192-entry tables | Sine: 16-bit magnitude (max 65,535) as two 8 KB byte planes, sign = bit 12 of x. Cosine: the sine at x + 2048, sign = bit 12 of x + 2048, plus a 12-entry exception list. 16 KB in all [M: review, on the table of `gensine.py`: the sign rules hold on all 8,192 entries; cosine and shifted sine differ on 12] |

A native product costs about 3.7-3.8 µs [M: experiment]. A RamWorks table
read costs 131 clocks today and about 35 with the design, so tables do not
beat it [R: experiment].

### 3.2 Bit-exact for demo sync

Demo sync needs the game logic exact [R verification §8.1], plus two side
effects of the renderer: it adds 1 to `validcount` once a frame
[R `r_frame65.s:285`] and stamps `sector.validcount` [R `r_bsp65.s:731-736`],
which the sound flood reads [R `p_pspr65.s:453-454`, `:488-489`]. The native
renderer does both exactly as upstream.

| Item | Rule | Where |
| --- | --- | --- |
| `P_Random` | 256-byte table, byte index; call order is state. Called only from `p_*.s`. | `m_random65.s:9-46` |
| `FixedMul` | Exact floor(a·b / 65536) mod 2^32; any exact method | `m_fixed65.s:425-437` |
| `FixedMul3216`, `FixedMulAngle` | Defined on the low word of b; reproduce the truncation | `m_fixed65.s:517-518`, `p_mobj65.s:1205-1213` |
| `FixedDiv` of the path traverse | C's `FixedDiv` with its guards | `p_trace65.s:237`, `:398-404` |
| `FixedApproxDiv` and the reciprocals | 16 significant bits through `RECIP_TABLE` (32,768 words); keep the table | `r_iigs65.s:546-560`, `m_recip65.s:270-312` |
| `P_AproxDistance` | dx + dy − min/2 with its rounding | `p_path65.s:105-113` |
| `R_PointToAngle3` | `SlopeDiv` and `tantoangleTable` | `r_iigs65.s:914-925` |
| `finesine`, `finecosine` | Doom8088's values; test all 16,384 entries | `tables65.s:1-23` |
| Sight side tests | Whole parts of coordinates; the log fast path | `p_sight65.s:1-6`, `:699-700` |
| Integer divide and modulo | Truncation toward zero; remainder takes the dividend's sign [A: C]. Divide by zero: owner question 5. | 18 call sites in game code, plus `_UDivMod32` in `R_PointToAngle3` (`r_iigs65.s:1134`), called from 6 `p_*` modules |
| Orders and policies | Thinker order, sector thing lists, block chains, pool slot policy (highest free index), `validcount` counting (game and renderer) | `p_spawn65.s:275-297` |
| Departures from Doom8088's C | Upstream is the truth, not the C. Kept as an inventory, each with a routine test. First entry: `P_PathTraverse` runs its early traversal with the guard off (decision 34), so `trav` sees the near intercepts even past `MAXINTERCEPTS` (64); the C calls it for none | `p_path65.s:178-183`, `:615` |

All rows are [R verification §8.1, or the file] at the places given.

### 3.3 Exact only for frame equality

`qmulh` (high word "+0 or 1" [R `r_wall65.s:1781-1786`]), `scaleFast`
through `RECIP_TABLE`, `FSTEP` (128 KB), the log BSP side tests, the vertex
angle cache, the sprite scale tables (32 KB), `finesineapprox`, the light
tables, edge stepping that "can be off by one after many columns" [R
`r_seg65.s:171-174`], and `M_Random` for the face [R verification §8.2].

Default: reproduce all of them, so frames compare with no tolerance. A
faster method needs a written waiver after the exact version passes (owner
question 3).

## 4. Memory and code map

### 4.1 Fast memory

| Region | Size | Content | Loaded |
| --- | ---: | --- | --- |
| Main `$0000-$01FF` | 0.5 KB | Zero page of the running phase; pair bytes `$06/$07` [R `zpbank-review.md:180`]; the stack. Pair build only: a 128-byte texel bounce buffer at `$0100-$017F`, live during the replay only | |
| Main `$0200-$03FF` | 0.5 KB | Globals | once |
| Main `$0400-$0BFF` (write-expensive) | 2 KB | Colormap light levels 32-33; `xtoviewangle`. Not the screen holes (`$07F8`, slot holes: written by slot-ROM and SmartPort calls) nor `$0878-$087F` (firmware metadata [R `vtw_video_policy.sv:33-36`]), or reload after any firmware call | per level, memory API PRIVATE |
| Main `$0C00-$1FFF` | 5 KB | Clip arrays, `COLW`, fill spans, covered ranges, weapon skip (about 3.5 KB [A]); hot game globals | scratch |
| Main `$2000-$5FFF` (write-expensive) | 16 KB | Colormaps A/B, light levels 0-31 | per level, memory API PRIVATE (6 ms) |
| Main `$6000-$BFFF` | 24 KB | Window W: code of the running phase | per phase |
| Main language card | 12 KB + 4 KB behind `$C08x` | IRQ, Phasor player (its code in the platform's 6 KB) and its 4.2 KB of data [R sound §4.3], input, far layer, phase loader and memory-API transport, multiply and divide with square tables, row blocks and record dispatcher. **Oversubscribed:** about 19.7 KB wanted. The second `$D000` bank holds only code that never runs in the replay or inside a window | once, CPU copy (the memory API cannot write the card) |
| Aux 0 `$0200-$1FFF`, `$A000-$BFFF` | 15.5 KB | Drawsegs, vissprites, openings; on F1.2.1 part of the records | scratch |
| Aux 0 `$2000-$9FFF` | 32 KB | The SHR screen | |
| Aux language card | 16 KB | Design + pair: the tic window. F1.2.1: read-only tables only | per level |

All rows [R memory §3.2], LC sizes [A: platform 6, math 4, row blocks
5.5, player data 4.2 KB]. A store to the write-expensive pages leaves a
mirror byte; only memory-API PRIVATE writes fill them cheaply [R memory
§1.1]. PRIVATE writes are never shown, so they never target the displayed
SHR screen [R `README_MEMORY_API.md:173-189`]. The aux card cannot hold tic
code on F1.2.1: `$C073` cannot move while ALTZP is on [R memory §3.3].

### 4.2 Fit: the first thing to settle

The render phases want 90 to 130 KB of fast memory: code 26-40 KB,
colormaps 17 KB, trig tables 20 KB, per-frame arrays 15-30 KB, game globals
8-16 KB [A: memory §3.4]. Also unplaced: the F1.2.1 records (5,969 B still,
10,524 B demo [M: verification §2.2]), the texel stage (3-6 KB still,
10-20 KB demo), the game's sine (16 KB, §3.1), the player's data.

| Variant | Hot memory the render phases can use | Consequence |
| --- | --- | --- |
| F1.2.1 | Main only: writable `$0200-$03FF`, `$0C00-$1FFF`, W and 12 KB of card, 41.5 KB; plus 18 KB write-expensive for read-only tables [R `vtw_video_policy.sv:43-48`]. Aux 0 and the aux card need a switch, and every switch waits for the drain. | A workable scheme [A]: the seg phase writes records to aux 0 through a zero-page batch buffer; before the replay the records are copied into W (its render code is dead by then) and the texel gather writes into W. Trig tables in aux 0 behind batched windows, or in RamWorks. About 1-2 ms still, 2-3 ms demo (6-10.5 KB at 0.19-0.25 µs/B, plus windows). |
| Design + pair | Main plus aux 0 by the pair, about 95 KB; records in RamWorks | Levers: 16-bit trig entries (about 10 KB), per-frame arrays in aux 0, paging the coldest 9% of render code. |

Milestone 5 starts with a byte-level allocation for each variant, the
language card byte by byte.

### 4.3 Code

| Subsystem | Native code, all | Native hot set (99% of instructions) |
| --- | ---: | ---: |
| Replay and drawers, full view | 7-9 KB | 6-8 KB |
| Render front end, segs, sprites, math | 50-72 KB | 19-26 KB |
| Game logic | 68-101 KB | 5.7-28 KB |
| Level load and zone | 17-26 KB | 0 |
| 2D, UI, video | 33-49 KB | 2-3.5 KB |
| Phasor player and effects | 3-5 KB | 1-2 KB |
| Platform | 4-6 KB | 2-3 KB |
| **All** | **180-270 KB** | **23-35 KB** |

[A: memory §2.1, from the measured 1.35-1.96 expansion.] The whole library
lives in RamWorks. Phase windows are loaded, never saved back.

| Phase | F1.2.1 | Design + pair |
| --- | --- | --- |
| Tics | Hot set into W: 5.5 KB still, 24-27 KB in a fight; the rest paged | Resident in the aux card with ALTZP on; pair writes through a 20-byte trampoline (aux zero-page writes do not load the pair). With ALTZP on the main card is unreachable, so the aux card duplicates vectors, an IRQ bridge, math and the trampoline, about 4-5 KB [A; R `kstart.s:23-24`]. Overflow 13-16 KB paged by CPU copy, 3.0-3.7 ms in the demo |
| Render | Hot set into W: 20 KB still, 24 KB demo | Resident in W; 3.4 KB overflow in the demo |
| Replay | Resident in the main card | Same |
| 2D, menus, level load | Loaded into W when the mode starts | Same |

[R memory §3.3-3.4.] Code loads use CPU copies (0.246 µs/B), which do not
depend on the ARM's `axi_us`; the memory API would take 15.7 ms still at
`axi_us` 0.305 [M: memory §3.4].

### 4.4 RamWorks allocation

| Use | Banks | Label |
| --- | ---: | --- |
| Code library | 3-5 | A: memory §3.2 |
| Level window, current map | 22-24 (E1M3 about 23.0) | R: memory §3.2; A: verification §2.3 |
| Level store, all maps | about 28 (upstream's is 1,821,696 bytes) | R: ARCHITECTURE §0; native format open (§7) |
| Zone (mobjs, sectors, lines, sides) | 4 (upstream heap 262,096 bytes) | R: modules §3.7 |
| Big tables: `FSTEP` 128 KB, `RECIP_TABLE` 64 KB, `LOGTAB` 64 KB, sine 64 KB, sprite scales 32 KB, tangent | about 6 | R: memory §4 |
| Per-map sight and move tables (upstream `$21`, `$0A-$0C`) | 3-4 | A |
| WAD directory and resident lumps (upstream `$10-$12`) | 3 | A |
| Records (pair build only) | 1 | R: memory §4 |
| Songs and effect scripts | 5 (about 283 KB) | R: sound §4.3 |
| 2D caches (view save, status cache, busy sign, text) | 1-2 | A |
| **Total** | **about 76-82 of 126** | A |

Bank 127 is excluded by the memory API and the pair [R memory §1.1].

### 4.5 Far access: one interface, two back ends

| Call | F1.2.1 back end | Pair back end |
| --- | --- | --- |
| `FAR_RD bank` | `sta $C073` if changed (shadowed in zero page), RAMRD on | `sta zp_rd` |
| `FAR_WR bank` | `sta $C073` if changed, RAMWRT on | `sta zp_wr` |
| `FAR_END` | RAMRD/RAMWRT off | `stz zp_rd` / `stz zp_wr` |
| `FAR_GET`, `FAR_PUT` | Language-card routine: window, loop, close | Loop with the pair set |
| `FAR_LOAD` | CPU copy from the card; memory API into write-expensive pages | Same |
| `FAR_MOVE`, `FAR_FILL` | Memory API COPY, FILL; never to the shown screen; each request under one VBL period (16.7 ms: about 45 KB PSRAM to main at 0.343 µs/B), because the CPU stops and VBL interrupts merge [R `README_MEMORY_API.md:233-235`] | Same |

[R memory §6.] Rules, checked at build time:

1. Inside a window only zero page, the stack page and the language card are
   near. This is the common subset of both back ends.
2. Code inside a read window lives in the language card or zero page.
3. On F1.2.1, no window opens while SHR bytes drain, unless a wait is meant.
4. Windows stay open across loops; callers sort work by bank.
5. The IRQ handler touches only zero page, the stack, the card and I/O,
   so it needs no switch whatever RAMRD, RAMWRT, `$C073` and the pair say
   (as the existing port [R `kstart.s:20-22`]). Its data lives in the card
   or zero page.

The builds differ in placement, not code (§4.2).

Cost on F1.2.1: 127-131 clocks a soft-switch write back to back, 122-253 at
a random phase [R `tools/a2vm/README.md:590-591`]; a window 3.0-4.7 µs, with
work between windows [M: review `far.py`]. On the design 3 clocks [M: model,
memory §1.2]. A pair window is one 3-cycle store [R memory §5.3]. The 3-8
reads a window are not measured; rules 1-2 force extra closes.

## 5. Renderer

### 5.1 Upstream techniques kept

| Technique | Upstream | Native |
| --- | --- | --- |
| Per-column records `K_TEX`, `K_TEXC`, `K_FILL`, `K_FUZZ`, `K_OVL`, `K_NEXT` | Bank `$1D`, 160 home pages + 50 extra, at most 53,760 B | Milestone 5 tests upstream's format on `ref816` dumps, then settles the shipping layout. F1.2.1: an 8-9 KB buffer (aux 0, copied into W, §4.2), flushed early when full, as upstream's `flush` [R `r_list65.s:272-323`]; so the port draws in batches where upstream draws once, and tests compare the record stream (§11). Pair: a RamWorks bank. |
| Record replay through row blocks | `drawcol.s` from upstream's `gendraw.py`, 15-19 bytes a row | Our own generator (not `gendraw.py`, GPL); 36 bytes a row pair against 34 [M: memory §2.2] |
| Row-block exit patched per record | `pairReady`/`fillEndW`, 394 + 327 patches a frame still [R PROFILE §5] | Same, one `sta abs` a record, in the main card |
| Dithered colormaps A/B | 2 × 8,704 B, bank `$0D` | Main, loaded per level (§4.1) |
| Planes as column fills, fill spans and stamps | `FS_*` at `$23:EF00` | Main `$0C00-$1FFF`; same "previous frame" state |
| Covered ranges, weapon skip | `CV_*`, `WCLIP` | Same |
| Weapon profiles | Arenas in bank `$0A` | 65C02 layout [A] |
| Views and detail levels | About 16 KB of variant drawers | Full view first; others loaded on a view change [R memory §2.1] |

### 5.2 What changes for the 65C02

- **Index width.** X = column as a byte, split arrays, `abs,X`. The
  experiment's seg loop saved about 11 cycles a column this way [M:
  experiment].
- **Pointers.** Bank + 16-bit offset. Level geometry is read through
  `FAR_GET` into zero page (nodes, segs, sectors), sorted by bank [A].
- **Multiply.** About 485-530 products a frame [M: experiment]. At about
  3.8 µs each, 1.9 ms a frame [A].
- **Seg loops.** 13 variants generated by a host script. The per-seg patches
  (`c17`, `c26`) stay self-modifying [R modules §3.2].
- **Replay on F1.2.1: gather, then draw.** Open one window per texel bank,
  copy every span the frame needs into a stage in W, then draw with RAMWRT
  on. The drain overlaps the drawing. A full stage draws a strip first
  [R memory §5.2].
- **Replay with the pair: bounce.** Per record, copy the texel span (128
  bytes, about 10 cycles a byte) into the stack page with `zp_rd` set, then
  draw with `zp_rd` = 0 so the colormaps read from main [R memory §5.3].
- **`$Cxxx` during the replay: the VBL interrupt only.** It must read
  `$C0A0` and write `$C0AF` [R `demos/doom/src/kernel/kstart.s:271-276`], so
  it waits for the drain; pending bytes grow about 0.43 a µs while drawing
  (1/0.564 − 1/0.985) [A], so the wait can reach several ms in heavy frames.
  Sound writes and input polls go after the drain [R sound §2.3].
- **Fuzz** reads the screen: aux reads with RAMRD, from language-card code [A].

## 6. Game logic

**Rule: same state after every tic.** Layouts may change; arithmetic,
truncations, approximations and call orders may not [R modules §3.6].

| 65816 idiom | Native form |
| --- | --- |
| 24-bit far pointers, `[dp],y` (1,729 operand lines [R iigs-platform §6]) | Handles or bank + offset; `FAR_GET` a record into zero page, work, `FAR_PUT` |
| Stack-relative arguments (62 `,s` in `p_map65.s` [M: modules]) | A zero-page argument block per call class [A] |
| DBR as the thinker base (`p_tick65.s`) | A zero-page pointer to the current mobj |
| `JML [dp]` (8 sites) | `jmp (abs,x)` through a table by function id |
| D as a data register (`p_trace65.s`, 7 `tcd`) | Zero-page variables |
| Four return-frame edits [R ARCHITECTURE §0] | Explicit status returns |
| Recursion: `bspNode` (4 B a level, depth 14-19 on E1 [M: review]) | The 65C02 stack, about 80 B |
| Recursion: `recursiveSound` (10 B a level [R `p_pspr65.s:473-500`]; flood depth up to 96, E1M3 [M: review, all two-sided lines open]) | Iterative, with an explicit work stack in RAM, visiting in upstream's order (so even the `P_LineOpening` globals match). About 670 B on the 65C02 stack would not fit in 128-256 B |
| Mobj pool: highest free slot | Same policy, so slots match the reference [R verification §4.2] |

Stack: a static budget from the call graph, the IRQ frame included, is
checked at build time (upstream's tic stack reached 228 B in the demo [R
`PROFILE.md:680`]).

- **Cost.** Standing still 51,624 65816 cycles a frame; demo 357,427 [M:
  PROFILE]. Native: 3.0-6.7 ms still and 18.4-41.3 ms demo on F1.2.1;
  1.4-3.2 and 9.2-20.6 on the design, at 4 tics [A: memory §7].
- **Hot spots in a fight.** `p_sight65` 138k cycles a frame, `p_tick65` 83k,
  `p_map65` 60k, `p_enemy65` 27k [M: modules §3.6]. Sight needs `LOGTAB` and
  per-map tables in RamWorks.
- **Rare paths.** Lifts, teleporters, the finale and saves barely run in the
  coverage scripts [M: modules §6]. Milestone 10 adds scripts or snapshots.
- **Order.** Thinkers and tables; player and game flow; movement and
  collision; sight and monsters; specials [R modules §5].

## 7. Level loading and the WAD

- **Host converter, our own code.** `DOOM1.WAD` to 65C02 layouts: geometry,
  blockmap, reject, texture column tables with their 128-byte over-read margin
  [R modules §3.7], sprite frames, flat colours, colormaps, sight tables.
  Upstream's `wadtool.py`, `levelimg.py`, `levelset.py` and `b1.py` are GPL
  and not used.
- **Loader.** Places units in the level window with memory API COPY and
  FILL. PSRAM to PSRAM costs 0.258 µs/B on F1.2.1 and 0.065 on the design;
  FILL PSRAM 0.129 and 0.029 [M: model, memory §1.2].
- **Upstream's cost** per map change, intermission included: 838.7 million
  cycles over 8 changes in the tour [M: modules §2], about 30 s of 2.86 MHz
  CPU a change.
- **Store.** Upstream keeps a B1-compressed store of 1.82 MB in RAM. Nine
  uncompressed windows (985 KB to 1.5 MB each [M: verification §2.3]) do not
  fit in 8 MB. So the native store is compressed in RAM or read from disk per
  map (owner question 9).
- **Check.** A canonical dump after `P_SetupLevel` equals `ref816`'s for each
  of the 9 maps.

## 8. 2D screens

| Screen | Plan |
| --- | --- |
| Status bar, face, HUD text | Transliterate. Nibble read-mask-or loops run from the language card (they need RAMRD). HUD text: a cached drawer, not upstream's 65816 code generator. |
| Menus | Transliterate; view saved by memory API COPY into a hidden buffer, restored to SHR by CPU stores. ZipGS and TransWarp menus go. Key-binding names change for the //e. |
| Automap | Transliterate; `K_OVL` records through the replay |
| Intermission, finale, wipe, title pictures | Transliterate. The memory API may fill hidden staging buffers; the shown screen gets CPU stores with RAMWRT on, because PRIVATE writes are never shown [R `README_MEMORY_API.md:173-189`]. On F1.2.1 a 32,000-byte picture, and each wipe frame, costs about 31.5 ms of drain [A] |

- Upstream draws 2D into a back buffer and copies dirty ranges [R modules
  §3.8]. On F1.2.1 each SHR byte adds about 1 µs of drain [R memory §7], so
  the port draws the status bar directly into SHR and keeps a back buffer only
  where overlap forces it [A].
- Cost: 2,173 instructions a frame still; the first demo frame 1.45 M cycles
  of status [M: modules §3.8; PROFILE §1]. Patch drawing costs 4.6 M
  instructions per intermission [M: modules §3.8].

## 9. Sound on the Phasor

Design in `sound`; prototype in `build/native-design/sound/`, original code
with no upstream derivation.

| Part | Design |
| --- | --- |
| Source | The WAD's 13 MUS lumps (245,179 B), 55 `DP*` and 55 `DS*` lumps, `GENMIDI` [M: sound §1] |
| Converter (host) | MUS to a voice-command stream at 140 Hz ticks; voice allocation on the host; GENMIDI carrier envelopes as software envelopes; drums as tone/noise recipes. 141,293 B for all songs in native12 [M] |
| Voices, native mode | 7 melodic + 2 drum on chips 0-2; 3 effect voices on chip 3. 8 of 13 songs need no steal; D_INTER steals 52 of 3,250 notes [M] |
| Fallback, Mockingboard mode | 3 melodic, 1 drum, 2 effects (mb6) [M: thin chords] |
| Player | In the mouse card's VBL IRQ (50/60 Hz): catch up 2-3 ticks, compare with register shadows, one burst of changed registers. About 2,500 cycles of compute [A] |
| Effects | AY scripts: pitch from `DP*`, loudness and noise from `DS*`, hand-tuned top 10. 14,837 B [M]. 4-bit PCM ruled out on F1.2.1 [A] |
| Game side | Keep `s_sound65.s` channel logic (distance, angle, priority), with `NUM_CHANNELS` 3; drop all DOC code [R sound §4.5] |
| Cost, F1.2.1 | 11.5-27.5 ms a second, from the slot-4 slowdown: 512 CPU cycles at 1 MHz after each `$C4xx` access [A on M counts; R `config_menu.c:4660-4692`, `vtw_core_top.sv:1119-1144`, `:1884-1898`; a2vm does not model it yet] |
| Cost, `vtw.slowdown.cycles=32` | 2.5-7.1 ms a second, no firmware change [A] |
| Cost, FW-S1 (VIA port writes exempt) | 0.4-1.3 ms a second [A] |

The player's data lives in the language card or zero page (§4.5 rule 5).
The main loop refills its ring from RamWorks by CPU copy through a read
window, about 0.13 ms for 512 B [A]; the memory API cannot write the card
[R `README_MEMORY_API.md:161`].

## 10. Platform

| Area | Plan |
| --- | --- |
| Boot | ProDOS `DOOM.SYSTEM` from `demos/doom/src/kernel/loader.s`; loads the code library and data into RamWorks, installs the language-card images by CPU copy, then discards ProDOS, as the existing loader does [R `loader.s:28-33`, `kstart.s:6`] |
| Disk | No ProDOS at run time: it lives in the main card and at `$BF00`, both the port's. Either all data is loaded at boot, or our own SmartPort block reader with a ProDOS directory reader (question 9) |
| Input | `demos/doom/src/kernel/input.s`: last key held via `$C010`, Open/Closed Apple, mouse. The //e has no key-up events [R `input.s:9-13`]; a held-key policy feeds `G_BuildTiccmd`. Demos use their own tic commands. |
| Clock | Mouse-card VBL: 7 tics per 10 VBLs on PAL, per 12 on NTSC [R `demos/doom/src/kernel/frame.s:4-5`]. Upstream's clock is 34.955 tics a second [M: MILESTONES]. |
| IRQ | Handler at `$FFFE` in the main card, with a copy (vectors and a bridge) in the aux card for phases with ALTZP on. It touches only zero page, the stack, the card and I/O, so it needs no switch and ignores the pair (the pair redirects only `$0200-$BFFF`); reads `$C0A0`, acks `$C0AF`, advances the clock, runs the player |
| `$Cxxx` rule | Every access is a bus cycle and waits for the drain on F1.2.1. Input and sound run between the replay's drain and the next frame [R modules §3.10] |
| Saves, settings | Through our block reader and writer on the slot-7 driver, `$42-$47` and `$07F8` kept clear [R ARCHITECTURE §5]; tables in `$0400-$0BFF` reloaded after if touched |
| Firmware | Probe for the pair at boot [R `zpbank-spec.md:350-363`]; zero it before any ROM or SmartPort call and at exit |

## 11. Verification

| Level | What is compared | How | Status |
| --- | --- | --- | --- |
| State bridge | Upstream structures (by `linkmap.json` symbol and `offsets.inc` field) and the port's (by a layout manifest) in one canonical model; pointers as identities, lists as sequences | Host tool; excluded fields listed with reasons (`validcount` stamps, kind cache, sight caches, code banks, IRQ state) | Prototype decodes 6 dumps; 8 checks pass; SoA round trip 0 differing bytes, mobjs only [M: verification §3]. Weak points [R `build/native-design/bridge.py:157-168`, `:297-313`]: mobj identity is the live index, not the pool slot; unknown pointers pass through as raw; zone mobjs are found only through the thinker list; thinker names come from nearest labels (`T_PlatRaise` read as `pickTab_end` [M: review]) |
| Routine | Footprint of each call: first-read bytes, last-written bytes, registers | Capture on `ref816`, convert, run on a2vm with `--image`, `--reg`, `--stop-pc`; also timed under both profiles | Done by hand for 3 routines: identical on 6,496 products, 258 `calcHeight` calls, 8,533 seg columns [M: experiment] |
| Tic | Game state at each `G_Ticker` entry | Lockstep-schedule mode: a build option of the port reads the reference's tics per frame from a file, and the native renderer (or a stub with its `validcount` side effects) runs; stamps compared. Free-running mode: stamps excluded | Designed [R verification §6] |
| Frame | The frame's record stream: every record drawn, flushed batches concatenated per column in order, `K_NEXT` dropped (the port flushes where upstream does not). All of aux `$2000-$9FFF` after the replay, and no stray writes (a2vm write log). Whole screen at `I_FinishUpdate` | Replay tested alone on reference records, also from a poisoned screen with the truth from upstream's `R_DrawLists` by `--call` | Designed [R verification §7] |
| Hardware | Frame and phase times; in the lockstep build a CRC of aux `$2000-$9FFF` each frame and a canonical state digest each 35 tics (stamps and render fields excluded), both against `ref816` and a2vm | Memory API STATUS counter; VBL counts | Milestone 0 and 12 |

**Inputs to the tic level** are demo lumps, synthetic tic streams from the
scripts, and event calls logged on the reference [R verification §6.2].
Generated streams are valid tests: the reference is the truth.

**Tool additions needed** [R verification §5.2-5.3; memory §8; sound §5]:

| Tool | Addition |
| --- | --- |
| `ref816` | `--dump-at` streaming; `--call-log`; `--call`; `--poke-file`; a lump placement option (a demo lump in a free bank, DEMO3's directory entry patched: DEMO3 at `$10:8984` is followed by `M_DOOM` and `TEXTURE1` [M: review]); later `--serve` |
| The port | The lockstep-schedule build option; a record-stream log |
| a2vm | `--snapshot-ranges`; a write log; `--ay-log`; the slot-4 slowdown; the zero-page pair (state, `$C069`, watch, redirect, a JMP-pointer cycle kind, two profiles `f121zp` and `fastzp`) |

## 12. Tools

| Tool | Use from now on |
| --- | --- |
| `ref816` | The truth: runs the release, captures states and call footprints, feeds the bridge |
| a2vm | Runs and times every native routine under `f121` and `fastpath` (then the pair profiles); runs whole native builds; validated against `a2sim.py` and one hardware frame [M: MILESTONES] |
| `tools/v816` | `linkmap.json`: the symbols the bridge reads. The image match stays a regression test. |
| `build/native-design/` helpers, `build/native-experiment/` (`capture.c`, `run02.c`) | Prototypes of the bridge and the routine harness; rewritten as tools once the licence question is settled |
| The interpreter (`src/vm`) | At most a bring-up aid: a cost baseline (299-319 cycles an instruction [M: MILESTONES]), or a temporary host for cold upstream routines whose data is still in upstream layout. No milestone depends on it; it is not shipped. |

## 13. Milestones

`<native>` is the native source tree: `build/native/` until the owner decides
the licence (question 1). Acceptance tests name what a reviewer runs;
items marked "Report" are measurements, not pass/fail.
Milestone 0 (hardware microbenchmarks, owner and card) is unchanged and
should run before milestone 5 ends. The sound track S1-S4 runs in parallel.

| # | Deliverable | Acceptance test |
| --- | --- | --- |
| 4 | This file and the five `research/native-*.md` reports | Two reviews (correctness, hardware) and the owner's review |
| 5 | **Replay on captured records.** Byte-level map of main, aux 0 and both cards for each variant (§4.2). Native replay for the full view: dispatcher, our own row-block generator, fills, fuzz, covered ranges, weapon skip, F1.2.1 gather-then-draw. A loader that puts a `ref816` capture (records, screen, spans, colormaps, texels) into a2vm and onto a disk image. States whether the replay tested is the shipping layout. | (1) 0 differing bytes in all of aux `$2000-$9FFF` and no stray writes, on 3 E1M1, 11 demo and 1 E1M3 frames, each run twice: on the captured screen, and on a poisoned screen with the truth from upstream's `R_DrawLists` by `--call` (the captured screen already holds the answer: the replay changes 0-2 bytes on the E1M1 and E1M3 frames [M: review]). (2) Synthetic record streams: every kind (`K_OVL` included), row ranges, both row parities, fuzz positions, colormaps; 0 differing bytes against `--call`. (3) On the card: CRC per frame equal to a2vm; time within 25% of a2vm. Report: a2vm time against 9.2-16.9 ms still and 23.8-39.7 ms demo on F1.2.1. |
| 6 | **Harness and math.** `ref816`, a2vm and port additions of §11. Bridge v1: schema, canonical model, upstream and port readers and writers, manifest format. Native math: multiply family, divides, reciprocals, `P_AproxDistance`, angles, sine and cosine, `P_Random`. | (1) A `--dump-at` stream equals the two-run method on the 6 captures of `verification` §3.1. (2) Bridge on all coverage dumps: 0 raw pointers; every byte of the game-state regions (pool map `$0A:8000`, `GSTAMP` `$22:8000` and flood tables included) is a schema field or a named exclusion; round trip byte-exact for all object kinds and globals; zone mobjs with no thinker have an identity; thinker functions from a declared list. (3) Each math routine equals the reference routine run by `--call`: all 8,192 sine and 8,192 cosine entries; 1 million random plus edge inputs for the others. (4) With the pair off, every existing a2vm test and the `a2sim` comparison are unchanged; the pair tests of `memory` §8.3 pass. |
| 7 | **Walls and planes.** Frame setup, BSP walk, wall setup, seg loops (generated variants), planes, from bridge-injected game state and upstream's level data. | (1) At `R_DrawMasked` entry, the record stream so far, clip arrays, drawsegs and fill spans equal `ref816`'s on the milestone 5 frames and 50 frames of each coverage script (`viewsize.script` excluded until milestone 13). (2) 1,000 captured calls each of `R_StoreWallRange` and `R_RenderSegLoop` equal in routine mode. Report: a2vm time per phase against §1.2. |
| 8 | **Whole renderer.** Sprites, masked walls, weapon, fuzz, sorting. | (1) The record stream and all of aux `$2000-$9FFF` equal `ref816` on every frame of demo3 (about 534 frames), state injected per frame. (2) On the card: 100 demo3 frames from a disk image, CRC per frame equal to a2vm. Report: FPS by VBL count against a2vm. |
| 9 | **Level loading.** Host converter from `DOOM1.WAD`, native store, loader, zone. | (1) Canonical level after `P_SetupLevel` equals `ref816`'s for all 9 maps. (2) Milestone 8's frame check passes on natively loaded levels. (3) The host's worst sound-flood depth of each map fits the work stack. Report: load time per map on a2vm and the card. |
| 10 | **Game logic in demo sync.** All game logic, demo playback, game flow. | (1) demo3, lockstep-schedule mode, with a new script that runs to the demo's end (about 380 s of machine time; `title.script` stops at 25 s): game state equal after all 2,134 tics. (2) `newgame` and `tour` as tic streams: equal every tic. (3) DEMO1 (E1M5, 5,026 tics) and DEMO2 (E1M3, 3,836 tics) placed by `ref816`'s lump option: equal every tic. (4) 10 generated streams of 2,000 tics: equal. (5) demo3 rendered natively: record stream and SHR equal every frame. (6) `P_PathTraverse` on long, dense traces (over 64 intercepts) by `--call`: equal. |
| 11 | **Whole game on a2vm.** Platform (boot, input, clock, IRQ, saves), status bar, HUD, menus, automap, intermission, finale, wipe; effects (S4). | (1) From a disk image, lockstep build: title page, then demo3 in sync (bridge each tic) with full screens equal at shot points given by gametic. (2) Screen compares, by gametic, for menus, automap, intermission, finale scripts. (3) Clock 34.9-35.0 tics a second on PAL and NTSC timing. (4) Save, quit, load: the canonical state equals the state saved, and 350 tics after the load equal `ref816` doing the same save and load. |
| 12 | **Whole game on the card.** | (1) Lockstep build on F1.2.1: demo3 plays; per-frame screen CRCs and per-35-tic canonical digests equal `ref816`'s and a2vm's. (2) One hour over the 9 maps with no crash. Report: FPS still and in the demo, sound on and off, against §1.1. |
| 13 | **Pair back end, view sizes, release.** When the firmware exists: the pair build on the card. Other view sizes and detail levels. | (1) Milestone 12's tests on the pair build. (2) Frame checks at every view size, `viewsize.script` included. (3) Owner sign-off. |

**Sound track, in parallel from now (original code, can live in `tools/`):**

| # | Deliverable | Acceptance test |
| --- | --- | --- |
| S1 | Host converter and player model as tools; `tests/test_sound_*.py` | All 13 songs: the converter's event stream equals a second, independent decoder's (a MUS-to-MIDI conversion, or upstream's `tools/dmxmus.py` run inside `build/` only); steal and write counts at or below `summary50.md`; tables match their formulas |
| S2 | 65C02 player on a2vm | AY writes after every interrupt equal the model's (checked in S1) for 60 s of each song. Report: cost against `sound` §4.2 once a2vm models slot 4 |
| S3 | Music on the card | A timed loop of AY writes confirms 40.4 µs a write and the 504 µs tail (window 512 and 32); a disk plays every song; the owner listens |
| S4 | Effects and game integration (with milestone 11) | `S_StartSound` events per tic equal `ref816`'s call log through demo3 |

## 14. Risks, ranked

| # | Risk | Effect | Mitigation |
| --: | --- | --- | --- |
| 1 | Fast memory does not fit. Design: 90-130 KB wanted, about 95 KB present. F1.2.1: only main is hot (41.5 KB writable plus 18 KB write-expensive), and the card is oversubscribed (about 19.7 KB wanted in 16) | More paging at 0.25 µs a byte, or switch-bound table reads at 1-5 µs | Byte-level map per variant first (milestone 5); records via aux 0 into W; trig tables behind batched windows or in RamWorks |
| 2 | The card departs from the model; only one frame anchors it | Every ms of §1 moves | Milestone 0 before milestone 5 ends; recalibrate at 5, 8, 12 |
| 3 | Game logic volume under a bit-exact contract (52 KB upstream, 68-101 KB native) | Late desyncs; slow progress | Bridge and routine tests first; tic-level bisection; more scripts for rare paths |
| 4 | The design and the pair are not built, or D4 (loading from aux zero page) is refused | The design column is out of reach; tic code stays in W with a trampoline or paging | Port runs on F1.2.1 first; one interface, two back ends |
| 5 | The SHR drain on F1.2.1 | Replay floor 8.4-21.5 ms; any `$Cxxx` access waits, the VBL interrupt's included; every picture or wipe frame about 31.5 ms | Gather then draw; `$Cxxx` placed after the drain; lazy mirror |
| 6 | Licence undecided | Nothing rewritten can be committed | Owner question 1, before milestone 5 code |
| 7 | Level store: RAM or load time | Long loads or no room | Compressed store or disk per map (question 9) |
| 8 | Sound: slot-4 cost and the instrument mapping | 1.2-3.4% of wall time; songs sound wrong | Profile window 32 or FW-S1; tuning by ear |
| 9 | Tool work in `ref816` and a2vm competes with other work in `tools/a2vm` | Milestone 6 slips | Additions are opt-in flags; existing tests byte-identical |
| 10 | `validcount` (16 bits) rises about 23.3 a tic in the demo, so it wraps about every 2,800 tics (80 s of play) [M: review, 742 at leveltime 73, 40,157 at 1,765]. At the wrap to 0 every line not stamped since the level loaded (stamps are 0 [R `p_setup65.s:386-388`]) counts as checked | Divergence in free-running mode whenever frame counts differ across a wrap | Lockstep-schedule mode as the gate, with the renderer's increments (question 4) |
| 11 | //e input reports one key | Awkward control | Mouse and Apple keys, as the existing port |

## 15. Questions for the owner

1. **Licence.** Rewritten code is translated from upstream, so it is a
   derivative of GPL-2 code. The rule "keep upstream out of the repository"
   cannot cover it. How is `demos/doom_gs` licensed before any rewritten code
   is committed? The same question covers tools that encode upstream's
   layouts (the bridge schema).
2. **Firmware.** Will the pair and the rest of the design be built, and is
   D4 (main zero page only) final? Ship a Doom profile with
   `vtw.slowdown.cycles=32`, or pursue FW-S1?
3. **Frame exactness.** Must renderer arithmetic stay exact (`qmulh`,
   `FSTEP`, scale tables), or may it trade exactness for speed within a
   pixel budget?
4. **Release gate.** `validcount` wraps about every 80 s of play, and the
   wrap to 0 makes a whole search skip every line unstamped since the level
   loaded. Gate on lockstep-schedule mode only, or also free-running mode
   accepting those differences? Or may the port fix the wrap (a divergence
   from upstream)?
5. **Division by zero.** May the vendor divides be tested as black boxes on
   `ref816` (outputs only)? C leaves the case undefined.
6. **E1M3 or E1M7.** Settled: the WAD's DEMO3 header is E1M7, and the
   documents were corrected on 2026-09-30.
7. **Minimum speed.** What frame rate on F1.2.1 is acceptable for a first
   release? §1.1 gives 13-29 FPS still and 7.9-19 in the demo.
8. **Memory.** May the port require 8 MB of RamWorks (126 banks)?
9. **Level store.** ProDOS cannot stay resident. Compressed in RAM, loaded
   at boot (longer boot), or read per map by our own SmartPort block reader?
   What load time is acceptable?
10. **View sizes.** Needed in the first release, or full view only?
11. **Sound.** VBL rate 50/60 Hz or every second VBL; keep the 6-voice
    fallback; effects automatic with 10 hand-tuned, or all hand-made; stereo
    by picking a left or right voice.
12. **Video and input.** PAL, NTSC or both? Is the mouse card required?
