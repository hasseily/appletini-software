/* Doom for the Appletini -- movement, collision, attacks, use (docs/DESIGN.md
 * section 9).
 *
 * Vanilla p_map.c: P_CheckPosition with PIT_CheckThing and PIT_CheckLine,
 * P_TryMove with the crossing of special lines, P_TeleportMove,
 * P_ThingHeightClip, P_SlideMove, P_AimLineAttack/P_LineAttack (autoaim,
 * puffs and blood), P_UseLines, P_RadiusAttack, P_ChangeSector.
 *
 * Statics in the blockmap (p_local.h) are handled where vanilla reads a
 * thing: the quick tests (flags, distance, heights) read the static's own
 * fields; a pickup is touched through its P_StaticView; anything that can
 * hurt it (a charging lost soul, a missile, a telefrag, a bullet, a blast,
 * a crusher) wakes it first (P_WakeStatic) and acts on the actor. A static
 * is itself the moving thing only in P_ChangeSector's height clip.
 *
 * Lines are read by index through the line cache; the spechit list and
 * the intercepts keep indices, and code that calls out (special line
 * actions) fetches its line again afterwards.
 */
#include "p_local.h"

/* on the 6502 this is a_map.s */
#if defined(GAME_REAL) && !defined(__CC65__)

fixed_t tmbbox[4];
mobj_t *tmthing;
uint32_t tmflags;
fixed_t tmx, tmy;
static fixed_t tmradius;
boolean floatok;
fixed_t tmfloorz, tmceilingz, tmdropoffz;
uint16_t ceilingline;
uint16_t spechit[MAXSPECIALCROSS];
uint8_t numspechit;

mobj_t *linetarget;
static mobj_t *shootthing;
static fixed_t shootz;
static int16_t la_damage;
fixed_t attackrange, aimslope, topslope, bottomslope;

static fixed_t fabs32(fixed_t v)
{
    return v < 0 ? -v : v;
}

/* position of an actor or a static */
static fixed_t thing_x(mobj_t *t) { return IS_STATIC(t) ? FIX(AS_STATIC(t)->x) : t->x; }
static fixed_t thing_y(mobj_t *t) { return IS_STATIC(t) ? FIX(AS_STATIC(t)->y) : t->y; }
static fixed_t thing_z(mobj_t *t) { return IS_STATIC(t) ? FIX(AS_STATIC(t)->z) : t->z; }

/* the low byte of a thing's flags: MF_SPECIAL, MF_SOLID, MF_SHOOTABLE */
static uint8_t thing_flags0(mobj_t *t)
{
    sobj_t *s;
    uint8_t f;

    if (!IS_STATIC(t))
        return FB_(t->flags, 0);
    s = AS_STATIC(t);
    f = FB_(mobjinfo[s->type].flags, 0);
    if (s->sflags & SF_CORPSE)
        f &= ~(MF_SOLID | MF_SHOOTABLE);
    if (s->sflags & SF_GIBS)
        f &= ~MF_SOLID;
    return f;
}

/* --- teleport move ------------------------------------------------------------ */
static boolean PIT_StompThing(mobj_t *thing)
{
    fixed_t blockdist;

    if (!(thing_flags0(thing) & MF_SHOOTABLE))
        return true;
    blockdist = FIX(P_ThingRadius(thing)) + tmradius;
    if (fabs32(thing_x(thing) - tmx) >= blockdist || fabs32(thing_y(thing) - tmy) >= blockdist)
        return true;
    if (thing == tmthing)
        return true;
    if (!IS_PLAYER(tmthing) && gamemap != 30)
        return false;
    thing = P_Actor(thing);
    if (thing)
        P_DamageMobj(thing, tmthing, tmthing, 10000);
    return true;
}

static void set_tm(mobj_t *thing, fixed_t x, fixed_t y)
{
    tmthing = thing;
    tmflags = thing->flags;
    tmradius = FIX(thing->radius);
    tmx = x;
    tmy = y;
    tmbbox[BOXTOP] = y + tmradius;
    tmbbox[BOXBOTTOM] = y - tmradius;
    tmbbox[BOXRIGHT] = x + tmradius;
    tmbbox[BOXLEFT] = x - tmradius;
}

