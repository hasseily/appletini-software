/*
 * Appletini Bosconian -- round layouts (docs/DESIGN.md section 10).
 *
 * One entry per distinct arcade layout. Coordinates are world pixels / 8
 * (the world is 1536x1536, the ship starts at 768,768 = 96,96 here), and
 * bit b of hz makes base b horizontal (core exposed left/right) instead of
 * vertical (core exposed top/bottom).
 *
 * The layouts follow the arcade round names and base counts as far as they
 * are documented: round 1 has three bases in a close triangle and round 2
 * four bases in two pairs; the later layouts (tight circle, Orion, circle,
 * big squiggle, straight line, tight cluster, sectors X/Y/Z, clusters, "A",
 * question mark) are reconstructed from their descriptions, and rounds 12
 * and up repeat six of them like the arcade does. tools/bosco_rom.py is the
 * place to add a table extractor once the ROM code has been read; until
 * then edit these numbers to correct a layout.
 */
#include "game.h"

const RoundDef round_layouts[ROUND_LAYOUTS] = {
    /* 1: close triangle */
    { 3, 0x06, {  96,  60, 132,   0,   0,   0,   0,   0 },
               {  56, 124, 124,   0,   0,   0,   0,   0 } },
    /* 2: two pairs */
    { 4, 0x0C, {  40,  40, 152, 152,   0,   0,   0,   0 },
               {  76, 116,  76, 116,   0,   0,   0,   0 } },
    /* 3: tight circle */
    { 6, 0x2A, { 136, 116,  76,  56,  76, 116,   0,   0 },
               {  96, 131, 131,  96,  61,  61,   0,   0 } },
    /* 4: Orion (Betelgeuse, Bellatrix, the belt, Saiph, Rigel) */
    { 7, 0x2A, {  56, 136,  80,  96, 112,  68, 128,   0 },
               {  24,  28,  64,  60,  56, 132, 136,   0 } },
    /* 5: circle */
    { 8, 0xAA, { 152, 136,  96,  56,  40,  56,  96, 136 },
               {  96, 136, 152, 136,  96,  56,  40,  56 } },
    /* 6: big squiggle */
    { 8, 0x55, {  16,  48,  80, 112, 144, 176, 152, 120 },
               {  40,  24,  40,  64,  88, 112, 144, 160 } },
    /* 7: straight line */
    { 8, 0xFF, {  12,  36,  60,  84, 108, 132, 156, 180 },
               {  56,  56,  56,  56,  56,  56,  56,  56 } },
    /* 8: tight cluster */
    { 8, 0x33, { 126, 144, 162, 170, 160, 142, 124, 140 },
               {  30,  26,  34,  52,  70,  76,  66,  50 } },
    /* 9: sector X */
    { 8, 0xF0, {  56,  72, 120, 136, 136, 120,  72,  56 },
               {  56,  72, 120, 136,  56,  72, 120, 136 } },
    /* 10: sector Y */
    { 8, 0x3F, {  76,  56,  36, 116, 136, 156,  96,  96 },
               {  76,  56,  36,  76,  56,  36, 128, 156 } },
    /* 11: sector Z */
    { 8, 0x18, {  40,  96, 152, 124,  68,  40,  96, 152 },
               {  40,  40,  40,  68, 124, 152, 152, 152 } },
    /* 12 (arcade round 14): two clusters */
    { 8, 0xF0, {  36,  60,  36,  60, 138, 162, 138, 162 },
               {  36,  36,  60,  60, 138, 138, 162, 162 } },
    /* 13 (arcade round 15): "A" */
    { 8, 0xAA, {  96,  82, 110,  68, 124,  54, 138,  96 },
               {  16,  44,  44,  72,  72, 100, 100,  68 } },
    /* 14 (arcade round 17): question mark */
    { 8, 0x55, { 100, 124, 148, 160, 148, 128, 128, 128 },
               {  40,  28,  40,  64,  88, 104, 128, 160 } },
};

/* rounds 12 and up cycle through these layouts (0-based indices) */
static const u8 repeat_seq[6] = { 2, 3, 11, 12, 4, 13 };

const RoundDef *round_layout(u8 round_no)
{
    u8 i;
    if (round_no == 0) round_no = 1;
    if (round_no <= 11) i = (u8)(round_no - 1);
    else i = repeat_seq[(u8)(round_no - 12) % 6];
    return &round_layouts[i];
}
