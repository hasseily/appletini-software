#ifndef TI_INTERNAL_H
#define TI_INTERNAL_H
#include "libtini.h"
extern uint8_t ti_io_bank, ti_io_len;
extern uint16_t ti_io_addr;
extern uint8_t *ti_io_near;
void ti_cpu_read(void);
void ti_cpu_write(void);
/* Rows of a checked bank 0 rectangle in one backend call; target/rows.s. */
extern uint8_t ti_io_width, ti_io_rows;
extern uint16_t ti_io_stride;
extern ti_handle ti_video_backup;
void ti_cpu_write_rows(void);
uint8_t ti_display_level(void);
/* Set by ti_time_note_gap, which memory and audio call without linking the
 * rest of the elapsed-time API. */
extern uint8_t ti_time_flags;
uint8_t ti_key_pending(void);
void ti_key_clear(void);
void ti_video_on(void);
void ti_video_off(void);
uint8_t ti_near_valid(const void *pointer, uint16_t length, uint8_t write);
extern void (*ti_graphics_cleanup_hook)(void);
extern ti_error (*ti_audio_cleanup_hook)(void);
extern void (*ti_storage_pause_hook)(void);
extern void (*ti_storage_resume_hook)(void);
ti_error ti_video_storage_begin(void);
ti_error ti_video_storage_end(void);
typedef ti_error (*ti_accel_rw)(uint8_t bank, uint16_t address, uint8_t *near_buffer,
                               uint16_t length, uint8_t write);
typedef ti_error (*ti_accel_fill)(uint8_t bank, uint16_t address, uint8_t value, uint16_t length);
typedef ti_error (*ti_accel_copy)(uint8_t dst_bank, uint16_t dst_address,
                                 uint8_t src_bank, uint16_t src_address, uint16_t length);
extern ti_accel_rw ti_accel_rw_hook;
extern ti_accel_fill ti_accel_fill_hook;
extern ti_accel_copy ti_accel_copy_hook;
/* Diagnostic-only video lifecycle; raw access stays out of public API. */
ti_error ti_diag_video_begin(void);
ti_error ti_diag_video_end(void);
void ti_diag_video_write(uint16_t address, const uint8_t *src, uint8_t length);
#endif
