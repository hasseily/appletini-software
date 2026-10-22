#ifndef STARFALL_GAME_H
#define STARFALL_GAME_H
#include <stdint.h>

/* One simulation tick is 1/30 second. Coordinates are unsigned playfield
 * pixels and describe sprite centres: x stays in 0..239 and y below 256. */
#define SF_WIDTH 240
#define SF_TOP 16
#define SF_BOTTOM 199
#define SF_ENEMIES 14
#define SF_PLAYER_BULLETS 28
#define SF_ENEMY_BULLETS 36
#define SF_FX 12
#define SF_PICKUPS 3
#define SF_WINGMEN 2
/* A sector lasts 24 seconds and raises the difficulty two levels. Pressure
 * stops rising at the last level, from the ninth sector. */
#define SF_SECTOR_TICKS 720
#define SF_LEVELS_PER_SECTOR 2
#define SF_LAST_LEVEL 15
#define SF_MAX_HULL 3
#define SF_MAX_BOMBS 5
#define SF_MAX_WEAPON 3
#define SF_CHAIN_TICKS 45
/* An upgrade with the widest weapon and both wingmen starts eight seconds
 * of overdrive. */
#define SF_OVERDRIVE_TICKS 240
#define SF_IN_UP 1
#define SF_IN_DOWN 2
#define SF_IN_LEFT 4
#define SF_IN_RIGHT 8
#define SF_IN_BOMB 16
#define SF_EVENT_FIRE 1
#define SF_EVENT_SHOT 2
#define SF_EVENT_EXPLODE 4
#define SF_EVENT_HURT 8
#define SF_EVENT_PICKUP 16
#define SF_EVENT_BOMB 32
#define SF_EVENT_OVER 64
#define SF_EVENT_SECTOR 128
#define SF_EVENT_HIT 256
#define SF_EVENT_BIG 512
#define SF_EVENT_WARNING 1024
#define SF_EVENT_WINGMAN_LOST 2048
/* The kill multiplier reached its top, x8: overdrive with fifteen chained kills. */
#define SF_EVENT_TOP_CHAIN 4096
#define SF_SCOUT 0
#define SF_DART 1
#define SF_GUNSHIP 2
#define SF_HEAVY 3
#define SF_SWEEPER 4
#define SF_UPGRADE 0
#define SF_SHIELD 1
#define SF_REPAIR 2
#define SF_BOMB 3
/* last_pickup also reports what an upgrade became at the top weapon level. */
#define SF_GOT_WINGMAN 4
#define SF_GOT_OVERDRIVE 5
/* Enemy bullet styles, stored as the bullet's nonzero active value. */
#define SF_SHOT_ORB 1
#define SF_SHOT_FAN 2
#define SF_SHOT_NEEDLE 3
#define SF_FX_BLAST 0
#define SF_FX_BIG 1
#define SF_FX_SPARK 2

/* The 65C02 indexes parallel byte arrays with one absolute,Y operand, so
 * each pool is stored as one array per field rather than as structures. */
typedef struct sf_game {
    uint32_t tick,score;
    uint16_t rng,kills,sector_clock;
    uint8_t ship_x,ship_y;
    uint8_t hull,bombs,weapon,invulnerable,shield,game_over;
    uint8_t sector;     /* zero-based, shown as SECTOR 01.. */
    uint8_t level;      /* difficulty, min(sector * SF_LEVELS_PER_SECTOR, SF_LAST_LEVEL) */
    uint8_t fire_clock,previous_input,spawn_clock,second;
    uint8_t chain,chain_clock,drop_count,drops,warned,last_pickup;
    uint8_t overdrive;  /* ticks left */
    uint8_t enemy_active[SF_ENEMIES],enemy_kind[SF_ENEMIES],enemy_hp[SF_ENEMIES];
    uint8_t enemy_x[SF_ENEMIES],enemy_y[SF_ENEMIES],enemy_phase[SF_ENEMIES];
    uint8_t enemy_age[SF_ENEMIES];  /* saturates at 255 */
    uint8_t enemy_fire[SF_ENEMIES]; /* ticks until the next shot */
    int8_t enemy_dx[SF_ENEMIES];
    /* Player shots always rise six pixels a tick. */
    uint8_t shot_active[SF_PLAYER_BULLETS],shot_x[SF_PLAYER_BULLETS];
    uint8_t shot_y[SF_PLAYER_BULLETS],shot_power[SF_PLAYER_BULLETS];
    int8_t shot_dx[SF_PLAYER_BULLETS];
    uint8_t bullet_active[SF_ENEMY_BULLETS]; /* 0 or SF_SHOT_* */
    uint8_t bullet_x[SF_ENEMY_BULLETS],bullet_y[SF_ENEMY_BULLETS];
    int8_t bullet_dx[SF_ENEMY_BULLETS],bullet_dy[SF_ENEMY_BULLETS];
    uint8_t fx_life[SF_FX],fx_x[SF_FX],fx_y[SF_FX],fx_kind[SF_FX];
    uint8_t pickup_active[SF_PICKUPS],pickup_x[SF_PICKUPS],pickup_y[SF_PICKUPS];
    uint8_t pickup_kind[SF_PICKUPS];
    /* Wingmen trail the ship on fixed sides: 0 left, 1 right. */
    uint8_t wing_active[SF_WINGMEN],wing_x[SF_WINGMEN],wing_y[SF_WINGMEN];
} sf_game;

/* The single simulation state. Copy it to keep or compare snapshots. On the
 * 65C02 it lives in the caller near arena's NEARBSS, outside main BSS. */
extern sf_game sf_state;
void sf_new(uint16_t seed);
/* BOMB is edge triggered; direction flags may be combined. Auto-fire is on. */
uint16_t sf_step(uint8_t input);
/* Kill score multiplier: the chain gives 1..4, doubled in overdrive. */
uint8_t sf_multiplier(void);
#endif
