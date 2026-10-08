/* SPDX-License-Identifier: GPL-2.0-only
 * Functional slot-7 devices. Contract sources in appletini-one:
 * hdl/apple/{smartport_card,supersprite_card}.sv and
 * ps_sources/frontend/smartport_service.c (local revision 1a3e8d3).
 * Direct launches use ROM service traps; ROM boot executes supplied C700/C800
 * firmware. The backend answers FIFO commands immediately in both modes.
 */
#include "cards.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { FIFO_SIZE = 1024, BLOCK_SIZE = 512, VRAM_SIZE = 16384 };
enum { SP_BADCTL = 0x21, SP_IO = 0x27, SP_NODEV = 0x28, SP_NOWRITE = 0x2b };

struct ap_cards {
    a2vm *vm;
    unsigned mode;
    uint8_t *disk;
    size_t disk_size;
    uint8_t in[FIFO_SIZE], out[FIFO_SIZE], prefix[10];
    unsigned in_size, out_size, out_pos, prefix_size, prefix_family;
    int selected, ready, overflow;
    uint8_t firmware, internal_c8;
    uint8_t slot_rom[256], c8_rom[2048];
    uint8_t vram[VRAM_SIZE], regs[8], ay[16];
    uint16_t vaddr;
    uint8_t read_buffer, latch, low, frame_flag, apple_video, overlay, ay_reg;
    uint8_t sprite_flags, ay_latched;
    uint64_t next_vbl;
};

static void update_irq(ap_cards *c)
{
    cpu65c02_set_irq(&c->vm->cpu, 2,
                     c->mode && c->frame_flag && (c->regs[1] & 0x20));
}

static void vdp_reset(ap_cards *c)
{
    /* Hardware resets the protocol and registers, retaining VRAM. */
    memset(c->regs, 0, sizeof c->regs);
    if (c->vm->sound_event) c->vm->sound_event(c->vm, 1, 4, 0, 0);
    memset(c->ay, 0, sizeof c->ay);
    c->vaddr = 0;
    c->read_buffer = c->latch = c->low = c->frame_flag = c->overlay = c->ay_reg = 0;
    c->apple_video = 1;
    c->ay_latched = 0;
    update_irq(c);
}

static void sprite_status(ap_cards *c)
{
    /* Match the current PS renderer, including its transparent-pattern
     * collision behavior. It preserves prior flags in text/blanked modes
     * and while the overlay is off. Updates occur at virtual VBlank here,
     * without the hardware ARM compositor's asynchronous scheduling. */
    if (!c->overlay || !(c->regs[1] & 0x40) || (c->regs[1] & 0x10)) return;
    unsigned attributes = (unsigned)(c->regs[5] & 0x7f) << 7;
    unsigned patterns = (unsigned)(c->regs[6] & 7) << 11;
    int size16 = !!(c->regs[1] & 2);
    int mag = c->regs[1] & 1 ? 2 : 1;
    int dim = (size16 ? 16 : 8) * mag;
    uint8_t counts[192] = {0};
    uint8_t occupied[192 * 256 / 8] = {0};
    uint32_t rows[32] = {0};
    unsigned flags = 31, last = 32;
    for (unsigned i = 0; i < 32; i++)
        if (c->vram[attributes + 4 * i] == 0xd0) { last = i; break; }
    for (unsigned i = 0; i < last; i++) {
        int y = c->vram[attributes + 4 * i];
        int sy = (y >= 0xe0 ? y - 256 : y) + 1;
        for (int dy = 0; dy < dim; dy++) {
            int line = sy + dy;
            if (line < 0 || line >= 192) continue;
            unsigned n = ++counts[line];
            if (n <= 4) rows[i] |= UINT32_C(1) << dy;
            else if (n == 5 && !(flags & 0x40)) flags = 0x40 | i;
        }
    }
    for (unsigned i = 0; i < last; i++) {
        const uint8_t *attribute = c->vram + attributes + 4 * i;
        int sy = (attribute[0] >= 0xe0 ? (int)attribute[0] - 256 : attribute[0]) + 1;
        int sx = attribute[1] - ((attribute[3] & 0x80) ? 32 : 0);
        unsigned pattern = size16 ? attribute[2] & 0xfc : attribute[2];
        for (int dy = 0; dy < dim; dy++) {
            if (!(rows[i] & (UINT32_C(1) << dy))) continue;
            unsigned row = (unsigned)(dy / mag);
            for (int dx = 0; dx < dim; dx++) {
                int col = sx + dx;
                if (col < 0 || col >= 256) continue;
                unsigned column = (unsigned)(dx / mag);
                unsigned pattern_address = patterns + pattern * 8 + row +
                                            (size16 && column >= 8 ? 16 : 0);
                if (!(c->vram[pattern_address] & (0x80u >> (column & 7)))) continue;
                unsigned bit = (unsigned)(sy + dy) * 256 + (unsigned)col;
                uint8_t mask = (uint8_t)(1u << (bit & 7));
                if (occupied[bit >> 3] & mask) flags |= 0x20;
                occupied[bit >> 3] |= mask;
            }
        }
    }
    c->sprite_flags = (uint8_t)flags;
}

