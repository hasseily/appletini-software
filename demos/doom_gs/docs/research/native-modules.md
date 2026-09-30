# Upstream's modules for a native 65C02 rewrite

Status: research, 2026-09-30. Nothing here is built. This inventory
supports the owner's direction of 2026-09-30: every routine becomes native
65C02 code, with data layouts chosen for the 65C02. Upstream's SHR
techniques stay: per-column records, record replay, dithered colormaps,
fill spans and covered ranges. Music is the WAD's MUS lumps played on the
Phasor.

Every claim carries a tag:

- **[M]**: measured. I ran it (method in section 1).
- **[R place]**: read at that place. `file:line` is upstream's
  `src/iigs/` unless another path is given. `research/…` and `PROFILE.md`
  are this repository's documents, which cite upstream themselves.
- **[A]**: assumed.

The vendor runtime `cal_integer.s` is left out by name. The only things
reported about it are call counts by callee name and its placed length
(447 bytes [M]). Its execution cost is folded into the row of
`m_fixed65.s`, so no figure of its own can be derived. That is the same
rule `PROFILE.md` follows.

## 0. Summary

- **Size.** The game is 60 assembly modules plus one generated file,
  `drawcol.s` (from upstream's `tools/gendraw.py`), and 15 include files;
  `boot.s` and `loader.s` are two more modules, linked apart [M]. The game
  places 170,117 bytes of code, 38,887 bytes of initialised data and
  80,510 bytes of BSS [M]. The boot block (158 bytes) and loader
  (3,036 bytes) come on top [M]. Fixed far tables and a 22-bank level
  window sit outside the link [R `memmap.inc`]. About 830 KB of those
  tables trade space for speed [R research/iigs-renderer.md §6].
- **Live code.** The four coverage scripts (`newgame`, `title`, `tour`,
  `viewsize`) execute 98,866 of the 170,117 code bytes, which is 58% [M].
  Coverage is a lower bound on live code. The automap, the finale,
  teleporters, lifts, saves and the key-binding menus hardly run in those
  scripts (section 2).
- **Where the time goes.** Standing still, five modules take 86% of the
  cycles [M]: `r_seg65.s` 35%, `drawcol.s` 20%, `r_list65.s` 14%,
  `r_wall65.s` 11%, `r_bsp65.s` 6%. In the title demo, `drawcol.s` takes
  35%, `r_seg65.s` 15%, `p_sight65.s` 8%, `r_list65.s` 7%, `p_tick65.s` 5%,
  `r_wall65.s` 4% and `p_map65.s` 3% (77% together) [M].
- **16-bit work.** Outside the replay, 44% (standing still) to 52% (demo)
  of executed instructions do a 16-bit operation [M]. For the renderer
  front end and the game logic it is 58% to 80% per module, except
  `p_tick65.s` (32%) and `p_trace65.s` (43%). For the replay it is 0% to
  16%. On a 65C02, each 16-bit operation becomes two 8-bit
  operations, so the front end and the game logic grow the most in
  translation; the replay grows the least.
- **Self-modification.** It is concentrated in the renderer [M]. Over the
  four runs, 199 writing instructions in 10 modules patched code.
  `r_list65.s` accounts for 86 of the writers and 466,335 of the writes.
  Outside the renderer only four modules patch code: `iigs_asm.s` and
  `w_level65.s` (MVN bank operands), `p_trace65.s` and `i_viigs65.s`.
- **Vendor runtime.** It is called from 46 call sites in 18 modules [M
  static count]. Every callee is a divide or a modulo: `_UDivMod32` 14
  sites, `_UDivMod16` 11, `_Div32` 8, `_Div16` 7, `_Mod16` 6. That is
  about 4 calls a frame standing still and 9 in the demo [M]. The port
  needs its own divide routines, written from the call sites.
- **Proposed order (section 5).** Build foundations and the
  verification harness first. Then rewrite in this order: the record
  replay, the seg loops with the wall setup and the BSP walk, sprites and
  masked drawing, the level data converter and loader, the game logic,
  the platform layer, 2D. The sound work on the Phasor runs in parallel.
  The order follows the cost, and it lets each piece be checked against
  `ref816` through an interface that already exists: the column records,
  the screen, and the game state per tic.

## 1. Method

The traces that `PROFILE.md` was made from were no longer in
`build/ref816/traces/`, so I traced again, without touching
`tools/ref816` or `docs/PROFILE.md`:

1. I copied `tools/ref816/*.c *.h` into this session's scratchpad and
   changed the copy of `trace.c` in three ways. Each `heat` record gets
   two more fields: the cycles and the far data accesses of the
   instructions at that address. A new per-frame record `farb PC BANK
   COUNT` counts far data accesses by instruction and bank. "Far" means
   the trace's own definition: data outside the near bank `$02`. The copy
   builds with `-Wall -Wextra -pedantic` and no warnings.
2. I ran the scenarios of `tools/ref816/profile816.py` with its own
   `make_trace`, pointed at the copied binary and at copies of
   `memory.img` and `disk.hdv`. The scenarios are standing still
   (`newgame`, 24 frames) and the title demo (`title`, 40 frames). The
   medians came out identical to `PROFILE.md`: 331,325 instructions and
   1,123,634 cycles standing still, 461,187 and 1,604,459 in the demo
   [M]. So the patch did not change the run.
3. I ran all four coverage scripts traced from the title page to their
   end: 393 frames in all. Those runs give the code executed (the trace's
   `width` records cover the whole run), the self-modification, the
   register widths, and the work per level load.
4. The opcode at each address comes from a RAM dump at the end of the
   `newgame` run (`--dump-ram`). Places come from `build/linkmap.json`
   through `tools/ref816/codemap.py`.

Definitions used in the tables:

| Column | Meaning |
|---|---|
| Code bytes | Placed fragments of kind `text` of the module in `build/linkmap.json`. This includes tables that live in code sections. |
| Data bytes | Placed `rodata` + `data`, and `bss`, of the module. |
| Ran, bytes | Bytes of distinct instructions that ran in any of the four whole runs. Instruction length comes from the opcode and the M/X flags seen there. |
| Instructions, cycles | Per frame, **mean** over the frames, so the rows add up to the frame mean. The frame means are 339,165 instructions and 1,153,059 cycles standing still, and 503,604 and 1,762,169 in the demo. The medians quoted in the summary are those of `PROFILE.md`. An MVN counts once per byte moved. |
| 16-bit A | Share of executed instructions that ran with M = 0, pooled over the four whole runs. X = 0 (16-bit index) holds for 98% to 100% of instructions in every module except `drawcol.s` (7%) [M], so it has no column. |
| 16-bit work | Share of executed instructions whose operation is 16 bits wide. That is an accumulator or memory operation with M = 0 (for example `lda sta adc cmp inc asl pha txa`), an index operation with X = 0 (for example `ldx stx cpx inx tax phx`), or MVN/MVP. Branches, jumps, REP/SEP and XBA do not count. I take it as the best predictor of how much a module grows in 8-bit code [A]. |
| Far still, Far demo | Far data accesses per frame (mean) to banks other than `$00`, `$01` and `$02`. Banks `$00` and `$01` are left out because on the target they map to main memory and to the SHR screen. |

Per-frame means differ from medians for modules that work in bursts. The
largest differences are `s_sound65.s` (standing still: median 73, mean
7,357 instructions), `patch65.s` and `iigs_asm.s` (median 0 in both
scenarios), `i_viigs65.s` and `i_doc65.s` (demo median 344 and 116), and,
in the demo, `r_wall65.s`, `r_bsp65.s` and `r_iigs65.s` (medians 7,386,
4,770 and 4,082) [M]. The first demo frame draws the whole status bar and
view; the last frames are a close fight.

## 2. Measures by module

All figures are [M]. Modules are grouped by subsystem as in section 3.
Planes have no module of their own; section 3.3 locates them.

| Module | Code bytes | Data bytes (init + bss) | Ran, bytes | Still: instructions | Still: cycles | Demo: instructions | Demo: cycles | 16-bit A | 16-bit work | Far still | Far demo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Renderer front end** | | | | | | | | | | | |
| r_bsp65.s | 2,182 | 2,510 + 1,132 | 1,881 | 20,756 | 74,814 | 11,993 | 43,563 | 100% | 68% | 3,474 | 2,079 |
| r_wall65.s | 4,325 | 0 + 68 | 3,536 | 33,438 | 122,827 | 21,282 | 75,810 | 96% | 69% | 4,550 | 3,147 |
| r_iigs65.s | 2,057 | 8,196 + 92 | 1,391 | 8,758 | 24,128 | 10,092 | 29,522 | 100% | 69% | 1 | 186 |
| r_frame65.s | 4,855 | 0 + 280 | 4,269 | 3,393 | 12,354 | 6,044 | 20,837 | 68% | 58% | 182 | 577 |
| r_state65.s | 0 | 642 + 14,844 | 0 | 0 | 0 | 0 | 0 | - | - | 0 | 0 |
| *subtotal* | *13,419* | | *11,077* | *66,345* | *234,123* | *49,411* | *169,733* | | | | |
| **Seg loops (with planes and sprite posts)** | | | | | | | | | | | |
| r_seg65.s | 12,804 | 6,632 + 2,510 | 8,043 | 125,529 | 400,311 | 81,656 | 260,424 | 41% | 32% | 13,266 | 8,830 |
| **Sprites and masked** | | | | | | | | | | | |
| r_thing65.s | 4,724 | 0 + 54 | 3,284 | 3,555 | 13,006 | 7,082 | 25,645 | 99% | 77% | 672 | 1,572 |
| r_sprite65.s | 3,326 | 0 + 1,158 | 2,232 | 4,855 | 16,545 | 13,676 | 46,604 | 30% | 40% | 603 | 2,250 |
| *subtotal* | *8,050* | | *5,516* | *8,410* | *29,551* | *20,758* | *72,249* | | | | |
| **Record replay** | | | | | | | | | | | |
| r_list65.s | 15,775 | 41 + 717 | 6,363 | 47,576 | 157,045 | 37,266 | 122,113 | 10% | 16% | 7,854 | 5,951 |
| drawcol.s (generated) | 16,669 | 0 + 17,452 | 5,212 | 65,036 | 232,857 | 174,337 | 620,319 | 0% | 0% | 12,628 | 34,854 |
| *subtotal* | *32,444* | | *11,575* | *112,612* | *389,902* | *211,603* | *742,432* | | | | |
| **Game logic: thinkers and tables** | | | | | | | | | | | |
| p_tick65.s | 1,183 | 0 + 0 | 827 | 7,054 | 25,636 | 23,054 | 82,807 | 35% | 32% | 2,507 | 8,398 |
| p_think65.s | 328 | 0 + 18 | 250 | 88 | 400 | 105 | 474 | 100% | 76% | 0 | 7 |
| info65.s | 0 | 8,444 + 0 | 0 | 0 | 0 | 0 | 0 | - | - | 0 | 0 |
| *subtotal* | *1,511* | | *1,077* | *7,142* | *26,036* | *23,159* | *83,281* | | | | |
| **Game logic: movement, collision, sight** | | | | | | | | | | | |
| p_map65.s | 7,121 | 2 + 278 | 4,805 | 24 | 128 | 16,037 | 60,017 | 95% | 67% | 0 | 3,559 |
| p_mobj65.s | 3,067 | 31 + 84 | 2,206 | 45 | 176 | 2,224 | 9,395 | 100% | 74% | 0 | 427 |
| p_path65.s | 2,583 | 0 + 106 | 1,113 | 34 | 102 | 1,129 | 4,264 | 100% | 77% | 0 | 24 |
| p_trace65.s | 4,397 | 0 + 708 | 3,256 | 0 | 0 | 1,999 | 7,029 | 64% | 43% | 0 | 201 |
| p_sight65.s | 3,345 | 0 + 172 | 2,840 | 487 | 1,743 | 38,990 | 138,285 | 98% | 70% | 81 | 7,553 |
| p_telept65.s | 690 | 0 + 36 | 0 | 0 | 0 | 0 | 0 | - | - | 0 | 0 |
| *subtotal* | *21,203* | | *14,220* | *590* | *2,149* | *60,379* | *218,989* | | | | |
| **Game logic: monsters and combat** | | | | | | | | | | | |
| p_enemy65.s | 4,968 | 0 + 110 | 2,500 | 408 | 1,535 | 7,051 | 26,971 | 98% | 72% | 111 | 1,920 |
| p_attack65.s | 2,273 | 0 + 102 | 1,679 | 0 | 0 | 106 | 469 | 100% | 77% | 0 | 10 |
| p_inter65.s | 2,439 | 689 + 52 | 977 | 0 | 0 | 65 | 272 | 98% | 72% | 0 | 13 |
| p_spawn65.s | 2,782 | 34 + 72 | 1,584 | 0 | 0 | 108 | 420 | 100% | 79% | 0 | 30 |
| *subtotal* | *12,462* | | *6,740* | *408* | *1,535* | *7,330* | *28,132* | | | | |
| **Game logic: player** | | | | | | | | | | | |
| p_user65.s | 1,635 | 0 + 18 | 959 | 1,252 | 5,296 | 1,775 | 7,529 | 99% | 70% | 144 | 219 |
| p_pspr65.s | 2,606 | 118 + 24 | 1,466 | 618 | 2,698 | 674 | 2,881 | 100% | 74% | 8 | 53 |
| p_use65.s | 496 | 0 + 28 | 325 | 0 | 0 | 13 | 64 | 100% | 80% | 0 | 1 |
| *subtotal* | *4,737* | | *2,750* | *1,870* | *7,994* | *2,462* | *10,474* | | | | |
| **Game logic: world specials** | | | | | | | | | | | |
| p_spec65.s | 973 | 35 + 16 | 719 | 716 | 2,980 | 552 | 2,197 | 100% | 77% | 280 | 155 |
| p_doors65.s | 1,535 | 100 + 46 | 645 | 0 | 0 | 71 | 332 | 100% | 75% | 0 | 17 |
| p_floor65.s | 2,611 | 0 + 72 | 543 | 0 | 0 | 107 | 492 | 100% | 73% | 0 | 21 |
| p_plats65.s | 782 | 0 + 24 | 0 | 0 | 0 | 0 | 0 | - | - | 0 | 0 |
| p_lights65.s | 823 | 0 + 14 | 667 | 274 | 1,150 | 1,098 | 4,640 | 99% | 68% | 136 | 559 |
| p_switch65.s | 1,206 | 379 + 424 | 329 | 0 | 0 | 7 | 27 | 100% | 60% | 0 | 1 |
| *subtotal* | *7,930* | | *2,903* | *990* | *4,130* | *1,835* | *7,687* | | | | |
| **Game flow** | | | | | | | | | | | |
| g_game65.s | 2,662 | 209 + 424 | 1,822 | 864 | 3,400 | 1,007 | 3,972 | 94% | 58% | 0 | 28 |
| d_main65.s | 1,476 | 269 + 88 | 1,138 | 271 | 1,280 | 271 | 1,276 | 98% | 49% | 2 | 2 |
| m_cheat65.s | 503 | 377 + 34 | 142 | 0 | 0 | 0 | 0 | 100% | 80% | 0 | 0 |
| *subtotal* | *4,641* | | *3,102* | *1,135* | *4,680* | *1,277* | *5,248* | | | | |
| **Level loading and WAD** | | | | | | | | | | | |
| w_level65.s | 4,455 | 0 + 0 | 2,142 | 0 | 0 | 0 | 0 | 98% | 56% | 0 | 0 |
| w_wad65.s | 461 | 103 + 3,604 | 413 | 234 | 874 | 102 | 380 | 98% | 77% | 41 | 18 |
| z_zone65.s | 1,402 | 254 + 68 | 1,143 | 4 | 17 | 17 | 67 | 100% | 79% | 0 | 2 |
| p_setup65.s | 2,962 | 0 + 116 | 2,564 | 0 | 0 | 0 | 0 | 100% | 77% | 0 | 0 |
| r_data65.s | 3,574 | 326 + 8,924 | 3,227 | 86 | 379 | 75 | 328 | 100% | 65% | 12 | 10 |
| *subtotal* | *12,854* | | *9,489* | *324* | *1,271* | *194* | *775* | | | | |
| **2D** | | | | | | | | | | | |
| i_viigs65.s | 4,701 | 269 + 7,814 | 4,290 | 364 | 1,474 | 7,231 | 28,718 | 33% | 40% | 58 | 1,284 |
| patch65.s | 581 | 0 + 38 | 526 | 1,095 | 3,853 | 8,946 | 31,190 | 33% | 30% | 117 | 1,543 |
| st_stuff65.s | 2,374 | 619 + 460 | 1,751 | 624 | 2,450 | 685 | 2,721 | 100% | 62% | 1 | 3 |
| hu_stuff65.s | 426 | 227 + 98 | 412 | 42 | 181 | 160 | 693 | 95% | 56% | 0 | 4 |
| m_menu65.s | 6,753 | 2,104 + 216 | 2,762 | 32 | 142 | 32 | 142 | 67% | 63% | 0 | 0 |
| am_map65.s | 6,203 | 168 + 12,224 | 297 | 16 | 68 | 16 | 68 | 100% | 77% | 0 | 0 |
| wi_stuff65.s | 1,690 | 268 + 118 | 1,414 | 0 | 0 | 0 | 0 | 100% | 65% | 0 | 0 |
| f_finale65.s | 488 | 322 + 28 | 45 | 0 | 0 | 0 | 0 | 100% | 33% | 0 | 0 |
| *subtotal* | *23,216* | | *11,497* | *2,173* | *8,169* | *17,069* | *63,532* | | | | |
| **Sound** | | | | | | | | | | | |
| s_sound65.s | 5,476 | 327 + 2,137 | 4,007 | 7,357 | 27,967 | 6,875 | 26,239 | 5% | 41% | 1,499 | 1,334 |
| i_snd65.s | 2,027 | 0 + 0 | 1,802 | 0 | 0 | 0 | 0 | - | - | 0 | 0 |
| i_doc65.s | 578 | 0 + 10 | 530 | 84 | 327 | 4,291 | 17,650 | 7% | 34% | 0 | 1,190 |
| *subtotal* | *8,081* | | *6,339* | *7,441* | *28,294* | *11,166* | *43,890* | | | | |
| **Platform** | | | | | | | | | | | |
| crt0.s | 128 | 0 + 0 | 96 | 0 | 0 | 0 | 0 | - | - | 0 | 0 |
| i_iigs65.s | 1,558 | 445 + 674 | 816 | 36 | 164 | 36 | 164 | 100% | 57% | 0 | 0 |
| iigs_asm.s | 908 | 0 + 70 | 587 | 244 | 1,204 | 1,622 | 10,292 | 100% | 99% | 5 | 1,712 |
| irq65.s | 944 | 0 + 34 | 770 | 624 | 2,161 | 1,496 | 5,098 | 1% | 17% | 151 | 323 |
| m_config65.s | 1,012 | 13 + 1,042 | 307 | 0 | 0 | 0 | 0 | 96% | 71% | 0 | 0 |
| *subtotal* | *4,550* | | *2,576* | *904* | *3,528* | *3,154* | *15,554* | | | | |
| **Shared math and tables** | | | | | | | | | | | |
| m_fixed65.s (+ vendor divides) | 1,367 | 0 + 1,564 | 1,336 | 3,133 | 10,718 | 9,482 | 31,992 | 99% | 66% | 496 | 1,725 |
| m_recip65.s | 649 | 0 + 10 | 429 | 0 | 0 | 2,367 | 6,490 | 100% | 78% | 0 | 277 |
| tables65.s | 80 | 4,418 + 0 | 78 | 126 | 501 | 179 | 710 | 100% | 81% | 48 | 66 |
| m_random65.s | 45 | 256 + 4 | 45 | 33 | 131 | 121 | 484 | 100% | 88% | 8 | 30 |
| string65.s | 74 | 0 + 0 | 74 | 0 | 0 | 3 | 8 | 100% | 81% | 0 | 1 |
| *subtotal* | *2,215* | | *1,962* | *3,292* | *11,349* | *12,152* | *39,684* | | | | |

The rows add up to 339,165 instructions and 1,153,023 cycles standing
still, and to 503,604 and 1,762,081 in the demo. The 36 and 88 cycles a
frame that are missing are interrupt entries, which run no instruction of
a module [M].

`boot.s` (158 bytes) and `loader.s` (3,036 bytes) are separate link parts
[M]. They have no place on the target, where a ProDOS system file and the
memory API load the game.

**A level load**, from the `tour` run. It covers 8 recorded map changes,
each with its intermission and the load of the next map [M]:

| Module | Instructions a load | Cycles a load | Note |
|---|---:|---:|---|
| w_level65.s | 6.3 million | 25.4 million | B1 decoding. MVN counts once per byte moved. |
| patch65.s | 4.6 million | 16.0 million | Intermission pictures and text |
| i_viigs65.s | 2.5 million | 11.9 million | Picture blits, busy sign |
| string65.s | 2.3 million | 8.0 million | memcpy and memset |
| r_data65.s | 2.2 million | 8.5 million | Texture column tables of the map |
| iigs_asm.s | 1.0 million | 6.7 million | `IIGS_CopyHuge` (MVN) |
| w_wad65.s, p_setup65.s | 0.66 and 0.60 million | 2.5 million each | Directory, level data |

At the IIgs's 2.86 MHz, that is about 30 s of ideal CPU per map change,
intermission included [M: 838.7 million cycles over the run, 214.6
million instructions, 112 frames]. On the target, most of it becomes
memory API copies and fills.

## 3. Subsystems

### 3.1 Renderer front end

| Module | Role | Includes | Main data structures |
|---|---|---|---|
| r_bsp65.s | BSP walk (`R_RenderBSPNode`, `bspNode` recursion by JSR, 4 bytes of stack a level), `R_CheckBBox`, `R_AddLine`, `R_ClipWallSegment`; sector light and plane colours [R `r_bsp65.s:1-15`; research/iigs-renderer.md §1] | memmap, offsets | Nodes (28 bytes) and segs (18 bytes) used in place in the level window. Vertex angle cache `MM_SEGANGLE` `$23:0000` (a word a vertex) with `MM_SEGSTAMP`. `viewangletoxTable` (2,042 bytes). `FLATCM` (1,088 bytes, bank `$0D`). `SMAP`/`CMO`/`PCMO` light maps. Direct page `BSPDP` (72 bytes) [R `memmap.inc`; M link map] |
| r_wall65.s | `R_StoreWallRange`: scales through `RECIP_TABLE`, wall edges into WPAGE, calls the seg loop [R `r_wall65.s:1-8`] | dscols, memmap, offsets, wpage | Drawsegs (`_s_drawsegs`, 128 × 42 = 5,376 bytes, bank `$02`). WPAGE at `$0A00`. `saveClip` MVN copies of the clip arrays [R research/iigs-renderer.md §4] |
| r_iigs65.s | Renderer helpers: `R_PointToAngle16`/`pointAngle`, `slopeT` division, grid walk for `R_PointInSubsector`, `FixedApproxDiv` [R `r_iigs65.s:1-10`, `:547`] | offsets | `tantoangleTable` (8,196 bytes) |
| r_frame65.s | `R_RenderPlayerView`, `setupFrame`, frame-start clears, `R_DrawMasked` (sprite sort, masked mid textures `mwCols`, player sprites), `vwFrame` view sizes, sky patch [R `r_frame65.s:1-8`] | dscols, lists, memmap, mul, offsets, viewwin, wpage | `FR_ORDER` (160 bytes), view window table `VWTAB` |
| r_state65.s | Data only: the renderer's shared state [R `r_state65.s:1-8`] | offsets | Drawsegs 5,376, `openings` 5,120, `vissprites` 3,360 (80 × 42), `floorclip`/`ceilingclip` 320 each, `screenheightarray`, `negonearray` [M link map] |

**Hot routines [M].** `r_bsp65.s`: `sl0` 17%, `scan0` 11%, `bspSub` 11%,
`boxAngles`, `scan1`, `checkBox`. `r_wall65.s`: `qmul` 20% (23% in the
demo), `scaleFast` 11%, `textured` 10%, `edgeP`, `saveClip`.
`r_iigs65.s`: `pointAngle` 29%, `slopeT` 14%. `r_frame65.s`:
`R_RenderPlayerView` (the clears) 40%, `drawMasked`, `wclipSprite`,
`sortSprites`.

**Far data [M].** `r_bsp65.s` reads the level window (bank `$33` in E1M1:
46% of its far accesses), bank `$23` (vertex angles, fill spans) and the
zone (`$06`). `r_wall65.s` reads the SQL/SQH square tables (`$13`-`$18`),
the level window and the zone. By the trace's definition, 33% of its far
accesses go to bank `$00`, where WPAGE is [R `wpage.inc:1-4`].

**Self-modification [M].** `r_frame65.s` patches two bytes of
`R_DrawSprite` and two of `clipIt` in `r_sprite65.s` once a frame, and
`mwS2a`/`mwS2b` in its own masked-wall column code.

**Vendor calls.** `r_iigs65.s` has 2 sites of `_UDivMod32` and
`r_wall65.s` has 1 of `_Mod16` [M static]. Neither was called in the
recorded frames [M].

**Strategy: redesign allowed, outputs must match.** The output is the
column records (section 3.5) and the drawseg and clip arrays that
sprites read. The front end can be rewritten with 65C02-friendly
layouts: split low/high byte arrays, 8-bit indices for columns 0-159, and
pointers as a 16-bit offset plus a bank byte. The records it produces must
be identical in rows, texel positions, steps and colormap pages, in the
same order within each column.

**What makes it hard.**

- The arithmetic is 16.16 fixed point: 68% to 69% of instructions do
  16-bit work [M]. Upstream multiplies through 512 KB of quarter-square
  tables. Exact products are exact whatever the method, so a 65C02
  multiply built from 8 × 8 quarter squares (2 KB in fast memory [A]) is
  free to replace them.
- The reciprocal and texture-step tables (`RECIP_TABLE` 64 KB, `FSTEP`
  128 KB) and `FixedApproxDiv` are approximations [R `m_recip65.s:1-10`,
  `r_iigs65.s:547`]. Matching them bit for bit means keeping the same
  tables, now in RamWorks and read at random, or recomputing the same
  truncated values.
- Edge stepping keeps 8 bits of fraction and "can be off by one after
  many columns" [R `r_seg65.s:171-174`]. That behaviour must be
  reproduced, not fixed.
- Zero page is scarce: `BSPDP` (72 bytes), WPAGE (about 250) and `DC_*`
  (44) all live in direct pages today [R research/iigs-renderer.md §4].

### 3.2 Seg loops

| Module | Role | Includes | Main data structures |
|---|---|---|---|
| r_seg65.s | `R_RenderSegLoop`: 13 loop variants for top, bottom and one-sided tiers and ceiling/floor marks, via `JMP (varTab,X)`. Per column it produces `K_TEX` records (`texCol`, `tierDraw`, `texRec`) and `K_FILL` records (`ceilFill`, `floorFill`), and updates the clips. Also sky columns, `R_DrawVisSprite` and `visPost` (sprite posts, section 3.4), constant-row multiply kernels (C16/C17/C19/C26) and the view-size variants [R `r_seg65.s:1-11`; research/iigs-renderer.md §1, §2.9] | lists, memmap, mul, offsets, segvar (13 times), viewwin, wpage | WPAGE `$0A00`. Records bank `$1D`. `COLW` write pointers. Fill spans and covered ranges `FS_*`/`CV_*` at `$23:EF00`. Texture directory `MM_COLDIR` `$25:0000` (256 × 4 bytes). `finetangentTable_part_3/4` (6 KB). `YHTABM` (1,026). C19 save tables (1,409). `FSTEP` `$1B`-`$1C` [M link map; R `memmap.inc`] |
| segvar.inc | One loop body, stamped out 13 times with `#define`: 8-bit A, 16-bit X = 2 × column [R `segvar.inc:1-8`] | - | - |
| wpage.inc | The WPAGE layout; `$00-$2B` are the drawers' `DC_*` inputs [R `wpage.inc:1-4`] | - | - |
| segclip.inc | Clip-only columns of the small views. **Not included by any file in this commit** [M grep] | - | - |

**Measures [M].** Standing still, 92% of `r_seg65.s`'s instructions run
in the seg-loop phase and 8% in masked drawing (sprite posts). Its time is
spread over many labels: `c26Store`, `tcExact`, `fillFloor`, `tierDraw`,
`visPost`, `v12col`, `R_RenderSegLoop`, `c26RecordReady` and `tcSpan`
each take 3% to 5%. That is the signature of a wide, flat inner loop. Far
data is 44% records (bank `$1D`), 15% bank `$23`, and the rest code-bank
tables and the level window. `r_seg65.s` runs 8,043 of its 12,804 code
bytes in the four runs.

**Self-modification [M].** Across the runs, 33 writing instructions patch
29 targets. Per seg: `c17Setup` writes into `c17Scale50`, 68 times a frame
standing still [R `PROFILE.md` §5], and `c26LightSetup` writes the
operand of `c26RecordReady` [R research/iigs-renderer.md §2.9]. On a view-size
change, `c19Install`/`c19Restore` copy kernels, and `ssPatch`/`ssMode`
and `c16Set`/`c17Mode` retarget loop exits. In the other direction,
`r_list65.s` (`R_SegHalf`, `onePatch`, `tPatch`) and `r_thing65.s`
(`vcQ`, `vcHalf`, `vc3`, `hvSet`) patch `r_seg65.s`.

**Vendor calls.** None [M static].

**Strategy: redesign allowed, outputs must match.** This is the second
largest cost standing still (35% of cycles [M]) and needs hand-written
65C02 loops. The contract is the same as for the front end: identical
records per column, identical clip arrays, identical fill-span and
covered-range state. The 13 variants can become 65C02 variants generated
by a host script. The per-seg patches (`c17`, `c26`) are cheap on a 65C02
and can stay as self-modification.

**What makes it hard.**

- Only 32% of instructions do 16-bit work [M], but the loop keeps several
  24-bit edges and steps, and X = 2 × column indexes word arrays. The
  65C02 wants X = column and split byte arrays.
- Records go to a 64 KB bank (at most 53,760 bytes [R research/iigs-renderer.md
  §2.7]). On the target that is a RamWorks bank, written through the
  proposed `$C069` write bank, or kept in fast memory if the budget
  allows [A].
- The texture step comes from the 128 KB `FSTEP` table [R `r_seg65.s:1926-1943`
  via research/iigs-renderer.md §4]. `FSTEP` is read about 360 times a
  frame in the demo [M: bank `$1B` is 4% of 9,011]. That is fine from
  RamWorks, but it must be bit-exact.

### 3.3 Planes

Planes have no module of their own. They are flat colours per sector
plane, drawn as column fills, with no visplanes or spans [R
research/iigs-renderer.md §0, §2.8]. The code sits in four places:

| Part | Where |
|---|---|
| Plane colours | `bspSub` in `r_bsp65.s` (`FLATCM[cm*32 + flat]`) [R research/iigs-renderer.md §2.8] |
| Fill records | `ceilFill`, `floorFill`, `fillFloor`, `fillCeil`, `visFill`, `fillBytes` in `r_seg65.s`, and the `PLANEFILL` macro inlined into the loops |
| Fill spans and stamps | `R_FillStamps`, `fillCut`, `cutFill` in `r_list65.s`; `FS_*` at `$23:EF00` |
| Fill replay | `fillEndW`, `drawFill`, `rlFillJump` in `r_list65.s`; `flatBlocks` in `drawcol.s` (4 bytes and 8 cycles a row) |

**Measures [M], by label, a lower bound because `PLANEFILL` is inlined.**
Standing still: 32,688 instructions and 114,616 cycles a frame, 10% of
the frame. In the demo: 24,409 and 86,491, 5%.

**Strategy: redesign allowed, outputs must match.** Keep the fill spans
and stamps; they avoid rewriting unchanged floor bytes, and each byte
saved is also a byte the SHR mirror does not have to drain. The fill row
block becomes `sta row,x` pairs with the even/odd bytes in A and X or Y
[A].

**What makes it hard.** The stamps depend on the frame before (the byte
reuse survives gun flashes because plane colours ignore `extralight` [R
research/iigs-renderer.md §2.5]). A native version must reproduce the
same "what the previous frame showed" state. If that state is wrong, a
fill is skipped over rows that do not hold its bytes, and stale pixels
stay on the screen.

### 3.4 Sprites and masked

| Module | Role | Includes | Main data structures |
|---|---|---|---|
| r_thing65.s | `R_AddSprites`, `R_ProjectSprite` with scale tables for tz = 4..1280 [R `r_thing65.s:1-15`] | info, memmap, offsets, viewwin, wpage | `vissprites` (in `r_state65.s`). Sprite scale tables `$22:0000`-`$22:7FFF` (`SPRXSCALE`, `SPRYSCALE`, `SPRISCALE`, `FQ`, `SPRBOUND`). Sprite frames and patches in the level window [R `memmap.inc`] |
| r_sprite65.s | `R_DrawSprite` (clip against drawsegs through `dsX1`/`dsX2`), shadow sprites (`K_FUZZ`, `fuzzColumn`), `R_DrawMaskedColumn`, weapon profiles (`wdProf`, `wbMake`) [R `r_sprite65.s:1-8`] | dscols, lists, mul, offsets, viewwin, wpage | `SC_TAB` (1,024). `dsX1`/`dsX2` byte columns in `MM_BV` (`$0A:B500`). Weapon profile arenas `$0A:C800` + `$0A:D000-$E3FF`, `$0A:ED00-$FEFF`. `FUZZ_DARKEN` `$01:A000` [R `dscols.inc`, `memmap.inc`, research/iigs-renderer.md §2.11] |
| (r_seg65.s) | `R_DrawVisSprite`, `visPost`: one `K_TEX` record per visible post [R research/iigs-renderer.md §2.11] | | `YHTAB` |
| (r_frame65.s) | `drawMasked`, `sortSprites`, `mwCols` (masked mid textures, `K_TEXC`), `vrPost`/`vrCol8` | | `FR_ORDER` |

**Measures [M].** Small standing still (8,410 instructions in these two
modules). In the demo: 20,758 instructions and 72,249 cycles, plus the
sprite posts in `r_seg65.s` and the masked code in `r_frame65.s`. The
masked-drawing phase as a whole ranges from 805 to 363,023 cycles a frame
[R `PROFILE.md` §1]. Hot labels: `dsLoop` (drawseg scan, 40% standing
still), `clipIt`, `wdProf` (weapon, 19% in the demo), and `txDone` in
`r_thing65.s` (58%).

**Self-modification [M].** `r_thing65.s` has 49 writing instructions (the
most after `r_list65.s`). They patch sign and offset bytes of its own
projection code (`gTX`, `gTZ`, `gTZsum`, `gGZcheck`), the post loop of
`r_seg65.s` (`visNext`, `visDone`), `visColD` in `r_frame65.s` and
`wdDraw` in `r_sprite65.s`. `r_sprite65.s` patches `dsLoop` (7 writes a
frame) and the exit of `fuzzBlock` in `drawcol.s`.

**Vendor calls.** None [M static].

**Strategy: redesign allowed, outputs must match.** The same record
contract as sections 3.1 and 3.2, plus the covered ranges (`CV_*`) and the
weapon skip (`WCLIP`), which change what the replay paints.

**What makes it hard.** The worst case is the one that matters: a large
monster at close range. The demo's last frames reach 108k instructions of
masked drawing [R `PROFILE.md` §1]. The weapon profiles are an elaborate
cache (arenas in bank `$0A`) that needs a 65C02 layout. The sprite scale
tables (32 KB) are an approximation of a division and must stay
bit-exact [R `r_thing65.s:1-6`].

### 3.5 Record replay

| Module | Role | Includes | Main data structures |
|---|---|---|---|
| r_list65.s | `R_DrawLists`: for each column 0..159, walk its record list and dispatch `K_TEX`/`K_TEXC`/`K_FILL`/`K_FUZZ`/`K_OVL`/`K_NEXT` to the row blocks. Covered-range cuts. Record allocation (`recTex`, `fillCol`, `newPage`, `flush`). View-size variants (half, third, quarter, "pair" detail image builder `pairMake`) [R `r_list65.s:1-13`; research/iigs-renderer.md §1, §2.7-2.9] | lists, offsets, viewwin, wpage | Records bank `$1D` (160 home pages + 50 extra pages, a record ends by offset 254). `COLW`, `colOrder` (320 bytes each). `TEXLO`/`TEXHI` row-block entry tables at `$01:1E41`. Two borrowed exit vectors at `$0565`/`$0765` [R `lists.inc:1-30`, `:180-185`] |
| drawcol.s | Generated by upstream's `tools/gendraw.py`: `texBlocks` (a 15- or 19-byte block a row), `flatBlocks` (4 bytes a row), `fuzzBlock` (217 rows × 10 bytes), images for other detail levels and view sizes (`detailimg`, `thirdimg`), plus the colormaps `iigs_shrcmapA/B` (2 × 8,704 bytes, bank `$0D`) as BSS [M link map; R research/iigs-renderer.md §2.9] | - | Colormaps `$0D:4600`. Screen `$01:2000` shadowed to `$E1` |
| lists.inc | Record layouts and kinds, `COLPAGE`, `FS`/`CV`/`WCLIP` layout [R `lists.inc:1-30`] | memmap | - |
| viewwin.inc | View sizes and their kept rows and columns [R `viewwin.inc:1-14`] | memmap | - |

**Measures [M].** 112,612 instructions and 389,902 cycles a frame standing
still (34%), and 211,603 and 742,432 in the demo (42%). `texBlocks` alone
is 92% to 94% of `drawcol.s`. The row blocks run with 8-bit A and index:
0% 16-bit work in `drawcol.s`, and 16% in `r_list65.s`. Far data in
`drawcol.s` is 39% the screen buffer (`$01`), 29% colormaps (`$0D`) and
the rest texels in the level window. In `r_list65.s` it is 55% records
(`$1D`). `r_list65.s` runs 6,363 of its 15,775 bytes; the rest is the
other view sizes and details.

**Self-modification [M].** This is the densest in the game. 86 writing
instructions in `r_list65.s` made 466,335 writes over the four runs.

- Per record: `pairReady` puts `$6C` (`JMP (abs)`) on the first byte
  after the last row and `pairRestore` puts back the opcode
  [R research/iigs-renderer.md §2.9], 394 times a frame standing still
  [R `PROFILE.md` §5]. `fillEndW` does the same with
  `RTS` for fills, 327 times a frame.
- Per view size or detail change: `pairSetDetail`, `pairPatch`,
  `R_SetThird` and the `nr*` routines rebuild the row image. In the small
  views the image written into `texBlocks` itself patches `texBlocks`
  (5 instructions, 18,319 writes, `viewsize` run only).
- `r_list65.s` also patches `r_seg65.s`, `r_frame65.s:vwFrame` and its own
  dispatch (`drawSel`, `oneDispatch`, `onePage`).

**Vendor calls.** None [M static].

**Strategy: redesign allowed, outputs must match.** This is the first
hand-written kernel: records in, screen bytes out. The contract is
exactly `lists.inc`. The first native replay can read upstream's record
format unchanged, so it runs behind any producer: `ref816` record dumps,
the interpreter, or native producers later. The records can move to a
65C02 layout (split fields, 8-bit column index) once the producers are
native. The row blocks should be regenerated by our own generator, not
from `gendraw.py`, which is GPL upstream code.

**What makes it hard.**

- **Three 64 KB spaces in one inner loop.** Each texel is
  `lda [SRC],y`, a 24-bit pointer into the level window. Each colormap
  lookup is `lda [CMA]`. The store goes to the screen buffer
  [R research/iigs-renderer.md §4]. On the 65C02, all three must be
  visible in one 64 KB map. With the proposed `$C069` pair, data reads of
  `$0200-$BFFF` come from the texture's RamWorks bank, and writes go to
  the SHR bank. The colormaps must then sit where reads are not
  redirected: the language card, 16 KB [R docs/firmware/zpbank-spec.md
  §0]. They are 17,408 bytes [M], so 1 KB over. Some colormap pages have
  to be dropped or merged, or kept per level [A].
- **The SHR mirror.** Each SHR store leaves a byte for the motherboard
  mirror. Draining takes about 0.98 µs a byte, and today the next `$Cxxx`
  access waits for the drain (fact given in the task). A frame writes
  8,519 screen bytes standing still and 21,881 in the demo, most of them
  in the replay [R MILESTONES.md; `PROFILE.md` §7]. That is 8.3 ms and
  21.4 ms of drain. The replay must make no `$Cxxx` access while the drain
  runs, and nothing else in the frame may wait on it.
- **Fine-grained self-modification.** It stays cheap on the 65C02 (one
  `sta abs` a record) as long as the row blocks sit in fast memory.
  TURBO's page cache holds only BRAM pages [R research/appletini-hardware.md §1].

### 3.6 Game logic

All modules here say "with the same results" as the Doom8088 C code
[R each file's header, lines 1-7]. The reference for the port is
upstream's behaviour, which includes its approximations: sight side tests
on the whole parts of coordinates [R `p_sight65.s:5`], `FixedApproxDiv`
[R `r_iigs65.s:547`], and `TICSTEP`, where the demos play as recorded only
with `TICSTEP` = 1 [R `tics.inc:1-9`].

| Area | Module | Role | Main data structures |
|---|---|---|---|
| Thinkers | p_tick65.s | `P_RunThinkers` (DBR = the thinker's bank, fields by `abs,X`), `P_MobjThinker`, `P_SetMobjState`. Function calls by `JML [FN_P]` [R `p_tick65.s:100-118`, `:533`] | Thinker list. `mobj_t` 120 bytes with a cached thinker kind in byte 11 [R research/iigs-platform.md §3] |
| | p_think65.s | Thinker list, `P_Ticker`, the tic stack at `LOGIC_SP` [R header; research/iigs-platform.md §3] | - |
| | info65.s | Data only: `states` (314 × 16 = 5,024), `mobjinfo` (50 × 64 = 3,200), `sprnames` [M link map; R `info65.s:1-7`] | - |
| Movement | p_map65.s | `P_CheckPosition`, `P_TryMove`, the line and thing iterators, blockmap walks, sector node lists, `P_TeleportMove` [R header] | Blockmap and reject in place in the WAD. `MM_BRL` in `$0B` |
| | p_mobj65.s | `P_XYMovement`, `P_ZMovement`, slide moves [R header] | - |
| | p_path65.s | `P_PathTraverse`, `P_AproxDistance`, intercepts [R header] | `MM_GW_TAB` `$0B:0000`, `MM_GSTAMP` |
| | p_trace65.s | `PIT_AddLineIntercepts`, `PIT_AddThingIntercepts`, `P_InterceptVector` with its `FixedDiv`. Uses D as a data register (7 `tcd` [M grep]; `PROFILE.md` §4) [R header; `p_trace65.s:431`] | `intercepts` (640 bytes) |
| | p_sight65.s | `P_CheckSight` over the BSP with log-based side tests [R header] | `LOGTAB` `$1F`. Per-map node and line logs in `$21`. `MM_SIGHTHINT` `$0A:0000` |
| | p_telept65.s | Teleporters [R header] | - |
| Monsters | p_enemy65.s | Monster AI: `A_Look`, `A_Chase`, `lookForPlayers`, the attacks. The actor is kept in `_Dp+8` [R `p_enemy65.s:1-6`; `actor.inc`] | - |
| | p_attack65.s | Hitscan: `P_AimLineAttack`, `P_LineAttack` and their traversers [R header] | - |
| | p_inter65.s | Pickups, damage, deaths [R header] | - |
| | p_spawn65.s | `P_SpawnMobj`, `P_RemoveMobj`, missiles, map things. A fixed pool of mobjs [R header; research/iigs-platform.md §4.6] | Mobj pool in the zone |
| Player | p_user65.s | `P_PlayerThink`, movement, view height, bobbing [R header] | `_g_player` (155 bytes) |
| | p_pspr65.s | Weapon states and actions [R header] | `weaponinfo` (108) |
| | p_use65.s | `P_UseLines` [R header] | - |
| World | p_spec65.s, p_doors65.s, p_floor65.s, p_plats65.s, p_lights65.s, p_switch65.s | Sector specials, animated and scrolling walls, doors, floors and stairs, lifts, light thinkers, switches [R headers] | `sector_t` 58, `line_t` 36, `side_t` 14 bytes [R research/iigs-platform.md §3]. `switchlist`, `SW_IDX` |
| Flow | g_game65.s, d_main65.s, m_cheat65.s | Tic commands, game actions, demo playback, save slots. Main loop and display; `MAXTICS`. Cheats [R headers] | `cmds`, the demo stream |

**Measures [M].** Standing still, the game logic is small: `p_tick65.s`
7,054 instructions, `p_user65.s` 1,252, everything else under 1,000. In
the demo it is 96,442 instructions and 353,811 cycles a frame. The main
parts are `p_sight65.s` (38,990 and 138,285), `p_tick65.s` (23,054 and
82,807), `p_map65.s` (16,037 and 60,017) and `p_enemy65.s` (7,051 and
26,971). The demo's tic phase reaches 958,322 cycles in one frame
[R `PROFILE.md` §1].

- 16-bit work is 67% to 80% in every module except `p_tick65.s` (32%)
  and `p_trace65.s` (43%) [M]. Those two switch widths often around
  bytes of state.
- Far data is mostly the zone (`$06`-`$08`: mobjs, sectors, lines),
  the level window (lumps in place) and the sight tables (`$1F`, `$21`).
- Hot labels: `sideTest`, `segTop`, `nodeSide`, `P_CheckSight` (sight).
  `visit` (43% of `p_tick65.s`: the thinker walk). `A_Look` and
  `behindFast` (monsters). `lLine`, `move`, `walkRange` (collision).
- Code: 52,484 bytes over these 25 modules, 30,792 bytes of it ran [M].
  That is 31% of the game's code.

**Self-modification [M].** `p_trace65.s` patches `thP`, `tlP1`, `tlP2`
and `ptBody` of `p_path65.s` (6 writers, 165 writes). Function pointers go
through the hand-assembled `JML [dp]` at 5 sites in these modules
(`p_tick65.s` 1, `p_map65.s` 2, `p_path65.s` 1, `p_pspr65.s` 1; the other
three of the 8 are in `patch65.s` and `r_sprite65.s`) [M static count].

**Vendor calls [M static].** `p_enemy65.s` 2 × `_Mod16`, `p_pspr65.s`
1 × `_Mod16`, `p_spawn65.s` 2 × `_Div32` + 1 × `_Mod16`, `p_inter65.s`
`_Div16` + `_Div32`, `p_floor65.s` `_Div16`, `p_path65.s` `_UDivMod32`,
`g_game65.s` 3 × `_UDivMod32`. In the demo, about 0.8 calls a frame from
the game logic [M].

**Strategy: close transliteration, bit-exact.** Demo3, the title loop and
lockstep checks all depend on each tic producing the same state. Data
layouts may change: the 4-byte far pointers can become 2-byte offsets
plus a bank byte, or handles, and fields can be split into byte arrays.
Arithmetic must not change: the same truncations, the same approximations
and the same order of `P_Random` calls.

**What makes it hard.**

- **Volume.** About 53 KB of 65816 code, mostly cold, much of it
  exercised only by rare events. Coverage scripts miss lifts, teleports
  and the finale. Tests need more scripts, or state snapshots before
  rare events.
- **Pointers.** 4-byte far pointers everywhere, and `[dp],y` on 1,729
  operand lines in the play code [R research/iigs-platform.md §6].
- **Calling conventions.** Stack-relative arguments (62 `,s` operands in
  `p_map65.s` alone [M static]). DBR-relative field access in the thinker
  walk. D used as a data register in `p_trace65.s`. A frame return that
  discards its caller's frame [R research/iigs-platform.md §3].
- **Cost in the demo.** Sight checks alone are 138k cycles a frame [M].
  They need `LOGTAB` (64 KB) and per-map tables in RamWorks, read at
  random.

### 3.7 Level loading and WAD

| Module | Role | Main data structures |
|---|---|---|
| w_level65.s | Map sets into the level window. B1 decompression with MVN, whose bank operands it patches. Store in RAM or on floppies with disk prompts. `titleWipe` [R `w_level65.s:1-10`; research/iigs-platform.md §4.4] | Level window `$2A`-`$3F` (22 banks; E1M3 needs 22.97) [R `w_level65.s:527-529`]. Store at `$40:0000` |
| w_wad65.s | WAD directory used in place, 256 hash chains [R header] | `lumphash` 512, `lumpnext` 3,072, resident WAD `$10`-`$12` |
| z_zone65.s | Zone heap over `$06`-`$09`, 16-byte headers, segment links [R header] | 262,096 bytes of heap [R research/iigs-platform.md §4.2] |
| p_setup65.s | `P_SetupLevel`: lines, sides, sectors and subsectors in the zone; segs, nodes, blockmap and reject in place; spawns things [R header] | Converted lump formats [R research/iigs-platform.md §4.5] |
| r_data65.s | Texture column tables per map (hot textures first), sprite frames, colormaps, animated flats, `R_PointOnSegSide` [R header] | `fullcolormap` (8,704), `MM_COLDIR`, composed columns in the window |

**Measures [M].** Nothing here runs per frame except `W_GetLumpByNum`
(234 instructions) and small parts of `r_data65.s`. The cost is at level
load (section 2 table): about 9.8 million instructions a load from these
five modules, plus 2.3 million in `memcpy` and `memset`. `w_level65.s`
patches its MVN bank operands (6 writers, 2,640 writes in the tour).

**Vendor calls [M static].** `p_setup65.s` 5 × `_UDivMod16`.
`r_data65.s` `_Div32`, `_Mod16` and `_UDivMod16`; its `_Mod16` runs 4
times a frame (animated flats).

**Strategy: redesign.** Upstream's layouts come from its own offline
tools (`wadtool.py`, `levelimg.py`, `levelset.py`, `b1.py`: GPL, not to
be copied). The port needs its own host converter from `DOOM1.WAD` to
65C02 layouts, and a loader that places units with memory API COPY and
FILL. The result is checked as a canonical dump of the level after
`P_SetupLevel` (sectors, lines, sides, subsectors, things, texture
columns), compared with `ref816`'s memory after the same load.

**What makes it hard.**

- Layout decisions cross every other subsystem, so they come first
  (section 5, step 0).
- 1.5 MB of level window per map lives in RamWorks, at 131+ fabric clocks
  a line miss today and about 35 with the firmware design (fact given in
  the task).
- The texture column tables point at texels in place, with an over-read
  margin of 128 bytes [R `tools/levelimg.py:23`, `:70`].

### 3.8 2D: status bar, HUD, menus, automap, intermission, finale, wipe

| Module | Role | Main data structures |
|---|---|---|
| i_viigs65.s | SHR video outside the 3D view: back buffer `$01:2000`, dirty byte ranges and `showDirty` (an MVN per row), palettes and tints with gamma, SCBs, nibble tables, view save for the menus, `D_Wipe`, raw pictures, the status-bar cache, the text cache [R `i_viigs65.s:1-4`; research/iigs-renderer.md §2.1, §2.12] | `TINTPAL` (5,376), `palette` (512), `scb` (200), `iigs_rowbase` (400), `iigs_rowpageL/R` (200 each), `GRAYMAP` (256), `STCACHE` `$01:A200` (5,120), `VIEWSAVE` `$22:9000`, `NIBTAB` `$0B:8000` (16 KB) |
| patch65.s | Patch drawing into the back buffer through nibble tables: a read, an AND mask and an OR per pixel. HUD text capture and compile to code at `MM_TEXTCODE` [R `patch65.s:1-9`, `:279-283`] | `MM_CAPVAL`, `MM_CAPMSK`, `MM_TEXTCODE` (`$25`-`$26`) |
| st_stuff65.s | Status bar widgets, face, palette effects [R header] | `faces`, `nmFaces`, `nmNums` |
| hu_stuff65.s | Message line, map title [R header] | - |
| m_menu65.s | Menus, key binding, mouse, display and sound options, benchmark, busy sign, accelerator control [R header; research/iigs-platform.md §2.6] | `keyNames` (1,024), menu tables, `MM_BUSY` (16 KB) |
| am_map65.s | Automap, full screen and overlay (`K_OVL` records) [R header] | `AM_LISTS` (12,000), `MM_VSTAB`, `MM_LVTAB` |
| wi_stuff65.s | Intermission [R header] | - |
| f_finale65.s | Episode 1 end text, then HELP2 [R header] | `e1text` |

**Measures [M].** Small in steady play: 2,173 instructions standing
still. In the demo it reaches 17,069 instructions (63,532 cycles) because
of the first frame's full redraw (`pairByte`, `drawRawData`, `pixLoop`,
`capPost`, `IIGS_TextCode`). `am_map65.s` ran only 297 of 6,203 bytes:
the automap was never opened. `f_finale65.s` ran 45 bytes. `m_menu65.s`
ran 2,762 of 6,753.

**Self-modification [M].** `i_viigs65.s` patches `displayCall` in
`d_main65.s` (menu palette, 40 writes). `IIGS_TextCode` writes 65816 code
into `MM_TEXTCODE` [R `patch65.s:279-381`], but no instruction outside
banks `$00` and `$03`-`$05` ran in the four runs [M], so the compiled text
code never executed there.

**Vendor calls [M static].** `am_map65.s` 2 × `_Div16`. `st_stuff65.s`
`_Div16` + 2 × `_UDivMod16` (0.2 to 0.8 calls a frame). `wi_stuff65.s`
2 × `_Div32`, 2 × `_UDivMod16`, `_UDivMod32`. `m_menu65.s`
6 × `_UDivMod32`. `f_finale65.s` `_Div32`. `i_viigs65.s` `_UDivMod16`.

**Strategy: transliteration, outputs must match (screen bytes).** Blits,
fills and view saves become memory API COPY and FILL. The dirty-range
copy from a back buffer can become direct drawing into SHR when the
lazy-mirror firmware exists; until then the back buffer in aux memory
plus memory API copies keeps upstream's design. The HUD text compiler
(65816 code generation) should become a 65C02 code generator, or a plain
cached drawer [A]. Accelerator menus (ZipGS, TransWarp GS) go.

**What makes it hard.** Volume more than speed: 23 KB of code, half of it
cold. Nibble-table patch drawing is per pixel with read-mask-or
(`pixLoop`), and costs 4.6 million instructions per intermission and load
[M].

### 3.9 Sound

| Module | Role | Main data structures |
|---|---|---|
| s_sound65.s | Doom's sound code for the Ensoniq DOC: 8 stereo channels, distance and pan, per-map DOC RAM plan. Starts songs; `musUpload` streams the next part of a song into DOC RAM [R `s_sound65.s:1-13`; `PROFILE.md` §1] | `PLANS` (550), `PAGEOWNER`, `SND_*` tables, `MM_MUSBUF` `$27:0000` (44 KB), `MM_SNDPCM` `$27:B000-$29:DFFF` |
| i_snd65.s | Decoder of the compressed sound bank at boot [R header] | `MM_SNDBANK` `$2C:0000` |
| i_doc65.s | DOC access, the tic timer (oscillator 31), the alarm (oscillator 30), `IIGS_DocUpload` [R `i_doc65.s:1-10`] | - |
| (irq65.s) | Music playback in the interrupt: register writes paced by the DOC alarm [R `irq65.s:1-10`] | Song image in `MM_MUSBUF` |
| music.inc | `MUSBUF` [R header] | - |

**Measures [M].** `musUpload` is 98% of `s_sound65.s` standing still:
7,206 instructions a frame on average [R `PROFILE.md` §1], in bursts.
`IIGS_DocUpload` in the demo: 4,291 instructions a frame on average.

**Vendor calls [M static].** `s_sound65.s` 2 × `_Div16`, `_Div32`,
`_UDivMod32`. In the demo, 3.8 calls a frame (distance attenuation).

**Strategy: redesign.** Per the owner, nothing of the DOC design is kept.

- **Music.** Play the WAD's MUS lumps on the Phasor's four AY-3-8913
  chips in native mode (12 tone voices, noise, envelopes) [R
  bilestoad/src/sound.s:1-16]. `DOOM1.WAD` has 13 MUS lumps totalling
  245,179 bytes [M]. A quick parse [M] gives, per song, 2 to 11 melodic
  channels plus percussion. The most melodic notes at once are 4
  (D_E1M3) to 11 (D_INTRO), with 10 in D_INTER and 9 in D_E1M9. So 12
  voices hold every song, but not together with sound effects in the
  busiest ones. The design needs voice stealing and a percussion mapping
  onto noise and envelopes. `GENMIDI` (11,908 bytes) holds OPL
  instruments that do not map onto an AY; each instrument needs a chosen
  AY rendition (octave, volume curve, noise for drums) [A].
- **Clock.** The MUS rate is 140 Hz [A: MUS format]. It can come from
  timer 1 of the Phasor's VIA, as Bilestoad does [R
  bilestoad/src/sound.s:13-16].
- **Sound effects.** `DOOM1.WAD` also has 55 PC-speaker lumps (`DP*`,
  3,055 bytes in all) next to the 55 PCM lumps (`DS*`, 535,127 bytes) [M].
  The PC-speaker sounds are tone sequences at 140 Hz, which map directly
  onto AY tone periods [A]. Upstream's channel logic (distance, pan,
  priority) can be transliterated, with AY volume and chip or voice
  choice standing in for DOC stereo.
