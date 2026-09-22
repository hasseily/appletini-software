/*
 * Appletini Bosconian -- round layouts, from the arcade ROM (docs/DESIGN.md
 * section 10).
 *
 * The sub CPU ROM of the arcade game keeps 14 base layouts: for every base
 * its radar tile (y/32, x/32) and its orientation, which the main CPU turns
 * into a base centre at (x*32+36, y*32+32) for a horizontal base and at
 * (x*32+32, y*32+36) for a vertical one. The values below are those centres
 * in world pixels (the world is 1024x1792). A second table gives the layout
 * of rounds 1 to 17; every later round plays rounds 12 to 17 again.
 *
 * Read from the ROM set with MAME (tools/bosco_rom.py converts only the
 * graphics; the numbers here were copied by hand and are checked by
 * tests/test_rounds.py).
 */
#include "game.h"

const RoundDef round_layouts[ROUND_LAYOUTS] = {
    /* layout 0: round 1 (H H H) */
    { 3, 0x07, {  484,  612,  356,    0,    0,    0,    0,    0 },
                { 1504, 1440, 1184,    0,    0,    0,    0,    0 } },
    /* layout 1: round 2 (H H V V) */
    { 4, 0x03, {  164,  164,  736,  928,    0,    0,    0,    0 },
                {  672,  864,  804,  804,    0,    0,    0,    0 } },
    /* layout 2: round 17 (H V V H H V H H) */
    { 8, 0xD9, {  228,  352,  544,  740,  676,  544,  484,  484 },
                {  416,  228,  228,  416,  672,  868, 1056, 1312 } },
    /* layout 3: round 6 (V H V V H H V H) */
    { 8, 0xB2, {   32,  612,  864,  864,  676,  548,  416,  548 },
                {  100,  224,  292,  612,  736, 1056, 1316, 1632 } },
    /* layout 4: round 9 (H H V V H H V V) */
    { 8, 0x33, {  164,  804,  352,  608,  356,  612,  160,  800 },
                {  544,  544,  740,  740, 1056, 1056, 1252, 1252 } },
    /* layout 5: round 14 (V H H H H V V H) */
    { 8, 0x9E, {  736,  804,  804,  484,  484,  672,  608,  228 },
                {  996,  992, 1056, 1120, 1184, 1380, 1380, 1504 } },
    /* layout 6: round 15 (V V V V V V H V) */
    { 8, 0x40, {  544,  416,  672,  480,  288,  608,   36,  800 },
                {  164,  548,  676,  740,  868,  932, 1248, 1636 } },
    /* layout 7: rounds 3, 12 (H H H V V H H H) */
    { 8, 0xE7, {  484,  356,  612,  288,  672,  356,  484,  612 },
                {  800,  864,  864,  932,  932, 1056, 1056, 1056 } },
    /* layout 8: rounds 4, 13 (H H V V V H H H) */
    { 8, 0xE3, {  164,  740,  608,  480,  352,  484,  868,  228 },
                {  288,  480,  996, 1060, 1124, 1376, 1504, 1632 } },
    /* layout 9: round 11 (V V V H H V V V) */
    { 8, 0x18, {  160,  480,  800,  612,  356,  160,  480,  800 },
                {  548,  548,  548,  736, 1056, 1252, 1252, 1252 } },
    /* layout 10: round 7 (V V V V V V V H) */
    { 8, 0x80, {   32,  160,  288,  416,  544,  672,  800,  932 },
                {  996,  996,  996,  996,  996,  996,  996,  992 } },
    /* layout 11: round 10 (H H V V H V V V) */
    { 8, 0x13, {  228,  740,  352,  608,  484,  480,  480,  480 },
                {  800,  800,  996,  996, 1120, 1252, 1380, 1508 } },
    /* layout 12: round 8 (H H H V H H H V) */
    { 8, 0x77, {  356,  484,  612,  416,  580,  356,  484,  608 },
                {  800,  800,  800,  868,  864,  992,  992,  996 } },
    /* layout 13: rounds 5, 16 (V V V V H H H H) */
    { 8, 0xF0, {  480,  800,  224,  480,  100,  868,  164,  740 },
                {  548,  676,  612, 1316,  864,  928, 1120, 1184 } },
};

/* layout of rounds 1..17 (0-based layout numbers) */
static const u8 round_seq[17] = { 0, 1, 7, 8, 13, 3, 10, 12, 4, 11, 9, 7, 8, 5, 6, 13, 2 };

const RoundDef *round_layout(u8 round_no)
{
    if (round_no == 0) round_no = 1;
    while (round_no > 17) round_no -= 6;         /* 18.. play 12..17 again */
    return &round_layouts[round_seq[round_no - 1]];
}
