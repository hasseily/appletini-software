# STARFALL bosses

The five bosses of STARFALL are original art by Henri Asseily, in the style
of Kenney's Pixel Shmup. They are not part of a Kenney pack. They have the
MIT License of libtini.

- The description of the art, as it came: [PACK.md](PACK.md)
- Geometry, frame sizes, offsets and hit boxes: [bosses.json](bosses.json)
  and the JSON file of each boss
- The 16-entry palette: `palette.hex`, `palette.gpl` and `palette.png`
- SHA-256 hashes of every file: [provenance.json](provenance.json)

Each boss is at most 100x77 pixels and faces down. It has a hull and three
weapon emplacements. Each strip has four frames, left to right. Each
emplacement has an intact strip and a destroyed strip of the same size.

`.gitattributes` keeps the exact bytes of these files, which the hashes
cover.

## Conversion

`tools/starfall_bosses.py` checks each file against `provenance.json` and
writes `build/starfall_bosses.h` and one art file for each boss,
`build/starfall_boss1.bin` to `build/starfall_boss5.bin`. The build runs it
before it compiles STARFALL.

```powershell
python tools/starfall_bosses.py --header build/starfall_bosses.h --art build --preview build/bosses.ppm
```

Twelve colors of the palette are in STARFALL's palette. Each boss gets two
more colors in palette slots 13 and 14 during its sector: the two other
colors that it uses most, the darker one in slot 13. Its third other color
becomes the nearest of the twelve.

The tool cuts frame 0 of the hull into strips of eight lines from the top of
the boss. Each strip keeps only the whole bytes from its first to its last
opaque pixel. The hull does not animate in the game. The weapons keep all
four intact and four destroyed frames. A weapon at an odd x gets one
transparent column on the left, because every image starts on a packed byte.

An art file starts with the bytes of all strips and of one frame of each
weapon. Then come the boss's record (161 bytes, as cc65 lays out
`sf_boss_art`), the strips and the weapon frames. The header holds the same
records for the host build of the simulation. The optional preview is a PPM
of each boss, drawn as the game draws it.
