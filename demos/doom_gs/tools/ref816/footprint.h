/*
 * The footprint of a call: what one routine of the game reads and writes
 * from its first instruction to its return, for --call and --capture of
 * main.c.
 *
 * A call ends with the RTS, RTL or RTI that leaves it: the footprint
 * counts depth, one up for each JSR, JSL, JSR (a,x), BRK, COP and
 * interrupt entry, one down for each RTS, RTL and RTI (and for each
 * firmware trap of iigs.c, which returns for the JSR that reached it),
 * and the call has returned after a return at depth 0. Code that leaves
 * by other means (a JMP through a pushed address, a stack switch) is not
 * seen; the depth then stays wrong until the run ends.
 *
 * What an interrupt does inside the call is not the call's: from the
 * interrupt's first push to its RTI, accesses are not recorded, and its
 * instructions and cycles are counted apart. An interrupt entry is a step
 * that made a stack or vector access before any opcode fetch (as in
 * trace.c).
 *
 * Recorded, outside interrupts:
 *
 *   reads    the first read of each byte of RAM that the call had not
 *            written before, with the value read: the bytes the call
 *            depends on. Program fetches and stack pulls are reads.
 *   writes   each byte of RAM written, and the byte of $E0/$E1 a write
 *            reached through the shadow register (iigs_shadow_target).
 *   I/O      reads and writes of $C000-$CFFF (and of $C000-$FFFF of
 *            banks $00/$01 when the I/O and ROM are mapped in there),
 *            counted by register; ROM and banks with no memory are
 *            counted, not recorded.
 *
 * The files are ref816 memory images (main.c, make_image.py): a header
 * with registers and soft switches, then records of an address, a length
 * and bytes. A reads image has the registers and switches at the start of
 * the call and a record for each run of bytes read first, with the values
 * read. A writes image has those at the return and a record for each run
 * of bytes written, with the values the call wrote last. So the memory at
 * the start with the writes image loaded over it is the memory at the
 * return, but for bytes an interrupt inside the call wrote after the call
 * did (the stack below S; "written_then_changed" counts them), and a
 * --call on the reads image alone runs the call again (as long as
 * it does what it did: the same path through the same bytes).
 *
 * Tracing (trace.h) and the footprint use the same hooks; main.c does not
 * allow both in one run. Outside a call the footprint only watches the
 * step hook for calls of the capture entry; the bus callbacks are its own
 * only while it records.
 */
#ifndef FOOTPRINT_H
#define FOOTPRINT_H

#include <stdint.h>
#include <stdio.h>

#include "iigs.h"

enum {
    FOOTPRINT_MAX_HITS = 256,
    FOOTPRINT_DEPTH = 4096      /* nesting kept exactly; deeper is counted */
};

typedef struct {
    /* --call: record from the first step, and stop the run (stop_request)
       when the call returns. */
    int call;
    const char *reads_path, *writes_path;   /* --call-reads, --call-writes */

    /* --capture: the calls (JSR, JSL, JSR (a,x)) of `entry`, counted from
       1 in the run (calls made while a capture records are not
       counted), whose hit number is in `hits`, each recorded into
       DIR/hit-NNNNNNNN/: entry.img (all RAM and the registers after the
       call instruction), reads.img, writes.img, exit.img (the bytes
       written, with their values at the return), call.json. */
    const char *capture_dir;
    uint32_t entry;
    uint64_t hits[FOOTPRINT_MAX_HITS];
    unsigned hit_count;
} footprint_config;

typedef struct footprint footprint;

/* Install the step hook (and, for a call, the bus callbacks at once).
   NULL when memory cannot be allocated. */
footprint *footprint_open(iigs *m, const footprint_config *c);

/* A note of the input: a capture names the last one before it. */
void footprint_note(footprint *f, const char *name);

/* The call of --call has returned. */
int footprint_returned(const footprint *f);

/* The "call" member of the final state (main.c), without a comma:
   whether the call returned, its depth, instructions and cycles, those
   of interrupts inside it, the bytes read and written, the I/O. The
   registers at the end are those now when it has not returned. */
void footprint_json(footprint *f, FILE *out);

/* Write --call-reads and --call-writes, restore the hooks, free. The
   message of the first error, or NULL; captures report theirs here too
   (a capture that cannot write its files stops nothing else). */
const char *footprint_close(footprint *f);

#endif