static void tm_sector(fixed_t x, fixed_t y)
{
    uint16_t sec = R_PointInSector(x, y);
    ceilingline = NO_INDEX;
    tmfloorz = tmdropoffz = FIX(sec_floorh[sec]);
    tmceilingz = FIX(sec_ceilh[sec]);
}

boolean P_TeleportMove(mobj_t *thing, fixed_t x, fixed_t y)
{
    int16_t xl, xh, yl, yh, bx, by;

    set_tm(thing, x, y);
    tm_sector(x, y);
    P_NewValidcount();
    numspechit = 0;
    xl = P_BlockX(tmbbox[BOXLEFT] - FIX(MAXRADIUS));
    xh = P_BlockX(tmbbox[BOXRIGHT] + FIX(MAXRADIUS));
    yl = P_BlockY(tmbbox[BOXBOTTOM] - FIX(MAXRADIUS));
    yh = P_BlockY(tmbbox[BOXTOP] + FIX(MAXRADIUS));
    for (bx = xl; bx <= xh; ++bx)
        for (by = yl; by <= yh; ++by)
            if (!P_BlockThingsIterator(bx, by, PIT_StompThing))
                return false;
    P_UnsetThingPosition(thing);
    thing->floorz = UNITS(tmfloorz);
    thing->ceilingz = UNITS(tmceilingz);
    thing->x = x;
    thing->y = y;
    P_SetThingPosition(thing);
    return true;
}

/* --- check position --------------------------------------------------------------- */
static boolean PIT_CheckLine(line_t *ld)
{
    if (tmbbox[BOXRIGHT] <= FIX(ld->bbox[BOXLEFT]) || tmbbox[BOXLEFT] >= FIX(ld->bbox[BOXRIGHT])
        || tmbbox[BOXTOP] <= FIX(ld->bbox[BOXBOTTOM]) || tmbbox[BOXBOTTOM] >= FIX(ld->bbox[BOXTOP]))
        return true;
    if (P_BoxOnLineSide(tmbbox, ld) != -1)
        return true;
    if (ld->backsector == NO_INDEX)
        return false;               /* one sided line */
    if (!FLAG(tmflags, MF_MISSILE)) {
        if (ld->flags & ML_BLOCKING)
            return false;
        if (!IS_PLAYER(tmthing) && (ld->flags & ML_BLOCKMONSTERS))
            return false;
    }
    P_LineOpening(ld);
    if (opentop < tmceilingz) {
        tmceilingz = opentop;
        ceilingline = ld->index;
    }
    if (openbottom > tmfloorz)
        tmfloorz = openbottom;
    if (lowfloor < tmdropoffz)
        tmdropoffz = lowfloor;
    if (ld->special && numspechit < MAXSPECIALCROSS)
        spechit[numspechit++] = ld->index;
    return true;
}

