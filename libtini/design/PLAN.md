# libtini development plan

libtini is a C game SDK for an Apple //e with Appletini. It has a small API,
offline asset tools and simple builds. The builds make ProDOS applications
and disk images. The game owns its loop.

[STARFALL](../examples/starfall/README.md) is the showcase game. It has one
endless vertically scrolling survival level, five enemy behaviors, five
bosses, bounded projectile pools, CC0 sprites, shared music, effects and
speech, CPU graphics and code overlays from a resource pack. Its graphics and audio use the existing interfaces. Its optional rankings panel probes the new HTTP service.
[The starter](../examples/starter/README.md) is a small game to copy. The
developer reference is [docs/index.html](../docs/index.html).

## Agreed boundaries

1. Core graphics and audio use the existing interfaces. Optional HTTP/S probes the F1.3.3 ARM service. Do not use proposed graphics commands, ARM drawing services or FPGA additions.
2. Private SmartPort extensions are optional. The SDK has a CPU-only build without private transport code.
3. Exclude SuperSprite. Keep slot 7 for SmartPort storage. Do not swap slots during game launch or play.
4. Include simple speech in the first release.
5. Support 33 MHz and TURBO. Game speed and audio speed are the same in the two modes.
6. Keep SDK builds self-contained. Build the optional HTTP firmware in its own repository. Offline programs do not require it.

The firmware baseline is Appletini F1.3.2. Packaged examples name this
firmware. Capability checks report the available services and the configured
cards.

## What the first release provides

| Area | Scope |
| --- | --- |
| Runtime | Startup, capability reports, timing, errors, diagnostics and a clean return to ProDOS |
| Graphics | SHR 320x200, palettes, software sprites, a sprite-scene band renderer, animation, tilemaps, scrolling, clipping, fonts, lines and filled shapes |
| Memory | Near buffers and banked resource handles, allocation, bounded reads and writes, copy and fill |
| Music and effects | Six Mockingboard voices, twelve Phasor voices, music playback and effects with priorities |
| Speech | Phrases that the host prepares from text, numbers, a queue, voice controls and cancellation |
| Input | Keyboard events, the held key, Apple buttons, raw and calibrated joystick, and a reserved mouse call that reports "unavailable" |
| Storage | ProDOS files, resource packs, buffered asset loads and saved games |
| Tools | Asset conversion, music and MIDI arrangement, speech compilation, a starter project, disk packaging, previews, diagnostics, benchmarks, a function profiler and a browser player |

HTTP/S and JSON form an optional module that probes the ARM service. More video modes and experimental 3D
are later modules too.

## Public API and project builds

The API has one umbrella header and a header for each feature. It uses
fixed-width integers, explicit result codes and opaque resource handles. The
supported C dialect and calling convention are documented. The compilers are
cc65 and ca65.

The fast paths are 65C02 assembly behind C calls. Routine game work does not
need assembly, softswitch control or slot-register offsets.

A game project contains C sources, assets and a short manifest. One build
command converts the assets, compiles and links the program, checks its
memory layout and packages a ProDOS disk image. All inputs are in the project
or in a documented installed SDK. No build refers to a sibling build tree.

This loop uses the API. The API is the ABI of the first implementation. It
is not frozen.

~~~c
ti_init(1, 3);
ti_gfx_surface_create(&canvas, 320, 200);
ti_gfx_begin(palette);
ti_audio_init(&audio);
ti_speech_bind(&speech);
ti_speech_say(SAY_READY, 1);
ti_steps_begin(ti_audio_ticks, TI_AUDIO_TICKS_PER_SECOND, 30, 30);

while (running) {
    ti_audio_update();
    ti_input_poll();
    steps = ti_steps_due();
    if (steps == TI_STEPS_GAP || !ti_audio_clock_valid()) { pause_game(); continue; }
    while (steps--) update_game(ti_stick_read(0), ti_input_held());
    ti_scene_frame();
    ti_scene_add(ship_x, ship_y, SHIP, 0);
    ti_scene_draw();
}

ti_shutdown();
~~~

Elapsed time comes from the device ticks of the audio driver, not from
display frames. `ti_steps_due` keeps part steps, limits catch-up and reports
a gap of more than one second. It does not invent time. Display edges are
observations with a lower-bound count. A frame count is not a wall clock.

## Graphics

The renderer uses 320x200 SHR, packed 4-bit pixels and one shared palette of
sixteen colors. Per-line palette controls are later work.

