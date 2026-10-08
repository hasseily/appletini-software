/*
 * a2vm: the machine around the cores. See a2vm.h for what it models;
 * each part names the part of a2sim.py (the earlier Appletini Doom
 * port's Python model, not in this repository) it was written from.
 */
#include "a2vm.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *const a2vm_switch_names[SW_COUNT] = {
    "store80", "ramrd", "ramwrt", "intcxrom", "altzp", "slotc3rom",
    "col80", "altchar", "text", "mixed", "page2", "hires"
};

/* The mouse card's slot ROM (a2sim.MOUSE_ROM, from appletini-one's
   hdl/apple/mouse_card_slot2.mem): the AppleMouse ID bytes and the
   firmware entry table. */
static const uint8_t mouse_rom[256] = {
    0xa2, 0x02, 0x60, 0xea, 0xea, 0x38, 0x60, 0x18, 0xea, 0xea, 0xea, 0x01,
    0x20, 0x8d, 0xac, 0xc0, 0x18, 0x60, 0x5e, 0x6f, 0xa6, 0xb3, 0xcd, 0x1b,
    0xea, 0xef, 0x3f, 0xc9, 0x02, 0xb0, 0xe6, 0x8d, 0xa7, 0xc0, 0xad, 0x78,
    0x04, 0x8d, 0xa8, 0xc0, 0xad, 0x78, 0x05, 0x8d, 0xa9, 0xc0, 0xad, 0xf8,
    0x04, 0x8d, 0xaa, 0xc0, 0xad, 0xf8, 0x05, 0x8d, 0xab, 0xc0, 0xa9, 0x02,
    0x4c, 0x0d, 0xc2, 0xad, 0x78, 0x04, 0x38, 0xe9, 0x47, 0xc9, 0x08, 0xb0,
    0xbc, 0x48, 0x29, 0x01, 0x8d, 0xa7, 0xc0, 0x68, 0x29, 0x06, 0x4a, 0x49,
    0x01, 0xaa, 0xbd, 0xa8, 0xc0, 0x8d, 0x78, 0x05, 0x18, 0x60, 0xc9, 0x10,
    0xb0, 0xa3, 0x48, 0x20, 0x00, 0xc2, 0x68, 0x9d, 0xf8, 0x07, 0x8d, 0xae,
    0xc0, 0x18, 0x60, 0x20, 0x00, 0xc2, 0xad, 0xa0, 0xc0, 0x9d, 0x78, 0x07,
    0x48, 0xa9, 0x02, 0x8d, 0xaf, 0xc0, 0x68, 0x29, 0x0e, 0xf0, 0x02, 0x18,
    0x60, 0x38, 0x60, 0xad, 0xa1, 0xc0, 0x9d, 0x78, 0x04, 0xad, 0xa2, 0xc0,
    0x9d, 0x78, 0x05, 0xad, 0xa3, 0xc0, 0x9d, 0xf8, 0x04, 0xad, 0xa4, 0xc0,
    0x9d, 0xf8, 0x05, 0xad, 0xa0, 0xc0, 0x9d, 0x78, 0x07, 0x60, 0x20, 0x00,
    0xc2, 0x20, 0x87, 0xc2, 0xa9, 0x01, 0x8d, 0xaf, 0xc0, 0x18, 0x60, 0x20,
    0x00, 0xc2, 0xa9, 0x00, 0x9d, 0x78, 0x04, 0x9d, 0xf8, 0x04, 0x9d, 0x78,
    0x05, 0x9d, 0xf8, 0x05, 0x9d, 0x78, 0x07, 0x20, 0xd0, 0xc2, 0x4c, 0xac,
    0xc2, 0x20, 0x00, 0xc2, 0xbd, 0x78, 0x04, 0x8d, 0xa1, 0xc0, 0xbd, 0x78,
    0x05, 0x8d, 0xa2, 0xc0, 0xbd, 0xf8, 0x04, 0x8d, 0xa3, 0xc0, 0xbd, 0xf8,
    0x05, 0x8d, 0xa4, 0xc0, 0x18, 0x60, 0xa9, 0x01, 0x4c, 0x0d, 0xc2, 0x20,
    0x00, 0xc2, 0xa9, 0x03, 0x8d, 0xac, 0xc0, 0x4c, 0xb6, 0xc2, 0xea, 0xd6,
    0xea, 0xea, 0xea, 0xea
};

/* --mouse-plain: a slot ROM with the AppleMouse ID bytes ($Cn05 $38,
   $Cn07 $18, $Cn0B $01, $Cn0C $20, $CnFB $D6) and an AppleMouse II's
   first instruction (BIT $FF58), nothing of the Appletini's firmware and
   no registers behind $C0n0-$C0nF: a card the AppleMouse ID check
   accepts that is not the Appletini's (DOOM GS's probe, docs/PLAY.md,
   the mouse probe). */
static uint8_t plain_mouse_rom(unsigned offset)
{
    switch (offset) {
    case 0x00: return 0x2c;
    case 0x01: return 0x58;
    case 0x02: return 0xff;
    case 0x05: return 0x38;
    case 0x07: return 0x18;
    case 0x0b: return 0x01;
    case 0x0c: return 0x20;
    case 0xfb: return 0xd6;
    default: return 0x00;
    }
}

/* --mouse-apple: an AppleMouse II's slot ROM as far as a program reads
   it: the ID bytes, its first instruction (BIT $FF58) and the firmware's
   entry table at $Cn12-$Cn19 (the offsets of 342-0270-C's bank 0:
   SETMOUSE $B3, SERVEMOUSE $C4, READMOUSE $9B, CLEARMOUSE $A4, POSMOUSE
   $C0, CLAMPMOUSE $8A, HOMEMOUSE $DD, INITMOUSE $BC). Each entry holds an
   RTS; a2vm services the call when the CPU is about to run it
   (apple_mouse_call). */
static const uint8_t apple_entries[8] = {
    0xb3, 0xc4, 0x9b, 0xa4, 0xc0, 0x8a, 0xdd, 0xbc
};

static uint8_t apple_mouse_rom(unsigned offset)
{
    for (unsigned i = 0; i < 8; i++) {
        if (offset == 0x12u + i)
            return apple_entries[i];
        if (offset == apple_entries[i])
            return 0x60;
    }
    if (offset == 0xfb)
        return 0xd6;
    return plain_mouse_rom(offset);
}

static void halt(a2vm *m, const char *reason)
{
    if (!m->halt[0])
        snprintf(m->halt, sizeof m->halt, "%s", reason);
}

/* ---- time ---- */

int a2vm_in_vbl(const a2vm *m)
{
    return a2vm_now(m) % m->frame_cycles >= m->vbl_start;
}

uint64_t a2vm_bus_clock(const a2vm *m)
{
    return a2vm_now(m) * m->frame_1mhz / m->frame_cycles;
}

/* ---- the mouse card (a2sim.MouseCard) ---- */

enum { CMD_HOME = 1, CMD_CLAMP = 2, CMD_DEFAULTS = 3 };
enum { MODE_ENABLE = 1, MODE_MOVE_IRQ = 2, MODE_BUTTON_IRQ = 4,
       MODE_VBL_IRQ = 8 };

static int32_t clamp16(int64_t value, int64_t low, int64_t high)
{
    if (high < low)
        high = low;
    if (value < low)
        value = low;
    if (value > high)
        value = high;
    return (int32_t)value;
}

static void mouse_init(a2vm_mouse *c)
{
    memset(c, 0, sizeof *c);
    c->clamp[0][1] = c->clamp[1][1] = 1023;
    c->connected = 1;
}

static uint8_t mouse_status(const a2vm_mouse *c)
{
    unsigned b = c->buttons, p = c->prev_buttons;
    return (uint8_t)(((b & 1) << 7) | ((p & 1) << 6) | (c->moved << 5) |
                     (((b >> 1) & 1) << 4) | (c->vbl_pending << 3) |
                     (c->button_pending << 2) | (c->move_irq << 1) |
                     ((p >> 1) & 1));
}

static void mouse_commit(a2vm_mouse *c, int64_t x, int64_t y,
                         unsigned buttons, int connected)
{
    x = clamp16(x, 0, 0xffff);
    y = clamp16(y, 0, 0xffff);
    c->ps_x = (int32_t)x;
    c->ps_y = (int32_t)y;
    c->ps_buttons = (uint8_t)(buttons & 3);
    c->connected = (uint8_t)connected;
    if (connected && (c->mode & MODE_ENABLE)) {
        if (x != c->x || y != c->y) {
            c->moved = 1;
            if (c->mode & MODE_MOVE_IRQ)
                c->move_irq = c->irq = 1;
        }
        if (c->ps_buttons != c->buttons && (c->mode & MODE_BUTTON_IRQ))
            c->button_pending = c->irq = 1;
        c->x = clamp16(x, c->clamp[0][0], c->clamp[0][1]);
        c->y = clamp16(y, c->clamp[1][0], c->clamp[1][1]);
        c->buttons = c->ps_buttons;
    } else if (!connected)
        c->buttons = 0;
    c->seq++;
}

static void mouse_vblank(a2vm_mouse *c)
{
    if (c->mode & MODE_VBL_IRQ)
        c->vbl_pending = c->irq = 1;
}

static uint8_t mouse_read(a2vm_mouse *c, unsigned reg)
{
    const int32_t *window = c->clamp[c->clamp_axis];
    uint8_t value = 0;
    switch (reg) {
    case 0: value = mouse_status(c); break;
    case 1: value = (uint8_t)c->x; break;
    case 2: value = (uint8_t)(c->x >> 8); break;
    case 3: value = (uint8_t)c->y; break;
    case 4: value = (uint8_t)(c->y >> 8); break;
    case 5: value = c->buttons; break;
    case 6: value = c->seq; break;
    case 7: value = c->clamp_axis; break;
    case 8: value = (uint8_t)window[0]; break;
    case 9: value = (uint8_t)(window[0] >> 8); break;
    case 10: value = (uint8_t)window[1]; break;
    case 11: value = (uint8_t)(window[1] >> 8); break;
    case 14: value = c->mode; break;
    }
    c->log_reads++;
    return value;
}

static void mouse_reclamp(a2vm_mouse *c)
{
    c->x = clamp16(c->x, c->clamp[0][0], c->clamp[0][1]);
    c->y = clamp16(c->y, c->clamp[1][0], c->clamp[1][1]);
}

static void mouse_write(a2vm_mouse *c, unsigned reg, uint8_t value)
{
    int32_t *window = c->clamp[c->clamp_axis];
    c->log_writes++;
    switch (reg) {
    case 1: c->x = (c->x & 0xff00) | value; break;
    case 2: c->x = (c->x & 0x00ff) | value << 8; break;
    case 3: c->y = (c->y & 0xff00) | value; break;
    case 4: c->y = (c->y & 0x00ff) | value << 8; break;
    case 7: c->clamp_axis = value & 1; break;
    case 8: window[0] = (window[0] & 0xff00) | value; break;
    case 9: window[0] = (window[0] & 0x00ff) | value << 8; break;
    case 10: window[1] = (window[1] & 0xff00) | value; break;
    case 11: window[1] = (window[1] & 0x00ff) | value << 8; break;
    case 12:
        if (value == CMD_HOME) {
            c->x = c->clamp[0][0];
            c->y = c->clamp[1][0];
        } else if (value == CMD_CLAMP) {
            if (window[0] > window[1]) {
                window[1] = (window[0] + window[1]) & 0xffff;
                window[0] = 0;
            }
            mouse_reclamp(c);
        } else if (value == CMD_DEFAULTS) {
            c->clamp[0][0] = c->clamp[1][0] = 0;
            c->clamp[0][1] = c->clamp[1][1] = 1023;
            mouse_reclamp(c);
        }
        break;
    case 14: c->mode = value & 0x0f; break;
    case 15:
        if (value & 1) {
            c->moved = c->move_irq = c->button_pending = 0;
            c->vbl_pending = 0;
            c->prev_buttons = c->buttons;
        }
        if (value & 2)
            c->irq = 0;
        break;
    }
}

/* ---- --mouse-rom: an AppleMouse II running Apple's ROM ----

   GSSquared's applemouseiii (src/devices/applemouseiii: PIA6520.cpp,
   MouseController.cpp, applemouseiii.cpp) in C, function by function,
   with the same protocol and the same timing: the controller's run()
   at each PIA access (before and after a read, after a write) and at
   each VBL, nothing in between. Port B: bits 1-3 the ROM's bank (A8-A10,
   ORB and DDRB), bit 4 RDACK and bit 5 WRREQUEST from the 6502, bit 6
   RDREADY and bit 7 WRACK from the controller. */

enum {
    RM_RDACK = 0x10, RM_WRREQUEST = 0x20, RM_RDREADY = 0x40, RM_WRACK = 0x80,
    RM_SET = 0x00, RM_READ = 0x10, RM_SERVE = 0x20, RM_CLEAR = 0x30,
    RM_POS = 0x40, RM_INIT = 0x50, RM_CLAMP = 0x60, RM_HOME = 0x70,
    RM_TIME = 0x90, RM_A0 = 0xa0, RM_RDMEM = 0xf0,
    RM_WAS_BUTTON1 = 1, RM_IRQ_MOVEMENT = 2, RM_IRQ_BUTTON = 4,
    RM_IRQ_VBL = 8, RM_IS_BUTTON1 = 0x10, RM_MOVED = 0x20,
    RM_WAS_BUTTON0 = 0x40, RM_IS_BUTTON0 = 0x80,
    RM_MODE_ENABLED = 1, RM_MODE_MOVED_IRQ = 3, RM_MODE_BUTTON_IRQ = 5,
    RM_MODE_VBL_IRQ = 8,
    RM_IRQ_BITS = RM_IRQ_VBL | RM_IRQ_MOVEMENT | RM_IRQ_BUTTON
};

static uint8_t rm_port_a(const a2vm_romouse *r)
{
    return (uint8_t)((r->ora & r->ddra) | (r->ia & ~r->ddra));
}

static uint8_t rm_port_b(const a2vm_romouse *r)
{
    return (uint8_t)((r->orb & r->ddrb) | (r->ib & ~r->ddrb));
}

/* the bank at $Cn00 (PIA6520::rom_bank) */
static unsigned rm_bank(const a2vm_romouse *r)
{
    return (unsigned)((r->orb & r->ddrb & 0x0e) >> 1);
}

static void rm_irq(a2vm_romouse *r, int asserted)
{
    if (r->irq == asserted)
        return;
    r->irq = (uint8_t)asserted;
    if (asserted)
        r->irq_asserts++;
    else
        r->irq_releases++;
}

static void rm_notify_bank(a2vm_romouse *r)
{
    uint8_t bank = (uint8_t)rm_bank(r);
    if (bank != r->last_bank) {
        r->last_bank = bank;
        r->bank_switches++;
    }
}

static void rm_clamp_xy(a2vm_romouse *r)
{
    if (r->x < r->clamp_min_x)
        r->x = r->clamp_min_x;
    if (r->y < r->clamp_min_y)
        r->y = r->clamp_min_y;
    if (r->x > r->clamp_max_x)
        r->x = r->clamp_max_x;
    if (r->y > r->clamp_max_y)
        r->y = r->clamp_max_y;
}

static void rm_home(a2vm_romouse *r)
{
    r->x = r->last_x = r->clamp_min_x;
    r->y = r->last_y = r->clamp_min_y;
}

