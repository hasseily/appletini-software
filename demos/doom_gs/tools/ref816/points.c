/*
 * Points of a run: see points.h.
 */
#include "points.h"

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { TEXT = 1024 };

static int problem(char *error, size_t size, const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(error, size, format, arguments);
    va_end(arguments);
    return 0;
}

/* The next part of the text at `*cursor`, up to `separator` (cut
   there), or NULL at the end. */
static char *next_part(char **cursor, char separator)
{
    char *part = *cursor;
    if (!part)
        return NULL;
    char *end = strchr(part, separator);
    if (end) {
        *end = 0;
        *cursor = end + 1;
    } else
        *cursor = NULL;
    return part;
}

static int in_ram(uint64_t address)
{
    unsigned bank = (unsigned)(address >> 16);
    return bank < IIGS_RAM_BANKS || bank == 0xe0 || bank == 0xe1;
}

/* A whole number of `text` (0x for hex when base is 0). */
static int number(const char *text, int base, uint64_t maximum,
                  uint64_t *value)
{
    char *end;
    if (!text[0] || text[0] == '-' || text[0] == '+')
        return 0;
    errno = 0;
    unsigned long long parsed = strtoull(text, &end, base);
    if (errno || end == text || *end || parsed > maximum)
        return 0;
    *value = parsed;
    return 1;
}

/* SET: N, N-M, N-M/K, N-/K or all. */
static int parse_set(point_set *s, const char *text)
{
    char buffer[TEXT];
    if (!strcmp(text, "all")) {
        *s = (point_set){ 0, UINT64_MAX, 1 };
        return 1;
    }
    if (strlen(text) >= sizeof buffer)
        return 0;
    strcpy(buffer, text);
    char *slash = strchr(buffer, '/'), *dash = strchr(buffer, '-');
    uint64_t every = 1;
    if (slash) {
        *slash = 0;
        if (!dash || !number(slash + 1, 0, UINT64_MAX, &every) || !every)
            return 0;
    }
    uint64_t first, last;
    if (dash) {
        *dash = 0;
        if (!number(buffer, 0, UINT64_MAX - 1, &first))
            return 0;
        if (!dash[1])
            last = UINT64_MAX;
        else if (!number(dash + 1, 0, UINT64_MAX - 1, &last) || last < first)
            return 0;
    } else {
        if (!number(buffer, 0, UINT64_MAX - 1, &first))
            return 0;
        last = first;
    }
    *s = (point_set){ first, last, every };
    return 1;
}

int point_set_has(const point_set *set, uint64_t value)
{
    return value >= set->first && value <= set->last &&
           (value - set->first) % set->every == 0;
}

uint64_t point_set_next(const point_set *set, uint64_t value)
{
    if (value <= set->first)
        return set->first;
    if (value > set->last)
        return UINT64_MAX;
    uint64_t steps = (value - set->first + set->every - 1) / set->every;
    if (steps > (UINT64_MAX - set->first) / set->every)
        return UINT64_MAX;
    uint64_t next = set->first + steps * set->every;
    return next <= set->last ? next : UINT64_MAX;
}

/* if=ADDR:SIZE:TEST:VALUE */
static int parse_test(point *p, const char *text, char *error, size_t size)
{
    static const char *names[] = { "eq", "ne", "lt", "le", "gt", "ge" };
    char buffer[TEXT];
    char *parts[4];
    if (strlen(text) >= sizeof buffer)
        return problem(error, size, "if: too long");
    strcpy(buffer, text);
    parts[0] = buffer;
    for (int i = 1; i < 4; i++) {
        char *colon = strchr(parts[i - 1], ':');
        if (!colon)
            return problem(error, size, "if takes ADDR:SIZE:TEST:VALUE");
        *colon = 0;
        parts[i] = colon + 1;
    }
    uint64_t address, width, value;
    if (!number(parts[0], 16, 0xffffff, &address) ||
        !number(parts[1], 10, 4, &width) ||
        (width != 1 && width != 2 && width != 4) ||
        !number(parts[3], 0, UINT32_MAX, &value))
        return problem(error, size, "if takes ADDR:SIZE:TEST:VALUE: a hex "
                       "address, a size of 1, 2 or 4 and a number");
    if (!in_ram(address) || !in_ram(address + width - 1))
        return problem(error, size, "if: $%06llX is not in RAM",
                       (unsigned long long)address);
    if (width < 4 && value >> (8 * width))
        return problem(error, size, "if: %s does not fit in %u bytes",
                       parts[3], (unsigned)width);
    p->test = POINT_ALWAYS;
    for (unsigned i = 0; i < sizeof names / sizeof *names; i++)
        if (!strcmp(parts[2], names[i]))
            p->test = (point_test)(POINT_EQ + i);
    if (p->test == POINT_ALWAYS)
        return problem(error, size, "if tests eq, ne, lt, le, gt or ge, "
                       "not %s", parts[2]);
    p->test_address = (uint32_t)address;
    p->test_size = (unsigned)width;
    p->test_value = (uint32_t)value;
    return 1;
}

