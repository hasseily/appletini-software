#include "internal.h"
#include "libtini/graphics.h"
#include "graphics_internal.h"

static uint8_t pixels[128], destination[128], mask_bits[32];

static uint8_t get_pixel(const uint8_t *row, uint16_t x)
{ return x & 1 ? row[x / 2] & 15 : row[x / 2] >> 4; }
static void set_pixel(uint8_t *row, uint16_t x, uint8_t color)
{
    if (x & 1) row[x / 2] = (uint8_t)((row[x / 2] & 0xF0) | color);
    else row[x / 2] = (uint8_t)((row[x / 2] & 15) | (color << 4));
}

static ti_error blit(ti_surface *d, int16_t x, int16_t y, const ti_surface *s,
                     const ti_rect *source, uint8_t key, ti_handle mask, uint32_t mask_offset)
{
    ti_rect r;
    int16_t sx, sy;
    uint16_t width, height, yy, xx, chunk, source_x, dest_x, src_bytes, dst_bytes, i;
    uint8_t color, visible;
    ti_error e = ti_gfx_surface_valid(d);
    if (e) return e;
    e = ti_gfx_surface_valid(s); if (e) return e;
    if (d->pixels == s->pixels || (mask && mask == d->pixels) ||
        (key > 15 && key != 255)) return TI_E_ARGUMENT;
    if (mask) {
        if (mask_offset > 0xFFFFFFFFUL - (uint32_t)((s->width + 7) / 8) * s->height) return TI_E_RANGE;
        e = ti_res_read(mask, mask_offset + (uint32_t)((s->width + 7) / 8) * s->height, 0, 0);
        if (e) return e;
    }
    r.x = r.y = 0; r.width = s->width; r.height = s->height;
    if (source) { if (!ti_near_valid(source, sizeof(*source), 0)) return TI_E_ARGUMENT; r = *source; }
    if (r.x < 0 || r.y < 0 || r.x > (int16_t)s->width || r.y > (int16_t)s->height ||
        r.width > s->width - r.x || r.height > s->height - r.y) return TI_E_RANGE;
    sx = r.x; sy = r.y;
    r.x = x; r.y = y;
    if (!ti_gfx_clip(d, &r)) return TI_OK;
    sx += r.x - x; sy += r.y - y; width = r.width; height = r.height;
    for (yy = 0; yy < height; ++yy) for (xx = 0; xx < width; xx += chunk) {
        chunk = width - xx > 240 ? 240 : width - xx;
        source_x = (uint16_t)sx + xx; dest_x = (uint16_t)r.x + xx;
        src_bytes = ((source_x & 1) + chunk + 1) / 2;
        dst_bytes = ((dest_x & 1) + chunk + 1) / 2;
        e = ti_res_read(s->pixels, s->offset + (uint32_t)((uint16_t)sy + yy) * s->stride + source_x / 2, pixels, src_bytes);
        if (e) return e;
        e = ti_res_read(d->pixels, d->offset + (uint32_t)((uint16_t)r.y + yy) * d->stride + dest_x / 2, destination, dst_bytes);
        if (e) return e;
        if (mask) {
            e = ti_res_read(mask, mask_offset + (uint32_t)((uint16_t)sy + yy) * ((s->width + 7) / 8) + source_x / 8,
                            mask_bits, (uint16_t)(((source_x & 7) + chunk + 7) / 8));
            if (e) return e;
        }
        for (i = 0; i < chunk; ++i) {
            color = get_pixel(pixels, (source_x & 1) + i);
            visible = mask ? (mask_bits[((source_x & 7) + i) / 8] & (128 >> (((source_x & 7) + i) & 7))) != 0 : color != key;
            if (visible) set_pixel(destination, (dest_x & 1) + i, color);
        }
        e = ti_res_write(d->pixels, d->offset + (uint32_t)((uint16_t)r.y + yy) * d->stride + dest_x / 2, destination, dst_bytes);
        if (e) return e;
    }
    return TI_OK;
}

