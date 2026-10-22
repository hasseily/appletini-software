/* Separate benchmark application; never linked into a game. */
#include "libtini.h"
#include "libtini/graphics.h"
#include "libtini/amem.h"
#ifndef TI_PRIVATE_TRANSPORT
#define TI_PRIVATE_TRANSPORT 0
#endif

volatile uint8_t bench_phase,bench_last_error,bench_accel_status,bench_accel_active;
volatile uint16_t bench_marker_count;
ti_gfx_stats bench_stats;
uint8_t bench_source[512],bench_result[512];
static ti_handle a,b;
static ti_surface screen;
static uint16_t i;
static const uint16_t palette[16]={0,0xFFF,0xF00,0x0F0,0x00F,0xFF0};
static ti_rect dirty={11,9,65,17};

/* Exported breakpoints bracket calls; the runner records emulated counters. */
void bench_mark(void){++bench_marker_count;}
static uint8_t failed(ti_error e)
{
    if(!e)return 0;
    bench_last_error=e;bench_phase=255;bench_mark();return 1;
}

int main(void)
{
    if(failed(ti_init(1,8)))return 1;
    if(failed(ti_res_alloc(TI_BANK_BYTES+4096,&a)))return 1;
    if(failed(ti_res_alloc(TI_BANK_BYTES+4096,&b)))return 1;
    if(failed(ti_res_fill(a,0,0x11,TI_BANK_BYTES+4096)))return 1;
    if(failed(ti_res_fill(b,0,0x22,TI_BANK_BYTES+4096)))return 1;
    for(i=0;i<512;++i)bench_source[i]=(uint8_t)(i*5+17);
    if(failed(ti_gfx_surface_create(&screen,320,200)))return 1;
    if(failed(ti_gfx_clear(&screen,4)))return 1;
    if(failed(ti_gfx_begin(palette)))return 1;
    ti_gfx_budget(0,0,0);
#if TI_PRIVATE_TRANSPORT
    bench_accel_status=ti_amem_enable();bench_accel_active=ti_amem_available();
#else
    bench_accel_status=TI_E_UNAVAILABLE;bench_accel_active=0;
#endif
    bench_phase=0;bench_mark();bench_last_error=TI_OK;
    bench_phase=1;bench_mark();bench_last_error=ti_res_write(a,TI_BANK_BYTES-256,bench_source,512);
    bench_phase=2;bench_mark();bench_last_error=ti_res_read(a,TI_BANK_BYTES-256,bench_result,512);
    bench_phase=3;bench_mark();bench_last_error=ti_res_fill(a,TI_BANK_BYTES-256,0xA6,1024);
    bench_phase=4;bench_mark();bench_last_error=ti_res_copy(b,TI_BANK_BYTES-4096-256,a,TI_BANK_BYTES-256,1024);
    bench_phase=5;bench_mark();bench_last_error=ti_gfx_present(&screen,0,&bench_stats);
    bench_phase=6;bench_mark();bench_last_error=ti_gfx_rect(&screen,11,9,65,17,5);
    bench_phase=7;bench_mark();bench_last_error=ti_gfx_present(&screen,&dirty,&bench_stats);
    bench_phase=8;bench_mark();
#if TI_PRIVATE_TRANSPORT
    ti_amem_disable();
#endif
    ti_gfx_end();ti_shutdown();
    return 0;
}
