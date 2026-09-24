/* Doom for the Appletini -- the player's tic (docs/DESIGN.md sections 9, 10).
 *
 * Vanilla p_user.c: thrust from the tic command, view height and bob,
 * death view, use, weapon change, powers. The tic command is built from
 * the kernel's input block by G_BuildTiccmd (g_game.c). One player.
 */
#include "p_local.h"

#ifdef GAME_REAL

#define MAXBOB          0x100000L
#define INVERSECOLORMAP 32
#define ANG5            (ANG90 / 18)

static boolean onground;

void P_Thrust(player_t *p, angle_t angle, fixed_t move)
{
    uint16_t fa = angle >> ANGLETOFINESHIFT;
    p->mo->momx += FixedMul(move, fine_cosine(fa));
    p->mo->momy += FixedMul(move, fine_sine(fa));
}

void P_CalcHeight(player_t *p)
{
    fixed_t bob, ceil4;
    mobj_t *mo = p->mo;

    /* bobbing from the momentum */
    p->bob = FixedMul(mo->momx, mo->momx) + FixedMul(mo->momy, mo->momy);
    p->bob >>= 2;
    if (p->bob > MAXBOB)
        p->bob = MAXBOB;
    ceil4 = FIX(mo->ceilingz) - 4 * FRACUNIT;
    if ((p->cheats & CF_NOMOMENTUM) || !onground) {
        p->viewz = mo->z + VIEWHEIGHT;
        if (p->viewz > ceil4)
            p->viewz = ceil4;
        p->viewz = mo->z + p->viewheight;       /* vanilla overrides it */
        return;
    }
    bob = FixedMul(p->bob / 2, fine_sine((FINEANGLES / 20 * leveltime) & FINEMASK));
    if (p->playerstate == PST_LIVE) {
        p->viewheight += p->deltaviewheight;
        if (p->viewheight > VIEWHEIGHT) {
            p->viewheight = VIEWHEIGHT;
            p->deltaviewheight = 0;
        }
        if (p->viewheight < VIEWHEIGHT / 2) {
            p->viewheight = VIEWHEIGHT / 2;
            if (p->deltaviewheight <= 0)
                p->deltaviewheight = 1;
        }
        if (p->deltaviewheight) {
            p->deltaviewheight += FRACUNIT / 4;
            if (!p->deltaviewheight)
                p->deltaviewheight = 1;
        }
    }
    p->viewz = mo->z + p->viewheight + bob;
    if (p->viewz > ceil4)
        p->viewz = ceil4;
}

static void P_MovePlayer(player_t *p)
{
    ticcmd_t *cmd = &p->cmd;
    mobj_t *mo = p->mo;

    mo->angle += cmd->angleturn;
    onground = mo->z <= FIX(mo->floorz);
    if (cmd->forwardmove && onground)
        P_Thrust(p, mo->angle, (fixed_t)cmd->forwardmove * 2048);
    if (cmd->sidemove && onground)
        P_Thrust(p, mo->angle - ANG90, (fixed_t)cmd->sidemove * 2048);
    if ((cmd->forwardmove || cmd->sidemove) && mo->state == S_PLAY)
        P_SetMobjState(mo, S_PLAY_RUN1);
}

static void P_DeathThink(player_t *p)
{
    angle_t angle, delta;
    mobj_t *mo = p->mo;

    P_MovePsprites(p);
    /* fall to the ground */
    if (p->viewheight > 6 * FRACUNIT)
        p->viewheight -= FRACUNIT;
    if (p->viewheight < 6 * FRACUNIT)
        p->viewheight = 6 * FRACUNIT;
    p->deltaviewheight = 0;
    onground = mo->z <= FIX(mo->floorz);
    P_CalcHeight(p);
    if (p->attacker && p->attacker != mo) {
        angle = R_PointToAngle2(mo->x, mo->y, p->attacker->x, p->attacker->y);
        delta = angle - mo->angle;
        if (delta < ANG5 || delta > (angle_t)-ANG5) {
            /* looking at the killer: fade the damage flash down */
            mo->angle = angle;
            if (p->damagecount)
                p->damagecount--;
        } else if (delta < ANG180) {
            mo->angle += ANG5;
        } else {
            mo->angle -= ANG5;
        }
    } else if (p->damagecount) {
        p->damagecount--;
    }
    if (p->cmd.buttons & BT_USE)
        p->playerstate = PST_REBORN;
}

void P_PlayerThink(player_t *p)
{
    ticcmd_t *cmd = &p->cmd;
    uint8_t newweapon;
    mobj_t *mo = p->mo;

    if (!mo)
        return;
    if (p->cheats & CF_NOCLIP)
        FLAGS_SET(mo->flags, MF_NOCLIP);
    else
        FLAGS_CLR(mo->flags, MF_NOCLIP);
    /* chainsaw run forward */
    if (FLAG(mo->flags, MF_JUSTATTACKED)) {
        cmd->angleturn = 0;
        cmd->forwardmove = 0xC800 / 512;
        cmd->sidemove = 0;
        FLAGS_CLR(mo->flags, MF_JUSTATTACKED);
    }
    if (p->playerstate == PST_DEAD) {
        P_DeathThink(p);
        return;
    }
    /* reactiontime: frozen after a teleport */
    if (mo->reactiontime)
        mo->reactiontime--;
    else
        P_MovePlayer(p);
    P_CalcHeight(p);
    if (sec_special[mo->sector])
        P_PlayerInSpecialSector(p);

    if (cmd->buttons & BT_CHANGE) {
        newweapon = (cmd->buttons & BT_WEAPONMASK) >> BT_WEAPONSHIFT;
        if (newweapon == wp_fist && p->weaponowned[wp_chainsaw]
            && !(p->readyweapon == wp_chainsaw && p->powers[pw_strength]))
            newweapon = wp_chainsaw;
        if (newweapon < NUMWEAPONS && p->weaponowned[newweapon] && newweapon != p->readyweapon)
            p->pendingweapon = newweapon;
    }
    if (cmd->buttons & BT_USE) {
        if (!p->usedown) {
            P_UseLines(p);
            p->usedown = true;
        }
    } else {
        p->usedown = false;
    }
    P_MovePsprites(p);

    /* counters */
    if (p->powers[pw_strength])
        p->powers[pw_strength]++;   /* strength counts up to diminish fade */
    if (p->powers[pw_invulnerability])
        p->powers[pw_invulnerability]--;
    if (p->powers[pw_invisibility])
        if (!--p->powers[pw_invisibility])
            FLAGS_CLR(mo->flags, MF_SHADOW);
    if (p->powers[pw_infrared])
        p->powers[pw_infrared]--;
    if (p->powers[pw_ironfeet])
        p->powers[pw_ironfeet]--;
    if (p->damagecount)
        p->damagecount--;
    if (p->bonuscount)
        p->bonuscount--;
    /* colormaps */
    if (p->powers[pw_invulnerability]) {
        if (p->powers[pw_invulnerability] > 4 * 32 || (p->powers[pw_invulnerability] & 8))
            p->fixedcolormap = INVERSECOLORMAP;
        else
            p->fixedcolormap = 0;
    } else if (p->powers[pw_infrared]) {
        if (p->powers[pw_infrared] > 4 * 32 || (p->powers[pw_infrared] & 8))
            p->fixedcolormap = 1;
        else
            p->fixedcolormap = 0;
    } else {
        p->fixedcolormap = 0;
    }
}

#endif
