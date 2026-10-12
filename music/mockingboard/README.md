# Sound & Speech I demos for ProDOS

`Mockingboard_IIplus_IIe.po` is a bootable 140 KB **native ProDOS** disk for a
64 KB Apple II+ or Apple IIe, with a Mockingboard-compatible card in slot 4.
It contains all 18 files from the supplied 1982 disk, plus ProDOS 2.4.3,
BASIC.SYSTEM and an automatic STARTUP program. The original `.dsk` is unchanged.

Boot the `.po` normally. To use it from an existing ProDOS installation, copy
the demo files into one directory, set that directory as the current prefix,
and use `RUN STARTUP` from BASIC.SYSTEM. Start with STARTUP or DEMO; the menu
programs share the machine-code routines loaded by that initializer.

The original A-H menu and all twelve A-L sound effects are retained. Menu keys
accept either case. Escape returns from the sound/music menus; Escape during
speech or the train stops it. Selecting the next sound effect silences the
previous one. The train also stops its sound when it finishes normally.

Speech is detected automatically: original SC-01 first, then the primary
SSI-263 socket used by later Mockingboards and Appletini's virtual Phasor.
The detected interface appears on the main menu. An ordinary Mockingboard
without a speech chip still plays the sound and music demos; the speech option
reports the missing speech response and returns on a keypress. Hardware that
stops responding during speech times out and is disabled until STARTUP is run
again. SSI-263 playback translates the original phonemes, so its voice and
timing differ from an original SC-01.

## What caused the freezes

The original entry at `$8000` sends speech through VIA-A's port B and calls
`$9013`, whose `$9014-$9019` loop waits forever for SC-01 CB1 readiness in
`$C40D` bit 4. The long speech demo calls it directly. The train calls it four
times for its whistle. Invalid keys in three menus and the worm's final
"oops" use it too. This is a speech-interface mismatch or absent response,
not a IIe-only CPU instruction problem.

The replacement driver supports native SC-01 and translated SSI-263 speech,
polls Escape, bounds each ready wait using eight VIA timer-2 periods (about
0.52 seconds), and caps phrase traversal at 256 bytes. It uses no ROM interrupt
handler or CPU-model-specific opcode. Timer expiry follows the card's clock;
it does not assume that accelerated CPU instruction time equals speech time.
A secondary finite poll count handles a non-counting timer.

For ProDOS, long/spaced filenames and their RUN/BLOAD references are converted
to legal names. BASIC memory is limited below `$2000`. Both original shape
tables are relocated from `$1000/$1100` to `$6000/$6100`, above the two HGR
pages and away from BASIC variables. The speech tables, AY tables, shape
contents, title graphic and sound-effect machine code are preserved.

## Rebuilding

From the repository root, with Python 3 and ACME installed:

```text
python music/mockingboard/tools/build_disk.py
python music/mockingboard/tools/verify_disk.py
python music/mockingboard/tools/test_driver.py
python music/mockingboard/tools/test_emulator.py --platform all
```

The driver tests additionally require `py65`. The builder uses the tracked
ProDOS master at `demos/fatdog_magic/assets/ProDOS_2_4_3.po`, rejects a source
disk whose SHA-256 differs from the audited input, and independently reads
back every output file and checks its allocation bitmap. No downloads, Java,
or DOS filesystem emulation are needed. Generated BASIC listings and assembler
output are in the ignored `build/` directory; input/output hashes and the
complete original-to-ProDOS file map are in `build-manifest.json`.

The emulator runner requires GSSquared and its `gs2debug` Python client;
`--emulator` and `--client-path` override the local defaults. It launches private
II+/IIe configurations and mounts private copies of the image. Audio output
is disabled during automation; speech readiness and return paths are checked.

The SC-01-to-SSI-263 map is adapted from Tom Charlesworth's
[play-sc01-using-ssi263](https://github.com/tomcw/play-sc01-using-ssi263).
Its MIT notice is in `THIRD_PARTY_NOTICES.txt`. The original demo programs retain
their 1982 Sweet Micro Systems copyright notices.

## Validation scope

The independent driver harness executes the assembled code on an NMOS 6502
model with separate CPU and hardware clocks. Its 21 checks cover all three
original phrases through both speech interfaces, delayed responses, absent
speech, mid-phrase failure, Escape, unterminated data, stack/register integrity,
an empty slot, and a synthetic 32x CPU clock. The software watchdog's exit
is also checked with its counter seeded near expiry. This is not a measurement
of Appletini TURBO.

The user confirmed hardware validation on 2026-10-12. Tested machine/card
combinations were not specified in that confirmation. Hardware confirmation
and the detailed emulator results are recorded in `VALIDATION.md`.
