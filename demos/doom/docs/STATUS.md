# Doom port: status after phase 2, and the memory problem

Written for a pause: phase 2 (the 6502 renderer and the game logic) is
done and verified, but the game does not fit its address space. This
file records where things stand, the numbers, and the options with what
each one yields, so the decision can be taken with everything in view.
Sections 4, 7, 8 and 9 of DESIGN.md hold the detail.

## 1. What exists and what it passes

**Renderer** (`src/render/`, 7.1 and 7.2 of DESIGN.md): BSP walk, walls,
planes, sky, two-sided middles, sprites, the spectre's fuzz, the weapon,
animation, extralight and fixed colormaps, in 65C02 assembly. Every
frame is byte-identical to the Python reference renderer
(`tools/refrender.py`):

- `tests/test_render_core.py`: 109 views without things (36
  deliverables, 6 golden, 9 flat-shaded, 40 random, 15 animation tics,
  3 colormap views) plus the four limits forced low.
- `tests/test_render_masked.py`: the same views with the 128 nearest
  things and the pistol, 76 synthetic scenes (rotations, flipped frames,
  very near and far, edges, fullbright, spectres, things behind and
  across two-sided middles, the weapon at nine positions, flashes, a
  crowd of 120) and forced limits.

Cost: mean 3.5 M cycles a frame with things (p90 6.3-6.9 M, max 7.7 M),
against the 1.25 M that one 60 Hz frame gives at 75 MHz: 20-25 fps in
typical views, about 10 fps in the worst. Where it goes: walls 1.25 M,
planes and spans 0.9 M, wall pixels 0.43 M, BSP/segs/bboxes 0.66 M,
the masked phase 0.4 M. Per the decision to leave speed until the
gameplay is validated, nothing has been tuned beyond what the agents did
while writing it. Memory: main memory and all three language-card areas
are within about 250 bytes of full; the zero page has 7 bytes free.

**Game** (`src/game/`, section 9): vanilla Doom's logic, kept as host C
(the reference, tested with gcc) with 65C02 assembly twins of the hot
modules for cc65: player movement and weapons, collision and the
blockmap, mobj movement and states, sight, monster AI, damage and
pickups, all 141 line specials and the sector specials (doors, floors,
stairs, donut, plats, ceilings, crushers, teleporters, lights, switches,
buttons, scrolling walls), the level flow (exit, intermission, secret
exit, E1M8 finale, new game, level undo through snapshots and a journal).

- Host tests: `test_game_core.py` (13), `test_game_monsters.py` (20),
  `test_game_specials.py` (18 host + 3 lockstep), `test_game_info.py`
  (tables equal vanilla's info.c and ZDoom's actors).
- The 6502 build against the host, compared after every tic (positions,
  momenta, states, random index, weapons, psprites, sectors, lines,
  level flow, sound counts, the render packet): `test_game_asm.py` (13),
  `test_game_sim.py` (5: a 290-tic session on E1M1, a barrel, E1M8,
  29 awake monsters for 300 tics, 14 pickups), the specials' lockstep.

These run in a py65 "flat" harness that gives the game 62 KB and code
windows, not the Apple's memory map: see the problem below.