- **Checking.** There is no upstream equivalent. The check is a host
  reference player that turns MUS into the same AY register stream, and
  listening on hardware.

**What makes it hard.** The instrument mapping is an artistic design task.
A player and its interrupt must share the CPU with the frame, with no
`$Cxxx` access while the SHR mirror drains; the Phasor lives at `$C4xx`.
So register writes should be batched between the replay and the next
frame, or the lazy-mirror firmware is needed [A].

### 3.10 Platform: boot, disk, input, clock, IRQ

| Module | Role | Target replacement |
|---|---|---|
| boot.s, loader.s | IIgs boot block and stage 2 loader, RAM probe, floppy and store loading [R headers] | ProDOS system file and memory API loads, as the existing port does [A] |
| crt0.s | Native mode, stack, D, DBR, BSS zeroing [R header] | Startup code |
| i_iigs65.s | `main`, table builds, 40-column text console with `printf`, `I_Error`, `I_Quit`, `I_StartTic` from ADB key events, `keyTable` [R header] | Text console on the //e text page; input from `demos/doom/src/kernel/input.s` [R `input.s:1-40`] |
| iigs_asm.s | ADB keyboard and mouse, ZipGS, `IIGS_CopyHuge` (a self-modified MVN) [R header; research/iigs-platform.md §2.2, §2.6] | Memory API COPY and FILL; //e keyboard and mouse card |
| irq65.s | IRQ handler (ADB, DOC alarm and music), RAM vectors, `bmDiskOn`/`bmSave` [R header] | IRQ for the mouse-card VBL and the Phasor VIA [A] |
| m_config65.s | Settings file and save slots on the boot disk [R header] | ProDOS file I/O [A] |
| keys.inc, loadbar.inc, memmap.inc, offsets.inc | Key codes, load bar, memory map, struct layouts [R headers] | Redesigned; `offsets.inc` becomes the canonical form of the state checker |

