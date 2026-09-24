/* Doom for the Appletini -- the weapons (docs/DESIGN.md section 9).
 *
 * Vanilla p_pspr.c and d_items.c for the weapons episode 1 has: fist,
 * chainsaw, pistol, shotgun, chaingun, rocket launcher, plasma rifle (the
 * BFG's slot exists but it is never owned; no super shotgun). The weapon
 * and flash layers are state machines over the same states table as the
 * things (info.c), their actions the A_* weapon actions below; the render
 * packet takes their sprite, frame and sx/sy (g_game.c).
 */
#include "p_local.h"

#ifdef GAME_REAL

#define LOWERSPEED      (FRACUNIT * 6)
#define RAISESPEED      (FRACUNIT * 6)
#define WEAPONBOTTOM    (128 * FRACUNIT)
#define WEAPONTOP       (32 * FRACUNIT)

const weaponinfo_t weaponinfo[NUMWEAPONS] = {
    { am_noammo, S_PUNCHUP, S_PUNCHDOWN, S_PUNCH, S_PUNCH1, S_NULL },
    { am_clip, S_PISTOLUP, S_PISTOLDOWN, S_PISTOL, S_PISTOL1, S_PISTOLFLASH },
    { am_shell, S_SGUNUP, S_SGUNDOWN, S_SGUN, S_SGUN1, S_SGUNFLASH1 },
    { am_clip, S_CHAINUP, S_CHAINDOWN, S_CHAIN, S_CHAIN1, S_CHAINFLASH1 },
    { am_misl, S_MISSILEUP, S_MISSILEDOWN, S_MISSILE, S_MISSILE1, S_MISSILEFLASH1 },
    { am_cell, S_PLASMAUP, S_PLASMADOWN, S_PLASMA, S_PLASMA1, S_PLASMAFLASH1 },
    { am_cell, S_NULL, S_NULL, S_NULL, S_NULL, S_NULL },    /* BFG: not in E1 */
    { am_noammo, S_SAWUP, S_SAWDOWN, S_SAW, S_SAW1, S_NULL },
};

const int16_t maxammo[NUMAMMO] = { 200, 50, 300, 50 };
const int16_t clipammo[NUMAMMO] = { 10, 4, 20, 1 };

/* the functions: on the 6502 they are a_user.s */
#if !defined(__CC65__)

fixed_t bulletslope;

void P_SetPsprite(player_t *p, uint8_t position, uint16_t stnum)
{
    pspdef_t *psp = &p->psprites[position];
    uint8_t ac;

    do {
        if (!stnum) {
            psp->state = S_NULL;
            break;
        }
        psp->state = stnum;
        psp->tics = st_tics[stnum];
        /* (vanilla's misc1/misc2 offsets: no weapon state here has them) */
        ac = st_action[stnum] & 0x7F;
        if (ac) {
            weapon_actions[ac - AC_FIRST_WEAPON](p, psp);
            if (!psp->state)
                break;
        }
        stnum = st_next[psp->state];
    } while (!psp->tics);
}

void P_BringUpWeapon(player_t *p)
{
    uint16_t newstate;

    if (p->pendingweapon == wp_nochange)
        p->pendingweapon = p->readyweapon;
    if (p->pendingweapon == wp_chainsaw)
        S_StartSound(p->mo, sfx_sawup);
    newstate = weaponinfo[p->pendingweapon].upstate;
    p->pendingweapon = wp_nochange;
    p->psprites[ps_weapon].sy = WEAPONBOTTOM;
    P_SetPsprite(p, ps_weapon, newstate);
}

boolean P_CheckAmmo(player_t *p)
{
    uint8_t ammo = weaponinfo[p->readyweapon].ammo;

    if (ammo == am_noammo || p->ammo[ammo] >= 1)
        return true;
    /* out of ammo: pick a weapon to change to, in vanilla's order */
    if (p->weaponowned[wp_plasma] && p->ammo[am_cell])
        p->pendingweapon = wp_plasma;
    else if (p->weaponowned[wp_chaingun] && p->ammo[am_clip])
        p->pendingweapon = wp_chaingun;
    else if (p->weaponowned[wp_shotgun] && p->ammo[am_shell])
        p->pendingweapon = wp_shotgun;
    else if (p->ammo[am_clip])
        p->pendingweapon = wp_pistol;
    else if (p->weaponowned[wp_chainsaw])
        p->pendingweapon = wp_chainsaw;
    else if (p->weaponowned[wp_missile] && p->ammo[am_misl])
        p->pendingweapon = wp_missile;
    else
        p->pendingweapon = wp_fist;
    P_SetPsprite(p, ps_weapon, weaponinfo[p->readyweapon].downstate);
    return false;
}

