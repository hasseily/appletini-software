#include "game.h"
/* The boss of a boss sector. On the 65C02 this file is part of the boss
 * overlay, with the boss drawing in main.c. Its variables are in the overlay
 * too, so none of them starts at zero. */
#ifdef __CC65__
#pragma code-name (push, "BOSS")
#pragma rodata-name (push, "BOSS")
#pragma bss-name (push, "BOSSBSS")
#endif
#define SF_BOSS_ART_TABLE
#include "starfall_bosses.h"
#define G sf_state
/* The record of this sector's boss. On the 65C02, main.c copies it from the
 * boss's art file before the first step; the host copies it from the header. */
sf_boss_art sf_boss;
#ifdef __CC65__
typedef char sf_boss_record_size[sizeof(sf_boss_art)==SF_BOSS_RECORD?1:-1];
#endif

/* Weapons: laser bursts, aimed orbs, orb fans, needle streams, slow mines,
 * missiles (diving darts) and the railgun, which charges for 40 steps. Boss
 * shots move about 40% faster than the shots of the waves. */
enum { W_LASER, W_AIMED, W_FAN, W_STREAM, W_MINES, W_MISSILE, W_RAIL };
#define RAIL_CHARGE 40
#define RAIL_SPEED 34
/* Manta, Excalibur, Scarab, Comet, Bulwark: the left, right and centre
 * emplacements. */
static const uint8_t weapon[SF_BOSS_COUNT][3]={
    {W_LASER,W_LASER,W_FAN},{W_AIMED,W_AIMED,W_LASER},{W_STREAM,W_STREAM,W_MINES},
    {W_MISSILE,W_MISSILE,W_FAN},{W_FAN,W_FAN,W_RAIL}};
static const uint8_t hit_points[SF_BOSS_COUNT][3]={
    {40,40,60},{48,48,72},{56,56,84},{64,64,96},{72,72,120}};
/* Steps between shots, and the first shot's delay. The railgun's reload
 * does not count its charge. Scarab's gatlings alternate 7 and 8. */
static const uint8_t reload[SF_BOSS_COUNT][3]={
    {64,64,50},{35,35,70},{7,8,37},{72,72,40},{50,50,85}};
static const uint8_t first[3]={30,60,90};
/* The boss moves two pixels each this many steps. */
static const uint8_t pace[SF_BOSS_COUNT]={2,3,2,1,3};

static uint8_t top,i,x,y,rx,ry;
#ifndef __CC65__
static uint8_t host_boss;
#endif

static void locate(void)
{
#ifndef __CC65__
    if(host_boss!=G.boss&&G.boss)sf_boss=sf_boss_arts[(host_boss=G.boss)-1];
#endif
    top=(uint8_t)(G.boss_y-sf_boss.height);
}
/* Each emplacement shoots from the middle of its hit box's bottom edge. */
static void muzzle(uint8_t part)
{
    sf_muzzle_x=(uint8_t)(G.boss_x+sf_boss.hit_x[part]+(sf_boss.hit_w[part]>>1));
    sf_muzzle_y=(uint8_t)(top+sf_boss.hit_y[part]+sf_boss.hit_h[part]);
}
static void shoot(uint8_t part)
{
    uint8_t kind=weapon[G.boss-1][part];
    muzzle(part);
    sf_muzzle_style=SF_SHOT_ORB;
    switch(kind) {
    case W_LASER:
        /* Three segments of a dashed line, 16 lines apart. */
        sf_muzzle_style=SF_SHOT_LASER;
        for(i=0;i<3;++i){sf_muzzle_y+=6;sf_enemy_shot(0,11);sf_muzzle_y+=10;}
        break;
    case W_AIMED: sf_aimed(4); break;
    case W_FAN:
        sf_muzzle_style=SF_SHOT_FAN;
        for(i=0;i<5;++i)sf_enemy_shot((int8_t)(i-2),3);
        break;
    case W_STREAM: sf_muzzle_style=SF_SHOT_NEEDLE;sf_enemy_shot(0,6); break;
    /* Two mines in five fall at two lines a step, the others at one. */
    case W_MINES: sf_enemy_shot((int8_t)((sf_random()%3)-1),sf_random()%5<2?2:1); break;
    case W_MISSILE:
        i=sf_spawn(SF_DART,sf_muzzle_x,0);
        if(i<SF_ENEMIES)G.enemy_y[i]=sf_muzzle_y;
        break;
    default:
        /* The railgun aims down its own column and holds the boss still. */
        G.rail_x=sf_muzzle_x&~1;G.rail_clock=RAIL_CHARGE;
        break;
    }
}
static void destroyed(uint8_t part)
{
    muzzle(part);
    sf_effect(sf_muzzle_x,sf_muzzle_y-8,SF_FX_BIG);
    sf_pickup(sf_muzzle_x,sf_muzzle_y,sf_drop());
    G.score+=500U*G.boss;
    sf_events|=SF_EVENT_EXPLODE|SF_EVENT_BIG;
    if(!(G.part_hp[0]|G.part_hp[1]|G.part_hp[2])) {
        G.boss_phase=SF_BOSS_DYING;G.boss_clock=75;G.rail_clock=0;
    }
}
static void damage(uint8_t part,uint8_t power)
{
    if(G.part_hp[part]<=power){G.part_hp[part]=0;destroyed(part);}
    else{G.part_hp[part]-=power;sf_events|=SF_EVENT_HIT;}
}
/* rx,ry: x,y relative to the boss; nonzero inside an opaque strip. */
static uint8_t hull(void)
{
    i=ry>>3;
    return i<sf_boss.bands&&(uint8_t)(rx-sf_boss.band_x[i])<(uint8_t)(sf_boss.band_bytes[i]<<1);
}
/* x,y relative to the boss, or nonzero outside its box. */
static uint8_t outside(void)
{
    locate();
    if(y>=G.boss_y||(uint8_t)(G.boss_y-y)>sf_boss.height)return 1;
    rx=x-G.boss_x;ry=y-top;
    return rx>=sf_boss.width;
}

