/* Doom for the Appletini -- map geometry utilities (docs/DESIGN.md section 9).
 *
 * Vanilla p_maputl.c: line sides, box sides, divlines and intercepts,
 * line openings, thing position links, the blockmap iterators, and
 * P_PathTraverse with its intercepts. The differences are in the storage:
 *
 *  - Lines come from the line cache (P_Line) by index; vanilla's
 *    per-line validcount is a bitset of the level's lines (one bit per
 *    line in the arena) with the list of the bytes set since the last
 *    P_NewValidcount, so that clearing costs what was marked.
 *  - Thing chains mix actors and statics (p_local.h): the iterators hand
 *    both to their callbacks; a static's position and size are read from
 *    its own fields (IS_STATIC).
 *  - Things are linked only in the blockmap: vanilla's sector thing lists
 *    exist for the renderer, which gets the things in the render packet.
 *    The blockmap chain is singly linked (unlinking walks the cell's
 *    chain, which is short).
 *  - The blockmap line lists are vanilla's, with the leading 0 that makes
 *    vanilla test line 0 in every cell (P_BlockLines).
 *  - At most MAXINTERCEPTS intercepts are kept (vanilla overran its
 *    array); further ones are dropped.
 */
#include "p_local.h"

/* on the 6502 this is a_maputl.s */
#if defined(GAME_REAL) && !defined(__CC65__)

#include <string.h>

fixed_t opentop, openbottom, openrange, lowfloor;
divline_t trace;
intercept_t intercepts[MAXINTERCEPTS];
intercept_t *intercept_p;
static boolean earlyout;

/* --- line marks (vanilla validcount) ----------------------------------------- */
#define MARKLIST 48
static uint8_t *linemarks;          /* numlines bits */
static uint16_t marked[MARKLIST];   /* byte indices set since the last clear */
static uint8_t nmarked;             /* MARKLIST + 1: too many, clear it all */

void P_InitLineMarks(void)
{
    linemarks = P_ArenaAlloc((numlines + 7) >> 3);
    nmarked = 0;
}

void P_NewValidcount(void)
{
    uint8_t i;
    if (nmarked > MARKLIST)
        memset(linemarks, 0, (numlines + 7) >> 3);
    else
        for (i = 0; i < nmarked; ++i)
            linemarks[marked[i]] = 0;
    nmarked = 0;
}

boolean P_LineChecked(uint16_t line)
{
    uint16_t i = line >> 3;
    uint8_t mask = 1 << (line & 7);

    if (linemarks[i] & mask)
        return true;
    if (!linemarks[i]) {
        if (nmarked < MARKLIST)
            marked[nmarked] = i;
        if (nmarked <= MARKLIST)
            ++nmarked;
    }
    linemarks[i] |= mask;
    return false;
}

/* --- sides --------------------------------------------------------------------- */
uint8_t P_PointOnLineSide(fixed_t x, fixed_t y, line_t *line)
{
    fixed_t dx, dy, left, right;

    if (!line->dx) {
        if (x <= FIX(line->v1x))
            return line->dy > 0;
        return line->dy < 0;
    }
    if (!line->dy) {
        if (y <= FIX(line->v1y))
            return line->dx < 0;
        return line->dx > 0;
    }
    dx = x - FIX(line->v1x);
    dy = y - FIX(line->v1y);
    left = FixedMul((fixed_t)line->dy, dx);
    right = FixedMul(dy, (fixed_t)line->dx);
    return right < left ? 0 : 1;
}

int8_t P_BoxOnLineSide(fixed_t *tmbox, line_t *ld)
{
    uint8_t p1 = 0, p2 = 0;

    switch (ld->slopetype) {
    case ST_HORIZONTAL:
        p1 = tmbox[BOXTOP] > FIX(ld->v1y);
        p2 = tmbox[BOXBOTTOM] > FIX(ld->v1y);
        if (ld->dx < 0) {
            p1 ^= 1;
            p2 ^= 1;
        }
        break;
    case ST_VERTICAL:
        p1 = tmbox[BOXRIGHT] < FIX(ld->v1x);
        p2 = tmbox[BOXLEFT] < FIX(ld->v1x);
        if (ld->dy < 0) {
            p1 ^= 1;
            p2 ^= 1;
        }
        break;
    case ST_POSITIVE:
        p1 = P_PointOnLineSide(tmbox[BOXLEFT], tmbox[BOXTOP], ld);
        p2 = P_PointOnLineSide(tmbox[BOXRIGHT], tmbox[BOXBOTTOM], ld);
        break;
    case ST_NEGATIVE:
        p1 = P_PointOnLineSide(tmbox[BOXRIGHT], tmbox[BOXTOP], ld);
        p2 = P_PointOnLineSide(tmbox[BOXLEFT], tmbox[BOXBOTTOM], ld);
        break;
    }
    if (p1 == p2)
        return p1;
    return -1;
}

