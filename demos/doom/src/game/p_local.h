/* Doom for the Appletini -- the play simulation's shared definitions
 * (docs/DESIGN.md section 9).
 *
 * This is vanilla Doom's p_local.h, p_mobj.h, d_player.h and r_defs.h in
 * one, reshaped for a 6502 with 46 KB of near memory (RamWorks bank 1,
 * the GAME space) and the level data in far banks:
 *
 *  - Map data stays in the converter's far arrays (section 6). The game
 *    reads it through the accessors of p_setup.c: near mirrors of the
 *    sector heights and specials (written through to far memory, where
 *    the renderer reads them), and small caches of the records the hot
 *    paths read (lines, nodes, subsectors, blockmap cells). A line_t here
 *    is a cached copy, valid until the next P_Line() of a line that maps
 *    to the same cache slot (LINECACHE_SIZE): code that calls out between
 *    reading a line and using it keeps the line's index, not the pointer.
 *
 *  - Things come in two representations sharing the blockmap chains:
 *    mobj_t "actors" (vanilla's mobj_t: everything that moves, fights or
 *    thinks) and sobj_t "statics", 16 bytes (pickups, decorations,
 *    corpses, barrels and dormant monsters: things that at most animate).
 *    A static becomes an actor when something acts on it (P_WakeStatic:
 *    damage, telefrag, a dormant monster's look that may succeed); an
 *    actor that has settled into a static-only life becomes a static
 *    again (P_MobjThinker). Code that walks the blockmap gets both kinds
 *    (IS_STATIC tells them apart) -- see P_BlockThingsIterator.
 *
 *  - References between mobjs are pointers (2 bytes on the 6502, the same
 *    as an index and cheaper to follow).
 */
#ifndef P_LOCAL_H
#define P_LOCAL_H

#include "doomtype.h"
#include "info.h"
#include "kernel.h"

/* --- constants (vanilla p_local.h) ----------------------------------------- */
#define FLOATSPEED      (FRACUNIT * 4)
#define MAXHEALTH       100
#define VIEWHEIGHT      (41 * FRACUNIT)
#define MAPBLOCKUNITS   128
#define MAPBLOCKSHIFT   (FRACBITS + 7)
#define MAPBTOFRAC      (MAPBLOCKSHIFT - FRACBITS)
#define PLAYERRADIUS    16
#define MAXRADIUS       32              /* map units */
#define GRAVITY         FRACUNIT
#define MAXMOVE         (30 * FRACUNIT)
#define USERANGE        (64 * FRACUNIT)
#define MELEERANGE      (64 * FRACUNIT)
#define MISSILERANGE    (32 * 64 * FRACUNIT)
#define BASETHRESHOLD   100
#define ONFLOORZ        MININT
#define ONCEILINGZ      MAXINT
#define TICRATE         35

enum { BOXTOP, BOXBOTTOM, BOXLEFT, BOXRIGHT };
enum { ST_HORIZONTAL, ST_VERTICAL, ST_POSITIVE, ST_NEGATIVE };

/* linedef flags (low byte of vanilla's ML_ word, which is all the game reads) */
#define ML_BLOCKING      1
#define ML_BLOCKMONSTERS 2
#define ML_TWOSIDED      4
#define ML_DONTPEGTOP    8
#define ML_DONTPEGBOTTOM 16
#define ML_SECRET        32
#define ML_SOUNDBLOCK    64
#define ML_DONTDRAW      128

#define NO_INDEX        0xFFFFu

/* --- thinkers (vanilla d_think.h) ------------------------------------------- */
struct thinker_s;
typedef void (*think_t)(struct thinker_s *);
typedef struct thinker_s {
    struct thinker_s *prev, *next;
    think_t function;               /* THINK_REMOVED: free at the next run */
} thinker_t;
#define THINK_REMOVED   ((think_t)1)

/* --- the map ---------------------------------------------------------------- */

