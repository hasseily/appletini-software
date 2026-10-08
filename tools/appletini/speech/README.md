# Appletini SSI-263 speech reference worker

This directory builds a separate **GPL-3.0** executable. The GPL-2.0-only
runner does not link these C++ sources. Its independently written client
`../speech.py` exchanges timestamped register writes and PCM with the worker
over standard input/output. `../speech_state.c` independently implements the
guest-visible registers, response counters and IRQ routing; it runs even when
audio output is disabled.

The vendored source comes from `hasseily/appletini-one`, commit
`1a3e8d38c57814471640c748879af28dbf16b266` (current F1.2.5 target checkout).
[reference/PROVENANCE.json](reference/PROVENANCE.json) records original paths
and SHA-256 hashes, generated data and modifications.
[reference/COPYING](reference/COPYING) contains the upstream GPL-3.0 license.
The retained sources and comments have not been relicensed. No gssquared,
SC-01 coefficient package, sampled speech or platform text-to-speech is used.
The 512-byte SC-02 parameter ROM is copied from the same hardware repository;
`rom.inc` is only its byte-for-byte C initializer, not a generated voice model.

The worker reuses `native_control`, `native_source` and `prototype_tract` from
`scripts/ssi263_host`. Despite the retained class name, this tract is the
reference used by the current native hardware engine. The adapter implements
the current `ssi263_native_pitch.sv` glide policy and AP reset behavior. It
uses the board's cold FF=0, ART reference RATE=8, voice trim 16384 and output
gain 1. Output uses the default +2 dB speech gain with secondary/socket 0 on
the left and primary/socket 1 on the right. Runtime frontend pan/volume
changes and their gain ramp are not emulated.

This is a deterministic **hardware reference model**, not proof of analog
SSI silicon accuracy. The upstream model retains provisional startup noise,
pitch-glide and analog calibration assumptions. FPGA FIFO/divider pipeline
latency, physical propagation delay and the DAC reconstruction filter are
not simulated. AP reset clears dynamic sound state, retains programming
registers except CTL=80, and retains the pitch mode/seed. The controller's
three-valued unknown startup nodes follow the host reference.

## Use and timing

`SpeechWorker(rate=48000, guest_hz=..., origin=..., xck_hz=...)` starts one
persistent worker. `render(pcm_s16le, events)` returns equal-length mixed
signed 16-bit little-endian stereo PCM. Each event is
`(absolute_guest_tick, socket_0_or_1, register, byte)`. Registers 0–7 are SSI
writes (4–7 alias FF), 8 requests AP warm reset, and 9 requests cold reset.
`close()` releases the process. The client builds the worker with C++17 and
`-O2` on first use or after its source changes; `CXX` selects the compiler.
No sibling checkout, Python package or network download is needed.

Use native `ap_get("clock_hz")`, `ap_get("audio_origin")` and
`ap_get("speech_xck_hz")`. Native audio uses rounded integer guest Hz, shared
by this worker. Sample n (zero-based) ends at
`origin + ceil((n+1)*guest_hz/48000)`. Writes at that exact boundary affect
the following interval. Effective XCK advances by the exact integer ratio
of elapsed guest time, so block sizes and host scheduling do not change PCM.
The SSI clock follows motherboard Q3/2: the default PAL reference is
1,015,625 Hz; native derives the selected PAL/NTSC effective motherboard rate.
Sub-cycle NTSC Q3 edge placement is approximated by that average frequency.

The client queues future events, including calls with zero PCM. A boundary
event may arrive with the following PCM block; older events fail explicitly.
The queue is bounded at 65,536 events, blocks at ten seconds, and IPC waits
have a bounded timeout. Native PCM addition saturates rather than wrapping.

## Independent controller

The two SSI-263AP sockets have separate registers and counters. DUR/INF/RATE
writes acknowledge D7. A CTL falling edge latches a nonzero DR mode; DR=00
disables interrupts while retaining the prior response function. Mode 1
responds after 16 RATE slots; modes 2/3 after 16 duration slots. Slots reload
the live RATE value. D7 remains readable without clearing it. Phasor mode 5
routes an enabled request directly to CPU IRQ; Mockingboard mode 0 generates
VIA CA1 on an enabled request edge when PCR selects falling-edge detection.
SSI acknowledgment does not clear the VIA's IFR latch. A mode change routes
an already pending request to the new destination. Warm reset retains DUR,
INF, RATE and FF, disables requests and sets CTL=80.

Counters advance on effective XCK boundaries. The small registered latency
between RTL counters and the Apple-visible bus is omitted. This controller
models the installed pair of AP sockets; optional SC-01 address compatibility
and non-AP socket variants are outside this profile.

## Binary protocol

The executable is launched as
`ssi263-speech --stream GUEST_HZ XCK_HZ ORIGIN`; `--help` prints the framing.
Each request starts with 12 bytes: ASCII `SSI1`, little-endian uint32 frame
count, little-endian uint32 event count. Each event is 16 bytes:
little-endian uint64 absolute tick, uint8 socket, uint8 register, uint8 value,
five reserved bytes. Events are ordered, and all must be at or before this
request's last sample boundary. Then come `frames*4` bytes of native PCM.
The reply is ASCII `SSO1`, little-endian uint32 PCM byte count, then mixed PCM.
The Python client retains events beyond the current block. End of input
closes the worker; malformed input reports an error on stderr and exits.

Run `python3 -m unittest discover -s tests -p test_appletini_speech.py -v`.
Tests cover response periods and live reloads, two independent sockets,
IRQ/PCR/acknowledgment, warm reset, fractional clock conversion, audible
phonemes, channel routing, cold replay, chunk-independent PCM, boundary
events, bounded queues and failed workers.
