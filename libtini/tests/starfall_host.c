#include "game.h"
#include "starfall_bosses.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define G sf_state
/* The boss record that boss.c keeps for the boss of the sector. */
extern sf_boss_art sf_boss;

static void quiet(void)
{
    sf_new(1234);G.spawn_clock=255;G.fire_clock=255;
    G.invulnerable=0;
}

static unsigned active(const uint8_t *flags,unsigned count)
{
    unsigned i,n=0;
    for(i=0;i<count;++i)n+=flags[i]!=0;
    return n;
}

static void incoming(int offset)
{
    G.bullet_active[0]=SF_SHOT_ORB;G.bullet_x[0]=(uint8_t)(G.ship_x+offset);
    G.bullet_y[0]=(uint8_t)(G.ship_y-2);G.bullet_dx[0]=0;G.bullet_dy[0]=2;
}

static void target(unsigned kind,unsigned hp,unsigned x,unsigned y)
{
    G.enemy_active[0]=1;G.enemy_kind[0]=(uint8_t)kind;G.enemy_hp[0]=(uint8_t)hp;
    G.enemy_x[0]=(uint8_t)x;G.enemy_y[0]=(uint8_t)y;G.enemy_dx[0]=1;
    G.enemy_age[0]=G.enemy_phase[0]=0;G.enemy_fire[0]=255;
}

static void shot(unsigned x,unsigned y,unsigned power)
{
    G.shot_active[0]=1;G.shot_x[0]=(uint8_t)x;G.shot_y[0]=(uint8_t)y;
    G.shot_dx[0]=0;G.shot_power[0]=(uint8_t)power;
}

static void drop_at_ship(unsigned kind)
{
    G.pickup_active[0]=1;G.pickup_kind[0]=(uint8_t)kind;
    G.pickup_x[0]=G.ship_x;G.pickup_y[0]=G.ship_y;
}

static void test_start_movement_and_restart(void)
{
    sf_game first;
    unsigned i;
    sf_new(42);first=G;sf_new(42);
    assert(!memcmp(&first,&G,sizeof(G)));
    assert(G.ship_x==120&&G.ship_y==174&&G.hull==3&&G.bombs==3);
    assert(!G.tick&&!G.score&&!G.game_over&&!G.sector&&!G.level);
    G.spawn_clock=255;
    for(i=0;i<150;++i)sf_step(SF_IN_UP|SF_IN_LEFT);
    assert(G.ship_x==8&&G.ship_y==SF_TOP+10);
    for(i=0;i<150;++i)sf_step(SF_IN_DOWN|SF_IN_RIGHT);
    assert(G.ship_x==SF_WIDTH-8&&G.ship_y==SF_BOTTOM-9);
    sf_step(SF_IN_UP|SF_IN_DOWN|SF_IN_LEFT|SF_IN_RIGHT);
    assert(G.ship_x==SF_WIDTH-8&&G.ship_y==SF_BOTTOM-9);
    sf_new(42);assert(!memcmp(&first,&G,sizeof(G)));
    sf_new(0);assert(G.rng!=0);
    /* The ROM-boot check reads and writes these fields by offset. */
    assert(offsetof(sf_game,tick)==0&&offsetof(sf_game,hull)==16&&offsetof(sf_game,chain)==28);
    assert(offsetof(sf_game,chain_clock)==29&&offsetof(sf_game,overdrive)==34);
    assert(offsetof(sf_game,sector_clock)==12&&offsetof(sf_game,bombs)==17);
    assert(offsetof(sf_game,invulnerable)==19&&offsetof(sf_game,sector)==22);
    puts("start, movement bounds and deterministic restart: pass");
}

static void test_autofire(void)
{
    unsigned i;
    quiet();G.fire_clock=0;
    assert(sf_step(0)&SF_EVENT_FIRE);
    assert(active(G.shot_active,SF_PLAYER_BULLETS)==1&&G.shot_power[0]==1);
    for(i=0;i<5;++i)assert(!(sf_step(0)&SF_EVENT_FIRE));
    assert(sf_step(0)&SF_EVENT_FIRE);
    assert(active(G.shot_active,SF_PLAYER_BULLETS)==2);
    assert(G.shot_y[0]==G.ship_y-9-36&&G.shot_y[1]==G.ship_y-9); /* six pixels a tick */
    quiet();G.fire_clock=0;G.weapon=1;sf_step(0);
    assert(active(G.shot_active,SF_PLAYER_BULLETS)==2);
    assert(G.shot_dx[0]==0&&G.shot_dx[1]==0);
    quiet();G.fire_clock=0;G.weapon=2;sf_step(0);
    assert(active(G.shot_active,SF_PLAYER_BULLETS)==3);
    assert(G.shot_power[0]==2&&G.shot_dx[1]==-1&&G.shot_dx[2]==1);
    quiet();G.fire_clock=0;G.weapon=SF_MAX_WEAPON;sf_step(0);
    assert(active(G.shot_active,SF_PLAYER_BULLETS)==5);
    assert(G.shot_dx[3]==-2&&G.shot_dx[4]==2&&G.fire_clock==6);
    puts("auto-fire cadence and four weapon levels: pass");
}

static void test_hits_shield_ramming_and_game_over(void)
{
    sf_game snapshot;
    uint16_t events;
    quiet();G.weapon=2;
    incoming(5);events=sf_step(0);
    assert(!(events&SF_EVENT_HURT)&&G.hull==3); /* art edge misses core */
    incoming(4);events=sf_step(0);
    assert((events&SF_EVENT_HURT)&&G.hull==2&&G.weapon==1);
    assert(G.invulnerable==60);
    incoming(0);sf_step(0);assert(G.hull==2);
    assert(!G.bullet_active[0]);
    G.invulnerable=0;G.shield=1;incoming(0);sf_step(0);
    assert(!G.shield&&G.hull==2&&G.weapon==1);
    G.invulnerable=0;G.hull=1;incoming(0);events=sf_step(0);
    assert((events&SF_EVENT_OVER)&&G.game_over&&!G.hull);
    snapshot=G;assert(!sf_step(SF_IN_BOMB|SF_IN_LEFT));
    assert(!memcmp(&G,&snapshot,sizeof(G)));
    /* Ramming hurts the ship and destroys anything lighter than a heavy. */
    quiet();target(SF_SCOUT,1,G.ship_x+1,G.ship_y-1);
    events=sf_step(0);
    assert((events&SF_EVENT_HURT)&&(events&SF_EVENT_EXPLODE));
    assert(G.hull==2&&!G.enemy_active[0]&&G.kills==1);
    quiet();target(SF_HEAVY,10,G.ship_x,G.ship_y);
    events=sf_step(0);
    assert((events&SF_EVENT_HURT)&&G.enemy_active[0]&&G.hull==2);
    assert(!(sf_step(0)&SF_EVENT_HURT)); /* invulnerable after the hit */
    puts("tight hitbox, ramming, invulnerability, shield and game over: pass");
}