void ap_cards_tick(ap_cards *c)
{
    if (!c->mode) return;
    uint64_t now = a2vm_now(c->vm);
    if (now >= c->next_vbl) {
        uint64_t frames = (now - c->next_vbl) / c->vm->frame_cycles + 1;
        c->next_vbl += frames * c->vm->frame_cycles;
        c->frame_flag = 1;
        sprite_status(c);
        update_irq(c);
    }
}

static unsigned status(ap_cards *c, unsigned unit, unsigned selector,
                         uint8_t *out)
{
    uint32_t blocks = (uint32_t)(c->disk_size / BLOCK_SIZE);
    memset(out, 0, 32);
    if (!unit) {
        out[0] = c->disk ? 1 : 0;
        if (!selector) return 8;
        if (selector != 3) return 0;
        /* Preserve the hardware's exact controller status layout. */
        out[8] = 12;
        memcpy(out + 9, "Appletini SP", 12);
        memset(out + 21, ' ', 4);
        out[27] = 1;
        return 29;
    }
    out[0] = 0xf8;               /* Session overlay is writable. */
    out[1] = (uint8_t)blocks;
    out[2] = (uint8_t)(blocks >> 8);
    out[3] = (uint8_t)(blocks >> 16);
    if (!selector) return 4;
    if (selector != 3) return 0;
    out[4] = 12;
    memcpy(out + 5, "Appletini HD", 12);
    memset(out + 17, ' ', 4);
    out[21] = 2;
    out[22] = 0x20;
    out[23] = 1;
    return 25;
}

static unsigned execute(ap_cards *c, unsigned family, const uint8_t *request,
                          unsigned length, uint8_t *reply)
{
    unsigned command, unit, prefix;
    uint32_t block;
    reply[0] = SP_BADCTL;
    if (family == 1 && length >= 6) {
        command = request[0];
        unit = ((request[1] >> 4) & 7) == 7
                 ? ((request[1] >> 7) ? 2 : 1) : 255;
        block = (uint32_t)request[4] | (uint32_t)request[5] << 8;
        prefix = 6;
    } else if (family == 2 && length >= 10) {
        command = request[0];
        unit = request[2];
        block = (uint32_t)request[5] | (uint32_t)request[6] << 8 |
                (uint32_t)request[7] << 16;
        prefix = 10;
        if (!unit && request[5] == 0x80 && (command == 0 || command == 4)) {
            if (request[1] != 3 || (command == 0 && length != 10) ||
                (command == 4 && (length < 12 ||
                  length != 12u + request[10] + ((unsigned)request[11] << 8)))) {
                reply[0] = command == 4 ? 0x61 : SP_BADCTL;
                return 1;
            }
            uint8_t normalized[FIFO_SIZE];
            memcpy(normalized, request, length);
            /* These bytes are unspecified firmware padding, not parameters. */
            memset(normalized + 6, 0, 4);
            a2vm_amem *a = &c->vm->amem;
            a->requests++;
            a->last_family = 2;
            unsigned n = (unsigned)a2vm_amem_execute(c->vm, 2, normalized,
                                                    length, reply);
            if (!n) { reply[0] = SP_BADCTL; return 1; }
            a->last_result = reply[0];
            if (c->vm->cost && !reply[0])
                a2vm_cost_amem(c->vm, normalized, length);
            return n;
        }
        if (command == 0) {
            if (unit && (unit != 1 || !c->disk)) {
                reply[0] = SP_NODEV;
                return 1;
            }
            unsigned n = status(c, unit, request[5], reply + 3);
            if (!n) return 1;
            reply[0] = 0;
            reply[1] = (uint8_t)n;
            reply[2] = 0;
            return n + 3;
        }
        if (command == 3) {
            reply[0] = SP_NOWRITE; /* Actual firmware refuses FORMAT. */
            return 1;
        }
    } else {
        return 1;
    }
    if (command > 2) return 1;
    if (unit != 1 || !c->disk) {
        reply[0] = SP_NODEV;
        if (family == 1 && command == 0) {
            reply[1] = reply[2] = 0;
            return 3;
        }
        return 1;
    }
    if (!command) {
        uint32_t blocks = (uint32_t)(c->disk_size / BLOCK_SIZE);
        if (blocks > 65535) blocks = 65535;
        reply[0] = 0;
        reply[1] = (uint8_t)blocks;
        reply[2] = (uint8_t)(blocks >> 8);
        return 3;
    }
    if (block >= c->disk_size / BLOCK_SIZE) {
        reply[0] = SP_IO;
        return 1;
    }
    uint8_t *data = c->disk + (size_t)block * BLOCK_SIZE;
    if (command == 1) {
        reply[0] = 0;
        memcpy(reply + 1, data, BLOCK_SIZE);
        return 513;
    }
    if (length < prefix + BLOCK_SIZE) {
        reply[0] = SP_IO;
        return 1;
    }
    memcpy(data, request + prefix, BLOCK_SIZE);
    reply[0] = 0;
    return 1;
}

