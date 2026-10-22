/* A libtini starter: a square that held keys or a joystick move at a fixed
 * 30 updates a second, a tone on a joystick button, and Q to quit. */
#include "libtini.h"

static ti_surface screen;
static const uint16_t colors[16]={0x012,0x123,0x235,0x346,0x467,0x68A,0x9BC,0xDEF,
 0xFA6,0xD64,0x832,0x4DC,0xA8F,0xFFB,0x57A,0x9ED};
/* Three voices on one AY chip: the least audio work per update. */
static ti_audio_config audio={TI_AUDIO_MOCKINGBOARD,0,0,0,3};
/* The square's position; tests read it. The caller near arena's NEARBSS
 * holds it, outside main memory, and startup zeroes it like BSS. */
#pragma bss-name (push, "NEARBSS")
int16_t starter_x, starter_y;
#pragma bss-name (pop)

static void square(uint8_t color)
{
    ti_rect r;
    r.x=starter_x;r.y=starter_y;r.width=16;r.height=16;
    ti_gfx_rect(&screen,starter_x,starter_y,16,16,color);
    ti_gfx_present(&screen,&r,0);
}

/* WASD or arrows while held, plus the stick's calibrated directions. */
static uint8_t directions(void)
{
    uint8_t d=ti_stick_read(0),k=ti_input_held();
    if(d==TI_STICK_ABSENT)d=0;
    if(k>='a'&&k<='z')k-=32;
    if(k=='W'||k==11)d|=TI_STICK_UP;
    if(k=='S'||k==10)d|=TI_STICK_DOWN;
    if(k=='A'||k==8)d|=TI_STICK_LEFT;
    if(k=='D'||k==21)d|=TI_STICK_RIGHT;
    return d;
}

int main(void)
{
    uint8_t key=0,steps,d,buttons,last_buttons=0;
    /* The canvas, display backup and audio init's temporary storage loan
     * need 97,536 bytes: three 48,640-byte resource banks, selectors 1-3. */
    if(ti_init(1,3)!=TI_OK)return 1;
    if(ti_gfx_surface_create(&screen,320,200)!=TI_OK)return 1;
    if(ti_gfx_begin(colors)!=TI_OK)return 1;
    ti_gfx_clear(&screen,0);
    ti_gfx_rect(&screen,0,0,320,12,1);
    ti_gfx_text(&screen,8,2,"MY FIRST LIBTINI GAME",13);
    ti_gfx_text(&screen,8,190,"HOLD WASD OR ARROWS, OR USE A STICK. Q QUITS",7);
    /* The audio driver also owns the clock and joystick timer. */
    if(ti_audio_init(&audio)==TI_OK) {
        ti_audio_reserve(0);
        ti_steps_begin(ti_audio_ticks,TI_AUDIO_TICKS_PER_SECOND,30,30);
    } else ti_gfx_text(&screen,8,96,"A SLOT 4 AUDIO CARD IS REQUIRED",9);
    ti_gfx_present(&screen,0,0);
    starter_x=152;starter_y=92;square(11);
    while(key!='Q') {
        ti_audio_update();ti_input_poll();
        while(ti_input_key(&key)==TI_OK&&key!='Q'&&key!='q');
        if(key=='q')key='Q';
        buttons=ti_input_buttons()&3;
        if(buttons&&!last_buttons)ti_audio_effect(0,300,12,10,1);
        last_buttons=buttons;
        steps=ti_steps_due();
        if(!steps||steps==TI_STEPS_GAP)continue;
        d=directions();
        if(!d)continue;
        square(0);
        /* Two pixels a step, inside the play area. */
        while(steps--) {
            if((d&TI_STICK_LEFT)&&starter_x>0)starter_x-=2;
            if((d&TI_STICK_RIGHT)&&starter_x<304)starter_x+=2;
            if((d&TI_STICK_UP)&&starter_y>14)starter_y-=2;
            if((d&TI_STICK_DOWN)&&starter_y<172)starter_y+=2;
        }
        square(11);
    }
    ti_audio_shutdown();ti_gfx_end();ti_gfx_surface_free(&screen);ti_shutdown();return 0;
}
