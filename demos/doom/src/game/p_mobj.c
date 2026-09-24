/* Doom for the Appletini -- things: states, spawning, movement, and the two
 * representations (docs/DESIGN.md section 9).
 *
 * Vanilla p_mobj.c (P_SetMobjState, P_XYMovement, P_ZMovement,
 * P_MobjThinker, P_SpawnMobj, P_RemoveMobj, the map thing spawner, puffs,
 * blood, missiles) plus what the 6502's memory needs:
 *
 * Actors (mobj_t, 63 bytes on the 6502) live in a pool sized per level
 * from the level arena; statics (sobj_t, 16 bytes) in another. Every
 * thing a map places is spawned as a static: a pickup, a decoration, a
 * barrel, and a monster ("dormant": it only runs its spawn state loop).
 * Episode 1's largest map places 634 things on ultra-violence; as actors
 * they would need 37 KB.
 *
 *  - P_RunStatics (after the thinkers, every tic) counts the statics'
 *    tics and steps their states. Their states have no actions (items and
 *    decorations never do: gen_info.py marks every state whose chain is
 *    quiet), except the dormant monsters' A_Look. A_Look can only wake a
 *    monster if its sector's soundtarget is set or REJECT lets it see the
 *    player's sector (P_CheckSight tests REJECT first); otherwise vanilla's
 *    A_Look changes nothing, so the static skips it. When it may succeed
 *    the static is woken first and the actor runs the state as vanilla.
 *  - P_WakeStatic turns a static into an actor with the fields vanilla's
 *    thing would have: position, angle, state and tics, the flags its type
 *    and history give (ambush, dropped, corpse), spawn health, floor and
 *    ceiling of its sector. The iterators wake a static before anything
 *    can change it beyond a static's fields (damage, telefrag, crushing
 *    damage); read-only looks (aiming, pickups, collisions) see it through
 *    P_StaticView, a scratch mobj.
 *  - P_MobjThinker puts an actor back to sleep when it has become a
 *    static in all but name: not the player, not shootable, not a
 *    missile, no momentum, on its floor (or hanging), in a quiet state,
 *    flags that a static can say. Dropped items and corpses end there.
 *    Its references are cleared first (P_ForgetMobj).
 *
 * When the actor pool is full a woken monster stays dormant (it tries
 * again at its next look) and a spawn takes the slot of a puff, blood or
 * fog; with nothing to take, kernel_crash CRASH_MOBJS.
 */
#include "p_local.h"

/* on the 6502 this is a_mobj.s; the level-start spawner, the missile
 * spawners and P_FindTeleportDest are p_spawn.c on both */
#if defined(GAME_REAL) && !defined(__CC65__)

#include <string.h>

mobj_t *mobjs, *mobjs_end;
sobj_t *statics, *statics_end;
uint16_t nummobjs, numstatics, mobjs_used, statics_used;
static mobj_t *mobj_free;
static sobj_t *static_hint;
mobj_t sview;
sobj_t *sview_src;

#define STOPSPEED       0x1000
#define FRICTION        0xE800

/* --- the pools ------------------------------------------------------------ */
void P_InitMobjs(uint16_t nstatic)
{
    uint16_t i, avail;

    numstatics = nstatic;
    statics = P_ArenaAlloc(nstatic * sizeof(sobj_t));
    statics_end = statics + nstatic;
    for (i = 0; i < nstatic; ++i)
        statics[i].sflags = SF_FREE;
    static_hint = statics;
    statics_used = 0;

    avail = P_ArenaFree();
    avail = avail > ARENA_RESERVE ? avail - ARENA_RESERVE : 0;
    nummobjs = avail / sizeof(mobj_t);
    if (nummobjs > MAXACTORS)
        nummobjs = MAXACTORS;
    mobjs = P_ArenaAlloc(nummobjs * sizeof(mobj_t));
    mobjs_end = mobjs + nummobjs;
    mobj_free = 0;
    for (i = nummobjs; i-- > 0;) {
        mobjs[i].thinker.next = (thinker_t *)mobj_free;
        mobj_free = &mobjs[i];
    }
    mobjs_used = 0;
    player.mo = 0;
}

