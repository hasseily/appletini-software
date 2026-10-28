#include "game.h"

/* The state and every variable of this file are in the near arena. */
#ifdef __CC65__
#pragma bss-name (push, "NEARBSS")
#endif
sf_game sf_state;
#define G sf_state
/* Event bits for the current step. The simulation is not reentrant. */
uint16_t sf_events;
/* Muzzle and style of the next enemy bullet. */
uint8_t sf_muzzle_x,sf_muzzle_y,sf_muzzle_style;
#ifndef __CC65__
uint8_t sf_overlay_boss;
#endif

/* |a-b|<=r for byte coordinates as one unsigned wrap test; needs r<=13. */
#define NEAR(a,b,r) ((uint8_t)((a)-(b)+(r))<=(uint8_t)(2*(r)))

uint8_t sf_random(void)
{
    /* Unsigned 16-bit wraparound gives the same stream on cc65 and hosts. */
    G.rng=(uint16_t)(G.rng*25173U+13849U);
    return (uint8_t)(G.rng>>8);
}

void sf_effect(uint8_t x,uint8_t y,uint8_t kind)
{
    static const uint8_t life[3]={12,18,6};
    uint8_t i;
    for(i=0;i<SF_FX;++i)if(!G.fx_life[i]) {
        G.fx_x[i]=x;G.fx_y[i]=y;G.fx_life[i]=life[kind];G.fx_kind[i]=kind;return;
    }
}

static uint8_t player_shot(uint8_t x,uint8_t y,int8_t dx,uint8_t power)
{
    uint8_t i;
    for(i=0;i<SF_PLAYER_BULLETS;++i)if(!G.shot_active[i]) {
        G.shot_x[i]=x;G.shot_y[i]=y;G.shot_dx[i]=dx;
        G.shot_power[i]=power;G.shot_active[i]=1;return 1;
    }
    return 0;
}

void sf_enemy_shot(int8_t dx,int8_t dy)
{
    uint8_t i;
    for(i=0;i<SF_ENEMY_BULLETS;++i)if(!G.bullet_active[i]) {
        G.bullet_x[i]=sf_muzzle_x;G.bullet_y[i]=sf_muzzle_y;
        G.bullet_dx[i]=dx;G.bullet_dy[i]=dy;G.bullet_active[i]=sf_muzzle_style;
        sf_events|=SF_EVENT_SHOT;return;
    }
}

/* Aim from the muzzle at the ship's current position. */
void sf_aimed(int8_t speed)
{
    int16_t dy=(int16_t)G.ship_y-sf_muzzle_y,dx;
    if(dy<24)dy=24;
    dx=((int16_t)G.ship_x-sf_muzzle_x)*speed/dy;
    if(dx>3)dx=3;
    if(dx< -3)dx=-3;
    sf_enemy_shot((int8_t)dx,speed);
}

void sf_pickup(uint8_t x,uint8_t y,uint8_t kind)
{
    uint8_t i;
    if(y<SF_TOP+5)y=SF_TOP+5;
    for(i=0;i<SF_PICKUPS;++i)if(!G.pickup_active[i]) {
        G.pickup_x[i]=x;G.pickup_y[i]=y;G.pickup_kind[i]=kind;G.pickup_active[i]=1;return;
    }
}

uint8_t sf_multiplier(void)
{
    uint8_t m=G.chain>=15?4:(uint8_t)(1+G.chain/5);
    return G.overdrive?m*2:m;
}

/* The next pickup of the drop cycle: weapon, shield, weapon, bomb in turn. */
uint8_t sf_drop(void)
{
    static const uint8_t cycle[4]={SF_BOMB,SF_UPGRADE,SF_SHIELD,SF_UPGRADE};
    return cycle[++G.drops&3];
}

