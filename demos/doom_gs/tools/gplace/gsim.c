/* gsim: the dry run of a placement of the tic code on recorded call
   traffic (gtrace's events): gcall.s's paging replayed, a load counted
   with its pages wherever FCALL would load (docs/speed-parts/place.md).
   GPL-2, the port's own.

   Usage: gsim UNITS TICUNIT EVENTS UNITMAP [EVENTS UNITMAP ...]
   UNITMAP: lines "local global" (each trace's unit numbers to the common
   ones; a unit the map leaves out is the core's: 1). Then on stdin, a line
   a question:

     P POLICY G_0..G_{UNITS-1} S_0..S_255 N_0..N_255
       a placement: unit u in group G_u (0 the core, 254 outside: a caller
       the tic image does not hold), group g in slot S_g with N_g pages.
       Slots 1 and 2 are W's; slots FIRST_FRAME and up are frame slots
       (main $2000-$5FFF: glayout.py frame_slots), one group each, loaded
       at its first call in a phase and its colormap pages restored once
       at the phase's end, all of a phase's restores in one memory-API
       request (gcall.s gr_load, fs_restore; every load is a PRIVATE
       request since docs/SPEED.md 10). POLICY 0: gcall.s's restore (the
       slot's group at the
       call is loaded again at the return when another is there); 1: the
       lazy restore (only the group the slot's innermost active call
       needs).
       Answer: for each trace "loads pages cross tics phases fpages
       rpages floads restores rreqs", where loads counts every load, pages
       a W slot's loads' pages, cross the calls that go through fc_call's
       path (the target in a group, not the caller's), fpages the frame
       slots' loads' pages, rpages the pages their restores copy back,
       floads the frame slots' loads, restores their restores (a
       descriptor each) and rreqs the restores' requests (one a phase that
       loaded a frame slot).
     V ... (as P): the check against the loads the trace recorded (gr_load's
       writes of SLOT_GRP): for each trace "bad_phases rec_loads sim_loads
       rec_groups_sum sim_groups_sum" (a phase is bad when its loads'
       count or their groups' sum differ).
     D ... (as P): the loads by their cause: lines "trace kind caller
       callee loads pages" (kind 0 a call's load, 1 a return's), "end".

   A trace's events: uint16 triples (op, a, b): 0 call (caller, callee), 1
   return, 2 a phase's start (the slots empty), 3 a recorded load (group,
   slot), 4 the phase's end. */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXT 32
#define MAXD 4096
#define NG 256
#define OUT 254
#define EMPTY 255
#define FIRST_FRAME 3           /* glayout.py FRAME_FIRST */
#define MAXS (FIRST_FRAME + 16) /* and FS_MAX */

typedef struct { uint8_t op; uint16_t a, b; } event;

static event *tr[MAXT];
static size_t trn[MAXT];
static long tics[MAXT];
static int ntr, units;

static void fail(const char *what)
{
    fprintf(stderr, "gsim: %s\n", what);
    exit(2);
}

static void load_trace(int t, const char *events, const char *map,
                       int tic_unit)
{
    int *glob = NULL;
    size_t nglob = 0;
    FILE *m = fopen(map, "r");
    if (!m)
        fail("cannot read a unit map");
    int lo, gl;
    while (fscanf(m, "%d %d", &lo, &gl) == 2) {
        if (lo < 0 || lo > 65535 || gl < 0 || gl >= units)
            fail("bad unit map");
        if ((size_t)lo >= nglob) {
            size_t n = (size_t)lo + 1;
            glob = realloc(glob, n * sizeof(int));
            if (!glob)
                fail("out of memory");
            for (size_t i = nglob; i < n; i++)
                glob[i] = 1;
            nglob = n;
        }
        glob[lo] = gl;
    }
    fclose(m);
    FILE *f = fopen(events, "rb");
    if (!f)
        fail("cannot read a trace");
    if (fseek(f, 0, SEEK_END))
        fail("cannot size a trace");
    long n = ftell(f);
    if (n < 0 || n % 6)
        fail("a trace of a bad size");
    rewind(f);
    uint8_t *raw = malloc((size_t)n ? (size_t)n : 1);
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n)
        fail("short trace");
    fclose(f);
    trn[t] = (size_t)n / 6;
    tr[t] = malloc(trn[t] * sizeof(event) + 1);
    if (!tr[t])
        fail("out of memory");
    for (size_t i = 0; i < trn[t]; i++) {
        const uint8_t *w = raw + 6 * i;
        event *e = &tr[t][i];
        e->op = w[0];
        e->a = (uint16_t)(w[2] | w[3] << 8);
        e->b = (uint16_t)(w[4] | w[5] << 8);
        if (e->op == 0) {
            e->a = (uint16_t)(e->a < nglob ? glob[e->a] : 1);
            e->b = (uint16_t)(e->b < nglob ? glob[e->b] : 1);
            if (e->b == tic_unit)
                tics[t]++;
        }
    }
    free(raw);
    free(glob);
}

static int grp[65536], slot[NG], pages[NG];

typedef struct { int slot, saved, caller, callee; } frame;

static frame st[MAXD];

typedef struct { int kind, caller, callee; long loads, pages; } cause;

static cause *causes;
static size_t ncauses, capcauses;

static void note(int kind, int caller, int callee, int pg)
{
    for (size_t i = 0; i < ncauses; i++)
        if (causes[i].kind == kind && causes[i].caller == caller &&
                causes[i].callee == callee) {
            causes[i].loads++;
            causes[i].pages += pg;
            return;
        }
    if (ncauses == capcauses) {
        capcauses = capcauses ? 2 * capcauses : 256;
        causes = realloc(causes, capcauses * sizeof(cause));
        if (!causes)
            fail("out of memory");
    }
    causes[ncauses++] = (cause){kind, caller, callee, 1, pg};
}