static void test_damage_chain_score_and_pickups(void)
{
    uint16_t events;
    quiet();G.drop_count=4;
    target(SF_SCOUT,1,121,80);shot(120,87,1);
    events=sf_step(0);
    assert((events&SF_EVENT_EXPLODE)&&!G.enemy_active[0]);
    assert(G.score==25&&G.kills==1&&!G.shot_active[0]);
    assert(G.chain==1&&G.chain_clock==SF_CHAIN_TICKS&&sf_multiplier()==1);
    /* Every fifth kill drops weapon, shield, weapon, bomb in turn. */
    assert(G.pickup_active[0]&&G.pickup_kind[0]==SF_UPGRADE&&G.drops==1);
    drop_at_ship(SF_UPGRADE);
    assert(sf_step(0)&SF_EVENT_PICKUP);
    assert(G.weapon==1&&G.score==75&&G.last_pickup==SF_UPGRADE);
    drop_at_ship(SF_SHIELD);sf_step(0);
    assert(G.shield&&G.score==125);
    drop_at_ship(SF_REPAIR);sf_step(0);
    assert(G.hull==3&&G.score==375); /* full hull converts to points */
    G.hull=2;drop_at_ship(SF_REPAIR);sf_step(0);
    assert(G.hull==3&&G.score==425);
    drop_at_ship(SF_BOMB);sf_step(0);
    assert(G.bombs==4&&G.score==475);
    /* At the widest weapon an upgrade becomes a wingman instead. */
    G.weapon=SF_MAX_WEAPON;drop_at_ship(SF_UPGRADE);sf_step(0);
    assert(G.weapon==SF_MAX_WEAPON&&G.score==525&&G.wing_active[0]);
    assert(G.last_pickup==SF_GOT_WINGMAN);G.wing_active[0]=0;
    /* A nearby pickup drifts towards the ship before it is collected. */
    G.pickup_active[0]=1;G.pickup_kind[0]=SF_SHIELD;
    G.pickup_x[0]=G.ship_x+30;G.pickup_y[0]=G.ship_y;sf_step(0);
    assert(G.pickup_active[0]&&G.pickup_x[0]==G.ship_x+29);
    G.pickup_active[0]=0;
    /* Heavies take sustained fire and leave a repair when the hull is low. */
    G.hull=2;G.chain_clock=0;
    target(SF_HEAVY,3,100,38);shot(100,44,2);events=sf_step(0);
    assert(G.enemy_active[0]&&G.enemy_hp[0]==1&&(events&SF_EVENT_HIT));
    shot(100,44,2);events=sf_step(0);
    assert(!G.enemy_active[0]&&(events&SF_EVENT_BIG)&&G.kills==2);
    assert(G.score==525+250&&G.pickup_active[0]&&G.pickup_kind[0]==SF_REPAIR);
    /* Quick kills build a chain; the fifth multiplies points by two. */
    G.pickup_active[0]=0;G.chain=4;G.chain_clock=3;
    target(SF_SCOUT,1,60,60);shot(60,67,1);sf_step(0);
    assert(G.chain==5&&sf_multiplier()==2&&G.score==775+50);
    G.chain=20;assert(sf_multiplier()==4);
    G.chain=5;G.chain_clock=1;sf_step(0);assert(!G.chain&&sf_multiplier()==1);
    G.chain=9;G.chain_clock=20;incoming(0);sf_step(0);
    assert(!G.chain&&!G.chain_clock); /* a hit breaks the chain */
    quiet();G.second=29;sf_step(0);assert(G.score==1&&!G.second);
    puts("damage, chain multiplier, drops and four pickup kinds: pass");
}

static void test_bombs(void)
{
    unsigned i;
    uint16_t events;
    quiet();target(SF_HEAVY,10,100,38);
    G.enemy_active[1]=1;G.enemy_kind[1]=SF_SCOUT;G.enemy_hp[1]=1;
    G.enemy_x[1]=30;G.enemy_y[1]=38;G.enemy_fire[1]=255;
    for(i=0;i<SF_ENEMY_BULLETS;++i) {
        G.bullet_active[i]=SF_SHOT_FAN;G.bullet_x[i]=30;G.bullet_y[i]=100;
    }
    events=sf_step(SF_IN_BOMB);
    assert((events&SF_EVENT_BOMB)&&(events&SF_EVENT_EXPLODE));
    assert(G.bombs==2&&G.enemy_hp[0]==3&&!G.enemy_active[1]);
    assert(!active(G.bullet_active,SF_ENEMY_BULLETS));
    assert(G.invulnerable==45);
    sf_step(SF_IN_BOMB);assert(G.bombs==2); /* held button is one bomb */
    sf_step(0);sf_step(SF_IN_BOMB);
    assert(G.bombs==1&&!G.enemy_active[0]);
    sf_step(0);sf_step(SF_IN_BOMB);assert(!G.bombs);
    sf_step(0);assert(!(sf_step(SF_IN_BOMB)&SF_EVENT_BOMB));
    /* Below capacity, a pickup replenishes without firing. */
    quiet();G.bombs=SF_MAX_BOMBS-1;drop_at_ship(SF_BOMB);events=sf_step(0);
    assert((events&SF_EVENT_PICKUP)&&!(events&SF_EVENT_BOMB)&&G.bombs==SF_MAX_BOMBS);
    /* At capacity it fires, clears shots and damages enemies. */
    target(SF_HEAVY,10,100,38);G.bullet_active[0]=SF_SHOT_FAN;
    G.bullet_x[0]=30;G.bullet_y[0]=100;G.bullet_dy[0]=1;
    drop_at_ship(SF_BOMB);events=sf_step(0);
    assert((events&SF_EVENT_PICKUP)&&(events&SF_EVENT_BOMB)&&G.bombs==SF_MAX_BOMBS);
    assert(G.enemy_hp[0]==3&&!active(G.bullet_active,SF_ENEMY_BULLETS)&&G.invulnerable==45);
    /* A manual bomb in the same step makes room; the pickup refills it. */
    quiet();G.bombs=SF_MAX_BOMBS;target(SF_HEAVY,20,100,38);
    drop_at_ship(SF_BOMB);events=sf_step(SF_IN_BOMB);
    assert((events&SF_EVENT_BOMB)&&G.bombs==SF_MAX_BOMBS&&G.enemy_hp[0]==13);
    /* A boss is scheduled after the tick chose PLAY; do not call BOSS yet. */
    quiet();G.bombs=SF_MAX_BOMBS;G.sector=3;G.sector_clock=SF_SECTOR_TICKS-1;
    drop_at_ship(SF_BOMB);events=sf_step(0);
    assert((events&SF_EVENT_BOMB)&&G.boss==1&&!G.boss_phase&&G.bombs==SF_MAX_BOMBS);
    puts("limited bombs, edge triggering, bullet clearing and heavy damage: pass");
}

