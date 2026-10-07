/*
 * The MLI stand-in of a2vm: see prodos.h. Each call follows the method of
 * the same name in a2sim.py's FakeProDOS (the earlier Appletini Doom
 * port's Python model), in the same order of checks.
 * Where FakeProDOS raises ProDOSError the call returns that code; where
 * Python itself would fail (an index past the end of main memory, a
 * volume the earlier port's build_disk refuses) the call returns PRODOS_FAULT.
 */
#include "prodos.h"

#include <ctype.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    BLOCK = 512,
    DIRECTORY_FIRST = 2, DIRECTORY_BLOCKS = 4,
    FIRST_BITMAP_BLOCK = 6,
    BLOCKS_PER_BITMAP = BLOCK * 8,
    ENTRY_LENGTH = 0x27, ENTRIES_PER_BLOCK = 0x0d,
    MAX_ENTRIES = ENTRIES_PER_BLOCK * DIRECTORY_BLOCKS - 1,
    FREE_BLOCKS = 64, MAX_BLOCKS = 0xffff,
    ACCESS_DEFAULT = 0xc3,
    MAX_PARTS = 64
};

/* ---- CRC-32 (the zlib polynomial, for the state digests) ---- */

uint32_t a2vm_crc32(uint32_t crc, const uint8_t *data, size_t length)
{
    static uint32_t table[256];
    if (!table[1]) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++)
                c = c & 1 ? 0xedb88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
    }
    crc = ~crc;
    for (size_t i = 0; i < length; i++)
        crc = table[(crc ^ data[i]) & 0xff] ^ (crc >> 8);
    return ~crc;
}

/* ---- buffers (Python bytearrays) ---- */

static int reserve(prodos_buffer *b, size_t length)
{
    if (length <= b->capacity)
        return 1;
    size_t capacity = b->capacity ? b->capacity : 512;
    while (capacity < length)
        capacity *= 2;
    uint8_t *data = realloc(b->data, capacity);
    if (!data)
        return 0;
    b->data = data;
    b->capacity = capacity;
    return 1;
}

/* data[start:end] = replacement, with Python's slice clipping. */
static int splice(prodos_buffer *b, size_t start, size_t end,
                  const uint8_t *replacement, size_t count)
{
    if (start > b->length)
        start = b->length;
    if (end > b->length)
        end = b->length;
    if (end < start)
        end = start;
    size_t length = b->length - (end - start) + count;
    if (!reserve(b, length))
        return 0;
    memmove(b->data + start + count, b->data + end, b->length - end);
    memcpy(b->data + start, replacement, count);
    b->length = length;
    return 1;
}

/* ---- names ---- */

/* FakeProDOS.NAME, ^[A-Z][A-Z0-9.]{0,14}$, with Python's "$" that also
   matches before a final newline. */
static int valid_name(const char *name)
{
    size_t length = strlen(name);
    if (length && name[length - 1] == '\n')
        length--;
    if (length < 1 || length > 15 || name[0] < 'A' || name[0] > 'Z')
        return 0;
    for (size_t i = 1; i < length; i++)
        if (!((name[i] >= 'A' && name[i] <= 'Z') ||
              (name[i] >= '0' && name[i] <= '9') || name[i] == '.'))
            return 0;
    return 1;
}

static void upper(char *text)
{
    for (; *text; text++)
        if (*text >= 'a' && *text <= 'z')
            *text = (char)(*text - 'a' + 'A');
}

/* build_disk.encode_name: 1-15 characters, a letter first, then letters,
   digits and dots (str.isalpha and str.isalnum, ASCII here). */
static int encodable(const char *name)
{
    size_t length = strlen(name);
    if (length < 1 || length > 15 || !isalpha((unsigned char)name[0]))
        return 0;
    for (size_t i = 0; i < length; i++)
        if (!isalnum((unsigned char)name[i]) && name[i] != '.')
            return 0;
    return 1;
}

/* ---- construction ---- */

a2vm_prodos *prodos_new(const char *volume, const char *launched)
{
    a2vm_prodos *p = calloc(1, sizeof *p);
    if (!p)
        return NULL;
    snprintf(p->volume, sizeof p->volume, "%s", volume);
    upper(p->volume);
    snprintf(p->prefix, sizeof p->prefix, "/%s/", p->volume);
    snprintf(p->launched, sizeof p->launched, "%s", launched);
    return p;
}

