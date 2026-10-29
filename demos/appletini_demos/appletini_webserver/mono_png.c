/* Native PNG/zlib/DEFLATE decoder for A2MONO. No heap or conversion service.
 * The compact canonical Huffman decoder follows RFC1951. All compressed
 * history and filter-row storage uses AUX expansion bank 1. */
#include "mono_png.h"
#ifdef MONO_PNG_HOST
#include "mono_png_host.h"
#else
#include "mono_gfx.h"
#endif
#include <string.h>
#ifdef __CC65__
#pragma bss-name ("PNGBSS")
#ifndef MONO_PNG_HOST
#pragma code-name ("PNG")
#pragma rodata-name ("PNG")
#endif
#endif

extern uint8_t mono_source_get(uint16_t offset);

static const char *error_text;
static uint16_t input_at, input_length, chunk_left;
static uint8_t chunk_type[4];
static uint32_t crc;
static uint8_t failed;
static uint16_t source_w, source_h, row_bytes;
static uint16_t result_w, result_h;
static int16_t dest_x, dest_y;
static uint8_t depth, color_type, channels, bytes_per_pixel;
static uint8_t palette[256], alpha[256];
static uint16_t palette_count;
static uint8_t transparent_key, key[3];
static uint16_t literal_count[16], literal_symbol[288];
static uint16_t distance_count[16], distance_symbol[32];
static uint16_t code_count[16], code_symbol[19];
static uint8_t lengths[320];
static uint32_t bit_buffer, output_count, output_limit;
static uint8_t bit_count;
static uint16_t history_at, adler_a, adler_b;
static uint8_t filter, pixel[4], above_left[4], previous[4];
static uint16_t row_at, sample_x, sample_y;
static uint16_t draw_x, draw_y, want_x, want_y, scale_x, scale_y;

static const uint8_t signature[8] = {137,80,78,71,13,10,26,10};
static const uint8_t code_order[19] = {
    16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15
};
static const uint16_t length_base[29] = {
    3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,
    67,83,99,115,131,163,195,227,258
};
static const uint8_t length_extra[29] = {
    0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0
};
static const uint16_t distance_base[30] = {
    1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,
    1025,1537,2049,3073,4097,6145,8193,12289,16385,24577
};
static const uint8_t distance_extra[30] = {
    0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13
};
static const uint8_t bayer[16] = {
    0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5
};

static void fail(const char *text)
{
    if (!failed) error_text = text;
    failed = 1;
}

static uint8_t input_byte(void)
{
    if (input_at >= input_length) {
        fail("PNG input is truncated");
        return 0;
    }
    return mono_source_get(input_at++);
}

static uint32_t input_word(void)
{
    uint8_t i;
    uint32_t n = 0;
    for (i = 0; i < 4U; ++i) n = (n << 8) | input_byte();
    return n;
}

static void crc_byte(uint8_t value)
{
    uint8_t i;
    crc ^= value;
    for (i = 0; i < 8U; ++i)
        crc = (crc >> 1) ^ ((crc & 1U) ? 0xEDB88320UL : 0UL);
}

static uint8_t chunk_byte(void)
{
    uint8_t value;
    if (!chunk_left) {
        fail("PNG chunk is truncated");
        return 0;
    }
    value = input_byte();
    --chunk_left;
    crc_byte(value);
    return value;
}

static uint32_t chunk_word(void)
{
    uint8_t i;
    uint32_t n = 0;
    for (i = 0; i < 4U; ++i) n = (n << 8) | chunk_byte();
    return n;
}

static uint8_t chunk_is(const char *name)
{
    return (uint8_t)(memcmp(chunk_type, name, 4) == 0);
}

static void chunk_end(void)
{
    uint32_t checksum;
    if (chunk_left) {
        fail("PNG chunk has extra bytes");
        return;
    }
    checksum = input_word();
    if (!failed && checksum != (crc ^ 0xFFFFFFFFUL)) fail("PNG CRC failed");
}

static void chunk_header(void)
{
    uint32_t length;
    uint8_t i;
    length = input_word();
    if (failed || length > 65535UL || input_length - input_at < 8U ||
        length > (uint32_t)(input_length - input_at - 8U)) {
        fail("PNG chunk length is invalid");
        return;
    }
    chunk_left = (uint16_t)length;
    crc = 0xFFFFFFFFUL;
    for (i = 0; i < 4U; ++i) {
        chunk_type[i] = input_byte();
        crc_byte(chunk_type[i]);
        if (!((chunk_type[i] >= 'A' && chunk_type[i] <= 'Z') ||
              (chunk_type[i] >= 'a' && chunk_type[i] <= 'z')))
            fail("PNG chunk name is invalid");
    }
}

