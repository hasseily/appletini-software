#!/usr/bin/env python3
"""Synthetic frames for the paths of the frame that no capture reaches
(milestone 7, stage C; docs/RENDER.md 4.1 "Synthetic cases", 5.3), with
upstream's truth from ref816 --call.

Usage:  python3 tools/native/framesynth.py [--specs a,b,...]

Each synthetic frame starts from a captured frame (tools/native/
rendercap.py): its run goes on ref816 again to that frame's R_FillStamps,
which --capture records whole (all RAM and the registers at the entry;
the machine is deterministic, and the capture's bank $02 must equal the
frame's P0). The spec's pokes change that state; then --call runs the
frame from display's JSL to R_FillStamps (the capture's return address
less 3, with S above it) on the changed state, once for each of
rendercap's points, stopped there: R_FillStamps (P0), the return of
weaponClip in weaponClipSame (P1, the seam), R_RenderBSPNode (P0b),
drawMasked (P3), and milestone 8's after sortSkip (P3s), playerSkip
(P3w), stripEarly (PS), R_DrawLists (P4) and its return (P5), each
saving rendercap.py's ranges of the point. A run that reaches drawAllL
(an early flush) first is refused, but for a spec whose flushes are its
point (pagefull): its P2 dumps are kept, p2-K before drawMasked and p2m-K
after it. The result is a
frame directory of rendercap.py's format, build/native/render/frames/
synth-NAME/, whose frame.json names the base frame, the spec and its
pokes; calls.json has no calls: --call cannot run with ref816's call log,
so a synthetic frame has neither checkpoint A's wall calls nor the count
of vertex angles (render_check.py leaves both out for it).

The specs (SPECS): what the captures miss (render_check.py
--frame-mode's coverage):

    noweapon    no weapon (the psprite's state 0): weaponClipSame's "no
                weapon" (WPREV's lump $FFFF, no skip)
    shadow      the invisibility power: the shadow weapon (FR_VIS has no
                colormap)
    automap     the automap overlay (automapmode AM_ACTIVE | AM_OVERLAY,
                viewbottom AM_TITLEY as display sets it): no weapon skip,
                the view's row after it changes (W_BOTR: no old spans),
                the clips of the shorter view
    skyfixed    the fixed colormap 1 (the light amplification visor) on a
                frame with sky walls: the sky's colormap page (no capture
                has both)
    fsfill      W_FSC 127: the 128-frame refresh of the span stamps
                (fsFill; one captured frame does it at 0)
    fswrap      W_FSC 255: the stamp wraps to 0 and refreshes
    flat        a third of every made texture's columns without a patch
                (the top byte of its column entry 1): tierFlat, a K_FILL
                of the texture's colour with its span cut; the level is
                converted again from the frame's level source with the
                same pokes (levels/src/synth-flat-SRC)
    flatsky     the same on a frame with sky walls
    flatv06, flatv14
                the same on frames with loops of kind 6 and 14 (a bottom
                wall under a ceiling, no top wall), where upstream's
                tierFlat leaves DC_ROW (the row of the ceiling clip) at the
                tier's first row
    skyodd      the player's angle with the low 6 bits of its high word
                63 on a frame with sky walls: the captured angles are
                multiples of 64 (keyboard, demo) and xtoviewangle's of 8,
                so no capture shows a sky column one angle unit off; the
                game reaches such angles (the death view turns by ANG5 or
                to the attacker, p_user65.s:578-650)

milestone 8 (docs/RENDER-MASKED.md 4.1), the projection's paths:

    spectre     the nearest thing of a frame that skips the weapon rows
                given MF_SHADOW (a spectre: legal in E1M2 too): a shadow
                vissprite, sortSkip clearing FR_SKIP and W_WSK
    crowd       100 of the level's things (every other sector's list
                emptied) in one listed sector's list, placed in pairs at
                50 places in front of the player: the MAXVISSPRITES cut
                (80) and the sort's ties
    close       the nearest thing moved 12 units in front of the player and
                7 to its left, a second 20 units ahead at a fraction of a
                unit, a third 5 ahead and 21 to the left: magnified
                sprites (xscale 1.0 or more: wHi and FixedMul), x1 < 0, a
                fractional thing's qmulh, labsTZ's rejection (labs(tx) >
                tz << 2 within the SPRBOUND bound)
    edge        two things moved by a fraction so that the low word of xl
                (the first) and of xr (the second) would be 0 on the
                qmulh path: upstream's FixedMul fallback of x1 and x2
                (r_thing65.s:449-485), found with tools/native/
                projmodel.py on the frame's own state
    qmulh       a thing moved by a fraction so that upstream's qmulh in its
                G parts ("+ 0 or 1") gives another vissprite than the
                exact product would: no captured frame shows the + 1

milestone 8, stage C (docs/RENDER-MASKED.md 4.1), the weapon:

    invis       the invisibility power at 12 (below 4 * 32 + 1, its bit 3
                set: the flicker's shadow weapon, pspSprite's second test;
                shadow's 1000 takes the first) on a frame of demo3 with
                sprites: no clip pass, the weapon's K_FUZZ records
    flash       psprite 1 given the pistol's flash state (S_PISTOLFLASH) on
                a frame without one: the flash drawn by R_DrawVisSprite,
                no weapon skip
    skipwall    a frame that skips the weapon rows (FR_SKIP), its nearest
                thing moved 40 units ahead on the view's centre line, so
                that its sprite crosses the weapon's rows: wclipSprite
                (WTMP) on a sprite reaching the view's bottom
    wphigh      psprite 0's sy 60 units lower than WEAPONTOP (32): the
                weapon's top above row 0, where wpStart refuses the profile
                (V_YH0 + the minimum a < 0), so both the clip pass and the
                draw take R_DrawVisSprite (the old code; no capture takes
                it: the game keeps sy in 32-128, the full view's weapon
                stays below row 0)

milestone 8, stage B (docs/RENDER-MASKED.md 4.1, 5.2 item 3), the page
model and the masked walls (the placements found with tools/native/
maskmodel.py and projmodel.py on the base frames' own state):

    mwlong      20 of the level's things on one line of sight behind the
                masked walls of an E1M6 frame: their records fill the
                columns' pages, so a K_TEXC of a masked post is refused at a
                page's end (a K_TEX in an extra page)
    pagefull    80 things on the view's centre line from 60 units on, the
                farthest a shadow: every extra page is taken and upstream
                draws all lists early (a flush in the masked phase, kept as
                p2m-0), the shadow's K_FUZZ records before it
    mwclose     the player moved near the masked walls of the E1M6 frame,
                their lines without ML_DONTPEGBOTTOM (the level converted
                again), their sectors' ceilings 24 units higher: masked
                ranges at a scale of 1.0 or more (the step from
                FixedReciprocal) and texturemid from the lower ceiling
    mwlight     the front sectors of an E1M9 frame's masked walls at light
                96: a masked range whose ends differ in the distance light
                shows each column's page (the captured two-light ranges are
                in bright sectors, where PGT's clamp gives one page)

Runs are bounded (time, files) and under nice.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, \
    Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import rendercap as RC, routinesynth as RS  # noqa: E402
from ref816 import bounded, dumps, refimage, title  # noqa: E402

CALL_TIMEOUT = 300.0
MAX_FILE = 64 << 20
MM_COLDIR = 0x250000
OFS_PL_POWERS, PW_INVISIBILITY = 41, 2
OFS_PL_PSPRITES = 129
OFS_PL_FIXEDCOLORMAP = 127
OFS_PL_MO, OFS_MO_ANGLE = 0, 32         # framestate.py's
AM_ACTIVE_OVERLAY = 3
AM_TITLEY = 168 - 1 - 7
WPAGE = 0x000A00
W_FSC = 0xE8


class SynthError(Exception):
    pass


class Spec(NamedTuple):
    name: str
    base: str                   # the captured frame it starts from
    pokes: Callable             # (Memory, sym) -> [(address, bytes)]
    level: bool                 # the pokes change the level: convert a
                                #   level source with them
    flushes: bool = False       # early flushes are the point (milestone 8's
                                #   pagefull): their P2 dumps are kept


# -- the specs' pokes --------------------------------------------------------

def poke_noweapon(mem, sym):
    return [(sym.address('_g_player') + OFS_PL_PSPRITES, bytes(4))]


def poke_shadow(mem, sym):
    return [(sym.address('_g_player') + OFS_PL_POWERS + 2 * PW_INVISIBILITY,
             (1000).to_bytes(2, 'little'))]


def poke_automap(mem, sym):
    return [(sym.address('automapmode'),
             AM_ACTIVE_OVERLAY.to_bytes(2, 'little')),
            (sym.address('viewbottom'), AM_TITLEY.to_bytes(2, 'little'))]


def poke_fixed(mem, sym):
    """The light amplification visor's colormap (1) for the player: the
    sky's records take the fixed colormap's page."""
    return [(sym.address('_g_player') + OFS_PL_FIXEDCOLORMAP,
             (1).to_bytes(2, 'little'))]


def poke_angle_low(low6: int):
    """The player's mobj angle with bits 16-21 (the low 6 bits of
    viewangle16) set to low6: (viewangle >> 16) + xtoviewangle[x] then has
    all six bits below the sky's texel column set for some columns."""
    def pokes(mem, sym):
        mo = int.from_bytes(mem.get(sym.address('_g_player') + OFS_PL_MO,
                                    3), 'little')
        angle = int.from_bytes(mem.get(mo + OFS_MO_ANGLE, 4), 'little')
        angle = (angle & ~(0x3F << 16)) | (low6 << 16)
        return [(mo + OFS_MO_ANGLE, angle.to_bytes(4, 'little'))]
    return pokes


