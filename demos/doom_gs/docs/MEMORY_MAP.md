# Byte-level memory map of the native port

Status: milestone 5, part A, 2026-09-30; section 8 and the replay's
regions of sections 2, 4.2 and 5 updated to the build of part C
(`src/native`, [its README](../src/native/README.md)), which departs from
part A where these sections say so. It answers [`NATIVE.md`](NATIVE.md)
section 4.2: "Milestone 5 starts with a byte-level allocation for each
variant, the language card byte by byte". Every region but the replay's
is a budget that milestones 6 to 11 fill.

**Labels**, as in `NATIVE.md`:

- **[M: source]** measured. `§A.1` and `§A.2` are measurements made for this
  map (appendix). `S2` is the size table of `src/sound/README.md`, from the
  linker map of the built player (uncommitted, reviewed once). `linkmap` is
  `build/linkmap.json`. `memory`, `verification`, `sound` and `experiment`
  are the reports in `docs/research/`.
- **[R file:line]** read there. Upstream files are in
  `build/upstream/src/iigs/`.
- **[A]** assumed, or arithmetic on labelled numbers.

**Variants.** "F1.2.1" is today's firmware. "Pair" is the firmware design
with the zero-page bank pair (`NATIVE.md` §0, profile `fastpath` plus the
pair). Both builds share the main language card, the zero page and main
`$0200-$5FFF`; they differ in W, aux bank 0 and the aux card.

**Addresses.** "aux N" is RamWorks bank N as `$C073` names it (a2vm's aux
bank N, physical N+1); aux 0 is the base aux bank with the SHR screen.
Banks 1-126 are RamWorks PSRAM; 127 is never used [R `NATIVE.md` §4.4].

## 0. Summary