static unsigned near_by(unsigned a,unsigned b,unsigned r)
{
    return a+r>=b&&a<=b+r;
}

static void test_wingmen_and_overdrive(void)
{
    unsigned i;
    uint16_t events;
    /* Upgrades past WIDE add a left wingman, a right one, then overdrive. */
    quiet();G.weapon=SF_MAX_WEAPON;
    drop_at_ship(SF_UPGRADE);sf_step(0);
    assert(G.wing_active[0]&&!G.wing_active[1]&&G.last_pickup==SF_GOT_WINGMAN);
    drop_at_ship(SF_UPGRADE);sf_step(0);
    assert(G.wing_active[1]&&!G.overdrive&&G.score==100);
    drop_at_ship(SF_UPGRADE);events=sf_step(0);
    assert((events&SF_EVENT_PICKUP)&&G.last_pickup==SF_GOT_OVERDRIVE);
    assert(!(events&SF_EVENT_TOP_CHAIN)); /* no chain yet */
    assert(G.overdrive==SF_OVERDRIVE_TICKS&&G.score==150);
    sf_step(0);assert(G.overdrive==SF_OVERDRIVE_TICKS-1);
    /* Wingmen trail the ship and settle twenty pixels to each side. */
    for(i=0;i<12;++i)sf_step(SF_IN_LEFT);
    for(i=0;i<12;++i)sf_step(0);
    assert(near_by(G.wing_x[0],G.ship_x-20,1)&&near_by(G.wing_x[1],G.ship_x+20,1));
    assert(near_by(G.wing_y[0],G.ship_y+5,1)&&near_by(G.wing_y[1],G.ship_y+5,1));
    for(i=0;i<60;++i)sf_step(SF_IN_LEFT);
    assert(G.ship_x==8&&near_by(G.wing_x[0],8,1)&&near_by(G.wing_x[1],28,1)); /* no wrap */
    for(i=0;i<80;++i)sf_step(SF_IN_RIGHT);
    assert(G.ship_x==SF_WIDTH-8&&near_by(G.wing_x[1],SF_WIDTH-8,1));
    /* Overdrive: seven shots, each one power stronger; wingmen fire ahead. */
    for(i=0;i<SF_PLAYER_BULLETS;++i)G.shot_active[i]=0;
    G.ship_x=120;for(i=0;i<20;++i)sf_step(0);
    for(i=0;i<SF_PLAYER_BULLETS;++i)G.shot_active[i]=0;
    G.fire_clock=0;assert(sf_step(0)&SF_EVENT_FIRE);
    assert(active(G.shot_active,SF_PLAYER_BULLETS)==7);
    assert(G.shot_power[0]==3&&G.shot_power[1]==2&&G.shot_power[4]==2);
    assert(G.shot_dx[5]==0&&G.shot_dx[6]==0&&near_by(G.shot_x[5],100,1)&&near_by(G.shot_x[6],140,1));
    assert(sf_multiplier()==2);G.chain=15;assert(sf_multiplier()==8);G.chain=0;
    /* The fifteenth chained kill in overdrive reaches x8 and reports it once. */
    for(i=0;i<SF_PLAYER_BULLETS;++i)G.shot_active[i]=0;
    G.fire_clock=255;G.chain=14;G.chain_clock=20;
    target(SF_SCOUT,1,60,80);shot(60,87,1);events=sf_step(0);
    assert((events&SF_EVENT_TOP_CHAIN)&&G.chain==15&&sf_multiplier()==8);
    target(SF_SCOUT,1,60,80);shot(60,87,1);events=sf_step(0);
    assert(!(events&SF_EVENT_TOP_CHAIN)&&G.chain==16&&!G.enemy_active[0]);
    G.chain=G.chain_clock=0;
    /* Overdrive shots pierce what they destroy and stop at what survives. */
    for(i=0;i<SF_PLAYER_BULLETS;++i)G.shot_active[i]=0;
    G.fire_clock=255;G.score=0;
    target(SF_SCOUT,1,60,80);shot(60,87,2);sf_step(0);
    assert(!G.enemy_active[0]&&G.shot_active[0]&&G.score==50); /* doubled */
    target(SF_HEAVY,10,60,60);sf_step(0);sf_step(0);
    assert(G.enemy_active[0]&&G.enemy_hp[0]==8&&!G.shot_active[0]);
    G.enemy_active[0]=0;G.overdrive=0;
    target(SF_SCOUT,1,60,80);shot(60,87,1);sf_step(0);
    assert(!G.enemy_active[0]&&!G.shot_active[0]);
    /* A wingman stops a bullet and is lost; the ship is untouched. */
    G.bullet_active[0]=SF_SHOT_ORB;G.bullet_x[0]=G.wing_x[0];G.bullet_y[0]=(uint8_t)(G.wing_y[0]-2);
    G.bullet_dx[0]=0;G.bullet_dy[0]=2;events=sf_step(0);
    assert((events&SF_EVENT_WINGMAN_LOST)&&!G.wing_active[0]&&G.wing_active[1]);
    assert(!G.bullet_active[0]&&G.hull==3&&!(events&SF_EVENT_HURT));
    /* The next upgrade replaces it; a hit ends overdrive but keeps wingmen. */
    drop_at_ship(SF_UPGRADE);sf_step(0);
    assert(G.wing_active[0]&&G.last_pickup==SF_GOT_WINGMAN);
    G.overdrive=100;incoming(0);events=sf_step(0);
    assert((events&SF_EVENT_HURT)&&!G.overdrive&&G.weapon==SF_MAX_WEAPON-1);
    assert(G.wing_active[0]&&G.wing_active[1]);
    /* Overdrive that starts during a fifteen-kill chain also reaches x8,
     * and another P while there reports nothing new. */
    G.weapon=SF_MAX_WEAPON;G.chain=15;G.chain_clock=20;
    drop_at_ship(SF_UPGRADE);events=sf_step(0);
    assert((events&SF_EVENT_TOP_CHAIN)&&G.last_pickup==SF_GOT_OVERDRIVE&&sf_multiplier()==8);
    drop_at_ship(SF_UPGRADE);events=sf_step(0);
    assert((events&SF_EVENT_PICKUP)&&!(events&SF_EVENT_TOP_CHAIN));
    puts("wingmen, bullet blocking, overdrive power, piercing and double points: pass");
}

