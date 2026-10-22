#include "internal.h"
/* Separate archive member: memory and audio note gaps without linking the
 * elapsed-time API. */
uint8_t ti_time_flags;
void ti_time_note_gap(void) { ti_time_flags |= TI_TIME_GAP; }
