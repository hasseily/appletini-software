/* SPDX-License-Identifier: MIT
 * Resident image coordinator. Encoded bytes stay in expansion RAM while a
 * decoder temporarily replaces the browser's code overlay. */
#include "mono_media.h"
#include "mono_net.h"
#include "mono_gfx.h"
#include "mono_image.h"
#include <string.h>
#include <stdlib.h>
#include <conio.h>

uint8_t mono_png_decode(int16_t, int16_t, uint16_t, uint16_t, uint16_t);
const char *mono_png_error(void);
uint8_t mono_jpeg_decode(int16_t, int16_t, uint16_t, uint16_t, uint16_t);
const char *mono_jpeg_error(void);
uint8_t mono_overlay_load(const char *name);
extern uint8_t mono_overlay_error, mono_overlay_stage;
extern uint8_t ti_net_poisoned;
extern const uint8_t _BROWSER_SIZE__, _GIF_SIZE__, _PNG_SIZE__, _JPEG_SIZE__, _NET_SIZE__;
/* The local demo image lives in MONO.GIF and is read after loading it. */
extern const uint8_t mono_sample[];
extern const uint16_t mono_sample_length;
char mono_media_message[80];
uint8_t mono_memory_ready;
uint16_t mono_overlay_expected;
static uint16_t encoded_length;
static uint8_t input[128];
static uint16_t input_at, input_count;