void prodos_free(a2vm_prodos *p)
{
    if (!p)
        return;
    for (size_t i = 0; i < p->file_count; i++)
        free(p->files[i].buffer.data);
    for (unsigned r = 1; r <= PRODOS_MAX_OPEN; r++)
        free(p->open[r].directory.data);
    free(p->files);
    free(p);
}

static int find(const a2vm_prodos *p, const char *name)
{
    for (size_t i = 0; i < p->file_count; i++)
        if (p->files[i].live && !strcmp(p->files[i].name, name))
            return (int)i;
    return -1;
}

/* A new live file at the end of the order (a new dict key). */
static prodos_file *append(a2vm_prodos *p, const char *name)
{
    if (p->file_count == p->file_capacity) {
        size_t capacity = p->file_capacity ? p->file_capacity * 2 : 64;
        prodos_file *files = realloc(p->files, capacity * sizeof *files);
        if (!files)
            return NULL;
        p->files = files;
        p->file_capacity = capacity;
    }
    prodos_file *f = &p->files[p->file_count++];
    memset(f, 0, sizeof *f);
    snprintf(f->name, sizeof f->name, "%s", name);
    f->live = 1;
    return f;
}

int prodos_add(a2vm_prodos *p, const char *name, uint8_t type, uint16_t aux,
               const uint8_t *data, size_t length, char *error,
               size_t error_size)
{
    char upper_name[64];
    snprintf(upper_name, sizeof upper_name, "%s", name);
    upper(upper_name);
    if (strlen(name) > 16 || !valid_name(upper_name)) {
        snprintf(error, error_size, "not a ProDOS file name: %s", name);
        return 0;
    }
    int index = find(p, upper_name);
    prodos_file *f = index >= 0 ? &p->files[index] : append(p, upper_name);
    if (!f || !reserve(&f->buffer, length ? length : 1)) {
        snprintf(error, error_size, "out of memory");
        return 0;
    }
    f->type = type;
    f->aux = aux;
    memcpy(f->buffer.data, data, length);
    f->buffer.length = length;
    return 1;
}

size_t prodos_launch_path(const a2vm_prodos *p, uint8_t *out, size_t size)
{
    char path[128];
    int length = snprintf(path, sizeof path, "%s%s", p->prefix, p->launched);
    if (length < 0 || (size_t)length + 1 > size || length > 255)
        return 0;
    out[0] = (uint8_t)length;
    memcpy(out + 1, path, (size_t)length);
    return (size_t)length + 1;
}

/* ---- the volume directory (build_disk.VolumeWriter) ---- */

static uint64_t file_block_count(size_t size)
{
    uint64_t data = size ? (size + BLOCK - 1) / BLOCK : 1;
    if (data == 1)
        return 1;
    if (data <= 256)
        return data + 1;
    return data + 1 + (data + 255) / 256;   /* > 256 * 128: refused below */
}

static uint64_t bitmap_blocks(uint64_t total)
{
    return (total + BLOCKS_PER_BITMAP - 1) / BLOCKS_PER_BITMAP;
}

static void put16(uint8_t *at, unsigned value)
{
    at[0] = (uint8_t)value;
    at[1] = (uint8_t)(value >> 8);
}

