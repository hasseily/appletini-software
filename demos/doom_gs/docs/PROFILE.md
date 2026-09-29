# Measured profiles of IIgs DOOM

Measured on the reference machine (`tools/ref816`) running upstream's
release image under script, at the IIgs's own CPU rate of 2,863,636 Hz,
with the tracing of `tools/ref816/trace.c`. This file is written by
`python3 tools/ref816/profile816.py` from the traces in
`build/ref816/traces/` (`--run` makes them again); its text is
`tools/ref816/profile_template.md`, so edit that, not this. The machine is
deterministic, and the same traces give this file byte for byte.

The machine is an ideal 65816: every memory access takes one cycle, with
no wait states. It has none of the IIgs's synchronisation with the 1 MHz
Mega II side, which a real machine pays on shadowed screen writes, on the
I/O space and on banks $E0 and $E1, and no refresh cycles. The
milliseconds and frames per second below are that machine's, faster than
a real IIgs. The counts of a frame do not depend on it: every traced frame
runs 4 tics, the most the game runs in a frame (the trace counts
4 and 4 calls of `P_Ticker` a frame), so a slower
machine draws the same frames with the same work. Only the interrupts and
the music, which follow machine time, would differ.

Two scenarios:

- **Standing still in E1M1**: `coverage/newgame.script` from its note
  `still` (3 seconds after E1M1 has loaded) to `still-10s`, ten seconds of
  machine time: 24 frames.
- **The title demo**: `coverage/title.script` from its note `demo` (the
  first tic of demo3, in E1M3) to `demo-25s`: 40 frames.

A frame is one pass of the game's main loop that drew the 3D view, from
one call of `R_RenderPlayerView` to the next. It includes the game tics
run in that pass, as the frame rates of `run_script.py` do, and the
medians below equal that tool's. Below 8.75 frames a second the game runs
4 tics a frame, which it does in every frame here. Each per-frame number
is the median over the frames, with the lowest and highest values in
brackets when they differ. An instruction is an opcode fetch: MVN and MVP
count once per byte they move.

The assembler vendor's runtime library, which upstream links into the
game, is folded into the other rows and never shown separately: its code
counts in the totals and in an "others" row with code of the game, and
none of its labels is named.

## How the phases are measured

Upstream marks phases only in a build with `IIGS_PHASES`, so the trace
derives them from the call structure of the release build:

| Phase | Entries | Boundaries |
|---|---|---|
| Game tics | `P_Ticker` $04B28D | a call of an entry to its return |
| Frame setup | `vwFrame` $04D1A1, `R_FillStamps` $05D789, `R_RenderPlayerView` $03E8BE | a call of an entry to its return |
| BSP walk | `R_RenderBSPNode` $034975 | a call of an entry to its return |
| Wall setup | `R_StoreWallRange` $034000 | a call of an entry to its return |
| Seg loops | `R_RenderSegLoop` $032757 | a call of an entry to its return |
| Sprite projection | `R_AddSprites` $0350C9 | a call of an entry to its return |
| Masked drawing | `drawMasked` $03E951 | a call of an entry to its return |
| Record replay | `R_DrawLists` $059AE8 | a call of an entry to its return |
| Status bar and HUD | `ST_doPaletteStuff` $03E82B, `ST_Drawer` $03E51A, `HU_Drawer` $04405A | a call of an entry to its return |
| Menu | `M_Ticker` $040A76, `M_Drawer` $040DEB | a call of an entry to its return |
| Finish | `I_FinishUpdate` $0367FB | a call of an entry to its return |
| Interrupts | the IRQ and NMI vectors | the entry (its first push) to the return |
| Everything else |  | outside the others |

A phase starts when a JSR, JSL or JSR (a,x) lands on one of its entries
and ends when the CPU is back at the instruction after that call with the
stack pointer it had before the call. Comparing S as well as the address
keeps recursion, and `P_Ticker`'s switch to its own stack at `LOGIC_SP`,
from ending a phase early. An interrupt is a phase from its first push to
the RTI that returns to the interrupted instruction. Phases nest and the
innermost owns each
instruction, cycle and memory access: the BSP walk excludes the wall setup
it calls, which excludes the seg loops. `vwFrame` and `R_FillStamps` run
in the display loop just before `R_RenderPlayerView`, so they count in the
frame before the one they prepare. "Everything else" is the rest of the
main loop: `G_Ticker` outside `P_Ticker`, the tic commands, the sound and
music, and the display loop itself.

A disk call reaches the machine's own firmware traps, which charge 2,000
cycles and run no instruction of the game. Those cycles belong to no
phase, and have a row of their own when a frame has any: 0
cycles in the frames standing still, 0 in the demo.

The trace checks its own boundaries. Phases still open when the next frame
started: 0 standing still, 0 in the demo.
Entries reached by a jump instead of a call, over the whole runs:
0 and 0. In every frame the phases and the firmware
traps add up to the frame's instructions and cycles.

## 1. Instructions and cycles by phase

### Standing still in E1M1

| Phase | Instructions | Cycles | Share of cycles |
|---|---:|---:|---:|
| Game tics | 13,786 (12,301-14,593) | 51,624 (46,133-54,645) | 4.4% |
| Frame setup | 3,068 | 10,641 | 0.9% |
| BSP walk | 29,591 | 99,575 | 8.6% |
| Wall setup | 31,137 | 115,381 | 10.0% |
| Seg loops | 115,545 | 367,549 | 31.9% |
| Sprite projection | 5,134 | 17,880 | 1.6% |
| Masked drawing | 16,522 (16,521-16,523) | 55,465 (55,461-55,469) | 4.8% |
| Record replay | 112,577 | 389,768 | 33.8% |
| Status bar and HUD | 283 (283-18,747) | 1,107 (1,107-70,728) | 0.6% |
| Menu | 32 (29-34) | 142 (129-156) | 0.0% |
| Finish | 21 (21-1,645) | 98 (98-7,174) | 0.1% |
| Interrupts | 790 (0-1,619) | 2,790 (0-5,744) | 0.2% |
| Everything else | 2,175 (1,997-23,164) | 8,608 (7,931-88,297) | 3.1% |
| **Frame** | 331,325 (329,164-371,580) | 1,123,634 (1,115,037-1,276,579) | 100% |

A frame takes 403 ms of machine time (2.48 frames a second):
331,325 instructions and 1,123,634 cycles,
3.40 cycles an instruction. The seg loops (32%) and
the record replay (34%) take two thirds of it, the BSP
walk and the wall setup 9% and 10%. The tics
cost little (4%) while the player stands in the first room.

What "Everything else" is made of, over all the frames:

| Code (nearest label) | Instructions a frame (mean) | Share |
|---|---:|---:|
| s_sound65.s:musUpload | 7,206 | 77.3% |
| g_game65.s:G_BuildTiccmd | 316 | 3.4% |
| m_fixed65.s:umul16lo | 192 | 2.1% |
| g_game65.s:weaponKey | 180 | 1.9% |
| st_stuff65.s:updateFace | 154 | 1.7% |
| g_game65.s:G_Ticker | 144 | 1.5% |
| st_stuff65.s:ST_Ticker | 128 | 1.4% |
| d_main65.s:buildNewTiccmds | 108 | 1.2% |
| 54 others | 890 | 9.6% |

