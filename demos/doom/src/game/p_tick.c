/* Doom for the Appletini -- thinkers and the tic (docs/DESIGN.md section 9).
 *
 * Vanilla p_tick.c: one doubly linked list of thinkers (the actors, and
 * the movers, lights and switches of the specials part), run in order
 * every tic; a removed thinker is marked (THINK_REMOVED) and unlinked the
 * next time the run reaches it, so that pointers to it stay usable until
 * then, as vanilla's Z_Free after the run did.
 *
 * Memory: an actor goes back to its pool (p_mobj.c); any other thinker is
 * a block of the thinker pool below, THINKER_BLOCKS blocks of
 * THINKER_BLOCK bytes allocated in the level arena (vanilla's
 * Z_Malloc(PU_LEVSPEC)): P_AllocThinker returns a zeroed block, the run
 * frees it after its removal.
 *
 * P_Ticker is vanilla's (one player): the player, the thinkers, then the
 * statics (p_mobj.c), the specials, and leveltime.
 */
#include "p_local.h"

/* on the 6502 this is a_mobj.s */
#if defined(GAME_REAL) && !defined(__CC65__)

#include <string.h>

thinker_t thinkercap;
static uint8_t *tblocks;            /* THINKER_BLOCKS x THINKER_BLOCK */
static uint8_t tblock_used[THINKER_BLOCKS];

void P_InitThinkers(void)
{
    thinkercap.prev = thinkercap.next = &thinkercap;
    tblocks = P_ArenaAlloc(THINKER_BLOCKS * THINKER_BLOCK);
    memset(tblock_used, 0, sizeof tblock_used);
}

thinker_t *P_AllocThinker(uint8_t size)
{
    uint8_t i;
    if (size <= THINKER_BLOCK)
        for (i = 0; i < THINKER_BLOCKS; ++i)
            if (!tblock_used[i]) {
                tblock_used[i] = 1;
                memset(tblocks + i * THINKER_BLOCK, 0, THINKER_BLOCK);
                return (thinker_t *)(tblocks + i * THINKER_BLOCK);
            }
    kernel_crash(CRASH_ARENA);
    return 0;
}

void P_AddThinker(thinker_t *thinker)
{
    thinkercap.prev->next = thinker;
    thinker->next = &thinkercap;
    thinker->prev = thinkercap.prev;
    thinkercap.prev = thinker;
}

void P_RemoveThinker(thinker_t *thinker)
{
    thinker->function = THINK_REMOVED;
}

void P_UnlinkThinker(thinker_t *thinker)
{
    thinker->next->prev = thinker->prev;
    thinker->prev->next = thinker->next;
}

static void free_thinker(thinker_t *t)
{
    if ((void *)t >= (void *)mobjs && (void *)t < (void *)mobjs_end)
        P_FreeActor((mobj_t *)t);
    else
        tblock_used[((uint8_t *)t - tblocks) / THINKER_BLOCK] = 0;
}

void P_RunThinkers(void)
{
    thinker_t *current = thinkercap.next, *next;

    while (current != &thinkercap) {
        if (current->function == THINK_REMOVED) {
            next = current->next;
            P_UnlinkThinker(current);
            free_thinker(current);
        } else {
            if (current->function)
                current->function(current);
            next = current->next;
        }
        current = next;
    }
}

void P_Ticker(void)
{
    P_PlayerThink(&player);
    P_RunThinkers();
    P_RunStatics();
    P_UpdateSpecials();
    ++leveltime;
}

#endif
