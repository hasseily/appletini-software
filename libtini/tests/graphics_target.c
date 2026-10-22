#include "libtini.h"
#include "libtini/graphics.h"
#include "internal.h"
#include "font.h"
#include "font_reference.h"

volatile uint16_t gfx_checks, gfx_failed;
static ti_surface d, s, screen;
static ti_handle prefix, bits, cells, font_data;
static uint8_t reference[117], observed[117], source[20];
static uint8_t row_source[326];
static uint8_t mask[5] = {0xAA,0x54,0xAA,0x54,0xAA};
static uint8_t map_ids[4] = {0,1,2,3};
static uint8_t font_bytes[14] = {'T','I','F','1',65,2,3,3,0x40,0xA0,0xE0,0xC0,0xE0,0xC0};
static const uint16_t palette[16] = {0,0xFFF,0xF00,0x0F0,0x00F,0xFF0,0x0FF,0xF0F};
static ti_sprite sprite;
static ti_tileset tiles;
static ti_tilemap map;
static ti_bitmap_font font;
static ti_animation animation = {2,3,5};
static ti_rect r;
static ti_gfx_stats stats;
static uint16_t x,y,i,j;
static uint32_t ticks;

static void check(uint8_t ok, uint16_t id)
{ ++gfx_checks; if (!ok && !gfx_failed) gfx_failed = id; }
static void ref_pixel(int16_t xx, int16_t yy, uint8_t color)
{
    uint16_t p;
    if (xx < 0 || xx >= 17 || yy < 0 || yy >= 13) return;
    p = (uint16_t)yy * 9 + (uint16_t)xx / 2;
    if (xx & 1) reference[p] = (uint8_t)((reference[p] & 0xF0) | color);
    else reference[p] = (uint8_t)((reference[p] & 15) | (color << 4));
}
static uint8_t source_pixel(uint16_t xx, uint16_t yy)
{ uint8_t v = source[yy * 4 + xx / 2]; return xx & 1 ? v & 15 : v >> 4; }
static void compare(uint16_t id)
{
    check(ti_res_read(d.pixels, d.offset, observed, sizeof(observed)) == TI_OK, id);
    for (i = 0; i < sizeof(observed); ++i) check(observed[i] == reference[i], id + 1);
}
static void ref_line(int16_t ax, int16_t ay, int16_t bx, int16_t by, uint8_t c)
{
    int16_t dx = bx > ax ? bx - ax : ax - bx, dy = by > ay ? by - ay : ay - by;
    int16_t sx = ax < bx ? 1 : -1, sy = ay < by ? 1 : -1, error = dx - dy, e;
    while (1) {
        ref_pixel(ax, ay, c);
        if (ax == bx && ay == by) break;
        e = error * 2;
        if (e > -dy) { error -= dy; ax += sx; }
        if (e < dx) { error += dx; ay += sy; }
    }
}
static uint32_t clock_tick(void) { ticks += 10; return ticks; }

static void read_video(uint16_t address, uint8_t length)
{
    ti_io_bank=0; ti_io_addr=address; ti_io_near=observed; ti_io_len=length;
    ti_cpu_read();
}

