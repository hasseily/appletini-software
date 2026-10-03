/* gtrace: the tic phase's call traffic, from a2vm's write log (docs/speed-
   parts/place.md). GPL-2, the port's own.

   a2vm --write-log (tools/a2vm/README.md, "The write log") gives every
   CPU write to the ranges asked for, with the PC of its instruction. With
   the stack page, SLOT_GRP, FC_T, FC_GRP and G_GAMETIC logged, the calls
   of the tic image are seen without any change to the machine:

   - a JSR is the two writes of one instruction at S and S - 1 with the
     values PC + 2 (an interrupt pushes PC, a BRK a third byte);
   - its target is read in the image's own bytes (the slot's group as
     SLOT_GRP says); fc_call, dc_call and an unknown target (the kernel's
     jsr k_go) are named by FC_T and FC_GRP when fc_go pushes, or when
     dc_call writes FC_T + 1 with FC_GRP 0 (a core entry);
   - a return is seen late: a push at S = a means that every frame whose
     JSR wrote at an address <= a has returned (the stack's discipline), so
     the returns come out in their order, before the next call;
   - gr_load's writes of SLOT_GRP are the loads that happened (the check
     of the model: gsim replays the calls and must find them); a frame
     slot's (slot 3 and up, main $2000-$5FFF: docs/SPEED.md 9) too, and
     fs_restore's $FF there empties it.

   A phase starts at a $FF written to SLOT_GRP + 1 by an "on" PC (the
   kernel's k_tic, the lockstep driver's core_in) and ends at a JSR from an
   "offpc" PC or to an "offt" target (the kernel's next steps, the driver's
   frame and load). Only the phases that start with G_GAMETIC and the
   clock in their windows are written.

   Usage: gtrace MAP EVENTS SUMMARY < write-log
   MAP (text, one item a line):
     slots LO1 LO2 END            the two slots' addresses (hex)
     fslot S LO END               frame slot S's addresses (hex)
     grp G LO LEN FILE OFF        G's bytes (0: always there) at LO
     unit ID G LO HI              [LO, HI) of group G is unit ID
     pages G N                    a load of G copies N pages
     addr NAME HEX                slotgrp fct fcgrp gametic fc_call dc_call
                                  dc_end fc_go fc_ret rt_lo rt_hi
     on LO HI | offpc LO HI | offt ADDR    (hex)
     tic UNIT                     the unit whose calls are the tics
     window FROM TO               gametics (decimal), FROM <= g < TO
     clocks FROM TO               the machine's clocks (decimal), the same
   EVENTS: uint16 triples (op, a, b), little-endian: 0 call (caller,
   callee), 1 return, 2 a phase's start (the slots empty), 3 a load (group,
   slot), 4 the phase's end.
   SUMMARY: a line a phase: written (1) or not (0), start clock, end
   clock, gametic at the start, tics, loads, pages (a phase not written
   counts none; a phase the run's end cuts is neither written nor
   listed); then "# key value" totals. Unit 0 is "outside" (a
   PC the map does not name), unit 1 the core's fixed code. */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXG 128
#define SLOTLEN 0x800
#define MAXS (3 + 16)           /* the W slots 1, 2, the frame slots 3 ..
                                   (glayout.py FRAME_FIRST, FS_MAX) */
#define NONE 0xFFFF
#define MAXF 512
#define MAXR 16

enum { F_NONE, F_PEND, F_REC };

typedef struct { int s, state, caller; } frame;

static uint8_t core_mem[65536], core_known[65536];
static uint16_t core_unit[65536];
static uint8_t *slot_mem[MAXG];
static uint16_t *slot_unit[MAXG];
static int pages[MAXG];
static int slot_lo[MAXS], slot_hi[MAXS], slot_end;
static long a_slotgrp = -1, a_fct = -1, a_fcgrp = -1, a_gametic = -1;
static long a_fc_call = -1, a_dc_call = -1, a_dc_end = -1, a_fc_go = -1,
            a_fc_ret = -1, a_rt_lo = -1, a_rt_hi = -1;