static boolean PIT_CheckThing(mobj_t *thing)
{
    fixed_t blockdist;
    uint8_t f0 = thing_flags0(thing), ttype;
    int16_t damage;
    mobj_t *act;

    if (!(f0 & (MF_SOLID | MF_SPECIAL | MF_SHOOTABLE)))
        return true;
    blockdist = FIX(P_ThingRadius(thing)) + tmradius;
    if (fabs32(thing_x(thing) - tmx) >= blockdist || fabs32(thing_y(thing) - tmy) >= blockdist)
        return true;
    if (thing == tmthing)
        return true;
    ttype = IS_STATIC(thing) ? AS_STATIC(thing)->type : thing->type;

    if (FLAG(tmflags, MF_SKULLFLY)) {
        damage = ((P_Random() % 8) + 1) * mobjinfo[tmthing->type].damage;
        act = P_Actor(thing);
        if (act)
            P_DamageMobj(act, tmthing, tmthing, damage);
        FLAGS_CLR(tmthing->flags, MF_SKULLFLY);
        tmthing->momx = tmthing->momy = tmthing->momz = 0;
        P_SetMobjState(tmthing, mobjinfo[tmthing->type].spawnstate);
        return false;
    }
    if (FLAG(tmflags, MF_MISSILE)) {
        if (tmthing->z > thing_z(thing) + P_ThingHeight(thing))
            return true;            /* overhead */
        if (tmthing->z + tmthing->height < thing_z(thing))
            return true;            /* underneath */
        if (tmthing->target && tmthing->target->type == ttype) {
            if (thing == tmthing->target)
                return true;
            if (ttype != MT_PLAYER)
                return false;       /* no infighting within a species */
        }
        if (!(f0 & MF_SHOOTABLE))
            return !(f0 & MF_SOLID);
        damage = ((P_Random() % 8) + 1) * mobjinfo[tmthing->type].damage;
        act = P_Actor(thing);
        if (act)
            P_DamageMobj(act, tmthing, tmthing->target, damage);
        return false;
    }
    if (f0 & MF_SPECIAL) {
        if (FLAG(tmflags, MF_PICKUP))
            P_TouchSpecialThing(IS_STATIC(thing) ? P_StaticView(AS_STATIC(thing)) : thing, tmthing);
        return !(f0 & MF_SOLID);
    }
    return !(f0 & MF_SOLID);
}

/* P_CheckPosition's work with tm* set */
static boolean check_position(void)
{
    int16_t xl, xh, yl, yh, bx, by;

    tm_sector(tmx, tmy);
    P_NewValidcount();
    numspechit = 0;
    if (FLAG(tmflags, MF_NOCLIP))
        return true;
    xl = P_BlockX(tmbbox[BOXLEFT] - FIX(MAXRADIUS));
    xh = P_BlockX(tmbbox[BOXRIGHT] + FIX(MAXRADIUS));
    yl = P_BlockY(tmbbox[BOXBOTTOM] - FIX(MAXRADIUS));
    yh = P_BlockY(tmbbox[BOXTOP] + FIX(MAXRADIUS));
    for (bx = xl; bx <= xh; ++bx)
        for (by = yl; by <= yh; ++by)
            if (!P_BlockThingsIterator(bx, by, PIT_CheckThing))
                return false;
    xl = P_BlockX(tmbbox[BOXLEFT]);
    xh = P_BlockX(tmbbox[BOXRIGHT]);
    yl = P_BlockY(tmbbox[BOXBOTTOM]);
    yh = P_BlockY(tmbbox[BOXTOP]);
    for (bx = xl; bx <= xh; ++bx)
        for (by = yl; by <= yh; ++by)
            if (!P_BlockLinesIterator(bx, by, PIT_CheckLine))
                return false;
    return true;
}

boolean P_CheckPosition(mobj_t *thing, fixed_t x, fixed_t y)
{
    set_tm(thing, x, y);
    return check_position();
}

boolean P_TryMove(mobj_t *thing, fixed_t x, fixed_t y)
{
    fixed_t oldx, oldy;
    uint8_t side, oldside;
    line_t *ld;
    uint16_t lnum;

    floatok = false;
    if (!P_CheckPosition(thing, x, y))
        return false;
    if (!FLAG(thing->flags, MF_NOCLIP)) {
        if (tmceilingz - tmfloorz < thing->height)
            return false;
        floatok = true;
        if (!FLAG(thing->flags, MF_TELEPORT) && tmceilingz - thing->z < thing->height)
            return false;
        if (!FLAG(thing->flags, MF_TELEPORT) && tmfloorz - thing->z > 24 * FRACUNIT)
            return false;
        if (!FLAG(thing->flags, MF_DROPOFF) && !FLAG(thing->flags, MF_FLOAT)
            && tmfloorz - tmdropoffz > 24 * FRACUNIT)
            return false;
    }
    P_UnsetThingPosition(thing);
    oldx = thing->x;
    oldy = thing->y;
    thing->floorz = UNITS(tmfloorz);
    thing->ceilingz = UNITS(tmceilingz);
    thing->x = x;
    thing->y = y;
    P_SetThingPosition(thing);
    if (!FLAG(thing->flags, MF_TELEPORT) && !FLAG(thing->flags, MF_NOCLIP)) {
        while (numspechit--) {
            lnum = spechit[numspechit];
            ld = P_Line(lnum);
            side = P_PointOnLineSide(thing->x, thing->y, ld);
            oldside = P_PointOnLineSide(oldx, oldy, ld);
            if (side != oldside && ld->special)
                P_CrossSpecialLine(lnum, oldside, thing);
        }
    }
    return true;
}