static void skip_chunk(void)
{
    if (!(chunk_type[0] & 32U)) {
        fail("PNG critical chunk is unsupported");
        return;
    }
    while (chunk_left && !failed) chunk_byte();
    if (!failed) chunk_end();
}

static uint8_t compressed_byte(void)
{
    while (!chunk_left && !failed) {
        chunk_end();
        if (failed) return 0;
        chunk_header();
        if (!failed && !chunk_is("IDAT")) fail("PNG IDAT ended early");
    }
    return failed ? 0 : chunk_byte();
}

static uint16_t bits(uint8_t count)
{
    uint16_t value;
    while (bit_count < count && !failed) {
        bit_buffer |= (uint32_t)compressed_byte() << bit_count;
        bit_count += 8U;
    }
    value = (uint16_t)(bit_buffer & ((1UL << count) - 1UL));
    bit_buffer >>= count;
    bit_count -= count;
    return value;
}

static void tree(const uint8_t *lens, uint16_t size,
                  uint16_t *counts, uint16_t *symbols)
{
    uint16_t offset[16];
    uint16_t i;
    uint8_t len;
    int32_t left = 1;
    memset(counts, 0, 32);
    for (i = 0; i < size; ++i) {
        if (lens[i] > 15U) { fail("Deflate length is invalid"); return; }
        ++counts[lens[i]];
    }
    for (len = 1; len < 16U; ++len) {
        left = (left << 1) - counts[len];
        if (left < 0) { fail("Deflate tree is invalid"); return; }
    }
    offset[1] = 0;
    for (len = 1; len < 15U; ++len) offset[len + 1U] = offset[len] + counts[len];
    for (i = 0; i < size; ++i)
        if (lens[i]) symbols[offset[lens[i]]++] = i;
}

static uint16_t symbol(const uint16_t *counts, const uint16_t *symbols)
{
    uint16_t code = 0, first = 0, index = 0, count;
    uint8_t len;
    for (len = 1; len < 16U && !failed; ++len) {
        code |= bits(1);
        count = counts[len];
        if (code >= first && code - first < count)
            return symbols[index + code - first];
        index += count;
        first = (uint16_t)((first + count) << 1);
        code <<= 1;
    }
    fail("Deflate symbol is invalid");
    return 0;
}

static void fixed_trees(void)
{
    uint16_t i;
    for (i = 0; i < 288U; ++i)
        lengths[i] = i < 144U ? 8U : i < 256U ? 9U : i < 280U ? 7U : 8U;
    tree(lengths, 288, literal_count, literal_symbol);
    for (i = 0; i < 32U; ++i) lengths[i] = 5;
    tree(lengths, 32, distance_count, distance_symbol);
}

static void dynamic_trees(void)
{
    uint16_t literals, distances, total, at, repeat, value;
    uint8_t count, i, previous = 0;
    literals = (uint16_t)(257U + bits(5));
    distances = (uint16_t)(1U + bits(5));
    count = (uint8_t)(4U + bits(4));
    if (literals > 286U) { fail("Deflate literal count is invalid"); return; }
    memset(lengths, 0, 19);
    for (i = 0; i < count; ++i) lengths[code_order[i]] = (uint8_t)bits(3);
    tree(lengths, 19, code_count, code_symbol);
    total = literals + distances;
    at = 0;
    while (at < total && !failed) {
        value = symbol(code_count, code_symbol);
        if (value < 16U) {
            previous = (uint8_t)value;
            lengths[at++] = previous;
        } else {
            if (value == 16U) {
                if (!at) { fail("Deflate repeat has no predecessor"); return; }
                repeat = (uint16_t)(3U + bits(2));
            } else if (value == 17U) {
                repeat = (uint16_t)(3U + bits(3));
                previous = 0;
            } else {
                repeat = (uint16_t)(11U + bits(7));
                previous = 0;
            }
            if (repeat > total - at) { fail("Deflate repeat is too long"); return; }
            while (repeat--) lengths[at++] = previous;
        }
    }
    if (!failed && !lengths[256]) fail("Deflate end symbol is missing");
    if (!failed) tree(lengths, literals, literal_count, literal_symbol);
    if (!failed) tree(lengths + literals, distances, distance_count, distance_symbol);
}

