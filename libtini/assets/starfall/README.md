# STARFALL art

The bosses are original art in [bosses](bosses/README.md), under the MIT
License of libtini. The rest of the art comes from Kenney.

The aircraft, pickup and explosion sprites come from **Pixel Shmup 1.1** by
Kenney. The publisher puts the pack in the public domain under **Creative
Commons Zero 1.0 Universal (CC0)**. The license of the pack does not require
credit to Kenney, but Kenney asks for it.

- Publisher and license declaration: <https://kenney.nl/assets/pixel-shmup>
- Alternative listing of the publisher: <https://kenney-assets.itch.io/pixel-shmup>
- CC0 terms: <https://creativecommons.org/publicdomain/zero/1.0/>
- Exact original archive: [source/kenney_pixel-shmup.zip](source/kenney_pixel-shmup.zip)
- Original publisher license, copied without changes: [source/License.txt](source/License.txt)
- Download URL, retrieval date and SHA-256 hashes: [provenance.json](provenance.json)

The archive came directly from the publisher on 2026-10-20. Its
`License.txt` gives version 1.1, created 2021-11-01. The web page of the
publisher lists the 1.0 release; the version of the archive applies to this
vendored input. The repository keeps the full original archive. Thus you can
examine the PNGs, the original colors and the license independently.

## Conversion

`tools/starfall_assets.py` reads the archive offline and checks its SHA-256
before the conversion. It uses the Python standard library, with a small PNG
reader for the indexed PNGs of the pack. Builds do not download assets, and
they do not need Pillow, ImageMagick or another checkout.

All sixteen output cells are 16 by 16 pixels. The tool reduces the six 32 by
32 source aircraft to 16 by 16 with pixel-center nearest-neighbor sampling
(source coordinates 1, 3, 5 and the subsequent odd values). It turns the five
enemy aircraft by 180 degrees. Four original 16 by 16 pickup tiles (weapon
"P", shield, repair cross and rocket) and three explosion and debris tiles
keep their pixels.

Transparent pixels become palette index zero. The tool maps each opaque pixel
to the nearest of the twelve art colors, by minimum squared RGB distance. When
two colors have the same distance, the lower palette index wins. These colors
keep the metal, cyan, orange, gold and lime ramps of Kenney at the four bits
for each color channel of SHR.

Three more palette entries are for stars, the HUD and effects. The archive
art does not use them, thus the game animates indices 14 and 15. The tool
puts the left pixel into the high nibble of each byte. It does not change the
original archive.

The fourteenth cell is an atlas of ten small sub-sprites for STARFALL: two
enemy orbs, a needle, two player shots, two engine flames, two hit sparks and
a wingman. The wingman glows in the animated index 14. These sub-sprites are
rows of palette indices in `tools/starfall_assets.py`. They are part of the
source of this project, not of the archive. Each sub-sprite starts on a packed
byte. The tool rejects an entry that is not aligned, that overlaps another
entry or that is outside the cell.

Two more cells hold the optional parallax backdrop: distant aircraft from
five grey aircraft of the pack. The tool crops each aircraft to its opaque
pixels and reduces it to a square with pixel-center nearest-neighbor
sampling. Then it makes the aircraft darker: the outline becomes dark blue
(13) and the body becomes the next darker grey.

`ship_0012` becomes one 10-pixel aircraft in the MID cell. `ship_0018` to
`ship_0021` become four 6-pixel aircraft, one in each 8x8 quadrant of the FAR
cell. The game draws them as four images with the 8-byte stride of the cell.
`provenance.json` gives their archive members and hashes.

The generated header contains sixteen cells (2,048 pixel bytes), a 32-byte
SHR palette and a 30-byte table of sub-sprite offsets and sizes. The stars
and the interface graphics of the game are geometric primitives.

```powershell
python tools/starfall_assets.py --header build/starfall_assets.h --preview build/starfall-art.ppm
```

The optional preview is a large portable PPM contact sheet. It shows the
player, scout, weaver, dart, heavy, gunship and weapon pickup, then the
shield, repair, bomb, three explosion frames, the atlas and the two backdrop
cells. Put generated headers and previews in the ignored build folder.
