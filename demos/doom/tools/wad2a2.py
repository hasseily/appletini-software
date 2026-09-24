#!/usr/bin/env python3
"""Convert freedoom1.wad into the Appletini port's RamWorks data (DESIGN.md 6).

    python3 tools/wad2a2.py --wad WAD --out build/data [--maps E1M1,E1M2,...]
                            [--first-bank 2] [--no-preview]
    python3 tools/wad2a2.py --layouts-md        (print the record tables)

Everything the port reads at run time is produced here, already placed in
RamWorks banks, so the kernel's loader only streams bytes to bank:address
and the renderer, the game and the reference renderer agree on one layout.

Output (build/data/):

  DIR.1            the directory bank (palettes, directories, map table)
  GFX.1 .. GFX.n   the graphics banks (textures, flats, sprites, UI pictures)
  E1M1.1 ..        each map's level-data banks
  manifest.json    files, banks, directory addresses, per-map array
                   descriptors, names, statistics
  doomdata.inc     ca65 constants (addresses, counts, record layouts)
  doomdata.h       the same for C (cc65), with structs of the records
  preview/         PNGs of a sample of textures, flats, sprites, UI
                   pictures decoded back from the bank images, and a
                   contact sheet

Banks. Bank 1 is the GAME space; the converter uses banks FIRST (2) and up,
contiguously: the directory bank, then the graphics banks, then each map's
banks (DD_MAP_FIRST_BANK on). With --shared-map-banks every map starts at
DD_MAP_FIRST_BANK (the kernel then loads one map's files per level; the
data of E1 fits 4 MB that way, not otherwise). Nothing else may use these
banks; other parts allocate banks after DD_LAST_BANK. Usable memory of a
bank is $0200-$BFFF (48,640 bytes).

  - Graphics bank: the 16 colormaps (Doom's COLORMAP 0, 2, .. 30) at
    $0200-$11FF (map k at $0200 + 256*k), objects from $1200 up to $BFFF,
    first-fit decreasing by size; no object crosses a bank.
  - Level bank: objects from $0200. An array larger than a bank is split
    in chunks of 2^k elements, chunk c in bank FIRST+c of consecutive
    banks, all at the same BASE address; element i is at bank
    FIRST + (i >> k), address BASE + (i & (2^k - 1)) * size (see
    pack_level for how k and BASE are chosen). An array that fits a bank
    is one chunk with 2^k >= its count, so the same formula holds.

Pixels. Graphics are Doom palette indices at half resolution. Halving
takes each 2x2 block (1x2 for UI pictures, which keep the SHR's 320
columns): if more than half of its texels are transparent the result is
transparent, otherwise the palette index whose RGB is nearest (squared
distance, lowest index on ties) to the average of the opaque texels; a
block whose opaque texels are all one index keeps it. Index 247 is never
produced as a colour (PLAYPAL 247 is black like index 0, which replaces
it), so 247 always means "transparent" in textures and UI pictures.

  - Texture: composited from its patches as R_GenerateComposite (later
    patches overwrite, clipped to the texture), halved, then padded to
    power-of-two width and height by wrapping (stored column x is halved
    column x mod w, row y is row y mod h), stored column major: texel
    (u, v) at ADDR + ((u & wmask) << log2h) + (v & hmask). A texture with
    a transparent texel after halving is flagged MASKED (247 = hole).
  - Flat: 32x32 row major, texel (x, y) at ADDR + 32*y + x (1,024 bytes).
  - Sprite patch (column/post format), at ADDR:
        +0 width u8, +1 height u8, +2 leftoffset s16, +4 topoffset s16,
        +6 colofs[width] u16 (offset of each column's posts from ADDR),
        posts: top u8, length u8, pixels[length]; top $FF ends a column.
    Offsets are halved (floor), in half-resolution texels.
  - UI picture (status bar, faces, digits, font, menus, title,
    intermission): row major width x height bytes, rows halved only,
    247 = transparent; offsets: left as is, top halved.

Directory bank (at the addresses of doomdata.inc, in this order from
$0200): PLAYPAL (14 palettes x 512 bytes, PAL256 RGB444: entry i byte 2i =
G<<4|B, byte 2i+1 = $20|R, each channel round(v*15/255)), INVULMAP (Doom's
COLORMAP 32, 256 bytes), MAPDIR (one MAP record per slot, slot =
9*(episode-1) + map-1; a zero name means "not converted"), TEXDIR,
FLATDIR, SPRDEF, SPRFRAME, SPRLUMP, UIDIR, ANIMS, SWITCHES, ENDOOM (4,000
bytes). Record layouts: RECORDS below (also `--layouts-md`, doomdata.inc,
doomdata.h, DESIGN.md section 6).

Data files. Each file is at most 128 KB: a 256-byte header (+0 magic
"A2DM", +4 version 1, +5 segment count n (<= 49), +6 two zero bytes, then
n entries of bank u8, address u16, length u16 from +8; zero padding to
256), then the segments' bytes in entry order. The loader copies each
segment to bank:address. A bank's used range is always one contiguous
run from $0200; a run may be split across two files.

Maps that break a limit (LIMITS) or have a broken reference are listed in
manifest.json under "skipped" with the reason, and left out.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wadlib  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]

# --- memory ----------------------------------------------------------------------
BANK_LO = 0x0200
BANK_HI = 0xC000
BANK_CAP = BANK_HI - BANK_LO            # 48,640 bytes
COLORMAP_ADDR = 0x0200
NUM_COLORMAPS = 16                      # COLORMAP 0, 2, .. 30
GFX_DATA = COLORMAP_ADDR + 256 * NUM_COLORMAPS   # $1200
GFX_CAP = BANK_HI - GFX_DATA            # 44,544 bytes
GAME_BANK = 1
FIRST_BANK = 2
TRANSPARENT = 247
FILE_MAX = 128 * 1024
FILE_HEADER = 256
FILE_MAGIC = b"A2DM"
FILE_VERSION = 1
FILE_MAX_SEGS = (FILE_HEADER - 8) // 5  # 49
NONE16 = 0xFFFF
SPR_NOLUMP = 0x3FFF                     # SPRFRAME: missing rotation
ANIM_TICS = 8                           # Doom's animation speed
MAX_TEX_HALF_W = 256                    # wmask must fit a byte
MAX_TEX_HALF_H = 128

# Per-map limits checked before a map is kept (16-bit indices with $FFFF =
# none; node children use bit 15 for "subsector"; one blockmap object must
# fit a bank). The renderer's part may tighten these (DESIGN.md 7).
LIMITS = {
    "vertexes": 0xFFFE, "linedefs": 0xFFFE, "sidedefs": 0xFFFE,
    "sectors": 0xFFFE, "segs": 0xFFFE, "subsectors": 0x7FFF,
    "nodes": 0x7FFF, "things": 0xFFFE, "seclines": 0xFFFE,
    "blockmap_bytes": BANK_CAP,
}


# --- record layouts -----------------------------------------------------------------

TYPES = {"u8": ("B", 1, "unsigned char"), "s8": ("b", 1, "signed char"),
         "u16": ("H", 2, "unsigned int"), "s16": ("h", 2, "int")}


def type_info(typ):
    """(struct code, size, C type); "cN" is N chars, "bN" N raw bytes."""
    if typ in TYPES:
        return TYPES[typ]
    n = int(typ[1:])
    return (f"{n}s", n, "char" if typ[0] == "c" else "unsigned char")


class Record:
    """A fixed-size little-endian record: the single source of the layouts
    written into the data, doomdata.inc, doomdata.h and DESIGN.md."""

    def __init__(self, tag, size, fields, doc):
        self.tag, self.size, self.doc = tag, size, doc
        self.fields = []            # (name, type, offset, comment)
        off = 0
        fmt = "<"
        for name, typ, *comment in fields:
            self.fields.append((name, typ, off, comment[0] if comment else ""))
            fmt += type_info(typ)[0]
            off += type_info(typ)[1]
        if off > size:
            raise ValueError(f"{tag}: fields take {off} > {size} bytes")
        self.pad = size - off
        self.fmt = fmt + ("%dx" % self.pad if self.pad else "")
        self.names = [f[0] for f in self.fields]
        assert struct.calcsize(self.fmt) == size

    def pack(self, **values) -> bytes:
        args = []
        for name, typ, _, _ in self.fields:
            v = values.pop(name, 0)
            if typ[0] in "cb" and typ not in TYPES:
                v = v.encode("ascii") if isinstance(v, str) else (v or b"")
            args.append(v)
        if values:
            raise KeyError(f"{self.tag}: unknown fields {sorted(values)}")
        return struct.pack(self.fmt, *args)

    def unpack(self, raw, offset=0) -> dict:
        return dict(zip(self.names, struct.unpack_from(self.fmt, raw, offset)))


R = Record
RECORDS = {r.tag: r for r in [
    # level data
    R("VERTEX", 4, [("x", "s16"), ("y", "s16")], "map units"),
    R("SEG", 16, [("v1", "u16"), ("v2", "u16"),
                  ("angle", "u16", "BAM16, from the WAD"),
                  ("linedef", "u16"), ("sidedef", "u16", "the seg's side of its linedef"),
                  ("offset", "s16", "map units along the linedef, from the WAD"),
                  ("frontsector", "u16"),
                  ("backsector", "u16", "$FFFF unless the linedef is two-sided")],
      "Doom's seg_t with its sectors resolved"),
    R("SSECTOR", 8, [("numsegs", "u16"), ("firstseg", "u16"),
                     ("sector", "u16", "sector of the first seg's sidedef")],
      "subsector (2 bytes padding)"),
    R("NODE", 32, [("x", "s16"), ("y", "s16"), ("dx", "s16"), ("dy", "s16"),
                   ("bbox0_top", "s16", "right child's box"), ("bbox0_bottom", "s16"),
                   ("bbox0_left", "s16"), ("bbox0_right", "s16"),
                   ("bbox1_top", "s16", "left child's box"), ("bbox1_bottom", "s16"),
                   ("bbox1_left", "s16"), ("bbox1_right", "s16"),
                   ("child0", "u16", "right (front); bit 15 = subsector"),
                   ("child1", "u16", "left (back); bit 15 = subsector")],
      "BSP node as in the WAD (4 bytes padding)"),
    R("SIDEDEF", 12, [("xoffset", "s16"), ("yoffset", "s16"),
                      ("toptexture", "u16", "TEXDIR index, 0 = none"),
                      ("bottomtexture", "u16"), ("midtexture", "u16"),
                      ("sector", "u16")], "sidedef, names resolved"),
    R("LINEDEF", 32, [("v1", "u16"), ("v2", "u16"), ("flags", "u16"),
                      ("special", "u8"),
                      ("slopetype", "u8", "0 horizontal, 1 vertical, 2 positive, 3 negative"),
                      ("tag", "u16"), ("side0", "u16"), ("side1", "u16", "$FFFF = one-sided"),
                      ("dx", "s16"), ("dy", "s16"),
                      ("bbox_top", "s16"), ("bbox_bottom", "s16"),
                      ("bbox_left", "s16"), ("bbox_right", "s16"),
                      ("frontsector", "u16"), ("backsector", "u16", "$FFFF = none"),
                      ("scratch", "u16", "zero; free for the game (validcount)")],
      "linedef with Doom's derived fields"),
    R("SECTOR", 16, [("floorheight", "s16"), ("ceilingheight", "s16"),
                     ("floorpic", "u16", "FLATDIR index"), ("ceilingpic", "u16"),
                     ("lightlevel", "u8"), ("special", "u8"), ("tag", "u16"),
                     ("linecount", "u16"), ("firstline", "u16", "index into SECLINES")],
      "sector, flats resolved, with its line list"),
    R("SECLINE", 2, [("line", "u16")],
      "per-sector linedef lists (P_GroupLines order)"),
    R("THING", 10, [("x", "s16"), ("y", "s16"), ("angle", "s16", "degrees"),
                    ("type", "u16", "doomednum"), ("flags", "u16")], "as in the WAD"),
    # directory bank
    R("DESC", 8, [("bank", "u8", "bank of chunk 0"), ("addr", "u16", "base address"),
                  ("elsize", "u8", "element size"), ("log2", "u8", "log2 elements per chunk"),
                  ("count", "u16", "elements"), ("chunks", "u8", "banks used")],
      "far array descriptor (DESIGN.md 4)"),
    R("MAP", 128, [("name", "c8", "\"E1M1\", NUL padded; zero = absent"),
                   ("arrays", "b88", "11 DESC records, index MAPARR_*"),
                   ("sky", "u16", "TEXDIR index of the sky texture"),
       ("firstbank", "u8"), ("numbanks", "u8")],
      "one per map slot"),
    R("TEX", 16, [("bank", "u8"), ("addr", "u16"),
                  ("log2w", "u8", "log2 stored width"), ("wmask", "u8", "stored width - 1"),
                  ("hmask", "u8", "stored height - 1"),
                  ("flags", "u8", "1 masked, 2 sky, 4 animated, 8 switch"),
                  ("log2h", "u8", "log2 stored height"),
                  ("width", "u16", "Doom width, map units"),
                  ("height", "u16", "Doom height, map units"),
                  ("anim_next", "u16", "next frame (self if not animated)"),
                  ("switchtex", "u16", "SW1/SW2 partner, 0 = none")],
      "texture, index 0 = none"),
    R("FLAT", 8, [("bank", "u8"), ("addr", "u16"), ("flags", "u8", "1 sky, 2 animated"),
                  ("anim_next", "u16", "next frame (self if not animated)"),
                  ("color", "u8", "nearest index to the average colour")],
      "flat (1 byte padding)"),
    R("SPRDEF", 4, [("firstframe", "u16", "SPRFRAME index"), ("numframes", "u8")],
      "sprite (spritedef_t), 1 byte padding"),
    R("SPRFRAME", 16, [(f"rot{i}", "u16") for i in range(8)],
      "rotation r (0 = front) lump: bits 0-13 SPRLUMP index ($3FFF missing), "
      "bit 14 frame rotates, bit 15 flipped"),
    R("SPRLUMP", 8, [("bank", "u8"), ("addr", "u16"), ("width", "u8"),
                     ("left", "s16", "halved leftoffset"), ("top", "s16", "halved topoffset")],
      "sprite patch (copy of its header fields)"),
    R("UIPIC", 12, [("bank", "u8"), ("addr", "u16"), ("height", "u8"),
                    ("width", "u16"), ("left", "s16"), ("top", "s16", "halved"),
                    ("flags", "u8", "1 = has transparent pixels")],
      "UI picture, row major (1 byte padding)"),
    R("ANIM", 4, [("kind", "u8", "0 flat, 1 texture"), ("count", "u8"),
                  ("first", "u16", "first frame index")],
      "animated sequence, frames consecutive, 8 tics each"),
    R("SWITCH", 4, [("off", "u16", "SW1 texture"), ("on", "u16", "SW2 texture")],
      "switch pair"),
    R("FILESEG", 5, [("bank", "u8"), ("addr", "u16"), ("length", "u16")],
      "data-file header segment entry (from +8)"),
]}

TEXF_MASKED, TEXF_SKY, TEXF_ANIM, TEXF_SWITCH = 1, 2, 4, 8
FLATF_SKY, FLATF_ANIM = 1, 2
MAP_ARRAYS = ["VERTEXES", "SEGS", "SSECTORS", "NODES", "SIDEDEFS", "LINEDEFS",
              "SECTORS", "SECLINES", "THINGS", "BLOCKMAP", "REJECT"]
ARRAY_RECORD = {"VERTEXES": "VERTEX", "SEGS": "SEG", "SSECTORS": "SSECTOR",
                "NODES": "NODE", "SIDEDEFS": "SIDEDEF", "LINEDEFS": "LINEDEF",
                "SECTORS": "SECTOR", "SECLINES": "SECLINE", "THINGS": "THING"}

# --- Doom's lists ---------------------------------------------------------------------

# animdefs (p_spec.c): (is texture, last, first)
ANIMDEFS = [
    (0, "NUKAGE3", "NUKAGE1"), (0, "FWATER4", "FWATER1"), (0, "SWATER4", "SWATER1"),
    (0, "LAVA4", "LAVA1"), (0, "BLOOD3", "BLOOD1"), (0, "RROCK08", "RROCK05"),
    (0, "SLIME04", "SLIME01"), (0, "SLIME08", "SLIME05"), (0, "SLIME12", "SLIME09"),
    (1, "BLODGR4", "BLODGR1"), (1, "SLADRIP3", "SLADRIP1"), (1, "BLODRIP4", "BLODRIP1"),
    (1, "FIREWALL", "FIREWALA"), (1, "GSTFONT3", "GSTFONT1"), (1, "FIRELAVA", "FIRELAV3"),
    (1, "FIREMAG3", "FIREMAG1"), (1, "FIREBLU2", "FIREBLU1"), (1, "ROCKRED3", "ROCKRED1"),
    (1, "BFALL4", "BFALL1"), (1, "SFALL4", "SFALL1"), (1, "WFALL4", "WFALL1"),
    (1, "DBRAIN4", "DBRAIN1"),
]

# info.c sprnames, the order of the SPR_* constants (filtered to the kept ones)
SPRNAMES = """TROO SHTG PUNG PISG PISF SHTF SHT2 CHGG CHGF MISG MISF SAWG PLSG PLSF
BFGG BFGF BLUD PUFF BAL1 BAL2 PLSS PLSE MISL BFS1 BFE1 BFE2 TFOG IFOG PLAY POSS
SPOS VILE FIRE FATB FBXP SKEL MANF FATT CPOS SARG HEAD BAL7 BOSS BOS2 SKUL SPID
BSPI APLS APBX CYBR PAIN SSWV KEEN BBRN BOSF ARM1 ARM2 BAR1 BEXP FCAN BON1 BON2
BKEY RKEY YKEY BSKU RSKU YSKU STIM MEDI SOUL PINV PSTR PINS MEGA SUIT PMAP PVIS
CLIP AMMO ROCK BROK CELL CELP SHEL SBOX BPAK BFUG MGUN CSAW LAUN PLAS SHOT SGN2
COLU SMT2 GOR1 POL2 POL5 POL4 POL3 POL1 POL6 GOR2 GOR3 GOR4 GOR5 SMIT COL1 COL2
COL3 COL4 CAND CBRA COL6 TRE1 TRE2 ELEC CEYE FSKU COL5 TBLU TGRN TRED SMBT SMGT
SMRT HDB1 HDB2 HDB3 HDB4 HDB5 HDB6 POB1 POB2 BRS1 TLMP TLP2""".split()

# Always kept: the E1 monsters and what they shoot and drop, the player
# and his weapons, projectiles, effects, every pickup, the barrel.
ALWAYS_SPRITES = """PLAY POSS SPOS TROO SARG SKUL HEAD BOSS
BAL1 BAL2 BAL7 MISL PLSS PLSE BFS1 BFE1 BFE2 PUFF BLUD TFOG IFOG BAR1 BEXP
PUNG PISG PISF SHTG SHTF CHGG CHGF MISG MISF SAWG PLSG PLSF BFGG BFGF
CLIP AMMO ROCK BROK CELL CELP SHEL SBOX BPAK BFUG MGUN CSAW LAUN PLAS SHOT
STIM MEDI SOUL BON1 BON2 ARM1 ARM2 PINV PSTR PINS SUIT PMAP PVIS MEGA
BKEY RKEY YKEY BSKU RSKU YSKU""".split()

# Doom 1 editor numbers -> sprites (things placed in maps). Monsters that
# are not in ALWAYS_SPRITES bring their projectile sprites along.
DOOMEDNUM_SPRITES = {
    1: "PLAY", 2: "PLAY", 3: "PLAY", 4: "PLAY", 11: "", 14: "",
    3004: "POSS", 9: "SPOS", 3001: "TROO", 3002: "SARG", 58: "SARG", 3006: "SKUL",
    3005: "HEAD", 3003: "BOSS", 16: "CYBR MISL", 7: "SPID PUFF",
    2001: "SHOT", 2002: "MGUN", 2003: "LAUN", 2004: "PLAS", 2005: "CSAW", 2006: "BFUG",
    2007: "CLIP", 2048: "AMMO", 2008: "SHEL", 2049: "SBOX", 2010: "ROCK", 2046: "BROK",
    2047: "CELL", 17: "CELP", 8: "BPAK", 2011: "STIM", 2012: "MEDI", 2013: "SOUL",
    2014: "BON1", 2015: "BON2", 2018: "ARM1", 2019: "ARM2", 2022: "PINV", 2023: "PSTR",
    2024: "PINS", 2025: "SUIT", 2026: "PMAP", 2045: "PVIS",
    5: "BKEY", 6: "YKEY", 13: "RKEY", 40: "BSKU", 39: "YSKU", 38: "RSKU",
    2035: "BAR1 BEXP", 2028: "COLU", 30: "COL1", 31: "COL2", 32: "COL3", 33: "COL4",
    36: "COL5", 37: "COL6", 41: "CEYE", 42: "FSKU", 43: "TRE1", 44: "TBLU", 45: "TGRN",
    46: "TRED", 47: "SMIT", 48: "ELEC", 54: "TRE2", 55: "SMBT", 56: "SMGT", 57: "SMRT",
    34: "CAND", 35: "CBRA", 49: "GOR1", 50: "GOR2", 51: "GOR3", 52: "GOR4", 53: "GOR5",
    59: "GOR2", 60: "GOR4", 61: "GOR3", 62: "GOR5", 63: "GOR1",
    10: "PLAY", 12: "PLAY", 15: "PLAY", 18: "POSS", 19: "SPOS", 20: "TROO", 21: "SARG",
    22: "HEAD", 23: "SKUL", 24: "POL5", 25: "POL1", 26: "POL6", 27: "POL4", 28: "POL2",
    29: "POL3",
}

# UI pictures (halved vertically only): status bar, faces, font, menus,
# title, episode-1 intermission.
UI_PATTERNS = [
    r"STBAR", r"STARMS", r"ST[GTY]NUM\d", r"STYSNUM\d", r"STTMINUS", r"STTPRCNT",
    r"STKEYS\d", r"STF(ST|TL|TR|OUCH|EVL|KILL|GOD|DEAD)\d*", r"STCFN\d\d\d",
    r"M_(DOOM|NGAME|OPTION|QUITG|NEWG|SKILL|JKILL|ROUGH|HURT|ULTRA|NMARE|EPISOD|EPI1"
    r"|SKULL1|SKULL2|PAUSE|THERM[LMRO]|SVOL|SFXVOL|MUSVOL|MSENS|ENDGAM|MESSG|MSGON"
    r"|MSGOFF|DETAIL|GDHIGH|GDLOW|DISOPT|SCRNSZ|RDTHIS|LOADG|SAVEG)",
    r"TITLEPIC", r"WIMAP0", r"WIA0\d+", r"WILV0\d", r"WIURH[01]", r"WISPLAT",
    r"WIOST[KISF]", r"WIF", r"WIMSTT", r"WITIME", r"WIPAR", r"WIMSTAR", r"WIMINUS",
    r"WIPCNT", r"WINUM\d", r"WICOLON", r"WISUCKS", r"WIKILRS", r"WISCRT2", r"WIENTER",
]
UI_RE = re.compile("^(" + "|".join(UI_PATTERNS) + ")$")


# --- palette and halving ----------------------------------------------------------

def rgb444(r, g, b):
    q = lambda v: (v * 15 + 127) // 255
    return q(r), q(g), q(b)


class Palette:
    """PLAYPAL 0 and the nearest-colour reduction used by every halving."""

    def __init__(self, playpal: bytes):
        self.rgb = [tuple(playpal[3 * i:3 * i + 3]) for i in range(256)]
        self.candidates = [(i, *self.rgb[i]) for i in range(256) if i != TRANSPARENT]
        self.cache = {}

    def nearest_sum(self, sr, sg, sb, n):
        """Index nearest to the colour (sr/n, sg/n, sb/n), exact integers."""
        key = (sr, sg, sb, n)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        best, bestd = 0, None
        for i, r, g, b in self.candidates:
            d = (n * r - sr) ** 2 + (n * g - sg) ** 2 + (n * b - sb) ** 2
            if bestd is None or d < bestd:
                best, bestd = i, d
        self.cache[key] = best
        return best

    def reduce(self, opaque):
        """Palette index for a block's opaque texels (a non-empty list)."""
        first = opaque[0]
        if first != TRANSPARENT and all(v == first for v in opaque):
            return first
        sr = sg = sb = 0
        rgb = self.rgb
        for v in opaque:
            r, g, b = rgb[v]
            sr += r
            sg += g
            sb += b
        return self.nearest_sum(sr, sg, sb, len(opaque))