static uint8_t blend(uint8_t gray, uint8_t opacity)
{
    uint16_t v = (uint16_t)(255U - gray) * opacity + 127U;
    return (uint8_t)(255U - ((v + 1U + (v >> 8)) >> 8));
}

static void draw_sample(uint8_t gray, uint8_t opacity)
{
    int16_t x, y;
    uint8_t threshold;
    if (sample_y == want_y && sample_x == want_x && draw_y < result_h &&
        draw_x < result_w) {
        x = dest_x + (int16_t)draw_x;
        y = dest_y + (int16_t)draw_y;
        if (opacity && x >= 0 && x < 560 && y >= 0 && y < 384) {
            if (opacity != 255U) gray = blend(gray, opacity);
            threshold = (uint8_t)(bayer[((uint8_t)y & 3U) * 4U +
                                       ((uint8_t)x & 3U)] * 16U + 8U);
            mono_gfx_pixel((uint16_t)x, (uint16_t)y, (uint8_t)(gray < threshold));
        }
        ++draw_x;
        scale_x += source_w;
        while (scale_x >= result_w) { scale_x -= result_w; ++want_x; }
    }
    ++sample_x;
}

static void reconstructed(uint8_t value, uint16_t byte_at)
{
    uint8_t shift, sample, mask, gray, opacity;
    uint8_t channel;
    if (color_type == 0U || color_type == 3U) {
        mask = (uint8_t)((1U << depth) - 1U);
        shift = 8;
        while (shift && sample_x < source_w) {
            shift -= depth;
            sample = (uint8_t)((value >> shift) & mask);
            opacity = 255;
            if (color_type == 3U) {
                if (sample >= palette_count) { fail("PNG palette index is invalid"); return; }
                gray = palette[sample];
                opacity = alpha[sample];
            } else {
                gray = depth == 8U ? sample : depth == 4U ?
                    (uint8_t)(sample * 17U) : depth == 2U ?
                    (uint8_t)(sample * 85U) : sample ? 255U : 0U;
                if (transparent_key && sample == key[0]) opacity = 0;
            }
            draw_sample(gray, opacity);
        }
    } else {
        channel = (uint8_t)(byte_at % channels);
        pixel[channel] = value;
        if (channel == channels - 1U) {
            opacity = 255;
            if (color_type == 4U) {
                gray = pixel[0];
                opacity = pixel[1];
            } else {
                gray = (uint8_t)(((uint16_t)pixel[0] * 77U +
                                  (uint16_t)pixel[1] * 150U +
                                  (uint16_t)pixel[2] * 29U + 128U) >> 8);
                if (color_type == 6U) opacity = pixel[3];
                else if (transparent_key && pixel[0] == key[0] &&
                         pixel[1] == key[1] && pixel[2] == key[2]) opacity = 0;
            }
            draw_sample(gray, opacity);
        }
    }
}

static uint8_t paeth(uint8_t a, uint8_t b, uint8_t c)
{
    int16_t p = (int16_t)a + b - c;
    int16_t aa = p - a, bb = p - b, cc = p - c;
    if (aa < 0) aa = -aa;
    if (bb < 0) bb = -bb;
    if (cc < 0) cc = -cc;
    return aa <= bb && aa <= cc ? a : bb <= cc ? b : c;
}

