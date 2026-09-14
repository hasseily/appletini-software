# AUXSTRESS and BANKMAP

Apple II auxiliary-memory and RamWorks diagnostics, moved from Appletini One.

- [AUXSTRESS.dsk](AUXSTRESS.dsk) is a 140 KB DOS 3.3 disk that boots directly
  into AUXSTRESS. Run `BRUN BANKMAP` from DOS to use the bank-decode probe.
- [AUXTOOLS.po](AUXTOOLS.po) is a 140 KB ProDOS disk. Use the Bitsy Bye menu
  to select AUXSTRESS or BANKMAP.

Both programs load at `$6000`. AUXSTRESS runs nine checks covering auxiliary
zero page and stack, RAMRD/RAMWRT, 80STORE, the auxiliary language card,
combined switches, rapid switching, retention, SmartPort interleave, and
128 RamWorks banks. It counts errors across repeated passes; any key exits.
The SmartPort check skips when no driver entry is available, and the RamWorks
walk skips when its bank probe finds no distinct banks.

BANKMAP walks 128 banks through zero page, the `$2000` window, text memory,
and the language card. It reports the number of distinct banks and the first
failure for each path.

## Build

Use Python 3, ACME, Java, and AppleCommander. From this directory:

```sh
python tools/build_auxstress_disk.py
```

`make disk` runs the same command. It writes binaries and both disk images to
`build/`; the tracked disks stay unchanged.

The builder uses the repository's shared
[DOS 3.3 master](../../demos/appletini_demos/assets/DOS%203.3%20System%20Master.dsk)
and [ProDOS 2.4.3 master](../../demos/fatdog_magic/assets/ProDOS_2_4_3.po).
Set `ACME_EXE`, `ACME` (ACME library directory), `APPLECOMMANDER` (JAR path),
`DOS33_MASTER`, or `PRODOS_MASTER` to use other tool or master locations.
Java must be on `PATH`; the builder also finds ACME on `PATH`.

## Provenance and validation

[migration.json](migration.json) records the original paths, source commit,
sizes, and SHA-256 hashes before migration edits. The tracked disk images
were copied byte-for-byte. Migration validation rebuilt both disks and checked
their boot blocks, catalogs, and embedded programs. Both the tracked and
rebuilt disks contain the same freshly assembled AUXSTRESS and BANKMAP bytes.
These checks do not validate physical auxiliary-memory or RamWorks timing.
