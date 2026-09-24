/* Doom for the Appletini -- the monsters' minds (docs/DESIGN.md section 9).
 *
 * Vanilla p_enemy.c (Doom 1.9) for the monsters of episode 1: waking by
 * sight or by sound (A_Look, P_NoiseAlert), the chase (A_Chase with
 * P_Move, P_TryWalk, P_NewChaseDir), the attack decisions
 * (P_CheckMeleeRange, P_CheckMissileRange) and the attacks of the
 * zombieman, shotgun guy, imp, demon and spectre, cacodemon, baron and
 * lost soul, the death actions and the E1M8 boss death. One player; the
 * sound hook is S_StartSound (the sound part plays it).
 *
 * Where this differs from vanilla it is the storage:
 *
 *  - lastlook: with one player vanilla's P_LookForPlayers only looks at
 *    player 0; a lastlook of 1 (P_Random() % 4 at spawn) ends the first
 *    look before it, every other value looks; afterwards it is always 0.
 *    Actors keep the byte, statics a bit (SF_LOOK1).
 *  - The sound flood (P_RecursiveSound) keeps its per-sector "traversed"
 *    level in sec_soundtraversed (level memory), cleared at each alert in
 *    place of vanilla's sector validcount; its result (which sectors get
 *    the sound target) is vanilla's. It recurses as vanilla does here;
 *    the 6502 version floods with a queue and skips an alert from a
 *    sector it has already flooded while no sector height has changed
 *    (the flood is a function of the start sector and the openings).
 *  - P_LookForPlayers asks whether the player is behind the monster's
 *    back before it looks (vanilla looks first): the answer is the same,
 *    and a sight walk costs far more than an angle. (What differs is only
 *    the line marks a walk leaves, which matter to a collision test in
 *    progress around it, as in vanilla, when a missile's hit wakes a
 *    monster whose chase loses its target at once.)
 *  - A_BossDeath scans the statics as well as the thinkers for a boss
 *    still alive (a dormant baron is a static here), and lowers the
 *    floors tagged 666 through EV_DoFloorTag (vanilla builds a fake line).
 *
 * On the 6502 this is a_enemy.s.
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)

#include <string.h>

static uint8_t *sec_soundtraversed;     /* 0: not reached by this flood, else soundblocks + 1 */
static mobj_t *soundtarget;

static const uint8_t opposite[9] = {
    DI_WEST, DI_SOUTHWEST, DI_SOUTH, DI_SOUTHEAST,
    DI_EAST, DI_NORTHEAST, DI_NORTH, DI_NORTHWEST, DI_NODIR
};
static const uint8_t diags[4] = { DI_NORTHWEST, DI_NORTHEAST, DI_SOUTHWEST, DI_SOUTHEAST };

void P_MonstersSetupLevel(void)
{
    sec_soundtraversed = P_ArenaAlloc(numsectors);
}

/* --- waking by sound ------------------------------------------------------------ */
static void P_RecursiveSound(uint16_t sec, uint8_t soundblocks)
{
    uint16_t first, count, i, lnum, other;
    line_t *check;
    uint8_t lflags;

    /* wake up all monsters in this sector */
    if (sec_soundtraversed[sec] && sec_soundtraversed[sec] <= soundblocks + 1)
        return;                     /* already flooded */
    sec_soundtraversed[sec] = soundblocks + 1;
    sec_soundtarget[sec] = soundtarget;
    count = P_SectorLines(sec, &first);
    for (i = 0; i < count; ++i) {
        lnum = P_SecLine(first + i);
        check = P_Line(lnum);
        lflags = check->flags;
        if (!(lflags & ML_TWOSIDED))
            continue;
        P_LineOpening(check);
        if (openrange <= 0)
            continue;               /* closed door */
        other = check->frontsector == sec ? check->backsector : check->frontsector;
        if (lflags & ML_SOUNDBLOCK) {
            if (!soundblocks)
                P_RecursiveSound(other, 1);
        } else {
            P_RecursiveSound(other, soundblocks);
        }
    }
}

/* If a monster yells at a player, it will alert other monsters to the
 * player (vanilla: every shot of the player's weapons). */
void P_NoiseAlert(mobj_t *target, mobj_t *emitter)
{
    soundtarget = target;
    memset(sec_soundtraversed, 0, numsectors);
    P_RecursiveSound(emitter->sector, 0);
}