boolean P_ThingHeightClip(mobj_t *thing)
{
    boolean onfloor = thing->z == FIX(thing->floorz);

    P_CheckPosition(thing, thing->x, thing->y);
    thing->floorz = UNITS(tmfloorz);
    thing->ceilingz = UNITS(tmceilingz);
    if (onfloor) {
        thing->z = tmfloorz;
    } else if (thing->z + thing->height > tmceilingz) {
        thing->z = tmceilingz - thing->height;
    }
    return tmceilingz - tmfloorz >= thing->height;
}

/* the same for a static: on its floor unless it hangs (NOGRAVITY) */
static boolean static_height_clip(sobj_t *s)
{
    fixed_t height = P_ThingHeight((mobj_t *)s);
    uint32_t flags = P_StaticFlags(s);

    tmthing = (mobj_t *)s;
    tmflags = flags;
    tmradius = FIX(P_ThingRadius((mobj_t *)s));
    tmx = FIX(s->x);
    tmy = FIX(s->y);
    tmbbox[BOXTOP] = tmy + tmradius;
    tmbbox[BOXBOTTOM] = tmy - tmradius;
    tmbbox[BOXRIGHT] = tmx + tmradius;
    tmbbox[BOXLEFT] = tmx - tmradius;
    check_position();
    if (!FLAG(flags, MF_NOGRAVITY))
        s->z = UNITS(tmfloorz);
    else if (FIX(s->z) + height > tmceilingz)
        s->z = UNITS(tmceilingz - height);
    return tmceilingz - tmfloorz >= height;
}

/* --- sliding ---------------------------------------------------------------------- */
static fixed_t bestslidefrac, secondslidefrac;
static uint16_t bestslideline, secondslideline;
static mobj_t *slidemo;
static fixed_t tmxmove, tmymove;

static void P_HitSlideLine(line_t *ld)
{
    uint8_t side;
    angle_t lineangle, moveangle, deltaangle;
    fixed_t movelen, newlen;

    if (ld->slopetype == ST_HORIZONTAL) {
        tmymove = 0;
        return;
    }
    if (ld->slopetype == ST_VERTICAL) {
        tmxmove = 0;
        return;
    }
    side = P_PointOnLineSide(slidemo->x, slidemo->y, ld);
    lineangle = R_PointToAngle2(0, 0, FIX(ld->dx), FIX(ld->dy));
    if (side == 1)
        lineangle += ANG180;
    moveangle = R_PointToAngle2(0, 0, tmxmove, tmymove);
    deltaangle = moveangle - lineangle;
    if (deltaangle > ANG180)
        deltaangle += ANG180;
    lineangle >>= ANGLETOFINESHIFT;
    deltaangle >>= ANGLETOFINESHIFT;
    movelen = P_AproxDistance(tmxmove, tmymove);
    newlen = FixedMul(movelen, fine_cosine(deltaangle));
    tmxmove = FixedMul(newlen, fine_cosine(lineangle));
    tmymove = FixedMul(newlen, fine_sine(lineangle));
}