def poke_fsc(value: int):
    def pokes(mem, sym):
        return [(WPAGE + W_FSC, bytes([value]))]
    return pokes


# -- milestone 8: the things (offsets.inc) --------------------------------

OFS_MO_X, OFS_MO_Y, OFS_MO_Z, OFS_MO_SNEXT = 12, 16, 20, 24
OFS_MO_FLAGS, SIZEOF_MO = 94, 120
MF_SHADOW_BYTE, MF_SHADOW_BIT = 2, 4        # flags bit 18
OFS_SEC_THINGLIST, SIZEOF_SEC = 22, 58


def base_frame(name: str):
    from native import framestate as FS
    return FS.Frame(RC.FRAMES / name)


def nearest_things(name: str, sym, count: int = 2) -> List[int]:
    """The things (pointers) of the base frame's vissprites that are not
    shadows, the largest scale (the nearest) first."""
    from native import projmodel as PM
    vis = PM.vissprites_ref(base_frame(name).dump('p3'), sym)
    vis = [v for v in vis if v['colormap']]
    vis.sort(key=lambda v: -v['scale'])
    return [v['gx'] & 0xFFFFFF for v in vis[:count]]


def view_of(mem, sym) -> Tuple[int, int, int]:
    """The player's x, y and angle (fixed_t, BAM)."""
    mo = int.from_bytes(mem.get(sym.address('_g_player') + OFS_PL_MO, 3),
                        'little')
    g = lambda o: int.from_bytes(mem.get(mo + o, 4), 'little')  # noqa
    return g(OFS_MO_X), g(OFS_MO_Y), g(OFS_MO_ANGLE)


