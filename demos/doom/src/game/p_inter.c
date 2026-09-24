/* Doom for the Appletini -- damage, death and pickups (docs/DESIGN.md
 * section 9).
 *
 * Vanilla p_inter.c (Doom 1.9, one player, not a net game): P_DamageMobj
 * with the thrust, the player's armour, the pain chance, waking and
 * retaliation (infighting included: a monster hurt by another turns on
 * it); P_KillMobj with the kill count and the dropped clip or shotgun;
 * P_TouchSpecialThing for every pickup of episode 1 (identified by its
 * sprite, as vanilla does) with vanilla's limits (health 100 from medikits,
 * 200 from bonuses and the soul sphere, armour 100/200, ammo up to the
 * maximum, doubled by the backpack, and double ammo on "I'm too young to
 * die" and nightmare).
 *
 * The core's rules: P_DamageMobj and P_KillMobj get actors only (a static
 * is woken before it can be hurt); P_TouchSpecialThing may get a static's
 * view (P_StaticView), which it reads and removes with P_RemoveMobj.
 * player.message is a number (MSG_*): the HUD will have the strings.
 * Vanilla's int arithmetic where it wraps is kept: the thrust of a
 * telefrag (damage 10,000) overflows 32 bits as vanilla's did.
 *
 * On the 6502 this is a_inter.s.
 */
#include "p_local.h"

#if defined(GAME_REAL) && !defined(__CC65__)

#define BONUSADD        6

/* --- getting stuff ------------------------------------------------------------ */
/* num is the number of clip loads, not the individual count (0 = half a
 * clip); false if the ammo can't be picked up at all */
static boolean P_GiveAmmo(player_t *p, uint8_t ammo, uint8_t num)
{
    int16_t oldammo, n;

    if (ammo == am_noammo)
        return false;
    if (p->ammo[ammo] == p->maxammo[ammo])
        return false;
    if (num)
        n = num * clipammo[ammo];
    else
        n = clipammo[ammo] / 2;
    if (gameskill == sk_baby || gameskill == sk_nightmare)
        n <<= 1;                    /* double ammo in trainer mode and nightmare */
    oldammo = p->ammo[ammo];
    p->ammo[ammo] += n;
    if (p->ammo[ammo] > p->maxammo[ammo])
        p->ammo[ammo] = p->maxammo[ammo];
    /* if non zero ammo, don't change up weapons: the player was lower on
     * purpose */
    if (oldammo)
        return true;
    /* we were down to zero, so select a new weapon (not user selectable) */
    switch (ammo) {
    case am_clip:
        if (p->readyweapon == wp_fist)
            p->pendingweapon = p->weaponowned[wp_chaingun] ? wp_chaingun : wp_pistol;
        break;
    case am_shell:
        if ((p->readyweapon == wp_fist || p->readyweapon == wp_pistol)
            && p->weaponowned[wp_shotgun])
            p->pendingweapon = wp_shotgun;
        break;
    case am_cell:
        if ((p->readyweapon == wp_fist || p->readyweapon == wp_pistol)
            && p->weaponowned[wp_plasma])
            p->pendingweapon = wp_plasma;
        break;
    case am_misl:
        if (p->readyweapon == wp_fist && p->weaponowned[wp_missile])
            p->pendingweapon = wp_missile;
        break;
    }
    return true;
}

/* a dropped weapon gives one clip, a placed one two */
static boolean P_GiveWeapon(player_t *p, uint8_t weapon, boolean dropped)
{
    boolean gaveammo, gaveweapon;
    uint8_t ammo = weaponinfo[weapon].ammo;

    if (ammo != am_noammo)
        gaveammo = P_GiveAmmo(p, ammo, dropped ? 1 : 2);
    else
        gaveammo = false;
    if (p->weaponowned[weapon]) {
        gaveweapon = false;
    } else {
        gaveweapon = true;
        p->weaponowned[weapon] = true;
        p->pendingweapon = weapon;
    }
    return gaveweapon || gaveammo;
}

/* false if the body isn't needed at all */
static boolean P_GiveBody(player_t *p, int16_t num)
{
    if (p->health >= MAXHEALTH)
        return false;
    p->health += num;
    if (p->health > MAXHEALTH)
        p->health = MAXHEALTH;
    p->mo->health = p->health;
    return true;
}

/* false if the armour is worse than the current armour */
static boolean P_GiveArmor(player_t *p, uint8_t armortype)
{
    int16_t hits = armortype * 100;

    if (p->armorpoints >= hits)
        return false;               /* don't pick up */
    p->armortype = armortype;
    p->armorpoints = hits;
    return true;
}

