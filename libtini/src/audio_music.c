#include "internal.h"
#include "audio_internal.h"
/* The event score player, pulled only by ti_music_start. */
static const ti_music_event *music;
static uint16_t music_count, music_index;
static uint8_t music_loop;
static uint8_t play(uint32_t now)
{
    uint8_t steps = 0;
    const ti_music_event *event;
    while (ti_audio_due(now, ti_audio_music_end)) {
        if (steps++ == 32) return 1;
        if (music_index == music_count) {
            if (!music_loop) { ti_music_stop(); return 0; }
            music_index = 0;
        }
        event = &music[music_index++]; ti_audio_music_volume[event->voice] = event->volume;
        ti_audio_tone(event->voice, event->period, event->volume);
        ti_audio_music_end += event->duration;
    }
    return 0;
}
ti_error ti_music_start(const ti_music_event *events, uint16_t count, uint8_t loop)
{
    uint16_t i, used = 0, reserved = ti_audio_music_mask();
    uint8_t voices = ti_audio_voices();
    if (!voices) return TI_E_STATE;
    if (!count || count > 512 || !events || !ti_near_valid(events, count * sizeof(*events), 0))
        return TI_E_ARGUMENT;
    for (i = 0; i < count; ++i) {
        if (events[i].voice >= voices || events[i].volume > 15 ||
            events[i].period > 2047 || !(reserved & (1U << events[i].voice))) return TI_E_RANGE;
        used |= 1U << events[i].voice;
    }
    ti_music_stop(); music = events; music_count = count; music_index = 0;
    music_loop = loop != 0; ti_audio_music_end = ti_audio_ticks();
    ti_audio_music_voices = used; ti_audio_player = play; return TI_OK;
}
