/* SPDX-License-Identifier: MIT */
#ifndef MONO_NET_H
#define MONO_NET_H
#include "mono_http.h"
#define MONO_HTTP_BODY 1U
#define MONO_HTTP_SAVED 2U
#define MONO_HTTP_FILE_FAILED 3U
#define MONO_HTTP_FILE_CANCELLED 4U
uint8_t mono_net_probe(void);
uint8_t mono_net_get(char *, uint16_t, mono_http_sink, uint16_t);
uint8_t mono_net_page(char *, uint16_t, mono_http_sink, uint16_t);
uint8_t mono_net_download(char *, const char *);
const char *mono_net_error(void);
extern uint8_t mono_http_policy;
extern const char *mono_http_download_name;
extern char mono_http_message[192];
#endif