static void destroy(uint8_t i)
{
    static const uint8_t points[5]={25,40,100,250,60};
    uint8_t kind=G.enemy_kind[i],x=G.enemy_x[i],y=G.enemy_y[i];
    G.enemy_active[i]=0;
    if(G.kills<65535U)++G.kills;
    G.chain=!G.chain_clock?1:(G.chain<255?G.chain+1:255);
    G.chain_clock=SF_CHAIN_TICKS;
    if(G.chain==15&&G.overdrive)sf_events|=SF_EVENT_TOP_CHAIN;
    G.score+=(uint16_t)points[kind]*sf_multiplier();
    sf_events|=SF_EVENT_EXPLODE;
    if(kind==SF_HEAVY){sf_effect(x,y,SF_FX_BIG);sf_events|=SF_EVENT_BIG;}
    else sf_effect(x,y,SF_FX_BLAST);
    /* Each fifth kill drops a pickup; each third in a boss sector. */
    if(++G.drop_count>=(G.boss?3:5)) {
        G.drop_count=0;
        sf_pickup(x,y,sf_drop());
    } else if(kind==SF_HEAVY) {
        sf_pickup(x,y,G.hull<SF_MAX_HULL?SF_REPAIR:SF_SHIELD);
    } else if(kind>=SF_GUNSHIP&&!(sf_random()&7)) {
        sf_pickup(x,y,SF_SHIELD);
    }
}

void sf_hurt(void)
{
    if(G.invulnerable||G.game_over)return;
    sf_events|=SF_EVENT_HURT;
    G.invulnerable=60;G.chain=G.chain_clock=G.overdrive=0;
    if(G.shield)G.shield=0;
    else {
        if(G.hull)--G.hull;
        if(G.weapon)--G.weapon;
    }
    sf_effect(G.ship_x,G.ship_y,SF_FX_BIG);
    if(!G.hull){G.game_over=1;sf_events|=SF_EVENT_OVER;}
}

static void bomb(void)
{
    uint8_t i;
    if(!G.bombs)return;
    --G.bombs;G.invulnerable=45;sf_events|=SF_EVENT_BOMB;
    for(i=0;i<SF_ENEMY_BULLETS;++i)G.bullet_active[i]=0;
    G.rail_clock=0;
    for(i=0;i<SF_ENEMIES;++i)if(G.enemy_active[i]) {
        if(G.enemy_hp[i]<=7)destroy(i);
        else G.enemy_hp[i]-=7;
    }
    if(G.boss&&G.boss_phase==SF_BOSS_FIGHT)sf_boss_bomb();
}

/* The new enemy's slot, or SF_ENEMIES when every slot is in use. */
uint8_t sf_spawn(uint8_t kind,uint8_t x,uint8_t phase)
{
    /* Gunships and heavies, the two most dangerous kinds, are the toughest. */
    static const uint8_t hp[5]={1,2,6,15,3};
    /* First shot delay. A scout's single aimed shot needs level 5. */
    static const uint8_t delay[5]={64,255,24,40,16};
    uint8_t i;
    for(i=0;i<SF_ENEMIES;++i)if(!G.enemy_active[i]) {
        G.enemy_x[i]=x;G.enemy_y[i]=8;G.enemy_age[i]=0;G.enemy_kind[i]=kind;
        G.enemy_hp[i]=hp[kind];G.enemy_active[i]=1;G.enemy_phase[i]=phase;
        G.enemy_fire[i]=delay[kind];G.enemy_dx[i]=G.ship_x<x?-1:1;
        if(kind==SF_HEAVY&&!G.warned){G.warned=1;sf_events|=SF_EVENT_WARNING;}
        return i;
    }
    return SF_ENEMIES;
}

