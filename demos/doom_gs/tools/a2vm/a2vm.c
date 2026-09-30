/*
 * a2vm: the machine around the cores. See a2vm.h for what it models;
 * each part names the part of demos/doom/tools/a2sim.py it follows.
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

/* ---- the Phasor (a2sim.Phasor) ---- */

enum { MOCKINGBOARD = 0, NATIVE = 5 };

static void phasor_init(a2vm_phasor *f)
{
    memset(f, 0, sizeof *f);
    f->ssi_dur = 0xc0;
}

static void phasor_mode_switch(a2vm_phasor *f, unsigned address)
{
    if (address & 8)
        f->mode = MOCKINGBOARD;
    f->mode |= address & 7;
}

/* _vias_for: a mask of the VIAs the address selects. */
static unsigned phasor_vias(const a2vm_phasor *f, unsigned address)
{
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
    if (f->mode == NATIVE) {
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
    int native = f->mode == NATIVE;
    if (!(bus & 4)) {
        memset(f->ay[index * 2], 0, 16);
        memset(f->ay[index * 2 + 1], 0, 16);
        f->selected[index][0] = f->selected[index][1] = 0;
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
        else {
            if (cs0 && f->selected[index][0])
                targets[count++] = index * 2;
            if ((cs0 || cs1) && f->selected[index][1])
                targets[count++] = index * 2 + 1;
        }
        for (unsigned i = 0; i < count; i++) {
            unsigned chip = targets[i];
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
    if (phasor_ssi_hit(f, address)) {
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
    if (phasor_ssi_hit(f, address)) {
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
        int64_t t1 = (0xffff - ((int64_t)a2vm_bus_clock(m) -
                                f->t1_start[index])) & 0xffff;
        switch (reg) {
        case 0: return f->via[index].orb;
        case 1: {
            unsigned bus = f->via[index].orb & f->via[index].ddrb;
            if (f->via[index].ddra == 0 && (bus & 7) == 5) {
                int cs0, cs1;
                phasor_chip_selects(f, index, &cs0, &cs1);
                unsigned chip = index * 2 + (cs0 ? 0 : 1);
                return f->ay[chip][f->latched[chip] & 15];
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

static uint8_t io_read(a2vm *m, uint16_t address)
{
    unsigned low = address & 0xff;
    m->io_accesses++;
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
    if (low == 0x30)
        m->speaker_toggles++;
    else if (low >= 0x50 && low <= 0x57)
        video_switch(m, low);
    else if (low >= 0x61 && low <= 0x63)
        return m->buttons[low - 0x61];
    else if (low >= 0x64 && low <= 0x67) {
        int64_t elapsed = (int64_t)a2vm_bus_clock(m) - m->paddle_trigger;
        return elapsed < m->paddles[low - 0x64] ? 0x80 : 0x00;
    } else if (low == 0x70)
        m->paddle_trigger = (int64_t)a2vm_bus_clock(m);
    else if (low >= 0x80 && low <= 0x8f)
        lc_switch(m, low, 1);
    else if ((int)(low >> 4) == 8 + m->phasor_slot) {
        if (!m->phasor_mb_only)
            phasor_mode_switch(&m->phasor, low);
    } else if (m->mouse_on && (int)(low >> 4) == 8 + m->mouse_slot)
        return mouse_read(&m->mouse, low & 0x0f);
    return 0x00;
}

static void io_write(a2vm *m, uint16_t address, uint8_t value)
{
    unsigned low = address & 0xff;
    m->io_accesses++;
    *m->clock += m->io_cycles;
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
    else if (low == 0x30)
        m->speaker_toggles++;
    else if (low >= 0x50 && low <= 0x57)
        video_switch(m, low);
    else if (low == 0x70)
        m->paddle_trigger = (int64_t)a2vm_bus_clock(m);
    else if (low == 0x71 || low == 0x73)
        a2vm_select_bank(m, value);
    else if (low >= 0x80 && low <= 0x8f)
        lc_switch(m, low, 0);
    else if ((int)(low >> 4) == 8 + m->phasor_slot) {
        if (!m->phasor_mb_only)
            phasor_mode_switch(&m->phasor, low);
    } else if (m->mouse_on && (int)(low >> 4) == 8 + m->mouse_slot)
        mouse_write(&m->mouse, low & 0x0f, value);
}

/* ---- the bus ---- */

static uint8_t slow_read(a2vm *m, uint16_t address)
{
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
    if (!m->sw[SW_INTCXROM] && slot == m->phasor_slot)
        return phasor_read(m, address);
    if (m->mouse_on && !m->sw[SW_INTCXROM] && address < 0xc800 &&
        slot == m->mouse_slot)
        return mouse_rom[address & 0xff];
    return m->rom[address - 0xc000];
}

static void slow_write(a2vm *m, uint16_t address, uint8_t value)
{
    if (address >= 0xd000)
        return;                     /* the language card, write-protected */
    if (address < 0xc100) {
        io_write(m, address, value);
        return;
    }
    *m->clock += m->io_cycles;
    if (m->amem_on && amem_write(m, address, value))
        return;
    if (((address >> 8) & 7) == m->phasor_slot)
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

uint8_t a2vm_read(a2vm *m, uint16_t address)
{
    return bus_read(m, address, CPU65C02_DATA);
}

void a2vm_write(a2vm *m, uint16_t address, uint8_t value)
{
    bus_write(m, address, value, CPU65C02_DATA);
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

static uint8_t native_read(void *context, uint16_t address,
                           cpu65c02_kind kind)
{
    return bus_read(context, address, kind);
}

static void native_write(void *context, uint16_t address, uint8_t value,
                         cpu65c02_kind kind)
{
    bus_write(context, address, value, kind);
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
    if (m->mouse_on)
        mouse_vblank(&m->mouse);
}

static void skip_idle(a2vm *m, uint16_t pc)
{
    for (unsigned i = 0; i < m->idle_count; i++) {
        const a2vm_idle *idle = &m->idle[i];
        if (idle->pc != pc)
            continue;
        if (idle->need_main_zp && m->sw[SW_ALTZP])
            return;
        if (idle->compare &&
            (m->main[idle->word_a] != m->main[idle->word_b] ||
             m->main[(uint16_t)(idle->word_a + 1)] !=
                 m->main[(uint16_t)(idle->word_b + 1)]))
            return;
        if (idle->need_vbl && !a2vm_in_vbl(m))
            return;
        uint64_t now = a2vm_now(m), target;
        if (idle->kind == A2VM_IDLE_VBL)
            target = m->next_vbl;
        else
            target = (now / m->frame_cycles + 1) * m->frame_cycles;
        if (target > now) {
            m->idle_cycles += target - now;
            if (m->cost)
                a2vm_cost_skip(m, target - now);
            *m->clock = target;
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

void a2vm_step(a2vm *m)
{
    if (a2vm_now(m) >= m->next_vbl)
        vbl_event(m);
    m->instructions++;
    if (m->core == A2VM_CORE_PY65) {
        if (m->mouse_on && m->mouse.irq && !(m->r.p & P65_I)) {
            m->r.waiting = 0;
            p65_irq(m);
            m->r.p &= (uint8_t)~P65_D;
            m->irqs++;
            if (m->ay_log)
                ay_log_irq(m);
            m->irq_guard = m->irq_bound_count != 0;
        }
        uint16_t pc = m->r.pc;
        if (m->idle_map[pc >> 3] & (1u << (pc & 7)))
            skip_idle(m, pc);
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
    int irq = m->mouse_on && m->mouse.irq;
    cpu65c02_set_irq(&m->cpu, 1, irq);
    int taken = irq && !(m->cpu.p & CPU65C02_I) &&
                m->cpu.state != CPU65C02_STOPPED;
    if (taken) {
        m->irqs++;
        if (m->ay_log)
            ay_log_irq(m);
    }
    uint16_t pc = m->cpu.pc;
    if (m->idle_map[pc >> 3] & (1u << (pc & 7)))
        skip_idle(m, pc);
    if (m->prodos && m->cpu.state == CPU65C02_RUNNING &&
        !(irq && !(m->cpu.p & CPU65C02_I)) && native_mli(m))
        return;
    int rti = (m->ay_log || m->irq_bound_count) && !taken &&
              m->cpu.state == CPU65C02_RUNNING && at_rti(m, m->cpu.pc);
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
    mouse_commit(&m->mouse, x, y, m->mouse.ps_buttons, 1);
}

void a2vm_mouse_delta(a2vm *m, int64_t dx, int64_t dy)
{
    a2vm_mouse *c = &m->mouse;
    int64_t x = clamp16(c->x + dx, c->clamp[0][0], c->clamp[0][1]);
    int64_t y = clamp16(c->y + dy, c->clamp[1][0], c->clamp[1][1]);
    mouse_commit(c, x, y, c->ps_buttons, 1);
}

void a2vm_mouse_buttons(a2vm *m, int left, int right)
{
    mouse_commit(&m->mouse, m->mouse.x, m->mouse.y,
                 (left ? 1u : 0u) | (right ? 2u : 0u), 1);
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
    m->phasor_slot = config->phasor_slot;
    m->mouse_slot = config->mouse_slot;
    m->amem_on = config->amem;
    amem_init(&m->amem);
    mouse_init(&m->mouse);
    phasor_init(&m->phasor);
    m->sw[SW_TEXT] = 1;
    m->lc_bank2 = 1;
    for (int i = 0; i < 4; i++)
        m->paddles[i] = 1400;
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
    free(m);
}
