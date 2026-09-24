/* Doom for the Appletini -- platforms, lifts (docs/DESIGN.md section 9):
 * vanilla p_plats.c.
 *
 *   T_PlatRaise  the plat thinker: down, wait 3 s, up (a lift), or up and
 *                down for ever (perpetualRaise), or up once with a new
 *                flat (raiseAndChange, raiseToNearestAndChange)
 *   EV_DoPlat    the tagged sectors; perpetualRaise first restarts the
 *                stopped ones
 *   EV_StopPlat  puts the tag's moving plats in stasis
 *
 * vanilla keeps its plats in activeplats[30] too, to find them by tag;
 * here the thinker list is searched (a plat in stasis stays a thinker and
 * does nothing, as vanilla's does without its function), and a finished
 * lift is simply removed.
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)   /* on the 6502: a_movers.s */

void T_PlatRaise(thinker_t *t)
{
    plat_t *plat = (plat_t *)t;
    uint8_t res;

    switch (plat->status) {
    case plat_up:
        res = T_MovePlane(&plat->m, plat->high, plat->crush, 0, 1);
        if ((plat->m.type == raiseAndChange || plat->m.type == raiseToNearestAndChange)
            && !(leveltime & 7))
            S_StartSound(0, sfx_stnmov);
        if (res == res_crushed && !plat->crush) {
            plat->count = plat->wait;
            plat->status = plat_down;
            S_StartSound(0, sfx_pstart);
        } else if (res == res_pastdest) {
            plat->count = plat->wait;
            plat->status = plat_waiting;
            S_StartSound(0, sfx_pstop);
            if (plat->m.type != perpetualRaise)
                P_RemoveMover(&plat->m);
        }
        break;
    case plat_down:
        res = T_MovePlane(&plat->m, plat->low, false, 0, -1);
        if (res == res_pastdest) {
            plat->count = plat->wait;
            plat->status = plat_waiting;
            S_StartSound(0, sfx_pstop);
        }
        break;
    case plat_waiting:
        if (!--plat->count) {
            plat->status = sec_floorh[plat->m.sector] == plat->low ? plat_up : plat_down;
            S_StartSound(0, sfx_pstart);
        }
        break;
    }
}

/* vanilla P_ActivateInStasis / EV_StopPlat over the thinker list */
static void plats_by_tag(uint16_t tag, boolean stop)
{
    thinker_t *t;
    plat_t *plat;

    for (t = thinkercap.next; t != &thinkercap; t = t->next) {
        if (t->function != T_PlatRaise)
            continue;
        plat = (plat_t *)t;
        if (plat->tag != tag)
            continue;
        if (stop && plat->status != plat_in_stasis) {
            plat->oldstatus = plat->status;
            plat->status = plat_in_stasis;
        } else if (!stop && plat->status == plat_in_stasis) {
            plat->status = plat->oldstatus;
        }
    }
}

void EV_StopPlat(uint16_t line)
{
    plats_by_tag(P_Line(line)->tag, true);
}

int16_t EV_DoPlat(uint16_t line, uint8_t type, int16_t amount)
{
    line_t *li = P_Line(line);
    uint16_t tag = li->tag, front = li->frontsector, cursor = 0, s;
    int16_t rtn = 0, h;
    plat_t *plat;

    if (type == perpetualRaise)
        plats_by_tag(tag, false);
    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        if (SEC_BUSY(s))
            continue;
        rtn = 1;
        plat = (plat_t *)P_NewMover(T_PlatRaise, sizeof *plat, s);
        plat->m.type = type;
        plat->tag = tag;
        h = sec_floorh[s];
        switch (type) {
        case raiseToNearestAndChange:
        case raiseAndChange:
            plat->m.speed = PLATSPEED / 2;
            P_SetSectorFloorPic(s, P_SectorFloorPic(front));
            if (type == raiseToNearestAndChange) {
                plat->high = P_FindNextHighestFloor(s, h);
                P_SetSectorSpecial(s, 0);   /* no more damage */
            } else {
                plat->high = h + amount;
            }
            plat->status = plat_up;
            S_StartSound(0, sfx_stnmov);
            break;
        case downWaitUpStay:
        case blazeDWUS:
            plat->m.speed = type == blazeDWUS ? PLATSPEED * 8 : PLATSPEED * 4;
            plat->low = P_FindLowestFloorSurrounding(s);
            if (plat->low > h)
                plat->low = h;
            plat->high = h;
            plat->wait = 35 * PLATWAIT;
            plat->status = plat_down;
            S_StartSound(0, sfx_pstart);
            break;
        case perpetualRaise:
            plat->m.speed = PLATSPEED;
            plat->low = P_FindLowestFloorSurrounding(s);
            if (plat->low > h)
                plat->low = h;
            plat->high = P_FindHighestFloorSurrounding(s);
            if (plat->high < h)
                plat->high = h;
            plat->wait = 35 * PLATWAIT;
            plat->status = P_Random() & 1;
            S_StartSound(0, sfx_pstart);
            break;
        }
    }
    return rtn;
}

#endif
