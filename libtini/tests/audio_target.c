#include "libtini.h"
#include "libtini/audio.h"
#include "libtini/input.h"
#include "audio_speech.h"
#include "audio_song.h"
volatile uint16_t test_checks,test_failed;
volatile uint8_t test_mode,test_no_speech;
volatile uint8_t test_return;
volatile uint8_t test_envelope_phase;
volatile uint8_t test_reject_phase;
volatile uint8_t test_gap_phase;
volatile uint8_t test_stick_phase;
volatile uint8_t test_paddle[2];
volatile uint8_t test_key_phase;
volatile uint8_t test_voice_phase;
volatile uint8_t test_song_phase;
extern uint8_t ti_audio_ay_shadow[4][14];
extern uint16_t ti_audio_music_mask(void);
static uint16_t envelope_voice;
static uint8_t key;
static ti_audio_config config;
ti_joystick joystick;
static uint32_t began;
static uint16_t i;
static const ti_music_event melody[]={{2,478,0,9},{2,319,0,9},{2,239,0,9},{2,0,0,0}};
static const ti_music_event envelope_melody[]={{0,478,0,9},{100,319,3,9}};
static const uint8_t repeated[]={10,10};
static const ti_phrase repeated_phrases[]={{repeated,2}};
static const ti_speech_bank repeated_bank={repeated_phrases,1,0};
static void check(uint8_t yes,uint16_t id){++test_checks;if(!yes&&!test_failed)test_failed=id;}
static uint8_t bad[TEST_SONG_SIZE];
/* One changed byte makes the song invalid. */
static void corrupt(uint16_t at,uint8_t value,uint16_t id)
{
    uint8_t old=bad[at];
    bad[at]=value;check(ti_song_start(bad,TEST_SONG_SIZE,1)==TI_E_RANGE,id);bad[at]=old;
}
static uint32_t fake_now;
static uint32_t fake_ticks(void){return fake_now;}
static void wait(uint8_t ticks)
{
    uint32_t until=ti_audio_ticks()+ticks;
    while ((int32_t)(ti_audio_ticks()-until)<0) ti_audio_update();
}
int main(void)
{
    config.personality=test_mode==1||test_mode==3?TI_AUDIO_PHASOR:TI_AUDIO_MOCKINGBOARD;
    config.speech=1;config.ducking=1;
    if(test_mode==2||test_mode==4){test_return=ti_audio_init(&config);check(test_return==TI_E_UNAVAILABLE,1);return 0;}
    check(ti_song_start(test_song,TEST_SONG_SIZE,1)==TI_E_STATE,130);
    check(ti_audio_effect_voice(0)==255,161);
    config.via_hz=99999UL;check(ti_audio_init(&config)==TI_E_RANGE,51);
    config.via_hz=4000001UL;check(ti_audio_init(&config)==TI_E_RANGE,52);
    config.via_hz=0;
    check(ti_audio_init(&config)==TI_OK,2);
    check(ti_audio_source_hz()==1000000UL,53);
    check(ti_audio_tick_divisor()==10000,54);
    check(ti_audio_voices()==(test_mode==1?12:6),3);
    /* Effect voices count from the first the music leaves: 3 at start. */
    check(ti_audio_effect_voice(0)==3&&ti_audio_effect_voice(ti_audio_voices()-4)==ti_audio_voices()-1&&
          ti_audio_effect_voice(ti_audio_voices()-3)==255,162);
    check(ti_audio_init(&config)==TI_E_STATE,4);
    check(ti_audio_clock_valid(),5);
    /* Fixed steps from a scripted clock: 30 a second from 100 ticks. */
    check(ti_steps_begin(0,100,30,30)==TI_E_ARGUMENT,86);
    check(ti_steps_begin(fake_ticks,1000,100,30)==TI_E_RANGE,87);
    fake_now=70000UL;
    check(ti_steps_begin(fake_ticks,100,30,30)==TI_OK,88);
    fake_now+=10;check(ti_steps_due()==3,89);
    fake_now+=5;check(ti_steps_due()==1,90);
    fake_now+=2;check(ti_steps_due()==1,91);
    fake_now+=100;check(ti_steps_due()==30,92);
    fake_now+=101;check(ti_steps_due()==TI_STEPS_GAP,93);
    fake_now+=3;check(ti_steps_due()==0,94);
    /* Memory and video calls note display gaps; that is not a clock gap. */
    ti_time_note_gap();check(ti_steps_due()==0,95);
    /* Time beyond max_steps is dropped, less one partial step. */
    check(ti_steps_begin(fake_ticks,100,30,2)==TI_OK,96);
    fake_now+=20;check(ti_steps_due()==2,126);
    check(ti_steps_due()==0,127);
    fake_now+=1;check(ti_steps_due()==1,128);
    if(test_mode==6)return 0; /* Exercise startup's cleanup-failure retry UI. */
    check(ti_speech_bind(&ti_demo_speech)==TI_OK,6);
    check(ti_music_start(melody,4,1)==TI_OK,7);
    test_reject_phase=1;
    check(ti_audio_reserve(0)==TI_E_BUSY,74);
    check(ti_audio_music_mask()==7,75);
    test_reject_phase=2;
    check(ti_audio_envelope(8,100,9)==TI_E_BUSY,55);
    check(ti_audio_envelope(1,0,9)==TI_E_RANGE,56);
    check(ti_audio_reserve(63)==TI_OK,65);
    if(test_mode!=1)check(ti_audio_envelope(1,100,9)==TI_E_BUSY,66);
    envelope_voice=test_mode==1?1:8;
    check(ti_audio_envelope(envelope_voice,0x1234,9)==TI_OK,57);
    check(ti_audio_envelope(envelope_voice,0x1234,9)==TI_OK,58);
    check(ti_audio_envelope(envelope_voice<<1,100,9)==TI_E_BUSY,59);
    check(ti_audio_envelope(envelope_voice|(envelope_voice<<1),0x1234,9)==TI_OK,60);
    check(ti_audio_reserve(0)==TI_E_BUSY,61);
    check(ti_audio_envelope_stop(63)==TI_OK,62);
    check(ti_audio_reserve(7)==TI_OK,67);
    check(ti_audio_effect(0,400,8,5,1)==TI_E_BUSY,8);
    check(ti_audio_effect(3,400,8,5,3)==TI_OK,9);
    check(ti_audio_effect(3,400,8,5,2)==TI_E_BUSY,10);
    test_reject_phase=3;
    check(ti_audio_reserve(15)==TI_E_BUSY,76);
    check(ti_audio_music_mask()==7,77);
    test_reject_phase=4;
    check(ti_speech_number(10000,1)==TI_E_RANGE,11);
    check(ti_speech_say(SAY_READY,1)==TI_OK,12);
    check(ti_speech_say(SAY_READY,1)==TI_OK,13);
    check(ti_speech_say(SAY_READY,1)==TI_OK,14);
    check(ti_speech_say(SAY_READY,1)==TI_OK,15);
    check(ti_speech_say(SAY_READY,1)==TI_E_FULL,16);
    ti_audio_update();
    check(ti_speech_busy(),17);
    check(ti_speech_say(SAY_PUMP,TI_SPEECH_INTERRUPT|5)==TI_OK,18);
    check(ti_speech_say(SAY_READY,TI_SPEECH_INTERRUPT|1)==TI_E_BUSY,19);
    ti_speech_stop();check(!ti_speech_busy(),20);
    check(ti_speech_number(9999,2)==TI_OK,21);
    ti_audio_update();wait(4);ti_speech_stop();
    check(ti_speech_voice(2,0x55,12)==TI_OK,22);
    check(ti_speech_voice(3,0,10)==TI_E_ARGUMENT,23);
    check(ti_speech_say(SAY_READY,1)==TI_OK,24);
    began=ti_audio_ticks();
    if(test_no_speech) {
        while (ti_audio_ticks()-began<205) ti_audio_update();
        check(!ti_speech_busy(),25);
        check(ti_speech_say(SAY_READY,1)==TI_E_UNAVAILABLE,26);
    } else {
        while(ti_speech_busy() && ti_audio_ticks()-began<100)ti_audio_update();
        check(!ti_speech_busy(),27);
        check(ti_audio_ticks()-began<100,28);
        check(ti_speech_bind(&repeated_bank)==TI_OK,48);
        check(ti_speech_number(1,1)==TI_E_UNAVAILABLE,78);
        ti_music_stop();
        check(ti_audio_reserve(15)==TI_OK,68);
        check(ti_music_start(envelope_melody,2,1)==TI_OK,69);
        ti_audio_update();
        check(ti_audio_envelope(envelope_voice,100,9)==TI_OK,70);
        test_envelope_phase=1;
        check(ti_speech_say(0,1)==TI_OK,49);
        ti_audio_update();
        check(ti_audio_ay_shadow[test_mode==1?0:2][8]==0,71);
        began=ti_audio_ticks();
        while(ti_speech_busy()&&ti_audio_ticks()-began<40)ti_audio_update();
        check(!ti_speech_busy(),50);
        check(ti_audio_ay_shadow[test_mode==1?0:2][8]==16,72);
        test_envelope_phase=2;
        check(ti_audio_envelope_stop(envelope_voice)==TI_OK,73);
    }
    /* Pattern songs: rejected layouts, then playback Python checks. */
    ti_music_stop();
    check(ti_audio_reserve(7)==TI_OK,131);
    check(ti_song_start(0,TEST_SONG_SIZE,1)==TI_E_ARGUMENT,132);
    check(ti_song_start(test_song,7,1)==TI_E_ARGUMENT,133);
    for(i=0;i<TEST_SONG_SIZE;++i)bad[i]=test_song[i];
    check(ti_song_start(bad,TEST_SONG_SIZE-1,1)==TI_E_RANGE,134);
    corrupt(2,0,135);corrupt(2,13,136);corrupt(4,2,137);corrupt(1,0,138);corrupt(5,0,158);
    /* The last track's floor and the last period's high byte. */
    corrupt(6+3*test_song[2],16,159);
    corrupt(6+3*test_song[2]+2*test_song[5],8,160);
    /* The first order, the first pattern byte, the last pattern end and
     * the first pattern offset. */
    i=7+3*test_song[2]+2*test_song[5]+2*test_song[6];
    corrupt(i,test_song[6],139);
    corrupt(i+test_song[2]*test_song[3],0x70,140);
    corrupt(TEST_SONG_SIZE-1,0x80,141);
    corrupt(i-2*test_song[6],0,142);
    check(ti_song_start(bad,TEST_SONG_SIZE,1)==TI_OK,143);
    check(ti_audio_reserve(3)==TI_E_BUSY,144);
    check(ti_audio_reserve(15)==TI_OK,145);
    check(ti_audio_effect_voice(0)==4&&ti_audio_effect_voice(1)==5,163);
    ti_music_stop();
    test_song_phase=1;
    check(ti_song_start(test_song,TEST_SONG_SIZE,1)==TI_OK,146);
    wait(60);
    /* One reserved voice plays only the first track, once. */
    test_song_phase=2;
    ti_music_stop();
    check(ti_audio_reserve(1)==TI_OK,147);
    check(ti_song_start(test_song,TEST_SONG_SIZE,0)==TI_OK,148);
    check(ti_audio_reserve(3)==TI_OK,149);
    check(ti_audio_reserve(2)==TI_E_BUSY,150);
    test_song_phase=3;
    wait(40);
    test_song_phase=4;
    check(ti_audio_reserve(0)==TI_OK,151);
    /* More than 32 due rows end the score with TI_E_TIMING. */
    check(ti_audio_reserve(1)==TI_OK,152);
    check(ti_song_start(fast_song,FAST_SONG_SIZE,1)==TI_OK,153);
    began=ti_audio_ticks();
    while(ti_audio_ticks()-began<40){}
    check(ti_audio_update()==TI_E_TIMING,154);
    check(ti_audio_resume_clock()==TI_OK,155);
    check(ti_audio_reserve(0)==TI_OK,156);
    check(ti_audio_effect_voice(0)==0&&ti_audio_effect_voice(ti_audio_voices()-1)==ti_audio_voices()-1,164);
    check(ti_audio_reserve(7)==TI_OK,157);
    ti_audio_mark_gap();check(!ti_audio_clock_valid(),29);
    began=ti_audio_ticks();
    test_gap_phase=1;
    for(i=0;i<1024;++i)ti_input_buttons();
    test_gap_phase=2;
    check(ti_audio_ticks()==began,79);
    check(ti_audio_update()==TI_E_TIMING,30);
    check(ti_audio_resume_clock()==TI_OK,31);
    check(ti_audio_clock_valid(),32);
    wait(2);check(ti_audio_ticks()>began,80);
    check(ti_audio_update()==TI_OK,33);
    check(ti_joystick_read(&joystick)==TI_OK,34);
    /* Fixture paddles time out after 600 and 1700 device clocks: 54 and 154. */
    check(joystick.x>40&&joystick.x<70&&joystick.y>135&&joystick.y<175,35);
    /* A RamWorks selector write strobes the paddles. Once x has finished, y
     * still runs from that strobe and would read short if triggered now. */
    *(volatile uint8_t *)0xC073=0;
    while(*(volatile uint8_t *)0xC064&128);
    check(ti_joystick_read(&joystick)==TI_OK,84);
    check(joystick.x>40&&joystick.x<70&&joystick.y>135&&joystick.y<175,85);
    /* An unfinished axis saturates; the finished one remains a reading. */
    test_stick_phase=1;
    check(ti_joystick_read(&joystick)==TI_E_TIMING,81);
    check(joystick.x>40&&joystick.x<70&&joystick.y==255,82);
    test_stick_phase=0;wait(1);
    check(ti_joystick_read(&joystick)==TI_OK&&joystick.y>135&&joystick.y<175,83);
    /* Calibrated directions. With no stick, four reads report ABSENT; the
     * next waits three seconds without measuring (Python checks). */
    test_stick_phase=2;
    for(i=0;i<4;++i)check(ti_stick_read(0)==TI_STICK_ABSENT,104);
    test_stick_phase=3;check(ti_stick_read(0)==TI_STICK_ABSENT,105);
    test_stick_phase=0;test_paddle[0]=test_paddle[1]=128;
    ti_stick_recalibrate();
    check(ti_stick_read(&joystick)==0,106);
    check(joystick.x>120&&joystick.x<142&&joystick.y>120&&joystick.y<142,107);
    test_paddle[0]=250;check(ti_stick_read(0)==TI_STICK_RIGHT,108);
    test_paddle[0]=20;check(ti_stick_read(0)==TI_STICK_LEFT,109);
    test_paddle[0]=128;test_paddle[1]=20;check(ti_stick_read(0)==TI_STICK_UP,110);
    test_paddle[0]=250;test_paddle[1]=250;check(ti_stick_read(0)==(TI_STICK_RIGHT|TI_STICK_DOWN),111);
    test_paddle[0]=test_paddle[1]=128;check(ti_stick_read(0)==0,112);
    /* Once a stick has answered, an unfinished axis is full deflection. */
    test_stick_phase=1;check(ti_stick_read(0)==TI_STICK_DOWN,113);
    test_stick_phase=0;test_paddle[0]=test_paddle[1]=0;wait(1);
    check(ti_input_buttons()==5,36);
    ti_input_reset();check(ti_input_key(&key)==TI_E_UNAVAILABLE,37);
    /* Python injects A at the next hardware keyboard read. */
    for(i=0;i<8;++i) check(ti_input_poll()==TI_OK,38);
    check(ti_input_poll()==TI_E_NOMEM,39);
    for(i=0;i<8;++i){check(ti_input_key(&key)==TI_OK,40);check(key=='A',41);}
    check(ti_input_key(&key)==TI_E_UNAVAILABLE,42);
    /* Held keys through the latch, strobe and any-key-down bit. */
    test_key_phase=1;
    check(ti_input_held()=='D',97);
    check(ti_input_key(&key)==TI_E_UNAVAILABLE,98);
    test_key_phase=2;
    check(ti_input_held()=='S',99);
    check(ti_input_poll()==TI_OK&&ti_input_key(&key)==TI_OK&&key=='S',100);
    test_key_phase=3;
    check(ti_input_held()=='W',101);
    check(ti_input_key(&key)==TI_OK&&key=='W',102);
    test_key_phase=4;
    check(ti_input_held()==0,103);
    test_key_phase=0;
    check(ti_mouse_read(&joystick)==TI_E_UNAVAILABLE,43);
    if(test_mode==5) {
        check(ti_audio_shutdown()==TI_E_IO,63);
        check(!ti_audio_clock_valid()&&ti_audio_voices()!=0,64);
    }
    check(ti_audio_shutdown()==TI_OK,44);check(ti_audio_voices()==0,45);
    check(ti_joystick_read(&joystick)==TI_E_UNAVAILABLE,46);
    check(ti_audio_shutdown()==TI_OK,47);
    if(test_mode<2) {
        /* Two voices round up to one chip of three; updates touch only it. */
        config.voices=2;
        check(ti_audio_init(&config)==TI_OK,121);
        check(ti_audio_voices()==3,122);
        check(ti_audio_reserve(0)==TI_OK,129);
        check(ti_audio_effect_voice(2)==2&&ti_audio_effect_voice(3)==255,165);
        test_voice_phase=1;
        check(ti_audio_effect(2,300,9,4,1)==TI_OK,123);
        check(ti_audio_effect(3,300,9,4,1)==TI_E_RANGE,124);
        wait(6);
        test_voice_phase=2;
        check(ti_audio_shutdown()==TI_OK,125);
        config.voices=0;
    }
    return 0;
}
