/* Doom for the Appletini -- line and sector specials (docs/DESIGN.md
 * section 9): vanilla p_spec.c.
 *
 *   P_CrossSpecialLine, P_UseSpecialLine, P_ShootSpecialLine
 *                one table (spec_tab) says, for every vanilla line
 *                special, how it is triggered (walk, switch, gun, manual
 *                door; once or repeatable; by monsters too), which EV_
 *                action it runs and with what argument; the three entry
 *                points check the trigger and run the action as vanilla's
 *                three switch statements do
 *   P_PlayerInSpecialSector  damaging floors (5, 7, 16, 4, 11), secrets (9)
 *   P_SpawnSpecials  level set-up: the tagged-sector list, the busy bits,
 *                the lights, the scrolling walls (48), the doors of sector
 *                specials 10 and 14, the secrets count
 *   P_UpdateSpecials  every tic: lights, switch buttons, scrolling walls
 *                (texture and flat animations are the renderer's: it gets
 *                the tic in the render packet)
 *   T_MovePlane  the movers' one step (vanilla's, with the eighths of
 *                p_spec.h)
 *   the neighbour searches (P_Find*Surrounding...), EV_DoDonut
 *   P_ResetLevelData  what a level restart must undo (below)
 *
 * Sector tags are far; vanilla's P_FindSectorFromLineTag scans every
 * sector, so the set-up lists the tagged sectors (few: 57 in E1M7, of
 * 699) with their tags in level memory, in sector order.
 *
 * Changing the level in place. The renderer reads sectors and sidedefs
 * from the converter's far records, and the game has no WAD to reload
 * them from, so what the specials change stays changed. P_ResetLevelData,
 * called before every level load (a new level, or the same one restarted
 * after the player's death), puts a level back:
 *   - sectors (heights, light, floor picture, special) change all the
 *     time: each map's SECTORS array is copied whole to a snapshot the
 *     first time the map is loaded, and copied back at every later load
 *     (the snapshots of E1: 45,888 bytes);
 *   - lines and sidedefs change a few times a level (a once-only line's
 *     special cleared, a once-only switch's texture): the bytes are
 *     journalled before the change (far address, length, old bytes) and
 *     the journal is played back, newest first, at the next load;
 *   - pressed buttons are put back up and scrolled walls back to their
 *     offsets from the part's near lists, which the level end leaves
 *     intact.
 * Both live in the specials' bank, the one below the game's far bank
 * (kbanks - 2): the journal at $0200 (JOURNAL_MAX entries of 6 bytes),
 * the snapshots from $0A00 on, continuing in the bank below if a map's
 * array does not fit.
 *
 * On the 6502 this file and the other p_*.c of the part are a_spec.s and
 * a_movers.s (the C is their reference, compiled on the host only). The
 * level set-up and the undoing (P_SpawnSpecials, P_ResetLevelData: the
 * last part of this file) are in the set-up overlay there (GOVL,
 * p_setup.c), whose bytes become actor slots once the level is set up.
 */
#include "p_spec.h"

#ifdef GAME_REAL

#include <string.h>

#if !defined(__CC65__)             /* on the 6502: a_spec.s */

uint8_t *sec_busy;
uint16_t *tag_list, tag_count, *scroll_list, jcount;
uint8_t scroll_count;

/* --- the specials table --------------------------------------------------------------------- */
/* trigger byte: kind in bits 0-2, then flags */
#define TR_W        1               /* walk over */
#define TR_S        2               /* switch (use) */
#define TR_G        3               /* gun (shoot) */
#define TR_D        4               /* manual door (use) */
#define TR_KIND     7
#define TR_REPEAT   0x08            /* WR/SR/GR/DR: stays */
#define TR_MONSTER  0x10            /* monsters trigger it too */
#define TR_ALWAYS   0x20            /* the switch texture changes whatever the action did */

enum { SA_NONE, SA_DOOR, SA_LOCKED, SA_VDOOR, SA_FLOOR, SA_PLAT, SA_STOPPLAT, SA_CEIL,
       SA_CRUSHSTOP, SA_STAIRS, SA_DONUT, SA_LIGHTON, SA_STROBE, SA_LIGHTSOFF, SA_TELEPORT,
       SA_EXIT, SA_CEILFLOOR };
/* SA_PLAT's argument: the type, and the raise of raiseAndChange */
#define PLAT24      0x10
#define PLAT32      0x20

#define W1(a, g)    { TR_W, a, g }
#define WR(a, g)    { TR_W | TR_REPEAT, a, g }
#define S1(a, g)    { TR_S, a, g }
#define SR(a, g)    { TR_S | TR_REPEAT, a, g }
#define DR(a, g)    { TR_D | TR_REPEAT, a, g }
#define D1(a, g)    { TR_D, a, g }
#define M           TR_MONSTER
#define NUMSPECIALS 142

