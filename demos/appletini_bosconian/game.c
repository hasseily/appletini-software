/*
 * Appletini Bosconian -- world simulation (docs/DESIGN.md section 10).
 *
 * Positions are integer world pixels (u16, x 0..1023, y 0..1791) and wrap
 * on both axes like the arcade's. Fractional
 * speeds use frame parity: a 1.5 px/frame object moves 2 px on even frames
 * and 1 px on odd frames. Every object is a set of parallel arrays indexed
 * by a u8 slot, which is what cc65 turns into cheap absolute,X code.
 *
 * Screen coordinates are deltas from the ship, which sits at the playfield
 * center (128,100). "sdx/sdy" below always means "object center minus ship
 * center", wrapped into -512..511 (x) and -896..895 (y).
 */

#include "game.h"

/* ---- shared state ---- */
u16 frame;
u32 score;
u32 hi_score;
u32 next_extra;
u8 lives;
u8 round_no;
u8 condition;
u16 player_x, player_y;
u8 player_h;
u8 player_dead;
u8 round_done;
s8 cam_dx, cam_dy;
u8 hud_dirty;
u8 last_event;
u8 bases_left;
u8 enemies_alive;
u8 formation_active;
u8 spy_active;

/* ---- bases ---- */
u16 base_x[BASE_MAX];
u16 base_y[BASE_MAX];
u8 base_state[BASE_MAX];
u8 base_hz[BASE_MAX];
u8 base_count;
static u8 base_pods[BASE_MAX];     /* 6-bit pod mask */
static u8 base_timer[BASE_MAX];    /* dying countdown */
static u8 base_cool[BASE_MAX];     /* pod shot cooldown */
static u8 base_mcool[BASE_MAX];    /* missile cooldown */
static s16 base_sx[BASE_MAX];
static s16 base_sy[BASE_MAX];
static u8 base_near[BASE_MAX];

/* Base geometry (docs/DESIGN.md section 10), from the arcade's tile grids.
 * [0] vertical base (64x72, core exposed at the top and bottom), [1]
 * horizontal base (72x64). pod_ox/oy are the centres of the pod SPRITES
 * relative to the base centre (a corner pod's 24x24 box includes its strut),
 * pod_hx/hy the centres of the 16x16 cannon bodies that are hit and that
 * shoot. Pods: axis pod, four corner pods, axis pod. */
static const s8 pod_ox[2][POD_COUNT] = {
    { 0, -20, 20, -20, 20, 0 }, { -28, -16, 16, -16, 16, 28 }
};
static const s8 pod_oy[2][POD_COUNT] = {
    { -28, -16, -16, 16, 16, 28 }, { 0, -20, -20, 20, 20, 0 }
};
static const s8 pod_hx[2][POD_COUNT] = {
    { 0, -24, 24, -24, 24, 0 }, { -28, -12, 12, -12, 12, 28 }
};
static const s8 pod_hy[2][POD_COUNT] = {
    { -28, -12, -12, 12, 12, 28 }, { 0, -24, -24, 24, 24, 0 }
};
/* the core box (32x40 / 40x32) and the 16 px wide tube along its axis */
static const u8 core_w[2] = { 32, 40 };
static const u8 core_h[2] = { 40, 32 };
static const u8 tube_w[2] = { 16, 40 };
static const u8 tube_h[2] = { 40, 16 };

/* ---- enemies ---- */
u8 en_type[ENEMY_MAX];
u8 en_flags[ENEMY_MAX];
u16 en_x[ENEMY_MAX];
u16 en_y[ENEMY_MAX];
static u8 en_h[ENEMY_MAX];         /* heading 0..7 */
static u8 en_timer[ENEMY_MAX];     /* homing turn countdown */
static s16 en_sx[ENEMY_MAX];
static s16 en_sy[ENEMY_MAX];
static u8 en_near[ENEMY_MAX];

/* formation follower offsets from the leader (a V that points up) */
static const s8 form_ox[FORM_SIZE] = { 0, -16, 16, -32, 32, 0 };
static const s8 form_oy[FORM_SIZE] = { 0, 14, 14, 28, 28, 28 };

/* ---- player shots ---- */
static u8 ps_life[PSHOT_MAX];
static u16 ps_x[PSHOT_MAX];
static u16 ps_y[PSHOT_MAX];
static u8 ps_h[PSHOT_MAX];
static s16 ps_sx[PSHOT_MAX];
static s16 ps_sy[PSHOT_MAX];

/* ---- enemy shots ---- */
static u8 es_life[ESHOT_MAX];
static u16 es_x[ESHOT_MAX];
static u16 es_y[ESHOT_MAX];
static s8 es_dx[ESHOT_MAX];
static s8 es_dy[ESHOT_MAX];
static s16 es_sx[ESHOT_MAX];
static s16 es_sy[ESHOT_MAX];

/* ---- missiles ---- */
static u8 ms_life[MISSILE_MAX];
static u16 ms_x[MISSILE_MAX];
static u16 ms_y[MISSILE_MAX];
static u8 ms_h[MISSILE_MAX];
static s16 ms_sx[MISSILE_MAX];
static s16 ms_sy[MISSILE_MAX];

/* ---- explosions ---- */
static u8 ex_kind[EXPL_MAX];
static u8 ex_timer[EXPL_MAX];
static u16 ex_x[EXPL_MAX];
static u16 ex_y[EXPL_MAX];
static s16 ex_sx[EXPL_MAX];
static s16 ex_sy[EXPL_MAX];

/* ---- field objects: 0 none, 1..3 asteroid shape, 4 mine ---- */
static u8 fld_kind[FIELD_MAX];
static u16 fld_x[FIELD_MAX];
static u16 fld_y[FIELD_MAX];
static s16 fld_sx[FIELD_MAX];
static s16 fld_sy[FIELD_MAX];
static u8 fld_near[FIELD_MAX];

/* ---- timers ---- */
static u8 fire_cool;               /* autofire countdown */
static u8 spawn_timer;             /* next free enemy spawn */
static u16 form_timer;             /* next formation */
static u16 spy_timer;              /* next spy ship */
static u16 round_time;             /* frames since the round started */
static u8 zig_timer;               /* P-type zigzag phase, 45 frames each */
static u8 zig_phase;
static u8 free_alive;              /* live enemies in slots 0..11 */