/* Only normal sectors spawn waves, so this is an overlay on the 65C02. */
#ifdef __CC65__
#pragma code-name (push, "PLAY")
#pragma rodata-name (push, "PLAY")
#endif
static void spawn_wave(void)
{
    /* Cumulative odds out of sixteen for scout, dart, gunship and sweeper
     * waves; the remainder are heavies. Rows: levels 0..3, 4-7, 8-11, 12+.
     * Heavies arrive at level 4, at most one at a time until level 9. */
    static const uint8_t mix[7][4]={
        {16,16,16,16},{11,16,16,16},{8,12,16,16},{6,9,13,16},
        {5,8,12,15},{4,7,11,14},{4,6,10,13}};
    static const uint8_t order[5]={SF_SCOUT,SF_DART,SF_GUNSHIP,SF_SWEEPER,SF_HEAVY};
    const uint8_t *odds;
    uint8_t level=G.level,roll=sf_random()&15,r=sf_random(),kind=0,i,x,heavies=0;
    SF_OVERLAY(0);
    odds=mix[level<4?level:(level<8?4:(level<12?5:6))];
    while(kind<4&&roll>=odds[kind])++kind;
    kind=order[kind];
    if(kind==SF_HEAVY) {
        for(i=0;i<SF_ENEMIES;++i)if(G.enemy_active[i]&&G.enemy_kind[i]==SF_HEAVY)++heavies;
        if(heavies>=1+(level>=9)+(level>=13))kind=SF_GUNSHIP;
    }
    switch(kind) {
    case SF_SCOUT:
        /* A line of three, five from level 6, weaving in alternate phase. */
        x=52+r%137;
        sf_spawn(SF_SCOUT,x,0);
        sf_spawn(SF_SCOUT,x-22,12);
        sf_spawn(SF_SCOUT,x+22,12);
        if(level>=6){sf_spawn(SF_SCOUT,x-44,0);sf_spawn(SF_SCOUT,x+44,0);}
        break;
    case SF_DART:
        x=24+r%96;
        sf_spawn(SF_DART,x,0);
        sf_spawn(SF_DART,SF_WIDTH-x,0);
        if(level>=8)sf_spawn(SF_DART,SF_WIDTH/2,0);
        break;
    case SF_GUNSHIP:
        x=24+r%(level>=10?80:193);
        sf_spawn(SF_GUNSHIP,x,0);
        if(level>=10)sf_spawn(SF_GUNSHIP,SF_WIDTH-x,0);
        break;
    case SF_SWEEPER:
        x=24+r%193;
        sf_spawn(SF_SWEEPER,x,0);
        if(level>=6)sf_spawn(SF_SWEEPER,SF_WIDTH-x,0);
        break;
    default:
        x=40+r%161;
        sf_spawn(SF_HEAVY,x,0);
        if(level>=8){sf_spawn(SF_SCOUT,x-26,0);sf_spawn(SF_SCOUT,x+26,12);}
        break;
    }
}

/* A run that starts at sector n, 1..99, for the title's cheat. The first
 * step enters that sector, with its bonus, and its boss when it has one. The
 * ship has the widest gun, both wingmen, a shield and every bomb. */
void sf_begin(uint8_t n)
{
    if(n>1) {
        G.sector=n-2;G.sector_clock=SF_SECTOR_TICKS-1;
        G.bosses=(n-1)/SF_BOSS_EVERY<SF_BOSS_COUNT?(n-1)/SF_BOSS_EVERY:SF_BOSS_COUNT;
    }
    G.weapon=SF_MAX_WEAPON;G.wing_active[0]=G.wing_active[1]=1;
    G.wing_x[0]=G.wing_x[1]=G.ship_x;G.wing_y[0]=G.wing_y[1]=G.ship_y;
    G.shield=1;G.bombs=SF_MAX_BOMBS;
}
#ifdef __CC65__
#pragma rodata-name (pop)
#pragma code-name (pop)
#endif