static void rm_command(a2vm_romouse *r)
{
    uint8_t *w = r->write_buffer, *b = r->read_buffer;
    r->commands[r->command >> 4]++;
    switch (r->command & 0xf0) {
    case RM_SET:
        r->mode = r->command & 0x0f;
        break;
    case RM_READ: {
        uint8_t st = r->int_state & RM_MOVED;
        if (r->last_button0)
            st |= RM_WAS_BUTTON0;
        if (r->last_button1)
            st |= RM_WAS_BUTTON1;
        if (r->button0)
            st |= RM_IS_BUTTON0;
        if (r->button1)
            st |= RM_IS_BUTTON1;
        b[4] = (uint8_t)(r->x & 0xff);
        b[3] = (uint8_t)((r->x >> 8) & 0xff);
        b[2] = (uint8_t)(r->y & 0xff);
        b[1] = (uint8_t)((r->y >> 8) & 0xff);
        b[0] = st;
        r->int_state = (uint8_t)(st & ~RM_MOVED);
        r->last_x = r->x;
        r->last_y = r->y;
        r->last_button0 = r->button0;
        r->last_button1 = r->button1;
        r->read_pos = 5;
        break;
    }
    case RM_SERVE:
        b[0] = (uint8_t)(r->int_state & ~RM_MOVED);
        r->read_pos = 1;
        r->int_state &= (uint8_t)~RM_IRQ_BITS;
        rm_irq(r, 0);
        break;
    case RM_CLEAR:
        r->x = r->y = 0;
        break;
    case RM_POS:
        r->x = (int16_t)(w[3] | w[2] << 8);
        r->y = (int16_t)(w[1] | w[0] << 8);
        rm_clamp_xy(r);
        r->last_x = r->x;
        r->last_y = r->y;
        break;
    case RM_INIT:
        r->clamp_max_x = r->clamp_max_y = 1023;
        r->clamp_min_x = r->clamp_min_y = 0;
        rm_home(r);
        rm_irq(r, 0);
        break;
    case RM_CLAMP: {
        int16_t low = (int16_t)(w[3] | w[1] << 8);
        int16_t high = (int16_t)(w[2] | w[0] << 8);
        if (low > high) {
            uint32_t t = (uint32_t)(int32_t)high + (uint32_t)(int32_t)low;
            high = (int16_t)(uint16_t)(t >> 1);
            low = 0;
        }
        if (r->command & 1) {
            r->clamp_min_y = low;
            r->clamp_max_y = high;
        } else {
            r->clamp_min_x = low;
            r->clamp_max_x = high;
        }
        rm_clamp_xy(r);
        break;
    }
    case RM_HOME:
        rm_home(r);
        break;
    case RM_TIME:
        r->intervbl = (r->command & 1) ? 20280 : 17030;
        break;
    case RM_RDMEM: {
        uint16_t address = (uint16_t)(w[1] | w[0] << 8);
        uint8_t v = 0;
        switch (address) {
        case 0x47: v = (uint8_t)(r->clamp_min_x >> 8); break;
        case 0x48: v = (uint8_t)(r->clamp_min_y >> 8); break;
        case 0x49: v = (uint8_t)r->clamp_min_x; break;
        case 0x4a: v = (uint8_t)r->clamp_min_y; break;
        case 0x4b: v = (uint8_t)(r->clamp_max_x >> 8); break;
        case 0x4c: v = (uint8_t)(r->clamp_max_y >> 8); break;
        case 0x4d: v = (uint8_t)r->clamp_max_x; break;
        case 0x4e: v = (uint8_t)r->clamp_max_y; break;
        }
        b[0] = v;
        r->read_pos = 1;
        break;
    }
    }
}

static void rm_accept(a2vm_romouse *r)
{
    if (r->write_pos)
        r->write_buffer[--r->write_pos] = rm_port_a(r);
    else {
        r->command = rm_port_a(r);
        switch (r->command & 0xf0) {
        case RM_POS:
        case RM_CLAMP: r->write_pos = 4; break;
        case RM_A0: r->write_pos = 1; break;
        case RM_RDMEM: r->write_pos = 2; break;
        case RM_TIME:
            switch (r->command & 0x0c) {
            case 0x4: r->write_pos = 2; break;
            case 0x8: r->write_pos = 1; break;
            case 0xc: r->write_pos = 3; break;
            }
            break;
        }
    }
    if (r->write_pos == 0)
        rm_command(r);
}

static void rm_run(a2vm_romouse *r)
{
    uint8_t port_b = rm_port_b(r);
    if ((port_b ^ r->last_port_b) & RM_WRREQUEST) {         /* process_write */
        if (port_b & RM_WRREQUEST) {
            r->read_pos = 0;
            rm_accept(r);
            r->ib = (uint8_t)((r->ib & ~RM_RDREADY) | RM_WRACK);
        } else if (r->ib & RM_WRACK)
            r->ib &= (uint8_t)~RM_WRACK;
    }
    if (port_b & RM_RDACK) {                                /* process_read */
        if (r->ib & RM_RDREADY) {
            if (r->read_pos > 0)
                r->read_pos--;
            r->ib &= (uint8_t)~RM_RDREADY;
        }
    } else if ((port_b & (RM_WRACK | RM_WRREQUEST)) == 0 &&
               (r->ib & RM_RDREADY) == 0) {
        r->ia = r->read_pos > 0 ? r->read_buffer[r->read_pos - 1] : 0x00;
        r->ib |= RM_RDREADY;
    }
    r->last_port_b = port_b;
    if (r->vbl_pending) {
        r->vbl_pending = 0;
        r->int_state |= RM_IRQ_VBL;
    }
    if ((r->int_state & RM_IRQ_BITS) && (r->old_int & RM_IRQ_BITS) == 0)
        rm_irq(r, 1);
    r->old_int = r->int_state;
}

static void rm_reset(a2vm_romouse *r)
{
    rm_irq(r, 0);
    r->ddra = r->ddrb = r->ora = r->orb = r->cra = r->crb = 0;
    r->ia = r->ib = 0;
    r->command = 0;
    memset(r->read_buffer, 0, sizeof r->read_buffer);
    memset(r->write_buffer, 0, sizeof r->write_buffer);
    r->read_pos = r->write_pos = 0;
    r->last_port_b = r->old_int = 0;
    r->intervbl = 17030;
    r->mode = r->int_state = r->vbl_pending = 0;
    r->x = r->y = r->last_x = r->last_y = 0;
    r->button0 = r->button1 = r->last_button0 = r->last_button1 = 0;
    r->clamp_min_x = r->clamp_min_y = 0;
    r->clamp_max_x = r->clamp_max_y = 1023;
    r->last_bank = 0xff;
    rm_notify_bank(r);
}

static uint8_t rm_pia_read(a2vm_romouse *r, unsigned address)
{
    uint8_t value;
    r->pia_reads++;
    rm_run(r);
    switch (address & 3) {
    case 0: value = (r->cra & 4) ? rm_port_a(r) : r->ddra; break;
    case 1: value = r->cra; break;
    case 2: value = (r->crb & 4) ? rm_port_b(r) : r->ddrb; break;
    default: value = r->crb; break;
    }
    rm_run(r);
    return value;
}

static void rm_pia_write(a2vm_romouse *r, unsigned address, uint8_t value)
{
    r->pia_writes++;
    switch (address & 3) {
    case 0:
        if (r->cra & 4)
            r->ora = value;
        else
            r->ddra = value;
        break;
    case 1: r->cra = value & 0x3f; break;
    case 2:
        if (r->crb & 4)
            r->orb = value;
        else
            r->ddrb = value;
        break;
    default: r->crb = value & 0x3f; break;
    }
    rm_notify_bank(r);
    rm_run(r);
}

static void rm_vbl(a2vm_romouse *r)
{
    r->vbls++;
    if (r->mode & RM_MODE_VBL_IRQ)
        r->vbl_pending = 1;
    rm_run(r);
}

static void rm_move_xy(a2vm_romouse *r, int8_t dx, int8_t dy)
{
    int16_t old_x = r->x, old_y = r->y;
    r->x = (int16_t)(r->x + dx);
    if (dx > 0) {
        if (r->x < old_x || r->x > r->clamp_max_x)
            r->x = r->clamp_max_x;
    } else if (r->x > old_x || r->x < r->clamp_min_x)
        r->x = r->clamp_min_x;
    r->y = (int16_t)(r->y + dy);
    if (dy > 0) {
        if (r->y < old_y || r->y > r->clamp_max_y)
            r->y = r->clamp_max_y;
    } else if (r->y > old_y || r->y < r->clamp_min_y)
        r->y = r->clamp_min_y;
    if (r->x != old_x || r->y != old_y) {
        r->int_state |= RM_MOVED;
        if ((r->mode & RM_MODE_MOVED_IRQ) == RM_MODE_MOVED_IRQ)
            r->int_state |= RM_IRQ_MOVEMENT;
    }
    rm_run(r);
}

static void rm_button(a2vm_romouse *r, int number, int pressed)
{
    if (number == 0)
        r->button0 = (uint8_t)(pressed != 0);
    else
        r->button1 = (uint8_t)(pressed != 0);
    if ((r->mode & RM_MODE_BUTTON_IRQ) == RM_MODE_BUTTON_IRQ)
        r->int_state |= RM_IRQ_BUTTON;
    rm_run(r);
}

/* a move of (dx, dy) in the controller's steps of -128..127 */
static void rm_delta(a2vm_romouse *r, int64_t dx, int64_t dy)
{
    while (dx || dy) {
        int64_t sx = dx < -128 ? -128 : dx > 127 ? 127 : dx;
        int64_t sy = dy < -128 ? -128 : dy > 127 ? 127 : dy;
        rm_move_xy(r, (int8_t)sx, (int8_t)sy);
        dx -= sx;
        dy -= sy;
    }
}

/* ---- the Phasor (a2sim.Phasor) ---- */

enum { MOCKINGBOARD = 0, NATIVE = 5 };

static void phasor_init(a2vm_phasor *f)
{
    memset(f, 0, sizeof *f);
    f->ssi_dur = 0xc0;
    memset(f->latched, 0xff, sizeof f->latched);
    for (unsigned i = 0; i < 2; i++) {
        f->t1[i].latch_lo = f->t1[i].latch_hi = 0xff;  /* power_reset */
        f->t1[i].load = 0xffff;
        f->t1[i].flag_bus = -1;
    }
    f->t1_clock = UINT64_MAX;
}

/* ---- --via-timers: timer 1 of each VIA, as via6522.v runs it ----

   The counter steps once an Apple bus cycle (via_timer_clock, sss_en:
   mockingboard.sv:86). Loaded with N (a write to T1C-H, which also loads
   the low latch), it reads N, N-1, ..., 0, then $FFFF, then the latch L
   again (via6522.v:338-352): the time-out, every L + 2 cycles. A
   time-out sets IFR bit 6 in free-run mode (ACR bit 6) and, in one-shot
   mode, the first one after the T1C-H write only (via6522.v:369-381).
   Reading T1C-L, writing T1C-H or T1L-H, or writing IFR with bit 6 set
   clears the flag (via6522.v:382-386); the VIA's IRQ is any IFR bit set
   whose IER bit is set (via6522.v:543). In Phasor native mode a read of
   T1C-L steps the counter once more (mockingboard.sv:87-97). The other
   IFR sources (CA1, CA2, CB1, CB2, the shift register, timer 2) are not
   modelled and stay clear. */

static uint16_t t1_latch(const a2vm_phasor *f, unsigned i)
{
    return (uint16_t)(f->t1[i].latch_hi << 8 | f->t1[i].latch_lo);
}

/* the counter at bus clock b; *undf: it is the $FFFF before a reload */
static uint16_t t1_counter(const a2vm_phasor *f, unsigned i, int64_t b,
                           int *undf)
{
    int64_t e = b - f->t1_start[i], load = f->t1[i].load;
    int64_t latch = t1_latch(f, i);
    *undf = 0;
    if (e < 0)
        e = 0;
    if (e <= load)
        return (uint16_t)(load - e);
    e -= load + 1;                  /* 0: the first $FFFF */
    int64_t r = e == 0 ? latch + 1 : (e - 1) % (latch + 2);
    if (r <= latch)
        return (uint16_t)(latch - r);
    *undf = 1;
    return 0xffff;
}

static uint64_t bus_to_clock(const a2vm *m, int64_t bus)
{
    if (bus < 0)
        return UINT64_MAX;
    uint64_t n = (uint64_t)bus * m->frame_cycles;
    return (n + m->frame_1mhz - 1) / m->frame_1mhz;
}

static void t1_reclock(a2vm *m)
{
    a2vm_phasor *f = &m->phasor;
    uint64_t a = bus_to_clock(m, f->t1[0].flag_bus);
    uint64_t b = bus_to_clock(m, f->t1[1].flag_bus);
    f->t1_clock = a < b ? a : b;
}

/* the next flag: the first time-out from t1_start, if one would flag */
static void t1_schedule(a2vm_phasor *f, unsigned i)
{
    if (!(f->t1[i].acr & 0x40) && !f->t1[i].armed)
        f->t1[i].flag_bus = -1;
    else
        f->t1[i].flag_bus = f->t1_start[i] + f->t1[i].load + 2;
}

/* the time-outs up to bus clock b */
static void t1_advance(a2vm_phasor *f, unsigned i, int64_t b)
{
    int64_t at = f->t1[i].flag_bus;
    if (at < 0 || at > b)
        return;
    f->t1[i].ifr |= 0x40;
    if (f->t1[i].acr & 0x40) {
        int64_t period = (int64_t)t1_latch(f, i) + 2;
        f->t1[i].flag_bus = at + ((b - at) / period + 1) * period;
    } else {
        f->t1[i].armed = 0;
        f->t1[i].flag_bus = -1;
    }
}

void a2vm_via_timers_update(a2vm *m)
{
    int64_t b = (int64_t)a2vm_bus_clock(m);
    t1_advance(&m->phasor, 0, b);
    t1_advance(&m->phasor, 1, b);
    t1_reclock(m);
}

/* before the latch or the mode changes: the counter's state now becomes
   the new origin, so the reloads to come use the new values */
static void t1_rebase(a2vm_phasor *f, unsigned i, int64_t b)
{
    int undf;
    uint16_t value = t1_counter(f, i, b, &undf);
    if (undf) {                     /* the $FFFF before a reload */
        f->t1_start[i] = b - 1;
        f->t1[i].load = 0;
    } else {
        f->t1_start[i] = b;
        f->t1[i].load = value;
    }
}

static int via_irq(const a2vm *m)
{
    if (!m->via_timers)
        return 0;
    const a2vm_phasor *f = &m->phasor;
    return ((f->t1[0].ifr & f->t1[0].ier) | (f->t1[1].ifr & f->t1[1].ier))
           != 0;
}

/* a write to register reg of VIA i; 0 for a register this does not
   model (the caller's own handling then applies) */
