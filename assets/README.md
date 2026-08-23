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
Apple II palette, then converts them into the compact `build/PARALLAX` runtime
asset.

## Runtime format

`PARALLAX` begins with a 16-byte `A13S` version-1 header containing the layer
count, 80-byte row width, 384-row height, and three little-endian chunk
offsets. Each layer chunk stores its speed numerator and denominator (5, 12,
or 28 over 20), followed by 384 little-endian, chunk-relative row offsets.

Each row contains a count followed by `(x,data)` pairs for sparse XOR drawing.
Pixel data is stored as 80 seven-dot groups in display order
`AUX[0], MAIN[0], AUX[1], MAIN[1], ...`; bit 0 is leftmost and bit 7 remains
clear for the runtime's Video-7 selector. The converter applies a fixed,
documented ranking to select source-derived groups at build time so the
complete embedded asset remains below 12KB without forming periodic bands.

For byte group `x`, source row `y`, and zero-based layer `l`, the converter
avalanches `(y*80+x) XOR ((l+1)*0x9E3779B9)` through two fixed 32-bit multiply
and XOR-shift stages. Each row ranks its nonzero groups by that value and keeps
`ceil(n/8)`, `ceil(n/5)`, or `ceil(n/4)` for deep space, nebula, or asteroids.
Deep space additionally keeps every group containing white. Fixed per-row
quotas prevent source-bearing rows from becoming accidentally blank; the
decorrelated ranking prevents the diagonal lattice produced by an affine
modulus. Zero data bytes are omitted because the runtime operation is XOR.

Source SHA-256 checksums:

```text
c8085f66d002ef0dd7b22af69d31e5afd22d6c8039e6098ab745e2f49cbc34a7  layer1_deep_space.png
1d1816124343049aef353eb822f1212ffca9577df7bf44dd86d30bcf2ef5d423  layer2_nebula.png
492df27c3fd2b6af5ca7ace4624bd46668cbc108b266e71415d68c18bf0d3c2c  layer3_asteroids.png
```
