#include "internal.h"
#include "libtini/storage.h"
/* The aligned 1 KiB ProDOS I/O buffer, from the linker layout. A layout that
 * gives that memory to the program leaves it out, so no file call links. */
extern uint8_t ti_file_buffer;

uint8_t ti_mli_command;
uint8_t *ti_mli_params;
uint8_t ti_mli_call(void);
static uint8_t pathname[16], parms[18], io[128], file_ref, busy, os_error;
static uint8_t pack_header[24], pack_name[16], chosen_name[16];
static uint32_t file_size, chosen_offset, chosen_size;

static void word(uint8_t *p, uint16_t value)
{ p[0] = (uint8_t)value; p[1] = (uint8_t)(value >> 8); }
static uint16_t read16(const uint8_t *p)
{ return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t read32(const uint8_t *p)
{ return (uint32_t)read16(p) | ((uint32_t)read16(p + 2) << 16); }

static uint8_t valid_name(const char *name, uint8_t *out, uint8_t underscore)
{
    uint8_t i, c;
    if (!name || !ti_near_valid(name, 1, 0)) return 0;
    for (i = 0; i < 16; ++i) {
        if (!ti_near_valid(name + i, 1, 0)) return 0;
        c = (uint8_t)name[i];
        if (!c) return i;
        if (i == 15 || (i == 0 && (c < 'A' || c > 'Z')) ||
            !((c >= 'A' && c <= 'Z') || (i && c >= '0' && c <= '9') || (i && c == '.') ||
              (i && underscore && c == '_')))
            return 0;
        out[i] = c;
    }
    return 0;
}

static uint8_t call(uint8_t command)
{
    ti_mli_command = command;
    ti_mli_params = parms;
    os_error = ti_mli_call();
    return os_error;
}

static ti_error begin(const char *name)
{
    uint8_t length;
    ti_error error;
    if (busy) return TI_E_BUSY;
    length = valid_name(name, pathname + 1, 0);
    if (!length) return TI_E_ARGUMENT;
    pathname[0] = length;
    os_error = 0;
    busy = 1;
    if (ti_storage_pause_hook) ti_storage_pause_hook();
    error = ti_video_storage_begin();
    if (error) {
        if (ti_storage_resume_hook) ti_storage_resume_hook();
        busy = 0;
    }
    return error;
}

static ti_error finish(ti_error error)
{
    uint8_t previous = os_error, close_error;
    if (file_ref) {
        parms[0] = 1; parms[1] = file_ref;
        close_error = call(0xCC);
        if (!error && close_error) error = TI_E_IO;
        if (previous) os_error = previous;
        file_ref = 0;
    }
    ti_video_storage_end();
    if (ti_storage_resume_hook) ti_storage_resume_hook();
    ti_time_note_gap();
    busy = 0;
    return error;
}

static uint8_t open_file(void)
{
    parms[0] = 3;
    word(parms + 1, (uint16_t)pathname);
    word(parms + 3, (uint16_t)&ti_file_buffer);
    parms[5] = 0;
    if (call(0xC8)) return 0;
    file_ref = parms[5];
    parms[0] = 2; parms[1] = file_ref;
    if (call(0xD1)) return 0;
    file_size = (uint32_t)read16(parms + 2) | ((uint32_t)parms[4] << 16);
    return 1;
}

static uint8_t read_exact(void *dst, uint16_t length)
{
    parms[0] = 4; parms[1] = file_ref;
    word(parms + 2, (uint16_t)dst); word(parms + 4, length);
    word(parms + 6, 0);
    if (call(0xCA)) return 0;
    if (read16(parms + 6) != length) { os_error = 0x4C; return 0; }
    return 1;
}

uint8_t ti_file_last_error(void) { return os_error; }

ti_error ti_file_read(const char *name, void *dst, uint16_t capacity, uint16_t *length)
{
    ti_error error;
    if (!length || !ti_near_valid(length, 2, 1)) return TI_E_ARGUMENT;
    *length = 0;
    if (!ti_near_valid(dst, capacity, 1)) return TI_E_RANGE;
    error = begin(name);
    if (error) return error;
    if (!open_file()) return finish(TI_E_IO);
    if (file_size > capacity) return finish(TI_E_RANGE);
    if (file_size && !read_exact(dst, (uint16_t)file_size)) return finish(TI_E_IO);
    *length = (uint16_t)file_size;
    return finish(TI_OK);
}

ti_error ti_file_write(const char *name, const void *src, uint16_t length)
{
    ti_error error;
    uint8_t i, result;
    if (!ti_near_valid(src, length, 0)) return TI_E_RANGE;
    error = begin(name);
    if (error) return error;
    for (i = 0; i < sizeof(parms); ++i) parms[i] = 0;
    parms[0] = 7; word(parms + 1, (uint16_t)pathname);
    parms[3] = 0xC3; parms[4] = 0x06; parms[7] = 1; /* BIN, seedling */
    result = call(0xC0);
    if (result && result != 0x47) return finish(TI_E_IO);
    if (!open_file()) return finish(TI_E_IO);
    if (length) {
        parms[0] = 4; parms[1] = file_ref;
        word(parms + 2, (uint16_t)src); word(parms + 4, length); word(parms + 6, 0);
        if (call(0xCB)) return finish(TI_E_IO);
        if (read16(parms + 6) != length) { os_error = 0x4C; return finish(TI_E_IO); }
    }
    parms[0] = 2; parms[1] = file_ref;
    word(parms + 2, length); parms[4] = 0;
    if (call(0xD0)) return finish(TI_E_IO);
    return finish(TI_OK); /* CLOSE flushes directory and file data. */
}

ti_error ti_pack_load(const char *name, const char *entry, ti_handle *out, uint32_t *size)
{
    uint8_t n, j, k, found = 0;
    uint16_t entries;
    uint32_t end, offset, length;
    ti_handle handle;
    ti_error error;
    if (!out || !size || !ti_near_valid(out, 2, 1) || !ti_near_valid(size, 4, 1))
        return TI_E_ARGUMENT;
    *out = 0; *size = 0;
    for (j = 0; j < 16; ++j) chosen_name[j] = 0;
    if (!valid_name(entry, chosen_name, 1)) return TI_E_ARGUMENT;
    error = begin(name);
    if (error) return error;
    if (!open_file()) return finish(TI_E_IO);
    if (file_size < 8) return finish(TI_E_FORMAT);
    if (!read_exact(pack_header, 8)) return finish(TI_E_IO);
    if (pack_header[0] != 'T' || pack_header[1] != 'P' || pack_header[2] != 'K' ||
        pack_header[3] != '1' || pack_header[6] || pack_header[7]) return finish(TI_E_FORMAT);
    entries = read16(pack_header + 4);
    if (!entries || entries > 16) return finish(TI_E_FORMAT);
    end = 8UL + (uint32_t)entries * 24UL;
    if (end > file_size) return finish(TI_E_FORMAT);
    /* Entries must be sorted by name and payload; reject duplicates/overlap. */
    for (j = 0; j < 16; ++j) pack_name[j] = 0;
    for (n = 0; n < (uint8_t)entries; ++n) {
        if (!read_exact(pack_header, 24)) return finish(TI_E_IO);
        if (!pack_header[0] || pack_header[15]) return finish(TI_E_FORMAT);
        k = 0;
        for (j = 0; j < 16; ++j) {
            if (!pack_header[j]) k = 1;
            else if (k || !((pack_header[j] >= 'A' && pack_header[j] <= 'Z') ||
                     (j && pack_header[j] >= '0' && pack_header[j] <= '9') ||
                     (j && (pack_header[j] == '.' || pack_header[j] == '_')))) return finish(TI_E_FORMAT);
        }
        if (n) {
            for (j = 0; j < 16 && pack_header[j] == pack_name[j]; ++j) { }
            if (j == 16 || pack_header[j] < pack_name[j]) return finish(TI_E_FORMAT);
        }
        for (j = 0; j < 16; ++j) pack_name[j] = pack_header[j];
        offset = read32(pack_header + 16); length = read32(pack_header + 20);
        if (!length || offset < end || offset > file_size || length > file_size - offset)
            return finish(TI_E_FORMAT);
        end = offset + length;
        for (j = 0; j < 16 && pack_name[j] == chosen_name[j]; ++j) { }
        if (j == 16) { chosen_offset = offset; chosen_size = length; found = 1; }
    }
    if (!found) return finish(TI_E_UNAVAILABLE);
    error = ti_res_alloc(chosen_size, &handle);
    if (error) return finish(error);
    parms[0] = 2; parms[1] = file_ref;
    word(parms + 2, (uint16_t)chosen_offset); parms[4] = (uint8_t)(chosen_offset >> 16);
    if (call(0xCE)) error = TI_E_IO;
    offset = 0;
    while (!error && offset < chosen_size) {
        length = chosen_size - offset;
        j = length > 128 ? 128 : (uint8_t)length;
        if (!read_exact(io, j)) { error = TI_E_IO; break; }
        error = ti_res_write(handle, offset, io, j);
        offset += j;
    }
    if (error) ti_res_free(handle);
    else { *out = handle; *size = chosen_size; }
    error = finish(error);
    if (error && *out) { ti_res_free(*out); *out = 0; *size = 0; }
    return error;
}