**Measures [M].** `irq65.s` 624 instructions a frame standing still
(music interrupt). `iigs_asm.s` 1,622 a frame in the demo, 90% of them
`mvnInst`, the MVN byte loop. `i_iigs65.s` 36 a frame.

**Self-modification [M].** `iigs_asm.s:nextChunk` patches the bank bytes
of `mvnInst` (2 writers, 3,004 writes). Read but not in recorded frames:
the loader's JML target and MVN banks [R `loader.s:328-333`, `:625-632`
via research/iigs-platform.md §3], and the benchmark hook
[R `m_menu65.s:2197-2251` via the same].

**Strategy: redesign.** Nothing IIgs-specific carries over.

- **Tic clock.** Upstream reads DOC oscillator 31 [R `i_doc65.s:1-10`],
  which gives 34.955 tics a second [R MILESTONES.md]. The existing port
  uses the mouse card's VBL interrupt [R `demos/doom/src/kernel/input.s:1-7`].
  Seven tics per 12 video frames gives 35 tics a second at 60 Hz, and
  34.953 at the //e's 59.92 Hz (17,030 bus cycles a frame [R
  `bilestoad/src/sound.s`, `TICK_CYCLES`]). That is within 0.01% of
  upstream's clock.
- **Input.** The //e reports only the last key, with no key-up events
  [R `input.s:9-13`]. Upstream expects ADB key down and up. The port
  needs a policy for held keys, as the existing port has. Demos are not
  affected; they carry their own tic commands.