/* vanilla's P_CrossSpecialLine, P_UseSpecialLine and P_ShootSpecialLine as
 * data: special -> trigger, action, argument */
static const uint8_t spec_tab[NUMSPECIALS][3] = {
    /*   0 */ { 0, 0, 0 },
    /*   1 */ { TR_D | TR_REPEAT | M, SA_VDOOR, 0 },
    /*   2 */ W1(SA_DOOR, vld_open),
    /*   3 */ W1(SA_DOOR, vld_close),
    /*   4 */ { TR_W | M, SA_DOOR, vld_normal },
    /*   5 */ W1(SA_FLOOR, raiseFloor),
    /*   6 */ W1(SA_CEIL, fastCrushAndRaise),
    /*   7 */ S1(SA_STAIRS, build8),
    /*   8 */ W1(SA_STAIRS, build8),
    /*   9 */ S1(SA_DONUT, 0),
    /*  10 */ { TR_W | M, SA_PLAT, downWaitUpStay },
    /*  11 */ { TR_S | TR_ALWAYS, SA_EXIT, 0 },
    /*  12 */ W1(SA_LIGHTON, 0),
    /*  13 */ W1(SA_LIGHTON, 255),
    /*  14 */ S1(SA_PLAT, raiseAndChange | PLAT32),
    /*  15 */ S1(SA_PLAT, raiseAndChange | PLAT24),
    /*  16 */ W1(SA_DOOR, vld_close30ThenOpen),
    /*  17 */ W1(SA_STROBE, 0),
    /*  18 */ S1(SA_FLOOR, raiseFloorToNearest),
    /*  19 */ W1(SA_FLOOR, lowerFloor),
    /*  20 */ S1(SA_PLAT, raiseToNearestAndChange),
    /*  21 */ S1(SA_PLAT, downWaitUpStay),
    /*  22 */ W1(SA_PLAT, raiseToNearestAndChange),
    /*  23 */ S1(SA_FLOOR, lowerFloorToLowest),
    /*  24 */ { TR_G | TR_ALWAYS, SA_FLOOR, raiseFloor },
    /*  25 */ W1(SA_CEIL, crushAndRaise),
    /*  26 */ { TR_D | TR_REPEAT, SA_VDOOR, 0 },
    /*  27 */ { TR_D | TR_REPEAT, SA_VDOOR, 0 },
    /*  28 */ { TR_D | TR_REPEAT, SA_VDOOR, 0 },
    /*  29 */ S1(SA_DOOR, vld_normal),
    /*  30 */ W1(SA_FLOOR, raiseToTexture),
    /*  31 */ D1(SA_VDOOR, 0),
    /*  32 */ { TR_D | M, SA_VDOOR, 0 },
    /*  33 */ { TR_D | M, SA_VDOOR, 0 },
    /*  34 */ { TR_D | M, SA_VDOOR, 0 },
    /*  35 */ W1(SA_LIGHTON, 35),
    /*  36 */ W1(SA_FLOOR, turboLower),
    /*  37 */ W1(SA_FLOOR, lowerAndChange),
    /*  38 */ W1(SA_FLOOR, lowerFloorToLowest),
    /*  39 */ { TR_W | M, SA_TELEPORT, 0 },
    /*  40 */ W1(SA_CEILFLOOR, 0),
    /*  41 */ S1(SA_CEIL, lowerToFloor),
    /*  42 */ SR(SA_DOOR, vld_close),
    /*  43 */ SR(SA_CEIL, lowerToFloor),
    /*  44 */ W1(SA_CEIL, lowerAndCrush),
    /*  45 */ SR(SA_FLOOR, lowerFloor),
    /*  46 */ { TR_G | TR_REPEAT | TR_ALWAYS | M, SA_DOOR, vld_open },
    /*  47 */ { TR_G | TR_ALWAYS, SA_PLAT, raiseToNearestAndChange },
    /*  48 */ { 0, 0, 0 },          /* scrolling wall: P_UpdateSpecials */
    /*  49 */ S1(SA_CEIL, crushAndRaise),
    /*  50 */ S1(SA_DOOR, vld_close),
    /*  51 */ { TR_S | TR_ALWAYS, SA_EXIT, 1 },
    /*  52 */ WR(SA_EXIT, 0),       /* (vanilla leaves it: the level ends) */
    /*  53 */ W1(SA_PLAT, perpetualRaise),
    /*  54 */ W1(SA_STOPPLAT, 0),
    /*  55 */ S1(SA_FLOOR, raiseFloorCrush),
    /*  56 */ W1(SA_FLOOR, raiseFloorCrush),
    /*  57 */ W1(SA_CRUSHSTOP, 0),
    /*  58 */ W1(SA_FLOOR, raiseFloor24),
    /*  59 */ W1(SA_FLOOR, raiseFloor24AndChange),
    /*  60 */ SR(SA_FLOOR, lowerFloorToLowest),
    /*  61 */ SR(SA_DOOR, vld_open),
    /*  62 */ SR(SA_PLAT, downWaitUpStay),
    /*  63 */ SR(SA_DOOR, vld_normal),
    /*  64 */ SR(SA_FLOOR, raiseFloor),
    /*  65 */ SR(SA_FLOOR, raiseFloorCrush),
    /*  66 */ SR(SA_PLAT, raiseAndChange | PLAT24),
    /*  67 */ SR(SA_PLAT, raiseAndChange | PLAT32),
    /*  68 */ SR(SA_PLAT, raiseToNearestAndChange),
    /*  69 */ SR(SA_FLOOR, raiseFloorToNearest),
    /*  70 */ SR(SA_FLOOR, turboLower),
    /*  71 */ S1(SA_FLOOR, turboLower),
    /*  72 */ WR(SA_CEIL, lowerAndCrush),
    /*  73 */ WR(SA_CEIL, crushAndRaise),
    /*  74 */ WR(SA_CRUSHSTOP, 0),
    /*  75 */ WR(SA_DOOR, vld_close),
    /*  76 */ WR(SA_DOOR, vld_close30ThenOpen),
    /*  77 */ WR(SA_CEIL, fastCrushAndRaise),
    /*  78 */ { 0, 0, 0 },
    /*  79 */ WR(SA_LIGHTON, 35),
    /*  80 */ WR(SA_LIGHTON, 0),
    /*  81 */ WR(SA_LIGHTON, 255),
    /*  82 */ WR(SA_FLOOR, lowerFloorToLowest),
    /*  83 */ WR(SA_FLOOR, lowerFloor),
    /*  84 */ WR(SA_FLOOR, lowerAndChange),
    /*  85 */ { 0, 0, 0 },
    /*  86 */ WR(SA_DOOR, vld_open),
    /*  87 */ WR(SA_PLAT, perpetualRaise),
    /*  88 */ { TR_W | TR_REPEAT | M, SA_PLAT, downWaitUpStay },
    /*  89 */ WR(SA_STOPPLAT, 0),
    /*  90 */ WR(SA_DOOR, vld_normal),
    /*  91 */ WR(SA_FLOOR, raiseFloor),
    /*  92 */ WR(SA_FLOOR, raiseFloor24),
    /*  93 */ WR(SA_FLOOR, raiseFloor24AndChange),
    /*  94 */ WR(SA_FLOOR, raiseFloorCrush),
    /*  95 */ WR(SA_PLAT, raiseToNearestAndChange),
    /*  96 */ WR(SA_FLOOR, raiseToTexture),
    /*  97 */ { TR_W | TR_REPEAT | M, SA_TELEPORT, 0 },
    /*  98 */ WR(SA_FLOOR, turboLower),
    /*  99 */ SR(SA_LOCKED, vld_blazeOpen),
    /* 100 */ W1(SA_STAIRS, turbo16),
    /* 101 */ S1(SA_FLOOR, raiseFloor),
    /* 102 */ S1(SA_FLOOR, lowerFloor),
    /* 103 */ S1(SA_DOOR, vld_open),
    /* 104 */ W1(SA_LIGHTSOFF, 0),
    /* 105 */ WR(SA_DOOR, vld_blazeRaise),
    /* 106 */ WR(SA_DOOR, vld_blazeOpen),
    /* 107 */ WR(SA_DOOR, vld_blazeClose),
    /* 108 */ W1(SA_DOOR, vld_blazeRaise),
    /* 109 */ W1(SA_DOOR, vld_blazeOpen),
    /* 110 */ W1(SA_DOOR, vld_blazeClose),
    /* 111 */ S1(SA_DOOR, vld_blazeRaise),
    /* 112 */ S1(SA_DOOR, vld_blazeOpen),
    /* 113 */ S1(SA_DOOR, vld_blazeClose),
    /* 114 */ SR(SA_DOOR, vld_blazeRaise),
    /* 115 */ SR(SA_DOOR, vld_blazeOpen),
    /* 116 */ SR(SA_DOOR, vld_blazeClose),
    /* 117 */ DR(SA_VDOOR, 0),
    /* 118 */ D1(SA_VDOOR, 0),
    /* 119 */ W1(SA_FLOOR, raiseFloorToNearest),
    /* 120 */ WR(SA_PLAT, blazeDWUS),
    /* 121 */ W1(SA_PLAT, blazeDWUS),
    /* 122 */ S1(SA_PLAT, blazeDWUS),
    /* 123 */ SR(SA_PLAT, blazeDWUS),
    /* 124 */ WR(SA_EXIT, 1),
    /* 125 */ { TR_W | M, SA_TELEPORT, 1 },
    /* 126 */ { TR_W | TR_REPEAT | M, SA_TELEPORT, 1 },
    /* 127 */ S1(SA_STAIRS, turbo16),
    /* 128 */ WR(SA_FLOOR, raiseFloorToNearest),
    /* 129 */ WR(SA_FLOOR, raiseFloorTurbo),
    /* 130 */ W1(SA_FLOOR, raiseFloorTurbo),
    /* 131 */ S1(SA_FLOOR, raiseFloorTurbo),
    /* 132 */ SR(SA_FLOOR, raiseFloorTurbo),
    /* 133 */ S1(SA_LOCKED, vld_blazeOpen),
    /* 134 */ SR(SA_LOCKED, vld_blazeOpen),
    /* 135 */ S1(SA_LOCKED, vld_blazeOpen),
    /* 136 */ SR(SA_LOCKED, vld_blazeOpen),
    /* 137 */ S1(SA_LOCKED, vld_blazeOpen),
    /* 138 */ { TR_S | TR_REPEAT | TR_ALWAYS, SA_LIGHTON, 255 },
    /* 139 */ { TR_S | TR_REPEAT | TR_ALWAYS, SA_LIGHTON, 35 },
    /* 140 */ S1(SA_FLOOR, raiseFloor512),
    /* 141 */ W1(SA_CEIL, silentCrushAndRaise),
};

