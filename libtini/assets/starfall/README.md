# STARFALL art

The aircraft, pickup and explosion sprites come from **Pixel Shmup 1.1**
by Kenney. The publisher dedicates the pack to the public domain under
**Creative Commons Zero 1.0 Universal (CC0)**. Kenney credit is appreciated
but is not required by the pack's license.

- Publisher and license declaration: <https://kenney.nl/assets/pixel-shmup>
- Publisher's alternative listing: <https://kenney-assets.itch.io/pixel-shmup>
- CC0 terms: <https://creativecommons.org/publicdomain/zero/1.0/>
- Exact original archive: [source/kenney_pixel-shmup.zip](source/kenney_pixel-shmup.zip)
- Original publisher license, copied without changes: [source/License.txt](source/License.txt)
- Download URL, retrieval date and SHA-256 hashes: [provenance.json](provenance.json)

The archive was downloaded directly from the publisher on 2026-10-20. Its
`License.txt` identifies version 1.1, created 2021-11-01. The publisher's web
page currently lists the original 1.0 release; the archive version controls
this vendored input. The complete original archive is retained so the PNGs,
original colors and license can always be inspected independently.

## Conversion

`tools/starfall_assets.py` reads the archive offline and verifies its SHA-256
before conversion. It uses Python's standard library, including a small PNG
reader for the pack's indexed PNGs. No normal build downloads assets or needs
Pillow, ImageMagick or another checkout.

All sixteen output cells are 16 by 16 pixels. The six 32 by 32 source
aircraft are reduced to 16 by 16 with pixel-center nearest-neighbor sampling
(source coordinates 1, 3, 5 and so on). The five enemy aircraft are rotated
180 degrees. Four original 16 by 16 pickup tiles (weapon "P", shield, repair
cross and rocket) and three explosion/debris tiles keep their pixels.

Transparent pixels become palette index zero. Opaque pixels are mapped by
minimum squared RGB distance to the twelve art colors, with ties resolved by
lower palette index. These retain Kenney's metal, cyan, orange, gold and lime
ramps at SHR's four bits per color channel. Three further palette entries
are available for stars, HUD and effects; archive art never uses them, so
the game animates indices 14 and 15. The generator packs the left pixel into
each byte's high nibble. It does not modify the original archive.

The fourteenth cell is an atlas of ten small sub-sprites drawn for
STARFALL: two enemy orbs, a needle, two player shots, two engine flames,
two hit sparks and a wingman. The wingman glows in animated index 14. They are written in `tools/starfall_assets.py` as rows of
palette indices and are part of this project's source, not the archive.
Each starts on a packed byte; the generator rejects misaligned, overlapping or out-of-cell entries.

Two further cells hold the optional parallax backdrop: distant traffic made
from five of the pack's grey aircraft. Each aircraft is cropped to its
opaque pixels and reduced to a square by pixel-center nearest-neighbor
sampling, then darkened: the outline becomes dark blue (13) and the body
the next darker grey. `ship_0012` becomes one 10-pixel aircraft in the MID
cell; `ship_0018` to `ship_0021` become four 6-pixel aircraft, one in each
8x8 quadrant of the FAR cell, which the game draws as four images with the
cell's 8-byte stride. Their members and hashes are in `provenance.json`.

The generated header contains sixteen cells (2,048 pixel bytes), a 32-byte
SHR palette and a 30-byte table of sub-sprite offsets and sizes. Stars and
interface graphics in the game are ordinary geometric primitives.

```powershell
python tools/starfall_assets.py --header build/starfall_assets.h --preview build/starfall-art.ppm
```

The optional preview is an enlarged portable PPM contact sheet: player,
scout, weaver, dart, heavy, gunship and weapon pickup; shield, repair, bomb,
three explosion frames, the atlas and the two backdrop cells.
Generated headers and previews belong in the ignored build directory.