| Question | Answer |
| --- | --- |
| Language card, 19.7 KB wanted in 16 | **Fits**, with four changes: (1) a `$D000` bank discipline: bank 2 holds the replay and is selected only while it runs, bank 1 holds math and the far layer and is selected otherwise, and the IRQ never touches `$D000-$DFFF`; (2) the effect-script buffers become 3 rings of 128 B (1,920 B wanted); (3) the fuzz and overlay drawers become loops in aux 0 (2.2 KB unrolled wanted); (4) the row-block entry tables and the colormap page tables move to main `$0800-$0BFF`. Section 4. |
| Its cost | 4 soft-switch reads a frame for the `$D000` bank (about 5 µs); a refill of the effect rings each frame (about 40 µs); fuzz as a loop (hidden under the drain on F1.2.1, up to about 1 ms in shadow-heavy frames with the pair) [A]. |
| What does not fit the card | Nothing of the resident set, if the assumed code sizes hold: 10.0 KB of the card is measured, about 5.5 KB assumed, about 0.9 KB spare (450 B in bank 1, 150 B in the sound code, 150 B in the replay's `$E000` part, 130 B of data, 50 B in bank 2). Fallbacks, in order: a 512 B song ring, a looped fill drawer, the memory-API transport into the level-load window (section 4.1). |
| Trig tables | Measured cold: 50 to 250 reading instructions a frame each [M: §A.2]. On F1.2.1 they go to the aux card (16,378 B of 16,384), read in short `ALTZP` windows with interrupts masked; `xtoviewangle` stays in main. |
| F1.2.1 records | Staged in aux 0 `$A000-$BFFF` (8 KB) during rendering, spilling to a RamWorks bank, bucketed by column into W before the replay. |
| F1.2.1 texel stage | W `$8000-$BFFF`, 16 KB. The three captured frames need 4.7 to 12.8 KB [M: §A.1]. A fuller stage draws a strip. |
| Game sine (16 KB) | RamWorks tables bank, both variants. |
| Player | Code and data in `$E000-$F8FF`: 4,799 B measured plus about 1.3 KB for effects [M: S2; A]. |
| Milestone 5 replay | Section 8: row blocks main card bank 2 `$D000-$DDFF`, dispatcher `$DE00-$DFFF` and `$F900-$FEFF`, records W `$6000-$7FFF`, stage W `$8000-$BFFF`, colormaps `$2000-$5FFF` and `$0400-$07FF`, entry tables `$0900-$0BFF`, spans `$0F00-$13FF`, covered ranges `$1400-$167F`, weapon skip `$1800-$197F`, zero page `$48-$6F`. |
| Main risk left | F1.2.1 render phase: aux 0 holds either the record staging or the render scratch, not both; drawsegs and vissprites go to RamWorks at an estimated 1 to 1.5 ms a frame (section 5). |

## 1. Rules the map rests on

| # | Rule | Why |
| --: | --- | --- |
| 1 | The language card is always RAM for reading and writing. Bank 1 of `$D000` is selected in every phase except the replay; the replay selects bank 2 on entry and bank 1 on exit (`bit $C083` twice, `bit $C08B` twice). | Two 4 KB banks at `$D000` serve two sets of phases [R `tools/a2vm/README.md:195`: two reads of an odd address enable writes]. |
| 2 | The IRQ handler touches only zero page `$D8-$FF`, the stack page, `$E000-$FFFF` and I/O (`$C0A0-$C0AF`, `$C400-$C4FF`). Never `$D000-$DFFF` (its bank depends on the phase), never `$0200-$BFFF` (RAMRD, RAMWRT, `$C073` and the pair may be set). | The IRQ contract of S2 [R `src/sound/README.md`, "The IRQ contract"], tightened from `$D000-$FFFF` to `$E000-$FFFF`. |
| 3 | Main `$0400-$0BFF` and `$2000-$5FFF`, and aux 0 `$0400-$0BFF`, hold only read-only data written by memory-API PRIVATE copies. No CPU store ever targets them after boot. | A CPU store there is a video write that leaves a mirror byte [R `tools/a2vm/a2vm.c:651-656`; `memory` §1.1]. |
| 4 | Aux 0 `$2000-$9FFF` is written only by CPU stores with RAMWRT on. PRIVATE never targets it. | PRIVATE writes are never shown [R `appletini-one/README_MEMORY_API.md` §4]. |
| 5 | Inside a far window only zero page, the stack page and the language card are near; code in a read window runs from the card or zero page. | `NATIVE.md` §4.5 rules 1-2. |
| 6 | During the replay's draw pass (RAMWRT on, `$C073` = 0), the replay writes only zero page `$48-$6F`, the stack, the row-block patch bytes in card bank 2, and aux 0 `$2000-$88FF`. | With RAMWRT on, every store to `$0200-$BFFF` goes to aux 0 [R `a2vm.c:643-648`]. Upstream writes back into records (`texStart`, `fillStart`) and resets `COLW` and `CV_ROW` during the replay [R `r_list65.s:601-605`, `:636-638`, `:1102`, `:1123`]; the native replay keeps those values in zero page and clears the covered ranges of a strip's columns after that strip's draw pass (RAMWRT off). |
| 7 | On F1.2.1, `ALTZP` is on only inside a window of straight-line code bracketed by SEI and CLI, which keeps results in registers or in main `$0200-$BFFF`. | The F1.2.1 aux card is full of tables and has no vectors (section 4.3). With `ALTZP` on, zero page and stack are aux's [R `appletini-hardware.md:109`]. |
| 8 | Nothing is ever written to main `$0878-$087F` or `$4078-$407F` by the CPU. | The firmware reads an `A2Li` signature and a load-hold byte there from its shadow of main memory, and treats writes there as immediate [R `appletini-one/hdl/apple/vtw_video_policy.sv:33-37`; `ps_sources/frontend/apple_cycle_renderer.c:2283-2336`]. PRIVATE writes emit no capture records, so a colormap loaded there by PRIVATE never reaches that shadow [R `README_MEMORY_API.md` §4]. |
| 9 | Slot holes of main `$0400-$07FF` (`$x78-$x7F`, `$xF8-$xFF`) and `$07F8` are written by slot firmware and SmartPort calls. The pages there are reloaded after any firmware call. | [R `NATIVE.md` §4.1, §10]. |
| 10 | Aux 0 `$9DC8-$9DFF` stays zero. | Standard SHR. The bytes `"SHR4"`\|`$80` at `$9DFC-$9DFF` would switch the card to its PAL256 mode [R `demos/doom/docs/DESIGN.md:60-72`]. |

## 2. Zero page and stack

Main zero page, both variants, all phases:

| Range | Bytes | Owner | Content |
| --- | ---: | --- | --- |
| `$00-$05` | 6 | platform | Temporaries of platform code (far layer arguments, memory API) |
| `$06-$07` | 2 | platform | The pair: `zp_rd`, `zp_wr` [R `firmware/zpbank-review.md:180`]. Always 0 on F1.2.1; reserved in both builds so they share the map |
| `$08-$17` | 16 | platform, persistent | `$C073` shadow, window state, far pointers and count, current phase, frame counter |
| `$18-$41` | 42 | phase overlay 1 | Per phase, below |
| `$42-$47` | 6 | reserved | Never live across a SmartPort call [R `NATIVE.md` §10; the pair spec's forbidden ROM and ProDOS zero page, `zpbank-spec.md` §7] |
| `$48-$D7` | 144 | phase overlay 2 | Per phase, below; the replay's `$48-$6F` (section 8) |
| `$D8-$FF` | 40 | IRQ | The player's 31 B [M: S2 `SNDZP`], effect ring pointers 6 B [A], 3 spare |

| Phase | Overlays used | Stack (main page 1) |
| --- | --- | --- |
| Boot, installer | all but `$D8-$FF` | page 1 |
| Level load | 1 and 2 | ≤ 128 B [A] |
| Tics | 1 and 2 (argument blocks, current mobj, fixed-point temporaries) | ≤ 160 B [A; upstream's tic stack reached 228 B with 3-byte returns, M: `PROFILE.md:680`] |
| Render | 1 and 2 (the seg loop page); spill to main `$0280-$02FF` | ≤ 112 B with the IRQ's 24 [M: at most 79 B below the driver's S in milestone 7's frame mode, 188 frames, so 103 B with the IRQ; the first budget, 96 B [A; BSP recursion about 80 B, R `NATIVE.md` §6; upstream's frame stack 86 B, M: `MILESTONES.md`], was below that and was raised in milestone 7's verification; `tools/native/rlayout.py` `RENDER_STACK`] |
| Replay | `$48-$6F` (39 B used [M: `make sizes`]) | 14 B below the caller's S [M: the harness's snapshots]; page 1 `$0100-$01B4` holds its gather (below), so S ≥ `$01C0` always |
| 2D, menus | 2 | ≤ 64 B [A] |
| IRQ | `$D8-$FF` | ≤ 24 B on top of any phase [A; a2vm can measure] |

The worst stack is about 16 (main loop) + 160 (tics) + 24 (IRQ) = 200 B of
256 [A]. Persistent state never lives in an overlay: it is in `$08-$17`,
`$0300-$03EF` or main `$1A80-$1FFF`.

**F1.2.1 replay (built).** During the replay `$0100-$018F` holds the
gather's 12 copy descriptors of 12 B and `$0190-$01B4` its per-row copy
loop (37 B, copied there at each call, its absolute operands set for each
record) [M: `src/native`]. Page 1, like zero page, is near in every RAMRD
state, so data and code there serve the copies that run with RAMRD on; the
card had no room. The stack stays at or above `$01C0`: the replay itself
takes 14 B below the caller's S [M], so with an IRQ on top (≤ 24 B) the
caller's S must be at least `$01E6` [A]. The harness checks that nothing
of page 1 changes but `$0100-$01B4` and `$01C0` up to the caller's S.

**Pair build only.** During the replay `$0100-$017F` is the texel bounce
buffer [R `NATIVE.md` §4.1], so S stays at or above `$0180` then (about 56
B used [A]). In the tic phase `ALTZP` is on and the tics use the aux zero
page and aux stack; pair stores go through the trampoline [R `NATIVE.md`
§4.3].

**Aux zero page and stack, F1.2.1.** Unused (rule 7).

## 3. Main memory `$0200-$BFFF`

### 3.1 `$0200-$03FF`

| Range | Bytes | Content | Owner | Loaded | Read-only in the frame |
| --- | ---: | --- | --- | --- | --- |
| `$0200-$027F` | 128 | Far bounce buffer: `FAR_GET` destination for records larger than zero page (a node 28 B, a seg 18 B, a sector 58 B [R `verification` §2.1]) | tics, render | scratch | no |
| `$0280-$02FF` | 128 | Zero-page spill of the running phase (the render loop page first) | per phase | scratch | no |
| `$0300-$03EF` | 240 | Persistent globals: gametic, tic command slot, input state, effect request queue, fill-span frame stamps (`W_FSC`, `W_FSP`, `W_FSW` [R `r_list65.s:144-150`]), level number, frame parameters. Milestone 7 (section 12): the cost phase `$0300` (test builds), the render frame block `$0310-$036F`, the render inputs `$0370-$039F`, the level's counts `$03A0-$03A3` | platform, all | zeroed at start | no |
| `$03F0-$03FF` | 16 | //e ROM soft vectors (BRK, reset, `&`, Ctrl-Y, NMI, `$03FE` IRQ). Set once at boot; the game's IRQ vector is `$FFFE` in the card | ROM | boot | yes |

### 3.2 `$0400-$0BFF`, write-expensive, read-only

| Range | Bytes | Content | Loaded | Label |
| --- | ---: | --- | --- | --- |
| `$0400-$04FF` | 256 | Colormap A, light level 32 | per level, PRIVATE; again after any firmware call (rule 9) | R `NATIVE.md` §4.1; 34 levels of 256 B [M: linkmap `iigs_shrcmapA` 8,704 B] |
| `$0500-$05FF` | 256 | Colormap A, level 33 | same | same |
| `$0600-$06FF` | 256 | Colormap B, level 32 | same | same |
| `$0700-$07FF` | 256 | Colormap B, level 33 | same | same |
| `$0800-$0821` | 34 | `CMPA`: page of colormap A by light level | boot, PRIVATE | A |
| `$0822-$0843` | 34 | `CMPB`: page of colormap B by light level | boot, PRIVATE | A |
| `$0844-$0877` | 52 | free (read-only data only) | | |
| `$0878-$087F` | 8 | **forbidden** (rule 8) | never | R `vtw_video_policy.sv:36` |
| `$0880-$08FF` | 128 | free (read-only data only) | | |
| `$0900-$09A8` | 169 | `TEXLO`: low byte of the texture row block of row 0-168 | boot, PRIVATE | A |
| `$09A9-$0A49` | 161 | `XTVLO`: `xtoviewangle` low bytes, x = 0-160 | boot, PRIVATE | M: linkmap 322 B |
| `$0A4A-$0AF2` | 169 | `TEXHI` | boot, PRIVATE | A |
| `$0AF3-$0B93` | 161 | `XTVHI` | boot, PRIVATE | M: linkmap |
| `$0B94-$0BFF` | 108 | free (read-only data only) | | |

Light levels 32 and 33 are the invulnerability map and the last map of the
`COLORMAP` lump [R `p_user65.s:39`]; they are rare, so they sit in the
pages that firmware calls can touch.

### 3.3 `$0C00-$1FFF`, renderer state and hot globals

All arrays are one byte per column, x = 0-159, split from upstream's words
[A; as the experiment's seg loop, R `experiment` (a)]. The three arrays
the seg loops index at column rate start on a page boundary.

| Range | Bytes | Content | Owner | Persistent across frames | Label |
| --- | ---: | --- | --- | --- | --- |
| `$0C00-$0C9F` | 160 | `FLOORCLIP` | render | no | M: linkmap `floorclip` 320 B |
| `$0CA0-$0CFF` | 96 | render scratch; `FRVIS` at `$0CA0-$0CC9` (milestone 7, section 12) | render | no | A |
| `$0D00-$0D9F` | 160 | `CEILCLIP` | render | no | M: linkmap `ceilingclip` |
| `$0DA0-$0DFF` | 96 | render scratch | render | no | A |
| `$0E00-$0E9F` | 160 | `SOLIDCOL` | render | no | M: linkmap `solidcol` 160 B |
| `$0EA0-$0EFF` | 96 | render scratch | render | no | A |
| `$0F00-$0F9F` | 160 | `FSTOP`: end of the top fill span | render | **yes** | R `lists.inc:73-86` (`FS_ROW` byte 2c) |
| `$0FA0-$103F` | 160 | `FSBOT`: first row of the bottom span | render | yes | `FS_ROW` byte 2c+1 |
| `$1040-$10DF` | 160 | `FSEVT`: even-row byte, top span | render | yes | `FS_EVEN` |
| `$10E0-$117F` | 160 | `FSEVB`: even-row byte, bottom span | render | yes | `FS_EVEN` |
| `$1180-$121F` | 160 | `FSODT` | render | yes | `FS_ODD` |
| `$1220-$12BF` | 160 | `FSODB` | render | yes | `FS_ODD` |
| `$12C0-$135F` | 160 | `FSSTT`: stamp of the top span | render | yes | `FS_STAMP` |
| `$1360-$13FF` | 160 | `FSSTB` | render | yes | `FS_STAMP` |
| `$1400-$149F` | 160 | `CVFIRST`: first covered row (0: none; 255: a shadow) | render, replay | zero between frames | R `lists.inc:108-117` (`CV_ROW` byte 2c) |
| `$14A0-$153F` | 160 | `CVEND`: row after the covered range | render, replay | zero between frames | `CV_ROW` byte 2c+1 |
| `$1540-$15DF` | 160 | `CVRECLO`: the covering record, low byte of its W address | render, replay | no | `CV_REC` |
| `$15E0-$167F` | 160 | `CVRECHI` | render, replay | no | `CV_REC` |
| `$1680-$1720` | 161 | `COLLO`: first record of column c in the record buffer; entry 160 is the end | replay | no | A |
| `$1721-$17C1` | 161 | `COLHI` | replay | no | A |
| `$17C2-$17FF` | 62 | replay scratch, written outside the draw pass only | replay | no | A |
| `$1800-$189F` | 160 | `WCLIP`: weapon skip, floor clip after the weapon pass | render | **yes** | R `lists.inc:123-129` |
| `$18A0-$18DF` | 64 | `WPREV`: the weapon vissprite of the frame before | render | yes | R `lists.inc:125-126`, `:130-131` (`$1C0 - $180`) |
| `$18E0-$197F` | 160 | `WTMP`: floor clip of a sprite in a frame that skips the weapon rows | render | no | R `lists.inc:127-128`, `:131` |
| `$1980-$19FF` | 128 | `DSX1`: x1 of drawseg i | render | no | R `dscols.inc:3-11`; 416-624 reads a frame [M: §A.2] |
| `$1A00-$1A7F` | 128 | `DSX2` | render | no | R `dscols.inc:12` |
| `$1A80-$1FFF` | 1,408 | Persistent hot game globals (the rest of upstream's near game globals go to RamWorks). Milestone 7 (section 12): `TEXTRANS` `$1A80-$1B7F`, `LNMAP` `$1B80-$1BFF` | tics | yes | A |

Tic phases never overlay `$0C00-$1A7F`.

### 3.4 `$2000-$5FFF`, colormaps, write-expensive, read-only

| Range | Bytes | Content | Loaded |
| --- | ---: | --- | --- |
| `$2000-$3FFF` | 8,192 | Colormap A, light levels 0-31: level L at page `$20+L` | per level, one PRIVATE COPY of 17,408 B with the pages of `$0400-$07FF`: about 6 ms [M: 0.343 µs/B, `memory` §1.2] |
| `$4000-$5FFF` | 8,192 | Colormap B, levels 0-31: level L at page `$40+L`. Page `$40` covers `$4078-$407F` (rule 8) | same |

The dispatcher reads `CMPA` and `CMPB` indexed by upstream's own `R_CMP`
byte, which is the page of colormap A in bank `$0D`, `$46` + L [R
`lists.inc:44-45`; M: linkmap `iigs_shrcmapA` at `$0D:4600`; the captured
records hold `$46-$64`, §A.1]. The table is
addressed as `CMPA-$46,Y`, so records keep upstream's value unchanged and no
page is crossed.

### 3.5 W, `$6000-$BFFF`, by phase

W is not write-expensive. It holds one phase at a time; code is loaded by
CPU copy from bank 1 of the card (0.246 µs/B [M: `memory` §1.2]) and never
saved back.

**F1.2.1:**

| Phase | Range | Bytes | Content | Loaded |
| --- | --- | ---: | --- | --- |
| Tics | `$6000-$BFFF` | 24,576 | Tic code window (hot set 5.5 KB still, 24-27 KB in a fight [A: `NATIVE.md` §4.3]) plus tic scratch: `intercepts` 640 B [M: linkmap], the sound-flood work stack, about 600 B [A] | per frame, CPU copy |
| Render | `$6000-$B9FF` | 23,040 | Render code window (hot set 19-26 KB [A: `NATIVE.md` §4.3]; the masked-phase code loads over the BSP code) | per frame, CPU copy |
| Render | `$BA00-$BFFF` | 1,536 | `YHTAB` 1,026 B, written in the masked phase [M: linkmap `YHTABM`; §A.2]; render scratch | scratch |
| Replay | `$6000-$7FFF` | 8,192 | Record buffer, one batch (section 8) | bucket pass from aux 0 and the records bank |
| Replay | `$8000-$BFFF` | 16,384 | Texel stage (section 8) | gather |
| 2D, menus, automap, intermission, level load | `$6000-$BFFF` | 24,576 | Mode window | when the mode starts |

**Pair:** the replay uses neither the record buffer nor the stage, and the
tics run from the aux card, so the render window stays resident: code
`$6000-$B9FF`, data `$BA00-$BFFF`, loaded when play starts. Overflow code
is paged into it (3.4 KB in the demo [A: `NATIVE.md` §4.3]). Menus and
level load reload it when they end.

## 4. The language cards

### 4.1 The oversubscription and its resolution

`NATIVE.md` §4.1 wanted about 19.7 KB in 16 KB: platform 6 KB, math 4 KB,
row blocks and dispatcher 5.5 KB [A], player data 4.2 KB [R `sound`
§4.3]. The resolution, with what moved out:

| Wanted | KB | Placed in the main card | Bytes | Moved out, and where |
| --- | ---: | --- | ---: | --- |
| Platform: IRQ, player code, input, far layer, phase loader, memory-API transport | 6 | Sound and IRQ code and tables `$E900-$F8FF`; far layer, phase loader and transport bank 1 `$DC00-$DFFF`; platform `$FF00-$FFFF` | 5,376 | Input to the tic window: it runs in the main loop between the drain and the next frame [R `NATIVE.md` §10] |
| Math with square tables | 4 | Bank 1 `$D000-$DBFF` | 3,072 | None |
| Row blocks and dispatcher | 5.5 | Bank 2 `$D000-$DFFF`; `$F900-$FEFF` | 5,632 | Fuzz and overlay drawers (2.2 KB unrolled [R `memory` §3.2]) to loops in aux 0 `$0200-$03FF`; entry tables to main `$0900-$0BFF` |
| Player data | 4.2 | `$E000-$E8FF` | 2,304 | Effect-script buffers (3 × 640 = 1,920 B [R `sound` §4.3]) to 3 rings of 128 B; scripts stay in RamWorks |
| **Total** | **19.7** | | **16,384** | |

**Why the `$D000` banks now count twice.** `NATIVE.md` §4.1 allowed the
second `$D000` bank only "code that never runs in the replay or inside a
window". That rule assumed the bank could change in the middle of a phase.
Here it changes twice a frame, at the replay's edges, and the IRQ never
reads `$D000-$DFFF` (rule 2), so each bank is a full 4 KB for its phases.
Bank 1 code may run inside far windows: the card is near in every window.

**Cost [A]:**

| Change | Cost a frame |
| --- | --- |
| `$D000` bank switches | 4 reads of `$C08x`, about 5 µs with the TURBO refill; the switch back at the replay's end is paid inside the drain wait that the next `$Cxxx` access pays anyway |
| Effect rings | The main loop refills 3 rings from RamWorks through a read window: at most about 40 B a voice a frame, about 40 µs. Effects last 0.87 s and average 270 B [M: `sound` §4.5; 14,837 B / 55] |
| Fuzz and overlay as loops | On F1.2.1 hidden under the drain (every fuzz byte is also a screen byte, 0.985 µs). With the pair, up to about 1 ms in frames with many shadow columns (91 fuzz records in one demo frame [M: `verification` series]) |
| Fuzz and overlay in aux 0 | Two RAMRD switches a record; on F1.2.1 the first waits for the bytes pending in the mirror |
| Entry tables in main | None: the replay reads them with RAMRD off |

**What does not fit, and the fallbacks.** Measured: 9,985 B (player
4,799 [M: S2], squares 2,048 and multiply 114 [M: `experiment` (b)],
texture blocks 3,024 [M: 36 B a row pair, `memory` §2.2]). Assumed: about
5,460 B (effects and IRQ state 1,248, math 486, far layer and transport 1,000, fill
blocks 505, dispatcher 1,902, platform 314). Spare: about 940 B. If the
code grows past the spare shown in 4.2:

1. Song ring 1,024 B to 512 B (−512 B). At ≤ 173 B/s it still lasts 2.9 s
   [M: `sound` §3.7]. Needs the S2 tests rerun.
2. Fill row blocks unrolled (505 B) to a loop (about 60 B). Costs nothing
   on F1.2.1, where the drain bounds fills; about 2 ms in fill-heavy
   frames with the pair [A: 26,880 fill bytes at 0.157 µs, `memory` §1.2,
   three times slower].
3. Memory-API transport (level loads, menus only) into the window of the
   mode that calls it, which the request must not overwrite (−about 400 B
   in bank 1).
4. Effect code into bank 1 with the IRQ selecting bank 1 itself: reads
   `$C011` and switches when it interrupts the replay, about 4 µs an
   interrupt (breaks rule 2; last resort).

### 4.2 Main card, byte map (both variants)

Installed at boot by CPU copy; the memory API cannot write the card [R
`README_MEMORY_API.md` §3]. Only the row-block patch bytes, the player's
state, rings and lists, and the IRQ state change afterwards.

**Bank 2 `$D000-$DFFF`: the replay bank** (selected only while the replay
runs):

| Range | Bytes | Content | Size, label |
| --- | ---: | --- | --- |
| `$D000-$DBCF` | 3,024 | Texture row blocks: row pair p (rows 2p, 2p+1) at `$D000 + 36p`, from our own generator | M: 36 B a row pair, `memory` §2.2; upstream's full-view image is 3,195 B [M: linkmap `texBlocks`] |
| `$DBD0` | 1 | Landing of row 168: `RTS` | A |
| `$DBD1-$DBFF` | 47 | generator slack | |
| `$DC00-$DCFB` | 252 | Fill row blocks of the even rows: row r at `$DC00 + 3 × (r >> 1)`, `STA $2000+160r,X` | M: build. Part A had one chain, "`STA` or `STY abs,X`", 3 B a row: the 65C02 has no `STY abs,X` (nor `STX abs,Y`), so each parity has its chain, and a fill record runs both with its parity's byte in A (upstream 4 B a row [M: linkmap `flatBlocks` 672 B]) |
| `$DCFC` | 1 | Landing of the even chain: `RTS` | M |
| `$DCFD-$DCFF` | 3 | slack | |
| `$DD00-$DDFB` | 252 | Fill row blocks of the odd rows: row r at `$DD00 + 3 × (r >> 1)` | M |
| `$DDFC` | 1 | Landing of the odd chain: `RTS` | M |
| `$DDFD-$DDFF` | 3 | slack | |
| `$DE00-$DFFF` | 512 | Dispatcher, hot part: column loop, record fetch, kind dispatch, covered-range cut, texture and fill set-up, exit patch and restore | 509 used [M: `make sizes`] |

**Bank 1 `$D000-$DFFF`: the compute bank** (selected in all other phases):

| Range | Bytes | Content | Size, label |
| --- | ---: | --- | --- |
| `$D000-$D7FF` | 2,048 | Quarter squares: four 512 B tables, page aligned | M: `experiment` (b) |
| `$D800-$DBFF` | 1,024 | 16 × 16 multiply (114 B [M: `experiment` (b)]), `FixedMul` family, divides written from the call sites, 16/32-bit helpers | about 600 B [A] |
| `$DC00-$DFFF` | 1,024 | Far layer (F1.2.1 or pair back end), the RamWorks table lookup, phase loader (CPU copy RamWorks → W with RAMRD on). The memory-API transport moved to the window of the mode that calls it (4.1 fallback 3, taken by milestone 7: section 12) | `MATHFAR` 67 B at `$DC00`, `far.s` 313 B at `$DC43-$DD7B` [M: `src/native/render.mk` sizes, stage A]; stage B adds the `FSTEP` gather, stage C the phase loader: 642 B in all [M] |

**`$E000-$FFFF`** (always visible):

| Range | Bytes | Content | Size, label |
| --- | ---: | --- | --- |
| `$E000-$E3FF` | 1,024 | Song ring, page aligned | M: S2 |
| `$E400-$E402` | 3 | Ring mirror | M: S2 |
| `$E403-$E412` | 16 | IRQ state: VBL count, tic accumulator, tic counter | A |
| `$E413-$E442` | 48 | Effect voice state (3 voices) | A |
| `$E443-$E47F` | 61 | spare | |
| `$E480-$E4FF` | 128 | Player write lists (one page, as `player.s` checks) | M: S2 |
| `$E500-$E736` | 567 | Player state: voices, shadows, song tables | M: S2 |
| `$E737-$E73F` | 9 | spare | |
| `$E740-$E8BF` | 384 | Effect rings, 3 × 128 | A |
| `$E8C0-$E8FF` | 64 | spare | |
| `$E900-$F8FF` | 4,096 | Sound code and tables: music, bursts, refill, the IRQ entry `snd_vbl` (2,104 B [M: S2]), periods, bend, levels (973 B [M: S2]), effects player (about 800 B [A]), platform IRQ additions (about 64 B [A]) | 3,941 used, 155 spare |
| `$F900-$FEFF` | 1,536 | Replay, `$E000` part: batches and strips, the F1.2.1 gather (walk, copies) or the pair bounce, the texture cut's `texStart`, the fill chains' set-up, calls to the aux-0 drawers, the covered-range clear | 1,079 B built [M: `make sizes`]; part A assumed about 1,390 B |
| `$FF00-$FFF9` | 250 | Platform: phase switch (card bank, RAMWRT, `$C073` 0), BRK and crash stub, IRQ bridge landing (pair build) | A |
| `$FFFA-$FFFF` | 6 | Vectors: NMI, reset (unused: reset selects the ROM), IRQ/BRK → `snd_vbl` | |

The S2 player's test map puts its ring, lists and state in bank 2 at
`$D000` [R `src/sound/sound.cfg`]; in the game they move to `$E000-$E736`
(rule 2). The player's README says nothing in it depends on those
addresses except the ring's page alignment and the lists' single page.

### 4.3 Aux card, F1.2.1: read-only tables

Loaded at boot by CPU copy with `ALTZP` on (through a bounce buffer in W).
Read by main code in SEI windows (rule 7): `ALTZP` on, one to three loads
into registers or main memory, `ALTZP` off. A window costs 2.4-4 µs [M:
`memory` §5.2, two to four bus cycles with the TURBO refill].

| Range | Bytes | Content | Reads a frame, still / demo [M: §A.2] |
| --- | ---: | --- | --- |
| aux card bank 1 `$D000-$D7FF` | 2,048 | `finetangent` part 3: 1,024 words as low and high planes | 83 / 62 (both parts) |
| bank 1 `$D800-$DFF9` | 2,042 | `viewangletox`, one plane: upstream's table is 2,042 **bytes** (values 0-160, `r_bsp65.s:1106-1235`, read as a word masked to its low byte), not 1,021 words. Corrected by milestone 7 (`docs/RENDER.md` 1.6); the earlier low and high planes of 1,021 were wrong | 166 / 100 |
| bank 1 `$DFFA-$DFFF` | 6 | free | |
| bank 2 `$D000-$DFFF` | 4,096 | `finetangent` part 4: 1,024 longs as four planes. Also needs bank 2 selected: 3 more soft-switch reads a window | |
| `$E000-$FFFF` | 8,192 | `tantoangle` entries 0-2047 as four planes of 2,048 at `$E000`, `$E800`, `$F000`, `$F800`. Entry 2048 is a constant in code (`ANG45`, `$20000000` [A: Doom's table; checked against upstream's at build]) | 62 / 50 |

Sizes: `tantoangleTable` 8,196 B, `finetangentTable_part_3` 2,048 B,
`_part_4` 4,096 B, `viewangletoxTable` 2,042 B [M: linkmap]; part 3 is
indexed by 2 × angle and part 4 by 4 × angle [R `r_seg65.s:2029-2066`].
Total 16,378 of 16,384 B. There are no vectors, which rule 7 makes safe.
Standing still, 311 reading instructions a frame [M: §A.2], about 1.5 a
lookup, make about 200 windows: 0.5-0.8 ms [A].

`finesineTable_part_1` (4,096 B, 42-50 reads a frame [M: §A.2]) and
`xtoviewangle` do not fit here: the first goes to the RamWorks tables
bank, the second to main `$09A9` and `$0AF3`.

### 4.4 Aux card, pair: the tic window

Tics run with `ALTZP` on, so the main card is unreachable and the aux card
carries its own copies [R `NATIVE.md` §4.3].

| Range | Bytes | Content | Label |
| --- | ---: | --- | --- |
| aux card bank 1 `$D000-$D7FF` | 2,048 | Quarter squares (copy) | M |
| bank 1 `$D800-$DBFF` | 1,024 | Math (copy), the 20 B pair trampoline, the pair far helpers | A |
| bank 1 `$DC00-$DFFF` | 1,024 | Tic code | A |
| bank 2 `$D000-$DFFF` | 4,096 | Tic code, cold part (needs bank 2 selected) | A |
| `$E000-$FEFF` | 7,936 | Tic code, hot part | A |
| `$FF00-$FFF9` | 250 | IRQ bridge: same bytes as main `$FF00-$FFF9` at the addresses where the fetch crosses cards (`ALTZP` off, call the main handler, `ALTZP` on, `RTI` from the aux stack) | A |
| `$FFFA-$FFFF` | 6 | Vectors → the bridge | |

Tic code room is about 9 KB hot plus 4 KB cold, against 5.5 KB still and
24-27 KB in a fight: 11-14 KB paged per fight frame by CPU copy [A;
`NATIVE.md` §4.3 said 13-16 KB]. The trig tables go to the RamWorks tables
bank, read through `zp_rd`.

## 5. Aux bank 0

| Range | Bytes | F1.2.1 | Pair | Loaded | Read-only in the frame |
| --- | ---: | --- | --- | --- | --- |
| `$0000-$01FF` | 512 | unused (rule 7) | Tic zero page and stack | | |
| `$0200-$02BF` | 192 | Screen-reading drawers, as loops: fuzz, automap overlay (113 B built [M]), the status bar's read-mask-or. They run with RAMRD and RAMWRT on, so their code and tables are aux reads. Since the fuzz queue took `$02C0-$03FF`, the status bar's drawer, not yet written, has the 79 B left. If it needs more, the queue shrinks by 4 B a record (`FQMAX`; `layout.py` asserts that `FUZZQ` is `AUXCODE_END` and that the queue ends at `$0400`), or the drawer goes to `$0400-$07FF` once its slot holes are verified | same | boot, PRIVATE | yes |
| `$02C0-$03FF` | 320 | The replay's fuzz queue: 80 records as four arrays of 80 bytes (column, first row, count, position), written in the draw pass with RAMWRT on, read with RAMRD on (section 8) | same | scratch | no |
| `$0400-$07FF` | 1,024 | free, write-expensive (read-only data only; aux slot holes unverified) | same | | |
| `$0800-$08FF` | 256 | `FUZZDARK`: darker colour of each colour | same | per level, PRIVATE (it follows the level palette [R `i_viigs65.s:1014-1017`]) | yes |
| `$0900-$09C7` | 200 | `ROWLO`: SHR row address, rows 0-199 | same | boot, PRIVATE | yes |
| `$09C8-$09F9` | 50 | `FZDIR`: the fuzz direction by position, 1 for the row below (Doom's `fuzzoffset`; upstream's `fuzzDir` [R `i_viigs65.s`]) | same | boot, PRIVATE | yes |
| `$0A00-$0AC7` | 200 | `ROWHI` | same | boot, PRIVATE | yes |
| `$0AC8-$0BFF` | 312 | free (read-only data only). Part A put `FZMOD50` (i mod 50, i < 250) at `$0B00`; the built fuzz drawer steps its position 0-49 itself | | | |
| `$0C00-$15FF` | 2,560 | `openings`, bytes: written in bursts per drawseg, 1,081 writes and 21 reads a frame still [M: §A.2] | same | scratch | no |
| `$1600-$19FF` | 1,024 | `SC_TAB` | same | scratch | no |
| `$1A00-$1FFF` | 1,536 | Drawseg fields read by the masked phase, 128 × 12 B [A] | With `$A000-$BFFF`: drawsegs and vissprites whole, 8,736 B as field planes [A] | scratch | no |
| `$2000-$88FF` | 26,880 | The 3D view: rows 0-167 × 160 B; the only range the replay writes | same | CPU stores | |
| `$8900-$9CFF` | 5,120 | Status bar rows 168-199 | same | CPU stores | |
| `$9D00-$9DC7` | 200 | SCBs | same | CPU stores | |
| `$9DC8-$9DFF` | 56 | zero (rule 10) | same | | |
| `$9E00-$9FFF` | 512 | 16 palettes | same | CPU stores | |
| `$A000-$BFFF` | 8,192 | Record staging: producers append records in production order through a zero-page batch buffer; beyond 8 KB they spill to the records bank | See `$1A00` | scratch | no |
| aux LC | 16,384 | Section 4.3 | Section 4.4 | boot | |

Aux 0 `$09FA-$09FF` and `$0AC8-$0BFF` are free (read-only data only). Upstream's sizes: `openings` 2,560 words, `_s_drawsegs` 128 × 42 B,
`vissprites` 80 × 42 B, `SC_TAB` 1,024 B [M: linkmap]. The view is rows
0-167 from byte 0 [R `build/gen/drawcol.s:23-24`, `:546-548`]; 168 rows is
`CONST_VIEWHEIGHT` [R `offsets.inc:1005`].

**F1.2.1 does not fit aux 0.** It has 13,312 writable bytes besides the
drawer code (`$0C00-$1FFF`, `$A000-$BFFF`). The render phase wants the
record staging (8 KB), openings, `SC_TAB`, drawsegs and vissprites: 20.5
KB. Records stay in aux 0: in RamWorks they would cost about 4 ms a frame
standing still against about 2 ms [A: writes 0.42 against 0.2 µs/B with
windows; reads 0.25 against 0.19 µs/B]. So drawsegs (5,376 B) and
vissprites (3,360 B) go to the RamWorks render bank: one `FAR_PUT` a
drawseg, one `FAR_GET` a sprite or clip candidate, 1-1.5 ms a frame [A on
M rates: 1,268 drawseg and 333 vissprite accesses a frame still, 661 and
736 in the demo, §A.2]. Milestone 7 measures it; the fallback is a smaller
staging area with more spill.

## 6. Pair build: what differs

| Region | F1.2.1 | Pair |
| --- | --- | --- |
| Main card | Section 4.2 | Same bytes; `$F900-$FEFF` holds the bounce in place of the gather, `$DC00-$DFFF` the pair back end |
| Aux card | Trig tables (4.3) | Tic window (4.4) |
| W | Phase windows, reloaded every frame | Render window resident |
| Records | Aux 0 staging, bucketed into W | The records bank through `zp_wr` and `zp_rd` |
| Texel stage | W `$8000-$BFFF` | `$0100-$017F`, 128 B a record [R `memory` §5.3] |
| Drawsegs, vissprites | RamWorks render bank | Aux 0 (quiet switches) |
| Trig tables | Aux card; `xtoviewangle` main | RamWorks tables bank through `zp_rd`; `xtoviewangle` main |
| Zero page | Section 2 | Same, plus the tics' aux zero page |

## 7. Where the unplaced items of `NATIVE.md` §4.2 went

| Item | Size | F1.2.1 | Pair |
| --- | --- | --- | --- |
| Records | 5,969 B still; 2,079-10,524 B demo [M: `verification` §2.2] | Aux 0 `$A000-$BFFF` staging, spill to the records bank; W `$6000-$7FFF` per batch | Records bank |
| Texel stage | 4.7-12.8 KB on the three captured frames with the rule of §A.1 [M] | W `$8000-$BFFF`, 16 KB; strips beyond | `$0100-$017F` |
| Game sine | 16 KB [R `NATIVE.md` §3.1] | RamWorks tables bank, one window a lookup | same, through `zp_rd` |
| Player code | 2,104 B + 973 B tables [M: S2]; effects about 800 B [A] | Main card `$E900-$F8FF` | same |
| Player data | 1,722 B [M: S2]; effects 432 B [A] | Main card `$E000-$E8FF` | same |
| Song streams, effect scripts | about 283 KB [R `sound` §4.3] | RamWorks | same |
| `states`, `mobjinfo` | 8,224 B [M: linkmap]; 353-836 reads a frame in tics [M: §A.2] | RamWorks, one `FAR_GET` a state change | same, through `zp_rd` |
| `FLATCM` | 1,088 B [M: linkmap]; 12-62 reads a frame [M: §A.2] | RamWorks tables bank | same |

**RamWorks banks this map adds** to `NATIVE.md` §4.4: a records bank (F1.2.1
spill and render bank: drawsegs, vissprites; pair: all records), and a
tables bank (sine 16 KB, `finesine` part 1, `FLATCM`, sprite scales 32 KB,
`states` and `mobjinfo`). Both fit the 76-82 banks of §4.4's total.

## 8. The milestone 5 replay: exact addresses

This is the F1.2.1 layout, which is the shipping placement for F1.2.1. The
record format is upstream's (`lists.inc` kinds and fields, `K_NEXT`
dropped) packed by column; milestone 7 may change the fields (a column tag
for the staging), not these addresses. The pair build's replay (records bank,
bounce at `$0100`) is tested in milestone 13.

| Part | Where | Bytes | Notes |
| --- | --- | ---: | --- |
| Texture row blocks | Main card bank 2 `$D000-$DBCF`, landing `$DBD0` | 3,025 | Row r enters at `TEXHI[r]:TEXLO[r]`; the exit is the first byte of row e, patched to `RTS` and restored |
| Fill row blocks | Bank 2: even rows `$DC00-$DCFB`, landing `$DCFC`; odd rows `$DD00-$DDFB`, landing `$DDFC` | 506 | Row r at `$DC00` or `$DD00` + 3 × (r >> 1), `STA $2000+160r,X`, computed (no table); a fill record runs both chains, each with its parity's byte (section 4.2) |
| Dispatcher, hot | Bank 2 `$DE00-$DFFF` | 512 | Entered from `$F900-$FEFF`, which selects bank 2 before and bank 1 after |
| Dispatcher, rest; gather | Main card `$F900-$FEFF` | 1,536 | The gather's copies run with RAMRD on |
| Gather descriptors, copy loop | Page 1 `$0100-$018F`, `$0190-$01B4`; the stack at or above `$01C0` | 181 | Section 2 |
| Fuzz, overlay | Aux 0 `$0200-$02BF`; tables aux 0 `$0800-$0AC7` (`FUZZDARK`, `ROWLO`, `FZDIR`, `ROWHI`) | 192; 706 | Entered with RAMRD on (section 5) |
| Fuzz queue | Aux 0 `$02C0-$03FF`: `FQCOL`, `FQROW`, `FQCNT`, `FQPOS`, 80 bytes each; its count in zero page (the gather's `gdx`, free in the draw) | 320 | Written with RAMWRT on (the draw), read with RAMRD on after the strip's columns; not a video window. The replay writes it and nothing else reads it |
| Entry tables | `TEXLO` `$0900-$09A8`, `TEXHI` `$0A4A-$0AF2` | 2 × 169 | Read-only |
| Colormap page tables | `CMPA` `$0800-$0821`, `CMPB` `$0822-$0843`, indexed `CMPA-$46,Y` by `R_CMP` | 2 × 34 | Read-only |
| Colormaps | A: pages `$20-$3F` (levels 0-31), `$04`, `$05` (32, 33). B: pages `$40-$5F`, `$06`, `$07` | 17,408 | Read-only |
| Record buffer | W `$6000-$7FFF` | 8,192 | Column c's records from `COL[c]` to `COL[c+1]` |
| Column starts | `COLLO` `$1680-$1720`, `COLHI` `$1721-$17C1` | 2 × 161 | |
| Texel stage | W `$8000-$BFFF` | 16,384 | |
| Covered ranges | `CVFIRST` `$1400`, `CVEND` `$14A0`, `CVRECLO` `$1540`, `CVRECHI` `$15E0` | 4 × 160 | The replay reads them; it zeroes `CVFIRST` and `CVEND` of a strip's columns after that strip's draw pass (upstream zeroes each column's as it starts it; the state at the end is the same) |
| Fill spans | `$0F00-$13FF` (8 arrays, 3.3) | 1,280 | Not read by the replay [R `r_list65.s:550-915`]; loaded so the state is whole |
| Weapon skip | `WCLIP` `$1800`, `WPREV` `$18A0`, `WTMP` `$18E0` | 384 | Not read by the replay: only `r_frame65.s` and `r_sprite65.s` name them [R grep] |
| Zero page | `$48-$6F` | 40 | Pointers to the record, the stage, colormaps A and B (low byte = texel), row block entry and exit, saved opcode, steps and paired steps, fraction, covered range, fill bytes, the stage's pointer list; the gather and the drawers alias the draw's temporaries (39 B used [M]) |
| Scratch in main | `$17C2-$17FF` | 62 | Gather and bucket only, never in the draw pass |
| Screen | Aux 0 `$2000-$88FF` | 26,880 | The only screen bytes it writes |

**The fuzz queue.** The draw queues each `K_FUZZ` record and draws the
queue after the strip's columns, in one RAMRD window, because on F1.2.1
a RAMRD write waits for the coalescer to send every screen byte written
so far, and it scans each page it sends whole: a fuzz record drawn in
place would wait twice on scattered column bytes
(`docs/results/fuzz-timing-2026-09-30.md`). A fuzz record that a later
record of its column paints over or next to (rows `R_ROW - 1` to
`R_ROW + R_COUNT`) must be drawn in place: the loader, and in the game
the producer, writes it into W as `K_FUZZNOW` (kind 4, not an upstream
kind). A record the full queue has no room for is drawn in place too.
The record format above is otherwise upstream's (`src/native/README.md`,
"The fuzz queue").

**Batches and strips.** A frame whose packed records exceed 8,192 B is
split by column range: columns [c0, c1) whole in each batch. Drawing
column ranges one after another gives the same pixels as upstream's single
pass, because each column's records keep their order and the covered-range
cut depends only on the column. A covering record in a later batch means
every record of the column in this batch is before it, so all are cut. The
demo series reaches 10,524 B [M: `verification`], so milestone 5 exercises
two batches. Within a batch, when the stage is full the replay draws the
columns gathered so far (a strip); the next `$C073` write then waits for
their drain.

**The stage.** For each `K_TEX` or `K_TEXC` record the gather copies the
texels it steps over (a span of at most 128 B) or, when fewer, one texel a
row with the stepping done while copying. That rule needs 6,362 B,
12,816 B and 4,717 B on the three captures; whole spans merged by column
would need 21,082 B, 16,861 B and 5,303 B [M: §A.1]. As built: the
choice is by the chain's whole step (one texel a row when it is 2 or more
and the record has at most 128 rows, a span otherwise, all 128 B when the
span passes texel 127); the records in W are never written: the stage
pointer the draw uses for each texture record goes on a list at the
stage's top, so a column that does not fit the stage is walked again in
the next strip. Part A had the gather rewrite each record's source.

**The copies, in groups.** The gather queues a copy descriptor a texture
record in page 1 and runs the queue when it holds 12 (all page 1 has room
for) and at each strip's end: RAMRD on, one `$C073` write for each texel
bank the group copies from, `$C073` back to 0, RAMRD off. `NATIVE.md`
§5.2 says "open one window per texel bank", which would need a queue of a
whole strip (100 or more descriptors, 1.2 KB or more near in every RAMRD
state: neither page 1 nor the card has room). The groups cost 69-221
soft-switch writes a frame, 0.10-0.34 ms on F1.2.1 and 0.01-0.05 ms on
fastpath [M: `replay_check.py --breakdown`, phase "switches", the 15
captured frames]; one group a strip would take 7 writes a strip, about
0.01 ms.

**Texels in a2vm.** 186 of E1M1's 394 texture records, 52 of 201 in E1M3
and 140 of 189 in the demo frame point outside `$0200-$BFFF` of their bank
[M: §A.1], where RAMRD cannot reach. The milestone 5 loader relocates each
column used (128 B) into aux banks 1-4, `$0200-$BFFF`, keeping a
`K_TEXC` chain in its `K_TEX`'s bank, and rewrites the sources. The frames
use 216, 178 and 87 distinct columns (27.6, 22.8 and 11.1 KB) [M: §A.1]:
one bank each.

**a2vm image records** [R `tools/a2vm/README.md:317`]: kind 0 main
(colormaps, the table ranges only (never `$0878-$087F` or the `XTVLO` and
`XTVHI` slots), `$0C00-$1FFF`, W); kind 2 main card with `$C000-$FFFF`
addresses (bank 2 at `$D000`, and `$E000-$FFFF`); kind 3 main card bank 1;
kind 1 aux bank 0 (screen, drawers, their tables) and aux banks 1-5
(texels, records). The harness's images also fill every other byte of the
machine with `$A5` or `$5A` (section 10, problem 1). Switches: `lc_read=1
lc_write=1 lc_bank2=0`: bank 1 at `$D000`, as rule 1 has it outside the
replay; the replay selects bank 2 and back.

**The card runner** (`src/native/runner.s`, not part of the game) loads
each frame as the game will (rules 3, 4 and 8): main `$0200-$03FF` and
`$0C00-$1FFF` and the screen by CPU; main's colormaps and tables and aux
0's drawers and tables by one memory-API request of PRIVATE copies from
the frame's copies in RamWorks. `disk.py --check` checks the first
frame's load on a2vm: no video write but the screen's, `$0878-$087F`
untouched.

## 9. Cost of this map against `NATIVE.md` §1

| Item | F1.2.1, ms a frame | Pair | Label |
| --- | --- | --- | --- |
| `$D000` bank switches | about 0.005 | same | A |
| Effect ring refills | about 0.04 | same | A |
| Aux-card trig windows | 0.5-0.8 still | 0 (tables bank, about 0.1) | A on M counts |
| Records: staging, bucket pass | about 2 still, 3-3.5 demo | 0 | A; `NATIVE.md` §1 has +1-2 and +2-3 |
| Drawsegs, vissprites in RamWorks | 1-1.5 | 0 | A on M counts |
| Stage strips | 0-0.8 on the captured frames | 0 | A: one unoverlapped gather a strip |
| Copy groups of 12 descriptors (section 8) | 0.10-0.34 | 0 (no gather) | M: `replay_check.py --breakdown` |
| Fuzz as a loop, queued per strip | 0.1-0.6 on the captured frames with fuzz (the coalescer's scan of their columns); 1.4-12.6 drawn in place | up to about 1 in shadow frames | M: `replay_check.py`, a2vm with the scan (`src/native/README.md`) |

The trig windows and the RamWorks drawsegs are new against `NATIVE.md`
§1.1: +1.5 to 2.3 ms a frame on F1.2.1 standing still [A], within the
estimate's width (36-75 ms).

## 10. Open problems

1. **a2vm has no command-line write log.** The harness hook exists (`write_hook`, `a2vm.c:928-930`) but no option prints it [R `verification` §5.3; `main.c:233-350`]. Until it does, milestone 5 checks stray writes by comparing a snapshot before and after the replay byte for byte outside the allowed ranges of rule 6. Every byte the frame does not define is filled with `$A5` in one run and `$5A` in the other, so a stray store of any constant (zero included) changes a byte in at least one run; a store of the value a defined byte already holds is still unseen, as are CPU stores that the card runner makes to the forbidden bytes of rule 8 with the value they hold. Needed: `--write-log` with ranges.
2. **a2vm has no pair**, so section 6 cannot be run yet [R `memory` §8].
3. **Code sizes are assumed** for the dispatcher, math, far layer, transport, effects and platform: about 5.5 KB of the card. The build must print the spare of every region.
4. **Render window on F1.2.1.** 23,040 B of code room against a 19-26 KB hot set [A]. Milestone 7 measures the native hot set. The whole front end (milestone 7, stages A-C): 15,606 B of the 20,416 B of code room (`docs/RENDER.md` 3.8, "Stage C as built"; section 12); its load each frame, code and per-level tables, 18,176 B, 4.54 ms on a2vm's f121 model (`docs/RENDER.md` "Stage C as built").
5. **Heavy demo frames.** The stage need and packed record bytes of the demo's heaviest frames are unknown: the series dumps were deleted after decoding [R `verification` §3]. Recapture them in milestone 5.
6. **The access counts of §A.2 are sampled** (one instruction in 499): 1 to 12 samples a table for the trig tables, so ±30-100%. Exact counts need `--call-log` or a full sample run.
7. **Soft-switch and `ALTZP` costs** are the model's; milestone 0 measures them.
8. **The sound track** must agree to two changes: the player's data at `$E000-$E736` and its zero page at `$D8-$F6` (S2), and effect rings in place of 640 B buffers (S4). This map does not touch `src/sound`.
9. **Aux slot holes.** Whether any firmware writes aux `$0478-$07FF` holes is not checked; aux `$0400-$07FF` is left free.
10. **Colormap level 33.** No use was found beyond the table; if none exists, pages `$05` and `$07` free 512 B.

## 11. Checklist for the build

The build writes a manifest of every region (name, space, start, end,
phases, load method, read-only flag) from the linker maps and this table,
and fails on any breach. Spaces: `main`, `aux0`, `auxN`, `mainlc1`,
`mainlc2`, `mainlce` (`$E000-$FFFF`), `auxlc1`, `auxlc2`, `auxlce`, `zp`,
`auxzp`.

**Overlaps**

- [ ] No two regions of one space overlap, unless both are declared overlays of disjoint phases (W windows; zero-page overlays 1 and 2).
- [ ] Every linker segment lies inside its region; each region prints its used and spare bytes.
- [ ] Nothing persistent lies in an overlay: `$08-$17`, `$0300-$03EF`, `$0F00-$13FF`, `$1800-$18DF`, `$1A80-$1FFF` and the card data only.

**Forbidden ranges**

- [ ] Main `$0878-$087F`, `$4078-$407F`: no CPU store (scan the code for absolute stores; the replay test's snapshot diff).
- [ ] Main `$03F0-$03FF`: written only by boot code.
- [ ] Zero page `$42-$47`: no symbol.
- [ ] Zero page `$06-$07`: only the pair symbols.
- [ ] Zero page `$D8-$FF`: only IRQ symbols; the IRQ uses nothing else in zero page.
- [ ] Aux 0 `$9DC8-$9DFF`: always zero.
- [ ] Aux bank 127 and banks above the machine's count: never named.
- [ ] Memory API: endpoints in `$0200-$BFFF` only, never the card, zero page, stack or aux 0 `$2000-$9FFF`; PRIVATE on every main or aux-0 destination; at most about 45 KB a request (one VBL period).

**Write-expensive pages**

- [ ] Every region in main `$0400-$0BFF`, `$2000-$5FFF` and aux 0 `$0400-$0BFF` is read-only and loaded by PRIVATE.
- [ ] Regions in main `$0400-$07FF` are flagged "reload after firmware calls", and every firmware call site reloads them.

**Language card**

- [ ] Bank 2 code is called only from the replay; bank 1 code never from the replay or the IRQ.
- [ ] IRQ code and data lie in `$E000-$FFFF`, zero page `$D8-$FF` and the stack. The replay test and the S2 tests run with `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`.
- [ ] Vectors: main card `$FFFA-$FFFF`; the IRQ vector points into `$E900-$F8FF`. Pair build: aux card vectors point to the bridge.
- [ ] Alignment: squares at `$D000` with 512 B tables; the ring at a page; the write lists in one page; colormap pages at page starts; `FLOORCLIP`, `CEILCLIP`, `SOLIDCOL` at page starts.
- [ ] Row blocks: `TEXLO`/`TEXHI` give 169 entries inside `$D000-$DBD0`; every entry is an opcode; the landing is `RTS`; fill row r is at `$DC00` (even) or `$DD00` (odd) + 3 × (r >> 1), landings `$DCFC` and `$DDFC` are `RTS`.

**Windows and switches**

- [ ] Code that runs with RAMRD on lies in a card region or zero page, or in aux 0 `$0200-$03FF` when RAMRD and RAMWRT are both on with `$C073` = 0.
- [ ] On F1.2.1 every `ALTZP`-on store (`$C009`) is inside SEI … CLI straight-line code with its `$C008`, and contains no zero-page or stack access.
- [ ] Every region read inside a pair window is in zero page, the stack page or the card.

**Stack**

- [ ] The static call-graph depth of each phase plus 24 B for the IRQ stays under the budgets of section 2; the pair build's replay stays above `$0180`.

## 12. Milestone 7, stages A, B and C: the front end's regions (built)

`docs/RENDER.md` risk 13 proposed these changes to this map; stages A,
B and C of milestone 7 build them (`tools/native/rlayout.py` holds every
address and checks the overlaps; `src/native/render.cfg` fails the link
on an overflow). Sizes are the build's [M: `make -f render.mk sizes`];
the rows marked B are stage B's, C stage C's.

| Space | Range | Content |
| --- | --- | --- |
| zero page | `$00-$05` | Far layer arguments `FA_DST`, `FA_SRC`, `FA_BANK`, `FA_N` |
| zero page | `$18-$38` | Overlay 1, the BSP walk's state (33 of 42 B), live across the call of the wall setup |
| zero page | `$48-$AE` | B: overlay 2, the seg page (103 of 104 B): the four edges, a column's rows, texCol's state, the seg's flags and light, the tiers' texturemid >> 7, the batch's count, the `FSTEP` gather's scale and step |
| main | `$0200-$0277` | Bounce buffer: five segs of 24 B |
| main | `$0280-$028F` | Spill of the walk: worldbottom, the plane colormap row, viewSide's first product, the subsector record, the root |
| main | `$0290-$02BE` | B: the seg descriptor's cold part (rw_x, rw_scale, scale2, rw_distance, the light level, the normal angle, rw_offset, rw_centerangle, the texturemids, the masked columns' opening index), genColumn's words, the gather's flag |
| main | `$0310-$036F` | Render frame block (87 of 96 B): the view, its sine and cosine, the light numbers, validcount, the span and weapon-skip stamps, the vertex cache's map unit and stamp, the status, the rules of our own taken (`RULES`, RENDER.md 3.9); B: the fill bytes and their plane colours, didsolidcol, rw_scalestep (kept from wall to wall), the staging's bank and pointer; C: the sky's slot 0 (bank, address) |
| main | `$0370-$039F` | Render inputs: the player's view (x, y, angle, viewz), extralight, the fixed colormap, gamma (what milestone 10's game state keeps) |
| main | `$03A0-$03A3` | The level's counts of sectors and sides (the bridge manifest of `levelconv.py`) |
| main | `$0CA0-$0CC9` | C: `FRVIS`: the frame's weapon vissprite from the seam (milestone 8's clip pass) |
| main | `$1800-$189F`, `$18A0-$18C9` | C: `WCLIP`, `WPREV` (3.3) written by the weapon skip (`nr_wskip`); `FSSTT`, `FSSTB` (3.3) by the plane stamps (`nr_fillstamps`) |
| main | `$1A80-$1B7F` | `TEXTRANS`: `texturetranslation` as bytes |
| main | `$0DA0-$0DE1` | B: the wall setup's variables (inside 3.3's render scratch) |
| main | `$1B80-$1BFF` | `LNMAP`: `ML_MAPPED` of 2,048 lines, a bit each |
| W | `$6000-$AFBF` | Render code: 4,342 B in stage A (`RENDERW` 3,061, the render subset of `MATHW` 1,281); 15,139 B with stage B (`rwall.s` 5,374, `rseg.s` and `rrec.s` 2,941, the 13 loops 2,482); 15,606 B with stage C (`rsky.s` 273, `rframe.s` 428). Loaded each frame by the phase loader: the code's pages and the tables' pages `$AF00-$B8FF` (18,176 B) |
| W | `$AFC0-$B3FF` | `FLATCM`, per level |
| W | `$B400-$B8FF` | `TXBANK`, `TXLO`, `TXHI`, `TXWM`, `TXHT`, per level; live in the masked phase |
| W | `$B900-$B9FF` | Record batch buffer (stage B); live in the masked phase |
| W | `$BA00-$BC7F` | Node frames of the walk, 20 × 32 B (under `YHTAB` in the masked phase) |
| W | `$BC80-$BEFF` | B: `FSTEP` of the seg's columns (low, high planes), its masked texture columns (low, high) |
| W | `$BF00-$BF27` | The wall's sector frame: front sector, side, back sector |
| W | `$BF28-$BFC7` | B: each column's light distance d (`DLW`), for a seg whose light varies |
| W | `$BFC8-$BFE7` | B: the drawseg being built (`DSBUF`) |
| card bank 1 | `$DC43-$DE4C` | `far.s`: `FAR_GET`, `FAR_PUT`, the vertex-angle gather and write-back, the stamp clear, the gather's 61 B of entries (near in a read window; `vg_n` to the end of `vg_d`, `$DE10-$DE4C` today, the only bytes of `$DC43-$DFFF` render code may write: `render_check.allowed_sets` takes them from the label file); B: the `FSTEP` gather (`far_fstep`) |
| card bank 1 | `$DE4D-$DE81` | C: the phase loader (`far_wload`, segment `RLOAD`, 53 B): the render window's image from RamWorks into W, one RAMRD window. `$DC00-$DFFF` holds 642 of 1,024 B |
| aux 0 | `$0C00-$15FF` | B: the openings' low bytes (section 5) |
| aux 0 | `$A000-$BFFF` | B: the record staging (section 5), a record with its column byte |
| aux card | bank 1 `$D000-$D7FF`, `$D800-$DFF9`; bank 2; `$E000-$FFFF` | `finetangent` part 3, `viewangletox` (one plane, the correction of 4.3), part 4, `tantoangle` 0-2047 |
| RamWorks | 6, 7 | `LVSEG` (segs, 24 B), `LVMAP` (nodes 32 B at `$0200`, subsectors 4 B at `$6200`, the vertex cache's three planes of 1,536 at `$6E00`, sectors 16 B at `$8000`, sides 8 B at `$9000`, patchless bitmaps at `$B000`) |
| RamWorks | 8 | B: `RENDB`: 128 drawsegs of 32 B at `$0200`, the openings' high bytes (`OPENHI`) at `$1200` |
| RamWorks | 9, 10 | B: the record spill beyond aux 0's staging. Bank 9 reached in frame mode by 18 of the 188 frames (up to 11,052 B staged, 2,860 B of them in bank 9) [M: milestone 7, stage C]; bank 10 never reached |
| RamWorks | 11-30 | Texel slots: one 128 B slot per texture column, and the sky's 256 (7 to 19 banks a map; 19 for E1M2-E1M4) |
| RamWorks | 31 | `SEAM`: the harness's weapon-clip seam (floorclip, C: `FR_VIS`, `MM_WPOK`) and lockstep data (test builds only) |
| RamWorks | 112 | C: the render window's image (`WCODE_BANK`, at W's addresses): the code and the per-level tables (the harness's bank; the game's allocation is milestone 11's) |
| RamWorks | 116-119 | `FSTEP_TABLE`, low plane `$2000-$5FFF`, high plane `$6000-$9FFF` |

## 13. Milestone 8, stages A, B and C: the whole renderer's regions (built)

`docs/RENDER-MASKED.md` risk 14 proposed these changes to this map (its
section 1.10); stages A, B and C of milestone 8 build the ones below (the
rows marked B are stage B's, C stage C's; a stage C row replaces the
earlier rows it names)
(`tools/native/rlayout.py` holds every address and checks the overlaps;
`src/native/render.cfg` and `bucket.cfg` fail the link on an overflow).
Sizes are the build's [M: `render_check.py --sizes`, the link maps];
"proposed" rows are the design's for stages B and C, reserved now.

| Space | Range | Content |
| --- | --- | --- |
| zero page | `$18-$35`, `$48-$AC` | The masked phase's overlays (`rlayout.OVM1`, `OVM2`): the projection's state; the thing's `RTHING`, its scale record and patch header fetched whole into overlay 2; free once the walk ends (milestone 7's overlays) |
| zero page | `$18-$2D`, `$70-$7A` | The bucket pass's prototype (after the masked phase): the chunk and walk pointers, the batch list (`BK_NB`, first columns, sizes); the replay keeps to `$48-$6F` |
| zero page | `$18-$3B`, `$48-$9E` | B: the draw phase (after the sort, over the projection's bytes: `rlayout.OVD1`, `OVD2`): R_DrawSprite's scan (the vissprite, its columns, the drawseg and its slot, r1, r2), the masked range's state, the record batch's count `MRB` and the record's sequence number `RSEQ`, the clip log's pointer; R_DrawVisSprite's (upstream's `V_*` names: frac, xiscale, spryscale, E - 1, the patch, K, the rows of a post, the clip pointers), `mwCols`' (spryscale, its step, texturemid × spryscale and its step, 48 bits each, sprtopscreen + $FFFF, the step) |
| main | `$0310-$036F` | The frame block: 95 of 96 B with `SPRN`, `FZPOS`, `NVIS`, `XPUSED`, `UPFLUSH`, `RECSEQ`, `RECDROP` (the last four for stages B and C) |
| main | `$0370-$039F` | The render inputs: 43 of 48 B with each psprite's sprite, frame, sx, sy (4 B), the player's sector light, `powers[pw_invisibility]` (stage C reads them; `framestate.py` injects them now) |
| main | `$1680-$171F` | `UPOFS` (stage B's page model), in milestone 5's `COLLO` during the render |
| main | `$1720-$176F` | `FRORD`: the sort's order, vissprite indexes, until the bucket pass writes `COLLO`/`COLHI` |
| main | `$0C00-$0EFF` | After the masked phase (dead then: `FLOORCLIP`, `CEILCLIP`, `SOLIDCOL` and the render scratch after each): the bucket pass's code that runs with `RAMRD` off (`BKFAR`, 707 of 768 B in stage A; stage C's finished pass 709 B), copied there from the masked image at the phase's end by `nm_bkload` (stage C) |
| main | `$18E0-$197F`, `$1980-$1A1F` | After the masked phase: the bucket pass's `CVWHI` (over `WTMP`) and `CVWLO` (over `DSX1`, `DSX2`): each covered column's record in its batch region. (The design had them over `SOLIDCOL`; the code took `$0C00-$0EFF`) |
| main | `$1980-$1A1F`, `$1A20-$1A6F` | C (replaces the row above): after the masked phase, over `DSX1`/`DSX2` (dead then), `CVDONE` (160 B: a covered column's record found; the record's W address goes straight into `CVRECLO`/`HI`, the sequence number compared before it is overwritten) and the batch list (`BK_FIRST` 27 B, `BK_SZLO`, `BK_SZHI` 26 B each: at most 26 batches). `WTMP` (`$18E0-$197F`) is no longer written: it stays the renderer's persistent state |
| main, zero page | `$1980-$1A1F`, `$1A20-$1A7B`, `$70-$9E` | C, after its verification (2026-10-01; replaces the row above for the batch list): 26 batches were too few (whole columns only promise that two adjacent batches pass 8,192 bytes together), so `rlayout.py` proves the bound, 45 batches (`MAXB`). `CVDONE` stays over `DSX1` (bit 0 the covering record found; bit 7, game build only, the column cut at a batch's limit, RENDER-MASKED.md 6.1); the sizes `BK_SZLO`, `BK_SZHI` (45 B each) over `DSX2`; the first columns `BK_FIRST` (46 B) in zero page `$71-$9E` after the count `BK_NB` (`$70`), in the bucket pass's `$70-$AF`, which the replay leaves alone |
| main | `$0200-$02FC` | C: `BKFAR2` (253 of 256 B), the bucket pass's second `RAMRD`-off part (the batch's bring-back and fuzz marks, the scatter's record copy), copied with `BKFAR` from the masked image by `nm_bkload` at the masked phase's end; main page 2 is dead in the render |
| main | `$18A0-$18AB`, `$18B0-$18BB` | C: `WPREV` and `FRVIS`, 12 B each (patch index, texturemid, x1, x2 as two bytes, startfrac's high word, the colormap page; RENDER-MASKED.md 1.7 said 11 B and `FRVIS` per frame at `$0CA0`): both persistent, as upstream's `FR_VIS` keeps what an off-screen or absent weapon does not write and `weaponClipSame` compares it |
| W | `$BA00-$BBBF` | C: the weapon's profile entries (`WPENT`, 2 B a column), a column's post list (`WPLST`, 72 B), the psprite's patch header (`WPHB`), sprite frame (`WSFR`) and profile header (`WPHD`): over the node frames in the front end's clip pass (before the walk) and over `YHTAB` in the masked phase's weapon draw (the sprites are done) |
| W | `$B198-$B1BF` | C: `WVIS`, the weapon's vissprite for `nm_vis` (the fallback `R_DrawVisSprite`), over the seg, side and front-sector fetch buffers |
| RamWorks | 49 | C: `WPRO`: `WPIDX` (`$0200`, a patch index to its profile, `$FFFF` none) and the profiles from `$0700` (header, then 2 B a column and each column's posts, 5 B each): 26,793 B for the 28 weapon lumps of E1M7, made iff upstream's `wbMake` would fit them into an empty arena 0 |
| card `$E000` part | `$FD8D-$FE7A` | C (replaces the prototype's row): `BKNEAR` 238 B (the chunk copy with a 24-bit count, the parking and bring-back, `bstop`); `BKCARD` is gone (its routines moved to `BKFAR`/`BKFAR2`). With the replay's `RCODE` (`$F900-$FD8C`), `$F900-$FE7A` holds 1,403 B |
| main | page 1 `$0100-$01B3` | The bucket pass's chunk of the staging (180 B), between gathers |
| W | `$6000-$6592` | Both W images' shared part: `MATHW` (1,281 B) then `AUXW` (`auxlc.s`, 146 B), loaded with the front end's image; the masked load leaves it in place. The front end's code (`RENDERW`) follows, to `$9D0F` (15,632 B of W code in all) |
| W | `$6800-$8500` | The masked phase's code and constants (`MASKW`; stage A: `mmain.s` 68 B, `mproj.s` 2,615 B with 427 B of tables, to `$727A`; B: `mmain.s` 260 B, `msprite.s` 1,157, `mvis.s` 1,417 with the test builds' clip log, `mwall.s` 1,778 with `PGT`, `rrec.s` again 198: 7,425 B; C: `mpsp.s` 421 B, `wpsp.s` again 902, `nm_bkload` 48, then the bucket pass's `BKFAR` and `BKFAR2` as loaded data: `ftest` to `$8A69` plus 962 B, `$6800-$8E2B`, 9,772 B), loaded by `far_mload` from `MCODE_BANK`; its room to `$9BFF` (13,312 B) |
| W | `$9C00-$A3FF` | `DSW`: the drawsegs whose `DSX1` is not 255, 32 B each, at most 64 |
| W | `$A400-$B07F` | The vissprites, 80 of 40 B (`rlayout.VISREC`) |
| W | `$B080-$B15B` | `SPRBOUND` for the frame (220 B, from `SPRT`) |
| W | `$B160-$B18F` | Fetch buffers: the sprite frame (24 B), the listed sector's record (16 B) |
| W | `$B200-$B3FF` | `TXMP`, per level (`mtables.img`), over `FLATCM`'s end (dead in the masked phase) |
| W | `$BA00-$BAFF` | The listed sectors' copy (`SECLIST`) during the projection, in `YHTAB`'s place (stage B) |
| W | `$BA00-$BDFF` | B: `YHTAB` after the projection, two planes of 512 (`YHL`, `YHH`: the high word of E - 1 of texel row t) |
| W | `$BE02-$BEA1`, `$BEA2-$BFE1` | B: `CLIPBUF` (a drawseg's clip run: a sprite's silhouette, a masked range's `mfloorclip`), `MTCLO`, `MTCHI` (a masked range's texture columns and their drawn marks) |
| W | `$B188-$B1F7` | B: fetch buffers after the projection's: the patch header `PHB`, a seg `SEGB`, a side `SIDEB`, the front and back sectors `MSEC_F`, `MSEC_B`, a drawseg past `DSW` `DSB` |
| main | `$0E00-$0E9F` | B: `MCCLIP`, a masked range's `mceilingclip` (`sprtopclip`), over `SOLIDCOL` (dead once the walk ends; compared at the walk's end) |
| main | `$1680-$171F`, frame block | B: the page model (`UPOFS`, `XPUSED`, `UPFLUSH`) and `RECSEQ`, written by every producer through `rec_room` (both images) from `rec_start` on |
| main | `$18E0-$197F` | B: `WTMP` is persistent (RENDER-MASKED.md 2.1: a sprite drawn past x2 + 1 reads what an earlier one left); stage C moved the bucket pass off it (`CVDONE` above) |
| card bank 1 | `$DE4D-$DE8E` | The phase loader: `far_wload` and `far_pload` (a bank and a list of page runs), 66 B (53 before) |
| card bank 1 | `$DE8F-$DF31` | `mfar.s` (`MFAR`, 163 B): `far_mload` (the masked image's page list) and `far_dscopy` with its 65 B of drawseg indexes |
| card bank 1 | `$DF32-$DFDC` | B: `far_posts`, `far_postsc` (a patch column's posts in one read window) and their buffer `pt_n` .. `pt_hi` (16 posts: topdelta, length, the post's address; the only bytes of `MFAR` the masked code writes), 171 B. No `far_open` or aux-0 copy: the far layer's `far_get` reads the openings' runs (aux 0, `RENDB`). Card bank 1 holds 989 of 1,024 B, 35 left |
| card `$E000` part | `$FD8D-$FEFA` | The bucket pass's prototype (`BKNEAR` 230 B: the chunk copy, the batches' parking and return; `BKCARD` 136 B: its shared small routines): 366 of the 371 B after milestone 5's replay. With the replay's 1,165 B, `$F900-$FEFF` would hold 1,531 of 1,536 B |
| aux 0 | `$1600-$16FF` | `SPRSEC`: the listed sectors (the walk writes one byte a sector in a `RAMWRT` window) |
| RamWorks | 9, 10 | Free: the record spill moved to 51-54 |
| RamWorks | 32-47 | `SPR0`..: the patch store, lumps whole with 128-byte tails (10-14 banks a level, 457,024-659,776 B [M: `levelconv.py --all`]: 32-41 for E1M2, 32-42 for E1M1, 32-44 for E1M4, E1M5, E1M7 and E1M9, 32-45 for E1M3, E1M6 and E1M8) |
| RamWorks | 48 | `SPRT`: the scale records (`$0200`, 1,281 of 16 B), `SPRBOUND` (`$5400`, injected), `PHDR` (`$5600`, 16 B a patch, 640), `SPRFR` (`$7E00`, 24 B a frame, 400) |
| RamWorks | 49 | `WPRO`: the weapons' profiles (stage C's row above) |
| RamWorks | 50 | `RTH`: the render things, 24 B a slot from `$0200`, 768 slots |
| RamWorks | 51-54 | `RECSP`: the record spill (four banks) |
| RamWorks | 55 | `RECW`: batches 2 and 3 parked by the bucket pass |
| RamWorks | 113 | `MCODE_BANK`: the masked phase's image (`MASKW` at its addresses, `TXMP` at `$B200`) |
| RamWorks | 114 | B, harness only: routine mode's copy of W's `DSW` and vissprites (`MRTN_BANK`, loaded by the driver after the images) |
| RamWorks | 31 | B, test builds only: the clip log from `$1400` (`SEAM_CLIPLOG`, where the walk's lockstep build keeps `SEAM_SOLID`: the two builds are exclusive), 322 B a call, at most 82 |
| main | `LVMAP` sector records | Offset 13 of each sector's 16-byte render part: its thing list's head (a `RTHING` slot, `$FFFF` none) |

The cost phases of the profiling builds (`$0300`, 2 × n) now reach 18:
a2vm counts 32 (`tools/a2vm/cost.h` `COST_PHASES`, 16 before). Stage B
marks phase 4 (the sprites and masked walls, upstream's number).

## Appendix: the measurements made for this map

### A.1 Records and texels in the captures

Input: the three `R_DrawLists`-entry dumps of `verification` §3.1
(`build/native-design/caps/{e1m1,e1m3,demo-e1m7}-R_DrawLists.ram`; banks
`$00-$7F` in order). A standard-library script (session scratch, not in the
repository) walks each column's list from page `COLPAGE(c)` [R
`lists.inc:19-28`] to the free byte in `COLW` (`$02:7B0C` [M: linkmap]),
following `K_NEXT`, with the kind sizes of `lists.inc:34-72`. It reproduces
the record bytes of `verification` §2.2 (5,969, 3,806 and 2,079 B).

For each `K_TEX` (and each `K_TEXC`, with its chain's step and bank) it
steps the texel index from `TI:TF` by `SI:SF` for each row, masked to 7
bits as the blocks do [R `r_list65.s:724-732`], ignoring covered-range
cuts (an upper bound).

| Frame | Texture records | Textured rows | Σ min(span, rows) | Spans merged by column | 128 B a column | Columns | Banks | Sources outside `$0200-$BFFF` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| E1M1, still | 394 | 6,362 | 6,362 | 21,082 | 27,648 | 216 | 8 | 186 |
| E1M3, tour | 201 | 13,454 | 12,816 | 16,861 | 22,784 | 178 | 6 | 52 |
| Demo, E1M7, gametic 1128 | 189 | 25,280 | 4,717 | 5,303 | 11,136 | 87 | 3 | 140 |

The texture records' colormap bytes `R_CMP` span `$46-$64`, `$46-$5A` and
`$47-$4B` in the three frames.

### A.2 Accesses a frame to upstream's tables

Input: the instruction samples of the `PROFILE.md` runs
(`build/a2vm/interp/{still,demo}.samples`: one instruction in 499, whole,
with every read and write [R `tools/ref816/README.md:224-225`]; 24 and 40
frames). An instruction counts once per table it reads or writes; the
count is scaled by 499 and divided by the frames. Tables by their
`linkmap` ranges. As a check, colormap reads come to 6,508 a frame still,
against 6,314 measured exactly in `memory` §4.

| Table | Still: reads / writes | Demo: reads / writes | Main phases |
| --- | --- | --- | --- |
| `tantoangle` | 62 / 0 | 50 / 0 | BSP; tics |
| `finetangent` | 83 / 0 | 62 / 0 | seg |
| `finesine` part 1 | 42 / 0 | 50 / 0 | wall |
| `xtoviewangle` | 250 / 0 | 75 / 0 | seg, wall |
| `viewangletox` | 166 / 0 | 100 / 0 | BSP |
| `states` | 353 / 0 | 836 / 0 | tics |
| `FLATCM` | 62 / 0 | 12 / 0 | BSP |
| `YHTABM` | 125 / 166 | 349 / 162 | masked |
| `openings` | 21 / 1,081 | 0 / 349 | wall |
| drawsegs | 374 / 894 | 387 / 274 | wall, masked |
| `dsX1`/`dsX2` (bank `$0A`) | 416 / 104 | 624 / 50 | masked |
| vissprites | 208 / 125 | 524 / 212 | sprites, masked |
| clip arrays | 2,287 / 1,497 | 1,397 / 1,410 | wall, seg, masked |
| `solidcol` | 1,019 / 187 | 499 / 200 | BSP |
| fill spans (`FS_*`) | 1,331 / 541 | 786 / 437 | seg |
| covered ranges (`CV_*`) | 353 / 104 | 399 / 337 | masked, replay |
| `COLW` | 1,289 / 1,248 | 986 / 986 | seg, replay |
| records (bank `$1D`) | 6,383 / 4,844 | 4,491 / 4,129 | replay; seg |
