# DOOM GS: the Apple IIgs DOOM on the Appletini 65C02

This is a port in progress of [Webifi's Apple IIgs DOOM](https://github.com/Webifi/iigs-doom)
to an enhanced Apple //e with an Appletini card. Upstream is a complete game,
about 82,000 lines of 65816 assembly. The Appletini's accelerator is a W65C02S,
so every instruction has to be translated, interpreted or rewritten.

**Status: planning and tooling. Nothing runs on the Apple yet.** Since
2026-09-30 the plan is a native 65C02 rewrite that keeps upstream's SHR
techniques, with music from the WAD's MUS songs on the Phasor. Progress and
the next steps are in [`docs/MILESTONES.md`](docs/MILESTONES.md).

It is separate from the existing port in [`demos/doom`](../doom/README.md),
which is a different engine written for cc65.

## What is here

| Path | Contents |
| --- | --- |
| `docs/MILESTONES.md` | The handoff brief: status, ground rules, results of each milestone, the next steps |
| `docs/NATIVE.md` | The architecture of the native rewrite: strategy by subsystem, memory map, verification, expected frame rates, milestones, risks and questions for the owner. Awaits the owner's review. |
| `docs/ARCHITECTURE.md` | The earlier draft architecture: a virtual 65816 machine on the 65C02. Superseded as the end state by the native rewrite; its facts and verification sections still hold. |
| `docs/INTERPRETER.md` | Measured cost of the 65816 interpreter of milestone 3, by opcode and by game phase |
| `docs/PROFILE.md` | Measured profiles of the game on the reference machine: instructions and cycles by phase, memory accesses by kind and bank, code heat, register widths, self-modification, stack and screen, and the architecture's performance assumptions measured. Written by `tools/ref816/profile816.py`. |
| `docs/design-proposals/` | The three independent proposals the architecture was drawn from, each with a correctness critique and a hardware critique |
| `docs/research/` | Reports on upstream's renderer and platform layer, on the Appletini hardware, and on the existing port |
| `docs/firmware/` | Plans and adversarial reviews for Appletini firmware changes that would speed up software like this. They are proposals; none is implemented. |
| `tools/` | Host tools (Python 3, standard library only): the fetch script, the front end and the assembler and linker for upstream's sources (`tools/v816/`) |
| `tools/ref816/` | The reference machine (C11): a 65816 core and its test harness, and a minimal IIgs that runs the release image |
| `tools/a2vm/` | The target model (C11): a W65C02S core, the //e with 128 RamWorks banks, the memory API, and a cost model of the Appletini's TURBO mode for F1.2.1 and for the firmware design, checked against a hardware capture |
| `src/vm/` | A 65816 interpreter in 65C02 assembly (ca65), measured in milestone 3; kept as a tool, not part of the game |
| `tests/` | Unit tests: `python3 -m unittest discover -s tests` |

## Image match

`python3 tools/fetch_upstream.py` fills `build/`. Then
`python3 tools/v816/imgmatch.py` assembles upstream's sources with the tools of
this port, recovers from the release image where the vendor's linker placed
each section fragment, links, and compares the result with the release byte
by byte. It writes `build/match-report.json` and `build/linkmap.json` (the
address of every fragment and the value of every symbol). Each placed
fragment in the link map has a `support` count, the number of independent
things in the image that give its address. The report's `single_evidence`
list names every number that rests on one reference only.

The research and firmware notes were written against Appletini firmware
F1.1.4 to F1.2.1 and upstream commit `8ea2eac`. Paths shown as `<upstream>`,
`<appletini-one>` and `<scratch>` refer to local checkouts, not to this
repository.

## Reference 65816 core

`tools/ref816/cpu816.c` is a 65816 core that makes the chip's valid bus
cycles in the chip's order and counts every cycle. It is checked against the
[SingleStepTests 65816 vectors](https://github.com/SingleStepTests/65816):

    python3 tools/ref816/fetch_vectors.py   # about 500 MB into build/vectors
    make -C tools/ref816 vectors            # all 5,120,000 cases
    make -C tools/ref816 selftest           # interrupts, WAI, STP, reset

The harness compares registers and memory, the cycle count and the sequence
of bus cycles. It lists by opcode the 44 cases where the vectors disagree
with the documented chip, with the evidence (`known_issues` in
`tools/ref816/vectors.c`).

## Reference machine

`tools/ref816/` also holds a minimal Apple IIgs around the core, with only
what upstream's game uses: 8 MB of RAM and banks `$E0`-`$E1`, the shadow
register, the soft switches the game writes, the vertical blank flag, the
Ensoniq DOC and its sound GLU (the game's clock), the ADB keyboard and mouse,
and traps for the slot firmware's block driver and SmartPort calls. It is
deterministic: the same image, disk and input give the same run. The game
starts at its entry point from the memory that upstream's loader would leave:

    python3 tools/ref816/make_image.py      # build/ref816/memory.img, disk.hdv
    make -C tools/ref816                    # build/ref816/ref816
    build/ref816/ref816 build/ref816/memory.img --disk build/ref816/disk.hdv \
        --frames 2401 --shot-frame 2400 --shot-dir build/ref816/shots
    python3 tools/ref816/shot.py build/ref816/shots/frame-002400.shr

`python3 tools/ref816/title.py` does all of this and reports the title
picture's statistics and the game clock's rate (about 35 tics per second of
machine time). The options of the machine (scripted keys and mouse, screen
dumps by frame or cycle, memory peeks, the final state with a hash of all
RAM) are at the top of `tools/ref816/main.c`, and the list of what the model
leaves out is in the headers (`iigs.h`, `doc.h`, `adb.h`). Tests:
`make -C tools/ref816 machinetest`, and `tests/test_ref816_machine.py`.

The game plays under script: `python3 tools/ref816/run_script.py SCRIPT`
runs an input script (keys, mouse, waits on the game's memory, shots) and
writes its shots to `build/ref816/shots/SCRIPT/`, with a report of the run
and of the game's frame rate. The format, the checks made on a run and the
CPU rate model are in [tools/ref816/README.md](tools/ref816/README.md); the
scripts that cover the title demo, a new game, the view sizes and the nine
maps are in `coverage/`.

`python3 tools/ref816/profile816.py` traces two of those runs (standing
still in E1M1, and the title demo) and writes
[docs/PROFILE.md](docs/PROFILE.md) from the traces, with the register
widths of every executed instruction in `build/ref816/widths.json`.

## Playing the game

`build/native/DOOM.hdv` is the whole game on one ProDOS volume: the title
loop with its music and demo, the menus, episode 1 from E1M1 with the
keyboard and the mouse, the status bar, the HUD, the automap, the
intermission, the music and the sound effects. Saving and loading say
"not in this version". It has been played on a2vm only; the owner's guide
for the card (the profile, the keys, the frame rates, the known problems)
is [`docs/PLAY.md`](docs/PLAY.md) section 12.

    python3 tools/fetch_upstream.py            # build/: upstream, the release, DOOM1.WAD
    # the other milestones' builds the disk takes (playdisk.py names any missing)
    python3 tools/native/playdisk.py           # build/native/DOOM.hdv (4.0 MB)

The machine: an Apple //e (PAL or NTSC) with the Appletini in TURBO mode,
8 MB RamWorks, the mouse card in slot 2, the Phasor in slot 4, and the
Doom profile (`vtw.slowdown.cycles=32`). Boot the `.hdv` as a ProDOS
volume: `DOOM.SYSTEM` loads everything from it and starts the title loop.

| Key | Does |
| --- | --- |
| Up, down arrows, `W` `S` | forward, back |
| Left, right arrows | turn |
| `A` `D`, `,` `.` | strafe |
| Open Apple, mouse button | fire |
| `E`, `SPACE`, `RETURN`, Solid Apple | use (`RETURN` also selects in the menus) |
| mouse left and right | turn |
| `1`-`7` | weapons |
| `TAB` | the automap, then its overlay, then off; `-` `=` zoom |
| `ESC` | the menu |

Run is the menu's OPTIONS, CONTROLS, ALWAYS RUN (the //e cannot see Shift
alone). The menu's KEY SETUP changes the keys. QUIT GAME ends on a text
screen.

## Licence

Everything in this directory is licensed under the GNU General Public
License, version 2 ([`LICENSE`](LICENSE)), as upstream is. The native port is
rewritten from upstream's source, so it is a derivative of it. The owner
chose this licence on 2026-09-30.

`tools/a2vm/py65core.h` holds tables from py65 under their own BSD licence,
which the header reproduces.

## What stays out of the repository

The build fetches a pinned clone of upstream and the v1.0 release image into
`build/`, which is ignored by git, and converts them there, as
[The Bilestoad](../bilestoad/README.md) does. Upstream's own files, the
release image, the shareware `DOOM1.WAD` (id Software's licence), ROM images
and third-party test vectors are never committed.

- `src/iigs/cal_integer.s` in upstream is a copy of the Calypsi vendor runtime.
  Its licence restricts it to that toolchain, so the port uses its own
  routines and keeps nothing derived from that file.
- The research notes quote short passages of upstream source for analysis.
