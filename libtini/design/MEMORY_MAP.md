# Linker and banked-memory layout

The two shared configurations make a raw ProDOS SYS file that ProDOS loads
and enters at $2000. They use the `none.lib` runtime of cc65 2.19 and the
startup code of the project. They use no language-card code and no overlays.

All address ranges in this file are inclusive. The build rejects segments
outside these regions. `build/layout.json` and the map files give the linked
sizes. Each build shows the free bytes of each linker memory area for each
game, and `build/memory.json` records them for every program. See
[GAMES.md](GAMES.md).

| MAIN range | Use |
| --- | --- |
| $0000-$007F | OS and firmware workspace |
| $0080-$0099 | cc65 zero page; saved at entry and restored before QUIT |
| $009A-$00FF | OS and firmware workspace |
| $0100-$013F | Lower hardware-stack workspace of ProDOS; not changed |
| $0140-$017F | Bank-transfer trampoline; the original bytes are saved and restored |
| $0180-$01FF | Hardware stack: 128 bytes, ProDOS IRQ dispatch included |
| $0200-$03FF | OS workspace and RESET vectors; not changed |
| $0400-$07FF | Text page 1; error output uses visible cells |
| $0800-$1FFF | Reserved in `cfg/libtini.cfg`; static read-only data and code in the full-game layout |
| $BF00-$BFFF | ProDOS globals and MLI; not changed |
| $C000-$CFFF | Existing switches and slots; no reassignment |
| $D000-$FFFF | ProDOS language card and ROM; not changed |

| Region | `cfg/libtini.cfg`: diagnostic, tests, starter | `cfg/game.cfg`: full game | STARFALL layout |
| --- | --- | --- | --- |
| Main code and state | $2000-$9FFF | $2000-$AEFF | $2000-$BA7F, with an overlay window |
| Guard | $AF00-$AFFF | $AF00-$AFFF | none |
| C software stack | $A000-$A7FF, top $A800 | $B700-$BEFF, top $BF00 | $BE00-$BEFF, top $BF00 |
| Private transfer stage | $A800-$A87F | $B400-$B47F | $BA80-$BAFF |
| Caller near arena, NEARBSS | $A900-$AEFF, 1536 bytes | $B480-$B6FF, 640 bytes | $BB00-$BDFF, 768 bytes |
| ProDOS aligned file buffer, `_ti_file_buffer` | $B000-$B3FF, 1 KiB | same | 1 KiB in the scene storage, before the scene starts |
| Other reserved space | $A880-$A8FF, $B400-$BEFF | none | none |

OSSTATE contains the launch flags, the saved zero page and the trampoline
bytes. Public near writes start after OSSTATE. Code, constants and the saved
OS state are read-only for the near APIs.

Writable DATA and BSS, free main space, the C stack and the near arena still
need object ownership by the caller. The runtime has no near allocator and no
collision detector.

The linker puts variables that an application declares in the `NEARBSS`
segment into the near arena of its layout. The linker rejects an overflow,
and startup zeroes these variables before BSS. The runtime puts nothing in
the near arena.

The full-game layout copies RODATA, AMEMCODE and LOWCODE to MAIN $0800-$1FFF
once. This copy occurs before the BSS clear and before the C stack starts.
The load bytes of these segments follow DATA in the SYS file.

That load image can overlap the BSS and stack areas, and it ends before
$BF00. It is not kept there. Low MAIN is ProDOS SYS memory that the
application owns. It contains constants, optional AMEM helpers and graphics
publication code, and it is read-only for the public near APIs.

The bank-switch loops always run from the safe page-one trampoline. A normal
exit restores the necessary OS state, not the low MAIN bytes of the
application.

The entry code of startup, up to the BSS clear, is in the ONCE segment. The
full-game layout puts ONCE directly after DATA, where BSS starts. The ONCE
code finishes before `zerobss` uses those bytes again, which gives 228 bytes
back to BSS. STARFALL's layout puts ONCE after its loader, in the overlay
window. The code that clears BSS, starts C and controls the exit is in
STARTUP.

The full-game layout has little free space with the optional AMEM build. Keep
the linker checks enabled when you extend it. Measure the two stacks when you
add foreground depth or IRQ nesting.

## STARFALL

