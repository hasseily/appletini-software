#include "libtini.h"
#include "libtini/audio.h"
#include "libtini/input.h"
#include "audio_speech.h"
#include "audio_music.h"
ti_audio_config demo_config = {TI_AUDIO_MOCKINGBOARD,1,1,0};
static void message(const char *s)
{
    uint8_t i;
    for (i=0;s[i] && i<40;++i) ((uint8_t*)0x400)[i]=(uint8_t)s[i]|128;
}
int main(void)
{
    uint8_t key;
    if (ti_audio_init(&demo_config)) {
        message("AUDIO CLOCK UNAVAILABLE - PRESS Q");
    } else {
        message("MUSIC AND SPEECH: 1 READY 2 NUMBER Q EXIT");
        ti_speech_bind(&ti_demo_speech);
        ti_music_start(ti_demo_music,TI_DEMO_MUSIC_COUNT,1);
        ti_speech_say(SAY_WELCOME,1);
    }
    for (;;) {
        ti_audio_update(); ti_input_poll();
        if (ti_input_key(&key)==TI_OK) {
            if (key=='Q'||key=='q'||key==27) break;
            if (key=='1') ti_speech_say(SAY_READY,1);
            if (key=='2') ti_speech_number(1984,1);
            if (key=='S'||key=='s') ti_speech_stop();
        }
    }
    ti_audio_shutdown(); return 0;
}
