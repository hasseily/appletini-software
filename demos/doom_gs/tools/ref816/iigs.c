/*
 * The minimal Apple IIgs: see iigs.h.
 */
#include "iigs.h"

#include <stdlib.h>
#include <string.h>

enum {
    BLOCK = 512,
    STACK_PAGE = 0x0100,
    /* Registers of the I/O page ($C0xx), by their low byte. */
    IO_80COL_OFF = 0x0c, IO_ALTCHAR_OFF = 0x0e, IO_VBL = 0x19,
    IO_VGC_INT = 0x23, IO_MOUSE = 0x24, IO_ADB_DATA = 0x26,
    IO_ADB_STATUS = 0x27, IO_NEWVIDEO = 0x29, IO_SCAN_INT = 0x32,
    IO_BORDER = 0x34, IO_SHADOW = 0x35, IO_SPEED = 0x36,
    IO_GLU = 0x3c, IO_INTEN = 0x41, IO_CLEAR_VBL = 0x47,
    IO_TEXT_OFF = 0x50, IO_TEXT_ON = 0x51, IO_PAGE2_OFF = 0x54,
    IO_ANNUNCIATORS = 0x58, IO_ANNUNCIATORS_END = 0x5f,
    /* ProDOS block driver parameters in page 0, and its results. */
    PD_COMMAND = 0x42, PD_UNIT = 0x43, PD_BUFFER = 0x44, PD_BLOCK = 0x46,
    ERR_BAD_COMMAND = 0x01, ERR_BAD_CODE = 0x21, ERR_IO = 0x27,
    ERR_NO_DEVICE = 0x28,
    /* SmartPort: the unit of the boot drive, its status byte (block
       device, writes and reads allowed, on line, formattable) and its
       device type (a hard disk). */
    SP_UNIT = 1, SP_STATUS = 0x00, SP_CONTROL = 0x04, SP_STATUS_BYTE = 0xf8, SP_TYPE_HARD_DISK = 0x02,
    SP_CODE_STATUS = 0x00, SP_CODE_DIB = 0x03,
    DIB_LENGTH = 25, DIB_NAME = 5, DIB_TYPE = 21
};

/* ---- time ---- */

uint64_t iigs_clock(const iigs *m)
{
    return m->clock_base +
           (m->cpu.cycles - m->cycle_base) * m->clock_num / m->clock_den;
}

int iigs_vbl(const iigs *m)
{
    return iigs_clock(m) % IIGS_FRAME_CLOCKS >=
           (uint64_t)IIGS_VBL_LINE * IIGS_LINE_CLOCKS;
}

static void set_speed(iigs *m, uint8_t value)
{
    m->clock_base = iigs_clock(m);
    m->cycle_base = m->cpu.cycles;
    if (value & 0x80) {
        m->clock_num = m->fast_num;
        m->clock_den = m->fast_den;
    } else {
        m->clock_num = IIGS_SLOW_CLOCKS;
        m->clock_den = 1;
    }
    m->speed = value;
}

static uint64_t gcd(uint64_t a, uint64_t b)
{
    while (b) {
        uint64_t r = a % b;
        a = b;
        b = r;
    }
    return a;
}

void iigs_set_cpu_hz(iigs *m, uint32_t hz)
{
    if (hz) {
        /* The fraction in lowest terms keeps the products of iigs_clock
           small: 12 MHz is 715909/600000 clocks a cycle. */
        uint64_t common = gcd(IIGS_MASTER_HZ, hz);
        m->fast_num = IIGS_MASTER_HZ / common;
        m->fast_den = hz / common;
    } else {
        m->fast_num = IIGS_FAST_CLOCKS;
        m->fast_den = 1;
    }
    set_speed(m, m->speed);
}

static void update_irq(iigs *m)
{
    cpu816_set_irq(&m->cpu, IIGS_IRQ_DOC, doc_irq(&m->doc));
    cpu816_set_irq(&m->cpu, IIGS_IRQ_ADB, adb_irq(&m->adb));
}