/* ---- stars ---- */
static s8 far_acc_x, far_acc_y;

/* ---- movement tables ---- */
static const s8 mv_x[8] = { 0, 1, 1, 1, 0, -1, -1, -1 };
static const s8 mv_y[8] = { -1, -1, 0, 1, 1, 1, 0, -1 };

/* 16 directions at speed 3 (enemy shots) */
static const s8 dir16_x[16] = { 0, 1, 2, 3, 3, 3, 2, 1, 0, -1, -2, -3, -3, -3, -2, -1 };
static const s8 dir16_y[16] = { -3, -3, -2, -1, 0, 1, 2, 3, 3, 3, 2, 1, 0, -1, -2, -3 };

static const u8 spawn_interval[3] = { 120, 90, 60 };
static const u16 form_interval[3] = { 1200, 840, 600 };
static const u16 form_bonus[3] = { 500, 1000, 1500 };

/* ---- title star rows: the bands between the title text lines (main.c
 * title_draw: big text at 40, lines at 80, 92, 104, 120, 150, 176; the
 * spinning ship at 60..75 is a sprite and covers stars itself) ---- */
static const u8 band_start[6] = { 0, 56, 112, 128, 158, 184 };
static const u8 band_len[6] = { 40, 24, 8, 22, 18, 16 };

/* ------------------------------------------------------------------ */
/* random numbers: 16-bit LFSR                                          */
/* ------------------------------------------------------------------ */
static u16 rng_state = 0xACE1;

void rng_seed(u16 s)
{
    if (s == 0) s = 0xACE1;
    rng_state = s;
}

/* Eight LFSR steps per call: one step would make consecutive values
 * (used as x then y) differ by a single shift, which lines every field
 * object and star up on a few diagonals. gcd(8, 65535) = 1, so the
 * period stays 65535. The generator only runs at round, star and spawn
 * time, never per frame. */
u16 rng_next(void)
{
    u16 v = rng_state;
    u8 n;
    for (n = 0; n < 8; ++n) {
        if ((u8)v & 1) {
            v >>= 1;
            v ^= 0xB400;
        } else {
            v >>= 1;
        }
    }
    rng_state = v;
    return v;
}

u8 rng8(void)
{
    return (u8)rng_next();
}

/* ------------------------------------------------------------------ */
/* small helpers                                                        */
/* ------------------------------------------------------------------ */
static u16 wrap_x(s16 v)
{
    if (v < 0) v += WORLD_W;
    else if (v >= WORLD_W) v -= WORLD_W;
    return (u16)v;
}

static u16 wrap_y(s16 v)
{
    if (v < 0) v += WORLD_H;
    else if (v >= WORLD_H) v -= WORLD_H;
    return (u16)v;
}

/* a - b wrapped into -512..511 */
static s16 wdelta_x(u16 a, u16 b)
{
    s16 d = (s16)(a - b);
    if (d > WORLD_W / 2 - 1) d -= WORLD_W;
    else if (d < -WORLD_W / 2) d += WORLD_W;
    return d;
}

/* a - b wrapped into -896..895 */
static s16 wdelta_y(u16 a, u16 b)
{
    s16 d = (s16)(a - b);
    if (d > WORLD_H / 2 - 1) d -= WORLD_H;
    else if (d < -WORLD_H / 2) d += WORLD_H;
    return d;
}

static s16 abs16(s16 v)
{
    return v < 0 ? -v : v;
}

/* object is inside the draw/collision range around the ship */
static u8 near_range(s16 dx, s16 dy)
{
    if (dx < -176 || dx > 176) return 0;
    if (dy < -148 || dy > 148) return 0;
    return 1;
}

/* Two centered boxes overlap. dx/dy = center b minus center a. The
 * combined box is inset by 2 px on each axis. */
static u8 boxes_hit(s16 dx, s16 dy, u8 wa, u8 ha, u8 wb, u8 hb)
{
    s16 lim;
    lim = (s16)((wa + wb) >> 1) - 2;
    if (lim <= 0) return 0;
    if (abs16(dx) >= lim) return 0;
    lim = (s16)((ha + hb) >> 1) - 2;
    if (lim <= 0) return 0;
    if (abs16(dy) >= lim) return 0;
    return 1;
}

/* heading 0..7 that points along (dx,dy) */
static u8 dir8(s16 dx, s16 dy)
{
    s16 ax = abs16(dx);
    s16 ay = abs16(dy);
    if (ax > (ay << 1)) return dx > 0 ? 2 : 6;
    if (ay > (ax << 1)) return dy > 0 ? 4 : 0;
    if (dx > 0) return dy > 0 ? 3 : 1;
    return dy > 0 ? 5 : 7;
}

/* direction 0..15 (0 = up, clockwise) that points along (dx,dy) */
static u8 dir16(s16 dx, s16 dy)
{
    s16 ax = abs16(dx);
    s16 ay = abs16(dy);
    u8 k;
    if (ax * 5 < ay) k = 0;
    else if (ax * 3 < ay * 2) k = 1;
    else if (ax * 2 < ay * 3) k = 2;
    else if (ax < ay * 5) k = 3;
    else k = 4;
    if (dx >= 0) {
        if (dy < 0) return k;
        return (u8)(8 - k);
    }
    if (dy >= 0) return (u8)(8 + k);
    return (u8)((16 - k) & 15);
}

/* turn heading h one step toward target t */
static u8 turn_toward(u8 h, u8 t)
{
    u8 diff = (t - h) & 7;
    if (diff == 0) return h;
    if (diff <= 3) return (h + 1) & 7;
    return (h - 1) & 7;
}

static void set_event(u8 ev)
{
    last_event = ev;
}

/* ------------------------------------------------------------------ */
/* score                                                                */
/* ------------------------------------------------------------------ */
void add_score(u16 n)
{
    score += n;
    hud_dirty |= HUD_SCORE;
    if (score > hi_score) {
        hi_score = score;
        hud_dirty |= HUD_HI;
    }
    if (score >= next_extra) {
        next_extra += 70000UL;
        if (lives < 9) ++lives;
        hud_dirty |= HUD_LIVES;
        sound_sfx(SFX_EXTRA_LIFE);
        set_event(EV_EXTRA_LIFE);
    }
}

