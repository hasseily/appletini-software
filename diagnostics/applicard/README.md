# Appli-Card software and diagnostics

PCPI CP/M boot media, compatibility disks, and Z80 validation programs for
the Appletini Appli-Card. Enable the virtual Appli-Card in slot 5 and boot
`DEMOBOOT.DO` through Disk II in slot 6. `DEMOGAME.DO` is its companion
game-data disk. The firmware controls and slot protocol are documented in
[appletini-one](../../../appletini-one/README_APPLICARD.md).

`pcpiboot.do` and `pcpiutil.do` retain the source boot/utility media.
`extras/` contains the PCPI ProDOS, StarCard, graphics, driver, and file
utility distributions. Consult the included
[PCPI ProDOS instructions](extras/PCPI_ProDOS.txt) before using those disks.
The `.po` files in `extras/` are ProDOS images; the CP/M image tool below
handles the 140 KB DOS-order `.do` files.

`BANKTEST.COM` tests Appletini's 32 distinct 64 KB Z80 RAM banks and the
common upper-memory mapping. Run `BANKTEST` from CP/M. It restores the
normal bank register before returning through a CP/M warm boot. A real
GZ80 with eight banks reports failure at bank 8 because this diagnostic
expects Appletini's 2 MB extension. `ZEXALL.COM` is the bundled Z80 CPU
instruction-validation program.

## Build and disk tools

Only Python 3 is required. From the appletini-software repository root:

```sh
python diagnostics/applicard/tools/build_applicard_banktest.py
python diagnostics/applicard/tools/pcpi_disk.py ls diagnostics/applicard/DEMOBOOT.DO
python diagnostics/applicard/tools/pcpi_disk.py info diagnostics/applicard/pcpiboot.do
```

The builder writes `build/BANKTEST.COM` and `build/BANKTEST.lst`. The root
`BANKTEST.COM` and `BANKTEST.lst` retain the original program and assembly
listing for comparison. No external assembler or firmware checkout is
needed to rebuild the program.

To create a separate CP/M data disk containing the rebuilt test:

```sh
python diagnostics/applicard/tools/pcpi_disk.py blank diagnostics/applicard/build/BANKTEST.DO
python diagnostics/applicard/tools/pcpi_disk.py add diagnostics/applicard/build/BANKTEST.DO diagnostics/applicard/build/BANKTEST.COM
python diagnostics/applicard/tools/pcpi_disk.py ls diagnostics/applicard/build/BANKTEST.DO
```

Boot CP/M from its boot disk, mount the new data disk as drive B, and run
`B:BANKTEST`. The `blank`, `add`, and `rm` commands write their named disk;
use working copies when changing the bundled media. `ls`, `info`, and
`verify` read their input disk. `extract` writes a named output file.
Run the tool without arguments for the full command list.

## Provenance

All bundled media and the original BANKTEST program/listing were moved
unchanged from `appletini-one`. `migration.json` records each source path,
source commit, byte count, and SHA-256 before relocation. Only the tool
paths and documentation were adapted for this project.

Third-party copyright and redistribution notices remain with the media.
In particular, `extras/PCPI_ProDOS.txt` retains Steven N. Hirsch's notice
covering that distribution. Retain it when redistributing those files.
The Appli-Card firmware ROM and its generator remain in appletini-one.

Matching build bytes and readable disk catalogs do not establish CP/M
runtime or physical-card compatibility; those require separate execution.