static int on_lo[MAXR], on_hi[MAXR], n_on;
static int off_lo[MAXR], off_hi[MAXR], n_off;
static int offt[MAXR], n_offt;
static int tic_unit = -1;
static long win_from = 0, win_to = 0x7FFFFFFFL;
static uint64_t clk_from = 0, clk_to = UINT64_MAX;

static frame stack[MAXF];
static int depth;
static int on, rec;
static int cur[MAXS];
static int fct, fcgrp;
static uint8_t gt[4];
static FILE *ev;
static uint64_t ph_start, ph_tics, ph_loads, ph_pages;
static long ph_gametic;
static FILE *sum;
static uint64_t n_cut, n_lines, n_jsr, n_calls, n_pend_lost, n_overflow, n_phases,
                n_unknown_unit;

static void fail(const char *what)
{
    fprintf(stderr, "gtrace: %s\n", what);
    exit(2);
}

/* a phase's events wait in buf until its end: a phase the run cut (the
   machine stopped inside it) is not written */
static uint8_t *buf;
static size_t nbuf, capbuf;

static void emit(int op, int a, int b)
{
    if (!rec)
        return;
    if (nbuf + 6 > capbuf) {
        capbuf = capbuf ? 2 * capbuf : 1 << 16;
        buf = realloc(buf, capbuf);
        if (!buf)
            fail("out of memory");
    }
    uint8_t *w = buf + nbuf;
    w[0] = (uint8_t)op;
    w[1] = (uint8_t)(op >> 8);
    w[2] = (uint8_t)a;
    w[3] = (uint8_t)(a >> 8);
    w[4] = (uint8_t)b;
    w[5] = (uint8_t)(b >> 8);
    nbuf += 6;
}

static void flush_phase(void)
{
    if (nbuf && fwrite(buf, 1, nbuf, ev) != nbuf)
        fail("cannot write the events");
    nbuf = 0;
}

static int slot_of(int a)
{
    if (a >= slot_lo[1] && a < slot_lo[2])
        return 1;
    if (a >= slot_lo[2] && a < slot_end)
        return 2;
    for (int s = 3; s < MAXS; s++)
        if (a >= slot_lo[s] && a < slot_hi[s])
            return s;
    return 0;
}

/* the unit at an address with group g in its slot (the core's otherwise) */
static int unit_in(int a, int g)
{
    int s = slot_of(a);
    if (!s)
        return core_unit[a] == NONE ? 0 : core_unit[a];
    if (g < 0 || g >= MAXG || !slot_unit[g])
        return 0;
    uint16_t u = slot_unit[g][a - slot_lo[s]];
    return u == NONE ? 0 : u;
}

static int unit_at(int a)
{
    int s = slot_of(a);
    return unit_in(a, s ? cur[s] : 0);
}

/* the byte at a as the CPU sees it now; -1 when the map does not know */
static int byte_at(int a)
{
    int s = slot_of(a);
    if (s) {
        int g = cur[s];
        if (g < 0 || g >= MAXG || !slot_mem[g])
            return -1;
        return slot_mem[g][a - slot_lo[s]];
    }
    return core_known[a] ? core_mem[a] : -1;
}

static int in(const int *lo, const int *hi, int n, int pc)
{
    for (int i = 0; i < n; i++)
        if (pc >= lo[i] && pc < hi[i])
            return 1;
    return 0;
}

static void pop_to(int a)
{
    while (depth && stack[depth - 1].s <= a) {
        depth--;
        if (stack[depth].state == F_REC)
            emit(1, 0, 0);
        else if (stack[depth].state == F_PEND)
            n_pend_lost++;
    }
}

static void end_phase(uint64_t clock)
{
    if (!on)
        return;
    pop_to(0x1FF);
    emit(4, 0, 0);
    flush_phase();
    fprintf(sum, "%d %" PRIu64 " %" PRIu64 " %ld %" PRIu64 " %" PRIu64
            " %" PRIu64 "\n", rec, ph_start, clock, ph_gametic, ph_tics,
            ph_loads, ph_pages);
    on = rec = 0;
}

static long gametic(void)
{
    return (long)gt[0] | (long)gt[1] << 8 | (long)gt[2] << 16 |
           (long)gt[3] << 24;
}