/* ------------------------------------------------------------------ */
/* explosions                                                           */
/* ------------------------------------------------------------------ */
static u8 explosion_add(u8 kind, u16 x, u16 y)
{
    u8 i;
    u8 oldest = 0;
    u8 best = 0xFF;
    for (i = 0; i < EXPL_MAX; ++i) {
        if (ex_kind[i] == EX_NONE) { oldest = i; break; }
        if (ex_timer[i] < best) { best = ex_timer[i]; oldest = i; }
    }
    /* a live blast is never replaced by a small explosion */
    if (ex_kind[oldest] == EX_BLAST && kind != EX_BLAST) return oldest;
    ex_kind[oldest] = kind;
    ex_x[oldest] = x;
    ex_y[oldest] = y;
    ex_sx[oldest] = wdelta_x(x, player_x);
    ex_sy[oldest] = wdelta_y(y, player_y);
    ex_timer[oldest] = kind == EX_BLAST ? 20 : 16;
    return oldest;
}

/* ------------------------------------------------------------------ */
/* enemies                                                              */
/* ------------------------------------------------------------------ */
static void enemy_clear_all(void)
{
    u8 i;
    for (i = 0; i < ENEMY_MAX; ++i) {
        en_type[i] = EN_NONE;
        en_flags[i] = 0;
    }
    formation_active = 0;
    spy_active = 0;
    enemies_alive = 0;
    free_alive = 0;
}

/* spawn position just outside the screen on a random side; heading points
 * at the ship. dist is the offset from the ship. */
static void spawn_pos(u8 slot, u8 dist)
{
    s16 ox, oy;
    u8 side = rng8() & 3;
    s16 spread = (s16)(rng8() & 0x7F) - 64;
    switch (side) {
    case 0: ox = spread; oy = -(s16)dist; break;
    case 1: ox = (s16)dist + 30; oy = spread; break;
    case 2: ox = spread; oy = (s16)dist; break;
    default: ox = -(s16)dist - 30; oy = spread; break;
    }
    en_x[slot] = wrap_x((s16)player_x + ox);
    en_y[slot] = wrap_y((s16)player_y + oy);
    en_h[slot] = dir8(-ox, -oy);
}

static void enemy_spawn_free(void)
{
    u8 i, t, r;
    for (i = 0; i < FORM_FIRST; ++i) {
        if (en_type[i] == EN_NONE) break;
    }
    if (i == FORM_FIRST) return;
    r = rng8() & 7;
    if (r == 7) t = EN_E;
    else if (r >= 5 && round_no >= 2) t = EN_P;
    else t = EN_I;
    en_type[i] = t;
    en_flags[i] = 0;
    en_timer[i] = 12;
    spawn_pos(i, 130);
}

static void formation_spawn(void)
{
    u8 i;
    if (formation_active) return;
    for (i = 0; i < FORM_SIZE; ++i) {
        en_type[FORM_FIRST + i] = EN_I;
        en_flags[FORM_FIRST + i] = i == 0 ? EF_LEADER : EF_FOLLOWER;
        en_timer[FORM_FIRST + i] = 12;
    }
    spawn_pos(FORM_FIRST, 190);
    formation_active = 1;
    speech_say(SAY_ALERT);
    if (condition > 0) sound_sfx(SFX_ALERT);
    set_event(EV_FORMATION);
}

static void spy_spawn(void)
{
    u8 i;
    if (spy_active) return;
    for (i = 0; i < FORM_FIRST; ++i) {
        if (en_type[i] == EN_NONE) break;
    }
    if (i == FORM_FIRST) return;
    en_type[i] = EN_SPY;
    en_flags[i] = 0;
    en_timer[i] = 0;
    spawn_pos(i, 150);
    /* a spy flies past, not straight at the ship */
    en_h[i] = (en_h[i] + 1) & 7;
    spy_active = 1;
    speech_say(SAY_SPY);
    sound_sfx(SFX_SPY);
    set_event(EV_SPY);
}

/* condition one step worse. by_spy: an escaped spy ship caused it. */
static void escalate(u8 by_spy)
{
    if (condition >= 2) {
        if (by_spy) {
            speech_say(SAY_BATTLE);
            form_timer = 1;
        }
        return;
    }
    ++condition;
    hud_dirty |= HUD_COND;
    sound_tempo(condition);
    set_event(EV_CONDITION);
    if (condition == 2) speech_say(SAY_RED);
    if (by_spy) {
        speech_say(SAY_BATTLE);
        form_timer = 1;
    }
}

static void enemy_remove(u8 i)
{
    en_type[i] = EN_NONE;
    en_flags[i] = 0;
}

/* enemy i destroyed (by a shot, a blast or the ship) */
static void enemy_kill(u8 i, u8 give_score)
{
    u8 t = en_type[i];
    u8 f = en_flags[i];
    u8 j;
    if (t == EN_NONE) return;
    explosion_add(EX_SMALL, en_x[i], en_y[i]);
    sound_sfx(SFX_EXPLODE);
    enemy_remove(i);
    if (give_score) {
        if (t == EN_SPY) add_score(200);
        else if (f & EF_LEADER) add_score(form_bonus[condition]);
        else if (t == EN_P) add_score(60);
        else if (t == EN_E) add_score(70);
        else add_score(50);
    }
    if (t == EN_SPY) spy_active = 0;
    if (f & EF_LEADER) {
        /* the whole formation goes with the leader */
        for (j = FORM_FIRST + 1; j < ENEMY_MAX; ++j) {
            if (en_type[j] != EN_NONE) {
                explosion_add(EX_SMALL, en_x[j], en_y[j]);
                enemy_remove(j);
            }
        }
        formation_active = 0;
    }
}

