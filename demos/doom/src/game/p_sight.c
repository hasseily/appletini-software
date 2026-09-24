/* Doom for the Appletini -- line of sight (docs/DESIGN.md section 9).
 *
 * Vanilla p_sight.c (Doom 1.9): REJECT first, then the BSP walk from the
 * looker's eye to the target, crossing only the subsectors the sight line
 * passes through (P_CrossBSPNode), and in each one every linedef it
 * crosses (P_CrossSubsector): a one-sided line, or an opening closed or
 * narrowed below the slopes to the target's top and bottom, blocks.
 *
 * What differs is the storage, not the results:
 *
 *  - The walk keeps an explicit stack of the "other side" children still
 *    to cross instead of recursing (the 6502's stack is 256 bytes and
 *    shared with everything; the BSP of episode 1 is at most 43 deep).
 *    A node's two side tests (the start and the end of the sight line)
 *    are both made when the node is entered, so the node need not be
 *    read again after its first child; the order in which subsectors are
 *    crossed is vanilla's.
 *  - Lines are the line cache's (P_Line: v1, dx, dy, flags, sectors);
 *    vanilla reads the seg's front and back sectors, this reads the
 *    line's: the same two sectors, and every test on them is symmetric
 *    (the lower ceiling, the higher floor, "equal heights"). A seg gives
 *    only its linedef's number (one 2-byte far read).
 *  - vanilla's validcount is the core's line marks (P_NewValidcount,
 *    P_LineChecked), shared with the other traversals as vanilla's.
 *  - topslope and bottomslope are the globals of the attack code, as in
 *    vanilla (p_map.c uses p_sight.c's).
 *
 * P_DivlineSide keeps vanilla's quirks: its horizontal-line case compares
 * x with the line's y, and its products (whole units, 32 bits) wrap as
 * vanilla's int arithmetic did.
 *
 * On the 6502 this is a_sight.s.
 */
#include "p_local.h"

#if defined(GAME_REAL) && !defined(__CC65__)

#define SIGHTSTACK  64              /* pending BSP children (depth) */

/* the walk's work, for the tests' measurements (tests/test_game_monsters.py) */
struct { uint32_t checks, walks, nodes, subsectors, segs, lines, crossed, intercepts; } sight_stats;

static fixed_t sightzstart;         /* eye z of the looker */
static divline_t strace;            /* from t1 to t2 */
static fixed_t t2x, t2y;

/* vanilla P_DivlineSide: 0 front, 1 back, 2 on */
static uint8_t P_DivlineSide(fixed_t x, fixed_t y, const divline_t *node)
{
    fixed_t dx, dy;
    int32_t left, right;

    if (!node->dx) {
        if (x == node->x)
            return 2;
        if (x <= node->x)
            return node->dy > 0;
        return node->dy < 0;
    }
    if (!node->dy) {
        if (x == node->y)           /* (sic) */
            return 2;
        if (y <= node->y)
            return node->dx < 0;
        return node->dx > 0;
    }
    dx = x - node->x;
    dy = y - node->y;
    left = (int32_t)((uint32_t)(node->dy >> FRACBITS) * (uint32_t)(dx >> FRACBITS));
    right = (int32_t)((uint32_t)(dy >> FRACBITS) * (uint32_t)(node->dx >> FRACBITS));
    if (right < left)
        return 0;
    if (left == right)
        return 2;
    return 1;
}

/* vanilla P_InterceptVector2: the fraction along v2 where v1 crosses it */
static fixed_t P_InterceptVector2(const divline_t *v2, const divline_t *v1)
{
    fixed_t num, den;

    den = FixedMul(v1->dy >> 8, v2->dx) - FixedMul(v1->dx >> 8, v2->dy);
    if (den == 0)
        return 0;
    num = FixedMul((v1->x - v2->x) >> 8, v1->dy) + FixedMul((v2->y - v1->y) >> 8, v1->dx);
    return FixedDiv(num, den);
}