static void start_phase(uint64_t clock)
{
    end_phase(clock);
    on = 1;
    depth = 0;
    for (int s = 0; s < MAXS; s++)
        cur[s] = 0xFF;
    ph_gametic = gametic();
    rec = ph_gametic >= win_from && ph_gametic < win_to &&
          clock >= clk_from && clock < clk_to;
    if (rec)
        n_phases++;
    ph_start = clock;
    ph_tics = ph_loads = ph_pages = 0;
    emit(2, 0, 0);
}

/* the innermost pending call gets its target; frames above it can only be
   an interrupt's, returned (a recorded call cannot come between a call
   and its target) */
static void resolve(int callee)
{
    int i = depth - 1;
    while (i >= 0 && stack[i].state == F_NONE)
        i--;
    if (i < 0 || stack[i].state != F_PEND)
        return;
    depth = i + 1;
    if (callee == 0)
        n_unknown_unit++;
    frame *f = &stack[depth - 1];
    if (callee >= 2 && callee != f->caller) {
        f->state = F_REC;
        emit(0, f->caller, callee);
        n_calls++;
        if (callee == tic_unit)
            ph_tics++;
    } else
        f->state = F_NONE;
}

static void jsr(int pc, int s, uint64_t clock)
{
    n_jsr++;
    if (in(off_lo, off_hi, n_off, pc)) {
        end_phase(clock);
        return;
    }
    int lo = byte_at((pc + 1) & 0xFFFF), hi = byte_at((pc + 2) & 0xFFFF);
    int t = lo < 0 || hi < 0 ? -1 : lo | hi << 8;
    for (int i = 0; i < n_offt; i++)
        if (t == offt[i]) {
            end_phase(clock);
            return;
        }
    if (depth == MAXF) {
        n_overflow++;
        return;
    }
    frame *f = &stack[depth++];
    f->s = s;
    f->caller = unit_at(pc);
    f->state = F_NONE;
    if (t == a_fc_call || t == a_dc_call ||
            (t < 0 && in(on_lo, on_hi, n_on, pc)))
        f->state = F_PEND;         /* (the kernel's jsr k_go: fc_go names it) */
    else if (t < 0)
        f->state = F_NONE;         /* (an interrupt handler's, the card's) */
    else {
        int callee = unit_at(t);
        if (callee >= 2 && callee != f->caller) {
            f->state = F_REC;
            emit(0, f->caller, callee);
            n_calls++;
            if (callee == tic_unit)
                ph_tics++;
        }
    }
}

static struct { int valid, pc, a, v; } prev;

static void stack_write(int pc, int a, int v, uint64_t clock)
{
    if (pc >= a_fc_go && pc < a_fc_ret) {
        /* fc_go's push of the slot's group: the call's target is FC_T in
           FC_GRP (fc_call's, dc_call's paged entries, the kernel's k_go) */
        pop_to(a);
        resolve(unit_in(fct, fcgrp));
        prev.valid = 0;
        return;
    }
    if (pc >= a_rt_lo && pc < a_rt_hi) {
        prev.valid = 0;
        return;
    }
    int r = (pc + 2) & 0xFFFF;
    if (prev.valid && prev.pc == pc && prev.a == a + 1 &&
            prev.v == r >> 8 && v == (r & 0xFF)) {
        prev.valid = 0;
        jsr(pc, a + 1, clock);
        return;
    }
    pop_to(a);
    prev.valid = 1;
    prev.pc = pc;
    prev.a = a;
    prev.v = v;
}

static unsigned long hexval(const char *s)
{
    return strtoul(s, NULL, 16);
}

