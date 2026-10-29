/* First-frame GIF streaming decoder for the A2MONO prototype.
 * Adapted from this directory's A2IMG decoder. Dictionary storage lives in
 * AUX RAM so image decoding does not consume the browser's near buffers. */
#include "mono_image.h"
#ifdef MONO_IMAGE_HOST
#include "mono_image_host.h"
#else
#include "mono_gfx.h"
#endif
#include <string.h>
#ifdef __CC65__
#pragma bss-name ("GIFBSS")
#ifndef MONO_IMAGE_HOST
#pragma code-name ("GIF")
#pragma rodata-name ("GIF")
#endif
#endif
#ifndef MONO_IMAGE_HOST
#include "mono_sample.h"
#endif

#define PREFIX_BASE 0x6000U
#define SUFFIX_BASE 0x8000U
#define STACK_BASE  0x9000U
#define NO_CODE    0xFFFFU

enum {
    S_HEADER, S_GLOBAL_PALETTE, S_BLOCK, S_EXT_LABEL, S_EXT_LENGTH,
    S_EXT_DATA, S_DESCRIPTOR, S_LOCAL_PALETTE, S_MINIMUM,
    S_DATA_LENGTH, S_DATA, S_DONE, S_ERROR
};

static uint8_t state;
static const char *error_text;
static int16_t dest_x, dest_y;
static uint16_t max_w, max_h, canvas_w, canvas_h;
static uint16_t result_w, result_h, draw_x, draw_y, want_x, scale_x;
static uint8_t row_selected;
static uint16_t frame_x, frame_y, frame_w, frame_h;
static uint8_t hold[13], hold_used;
static uint8_t palette[256];
static uint16_t palette_count, palette_byte;
static uint8_t palette_r, palette_g;
static uint8_t extension_label, extension_at;
static uint8_t transparent, transparent_index;
static uint8_t interlaced, pass;
static uint16_t pixel_x, pixel_y, rows_done;
static uint16_t clear_code, end_code, next_code, previous_code;
static uint8_t minimum_code, code_width, first_char, got_end;
static uint32_t bit_buffer;
static uint8_t bit_count, block_left;

static const uint8_t pass_start[4] = { 0, 4, 2, 1 };
static const uint8_t pass_step[4] = { 8, 8, 4, 2 };
static const uint8_t bayer[16] = {
     0,  8,  2, 10,
    12,  4, 14,  6,
     3, 11,  1,  9,
    15,  7, 13,  5
};

static void fail(const char *text)
{
    if (state != S_ERROR) {
        error_text = text;
        state = S_ERROR;
    }
}