static void enemies_tick(u8 player_active)
{
    u8 i, h, t, step;
    s8 d;
    s16 dx, dy;

    for (i = 0; i < ENEMY_MAX; ++i) {
        t = en_type[i];
        if (t == EN_NONE) continue;
        if (en_flags[i] & EF_FOLLOWER) continue;   /* placed by the leader */

        h = en_h[i];
        step = (frame & 1) ? 1 : 2;                /* 1.5 px/frame */
        if (t == EN_I) {
            if (--en_timer[i] == 0) {
                en_timer[i] = 12;
                h = turn_toward(h, dir8(-en_sx[i], -en_sy[i]));
                en_h[i] = h;
            }
        } else if (t == EN_P) {
            if (--en_timer[i] == 0) {
                en_timer[i] = 12;
                h = turn_toward(h, dir8(-en_sx[i], -en_sy[i]));
                en_h[i] = h;
            }
            /* zigzag: lean one step left or right of the homing heading */
            h = zig_phase ? (h + 1) & 7 : (h - 1) & 7;
            step = 2;
        } else if (t == EN_SPY) {
            step = 1;
        }
        d = mv_x[h];
        if (step == 2) d += d;
        en_x[i] = wrap_x((s16)en_x[i] + d);
        d = mv_y[h];
        if (step == 2) d += d;
        en_y[i] = wrap_y((s16)en_y[i] + d);

        dx = wdelta_x(en_x[i], player_x);
        dy = wdelta_y(en_y[i], player_y);
        en_sx[i] = dx;
        en_sy[i] = dy;

        if (t == EN_E || t == EN_SPY) {
            if (abs16(dx) > 320 || abs16(dy) > 320) {
                enemy_remove(i);
                if (t == EN_SPY) {
                    spy_active = 0;
                    escalate(1);
                }
                continue;
            }
        }

        if (en_flags[i] & EF_LEADER) {
            u8 j;
            for (j = 1; j < FORM_SIZE; ++j) {
                u8 s = FORM_FIRST + j;
                if (en_type[s] == EN_NONE) continue;
                en_h[s] = en_h[i];
                en_x[s] = wrap_x((s16)en_x[i] + form_ox[j]);
                en_y[s] = wrap_y((s16)en_y[i] + form_oy[j]);
                en_sx[s] = wdelta_x(en_x[s], player_x);
                en_sy[s] = wdelta_y(en_y[s], player_y);
            }
        }
    }

    /* range flags, counts, contact with the ship */
    free_alive = 0;
    enemies_alive = 0;
    for (i = 0; i < ENEMY_MAX; ++i) {
        if (en_type[i] == EN_NONE) { en_near[i] = 0; continue; }
        ++enemies_alive;
        if (i < FORM_FIRST) ++free_alive;
        en_near[i] = near_range(en_sx[i], en_sy[i]);
        if (player_active && en_near[i] &&
            boxes_hit(en_sx[i], en_sy[i], 16, 16, 16, 16)) {
            player_dead = 1;
            enemy_kill(i, 0);
        }
    }
}

/* ------------------------------------------------------------------ */
/* enemy shots and missiles                                             */
/* ------------------------------------------------------------------ */
static void eshot_fire(u16 x, u16 y)
{
    u8 i, d;
    for (i = 0; i < ESHOT_MAX; ++i) {
        if (es_life[i] == 0) break;
    }
    if (i == ESHOT_MAX) return;
    d = dir16(wdelta_x(player_x, x), wdelta_y(player_y, y));
    es_life[i] = 90;
    es_x[i] = x;
    es_y[i] = y;
    es_dx[i] = dir16_x[d];
    es_dy[i] = dir16_y[d];
}

static void eshots_tick(u8 player_active)
{
    u8 i;
    s16 dx, dy;
    for (i = 0; i < ESHOT_MAX; ++i) {
        if (es_life[i] == 0) continue;
        --es_life[i];
        es_x[i] = wrap_x((s16)es_x[i] + es_dx[i]);
        es_y[i] = wrap_y((s16)es_y[i] + es_dy[i]);
        dx = wdelta_x(es_x[i], player_x);
        dy = wdelta_y(es_y[i], player_y);
        es_sx[i] = dx;
        es_sy[i] = dy;
        if (abs16(dx) > 160 || abs16(dy) > 140) { es_life[i] = 0; continue; }
        if (player_active && boxes_hit(dx, dy, 16, 16, 4, 4)) {
            player_dead = 1;
            es_life[i] = 0;
        }
    }
}

static void missile_fire(u16 x, u16 y)
{
    u8 i;
    for (i = 0; i < MISSILE_MAX; ++i) {
        if (ms_life[i] == 0) break;
    }
    if (i == MISSILE_MAX) return;
    ms_life[i] = 240;                  /* u8: 240 px of travel at 1 px per frame */
    ms_x[i] = x;
    ms_y[i] = y;
    ms_h[i] = dir8(wdelta_x(player_x, x), wdelta_y(player_y, y));
    sound_sfx(SFX_MISSILE);
}

static void missiles_tick(u8 player_active)
{
    u8 i, h;
    s16 dx, dy;
    for (i = 0; i < MISSILE_MAX; ++i) {
        if (ms_life[i] == 0) continue;
        --ms_life[i];
        if (ms_life[i] == 0) {
            explosion_add(EX_SMALL, ms_x[i], ms_y[i]);
            continue;
        }
        h = ms_h[i];
        if ((ms_life[i] & 7) == 0) {
            h = turn_toward(h, dir8(-ms_sx[i], -ms_sy[i]));
            ms_h[i] = h;
        }
        /* 1 px per frame: slower than the ship, so it can be outrun */
        ms_x[i] = wrap_x((s16)ms_x[i] + mv_x[h]);
        ms_y[i] = wrap_y((s16)ms_y[i] + mv_y[h]);
        dx = wdelta_x(ms_x[i], player_x);
        dy = wdelta_y(ms_y[i], player_y);
        ms_sx[i] = dx;
        ms_sy[i] = dy;
        if (player_active && boxes_hit(dx, dy, 16, 16, 4, 4)) {
            player_dead = 1;
            explosion_add(EX_SMALL, ms_x[i], ms_y[i]);
            ms_life[i] = 0;
        }
    }
}

/* ------------------------------------------------------------------ */
/* bases                                                                */
/* ------------------------------------------------------------------ */
static u16 base_score(void)
{
    u8 r = round_no;
    if (r > 4) r = 4;
    return 1500 + 500 * (u16)(r - 1);
}

