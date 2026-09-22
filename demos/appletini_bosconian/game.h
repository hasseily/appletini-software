/*
 * Appletini Bosconian -- game state shared between main.c and game.c.
 * main.c owns the state machine, HUD, title and mailbox. game.c owns the
 * world: objects, movement, collisions, spawning and the display list.
 */
#ifndef GAME_H
#define GAME_H

#include "bosco.h"

/* ---- world: the arcade's 1024x1792, wrapping on both axes; the ship starts
 * near the bottom, heading up, like the arcade ---- */
#define WORLD_W 1024
#define WORLD_H 1792
#define START_X 512
#define START_Y 1668

/* ---- object pools ---- */
#define ENEMY_MAX 18            /* 12 free enemies + 6 formation slots */
#define FORM_FIRST 12           /* formation slots 12..17, leader at 12 */
#define FORM_SIZE 6
#define PSHOT_MAX 4
#define ESHOT_MAX 8
#define MISSILE_MAX 4
#define EXPL_MAX 8
#define FIELD_MAX 40            /* 24 asteroids + 16 mines */
#define ASTEROID_COUNT 24
#define BASE_MAX 8
#define POD_COUNT 6

/* enemy types */
#define EN_NONE 0
#define EN_I 1
#define EN_P 2
#define EN_E 3
#define EN_SPY 4

/* enemy flags */
#define EF_LEADER 0x01
#define EF_FOLLOWER 0x02

/* explosion kinds */
#define EX_NONE 0
#define EX_SMALL 1              /* 16x16, 3 frames */
#define EX_BLAST 2              /* mine blast, 32x32, 3 frames, kills for 20 frames */

/* base life state */
#define BASE_DEAD 0
#define BASE_ALIVE 1
#define BASE_DYING 2

/* HUD dirty bits (main.c redraws the value when its bit is set) */
#define HUD_SCORE 0x01
#define HUD_HI 0x02
#define HUD_COND 0x04
#define HUD_ROUND 0x08
#define HUD_LIVES 0x10
#define HUD_ALL 0x1F

/* ---- shared state (defined in game.c) ---- */
extern u16 frame;               /* frames since boot, counts in every state */
extern u32 score;
extern u32 hi_score;
extern u32 next_extra;          /* score of the next extra life */
extern u8 lives;
extern u8 round_no;             /* 1.. */
extern u8 condition;            /* 0 green, 1 yellow, 2 red */
extern u16 player_x, player_y;  /* world center of the ship */
extern u8 player_h;             /* heading 0..7, 0 = up, clockwise */
extern u8 player_dead;          /* set by world_tick when the ship is hit */
extern u8 round_done;           /* set by world_tick when every base is gone */
extern s8 cam_dx, cam_dy;       /* camera movement in the last world_tick */
extern u8 hud_dirty;            /* HUD_* bits */
extern u8 last_event;           /* EV_* for the mailbox */
extern u8 bases_left;
extern u8 enemies_alive;        /* every live enemy, formation included */
extern u8 formation_active;
extern u8 spy_active;

/* bases: read by the radar */
extern u16 base_x[BASE_MAX];
extern u16 base_y[BASE_MAX];
extern u8 base_state[BASE_MAX];
extern u8 base_hz[BASE_MAX];    /* 1 = horizontal base (core exposed left/right) */
extern u8 base_count;

/* round layouts (rounds.c, from the arcade ROM): base centres in world pixels */
typedef struct {
    u8 count;                   /* bases in this layout, 3..BASE_MAX */
    u8 hz;                      /* bit b set = base b is horizontal */
    u16 x[BASE_MAX];
    u16 y[BASE_MAX];
} RoundDef;
#define ROUND_LAYOUTS 14
extern const RoundDef round_layouts[ROUND_LAYOUTS];
const RoundDef *round_layout(u8 round_no);

/* enemies: the radar shows the spy ship and the formation leader */
extern u8 en_type[ENEMY_MAX];
extern u8 en_flags[ENEMY_MAX];
extern u16 en_x[ENEMY_MAX];
extern u16 en_y[ENEMY_MAX];

/* ---- game.c API ---- */
void rng_seed(u16 s);
u16 rng_next(void);
u8 rng8(void);

void add_score(u16 n);          /* also handles the high score and extra lives */
void world_new_round(void);     /* lay out bases and field objects, reset the ship */
void world_respawn(void);       /* ship back to the start, enemies and shots cleared */
void world_tick(u8 in, u8 player_active); /* one frame of play logic */
void world_build_dl(u8 with_player);      /* fill dl_items / dl_count */
void world_death_burst(void);   /* explosions at the ship when it dies */
void world_clear(void);         /* remove every object (title screen) */
void stars_init(u8 title);      /* re-randomize both star layers */
void stars_tick(s8 dx, s8 dy);  /* scroll the stars by the camera delta */

#endif