static uint64_t earliest(uint64_t a, uint64_t b)
{
    return a < b ? a : b;
}

/* Bring the DOC, the ADB and the frame count up to `now`. */
static void events(iigs *m, uint64_t now)
{
    /* Whole periods of the clock fraction go into the base, exactly, so
       that the product in iigs_clock stays small however long the run
       and whatever the CPU rate. */
    uint64_t periods = (m->cpu.cycles - m->cycle_base) / m->clock_den;
    m->cycle_base += periods * m->clock_den;
    m->clock_base += periods * m->clock_num;

    doc_run(&m->doc, now);
    adb_run(&m->adb, now);
    update_irq(m);
    m->frame = now / IIGS_FRAME_CLOCKS;
    m->next_event = earliest(
        earliest(m->doc.next_sample, adb_next_event(&m->adb)),
        (m->frame + 1) * IIGS_FRAME_CLOCKS);
}

/* ---- the I/O page ---- */

static uint8_t io_read(iigs *m, uint8_t reg)
{
    uint64_t now = iigs_clock(m);
    uint8_t value;

    switch (reg) {
    case IO_VBL:
        return iigs_vbl(m) ? 0x80 : 0x00;
    case IO_MOUSE: case IO_ADB_DATA: case IO_ADB_STATUS:
        value = adb_read(&m->adb, reg, now);
        update_irq(m);
        return value;
    case IO_NEWVIDEO: return m->newvideo;
    case IO_BORDER: return m->border;
    case IO_SHADOW: return m->shadow;
    case IO_SPEED: return m->speed;
    case IO_GLU: case IO_GLU + 1: case IO_GLU + 2: case IO_GLU + 3:
        value = doc_glu_read(&m->doc, reg - IO_GLU, now);
        update_irq(m);
        return value;
    case IO_TEXT_OFF: m->text = 0; return 0;
    case IO_TEXT_ON: m->text = 1; return 0;
    default:
        break;
    }
    /* The annunciators: without a ZipGS nothing answers there, so the
       game's probe finds no card. */
    if (reg >= IO_ANNUNCIATORS && reg <= IO_ANNUNCIATORS_END)
        return 0;
    m->counts.io_reads[reg]++;
    return 0;
}

static void io_write(iigs *m, uint8_t reg, uint8_t value)
{
    uint64_t now = iigs_clock(m);

    switch (reg) {
    case IO_80COL_OFF: case IO_ALTCHAR_OFF: case IO_PAGE2_OFF:
    case IO_SCAN_INT: case IO_CLEAR_VBL:
        return;                 /* nothing of these is displayed */
    case IO_VGC_INT: m->vgc_int = value; return;
    case IO_INTEN: m->inten = value; return;
    case IO_MOUSE: case IO_ADB_DATA: case IO_ADB_STATUS:
        adb_write(&m->adb, reg, value, now);
        update_irq(m);
        return;
    case IO_NEWVIDEO: m->newvideo = value; return;
    case IO_BORDER: m->border = value; return;
    case IO_SHADOW: m->shadow = value; return;
    case IO_SPEED: set_speed(m, value); return;
    case IO_GLU: case IO_GLU + 1: case IO_GLU + 2: case IO_GLU + 3:
        doc_glu_write(&m->doc, reg - IO_GLU, value, now);
        update_irq(m);
        return;
    case IO_TEXT_OFF: m->text = 0; return;
    case IO_TEXT_ON: m->text = 1; return;
    default:
        break;
    }
    if (reg >= IO_ANNUNCIATORS && reg <= IO_ANNUNCIATORS_END)
        return;
    m->counts.io_writes[reg]++;
}

/* ---- the memory map ---- */

/* A read that the model answers with 0, by the instruction that made
   it: into the site of that instruction, a new one while there is
   room. */