static void read_map(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f)
        fail("cannot read the map");
    char line[1024];
    for (int i = 0; i < 65536; i++)
        core_unit[i] = NONE;
    while (fgets(line, sizeof line, f)) {
        char k[32], name[32], file[800];
        unsigned g = 0, lo = 0, hi = 0, id = 0, len = 0, off = 0, n = 0;
        long from = 0, to = 0;
        if (line[0] == '#' || line[0] == '\n')
            continue;
        if (sscanf(line, "%31s", k) != 1)
            continue;
        if (!strcmp(k, "slots")) {
            unsigned a, b, c;
            if (sscanf(line, "%*s %x %x %x", &a, &b, &c) != 3)
                fail("bad slots");
            slot_lo[1] = (int)a;
            slot_lo[2] = (int)b;
            slot_end = (int)c;
            slot_hi[1] = (int)b;
            slot_hi[2] = (int)c;
            if (b - a != SLOTLEN || c - b != SLOTLEN)
                fail("slots of another size");
        } else if (!strcmp(k, "fslot")) {
            unsigned sl, a, c;
            if (sscanf(line, "%*s %u %x %x", &sl, &a, &c) != 3 || sl < 3 ||
                    sl >= MAXS || c <= a || c - a > SLOTLEN)
                fail("bad fslot");
            slot_lo[sl] = (int)a;
            slot_hi[sl] = (int)c;
        } else if (!strcmp(k, "grp")) {
            if (sscanf(line, "%*s %u %x %x %799s %x", &g, &lo, &len, file,
                       &off) != 5 || g >= MAXG)
                fail("bad grp");
            FILE *b = fopen(file, "rb");
            if (!b)
                fail("cannot read a group's bytes");
            uint8_t *data = malloc(len ? len : 1);
            if (!data || fseek(b, (long)off, SEEK_SET) ||
                    fread(data, 1, len, b) != len)
                fail("short group bytes");
            fclose(b);
            if (g == 0) {
                for (unsigned i = 0; i < len && lo + i < 65536; i++) {
                    core_mem[lo + i] = data[i];
                    core_known[lo + i] = 1;
                }
            } else {
                int s = slot_of((int)lo);
                if (!s || lo + len > (unsigned)slot_hi[s])
                    fail("a group outside its slot");
                if (!slot_mem[g])
                    slot_mem[g] = calloc(SLOTLEN, 1);
                memcpy(slot_mem[g] + (lo - (unsigned)slot_lo[s]), data, len);
            }
            free(data);
        } else if (!strcmp(k, "unit")) {
            if (sscanf(line, "%*s %u %u %x %x", &id, &g, &lo, &hi) != 4 ||
                    g >= MAXG || id >= NONE || hi > 65536)
                fail("bad unit");
            for (unsigned a = lo; a < hi; a++) {
                int s = slot_of((int)a);
                if (g == 0)
                    core_unit[a] = (uint16_t)id;
                else if (s) {
                    if (!slot_unit[g]) {
                        slot_unit[g] = malloc(SLOTLEN * sizeof(uint16_t));
                        for (int i = 0; i < SLOTLEN; i++)
                            slot_unit[g][i] = NONE;
                    }
                    slot_unit[g][a - (unsigned)slot_lo[s]] = (uint16_t)id;
                }
            }
        } else if (!strcmp(k, "pages")) {
            if (sscanf(line, "%*s %u %u", &g, &n) != 2 || g >= MAXG)
                fail("bad pages");
            pages[g] = (int)n;
        } else if (!strcmp(k, "addr")) {
            unsigned v;
            if (sscanf(line, "%*s %31s %x", name, &v) != 2)
                fail("bad addr");
            long *p = !strcmp(name, "slotgrp") ? &a_slotgrp :
                      !strcmp(name, "fct") ? &a_fct :
                      !strcmp(name, "fcgrp") ? &a_fcgrp :
                      !strcmp(name, "gametic") ? &a_gametic :
                      !strcmp(name, "fc_call") ? &a_fc_call :
                      !strcmp(name, "dc_call") ? &a_dc_call :
                      !strcmp(name, "dc_end") ? &a_dc_end :
                      !strcmp(name, "fc_go") ? &a_fc_go :
                      !strcmp(name, "fc_ret") ? &a_fc_ret :
                      !strcmp(name, "rt_lo") ? &a_rt_lo :
                      !strcmp(name, "rt_hi") ? &a_rt_hi : NULL;
            if (!p)
                fail("unknown addr");
            *p = (long)v;
        } else if (!strcmp(k, "on") || !strcmp(k, "offpc")) {
            int *l = k[1] == 'n' ? on_lo : off_lo, *h = k[1] == 'n' ? on_hi
                                                                  : off_hi;
            int *n2 = k[1] == 'n' ? &n_on : &n_off;
            if (*n2 == MAXR || sscanf(line, "%*s %x %x", &lo, &hi) != 2)
                fail("bad on/offpc");
            l[*n2] = (int)lo;
            h[(*n2)++] = (int)hi;
        } else if (!strcmp(k, "offt")) {
            if (n_offt == MAXR || sscanf(line, "%*s %x", &lo) != 1)
                fail("bad offt");
            offt[n_offt++] = (int)lo;
        } else if (!strcmp(k, "tic")) {
            if (sscanf(line, "%*s %u", &id) != 1)
                fail("bad tic");
            tic_unit = (int)id;
        } else if (!strcmp(k, "clocks")) {
            unsigned long long cf, ct;
            if (sscanf(line, "%*s %llu %llu", &cf, &ct) != 2)
                fail("bad clocks");
            clk_from = cf;
            clk_to = ct;
        } else if (!strcmp(k, "window")) {
            if (sscanf(line, "%*s %ld %ld", &from, &to) != 2)
                fail("bad window");
            win_from = from;
            win_to = to;
        } else
            fail("unknown map item");
    }
    fclose(f);
    if (a_slotgrp < 0 || a_fct < 0 || a_fcgrp < 0 || a_gametic < 0 ||
            a_fc_call < 0 || a_dc_call < 0 || a_dc_end < 0 || a_fc_go < 0 ||
            a_fc_ret < 0 || a_rt_lo < 0 || a_rt_hi < 0 || !slot_end)
        fail("the map lacks an address");
}

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: gtrace MAP EVENTS SUMMARY < write-log\n");
        return 2;
    }
    for (int s = 0; s < MAXS; s++)
        cur[s] = 0xFF;
    read_map(argv[1]);
    ev = fopen(argv[2], "wb");
    sum = fopen(argv[3], "w");
    if (!ev || !sum)
        fail("cannot write the outputs");
    static char line[512];
    uint64_t clock = 0;
    while (fgets(line, sizeof line, stdin)) {
        if (line[0] != 'w')
            continue;
        n_lines++;
        char *p = line + 2, *e;
        clock = strtoull(p, &e, 10);
        strtoull(e, &e, 10);
        int pc = (int)strtoul(e, &e, 16);
        int a = (int)strtoul(e, &e, 16);
        /* the value written: the last field */
        char *last = strrchr(line, ' ');
        if (!last)
            continue;
        int v = (int)hexval(last + 1);
        if (a >= 0x100 && a < 0x200) {
            if (on)
                stack_write(pc, a, v, clock);
        } else if (a > a_slotgrp && a < a_slotgrp + MAXS) {
            int s = (int)(a - a_slotgrp);
            if (v == 0xFF) {
                if (s == 1 && in(on_lo, on_hi, n_on, pc))
                    start_phase(clock);
                else if (on)
                    cur[s] = 0xFF;
            } else if (on) {
                cur[s] = v;
                ph_loads++;
                ph_pages += (uint64_t)pages[v & (MAXG - 1)];
                emit(3, v, s);
            }
        } else if (a == a_fct || a == a_fct + 1) {
            if (a == a_fct)
                fct = (fct & 0xFF00) | v;
            else {
                fct = (fct & 0xFF) | v << 8;
                if (on && pc >= a_dc_call && pc < a_dc_end && fcgrp == 0)
                    resolve(unit_in(fct, 0));
            }
        } else if (a == a_fcgrp) {
            fcgrp = v;
        } else if (a >= a_gametic && a < a_gametic + 4) {
            gt[a - a_gametic] = (uint8_t)v;
        }
    }
    if (on) {                   /* (cut by the run's end: not written) */
        if (rec)
            n_phases--;
        nbuf = 0;
        n_cut++;
    }
    fprintf(sum, "# cut %" PRIu64 "\n", n_cut);
    fprintf(sum, "# lines %" PRIu64 "\n# jsr %" PRIu64 "\n# calls %" PRIu64
            "\n# phases %" PRIu64 "\n# pending_lost %" PRIu64
            "\n# overflow %" PRIu64 "\n# unknown_target %" PRIu64 "\n",
            n_lines, n_jsr, n_calls, n_phases, n_pend_lost, n_overflow,
            n_unknown_unit);
    if (fclose(ev) || fclose(sum))
        fail("cannot finish the outputs");
    return 0;
}
