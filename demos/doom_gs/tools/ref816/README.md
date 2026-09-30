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
| `footprint.c`, `footprint.h` | Calls (`--call`) and captures of calls (`--capture`): what a routine reads and writes, to its return |
| `refimage.py` | Memory images: read, write, and a sparse memory |
| `lists.py` | Upstream's column records (`lists.inc`) decoded from memory |
| `capture.py` | Captures of the record replay (`R_DrawLists`) at the frames of milestone 5, into `build/captures/` |
| `points.c`, `points.h` | Points of a run (a routine's entry, a frame, a cycle count, with hits, a note and a memory test), for `--dump-at` and `--poke-file` |
| `inject.c`, `inject.h` | Pokes at points (`--poke-file`) and lumps placed in the game's WAD (`--wad`, `--lump`) |
| `calllog.c`, `calllog.h` | The call log (`--call-log`): each call of chosen routines, registers and declared memory at entry and return |
| `dumps.py` | Dump streams read back, points written with symbols, and the check against the two-run method |
| `calls.py` | Call logs read back, routines written with symbols, and a command that logs routines through a script or a demo |
| `lumps.py` | DEMO1 and DEMO2 of `DOOM1.WAD` placed as DEMO3, and the title loop played to a demo's end |
| `divscan.py` | The scan for division by zero over the coverage scripts and the three demos |

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

## Calls and captures

These are for milestone 5 and later (`docs/NATIVE.md` section 11): the
reference's own routines as the oracle of the native ones.

### Loading and saving memory

| Option | Meaning |
| --- | --- |
| `--load ADDR:FILE` | the bytes of FILE into RAM at ADDR (hex), after the image, with no I/O or shadowing |
| `--load-image FILE` | the records of the memory image FILE (its registers and switches are not used) |
| `--reg NAME=VALUE` | a register after the image and the loads: `a`, `x`, `y`, `s`, `d`, `pc` (16 bits), `pbr`, `dbr`, `p` (8 bits), `e` (0 or 1); VALUE in hex |
| `--save ADDR:LEN:FILE` | LEN bytes of RAM from ADDR to FILE at the end of the run (LEN decimal, or `0x` hex) |

Loads happen in the order given, so a later one overwrites an earlier
one (a poisoned screen over a captured one, say). They work in any run.

### --call

    ref816 IMAGE [--load ...] [--reg ...] --call ADDR [--call-reads FILE]
           [--call-writes FILE] [--save ...] [--cycles N]

runs the routine at ADDR (PBR and PC; hex) on the state of the image,
the loads and `--reg`, and ends the run when it returns: at the RTS, RTL
or RTI that leaves it at call depth 0 (end reason `return`). The depth
goes up at each JSR, JSL, JSR (a,x), BRK, COP and interrupt entry and
down at each RTS, RTL and RTI (and at a firmware trap, which returns for
its JSR), so a routine needs no return address of its own on the stack:
it returns into whatever its stack holds, and the run stops there.
Without `--frames` or `--cycles` a call may take 1,000,000,000 cycles.
The final state gets a `call` member:

| Field | Meaning |
| --- | --- |
| `returned`, `depth` | whether it returned, and the depth when the run ended |
| `start`, `end` | the registers (and the shadow register) at the start and at the return |
| `instructions`, `cycles` | the routine's own, without the interrupts inside it |
| `interrupts` | their count, instructions and cycles |
| `bytes_read` | bytes of RAM read before the call wrote them |
| `bytes_written` | bytes of RAM written (with the bytes of `$E0`/`$E1` that the shadow register copied them to) |
| `written_then_changed` | of those, the ones an interrupt inside the call wrote again later |
| `io`, `rom_reads`, ... | I/O registers by address, ROM and missing memory |

`--call-reads FILE` writes the bytes read first, with the values read
and the registers and switches at the start, as a memory image: `--call`
on it alone runs the call again, as long as it takes the same path.
`--call-writes FILE` writes the bytes written, with the values the call
wrote last and the registers and switches at the return. What an
interrupt does inside the call is left out of both (`footprint.h`).
The machine starts a `--call` with the DOC and the ADB quiet, so no
interrupt comes unless the routine starts one.

`--call` goes with neither `--trace` nor `--capture` (they share the
machine's hooks).

### --capture

    ref816 ... --capture DIR --capture-entry ADDR --capture-hit N ...

counts the calls (JSR, JSL, JSR (a,x)) of the routine at ADDR from 1 in
the run, and records each call whose number is given (`--capture-hit`,
repeatable) into `DIR/hit-NNNNNNNN/`:

| File | Content |
| --- | --- |
| `entry.img` | all RAM when the routine starts (after the call instruction), with the registers and switches: `--call ADDR` on it runs the call alone |
| `reads.img`, `writes.img` | as `--call-reads` and `--call-writes` |
| `exit.img` | the bytes written, with their values at the return (`writes.img` but for what interrupts wrote after the call) |
| `call.json` | `hit`, `entry`, the last `note` of the input before it, `frame`, `clock`, `cycles` and `instructions` of the machine at the entry, and `call` as above |

The run exits with status 2 when a chosen call does not come or does
not return before the run ends. Recording a call changes nothing of the
run: `capture.py` checks that the capturing run ends with the RAM and
the log of marks of a run without it.

### Replay captures: capture.py

    python3 tools/ref816/capture.py [--out DIR] [--sets still,demo,e1m3]
                                    [--keep-raw] [--no-verify]

makes the frame set of milestone 5 in `build/captures/`: `still-1` to
`still-3`, the first three calls of `R_DrawLists` after the note `still`
of `coverage/newgame.script` (standing in E1M1); `demo-01` to `demo-11`,
eleven calls spread evenly from the note `demo` to `demo-25s` of
`coverage/title.script` (demo3, E1M7); `e1m3-1`, the first call after
the shot `e1m3` of `coverage/tour.script` (the tool puts a note after
that line of the script, which changes nothing of the run). The last
call of a run is never chosen: the run may end before it returns.

Each script runs twice, with `run_script.py`'s checks: once with
`--mark` at `R_DrawLists` and `drawAllL` (an early flush of the lists)
to choose the calls, once with `--capture`. Each raw capture is then
distilled into one directory a frame, and the raw files are deleted
(`--keep-raw` keeps them in `DIR/raw/`). The files of a frame, all
places from the link map:

| File | From | Content |
| --- | --- | --- |
| `records-00.bin`, `records-20.bin`, `records-a0.bin` | `$1D:0000`, `$1D:2000`, `$1D:A000` | the pages the column lists can use (`lists.inc`: the home pages `COLPAGE(c)` and the extra pages `XP_FIRST`-`$FF`), 53,760 bytes |
| `lists.bin` | `COLW` | `COLW` (the end of each list), `XPNEXT`, `colOrder` |
| `screen.bin` | `$E1:2000` | the SHR screen: pixels, SCBs, palettes (32 KB) |
| `buffer.bin` | `$01:2000` | bank `$01` `$2000-$9FFF`, where the drawers write with SHR shadowing on |
| `spans.bin` | `FS_ROW` | the fill spans (`FS_ROW`, `FS_EVEN`, `FS_ODD`, `FS_STAMP`) and the covered ranges (`CV_ROW`, `CV_REC`) |
| `weapon.bin` | `WCLIP` | the weapon skip: `WCLIP`, `WPREV`, `WTMP` |
| `colormaps.bin` | `iigs_shrcmapA` | both colormaps, 17,408 bytes; the manifest lists the pages the records use |
| `fuzz.bin` | `FUZZ_DARKEN` | the shadow drawer's darkening table, 256 bytes (all of it: on another screen the drawer reads other entries) |
| `texels.img` | | an image: 128 bytes from the texel address of each `K_TEX` and `K_TEXC` record (the texel position is 7 bits), merged, by bank |
| `context.img` | | an image: every other byte the replay read before writing it (its code, the row blocks, the direct page, the stack, `TEXLO`/`TEXHI`, the view size flags), with the value read, and the registers and switches at the entry |
| `screen-after.bin`, `buffer-after.bin` | `$E1:2000`, `$01:2000` | the same after the replay |
| `writes.img` | | an image: every byte the replay wrote, with its value, and the registers at its return |
| `manifest.json` | | below |

`capture.call_options` gives the arguments that run the replay alone on
a frame: `context.img` as the image, then every "before" file loaded.
Unless `--no-verify`, the tool does so for each frame, and the replay
must return, write exactly the bytes of `writes.img` with the registers
at its return, leave `screen-after.bin` and `buffer-after.bin` byte for
byte, and take the instructions and cycles of the capture.

`manifest.json` holds `format` (`ref816-replay-capture 1`), `name`,
`script`, `note`, `hit` (the call of `R_DrawLists`, from 1),
`frame` (the video frame), `seconds` and `cycles` of machine time,
`gametic`, `entry` (`symbol`, `address`), `registers` and `switches` at
the entry, and `files`: for each, `name`, `file`, `when` (`before` or
`after` the replay), `what`, `format` (`raw`: its `size` bytes go at
`address`, also written `at` as `$BB:AAAA`; `image`: a memory image
whose records are `ranges`, `[address, length]`, `size` bytes in all)
and `sha256`. Then the measures: `records` (counts by kind, bytes,
extra pages used, `colormap_pages`), `early_flushes` (calls of
`drawAllL` since the frame before: records drawn early, which a capture
at `R_DrawLists` does not see), `replay` (instructions, cycles,
interrupts, bytes read and written, I/O, all without the interrupts),
`screen` (bytes of the pixels written, and bytes changed from before
to after, in the view, the pixels, the SCBs and palettes),
`context_by_bank`, `written_by_bank`,
`written_then_changed_by_interrupts` (the stack below S), `problems`
(empty when the capture is sound: every byte read first inside a named
file had its value at the entry, and no byte of the level window was
read outside the texels of the records), and `verified`.

`lists.py` walks the records (`lists.walk`) from any memory; the
capture uses it for the texels and the counts, and it refuses a record
of unknown kind or a list that does not reach its end.

`tests/test_ref816_call.py` checks `--call`, `--capture` and the
loading options on hand-made routines; `tests/test_ref816_capture.py`
captures three E1M1 frames and two demo frames and checks the manifest,
the `--call` oracle, and a run on a poisoned screen.

## Points, dumps, pokes and call logs

These are for milestone 6 (`docs/NATIVE.md` section 11, "Tool
additions"): many states and many calls from one run, instead of a rerun
from power-on for each. None of them changes the run: a run with them
ends with the RAM, the marks and the screen dumps of the same run
without them (tests of each below), except for the memory a poke or a
lump writes on purpose.

### Points

A point is KEY=VALUE items separated by commas (`points.h`). The first
says what it is:

| First item | The point |
| --- | --- |
| `pc=ADDR` | each time the CPU reaches ADDR (hex, PBR and PC), before the instruction there, as `--mark` |
| `frame=SET` | the start of each video frame of SET: its first instruction boundary, after the steps of the input due then (as `--frames` and `--shot-frame`) |
| `cycle=SET` | for each N of SET, the first instruction boundary at which the CPU has made N cycles or more (as `--cycles`) |

Then, in any order: `hits=SET` (pc only: which arrivals, from 1; default
all), `after=NOTE` (only once the input's note NOTE has come),
`if=ADDR:SIZE:TEST:VALUE` (only when the 1-, 2- or 4-byte value at ADDR
passes `eq`, `ne`, `lt`, `le`, `gt` or `ge` VALUE, unsigned) and, for
dumps, `ranges=R+R...` (a bank `BB`, banks `BB-BB`, or `ADDR:LEN`; all
RAM by default, in the order of `--dump-ram`). SET is `N`, `N-M`,
`N-M/K`, `N-/K` or `all`. An arrival that fails `after` or `if` is not
a hit, so `pc=03CEB7,after=cap,hits=1` is the first `G_Ticker` after the
note `cap`, and `pc=03CEB7,if=02C6AF:4:ge:1200,hits=1` the first
`G_Ticker` at gametic 1200 or later. `dumps.resolve` writes the
addresses of `pc`, `if` and `ranges` from symbols of the link map
(`pc=G_Ticker,if=_g_gametic:4:ge:1200`).

### --dump-at and the dump stream

    ref816 ... --dump-at POINT [--dump-at POINT ...] --dump-stream FILE

dumps memory each time a point fires, into one stream (`-` for stdout,
with `--state`): a line of JSON, `{"format": "ref816-dump-stream 1",
"points": [...]}`; for each dump a line of JSON followed by its bytes;
and a last line `{"end": REASON, "dumps": N}`. A dump's line has `dump`
(from 1), `point` (the index of its `--dump-at`, from 0), `hit` (the
arrival, or the frame or cycle count the point fired for), `note` (the
last note of the input), `frame`, `clock`, `cycles`, `instructions`,
`cpu` and `switches` as the final state has them, `peek` (the `--peek`
ranges at that moment, such as the gametic), `ranges` (`[address,
length]` each) and `bytes`, the length of what follows. `dumps.read`
yields the dumps of a file or a pipe one at a time; `dumps.Stream` reads
a whole file.

**Bounds.** A dump of all RAM is 8.5 MB, and a point such as `cycle=all`
or `pc=ADDR` without `hits=` fires thousands of times a second. The stream
may grow to `--dump-limit BYTES` (default 1 GiB) and hold `--dump-max N`
dumps (default: no count). A dump that would pass either is not written:
the stream ends with `{"end": "dump-limit"}` or `{"end": "dump-max"}`
and the run fails with status 2 and a message naming the point. Every
frame and cycle point moves on past the moment it fired for, and every
turn of the run's loop makes progress; the machine checks both and fails
(status 2) rather than dump or poke again at one moment for ever (on
2026-09-30 a planted bug in `points.c` that broke the first wrote a
90 GB stream before these checks existed).

**Check (milestone 6, acceptance 1).** `python3 tools/ref816/dumps.py
--verify` makes the six captures of `docs/research/native-verification.md`
section 3.1 both ways: the two-run method (a run with `--mark` for the
entries, then a run to the cycle count of the first entry after the note
`cap` with `--cycles` and `--dump-ram`), and one run of each script
with `--dump-at pc=ROUTINE,after=cap,hits=1` for `G_Ticker` and
`R_DrawLists`. All six dumps are equal byte for byte, all 8,519,680 bytes
of RAM, with the registers, cycles and instructions of the two-run
method, and the cycle counts are those of the section (172,980,261 and
172,583,162 for E1M1; 404,818,326 and 405,384,889 for E1M3; 261,613,133
and 262,188,510 for the demo). About 15 s. `tests/test_ref816_dump.py`
runs it, and checks hits, frames, cycles, notes, tests, ranges and the
stream format on a hand-made loop, each against the two-run method.

### --poke-file

    ref816 ... --poke-file FILE

writes memory at points of the run. A line of the file is `POINT ADDR
DATA` (`#` starts a comment): DATA is hex bytes, or `@PATH`, the bytes of
a file (relative to the poke file). The bytes go into RAM as `--load`
puts them: no I/O and no shadowing. At a moment where several fire, the
pokes come first, in the order of their lines, then the dumps. A pc
point writes before the instruction at its address runs.

### --wad, --lump and lumps.py

    ref816 ... --wad 100000 --lump DEMO3:7E0000:build/ref816/lumps/DEMO1.lmp

puts the bytes of the file at `$7E:0000` and points the directory entry
`DEMO3` of the game's WAD in RAM (at `MM_WAD`, `$10:0000`) there: offset
`$7E0000 - $100000`, the file's size. The release's resident WAD names
DEMO3 only, and DEMO3 at `$10:8984` is followed by `M_DOOM` and
`TEXTURE1`, so DEMO1 (20,118 bytes) and DEMO2 (15,358) cannot go over it;
the title loop asks for "demo3" by name, so a lump placed under that
entry plays in its place. The machine refuses a name the directory has
not exactly once, a place outside RAM or across a 64 KB bank (upstream
uses lumps in place, never across banks), and a place that is not all
zero.

`python3 tools/ref816/lumps.py DEMO1` prints the options (`--dest` for
another place); `--play` runs the title loop with the lump to the demo's
end (`lumps.demo_script`) and reports the tics it lasted. Measured:
DEMO1 plays E1M5 for 5,026 tics and DEMO2 E1M3 for 3,836 tics, the
counts of their lumps, to their end marker, without a problem. The
default place, bank `$7E`: upstream's level loader takes its window
banks below `MM_MUSBANK` (`$6A`) and the songs follow it; at the end of
all four coverage scripts, banks `$79-$7F` hold only the two bytes of the
loader's memory probe at `$bb:8000`. `tests/test_ref816_inject.py`
checks that DEMO3 placed at `$7E:0000` under its own entry gives the
release's run mark for mark, with the same screen dumps, and that DEMO1
starts E1M5.

### --call-log

    ref816 ... --call-log ROUTINE [--call-log ROUTINE ...] --call-log-file FILE

logs every call of each ROUTINE, `ADDR[,KEY=VALUE...]` (`calllog.h`):

| Key | Meaning |
| --- | --- |
| `name=NAME` | its name in the log |
| `in=R+R...`, `out=R+R...`, `mem=R+R...` | memory read at the entry, at the return, or both: `ADDR:LEN`, `d+OFF:LEN` (bank 0, D + OFF, the direct page) or `s+OFF:LEN` (bank 0, S + OFF after the call instruction: `s+1:3` is a JSL's return address); d and s addresses are fixed at the entry |
| `jumps=1` | a JMP or JML that lands on ADDR is a call too (thinker functions, entered by `JML [dp]`) |
| `entry=1` | log the entry only: no return, no out |
| `hits=`, `after=`, `if=` | which calls, as for points (`if` at the entry) |

A call starts after the JSR, JSL or JSR (a,x) (or, with `jumps=1`, the
jump) that reaches ADDR, and returns at the first RTS, RTL, RTI or
firmware trap after which S is above S at the entry. An interrupt inside
a call returns with S at or below it, so it does not end the call; calls
made inside interrupts are logged like the others, with `irq` above 0.

The log may grow to `--call-log-limit BYTES` (default 1 GiB): the line
that passes it is the last, and the run fails with status 2.

**Format** (`ref816-call-log 1`, JSON lines). The first line lists the
routines: index, name, entry, jumps, entry_only, and their in and out
ranges (`{"base": "abs"|"d"|"s", "offset", "length"}`). Then a line for
each call, written when it returns (a callee before its caller), or at
its entry with `entry=1`:

    {"call": 12, "routine": 0, "hit": 3, "from": 205847, "via": "jsl",
     "parent": 0, "depth": 0, "irq": 0, "frame": 6357,
     "cycles": 303834455, "instructions": 79176734,
     "in": {"pc": 353192, "a": 12954, "x": 65498, "y": 65498, "s": 16365,
            "d": 2304, "dbr": 2, "p": 128, "e": 0,
            "mem": ["6ddb0200"]},
     "out": {"exit": "rtl", "pc": 205851, "a": 65125, "x": 65427, ...,
             "cycles": 303834863, "instructions": 79176861,
             "interrupts": 0, "mem": []},
     "returned": true}

`call` numbers the logged calls from 1 in the order of their entries;
`hit` is the routine's own count (as `hits=` counts); `from` is the
address of the calling instruction; `via` is `jsr`, `jsl`, `jsr_x`,
`jmp`, `jml`, `jmp_ind`, `jmp_x` or `jml_ind`; `parent` is the innermost
logged call open at the entry (0 for none) and `depth` how many are
open; `irq` counts the interrupts open. `frame`, `cycles` and
`instructions` are the machine's at the entry; those of `out` at the
return, interrupts included. `mem` is a hex string a range. A call still
open when the run ends has `"returned": false` and `"exit": null`, with
the registers of the end; an `entry=1` line has `"out": null`. The last
line is `{"end": true, "calls": N, "arrivals": [...]}`, the calls of each
routine that passed `after` and `if`, logged or not. The log uses the
step hook, so it goes with neither `--trace`, `--call` nor `--capture`.

**Routine oracles from real play.** `calls.py` writes routines with
symbols, and ranges of the direct page as the game's code writes them:
`dp:SYMBOL:LEN` is D plus SYMBOL's offset from the base of the direct
page (the section `ztiny`; `.tiny` in `tools/v816/expr.py`). For
example, upstream's `FixedMul` takes a in X:C and b in `_Dp[0-3]` and
returns X:C (`m_fixed65.s`):

    python3 tools/ref816/calls.py title "FixedMul,in=dp:_Dp:4"
    python3 tools/ref816/calls.py DEMO1 "FixedMul,in=dp:_Dp:4" \
        "P_AproxDistance,in=dp:_Dp:4"

log each call's registers and `_Dp[0-3]` at the entry and the registers
at the return, through the title script or the whole of DEMO1, into
`build/ref816/calls/`. `calls.calls(path)` yields each call with its
memory as bytes. Declare what a routine reads beyond its registers with
`in=`, and what it writes with `out=`, from its source's header comment;
the test `test_fixed_mul_is_exact_on_every_call_of_the_title_demo`
checks every logged `FixedMul` of the title demo against the exact
product, as an example. Never log the outputs of the vendor runtime's
routines (`cal_integer.s`): the owner ruled out testing them as black
boxes; `divscan.py` logs their entries only (`entry=1`).

### Division by zero: divscan.py

    python3 tools/ref816/divscan.py [--jobs 2] [--runs title,DEMO1,...]

runs the four coverage scripts and the title loop to the end of each of
the three demos (DEMO1 and DEMO2 placed by `lumps.py`) with a call log of
the game's five integer divides, entries only, and reports every call
with a zero divisor, by call site and source line, into
`build/ref816/divscan/report.json`. The routines and where each takes its
divisor come from the game's own call sites, never from `cal_integer.s`:
`_UDivMod16`, `_Div16` and `_Mod16` take the dividend in A and the
divisor in X (`i_viigs65.s:1371-1373`, `p_floor65.s:1222-1224`,
`p_enemy65.s:592-594`); `_UDivMod32` and `_Div32` take them in `_Dp[0-3]`
and `_Dp[4-7]` (`g_game65.s:808-816`, `s_sound65.s:643-647`). A call site
is placed on its line through the nearest label of the link map and the
count of JSL instructions to the routine after it (`--sites` prints the
46 sites of the sources, all found in the image). The tests forbid the
scan to open `cal_integer.s`.

**Result, 2026-09-30:** 50,753 calls from the game's code, at 31 of the
46 call sites, and **no zero divisor**, in title (3,691 calls), newgame
(3,807), viewsize (3,859), tour (6,485), DEMO1 (15,296), DEMO2 (9,432)
and DEMO3 (8,183); D was `$0900` at every call, and no call came from
inside the vendor runtime. The 15 sites no run reached:
`p_floor65.s:1224`, `r_wall65.s:1585`, `g_game65.s:1356`,
`g_game65.s:1397`, `r_iigs65.s:410`, `r_iigs65.s:1134` (the slow paths
of `R_PointToAngle3` and its older twin), `f_finale65.s:187`, the six of
`m_menu65.s` (the benchmark) and `am_map65.s:2694` and `:2714` (the
automap's clipping). About 25 s with 2 jobs.