static void test_five_enemy_behaviors(void)
{
    unsigned i;
    quiet();target(SF_SCOUT,1,100,40);
    for(i=0;i<12;++i)sf_step(0);
    assert(G.enemy_x[0]<100&&G.enemy_y[0]==52);
    for(i=0;i<12;++i)sf_step(0);
    assert(G.enemy_x[0]==100&&G.enemy_y[0]==64);
    assert(!active(G.bullet_active,SF_ENEMY_BULLETS)); /* level 0 scouts hold fire */
    quiet();G.level=5;target(SF_SCOUT,1,100,40);G.enemy_fire[0]=1;
    assert(sf_step(0)&SF_EVENT_SHOT);
    assert(G.bullet_active[0]==SF_SHOT_ORB&&G.enemy_fire[0]==255);
    quiet();target(SF_DART,2,100,40);sf_step(0);
    assert(G.enemy_x[0]==101&&G.enemy_y[0]==43);
    quiet();G.ship_x=200;target(SF_GUNSHIP,4,100,52);
    G.enemy_fire[0]=1;assert(sf_step(0)&SF_EVENT_SHOT);
    assert(G.enemy_y[0]==52&&G.bullet_dx[0]>0&&G.bullet_dy[0]==2);
    assert(G.bullet_active[0]==SF_SHOT_ORB&&G.enemy_fire[0]==64);
    quiet();target(SF_HEAVY,10,100,38);G.enemy_fire[0]=1;
    assert(sf_step(0)&SF_EVENT_SHOT);
    assert(active(G.bullet_active,SF_ENEMY_BULLETS)==3);
    assert(G.bullet_dx[0]==-1&&G.bullet_dx[2]==1&&G.bullet_active[1]==SF_SHOT_FAN);
    quiet();G.level=8;target(SF_HEAVY,10,100,38);G.enemy_fire[0]=1;sf_step(0);
    assert(active(G.bullet_active,SF_ENEMY_BULLETS)==5);
    assert(G.bullet_dx[0]==-2&&G.bullet_dx[4]==2&&G.enemy_fire[0]==77-20);
    quiet();target(SF_SWEEPER,3,229,40);sf_step(0);
    assert(G.enemy_dx[0]==-1&&G.enemy_x[0]==230);
    sf_step(0);assert(G.enemy_x[0]==228&&G.enemy_y[0]==41);
    G.enemy_fire[0]=1;sf_step(0);
    assert(G.bullet_active[0]==SF_SHOT_NEEDLE&&G.bullet_dx[0]==0&&G.bullet_dy[0]==3);
    puts("scout weave, dart dive, gunship aim, heavy fans, sweeper needles: pass");
}

static void test_sectors(void)
{
    uint16_t events;
    quiet();G.sector_clock=SF_SECTOR_TICKS-2;
    assert(!(sf_step(0)&SF_EVENT_SECTOR)&&!G.sector);
    events=sf_step(0);
    assert((events&SF_EVENT_SECTOR)&&G.sector==1&&G.level==0);
    assert(G.score==100&&G.spawn_clock>=75&&!G.sector_clock);
    /* Three levels each four sectors: the twentieth sector plays level 14 and
     * the next, after the fourth boss, the last. No bosses here. */
    G.bosses=SF_BOSS_COUNT;
    G.sector=6;G.sector_clock=SF_SECTOR_TICKS-1;sf_step(0);assert(G.sector==7&&G.level==5);
    G.sector=18;G.sector_clock=SF_SECTOR_TICKS-1;sf_step(0);assert(G.sector==19&&G.level==14);
    G.sector_clock=SF_SECTOR_TICKS-1;sf_step(0);assert(G.sector==20&&G.level==SF_LAST_LEVEL);
    G.sector=98;G.sector_clock=SF_SECTOR_TICKS-1;sf_step(0);
    assert(G.sector==98&&G.level==SF_LAST_LEVEL);
    quiet();G.spawn_clock=1;sf_step(0);assert(G.spawn_clock==53);
    quiet();G.level=13;G.spawn_clock=1;sf_step(0);assert(G.spawn_clock==22);
    quiet();G.level=14;G.spawn_clock=1;sf_step(0);assert(G.spawn_clock==19);
    quiet();G.level=SF_LAST_LEVEL;G.spawn_clock=1;sf_step(0);assert(G.spawn_clock==19);
    puts("24-second sectors, a ramp to the last level after the fourth boss, bonuses, breathers and spawn pacing: pass");
}

static uint8_t boss_top(void) { return (uint8_t)(G.boss_y-sf_boss.height); }
static uint8_t muzzle_x(unsigned part)
{ return (uint8_t)(G.boss_x+sf_boss.hit_x[part]+sf_boss.hit_w[part]/2); }
static void clear_shots(void)
{
    memset(G.bullet_active,0,sizeof(G.bullet_active));
    memset(G.shot_active,0,sizeof(G.shot_active));
}
/* End the sector before boss n (1..5) and step until it fights. */
static void boss_fight(unsigned n)
{
    uint16_t events;
    quiet();G.bosses=(uint8_t)(n-1);G.sector=(uint8_t)(SF_BOSS_EVERY*n-2);
    G.sector_clock=SF_SECTOR_TICKS-1;G.invulnerable=255;
    events=sf_step(0);
    assert((events&SF_EVENT_BOSS)&&(events&SF_EVENT_SECTOR)&&G.boss==n);
    assert(G.sector==SF_BOSS_EVERY*n-1&&!G.sector_clock);
    while(G.boss_phase!=SF_BOSS_FIGHT)sf_step(0);
    clear_shots();G.invulnerable=0;
}

