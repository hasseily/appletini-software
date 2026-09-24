/* Doom for the Appletini -- the game's entry points, level flow, tic
 * commands and the render packet (docs/DESIGN.md sections 8, 9, 10).
 *
 * The kernel calls, in GAME space (src/kernel/frame.s):
 *   game_init   once at boot (crt0.s): the far tables, the player, E1M1
 *   game_tic    once per 35 Hz tic: pending level changes, the tic
 *               command from the input block, P_Ticker
 *   game_frame  once per rendered frame, after the tics: the render
 *               packet (rview) for render_frame
 *
 * Level flow (vanilla g_game.c for one player, no menus yet): the start
 * map is E1M1 at "hurt me plenty". An exit (G_ExitLevel,
 * G_SecretExitLevel) ends the level at the next tic: the tally of the
 * level (wminfo: kills, items, secrets, time, par) is made and the game
 * waits in GS_INTERMISSION for a new press of fire or use (vanilla
 * WI_checkForAccelerate; the intermission screens will show wminfo),
 * then loads the next converted map: E1M1..E1M8 in order, E1M3's secret
 * exit to E1M9, E1M9 back to E1M4. E1M8's exit ends the episode
 * (GS_FINALE, vanilla's ga_victory: no tally, the end text), and a press
 * there starts a new game at E1M1. The dead player's use key restarts the
 * level with a new player (G_PlayerReborn), as vanilla's single-player
 * G_DoReborn does. Every load first undoes what the specials changed in
 * the far map records (P_ResetLevelData, p_spec.c), since the game has no
 * WAD to reload them from.
 *
 * Messages: player.message (MSG_*: pickups, "you need a key") is taken
 * after every tic into a queue of MSGQ_SIZE for the status bar, which
 * reads them with G_NextMessage (vanilla's HU_Ticker takes and clears
 * plr->message the same way; the oldest is dropped when the queue is
 * full).
 *
 * S_StartSound, G_BuildTiccmd and R_BuildView are a_view.s on the 6502.
 *
 * The render packet (rview.h) is the eye (player.viewz with the bob), the
 * angle, the weapon layers, extralight, the tic, and the things nearest
 * to the eye: all actors and statics that have a sprite except the
 * player's own, sorted into 32 distance bands of 128 units; when there
 * are more than RV_MAXTHINGS, the nearest bands are taken first and
 * things behind the eye (more than 64 units behind its plane) are left
 * out, since the renderer would not draw them.
 */
#include "p_spec.h"          /* P_ResetLevelData */
#include "rview.h"

#ifdef GAME_REAL

#include <string.h>

player_t player;
uint8_t gameskill, gameepisode, gamemap, gameaction, gamestate;
wbstartstruct_t wminfo;
uint16_t wi_tics;
uint32_t leveltics;
uint16_t leveltime, totalkills, totalitems, totalsecret;
rview_t rview;
uint8_t snd_last[8], snd_count;
unsigned long game_tics;

void game_farinit(void);            /* fixed.s */

#if !defined(__CC65__)             /* on the 6502: a_view.s */
/* --- sound hook ------------------------------------------------------------ */
/* The sound part (DESIGN.md section 11) will play these; for now the last
 * eight are kept for it and the tests. */
void S_StartSound(mobj_t *origin, uint8_t sfx)
{
    (void)origin;
    snd_last[snd_count & 7] = sfx;
    ++snd_count;
}

#endif

/* --- the player -------------------------------------------------------------- */
void G_PlayerReborn(void)
{
    uint8_t i;
    int16_t kills = player.killcount, items = player.itemcount, secrets = player.secretcount;

    memset(&player, 0, sizeof player);
    player.killcount = kills;
    player.itemcount = items;
    player.secretcount = secrets;
    player.usedown = player.attackdown = true;  /* don't do anything immediately */
    player.playerstate = PST_LIVE;
    player.health = MAXHEALTH;
    player.readyweapon = player.pendingweapon = wp_pistol;
    player.weaponowned[wp_fist] = true;
    player.weaponowned[wp_pistol] = true;
    player.ammo[am_clip] = 50;
    for (i = 0; i < NUMAMMO; ++i)
        player.maxammo[i] = maxammo[i];
}

/* vanilla G_PlayerFinishLevel: what does not carry to the next level */
static void G_PlayerFinishLevel(void)
{
    memset(player.powers, 0, sizeof player.powers);
    memset(player.cards, 0, sizeof player.cards);
    player.extralight = 0;
    player.fixedcolormap = 0;
    player.damagecount = 0;
    player.bonuscount = 0;
}