static void base_kill(u8 b)
{
    u8 p;
    const s8 *hx = pod_hx[base_hz[b]];
    const s8 *hy = pod_hy[base_hz[b]];
    base_state[b] = BASE_DYING;
    base_timer[b] = 60;
    for (p = 0; p < POD_COUNT; ++p) {
        if (base_pods[b] & (1 << p)) {
            explosion_add(EX_SMALL, wrap_x((s16)base_x[b] + hx[p]),
                          wrap_y((s16)base_y[b] + hy[p]));
        }
    }
    base_pods[b] = 0;
    add_score(base_score());
    sound_sfx(SFX_BASE);
    set_event(EV_BASE_DESTROYED);
    if (bases_left) --bases_left;
}

/* cannon p of base b destroyed: 200 points, a small explosion, rubble; the
 * sixth one takes the base with it */
static void pod_kill(u8 b, u8 p)
{
    const s8 *hx = pod_hx[base_hz[b]];
    const s8 *hy = pod_hy[base_hz[b]];
    base_pods[b] &= (u8)~(1 << p);
    explosion_add(EX_SMALL, wrap_x((s16)base_x[b] + hx[p]),
                  wrap_y((s16)base_y[b] + hy[p]));
    sound_sfx(SFX_POD);
    add_score(200);
    if (base_pods[b] == 0) base_kill(b);
}

static void bases_tick(u8 player_active)
{
    u8 b, p, hz;
    s16 dx, dy, px, py;
    u8 all_gone = 1;
    const s8 *hx;
    const s8 *hy;

    for (b = 0; b < base_count; ++b) {
        if (base_state[b] == BASE_DEAD) continue;
        all_gone = 0;
        dx = wdelta_x(base_x[b], player_x);
        dy = wdelta_y(base_y[b], player_y);
        base_sx[b] = dx;
        base_sy[b] = dy;
        /* a base is up to 72 px across: widen the range by half of that */
        base_near[b] = (dx >= -212 && dx <= 212 && dy >= -184 && dy <= 184);

        if (base_state[b] == BASE_DYING) {
            if (--base_timer[b] == 0) base_state[b] = BASE_DEAD;
            continue;
        }

        if (base_cool[b]) --base_cool[b];
        if (base_mcool[b]) --base_mcool[b];

        if (!player_active || !base_near[b]) continue;

        /* homing missile from the core, from round 3 on */
        if (round_no >= 3 && base_mcool[b] == 0 &&
            abs16(dx) <= 200 && abs16(dy) <= 200) {
            base_mcool[b] = 250;
            missile_fire(base_x[b], base_y[b]);
        }

        hz = base_hz[b];
        /* ramming the core destroys the base and the ship */
        if (boxes_hit(dx, dy, 16, 16, core_w[hz], core_h[hz])) {
            player_dead = 1;
            base_kill(b);
            continue;
        }

        hx = pod_hx[hz];
        hy = pod_hy[hz];
        for (p = 0; p < POD_COUNT; ++p) {
            if (!(base_pods[b] & (1 << p))) continue;
            px = dx + hx[p];
            py = dy + hy[p];
            /* ramming a cannon destroys it and the ship */
            if (boxes_hit(px, py, 16, 16, 16, 16)) {
                player_dead = 1;
                pod_kill(b, p);
                if (base_state[b] != BASE_ALIVE) break;
                continue;
            }
            /* cannon shot: cannon on screen (which also puts it within 140 px) */
            if (base_cool[b] == 0 && abs16(px) <= 128 && abs16(py) <= 100) {
                base_cool[b] = 90;
                eshot_fire(wrap_x((s16)base_x[b] + hx[p]),
                           wrap_y((s16)base_y[b] + hy[p]));
            }
        }
    }
    if (all_gone && base_count) round_done = 1;
}

/* ------------------------------------------------------------------ */
/* field objects                                                        */
/* ------------------------------------------------------------------ */
static void field_tick(u8 player_active)
{
    u8 i, w;
    s16 dx, dy;
    for (i = 0; i < FIELD_MAX; ++i) {
        if (fld_kind[i] == 0) { fld_near[i] = 0; continue; }
        dx = wdelta_x(fld_x[i], player_x);
        if (dx < -176 || dx > 176) { fld_near[i] = 0; continue; }  /* far: skip y */
        dy = wdelta_y(fld_y[i], player_y);
        fld_sx[i] = dx;
        fld_sy[i] = dy;
        fld_near[i] = (u8)(dy >= -148 && dy <= 148);
        if (!player_active || !fld_near[i]) continue;
        w = fld_kind[i] == 4 ? 12 : 16;
        if (boxes_hit(dx, dy, 16, 16, w, w)) player_dead = 1;
    }
}

/* a mine blast at explosion e kills enemies and the ship within 14 px */
static void blast_check(u8 e, u8 player_active)
{
    u8 i;
    s16 dx, dy;
    if (player_active) {
        if (abs16(ex_sx[e]) <= 14 && abs16(ex_sy[e]) <= 14) player_dead = 1;
    }
    for (i = 0; i < ENEMY_MAX; ++i) {
        if (en_type[i] == EN_NONE || !en_near[i]) continue;
        dx = en_sx[i] - ex_sx[e];
        dy = en_sy[i] - ex_sy[e];
        if (abs16(dx) <= 14 && abs16(dy) <= 14) enemy_kill(i, 1);
    }
}

static void explosions_tick(u8 player_active)
{
    u8 i;
    for (i = 0; i < EXPL_MAX; ++i) {
        if (ex_kind[i] == EX_NONE) continue;
        ex_sx[i] = wdelta_x(ex_x[i], player_x);
        ex_sy[i] = wdelta_y(ex_y[i], player_y);
        if (ex_kind[i] == EX_BLAST) blast_check(i, player_active);
        if (--ex_timer[i] == 0) ex_kind[i] = EX_NONE;
    }
}

/* ------------------------------------------------------------------ */
/* player and player shots                                              */
/* ------------------------------------------------------------------ */
static void player_fire(void)
{
    u8 i, n = 0, a = 0xFF, b = 0xFF;
    for (i = 0; i < PSHOT_MAX; ++i) {
        if (ps_life[i]) ++n;
        else if (a == 0xFF) a = i;
        else b = i;
    }
    if (n > PSHOT_MAX - 2) return;          /* two volleys in flight */
    ps_life[a] = 24;                        /* 24 * 5 = 120 px range */
    ps_x[a] = player_x;
    ps_y[a] = player_y;
    ps_h[a] = player_h;
    ps_life[b] = 24;
    ps_x[b] = player_x;
    ps_y[b] = player_y;
    ps_h[b] = (player_h + 4) & 7;
    sound_sfx(SFX_SHOT);
}

