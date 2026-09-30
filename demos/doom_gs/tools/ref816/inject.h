/*
 * Memory written into a run from outside: pokes at points of the run
 * (--poke-file of main.c) and lumps placed in the game's WAD before it
 * starts (--wad, --lump).
 *
 * A poke file has one poke a line; # starts a comment:
 *
 *   POINT ADDR DATA
 *
 * POINT is a point of points.h (pc=, frame= or cycle=, with hits, after
 * and if; no ranges). ADDR is where the bytes go (hex, 24 bits). DATA is
 * the bytes in hex (an even number of digits), or @PATH: the bytes of the
 * file PATH (relative to the poke file's directory unless it starts with
 * /). Each time the point fires, the bytes are written into RAM as --load
 * writes them: no I/O and no shadowing, all within RAM. Pokes that fire
 * at the same moment are written in the order of their lines (and of
 * the files), before any --dump-at of that moment.
 *
 * A lump: the WAD of the game in RAM at --wad ADDR, as upstream keeps it
 * (build/upstream/src/iigs/w_wad65.s): a header ("IWAD" or "PWAD", the
 * number of lumps, the directory's offset from ADDR, each 32 bits), and a
 * directory of 16-byte entries (the lump's offset from ADDR, its size and
 * its name, 8 bytes padded with zeros). --lump NAME:DEST:FILE puts the
 * bytes of FILE at DEST (hex) and points the directory's one entry named
 * NAME there: offset DEST - ADDR (modulo 2^32), size the file's. It
 * refuses a NAME that is missing or more than one entry's, a DEST that is
 * not RAM, that crosses a 64 KB bank (upstream uses a lump in place and
 * never across banks) or that holds a byte other than zero (the place
 * must be free). Lumps go in after the image and the --load files,
 * before --reg.
 */
#ifndef INJECT_H
#define INJECT_H

#include <stddef.h>
#include <stdint.h>

#include "iigs.h"
#include "points.h"

typedef struct {
    point when;
    uint32_t address;
    uint8_t *data;
    uint32_t length;
} poke;

typedef struct {
    poke *pokes;
    size_t count, capacity;
} poke_list;

/* Add the pokes of the file at `path` to `list`. Returns 0 with a
   message "PATH:LINE: ..." in `error`. */
int pokes_read(poke_list *list, const char *path, char *error, size_t size);

void pokes_free(poke_list *list);

/* Write a poke's bytes into RAM. */
void poke_apply(iigs *m, const poke *p);

/* Place `length` bytes of `data` at `dest` and point the entry `name` of
   the WAD at `wad` there. Returns 0 with a message in `error`. */
int lump_place(iigs *m, uint32_t wad, const char *name, uint32_t dest,
               const uint8_t *data, size_t length, char *error, size_t size);

#endif
