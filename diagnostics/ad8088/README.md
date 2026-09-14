# AD8088 test disks

Visible Apple II diagnostics for the virtual ALF AD8088 Plus and its
AD128K-compatible memory range.

- [AD8088_Test.dsk](AD8088_Test.dsk): 140 KB DOS 3.3 image.
- [AD8088_Test.po](AD8088_Test.po): 800 KB ProDOS image.

Both disks boot into `AD8088.TEST` at `$6000`. It checks the slot-5 mailbox,
the monitor's integer command, memory fill/copy, and execution of a short
8088 program. The last stage writes `8088 EXECUTED THIS LINE` into the Apple
text page through the shared-memory window.

Select the virtual ALF AD8088 Plus for slot 5 in the Appletini configuration.
Virtual TransWarp and AD8088 cannot run together because both own the Apple
bus. See the firmware repository's
[AD8088 documentation](../../../appletini-one/README_AD8088.md) for the
configuration and supported monitor commands.

## Build

Use Python 3, ACME, Java, and AppleCommander. From this directory:

```sh
python tools/build_ad8088_test_disks.py
```

`make disk` runs the same command. It writes the binary and both disk images
to `build/`; the tracked disks stay unchanged.

The builder uses the repository's shared
[DOS 3.3 master](../../demos/appletini_demos/assets/DOS%203.3%20System%20Master.dsk)
and [ProDOS 2.4.3 master](../../demos/fatdog_magic/assets/ProDOS_2_4_3.po).
Set `ACME_EXE`, `APPLECOMMANDER` (JAR path), `DOS33_MASTER`, or
`PRODOS_MASTER` to use other tool or master locations. Java must be on
`PATH`; the builder also finds ACME on `PATH`.

## Provenance and validation

[migration.json](migration.json) records the original paths, source commit,
sizes, and SHA-256 hashes before migration edits. The tracked disk images
were copied byte-for-byte. Migration validation rebuilt both disks and checked
their boot blocks, catalogs, and embedded programs. Both the tracked and
rebuilt disks contain the same freshly assembled AD8088.TEST bytes.
The firmware repository retains its AD8088 protocol and instruction-core
regressions. These checks do not replace execution on an Apple II with the
virtual card enabled.
