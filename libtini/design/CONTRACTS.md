# Public API and machine contract

Include libtini.h or the small feature headers in include/libtini/. Use cc65's
C99 subset and default cc65 ABI: nonvariadic calls use fastcall, with the final
argument in A/X/sreg and earlier arguments on the C stack. Target is 65C02.
Public widths come from stdint.h. Errors are uint8_t; handles are uint16_t.
This is the initial implementation ABI, not a stable future ABI promise.

| Result | Meaning |
| --- | --- |
| TI_OK | Completed synchronously |
| TI_E_ARGUMENT / STATE / RANGE | Invalid argument, lifecycle or bounded range |
| TI_E_NOMEM / HANDLE | Capacity/slots exhausted, or stale/invalid handle |
| TI_E_UNAVAILABLE | Device/service absent or unsupported before use |
| TI_E_TIMING | Explicit service gap, timeout or publication budget exceeded |
| TI_E_BUSY / FULL | Ownership/priority conflict, reentrant call or disturbed measurement; or a bounded queue or list full |
| TI_E_IO / FORMAT | OS/transport failure, or invalid authored data |

`ti_error_keep(e)` returns `e` and keeps the first nonzero result passed to
it; `ti_error_first` returns that result until `ti_error_clear`. A program
can wrap calls whose failure it handles later, such as once a frame, instead
of testing each one. Results not passed to it are not kept.

# Launch and lifecycle

Launch as a ProDOS SYS at $2000 on enhanced //e/65C02. Entry requires MAIN
RAMRD/RAMWRT, ALTZP off, RamWorks selector zero and fake SHR disabled
($C029=$01). 80STORE/HIRES/PAGE2 must not redirect the $2000 instruction stream
to AUX. A normal ProDOS text launch satisfies this. C073 and fake-SHR C029
have no reliable readback, so their entry values are explicit requirements.

Startup saves cc65 ZP, the page-one trampoline, entry P, 80STORE and six
readable display flags. It masks IRQs, disables 80STORE, relocates the optional
static low segments, clears NEARBSS and BSS, initializes both stacks and
installs the CPU transfer trampoline. The steps before clearing BSS run from
the ONCE segment, which `cfg/game.cfg` places under BSS. C runs in binary mode with the launch IRQ policy.
RESET vectors, ProDOS device lists and language-card contents are untouched.

ti_init(first_bank, bank_count) is an exclusive grant, not ownership discovery.
Grant a nonempty contiguous set within selectors 1..126 known to be free of
other applications/drivers. A save/test/restore probe at AUX $A000 detects
missing/aliased banks, including aliases to AUX0. It does not identify firmware
or certify every byte. Invalid grants return ARGUMENT; a failed probe returns
UNAVAILABLE without retaining writes. A second active init returns STATE.

ti_shutdown is idempotent. It shuts down owned audio, ends graphics, restores
the AUX0 snapshot, clears accelerator hooks and invalidates resources.
Return from main or exit invokes cleanup, restores saved machine/OS state and
calls ProDOS QUIT. Files are synchronous and closed before storage returns.
Normal return is the supported exit path. Reset/power loss cannot run cleanup.
See [memory map](MEMORY_MAP.md) for the two supported static layouts.

If standard ProDOS interrupt removal fails, audio shutdown returns IO with
hardware silenced and ownership retained for retry. ti_shutdown propagates
that failure without invalidating remaining resources or releasing callback
code. Whole-program cleanup can already have ended video to give AUX back to
the OS. Startup keeps the SYS loaded,
shows a cleanup error and retries on a key; it cannot QUIT with an OS callback
pointing into unloaded code. This is an explicit OS-error path, not successful
cleanup. Audio interrupt allocation/removal also lends AUX0 back to ProDOS
so its workspace changes join the saved OS image.

# Near pointers and resource handles

Near buffers are actual MAIN objects. Readable/writable ranges come from
linker symbols; code, constants, OSSTATE, transfer buffers, guards, I/O and
ProDOS globals cannot be public write destinations. Full-game low MAIN is
readable only. A nonzero buffer must fit a single permitted region. A zero
length accepts NULL and performs no memory access. Guards do not replace
object ownership: callers must keep objects away from private globals and
active stacks. Near move has memmove semantics; near fill writes a byte.

Resources use first fit over 48640-byte windows. There are eight slots.
Capacity, fragmentation, slot exhaustion and retired slots can fail an
allocation. ti_res_alloc requires a writable near output handle, sets it
invalid on failure, rejects zero size and returns uninitialized bytes on
success. Handles encode slot and generation, never a C address. Copying a
handle does not retain it. Free/shutdown invalidates every copy. A slot retires
at generation 4095 instead of wrapping into an old live handle; generations
survive reinit in one invocation.

Read/write use 32-bit resource offsets, borrowed near buffers and 16-bit
lengths. Fill/copy use 32-bit lengths. All handles/ranges/buffers are checked
before starting. Bounds use subtraction to reject integer wrap. End offset
is valid only at zero length; zero-length calls still need live handles.
Resource copy has memmove semantics in both overlap directions. Distinct live
allocations cannot overlap. There are no asynchronous transfers, permanently
mapped pointers or retained transfer buffers.

The default build compiles out private transport. The optional build probes
an exact known controller before STATUS/CONTROL and selects CPU before
submission when unavailable. Submitted errors may have changed data: return
IO and poison the backend, never silently replay through CPU. Same-handle
overlap stays CPU. Video/OS snapshots always stay CPU. See [AMEM](AMEM.md).

