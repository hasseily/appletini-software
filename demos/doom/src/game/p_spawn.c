/* Doom for the Appletini -- the level-start spawner and the missile
 * spawners (docs/DESIGN.md section 9).
 *
 * The parts of vanilla p_mobj.c that run at level start or once per shot
 * rather than every tic, kept in C on both targets (on the 6502 the rest
 * of p_mobj.c is a_mobj.s): P_SpawnMapThing (every thing a map places
 * becomes a static, p_mobj.c's header says why), P_SpawnPlayer,
 * P_FindTeleportDest, P_SpawnMissile, P_SpawnPlayerMissile.
 */
#include "p_local.h"

#ifdef GAME_REAL

void P_SpawnPlayer(void)
{
    extern int16_t playerstart[3];
    player_t *p = &player;
    mobj_t *mobj;

    if (p->playerstate == PST_REBORN)
        G_PlayerReborn();
    mobj = P_SpawnMobj(FIX(playerstart[0]), FIX(playerstart[1]), ONFLOORZ, MT_PLAYER);
    mobj->angle = ANG45 * (playerstart[2] / 45);
    mobj->health = p->health;
    p->mo = mobj;
    p->playerstate = PST_LIVE;
    p->refire = 0;
    p->message = 0;
    p->damagecount = 0;
    p->bonuscount = 0;
    p->extralight = 0;
    p->fixedcolormap = 0;
    p->viewheight = VIEWHEIGHT;
    P_SetupPsprites(p);
}

int16_t playerstart[3];

void P_SpawnMapThing(int16_t x, int16_t y, int16_t angle, uint16_t type, uint16_t options)
{
    uint8_t t, bit;
    sobj_t *s;
    const mobjinfo_t *info;

    if (type == 11)
        return;
    if (type <= 4) {
        if (type == 1) {
            playerstart[0] = x;
            playerstart[1] = y;
            playerstart[2] = angle;
            P_SpawnPlayer();
        }
        return;
    }
    if (options & 16)
        return;
    bit = gameskill == sk_baby ? 1 : gameskill == sk_nightmare ? 4 : 1 << (gameskill - 1);
    if (!(options & bit))
        return;
    t = P_ThingType(type);
    if (t == 0xFF)
        return;                     /* vanilla stops with an error */
    info = &mobjinfo[t];
    s = P_AllocStatic();
    if (!s)
        kernel_crash(CRASH_MOBJS);
    P_Random();                     /* P_SpawnMobj's lastlook */
    s->type = t;
    s->x = x;
    s->y = y;
    s->state = info->spawnstate;
    s->tics = st_tics[s->state];
    if (s->tics != ST_FOREVER && s->tics > 0)
        s->tics = 1 + P_Random() % s->tics;
    s->sector = R_PointInSector(FIX(x), FIX(y));
    if (FLAG(info->flags, MF_SPAWNCEILING))
        s->z = sec_ceilh[s->sector] - info->height;
    else
        s->z = sec_floorh[s->sector];
    s->angle = (uint8_t)((ANG45 * (uint16_t)(angle / 45)) >> 8);
    s->bnext = 0;
    if (options & 8)
        s->sflags |= SF_AMBUSH;
    if (FLAG(info->flags, MF_COUNTKILL) || t == MT_SKULL)
        s->sflags |= SF_DORMANT;
    if (FLAG(info->flags, MF_COUNTKILL))
        ++totalkills;
    if (FLAG(info->flags, MF_COUNTITEM))
        ++totalitems;
    if (FLAG(info->flags, MF_NOBLOCKMAP))
        s->sflags |= SF_NOBLOCK;
    else
        P_LinkStatic(s);
}

mobj_t *P_FindTeleportDest(uint16_t sector)
{
    sobj_t *s;
    mobj_t *mo;

    for (s = statics; s < statics_end; ++s)
        if (!(s->sflags & SF_FREE) && s->type == MT_TELEPORTMAN && s->sector == sector)
            return P_StaticView(s);
    for (mo = mobjs; mo < mobjs_end; ++mo)
        if (mo->thinker.function == (think_t)P_MobjThinker && mo->type == MT_TELEPORTMAN
            && mo->sector == sector)
            return mo;
    return 0;
}

mobj_t *P_SpawnMissile(mobj_t *source, mobj_t *dest, uint8_t type)
{
    mobj_t *th;
    angle_t an;
    fixed_t dist, speed;

    th = P_SpawnMobj(source->x, source->y, source->z + 4 * 8 * FRACUNIT, type);
    if (mobjinfo[type].seesound)
        S_StartSound(th, mobjinfo[type].seesound);
    th->target = source;
    an = R_PointToAngle2(source->x, source->y, dest->x, dest->y);
    if (FLAG(dest->flags, MF_SHADOW))
        an += P_SubRandom() << 4;   /* vanilla << 20 on 32-bit angles */
    th->angle = an;
    an >>= ANGLETOFINESHIFT;
    speed = FIX(mobjinfo[type].speed);
    th->momx = FixedMul(speed, fine_cosine(an));
    th->momy = FixedMul(speed, fine_sine(an));
    dist = P_AproxDistance(dest->x - source->x, dest->y - source->y);
    dist = dist / speed;
    if (dist < 1)
        dist = 1;
    th->momz = (dest->z - source->z) / dist;
    P_CheckMissileSpawn(th);
    return th;
}

void P_SpawnPlayerMissile(mobj_t *source, uint8_t type)
{
    mobj_t *th;
    angle_t an;
    fixed_t slope, speed;

    an = source->angle;
    slope = P_AimLineAttack(source, an, 16 * 64 * FRACUNIT);
    if (!linetarget) {
        an += 1 << 10;              /* vanilla 1 << 26 */
        slope = P_AimLineAttack(source, an, 16 * 64 * FRACUNIT);
        if (!linetarget) {
            an -= 2 << 10;
            slope = P_AimLineAttack(source, an, 16 * 64 * FRACUNIT);
        }
        if (!linetarget) {
            an = source->angle;
            slope = 0;
        }
    }
    th = P_SpawnMobj(source->x, source->y, source->z + 4 * 8 * FRACUNIT, type);
    if (mobjinfo[type].seesound)
        S_StartSound(th, mobjinfo[type].seesound);
    th->target = source;
    th->angle = an;
    speed = FIX(mobjinfo[type].speed);
    th->momx = FixedMul(speed, fine_cosine(an >> ANGLETOFINESHIFT));
    th->momy = FixedMul(speed, fine_sine(an >> ANGLETOFINESHIFT));
    th->momz = FixedMul(speed, slope);
    P_CheckMissileSpawn(th);
}

#endif
