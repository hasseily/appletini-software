/* Doom for the Appletini -- the level data's hot accessors and caches
 * (docs/DESIGN.md sections 6 and 9).
 *
 * The C reference of src/game/a_levdata.s: the host build compiles this
 * file, the 6502 build the assembly (same functions, same results).
 *
 *   P_LevAddr/P_LevRead/P_LevWrite  element i of a level array (MAPARR_*)
 *                through its far descriptor (levarr, set by P_SetupLevel)
 *   P_SetSectorFloor/Ceiling/Special  the near mirrors and the far record
 *                (where the renderer reads the sector)
 *   P_Line       the line cache: LINECACHE_SIZE compact lines, direct
 *                mapped by index; the pointer is valid until a line with
 *                the same slot (index & 63) is fetched
 *   P_SetLineSpecial  far record and cache
 *   P_BlockLines the blockmap's line list of a cell, CELLCACHE_SIZE cells
 *                cached (lists of at most CELL_LINES lines)
 *   R_PointInSector  the BSP walk (vanilla R_PointInSubsector, then the
 *                subsector's sector) with NODECACHE_SIZE nodes and
 *                SSECCACHE_SIZE subsectors cached
 *   P_RejectVisible  REJECT, with the row of the last s2 cached in two
 *                bitsets (rej_known, rej_bits; p_setup.c allocates them)
 *   P_ClearCaches    at level start
 */
#include "p_local.h"

#if defined(GAME_REAL) && !defined(__CC65__)

#include <string.h>

#define GET16(b, o)     (*(int16_t *)((uint8_t *)(b) + (o)))
#define GETU16(b, o)    (*(uint16_t *)((uint8_t *)(b) + (o)))

far_t P_LevAddr(uint8_t array, uint16_t index)
{
    levarr_t *a = &levarr[array];
    uint16_t within = index & a->mask;
    uint8_t bank = a->bank;
    uint16_t off;

    if (a->log2 < 16)
        bank += (uint8_t)(index >> a->log2);
    if (a->shift != 0xFF)
        off = within << a->shift;
    else
        off = within * a->elsize;
    return FAR(bank, a->addr + off);
}

void P_LevRead(uint8_t array, uint16_t index, void *dst, uint16_t len)
{
    far_read(P_LevAddr(array, index), dst, len);
}

void P_LevWrite(uint8_t array, uint16_t index, const void *src, uint16_t len)
{
    far_write(src, P_LevAddr(array, index), len);
}

/* --- sectors ------------------------------------------------------------------- */
/* Every height change counts here: the monsters' sound flood (p_enemy.c)
 * knows from it that the openings between sectors may have changed. */
uint8_t sec_changes;

void P_SetSectorFloor(uint16_t sector, int16_t height)
{
    ++sec_changes;
    sec_floorh[sector] = height;
    far_write(&sec_floorh[sector], P_LevAddr(MAPARR_SECTORS, sector) + SECTOR_FLOORHEIGHT, 2);
}

void P_SetSectorCeiling(uint16_t sector, int16_t height)
{
    ++sec_changes;
    sec_ceilh[sector] = height;
    far_write(&sec_ceilh[sector], P_LevAddr(MAPARR_SECTORS, sector) + SECTOR_CEILINGHEIGHT, 2);
}

void P_SetSectorSpecial(uint16_t sector, uint8_t special)
{
    sec_special[sector] = special;
    far_write(&sec_special[sector], P_LevAddr(MAPARR_SECTORS, sector) + SECTOR_SPECIAL, 1);
}

/* --- lines ------------------------------------------------------------------------- */
#define LINECACHE_SIZE  64
static line_t linecache[LINECACHE_SIZE];

