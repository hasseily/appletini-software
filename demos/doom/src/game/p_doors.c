/* Doom for the Appletini -- doors (docs/DESIGN.md section 9): vanilla
 * p_doors.c.
 *
 *   T_VerticalDoor   the door thinker: up, wait, down; a thing under a
 *                    closing door sends it back up (not blazing/close doors)
 *   EV_DoDoor        the tagged sectors' doors (switches, walk lines)
 *   EV_DoLockedDoor  the same behind a key (99, 133-137): "you need a ...
 *                    key to activate this object"
 *   EV_VerticalDoor  the manual doors (1, 26-28, 31-34, 117, 118): the
 *                    sector behind the line; locked ones need their key
 *                    ("you need a ... key to open this door"); using a
 *                    moving raise door turns it around
 *   P_SpawnDoorCloseIn30, P_SpawnDoorRaiseIn5Mins  sector specials 10, 14
 *
 * Heights in map units; the door's top is 4 below its lowest neighbouring
 * ceiling, as vanilla's. The messages go to player.message (MSG_PD_*), as
 * vanilla's player->message; the level flow queues them (g_game.c).
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)   /* on the 6502: a_movers.s */

void T_VerticalDoor(thinker_t *t)
{
    vldoor_t *door = (vldoor_t *)t;
    uint16_t s = door->m.sector;
    uint8_t type = door->m.type, res;

    switch (door->direction) {
    case 0:                         /* waiting at the top */
        if (!--door->topcountdown) {
            switch (type) {
            case vld_blazeRaise:
                door->direction = -1;
                S_StartSound(0, sfx_bdcls);
                break;
            case vld_normal:
                door->direction = -1;
                S_StartSound(0, sfx_dorcls);
                break;
            case vld_close30ThenOpen:
                door->direction = 1;
                S_StartSound(0, sfx_doropn);
                break;
            }
        }
        break;
    case 2:                         /* the initial wait of raiseIn5Mins */
        if (!--door->topcountdown && type == vld_raiseIn5Mins) {
            door->direction = 1;
            door->m.type = vld_normal;
            S_StartSound(0, sfx_doropn);
        }
        break;
    case -1:                        /* down */
        res = T_MovePlane(&door->m, sec_floorh[s], false, 1, -1);
        if (res == res_pastdest) {
            switch (type) {
            case vld_blazeRaise:
            case vld_blazeClose:
                P_RemoveMover(&door->m);
                S_StartSound(0, sfx_bdcls);
                break;
            case vld_normal:
            case vld_close:
                P_RemoveMover(&door->m);
                break;
            case vld_close30ThenOpen:
                door->direction = 0;
                door->topcountdown = 35 * 30;
                break;
            }
        } else if (res == res_crushed) {
            if (type != vld_blazeClose && type != vld_close) {
                door->direction = 1;    /* a thing in the way: back up */
                S_StartSound(0, sfx_doropn);
            }
        }
        break;
    case 1:                         /* up */
        res = T_MovePlane(&door->m, door->topheight, false, 1, 1);
        if (res == res_pastdest) {
            switch (type) {
            case vld_blazeRaise:
            case vld_normal:
                door->direction = 0;
                door->topcountdown = door->topwait;
                break;
            case vld_close30ThenOpen:
            case vld_blazeOpen:
            case vld_open:
                P_RemoveMover(&door->m);
                break;
            }
        }
        break;
    }
}

static vldoor_t *new_door(uint16_t sector, uint8_t type)
{
    vldoor_t *door = (vldoor_t *)P_NewMover(T_VerticalDoor, sizeof *door, sector);
    door->m.type = type;
    door->m.speed = VDOORSPEED;
    door->topwait = VDOORWAIT;
    return door;
}

int16_t EV_DoDoor(uint16_t line, uint8_t type)
{
    uint16_t tag = P_Line(line)->tag, cursor = 0, s;
    int16_t rtn = 0;
    vldoor_t *door;

    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        if (SEC_BUSY(s))
            continue;
        rtn = 1;
        door = new_door(s, type);
        switch (type) {
        case vld_blazeClose:
        case vld_close:
            door->topheight = P_FindLowestCeilingSurrounding(s) - 4;
            door->direction = -1;
            if (type == vld_blazeClose) {
                door->m.speed = VDOORSPEED * 4;
                S_StartSound(0, sfx_bdcls);
            } else {
                S_StartSound(0, sfx_dorcls);
            }
            break;
        case vld_close30ThenOpen:
            door->topheight = sec_ceilh[s];
            door->direction = -1;
            S_StartSound(0, sfx_dorcls);
            break;
        case vld_blazeRaise:
        case vld_blazeOpen:
            door->direction = 1;
            door->topheight = P_FindLowestCeilingSurrounding(s) - 4;
            door->m.speed = VDOORSPEED * 4;
            if (door->topheight != sec_ceilh[s])
                S_StartSound(0, sfx_bdopn);
            break;
        case vld_normal:
        case vld_open:
            door->direction = 1;
            door->topheight = P_FindLowestCeilingSurrounding(s) - 4;
            if (door->topheight != sec_ceilh[s])
                S_StartSound(0, sfx_doropn);
            break;
        }
    }
    return rtn;
}