static boolean PTR_SlideTraverse(intercept_t *in)
{
    line_t *li;

    if (!in->isaline)
        return true;                /* vanilla: I_Error */
    li = P_Line(in->line);
    if (!(li->flags & ML_TWOSIDED)) {
        if (P_PointOnLineSide(slidemo->x, slidemo->y, li))
            return true;            /* don't hit the back side */
        goto isblocking;
    }
    P_LineOpening(li);
    if (openrange < slidemo->height)
        goto isblocking;
    if (opentop - slidemo->z < slidemo->height)
        goto isblocking;
    if (openbottom - slidemo->z > 24 * FRACUNIT)
        goto isblocking;
    return true;
isblocking:
    if (in->frac < bestslidefrac) {
        secondslidefrac = bestslidefrac;
        secondslideline = bestslideline;
        bestslidefrac = in->frac;
        bestslideline = in->line;
    }
    return false;
}

void P_SlideMove(mobj_t *mo)
{
    fixed_t leadx, leady, trailx, traily, newx, newy, r = FIX(mo->radius);
    uint8_t hitcount = 0;

    slidemo = mo;
retry:
    if (++hitcount == 3)
        goto stairstep;
    if (mo->momx > 0) {
        leadx = mo->x + r;
        trailx = mo->x - r;
    } else {
        leadx = mo->x - r;
        trailx = mo->x + r;
    }
    if (mo->momy > 0) {
        leady = mo->y + r;
        traily = mo->y - r;
    } else {
        leady = mo->y - r;
        traily = mo->y + r;
    }
    bestslidefrac = FRACUNIT + 1;
    P_PathTraverse(leadx, leady, leadx + mo->momx, leady + mo->momy, PT_ADDLINES, PTR_SlideTraverse);
    P_PathTraverse(trailx, leady, trailx + mo->momx, leady + mo->momy, PT_ADDLINES, PTR_SlideTraverse);
    P_PathTraverse(leadx, traily, leadx + mo->momx, traily + mo->momy, PT_ADDLINES, PTR_SlideTraverse);
    if (bestslidefrac == FRACUNIT + 1) {
stairstep:
        if (!P_TryMove(mo, mo->x, mo->y + mo->momy))
            P_TryMove(mo, mo->x + mo->momx, mo->y);
        return;
    }
    bestslidefrac -= 0x800;
    if (bestslidefrac > 0) {
        newx = FixedMul(mo->momx, bestslidefrac);
        newy = FixedMul(mo->momy, bestslidefrac);
        if (!P_TryMove(mo, mo->x + newx, mo->y + newy))
            goto stairstep;
    }
    bestslidefrac = FRACUNIT - (bestslidefrac + 0x800);
    if (bestslidefrac > FRACUNIT)
        bestslidefrac = FRACUNIT;
    if (bestslidefrac <= 0)
        return;
    tmxmove = FixedMul(mo->momx, bestslidefrac);
    tmymove = FixedMul(mo->momy, bestslidefrac);
    P_HitSlideLine(P_Line(bestslideline));
    mo->momx = tmxmove;
    mo->momy = tmymove;
    if (!P_TryMove(mo, mo->x + tmxmove, mo->y + tmymove))
        goto retry;
}

/* --- aiming and shooting ------------------------------------------------------------ */
static boolean PTR_AimTraverse(intercept_t *in)
{
    line_t *li;
    mobj_t *th;
    fixed_t slope, thingtopslope, thingbottomslope, dist, thz;

    if (in->isaline) {
        li = P_Line(in->line);
        if (!(li->flags & ML_TWOSIDED))
            return false;
        P_LineOpening(li);
        if (openbottom >= opentop)
            return false;
        dist = FixedMul(attackrange, in->frac);
        if (li->backsector == NO_INDEX || sec_floorh[li->frontsector] != sec_floorh[li->backsector]) {
            slope = FixedDiv(openbottom - shootz, dist);
            if (slope > bottomslope)
                bottomslope = slope;
        }
        if (li->backsector == NO_INDEX || sec_ceilh[li->frontsector] != sec_ceilh[li->backsector]) {
            slope = FixedDiv(opentop - shootz, dist);
            if (slope < topslope)
                topslope = slope;
        }
        if (topslope <= bottomslope)
            return false;
        return true;
    }
    th = in->thing;
    if (th == shootthing)
        return true;
    if (!(thing_flags0(th) & MF_SHOOTABLE))
        return true;
    dist = FixedMul(attackrange, in->frac);
    thz = thing_z(th);
    thingtopslope = FixedDiv(thz + P_ThingHeight(th) - shootz, dist);
    if (thingtopslope < bottomslope)
        return true;
    thingbottomslope = FixedDiv(thz - shootz, dist);
    if (thingbottomslope > topslope)
        return true;
    if (thingtopslope > topslope)
        thingtopslope = topslope;
    if (thingbottomslope < bottomslope)
        thingbottomslope = bottomslope;
    aimslope = (thingtopslope + thingbottomslope) / 2;
    linetarget = th;
    return false;
}