def ahead(mem, sym, forward: float, left: float) -> Tuple[int, int]:
    """A point `forward` units ahead of the player and `left` to its left,
    as fixed_t (the host's arithmetic: a place, not a result compared)."""
    import math
    x, y, angle = view_of(mem, sym)
    a = angle / 4294967296.0 * 2 * math.pi
    s32 = lambda v: v - (1 << 32) if v & 0x80000000 else v  # noqa
    px = s32(x) + round((forward * math.cos(a) - left * math.sin(a)) *
                        65536)
    py = s32(y) + round((forward * math.sin(a) + left * math.cos(a)) *
                        65536)
    return px & 0xFFFFFFFF, py & 0xFFFFFFFF


def poke_spectre(base: str):
    def pokes(mem, sym):
        th = nearest_things(base, sym, 1)[0]
        at = th + OFS_MO_FLAGS + MF_SHADOW_BYTE
        return [(at, bytes([mem.byte(at) | MF_SHADOW_BIT]))]
    return pokes


def poke_close(base: str):
    def pokes(mem, sym):
        near = nearest_things(base, sym, 3)
        if len(near) < 3:
            raise SynthError('%s has fewer than three things in view'
                             % base)
        x, y = ahead(mem, sym, 12, 7)
        out = [(near[0] + OFS_MO_X, (x & ~0xFFFF).to_bytes(4, 'little')),
               (near[0] + OFS_MO_Y, (y & ~0xFFFF).to_bytes(4, 'little'))]
        x, y = ahead(mem, sym, 20.3, -2.7)
        out += [(near[1] + OFS_MO_X, x.to_bytes(4, 'little')),
                (near[1] + OFS_MO_Y, y.to_bytes(4, 'little'))]
        # labs(tx) > tz << 2 inside the SPRBOUND bound: labsTZ rejects
        x, y = ahead(mem, sym, 5, 21)
        out += [(near[2] + OFS_MO_X, (x & ~0xFFFF).to_bytes(4, 'little')),
                (near[2] + OFS_MO_Y, (y & ~0xFFFF).to_bytes(4, 'little'))]
        return out
    return pokes


def poke_crowd(base: str, count: int = 100):
    """count of the level's things (the sector lists' order, not the
    player's) in the first listed sector's list, every other list empty,
    in pairs at count / 2 places in front of the player."""
    def pokes(mem, sym):
        frame = base_frame(base)
        a = sym.address
        secs = int.from_bytes(mem.get(a('_g_sectors'), 3), 'little')
        nsec = mem.word(a('_g_numsectors'))
        player = int.from_bytes(mem.get(a('_g_player') + OFS_PL_MO, 3),
                                'little')
        things = []
        for i in range(nsec):
            ptr = int.from_bytes(mem.get(secs + SIZEOF_SEC * i +
                                         OFS_SEC_THINGLIST, 3), 'little')
            while ptr:
                if ptr != player:
                    things.append(ptr)
                ptr = int.from_bytes(mem.get(ptr + OFS_MO_SNEXT, 3),
                                     'little')
        if len(things) < count:
            raise SynthError('%s: %d things, not %d' % (base, len(things),
                                                        count))
        things = things[:count]
        listed = frame.calls['addsprites'][0][0] & 0xFFFFFF
        out = []
        for i in range(nsec):
            head = secs + SIZEOF_SEC * i + OFS_SEC_THINGLIST
            if head != listed + OFS_SEC_THINGLIST:
                out.append((head, bytes(4)))
        out.append((listed + OFS_SEC_THINGLIST,
                    things[0].to_bytes(4, 'little')))
        for k, th in enumerate(things):
            nxt = things[k + 1] if k + 1 < len(things) else 0
            out.append((th + OFS_MO_SNEXT, nxt.to_bytes(4, 'little')))
            place = k // 2                  # two things a place: ties
            row, col = divmod(place, 10)
            forward = 96 + 40 * row
            left = (col - 4.5) * forward / 7.0
            x, y = ahead(mem, sym, forward, left)
            out.append((th + OFS_MO_X, (x & ~0xFFFF).to_bytes(4, 'little')))
            out.append((th + OFS_MO_Y, (y & ~0xFFFF).to_bytes(4, 'little')))
        return out
    return pokes