static void fifo_execute(ap_cards *c, unsigned family)
{
    c->ready = 0;
    c->out_pos = 0;
    c->out_size = 1;
    c->out[0] = SP_BADCTL;
    if (c->overflow) goto done;
    if (family == 0x81 || family == 0x82) {
        unsigned prefix = family == 0x81 ? 6 : 10;
        c->prefix_size = 0;
        if (c->in_size >= prefix && c->in[0] == 2) {
            memcpy(c->prefix, c->in, prefix);
            c->prefix_size = prefix;
            c->prefix_family = family & 0x7f;
            c->out[0] = 0;
        }
    } else {
        if (c->prefix_size) {
            unsigned prefix = c->prefix_size;
            c->prefix_size = 0;
            if (family != c->prefix_family || c->in_size > FIFO_SIZE - prefix)
                goto done;
            memmove(c->in + prefix, c->in, c->in_size);
            memcpy(c->in, c->prefix, prefix);
            c->in_size += prefix;
        }
        c->out_size = execute(c, family, c->in, c->in_size, c->out);
    }
done:
    c->in_size = 0;
    c->overflow = 0;
    c->ready = 1;
}

static int device_read(a2vm *vm, uint16_t address)
{
    ap_cards *c = vm->device_context;
    if (c->mode && address >= 0xc0f0 && address <= 0xc0ff) {
        ap_cards_tick(c);
        switch (address & 15) {
        case 0: {
            int value = c->read_buffer;
            c->read_buffer = c->vram[c->vaddr];
            c->vaddr = (c->vaddr + 1) & 0x3fff;
            c->latch = 0;
            return value;
        }
        case 1: {
            int value = (c->frame_flag ? 0x80 : 0) | c->sprite_flags;
            c->frame_flag = c->latch = 0;
            update_irq(c);
            return value;
        }
        case 14: case 15: return c->ay_latched && c->ay_reg < 16 ? c->ay[c->ay_reg] : 0xff;
        default: return 0;
        }
    }
    if (address < 0xc100 || address > 0xcfff) return -1;
    if (address == 0xcfff) {
        int value = c->firmware && (c->internal_c8 || vm->sw[SW_INTCXROM]) ?
                    vm->rom[0xfff] : 0;
        c->selected = vm->amem.selected = 0;
        c->internal_c8 = 0;
        return value;
    }
    /* Enhanced //e internal C3 claims C8 until CFFF/reset, even when
     * INTCXROM subsequently clears. Slot-ROM fetches cannot clear it. */
    if (c->firmware && address >= 0xc300 && address < 0xc400 &&
        !vm->sw[SW_SLOTC3ROM]) {
        c->internal_c8 = 1;
        c->selected = vm->amem.selected = 0;
    }
    if (vm->sw[SW_INTCXROM]) return -1;
    if (address < 0xc700) {
        c->selected = vm->amem.selected = 0;
        return -1;
    }
    if (c->firmware && address >= 0xc800 && c->internal_c8)
        return vm->rom[address - 0xc000];
    if (c->mode) return 0;        /* No SmartPort behind SuperSprite. */
    if (address < 0xc800) {
        c->selected = vm->amem.selected = 1;
        return c->firmware ? c->slot_rom[address & 255] : vm->amem.rom[address & 255];
    }
    if (!c->selected) return -1;
    if (address == 0xcff0)
        return c->out_pos < c->out_size ? c->out[c->out_pos] : 0;
    /* Bit 5 is private-vTW availability, not ordinary UltraWarp I/O;
     * bit 6 stays clear because this model uses the FIFO fallback. */
    if (address == 0xcff1)
        return (vm->amem.private_port ? 0x20 : 0) | (c->ready ? 0x80 : 0);
    if (address == 0xcff2) return 0;
    return c->firmware ? c->c8_rom[address - 0xc800] : 0;
}

