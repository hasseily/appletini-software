/* The render packet: what the game hands the renderer every frame.
 *
 * It lives in the GAME space (symbol _rview in bank 1); the renderer copies
 * it into main memory with one far read at the start of render_frame, so
 * the game can keep playing with its own structures while the frame is
 * drawn. Positions are in the renderer's sub-units (1/16 map unit, i.e.
 * fixed_t >> 12, sign-extended to 32 bits); angles are BAM16 (angle_t >>
 * 16). The layout is fixed and mirrored in src/kernel/rview.inc: change
 * both and tools/refrender.py's reading of it together.
 *
 * The game fills things[] with the closest mobjs that have a sprite (at
 * most RV_MAXTHINGS, nearest first, the player's own mobj excluded), each
 * with the sector it stands in (its subsector's sector, which the game
 * knows). The renderer draws a thing only if its sector was reached by the
 * BSP walk, clipped by the walls as Doom does.
 */
#ifndef RVIEW_H
#define RVIEW_H

#include <stdint.h>

#define RV_MAXTHINGS 128

#define RT_SHADOW     0x01      /* MF_SHADOW: the spectre's fuzz */
#define RT_FULLBRIGHT 0x80      /* in frame: Doom's FF_FULLBRIGHT, moved to bit 7 */
#define RV_NOCOLORMAP 0xFF

typedef struct {                /* 20 bytes */
    int32_t  x, y, z;           /* sub-units; z = the thing's feet */
    uint16_t angle;             /* BAM16 */
    uint8_t  sprite;            /* SPR_ number (doomdata.h) */
    uint8_t  frame;             /* frame letter index; bit 7 full bright */
    uint8_t  flags;             /* RT_* */
    uint8_t  pad;
    uint16_t sector;
} rthing_t;

typedef struct {                /* 10 bytes: a weapon layer (weapon, flash) */
    uint8_t  sprite;            /* 0xFF = layer off */
    uint8_t  frame;             /* bit 7 full bright */
    int32_t  sx, sy;            /* Doom's 320x200 screen, 16.16 */
} rpsprite_t;

typedef struct {
    int32_t    x, y, z;         /* the eye, sub-units */
    uint16_t   angle;           /* BAM16 */
    uint8_t    extralight;      /* 0..2 (gun flashes) */
    uint8_t    fixedcolormap;   /* stored colormap 0..15, or RV_NOCOLORMAP */
    uint16_t   tic;             /* game tic, for texture and flat animation */
    uint8_t    nthings;
    uint8_t    npsprites;       /* 0..2 */
    rpsprite_t psprites[2];     /* offset 20 */
    rthing_t   things[RV_MAXTHINGS];   /* offset 40 */
} rview_t;

extern rview_t rview;

#endif