static boolean PTR_ShootTraverse(intercept_t *in)
{
    fixed_t x, y, z, frac, slope, dist, thingtopslope, thingbottomslope, thz;
    line_t *li;
    mobj_t *th;
    uint16_t front, back;
    uint8_t lflags;

    if (in->isaline) {
        li = P_Line(in->line);
        if (li->special) {
            P_ShootSpecialLine(shootthing, in->line);
            li = P_Line(in->line);
        }
        lflags = li->flags;
        front = li->frontsector;
        back = li->backsector;
        if (!(lflags & ML_TWOSIDED))
            goto hitline;
        P_LineOpening(li);
        dist = FixedMul(attackrange, in->frac);
        if (back == NO_INDEX) {
            slope = FixedDiv(openbottom - shootz, dist);
            if (slope > aimslope)
                goto hitline;
            slope = FixedDiv(opentop - shootz, dist);
            if (slope < aimslope)
                goto hitline;
        } else {
            if (sec_floorh[front] != sec_floorh[back]) {
                slope = FixedDiv(openbottom - shootz, dist);
                if (slope > aimslope)
                    goto hitline;
            }
            if (sec_ceilh[front] != sec_ceilh[back]) {
                slope = FixedDiv(opentop - shootz, dist);
                if (slope < aimslope)
                    goto hitline;
            }
        }
        return true;
hitline:
        frac = in->frac - FixedDiv(4 * FRACUNIT, attackrange);
        x = trace.x + FixedMul(trace.dx, frac);
        y = trace.y + FixedMul(trace.dy, frac);
        z = shootz + FixedMul(aimslope, FixedMul(frac, attackrange));
        if (P_SectorCeilingPic(front) == skyflatnum) {
            if (z > FIX(sec_ceilh[front]))
                return false;       /* don't shoot the sky */
            if (back != NO_INDEX && P_SectorCeilingPic(back) == skyflatnum)
                return false;
        }
        P_SpawnPuff(x, y, z);
        return false;
    }
    th = in->thing;
    if (th == shootthing)
        return true;
    if (!(thing_flags0(th) & MF_SHOOTABLE))
        return true;
    dist = FixedMul(attackrange, in->frac);
    thz = thing_z(th);
    thingtopslope = FixedDiv(thz + P_ThingHeight(th) - shootz, dist);
    if (thingtopslope < aimslope)
        return true;
    thingbottomslope = FixedDiv(thz - shootz, dist);
    if (thingbottomslope > aimslope)
        return true;
    frac = in->frac - FixedDiv(10 * FRACUNIT, attackrange);
    x = trace.x + FixedMul(trace.dx, frac);
    y = trace.y + FixedMul(trace.dy, frac);
    z = shootz + FixedMul(aimslope, FixedMul(frac, attackrange));
    th = P_Actor(th);
    if (!th)
        return false;
    if (FLAG(th->flags, MF_NOBLOOD))
        P_SpawnPuff(x, y, z);
    else
        P_SpawnBlood(x, y, z, la_damage);
    if (la_damage)
        P_DamageMobj(th, shootthing, shootthing, la_damage);
    return false;
}

