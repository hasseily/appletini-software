# Linker and banked-memory layout

Both configurations produce a raw ProDOS SYS loaded and entered at $2000,
using cc65 2.19's none.lib and project startup. They use no language-card code
or overlays. Addresses below are inclusive. The build rejects segments outside
these regions; build/layout.json and map files give current linked sizes.
Each build prints the free bytes of every linker memory area per game, and
build/memory.json records them for every program; see [games](GAMES.md).

| MAIN range | Ownership |
| --- | --- |
| $0000-$007F | OS/firmware workspace |
| $0080-$0099 | cc65 ZP; saved on entry and restored before QUIT |
| $009A-$00FF | OS/firmware workspace |
| $0100-$013F | ProDOS lower hardware-stack workspace, untouched |
| $0140-$017F | Bank-transfer trampoline; original bytes saved/restored |
| $0180-$01FF | Hardware stack; 128 bytes including ProDOS IRQ dispatch |
| $0200-$03FF | OS workspace and RESET vectors, untouched |
| $0400-$07FF | Text page 1; error output uses visible cells |
| $0800-$1FFF | Foundation: reserved; full game: static read-only data/code |
| $BF00-$BFFF | ProDOS globals/MLI, untouched |
| $C000-$CFFF | Existing switches/slots; no reassignment |
| $D000-$FFFF | ProDOS language card/ROM, untouched |

| Region | cfg/libtini.cfg: diagnostic, tests, starter | cfg/game.cfg: full game | STARFALL's own layout |
| --- | --- | --- | --- |
| Main code/state | $2000-$9FFF | $2000-$AEFF | $2000-$B3FF |
| Guard | $AF00-$AFFF | $AF00-$AFFF | none |
| C software stack | $A000-$A7FF, top $A800 | $B700-$BEFF, top $BF00 | same as game.cfg |
| Private transfer stage | $A800-$A87F | $B400-$B47F | same as game.cfg |
| Caller near arena, NEARBSS | $A900-$AEFF, 1536 bytes | $B480-$B6FF, 640 bytes | same as game.cfg |
| ProDOS aligned file buffer, `_ti_file_buffer` | $B000-$B3FF, 1 KiB | same | none: no file calls link |
| Additional reserved space | $A880-$A8FF, $B400-$BEFF | none | none |

OSSTATE contains launch flags, saved ZP and trampoline. Public near writes
start after it. Code, constants and saved OS state are read-only to near APIs.
Writable DATA/BSS, free main space, C stack and near arena still require caller
object ownership. The runtime provides no near allocator or collision detector.
Variables an application declares in the `NEARBSS` segment are placed in its
layout's near arena by the linker, which rejects an overflow, and startup
zeroes them before BSS. The runtime itself places nothing there.

The full game statically relocates RODATA, AMEMCODE and LOWCODE into MAIN
$0800-$1FFF once, before clearing BSS or initializing the C stack. Their load
bytes follow DATA in the SYS. That load image may overlap future BSS/stack and
ends before $BF00; it is not retained there. Low MAIN is application-owned
ProDOS SYS memory. It contains constants, optional AMEM helpers and graphics
publication code. It remains read-only through public near APIs.
Bank-switch loops themselves always execute from the safe page-one trampoline.
Normal exit restores required OS state, not application-owned low MAIN bytes.

Startup's entry code, up to clearing BSS, is in the ONCE segment. The full
game places ONCE right after DATA, where BSS begins, so it finishes before
zerobss reuses those bytes; in STARFALL that returns 228 bytes to BSS. The
code that clears BSS, starts C and handles exit stays in STARTUP.

The optional full game has tight headroom. Keep linker checks enabled when
extending it. Measure both stacks when adding foreground depth or IRQ nesting.

STARFALL uses its own copy of `cfg/game.cfg`,
[`examples/starfall/starfall.cfg`](../examples/starfall/starfall.cfg). It
makes no file calls, so the guard page and the file buffer join WORK, which
ends at $B3FF. Its 547-byte game state, star columns,
animated palette and two text buffers are NEARBSS variables at $B480: 639
of the 640 bytes. Its 112-sprite scene list, 896 bytes, and 960-byte
eight-line scene strip occupy static BSS, with 197 bytes of library scene
state. Its 320x200
packed interface canvas lives behind a banked handle. Its 2,048 bytes of
sprite cells, speech phrases, 1,020-byte song and sound table are near
read-only constants in low MAIN, beside most of the song player, the
text glyph loop, the publication row copy and the title's backdrop option;
the example's other tables and strings follow its code. STARFALL has no
optional-AMEM build. 88 bytes of low MAIN and 1,110 bytes below $B400 remain
free. It grants RamWorks selectors 1-3 for the canvas,
AUX0 display backup and temporary ProDOS/IRQ storage loan. Those three
allocations peak at 97,536 bytes, exceeding two resource banks by 256 bytes.
No extra framebuffer or sprite hardware is required.

During play a libtini sprite scene composes changed blocks eight lines at a
time in near memory and publishes them with normal CPU writes, without a
round trip through the banked interface canvas. That canvas remains
available for title, HUD and opaque pause/game-over panels; it does not
retain the current playfield.

| AUX range | Ownership |
| --- | --- |
| Selector 0 | OS/display, never a public resource bank |
| AUX0 $2000-$9FFF | SHR pixels/SCBs/palettes/padding; all 32768 original bytes backed up |
| Selectors 1..126 $0000-$01FF | Reserved ZP/stack, never resources |
| Explicitly granted selectors $0200-$BFFF | 48640 resource bytes per bank |
| Every selector $C000-$FFFF | I/O/ROM/LC, excluded |

The existing F1.3.1 baseline serves selectors 0..126. Selector 127 addresses
beyond the first PSRAM chip and is rejected. A maximum grant has 6,128,640
resource bytes before allocations, not a flat 8 MB C heap. The grant must
exclude other owners. The diagnostic grants banks 1-2. STARFALL and the
starter grant 1-3 (145,920 bytes) for a 32000-byte canvas, the 32768-byte
AUX0 display backup and the temporary 32768-byte storage loan that audio
initialization uses during ProDOS interrupt allocation. Beside the canvas
and backup, two banks cannot hold that loan, and audio initialization
fails. The bounded AUX loan
retains OS /RAM changes. See [storage](STORAGE.md).

Resources cross from $BFFF to $0200 in the next granted bank. CPU operations
split there and into at most 128 bytes per IRQ-masked burst. RAMRD changes
instruction fetches too: only the $0140 trampoline executes while AUX reads
are active. ALTZP stays off; MAIN and selector zero return before C/IRQs
resume. No mapped resource pointer escapes. Optional AMEM touches private
working resources only. Video always publishes through normal CPU writes.
