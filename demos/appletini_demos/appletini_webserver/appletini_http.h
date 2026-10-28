#ifndef APPLETINI_HTTP_H
#define APPLETINI_HTTP_H
#include <stdint.h>
uint8_t appletini_http_probe(void);
uint8_t appletini_http_fetch(char url[128],char *body,uint16_t capacity,
                            uint16_t *length,uint8_t *cut,uint8_t *plain);
const char *appletini_http_error(void);
#endif