def poke_line(base: str, count: int, near: float, step: float,
              left: float, shadow: bool):
    """count of the level's things (the sector lists' order, not the
    player's) in the first listed sector's list, every other list empty,
    on one line of sight: thing k at `near + step k` units ahead and
    `left` times that to the left, at whole map units, so that their
    columns overlap and their records pile up in the same lists (the page
    model: extra pages, K_TEXC refused at a page's end, a flush). With
    `shadow`, the farthest (drawn first) is given MF_SHADOW: its K_FUZZ
    records come before any flush."""
    def pokes(mem, sym):
        frame = base_frame(base)
        a = sym.address
        secs = int.from_bytes(mem.get(a('_g_sectors'), 3), 'little')
        nsec = mem.word(a('_g_numsectors'))
        player = int.from_bytes(mem.get(a('_g_player') + OFS_PL_MO, 3),
                                'little')
        things = []
        for i in range(nsec):
            ptr = int.from_bytes(mem.get(secs + SIZEOF_SEC * i +
                                         OFS_SEC_THINGLIST, 3), 'little')
            while ptr:
                if ptr != player:
                    things.append(ptr)
                ptr = int.from_bytes(mem.get(ptr + OFS_MO_SNEXT, 3),
                                     'little')
        if len(things) < count:
            raise SynthError('%s: %d things, not %d' % (base, len(things),
                                                        count))
        things = things[:count]
        listed = frame.calls['addsprites'][0][0] & 0xFFFFFF
        out = []
        for i in range(nsec):
            head = secs + SIZEOF_SEC * i + OFS_SEC_THINGLIST
            if head != listed + OFS_SEC_THINGLIST:
                out.append((head, bytes(4)))
        out.append((listed + OFS_SEC_THINGLIST,
                    things[0].to_bytes(4, 'little')))
        for k, th in enumerate(things):
            nxt = things[k + 1] if k + 1 < len(things) else 0
            out.append((th + OFS_MO_SNEXT, nxt.to_bytes(4, 'little')))
            forward = near + step * k
            x, y = ahead(mem, sym, forward, left * forward)
            out.append((th + OFS_MO_X, (x & ~0xFFFF).to_bytes(4, 'little')))
            out.append((th + OFS_MO_Y, (y & ~0xFFFF).to_bytes(4, 'little')))
            at = th + OFS_MO_FLAGS + MF_SHADOW_BYTE
            flags = mem.byte(at) & ~MF_SHADOW_BIT
            if shadow and k == count - 1:
                flags |= MF_SHADOW_BIT
            out.append((at, bytes([flags])))
        return out
    return pokes


OFS_SEG_LINENUM, SIZEOF_LINE, OFS_LINE_FLAGS = 14, 36, 26
ML_DONTPEGBOTTOM = 16
OFS_SEG_FRONTSECTORNUM, OFS_SEC_CEILINGHEIGHT = 16, 4


def poke_mwclose(base: str, forward: float, left: float, ceil: int):
    """The player moved `forward` units ahead and `left` to its left, near
    the base frame's masked walls, whose lines lose ML_DONTPEGBOTTOM (the
    masked texture hangs from the lower ceiling) and whose sectors' ceilings
    rise `ceil` units (so the texture no longer spans floor to ceiling, and
    the two pegs give different texturemids): a masked range at a scale of
    1.0 or more (the step from FixedReciprocal), texturemid from the lower
    ceiling. The line flags are level data too: the level is converted
    again with the pokes."""
    def pokes(mem, sym):
        from native import rcanon
        frame = base_frame(base)
        a = sym.address
        p3 = frame.dump('p3')
        segs = p3.u(a('_g_segs'), 3)
        lines = int.from_bytes(mem.get(a('_g_lines'), 3), 'little')
        secs = int.from_bytes(mem.get(a('_g_sectors'), 3), 'little')
        out = []
        seen = set()
        for i in range(p3.u(rcanon.DS_COUNT, 2)):
            ds = rcanon.ref_drawseg(p3, sym, i, segs)
            if ds['masked'] is None:
                continue
            line = int.from_bytes(mem.get(segs + 18 * ds['seg'] +
                                          OFS_SEG_LINENUM, 2), 'little')
            for o in (OFS_SEG_FRONTSECTORNUM, OFS_SEG_FRONTSECTORNUM + 1):
                sec = mem.byte(segs + 18 * ds['seg'] + o)
                if ('sector', sec) in seen:
                    continue
                seen.add(('sector', sec))
                at = secs + SIZEOF_SEC * sec + OFS_SEC_CEILINGHEIGHT
                h = int.from_bytes(mem.get(at, 4), 'little')
                out.append((at, ((h + (ceil << 16)) & 0xFFFFFFFF)
                            .to_bytes(4, 'little')))
            if line in seen:
                continue
            seen.add(line)
            at = lines + SIZEOF_LINE * line + OFS_LINE_FLAGS
            out.append((at, bytes([mem.byte(at) & ~ML_DONTPEGBOTTOM])))
        if not out:
            raise SynthError('%s has no masked wall' % base)
        mo = int.from_bytes(mem.get(a('_g_player') + OFS_PL_MO, 3),
                            'little')
        x, y = ahead(mem, sym, forward, left)
        out += [(mo + OFS_MO_X, (x & ~0xFFFF).to_bytes(4, 'little')),
                (mo + OFS_MO_Y, (y & ~0xFFFF).to_bytes(4, 'little'))]
        return out
    return pokes


OFS_SEC_LIGHTLEVEL = 48