void G_ExitLevel(void)
{
    gameaction = ga_completed;
}

void G_SecretExitLevel(void)
{
    gameaction = ga_secretcompleted;
}

/* --- messages for the status bar ------------------------------------------------ */
#define MSGQ_SIZE   4
static uint8_t msgq[MSGQ_SIZE], msgq_head, msgq_count;

void G_Message(uint8_t msg)
{
    if (msgq_count == MSGQ_SIZE) {
        msgq_head = (msgq_head + 1) & (MSGQ_SIZE - 1);
        --msgq_count;
    }
    msgq[(msgq_head + msgq_count) & (MSGQ_SIZE - 1)] = msg;
    ++msgq_count;
}

uint8_t G_NextMessage(void)
{
    uint8_t msg;

    if (!msgq_count)
        return 0;
    msg = msgq[msgq_head];
    msgq_head = (msgq_head + 1) & (MSGQ_SIZE - 1);
    --msgq_count;
    return msg;
}

/* --- level flow ---------------------------------------------------------------------- */
/* Doom's par times of episode 1, seconds */
static const uint8_t pars[9] = { 30, 75, 120, 90, 165, 180, 180, 30, 165 };

static boolean map_exists(uint8_t map)
{
    return far_peek(FAR(DD_DIR_BANK, DD_MAPDIR + MAP_SIZE * (map - 1) + MAP_NAME)) != 0;
}

static void G_DoLoadLevel(uint8_t map)
{
#ifdef __CC65__
    P_LoadOverlay();                /* the set-up code (p_setup.c, p_spec.c's end) */
#endif
    P_ResetLevelData(map);          /* the far records as the converter made them */
    /* (vanilla P_SetupLevel) */
    player.killcount = player.itemcount = player.secretcount = 0;
    P_SetupLevel(1, map, gameskill);
#ifdef __CC65__
    P_ExtendPool();                 /* its bytes become actor slots */
#endif
    gameaction = ga_nothing;
    gamestate = GS_LEVEL;
    leveltics = 0;
}

/* the level is over: its tally, then the intermission (or the episode's end) */
static void G_DoCompleted(boolean secret)
{
    uint8_t next;

    G_PlayerFinishLevel();
    if (secret && gamemap == 3)
        next = 9;
    else if (gamemap == 9)
        next = 4;
    else if (gamemap >= 8)
        next = 1;
    else
        next = gamemap + 1;
    while (!map_exists(next))
        next = next >= 9 ? 1 : next + 1;
    wminfo.epsd = gameepisode;
    wminfo.last = gamemap;
    wminfo.next = next;
    wminfo.didsecret = secret;
    wminfo.maxkills = totalkills;
    wminfo.maxitems = totalitems;
    wminfo.maxsecret = totalsecret;
    wminfo.kills = player.killcount;
    wminfo.items = player.itemcount;
    wminfo.secret = player.secretcount;
    wminfo.time = leveltics;
    wminfo.partime = gamemap <= 9 ? pars[gamemap - 1] : 0;
    wi_tics = 0;
    gamestate = gamemap == 8 ? GS_FINALE : GS_INTERMISSION;
    gameaction = ga_nothing;
}

/* vanilla WI_checkForAccelerate: a new press of fire or use */
static boolean G_Accelerate(void)
{
    uint8_t b = player.cmd.buttons;
    boolean hit = false;

    if (b & BT_ATTACK) {
        if (!player.attackdown)
            hit = true;
        player.attackdown = true;
    } else {
        player.attackdown = false;
    }
    if (b & BT_USE) {
        if (!player.usedown)
            hit = true;
        player.usedown = true;
    } else {
        player.usedown = false;
    }
    return hit;
}

#if !defined(__CC65__)             /* on the 6502: a_view.s */
/* --- tic commands (vanilla G_BuildTiccmd for the Apple's input) ----------------- */
#define SLOWTURNTICS    6
#define MAXPLMOVE       0x32
static const int8_t forwardmove[2] = { 0x19, 0x32 };
static const int8_t sidemove[2] = { 0x18, 0x28 };
static const int16_t angleturn[3] = { 640, 1280, 320 };    /* + slow turn */
static uint8_t turnheld;