static void test_bosses(void)
{
    static const uint16_t full[SF_BOSS_COUNT]={140,168,196,224,264};
    uint16_t events;
    unsigned i,x,y,steps,before;
    /* Sector 5 is the first boss's. The boss enters from the top for its
     * height and eight lines more, and the sector has no clock. */
    quiet();G.sector=3;G.sector_clock=SF_SECTOR_TICKS-1;
    events=sf_step(0);
    assert((events&SF_EVENT_BOSS)&&(events&SF_EVENT_SECTOR)&&G.boss==1&&G.sector==4);
    sf_step(0);
    assert(G.boss_phase==SF_BOSS_ENTER&&G.boss_y==SF_TOP&&G.boss_full==140);
    assert(G.part_hp[0]==40&&G.part_hp[1]==40&&G.part_hp[2]==60&&!(G.boss_x&1));
    for(steps=0;G.boss_phase==SF_BOSS_ENTER;++steps)sf_step(0);
    assert(steps==sf_boss.height+8u&&G.boss_y==SF_TOP+sf_boss.height+8u&&!G.sector_clock);
    for(i=1;i<=SF_BOSS_COUNT;++i){boss_fight(i);assert(G.boss_full==full[i-1]);}

    /* Manta's wing laser: three 12-line segments 16 lines apart, straight
     * down at eleven lines a step. A segment reaches ten lines from the core;
     * an orb only four. */
    boss_fight(1);G.part_fire[0]=0;G.part_fire[1]=G.part_fire[2]=200;
    sf_step(0);
    assert(active(G.bullet_active,SF_ENEMY_BULLETS)==3);
    for(i=0;i<3;++i)
        assert(G.bullet_active[i]==SF_SHOT_LASER&&G.bullet_dy[i]==11&&!G.bullet_dx[i]&&G.bullet_x[i]==muzzle_x(0));
    assert(G.bullet_y[1]==G.bullet_y[0]+16&&G.bullet_y[2]==G.bullet_y[1]+16);
    clear_shots();G.bullet_active[0]=SF_SHOT_LASER;G.bullet_x[0]=G.ship_x;
    G.bullet_y[0]=(uint8_t)(G.ship_y-18);G.bullet_dx[0]=0;G.bullet_dy[0]=8;
    assert(sf_step(0)&SF_EVENT_HURT);
    clear_shots();G.invulnerable=0;incoming(0);G.bullet_y[0]=(uint8_t)(G.ship_y-10);
    G.bullet_dy[0]=2;assert(!(sf_step(0)&SF_EVENT_HURT));

    /* Shots: an emplacement takes damage, the hull stops a shot, a gap
     * beside a strip lets it through. The boss moves after the shots. */
    boss_fight(1);
    x=muzzle_x(2);y=(uint8_t)(boss_top()+sf_boss.hit_y[2]+sf_boss.hit_h[2]/2);
    shot(x,y+6,1);events=sf_step(0);
    assert(G.part_hp[2]==59&&!G.shot_active[0]&&(events&SF_EVENT_HIT));
    clear_shots();
    x=(uint8_t)(G.boss_x+sf_boss.band_x[1]+1);y=(uint8_t)(boss_top()+9);
    shot(x,y+6,1);sf_step(0);
    assert(!G.shot_active[0]&&G.part_hp[0]==40&&G.part_hp[1]==40&&G.part_hp[2]==59);
    clear_shots();x=(uint8_t)(G.boss_x+sf_boss.band_x[1]-4);
    shot(x,y+6,1);sf_step(0);assert(G.shot_active[0]);
    /* Below an emplacement, the hull lets a shot through to it. */
    clear_shots();x=muzzle_x(2);y=(uint8_t)(boss_top()+sf_boss.height-1);
    shot(x,y+6,1);sf_step(0);
    assert(G.shot_active[0]&&G.part_hp[2]==59);
    for(i=0;i<4&&G.shot_active[0];++i)sf_step(0);
    assert(!G.shot_active[0]&&G.part_hp[2]==58);

    /* A bomb takes seven from each emplacement. */
    boss_fight(2);G.bombs=1;sf_step(SF_IN_BOMB);
    assert(G.part_hp[0]==41&&G.part_hp[1]==41&&G.part_hp[2]==65&&!G.bombs);
    boss_fight(2);G.bombs=SF_MAX_BOMBS;drop_at_ship(SF_BOMB);events=sf_step(0);
    assert((events&SF_EVENT_PICKUP)&&(events&SF_EVENT_BOMB)&&G.bombs==SF_MAX_BOMBS);
    assert(G.part_hp[0]==41&&G.part_hp[1]==41&&G.part_hp[2]==65);

    /* The hull hurts the ship's core. */
    boss_fight(1);G.ship_x=(uint8_t)(G.boss_x+sf_boss.band_x[5]+12);G.ship_y=(uint8_t)(boss_top()+44);
    assert(sf_step(0)&SF_EVENT_HURT);

    /* Destroyed emplacements drop pickups and score; when the last falls,
     * the boss burns for 75 steps and the next sector starts with its bonus
     * and the boss's. */
    boss_fight(1);G.invulnerable=255;G.part_fire[0]=G.part_fire[1]=G.part_fire[2]=255;
    before=(unsigned)G.score;G.part_hp[2]=1;
    shot(muzzle_x(2),(uint8_t)(boss_top()+sf_boss.hit_y[2]+sf_boss.hit_h[2]/2+6),1);
    events=sf_step(0);
    assert(!G.part_hp[2]&&(events&SF_EVENT_BIG)&&active(G.pickup_active,SF_PICKUPS)==1);
    assert(G.score>=before+500&&G.boss_phase==SF_BOSS_FIGHT);
    G.part_hp[0]=G.part_hp[1]=1;G.bombs=1;sf_step(SF_IN_BOMB);
    assert(G.boss_phase==SF_BOSS_DYING&&G.boss_clock==74);
    before=(unsigned)G.score;
    for(steps=1;!((events=sf_step(0))&SF_EVENT_BOSS_DOWN);++steps)assert(G.boss==1);
    assert(steps==74&&(events&SF_EVENT_SECTOR)&&!G.boss&&G.bosses==1&&G.sector==5&&G.level==3);
    assert(G.score>=before+2000+500);

    /* The other weapons: aimed orbs, needle streams, slow mines, missiles
     * that dive from the pods, and fans. */
    boss_fight(2);G.part_fire[0]=0;G.part_fire[1]=G.part_fire[2]=200;sf_step(0);
    assert(active(G.bullet_active,SF_ENEMY_BULLETS)==1&&G.bullet_active[0]==SF_SHOT_ORB&&G.bullet_dy[0]==4);
    boss_fight(3);G.part_fire[0]=0;G.part_fire[1]=G.part_fire[2]=200;sf_step(0);
    assert(G.bullet_active[0]==SF_SHOT_NEEDLE&&G.bullet_dy[0]==6&&G.bullet_x[0]==muzzle_x(0));
    clear_shots();G.part_fire[2]=0;G.part_fire[0]=200;sf_step(0);
    assert(G.bullet_active[0]==SF_SHOT_ORB&&(G.bullet_dy[0]==1||G.bullet_dy[0]==2));
    boss_fight(4);G.part_fire[0]=0;G.part_fire[1]=G.part_fire[2]=200;
    memset(G.enemy_active,0,sizeof(G.enemy_active));sf_step(0);
    assert(G.enemy_active[0]&&G.enemy_kind[0]==SF_DART);
    assert(G.enemy_y[0]==(uint8_t)(boss_top()+sf_boss.hit_y[0]+sf_boss.hit_h[0]));
    boss_fight(5);G.part_fire[0]=0;G.part_fire[1]=G.part_fire[2]=200;sf_step(0);
    assert(active(G.bullet_active,SF_ENEMY_BULLETS)==5&&G.bullet_active[0]==SF_SHOT_FAN&&G.bullet_dy[0]==3);

    /* The railgun charges for 40 steps with its column shown and the boss
     * still, then fires a slug at 34 lines a step. The slug hits a core on
     * its path between two positions; a core six pixels aside is safe. */
    for(i=0;i<2;++i) {
        boss_fight(5);G.part_fire[0]=G.part_fire[1]=255;G.part_fire[2]=0;
        sf_step(0);
        assert(G.rail_clock==40&&G.rail_x==(muzzle_x(2)&~1));
        x=G.boss_x;G.ship_x=(uint8_t)(G.rail_x+(i?6:0));
        for(steps=0;G.rail_clock;++steps){sf_step(0);assert(G.boss_x==x);}
        assert(steps==40&&G.bullet_active[0]==SF_SHOT_RAIL&&G.bullet_dy[0]==34);
        for(events=0,steps=0;steps<8&&G.bullet_active[0];++steps)events|=sf_step(0);
        assert(i?!(events&SF_EVENT_HURT):(events&SF_EVENT_HURT)!=0);
    }

    /* Boss sectors bring a line of three scouts each five seconds, and each
     * third kill drops a pickup. */
    boss_fight(1);G.spawn_clock=1;sf_step(0);
    assert(active(G.enemy_active,SF_ENEMIES)==3&&G.spawn_clock==150);
    boss_fight(1);G.part_fire[0]=G.part_fire[1]=G.part_fire[2]=255;
    for(i=0;i<3;++i) {
        memset(G.enemy_active,0,sizeof(G.enemy_active));target(SF_SCOUT,1,200,170);
        shot(200,176,1);sf_step(0);
        assert(active(G.pickup_active,SF_PICKUPS)==(i==2));
    }

    /* After the fifth boss, sectors follow each other without bosses. */
    quiet();G.bosses=SF_BOSS_COUNT;G.sector=29;G.sector_clock=SF_SECTOR_TICKS-1;
    events=sf_step(0);
    assert((events&SF_EVENT_SECTOR)&&!(events&SF_EVENT_BOSS)&&!G.boss&&G.sector==30);
    /* The fourth boss's sector, 20, plays level 14; the sector after it
     * plays the last level. */
    quiet();G.bosses=3;G.sector=18;G.sector_clock=SF_SECTOR_TICKS-1;
    assert(sf_step(0)&SF_EVENT_BOSS);assert(G.boss==4&&G.sector==19&&G.level==14);
    G.invulnerable=255;sf_step(0);G.part_hp[0]=G.part_hp[1]=G.part_hp[2]=0;G.boss_phase=SF_BOSS_DYING;
    G.boss_clock=1;sf_step(0);assert(!G.boss&&G.bosses==4&&G.sector==20&&G.level==SF_LAST_LEVEL);
    /* The title's cheat: the first step enters the chosen sector, with its
     * boss when it has one, and the ship has everything. */
    for(i=1;i<=99;++i) {
        quiet();sf_begin((uint8_t)i);
        assert(G.weapon==SF_MAX_WEAPON&&G.wing_active[0]&&G.wing_active[1]&&G.shield&&G.bombs==SF_MAX_BOMBS);
        sf_step(0);
        assert(G.sector==i-1&&G.hull==SF_MAX_HULL);
        assert(G.boss==(i%5||i>25?0:i/5)&&G.bosses==(i>25?5:(i-1)/5));
        assert(G.level==(i>20?SF_LAST_LEVEL:(i-1)*3/4));
    }
    puts("boss sectors, entry, lasers, railgun, hull, emplacements, bombs, drops and light waves: pass");
}

