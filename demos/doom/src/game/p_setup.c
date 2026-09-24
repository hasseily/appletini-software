/* Doom for the Appletini -- the level: loading it (docs/DESIGN.md sections
 * 6 and 9).
 *
 * The converter has already done vanilla's P_SetupLevel work that needs
 * the whole WAD (sectors resolved, lines with their bounding boxes and
 * sectors, P_GroupLines' line lists) and left every array in far memory
 * (MAPDIR). P_SetupLevel reads the map's descriptors into levarr, resets
 * the level arena and fills it:
 *
 *   blocklinks   the blockmap's thing chains (vanilla's)
 *   sec_floorh/sec_ceilh/sec_special  every sector's heights and special
 *                (the fields the play code reads all the time); a change
 *                goes through P_SetSector* (p_levdata.c), which also
 *                writes the far record, where the renderer reads it
 *   sec_soundtarget  the monsters' (vanilla sector_t.soundtarget)
 *   rej_known/rej_bits  the reject row cache
 *   the thinker blocks (p_tick.c) and the thing pools (p_mobj.c)
 *
 * then spawns the map's things and calls the other parts' level set-up.
 * The hot accessors and caches of the level data are in p_levdata.c
 * (a_levdata.s on the 6502); the rarely used ones are here.
 *
 * The level arena is the memory above the C BSS up to the C stack
 * ($B800), plus the bytes the far tables used at boot (segment GFAR,
 * copied to the game's far bank by game_farinit) and, after the set-up,
 * those of the set-up code itself (segment GOVL, below). It is reset at
 * every level start; the other parts allocate from it in their level
 * set-up (P_SpawnSpecials, P_MonstersSetupLevel), never later.
 */
#include "p_local.h"

#ifdef GAME_REAL

#include <string.h>

#define GET16(b, o)     (*(int16_t *)((uint8_t *)(b) + (o)))
#define GETU16(b, o)    (*(uint16_t *)((uint8_t *)(b) + (o)))

/* --- the level's far arrays ------------------------------------------------ */
levarr_t levarr[11];
uint8_t *rej_known, *rej_bits;
uint16_t numsectors, numlines, numsubsectors, numnodes, numsides;
uint16_t skyflatnum = DD_SKYFLAT;

int16_t *sec_floorh, *sec_ceilh;
uint8_t *sec_special;
mobj_t **sec_soundtarget;
int16_t bmaporgx, bmaporgy;
uint8_t bmapwidth, bmapheight;
mobj_t **blocklinks;
static uint16_t bmapcells;

/* --- the arena ------------------------------------------------------------------ */
/* On the 6502 the level set-up (the arena, P_SetupLevel, and p_spawn.c's
 * map thing spawner) is an overlay, segment GOVL: linked right after the
 * far tables (GFAR), copied with them to the game's far bank at boot, and
 * read back into place before each level's set-up (P_LoadOverlay). After
 * the set-up its bytes become actor slots (P_ExtendPool): the actor pool
 * is placed at the top of the GFAR hole, right below the overlay. */
#ifdef __CC65__
#pragma code-name (push, "GOVL")
#pragma rodata-name (push, "GOVL")
extern uint16_t arena_bounds[5];    /* fixed.s: BSS end, stack bottom, GFAR start, GOVL start, GOVL end */
#define ARENA_LO    arena_bounds[0]
#define ARENA_HI    arena_bounds[1]
#define HOLE_LO     arena_bounds[2]
#define HOLE_HI     hole_hi
#define OVL_LO      arena_bounds[3]
#define OVL_HI      arena_bounds[4]
static uint16_t hole_hi;
#else
#define HOST_ARENA  (256u * 1024u)
static uint8_t host_arena[HOST_ARENA];
#define ARENA_LO    ((uintptr_t)host_arena)
#define ARENA_HI    ((uintptr_t)host_arena + HOST_ARENA)
#define HOLE_LO     0
#define HOLE_HI     0
#endif
static uintptr_t arena_ptr, hole_ptr;

static void P_ArenaReset(void)
{
    arena_ptr = ARENA_LO;
    hole_ptr = HOLE_LO;
#ifdef __CC65__
    hole_hi = OVL_LO;
#endif
}

/* Level memory, zeroed: from the main area when it fits, else the GFAR
 * hole (whose top the actor pool takes, P_ArenaPool). Pointers stay
 * 2-byte aligned (the host likes it). */