Most of it is the music: `musUpload` loads the next part of a song into
the sound chip each pass. The music is also why a few interrupts show up
(the DOC alarm that paces it).

### The title demo

| Phase | Instructions | Cycles | Share of cycles |
|---|---:|---:|---:|
| Game tics | 96,468 (45,146-257,740) | 357,427 (165,745-958,322) | 23.0% |
| Frame setup | 3,331 (2,386-148,733) | 11,472 (8,327-467,208) | 1.4% |
| BSP walk | 6,934 (2,999-48,970) | 23,056 (10,216-160,535) | 3.6% |
| Wall setup | 5,617 (1,848-44,586) | 21,364 (8,803-160,115) | 3.8% |
| Seg loops | 45,424 (36,515-144,650) | 143,498 (115,038-459,410) | 13.1% |
| Sprite projection | 3,452 (446-21,492) | 12,034 (1,581-74,181) | 1.6% |
| Masked drawing | 15,718 (204-107,887) | 51,410 (805-363,023) | 4.8% |
| Record replay | 218,962 (123,520-299,424) | 772,688 (431,433-1,051,453) | 42.3% |
| Status bar and HUD | 601 (501-383,116) | 2,166 (1,846-1,451,802) | 3.5% |
| Menu | 32 (29-34) | 142 (129-156) | 0.0% |
| Finish | 21 (21-10,536) | 98 (98-62,992) | 0.3% |
| Interrupts | 635 (0-7,723) | 2,250 (0-26,699) | 0.3% |
| Everything else | 5,066 (2,103-24,891) | 19,667 (8,368-95,814) | 2.3% |
| **Frame** | 461,187 (368,504-990,573) | 1,604,459 (1,300,824-3,579,727) | 100% |

A frame takes 615 ms (1.63 frames a second):
461,187 instructions and 1,604,459 cycles. With monsters
awake in E1M3 the tics rise to 23% of the cycles and the
replay to 42%. The first frame is the slowest: it draws the
whole status bar and view window (the status bar and frame setup phases).
The last frames are a fight at close range, where a large monster fills
the view and the masked drawing (sprites) and the replay grow.

| Code (nearest label) | Instructions a frame (mean) | Share |
|---|---:|---:|
| s_sound65.s:musUpload | 5,896 | 58.1% |
| iigs_asm.s:mvnInst | 800 | 7.9% |
| g_game65.s:G_BuildTiccmd | 319 | 3.1% |
| m_fixed65.s:umul16lo | 249 | 2.5% |
| g_game65.s:weaponKey | 180 | 1.8% |
| r_iigs65.s:slopeDiv3 | 165 | 1.6% |
| st_stuff65.s:updateFace | 164 | 1.6% |
| g_game65.s:readDemoTiccmd | 144 | 1.4% |
| 95 others | 2,233 | 22.0% |

**For the port.** Outside the replay a frame is 218,748 (216,587-259,003) instructions
standing still and 232,964 (138,663-753,117) in the demo (section 8). At the nominal 18
cycles a translated instruction and 45 million cycles a second of
ARCHITECTURE.md section 6 that is about 87 ms and 93
ms of CPU time before any far access. The seg loops, the BSP walk and the
wall setup are where translated code must be good. The replay, which the
plan hand-writes, is a third to two fifths of the IIgs's cycles, so its
kernel matters as much as the translator. The tics vary most among the
large phases (the ranges of the demo): a budget must hold for a fight, not
only for a still view.

## 2. Memory accesses

### Standing still in E1M1

| Access | Reads | Writes |
|---|---:|---:|
| Opcode and operand fetches | 674,367 (669,633-765,409) | 0 |
| Direct page | 129,006 (128,339-151,274) | 38,466 (38,229-41,557) |
| Stack | 9,307 (9,211-10,236) | 8,689 (8,571-9,602) |
| Near data, bank $02 | 27,586 (27,268-31,098) | 11,181 (11,119-12,583) |
| Far data, all other banks | 43,478 (42,967-50,277) | 19,228 (19,146-20,767) |
| I/O space and ROM | 38 (20-71) | 201 (85-4,170) |
| Vectors | 13 (0-22) | 0 |

