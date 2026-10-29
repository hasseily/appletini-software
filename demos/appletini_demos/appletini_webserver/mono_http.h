/* SPDX-License-Identifier: MIT */
#ifndef MONO_HTTP_H
#define MONO_HTTP_H
#include <stdint.h>
typedef uint8_t (*mono_http_sink)(const uint8_t *, uint16_t);
uint8_t mono_http_probe(void);
/* Sink: 0=continue, 1=stop successfully, 2=reject. Never replays a request.
 * The ARM follows redirects; only the final response reaches the sink.
 * URL receives the final URL. limit is a hard encoded-body byte limit. */
uint8_t mono_http_get(char *url, uint16_t url_capacity,
                      mono_http_sink sink, uint16_t limit);
extern char mono_http_type[64];
extern uint16_t mono_http_code, mono_http_length;
extern uint8_t mono_http_cut;
/* API/card diagnostics captured before cleanup reuses the transport globals. */
extern uint8_t mono_http_transport_error, mono_http_card_error;
const char *mono_http_error(void);
#endif
