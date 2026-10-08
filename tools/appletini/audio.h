/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef APPLETINI_AUDIO_H
#define APPLETINI_AUDIO_H
#include <stddef.h>
#include <stdint.h>
typedef struct ap_audio ap_audio;
/* Guest-time synthesis. Four seconds of bounded PCM; callers drain before
 * three seconds. An overflow is sticky and reported, never hidden. */
ap_audio *ap_audio_new(unsigned rate, uint64_t hz, double bus_hz,
                       uint64_t origin, unsigned mode, unsigned speaker);
void ap_audio_free(ap_audio *a);
void ap_audio_sync(ap_audio *a, uint64_t tick);
void ap_audio_event(ap_audio *a, uint64_t tick, unsigned kind,
                    unsigned chip, unsigned reg, unsigned value);
void ap_audio_seed(ap_audio *a, unsigned chip, const uint8_t registers[16]);
size_t ap_audio_count(const ap_audio *a);
size_t ap_audio_take(ap_audio *a, int16_t *stereo, size_t frames);
unsigned ap_audio_rate(const ap_audio *a);
uint64_t ap_audio_frames(const ap_audio *a);
int ap_audio_full(const ap_audio *a);
int ap_audio_overflow(const ap_audio *a);
#endif
