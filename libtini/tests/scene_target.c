/* Drives the band renderer for tests/scene_validate.py, which compares the
 * screen with a reference rendering of the sprite list after every draw. */
#include "libtini.h"
volatile uint16_t test_checks, test_failed;
volatile uint8_t test_expect_quiet;
volatile uint16_t test_services;
TI_SCENE_STORAGE(24, 160);
/* A sheet 12 bytes wide; images inside it use stride 12. */
uint8_t test_sheet[12 * 40];
ti_image test_images[] = {
    {test_sheet, 8, 16, 12},           /* 16x16 */
    {test_sheet + 9, 3, 40, 12},       /* tall: 6x40 */
    {test_sheet + 12 * 20, 12, 5, 12}, /* wide: 24x5 */
    {test_sheet + 1, 1, 1, 12},        /* one byte */
    {0, 1, 1, 0}, {0, 6, 1, 0}, {0, 1, 12, 0}, {0, 20, 9, 0}
};
#define IMAGES (sizeof(test_images) / sizeof(test_images[0]))
static const uint16_t palette[16] = {0x000,0x111,0x222,0x333,0x444,0x555,0x666,0x777,
    0x888,0x999,0xAAA,0xBBB,0xCCC,0xDDD,0xEEE,0xFFF};
static ti_scene_config config;
static uint8_t garbage[160];
static uint16_t seed = 0x1234;
static int16_t px[24], py[24];
static uint8_t image[24], color[24], live, i, n;
static void check(uint8_t yes, uint16_t id) { ++test_checks; if (!yes && !test_failed) test_failed = id; }
static uint8_t rnd(void) { seed = seed * 25173U + 13849U; return (uint8_t)(seed >> 8); }
static void service(void) { ++test_services; }
/* Python fills the SHR pixels with a pattern here, then checks them. */
void test_ready(void) {}
void test_shown(void) {}
static void place(uint8_t k)
{
    /* Positions from 48 pixels before to 48 past the area, either axis. */
    px[k] = (int16_t)config.x - 48 + (int16_t)(((uint16_t)rnd() << 8 | rnd()) % (config.width + 96));
    py[k] = (int16_t)config.y - 48 + (int16_t)(((uint16_t)rnd() << 8 | rnd()) % (config.height + 96));
    image[k] = rnd() % IMAGES;
    color[k] = rnd() & 15;
}
static void show(void)
{
    ti_scene_frame();
    for (i = 0; i < live; ++i) check(ti_scene_add(px[i], py[i], image[i], color[i]) == TI_OK, 10);
    check(ti_scene_draw() == TI_OK, 11);
    test_shown();
}
static void frames(uint8_t count)
{
    while (count--) {
        /* Move a few sprites, keep the rest, and now and then add or drop one. */
        n = rnd() & 3;
        while (n--) place(rnd() % live);
        if ((rnd() & 7) == 0 && live < 24) place(live++);
        if ((rnd() & 7) == 1 && live > 1) --live;
        show();
    }
}
/* Overwrite the whole area with one byte, as another drawer would. */
static void paint(uint8_t value)
{
    uint8_t line;
    for (i = 0; i < 160; ++i) garbage[i] = value;
    for (line = 0; line < config.height; ++line)
        check(ti_gfx_present_rows(config.x, config.y + line, config.width, 1, garbage, config.width / 2, 0) == TI_OK, 12);
}
static void area(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint8_t background, uint8_t count)
{
    config.x = x; config.y = y; config.width = width; config.height = height;
    config.background = background;
    check(ti_scene_begin(&config) == TI_OK, 20);
    ti_scene_invalidate();
    for (live = 0; live < 6; ++live) place(live);
    show();
    frames(count);
}
int main(void)
{
    uint16_t before;
    for (before = 0; before < sizeof(test_sheet); ++before) {
        n = rnd();
        test_sheet[before] = (n & 3) == 0 ? 0 : (n & 3) == 1 ? (n & 0x0F) : (n & 3) == 2 ? (n & 0xF0) : n;
    }
    if (ti_init(1, 1) != TI_OK || ti_gfx_begin(palette) != TI_OK) return 1;
    test_ready();
    check(ti_scene_add(0, 0, 0, 0) == TI_E_STATE, 1);
    check(ti_scene_draw() == TI_E_STATE, 2);
    config.images = test_images; config.image_count = IMAGES; config.service = service;
    config.x = 40; config.y = 24; config.width = 160; config.height = 64;
    config.x = 41; check(ti_scene_begin(&config) == TI_E_RANGE, 3); config.x = 40;
    config.height = 12; check(ti_scene_begin(&config) == TI_E_RANGE, 4); config.height = 64;
    config.width = 290; check(ti_scene_begin(&config) == TI_E_RANGE, 5); config.width = 160;
    config.y = 150; check(ti_scene_begin(&config) == TI_E_RANGE, 6); config.y = 24;
    config.background = 16; check(ti_scene_begin(&config) == TI_E_RANGE, 7); config.background = 0;
    config.image_count = 0; check(ti_scene_begin(&config) == TI_E_ARGUMENT, 8); config.image_count = IMAGES;
    test_images[2].stride = 11; check(ti_scene_begin(&config) == TI_E_RANGE, 9); test_images[2].stride = 12;
    check(ti_scene_add(0, 0, 0, 0) == TI_E_STATE, 13);
    check(ti_scene_begin(0) == TI_E_ARGUMENT, 14);
    test_images[3].rows = 0; check(ti_scene_begin(&config) == TI_E_RANGE, 15); test_images[3].rows = 1;
    test_images[0].pixels = (const uint8_t *)0xC000;
    check(ti_scene_begin(&config) == TI_E_RANGE, 16); test_images[0].pixels = test_sheet;

    area(40, 24, 160, 64, 3, 30);
    /* An unchanged list publishes nothing. */
    test_expect_quiet = 1; show(); test_expect_quiet = 0;
    /* Eight bands: the service runs after the fourth and the eighth. */
    before = test_services; place(0); show();
    check(test_services - before == 2, 30);
    /* A full list and an unknown image. */
    ti_scene_frame();
    for (i = 0; i < 24; ++i) check(ti_scene_add(60, 40, 4, 1) == TI_OK, 31);
    check(ti_scene_add(60, 40, 4, 1) == TI_E_FULL, 32);
    check(ti_scene_draw() == TI_OK, 33);
    test_shown();
    ti_scene_frame();
    check(ti_scene_add(0, 0, IMAGES, 0) == TI_E_RANGE, 34);
    show();
    /* Another drawer leaves the background: forget the last list. */
    paint(0x33); ti_scene_forget(); place(1); show();
    /* Another drawer leaves anything: redraw the whole area. */
    paint(0x5A); ti_scene_invalidate(); show();
    frames(8);

    /* A last block cut by the area's edge, and the full screen width. */
    area(0, 16, 236, 184, 0, 6);
    area(0, 192, 320, 8, 9, 6);
    return 0;
}
