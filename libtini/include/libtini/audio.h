#ifndef LIBTINI_AUDIO_H
#define LIBTINI_AUDIO_H
#include "types.h"
#define TI_AUDIO_MOCKINGBOARD 1
#define TI_AUDIO_PHASOR 2
#define TI_AUDIO_TICKS_PER_SECOND 100
#define TI_SPEECH_QUEUE 4
#define TI_SPEECH_INTERRUPT 128
typedef struct ti_audio_config {
    uint8_t personality, speech, ducking;
    uint32_t via_hz; /* 0 assumes nominal 1 MHz; calibrate on the board. */
    /* 0 uses every voice: 6 on Mockingboard, 12 on Phasor. A smaller count,
     * rounded up to whole AY chips of three voices, limits every update to
     * those chips; ti_audio_voices reports the result. */
    uint8_t voices;
} ti_audio_config;
typedef struct ti_music_event { uint16_t duration, period; uint8_t voice, volume; } ti_music_event;
typedef struct ti_phrase { const uint8_t *data; uint8_t length; } ti_phrase;
typedef struct ti_speech_bank {
    const ti_phrase *phrases;
    uint8_t count;
    const uint8_t *number_ids; /* 0..19, twenty..ninety, hundred, thousand; NULL omits numbers */
} ti_speech_bank;
/* Exclusive slot-4 VIA/AY/SSI ownership. No mode/slot swaps after init.
 * Init registers a ProDOS interrupt receiver; shutdown removes it. */
ti_error ti_audio_init(const ti_audio_config *config);
ti_error ti_audio_shutdown(void);
ti_error ti_audio_update(void);
uint32_t ti_audio_ticks(void);
uint8_t ti_audio_voices(void);
uint8_t ti_audio_clock_valid(void);
uint32_t ti_audio_source_hz(void);
uint16_t ti_audio_tick_divisor(void);
void ti_audio_mark_gap(void);
ti_error ti_audio_resume_clock(void);
ti_error ti_audio_reserve(uint16_t music_voices);
/* Voice n, counting from 0, of those ti_audio_reserve leaves to effects;
 * 255, which ti_audio_effect rejects, when fewer are left. One table of
 * effect voices then suits any card and reservation. */
uint8_t ti_audio_effect_voice(uint8_t n);
ti_error ti_music_start(const ti_music_event *events, uint16_t count, uint8_t loop);
/* A pattern song from tools/music.py. Track i plays on the i-th reserved
 * voice; tracks beyond the reserved voices are not played. */
ti_error ti_song_start(const uint8_t *song, uint16_t size, uint8_t loop);
void ti_music_stop(void);
ti_error ti_audio_effect(uint8_t voice, uint16_t period, uint8_t volume,
                         uint16_t duration, uint8_t priority);
/* AY envelope period/shape are shared by all three voices of one chip.
 * MB with speech enabled permits envelopes only on voices 3..5.
 * Every trigger writes register 13, even when the shape is unchanged. */
ti_error ti_audio_envelope(uint16_t voices, uint16_t period, uint8_t shape);
ti_error ti_audio_envelope_stop(uint16_t voices);
/* Banks/events are borrowed near read-only data until stop/rebind/shutdown. */
ti_error ti_speech_bind(const ti_speech_bank *bank);
ti_error ti_speech_say(uint8_t phrase, uint8_t priority);
ti_error ti_speech_number(uint16_t value, uint8_t priority);
uint8_t ti_speech_busy(void);
void ti_speech_stop(void);
ti_error ti_speech_voice(uint8_t preset, uint8_t pitch, uint8_t rate);
#endif