/* one player shot against everything it can hit; returns 1 if it is used up */
static u8 pshot_hit(u8 s)
{
    u8 i, b, p, w;
    s16 dx, dy, px, py;
    s16 sx = ps_sx[s];
    s16 sy = ps_sy[s];
    const s8 *hx;
    const s8 *hy;

    /* enemies */
    for (i = 0; i < ENEMY_MAX; ++i) {
        if (en_type[i] == EN_NONE || !en_near[i]) continue;
        if (boxes_hit(en_sx[i] - sx, en_sy[i] - sy, 4, 4, 16, 16)) {
            enemy_kill(i, 1);
            return 1;
        }
    }
    /* missiles can be shot down */
    for (i = 0; i < MISSILE_MAX; ++i) {
        if (ms_life[i] == 0) continue;
        if (boxes_hit(ms_sx[i] - sx, ms_sy[i] - sy, 4, 4, 4, 4)) {
            explosion_add(EX_SMALL, ms_x[i], ms_y[i]);
            sound_sfx(SFX_HIT);
            add_score(50);
            ms_life[i] = 0;
            return 1;
        }
    }
    /* field objects */
    for (i = 0; i < FIELD_MAX; ++i) {
        if (fld_kind[i] == 0 || !fld_near[i]) continue;
        w = fld_kind[i] == 4 ? 12 : 16;
        if (boxes_hit(fld_sx[i] - sx, fld_sy[i] - sy, 4, 4, w, w)) {
            if (fld_kind[i] == 4) {
                explosion_add(EX_BLAST, fld_x[i], fld_y[i]);
                sound_sfx(SFX_MINE);
                add_score(20);
            } else {
                explosion_add(EX_SMALL, fld_x[i], fld_y[i]);
                sound_sfx(SFX_HIT);
                add_score(10);
            }
            fld_kind[i] = 0;
            return 1;
        }
    }
    /* bases: cannons, then the core */
    for (b = 0; b < base_count; ++b) {
        if (base_state[b] != BASE_ALIVE || !base_near[b]) continue;
        dx = base_sx[b] - sx;
        dy = base_sy[b] - sy;
        w = base_hz[b];
        hx = pod_hx[w];
        hy = pod_hy[w];
        for (p = 0; p < POD_COUNT; ++p) {
            if (!(base_pods[b] & (1 << p))) continue;
            px = dx + hx[p];
            py = dy + hy[p];
            if (boxes_hit(px, py, 4, 4, 16, 16)) {
                pod_kill(b, p);
                return 1;
            }
        }
        if (boxes_hit(dx, dy, 4, 4, core_w[w], core_h[w])) {
            /* the core is open only along the base's axis: a vertical base
             * takes a shot flying up or down into its 16 px tube, a
             * horizontal one a shot flying left or right; everything else
             * bounces off the hull */
            if (boxes_hit(dx, dy, 4, 4, tube_w[w], tube_h[w]) &&
                (w ? (mv_y[ps_h[s]] == 0) : (mv_x[ps_h[s]] == 0))) {
                base_kill(b);
            } else {
                sound_sfx(SFX_HIT);
            }
            return 1;
        }
    }
    return 0;
}

static void pshots_tick(void)
{
    u8 i, h;
    for (i = 0; i < PSHOT_MAX; ++i) {
        if (ps_life[i] == 0) continue;
        --ps_life[i];
        h = ps_h[i];
        ps_x[i] = wrap_x((s16)ps_x[i] + mv_x[h] * 5);
        ps_y[i] = wrap_y((s16)ps_y[i] + mv_y[h] * 5);
        ps_sx[i] = wdelta_x(ps_x[i], player_x);
        ps_sy[i] = wdelta_y(ps_y[i], player_y);
        if (pshot_hit(i)) ps_life[i] = 0;
    }
}

static void player_tick(u8 in)
{
    u8 h = player_h;
    u8 step;
    s8 d;

    /* a direction input sets the heading; the ship never stops */
    switch (in & (IN_UP | IN_DOWN | IN_LEFT | IN_RIGHT)) {
    case IN_UP: h = 0; break;
    case IN_UP | IN_RIGHT: h = 1; break;
    case IN_RIGHT: h = 2; break;
    case IN_DOWN | IN_RIGHT: h = 3; break;
    case IN_DOWN: h = 4; break;
    case IN_DOWN | IN_LEFT: h = 5; break;
    case IN_LEFT: h = 6; break;
    case IN_UP | IN_LEFT: h = 7; break;
    default: break;
    }
    player_h = h;

    step = (frame & 1) ? 1 : 2;             /* 1.5 px/frame */
    d = mv_x[h];
    if (step == 2) d += d;
    cam_dx = d;
    player_x = wrap_x((s16)player_x + d);
    d = mv_y[h];
    if (step == 2) d += d;
    cam_dy = d;
    player_y = wrap_y((s16)player_y + d);

    if (fire_cool) --fire_cool;
    if ((in & IN_FIRE) && fire_cool == 0) {
        fire_cool = 8;
        player_fire();
    }
}

/* ------------------------------------------------------------------ */
/* spawning and timers                                                  */
/* ------------------------------------------------------------------ */
static void director_tick(void)
{
    u8 cap;

    ++round_time;
    if (round_time == 2700 || round_time == 5400) escalate(0);

    if (++zig_timer >= 45) {
        zig_timer = 0;
        zig_phase ^= 1;
    }

    cap = 2 + (condition << 1) + (round_no >> 1);
    if (cap > 12) cap = 12;
    if (spawn_timer) --spawn_timer;
    if (spawn_timer == 0) {
        spawn_timer = spawn_interval[condition];
        if (free_alive < cap) enemy_spawn_free();
    }

    if (form_timer) --form_timer;
    if (form_timer == 0) {
        form_timer = form_interval[condition];
        formation_spawn();
    }

    if (spy_timer) --spy_timer;
    if (spy_timer == 0) {
        spy_timer = 1500;
        spy_spawn();
    }
}