static int device_write(a2vm *vm, uint16_t address, uint8_t value)
{
    ap_cards *c = vm->device_context;
    if (c->mode && address >= 0xc0f0 && address <= 0xc0ff) {
        switch (address & 15) {
        case 0:
            c->vram[c->vaddr] = value;
            c->vaddr = (c->vaddr + 1) & 0x3fff;
            c->latch = 0;
            break;
        case 1:
            if (!c->latch) {
                c->low = value;
                c->latch = 1;
            } else {
                c->latch = 0;
                unsigned operation = value >> 6;
                if (operation < 2) {
                    c->vaddr = (uint16_t)(((value & 63) << 8) | c->low);
                    if (!operation) {
                        c->read_buffer = c->vram[c->vaddr];
                        c->vaddr = (c->vaddr + 1) & 0x3fff;
                    }
                } else if (operation == 2) {
                    c->regs[value & 7] = c->low;
                }
            }
            break;
        case 3: c->apple_video = 0; break;
        case 4: c->apple_video = 1; break;
        case 5: c->overlay = 0; break;
        case 6: c->overlay = 1; break;
        case 7: vdp_reset(c); break;
        case 12: case 13: {
            if (!c->ay_latched || c->ay_reg >= 16) break;
            static const uint8_t masks[16] = {
                255,15,255,15,255,15,31,255,31,31,31,255,255,15,255,255
            };
            if (c->vm->sound_event)
                c->vm->sound_event(c->vm, 0, 4, c->ay_reg, value);
            c->ay[c->ay_reg] = value & masks[c->ay_reg];
            break;
        }
        case 14: case 15: c->ay_reg = value; c->ay_latched = 1; break;
        default: break;
        }
        update_irq(c);
        return 1;
    }
    if (address < 0xc100 || address > 0xcfff) return 0;
    if (address == 0xcfff) {
        c->selected = vm->amem.selected = 0;
        c->internal_c8 = 0;
        return 1;
    }
    if (c->firmware && address < 0xc800) {
        if (address >= 0xc300 && address < 0xc400 && !vm->sw[SW_SLOTC3ROM]) {
            c->internal_c8 = 1;
            c->selected = vm->amem.selected = 0;
        } else if (!vm->sw[SW_INTCXROM]) {
            c->selected = vm->amem.selected = address >= 0xc700;
        }
    }
    if (address < 0xc700) return 0;
    if (vm->sw[SW_INTCXROM]) return 0;
    if (c->mode) return 1;
    if (c->firmware && address >= 0xc800 && c->internal_c8) return 1;
    if (!c->selected) return 0;
    if (address == 0xcff0) {
        if (c->in_size < FIFO_SIZE) c->in[c->in_size++] = value;
        else c->overflow = 1;
    } else if (address == 0xcff2) {
        if (c->out_pos < c->out_size) c->out_pos++;
    } else if (address == 0xcff1) {
        fifo_execute(c, value);
    }
    return 1;
}

ap_cards *ap_cards_new(a2vm *vm)
{
    ap_cards *c = calloc(1, sizeof *c);
    if (!c) return NULL;
    c->vm = vm;
    c->next_vbl = vm->next_vbl;
    vm->device_context = c;
    vm->device_read = device_read;
    vm->device_write = device_write;
    vdp_reset(c);
    return c;
}

void ap_cards_free(ap_cards *c)
{
    if (!c) return;
    c->vm->device_context = NULL;
    c->vm->device_read = NULL;
    c->vm->device_write = NULL;
    cpu65c02_set_irq(&c->vm->cpu, 2, 0);
    free(c->disk);
    free(c);
}

