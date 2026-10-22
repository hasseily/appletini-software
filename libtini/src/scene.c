#include "internal.h"
#include "libtini/scene.h"
/* Scene state. Setup, marking, composition and publication are in
 * target/scene.s, which reads this state at absolute addresses. The sprite
 * arrays and strip come from the game's TI_SCENE_STORAGE. */
const ti_image *ti_scene_images;
uint8_t ti_scene_image_count, ti_scene_x0, ti_scene_y0, ti_scene_row_bytes, ti_scene_lines;
uint8_t ti_scene_bands, ti_scene_blocks, ti_scene_fill, ti_scene_count, ti_scene_end;
uint16_t ti_scene_screen;
/* Strip row addresses, and one changed-block bit mask a band in three
 * bytes: bands 0..24 of byte 0, then of byte 1, then of byte 2. */
uint8_t ti_scene_row_lo[8], ti_scene_row_hi[8];
uint8_t ti_scene_mask[75];
void (*ti_scene_service)(void);
void ti_scene_frame(void) { ti_scene_count = 0; }
void ti_scene_forget(void) { ti_scene_end = 0; }