static void P_FireWeapon(player_t *p)
{
    if (!P_CheckAmmo(p))
        return;
    P_SetMobjState(p->mo, S_PLAY_ATK1);
    P_SetPsprite(p, ps_weapon, weaponinfo[p->readyweapon].atkstate);
    P_NoiseAlert(p->mo, p->mo);
}

void P_DropWeapon(player_t *p)
{
    P_SetPsprite(p, ps_weapon, weaponinfo[p->readyweapon].downstate);
}

void A_WeaponReady(player_t *p, pspdef_t *psp)
{
    uint16_t angle;

    /* the player's own sprite leaves its attack frames */
    if (p->mo->state == S_PLAY_ATK1 || p->mo->state == S_PLAY_ATK2)
        P_SetMobjState(p->mo, S_PLAY);
    if (p->readyweapon == wp_chainsaw && psp->state == S_SAW)
        S_StartSound(p->mo, sfx_sawidl);
    /* put the weapon away if the player changes it or dies */
    if (p->pendingweapon != wp_nochange || !p->health) {
        P_SetPsprite(p, ps_weapon, weaponinfo[p->readyweapon].downstate);
        return;
    }
    /* fire (the rocket launcher and the BFG only on a new press) */
    if (p->cmd.buttons & BT_ATTACK) {
        if (!p->attackdown || (p->readyweapon != wp_missile && p->readyweapon != wp_bfg)) {
            p->attackdown = true;
            P_FireWeapon(p);
            return;
        }
    } else {
        p->attackdown = false;
    }
    /* bob the weapon with the movement */
    angle = (128 * leveltime) & FINEMASK;
    psp->sx = FRACUNIT + FixedMul(p->bob, fine_cosine(angle));
    angle &= FINEANGLES / 2 - 1;
    psp->sy = WEAPONTOP + FixedMul(p->bob, fine_sine(angle));
}

void A_ReFire(player_t *p, pspdef_t *psp)
{
    (void)psp;
    if ((p->cmd.buttons & BT_ATTACK) && p->pendingweapon == wp_nochange && p->health) {
        p->refire++;
        P_FireWeapon(p);
    } else {
        p->refire = 0;
        P_CheckAmmo(p);
    }
}

void A_Lower(player_t *p, pspdef_t *psp)
{
    psp->sy += LOWERSPEED;
    if (psp->sy < WEAPONBOTTOM)
        return;
    if (p->playerstate == PST_DEAD) {
        psp->sy = WEAPONBOTTOM;
        return;                     /* the weapon stays down */
    }
    if (!p->health) {
        P_SetPsprite(p, ps_weapon, S_NULL);
        return;
    }
    p->readyweapon = p->pendingweapon;
    P_BringUpWeapon(p);
}

void A_Raise(player_t *p, pspdef_t *psp)
{
    psp->sy -= RAISESPEED;
    if (psp->sy > WEAPONTOP)
        return;
    psp->sy = WEAPONTOP;
    P_SetPsprite(p, ps_weapon, weaponinfo[p->readyweapon].readystate);
}

void A_GunFlash(player_t *p, pspdef_t *psp)
{
    (void)psp;
    P_SetMobjState(p->mo, S_PLAY_ATK2);
    P_SetPsprite(p, ps_flash, weaponinfo[p->readyweapon].flashstate);
}

void A_Punch(player_t *p, pspdef_t *psp)
{
    angle_t angle;
    int16_t damage;
    fixed_t slope;

    (void)psp;
    damage = (P_Random() % 10 + 1) << 1;
    if (p->powers[pw_strength])
        damage *= 10;
    angle = p->mo->angle;
    angle += P_SubRandom() << 2;    /* vanilla << 18 */
    slope = P_AimLineAttack(p->mo, angle, MELEERANGE);
    P_LineAttack(p->mo, angle, MELEERANGE, slope, damage);
    if (linetarget) {
        S_StartSound(p->mo, sfx_punch);
        p->mo->angle = R_PointToAngle2(p->mo->x, p->mo->y, linetarget->x, linetarget->y);
    }
}

void A_Saw(player_t *p, pspdef_t *psp)
{
    angle_t angle;
    int16_t damage;
    fixed_t slope;

    (void)psp;
    damage = 2 * (P_Random() % 10 + 1);
    angle = p->mo->angle;
    angle += P_SubRandom() << 2;
    /* use meleerange + 1 so the puff doesn't skip the flash */
    slope = P_AimLineAttack(p->mo, angle, MELEERANGE + 1);
    P_LineAttack(p->mo, angle, MELEERANGE + 1, slope, damage);
    if (!linetarget) {
        S_StartSound(p->mo, sfx_sawful);
        return;
    }
    S_StartSound(p->mo, sfx_sawhit);
    /* turn to face the target */
    angle = R_PointToAngle2(p->mo->x, p->mo->y, linetarget->x, linetarget->y);
    if ((angle_t)(angle - p->mo->angle) > ANG180) {
        if ((int16_t)(angle - p->mo->angle) < -(int16_t)(ANG90 / 20))
            p->mo->angle = angle + ANG90 / 21;
        else
            p->mo->angle -= ANG90 / 20;
    } else {
        if ((angle_t)(angle - p->mo->angle) > ANG90 / 20)
            p->mo->angle = angle - ANG90 / 21;
        else
            p->mo->angle += ANG90 / 20;
    }
    FLAGS_SET(p->mo->flags, MF_JUSTATTACKED);
}

