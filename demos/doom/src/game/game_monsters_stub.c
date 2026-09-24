/* Doom for the Appletini -- stand-ins for the MONSTERS part (docs/DESIGN.md
 * section 9): vanilla p_enemy.c, p_inter.c and p_sight.c will replace
 * this file, with these signatures (p_local.h, info.h).
 *
 * Until then the core needs something to call: things take damage and
 * die (vanilla's P_DamageMobj/P_KillMobj without the thrust, pain,
 * retaliation and drops), a pickup is removed, sight is REJECT alone,
 * and the monster actions do nothing but what a death needs (A_Fall,
 * A_Explode). Monsters stand still.
 *
 * Interface notes for the real part (the core relies on them):
 *  - P_DamageMobj/P_KillMobj receive actors, never statics: the core
 *    wakes a static (P_WakeStatic) before it can be hurt.
 *  - P_TouchSpecialThing may receive a static's view (P_StaticView):
 *    read its fields, and remove it with P_RemoveMobj(special) (which
 *    removes the static); do not keep the pointer.
 *  - vanilla's mobj->player is MO_PLAYER(mo); mobj->info is
 *    &mobjinfo[mo->type]; mobj->subsector->sector is mo->sector;
 *    sector->soundtarget is sec_soundtarget[sector]; the REJECT test is
 *    P_RejectVisible; floorz/ceilingz are map units (FIX() them).
 *  - P_MonstersSetupLevel runs at level start after the things are
 *    spawned: allocate per-level arrays there (P_ArenaAlloc).
 *  - A_Look on a dormant monster runs only when it can succeed (p_mobj.c):
 *    it must keep vanilla's behaviour of doing nothing otherwise.
 */
#include "p_local.h"

#ifdef GAME_REAL

void P_DamageMobj(mobj_t *target, mobj_t *inflictor, mobj_t *source, int16_t damage)
{
    player_t *pl;

    (void)inflictor;
    if (!FLAG(target->flags, MF_SHOOTABLE))
        return;
    if (target->health <= 0)
        return;
    if (FLAG(target->flags, MF_SKULLFLY))
        target->momx = target->momy = target->momz = 0;
    pl = MO_PLAYER(target);
    if (pl) {
        if (gameskill == sk_baby)
            damage >>= 1;
        if ((pl->cheats & CF_GODMODE) || pl->powers[pw_invulnerability])
            return;
        pl->health -= damage;
        if (pl->health < 0)
            pl->health = 0;
        pl->attacker = source;
        pl->damagecount += damage > 100 ? 100 : (uint8_t)damage;
        if (pl->damagecount > 100)
            pl->damagecount = 100;
    }
    target->health -= damage;
    if (target->health <= 0)
        P_KillMobj(source, target);
}

void P_KillMobj(mobj_t *source, mobj_t *target)
{
    player_t *pl = MO_PLAYER(target);

    (void)source;
    target->flags &= ~(MF_SHOOTABLE | MF_FLOAT | MF_SKULLFLY);
    if (target->type != MT_SKULL)
        FLAGS_CLR(target->flags, MF_NOGRAVITY);
    target->flags |= MF_CORPSE | MF_DROPOFF;
    target->height >>= 2;
    if (FLAG(target->flags, MF_COUNTKILL))
        ++player.killcount;
    if (pl) {
        FLAGS_CLR(target->flags, MF_SOLID);
        pl->playerstate = PST_DEAD;
        P_DropWeapon(pl);
    }
    if (target->health < -mobjinfo[target->type].spawnhealth
        && mobjinfo[target->type].xdeathstate)
        P_SetMobjState(target, mobjinfo[target->type].xdeathstate);
    else
        P_SetMobjState(target, mobjinfo[target->type].deathstate);
    target->tics -= P_Random() & 3;
    if ((int8_t)target->tics < 1)
        target->tics = 1;
}

void P_TouchSpecialThing(mobj_t *special, mobj_t *toucher)
{
    fixed_t delta = special->z - toucher->z;

    if (delta > toucher->height || delta < -8 * FRACUNIT)
        return;                     /* out of reach */
    if (toucher->health <= 0)
        return;
    if (FLAG(special->flags, MF_COUNTITEM))
        ++player.itemcount;
    P_RemoveMobj(special);
    player.bonuscount += 6;
    S_StartSound(toucher, sfx_itemup);
}

boolean P_CheckSight(mobj_t *t1, mobj_t *t2)
{
    return P_RejectVisible(t1->sector, t2->sector);
}

void P_NoiseAlert(mobj_t *target, mobj_t *emitter)
{
    (void)target;
    (void)emitter;
}

void P_MonstersSetupLevel(void)
{
}

void A_Look(mobj_t *actor) { (void)actor; }
void A_Chase(mobj_t *actor) { (void)actor; }
void A_FaceTarget(mobj_t *actor) { (void)actor; }
void A_PosAttack(mobj_t *actor) { (void)actor; }
void A_SPosAttack(mobj_t *actor) { (void)actor; }
void A_TroopAttack(mobj_t *actor) { (void)actor; }
void A_SargAttack(mobj_t *actor) { (void)actor; }
void A_HeadAttack(mobj_t *actor) { (void)actor; }
void A_BruisAttack(mobj_t *actor) { (void)actor; }
void A_SkullAttack(mobj_t *actor) { (void)actor; }
void A_Scream(mobj_t *actor) { (void)actor; }
void A_XScream(mobj_t *actor) { (void)actor; }
void A_Pain(mobj_t *actor) { (void)actor; }
void A_Fall(mobj_t *actor) { FLAGS_CLR(actor->flags, MF_SOLID); }
void A_Explode(mobj_t *actor) { P_RadiusAttack(actor, actor->target, 128); }
void A_BossDeath(mobj_t *actor) { (void)actor; }
void A_PlayerScream(mobj_t *actor) { (void)actor; }

#endif