static void output_byte(uint8_t value)
{
    uint8_t up, left, upper_left, channel, predictor = 0;
    uint16_t byte_at, old;
    if (output_count >= output_limit) { fail("PNG has too much pixel data"); return; }
    mono_bank_set(1, (uint16_t)(0x2000U + history_at), value);
    history_at = (uint16_t)((history_at + 1U) & 32767U);
    ++output_count;
    old = adler_a;
    adler_a += value;
    if (adler_a < old) adler_a += 15U;
    if (adler_a >= 65521U) adler_a -= 65521U;
    old = adler_b;
    adler_b += adler_a;
    if (adler_b < old) adler_b += 15U;
    if (adler_b >= 65521U) adler_b -= 65521U;
    if (!row_at) {
        filter = value;
        if (filter > 4U) fail("PNG filter is invalid");
        memset(previous, 0, 4);
        memset(above_left, 0, 4);
    } else {
        byte_at = row_at - 1U;
        channel = (uint8_t)(byte_at % bytes_per_pixel);
        up = sample_y ? mono_bank_get(1, (uint16_t)(0xA000U + byte_at)) : 0;
        left = previous[channel];
        upper_left = above_left[channel];
        if (filter == 1U) predictor = left;
        else if (filter == 2U) predictor = up;
        else if (filter == 3U) predictor = (uint8_t)(((uint16_t)left + up) >> 1);
        else if (filter == 4U) predictor = paeth(left, up, upper_left);
        value += predictor;
        mono_bank_set(1, (uint16_t)(0xA000U + byte_at), value);
        previous[channel] = value;
        above_left[channel] = up;
        reconstructed(value, byte_at);
    }
    ++row_at;
    if (row_at > row_bytes) {
        if (sample_y == want_y && draw_y < result_h) {
            ++draw_y;
            scale_y += source_h;
            while (scale_y >= result_h) { scale_y -= result_h; ++want_y; }
        }
        ++sample_y;
        row_at = sample_x = draw_x = want_x = scale_x = 0;
    }
}

static void inflate(void)
{
    uint8_t last, type, check_a, check_b;
    uint16_t length, inverse, code, distance, i;
    uint32_t checksum;
    check_a = compressed_byte();
    check_b = compressed_byte();
    if ((check_a & 15U) != 8U || (check_a >> 4) > 7U ||
        (((uint16_t)check_a << 8) | check_b) % 31U || (check_b & 32U)) {
        fail("PNG zlib header is invalid");
        return;
    }
    do {
        last = (uint8_t)bits(1);
        type = (uint8_t)bits(2);
        if (type == 0U) {
            bit_buffer = 0; bit_count = 0;
            length = compressed_byte();
            length |= (uint16_t)compressed_byte() << 8;
            inverse = compressed_byte();
            inverse |= (uint16_t)compressed_byte() << 8;
            if ((uint16_t)(length ^ inverse) != 65535U) fail("Deflate stored block is invalid");
            while (length-- && !failed) output_byte(compressed_byte());
        } else if (type == 1U || type == 2U) {
            if (type == 1U) fixed_trees(); else dynamic_trees();
            while (!failed) {
                code = symbol(literal_count, literal_symbol);
                if (failed || code == 256U) break;
                if (code < 256U) output_byte((uint8_t)code);
                else {
                    if (code > 285U) { fail("Deflate length code is invalid"); break; }
                    code -= 257U;
                    length = length_base[code] + bits(length_extra[code]);
                    code = symbol(distance_count, distance_symbol);
                    if (failed || code >= 30U) { fail("Deflate distance code is invalid"); break; }
                    distance = distance_base[code] + bits(distance_extra[code]);
                    if (!distance || distance > 32768U || distance > output_count) {
                        fail("Deflate distance is invalid"); break;
                    }
                    for (i = 0; i < length && !failed; ++i)
                        output_byte(mono_bank_get(1, (uint16_t)(0x2000U +
                            ((history_at - distance) & 32767U))));
                }
            }
        } else fail("Deflate block type is invalid");
    } while (!last && !failed);
    bit_buffer = 0; bit_count = 0;
    checksum = 0;
    for (i = 0; i < 4U && !failed; ++i) checksum = (checksum << 8) | compressed_byte();
    if (!failed && checksum != (((uint32_t)adler_b << 16) | adler_a)) fail("PNG Adler32 failed");
    if (!failed && output_count != output_limit) fail("PNG pixel data is incomplete");
}

static void read_palette(void)
{
    uint16_t i;
    uint8_t r, g, b;
    if (!chunk_left || chunk_left > 768U || chunk_left % 3U || color_type == 0U || color_type == 4U) {
        fail("PNG palette is invalid"); return;
    }
    palette_count = chunk_left / 3U;
    for (i = 0; i < palette_count; ++i) {
        r = chunk_byte(); g = chunk_byte(); b = chunk_byte();
        palette[i] = (uint8_t)(((uint16_t)r * 77U + (uint16_t)g * 150U +
                               (uint16_t)b * 29U + 128U) >> 8);
    }
    chunk_end();
}