int ap_cards_mount(ap_cards *c, const char *path, char *error, size_t size)
{
    FILE *file = path ? fopen(path, "rb") : NULL;
    long length = -1;
    if (file && !fseek(file, 0, SEEK_END)) length = ftell(file);
    /* Bound allocation: large SmartPort images need a sparse overlay backend. */
    if (length <= 0 || length % BLOCK_SIZE || length > 128L * 1024 * 1024) {
        if (file) fclose(file);
        snprintf(error, size, "disk must be a raw .po/.hdv image, 512-byte blocks, at most 128 MiB");
        return 0;
    }
    uint8_t *data = malloc((size_t)length);
    if (!data) {
        fclose(file);
        snprintf(error, size, "out of memory loading disk");
        return 0;
    }
    int bad = fseek(file, 0, SEEK_SET) ||
               fread(data, 1, (size_t)length, file) != (size_t)length;
    if (fclose(file)) bad = 1;
    if (bad) {
        free(data);
        snprintf(error, size, "cannot read disk image");
        return 0;
    }
    free(c->disk);
    c->disk = data;
    c->disk_size = (size_t)length;
    return 1;
}

int ap_cards_mode(ap_cards *c, const char *mode)
{
    unsigned next;
    if (mode && !strcmp(mode, "smartport")) next = 0;
    else if (mode && !strcmp(mode, "supersprite")) next = 1;
    else return 0;
    if (next == c->mode) return 1;
    c->mode = next;
    c->vm->amem_on = !next;      /* Also remove the private SmartPort cost path. */
    uint64_t now = a2vm_now(c->vm);
    c->next_vbl = c->vm->vbl_start;
    if (now >= c->next_vbl)
        c->next_vbl += ((now - c->next_vbl) / c->vm->frame_cycles + 1) *
                       c->vm->frame_cycles;
    c->selected = c->vm->amem.selected = 0;
    c->in_size = c->out_size = c->out_pos = c->prefix_size = 0;
    c->ready = c->overflow = 0;
    vdp_reset(c);
    return 1;
}

unsigned ap_cards_slot7(const ap_cards *c) { return c->mode; }

int ap_cards_boot(ap_cards *c, const void *slot_rom, size_t slot_size,
                   const void *c8_rom, size_t c8_size)
{
    if (!slot_rom || !c8_rom || slot_size != 256 || c8_size != 2048 ||
        !c->disk || c->mode) return 0;
    memcpy(c->slot_rom, slot_rom, slot_size);
    memcpy(c->c8_rom, c8_rom, c8_size);
    c->firmware = 1;
    c->internal_c8 = c->selected = c->vm->amem.selected = 0;
    c->in_size = c->out_size = c->out_pos = c->prefix_size = 0;
    c->ready = c->overflow = 0;
    return 1;
}

int ap_cards_read(ap_cards *c, const char *kind, unsigned offset,
                   void *buffer, size_t size)
{
    if (!kind || (size && !buffer)) return 0;
    const uint8_t *data;
    size_t length;
    uint8_t state[8] = { (c->frame_flag ? 0x80 : 0) | c->sprite_flags, (uint8_t)c->vaddr,
                        (uint8_t)(c->vaddr >> 8), c->latch, c->apple_video,
                        c->overlay, c->ay_reg, (uint8_t)c->mode };
    if (!strcmp(kind, "phasor-ay")) { data = &c->vm->phasor.ay[0][0]; length = 64; }
    else if (!strcmp(kind, "supersprite-vram")) { data = c->vram; length = sizeof c->vram; }
    else if (!strcmp(kind, "supersprite-regs")) { data = c->regs; length = sizeof c->regs; }
    else if (!strcmp(kind, "supersprite-ay")) { data = c->ay; length = sizeof c->ay; }
    else if (!strcmp(kind, "supersprite-state")) { data = state; length = sizeof state; }
    else return 0;
    if (offset > length || size > length - offset) return 0;
    if (size) memcpy(buffer, data + offset, size);
    return 1;
}

/* Bus-visible memory mapping applies to stack, parameters and data. The
 * service trap advances CPU time by bus accesses plus an RTS-equivalent
 * six cycles. It does not model the omitted firmware instruction latency. */
static uint8_t guest_read(ap_cards *c, uint16_t address)
{
    c->vm->cpu.cycles++;
    return a2vm_read(c->vm, address);
}

