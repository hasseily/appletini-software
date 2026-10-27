# Emulator boot ROMs

The repository and libtini release archives include these boot inputs:

- `Apple2e_Enhanced.rom`: 16 KiB enhanced Apple //e system ROM.
- `smartport_a2retronet_style_c700.mem`: 256 bytes of slot-7 firmware in hex text.
- `smartport_a2retronet_style_c800.mem`: 2048 bytes of SmartPort firmware in hex text.

`tools/web.py`, `tools/benchmark.py` and `tests/web_validate.py` use this
directory by default, independent of the working directory. Use
`--boot-roms DIR` for another directory inside libtini. Use `--direct-launch`
for the ProDOS MLI stand-in. The stand-in does not support audio interrupt
allocation, so STARFALL needs the default ROM boot.

`provenance.json` records the source and SHA-256 hash of each bundled ROM.
These files retain their original ownership and notices; the libtini MIT
license does not relicense Apple firmware. See `NOTICES.txt`.

Native text previews also need a separately installed 4096-byte
`apple2e-video.bin`. That optional file is not included in the repository or
release archives. Browser SHR output does not need it.