void *P_ArenaAlloc(uint16_t size)
{
    void *p;
    size = (size + 1) & ~1u;
    /* (the comparisons are written not to overflow 16-bit addresses) */
    if (ARENA_HI >= arena_ptr && size <= ARENA_HI - arena_ptr) {
        p = (void *)arena_ptr;
        arena_ptr += size;
    } else if (size <= HOLE_HI - hole_ptr) {
        p = (void *)hole_ptr;
        hole_ptr += size;
    } else {
        kernel_crash(CRASH_ARENA);
        return 0;
    }
    memset(p, 0, size);
    return p;
}

uint16_t P_ArenaFree(void)
{
    return ARENA_HI > arena_ptr ? (uint16_t)(ARENA_HI - arena_ptr) : 0;
}

#ifdef __CC65__
/* The actor pool (P_InitMobjs): the top of the GFAR hole, ending at the
 * overlay, which P_ExtendPool adds after the set-up; ARENA_RESERVE bytes
 * stay free for P_SpawnSpecials and P_MonstersSetupLevel, and the whole
 * pool (with the overlay's slots) holds at most MAXACTORS. */
void *P_ArenaPool(uint16_t *count)
{
    uint16_t avail = HOLE_HI - hole_ptr, spare, n, later;

    spare = ARENA_HI > arena_ptr ? ARENA_HI - arena_ptr : 0;
    if (spare < ARENA_RESERVE)
        avail = avail > ARENA_RESERVE - spare ? avail - (ARENA_RESERVE - spare) : 0;
    n = avail / sizeof(mobj_t);
    later = (OVL_HI - OVL_LO) / sizeof(mobj_t);
    if (n + later > MAXACTORS)
        n = MAXACTORS > later ? MAXACTORS - later : 0;
    *count = n;
    hole_hi = OVL_LO - n * sizeof(mobj_t);
    memset((void *)hole_hi, 0, n * sizeof(mobj_t));
    return (void *)hole_hi;
}
#endif

#ifdef __CC65__
#pragma code-name (pop)
#pragma rodata-name (pop)
#endif

/* --- sectors ----------------------------------------------------------------------- */
static uint16_t sector_u16(uint16_t sector, uint8_t offset)
{
    uint16_t v;
    far_read(P_LevAddr(MAPARR_SECTORS, sector) + offset, &v, 2);
    return v;
}

uint16_t P_SectorTag(uint16_t sector)       { return sector_u16(sector, SECTOR_TAG); }
uint16_t P_SectorFloorPic(uint16_t sector)  { return sector_u16(sector, SECTOR_FLOORPIC); }
uint16_t P_SectorCeilingPic(uint16_t sector) { return sector_u16(sector, SECTOR_CEILINGPIC); }

uint8_t P_SectorLight(uint16_t sector)
{
    return far_peek(P_LevAddr(MAPARR_SECTORS, sector) + SECTOR_LIGHTLEVEL);
}

void P_SetSectorLight(uint16_t sector, uint8_t light)
{
    far_write(&light, P_LevAddr(MAPARR_SECTORS, sector) + SECTOR_LIGHTLEVEL, 1);
}

uint16_t P_SectorLines(uint16_t sector, uint16_t *first)
{
    uint16_t v[2];
    far_read(P_LevAddr(MAPARR_SECTORS, sector) + SECTOR_LINECOUNT, v, 4);
    *first = v[1];
    return v[0];
}

uint16_t P_SecLine(uint16_t secline)
{
    uint16_t v;
    P_LevRead(MAPARR_SECLINES, secline, &v, 2);
    return v;
}

/* The blockmap cells a sector's things can be in (vanilla's blockbox from
 * P_GroupLines): the box of its lines, MAXRADIUS around, clamped; and the
 * box of its lines itself, in map units (sec_bbox: P_ChangeSector skips
 * the things outside it). An eight-entry cache: movers ask every tic
 * while they move, and several move at once. */
#define BBOXCACHE 8
static uint16_t bbox_key[BBOXCACHE];
static uint8_t bbox_val[BBOXCACHE][4];
static int16_t bbox_units[BBOXCACHE][4];
static uint8_t bbox_next;
int16_t sec_bbox[4];

void P_ClearBlockBoxCache(void)
{
    uint8_t i;
    for (i = 0; i < BBOXCACHE; ++i)
        bbox_key[i] = NO_INDEX;
}