/* A cached line (the LINEDEF record less what the game never reads). */
typedef struct line_s {
    uint16_t index;                 /* the linedef number; NO_INDEX = empty slot */
    int16_t  v1x, v1y, dx, dy;      /* map units */
    int16_t  bbox[4];               /* BOXTOP, BOXBOTTOM, BOXLEFT, BOXRIGHT */
    uint16_t frontsector, backsector;   /* NO_INDEX = none */
    uint16_t tag;
    uint8_t  flags;                 /* ML_* */
    uint8_t  special;
    uint8_t  slopetype;             /* ST_* */
} line_t;

typedef struct {                    /* vanilla divline_t */
    fixed_t x, y, dx, dy;
} divline_t;

typedef struct {
    fixed_t frac;                   /* along the trace, 0..FRACUNIT */
    boolean isaline;
    uint16_t line;                  /* the line's index, if isaline */
    struct mobj_s *thing;           /* else the thing (an actor or a static) */
} intercept_t;

typedef boolean (*traverser_t)(intercept_t *in);

/* --- things ------------------------------------------------------------------ */

typedef struct mobj_s {
    thinker_t thinker;              /* first: a mobj is its own thinker */
    fixed_t   x, y, z;
    struct mobj_s *bnext;           /* blockmap chain (actors and statics) */
    fixed_t   momx, momy, momz;
    uint32_t  flags;                /* MF_* */
    fixed_t   height;               /* info height, >> 2 dead, 0 gibbed */
    angle_t   angle;
    uint16_t  state;
    int16_t   health;
    int16_t   floorz, ceilingz;     /* map units (sector heights are whole) */
    uint16_t  sector;               /* the sector of its subsector */
    struct mobj_s *target;
    struct mobj_s *tracer;
    uint8_t   type, tics;           /* tics: ST_FOREVER = vanilla -1 */
    uint8_t   radius;               /* map units; 0 when gibbed */
    uint8_t   movedir, movecount, reactiontime, threshold;
    uint8_t   lastlook;             /* vanilla's P_Random() % MAXPLAYERS at spawn */
} mobj_t;

typedef struct sobj_s {
    int16_t   x, y, z;              /* map units */
    struct mobj_s *bnext;           /* blockmap chain, as mobj_t.bnext */
    uint16_t  sector;
    uint16_t  state;
    uint8_t   type, tics;
    uint8_t   sflags;               /* SF_* */
    uint8_t   angle;                /* BAM8 (angle_t >> 8) */
} sobj_t;

#define SF_FREE     0x01            /* slot unused */
#define SF_AMBUSH   0x02            /* MF_AMBUSH */
#define SF_DROPPED  0x04            /* MF_DROPPED */
#define SF_CORPSE   0x08            /* dead: MF_CORPSE, height >> 2, not solid/shootable */
#define SF_GIBS     0x10            /* crushed: radius and height 0 */
#define SF_DORMANT  0x20            /* a monster that has not woken yet */
#define SF_NOBLOCK  0x40            /* not linked in the blockmap (MF_NOBLOCKMAP) */
#define SF_LOOK1    0x80            /* its lastlook is 1 (p_enemy.c: the first look fails) */

extern sobj_t *statics, *statics_end;
#define IS_STATIC(p)    ((void *)(p) >= (void *)statics && (void *)(p) < (void *)statics_end)
#define AS_STATIC(p)    ((sobj_t *)(void *)(p))
#define BNEXT(p)        (IS_STATIC(p) ? AS_STATIC(p)->bnext : (p)->bnext)

/* --- the player (vanilla d_player.h, one player) -------------------------------- */
enum { PST_LIVE, PST_DEAD, PST_REBORN };
enum { wp_fist, wp_pistol, wp_shotgun, wp_chaingun, wp_missile, wp_plasma, wp_bfg,
       wp_chainsaw, NUMWEAPONS, wp_nochange = 10 };
enum { am_clip, am_shell, am_cell, am_misl, NUMAMMO, am_noammo };
enum { pw_invulnerability, pw_strength, pw_invisibility, pw_ironfeet, pw_allmap,
       pw_infrared, NUMPOWERS };
enum { it_bluecard, it_yellowcard, it_redcard, it_blueskull, it_yellowskull,
       it_redskull, NUMCARDS };
enum { ps_weapon, ps_flash, NUMPSPRITES };

