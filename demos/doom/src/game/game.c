/* Doom for the Appletini -- the GAME space skeleton (docs/DESIGN.md
 * section 9).
 *
 * The platform's stand-in for Doom's play simulation: it proves the
 * pieces the real game will stand on. game_init runs once from the C
 * start-up (crt0.s); game_tic runs once per 35 Hz tic. Each tic counts
 * itself, keeps a copy of the input block and reads one element of a far
 * array through far_elem + far_read: the stand-in data set's probe array
 * (DD_PROBE_*, chunked over several banks, tools/make_standin.py) when the
 * data has one, else one entry of the converter's PLAYPAL. tests/test_platform.py checks the counters and
 * the element read against the data.
 *
 * It is built only against the platform's stand-in data set (no MAPDIR):
 * with the converter's data the real game (g_game.c and the p_*.c
 * modules) provides game_init, game_tic and game_frame.
 */
#include "kernel.h"
#include "doomdata.h"

#ifndef DD_MAPDIR

unsigned long game_tics;
unsigned char game_inits;
struct kinput game_input;       /* kin as seen by the last tic */
int game_turn;                  /* the sum of mouse_dx over the tics */
unsigned int probe_index;
far_t probe_addr;
unsigned char probe_value[8];

#if defined(DD_PROBE_BANK)
static const struct far_array probe_array = {
    DD_PROBE_BANK, DD_PROBE_ADDR, DD_PROBE_SIZE, DD_PROBE_LOG2
};
#define PROBE_COUNT DD_PROBE_COUNT
#define PROBE_SIZE  DD_PROBE_SIZE
#elif defined(DD_PLAYPAL)
static const struct far_array probe_array = {
    DD_DIR_BANK, DD_PLAYPAL, 2, 15
};
#define PROBE_COUNT (256 * 14)
#define PROBE_SIZE  2
#endif

void game_init(void)
{
    ++game_inits;
    game_tics = 0;
}

void game_tic(void)
{
    ++game_tics;
    game_input = kin;
    game_turn += kin.mouse_dx;
#ifdef PROBE_COUNT
    /* a stride that walks across the chunk boundaries */
    probe_index = (unsigned int)((game_tics * 1021UL) % PROBE_COUNT);
    probe_addr = far_elem(&probe_array, probe_index);
    far_read(probe_addr, probe_value, PROBE_SIZE);
#endif
}

/* the render packet hook (the stand-in renderer does not read one) */
void game_frame(void)
{
}

#endif
