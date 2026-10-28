#ifndef LIBTINI_NET_H
#define LIBTINI_NET_H
#include "types.h"
/* Signed ARM result in ti_net_status.result, separate from ti_error.
 * DNS/connect retries exhausted the 30-second request deadline. */
#define TI_NET_RESULT_NETWORK_NOT_READY (-111)
#define TI_NET_IDLE 0
#define TI_NET_QUEUED 1
#define TI_NET_ACTIVE 2
#define TI_NET_DONE 3
#define TI_NET_FAILED 4
#define TI_NET_CANCELLED 5
#define TI_NET_BODY 0x83
#define TI_NET_VALUE 0x84
#define TI_NET_URL 0x85
#define TI_NET_CONTENT_TYPE 0x86
#define TI_NET_MORE 1
#define TI_NET_END 2
#define TI_NET_SOURCE_FAILED 3
#define TI_NET_LOST 4
#define TI_JSON_NONE 0
#define TI_JSON_PENDING 1
#define TI_JSON_FOUND 2
#define TI_JSON_NO_DOCUMENT 3
#define TI_JSON_BAD_DOCUMENT 4
#define TI_JSON_BAD_PATH 5
#define TI_JSON_MISSING 6
typedef struct {
    const char *method, *url, *headers;
    const void *body;
    uint16_t body_length;
    uint8_t retain;
} ti_net_request;
typedef struct {
    uint8_t generation, state, retained, json_state, json_type;
    int16_t result;
    uint16_t http_status, url_length, content_type_length;
    uint32_t body_length, buffered, value_length;
} ti_net_status;
typedef struct { uint8_t state; uint16_t length; const uint8_t *data; } ti_net_chunk;
/* Probe and poll borrow 64 writable MAIN bytes. Read borrows 9..512 bytes.
 * The pointer in chunk refers to reply+8, until the caller reuses reply.
 * Call only from foreground with MAIN RAM and the normal cc65 ZP selected.
 * A timeout poisons this module until the program exits. It never retries a
 * POST, a partial command, or a response with an unknown generation. */
ti_error ti_net_probe(void *reply);
ti_error ti_net_start(const ti_net_request *request);
ti_error ti_net_poll(void *reply, ti_net_status *status);
ti_error ti_net_read(uint8_t source, uint16_t offset, void *reply,
                     uint16_t capacity, ti_net_chunk *chunk);
ti_error ti_net_json(const char *pointer);
ti_error ti_net_cancel(void);
uint8_t ti_net_available(void);
uint8_t ti_net_last_error(void);
/* Profile clock from the ARM, zero if unknown. Pass a nonzero value to
 * ti_audio_config.via_hz before starting audio. */
uint32_t ti_net_via_hz(void);
#endif