def halve(cols, width, height, sx, sy, pal: Palette):
    """Column-major picture (None = transparent) reduced by sx x sy blocks."""
    W = (width + sx - 1) // sx
    H = (height + sy - 1) // sy
    out = []
    for X in range(W):
        src = cols[sx * X:sx * X + sx]
        oc = [None] * H
        for Y in range(H):
            y0 = sy * Y
            vals = []
            for c in src:
                vals.extend(c[y0:y0 + sy])
            opaque = [v for v in vals if v is not None]
            if 2 * len(opaque) >= len(vals):
                oc[Y] = pal.reduce(opaque)
        out.append(oc)
    return out, W, H


def pow2_at_least(v):
    p = 1
    while p < v:
        p <<= 1
    return p


def log2(v):
    return v.bit_length() - 1


# --- graphics ---------------------------------------------------------------------------

class GfxObject:
    """Bytes to be placed in a graphics bank."""

    def __init__(self, kind, name, data):
        self.kind, self.name, self.data = kind, name, bytes(data)
        self.bank = self.addr = None


def build_texture(wad, tdef, pal, patch_cache):
    canvas = [[None] * tdef.height for _ in range(tdef.width)]
    for ox, oy, pname in tdef.patches:
        if pname not in patch_cache:
            patch_cache[pname] = wad.read(pname) if wad.has(pname) else None
        raw = patch_cache[pname]
        if raw is None:
            print(f"warning: texture {tdef.name}: missing patch {pname}", file=sys.stderr)
            continue
        wadlib.draw_patch_into(canvas, tdef.width, tdef.height, raw, ox, oy)
    half, w0, h0 = halve(canvas, tdef.width, tdef.height, 2, 2, pal)
    if w0 > MAX_TEX_HALF_W or h0 > MAX_TEX_HALF_H:
        raise ValueError(f"texture {tdef.name} is {tdef.width}x{tdef.height}: too large")
    masked = any(v is None for c in half for v in c)
    W, H = pow2_at_least(w0), pow2_at_least(h0)
    data = bytearray()
    for x in range(W):
        col = half[x % w0]
        for y in range(H):
            v = col[y % h0]
            data.append(TRANSPARENT if v is None else v)
    return dict(half=half, w0=w0, h0=h0, W=W, H=H, masked=masked, data=bytes(data))


