/* SPDX-License-Identifier: MIT */
#include "mono_gfx.h"
#include <conio.h>
unsigned char mono_fixture_checks;
unsigned char mono_fixture_failed;
static const unsigned char stripe[4] = {0x55,0x2A,0x33,0x4C};
static unsigned char transfer[300];
int main(void)
{
    mono_gfx_init();
    mono_gfx_clear(1);
    mono_aux_set(0x6000,0x5A);
    mono_aux_set(0xBFFF,0xC3);
    mono_bank_set(2,0x2000,0x39);
    mono_bank_set(3,0xBFFF,0xE7);
    if (mono_aux_get(0x6000)!=0x5A || mono_aux_get(0xBFFF)!=0xC3 ||
        mono_bank_get(2,0x2000)!=0x39 || mono_bank_get(3,0xBFFF)!=0xE7)
        mono_fixture_failed=1;
    ++mono_fixture_checks;
    {
        unsigned int i;
        unsigned char bank;
        for(i=0;i<300;++i) transfer[i]=(unsigned char)(i*13U+7U);
        for(bank=1;bank!=4;++bank) {
            mono_bank_write(bank,0x60F0,transfer,300);
            for(i=0;i<300;++i) transfer[i]=0;
            mono_bank_read(bank,0x60F0,transfer,300);
            for(i=0;i<300;++i)
                if(transfer[i]!=(unsigned char)(i*13U+7U)) mono_fixture_failed=2;
        }
    }
    ++mono_fixture_checks;
    mono_gfx_text(1,1,"A2MONO 560x384 - both fields",0);
    mono_gfx_text(1,3,"ABCDEFGHIJKLMNOPQRSTUVWXYZ",0);
    mono_gfx_text(1,4,"abcdefghijklmnopqrstuvwxyz",0);
    mono_gfx_invert(1,1,6);
    mono_gfx_invert(1,1,6);
    mono_gfx_row(45,1,stripe,4);
    mono_gfx_pixel(0,0,1);
    mono_gfx_pixel(559,0,1);
    mono_gfx_pixel(0,383,1);
    mono_gfx_pixel(559,383,1);
    mono_gfx_pixel(560,384,1); /* clipped */
    mono_gfx_commit();
    ++mono_fixture_checks;
    cgetc();
    mono_gfx_end();
    return mono_fixture_failed;
}