/* --- range checks ----------------------------------------------------------------- */
static boolean P_CheckMeleeRange(mobj_t *actor)
{
    mobj_t *pl = actor->target;
    fixed_t dist;

    if (!pl)
        return false;
    dist = P_AproxDistance(pl->x - actor->x, pl->y - actor->y);
    if (dist >= MELEERANGE - 20 * FRACUNIT + FIX(mobjinfo[pl->type].radius))
        return false;
    if (!P_CheckSight(actor, actor->target))
        return false;
    return true;
}

static boolean P_CheckMissileRange(mobj_t *actor)
{
    fixed_t dist;

    if (!P_CheckSight(actor, actor->target))
        return false;
    if (FLAG(actor->flags, MF_JUSTHIT)) {
        /* the target just hit the enemy, so fight back! */
        FLAGS_CLR(actor->flags, MF_JUSTHIT);
        return true;
    }
    if (actor->reactiontime)
        return false;               /* do not attack yet */
    dist = P_AproxDistance(actor->x - actor->target->x, actor->y - actor->target->y)
           - 64 * FRACUNIT;
    if (!mobjinfo[actor->type].meleestate)
        dist -= 128 * FRACUNIT;     /* no melee attack, so fire more */
    dist >>= FRACBITS;
    if (actor->type == MT_SKULL)
        dist >>= 1;
    if (dist > 200)
        dist = 200;
    if (P_Random() < dist)
        return false;
    return true;
}

/* --- moving ---------------------------------------------------------------------------- */
static const fixed_t xspeed[8] = { FRACUNIT, 47000, 0, -47000, -FRACUNIT, -47000, 0, 47000 };
static const fixed_t yspeed[8] = { 0, 47000, FRACUNIT, 47000, 0, -47000, -FRACUNIT, -47000 };

/* Move in the current direction; false if the move is blocked. */
static boolean P_Move(mobj_t *actor)
{
    fixed_t tryx, tryy;
    boolean good;
    uint8_t speed;

    if (actor->movedir == DI_NODIR)
        return false;
    speed = mobjinfo[actor->type].speed;
    tryx = actor->x + speed * xspeed[actor->movedir];
    tryy = actor->y + speed * yspeed[actor->movedir];
    if (!P_TryMove(actor, tryx, tryy)) {
        /* open any specials */
        if (FLAG(actor->flags, MF_FLOAT) && floatok) {
            /* must adjust height */
            if (actor->z < tmfloorz)
                actor->z += FLOATSPEED;
            else
                actor->z -= FLOATSPEED;
            FLAGS_SET(actor->flags, MF_INFLOAT);
            return true;
        }
        if (!numspechit)
            return false;
        actor->movedir = DI_NODIR;
        good = false;
        while (numspechit--) {
            /* if the special is not a door that can be opened, false */
            if (P_UseSpecialLine(actor, spechit[numspechit], 0))
                good = true;
        }
        return good;
    }
    FLAGS_CLR(actor->flags, MF_INFLOAT);
    if (!FLAG(actor->flags, MF_FLOAT))
        actor->z = FIX(actor->floorz);
    return true;
}

/* Attempts to move the actor in its current direction; if blocked by a
 * wall or an actor, false; if the move is clear or blocked only by a
 * door, true, with a new movecount. */
static boolean P_TryWalk(mobj_t *actor)
{
    if (!P_Move(actor))
        return false;
    actor->movecount = P_Random() & 15;
    return true;
}