static int t1_write(a2vm *m, unsigned i, unsigned reg, uint8_t value)
{
    a2vm_phasor *f = &m->phasor;
    int64_t b = (int64_t)a2vm_bus_clock(m);
    t1_advance(f, i, b);
    switch (reg) {
    case 4: case 6:                 /* T1C-L, T1L-L: the low latch */
        t1_rebase(f, i, b);
        f->t1[i].latch_lo = value;
        break;
    case 5:                         /* T1C-H: load and start */
        f->t1[i].latch_hi = value;
        f->t1_start[i] = b;
        f->t1[i].load = t1_latch(f, i);
        f->t1[i].ifr &= (uint8_t)~0x40;
        f->t1[i].armed = 1;
        break;
    case 7:                         /* T1L-H */
        t1_rebase(f, i, b);
        f->t1[i].latch_hi = value;
        f->t1[i].ifr &= (uint8_t)~0x40;
        break;
    case 11:
        t1_rebase(f, i, b);
        f->t1[i].acr = value;
        break;
    case 13:
        f->t1[i].ifr &= (uint8_t)~(value & 0x7f);
        return 1;
    case 14:
        if (value & 0x80)
            f->t1[i].ier |= value & 0x7f;
        else
            f->t1[i].ier &= (uint8_t)~(value & 0x7f);
        return 1;
    default:
        return 0;
    }
    t1_schedule(f, i);
    t1_advance(f, i, b);
    t1_reclock(m);
    return 1;
}

/* a read of register reg of VIA i: the value, or -1 for a register this
   does not model */
static int t1_read(a2vm *m, unsigned i, unsigned reg)
{
    a2vm_phasor *f = &m->phasor;
    int64_t b = (int64_t)a2vm_bus_clock(m);
    int undf, value;
    /* a read returns the counter before this cycle's step
       (timer1_bus_value, via6522.v:319-332): its value at the end of the
       cycle before */
    int64_t before = b > f->t1_start[i] ? b - 1 : b;
    t1_advance(f, i, b);
    switch (reg) {
    case 4:
        value = t1_counter(f, i, before, &undf) & 0xff;
        f->t1[i].ifr &= (uint8_t)~0x40;
        if (f->mode == NATIVE) {    /* one more step: the whole run of
                                       the counter one cycle sooner */
            f->t1_start[i]--;
            if (f->t1[i].flag_bus >= 0)
                f->t1[i].flag_bus--;
            t1_advance(f, i, b);
            t1_reclock(m);
        }
        return value;
    case 5: return t1_counter(f, i, before, &undf) >> 8;
    case 6: return f->t1[i].latch_lo;
    case 7: return f->t1[i].latch_hi;
    case 11: return f->t1[i].acr;
    case 13:
        return ((f->t1[i].ifr & f->t1[i].ier) ? 0x80 : 0) | f->t1[i].ifr;
    case 14: return 0x80 | f->t1[i].ier;
    default: return -1;
    }
}

static void phasor_mode_switch(a2vm *m, unsigned address)
{
    a2vm_phasor *f = &m->phasor;
    unsigned before = f->mode;
    if (address & 8)
        f->mode = MOCKINGBOARD;
    f->mode |= address & 7;
    if (m->sound_event && before != f->mode)
        m->sound_event(m, 2, 0, 0, f->mode);
}

/* _vias_for: a mask of the VIAs the address selects. */
static unsigned phasor_vias(const a2vm_phasor *f, unsigned address)
{
    if (f->mode == 7) return 2;
    if (f->mode == NATIVE)
        return (address & 0x10 ? 1u : 0u) | (address & 0x80 ? 2u : 0u);
    return address & 0x80 ? 2u : 1u;
}

static int phasor_ssi_hit(const a2vm_phasor *f, unsigned address)
{
    return f->mode == NATIVE && (address & 0xf8) == 0x40;
}

static void phasor_chip_selects(const a2vm_phasor *f, unsigned index,
                                int *cs0, int *cs1)
{
    unsigned bus = f->via[index].orb & f->via[index].ddrb;
    if (f->mode == NATIVE || f->mode == 7) {
        *cs0 = !(bus & 0x10);
        *cs1 = !(bus & 0x08);
    } else {
        *cs0 = 1;
        *cs1 = 0;
    }
}

/* --ay-log: the time fields of a line (README.md, "The AY log"). */
static void ay_log_time(const a2vm *m)
{
    uint64_t cycles = m->core == A2VM_CORE_PY65 ? m->py65_cycles
                                                : m->cpu.cycles;
    fprintf(m->ay_log, " %" PRIu64 " %" PRIu64, cycles, a2vm_bus_clock(m));
    if (m->cost)
        fprintf(m->ay_log, " %" PRIu64, m->cost->t);
    else
        fputs(" -", m->ay_log);
}

static void phasor_port_b(a2vm *m, unsigned index)
{
    a2vm_phasor *f = &m->phasor;
    unsigned bus = f->via[index].orb & f->via[index].ddrb;
    int cs0, cs1;
    phasor_chip_selects(f, index, &cs0, &cs1);
    unsigned function = bus & 7;
    int native = f->mode == NATIVE || f->mode == 7;
    if (!(bus & 4)) {
        memset(f->ay[index * 2], 0, 16);
        memset(f->ay[index * 2 + 1], 0, 16);
        f->latched[index * 2] = f->latched[index * 2 + 1] = 0xff;
        f->selected[index][0] = f->selected[index][1] = 0;
        if (m->sound_event) {
            m->sound_event(m, 1, index * 2, 0, 0);
            m->sound_event(m, 1, index * 2 + 1, 0, 0);
        }
        if (m->ay_log)
            for (unsigned chip = index * 2; chip < index * 2 + 2; chip++) {
                fputs("reset", m->ay_log);
                ay_log_time(m);
                fprintf(m->ay_log, " %u\n", chip);
            }
    } else if (function == 7) {
        if (!native) {
            f->latched[index * 2] = f->via[index].ora;
            return;
        }
        if (cs0 || cs1)
            f->latched[index * 2] = f->via[index].ora;
        if (cs1) {
            f->latched[index * 2 + 1] = f->via[index].ora;
            f->selected[index][0] = f->selected[index][1] = 1;
        } else if (cs0) {
            f->selected[index][0] = 1;
            f->selected[index][1] = 0;
        }
    } else if (function == 6) {
        unsigned targets[2], count = 0;
        if (!native)
            targets[count++] = index * 2;
        else if (f->mode == 7) {
            if (cs0) targets[count++] = index * 2;
            if (cs1 || (cs0 && f->selected[index][1]))
                targets[count++] = index * 2 + 1;
        } else {
            if (cs0 && f->selected[index][0])
                targets[count++] = index * 2;
            if ((cs0 || cs1) && f->selected[index][1])
                targets[count++] = index * 2 + 1;
        }
        for (unsigned i = 0; i < count; i++) {
            unsigned chip = targets[i];
            if (f->latched[chip] > 15) continue;
            if (m->sound_event)
                m->sound_event(m, 0, chip, f->latched[chip], f->via[index].ora);
            f->ay[chip][f->latched[chip] & 15] = f->via[index].ora;
            f->ay_writes++;
            if (m->ay_log) {
                fputs("w", m->ay_log);
                ay_log_time(m);
                fprintf(m->ay_log, " %u %u %u\n", chip,
                        f->latched[chip] & 15u, f->via[index].ora);
            }
        }
    }
}

static void phasor_write(a2vm *m, unsigned address, uint8_t value)
{
    a2vm_phasor *f = &m->phasor;
    if (m->speech_write)
        m->speech_write(m, address, value);
    if (!m->speech_write && phasor_ssi_hit(f, address)) {
        unsigned reg = address & 7;
        if (reg == 0) {
            f->ssi_dur = value;
            f->ssi_started = (int64_t)a2vm_bus_clock(m);
            f->ssi_running = 1;
            f->ssi_phonemes++;
        } else if (reg == 2)
            f->ssi_rate = value;
        else if (reg == 3 && (value & 0x80))
            f->ssi_running = 0;
        return;
    }
    unsigned vias = phasor_vias(f, address);
    for (unsigned index = 0; index < 2; index++) {
        if (!(vias & (1u << index)))
            continue;
        if (m->via_timers && t1_write(m, index, address & 0x0f, value))
            continue;
        switch (address & 0x0f) {
        case 0: f->via[index].orb = value; phasor_port_b(m, index); break;
        case 1: f->via[index].ora = value; break;
        case 2: f->via[index].ddrb = value; break;
        case 3: f->via[index].ddra = value; break;
        case 5: f->t1_start[index] = (int64_t)a2vm_bus_clock(m); break;
        case 15:
            /* ORA without handshake, as via6522.v:149 writes it; a2sim.py
               ignores the register, so only --via-ora-nh does this */
            if (m->via_ora_nh)
                f->via[index].ora = value;
            break;
        }
    }
}

static uint8_t phasor_read(a2vm *m, unsigned address)
{
    a2vm_phasor *f = &m->phasor;
    if (m->speech_read) {
        int data = m->speech_read(m, address);
        if (data >= 0) return (uint8_t)data;
    }
    if (!m->speech_read && phasor_ssi_hit(f, address)) {
        if (!f->ssi_running)
            return 0;
        int64_t ticks = (int64_t)(4 - (f->ssi_dur >> 6)) *
                        (16 - (f->ssi_rate >> 4)) * 4096;
        return (int64_t)a2vm_bus_clock(m) - f->ssi_started >= ticks ? 0x80 : 0;
    }
    unsigned vias = phasor_vias(f, address);
    for (unsigned index = 0; index < 2; index++) {
        if (!(vias & (1u << index)))
            continue;
        unsigned reg = address & 0x0f;
        if (m->via_timers) {
            int value = t1_read(m, index, reg);
            if (value >= 0)
                return (uint8_t)value;
        }
        int64_t t1 = (0xffff - ((int64_t)a2vm_bus_clock(m) -
                                f->t1_start[index])) & 0xffff;
        switch (reg) {
        case 0: return f->via[index].orb;
        case 1: {
            unsigned bus = f->via[index].orb & f->via[index].ddrb;
            if (f->via[index].ddra == 0 && (bus & 7) == 5) {
                int cs0, cs1;
                phasor_chip_selects(f, index, &cs0, &cs1);
                static const uint8_t masks[16] = {
                    255,15,255,15,255,15,31,255,31,31,31,255,255,15,255,255
                };
                unsigned primary = f->mode == NATIVE ?
                    cs0 && f->selected[index][0] : cs0;
                unsigned secondary = f->mode == NATIVE ?
                    (cs0 || cs1) && f->selected[index][1] :
                    f->mode == 7 && (cs1 || (cs0 && f->selected[index][1]));
                unsigned value = 0;
                if (!primary && !secondary) return 0xff;
                for (unsigned j = 0; j < 2; j++) {
                    if (!(j ? secondary : primary)) continue;
                    unsigned chip = index * 2 + j, reg = f->latched[chip];
                    value |= reg < 16 ? f->ay[chip][reg] & masks[reg] : 0xff;
                }
                return (uint8_t)value;
            }
            return f->via[index].ora;
        }
        case 2: return f->via[index].ddrb;
        case 3: return f->via[index].ddra;
        case 4: return (uint8_t)t1;
        case 5: return (uint8_t)(t1 >> 8);
        }
        /* a register a2sim does not model: the first VIA of the list
           answers nothing and the loop goes on to the next */
    }
    return 0xff;
}

/* ---- the memory API (a2sim.FakeSmartPortMemory) ---- */

static void amem_init(a2vm_amem *a)
{
    static const uint8_t caps[16] = {
        'A', 'M', 'E', 'M', 1, 0, 16, 16, 7, 0, 0, 2, 0, 0xc0, 0x7e, 1
    };
    uint8_t *input = a->input;
    memset(a, 0, sizeof *a);
    a->input = input;
    a->supported = a->available = a->private_port = 1;
    a->rom[1] = 0x20;
    a->rom[3] = 0;
    a->rom[5] = 3;
    a->rom[7] = 0;
    a->rom[0xff] = 0x0a;
    memcpy(a->caps, caps, sizeof caps);
    a->caps[20] = 0x00;
    a->caps[21] = 0x02;
}

void a2vm_amem_options(a2vm *m, int supported, int available,
                       int private_port)
{
    m->amem.supported = (uint8_t)!!supported;
    m->amem.available = (uint8_t)!!available;
    m->amem.private_port = (uint8_t)!!private_port;
}

static void amem_malformed(a2vm *m, const char *what)
{
    char text[200];
    snprintf(text, sizeof text, "amem-malformed: %s", what);
    halt(m, text);
}

static int all_zero(const uint8_t *data, size_t length)
{
    for (size_t i = 0; i < length; i++)
        if (data[i])
            return 0;
    return 1;
}

static uint8_t *amem_storage(a2vm *m, unsigned space, unsigned bank)
{
    return space == 0 ? m->main : m->aux_banks + (size_t)bank * A2VM_BANK_SIZE;
}

/* _execute: the reply to a request, or 0 bytes (and m->halt) where the
   fake raises AssertionError. */
size_t a2vm_amem_execute(a2vm *m, uint8_t family, const uint8_t *request,
                         size_t length, uint8_t *reply)
{
    a2vm_amem *a = &m->amem;
    if (family != 2 || length < 10 || request[1] != 3 || request[2] != 0) {
        amem_malformed(m, "a request that is not a SmartPort call");
        return 0;
    }
    if (!all_zero(request + 6, 4)) {
        amem_malformed(m, "parameter padding is not zero");
        return 0;
    }
    uint8_t command = request[0], selector = request[5];
    if (command == 0) {
        if (length != 10) {
            amem_malformed(m, "STATUS request with trailing bytes");
            return 0;
        }
        if (selector != 0x80 || !a->supported) {
            reply[0] = 0x21;
            return 1;
        }
        a->caps[15] = a->available;
        reply[0] = 0;
        reply[1] = 0x20;
        reply[2] = 0;
        memcpy(reply + 3, a->caps, 32);
        return 35;
    }
    if (command != 4 || selector != 0x80 || length < 12) {
        reply[0] = 0x21;
        return 1;
    }
    size_t payload = request[10] | (size_t)request[11] << 8;
    if (length != 12 + payload) {
        amem_malformed(m, "CONTROL payload length differs from the bytes sent");
        return 0;
    }
    if (!a->supported || !a->available) {
        reply[0] = 0x60;
        return 1;
    }
    const uint8_t *data = request + 12;
    if (payload < 8 || memcmp(data, "AMEM\1", 5) || data[6] || data[7] ||
        data[5] < 1 || data[5] > 16 || payload != 8 + 16u * data[5]) {
        reply[0] = 0x61;
        return 1;
    }
    struct { unsigned op, has_source, source[3], destination[3], size, fill; }
        list[16];
    unsigned count = 0;
    for (size_t position = 8; position < payload; position += 16) {
        const uint8_t *d = data + position;
        unsigned op = d[0], flags = d[1];
        unsigned size = d[10] | d[11] << 8;
        if ((op != 1 && op != 2) || (flags & ~1u) || !all_zero(d + 13, 3) ||
            (op == 1 && d[12]) || (op == 2 && !all_zero(d + 2, 4))) {
            reply[0] = 0x62;
            return 1;
        }
        unsigned endpoints[2][3];
        unsigned first = op == 1 ? 0 : 1;
        for (unsigned e = first; e < 2; e++) {
            unsigned offset = e ? 6 : 2;
            unsigned space = d[offset], bank = d[offset + 1];
            unsigned address = d[offset + 2] | d[offset + 3] << 8;
            if (space > 1 || (space == 0 && bank) || bank > 126 || !size ||
                address < 0x200 || address + size > 0xc000) {
                reply[0] = 0x63;
                return 1;
            }
            endpoints[e][0] = space;
            endpoints[e][1] = bank;
            endpoints[e][2] = address;
        }
        if (op == 1 && endpoints[0][0] == endpoints[1][0] &&
            endpoints[0][1] == endpoints[1][1] &&
            endpoints[0][2] < endpoints[1][2] + size &&
            endpoints[1][2] < endpoints[0][2] + size) {
            reply[0] = 0x64;
            return 1;
        }
        if (!(flags & 1) && (endpoints[1][0] == 0 || endpoints[1][1] == 0)) {
            reply[0] = 0x65;
            return 1;
        }
        list[count].op = op;
        list[count].has_source = op == 1;
        memcpy(list[count].source, endpoints[0], sizeof endpoints[0]);
        memcpy(list[count].destination, endpoints[1], sizeof endpoints[1]);
        list[count].size = size;
        list[count].fill = d[12];
        count++;
    }
    for (unsigned i = 0; i < count; i++) {
        uint8_t *target = amem_storage(m, list[i].destination[0],
                                       list[i].destination[1]) +
                          list[i].destination[2];
        if (list[i].has_source)
            memmove(target, amem_storage(m, list[i].source[0],
                                         list[i].source[1]) +
                            list[i].source[2], list[i].size);
        else
            memset(target, (int)list[i].fill, list[i].size);
        a->completed++;
    }
    reply[0] = 0;
    return 1;
}