static void note_read(iigs *m, iigs_read_site *sites, unsigned *count,
                      uint32_t address)
{
    uint32_t pc = m->opcode_pc;
    unsigned i;
    for (i = 0; i < *count && sites[i].pc != pc; i++)
        ;
    if (i == *count) {
        if (*count == IIGS_READ_SITES) {
            m->counts.read_sites_lost++;
            return;
        }
        sites[i] = (iigs_read_site){ pc, address, address, 0 };
        (*count)++;
    }
    if (address < sites[i].first)
        sites[i].first = address;
    if (address > sites[i].last)
        sites[i].last = address;
    sites[i].count++;
}

/* Banks $00/$01 and $E0/$E1 at $C000-$CFFF, and banks $00/$01 above
   with the I/O and ROM mapped in. */
static uint8_t low_read(iigs *m, uint32_t address)
{
    uint16_t offset = (uint16_t)address;
    if (offset < 0xc100)
        return io_read(m, (uint8_t)offset);
    /* The one byte of the disk slot's ROM that a loader reads: $CnFF,
       the low byte of the block driver entry. */
    if (offset == (IIGS_DRIVER_ENTRY | 0xff))
        return (uint8_t)IIGS_DRIVER_ENTRY;
    if (offset < 0xd000)
        m->counts.slot_rom_reads++;
    else {
        m->counts.rom_reads++;
        note_read(m, m->counts.rom_read_sites,
                  &m->counts.rom_read_site_count, address);
    }
    return 0;
}

static void low_write(iigs *m, uint16_t offset, uint8_t value)
{
    if (offset < 0xc100)
        io_write(m, (uint8_t)offset, value);
    else
        m->counts.rom_writes++;
}

/* An opcode fetch (VDA and VPA both high): count the instruction, the
   software interrupts and the opcodes that only a CPU running data
   would meet. */
static void opcode_fetched(iigs *m, uint32_t address, uint8_t opcode)
{
    m->instructions++;
    m->opcode = opcode;
    m->opcode_pc = address;
    switch (opcode) {
    case 0x00: case 0x02:
        if (!m->counts.brk && !m->counts.cop)
            m->counts.first_brk_pc = address;
        if (opcode)
            m->counts.cop++;
        else
            m->counts.brk++;
        break;
    case 0x42: m->counts.wdm++; m->odd_opcode = 1; break;
    case 0xdb: m->counts.stp++; m->odd_opcode = 1; break;
    default: break;
    }
}

static uint8_t memory_read(iigs *m, uint32_t address)
{
    unsigned bank = address >> 16;
    uint16_t offset = (uint16_t)address;

    if (bank < IIGS_RAM_BANKS) {
        if (bank < 2 && offset >= 0xc000) {
            if (!(m->shadow & IIGS_SHADOW_IOLC))
                return low_read(m, address);
            if ((m->cpu.bus & CPU816_VPB) && offset == 0xffee)
                m->counts.interrupts++;
        }
        return m->ram[address];
    }
    if (bank == 0xe0 || bank == 0xe1) {
        if (offset >= 0xc000 && offset < 0xd000)
            return low_read(m, address);
        return m->mega[(address - 0xe00000)];
    }
    m->counts.unmapped_reads++;
    note_read(m, m->counts.unmapped_read_sites,
              &m->counts.unmapped_read_site_count, address);
    return 0;
}

static uint8_t bus_read(void *context, uint32_t address)
{
    iigs *m = context;
    uint8_t value = memory_read(m, address);
    if ((m->cpu.bus & (CPU816_VDA | CPU816_VPA)) ==
        (CPU816_VDA | CPU816_VPA))
        opcode_fetched(m, address, value);
    return value;
}