static void run(int t, int policy, char mode)
{
    long loads = 0, pg = 0, cross = 0, phases = 0;
    long fpg = 0, rpg = 0, floads = 0, restores = 0, rreqs = 0;
    long bad = 0, rec_loads = 0, sim_loads = 0, rec_sum = 0, sim_sum = 0;
    long ph_rec = 0, ph_sim = 0, ph_rsum = 0, ph_ssum = 0;
    int cur[MAXS], need[MAXS], used[MAXS];
    int depth = 0, overflow = 0;
    for (int k = 0; k < MAXS; k++)
        cur[k] = need[k] = EMPTY, used[k] = 0;
    ncauses = 0;
    const event *e = tr[t];
    for (size_t i = 0; i < trn[t]; i++, e++) {
        switch (e->op) {
        case 2: {
            /* (a phase's start: the last one's frame slots restored, one
               request) */
            int any = 0;
            for (int k = 0; k < MAXS; k++) {
                if (used[k])
                    rpg += used[k], restores++, any = 1;
                cur[k] = need[k] = EMPTY;
                used[k] = 0;
            }
            rreqs += any;
            depth = 0;
            phases++;
            ph_rec = ph_sim = ph_rsum = ph_ssum = 0;
            break;
        }
        case 4:
            if (ph_rec != ph_sim || ph_rsum != ph_ssum)
                bad++;
            break;
        case 3:
            rec_loads++;
            rec_sum += e->a;
            ph_rec++;
            ph_rsum += e->a;
            break;
        case 0: {
            int ga = grp[e->a], gb = grp[e->b];
            if (depth == MAXD) {
                overflow = 1;
                break;
            }
            frame *f = &st[depth++];
            f->slot = 0;
            f->caller = e->a;
            f->callee = e->b;
            if (gb != 0 && gb != ga && gb != OUT) {
                int s = slot[gb];
                cross++;
                f->slot = s;
                f->saved = policy ? need[s] : cur[s];
                if (policy)
                    need[s] = gb;
                if (cur[s] != gb) {
                    cur[s] = gb;
                    loads++;
                    if (s >= FIRST_FRAME) {
                        floads++;
                        fpg += pages[gb];
                        if (pages[gb] > used[s])
                            used[s] = pages[gb];
                    } else
                        pg += pages[gb];
                    sim_loads++;
                    sim_sum += gb;
                    ph_sim++;
                    ph_ssum += gb;
                    if (mode == 'D')
                        note(0, e->a, e->b, pages[gb]);
                }
            }
            break;
        }
        case 1: {
            if (!depth)
                break;
            frame *f = &st[--depth];
            if (!f->slot)
                break;
            int s = f->slot, old = f->saved;
            if (policy)
                need[s] = old;
            if (old != EMPTY && cur[s] != old) {
                cur[s] = old;
                loads++;
                if (s >= FIRST_FRAME) {
                    floads++;
                    fpg += pages[old];
                    if (pages[old] > used[s])
                        used[s] = pages[old];
                } else
                    pg += pages[old];
                sim_loads++;
                sim_sum += old;
                ph_sim++;
                ph_ssum += old;
                if (mode == 'D')
                    note(1, f->caller, f->callee, pages[old]);
            }
            break;
        }
        default:
            break;
        }
    }
    if (overflow)
        fail("a trace deeper than the model's stack");
    int any = 0;                        /* (the last phase's restores) */
    for (int k = 0; k < MAXS; k++)
        if (used[k])
            rpg += used[k], restores++, any = 1;
    rreqs += any;
    if (mode == 'V')
        printf("%ld %ld %ld %ld %ld ", bad, rec_loads, sim_loads, rec_sum,
               sim_sum);
    else if (mode == 'D') {
        for (size_t i = 0; i < ncauses; i++)
            printf("%d %d %d %d %ld %ld\n", t, causes[i].kind,
                   causes[i].caller, causes[i].callee, causes[i].loads,
                   causes[i].pages);
    } else
        printf("%ld %ld %ld %ld %ld %ld %ld %ld %ld %ld ", loads, pg, cross,
               tics[t], phases, fpg, rpg, floads, restores, rreqs);
}

int main(int argc, char **argv)
{
    if (argc < 5 || (argc - 3) % 2) {
        fprintf(stderr, "usage: gsim UNITS TICUNIT EVENTS UNITMAP "
                "[EVENTS UNITMAP ...]\n");
        return 2;
    }
    units = atoi(argv[1]);
    int tic_unit = atoi(argv[2]);
    if (units < 2 || units > 65535)
        fail("bad unit count");
    ntr = (argc - 3) / 2;
    if (ntr > MAXT)
        fail("too many traces");
    for (int t = 0; t < ntr; t++)
        load_trace(t, argv[3 + 2 * t], argv[4 + 2 * t], tic_unit);
    char mode[4];
    int policy;
    while (scanf("%3s %d", mode, &policy) == 2) {
        for (int u = 0; u < units; u++)
            if (scanf("%d", &grp[u]) != 1 || grp[u] < 0 || grp[u] >= NG)
                fail("bad placement");
        for (int g = 0; g < NG; g++)
            if (scanf("%d", &slot[g]) != 1 || slot[g] < 0 ||
                    slot[g] >= MAXS)
                fail("bad slots");
        for (int g = 0; g < NG; g++)
            if (scanf("%d", &pages[g]) != 1 || pages[g] < 0)
                fail("bad pages");
        for (int t = 0; t < ntr; t++)
            run(t, policy, mode[0]);
        if (mode[0] == 'D')
            printf("end");
        printf("\n");
        fflush(stdout);
    }
    return 0;
}
