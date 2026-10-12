# Validation — 2026-10-12

Release: `Mockingboard_IIplus_IIe.po`, 143,360 bytes, native ProDOS, 21 files,
113 of 280 blocks used.

SHA-256:
`18f6197b90cf3d9bfbde322ea374a869f93177c93453e89cd587433c1c85547a`

The original DOS disk remains unchanged:
`5745a87e1c6dfb9948ce9fa759d27504a22883c2ff0349e195c9370bbd6e238c`.
The build manifest records the original and converted file hashes and names.

## Full-machine execution

GSSquared executable tested:
`C:/Users/hasse/source/repos/gssquared/build-phasor-pr/GSSquared.exe`

Executable SHA-256:
`c5bf94c13f198c334ebe2a744e6c3032b1d0502c023c2af120a927a41830d98f`

Each machine used a fresh configuration with a slot-4 Mockingboard and slot-6
Disk II; the II+ also had a slot-0 language card. The emulator mounted private
copies of the exact release image. The primary SSI-263 was detected, and the
full speech demonstration returned with success status, not the missing-chip
or timeout path. Audio output was disabled during these automated tests.

| Machine | All menus and demos | Train and speech Escape | Exit to working BASIC |
| --- | --- | --- | --- |
| Apple II+ / NMOS 6502 | Passed | Passed | Passed |
| Apple IIe / NMOS 6502 | Passed | Passed | Passed |
| Enhanced Apple IIe | Passed | Passed | Passed |

For each machine, the runner exercised all twelve A-L sound effects, all eight
music keys, full speech playback, Worm, Laser, Multiple Tones, both Multiple
Noise programs, lowercase menu input, invalid keys, and returns between menus.
It inspected the executing BASIC line and advancing CPU cycles as well as
screen text, so stale menu text alone could not count as a successful return.
The final exit check made BASIC execute `PRINT"EXIT.OK"` and verified its output.

The unenhanced IIe completed all 38 checkpoints in one run. II+ and enhanced
IIe each completed the first 37 checkpoints; their original last assertion
incorrectly assumed END resets Applesoft's current-line number to 65535.
That assertion failed at a responsive BASIC prompt. A corrected, targeted
exit test then passed on both machines without repeating the successful demo
checks. The original failed assertions remain in the raw evidence, alongside
the successful exit tests; they are harness failures, not suppressed results.

Evidence is retained in the ignored build directory:

- `build/emulator-final/p1/`, `p2/`, `p3/`: per-check state, machine commands,
  image hashes and emulator logs.
- `build/emulator-exit/p1/`, `p3/`: corrected exit checks and exact BASIC output.

The final IIe train sequence completed in about 4.65 emulated seconds,
including the test's readiness overhead. Full translated speech took about
13.6 seconds. These are emulator observations, not Appletini performance
measurements. The original empty-FOR pause loops are retained in the train.

## Driver and image checks

`tools/test_driver.py` passed 21 checks while executing the actual 790-byte
driver in a py65 NMOS-6502 model. The model clocks speech and VIA timers
independently of the CPU. It covers all original phrase tables on both SC-01
and SSI-263, 250 ms phoneme responses, no speech chip, an empty slot, stalled
speech, Escape and AY silence, register/stack/interrupt-mask preservation,
unterminated data, and synthetic CPU rates of 1x and 32x. The secondary software
watchdog exit was tested with its counter seeded near expiry; the entire
long countdown was not run. This is not a TURBO hardware benchmark.

Driver SHA-256:
`ae288d99d84330d535283f1ee25c15e0bca78f7c80549323ad480426a80d662c`

`tools/verify_disk.py` passed all five groups of independent image checks:
source identity and all 18 original files; runtime/boot/STARTUP and manifest
integrity; BASIC links, branches, file references and memory bounds; original
data and sound-code preservation; patched vectors and relocated memory ranges.
The builder also verifies extracted output payloads and the allocation bitmap.

Reports: `build/driver-validation.txt`, `build/driver-validation.json` and
`build/verify_disk.json`.

## Physical validation

On 2026-10-12, the user confirmed the delivered image was "Validated on
hardware." This is user-reported hardware validation of the release above.
The follow-up did not specify the tested machine/card combinations or individual
test cases.

The automated evidence above remains emulator and driver-model validation:
native SC-01 behavior was modeled, and the full-machine emulator runs used
SSI-263. A card without an SC-01 or primary SSI-263 cannot produce this speech;
the disk reports that condition and remains usable instead of waiting forever.