#define INVULNTICS  (30 * TICRATE)
#define INVISTICS   (60 * TICRATE)
#define INFRATICS   (120 * TICRATE)
#define IRONTICS    (60 * TICRATE)

/* ticcmd buttons (vanilla d_event.h) */
#define BT_ATTACK       1
#define BT_USE          2
#define BT_CHANGE       4
#define BT_WEAPONMASK   (8 + 16 + 32)
#define BT_WEAPONSHIFT  3

typedef struct {
    int8_t   forwardmove;           /* *2048 for move */
    int8_t   sidemove;
    int16_t  angleturn;             /* BAM16 per tic (vanilla's << 16 already done) */
    uint8_t  buttons;
} ticcmd_t;

typedef struct pspdef_s {
    uint16_t state;                 /* S_NULL = off */
    uint8_t  tics;
    fixed_t  sx, sy;
} pspdef_t;

typedef struct {
    uint8_t  ammo;
    uint16_t upstate, downstate, readystate, atkstate, flashstate;
} weaponinfo_t;
extern const weaponinfo_t weaponinfo[NUMWEAPONS];

typedef struct player_s {
    mobj_t  *mo;
    uint8_t  playerstate;
    ticcmd_t cmd;
    fixed_t  viewz, viewheight, deltaviewheight, bob;
    int16_t  health, armorpoints;
    uint8_t  armortype;
    int16_t  powers[NUMPOWERS];
    boolean  cards[NUMCARDS];
    boolean  backpack;
    uint8_t  readyweapon, pendingweapon;
    boolean  weaponowned[NUMWEAPONS];
    int16_t  ammo[NUMAMMO], maxammo[NUMAMMO];
    boolean  attackdown, usedown;
    uint8_t  cheats;
    uint8_t  refire;
    int16_t  killcount, itemcount, secretcount;
    uint8_t  damagecount, bonuscount;
    mobj_t  *attacker;
    uint8_t  extralight;
    uint8_t  fixedcolormap;         /* 0 none, 1 infrared, 32 invulnerable (vanilla) */
    pspdef_t psprites[NUMPSPRITES];
    boolean  didsecret;
    uint8_t  message;               /* MSG_* of the last pickup (the HUD shows it), 0 none */
} player_t;
#define CF_NOCLIP       1
#define CF_GODMODE      2
#define CF_NOMOMENTUM   4

extern player_t player;             /* the one player (vanilla players[0]) */
/* vanilla's mobj->player: the player if this is his mobj, else NULL */
#define MO_PLAYER(m_)   ((m_) == player.mo ? &player : (player_t *)0)
#define IS_PLAYER(m_)   ((m_) == player.mo)

/* --- globals of the level (g_game.c, p_setup.c) --------------------------------- */
extern uint8_t  gameskill;          /* 0 baby .. 4 nightmare (sk_*) */
extern uint8_t  gameepisode, gamemap;
extern uint16_t leveltime;
extern uint16_t totalkills, totalitems, totalsecret;
extern uint8_t  gameaction;         /* ga_* */
enum { sk_baby, sk_easy, sk_medium, sk_hard, sk_nightmare };
enum { ga_nothing, ga_loadlevel, ga_completed, ga_secretcompleted, ga_died, ga_worlddone,
       ga_newgame };
/* the level flow (g_game.c): playing, the tally after a level, the end of
 * the episode (vanilla gamestate_t, and its finale) */
extern uint8_t  gamestate;
enum { GS_LEVEL, GS_INTERMISSION, GS_FINALE };
typedef struct {                    /* vanilla wbstartstruct_t for one player */
    uint8_t  epsd, last, next;      /* episode, the map left, the map to come (1-9) */
    boolean  didsecret;             /* left by a secret exit */
    int16_t  maxkills, maxitems, maxsecret;
    int16_t  kills, items, secret;
    uint32_t time;                  /* tics spent in the level */
    uint16_t partime;               /* seconds */
} wbstartstruct_t;
extern wbstartstruct_t wminfo;      /* valid in GS_INTERMISSION and GS_FINALE */
extern uint16_t wi_tics;            /* tics in the intermission or finale */
extern uint32_t leveltics;          /* tics in the level (leveltime wraps at 65536) */
/* messages for the status bar (MSG_*: pickups, keys), oldest first */
void    G_Message(uint8_t msg);
uint8_t G_NextMessage(void);        /* 0: none waiting */