/* An invulnerable ship with the widest gun and both wingmen sits below an
 * intact emplacement of each boss in turn. Two copies run the same steps. */
static void test_boss_marathon(void)
{
    static sf_game a,b;
    unsigned i,j,start=0,longest=0,part,target_x;
    uint16_t ea,eb;
    uint8_t input=0;
    quiet();G.sector=SF_BOSS_EVERY-2;G.sector_clock=SF_SECTOR_TICKS-1;
    G.weapon=SF_MAX_WEAPON;G.wing_active[0]=G.wing_active[1]=1;a=G;b=G;
    for(i=0;i<60000&&a.bosses<SF_BOSS_COUNT;++i) {
        G=a;G.invulnerable=255;G.weapon=SF_MAX_WEAPON;G.wing_active[0]=G.wing_active[1]=1;
        ea=sf_step(input);a=G;
        G=b;G.invulnerable=255;G.weapon=SF_MAX_WEAPON;G.wing_active[0]=G.wing_active[1]=1;
        eb=sf_step(input);b=G;
        assert(ea==eb&&!memcmp(&a,&b,sizeof(sf_game)));
        for(j=0;j<SF_ENEMY_BULLETS;++j)if(G.bullet_active[j])
            assert(G.bullet_active[j]<=SF_SHOT_RAIL&&G.bullet_x[j]<SF_WIDTH);
        assert(active(G.enemy_active,SF_ENEMIES)<=SF_ENEMIES&&G.level<=SF_LAST_LEVEL);
        if(ea&SF_EVENT_BOSS)start=i;
        if(ea&SF_EVENT_BOSS_DOWN) {
            printf("boss %u down after %u s\n",(unsigned)a.bosses,(i-start)/30);
            if(i-start>longest)longest=i-start;
            /* The next boss comes after five sectors; skip to it. */
            G=a;G.sector=(uint8_t)(SF_BOSS_EVERY*(G.bosses+1)-2);G.sector_clock=SF_SECTOR_TICKS-1;a=b=G;
        }
        input=0;
        if(G.boss&&G.boss_phase==SF_BOSS_FIGHT) {
            for(part=0;part<3&&!G.part_hp[part];++part){}
            if(part<3) {
                target_x=muzzle_x(part);
                if(G.ship_x+2u<target_x)input=SF_IN_RIGHT;
                else if(G.ship_x>target_x+2u)input=SF_IN_LEFT;
            }
        }
    }
    assert(a.bosses==SF_BOSS_COUNT&&longest<120*30);
    printf("five bosses destroyed in %u deterministic steps, the longest in %u s: pass\n",i,longest/30);
}