static void P_NewChaseDir(mobj_t *actor)
{
    fixed_t deltax, deltay, ax, ay;
    uint8_t d1, d2, tdir, olddir, turnaround;

    olddir = actor->movedir;
    turnaround = opposite[olddir];
    deltax = actor->target->x - actor->x;
    deltay = actor->target->y - actor->y;
    if (deltax > 10 * FRACUNIT)
        d1 = DI_EAST;
    else if (deltax < -10 * FRACUNIT)
        d1 = DI_WEST;
    else
        d1 = DI_NODIR;
    if (deltay < -10 * FRACUNIT)
        d2 = DI_SOUTH;
    else if (deltay > 10 * FRACUNIT)
        d2 = DI_NORTH;
    else
        d2 = DI_NODIR;
    /* try the direct route */
    if (d1 != DI_NODIR && d2 != DI_NODIR) {
        actor->movedir = diags[((deltay < 0) << 1) + (deltax > 0)];
        if (actor->movedir != turnaround && P_TryWalk(actor))
            return;
    }
    /* try other directions */
    ax = deltax < 0 ? -deltax : deltax;
    ay = deltay < 0 ? -deltay : deltay;
    if (P_Random() > 200 || ay > ax) {
        tdir = d1;
        d1 = d2;
        d2 = tdir;
    }
    if (d1 == turnaround)
        d1 = DI_NODIR;
    if (d2 == turnaround)
        d2 = DI_NODIR;
    if (d1 != DI_NODIR) {
        actor->movedir = d1;
        if (P_TryWalk(actor))
            return;                 /* either moved forward or attacked */
    }
    if (d2 != DI_NODIR) {
        actor->movedir = d2;
        if (P_TryWalk(actor))
            return;
    }
    /* there is no direct path to the player, so pick another direction */
    if (olddir != DI_NODIR) {
        actor->movedir = olddir;
        if (P_TryWalk(actor))
            return;
    }
    /* randomly determine the direction of search */
    if (P_Random() & 1) {
        for (tdir = DI_EAST; tdir <= DI_SOUTHEAST; ++tdir) {
            if (tdir != turnaround) {
                actor->movedir = tdir;
                if (P_TryWalk(actor))
                    return;
            }
        }
    } else {
        for (tdir = DI_SOUTHEAST + 1; tdir-- > DI_EAST;) {
            if (tdir != turnaround) {
                actor->movedir = tdir;
                if (P_TryWalk(actor))
                    return;
            }
        }
    }
    if (turnaround != DI_NODIR) {
        actor->movedir = turnaround;
        if (P_TryWalk(actor))
            return;
    }
    actor->movedir = DI_NODIR;      /* can not move */
}

/* vanilla P_LookForPlayers for one player (see the header for lastlook).
 * If allaround is false, only look 180 degrees in front. */
static boolean P_LookForPlayers(mobj_t *actor, boolean allaround)
{
    angle_t an;
    fixed_t dist;
    mobj_t *pmo = player.mo;

    if (actor->lastlook == 1) {
        actor->lastlook = 0;
        return false;               /* vanilla stops at player 0 before looking */
    }
    actor->lastlook = 0;
    if (player.health <= 0)
        return false;               /* dead */
    /* (vanilla looks first, then asks whether the player is behind its
     * back: the answer is the same with the cheap question first) */
    if (!allaround) {
        an = R_PointToAngle2(actor->x, actor->y, pmo->x, pmo->y) - actor->angle;
        if (an > ANG90 && an < ANG270) {
            dist = P_AproxDistance(pmo->x - actor->x, pmo->y - actor->y);
            if (dist > MELEERANGE)
                return false;       /* behind back (if real close, react anyway) */
        }
    }
    if (!P_CheckSight(actor, pmo))
        return false;               /* out of sight */
    actor->target = pmo;
    return true;
}

/* --- actions ------------------------------------------------------------------------- */
/* Stay in state until a player is sighted. */
void A_Look(mobj_t *actor)
{
    mobj_t *targ;
    uint8_t sound;
    const mobjinfo_t *info = &mobjinfo[actor->type];

    actor->threshold = 0;           /* any shot will wake up */
    targ = sec_soundtarget[actor->sector];
    if (targ && FLAG(targ->flags, MF_SHOOTABLE)) {
        actor->target = targ;
        if (FLAG(actor->flags, MF_AMBUSH)) {
            if (P_CheckSight(actor, actor->target))
                goto seeyou;
        } else {
            goto seeyou;
        }
    }
    if (!P_LookForPlayers(actor, false))
        return;
seeyou:
    /* go into chase state */
    if (info->seesound) {
        switch (info->seesound) {
        case sfx_posit1:
        case sfx_posit2:
        case sfx_posit3:
            sound = sfx_posit1 + P_Random() % 3;
            break;
        case sfx_bgsit1:
        case sfx_bgsit2:
            sound = sfx_bgsit1 + P_Random() % 2;
            break;
        default:
            sound = info->seesound;
            break;
        }
        S_StartSound(actor, sound);
    }
    P_SetMobjState(actor, info->seestate);
}

