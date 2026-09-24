/* Doom for the Appletini -- teleporters (docs/DESIGN.md section 9):
 * vanilla p_telept.c.
 *
 * EV_Teleport: a thing crossing the line's front side goes to the
 * teleport destination (MT_TELEPORTMAN) in a sector with the line's tag,
 * if P_TeleportMove lets it (telefragging what is there), with fog at
 * both ends. vanilla takes the first destination of its thinker list
 * that is in a tagged sector; the core's P_FindTeleportDest looks in the
 * statics, where the map's destinations are (per sector, in tag order).
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)   /* on the 6502: a_movers.s */

int16_t EV_Teleport(uint16_t line, uint8_t side, mobj_t *thing)
{
    uint16_t tag, cursor = 0, s, fa;
    mobj_t *m, *fog;
    fixed_t x, y, oldx, oldy, oldz;
    angle_t angle;
    player_t *p;

    if (FLAG(thing->flags, MF_MISSILE) || side == 1)
        return 0;                   /* no missiles; the back side lets you out */
    tag = P_Line(line)->tag;
    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        m = P_FindTeleportDest(s);
        if (!m)
            continue;
        /* (a static destination is a view that the move may reuse) */
        x = m->x;
        y = m->y;
        angle = m->angle;
        oldx = thing->x;
        oldy = thing->y;
        oldz = thing->z;
        if (!P_TeleportMove(thing, x, y))
            return 0;
        thing->z = FIX(thing->floorz);
        p = MO_PLAYER(thing);
        if (p)
            p->viewz = thing->z + p->viewheight;
        fog = P_SpawnMobj(oldx, oldy, oldz, MT_TFOG);
        S_StartSound(fog, sfx_telept);
        fa = angle >> ANGLETOFINESHIFT;
        fog = P_SpawnMobj(x + 20 * fine_cosine(fa), y + 20 * fine_sine(fa), thing->z, MT_TFOG);
        S_StartSound(fog, sfx_telept);
        if (p)
            thing->reactiontime = 18;   /* don't move for a bit */
        thing->angle = angle;
        thing->momx = thing->momy = thing->momz = 0;
        return 1;
    }
    return 0;
}

#endif