**What makes it hard.** Little code. The hard part is the `$Cxxx` rules:
every `$C000-$CFFF` access is a real bus cycle and waits for the SHR
drain [R research/appletini-hardware.md §1]. So input polling, sound
register writes and interrupts must be placed in the frame where no drain
is pending.

### 3.11 Shared math and tables

| Module | Role | Main data structures |
|---|---|---|
| m_fixed65.s | Quarter-square multiply: `umul16`, `mul3216`, `_Mul32`, `_Mul16`, `FixedMul`, `IIGS_MulLo16`; builds the tables at boot [R `m_fixed65.s:1-8`] | `SQL`/`SQH` `$13`-`$1A` (512 KB); `iigs_mulT` (1,532, `mul.inc`) |
| m_recip65.s | Reciprocals and the texture-step table [R `m_recip65.s:1-10`] | `RECIP_TABLE` `$1E` (64 KB), `FSTEP` `$1B`-`$1C` (128 KB) |
| tables65.s | `finesine`, `finecosine` from the full table, and approximations [R header] | `SINE` `$20` (64 KB), `finesineTable_part_1` (4,096), `xtoviewangleTable` (322) |
| m_random65.s | `P_Random`, `M_Random` [R header] | `rndtable` (256) |
| string65.s | `memcpy`, `memset` a word at a time [R header] | - |
| mul.inc, offsets.inc | Byte-product macros; struct layouts and constants | - |