/* Actor has a melee attack, so it tries to close as fast as possible. */
void A_Chase(mobj_t *actor)
{
    int16_t delta;
    const mobjinfo_t *info = &mobjinfo[actor->type];

    if (actor->reactiontime)
        actor->reactiontime--;
    /* modify target threshold */
    if (actor->threshold) {
        if (!actor->target || actor->target->health <= 0)
            actor->threshold = 0;
        else
            actor->threshold--;
    }
    /* turn towards movement direction if not there yet */
    if (actor->movedir < 8) {
        actor->angle &= 0xE000;     /* vanilla 7 << 29 */
        delta = (int16_t)(actor->angle - (actor->movedir << 13));
        if (delta > 0)
            actor->angle -= ANG90 / 2;
        else if (delta < 0)
            actor->angle += ANG90 / 2;
    }
    if (!actor->target || !FLAG(actor->target->flags, MF_SHOOTABLE)) {
        /* look for a new target */
        if (P_LookForPlayers(actor, true))
            return;                 /* got a new target */
        P_SetMobjState(actor, info->spawnstate);
        return;
    }
    /* do not attack twice in a row */
    if (FLAG(actor->flags, MF_JUSTATTACKED)) {
        FLAGS_CLR(actor->flags, MF_JUSTATTACKED);
        if (gameskill != sk_nightmare)
            P_NewChaseDir(actor);
        return;
    }
    /* check for melee attack */
    if (info->meleestate && P_CheckMeleeRange(actor)) {
        if (info->attacksound)
            S_StartSound(actor, info->attacksound);
        P_SetMobjState(actor, info->meleestate);
        return;
    }
    /* check for missile attack */
    if (info->missilestate) {
        if (gameskill < sk_nightmare && actor->movecount)
            goto nomissile;
        if (!P_CheckMissileRange(actor))
            goto nomissile;
        P_SetMobjState(actor, info->missilestate);
        FLAGS_SET(actor->flags, MF_JUSTATTACKED);
        return;
    }
nomissile:
    /* chase towards player; vanilla's movecount is an int that goes on
     * down while no walk succeeds: a signed byte that stops at -128 keeps
     * every sign it has */
    if ((int8_t)actor->movecount != -128)
        --actor->movecount;
    if ((int8_t)actor->movecount < 0 || !P_Move(actor))
        P_NewChaseDir(actor);
    /* make active sound */
    if (info->activesound && P_Random() < 3)
        S_StartSound(actor, info->activesound);
}

void A_FaceTarget(mobj_t *actor)
{
    if (!actor->target)
        return;
    FLAGS_CLR(actor->flags, MF_AMBUSH);
    actor->angle = R_PointToAngle2(actor->x, actor->y, actor->target->x, actor->target->y);
    if (FLAG(actor->target->flags, MF_SHADOW))
        actor->angle += P_SubRandom() << 5;     /* vanilla << 21 */
}

void A_PosAttack(mobj_t *actor)
{
    angle_t angle;
    int16_t damage;
    fixed_t slope;

    if (!actor->target)
        return;
    A_FaceTarget(actor);
    angle = actor->angle;
    slope = P_AimLineAttack(actor, angle, MISSILERANGE);
    S_StartSound(actor, sfx_pistol);
    angle += P_SubRandom() << 4;                /* vanilla << 20 */
    damage = ((P_Random() % 5) + 1) * 3;
    P_LineAttack(actor, angle, MISSILERANGE, slope, damage);
}

void A_SPosAttack(mobj_t *actor)
{
    uint8_t i;
    angle_t angle, bangle;
    int16_t damage;
    fixed_t slope;

    if (!actor->target)
        return;
    S_StartSound(actor, sfx_shotgn);
    A_FaceTarget(actor);
    bangle = actor->angle;
    slope = P_AimLineAttack(actor, bangle, MISSILERANGE);
    for (i = 0; i < 3; ++i) {
        angle = bangle + (P_SubRandom() << 4);
        damage = ((P_Random() % 5) + 1) * 3;
        P_LineAttack(actor, angle, MISSILERANGE, slope, damage);
    }
}

/* the imp: claw at melee range, else a fireball */
void A_TroopAttack(mobj_t *actor)
{
    int16_t damage;

    if (!actor->target)
        return;
    A_FaceTarget(actor);
    if (P_CheckMeleeRange(actor)) {
        S_StartSound(actor, sfx_claw);
        damage = (P_Random() % 8 + 1) * 3;
        P_DamageMobj(actor->target, actor, actor, damage);
        return;
    }
    P_SpawnMissile(actor, actor->target, MT_TROOPSHOT);
}

