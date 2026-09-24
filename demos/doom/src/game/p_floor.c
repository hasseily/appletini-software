/* Doom for the Appletini -- moving floors and stairs (docs/DESIGN.md
 * section 9): vanilla p_floor.c (T_MovePlane is in p_spec.c).
 *
 *   T_MoveFloor     the floor thinker; at its destination a donut's slime
 *                   and lowerAndChange take their new flat and special
 *   EV_DoFloor      the tagged sectors (EV_DoFloorTag: A_BossDeath's 666)
 *   EV_BuildStairs  vanilla's stairs: from each tagged sector, the next
 *                   step is the back sector of a two-sided line whose
 *                   front is this step, if it has the same flat
 *
 * raiseToTexture's texture heights come from the TEX records (the
 * texture's Doom height); texture 0 ("-", none) is not counted, where
 * vanilla took texture 0's height.
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)   /* on the 6502: a_movers.s */

void T_MoveFloor(thinker_t *t)
{
    floormove_t *f = (floormove_t *)t;
    uint16_t s = f->m.sector;
    uint8_t res = T_MovePlane(&f->m, f->floordestheight, f->crush, 0, f->direction);

    if (!(leveltime & 7))
        S_StartSound(0, sfx_stnmov);
    if (res != res_pastdest)
        return;
    if (f->direction == 1 ? f->m.type == donutRaise : f->m.type == lowerAndChange) {
        P_SetSectorSpecial(s, f->newspecial);
        P_SetSectorFloorPic(s, f->texture);
    }
    P_RemoveMover(&f->m);
    S_StartSound(0, sfx_pstop);
}

/* the Doom height of a sidedef's lower texture, 0x7FFF if none */
static int16_t bottom_height(uint16_t side)
{
    uint16_t tex;
    int16_t h;

    if (side == NO_INDEX)
        return INT16_MAX;
    far_read(P_LevAddr(MAPARR_SIDEDEFS, side) + SIDEDEF_BOTTOMTEXTURE, &tex, 2);
    if (!tex)
        return INT16_MAX;
    far_read(FAR(DD_DIR_BANK, DD_TEXDIR + TEX_SIZE * tex + TEX_HEIGHT), &h, 2);
    return h;
}

#ifndef __CC65__
/* (the host build records the calls for the monsters part's tests) */
uint16_t ev_floortag_tag, ev_floortag_calls;
#endif

