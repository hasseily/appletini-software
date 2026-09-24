/* Doom for the Appletini -- the host harness of the game's C code
 * (tests/test_game_core.py builds it with gcc into a shared library and
 * drives it through ctypes).
 *
 * It provides what the GAME space gets from elsewhere on the Apple:
 *  - the kernel (kernel.h here): far memory as 128 banks of 64 KB that
 *    the test fills from the converter's data files, the input block,
 *    kernel_crash (recorded, and the call in progress abandoned with
 *    longjmp);
 *  - fixed.s: FixedMul/FixedDiv with 64-bit arithmetic (vanilla's own
 *    definitions), the far tables from tests/host/gtables_host.h
 *    (generated with gtables.s by tools/gen_info.py), game_farinit;
 *  - entry points and accessors for the tests: run the game's calls
 *    under the crash guard, read the player, the things and the render
 *    packet (serialized in the 6502 layout of rview.h), place the player,
 *    spawn things and fire hitscans.
 */
#include <setjmp.h>
#include <stdlib.h>
#include <string.h>

#include "p_local.h"
#include "rview.h"
#include "gtables_host.h"

/* --- kernel ------------------------------------------------------------------ */
static uint8_t banks[128][65536];
struct kinput kin;
uint16_t ktics;
uint8_t kbanks = 128;
static jmp_buf crash_jmp;
static int crash_armed, crash_code;
unsigned long host_far_reads, host_far_bytes;

uint8_t *host_banks(void) { return &banks[0][0]; }
int host_crash_code(void) { return crash_code; }

void far_read(far_t src, void *dst, unsigned int len)
{
    ++host_far_reads;
    host_far_bytes += len;
    memcpy(dst, &banks[FAR_BANK(src)][FAR_ADDR(src)], len);
}

void far_write(const void *src, far_t dst, unsigned int len)
{
    memcpy(&banks[FAR_BANK(dst)][FAR_ADDR(dst)], src, len);
}

void far_copy(far_t src, far_t dst, unsigned int len)
{
    memmove(&banks[FAR_BANK(dst)][FAR_ADDR(dst)], &banks[FAR_BANK(src)][FAR_ADDR(src)], len);
}

far_t far_elem(const struct far_array *a, unsigned int index)
{
    uint16_t within = index & ((1u << a->log2) - 1);
    return FAR(a->bank + (index >> a->log2), a->base + within * a->size);
}

unsigned char far_peek(far_t a)
{
    ++host_far_reads;
    ++host_far_bytes;
    return banks[FAR_BANK(a)][FAR_ADDR(a)];
}

void set_palette(unsigned char n) { (void)n; }
void kernel_reboot(void) { abort(); }

void kernel_crash(unsigned char code)
{
    crash_code = code;
    if (crash_armed)
        longjmp(crash_jmp, 1);
    abort();
}

/* --- fixed.s -------------------------------------------------------------------- */
fixed_t FixedMul(fixed_t a, fixed_t b)
{
    return (fixed_t)(((int64_t)a * b) >> FRACBITS);
}

fixed_t FixedDiv(fixed_t a, fixed_t b)
{
    if ((labs(a) >> 14) >= labs(b))
        return (a ^ b) < 0 ? MININT : MAXINT;
    return (fixed_t)(((int64_t)a << FRACBITS) / b);
}

fixed_t fine_sine(uint16_t a)
{
    uint16_t h = a & 4095;
    fixed_t v = host_finesine_q[h < 2048 ? h : 4095 - h];
    return (a & 4096) ? -v : v;
}

fixed_t fine_cosine(uint16_t a)
{
    return fine_sine(a + 2048);
}

angle_t tanto_angle(uint16_t slope)
{
    return host_tantoangle[slope];
}

void game_farinit(void)
{
}

/* --- guarded calls --------------------------------------------------------------- */
typedef void (*call_t)(void);

static int guarded(call_t fn)
{
    crash_code = 0;
    crash_armed = 1;
    if (setjmp(crash_jmp)) {
        crash_armed = 0;
        return crash_code;
    }
    fn();
    crash_armed = 0;
    return 0;
}

int host_init(void) { return guarded(game_init); }
int host_tic(void) { return guarded(game_tic); }
int host_frame(void) { return guarded(game_frame); }

static uint8_t load_ep, load_map, load_skill;
static void do_load(void)
{
    player.playerstate = PST_REBORN;
    P_SetupLevel(load_ep, load_map, load_skill);
}

int host_load(int episode, int map, int skill)
{
    load_ep = episode;
    load_map = map;
    load_skill = skill;
    return guarded(do_load);
}

void host_set_input(int mouse_dx, int buttons, int move, int weapon)
{
    kin.mouse_dx = mouse_dx;
    kin.buttons = buttons;
    kin.move = move;
    kin.weapon = weapon;
}

/* --- the player ---------------------------------------------------------------------- */
/* x, y, z, angle, viewz, momx, momy, health, floorz, ceilingz, sector,
 * readyweapon, ammo[clip], state, playerstate, weapon psprite state */
void host_player(int32_t *out)
{
    mobj_t *mo = player.mo;
    out[0] = mo->x;
    out[1] = mo->y;
    out[2] = mo->z;
    out[3] = mo->angle;
    out[4] = player.viewz;
    out[5] = mo->momx;
    out[6] = mo->momy;
    out[7] = player.health;
    out[8] = mo->floorz;
    out[9] = mo->ceilingz;
    out[10] = mo->sector;
    out[11] = player.readyweapon;
    out[12] = player.ammo[am_clip];
    out[13] = mo->state;
    out[14] = player.playerstate;
    out[15] = player.psprites[ps_weapon].state;
}