/* the action of a table entry; the count of sectors it started (the
 * switch texture changes only if not 0, as vanilla's `if (EV_...)`) */
static int16_t run_action(uint16_t line, const uint8_t *e, mobj_t *thing, uint8_t side)
{
    uint8_t arg = e[2];

    switch (e[1]) {
    case SA_DOOR:       return EV_DoDoor(line, arg);
    case SA_LOCKED:     return EV_DoLockedDoor(line, arg, thing);
    case SA_VDOOR:      EV_VerticalDoor(line, thing); return 1;
    case SA_FLOOR:      return EV_DoFloor(line, arg);
    case SA_PLAT:
        return EV_DoPlat(line, arg & 15, arg & PLAT24 ? 24 : arg & PLAT32 ? 32 : 0);
    case SA_STOPPLAT:   EV_StopPlat(line); return 1;
    case SA_CEIL:       return EV_DoCeiling(line, arg);
    case SA_CRUSHSTOP:  return EV_CeilingCrushStop(line);
    case SA_STAIRS:     return EV_BuildStairs(line, arg);
    case SA_DONUT:      return EV_DoDonut(line);
    case SA_LIGHTON:    EV_LightTurnOn(line, arg); return 1;
    case SA_STROBE:     EV_StartLightStrobing(line); return 1;
    case SA_LIGHTSOFF:  EV_TurnTagLightsOff(line); return 1;
    case SA_TELEPORT:   return EV_Teleport(line, side, thing);
    case SA_EXIT:
        if (arg)
            G_SecretExitLevel();
        else
            G_ExitLevel();
        return 1;
    case SA_CEILFLOOR:
        EV_DoCeiling(line, raiseToHighest);
        EV_DoFloor(line, lowerFloorToLowest);
        return 1;
    }
    return 0;
}