static void guest_write(ap_cards *c, uint16_t address, uint8_t value)
{
    c->vm->cpu.cycles++;
    a2vm_write(c->vm, address, value);
}

int ap_cards_step(ap_cards *c)
{
    a2vm *vm = c->vm;
    uint16_t pc = vm->cpu.pc;
    if (c->firmware || c->mode || vm->sw[SW_INTCXROM] ||
        (pc != 0xc70a && pc != 0xc70d) ||
        vm->cpu.state != CPU65C02_RUNNING || vm->cpu.nmi_pending ||
        (vm->cpu.irq_sources && !(vm->cpu.p & CPU65C02_I)))
        return 0;
    /* Firmware BSETUP publishes MSLOT before moving the result; a read
     * buffer covering $07F8 must retain the byte read from the disk. */
    guest_write(c, 0x07f8, 0xc7);
    uint8_t lo = guest_read(c, (uint16_t)(0x100 | (uint8_t)(vm->cpu.s + 1)));
    uint8_t hi = guest_read(c, (uint16_t)(0x100 | (uint8_t)(vm->cpu.s + 2)));
    uint16_t ret = (uint16_t)(lo | hi << 8);
    uint16_t buffer = 0;
    uint8_t request[FIFO_SIZE] = {0}, reply[FIFO_SIZE];
    unsigned length, family = pc == 0xc70d ? 2 : 1;
    if (family == 2) {
        request[0] = guest_read(c, (uint16_t)(ret + 1));
        lo = guest_read(c, (uint16_t)(ret + 2));
        hi = guest_read(c, (uint16_t)(ret + 3));
        uint16_t parameters = (uint16_t)(lo | hi << 8);
        for (unsigned i = 0; i < 9; i++)
            request[i + 1] = guest_read(c, (uint16_t)(parameters + i));
        buffer = (uint16_t)(request[3] | request[4] << 8);
        length = 10;
        ret = (uint16_t)(ret + 3);
        if (request[0] == 4) {
            lo = guest_read(c, buffer);
            hi = guest_read(c, (uint16_t)(buffer + 1));
            unsigned payload = lo | (unsigned)hi << 8;
            if (payload <= FIFO_SIZE - 12) {
                request[10] = lo;
                request[11] = hi;
                for (unsigned i = 0; i < payload; i++)
                    request[12 + i] = guest_read(c, (uint16_t)(buffer + 2 + i));
                length = 12 + payload;
            }
        }
    } else {
        for (unsigned i = 0; i < 6; i++) request[i] = guest_read(c, (uint16_t)(0x42 + i));
        buffer = (uint16_t)(request[2] | request[3] << 8);
        length = 6;
    }
    if (request[0] == 2) {
        for (unsigned i = 0; i < BLOCK_SIZE; i++)
            request[length + i] = guest_read(c, (uint16_t)(buffer + i));
        length += BLOCK_SIZE;
    }
    unsigned n = execute(c, family, request, length, reply);
    if (!reply[0]) {
        unsigned skip = request[0] == 1 ? 1 : 3;
        if ((family == 2 && request[0] == 0) || request[0] == 1)
            for (unsigned i = skip; i < n; i++)
                guest_write(c, (uint16_t)(buffer + i - skip), reply[i]);
        if (!request[0]) {
            vm->cpu.x = reply[1];
            vm->cpu.y = reply[2];
        }
    }
    vm->cpu.a = reply[0];
    /* Both ROM return paths end with CMP #$01: carry is the API result,
     * and N/Z reflect A-1 rather than A. */
    uint8_t compared = (uint8_t)(reply[0] - 1);
    vm->cpu.p = (uint8_t)((vm->cpu.p & ~(CPU65C02_C | CPU65C02_Z | CPU65C02_N)) |
                         (reply[0] ? CPU65C02_C : 0) |
                         (!compared ? CPU65C02_Z : 0) | (compared & CPU65C02_N));
    vm->cpu.s = (uint8_t)(vm->cpu.s + 2);
    vm->cpu.pc = (uint16_t)(ret + 1);
    vm->cpu.cycles += 6;
    vm->instructions++;
    vm->instruction_pc = pc;
    /* In TURBO, routed accesses already charged the cost model. */
    if (vm->cost) vm->cost->t += 6 * vm->cost->p.turbo_hit;
    c->selected = vm->amem.selected = 1;
    return 1;
}
