# Appletini Demos

[Appletini_Demos.po](Appletini_Demos.po) is the bootable 32 MB
ProDOS showcase disk, moved with its sources from `appletini-one/software`. Mount it on an
Appletini SmartPort drive and boot it to enter the HGR launcher.

The menu includes New Image Modes, Speed Race, raster bars, Mandelbrot,
wave animation, SuperSprite, the network browser/server/image viewer,
the AD8088 MS-DOS HGR cube, and Linear Text Overlay. Enable the relevant
virtual cards in Appletini's configuration. The launcher probes for
Appletini; a generic Apple II emulator does not supply all these features.

The menu no longer animates the HDMI border. That animation repeatedly
accessed `$C034`, which also toggles the Apple //e speaker, causing a whine
at high acceleration. The launcher now avoids the entire `$C030-$C03F`
speaker range. A regression executes its startup, idle loop, and keyboard
paths while checking I/O accesses. Dedicated raster demos keep their border
effects.

## Build and verify

Run from the appletini-software repository root on Windows:

```powershell
python demos/appletini_demos/tools/build_appletini_demo_disk.py
python demos/appletini_demos/tools/test_demo_disk.py
python demos/appletini_demos/tools/test_demo_disk.py --disk demos/appletini_demos/build/Appletini_Demos.po
python demos/appletini_demos/tools/test_appletini_webserver.py
```

The builder requires Python 3.10+, Java, AppleCommander, ACME, and cc65's
`cl65` on PATH. Set `APPLECOMMANDER` to the AppleCommander jar, `ACME_EXE`
to ACME, and `ACME` to its library directory when using other tool locations.
The bundled network library and its licenses are in
[appletini_webserver/ip65](appletini_webserver/ip65); see the
[network app README](appletini_webserver/README.md) for runtime details.
Install `py65` for the tests that execute assembled viewer code.

The fresh image is written to `build/Appletini_Demos.po`; the tracked disk
beside this README includes the silent-menu fix. Generated assembly, binaries, and
logs also stay in `build/`. Network build output stays in
`appletini_webserver/build/`. From this directory, the equivalent Make
targets are `disk`, `verify`, and `verify-build`.

The disk build needs no firmware checkout. Tests use a pinned SmartPort ROM
fixture to check the launcher's detection bytes. Set `APPLETINI_ROOT` to an
appletini-one checkout to also check them against its current ROM.
These checks validate sources, assembly behavior, and disk contents; they
do not exercise physical Appletini hardware.

To rebuild the separate SuperSprite DOS 3.3 disk:

```powershell
python demos/appletini_demos/tools/build_supersprite_demo.py
```

This writes `build/SSDEMO.dsk`. The showcase builder uses the preserved
`assets/SSDEMO.dsk` input; compare a rebuilt version before replacing that
input. Override `DOS33_MASTER` to use another DOS 3.3 master.

## Migration and inputs

Imported from `hasseily/appletini-one` commit
`391f73f271cb17746775239e68bbd15610b67101`. The imported disk was
33,554,432 bytes with SHA-256:

```text
9d40c441dd26d9a39e20d208705b6e82a6aba2a6a25f15b02871da46ddf3dada
```

[migration.json](migration.json) records original checkout paths, sizes, hashes, and
whether each input moved or was copied. The hashes describe the source
checkout before build-path changes and the menu fix. Assembly/BASIC sources, the network
apps, builders, and their software tests now live here. Build-path changes
do not change the demo programs. Rebuilding also picks up the existing
text-overlay keyboard fix in the imported sources, which was newer than
the imported disk. `launcher_assets.a65` is regenerated from
`tools/gen_hgr_assets.py` instead of being tracked.

The base MS-DOS image, DOS 3.3 master, SuperSprite input disk, and image
corpora were copied so appletini-one's remaining diagnostics and renderer
fixtures keep their existing inputs. Their source hashes are recorded in
the manifest. The SmartPort ROM is a test fixture copied from firmware;
firmware remains the authority for that ROM. The authored viewer, border,
and overlay sources moved here; their remaining firmware-side checks use
`APPLETINI_SOFTWARE_ROOT` (default: a sibling appletini-software checkout).

The MS-DOS base preserves Reboot Camp '83's bridge, DOS files, HGR cube,
and source disk. The builder patches only the demo return path and startup
batch file. Existing third-party media and IP65 retain their provenance
and license terms.