/* the level's far arrays (p_setup.c fills levarr from MAPDIR) */
typedef struct {  /* 10 bytes */
    uint8_t  bank;
    uint16_t addr;
    uint8_t  elsize;
    uint8_t  shift;                 /* log2 of elsize, 0xFF if not a power of two */
    uint8_t  log2;                  /* elements per chunk */
    uint16_t mask;                  /* 2^log2 - 1 */
    uint16_t count;
} levarr_t;

extern levarr_t levarr[11];
extern uint8_t *rej_known, *rej_bits;     /* the reject row cache (p_levdata.c) */

/* map sizes and near arrays of the current level (p_setup.c) */
extern uint16_t numsectors, numlines, numsubsectors, numnodes, numsides;
extern int16_t *sec_floorh, *sec_ceilh;     /* map units, near mirrors */
extern uint8_t *sec_special;
extern mobj_t **sec_soundtarget;            /* the monsters part's (vanilla sector->soundtarget) */
extern int16_t  bmaporgx, bmaporgy;         /* map units */
extern uint8_t  bmapwidth, bmapheight;
extern mobj_t **blocklinks;
extern uint16_t skyflatnum;

/* --- p_setup.c: level data access --------------------------------------------- */
void     P_SetupLevel(uint8_t episode, uint8_t map, uint8_t skill);
far_t    P_LevAddr(uint8_t array, uint16_t index);   /* MAPARR_* */
void     P_LevRead(uint8_t array, uint16_t index, void *dst, uint16_t len);
void     P_LevWrite(uint8_t array, uint16_t index, const void *src, uint16_t len);
line_t  *P_Line(uint16_t index);
void     P_SetLineSpecial(uint16_t line, uint8_t special);
uint16_t P_LineSide(uint16_t line, uint8_t side);   /* sidedef number */
void     P_SetSectorFloor(uint16_t sector, int16_t height);
void     P_SetSectorCeiling(uint16_t sector, int16_t height);
void     P_SetSectorSpecial(uint16_t sector, uint8_t special);
uint16_t P_SectorTag(uint16_t sector);
uint8_t  P_SectorLight(uint16_t sector);
void     P_SetSectorLight(uint16_t sector, uint8_t light);
uint16_t P_SectorFloorPic(uint16_t sector);
uint16_t P_SectorCeilingPic(uint16_t sector);
uint16_t P_SectorLines(uint16_t sector, uint16_t *first);  /* count; *first = SECLINES index */
uint16_t P_SecLine(uint16_t secline);               /* SECLINES[secline] */
void     P_SectorBlockBox(uint16_t sector, uint8_t *box);  /* cells: top, bottom, left, right */
extern int16_t sec_bbox[4];         /* ... and its lines' box in map units (the same order) */
boolean  P_RejectVisible(uint16_t s1, uint16_t s2);  /* false: REJECT says they cannot see */
uint16_t R_PointInSector(fixed_t x, fixed_t y);
void     P_ClearCaches(void);                       /* p_levdata.c, level start */
extern uint8_t sec_changes;         /* counts P_SetSectorFloor/Ceiling calls (mod 256) */
typedef struct {                    /* a cached BSP node (p_levdata.c) */
    uint16_t node;                  /* its number; NO_INDEX = empty slot */
    int16_t  x, y, dx, dy;          /* the partition line, map units */
    uint16_t child[2];              /* right (front), left (back); bit 15 = subsector */
} bspnode_t;
bspnode_t *P_Node(uint16_t nodenum);  /* valid until the next P_Node or R_PointInSector */
void     P_ClearBlockBoxCache(void);
void    *P_ArenaAlloc(uint16_t size);               /* level memory, zeroed; crash when full */
uint16_t P_ArenaFree(void);
uint8_t  P_ThingType(uint16_t doomednum);             /* MT_ of a doomednum, 0xFF unknown */
uint8_t  P_BlockLines(uint16_t cell, uint16_t *out, uint8_t max, uint16_t *skip);