int prodos_directory(a2vm_prodos *p, prodos_buffer *out)
{
    /* volume_size, with empty files counted as one byte */
    uint64_t used = FIRST_BITMAP_BLOCK + FREE_BLOCKS;
    unsigned count = 0;
    for (size_t i = 0; i < p->file_count; i++) {
        const prodos_file *f = &p->files[i];
        if (!f->live)
            continue;
        size_t size = f->buffer.length ? f->buffer.length : 1;
        if ((size + BLOCK - 1) / BLOCK > 256 * 128) {
            snprintf(p->fault, sizeof p->fault,
                     "%s: file too large for build_disk", f->name);
            return 0;
        }
        used += file_block_count(size);
        count++;
    }
    uint64_t total = used + bitmap_blocks(used);
    total += bitmap_blocks(total) - bitmap_blocks(used);
    if (total > MAX_BLOCKS) {
        snprintf(p->fault, sizeof p->fault,
                 "the files need %llu blocks, more than a ProDOS volume holds",
                 (unsigned long long)total);
        return 0;
    }
    if (total < 280)
        total = 280;
    if (!encodable(p->volume)) {
        snprintf(p->fault, sizeof p->fault, "invalid ProDOS name %s",
                 p->volume);
        return 0;
    }
    if (count > MAX_ENTRIES) {
        snprintf(p->fault, sizeof p->fault,
                 "volume directory is full (%d entries)", MAX_ENTRIES);
        return 0;
    }
    if (!reserve(out, DIRECTORY_BLOCKS * BLOCK))
        return 0;
    memset(out->data, 0, DIRECTORY_BLOCKS * BLOCK);
    out->length = DIRECTORY_BLOCKS * BLOCK;

    uint64_t next_free = FIRST_BITMAP_BLOCK + bitmap_blocks(total);
    unsigned slot = 1;          /* slot 0 of the first block: the header */
    for (size_t i = 0; i < p->file_count; i++) {
        const prodos_file *f = &p->files[i];
        if (!f->live)
            continue;
        if (!encodable(f->name)) {
            snprintf(p->fault, sizeof p->fault, "invalid ProDOS name %s",
                     f->name);
            return 0;
        }
        size_t size = f->buffer.length ? f->buffer.length : 1;
        uint64_t chunks = (size + BLOCK - 1) / BLOCK;
        uint64_t blocks = file_block_count(size);
        unsigned storage = chunks == 1 ? 1 : chunks <= 256 ? 2 : 3;
        uint64_t key = next_free;
        if (next_free + blocks > total) {
            snprintf(p->fault, sizeof p->fault, "volume is full");
            return 0;
        }
        next_free += blocks;
        uint8_t *entry = out->data + (slot / ENTRIES_PER_BLOCK) * BLOCK + 4 +
                         (slot % ENTRIES_PER_BLOCK) * ENTRY_LENGTH;
        size_t length = strlen(f->name);
        entry[0] = (uint8_t)(storage << 4 | length);
        memcpy(entry + 1, f->name, length);
        entry[16] = f->type;
        put16(entry + 17, (unsigned)key);
        put16(entry + 19, (unsigned)blocks);
        entry[21] = (uint8_t)size;
        entry[22] = (uint8_t)(size >> 8);
        entry[23] = (uint8_t)(size >> 16);
        entry[30] = ACCESS_DEFAULT;
        put16(entry + 31, f->aux);
        put16(entry + 37, 2);
        slot++;
    }
    for (unsigned b = 0; b < DIRECTORY_BLOCKS; b++) {
        uint8_t *block = out->data + b * BLOCK;
        put16(block, b ? DIRECTORY_FIRST + b - 1 : 0);
        put16(block + 2, b + 1 < DIRECTORY_BLOCKS ? DIRECTORY_FIRST + b + 1 : 0);
    }
    uint8_t *head = out->data + 4;
    size_t length = strlen(p->volume);
    head[0] = (uint8_t)(0xf0 | length);
    memcpy(head + 1, p->volume, length);
    head[30] = ACCESS_DEFAULT;
    head[31] = ENTRY_LENGTH;
    head[32] = ENTRIES_PER_BLOCK;
    put16(head + 33, count);
    put16(head + 35, FIRST_BITMAP_BLOCK);
    put16(head + 37, (unsigned)total);
    return 1;
}

/* ---- the calls ---- */

typedef struct {
    a2vm_prodos *p;
    uint8_t *main;
    jmp_buf fail;
} call;

/* ProDOSError(code), or PRODOS_FAULT with a message */
static void raise_error(call *c, int code)
{
    longjmp(c->fail, code);
}

static void fault(call *c, const char *what, unsigned address)
{
    snprintf(c->p->fault, sizeof c->p->fault, "%s at $%X", what, address);
    longjmp(c->fail, PRODOS_FAULT);
}

static uint8_t get(call *c, unsigned address)
{
    if (address > 0xffff)
        fault(c, "read past main memory", address);
    return c->main[address];
}

static void set(call *c, unsigned address, unsigned value)
{
    if (address > 0xffff)
        fault(c, "write past main memory", address);
    c->main[address] = (uint8_t)value;
}

static unsigned get16(call *c, unsigned address)
{
    return get(c, address) | get(c, address + 1) << 8;
}

static void set16(call *c, unsigned address, unsigned value)
{
    set(c, address, value & 0xff);
    set(c, address + 1, (value >> 8) & 0xff);
}