static void decrease_ammo(player_t *p, uint8_t amount)
{
    p->ammo[weaponinfo[p->readyweapon].ammo] -= amount;
}

void A_FireMissile(player_t *p, pspdef_t *psp)
{
    (void)psp;
    decrease_ammo(p, 1);
    P_SpawnPlayerMissile(p->mo, MT_ROCKET);
}

void A_FirePlasma(player_t *p, pspdef_t *psp)
{
    (void)psp;
    decrease_ammo(p, 1);
    P_SetPsprite(p, ps_flash, weaponinfo[p->readyweapon].flashstate + (P_Random() & 1));
    P_SpawnPlayerMissile(p->mo, MT_PLASMA);
}

/* sets a slope so a near miss is at approximately the height of the
 * intended target */
static void P_BulletSlope(mobj_t *mo)
{
    angle_t an = mo->angle;

    bulletslope = P_AimLineAttack(mo, an, 16 * 64 * FRACUNIT);
    if (!linetarget) {
        an += 1 << 10;              /* vanilla 1 << 26 */
        bulletslope = P_AimLineAttack(mo, an, 16 * 64 * FRACUNIT);
        if (!linetarget) {
            an -= 2 << 10;
            bulletslope = P_AimLineAttack(mo, an, 16 * 64 * FRACUNIT);
        }
    }
}

static void P_GunShot(mobj_t *mo, boolean accurate)
{
    angle_t angle;
    int16_t damage;

    damage = 5 * (P_Random() % 3 + 1);
    angle = mo->angle;
    if (!accurate)
        angle += P_SubRandom() << 2;    /* vanilla << 18 */
    P_LineAttack(mo, angle, MISSILERANGE, bulletslope, damage);
}

void A_FirePistol(player_t *p, pspdef_t *psp)
{
    (void)psp;
    S_StartSound(p->mo, sfx_pistol);
    P_SetMobjState(p->mo, S_PLAY_ATK2);
    decrease_ammo(p, 1);
    P_SetPsprite(p, ps_flash, weaponinfo[p->readyweapon].flashstate);
    P_BulletSlope(p->mo);
    P_GunShot(p->mo, !p->refire);
}

void A_FireShotgun(player_t *p, pspdef_t *psp)
{
    uint8_t i;

    (void)psp;
    S_StartSound(p->mo, sfx_shotgn);
    P_SetMobjState(p->mo, S_PLAY_ATK2);
    decrease_ammo(p, 1);
    P_SetPsprite(p, ps_flash, weaponinfo[p->readyweapon].flashstate);
    P_BulletSlope(p->mo);
    for (i = 0; i < 7; ++i)
        P_GunShot(p->mo, false);
}

void A_FireCGun(player_t *p, pspdef_t *psp)
{
    S_StartSound(p->mo, sfx_pistol);
    if (!p->ammo[weaponinfo[p->readyweapon].ammo])
        return;
    P_SetMobjState(p->mo, S_PLAY_ATK2);
    decrease_ammo(p, 1);
    P_SetPsprite(p, ps_flash, weaponinfo[p->readyweapon].flashstate + psp->state - S_CHAIN1);
    P_BulletSlope(p->mo);
    P_GunShot(p->mo, !p->refire);
}

void A_Light0(player_t *p, pspdef_t *psp) { (void)psp; p->extralight = 0; }
void A_Light1(player_t *p, pspdef_t *psp) { (void)psp; p->extralight = 1; }
void A_Light2(player_t *p, pspdef_t *psp) { (void)psp; p->extralight = 2; }

void P_SetupPsprites(player_t *p)
{
    uint8_t i;
    for (i = 0; i < NUMPSPRITES; ++i)
        p->psprites[i].state = S_NULL;
    p->pendingweapon = p->readyweapon;
    P_BringUpWeapon(p);
}

void P_MovePsprites(player_t *p)
{
    uint8_t i;
    pspdef_t *psp = &p->psprites[0];

    for (i = 0; i < NUMPSPRITES; ++i, ++psp) {
        if (psp->state && psp->tics != ST_FOREVER) {
            if (!--psp->tics)
                P_SetPsprite(p, i, st_next[psp->state]);
        }
    }
    p->psprites[ps_flash].sx = p->psprites[ps_weapon].sx;
    p->psprites[ps_flash].sy = p->psprites[ps_weapon].sy;
}

#endif

#endif