/* --- fixed.s / m_fixed ---------------------------------------------------------- */
fixed_t FASTCALL FixedMul(fixed_t a, fixed_t b);
fixed_t FASTCALL FixedDiv(fixed_t a, fixed_t b);
fixed_t FASTCALL fine_sine(uint16_t fineangle);
fixed_t FASTCALL fine_cosine(uint16_t fineangle);
angle_t FASTCALL tanto_angle(uint16_t slope);       /* 0..SLOPERANGE */
angle_t R_PointToAngle2(fixed_t x1, fixed_t y1, fixed_t x2, fixed_t y2);
fixed_t P_AproxDistance(fixed_t dx, fixed_t dy);
uint8_t P_Random(void);
int16_t P_SubRandom(void);          /* P_Random() - P_Random(), left to right */
extern uint8_t prndindex;
void    M_ClearRandom(void);

/* --- p_tick.c ------------------------------------------------------------------- */
extern thinker_t thinkercap;
void P_InitThinkers(void);
void P_AddThinker(thinker_t *thinker);
void P_RemoveThinker(thinker_t *thinker);
void P_RunThinkers(void);
void P_UnlinkThinker(thinker_t *thinker);   /* out of the list now (not while it runs) */
thinker_t *P_AllocThinker(uint8_t size);     /* a zeroed block of <= THINKER_BLOCK bytes */
#ifdef __CC65__
#define THINKER_BLOCK   32
#else
#define THINKER_BLOCK   64          /* the host's thinker_t alone is 24 bytes */
#endif
#define THINKER_BLOCKS  32
void P_FreeActor(mobj_t *mo);
void P_Ticker(void);

/* --- p_mobj.c ------------------------------------------------------------------- */
extern mobj_t *mobjs, *mobjs_end;   /* the actor pool */
extern uint16_t nummobjs, numstatics, mobjs_used, statics_used;
extern mobj_t sview;                /* a static seen as a mobj (P_StaticView) */
extern sobj_t *sview_src;
boolean P_SetMobjState(mobj_t *mobj, uint16_t state);
void    P_MobjThinker(mobj_t *mobj);
mobj_t *P_SpawnMobj(fixed_t x, fixed_t y, fixed_t z, uint8_t type);
void    P_RemoveMobj(mobj_t *mobj);
void    P_ExplodeMissile(mobj_t *mo);
void    P_SpawnPuff(fixed_t x, fixed_t y, fixed_t z);
void    P_SpawnBlood(fixed_t x, fixed_t y, fixed_t z, int16_t damage);
mobj_t *P_SpawnMissile(mobj_t *source, mobj_t *dest, uint8_t type);
void    P_SpawnPlayerMissile(mobj_t *source, uint8_t type);
void    P_CheckMissileSpawn(mobj_t *th);
void    P_SpawnMapThing(int16_t x, int16_t y, int16_t angle, uint16_t type, uint16_t options);
void    P_SpawnPlayer(void);
mobj_t *P_WakeStatic(sobj_t *s);    /* NULL if no actor slot is free */
mobj_t *P_StaticView(sobj_t *s);    /* read-only mobj image of a static */
mobj_t *P_Actor(mobj_t *thing);     /* thing itself, or its static woken (may be NULL) */
void    P_RunStatics(void);
void    P_InitMobjs(uint16_t statics);  /* the pools; the actors get the arena less ARENA_RESERVE */
void   *P_ArenaPool(uint16_t *count);   /* 6502: the actor pool's place and size (p_setup.c) */
void    P_ExtendPool(void);             /* 6502: the set-up overlay's bytes become actor slots */
void    P_LoadOverlay(void);            /* 6502: the set-up overlay back into place (fixed.s) */
#define ARENA_RESERVE   2048        /* level memory left for P_SpawnSpecials, P_MonstersSetupLevel */
#define MAXACTORS       160
fixed_t P_ThingHeight(mobj_t *thing);   /* height of an actor or a static */
uint8_t P_ThingRadius(mobj_t *thing);
uint32_t P_StaticFlags(sobj_t *s);
mobj_t *P_FindTeleportDest(uint16_t sector);   /* an MT_TELEPORTMAN in the sector */
void    P_ForgetMobj(mobj_t *mo);   /* clear every reference to mo (it is going away) */
sobj_t *P_AllocStatic(void);        /* a free static slot, NULL if none */