/* ------------------------------------------------------------------ */
/* public: round setup                                                  */
/* ------------------------------------------------------------------ */
static void pools_clear(void)
{
    u8 i;
    enemy_clear_all();
    for (i = 0; i < PSHOT_MAX; ++i) ps_life[i] = 0;
    for (i = 0; i < ESHOT_MAX; ++i) es_life[i] = 0;
    for (i = 0; i < MISSILE_MAX; ++i) ms_life[i] = 0;
    for (i = 0; i < EXPL_MAX; ++i) ex_kind[i] = EX_NONE;
    fire_cool = 0;
    player_dead = 0;
    cam_dx = 0;
    cam_dy = 0;
}

void world_respawn(void)
{
    pools_clear();
    player_x = START_X;
    player_y = START_Y;
    player_h = 0;
    spawn_timer = 120;
    form_timer = form_interval[condition];
    spy_timer = 1500;
}

/* Chebyshev distance from (x,y) to every live base and to the start */
static u8 spot_is_free(u16 x, u16 y)
{
    u8 b;
    if (abs16(wdelta_x(x, START_X)) < 160 && abs16(wdelta_y(y, START_Y)) < 160) return 0;
    for (b = 0; b < base_count; ++b) {
        if (abs16(wdelta_x(x, base_x[b])) < 96 && abs16(wdelta_y(y, base_y[b])) < 96) return 0;
    }
    return 1;
}

void world_new_round(void)
{
    u8 b, i, tries;
    u16 x, y;
    const RoundDef *rd = round_layout(round_no);

    base_count = rd->count;
    for (b = 0; b < BASE_MAX; ++b) {
        base_state[b] = BASE_DEAD;
        if (b >= base_count) continue;
        base_x[b] = rd->x[b];
        base_y[b] = rd->y[b];
        base_hz[b] = (rd->hz >> b) & 1;
        base_state[b] = BASE_ALIVE;
        base_pods[b] = 0x3F;
        base_timer[b] = 0;
        base_cool[b] = 0;
        base_mcool[b] = (u8)(120 + (rng8() & 63));
    }
    bases_left = base_count;

    for (i = 0; i < FIELD_MAX; ++i) {
        fld_kind[i] = 0;
        for (tries = 0; tries < 8; ++tries) {
            x = rng_next() % WORLD_W;
            y = rng_next() % WORLD_H;
            if (spot_is_free(x, y)) break;
        }
        if (tries == 8) continue;
        fld_x[i] = x;
        fld_y[i] = y;
        if (i < ASTEROID_COUNT) fld_kind[i] = 1 + rng8() % 3;
        else fld_kind[i] = 4;
    }

    condition = 0;
    round_time = 0;
    zig_timer = 0;
    zig_phase = 0;
    round_done = 0;
    hud_dirty |= HUD_COND | HUD_ROUND;
    world_respawn();
}

/* ------------------------------------------------------------------ */
/* public: one frame                                                    */
/* ------------------------------------------------------------------ */
void world_tick(u8 in, u8 player_active)
{
    player_dead = 0;
    if (player_active) {
        player_tick(in);
        director_tick();
    } else {
        cam_dx = 0;
        cam_dy = 0;
    }
    enemies_tick(player_active);
    field_tick(player_active);
    bases_tick(player_active);
    eshots_tick(player_active);
    missiles_tick(player_active);
    if (player_active) pshots_tick();
    else {
        u8 i;
        for (i = 0; i < PSHOT_MAX; ++i) ps_life[i] = 0;
    }
    explosions_tick(player_active);
    if (!player_active) player_dead = 0;
}

void world_death_burst(void)
{
    u8 e;
    explosion_add(EX_SMALL, player_x, player_y);
    e = explosion_add(EX_SMALL, wrap_x((s16)player_x - 8), wrap_y((s16)player_y + 6));
    ex_timer[e] = 24;
    e = explosion_add(EX_SMALL, wrap_x((s16)player_x + 8), wrap_y((s16)player_y - 6));
    ex_timer[e] = 32;
}

void world_clear(void)
{
    u8 b;
    pools_clear();
    for (b = 0; b < BASE_MAX; ++b) base_state[b] = BASE_DEAD;
    base_count = 0;
    bases_left = 0;
    round_done = 0;
}

/* ------------------------------------------------------------------ */
/* public: display list                                                 */
/* ------------------------------------------------------------------ */
static struct DlItem *dlp;

/* The list is built in dl_tmp and then counting-sorted by y into
 * dl_items (docs/DESIGN.md section 5): 25 buckets of 8 rows, rows above
 * the screen in bucket 0 and rows below it in bucket 24. The sort is
 * stable, so items of one bucket keep their layer order. The ship is
 * added after the sort so it stays on top. */
#define DL_BUCKETS 25
static struct DlItem dl_tmp[DL_MAX];
static u8 dl_bucket_pos[DL_BUCKETS + 1];

static u8 dl_bucket(s16 y)
{
    if (y < 0) return 0;
    if (y >= FIELD_H) return DL_BUCKETS - 1;
    return (u8)(y >> 3);
}

static void dl_sort(void)
{
    u8 i, b;
    struct DlItem *src;
    struct DlItem *dst;

    for (b = 0; b <= DL_BUCKETS; ++b) dl_bucket_pos[b] = 0;
    src = dl_tmp;
    for (i = 0; i < dl_count; ++i, ++src) ++dl_bucket_pos[dl_bucket(src->y) + 1];
    for (b = 1; b <= DL_BUCKETS; ++b) dl_bucket_pos[b] += dl_bucket_pos[b - 1];
    src = dl_tmp;
    for (i = 0; i < dl_count; ++i, ++src) {
        b = dl_bucket(src->y);
        dst = dl_items + dl_bucket_pos[b];
        ++dl_bucket_pos[b];
        dst->id = src->id;
        dst->x = src->x;
        dst->y = src->y;
    }
    dlp = dl_items + dl_count;
}