def build_flat(raw, pal):
    cols = [[raw[64 * y + x] for y in range(64)] for x in range(64)]
    half, _, _ = halve(cols, 64, 64, 2, 2, pal)
    data = bytes(half[x][y] for y in range(32) for x in range(32))
    sr = sg = sb = 0
    for v in raw:
        r, g, b = pal.rgb[v]
        sr += r
        sg += g
        sb += b
    return data, pal.nearest_sum(sr, sg, sb, len(raw))


def build_sprite(raw, pal):
    pic = wadlib.decode_patch(raw)
    half, W, H = halve(pic.columns, pic.width, pic.height, 2, 2, pal)
    if W > 255 or H > 254:
        raise ValueError("sprite too large after halving")
    left, top = pic.left // 2, pic.top // 2
    head = struct.pack("<BBhh", W, H, left, top)
    colofs = []
    posts = bytearray()
    base = 6 + 2 * W
    for col in half:
        colofs.append(base + len(posts))
        y = 0
        while y < H:
            if col[y] is None:
                y += 1
                continue
            y1 = y
            while y1 < H and col[y1] is not None and y1 - y < 255:
                y1 += 1
            posts += bytes((y, y1 - y)) + bytes(col[y:y1])
            y = y1
        posts.append(0xFF)
    data = head + b"".join(struct.pack("<H", o) for o in colofs) + posts
    return data, dict(width=W, height=H, left=left, top=top, half=half)


def build_uipic(raw, pal):
    pic = wadlib.decode_patch(raw)
    half, W, H = halve(pic.columns, pic.width, pic.height, 1, 2, pal)
    if H > 255:
        raise ValueError("UI picture too tall")
    trans = any(v is None for c in half for v in c)
    data = bytes(TRANSPARENT if half[x][y] is None else half[x][y]
                 for y in range(H) for x in range(W))
    return data, dict(width=W, height=H, left=pic.left, top=pic.top // 2,
                      flags=1 if trans else 0)