/* --- p_maputl.c ------------------------------------------------------------------- */
extern fixed_t opentop, openbottom, openrange, lowfloor;
extern divline_t trace;
extern intercept_t intercepts[];
extern intercept_t *intercept_p;
#define MAXINTERCEPTS   128
#define PT_ADDLINES     1
#define PT_ADDTHINGS    2
#define PT_EARLYOUT     4
uint8_t P_PointOnLineSide(fixed_t x, fixed_t y, line_t *line);
int8_t  P_BoxOnLineSide(fixed_t *tmbox, line_t *ld);
uint8_t P_PointOnDivlineSide(fixed_t x, fixed_t y, divline_t *line);
void    P_MakeDivline(line_t *li, divline_t *dl);
fixed_t P_InterceptVector(divline_t *v2, divline_t *v1);
void    P_LineOpening(line_t *linedef);
void    P_UnsetThingPosition(mobj_t *thing);
void    P_SetThingPosition(mobj_t *thing);
void    P_LinkStatic(sobj_t *s);
void    P_UnlinkStatic(sobj_t *s);
boolean P_BlockLinesIterator(int16_t x, int16_t y, boolean (*func)(line_t *));
boolean P_BlockThingsIterator(int16_t x, int16_t y, boolean (*func)(mobj_t *));
boolean P_PathTraverse(fixed_t x1, fixed_t y1, fixed_t x2, fixed_t y2, uint8_t flags,
                       traverser_t trav);
void    P_InitLineMarks(void);   /* level start: the line mark bitset */
void    P_NewValidcount(void);      /* vanilla validcount++ for lines */
boolean P_LineChecked(uint16_t line);   /* sets the mark; true if already set */
int16_t P_BlockX(fixed_t x);        /* (x - bmaporgx) >> MAPBLOCKSHIFT */
int16_t P_BlockY(fixed_t y);

/* --- p_map.c ------------------------------------------------------------------------ */
extern fixed_t tmbbox[4];
extern mobj_t *tmthing;
extern uint32_t tmflags;
extern fixed_t tmx, tmy;
extern boolean floatok;
extern fixed_t tmfloorz, tmceilingz, tmdropoffz;
extern uint16_t ceilingline;        /* NO_INDEX = none */
#define MAXSPECIALCROSS 8
extern uint16_t spechit[MAXSPECIALCROSS];
extern uint8_t numspechit;
extern mobj_t *linetarget;
extern fixed_t attackrange, aimslope, topslope, bottomslope;
boolean P_CheckPosition(mobj_t *thing, fixed_t x, fixed_t y);
boolean P_TryMove(mobj_t *thing, fixed_t x, fixed_t y);
boolean P_TeleportMove(mobj_t *thing, fixed_t x, fixed_t y);
boolean P_ThingHeightClip(mobj_t *thing);
void    P_SlideMove(mobj_t *mo);
fixed_t P_AimLineAttack(mobj_t *t1, angle_t angle, fixed_t distance);
void    P_LineAttack(mobj_t *t1, angle_t angle, fixed_t distance, fixed_t slope, int16_t damage);
void    P_UseLines(player_t *player);
void    P_RadiusAttack(mobj_t *spot, mobj_t *source, int16_t damage);
boolean P_ChangeSector(uint16_t sector, boolean crunch);

/* --- p_user.c, p_pspr.c --------------------------------------------------------------- */
void P_PlayerThink(player_t *player);
void P_CalcHeight(player_t *player);
void P_Thrust(player_t *player, angle_t angle, fixed_t move);
void P_SetupPsprites(player_t *player);
void P_MovePsprites(player_t *player);
void P_SetPsprite(player_t *player, uint8_t position, uint16_t stnum);
void P_DropWeapon(player_t *player);
boolean P_CheckAmmo(player_t *player);
void P_BringUpWeapon(player_t *player);
extern fixed_t bulletslope;
extern const int16_t maxammo[NUMAMMO];
extern const int16_t clipammo[NUMAMMO];