static const uint8_t *entry(uint16_t line)
{
    uint8_t special = P_Line(line)->special;
    return special < NUMSPECIALS ? spec_tab[special] : spec_tab[0];
}

/* vanilla P_CrossSpecialLine: a walk-over line crossed from `side` */
void P_CrossSpecialLine(uint16_t linenum, uint8_t side, mobj_t *thing)
{
    const uint8_t *e = entry(linenum);
    uint8_t trig = e[0];

    if ((trig & TR_KIND) != TR_W)
        return;
    if (!IS_PLAYER(thing)) {
        /* vanilla's list of projectiles that trigger nothing: rocket,
         * plasma, BFG, imp, cacodemon and baron shots, E1's projectiles
         * all (and nothing else of E1 has MF_MISSILE) */
        if (FLAG(thing->flags, MF_MISSILE) || !(trig & TR_MONSTER))
            return;
    } else if (e[1] == SA_TELEPORT && e[2]) {
        return;                     /* 125, 126: monsters only */
    }
    run_action(linenum, e, thing, side);
    if (!(trig & TR_REPEAT))
        P_ClearLineSpecial(linenum);
}

/* vanilla P_ShootSpecialLine: a hitscan hit the line */
void P_ShootSpecialLine(mobj_t *thing, uint16_t linenum)
{
    const uint8_t *e = entry(linenum);
    uint8_t trig = e[0];

    if ((trig & TR_KIND) != TR_G)
        return;
    if (!IS_PLAYER(thing) && !(trig & TR_MONSTER))
        return;
    run_action(linenum, e, thing, 0);
    P_ChangeSwitchTexture(linenum, (trig & TR_REPEAT) != 0);
}

