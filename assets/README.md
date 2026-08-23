# Parallax and player-ship source art

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

The same supplied folder also provided `ship_f0.png` through `ship_f7.png` and
`ship.json`. Each frame is a 56x64 RGBA image with binary alpha and exact Apple
II palette colors. Frames 0-1 are neutral, 2-3 bank left, 4-5 bank right, and
6-7 are the burst/dissipate firing sequence.

`tools/convert_parallax.py` treats these PNGs as canonical source images. It
requires RGBA8, binary alpha, and exact membership in the documented 16-color
Apple II palette, then compiles every source pixel into the `build/PARALLAX`
runtime asset. Nothing is sampled or discarded. The first layer must be fully
opaque; the two foreground layers retain their exact binary-alpha masks.

## Runtime format

`PARALLAX` uses the exact-alpha `A13C` version-1 format. Its 16-byte header is
little-endian `<4sBBBBHHHH>` and currently contains magic, version, three
layers, 80 seven-dot groups per row, six banks, width 560, height 384,
directory offset 16, and bank-image offset 4096. The header is followed by
1,152 three-byte `<BH>` directory entries in layer-major, row-major order.
Each entry names a RamWorks bank from 1 through 5 and an absolute routine
address from `$2000` through `$9FFF`. Zero padding extends the directory prefix
to 4 KiB, followed by six complete 32 KiB bank images. A row routine never
crosses a bank boundary; row routines use banks 1-5 and the ship occupies bank
6.

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

`tools/convert_ship.py` compiles all eight ship frames at all four possible
seven-dot-group origins. Each 1 KiB variant contains 64 woven rows of eight
`(keep,data)` pairs. Runtime composition is exactly `(background & keep) |
data`; opaque black therefore clears background dots, transparency preserves
them, and bit 7 remains set for Video-7 color. The four phase variants let the
ship move in seven-dot increments without changing hue. The resulting 32 KiB
`build/SHIP` image has SHA-256
`587f6ad854729d4637a266e3dd89c8bbbfb52f320d4594adaa44b6015ddc7db4`.

The current canonical `PARALLAX` asset is 200,704 bytes: a 4 KiB directory
prefix plus six 32 KiB RamWorks images. Its SHA-256 is
`03b4ab494cf71c812bdeba540c898a38ca51c755944d02d2b4edc348ba30477a`.

At runtime `parallax_assets_load()` reads `/A13INVASION/PARALLAX` through
ProDOS/SmartPort into RamWorks banks 1-6. `parallax_render_slice(count)` takes
the deep, nebula, asteroid, and destination starting rows in fixed zero page
`$68/$69`, `$6A/$6B`, `$6C/$6D`, and `$6E/$6F`; normal slices use 106, 106,
and 104 woven rows. Zero page `$70-$7F` is renderer scratch and `$A0-$EF` is
the exact 80-byte composition buffer. `video_ship_fast()` reads the selected
frame and color phase from bank 6 and composites it into both DHGRi fields.
Bank 0 remains the display bank, so gameplay/replay storage begins at bank 7.

Source SHA-256 checksums:

```text
c8085f66d002ef0dd7b22af69d31e5afd22d6c8039e6098ab745e2f49cbc34a7  layer1_deep_space.png
1d1816124343049aef353eb822f1212ffca9577df7bf44dd86d30bcf2ef5d423  layer2_nebula.png
492df27c3fd2b6af5ca7ace4624bd46668cbc108b266e71415d68c18bf0d3c2c  layer3_asteroids.png
3ff7c5f6941c1fa9e84167e6740bf08e6c6d7cf662f7ff4d5e7af7bd457144b6  ship_f0.png
d70959cd0e13d1b6436a482681ee2cfaa2f79cfd5aa33dd7d9f96f61fd41dab3  ship_f1.png
7d7a6b34ae7b8e332f9b93e0778540685eddfee53a9969d8ae274972ca2ac36d  ship_f2.png
ecb305e1fe846f8abfeadb78fa6c1f5ea768db0c61e9ad9b3c2c5bf10069df66  ship_f3.png
d89c71cc2ba699411e30f62a03531e6d7705718a2da215076e74f91431915670  ship_f4.png
8876dc5531a3acd4c24a843080d64de0282ad61dfef4f2c9c59c912b1863d7ef  ship_f5.png
8928b904932410c593b4648d211790bcef9e56842f211cdc17643e8cf278edb9  ship_f6.png
a6d3fe6f283bc72c4cab84d61d7bd1ebde9f1f98b34ec6501ea4ec188a75b970  ship_f7.png
43fe77212c46927aac2ea38e1689bf1ae9fe837362a4cfe1624d3cb2beceaa7b  ship.json
```
