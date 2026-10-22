#ifndef TI_AUDIO_INTERNAL_H
#define TI_AUDIO_INTERNAL_H
#include "libtini/audio.h"
typedef struct speech_job { uint8_t ids[8], count, word, phone, priority; } speech_job;
extern const ti_speech_bank *ti_audio_speech_bank;
ti_error ti_speech_submit(speech_job *job,uint8_t priority);
/* The event and song players are separate archive modules, linked only when
 * a program starts that kind of score. ti_audio_update calls the active one;
 * nonzero means more than 32 steps were due, which ends the score with
 * TI_E_TIMING. A player sets the music volume of its voices and the voices
 * it uses, which reservation changes keep, and the next deadline, which
 * resuming the clock rebases. Tones and the dirty flag ask the next update
 * to write the AYs. */
extern uint8_t (*ti_audio_player)(uint32_t now);
extern uint8_t ti_audio_music_volume[12], ti_audio_dirty;
extern uint16_t ti_audio_music_voices;
extern uint32_t ti_audio_music_end;
uint8_t ti_audio_due(uint32_t now,uint32_t deadline);
void ti_audio_tone(uint8_t voice,uint16_t period,uint8_t volume);
uint16_t ti_audio_music_mask(void);
#endif
