#!/usr/bin/env python3
"""A small reader for Doom WAD files (IWAD/PWAD), shared by the tools.

Only what the port needs: the lump directory, lookup by name with Doom's
rules (the last lump of a name wins, as `W_GetNumForName`), the lumps
between marker pairs (`S_START`/`S_END`, `F_START`/`F_END`, also the
`SS_`/`FF_` spellings), the map lumps, `TEXTURE1/2` with `PNAMES`, and
the decoding of patches (Doom's column/post picture format) into a
full-resolution pixel array where `None` is a transparent pixel.

Everything here is read-only and pure Python so that the converter, the
reference renderer and the tests can use it without extra packages.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

MAP_LUMPS = ("THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS",
             "SSECTORS", "NODES", "SECTORS", "REJECT", "BLOCKMAP")


def lump_name(raw: bytes) -> str:
    """An 8-byte name field as an upper-case string (NUL padded)."""
    return raw.split(b"\0", 1)[0].decode("ascii", "replace").upper()


@dataclass
class Lump:
    index: int
    name: str
    offset: int
    size: int


@dataclass
class TextureDef:
    """One TEXTURE1/2 entry: size in map units and its patches."""
    name: str
    width: int
    height: int
    masked: int
    patches: list = field(default_factory=list)   # (originx, originy, patch name)
    order: int = 0                                  # position across TEXTURE1+2


class Wad:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        ident, count, diroff = struct.unpack_from("<4sii", self.data, 0)
        if ident not in (b"IWAD", b"PWAD"):
            raise ValueError(f"{path}: not a WAD file")
        self.ident = ident.decode()
        self.lumps: list[Lump] = []
        for i in range(count):
            off, size, name = struct.unpack_from("<ii8s", self.data, diroff + 16 * i)
            self.lumps.append(Lump(i, lump_name(name), off, size))
        self.by_name: dict[str, int] = {}
        for lump in self.lumps:
            self.by_name[lump.name] = lump.index      # last one wins

    # --- lookup -------------------------------------------------------------
    def has(self, name: str) -> bool:
        return name.upper() in self.by_name

    def num(self, name: str) -> int:
        return self.by_name[name.upper()]

    def read(self, which) -> bytes:
        lump = self.lumps[which] if isinstance(which, int) else self.lumps[self.num(which)]
        return self.data[lump.offset:lump.offset + lump.size]

    def between(self, start_names, end_names) -> list[Lump]:
        """Lumps between the first start marker and the last end marker."""
        start = next((i for i, l in enumerate(self.lumps) if l.name in start_names), None)
        end = None
        for i, l in enumerate(self.lumps):
            if l.name in end_names:
                end = i
        if start is None or end is None:
            return []
        return [l for l in self.lumps[start + 1:end]
                if l.size > 0 and not l.name.endswith(("_START", "_END"))]

    def sprite_lumps(self) -> list[Lump]:
        return self.between(("S_START", "SS_START"), ("S_END", "SS_END"))

    def flat_lumps(self) -> list[Lump]:
        return self.between(("F_START", "FF_START"), ("F_END", "FF_END"))

    # --- maps ---------------------------------------------------------------
    def map_names(self) -> list[str]:
        names = []
        for i, lump in enumerate(self.lumps[:-1]):
            if self.lumps[i + 1].name == "THINGS" and lump.size == 0:
                names.append(lump.name)
        return names

    def map_lumps(self, mapname: str) -> dict[str, bytes]:
        """The ten map lumps that follow the marker (first marker of that name)."""
        start = next(i for i, l in enumerate(self.lumps) if l.name == mapname.upper())
        out = {}
        for lump in self.lumps[start + 1:start + 1 + len(MAP_LUMPS)]:
            if lump.name in MAP_LUMPS:
                out[lump.name] = self.data[lump.offset:lump.offset + lump.size]
        return out

    # --- textures -----------------------------------------------------------
    def pnames(self) -> list[str]:
        raw = self.read("PNAMES")
        count = struct.unpack_from("<i", raw, 0)[0]
        return [lump_name(raw[4 + 8 * i:12 + 8 * i]) for i in range(count)]

    def texture_defs(self) -> list[TextureDef]:
        """TEXTURE1 then TEXTURE2 in order (Doom's texture numbering)."""
        names = self.pnames()
        out: list[TextureDef] = []
        for tl in ("TEXTURE1", "TEXTURE2"):
            if not self.has(tl):
                continue
            raw = self.read(tl)
            count = struct.unpack_from("<i", raw, 0)[0]
            for k in range(count):
                o = struct.unpack_from("<i", raw, 4 + 4 * k)[0]
                name = lump_name(raw[o:o + 8])
                masked, width, height = struct.unpack_from("<ihh", raw, o + 8)
                npatch = struct.unpack_from("<h", raw, o + 20)[0]
                tex = TextureDef(name, width, height, masked, order=len(out))
                for p in range(npatch):
                    ox, oy, pidx = struct.unpack_from("<hhh", raw, o + 22 + 10 * p)
                    tex.patches.append((ox, oy, names[pidx]))
                out.append(tex)
        return out


# --- pictures ------------------------------------------------------------------

@dataclass
class Picture:
    """A decoded patch: columns[x][y] is a palette index or None (transparent)."""
    width: int
    height: int
    left: int
    top: int
    columns: list


def decode_patch(raw: bytes) -> Picture:
    """Doom's patch_t -> Picture (posts drawn in order, clipped to the height)."""
    width, height, left, top = struct.unpack_from("<hhhh", raw, 0)
    cols = []
    for x in range(width):
        col = [None] * height
        p = struct.unpack_from("<I", raw, 8 + 4 * x)[0]
        while p < len(raw) and raw[p] != 0xFF:
            topdelta, length = raw[p], raw[p + 1]
            pix = raw[p + 3:p + 3 + length]
            for i, v in enumerate(pix):
                y = topdelta + i
                if 0 <= y < height:
                    col[y] = v
            p += length + 4
        cols.append(col)
    return Picture(width, height, left, top, cols)


def draw_patch_into(canvas: list, width: int, height: int, raw: bytes, ox: int, oy: int):
    """Composite a patch's posts into a column-major canvas at (ox, oy), as
    Doom's R_GenerateComposite: later patches overwrite, rows outside the
    texture are clipped, transparent pixels leave the canvas alone."""
    pw = struct.unpack_from("<h", raw, 0)[0]
    for x in range(pw):
        tx = ox + x
        if tx < 0 or tx >= width:
            continue
        col = canvas[tx]
        p = struct.unpack_from("<I", raw, 8 + 4 * x)[0]
        while p < len(raw) and raw[p] != 0xFF:
            topdelta, length = raw[p], raw[p + 1]
            y0 = oy + topdelta
            for i in range(length):
                y = y0 + i
                if 0 <= y < height:
                    col[y] = raw[p + 3 + i]
            p += length + 4
