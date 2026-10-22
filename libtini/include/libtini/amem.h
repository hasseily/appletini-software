#ifndef LIBTINI_AMEM_H
#define LIBTINI_AMEM_H
#include "types.h"
/* Optional module, absent from the CPU-only binary. Enable probes the exact
 * baseline controller and API before automatic selection for eligible banked
 * transfers. Unsupported/unavailable BEFORE submission uses the CPU path.
 * Execution errors return TI_E_IO, never replay through CPU copies. */
ti_error ti_amem_enable(void);
void ti_amem_disable(void);
uint8_t ti_amem_available(void);
uint8_t ti_amem_last_error(void);
#endif