/* Trigger many waves at one level and report the enemy kinds they added.
 * Each new enemy starts with its kind's hit points. */
static unsigned wave_mix(unsigned level,unsigned waves,unsigned counts[5],unsigned keep_heavies)
{
    static const uint8_t spawn_hp[5]={1,2,6,15,3};
    unsigned i,j,max_heavies=0,heavies;
    memset(counts,0,5*sizeof(counts[0]));
    sf_new((uint16_t)(level*977+13));G.level=(uint8_t)level;G.fire_clock=255;
    for(i=0;i<waves;++i) {
        G.spawn_clock=1;G.invulnerable=255;G.sector_clock=0;G.fire_clock=255;
        for(j=0;j<SF_ENEMIES;++j)
            if(!keep_heavies||G.enemy_kind[j]!=SF_HEAVY)G.enemy_active[j]=0;
        for(j=0;j<SF_ENEMY_BULLETS;++j)G.bullet_active[j]=0;
        sf_step(0);
        for(heavies=j=0;j<SF_ENEMIES;++j)if(G.enemy_active[j]) {
            if(!G.enemy_age[j]) { /* spawned this step */
                ++counts[G.enemy_kind[j]];
                assert(G.enemy_hp[j]==spawn_hp[G.enemy_kind[j]]);
            }
            if(G.enemy_kind[j]==SF_HEAVY)++heavies;
            /* Keep survivors in view so a capped heavy stays alive. */
            G.enemy_y[j]=40;
        }
        if(heavies>max_heavies)max_heavies=heavies;
    }
    return max_heavies;
}

static void test_enemy_roster_unlocks_slowly(void)
{
    unsigned c[5],level,cap,peak;
    wave_mix(0,400,c,0);
    assert(c[SF_SCOUT]&&!c[SF_DART]&&!c[SF_GUNSHIP]&&!c[SF_SWEEPER]&&!c[SF_HEAVY]);
    wave_mix(1,400,c,0);
    assert(c[SF_SCOUT]&&c[SF_DART]&&!c[SF_GUNSHIP]&&!c[SF_SWEEPER]&&!c[SF_HEAVY]);
    wave_mix(2,400,c,0);
    assert(c[SF_GUNSHIP]&&!c[SF_SWEEPER]&&!c[SF_HEAVY]);
    wave_mix(3,400,c,0);
    assert(c[SF_SWEEPER]&&!c[SF_HEAVY]);
    /* Heavies arrive at level 4 in about one wave of sixteen. */
    wave_mix(4,1600,c,0);
    printf("level 4 heavy waves: %u of 1600\n",c[SF_HEAVY]);
    assert(c[SF_HEAVY]>=60&&c[SF_HEAVY]<=150);
    for(level=4;level<=SF_LAST_LEVEL;++level) {
        cap=1+(level>=9)+(level>=13);
        peak=wave_mix(level,800,c,1);
        assert(peak==cap);
    }
    puts("roster unlocks by sector and heavy wide-shot ships are capped: pass");
}

/* Heavies need level 4, first reached in this zero-based sector. */
#define HEAVY_SECTOR 6
static void test_determinism_and_pool_limits(void)
{
    static sf_game a,b;
    unsigned i,j,types=0,max_enemies=0,max_shots=0,first_heavy=0,heavies,fans_early=0;
    unsigned wing_ticks=0,drive_ticks=0;
    uint8_t input;
    uint16_t ea,eb;
    /* Normal sectors only; test_boss_marathon covers the bosses. */
    sf_new(77);G.bosses=SF_BOSS_COUNT;a=G;b=G;
    for(i=0;i<20000;++i) {
        unsigned enemies=0,shots;
        input=(i/90)&1?SF_IN_LEFT:SF_IN_RIGHT;
        if(i%607==0)input|=SF_IN_BOMB;
        G=a;G.invulnerable=255;ea=sf_step(input);a=G;
        G=b;G.invulnerable=255;eb=sf_step(input);b=G;
        assert(ea==eb&&!memcmp(&a,&b,sizeof(sf_game)));
        assert(G.level<=SF_LAST_LEVEL&&G.weapon<=SF_MAX_WEAPON&&G.bombs<=SF_MAX_BOMBS);
        assert(G.hull==3&&!G.game_over&&G.tick==i+1);
        for(heavies=j=0;j<SF_ENEMIES;++j)if(G.enemy_active[j]) {
            ++enemies;types|=1U<<G.enemy_kind[j];
            assert(G.enemy_kind[j]<=SF_SWEEPER&&G.enemy_hp[j]>0);
            assert(G.enemy_x[j]>=8&&G.enemy_x[j]<=SF_WIDTH-8);
            assert(G.enemy_y[j]>=8&&G.enemy_y[j]<=SF_BOTTOM+12);
            if(G.enemy_kind[j]==SF_HEAVY)++heavies;
        }
        if(heavies&&!first_heavy)first_heavy=i+1;
        assert(heavies<=1U+(G.level>=9)+(G.level>=13));
        for(j=0;j<SF_ENEMY_BULLETS;++j)if(G.bullet_active[j]) {
            assert(G.bullet_active[j]<=SF_SHOT_NEEDLE&&G.bullet_x[j]<SF_WIDTH);
            if(G.bullet_active[j]==SF_SHOT_FAN&&i<HEAVY_SECTOR*SF_SECTOR_TICKS)++fans_early;
        }
        for(j=0;j<SF_PICKUPS;++j)if(G.pickup_active[j])assert(G.pickup_kind[j]<=SF_BOMB);
        assert(G.overdrive<=SF_OVERDRIVE_TICKS);
        drive_ticks+=G.overdrive!=0;
        for(j=0;j<SF_WINGMEN;++j)if(G.wing_active[j]) {
            ++wing_ticks;
            assert(G.wing_x[j]>=8&&G.wing_x[j]<=SF_WIDTH-8&&G.wing_y[j]<=SF_BOTTOM);
        }
        assert(enemies<=SF_ENEMIES);
        shots=active(G.bullet_active,SF_ENEMY_BULLETS);
        assert(active(G.shot_active,SF_PLAYER_BULLETS)<=SF_PLAYER_BULLETS);
        if(enemies>max_enemies)max_enemies=enemies;
        if(shots>max_shots)max_shots=shots;
    }
    assert(types==31&&G.level==SF_LAST_LEVEL);
    assert(first_heavy>HEAVY_SECTOR*SF_SECTOR_TICKS&&!fans_early);
    assert(max_enemies>=8&&max_shots>=20&&wing_ticks&&drive_ticks);
    printf("20,000 deterministic ticks, five types, bounded pools: pass "
           "(%u enemies, %u hostile shots peak; first heavy at %u s)\n",
           max_enemies,max_shots,first_heavy/30);
}