void P_SectorBlockBox(uint16_t sector, uint8_t *box)
{
    uint8_t i;
    uint16_t first, count, n;
    int16_t top = INT16_MIN, bottom = INT16_MAX, left = INT16_MAX, right = INT16_MIN;
    int16_t b;
    line_t *li;

    for (i = 0; i < BBOXCACHE; ++i)
        if (bbox_key[i] == sector) {
            memcpy(box, bbox_val[i], 4);
            memcpy(sec_bbox, bbox_units[i], sizeof sec_bbox);
            return;
        }
    count = P_SectorLines(sector, &first);
    for (n = 0; n < count; ++n) {
        li = P_Line(P_SecLine(first + n));
        if (li->bbox[BOXTOP] > top) top = li->bbox[BOXTOP];
        if (li->bbox[BOXBOTTOM] < bottom) bottom = li->bbox[BOXBOTTOM];
        if (li->bbox[BOXLEFT] < left) left = li->bbox[BOXLEFT];
        if (li->bbox[BOXRIGHT] > right) right = li->bbox[BOXRIGHT];
    }
    sec_bbox[BOXTOP] = top;
    sec_bbox[BOXBOTTOM] = bottom;
    sec_bbox[BOXLEFT] = left;
    sec_bbox[BOXRIGHT] = right;
    b = (top - bmaporgy + MAXRADIUS) >> 7;
    box[BOXTOP] = b >= bmapheight ? bmapheight - 1 : (uint8_t)b;
    b = (bottom - bmaporgy - MAXRADIUS) >> 7;
    box[BOXBOTTOM] = b < 0 ? 0 : (uint8_t)b;
    b = (right - bmaporgx + MAXRADIUS) >> 7;
    box[BOXRIGHT] = b >= bmapwidth ? bmapwidth - 1 : (uint8_t)b;
    b = (left - bmaporgx - MAXRADIUS) >> 7;
    box[BOXLEFT] = b < 0 ? 0 : (uint8_t)b;
    i = bbox_next;
    bbox_next = (i + 1) & (BBOXCACHE - 1);
    bbox_key[i] = sector;
    memcpy(bbox_val[i], box, 4);
    memcpy(bbox_units[i], sec_bbox, sizeof sec_bbox);
}

uint16_t P_LineSide(uint16_t line, uint8_t side)
{
    uint16_t v;
    far_read(P_LevAddr(MAPARR_LINEDEFS, line) + (side ? LINEDEF_SIDE1 : LINEDEF_SIDE0), &v, 2);
    return v;
}

/* --- level set-up ------------------------------------------------------------------------------- */
#ifdef __CC65__
#pragma code-name (push, "GOVL")
#pragma rodata-name (push, "GOVL")
#endif

/* thing types that drop an item when killed (vanilla P_KillMobj) */
static boolean dropper(uint8_t type)
{
    return type == MT_POSSESSED || type == MT_SHOTGUY;
}

static uint8_t skill_bit(uint8_t skill)
{
    if (skill == sk_baby)
        return 1;
    if (skill == sk_nightmare)
        return 4;
    return 1 << (skill - 1);
}

uint8_t P_ThingType(uint16_t doomednum)
{
    uint8_t i;
    for (i = 0; i < NUMMOBJTYPES; ++i)
        if (mi_doomednum[i] == (int16_t)doomednum)
            return i;
    return 0xFF;
}

static uint8_t setup_buf[MAP_SIZE];    /* the MAP record, then things and sectors */