**Measures [M].** Standing still, 3,133 instructions a frame in
`m_fixed65.s` including the folded vendor divides. In the demo, 9,482,
and `m_recip65.s` adds 2,367. Far data goes to `SQL`/`SQH` (`$13`-`$18`)
and `RECIP_TABLE` (`$1E`).

**Strategy: redesign allowed, outputs must match bit for bit.** Every
function has a host model and a test over its whole domain, or a large
random sample of it [A]. Multiplication can use any exact method; small
8 × 8 quarter-square tables in fast memory are the obvious one.
Reciprocals, `FSTEP` and the sprite scale tables are approximations of a
division, so they need the same tables or the same truncated formula. The
divide routines that replace the vendor runtime are written from the call
sites only (the ground rules).

**What makes it hard.** Table size against fast memory. Upstream uses
about 830 KB of tables [R research/iigs-renderer.md §6]. The native port
keeps in fast memory only what the inner loops read and leaves the rest
in RamWorks.

## 4. Cross-cutting inventories

### 4.1 Self-modifying code, by writing module [M]

Writes over the four whole runs, in recorded frames only (from the title
page on).

| Writer | Writer instructions | Targets | Writes | When |
|---|---:|---|---:|---|
| r_list65.s | 86 | `drawcol.s` `texBlocks`, `flatBlocks`; `r_seg65.s` (13 labels); `r_frame65.s:vwFrame`; its own `drawSel`, `oneDispatch`, `onePage`, `nrRow*` | 466,335 | Per record (row-block exits), per view size or detail change |
| drawcol.s | 5 | `texBlocks` | 18,319 | Small view sizes only |
| r_seg65.s | 33 | 29 of its own labels (`c17Scale50`, `c26RecordReady`, loop exits, C19 kernel sites) | 16,564 | Per seg, per view size |
| r_sprite65.s | 4 | `dsLoop`; `drawcol.s:fuzzBlock` | 6,248 | Per sprite, per shadow column |
| iigs_asm.s | 2 | `mvnInst` | 3,004 | Per `IIGS_CopyHuge` chunk |
| w_level65.s | 6 | `b1Lmvn`, `b1Mmvn`, `b1Rdb`, `b1Rdw` | 2,640 | Level load |
| r_frame65.s | 6 | `r_sprite65.s:R_DrawSprite`, `clipIt`; its own `mwS2a`, `mwS2b` | 1,904 | Per frame, per masked column |
| r_thing65.s | 49 | Its own `gTX`, `gTZ`, `gTZsum`, `gGZcheck`; `r_seg65.s:visNext`, `visDone`; `r_frame65.s:visColD`; `r_sprite65.s:wdDraw` | 1,129 | Per sprite, per view size |
| p_trace65.s | 6 | Its own `thP`, `tlP1`, `tlP2`; `p_path65.s:ptBody` | 165 | Per trace |
| i_viigs65.s | 2 | `d_main65.s:displayCall` | 40 | Menu open and close |