static void move_enemies(void)
{
    uint8_t i,j,n,level=G.level;
    for(i=0;i<SF_ENEMIES;++i)if(G.enemy_active[i]) {
        if(G.enemy_age[i]<255)++G.enemy_age[i];
        if(G.enemy_fire[i])--G.enemy_fire[i];
        sf_muzzle_x=G.enemy_x[i];sf_muzzle_style=SF_SHOT_ORB;
        switch(G.enemy_kind[i]) {
        case SF_SCOUT:
            ++G.enemy_y[i];
            G.enemy_x[i]+=((G.enemy_age[i]+G.enemy_phase[i])/12)&1?1:-1;
            if(!G.enemy_fire[i]) {
                G.enemy_fire[i]=level>=11?54:255;
                sf_muzzle_y=G.enemy_y[i]+7;
                if(level>=5)sf_aimed(2);
            }
            break;
        case SF_DART:
            G.enemy_y[i]+=3;
            if(G.enemy_age[i]<35)G.enemy_x[i]+=G.enemy_dx[i];
            break;
        case SF_GUNSHIP:
            if(G.enemy_y[i]<52||G.enemy_age[i]>175)++G.enemy_y[i];
            if(!G.enemy_fire[i]) {
                G.enemy_fire[i]=64-(5*level>>1);sf_muzzle_y=G.enemy_y[i]+7;
                sf_aimed(level>=10?3:2);
            }
            break;
        case SF_HEAVY:
            if(G.enemy_y[i]<38||G.enemy_age[i]>250)++G.enemy_y[i];
            if(!G.enemy_fire[i]) {
                /* Three-shot fans; five shots only from level 8. */
                G.enemy_fire[i]=77-(5*level>>1);sf_muzzle_y=G.enemy_y[i]+10;n=level>=8?5:3;
                sf_muzzle_style=SF_SHOT_FAN;
                for(j=0;j<n;++j)sf_enemy_shot((int8_t)(j-(n>>1)),2);
            }
            break;
        default:
            G.enemy_x[i]+=G.enemy_dx[i]*2;
            if(G.enemy_x[i]<10){G.enemy_x[i]=10;G.enemy_dx[i]=1;}
            if(G.enemy_x[i]>SF_WIDTH-10){G.enemy_x[i]=SF_WIDTH-10;G.enemy_dx[i]=-1;}
            if(G.tick&1)++G.enemy_y[i];
            if(!G.enemy_fire[i]) {
                G.enemy_fire[i]=51-(7*level>>2);
                sf_muzzle_x=G.enemy_x[i];sf_muzzle_y=G.enemy_y[i]+6;
                sf_muzzle_style=SF_SHOT_NEEDLE;sf_enemy_shot(0,3);
            }
            break;
        }
        if(G.enemy_x[i]<8)G.enemy_x[i]=8;
        if(G.enemy_x[i]>SF_WIDTH-8)G.enemy_x[i]=SF_WIDTH-8;
        if(G.enemy_y[i]>SF_BOTTOM+12)G.enemy_active[i]=0;
    }
}

static void move_bullets(uint8_t boss)
{
    uint8_t i,j,x,y,rx,ry,style;
    for(i=0;i<SF_PLAYER_BULLETS;++i)if(G.shot_active[i]) {
        x=G.shot_x[i]+=G.shot_dx[i];y=G.shot_y[i]-=6;
        if(y<SF_TOP-6||x>=SF_WIDTH){G.shot_active[i]=0;continue;}
        /* The boss stops every shot, an overdrive lance too. */
        if(boss&&sf_boss_hit(x,y,G.shot_power[i])){G.shot_active[i]=0;continue;}
        for(j=0;j<SF_ENEMIES;++j)if(G.enemy_active[j]) {
            rx=G.enemy_kind[j]==SF_HEAVY?11:7;ry=rx==11?10:7;
            if(NEAR(x,G.enemy_x[j],rx)&&NEAR(y,G.enemy_y[j],ry)) {
                /* Overdrive shots pierce what they destroy. */
                if(G.enemy_hp[j]<=G.shot_power[i]){G.shot_active[i]=G.overdrive!=0;destroy(j);}
                else {
                    G.shot_active[i]=0;G.enemy_hp[j]-=G.shot_power[i];
                    sf_effect(x,y,SF_FX_SPARK);sf_events|=SF_EVENT_HIT;
                }
                break;
            }
        }
    }
    for(i=0;i<SF_ENEMY_BULLETS;++i)if((style=G.bullet_active[i])) {
        x=G.bullet_x[i]+=G.bullet_dx[i];y=G.bullet_y[i]+=G.bullet_dy[i];
        /* Half the height of the shot: a laser is 12 lines, a slug 40. */
        ry=style==SF_SHOT_RAIL?20:(style==SF_SHOT_LASER?6:0);
        /* Every bullet moves down, so a y below its step has wrapped. */
        if(y>SF_BOTTOM+4+ry||y<G.bullet_dy[i]||x>=SF_WIDTH){G.bullet_active[i]=0;continue;}
        /* A wingman stops a bullet and is lost. */
        for(j=0;j<SF_WINGMEN;++j)if(G.wing_active[j]&&NEAR(x,G.wing_x[j],4)&&NEAR(y,G.wing_y[j],4+ry)) {
            G.wing_active[j]=G.bullet_active[i]=0;
            sf_effect(x,G.wing_y[j],SF_FX_BLAST);sf_events|=SF_EVENT_WINGMAN_LOST;
        }
        if(!G.bullet_active[i])continue;
        /* Ship art is 16x16; its vulnerable core is only 9x9 pixels. A slug
         * moves faster than its length, so it hits the core anywhere on its
         * path since the last step. */
        if(style==SF_SHOT_RAIL) {
            if(NEAR(x,G.ship_x,5)&&G.ship_y+24+G.bullet_dy[i]>=y&&G.ship_y<=y+24)
                {G.bullet_active[i]=0;sf_hurt();}
        } else if(NEAR(x,G.ship_x,4)&&NEAR(y,G.ship_y,4+ry)){G.bullet_active[i]=0;sf_hurt();}
    }
}