/* FakeSmartPortMemory.read: -1 where it returns None. */
static int amem_read(a2vm *m, uint16_t address)
{
    a2vm_amem *a = &m->amem;
    if (address == 0xcfff) {
        a->selected = 0;
        return -1;
    }
    if (m->sw[SW_INTCXROM])
        return -1;
    if (address < 0xc800) {
        a->selected = address >= 0xc700;
        return a->selected ? a->rom[address & 0xff] : -1;
    }
    if (!a->selected)
        return -1;
    if (address == 0xcff0)
        return a->output_length ? a->output[0] : 0;
    if (address == 0xcff1)
        return (a->private_port ? 0x20 : 0) | (a->ready ? 0x80 : 0);
    return -1;
}

/* FakeSmartPortMemory.write: 1 when it takes the write. */
static int amem_write(a2vm *m, uint16_t address, uint8_t value)
{
    a2vm_amem *a = &m->amem;
    if (address == 0xcfff) {
        a->selected = 0;
        return 1;
    }
    if (m->sw[SW_INTCXROM] || !a->selected)
        return 0;
    if (address == 0xcff0) {
        if (a->input_length == A2VM_AMEM_BUFFER)
            amem_malformed(m, "a request longer than any the API takes");
        else
            a->input[a->input_length++] = value;
    } else if (address == 0xcff2) {
        if (!a->output_length)
            amem_malformed(m, "SmartPort caller popped an empty reply");
        else
            memmove(a->output, a->output + 1, --a->output_length);
    } else if (address == 0xcff1) {
        uint8_t reply[64];
        size_t length = a->input_length;
        a->input_length = 0;
        a->requests++;
        if (m->zpb.rd || m->zpb.wr)
            m->zpb.amem++;          /* a firmware call with the pair set */
        a->last_family = value;
        size_t n = a2vm_amem_execute(m, value, a->input, length, reply);
        if (m->halt[0])
            return 1;
        if (m->cost && n && reply[0] == 0)
            a2vm_cost_amem(m, a->input, length);
        memcpy(a->output, reply, n);
        a->output_length = n;
        a->last_result = reply[0];
        a->ready = !a->never_ready;
    } else
        return 0;
    return 1;
}

/* ---- memory map (a2sim.Machine.__getitem__ and __setitem__) ---- */

static int aux_selected(const a2vm *m, unsigned address, a2vm_switch flag)
{
    if (m->sw[SW_STORE80]) {
        if (address >= 0x0400 && address < 0x0800)
            return m->sw[SW_PAGE2];
        if (m->sw[SW_HIRES] && address >= 0x2000 && address < 0x4000)
            return m->sw[SW_PAGE2];
    }
    return m->sw[flag];
}

/* The storage of the language card at `address` ($D000-$FFFF) as the
   CPU sees it with the card enabled. */
static uint8_t *lc_target(a2vm *m, unsigned address)
{
    int bank1 = address < 0xe000 && !m->lc_bank2;
    if (m->sw[SW_ALTZP])
        return m->aux + (bank1 ? address - 0x1000 : address);
    if (bank1)
        return m->lc1 + (address - 0xd000);
    return m->lc + (address - 0xc000);
}

void a2vm_remap(a2vm *m)
{
    uint8_t *zp = m->sw[SW_ALTZP] ? m->aux : m->main;
    for (unsigned page = 0; page < 2; page++) {
        m->rpage[page] = zp + page * 256;
        m->wpage[page] = zp + page * 256;
        m->wflag[page] = 0;
    }
    for (unsigned page = 2; page < 0xc0; page++) {
        unsigned address = page << 8;
        int read_aux = aux_selected(m, address, SW_RAMRD);
        int write_aux = aux_selected(m, address, SW_RAMWRT);
        m->rpage[page] = (read_aux ? m->aux : m->main) + address;
        m->wpage[page] = (write_aux ? m->aux : m->main) + address;
        int text = page >= 0x04 && page < 0x0c;
        if (write_aux)
            m->wflag[page] = m->bank == 0 && (text || (page >= 0x20 &&
                                                       page < 0xa0))
                             ? (page >= 0x20 ? 3 : 1) : 0;
        else
            m->wflag[page] = text || (page >= 0x20 && page < 0x60);
        m->vflag[page] = (uint8_t)(write_aux && page >= 0x20 && page < 0xa0);
    }
    for (unsigned page = 0xc0; page < 0xd0; page++) {
        m->rpage[page] = NULL;
        m->wpage[page] = NULL;
        m->wflag[page] = 0;
    }
    for (unsigned page = 0xd0; page < 0x100; page++) {
        unsigned address = page << 8;
        m->rpage[page] = m->lc_read ? lc_target(m, address)
                                    : m->rom + (address - 0xc000);
        m->wpage[page] = m->lc_write ? lc_target(m, address) : NULL;
        m->wflag[page] = 0;
    }
}

void a2vm_select_bank(a2vm *m, unsigned value)
{
    m->bank = (value & 0x7f) % m->ramworks_banks;
    m->aux = m->aux_banks + (size_t)m->bank * A2VM_BANK_SIZE;
    a2vm_remap(m);
}

uint8_t *a2vm_storage(a2vm *m, int kind, unsigned bank, uint16_t address)
{
    switch (kind) {
    case 0: return m->main + address;
    case 1: return bank < A2VM_MAX_BANKS
                   ? m->aux_banks + (size_t)bank * A2VM_BANK_SIZE + address
                   : NULL;
    case 2: return address >= 0xc000 ? m->lc + (address - 0xc000) : NULL;
    case 3: return address >= 0xd000 && address < 0xe000
                   ? m->lc1 + (address - 0xd000) : NULL;
    }
    return NULL;
}

/* ---- I/O ($C000-$C0FF): a2sim.Machine._io_read and _io_write ---- */

static const int8_t status_switch[32] = {
    [0x13] = SW_RAMRD, [0x14] = SW_RAMWRT, [0x15] = SW_INTCXROM,
    [0x16] = SW_ALTZP, [0x17] = SW_SLOTC3ROM, [0x18] = SW_STORE80,
    [0x1a] = SW_TEXT, [0x1b] = SW_MIXED, [0x1c] = SW_PAGE2,
    [0x1d] = SW_HIRES, [0x1e] = SW_ALTCHAR, [0x1f] = SW_COL80
};

static uint8_t keyboard(a2vm *m)
{
    if (!(m->key_latch & 0x80) && m->key_count &&
        a2vm_now(m) >= m->keys[0].when) {
        m->key_latch = m->keys[0].key | 0x80;
        memmove(m->keys, m->keys + 1, --m->key_count * sizeof m->keys[0]);
    }
    return m->key_latch;
}

static void video_switch(a2vm *m, unsigned low)
{
    static const a2vm_switch names[4] = { SW_TEXT, SW_MIXED, SW_PAGE2,
                                          SW_HIRES };
    a2vm_switch s = names[(low - 0x50) >> 1];
    m->sw[s] = low & 1;
    if (s == SW_PAGE2 || s == SW_HIRES)
        a2vm_remap(m);
}

static void lc_switch(a2vm *m, unsigned low, int is_read)
{
    m->lc_bank2 = !(low & 8);
    m->lc_read = (low & 3) == 0 || (low & 3) == 3;
    if (low & 1) {
        if (is_read) {
            if (m->lc_prewrite)
                m->lc_write = 1;
            m->lc_prewrite = 1;
        } else
            m->lc_prewrite = 0;
    } else {
        m->lc_write = 0;
        m->lc_prewrite = 0;
    }
    a2vm_remap(m);
}

/* ---- the zero-page bank pair (README.md, "The zero-page bank pair") ----

   The firmware design's pair as corrected in its review, with the RTL
   places it builds on (appletini-one, F1.2.1):

   - A write to $C069 while the pair is armed sets the pair and clears
     both registers: $00 or $FF turns it off, $01-$FE makes that byte
     zp_rd and the next zp_wr. The write stays an ordinary bus cycle (the
     X_ROUTE branch is not changed): a2vm's I/O write does nothing
     else, as a2sim.py's did nothing for $C069. Reads of $C069
     are unchanged.
   - While the pair is on, a committed CPU write whose decode is main
     zero page loads the register its address names; writes to aux zero
     page (ALTZP) are ignored. The value applies on the next edge: every write to $00xx is the last cycle of
     its instruction and the first redirected access comes at least 4
     cycles later, so a2vm applies it at once.
   - A stored 1-126 selects that $C073 bank (physical bank value + 1);
     0 and 127-255 follow the switches.
   - Only data_ea cycles (cpu65c02.h) to $0200-$BFFF are redirected, by
     zp_rd for reads and zp_wr for writes, and the redirect wins over
     RAMRD, RAMWRT, 80STORE and PAGE2 (the override comes after the
     80STORE block of translate_apple_addr, globals.sv:263-269).
     Redirected banks are PSRAM banks of 2 or more, so a redirected write
     is never posted, shadowed or counted as a video write
     (vtw_core_top.sv:565-569).
   - Reset: off at power-on, on RES#
     (a2vm_zpbank_reset) and when disarmed; kept across everything else.
   - The memory API and pokes from outside the CPU never load it (they do not
     go through the CPU; the API cannot reach zero page). */

static uint8_t zpb_decode(uint8_t value)
{
    return value >= 1 && value <= 126 ? value : 0;
}

static void zpb_enable(a2vm *m, uint8_t value)
{
    m->zpb.enables++;
    m->zpb.address = value == 0xff ? 0 : value;
    m->zpb.rd = m->zpb.wr = 0;
}

/* A committed CPU write to main zero page. */
static void zpb_watch(a2vm *m, uint16_t address, uint8_t value)
{
    if (address == m->zpb.address) {
        m->zpb.rd = zpb_decode(value);
        m->zpb.loads++;
    } else if (address == (uint16_t)(m->zpb.address + 1)) {
        m->zpb.wr = zpb_decode(value);
        m->zpb.loads++;
    }
}

/* A breach of the pair's contract: firmware (the slot ROMs or the //e
   ROM) running while the pair redirects. */
static int zpb_in_firmware(const a2vm *m)
{
    uint16_t pc = m->instruction_pc;
    return (pc >= 0xc100 && pc < 0xd000) || (pc >= 0xd000 && !m->lc_read);
}

static inline int zpb_redirects(uint16_t address)
{
    return address >= 0x0200 && address < 0xc000;
}

static uint8_t *zpb_page(a2vm *m, uint8_t bank, uint16_t address)
{
    if (zpb_in_firmware(m))
        m->zpb.firmware++;
    return m->aux_banks + (size_t)bank * A2VM_BANK_SIZE + (address & 0xff00);
}

int a2vm_zpbank_arm(a2vm *m, int on, char *error, size_t error_size)
{
    if (on && m->core != A2VM_CORE_W65C02S) {
        snprintf(error, error_size, "the zero-page pair needs the exact "
                 "core (--core w65c02s): the compatibility core does not "
                 "class its cycles");
        return 0;
    }
    if (on && m->ramworks_banks != A2VM_MAX_BANKS) {
        snprintf(error, error_size, "the zero-page pair needs %d RamWorks "
                 "banks (the card's 8 MB)", A2VM_MAX_BANKS);
        return 0;
    }
    m->zpb.armed = (uint8_t)!!on;
    if (!on)
        a2vm_zpbank_reset(m);
    return 1;
}

void a2vm_zpbank_reset(a2vm *m)
{
    m->zpb.address = m->zpb.rd = m->zpb.wr = 0;
}

/* ---- the VidHD (--vidhd; a2vm.h, README.md "The VidHD") ---- */

static void vidhd_note(a2vm_vidhd_note *notes, uint64_t total, uint16_t pc,
                       uint16_t address, uint8_t bank, uint32_t count,
                       uint64_t clock)
{
    if (total > A2VM_VIDHD_RECORDS)
        return;                     /* (total: this one included) */
    a2vm_vidhd_note *n = &notes[total - 1];
    n->pc = pc;
    n->address = address;
    n->bank = bank;
    n->count = count;
    n->clock = clock;
}

/* Does the SHADOW register's value `s` let a write of aux `address`
   ($2000-$9FFF) into the copy? (the IIgs rules: bit 1 hi-res page 1,
   bit 2 page 2, bit 3 SHR, bit 4 aux hi-res inhibited) */
static int vidhd_shadowed(uint8_t s, uint16_t address)
{
    if (!(s & 0x08))
        return 1;
    if (address < 0x4000)
        return !(s & 0x02) && !(s & 0x10);
    if (address < 0x6000)
        return !(s & 0x04) && !(s & 0x10);
    return 0;
}

/* A CPU write that reaches aux $2000-$9FFF of the bank selected. */
static void vidhd_write(a2vm *m, uint16_t address, uint8_t value)
{
    a2vm_vidhd *v = &m->vidhd;
    if (vidhd_shadowed(v->shadow, address)) {
        v->copy[address - 0x2000] = value;
        v->fed++;
        if (m->bank != 0) {
            v->foreign++;
            if (v->c035_writes)     /* (its notes then: a program's) */
                v->foreign_after++;
            vidhd_note(v->foreign_notes, v->c035_writes ? v->foreign_after
                       : v->foreign, m->instruction_pc, address,
                       (uint8_t)m->bank, 0, a2vm_now(m));
        }
    } else if (m->bank == 0) {
        v->unshadowed++;
        vidhd_note(v->unshadowed_notes, v->unshadowed, m->instruction_pc,
                   address, 0, 0, a2vm_now(m));
    }
}

/* An access of $C030-$C03F: a //e's speaker toggles. Two in a row (the
   second in the very next instruction) leave it as it was within a few
   cycles; any other is a click. */
static void vidhd_speaker(a2vm *m, uint16_t address)
{
    a2vm_vidhd *v = &m->vidhd;
    v->speaker++;
    if (v->pending && m->instructions == v->pending_instruction + 1) {
        v->pairs++;
        v->pending = 0;
        return;
    }
    if (v->pending) {
        v->unpaired++;
        vidhd_note(v->unpaired_notes, v->unpaired, v->pending_pc,
                   v->pending_address, 0, 0, a2vm_now(m));
    }
    v->pending = 1;
    v->pending_instruction = m->instructions;
    v->pending_pc = m->instruction_pc;
    v->pending_address = address;
}