/* A player model for difficulty: it dodges by looking ahead at bullets and
 * aircraft, chases the lowest enemy and pickups, and bombs when cornered. It
 * sees the state eight ticks (267 ms) late and decides every fourth tick. */
static const int8_t bot_dx[9]={0,0,0,-3,3,-3,3,-3,3},bot_dy[9]={0,-3,3,0,0,-3,-3,3,3};
static const uint8_t bot_move[9]={0,SF_IN_UP,SF_IN_DOWN,SF_IN_LEFT,SF_IN_RIGHT,
    SF_IN_UP|SF_IN_LEFT,SF_IN_UP|SF_IN_RIGHT,SF_IN_DOWN|SF_IN_LEFT,SF_IN_DOWN|SF_IN_RIGHT};
static int clamp(int v,int low,int high) { return v<low?low:v>high?high:v; }
static int distance(int a,int b) { return a<b?b-a:a-b; }
static uint8_t bot_input(const sf_game *seen)
{
    unsigned m,i,k,best=0;
    long danger,score,lowest_score=0x7FFFFFFFL;
    int x,y,target_x=G.ship_x,lowest=-1;
    for(i=0;i<SF_ENEMIES;++i)if(seen->enemy_active[i]&&seen->enemy_y[i]<G.ship_y-30&&seen->enemy_y[i]>lowest)
        {lowest=seen->enemy_y[i];target_x=seen->enemy_x[i];}
    for(i=0;i<SF_PICKUPS;++i)if(seen->pickup_active[i])target_x=seen->pickup_x[i];
    for(m=0;m<9;++m) {
        danger=0;
        for(k=1;k<=10;++k) {
            x=clamp(G.ship_x+bot_dx[m]*(int)(k<4?k:4),8,SF_WIDTH-8);
            y=clamp(G.ship_y+bot_dy[m]*(int)(k<4?k:4),SF_TOP+10,SF_BOTTOM-9);
            for(i=0;i<SF_ENEMY_BULLETS;++i)if(seen->bullet_active[i]) {
                int ex=distance(seen->bullet_x[i]+seen->bullet_dx[i]*(int)k,x);
                int ey=distance(seen->bullet_y[i]+seen->bullet_dy[i]*(int)k,y);
                if(ex<=6&&ey<=6)danger+=20000/k;else if(ex<=10&&ey<=10)danger+=2000/k;
            }
            if(k<=8)for(i=0;i<SF_ENEMIES;++i)if(seen->enemy_active[i]) {
                int r=seen->enemy_kind[i]==SF_HEAVY?14:10;
                int ey=seen->enemy_y[i]+(seen->enemy_kind[i]==SF_DART?3:1)*(int)k;
                if(distance(seen->enemy_x[i],x)<=r&&distance(ey,y)<=r)danger+=16000/k;
            }
        }
        x=clamp(G.ship_x+bot_dx[m],8,SF_WIDTH-8);y=clamp(G.ship_y+bot_dy[m],SF_TOP+10,SF_BOTTOM-9);
        score=danger+10*distance(x,target_x)+6*distance(y,165);
        if(score<lowest_score){lowest_score=score;best=m;}
    }
    return (uint8_t)(bot_move[best]|(lowest_score>16000&&G.bombs&&!G.invulnerable?SF_IN_BOMB:0));
}

static void test_reaction_bot(void)
{
    static sf_game history[16];
    unsigned seed,ticks,total=0,least=0xFFFFFFFFU,hits=0,early=0;
    uint8_t input;
    for(seed=1;seed<=16;++seed) {
        sf_new((uint16_t)(seed*7919));input=0;
        for(ticks=0;!G.game_over&&ticks<36000;++ticks) {
            history[ticks&15]=G;
            if(ticks>=8&&!(ticks&3))input=bot_input(&history[(ticks-8)&15]);
            if(sf_step(input)&SF_EVENT_HURT){++hits;if(ticks<5400)++early;}
        }
        if(ticks<least)least=ticks;
        total+=ticks;
    }
    printf("reaction bot lasts %u s at least, %u s on average over sixteen seeds; "
           "%.2f hits a minute, %.2f in the first three\n",least/30,total/480,
           hits*1800.0/total,early/16.0);
    /* The ramp reaches its last level after the fourth boss. The bot does
     * not aim at bosses, and it averages about seven minutes. */
    assert(total/480>=120&&total/480<=900);
    puts("an active player model is challenged within minutes: pass");
}

/* Without input or forced invulnerability, record how long the ship lasts. */
static void test_passive_survival(void)
{
    unsigned seed,least=0xFFFF,total=0,ticks;
    for(seed=1;seed<=8;++seed) {
        sf_new((uint16_t)(seed*7919));
        for(ticks=0;!G.game_over&&ticks<54000;++ticks)sf_step(0);
        if(ticks<least)least=ticks;
        total+=ticks;
    }
    printf("passive ship lasts %u s at least, %u s on average over eight seeds\n",
           least/30,total/240);
    assert(least>=45*30);
    puts("opening sectors stay gentle for an idle ship: pass");
}

int main(void)
{
    test_start_movement_and_restart();test_autofire();
    test_hits_shield_ramming_and_game_over();test_damage_chain_score_and_pickups();
    test_bombs();test_wingmen_and_overdrive();test_five_enemy_behaviors();test_sectors();
    test_bosses();test_boss_marathon();
    test_enemy_roster_unlocks_slowly();test_determinism_and_pool_limits();
    test_passive_survival();test_reaction_bot();
    printf("STARFALL portable core: all checks passed; state %u bytes\n",
           (unsigned)sizeof(sf_game));
    return 0;
}
