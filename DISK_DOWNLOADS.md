# Disk downloads and build checks

The [download catalog](README.md#disk-images) links the ready-to-use files.
[SHA256SUMS](SHA256SUMS) covers those downloads and the Appli-Card boot,
utility and ProDOS media. Hashes describe the committed bytes, including ZIP
packaging; they do not establish hardware compatibility.

## Built on 2026-10-22

| Download | Build output | Checks performed |
|---|---|---|
| `libtini/examples/starfall/STARFALL.po` | `libtini/build/starfall.po` | All 22 libtini checks pass, among them builds, host tests, native emulator tests and ROM-boot STARFALL runs with Mockingboard and Phasor; the browser player matches the native machine through a ROM boot at vtw33 and turbo-f122 |

Build it from `libtini/` with Python 3 and cc65 2.19; the first command
installs the pinned ProDOS 2.4.3 input:

```sh
python tools/setup_inputs.py
python tools/build.py --cc65-home <cc65>
```

The checks are emulator evidence. This build's effect and music levels follow
the owner's listening on hardware; libtini's checks and status page,
`libtini/docs/reference/testing.html`, lists the remaining board gates.

## Built on 2026-10-12

| Download | Build output | Checks performed |
|---|---|---|
| `demos/fatdog_magic/FATDOG_MAGIC.po` | `demos/fatdog_magic/dist/FATDOG_MAGIC.po` | All 52 images and system files match bundled inputs; boot order, boot blocks and complete ProDOS allocation pass |
| `demos/appletini_invasion/Appletini-Invasion.hdv` | `demos/appletini_invasion/dist/Appletini-Invasion.hdv` | System and parallax payloads read back identically; loader bounds, asset header, boot blocks and image size pass; speech scheduler tests pass |
| `music/house_of_the_rising_sun/RISING.SUN.hdv` | `music/house_of_the_rising_sun/player/build/RISING.SUN.hdv` | Full PAL and NTSC streams execute through py65; all 18,884 register writes, timing, loader/error paths, replay/stop/quit, overrun mute and disk contents pass |

The published files are byte-for-byte copies of these build outputs. These
checks did not include a new ROM-level boot or physical-board test. Existing
download images were retained, including the user-validated Mockingboard disk
and Pinball's build with its unresolved hardware sprite-smear report.

Rebuild FATDOG with Python 3, ACME, Java and AppleCommander:

```sh
python demos/fatdog_magic/tools/build_fatdog_magic_disk.py
python demos/fatdog_magic/tools/verify_disk.py
```

Rebuild Invasion with Python 3/Pillow, cc65, GNU make, Java and AppleCommander:

```sh
cd demos/appletini_invasion
make disk APPLECOMMANDER_JAR=/path/to/AppleCommander.jar
make test
```

This refresh compiled Invasion under WSL Ubuntu, then ran `tools/build_disk.py`
with native Windows Python/Java and its `--applecommander` option. The builder
used the sibling firmware checkout's ProDOS 2.4.3 master. See the project
README for master and tool overrides.

Rebuild Rising Sun with Python 3, cc65, GNU make and py65:

```sh
cd music/house_of_the_rising_sun
make streams disk
make check
```

This refresh used WSL for assembly and native Windows Python for
`player/check.py`. Copy the verified outputs to the download paths above,
then update `SHA256SUMS` whenever publishing a replacement.

## DOOM GS v1.5 rebuild

The converter now uses the [v1.5 reference image](https://github.com/Webifi/iigs-doom/releases/download/v1.5/doom-hd.hdv)
with SHA-256 `917212c62acf08d4ff27752e44a97543b8e142a1587e26dc0ee3f22e0053a9e5`
and source commit `e645893f3d1ac6826e560e0ed3b28e0062c33995`.
The original reference disk stays in ignored `build/release/` as a build input.

The downloadable [DOOM.hdv](demos/doom_gs/DOOM.hdv) is copied from
`demos/doom_gs/build/native/DOOM.hdv`. Rebuild with `./build.sh` in that
project, then run `make -C tools/ref816 test` and
`python3 tools/native/check_release.py`. The source-to-image comparison,
renderer captures, table checks, native memory budgets and model play checks
are described in [DOOM validation](demos/doom_gs/VALIDATION.md).

This updates the reference inputs and conversion pipeline for the existing
65C02 port. It does not import all new IIgs hardware features. The user
subsequently confirmed successful hardware testing of the published disk;
see the [hardware validation record](demos/doom_gs/VALIDATION.md#hardware-validation).

## Glyph Lab

The [Glyph Lab demo](demos/glyph_lab/README.md) includes a bootable
[Glyph-Lab.hdv](demos/glyph_lab/Glyph-Lab.hdv): an 800 KiB ProDOS volume that
starts `GLYPH.SYSTEM`. Its three animated 40-column text scenes upload original
4 KiB fonts through SmartPort. Running it requires Appletini firmware with the
AGLY v1 character-ROM API and an active ARM video renderer.

The [manifest](demos/glyph_lab/manifest.json) records build inputs and output
hashes; [SHA256SUMS](SHA256SUMS) covers the downloadable disk.

Rebuild and run the host tests with Python 3, ACME, Pillow and py65:

```sh
cd demos/glyph_lab
python tools/build.py
python tests/test_glyph_lab.py -v
```

Both commands default to the sibling `appletini-one` checkout. Pass
`--appletini-root /path/to/appletini-one` to either command to use another path.
The tests execute the assembled demo and SmartPort ROM against a modeled ARM
backend, checking font upload, commit and restore, controls, error paths and
disk contents. The included previews are model output. The user confirmed
successful hardware validation of the demo.
