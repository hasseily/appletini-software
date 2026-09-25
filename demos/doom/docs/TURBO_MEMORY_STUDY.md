# Doom: TURBO mirroring and fast memory

2026-09-25. Source reviewed: Appletini firmware **F1.1.1**, commit
`1fd4f371e8f4ef08bc63875550564590609fcfeb`. The installed version was confirmed
by the user. Performance evidence comes from the PAL E1M1 v8 capture. The user
rejected v9's increased catch-up budget after hardware testing: it reduced FPS
and made control changes too large between frames. v10 keeps PAL calibration
and restores v8's four-tic limit. Firmware comparisons should use the same v10
build on both sides; its hardware results are still pending.

## Conclusions

- The accelerated CPU and Appletini display do not inherently need every
  video write copied to motherboard RAM. F1.1.1 already sends accepted writes
  directly to the renderer and separately coalesces motherboard updates.
- Mirroring preserves physical display and bus-side visibility. Keep that
  compatibility contract as the default.
- Several full-flush conditions are broader than their actual hazards.
  MAIN-only RamWorks switches, ordinary language-card switches, and accesses
  to the built-in mouse are the first candidates for narrower rules.
- An application-controlled local-display mode would permit larger changes,
  including reuse of memory currently reserved for motherboard mirroring.
- A second 48 KiB main-memory context can replace Doom's bulk GAME/RENDER
  snapshots. Selective code residency and a better extended-memory cache
  address a separate cost. These gains cannot simply be added to mirror gains:
  copy phases already include some mirror waits.
- A generic copy/fill engine is an alternative to extra MAIN contexts. It can
  retain today's RAM layout and serve other applications. Faster PSRAM
  scheduling can also benefit existing code without adopting a new API.

**Follow-up recorded at the user's request:** fix the broad F1.1.1 flush
conditions in section 4 later. Those rules remain unchanged. The
`codex/memory-copy-fill-api` firmware branch now implements an ARM-only
SmartPort copy/fill service, using the existing hold, shadow-port and PSRAM-DMA
interfaces. The v11 Doom candidate uses it for private phase memory and the
internal view-buffer clear, with a stock-firmware CPU fallback. The exact
contract is in `appletini-one/README_MEMORY_API.md`; hardware throughput is
unmeasured. This implements generic transfer acceleration before adding MAIN banks.

## 1. What mirroring does in 1.1.1

The paths are:

1. A CPU store updates Appletini's authoritative shadow RAM.
2. An eligible video/overlay store also enters the ordered renderer stream.
3. A separate coalescer records the latest value for a motherboard destination.
4. The physical bus engine eventually writes that value to MAIN or AUX RAM.

TURBO's display path already batches work and accepts writes at fabric speed,
subject to renderer backpressure. It does not impose one synchronous 1 MHz
motherboard transaction on every CPU video store.

The coalescer stores a 128 KiB MAIN/AUX data image and a dirty bitmap. Active
pages drain in the background. Inactive pages may remain dirty until an
exposure or ownership boundary. AUX graphics/SHR retains conservative active
mirroring because classic Apple video switches do not fully describe its use.