uint8_t sf_boss_hit(uint8_t shot_x,uint8_t shot_y,uint8_t power)
{
    uint8_t part;
    SF_OVERLAY(1);
    if(!G.boss)return 0;
    x=shot_x;y=shot_y;
    if(outside())return 0;
    /* A shot in the columns of an intact emplacement and below it goes on
     * through the hull and hits it a step later. */
    for(part=0;part<3;++part)
        if(G.part_hp[part]&&(uint8_t)(rx-sf_boss.hit_x[part])<sf_boss.hit_w[part]) {
            i=ry-sf_boss.hit_y[part];
            if(i<sf_boss.hit_h[part]) {
                if(G.boss_phase!=SF_BOSS_DYING)damage(part,power);
                sf_effect(x,y,SF_FX_SPARK);
                return 1;
            }
            if(i<128)return 0;
        }
    if(!hull())return 0;
    sf_effect(x,y,SF_FX_SPARK);
    return 1;
}

void sf_boss_bomb(void)
{
    uint8_t part;
    SF_OVERLAY(1);
    if(G.boss_phase!=SF_BOSS_FIGHT)return;
    locate();
    for(part=0;part<3;++part)if(G.part_hp[part])damage(part,7);
}

/* The hull hurts the ship's core. */
void sf_boss_ram(void)
{
    SF_OVERLAY(1);
    if(!G.boss||G.boss_phase==SF_BOSS_DYING||G.invulnerable)return;
    x=G.ship_x;y=G.ship_y;
    if(!outside()&&hull())sf_hurt();
}

void sf_boss_step(void)
{
    uint8_t part,b=G.boss-1;
    SF_OVERLAY(1);
    locate();
    switch(G.boss_phase) {
    case 0:
        /* It enters from the top, centred, with full emplacements. */
        G.boss_x=(uint8_t)((SF_WIDTH-sf_boss.width)>>1)&~1;G.boss_y=SF_TOP;G.boss_dx=2;
        G.boss_full=0;
        for(part=0;part<3;++part) {
            G.boss_full+=G.part_hp[part]=hit_points[b][part];G.part_fire[part]=first[part];
        }
        G.rail_clock=0;G.spawn_clock=120;G.boss_phase=SF_BOSS_ENTER;
        break;
    case SF_BOSS_ENTER:
        if(++G.boss_y>=SF_TOP+sf_boss.height+8)G.boss_phase=SF_BOSS_FIGHT;
        break;
    case SF_BOSS_FIGHT:
        if(G.rail_clock) {
            if(!--G.rail_clock) {
                sf_muzzle_x=G.rail_x;sf_muzzle_y=G.boss_y;sf_muzzle_style=SF_SHOT_RAIL;
                sf_enemy_shot(0,RAIL_SPEED);
            }
        } else if(!((uint8_t)G.tick%pace[b])) {
            G.boss_x+=G.boss_dx;
            if(G.boss_x<=8)G.boss_dx=2;
            if(G.boss_x>=SF_WIDTH-8-sf_boss.width)G.boss_dx=-2;
        }
        for(part=0;part<3;++part)if(G.part_hp[part]) {
            if(G.part_fire[part])--G.part_fire[part];
            else if(!G.rail_clock){shoot(part);G.part_fire[part]=reload[b][part];}
        }
        /* Light waves: a line of three scouts each five seconds. */
        if(!--G.spawn_clock) {
            G.spawn_clock=150;
            x=40+sf_random()%161;
            sf_spawn(SF_SCOUT,x,0);sf_spawn(SF_SCOUT,x-22,12);sf_spawn(SF_SCOUT,x+22,12);
        }
        break;
    default:
        /* Explosions across the hull, then the next sector. */
        if(!(G.boss_clock%6)) {
            sf_effect((uint8_t)(G.boss_x+sf_random()%sf_boss.width),
                      (uint8_t)(top+sf_random()%sf_boss.height),SF_FX_BIG);
            if(!(G.boss_clock%18))sf_events|=SF_EVENT_BIG|SF_EVENT_EXPLODE;
        }
        if(!--G.boss_clock) {
            G.score+=2000U*G.boss;++G.bosses;G.boss=0;
            sf_events|=SF_EVENT_BOSS_DOWN;
            sf_next_sector();
        }
        break;
    }
}
#ifdef __CC65__
#pragma bss-name (pop)
#pragma rodata-name (pop)
#pragma code-name (pop)
#endif