uint8_t mono_overlay(const char *name)
{
    uint8_t n;
    static const char hex[]="0123456789ABCDEF";
    if(ti_net_poisoned) {strcpy(mono_media_message,"HTTP fault: restart browser");return 0;}
    if(!strcmp(name,"MONO.WEB")) mono_overlay_expected=(uint16_t)&_BROWSER_SIZE__;
    else if(!strcmp(name,"MONO.GIF")) mono_overlay_expected=(uint16_t)&_GIF_SIZE__;
    else if(!strcmp(name,"MONO.PNG")) mono_overlay_expected=(uint16_t)&_PNG_SIZE__;
    else if(!strcmp(name,"MONO.JPG")) mono_overlay_expected=(uint16_t)&_JPEG_SIZE__;
    else if(!strcmp(name,"MONO.NET")) mono_overlay_expected=(uint16_t)&_NET_SIZE__;
    else return 0;
    if(mono_overlay_load(name)) return 1;
    strcpy(mono_media_message,"Cannot load ");strncat(mono_media_message,name,60);
    n=(uint8_t)strlen(mono_media_message);
    mono_media_message[n++]=' ';
    mono_media_message[n++]=mono_overlay_stage;
    mono_media_message[n++]='$';
    mono_media_message[n++]=hex[mono_overlay_error>>4];
    mono_media_message[n++]=hex[mono_overlay_error&15];
    mono_media_message[n]=0;
    return 0;
}
static uint8_t memory_probe(void)
{
    uint8_t saved[4],i,ok=1;
    for(i=0;i<4;++i) saved[i]=mono_bank_get(i,0xBFFE);
    for(i=0;i<4;++i) mono_bank_set(i,0xBFFE,(uint8_t)(0xA4+i));
    for(i=0;i<4;++i) if(mono_bank_get(i,0xBFFE)!=(uint8_t)(0xA4+i)) ok=0;
    for(i=0;i<4;++i) mono_bank_set(i,0xBFFE,saved[i]);
    return ok;
}
void mono_media_init(void) {mono_memory_ready=memory_probe();}
static uint8_t cache_sink(const uint8_t *data,uint16_t length)
{
    uint16_t n,at;
    uint8_t bank;
    while(length) {
        bank=encoded_length<40960U?2:3;
        at=encoded_length<40960U?encoded_length:encoded_length-40960U;
        n=40960U-at; if(n>length) n=length;
        mono_bank_write(bank,0x2000U+at,data,n);
        encoded_length+=n;data+=n;length-=n;
    }
    return 0;
}
uint8_t mono_source_get(uint16_t offset)
{
    uint16_t n,at;
    uint8_t bank;
    if(offset>=encoded_length) return 0;
    if(offset<input_at || offset-input_at>=input_count) {
        bank=offset<40960U?2:3;at=offset<40960U?offset:offset-40960U;
        n=encoded_length-offset;
        if(n>sizeof(input)) n=sizeof(input);
        if(n>40960U-at) n=40960U-at;
        mono_bank_read(bank,0x2000U+at,input,n);
        input_at=offset;input_count=n;
    }
    return input[offset-input_at];
}
static uint8_t gif_decode(int16_t x,int16_t y,uint16_t w,uint16_t h)
{
    uint16_t at=0,n,i;
    uint8_t chunk[64],state=0;
    mono_image_begin(x,y,w,h);
    while(at<encoded_length && !state) {
        n=encoded_length-at;if(n>sizeof(chunk)) n=sizeof(chunk);
        for(i=0;i<n;++i) chunk[i]=mono_source_get(at+i);
        state=mono_image_feed(chunk,n);at+=n;
    }
    state=mono_image_finish();
    if(state!=MONO_IMAGE_DONE) {strncpy(mono_media_message,mono_image_error(),79);return 0;}
    return 1;
}
uint8_t mono_media(char *url,int16_t x,int16_t y,uint16_t w,uint16_t h)
{
    uint8_t format=0,ok=0,local;
    const char *overlay;
    mono_media_message[0]=0;
    if(ti_net_poisoned) {strcpy(mono_media_message,"HTTP fault: restart browser");return 0;}
    if(!mono_memory_ready) {strcpy(mono_media_message,"Images need 256 KiB of banked auxiliary memory");return 0;}
    encoded_length=0;
    local=!strcmp(url,"about:sample");
    if(local) {
        if(!mono_overlay("MONO.GIF")) goto load_failed;
        cache_sink(mono_sample,mono_sample_length);
    }
    else if(!mono_net_get(url,256,cache_sink,65535U)) {
        strncpy(mono_media_message,mono_net_error(),79);return 0;
    } else if(mono_http_cut) {strcpy(mono_media_message,"Encoded image exceeds 65535 bytes");return 0;}
    input_at=0xFFFF;input_count=0;
    if(encoded_length>=6 && mono_source_get(0)=='G' && mono_source_get(1)=='I' && mono_source_get(2)=='F') format=1;
    else if(encoded_length>=8 && mono_source_get(0)==137 && mono_source_get(1)=='P' && mono_source_get(2)=='N' && mono_source_get(3)=='G') format=2;
    else if(encoded_length>=3 && mono_source_get(0)==255 && mono_source_get(1)==216 && mono_source_get(2)==255) format=3;
    if(!format) {
        strcpy(mono_media_message,"Unsupported image; use GIF, PNG or baseline JPEG");
        if(local) goto load_failed;
        return 0;
    }
    overlay=format==1?"MONO.GIF":format==2?"MONO.PNG":"MONO.JPG";
    if(!local && !mono_overlay(overlay)) goto load_failed;
    mono_gfx_begin();
    if(format==1) ok=gif_decode(x,y,w,h);
    else if(format==2) {ok=mono_png_decode(x,y,w,h,encoded_length);if(!ok) strncpy(mono_media_message,mono_png_error(),79);}
    else {ok=mono_jpeg_decode(x,y,w,h,encoded_length);if(!ok) strncpy(mono_media_message,mono_jpeg_error(),79);}
    mono_media_message[79]=0;
    /* Return addresses into BROWSER are valid only after it is restored.
     * A failed restore cannot safely return to the caller. */
    if(!mono_overlay("MONO.WEB")) {
        mono_gfx_end();cputs("A2MONO: cannot restore MONO.WEB\r\n");exit(1);
    }
    mono_gfx_commit();return ok;
load_failed:
    if(!mono_overlay("MONO.WEB")) {mono_gfx_end();exit(1);}
    return 0;
}