static void test_near_rows(void)
{
    uint16_t row, piece, k;
    for(i=0;i<sizeof(row_source);++i) row_source[i]=(uint8_t)(i*13+7);
    ti_gfx_budget(320,0,0);
    check(ti_gfx_present_rows(0,10,320,2,row_source,163,&stats)==TI_OK,3000);
    check(stats.bytes==320UL && !stats.elapsed_ticks && stats.flags==TI_GFX_EDGE_GAP,3001);
    /* Full-width rows force two <=128-byte CPU bursts. The 3-byte source
     * padding must not appear at the beginning of the second video row. */
    for(row=0;row<2;++row) for(piece=0;piece<160;piece+=80) {
        read_video((uint16_t)(0x2000+(10+row)*160+piece),80);
        for(k=0;k<80;++k) check(observed[k]==row_source[row*163+piece+k],3002);
    }
    /* 129-byte rows: one full burst and one byte, with neighbours kept. */
    {
        uint8_t before,after;
        read_video(0x2000+20*160+29,1);before=observed[0];
        read_video(0x2000+21*160+159,1);after=observed[0];
        ti_gfx_budget(258,0,0);
        check(ti_gfx_present_rows(60,20,258,2,row_source,129,&stats)==TI_OK,3028);
        check(stats.bytes==258UL,3029);
        for(row=0;row<2;++row) for(piece=0;piece<129;piece+=43) {
            read_video((uint16_t)(0x2000+(20+row)*160+30+piece),43);
            for(k=0;k<43;++k) check(observed[k]==row_source[row*129+piece+k],3030);
        }
        read_video(0x2000+20*160+29,1);check(observed[0]==before,3031);
        read_video(0x2000+21*160+159,1);check(observed[0]==after,3032);
    }
    ti_gfx_budget(6,0,0);
    check(ti_gfx_present_rows(20,12,4,3,row_source,3,&stats)==TI_OK,3003);
    check(stats.bytes==6UL,3004);
    for(row=0;row<3;++row) {
        read_video((uint16_t)(0x2000+(12+row)*160+9),4);
        check(observed[0]==0x44 && observed[1]==row_source[row*3] &&
              observed[2]==row_source[row*3+1] && observed[3]==0x44,3005);
    }
    stats.bytes=0x12345678UL; stats.elapsed_ticks=0x87654321UL; stats.flags=0xA5;
    check(ti_gfx_present_rows(0,10,0,1,row_source,1,&stats)==TI_E_ARGUMENT,3010);
    check(ti_gfx_present_rows(0,10,2,0,row_source,1,&stats)==TI_E_ARGUMENT,3011);
    check(ti_gfx_present_rows(0,10,2,1,0,1,&stats)==TI_E_ARGUMENT,3012);
    check(ti_gfx_present_rows(1,10,2,1,row_source,1,&stats)==TI_E_RANGE,3013);
    check(ti_gfx_present_rows(0,10,3,1,row_source,2,&stats)==TI_E_RANGE,3014);
    check(ti_gfx_present_rows(320,10,2,1,row_source,1,&stats)==TI_E_RANGE,3015);
    check(ti_gfx_present_rows(0,200,2,1,row_source,1,&stats)==TI_E_RANGE,3016);
    check(ti_gfx_present_rows(318,10,4,1,row_source,2,&stats)==TI_E_RANGE,3017);
    check(ti_gfx_present_rows(0,199,2,2,row_source,1,&stats)==TI_E_RANGE,3018);
    check(ti_gfx_present_rows(65534U,10,65534U,1,row_source,32767U,&stats)==TI_E_RANGE,3019);
    check(ti_gfx_present_rows(0,10,2,65535U,row_source,1,&stats)==TI_E_RANGE,3020);
    check(ti_gfx_present_rows(0,10,4,1,row_source,1,&stats)==TI_E_RANGE,3021);
    check(ti_gfx_present_rows(0,10,2,2,row_source,65535U,&stats)==TI_E_RANGE,3022);
    check(ti_gfx_present_rows(0,0,2,200,row_source,65535U,&stats)==TI_E_RANGE,3023);
    check(ti_gfx_present_rows(0,10,2,1,(const uint8_t *)0xA800,1,&stats)==TI_E_RANGE,3024);
    check(ti_gfx_present_rows(0,10,4,1,(const uint8_t *)0xAEFF,2,&stats)==TI_E_RANGE,3025);
    check(ti_gfx_present_rows(0,10,4,1,(const uint8_t *)0xFFFF,2,&stats)==TI_E_RANGE,3026);
    check(ti_gfx_present_rows(0,10,2,1,row_source,1,(ti_gfx_stats *)0x2000)==TI_E_ARGUMENT,3027);
    check(ti_gfx_present_rows(0,10,2,1,row_source,1,(ti_gfx_stats *)0xAEFF)==TI_E_ARGUMENT,3028);
    ticks=0; ti_gfx_budget(5,clock_tick,1);
    check(ti_gfx_present_rows(0,10,4,3,row_source,3,&stats)==TI_E_TIMING,3029);
    check(!ticks && stats.bytes==0x12345678UL && stats.elapsed_ticks==0x87654321UL &&
          stats.flags==0xA5,3030);
    /* The rejected calls left both edges of the target row unchanged. */
    read_video(0x2640,2);
    check(observed[0]==row_source[0] && observed[1]==row_source[1],3031);
    read_video(0x26DE,2);
    check(observed[0]==row_source[158] && observed[1]==row_source[159],3032);
    read_video(0x9D00,1); check(observed[0]==0,3033);
    /* Exact near and screen endpoints, including a final stride never used. */
    *(uint8_t *)0xAEFF=0xBC;
    ti_gfx_budget(1,0,0);
    check(ti_gfx_present_rows(318,199,2,1,(const uint8_t *)0xAEFF,65535U,&stats)==TI_OK,3034);
    read_video(0x9CFE,2); check(observed[0]==0x44 && observed[1]==0xBC,3035);
    *(uint8_t *)0xA900=0xC8;
    ti_gfx_budget(2,0,0);
    check(ti_gfx_present_rows(30,20,2,2,(const uint8_t *)0xA900,0x5FF,&stats)==TI_OK,3036);
    read_video(0x2C8F,1); check(observed[0]==0xC8,3037);
    read_video(0x2D2F,1); check(observed[0]==0xBC,3038);
    check(ti_gfx_present_rows(30,20,2,2,(const uint8_t *)0xA900,0x600,&stats)==TI_E_RANGE,3039);
    ticks=0; ti_gfx_budget(1,clock_tick,5);
    check(ti_gfx_present_rows(0,10,2,1,row_source,1,&stats)==TI_E_TIMING,3040);
    check(stats.bytes==1UL && stats.elapsed_ticks==10 &&
          stats.flags==(TI_GFX_EDGE_GAP|TI_GFX_CLOCK_VALID|TI_GFX_OVERRUN),3041);
    read_video(0x2640,1); check(observed[0]==row_source[0],3042);
    ticks=0xFFFFFFF0UL; ti_gfx_budget(1,clock_tick,10);
    check(ti_gfx_present_rows(0,10,2,1,row_source,1,&stats)==TI_OK,3043);
    check(stats.elapsed_ticks==10 && stats.flags==(TI_GFX_EDGE_GAP|TI_GFX_CLOCK_VALID),3044);
    ti_gfx_budget(0,0,0);
    check(ti_gfx_present_rows(0,10,2,1,row_source,1,0)==TI_OK,3045);
}

