/*
 * Pokes and lumps: see inject.h.
 */
#include "inject.h"

#include <ctype.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { LINE = 4096, PATH = 4096, WAD_HEADER = 12, ENTRY = 16, NAME = 8 };

static int problem(char *error, size_t size, const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(error, size, format, arguments);
    va_end(arguments);
    return 0;
}

static int in_ram(uint64_t address)
{
    unsigned bank = (unsigned)(address >> 16);
    return bank < IIGS_RAM_BANKS || bank == 0xe0 || bank == 0xe1;
}

static int all_in_ram(uint64_t address, uint64_t length)
{
    if (!length || address + length - 1 > 0xffffff)
        return 0;
    for (uint64_t a = address; a < address + length; a = (a | 0xffff) + 1)
        if (!in_ram(a))
            return 0;
    return 1;
}

/* The bytes of a file; NULL with errno set. */
static uint8_t *read_all(const char *path, uint32_t *length)
{
    FILE *file = fopen(path, "rb");
    if (!file)
        return NULL;
    size_t capacity = 1 << 16, used = 0;
    uint8_t *data = malloc(capacity);
    while (data) {
        used += fread(data + used, 1, capacity - used, file);
        if (used < capacity || capacity >= 1 << 25)
            break;
        uint8_t *grown = realloc(data, capacity * 2);
        if (!grown) {
            free(data);
            data = NULL;
            break;
        }
        data = grown;
        capacity *= 2;
    }
    int bad = ferror(file) || used > 0x1000000;
    fclose(file);
    if (!data || bad) {
        free(data);
        errno = bad ? EFBIG : ENOMEM;
        return NULL;
    }
    *length = (uint32_t)used;
    return data;
}

static int hex_digit(int c)
{
    return isdigit(c) ? c - '0' : isxdigit(c) ? tolower(c) - 'a' + 10 : -1;
}

/* One line: POINT ADDR DATA. */
static int poke_line(poke *p, char *text, const char *path,
                     const char *where, char *error, size_t size)
{
    char *words[4];
    int count = 0;
    for (char *w = text; *w && count < 4;) {
        while (*w == ' ' || *w == '\t')
            w++;
        if (!*w)
            break;
        words[count++] = w;
        while (*w && *w != ' ' && *w != '\t')
            w++;
        if (*w)
            *w++ = 0;
    }
    if (count != 3)
        return problem(error, size, "%s: a poke is POINT ADDR DATA", where);
    char message[512];
    if (!point_parse(&p->when, words[0], POINT_FOR_POKE, message,
                     sizeof message))
        return problem(error, size, "%s: %s", where, message);
    char *end;
    errno = 0;
    unsigned long address = strtoul(words[1], &end, 16);
    if (errno || end == words[1] || *end || address > 0xffffff)
        return problem(error, size, "%s: %s is not a 24-bit hex address",
                       where, words[1]);
    p->address = (uint32_t)address;
    const char *data = words[2];
    if (data[0] == '@') {
        char file[PATH];
        const char *slash = strrchr(path, '/');
        if (data[1] == '/' || !slash)
            snprintf(file, sizeof file, "%s", data + 1);
        else
            snprintf(file, sizeof file, "%.*s/%s", (int)(slash - path), path,
                     data + 1);
        p->data = read_all(file, &p->length);
        if (!p->data)
            return problem(error, size, "%s: cannot read %s: %s", where,
                           file, strerror(errno));
    } else {
        size_t digits = strlen(data);
        if (!digits || digits % 2)
            return problem(error, size, "%s: DATA is hex bytes or @PATH",
                           where);
        p->length = (uint32_t)(digits / 2);
        p->data = malloc(p->length);
        if (!p->data)
            return problem(error, size, "%s: out of memory", where);
        for (size_t i = 0; i < p->length; i++) {
            int high = hex_digit(data[2 * i]), low = hex_digit(data[2 * i + 1]);
            if (high < 0 || low < 0) {
                free(p->data);
                p->data = NULL;
                return problem(error, size, "%s: DATA is hex bytes or @PATH",
                               where);
            }
            p->data[i] = (uint8_t)(high << 4 | low);
        }
    }
    if (!all_in_ram(p->address, p->length)) {
        free(p->data);
        p->data = NULL;
        return problem(error, size, "%s: $%06X and the %u bytes after are "
                       "not all RAM", where, (unsigned)p->address,
                       (unsigned)p->length);
    }
    return 1;
}