def poke_mwlight(base: str, light: int):
    """The front sectors of the base frame's masked walls given the light
    level `light`: in a dark sector each step of the distance light d
    (min(23, spryscale >> 13)) is another colormap page, so a masked range
    whose ends differ in d shows its columns' own pages (the captured two-
    light ranges are in bright sectors, where PGT's clamp gives one page)."""
    def pokes(mem, sym):
        from native import rcanon
        frame = base_frame(base)
        a = sym.address
        p3 = frame.dump('p3')
        segs = p3.u(a('_g_segs'), 3)
        secs = int.from_bytes(mem.get(a('_g_sectors'), 3), 'little')
        out, seen = [], set()
        for i in range(p3.u(rcanon.DS_COUNT, 2)):
            ds = rcanon.ref_drawseg(p3, sym, i, segs)
            if ds['masked'] is None:
                continue
            sec = mem.byte(segs + 18 * ds['seg'] + OFS_SEG_FRONTSECTORNUM)
            if sec in seen:
                continue
            seen.add(sec)
            out.append((secs + SIZEOF_SEC * sec + OFS_SEC_LIGHTLEVEL,
                        light.to_bytes(2, 'little')))
        if not out:
            raise SynthError('%s has no masked wall' % base)
        return out
    return pokes


class _Dump:
    """refimage.Memory as the dumps' interface (projmodel's reads)."""

    def __init__(self, mem):
        self.mem = mem

    def u(self, address: int, size: int) -> int:
        return int.from_bytes(self.mem.get(address, size), 'little')

    def read(self, address: int, length: int) -> bytes:
        return self.mem.get(address, length)


def poke_edge(base: str):
    """Two things of the frame moved by a fraction of a unit (along x or y,
    whichever the view's sine or cosine moves tx more with) so that, on
    the qmulh path, the low word of xl (the first) and of xr (the second)
    would be 0: upstream then takes FixedMul (projmodel.py finds the
    fractions on the frame's own state; things of xscale below 1.0, the
    nearest first)."""
    def pokes(mem, sym):
        from native import projmodel as PM
        frame = base_frame(base)
        v = PM.frame_view(frame.dump('p0b'), sym)
        gz0, gx0 = PM.g_parts(v)
        lm = PM._level_memory(frame.meta['level_src'])
        spr = PM.Sprites(lm, sym)
        smap = [lm.u16(sym.address('SMAP') + 2 * i) for i in range(64)]
        cmo = [lm.u16(sym.address('CMO') + 2 * i) for i in range(85)]
        csign, ssign = v['viewcos'] >> 31, v['viewsin'] >> 31
        s32 = lambda x: x - (1 << 32) if x & 0x80000000 else x  # noqa
        along = OFS_MO_X if abs(s32(v['viewsin'])) >= \
            abs(s32(v['viewcos'])) else OFS_MO_Y
        vis = PM.vissprites_ref(frame.dump('p3'), sym)
        cands = [v_['gx'] & 0xFFFFFF for v_ in sorted(
            vis, key=lambda v_: -v_['scale'])
            if v_['colormap'] and v_['scale'] < 0x20000]
        dump = _Dump(mem)
        out, used = [], set()
        for which in ('xl', 'xr'):
            for th in cands:
                if th in used:
                    continue
                c0 = dump.u(th + along, 4)
                hit = None
                for frac in range(1, 0x10000):
                    val = ((c0 & ~0xFFFF) | frac).to_bytes(4, 'little')
                    trial = _Poked(mem, {th + along: val})
                    paths = []
                    got = PM.project_one(_Dump(trial), th, v, gz0, gx0, spr,
                                         smap[40], cmo,
                                         sym.address('fullcolormap'),
                                         csign, ssign, 0, paths, lm, sym)
                    if got is not None and 'fixmulx:' + which in paths:
                        hit = val
                        break
                if hit is not None:
                    out.append((th + along, hit))
                    used.add(th)
                    break
            else:
                raise SynthError('%s: no fraction takes the FixedMul of %s'
                                 % (base, which))
        return out
    return pokes


def poke_qmulh(base: str):
    """A thing of the frame moved by a fraction of a unit (along x) so that
    upstream's qmulh ("+ 0 or 1" in the last bit) in its G parts gives
    another vissprite than the exact product would (a fracstep, a scale
    or an x1 one off): no captured frame shows it (projmodel.py finds the
    fraction)."""
    def pokes(mem, sym):
        from native import projmodel as PM
        frame = base_frame(base)
        v = PM.frame_view(frame.dump('p0b'), sym)
        gz0, gx0 = PM.g_parts(v)
        lm = PM._level_memory(frame.meta['level_src'])
        spr = PM.Sprites(lm, sym)
        smap = [lm.u16(sym.address('SMAP') + 2 * i) for i in range(64)]
        cmo = [lm.u16(sym.address('CMO') + 2 * i) for i in range(85)]
        csign, ssign = v['viewcos'] >> 31, v['viewsin'] >> 31
        real = PM.gpart
        exact = lambda low, b, _e: real(low, b, True)  # noqa: E731

        def one(trial, th, gp):
            PM.gpart = gp
            try:
                return PM.project_one(_Dump(trial), th, v, gz0, gx0, spr,
                                      smap[40], cmo,
                                      sym.address('fullcolormap'), csign,
                                      ssign, 0, [], lm, sym)
            finally:
                PM.gpart = real
        for th in nearest_things(base, sym, 6):
            x0 = _Dump(mem).u(th + OFS_MO_X, 4)
            for frac in range(1, 0x10000):
                val = ((x0 & ~0xFFFF) | frac).to_bytes(4, 'little')
                trial = _Poked(mem, {th + OFS_MO_X: val})
                a, b = one(trial, th, real), one(trial, th, exact)
                if a is not None and a != b:
                    return [(th + OFS_MO_X, val)]
        raise SynthError('%s: no fraction shows qmulh' % base)
    return pokes