line_t *P_Line(uint16_t index)
{
    line_t *li = &linecache[index & (LINECACHE_SIZE - 1)];
    uint8_t b[LINEDEF_BACKSECTOR + 2 - LINEDEF_FLAGS];
    int16_t dx, dy;

    if (li->index == index)
        return li;
    far_read(P_LevAddr(MAPARR_LINEDEFS, index) + LINEDEF_FLAGS, b, sizeof b);
#define L(o) ((o) - LINEDEF_FLAGS)
    li->index = index;
    li->flags = b[L(LINEDEF_FLAGS)];
    li->special = b[L(LINEDEF_SPECIAL)];
    li->slopetype = b[L(LINEDEF_SLOPETYPE)];
    li->tag = GETU16(b, L(LINEDEF_TAG));
    dx = li->dx = GET16(b, L(LINEDEF_DX));
    dy = li->dy = GET16(b, L(LINEDEF_DY));
    li->bbox[BOXTOP] = GET16(b, L(LINEDEF_BBOX_TOP));
    li->bbox[BOXBOTTOM] = GET16(b, L(LINEDEF_BBOX_BOTTOM));
    li->bbox[BOXLEFT] = GET16(b, L(LINEDEF_BBOX_LEFT));
    li->bbox[BOXRIGHT] = GET16(b, L(LINEDEF_BBOX_RIGHT));
    /* v1 is the corner the line starts from */
    li->v1x = dx >= 0 ? li->bbox[BOXLEFT] : li->bbox[BOXRIGHT];
    li->v1y = dy >= 0 ? li->bbox[BOXBOTTOM] : li->bbox[BOXTOP];
    li->frontsector = GETU16(b, L(LINEDEF_FRONTSECTOR));
    li->backsector = GETU16(b, L(LINEDEF_BACKSECTOR));
#undef L
    return li;
}

void P_SetLineSpecial(uint16_t line, uint8_t special)
{
    line_t *li = &linecache[line & (LINECACHE_SIZE - 1)];
    if (li->index == line)
        li->special = special;
    far_write(&special, P_LevAddr(MAPARR_LINEDEFS, line) + LINEDEF_SPECIAL, 1);
}

/* --- the blockmap's line lists --------------------------------------------------------- */
#define CELLCACHE_SIZE  16
#define CELL_LINES      27
typedef struct {
    uint16_t cell;                  /* NO_INDEX = empty */
    uint8_t  count;                 /* 255: the list is longer than CELL_LINES */
    uint16_t lines[CELL_LINES];
} cellcache_t;
static cellcache_t cellcache[CELLCACHE_SIZE];

/* Up to `max` line numbers of the cell's list from position *skip on
 * (vanilla's list, including its leading 0 entry, which vanilla checks as
 * line 0) into out; *skip advances; returns the count (0: the list is
 * done). A list that fits CELL_LINES is served from the cache. */
uint8_t P_BlockLines(uint16_t cell, uint16_t *out, uint8_t max, uint16_t *skip)
{
    cellcache_t *c = &cellcache[cell & (CELLCACHE_SIZE - 1)];
    uint16_t offset, buf[16];
    uint8_t n, i;

    if (c->cell != cell) {
        /* fetch: the list's offset, then its words until $FFFF */
        P_LevRead(MAPARR_BLOCKMAP, 4 + cell, &offset, 2);
        c->cell = cell;
        c->count = 0;
        for (;;) {
            P_LevRead(MAPARR_BLOCKMAP, offset, buf, sizeof buf);
            for (i = 0; i < 16; ++i) {
                if (buf[i] == 0xFFFF)
                    goto fetched;
                if (c->count == CELL_LINES) {
                    c->count = 255;
                    goto fetched;
                }
                c->lines[c->count++] = buf[i];
            }
            offset += 16;
        }
    }
fetched:
    if (c->count != 255) {
        n = 0;
        while (*skip < c->count && n < max)
            out[n++] = c->lines[(*skip)++];
        return n;
    }
    /* a long list: read it from far memory from *skip on */
    P_LevRead(MAPARR_BLOCKMAP, 4 + cell, &offset, 2);
    offset += *skip;
    if (max > 16)
        max = 16;
    P_LevRead(MAPARR_BLOCKMAP, offset, buf, max * 2);
    for (n = 0; n < max && buf[n] != 0xFFFF; ++n)
        out[n] = buf[n];
    *skip += n;
    return n;
}

/* --- BSP: point in sector ------------------------------------------------------------------ */
#define NODECACHE_SIZE  128
typedef bspnode_t nodecache_t;
static nodecache_t nodecache[NODECACHE_SIZE];

#define SSECCACHE_SIZE  64
static uint16_t ssec_key[SSECCACHE_SIZE], ssec_sector[SSECCACHE_SIZE];