static void P_GiveCard(player_t *p, uint8_t card)
{
    if (p->cards[card])
        return;
    p->bonuscount = BONUSADD;
    p->cards[card] = 1;
}

static boolean P_GivePower(player_t *p, uint8_t power)
{
    switch (power) {
    case pw_invulnerability:
        p->powers[power] = INVULNTICS;
        return true;
    case pw_invisibility:
        p->powers[power] = INVISTICS;
        FLAGS_SET(p->mo->flags, MF_SHADOW);
        return true;
    case pw_infrared:
        p->powers[power] = INFRATICS;
        return true;
    case pw_ironfeet:
        p->powers[power] = IRONTICS;
        return true;
    case pw_strength:
        P_GiveBody(p, 100);
        p->powers[power] = 1;
        return true;
    }
    if (p->powers[power])
        return false;               /* already got it */
    p->powers[power] = 1;
    return true;
}

/* A card: the message only if new; always picked up (not a net game). */
static void give_card(player_t *p, uint8_t card, uint8_t msg)
{
    if (!p->cards[card])
        p->message = msg;
    P_GiveCard(p, card);
}

void P_TouchSpecialThing(mobj_t *special, mobj_t *toucher)
{
    player_t *p = &player;
    fixed_t delta;
    uint8_t sound = sfx_itemup, i;
    boolean dropped = FLAG(special->flags, MF_DROPPED) != 0;

    delta = special->z - toucher->z;
    if (delta > toucher->height || delta < -8 * FRACUNIT)
        return;                     /* out of reach */
    /* dead thing touching (can happen with a sliding player corpse) */
    if (toucher->health <= 0)
        return;
    switch (st_sprite[special->state]) {
    /* armour */
    case SPR_ARM1:
        if (!P_GiveArmor(p, 1))
            return;
        p->message = MSG_GOTARMOR;
        break;
    case SPR_ARM2:
        if (!P_GiveArmor(p, 2))
            return;
        p->message = MSG_GOTMEGA;
        break;
    /* bonus items */
    case SPR_BON1:
        p->health++;                /* can go over 100% */
        if (p->health > 200)
            p->health = 200;
        p->mo->health = p->health;
        p->message = MSG_GOTHTHBONUS;
        break;
    case SPR_BON2:
        p->armorpoints++;           /* can go over 100% */
        if (p->armorpoints > 200)
            p->armorpoints = 200;
        if (!p->armortype)
            p->armortype = 1;
        p->message = MSG_GOTARMBONUS;
        break;
    case SPR_SOUL:
        p->health += 100;
        if (p->health > 200)
            p->health = 200;
        p->mo->health = p->health;
        p->message = MSG_GOTSUPER;
        sound = sfx_getpow;
        break;
    /* cards */
    case SPR_BKEY: give_card(p, it_bluecard, MSG_GOTBLUECARD); break;
    case SPR_YKEY: give_card(p, it_yellowcard, MSG_GOTYELWCARD); break;
    case SPR_RKEY: give_card(p, it_redcard, MSG_GOTREDCARD); break;
    case SPR_BSKU: give_card(p, it_blueskull, MSG_GOTBLUESKUL); break;
    case SPR_YSKU: give_card(p, it_yellowskull, MSG_GOTYELWSKUL); break;
    case SPR_RSKU: give_card(p, it_redskull, MSG_GOTREDSKULL); break;
    /* medikits, heals */
    case SPR_STIM:
        if (!P_GiveBody(p, 10))
            return;
        p->message = MSG_GOTSTIM;
        break;
    case SPR_MEDI:
        if (!P_GiveBody(p, 25))
            return;
        /* (vanilla tests the health after the heal: "needed" never shows) */
        p->message = p->health < 25 ? MSG_GOTMEDINEED : MSG_GOTMEDIKIT;
        break;
    /* power ups */
    case SPR_PINV:
        if (!P_GivePower(p, pw_invulnerability))
            return;
        p->message = MSG_GOTINVUL;
        sound = sfx_getpow;
        break;
    case SPR_PSTR:
        if (!P_GivePower(p, pw_strength))
            return;
        p->message = MSG_GOTBERSERK;
        if (p->readyweapon != wp_fist)
            p->pendingweapon = wp_fist;
        sound = sfx_getpow;
        break;
    case SPR_PINS:
        if (!P_GivePower(p, pw_invisibility))
            return;
        p->message = MSG_GOTINVIS;
        sound = sfx_getpow;
        break;
    case SPR_SUIT:
        if (!P_GivePower(p, pw_ironfeet))
            return;
        p->message = MSG_GOTSUIT;
        sound = sfx_getpow;
        break;
    case SPR_PMAP:
        if (!P_GivePower(p, pw_allmap))
            return;
        p->message = MSG_GOTMAP;
        sound = sfx_getpow;
        break;
    case SPR_PVIS:
        if (!P_GivePower(p, pw_infrared))
            return;
        p->message = MSG_GOTVISOR;
        sound = sfx_getpow;
        break;
    /* ammo */
    case SPR_CLIP:
        if (!P_GiveAmmo(p, am_clip, dropped ? 0 : 1))
            return;
        p->message = MSG_GOTCLIP;
        break;
    case SPR_AMMO:
        if (!P_GiveAmmo(p, am_clip, 5))
            return;
        p->message = MSG_GOTCLIPBOX;
        break;
    case SPR_ROCK:
        if (!P_GiveAmmo(p, am_misl, 1))
            return;
        p->message = MSG_GOTROCKET;
        break;
    case SPR_BROK:
        if (!P_GiveAmmo(p, am_misl, 5))
            return;
        p->message = MSG_GOTROCKBOX;
        break;
    case SPR_CELL:
        if (!P_GiveAmmo(p, am_cell, 1))
            return;
        p->message = MSG_GOTCELL;
        break;
    case SPR_CELP:
        if (!P_GiveAmmo(p, am_cell, 5))
            return;
        p->message = MSG_GOTCELLBOX;
        break;
    case SPR_SHEL:
        if (!P_GiveAmmo(p, am_shell, 1))
            return;
        p->message = MSG_GOTSHELLS;
        break;
    case SPR_SBOX:
        if (!P_GiveAmmo(p, am_shell, 5))
            return;
        p->message = MSG_GOTSHELLBOX;
        break;
    case SPR_BPAK:
        if (!p->backpack) {
            for (i = 0; i < NUMAMMO; ++i)
                p->maxammo[i] *= 2;
            p->backpack = true;
        }
        for (i = 0; i < NUMAMMO; ++i)
            P_GiveAmmo(p, i, 1);
        p->message = MSG_GOTBACKPACK;
        break;
    /* weapons */
    case SPR_MGUN:
        if (!P_GiveWeapon(p, wp_chaingun, dropped))
            return;
        p->message = MSG_GOTCHAINGUN;
        sound = sfx_wpnup;
        break;
    case SPR_CSAW:
        if (!P_GiveWeapon(p, wp_chainsaw, false))
            return;
        p->message = MSG_GOTCHAINSAW;
        sound = sfx_wpnup;
        break;
    case SPR_LAUN:
        if (!P_GiveWeapon(p, wp_missile, false))
            return;
        p->message = MSG_GOTLAUNCHER;
        sound = sfx_wpnup;
        break;
    case SPR_PLAS:
        if (!P_GiveWeapon(p, wp_plasma, false))
            return;
        p->message = MSG_GOTPLASMA;
        sound = sfx_wpnup;
        break;
    case SPR_SHOT:
        if (!P_GiveWeapon(p, wp_shotgun, dropped))
            return;
        p->message = MSG_GOTSHOTGUN;
        sound = sfx_wpnup;
        break;
    default:
        return;                     /* vanilla: I_Error (nothing else is gettable in E1) */
    }
    if (FLAG(special->flags, MF_COUNTITEM))
        p->itemcount++;
    P_RemoveMobj(special);
    p->bonuscount += BONUSADD;
    S_StartSound(0, sound);
}

