/* SPDX-License-Identifier: MIT */
#include "mono_document.h"
#include <stdint.h>
#include <string.h>
uint8_t mono_document_failed, mono_document_checks;
uint16_t mono_document_observed_capacity;
static uint8_t buffer[300];

static uint8_t pattern(uint16_t offset)
{
    return (uint8_t)(offset ^ (offset >> 8) ^ 0x5AU);
}
static void fill_to(uint16_t end)
{
    uint16_t n,i,at;
    while (mono_document_length < end) {
        at = mono_document_length;
        n = end-at;
        if (n > sizeof(buffer)) n = sizeof(buffer);
        for (i = 0; i < n; ++i) buffer[i] = pattern(at+i);
        if (mono_document_append(buffer,n)) { mono_document_failed=1; return; }
    }
}

int main(void)
{
    uint16_t at,n,i;
    mono_document_init();
    mono_document_observed_capacity = mono_document_capacity;
    if (mono_document_length) mono_document_failed=2;
    ++mono_document_checks;
    fill_to(mono_document_capacity);
    if (mono_document_length != mono_document_capacity) mono_document_failed=3;
    buffer[0]=0x4B;
    if (mono_document_append(buffer,1)!=2 ||
        mono_document_length != mono_document_capacity) mono_document_failed=4;
    ++mono_document_checks;
    at=0;
    while (at < mono_document_length) {
        n=mono_document_length-at;
        if (n>sizeof(buffer)) n=sizeof(buffer);
        mono_document_read(at,buffer,n);
        for(i=0;i<n;++i) if(buffer[i]!=pattern(at+i)) mono_document_failed=5;
        at+=n;
    }
    ++mono_document_checks;
    if(mono_document_capacity==65535U) {
        mono_document_read(40959U,buffer,2);
        if(buffer[0]!=pattern(40959U) || buffer[1]!=pattern(40960U)) mono_document_failed=6;
        memset(buffer,0xCE,sizeof(buffer));
        mono_document_read(65530U,buffer,20);
        for(i=0;i<5;++i) if(buffer[i]!=pattern(65530U+i)) mono_document_failed=7;
        if(buffer[5]!=0xCE) mono_document_failed=8;
    }
    memset(buffer,0xCE,sizeof(buffer));
    mono_document_read(mono_document_capacity,buffer,20);
    if(buffer[0]!=0xCE) mono_document_failed=9;
    ++mono_document_checks;
    mono_document_reset();
    if(mono_document_length || mono_document_append(0,16)!=2 ||
       mono_document_length) mono_document_failed=10;
    fill_to(mono_document_capacity-1U);
    buffer[0]=0x4B;buffer[1]=0xD2;
    if(mono_document_append(buffer,2)!=2 ||
       mono_document_length!=mono_document_capacity) mono_document_failed=11;
    mono_document_read(mono_document_capacity-1U,buffer,1);
    if(buffer[0]!=0x4B) mono_document_failed=12;
    ++mono_document_checks;
    return mono_document_failed;
}
