A2MONO archive.org TLS fix TEST build

Boot A2MONO-ARCHIVE-FIX.po on an Appletini SmartPort drive. This disk is
byte-identical to A2MONO.po. For an existing ProDOS volume, import the
AppleSingle A2MONO.SYSTEM and copy all five matching MONO.* overlays:
MONO.WEB, MONO.NET, MONO.GIF, MONO.PNG and MONO.JPG.

Use the matching a2mono-archive TEST firmware, supplied separately:
FIRMWARE.BIN SHA-256: b59c5f2fe8eb77d987a7bdc84c3bd6d94fe27bd5c748a467109c06e24c0b6a6f
Firmware is not included in this browser ZIP. Keep all browser files from
this build together.

This release adds Go Daddy Root Certificate Authority - G2 to the 29-root
CA bundle. An existing ATNETCA.PEM in the FAT SD-card root OVERRIDES the
firmware's embedded roots. Replace it with HTTPS/ATNETCA.PEM from this ZIP,
or remove the old override and use the updated firmware's embedded roots.
Then reboot. Keep private seed files. A PEM copied inside the ProDOS disk
image does not update the ARM service trust store.

Page connection failures now display a TLS or DNS error instead of
Download failed: -9984. Actual file errors retain numeric results. HTTPS
certificate verification rules remain enabled. Existing SD-download,
anchor, mobile, mouse and image behavior remains available.

Target: 33 MHz or faster, monochrome DHGRi, banked auxiliary RAM. Images
start off; I loads them. Read README_MONO.md for setup, controls and limits.

Verification is emulated/native testing, not physical-board validation.
verification/evidence-scope.json identifies exact-final versus unchanged
component baseline evidence without relabeling previous binary hashes.