void G_BuildTiccmd(ticcmd_t *cmd)
{
    uint8_t speed = (kin.buttons & KB_RUN) ? 1 : 0, tspeed;
    uint8_t move = kin.move;
    int16_t forward = 0, side = 0;

    memset(cmd, 0, sizeof *cmd);
    if (move & (KM_LEFT | KM_RIGHT)) {
        if (turnheld < 255)
            ++turnheld;
    } else {
        turnheld = 0;
    }
    tspeed = turnheld < SLOWTURNTICS ? 2 : speed;
    if (move & KM_RIGHT)
        cmd->angleturn -= angleturn[tspeed];
    if (move & KM_LEFT)
        cmd->angleturn += angleturn[tspeed];
    if (move & KM_FORWARD)
        forward += forwardmove[speed];
    if (move & KM_BACK)
        forward -= forwardmove[speed];
    if (move & KM_STRAFER)
        side += sidemove[speed];
    if (move & KM_STRAFEL)
        side -= sidemove[speed];
    /* the mouse turns: vanilla angleturn -= mousex * 8 at sensitivity 5 */
    cmd->angleturn -= kin.mouse_dx * 8;
    if (forward > MAXPLMOVE)
        forward = MAXPLMOVE;
    else if (forward < -MAXPLMOVE)
        forward = -MAXPLMOVE;
    if (side > MAXPLMOVE)
        side = MAXPLMOVE;
    else if (side < -MAXPLMOVE)
        side = -MAXPLMOVE;
    cmd->forwardmove = (int8_t)forward;
    cmd->sidemove = (int8_t)side;
    if (kin.buttons & KB_FIRE)
        cmd->buttons |= BT_ATTACK;
    if (kin.buttons & KB_USE)
        cmd->buttons |= BT_USE;
    if (kin.weapon >= 1 && kin.weapon <= 7)
        cmd->buttons |= BT_CHANGE | ((kin.weapon - 1) << BT_WEAPONSHIFT);
}

/* --- the render packet --------------------------------------------------------------- */
#define NBANDS 32
#define MAXCAND 255
static uint8_t band_head[NBANDS];
static uint8_t band_hist[NBANDS];
static uint8_t band_count, band_limit;
static boolean band_full;
static void *cand_ptr[MAXCAND];     /* the thing (an actor or a static) */
static uint8_t cand_next[MAXCAND];

/* file the thing under its distance band (vanilla P_AproxDistance in
 * map units, 128-unit bands); bands past band_limit are only counted */
static void add_candidate(void *thing, int16_t dx, int16_t dy)
{
    uint16_t ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy;
    uint16_t d = ax < ay ? ax + ay - (ax >> 1) : ax + ay - (ay >> 1);
    uint8_t band = d >= (NBANDS << 7) ? NBANDS - 1 : (uint8_t)(d >> 7);

    if (band_hist[band] < 255)
        ++band_hist[band];
    if (band > band_limit)
        return;
    if (band_count == MAXCAND) {
        band_full = true;
        return;
    }
    cand_ptr[band_count] = thing;
    cand_next[band_count] = band_head[band];
    band_head[band] = band_count;
    ++band_count;
}

static void gather(mobj_t *pmo, int16_t px, int16_t py)
{
    mobj_t *mo;
    sobj_t *s;

    memset(band_head, 0xFF, sizeof band_head);
    memset(band_hist, 0, sizeof band_hist);
    band_count = 0;
    band_full = false;
    for (mo = mobjs; mo < mobjs_end; ++mo) {
        if (mo->thinker.function != (think_t)P_MobjThinker || mo == pmo
            || FLAG(mo->flags, MF_NOSECTOR) || mo->state == S_NULL)
            continue;
        add_candidate(mo, UNITS(mo->x) - px, UNITS(mo->y) - py);
    }
    for (s = statics; s < statics_end; ++s) {
        if ((s->sflags & SF_FREE) || FLAG(mobjinfo[s->type].flags, MF_NOSECTOR))
            continue;
        add_candidate(s, s->x - px, s->y - py);
    }
}