/* An actor slot: the free list, else a puff/blood/fog removed on the spot. */
static mobj_t *P_AllocActor(boolean must)
{
    mobj_t *mo;

    if (!mobj_free) {
        for (mo = mobjs; mo < mobjs_end; ++mo)
            if (mo->thinker.function && mo->thinker.function != THINK_REMOVED
                && (mo->type == MT_PUFF || mo->type == MT_BLOOD
                    || mo->type == MT_TFOG || mo->type == MT_IFOG)) {
                P_RemoveMobj(mo);
                P_UnlinkThinker(&mo->thinker);
                P_FreeActor(mo);
                break;
            }
        if (!mobj_free) {
            if (must)
                kernel_crash(CRASH_MOBJS);
            return 0;
        }
    }
    mo = mobj_free;
    mobj_free = (mobj_t *)mo->thinker.next;
    memset(mo, 0, sizeof *mo);
    ++mobjs_used;
    return mo;
}

/* p_tick.c calls this when a removed actor leaves the thinker list */
void P_FreeActor(mobj_t *mo)
{
    mo->thinker.function = 0;
    mo->thinker.next = (thinker_t *)mobj_free;
    mobj_free = mo;
    --mobjs_used;
}

sobj_t *P_AllocStatic(void)
{
    sobj_t *s = static_hint;
    uint16_t n;

    for (n = numstatics; n; --n) {
        if (s->sflags & SF_FREE) {
            static_hint = s;
            s->sflags = 0;
            ++statics_used;
            return s;
        }
        if (++s == statics_end)
            s = statics;
    }
    return 0;
}

/* The slot's bnext is left alone: an iterator may be standing on it. */
static void P_FreeStatic(sobj_t *s)
{
    s->sflags = SF_FREE;
    --statics_used;
}

/* --- statics seen as mobjs ---------------------------------------------------- */
uint32_t P_StaticFlags(sobj_t *s)
{
    uint32_t f = mobjinfo[s->type].flags;
    uint8_t sf = s->sflags;

    if (sf & SF_CORPSE) {
        f &= ~(MF_SHOOTABLE | MF_FLOAT | MF_SKULLFLY | MF_SOLID);
        if (s->type != MT_SKULL)
            f &= ~MF_NOGRAVITY;
        f |= MF_CORPSE | MF_DROPOFF;
    }
    if (sf & SF_GIBS)
        f &= ~MF_SOLID;
    if (sf & SF_AMBUSH)
        f |= MF_AMBUSH;
    if (sf & SF_DROPPED)
        f |= MF_DROPPED;
    return f;
}

static fixed_t static_height(sobj_t *s)
{
    if (s->sflags & SF_GIBS)
        return 0;
    if (s->sflags & SF_CORPSE)
        return FIX(mobjinfo[s->type].height) >> 2;
    return FIX(mobjinfo[s->type].height);
}

fixed_t P_ThingHeight(mobj_t *thing)
{
    return IS_STATIC(thing) ? static_height(AS_STATIC(thing)) : thing->height;
}

uint8_t P_ThingRadius(mobj_t *thing)
{
    if (IS_STATIC(thing))
        return (AS_STATIC(thing)->sflags & SF_GIBS) ? 0 : mobjinfo[AS_STATIC(thing)->type].radius;
    return thing->radius;
}

/* the fields of an actor that a static defines */
static void static_to_mobj(sobj_t *s, mobj_t *mo)
{
    mo->x = FIX(s->x);
    mo->y = FIX(s->y);
    mo->z = FIX(s->z);
    mo->type = s->type;
    mo->state = s->state;
    mo->tics = s->tics;
    mo->angle = (angle_t)s->angle << 8;
    mo->sector = s->sector;
    mo->flags = P_StaticFlags(s);
    mo->height = static_height(s);
    mo->radius = (s->sflags & SF_GIBS) ? 0 : mobjinfo[s->type].radius;
    mo->health = (s->sflags & SF_CORPSE) ? 0 : mobjinfo[s->type].spawnhealth;
    mo->floorz = sec_floorh[s->sector];
    mo->ceilingz = sec_ceilh[s->sector];
    if (gameskill != sk_nightmare)
        mo->reactiontime = mobjinfo[s->type].reactiontime;
    mo->lastlook = (s->sflags & SF_LOOK1) ? 1 : 0;
}

mobj_t *P_StaticView(sobj_t *s)
{
    memset(&sview, 0, sizeof sview);
    static_to_mobj(s, &sview);
    sview_src = s;
    return &sview;
}