static void set24(call *c, unsigned address, uint64_t value)
{
    set(c, address, value & 0xff);
    set(c, address + 1, (value >> 8) & 0xff);
    set(c, address + 2, (value >> 16) & 0xff);
}

static uint64_t get24(call *c, unsigned address)
{
    return get(c, address) | get(c, address + 1) << 8 |
           (uint64_t)get(c, address + 2) << 16;
}

/* _pathname: the counted string at `address`, high bits stripped, upper
   case (resolve upper-cases it). */
static void pathname(call *c, unsigned address, char *out, size_t size)
{
    unsigned length = get(c, address);
    size_t n = 0;
    for (unsigned i = 0; i < length && address + 1 + i <= 0xffff; i++)
        if (n + 1 < size)
            out[n++] = (char)(c->main[address + 1 + i] & 0x7f);
    out[n] = 0;
    for (size_t i = 0; i < n; i++)
        if (out[i] >= 'a' && out[i] <= 'z')
            out[i] = (char)(out[i] - 'a' + 'A');
}

/* The non-empty parts of `text` split at "/". */
static unsigned split(char *text, char **parts, unsigned limit)
{
    unsigned count = 0;
    char *start = text;
    for (char *at = text;; at++) {
        if (*at == '/' || !*at) {
            int end = !*at;
            *at = 0;
            if (*start && count < limit)
                parts[count++] = start;
            if (end)
                break;
            start = at + 1;
        }
    }
    return count;
}

/* resolve: the file name `path` refers to, or "" for the volume
   directory. */
static void resolve(call *c, const char *path, char *name, size_t size)
{
    char text[300], prefix[32];
    char *parts[MAX_PARTS], *prefix_parts[MAX_PARTS];
    unsigned count;
    snprintf(text, sizeof text, "%s", path);
    if (!text[0])
        raise_error(c, PRODOS_E_BADPATH);
    if (text[0] == '/') {
        count = split(text, parts, MAX_PARTS);
        if (!count || strcmp(parts[0], c->p->volume))
            raise_error(c, count ? PRODOS_E_NOVOL : PRODOS_E_BADPATH);
        memmove(parts, parts + 1, (count - 1) * sizeof *parts);
        count--;
    } else {
        snprintf(prefix, sizeof prefix, "%s", c->p->prefix);
        unsigned n = split(prefix, prefix_parts, MAX_PARTS);
        char *mine[MAX_PARTS];
        unsigned own = split(text, mine, MAX_PARTS);
        count = 0;
        for (unsigned i = 1; i < n; i++)
            parts[count++] = prefix_parts[i];
        for (unsigned i = 0; i < own && count < MAX_PARTS; i++)
            parts[count++] = mine[i];
    }
    for (unsigned i = 0; i < count; i++)
        if (!valid_name(parts[i]))
            raise_error(c, PRODOS_E_BADPATH);
    if (!count) {
        name[0] = 0;
        return;
    }
    if (count > 1)
        raise_error(c, PRODOS_E_NOPATH);
    snprintf(name, size, "%s", parts[0]);
}

static void resolve_at(call *c, unsigned parms, char *name, size_t size)
{
    char path[300];
    pathname(c, get16(c, parms + 1), path, sizeof path);
    resolve(c, path, name, size);
}

/* _file: the live file the pathname of the block names. */
static int named_file(call *c, unsigned parms)
{
    char name[300];
    resolve_at(c, parms, name, sizeof name);
    int index = name[0] ? find(c->p, name) : -1;
    if (index < 0)
        raise_error(c, PRODOS_E_NOFILE);
    return index;
}

static prodos_open *opened(call *c, unsigned ref)
{
    if (ref < 1 || ref > PRODOS_MAX_OPEN || !c->p->open[ref].used)
        raise_error(c, PRODOS_E_BADREF);
    return &c->p->open[ref];
}

static void mli_open(call *c, unsigned parms)
{
    a2vm_prodos *p = c->p;
    char name[300];
    resolve_at(c, parms, name, sizeof name);
    if (p->open_count >= PRODOS_MAX_OPEN)
        raise_error(c, PRODOS_E_TOOMANY);
    int index = -1;
    if (name[0]) {
        index = find(p, name);
        if (index < 0)
            raise_error(c, PRODOS_E_NOFILE);
    }
    unsigned ref = 1;
    while (p->open[ref].used)
        ref++;
    prodos_open *o = &p->open[ref];
    if (index < 0) {
        if (!prodos_directory(p, &o->directory))
            longjmp(c->fail, PRODOS_FAULT);
        o->buffer = &o->directory;
    } else
        o->buffer = &p->files[index].buffer;
    o->used = 1;
    o->file = index;
    o->pos = 0;
    o->dirty = 0;
    p->open_order[p->open_count++] = (uint8_t)ref;
    set(c, parms + 5, ref);
}