#ifndef __CC65__
/* (the host build records the calls for the monsters part's tests: a
 * monster blocked by a door line asks to use it) */
uint16_t use_calls, use_last_line;
mobj_t *use_last_thing;
#endif

/* vanilla P_UseSpecialLine: the player (or a monster at a door) uses the
 * line from `side`; false if it cannot be used */
boolean P_UseSpecialLine(mobj_t *thing, uint16_t linenum, uint8_t side)
{
    const uint8_t *e;
    uint8_t trig, special;

#ifndef __CC65__
    ++use_calls;
    use_last_line = linenum;
    use_last_thing = thing;
#endif
    if (side)
        return false;               /* only the front side */
    special = P_Line(linenum)->special;
    if (!IS_PLAYER(thing)) {
        /* monsters open the manual doors that are not secret */
        if (P_Line(linenum)->flags & ML_SECRET)
            return false;
        if (special != 1 && special != 32 && special != 33 && special != 34)
            return false;
    }
    e = entry(linenum);
    trig = e[0];
    if ((trig & TR_KIND) == TR_D) {
        EV_VerticalDoor(linenum, thing);
    } else if ((trig & TR_KIND) == TR_S) {
        if (run_action(linenum, e, thing, 0) || (trig & TR_ALWAYS))
            P_ChangeSwitchTexture(linenum, (trig & TR_REPEAT) != 0);
    }
    return true;
}

/* --- sectors: tags, busy bits, neighbours ---------------------------------------------------- */

void P_SetBusy(uint16_t s)   { sec_busy[s >> 3] |= (uint8_t)(1 << (s & 7)); }
void P_ClearBusy(uint16_t s) { sec_busy[s >> 3] &= (uint8_t)~(1 << (s & 7)); }

/* the next sector with the tag after *cursor's place; NO_INDEX when done
 * (vanilla P_FindSectorFromLineTag) */
uint16_t P_FindSectorFromTag(uint16_t tag, uint16_t *cursor)
{
    uint16_t i;
    for (i = *cursor; i < tag_count; ++i)
        if (tag_list[2 * i + 1] == tag) {
            *cursor = i + 1;
            return tag_list[2 * i];
        }
    *cursor = tag_count;
    return NO_INDEX;
}

/* vanilla getNextSector: the sector on the line's other side */
uint16_t P_NextSector(uint16_t line, uint16_t sector)
{
    line_t *li = P_Line(line);
    if (!(li->flags & ML_TWOSIDED))
        return NO_INDEX;
    return li->frontsector == sector ? li->backsector : li->frontsector;
}

uint16_t P_LineFrontSector(uint16_t line)
{
    return P_Line(line)->frontsector;
}

/* the neighbours' heights: one walk over the sector's lines, kept by kind */
enum { NB_LOWFLOOR, NB_HIGHFLOOR, NB_NEXTFLOOR, NB_LOWCEIL, NB_HIGHCEIL };

static int16_t neighbours(uint16_t sector, uint8_t kind, int16_t start, int16_t height)
{
    uint16_t first, count, n, other;
    int16_t v, h = start;

    count = P_SectorLines(sector, &first);
    for (n = 0; n < count; ++n) {
        other = P_NextSector(P_SecLine(first + n), sector);
        if (other == NO_INDEX)
            continue;
        v = kind >= NB_LOWCEIL ? sec_ceilh[other] : sec_floorh[other];
        switch (kind) {
        case NB_LOWFLOOR:
        case NB_LOWCEIL:
            if (v < h)
                h = v;
            break;
        case NB_HIGHFLOOR:
        case NB_HIGHCEIL:
            if (v > h)
                h = v;
            break;
        case NB_NEXTFLOOR:
            /* vanilla: the lowest of the floors above `height` (it
             * collects them in a 20-entry array; the answer is the same) */
            if (v > height && (h == height || v < h))
                h = v;
            break;
        }
    }
    return h;
}

int16_t P_FindLowestFloorSurrounding(uint16_t s)
{
    return neighbours(s, NB_LOWFLOOR, sec_floorh[s], 0);
}

int16_t P_FindHighestFloorSurrounding(uint16_t s)
{
    return neighbours(s, NB_HIGHFLOOR, -500, 0);
}

/* vanilla returns the current height when no neighbour is higher */
int16_t P_FindNextHighestFloor(uint16_t s, int16_t height)
{
    return neighbours(s, NB_NEXTFLOOR, height, height);
}