uint32_t iigs_shadow_target(const iigs *m, uint32_t address)
{
    unsigned bank = (address >> 16) & 0xff;
    uint16_t offset = (uint16_t)address;
    uint8_t inhibit = m->shadow;
    int copy;

    if (bank >= 2)
        return IIGS_NO_SHADOW;
    if (offset >= 0x0400 && offset < 0x0800)
        copy = !(inhibit & IIGS_SHADOW_TEXT1);
    else if (offset >= 0x0800 && offset < 0x0c00)
        copy = !(inhibit & IIGS_SHADOW_TEXT2);
    else if (offset >= 0x2000 && offset < 0xa000) {
        int hires = bank == 0 || !(inhibit & IIGS_SHADOW_AUX_HIRES);
        copy = (bank == 1 && !(inhibit & IIGS_SHADOW_SHR)) ||
               (hires && offset < 0x4000 && !(inhibit & IIGS_SHADOW_HIRES1)) ||
               (hires && offset >= 0x4000 && offset < 0x6000 &&
                !(inhibit & IIGS_SHADOW_HIRES2));
    } else
        copy = 0;
    return copy ? 0xe00000u | (uint32_t)bank << 16 | offset : IIGS_NO_SHADOW;
}

static void bus_write(void *context, uint32_t address, uint8_t value)
{
    iigs *m = context;
    unsigned bank = address >> 16;
    uint16_t offset = (uint16_t)address;

    if (bank < IIGS_RAM_BANKS) {
        if (bank < 2) {
            if (offset >= 0xc000 && !(m->shadow & IIGS_SHADOW_IOLC)) {
                low_write(m, offset, value);
                return;
            }
            uint32_t copy = iigs_shadow_target(m, address);
            if (copy != IIGS_NO_SHADOW)
                m->mega[copy - 0xe00000u] = value;
        }
        m->ram[address] = value;
        return;
    }
    if (bank == 0xe0 || bank == 0xe1) {
        if (offset >= 0xc000 && offset < 0xd000)
            low_write(m, offset, value);
        else
            m->mega[address - 0xe00000] = value;
        return;
    }
    m->counts.unmapped_writes++;
}

uint8_t iigs_peek(const iigs *m, uint32_t address)
{
    unsigned bank = (address >> 16) & 0xff;
    if (bank < IIGS_RAM_BANKS)
        return m->ram[address & 0xffffff];
    if (bank == 0xe0 || bank == 0xe1)
        return m->mega[(address & 0xffffff) - 0xe00000];
    return 0;
}

int iigs_load(iigs *m, uint32_t address, const uint8_t *data, size_t length)
{
    for (size_t i = 0; i < length; i++) {
        uint32_t at = (uint32_t)(address + i);
        unsigned bank = at >> 16;
        if (bank < IIGS_RAM_BANKS)
            m->ram[at] = data[i];
        else if (bank == 0xe0 || bank == 0xe1)
            m->mega[at - 0xe00000] = data[i];
        else
            return 0;
    }
    return 1;
}

/* ---- the slot firmware ---- */

/* Bank 0 through the memory map, as the firmware would access it. */
static uint8_t read0(iigs *m, uint16_t address)
{
    return memory_read(m, address);
}

static uint16_t read0_word(iigs *m, uint16_t address)
{
    return (uint16_t)(read0(m, address) | read0(m, (uint16_t)(address + 1))
                      << 8);
}

/* Pull the return address of the JSR that reached the firmware. */
static uint16_t pull_return(iigs *m)
{
    cpu816 *c = &m->cpu;
    uint16_t address = 0;
    for (int i = 0; i < 2; i++) {
        c->s = c->e ? (uint16_t)(STACK_PAGE | ((c->s + 1) & 0xff))
                    : (uint16_t)(c->s + 1);
        address |= (uint16_t)(read0(m, c->s) << (8 * i));
    }
    return address;
}

/* One block between the disk and bank 0; 0 for a block past the end. */
static int transfer(iigs *m, uint32_t block, uint16_t buffer, int write)
{
    if (block >= m->disk_blocks)
        return 0;
    uint8_t *data = m->disk + (size_t)block * BLOCK;
    for (unsigned i = 0; i < BLOCK; i++) {
        uint16_t at = (uint16_t)(buffer + i);
        if (write)
            data[i] = read0(m, at);
        else
            bus_write(m, at, data[i]);
    }
    if (write)
        m->disk_written = 1;
    return 1;
}