static uint8_t vidhd_rom(unsigned offset)
{
    static const uint8_t id[3] = { 0x24, 0xea, 0x4c };
    return offset < 3 ? id[offset] : 0x00;
}

int a2vm_vidhd_checks(a2vm *m, const uint16_t *pcs, unsigned count)
{
    a2vm_vidhd *v = &m->vidhd;
    if (!v->slot || count > A2VM_VIDHD_CHECKS)
        return 0;
    if (!v->check_map) {
        v->check_map = calloc(1, 8192);
        if (!v->check_map)
            return 0;
    }
    for (unsigned i = 0; i < count; i++) {
        v->check_pcs[i] = pcs[i];
        v->check_map[pcs[i] >> 3] |= (uint8_t)(1u << (pcs[i] & 7));
    }
    v->check_count = count;
    return 1;
}

int a2vm_vidhd_check(a2vm *m, uint16_t pc)
{
    a2vm_vidhd *v = &m->vidhd;
    const uint8_t *aux0 = m->aux_banks + 0x2000;
    uint32_t differ = 0;
    unsigned first = 0;
    if (memcmp(v->copy, aux0, 0x8000))
        for (unsigned i = 0x8000; i-- > 0;)
            if (v->copy[i] != aux0[i]) {
                differ++;
                first = i;
            }
    if (v->check_count && pc == v->check_pcs[0]) {
        uint64_t n = v->c035_writes - v->c035_at_first;
        v->between[n < 31 ? n : 31]++;
        v->c035_at_first = v->c035_writes;
    }
    for (unsigned i = 0; i < v->check_count; i++)
        if (v->check_pcs[i] == pc) {
            v->checks[i]++;
            if (differ)
                v->mismatches[i]++;
        }
    if (differ) {
        v->mismatch_total++;
        vidhd_note(v->mismatch_notes, v->mismatch_total, pc,
                   (uint16_t)(0x2000 + first), 0, differ, a2vm_now(m));
    }
    return !differ;
}

static inline void vidhd_step_check(a2vm *m, uint16_t pc)
{
    if (m->vidhd.check_map &&
        (m->vidhd.check_map[pc >> 3] & (1u << (pc & 7))))
        a2vm_vidhd_check(m, pc);
}

/* README_SLOT2_GAMEPADS.md and hdl/apple/slot2_gamepad_card.sv: the
   four direct ports alias on A0/A1; SNES writes decode only A0. */
static uint8_t slot2_pad_read(const a2vm *m, unsigned address)
{
    if (m->slot2_mode == A2VM_SLOT2_FOUR_PLAY) {
        unsigned player = address & 3;
        unsigned b = (m->pad_present & (1u << player)) ?
                     m->pad_buttons[player] : 0;
        return (uint8_t)(0x20 | ((b >> 4) & 15) | ((b & A2VM_PAD_Y) << 3) |
                         ((b & A2VM_PAD_A) >> 2) | ((b & A2VM_PAD_B) << 7));
    }
    unsigned result = 0;
    for (unsigned player = 0; player < 2; player++) {
        unsigned bit = 1;
        if (m->snes_present & (1u << player)) {
            if (m->snes_bit < 12)
                bit = !(m->snes_buttons[player] & (1u << m->snes_bit));
            else if (m->snes_bit == 16)
                bit = 0;
        }
        result |= bit << (7 - player);
    }
    return (uint8_t)result;
}

static void slot2_pad_write(a2vm *m, unsigned address)
{
    if (m->slot2_mode != A2VM_SLOT2_SNES_MAX)
        return;
    if (!(address & 1)) {
        m->snes_buttons[0] = m->pad_buttons[0];
        m->snes_buttons[1] = m->pad_buttons[1];
        m->snes_present = m->pad_present & 3;
        m->snes_bit = 0;
    } else if (m->snes_bit < 16)
        m->snes_bit++;
}

static void paddle_trigger(a2vm *m)
{
    m->paddle_trigger = (int64_t)a2vm_bus_clock(m);
    for (unsigned i = 0; i < 4; i++)
        m->paddles[i] = 4 + 11 * m->paddle_values[i];
}

static uint8_t game_button(const a2vm *m, unsigned index)
{
    static const unsigned masks[3] = {A2VM_PAD_B, A2VM_PAD_A, A2VM_PAD_Y};
    uint8_t value = m->buttons[index];
    for (unsigned player = 0; player < 4; player++)
        if (m->pad_present & (1u << player)) {
            if (m->pad_buttons[player] & masks[index])
                value |= 0x80;
            break;
        }
    return value;
}

static uint8_t io_read(a2vm *m, uint16_t address)
{
    unsigned low = address & 0xff;
    m->io_accesses++;
    if (m->vidhd.slot && (low & 0xf0) == 0x30)
        vidhd_speaker(m, address);
    *m->clock += m->io_cycles;
    if (low == 0x00)
        return keyboard(m);
    if (low == 0x10) {
        uint8_t value = (uint8_t)((m->key_held ? 0x80 : 0) |
                                  (m->key_latch & 0x7f));
        m->key_latch &= 0x7f;
        return value;
    }
    if (low == 0x19)
        return a2vm_in_vbl(m) ? 0x00 : 0x80;
    if (low >= 0x13 && low <= 0x1f && low != 0x19)
        return (uint8_t)((m->sw[status_switch[low]] ? 0x80 : 0) |
                         (m->key_latch & 0x7f));
    if (low == 0x29)
        return m->newvideo;
    if (low >= 0x30 && low <= 0x3f) {
        m->speaker_toggles++;
        if (m->sound_event) m->sound_event(m, 3, 0, 0, m->speaker_toggles & 1);
    }
    else if (low >= 0x50 && low <= 0x57)
        video_switch(m, low);
    else if (low == 0x5e || low == 0x5f) m->dhires = !(low & 1);
    else if ((low >= 0x61 && low <= 0x63) || (low >= 0x69 && low <= 0x6b))
        return game_button(m, (low & 7) - 1);
    else if ((low >= 0x64 && low <= 0x67) || (low >= 0x6c && low <= 0x6f)) {
        int64_t elapsed = (int64_t)a2vm_bus_clock(m) - m->paddle_trigger;
        return elapsed < m->paddles[low & 3] ? 0x80 : 0x00;
    } else if (low >= 0x70 && low <= 0x7f)
        paddle_trigger(m);
    else if (low >= 0x80 && low <= 0x8f)
        lc_switch(m, low, 1);
    else if (m->phasor_slot > 0 && (int)(low >> 4) == 8 + m->phasor_slot) {
        if (!m->phasor_mb_only)
            phasor_mode_switch(m, low);
    } else if ((low & 0xf0) == 0xa0 && m->slot2_mode >= A2VM_SLOT2_FOUR_PLAY)
        return slot2_pad_read(m, low);
    else if (m->mouse_on && (int)(low >> 4) == 8 + m->mouse_slot)
        return mouse_read(&m->mouse, low & 0x0f);
    else if (m->mouse_rom && (int)(low >> 4) == 8 + m->mouse_slot)
        return rm_pia_read(&m->romouse, low & 0x0f);
    return 0x00;
}

static void io_write(a2vm *m, uint16_t address, uint8_t value)
{
    unsigned low = address & 0xff;
    m->io_accesses++;
    *m->clock += m->io_cycles;
    if (low >= 0x70 && low <= 0x7f)
        paddle_trigger(m);
    if (m->vidhd.slot && (low & 0xf0) == 0x30) {
        vidhd_speaker(m, address);
        if (low == 0x35) {
            m->vidhd.shadow = value;
            m->vidhd.c035_writes++;
        }
    }
    if (low <= 0x0f) {
        a2vm_switch s = (a2vm_switch)(low >> 1);
        m->sw[s] = low & 1;
        if (s == SW_STORE80 || s == SW_RAMRD || s == SW_RAMWRT ||
            s == SW_ALTZP)
            a2vm_remap(m);
    } else if (low == 0x10)
        m->key_latch &= 0x7f;
    else if (low == 0x29)
        m->newvideo = value;
    else if (low >= 0x30 && low <= 0x3f) {
        m->speaker_toggles++;
        if (m->sound_event) m->sound_event(m, 3, 0, 0, m->speaker_toggles & 1);
    }
    else if (low >= 0x50 && low <= 0x57)
        video_switch(m, low);
    else if (low == 0x5e || low == 0x5f) m->dhires = !(low & 1);
    else if (low == 0x71 || low == 0x73)
        a2vm_select_bank(m, value);
    else if (low == 0x69 && m->zpb.armed)
        zpb_enable(m, value);
    else if (low >= 0x80 && low <= 0x8f)
        lc_switch(m, low, 0);
    else if (m->phasor_slot > 0 && (int)(low >> 4) == 8 + m->phasor_slot) {
        if (!m->phasor_mb_only)
            phasor_mode_switch(m, low);
    } else if ((low & 0xf0) == 0xa0 && m->slot2_mode >= A2VM_SLOT2_FOUR_PLAY)
        slot2_pad_write(m, low);
    else if (m->mouse_on && (int)(low >> 4) == 8 + m->mouse_slot)
        mouse_write(&m->mouse, low & 0x0f, value);
    else if (m->mouse_rom && (int)(low >> 4) == 8 + m->mouse_slot)
        rm_pia_write(&m->romouse, low & 0x0f, value);
}

/* ---- the block device (--blockdev; README.md, "The block device") ---- */

/* Its slot ROM: a ProDOS block device's ID bytes, not a SmartPort's
   ($Cn07 $01), the driver's entry $Cn0A (an RTS there; a2vm does the call
   before it runs), $CnFF its offset. In slot 7 with --amem the memory
   API's ROM answers first: the same bytes but $C707 $00 (amem_init). */
static uint8_t blockdev_rom(unsigned offset)
{
    switch (offset) {
    case 0x01: return 0x20;
    case 0x03: return 0x00;
    case 0x05: return 0x03;
    case 0x07: return 0x01;
    case 0x0a: return 0x60;
    case 0xff: return 0x0a;
    default: return 0x00;
    }
}

enum {
    BD_STATUS = 0, BD_READ = 1, BD_WRITE = 2, BD_FORMAT = 3,
    BD_E_BADCALL = 0x01, BD_E_IO = 0x27, BD_E_NODEV = 0x28,
    BD_E_WPROT = 0x2b
};

/* The driver's call the CPU is about to run at $Cn0A (INTCXROM off):
   ProDOS's block-device protocol through the bus, then an RTS. */
static int blockdev_call(a2vm *m)
{
    a2vm_blockdev *b = &m->blockdev;
    unsigned n = (unsigned)b->slot;
    if (m->sw[SW_INTCXROM] || m->cpu.pc != (0xc00a | n << 8))
        return 0;
    uint8_t command = a2vm_read(m, 0x0042), unit = a2vm_read(m, 0x0043);
    uint16_t buffer = (uint16_t)(a2vm_read(m, 0x0044) |
                                 a2vm_read(m, 0x0045) << 8);
    uint16_t block = (uint16_t)(a2vm_read(m, 0x0046) |
                                a2vm_read(m, 0x0047) << 8);
    uint8_t error = 0, data[512];
    b->calls++;
    a2vm_write(m, 0x07f8, (uint8_t)(0xc0 + n));     /* MSLOT */
    if (((unit >> 4) & 7) != n || (unit & 0x80))
        error = BD_E_NODEV;                         /* one drive */
    else if (command == BD_STATUS) {
        b->statuses++;
        m->cpu.x = (uint8_t)b->blocks;
        m->cpu.y = (uint8_t)(b->blocks >> 8);
        if (b->read_only)
            error = BD_E_WPROT;
    } else if (command == BD_READ) {
        b->reads++;
        if (block >= b->blocks || fseek(b->file, (long)block * 512,
                                        SEEK_SET) ||
            fread(data, 1, 512, b->file) != 512)
            error = BD_E_IO;
        else
            for (unsigned i = 0; i < 512; i++)
                a2vm_write(m, (uint16_t)(buffer + i), data[i]);
    } else if (command == BD_WRITE) {
        b->writes++;
        if (b->read_only)
            error = BD_E_WPROT;
        else if (block >= b->blocks)
            error = BD_E_IO;
        else {
            for (unsigned i = 0; i < 512; i++)
                data[i] = a2vm_read(m, (uint16_t)(buffer + i));
            if (fseek(b->file, (long)block * 512, SEEK_SET) ||
                fwrite(data, 1, 512, b->file) != 512 || fflush(b->file))
                error = BD_E_IO;
            else if (b->written_count < A2VM_BLOCKDEV_NOTES)
                b->written[b->written_count++] = block;
        }
    } else if (command == BD_FORMAT)
        error = b->read_only ? BD_E_WPROT : 0;
    else
        error = BD_E_BADCALL;
    if (error)
        b->errors++;
    b->last_command = command;
    b->last_unit = unit;
    b->last_block = block;
    b->last_error = error;
    if (n == 7 && m->amem_on)
        m->amem.selected = 1;       /* (the firmware's C8 space stays) */
    /* the RTS */
    uint8_t lo = a2vm_read(m, (uint16_t)(0x0100 + (uint8_t)(m->cpu.s + 1)));
    uint8_t hi = a2vm_read(m, (uint16_t)(0x0100 + (uint8_t)(m->cpu.s + 2)));
    m->cpu.s = (uint8_t)(m->cpu.s + 2);
    m->cpu.pc = (uint16_t)((lo | hi << 8) + 1);
    m->cpu.a = error;
    if (error)
        m->cpu.p |= CPU65C02_C;
    else
        m->cpu.p &= (uint8_t)~CPU65C02_C;
    m->cpu.cycles += 6;
    return 1;
}

/* ---- the bus ---- */

static uint8_t slow_read(a2vm *m, uint16_t address)
{
    if (m->device_read) {
        int value = m->device_read(m, address);
        if (value >= 0) {
            *m->clock += m->io_cycles;
            if (address < 0xc100)
                m->io_accesses++;
            return (uint8_t)value;
        }
    }
    if (address < 0xc100)
        return io_read(m, address);
    /* $C100-$CFFF (the pages at and above $D000 are always mapped) */
    *m->clock += m->io_cycles;
    if (m->amem_on) {
        int value = amem_read(m, address);
        if (value >= 0)
            return (uint8_t)value;
    }
    int slot = (address >> 8) & 7;
    if (m->blockdev.slot && slot == m->blockdev.slot && address < 0xc800 &&
        !m->sw[SW_INTCXROM])
        return blockdev_rom(address & 0xff);
    if (m->vidhd.slot && slot == m->vidhd.slot && address < 0xc800 &&
        !m->sw[SW_INTCXROM] && (slot != 3 || m->sw[SW_SLOTC3ROM]))
        return vidhd_rom(address & 0xff);   /* (slot 3: the //e's own
                                               ROM unless SLOTC3ROM) */
    if (!m->sw[SW_INTCXROM] && m->phasor_slot > 0 && slot == m->phasor_slot)
        return phasor_read(m, address);
    if (m->mouse_on && !m->sw[SW_INTCXROM] && address < 0xc800 &&
        slot == m->mouse_slot)
        return mouse_rom[address & 0xff];
    if (m->mouse_plain && !m->sw[SW_INTCXROM] && address < 0xc800 &&
        slot == m->mouse_slot)
        return plain_mouse_rom(address & 0xff);
    if (m->mouse_apple && !m->sw[SW_INTCXROM] && address < 0xc800 &&
        slot == m->mouse_slot)
        return apple_mouse_rom(address & 0xff);
    if (m->mouse_rom && !m->sw[SW_INTCXROM] && address < 0xc800 &&
        slot == m->mouse_slot)
        return m->romouse.rom[rm_bank(&m->romouse) << 8 | (address & 0xff)];
    return m->rom[address - 0xc000];
}