/* the demon and the spectre's bite (Doom 1.5 and later: only in range) */
void A_SargAttack(mobj_t *actor)
{
    int16_t damage;

    if (!actor->target)
        return;
    A_FaceTarget(actor);
    if (!P_CheckMeleeRange(actor))
        return;
    damage = ((P_Random() % 10) + 1) * 4;
    P_DamageMobj(actor->target, actor, actor, damage);
}

/* the cacodemon */
void A_HeadAttack(mobj_t *actor)
{
    int16_t damage;

    if (!actor->target)
        return;
    A_FaceTarget(actor);
    if (P_CheckMeleeRange(actor)) {
        damage = (P_Random() % 6 + 1) * 10;
        P_DamageMobj(actor->target, actor, actor, damage);
        return;
    }
    P_SpawnMissile(actor, actor->target, MT_HEADSHOT);
}

/* the baron (no A_FaceTarget: its attack states do that) */
void A_BruisAttack(mobj_t *actor)
{
    int16_t damage;

    if (!actor->target)
        return;
    if (P_CheckMeleeRange(actor)) {
        S_StartSound(actor, sfx_claw);
        damage = (P_Random() % 8 + 1) * 10;
        P_DamageMobj(actor->target, actor, actor, damage);
        return;
    }
    P_SpawnMissile(actor, actor->target, MT_BRUISERSHOT);
}

/* the lost soul flies at the player like a missile */
#define SKULLSPEED  (20 * FRACUNIT)

void A_SkullAttack(mobj_t *actor)
{
    mobj_t *dest;
    uint16_t an;
    fixed_t dist;

    if (!actor->target)
        return;
    dest = actor->target;
    FLAGS_SET(actor->flags, MF_SKULLFLY);
    S_StartSound(actor, mobjinfo[actor->type].attacksound);
    A_FaceTarget(actor);
    an = actor->angle >> ANGLETOFINESHIFT;
    actor->momx = FixedMul(SKULLSPEED, fine_cosine(an));
    actor->momy = FixedMul(SKULLSPEED, fine_sine(an));
    dist = P_AproxDistance(dest->x - actor->x, dest->y - actor->y);
    dist = dist / SKULLSPEED;
    if (dist < 1)
        dist = 1;
    actor->momz = (dest->z + (dest->height >> 1) - actor->z) / dist;
}

void A_Scream(mobj_t *actor)
{
    uint8_t sound;

    switch (mobjinfo[actor->type].deathsound) {
    case 0:
        return;
    case sfx_podth1:
    case sfx_podth2:
    case sfx_podth3:
        sound = sfx_podth1 + P_Random() % 3;
        break;
    case sfx_bgdth1:
    case sfx_bgdth2:
        sound = sfx_bgdth1 + P_Random() % 2;
        break;
    default:
        sound = mobjinfo[actor->type].deathsound;
        break;
    }
    S_StartSound(actor, sound);
}

void A_XScream(mobj_t *actor)
{
    S_StartSound(actor, sfx_slop);
}

void A_Pain(mobj_t *actor)
{
    if (mobjinfo[actor->type].painsound)
        S_StartSound(actor, mobjinfo[actor->type].painsound);
}

/* the actor is on the ground, it can be walked over */
void A_Fall(mobj_t *actor)
{
    FLAGS_CLR(actor->flags, MF_SOLID);
}

void A_Explode(mobj_t *actor)
{
    P_RadiusAttack(actor, actor->target, 128);
}

/* E1M8: when the last baron dies, the floors tagged 666 lower (Ultimate
 * Doom's rule: episode 1, map 8, the baron). */
void A_BossDeath(mobj_t *mo)
{
    mobj_t *mo2;
    sobj_t *s;

    if (gamemap != 8 || mo->type != MT_BRUISER)
        return;
    if (player.health <= 0)
        return;                     /* no one left alive, so do not end game */
    /* scan the remaining things to see if all bosses are dead */
    for (mo2 = mobjs; mo2 < mobjs_end; ++mo2)
        if (mo2->thinker.function == (think_t)P_MobjThinker && mo2 != mo
            && mo2->type == mo->type && mo2->health > 0)
            return;                 /* other boss not dead */
    for (s = statics; s < statics_end; ++s)
        if (!(s->sflags & (SF_FREE | SF_CORPSE)) && s->type == mo->type)
            return;                 /* a dormant one (spawn health) */
    EV_DoFloorTag(666, lowerFloorToLowest);
}

void A_PlayerScream(mobj_t *mo)
{
    S_StartSound(mo, sfx_pldeth);
}

#endif