static boolean P_CrossSubsector(uint16_t num)
{
    uint16_t seg[2], count, lnum, front, back;
    int16_t v1x, v1y, v2x, v2y, fc, bc, ff, bf;
    uint8_t s1, s2, lflags;
    line_t *line;
    divline_t divl;
    fixed_t opentop, openbottom, frac, slope;

    ++sight_stats.subsectors;
    P_LevRead(MAPARR_SSECTORS, num, seg, 4);    /* numsegs, firstseg */
    for (count = seg[0]; count; --count, ++seg[1]) {
        ++sight_stats.segs;
        far_read(P_LevAddr(MAPARR_SEGS, seg[1]) + SEG_LINEDEF, &lnum, 2);
        if (P_LineChecked(lnum))
            continue;               /* already checked other side */
        ++sight_stats.lines;
        line = P_Line(lnum);
        v1x = line->v1x;
        v1y = line->v1y;
        v2x = v1x + line->dx;
        v2y = v1y + line->dy;
        s1 = P_DivlineSide(FIX(v1x), FIX(v1y), &strace);
        s2 = P_DivlineSide(FIX(v2x), FIX(v2y), &strace);
        if (s1 == s2)
            continue;               /* line isn't crossed */
        divl.x = FIX(v1x);
        divl.y = FIX(v1y);
        divl.dx = FIX(line->dx);
        divl.dy = FIX(line->dy);
        s1 = P_DivlineSide(strace.x, strace.y, &divl);
        s2 = P_DivlineSide(t2x, t2y, &divl);
        if (s1 == s2)
            continue;
        ++sight_stats.crossed;
        back = line->backsector;
        lflags = line->flags;
        front = line->frontsector;
        if (back == NO_INDEX)
            return false;           /* an "impassible glass" hack line */
        if (!(lflags & ML_TWOSIDED))
            return false;
        ff = sec_floorh[front];
        bf = sec_floorh[back];
        fc = sec_ceilh[front];
        bc = sec_ceilh[back];
        if (ff == bf && fc == bc)
            continue;               /* no wall to block sight with */
        opentop = FIX(fc < bc ? fc : bc);
        openbottom = FIX(ff > bf ? ff : bf);
        if (openbottom >= opentop)
            return false;           /* closed door */
        ++sight_stats.intercepts;
        frac = P_InterceptVector2(&strace, &divl);
        if (ff != bf) {
            slope = FixedDiv(openbottom - sightzstart, frac);
            if (slope > bottomslope)
                bottomslope = slope;
        }
        if (fc != bc) {
            slope = FixedDiv(opentop - sightzstart, frac);
            if (slope < topslope)
                topslope = slope;
        }
        if (topslope <= bottomslope)
            return false;
    }
    return true;                    /* passed the subsector */
}

/* vanilla P_CrossBSPNode(numnodes - 1) with an explicit stack */
static boolean P_CrossBSP(void)
{
    uint16_t stack[SIGHTSTACK], bspnum;
    uint8_t depth = 0, side, side2;
    bspnode_t *bsp;
    divline_t dl;

    if (!numnodes)
        return P_CrossSubsector(0);
    bspnum = numnodes - 1;
    for (;;) {
        while (!(bspnum & 0x8000)) {
            ++sight_stats.nodes;
            bsp = P_Node(bspnum);
            dl.x = FIX(bsp->x);
            dl.y = FIX(bsp->y);
            dl.dx = FIX(bsp->dx);
            dl.dy = FIX(bsp->dy);
            side = P_DivlineSide(strace.x, strace.y, &dl);
            if (side == 2)
                side = 0;           /* an "on" should cross both sides */
            side2 = P_DivlineSide(t2x, t2y, &dl);
            /* the partition plane is crossed: the ending side after the
             * starting one (vanilla: if side == the end's side, done) */
            if (side != side2 && depth < SIGHTSTACK)
                stack[depth++] = bsp->child[side ^ 1];
            bspnum = bsp->child[side];
        }
        if (!P_CrossSubsector(bspnum & 0x7FFF))
            return false;
        if (!depth)
            return true;
        bspnum = stack[--depth];
    }
}

boolean P_CheckSight(mobj_t *t1, mobj_t *t2)
{
    ++sight_stats.checks;
    /* first check for trivial rejection */
    if (!P_RejectVisible(t1->sector, t2->sector))
        return false;
    ++sight_stats.walks;
    /* an unobstructed line of sight is possible: look from the eyes of t1
     * to any part of t2 */
    P_NewValidcount();
    sightzstart = t1->z + t1->height - (t1->height >> 2);
    topslope = (t2->z + t2->height) - sightzstart;
    bottomslope = t2->z - sightzstart;
    strace.x = t1->x;
    strace.y = t1->y;
    t2x = t2->x;
    t2y = t2->y;
    strace.dx = t2->x - t1->x;
    strace.dy = t2->y - t1->y;
    return P_CrossBSP();
}

#endif
