#include "internal.h"
#include "libtini/input.h"
#define IO(a) (*(volatile uint8_t *)(a))
static uint8_t keys[8], head, used;
static volatile uint8_t io_sink;
void ti_input_reset(void) { head = used = 0; }
static ti_error queue(uint8_t key)
{
    if (used == sizeof(keys)) return TI_E_NOMEM;
    keys[(head + used) & 7] = key & 127;
    ++used;
    return TI_OK;
}
ti_error ti_input_poll(void)
{
    uint8_t key = IO(0xC000);
    if (!(key & 128)) return TI_OK;
    io_sink = IO(0xC010);
    return queue(key);
}
/* Reading $C010 clears the keyboard strobe, so only read it without a
 * pending key. A key that arrives between the two reads loses its strobe;
 * its new code in the latch queues it here. */
uint8_t ti_input_held(void)
{
    uint8_t before = IO(0xC000), status;
    if (before & 128) return before & 127;
    status = IO(0xC010);
    if ((status ^ before) & 127) (void)queue(status);
    return status & 128 ? status & 127 : 0;
}
ti_error ti_input_key(uint8_t *out)
{
    if (!out || !ti_near_valid(out, 1, 1)) return TI_E_ARGUMENT;
    if (!used) return TI_E_UNAVAILABLE;
    *out = keys[head]; head = (head + 1) & 7; --used;
    return TI_OK;
}
uint8_t ti_input_buttons(void)
{
    return (uint8_t)((IO(0xC061) >> 7) | ((IO(0xC062) >> 6) & 2) |
                     ((IO(0xC063) >> 5) & 4));
}
ti_error ti_mouse_read(void *state) { (void)state; return TI_E_UNAVAILABLE; }