Read but not seen in recorded frames: `loader.s` (JML target, MVN banks),
`m_menu65.s` (benchmark hook), `patch65.s` (compiled text code), and the
move of the music interrupt code to `$00:DC00`
[R research/iigs-platform.md §1.4, §3].

### 4.2 Calls into the vendor runtime, by callee name

Static call sites in the game's sources [M: a scan of instruction
operands], and calls a frame in the recorded frames [M]:

| Callee | Sites | Modules (sites) | Calls a frame, still | Calls a frame, demo |
|---|---:|---|---:|---:|
| `_UDivMod32` | 14 | m_menu65 (6), g_game65 (3), r_iigs65 (2), p_path65, s_sound65, wi_stuff65 | 0 | 0.2 |
| `_UDivMod16` | 11 | p_setup65 (5), st_stuff65 (2), wi_stuff65 (2), i_viigs65, r_data65 | 0.2 | 0.8 |
| `_Div32` | 8 | p_spawn65 (2), wi_stuff65 (2), f_finale65, p_inter65, r_data65, s_sound65 | 0 | 1.3 |
| `_Div16` | 7 | am_map65 (2), s_sound65 (2), p_floor65, p_inter65, st_stuff65 | 0 | 2.65 |
| `_Mod16` | 6 | p_enemy65 (2), p_pspr65, p_spawn65, r_data65, r_wall65 | 4.0 | 4.4 |
| **All** | **46** | 18 modules | **4.2** | **9.4** |

