/*
 * Points of a run: the moments at which main.c dumps memory (--dump-at)
 * or writes it (--poke-file), and the choice of calls that calllog.c logs
 * (--call-log).
 *
 * A point is written as KEY=VALUE items separated by commas. The first
 * says what the point is:
 *
 *   pc=ADDR        each time the CPU reaches ADDR (hex, 24 bits: PBR and
 *                  PC), before the instruction there, as --mark does
 *   frame=SET      the start of each video frame of SET: the first
 *                  instruction boundary of the frame, after the steps of
 *                  the input due then (as --frames and --shot-frame)
 *   cycle=SET      for each N of SET, the first instruction boundary at
 *                  which the CPU has made N cycles or more (as --cycles)
 *
 * The others, in any order:
 *
 *   hits=SET       pc only: which arrivals, counted from 1 (default: all)
 *   after=NOTE     only once the note NOTE of the input has come
 *   if=ADDR:SIZE:TEST:VALUE
 *                  only when the SIZE-byte (1, 2 or 4) little-endian
 *                  value at ADDR (hex) passes TEST: eq, ne, lt, le, gt or
 *                  ge VALUE (unsigned; 0x for hex)
 *   ranges=R+R...  dumps only: what to dump (default: all RAM in the order
 *                  of --dump-ram, banks $00-$7F then $E0-$E1). R is a bank
 *                  BB, banks BB-BB, or ADDR:LEN (hex address; LEN decimal,
 *                  or hex with 0x), all in RAM
 *
 * SET is N, N-M (both included), N-M/K or N-/K (every Kth from N), or
 * "all"; numbers are decimal, or hex with 0x. An arrival or a frame that
 * fails `after` or `if` is not a hit: hits=1 with after=NOTE is the first
 * arrival after the note.
 *
 * A point only reads the machine (iigs_peek); it never changes it.
 */
#ifndef POINTS_H
#define POINTS_H

#include <stddef.h>
#include <stdint.h>

#include "iigs.h"

enum {
    POINT_NAME = 64,            /* a note's name, with its NUL */
    POINT_RANGES = 32
};

/* first, first + every, ... up to last (UINT64_MAX: no end). */
typedef struct {
    uint64_t first, last, every;
} point_set;

typedef enum { POINT_PC, POINT_FRAME, POINT_CYCLE } point_kind;

typedef enum {
    POINT_ALWAYS, POINT_EQ, POINT_NE, POINT_LT, POINT_LE, POINT_GT, POINT_GE
} point_test;

typedef struct {
    point_kind kind;
    uint32_t pc;                /* POINT_PC */
    point_set set;              /* hits, frames or cycles */
    char after[POINT_NAME];     /* "" for none */
    point_test test;
    uint32_t test_address, test_value;
    unsigned test_size;
    uint32_t range_address[POINT_RANGES], range_length[POINT_RANGES];
    unsigned range_count;       /* 0: all RAM */

    /* While the run goes on. */
    int after_seen;
    uint64_t hits;              /* arrivals that passed after and if */
    uint64_t next;              /* frame, cycle: the next member of set */
    uint64_t last_hit;          /* point_hit */
} point;

/* What a text may hold. */
typedef enum {
    POINT_FOR_DUMP,             /* pc, frame or cycle, and ranges */
    POINT_FOR_POKE,             /* pc, frame or cycle */
    POINT_FOR_CALL              /* no kind: hits, after, if only */
} point_use;

/* Parse `text` into `p` (a POINT_FOR_CALL is a pc point with pc 0: the
   caller sets it). Returns 0 with a message in `error` when the text is
   not a point. */
int point_parse(point *p, const char *text, point_use use, char *error,
                size_t size);

/* One KEY=VALUE item of a point (hits, after, if, or with
   POINT_FOR_DUMP ranges); `known` is 0 when the key is none of these.
   Returns 0 with a message in `error` for a bad value. calllog.c parses
   its own keys and passes the rest here. */
int point_item(point *p, const char *key, const char *value, point_use use,
               int *known, char *error, size_t size);

/* Whether `set` has `value`, and its smallest member at or above
   `value` (UINT64_MAX when none). */
int point_set_has(const point_set *set, uint64_t value);
uint64_t point_set_next(const point_set *set, uint64_t value);

/* The note `name` of the input has come. */
void point_note(point *p, const char *name);

/* Whether `after` and `if` pass now. */
int point_passes(const point *p, const iigs *m);

/* The machine stopped between instructions; `at_pc` is 1 when it
   stopped at a breakpoint at p->pc. Whether the point fires now: counts
   its hit, and moves a frame or cycle point on to its next member. */
int point_fires(point *p, const iigs *m, int at_pc);

/* The frame or cycle at which a frame or cycle point is next due
   (UINT64_MAX for none, or for another kind). */
uint64_t point_due_frame(const point *p);
uint64_t point_due_cycle(const point *p);

/* The number of the hit that fired last: the arrival for pc, else the
   frame or the cycle count of the set. */
uint64_t point_hit(const point *p);

/* The bytes a dump of the point writes. */
uint64_t point_dump_bytes(const point *p);

#endif
