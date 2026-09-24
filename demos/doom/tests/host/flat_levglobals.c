/* The globals a_levdata.s reads, for its unit test in the py65 harness
 * (tests/test_game_asm.py): the test fills them as P_SetupLevel would. */
#include "p_local.h"

levarr_t levarr[11];
uint16_t numnodes, numsectors;
int16_t *sec_floorh, *sec_ceilh;
uint8_t *sec_special;
uint8_t *rej_known, *rej_bits;
uint8_t lev_scratch[4096];      /* the arrays the pointers point into */

/* ... and those a_maputl.s reads */
uint16_t numlines;
int16_t bmaporgx, bmaporgy;
uint8_t bmapwidth, bmapheight;
mobj_t **blocklinks;
sobj_t *statics, *statics_end;
uint8_t lev_arena[8192];
static uint16_t arena_used;

void *P_ArenaAlloc(uint16_t size)
{
    void *p = lev_arena + arena_used;
    uint16_t i;
    for (i = 0; i < size; ++i)
        lev_arena[arena_used + i] = 0;
    arena_used += size;
    return p;
}