# -- milestone 8, stage C: the weapon ---------------------------------------

OFS_PSP_STATE, OFS_PSP_SY, SIZEOF_PSP = 0, 8, 12
STATE_SIZE = 16                 # info.inc
S_PISTOLFLASH = 17              # offsets.inc CONST_S_PISTOLFLASH


def poke_invis(value: int):
    def pokes(mem, sym):
        return [(sym.address('_g_player') + OFS_PL_POWERS +
                 2 * PW_INVISIBILITY, value.to_bytes(2, 'little'))]
    return pokes


def poke_flash(mem, sym):
    at = sym.address('_g_player') + OFS_PL_PSPRITES + SIZEOF_PSP
    if int.from_bytes(mem.get(at + OFS_PSP_STATE, 4), 'little'):
        raise SynthError('the base frame has a flash')
    state = sym.address('states') + STATE_SIZE * S_PISTOLFLASH
    return [(at + OFS_PSP_STATE, state.to_bytes(4, 'little'))]


def poke_wphigh(mem, sym):
    at = sym.address('_g_player') + OFS_PL_PSPRITES + OFS_PSP_SY
    return [(at, ((32 - 60) << 16 & 0xFFFFFFFF).to_bytes(4, 'little'))]


def poke_skipwall(base: str):
    def pokes(mem, sym):
        frame = base_frame(base)
        if not frame.dump('p3s').u(sym.address('FR_SKIP'), 2):
            raise SynthError('%s does not skip the weapon rows' % base)
        th = nearest_things(base, sym, 1)[0]
        x, y = ahead(mem, sym, 40, 0)
        return [(th + OFS_MO_X, (x & ~0xFFFF).to_bytes(4, 'little')),
                (th + OFS_MO_Y, (y & ~0xFFFF).to_bytes(4, 'little'))]
    return pokes


class _Poked:
    """A memory with some bytes changed (the search's trial)."""

    def __init__(self, mem, pokes: Dict[int, bytes]):
        self.mem = mem
        self.pokes = pokes

    def get(self, address: int, length: int) -> bytes:
        data = bytearray(self.mem.get(address, length))
        for at, b in self.pokes.items():
            for k in range(len(b)):
                if address <= at + k < address + length:
                    data[at + k - address] = b[k]
        return bytes(data)


def poke_flat(mem, sym):
    """Every made texture's columns c with c % 3 == 1: the top byte of the
    column entry 1 (upstream's "no patch", r_seg65.s:1509; TIER's test is
    the entry's high word >= $0100)."""
    out = []
    for t in range(256):
        entry = mem.get(MM_COLDIR + 4 * t, 4)
        if entry[2] == 0 and entry[3] == 0:
            continue
        table = entry[0] | entry[1] << 8 | entry[2] << 16
        for c in range(entry[3] + 1):
            if c % 3 == 1:
                out.append((table + 4 * c + 3, b'\x01'))
    if not out:
        raise SynthError('no texture made')
    return out


SPECS = (
    Spec('noweapon', 'still-2', poke_noweapon, False),
    Spec('shadow', 'still-2', poke_shadow, False),
    Spec('automap', 'newgame-10', poke_automap, False),
    Spec('skyfixed', 'tour-46', poke_fixed, False),
    Spec('fsfill', 'still-1', poke_fsc(127), False),
    Spec('fswrap', 'demo-10', poke_fsc(255), False),
    Spec('flat', 'still-1', poke_flat, True),
    Spec('flatsky', 'newgame-18', poke_flat, True),
    Spec('flatv06', 'demo-10', poke_flat, True),
    Spec('flatv14', 'title-14', poke_flat, True),
    Spec('skyodd', 'tour-46', poke_angle_low(63), False),
    # milestone 8, stage A
    Spec('spectre', 'tour-11', poke_spectre('tour-11'), False),
    Spec('crowd', 'tour-10', poke_crowd('tour-10'), False),
    Spec('close', 'title-35', poke_close('title-35'), False),
    Spec('edge', 'tour-10', poke_edge('tour-10'), False),
    Spec('qmulh', 'demo3-371', poke_qmulh('demo3-371'), False),
    # milestone 8, stage B (the page model and the masked walls; the
    # placements found with tools/native/maskmodel.py and projmodel.py on
    # the base frames' own state)
    Spec('mwlong', 'tour-31', poke_line('tour-31', 20, 280, 2, -0.75,
                                        False), False),
    Spec('pagefull', 'tour-10', poke_line('tour-10', 80, 60, 2, 0.0, True),
         False, True),
    Spec('mwclose', 'tour-31', poke_mwclose('tour-31', 150, -95, 24),
         True),
    Spec('mwlight', 'tour-46', poke_mwlight('tour-46', 96), False),
    # milestone 8, stage C (the weapon)
    Spec('invis', 'title-25', poke_invis(12), False),
    Spec('flash', 'title-25', poke_flash, False),
    Spec('skipwall', 'title-18', poke_skipwall('title-18'), False),
    Spec('wphigh', 'title-25', poke_wphigh, False),
)


# ---------------------------------------------------------------------------
# The machine
# ---------------------------------------------------------------------------

