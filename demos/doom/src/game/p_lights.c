/* Doom for the Appletini -- sector lights (docs/DESIGN.md section 9):
 * vanilla p_lights.c.
 *
 * vanilla's light thinkers (T_LightFlash, T_StrobeFlash, T_Glow,
 * T_FireFlicker) are records of a list in level memory here, run by
 * P_UpdateSpecials: 8 bytes each instead of a 32-byte thinker block, and
 * no thinker call. E1M3 has 27 of them. The sector's light is written to
 * its far record (the renderer reads it there) when it changes; the
 * record keeps a near copy (cur) that vanilla read from the sector.
 * EV_LightTurnOn and EV_TurnTagLightsOff go through P_SetLight so that
 * the copy follows.
 *
 * The list holds the lights of the sector specials (1, 2, 3, 4, 8, 12,
 * 13, 17) plus SPARE_LIGHTS for EV_StartLightStrobing (walk line 17, not
 * in Freedoom's E1): more strobes than that are not started.
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)   /* on the 6502: a_spec.s */

#define GLOWSPEED       8
#define STROBEBRIGHT    5
#define FASTDARK        15
#define SLOWDARK        35

light_t *lights;                    /* (P_SpawnSpecials makes the list) */
uint8_t numlights, maxlights;

static light_t *new_light(uint16_t sector, uint8_t kind)
{
    light_t *l;

    if (numlights == maxlights)
        return 0;
    l = &lights[numlights++];
    l->sector = sector;
    l->kind = kind;
    l->cur = l->maxlight = P_SectorLight(sector);
    l->minlight = P_FindMinSurroundingLight(sector, l->maxlight);
    P_SetSectorSpecial(sector, 0);  /* nothing special about it during play */
    return l;
}

static void spawn_strobe(uint16_t sector, uint8_t dark, boolean insync)
{
    light_t *l = new_light(sector, LT_STROBE);

    if (!l)
        return;
    l->aux = dark;
    if (l->minlight == l->maxlight)
        l->minlight = 0;
    l->count = insync ? 1 : (P_Random() & 7) + 1;
}

/* vanilla P_SpawnSpecials' lights; other specials are ignored */
void P_SpawnLight(uint16_t sector, uint8_t special)
{
    light_t *l;

    switch (special) {
    case 1:                         /* flickering (P_SpawnLightFlash) */
        if ((l = new_light(sector, LT_FLASH)) != 0)
            l->count = (P_Random() & 64) + 1;
        break;
    case 2:
        spawn_strobe(sector, FASTDARK, false);
        break;
    case 3:
        spawn_strobe(sector, SLOWDARK, false);
        break;
    case 4:                         /* strobe, and the floor hurts */
        spawn_strobe(sector, FASTDARK, false);
        P_SetSectorSpecial(sector, 4);
        break;
    case 8:                         /* glowing (P_SpawnGlowingLight) */
        new_light(sector, LT_GLOW);
        break;
    case 12:
        spawn_strobe(sector, SLOWDARK, true);
        break;
    case 13:
        spawn_strobe(sector, FASTDARK, true);
        break;
    case 17:                        /* fire flicker */
        if ((l = new_light(sector, LT_FIRE)) != 0) {
            l->minlight += 16;
            l->count = 4;
        }
        break;
    }
}

void P_SetLight(uint16_t sector, uint8_t light)
{
    uint8_t i;

    P_SetSectorLight(sector, light);
    for (i = 0; i < numlights; ++i)
        if (lights[i].sector == sector)
            lights[i].cur = light;
}

void P_RunLights(void)
{
    light_t *l = lights;
    uint8_t i, amount;
    int16_t v;

    for (i = numlights; i; --i, ++l) {
        if (l->kind == LT_GLOW) {
            v = l->cur;
            if (l->aux) {           /* up */
                v += GLOWSPEED;
                if (v >= l->maxlight) {
                    v -= GLOWSPEED;
                    l->aux = 0;
                }
            } else {                /* down */
                v -= GLOWSPEED;
                if (v <= l->minlight) {
                    v += GLOWSPEED;
                    l->aux = 1;
                }
            }
        } else {
            if (--l->count)
                continue;
            switch (l->kind) {
            case LT_FLASH:          /* T_LightFlash: dark 1-8 tics, bright 1 or 65 (vanilla's & 64) */
                if (l->cur == l->maxlight) {
                    v = l->minlight;
                    l->count = (P_Random() & 7) + 1;
                } else {
                    v = l->maxlight;
                    l->count = (P_Random() & 64) + 1;
                }
                break;
            case LT_STROBE:         /* T_StrobeFlash */
                if (l->cur == l->minlight) {
                    v = l->maxlight;
                    l->count = STROBEBRIGHT;
                } else {
                    v = l->minlight;
                    l->count = l->aux;
                }
                break;
            default:                /* T_FireFlicker */
                amount = (P_Random() & 3) * 16;
                v = l->cur - amount < l->minlight ? l->minlight : l->maxlight - amount;
                l->count = 4;
                break;
            }
        }
        if ((uint8_t)v != l->cur) {
            l->cur = (uint8_t)v;
            P_SetSectorLight(l->sector, l->cur);
        }
    }
}

/* --- the line actions ---------------------------------------------------------------------- */
void EV_StartLightStrobing(uint16_t line)
{
    uint16_t tag = P_Line(line)->tag, cursor = 0, s;

    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX)
        if (!SEC_BUSY(s))
            spawn_strobe(s, SLOWDARK, false);
}

void EV_TurnTagLightsOff(uint16_t line)
{
    uint16_t tag = P_Line(line)->tag, cursor = 0, s;

    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX)
        P_SetLight(s, P_FindMinSurroundingLight(s, P_SectorLight(s)));
}

/* bright 0: the brightest neighbour's light; as vanilla, the level found
 * for the first sector is kept for the others */
void EV_LightTurnOn(uint16_t line, uint8_t bright)
{
    uint16_t tag = P_Line(line)->tag, cursor = 0, s, first, count, n, other;
    uint8_t v;

    while ((s = P_FindSectorFromTag(tag, &cursor)) != NO_INDEX) {
        if (!bright) {
            count = P_SectorLines(s, &first);
            for (n = 0; n < count; ++n) {
                other = P_NextSector(P_SecLine(first + n), s);
                if (other == NO_INDEX)
                    continue;
                v = P_SectorLight(other);
                if (v > bright)
                    bright = v;
            }
        }
        P_SetLight(s, bright);
    }
}

#endif
