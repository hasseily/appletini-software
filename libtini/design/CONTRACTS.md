# Public API and machine contract

Include `libtini.h` or the small feature headers in `include/libtini/`. Use
the C99 subset of cc65 and the default cc65 ABI. Non-variadic calls use
fastcall: the last argument is in A/X/sreg and the other arguments are on the
C stack. The target is the 65C02.

Public widths come from `stdint.h`. Errors are `uint8_t` and handles are
`uint16_t`. This is the ABI of the first implementation. It is not a promise
of a stable future ABI.

| Result | Meaning |
| --- | --- |
| TI_OK | The call completed synchronously |
| TI_E_ARGUMENT / STATE / RANGE | Invalid argument, wrong lifecycle state or a value outside its bound |
| TI_E_NOMEM / HANDLE | No capacity or no free slot, or a stale or invalid handle |
| TI_E_UNAVAILABLE | The device or service is absent or unsupported before use |
| TI_E_TIMING | A service gap, a timeout or a publication over its budget |
| TI_E_BUSY / FULL | An ownership or priority conflict, a reentrant call or a disturbed measurement; or a full bounded queue or list |
| TI_E_IO / FORMAT | An OS or transport failure, or invalid authored data |

`ti_error_keep(e)` returns `e` and keeps the first nonzero result that it
gets. `ti_error_first` returns that result until `ti_error_clear`. A program
can wrap calls in `ti_error_keep` and test `ti_error_first` once a frame.
The library does not keep results that the program does not give to
`ti_error_keep`.

# Launch and lifecycle

Launch the program as a ProDOS SYS file at $2000 on an enhanced //e with a
65C02. At entry, these conditions must be true:

- RAMRD and RAMWRT select MAIN, and ALTZP is off.
- The RamWorks selector is zero.
- Fake SHR is off ($C029 = $01).
- 80STORE, HIRES and PAGE2 do not send the $2000 instruction stream to AUX.

A normal ProDOS text launch meets these conditions. $C073 and the fake-SHR
switch $C029 have no reliable readback. Thus their entry values are explicit
requirements.

Startup saves the cc65 zero page, the page-one trampoline area, the entry P
register, 80STORE and six readable display flags. It masks IRQs, disables
80STORE, copies the static low segments, clears NEARBSS and BSS, sets the two
stacks and installs the CPU transfer trampoline. The steps before the BSS
clear run from the ONCE segment. `cfg/game.cfg` puts ONCE where BSS starts.

C runs in binary mode with the IRQ policy of the launch. Startup does not
change the RESET vectors, the ProDOS device lists or the language card.

`ti_init(first_bank, bank_count)` is an exclusive grant. It does not discover
ownership. Grant a contiguous set of selectors in 1..126 that no other
program or driver uses. A save, test and restore probe at AUX $A000 finds
missing and aliased banks, including aliases to AUX0. The probe does not
identify the firmware and does not test every byte.

An invalid grant returns TI_E_ARGUMENT. A failed probe returns
TI_E_UNAVAILABLE and keeps none of its writes. A second `ti_init` while the
library is active returns TI_E_STATE.

`ti_shutdown` is idempotent. It stops audio, ends graphics, restores the AUX0
snapshot, clears the accelerator hooks and invalidates all resources. A
return from `main` or a call to `exit` runs this cleanup. Startup then
restores the saved machine and OS state and calls ProDOS QUIT.

File calls are synchronous, and they close their file before they return. A
normal return is the supported exit path. Reset and power loss cannot run the
cleanup. [MEMORY_MAP.md](MEMORY_MAP.md) gives the two static layouts.

If ProDOS cannot remove the audio interrupt handler, audio shutdown returns
TI_E_IO. The hardware is silent, and the driver keeps ownership so that a
retry is possible. `ti_shutdown` returns the same failure. It does not
invalidate the remaining resources or release the handler code.

The whole-program cleanup can have ended video already, so that ProDOS has
its AUX bytes again. Startup keeps the SYS file in memory, shows a cleanup
error and retries on a key. It cannot call QUIT while an OS callback points
into memory that ProDOS can reuse. This is an explicit OS error path.

