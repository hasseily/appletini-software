/* Doom for the Appletini -- the SPECIALS part's interface (docs/DESIGN.md
 * section 9): vanilla p_spec.h reduced to what episode 1 needs, with
 * lines passed by index (line_t is a cached copy, p_local.h).
 *
 * The core calls P_CrossSpecialLine, P_ShootSpecialLine,
 * P_UseSpecialLine, P_PlayerInSpecialSector, P_SpawnSpecials and
 * P_UpdateSpecials (p_local.h); the EV_ functions are the part's own,
 * declared here with the signatures the stand-in (game_specials_stub.c)
 * gives them.
 *
 * Tools of the core for the part:
 *   sectors    sec_floorh/sec_ceilh/sec_special (near, read), their
 *              setters P_SetSectorFloor/Ceiling/Special (write through to
 *              the renderer's far record), P_SectorTag, P_SectorLight/
 *              P_SetSectorLight, P_SectorFloorPic/CeilingPic,
 *              P_SectorLines + P_SecLine (a sector's lines),
 *              P_ChangeSector (the crush test after a height change)
 *   lines      P_Line (cached), P_SetLineSpecial, P_LineSide (sidedef
 *              numbers; sidedefs are far: P_LevRead(MAPARR_SIDEDEFS...)
 *              and P_LevWrite for the switch textures)
 *   thinkers   P_AllocThinker(size <= THINKER_BLOCK) + P_AddThinker;
 *              P_RemoveThinker frees the block after the run
 *   teleports  P_FindTeleportDest(sector), P_TeleportMove
 *   level      G_ExitLevel, G_SecretExitLevel; totalsecret is counted
 *              in P_SpawnSpecials (sector special 9) as vanilla does
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

int16_t EV_DoDoor(uint16_t line, uint8_t type);
void    EV_VerticalDoor(uint16_t line, mobj_t *thing);
int16_t EV_DoFloor(uint16_t line, uint8_t floortype);
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