| Bank | Holds | Reads | Writes | 8-byte lines | 64-byte lines | Pages |
|---|---|---:|---:|---:|---:|---:|
| $02 | near data (cnear, near, znear) | 27,586 (27,268-31,098) | 11,181 (11,119-12,583) | 1,014 (993-1,040) | 306 (299-313) | 126 (125-130) |
| $00 | core19save, stack, ztiny | 3,619 (3,581-3,695) | 1,381 (1,381-1,383) | 36 (31-39) | 11 (10-12) | 7 (6-7) |
| $01 | shadowed screen, bank $E1 | 1,576 (1,576-2,854) | 8,519 (8,519-9,449) | 1,188 (1,188-1,304) | 188 (188-246) | 68 (68-106) |
| $03 | cfar | 1,513 | 78 | 43 | 18 | 12 |
| $04 | cfar | 62 (52-66) | 18 (18-76) | 17 (13-20) | 8 (6-10) | 6 (4-8) |
| $05 | data_init_table | 144 | 1,442 | 84 | 25 | 11 |
| $06 | zone | 4,531 (4,303-4,650) | 622 (556-696) | 486 (456-500) | 186 (176-191) | 77 (70-78) |
| $0A | MM_BV, MM_SIGHTHINT, MM_TP_MAP, MM_WCLIP, MM_WPOK, MM_WPROF | 800 | 149 (147-149) | 101 (100-101) | 21 (20-21) | 10 (9-10) |
| $0B | MM_BRL, MM_GW_TAB, MM_NIBTAB | 0 (0-582) | 0 | 0 (0-113) | 0 (0-62) | 0 (0-28) |
| $0D | cmaps, coldfar, zfar | 6,798 (6,798-7,030) | 248 (248-364) | 250 (249-260) | 81 (81-83) | 32 (32-33) |
| $10 | MM_WAD | 68 (68-76) | 0 | 6 (6-9) | 6 (6-8) | 6 (6-7) |
| $12 |  | 0 (0-840) | 0 | 0 (0-104) | 0 (0-16) | 0 (0-5) |
| $13 | MM_SQL | 1,082 (1,042-1,114) | 0 | 317 (314-322) | 237 (234-241) | 148 (146-152) |
| $14 |  | 602 (570-642) | 0 | 220 (213-223) | 177 (172-182) | 117 (114-120) |
| $15 |  | 188 | 0 | 78 | 61 | 41 |
| $16 |  | 88 | 0 | 28 | 25 | 16 |
| $17 | MM_SQH | 1,014 (974-1,046) | 0 | 362 (357-366) | 280 (277-284) | 168 (167-172) |
| $18 |  | 610 (578-650) | 0 | 224 (217-227) | 181 (176-186) | 121 (118-123) |
| $19 |  | 238 | 0 | 99 | 81 | 57 |
| $1A |  | 138 | 0 | 49 | 43 | 31 |
| $1B | MM_FSTEP | 496 | 0 | 111 | 105 | 71 |
| $1C |  | 100 | 0 | 27 | 27 | 25 |
| $1D | MM_RECBASE, MM_VTXHASH | 6,117 | 5,975 | 792 | 186 | 160 |
| $1E | MM_RECIP | 68 | 0 | 15 | 15 | 13 |
| $1F | MM_LOGTAB | 20 (12-24) | 0 | 10 (6-11) | 9 (5-10) | 6 (3-7) |
| $20 | MM_SINE | 48 | 0 | 12 | 12 | 12 (11-12) |
| $21 | MM_B3F | 210 (196-210) | 0 | 55 (49-55) | 20 (14-20) | 11 (7-12) |
| $22 | MM_FQ, MM_GSTAMP, MM_SPRBOUND, MM_SPRISCALE, MM_SPRXSCALE, MM_SPRYSCALE, MM_VIEWSAVE | 150 | 0 | 33 | 30 | 17 |
| $23 | MM_AMKEY, MM_FS, MM_LVTAB, MM_SEGANGLE, MM_SEGSTAMP | 2,083 | 749 | 251 | 37 | 16 |
| $24 | MM_FL_ENT, MM_SEGVTX, MM_VIEWSAVE2, MM_VSTAB | 276 | 0 | 47 | 10 | 5 |
| $25 | MM_BUSY, MM_CAPMSK, MM_COLDIR | 132 | 0 | 6 | 5 | 2 |
| $27 | MM_MUSBUF, MM_SNDPCM | 171 (42-474) | 46 (21-438) | 27 (5-121) | 12 (1-23) | 6 (1-8) |
| $2A | level window, MM_TITLEPIC | 250 | 0 | 68 | 15 | 5 |
| $2E | level window | 167 | 0 | 94 | 42 | 11 |
| $30 | level window | 125 | 0 | 26 (26-40) | 9 (7-13) | 4 (4-7) |
| $31 | level window | 2,573 | 0 | 882 | 160 | 60 |
| $33 | level window | 2,138 (2,134-2,138) | 0 | 360 (358-360) | 60 (58-60) | 23 (22-24) |
| $34 | level window | 211 | 0 | 79 | 29 | 10 |
| $35 | level window | 632 | 0 | 279 | 75 | 50 |
| $36 | level window | 2,206 | 0 | 288 (288-289) | 48 (48-49) | 15 |
| $37 | level window | 1,969 | 0 | 260 | 49 | 17 |
| $6A | MM_MUSBANK | 0 (0-4,096) | 0 | 0 (0-513) | 0 (0-65) | 0 (0-17) |
| $6B |  | 0 (0-4,096) | 0 | 0 (0-513) | 0 (0-65) | 0 (0-17) |
| $E1 | screen | 0 | 0 (0-348) | 0 (0-58) | 0 (0-29) | 0 (0-19) |
| **Far** |  | 43,478 (42,967-50,277) | 19,228 (19,146-20,767) | 7,332 (7,262-8,216) | 2,592 (2,554-2,815) | 1,472 (1,445-1,573) |

| Phase | Far reads | Far writes | Bank changes |
|---|---:|---:|---:|
| Game tics | 3,278 (2,993-3,400) | 608 (540-682) | 350 (312-355) |
| Frame setup | 310 | 29 | 25 (24-25) |
| BSP walk | 3,610 | 16 | 748 (748-749) |
| Wall setup | 4,890 | 1,310 | 1,732 (1,732-1,733) |
| Seg loops | 5,527 | 6,318 | 2,315 (2,315-2,319) |
| Sprite projection | 1,116 | 0 | 321 (321-322) |
| Masked drawing | 1,455 | 872 | 339 (339-340) |
| Record replay | 22,792 | 10,025 | 24,613 (24,613-24,616) |
| Status bar and HUD | 0 (0-2,480) | 0 (0-1,075) | 0 (0-1,813) |
| Finish | 0 (0-464) | 0 (0-377) | 0 (0-726) |
| Interrupts | 200 (0-469) | 22 (0-66) | 40 (0-109) |
| Everything else | 45 (45-4,233) | 3 (3-443) | 12 (12-47) |
| **Frame** | 43,478 (42,967-50,277) | 19,228 (19,146-20,767) | 30,498 (30,451-33,033) |

### The title demo

| Access | Reads | Writes |
|---|---:|---:|
| Opcode and operand fetches | 930,612 (714,280-1,988,536) | 0 |
| Direct page | 228,634 (171,642-373,090) | 48,694 (39,132-93,193) |
| Stack | 12,526 (7,109-52,203) | 10,662 (5,705-50,247) |
| Near data, bank $02 | 32,358 (11,611-121,911) | 11,925 (4,704-39,810) |
| Far data, all other banks | 82,308 (66,894-183,241) | 31,400 (24,949-88,005) |
| I/O space and ROM | 50 (12-337) | 1,766 (10-12,850) |
| Vectors | 15 (0-104) | 0 |

