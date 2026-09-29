/*
 * The input program of a run: what happens to the machine, and when, as
 * a list of steps done one after the other at the start of video frames.
 *
 * A step is a line
 *
 *   WHEN ACTION ARGUMENTS            (# starts a comment)
 *
 * WHEN is N, the start of video frame N since power-on, or +N, N frames
 * after the step before (a step before a first one is at frame 0). A step
 * is due at that frame, and done at the first instruction boundary of it.
 * An absolute frame that is already past when its step comes up is an
 * error (PROGRAM_LATE): the run would not be the one written down.
 *
 *   key CODE down|up           an ADB key code 0-127
 *   mouse DX DY                mouse motion
 *   button 0|1 down|up         a mouse button
 *   shot NAME                  a screen dump NAME.shr (the caller writes it)
 *   note NAME                  a line in the log of marks (main.c), to
 *                              measure between two points of the run
 *   poke ADDRESS SIZE VALUE    SIZE (1, 2 or 4) bytes of RAM, little-endian
 *   wait ADDRESS SIZE TEST VALUE LIMIT
 *                              from WHEN on, the start of the first frame
 *                              at which the SIZE-byte value at ADDRESS
 *                              passes TEST: eq, ne, ge or lt VALUE
 *                              (unsigned), or gain: it has grown by VALUE
 *                              or more (modulo its size) since the wait
 *                              began. The steps after it count from that
 *                              frame. PROGRAM_TIMEOUT when it has not
 *                              passed LIMIT frames after WHEN.
 *   stop                       the end of the run
 *
 * Numbers take a 0x prefix for hexadecimal. Only frame starts matter, so
 * the steps done are the same however often the caller stops the machine
 * within a frame (for screen dumps or breakpoints).
 */
#ifndef PROGRAM_H
#define PROGRAM_H

#include <stddef.h>
#include <stdint.h>

#include "iigs.h"

enum { PROGRAM_NAME = 64 };

typedef enum {
    STEP_KEY, STEP_MOUSE, STEP_BUTTON, STEP_SHOT, STEP_NOTE, STEP_POKE,
    STEP_WAIT, STEP_STOP
} step_kind;

typedef enum { TEST_EQ, TEST_NE, TEST_GE, TEST_LT, TEST_GAIN } wait_test;

typedef struct {
    unsigned line;              /* in the file, for messages */
    int relative;
    uint64_t when;
    step_kind kind;
    int a, b;                   /* key: code, down; mouse: dx, dy;
                                   button: number, down */
    uint32_t address;           /* poke, wait */
    unsigned size;
    uint32_t value;
    wait_test test;
    uint64_t limit;
    char name[PROGRAM_NAME];    /* shot, note */
} step;

typedef struct {
    step *steps;
    size_t count;
    size_t next;                /* the step to do next */
    uint64_t time;              /* the frame of the last step done */
    int started;                /* the next step's frame is fixed: */
    uint64_t due;               /*   the frame it is due, */
    uint64_t wait_from;         /*   a wait: its WHEN, */
    uint32_t wait_start;        /*   the value it began with */
} program;

typedef enum {
    PROGRAM_IDLE,               /* nothing to do before program_due */
    PROGRAM_DONE,               /* a step is done: call again */
    PROGRAM_SHOT,               /* the step is a shot: write it, call again */
    PROGRAM_NOTE,               /* the same for a note */
    PROGRAM_STOP,
    PROGRAM_TIMEOUT,            /* the step is a wait that did not pass */
    PROGRAM_LATE,               /* the step's frame was past */
    PROGRAM_END                 /* no steps left */
} program_result;

/* Read the program at `path`. On an error returns 0 with a message
   "PATH:LINE: ..." in `error`. */
int program_read(program *p, const char *path, char *error, size_t size);

/* An empty program. */
void program_init(program *p);
void program_free(program *p);

/* The frame the program next needs the machine at, UINT64_MAX when it
   has no steps left. */
uint64_t program_due(const program *p);

/* Do the next step if it is due at the machine's frame. `*current` is
   that step for every result but PROGRAM_IDLE and PROGRAM_END. */
program_result program_step(program *p, iigs *m, const step **current);

#endif