The library has software surfaces, masked sprites, clipping, animation,
tilemaps, fonts and basic shapes. Memory and drawing cost set the limits for
surfaces and sprites. The API reports errors and budgets. It does not assume
a fixed hardware sprite count.

The host prepares pixel packing and masks. The runtime works on changed
regions, background restoration and grouped bank accesses.

A software backbuffer helps composition, but it does not give an atomic
hardware page swap. SHR publication samples the video shadow at a frame
boundary. A publication finishes within its budget or reports an overrun.
The return of a publication call means that the CPU writes are complete.

Normal CPU video writes publish the pixels. Display work is separate from
private working-memory transfers. TURBO captures video writes in batches, so
a video byte is not an independent synchronous 1 MHz bus transaction.

The HGR, DHGR, DHGRi and enhanced SHR formats can become later backends with
explicit packing and publication rules. SuperSprite is outside the SDK scope.

## Memory and optional private services

Ordinary near pointers are separate from banked resources. Small game state
and frequent tables are near. Larger images, maps, audio sequences and arrays
are behind handles and explicit offsets.

The library supports allocation, release, bounded reads and writes, copy and
fill across bank boundaries. It reserves memory for the display, the
operating system, the runtime, transfer buffers and caches. Up to 8 MB is the
configured banked capacity. It is not a flat C heap or an amount that is free
for the game.

Bank-switch routines and their state are in safe memory. The interrupt,
mapping and buffer-lifetime rules are specified. Cross-bank transfers do not
expose temporary mapped pointers as permanent addresses.

| Operation | Standard implementation | Optional implementation |
| --- | --- | --- |
| Near copy and fill | Optimized CPU loops | None |
| Banked copy and fill | Safe CPU bank switches and bounded transfers | Existing AMEM service |
| Video drawing and publication | Normal CPU video writes | Same CPU video path |
| Bitmap fonts | Software drawing | No private service |

The optional build selects AMEM automatically for eligible transfers. The
standard memory routines are the reference implementation. Before it uses a
private service, the library probes the controller identity, the API version,
the capabilities and the availability.

The library uses the CPU path when a service is absent, unsupported or
unavailable before submission. After an accelerated transfer starts, the
library reports execution failures. It does not repeat an operation that can
have changed memory. Copy, overlap and range semantics are the same in all
implementations.

AMEM PRIVATE updates authoritative working memory without renderer capture or
physical video replay. The library uses it only for eligible private
resources. It is not a framebuffer blitter.

No mandatory startup, graphics, input, storage or audio function needs a
private selector. Standard SmartPort disk I/O is separate from the private
extensions of Appletini.

Code overlays can be a later advanced feature. An ordinary small game does
not need them.

## Music and sound effects

Mockingboard games use a six-voice arrangement. Phasor games can use twelve
voices. A voice reservation selects the voices for music, and a smaller card
plays the first tracks of a larger arrangement.

The driver has notes, envelopes, music playback, effects with priorities and
explicit voice reservations. Register shadows and grouped writes limit slot
traffic. Repeated writes that restart an envelope or a speech operation stay
in the output.

One driver owns the timer, the interrupt and the sound ports. Music, effects
and speech share this driver. Interrupt callbacks do no disk I/O.

The time source is the real device cadence, not a CPU delay loop. Music and
speech keep their rate at 33 MHz and in TURBO.

## Speech in the first release

Speech uses the existing SSI-263 register interface. It needs no new firmware
and no private SmartPort calls.

Authors write phrases as text in a speech asset file. A host tool converts
the text to compact phoneme sequences and makes C identifiers. The tool has
pronunciation overrides, a preview command and a small documented English
vocabulary.

~~~c
ti_speech_say(SAY_WELCOME, 1);
ti_speech_say(SAY_EXTRA_LIFE, TI_SPEECH_INTERRUPT | 2);
ti_speech_number(score, 1);
ti_speech_busy();
ti_speech_stop();
~~~

Playback does not block. It uses a bounded queue with explicit full, busy,
unavailable and error results. It supports priority, interruption,
cancellation, pitch and rate controls, voice presets and optional music
ducking.

Number expansion joins prepared words for scores, counts and room numbers.
The range is 0 to 9999. One spoken phrase is active at a time. The use of
both speech sockets at the same time is a later extension.

The normal audio update services speech with the device-ready logic. Waits
are bounded, and a stop silences the chip. Runtime text conversion is later
work. Games keep text captions for essential spoken information.

## Input and storage