int16_t P_FindLowestCeilingSurrounding(uint16_t s)
{
    return neighbours(s, NB_LOWCEIL, INT16_MAX, 0);
}

int16_t P_FindHighestCeilingSurrounding(uint16_t s)
{
    return neighbours(s, NB_HIGHCEIL, 0, 0);
}

uint8_t P_FindMinSurroundingLight(uint16_t sector, uint8_t max)
{
    uint16_t first, count, n, other;
    uint8_t v, min = max;

    count = P_SectorLines(sector, &first);
    for (n = 0; n < count; ++n) {
        other = P_NextSector(P_SecLine(first + n), sector);
        if (other == NO_INDEX)
            continue;
        v = P_SectorLight(other);
        if (v < min)
            min = v;
    }
    return min;
}

void P_SetSectorFloorPic(uint16_t sector, uint16_t pic)
{
    far_write(&pic, P_LevAddr(MAPARR_SECTORS, sector) + SECTOR_FLOORPIC, 2);
}

/* --- movers ------------------------------------------------------------------------------------ */
mover_t *P_NewMover(think_t function, uint8_t size, uint16_t sector)
{
    mover_t *m = (mover_t *)P_AllocThinker(size);
    P_AddThinker(&m->thinker);
    m->thinker.function = function;
    m->sector = sector;
    P_SetBusy(sector);
    return m;
}

void P_RemoveMover(mover_t *m)
{
    P_ClearBusy(m->sector);
    P_RemoveThinker(&m->thinker);
}

mover_t *P_FindMover(uint16_t sector, think_t function)
{
    thinker_t *t;
    for (t = thinkercap.next; t != &thinkercap; t = t->next)
        if (t->function == function && ((mover_t *)t)->sector == sector)
            return (mover_t *)t;
    return 0;
}

/* vanilla T_MovePlane: one tic of a floor (ceiling 0) or ceiling (1)
 * toward dest. The mover's speed is in eighths of a unit; the plane moves
 * by the whole units owed. On tics that owe none it does not move, and
 * only a crusher asks P_ChangeSector (its things take damage every fourth
 * tic, as in vanilla). */
uint8_t T_MovePlane(mover_t *m, int16_t dest, boolean crush, uint8_t ceiling, int8_t direction)
{
    uint16_t s = m->sector;
    int16_t last = ceiling ? sec_ceilh[s] : sec_floorh[s];
    int16_t now;
    uint8_t step, result;

    step = m->acc + m->speed;
    m->acc = step & 7;
    step >>= 3;

    if (last == dest || (direction < 0 ? last - step < dest : last + step > dest)) {
        now = dest;                 /* there, unless things do not fit */
        result = res_pastdest;
    } else if (!step) {
        if (crush)
            P_ChangeSector(s, true);
        return res_ok;
    } else {
        now = direction < 0 ? last - step : last + step;
        result = res_ok;
    }
    if (ceiling)
        P_SetSectorCeiling(s, now);
    else
        P_SetSectorFloor(s, now);
    if (!P_ChangeSector(s, crush))
        return result;
    if (result == res_ok) {
        /* things do not fit on the way: a rising ceiling goes on, a
         * crusher crushes on (floor up, ceiling down), the rest go back */
        if (ceiling && direction > 0)
            return res_ok;
        if (crush && (ceiling ? direction < 0 : direction > 0))
            return res_crushed;
        result = res_crushed;
    }
    if (ceiling)
        P_SetSectorCeiling(s, last);
    else
        P_SetSectorFloor(s, last);
    P_ChangeSector(s, crush);
    return result;
}

