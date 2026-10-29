/* SPDX-License-Identifier: MIT */
#include "mono_jpeg.h"
#include "mono_gfx.h"
#include "third_party/picojpeg/picojpeg.h"

#ifdef __CC65__
#pragma code-name ("JPEG")
#pragma rodata-name ("JPEG")
#pragma data-name ("JPEG")
#pragma bss-name ("JPEGBSS")
#endif

extern uint8_t mono_source_get(uint16_t offset);
static pjpeg_image_info_t image;
static uint16_t source_offset, source_length;
static const char *jpeg_error;
static const uint8_t bayer[16] = {
    8,136,40,168,200,72,232,104,56,184,24,152,248,120,216,88
};

const char *mono_jpeg_error(void)
{
    return jpeg_error ? jpeg_error : "Invalid JPEG";
}

static unsigned char need_bytes(unsigned char *buffer, unsigned char capacity,
                                 unsigned char *read_count, void *unused)
{
    uint8_t n = 0;
    (void)unused;
    while (n < capacity && source_offset < source_length)
        buffer[n++] = mono_source_get(source_offset++);
    *read_count = n;
    return n ? 0 : PJPG_STREAM_READ_ERROR;
}

static uint16_t ceiling_scale(uint16_t value, uint16_t output,
                              uint16_t input)
{
    return (uint16_t)(((uint32_t)value*output + input-1U) / input);
}

static void draw_mcu(uint16_t source_x, uint16_t source_y,
                     uint16_t out_width, uint16_t out_height,
                     int16_t x, int16_t y)
{
    uint16_t end_x, end_y, dx, dy, sx, sy, remainder;
    uint16_t first_x, first_y, last_x, last_y;
    uint8_t offset, gray;
    int16_t px, py;
    uint32_t scaled;
    end_x = source_x + image.m_MCUWidth;
    end_y = source_y + image.m_MCUHeight;
    if (end_x > (uint16_t)image.m_width) end_x = image.m_width;
    if (end_y > (uint16_t)image.m_height) end_y = image.m_height;
    first_x = ceiling_scale(source_x,out_width,image.m_width);
    first_y = ceiling_scale(source_y,out_height,image.m_height);
    last_x = ceiling_scale(end_x,out_width,image.m_width);
    last_y = ceiling_scale(end_y,out_height,image.m_height);
    for (dy = first_y; dy < last_y; ++dy) {
        py = y + dy;
        if (py < 0 || py >= (int16_t)MONO_HEIGHT) continue;
        sy = (uint16_t)((uint32_t)dy*image.m_height/out_height)-source_y;
        scaled = (uint32_t)first_x*image.m_width;
        sx = (uint16_t)(scaled/out_width)-source_x;
        remainder = (uint16_t)(scaled%out_width);
        for (dx = first_x; dx < last_x; ++dx) {
            px = x + dx;
            if (px >= 0 && px < (int16_t)MONO_WIDTH) {
                offset = (uint8_t)(((sy & 8U) << 4) +
                          ((sx & 8U) << 3) + ((sy & 7U) << 3) + (sx & 7U));
                gray = image.m_pMCUBufR[offset];
                mono_gfx_pixel(px,py,gray <=
                    bayer[((uint8_t)py & 3U)*4U+((uint8_t)px & 3U)]);
            }
            if (dx+1U != last_x) {
                remainder += image.m_width;
                while (remainder >= out_width) {
                    remainder -= out_width;
                    ++sx;
                }
            }
        }
    }
}

uint8_t mono_jpeg_decode(int16_t x, int16_t y, uint16_t max_width,
                        uint16_t max_height, uint16_t encoded_length)
{
    uint16_t width, height, source_x, source_y, column, row;
    uint8_t status;
    jpeg_error = 0;
    source_offset = 0;
    source_length = encoded_length;
    if (!max_width || !max_height || encoded_length < 4U ||
        mono_source_get(0) != 0xFF || mono_source_get(1) != 0xD8 ||
        mono_source_get(encoded_length-2U) != 0xFF ||
        mono_source_get(encoded_length-1U) != 0xD9) {
        jpeg_error = "JPEG is truncated or has no SOI/EOI";
        return 0;
    }
    status = pjpeg_decode_init(&image,need_bytes,0,0);
    if (status) {
        jpeg_error = status == PJPG_UNSUPPORTED_MODE ?
            "Progressive JPEG is not supported" : "Unsupported or invalid JPEG";
        return 0;
    }
    if (max_width > MONO_WIDTH) max_width = MONO_WIDTH;
    if (max_height > MONO_HEIGHT) max_height = MONO_HEIGHT;
    width = image.m_width;
    height = image.m_height;
    if (width > max_width) {
        height = (uint16_t)((uint32_t)height*max_width/width);
        width = max_width;
    }
    if (height > max_height) {
        width = (uint16_t)((uint32_t)width*max_height/height);
        height = max_height;
    }
    if (!width) width = 1;
    if (!height) height = 1;
    source_y = 0;
    for (row = 0; row < (uint16_t)image.m_MCUSPerCol; ++row) {
        source_x = 0;
        for (column = 0; column < (uint16_t)image.m_MCUSPerRow; ++column) {
            status = pjpeg_decode_mcu();
            if (status) {
                jpeg_error = "JPEG entropy data is invalid or truncated";
                return 0;
            }
            draw_mcu(source_x,source_y,width,height,x,y);
            source_x += image.m_MCUWidth;
        }
        source_y += image.m_MCUHeight;
    }
    return 1;
}