static uint16_t word(const uint8_t *p)
{
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint16_t prefix_get(uint16_t code)
{
    uint16_t address = (uint16_t)(PREFIX_BASE + code * 2U);
    uint8_t lo = mono_aux_get(address);
    return (uint16_t)(lo | ((uint16_t)mono_aux_get(address + 1U) << 8));
}

static void dictionary_set(uint16_t code, uint16_t prefix, uint8_t suffix)
{
    uint16_t address = (uint16_t)(PREFIX_BASE + code * 2U);
    mono_aux_set(address, (uint8_t)prefix);
    mono_aux_set(address + 1U, (uint8_t)(prefix >> 8));
    mono_aux_set((uint16_t)(SUFFIX_BASE + code), suffix);
}

static void advance_x(void)
{
    ++draw_x;
    scale_x += canvas_w;
    while (scale_x >= result_w) { scale_x -= result_w; ++want_x; }
}

static void start_row(void)
{
    uint16_t y = frame_y + pixel_y;
    draw_x = want_x = scale_x = 0;
    while (want_x < frame_x && draw_x < result_w) advance_x();
    draw_y = (uint16_t)(((uint32_t)y * result_h + canvas_h - 1U) / canvas_h);
    row_selected = (uint8_t)(draw_y < result_h &&
        (uint16_t)((uint32_t)draw_y * canvas_h / result_h) == y);
}

static void emit(uint8_t index)
{
    int16_t x, y;
    uint8_t threshold;
    if (rows_done >= frame_h || pixel_y >= frame_h) {
        fail("GIF has too many pixels");
        return;
    }
    if (index >= palette_count) {
        fail("GIF palette index is invalid");
        return;
    }
    if (!pixel_x) start_row();
    if (row_selected && frame_x + pixel_x == want_x && draw_x < result_w) {
        x = (int16_t)(dest_x + (int16_t)draw_x);
        y = (int16_t)(dest_y + (int16_t)draw_y);
        if ((!transparent || index != transparent_index) &&
            x >= 0 && x < 560 && y >= 0 && y < 384) {
            threshold = (uint8_t)(bayer[((uint8_t)y & 3U) * 4U +
                                       ((uint8_t)x & 3U)] * 16U + 8U);
            mono_gfx_pixel((uint16_t)x, (uint16_t)y,
                           (uint8_t)(palette[index] < threshold));
        }
        advance_x();
    }
    ++pixel_x;
    if (pixel_x == frame_w) {
        pixel_x = 0;
        ++rows_done;
        if (interlaced) {
            pixel_y += pass_step[pass];
            while (pixel_y >= frame_h && pass < 3U) {
                ++pass;
                pixel_y = pass_start[pass];
            }
        } else {
            ++pixel_y;
        }
    }
}

static void restart(void)
{
    next_code = (uint16_t)(end_code + 1U);
    code_width = (uint8_t)(minimum_code + 1U);
    previous_code = NO_CODE;
}

static void decode_code(uint16_t code)
{
    uint16_t current, prefix, stack_used;
    if (code == clear_code) {
        restart();
        return;
    }
    if (code == end_code) {
        if (rows_done != frame_h || pixel_x != 0U) {
            fail("GIF has too few pixels");
        } else {
            got_end = 1;
        }
        return;
    }
    if (previous_code == NO_CODE) {
        if (code >= clear_code) {
            fail("GIF first LZW code is invalid");
            return;
        }
        first_char = (uint8_t)code;
        emit(first_char);
        previous_code = code;
        return;
    }
    if (code > next_code || code >= 4096U) {
        fail("GIF LZW code is invalid");
        return;
    }
    current = code;
    stack_used = 0;
    if (code == next_code) {
        mono_aux_set(STACK_BASE, first_char);
        stack_used = 1;
        current = previous_code;
    }
    while (current >= clear_code) {
        if (current <= end_code || current >= next_code || stack_used >= 4095U) {
            fail("GIF LZW chain is invalid");
            return;
        }
        mono_aux_set((uint16_t)(STACK_BASE + stack_used),
                     mono_aux_get((uint16_t)(SUFFIX_BASE + current)));
        ++stack_used;
        prefix = prefix_get(current);
        if (prefix >= current) {
            fail("GIF LZW prefix is invalid");
            return;
        }
        current = prefix;
    }
    first_char = (uint8_t)current;
    mono_aux_set((uint16_t)(STACK_BASE + stack_used), first_char);
    ++stack_used;
    while (stack_used != 0U) {
        --stack_used;
        emit(mono_aux_get((uint16_t)(STACK_BASE + stack_used)));
        if (state == S_ERROR) return;
    }
    if (next_code < 4096U) {
        dictionary_set(next_code, previous_code, first_char);
        ++next_code;
        if (code_width < 12U && next_code == (uint16_t)(1U << code_width))
            ++code_width;
    }
    previous_code = code;
}

static void lzw_byte(uint8_t value)
{
    uint16_t code;
    if (got_end) return;
    bit_buffer |= (uint32_t)value << bit_count;
    bit_count += 8U;
    while (bit_count >= code_width) {
        code = (uint16_t)(bit_buffer & ((1U << code_width) - 1U));
        bit_buffer >>= code_width;
        bit_count -= code_width;
        decode_code(code);
        if (got_end || state == S_ERROR) return;
    }
}

static void palette_byte_feed(uint8_t value)
{
    uint8_t channel = (uint8_t)(palette_byte % 3U);
    if (channel == 0U) palette_r = value;
    else if (channel == 1U) palette_g = value;
    else palette[palette_byte / 3U] = (uint8_t)(
        ((uint16_t)palette_r * 77U + (uint16_t)palette_g * 150U +
         (uint16_t)value * 29U + 128U) >> 8);
    ++palette_byte;
    if (palette_byte == palette_count * 3U)
        state = state == S_LOCAL_PALETTE ? S_MINIMUM : S_BLOCK;
}

static void step(uint8_t value)
{
    switch (state) {
    case S_HEADER:
        hold[hold_used++] = value;
        if (hold_used != 13U) break;
        if (memcmp(hold, "GIF87a", 6) && memcmp(hold, "GIF89a", 6)) {
            fail("Image is not GIF87a/GIF89a");
            break;
        }
        canvas_w = word(hold + 6);
        canvas_h = word(hold + 8);
        if (!canvas_w || !canvas_h || canvas_w > 4096U || canvas_h > 4096U ||
            (uint32_t)canvas_w * canvas_h > 4194304UL) {
            fail("GIF dimensions are unsupported");
            break;
        }
        result_w = canvas_w; result_h = canvas_h;
        if (result_w > max_w || result_h > max_h) {
            result_w = max_w;
            result_h = (uint16_t)((uint32_t)canvas_h * max_w / canvas_w);
            if (result_h > max_h) {
                result_h = max_h;
                result_w = (uint16_t)((uint32_t)canvas_w * max_h / canvas_h);
            }
            if (!result_w) result_w = 1;
            if (!result_h) result_h = 1;
        }
        palette_count = 0;
        if (hold[10] & 0x80U) {
            palette_count = (uint16_t)(2U << (hold[10] & 7U));
            palette_byte = 0;
            state = S_GLOBAL_PALETTE;
        } else state = S_BLOCK;
        break;
    case S_GLOBAL_PALETTE:
    case S_LOCAL_PALETTE:
        palette_byte_feed(value);
        break;
    case S_BLOCK:
        if (value == 0x21U) state = S_EXT_LABEL;
        else if (value == 0x2CU) {
            state = S_DESCRIPTOR;
            hold_used = 0;
        } else if (value == 0x3BU) fail("GIF has no image frame");
        else fail("GIF block marker is invalid");
        break;
    case S_EXT_LABEL:
        extension_label = value;
        extension_at = 0;
        state = S_EXT_LENGTH;
        break;
    case S_EXT_LENGTH:
        if (!value) {
            if (extension_label == 0xF9U && extension_at != 4U)
                fail("GIF graphics control is invalid");
            else state = S_BLOCK;
        } else {
            if (extension_label == 0xF9U &&
                (value != 4U || extension_at != 0U)) {
                fail("GIF graphics control is invalid");
                break;
            }
            block_left = value;
            state = S_EXT_DATA;
        }
        break;
    case S_EXT_DATA:
        if (extension_label == 0xF9U) {
            if (extension_at == 0U) transparent = (uint8_t)(value & 1U);
            if (extension_at == 3U) transparent_index = value;
        }
        ++extension_at;
        --block_left;
        if (!block_left) state = S_EXT_LENGTH;
        break;
    case S_DESCRIPTOR:
        hold[hold_used++] = value;
        if (hold_used != 9U) break;
        frame_x = word(hold);
        frame_y = word(hold + 2);
        frame_w = word(hold + 4);
        frame_h = word(hold + 6);
        if (!frame_w || !frame_h || frame_x >= canvas_w || frame_y >= canvas_h ||
            frame_w > canvas_w - frame_x || frame_h > canvas_h - frame_y) {
            fail("GIF frame rectangle is invalid");
            break;
        }
        pixel_x = pixel_y = rows_done = 0;
        pass = 0;
        interlaced = (uint8_t)(hold[8] & 0x40U);
        if (hold[8] & 0x80U) {
            palette_count = (uint16_t)(2U << (hold[8] & 7U));
            palette_byte = 0;
            state = S_LOCAL_PALETTE;
        } else if (!palette_count) fail("GIF frame has no palette");
        else state = S_MINIMUM;
        break;
    case S_MINIMUM:
        if (value < 2U || value > 8U) {
            fail("GIF LZW minimum is invalid");
            break;
        }
        minimum_code = value;
        clear_code = (uint16_t)(1U << value);
        end_code = (uint16_t)(clear_code + 1U);
        bit_buffer = 0;
        bit_count = got_end = 0;
        restart();
        state = S_DATA_LENGTH;
        break;
    case S_DATA_LENGTH:
        if (!value) {
            if (!got_end) fail("GIF LZW end code is missing");
            else state = S_DONE;
        } else {
            block_left = value;
            state = S_DATA;
        }
        break;
    case S_DATA:
        lzw_byte(value);
        --block_left;
        if (state != S_ERROR && !block_left) state = S_DATA_LENGTH;
        break;
    default:
        break;
    }
}

void mono_image_begin(int16_t x, int16_t y, uint16_t width, uint16_t height)
{
    state = S_HEADER;
    error_text = 0;
    dest_x = x;
    dest_y = y;
    max_w = width;
    max_h = height;
    canvas_w = canvas_h = result_w = result_h = 0;
    hold_used = transparent = transparent_index = 0;
    if (!width || !height || width > 560U || height > 384U ||
        x < -560 || x > 560 || y < -384 || y > 384)
        fail("Invalid image destination");
}

uint8_t mono_image_feed(const uint8_t *data, uint16_t length)
{
    if (!data && length) fail("Missing image input");
    while (length && state != S_DONE && state != S_ERROR) {
        step(*data++);
        --length;
    }
    return mono_image_status();
}

uint8_t mono_image_finish(void)
{
    if (state != S_DONE && state != S_ERROR) fail("GIF download is incomplete");
    return mono_image_status();
}

uint8_t mono_image_status(void)
{
    if (state == S_DONE) return MONO_IMAGE_DONE;
    if (state == S_ERROR) return MONO_IMAGE_ERROR;
    return MONO_IMAGE_MORE;
}

const char *mono_image_error(void) { return error_text; }
uint16_t mono_image_width(void) { return result_w; }
uint16_t mono_image_height(void) { return result_h; }