/* --- vanilla EV_DoDonut ------------------------------------------------------------------------ */
int16_t EV_DoDonut(uint16_t line)
{
    uint16_t tag = P_Line(line)->tag, cursor = 0, s1, s2, s3, first, count, n, ln;
    int16_t rtn = 0;
    floormove_t *f;
    line_t *li;

    while ((s1 = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        if (SEC_BUSY(s1))
            continue;
        rtn = 1;
        P_SectorLines(s1, &first);
        s2 = P_NextSector(P_SecLine(first), s1);
        if (s2 == NO_INDEX)
            continue;               /* (vanilla would crash) */
        count = P_SectorLines(s2, &first);
        for (n = 0; n < count; ++n) {
            ln = P_SecLine(first + n);
            li = P_Line(ln);
            /* vanilla's test of ML_TWOSIDED is `!flags & ML_TWOSIDED`,
             * always false: only the line back to s1 is skipped */
            if (li->backsector == s1 || li->backsector == NO_INDEX)
                continue;
            s3 = li->backsector;
            /* the rising slime */
            f = (floormove_t *)P_NewMover(T_MoveFloor, sizeof *f, s2);
            f->m.type = donutRaise;
            f->m.speed = FLOORSPEED / 2;
            f->direction = 1;
            f->texture = P_SectorFloorPic(s3);
            f->newspecial = 0;
            f->floordestheight = sec_floorh[s3];
            /* the lowering donut hole */
            f = (floormove_t *)P_NewMover(T_MoveFloor, sizeof *f, s1);
            f->m.type = lowerFloor;
            f->m.speed = FLOORSPEED / 2;
            f->direction = -1;
            f->floordestheight = sec_floorh[s3];
            break;
        }
    }
    return rtn;
}

/* --- the player on a special sector (vanilla P_PlayerInSpecialSector) --------------------------- */
void P_PlayerInSpecialSector(player_t *p)
{
    mobj_t *mo = p->mo;
    uint16_t s = mo->sector;
    uint8_t damage = 0;

    if (mo->z != FIX(sec_floorh[s]))
        return;                     /* not on the floor yet */
    switch (sec_special[s]) {
    case 5:                         /* hellslime */
        if (!p->powers[pw_ironfeet])
            damage = 10;
        break;
    case 7:                         /* nukage */
        if (!p->powers[pw_ironfeet])
            damage = 5;
        break;
    case 16:                        /* super hellslime */
    case 4:                         /* strobe hurt */
        if (!p->powers[pw_ironfeet] || P_Random() < 5)
            damage = 20;
        break;
    case 9:                         /* secret */
        ++p->secretcount;
        P_SetSectorSpecial(s, 0);
        return;
    case 11:                        /* E1M8's exit: god mode off, 20 a hit, out at 10 */
        p->cheats &= ~CF_GODMODE;
        if (!(leveltime & 0x1F))
            P_DamageMobj(mo, 0, 0, 20);
        if (p->health <= 10)
            G_ExitLevel();
        return;
    default:
        return;                     /* (vanilla: I_Error) */
    }
    if (damage && !(leveltime & 0x1F))
        P_DamageMobj(mo, 0, 0, damage);
}

/* --- the tic ------------------------------------------------------------------------------------ */
/* the sector specials that spawn something: lights, and the doors of 10
 * (closes after 30 s) and 14 (opens after 5 min) */
void P_SpawnSectorSpecial(uint16_t sector, uint8_t special)
{
    if (special == 10)
        P_SpawnDoorCloseIn30(sector);
    else if (special == 14)
        P_SpawnDoorRaiseIn5Mins(sector);
    else
        P_SpawnLight(sector, special);
}

void P_UpdateSpecials(void)
{
    uint8_t i;
    int16_t x;

    P_RunLights();
    P_RunButtons();
    /* scrolling walls: one unit a tic, from the offset they started at */
    for (i = 0; i < scroll_count; ++i) {
        x = scroll_list[2 * i + 1] + leveltime + 1;
        far_write(&x, P_LevAddr(MAPARR_SIDEDEFS, scroll_list[2 * i]) + SIDEDEF_XOFFSET, 2);
    }
}

/* before a lasting change of 1 or 2 bytes at addr: remember them. A full
 * journal (more than JOURNAL_MAX once-only lines used in a level) leaves
 * the later changes in place after a restart. */
void P_JournalBytes(far_t addr, uint8_t len)
{
    uint8_t e[6];

    if (jcount >= JOURNAL_MAX)
        return;
    e[0] = (uint8_t)addr;
    e[1] = (uint8_t)(addr >> 8);
    e[2] = (uint8_t)(addr >> 16);
    e[3] = len;
    far_read(addr, e + 4, len);
    far_write(e, FAR(kbanks - 2, JOURNAL_BASE + jcount * 6), 6);
    ++jcount;
}

void P_ClearLineSpecial(uint16_t line)
{
    P_JournalBytes(P_LevAddr(MAPARR_LINEDEFS, line) + LINEDEF_SPECIAL, 1);
    P_SetLineSpecial(line, 0);
}

/* --- level set-up and undoing (a_spec.s's end: in the set-up overlay) ----------------------------- */

void P_SpawnSpecials(void)
{
    uint16_t n, tag;
    uint8_t special, count;

    /* the tagged sectors and the lights */
    sec_busy = P_ArenaAlloc((numsectors + 7) >> 3);
    tag_count = 0;
    count = 0;
    for (n = 0; n < numsectors; ++n) {
        if (P_SectorTag(n))
            ++tag_count;
        special = sec_special[n];
        if ((special >= 1 && special <= 4) || special == 8 || special == 12 || special == 13
            || special == 17)
            ++count;
    }
    tag_list = P_ArenaAlloc(tag_count * 4);
    maxlights = count + SPARE_LIGHTS;
    lights = P_ArenaAlloc(maxlights * sizeof(light_t));
    numlights = 0;
    tag_count = 0;
    for (n = 0; n < numsectors; ++n) {
        tag = P_SectorTag(n);
        if (tag) {
            tag_list[2 * tag_count] = n;
            tag_list[2 * tag_count + 1] = tag;
            ++tag_count;
        }
        special = sec_special[n];
        if (special == 9)
            ++totalsecret;
        else if (special)
            P_SpawnSectorSpecial(n, special);
    }

    /* the scrolling walls: two passes over the lines' specials (one far
     * byte each) would cost twice; the list takes MAXSCROLLERS at most */
    scroll_list = P_ArenaAlloc(MAXSCROLLERS * 4);
    scroll_count = 0;
    for (n = 0; n < numlines; ++n)
        if (far_peek(P_LevAddr(MAPARR_LINEDEFS, n) + LINEDEF_SPECIAL) == 48
            && scroll_count < MAXSCROLLERS) {
            scroll_list[2 * scroll_count] = P_LineSide(n, 0);
            far_read(P_LevAddr(MAPARR_SIDEDEFS, scroll_list[2 * scroll_count]) + SIDEDEF_XOFFSET,
                     &scroll_list[2 * scroll_count + 1], 2);
            ++scroll_count;
        }
    P_ResetButtons(false);
}

/* the snapshots: where each map's SECTORS array is kept (0: not yet) */
#define SNAP_END        0xC000u
#define SNAP_MAPS       9           /* episode 1 */
static uint8_t snap_bank[SNAP_MAPS];
static uint16_t snap_addr[SNAP_MAPS];
static uint8_t snap_nextbank;
static uint16_t snap_next;

/* the map's SECTORS array between its far chunks and the snapshot (to 1:
 * into the snapshot) */
static void snapshot(const uint8_t *desc, uint8_t bank, uint16_t addr, boolean to)
{
    uint16_t count = desc[DESC_COUNT] | desc[DESC_COUNT + 1] << 8;
    uint16_t per = desc[DESC_LOG2] >= 16 ? 0xFFFF : (uint16_t)1 << desc[DESC_LOG2];
    uint16_t base = desc[DESC_ADDR] | desc[DESC_ADDR + 1] << 8, n, len;
    uint8_t chunk = desc[DESC_BANK];
    far_t live;

    while (count) {
        n = count < per ? count : per;
        len = n * SECTOR_SIZE;
        live = FAR(chunk, base);
        if (to)
            far_copy(live, FAR(bank, addr), len);
        else
            far_copy(FAR(bank, addr), live, len);
        addr += len;
        count -= n;
        ++chunk;
    }
}

void P_ResetLevelData(uint8_t map)
{
    uint8_t e[6], desc[DESC_SIZE], bank = kbanks - 2, i;
    uint16_t size;

    if (bank < DD_LAST_BANK + 2)
        kernel_crash(CRASH_BANKS);
    /* the level being left: buttons up, walls unscrolled, the journal back */
    P_ResetButtons(true);
    for (i = 0; i < scroll_count; ++i)
        far_write(&scroll_list[2 * i + 1],
                  P_LevAddr(MAPARR_SIDEDEFS, scroll_list[2 * i]) + SIDEDEF_XOFFSET, 2);
    scroll_count = 0;
    while (jcount) {
        --jcount;
        far_read(FAR(bank, JOURNAL_BASE + jcount * 6), e, 6);
        far_write(e + 4, FAR(e[2], e[0] | e[1] << 8), e[3]);
    }

    /* the level to load: its sectors from the snapshot, or a snapshot */
    if (map < 1 || map > SNAP_MAPS)
        return;
    far_read(FAR(DD_DIR_BANK, DD_MAPDIR + MAP_SIZE * (map - 1) + MAP_ARRAYS
                 + DESC_SIZE * MAPARR_SECTORS), desc, DESC_SIZE);
    if (snap_bank[map - 1]) {
        snapshot(desc, snap_bank[map - 1], snap_addr[map - 1], false);
        return;
    }
    size = (desc[DESC_COUNT] | desc[DESC_COUNT + 1] << 8) * SECTOR_SIZE;
    if (!snap_nextbank) {
        snap_nextbank = bank;
        snap_next = SNAP_BASE;
    }
    if (size > SNAP_END - snap_next) {
        --snap_nextbank;            /* the bank below, from $0200 */
        if (snap_nextbank < DD_LAST_BANK + 2)
            kernel_crash(CRASH_BANKS);
        snap_next = JOURNAL_BASE;
    }
    snap_bank[map - 1] = snap_nextbank;
    snap_addr[map - 1] = snap_next;
    snapshot(desc, snap_nextbank, snap_next, true);
    snap_next += size;
}

#endif /* !__CC65__ */

#endif
