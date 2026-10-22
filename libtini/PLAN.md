# libtini development plan

Date: 2026-10-20

libtini will be a C game SDK for an Apple //e with Appletini. It will offer a small API, offline asset tools and simple builds that produce ProDOS applications and disk images. The game owns its loop.

[STARFALL](examples/starfall/README.md) is the showcase game: one endless
vertically scrolling survival level, five enemy behaviors, bounded
projectile pools, CC0 sprites, shared music/effects/speech and CPU graphics.
It uses the same existing-firmware boundary and has separate validation gates.
[The starter](examples/starter/README.md) is a small game to copy.

## Agreed boundaries

1. Use only hardware interfaces and services already present in existing firmware. Do not implement or depend on proposed graphics commands, ARM drawing services or FPGA additions.
2. Private SmartPort extensions are optional. The SDK must support a CPU-only build that omits private transport code.
3. Exclude SuperSprite. Keep slot 7 available for SmartPort storage, with no manual slot swapping during game launch or play.
4. Include simple speech in the first release.
5. Target 33 MHz and TURBO. Measure each mode on the board; preserve game and audio speed across modes.
6. Keep the SDK self-contained. Appletini firmware and other repositories remain unchanged.

At the first implementation checkpoint, choose and record an existing firmware release for board tests. Packaged examples must name the exact firmware they were tested with. Capability checks must reflect available services and configured cards.

## What the first release provides

| Area | Scope |
| --- | --- |
| Runtime | Startup, capability reporting, timing, errors, diagnostics and clean return to ProDOS |
| Graphics | SHR 320x200, palettes, software sprites, animation, tilemaps, scrolling, clipping, fonts, lines and filled shapes |
| Memory | Near buffers and banked resource handles, allocation, bounded reads and writes, copy and fill |
| Music and effects | Six Mockingboard voices, twelve Phasor voices, music playback and effects with priorities |
| Speech | Phrases prepared from text at build time, numbers, a queue, voice controls and cancellation |
| Input | Keyboard events, Apple buttons and joystick; an optional mouse driver |
| Storage | ProDOS files, resource packs, buffered asset loading and saved games |
| Tools | Asset conversion, a starter project, disk packaging, previews, diagnostics and benchmarks |

Networking follows as an optional module after the core is stable. Further existing video modes and experimental 3D follow measurements of the first renderer.

## Public API and project builds

Use a small umbrella header and feature headers, fixed-width integers, explicit result codes and opaque resource handles. Document the supported C dialect and calling conventions. Begin with cc65 and ca65, which already serve local C and assembly games.

Keep the fast paths in 65C02 assembly behind C calls. Avoid requiring users to write assembly, manage softswitches or know slot-register offsets for routine game work.

A game project contains C sources, assets and a short build file. One build command converts assets, compiles and links the program, checks its memory layout and packages a ProDOS disk image. Required inputs must live inside the project or a documented installed SDK, without references to sibling build trees.

The API names below describe the intended style; they are not a fixed ABI.

~~~c
ti_init(&config);
ti_speech_say(SAY_READY);

while (running) {
    ti_frame_begin();
    ti_input_poll();
    update_game(ti_elapsed_ticks());
    ti_map_draw(level, camera_x, camera_y);
    ti_sprite_draw(ship, ship_x, ship_y, animation_frame);
    ti_audio_update();
    ti_frame_end();
}

ti_shutdown();
~~~

Define elapsed-tick and frame-service rules before implementing this loop. Account for missed display edges and long operations. A frame count alone cannot serve as a reliable wall clock.

## Graphics

Start with 320x200 SHR, packed 4-bit pixels and a shared sixteen-colour palette. Add per-line palette controls after the basic renderer works well.

Provide software surfaces, masked sprites, clipping, animation, tilemaps, fonts and basic shapes. Surface and sprite limits depend on memory and drawing cost. Expose errors and useful budgets rather than assuming a fixed hardware sprite count.

Prepare pixel packing, masks, shifted sprite forms and optional generated drawing routines on the host. Optimize the runtime around changed regions, background restoration, cached tiles and grouped bank accesses.

A software backbuffer helps composition but does not add an atomic hardware page swap. Current SHR publication samples the video shadow at a frame boundary. The library must finish a drawing burst within the chosen deadline or report an overrun. Define exactly what frame end means for this backend.

Use normal CPU video writes to publish pixels. Keep display work separate from private working-memory transfers. Evaluate TURBO's current capture and synchronization behaviour; do not treat every video byte as an independent synchronous 1 MHz bus transaction or reuse an old bandwidth figure as a universal limit.