The allocation and removal of the audio interrupt also lend AUX0 back to
ProDOS. Thus the workspace changes of ProDOS go into the saved OS image.

# Near pointers and resource handles

Near buffers are real MAIN objects. Linker symbols give the readable and
writable ranges. Code, constants, OSSTATE, transfer buffers, guards, I/O and
ProDOS globals are not public write destinations. In the full-game layout,
low MAIN is read-only.

A buffer with a nonzero length must fit in one permitted region. A zero
length accepts NULL and accesses no memory. The guards do not replace object
ownership: keep objects away from private globals and active stacks. A near
move has memmove semantics. A near fill writes one byte value.

Resources use first fit in the logical stream of 48640-byte bank windows.
There are eight slots. An allocation can fail because of capacity,
fragmentation, a full slot table or retired slots.

`ti_res_alloc` needs a writable near output handle. It sets the handle to
invalid on failure, rejects a zero size and gives uninitialized bytes on
success. A handle encodes a slot and a generation, never a C address.

A copy of a handle does not keep the resource. Free and shutdown invalidate
every copy. A slot retires at generation 4095, so it never wraps to the value
of an old live handle. Generations stay the same through a new `ti_init` in
the same program run.

Read and write use 32-bit resource offsets, borrowed near buffers and 16-bit
lengths. Fill and copy use 32-bit lengths. Each call checks all handles,
ranges and buffers before it starts. The bounds checks use subtraction, so
integer wrap cannot pass them.

The end offset is valid only with a zero length. A zero-length call still
needs a live handle. Resource copy has memmove semantics in the two overlap
directions. Two live allocations never overlap.

There are no asynchronous transfers, permanent mapped pointers or kept
transfer buffers.

The default build has no private transport. The optional build probes for
the exact known controller before it sends STATUS or CONTROL. When the
service is unavailable before submission, it uses the CPU.

A submitted transfer that fails can have changed the data. The library then
returns TI_E_IO and stops the private backend. It never repeats the transfer
through the CPU. Same-handle overlap always uses the CPU, and so do video and
OS snapshots. See [AMEM.md](AMEM.md).

# Mapping, interrupts and publication

Public calls run in the foreground with MAIN reads and writes, ALTZP and
80STORE off and selector zero. Calls are not reentrant.

Each CPU bank burst saves P, masks IRQs, copies its parameters into MAIN zero
page, selects the bank and runs page-one code. It restores MAIN and selector
zero before it restores P.

A bank 0 burst uses the selector value zero that is already set. It writes no
$C073, because a $C073 access also starts the paddle timers. Callers with
IRQs disabled keep them disabled. Callers with IRQs enabled get IRQs back
between bursts. The limit is a byte count and an instruction cost.

An external IRQ handler must not call libtini, change mappings or the
selector, touch libtini zero page or access granted AUX banks. An NMI cannot
be masked. An NMI handler must run safely with AUX reads selected, keep
scratch state and obey the same ownership rules.

A C handler in switched memory is not safe. The audio interrupt receiver of
the library uses no C code, no zero page and no mapping changes. Keep the
total hardware stack use, OS dispatch included, inside 128 bytes.

`ti_gfx_begin` allocates an OS snapshot and saves all of AUX0 $2000-$9FFF.
Software surfaces stay in banked resources. `ti_gfx_present` copies the
changed packed pixels with normal CPU writes.

The return of a publication means that the CPU writes are complete. It does
not mean an atomic page swap or an HDMI presentation. Byte budgets reject an
update before any write. A measured deadline overrun returns TI_E_TIMING
after the writes. See [GRAPHICS.md](GRAPHICS.md).

`ti_gfx_present_rows` publishes a packed near rectangle that the caller owns.
It uses the same CPU backend during an active graphics session. Its x and
width must be even, and the rectangle must fit on the screen.

It checks the complete source span and the budget before it writes. It
borrows the buffer only until it returns, and it changes no banked surface.
Its return has the same meaning as the return of `ti_gfx_present`.