static void mli_read(call *c, unsigned parms)
{
    prodos_open *o = opened(c, get(c, parms + 1));
    unsigned buffer = get16(c, parms + 2), request = get16(c, parms + 4);
    prodos_buffer *data = o->buffer;
    /* data[pos:pos + request]: pos may lie past the end when another
       reference to the file shortened it */
    size_t pos = o->pos < data->length ? (size_t)o->pos : data->length;
    size_t chunk = data->length - pos < request ? data->length - pos : request;
    set16(c, parms + 6, (unsigned)chunk);
    if (request && !chunk)
        raise_error(c, PRODOS_E_EOF);
    if (buffer + chunk > 0x10000)
        fault(c, "read into a buffer past main memory", buffer);
    memcpy(c->main + buffer, data->data + pos, chunk);
    o->pos += chunk;
}

static void mli_write(call *c, unsigned parms)
{
    prodos_open *o = opened(c, get(c, parms + 1));
    if (o->file < 0)
        raise_error(c, PRODOS_E_ACCESS);
    unsigned buffer = get16(c, parms + 2), request = get16(c, parms + 4);
    prodos_buffer *data = o->buffer;
    size_t pos = (size_t)o->pos;
    if (data->length < pos) {
        if (!reserve(data, pos))
            fault(c, "out of memory", 0);
        memset(data->data + data->length, 0, pos - data->length);
        data->length = pos;
    }
    size_t count = buffer + request > 0x10000 ? 0x10000 - buffer : request;
    if (!splice(data, pos, pos + request, c->main + buffer, count))
        fault(c, "out of memory", 0);
    o->pos = (uint64_t)pos + request;
    o->dirty = 1;
    set16(c, parms + 6, request);
}

static void close_ref(a2vm_prodos *p, unsigned ref)
{
    p->open[ref].used = 0;
    for (unsigned i = 0; i < p->open_count; i++)
        if (p->open_order[i] == ref) {
            memmove(p->open_order + i, p->open_order + i + 1,
                    p->open_count - i - 1);
            p->open_count--;
            break;
        }
}

static void mli_close(call *c, unsigned parms)
{
    unsigned ref = get(c, parms + 1);
    if (ref == 0) {
        while (c->p->open_count)
            close_ref(c->p, c->p->open_order[0]);
        return;
    }
    opened(c, ref);
    close_ref(c->p, ref);
}

static void mli_create(call *c, unsigned parms)
{
    char name[300];
    resolve_at(c, parms, name, sizeof name);
    if (!name[0] || find(c->p, name) >= 0)
        raise_error(c, PRODOS_E_DUP);
    uint8_t type = get(c, parms + 4);
    unsigned aux = get16(c, parms + 5);
    prodos_file *f = append(c->p, name);
    if (!f)
        fault(c, "out of memory", 0);
    f->type = type;
    f->aux = (uint16_t)aux;
}

static void mli_destroy(call *c, unsigned parms)
{
    c->p->files[named_file(c, parms)].live = 0;
}

static void mli_get_file_info(call *c, unsigned parms)
{
    const prodos_file *f = &c->p->files[named_file(c, parms)];
    set(c, parms + 3, 0xc3);
    set(c, parms + 4, f->type);
    set16(c, parms + 5, f->aux);
    size_t blocks = (f->buffer.length + 511) / 512;
    if (blocks < 1)
        blocks = 1;
    unsigned storage = blocks == 1 ? 1 : blocks <= 256 ? 2 : 3;
    size_t index = storage == 1 ? 0 : storage == 2 ? 1 : 1 + (blocks + 255) / 256;
    set(c, parms + 7, storage);
    set16(c, parms + 8, (unsigned)((blocks + index) & 0xffff));
    for (unsigned offset = 10; offset < 18; offset++)
        set(c, parms + offset, 0);
}

