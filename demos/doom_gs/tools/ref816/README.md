# ref816: the reference machine

A 65816 core (`cpu816.c`) and a minimal Apple IIgs around it (`iigs.c`,
`doc.c`, `adb.c`) that runs upstream's release image from its entry point,
deterministically: the same image, disk, input and CPU rate give the same
run, byte for byte. The machine reads no host clock and nothing random.

| File | What it is |
| --- | --- |
| `cpu816.c`, `cpu816.h` | The 65816 core, cycle by cycle on the bus |
| `iigs.c`, `iigs.h` | Memory map, shadowing, soft switches, video timing, firmware traps, breakpoints |
| `doc.c`, `adb.c` | The DOC (the game's clock) and the ADB keyboard and mouse |
| `program.c`, `program.h` | The input program of a run: keys, mouse, shots, waits on memory |
| `main.c` | The command line: `build/ref816/ref816` (options at the top of the file) |
| `make_image.py` | The memory that upstream's loader leaves, as a memory image |
| `shot.py` | Screen dumps to PNG, and the statistics of the game's view |
| `keys.py` | The keys of the IIgs keyboard by name, as ADB key codes |
| `script.py` | Input scripts (below) compiled into the input program |
| `marks.py` | The log of marks and notes, and frame rates from it |
| `run_script.py` | Runs a script, collects its shots, checks and reports the run |
| `title.py` | Boots to the title screen and measures the game clock |
| `trace.c`, `trace.h` | The trace of a run (`--trace`): phases, accesses, code heat, widths, writes to code, stack, screen |
| `tracefile.py` | Reads a trace file |
| `codemap.py` | Addresses as places of the link map: section, source file, label |
| `measures.py` | The measures of a trace, frame by frame |
| `profile816.py`, `profile_template.md` | Traces two scenarios and writes `docs/PROFILE.md` |

Build and check:

    python3 tools/ref816/fetch_vectors.py
    make -C tools/ref816 vectors selftest machinetest
    python3 tools/ref816/title.py

## Input scripts

`run_script.py` runs a script on the release image and writes its shots
as PNG files to `build/ref816/shots/NAME/`, and the compiled program, the
final state, the log of marks and a report to `build/ref816/runs/NAME/`:

    python3 tools/ref816/run_script.py title newgame viewsize tour
    python3 tools/ref816/run_script.py newgame --cpu-hz 12000000 --twice

A name without a path is a script of `coverage/`. `--twice` runs it again
and checks that the RAM, the shots and the log come out the same.
`--cpu-hz` sets the CPU rate (below). The exit status is 1 when a run has a
problem (below).

A script is a text file with one action a line; `#` starts a comment.

    [at WHEN] ACTION ...

`at WHEN` says when the action happens; a line without it happens right
after the line before. WHEN is one of

| WHEN | Meaning |
| --- | --- |
| `N` or `Nf` | the start of video frame N since power-on (59.92 frames a second) |
| `Ns` | N seconds of machine time since power-on (N may have decimals), to the nearest frame |
| `Nt` | the first frame at which the game's tic count `_g_gametic` is N or more |
| `+N`, `+Nf`, `+Ns`, `+Nt` | that long after the line before |

Frames and seconds are machine time; tics are game time. The game runs at
most 4 tics a frame of its own, so on a slow CPU game time runs slower than
machine time: moves timed in tics come out about the same at any CPU rate,
moves timed in seconds do not. A tic time waits for the game (it compiles to
a `wait`, below, of up to half a second of machine time a tic).

The actions:

| Action | Meaning |
| --- | --- |
| `key down NAME`, `key up NAME` | a key of the keyboard |
| `press NAME [FRAMES]` | key down, and up FRAMES frames later (default 6); the next line counts from the key up |
| `type TEXT` | each letter or digit pressed for 4 frames, 4 frames apart (for the cheats) |
| `mouse DX DY` | mouse motion |
| `button down [0\|1]`, `button up [0\|1]` | a mouse button (default 0: the game's fire) |
| `shot NAME` | a screen shot `NAME.png` (letters, digits, `-`, `_`) |
| `note NAME` | a point of the run; the report measures the frame rate from each note to the next |
| `wait [byte\|word\|long] SYMBOL TEST VALUE [within TIME]` | the first frame from now at which the value passes TEST: `==`, `!=`, `>=` or `<` VALUE, or `grows` VALUE (by that much since the wait began); the run fails when it has not within TIME (frames or seconds, default 120 s) |
| `poke [byte\|word\|long] SYMBOL VALUE` | write a value to memory |
| `stop` | the end of the run; a script must end with it |

A SYMBOL is a label of the game from `build/linkmap.json`: `name`, or
`unit:name` when several source files have one of that name (such as
`m_menu65.s:itemOn`), or a number; `+offset` adds to it. The size is a word
unless `byte` or `long` comes first. VALUE is a whole number, `0x` for
hexadecimal. Waits make a script independent of the CPU rate where time
alone would not: wait for the menu the game shows, not for a second.

Key names are lower case: the letters and digits, `return`, `escape`
(`esc`), `space`, `tab`, `delete`, `control` (`ctrl`), `shift`, `capslock`,
`option`, `command`, `left`, `right`, `up`, `down`, `comma`, `period`,
`slash`, `minus`, `equals` and the other punctuation by name, `keypad0` to
`keypad9`, `keypadenter` and the other keypad keys, `f1` to `f15`, `help`,
`home`, `end`, `pageup`, `pagedown`, `forwarddelete`, `reset`; or an ADB key
code `0x00`-`0x7f`. The full list is in `keys.py`. The game's default
bindings (`keyDefaults` of `src/iigs/i_iigs65.s`) are PC Doom's: the arrows
move and turn, `control` fires, `space` and `e` use, `shift` runs, `option`
and `command` strafe with the arrows, `,` `.` `a` `d` strafe, `w` `s` move,
`1`-`7` pick a weapon, `tab` the map, `escape` the menu, `return` chooses in
the menus. Mouse button 0 fires, button 1 strafes.

An example, shortened from `coverage/newgame.script`:

    wait d_main65.s:pagedrawn == 1 within 90s   # the title page is up
    at +1s press escape                     # the main menu
    wait m_menu65.s:currentMenu == 0 within 10s
    press return                            # NEW GAME: the skill menu
    wait m_menu65.s:currentMenu == 2 within 10s
    at +3s shot skill
    press return                            # the default skill
    wait _g_gamestate == 0 within 10s       # the level
    wait long _g_gametic grows 1 within 60s # E1M1 has loaded
    key down up
    at +50t key up up
    shot walk
    stop

`script.py` compiles a script into the machine's input program, a list of
steps at frame starts (`program.h` gives its format); `run_script.py`
writes it to `build/ref816/runs/NAME/input.txt`, each step with the script
line it came from.

## What a run checks

`run_script.py` runs the machine with the game's `I_Error` and `I_Quit` as
stop addresses and `--stop-on-fault`, and reports a problem for

- the game's error or quit screen, with its text;
- a branch to itself (a CPU that only an interrupt could get out of);
- WDM or STP, which the game never uses: the CPU would be running data;
- a wait of the script that times out, and a run that ends before the
  script's `stop`;
- an I/O register the machine does not model, but `$C039` (the serial
  controller, which the game only switches off), a write to ROM, a slot ROM
  read, a write to a bank with no memory, an ADB command the model does not
  know, a firmware error;
- a read of the ROM or of a bank with no memory (the machine answers 0)
  outside `KNOWN_READS` of `run_script.py`. The machine keeps these reads by
  reading instruction, with the addresses read; a known read names the
  function that makes it and the symbol it reads, both found in the link
  map, and how many bytes it reads in a run. There are two: `irq65.s`
  `IIGS_StartInterrupts` copies the 32 bytes of the ROM's vectors from
  `VECTORS` before it maps RAM there, and `m_menu65.s` `bmAccelOff` reads
  the first byte of the TransWarp GS signature at `TW_ID` (bank `$BC`), once.
  `tests/test_ref816_machine.py` checks that a run meets exactly these;
- a main loop that does not come round (no call of `displayCall` of
  `d_main65.s`) for 200 million CPU cycles after its first time. The longest
  legitimate wait is a level load: up to 74 million cycles.

BRK and COP are not faults: they go through the vectors the game sets.
Upstream's `R_InitLists` (`src/iigs/r_list65.s`) returns from `initColw`
into 14 bytes of zero padding, which run as 7 BRKs whose vector is an `rti`
(`noEntry` of `src/iigs/irq65.s`), each skipping two bytes. The report
counts BRK and COP and names the first.

## CPU rate and frame measurements

The CPU is an ideal 65816 on memory of uniform speed: every bus cycle takes
one CPU cycle, with no wait states for slow memory, I/O or refresh. Without
`--cpu-hz` a cycle takes 5 master clocks of 14.31818 MHz in the IIgs's fast
mode, 2,863,636 Hz; `--cpu-hz N` makes it N Hz (the master clock, and so the
video frames, the DOC and the game's clock, keep their rate). Slow mode
(`$C036` bit 7 clear), which the game does not use, stays at 14 master
clocks a cycle.

The report gives, from each note of the script to the next, the 3D frames
drawn per second of machine time (calls of `R_RenderPlayerView`), and the
median instructions and cycles of one frame: from one call of
`R_RenderPlayerView` to the next, the game tics in between included. An
instruction is an opcode fetch (MVN and MVP fetch theirs again for each byte
they move).

Each shot also gets the statistics of the game's view (`shot.view_stats`):
the colours and the distinct rows of the view (rows 0-167), whether the
status bar (rows 168-199) has palettes of its own and rows of its own, and
the window of the view (the box of its pixels that are not black, 320x168 at
full size). `full_3d_view` is true for a full-size 3D view.

## The coverage scripts

| Script | What it does |
| --- | --- |
| `coverage/title.script` | The title page, then the demo (demo3, in E1M7) for 25 seconds, a shot every 5 |
| `coverage/newgame.script` | A new game at the default skill through the menus; 10 seconds standing in E1M1; strafe, walk, turn, fire, open the first door, walk through |
| `coverage/viewsize.script` | Every view size of DISPLAY & SOUND, FULL down to 1/4 and back, each checked on `VW_SIZE`, a shot at each |
| `coverage/tour.script` | The nine maps of episode 1 through the level cheat, 5 seconds and a shot in each, in god mode |

In this port `idclev` takes no map number: it ends the level, and the level
after map N is N + 1 (`src/iigs/m_cheat65.s`, `src/iigs/g_game65.s`). E1M9
comes only after the secret exit of E1M3, so `tour.script` stands in for
that exit with a `poke` of the intermission's next map, as the game's
`doCompleted` sets it for a secret exit.

`tests/test_coverage.py` runs the four scripts twice at the IIgs's rate and
`newgame.script` twice at 12 MHz, and checks their shots.

## Traces and profiles

`--trace FILE` makes the machine write a trace of the run (the format is
at the top of `trace.h`). Without it the machine calls no trace code: the
trace replaces the CPU's bus callbacks with its own and sets the step hook
of `iigs.h` only while it runs. The trace records frames of the game, from
one call of `--trace-frame ADDR` to the next, between the notes
`--trace-from` and `--trace-to` of the input. For each frame and each
phase it gives instructions and cycles, memory accesses by kind (opcode
and operand fetches, direct page, stack, data by bank, I/O, vectors), the
distinct 8-byte lines, 64-byte lines and pages of data touched in each
bank, the changes of bank between consecutive far accesses (outside the
banks of `--trace-near`), the lowest S above and below
`--trace-stack-split`, the writes that reach the super hi-res screen and
those that changed it, the instructions executed at each address, the
entries of each phase, and the cycles of the machine's firmware traps,
which run no instruction of the game and belong to no phase; the
instructions by opcode and by the widths (E, M, X) they ran with; and, in
a model of the code page cache of the interpreter of `src/vm` (16 pages
filled in turn), the program fetches that entered another page and those
that missed. Over the whole run it gives every write to a byte that runs
as code, and the (M, X), D and DBR values each instruction address ran
with. With `--trace-samples FILE` it also writes one instruction of the
recorded frames in `--trace-sample-every N` (499 by default) whole, with
its registers, every byte it read and wrote and the registers after it,
so that `tools/a2vm/game816` can run it again on the interpreter
(`tools/a2vm/interpreter_report.py`, which writes `docs/INTERPRETER.md`).

A phase (`--trace-phase NAME=ADDR`) starts with a call to one of its
entries and ends when the CPU is back after that call with S as it was;
an interrupt is a phase from its first push to its return. The core
tags each bus cycle with what its address is made from (`space` in
`cpu816.h`), which is how the trace tells the direct page, the stack
and data apart.

`python3 tools/ref816/profile816.py` runs `coverage/newgame.script`
(from its note `still` to `still-10s`) and `coverage/title.script`
(`demo` to `demo-25s`) traced at the IIgs's own CPU rate, when their
traces in `build/ref816/traces/` are missing or with `--run`, and writes
`docs/PROFILE.md` from them (tables of `measures.py` inside the text of
`profile_template.md`) and `build/ref816/widths.json`. The same traces
give the same files. Nothing of the vendor runtime (`cal_integer.s`)
reaches the report: `codemap.py` makes its code one anonymous place, and
`profile816.py` folds that place into an "others" row together with code
of the game, never alone and never as a row of its own, so that neither a
row nor a total minus the rows gives a figure of its own. The rows it
would have had go to `build/ref816/profile-withheld.json` only.