void R_BuildView(void)
{
    mobj_t *mo, *pmo = player.mo;
    sobj_t *s;
    rthing_t *t;
    uint8_t i, b, n, cull, fc;
    uint16_t sum;
    int16_t px, py, dx, dy;
    int32_t cosv = 0, sinv = 0, dot;
    uint16_t state;
    pspdef_t *psp;
    rpsprite_t *rp;

    if (!pmo)
        return;
    rview.x = pmo->x >> 12;
    rview.y = pmo->y >> 12;
    rview.z = player.viewz >> 12;
    rview.angle = pmo->angle;
    rview.extralight = player.extralight;
    fc = player.fixedcolormap;
    /* Doom colormap c is the stored colormap c >> 1; the invulnerability
     * map (32) has no number in the packet yet */
    rview.fixedcolormap = fc == 0 || fc == 32 ? RV_NOCOLORMAP : fc >> 1;
    rview.tic = leveltime;

    /* weapon layers */
    n = 0;
    for (i = 0, psp = player.psprites; i < NUMPSPRITES; ++i, ++psp) {
        if (!psp->state)
            continue;
        rp = &rview.psprites[n++];
        rp->sprite = st_sprite[psp->state];
        rp->frame = st_frame[psp->state];
        rp->sx = psp->sx;
        rp->sy = psp->sy;
    }
    rview.npsprites = n;
    for (; n < 2; ++n)
        rview.psprites[n].sprite = 0xFF;

    /* the candidates by distance band; with more than MAXCAND of them a
     * second pass keeps the bands that hold the nearest MAXCAND */
    px = UNITS(pmo->x);
    py = UNITS(pmo->y);
    band_limit = NBANDS - 1;
    gather(pmo, px, py);
    if (band_full) {
        sum = 0;
        for (b = 0; b < NBANDS; ++b) {
            sum += band_hist[b];
            if (sum > MAXCAND)
                break;
        }
        band_limit = b ? b - 1 : 0;
        gather(pmo, px, py);
    }
    cull = band_count > RV_MAXTHINGS;
    if (cull) {
        cosv = fine_cosine(pmo->angle >> ANGLETOFINESHIFT) >> 8;
        sinv = fine_sine(pmo->angle >> ANGLETOFINESHIFT) >> 8;
    }

    /* nearest bands first; when they are too many, not those behind */
    n = 0;
    t = rview.things;
    for (b = 0; b < NBANDS && n < RV_MAXTHINGS; ++b) {
        for (i = band_head[b]; i != 0xFF && n < RV_MAXTHINGS; i = cand_next[i]) {
            mo = cand_ptr[i];
            if (IS_STATIC(mo)) {
                s = AS_STATIC(mo);
                if (cull) {
                    dx = s->x - px;
                    dy = s->y - py;
                    dot = (int32_t)dx * cosv + (int32_t)dy * sinv;
                    if (dot < -64L * 256)
                        continue;
                }
                t->x = (int32_t)s->x << 4;
                t->y = (int32_t)s->y << 4;
                t->z = (int32_t)s->z << 4;
                t->angle = (angle_t)s->angle << 8;
                state = s->state;
                t->flags = FLAG(mobjinfo[s->type].flags, MF_SHADOW) ? RT_SHADOW : 0;
                t->sector = s->sector;
            } else {
                if (cull) {
                    dx = UNITS(mo->x) - px;
                    dy = UNITS(mo->y) - py;
                    dot = (int32_t)dx * cosv + (int32_t)dy * sinv;
                    if (dot < -64L * 256)
                        continue;
                }
                t->x = mo->x >> 12;
                t->y = mo->y >> 12;
                t->z = mo->z >> 12;
                t->angle = mo->angle;
                state = mo->state;
                t->flags = FLAG(mo->flags, MF_SHADOW) ? RT_SHADOW : 0;
                t->sector = mo->sector;
            }
            t->sprite = st_sprite[state];
            t->frame = st_frame[state];
            t->pad = 0;
            ++t;
            ++n;
        }
    }
    rview.nthings = n;
}

#endif

/* --- entry points ------------------------------------------------------------------------- */
void game_init(void)
{
    game_farinit();
    M_ClearRandom();
    gameskill = sk_medium;
    player.playerstate = PST_REBORN;
    G_DoLoadLevel(1);
    R_BuildView();
}

void game_tic(void)
{
    ++game_tics;
    switch (gameaction) {
    case ga_completed:
        G_DoCompleted(false);
        break;
    case ga_secretcompleted:
        G_DoCompleted(true);
        break;
    case ga_worlddone:
        G_DoLoadLevel(wminfo.next);
        break;
    case ga_newgame:                /* after the episode: a new game */
        player.playerstate = PST_REBORN;
        G_DoLoadLevel(1);
        break;
    case ga_loadlevel:
        G_DoLoadLevel(gamemap);
        break;
    }
    G_BuildTiccmd(&player.cmd);
    if (gamestate != GS_LEVEL) {
        /* the intermission, the episode's end: wait for a press */
        if (wi_tics < 0xFFFF)
            ++wi_tics;
        if (G_Accelerate())
            gameaction = gamestate == GS_FINALE ? ga_newgame : ga_worlddone;
        return;
    }
    player.message = 0;
    P_Ticker();
    ++leveltics;
    if (player.message)
        G_Message(player.message);
    if (player.playerstate == PST_REBORN)
        gameaction = ga_loadlevel;  /* vanilla single player: restart the level */
}

void game_frame(void)
{
    R_BuildView();
}

#endif