/* One range of ranges=: BB, BB-BB or ADDR:LEN. */
static int parse_range(point *p, const char *text, char *error, size_t size)
{
    char buffer[TEXT];
    uint64_t address, length, first, last;
    if (p->range_count == POINT_RANGES)
        return problem(error, size, "ranges: at most %d", POINT_RANGES);
    if (strlen(text) >= sizeof buffer)
        return problem(error, size, "ranges: too long");
    strcpy(buffer, text);
    char *colon = strchr(buffer, ':'), *dash = strchr(buffer, '-');
    if (colon) {
        *colon = 0;
        if (!number(buffer, 16, 0xffffff, &address) ||
            !number(colon + 1, 0, 0x1000000, &length) || !length)
            return problem(error, size, "ranges: %s is not ADDR:LEN", text);
    } else {
        if (dash)
            *dash = 0;
        if (!number(buffer, 16, 0xff, &first) ||
            (dash && !number(dash + 1, 16, 0xff, &last)))
            return problem(error, size, "ranges: %s is not a bank or banks",
                           text);
        if (!dash)
            last = first;
        if (last < first)
            return problem(error, size, "ranges: %s goes down", text);
        address = first << 16;
        length = (last - first + 1) << 16;
    }
    for (uint64_t a = address; a < address + length; a = (a | 0xffff) + 1)
        if (!in_ram(a))
            return problem(error, size, "ranges: %s is not all RAM", text);
    if (!in_ram(address + length - 1))
        return problem(error, size, "ranges: %s is not all RAM", text);
    p->range_address[p->range_count] = (uint32_t)address;
    p->range_length[p->range_count++] = (uint32_t)length;
    return 1;
}

int point_item(point *p, const char *key, const char *value, point_use use,
               int *known, char *error, size_t size)
{
    *known = 1;
    if (!strcmp(key, "hits")) {
        if (p->kind != POINT_PC)
            return problem(error, size, "hits goes with pc only");
        if (!parse_set(&p->set, value))
            return problem(error, size, "hits takes N, N-M, N-M/K, N-/K "
                           "or all, not %s", value);
        if (!p->set.first)
            return problem(error, size, "hits count from 1");
        return 1;
    }
    if (!strcmp(key, "after")) {
        if (!value[0] || strlen(value) >= POINT_NAME)
            return problem(error, size, "after takes a note's name");
        strcpy(p->after, value);
        p->after_seen = 0;
        return 1;
    }
    if (!strcmp(key, "if"))
        return parse_test(p, value, error, size);
    if (!strcmp(key, "ranges") && use == POINT_FOR_DUMP) {
        char buffer[TEXT];
        if (strlen(value) >= sizeof buffer)
            return problem(error, size, "ranges: too long");
        strcpy(buffer, value);
        char *cursor = buffer, *part;
        while ((part = next_part(&cursor, '+')))
            if (!parse_range(p, part, error, size))
                return 0;
        if (!p->range_count)
            return problem(error, size, "ranges takes R+R...");
        return 1;
    }
    *known = 0;
    return 1;
}