/* place the player at (x, y) map units on the floor there, angle BAM16 */
static int16_t pl_x, pl_y;
static uint16_t pl_angle;
static void do_place(void)
{
    mobj_t *mo = player.mo;
    P_UnsetThingPosition(mo);
    mo->x = FIX(pl_x);
    mo->y = FIX(pl_y);
    mo->angle = pl_angle;
    mo->momx = mo->momy = mo->momz = 0;
    P_SetThingPosition(mo);
    P_CheckPosition(mo, mo->x, mo->y);
    mo->floorz = UNITS(tmfloorz);
    mo->ceilingz = UNITS(tmceilingz);
    mo->z = tmfloorz;
    player.viewz = mo->z + VIEWHEIGHT;
    player.viewheight = VIEWHEIGHT;
    player.deltaviewheight = 0;
}

int host_place_player(int x, int y, int angle)
{
    pl_x = x;
    pl_y = y;
    pl_angle = angle;
    return guarded(do_place);
}

/* --- things ------------------------------------------------------------------------------- */
/* per thing 10 int32: kind (0 actor, 1 static), type, x, y, z (fixed),
 * state, health, flags, sector, sflags; returns the count */
int host_things(int32_t *out, int max)
{
    int n = 0;
    mobj_t *mo;
    sobj_t *s;

    for (mo = mobjs; mo < mobjs_end && n < max; ++mo) {
        if (mo->thinker.function != (think_t)P_MobjThinker)
            continue;
        out[0] = 0; out[1] = mo->type; out[2] = mo->x; out[3] = mo->y; out[4] = mo->z;
        out[5] = mo->state; out[6] = mo->health; out[7] = (int32_t)mo->flags;
        out[8] = mo->sector; out[9] = 0;
        out += 10;
        ++n;
    }
    for (s = statics; s < statics_end && n < max; ++s) {
        if (s->sflags & SF_FREE)
            continue;
        out[0] = 1; out[1] = s->type; out[2] = FIX(s->x); out[3] = FIX(s->y); out[4] = FIX(s->z);
        out[5] = s->state; out[6] = 0; out[7] = (int32_t)P_StaticFlags(s);
        out[8] = s->sector; out[9] = s->sflags;
        out += 10;
        ++n;
    }
    return n;
}

void host_counts(int32_t *out)
{
    out[0] = nummobjs;
    out[1] = mobjs_used;
    out[2] = numstatics;
    out[3] = statics_used;
    out[4] = totalkills;
    out[5] = totalitems;
    out[6] = totalsecret;
    out[7] = P_ArenaFree();
    out[8] = leveltime;
    out[9] = gamemap;
    out[10] = sizeof(mobj_t);
    out[11] = sizeof(sobj_t);
}

static int16_t sp_x, sp_y;
static uint8_t sp_type;
static mobj_t *sp_result;
static void do_spawn(void)
{
    sp_result = P_SpawnMobj(FIX(sp_x), FIX(sp_y), ONFLOORZ, sp_type);
}

int host_spawn(int type, int x, int y)
{
    sp_type = type;
    sp_x = x;
    sp_y = y;
    if (guarded(do_spawn))
        return -1;
    return (int)(sp_result - mobjs);
}

uint16_t host_point_sector(int x, int y)
{
    return R_PointInSector(FIX(x), FIX(y));
}

/* one hitscan from the player: angle BAM16, slope 16.16 */
static uint16_t la_angle;
static fixed_t la_slope;
static void do_attack(void)
{
    P_LineAttack(player.mo, la_angle, MISSILERANGE, la_slope, 10);
}

int host_line_attack(int angle, int32_t slope)
{
    la_angle = angle;
    la_slope = slope;
    return guarded(do_attack);
}

static fixed_t aim_result;
static void do_aim(void)
{
    aim_result = P_AimLineAttack(player.mo, la_angle, 16 * 64 * FRACUNIT);
}

int32_t host_aim(int angle)
{
    la_angle = angle;
    if (guarded(do_aim))
        return 0x7FFFFFFF;
    return linetarget ? aim_result : 0x7FFFFFFE;
}

/* --- the render packet in the 6502 layout (rview.h / rview.inc) ------------------------- */
static void put16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
static void put32(uint8_t *p, uint32_t v) { put16(p, v); put16(p + 2, v >> 16); }

int host_rview(uint8_t *out)
{
    int i;
    uint8_t *t;

    put32(out + 0, rview.x);
    put32(out + 4, rview.y);
    put32(out + 8, rview.z);
    put16(out + 12, rview.angle);
    out[14] = rview.extralight;
    out[15] = rview.fixedcolormap;
    put16(out + 16, rview.tic);
    out[18] = rview.nthings;
    out[19] = rview.npsprites;
    for (i = 0; i < 2; ++i) {
        uint8_t *p = out + 20 + 10 * i;
        p[0] = rview.psprites[i].sprite;
        p[1] = rview.psprites[i].frame;
        put32(p + 2, rview.psprites[i].sx);
        put32(p + 6, rview.psprites[i].sy);
    }
    for (i = 0; i < rview.nthings; ++i) {
        t = out + 40 + 20 * i;
        put32(t + 0, rview.things[i].x);
        put32(t + 4, rview.things[i].y);
        put32(t + 8, rview.things[i].z);
        put16(t + 12, rview.things[i].angle);
        t[14] = rview.things[i].sprite;
        t[15] = rview.things[i].frame;
        t[16] = rview.things[i].flags;
        t[17] = rview.things[i].pad;
        put16(t + 18, rview.things[i].sector);
    }
    return 40 + 20 * rview.nthings;
}

uint8_t host_sounds(uint8_t *out)
{
    memcpy(out, snd_last, 8);
    return snd_count;
}
