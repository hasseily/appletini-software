/* Doom for the Appletini -- the SPECIALS part (docs/DESIGN.md section 9):
 * vanilla p_spec.h, reduced to what the part shares between its files
 * (p_spec.c, p_doors.c, p_floor.c, p_plats.c, p_ceilng.c, p_lights.c,
 * p_switch.c, p_telept.c) and with lines passed by index (line_t is a
 * cached copy, p_local.h).
 *
 * The core calls P_CrossSpecialLine, P_ShootSpecialLine,
 * P_UseSpecialLine, P_PlayerInSpecialSector, P_SpawnSpecials and
 * P_UpdateSpecials (p_local.h); the monsters part calls P_UseSpecialLine
 * (a monster blocked by a door line) and EV_DoFloorTag (A_BossDeath's tag
 * 666); the level flow (g_game.c) calls P_ResetLevelData.
 *
 * Tools of the core the part uses:
 *   sectors    sec_floorh/sec_ceilh/sec_special (near, read), their
 *              setters P_SetSectorFloor/Ceiling/Special (write through to
 *              the renderer's far record), P_SectorTag, P_SectorLight/
 *              P_SetSectorLight, P_SectorFloorPic, P_SectorLines +
 *              P_SecLine, P_ChangeSector (the crush test after a height
 *              change)
 *   lines      P_Line (cached), P_SetLineSpecial, P_LineSide (sidedef
 *              numbers; sidedefs are far: P_LevAddr + far_read/far_write
 *              for the switch textures and the scrolling offsets)
 *   thinkers   P_AllocThinker(size <= THINKER_BLOCK) + P_AddThinker;
 *              P_RemoveThinker frees the block after the run
 *   teleports  P_FindTeleportDest(sector), P_TeleportMove
 *
 * Differences from vanilla, all deliberate (DESIGN.md section 9):
 *   - Heights are whole map units (the far records are). A mover's speed
 *     is kept in eighths of a unit per tic (every vanilla speed is a
 *     multiple of FRACUNIT/8: stairs 1/4, the change-texture plats 1/2, a
 *     blocked crusher 1/8) and the eighths not yet moved are carried
 *     (mover_t.acc): a slow plane moves one unit every 2, 4 or 8 tics and
 *     is where vanilla's is at every whole unit.
 *   - vanilla's sector->specialdata is one bit per sector (sec_busy);
 *     the few places that need the mover itself find it in the thinker
 *     list, and never mistake a lift for a door (vanilla's bug).
 *   - Lights are not thinkers: a list of 8-byte records run by
 *     P_UpdateSpecials (the thinker blocks are few and 32 bytes).
 *   - Sounds of sectors have no origin (S_StartSound(NULL, ...)).
 */
#ifndef P_SPEC_H
#define P_SPEC_H

#include "p_local.h"

/* doors */
enum { vld_normal, vld_close30ThenOpen, vld_close, vld_open, vld_raiseIn5Mins,
       vld_blazeRaise, vld_blazeOpen, vld_blazeClose };
/* floors */
enum { lowerFloor, lowerFloorToLowest, turboLower, raiseFloor, raiseFloorToNearest,
       raiseToTexture, lowerAndChange, raiseFloor24, raiseFloor24AndChange,
       raiseFloorCrush, raiseFloorTurbo, donutRaise, raiseFloor512 };
/* platforms */
enum { perpetualRaise, downWaitUpStay, raiseAndChange, raiseToNearestAndChange,
       blazeDWUS };
/* ceilings */
enum { lowerToFloor, raiseToHighest, lowerAndCrush, crushAndRaise, fastCrushAndRaise,
       silentCrushAndRaise };
/* stairs */
enum { build8, turbo16 };

/* speeds in eighths of a map unit per tic (vanilla's in FRACUNIT) */
#define SPEED(units)    ((uint8_t)((units) * 8))
#define VDOORSPEED      SPEED(2)
#define VDOORWAIT       150
#define FLOORSPEED      SPEED(1)
#define CEILSPEED       SPEED(1)
#define PLATSPEED       SPEED(1)
#define PLATWAIT        3

/* T_MovePlane's results */
enum { res_ok, res_crushed, res_pastdest };

/* Every mover's first fields: its thinker, its sector, its speed. */
typedef struct {
    thinker_t thinker;
    uint16_t  sector;
    uint8_t   type;
    uint8_t   speed;                /* eighths of a unit per tic */
    uint8_t   acc;                  /* eighths owed from earlier tics */
} mover_t;

typedef struct {                    /* vanilla vldoor_t */
    mover_t   m;
    int8_t    direction;            /* 1 up, 0 waiting, -1 down, 2 initial wait */
    int16_t   topheight;
    uint16_t  topwait, topcountdown;
} vldoor_t;

typedef struct {                    /* vanilla floormove_t */
    mover_t   m;
    int8_t    direction;
    boolean   crush;
    uint8_t   newspecial;
    uint16_t  texture;
    int16_t   floordestheight;
} floormove_t;

enum { plat_up, plat_down, plat_waiting, plat_in_stasis };
typedef struct {                    /* vanilla plat_t */
    mover_t   m;
    int16_t   low, high;
    uint8_t   wait, count;          /* at most 35 * PLATWAIT */
    uint8_t   status, oldstatus;
    boolean   crush;
    uint16_t  tag;
} plat_t;

typedef struct {                    /* vanilla ceiling_t */
    mover_t   m;
    int16_t   bottomheight, topheight;
    boolean   crush;
    int8_t    direction, olddirection;  /* 0: in stasis */
    uint16_t  tag;
} ceiling_t;