static void mli_set_file_info(call *c, unsigned parms)
{
    prodos_file *f = &c->p->files[named_file(c, parms)];
    f->type = get(c, parms + 4);
    f->aux = (uint16_t)get16(c, parms + 5);
}

static void mli_get_prefix(call *c, unsigned parms)
{
    unsigned buffer = get16(c, parms + 1);
    size_t length = strlen(c->p->prefix);
    set(c, buffer, (unsigned)length);
    for (size_t i = 0; i < length; i++)
        set(c, buffer + 1 + (unsigned)i, (uint8_t)c->p->prefix[i]);
}

static void mli_set_prefix(call *c, unsigned parms)
{
    char name[300];
    resolve_at(c, parms, name, sizeof name);
    if (name[0])
        raise_error(c, PRODOS_E_NOPATH);
    snprintf(c->p->prefix, sizeof c->p->prefix, "/%s/", c->p->volume);
}

static void mli_on_line(call *c, unsigned parms)
{
    unsigned unit = get(c, parms + 1), buffer = get16(c, parms + 2);
    unsigned entries = unit ? 1 : 14;
    if (buffer + 16 * entries > 0x10000)
        fault(c, "ON_LINE buffer past main memory", buffer);
    memset(c->main + buffer, 0, 16 * entries);
    size_t length = strlen(c->p->volume);
    set(c, buffer, 0x70 | (unsigned)length);
    memcpy(c->main + buffer + 1, c->p->volume, length);
}

static void mli_set_mark(call *c, unsigned parms)
{
    prodos_open *o = opened(c, get(c, parms + 1));
    uint64_t position = get24(c, parms + 2);
    if (position > o->buffer->length)
        raise_error(c, PRODOS_E_POSITION);
    o->pos = position;
}

static void mli_get_mark(call *c, unsigned parms)
{
    prodos_open *o = opened(c, get(c, parms + 1));
    set24(c, parms + 2, o->pos);
}

static void mli_set_eof(call *c, unsigned parms)
{
    prodos_open *o = opened(c, get(c, parms + 1));
    uint64_t eof = get24(c, parms + 2);
    prodos_buffer *data = o->buffer;
    if (eof < data->length)
        data->length = (size_t)eof;
    else {
        if (!reserve(data, (size_t)eof))
            fault(c, "out of memory", 0);
        memset(data->data + data->length, 0, (size_t)eof - data->length);
        data->length = (size_t)eof;
    }
    if (o->pos > eof)
        o->pos = eof;
    o->dirty = 1;
}

static void mli_get_eof(call *c, unsigned parms)
{
    prodos_open *o = opened(c, get(c, parms + 1));
    set24(c, parms + 2, o->buffer->length);
}

static void log_call(a2vm_prodos *p, uint8_t number, uint8_t error)
{
    uint8_t pair[2] = { number, error };
    p->calls++;
    p->calls_crc = a2vm_crc32(p->calls_crc, pair, 2);
}

int prodos_call(a2vm_prodos *p, uint8_t *main, uint8_t number,
                uint16_t parms)
{
    typedef void (*handler)(call *, unsigned);
    handler h = NULL;
    call c;
    if (number == 0x65) {
        log_call(p, number, 0);
        p->quit = 1;
        return PRODOS_QUIT;
    }
    switch (number) {
    case 0xc8: h = mli_open; break;
    case 0xca: h = mli_read; break;
    case 0xcb: h = mli_write; break;
    case 0xcc: h = mli_close; break;
    case 0xc0: h = mli_create; break;
    case 0xc1: h = mli_destroy; break;
    case 0xc4: h = mli_get_file_info; break;
    case 0xc3: h = mli_set_file_info; break;
    case 0xc7: h = mli_get_prefix; break;
    case 0xc6: h = mli_set_prefix; break;
    case 0xc5: h = mli_on_line; break;
    case 0xce: h = mli_set_mark; break;
    case 0xcf: h = mli_get_mark; break;
    case 0xd0: h = mli_set_eof; break;
    case 0xd1: h = mli_get_eof; break;
    }
    if (!h) {
        log_call(p, number, PRODOS_E_BADCALL);
        return PRODOS_E_BADCALL;
    }
    c.p = p;
    c.main = main;
    int error = setjmp(c.fail);
    if (!error)
        h(&c, parms);
    if (error == PRODOS_FAULT)
        return PRODOS_FAULT;
    log_call(p, number, (uint8_t)error);
    return error;
}