| Bank | Holds | Reads | Writes | 8-byte lines | 64-byte lines | Pages |
|---|---|---:|---:|---:|---:|---:|
| $02 | near data (cnear, near, znear) | 32,358 (11,611-121,911) | 11,925 (4,704-39,810) | 820 (548-1,367) | 234 (156-387) | 102 (72-142) |
| $00 | core19save, stack, ztiny | 2,915 (1,167-8,194) | 263 (69-1,829) | 34 (26-47) | 12 (10-16) | 7 (6-10) |
| $01 | shadowed screen, bank $E1 | 1,456 (672-22,051) | 21,881 (10,839-46,790) | 2,810 (1,470-4,659) | 388 (261-586) | 101 (74-147) |
| $03 | cfar | 606 (385-2,635) | 28 (4-272) | 38 (17-187) | 19 (12-49) | 14 (11-23) |
| $04 | cfar | 188 (110-492) | 33 (6-134) | 21 (11-53) | 12 (8-24) | 9 (5-17) |
| $05 | data_init_table | 224 (16-5,558) | 663 (320-2,550) | 70 (7-163) | 27 (5-49) | 12 (4-19) |
| $06 | zone | 9,162 (7,248-17,849) | 2,160 (1,833-4,759) | 958 (826-1,350) | 384 (358-455) | 124 (117-142) |
| $07 | zone | 4,935 (844-19,674) | 456 (130-1,354) | 524 (98-1,622) | 176 (63-374) | 82 (45-139) |
| $08 | zone | 1,552 (1,424-1,973) | 90 (77-295) | 72 (58-127) | 20 (15-35) | 7 (5-14) |
| $0A | MM_BV, MM_SIGHTHINT, MM_TP_MAP, MM_WCLIP, MM_WPOK, MM_WPROF | 785 (100-3,603) | 76 (30-2,166) | 111 (25-191) | 32 (12-48) | 18 (9-27) |
| $0B | MM_BRL, MM_GW_TAB, MM_NIBTAB | 0 (0-24,695) | 0 | 0 (0-317) | 0 (0-89) | 0 (0-32) |
| $0C | MM_FL_IDX | 0 (0-444) | 0 | 0 (0-99) | 0 (0-55) | 0 (0-20) |
| $0D | cmaps, coldfar, zfar | 20,283 (8,066-26,845) | 210 (52-899) | 286 (58-435) | 107 (25-156) | 42 (12-57) |
| $10 | MM_WAD | 82 (32-13,793) | 0 | 12 (4-1,800) | 10 (2-300) | 8 (2-83) |
| $11 |  | 0 (0-1,688) | 0 | 0 (0-207) | 0 (0-27) | 0 (0-8) |
| $12 |  | 0 (0-6,622) | 0 | 0 (0-478) | 0 (0-74) | 0 (0-28) |
| $13 | MM_SQL | 953 (360-2,694) | 0 | 250 (102-792) | 184 (85-487) | 128 (64-223) |
| $14 |  | 474 (198-1,392) | 0 | 148 (70-542) | 127 (64-388) | 96 (54-200) |
| $15 |  | 121 (40-462) | 0 | 45 (20-177) | 42 (20-140) | 38 (18-91) |
| $16 |  | 118 (20-444) | 0 | 34 (7-142) | 34 (7-111) | 30 (7-78) |
| $17 | MM_SQH | 833 (264-2,722) | 0 | 250 (98-899) | 194 (88-560) | 134 (66-239) |
| $18 |  | 490 (198-1,522) | 0 | 154 (70-607) | 134 (64-434) | 102 (54-217) |
| $19 |  | 131 (38-598) | 0 | 48 (19-249) | 46 (19-197) | 44 (18-134) |
| $1A |  | 126 (20-502) | 0 | 40 (7-165) | 39 (7-130) | 34 (7-92) |
| $1B | MM_FSTEP | 320 (150-734) | 0 | 150 (19-359) | 91 (9-247) | 43 (3-102) |
| $1C |  | 31 (0-192) | 0 | 16 (0-96) | 16 (0-94) | 14 (0-86) |
| $1D | MM_RECBASE, MM_VTXHASH | 3,080 (1,760-12,436) | 3,007 (1,760-15,239) | 433 (320-1,976) | 160 (160-314) | 160 (160-169) |
| $1E | MM_RECIP | 53 (6-2,616) | 0 | 16 (2-818) | 16 (2-628) | 16 (2-256) |
| $1F | MM_LOGTAB | 470 (64-3,468) | 0 | 84 (26-222) | 40 (19-75) | 15 (10-24) |
| $20 | MM_SINE | 68 (16-168) | 0 | 14 (4-28) | 14 (4-22) | 14 (4-20) |
| $21 | MM_B3F | 1,193 (222-5,552) | 0 (0-552) | 172 (45-491) | 71 (34-123) | 34 (21-46) |
| $22 | MM_FQ, MM_GSTAMP, MM_SPRBOUND, MM_SPRISCALE, MM_SPRXSCALE, MM_SPRYSCALE, MM_VIEWSAVE | 143 (2-5,902) | 0 (0-11,226) | 32 (1-1,953) | 26 (1-249) | 22 (1-66) |
| $23 | MM_AMKEY, MM_FS, MM_LVTAB, MM_SEGANGLE, MM_SEGSTAMP | 1,062 (208-4,774) | 704 (32-2,360) | 189 (46-282) | 30 (7-45) | 13 (4-19) |
| $24 | MM_FL_ENT, MM_SEGVTX, MM_VIEWSAVE2, MM_VSTAB | 50 (32-640) | 0 | 8 (5-122) | 3 (2-27) | 2 (1-11) |
| $25 | MM_BUSY, MM_CAPMSK, MM_COLDIR | 46 (4-3,157) | 0 (0-1,596) | 3 (1-134) | 2 (1-19) | 2 (1-7) |
| $26 | MM_CAPVAL, MM_TEXTCODE | 0 (0-2,151) | 0 (0-7,148) | 0 (0-778) | 0 (0-101) | 0 (0-27) |
| $27 | MM_MUSBUF, MM_SNDPCM | 130 (12-4,923) | 60 (8-8,194) | 24 (2-1,026) | 14 (1-129) | 6 (1-33) |
| $28 |  | 0 (0-5,385) | 0 | 0 (0-674) | 0 (0-86) | 0 (0-23) |
| $29 |  | 0 (0-4,095) | 0 | 0 (0-512) | 0 (0-65) | 0 (0-17) |
| $2A | level window, MM_TITLEPIC | 78 (0-1,498) | 0 | 12 (0-75) | 4 (0-44) | 1 (0-41) |
| $2B | level window | 0 (0-973) | 0 | 0 (0-232) | 0 (0-60) | 0 (0-44) |
| $2C | level window, MM_SNDBANK | 0 (0-89) | 0 | 0 (0-45) | 0 (0-21) | 0 (0-18) |
| $2D | level window | 0 (0-10,878) | 0 | 0 (0-683) | 0 (0-140) | 0 (0-44) |
| $2E | level window | 0 (0-661) | 0 | 0 (0-145) | 0 (0-70) | 0 (0-37) |
| $2F | level window | 0 (0-629) | 0 | 0 (0-118) | 0 (0-25) | 0 (0-14) |
| $30 | level window | 452 (0-2,561) | 0 | 82 (0-247) | 37 (0-67) | 13 (0-33) |
| $31 | level window | 2,826 (0-25,224) | 0 | 176 (0-602) | 46 (0-156) | 20 (0-66) |
| $32 | level window | 0 (0-8) | 0 | 0 (0-2) | 0 (0-2) | 0 (0-2) |
| $33 | level window | 2,142 (246-7,282) | 0 | 194 (47-521) | 68 (24-151) | 38 (17-65) |
| $34 | level window | 962 (92-3,670) | 0 | 182 (17-639) | 38 (3-143) | 14 (2-50) |
| $35 | level window | 8,114 (0-21,122) | 0 | 1,114 (0-1,439) | 196 (0-260) | 66 (0-99) |
| $36 | level window | 0 (0-436) | 0 | 0 (0-140) | 0 (0-37) | 0 (0-26) |
| $37 | level window | 0 (0-24) | 0 | 0 (0-8) | 0 (0-6) | 0 (0-6) |
| $38 | level window | 0 (0-54) | 0 | 0 (0-15) | 0 (0-11) | 0 (0-11) |
| $39 | level window | 971 (0-2,785) | 0 | 128 (0-251) | 22 (0-49) | 7 (0-23) |
| $3A | level window | 96 (0-640) | 0 | 18 (0-66) | 3 (0-9) | 2 (0-4) |
| $70 |  | 0 (0-2,814) | 0 | 0 (0-352) | 0 (0-44) | 0 (0-11) |
| $71 |  | 0 (0-8,192) | 0 | 0 (0-1,025) | 0 (0-129) | 0 (0-33) |
| $72 |  | 0 (0-4,096) | 0 | 0 (0-513) | 0 (0-65) | 0 (0-17) |
| $E1 | screen | 0 | 0 (0-7,688) | 0 (0-913) | 0 (0-115) | 0 (0-30) |
| **Far** |  | 82,308 (66,894-183,241) | 31,400 (24,949-88,005) | 9,826 (7,143-22,091) | 2,980 (2,095-5,307) | 1,546 (1,087-2,432) |