def parse_ranges(text: str) -> List[Tuple[int, int]]:
    """rendercap.ranges_of's text as (address, length) pairs."""
    out = []
    for item in text.split('+'):
        if ':' in item:
            address, length = item.split(':')
            out.append((int(address, 16), int(length)))
        elif '-' in item:
            first, last = (int(x, 16) for x in item.split('-'))
            out.append((first << 16, (last - first + 1) << 16))
        else:
            out.append((int(item, 16) << 16, 0x10000))
    return out


def run_to(entry: Path, pokes: Optional[Path], start: int, s: int,
           stops: Sequence[int], ranges: List[Tuple[int, int]], work: Path
           ) -> Tuple[Dict, dumps.Dump]:
    """ref816 --call from `start` (S = s) on the image and the pokes,
    stopped at the first of `stops`: the final state and the ranges as
    one dump (its header's cpu: the registers there)."""
    command = ['nice', '-n', '10', str(title.MACHINE), str(entry)]
    if pokes is not None:
        command += ['--load-image', str(pokes)]
    files = []
    for k, (address, length) in enumerate(ranges):
        path = work / ('save-%d.bin' % k)
        files.append(path)
        command += ['--save', '%06X:0x%X:%s' % (address, length, path)]
    command += ['--reg', 's=%X' % s, '--call', '%06X' % start,
                '--cycles', '400000000']
    for stop in stops:
        command += ['--stop-pc', '%06X' % stop]
    result = bounded.run(command, timeout=CALL_TIMEOUT, max_bytes=MAX_FILE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    if result.returncode:
        raise SynthError('--call failed (%d): %s' % (result.returncode,
                                                     result.stderr[-1000:]))
    state = json.loads(result.stdout)
    data = b''.join(p.read_bytes() for p in files)
    for p in files:
        p.unlink()
    header = {'cpu': RS.registers_of(state),
              'cycles': state.get('cycles', 0),
              'ranges': [list(r) for r in ranges], 'bytes': len(data)}
    return state, dumps.Dump(header, data)


FLUSH_LIMIT = 64                # early flushes a synthetic frame may have


def flush_dumps(entry: Path, pokes: Path, start: int, s: int, stop: int,
                sym, work: Path) -> List[dumps.Dump]:
    """ref816 --call from `start` to `stop` with a --dump-at point at
    drawAllL (rendercap.py's P2 ranges): the early flushes' dumps, in
    order. Bounded: at most FLUSH_LIMIT dumps, and the stream's size."""
    ranges = RC.ranges_of('P2', sym)
    point = dumps.resolve('pc=%s,ranges=%s' % (RC.capture.FLUSH, ranges),
                          sym)
    stream = work / 'flush.stream'
    state = work / 'flush-state.json'
    command = ['nice', '-n', '10', str(title.MACHINE), str(entry),
               '--load-image', str(pokes), '--reg', 's=%X' % s,
               '--call', '%06X' % start, '--cycles', '400000000',
               '--stop-pc', '%06X' % stop, '--dump-at', point,
               '--dump-stream', str(stream), '--state', str(state),
               '--dump-max', str(FLUSH_LIMIT),
               '--dump-limit', str(FLUSH_LIMIT * RC.DUMP_BYTES['P2'] * 2)]
    result = bounded.run(command, timeout=CALL_TIMEOUT, max_bytes=MAX_FILE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    if result.returncode:
        raise SynthError('--call with the flush dumps failed (%d): %s'
                         % (result.returncode, result.stderr[-1000:]))
    with open(str(stream), 'rb') as handle:
        out = list(dumps.read(handle))
    stream.unlink()
    state.unlink()
    return out


def check_p0(d: dumps.Dump, base: dumps.Dump, pokes) -> None:
    """The run reaches R_FillStamps with the frame's state: its P0 equals
    the captured frame's, the pokes applied, in every range they share."""
    poked = refimage.Memory()
    for address, length in base.header['ranges']:
        poked.put(address, base.get(address, length))
    for address, data in pokes:
        if poked.is_known(address):
            poked.put(address, data)
    for address, length in d.header['ranges']:
        want = poked.get(address, length)
        got = d.get(address, length)
        if got != want:
            bad = next(i for i in range(length) if got[i] != want[i])
            raise SynthError('P0 differs from the frame\'s at $%06X'
                             % (address + bad))


def level_source(spec: Spec, base_src: str, pokes) -> str:
    """The frame's level source with the pokes (a new source, so a new
    conversion): its name."""
    name = 'synth-%s-%s' % (spec.name, base_src)
    ram = bytearray(RC.load_ram(RC.LEVEL_SOURCES / (base_src + '.ram.z')))
    for address, data in pokes:
        bank = address >> 16
        if bank >= 0x80:
            raise SynthError('a level poke outside banks $00-$7F')
        at = (bank << 16) | (address & 0xFFFF)
        ram[at:at + len(data)] = data
    (RC.LEVEL_SOURCES / (name + '.ram.z')).write_bytes(
        zlib.compress(bytes(ram), 6))
    info = json.loads((RC.LEVEL_SOURCES / (base_src + '.json')).read_text())
    info.update({'name': name, 'synthetic': spec.name, 'base': base_src,
                 'pokes': len(pokes)})
    (RC.LEVEL_SOURCES / (name + '.json')).write_text(
        json.dumps(info, indent=1) + '\n')
    return name


def make_one(spec: Spec, sym, work: Path) -> Dict[str, Any]:
    base_dir = RC.FRAMES / spec.base
    meta = json.loads((base_dir / 'frame.json').read_text())
    run = next(r for r in RC.RUNS if r.key == meta['run'])
    fs = sym.address('R_FillStamps')
    image = RS.capture_entry(run, fs, meta['frame']['fs_hit'], sym, work)
    mem = refimage.Memory(image.records)
    p0 = RC.load_dump(base_dir / 'p0.dump.z')
    if mem.get(0x020000, 0x10000) != p0.get(0x020000, 0x10000):
        raise SynthError('the capture is not the frame\'s R_FillStamps')
    regs = image.registers
    s = regs.s
    ret = int.from_bytes(mem.get(s + 1, 3), 'little')
    start = ret - 3                     # display's JSL R_FillStamps
    if mem.byte(start) != 0x22 or \
            int.from_bytes(mem.get(start + 1, 3), 'little') != fs:
        raise SynthError('the return address is not after a JSL '
                         'R_FillStamps')
    pokes = spec.pokes(mem, sym)
    entry_path = work / 'entry.img'
    entry_path.write_bytes(refimage.image_bytes(regs, image.switches,
                                                image.records))
    poke_path = work / 'pokes.img'
    poke_path.write_bytes(refimage.image_bytes(
        regs, image.switches, [(a, bytes(d)) for a, d in pokes]))
    out = RC.FRAMES / ('synth-' + spec.name)
    staging = work / 'frame'
    staging.mkdir()
    # each point is reached before an early flush (drawAllL), which
    # would refuse the spec
    flush = sym.address(RC.capture.FLUSH)
    cycles = {}
    r = RC.routines(sym)
    where_of = {'P0': 'fs', 'P1': 'seam', 'P0b': 'bsp', 'P3': 'dm',
                'P3s': 'dm3', 'P3w': 'ps', 'PS': 'se', 'P4': 'dl',
                'P5': 'dlr'}
    stops = (flush,) if not spec.flushes else ()
    for kind, _, what in RC.FRAME_POINTS:
        where = r[where_of[kind]]
        st, d = run_to(entry_path, poke_path, start, s + 3,
                       (where,) + stops,
                       parse_ranges(RC.ranges_of(kind, sym)), work)
        if st['end']['reason'] != 'stop-pc':
            raise SynthError('%s: --call ended with %s' % (
                what, st['end']['reason']))
        if st['end']['pc'] != where:
            raise SynthError('%s: the frame flushes its lists early'
                             % what)
        if what == 'p0':
            check_p0(d, p0, pokes)
        RC.write_dump(staging / (what + '.dump.z'), d)
        cycles[what] = d.header['cycles']
    flushes = mflushes = 0
    if spec.flushes:
        # the early flushes: a P2 dump at each drawAllL up to R_DrawLists'
        # return (P5), before drawMasked (p2-K) or after it (p2m-K)
        found = flush_dumps(entry_path, poke_path, start, s + 3,
                            r[where_of['P5']], sym, work)
        if not found:
            raise SynthError('the frame does not flush early')
        for d in found:
            if d.header['cycles'] < cycles['p3']:
                name = 'p2-%d' % flushes
                flushes += 1
            else:
                name = 'p2m-%d' % mflushes
                mflushes += 1
            RC.write_dump(staging / (name + '.dump.z'), d)
    level_src = meta['level_src']
    if spec.level:
        level_src = level_source(spec, level_src, pokes)
    meta = dict(meta, name='synth-' + spec.name, set='synth',
                synthetic=spec.name, base=spec.base, level_src=level_src,
                flushes=flushes, mflushes=mflushes, call_cycles=cycles,
                pokes=[[a, bytes(d).hex()] for a, d in pokes])
    (staging / 'frame.json').write_text(json.dumps(meta, indent=1) + '\n')
    (staging / 'calls.json').write_text(json.dumps(
        {'storewall': [], 'vtxangle': None, 'textures': []}) + '\n')
    if out.exists():
        shutil.rmtree(str(out))
    shutil.move(str(staging), str(out))
    return {'spec': spec.name, 'base': spec.base, 'pokes': len(pokes),
            'level_src': level_src, 'frame': str(out)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--specs', default=','.join(s.name for s in SPECS))
    args = parser.parse_args(argv)
    wanted = args.specs.split(',')
    specs = [s for s in SPECS if s.name in wanted]
    if len(specs) != len(wanted):
        parser.error('unknown spec in %s' % args.specs)
    for s in specs:
        if not (RC.FRAMES / s.base / 'frame.json').exists():
            print('no frame %s: run python3 tools/native/rendercap.py'
                  % s.base, file=sys.stderr)
            return 1
    title.build_machine()
    title.ensure_image()
    sym = dumps.symbols()
    RC.check_disk(RC.FRAMES)
    failed = 0
    for spec in specs:
        work = Path(tempfile.mkdtemp(prefix='tmp-render-fsynth-',
                                     dir=str(RC.make_image.BUILD)))
        try:
            res = make_one(spec, sym, work)
            print('%-9s from %s, %d pokes%s' % (
                res['spec'], res['base'], res['pokes'],
                ', level source %s' % res['level_src']
                if spec.level else ''), flush=True)
        except (SynthError, RS.SynthError, RuntimeError) as error:
            print('%-9s FAILED: %s' % (spec.name, error), flush=True)
            failed += 1
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