uint8_t P_PointOnDivlineSide(fixed_t x, fixed_t y, divline_t *line)
{
    fixed_t dx, dy, left, right;

    if (!line->dx) {
        if (x <= line->x)
            return line->dy > 0;
        return line->dy < 0;
    }
    if (!line->dy) {
        if (y <= line->y)
            return line->dx < 0;
        return line->dx > 0;
    }
    dx = x - line->x;
    dy = y - line->y;
    /* try to decide by the sign bits */
    if ((FB_(line->dy, 3) ^ FB_(line->dx, 3) ^ FB_(dx, 3) ^ FB_(dy, 3)) & 0x80) {
        if ((FB_(line->dy, 3) ^ FB_(dx, 3)) & 0x80)
            return 1;
        return 0;
    }
    left = FixedMul(line->dy >> 8, dx >> 8);
    right = FixedMul(dy >> 8, line->dx >> 8);
    return right < left ? 0 : 1;
}

void P_MakeDivline(line_t *li, divline_t *dl)
{
    dl->x = FIX(li->v1x);
    dl->y = FIX(li->v1y);
    dl->dx = FIX(li->dx);
    dl->dy = FIX(li->dy);
}

fixed_t P_InterceptVector(divline_t *v2, divline_t *v1)
{
    fixed_t num, den;

    den = FixedMul(v1->dy >> 8, v2->dx) - FixedMul(v1->dx >> 8, v2->dy);
    if (den == 0)
        return 0;
    num = FixedMul((v1->x - v2->x) >> 8, v1->dy) + FixedMul((v2->y - v1->y) >> 8, v1->dx);
    return FixedDiv(num, den);
}

void P_LineOpening(line_t *linedef)
{
    uint16_t front, back;

    if (linedef->backsector == NO_INDEX) {
        openrange = 0;
        return;
    }
    front = linedef->frontsector;
    back = linedef->backsector;
    opentop = FIX(sec_ceilh[front] < sec_ceilh[back] ? sec_ceilh[front] : sec_ceilh[back]);
    if (sec_floorh[front] > sec_floorh[back]) {
        openbottom = FIX(sec_floorh[front]);
        lowfloor = FIX(sec_floorh[back]);
    } else {
        openbottom = FIX(sec_floorh[back]);
        lowfloor = FIX(sec_floorh[front]);
    }
    openrange = opentop - openbottom;
}

/* --- thing position ---------------------------------------------------------------- */
int16_t P_BlockX(fixed_t x)
{
    return (int16_t)((x - FIX(bmaporgx)) >> MAPBLOCKSHIFT);
}

int16_t P_BlockY(fixed_t y)
{
    return (int16_t)((y - FIX(bmaporgy)) >> MAPBLOCKSHIFT);
}

static mobj_t **cell_head(int16_t bx, int16_t by)
{
    if (bx < 0 || by < 0 || bx >= bmapwidth || by >= bmapheight)
        return 0;
    return &blocklinks[(uint16_t)by * bmapwidth + bx];
}

static void chain_remove(mobj_t **link, mobj_t *thing)
{
    while (*link) {
        if (*link == thing) {
            *link = BNEXT(thing);
            return;
        }
        link = IS_STATIC(*link) ? &AS_STATIC(*link)->bnext : &(*link)->bnext;
    }
}

void P_UnsetThingPosition(mobj_t *thing)
{
    mobj_t **head;

    if (!FLAG(thing->flags, MF_NOBLOCKMAP)) {
        head = cell_head(P_BlockX(thing->x), P_BlockY(thing->y));
        if (head)
            chain_remove(head, thing);
    }
}

void P_SetThingPosition(mobj_t *thing)
{
    mobj_t **head;

    thing->sector = R_PointInSector(thing->x, thing->y);
    if (!FLAG(thing->flags, MF_NOBLOCKMAP)) {
        head = cell_head(P_BlockX(thing->x), P_BlockY(thing->y));
        if (head) {
            thing->bnext = *head;
            *head = thing;
        } else {
            thing->bnext = 0;
        }
    }
}