/* --- g_game.c ----------------------------------------------------------------------- */
void G_ExitLevel(void);
void G_SecretExitLevel(void);
void G_PlayerReborn(void);
void G_BuildTiccmd(ticcmd_t *cmd);
void R_BuildView(void);
void S_StartSound(mobj_t *origin, uint8_t sfx);
extern uint8_t  snd_last[8];        /* the last sounds started (the sound part takes them) */
extern uint8_t  snd_count;

/* --- the MONSTERS part (p_enemy.c, p_inter.c, p_sight.c) ----------------------------- */
void    P_DamageMobj(mobj_t *target, mobj_t *inflictor, mobj_t *source, int16_t damage);
void    P_KillMobj(mobj_t *source, mobj_t *target);
void    P_TouchSpecialThing(mobj_t *special, mobj_t *toucher);
boolean P_CheckSight(mobj_t *t1, mobj_t *t2);
void    P_NoiseAlert(mobj_t *target, mobj_t *emitter);
void    P_MonstersSetupLevel(void);
/* A_* mobj actions: info.h */
/* vanilla's movement directions (p_enemy.c) */
enum { DI_EAST, DI_NORTHEAST, DI_NORTH, DI_NORTHWEST, DI_WEST, DI_SOUTHWEST, DI_SOUTH,
       DI_SOUTHEAST, DI_NODIR };
/* player.message: vanilla's pickup messages (d_englsh.h), by number */
enum { MSG_NONE, MSG_GOTARMOR, MSG_GOTMEGA, MSG_GOTHTHBONUS, MSG_GOTARMBONUS, MSG_GOTSUPER,
       MSG_GOTBLUECARD, MSG_GOTYELWCARD, MSG_GOTREDCARD, MSG_GOTBLUESKUL, MSG_GOTYELWSKUL,
       MSG_GOTREDSKULL, MSG_GOTSTIM, MSG_GOTMEDINEED, MSG_GOTMEDIKIT, MSG_GOTINVUL,
       MSG_GOTBERSERK, MSG_GOTINVIS, MSG_GOTSUIT, MSG_GOTMAP, MSG_GOTVISOR, MSG_GOTCLIP,
       MSG_GOTCLIPBOX, MSG_GOTROCKET, MSG_GOTROCKBOX, MSG_GOTCELL, MSG_GOTCELLBOX,
       MSG_GOTSHELLS, MSG_GOTSHELLBOX, MSG_GOTBACKPACK, MSG_GOTCHAINGUN, MSG_GOTCHAINSAW,
       MSG_GOTLAUNCHER, MSG_GOTPLASMA, MSG_GOTSHOTGUN,
       /* the specials part's (vanilla PD_*: "You need a blue key to activate
        * this object" (a locked switch), "... to open this door") */
       MSG_PD_BLUEO, MSG_PD_REDO, MSG_PD_YELLOWO, MSG_PD_BLUEK, MSG_PD_REDK, MSG_PD_YELLOWK };

/* --- the SPECIALS part (game_specials_stub.c until p_spec & co) ------------------------ */
void    P_CrossSpecialLine(uint16_t linenum, uint8_t side, mobj_t *thing);
void    P_ShootSpecialLine(mobj_t *thing, uint16_t linenum);
boolean P_UseSpecialLine(mobj_t *thing, uint16_t linenum, uint8_t side);
void    P_PlayerInSpecialSector(player_t *player);
void    P_SpawnSpecials(void);
void    P_UpdateSpecials(void);

/* kernel_crash codes of the game (the kernel uses 1-2) */
#define CRASH_ARENA     0x20        /* level memory exhausted */
#define CRASH_NOMAP     0x21        /* map not in MAPDIR */
#define CRASH_MOBJS     0x22        /* no actor slot for a thing that must exist */
#define CRASH_BANKS     0x23        /* no RamWorks bank for the game's far tables */

#endif