fixed_t P_AimLineAttack(mobj_t *t1, angle_t angle, fixed_t distance)
{
    fixed_t x2, y2;
    uint16_t fa = angle >> ANGLETOFINESHIFT;

    shootthing = t1;
    x2 = t1->x + (distance >> FRACBITS) * fine_cosine(fa);
    y2 = t1->y + (distance >> FRACBITS) * fine_sine(fa);
    shootz = t1->z + (t1->height >> 1) + 8 * FRACUNIT;
    topslope = 100 * FRACUNIT / 160;    /* (SCREENHEIGHT/2)*FRACUNIT/(SCREENWIDTH/2) */
    bottomslope = -100 * FRACUNIT / 160;
    attackrange = distance;
    linetarget = 0;
    P_PathTraverse(t1->x, t1->y, x2, y2, PT_ADDLINES | PT_ADDTHINGS, PTR_AimTraverse);
    if (linetarget) {
        /* a static target is given as its view: callers read it only */
        if (IS_STATIC(linetarget))
            linetarget = P_StaticView(AS_STATIC(linetarget));
        return aimslope;
    }
    return 0;
}

void P_LineAttack(mobj_t *t1, angle_t angle, fixed_t distance, fixed_t slope, int16_t damage)
{
    fixed_t x2, y2;
    uint16_t fa = angle >> ANGLETOFINESHIFT;

    shootthing = t1;
    la_damage = damage;
    x2 = t1->x + (distance >> FRACBITS) * fine_cosine(fa);
    y2 = t1->y + (distance >> FRACBITS) * fine_sine(fa);
    shootz = t1->z + (t1->height >> 1) + 8 * FRACUNIT;
    attackrange = distance;
    aimslope = slope;
    P_PathTraverse(t1->x, t1->y, x2, y2, PT_ADDLINES | PT_ADDTHINGS, PTR_ShootTraverse);
}

/* --- use ------------------------------------------------------------------------------ */
static mobj_t *usething;

static boolean PTR_UseTraverse(intercept_t *in)
{
    uint8_t side;
    line_t *li = P_Line(in->line);

    if (!li->special) {
        P_LineOpening(li);
        if (openrange <= 0) {
            S_StartSound(usething, sfx_noway);
            return false;           /* can't use through a wall */
        }
        return true;                /* not a special line, but keep checking */
    }
    side = P_PointOnLineSide(usething->x, usething->y, li) == 1 ? 1 : 0;
    P_UseSpecialLine(usething, in->line, side);
    return false;                   /* can't use more than one special line in a row */
}

void P_UseLines(player_t *pl)
{
    uint16_t angle;
    fixed_t x1, y1, x2, y2;

    usething = pl->mo;
    angle = pl->mo->angle >> ANGLETOFINESHIFT;
    x1 = pl->mo->x;
    y1 = pl->mo->y;
    x2 = x1 + (USERANGE >> FRACBITS) * fine_cosine(angle);
    y2 = y1 + (USERANGE >> FRACBITS) * fine_sine(angle);
    P_PathTraverse(x1, y1, x2, y2, PT_ADDLINES, PTR_UseTraverse);
}

/* --- radius attack ------------------------------------------------------------------------ */
static mobj_t *bombsource, *bombspot;
static int16_t bombdamage;

static boolean PIT_RadiusAttack(mobj_t *thing)
{
    fixed_t dx, dy, dist;

    if (!(thing_flags0(thing) & MF_SHOOTABLE))
        return true;
    /* (the cyberdemon and the spider mastermind are immune: not in E1) */
    dx = fabs32(thing_x(thing) - bombspot->x);
    dy = fabs32(thing_y(thing) - bombspot->y);
    dist = dx > dy ? dx : dy;
    dist = (dist - FIX(P_ThingRadius(thing))) >> FRACBITS;
    if (dist < 0)
        dist = 0;
    if (dist >= bombdamage)
        return true;
    thing = P_Actor(thing);
    if (thing && P_CheckSight(thing, bombspot))
        P_DamageMobj(thing, bombspot, bombsource, bombdamage - (int16_t)dist);
    return true;
}

