#ifndef LIBTINI_TYPES_H
#define LIBTINI_TYPES_H
#include <stdint.h>

/* cc65 C99 subset; default cc65 ABI (__fastcall__ for nonvariadic calls).
 * No public enum has an ABI-sized type. */
typedef uint8_t ti_error;
typedef uint16_t ti_handle;
#define TI_OK             ((ti_error)0)
#define TI_E_ARGUMENT     ((ti_error)1)
#define TI_E_STATE        ((ti_error)2)
#define TI_E_RANGE        ((ti_error)3)
#define TI_E_NOMEM        ((ti_error)4)
#define TI_E_HANDLE       ((ti_error)5)
#define TI_E_UNAVAILABLE  ((ti_error)6)
#define TI_E_TIMING       ((ti_error)7)
#define TI_E_BUSY         ((ti_error)8)
#define TI_E_IO           ((ti_error)9)
#define TI_E_FORMAT       ((ti_error)10)
#define TI_E_FULL         ((ti_error)11)
#define TI_INVALID_HANDLE ((ti_handle)0)

/* ti_error_first is the first nonzero error passed to ti_error_keep since
 * start or ti_error_clear. keep returns e, so it can wrap any call whose
 * failure the program handles later, such as once a frame. */
ti_error ti_error_keep(ti_error e);
ti_error ti_error_first(void);
void ti_error_clear(void);
#endif