Existing HGR, DHGR, DHGRi and enhanced SHR formats can become later backends with explicit packing and publication rules. SuperSprite remains outside the SDK scope.

## Memory and optional private services

Separate ordinary near pointers from banked resources. Keep small game state and hot tables near. Store larger images, maps, audio sequences and arrays behind handles and explicit offsets.

Support allocation, release, bounded reads and writes, copy and fill across bank boundaries. Reserve memory for the display, operating system, runtime, transfer buffers and active caches. Up to 8 MB describes configured banked capacity, not a flat C heap or a guaranteed amount free to the game.

Keep bank-switch routines and their required state in safe memory. Specify interrupt, mapping and buffer-lifetime rules. Make cross-bank transfers efficient without exposing temporary mapped pointers as permanent addresses.

| Operation | Standard implementation | Optional implementation |
| --- | --- | --- |
| Near copy and fill | Optimized CPU loops | Existing service for eligible ranges when it saves time |
| Banked copy and fill | Safe CPU bank switching and bounded transfers | Existing AMEM service |
| Video drawing and publication | Normal CPU video writes | Same supported video path |
| Bitmap fonts | Software drawing | No private service required |

Provide automatic selection and CPU-only mode. Standard memory routines form the reference implementation. Probe controller identity, API version, capabilities and availability before using private services.

Select CPU fallback when a service is absent, unsupported or unavailable before submission. Once an accelerated transfer starts, report execution failures; do not silently repeat an operation that may have partly changed memory. Preserve copy, overlap and range semantics across implementations.

AMEM PRIVATE updates authoritative working memory without renderer capture or physical video replay. Restrict it to eligible private resources. It is not a framebuffer blitter.

No mandatory startup, graphics, input, storage or audio function may require a private selector. Standard SmartPort disk I/O remains separate from Appletini's private extensions.

Code overlays can become a later advanced feature. The first release should not require them for an ordinary small game.

## Music and sound effects

Support a common six-voice arrangement for Mockingboard and optional twelve-voice Phasor arrangements. Define how assets select a smaller arrangement or reserve voices when fewer channels are available.

Provide notes, envelopes, music playback, effects with priorities and explicit voice reservations. Use register shadows and grouped writes to limit slot traffic. Preserve repeated writes that retrigger an envelope or speech operation.

Centralize timer, interrupt and sound-port ownership. Music, effects and speech must share one driver. Keep disk I/O out of interrupt callbacks and refill streaming buffers in the foreground.

Use a time source tied to the real device cadence rather than CPU delay loops. Music and speech must retain their rate at 33 MHz and TURBO.

## Speech in the first release

Use the existing SSI-263 register interface. Speech requires neither new firmware nor private SmartPort calls.

Authors write phrases as text in a speech asset file. A new host tool converts text to compact phoneme sequences and generates C identifiers. Provide pronunciation overrides, a preview command and a small documented initial English vocabulary or rule set. Text conversion is new SDK tooling; existing game drivers already consume authored phonemes.

~~~c
ti_speech_say(SAY_WELCOME);
ti_speech_say(SAY_EXTRA_LIFE);
ti_speech_number(score);
ti_speech_busy();
ti_speech_stop();
~~~

Playback is nonblocking and uses a bounded queue with explicit full, busy, unavailable and error results. Support priority, interruption, cancellation, pitch and rate controls, voice presets and optional music ducking.

Number expansion joins prepared words for changing scores, counts and room numbers. Define the supported range and pronunciation rules. Start with one active spoken phrase; using both speech sockets at once is a later extension.

Service speech through the normal audio update and device-ready logic, with bounded waits and safe silence on stop. Test its interaction with AY writes in both audio personalities.

Arbitrary runtime text conversion can follow later. The first release uses text compiled on the host, phrase identifiers and number expansion. Games should retain text for essential spoken clues.

## Input and storage

Provide character and key events through the real Apple keyboard interface. Do not promise an arbitrary simultaneous-key matrix. Give buttons, joystick and supported gamepads their own documented state APIs.

Make mouse support optional through the existing AppleMouse interface. Report configured devices honestly; mouse and some gamepad personalities share slot 2. Do not change slot assignments during startup.

Provide ProDOS file loading, resource packs, buffered reads and saved games. Define memory ownership, file buffers and auxiliary-memory use together so they do not collide with ProDOS or its RAM disk. Keep sound and frame service requirements explicit during long loads.

Shutdown must silence sound, release library-owned state and restore the mapping and operating-system state required for a clean return.

## Tools and repository layout

