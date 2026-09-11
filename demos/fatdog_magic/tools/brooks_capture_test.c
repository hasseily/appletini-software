/* Host-only regression test: execute the unchanged Appletini renderer after
 * applying the PL capture mask. This is never assembled into MAGIC.SYSTEM.
 * The sibling firmware harness supplies its existing hardware stubs.
 */
#define main upstream_harness_main
#include "harness.c"
#undef main

static uint8_t capture_mask[0x20000];

static void captured_write(uint32_t address, uint8_t value)
{
    if (address < sizeof capture_mask && capture_mask[address])
        feed(rec_write(address, value));
}

static void field_write(unsigned field, const uint8_t *data)
{
    uint32_t base = field == 0 ? 0x12000u : 0x2000u;
    for (unsigned i = 0; i < 0x8000; ++i)
        captured_write(base + i, (i >= 0x7DFC && i < 0x7E00) ? 0 : data[i]);
}

static void palette_write(const uint8_t *field, const uint8_t *palette)
{
    uint32_t address = field[0x7DFA] | ((uint32_t)field[0x7DFB] << 8);
    if (field[0x7DF9] == 1) address += 0x10000u;
    for (unsigned i = 0; i < 6400; ++i)
        captured_write(address + i, palette[i]);
}

int main(int argc, char **argv)
{
    if (argc != 5) return 2;
    snprintf(s_repo, sizeof s_repo, "%s", argv[1]);
    snprintf(s_out, sizeof s_out, "%s", argv[4]);
    s_settings = apple_video_settings_pack_border_full(
        0u, 0u, APPLE_VIDEO_COLOR_COMPOSITE_MONITOR, 1u, 1u, 0u, 0u, 0, 0, 0u);
    if (apple_cycle_renderer_init() != 0) return 2;
    /* BANKS consumes the capture shadow produced by executing MAGIC.SYSTEM
     * in the CPU test. The renderer sees only bytes that survived capture. */
    if (strcmp(argv[3], "BANKS") == 0) {
        uint8_t *main = load_file_exact(argv[2], 65536);
        uint8_t *aux = load_file_exact("aux.bin", 65536);
        for (unsigned i = 0; i < 65536; ++i) {
            feed(rec_write(i, main[i]));
            feed(rec_write(0x10000u + i, aux[i]));
        }
        free(main);
        free(aux);
        goto publish;
    }
    size_t size;
    uint8_t *file = load_file(argv[2], &size);
    uint8_t *mask = load_file_exact(argv[3], sizeof capture_mask);
    memcpy(capture_mask, mask, sizeof capture_mask);
    free(mask);
    if (size != 39168 && size != 71936 && size != 78336) return 2;
    field_write(0, file);
    palette_write(file, file + 32768);
    if (size > 39168) {
        field_write(1, file + 39168);
        if (size == 78336) palette_write(file + 39168, file + 71936);
        for (unsigned i = 0; i < 4; ++i)
            captured_write(0x9DFCu + i, file[39168 + 0x7DFC + i]);
    }
    for (unsigned i = 0; i < 4; ++i)
        captured_write(0x19DFCu + i, file[0x7DFC + i]);
    free(file);
publish:
    feed(rec_io(0xC029u, 0xC1u));
    for (unsigned i = 0; i < 6; ++i) shr_marker();
    if (s_pub_slot == 0xFF) return 3;
    dump_published_shr("frame.bgra");
    dump_banks("main.bin", "aux.bin");
    const uint32_t *pixels = (const uint32_t *)s_slot_mem[s_pub_slot];
    unsigned nonblack = 0;
    for (unsigned i = 0; i < 640u * 400u; ++i)
        nonblack += (pixels[i] & 0xFFFFFFu) != 0;
    printf("detail=%u nonblack=%u\n", (unsigned)s_pub_detail, nonblack);
    return 0;
}
