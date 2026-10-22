#include "audio_internal.h"
#define bank ti_audio_speech_bank
/* Pulled from the archive only by applications using spoken numbers. */
ti_error ti_speech_number(uint16_t value, uint8_t priority)
{
    speech_job job;
    uint8_t n, part;
    if (!bank) return TI_E_STATE;
    if (value > 9999) return TI_E_RANGE;
    if (!bank->number_ids) return TI_E_UNAVAILABLE;
    job.count = 0;
    if (value >= 1000) { job.ids[job.count++] = bank->number_ids[value / 1000];
        job.ids[job.count++] = bank->number_ids[29]; value %= 1000; }
    if (value >= 100) { job.ids[job.count++] = bank->number_ids[value / 100];
        job.ids[job.count++] = bank->number_ids[28]; value %= 100; }
    if (value >= 20) { n = (uint8_t)(value / 10); part = (uint8_t)(value % 10);
        job.ids[job.count++] = bank->number_ids[18 + n];
        if (part) job.ids[job.count++] = bank->number_ids[part];
    } else if (value || !job.count) job.ids[job.count++] = bank->number_ids[value];
    return ti_speech_submit(&job, priority);
}
