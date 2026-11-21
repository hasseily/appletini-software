/* SPDX-License-Identifier: MIT
 * Resident overlay gateway and picture store. The Appletini card decodes
 * and dithers each image; the finished 1-bit rows stay in banked RAM. */
#include "mono_media.h"
#include "mono_net.h"
#include "mono_gfx.h"
#include <string.h>
#include <stdlib.h>
#include <conio.h>

uint8_t mono_overlay_load(const char *name);
extern uint8_t mono_overlay_error, mono_overlay_stage;
extern uint8_t ti_net_poisoned;
extern const uint8_t _BROWSER_SIZE__, _NET_SIZE__;
char mono_media_message[80];
uint8_t mono_memory_ready;
uint16_t mono_overlay_expected;
static uint8_t input[80];

uint8_t mono_overlay(const char *name)
{
    uint8_t n;
    static const char hex[]="0123456789ABCDEF";
    if(ti_net_poisoned) {strcpy(mono_media_message,"HTTP fault: restart browser");return 0;}
    if(name[5]=='W') mono_overlay_expected=(uint16_t)&_BROWSER_SIZE__;
    else mono_overlay_expected=(uint16_t)&_NET_SIZE__;
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

#define PICTURE_BANK_BYTES 40960U
#define PICTURE_TOP 8
#define PICTURE_BOTTOM 352
static struct { uint8_t state, bank; uint16_t at, width, height; } pictures[MONO_PICTURE_MAX];
static uint8_t arena_banks[7], arena_count, arena_bank, head[4], head_used, loading;
static uint8_t picture_box[4];
static uint16_t arena_at, picture_left;

void mono_picture_reset(void)
{
    memset(pictures,0,sizeof(pictures));
    arena_bank=0;arena_at=0;
}
uint8_t mono_picture_rows(uint8_t index, uint8_t enabled)
{
    if(!enabled || index>=MONO_PICTURE_MAX || pictures[index].state!=1) return 1;
    return (uint8_t)((pictures[index].height+7U)>>3);
}
uint8_t mono_picture_cols(uint8_t index, uint8_t enabled)
{
    if(!enabled || index>=MONO_PICTURE_MAX || pictures[index].state!=1) return 7; /* "[Image]" */
    return (uint8_t)((pictures[index].width+6U)/7U);
}
static uint8_t picture_sink(const uint8_t *data,uint16_t length)
{
    uint16_t size;
    while(head_used<4 && length) {
        head[head_used++]=*data++;--length;
        if(head_used!=4) continue;
        pictures[loading].width=head[0]|((uint16_t)head[1]<<8);
        pictures[loading].height=head[2]|((uint16_t)head[3]<<8);
        if(!pictures[loading].width || pictures[loading].width>546U ||
           !pictures[loading].height || pictures[loading].height>240U) return 2;
        size=((pictures[loading].width+6U)/7U)*pictures[loading].height;
        if(size>PICTURE_BANK_BYTES-arena_at) {
            /* Next bank. After the last bank, start again and drop all
             * stored pictures: they load again when they come into view. */
            if(++arena_bank==arena_count) {
                arena_bank=0;
                for(size=0;size<MONO_PICTURE_MAX;++size)
                    if(pictures[size].state==1) pictures[size].state=0;
                size=((pictures[loading].width+6U)/7U)*pictures[loading].height;
            }
            arena_at=0;
        }
        pictures[loading].bank=arena_banks[arena_bank];
        pictures[loading].at=arena_at;
        picture_left=size;
    }
    if(length>picture_left) return 2;
    if(length) {
        mono_bank_write(arena_banks[arena_bank],0x2000U+arena_at,data,length);
        arena_at+=length;picture_left-=length;
    }
    return 0;
}
uint8_t mono_picture_load(uint8_t index,char *url,uint16_t width,uint16_t height)
{
    if(index>=MONO_PICTURE_MAX) return 0;
    pictures[index].state=2;
    mono_media_message[0]=0;
    if(!url) return 0;
    if(!mono_http_images || !arena_count) {
        strcpy(mono_media_message,mono_http_images?"Images need 256 KiB of banked auxiliary memory":
                                                   "Images need newer Appletini firmware");
        return 0;
    }
    if(!width || width>546U) width=546U;
    if(!height || height>240U) height=240U;
    picture_box[0]=(uint8_t)width;picture_box[1]=(uint8_t)(width>>8);
    picture_box[2]=(uint8_t)height;picture_box[3]=0;
    loading=index;head_used=0;picture_left=0;
    if(!mono_net_image(url,picture_box,picture_sink) || head_used!=4 || picture_left) {
        strncpy(mono_media_message,mono_net_error(),79);mono_media_message[79]=0;
        if(!mono_media_message[0]) strcpy(mono_media_message,"Image transfer was incomplete");
        return 0;
    }
    pictures[index].state=1;
    return 1;
}
uint8_t mono_picture_show(uint8_t index,uint8_t column,int16_t y)
{
    uint16_t at,row;
    uint8_t bytes;
    if(index>=MONO_PICTURE_MAX) return 2;
    if(pictures[index].state!=1) return pictures[index].state;
    bytes=(uint8_t)((pictures[index].width+6U)/7U);
    at=pictures[index].at;
    for(row=0;row<pictures[index].height;++row,++y,at+=bytes) {
        if(y<PICTURE_TOP || y>=PICTURE_BOTTOM) continue;
        mono_bank_read(pictures[index].bank,0x2000U+at,input,bytes);
        mono_gfx_row((uint16_t)y,column,input,bytes);
    }
    return 1;
}
/* Banks 1 to 3 always hold pictures. Banks 6 to 9 join when all ten
 * selectors are separate memory. Banks 4 and 5 hold the document. */
static uint8_t distinct(uint8_t count)
{
    uint8_t saved[10],i,ok=1;
    for(i=0;i<count;++i) saved[i]=mono_bank_get(i,0xBFFE);
    for(i=0;i<count;++i) mono_bank_set(i,0xBFFE,(uint8_t)(0xC4+i));
    for(i=0;i<count;++i) if(mono_bank_get(i,0xBFFE)!=(uint8_t)(0xC4+i)) ok=0;
    for(i=0;i<count;++i) mono_bank_set(i,0xBFFE,saved[i]);
    return ok;
}
void mono_media_init(void)
{
    uint8_t i;
    arena_count=0;
    mono_memory_ready=distinct(4);
    if(!mono_memory_ready) return;
    for(i=1;i<4;++i) arena_banks[arena_count++]=i;
    if(distinct(10)) for(i=6;i<10;++i) arena_banks[arena_count++]=i;
}