void P_LinkStatic(sobj_t *s)
{
    mobj_t **head = cell_head((s->x - bmaporgx) >> 7, (s->y - bmaporgy) >> 7);
    if (head) {
        s->bnext = *head;
        *head = (mobj_t *)s;
    } else {
        s->bnext = 0;
    }
}

void P_UnlinkStatic(sobj_t *s)
{
    mobj_t **head = cell_head((s->x - bmaporgx) >> 7, (s->y - bmaporgy) >> 7);
    if (head)
        chain_remove(head, (mobj_t *)s);
}

/* --- iterators ------------------------------------------------------------------------ */
boolean P_BlockLinesIterator(int16_t x, int16_t y, boolean (*func)(line_t *))
{
    uint16_t cell, pos = 0, list[16];
    uint8_t n, i;

    if (x < 0 || y < 0 || x >= bmapwidth || y >= bmapheight)
        return true;
    cell = (uint16_t)y * bmapwidth + x;
    while ((n = P_BlockLines(cell, list, 16, &pos)) != 0) {
        for (i = 0; i < n; ++i) {
            if (P_LineChecked(list[i]))
                continue;
            if (!func(P_Line(list[i])))
                return false;
        }
    }
    return true;
}

boolean P_BlockThingsIterator(int16_t x, int16_t y, boolean (*func)(mobj_t *))
{
    mobj_t *mobj, *next;

    if (x < 0 || y < 0 || x >= bmapwidth || y >= bmapheight)
        return true;
    for (mobj = blocklinks[(uint16_t)y * bmapwidth + x]; mobj; mobj = next) {
        if (!func(mobj))
            return false;
        next = BNEXT(mobj);
    }
    return true;
}

/* --- intercepts ---------------------------------------------------------------------------- */
static boolean PIT_AddLineIntercepts(line_t *ld)
{
    uint8_t s1, s2;
    fixed_t frac;
    divline_t dl;

    if (trace.dx > FRACUNIT * 16 || trace.dy > FRACUNIT * 16
        || trace.dx < -FRACUNIT * 16 || trace.dy < -FRACUNIT * 16) {
        s1 = P_PointOnDivlineSide(FIX(ld->v1x), FIX(ld->v1y), &trace);
        s2 = P_PointOnDivlineSide(FIX(ld->v1x + ld->dx), FIX(ld->v1y + ld->dy), &trace);
    } else {
        s1 = P_PointOnLineSide(trace.x, trace.y, ld);
        s2 = P_PointOnLineSide(trace.x + trace.dx, trace.y + trace.dy, ld);
    }
    if (s1 == s2)
        return true;
    P_MakeDivline(ld, &dl);
    frac = P_InterceptVector(&trace, &dl);
    if (frac < 0)
        return true;
    if (earlyout && frac < FRACUNIT && ld->backsector == NO_INDEX)
        return false;
    if (intercept_p == intercepts + MAXINTERCEPTS)
        return true;
    intercept_p->frac = frac;
    intercept_p->isaline = true;
    intercept_p->line = ld->index;
    ++intercept_p;
    return true;
}

static boolean PIT_AddThingIntercepts(mobj_t *thing)
{
    fixed_t x1, y1, x2, y2, tx, ty, r;
    uint8_t s1, s2;
    divline_t dl;
    fixed_t frac;

    if (IS_STATIC(thing)) {
        tx = FIX(AS_STATIC(thing)->x);
        ty = FIX(AS_STATIC(thing)->y);
    } else {
        tx = thing->x;
        ty = thing->y;
    }
    r = FIX(P_ThingRadius(thing));
    if ((trace.dx ^ trace.dy) > 0) {
        x1 = tx - r;
        y1 = ty + r;
        x2 = tx + r;
        y2 = ty - r;
    } else {
        x1 = tx - r;
        y1 = ty - r;
        x2 = tx + r;
        y2 = ty + r;
    }
    s1 = P_PointOnDivlineSide(x1, y1, &trace);
    s2 = P_PointOnDivlineSide(x2, y2, &trace);
    if (s1 == s2)
        return true;
    dl.x = x1;
    dl.y = y1;
    dl.dx = x2 - x1;
    dl.dy = y2 - y1;
    frac = P_InterceptVector(&trace, &dl);
    if (frac < 0)
        return true;
    if (intercept_p == intercepts + MAXINTERCEPTS)
        return true;
    intercept_p->frac = frac;
    intercept_p->isaline = false;
    intercept_p->thing = thing;
    ++intercept_p;
    return true;
}