/* the pointer in the blockmap chain that points at thing */
static mobj_t **chain_link(mobj_t *thing, int16_t x, int16_t y)
{
    int16_t bx = (x - bmaporgx) >> 7, by = (y - bmaporgy) >> 7;
    mobj_t **link;

    if (bx < 0 || by < 0 || bx >= bmapwidth || by >= bmapheight)
        return 0;
    link = &blocklinks[(uint16_t)by * bmapwidth + bx];
    while (*link && *link != thing)
        link = IS_STATIC(*link) ? &AS_STATIC(*link)->bnext : &(*link)->bnext;
    return *link ? link : 0;
}

mobj_t *P_WakeStatic(sobj_t *s)
{
    mobj_t *mo, **link;

    mo = P_AllocActor(false);
    if (!mo)
        return 0;
    static_to_mobj(s, mo);
    mo->thinker.function = (think_t)P_MobjThinker;
    P_AddThinker(&mo->thinker);
    if (!(s->sflags & SF_NOBLOCK)) {
        link = chain_link((mobj_t *)s, s->x, s->y);
        if (link) {
            mo->bnext = s->bnext;
            *link = mo;
        }
    }
    if (sview_src == s)
        sview_src = 0;
    P_FreeStatic(s);
    return mo;
}

mobj_t *P_Actor(mobj_t *thing)
{
    if (IS_STATIC(thing))
        return P_WakeStatic(AS_STATIC(thing));
    if (thing == &sview)
        return sview_src ? P_WakeStatic(sview_src) : 0;
    return thing;
}

/* Clear every reference to an actor that is going away (removed, or put
 * to sleep): vanilla keeps dangling pointers into freed zone memory; the
 * pool reuses slots at once, so they are cut. */
void P_ForgetMobj(mobj_t *gone)
{
    mobj_t *mo;
    uint16_t i;

    for (mo = mobjs; mo < mobjs_end; ++mo) {
        if (mo->target == gone)
            mo->target = 0;
        if (mo->tracer == gone)
            mo->tracer = 0;
    }
    if (player.attacker == gone)
        player.attacker = 0;
    for (i = 0; i < numsectors; ++i)
        if (sec_soundtarget[i] == gone)
            sec_soundtarget[i] = 0;
}

/* An actor that can live on as a static does. */
static void P_TrySleep(mobj_t *mo)
{
    sobj_t *s;
    uint8_t sf;
    mobj_t **link;

    if (FLAG(mo->flags, MF_SHOOTABLE) || FLAG(mo->flags, MF_MISSILE)
        || FLAG(mo->flags, MF_SKULLFLY) || mo == player.mo)
        return;
    if (mo->momx || mo->momy || mo->momz)
        return;
    if (mo->z != FIX(mo->floorz) && !FLAG(mo->flags, MF_NOGRAVITY))
        return;
    if (mo->tics != ST_FOREVER && !(st_action[mo->state] & 0x80))
        return;
    sf = 0;
    if (FLAG(mo->flags, MF_CORPSE))
        sf |= SF_CORPSE;
    if (!mo->radius)
        sf |= SF_GIBS;
    if (FLAG(mo->flags, MF_DROPPED))
        sf |= SF_DROPPED;
    if (FLAG(mo->flags, MF_AMBUSH))
        sf |= SF_AMBUSH;
    if (FLAG(mo->flags, MF_NOBLOCKMAP))
        sf |= SF_NOBLOCK;
    s = P_AllocStatic();
    if (!s)
        return;
    s->sflags = sf;
    s->type = mo->type;
    if ((mo->flags & ~(MF_JUSTHIT | MF_JUSTATTACKED | MF_INFLOAT)) != P_StaticFlags(s)
        || mo->height != static_height(s)) {
        P_FreeStatic(s);
        return;
    }
    s->x = UNITS(mo->x);
    s->y = UNITS(mo->y);
    s->z = UNITS(mo->z);
    s->angle = mo->angle >> 8;
    s->state = mo->state;
    s->tics = mo->tics;
    s->sector = mo->sector;
    s->bnext = 0;
    if (!(sf & SF_NOBLOCK)) {
        link = chain_link(mo, s->x, s->y);
        if (link) {
            s->bnext = mo->bnext;
            *link = (mobj_t *)s;
        }
    }
    P_ForgetMobj(mo);
    P_RemoveThinker(&mo->thinker);
}

