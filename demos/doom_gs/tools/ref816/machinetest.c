/*
 * Tests of the minimal IIgs (iigs.c, doc.c, adb.c) on small programs and
 * direct register accesses: the memory map and the shadow register, the
 * clock and the CPU rate, the DOC timer and alarm as the game programs
 * them, the ADB keyboard and mouse sequences, the firmware traps, and
 * what iigs_run stops at: breakpoints, spins and odd opcodes.
 *
 * usage: machinetest     (prints each failed check; exit status 1 if any)
 */
#include "iigs.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;

#define CHECK(test, condition) \
    do { \
        if (!(condition)) { \
            printf("%s: failed: %s (line %d)\n", test, #condition, __LINE__); \
            failures++; \
        } \
    } while (0)

static iigs machine;

/* A machine with the given soft switches and the CPU in native mode at
   $00:1000 with 8-bit A. */
static iigs *fresh(uint8_t shadow)
{
    iigs_free(&machine);
    if (!iigs_init(&machine)) {
        puts("out of memory");
        exit(2);
    }
    iigs_set_switches(&machine, 0xc1, 0, shadow, 0x80);
    cpu816 *c = &machine.cpu;
    c->e = 0;
    c->p = CPU816_M | CPU816_I;
    c->pc = 0x1000;
    c->s = 0x01ff;
    cpu816_normalise(c);
    return &machine;
}

/* The bus as the CPU sees it. */
static uint8_t get(iigs *m, uint32_t address)
{
    return m->cpu.read(m, address);
}

static void put(iigs *m, uint32_t address, uint8_t value)
{
    m->cpu.write(m, address, value);
}

/* Run the code at $00:1000 until the CPU reaches STP. */
static void run(iigs *m, const uint8_t *code, size_t length)
{
    iigs_load(m, 0x001000, code, length);
    for (int i = 0; i < 100000 && m->cpu.state != CPU816_STOPPED; i++)
        iigs_run(m, m->cpu.cycles + 1, UINT64_MAX);
}

/* Let `seconds` of machine time pass with the CPU spinning in bank 2. */
static void wait_seconds(iigs *m, double seconds)
{
    static const uint8_t spin[] = { 0x80, 0xfe };      /* bra * */
    iigs_load(m, 0x020000, spin, sizeof spin);
    m->cpu.pbr = 2;
    m->cpu.pc = 0;
    uint64_t cycles = (uint64_t)(seconds * IIGS_MASTER_HZ *
                                 m->clock_den / m->clock_num);
    iigs_run(m, m->cpu.cycles + cycles, UINT64_MAX);
}

static void test_memory_map(void)
{
    const char *t = "memory map";
    iigs *m = fresh(IIGS_SHADOW_SHR);
    put(m, 0x7fffff, 0x5a);
    CHECK(t, get(m, 0x7fffff) == 0x5a);
    put(m, 0x800000, 0x77);
    CHECK(t, get(m, 0x800000) == 0);
    CHECK(t, m->counts.unmapped_reads == 1 && m->counts.unmapped_writes == 1);
    CHECK(t, get(m, 0xbcff00) == 0);   /* no TransWarp GS firmware */
    put(m, 0xe1d000, 0x12);
    CHECK(t, get(m, 0xe1d000) == 0x12);

    /* I/O and ROM in banks $00/$01 until bit 6 of $C035 is set. */
    put(m, 0x00ffee, 0x34);
    CHECK(t, get(m, 0x00ffee) == 0 && m->counts.rom_writes == 1);
    CHECK(t, get(m, 0x00c035) == IIGS_SHADOW_SHR);
    put(m, 0xe0c035, IIGS_SHADOW_SHR | IIGS_SHADOW_IOLC);
    CHECK(t, m->shadow == (IIGS_SHADOW_SHR | IIGS_SHADOW_IOLC));
    put(m, 0x00ffee, 0x34);
    put(m, 0x01c035, 0x99);
    CHECK(t, get(m, 0x00ffee) == 0x34);
    CHECK(t, get(m, 0x01c035) == 0x99);
    CHECK(t, m->shadow == (IIGS_SHADOW_SHR | IIGS_SHADOW_IOLC));
    CHECK(t, get(m, 0xe0c035) == (IIGS_SHADOW_SHR | IIGS_SHADOW_IOLC));

    /* Registers the model does not have are counted. */
    get(m, 0xe0c068);
    put(m, 0xe0c068, 1);
    CHECK(t, m->counts.io_reads[0x68] == 1 && m->counts.io_writes[0x68] == 1);
    /* No ZipGS: the annunciators answer 0 and are not counted. */
    put(m, 0xe0c05c, 0xff);
    CHECK(t, get(m, 0xe0c05c) == 0 && m->counts.io_reads[0x5c] == 0);
}

/* ROM reads and reads of banks with no memory are kept by the instruction
   that made them, with the addresses it read. */
static void test_read_sites(void)
{
    const char *t = "read sites";
    static const uint8_t code[] = {
        0xaf, 0x00, 0xff, 0xbc,         /* 1000 lda $BCFF00 */
        0xaf, 0x01, 0xff, 0xbc,         /* 1004 lda $BCFF01 */
        0xc2, 0x20,                     /* 1008 rep #$20 */
        0xaf, 0xe0, 0xff, 0x00,         /* 100A lda $00FFE0 (16 bits) */
        0xdb };                         /* 100E stp */
    iigs *m = fresh(IIGS_SHADOW_SHR);
    run(m, code, sizeof code);
    const iigs_counts *n = &m->counts;
    CHECK(t, n->unmapped_reads == 2 && n->unmapped_read_site_count == 2);
    CHECK(t, n->unmapped_read_sites[0].pc == 0x1000 &&
             n->unmapped_read_sites[0].first == 0xbcff00 &&
             n->unmapped_read_sites[0].last == 0xbcff00 &&
             n->unmapped_read_sites[0].count == 1);
    CHECK(t, n->unmapped_read_sites[1].pc == 0x1004 &&
             n->unmapped_read_sites[1].first == 0xbcff01);
    CHECK(t, n->rom_reads == 2 && n->rom_read_site_count == 1);
    CHECK(t, n->rom_read_sites[0].pc == 0x100a &&
             n->rom_read_sites[0].first == 0x00ffe0 &&
             n->rom_read_sites[0].last == 0x00ffe1 &&
             n->rom_read_sites[0].count == 2);
    CHECK(t, n->read_sites_lost == 0);
}

static void test_shadow(void)
{
    const char *t = "shadow";
    iigs *m = fresh(0x3f);              /* everything inhibited */
    put(m, 0x012000, 1);
    put(m, 0x000400, 2);
    CHECK(t, iigs_peek(m, 0xe12000) == 0 && iigs_peek(m, 0xe00400) == 0);

    put(m, 0xe0c035, 0x3f & ~IIGS_SHADOW_SHR);
    put(m, 0x012000, 3);
    put(m, 0x019fff, 4);
    put(m, 0x002000, 5);
    put(m, 0x01a000, 6);
    CHECK(t, iigs_peek(m, 0xe12000) == 3 && iigs_peek(m, 0xe19fff) == 4);
    CHECK(t, iigs_peek(m, 0xe02000) == 0 && iigs_peek(m, 0xe1a000) == 0);
    CHECK(t, iigs_peek(m, 0x012000) == 3);

    put(m, 0xe0c035, 0x3f & ~IIGS_SHADOW_TEXT1);
    put(m, 0x000400, 7);
    put(m, 0x0107ff, 8);
    CHECK(t, iigs_peek(m, 0xe00400) == 7 && iigs_peek(m, 0xe107ff) == 8);

    put(m, 0xe0c035, 0x3f & ~IIGS_SHADOW_HIRES1);
    put(m, 0x002000, 9);
    put(m, 0x012001, 10);
    CHECK(t, iigs_peek(m, 0xe02000) == 9 && iigs_peek(m, 0xe12001) == 0);
}

static void test_clock(void)
{
    const char *t = "clock";
    static const uint8_t slow[] = {
        0xa9, 0x00, 0x8f, 0x36, 0xc0, 0xe0,     /* lda #0 / sta $E0C036 */
        0xea, 0xea, 0xdb };                     /* nop / nop / stp */
    iigs *m = fresh(IIGS_SHADOW_SHR);
    CHECK(t, !iigs_vbl(m));
    run(m, slow, sizeof slow);
    /* 2 + 5 cycles fast, then 2 + 2 + 3 slow (STP spends 3). */
    CHECK(t, m->cpu.cycles == 14);
    CHECK(t, iigs_clock(m) == 7 * 5 + 7 * 14);

    m = fresh(IIGS_SHADOW_SHR);
    wait_seconds(m, 1.0);
    CHECK(t, m->frame == 59);           /* 59.92 frames a second */
    uint64_t line = iigs_clock(m) % IIGS_FRAME_CLOCKS / IIGS_LINE_CLOCKS;
    CHECK(t, iigs_vbl(m) == (line >= IIGS_VBL_LINE));
    CHECK(t, (get(m, 0xe0c019) & 0x80) == (iigs_vbl(m) ? 0x80 : 0));
}

static void test_cpu_rate(void)
{
    const char *t = "CPU rate";
    iigs *m = fresh(IIGS_SHADOW_SHR);
    iigs_set_cpu_hz(m, 12000000);
    CHECK(t, m->clock_num == 715909 && m->clock_den == 600000);
    wait_seconds(m, 1.0);
    CHECK(t, m->cpu.cycles == 12000000);
    CHECK(t, iigs_clock(m) == IIGS_MASTER_HZ);
    CHECK(t, m->frame == 59);

    /* Slow mode keeps its 14 master clocks; fast mode comes back at the
       rate given. */
    uint64_t clock = iigs_clock(m);
    put(m, 0xe0c036, 0x00);
    m->cpu.cycles += 10;
    CHECK(t, iigs_clock(m) == clock + 140);
    put(m, 0xe0c036, 0x80);
    CHECK(t, m->clock_num == 715909 && m->clock_den == 600000);
    iigs_set_cpu_hz(m, 0);
    CHECK(t, m->clock_num == IIGS_FAST_CLOCKS && m->clock_den == 1);
}

/* ---- what iigs_run stops at ---- */

static void test_breakpoints(void)
{
    const char *t = "breakpoints";
    static const uint8_t loop[] = { 0xea, 0x80, 0xfd };  /* nop / bra -3 */
    iigs *m = fresh(IIGS_SHADOW_SHR);
    iigs_load(m, 0x001000, loop, sizeof loop);
    CHECK(t, iigs_set_break(m, 0x001000));
    /* A stop before the first instruction, then once round the loop
       each time, the stop passed over when the caller goes on. */
    CHECK(t, iigs_run(m, 1000, UINT64_MAX) == IIGS_BREAK);
    CHECK(t, m->cpu.pc == 0x1000 && m->instructions == 0);
    CHECK(t, iigs_run(m, 1000, UINT64_MAX) == IIGS_BREAK);
    CHECK(t, m->cpu.pc == 0x1000 && m->instructions == 2);
    CHECK(t, m->cpu.cycles == 2 + 3);
    CHECK(t, iigs_run(m, 1000, UINT64_MAX) == IIGS_BREAK);
    CHECK(t, m->instructions == 4);
    /* A limit met first, then the breakpoint where it left off. */
    m = fresh(IIGS_SHADOW_SHR);
    iigs_load(m, 0x001000, loop, sizeof loop);
    iigs_set_break(m, 0x001001);
    CHECK(t, iigs_run(m, 1, UINT64_MAX) == IIGS_LIMIT);
    CHECK(t, m->cpu.pc == 0x1001);
    CHECK(t, iigs_run(m, 1000, UINT64_MAX) == IIGS_BREAK);
    CHECK(t, m->cpu.pc == 0x1001);
}

static void test_spin(void)
{
    const char *t = "spin";
    static const uint8_t spin[] = { 0x80, 0xfe };        /* bra * */
    /* lda #2 / ldx ##$2000 / ldy ##$3000 / mvn 0,0 / stp: MVN comes back
       to itself for each of its 3 bytes, which is no spin. */
    static const uint8_t move[] = {
        0xa9, 0x02, 0xa2, 0x00, 0x20, 0xa0, 0x00, 0x30,
        0x54, 0x00, 0x00, 0xdb };
    iigs *m = fresh(IIGS_SHADOW_SHR);
    iigs_load(m, 0x001000, spin, sizeof spin);
    CHECK(t, iigs_run(m, 1000, UINT64_MAX) == IIGS_LIMIT);
    m->stop_on_fault = 1;
    CHECK(t, iigs_run(m, 2000, UINT64_MAX) == IIGS_SPIN);
    CHECK(t, m->cpu.pc == 0x1000);

    m = fresh(IIGS_SHADOW_SHR);
    m->stop_on_fault = 1;
    iigs_load(m, 0x002000, (const uint8_t *)"abc", 3);
    iigs_load(m, 0x001000, move, sizeof move);
    CHECK(t, iigs_run(m, 1000, UINT64_MAX) == IIGS_ODD_OPCODE);
    CHECK(t, m->opcode_pc == 0x00100b);
    CHECK(t, iigs_peek(m, 0x003002) == 'c');
    CHECK(t, m->instructions == 3 + 3 + 1);
}

static void test_odd_opcodes(void)
{
    const char *t = "odd opcodes";
    /* BRK goes through the RAM vector to a WDM: BRK is counted, WDM
       stops the run. */
    static const uint8_t code[] = { 0x00, 0x00 };
    static const uint8_t handler[] = { 0x42, 0x00 };
    static const uint8_t vector[] = { 0x00, 0x30 };
    iigs *m = fresh(IIGS_SHADOW_SHR | IIGS_SHADOW_IOLC);
    m->stop_on_fault = 1;
    iigs_load(m, 0x00ffe6, vector, 2);
    iigs_load(m, 0x003000, handler, sizeof handler);
    iigs_load(m, 0x001000, code, sizeof code);
    CHECK(t, iigs_run(m, 1000, UINT64_MAX) == IIGS_ODD_OPCODE);
    CHECK(t, m->counts.brk == 1 && m->counts.first_brk_pc == 0x001000);
    CHECK(t, m->counts.wdm == 1 && m->opcode_pc == 0x003000);
    CHECK(t, m->cpu.pc == 0x3002);
}

/* ---- the DOC, programmed as src/iigs/i_doc65.s does ---- */

static void doc_set(iigs *m, uint8_t reg, uint8_t value)
{
    put(m, 0xe0c03c, 0x00);             /* registers, no increment */
    put(m, 0xe0c03e, reg);
    put(m, 0xe0c03d, value);
}

static uint8_t doc_get(iigs *m, uint8_t reg)
{
    put(m, 0xe0c03c, 0x00);
    put(m, 0xe0c03e, reg);
    get(m, 0xe0c03d);                   /* starts the access */
    return get(m, 0xe0c03d);
}

static void ramp(iigs *m)
{
    put(m, 0xe0c03c, GLU_RAM | GLU_INCREMENT);
    put(m, 0xe0c03e, 0x00);
    put(m, 0xe0c03f, 0xff);
    put(m, 0xe0c03d, 255);
    for (int i = 1; i < 256; i++)
        put(m, 0xe0c03d, (uint8_t)i);
}

static void test_doc_timer(void)
{
    const char *t = "DOC timer";
    iigs *m = fresh(IIGS_SHADOW_SHR);
    ramp(m);
    CHECK(t, m->doc.ram[0xff00] == 255 && m->doc.ram[0xff80] == 0x80);
    doc_set(m, 0xe1, 31 * 2);
    doc_set(m, 31, 87);
    doc_set(m, 0x20 + 31, 0);
    doc_set(m, 0x80 + 31, 0xff);
    doc_set(m, 0xc0 + 31, 0x07);
    doc_set(m, 0xa0 + 31, 0x00);
    CHECK(t, doc_sample_clocks(&m->doc) == 544);

    /* I_GetTime's count of ramp steps over 10 seconds, read every 10 ms.
       The data register holds a ramp byte from the first sample on
       (38 us; the game's first read comes later than that). */
    wait_seconds(m, 0.001);
    uint8_t last = doc_get(m, 0x60 + 31);
    uint32_t steps = 0;
    for (int i = 0; i < 1000; i++) {
        wait_seconds(m, 0.01);
        uint8_t now = doc_get(m, 0x60 + 31);
        steps += (uint8_t)(now - last);
        last = now;
    }
    /* 26,320 samples a second * 87 / 65536 = 34.94 steps a second. */
    CHECK(t, steps >= 348 && steps <= 351);
    CHECK(t, !m->cpu.irq_sources);
}

static void test_doc_alarm(void)
{
    const char *t = "DOC alarm";
    iigs *m = fresh(IIGS_SHADOW_SHR);
    ramp(m);
    doc_set(m, 0xe1, 31 * 2);
    doc_set(m, 30, 249);
    doc_set(m, 0x80 + 30, 0xff);
    doc_set(m, 0xc0 + 30, 0x00);
    doc_set(m, 0xa0 + 30, 0x0a);        /* one-shot, interrupt, running */
    uint64_t start = m->doc.samples;
    while (!m->cpu.irq_sources && m->doc.samples < start + 2000)
        wait_seconds(m, 0.0001);
    /* One pass of 131072 / 249 samples, about 20 ms: the index passes
       the end of the table at the 528th sample; the wait adds up to 3. */
    uint64_t pass = m->doc.samples - start;
    CHECK(t, pass >= 528 && pass <= 531);
    CHECK(t, m->cpu.irq_sources == IIGS_IRQ_DOC);
    CHECK(t, doc_get(m, 0xa0 + 30) & DOC_HALT);
    uint8_t irq = doc_get(m, 0xe0);     /* IIGS_Alarm's double read */
    CHECK(t, !(irq & 0x80) && (irq & 0x3e) == 30 << 1);
    CHECK(t, !m->cpu.irq_sources);

    doc_set(m, 0xa0 + 30, 0x0a);
    wait_seconds(m, 0.03);
    CHECK(t, m->cpu.irq_sources == IIGS_IRQ_DOC);
    put(m, 0xe0c03e, 0xe0);
    get(m, 0xe0c03d);                   /* the handler's one read */
    CHECK(t, !m->cpu.irq_sources);
    CHECK(t, (get(m, 0xe0c03d) & 0xbe) == (30 << 1));
}

static void test_doc_zero_halts(void)
{
    const char *t = "DOC zero byte";
    iigs *m = fresh(IIGS_SHADOW_SHR);
    put(m, 0xe0c03c, GLU_RAM | GLU_INCREMENT);
    put(m, 0xe0c03e, 0x00);
    put(m, 0xe0c03f, 0x10);
    for (int i = 0; i < 8; i++)
        put(m, 0xe0c03d, 0x80);
    put(m, 0xe0c03d, 0x00);
    CHECK(t, m->doc.glu_address == 0x1009);
    doc_set(m, 0xe1, 3 * 2);            /* oscillators 0-3 */
    doc_set(m, 3, 0x00);
    doc_set(m, 0x20 + 3, 0x02);         /* one table byte a sample */
    doc_set(m, 0x80 + 3, 0x10);
    doc_set(m, 0xc0 + 3, 0x00);
    doc_set(m, 0xa0 + 3, 0x02);         /* one-shot, no interrupt */
    wait_seconds(m, 0.01);
    CHECK(t, m->doc.osc[3].control & DOC_HALT);
    CHECK(t, doc_get(m, 0x60 + 3) == 0x80);
    CHECK(t, !m->cpu.irq_sources);
}

/* ---- the ADB, driven as src/iigs/iigs_asm.s does ---- */

static uint8_t adb_status(iigs *m)
{
    return get(m, 0xe0c027);
}

static void adb_command(iigs *m, uint8_t value)
{
    put(m, 0xe0c026, value);
}

static void test_adb_keyboard(void)
{
    const char *t = "ADB keyboard";
    iigs *m = fresh(IIGS_SHADOW_SHR);
    adb_key(&m->adb, 0x35, 1);
    wait_seconds(m, 0.05);
    CHECK(t, !(adb_status(m) & ADB_DATA_FULL));  /* still polled itself */

    adb_command(m, 0x04);               /* set modes: no keyboard poll */
    adb_command(m, 0x01);
    adb_command(m, 0x52);               /* service requests of address 2 */
    put(m, 0xe0c027, ADB_DATA_IRQ | ADB_MOUSE_IRQ);
    wait_seconds(m, 0.02);
    CHECK(t, adb_status(m) & ADB_DATA_FULL);
    CHECK(t, m->cpu.irq_sources == IIGS_IRQ_ADB);
    CHECK(t, get(m, 0xe0c026) == 0x08);
    CHECK(t, !m->cpu.irq_sources);

    adb_key(&m->adb, 0x35, 0);
    adb_key(&m->adb, 0x00, 1);
    adb_command(m, 0xc2);               /* Talk register 0 of address 2 */
    wait_seconds(m, 0.002);
    CHECK(t, !(adb_status(m) & ADB_DATA_FULL));  /* the bus time */
    wait_seconds(m, 0.004);
    CHECK(t, get(m, 0xe0c026) == 0x81);
    CHECK(t, get(m, 0xe0c026) == 0x35);
    CHECK(t, get(m, 0xe0c026) == 0xb5);
    CHECK(t, !(adb_status(m) & ADB_DATA_FULL));

    wait_seconds(m, 0.02);              /* the key still waiting asks */
    CHECK(t, get(m, 0xe0c026) == 0x08);
    adb_command(m, 0xc2);
    wait_seconds(m, 0.006);
    CHECK(t, get(m, 0xe0c026) == 0x81);
    CHECK(t, get(m, 0xe0c026) == 0x00);
    CHECK(t, get(m, 0xe0c026) == 0xff);
    adb_command(m, 0xc2);               /* nothing left */
    wait_seconds(m, 0.006);
    CHECK(t, get(m, 0xe0c026) == 0x80);
    CHECK(t, !(adb_status(m) & ADB_DATA_FULL));
    CHECK(t, m->adb.unknown_commands == 0);
    adb_command(m, 0x0d);
    CHECK(t, m->adb.unknown_commands == 1 && m->adb.last_unknown == 0x0d);
}

static void test_adb_mouse(void)
{
    const char *t = "ADB mouse";
    iigs *m = fresh(IIGS_SHADOW_SHR);
    put(m, 0xe0c027, ADB_MOUSE_IRQ);
    adb_mouse_move(&m->adb, 100, -3);
    adb_mouse_button(&m->adb, 0, 1);
    wait_seconds(m, 0.012);
    CHECK(t, adb_status(m) & ADB_MOUSE_FULL);
    CHECK(t, m->cpu.irq_sources == IIGS_IRQ_ADB);
    CHECK(t, !(adb_status(m) & ADB_MOUSE_Y_NEXT));
    CHECK(t, get(m, 0xe0c024) == (0x80 | 63));   /* button 1 up, +63 */
    CHECK(t, adb_status(m) & ADB_MOUSE_Y_NEXT);
    CHECK(t, get(m, 0xe0c024) == (0x7f & -3));   /* button 0 down, -3 */
    CHECK(t, !(adb_status(m) & ADB_MOUSE_FULL));
    CHECK(t, !m->cpu.irq_sources);
    wait_seconds(m, 0.012);             /* the rest of the move */
    CHECK(t, get(m, 0xe0c024) == (0x80 | 37));
    CHECK(t, get(m, 0xe0c024) == 0x00);
    wait_seconds(m, 0.05);
    CHECK(t, !(adb_status(m) & ADB_MOUSE_FULL));  /* nothing new */
}

/* ---- the firmware traps ---- */

static void test_block_driver(void)
{
    const char *t = "block driver";
    static uint8_t disk[4 * 512];
    /* In emulation mode: read block 2 to $7A00, then write it to
       block 3, then read block 9 (past the end); keep each carry. */
    static const uint8_t code[] = {
        0x38, 0xfb,                     /* sec / xce */
        0xa9, 0x70, 0x85, 0x43,         /* lda #$70 / sta $43 (unit) */
        0xa9, 0x00, 0x85, 0x44,         /* buffer $7A00 */
        0xa9, 0x7a, 0x85, 0x45,
        0xa9, 0x02, 0x85, 0x46,         /* block 2 */
        0x64, 0x47,
        0xa9, 0x01, 0x85, 0x42,         /* READ */
        0x20, 0x0a, 0xc7,               /* jsr $C70A */
        0x08,                           /* php */
        0xa9, 0x03, 0x85, 0x46,         /* block 3 */
        0xa9, 0x02, 0x85, 0x42,         /* WRITE */
        0x20, 0x0a, 0xc7,
        0x08,
        0xa9, 0x09, 0x85, 0x46,         /* block 9 */
        0xa9, 0x01, 0x85, 0x42,
        0x20, 0x0a, 0xc7,
        0x08,
        0x8d, 0x00, 0x20,               /* sta $2000: the error */
        0xdb };                         /* stp */
    for (int i = 0; i < 512; i++)
        disk[2 * 512 + i] = (uint8_t)(i * 7);
    iigs *m = fresh(IIGS_SHADOW_SHR);
    iigs_attach_disk(m, disk, sizeof disk);
    run(m, code, sizeof code);
    CHECK(t, m->cpu.state == CPU816_STOPPED);
    CHECK(t, iigs_peek(m, 0x7a00 + 511) == (uint8_t)(511 * 7));
    CHECK(t, disk[3 * 512 + 100] == (uint8_t)(100 * 7) && m->disk_written);
    CHECK(t, !(iigs_peek(m, 0x01ff) & CPU816_C));
    CHECK(t, !(iigs_peek(m, 0x01fe) & CPU816_C));
    CHECK(t, iigs_peek(m, 0x01fd) & CPU816_C);
    CHECK(t, iigs_peek(m, 0x2000) == 0x27);
    CHECK(t, m->counts.driver_calls == 3 && m->counts.firmware_errors == 1);
    CHECK(t, m->counts.firmware_cycles == 3 * IIGS_FIRMWARE_CYCLES);
    CHECK(t, m->cpu.s == 0x01fc);
}

static void test_smartport(void)
{
    const char *t = "SmartPort";
    static uint8_t disk[1600 * 512];
    /* STATUS code 3 (the DIB) of unit 1 into $0300, then CONTROL code 4
       (eject), from emulation mode with the parameters in line. */
    static const uint8_t code[] = {
        0x38, 0xfb,                     /* sec / xce */
        0x20, 0x0d, 0xc7, 0x00, 0x00, 0x11,     /* jsr $C70D: STATUS */
        0x08,                           /* php */
        0x20, 0x0d, 0xc7, 0x04, 0x10, 0x11,     /* CONTROL */
        0x08,
        0xdb };
    static const uint8_t status_params[] = { 3, 1, 0x00, 0x03, 3 };
    static const uint8_t control_params[] = { 3, 1, 0x00, 0x03, 4 };
    iigs *m = fresh(IIGS_SHADOW_SHR);
    iigs_attach_disk(m, disk, sizeof disk);
    iigs_load(m, 0x1100, status_params, sizeof status_params);
    iigs_load(m, 0x1110, control_params, sizeof control_params);
    run(m, code, sizeof code);
    CHECK(t, m->cpu.state == CPU816_STOPPED);
    CHECK(t, iigs_peek(m, 0x0300) == 0xf8);
    CHECK(t, iigs_peek(m, 0x0301) == (1600 & 0xff));
    CHECK(t, iigs_peek(m, 0x0302) == (1600 >> 8));
    CHECK(t, iigs_peek(m, 0x0300 + 21) == 0x02);         /* a hard disk */
    CHECK(t, !(iigs_peek(m, 0x01ff) & CPU816_C));
    CHECK(t, !(iigs_peek(m, 0x01fe) & CPU816_C));
    CHECK(t, m->counts.smartport_calls == 2);

    /* With the I/O space turned off the entry is plain RAM: no trap. */
    static const uint8_t off[] = {
        0xa9, 0x40, 0x8f, 0x35, 0xc0, 0xe0,     /* lda #$40 / sta $E0C035 */
        0x20, 0x0d, 0xc7 };                     /* jsr $C70D */
    static const uint8_t landing[] = { 0xdb };
    m = fresh(IIGS_SHADOW_SHR);
    iigs_load(m, IIGS_SMARTPORT_ENTRY, landing, 1);
    run(m, off, sizeof off);
    CHECK(t, m->cpu.pc == IIGS_SMARTPORT_ENTRY + 1);
    CHECK(t, m->counts.smartport_calls == 0);
}

static void test_interrupt_vector(void)
{
    const char *t = "RAM vectors";
    /* With the I/O and ROM off, an IRQ takes the native vector from RAM
       at $00:FFEE. */
    static const uint8_t code[] = { 0x58, 0x80, 0xfe };     /* cli / bra * */
    static const uint8_t handler[] = { 0xdb };
    static const uint8_t vector[] = { 0x00, 0x30 };
    iigs *m = fresh(IIGS_SHADOW_SHR | IIGS_SHADOW_IOLC);
    iigs_load(m, 0x00ffee, vector, 2);
    iigs_load(m, 0x003000, handler, 1);
    put(m, 0xe0c027, ADB_MOUSE_IRQ);
    adb_mouse_move(&m->adb, 1, 0);
    run(m, code, sizeof code);
    CHECK(t, m->cpu.pc == 0x3001);
    CHECK(t, m->counts.interrupts == 1);
}

int main(void)
{
    test_memory_map();
    test_read_sites();
    test_shadow();
    test_clock();
    test_cpu_rate();
    test_doc_timer();
    test_doc_alarm();
    test_doc_zero_halts();
    test_adb_keyboard();
    test_adb_mouse();
    test_block_driver();
    test_smartport();
    test_interrupt_vector();
    test_breakpoints();
    test_spin();
    test_odd_opcodes();
    iigs_free(&machine);
    if (failures) {
        printf("%d checks failed\n", failures);
        return 1;
    }
    puts("machinetest: all checks passed");
    return 0;
}