| Phase | Far reads | Far writes | Bank changes |
|---|---:|---:|---:|
| Game tics | 20,981 (10,980-53,760) | 2,696 (2,083-6,850) | 3,332 (1,198-12,374) |
| Frame setup | 367 (156-21,218) | 36 (31-12,522) | 33 (27-5,937) |
| BSP walk | 644 (358-4,956) | 60 (34-392) | 161 (98-1,187) |
| Wall setup | 833 (210-6,910) | 186 (37-1,619) | 322 (79-2,608) |
| Seg loops | 2,285 (1,535-5,793) | 2,878 (1,762-8,654) | 1,359 (770-2,794) |
| Sprite projection | 729 (104-4,194) | 0 | 210 (25-1,158) |
| Masked drawing | 1,321 (28-8,609) | 1,186 (11-9,868) | 304 (4-2,391) |
| Record replay | 45,926 (24,268-64,868) | 22,924 (12,417-30,184) | 62,416 (27,051-77,793) |
| Status bar and HUD | 0 (0-63,286) | 0 (0-24,523) | 0 (0-30,628) |
| Finish | 0 (0-7,592) | 0 (0-7,148) | 0 (0-14,252) |
| Interrupts | 116 (0-1,879) | 24 (0-290) | 32 (0-520) |
| Everything else | 246 (73-8,693) | 3 (3-10,408) | 41 (16-17,178) |
| **Frame** | 82,308 (66,894-183,241) | 31,400 (24,949-88,005) | 68,890 (38,492-142,289) |

**Kinds of access.** Direct page accesses outnumber all other data
accesses together, so the plan's virtual direct page in the 65C02's own
fast memory is where most of the data traffic goes. Far data is
62,766 accesses a frame standing still and 112,788 in the demo,
19% and 24% of the instructions.

**Far banks and lines.** A frame touches 2,592 distinct
64-byte lines of far data standing still (1,472 pages) and
2,980 in the demo (1,546 pages). That is far more
than a small cache holds (the line cache of ARCHITECTURE.md section 3.4 has
64 lines of 64 bytes), and it is spread over dozens of banks: the level
window, the quarter-square tables of the multiply (banks $13-$1A), the
colormaps in $0D, the records in $1D. A cache pays only for the objects the
plan gives it (nodes, segs, sectors) and the tables need paths of their
own. Bank $02 is touched on 126 of its 256 pages a frame
standing still and 102 in the demo, a large share of the
fast memory if all of it were resident; the hot extent of section 3.3
should be chosen from these pages.

**Bank changes.** A change of bank between two consecutive far accesses
happens 30,498 times a frame standing still and
68,890 times in the demo. The replay makes 80%
and 82% of them, as upstream's order alternates between
the screen (bank $01), the colormaps ($0D), the records ($1D) and the
textures in the level window. At about 1 µs a change, upstream's order
would cost the replay tens of milliseconds a frame; the plan's replay
batches its passes by bank (read, gather, shade), which removes most of
them. Outside the replay there are 5,885 (5,838-8,420) changes a frame
standing still, about 6 ms, and 9,832 (3,300-76,522) in the demo,
about 10 ms.

## 3. Code heat

### Standing still in E1M1

| Code bytes | A frame |
|---|---:|
| Executed at least once | 19,165 (17,735-20,628) |
| 90% of the instructions | 6,231 (5,952-6,768) |
| 99% of the instructions | 13,591 (12,761-14,472) |
| 99.9% of the instructions | 18,478 (17,014-19,888) |

By section and by source file, over all the frames together (so that the
parts add up; the totals of a single frame are those above):

| Section | Executed | 90% | 99% | 99.9% |
|---|---:|---:|---:|---:|
| bspcode | 4,829 | 1,707 | 4,417 | 4,829 |
| farcode | 4,839 | 171 | 1,875 | 4,029 |
| segcode | 3,262 | 1,970 | 3,084 | 3,262 |
| logiccode | 2,259 | 232 | 1,576 | 1,986 |
| hotdraw | 1,405 | 1,018 | 1,185 | 1,405 |
| segwalls | 646 | 609 | 644 | 646 |
| hotlist | 569 | 409 | 492 | 569 |
| hotmul | 561 | 30 | 336 | 561 |
| coldcode | 436 | 0 | 74 | 418 |
| code | 913 | 0 | 36 | 402 |
| vw3code | 373 | 47 | 58 | 373 |
| irqcode | 387 | 0 | 258 | 327 |
| muscode | 512 | 12 | 121 | 142 |
| core14 | 142 | 0 | 104 | 142 |
| detailimg | 121 | 49 | 50 | 121 |
| vwcode | 97 | 0 | 0 | 97 |
| irqcold | 68 | 0 | 21 | 68 |
| paircode | 40 | 0 | 0 | 40 |
| halflist | 38 | 0 | 0 | 38 |
| maskcode | 13 | 0 | 13 | 13 |
| core5cold | 9 | 9 | 9 | 9 |
| 2 others | 61 | 14 | 61 | 61 |
| **All** | 21,580 | 6,277 | 14,414 | 19,538 |

| Source file | Executed | 90% | 99% | 99.9% |
|---|---:|---:|---:|---:|
| r_seg65.s | 3,336 | 2,208 | 3,161 | 3,336 |
| r_wall65.s | 2,705 | 1,135 | 2,418 | 2,705 |
| r_bsp65.s | 1,709 | 747 | 1,405 | 1,709 |
| drawcol.s | 1,405 | 1,018 | 1,185 | 1,405 |
| r_frame65.s | 1,290 | 64 | 276 | 1,290 |
| r_thing65.s | 937 | 0 | 867 | 937 |
| r_sprite65.s | 929 | 100 | 498 | 929 |
| r_list65.s | 768 | 458 | 542 | 768 |
| p_user65.s | 605 | 0 | 605 | 605 |
| m_fixed65.s | 593 | 30 | 354 | 593 |
| d_main65.s | 449 | 0 | 69 | 449 |
| g_game65.s | 422 | 12 | 422 | 422 |
| r_iigs65.s | 617 | 205 | 378 | 417 |
| irq65.s | 455 | 0 | 279 | 395 |
| p_pspr65.s | 360 | 0 | 359 | 360 |
| st_stuff65.s | 610 | 0 | 250 | 354 |
| p_tick65.s | 350 | 211 | 269 | 350 |
| p_enemy65.s | 468 | 0 | 31 | 337 |
| p_sight65.s | 839 | 0 | 36 | 328 |
| i_viigs65.s | 506 | 3 | 212 | 289 |
| 20 others | 2,227 | 86 | 798 | 1,560 |
| **All** | 21,580 | 6,277 | 14,414 | 19,538 |

By phase, over all the frames together:

| Phase | Instructions | Executed | 90% | 99% | 99.9% |
|---|---:|---:|---:|---:|---:|
| Game tics | 13,786 (12,301-14,593) | 3,861 | 1,837 | 3,210 | 3,689 |
| Frame setup | 3,068 | 1,905 | 1,182 | 1,831 | 1,899 |
| BSP walk | 29,591 | 2,215 | 1,133 | 1,820 | 2,152 |
| Wall setup | 31,137 | 2,418 | 1,515 | 2,219 | 2,376 |
| Seg loops | 115,545 | 2,554 | 1,323 | 2,128 | 2,428 |
| Sprite projection | 5,134 | 1,021 | 804 | 968 | 1,011 |
| Masked drawing | 16,522 (16,521-16,523) | 2,443 | 1,057 | 2,113 | 2,419 |
| Record replay | 112,577 | 2,083 | 1,102 | 1,539 | 1,844 |
| Status bar and HUD | 283 (283-18,747) | 1,448 | 596 | 985 | 1,412 |
| Menu | 32 (29-34) | 42 | 24 | 42 | 42 |
| Finish | 21 (21-1,645) | 136 | 100 | 135 | 136 |
| Interrupts | 790 (0-1,619) | 455 | 316 | 414 | 446 |
| Everything else | 2,175 (1,997-23,164) | 1,912 | 549 | 1,344 | 1,680 |

### The title demo

| Code bytes | A frame |
|---|---:|
| Executed at least once | 28,360 (22,254-41,324) |
| 90% of the instructions | 8,416 (4,584-18,247) |
| 99% of the instructions | 20,818 (14,538-33,037) |
| 99.9% of the instructions | 27,294 (21,385-39,502) |

| Section | Executed | 90% | 99% | 99.9% |
|---|---:|---:|---:|---:|
| logiccode | 12,326 | 1,164 | 5,921 | 9,611 |
| farcode | 10,825 | 1,040 | 5,010 | 8,823 |
| bspcode | 5,735 | 2,085 | 4,894 | 5,612 |
| code | 6,167 | 2,112 | 4,524 | 5,436 |
| segcode | 4,492 | 2,135 | 3,474 | 4,286 |
| hotdraw | 3,296 | 3,053 | 3,251 | 3,279 |
| segwalls | 1,902 | 1,282 | 1,600 | 1,885 |
| coldcode | 6,470 | 126 | 388 | 1,696 |
| vw3code | 1,507 | 470 | 1,018 | 1,270 |
| hotmul | 1,223 | 347 | 795 | 1,077 |
| hotlist | 770 | 447 | 583 | 718 |
| maskcode | 738 | 248 | 517 | 718 |
| logicfar | 528 | 37 | 437 | 521 |
| irqcode | 400 | 34 | 358 | 392 |
| muscode | 570 | 12 | 115 | 340 |
| segmore | 162 | 0 | 146 | 151 |
| core14 | 146 | 0 | 129 | 138 |
| vwcode | 170 | 0 | 0 | 132 |
| detailimg | 121 | 50 | 50 | 121 |
| irqcold | 89 | 0 | 68 | 89 |
| listfuzz | 51 | 51 | 51 | 51 |
| paircode | 40 | 0 | 0 | 40 |
| halflist | 38 | 0 | 0 | 38 |
| core5cold | 9 | 9 | 9 | 9 |
| 2 others | 265 | 31 | 111 | 219 |
| **All** | 58,040 | 14,733 | 33,449 | 46,652 |

| Source file | Executed | 90% | 99% | 99.9% |
|---|---:|---:|---:|---:|
| r_seg65.s | 5,874 | 3,008 | 4,597 | 5,683 |
| drawcol.s | 4,857 | 3,053 | 4,434 | 4,732 |
| p_map65.s | 4,591 | 1,052 | 2,777 | 3,751 |
| r_wall65.s | 3,344 | 1,225 | 2,479 | 2,961 |
| p_trace65.s | 3,081 | 36 | 895 | 2,406 |
| p_sight65.s | 2,317 | 1,314 | 2,136 | 2,291 |
| r_sprite65.s | 2,190 | 807 | 1,611 | 1,929 |
| s_sound65.s | 2,256 | 12 | 421 | 1,913 |
| r_frame65.s | 1,944 | 337 | 830 | 1,880 |
| p_enemy65.s | 2,260 | 358 | 1,046 | 1,801 |
| r_bsp65.s | 1,771 | 759 | 1,456 | 1,750 |
| r_thing65.s | 1,837 | 358 | 1,401 | 1,691 |
| p_mobj65.s | 1,648 | 66 | 777 | 1,455 |
| r_iigs65.s | 1,373 | 321 | 893 | 1,145 |
| p_path65.s | 1,110 | 20 | 668 | 985 |
| r_list65.s | 1,061 | 548 | 684 | 968 |
| m_fixed65.s | 1,023 | 288 | 685 | 917 |
| i_viigs65.s | 1,265 | 167 | 470 | 850 |
| p_user65.s | 864 | 11 | 814 | 830 |
| p_tick65.s | 787 | 296 | 625 | 711 |
| 30 others | 12,587 | 697 | 3,750 | 6,003 |
| **All** | 58,040 | 14,733 | 33,449 | 46,652 |

| Phase | Instructions | Executed | 90% | 99% | 99.9% |
|---|---:|---:|---:|---:|---:|
| Game tics | 96,468 (45,146-257,740) | 28,371 | 6,422 | 15,804 | 23,325 |
| Frame setup | 3,331 (2,386-148,733) | 3,097 | 826 | 2,471 | 2,813 |
| BSP walk | 6,934 (2,999-48,970) | 2,279 | 1,104 | 1,802 | 2,151 |
| Wall setup | 5,617 (1,848-44,586) | 3,852 | 1,676 | 2,491 | 2,975 |
| Seg loops | 45,424 (36,515-144,650) | 5,066 | 2,090 | 3,550 | 4,624 |
| Sprite projection | 3,452 (446-21,492) | 2,505 | 1,156 | 1,827 | 2,291 |
| Masked drawing | 15,718 (204-107,887) | 4,752 | 1,725 | 3,120 | 3,939 |
| Record replay | 218,962 (123,520-299,424) | 5,839 | 2,805 | 4,135 | 5,150 |
| Status bar and HUD | 601 (501-383,116) | 2,877 | 511 | 1,512 | 2,273 |
| Menu | 32 (29-34) | 42 | 24 | 42 | 42 |
| Finish | 21 (21-10,536) | 529 | 86 | 393 | 519 |
| Interrupts | 635 (0-7,723) | 489 | 288 | 433 | 474 |
| Everything else | 5,066 (2,103-24,891) | 4,179 | 1,042 | 2,825 | 3,657 |

**For the port.** Standing still, 19,165 bytes of code run
in a frame and 13,591 bytes account for 99% of its instructions;
in the demo 28,360 and 20,818. At the plan's
expansion of 8.5 bytes of 65C02 code for 2.7 bytes of 65816 code
(section 3.5), the 99% set is about 42 KB of native
code standing still and 64 KB in the demo, a large
part of the 90 KB of fast memory before any data. The code must rotate by
phase, as the phase windows of section 3.2 do; section 8 measures how much
of each phase a window covers. Standing still, the renderer's own sections
(`segcode`, `bspcode`, `hotdraw`, `segwalls`, `hotlist`) hold most of the
90% set. In the demo the game logic joins them (`logiccode`, `p_map65.s`,
`p_sight65.s`), and neither the tic window nor the render window covers
its phase as well as standing still.