/* --- states -------------------------------------------------------------------- */
boolean P_SetMobjState(mobj_t *mobj, uint16_t state)
{
    uint8_t ac;

    do {
        if (state == S_NULL) {
            mobj->state = S_NULL;
            P_RemoveMobj(mobj);
            return false;
        }
        mobj->state = state;
        mobj->tics = st_tics[state];
        ac = st_action[state] & 0x7F;
        if (ac)
            mobj_actions[ac](mobj);
        state = st_next[state];
    } while (!mobj->tics);
    return true;
}

void P_ExplodeMissile(mobj_t *mo)
{
    mo->momx = mo->momy = mo->momz = 0;
    P_SetMobjState(mo, mobjinfo[mo->type].deathstate);
    mo->tics -= P_Random() & 3;
    if ((int8_t)mo->tics < 1)
        mo->tics = 1;
    FLAGS_CLR(mo->flags, MF_MISSILE);
    if (mobjinfo[mo->type].deathsound)
        S_StartSound(mo, mobjinfo[mo->type].deathsound);
}

/* --- movement --------------------------------------------------------------------- */
static void P_XYMovement(mobj_t *mo)
{
    fixed_t ptryx, ptryy, xmove, ymove;
    player_t *pl;

    if (!mo->momx && !mo->momy) {
        if (FLAG(mo->flags, MF_SKULLFLY)) {
            FLAGS_CLR(mo->flags, MF_SKULLFLY);
            mo->momx = mo->momy = mo->momz = 0;
            P_SetMobjState(mo, mobjinfo[mo->type].spawnstate);
        }
        return;
    }
    pl = MO_PLAYER(mo);
    if (mo->momx > MAXMOVE)
        mo->momx = MAXMOVE;
    else if (mo->momx < -MAXMOVE)
        mo->momx = -MAXMOVE;
    if (mo->momy > MAXMOVE)
        mo->momy = MAXMOVE;
    else if (mo->momy < -MAXMOVE)
        mo->momy = -MAXMOVE;
    xmove = mo->momx;
    ymove = mo->momy;
    do {
        if (xmove > MAXMOVE / 2 || ymove > MAXMOVE / 2) {
            ptryx = mo->x + xmove / 2;
            ptryy = mo->y + ymove / 2;
            xmove >>= 1;
            ymove >>= 1;
        } else {
            ptryx = mo->x + xmove;
            ptryy = mo->y + ymove;
            xmove = ymove = 0;
        }
        if (!P_TryMove(mo, ptryx, ptryy)) {
            if (pl) {
                P_SlideMove(mo);
            } else if (FLAG(mo->flags, MF_MISSILE)) {
                /* vanilla's hack: missiles vanish against a sky ceiling */
                if (ceilingline != NO_INDEX) {
                    line_t *li = P_Line(ceilingline);
                    if (li->backsector != NO_INDEX
                        && P_SectorCeilingPic(li->backsector) == skyflatnum) {
                        P_RemoveMobj(mo);
                        return;
                    }
                }
                P_ExplodeMissile(mo);
            } else {
                mo->momx = mo->momy = 0;
            }
        }
    } while (xmove || ymove);

    if (pl && (pl->cheats & CF_NOMOMENTUM)) {
        mo->momx = mo->momy = 0;
        return;
    }
    if (FLAG(mo->flags, MF_MISSILE) || FLAG(mo->flags, MF_SKULLFLY))
        return;
    if (mo->z > FIX(mo->floorz))
        return;
    if (FLAG(mo->flags, MF_CORPSE)) {
        if (mo->momx > FRACUNIT / 4 || mo->momx < -FRACUNIT / 4
            || mo->momy > FRACUNIT / 4 || mo->momy < -FRACUNIT / 4) {
            if (mo->floorz != sec_floorh[mo->sector])
                return;
        }
    }
    if (mo->momx > -STOPSPEED && mo->momx < STOPSPEED
        && mo->momy > -STOPSPEED && mo->momy < STOPSPEED
        && (!pl || (pl->cmd.forwardmove == 0 && pl->cmd.sidemove == 0))) {
        if (pl && (uint16_t)(pl->mo->state - S_PLAY_RUN1) < 4)
            P_SetMobjState(pl->mo, S_PLAY);
        mo->momx = 0;
        mo->momy = 0;
    } else {
        mo->momx = FixedMul(mo->momx, FRICTION);
        mo->momy = FixedMul(mo->momy, FRICTION);
    }
}

