/*
 * The call log (--call-log of main.c): every call of chosen routines in a
 * run, with the registers and a declared memory footprint at its entry and
 * at its return, one JSON object a line. Routine-level oracles at scale:
 * the inputs and outputs of the game's own routines in real play.
 *
 * A routine is given as
 *
 *   ADDR[,KEY=VALUE...]
 *
 * ADDR is its entry (hex, 24 bits), and the keys are
 *
 *   name=NAME      the name the log gives it (default: the address in
 *                  hex); printable ASCII without quotes or backslashes
 *   in=R+R...      memory read at the entry
 *   out=R+R...     memory read at the return
 *   mem=R+R...     both (added to in and to out)
 *   jumps=1        JMP and JML that land on ADDR are calls too (thinker
 *                  functions, entered by JML [dp]); default: only JSR,
 *                  JSL and JSR (a,x)
 *   entry=1        log at the entry only: no return, no out
 *   hits=, after=, if=   which calls (points.h; `if` is tested at the
 *                  entry). hits count the calls that pass after and if.
 *
 * A range R is ADDR:LEN (hex address; LEN decimal or 0x hex), d+OFF:LEN
 * (bank 0, D + OFF: the direct page), or s+OFF:LEN (bank 0, S + OFF: the
 * stack; S after the call instruction, so s+1:3 is the return address of
 * a JSL). OFF is hex. The address of a d or s range is fixed at the
 * entry and read again at the return. Bytes of I/O space read as the RAM
 * under it (iigs_peek), never as I/O.
 *
 * A call starts after the instruction that reaches ADDR. It returns at
 * the first RTS, RTL or RTI (or firmware trap, which returns for its
 * JSR) after which S is above S at the entry: the stack is back to the
 * caller's level. Interrupts inside a call return with S at or below it,
 * so they do not end it; calls inside interrupts are logged like others,
 * with irq > 0. A routine that leaves without returning (a JMP through a
 * pulled address, a stack switch) ends at the next such return, which
 * its `exit` and registers show.
 *
 * The file: a first line
 *
 *   {"format": "ref816-call-log 1", "routines": [...]}
 *
 * with each routine's index, name, entry, jumps, entry_only, in and out
 * (each range as {"base": "abs"|"d"|"s", "offset": N, "length": N});
 * then a line for each logged call when it returns (so a callee's line
 * comes before its caller's), or at its entry for entry=1:
 *
 *   {"call": N, "routine": I, "hit": H, "from": PC, "via": "jsl",
 *    "parent": P, "depth": K, "irq": Q, "frame": F, "cycles": C,
 *    "instructions": T,
 *    "in": {"pc": ..., "a": ..., "x": ..., "y": ..., "s": ..., "d": ...,
 *           "dbr": ..., "p": ..., "e": ..., "mem": ["hex", ...]},
 *    "out": {"exit": "rtl", "pc": ..., (registers), "cycles": C2,
 *            "instructions": T2, "interrupts": R, "mem": ["hex", ...]},
 *    "returned": true}
 *
 * call numbers the logged calls from 1 in the order of their entries;
 * hit is the routine's own call number (from 1, as hits= counts); from
 * is the address of the calling instruction; via is jsr, jsl, jsr_x,
 * jmp, jml, jmp_ind, jmp_x or jml_ind; parent is the call number of the
 * innermost logged call open at the entry (0: none), depth the number of
 * those open; irq the interrupts open at the entry. frame, cycles and
 * instructions are the machine's at the entry, cycles and instructions
 * of out at the return (interrupts inside included). mem has a hex
 * string for each range, in order. A call still open when the run ends
 * gets "returned": false and the registers of the end, "exit": null. An
 * entry=1 line has "out": null and no "returned". The last line is
 *
 *   {"end": true, "calls": N, "arrivals": [each routine's count]}
 *
 * Arrivals are all calls of each routine, logged or not (those that
 * pass after and if). The log uses the step hook of iigs.h, so it goes
 * with neither --trace, --call nor --capture. It only reads the machine.
 */
#ifndef CALLLOG_H
#define CALLLOG_H

#include <stddef.h>
#include <stdint.h>

#include "iigs.h"
#include "points.h"

enum {
    CALLLOG_ROUTINES = 64,
    CALLLOG_RANGES = 16,
    CALLLOG_NAME = 64
};

typedef enum { CALLLOG_ABS, CALLLOG_D, CALLLOG_S } calllog_base;

typedef struct {
    calllog_base base;
    uint32_t offset, length;
} calllog_range;

typedef struct {
    uint32_t entry;
    char name[CALLLOG_NAME];
    int jumps, entry_only;
    point select;               /* hits, after, if */
    calllog_range in[CALLLOG_RANGES], out[CALLLOG_RANGES];
    unsigned in_count, out_count;
} calllog_routine;

typedef struct calllog calllog;

/* Parse a --call-log routine. Returns 0 with a message in `error`. */
int calllog_parse(calllog_routine *r, const char *text, char *error,
                  size_t size);

/* Start logging `count` routines into `path`: writes the first line and
   installs the step hook. NULL with a message in `error` when the file
   cannot be written or memory allocated. */
calllog *calllog_open(iigs *m, const calllog_routine *routines,
                      unsigned count, const char *path, char *error,
                      size_t size);

/* The most bytes the log may hold (0: no limit). A line that takes it
   past the limit is the last: the log takes no more, sets the machine's
   stop_request, and calllog_problem says why. */
void calllog_set_limit(calllog *l, uint64_t bytes);
const char *calllog_problem(const calllog *l);

/* A note of the input (for after=). */
void calllog_note(calllog *l, const char *name);

/* Log the calls still open, write the last line, remove the hook, free.
   The message of the first error, or NULL. */
const char *calllog_close(calllog *l);

#endif