/* the movers' thinkers (p_doors.c, p_floor.c, p_plats.c, p_ceilng.c) */
void T_VerticalDoor(thinker_t *t);
void T_MoveFloor(thinker_t *t);
void T_PlatRaise(thinker_t *t);
void T_MoveCeiling(thinker_t *t);

/* --- p_spec.c: the part's tools ---------------------------------------------------------- */
/* The state the level set-up (C, the GOVL overlay on the 6502) makes and
 * the runtime (a_spec.s on the 6502) uses: */
extern uint8_t  *sec_busy;          /* vanilla sector->specialdata != NULL, one bit a sector */
extern uint16_t *tag_list;          /* the tagged sectors: pairs of sector, tag, in sector order */
extern uint16_t  tag_count;
extern uint16_t *scroll_list;       /* the scrolling walls (48): pairs of sidedef, first offset */
extern uint8_t   scroll_count;
extern uint16_t  jcount;            /* entries in the level's journal (P_JournalBytes) */
typedef struct {                    /* a light (p_lights.c), 8 bytes */
    uint16_t sector;
    uint8_t  kind;                  /* LT_* */
    uint8_t  count;                 /* tics to the next change */
    uint8_t  minlight, maxlight;
    uint8_t  cur;                   /* the sector's light now */
    uint8_t  aux;                   /* strobe: darktime; glow: 1 up, 0 down */
} light_t;
enum { LT_FLASH, LT_STROBE, LT_GLOW, LT_FIRE };
extern light_t *lights;
extern uint8_t   numlights, maxlights;
#define SPARE_LIGHTS    8           /* EV_StartLightStrobing's */
#define MAXSCROLLERS    32
/* the specials' bank (kbanks - 2): the journal, then the sectors' snapshots */
#define JOURNAL_BASE    0x0200
#define JOURNAL_MAX     341         /* 6-byte entries in $0200-$09FF */
#define SNAP_BASE       0x0A00

#define SEC_BUSY(s)     (sec_busy[(s) >> 3] & (uint8_t)(1 << ((s) & 7)))
void     P_SetBusy(uint16_t sector);
void     P_ClearBusy(uint16_t sector);
mover_t *P_NewMover(think_t function, uint8_t size, uint16_t sector);  /* busy, added, zeroed */
void     P_RemoveMover(mover_t *m);  /* not busy; the thinker goes at the next run */
mover_t *P_FindMover(uint16_t sector, think_t function);    /* NULL: none */
uint8_t  T_MovePlane(mover_t *m, int16_t dest, boolean crush, uint8_t ceiling, int8_t direction);

uint16_t P_FindSectorFromTag(uint16_t tag, uint16_t *cursor);   /* start *cursor at 0; NO_INDEX: done */
uint16_t P_NextSector(uint16_t line, uint16_t sector);     /* the other side, NO_INDEX if none */
int16_t  P_FindLowestFloorSurrounding(uint16_t sector);
int16_t  P_FindHighestFloorSurrounding(uint16_t sector);
int16_t  P_FindNextHighestFloor(uint16_t sector, int16_t height);
int16_t  P_FindLowestCeilingSurrounding(uint16_t sector);
int16_t  P_FindHighestCeilingSurrounding(uint16_t sector);
uint8_t  P_FindMinSurroundingLight(uint16_t sector, uint8_t max);
void     P_SetSectorFloorPic(uint16_t sector, uint16_t pic);
void     P_SpawnSectorSpecial(uint16_t sector, uint8_t special);    /* lights, doors 10 and 14 */

/* Level records the renderer reads are changed in place in far memory;
 * these keep what a level restart needs to undo (p_spec.c). */
void     P_JournalBytes(far_t addr, uint8_t len);   /* before a lasting change of <= 2 bytes */
void     P_ClearLineSpecial(uint16_t line);         /* a W1/S1/G1 line is used up */
void     P_ResetLevelData(uint8_t map);             /* level load: undo, and the sectors' snapshot */

/* --- p_lights.c ---------------------------------------------------------------------------- */
void     P_SpawnLight(uint16_t sector, uint8_t special);    /* sector specials 1-4, 8, 12, 13, 17 */
void     P_RunLights(void);
void     P_SetLight(uint16_t sector, uint8_t light);        /* the record and the list's copy */

/* --- p_switch.c ---------------------------------------------------------------------------- */
void     P_ChangeSwitchTexture(uint16_t line, boolean useAgain);
void     P_RunButtons(void);
void     P_ResetButtons(boolean up);    /* none pressed; up: put the pressed ones back first */

/* --- the EV_ actions ------------------------------------------------------------------------- */
int16_t EV_DoDoor(uint16_t line, uint8_t type);
int16_t EV_DoLockedDoor(uint16_t line, uint8_t type, mobj_t *thing);
void    EV_VerticalDoor(uint16_t line, mobj_t *thing);
void    P_SpawnDoorCloseIn30(uint16_t sector);
void    P_SpawnDoorRaiseIn5Mins(uint16_t sector);
int16_t EV_DoFloor(uint16_t line, uint8_t floortype);
int16_t EV_DoFloorTag(uint16_t tag, uint8_t floortype);  /* A_BossDeath's tag 666 */
int16_t EV_DoPlat(uint16_t line, uint8_t type, int16_t amount);
void    EV_StopPlat(uint16_t line);
int16_t EV_DoCeiling(uint16_t line, uint8_t type);
int16_t EV_CeilingCrushStop(uint16_t line);
int16_t EV_BuildStairs(uint16_t line, uint8_t type);
int16_t EV_DoDonut(uint16_t line);
void    EV_LightTurnOn(uint16_t line, uint8_t bright);
void    EV_StartLightStrobing(uint16_t line);
void    EV_TurnTagLightsOff(uint16_t line);
int16_t EV_Teleport(uint16_t line, uint8_t side, mobj_t *thing);

#endif