No site calls `_DivModSign16`, `_DivModSign32` or `_Mod32` directly [M].
The multiplies (`_Mul16`, `_Mul32`) are upstream's own, in `m_fixed65.s`
[M link map].

### 4.3 Register widths, direct page and data bank

Over the four runs, 44,680 instruction addresses ran [M]. Only
`drawcol.s` (160 addresses, none of them in the `newgame` and `title`
runs), `iigs_asm.s` (42) and `irq65.s` (24) ran the same address with
more than one (M, X) [M]. D and DBR vary at a few hundred addresses: in `irq65.s`, `iigs_asm.s`,
`p_trace65.s` (D as data) and the tic code of `p_map65.s`, `p_trace65.s`,
`p_pspr65.s`, `w_level65.s` and `p_tick65.s` (DBR as a base register)
[R `PROFILE.md` §4]. For a rewrite, those are the places where the
65816's addressing carries meaning that has to become explicit pointers.

## 5. Rewrite order

| Step | What | Why this place | Checked against `ref816` by |
|---|---|---|---|
| 0 | **Foundations.** Zero-page plan, fast-memory budget and code overlays (memory API COPY by phase), bank plan for RamWorks. Host converter from `DOOM1.WAD` to 65C02 layouts. Shared math with host models. A **state canonicaliser** on both machines: upstream layouts through `offsets.inc` on `ref816`, native layouts on `a2vm`, into one text form. | Every later step depends on layouts and on a way to compare. 58% of 170 KB of code runs, and a native version is larger [A: 1.5 to 2.5 times], far beyond about 90 KB of fast memory, so overlays are designed in, not added later. | Math: whole-domain or random tests against host models |
| 1 | **Record replay** (`r_list65.s`, `drawcol.s`) | The largest cost: 34% to 42% of cycles [M]. Already 8-bit. A clean interface: records in, screen out. Can run behind upstream's records (`ref816` dumps of bank `$1D`) before any producer is native. Tests the hardware's risky parts early: SHR drain, `$C069` banks, TURBO caching of patched code. Fits milestone 4. | Screen bytes from the same record bank dump |
| 2 | **Seg loops, wall setup, BSP walk** (`r_seg65.s`, `r_wall65.s`, `r_bsp65.s`, `r_iigs65.s`, planes) | 54% of the cycles standing still and 23% in the demo [M]. Produces records, so it plugs into step 1. | Record lists per column and clip arrays, from a `ref816` state snapshot (player position, level) |
| 3 | **Sprites and masked** (`r_thing65.s`, `r_sprite65.s`, `drawMasked`/`mwCols` of `r_frame65.s`, `visPost`) and **frame setup** | Completes the renderer. The demo's worst frames are here [R `PROFILE.md` §1]. | Records, covered ranges, weapon skip, then whole screens |
| 4 | **Level loading** (`w_level65.s`, `w_wad65.s`, `z_zone65.s`, `p_setup65.s`, `r_data65.s`) | Lets the native renderer run from a native level load instead of injected snapshots. Mostly memory API work. | Canonical level dump after `P_SetupLevel`, each of the 9 maps |
| 5 | **Game logic**, in this order: thinkers and tables; player and game flow (`p_user65.s`, `p_pspr65.s`, `g_game65.s`, `d_main65.s`); movement and collision (`p_map65.s`, `p_mobj65.s`, `p_path65.s`, `p_trace65.s`); sight and monsters (`p_sight65.s`, `p_enemy65.s`, `p_attack65.s`, `p_inter65.s`, `p_spawn65.s`); specials | 52 KB of code, but cheap standing still (4% of cycles) and 23% in the demo [R `PROFILE.md` §1]. It must be bit-exact, so it comes when the harness is proven. The order follows demo3's needs: a player that stands, then walks, then meets monsters. | Canonical game state after every tic, through demo3 and the coverage scripts |
| 6 | **Platform** (input, tic clock, IRQ, settings) | Needed for interactive play and hardware runs. Minimal stubs on `a2vm` earlier. | Scripts replayed as input; clock rate about 34.95 tics a second |
| 7 | **2D** (`i_viigs65.s`, `patch65.s`, `st_stuff65.s`, `hu_stuff65.s`, `m_menu65.s`, `am_map65.s`, `wi_stuff65.s`, `f_finale65.s`) | Large but cold (2,173 instructions a frame standing still [M]). Straight transliteration with memory API blits. | Screen bytes of the status bar, menus, automap, intermission |
| 8 | **Sound on the Phasor** (MUS player, sound effects) | Independent of upstream's code, so it can run in parallel with any step once the `$Cxxx` timing rules of step 1 are known. | A host MUS-to-AY reference player; listening on hardware |