## 4. Register widths

Over the two whole runs, from the game's entry to the end of each script:

| Register | Addresses with one value | With more than one | Most values at one address |
|---|---:|---:|---:|
| (M, X) | 38,723 | 70 | 3 |
| D | 38,432 | 361 | 515 |
| DBR | 38,019 | 774 | 149 |

| Source file | Addresses executed | More than one (M, X) | More than one D | More than one DBR |
|---|---:|---:|---:|---:|
| irq65.s | 307 | 24 | 236 | 29 |
| p_map65.s | 2,257 | 0 | 0 | 259 |
| iigs_asm.s | 217 | 42 | 78 | 126 |
| p_trace65.s | 1,439 | 0 | 47 | 147 |
| p_pspr65.s | 634 | 0 | 0 | 68 |
| w_level65.s | 807 | 0 | 0 | 67 |
| p_tick65.s | 380 | 0 | 0 | 45 |
| m_recip65.s | 229 | 0 | 0 | 18 |
| p_attack65.s | 715 | 0 | 0 | 5 |
| m_menu65.s | 662 | 0 | 0 | 3 |
| r_seg65.s | 3,497 | 1 | 0 | 2 |
| r_list65.s | 756 | 0 | 0 | 2 |
| r_thing65.s | 921 | 2 | 0 | 0 |
| i_viigs65.s | 1,758 | 0 | 0 | 1 |
| p_sight65.s | 1,261 | 0 | 0 | 1 |
| 2 others | 2,654 | 1 | 0 | 1 |

38,793 instruction addresses ran. The (M, X) widths had one
value at all but 70 of them, D at all but 361 and DBR at
all but 774. Addresses run in emulation mode:
0. Static
inference of the widths can be exact nearly everywhere, and the
exceptions are few enough to list: `build/ref816/widths.json` has every
address with its values. The interrupt handler (`irq65.s`) and the helpers
of `iigs_asm.s` run with several widths and direct pages, `p_trace65.s`
uses D as a data register, and the tic code of `p_map65.s`, `p_trace65.s`
and others runs with several data banks. Those addresses need guards or
the interpreter.

## 5. Self-modification

Every write to a byte that the run executes as code (an opcode or an
operand, before or after the write), by writing instruction and by the
label of its target.

### Standing still in E1M1

| Writing instruction | Target | Writes a frame | Bytes written |
|---|---|---:|---:|
| r_list65.s:pairReady+3 ($059C5A) | drawcol.s:texBlocks | 394 | 35 |
| r_list65.s:pairRestore+0 ($059C68) | drawcol.s:texBlocks | 394 | 35 |
| r_list65.s:fillEndW+18 ($059D70) | drawcol.s:flatBlocks | 327 | 42 |
| r_list65.s:fillEndW+36 ($059D82) | drawcol.s:flatBlocks | 327 | 42 |
| r_seg65.s:c17Setup+4 ($00B404) | r_seg65.s:c17Scale50 | 68 | 2 |
| r_seg65.s:c26LightSetup+10 ($056039) | r_seg65.s:c26RecordReady | 10 | 2 |
| r_sprite65.s:R_DrawSprite+52 ($040034) | r_sprite65.s:dsLoop | 7 | 1 |
| r_sprite65.s:R_DrawSprite+60 ($04003C) | r_sprite65.s:dsLoop | 7 | 1 |
| iigs_asm.s:nextChunk+68 ($044D02) | iigs_asm.s:mvnInst | 0 (0-29) | 1 |
| iigs_asm.s:nextChunk+76 ($044D0A) | iigs_asm.s:mvnInst | 0 (0-29) | 1 |
| r_frame65.s:R_RenderPlayerView+74 ($03E908) | r_sprite65.s:R_DrawSprite | 1 | 1 |
| r_frame65.s:R_RenderPlayerView+78 ($03E90C) | r_sprite65.s:clipIt | 1 | 1 |
| r_frame65.s:R_RenderPlayerView+84 ($03E912) | r_sprite65.s:R_DrawSprite | 1 | 1 |
| r_frame65.s:R_RenderPlayerView+88 ($03E916) | r_sprite65.s:clipIt | 1 | 1 |
| **All** |  | 1,538 (1,538-1,596) | 166 |

### The title demo

| Writing instruction | Target | Writes a frame | Bytes written |
|---|---|---:|---:|
| r_list65.s:pairReady+3 ($059C5A) | drawcol.s:texBlocks | 234 (160-552) | 158 |
| r_list65.s:pairRestore+0 ($059C68) | drawcol.s:texBlocks | 234 (160-552) | 158 |
| r_list65.s:fillEndW+18 ($059D70) | drawcol.s:flatBlocks | 79 (0-782) | 150 |
| r_list65.s:fillEndW+36 ($059D82) | drawcol.s:flatBlocks | 79 (0-782) | 150 |
| r_seg65.s:c17Setup+4 ($00B404) | r_seg65.s:c17Scale50 | 10 (2-86) | 2 |
| r_list65.s:fillEndW+18 ($059D70) | drawcol.s:texBlocks | 2 (0-142) | 1 |
| r_list65.s:fillEndW+36 ($059D82) | drawcol.s:texBlocks | 2 (0-142) | 1 |
| r_sprite65.s:fuzzColumn+70 ($045882) | drawcol.s:fuzzBlock | 0 (0-91) | 121 |
| r_sprite65.s:fuzzColumn+82 ($04588E) | drawcol.s:fuzzBlock | 0 (0-91) | 121 |
| r_sprite65.s:R_DrawSprite+52 ($040034) | r_sprite65.s:dsLoop | 4 (0-24) | 1 |
| r_sprite65.s:R_DrawSprite+60 ($04003C) | r_sprite65.s:dsLoop | 4 (0-24) | 1 |
| r_seg65.s:c26LightSetup+10 ($056039) | r_seg65.s:c26RecordReady | 6 (0-20) | 2 |
| iigs_asm.s:nextChunk+68 ($044D02) | iigs_asm.s:mvnInst | 0 (0-42) | 1 |
| iigs_asm.s:nextChunk+76 ($044D0A) | iigs_asm.s:mvnInst | 0 (0-42) | 1 |
| r_frame65.s:R_RenderPlayerView+74 ($03E908) | r_sprite65.s:R_DrawSprite | 1 | 1 |
| r_frame65.s:R_RenderPlayerView+78 ($03E90C) | r_sprite65.s:clipIt | 0 (0-21) | 1 |
| 18 other writer and target pairs |  | 2 (1-63) | 26 |
| **All** |  | 696 (361-2,842) | 896 |

Standing still, the game writes to its code 1,538 times a
frame, from 14 instructions into 8
labels; in the demo 696 times, from 32
instructions into 17 labels. Most of it is the replay
patching the ends of its row blocks (`r_list65.s` writing the
`texBlocks` and `flatBlocks` of `drawcol.s`), which the plan replaces with
a hand-written kernel. Beyond that the translator meets a short list of
patch sites, each written up to about a hundred times a frame (the seg
setup, the sprite and fuzz drawers, the MVN of `iigs_asm.s`). The writes whose byte had not run yet
are counted when it first runs; 0 standing still and
60 in the demo shared that wait with a write of another
instruction or frame and were counted with the last one.