int16_t EV_DoFloorTag(uint16_t tag, uint8_t type)
{
    uint16_t cursor = 0, s, first, count, n, ln, other;
    int16_t rtn = 0, h, minsize;
    int32_t dest;
    floormove_t *f;
    line_t *li;

#ifndef __CC65__
    ev_floortag_tag = tag;
    ++ev_floortag_calls;
#endif
    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        if (SEC_BUSY(s))
            continue;               /* already moving: keep going */
        rtn = 1;
        f = (floormove_t *)P_NewMover(T_MoveFloor, sizeof *f, s);
        f->m.type = type;
        f->m.speed = FLOORSPEED;
        f->direction = 1;
        switch (type) {
        case lowerFloor:
            f->direction = -1;
            f->floordestheight = P_FindHighestFloorSurrounding(s);
            break;
        case lowerFloorToLowest:
            f->direction = -1;
            f->floordestheight = P_FindLowestFloorSurrounding(s);
            break;
        case turboLower:
            f->direction = -1;
            f->m.speed = FLOORSPEED * 4;
            f->floordestheight = P_FindHighestFloorSurrounding(s);
            if (f->floordestheight != sec_floorh[s])
                f->floordestheight += 8;
            break;
        case raiseFloorCrush:
        case raiseFloor:
            f->crush = type == raiseFloorCrush;
            h = P_FindLowestCeilingSurrounding(s);
            if (h > sec_ceilh[s])
                h = sec_ceilh[s];
            f->floordestheight = f->crush ? h - 8 : h;
            break;
        case raiseFloorTurbo:
            f->m.speed = FLOORSPEED * 4;
            /* fall through */
        case raiseFloorToNearest:
            f->floordestheight = P_FindNextHighestFloor(s, sec_floorh[s]);
            break;
        case raiseFloor24:
            f->floordestheight = sec_floorh[s] + 24;
            break;
        case raiseFloor512:
            f->floordestheight = sec_floorh[s] + 512;
            break;
        case raiseToTexture:
            minsize = INT16_MAX;
            count = P_SectorLines(s, &first);
            for (n = 0; n < count; ++n) {
                ln = P_SecLine(first + n);
                if (!(P_Line(ln)->flags & ML_TWOSIDED))
                    continue;
                h = bottom_height(P_LineSide(ln, 0));
                if (h < minsize)
                    minsize = h;
                h = bottom_height(P_LineSide(ln, 1));
                if (h < minsize)
                    minsize = h;
            }
            dest = (int32_t)sec_floorh[s] + minsize;
            f->floordestheight = dest > INT16_MAX ? INT16_MAX : (int16_t)dest;
            break;
        case lowerAndChange:
            f->direction = -1;
            f->floordestheight = P_FindLowestFloorSurrounding(s);
            f->texture = P_SectorFloorPic(s);
            /* the flat and special of a neighbour at the destination */
            count = P_SectorLines(s, &first);
            for (n = 0; n < count; ++n) {
                ln = P_SecLine(first + n);
                li = P_Line(ln);
                if (!(li->flags & ML_TWOSIDED))
                    continue;
                other = li->frontsector == s ? li->backsector : li->frontsector;
                if (sec_floorh[other] == f->floordestheight) {
                    f->texture = P_SectorFloorPic(other);
                    f->newspecial = sec_special[other];
                    break;
                }
            }
            break;
        }
    }
    return rtn;
}

int16_t EV_DoFloor(uint16_t line, uint8_t type)
{
    uint16_t cursor = 0, s, front;
    line_t *li = P_Line(line);
    uint16_t tag = li->tag;

    if (type == raiseFloor24AndChange) {
        /* the tagged sectors take the flat and special of the line's front */
        front = li->frontsector;
        while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX)
            if (!SEC_BUSY(s)) {
                P_SetSectorFloorPic(s, P_SectorFloorPic(front));
                P_SetSectorSpecial(s, sec_special[front]);
            }
        type = raiseFloor24;
    }
    return EV_DoFloorTag(tag, type);
}

int16_t EV_BuildStairs(uint16_t line, uint8_t type)
{
    uint16_t tag = P_Line(line)->tag, cursor = 0, s, first, count, n, ln, next, texture;
    int16_t rtn = 0, height;
    uint8_t speed, stairsize, ok;
    floormove_t *f;
    line_t *li;

    if (type == build8) {
        speed = FLOORSPEED / 4;
        stairsize = 8;
    } else {
        speed = FLOORSPEED * 4;
        stairsize = 16;
    }
    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        if (SEC_BUSY(s))
            continue;
        rtn = 1;
        height = sec_floorh[s] + stairsize;
        texture = P_SectorFloorPic(s);
        do {
            f = (floormove_t *)P_NewMover(T_MoveFloor, sizeof *f, s);
            f->direction = 1;
            f->m.speed = speed;
            f->floordestheight = height;
            /* the next step: a two-sided line with this step in front */
            ok = 0;
            count = P_SectorLines(s, &first);
            for (n = 0; n < count; ++n) {
                ln = P_SecLine(first + n);
                li = P_Line(ln);
                if (!(li->flags & ML_TWOSIDED) || li->frontsector != s)
                    continue;
                next = li->backsector;
                if (P_SectorFloorPic(next) != texture)
                    continue;
                height += stairsize;
                if (SEC_BUSY(next))
                    continue;
                s = next;
                ok = 1;
                break;
            }
        } while (ok);
    }
    return rtn;
}

#endif
