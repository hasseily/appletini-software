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
{still_tics} and {demo_tics} calls of `P_Ticker` a frame), so a slower
machine draws the same frames with the same work. Only the interrupts and
the music, which follow machine time, would differ.

Two scenarios:

- **Standing still in E1M1**: `coverage/newgame.script` from its note
  `still` (3 seconds after E1M1 has loaded) to `still-10s`, ten seconds of
  machine time: {still_frames} frames.
- **The title demo**: `coverage/title.script` from its note `demo` (the
  first tic of demo3, in E1M3) to `demo-25s`: {demo_frames} frames.

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

{phase_detection}

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
phase, and have a row of their own when a frame has any: {still_firmware}
cycles in the frames standing still, {demo_firmware} in the demo.

The trace checks its own boundaries. Phases still open when the next frame
started: {still_unclosed} standing still, {demo_unclosed} in the demo.
Entries reached by a jump instead of a call, over the whole runs:
{still_jumps} and {demo_jumps}. In every frame the phases and the firmware
traps add up to the frame's instructions and cycles.

## 1. Instructions and cycles by phase

### Standing still in E1M1

{still_phases}

A frame takes {still_ms} ms of machine time ({still_fps} frames a second):
{still_instructions} instructions and {still_cycles} cycles,
{still_cpi} cycles an instruction. The seg loops ({still_share_seg}) and
the record replay ({still_share_replay}) take two thirds of it, the BSP
walk and the wall setup {still_share_bsp} and {still_share_wall}. The tics
cost little ({still_share_tics}) while the player stands in the first room.

What "Everything else" is made of, over all the frames:

{still_other}

Most of it is the music: `musUpload` loads the next part of a song into
the sound chip each pass. The music is also why a few interrupts show up
(the DOC alarm that paces it).

### The title demo

{demo_phases}

A frame takes {demo_ms} ms ({demo_fps} frames a second):
{demo_instructions} instructions and {demo_cycles} cycles. With monsters
awake in E1M3 the tics rise to {demo_share_tics} of the cycles and the
replay to {demo_share_replay}. The first frame is the slowest: it draws the
whole status bar and view window (the status bar and frame setup phases).
The last frames are a fight at close range, where a large monster fills
the view and the masked drawing (sprites) and the replay grow.

{demo_other}

**For the port.** Outside the replay a frame is {still_p2} instructions
standing still and {demo_p2} in the demo (section 8). At the nominal 18
cycles a translated instruction and 45 million cycles a second of
ARCHITECTURE.md section 6 that is about {still_p2_ms} ms and {demo_p2_ms}
ms of CPU time before any far access. The seg loops, the BSP walk and the
wall setup are where translated code must be good. The replay, which the
plan hand-writes, is a third to two fifths of the IIgs's cycles, so its
kernel matters as much as the translator. The tics vary most among the
large phases (the ranges of the demo): a budget must hold for a fight, not
only for a still view.

## 2. Memory accesses

### Standing still in E1M1

{still_access}

{still_banks}

{still_far_phases}

### The title demo

{demo_access}

{demo_banks}

{demo_far_phases}

**Kinds of access.** Direct page accesses outnumber all other data
accesses together, so the plan's virtual direct page in the 65C02's own
fast memory is where most of the data traffic goes. Far data is
{still_far} accesses a frame standing still and {demo_far} in the demo,
{still_far_share} and {demo_far_share} of the instructions.

**Far banks and lines.** A frame touches {still_far_lines64} distinct
64-byte lines of far data standing still ({still_far_pages} pages) and
{demo_far_lines64} in the demo ({demo_far_pages} pages). That is far more
than a small cache holds (the line cache of ARCHITECTURE.md section 3.4 has
64 lines of 64 bytes), and it is spread over dozens of banks: the level
window, the quarter-square tables of the multiply (banks $13-$1A), the
colormaps in $0D, the records in $1D. A cache pays only for the objects the
plan gives it (nodes, segs, sectors) and the tables need paths of their
own. Bank $02 is touched on {still_near_pages} of its 256 pages a frame
standing still and {demo_near_pages} in the demo, a large share of the
fast memory if all of it were resident; the hot extent of section 3.3
should be chosen from these pages.

**Bank changes.** A change of bank between two consecutive far accesses
happens {still_bank_changes} times a frame standing still and
{demo_bank_changes} times in the demo. The replay makes {still_replay_changes}
and {demo_replay_changes} of them, as upstream's order alternates between
the screen (bank $01), the colormaps ($0D), the records ($1D) and the
textures in the level window. At about 1 µs a change, upstream's order
would cost the replay tens of milliseconds a frame; the plan's replay
batches its passes by bank (read, gather, shade), which removes most of
them. Outside the replay there are {still_p6_changes} changes a frame
standing still, about {still_p6_ms} ms, and {demo_p6_changes} in the demo,
about {demo_p6_ms} ms.

## 3. Code heat

### Standing still in E1M1

{still_heat}

By section and by source file, over all the frames together (so that the
parts add up; the totals of a single frame are those above):

{still_heat_sections}

{still_heat_files}

By phase, over all the frames together:

{still_heat_phases}

### The title demo

{demo_heat}

{demo_heat_sections}

{demo_heat_files}

{demo_heat_phases}

