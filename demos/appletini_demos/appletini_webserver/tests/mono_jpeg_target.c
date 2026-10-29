/* SPDX-License-Identifier: MIT */
#include "mono_gfx.h"
#include "mono_jpeg.h"
#include "jpeg_fixtures.h"
#include <conio.h>
unsigned char mono_jpeg_results[10];
static const unsigned char *jpeg_input;
unsigned char mono_source_get(unsigned int offset) { return jpeg_input[offset]; }
int main(void)
{
    mono_gfx_init();
    mono_gfx_clear(1);
    jpeg_input = jpeg_gray;
    mono_jpeg_results[0] = mono_jpeg_decode(10,10,40,40,sizeof(jpeg_gray));
    jpeg_input = jpeg_rgb;
    mono_jpeg_results[1] = mono_jpeg_decode(60,10,40,40,sizeof(jpeg_rgb));
    jpeg_input = jpeg_subsampled;
    mono_jpeg_results[2] = mono_jpeg_decode(110,10,40,40,sizeof(jpeg_subsampled));
    jpeg_input = jpeg_rgb;
    mono_jpeg_results[3] = mono_jpeg_decode(160,10,9,7,sizeof(jpeg_rgb));
    mono_jpeg_results[4] = mono_jpeg_decode(200,10,40,40,sizeof(jpeg_rgb)-2);
    jpeg_input = jpeg_progressive;
    mono_jpeg_results[5] = mono_jpeg_decode(250,10,40,40,sizeof(jpeg_progressive));
    jpeg_input = jpeg_vertical;
    mono_jpeg_results[6] = mono_jpeg_decode(300,10,40,40,sizeof(jpeg_vertical));
    jpeg_input = jpeg_gray;
    mono_gfx_clip(16,352);
    mono_jpeg_results[7] = mono_jpeg_decode(350,0,40,40,sizeof(jpeg_gray));
    mono_gfx_clip(0,384);
    mono_jpeg_results[8] = mono_jpeg_decode(400,-5,40,40,sizeof(jpeg_gray));
    jpeg_input = jpeg_badtable;
    mono_jpeg_results[9] = mono_jpeg_decode(450,0,40,40,sizeof(jpeg_badtable));
    mono_gfx_text(1,9,"JPEG: native Y, full-size and scaled",0);
    mono_gfx_commit();
    cgetc();
    mono_gfx_end();
    return 0;
}