static void slow_write(a2vm *m, uint16_t address, uint8_t value)
{
    if (address >= 0xd000)
        return;                     /* the language card, write-protected */
    if (m->device_write && m->device_write(m, address, value)) {
        *m->clock += m->io_cycles;
        if (address < 0xc100)
            m->io_accesses++;
        return;
    }
    if (address < 0xc100) {
        io_write(m, address, value);
        return;
    }
    *m->clock += m->io_cycles;
    if (m->amem_on && amem_write(m, address, value))
        return;
    if (m->phasor_slot > 0 && ((address >> 8) & 7) == m->phasor_slot)
        phasor_write(m, address, value);
}

/* The operand fetch of JSR $BF00 in the compatibility core
   (a2sim.Machine._mli_fetch and FakeProDOS.intercept): the return address
   is pushed already. -1 lets the read go on (not a call, or QUIT). */
static int mli_fetch(a2vm *m, uint16_t address)
{
    const uint8_t *main = m->main;
    if (address < 0x0201 || address > 0xfffa || main[address - 1] != 0x20 ||
        main[address] != 0x00 || main[address + 1] != 0xbf)
        return -1;
    uint16_t jsr = (uint16_t)(address - 1);
    uint8_t number = main[jsr + 3];
    uint16_t parms = (uint16_t)(main[jsr + 4] | main[jsr + 5] << 8);
    int error = prodos_call(m->prodos, m->main, number, parms);
    if (error == PRODOS_QUIT)
        return -1;
    if (error == PRODOS_FAULT) {
        char text[256];
        snprintf(text, sizeof text, "prodos-fault: %s", m->prodos->fault);
        halt(m, text);
        error = 0;
    }
    m->r.a = (uint8_t)error;
    if (error)
        m->r.p |= CPU65C02_C;
    else
        m->r.p &= (uint8_t)~CPU65C02_C;
    m->r.sp = (uint8_t)(m->r.sp + 2);
    uint16_t target = (uint16_t)(jsr + 6);
    m->mli_hi_pending = 1;
    m->mli_hi_address = (uint16_t)(address + 1);
    m->mli_hi_value = (uint8_t)(target >> 8);
    return target & 0xff;
}

/* --irq-bounds: an access inside an interrupt handler outside every
   allowed range halts the run. */
static void irq_bounds_check(a2vm *m, uint16_t address, int write)
{
    for (unsigned i = 0; i < m->irq_bound_count; i++)
        if (address >= m->irq_bounds[i][0] && address <= m->irq_bounds[i][1])
            return;
    char text[96];
    snprintf(text, sizeof text, "irq-bounds: %s $%04X in an interrupt, "
             "pc $%04X", write ? "write" : "read", address, a2vm_pc(m));
    halt(m, text);
}

/* --write-log: one line (README.md, "The write log"). It is the
   machine's write_hook, which sees every CPU write, with the storage byte
   it reaches, before the write. */
static void log_write(a2vm *m, uint16_t address, uint8_t *storage,
                      uint8_t value)
{
    if (!a2vm_in_ranges(m, m->write_ranges, m->write_range_count, address,
                        storage))
        return;
    if (m->write_log_limit && m->write_logged >= m->write_log_limit) {
        char text[96];
        snprintf(text, sizeof text, "write-log: %" PRIu64 " lines, the "
                 "--write-log-limit", m->write_log_limit);
        halt(m, text);
        return;
    }
    static const char *const names[] = { "main", "aux", "lc", "lc1" };
    unsigned kind, bank, offset;
    uint64_t cycles = m->core == A2VM_CORE_PY65 ? m->py65_cycles
                                                : m->cpu.cycles;
    fprintf(m->write_log, "w %" PRIu64 " %" PRIu64 " %04X %04X", a2vm_now(m),
            cycles, m->instruction_pc, address);
    if (storage && a2vm_locate(m, storage, &kind, &bank, &offset))
        fprintf(m->write_log, " %s %u %04X %02X %02X\n", names[kind], bank,
                offset, *storage, value);
    else
        fprintf(m->write_log, " io - - - %02X\n", value);
    m->write_logged++;
}

void a2vm_start_write_log(a2vm *m, FILE *log)
{
    m->write_log = log;
    m->write_hook = log_write;
}

static inline uint8_t bus_read(a2vm *m, uint16_t address, int kind)
{
    if (m->irq_guard)
        irq_bounds_check(m, address, 0);
    if (m->cost)
        a2vm_cost_read(m, address, m->rpage[address >> 8], kind);
    if (m->prodos && m->core == A2VM_CORE_PY65) {
        if (address == m->r.pc) {
            int value = mli_fetch(m, address);
            if (value >= 0)
                return (uint8_t)value;
        } else if (m->mli_hi_pending && address == m->mli_hi_address) {
            m->mli_hi_pending = 0;
            return m->mli_hi_value;
        }
    }
    const uint8_t *page = m->rpage[address >> 8];
    if (page)
        return page[address & 0xff];
    uint8_t value = slow_read(m, address);
    if (m->cost)
        a2vm_cost_after_io(m, address, 0, value);
    return value;
}

static inline void bus_write(a2vm *m, uint16_t address, uint8_t value,
                             int kind)
{
    if (m->irq_guard)
        irq_bounds_check(m, address, 1);
    uint8_t *page = m->wpage[address >> 8];
    if (m->write_hook)
        m->write_hook(m, address, page ? page + (address & 0xff) : NULL,
                      value);
    if (m->cost)
        a2vm_cost_write(m, address, value, page, kind);
    if (page) {
        if (m->vidhd.slot && m->vflag[address >> 8])
            vidhd_write(m, address, value);
        page[address & 0xff] = value;
        uint8_t flag = m->wflag[address >> 8];
        if (flag) {
            m->video_writes++;
            if (flag & 2)
                m->shr_writes++;
        }
        return;
    }
    slow_write(m, address, value);
    if (m->cost)
        a2vm_cost_after_io(m, address, 1, value);
}

/* The bus with the zero-page pair armed (the machine without it keeps the
   two functions above, and their speed): a data_ea cycle to $0200-$BFFF
   goes to the register's bank when it is not 0; a write whose byte is
   main zero page may load a register. The compatibility core never runs
   on it (a2vm_zpbank_arm). */
static inline uint8_t bus_read_zp(a2vm *m, uint16_t address, int kind)
{
    if ((kind & CPU65C02_EA) && m->zpb.rd && zpb_redirects(address)) {
        const uint8_t *page = zpb_page(m, m->zpb.rd, address);
        m->zpb.reads++;
        if (m->irq_guard)
            irq_bounds_check(m, address, 0);
        if (m->cost)
            a2vm_cost_read(m, address, page, kind);
        return page[address & 0xff];
    }
    return bus_read(m, address, kind);
}

static inline void bus_write_zp(a2vm *m, uint16_t address, uint8_t value,
                                int kind)
{
    if ((kind & CPU65C02_EA) && m->zpb.wr && zpb_redirects(address)) {
        uint8_t *page = zpb_page(m, m->zpb.wr, address);
        m->zpb.writes++;
        if (m->irq_guard)
            irq_bounds_check(m, address, 1);
        if (m->write_hook)
            m->write_hook(m, address, page + (address & 0xff), value);
        if (m->cost)
            a2vm_cost_write(m, address, value, page, kind);
        page[address & 0xff] = value;   /* PSRAM: never a video write */
        return;
    }
    bus_write(m, address, value, kind);
    if (address < 0x100 && m->zpb.address && m->wpage[0] == m->main)
        zpb_watch(m, address, value);
}

uint8_t a2vm_read(a2vm *m, uint16_t address)
{
    return m->zpb.armed ? bus_read_zp(m, address, CPU65C02_DATA)
                        : bus_read(m, address, CPU65C02_DATA);
}

void a2vm_write(a2vm *m, uint16_t address, uint8_t value)
{
    if (m->zpb.armed)
        bus_write_zp(m, address, value, CPU65C02_DATA);
    else
        bus_write(m, address, value, CPU65C02_DATA);
}

uint8_t a2vm_read_ea(a2vm *m, uint16_t address)
{
    return bus_read_zp(m, address, CPU65C02_DATA_EA);
}

void a2vm_write_ea(a2vm *m, uint16_t address, uint8_t value)
{
    bus_write_zp(m, address, value, CPU65C02_DATA_EA);
}

/* ---- the cores ---- */

#define P65_M a2vm
#define P65_RD(address) bus_read(m, (address), CPU65C02_DATA)
#define P65_WR(address, value) \
    bus_write(m, (address), (uint8_t)(value), CPU65C02_DATA)
#include "py65core.h"
#undef P65_M
#undef P65_RD
#undef P65_WR

#define C02_PREFIX w65_
#define C02_LINKAGE static inline
#define C02_READ(cpu, address, kind) \
    bus_read((a2vm *)(cpu)->context, (address), (kind))
#define C02_WRITE(cpu, address, value, kind) \
    bus_write((a2vm *)(cpu)->context, (address), (value), (kind))
#include "cpu65c02_core.h"
#undef C02_PREFIX
#undef C02_LINKAGE
#undef C02_READ
#undef C02_WRITE

/* the exact core again, on the bus of the armed pair */
#define C02_PREFIX w65zp_
#define C02_LINKAGE static inline
#define C02_READ(cpu, address, kind) \
    bus_read_zp((a2vm *)(cpu)->context, (address), (kind))
#define C02_WRITE(cpu, address, value, kind) \
    bus_write_zp((a2vm *)(cpu)->context, (address), (value), (kind))
#include "cpu65c02_core.h"
#undef C02_PREFIX
#undef C02_LINKAGE
#undef C02_READ
#undef C02_WRITE

static uint8_t native_read(void *context, uint16_t address,
                           cpu65c02_kind kind)
{
    a2vm *m = context;
    return m->zpb.armed ? bus_read_zp(m, address, kind)
                        : bus_read(m, address, kind);
}

static void native_write(void *context, uint16_t address, uint8_t value,
                         cpu65c02_kind kind)
{
    a2vm *m = context;
    if (m->zpb.armed)
        bus_write_zp(m, address, value, kind);
    else
        bus_write(m, address, value, kind);
}

uint16_t a2vm_pc(const a2vm *m)
{
    return m->core == A2VM_CORE_PY65 ? m->r.pc : m->cpu.pc;
}

uint8_t a2vm_register(const a2vm *m, char name)
{
    int py = m->core == A2VM_CORE_PY65;
    switch (name) {
    case 'a': return py ? m->r.a : m->cpu.a;
    case 'x': return py ? m->r.x : m->cpu.x;
    case 'y': return py ? m->r.y : m->cpu.y;
    case 's': return py ? m->r.sp : m->cpu.s;
    case 'p': return py ? m->r.p : m->cpu.p;
    }
    return 0;
}

void a2vm_set_register(a2vm *m, char name, unsigned value)
{
    int py = m->core == A2VM_CORE_PY65;
    uint8_t v = (uint8_t)value;
    switch (name) {
    case 'c':                           /* the program counter */
        if (py)
            m->r.pc = (uint16_t)value;
        else
            m->cpu.pc = (uint16_t)value;
        break;
    case 'a': if (py) m->r.a = v; else m->cpu.a = v; break;
    case 'x': if (py) m->r.x = v; else m->cpu.x = v; break;
    case 'y': if (py) m->r.y = v; else m->cpu.y = v; break;
    case 's': if (py) m->r.sp = v; else m->cpu.s = v; break;
    case 'p':
        if (py)
            m->r.p = v;
        else {
            m->cpu.p = v;
            cpu65c02_normalise(&m->cpu);
        }
        break;
    }
}

/* ---- a2sim.Machine.step ---- */

static void vbl_event(a2vm *m)
{
    m->next_vbl += m->frame_cycles;
    if (m->mouse_on || m->mouse_apple)
        mouse_vblank(&m->mouse);
    if (m->mouse_rom && !m->mouse_no_vbl)
        rm_vbl(&m->romouse);
}

static void skip_idle(a2vm *m, uint16_t pc)
{
    for (unsigned i = 0; i < m->idle_count; i++) {
        const a2vm_idle *idle = &m->idle[i];
        if (idle->pc != pc)
            continue;
        if (idle->need_main_zp && m->sw[SW_ALTZP])
            return;
        if (idle->compare) {
            const uint8_t *a = a2vm_storage(m, idle->store_a, 0, idle->word_a);
            const uint8_t *b = a2vm_storage(m, idle->store_b, 0, idle->word_b);
            const uint8_t *a1 = a2vm_storage(m, idle->store_a, 0,
                                             (uint16_t)(idle->word_a + 1));
            const uint8_t *b1 = a2vm_storage(m, idle->store_b, 0,
                                             (uint16_t)(idle->word_b + 1));
            if (!a || !b || !a1 || !b1 || *a != *b || *a1 != *b1)
                return;
        }
        for (unsigned j = 0; j < idle->byte_count; j++)
            if (m->main[idle->byte_addr[j]] != idle->byte_value[j])
                return;
        if (idle->need_vbl && !a2vm_in_vbl(m))
            return;
        uint64_t now = a2vm_now(m), target;
        if (idle->kind == A2VM_IDLE_VBL)
            target = m->next_vbl;
        else
            target = (now / m->frame_cycles + 1) * m->frame_cycles;
        /* a VIA timer's interrupt comes first: the skip ends there */
        if (m->via_timers &&
            ((m->phasor.t1[0].ier | m->phasor.t1[1].ier) & 0x40) &&
            m->phasor.t1_clock < target)
            target = m->phasor.t1_clock;
        if (target > now) {
            m->idle_cycles += target - now;
            if (m->cost)
                a2vm_cost_skip(m, target - now);
            if (m->clock_advance) m->clock_advance(m, target);
            else *m->clock = target;
            if (target >= m->next_vbl)
                vbl_event(m);
        }
        return;
    }
}

/* The MLI trap of the exact core: at the step boundary, a JSR $BF00
   (with the bytes of main memory, as a2sim checks them) is serviced
   in the 6 cycles of the JSR. */
static int native_mli(a2vm *m)
{
    uint16_t pc = m->cpu.pc;
    const uint8_t *main = m->main;
    if (pc < 0x0200 || pc > 0xfff9 || main[pc] != 0x20 ||
        main[pc + 1] != 0x00 || main[pc + 2] != 0xbf)
        return 0;
    int error = prodos_call(m->prodos, m->main, main[pc + 3],
                            (uint16_t)(main[pc + 4] | main[pc + 5] << 8));
    if (error == PRODOS_QUIT)
        return 0;
    if (error == PRODOS_FAULT) {
        char text[256];
        snprintf(text, sizeof text, "prodos-fault: %s", m->prodos->fault);
        halt(m, text);
        error = 0;
    }
    m->cpu.a = (uint8_t)error;
    if (error)
        m->cpu.p |= CPU65C02_C;
    else
        m->cpu.p &= (uint8_t)~CPU65C02_C;
    m->cpu.pc = (uint16_t)(pc + 6);
    m->cpu.cycles += 6;
    return 1;
}