Character and key events come from the real Apple keyboard interface. The
library does not give a simultaneous-key matrix. Buttons and the joystick
have their own documented state APIs.

Mouse support is a reserved optional call through the existing AppleMouse
interface. It reports "unavailable". Mouse and some gamepad personalities
share slot 2. The library does not change slot assignments.

The library has ProDOS file loads, resource packs, buffered reads and saved
games. Memory ownership, file buffers and auxiliary memory use are defined
together, so they do not collide with ProDOS or its RAM disk. Sound and
frame service rules for long loads are explicit.

Shutdown silences sound, releases the state of the library and restores the
mapping and operating system state for a clean return.

## Tools and repository layout

Public headers, runtime sources, assembly backends, asset tools, examples and
tests are in this repository. Tool and dependency versions are pinned.
Third-party code is copied only after a license review.

Asset tools convert artwork to native packed pixels, palettes, masks, sprite
frames, maps and fonts. They convert music to compact device events and
compile speech text to phonemes. They give size and bank-layout reports and
reject layouts that overlap reserved ranges.

Host tests check game logic, asset conversion and reference pixel results.
Emulator tests check assembled routines and device behavior. Hardware tests
check real timing and output.

## Implementation checkpoints

All five checkpoints are implemented. See [build and run instructions](../README.md),
[the developer reference](../docs/index.html), [building a game](GAMES.md),
[memory layout](MEMORY_MAP.md), [API contracts](CONTRACTS.md) and
[Checks](../docs/reference/testing.html).

1. Foundation: toolchain, public types and errors, startup and exit, timing contract, linker layout, CPU-only memory routines, banked resource tests and one SHR diagnostic screen.
2. Graphics and resources: sprite and tile drawing, surfaces, fonts, asset conversion, resource packs and optional AMEM behind the memory API. The same operations work with private services disabled.
3. Audio and input: music, effects, the speech text compiler, queued speech, numbers, keyboard and joystick, and the reserved mouse call.
4. First playable game: STARFALL, with music, speech, restart and fixed-rate play at 33 MHz and in TURBO.
5. First release: STARFALL, the starter project, packaged disks, diagnostics, source and reference documentation, on firmware F1.3.2.

The CPU-only build includes STARFALL, the starter, the audio demo, the speech
check, the shared music, speech and input driver, the sprite scene renderer,
resource tools and per-game build manifests. The optional AMEM build includes
the same programs, but not STARFALL. A browser player runs the games on the
development machine model.

## Release checks

The release passes these checks:

- The packaged games boot from ProDOS and play through to a clean exit on firmware F1.3.2.
- Simulation, music and speech rates are the same at 33 MHz and in TURBO.
- The programs run with private extensions enabled, unavailable and compiled out. The CPU paths are tested.
- Bank boundaries, reserved ranges, overlapping moves, handle lifetime, allocation failure and smaller memory profiles are tested.
- Music, effects, speech priorities, queue limits, cancellation and absent speech hardware are tested.
- Keyboard, joystick, the reserved mouse call, asset reads, saved games and clean exit are tested.
- Frame time, bytes written, drawing sizes and counts, near-memory use and banked-resource use are recorded for stated scenes.
- Host checks, emulator checks and hardware results are separate evidence.
- No build needs files from a sibling checkout, a temporary folder or a session directory.

## Later modules

The HTTP/S module has start, poll, read, cancel and JSON Pointer calls.
A later hardware-socket module can expose Uthernet directly. Real-time co-op
is outside the current module.

A later 3D module can have fixed-point transforms, projection, clipping,
wireframes, flat-shaded triangles and raycasting, with separate examples and
measurements.

A hosted preview backend can make iteration faster. It keeps the memory,
format and timing limits of the target.

## Existing reference code

These are source references. They are not build dependencies.

- [Appletini copy and fill API](https://github.com/hasseily/appletini-one/blob/F1.3.2/README_MEMORY_API.md)
- [TURBO behavior](https://github.com/hasseily/appletini-one/blob/F1.3.2/README_TURBO.md)
- [Bosconian C and assembly game](https://github.com/hasseily/appletini-software/tree/main/demos/appletini_bosconian)
- [Native Phasor stream player](https://github.com/hasseily/appletini-software/tree/main/music/song_to_phasor/player)
- [Uthernet C examples](https://github.com/hasseily/appletini-software/tree/main/demos/appletini_demos/appletini_webserver)
- [Joeylib2](https://forge.duensing.digital/AI_Slop/joeylib2)
