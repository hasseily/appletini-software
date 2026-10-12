# Disk downloads and build checks

The [download catalog](README.md#disk-images) links the ready-to-use files.
[SHA256SUMS](SHA256SUMS) covers those downloads and the Appli-Card boot,
utility and ProDOS media. Hashes describe the committed bytes, including ZIP
packaging; they do not establish hardware compatibility.

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

## DOOM GS build dependency

No new `DOOM.hdv` is included. The source pin
`8ea2eac8b650daf2cf66127c4be6d3f8654dd335` remains fetchable explicitly, but
the original v1.0 `doom-hd.hdv` download returns HTTP 404. Its required SHA-256
is `2716166dda1d87faf3bdec572ddcf652379a54da78f1dcccdd0897e00b23bd0d`.
The builder uses that exact reference image to recover layouts, compare its
assembled upstream code byte for byte and capture renderer data. A newer
upstream release cannot simply be substituted. See the
[local-input option](demos/doom_gs/README.md#building).

The supplied [v1.5 image](https://github.com/Webifi/iigs-doom/releases/download/v1.5/doom-hd.hdv)
was downloaded and checked. Its SHA-256 is
`917212c62acf08d4ff27752e44a97543b8e142a1587e26dc0ee3f22e0053a9e5`,
so the builder correctly rejects it. Upstream v1.5 changes 82 source files
relative to the pinned revision. Adopting it requires updating and validating
the conversion, rather than changing only the URL or expected hash. None of
the currently listed v1.1 through v1.5 release-image hashes match the reference.

The original reference image is only a build input and stays in ignored
`build/`; it is not a download to publish here. A final converted game disk
can be published after the original build dependency is available again.