# --- level data -----------------------------------------------------------------------

class MapError(Exception):
    pass


def convert_map(name, lumps, texindex, flatindex):
    """Level lumps -> ({array name: (element size, count, bytes)}, counts).
    Raises MapError for a broken reference or a limit exceeded. With
    texindex/flatindex None the names are not resolved (validation pass)."""
    for k in wadlib.MAP_LUMPS:
        if k not in lumps:
            raise MapError(f"missing lump {k}")
    verts = list(struct.iter_unpack("<hh", lumps["VERTEXES"]))
    lines = list(struct.iter_unpack("<HHHHHHH", lumps["LINEDEFS"]))
    sides_raw = [struct.unpack_from("<hh8s8s8sH", lumps["SIDEDEFS"], 30 * i)
                 for i in range(len(lumps["SIDEDEFS"]) // 30)]
    secs_raw = [struct.unpack_from("<hh8s8shhh", lumps["SECTORS"], 26 * i)
                for i in range(len(lumps["SECTORS"]) // 26)]
    segs = list(struct.iter_unpack("<HHHHHh", lumps["SEGS"]))
    ssecs = list(struct.iter_unpack("<HH", lumps["SSECTORS"]))
    nodes = list(struct.iter_unpack("<hhhh4h4hHH", lumps["NODES"]))
    things = lumps["THINGS"][:len(lumps["THINGS"]) // 10 * 10]
    nv, nl, ns, nsec = len(verts), len(lines), len(sides_raw), len(secs_raw)
    counts = {"vertexes": nv, "linedefs": nl, "sidedefs": ns, "sectors": nsec,
              "segs": len(segs), "subsectors": len(ssecs), "nodes": len(nodes),
              "things": len(things) // 10, "blockmap_bytes": len(lumps["BLOCKMAP"])}

    def check(cond, what):
        if not cond:
            raise MapError(what)

    rec = RECORDS
    # sidedefs
    sides = []
    out_sides = bytearray()
    for i, (xo, yo, top, bot, mid, sec) in enumerate(sides_raw):
        check(sec < nsec, f"sidedef {i}: sector {sec} out of range")
        t = []
        for raw in (top, bot, mid):
            n = wadlib.lump_name(raw)
            if n in ("-", "") or texindex is None:
                t.append(0)
            elif n in texindex:
                t.append(texindex[n])
            else:
                print(f"warning: {name}: unknown texture {n}", file=sys.stderr)
                t.append(0)
        sides.append(sec)
        out_sides += rec["SIDEDEF"].pack(xoffset=xo, yoffset=yo, toptexture=t[0],
                                         bottomtexture=t[1], midtexture=t[2], sector=sec)
    # linedefs
    out_lines = bytearray()
    lfront, lback = [], []
    for i, (v1, v2, flags, special, tag, s0, s1) in enumerate(lines):
        check(v1 < nv and v2 < nv, f"linedef {i}: vertex out of range")
        check(s0 < ns, f"linedef {i}: no front sidedef")
        check(s1 == NONE16 or s1 < ns, f"linedef {i}: back sidedef out of range")
        check(special < 256, f"linedef {i}: special {special} > 255")
        (x1, y1), (x2, y2) = verts[v1], verts[v2]
        dx, dy = x2 - x1, y2 - y1
        if dx == 0:
            slope = 1
        elif dy == 0:
            slope = 0
        elif (dx > 0) == (dy > 0):
            slope = 2
        else:
            slope = 3
        front = sides[s0]
        back = sides[s1] if s1 != NONE16 else NONE16
        lfront.append(front)
        lback.append(back)
        out_lines += rec["LINEDEF"].pack(
            v1=v1, v2=v2, flags=flags, special=special, slopetype=slope, tag=tag,
            side0=s0, side1=s1, dx=dx, dy=dy, bbox_top=max(y1, y2),
            bbox_bottom=min(y1, y2), bbox_left=min(x1, x2), bbox_right=max(x1, x2),
            frontsector=front, backsector=back)
    # sector line lists (P_GroupLines)
    per_sector = [[] for _ in range(nsec)]
    for i in range(nl):
        per_sector[lfront[i]].append(i)
        if lback[i] != NONE16 and lback[i] != lfront[i]:
            per_sector[lback[i]].append(i)
    out_seclines = bytearray()
    out_secs = bytearray()
    first = 0
    for i, (fh, ch, fp, cp, light, special, tag) in enumerate(secs_raw):
        pics = []
        for raw in (fp, cp):
            n = wadlib.lump_name(raw)
            if flatindex is None:
                pics.append(0)
                continue
            if n not in flatindex:
                print(f"warning: {name}: unknown flat {n}", file=sys.stderr)
            pics.append(flatindex.get(n, 0))
        check(0 <= special < 256, f"sector {i}: special {special}")
        lst = per_sector[i]
        out_secs += rec["SECTOR"].pack(
            floorheight=fh, ceilingheight=ch, floorpic=pics[0], ceilingpic=pics[1],
            lightlevel=max(0, min(255, light)), special=special, tag=tag & 0xFFFF,
            linecount=len(lst), firstline=first)
        for ln in lst:
            out_seclines += struct.pack("<H", ln)
        first += len(lst)
    counts["seclines"] = first
    # segs
    out_segs = bytearray()
    for i, (v1, v2, angle, ld, side, offset) in enumerate(segs):
        check(v1 < nv and v2 < nv, f"seg {i}: vertex out of range")
        check(ld < nl and side < 2, f"seg {i}: bad linedef/side")
        l = lines[ld]
        sd = l[5] if side == 0 else l[6]
        check(sd != NONE16, f"seg {i}: its side of linedef {ld} has no sidedef")
        front = sides[sd]
        back = NONE16
        if l[2] & 4:                    # ML_TWOSIDED
            other = l[6] if side == 0 else l[5]
            if other != NONE16:
                back = sides[other]
        out_segs += rec["SEG"].pack(v1=v1, v2=v2, angle=angle, linedef=ld, sidedef=sd,
                                    offset=offset, frontsector=front, backsector=back)
    # subsectors
    out_ssecs = bytearray()
    for i, (n, fs) in enumerate(ssecs):
        check(n > 0 and fs + n <= len(segs), f"subsector {i}: seg range")
        seg = segs[fs]
        l = lines[seg[3]]
        sd = l[5] if seg[4] == 0 else l[6]
        out_ssecs += rec["SSECTOR"].pack(numsegs=n, firstseg=fs, sector=sides[sd])
    # nodes
    out_nodes = bytearray()
    for i, nd in enumerate(nodes):
        x, y, dx, dy = nd[0:4]
        b0, b1 = nd[4:8], nd[8:12]
        c0, c1 = nd[12], nd[13]
        for c in (c0, c1):
            if c & 0x8000:
                check((c & 0x7FFF) < len(ssecs), f"node {i}: subsector out of range")
            else:
                check(c < len(nodes), f"node {i}: child out of range")
        out_nodes += rec["NODE"].pack(
            x=x, y=y, dx=dx, dy=dy, bbox0_top=b0[0], bbox0_bottom=b0[1], bbox0_left=b0[2],
            bbox0_right=b0[3], bbox1_top=b1[0], bbox1_bottom=b1[1], bbox1_left=b1[2],
            bbox1_right=b1[3], child0=c0, child1=c1)
    # reject (padded to its full size), blockmap as is
    rej_len = (nsec * nsec + 7) // 8
    reject = (lumps["REJECT"] + bytes(rej_len))[:rej_len]
    blockmap = lumps["BLOCKMAP"]
    check(len(blockmap) >= 8 and len(blockmap) % 2 == 0, "blockmap missing or odd")

    for key, limit in LIMITS.items():
        if counts[key] > limit:
            raise MapError(f"{key} {counts[key]} over the limit {limit}")

    arrays = {
        "VERTEXES": (4, nv, b"".join(struct.pack("<hh", *v) for v in verts)),
        "SEGS": (16, len(segs), bytes(out_segs)),
        "SSECTORS": (8, len(ssecs), bytes(out_ssecs)),
        "NODES": (32, len(nodes), bytes(out_nodes)),
        "SIDEDEFS": (12, ns, bytes(out_sides)),
        "LINEDEFS": (32, nl, bytes(out_lines)),
        "SECTORS": (16, nsec, bytes(out_secs)),
        "SECLINES": (2, first, bytes(out_seclines)),
        "THINGS": (10, len(things) // 10, bytes(things)),
        "BLOCKMAP": (2, len(blockmap) // 2, bytes(blockmap)),
        "REJECT": (1, rej_len, bytes(reject)),
    }
    return arrays, counts


def chunk_log2(size):
    k = 0
    while (size << (k + 1)) <= BANK_CAP and k < 15:
        k += 1
    return k


# --- bank images ------------------------------------------------------------------------

class Banks:
    """Bank images being filled: bank -> bytearray(65536) and its top."""

    def __init__(self):
        self.image = {}
        self.top = {}
        self.region = {}

    def new(self, bank, region, top):
        self.image[bank] = bytearray(0x10000)
        self.top[bank] = top
        self.region[bank] = region

    def put(self, bank, addr, data):
        assert BANK_LO <= addr and addr + len(data) <= BANK_HI, (bank, hex(addr), len(data))
        self.image[bank][addr:addr + len(data)] = data
        self.top[bank] = max(self.top[bank], addr + len(data))

    def segments(self, banks):
        return [(b, BANK_LO, self.top[b] - BANK_LO) for b in banks if self.top[b] > BANK_LO]


def pack_level(arrays):
    """Place a map's arrays in its banks: -> (bank count, {array: (bank offset,
    address, log2 elements per chunk, chunks)}).

    An array larger than a bank is chunked: its chunks share one base
    address in consecutive banks, the smallest base above what those banks
    already hold. Every chunk exponent from the largest down by three is
    tried for each such array and the combination using the fewest banks
    wins (then the fewest chunks). Arrays that fit a bank follow, first-fit
    decreasing; their exponent is at least ceil(log2 count), so i >> k = 0
    holds for every element.
    """
    multi = [a for a in MAP_ARRAYS if len(arrays[a][2]) > BANK_CAP]
    singles = sorted((a for a in MAP_ARRAYS if a not in multi),
                     key=lambda a: (-len(arrays[a][2]), MAP_ARRAYS.index(a)))
    choices = []
    for a in multi:
        kmax = chunk_log2(arrays[a][0])
        choices.append([k for k in range(kmax, max(kmax - 3, 0) - 1, -1)])

    def attempt(ks):
        tops, place = [], {}
        order = sorted(multi, key=lambda a: (-(arrays[a][0] << ks[a]), MAP_ARRAYS.index(a)))
        for a in order:
            size, count, data = arrays[a]
            per = size << ks[a]
            lens = [min(per, len(data) - c * per) for c in range((len(data) + per - 1) // per)]
            s = 0
            while True:
                base = max([BANK_LO] + [tops[s + c] for c in range(len(lens)) if s + c < len(tops)])
                if all(base + n <= BANK_HI for n in lens):
                    break
                s += 1
            while len(tops) < s + len(lens):
                tops.append(BANK_LO)
            for c, n in enumerate(lens):
                tops[s + c] = base + n
            place[a] = (s, base, ks[a], len(lens))
        for a in singles:
            size, count, data = arrays[a]
            k = max(chunk_log2(size), (count - 1).bit_length())
            b = next((i for i, t in enumerate(tops) if t + len(data) <= BANK_HI), None)
            if b is None:
                b = len(tops)
                tops.append(BANK_LO)
            place[a] = (b, tops[b], k, 1)
            tops[b] += len(data)
        return len(tops), place

    best = None
    for combo in itertools.product(*choices):
        ks = dict(zip(multi, combo))
        n, place = attempt(ks)
        key = (n, -sum(combo))
        if best is None or key < best[0]:
            best = (key, n, place)
    return best[1], best[2]


# --- the conversion ------------------------------------------------------------------------

class Conversion:
    def __init__(self, wad_path, maps, first_bank=FIRST_BANK, verbose=True,
                 shared_map_banks=False):
        self.t0 = time.time()
        self.verbose = verbose
        self.wad = wadlib.Wad(wad_path)
        self.wad_sha256 = hashlib.sha256(self.wad.data).hexdigest()
        self.first_bank = first_bank
        self.requested = maps
        self.shared = shared_map_banks
        self.pal = Palette(self.wad.read("PLAYPAL")[:768])
        self.banks = Banks()
        self.skipped = {}
        self.run()

    def log(self, msg):
        if self.verbose:
            print(f"[{time.time() - self.t0:6.1f}s] {msg}", file=sys.stderr)

    # ------------------------------------------------------------------
    def run(self):
        wad = self.wad
        self.texdefs = wad.texture_defs()
        self.texdef_by_name = {}
        for t in self.texdefs:
            self.texdef_by_name.setdefault(t.name, t)
        self.flat_lumps = {}
        self.flat_order = []
        for l in wad.flat_lumps():
            if l.name not in self.flat_lumps:
                self.flat_order.append(l.name)
            self.flat_lumps[l.name] = l.index

        # maps: which textures, flats and things they use
        map_lumps = {}
        used_tex, used_flats, used_types = set(), set(), set()
        episodes = set()
        for m in self.requested:
            mm = re.fullmatch(r"E(\d)M(\d)", m)
            if not mm or m not in wad.map_names():
                self.skipped[m] = "not in the WAD"
                continue
            lumps = wad.map_lumps(m)
            try:
                convert_map(m, lumps, None, None)
            except MapError as e:
                self.skipped[m] = str(e)
                print(f"warning: {m} skipped: {e}", file=sys.stderr)
                continue
            map_lumps[m] = lumps
            episodes.add(int(mm.group(1)))
            sd = lumps.get("SIDEDEFS", b"")
            for k in range(len(sd) // 30):
                for o in (4, 12, 20):
                    used_tex.add(wadlib.lump_name(sd[30 * k + o:30 * k + o + 8]))
            sc = lumps.get("SECTORS", b"")
            for k in range(len(sc) // 26):
                used_flats.add(wadlib.lump_name(sc[26 * k + 4:26 * k + 12]))
                used_flats.add(wadlib.lump_name(sc[26 * k + 12:26 * k + 20]))
            for th in struct.iter_unpack("<hhhHH", lumps.get("THINGS", b"")[:len(lumps.get("THINGS", b"")) // 10 * 10]):
                used_types.add(th[3])
        used_tex.discard("-")
        used_tex.discard("")
        self.episodes = sorted(episodes) or [1]
        self.skies = {e: f"SKY{e}" for e in self.episodes}
        used_tex |= {s for s in self.skies.values() if s in self.texdef_by_name}
        used_flats.add("F_SKY1")

        # complete animations and switches
        self.anim_seqs = []
        tex_order = [t.name for t in self.texdefs]
        for kind, last, first in ANIMDEFS:
            order = tex_order if kind else self.flat_order
            if first not in order or last not in order:
                continue
            a, b = order.index(first), order.index(last)
            if b < a:
                continue
            frames = order[a:b + 1]
            used = used_tex if kind else used_flats
            if any(f in used for f in frames):
                used |= set(frames)
                self.anim_seqs.append((kind, frames))
        for n in list(used_tex):
            if n[:3] in ("SW1", "SW2"):
                partner = ("SW2" if n[:3] == "SW1" else "SW1") + n[3:]
                if partner in self.texdef_by_name:
                    used_tex.add(partner)

        # numbering: WAD order (animation frames stay consecutive)
        missing = sorted(n for n in used_tex if n not in self.texdef_by_name)
        for n in missing:
            print(f"warning: texture {n} not in TEXTURE1/2", file=sys.stderr)
        self.tex_names = ["-"]
        seen = set()
        for t in self.texdefs:
            if t.name in used_tex and t.name not in seen:
                seen.add(t.name)
                self.tex_names.append(t.name)
        self.texindex = {n: i for i, n in enumerate(self.tex_names) if i}
        self.flat_names = [n for n in self.flat_order if n in used_flats]
        for n in sorted(used_flats - set(self.flat_names)):
            print(f"warning: flat {n} not in the WAD", file=sys.stderr)
        self.flatindex = {n: i for i, n in enumerate(self.flat_names)}
        self.switches = []
        for n in self.tex_names:
            if n.startswith("SW1") and "SW2" + n[3:] in self.texindex:
                self.switches.append((self.texindex[n], self.texindex["SW2" + n[3:]]))

        # sprites
        keep = set(ALWAYS_SPRITES)
        for ty in sorted(used_types):
            if ty in DOOMEDNUM_SPRITES:
                keep |= set(DOOMEDNUM_SPRITES[ty].split())
            else:
                print(f"warning: thing type {ty} unknown, no sprite kept", file=sys.stderr)
        self.sprite_lumps_by_name = {}
        for l in wad.sprite_lumps():
            self.sprite_lumps_by_name[l.name] = l.index
        present = {n[:4] for n in self.sprite_lumps_by_name}
        order = SPRNAMES + sorted(keep - set(SPRNAMES))
        self.sprite_names = [s for s in order if s in keep and s in present]
        self.sprites_missing = sorted(s for s in keep if s not in present)

        self.log(f"{len(map_lumps)} maps, {len(self.tex_names) - 1} textures, "
                 f"{len(self.flat_names)} flats, {len(self.sprite_names)} sprites")
        self.build_graphics()
        self.build_directory_contents()
        self.build_maps(map_lumps)
        self.build_directory_bank()
        self.log(f"banks {self.first_bank}..{self.last_bank}")

    # ------------------------------------------------------------------
    def build_graphics(self):
        wad, pal = self.wad, self.pal
        objects = []
        # textures
        patch_cache = {}
        self.textures = [None]
        for n in self.tex_names[1:]:
            t = build_texture(wad, self.texdef_by_name[n], pal, patch_cache)
            t["obj"] = GfxObject("tex", n, t["data"])
            objects.append(t["obj"])
            self.textures.append(t)
        self.log("textures composited and halved")
        self.flats = []
        for n in self.flat_names:
            data, color = build_flat(wad.read(self.flat_lumps[n]), pal)
            obj = GfxObject("flat", n, data)
            objects.append(obj)
            self.flats.append(dict(name=n, data=data, color=color, obj=obj))
        # sprite lumps and frames
        self.sprlumps = []
        self.sprdefs = []
        self.sprframes = []
        for s in self.sprite_names:
            names = sorted(n for n in self.sprite_lumps_by_name if n[:4] == s)
            frames = {}
            for n in names:
                idx = len(self.sprlumps)
                data, info = build_sprite(wad.read(self.sprite_lumps_by_name[n]), pal)
                obj = GfxObject("sprite", n, data)
                objects.append(obj)
                self.sprlumps.append(dict(name=n, obj=obj, **info))
                for fr, rot, flip in ((n[4:5], n[5:6], 0), (n[6:7], n[7:8], 1)):
                    if not fr:
                        continue
                    f = ord(fr) - ord("A")
                    r = int(rot)
                    slot = frames.setdefault(f, [None] * 8)
                    if r == 0:
                        for k in range(8):
                            slot[k] = (idx, flip, 0)
                    else:
                        slot[r - 1] = (idx, flip, 1)
            nframes = max(frames) + 1 if frames else 0
            self.sprdefs.append((len(self.sprframes), nframes))
            for f in range(nframes):
                slot = frames.get(f, [None] * 8)
                rotates = any(e is not None and e[2] for e in slot)
                fallback = next((e for e in slot if e is not None), None)
                entry = []
                for e in slot:
                    e = e or fallback
                    if e is None:
                        entry.append(SPR_NOLUMP | (0x4000 if rotates else 0))
                    else:
                        entry.append(e[0] | (0x4000 if rotates else 0) | (0x8000 if e[1] else 0))
                self.sprframes.append(entry)
        self.log(f"{len(self.sprlumps)} sprite lumps halved")
        # UI pictures
        self.uipics = []
        for l in wad.lumps:
            if UI_RE.match(l.name) and l.size > 8 and l.name not in {u["name"] for u in self.uipics}:
                data, info = build_uipic(wad.read(wad.num(l.name)), pal)
                obj = GfxObject("ui", l.name, data)
                objects.append(obj)
                self.uipics.append(dict(name=l.name, obj=obj, **info))
        # colormaps
        cmap = wad.read("COLORMAP")
        self.colormaps = b"".join(cmap[256 * 2 * k:256 * 2 * k + 256] for k in range(NUM_COLORMAPS))
        self.invulmap = cmap[256 * 32:256 * 33]
        # place: the directory bank first, then the graphics banks
        self.dir_bank = self.first_bank
        self.banks.new(self.dir_bank, "DIR", BANK_LO)
        self.gfx_banks = []
        first_gfx = self.first_bank + 1
        nb = first_gfx
        # pack with the colormaps pre-placed in every new bank
        order = sorted(range(len(objects)), key=lambda i: (-len(objects[i].data), i))
        for i in order:
            obj = objects[i]
            size = len(obj.data)
            if size > GFX_CAP:
                raise ValueError(f"{obj.name}: {size} bytes do not fit a graphics bank")
            for b in self.gfx_banks:
                if self.banks.top[b] + size <= BANK_HI:
                    break
            else:
                b = nb
                nb += 1
                self.banks.new(b, "GFX", BANK_LO)
                self.banks.put(b, COLORMAP_ADDR, self.colormaps)
                self.gfx_banks.append(b)
            obj.bank, obj.addr = b, self.banks.top[b]
            self.banks.put(b, obj.addr, obj.data)
        self.next_bank = nb
        self.gfx_objects = objects
        self.log(f"graphics: {len(objects)} objects in {len(self.gfx_banks)} banks")

    # ------------------------------------------------------------------
    def build_directory_contents(self):
        """Everything of the directory bank except the map table."""
        playpal = self.wad.read("PLAYPAL")
        pp = bytearray()
        for p in range(14):
            for i in range(256):
                r, g, b = rgb444(*playpal[768 * p + 3 * i:768 * p + 3 * i + 3])
                pp += bytes((g << 4 | b, 0x20 | r))
        self.playpal444 = bytes(pp)
        rec = RECORDS
        tex = bytearray(rec["TEX"].pack())      # 0 = none
        anim_next_tex = {}
        anim_next_flat = {}
        self.anims = bytearray()
        for kind, frames in self.anim_seqs:
            index = self.texindex if kind else self.flatindex
            ids = [index[f] for f in frames]
            for a, b in zip(ids, ids[1:] + ids[:1]):
                (anim_next_tex if kind else anim_next_flat)[a] = b
            self.anims += rec["ANIM"].pack(kind=kind, count=len(ids), first=ids[0])
        switch_of = {}
        for a, b in self.switches:
            switch_of[a] = b
            switch_of[b] = a
        sky_names = set(self.skies.values())
        for i, t in enumerate(self.textures[1:], 1):
            n = self.tex_names[i]
            d = self.texdef_by_name[n]
            flags = (TEXF_MASKED if t["masked"] else 0) | (TEXF_SKY if n in sky_names else 0) \
                | (TEXF_ANIM if i in anim_next_tex else 0) | (TEXF_SWITCH if i in switch_of else 0)
            tex += rec["TEX"].pack(bank=t["obj"].bank, addr=t["obj"].addr, log2w=log2(t["W"]),
                                   wmask=t["W"] - 1, hmask=t["H"] - 1, flags=flags,
                                   log2h=log2(t["H"]), width=d.width, height=d.height,
                                   anim_next=anim_next_tex.get(i, i), switchtex=switch_of.get(i, 0))
        self.texdir = bytes(tex)
        flat = bytearray()
        for i, f in enumerate(self.flats):
            flags = (FLATF_SKY if f["name"] == "F_SKY1" else 0) | (FLATF_ANIM if i in anim_next_flat else 0)
            flat += rec["FLAT"].pack(bank=f["obj"].bank, addr=f["obj"].addr, flags=flags,
                                     anim_next=anim_next_flat.get(i, i), color=f["color"])
        self.flatdir = bytes(flat)
        self.sprdef = b"".join(rec["SPRDEF"].pack(firstframe=a, numframes=n) for a, n in self.sprdefs)
        self.sprframe = b"".join(rec["SPRFRAME"].pack(**{f"rot{k}": e[k] for k in range(8)})
                                 for e in self.sprframes)
        self.sprlump = b"".join(rec["SPRLUMP"].pack(bank=s["obj"].bank, addr=s["obj"].addr,
                                                    width=s["width"], left=s["left"], top=s["top"])
                                for s in self.sprlumps)
        self.uidir = b"".join(rec["UIPIC"].pack(bank=u["obj"].bank, addr=u["obj"].addr,
                                                height=u["height"], width=u["width"],
                                                left=u["left"], top=u["top"], flags=u["flags"])
                              for u in self.uipics)
        self.switchtab = b"".join(rec["SWITCH"].pack(off=a, on=b) for a, b in self.switches)
        self.endoom = self.wad.read("ENDOOM")[:4000] if self.wad.has("ENDOOM") else bytes(4000)

    # ------------------------------------------------------------------
    def build_maps(self, map_lumps):
        """Each map in its own banks after the graphics (default), or, with
        shared map banks, every map at the same banks (loaded per level)."""
        self.maps = {}
        self.map_images = {}
        self.map_first_bank = self.next_bank
        last = self.next_bank - 1
        for m in self.requested:
            if m not in map_lumps:
                continue
            try:
                arrays, counts = convert_map(m, map_lumps[m], self.texindex, self.flatindex)
            except MapError as e:
                self.skipped[m] = str(e)
                print(f"warning: {m} skipped: {e}", file=sys.stderr)
                continue
            nbanks, place = pack_level(arrays)
            first = self.map_first_bank if self.shared else self.next_bank
            region_banks = list(range(first, first + nbanks))
            mb = self.map_images[m] = Banks()
            for b in region_banks:
                mb.new(b, m, BANK_LO)
            descs = {}
            for an in MAP_ARRAYS:
                size, count, data = arrays[an]
                rel, addr, k, nchunks = place[an]
                per = (1 << k) * size
                for c in range(nchunks):
                    mb.put(first + rel + c, addr, data[c * per:(c + 1) * per])
                descs[an] = dict(bank=first + rel, addr=addr, elsize=size, log2=k,
                                 count=count, chunks=nchunks)
            self.next_bank = first + nbanks
            last = max(last, first + nbanks - 1)
            mm = re.fullmatch(r"E(\d)M(\d)", m)
            ep, mn = int(mm.group(1)), int(mm.group(2))
            self.maps[m] = dict(slot=9 * (ep - 1) + mn - 1, banks=region_banks, arrays=descs,
                                counts=counts, sky=self.texindex.get(self.skies.get(ep, ""), 0),
                                bytes=sum(len(arrays[a][2]) for a in MAP_ARRAYS))
            self.log(f"{m}: {len(region_banks)} banks ({self.maps[m]['bytes']} bytes)")
        self.last_bank = last

    # ------------------------------------------------------------------
    def build_directory_bank(self):
        rec = RECORDS
        nslots = 9 * max(self.episodes)
        mapdir = bytearray()
        for slot in range(nslots):
            m = next((k for k, v in self.maps.items() if v["slot"] == slot), None)
            if m is None:
                mapdir += bytes(rec["MAP"].size)
                continue
            info = self.maps[m]
            body = b"".join(rec["DESC"].pack(**info["arrays"][a]) for a in MAP_ARRAYS)
            vals = {"name": m.encode(), "arrays": body}
            mapdir += rec["MAP"].pack(sky=info["sky"], firstbank=info["banks"][0],
                                      numbanks=len(info["banks"]), **vals)
        parts = [("PLAYPAL", self.playpal444, 14), ("INVULMAP", self.invulmap, 1),
                 ("MAPDIR", bytes(mapdir), nslots), ("TEXDIR", self.texdir, len(self.tex_names)),
                 ("FLATDIR", self.flatdir, len(self.flats)),
                 ("SPRDEF", self.sprdef, len(self.sprdefs)),
                 ("SPRFRAME", self.sprframe, len(self.sprframes)),
                 ("SPRLUMP", self.sprlump, len(self.sprlumps)),
                 ("UIDIR", self.uidir, len(self.uipics)),
                 ("ANIMS", bytes(self.anims), len(self.anim_seqs)),
                 ("SWITCHES", self.switchtab, len(self.switches)),
                 ("ENDOOM", self.endoom, 1)]
        addr = BANK_LO
        self.dir_layout = {}
        for name, data, count in parts:
            if addr + len(data) > BANK_HI:
                raise ValueError("the directory bank overflows")
            self.banks.put(self.dir_bank, addr, data)
            self.dir_layout[name] = dict(addr=addr, length=len(data), count=count)
            addr += len(data)

    # --- output ---------------------------------------------------------
    def region_list(self):
        """[(region, its Banks, bank numbers)] in load order."""
        regions = [("DIR", self.banks, [self.dir_bank]), ("GFX", self.banks, self.gfx_banks)]
        for m in self.requested:
            if m in self.maps:
                regions.append((m, self.map_images[m], self.maps[m]["banks"]))
        return regions

    def data_files(self):
        """[(file name, region, bytes, segments)] of the whole conversion."""
        out = []
        for region, images, banks in self.region_list():
            segs = images.segments(banks)
            pending = [(b, a, images.image[b][a:a + n]) for b, a, n in segs]
            num = 1
            while pending:
                entries, body = [], bytearray()
                room = FILE_MAX - FILE_HEADER
                while pending and room > 0 and len(entries) < FILE_MAX_SEGS:
                    b, a, data = pending[0]
                    take = min(len(data), room)
                    entries.append((b, a, take))
                    body += data[:take]
                    room -= take
                    if take == len(data):
                        pending.pop(0)
                    else:
                        pending[0] = (b, a + take, data[take:])
                head = bytearray(FILE_MAGIC + bytes((FILE_VERSION, len(entries), 0, 0)))
                for b, a, n in entries:
                    head += RECORDS["FILESEG"].pack(bank=b, addr=a, length=n)
                head += bytes(FILE_HEADER - len(head))
                out.append((f"{region}.{num}", region, bytes(head + body), entries))
                num += 1
        return out

    def write(self, outdir: Path, preview=True):
        outdir.mkdir(parents=True, exist_ok=True)
        for old in outdir.glob("*.[0-9]*"):
            if re.fullmatch(r"(DIR|GFX|E\dM\d)\.\d+", old.name):
                old.unlink()
        files = self.data_files()
        for name, _, data, _ in files:
            (outdir / name).write_bytes(data)
        manifest = self.manifest(files)
        (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        (outdir / "doomdata.inc").write_text(self.include_asm(files))
        (outdir / "doomdata.h").write_text(self.include_c(files))
        if preview:
            write_preview(self, outdir / "preview")
        self.log(f"wrote {len(files)} data files to {outdir}")
        return manifest

    def manifest(self, files):
        gfx_bytes = {}
        for o in self.gfx_objects:
            gfx_bytes[o.kind] = gfx_bytes.get(o.kind, 0) + len(o.data)
        nbanks = self.last_bank - self.first_bank + 1
        return {
            "format": 1,
            "wad": {"file": self.wad.path.name, "sha256": self.wad_sha256},
            "banks": {"first": self.first_bank, "last": self.last_bank, "count": nbanks,
                      "directory": self.dir_bank, "graphics": self.gfx_banks,
                      "used": {f"{r}:{b}": imgs.top[b] - BANK_LO
                               for r, imgs, bl in self.region_list() for b in bl},
                      "maps_shared": self.shared, "maps_first": self.map_first_bank,
                      "fits_4mb": self.last_bank <= 63, "fits_8mb": self.last_bank <= 127},
            "files": [{"name": n, "region": r, "size": len(d),
                       "segments": [[b, a, l] for b, a, l in e]} for n, r, d, e in files],
            "directory": {k: dict(v) for k, v in self.dir_layout.items()},
            "colormaps": {"addr": COLORMAP_ADDR, "count": NUM_COLORMAPS, "data": GFX_DATA},
            "textures": [{"index": i, "name": n,
                          **({} if i == 0 else {
                              "bank": self.textures[i]["obj"].bank,
                              "addr": self.textures[i]["obj"].addr,
                              "width": self.textures[i]["W"], "height": self.textures[i]["H"],
                              "half": [self.textures[i]["w0"], self.textures[i]["h0"]],
                              "masked": self.textures[i]["masked"]})}
                         for i, n in enumerate(self.tex_names)],
            "flats": [{"index": i, "name": f["name"], "bank": f["obj"].bank, "addr": f["obj"].addr}
                      for i, f in enumerate(self.flats)],
            "sky_flat": self.flatindex.get("F_SKY1", NONE16),
            "skies": {str(e): self.texindex.get(s, 0) for e, s in self.skies.items()},
            "sprites": [{"index": i, "name": s, "firstframe": self.sprdefs[i][0],
                         "numframes": self.sprdefs[i][1]} for i, s in enumerate(self.sprite_names)],
            "sprites_missing": self.sprites_missing,
            "sprite_lumps": [{"index": i, "name": s["name"], "bank": s["obj"].bank,
                              "addr": s["obj"].addr, "size": len(s["obj"].data)}
                             for i, s in enumerate(self.sprlumps)],
            "ui": [{"index": i, "name": u["name"], "bank": u["obj"].bank, "addr": u["obj"].addr,
                    "width": u["width"], "height": u["height"]} for i, u in enumerate(self.uipics)],
            "anims": [{"kind": "texture" if k else "flat", "frames": f} for k, f in self.anim_seqs],
            "switches": [[self.tex_names[a], self.tex_names[b]] for a, b in self.switches],
            "maps": {m: {"slot": v["slot"], "banks": v["banks"], "sky": v["sky"],
                         "counts": v["counts"], "bytes": v["bytes"], "arrays": v["arrays"]}
                     for m, v in self.maps.items()},
            "skipped": self.skipped,
            "records": {t: {"size": r.size, "fields": [[n, ty, o] for n, ty, o, _ in r.fields]}
                        for t, r in RECORDS.items()},
            "limits": LIMITS,
            "stats": {"banks": nbanks, "graphics_banks": len(self.gfx_banks),
                      "graphics_bytes": gfx_bytes,
                      "map_banks": {m: len(v["banks"]) for m, v in self.maps.items()},
                      "textures": len(self.tex_names) - 1, "flats": len(self.flats),
                      "sprites": len(self.sprite_names), "sprite_lumps": len(self.sprlumps),
                      "sprite_frames": len(self.sprframes), "ui_pictures": len(self.uipics),
                      "data_bytes": sum(len(d) for _, _, d, _ in files)},
        }

    # --- include files -----------------------------------------------------
    def constants(self, files):
        """[(name, value, comment)] shared by doomdata.inc and doomdata.h."""
        c = []
        add = lambda n, v, cm="": c.append((n, v, cm))
        add("DD_FIRST_BANK", self.first_bank, "first bank used by the data")
        add("DD_LAST_BANK", self.last_bank, "last bank used by the data")
        add("DD_DIR_BANK", self.dir_bank, "the directory bank")
        add("DD_GFX_FIRST_BANK", self.gfx_banks[0])
        add("DD_GFX_NUM_BANKS", len(self.gfx_banks))
        add("DD_MAP_FIRST_BANK", self.map_first_bank, "first bank of the level data")
        add("DD_MAP_BANKS_SHARED", int(self.shared), "1: every map at the same banks")
        add("DD_COLORMAPS", COLORMAP_ADDR, "16 colormaps in every graphics bank")
        add("DD_NUM_COLORMAPS", NUM_COLORMAPS)
        add("DD_GFX_DATA", GFX_DATA)
        add("DD_TRANSPARENT", TRANSPARENT)
        add("DD_ANIM_TICS", ANIM_TICS)
        add("DD_SPR_NOLUMP", SPR_NOLUMP)
        for k, v in self.dir_layout.items():
            add(f"DD_{k}", v["addr"])
        add("DD_NUM_PALETTES", 14)
        add("DD_NUM_MAPSLOTS", self.dir_layout["MAPDIR"]["count"])
        add("DD_NUM_TEXTURES", len(self.tex_names), "including 0 = none")
        add("DD_NUM_FLATS", len(self.flats))
        add("DD_SKYFLAT", self.flatindex.get("F_SKY1", NONE16))
        add("DD_NUM_SPRITES", len(self.sprite_names))
        add("DD_NUM_SPRFRAMES", len(self.sprframes))
        add("DD_NUM_SPRLUMPS", len(self.sprlumps))
        add("DD_NUM_UIPICS", len(self.uipics))
        add("DD_NUM_ANIMS", len(self.anim_seqs))
        add("DD_NUM_SWITCHES", len(self.switches))
        add("DD_NUM_FILES", len(files))
        for flag, v in (("TEXF_MASKED", 1), ("TEXF_SKY", 2), ("TEXF_ANIM", 4),
                        ("TEXF_SWITCH", 8), ("FLATF_SKY", 1), ("FLATF_ANIM", 2)):
            add(flag, v)
        for i, a in enumerate(MAP_ARRAYS):
            add(f"MAPARR_{a}", i, "DESC index in a MAP record")
        for tag, r in RECORDS.items():
            add(f"{tag}_SIZE", r.size)
            for n, _, o, _ in r.fields:
                add(f"{tag}_{n.upper()}", o)
        for i, s in enumerate(self.sprite_names):
            add(f"SPR_{s}", i)
        for i, u in enumerate(self.uipics):
            add(f"UI_{u['name']}", i)
        return c

    def include_asm(self, files):
        out = ["; doomdata.inc: generated by tools/wad2a2.py from "
               f"{self.wad.path.name} (sha256 {self.wad_sha256[:16]}...). Do not edit.",
               "; Layouts: docs/DESIGN.md section 6 and the converter's docstring.", ""]
        for n, v, cm in self.constants(files):
            val = f"${v:04X}" if v > 255 else str(v)
            out.append(f"{n:24s} = {val}" + (f"    ; {cm}" if cm else ""))
        out += ["", "; the data files, in load order: length-prefixed names, 0 ends",
                ".macro DD_FILE_TABLE"]
        for n, _, _, _ in files:
            out.append(f'        .byte {len(n)}, "{n}"')
        out += ["        .byte 0", ".endmacro", ""]
        return "\n".join(out)

    def include_c(self, files):
        out = ["/* doomdata.h: generated by tools/wad2a2.py from "
               f"{self.wad.path.name} (sha256 {self.wad_sha256[:16]}...). Do not edit.",
               " * Layouts: docs/DESIGN.md section 6 and the converter's docstring. */",
               "#ifndef DOOMDATA_H", "#define DOOMDATA_H", ""]
        for n, v, cm in self.constants(files):
            out.append(f"#define {n:24s} {v}" + (f"  /* {cm} */" if cm else ""))
        out.append("")
        for tag, r in RECORDS.items():
            if tag in ("FILESEG",):
                continue
            out.append(f"/* {r.doc} */")
            out.append("typedef struct {")
            for n, ty, o, cm in r.fields:
                ctype = type_info(ty)[2]
                arr = "" if ty in TYPES else f"[{type_info(ty)[1]}]"
                out.append(f"    {ctype} {n}{arr};" + (f"  /* {cm} */" if cm else ""))
            if r.pad:
                out.append(f"    unsigned char pad[{r.pad}];")
            out.append(f"}} {tag.lower()}_t;")
            out.append("")
        out.append("#endif")
        return "\n".join(out) + "\n"


# --- reading the output back ------------------------------------------------------------

def parse_data_file(raw: bytes):
    """A data file -> [(bank, addr, bytes)]."""
    if raw[:4] != FILE_MAGIC or raw[4] != FILE_VERSION:
        raise ValueError("not a data file")
    n = raw[5]
    pos = FILE_HEADER
    out = []
    for i in range(n):
        b, a, l = struct.unpack_from("<BHH", raw, 8 + 5 * i)
        out.append((b, a, raw[pos:pos + l]))
        pos += l
    if pos != len(raw):
        raise ValueError("data file length does not match its header")
    return out


def load_banks(outdir, regions=None) -> dict:
    """Rebuild the bank images (bank -> bytearray(65536)) from the files of
    the given regions ("DIR", "GFX", map names; default all, which with
    shared map banks would overlay the maps: pass one map then)."""
    outdir = Path(outdir)
    manifest = json.loads((outdir / "manifest.json").read_text())
    banks = {}
    for f in manifest["files"]:
        if regions is not None and f["region"] not in regions:
            continue
        for b, a, data in parse_data_file((outdir / f["name"]).read_bytes()):
            img = banks.setdefault(b, bytearray(0x10000))
            img[a:a + len(data)] = data
    return banks


def read_record(banks, tag, bank, addr, index=0):
    r = RECORDS[tag]
    return r.unpack(banks[bank], addr + index * r.size)


def decode_texture(banks, dir_bank, texdir, index):
    """TEXDIR entry -> (record, stored columns [W][H])."""
    t = read_record(banks, "TEX", dir_bank, texdir, index)
    W, H = t["wmask"] + 1, t["hmask"] + 1
    img = banks[t["bank"]]
    cols = [list(img[t["addr"] + (x << t["log2h"]):t["addr"] + (x << t["log2h"]) + H])
            for x in range(W)]
    return t, cols


def decode_sprite(img, addr):
    """Sprite patch at addr -> (width, height, left, top, columns with None)."""
    w, h, left, top = struct.unpack_from("<BBhh", img, addr)
    cols = []
    for x in range(w):
        col = [None] * h
        p = addr + struct.unpack_from("<H", img, addr + 6 + 2 * x)[0]
        while img[p] != 0xFF:
            y, n = img[p], img[p + 1]
            col[y:y + n] = list(img[p + 2:p + 2 + n])
            p += 2 + n
        cols.append(col)
    return w, h, left, top, cols


# --- preview -----------------------------------------------------------------------------

def write_preview(conv: Conversion, pdir: Path):
    from PIL import Image
    pdir.mkdir(parents=True, exist_ok=True)
    for old in pdir.glob("*.png"):
        old.unlink()
    img = conv.banks.image
    rgb = conv.pal.rgb
    bg = (40, 40, 48)

    def to_image(cols, w, h):
        im = Image.new("RGB", (max(w, 1), max(h, 1)), bg)
        px = im.load()
        for x in range(w):
            for y in range(h):
                v = cols[x][y]
                if v is not None and v != TRANSPARENT:
                    px[x, y] = rgb[v]
        return im

    def sample(seq, n):
        if len(seq) <= n:
            return list(range(len(seq)))
        return [round(i * (len(seq) - 1) / (n - 1)) for i in range(n)]

    tiles = []
    dl = conv.dir_layout
    for i in sample(range(1, len(conv.tex_names)), 24):
        idx = i + 1
        t, cols = decode_texture(img, conv.dir_bank, dl["TEXDIR"]["addr"], idx)
        im = to_image(cols, t["wmask"] + 1, t["hmask"] + 1)
        name = conv.tex_names[idx]
        im.save(pdir / f"tex_{name}.png")
        tiles.append((name, im))
    for i in sample(conv.flats, 12):
        f = conv.flats[i]
        r = RECORDS["FLAT"].unpack(img[conv.dir_bank], dl["FLATDIR"]["addr"] + 8 * i)
        data = img[r["bank"]][r["addr"]:r["addr"] + 1024]
        cols = [[data[32 * y + x] for y in range(32)] for x in range(32)]
        im = to_image(cols, 32, 32)
        im.save(pdir / f"flat_{f['name']}.png")
        tiles.append((f["name"], im))
    for i in sample(conv.sprlumps, 24):
        s = conv.sprlumps[i]
        r = RECORDS["SPRLUMP"].unpack(img[conv.dir_bank], dl["SPRLUMP"]["addr"] + 8 * i)
        w, h, _, _, cols = decode_sprite(img[r["bank"]], r["addr"])
        im = to_image(cols, w, h)
        im.save(pdir / f"spr_{s['name']}.png")
        tiles.append((s["name"], im))
    for name in ("STBAR", "TITLEPIC", "STFST01", "M_DOOM"):
        u = next((k for k, u in enumerate(conv.uipics) if u["name"] == name), None)
        if u is None:
            continue
        r = RECORDS["UIPIC"].unpack(img[conv.dir_bank], dl["UIDIR"]["addr"] + 12 * u)
        W, H = r["width"], r["height"]
        data = img[r["bank"]][r["addr"]:r["addr"] + W * H]
        cols = [[data[W * y + x] for y in range(H)] for x in range(W)]
        im = to_image(cols, W, H).resize((W, 2 * H), Image.NEAREST)   # SHR aspect
        im.save(pdir / f"ui_{name}.png")
        tiles.append((name, im))
    # contact sheet: 3x, rows of tiles
    scale, pad, width = 3, 6, 1200
    x = y = pad
    rowh = 0
    placed = []
    for name, im in tiles:
        w, h = im.width * scale, im.height * scale
        if w > width - 2 * pad:
            s = (width - 2 * pad) / w
            w, h = int(w * s), int(h * s)
        if x + w + pad > width:
            x, y, rowh = pad, y + rowh + pad, 0
        placed.append((im, x, y, w, h))
        x += w + pad
        rowh = max(rowh, h)
    sheet = Image.new("RGB", (width, y + rowh + pad), (16, 16, 20))
    for im, x, y, w, h in placed:
        sheet.paste(im.resize((w, h), Image.NEAREST), (x, y))
    sheet.save(pdir / "contact_sheet.png")


# --- command line -----------------------------------------------------------------------

def layouts_markdown():
    out = []
    for tag, r in RECORDS.items():
        out.append(f"**{tag}** ({r.size} bytes): {r.doc}.\n")
        out.append("| Offset | Field | Type | Notes |")
        out.append("|---|---|---|---|")
        for n, ty, o, cm in r.fields:
            out.append(f"| +{o} | `{n}` | {ty} | {cm} |")
        if r.pad:
            out.append(f"| +{r.size - r.pad} | (padding) | {r.pad} bytes | zero |")
        out.append("")
    return "\n".join(out)


def default_wad():
    env = os.environ.get("FREEDOOM_WAD")
    return env or str(PROJECT / "build/wad/freedoom1.wad")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--wad", default=default_wad())
    ap.add_argument("--out", default=str(PROJECT / "build/data"))
    ap.add_argument("--maps", default=",".join(f"E1M{i}" for i in range(1, 10)))
    ap.add_argument("--first-bank", type=int, default=FIRST_BANK)
    ap.add_argument("--shared-map-banks", action="store_true",
                    help="place every map at the same banks (the kernel loads one level at a time)")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--layouts-md", action="store_true", help="print the record tables")
    ap.add_argument("--limit", action="append", default=[], metavar="NAME=VALUE",
                    help="override a per-map limit (see LIMITS), e.g. segs=4096")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)
    if args.layouts_md:
        print(layouts_markdown())
        return 0
    for item in args.limit:
        name, _, value = item.partition("=")
        if name not in LIMITS:
            ap.error(f"unknown limit {name}; known: {', '.join(LIMITS)}")
        LIMITS[name] = int(value, 0)
    maps = [m.strip().upper() for m in args.maps.split(",") if m.strip()]
    conv = Conversion(args.wad, maps, args.first_bank, verbose=not args.quiet,
                      shared_map_banks=args.shared_map_banks)
    man = conv.write(Path(args.out), preview=not args.no_preview)
    st = man["stats"]
    print(f"wad2a2: {len(conv.maps)} maps, banks {conv.first_bank}..{conv.last_bank} "
          f"({st['banks']} banks, {st['graphics_banks']} graphics), "
          f"{len(man['files'])} files, {st['data_bytes']} bytes")
    if conv.skipped:
        for m, why in conv.skipped.items():
            print(f"wad2a2: skipped {m}: {why}")
    if not man["banks"]["fits_4mb"]:
        print("wad2a2: warning: the data needs banks above 63 (more than 4 MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
