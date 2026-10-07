# ref816: the reference machine

A 65816 core (`cpu816.c`) and a minimal Apple IIgs around it (`iigs.c`,
`doc.c`, `adb.c`) that runs upstream's release image from its entry point,
deterministically: the same image, disk, input and CPU rate give the same
run, byte for byte. The machine reads no host clock and nothing random.

The build uses it to take tables from upstream's own renderer:
`build.sh` builds the machine and the memory image, then
`tools/native/rendercap.py` runs the release on it and captures the
frames that `tools/native/rtables.py` and the level tools read.

| File | What it is |
| --- | --- |
| `cpu816.c`, `cpu816.h` | The 65816 core, cycle by cycle on the bus |
| `iigs.c`, `iigs.h` | Memory map, shadowing, soft switches, video timing, firmware traps, breakpoints |
| `doc.c`, `adb.c` | The DOC (the game's clock) and the ADB keyboard and mouse |
| `program.c`, `program.h` | The input program of a run: keys, mouse, shots, waits on memory |
| `main.c` | The command line: `build/ref816/ref816` (options at the top of the file) |
| `trace.c`, `trace.h` | The trace of a run (`--trace`) |
| `footprint.c`, `footprint.h` | Calls (`--call`) and captures of calls (`--capture`): what a routine reads and writes, to its return |
| `points.c`, `points.h` | Points of a run, for `--dump-at` and `--poke-file` |
| `inject.c`, `inject.h` | Pokes at points (`--poke-file`) and lumps placed in the game's WAD (`--wad`, `--lump`) |
| `calllog.c`, `calllog.h` | The call log (`--call-log`) |
| `make_image.py` | The memory that upstream's loader leaves, as a memory image |
| `refimage.py` | Memory images read back, and a sparse memory |
| `title.py` | The machine's files (`build/ref816/ref816`, `memory.img`, `disk.hdv`), built when missing |
| `keys.py` | The keys of the IIgs keyboard by name, as ADB key codes |
| `script.py` | Input scripts (below) compiled into the input program |
| `run_script.py` | What makes a run meaningless (below), and the stops and marks a run uses |
| `marks.py` | The log of marks and notes (`--mark`, `--marks`) read back |
| `dumps.py` | Dump streams read back, and points written with symbols |
| `calls.py` | Call logs read back, and routines written with symbols |
| `capture.py` | The choice of frames for the record replay (`R_DrawLists`) from a run's marks |
| `lumps.py` | The lumps of `DOOM1.WAD` by name, and the script of the title loop to a demo's end |
| `bounded.py` | `subprocess.run` with a time limit, a file-size limit and a CPU limit on the child |

Build:

    make -C tools/ref816              # build/ref816/ref816
    python3 tools/ref816/make_image.py

`make_image.py` writes `build/ref816/memory.img` (the state the loader
leaves on an 8 MB IIgs booting the release from a hard disk in slot 7),
`disk.hdv` (a copy of the disk the machine serves to the game's firmware
calls) and `loader.img` (the loader alone). Its options are `--image`,
`--linkmap`, `--out` and `--banks N` (a IIgs with RAM in banks `$00` to
N-1, which leaves the level store on the disk). The files hold upstream's
code and data and stay in `build/`.

## The machine

The CPU is an ideal 65816 on memory of uniform speed: every bus cycle takes
one CPU cycle, with no wait states for slow memory, I/O or refresh. Without
`--cpu-hz` a cycle takes 5 master clocks of 14.31818 MHz in the IIgs's fast
mode, 2,863,636 Hz; `--cpu-hz N` makes it N Hz (the master clock, and so the
video frames, the DOC and the game's clock, keep their rate). Slow mode
(`$C036` bit 7 clear), which the game does not use, stays at 14 master
clocks a cycle. A video frame is 912 x 262 master clocks, 59.92 frames a
second.

The machine has RAM in banks `$00-$7F` and `$E0-$E1`, no ROM image (a
read of the ROM or of a bank with no memory gives 0), and firmware traps
for the calls the game makes. An instruction is an opcode fetch (MVN and
MVP fetch theirs again for each byte they move).

    build/ref816/ref816 [options] IMAGE

The main options (the full list is at the top of `main.c`):

| Option | Meaning |
| --- | --- |
| `--frames N`, `--cycles N` | stop when video frame N starts, or after N CPU cycles (at least one) |
| `--cpu-hz N` | the CPU rate (above) |
| `--stop-pc ADDR` | stop before the instruction at ADDR (hex; repeatable) |
| `--stop-on-fault` | stop after a branch to itself, WDM or STP |
| `--mark ADDR`, `--marks FILE` | log each arrival at ADDR (`marks.py` reads the log) |
| `--disk FILE`, `--disk-out FILE` | the disk the firmware traps serve, and the disk with the game's writes at the end |
| `--input FILE` | the input program (`program.h`) |
| `--shot-frame N`, `--shot-cycle N`, `--shot-dir DIR` | screen dumps: `$E1:2000-$9FFF` then `$C034` and `$C029`, as `.shr` files |
| `--peek ADDR:LEN`, `--state FILE`, `--dump-ram FILE` | memory in the final state; the state (JSON); all RAM at the end |
| `--load ADDR:FILE`, `--load-image FILE` | bytes into RAM after the image, with no I/O or shadowing, in the order given |
| `--reg NAME=VALUE` | a register after the image and the loads: `a`, `x`, `y`, `s`, `d`, `pc`, `pbr`, `dbr`, `p`, `e`; hex |
| `--save ADDR:LEN:FILE` | LEN bytes of RAM from ADDR to FILE at the end |

A memory image (`refimage.py`) is a 32-byte header, `REF816I1` then the
registers and the soft switches, then records: a 32-bit address, a 32-bit
length and the bytes, all little-endian.

## Input scripts

A script is a text file with one action a line; `#` starts a comment.
`script.compile_script` turns it into the machine's input program, a list
of steps at frame starts (`program.h` gives its format).

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
| `shot NAME` | a screen dump `NAME.shr` (letters, digits, `-`, `_`) |
| `note NAME` | a point of the run, logged with the marks |
| `wait [byte\|word\|long] SYMBOL TEST VALUE [within TIME]` | the first frame from now at which the value passes TEST: `==`, `!=`, `>=` or `<` VALUE, or `grows` VALUE (by that much since the wait began); the run fails when it has not within TIME (frames or seconds, default 120 s) |
| `poke [byte\|word\|long] SYMBOL VALUE` | write a value to memory |
| `stop` | the end of the run; a script must end with it |

A SYMBOL is a label of the game from upstream's link map: `name`, or
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
code `0x00`-`0x7f`. The full list is in `keys.py`. Upstream's default
bindings are PC Doom's: the arrows move and turn, `control` fires, `space`
and `e` use, `shift` runs, `option` and `command` strafe with the arrows,
`,` `.` `a` `d` strafe, `w` `s` move, `1`-`7` pick a weapon, `tab` the map,
`escape` the menu, `return` chooses in the menus. Mouse button 0 fires,
button 1 strafes.

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

The scripts in `coverage/`:

| Script | What it does |
| --- | --- |
| `title.script` | The title page, then the demo (demo3, in E1M7) for 25 seconds, a shot every 5 |
| `newgame.script` | A new game at the default skill through the menus; 10 seconds standing in E1M1; strafe, walk, turn, fire, open the first door, walk through |
| `tour.script` | The nine maps of episode 1 through the level cheat, 5 seconds and a shot in each, in god mode |

In upstream's port `idclev` takes no map number: it ends the level, and the
level after map N is N + 1. E1M9 comes only after the secret exit of E1M3,
so `tour.script` stands in for that exit with a `poke` of the
intermission's next map.

## What makes a run meaningless

`run_script.problems` reports a problem for

- the game's error or quit screen (the run stops at `I_Error` and
  `I_Quit`), with its text;
- a branch to itself, WDM or STP (`--stop-on-fault`);
- a wait of the script that times out, and a run that ends before the
  script's `stop`;
- an I/O register the machine does not model, but `$C039` (the serial
  controller, which the game only switches off), a write to ROM, a slot ROM
  read, a write to a bank with no memory, an ADB command the model does not
  know, a firmware error;
- a read of the ROM or of a bank with no memory outside `KNOWN_READS`:
  `IIGS_StartInterrupts` copying the ROM's vectors, and `bmAccelOff`
  reading the first byte of the TransWarp GS signature;
- a main loop that does not come round (no call of `displayCall` of
  `d_main65.s`) for 200 million CPU cycles after its first time.

BRK and COP are not faults: they go through the vectors the game sets.
Upstream's `R_InitLists` returns into 14 bytes of zero padding, which run as
7 BRKs whose vector is an `rti`.

## Calls and captures

    ref816 IMAGE [--load ...] [--reg ...] --call ADDR [--call-reads FILE]
           [--call-writes FILE] [--save ...] [--cycles N]

runs the routine at ADDR (PBR and PC; hex) on the state of the image, the
loads and `--reg`, and ends the run when it returns: at the RTS, RTL or RTI
that leaves it at call depth 0 (end reason `return`). The depth goes up at
each JSR, JSL, JSR (a,x), BRK, COP and interrupt entry and down at each
RTS, RTL and RTI, so a routine needs no return address of its own on the
stack. Without `--frames` or `--cycles` a call may take 1,000,000,000
cycles. The final state gets a `call` member: whether it returned, the
registers at the start and the return, its own instructions and cycles
(without interrupts), the bytes it read before writing them and the bytes
it wrote. `--call-reads FILE` writes the bytes read first as a memory
image (`--call` on it alone runs the call again, as long as it takes the
same path); `--call-writes FILE` the bytes written. The machine starts a
`--call` with the DOC and the ADB quiet.

    ref816 ... --capture DIR --capture-entry ADDR --capture-hit N ...

counts the calls of the routine at ADDR from 1 and records each chosen
call into `DIR/hit-NNNNNNNN/`: `entry.img` (all RAM at the entry, with
the registers), `reads.img`, `writes.img`, `exit.img` and `call.json`.
The run exits with status 2 when a chosen call does not come or does not
return. Recording a call changes nothing of the run.

`--call` and `--capture` go in separate runs, and neither goes with
`--trace` (they share the machine's hooks).

## Points, dumps, pokes and call logs

Many states and many calls from one run. None of them changes the run,
except for the memory a poke or a lump writes on purpose.

### Points

A point is KEY=VALUE items separated by commas (`points.h`). The first
says what it is:

| First item | The point |
| --- | --- |
| `pc=ADDR` | each time the CPU reaches ADDR (hex, PBR and PC), before the instruction there |
| `frame=SET` | the start of each video frame of SET, after the steps of the input due then |
| `cycle=SET` | for each N of SET, the first instruction boundary at which the CPU has made N cycles or more |

Then, in any order: `hits=SET` (pc only: which arrivals, from 1; default
all), `after=NOTE` (only once the input's note NOTE has come),
`if=ADDR:SIZE:TEST:VALUE` (only when the 1-, 2- or 4-byte value at ADDR
passes `eq`, `ne`, `lt`, `le`, `gt` or `ge` VALUE, unsigned) and, for
dumps, `ranges=R+R...` (a bank `BB`, banks `BB-BB`, or `ADDR:LEN`; all
RAM by default). SET is `N`, `N-M`, `N-M/K`, `N-/K` or `all`. An arrival
that fails `after` or `if` is not a hit. `dumps.resolve` writes the
addresses of `pc`, `if` and `ranges` from symbols of the link map
(`pc=G_Ticker,if=_g_gametic:4:ge:1200`).

### --dump-at and the dump stream

    ref816 ... --dump-at POINT [--dump-at POINT ...] --dump-stream FILE

dumps memory each time a point fires, into one stream (`-` for stdout,
with `--state`): a line of JSON, `{"format": "ref816-dump-stream 1",
"points": [...]}`; for each dump a line of JSON followed by its bytes;
and a last line `{"end": REASON, "dumps": N}`. A dump's line has `dump`
(from 1), `point` (the index of its `--dump-at`, from 0), `hit`, `note`
(the last note of the input), `frame`, `clock`, `cycles`,
`instructions`, `cpu`, `switches`, `peek`, `ranges` (`[address, length]`
each) and `bytes`, the length of what follows. `dumps.read` yields the
dumps one at a time; `dumps.Stream` reads a whole file.

**Bounds.** A dump of all RAM is 8.5 MB, and a point such as `cycle=all`
fires thousands of times a second. The stream may grow to `--dump-limit
BYTES` (default 1 GiB) and hold `--dump-max N` dumps (default: no
count). A dump that would pass either is not written: the stream ends
with `{"end": "dump-limit"}` or `{"end": "dump-max"}` and the run fails
with status 2. The machine also fails (status 2) rather than fire again
at one moment for ever.

### --poke-file

    ref816 ... --poke-file FILE

writes memory at points of the run. A line of the file is `POINT ADDR
DATA` (`#` starts a comment): DATA is hex bytes, or `@PATH`, the bytes of
a file (relative to the poke file). The bytes go into RAM as `--load`
puts them. At a moment where several fire, the pokes come first, in the
order of their lines, then the dumps. A pc point writes before the
instruction at its address runs.

### --wad and --lump

    ref816 ... --wad 100000 --lump DEMO3:7E0000:FILE

puts the bytes of FILE at `$7E:0000` and points the directory entry
`DEMO3` of the game's WAD in RAM (at `$10:0000`) there. The title loop
asks for "demo3" by name, so a lump placed under that entry plays in its
place (DEMO1 and DEMO2 of `DOOM1.WAD` do not fit over DEMO3 in the
resident WAD). The machine refuses a name the directory has not exactly
once, a place outside RAM or across a 64 KB bank, and a place that is
not all zero. `lumps.read_wad` reads the lumps; `lumps.demo_script(map)`
is the title loop played to the demo's end.

### --call-log

    ref816 ... --call-log ROUTINE [--call-log ROUTINE ...] --call-log-file FILE

logs every call of each ROUTINE, `ADDR[,KEY=VALUE...]` (`calllog.h`):

| Key | Meaning |
| --- | --- |
| `name=NAME` | its name in the log |
| `in=R+R...`, `out=R+R...`, `mem=R+R...` | memory read at the entry, at the return, or both: `ADDR:LEN`, `d+OFF:LEN` (bank 0, D + OFF) or `s+OFF:LEN` (bank 0, S + OFF after the call instruction: `s+1:3` is a JSL's return address); d and s addresses are fixed at the entry |
| `jumps=1` | a JMP or JML that lands on ADDR is a call too (thinker functions, entered by `JML [dp]`) |
| `entry=1` | log the entry only: no return, no out |
| `hits=`, `after=`, `if=` | which calls, as for points (`if` at the entry) |

A call starts after the JSR, JSL or JSR (a,x) (or, with `jumps=1`, the
jump) that reaches ADDR, and returns at the first RTS, RTL, RTI or
firmware trap after which S is above S at the entry. Calls made inside
interrupts are logged like the others, with `irq` above 0. The log may
grow to `--call-log-limit BYTES` (default 1 GiB); the line that passes it
ends the run with status 2. `--call-log` goes with neither `--trace`,
`--call` nor `--capture`.

**Format** (`ref816-call-log 1`, JSON lines). The first line lists the
routines: index, name, entry, jumps, entry_only, and their in and out
ranges. Then a line for each call, written when it returns (a callee
before its caller), or at its entry with `entry=1`:

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
`hit` is the routine's own count; `from` is the address of the calling
instruction; `via` is `jsr`, `jsl`, `jsr_x`, `jmp`, `jml`, `jmp_ind`,
`jmp_x` or `jml_ind`; `parent` is the innermost logged call open at the
entry (0 for none) and `depth` how many are open. `mem` is a hex string a
range. A call still open when the run ends has `"returned": false`; an
`entry=1` line has `"out": null`. The last line is `{"end": true,
"calls": N, "arrivals": [...]}`.

`calls.resolve` and `calls.options` write routines with symbols, and
ranges of the direct page as the game's code writes them: `dp:SYMBOL:LEN`
is D plus SYMBOL's offset from the base of the direct page (the section
`ztiny`). Upstream's `FixedMul` (a in X:C, b in `_Dp[0-3]`) is
`FixedMul,in=dp:_Dp:4`. `calls.read` reads a log back.

## Traces

`--trace FILE` makes the machine write a trace of the run (the format is
at the top of `trace.h`); without it the machine calls no trace code. The
trace records frames of the game, from one call of `--trace-frame ADDR` to
the next, between the notes `--trace-from` and `--trace-to` of the input.
For each frame and each phase (`--trace-phase NAME=ADDR`: from a call to
one of its entries to the return with S as it was) it gives instructions
and cycles, memory accesses by kind (opcode and operand fetches, direct
page, stack, data by bank, I/O, vectors), the data lines and pages
touched, far-bank changes (outside the banks of `--trace-near`), stack
depth (`--trace-stack-split`), writes to the super hi-res screen, the
instructions by address, opcode and width. `--trace-samples FILE` writes
one instruction in `--trace-sample-every N` (499 by default) whole, with
its registers and the bytes it read and wrote.