static void P_ZMovement(mobj_t *mo)
{
    fixed_t dist, delta, floorz = FIX(mo->floorz);
    player_t *pl = MO_PLAYER(mo);

    if (pl && mo->z < floorz) {
        pl->viewheight -= floorz - mo->z;
        pl->deltaviewheight = (VIEWHEIGHT - pl->viewheight) >> 3;
    }
    mo->z += mo->momz;
    if (FLAG(mo->flags, MF_FLOAT) && mo->target) {
        if (!FLAG(mo->flags, MF_SKULLFLY) && !FLAG(mo->flags, MF_INFLOAT)) {
            dist = P_AproxDistance(mo->x - mo->target->x, mo->y - mo->target->y);
            delta = (mo->target->z + (mo->height >> 1)) - mo->z;
            if (delta < 0 && dist < -(delta * 3))
                mo->z -= FLOATSPEED;
            else if (delta > 0 && dist < (delta * 3))
                mo->z += FLOATSPEED;
        }
    }
    if (mo->z <= floorz) {
        /* Ultimate Doom's lost soul bounce */
        if (FLAG(mo->flags, MF_SKULLFLY))
            mo->momz = -mo->momz;
        if (mo->momz < 0) {
            if (pl && mo->momz < -GRAVITY * 8) {
                pl->deltaviewheight = mo->momz >> 3;
                S_StartSound(mo, sfx_oof);
            }
            mo->momz = 0;
        }
        mo->z = floorz;
        if (FLAG(mo->flags, MF_MISSILE) && !FLAG(mo->flags, MF_NOCLIP)) {
            P_ExplodeMissile(mo);
            return;
        }
    } else if (!FLAG(mo->flags, MF_NOGRAVITY)) {
        if (mo->momz == 0)
            mo->momz = -GRAVITY * 2;
        else
            mo->momz -= GRAVITY;
    }
    if (mo->z + mo->height > FIX(mo->ceilingz)) {
        if (mo->momz > 0)
            mo->momz = 0;
        mo->z = FIX(mo->ceilingz) - mo->height;
        if (FLAG(mo->flags, MF_SKULLFLY))
            mo->momz = -mo->momz;
        if (FLAG(mo->flags, MF_MISSILE) && !FLAG(mo->flags, MF_NOCLIP)) {
            P_ExplodeMissile(mo);
            return;
        }
    }
}

void P_MobjThinker(mobj_t *mobj)
{
    if (mobj->momx || mobj->momy || FLAG(mobj->flags, MF_SKULLFLY)) {
        P_XYMovement(mobj);
        if (mobj->thinker.function == THINK_REMOVED)
            return;
    }
    if (mobj->z != FIX(mobj->floorz) || mobj->momz) {
        P_ZMovement(mobj);
        if (mobj->thinker.function == THINK_REMOVED)
            return;
    }
    if (mobj->tics != ST_FOREVER) {
        if (!--mobj->tics)
            if (!P_SetMobjState(mobj, st_next[mobj->state]))
                return;
    }
    /* (nightmare respawn: not in this port) */
    P_TrySleep(mobj);
}

/* --- spawning ------------------------------------------------------------------------ */
mobj_t *P_SpawnMobj(fixed_t x, fixed_t y, fixed_t z, uint8_t type)
{
    mobj_t *mobj = P_AllocActor(true);
    const mobjinfo_t *info = &mobjinfo[type];

    mobj->type = type;
    mobj->x = x;
    mobj->y = y;
    mobj->radius = info->radius;
    mobj->height = FIX(info->height);
    mobj->flags = info->flags;
    mobj->health = info->spawnhealth;
    if (gameskill != sk_nightmare)
        mobj->reactiontime = info->reactiontime;
    mobj->lastlook = P_Random() & 3;    /* vanilla's P_Random() % MAXPLAYERS */
    mobj->state = info->spawnstate;
    mobj->tics = st_tics[mobj->state];
    P_SetThingPosition(mobj);
    mobj->floorz = sec_floorh[mobj->sector];
    mobj->ceilingz = sec_ceilh[mobj->sector];
    if (z == ONFLOORZ)
        mobj->z = FIX(mobj->floorz);
    else if (z == ONCEILINGZ)
        mobj->z = FIX(mobj->ceilingz) - FIX(info->height);
    else
        mobj->z = z;
    mobj->thinker.function = (think_t)P_MobjThinker;
    P_AddThinker(&mobj->thinker);
    return mobj;
}