Sources: [TURBO contract](https://github.com/hasseily/appletini-one/blob/F1.1.1/README_TURBO.md#L98),
[coalescer](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_video_coalescer.sv#L3),
[video policy](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_video_policy.sv#L18).

## 2. Who needs the motherboard copy?

| Use case | Requirement |
|---|---|
| Appletini HDMI showing Doom's SHR image | Direct renderer records provide the image; physical mirroring is not intrinsically required. |
| Motherboard composite/CRT showing text, lores, HGR or DHGR | Physical display memory must be updated. Deferred/coalesced updates may lag or omit intermediate raster effects. |
| A bus-observing video card or other external consumer | May depend on physical writes and their order; retain the existing contract unless explicitly excluded. |
| Unknown physical card access or DMA | Can expose memory to a consumer outside the CPU shadow; synchronize the relevant data and reconcile external writes. Video mirroring alone is not a general DMA coherence solution. |
| Built-in mouse status and IRQ acknowledgement | Uses register state and cannot DMA; unrelated hidden video data need not be flushed just for this access. |
| Returning to ordinary TURBO/classic display policy | Complete or reconstruct the deferred motherboard image before declaring the transition complete. |
| Apple reset/native CPU restart | Existing reset semantics already discard pending mirror work. Native CPU handback requires a cold reset; it does not resume the accelerated program in coherent mirrored RAM. |

Motherboard memory outside the video windows is already allowed to be stale.
Avoid describing the mirror as a complete copy of the accelerator's RAM.

Sources: [current memory/reset contract](https://github.com/hasseily/appletini-one/blob/F1.1.1/README_VIRTUAL_TRANSWARP.md#L109),
[native handback limitation](https://github.com/hasseily/appletini-one/blob/F1.1.1/README_VIRTUAL_TRANSWARP.md#L374),
[mouse bus outputs](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/mouse_card.sv#L218).

## 3. Why bank changes currently flush

The replay engine saves and changes RAMWRT and, when 80STORE requires it,
PAGE2. It does **not** save, select and restore the physical RamWorks bank.
Consequently, deferred AUX data must be drained before changing that bank,
or a later replay could write it into the newly selected expansion bank.

MAIN destinations do not depend on the RamWorks bank. Nevertheless, the
current `$C071/$C073` rule flushes all pending MAIN and AUX data.

Doom restores ordinary game/renderer memory at addresses that overlap classic
video windows. Those stores can dirty the mirror even though the data is
working memory. Subsequent far-data access or code-bank switching can then
pay for the flush. This cost appears in walls, game and copy phases, as well
as presentation.

Sources: [flush predicate](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_core_top.sv#L1344),
[bank replay invariant](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_video_bank_sync.sv#L3),
[Doom phase copies](../src/kernel/space.s).

## 4. First firmware changes to test

These are proposals, with source-based correctness arguments; they have not
been implemented or measured on hardware.

### A. Preserve dirty MAIN pages across RamWorks changes

Skip the **full** mirror flush for `$C071/$C073` when AUX is drained. Preserve
active-write ordering and the existing physical FIFO barriers. A clean AUX
dirty bitmap alone does not prove that every already-queued write has retired.

When AUX remains pending, retain the current flush. This preserves the rule
that deferred AUX belongs to the base auxiliary bank. An AUX-only flush can
follow later, with separate bank-mask and completion logic.

Ignored bank writes and writes selecting the current bank also deserve an
exception when the actual decoder proves no physical mapping change occurs.

### B. Exclude ordinary language-card switches from full video flushes

The current predicate treats every `$C080–$CFFF` access as an exposure hazard.
On a //e, `$C080–$C08F` changes the language-card latches for `$D000–$FFFF`,
without changing ordinary video destinations. Preserve the double-access
write-enable semantics and active/FIFO ordering while allowing unrelated
hidden pages to remain dirty. Initially constrain this exception to supported
//e configurations and ordinary video windows.

### C. Recognize built-in mouse accesses

`$C0A0` status and `$C0AF` acknowledgement only access mouse registers in the
built-in implementation, whose DMA/address-drive outputs are disabled. These
accesses occur in the VBL IRQ and can otherwise force full flushes every 20 ms
on PAL.

Gate an exception on **actual built-in slot ownership**. An address-only
exception would incorrectly assume that a physical card behind a disabled
virtual slot has the same behavior.

Sources: [LC latch updates](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/soft_switch_manager.sv#L192),
[mouse status](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/mouse_card.sv#L183),
[slot ownership](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/apple_top.sv#L683).

## 5. Application control

F1.1.1 has no application-visible control that disables motherboard mirroring.
`$C074` controls accelerator speed/enable behavior; it is not a mirror-policy
register. Choosing TURBO already selects the current direct-renderer policy.

A new API should use capability discovery and a versioned existing extension
transport, rather than claiming an arbitrary unused-looking soft switch.
The following names describe a proposed contract, not existing commands:

| Operation | Proposed meaning |
|---|---|
| `QUERY` | Return supported mirror policies, fast-memory features and interface version. |
| `ACQUIRE_LOCAL_DISPLAY` | Enter an application-scoped policy after any required transition fence; register physical bank-qualified ranges and return a session token. |
| `SYNC_MOTHERBOARD` | Materialize the latest shared video contents and wait for physical completion. A separate renderer fence must define capture completion versus actual displayed-frame completion. |
| `RELEASE` | Restore compatibility policy synchronously, including required replay and switch restoration. |
| `STATUS` | Report policy, pending synchronization, forced transitions and errors. |

Two possible policies should remain distinct:

- **Deferred mirroring:** retain dirty state and flush only at explicit or
  externally required boundaries. Replaying AUX after arbitrary RamWorks
  changes needs added save/select/restore support for that bank.
- **Local display with no physical replay:** accept that the motherboard
  display becomes stale. On release, reconstruct required video pages from
  authoritative shadow RAM. Keep a dirty bitmap or deliberately resynchronize
  the declared ranges in full.

Initially retain conservative DMA/external-writer fences. A later interface
could declare private working-memory ranges and explicit shared transfer
buffers. Reset/abort and user speed changes must have defined transitions.

A range-based interface could distinguish `PRIVATE` (omit capture and physical
mirroring) from `CAPTURE_ONLY` (retain every renderer record, omit physical
mirroring). For this Doom mode, MAIN `$0400–$0BFF` and `$2000–$5FFF` are working
memory; base AUX `$2000–$9FFF` contains the displayed SHR pixels and controls.
Unlisted ranges retain the existing policy. Acquisition can happen once for
gameplay, without a new command on every frame. Releasing excluded ranges needs
resynchronization from shadow, since draining the old mirror alone cannot
recover writes that never entered it. Policy changes must invalidate affected
cached write permissions.

**A concrete existing transport:** SmartPort controller STATUS plus standard
CONTROL command `$04`. Its ROM already carries length-prefixed CONTROL data;
the PS service currently rejects CONTROL with `ERR_BADCTL`. A documented vendor
capability/status selector and CONTROL payload could add the policy without
claiming new Apple MMIO addresses. Selector numbers remain to be assigned.
GETDIB identifies `Appletini SP`, but its reported version is hard-coded protocol
1.0, so it cannot prove support for the new API. Slot ownership must be verified.

Reserved LINTXT offsets are not permission to use them without an interface
revision. The application's fallback on older firmware or a different slot
configuration should be the current compatible behavior.

Sources: [CONTROL ROM transport](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/smartport_a2retronet_style.asm#L512),
[current CONTROL rejection](https://github.com/hasseily/appletini-one/blob/F1.1.1/ps_sources/frontend/smartport_service.c#L1737),
[controller identity](https://github.com/hasseily/appletini-one/blob/F1.1.1/ps_sources/frontend/smartport_service.c#L1195).

## 6. Fast RAM for Doom

### Persistent phase contexts

Add a selector for **main `$0200–$BFFF`**, independent of RamWorks. Keep main
zero page, the hardware stack, I/O and main language card shared. Existing main
RAM holds one phase; one additional **48 KiB** slab holds the other.
The selector must affect CPU reads, writes and physical cache tags without
changing AUX/RamWorks selection. Private phase pages should also carry the
private capture/mirror policy, so working-memory stores do not create new
video dirty state.

The switch runs from resident main-LC code. Keep the current 174-byte renderer
zero-page save/restore, and preserve the existing packet/input handoff. The
framebuffer remains in the renderer context. GAME's near pointers and shared
gate code remain valid within its context.

Cost: **12 BRAM36 tiles** for byte-wide storage. This avoids both bulk phase
copies, which occupied about 27% of v8. Removing that phase cost alone has an
ideal ceiling around 1.37×; hardware barriers overlap it.

In the initialized v9 E1M1 model, the arena ends at `$7A91`, rounded to `$7B00`
for snapshots. The four transfers per frame are 17,152 bytes of renderer save,
30,976 bytes of game load, 23,040 bytes of game save, and 35,584 bytes of renderer
load: **106,752 copied bytes per frame**, or 213,504 source/destination byte
accesses before loop overhead. The 174-byte ZP save/restore and 13,440-byte
framebuffer clear remain unless changed separately.

### Extended code and context storage

The six extended code banks use `$D000–$FFFF`: **72 KiB** in total. Their zero
pages and hardware stacks add **3 KiB**. Base-auxiliary control code already
uses fast shadow RAM.
Pin the physically translated LC2/high pages; these code banks do not require
an additional LC bank-1 4 KiB allocation.

Pinning all six plus their small contexts costs about **19 more tiles**, for
31 tiles including the extra phase. A smaller allocation can pin selected hot
banks, for example actors, weapons and specials, while retaining all six small
ZP/stack contexts: about 10 tiles plus the 12-tile phase image.

Capacity must be checked against the actual release build. The old 74/140
utilization figure is obsolete. F1.1.1's TURBO notes mention 110/140 for a
specific failed-timing trial, not a verified final-release resource report.

### Better cache / DDR backing

F1.1.1's new 128-byte shadow cache does not cache extended PSRAM. That path
still has a shared eight-byte write-allocate line. Multiple resident lines,
physical tags, pinned code/context lines and better burst scheduling deserve
separate measurement. Cached DDR offers much more capacity but needs an FPGA
memory interface and explicit coherence with ARM services.

### Reusing mirror storage

In an explicit mode that disables physical mirroring, the existing coalescer's
128 KiB data storage is large enough in capacity terms for a 48 KiB phase image,
72 KiB of code and 3 KiB of ZP/stacks: **123 KiB**. This requires redesigned
ports/mapping and entry/exit behavior; it is not a present firmware feature or
a proven timing fit. Dirty tracking or full-range resynchronization is still
needed when restoring motherboard visibility.

### Remove duplicate mirror storage while retaining mirroring

Another option is to keep the dirty bitmap and fetch each pending byte from
the existing MAIN/AUX shadow when it is ready for physical replay. The mirror's
128 KiB data array duplicates that storage. In principle, removing it could
recover about **32 BRAM36 tiles** while keeping physical display support.
That is enough capacity for the 31-tile phase-plus-all-code proposal above,
before added arbitration and implementation overhead.

This is feasible architectural work, with an important ordering issue: the
current shadow store can commit before the renderer accepts its event. A
backpressured overwrite must not cause replay to expose a newer, unaccepted
value for an already-dirty address. Aligning shadow commit with accepted video
writes, or retaining the last accepted byte for the blocked address, is needed.

The mirror would use spare shadow port-B cycles, preserving the ARM host port's
fixed-latency contract. It must detect CPU write/read collisions, reconcile ARM
writes, retain concurrent dirty updates, and hold a fetched tuple stable while
the bus queue stalls. Motherboard drain bandwidth is much lower than the fabric
port's capacity, but timing and arbitration still require synthesis and tests.

This may be the best long-term memory design because it can free storage while
retaining the current mirroring feature. It is more work than narrowing flush
conditions and has no measured speedup yet.

Sources: [shadow storage](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_shadow.sv#L99),
[extended-memory cache](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_core_top.sv#L994),
[shadow commit and capture acceptance](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_core_top.sv#L1278),
[build capacity caveat](https://github.com/hasseily/appletini-one/blob/F1.1.1/README_TURBO.md#L146).

## 7. Measurements and correctness gates

Add counters for flush reason, bytes retired and stalled clocks, separating
RamWorks, LC, mouse IRQ, other I/O, policy changes and external holds. Snapshot
them frequently enough to handle 32-bit wrapping; preferably expose one atomic
snapshot. Current `wait video` mixes posting stalls and barriers, and the cache
hit/miss fields do not describe a single PSRAM hit rate.

Test MAIN-only and MAIN+AUX dirtiness across bank changes; RAMWRT/PAGE2/80STORE
combinations; queued writes/backpressure; LC latch sequences; built-in versus
physical mouse ownership; DMA and external writes; policy transitions; reset;
and correct restoration of physical switches.

Compare the same v10 disk under each firmware candidate. Record FPS **and TPS**
for a stationary view, movement and combat. The v8 video-wait delta suggests
roughly a quarter of fabric time subject to counter-wrap/snapshot caveats; it
does not establish a precise removable fraction or an additional independent
gain on top of phase-copy removal.

For a firmware implementation, measure the narrow flush changes independently
from transfer acceleration. Section 8 assesses the generic transfer alternative
before committing BRAM to persistent phase memory.

## 8. Faster copying instead of extra MAIN banks

This is a design assessment against F1.1.1, not an implemented feature or a
hardware benchmark. The two useful layers are improvements to ordinary TURBO
memory access and an application-callable bulk copy/fill service.

### Where time goes today

Doom's page copy already unrolls eight byte transfers. Each byte still needs
an indirect load, an indirect store and index work. More unrolling only attacks
part of that cost. TURBO shortens safe CPU cycles, so ordinary 65C02 cycle
counts must not be treated as fabric clocks or converted using a fixed TURBO
MHz rating.

For scale, the current page-aligned loop costs 3,437 classic 65C02 cycles per
256 bytes, excluding call setup and hardware stalls. Doubling the unroll from
eight to sixteen saves only about 1.4% of that loop's classic cycles while
adding 40 code bytes. This is not a route to several-times-faster transfers.

The backing banks are PSRAM. Its separate, single eight-byte CPU cache uses
write allocation: a save into a new destination line reads its old contents
before patching and eventually writing all eight bytes. A bulk engine knows
when it will replace an entire aligned line and can omit that old-data read.
Partial first/last lines still require preservation of untouched bytes.

The PSRAM scheduler admits a background operation at most once per Apple bus
cycle, within a 40-fabric-clock admission window. This limits even the existing
PS DMA path to roughly **8 MB/s of line payload** before contention and setup.
PSRAM-to-PSRAM copies need a read and a write, so their corresponding ceiling
is roughly **4 MB/s of copied payload**. These are scheduler bounds, not
measured application rates and not a synchronous 1 MHz model for video stores.

Sources: [Doom page copy](../src/kernel/space.s),
[write-allocate cache](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_core_top.sv#L994),
[miss handling](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_core_top.sv#L1928),
[PSRAM scheduling](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/psram_simple.sv#L232).

### A. Let PSRAM run whenever safe while Appletini owns the bus

F1.1.1 already suppresses native AUX read service while `vtw_bus_owned` is true;
the accelerated CPU uses its private memory path. Yet background PSRAM requests
still wait for the per-Apple-cycle window. During exclusive ownership, allow
fixed eight-byte operations whenever the driver is ready, retaining priority
for committed external/posted writes and fair access for other clients.

This needs an explicit quiesce/drain handshake before physical bus handback.
Simply OR-ing `vtw_bus_owned` into the admission predicate could launch a
transaction immediately before release and miss the first native read deadline.
Reset, abort and external DMA ownership transitions need the same analysis.
The native path retains its existing deadline schedule.

This is a relatively focused RTL change that could help existing RamWorks
software automatically, including code fetches and small data accesses. Its
gain depends on how often callers wait for admission. It does not eliminate
CPU instructions, cache conflicts or mirror barriers.

Sources: [read-service ownership gate](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/psram_simple.sv#L134),
[admission priority](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/psram_simple.sv#L434).

### B. Add a generic bank-aware copy/fill engine

These are explicit new calls, so they need not enforce TURBO or change the
selected CPU speed. Gate availability on capabilities and safe memory ownership.
The initial shadow-based implementation can support other active vTW speeds;
native motherboard-CPU operation requires a separate coherent memory backend.

Expose explicit source/destination memory spaces, bank identities, offsets and
lengths. Resolve those to physical addresses independently of the CPU's current
RAMRD/RAMWRT/ALTZP/RamWorks selection. The engine then moves words/lines between
shadow BRAM and PSRAM without executing a 65C02 instruction per byte. A small
FIFO can bridge the 32-bit shadow port and 64-bit PSRAM transactions; no second
48 KiB MAIN image is required.

Start with synchronous COPY and FILL plus an ordered descriptor list. Define
overlap explicitly: reject it initially or implement correct forward/backward
memmove behavior. Keep commands, caller, stack and completion state outside
destination ranges. Flush dirty source cache state, hold the CPU safely, then
invalidate or update destination cache entries before resuming. Coordinate
with the ARM host port and other DMA clients. Small transfers should retain a
software path below a measured setup-cost threshold.

For Doom, submit one list at each phase handoff:

1. Save the current phase's mutable ranges into its existing backing bank.
2. Load the other phase's existing image into MAIN.
3. On return to RENDER, clear the 13,440-byte view buffer after restoring the
   renderer's saved zero page from its first bytes.

The third step has a CPU dependency: either keep the clear as a separate call,
or arrange a distinct saved-ZP buffer before combining it into the transfer
list. Do not clear the saved renderer zero page before restoring it.

Bank-to-bank copies could avoid the current 256-byte CPU bounce buffer and
repeated soft-switch changes. The packet publication could copy from the
explicit base-AUX LC source directly to bank 124, retaining header-last
publication. Larger texture/data-cache loads, buffers, snapshots and clears
would also benefit. A future strided blit mode could handle Doom's column-to-row
conversion and doubled pixels; plain memcpy cannot replace that transform.

The shadow RAM already has aligned 32-bit reads on both ports and 32-bit writes
on the ARM port. An autonomous engine needs port arbitration and completion
logic, not a new wide-RAM design from scratch. Longer PSRAM bursts are a later
step: today's driver transfers fixed eight-byte lines. Adding bursts requires
driver/arbiter changes and validation of device timing, burst boundaries and
maximum chip-select duration.

Sources: [wide shadow ports](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_shadow.sv#L68),
[fixed-size PSRAM interface](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/psram_driver.sv#L7),
[Doom far copies](../src/kernel/far.s), [packet publication](../src/game/a_view.s),
[display transform](../src/kernel/video.s).

### C. Prototype through ARM using existing RTL

A PS-firmware-only prototype can stage MAIN through DDR using the packed
shadow port, then use the existing DDR-to-PSRAM DMA engine; reverse those steps
for loads. Add a versioned vendor command through the existing SmartPort
CONTROL transport. Batch ranges per handoff to amortize service overhead.
This command does not exist in F1.1.1.

Expose this through an SDK helper taking a command-list pointer, returning
synchronously with carry clear on success. Probe a versioned controller STATUS
capability first; use controller unit 0 and a newly assigned vendor CONTROL
selector to submit COPY/FILL descriptors. The standard CONTROL command is
`$04`; the new selector and payload ABI still need assignment. The payload's
16-bit length excludes its own two bytes.

For arbitrary MAIN snapshots, the submitter must avoid the ordinary ROM entry's
`DSETUP` write to MAIN `$07F8`. Restoring that byte after the command is too late
if a save already captured it, and could overwrite the new phase after a load.
A resident-LC helper can send the same protocol through the existing SmartPort
FIFO (`$CFF0` DATA, `$CFF1` CTRL, `$CFF2` DPOP) after verifying slot/C8 ownership,
or firmware can advertise a dedicated entry that avoids this workspace write.
Preserve zero-page scratch and keep active stack/return state outside copy
destinations. Only descriptors travel through the FIFO; payload memory moves
through the copy service. The ordinary ROM transmits nine parameter-list bytes,
so a caller using it must pad the five meaningful CONTROL bytes with four zeros.

The prototype must split each logical bulk request internally, for example
into 512-byte DMA chunks while retaining the hold. F1.1.1 instantiates the DMA
engine with a ten-bit length and connects only `dma_req_length[9:0]`, although
the C helper accepts a sixteen-bit length. The current command module passes
the length through without splitting. Do not submit a 32 KiB transfer to that
helper as one request; the interface limit needs correction or explicit
chunking. The narrower engine was chosen to meet fabric timing.

This would establish real setup and transfer times before designing new RTL.
It is not a zero-copy path: ARM shadow reads currently perform readiness,
request, completion and data MMIO operations per four bytes. The PSRAM leg
still has the bus-cycle admission limit. MAIN-to-RamWorks saves are the simplest
first experiment because they do not modify a displayed shadow region.

**Do not blindly reuse the complete SmartPort restore helper.** Its BRAM writes
alone do not notify the renderer. Its video fix-up path uses ARM POST_PUSH and
waits for physical posts to drain, rather than feeding TURBO's direct capture
and coalescer. A generic fast restore must implement the correct display policy
or it can lose much of the expected benefit.

Sources: [packed shadow writes](https://github.com/hasseily/appletini-one/blob/F1.1.1/ps_sources/frontend/smartport_service.c#L594),
[packed shadow reads](https://github.com/hasseily/appletini-one/blob/F1.1.1/ps_sources/frontend/smartport_service.c#L846),
[SmartPort video fix-up](https://github.com/hasseily/appletini-one/blob/F1.1.1/ps_sources/frontend/smartport_service.c#L652),
[ARM post routing](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/vtw_core_top.sv#L1432),
[instantiated DMA width](https://github.com/hasseily/appletini-one/blob/F1.1.1/hdl/apple/apple_top.sv#L1785),
[C DMA length validation](https://github.com/hasseily/appletini-one/blob/F1.1.1/ps_sources/lib/psdma.c#L96).

### Display policy and profiling remain part of the design

Normal copies into visible video memory must reach the ordered renderer stream
and the selected motherboard mirror policy. The engine must honor backpressure.
Explicitly declared private working ranges can omit those effects; declaring
them private changes the visibility contract and requires the entry/exit rules
from section 5. A DMA write to BRAM must not silently become a way to bypass
normal video semantics. The broad flush work remains relevant to command entry
and cache-hold operations as well as ordinary CPU banking.

CPU holds introduce another measurement issue. The mouse VBL interrupt is a
pending event, not an elapsed-time counter. A hold spanning multiple 20 ms PAL
frames can coalesce interrupts and undercount elapsed time. Use a free-running
hardware timestamp for copy benchmarks and game-clock reconciliation, or ensure
bounded holds with adequate interrupt service between chunks. Record copied
bytes, setup clocks, memory wait clocks, capture wait clocks and mirror waits
separately. Compare the same v10 PAL workload on both firmware versions.

### Expected scale, with bounds

The v8 copy phases account for about **72.4 ms of a 268.1 ms frame**. Combining
that observation with the initialized E1M1 payload of 106,752 bytes gives an
effective **1.48 MB/s**. This includes CPU work, framebuffer clearing, banking
and synchronization; it is not the PSRAM wire rate or a direct v9 measurement.

At the existing scheduler's ideal 8 MB/s bound, that payload alone takes
13.3 ms. At a hypothetical measured 20 MB/s after scheduler/engine changes,
it takes 5.3 ms. Both exclude setup, clears, display effects and contention.
Thus a 5–10 times reduction in bulk-transfer cost is a reasonable engineering
target for a direct engine plus scheduler improvements, not a measured result.

If the *entire* two copy phases improved by the factors below and all other
v8 work stayed fixed, the resulting rates would be:

| Copy-phase speedup | Whole-frame speedup | Illustrative v8 FPS |
| --- | --- | --- |
| 2 times | 1.16 times | 4.31 |
| 5 times | 1.28 times | 4.76 |
| 10 times | 1.32 times | 4.93 |
| Copy phases free | 1.37 times | 5.11 |

The main value is a reusable memory facility. Faster PSRAM may also help walls
and gameplay, and a later blitter could reduce presentation cost; those gains
require separate evidence. A faster memcpy alone cannot deliver 5 times Doom
performance. Extra MAIN contexts remain an option if residual copy cost proves
important after this more general work.