STARFALL uses its own layout,
[`examples/starfall/starfall.cfg`](../examples/starfall/starfall.cfg). It
keeps code that it does not use all the time in RamWorks and copies it to an
overlay window to run it. See [GAMES.md](GAMES.md#overlays).

| MAIN range | Use |
| --- | --- |
| $0800-$1FFF | Sprite cells, speech, song, font, sound table; the song player, text and row-copy code, `animate`, `telemetry` and `render` |
| $2000 to the window | Resident code and data |
| The window, to $AC2F | One overlay at a time; at load time, `TIFILES` and the loader |
| $AC30-$BA7F | The scene storage, then BSS |
| $BA80-$BAFF | Transfer stage |
| $BB00-$BDFF | Near arena: the 566-byte game state, the variables of `game.c`, the star columns, the animated palette, text buffers, the boss's name and colors and the HUD's values |
| $BE00-$BEFF | C stack. STARFALL uses less than 100 bytes of it |

The build prints the bounds of each area. The window starts after the
resident code and data, at about $9600, and holds about 5.6 KiB.

| Overlay | Contents | In the window |
| --- | --- | --- |
| Title | The title screen, its cheat, the launch and `TISETUP` | From the load until the launch |
| Panels | The pause, clock-gap, game-over and missing-audio panels | In a pause and after the ship is lost |
| Play | The waves of normal sectors, and the cheat's start | In normal sectors |
| Boss | The bosses and their drawing, with the record and art of one boss | In boss sectors |

`STARFALL.PAK` holds the four overlays and the art of the five bosses, 37,175
bytes in one resource. The boss overlay's variables follow its code, and the
art of the boss follows them: the body strips, then one frame slot for each
weapon. The other boss frames stay in the resource. The game copies a frame
to its slot when the animation changes it, about 0.2 ms for each copy.

Startup loads the pack before graphics start, so the file calls need no
storage loan. The ProDOS file buffer is the first page-aligned 1 KiB of the
1,856 bytes of scene storage, which no code uses before `ti_scene_begin`.
After the load, STARFALL makes no file calls.

The 320x200 packed interface canvas is behind a banked handle. STARFALL
grants RamWorks selectors 1-3 for the pack, the canvas, the AUX0 display
backup and the temporary storage loan for ProDOS and the IRQ handler. The
peak of these allocations is 134,711 bytes of the 145,920. The game needs no
extra framebuffer and no sprite hardware.

During play, a libtini sprite scene composes the changed blocks in near
memory, eight lines at a time. It publishes them with normal CPU writes,
without the banked interface canvas. The canvas holds the title, the HUD and
the opaque pause and game-over panels. It does not hold the playfield.

## Auxiliary memory

| AUX range | Use |
| --- | --- |
| Selector 0 | OS and display; never a public resource bank |
| AUX0 $2000-$9FFF | SHR pixels, SCBs, palettes and padding; all 32768 original bytes are backed up |
| Selectors 1..126 $0000-$01FF | Reserved zero page and stack; never resources |
| Granted selectors $0200-$BFFF | 48640 resource bytes per bank |
| Every selector $C000-$FFFF | I/O, ROM and language card; excluded |

The F1.3.2 baseline serves selectors 0..126. Selector 127 is beyond the first
PSRAM chip, and `ti_init` rejects it. A maximum grant has 6,128,640 resource
bytes before allocations. It is not a flat 8 MB C heap.

The grant must exclude other users of the banks. The diagnostic grants banks
1-2. STARFALL and the starter grant banks 1-3 (145,920 bytes). These banks
hold a 32000-byte canvas, the 32768-byte AUX0 display backup and the
temporary 32768-byte storage loan.

Audio initialization uses the storage loan during the ProDOS interrupt
allocation. With the canvas and the backup, two banks cannot hold the loan,
and audio initialization fails. The bounded AUX loan keeps the /RAM changes
of the OS. See [STORAGE.md](STORAGE.md).

Resources cross from $BFFF to $0200 in the next granted bank. CPU operations
split there, and into IRQ-masked bursts of at most 128 bytes. RAMRD also
changes instruction fetches, so only the $0140 trampoline runs while AUX
reads are active.

ALTZP stays off. MAIN and selector zero return before C code or IRQs
continue. No mapped resource pointer leaves the library. Optional AMEM
touches only private working resources. Video always uses normal CPU writes.