static boolean P_TraverseIntercepts(traverser_t func, fixed_t maxfrac)
{
    uint8_t count = (uint8_t)(intercept_p - intercepts);
    fixed_t dist;
    intercept_t *scan, *in = 0;

    while (count--) {
        dist = MAXINT;
        for (scan = intercepts; scan < intercept_p; ++scan)
            if (scan->frac < dist) {
                dist = scan->frac;
                in = scan;
            }
        if (dist > maxfrac)
            return true;
        if (!func(in))
            return false;
        in->frac = MAXINT;
    }
    return true;
}

boolean P_PathTraverse(fixed_t x1, fixed_t y1, fixed_t x2, fixed_t y2, uint8_t flags,
                       traverser_t trav)
{
    fixed_t xt1, yt1, xt2, yt2, xstep, ystep, partial, xintercept, yintercept;
    int16_t mapx, mapy, mapxstep, mapystep;
    uint8_t count;

    earlyout = (flags & PT_EARLYOUT) != 0;
    P_NewValidcount();
    intercept_p = intercepts;
    if (((x1 - FIX(bmaporgx)) & (((fixed_t)MAPBLOCKUNITS << FRACBITS) - 1)) == 0)
        x1 += FRACUNIT;
    if (((y1 - FIX(bmaporgy)) & (((fixed_t)MAPBLOCKUNITS << FRACBITS) - 1)) == 0)
        y1 += FRACUNIT;
    trace.x = x1;
    trace.y = y1;
    trace.dx = x2 - x1;
    trace.dy = y2 - y1;
    x1 -= FIX(bmaporgx);
    y1 -= FIX(bmaporgy);
    xt1 = x1 >> MAPBLOCKSHIFT;
    yt1 = y1 >> MAPBLOCKSHIFT;
    x2 -= FIX(bmaporgx);
    y2 -= FIX(bmaporgy);
    xt2 = x2 >> MAPBLOCKSHIFT;
    yt2 = y2 >> MAPBLOCKSHIFT;
    if (xt2 > xt1) {
        mapxstep = 1;
        partial = FRACUNIT - ((x1 >> MAPBTOFRAC) & (FRACUNIT - 1));
        ystep = FixedDiv(y2 - y1, x2 > x1 ? x2 - x1 : x1 - x2);
    } else if (xt2 < xt1) {
        mapxstep = -1;
        partial = (x1 >> MAPBTOFRAC) & (FRACUNIT - 1);
        ystep = FixedDiv(y2 - y1, x2 > x1 ? x2 - x1 : x1 - x2);
    } else {
        mapxstep = 0;
        partial = FRACUNIT;
        ystep = 256 * FRACUNIT;
    }
    yintercept = (y1 >> MAPBTOFRAC) + FixedMul(partial, ystep);
    if (yt2 > yt1) {
        mapystep = 1;
        partial = FRACUNIT - ((y1 >> MAPBTOFRAC) & (FRACUNIT - 1));
        xstep = FixedDiv(x2 - x1, y2 > y1 ? y2 - y1 : y1 - y2);
    } else if (yt2 < yt1) {
        mapystep = -1;
        partial = (y1 >> MAPBTOFRAC) & (FRACUNIT - 1);
        xstep = FixedDiv(x2 - x1, y2 > y1 ? y2 - y1 : y1 - y2);
    } else {
        mapystep = 0;
        partial = FRACUNIT;
        xstep = 256 * FRACUNIT;
    }
    xintercept = (x1 >> MAPBTOFRAC) + FixedMul(partial, xstep);
    mapx = (int16_t)xt1;
    mapy = (int16_t)yt1;
    for (count = 0; count < 64; ++count) {
        if (flags & PT_ADDLINES)
            if (!P_BlockLinesIterator(mapx, mapy, PIT_AddLineIntercepts))
                return false;
        if (flags & PT_ADDTHINGS)
            if (!P_BlockThingsIterator(mapx, mapy, PIT_AddThingIntercepts))
                return false;
        if (mapx == xt2 && mapy == yt2)
            break;
        if ((yintercept >> FRACBITS) == mapy) {
            yintercept += ystep;
            mapx += mapxstep;
        } else if ((xintercept >> FRACBITS) == mapx) {
            xintercept += xstep;
            mapy += mapystep;
        }
    }
    return P_TraverseIntercepts(trav, FRACUNIT);
}

#endif