int point_parse(point *p, const char *text, point_use use, char *error,
                size_t size)
{
    char buffer[TEXT];
    memset(p, 0, sizeof *p);
    p->kind = POINT_PC;
    p->set = (point_set){ 1, UINT64_MAX, 1 };
    p->after_seen = 1;
    if (strlen(text) >= sizeof buffer)
        return problem(error, size, "%.40s...: too long", text);
    strcpy(buffer, text);
    int first = 1;
    char *cursor = buffer[0] || use != POINT_FOR_CALL ? buffer : NULL;
    char *item;
    for (; (item = next_part(&cursor, ',')); first = 0) {
        char *equals = strchr(item, '=');
        if (!equals)
            return problem(error, size, "%s: %s is not KEY=VALUE", text,
                           item);
        *equals = 0;
        const char *key = item, *value = equals + 1;
        if (first && use != POINT_FOR_CALL) {
            if (!strcmp(key, "pc")) {
                uint64_t pc;
                if (!number(value, 16, 0xffffff, &pc))
                    return problem(error, size, "%s: pc takes a 24-bit hex "
                                   "address", text);
                p->pc = (uint32_t)pc;
            } else if (!strcmp(key, "frame") || !strcmp(key, "cycle")) {
                p->kind = key[0] == 'f' ? POINT_FRAME : POINT_CYCLE;
                if (!parse_set(&p->set, value))
                    return problem(error, size, "%s: %s takes N, N-M, "
                                   "N-M/K, N-/K or all", text, key);
            } else
                return problem(error, size, "%s: a point starts with pc=, "
                               "frame= or cycle=", text);
            continue;
        }
        int known;
        if (!point_item(p, key, value, use, &known, error, size))
            return 0;
        if (!known)
            return problem(error, size, "%s: unknown key %s", text, key);
    }
    if (first && use != POINT_FOR_CALL)
        return problem(error, size, "an empty point");
    p->next = p->kind == POINT_PC ? 0 : point_set_next(&p->set, 0);
    return 1;
}

void point_note(point *p, const char *name)
{
    if (p->after[0] && !strcmp(p->after, name))
        p->after_seen = 1;
}

int point_passes(const point *p, const iigs *m)
{
    if (!p->after_seen)
        return 0;
    if (p->test == POINT_ALWAYS)
        return 1;
    uint32_t value = 0;
    for (unsigned i = 0; i < p->test_size; i++)
        value |= (uint32_t)iigs_peek(m, p->test_address + i) << (8 * i);
    switch (p->test) {
    case POINT_EQ: return value == p->test_value;
    case POINT_NE: return value != p->test_value;
    case POINT_LT: return value < p->test_value;
    case POINT_LE: return value <= p->test_value;
    case POINT_GT: return value > p->test_value;
    case POINT_GE: return value >= p->test_value;
    default: return 1;
    }
}

int point_fires(point *p, const iigs *m, int at_pc)
{
    switch (p->kind) {
    case POINT_PC:
        if (!at_pc || !point_passes(p, m))
            return 0;
        p->hits++;
        p->last_hit = p->hits;
        return point_set_has(&p->set, p->hits);
    case POINT_FRAME:
        if (m->frame < p->next)
            return 0;
        p->next = m->frame == UINT64_MAX ? UINT64_MAX :
                  point_set_next(&p->set, m->frame + 1);
        if (!point_passes(p, m))
            return 0;
        p->hits++;
        p->last_hit = m->frame;
        return 1;
    case POINT_CYCLE: {
        if (m->cpu.cycles < p->next)
            return 0;
        uint64_t member = p->next;
        p->next = point_set_next(&p->set, m->cpu.cycles + 1);
        if (!point_passes(p, m))
            return 0;
        p->hits++;
        p->last_hit = member;
        return 1;
    }
    }
    return 0;
}

uint64_t point_due_frame(const point *p)
{
    return p->kind == POINT_FRAME ? p->next : UINT64_MAX;
}

uint64_t point_due_cycle(const point *p)
{
    return p->kind == POINT_CYCLE ? p->next : UINT64_MAX;
}

uint64_t point_hit(const point *p)
{
    return p->last_hit;
}

uint64_t point_dump_bytes(const point *p)
{
    if (!p->range_count)
        return (uint64_t)(IIGS_RAM_BANKS + 2) * IIGS_BANK;
    uint64_t total = 0;
    for (unsigned i = 0; i < p->range_count; i++)
        total += p->range_length[i];
    return total;
}