Why this order rather than the game first:

- **Cost.** Steps 1-3 cover 91% of the cycles standing still and 71% in
  the demo [M, section 2]. Their speed decides whether native is
  worth it, so they are measured on hardware first.
- **Interfaces.** The column records, the screen bytes and the per-tic
  state are exact, already-defined interfaces that `ref816` can dump. Each
  step can be verified alone, without a whole native game.
- **Risk.** The replay tests the hardware assumptions: the SHR drain, the
  zero-page bank pair, the colormaps in the language card, and patched
  code in TURBO. If they fail, the renderer's design changes, and it is
  better to learn that before 53 KB of game logic depends on the data
  layouts.
- **Exactness last.** The game logic has much code (52 KB) and the
  strictest contract. It is best done with a proven canonicaliser and with the
  renderer already able to show its state.

## 6. Limits of this inventory

- Coverage: four scripts. Lifts, teleports, the finale, saves, key
  binding, the automap and the sound options barely run or do not run.
  "Ran, bytes" is a lower bound on live code.
- Cycles are those of an ideal 65816 with no wait states, as in
  `PROFILE.md`. They rank the work; they are not target times.
- "16-bit work" uses the widths recorded at each address over the whole
  runs. For the few addresses with more than one width, a 16-bit value
  seen at least once counts as 16-bit.
- Opcodes and lengths come from a RAM dump at the end of one run. Bytes
  that were patched and not restored could be misread. The main patched
  sites (row-block exits) are restored after each use [R
  research/iigs-renderer.md §2.9].
- The patched tracer and the analysis scripts lived in this session's
  scratchpad, not in the repository. To redo them, apply the changes
  described in section 1 to a copy of `tools/ref816`.