/* add sprite id centered at (sdx,sdy) relative to the ship */
static void dl_add(u8 id, s16 sdx, s16 sdy)
{
    s16 x, y;
    u8 w, h;
    if (dl_count >= DL_MAX) return;
    w = spr_width[id];
    h = spr_height[id];
    x = FIELD_CX + sdx - (s16)(w >> 1);
    y = FIELD_CY + sdy - (s16)(h >> 1);
    if (x > 288 || y > 232) return;
    if (x < -32 - (s16)w || y < -32 - (s16)h) return;
    dlp->id = id;
    dlp->x = x;
    dlp->y = y;
    ++dlp;
    ++dl_count;
}

void world_build_dl(u8 with_player)
{
    u8 i, b, p, f, hz, id;
    const s8 *ox;
    const s8 *oy;

    dl_count = 0;
    dlp = dl_tmp;

    /* bases: the six pods (live or rubble) then the core; a dying base
     * shows the big explosion */
    for (b = 0; b < base_count; ++b) {
        if (base_state[b] == BASE_DEAD || !base_near[b]) continue;
        if (base_state[b] == BASE_DYING) {
            f = base_timer[b] > 40 ? 0 : (base_timer[b] > 20 ? 1 : 2);
            dl_add(SPR_BIGEXPL_0 + f, base_sx[b], base_sy[b]);
            continue;
        }
        hz = base_hz[b];
        ox = pod_ox[hz];
        oy = pod_oy[hz];
        for (p = 0; p < POD_COUNT; ++p) {
            if (base_pods[b] & (1 << p)) id = hz ? SPR_POD_H0 : SPR_POD_V0;
            else id = hz ? SPR_PODDEAD_H0 : SPR_PODDEAD_V0;
            dl_add(id + p, base_sx[b] + ox[p], base_sy[b] + oy[p]);
        }
        dl_add(hz ? SPR_CORE_H : SPR_CORE_V, base_sx[b], base_sy[b]);
    }

    /* field objects */
    for (i = 0; i < FIELD_MAX; ++i) {
        if (!fld_near[i]) continue;
        if (fld_kind[i] == 4) dl_add(SPR_MINE, fld_sx[i], fld_sy[i]);
        else dl_add(SPR_ASTEROID_0 + fld_kind[i] - 1, fld_sx[i], fld_sy[i]);
    }

    /* enemy shots and missiles */
    for (i = 0; i < ESHOT_MAX; ++i) {
        if (es_life[i]) dl_add(SPR_SHOT_ENEMY, es_sx[i], es_sy[i]);
    }
    f = (u8)(frame >> 2) & 1;
    for (i = 0; i < MISSILE_MAX; ++i) {
        if (ms_life[i]) dl_add(SPR_MISSILE_0 + f, ms_sx[i], ms_sy[i]);
    }

    /* enemies: every type has the eight headings */
    for (i = 0; i < ENEMY_MAX; ++i) {
        u8 t = en_type[i];
        if (t == EN_NONE || !en_near[i]) continue;
        if (t == EN_I) id = (en_flags[i] & EF_LEADER) ? SPR_PTYPE_0 : SPR_ITYPE_0;
        else if (t == EN_P) id = SPR_PTYPE_0;
        else if (t == EN_E) id = SPR_ETYPE_0;
        else id = SPR_SPY_0;
        dl_add(id + en_h[i], en_sx[i], en_sy[i]);
    }

    /* player shots: a bar along the heading, a diagonal on the diagonals */
    for (i = 0; i < PSHOT_MAX; ++i) {
        if (!ps_life[i]) continue;
        f = ps_h[i];
        if (f & 1) id = (f == 1 || f == 5) ? SPR_SHOT_PLAYER_D1 : SPR_SHOT_PLAYER_D2;
        else id = (f & 2) ? SPR_SHOT_PLAYER_H : SPR_SHOT_PLAYER;
        dl_add(id, ps_sx[i], ps_sy[i]);
    }

    /* explosions: three frames each */
    for (i = 0; i < EXPL_MAX; ++i) {
        u8 k = ex_kind[i];
        if (k == EX_NONE) continue;
        if (!near_range(ex_sx[i], ex_sy[i])) continue;
        f = ex_timer[i];
        if (k == EX_SMALL) {
            f = f > 10 ? 0 : (f > 5 ? 1 : 2);
            dl_add(SPR_EXPL_0 + f, ex_sx[i], ex_sy[i]);
        } else {
            f = f > 13 ? 0 : (f > 6 ? 1 : 2);
            dl_add(SPR_BIGEXPL_0 + f, ex_sx[i], ex_sy[i]);
        }
    }

    /* y order for the beam race, then the player last, always on top */
    dl_sort();
    if (with_player) dl_add(SPR_SHIP_0 + player_h, 0, 0);
}

/* ------------------------------------------------------------------ */
/* public: stars                                                        */
/* ------------------------------------------------------------------ */
void stars_init(u8 title)
{
    u8 i, band;
    star_count = STAR_MAX;
    for (i = 0; i < STAR_MAX; ++i) {
        star_x[i] = rng8();
        if (title) {
            /* keep title stars off the text rows */
            band = rng8() % 6;
            star_y[i] = band_start[band] + rng8() % band_len[band];
        } else {
            star_y[i] = rng8() % FIELD_H;
        }
        if (i < 24) {
            star_color[i] = C_DTEAL;                 /* far layer */
        } else {
            band = rng8() & 3;
            star_color[i] = band == 0 ? C_CYAN : (band == 1 ? C_GRAY : C_WHITE);
        }
    }
    far_acc_x = 0;
    far_acc_y = 0;
}

static void star_move(u8 i, s8 dx, s8 dy)
{
    s16 v;
    star_x[i] = (u8)(star_x[i] - dx);
    v = (s16)star_y[i] - dy;
    if (v < 0) v += FIELD_H;
    else if (v >= FIELD_H) v -= FIELD_H;
    star_y[i] = (u8)v;
}

void stars_tick(s8 dx, s8 dy)
{
    u8 i;
    s8 fx, fy;
    far_acc_x += dx;
    far_acc_y += dy;
    fx = far_acc_x >> 1;
    fy = far_acc_y >> 1;
    far_acc_x -= (s8)(fx << 1);
    far_acc_y -= (s8)(fy << 1);
    for (i = 0; i < 24; ++i) {
        if (fx || fy) star_move(i, fx, fy);
    }
    if (dx == 0 && dy == 0) return;
    for (i = 24; i < STAR_MAX; ++i) star_move(i, dx, dy);
}