int pokes_read(poke_list *list, const char *path, char *error, size_t size)
{
    FILE *file = fopen(path, "r");
    if (!file)
        return problem(error, size, "cannot read %s: %s", path,
                       strerror(errno));
    char text[LINE];
    unsigned number = 0;
    int ok = 1;
    while (ok && fgets(text, sizeof text, file)) {
        char where[PATH + 32];
        number++;
        snprintf(where, sizeof where, "%s:%u", path, number);
        size_t length = strlen(text);
        if (length && text[length - 1] != '\n' && !feof(file)) {
            ok = problem(error, size, "%s: the line is too long", where);
            break;
        }
        char *hash = strchr(text, '#');
        if (hash)
            *hash = 0;
        for (char *c = text; *c; c++)
            if (*c == '\n' || *c == '\r')
                *c = ' ';
        int blank = 1;
        for (char *c = text; *c; c++)
            blank &= *c == ' ' || *c == '\t';
        if (blank)
            continue;
        if (list->count == list->capacity) {
            size_t capacity = list->capacity ? 2 * list->capacity : 16;
            poke *grown = realloc(list->pokes, capacity * sizeof *grown);
            if (!grown) {
                ok = problem(error, size, "%s: out of memory", where);
                break;
            }
            list->pokes = grown;
            list->capacity = capacity;
        }
        poke *p = &list->pokes[list->count];
        memset(p, 0, sizeof *p);
        ok = poke_line(p, text, path, where, error, size);
        if (ok)
            list->count++;
    }
    if (ok && ferror(file))
        ok = problem(error, size, "cannot read %s", path);
    fclose(file);
    return ok;
}

void pokes_free(poke_list *list)
{
    for (size_t i = 0; i < list->count; i++)
        free(list->pokes[i].data);
    free(list->pokes);
    list->pokes = NULL;
    list->count = list->capacity = 0;
}

void poke_apply(iigs *m, const poke *p)
{
    iigs_load(m, p->address, p->data, p->length);
}

/* ---- lumps ---- */

static uint32_t peek32(const iigs *m, uint32_t address)
{
    uint32_t value = 0;
    for (int i = 0; i < 4; i++)
        value |= (uint32_t)iigs_peek(m, (address + i) & 0xffffff) << (8 * i);
    return value;
}

static void put32(uint8_t *p, uint32_t value)
{
    for (int i = 0; i < 4; i++)
        p[i] = (uint8_t)(value >> (8 * i));
}

int lump_place(iigs *m, uint32_t wad, const char *name, uint32_t dest,
               const uint8_t *data, size_t length, char *error, size_t size)
{
    char id[5];
    for (int i = 0; i < 4; i++)
        id[i] = (char)iigs_peek(m, wad + i);
    id[4] = 0;
    if (!all_in_ram(wad, WAD_HEADER) ||
        (strcmp(id, "IWAD") && strcmp(id, "PWAD")))
        return problem(error, size, "--wad %06X: no IWAD or PWAD there",
                       (unsigned)wad);
    size_t name_length = strlen(name);
    if (!name_length || name_length > NAME)
        return problem(error, size, "--lump: a name of 1 to 8 characters");
    uint32_t lumps = peek32(m, wad + 4);
    uint32_t directory = (wad + peek32(m, wad + 8)) & 0xffffff;
    if (!all_in_ram(directory, (uint64_t)lumps * ENTRY))
        return problem(error, size, "--wad %06X: the directory of %u lumps "
                       "at $%06X is not in RAM", (unsigned)wad,
                       (unsigned)lumps, (unsigned)directory);
    uint32_t entry = 0;
    unsigned found = 0;
    for (uint32_t i = 0; i < lumps; i++) {
        uint32_t at = directory + i * ENTRY;
        int same = 1;
        for (unsigned j = 0; j < NAME; j++) {
            uint8_t c = iigs_peek(m, at + 8 + j);
            uint8_t want = j < name_length ? (uint8_t)name[j] : 0;
            same &= c == want;
        }
        if (same) {
            entry = at;
            found++;
        }
    }
    if (found != 1)
        return problem(error, size, "--lump %s: %u entries of that name in "
                       "the directory, not 1", name, found);
    if (!length || !all_in_ram(dest, length) ||
        dest >> 16 != (uint32_t)((dest + length - 1) >> 16))
        return problem(error, size, "--lump %s: %zu bytes at $%06X are not "
                       "RAM within one bank", name, length, (unsigned)dest);
    for (size_t i = 0; i < length; i++)
        if (iigs_peek(m, (uint32_t)(dest + i)))
            return problem(error, size, "--lump %s: $%06X is not free (a "
                           "byte there is not zero)", name,
                           (unsigned)(dest + i));
    uint8_t fields[8];
    put32(fields, (dest - wad) & 0xffffffffu);
    put32(fields + 4, (uint32_t)length);
    iigs_load(m, dest, data, length);
    iigs_load(m, entry, fields, sizeof fields);
    return 1;
}
