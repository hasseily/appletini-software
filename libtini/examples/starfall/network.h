#ifndef SF_NETWORK_H
#define SF_NETWORK_H
#include <stdint.h>
uint32_t sf_online_clock(void);
void sf_online_begin(void);
void sf_online_poll(void);
/* Nonzero closes the panel; the caller then restores its game-over overlay. */
uint8_t sf_online_key(uint8_t key);
uint8_t sf_online_panel(void);
#endif