static void read_transparency(void)
{
    uint16_t i;
    uint8_t high;
    if (color_type == 3U) {
        if (!palette_count || chunk_left > palette_count) { fail("PNG transparency is invalid"); return; }
        i = 0;
        while (chunk_left) alpha[i++] = chunk_byte();
    } else if ((color_type == 0U && chunk_left == 2U) ||
               (color_type == 2U && chunk_left == 6U)) {
        transparent_key = 1;
        i = 0;
        while (chunk_left) {
            high = chunk_byte(); key[i++] = chunk_byte();
            if (high) transparent_key = 0;
        }
    } else { fail("PNG transparency is invalid"); return; }
    chunk_end();
}

static void read_header(uint16_t max_width, uint16_t max_height)
{
    uint32_t w, h, bytes;
    uint8_t compression, filtering, interlace;
    if (!chunk_is("IHDR") || chunk_left != 13U) { fail("PNG IHDR is missing"); return; }
    w = chunk_word(); h = chunk_word();
    depth = chunk_byte(); color_type = chunk_byte();
    compression = chunk_byte(); filtering = chunk_byte(); interlace = chunk_byte();
    if (!w || !h || w > 4096UL || h > 4096UL || w * h > 4194304UL ||
        compression || filtering || interlace) { fail("PNG size or interlace is unsupported"); return; }
    if ((color_type == 0U || color_type == 3U) &&
        (depth == 1U || depth == 2U || depth == 4U || depth == 8U)) channels = 1;
    else if (depth == 8U && color_type == 2U) channels = 3;
    else if (depth == 8U && color_type == 4U) channels = 2;
    else if (depth == 8U && color_type == 6U) channels = 4;
    else { fail("PNG pixel format is unsupported"); return; }
    source_w = (uint16_t)w; source_h = (uint16_t)h;
    bytes = (w * channels * depth + 7U) >> 3;
    if (bytes > 8192UL) { fail("PNG scanline exceeds AUX storage"); return; }
    row_bytes = (uint16_t)bytes;
    bytes_per_pixel = channels;
    output_limit = (bytes + 1U) * h;
    result_w = source_w; result_h = source_h;
    if (result_w > max_width || result_h > max_height) {
        result_w = max_width;
        result_h = (uint16_t)(h * max_width / w);
        if (result_h > max_height) {
            result_h = max_height;
            result_w = (uint16_t)(w * max_height / h);
        }
        if (!result_w) result_w = 1;
        if (!result_h) result_h = 1;
    }
    chunk_end();
}

uint8_t mono_png_decode(int16_t x, int16_t y, uint16_t width,
                        uint16_t height, uint16_t encoded_length)
{
    uint8_t i, ended = 0;
    failed = 0; error_text = 0;
    input_at = 0; input_length = encoded_length;
    dest_x = x; dest_y = y;
    result_w = result_h = 0;
    palette_count = transparent_key = 0;
    memset(alpha, 255, sizeof(alpha));
    if (!width || width > 560U || !height || height > 384U ||
        x < -560 || x > 560 || y < -384 || y > 384) {
        fail("PNG image box is invalid"); return 0;
    }
    for (i = 0; i < 8U; ++i)
        if (input_byte() != signature[i]) fail("Image is not PNG");
    if (failed) return 0;
    chunk_header();
    if (!failed) read_header(width, height);
    while (!failed) {
        chunk_header();
        if (failed || chunk_is("IDAT")) break;
        if (chunk_is("PLTE")) read_palette();
        else if (chunk_is("tRNS")) read_transparency();
        else skip_chunk();
    }
    if (!failed && color_type == 3U && !palette_count) fail("PNG palette is missing");
    bit_count = 0; bit_buffer = output_count = 0;
    history_at = adler_b = 0; adler_a = 1;
    row_at = sample_x = sample_y = draw_x = draw_y = want_x = want_y = scale_x = scale_y = 0;
    if (!failed) inflate();
    if (!failed && chunk_left) fail("PNG zlib stream has extra data");
    if (!failed) chunk_end();
    while (!failed && !ended) {
        chunk_header();
        if (failed) break;
        if (chunk_is("IEND")) {
            if (chunk_left) fail("PNG IEND is invalid");
            else { chunk_end(); ended = 1; }
        } else if (chunk_is("IDAT")) {
            if (chunk_left) fail("PNG has extra IDAT data");
            else chunk_end();
        } else skip_chunk();
    }
    if (!failed && input_at != input_length) fail("PNG has trailing bytes");
    return (uint8_t)!failed;
}

const char *mono_png_error(void) { return error_text; }
uint16_t mono_png_width(void) { return result_w; }
uint16_t mono_png_height(void) { return result_h; }