static void collect(uint8_t kind)
{
    uint8_t i;
    G.last_pickup=kind;G.score+=50;sf_events|=SF_EVENT_PICKUP;
    switch(kind) {
    case SF_UPGRADE:
        if(G.weapon<SF_MAX_WEAPON){++G.weapon;return;}
        /* Past the widest weapon: a wingman on each side, then overdrive. */
        for(i=0;i<SF_WINGMEN;++i)if(!G.wing_active[i]) {
            G.wing_active[i]=1;G.wing_x[i]=G.ship_x;G.wing_y[i]=G.ship_y;
            G.last_pickup=SF_GOT_WINGMAN;return;
        }
        if(!G.overdrive&&G.chain>=15)sf_events|=SF_EVENT_TOP_CHAIN;
        G.overdrive=SF_OVERDRIVE_TICKS;G.last_pickup=SF_GOT_OVERDRIVE;return;
    case SF_SHIELD: G.shield=1; return;
    case SF_REPAIR:
        if(G.hull<SF_MAX_HULL){++G.hull;return;}
        break;
    default:
        if(G.bombs<SF_MAX_BOMBS){++G.bombs;return;}
        /* Use the pickup at once, keeping the full reserve. The active
         * overlay can still be PLAY on a boss sector's transition step. */
        bomb();++G.bombs;return;
    }
    G.score+=200; /* already at the maximum */
}

static void move_pickups(void)
{
    uint8_t i,x,y,dx,dy;
    for(i=0;i<SF_PICKUPS;++i)if(G.pickup_active[i]) {
        x=G.pickup_x[i];y=G.pickup_y[i];
        if(!(G.tick&1))++y;
        /* Pickups within forty pixels drift towards the ship. */
        dx=x<G.ship_x?G.ship_x-x:x-G.ship_x;
        dy=y<G.ship_y?G.ship_y-y:y-G.ship_y;
        if(dx<40&&dy<40) {
            if(x!=G.ship_x)x+=x<G.ship_x?1:-1;
            if(y!=G.ship_y)y+=y<G.ship_y?1:-1;
        }
        G.pickup_x[i]=x;G.pickup_y[i]=y;
        if(y>SF_BOTTOM+6)G.pickup_active[i]=0;
        else if(dx<=11&&dy<=11){G.pickup_active[i]=0;collect(G.pickup_kind[i]);}
    }
}

static void fire(void)
{
    uint8_t w=G.weapon,x=G.ship_x,y=G.ship_y,count=0,p=G.overdrive?2:1,i;
    int8_t spread=w>=2?1:0;
    if(G.fire_clock){--G.fire_clock;return;}
    G.fire_clock=w==SF_MAX_WEAPON?6:5;
    /* SINGLE, TWIN, TRIPLE with a strong centre, then WIDE. Overdrive adds
     * one power to every shot. Wingmen fire straight ahead. */
    if(w!=1)count+=player_shot(x,y-9,0,w?p+1:p);
    if(w) {
        count+=player_shot(x-5,y-6,-spread,p);
        count+=player_shot(x+5,y-6,spread,p);
    }
    if(w==SF_MAX_WEAPON) {
        count+=player_shot(x-8,y-3,-2,p);
        count+=player_shot(x+8,y-3,2,p);
    }
    for(i=0;i<SF_WINGMEN;++i)if(G.wing_active[i])
        count+=player_shot(G.wing_x[i],G.wing_y[i]-6,0,p);
    if(count)sf_events|=SF_EVENT_FIRE;
}

/* Wingmen close half the distance to their side of the ship each tick, so
 * they trail it by a few pixels. */