/* the key a special wants (it_bluecard, ...; 0xFF none) and the message
 * the player gets without it */
static boolean has_key(mobj_t *thing, uint8_t card, uint8_t msg)
{
    player_t *p = MO_PLAYER(thing);

    if (!p)
        return false;
    if (p->cards[card] || p->cards[card + 3])   /* the card or the skull */
        return true;
    p->message = msg;
    S_StartSound(0, sfx_oof);
    return false;
}

int16_t EV_DoLockedDoor(uint16_t line, uint8_t type, mobj_t *thing)
{
    switch (P_Line(line)->special) {
    case 99:
    case 133:
        if (!has_key(thing, it_bluecard, MSG_PD_BLUEO))
            return 0;
        break;
    case 134:
    case 135:
        if (!has_key(thing, it_redcard, MSG_PD_REDO))
            return 0;
        break;
    case 136:
    case 137:
        if (!has_key(thing, it_yellowcard, MSG_PD_YELLOWO))
            return 0;
        break;
    }
    return EV_DoDoor(line, type);
}

void EV_VerticalDoor(uint16_t line, mobj_t *thing)
{
    line_t *li = P_Line(line);
    uint8_t special = li->special;
    uint16_t s = li->backsector;    /* vanilla: sides[line->sidenum[side ^ 1]].sector, side 0 */
    vldoor_t *door;

    switch (special) {
    case 26:
    case 32:
        if (!has_key(thing, it_bluecard, MSG_PD_BLUEK))
            return;
        break;
    case 27:
    case 34:
        if (!has_key(thing, it_yellowcard, MSG_PD_YELLOWK))
            return;
        break;
    case 28:
    case 33:
        if (!has_key(thing, it_redcard, MSG_PD_REDK))
            return;
        break;
    }
    if (s == NO_INDEX)
        return;                     /* a one-sided door line (vanilla would crash) */

    /* the sector already moves: a raise door turns around */
    if (SEC_BUSY(s)) {
        door = (vldoor_t *)P_FindMover(s, T_VerticalDoor);
        if (door && (special == 1 || special == 26 || special == 27 || special == 28
                     || special == 117)) {
            if (door->direction == -1)
                door->direction = 1;    /* go back up */
            else if (IS_PLAYER(thing))
                door->direction = -1;   /* start down (monsters never close doors) */
            return;
        }
        /* vanilla takes any mover for a door here; this one only turns
         * doors around, and starts nothing on a sector already moving */
        if (!door)
            return;
    }

    S_StartSound(0, special == 117 || special == 118 ? sfx_bdopn : sfx_doropn);
    door = new_door(s, vld_normal);
    door->direction = 1;
    switch (special) {
    case 31:
    case 32:
    case 33:
    case 34:
        door->m.type = vld_open;
        P_ClearLineSpecial(line);
        break;
    case 117:
        door->m.type = vld_blazeRaise;
        door->m.speed = VDOORSPEED * 4;
        break;
    case 118:
        door->m.type = vld_blazeOpen;
        P_ClearLineSpecial(line);
        door->m.speed = VDOORSPEED * 4;
        break;
    }
    door->topheight = P_FindLowestCeilingSurrounding(s) - 4;
}

/* sector special 10: closes 30 seconds into the level */
void P_SpawnDoorCloseIn30(uint16_t s)
{
    vldoor_t *door = new_door(s, vld_normal);
    P_SetSectorSpecial(s, 0);
    door->direction = 0;
    door->topcountdown = 30 * 35;
}

/* sector special 14: opens 5 minutes into the level */
void P_SpawnDoorRaiseIn5Mins(uint16_t s)
{
    vldoor_t *door = new_door(s, vld_raiseIn5Mins);
    P_SetSectorSpecial(s, 0);
    door->direction = 2;
    door->topheight = P_FindLowestCeilingSurrounding(s) - 4;
    door->topcountdown = 5 * 60 * 35;
}

#endif