## 6. Stack

### Standing still in E1M1

| Stack | Phase at the lowest | Bytes used a frame | Lowest S | Most bytes used |
|---|---|---:|---:|---:|
| Frame stack (top $3FFF) | Interrupts | 68 (68-75) | $3FB4 | 75 |
| Tic stack (top $1B6F) | Game tics | 28 (23-28) | $1B53 | 28 |

### The title demo

| Stack | Phase at the lowest | Bytes used a frame | Lowest S | Most bytes used |
|---|---|---:|---:|---:|
| Frame stack (top $3FFF) | Interrupts | 70 (67-86) | $3FA9 | 86 |
| Tic stack (top $1B6F) | Game tics | 72 (63-228) | $1A8B | 228 |

Bytes used are counted down from the stack's top: the frame stack from
$3FFF (`crt0.s` sets S there) and the tic stack from `LOGIC_SP`. The
lowest point of the frame stack is reached inside an interrupt, which
pushes on top of what it interrupted. The frame stack used at most
75 bytes standing still and 86 in the
demo, the tic stack 28 and 228.
ARCHITECTURE.md section 3.2 gives the soft stack 4 KB of fast memory; these
scenarios use a small part of that. Level loads, the menus and the
intermission are not measured here, so the budget should come from a run
of all the coverage scripts before it is cut.

## 7. Screen

### Standing still in E1M1

| Writes to $E1:2000-$9CFF | Bytes a frame | Changed |
|---|---:|---:|
| All | 8,519 (8,519-8,867) | 152 (150-188) |
| Directly | 0 (0-348) |  |
| By shadowing | 8,519 |  |
| Record replay | 8,519 | 152 (150-152) |
| Finish | 0 (0-348) | 0 (0-36) |

### The title demo

| Writes to $E1:2000-$9CFF | Bytes a frame | Changed |
|---|---:|---:|
| All | 21,881 (10,839-33,935) | 15,262 (7,258-32,154) |
| Directly | 0 (0-6,720) |  |
| By shadowing | 21,881 (10,839-27,550) |  |
| Record replay | 21,677 (10,839-27,550) | 15,262 (7,258-25,231) |
| Finish | 0 (0-6,720) | 0 (0-5,383) |
| Everything else | 0 (0-1,600) | 0 (0-1,540) |

Standing still, the game writes 8,519 bytes to the screen
a frame, all of them in the replay and through shadowing, and
152 of them change
the stored value. At about 1 µs a byte on the target that is
8.5 ms a frame as written, 0.2 ms if only the
changed bytes went out. In the demo it is 21,881 bytes,
15,262 of them changed: 21.9 ms against
15.3 ms. Comparing with the screen before the drain makes a
still view almost free and saves less when the view moves.

## 8. The assumptions of ARCHITECTURE.md section 6, measured

These replace the assumptions P2, P4, P6 and P8 of ARCHITECTURE.md section
6 (which stays as it was written).

| # | Assumption | Assumed | Standing still in E1M1 | Title demo |
|---|---|---:|---:|---:|
| P2 | Upstream instructions per frame outside the replay | 450,000 (300,000 to 600,000) | 218,748 (216,587-259,003) | 232,964 (138,663-753,117) |
| P2' | The same without the game tics (new) | | 204,894 (204,030-244,410) | 128,554 (53,785-622,324) |
| P2'' | Instructions of one game tic (new) | | 3,447 (3,075-3,648) | 24,117 (11,286-64,435) |
| P4 | Share of executed instructions that are native | 97% (90% to 99%) | 97.5% | 91.3% |
| P6 | Far accesses per frame outside the replay | 54,000 (12% of the instructions) | 29,949 (29,296-38,227), 14% of the instructions | 47,345 (26,208-197,293), 19% of the instructions |
| P6' | Changes of bank between them (new) | | 5,885 (5,838-8,420) | 9,832 (3,300-76,522) |
| P8 | SHR bytes per frame | 13,000 | 8,519 (8,519-8,867) written, 152 (150-188) changed | 21,881 (10,839-33,935) written, 15,262 (7,258-32,154) changed |

**P2** is the frame's instructions minus the record replay's, with the
tics the frame runs: 4 standing still and 4 in the
demo, as the calls of `P_Ticker` count them. **P2'** also leaves out the
game tics phase (`P_Ticker` and its callees), and **P2''** is one tic: a
frame's game tics phase divided by its calls of `P_Ticker`, frame by frame.
A target that runs n tics a frame needs about P2' + n × P2''. The rest of
the work of a tic stays in P2': the tic commands, `G_Ticker` outside
`P_Ticker` and the tickers of the status bar and HUD, which are in
"Everything else".

**P4** is measured as the share of each window's instructions that its
3,500 most executed instruction addresses cover, taken
over all the frames together. ARCHITECTURE.md section 3.5 sizes a phase
window at about 30 KB, "about 3,500 source instructions". The windows are
the phases of section 3.2 (the replay is hand-written and has none):

Standing still in E1M1:

| Window | Instructions a frame (mean) | Addresses executed | Hottest 1,750 cover | Hottest 3,500 cover | Hottest 7,000 cover |
|---|---:|---:|---:|---:|---:|
| Tics | 13,638 | 1,800 | 100.0% | 100.0% | 100.0% |
| Render | 200,997 | 5,601 | 83.1% | 97.2% | 100.0% |
| UI and 2D | 2,010 | 720 | 100.0% | 100.0% | 100.0% |
| Rest | 9,943 | 954 | 100.0% | 100.0% | 100.0% |
| **All but the replay** | 226,588 |  | 85.0% | 97.5% | 100.0% |

The title demo:

| Window | Instructions a frame (mean) | Addresses executed | Hottest 1,750 cover | Hottest 3,500 cover | Hottest 7,000 cover |
|---|---:|---:|---:|---:|---:|
| Tics | 111,031 | 12,835 | 79.6% | 92.1% | 98.8% |
| Render | 151,117 | 9,074 | 70.2% | 89.0% | 99.4% |
| UI and 2D | 17,529 | 1,366 | 100.0% | 100.0% | 100.0% |
| Rest | 11,645 | 1,944 | 99.9% | 100.0% | 100.0% |
| **All but the replay** | 291,322 |  | 76.8% | 91.3% | 99.3% |

**P6** counts data accesses outside the direct page, the stack, bank $02
and the I/O space, outside the replay, so it includes banks $00 and $01.
P6' counts the changes of bank between consecutive such accesses, which
the target pays at about 1 µs each.

**P8** counts the bytes written to $E1:2000-$9CFF, directly or through
shadowing, and those that changed the byte.

Measured, P2 is about half of the nominal assumption both standing still
and in the median frame of the demo. The demo's first frame, which draws
the whole status bar, goes past the assumption's upper end, and the fight
at its end comes close to it. P4 holds standing still and falls to about
91% in the demo, where the tics and the renderer both run more varied
code. Far accesses are fewer than assumed, but as a share of the
instructions they are higher than the 12% assumed. The screen bytes are
fewer than assumed standing still and more in the demo.