/* --mouse-apple: the AppleMouse II's firmware call the CPU is about to
   run at an entry of the table, serviced as the firmware does it
   (README.md, "The AppleMouse II"): X = $Cn and Y = $n0 by the
   convention, the slot's screen holes of main $0478-$07FF (through the
   bus, so the //e's switches and the interrupt bounds apply) and, for
   SERVEMOUSE, zero page $06, which the real firmware borrows for an RTS
   and gives back; then an RTS, C clear for success (SETMOUSE's mode over
   $0F, and SERVEMOUSE with no interrupt of the mouse pending, set C). */
static int apple_mouse_call(a2vm *m)
{
    uint16_t pc = m->cpu.pc;
    unsigned n = (unsigned)m->mouse_slot, entry;
    if (m->sw[SW_INTCXROM] || (pc >> 8) != 0xc0 + n)
        return 0;
    for (entry = 0; entry < 8; entry++)
        if ((pc & 0xff) == apple_entries[entry])
            break;
    if (entry == 8)
        return 0;
    a2vm_mouse *c = &m->mouse;
    uint16_t xl = (uint16_t)(0x0478 + n), yl = (uint16_t)(0x04f8 + n),
             xh = (uint16_t)(0x0578 + n), yh = (uint16_t)(0x05f8 + n),
             bank = (uint16_t)(0x0678 + n), cmd = (uint16_t)(0x06f8 + n),
             status = (uint16_t)(0x0778 + n), mode = (uint16_t)(0x07f8 + n);
    int fail = 0;
    m->mouse_calls[entry]++;
    switch (entry) {
    case 0:                                         /* SETMOUSE */
        if (m->cpu.a >= 0x10) {
            fail = 1;
            break;
        }
        c->mode = m->cpu.a;
        a2vm_write(m, mode, m->cpu.a);
        a2vm_write(m, cmd, m->cpu.a);
        a2vm_write(m, bank, 0x06);
        break;
    case 1: {                                       /* SERVEMOUSE */
        uint8_t keep = a2vm_read(m, 0x0006);
        a2vm_write(m, 0x0006, 0x60);
        a2vm_write(m, 0x0006, keep);
        a2vm_write(m, cmd, 0x20);
        a2vm_write(m, bank, 0x06);
        uint8_t bits = (uint8_t)((c->vbl_pending << 3) |
                                 (c->button_pending << 2) |
                                 (c->move_irq << 1));
        a2vm_write(m, status,
                   (uint8_t)((a2vm_read(m, status) & 0xf1) | bits));
        c->vbl_pending = c->button_pending = c->move_irq = c->irq = 0;
        fail = bits == 0;
        break;
    }
    case 2: {                                       /* READMOUSE */
        a2vm_write(m, cmd, 0x00);
        a2vm_write(m, bank, 0x00);
        a2vm_write(m, xl, (uint8_t)c->x);
        a2vm_write(m, xh, (uint8_t)(c->x >> 8));
        a2vm_write(m, yl, (uint8_t)c->y);
        a2vm_write(m, yh, (uint8_t)(c->y >> 8));
        a2vm_write(m, status, (uint8_t)(((c->buttons & 1) << 7) |
                                        ((c->prev_buttons & 1) << 6) |
                                        (c->moved << 5)));
        c->prev_buttons = c->buttons;
        c->moved = 0;
        break;
    }
    case 3:                                         /* CLEARMOUSE */
        c->x = clamp16(0, c->clamp[0][0], c->clamp[0][1]);
        c->y = clamp16(0, c->clamp[1][0], c->clamp[1][1]);
        a2vm_write(m, cmd, 0x30);
        a2vm_write(m, xl, 0);
        a2vm_write(m, xh, 0);
        a2vm_write(m, yl, 0);
        a2vm_write(m, yh, 0);
        break;
    case 4:                                         /* POSMOUSE */
        a2vm_write(m, cmd, 0x40);
        a2vm_write(m, bank, 0x0e);
        c->x = clamp16(a2vm_read(m, xl) | a2vm_read(m, xh) << 8,
                       c->clamp[0][0], c->clamp[0][1]);
        c->y = clamp16(a2vm_read(m, yl) | a2vm_read(m, yh) << 8,
                       c->clamp[1][0], c->clamp[1][1]);
        break;
    case 5: {                                       /* CLAMPMOUSE */
        int32_t *window = c->clamp[m->cpu.a & 1];
        window[0] = a2vm_read(m, 0x0478) | a2vm_read(m, 0x0578) << 8;
        window[1] = a2vm_read(m, 0x04f8) | a2vm_read(m, 0x05f8) << 8;
        a2vm_write(m, cmd, (uint8_t)(0x60 | (m->cpu.a & 1)));
        a2vm_write(m, bank, 0x0e);
        mouse_reclamp(c);
        break;
    }
    case 6:                                         /* HOMEMOUSE */
        c->x = c->clamp[0][0];
        c->y = c->clamp[1][0];
        a2vm_write(m, cmd, 0x70);
        break;
    default:                                        /* INITMOUSE */
        c->clamp[0][0] = c->clamp[1][0] = 0;
        c->clamp[0][1] = c->clamp[1][1] = 1023;
        c->x = c->y = 0;
        c->mode = 0;
        c->moved = c->move_irq = c->button_pending = 0;
        c->vbl_pending = c->irq = 0;
        c->prev_buttons = c->buttons;
        a2vm_write(m, mode, 0x00);
        a2vm_write(m, status, 0x00);
        a2vm_write(m, bank, 0x04);
        break;
    }
    /* the RTS */
    uint8_t lo = a2vm_read(m, (uint16_t)(0x0100 + (uint8_t)(m->cpu.s + 1)));
    uint8_t hi = a2vm_read(m, (uint16_t)(0x0100 + (uint8_t)(m->cpu.s + 2)));
    m->cpu.s = (uint8_t)(m->cpu.s + 2);
    m->cpu.pc = (uint16_t)((lo | hi << 8) + 1);
    if (fail)
        m->cpu.p |= CPU65C02_C;
    else
        m->cpu.p &= (uint8_t)~CPU65C02_C;
    m->cpu.cycles += 6;
    return 1;
}

/* --ay-log: an interrupt taken, or an RTI about to run. */
static void ay_log_irq(a2vm *m)
{
    fprintf(m->ay_log, "irq %" PRIu64, m->irqs);
    ay_log_time(m);
    fputc('\n', m->ay_log);
}

static int at_rti(const a2vm *m, uint16_t pc)
{
    const uint8_t *page = m->rpage[pc >> 8];
    return page && page[pc & 0xff] == 0x40;
}

static void ay_log_rti(a2vm *m)
{
    fputs("rti", m->ay_log);
    ay_log_time(m);
    fputc('\n', m->ay_log);
}

void a2vm_service_events(a2vm *m)
{
    if (m->service_hook) m->service_hook(m);
    /* Drain overdue frame events as well: two callers at this same
       instruction boundary must not deliver different pending events. */
    while (a2vm_now(m) >= m->next_vbl)
        vbl_event(m);
    if (m->via_timers && a2vm_now(m) >= m->phasor.t1_clock)
        a2vm_via_timers_update(m);
    if (m->core == A2VM_CORE_W65C02S) {
        int irq = ((m->mouse_on || m->mouse_apple) && m->mouse.irq) ||
                  (m->mouse_rom && m->romouse.irq) || via_irq(m);
        cpu65c02_set_irq(&m->cpu, 1, irq);
    }
}

void a2vm_step(a2vm *m)
{
    a2vm_service_events(m);
    m->instructions++;
    if (m->core == A2VM_CORE_PY65) {
        m->instruction_pc = m->r.pc;
        if ((((m->mouse_on || m->mouse_apple) && m->mouse.irq) ||
             (m->mouse_rom && m->romouse.irq) || via_irq(m)) &&
            !(m->r.p & P65_I)) {
            m->r.waiting = 0;
            p65_irq(m);
            m->r.p &= (uint8_t)~P65_D;
            m->irqs++;
            if (m->ay_log)
                ay_log_irq(m);
            m->irq_guard = m->irq_bound_count != 0;
        }
        uint16_t pc = m->r.pc;
        m->instruction_pc = pc;
        if (m->mouse_apple && (pc >> 8) == 0xc0 + m->mouse_slot)
            halt(m, "mouse-apple: the AppleMouse II's firmware needs "
                 "--core w65c02s");
        if (m->blockdev.slot && pc == (0xc00a | m->blockdev.slot << 8))
            halt(m, "blockdev: the block device's driver needs "
                 "--core w65c02s");
        if (m->idle_map[pc >> 3] & (1u << (pc & 7)))
            skip_idle(m, pc);
        if (m->pc_hook && !m->r.waiting &&
            (m->pc_hook_map[pc >> 3] & (1u << (pc & 7))))
            m->pc_hook(m, pc);
        if (!m->r.waiting)
            vidhd_step_check(m, pc);
        if (m->cost && m->cost->timed && m->r.waiting)
            m->cost->t += m->cost->p.turbo_hit;     /* WAI takes time */
        int rti = (m->ay_log || m->irq_bound_count) && !m->r.waiting &&
                  at_rti(m, m->r.pc);
        p65_step(m);
        if (rti) {
            if (m->ay_log)
                ay_log_rti(m);
            m->irq_guard = 0;
        }
        return;
    }
    int taken = m->cpu.irq_sources && !(m->cpu.p & CPU65C02_I) &&
                m->cpu.state != CPU65C02_STOPPED;
    if (taken) {
        m->irqs++;
        if (m->ay_log)
            ay_log_irq(m);
    }
    uint16_t pc = m->cpu.pc;
    m->instruction_pc = pc;     /* an interrupt entry's too */
    if (!taken && (m->idle_map[pc >> 3] & (1u << (pc & 7))))
        skip_idle(m, pc);
    if (m->pc_hook && !taken && m->cpu.state == CPU65C02_RUNNING &&
        (m->pc_hook_map[pc >> 3] & (1u << (pc & 7))))
        m->pc_hook(m, pc);
    if (!taken && m->cpu.state == CPU65C02_RUNNING)
        vidhd_step_check(m, pc);
    if (m->prodos && m->cpu.state == CPU65C02_RUNNING &&
        !taken && native_mli(m))
        return;
    if (m->mouse_apple && m->cpu.state == CPU65C02_RUNNING &&
        !taken && apple_mouse_call(m))
        return;
    if (m->blockdev.slot && m->cpu.state == CPU65C02_RUNNING &&
        !taken && blockdev_call(m))
        return;
    int rti = (m->ay_log || m->irq_bound_count) && !taken &&
              m->cpu.state == CPU65C02_RUNNING && at_rti(m, m->cpu.pc);
    if (m->zpb.armed)
        w65zp_step(&m->cpu);
    else
        w65_step(&m->cpu);
    /* the bounds hold from the handler's first instruction: the entry's
       reads of the interrupted PC are the main program's */
    if (taken && m->irq_bound_count)
        m->irq_guard = 1;
    if (rti) {
        if (m->ay_log)
            ay_log_rti(m);
        m->irq_guard = 0;
    }
}

int a2vm_add_idle(a2vm *m, const a2vm_idle *idle)
{
    for (unsigned i = 0; i < m->idle_count; i++)
        if (m->idle[i].pc == idle->pc) {
            m->idle[i] = *idle;         /* a dict: the last one wins */
            return 1;
        }
    if (m->idle_count == A2VM_MAX_IDLE)
        return 0;
    m->idle[m->idle_count++] = *idle;
    m->idle_map[idle->pc >> 3] |= (uint8_t)(1u << (idle->pc & 7));
    return 1;
}

/* ---- input (a2sim.Machine.press, hold, release, mouse_*) ---- */

int a2vm_set_slot2(a2vm *m, int mode)
{
    if (!m || mode < A2VM_SLOT2_OFF || mode > A2VM_SLOT2_SNES_MAX)
        return 0;
    if (mode != A2VM_SLOT2_OFF &&
        (m->phasor_slot == 2 || m->vidhd.slot == 2 || m->blockdev.slot == 2))
        return 0;
    if (mode == m->slot2_mode)
        return 1;
    if (m->mouse_slot == 2) {
        unsigned kind = (m->mouse_on ? 1u : 0u) |
                        (m->mouse_plain ? 2u : 0u) |
                        (m->mouse_apple ? 4u : 0u) |
                        (m->mouse_rom ? 8u : 0u);
        if (kind)
            m->slot2_mouse_kind = (uint8_t)kind;
        m->mouse_on = m->mouse_plain = m->mouse_apple = m->mouse_rom = 0;
        mouse_init(&m->mouse);
        rm_reset(&m->romouse);
    }
    m->slot2_mode = mode;
    m->snes_bit = 16;
    m->snes_present = 0;
    m->snes_buttons[0] = m->snes_buttons[1] = 0;
    if (mode == A2VM_SLOT2_MOUSE) {
        unsigned kind = m->slot2_mouse_kind ? m->slot2_mouse_kind : 1;
        m->mouse_slot = 2;
        m->mouse_on = (kind & 1) != 0;
        m->mouse_plain = (kind & 2) != 0;
        m->mouse_apple = (kind & 4) != 0;
        m->mouse_rom = (kind & 8) != 0;
        mouse_init(&m->mouse);
        rm_reset(&m->romouse);
    }
    /* The CPU's shared device IRQ bit must not retain a removed mouse
       assertion. Preserve the VIA and a mouse in another slot. */
    int irq = ((m->mouse_on || m->mouse_apple) && m->mouse.irq) ||
              (m->mouse_rom && m->romouse.irq) || via_irq(m);
    cpu65c02_set_irq(&m->cpu, 1, irq);
    return 1;
}

int a2vm_set_pad(a2vm *m, unsigned index, int buttons)
{
    if (!m || index >= 4 || buttons < -1 || buttons > 0xfff)
        return 0;
    if (buttons < 0) {
        m->pad_buttons[index] = 0;
        m->pad_present &= (uint8_t)~(1u << index);
    } else {
        m->pad_buttons[index] = (uint16_t)buttons;
        m->pad_present |= (uint8_t)(1u << index);
    }
    return 1;
}

int a2vm_set_paddle(a2vm *m, unsigned index, unsigned value)
{
    if (!m || index >= 4 || value > 255)
        return 0;
    m->paddle_values[index] = (uint8_t)value;
    return 1;
}

void a2vm_press(a2vm *m, uint8_t key, uint64_t at_cycle)
{
    if (m->key_count == A2VM_MAX_KEYS) {
        halt(m, "too many queued keys");
        return;
    }
    m->keys[m->key_count].when = at_cycle;
    m->keys[m->key_count].key = key & 0x7f;
    m->key_count++;
}

void a2vm_hold(a2vm *m, uint8_t key)
{
    m->key_latch = (uint8_t)((key & 0x7f) | 0x80);
    m->key_held = 1;
}

void a2vm_release(a2vm *m)
{
    m->key_held = 0;
}

void a2vm_mouse_move(a2vm *m, int64_t x, int64_t y)
{
    if (m->mouse_rom) {
        rm_delta(&m->romouse, x - m->romouse.x, y - m->romouse.y);
        return;
    }
    mouse_commit(&m->mouse, x, y, m->mouse.ps_buttons, 1);
}