# Mapping, interrupts and publication

Public calls run in foreground with MAIN reads/writes, ALTZP/80STORE off and
selector zero. Calls are non-reentrant. Each CPU bank burst saves P, masks
IRQs, copies parameters into MAIN ZP, selects the bank and executes page-one
code. It restores MAIN/selector zero before P. A bank 0 burst relies on the
selector already being zero and writes no $C073, which would also strobe
the paddle timers. IRQ-disabled callers remain
disabled; enabled callers regain IRQs between bursts. The bound is bytes and
instruction cost, not a measured board-time guarantee.

An external IRQ must not call libtini, alter mappings/selector, touch its ZP
or access granted AUX. An NMI cannot be masked: it must execute safely under
AUX reads, preserve scratch state and obey the same ownership. A C handler in
switched memory is unsafe. The library's audio receiver uses no C/ZP/mapping
changes. Keep total hardware-stack use inside 128 bytes, including OS dispatch.

Graphics begin allocates an OS snapshot and saves all AUX0 $2000-$9FFF.
Software surfaces remain banked resources. Present copies dirty packed pixels
through normal CPU writes. Completion means writes finished, not an atomic
page swap or HDMI presentation. Byte budgets reject before writes; a measured
deadline overrun returns TIMING after writes. See [graphics](GRAPHICS.md).
`ti_gfx_present_rows` publishes a caller-owned packed near rectangle through
the same CPU backend during an active graphics session. Its x/width must be
even and the rectangle must fit onscreen. It validates the complete source
span and budget before writing, borrows the buffer only until return and
does not update any banked surface. Its completion has the same meaning as
ordinary present.
`ti_scene_draw` publishes the changed blocks of one sprite-scene rectangle
through the same CPU writes during an active graphics session. The game owns
the sprite list and strip storage; the scene borrows its near image table
and pixels until the next begin. Draws are foreground-only, use no budget or
banked resource, and assume nothing else drew in the rectangle unless the
game calls forget or invalidate.
Storage temporarily restores the OS's AUX bytes, performs ordinary ProDOS
MLI I/O, captures resulting OS changes, then restores the picture. It needs
another 32768 resource bytes/slot and fails before MLI if unavailable.
External AUX-using handlers during display remain excluded. See [storage](STORAGE.md).

# Device ticks and observed display edges

CPU delay loops cannot time both 33 MHz and TURBO. C019 bit7 is a sampled
display-active level. ti_time_poll counts observed blank-to-active edges only.
Its count is a lower bound: full display periods between polls are invisible.
It is not an HDMI presentation counter and implies no screen completion.

ti_time_begin(NULL,0) chooses observations without elapsed time: poll fills
a sample but returns UNAVAILABLE, leaves elapsed zero and clears VALID.
Alternatively supply a real device-driven monotonic uint32 callback and its
rate. Both arguments must be present/absent together. The callback returns an
atomic foreground snapshot without mappings/libtini recursion. Elapsed is
unsigned source()-origin; rebase before 2^32 ticks. A single wrap is supported.

The shared audio driver supplies nominal 100 Hz VIA ticks, independent of CPU
speed. via_hz explicitly configures the known/calibrated device source;
zero assumes 1 MHz. Actual period is integer divisor/source_hz. Read the
source/divisor queries instead of asserting exact milliseconds without
calibration. Native default measured 102 ticks per 1.00129 model seconds;
explicit 1020484 Hz model calibration gives 100 in both CPU profiles. This
is model evidence, not board calibration. See [audio](AUDIO.md).

A VIA pending bit cannot count multiple masked timer periods. Arbitrary long
IRQ suspension invalidates elapsed time. The audio gap/resume hooks silence,
cancel/rebase bounded work around known storage/AMEM operations. Unknown
blocking work must bracket the same hooks. Display GAP is sticky since begin;
memory/video operations conservatively mark it, and polling cannot recover
missed edges. `ti_steps_due` accumulates a nominal fixed update rate from
device ticks, caps catch-up and reports gaps over a second instead of
inventing time; STARFALL pauses on one. Display gaps are not clock gaps.
Only the tick source's low 16 bits are kept: reset after longer pauses.

# Feature lifetimes

Surface/sprite/map/font views borrow live handles and offsets; releasing their
underlying allocation invalidates every view. Music arrays, songs and speech
banks borrow near read-only objects until stop/rebind/shutdown. File near buffers
are borrowed only until synchronous return. Input returns character events,
not release events or an arbitrary simultaneous-key matrix. `ti_input_held`
reports only the newest key while any key is down. Joystick timing uses the
owned device timers: VIA-B T2, or T1C-H windows where T2 does not count. Any
$C070-$C07F access, including $C073 selector writes, strobes the paddles, so
a read first waits up to 4 ms for running paddle timers. Bank 0 transfers do
not write $C073. An unfinished axis reads 255 with TI_E_TIMING;
interrupt-disturbed reads return TI_E_BUSY unchanged. `ti_stick_read` keeps
one stick's calibration in static state; it is not reentrant. Optional mouse reports UNAVAILABLE; it never
changes slot personalities. Audio owns the slot-4 card exclusively and uses
standard ProDOS interrupt allocation/removal. Its shutdown is required before
giving that card to another owner.