static void move_wingmen(void)
{
    static const int8_t side[SF_WINGMEN]={-20,20};
    uint8_t i,x;
    for(i=0;i<SF_WINGMEN;++i)if(G.wing_active[i]) {
        x=G.ship_x+side[i];
        if(x<8||x>SF_WIDTH-8)x=i?SF_WIDTH-8:8;
        G.wing_x[i]=(uint8_t)((G.wing_x[i]+x+1)>>1);
        G.wing_y[i]=(uint8_t)((G.wing_y[i]+G.ship_y+6)>>1);
    }
}

/* The next sector: its level, its bonus and a breather. Sectors 5, 10, 15,
 * 20 and 25 are boss sectors. */
void sf_next_sector(void)
{
    G.sector_clock=0;
    if(G.sector<98)++G.sector;
    G.level=G.sector>=SF_RAMP_SECTORS?SF_LAST_LEVEL:(uint8_t)(G.sector*3/4);
    G.score+=(uint16_t)G.sector*100;
    /* A short breather before the next sector's first wave. */
    if(G.spawn_clock<75)G.spawn_clock=75;
    sf_events|=SF_EVENT_SECTOR;
    if(G.bosses<SF_BOSS_COUNT&&G.sector+1==SF_BOSS_EVERY*(G.bosses+1)) {
        G.boss=G.bosses+1;G.boss_phase=0;sf_events|=SF_EVENT_BOSS;
    }
}

void sf_new(uint16_t seed)
{
    uint8_t *p=(uint8_t *)&G;
    uint16_t size=sizeof(G);
    while(size--)*p++=0;
    G.rng=seed?seed:0x5F21;
    G.ship_x=120;G.ship_y=174;
    G.hull=SF_MAX_HULL;G.bombs=3;G.spawn_clock=45;G.invulnerable=45;
}

uint16_t sf_step(uint8_t input)
{
    /* A step that starts with a boss uses the boss overlay, and only it. */
    uint8_t i,r,boss=G.boss;
    sf_events=0;
    if(G.game_over)return 0;
#ifndef __CC65__
    sf_overlay_boss=boss!=0;
#endif
    ++G.tick;
    if(++G.second==30){G.second=0;++G.score;++G.seconds;}
    /* A boss sector has no clock: it ends with its boss. */
    if(!boss&&++G.sector_clock==SF_SECTOR_TICKS)sf_next_sector();
    if(G.chain_clock&&!--G.chain_clock)G.chain=0;
    if(G.invulnerable)--G.invulnerable;
    if(G.overdrive)--G.overdrive;
    if(input&SF_IN_UP)G.ship_y-=3;
    if(input&SF_IN_DOWN)G.ship_y+=3;
    if(input&SF_IN_LEFT)G.ship_x-=3;
    if(input&SF_IN_RIGHT)G.ship_x+=3;
    if(G.ship_x<8)G.ship_x=8;
    if(G.ship_x>SF_WIDTH-8)G.ship_x=SF_WIDTH-8;
    if(G.ship_y<SF_TOP+10)G.ship_y=SF_TOP+10;
    if(G.ship_y>SF_BOTTOM-9)G.ship_y=SF_BOTTOM-9;
    if((input&SF_IN_BOMB)&&!(G.previous_input&SF_IN_BOMB))bomb();
    G.previous_input=input;
    move_wingmen();
    move_enemies();
    move_bullets(boss);
    move_pickups();
    /* Ramming hurts the ship and destroys anything lighter than a heavy. */
    for(i=0;i<SF_ENEMIES;++i)if(G.enemy_active[i]&&!G.invulnerable) {
        r=G.enemy_kind[i]==SF_HEAVY?12:8;
        if(NEAR(G.enemy_x[i],G.ship_x,r)&&NEAR(G.enemy_y[i],G.ship_y,9)) {
            sf_hurt();
            if(G.enemy_kind[i]!=SF_HEAVY)destroy(i);
        }
    }
    if(boss)sf_boss_ram();
    for(i=0;i<SF_FX;++i)if(G.fx_life[i])--G.fx_life[i];
    if(!G.game_over) {
        fire();
        if(boss)sf_boss_step();
        else {
            if(G.spawn_clock)--G.spawn_clock;
            if(!G.spawn_clock) {
                spawn_wave();
                G.spawn_clock=G.level>=14?19:53-G.level*12/5;
            }
        }
    }
    return sf_events;
}
#ifdef __CC65__
#pragma bss-name (pop)
#endif
