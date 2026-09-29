/*
 * The trace of a run of ref816: what the game does frame by frame, for
 * the profiles of tools/ref816/profile816.py.
 *
 * A frame of the game is one pass of its main loop that drew the 3D view,
 * from one call of the frame entry (R_RenderPlayerView) to the next, as
 * in tools/ref816/marks.py. Frames are recorded between two notes of the
 * input program: from the first frame that starts after the note `from`
 * to the last one that ends before the note `to`.
 *
 * Phases come from the call structure. A phase is entered by a call
 * (JSR, JSL or JSR (a,x)) to one of its entry addresses and left when the
 * CPU is back at the instruction after that call with S as it was before
 * it, which a return does and a stack switch in between does not. An
 * interrupt is the phase "interrupt" from its first push to the return
 * to the interrupted instruction. Phases nest; the innermost one owns
 * the instructions, cycles and accesses. Phase 0, "other", is outside
 * all of them. The cycles of the machine's firmware traps are no
 * phase's: the frame counts them apart.
 *
 * Tracing costs nothing unless it is on: the machine calls the trace
 * only through its step hook and the CPU's bus callbacks, which the trace
 * replaces with its own while it runs.
 *
 * The file is text, one record a line, addresses in hexadecimal and
 * counts in decimal:
 *
 *   ref816-trace 1
 *   phase INDEX NAME                       every phase, 0 and 1 first
 *   entry ADDRESS PHASE                    every entry address
 *   near BANK                              banks whose data is not far
 *   split ADDRESS                          the stack split, below
 *   note NAME CLOCK CYCLES INSTRUCTIONS    each note of the input
 *   frame INDEX CLOCK CYCLES INSTRUCTIONS CLOCK CYCLES INSTRUCTIONS
 *                                          a frame: the counts at its
 *                                          start and at its end, then:
 *     cost PHASE INSTRUCTIONS CYCLES
 *     enters PHASE COUNT                   times the phase was entered: a
 *                                          call of an entry, or an
 *                                          interrupt
 *     firmware CALLS CYCLES                firmware traps of the machine
 *                                          (iigs.c): the cycles they
 *                                          charge with no instruction,
 *                                          which no phase has; the costs
 *                                          and these add up to the frame
 *     access PHASE SPACE BANK READS WRITES
 *                                          SPACE is program, direct, stack,
 *                                          data, io (the I/O space and
 *                                          ROM) or vector
 *     lines BANK T8 T64 T256 W8 W64 W256   data accesses: the distinct
 *                                          8-byte lines, 64-byte lines and
 *                                          256-byte pages touched (read or
 *                                          written) and written
 *     switches PHASE COUNT                 data accesses outside the near
 *                                          banks whose bank differs from
 *                                          that of the one before
 *     stack PHASE HIGH LOW                 the lowest S after a step above
 *                                          the split and at or below it
 *                                          (- for none)
 *     screen PHASE DIRECT SHADOWED CHANGED writes that reach $E1:2000-
 *                                          $9CFF, directly or by shadowing,
 *                                          and those that changed the byte
 *     heat PHASE ADDRESS COUNT LENGTH      instructions executed at ADDRESS
 *                                          and their length in bytes
 *     unclosed COUNT                       phases still open when the next
 *                                          frame started (then closed)
 *   smc FRAME WRITER TARGET COUNT          writes in a recorded frame by
 *                                          the instruction at WRITER to a
 *                                          byte that the run executes (an
 *                                          opcode or an operand), before
 *                                          or after the write
 *   smc-mixed COUNT                        of those, writes that waited
 *                                          for the first execution of
 *                                          their byte with writes of
 *                                          another instruction or frame:
 *                                          all are counted with the last
 *   jumps PHASE COUNT                      entries reached otherwise than
 *                                          by a call or a return
 *   width ADDRESS KIND VALUE               over the whole run: an
 *                                          instruction at ADDRESS executed
 *                                          with that value of mx (E << 2
 *                                          | M << 1 | X), d or dbr
 *   end CLOCK CYCLES INSTRUCTIONS
 *
 * CLOCK is in master clocks; an instruction is an opcode fetch (MVN and
 * MVP fetch theirs again for each byte), as in iigs.h.
 */
#ifndef TRACE_H
#define TRACE_H

#include <stdint.h>

#include "iigs.h"

enum {
    TRACE_MAX_PHASES = 16,
    TRACE_MAX_ENTRIES = 64,
    TRACE_OTHER = 0,            /* the phase outside all others */
    TRACE_INTERRUPT = 1
};

typedef struct {
    const char *path;
    uint32_t frame_entry;       /* a call to it starts a frame */
    const char *from, *to;      /* notes; NULL for the start, the end */
    unsigned phase_count;       /* names[0] and names[1] are fixed */
    const char *names[TRACE_MAX_PHASES];
    unsigned entry_count;
    uint32_t entries[TRACE_MAX_ENTRIES];
    uint8_t entry_phase[TRACE_MAX_ENTRIES];
    uint8_t near[256];          /* 1 for a bank whose data is not far */
    uint16_t stack_split;
} trace_config;

typedef struct trace trace;

/* A configuration with no phases but "other" and "interrupt", no
   frame entry (0), no near bank and the stack split at 0. */
void trace_config_init(trace_config *c, const char *path);

/* Add `entry` to the phase `name`, a new one if no phase has that name
   yet. Returns 0 when there are too many phases or entries, or for the
   names "other" and "interrupt". */
int trace_config_phase(trace_config *c, const char *name, uint32_t entry);

/* Start tracing `m` into the file of `c`, which must stay valid until
   trace_close. Returns NULL when the file cannot be written or memory
   is short. */
trace *trace_open(iigs *m, const trace_config *c);

/* A note of the input program at the current time. */
void trace_note(trace *t, const char *name);

/* Write what covers the whole run, close the file, give the machine its
   bus back and free `t`. Returns 0 when the file could not be written. */
int trace_close(trace *t);

#endif