Keep public headers, runtime sources, assembly backends, asset tools, examples and tests in this repository as they are added. Pin tool and dependency versions when selecting them. Review licenses before copying third-party code.

Asset tools should convert artwork to native packed pixels, palettes, masks, sprite frames, maps and fonts; convert music to compact device events; and compile speech text to phonemes. Produce size and bank-layout reports and reject layouts that overlap reserved ranges.

Use host tests for pure game logic, asset conversion and reference pixel results. Use emulator tests for assembled routines and supported device behaviour. Board tests establish real timing and output.

## Implementation checkpoints

All five checkpoints now have implementations. See [build/run instructions](README.md),
[building a game](docs/GAMES.md), [memory layout](docs/MEMORY_MAP.md),
[API contracts](docs/CONTRACTS.md) and [validation](docs/VALIDATION.md).
The CPU-only and optional-AMEM builds include STARFALL, the starter, the
shared music/speech/input driver, resource tools and per-game build
manifests. Available host and emulator evidence is recorded
separately from the remaining physical 33 MHz/TURBO acceptance gates.
The selected board baseline is existing F1.3.1,
`8af06741f3b9454b6bc226b7d55f69cc09097ccf`; no firmware rebuild/flash occurred.
Checkpoint-five software is present, but release acceptance is not complete
until the board gates pass. Optional mouse currently reports unavailable.

1. Foundation: toolchain, public types and errors, startup and exit, timing contract, linker layout, CPU-only memory routines, banked resource tests and one SHR diagnostic screen.
2. Graphics and resources: sprite and tile drawing, surfaces, fonts, asset conversion, resource packs and optional AMEM behind the existing memory API. Verify the same operations with private services disabled.
3. Audio and input: music, effects, speech text compiler, queued speech, numbers, keyboard and joystick, plus optional mouse. Finish the speech-and-music demo before game dialogue expands.
4. First playable game: STARFALL, with music, speech, restart and fixed-rate play. Measure it at 33 MHz and TURBO with private services disabled.
5. First release: STARFALL, the starter project, packaged disks, diagnostics, source and reference docs. Complete board checks and record the tested firmware.

Next acceptance checkpoint: run STARFALL, the starter, diagnostics, file
save/load, clock calibration, music and intelligibility checks on the
selected physical board at 33 MHz and TURBO, with private services compiled
out and enabled.
Measure publication/IRQ latency before making speed or play-length claims.
Networking/additional video/3D remain later optional implementation modules.

## Release checks

- Boot the packaged games from ProDOS and play them through to a clean exit on existing firmware.
- Verify 33 MHz and TURBO with consistent simulation, music and speech rates.
- Run with private extensions enabled, unavailable and compiled out; exercise the actual CPU paths.
- Test bank boundaries, reserved ranges, overlapping moves where supported, handle lifetime, allocation failure and smaller memory profiles.
- Verify music, effects, speech priorities, queue limits, cancellation and absent speech hardware.
- Verify keyboard, joystick, optional mouse, asset reads, saved games and clean exit.
- Record frame time, bytes written, drawing sizes and counts, near-memory use and banked-resource use for stated scenes.
- Treat host checks, emulation and board results as separate evidence.
- Ensure no build needs files from a sibling checkout, temporary folder or session directory.

## Later modules

Add bounded polling for Uthernet networking after the core is stable. Reuse existing interface patterns and keep networking optional.

Explore fixed-point transforms, projection, clipping, wireframes, flat-shaded triangles and raycasting as a later 3D module. Use separate examples and measurements.

A hosted preview backend can improve iteration later, while retaining the target's memory, format and timing limits in validation.

## Existing reference code

These are source references, not build dependencies or proof that a particular packaged game has passed board tests.

- [Appletini copy and fill API](https://github.com/hasseily/appletini-one/blob/8af06741f3b9454b6bc226b7d55f69cc09097ccf/README_MEMORY_API.md)
- [Current TURBO behaviour](https://github.com/hasseily/appletini-one/blob/8af06741f3b9454b6bc226b7d55f69cc09097ccf/README_TURBO.md)
- [Bosconian C and assembly game](https://github.com/hasseily/appletini-software/tree/main/demos/appletini_bosconian)
- [Native Phasor stream player](https://github.com/hasseily/appletini-software/tree/main/music/song_to_phasor/player)
- [Uthernet C examples](https://github.com/hasseily/appletini-software/tree/main/demos/appletini_demos/appletini_webserver)
- [Joeylib2](https://forge.duensing.digital/AI_Slop/joeylib2)