**For the port.** Standing still, {still_executed_bytes} bytes of code run
in a frame and {still_hot_99} bytes account for 99% of its instructions;
in the demo {demo_executed_bytes} and {demo_hot_99}. At the plan's
expansion of 8.5 bytes of 65C02 code for 2.7 bytes of 65816 code
(section 3.5), the 99% set is about {still_hot_99_native_kb} KB of native
code standing still and {demo_hot_99_native_kb} KB in the demo, a large
part of the 90 KB of fast memory before any data. The code must rotate by
phase, as the phase windows of section 3.2 do; section 8 measures how much
of each phase a window covers. Standing still, the renderer's own sections
(`segcode`, `bspcode`, `hotdraw`, `segwalls`, `hotlist`) hold most of the
90% set. In the demo the game logic joins them (`logiccode`, `p_map65.s`,
`p_sight65.s`), and neither the tic window nor the render window covers
its phase as well as standing still.

## 4. Register widths

Over the two whole runs, from the game's entry to the end of each script:

{widths}

{widths_files}

{widths_executed} instruction addresses ran. The (M, X) widths had one
value at all but {widths_mx} of them, D at all but {widths_d} and DBR at
all but {widths_dbr}. Addresses run in emulation mode:
{widths_emulation}. Static
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

{still_smc}

### The title demo

{demo_smc}

Standing still, the game writes to its code {still_smc_writes} times a
frame, from {still_smc_writers} instructions into {still_smc_targets}
labels; in the demo {demo_smc_writes} times, from {demo_smc_writers}
instructions into {demo_smc_targets} labels. Most of it is the replay
patching the ends of its row blocks (`r_list65.s` writing the
`texBlocks` and `flatBlocks` of `drawcol.s`), which the plan replaces with
a hand-written kernel. Beyond that the translator meets a short list of
patch sites, each written up to about a hundred times a frame (the seg
setup, the sprite and fuzz drawers, the MVN of `iigs_asm.s`). The writes whose byte had not run yet
are counted when it first runs; {still_smc_mixed} standing still and
{demo_smc_mixed} in the demo shared that wait with a write of another
instruction or frame and were counted with the last one.

## 6. Stack

### Standing still in E1M1

{still_stack}

### The title demo

{demo_stack}

Bytes used are counted down from the stack's top: the frame stack from
$3FFF (`crt0.s` sets S there) and the tic stack from `LOGIC_SP`. The
lowest point of the frame stack is reached inside an interrupt, which
pushes on top of what it interrupted. The frame stack used at most
{still_stack_frame} bytes standing still and {demo_stack_frame} in the
demo, the tic stack {still_stack_tic} and {demo_stack_tic}.
ARCHITECTURE.md section 3.2 gives the soft stack 4 KB of fast memory; these
scenarios use a small part of that. Level loads, the menus and the
intermission are not measured here, so the budget should come from a run
of all the coverage scripts before it is cut.

## 7. Screen

### Standing still in E1M1

{still_screen}

### The title demo

{demo_screen}

Standing still, the game writes {still_screen_bytes} bytes to the screen
a frame, all of them in the replay and through shadowing, and
{still_screen_changed} of them change
the stored value. At about 1 µs a byte on the target that is
{still_p8_ms} ms a frame as written, {still_p8_changed_ms} ms if only the
changed bytes went out. In the demo it is {demo_screen_bytes} bytes,
{demo_screen_changed} of them changed: {demo_p8_ms} ms against
{demo_p8_changed_ms} ms. Comparing with the screen before the drain makes a
still view almost free and saves less when the view moves.

## 8. The assumptions of ARCHITECTURE.md section 6, measured

These replace the assumptions P2, P4, P6 and P8 of ARCHITECTURE.md section
6 (which stays as it was written).

| # | Assumption | Assumed | Standing still in E1M1 | Title demo |
|---|---|---:|---:|---:|
| P2 | Upstream instructions per frame outside the replay | 450,000 (300,000 to 600,000) | {still_p2} | {demo_p2} |
| P2' | The same without the game tics (new) | | {still_p2_no_tics} | {demo_p2_no_tics} |
| P2'' | Instructions of one game tic (new) | | {still_tic} | {demo_tic} |
| P4 | Share of executed instructions that are native | 97% (90% to 99%) | {still_p4} | {demo_p4} |
| P6 | Far accesses per frame outside the replay | 54,000 (12% of the instructions) | {still_p6} | {demo_p6} |
| P6' | Changes of bank between them (new) | | {still_p6_changes} | {demo_p6_changes} |
| P8 | SHR bytes per frame | 13,000 | {still_p8} | {demo_p8} |

**P2** is the frame's instructions minus the record replay's, with the
tics the frame runs: {still_tics} standing still and {demo_tics} in the
demo, as the calls of `P_Ticker` count them. **P2'** also leaves out the
game tics phase (`P_Ticker` and its callees), and **P2''** is one tic: a
frame's game tics phase divided by its calls of `P_Ticker`, frame by frame.
A target that runs n tics a frame needs about P2' + n × P2''. The rest of
the work of a tic stays in P2': the tic commands, `G_Ticker` outside
`P_Ticker` and the tickers of the status bar and HUD, which are in
"Everything else".

**P4** is measured as the share of each window's instructions that its
{window_instructions} most executed instruction addresses cover, taken
over all the frames together. ARCHITECTURE.md section 3.5 sizes a phase
window at about 30 KB, "about 3,500 source instructions". The windows are
the phases of section 3.2 (the replay is hand-written and has none):

Standing still in E1M1:

{still_windows}

The title demo:

{demo_windows}

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