/* --- dying ------------------------------------------------------------------------- */
void P_KillMobj(mobj_t *source, mobj_t *target)
{
    player_t *tp = MO_PLAYER(target);
    uint8_t item;
    mobj_t *mo;
    const mobjinfo_t *info = &mobjinfo[target->type];

    (void)source;
    target->flags &= ~(MF_SHOOTABLE | MF_FLOAT | MF_SKULLFLY);
    if (target->type != MT_SKULL)
        FLAGS_CLR(target->flags, MF_NOGRAVITY);
    target->flags |= MF_CORPSE | MF_DROPOFF;
    target->height >>= 2;
    /* count all monster deaths, even those caused by other monsters */
    if (FLAG(target->flags, MF_COUNTKILL))
        player.killcount++;
    if (tp) {
        FLAGS_CLR(target->flags, MF_SOLID);
        tp->playerstate = PST_DEAD;
        P_DropWeapon(tp);
    }
    if (target->health < -info->spawnhealth && info->xdeathstate)
        P_SetMobjState(target, info->xdeathstate);
    else
        P_SetMobjState(target, info->deathstate);
    target->tics -= P_Random() & 3;
    if ((int8_t)target->tics < 1)
        target->tics = 1;
    /* drop stuff: the kind of object spawned during the death frame */
    switch (target->type) {
    case MT_POSSESSED:
        item = MT_CLIP;
        break;
    case MT_SHOTGUY:
        item = MT_SHOTGUN;
        break;
    default:
        return;
    }
    mo = P_SpawnMobj(target->x, target->y, ONFLOORZ, item);
    FLAGS_SET(mo->flags, MF_DROPPED);   /* special versions of items */
}