static uint8_t driver_call(iigs *m)
{
    cpu816 *c = &m->cpu;
    uint8_t command = read0(m, PD_COMMAND);
    uint16_t buffer = read0_word(m, PD_BUFFER);
    uint16_t block = read0_word(m, PD_BLOCK);

    m->counts.driver_calls++;
    if (read0(m, PD_UNIT) != IIGS_DISK_UNIT)
        return ERR_NO_DEVICE;
    switch (command) {
    case 0:
        c->x = (uint16_t)(m->disk_blocks & 0xff);
        c->y = (uint16_t)((m->disk_blocks >> 8) & 0xff);
        return 0;
    case 1: case 2:
        return transfer(m, block, buffer, command == 2) ? 0 : ERR_IO;
    case 3:
        return 0;
    default:
        return ERR_BAD_COMMAND;
    }
}

static void status_list(iigs *m, uint16_t list, uint8_t code)
{
    uint8_t dib[DIB_LENGTH] = { SP_STATUS_BYTE };
    static const char name[] = "REF816 DISK";

    dib[1] = (uint8_t)m->disk_blocks;
    dib[2] = (uint8_t)(m->disk_blocks >> 8);
    dib[3] = (uint8_t)(m->disk_blocks >> 16);
    dib[4] = (uint8_t)(sizeof name - 1);
    memset(dib + DIB_NAME, ' ', 16);
    memcpy(dib + DIB_NAME, name, sizeof name - 1);
    dib[DIB_TYPE] = SP_TYPE_HARD_DISK;
    unsigned length = code == SP_CODE_DIB ? DIB_LENGTH : 4;
    for (unsigned i = 0; i < length; i++)
        bus_write(m, (uint16_t)(list + i), dib[i]);
    m->cpu.x = (uint16_t)length;
    m->cpu.y = 0;
}

/* The game makes STATUS calls (code 0, the status byte; code 3, the
   device information block) and CONTROL code 4 (eject); other commands
   are refused. */
static uint8_t smartport_call(iigs *m, uint8_t command, uint16_t params)
{
    uint8_t unit = read0(m, (uint16_t)(params + 1));
    uint16_t list = read0_word(m, (uint16_t)(params + 2));
    uint8_t code = read0(m, (uint16_t)(params + 4));

    m->counts.smartport_calls++;
    if (unit != SP_UNIT)
        return ERR_NO_DEVICE;
    switch (command) {
    case SP_STATUS:
        if (code != SP_CODE_STATUS && code != SP_CODE_DIB)
            return ERR_BAD_CODE;
        status_list(m, list, code);
        return 0;
    case SP_CONTROL:
        return 0;               /* eject and the rest: nothing to do */
    default:
        return ERR_BAD_COMMAND;
    }
}

/* The CPU is at a firmware entry: do the call and return as its RTS
   would, with the error in A and the carry. */
static void firmware_call(iigs *m)
{
    cpu816 *c = &m->cpu;
    uint16_t back = pull_return(m);
    uint8_t error;

    if (c->pc == IIGS_DRIVER_ENTRY) {
        error = driver_call(m);
        c->pc = (uint16_t)(back + 1);
    } else {
        uint8_t command = read0(m, (uint16_t)(back + 1));
        uint16_t params = read0_word(m, (uint16_t)(back + 2));
        error = smartport_call(m, command, params);
        c->pc = (uint16_t)(back + 4);
    }
    if (error)
        m->counts.firmware_errors++;
    c->a = (uint16_t)((c->a & 0xff00) | error);
    c->p = (uint8_t)((c->p & ~(CPU816_C | CPU816_Z | CPU816_N)) |
                     (error ? CPU816_C : CPU816_Z));
    c->cycles += IIGS_FIRMWARE_CYCLES;
    m->counts.firmware_cycles += IIGS_FIRMWARE_CYCLES;
}

static int at_firmware(const iigs *m)
{
    return (m->cpu.pc == IIGS_DRIVER_ENTRY ||
            m->cpu.pc == IIGS_SMARTPORT_ENTRY) &&
           m->cpu.pbr == 0 && !(m->shadow & IIGS_SHADOW_IOLC);
}