void P_RadiusAttack(mobj_t *spot, mobj_t *source, int16_t damage)
{
    int16_t x, y, xl, xh, yl, yh;
    fixed_t dist = FIX(damage + MAXRADIUS);

    yh = P_BlockY(spot->y + dist);
    yl = P_BlockY(spot->y - dist);
    xh = P_BlockX(spot->x + dist);
    xl = P_BlockX(spot->x - dist);
    bombspot = spot;
    bombsource = source;
    bombdamage = damage;
    for (y = yl; y <= yh; ++y)
        for (x = xl; x <= xh; ++x)
            P_BlockThingsIterator(x, y, PIT_RadiusAttack);
}

/* --- sector height change ------------------------------------------------------------------- */
static boolean crushchange, nofit;

static boolean PIT_ChangeSector(mobj_t *thing)
{
    mobj_t *mo;
    sobj_t *s;
    int16_t x, y, r;

    /* A thing whose box is outside the box of the sector's lines touches
     * none of them and is not in the sector: its heights do not depend on
     * this one (vanilla clips it anyway; on the 6502 that is a whole
     * P_CheckPosition). The test is in map units, conservative on the
     * fraction of an actor's position. */
    if (IS_STATIC(thing)) {
        x = AS_STATIC(thing)->x;
        y = AS_STATIC(thing)->y;
    } else {
        x = UNITS(thing->x);
        y = UNITS(thing->y);
    }
    r = P_ThingRadius(thing);
    if (x + r < sec_bbox[BOXLEFT] || x - r > sec_bbox[BOXRIGHT]
        || y + r < sec_bbox[BOXBOTTOM] || y - r > sec_bbox[BOXTOP])
        return true;
    if (IS_STATIC(thing)) {
        s = AS_STATIC(thing);
        if (static_height_clip(s))
            return true;
        if (s->sflags & SF_CORPSE) {
            s->state = S_GIBS;
            s->tics = st_tics[S_GIBS];
            s->sflags |= SF_GIBS;   /* not solid, radius and height 0 */
            return true;
        }
        if (s->sflags & SF_DROPPED) {
            P_RemoveMobj(thing);
            return true;
        }
        if (!(thing_flags0(thing) & MF_SHOOTABLE))
            return true;
        nofit = true;
        if (crushchange && !(leveltime & 3)) {
            thing = P_Actor(thing);
            if (!thing)
                return true;
            /* on as an actor below */
        } else {
            return true;
        }
    } else {
        if (P_ThingHeightClip(thing))
            return true;
        if (thing->health <= 0) {
            P_SetMobjState(thing, S_GIBS);
            FLAGS_CLR(thing->flags, MF_SOLID);
            thing->height = 0;
            thing->radius = 0;
            return true;
        }
        if (FLAG(thing->flags, MF_DROPPED)) {
            P_RemoveMobj(thing);
            return true;
        }
        if (!FLAG(thing->flags, MF_SHOOTABLE))
            return true;
        nofit = true;
        if (!(crushchange && !(leveltime & 3)))
            return true;
    }
    P_DamageMobj(thing, 0, 0, 10);
    mo = P_SpawnMobj(thing->x, thing->y, thing->z + thing->height / 2, MT_BLOOD);
    mo->momx = (fixed_t)P_SubRandom() << 12;
    mo->momy = (fixed_t)P_SubRandom() << 12;
    return true;
}

boolean P_ChangeSector(uint16_t sector, boolean crunch)
{
    uint8_t box[4], x, y;

    nofit = false;
    crushchange = crunch;
    P_SectorBlockBox(sector, box);
    for (x = box[BOXLEFT]; x <= box[BOXRIGHT]; ++x)
        for (y = box[BOXBOTTOM]; y <= box[BOXTOP]; ++y)
            P_BlockThingsIterator(x, y, PIT_ChangeSector);
    return nofit;
}

#endif
