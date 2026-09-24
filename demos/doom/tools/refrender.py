#!/usr/bin/env python3
"""The reference renderer: Doom's renderer as the 6502 does it (DESIGN.md 5, 7).

    python3 tools/refrender.py --map E1M1 [--data build/data] --start --out view.png
    python3 tools/refrender.py --map E1M1 --view X Y Z ANGLE [--tic N] [--extralight N]
                               [--shaded] [--no-things] [--no-weapon] [--stats]
    python3 tools/refrender.py --deliverables [--out-dir build/refrender]

This file is the specification of the 6502 renderer (src/render/). It
reads only the converted data (the bank images of tools/wad2a2.py and
the directory addresses of its manifest, the same numbers as
doomdata.inc), renders one view into the 160x84 column-major view buffer
of palette indices, and writes a PNG. Every quantity is an integer of a
stated width and every operation is one the 6502 does exactly: add,
subtract, shift, a table lookup, an exact multiply, an exact division
(truncating toward zero where signed). The 6502 renderer must produce
the same view buffer, byte for byte; tests/test_refrender.py pins it.
The tables are built here (build_tables) and written for ca65 by
tools/gen_tables.py, so both sides use the same numbers by construction.

The algorithm is Doom's (r_bsp, r_segs, r_plane, r_things, r_draw) in
Doom's order; what differs is the arithmetic, reduced for a 65C02:

  - Positions relative to the view are in 1/16 map unit ("sub-units",
    24-bit signed): the game's 16.16 fixed_t shifted right by 12. Map
    data (vertexes, heights) are map units, shifted left by 4 when met.
  - Angles are BAM16 (Doom's angle_t >> 16). Fine angles: 4096 per turn
    (BAM16 >> 4). Sines are Q14 (1.0 = 16384), from a quarter-wave
    table. R_PointToAngle is Doom's octant method with a 1025-entry
    tantoangle table (slope = (small << 10) / big, exact division).
  - Projection: the view is Doom's 320x168 low-detail view halved in both
    directions, so one focal length, 80 pixels, serves columns and rows
    (a row stands for two of Doom's rows, which keeps Doom's aspect).
    centerx = 80, centery = 42, field of view 90 degrees.
  - A wall's scale (pixels per map unit) is 16.16 fixed, clamped to
    [SCALE_MIN, SCALE_MAX] = [1/256, 64] as Doom's; it is exact at both
    ends of a wall range and stepped linearly between them. Its
    reciprocal (texels per pixel) comes from a 256-entry table of the
    9-bit normalised mantissa. The perpendicular distance and the
    texture offset of a wall are dot products with the unit normal and
    direction (two multiplies each) instead of Doom's R_PointToDist.
  - Texture column per screen column: rw_offset - tan(angle) * distance,
    Doom's formula, with a 12-bit-fraction tangent table.
  - Column texel stepping is 8.8 fixed (16-bit adds), started exactly per
    column piece; span stepping is 5.11 fixed per axis for 32x32 flats.
  - Graphics are the converter's half-resolution ones (one texel = two
    map units); colormaps are the 16 stored (Doom's even ones), so a
    Doom colormap number c becomes c >> 1.
  - Every limit (visplanes, drawsegs, openings, vissprites) is a named
    constant and overflowing one degrades the picture, never the program
    (see the constants).

Instrumentation: render() returns counters of the work the 6502 does
(nodes, segs, columns, pixels, spans, multiplies, divisions, ...);
--stats prints them.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wad2a2  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]

# --- the view -------------------------------------------------------------------------
VIEW_W = 160
VIEW_H = 84
CENTERX = 80
CENTERY = 42
PROJ = 80                       # focal length in pixels, both axes
SUBBITS = 4                     # sub-units: 1/16 map unit
VIEWHEIGHT = 41                 # Doom's eye height above the floor (map units)

# --- angles and tables ----------------------------------------------------------------
ANG45, ANG90, ANG180, ANG270 = 0x2000, 0x4000, 0x8000, 0xC000
FINEANGLES = 4096
FINESHIFT = 4                   # BAM16 >> 4
FINEMASK = FINEANGLES - 1
SINEBITS = 14                   # Q14 sines
SINE_ONE = 1 << SINEBITS
SLOPEBITS = 10
SLOPERANGE = 1 << SLOPEBITS     # tantoangle has SLOPERANGE + 1 entries
TANBITS = 12                    # fraction bits of the tangent table
TANHALF = FINEANGLES // 2       # tangent indexes 0..2047 = -90..+90 degrees
FIELDOFVIEW = FINEANGLES // 4   # 90 degrees

# --- walls ------------------------------------------------------------------------------
HEIGHTBITS = 12                 # fraction bits of topfrac/bottomfrac (rows)
HEIGHTUNIT = 1 << HEIGHTBITS
SCALE_MIN = 256                 # 1/256 pixel per map unit (16.16)
SCALE_MAX = 64 << 16
RECIPBITS = 9                   # mantissa bits of the reciprocal table
RECIP_BASE = 1 << (RECIPBITS - 1)   # mantissas 256..511

# --- lighting (Doom's r_main.h, with Doom's scales) ---------------------------------------
LIGHTLEVELS = 16
LIGHTSEGSHIFT = 4
MAXLIGHTSCALE = 48
LIGHTSCALESHIFT = 11            # Doom's 12; our scale is half of Doom's (focal 80, not 160)
MAXLIGHTZ = 128
LIGHTZSHIFT = 8                 # distance in sub-units >> 8 = Doom's distance >> 20
DOOM_COLORMAPS = 32
NUMCOLORMAPS = 16               # stored: Doom's colormaps 0, 2, .., 30
FUZZ_COLORMAP = 3               # Doom's colormap 6

# --- things --------------------------------------------------------------------------------
MINZ = 4 << SUBBITS             # sprites nearer than 4 units are not drawn
FF_FULLBRIGHT = 0x8000
FF_FRAMEMASK = 0x7FFF
MF_SHADOW = 1                   # vissprite flag: drawn with the fuzz effect
BASEYCENTER = 100               # Doom's weapon sprite reference row
WEAPONTOP = 32 << 16            # psprite sy when the weapon is up (16.16)

# --- per-frame limits ------------------------------------------------------------------------
# Measured by --sweep 40 (360 random views inside the E1 maps, limits
# lifted): drawsegs p90 91, max 197; visplanes p90 36, max 76; openings p90
# 878 bytes, max 1,603; vissprites p90 26, max 83; BSP depth max 43. A
# solid-seg list over 160 columns holds at most 80 disjoint ranges plus the
# two sentinels, so MAXSOLIDSEGS cannot overflow. Overflowing any other limit
# degrades the picture, never the program:
MAXSOLIDSEGS = VIEW_W // 2 + 2
MAXDRAWSEGS = 160               # beyond: the wall is drawn but not recorded (it clips no sprite)
MAXVISPLANES = 128              # beyond: that plane piece is drawn flat-shaded at once
MAXOPENINGS = 2048              # bytes; beyond: the drawseg keeps no clip arrays, no masked middle
MAXVISSPRITES = 96              # beyond: further things are not drawn
MAXBSPDEPTH = 64                # the node stack; a deeper subtree is not visited

MAXINT = 0x7FFFFFFF
MININT = -0x80000000

# linedef flags (Doom)
ML_TWOSIDED = 4
ML_DONTPEGTOP = 8
ML_DONTPEGBOTTOM = 16

SIL_NONE, SIL_BOTTOM, SIL_TOP, SIL_BOTH = 0, 1, 2, 3
NF_SUBSECTOR = 0x8000
NONE16 = 0xFFFF
TRANSPARENT = wad2a2.TRANSPARENT


# --- integer helpers ---------------------------------------------------------------------------

def s32(v):
    """Wrap to a signed 32-bit value (the width of the 6502's accumulators)."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def div_trunc(a, b):
    """Signed division truncating toward zero (sign-magnitude, as the 6502)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


# --- tables ------------------------------------------------------------------------------------

class Tables:
    """Every table the renderer reads. Built once from floating point, then
    everything else is integer; tools/gen_tables.py writes these arrays."""

    def __init__(self):
        # quarter-wave sine, Q14, entries 0..1024 (sin of i * 2pi / 4096)
        q = FINEANGLES // 4
        self.sine_q = [round(math.sin(i * 2 * math.pi / FINEANGLES) * SINE_ONE)
                       for i in range(q + 1)]
        # tantoangle: BAM16 of atan(i / 1024), i = 0..1024
        self.tantoangle = [round(math.atan(i / SLOPERANGE) * 32768 / math.pi)
                           for i in range(SLOPERANGE + 1)]
        # tangent, positive half: tan((i + 0.5) * 2pi / 4096) for fine index
        # 1024 + i (i = 0..1023), 12 fraction bits; the negative half by
        # symmetry: tan[2047 - a] = -tan[a]
        self.tan_pos = [round(math.tan((i + 0.5) * 2 * math.pi / FINEANGLES) * (1 << TANBITS))
                        for i in range(TANHALF // 2)]
        assert max(self.tan_pos) < 1 << 23
        # reciprocal: texels per pixel (16.16) for a scale with mantissa m
        # (256..511): 2^31 / (m + 0.5), 24 bits
        self.recip = [round((1 << 31) / (m + 0.5)) for m in range(RECIP_BASE, 2 * RECIP_BASE)]
        assert max(self.recip) < 1 << 24
        self._texture_mapping()
        # 1/cos of each column's angle, Q14
        self.distscale = [(1 << (2 * SINEBITS)) // abs(self.cos(self.xtoviewangle[x] >> FINESHIFT))
                          for x in range(VIEW_W)]
        # rows: 80 / |y - 41.5| in 8.8
        self.yslope = [(PROJ << 9) // abs(2 * (y - CENTERY) + 1) for y in range(VIEW_H)]
        self._lights()
        # Doom's fuzz offsets (+-1 row: +-1 byte in the column-major buffer)
        F, B = 1, -1
        self.fuzzoffset = [F, B, F, B, F, F, B, F, F, B, F, F, F, B, F, F, F, B, B, B,
                           F, B, B, B, F, F, F, F, B, F, B, F, F, B, B, F, F, B, B, B,
                           B, F, F, F, F, B, F, F, B, F]
        # 8x8 multiply by quarter squares: sqr[i] = i*i/4 (i = 0..511),
        # nsqr[i] = (i-255)^2/4: a*b = sqr[a+b] - nsqr[a-b+255]
        self.mul_sqr = [i * i // 4 for i in range(512)]
        self.mul_nsqr = [(i - 255) * (i - 255) // 4 for i in range(512)]

    def _texture_mapping(self):
        """Doom's R_InitTextureMapping for 160 columns and 4096 fine angles."""
        def tan16(i):   # Doom's finetangent (16.16) at our fine index 0..2047
            return int(math.tan((i - TANHALF // 2 + 0.5) * 2 * math.pi / FINEANGLES) * 65536)
        focal = ((CENTERX << 16) << 16) // tan16(TANHALF // 2 + FIELDOFVIEW // 2)
        vatx = []
        for i in range(TANHALF):
            t16 = tan16(i)
            if t16 > 2 * 65536:
                t = -1
            elif t16 < -2 * 65536:
                t = VIEW_W + 1
            else:
                t = (t16 * focal) >> 16
                t = ((CENTERX << 16) - t + 65535) >> 16
                t = max(-1, min(VIEW_W + 1, t))
            vatx.append(t)
        self.xtoviewangle = []
        for x in range(VIEW_W + 1):
            i = 0
            while vatx[i] > x:
                i += 1
            self.xtoviewangle.append(((i << FINESHIFT) - ANG90) & 0xFFFF)
        vatx = [0 if t == -1 else VIEW_W if t == VIEW_W + 1 else t for t in vatx]
        self.clipangle = self.xtoviewangle[0]
        # only the indexes reachable after clipping to +-clipangle are kept
        self.vatx_first = ((ANG90 - self.clipangle) & 0xFFFF) >> FINESHIFT
        last = ((ANG90 + self.clipangle) & 0xFFFF) >> FINESHIFT
        self.viewangletox = vatx[self.vatx_first:last + 1]

    def _lights(self):
        """scalelight[16][48] and zlight[16][128] as stored colormap numbers."""
        self.scalelight, self.zlight = [], []
        for i in range(LIGHTLEVELS):
            startmap = ((LIGHTLEVELS - 1 - i) * 2) * DOOM_COLORMAPS // LIGHTLEVELS
            row = []
            for j in range(MAXLIGHTSCALE):
                level = startmap - j * 320 // 320 // 2
                row.append(max(0, min(DOOM_COLORMAPS - 1, level)) >> 1)
            self.scalelight.append(row)
            row = []
            for j in range(MAXLIGHTZ):
                scale = ((160 << 32) // ((j + 1) << 20)) >> 12
                level = startmap - scale // 2
                row.append(max(0, min(DOOM_COLORMAPS - 1, level)) >> 1)
            self.zlight.append(row)

    # the lookups, as the 6502 does them
    def sin(self, fine):
        fine &= FINEMASK
        q, i = fine >> 10, fine & 1023
        if q == 0:
            return self.sine_q[i]
        if q == 1:
            return self.sine_q[1024 - i]
        if q == 2:
            return -self.sine_q[i]
        return -self.sine_q[1024 - i]

    def cos(self, fine):
        return self.sin(fine + FINEANGLES // 4)

    def sin_bam(self, a):
        """Sine of a BAM16 angle, Q14: the fine table interpolated linearly
        with the angle's low 4 bits (one small multiply, (s1 - s0) * f >> 4)."""
        i, f = (a & 0xFFFF) >> FINESHIFT, a & 15
        s0 = self.sin(i)
        return s0 + (((self.sin(i + 1) - s0) * f) >> FINESHIFT)

    def cos_bam(self, a):
        return self.sin_bam(a + ANG90)

    def tan(self, a):
        """Tangent at fine index a (0..2047 = -90..+90 degrees), 12 fraction bits."""
        if a >= TANHALF // 2:
            return self.tan_pos[a - TANHALF // 2]
        return -self.tan_pos[TANHALF // 2 - 1 - a]

    def vatx(self, angle):
        """viewangletox for a BAM16 angle already clipped to +-clipangle."""
        return self.viewangletox[(((angle + ANG90) & 0xFFFF) >> FINESHIFT) - self.vatx_first]

    def iscale(self, scale):
        """Texels per pixel (16.16) for a scale (pixels per map unit, 16.16):
        2^31 / scale by the table, the scale normalised to 9 bits."""
        n = scale.bit_length() - RECIPBITS
        if n >= 0:
            return self.recip[(scale >> n) - RECIP_BASE] >> n
        return self.recip[(scale << -n) - RECIP_BASE] << -n

    def sizes(self):
        """name -> (entries, bytes per entry) of the tables the 6502 keeps."""
        return {
            "sine": (len(self.sine_q), 2), "tantoangle": (len(self.tantoangle), 2),
            "tangent": (len(self.tan_pos), 3), "recip": (len(self.recip), 3),
            "xtoviewangle": (len(self.xtoviewangle), 2),
            "viewangletox": (len(self.viewangletox), 1),
            "distscale": (len(self.distscale), 2), "yslope": (len(self.yslope), 2),
            "scalelight": (LIGHTLEVELS * MAXLIGHTSCALE, 1),
            "zlight": (LIGHTLEVELS * MAXLIGHTZ, 1),
            "fuzzoffset": (len(self.fuzzoffset), 1),
            "mul_sqr": (512, 2), "mul_nsqr": (512, 2),
            "coladdr": (VIEW_W, 2),
        }


_TABLES = None


def tables() -> Tables:
    global _TABLES
    if _TABLES is None:
        _TABLES = Tables()
    return _TABLES


# --- the converted data -----------------------------------------------------------------------

class Rec:
    """A record as attributes (fields of wad2a2.RECORDS)."""

    def __init__(self, d):
        self.__dict__.update(d)


class GameData:
    """The directory bank, the graphics banks and one map's banks, read only
    as the 6502 reads them: records at the directory addresses, map arrays
    through their far descriptors."""

    def __init__(self, datadir, mapname):
        datadir = Path(datadir)
        self.manifest = json.loads((datadir / "manifest.json").read_text())
        self.banks = wad2a2.load_banks(datadir, ["DIR", "GFX", mapname])
        m = self.manifest
        self.dir_bank = m["banks"]["directory"]
        d = m["directory"]
        rd = lambda tag, name, i: Rec(wad2a2.read_record(self.banks, tag, self.dir_bank,
                                                         d[name]["addr"], i))
        self.textures = [rd("TEX", "TEXDIR", i) for i in range(d["TEXDIR"]["count"])]
        self.flats = [rd("FLAT", "FLATDIR", i) for i in range(d["FLATDIR"]["count"])]
        self.sprdefs = [rd("SPRDEF", "SPRDEF", i) for i in range(d["SPRDEF"]["count"])]
        self.sprframes = [rd("SPRFRAME", "SPRFRAME", i) for i in range(d["SPRFRAME"]["count"])]
        self.sprlumps = [rd("SPRLUMP", "SPRLUMP", i) for i in range(d["SPRLUMP"]["count"])]
        self.anims = [rd("ANIM", "ANIMS", i) for i in range(d["ANIMS"]["count"])]
        self.sprite_index = {s["name"]: s["index"] for s in m["sprites"]}
        pal = self.banks[self.dir_bank][d["PLAYPAL"]["addr"]:d["PLAYPAL"]["addr"] + 512]
        self.rgb = [((pal[2 * i + 1] & 15) * 16, (pal[2 * i] >> 4) * 16, (pal[2 * i] & 15) * 16)
                    for i in range(256)]
        self.skyflat = next(i for i, f in enumerate(self.flats) if f.flags & wad2a2.FLATF_SKY)
        # the map, from MAPDIR
        ep, mp = int(mapname[1]), int(mapname[3])
        slot = 9 * (ep - 1) + mp - 1
        rec = wad2a2.read_record(self.banks, "MAP", self.dir_bank, d["MAPDIR"]["addr"], slot)
        if rec["name"].rstrip(b"\0").decode() != mapname:
            raise ValueError(f"{mapname} is not in the data")
        self.sky = rec["sky"]
        descs = [wad2a2.RECORDS["DESC"].unpack(rec["arrays"], 8 * k)
                 for k in range(len(wad2a2.MAP_ARRAYS))]
        self.arrays = dict(zip(wad2a2.MAP_ARRAYS, descs))
        L = {}
        for name, rtag in wad2a2.ARRAY_RECORD.items():
            L[name] = [Rec(self.far_record(rtag, self.arrays[name], i))
                       for i in range(self.arrays[name]["count"])]
        self.vertexes, self.segs = L["VERTEXES"], L["SEGS"]
        self.subsectors, self.nodes = L["SSECTORS"], L["NODES"]
        self.sides, self.lines, self.sectors = L["SIDEDEFS"], L["LINEDEFS"], L["SECTORS"]
        self.things = L["THINGS"]

    def far_record(self, tag, desc, i):
        k = desc["log2"]
        bank = desc["bank"] + (i >> k)
        addr = desc["addr"] + (i & ((1 << k) - 1)) * desc["elsize"]
        return wad2a2.read_record(self.banks, tag, bank, addr)

    # graphics
    def colormap(self, bank, k):
        base = wad2a2.COLORMAP_ADDR + 256 * k
        return self.banks[bank][base:base + 256]

    def sprite_patch(self, lump):
        """(bank image, addr, width, height, left, top) of a SPRLUMP entry."""
        s = self.sprlumps[lump]
        img = self.banks[s.bank]
        w, h, left, top = struct.unpack_from("<BBhh", img, s.addr)
        return img, s.addr, w, h, left, top


# --- the renderer ------------------------------------------------------------------------------

class View:
    """The eye: x, y, z in sub-units (1/16 map unit), angle BAM16."""

    def __init__(self, x, y, z, angle):
        self.x, self.y, self.z, self.angle = int(x), int(y), int(z), int(angle) & 0xFFFF

    @classmethod
    def from_units(cls, x, y, z, angle_deg):
        return cls(round(x * 16), round(y * 16), round(z * 16),
                   round(angle_deg * 65536 / 360))

    @classmethod
    def from_fixed(cls, x, y, z, angle32):
        """From the game's 16.16 fixed_t and 32-bit angle_t."""
        return cls(x >> 12, y >> 12, z >> 12, angle32 >> 16)

    def __repr__(self):
        return (f"View({self.x / 16:.2f}, {self.y / 16:.2f}, {self.z / 16:.2f}, "
                f"{self.angle * 360 / 65536:.1f} deg)")


class Thing:
    """A thing to draw: position in sub-units, angle BAM16, sprite (SPR_
    number), frame (bit 15 = full bright), flags (MF_SHADOW)."""
    __slots__ = ("x", "y", "z", "angle", "sprite", "frame", "flags", "sector")

    def __init__(self, x, y, z, angle, sprite, frame, flags=0):
        self.x, self.y, self.z = int(x), int(y), int(z)
        self.angle, self.sprite, self.frame, self.flags = angle & 0xFFFF, sprite, frame, flags
        self.sector = None


class PSprite:
    """A weapon layer: sprite, frame, sx, sy in Doom's 320x200 16.16."""

    def __init__(self, sprite, frame, sx=1 << 16, sy=WEAPONTOP):
        self.sprite, self.frame, self.sx, self.sy = sprite, frame, sx, sy


class Visplane:
    __slots__ = ("height", "picnum", "light", "minx", "maxx", "top", "bottom", "overflow")

    def __init__(self, height, picnum, light, overflow=False):
        self.height, self.picnum, self.light = height, picnum, light
        self.minx, self.maxx = VIEW_W, -1
        # index x + 1 (columns -1 .. 160): 0xFF = unused, bottom 0
        self.top = bytearray([0xFF]) * (VIEW_W + 2)
        self.bottom = bytearray(VIEW_W + 2)
        self.overflow = overflow


class Drawseg:
    __slots__ = ("seg", "x1", "x2", "scale1", "scale2", "scalestep", "silhouette",
                 "bsilheight", "tsilheight", "sprtopclip", "sprbottomclip", "maskedtexturecol")


class Vissprite:
    __slots__ = ("x1", "x2", "gx", "gy", "gz", "gzt", "startfrac", "scale", "xiscale",
                 "texturemid", "lump", "colormap", "flags", "flip")


class Stats(dict):
    def add(self, key, n=1):
        self[key] = self.get(key, 0) + n


class Renderer:
    """One frame: render(view) -> (view buffer, stats). The buffer is a
    bytearray of 160*84, column x at 84*x (DESIGN.md 3)."""

    def __init__(self, data: GameData, shaded=False, check_writes=False, masked=True):
        self.d = data
        self.t = tables()
        self.shaded = shaded                # planes as flat-shaded columns
        self.check_writes = check_writes    # count writes per pixel (tests)
        self.masked = masked                # False: skip sprites and masked middles (tests)

    # ---- entry ----
    def render(self, view: View, things=(), psprites=(), tic=0, extralight=0,
               fixedcolormap=None):
        d, t = self.d, self.t
        self.view = view
        self.vx, self.vy, self.vz, self.va = view.x, view.y, view.z, view.angle
        self.viewcos = t.cos_bam(self.va)
        self.viewsin = t.sin_bam(self.va)
        # span steps per pixel (5.11 flat texels) are distance * base >> 15:
        # Doom's basexscale = cos(viewangle - 90) / centerx, baseyscale =
        # -sin(viewangle - 90) / centerx, here Q14 * 8/5 (= 2^15 * 64 / 80 / 2^14)
        a = (self.va - ANG90) & 0xFFFF
        self.basexscale = div_trunc(t.cos_bam(a) * 8, 5)
        self.baseyscale = -div_trunc(t.sin_bam(a) * 8, 5)
        self.extralight = extralight
        self.fixedcolormap = fixedcolormap
        self.stats = st = Stats()
        self.buf = bytearray(VIEW_W * VIEW_H)
        self.writes = bytearray(VIEW_W * VIEW_H) if self.check_writes else None
        self.fuzzpos = 0
        self._animate(tic)
        # clip state
        self.solidsegs = [[-0x7FFF, -1], [VIEW_W, 0x7FFF]]
        self.ceilingclip = [-1] * VIEW_W
        self.floorclip = [VIEW_H] * VIEW_W
        self.drawsegs = []
        self.openings = 0
        self.visplanes = []
        self.vissprites = []
        self.sector_things = {}
        for th in things:
            if th.sector is None:
                th.sector = self.point_sector(th.x, th.y)
            self.sector_things.setdefault(th.sector, []).append(th)
        self.sectors_done = set()
        self.cached = [None] * VIEW_H            # R_MapPlane's per-row cache
        self.vertex_angles = {}                  # per-frame vertex angle cache (counted)
        # the frame
        self.depth = 0
        self.render_bsp(len(d.nodes) - 1 if d.nodes else NF_SUBSECTOR)
        self.draw_planes()
        if self.writes is not None:
            self.plane_writes = bytes(self.writes)
        if self.masked:
            self.draw_masked()
        for psp in psprites:
            self.draw_psprite(psp)
        st["drawsegs"] = len(self.drawsegs)
        st["visplanes"] = len(self.visplanes)
        st["openings"] = self.openings
        st["vissprites"] = len(self.vissprites)
        return self.buf, st

    def _animate(self, tic):
        """Texture and flat translation for game tic `tic` (8 tics a frame)."""
        d = self.d
        self.textrans = list(range(len(d.textures)))
        self.flattrans = list(range(len(d.flats)))
        for a in d.anims:
            tr = self.flattrans if a.kind == 0 else self.textrans
            for i in range(a.first, a.first + a.count):
                tr[i] = a.first + ((tic // wad2a2.ANIM_TICS + i - a.first) % a.count)

    # ---- geometry ----
    def point_to_angle(self, x, y):
        """R_PointToAngle of a vector in sub-units -> BAM16 (octants + tantoangle)."""
        self.stats.add("div_slope")
        ta = self.t.tantoangle

        def slope(num, den):
            return SLOPERANGE if den == 0 else min((num << SLOPEBITS) // den, SLOPERANGE)

        if x == 0 and y == 0:
            return 0
        if x >= 0:
            if y >= 0:
                if x > y:
                    return ta[slope(y, x)]
                return (ANG90 - 1 - ta[slope(x, y)]) & 0xFFFF
            y = -y
            if x > y:
                return (-ta[slope(y, x)]) & 0xFFFF
            return (ANG270 + ta[slope(x, y)]) & 0xFFFF
        x = -x
        if y >= 0:
            if x > y:
                return (ANG180 - 1 - ta[slope(y, x)]) & 0xFFFF
            return (ANG90 + ta[slope(x, y)]) & 0xFFFF
        y = -y
        if x > y:
            return (ANG180 + ta[slope(y, x)]) & 0xFFFF
        return (ANG270 - 1 - ta[slope(x, y)]) & 0xFFFF

    def vertex_angle(self, vi):
        """Angle from the eye to vertex vi (cached per frame: the 6502 keeps a
        per-vertex frame stamp, so each vertex costs one division)."""
        a = self.vertex_angles.get(vi)
        if a is None:
            v = self.d.vertexes[vi]
            a = self.point_to_angle((v.x << SUBBITS) - self.vx, (v.y << SUBBITS) - self.vy)
            self.vertex_angles[vi] = a
        return a

    @staticmethod
    def point_on_side(x, y, nx, ny, ndx, ndy):
        """R_PointOnSide: point in sub-units, line (map units) -> 0 front, 1 back."""
        nx <<= SUBBITS
        ny <<= SUBBITS
        if ndx == 0:
            return int(ndy > 0) if x <= nx else int(ndy < 0)
        if ndy == 0:
            return int(ndx < 0) if y <= ny else int(ndx > 0)
        dx, dy = x - nx, y - ny
        if (ndy ^ ndx ^ dx ^ dy) < 0:
            return 1 if (ndy ^ dx) < 0 else 0
        return 1 if dy * ndx >= ndy * dx else 0

    def point_subsector(self, x, y):
        d = self.d
        if not d.nodes:
            return 0
        n = len(d.nodes) - 1
        while not n & NF_SUBSECTOR:
            nd = d.nodes[n]
            side = self.point_on_side(x, y, nd.x, nd.y, nd.dx, nd.dy)
            n = nd.child1 if side else nd.child0
        return n & ~NF_SUBSECTOR

    def point_sector(self, x, y):
        return self.d.subsectors[self.point_subsector(x, y)].sector

    # ---- BSP ----
    def render_bsp(self, bspnum):
        st = self.stats
        if bspnum & NF_SUBSECTOR:
            self.subsector(bspnum & ~NF_SUBSECTOR if bspnum != NONE16 else 0)
            return
        if self.depth >= MAXBSPDEPTH:
            st.add("bsp_overflow")
            return
        self.depth += 1
        st["bsp_depth"] = max(st.get("bsp_depth", 0), self.depth)
        st.add("nodes")
        nd = self.d.nodes[bspnum]
        side = self.point_on_side(self.vx, self.vy, nd.x, nd.y, nd.dx, nd.dy)
        st.add("mul_side", 2)
        self.render_bsp(nd.child1 if side else nd.child0)
        if side:
            box = (nd.bbox0_top, nd.bbox0_bottom, nd.bbox0_left, nd.bbox0_right)
        else:
            box = (nd.bbox1_top, nd.bbox1_bottom, nd.bbox1_left, nd.bbox1_right)
        if self.check_bbox(box):
            self.render_bsp(nd.child0 if side else nd.child1)
        self.depth -= 1

    CHECKCOORD = [(3, 0, 2, 1), (3, 0, 2, 0), (3, 1, 2, 0), None, (2, 0, 2, 1), None,
                  (3, 1, 3, 0), None, (2, 0, 3, 1), (2, 1, 3, 1), (2, 1, 3, 0)]

    def check_bbox(self, box):
        """R_CheckBBox: could any part of the box be visible?"""
        st = self.stats
        st.add("bbox_checks")
        vx, vy = self.vx, self.vy
        top, bottom, left, right = (c << SUBBITS for c in box)
        boxx = 0 if vx <= left else 1 if vx < right else 2
        boxy = 0 if vy >= top else 1 if vy > bottom else 2
        boxpos = (boxy << 2) + boxx
        if boxpos == 5:
            return True
        c = self.CHECKCOORD[boxpos]
        sub = (top, bottom, left, right)
        x1, y1, x2, y2 = sub[c[0]], sub[c[1]], sub[c[2]], sub[c[3]]
        clip = self.t.clipangle
        angle1 = (self.point_to_angle(x1 - vx, y1 - vy) - self.va) & 0xFFFF
        angle2 = (self.point_to_angle(x2 - vx, y2 - vy) - self.va) & 0xFFFF
        span = (angle1 - angle2) & 0xFFFF
        if span >= ANG180:
            return True
        tspan = (angle1 + clip) & 0xFFFF
        if tspan > 2 * clip:
            tspan = (tspan - 2 * clip) & 0xFFFF
            if tspan >= span:
                return False
            angle1 = clip
        tspan = (clip - angle2) & 0xFFFF
        if tspan > 2 * clip:
            tspan = (tspan - 2 * clip) & 0xFFFF
            if tspan >= span:
                return False
            angle2 = (-clip) & 0xFFFF
        sx1 = self.t.vatx(angle1)
        sx2 = self.t.vatx(angle2)
        if sx1 == sx2:
            return False
        sx2 -= 1
        for first, last in self.solidsegs:
            if last >= sx2:
                break
        return not (sx1 >= first and sx2 <= last)

    def subsector(self, num):
        d, st = self.d, self.stats
        st.add("subsectors")
        sub = d.subsectors[num]
        self.frontsector = fs = d.sectors[sub.sector]
        self.frontsector_index = sub.sector
        light = fs.lightlevel
        if (fs.floorheight << SUBBITS) < self.vz:
            self.floorplane = self.find_plane(fs.floorheight, self.flattrans[fs.floorpic], light)
        else:
            self.floorplane = None
        if (fs.ceilingheight << SUBBITS) > self.vz or fs.ceilingpic == d.skyflat:
            self.ceilingplane = self.find_plane(fs.ceilingheight, self.flattrans[fs.ceilingpic],
                                                light)
        else:
            self.ceilingplane = None
        self.add_sprites(sub.sector)
        for i in range(sub.firstseg, sub.firstseg + sub.numsegs):
            self.add_line(d.segs[i])

    def add_line(self, seg):
        """R_AddLine: clip the seg to the view angle range, find its columns."""
        st, t, d = self.stats, self.t, self.d
        st.add("segs")
        self.curline = seg
        angle1 = self.vertex_angle(seg.v1)
        angle2 = self.vertex_angle(seg.v2)
        span = (angle1 - angle2) & 0xFFFF
        if span >= ANG180:
            return
        self.rw_angle1 = angle1
        angle1 = (angle1 - self.va) & 0xFFFF
        angle2 = (angle2 - self.va) & 0xFFFF
        clip = t.clipangle
        tspan = (angle1 + clip) & 0xFFFF
        if tspan > 2 * clip:
            tspan = (tspan - 2 * clip) & 0xFFFF
            if tspan >= span:
                return
            angle1 = clip
        tspan = (clip - angle2) & 0xFFFF
        if tspan > 2 * clip:
            tspan = (tspan - 2 * clip) & 0xFFFF
            if tspan >= span:
                return
            angle2 = (-clip) & 0xFFFF
        x1 = t.vatx(angle1)
        x2 = t.vatx(angle2)
        if x1 == x2:
            return
        st.add("segs_facing")
        self.backsector = bs = d.sectors[seg.backsector] if seg.backsector != NONE16 else None
        fs = self.frontsector
        if bs is None:
            self.clip_solid(x1, x2 - 1)
            return
        if bs.ceilingheight <= fs.floorheight or bs.floorheight >= fs.ceilingheight:
            self.clip_solid(x1, x2 - 1)
            return
        if bs.ceilingheight != fs.ceilingheight or bs.floorheight != fs.floorheight:
            self.clip_pass(x1, x2 - 1)
            return
        if (bs.ceilingpic == fs.ceilingpic and bs.floorpic == fs.floorpic
                and bs.lightlevel == fs.lightlevel and d.sides[seg.sidedef].midtexture == 0):
            return
        self.clip_pass(x1, x2 - 1)

    def clip_solid(self, first, last):
        """R_ClipSolidWallSegment."""
        ss = self.solidsegs
        i = 0
        while ss[i][1] < first - 1:
            i += 1
        if first < ss[i][0]:
            if last < ss[i][0] - 1:
                self.store_wall_range(first, last)
                ss.insert(i, [first, last])
                assert len(ss) <= MAXSOLIDSEGS
                return
            self.store_wall_range(first, ss[i][0] - 1)
            ss[i][0] = first
        if last <= ss[i][1]:
            return
        nxt = i
        while last >= ss[nxt + 1][0] - 1:
            self.store_wall_range(ss[nxt][1] + 1, ss[nxt + 1][0] - 1)
            nxt += 1
            if last <= ss[nxt][1]:
                ss[i][1] = ss[nxt][1]
                del ss[i + 1:nxt + 1]
                return
        self.store_wall_range(ss[nxt][1] + 1, last)
        ss[i][1] = last
        del ss[i + 1:nxt + 1]

    def clip_pass(self, first, last):
        """R_ClipPassWallSegment."""
        ss = self.solidsegs
        i = 0
        while ss[i][1] < first - 1:
            i += 1
        if first < ss[i][0]:
            if last < ss[i][0] - 1:
                self.store_wall_range(first, last)
                return
            self.store_wall_range(first, ss[i][0] - 1)
        if last <= ss[i][1]:
            return
        while last >= ss[i + 1][0] - 1:
            self.store_wall_range(ss[i][1] + 1, ss[i + 1][0] - 1)
            i += 1
            if last <= ss[i][1]:
                return
        self.store_wall_range(ss[i][1] + 1, last)

    # ---- planes ----
    def find_plane(self, height, picnum, light):
        """R_FindPlane (height in map units)."""
        if picnum == self.d.skyflat:
            height, light = 0, 0
        for pl in self.visplanes:
            if pl.height == height and pl.picnum == picnum and pl.light == light:
                return pl
        return self._new_plane(height, picnum, light)

    def _new_plane(self, height, picnum, light):
        if self.shaded or len(self.visplanes) >= MAXVISPLANES:
            if not self.shaded:
                self.stats.add("visplane_overflow")
            return Visplane(height, picnum, light, overflow=True)
        pl = Visplane(height, picnum, light)
        self.visplanes.append(pl)
        return pl

    def check_plane(self, pl, start, stop):
        """R_CheckPlane: the plane if columns start..stop are free in it, else a new one."""
        if pl.overflow:
            return pl
        if start < pl.minx:
            intrl, unionl = pl.minx, start
        else:
            unionl, intrl = pl.minx, start
        if stop > pl.maxx:
            intrh, unionh = pl.maxx, stop
        else:
            unionh, intrh = pl.maxx, stop
        x = intrl
        while x <= intrh:
            if pl.top[x + 1] != 0xFF:
                break
            x += 1
        if x > intrh:
            pl.minx, pl.maxx = unionl, unionh
            return pl
        new = self._new_plane(pl.height, pl.picnum, pl.light)
        if not new.overflow:
            new.minx, new.maxx = start, stop
        return new

    # ---- walls ----
    def scale_from_angle(self, visangle):
        """R_ScaleFromGlobalAngle: pixels per map unit (16.16) along a ray."""
        t = self.t
        anglea = (ANG90 + visangle - self.va) & 0xFFFF
        angleb = (ANG90 + visangle - self.rw_normalangle) & 0xFFFF
        sinea = t.sin_bam(anglea)
        sineb = t.sin_bam(angleb)
        num = PROJ * sineb
        den = (self.rw_distance * sinea) >> SINEBITS
        self.stats.add("mul_seg", 2)
        if den <= 0:
            return SCALE_MAX
        if num <= 0:
            return SCALE_MIN
        if num >= den << 16:
            return SCALE_MAX
        self.stats.add("div_scale")
        return max(SCALE_MIN, (num << 6) // den)

    def store_wall_range(self, start, stop):
        """R_StoreWallRange: one wall range, columns start..stop."""
        d, t, st = self.d, self.t, self.stats
        seg, fs, bs = self.curline, self.frontsector, self.backsector
        st.add("wall_ranges")
        side = d.sides[seg.sidedef]
        line = d.lines[seg.linedef]
        v1, v2 = d.vertexes[seg.v1], d.vertexes[seg.v2]
        vz = self.vz
        ds = Drawseg()
        record = len(self.drawsegs) < MAXDRAWSEGS
        if not record:
            st.add("drawseg_overflow")
        self.rw_normalangle = na = (seg.angle + ANG90) & 0xFFFF
        dx = (v1.x << SUBBITS) - self.vx
        dy = (v1.y << SUBBITS) - self.vy
        self.rw_distance = (dx * t.cos_bam(na) + dy * t.sin_bam(na)) >> SINEBITS
        st.add("mul_seg", 2)
        ds.seg = seg
        ds.x1, ds.x2 = start, stop
        rw_scale = ds.scale1 = self.scale_from_angle(self.va + t.xtoviewangle[start])
        if stop > start:
            ds.scale2 = self.scale_from_angle(self.va + t.xtoviewangle[stop])
            ds.scalestep = rw_scalestep = div_trunc(ds.scale2 - rw_scale, stop - start)
            st.add("div_step")
        else:
            ds.scale2 = ds.scale1
            ds.scalestep = rw_scalestep = 0
        worldtop = (fs.ceilingheight << SUBBITS) - vz
        worldbottom = (fs.floorheight << SUBBITS) - vz
        midtexture = toptexture = bottomtexture = 0
        maskedtexture = False
        ds.maskedtexturecol = None
        ds.sprtopclip = ds.sprbottomclip = None
        markfloor = markceiling = False
        rw_midtexturemid = rw_toptexturemid = rw_bottomtexturemid = 0
        worldhigh = worldlow = 0
        rowoffset = side.yoffset << SUBBITS
        if bs is None:
            midtexture = self.textrans[side.midtexture]
            markfloor = markceiling = True
            if line.flags & ML_DONTPEGBOTTOM:
                vtop = ((fs.floorheight + d.textures[side.midtexture].height) << SUBBITS)
                rw_midtexturemid = vtop - vz
            else:
                rw_midtexturemid = worldtop
            rw_midtexturemid += rowoffset
            ds.silhouette = SIL_BOTH
            ds.sprtopclip = "screenheight"
            ds.sprbottomclip = "negone"
            ds.bsilheight = MAXINT
            ds.tsilheight = MININT
        else:
            ds.silhouette = 0
            ds.bsilheight = ds.tsilheight = 0
            if fs.floorheight > bs.floorheight:
                ds.silhouette = SIL_BOTTOM
                ds.bsilheight = fs.floorheight << SUBBITS
            elif (bs.floorheight << SUBBITS) > vz:
                ds.silhouette = SIL_BOTTOM
                ds.bsilheight = MAXINT
            if fs.ceilingheight < bs.ceilingheight:
                ds.silhouette |= SIL_TOP
                ds.tsilheight = fs.ceilingheight << SUBBITS
            elif (bs.ceilingheight << SUBBITS) < vz:
                ds.silhouette |= SIL_TOP
                ds.tsilheight = MININT
            if bs.ceilingheight <= fs.floorheight:
                ds.sprbottomclip = "negone"
                ds.bsilheight = MAXINT
                ds.silhouette |= SIL_BOTTOM
            if bs.floorheight >= fs.ceilingheight:
                ds.sprtopclip = "screenheight"
                ds.tsilheight = MININT
                ds.silhouette |= SIL_TOP
            worldhigh = (bs.ceilingheight << SUBBITS) - vz
            worldlow = (bs.floorheight << SUBBITS) - vz
            if fs.ceilingpic == d.skyflat and bs.ceilingpic == d.skyflat:
                worldtop = worldhigh
            markfloor = (worldlow != worldbottom or bs.floorpic != fs.floorpic
                         or bs.lightlevel != fs.lightlevel)
            markceiling = (worldhigh != worldtop or bs.ceilingpic != fs.ceilingpic
                           or bs.lightlevel != fs.lightlevel)
            if bs.ceilingheight <= fs.floorheight or bs.floorheight >= fs.ceilingheight:
                markceiling = markfloor = True
            if worldhigh < worldtop:
                toptexture = self.textrans[side.toptexture]
                if line.flags & ML_DONTPEGTOP:
                    rw_toptexturemid = worldtop
                else:
                    vtop = (bs.ceilingheight + d.textures[side.toptexture].height) << SUBBITS
                    rw_toptexturemid = vtop - vz
            if worldlow > worldbottom:
                bottomtexture = self.textrans[side.bottomtexture]
                if line.flags & ML_DONTPEGBOTTOM:
                    rw_bottomtexturemid = worldtop
                else:
                    rw_bottomtexturemid = worldlow
            rw_toptexturemid += rowoffset
            rw_bottomtexturemid += rowoffset
            if side.midtexture:
                need = 2 * (stop - start + 1)
                if record and self.openings + need <= MAXOPENINGS:
                    maskedtexture = True
                    ds.maskedtexturecol = {}
                    self.openings += need
                elif record:
                    st.add("openings_overflow")
        segtextured = midtexture or toptexture or bottomtexture or maskedtexture
        rw_offset = rw_centerangle = 0
        walllights = None
        if segtextured:
            rw_offset = (((self.vx - (v1.x << SUBBITS)) * t.cos_bam(seg.angle)
                          + (self.vy - (v1.y << SUBBITS)) * t.sin_bam(seg.angle)) >> SINEBITS)
            rw_offset += (side.xoffset + seg.offset) << SUBBITS
            st.add("mul_seg", 2)
            rw_centerangle = (ANG90 + self.va - na) & 0xFFFF
            if self.fixedcolormap is None:
                lightnum = (fs.lightlevel >> LIGHTSEGSHIFT) + self.extralight
                if v1.y == v2.y:
                    lightnum -= 1
                elif v1.x == v2.x:
                    lightnum += 1
                walllights = t.scalelight[max(0, min(LIGHTLEVELS - 1, lightnum))]
        if (fs.floorheight << SUBBITS) >= vz:
            markfloor = False
        if (fs.ceilingheight << SUBBITS) <= vz and fs.ceilingpic != d.skyflat:
            markceiling = False
        # rows: 12 fraction bits; (sub-units * 16.16) >> 8
        topstep = -((rw_scalestep * worldtop) >> 8)
        topfrac = s32((CENTERY << HEIGHTBITS) - ((worldtop * rw_scale) >> 8))
        bottomstep = -((rw_scalestep * worldbottom) >> 8)
        bottomfrac = s32((CENTERY << HEIGHTBITS) - ((worldbottom * rw_scale) >> 8))
        st.add("mul_seg", 4)
        pixhigh = pixlow = pixhighstep = pixlowstep = 0
        if bs is not None:
            if worldhigh < worldtop:
                pixhigh = s32((CENTERY << HEIGHTBITS) - ((worldhigh * rw_scale) >> 8))
                pixhighstep = -((rw_scalestep * worldhigh) >> 8)
                st.add("mul_seg", 2)
            if worldlow > worldbottom:
                pixlow = s32((CENTERY << HEIGHTBITS) - ((worldlow * rw_scale) >> 8))
                pixlowstep = -((rw_scalestep * worldlow) >> 8)
                st.add("mul_seg", 2)
        if markceiling:
            self.ceilingplane = self.check_plane(self.ceilingplane, start, stop)
        if markfloor:
            self.floorplane = self.check_plane(self.floorplane, start, stop)

        # R_RenderSegLoop
        cclip, fclip = self.ceilingclip, self.floorclip
        cpl, fpl = self.ceilingplane, self.floorplane
        texcol = 0
        colormap = 0
        for x in range(start, stop + 1):
            st.add("wall_columns")
            yl = (topfrac + HEIGHTUNIT - 1) >> HEIGHTBITS
            if yl < cclip[x] + 1:
                yl = cclip[x] + 1
            yh = bottomfrac >> HEIGHTBITS
            if yh >= fclip[x]:
                yh = fclip[x] - 1
            if markceiling:
                top = cclip[x] + 1
                bottom = yl - 1
                if bottom >= fclip[x]:
                    bottom = fclip[x] - 1
                # Not in Doom: when the ceiling edge is below the floor edge
                # (a sky-hack worldtop below the floor), the floor keeps the
                # rows both would mark, so no pixel is drawn twice.
                if markfloor and bottom > yh:
                    bottom = yh
                if top <= bottom:
                    self.mark_plane(cpl, x, top, bottom, fs.lightlevel, rw_scale)
            if markfloor:
                top = yh + 1
                bottom = fclip[x] - 1
                if top <= cclip[x]:
                    top = cclip[x] + 1
                if top <= bottom:
                    self.mark_plane(fpl, x, top, bottom, fs.lightlevel, rw_scale)
            if segtextured:
                a = ((rw_centerangle + t.xtoviewangle[x]) & 0xFFFF) >> FINESHIFT
                if a >= TANHALF:
                    a = TANHALF - 1 if a < TANHALF + FINEANGLES // 4 else 0
                u = rw_offset - ((t.tan(a) * self.rw_distance) >> TANBITS)
                texcol = u >> (SUBBITS + 1)          # half-resolution texel column
                st.add("mul_col")
                if self.fixedcolormap is not None:
                    colormap = self.fixedcolormap
                else:
                    colormap = walllights[min(rw_scale >> LIGHTSCALESHIFT, MAXLIGHTSCALE - 1)]
                iscale = t.iscale(rw_scale)
            if midtexture:
                self.draw_wall_column(x, yl, yh, midtexture, texcol, rw_midtexturemid,
                                      iscale, colormap)
                cclip[x] = VIEW_H
                fclip[x] = -1
            else:
                if toptexture:
                    mid = pixhigh >> HEIGHTBITS
                    pixhigh = s32(pixhigh + pixhighstep)
                    if mid >= fclip[x]:
                        mid = fclip[x] - 1
                    if mid >= yl:
                        self.draw_wall_column(x, yl, mid, toptexture, texcol, rw_toptexturemid,
                                              iscale, colormap)
                        cclip[x] = mid
                    else:
                        cclip[x] = yl - 1
                elif markceiling:
                    cclip[x] = yl - 1
                if bottomtexture:
                    mid = (pixlow + HEIGHTUNIT - 1) >> HEIGHTBITS
                    pixlow = s32(pixlow + pixlowstep)
                    if mid <= cclip[x]:
                        mid = cclip[x] + 1
                    if mid <= yh:
                        self.draw_wall_column(x, mid, yh, bottomtexture, texcol,
                                              rw_bottomtexturemid, iscale, colormap)
                        fclip[x] = mid
                    else:
                        fclip[x] = yh + 1
                elif markfloor:
                    fclip[x] = yh + 1
                if maskedtexture:
                    ds.maskedtexturecol[x] = texcol
            rw_scale += rw_scalestep
            topfrac = s32(topfrac + topstep)
            bottomfrac = s32(bottomfrac + bottomstep)

        # sprite clipping info
        if record:
            if (ds.silhouette & SIL_TOP or maskedtexture) and ds.sprtopclip is None:
                ds.sprtopclip = self._opening(cclip, start, stop)
            if (ds.silhouette & SIL_BOTTOM or maskedtexture) and ds.sprbottomclip is None:
                ds.sprbottomclip = self._opening(fclip, start, stop)
            if ds.sprtopclip is False or ds.sprbottomclip is False:
                # out of openings: this drawseg clips nothing
                ds.silhouette = 0
                ds.sprtopclip = ds.sprbottomclip = None
                if ds.maskedtexturecol is not None:
                    ds.maskedtexturecol = None
            if maskedtexture and ds.maskedtexturecol is not None:
                if not ds.silhouette & SIL_TOP:
                    ds.silhouette |= SIL_TOP
                    ds.tsilheight = MININT
                if not ds.silhouette & SIL_BOTTOM:
                    ds.silhouette |= SIL_BOTTOM
                    ds.bsilheight = MAXINT
            self.drawsegs.append(ds)

    def _opening(self, clip, start, stop):
        n = stop - start + 1
        if self.openings + n > MAXOPENINGS:
            self.stats.add("openings_overflow")
            return False
        self.openings += n
        return {x: clip[x] for x in range(start, stop + 1)}

    def mark_plane(self, pl, x, top, bottom, light, rw_scale):
        """A plane piece of column x, rows top..bottom: into the visplane, or,
        flat-shaded mode and visplane overflow, drawn at once."""
        if not pl.overflow:
            pl.top[x + 1] = top
            pl.bottom[x + 1] = bottom
            return
        d, t, st = self.d, self.t, self.stats
        if pl.picnum == d.skyflat:
            self.draw_sky_column(x, top, bottom)
            return
        flat = d.flats[pl.picnum]
        if self.fixedcolormap is not None:
            k = self.fixedcolormap
        else:
            lightnum = max(0, min(LIGHTLEVELS - 1, (light >> LIGHTSEGSHIFT) + self.extralight))
            k = t.scalelight[lightnum][min(rw_scale >> LIGHTSCALESHIFT, MAXLIGHTSCALE - 1)]
        c = self.d.colormap(flat.bank, k)[flat.color]
        st.add("shaded_columns")
        st.add("shaded_pixels", bottom - top + 1)
        for y in range(top, bottom + 1):
            self.put(x, y, c)

    # ---- drawing primitives ----
    def put(self, x, y, c):
        i = VIEW_H * x + y
        self.buf[i] = c
        if self.writes is not None:
            self.writes[i] += 1

    def draw_wall_column(self, x, yl, yh, texnum, texcol, texturemid, iscale, colormap):
        """R_DrawColumn for a wall piece: 8.8 texel stepping, v & hmask."""
        if yh < yl:
            return
        st = self.stats
        st.add("wall_pieces")
        st.add("wall_pixels", yh - yl + 1)
        tex = self.d.textures[texnum]
        img = self.d.banks[tex.bank]
        base = tex.addr + ((texcol & tex.wmask) << tex.log2h)
        cmap = self.d.colormap(tex.bank, colormap)
        frac = (texturemid << 11) + (yl - CENTERY) * iscale      # texels, 16.16
        st.add("mul_piece")
        f = (frac >> 8) & 0xFFFF
        step = ((iscale + 0x80) >> 8) & 0xFFFF
        hmask = tex.hmask
        for y in range(yl, yh + 1):
            self.put(x, y, cmap[img[base + ((f >> 8) & hmask)]])
            f = (f + step) & 0xFFFF

    def draw_sky_column(self, x, yl, yh):
        """The sky: column from the view angle (512 per turn), row y + 8, colormap 0."""
        st = self.stats
        st.add("sky_columns")
        st.add("sky_pixels", yh - yl + 1)
        tex = self.d.textures[self.textrans[self.d.sky]]
        img = self.d.banks[tex.bank]
        col = ((self.va + self.t.xtoviewangle[x]) & 0xFFFF) >> 7
        base = tex.addr + ((col & tex.wmask) << tex.log2h)
        cmap = self.d.colormap(tex.bank, self.fixedcolormap or 0)
        # texturemid 50 texels, iscale 1: f = (50 + y - 42) << 8
        f = ((50 + yl - CENTERY) << 8) & 0xFFFF
        for y in range(yl, yh + 1):
            self.put(x, y, cmap[img[base + ((f >> 8) & tex.hmask)]])
            f = (f + 0x100) & 0xFFFF

    # ---- planes ----
    def draw_planes(self):
        """R_DrawPlanes: sky planes as columns, the others as spans."""
        d, t, st = self.d, self.t, self.stats
        for pl in self.visplanes:
            if pl.minx > pl.maxx:
                continue
            st.add("planes_drawn")
            if pl.picnum == d.skyflat:
                for x in range(pl.minx, pl.maxx + 1):
                    top, bottom = pl.top[x + 1], pl.bottom[x + 1]
                    if top <= bottom:
                        self.draw_sky_column(x, top, bottom)
                continue
            self.planeheight = abs((pl.height << SUBBITS) - self.vz)
            if self.fixedcolormap is None:
                light = max(0, min(LIGHTLEVELS - 1,
                                   (pl.light >> LIGHTSEGSHIFT) + self.extralight))
                self.planezlight = t.zlight[light]
            flat = d.flats[pl.picnum]
            self.ds_flat = flat
            pl.top[pl.maxx + 2] = 0xFF
            pl.top[pl.minx] = 0xFF
            self.spanstart = [0] * VIEW_H
            for x in range(pl.minx, pl.maxx + 2):
                self.make_spans(x, pl.top[x], pl.bottom[x], pl.top[x + 1], pl.bottom[x + 1])

    def make_spans(self, x, t1, b1, t2, b2):
        """R_MakeSpans (x: this column; t1/b1 the previous column's range)."""
        while t1 < t2 and t1 <= b1:
            self.map_plane(t1, self.spanstart[t1], x - 1)
            t1 += 1
        while b1 > b2 and b1 >= t1:
            self.map_plane(b1, self.spanstart[b1], x - 1)
            b1 -= 1
        while t2 < t1 and t2 <= b2:
            self.spanstart[t2] = x
            t2 += 1
        while b2 > b1 and b2 >= t2:
            self.spanstart[b2] = x
            b2 -= 1

    def map_plane(self, y, x1, x2):
        """R_MapPlane + R_DrawSpan: row y, columns x1..x2 of the current plane."""
        t, st = self.t, self.stats
        st.add("spans")
        st.add("span_pixels", x2 - x1 + 1)
        c = self.cached[y]
        if c is not None and c[0] == self.planeheight:
            distance, xstep, ystep = c[1:]
        else:
            distance = (self.planeheight * t.yslope[y]) >> 8
            xstep = ((distance * self.basexscale) >> 15) & 0xFFFF
            ystep = ((distance * self.baseyscale) >> 15) & 0xFFFF
            self.cached[y] = (self.planeheight, distance, xstep, ystep)
            st.add("span_rows")
            st.add("mul_span", 3)
        length = (distance * t.distscale[x1]) >> SINEBITS
        angle = (self.va + t.xtoviewangle[x1]) & 0xFFFF
        xfrac = ((self.vx << 6) + ((t.cos_bam(angle) * length) >> 8)) & 0xFFFF
        yfrac = (-(self.vy << 6) - ((t.sin_bam(angle) * length) >> 8)) & 0xFFFF
        st.add("mul_span", 3)
        if self.fixedcolormap is not None:
            k = self.fixedcolormap
        else:
            k = self.planezlight[min(distance >> LIGHTZSHIFT, MAXLIGHTZ - 1)]
        flat = self.ds_flat
        img = self.d.banks[flat.bank]
        cmap = self.d.colormap(flat.bank, k)
        base = flat.addr
        for x in range(x1, x2 + 1):
            spot = ((yfrac >> 11) << 5) | (xfrac >> 11)
            self.put(x, y, cmap[img[base + spot]])
            xfrac = (xfrac + xstep) & 0xFFFF
            yfrac = (yfrac + ystep) & 0xFFFF

    # ---- things ----
    def add_sprites(self, sector):
        if sector in self.sectors_done:
            return
        self.sectors_done.add(sector)
        light = self.d.sectors[sector].lightlevel
        lightnum = max(0, min(LIGHTLEVELS - 1, (light >> LIGHTSEGSHIFT) + self.extralight))
        for th in self.sector_things.get(sector, ()):
            self.project_sprite(th, self.t.scalelight[lightnum])

    def sprite_lump(self, sprite, frame, rot):
        """(SPRLUMP index, flipped) of a sprite frame seen at rotation rot, or None."""
        d = self.d
        sd = d.sprdefs[sprite]
        f = frame & FF_FRAMEMASK
        if f >= sd.numframes:
            return None
        fr = d.sprframes[sd.firstframe + f]
        e = fr.rot0
        if e & 0x4000:
            e = getattr(fr, f"rot{rot}")
        lump = e & 0x3FFF
        if lump == wad2a2.SPR_NOLUMP:
            return None
        return lump, bool(e & 0x8000)

    def project_sprite(self, th, spritelights):
        """R_ProjectSprite: a thing -> a vissprite."""
        t, st = self.t, self.stats
        st.add("things")
        tr_x = th.x - self.vx
        tr_y = th.y - self.vy
        gxt = (tr_x * self.viewcos) >> SINEBITS
        gyt = -((tr_y * self.viewsin) >> SINEBITS)
        tz = gxt - gyt
        st.add("mul_thing", 2)
        if tz < MINZ:
            return
        xscale = (PROJ << 20) // tz               # pixels per map unit, 16.16
        st.add("div_thing")
        gxt = -((tr_x * self.viewsin) >> SINEBITS)
        gyt = (tr_y * self.viewcos) >> SINEBITS
        tx = -(gyt + gxt)
        st.add("mul_thing", 2)
        if abs(tx) > tz << 2:
            return
        ang = self.point_to_angle(tr_x, tr_y)
        rot = ((ang - th.angle + 0x9000) & 0xFFFF) >> 13
        lf = self.sprite_lump(th.sprite, th.frame, rot)
        if lf is None:
            return
        lump, flip = lf
        s = self.d.sprlumps[lump]
        tx -= s.left << (SUBBITS + 1)
        x1 = ((CENTERX << 16) + ((tx * xscale) >> SUBBITS)) >> 16
        if x1 > VIEW_W - 1:
            return
        tx += s.width << (SUBBITS + 1)
        x2 = (((CENTERX << 16) + ((tx * xscale) >> SUBBITS)) >> 16) - 1
        st.add("mul_thing", 2)
        if x2 < 0:
            return
        if len(self.vissprites) >= MAXVISSPRITES:
            st.add("vissprite_overflow")
            return
        vis = Vissprite()
        vis.flags = th.flags
        vis.scale = xscale
        vis.gx, vis.gy, vis.gz = th.x, th.y, th.z
        vis.gzt = th.z + (s.top << (SUBBITS + 1))
        vis.texturemid = vis.gzt - self.vz          # sub-units
        vis.x1 = max(0, x1)
        vis.x2 = min(VIEW_W - 1, x2)
        iscale = t.iscale(xscale)                  # texels per pixel
        if flip:
            vis.startfrac = (s.width << 16) - 1
            vis.xiscale = -iscale
        else:
            vis.startfrac = 0
            vis.xiscale = iscale
        if vis.x1 > x1:
            vis.startfrac += vis.xiscale * (vis.x1 - x1)
            st.add("mul_thing")
        vis.lump, vis.flip = lump, flip
        if th.flags & MF_SHADOW:
            vis.colormap = None
        elif self.fixedcolormap is not None:
            vis.colormap = self.fixedcolormap
        elif th.frame & FF_FULLBRIGHT:
            vis.colormap = 0
        else:
            vis.colormap = spritelights[min(xscale >> LIGHTSCALESHIFT, MAXLIGHTSCALE - 1)]
        self.vissprites.append(vis)

    def draw_masked(self):
        """R_DrawMasked: sprites far to near, then the remaining masked middles."""
        order = sorted(range(len(self.vissprites)), key=lambda i: (self.vissprites[i].scale, i))
        self.stats.add("sort_sprites", len(order))
        for i in order:
            self.draw_sprite(self.vissprites[i])
        for ds in reversed(self.drawsegs):
            if ds.maskedtexturecol is not None:
                self.render_masked_seg_range(ds, ds.x1, ds.x2)

    def point_on_seg_side(self, x, y, seg):
        v1, v2 = self.d.vertexes[seg.v1], self.d.vertexes[seg.v2]
        return self.point_on_side(x, y, v1.x, v1.y, v2.x - v1.x, v2.y - v1.y)

    def draw_sprite(self, spr):
        """R_DrawSprite: clip a vissprite by the drawsegs, then draw it."""
        st = self.stats
        clipbot = {x: -2 for x in range(spr.x1, spr.x2 + 1)}
        cliptop = dict(clipbot)
        for ds in reversed(self.drawsegs):
            if (ds.x1 > spr.x2 or ds.x2 < spr.x1
                    or (not ds.silhouette and ds.maskedtexturecol is None)):
                continue
            st.add("sprite_drawseg_checks")
            r1 = max(ds.x1, spr.x1)
            r2 = min(ds.x2, spr.x2)
            if ds.scale1 > ds.scale2:
                lowscale, scale = ds.scale2, ds.scale1
            else:
                lowscale, scale = ds.scale1, ds.scale2
            if scale < spr.scale or (lowscale < spr.scale
                                     and not self.point_on_seg_side(spr.gx, spr.gy, ds.seg)):
                if ds.maskedtexturecol is not None:
                    self.render_masked_seg_range(ds, r1, r2)
                continue
            sil = ds.silhouette
            if spr.gz >= ds.bsilheight:
                sil &= ~SIL_BOTTOM
            if spr.gzt <= ds.tsilheight:
                sil &= ~SIL_TOP
            for x in range(r1, r2 + 1):
                if sil & SIL_BOTTOM and clipbot[x] == -2:
                    clipbot[x] = self._clipval(ds.sprbottomclip, x)
                if sil & SIL_TOP and cliptop[x] == -2:
                    cliptop[x] = self._clipval(ds.sprtopclip, x)
        for x in clipbot:
            if clipbot[x] == -2:
                clipbot[x] = VIEW_H
            if cliptop[x] == -2:
                cliptop[x] = -1
        self.mfloorclip, self.mceilingclip = clipbot, cliptop
        self.draw_vissprite(spr, (spr.scale * 2), abs(spr.xiscale))

    @staticmethod
    def _clipval(arr, x):
        if arr == "screenheight":
            return VIEW_H
        if arr == "negone":
            return -1
        return arr[x]

    def draw_vissprite(self, vis, spryscale, iscale, texturemid_t=None, sprtopscreen=None):
        """R_DrawVisSprite: columns of a sprite patch, posts clipped by
        mfloorclip/mceilingclip. spryscale: pixels per texel (16.16);
        iscale: texels per pixel (16.16)."""
        st = self.stats
        img, addr, w, h, left, top = self.d.sprite_patch(vis.lump)
        if texturemid_t is None:
            texturemid_t = vis.texturemid << 11           # sub-units -> texels 16.16
            sprtopscreen = (CENTERY << 16) - ((vis.texturemid * vis.scale) >> SUBBITS)
            st.add("mul_sprite")
        bank = self.d.sprlumps[vis.lump].bank
        cmap = None if vis.colormap is None else self.d.colormap(bank, vis.colormap)
        frac = vis.startfrac
        st.add("sprites_drawn")
        for x in range(vis.x1, vis.x2 + 1):
            col = frac >> 16
            frac += vis.xiscale
            if col < 0 or col >= w:
                continue
            st.add("sprite_columns")
            p = addr + struct.unpack_from("<H", img, addr + 6 + 2 * col)[0]
            while img[p] != 0xFF:
                topdelta, length = img[p], img[p + 1]
                topscreen = sprtopscreen + spryscale * topdelta
                bottomscreen = topscreen + spryscale * length
                st.add("sprite_posts")
                st.add("mul_post", 2)
                yl = (topscreen + 0xFFFF) >> 16
                yh = (bottomscreen - 1) >> 16
                if yh >= self.mfloorclip[x]:
                    yh = self.mfloorclip[x] - 1
                if yl <= self.mceilingclip[x]:
                    yl = self.mceilingclip[x] + 1
                if yl <= yh:
                    mid = texturemid_t - (topdelta << 16)
                    self.draw_post(x, yl, yh, img, p + 2, mid, iscale, cmap, bank)
                p += 2 + length

    def draw_post(self, x, yl, yh, img, src, texturemid, iscale, cmap, bank):
        """One post: rows yl..yh from the post's pixels at src, 8.8 stepping
        (the index is not masked: rounding can read the byte after the post,
        as Doom does); cmap None = the fuzz effect."""
        st = self.stats
        frac = texturemid + (yl - CENTERY) * iscale
        f = (frac >> 8) & 0xFFFF
        step = ((iscale + 0x80) >> 8) & 0xFFFF
        st.add("mul_piece")
        if cmap is None:
            # Doom's fuzz: darken a neighbouring row (rows 1..82 only)
            yl = max(yl, 1)
            yh = min(yh, VIEW_H - 2)
            st.add("fuzz_pixels", max(0, yh - yl + 1))
            fz = self.d.colormap(bank, FUZZ_COLORMAP)
            for y in range(yl, yh + 1):
                src_i = VIEW_H * x + y + self.t.fuzzoffset[self.fuzzpos]
                self.put(x, y, fz[self.buf[src_i]])
                self.fuzzpos = (self.fuzzpos + 1) % len(self.t.fuzzoffset)
            return
        st.add("sprite_pixels", yh - yl + 1)
        for y in range(yl, yh + 1):
            self.put(x, y, cmap[img[src + (f >> 8)]])
            f = (f + step) & 0xFFFF

    def render_masked_seg_range(self, ds, x1, x2):
        """R_RenderMaskedSegRange: a two-sided middle texture, columns x1..x2."""
        d, t, st = self.d, self.t, self.stats
        seg = ds.seg
        fs = d.sectors[seg.frontsector]
        bs = d.sectors[seg.backsector]
        side = d.sides[seg.sidedef]
        line = d.lines[seg.linedef]
        texnum = self.textrans[side.midtexture]
        tex = d.textures[texnum]
        v1, v2 = d.vertexes[seg.v1], d.vertexes[seg.v2]
        lightnum = (fs.lightlevel >> LIGHTSEGSHIFT) + self.extralight
        if v1.y == v2.y:
            lightnum -= 1
        elif v1.x == v2.x:
            lightnum += 1
        walllights = t.scalelight[max(0, min(LIGHTLEVELS - 1, lightnum))]
        spryscale = ds.scale1 + (x1 - ds.x1) * ds.scalestep
        if line.flags & ML_DONTPEGBOTTOM:
            mid = max(fs.floorheight, bs.floorheight) + tex.height
        else:
            mid = min(fs.ceilingheight, bs.ceilingheight)
        texturemid = (mid << SUBBITS) - self.vz + (side.yoffset << SUBBITS)
        img = d.banks[tex.bank]
        height = tex.height                                  # map units
        for x in range(x1, x2 + 1):
            tc = ds.maskedtexturecol.get(x)
            if tc is not None:
                st.add("masked_columns")
                if self.fixedcolormap is not None:
                    k = self.fixedcolormap
                else:
                    k = walllights[min(spryscale >> LIGHTSCALESHIFT, MAXLIGHTSCALE - 1)]
                cmap = d.colormap(tex.bank, k)
                sprtopscreen = (CENTERY << 16) - ((texturemid * spryscale) >> SUBBITS)
                bottomscreen = sprtopscreen + spryscale * height
                iscale = t.iscale(spryscale)
                st.add("mul_piece", 3)
                yl = (sprtopscreen + 0xFFFF) >> 16
                yh = (bottomscreen - 1) >> 16
                if yh >= self._clipval(ds.sprbottomclip, x):
                    yh = self._clipval(ds.sprbottomclip, x) - 1
                if yl <= self._clipval(ds.sprtopclip, x):
                    yl = self._clipval(ds.sprtopclip, x) + 1
                if yl <= yh:
                    base = tex.addr + ((tc & tex.wmask) << tex.log2h)
                    frac = (texturemid << 11) + (yl - CENTERY) * iscale
                    f = (frac >> 8) & 0xFFFF
                    step = ((iscale + 0x80) >> 8) & 0xFFFF
                    for y in range(yl, yh + 1):
                        c = img[base + ((f >> 8) & tex.hmask)]
                        if c != TRANSPARENT:
                            self.put(x, y, cmap[c])
                            st.add("masked_pixels")
                        f = (f + step) & 0xFFFF
                del ds.maskedtexturecol[x]
            spryscale += ds.scalestep

    def draw_psprite(self, psp):
        """R_DrawPSprite: the weapon, one texel per pixel, lit by the view's sector."""
        d, st = self.d, self.stats
        lf = self.sprite_lump(psp.sprite, psp.frame, 0)
        if lf is None:
            return
        lump, flip = lf
        s = d.sprlumps[lump]
        tx = ((psp.sx - (160 << 16)) >> 1) - (s.left << 16)
        x1 = ((CENTERX << 16) + tx) >> 16
        if x1 > VIEW_W - 1:
            return
        tx += s.width << 16
        x2 = (((CENTERX << 16) + tx) >> 16) - 1
        if x2 < 0:
            return
        vis = Vissprite()
        vis.lump, vis.flip = lump, flip
        vis.x1, vis.x2 = max(0, x1), min(VIEW_W - 1, x2)
        texturemid_t = (((BASEYCENTER << 16) + 0x8000 - psp.sy) >> 1) + (s.top << 16)
        if flip:
            vis.xiscale, vis.startfrac = -(1 << 16), (s.width << 16) - 1
        else:
            vis.xiscale, vis.startfrac = 1 << 16, 0
        if vis.x1 > x1:
            vis.startfrac += vis.xiscale * (vis.x1 - x1)
        if self.fixedcolormap is not None:
            vis.colormap = self.fixedcolormap
        elif psp.frame & FF_FULLBRIGHT:
            vis.colormap = 0
        else:
            sec = d.sectors[self.point_sector(self.vx, self.vy)]
            lightnum = max(0, min(LIGHTLEVELS - 1,
                                  (sec.lightlevel >> LIGHTSEGSHIFT) + self.extralight))
            vis.colormap = self.t.scalelight[lightnum][MAXLIGHTSCALE - 1]
        self.mfloorclip = {x: VIEW_H for x in range(vis.x1, vis.x2 + 1)}
        self.mceilingclip = {x: -1 for x in range(vis.x1, vis.x2 + 1)}
        sprtopscreen = (CENTERY << 16) - texturemid_t
        st.add("psprites")
        n0 = st.get("sprite_pixels", 0)
        self.draw_vissprite(vis, 1 << 16, 1 << 16, texturemid_t, sprtopscreen)
        st.add("psprite_pixels", st.get("sprite_pixels", 0) - n0)


# --- things as spawned -------------------------------------------------------------------------

# doomednum -> (sprite, frames, tics per frame, bright ("" none, "*" all, or
# a mask string per frame), flags). Flags: "C" spawned at the ceiling with
# height H ("C68"), "S" shadow (fuzz). Frames are Doom's spawn-state loops.
THING_TYPES = {
    # monsters (spawn state: standing)
    3004: ("POSS", "AB", 10, "", ""), 9: ("SPOS", "AB", 10, "", ""),
    3001: ("TROO", "AB", 10, "", ""), 3002: ("SARG", "AB", 10, "", ""),
    58: ("SARG", "AB", 10, "", "S"), 3006: ("SKUL", "AB", 10, "*", ""),
    3005: ("HEAD", "A", 10, "", ""), 3003: ("BOSS", "AB", 10, "", ""),
    16: ("CYBR", "AB", 10, "", ""), 7: ("SPID", "AB", 10, "", ""),
    # weapons, ammo, health, armour, powers, keys
    2001: ("SHOT", "A", 0, "", ""), 2002: ("MGUN", "A", 0, "", ""),
    2003: ("LAUN", "A", 0, "", ""), 2004: ("PLAS", "A", 0, "", ""),
    2005: ("CSAW", "A", 0, "", ""), 2006: ("BFUG", "A", 0, "", ""),
    2007: ("CLIP", "A", 0, "", ""), 2048: ("AMMO", "A", 0, "", ""),
    2008: ("SHEL", "A", 0, "", ""), 2049: ("SBOX", "A", 0, "", ""),
    2010: ("ROCK", "A", 0, "", ""), 2046: ("BROK", "A", 0, "", ""),
    2047: ("CELL", "A", 0, "", ""), 17: ("CELP", "A", 0, "", ""),
    8: ("BPAK", "A", 0, "", ""), 2011: ("STIM", "A", 0, "", ""),
    2012: ("MEDI", "A", 0, "", ""), 2013: ("SOUL", "ABCDCB", 6, "*", ""),
    2014: ("BON1", "ABCDCB", 6, "", ""), 2015: ("BON2", "ABCDCB", 6, "", ""),
    2018: ("ARM1", "AB", 6, "01", ""), 2019: ("ARM2", "AB", 6, "01", ""),
    2022: ("PINV", "ABCD", 6, "*", ""), 2023: ("PSTR", "A", 0, "*", ""),
    2024: ("PINS", "ABCD", 6, "*", ""), 2025: ("SUIT", "A", 0, "*", ""),
    2026: ("PMAP", "ABCDCB", 6, "*", ""), 2045: ("PVIS", "AB", 6, "10", ""),
    83: ("MEGA", "ABCD", 6, "*", ""),
    5: ("BKEY", "AB", 10, "01", ""), 6: ("YKEY", "AB", 10, "01", ""),
    13: ("RKEY", "AB", 10, "01", ""), 40: ("BSKU", "AB", 10, "01", ""),
    39: ("YSKU", "AB", 10, "01", ""), 38: ("RSKU", "AB", 10, "01", ""),
    # barrel, lights, decorations
    2035: ("BAR1", "AB", 6, "", ""), 2028: ("COLU", "A", 0, "*", ""),
    34: ("CAND", "A", 0, "*", ""), 35: ("CBRA", "A", 0, "*", ""),
    30: ("COL1", "A", 0, "", ""), 31: ("COL2", "A", 0, "", ""),
    32: ("COL3", "A", 0, "", ""), 33: ("COL4", "A", 0, "", ""),
    36: ("COL5", "AB", 14, "", ""), 37: ("COL6", "A", 0, "", ""),
    41: ("CEYE", "ABCB", 6, "*", ""), 42: ("FSKU", "ABC", 6, "*", ""),
    43: ("TRE1", "A", 0, "", ""), 54: ("TRE2", "A", 0, "", ""),
    44: ("TBLU", "ABCD", 4, "*", ""), 45: ("TGRN", "ABCD", 4, "*", ""),
    46: ("TRED", "ABCD", 4, "*", ""), 55: ("SMBT", "ABCD", 4, "*", ""),
    56: ("SMGT", "ABCD", 4, "*", ""), 57: ("SMRT", "ABCD", 4, "*", ""),
    47: ("SMIT", "A", 0, "", ""), 48: ("ELEC", "A", 0, "", ""),
    49: ("GOR1", "ABCB", 10, "", "C68"), 50: ("GOR2", "A", 0, "", "C84"),
    51: ("GOR3", "A", 0, "", "C84"), 52: ("GOR4", "A", 0, "", "C68"),
    53: ("GOR5", "A", 0, "", "C52"), 59: ("GOR2", "A", 0, "", "C84"),
    60: ("GOR4", "A", 0, "", "C68"), 61: ("GOR3", "A", 0, "", "C52"),
    62: ("GOR5", "A", 0, "", "C52"), 63: ("GOR1", "ABCB", 10, "", "C68"),
    # corpses and gore on the floor
    10: ("PLAY", "W", 0, "", ""), 12: ("PLAY", "W", 0, "", ""),
    15: ("PLAY", "N", 0, "", ""), 18: ("POSS", "L", 0, "", ""),
    19: ("SPOS", "L", 0, "", ""), 20: ("TROO", "M", 0, "", ""),
    21: ("SARG", "N", 0, "", ""), 22: ("HEAD", "L", 0, "", ""),
    24: ("POL5", "A", 0, "", ""), 25: ("POL1", "A", 0, "", ""),
    26: ("POL6", "AB", 6, "", ""), 27: ("POL4", "A", 0, "", ""),
    28: ("POL2", "A", 0, "", ""), 29: ("POL3", "AB", 6, "*", ""),
}
SKILL_BITS = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4}


def spawn_things(data: GameData, skill=4, tic=0):
    """The map's THINGS as Doom spawns them at `skill` (single player): the
    sprite and frame of each type's spawn state at game tic `tic`, z on the
    floor (or hanging from the ceiling). Player starts and unknown types are
    left out. Returns [Thing]."""
    r = Renderer(data)
    out = []
    for th in data.things:
        if th.flags & 16 or not th.flags & SKILL_BITS[skill]:
            continue
        spec = THING_TYPES.get(th.type)
        if spec is None:
            continue
        name, frames, tics, bright, flags = spec
        if name not in data.sprite_index:
            continue
        k = (tic // tics) % len(frames) if tics else 0
        frame = ord(frames[k]) - ord("A")
        if bright == "*" or (bright and bright[k] == "1"):
            frame |= FF_FULLBRIGHT
        x16, y16 = th.x << SUBBITS, th.y << SUBBITS
        sector = r.point_sector(x16, y16)
        sec = data.sectors[sector]
        if flags.startswith("C"):
            z = sec.ceilingheight - int(flags[1:])
        else:
            z = sec.floorheight
        thing = Thing(x16, y16, z << SUBBITS, round(th.angle * 65536 / 360),
                      data.sprite_index[name], frame, MF_SHADOW if "S" in flags else 0)
        thing.sector = sector
        out.append(thing)
    return out


def player_start(data: GameData, player=1):
    """The View at player `player`'s start: eye 41 units above the floor."""
    th = next(t for t in data.things if t.type == player)
    r = Renderer(data)
    sec = data.sectors[r.point_sector(th.x << SUBBITS, th.y << SUBBITS)]
    return View(th.x << SUBBITS, th.y << SUBBITS, (sec.floorheight + VIEWHEIGHT) << SUBBITS,
                round(th.angle * 65536 / 360))


def view_at(data: GameData, x, y, angle_deg, eye=VIEWHEIGHT):
    """A View at map (x, y) with the eye `eye` units above that point's floor."""
    r = Renderer(data)
    sec = data.sectors[r.point_sector(round(x * 16), round(y * 16))]
    return View.from_units(x, y, sec.floorheight + eye, angle_deg)


def weapon(data: GameData, name="PISG", frame=0):
    return PSprite(data.sprite_index[name], frame)


# --- output ------------------------------------------------------------------------------------

def to_png(buf, rgb, path, scale=4):
    """The view as the Appletini shows it: each game pixel 2x1 SHR pixels,
    each SHR pixel 2x4 on the 640x400 output, so 4x4 here (640x336)."""
    from PIL import Image
    img = Image.new("RGB", (VIEW_W, VIEW_H))
    px = img.load()
    for x in range(VIEW_W):
        for y in range(VIEW_H):
            px[x, y] = rgb[buf[VIEW_H * x + y]]
    img = img.resize((VIEW_W * scale, VIEW_H * scale), Image.NEAREST)
    img.save(path)


# --- viewpoints for the deliverables -------------------------------------------------------------

DOOR_SPECIALS = {1, 26, 27, 28, 31, 32, 33, 34, 46, 63, 90, 103, 105, 106, 107, 108, 109,
                 111, 112, 113, 114, 115, 116, 117, 118, 29, 50, 42, 61}


def _inside(r, data, x, y, sector=None, eye=VIEWHEIGHT):
    """Is (x, y) in a sector with room for the eye (and in `sector` if given)?"""
    s = r.point_sector(round(x * 16), round(y * 16))
    sec = data.sectors[s]
    if sector is not None and s != sector:
        return False
    return sec.ceilingheight - sec.floorheight >= eye + 8


def pick_views(data: GameData):
    """Three extra viewpoints for a map, chosen by rule so every map gets them:
    (1) along a corridor: the longest one-sided wall, from 32 units in from
        one end, halfway to the opposite wall (at most 128 units out);
    (2) up a flight of steps: the step line (two-sided, floors 1..24 apart)
        with the most other step lines within 256 units, seen from 192 units
        out on its lower side, with no wall within 256 units ahead (of the
        first eight such, the one that draws the most wall ranges);
    (3) facing a door from 96 units away.
    Returns [(label, View)]."""
    r = Renderer(data)
    views = []
    V = data.vertexes

    def length(l):
        return math.hypot(l.dx, l.dy)

    def wall_distance(x, y, dx, dy):
        """Distance along (dx, dy) from (x, y) to the nearest one-sided line."""
        best = 1e9
        for l in data.lines:
            if l.side1 != NONE16:
                continue
            x1, y1 = V[l.v1].x, V[l.v1].y
            ex, ey = l.dx, l.dy
            den = dx * ey - dy * ex
            if abs(den) < 1e-9:
                continue
            wx, wy = x1 - x, y1 - y
            t = (wx * ey - wy * ex) / den
            u = (wx * dy - wy * dx) / den
            if t > 0.5 and 0 <= u <= 1:
                best = min(best, t)
        return best

    # (1) corridor
    lines = sorted((l for l in data.lines if l.side1 == NONE16), key=length, reverse=True)
    for l in lines[:40]:
        L = length(l)
        ux, uy = l.dx / L, l.dy / L
        nx, ny = uy, -ux              # right of the line = its front side
        v = V[l.v1]
        x0, y0 = v.x + ux * 32 + nx * 2, v.y + uy * 32 + ny * 2
        w = wall_distance(x0, y0, nx, ny)
        off = min(w / 2, 128)
        if off < 20:
            continue
        x, y = x0 + nx * off, y0 + ny * off
        if _inside(r, data, x, y, l.frontsector):
            views.append(("corridor", view_at(data, x, y, math.degrees(math.atan2(uy, ux)))))
            break
    # (2) steps
    steps = []
    for l in data.lines:
        if l.side1 == NONE16 or length(l) < 32:
            continue
        df = data.sectors[l.backsector].floorheight - data.sectors[l.frontsector].floorheight
        if 0 < abs(df) <= 24:
            mx = (V[l.v1].x + V[l.v2].x) / 2
            my = (V[l.v1].y + V[l.v2].y) / 2
            steps.append((l, mx, my, df))
    ranked = sorted(steps, key=lambda s: -sum(1 for o in steps
                                             if math.hypot(o[1] - s[1], o[2] - s[2]) < 256))
    candidates = []
    for l, mx, my, df in ranked[:40]:
        L = length(l)
        nx, ny = l.dy / L, -l.dx / L      # towards the front side
        if df < 0:                         # the front side is higher: look from the back
            nx, ny = -nx, -ny
        low = l.frontsector if df > 0 else l.backsector
        x, y = mx + nx * 192, my + ny * 192
        if _inside(r, data, x, y) and wall_distance(x, y, -nx, -ny) > 256:
            view = view_at(data, x, y, math.degrees(math.atan2(-ny, -nx)))
            if data.sectors[r.point_sector(view.x, view.y)].floorheight <= \
                    data.sectors[low].floorheight + 24:
                candidates.append(view)
                if len(candidates) == 8:
                    break
    if candidates:
        # the one that shows the most (wall ranges drawn)
        views.append(("steps", max(candidates,
                                   key=lambda v: Renderer(data).render(v)[1].get("wall_ranges", 0))))
    # (3) a door
    for l in data.lines:
        if l.special in DOOR_SPECIALS and l.side1 != NONE16:
            L = length(l)
            if L < 32:
                continue
            ux, uy = l.dx / L, l.dy / L
            nx, ny = uy, -ux
            mx = (V[l.v1].x + V[l.v2].x) / 2
            my = (V[l.v1].y + V[l.v2].y) / 2
            x, y = mx + nx * 96, my + ny * 96
            if _inside(r, data, x, y, l.frontsector):
                views.append(("door", view_at(data, x, y, math.degrees(math.atan2(-ny, -nx)))))
                break
    # fallback (a map without some of the above): into the largest room
    if len(views) < 3:
        def extent(si):
            xs = [V[vi].x for l in data.lines if si in (l.frontsector, l.backsector)
                  for vi in (l.v1, l.v2)]
            ys = [V[vi].y for l in data.lines if si in (l.frontsector, l.backsector)
                  for vi in (l.v1, l.v2)]
            return min(xs), min(ys), max(xs), max(ys)
        boxes = [(si, extent(si)) for si in range(len(data.sectors))
                 if any(si in (l.frontsector, l.backsector) for l in data.lines)]
        boxes.sort(key=lambda b: -(b[1][2] - b[1][0]) * (b[1][3] - b[1][1]))
        for si, (x0, y0, x1, y1) in boxes:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            for ex, ey in ((x0, cy), (x1, cy), (cx, y0), (cx, y1)):
                x, y = cx + (ex - cx) * 0.8, cy + (ey - cy) * 0.8
                if _inside(r, data, x, y, si):
                    views.append(("room", view_at(data, x, y,
                                                  math.degrees(math.atan2(cy - y, cx - x)))))
                    break
            if len(views) >= 3:
                break
    return views


def random_views(data: GameData, n, seed=1):
    """n random views inside the map (a point strictly inside its subsector,
    with headroom), random angles; deterministic for a seed."""
    import random
    rnd = random.Random(seed)
    r = Renderer(data)
    V = data.vertexes
    xs, ys = [v.x for v in V], [v.y for v in V]
    out = []
    while len(out) < n:
        x, y = rnd.uniform(min(xs), max(xs)), rnd.uniform(min(ys), max(ys))
        x16, y16 = round(x * 16), round(y * 16)
        ss = data.subsectors[r.point_subsector(x16, y16)]
        segs = data.segs[ss.firstseg:ss.firstseg + ss.numsegs]
        if any(r.point_on_seg_side(x16, y16, sg) for sg in segs):
            continue            # outside the subsector's convex region: outside the map
        if not _inside(r, data, x, y):
            continue
        out.append(view_at(data, x, y, rnd.uniform(0, 360)))
    return out


def sweep(datadir, per_map=40, seed=1, limits=None):
    """Render per_map random views of every map (things and weapon on) and
    return the list of stats; limits: {"MAXVISPLANES": n, ...} to override."""
    g = globals()
    saved = {k: g[k] for k in (limits or {})}
    g.update(limits or {})
    try:
        manifest = json.loads((Path(datadir) / "manifest.json").read_text())
        out = []
        for mapname in sorted(manifest["maps"]):
            data = GameData(datadir, mapname)
            things = spawn_things(data)
            for view in random_views(data, per_map, seed):
                r = Renderer(data)
                _, st = r.render(view, things, [weapon(data)])
                st = dict(st)
                st["map"] = mapname
                out.append(st)
        return out
    finally:
        g.update(saved)


def summarize(stats, keys=None):
    keys = keys or [k for k in STAT_ORDER if any(k in s for s in stats)]
    lines = []
    for k in keys:
        vals = sorted(s.get(k, 0) for s in stats)
        n = len(vals)
        lines.append(f"{k:<16} mean {sum(vals) / n:8.0f}  p50 {vals[n // 2]:6d}  "
                     f"p90 {vals[int(n * 0.9)]:6d}  max {vals[-1]:6d}")
    return "\n".join(lines)


# --- command line -----------------------------------------------------------------------------

STAT_ORDER = ["nodes", "bsp_depth", "bbox_checks", "subsectors", "segs", "segs_facing",
              "wall_ranges", "wall_columns", "wall_pieces", "wall_pixels", "sky_columns",
              "sky_pixels", "planes_drawn", "span_rows", "spans", "span_pixels",
              "shaded_columns", "shaded_pixels", "masked_columns", "masked_pixels",
              "things", "sprites_drawn", "sprite_columns", "sprite_posts", "sprite_pixels",
              "psprite_pixels", "fuzz_pixels", "drawsegs", "visplanes", "openings",
              "vissprites", "div_slope", "div_scale", "div_step", "div_thing", "mul_side",
              "mul_seg", "mul_col", "mul_piece", "mul_span", "mul_thing", "mul_sprite",
              "mul_post"]


def format_stats(st):
    keys = [k for k in STAT_ORDER if k in st] + sorted(k for k in st if k not in STAT_ORDER)
    return " ".join(f"{k}={st[k]}" for k in keys)


def render_view(data, view, tic=0, things=True, weapon_on=True, shaded=False, extralight=0,
                check_writes=False):
    r = Renderer(data, shaded=shaded, check_writes=check_writes)
    th = spawn_things(data, tic=tic) if things else []
    psp = [weapon(data)] if weapon_on else []
    buf, st = r.render(view, th, psp, tic=tic, extralight=extralight)
    return r, buf, st


def deliverables(datadir, outdir, maps=None, shaded=False):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((Path(datadir) / "manifest.json").read_text())
    maps = maps or sorted(manifest["maps"])
    report = {}
    for mapname in maps:
        data = GameData(datadir, mapname)
        views = [("start", player_start(data))] + pick_views(data)
        for n, (label, view) in enumerate(views):
            t0 = time.time()
            r, buf, st = render_view(data, view, shaded=shaded)
            name = f"{mapname}_{n}"
            to_png(buf, data.rgb, outdir / f"{name}.png")
            report[name] = {"label": label, "view": repr(view), "stats": dict(st)}
            print(f"{name} {label:8s} {view!r} ({time.time() - t0:.1f}s)\n    {format_stats(st)}")
    (outdir / "stats.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=str(PROJECT / "build/data"))
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--start", action="store_true", help="view from player 1's start")
    ap.add_argument("--view", nargs=4, type=float, metavar=("X", "Y", "Z", "ANGLE"),
                    help="eye in map units (z absolute) and angle in degrees")
    ap.add_argument("--tic", type=int, default=0)
    ap.add_argument("--extralight", type=int, default=0)
    ap.add_argument("--shaded", action="store_true", help="flat-shaded floors and ceilings")
    ap.add_argument("--no-things", action="store_true")
    ap.add_argument("--no-weapon", action="store_true")
    ap.add_argument("--out", default="view.png")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--deliverables", action="store_true",
                    help="every map: the start and three chosen views, into --out-dir")
    ap.add_argument("--out-dir", default=str(PROJECT / "build/refrender"))
    ap.add_argument("--maps", help="with --deliverables: comma-separated maps")
    ap.add_argument("--sweep", type=int, metavar="N",
                    help="N random views per map with the limits lifted: work statistics")
    a = ap.parse_args(argv)
    if a.sweep:
        big = {"MAXVISPLANES": 10000, "MAXDRAWSEGS": 10000, "MAXOPENINGS": 1 << 20,
               "MAXVISSPRITES": 10000}
        stats = sweep(a.data, a.sweep, limits=big)
        print(f"{len(stats)} views ({a.sweep} per map), limits lifted:")
        print(summarize(stats))
        return 0
    if a.deliverables:
        deliverables(a.data, a.out_dir, a.maps.split(",") if a.maps else None, a.shaded)
        return 0
    data = GameData(a.data, a.map)
    view = View.from_units(*a.view) if a.view else player_start(data)
    r, buf, st = render_view(data, view, a.tic, not a.no_things, not a.no_weapon, a.shaded,
                             a.extralight)
    to_png(buf, data.rgb, a.out)
    print(f"{a.map} {view!r} -> {a.out}")
    if a.stats:
        print(format_stats(st))
    return 0


if __name__ == "__main__":
    sys.exit(main())