`ti_scene_draw` publishes the changed blocks of one sprite-scene rectangle
with the same CPU writes, during an active graphics session. The game owns
the sprite list and the strip storage. The scene borrows its near image table
and pixels until the next `ti_scene_begin`.

Scene draws are foreground-only and use no budget or banked resource. The
scene assumes that no other code drew in its rectangle. When other code
draws there, the game calls `ti_scene_forget` or `ti_scene_invalidate`.

A file call restores the AUX bytes of the OS for the duration of the call.
It does ordinary ProDOS MLI I/O, keeps the changes that ProDOS made and then
restores the picture. It needs one more slot and 32768 resource bytes, and
it fails before the MLI call when they are not available.

External handlers that use AUX memory while the screen shows SHR are not
permitted. See [STORAGE.md](STORAGE.md).

# Device ticks and observed display edges

CPU delay loops cannot time both 33 MHz and TURBO. Bit 7 of $C019 is a
sampled display-active level. `ti_time_poll` counts only the blank-to-active
edges that it sees.

The count is a lower bound, because a full display period between two polls
is not visible. It is not an HDMI presentation counter. It does not tell when
a screen is complete.

`ti_time_begin(NULL, 0)` selects observation without elapsed time. Then
`ti_time_poll` fills a sample, returns TI_E_UNAVAILABLE, sets elapsed time to
zero and clears the VALID flag.

As an alternative, give a monotonic `uint32_t` callback that a real device
drives, and its rate. Give the two arguments together or neither of them. The
callback returns an atomic foreground snapshot, with no mapping changes and
no calls into libtini.

Elapsed time is the unsigned difference from the first `source()` value.
Begin again before 2^32 ticks pass. The library supports one wrap.

The shared audio driver gives VIA ticks at a nominal 100 Hz, independent of
CPU speed. `via_hz` sets the known or calibrated device clock. Zero selects
1 MHz. The real tick period is the integer divisor divided by `source_hz`.
Use the source and divisor queries to calculate exact time.

On the development emulator, the default configuration gives 102 ticks in
1.00129 model seconds. A `via_hz` of 1020484 gives 100 ticks a second in the
two CPU profiles. See [AUDIO.md](AUDIO.md).

A VIA pending bit cannot count more than one masked timer period. A long IRQ
suspension makes elapsed time invalid. The audio gap and resume hooks silence
the hardware, cancel bounded work and rebase the clock around storage and
AMEM operations. Other blocking work must use the same hooks.

The display GAP flag stays set from `ti_time_begin`. Memory and video
operations set it as a precaution. Polls cannot recover missed edges.

`ti_steps_due` adds up a nominal fixed update rate from device ticks. It
limits catch-up and reports gaps of more than one second. It does not invent
time, and STARFALL pauses on a gap. Display gaps are not clock gaps.
`ti_steps_due` keeps only the low 16 bits of the tick source, so reset it
after longer pauses.

# Feature lifetimes

Surface, sprite, map and font views borrow live handles and offsets. When the
program frees the allocation under a view, every view of it becomes invalid.

Music arrays, songs and speech banks borrow near read-only objects until a
stop, a new bind or shutdown. File calls borrow near buffers only until they
return.

Input gives character events. It does not give release events or a
simultaneous-key matrix. `ti_input_held` gives only the newest key while any
key is down.

Joystick timing uses the device timers that audio owns: VIA-B T2, or T1C-H
windows where T2 does not count. Any $C070-$C07F access, $C073 selector
writes included, starts the paddle timers. Thus a read first waits up to
4 ms for the paddle timers to stop.

Bank 0 transfers do not write $C073. An axis that does not finish reads 255,
and the call returns TI_E_TIMING. A read that interrupts disturb returns
TI_E_BUSY and changes nothing.

`ti_stick_read` keeps the calibration of one stick in static state. It is not
reentrant. The reserved mouse call returns TI_E_UNAVAILABLE and never changes
slot personalities.

Audio owns the slot-4 card exclusively. It uses the standard ProDOS interrupt
allocation and removal. Call `ti_audio_shutdown` before another driver uses
that card.
