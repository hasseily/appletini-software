#include "internal.h"

/* Exported for tests, which read it from the label file. */
ti_error ti_error_kept;

ti_error ti_error_keep(ti_error e)
{
    if (!ti_error_kept) ti_error_kept = e;
    return e;
}

ti_error ti_error_first(void) { return ti_error_kept; }

void ti_error_clear(void) { ti_error_kept = TI_OK; }