int main(void)
{
    /* Compare the compiled lookup against the frozen original renderer. */
    for (x=0;x<256;++x) for (y=0;y<7;++y)
        check(ti_font_row((uint8_t)x,(uint8_t)y) == ti_font_reference_row((uint8_t)x,(uint8_t)y),
              (uint16_t)(700+x*7+y));
    check(ti_init(1,6) == TI_OK, 1);
    check(ti_gfx_present_rows(0,0,2,1,source,1,&stats)==TI_E_STATE,2999);
    check(ti_gfx_surface_create(&d,321,1) == TI_E_RANGE, 2);
    check(ti_res_alloc(TI_BANK_BYTES - 50, &prefix) == TI_OK, 3);
    check(ti_gfx_surface_create(&d,17,13) == TI_OK, 4); /* crosses a bank */
    check(ti_gfx_clear(&d,3) == TI_OK, 5);
    for (i=0;i<sizeof(reference);++i) reference[i]=0x33;
    compare(10);
    check(ti_gfx_rect(&d,-3,2,9,4,5) == TI_OK, 12);
    for (y=2;y<6;++y) for(x=0;x<6;++x) ref_pixel(x,y,5);
    check(ti_gfx_rect(&d,5,2,1,1,9) == TI_OK, 13); ref_pixel(5,2,9);
    check(ti_gfx_rect(&d,16,12,100,100,14) == TI_OK, 14); ref_pixel(16,12,14);
    check(ti_gfx_rect(&d,(-32767-1),0,65535U,1,6) == TI_OK, 15);
    for (x=0;x<17;++x) ref_pixel(x,0,6);
    compare(16);
    check(ti_gfx_line(&d,-10,-10,25,15,8) == TI_OK, 18); ref_line(-10,-10,25,15,8);
    check(ti_gfx_line(&d,8,-10,8,20,2) == TI_OK, 19); ref_line(8,-10,8,20,2);
    check(ti_gfx_line(&d,-2048,0,1,1,1) == TI_E_RANGE, 20);
    compare(21);
    check(ti_gfx_text(&d,-2,8,"A",1) == TI_OK, 23);
    for(y=0;y<7;++y) {
        uint8_t row = y == 0 ? 14 : (y == 3 ? 31 : 17);
        for(x=0;x<5;++x) if(row & (16 >> x)) ref_pixel((int16_t)x-2,y+8,1);
    }
    compare(24);

    check(ti_res_alloc(28,&s.pixels) == TI_OK,26);
    s.offset=8; s.width=7; s.height=5; s.stride=4;
    for (i=0;i<20;++i) source[i]=(uint8_t)(((i*2)%16)<<4 | ((i*2+1)%16));
    check(ti_res_write(s.pixels,8,source,20) == TI_OK,27);
    check(ti_gfx_blit(&d,3,2,&s,0,255) == TI_OK,28);
    for(y=0;y<5;++y) for(x=0;x<7;++x) ref_pixel(x+3,y+2,source_pixel(x,y));
    compare(29);
    check(ti_gfx_blit(&d,-2,-1,&s,0,0) == TI_OK,31);
    for(y=1;y<5;++y) for(x=2;x<7;++x) if(source_pixel(x,y)) ref_pixel(x-2,y-1,source_pixel(x,y));
    compare(32);
    check(ti_res_alloc(5,&bits) == TI_OK,34);
    check(ti_res_write(bits,0,mask,5) == TI_OK,35);
    sprite.image=s; sprite.mask=bits; sprite.mask_offset=0;
    check(ti_gfx_sprite(&d,9,7,&sprite) == TI_OK,36);
    for(y=0;y<5;++y) for(x=0;x<7;++x) if(mask[y] & (128 >> x)) ref_pixel(x+9,y+7,source_pixel(x,y));
    compare(37);
    check(ti_gfx_blit(&d,0,0,&d,0,255) == TI_E_ARGUMENT,39);

    check(ti_res_alloc(4,&cells) == TI_OK,40);
    check(ti_res_write(cells,0,map_ids,4) == TI_OK,41);
    tiles.image=s; tiles.tile_width=3; tiles.tile_height=2; tiles.columns=2; tiles.count=4;
    map.cells=cells; map.offset=0; map.columns=map.rows=2;
    r.x=r.y=1; r.width=10; r.height=7;
    check(ti_gfx_map(&d,&r,&tiles,&map,1,1) == TI_OK,42);
    for(y=0;y<7;++y) for(x=0;x<10;++x) {
        uint16_t wx=x+1, wy=y+1;
        uint8_t color=0;
        if(wx<6 && wy<4) {
            j=map_ids[(wy/2)*2+wx/3];
            color=source_pixel((j%2)*3+wx%3,(j/2)*2+wy%2);
        }
        ref_pixel(x+1,y+1,color);
    }
    compare(43);
    check(ti_gfx_map(&d,&r,&tiles,&map,65535U,0) == TI_E_RANGE,45);
    check(ti_gfx_animation_frame(&animation,0) == 2,46);
    check(ti_gfx_animation_frame(&animation,5) == 3,47);
    check(ti_gfx_animation_frame(&animation,15) == 2,48);
    check(ti_res_alloc(14,&font_data) == TI_OK,49);
    check(ti_res_write(font_data,0,font_bytes,14) == TI_OK,50);
    font.glyphs=font_data; font.offset=8; font.width=3; font.height=3; font.first=65; font.count=2;
    check(ti_gfx_text_font(&d,14,0,"AB",7,&font) == TI_OK,51);
    for(y=0;y<3;++y) for(x=0;x<3;++x) if(font_bytes[8+y] & (128>>x)) ref_pixel(x+14,y,7);
    compare(52);
    check(ti_gfx_surface_free(&d) == TI_OK,54);
    check(ti_gfx_surface_free(&d) == TI_E_HANDLE,55);
    check(ti_res_free(s.pixels) == TI_OK,56);
    check(ti_res_free(prefix) == TI_OK,57);
    check(ti_res_free(bits) == TI_OK,58);
    check(ti_res_free(cells) == TI_OK,59);
    check(ti_res_free(font_data) == TI_OK,60);

    check(ti_gfx_surface_create(&screen,320,200) == TI_OK,61);
    check(ti_gfx_clear(&screen,4) == TI_OK,62);
    s.pixels=0;
    check(ti_gfx_surface_create(&s,320,3) == TI_OK,75);
    for (y=0;y<3;++y) for (j=0;j<160;j+=20) {
        for(i=0;i<20;++i) source[i]=(uint8_t)((((j+i)*2)%16)<<4 | (((j+i)*2+1)%16));
        check(ti_res_write(s.pixels,(uint32_t)y*160+j,source,20) == TI_OK,76);
    }
    check(ti_gfx_blit(&screen,1,4,&s,0,0) == TI_OK,77); /* both 240-pixel chunks */
    for(y=4;y<7;++y) for(j=0;j<160;j+=100) {
        uint8_t n=j?60:100;
        check(ti_res_read(screen.pixels,(uint32_t)y*160+j,observed,n) == TI_OK,78);
        for(i=0;i<n;++i) {
            uint8_t hi=(uint8_t)(((j+i)*2-1)&15),lo=(uint8_t)(((j+i)*2)&15);
            if(!j&&!i)hi=4;
            if(!hi)hi=4;
            if(!lo)lo=4;
            check(observed[i]==(uint8_t)((hi<<4)|lo),79);
        }
    }
    check(ti_gfx_surface_free(&s) == TI_OK,80);
    check(ti_gfx_begin(palette) == TI_OK,63);
    ti_gfx_budget(0,0,0);
    check(ti_gfx_present(&screen,0,&stats) == TI_OK,81);
    check(stats.bytes == 32000UL,82);
    r.x=1;r.y=1;r.width=3;r.height=2;
    ti_gfx_budget(3,0,0);
    check(ti_gfx_present(&screen,&r,&stats) == TI_E_TIMING,64);
    ti_gfx_budget(4,0,0);
    check(ti_gfx_present(&screen,&r,&stats) == TI_OK,65);
    check(stats.bytes == 4 && stats.flags == TI_GFX_EDGE_GAP,66);
    ti_gfx_budget(4,clock_tick,5);
    check(ti_gfx_present(&screen,&r,&stats) == TI_E_TIMING,67);
    check(stats.elapsed_ticks==10 && (stats.flags & TI_GFX_OVERRUN),68);
    test_near_rows();
    check(ti_shutdown() == TI_OK,69); /* active graphics cleanup hook */
    check(ti_init(1,6) == TI_OK,70);
    check(ti_gfx_begin(palette) == TI_OK,71);
    check(ti_gfx_end() == TI_OK,72);
    check(ti_gfx_end() == TI_OK,73);
    check(ti_shutdown() == TI_OK,74);
    return 0;
}