void iigs_attach_disk(iigs *m, uint8_t *data, size_t length)
{
    m->disk = data;
    m->disk_blocks = (uint32_t)(length / BLOCK);
}

/* ---- the machine ---- */

int iigs_init(iigs *m)
{
    memset(m, 0, sizeof *m);
    m->ram = calloc(IIGS_RAM_BANKS, IIGS_BANK);
    m->mega = calloc(2, IIGS_BANK);
    if (!m->ram || !m->mega) {
        iigs_free(m);
        return 0;
    }
    cpu816_init(&m->cpu, bus_read, bus_write, m);
    m->shadow = IIGS_SHADOW_SHR;
    m->speed = 0x80;
    /* iigs_set_cpu_hz reads the clock, which divides by clock_den. */
    m->clock_den = 1;
    iigs_set_cpu_hz(m, 0);
    doc_init(&m->doc, 0);
    adb_init(&m->adb, 0);
    events(m, 0);
    return 1;
}

void iigs_free(iigs *m)
{
    free(m->ram);
    free(m->mega);
    free(m->breaks);
    m->ram = m->mega = m->breaks = NULL;
}

void iigs_set_switches(iigs *m, uint8_t newvideo, uint8_t border,
                       uint8_t shadow, uint8_t speed)
{
    m->newvideo = newvideo;
    m->border = border;
    m->shadow = shadow;
    set_speed(m, speed);
}

int iigs_set_break(iigs *m, uint32_t address)
{
    if (!m->breaks && !(m->breaks = calloc(1u << 21, 1)))
        return 0;
    address &= 0xffffff;
    m->breaks[address >> 3] |= (uint8_t)(1u << (address & 7));
    return 1;
}

static int at_break(const iigs *m, uint32_t pc)
{
    return m->breaks && (m->breaks[pc >> 3] >> (pc & 7) & 1);
}

/* The instruction just executed left PC where it was: a branch or jump
   to itself. MVN and MVP go back to themselves for each byte, and a
   CPU in WAI or STP stays put without executing anything. */
static int spun(const iigs *m, uint32_t pc)
{
    const cpu816 *c = &m->cpu;
    return ((uint32_t)c->pbr << 16 | c->pc) == pc &&
           c->state == CPU816_RUNNING && m->opcode != 0x54 &&
           m->opcode != 0x44;
}

iigs_stop iigs_run(iigs *m, uint64_t cycle_limit, uint64_t frame_limit)
{
    m->odd_opcode = 0;
    while (m->cpu.cycles < cycle_limit && m->frame < frame_limit) {
        uint32_t pc = (uint32_t)m->cpu.pbr << 16 | m->cpu.pc;
        if (at_break(m, pc) && !m->break_passed) {
            m->break_passed = 1;
            return IIGS_BREAK;
        }
        m->break_passed = 0;
        if (at_firmware(m))
            firmware_call(m);
        else
            cpu816_step(&m->cpu);
        if (m->after_step)
            m->after_step(m->step_context);
        uint64_t now = iigs_clock(m);
        if (now >= m->next_event)
            events(m, now);
        if (m->stop_on_fault && m->odd_opcode) {
            m->odd_opcode = 0;
            return IIGS_ODD_OPCODE;
        }
        if (m->stop_on_fault && spun(m, pc))
            return IIGS_SPIN;
    }
    return IIGS_LIMIT;
}

uint64_t iigs_ram_hash(const iigs *m)
{
    uint64_t hash = 0xcbf29ce484222325u;
    const uint64_t prime = 0x100000001b3u;
    for (size_t i = 0; i < (size_t)IIGS_RAM_BANKS * IIGS_BANK; i++)
        hash = (hash ^ m->ram[i]) * prime;
    for (size_t i = 0; i < 2 * (size_t)IIGS_BANK; i++)
        hash = (hash ^ m->mega[i]) * prime;
    return hash;
}
