/* Doom for the Appletini -- stand-ins for the SPECIALS part (docs/DESIGN.md
 * section 9): vanilla p_spec.c, p_doors.c, p_floor.c, p_plats.c,
 * p_ceilng.c, p_lights.c, p_switch.c and p_telept.c will replace this
 * file, with these signatures (p_local.h, p_spec.h).
 *
 * Until then only the exits work (so that level flow can be tested):
 * the use exits 11 (normal) and 51 (secret) and the walk-over exits 52
 * and 124 end the level; secrets are counted as vanilla's
 * P_SpawnSpecials does. Every EV_ does nothing and reports no sector
 * moved.
 */
#include "p_spec.h"

#ifdef GAME_REAL

void P_CrossSpecialLine(uint16_t linenum, uint8_t side, mobj_t *thing)
{
    line_t *line = P_Line(linenum);

    (void)side;
    if (!IS_PLAYER(thing))
        return;
    if (line->special == 52)
        G_ExitLevel();
    else if (line->special == 124)
        G_SecretExitLevel();
}

void P_ShootSpecialLine(mobj_t *thing, uint16_t linenum)
{
    (void)thing;
    (void)linenum;
}

boolean P_UseSpecialLine(mobj_t *thing, uint16_t linenum, uint8_t side)
{
    line_t *line = P_Line(linenum);

    if (side || !IS_PLAYER(thing))
        return false;
    if (line->special == 11) {
        S_StartSound(thing, sfx_swtchn);
        G_ExitLevel();
    } else if (line->special == 51) {
        S_StartSound(thing, sfx_swtchn);
        G_SecretExitLevel();
    }
    return true;
}

void P_PlayerInSpecialSector(player_t *p)
{
    (void)p;
}

void P_SpawnSpecials(void)
{
    uint16_t n;
    for (n = 0; n < numsectors; ++n)
        if (sec_special[n] == 9)
            ++totalsecret;
}

void P_UpdateSpecials(void)
{
}

int16_t EV_DoDoor(uint16_t line, uint8_t type) { (void)line; (void)type; return 0; }
void EV_VerticalDoor(uint16_t line, mobj_t *thing) { (void)line; (void)thing; }
int16_t EV_DoFloor(uint16_t line, uint8_t floortype) { (void)line; (void)floortype; return 0; }
int16_t EV_DoPlat(uint16_t line, uint8_t type, int16_t amount)
{
    (void)line; (void)type; (void)amount;
    return 0;
}
void EV_StopPlat(uint16_t line) { (void)line; }
int16_t EV_DoCeiling(uint16_t line, uint8_t type) { (void)line; (void)type; return 0; }
int16_t EV_CeilingCrushStop(uint16_t line) { (void)line; return 0; }
int16_t EV_BuildStairs(uint16_t line, uint8_t type) { (void)line; (void)type; return 0; }
int16_t EV_DoDonut(uint16_t line) { (void)line; return 0; }
void EV_LightTurnOn(uint16_t line, uint8_t bright) { (void)line; (void)bright; }
void EV_StartLightStrobing(uint16_t line) { (void)line; }
void EV_TurnTagLightsOff(uint16_t line) { (void)line; }
int16_t EV_Teleport(uint16_t line, uint8_t side, mobj_t *thing)
{
    (void)line; (void)side; (void)thing;
    return 0;
}

#endif