void P_RemoveMobj(mobj_t *mobj)
{
    sobj_t *s;

    if (mobj == &sview) {
        s = sview_src;
        if (s) {
            if (!(s->sflags & SF_NOBLOCK))
                P_UnlinkStatic(s);
            P_FreeStatic(s);
            sview_src = 0;
        }
        return;
    }
    if (IS_STATIC(mobj)) {
        s = AS_STATIC(mobj);
        if (!(s->sflags & SF_NOBLOCK))
            P_UnlinkStatic(s);
        P_FreeStatic(s);
        return;
    }
    /* (deathmatch item respawn queue: not in this port) */
    P_UnsetThingPosition(mobj);
    if (FLAG(mobjinfo[mobj->type].flags, MF_SHOOTABLE))
        P_ForgetMobj(mobj);
    P_RemoveThinker(&mobj->thinker);
}

/* --- the statics' tic --------------------------------------------------------------------- */
/* A dormant monster's A_Look can succeed only if its sector heard a noise
 * or REJECT lets it see the living player. */
static boolean P_DormantMayWake(sobj_t *s)
{
    if (sec_soundtarget[s->sector])
        return true;
    return player.mo != 0 && player.health > 0 && P_RejectVisible(s->sector, player.mo->sector);
}

void P_RunStatics(void)
{
    sobj_t *s;
    uint16_t st;
    uint8_t ac;
    mobj_t *mo;

    for (s = statics; s < statics_end; ++s) {
        if ((s->sflags & SF_FREE) || s->tics == ST_FOREVER)
            continue;
        if (--s->tics)
            continue;
        st = s->state;
        do {
            st = st_next[st];
            if (st == S_NULL) {
                if (!(s->sflags & SF_NOBLOCK))
                    P_UnlinkStatic(s);
                P_FreeStatic(s);
                break;
            }
            ac = st_action[st] & 0x7F;
            if (ac && (ac != AC_Look || !(s->sflags & SF_DORMANT) || P_DormantMayWake(s))) {
                mo = P_WakeStatic(s);
                if (mo) {
                    P_SetMobjState(mo, st);
                    break;
                }
                /* no actor slot: the state runs without its action */
            }
            s->state = st;
            s->tics = st_tics[st];
        } while (!s->tics);
    }
}

/* --- puffs, blood, missiles ----------------------------------------------------------------- */
void P_SpawnPuff(fixed_t x, fixed_t y, fixed_t z)
{
    mobj_t *th;

    z += (fixed_t)P_SubRandom() << 10;
    th = P_SpawnMobj(x, y, z, MT_PUFF);
    th->momz = FRACUNIT;
    th->tics -= P_Random() & 3;
    if ((int8_t)th->tics < 1)
        th->tics = 1;
    if (attackrange == MELEERANGE)
        P_SetMobjState(th, S_PUFF3);
}

void P_SpawnBlood(fixed_t x, fixed_t y, fixed_t z, int16_t damage)
{
    mobj_t *th;

    z += (fixed_t)P_SubRandom() << 10;
    th = P_SpawnMobj(x, y, z, MT_BLOOD);
    th->momz = FRACUNIT * 2;
    th->tics -= P_Random() & 3;
    if ((int8_t)th->tics < 1)
        th->tics = 1;
    if (damage <= 12 && damage >= 9)
        P_SetMobjState(th, S_BLOOD2);
    else if (damage < 9)
        P_SetMobjState(th, S_BLOOD3);
}

void P_CheckMissileSpawn(mobj_t *th)
{
    th->tics -= P_Random() & 3;
    if ((int8_t)th->tics < 1)
        th->tics = 1;
    th->x += th->momx >> 1;
    th->y += th->momy >> 1;
    th->z += th->momz >> 1;
    if (!P_TryMove(th, th->x, th->y))
        P_ExplodeMissile(th);
}

#endif
