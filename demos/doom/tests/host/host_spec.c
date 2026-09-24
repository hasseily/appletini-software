/* Doom for the Appletini -- the host harness's view of the SPECIALS part
 * and the level flow (tests/test_game_specials.py links it with the
 * game's C and host.c into its own library).
 *
 * Readers of what the specials change (sectors and sidedefs as the
 * renderer sees them: the far records; the near mirrors; the busy bits;
 * the movers), of the level flow (gamestate, wminfo, the message queue),
 * and a few setters (keys, powers, the player's health).
 */
#include "p_spec.h"

/* per sector: floor, ceiling (near), floor, ceiling, light, special,
 * floorpic (far record), special (near), busy, tag */
void host_sector(int s, int32_t *out)
{
    int16_t v[4];
    uint8_t b[2];
    far_t a = P_LevAddr(MAPARR_SECTORS, (uint16_t)s);

    out[0] = sec_floorh[s];
    out[1] = sec_ceilh[s];
    far_read(a, v, 8);
    out[2] = v[0];
    out[3] = v[1];
    far_read(a + SECTOR_LIGHTLEVEL, b, 2);
    out[4] = b[0];
    out[5] = b[1];
    out[6] = (uint16_t)v[2];
    out[7] = sec_special[s];
    out[8] = sec_busy ? SEC_BUSY(s) != 0 : 0;
    out[9] = P_SectorTag((uint16_t)s);
}

/* a sidedef's xoffset, top, bottom, middle texture (far record) */
void host_side(int side, int32_t *out)
{
    int16_t v[5];
    far_read(P_LevAddr(MAPARR_SIDEDEFS, (uint16_t)side), v, 10);
    out[0] = v[0];
    out[1] = (uint16_t)v[2];
    out[2] = (uint16_t)v[3];
    out[3] = (uint16_t)v[4];
}

int host_line_special(int line)
{
    return far_peek(P_LevAddr(MAPARR_LINEDEFS, (uint16_t)line) + LINEDEF_SPECIAL);
}

int host_line_side(int line, int side) { return P_LineSide((uint16_t)line, (uint8_t)side); }

/* the movers in the thinker list: doors, floors, plats, ceilings */
void host_movers(int32_t *out)
{
    thinker_t *t;
    out[0] = out[1] = out[2] = out[3] = 0;
    for (t = thinkercap.next; t != &thinkercap; t = t->next) {
        if (t->function == T_VerticalDoor) ++out[0];
        else if (t->function == T_MoveFloor) ++out[1];
        else if (t->function == T_PlatRaise) ++out[2];
        else if (t->function == T_MoveCeiling) ++out[3];
    }
}

/* gamestate, gamemap, gameaction, wi_tics, wminfo (epsd, last, next,
 * didsecret, maxkills, maxitems, maxsecret, kills, items, secret, time,
 * partime), the player's counts (kills, items, secrets), totalsecret,
 * leveltics */
void host_flow(int32_t *out)
{
    out[0] = gamestate;
    out[1] = gamemap;
    out[2] = gameaction;
    out[3] = wi_tics;
    out[4] = wminfo.epsd;
    out[5] = wminfo.last;
    out[6] = wminfo.next;
    out[7] = wminfo.didsecret;
    out[8] = wminfo.maxkills;
    out[9] = wminfo.maxitems;
    out[10] = wminfo.maxsecret;
    out[11] = wminfo.kills;
    out[12] = wminfo.items;
    out[13] = wminfo.secret;
    out[14] = (int32_t)wminfo.time;
    out[15] = wminfo.partime;
    out[16] = player.killcount;
    out[17] = player.itemcount;
    out[18] = player.secretcount;
    out[19] = totalsecret;
    out[20] = (int32_t)leveltics;
}

int host_next_message(void) { return G_NextMessage(); }
void host_card(int card, int on) { player.cards[card] = (boolean)on; }
void host_power(int power, int tics) { player.powers[power] = (int16_t)tics; }
int host_health(void) { return player.health; }
void host_set_health(int h) { player.health = (int16_t)h; player.mo->health = (int16_t)h; }
int host_spec_bank(void) { return kbanks - 2; }

/* P_SpawnSectorSpecial at run time (a light or a door of special 10/14) */
void host_spawn_sector_special(int sector, int special)
{
    P_SpawnSectorSpecial((uint16_t)sector, (uint8_t)special);
}
