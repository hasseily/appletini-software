/* Doom for the Appletini -- moving ceilings and crushers (docs/DESIGN.md
 * section 9): vanilla p_ceilng.c.
 *
 *   T_MoveCeiling        the thinker: crushers go down and up for ever
 *                        (slowed to an eighth while a thing is crushed),
 *                        the others once
 *   EV_DoCeiling         the tagged sectors; the crushing types first
 *                        restart the tag's stopped crushers
 *   EV_CeilingCrushStop  puts the tag's moving crushers in stasis
 *
 * As with the plats, vanilla's activeceilings[30] is the thinker list
 * searched by tag.
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)   /* on the 6502: a_movers.s */

void T_MoveCeiling(thinker_t *t)
{
    ceiling_t *c = (ceiling_t *)t;
    uint8_t type = c->m.type, res;

    if (!c->direction)
        return;                     /* in stasis */
    if (c->direction > 0)
        res = T_MovePlane(&c->m, c->topheight, false, 1, 1);
    else
        res = T_MovePlane(&c->m, c->bottomheight, c->crush, 1, -1);
    if (!(leveltime & 7) && type != silentCrushAndRaise)
        S_StartSound(0, sfx_stnmov);

    if (c->direction > 0) {
        if (res != res_pastdest)
            return;
        switch (type) {
        case raiseToHighest:
            P_RemoveMover(&c->m);
            break;
        case silentCrushAndRaise:
            S_StartSound(0, sfx_pstop);
            /* fall through */
        case fastCrushAndRaise:
        case crushAndRaise:
            c->direction = -1;
            break;
        }
    } else if (res == res_pastdest) {
        switch (type) {
        case silentCrushAndRaise:
            S_StartSound(0, sfx_pstop);
            /* fall through */
        case crushAndRaise:
            c->m.speed = CEILSPEED;
            /* fall through */
        case fastCrushAndRaise:
            c->direction = 1;
            break;
        case lowerAndCrush:
        case lowerToFloor:
            P_RemoveMover(&c->m);
            break;
        }
    } else if (res == res_crushed) {
        if (type == silentCrushAndRaise || type == crushAndRaise || type == lowerAndCrush)
            c->m.speed = CEILSPEED / 8;
    }
}

/* vanilla P_ActivateInStasisCeiling (stop false) and EV_CeilingCrushStop */
static int16_t ceilings_by_tag(uint16_t tag, boolean stop)
{
    thinker_t *t;
    ceiling_t *c;
    int16_t rtn = 0;

    for (t = thinkercap.next; t != &thinkercap; t = t->next) {
        if (t->function != T_MoveCeiling)
            continue;
        c = (ceiling_t *)t;
        if (c->tag != tag)
            continue;
        if (stop && c->direction) {
            c->olddirection = c->direction;
            c->direction = 0;
            rtn = 1;
        } else if (!stop && !c->direction) {
            c->direction = c->olddirection;
        }
    }
    return rtn;
}

int16_t EV_CeilingCrushStop(uint16_t line)
{
    return ceilings_by_tag(P_Line(line)->tag, true);
}

int16_t EV_DoCeiling(uint16_t line, uint8_t type)
{
    uint16_t tag = P_Line(line)->tag, cursor = 0, s;
    int16_t rtn = 0;
    ceiling_t *c;

    if (type == fastCrushAndRaise || type == silentCrushAndRaise || type == crushAndRaise)
        ceilings_by_tag(tag, false);
    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        if (SEC_BUSY(s))
            continue;
        rtn = 1;
        c = (ceiling_t *)P_NewMover(T_MoveCeiling, sizeof *c, s);
        c->m.type = type;
        c->m.speed = CEILSPEED;
        c->direction = -1;
        c->tag = tag;               /* (vanilla: sec->tag, the same) */
        switch (type) {
        case fastCrushAndRaise:
            c->crush = true;
            c->topheight = sec_ceilh[s];
            c->bottomheight = sec_floorh[s] + 8;
            c->m.speed = CEILSPEED * 2;
            break;
        case silentCrushAndRaise:
        case crushAndRaise:
            c->crush = true;
            c->topheight = sec_ceilh[s];
            /* fall through */
        case lowerAndCrush:
        case lowerToFloor:
            c->bottomheight = sec_floorh[s];
            if (type != lowerToFloor)
                c->bottomheight += 8;
            break;
        case raiseToHighest:
            c->topheight = P_FindHighestCeilingSurrounding(s);
            c->direction = 1;
            break;
        }
    }
    return rtn;
}

#endif