void a2vm_mouse_delta(a2vm *m, int64_t dx, int64_t dy)
{
    if (m->mouse_rom) {
        rm_delta(&m->romouse, dx, dy);
        return;
    }
    a2vm_mouse *c = &m->mouse;
    int64_t x = clamp16(c->x + dx, c->clamp[0][0], c->clamp[0][1]);
    int64_t y = clamp16(c->y + dy, c->clamp[1][0], c->clamp[1][1]);
    mouse_commit(c, x, y, c->ps_buttons, 1);
}

void a2vm_mouse_buttons(a2vm *m, int left, int right)
{
    if (m->mouse_rom) {
        if (m->romouse.button0 != (left != 0))
            rm_button(&m->romouse, 0, left);
        if (m->romouse.button1 != (right != 0))
            rm_button(&m->romouse, 1, right);
        return;
    }
    mouse_commit(&m->mouse, m->mouse.x, m->mouse.y,
                 (left ? 1u : 0u) | (right ? 2u : 0u), 1);
}

/* ---- the CPU's RESET ---- */

void a2vm_cpu_reset(a2vm *m)
{
    a2vm_zpbank_reset(m);
    m->instruction_pc = a2vm_pc(m);
    if (m->core == A2VM_CORE_W65C02S)
        w65_reset(&m->cpu);
}

/* ---- ranges (the write log, range snapshots) ---- */

int a2vm_locate(const a2vm *m, const uint8_t *p, unsigned *kind,
                unsigned *bank, unsigned *offset)
{
    *bank = 0;
    if (p >= m->main && p < m->main + sizeof m->main) {
        *kind = A2VM_RANGE_MAIN;
        *offset = (unsigned)(p - m->main);
    } else if (p >= m->lc && p < m->lc + sizeof m->lc) {
        *kind = A2VM_RANGE_LC;
        *offset = 0xc000 + (unsigned)(p - m->lc);
    } else if (p >= m->lc1 && p < m->lc1 + sizeof m->lc1) {
        *kind = A2VM_RANGE_LC1;
        *offset = 0xd000 + (unsigned)(p - m->lc1);
    } else if (p >= m->aux_banks &&
               p < m->aux_banks + (size_t)A2VM_MAX_BANKS * A2VM_BANK_SIZE) {
        size_t o = (size_t)(p - m->aux_banks);
        *kind = A2VM_RANGE_AUX;
        *bank = (unsigned)(o / A2VM_BANK_SIZE);
        *offset = (unsigned)(o % A2VM_BANK_SIZE);
    } else
        return 0;
    return 1;
}

int a2vm_in_ranges(const a2vm *m, const a2vm_range *ranges, unsigned count,
                   uint16_t address, const uint8_t *p)
{
    unsigned kind = A2VM_RANGE_CPU, bank = 0, offset = 0;
    int located = p && a2vm_locate(m, p, &kind, &bank, &offset);
    for (unsigned i = 0; i < count; i++) {
        const a2vm_range *r = &ranges[i];
        if (r->kind == A2VM_RANGE_CPU) {
            if (address >= r->low && address <= r->high)
                return 1;
        } else if (located && r->kind == kind && offset >= r->low &&
                   offset <= r->high &&
                   (kind != A2VM_RANGE_AUX ||
                    (bank >= r->bank_low && bank <= r->bank_high)))
            return 1;
    }
    return 0;
}

static int parse_hex16(const char *text, uint16_t *value)
{
    char *end;
    unsigned long v = strtoul(text, &end, 16);
    if (end == text || *end || v > 0xffff)
        return 0;
    *value = (uint16_t)v;
    return 1;
}

int a2vm_parse_ranges(const char *text, a2vm_range *ranges,
                      unsigned *count, int allow_cpu, char *error,
                      size_t error_size)
{
    char buffer[4096];
    if (strlen(text) >= sizeof buffer) {
        snprintf(error, error_size, "the ranges are too long");
        return 0;
    }
    strcpy(buffer, text);
    *count = 0;
    for (char *item = strtok(buffer, ","); item; item = strtok(NULL, ",")) {
        a2vm_range r;
        memset(&r, 0, sizeof r);
        char *colon = strchr(item, ':');
        if (colon)
            *colon = 0;
        uint16_t lowest = 0, highest = 0xffff;
        if (!strcmp(item, "main"))
            r.kind = A2VM_RANGE_MAIN;
        else if (!strcmp(item, "lc")) {
            r.kind = A2VM_RANGE_LC;
            lowest = 0xc000;
        } else if (!strcmp(item, "lc1")) {
            r.kind = A2VM_RANGE_LC1;
            lowest = 0xd000;
            highest = 0xdfff;
        } else if (!strcmp(item, "cpu") && allow_cpu)
            r.kind = A2VM_RANGE_CPU;
        else if (!strncmp(item, "aux", 3) && item[3]) {
            char *end, *dash;
            unsigned long first = strtoul(item + 3, &end, 10), last = first;
            dash = end;
            if (*dash == '-')
                last = strtoul(dash + 1, &end, 10);
            if (end == item + 3 || *end || first > last ||
                last >= A2VM_MAX_BANKS) {
                snprintf(error, error_size, "%s: aux banks are auxN or "
                         "auxN-M, 0-%d", item, A2VM_MAX_BANKS - 1);
                return 0;
            }
            r.kind = A2VM_RANGE_AUX;
            r.bank_low = (uint8_t)first;
            r.bank_high = (uint8_t)last;
        } else {
            snprintf(error, error_size, "%s: a range is main, auxN, auxN-M, "
                     "lc, lc1%s, then :LO-HI", item, allow_cpu ? ", cpu" : "");
            return 0;
        }
        r.low = lowest;
        r.high = highest;
        if (colon) {
            char *dash = strchr(colon + 1, '-');
            if (dash)
                *dash = 0;
            if (!parse_hex16(colon + 1, &r.low) ||
                (dash && !parse_hex16(dash + 1, &r.high))) {
                snprintf(error, error_size, "%s: the addresses are hex, LO or "
                         "LO-HI", item);
                return 0;
            }
            if (!dash)
                r.high = r.low;
        }
        if (r.low > r.high || r.low < lowest || r.high > highest) {
            snprintf(error, error_size, "%s: $%04X-$%04X is empty or outside "
                     "$%04X-$%04X", item, r.low, r.high, lowest, highest);
            return 0;
        }
        if (*count == A2VM_MAX_RANGES) {
            snprintf(error, error_size, "at most %d ranges", A2VM_MAX_RANGES);
            return 0;
        }
        ranges[(*count)++] = r;
    }
    if (!*count) {
        snprintf(error, error_size, "no range");
        return 0;
    }
    return 1;
}

/* ---- construction ---- */

void a2vm_default_config(a2vm_config *config)
{
    memset(config, 0, sizeof *config);
    config->core = A2VM_CORE_PY65;
    config->turbo = 1;
    config->speed = 1;
    config->io_cycles = -1;
    config->ramworks_banks = A2VM_MAX_BANKS;
    config->mouse = 1;
    config->phasor_slot = 4;
    config->mouse_slot = 2;
}

a2vm *a2vm_new(const a2vm_config *config, char *error, size_t error_size)
{
    if (config->ramworks_banks < 1 || config->ramworks_banks > A2VM_MAX_BANKS) {
        snprintf(error, error_size, "ramworks_banks must be 1..128");
        return NULL;
    }
    if (!config->turbo && config->speed < 1) {
        snprintf(error, error_size, "the speed must be at least 1 MHz");
        return NULL;
    }
    a2vm *m = calloc(1, sizeof *m);
    if (!m) {
        snprintf(error, error_size, "out of memory");
        return NULL;
    }
    m->aux_banks = calloc(A2VM_MAX_BANKS, A2VM_BANK_SIZE);
    m->amem.input = malloc(A2VM_AMEM_BUFFER);
    if (!m->aux_banks || !m->amem.input) {
        a2vm_free(m);
        snprintf(error, error_size, "out of memory");
        return NULL;
    }
    if (config->rom)
        memcpy(m->rom, config->rom, sizeof m->rom);
    else if (config->rom_path) {
        FILE *file = fopen(config->rom_path, "rb");
        size_t n = file ? fread(m->rom, 1, sizeof m->rom, file) : 0;
        int more = file && fgetc(file) != EOF;
        if (file)
            fclose(file);
        if (n != sizeof m->rom || more) {
            snprintf(error, error_size, "%s is not a 16 KB ROM image",
                     config->rom_path);
            a2vm_free(m);
            return NULL;
        }
    }
    m->core = config->core;
    m->clock = m->core == A2VM_CORE_PY65 ? &m->py65_cycles : &m->cpu.cycles;
    m->frame_cycles = config->turbo ? A2VM_TURBO_FRAME
                                    : (uint64_t)A2VM_FRAME_1MHZ * config->speed;
    m->vbl_start = A2VM_VBL_LINE * m->frame_cycles / A2VM_LINES;
    m->frame_1mhz = A2VM_FRAME_1MHZ;
    if (config->io_cycles >= 0)
        m->io_cycles = (uint64_t)config->io_cycles;
    else
        m->io_cycles = config->turbo ? m->frame_cycles / A2VM_FRAME_1MHZ : 0;
    m->ramworks_banks = config->ramworks_banks;
    m->mouse_on = config->mouse;
    m->mouse_plain = config->mouse_plain;
    m->mouse_apple = config->mouse_apple;
    if (config->mouse_rom) {
        FILE *file = fopen(config->mouse_rom, "rb");
        size_t n = file ? fread(m->romouse.rom, 1, sizeof m->romouse.rom,
                                file) : 0;
        int more = file && fgetc(file) != EOF;
        if (file)
            fclose(file);
        if (n != sizeof m->romouse.rom || more) {
            snprintf(error, error_size, "%s is not a 2 KB AppleMouse II ROM",
                     config->mouse_rom);
            a2vm_free(m);
            return NULL;
        }
        m->mouse_rom = 1;
        m->mouse_no_vbl = config->mouse_no_vbl;
        rm_reset(&m->romouse);
    }
    m->phasor_slot = config->phasor_slot;
    m->mouse_slot = config->mouse_slot;
    m->slot2_mode = m->mouse_slot == 2 &&
        (m->mouse_on || m->mouse_plain || m->mouse_apple || m->mouse_rom) ?
        A2VM_SLOT2_MOUSE : A2VM_SLOT2_OFF;
    m->slot2_mouse_kind = (uint8_t)((m->mouse_on ? 1 : 0) |
        (m->mouse_plain ? 2 : 0) | (m->mouse_apple ? 4 : 0) |
        (m->mouse_rom ? 8 : 0));
    m->snes_bit = 16;
    if (config->vidhd_slot) {
        if (config->vidhd_slot < 1 || config->vidhd_slot > 7) {
            snprintf(error, error_size, "the VidHD's slot must be 1..7");
            a2vm_free(m);
            return NULL;
        }
        m->vidhd.copy = calloc(1, 0x8000);
        if (!m->vidhd.copy) {
            snprintf(error, error_size, "out of memory");
            a2vm_free(m);
            return NULL;
        }
        m->vidhd.slot = config->vidhd_slot;
    }
    m->amem_on = config->amem;
    amem_init(&m->amem);
    if (config->blockdev_slot) {
        a2vm_blockdev *b = &m->blockdev;
        if (config->blockdev_slot < 1 || config->blockdev_slot > 7 ||
            !config->blockdev_path) {
            snprintf(error, error_size, "the block device needs a slot "
                     "1..7 and an image");
            a2vm_free(m);
            return NULL;
        }
        b->read_only = config->blockdev_ro;
        b->file = fopen(config->blockdev_path, b->read_only ? "rb" : "r+b");
        long size = -1;
        if (b->file && !fseek(b->file, 0, SEEK_END))
            size = ftell(b->file);
        if (size <= 0 || size % 512 || size / 512 > 0xffff) {
            snprintf(error, error_size, "%s is not an image of 1-65,535 "
                     "blocks", config->blockdev_path);
            a2vm_free(m);
            return NULL;
        }
        b->blocks = (uint32_t)(size / 512);
        b->slot = config->blockdev_slot;
        if (b->slot == 7)
            m->amem.rom[0x0a] = 0x60;   /* (the entry's RTS) */
    }
    mouse_init(&m->mouse);
    phasor_init(&m->phasor);
    m->sw[SW_TEXT] = 1;
    m->lc_bank2 = 1;
    for (int i = 0; i < 4; i++) {
        m->paddle_values[i] = 128;
        m->paddles[i] = 4 + 11 * 128;
    }
    m->paddle_trigger = -100000;
    m->next_vbl = m->vbl_start;

    /* py65's reset: PC 0 (the MPU's start_pc), S $FF, P $30 */
    m->r.sp = 0xff;
    m->r.p = 0x30;
    cpu65c02_init(&m->cpu, native_read, native_write, m);
    m->cpu.s = 0xff;
    m->cpu.p = 0x30;
    cpu65c02_normalise(&m->cpu);

    /* booted_zero_page */
    static const uint8_t zero_page[][2] = {
        { 0x20, 0 }, { 0x21, 40 }, { 0x22, 0 }, { 0x23, 24 }, { 0x32, 0xff },
        { 0x36, 0xf0 }, { 0x37, 0xfd }, { 0x38, 0x1b }, { 0x39, 0xfd }
    };
    for (size_t i = 0; i < sizeof zero_page / sizeof zero_page[0]; i++)
        m->main[zero_page[i][0]] = zero_page[i][1];
    a2vm_select_bank(m, 0);
    return m;
}

void a2vm_attach_prodos(a2vm *m, a2vm_prodos *prodos)
{
    uint8_t path[256];
    m->prodos = prodos;
    m->main[0xbf00] = 0x4c;
    m->main[0xbf01] = 0x00;
    m->main[0xbf02] = 0xbf;
    size_t length = prodos_launch_path(prodos, path, sizeof path);
    memcpy(m->main + 0x280, path, length);
}

void a2vm_attach_cost(a2vm *m, a2vm_cost *cost, int timed)
{
    m->cost = cost;
    cost->timed = timed;
    a2vm_cost_attach(m);
    if (timed) {
        m->clock = &cost->t;
        cost->t = 0;
        m->frame_cycles = a2vm_cost_frame_clocks(cost);
        m->vbl_start = cost->p.vbl_line * m->frame_cycles / cost->p.lines;
        m->frame_1mhz = 65u * cost->p.lines;
        m->io_cycles = 0;
        m->next_vbl = m->vbl_start;
    }
}

void a2vm_free(a2vm *m)
{
    if (!m)
        return;
    a2vm_cost_free(m->cost);
    prodos_free(m->prodos);
    free(m->aux_banks);
    free(m->amem.input);
    free(m->vidhd.copy);
    free(m->vidhd.check_map);
    if (m->blockdev.file)
        fclose(m->blockdev.file);
    free(m);
}

void a2vm_blockdev_global_page(a2vm *m)
{
    unsigned n = (unsigned)m->blockdev.slot;
    if (!n)
        return;
    m->main[0xbf30] = (uint8_t)(n << 4);            /* DEVNUM: drive 1 */
    m->main[0xbf10 + 2 * n] = 0x0a;                 /* DEVADR's entry */
    m->main[0xbf11 + 2 * n] = (uint8_t)(0xc0 + n);
}
