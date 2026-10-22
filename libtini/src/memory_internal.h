#ifndef TI_MEMORY_INTERNAL_H
#define TI_MEMORY_INTERNAL_H
#include "internal.h"

/* Archive-module interface, not a public banked pointer API. These records
 * remain owned by memory.c; callers must not retain them across free/shutdown.
 * Transfers keep the existing shared staging area and logical-window cache. */
typedef struct ti_memory_resource {
    uint32_t base, size;
    uint16_t generation;
    uint8_t used, retired;
} ti_memory_resource;

ti_memory_resource *ti_memory_lookup(ti_handle handle);
uint8_t ti_memory_in_range(ti_memory_resource *r, uint32_t offset, uint32_t length);
void ti_memory_transfer(ti_memory_resource *r, uint32_t offset,
                        uint8_t *near_buffer, uint16_t length, uint8_t write);
/* The CPU bank and $0200-$BFFF address of a checked resource byte, for a
 * caller that walks banked rows itself, as graphics_video.c does. */
uint16_t ti_memory_address(ti_memory_resource *r, uint32_t offset, uint8_t *bank);
#if TI_PRIVATE_TRANSPORT
uint16_t ti_memory_locate(uint32_t position, uint8_t *bank, uint16_t *address);
#endif
extern uint8_t ti_transfer_start;

#endif
