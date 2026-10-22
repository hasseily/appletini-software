#include "libtini/audio.h"
/* This object is pulled only by callers using the envelope API. The shared
 * owner supplies its shadows and grouped hardware writer; no second driver. */
extern uint8_t ti_audio_native,ti_audio_speech_enabled,ti_ay_chip,ti_ay_reg,ti_ay_value;
extern uint8_t ti_audio_ay_want[4][14],ti_audio_ay_shadow[4][14];
extern uint16_t ti_audio_envelope_mask;
extern uint16_t ti_audio_music_mask(void);
extern void ti_audio_refresh(void),ti_ay_write(void);

ti_error ti_audio_envelope(uint16_t mask,uint16_t period,uint8_t shape)
{
    uint8_t group,chip,reg,voices=ti_audio_voices();
    uint16_t affected,group_mask;
    if(!voices)return TI_E_STATE;
    if(!mask||mask>=(1U<<voices)||!period||shape>15)return TI_E_RANGE;
    if(ti_audio_native) {if(period>32767)return TI_E_RANGE;period<<=1;}
    if(mask&~ti_audio_music_mask())return TI_E_BUSY;
    /* SSI aliases VIA-A in compatibility mode and may reset the first AY.
     * Its envelope phase cannot survive those writes. Use the second AY. */
    if(!ti_audio_native&&ti_audio_speech_enabled&&(mask&7))return TI_E_BUSY;
    for(group=0;group<voices/3;++group) {
        group_mask=(uint16_t)7<<(group*3);affected=mask&group_mask;
        if(affected&&(ti_audio_envelope_mask&group_mask&~mask))return TI_E_BUSY;
    }
    ti_audio_envelope_mask|=mask;
    for(group=0;group<voices/3;++group) {
        if(!(mask&((uint16_t)7<<(group*3))))continue;
        chip=(!ti_audio_native&&group)?2:group;
        ti_audio_ay_want[chip][11]=(uint8_t)period;
        ti_audio_ay_want[chip][12]=(uint8_t)(period>>8);
        ti_audio_ay_want[chip][13]=shape;
        for(reg=11;reg<14;++reg) {
            ti_ay_chip=chip;ti_ay_reg=reg;ti_ay_value=ti_audio_ay_want[chip][reg];
            ti_ay_write();ti_audio_ay_shadow[chip][reg]=ti_ay_value;
        }
    }
    ti_audio_refresh();return TI_OK;
}
ti_error ti_audio_envelope_stop(uint16_t mask)
{
    uint8_t voices=ti_audio_voices();
    if(!voices)return TI_E_STATE;
    if(mask>=(1U<<voices))return TI_E_RANGE;
    ti_audio_envelope_mask&=~mask;
    ti_audio_refresh();return TI_OK;
}