void P_SetupLevel(uint8_t episode, uint8_t map, uint8_t skill)
{
    uint8_t *rec = setup_buf, *tb = setup_buf, *sb = setup_buf;
    uint8_t *d;
    uint8_t i, k, bit;
    uint16_t n, count, nthings, statics_needed;
    int16_t hdr[4];
    uint8_t type;

    gameepisode = episode;
    gamemap = map;
    gameskill = skill;
    far_read(FAR(DD_DIR_BANK, DD_MAPDIR + MAP_SIZE * (9 * (episode - 1) + map - 1)), rec, MAP_SIZE);
    if (!rec[MAP_NAME])
        kernel_crash(CRASH_NOMAP);
    for (i = 0; i < 11; ++i) {
        d = rec + MAP_ARRAYS + DESC_SIZE * i;
        levarr[i].bank = d[DESC_BANK];
        levarr[i].addr = GETU16(d, DESC_ADDR);
        levarr[i].elsize = d[DESC_ELSIZE];
        levarr[i].log2 = d[DESC_LOG2];
        levarr[i].mask = d[DESC_LOG2] >= 16 ? 0xFFFF : (uint16_t)((1u << d[DESC_LOG2]) - 1);
        levarr[i].count = GETU16(d, DESC_COUNT);
        levarr[i].shift = 0xFF;
        for (k = 0; k < 8; ++k)
            if (d[DESC_ELSIZE] == (1 << k))
                levarr[i].shift = k;
    }
    numsectors = levarr[MAPARR_SECTORS].count;
    numlines = levarr[MAPARR_LINEDEFS].count;
    numsubsectors = levarr[MAPARR_SSECTORS].count;
    numnodes = levarr[MAPARR_NODES].count;
    numsides = levarr[MAPARR_SIDEDEFS].count;
    P_ClearCaches();
    P_ClearBlockBoxCache();

    /* the arena: blockmap chains, sectors, reject row, the pools */
    P_ArenaReset();
    P_LevRead(MAPARR_BLOCKMAP, 0, hdr, 8);
    bmaporgx = hdr[0];
    bmaporgy = hdr[1];
    bmapwidth = (uint8_t)hdr[2];
    bmapheight = (uint8_t)hdr[3];
    bmapcells = (uint16_t)bmapwidth * bmapheight;
    blocklinks = P_ArenaAlloc(bmapcells * sizeof(mobj_t *));
    sec_floorh = P_ArenaAlloc(numsectors * 2);
    sec_ceilh = P_ArenaAlloc(numsectors * 2);
    sec_special = P_ArenaAlloc(numsectors);
    sec_soundtarget = P_ArenaAlloc(numsectors * sizeof(mobj_t *));
    rej_known = P_ArenaAlloc((numsectors + 7) >> 3);
    rej_bits = P_ArenaAlloc((numsectors + 7) >> 3);
    P_InitLineMarks();
    for (n = 0; n < numsectors; n += 8) {
        count = numsectors - n < 8 ? numsectors - n : 8;
        P_LevRead(MAPARR_SECTORS, n, sb, count * SECTOR_SIZE);
        for (i = 0; i < count; ++i) {
            sec_floorh[n + i] = GET16(sb, SECTOR_SIZE * i + SECTOR_FLOORHEIGHT);
            sec_ceilh[n + i] = GET16(sb, SECTOR_SIZE * i + SECTOR_CEILINGHEIGHT);
            sec_special[n + i] = sb[SECTOR_SIZE * i + SECTOR_SPECIAL];
        }
    }

    /* count the things this skill spawns: the statics pool holds them all,
     * and an item for each monster that drops one */
    nthings = levarr[MAPARR_THINGS].count;
    bit = skill_bit(skill);
    statics_needed = 8;
    for (n = 0; n < nthings; n += 8) {
        count = nthings - n < 8 ? nthings - n : 8;
        P_LevRead(MAPARR_THINGS, n, tb, count * THING_SIZE);
        for (i = 0; i < count; ++i) {
            d = tb + THING_SIZE * i;
            if (GETU16(d, THING_TYPE) <= 4 || GETU16(d, THING_TYPE) == 11)
                continue;
            if ((d[THING_FLAGS] & 16) || !(d[THING_FLAGS] & bit))
                continue;
            type = P_ThingType(GETU16(d, THING_TYPE));
            if (type == 0xFF)
                continue;
            ++statics_needed;
            if (dropper(type))
                ++statics_needed;
        }
    }
    P_InitThinkers();
    P_InitMobjs(statics_needed);
    leveltime = 0;
    totalkills = totalitems = totalsecret = 0;

    /* spawn */
    for (n = 0; n < nthings; n += 8) {
        count = nthings - n < 8 ? nthings - n : 8;
        P_LevRead(MAPARR_THINGS, n, tb, count * THING_SIZE);
        for (i = 0; i < count; ++i) {
            d = tb + THING_SIZE * i;
            P_SpawnMapThing(GET16(d, THING_X), GET16(d, THING_Y), GET16(d, THING_ANGLE),
                            GETU16(d, THING_TYPE), GETU16(d, THING_FLAGS));
        }
    }
    P_SpawnSpecials();
    P_MonstersSetupLevel();
}

#ifdef __CC65__
#pragma code-name (pop)
#pragma rodata-name (pop)
#endif

#endif
