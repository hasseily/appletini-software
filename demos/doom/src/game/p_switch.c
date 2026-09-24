/* Doom for the Appletini -- switches (docs/DESIGN.md section 9): vanilla
 * p_switch.c.
 *
 *   P_ChangeSwitchTexture  the used line's front sidedef shows the other
 *                   texture of its SW1/SW2 pair (the converter gives each
 *                   TEX record its partner, TEX_SWITCHTEX); a repeatable
 *                   switch becomes a button that comes back after a second
 *   P_RunButtons    the buttons' timers (P_UpdateSpecials)
 *   P_ResetButtons  level start and end
 *
 * The texture is changed in the sidedef's far record, where the renderer
 * reads it. A once-only switch's change is journalled (p_spec.c) so that a
 * restarted level has it back; a button is put back up at the level's end
 * instead. vanilla looks for the first switch of its list among the top,
 * middle and bottom textures; here top, then middle, then bottom (the
 * same unless a sidedef has two switch textures).
 */
#include "p_spec.h"

#if defined(GAME_REAL) && !defined(__CC65__)   /* on the 6502: a_spec.s */

#include <string.h>

#define MAXBUTTONS      16
#define BUTTONTIME      35

typedef struct {
    uint16_t line;
    uint16_t side;                  /* the line's front sidedef */
    uint8_t  where;                 /* SIDEDEF_TOPTEXTURE, _MIDTEXTURE, _BOTTOMTEXTURE */
    uint16_t btexture;              /* the texture to put back */
    uint8_t  btimer;                /* 0: slot free */
} button_t;

static button_t buttonlist[MAXBUTTONS];
static uint8_t buttons_on;

/* vanilla P_StartButton */
static void start_button(uint16_t line, uint16_t side, uint8_t where, uint16_t texture)
{
    button_t *b;

    for (b = buttonlist; b < buttonlist + MAXBUTTONS; ++b)
        if (b->btimer && b->line == line)
            return;                 /* already pressed */
    for (b = buttonlist; b < buttonlist + MAXBUTTONS; ++b)
        if (!b->btimer) {
            b->line = line;
            b->side = side;
            b->where = where;
            b->btexture = texture;
            b->btimer = BUTTONTIME;
            ++buttons_on;
            return;
        }
    /* (vanilla: I_Error "no button slots left"; here the switch stays on) */
}

static const uint8_t where_tab[3] = { SIDEDEF_TOPTEXTURE, SIDEDEF_MIDTEXTURE, SIDEDEF_BOTTOMTEXTURE };

void P_ChangeSwitchTexture(uint16_t line, boolean useAgain)
{
    uint16_t side, tex[3], other;
    uint8_t i, where;
    far_t rec, at;

    if (!useAgain)
        P_ClearLineSpecial(line);
    side = P_LineSide(line, 0);
    rec = P_LevAddr(MAPARR_SIDEDEFS, side);
    far_read(rec + SIDEDEF_TOPTEXTURE, tex, 6);   /* top, bottom, middle */
    for (i = 0; i < 3; ++i) {
        where = where_tab[i];
        at = rec + where;
        other = tex[(where - SIDEDEF_TOPTEXTURE) >> 1];
        if (!other)
            continue;
        far_read(FAR(DD_DIR_BANK, DD_TEXDIR + TEX_SIZE * other + TEX_SWITCHTEX), &other, 2);
        if (!other)
            continue;
        /* (vanilla's sfx_swtchx for the exit switch never plays: the
         * special is cleared first) */
        S_StartSound(0, sfx_swtchn);
        if (useAgain)
            start_button(line, side, where, tex[(where - SIDEDEF_TOPTEXTURE) >> 1]);
        else
            P_JournalBytes(at, 2);
        far_write(&other, at, 2);
        return;
    }
}

void P_RunButtons(void)
{
    button_t *b;

    if (!buttons_on)
        return;
    for (b = buttonlist; b < buttonlist + MAXBUTTONS; ++b)
        if (b->btimer && !--b->btimer) {
            far_write(&b->btexture, P_LevAddr(MAPARR_SIDEDEFS, b->side) + b->where, 2);
            S_StartSound(0, sfx_swtchn);
            --buttons_on;
        }
}

void P_ResetButtons(boolean up)
{
    button_t *b;

    if (up)
        for (b = buttonlist; b < buttonlist + MAXBUTTONS; ++b)
            if (b->btimer)
                far_write(&b->btexture, P_LevAddr(MAPARR_SIDEDEFS, b->side) + b->where, 2);
    memset(buttonlist, 0, sizeof buttonlist);
    buttons_on = 0;
}

#endif