Tic costs (E1M1, far accesses charged at the kernel's rate): standing
42 K, walking 64-70 K, firing 165-365 K (max 2.3 M: three autoaim
traces plus the shot), 29 awake monsters: mean 717 K, p90 1.4 M, max
2.8 M; the render packet 370 K a frame; level load 7-9 M.

**Platform** (`src/kernel/`, section 8): loader, PAL256 video, spaces,
far access, VBL clock, frame loop, blit, input; `tests/test_platform.py`
(27) and `tests/test_disk.py` (6). `tools/a2sim.py` is the test machine.

Not done: the status bar, title and menus, sound, and the first real
boot of the whole program (loader + kernel + renderer + game) in the
simulator, because the link fails.

## 2. The problem: the game is 85 KB, its space is 46.6 KB

The GAME space is RamWorks bank 1, `$0200-$B7FF` (46,592 bytes; the
C stack takes `$B800-$BFFF`). The game's segments today (`od65
--dump-segsize` of `build/game/*.o`; the last two are reused as level
memory after the level is set up):

| Segment | bytes | What |
|---|---|---|
| CODE | 49,134 | assembly 41.5 K (a_map 6.0, a_mobj 5.5, a_movers 4.7, a_enemy 4.6, a_maputl 4.0, a_spec 3.7, a_user 3.6, a_sight 3.0, a_levdata 2.6, a_inter 2.6, a_view 1.9, fixed 1.9, gwork 0.6, kglue 0.1); C 5.7 K (p_spawn 1.5, p_setup 1.4, g_game 1.0, m_misc 0.5, ...); cc65 runtime 2.0 K |
| RODATA | 6,919 | states 3.0 K, mobjinfo 3.1 K, spec_tab 0.4 K, rndtable, small tables |
| BSS | 13,322 | level-data caches 4.8 K, rview (render packet, 128 things) 2.6 K, g_game 2.7 K, a_maputl 1.3 K, intercepts 1.2 K, fixed 1.1 K, sight caches 0.9 K, a_view 0.9 K, candidates 0.8 K, W 0.3 K |
| resident | **69,375** | |
| GFAR | 8,194 | far tables, copied to the game's far bank at boot; then level memory |
| GOVL | 5,347 | set-up overlay (read back before each level); then actor slots |
| total in the image | **82,916** | |

Plus level memory (blockmap chains, sector arrays, line marks, thinker
blocks, statics, reserve; the GFAR + GOVL bytes, 13.5 K, are the only
room for it now) and 64 bytes per awake actor:

| map | E1M1 | E1M2 | E1M3 | E1M4 | E1M5 | E1M6 | E1M7 | E1M8 | E1M9 |
|---|---|---|---|---|---|---|---|---|---|
| skill 2 | 9,963 | 13,155 | 13,434 | 14,914 | 13,148 | 17,010 | 22,368 | 6,534 | 13,421 |
| skill 4 | 10,331 | 13,891 | 14,666 | 15,922 | 13,740 | 18,914 | 23,936 | 6,550 | 13,741 |

So the whole game with E1M7 on ultra-violence and, say, 100 awake actors
wants about 69 + 24 + 6.4 = **100 KB**, against 46.6 KB. The linker
today stops at "CODE overflows GAME by 4,462 bytes" (CODE alone), and
"GZP overflows KZP by 1 byte" (the game wants 8 bytes of zero page; the
kernel and renderer leave 7).

## 3. Hardware facts that bound the options

Verified in appletini-one's HDL (`hdl/globals.sv`, the vTW translator)
and the kernel measurements:

1. A RamWorks bank is a whole 64 KB: with ALTZP on, the zero page, the
   stack and the language card (`$D000-$FFFF`) come from the selected
   bank too. So code in a bank's language card disappears when the bank
   register changes, like code in its `$0200-$BFFF`.
2. RAMRD and RAMWRT choose main or "aux", and aux is the one bank that
   `$C073` selects. There is no way to read one bank and write another
   in the same instruction: bank-to-bank data goes through main memory,
   the main language card or the zero page (a bounce).
3. Every `$C0xx` access costs a 1 MHz bus cycle, about 73 cycles at
   75 MHz (TURBO waits for the mirror). A space switch is 2-3 of them,
   a bank switch 1. Hence the kernel's far access from GAME space costs
   about 360 cycles fixed plus 37 a byte (RENDER space: 16 a byte). A
   bounce written for it could reach about 300 + 24 a byte, no better.
4. Main memory (`$0200-$BFFF`) and the main language card are the
   renderer's and the kernel's, and full. The renderer must live in main
   memory: its inner loops read a texture bank with RAMRD on and write
   the view buffer in main memory, which is the only arrangement fact 2
   allows.
5. The view buffer (13.4 KB of main memory) is dead between the blit
   and the next `render_frame`, i.e. while the tics run, but only as
   scratch: nothing in it survives a frame.

The largest fast address space the machine can give the game is
therefore **one RamWorks bank with ALTZP on**: `$0200-$BFFF` (47.5 KB)
plus its own language card (16 KB, of which 12 KB contiguous), its own
zero page (256 bytes) and its own stack: about **63.3 KB** after the
kernel's trampolines. Everything beyond that is "far" at the cost in
fact 3, or lives in an overlay.

## 4. Options, with what each yields

**A. GAME space with ALTZP on** (+16.7 KB and the zero page). Needs in
the kernel: a trampoline in bank 1 (`$0200-$BFFF`, visible in both
ALTZP states) that switches ALTZP off, copies the call's parameters into
the kernel's zero page, calls the jump table, and switches back (+146
cycles per kernel call, i.e. +40% on a far read); the same in reverse
for `call_game`; a vector table and an IRQ stub in bank 1's language
card (`ALTZP off; jsr kernel irq body; ALTZP on; rti`); the loader
writing a bank-1 language-card image (a fourth image file); the
simulator modelling the per-bank card (today it has one aux card). The
game gets 256 bytes of zero page (the W slots and the 8-byte GZP go
there, which also makes the assembly faster) and 12-16 KB more. This is
the one option that changes the ceiling; everything else is a diet.

**B. Cold code in overlays** (loaded from far memory into a window
when needed, as the level set-up already is): the movers' set-up code
(EV_DoDoor, EV_DoFloor, EV_BuildStairs, plats, ceilings, teleport: about
4 KB, run when a line is triggered), the specials' use/cross/shoot
dispatch (about 2 KB), damage and pickups (2.6 KB, run on hits),
p_setup's resident part (1.4 KB), the level flow (1 KB), m_misc (0.5 KB).
About 11 KB out, a 4-5 KB window in: **net 6-7 KB**, at about 150-200 K
cycles per overlay load, i.e. per door opened or item picked up (a
tenth of a frame; acceptable) but not per tic. The missile spawners and
the sight code must stay resident (they run every second or every tic).

**C. Tables and buffers**: mobjinfo (3.1 KB) far, read at spawn and on
damage; the render packet capped at 64 things (-1.3 KB); the C stack cut
to 512 bytes, the C being small now (-1.5 KB); the level-data caches
trimmed (-1 KB, costs speed): **about 5-7 KB**.

**D. Level memory far with caches, hot subset resident.** The map data
(lines, sectors, nodes, blockmap) is already far with caches and the
tics are within budget, so the same pattern extends to level memory:
statics (dormant things: E1M7 about 5 KB) far with a short list of the
ones that animate; line marks and thinker blocks far; the blockmap thing
chains (E1M7 about 4 KB), the dynamic sector state (about 2 KB) and the
actor pool resident. Actors have to be capped (their pool is the largest
hot item: 64 bytes each); with 96 slots, 6 KB. Awake monsters beyond
the cap would stay dormant, which is a visible difference from vanilla
on the crowded maps at ultra-violence. Hot level memory: **about 13 KB**.

**Tally of A + B + C + D**: resident 69.4 - 7 - 6 = 56.4 KB, plus the
overlay window (counted in B), plus hot level memory 13 KB = 69.4 KB
against a 63.3 KB pool. **Still about 6 KB short**, before any margin;
so the actor cap would have to be lower (64: 4 KB), the caches smaller,
and more of the code cold (the monsters' pain/death/pickup paths,
the switches and lights) — each of which costs speed or fidelity. It
fits only just, and it is a large, cross-cutting change to code that
is verified today.

**Rejected** (why, for the record):
- Code mirrored in two banks with data split between them: the code is
  49 KB of the 64, so two banks give less data room than one with ALTZP.
- Two banks as two spaces (say, the monsters in bank 2): they share the
  actors, the sectors and the map caches at every step.
- Swapping the homes (game in main memory, renderer in a bank): fact 4;
  and main memory is no larger.
- Game state in the dead view buffer or in main memory: nothing there
  survives a frame; saving and restoring 13 KB costs 640 K cycles a
  frame.
- Per-tic code overlays (swap the monsters' code in and out each tic):
  10 KB a tic at 37 cycles a byte is 370 K.
- Actors far: a thinker's actor round trip is about 4 K cycles; twenty
  awake monsters would cost 80 K a tic before doing anything.

## 5. Where fidelity could be traded instead

If the ceiling of 63 KB is taken as the frame, the honest question is
what to leave out of vanilla's logic rather than where to hide it:

- The specials beyond E1's 42 line types cost little (one table), but
  the movers' code for stairs, donut, crushers and plats is 2-3 KB of
  assembly that E1 uses rarely or never (donut and crushers: never).
- The intermission, finale and level undo (snapshots and the journal:
  about 2 KB resident, the rest far) could be simplified to a restart
  from a fresh load if level memory were reloaded from the WAD images
  (it cannot be today: the game rewrites the converted sector records in
  place).
- Autoaim's three traces on every shot, and the 128-thing render packet,
  are the two biggest per-frame costs and also memory.
- The actor cap (D) is the one that changes what the player sees.

## 6. Test status at the pause

See the end of this file for the run made at the pause (`make test`
covers the platform, disk, converter, reference renderer, game and
renderer suites; the renderer suites need `RENDER_GAMESRC` pointing at
the game snapshot in `build/rtrack/gamesnap`, and the game lockstep
suites their flat harness, until the link fits).

The main link (`make`) fails on the overflows in section 2. The renderer
links and runs on its own (`make BUILD=build/rtrack/
GAMESRC=build/rtrack/gamesnap`); the game runs on its own in the flat
py65 harness.

## 7. What was not touched, per the decision on speed

The renderer's speed (3.5 M cycles a frame against 1.25 M) and the
firing and monster tic peaks are recorded but not worked on: the
gameplay is to be validated first. The memory problem above is not a
speed matter: it stops the program from linking at all.
