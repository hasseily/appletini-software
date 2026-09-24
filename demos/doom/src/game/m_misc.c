/* Doom for the Appletini -- random numbers and angle arithmetic in C
 * (docs/DESIGN.md sections 5 and 9).
 *
 * P_Random is vanilla's (m_random.c: rndtable, one index); P_SubRandom is
 * chocolate-doom's left-to-right P_Random() - P_Random(), which is what
 * vanilla's compiler did. R_PointToAngle2 is vanilla's octant search with
 * SlopeDiv into tantoangle, returning vanilla's angle >> 16 exactly (the
 * table holds tantoangle >> 16; the octants that subtract from ANGnn - 1
 * keep the low bits' borrow, the negated octant adds it back).
 */
#include "p_local.h"

#ifdef GAME_REAL

uint8_t prndindex;

uint8_t P_Random(void)
{
    return rndtable[++prndindex];
}

int16_t P_SubRandom(void)
{
    int16_t r = P_Random();
    return r - P_Random();
}

void M_ClearRandom(void)
{
    prndindex = 0;
}

#ifndef __CC65__                   /* on the 6502: a_maputl.s */
fixed_t P_AproxDistance(fixed_t dx, fixed_t dy)
{
    if (dx < 0)
        dx = -dx;
    if (dy < 0)
        dy = -dy;
    if (dx < dy)
        return dx + dy - (dx >> 1);
    return dx + dy - (dy >> 1);
}
#endif

static uint16_t SlopeDiv(uint32_t num, uint32_t den)
{
    uint32_t ans;

    if (den < 512)
        return SLOPERANGE;
    ans = (num << 3) / (den >> 8);
    return ans <= SLOPERANGE ? (uint16_t)ans : SLOPERANGE;
}

angle_t R_PointToAngle2(fixed_t x1, fixed_t y1, fixed_t x, fixed_t y)
{
    x -= x1;
    y -= y1;
    if (!x && !y)
        return 0;
    if (x >= 0) {
        if (y >= 0) {
            if (x > y)
                return tanto_angle(SlopeDiv(y, x));                 /* octant 0 */
            return ANG90 - 1 - tanto_angle(SlopeDiv(x, y));         /* octant 1 */
        }
        y = -y;
        if (x > y) {                                                /* octant 8 */
            /* vanilla -tantoangle[s] >> 16: every entry but the first and
             * the last (0 and ANG45) has low bits set, so the negation
             * borrows */
            uint16_t s = SlopeDiv(y, x);
            return (angle_t)(0 - tanto_angle(s) - (s != 0 && s != SLOPERANGE));
        }
        return ANG270 + tanto_angle(SlopeDiv(x, y));                /* octant 7 */
    }
    x = -x;
    if (y >= 0) {
        if (x > y)
            return ANG180 - 1 - tanto_angle(SlopeDiv(y, x));        /* octant 3 */
        return ANG90 + tanto_angle(SlopeDiv(x, y));                 /* octant 2 */
    }
    y = -y;
    if (x > y)
        return ANG180 + tanto_angle(SlopeDiv(y, x));                /* octant 4 */
    return ANG270 - 1 - tanto_angle(SlopeDiv(x, y));                /* octant 5 */
}

#endif