ti_error ti_gfx_blit(ti_surface *d, int16_t x, int16_t y, const ti_surface *s, const ti_rect *r, uint8_t key)
{ return blit(d, x, y, s, r, key, 0, 0); }

ti_error ti_gfx_sprite(ti_surface *d, int16_t x, int16_t y, const ti_sprite *sprite)
{
    if (!sprite || !ti_near_valid(sprite, sizeof(*sprite), 0)) return TI_E_ARGUMENT;
    return blit(d, x, y, &sprite->image, 0, 0, sprite->mask, sprite->mask_offset);
}

ti_error ti_gfx_map(ti_surface *d, const ti_rect *viewport, const ti_tileset *t,
                    const ti_tilemap *m, uint16_t camera_x, uint16_t camera_y)
{
    ti_rect v, tile;
    uint16_t yy, xx, w, h, wx, wy, col, row;
    uint8_t id;
    ti_error e = ti_gfx_surface_valid(d);
    if (e) return e;
    if (!viewport || !t || !m || !ti_near_valid(viewport, sizeof(*viewport), 0) ||
        !ti_near_valid(t, sizeof(*t), 0) || !ti_near_valid(m, sizeof(*m), 0)) return TI_E_ARGUMENT;
    e = ti_gfx_surface_valid(&t->image); if (e) return e;
    if (!t->tile_width || !t->tile_height || !t->columns || !t->count || t->count > 256 ||
        (uint16_t)t->columns * t->tile_width > t->image.width ||
        (uint16_t)((t->count + t->columns - 1) / t->columns) * t->tile_height > t->image.height ||
        !m->columns || m->columns > 256 || !m->rows || m->rows > 256) return TI_E_RANGE;
    v = *viewport;
    if (!ti_gfx_clip(d, &v)) return TI_OK;
    if ((uint32_t)camera_x + v.width + (uint16_t)(v.x - viewport->x) > 65535UL ||
        (uint32_t)camera_y + v.height + (uint16_t)(v.y - viewport->y) > 65535UL) return TI_E_RANGE;
    if (m->offset > 0xFFFFFFFFUL - (uint32_t)m->columns * m->rows) return TI_E_RANGE;
    e = ti_res_read(m->cells, m->offset + (uint32_t)m->columns * m->rows, 0, 0);
    if (e) return e;
    for (yy = 0; yy < v.height; yy += h) {
        wy = camera_y + yy + (uint16_t)(v.y - viewport->y);
        h = t->tile_height - wy % t->tile_height;
        if (h > v.height - yy) h = v.height - yy;
        for (xx = 0; xx < v.width; xx += w) {
            wx = camera_x + xx + (uint16_t)(v.x - viewport->x);
            w = t->tile_width - wx % t->tile_width;
            if (w > v.width - xx) w = v.width - xx;
            col = wx / t->tile_width; row = wy / t->tile_height;
            if (col >= m->columns || row >= m->rows) {
                e = ti_gfx_rect(d, v.x + xx, v.y + yy, w, h, 0);
            } else {
                e = ti_res_read(m->cells, m->offset + (uint32_t)row * m->columns + col, &id, 1);
                if (e) return e;
                if (id >= t->count) return TI_E_RANGE;
                tile.x = (id % t->columns) * t->tile_width + wx % t->tile_width;
                tile.y = (id / t->columns) * t->tile_height + wy % t->tile_height;
                tile.width = w; tile.height = h;
                e = blit(d, v.x + xx, v.y + yy, &t->image, &tile, 255, 0, 0);
            }
            if (e) return e;
        }
    }
    return TI_OK;
}

uint16_t ti_gfx_animation_frame(const ti_animation *a, uint32_t elapsed)
{
    if (!a || !ti_near_valid(a, sizeof(*a), 0) || !a->count || !a->ticks_per_frame ||
        a->first > 65535U - a->count) return 0;
    return a->first + (uint16_t)((elapsed / a->ticks_per_frame) % a->count);
}

