/* SPDX-License-Identifier: MIT
 * Resident NET gateway. No network code or error pointer survives in WEB. */
#include "mono_net.h"
#include "mono_gfx.h"
#include "mono_media.h"
#include <string.h>

extern uint8_t ti_net_poisoned, ti_net_rc;
uint8_t mono_overlay(const char *name);

static uint8_t enter(void)
{
    if(ti_net_poisoned) {
        mono_http_transport_error=9;mono_http_card_error=ti_net_rc;
        strcpy(mono_http_message,"HTTP fault: restart browser");return 0;
    }
    /* This AUX workspace belongs to GIF only while a decoder is running.
     * HTTP completes before a codec starts, so no active dictionary is lost.
     * Save the complete window, including its two unused padding bytes. */
    mono_aux_write(0x6000U,(const void*)0x8B00U,0x2C00U);
    if(mono_overlay("MONO.NET")) return 1;
    strncpy(mono_http_message,mono_media_message,191);mono_http_message[191]=0;
    mono_aux_read(0x6000U,(void*)0x8B00U,0x2C00U);return 0;
}
static void leave(void)
{
    const char *message=mono_http_error();
    if(message!=mono_http_message) {
        strncpy(mono_http_message,message,191);mono_http_message[191]=0;
    }
    /* A timeout leaves FIFO ownership uncertain. Restoring from AUX uses
     * no ProDOS/SmartPort traffic, even for the failed-request path. */
    mono_aux_read(0x6000U,(void*)0x8B00U,0x2C00U);
}
const char *mono_net_error(void) {return mono_http_message;}
uint8_t mono_net_probe(void)
{
    uint8_t ok;
    if(!enter()) return 0;
    ok=mono_http_probe();leave();return ok;
}
static uint8_t get(char *url,uint16_t cap,mono_http_sink sink,uint16_t limit)
{
    uint8_t result;
    if(!enter()) return mono_http_policy==4?MONO_HTTP_FILE_FAILED:0;
    result=mono_http_get(url,cap,sink,limit);leave();return result;
}
uint8_t mono_net_get(char *url,uint16_t cap,mono_http_sink sink,uint16_t limit)
{
    mono_http_policy=0;mono_http_download_name=0;
    return get(url,cap,sink,limit);
}
uint8_t mono_net_page(char *url,uint16_t cap,mono_http_sink sink,uint16_t limit)
{
    mono_http_policy=2;mono_http_download_name=0;
    return get(url,cap,sink,limit);
}
uint8_t mono_net_download(char *url,const char *name)
{
    mono_http_policy=4;mono_http_download_name=name;
    return get(url,256,0,0);
}
