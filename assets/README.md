# Parallax source art

These three 560x384 RGBA PNG layers were supplied by the repository owner for
the Appletini Invasion showcase:

| Layer | File | Speed |
| --- | --- | ---: |
| Deep space | `layer1_deep_space.png` | 0.25 px/frame |
| Nebula | `layer2_nebula.png` | 0.60 px/frame |
| Asteroids | `layer3_asteroids.png` | 1.40 px/frame |

The supplied source folder contained a generator, palette, browser demo, and
README, but no license statement, copyright notice, author attribution, or
embedded PNG license metadata. This provenance note does not invent or imply a
license.

`tools/convert_parallax.py` treats these PNGs as canonical source images. It
requires RGBA8, binary alpha, and exact membership in the documented 16-color
Apple II palette, then compiles every source pixel into the `build/PARALLAX`
runtime asset. Nothing is sampled or discarded. The first layer must be fully
opaque; the two foreground layers retain their exact binary-alpha masks.

## Runtime format

`PARALLAX` uses the exact-alpha `A13C` version-1 format. Its 16-byte header is
little-endian `<4sBBBBHHHH>` and currently contains magic, version, three
layers, 80 seven-dot groups per row, five banks, width 560, height 384,
directory offset 16, and bank-image offset 4096. The header is followed by
1,152 three-byte `<BH>` directory entries in layer-major, row-major order.
Each entry names a RamWorks bank from 1 through 5 and an absolute routine
address from `$2000` through `$9FFF`. Zero padding extends the directory prefix
to 4 KiB, followed by five complete 32 KiB bank images. A row routine never
crosses a bank boundary.

Rows are compiled as small 65C02 routines instead of interpreted records.
They compose an 80-byte common-main work row at `$A0-$EF`, stored as the
contiguous buffers AUX `$A0-$C7` and MAIN `$C8-$EF`. Source groups map there
in display order `AUX[0], MAIN[0], AUX[1], MAIN[1], ...`. Deep-space routines
initialize every group. Nebula and asteroid routines perform exact binary-alpha
replacement with grouped `STA`, `TRB`, and `TSB` operations or an
`AND`/`ORA` merge for mixed seven-dot masks. Every stored byte has bit 7 set to
select Video-7 color; the low seven bits preserve the global DHGR dot phase.
The converter structurally validates the container and emulates every
generated routine against direct alpha composition for all 128 possible input
values before writing the file.

The current canonical asset is 167,936 bytes: a 4 KiB directory prefix plus
five 32 KiB RamWorks images. Its SHA-256 is
`0d8cff3f0d32f981ecfd1327ea369a9cc83939d675ebf24248c6a88aac7915f2`.

At runtime `parallax_assets_load()` reads `/A13INVASION/PARALLAX` through
ProDOS/SmartPort into RamWorks banks 1-5. `parallax_render_slice(count)` takes
the deep, nebula, asteroid, and destination starting rows in fixed zero page
`$68/$69`, `$6A/$6B`, `$6C/$6D`, and `$6E/$6F`; normal slices use 106, 106,
and 104 woven rows. Zero page `$70-$7F` is renderer scratch and `$A0-$EF` is
the exact 80-byte composition buffer. Bank 0 remains the display bank, so
gameplay/replay storage begins at bank 6.

Source SHA-256 checksums:

```text
c8085f66d002ef0dd7b22af69d31e5afd22d6c8039e6098ab745e2f49cbc34a7  layer1_deep_space.png
1d1816124343049aef353eb822f1212ffca9577df7bf44dd86d30bcf2ef5d423  layer2_nebula.png
492df27c3fd2b6af5ca7ace4624bd46668cbc108b266e71415d68c18bf0d3c2c  layer3_asteroids.png
```
