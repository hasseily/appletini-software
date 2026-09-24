/* Doom for the Appletini -- basic types of the game (docs/DESIGN.md
 * sections 5 and 9).
 *
 * The game is compiled twice: by cc65 for the GAME space (int 16 bits,
 * long 32, pointers 16, char unsigned) and by gcc on the host for the
 * logic tests (tests/host/, int 32, pointers 64). Everything that has a
 * width says so (stdint.h); nothing relies on int being 16 bits.
 *
 *   fixed_t   Doom's 16.16 fixed point, 32 bits signed.
 *   angle_t   16-bit BAM (Doom's 32-bit angle >> 16): a turn is 65,536.
 *             The player turns by whole BAM16 steps in vanilla already
 *             (angleturn << 16); monsters and missiles lose the low 16
 *             bits of angles they never needed (fine angles are >> 19 in
 *             vanilla, >> 3 here).
 *   boolean   one byte.
 *
 * Fine angles: 8,192 per turn as vanilla (finesine/finecosine by
 * fine_sine()/fine_cosine(), fixed.s); ANGLETOFINESHIFT is 3 for BAM16.
 *
 * The real game is compiled only against the converter's data (doomdata.h
 * with DD_MAPDIR); against the platform's stand-in data set every game
 * module compiles to nothing and game.c keeps the platform skeleton.
 */
#ifndef DOOMTYPE_H
#define DOOMTYPE_H

#include <stddef.h>
#include <stdint.h>
#include "doomdata.h"

#ifdef DD_MAPDIR
#define GAME_REAL 1
#endif

#ifdef __CC65__
#define FASTCALL __fastcall__
#else
#define FASTCALL
#endif

typedef int32_t  fixed_t;
typedef uint16_t angle_t;
typedef uint8_t  boolean;

#ifndef true
#define true  1
#define false 0
#endif

#define FRACBITS        16
#define FRACUNIT        0x10000L
#define MAXINT          0x7FFFFFFFL
#define MININT          ((fixed_t)0x80000000UL)

/* map units -> fixed: FIX(v) is v << 16 for an int16 v. cc65 builds the
 * long from bytes (int2fix, fixed.s) instead of a 32-bit shift. */
#ifdef __CC65__
fixed_t FASTCALL int2fix(int16_t v);
#define FIX(v)          int2fix(v)
#else
#define FIX(v)          ((fixed_t)(v) * 65536L)
#endif
/* fixed -> map units, floor (arithmetic shift) */
#define UNITS(f)        ((int16_t)((f) >> FRACBITS))

#define ANG45           0x2000u
#define ANG90           0x4000u
#define ANG180          0x8000u
#define ANG270          0xC000u
#define FINEANGLES      8192
#define FINEMASK        (FINEANGLES - 1)
#define ANGLETOFINESHIFT 3
#define SLOPERANGE      2048
#define SLOPEBITS       11
#define DBITS           (FRACBITS - SLOPEBITS)

/* Test, set or clear one MF_ flag of a 32-bit flags word by its byte:
 * FLAG(mo->flags, MF_SOLID). info.h gives every flag's byte (MF_x_B) and
 * mask in it (MF_x_M); cc65 would otherwise do 32-bit arithmetic. Little
 * endian on both targets. The byte is *(p + n), not p[n]: cc65 2.18 drops
 * the member's offset from ((uint8_t *)&ptr->member)[n] (it reads ptr + n;
 * tests/test_game_sim.py found it, tests/test_game_core.py checks the
 * code cc65 makes of this macro). */
#define FB_(v, n)       (*((uint8_t *)&(v) + (n)))
#define FLAG(v, f)      (FB_(v, f##_B) & f##_M)
#define FLAGS_SET(v, f) (FB_(v, f##_B) |= f##_M)
#define FLAGS_CLR(v, f) (FB_(v, f##_B) &= (uint8_t)~f##_M)

#endif