/* --- damage ---------------------------------------------------------------------------- */
/* Damages both enemies and players. inflictor is the thing that caused
 * the damage (a creature or a missile; NULL for crushers and slime),
 * source the thing to target after taking damage (a creature, or NULL
 * for barrels and the environment). */
void P_DamageMobj(mobj_t *target, mobj_t *inflictor, mobj_t *source, int16_t damage)
{
    angle_t ang;
    int16_t saved, dc;
    player_t *p;
    fixed_t thrust;
    const mobjinfo_t *info = &mobjinfo[target->type];

    if (!FLAG(target->flags, MF_SHOOTABLE))
        return;                     /* shouldn't happen... */
    if (target->health <= 0)
        return;
    if (FLAG(target->flags, MF_SKULLFLY))
        target->momx = target->momy = target->momz = 0;
    p = MO_PLAYER(target);
    if (p && gameskill == sk_baby)
        damage >>= 1;               /* take half damage in trainer mode */
    /* some close combat weapons should not inflict thrust and push the
     * victim out of reach, thus kick away unless using the chainsaw */
    if (inflictor && !FLAG(target->flags, MF_NOCLIP)
        && (!source || !IS_PLAYER(source) || player.readyweapon != wp_chainsaw)) {
        ang = R_PointToAngle2(inflictor->x, inflictor->y, target->x, target->y);
        /* damage * (FRACUNIT >> 3) * 100 / mass in vanilla's int */
        thrust = (int32_t)((uint32_t)(int32_t)damage * (uint32_t)(8192 * 100)) / info->mass;
        /* make fall forwards sometimes */
        if (damage < 40 && damage > target->health
            && target->z - inflictor->z > 64 * FRACUNIT && (P_Random() & 1)) {
            ang += ANG180;
            thrust *= 4;
        }
        ang >>= ANGLETOFINESHIFT;
        target->momx += FixedMul(thrust, fine_cosine(ang));
        target->momy += FixedMul(thrust, fine_sine(ang));
    }
    /* player specific */
    if (p) {
        /* end of game hell hack */
        if (sec_special[target->sector] == 11 && damage >= target->health)
            damage = target->health - 1;
        /* below certain threshold, ignore damage in god mode, or with the
         * invulnerability power */
        if (damage < 1000 && ((p->cheats & CF_GODMODE) || p->powers[pw_invulnerability]))
            return;
        if (p->armortype) {
            saved = p->armortype == 1 ? damage / 3 : damage / 2;
            if (p->armorpoints <= saved) {
                /* armour is used up */
                saved = p->armorpoints;
                p->armortype = 0;
            }
            p->armorpoints -= saved;
            damage -= saved;
        }
        p->health -= damage;        /* mirror mobj health here for Dave */
        if (p->health < 0)
            p->health = 0;
        p->attacker = source;
        dc = p->damagecount + damage;   /* add damage after armour / invulnerability */
        p->damagecount = dc > 100 ? 100 : (uint8_t)dc;  /* a teleport stomp does 10k points */
    }
    /* do the damage */
    target->health -= damage;
    if (target->health <= 0) {
        P_KillMobj(source, target);
        return;
    }
    if (P_Random() < info->painchance && !FLAG(target->flags, MF_SKULLFLY)) {
        FLAGS_SET(target->flags, MF_JUSTHIT);   /* fight back! */
        P_SetMobjState(target, info->painstate);
    }
    target->reactiontime = 0;       /* we're awake now... */
    if (!target->threshold && source && source != target) {
        /* if not intent on another player, chase after this one */
        target->target = source;
        target->threshold = BASETHRESHOLD;
        if (target->state == info->spawnstate && info->seestate != S_NULL)
            P_SetMobjState(target, info->seestate);
    }
}

#endif