/* vanilla R_PointOnSide with the node's whole-unit fields */
static uint8_t R_PointOnSide(fixed_t x, fixed_t y, nodecache_t *node)
{
    fixed_t dx, dy, left, right;

    if (!node->dx) {
        if (x <= FIX(node->x))
            return node->dy > 0;
        return node->dy < 0;
    }
    if (!node->dy) {
        if (y <= FIX(node->y))
            return node->dx < 0;
        return node->dx > 0;
    }
    dx = x - FIX(node->x);
    dy = y - FIX(node->y);
    /* the sign shortcut: node->dy ^ node->dx ^ dx ^ dy */
    if (((uint8_t)((uint16_t)node->dy >> 8) ^ (uint8_t)((uint16_t)node->dx >> 8)
         ^ FB_(dx, 3) ^ FB_(dy, 3)) & 0x80) {
        if (((uint8_t)((uint16_t)node->dy >> 8) ^ FB_(dx, 3)) & 0x80)
            return 1;
        return 0;
    }
    left = FixedMul((fixed_t)node->dy, dx);
    right = FixedMul(dy, (fixed_t)node->dx);
    return right < left ? 0 : 1;
}

/* The node's partition and children, from the cache (direct mapped by
 * number) or far memory. */
bspnode_t *P_Node(uint16_t nodenum)
{
    nodecache_t *nc = &nodecache[nodenum & (NODECACHE_SIZE - 1)];
    uint8_t b[NODE_CHILD1 + 2];

    if (nc->node != nodenum) {
        far_read(P_LevAddr(MAPARR_NODES, nodenum), b, sizeof b);
        nc->node = nodenum;
        nc->x = GET16(b, NODE_X);
        nc->y = GET16(b, NODE_Y);
        nc->dx = GET16(b, NODE_DX);
        nc->dy = GET16(b, NODE_DY);
        nc->child[0] = GETU16(b, NODE_CHILD0);
        nc->child[1] = GETU16(b, NODE_CHILD1);
    }
    return nc;
}

uint16_t R_PointInSector(fixed_t x, fixed_t y)
{
    uint16_t nodenum, ss;
    nodecache_t *nc;
    uint8_t i;

    if (!numnodes) {
        ss = 0;
    } else {
        nodenum = numnodes - 1;
        while (!(nodenum & 0x8000)) {
            nc = P_Node(nodenum);
            nodenum = nc->child[R_PointOnSide(x, y, nc)];
        }
        ss = nodenum & 0x7FFF;
    }
    i = ss & (SSECCACHE_SIZE - 1);
    if (ssec_key[i] != ss) {
        ssec_key[i] = ss;
        far_read(P_LevAddr(MAPARR_SSECTORS, ss) + SSECTOR_SECTOR, &ssec_sector[i], 2);
    }
    return ssec_sector[i];
}

/* --- reject ------------------------------------------------------------------------------------ */
/* The bits of the row of sector s2 (usually the player's): REJECT bit
 * s1 * numsectors + s2 is read once per s1 while s2 stays the same. */
static uint16_t rej_s2 = NO_INDEX;

boolean P_RejectVisible(uint16_t s1, uint16_t s2)
{
    uint32_t pnum;
    uint8_t mask = 1 << (s1 & 7), byte;
    uint16_t i = s1 >> 3;

    if (s2 != rej_s2) {
        rej_s2 = s2;
        memset(rej_known, 0, (numsectors + 7) >> 3);
    }
    if (!(rej_known[i] & mask)) {
        pnum = (uint32_t)s1 * numsectors + s2;
        byte = far_peek(P_LevAddr(MAPARR_REJECT, (uint16_t)(pnum >> 3)));
        rej_known[i] |= mask;
        if (byte & (1 << ((uint8_t)pnum & 7)))
            rej_bits[i] |= mask;
        else
            rej_bits[i] &= ~mask;
    }
    return !(rej_bits[i] & mask);
}


void P_ClearCaches(void)
{
    uint8_t i;
    for (i = 0; i < LINECACHE_SIZE; ++i)
        linecache[i].index = NO_INDEX;
    for (i = 0; i < NODECACHE_SIZE; ++i)
        nodecache[i].node = NO_INDEX;
    for (i = 0; i < SSECCACHE_SIZE; ++i)
        ssec_key[i] = NO_INDEX;
    for (i = 0; i < CELLCACHE_SIZE; ++i)
        cellcache[i].cell = NO_INDEX;
    rej_s2 = NO_INDEX;
}


#endif
