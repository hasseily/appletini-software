/*
 * Appletini Bosconian -- entry point, state machine, HUD, title screen and
 * debug mailbox. World logic lives in game.c (see game.h).
 *
 * Frame order (docs/DESIGN.md): video_wait_vbl(); read input; game logic;
 * build the display list and stars; video_render(); sound_update();
 * mailbox_tick().
 */

#include "game.h"

void prodos_quit(void);         /* prodos_quit.s: video is already shut down */

static void enter_play_round(void);
static void dl_ship_at(u8 y);

/* ---- frame budget: more AUX bytes than this stalls the 33 MHz bus ---- */
#define WRITE_BUDGET 10000

/* ---- state ---- */
static u8 state;
static u8 prev_in;              /* input mask of the last frame (edges) */
static u16 state_timer;         /* frames left in a timed state */
static u8 ramworks_banks;
static u16 speed_iters;
static u8 mhz;
static u16 max_writes;
static u16 dropped_frames;
static u8 title_blink;

/* ---- side panel layout (docs/DESIGN.md section 6): the arcade's panel,
 * 64 px wide, squeezed from 224 to 200 rows ---- */
#define PANEL_Y_HI 0            /* HI-SCORE caption, then its digits */
#define PANEL_Y_HI_VALUE 8
#define PANEL_Y_1UP 16
#define PANEL_Y_SCORE 24
#define PANEL_Y_CONDITION 36    /* the 62x8 CONDITION caption sprite */
#define PANEL_Y_COND_BOX 44     /* 16 rows: rule, GREEN/YELLOW/RED, rule */
#define RADAR_Y 64              /* the whole 1024x1792 world at 1/16: 64x112 */
#define RADAR_H 112
#define PANEL_Y_LIVES 176       /* up to four 16x16 ship icons */
#define PANEL_Y_ROUND 192
#define RADAR_COLOR C_PURPLE    /* the arcade radar's background */

/* radar dots drawn last frame (erased before the new ones are drawn) */
#define RADAR_MAX 12
static u8 radar_px[RADAR_MAX];
static u8 radar_py[RADAR_MAX];
static u8 radar_n;
static u8 radar_new_px[RADAR_MAX];
static u8 radar_new_py[RADAR_MAX];
static u8 radar_new_color[RADAR_MAX];
static u8 radar_new_n;
static u8 radar_marks[BASE_MAX];    /* base marker drawn on the radar */

static char textbuf[36];

static const u8 cond_color[3] = { C_GREEN, C_YELLOW, C_RED };
static const char cond_name0[] = "GREEN";
static const char cond_name1[] = "YELLOW";
static const char cond_name2[] = "RED";
static const u8 cond_px[3] = { 6, 4, 10 };     /* byte column that centres each word */

/* ------------------------------------------------------------------ */
/* number formatting (no stdio in the none target)                      */
/* ------------------------------------------------------------------ */
/* write v as exactly `digits` decimal characters (leading zeros) */
static void fmt_u16(char *dst, u16 v, u8 digits)
{
    u8 i;
    for (i = digits; i > 0; --i) {
        dst[i - 1] = (char)('0' + v % 10);
        v /= 10;
    }
}

/* write v right-aligned in 7 columns, blanks in front, NUL terminated */
static void fmt_score(char *dst, u32 v)
{
    static const u32 pow10[7] = { 1000000UL, 100000UL, 10000UL, 1000UL, 100UL, 10UL, 1UL };
    u8 i, d;
    u8 started = 0;
    if (v > 9999999UL) v = 9999999UL;
    for (i = 0; i < 7; ++i) {
        d = 0;
        while (v >= pow10[i]) { v -= pow10[i]; ++d; }
        if (d || started || i == 6) {
            dst[i] = (char)('0' + d);
            started = 1;
        } else {
            dst[i] = ' ';
        }
    }
    dst[7] = 0;
}

/* ------------------------------------------------------------------ */
/* startup                                                              */
/* ------------------------------------------------------------------ */
/* Like Invasion's ramworks_init: tag banks 1..127, then read them back in
 * order and stop at the first bank that does not answer. Bank 0 counts. */
static u8 ramworks_init(void)
{
    u8 bank;
    u8 found = 1;
    for (bank = 1; bank < 128; ++bank) {
        REG8(RAMWORKS) = bank;
        REG8(RAMWRTON) = 0;
        REG8(0x1000) = bank;
        REG8(0x1001) = (u8)~bank;
        REG8(RAMWRTOFF) = 0;
    }
    for (bank = 1; bank < 128; ++bank) {
        if (ramworks_probe(bank) != bank) break;
        ++found;
    }
    REG8(RAMWORKS) = 0;
    REG8(RAMRDOFF) = 0;
    REG8(RAMWRTOFF) = 0;
    return found;
}

/* ------------------------------------------------------------------ */
/* mailbox                                                              */
/* ------------------------------------------------------------------ */
static void mailbox_tick(void)
{
    MAILBOX->state = state;
    MAILBOX->frame_lo = (u8)frame;
    MAILBOX->frame_hi = (u8)(frame >> 8);
    MAILBOX->score = score;
    MAILBOX->round = round_no;
    MAILBOX->lives = lives;
    MAILBOX->condition = condition;
    MAILBOX->player_x = player_x;
    MAILBOX->player_y = player_y;
    MAILBOX->heading = player_h;
    MAILBOX->bases_left = bases_left;
    MAILBOX->enemies_alive = enemies_alive;
    MAILBOX->dl_count = dl_count;
    MAILBOX->frame_writes = video_frame_writes;
    MAILBOX->max_frame_writes = max_writes;
    MAILBOX->ramworks_banks = ramworks_banks;
    MAILBOX->speed_probe = speed_iters;
    MAILBOX->sfx_now = sound_current_sfx;
    MAILBOX->music_track = sound_current_track;
    MAILBOX->speech_phrase = speech_current;
    MAILBOX->input_mask = prev_in;
    MAILBOX->formation_active = formation_active;
    MAILBOX->spy_active = spy_active;
    MAILBOX->last_event = last_event;
    MAILBOX->dropped_frames = dropped_frames;
    MAILBOX->star_count = star_count;
    MAILBOX->joy_status = input_joy_status();
    MAILBOX->sound_chips = sound_chips;
}

static void mailbox_init(void)
{
    MAILBOX->magic[0] = 0;
    mailbox_tick();
    MAILBOX->magic[1] = '1';
    MAILBOX->magic[2] = '3';
    MAILBOX->magic[3] = 'B';
    MAILBOX->magic[0] = 'A';        /* written last */
}

/* ------------------------------------------------------------------ */
/* side panel                                                           */
/* ------------------------------------------------------------------ */
static void hud_labels(void)
{
    panel_text(0, PANEL_Y_HI, C_RED, "HI-SCORE");
    panel_text(0, PANEL_Y_1UP, C_WHITE, "1UP");
    panel_sprite(0, PANEL_Y_CONDITION, SPR_CAPTION_COND);
    panel_fill(0, RADAR_Y, PANEL_BYTES, RADAR_H, RADAR_COLOR);
    hud_dirty = HUD_ALL;
}

static void hud_lives(void)
{
    u8 i, n = lives;
    if (n > 4) n = 4;
    panel_fill(0, PANEL_Y_LIVES, PANEL_BYTES, 16, C_BLACK);
    for (i = 0; i < n; ++i) panel_sprite(i << 3, PANEL_Y_LIVES, SPR_ICON_SHIP);
}

static void hud_update(void)
{
    u8 d = hud_dirty;
    if (!d) return;
    hud_dirty = 0;
    if (d & HUD_HI) {
        fmt_score(textbuf, hi_score);
        panel_text(4, PANEL_Y_HI_VALUE, C_WHITE, textbuf);
    }
    if (d & HUD_SCORE) {
        fmt_score(textbuf, score);
        panel_text(4, PANEL_Y_SCORE, C_WHITE, textbuf);
    }
    if (d & HUD_COND) {
        /* the arcade's framed condition label in its colour */
        u8 c = cond_color[condition];
        panel_fill(0, PANEL_Y_COND_BOX, PANEL_BYTES, 16, C_BLACK);
        panel_fill(0, PANEL_Y_COND_BOX, PANEL_BYTES, 2, c);
        panel_fill(0, PANEL_Y_COND_BOX + 14, PANEL_BYTES, 2, c);
        panel_text(cond_px[condition], PANEL_Y_COND_BOX + 4, c,
                   condition == 0 ? cond_name0 :
                   (condition == 1 ? cond_name1 : cond_name2));
    }
    if (d & HUD_ROUND) {
        textbuf[0] = 'R'; textbuf[1] = 'O'; textbuf[2] = 'U';
        textbuf[3] = 'N'; textbuf[4] = 'D'; textbuf[5] = ' ';
        fmt_u16(textbuf + 6, round_no, 2);
        textbuf[8] = 0;
        panel_text(0, PANEL_Y_ROUND, C_GRAY, textbuf);
    }
    if (d & HUD_LIVES) hud_lives();
}

/* Radar: the world at 1/16 in the 64x112 box, like the arcade's. Bases are
 * the arcade's 8x8 marker tile, redrawn every frame so the dots that pass
 * over them leave no holes; the ship and the enemies that show (spy ship,
 * formation leader) are 2x2 dots erased in the background colour. */
static void radar_base_pos(u8 i, u8 *px, u8 *py)
{
    s16 x = (s16)(base_x[i] >> 4) - 4;
    s16 y = (s16)(base_y[i] >> 4) - 4;
    if (x < 0) x = 0;
    if (x > 56) x = 56;
    if (y < 0) y = 0;
    if (y > RADAR_H - 8) y = RADAR_H - 8;
    *px = (u8)(x >> 1);
    *py = (u8)(RADAR_Y + y);
}

/* new round or title: plain radar box, no markers */
static void radar_reset(void)
{
    u8 i;
    panel_fill(0, RADAR_Y, PANEL_BYTES, RADAR_H, RADAR_COLOR);
    for (i = 0; i < BASE_MAX; ++i) radar_marks[i] = 0;
    radar_n = 0;
    radar_new_n = 0;
}

static void radar_add(u16 x, u16 y, u8 color)
{
    u8 r;
    if (radar_new_n >= RADAR_MAX) return;
    r = (u8)(y >> 4);
    if (r > RADAR_H - 2) r = RADAR_H - 2;      /* a dot is two rows tall */
    radar_new_px[radar_new_n] = (u8)(x >> 5);
    radar_new_py[radar_new_n] = RADAR_Y + r;
    radar_new_color[radar_new_n] = color;
    ++radar_new_n;
}

static void radar_flush(void)
{
    u8 i, px, py;
    for (i = 0; i < radar_n; ++i) panel_dot(radar_px[i], radar_py[i], RADAR_COLOR);
    for (i = 0; i < base_count; ++i) {
        if (base_state[i] == BASE_ALIVE) {
            radar_base_pos(i, &px, &py);
            panel_sprite(px, py, SPR_ICON_BASE);
            radar_marks[i] = 1;
        } else if (radar_marks[i]) {
            radar_base_pos(i, &px, &py);
            panel_fill(px, py, 4, 8, RADAR_COLOR);
            radar_marks[i] = 0;
        }
    }
    for (i = 0; i < radar_new_n; ++i) {
        panel_dot(radar_new_px[i], radar_new_py[i], radar_new_color[i]);
        radar_px[i] = radar_new_px[i];
        radar_py[i] = radar_new_py[i];
    }
    radar_n = radar_new_n;
    radar_new_n = 0;
}

static void radar_update(u8 with_player)
{
    u8 i;
    radar_new_n = 0;
    for (i = 0; i < ENEMY_MAX; ++i) {
        if (en_type[i] == EN_SPY || (en_flags[i] & EF_LEADER)) {
            radar_add(en_x[i], en_y[i], C_RED);
        }
    }
    if (with_player && (frame & 8)) radar_add(player_x, player_y, C_WHITE);
    radar_flush();
}

/* ------------------------------------------------------------------ */
/* title screen                                                         */
/* ------------------------------------------------------------------ */
static void title_draw(void)
{
    u8 i;
    field_text_big(56, 40, C_WHITE, "BOSCONIAN");
    field_text(4, 80, C_GRAY, "APPLETINI //E SHR 320X200 60FPS");
    fmt_u16(textbuf, mhz, 2);
    textbuf[2] = ' '; textbuf[3] = 'M'; textbuf[4] = 'H'; textbuf[5] = 'Z';
    textbuf[6] = ' '; textbuf[7] = ' ';
    textbuf[8] = 'R'; textbuf[9] = 'A'; textbuf[10] = 'M'; textbuf[11] = 'W';
    textbuf[12] = 'O'; textbuf[13] = 'R'; textbuf[14] = 'K'; textbuf[15] = 'S';
    textbuf[16] = ' ';
    fmt_u16(textbuf + 17, ramworks_banks, 3);
    textbuf[20] = ' '; textbuf[21] = 'B'; textbuf[22] = 'A'; textbuf[23] = 'N';
    textbuf[24] = 'K'; textbuf[25] = 'S'; textbuf[26] = 0;
    field_text(24, 92, C_GRAY, textbuf);
    if (sound_chips == 4) field_text(36, 104, C_GRAY, "PHASOR NATIVE 12 VOICES");
    else field_text(44, 104, C_GRAY, "MOCKINGBOARD 6 VOICES");
    for (i = 0; i < 11; ++i) textbuf[i] = "HIGH SCORE "[i];
    fmt_score(textbuf + 11, hi_score);
    field_text(56, 120, C_CYAN, textbuf);
    field_text(48, 150, C_YELLOW, "PRESS FIRE OR RETURN");
    field_text(52, 176, C_DTEAL, "ESC QUITS TO PRODOS");
}

static void enter_title(void)
{
    state = ST_TITLE;
    world_clear();
    video_clear_playfield();
    radar_reset();
    stars_init(1);
    title_draw();
    title_blink = 0;
    dl_count = 0;
    sound_music(MUSIC_TITLE);
    input_joy_calibrate();
}

static void title_tick(u8 pressed)
{
    /* Esc and Q quit (both carry IN_QUIT); a bare P is ignored here */
    if (pressed & IN_QUIT) {
        sound_music(MUSIC_NONE);
        sound_update();
        sound_shutdown();
        video_shutdown();
        prodos_quit();
        return;
    }
    if (pressed & (IN_START | IN_FIRE)) {
        /* new game */
        rng_seed(frame | 1);
        score = 0;
        lives = 3;
        round_no = 1;
        next_extra = 20000UL;
        hud_dirty = HUD_ALL;
        world_new_round();
        enter_play_round();
        return;
    }
    /* blink the prompt every 32 frames */
    if (++title_blink == 32) {
        title_blink = 0;
        field_text(48, 150, (frame & 32) ? C_BLACK : C_YELLOW, "PRESS FIRE OR RETURN");
    }
    /* a slowly spinning ship above the text */
    dl_items[0].id = SPR_SHIP_0 + ((u8)(frame >> 4) & 7);
    dl_items[0].x = 120;
    dl_items[0].y = 60;
    dl_count = 1;
    stars_tick(1, 0);
}

/* ------------------------------------------------------------------ */
/* play states                                                          */
/* ------------------------------------------------------------------ */
static void enter_play_round(void)
{
    state = ST_PLAY;
    video_clear_playfield();
    radar_reset();
    stars_init(0);
    dl_ship_at(FIELD_CY - 8);       /* first frame: the ship, not a stale list */
    sound_tempo(condition);
    sound_music(MUSIC_BLASTOFF);
    speech_say(SAY_BLAST_OFF);
    last_event = EV_ROUND_START;
}

static void enter_play_respawn(void)
{
    state = ST_PLAY;
    world_respawn();
    sound_music(MUSIC_BLASTOFF);
    speech_say(SAY_BLAST_OFF);
}

static void enter_dying(void)
{
    state = ST_DYING;
    state_timer = 90;
    world_death_burst();
    sound_music(MUSIC_DEATH);
    sound_sfx(SFX_PLAYER_DIE);
    last_event = EV_PLAYER_DIED;
}

/* only the ship, centered at row y, holding its heading */
static void dl_ship_at(u8 y)
{
    dl_items[0].id = SPR_SHIP_0 + player_h;
    dl_items[0].x = FIELD_CX - 8;
    dl_items[0].y = y;
    dl_count = 1;
}

#define ROUND_CLEAR_SHIP_Y 56   /* above "ROUND CLEAR" (row 80) and the bonus (96) */

static void enter_round_clear(void)
{
    u16 bonus;
    state = ST_ROUND_CLEAR;
    state_timer = 120;
    video_clear_playfield();
    star_count = 0;
    dl_ship_at(ROUND_CLEAR_SHIP_Y);
    bonus = round_no > 60 ? 60000U : (u16)round_no * 1000U;
    add_score(bonus);
    field_text(84, 80, C_WHITE, "ROUND CLEAR");
    textbuf[0] = 'B'; textbuf[1] = 'O'; textbuf[2] = 'N'; textbuf[3] = 'U';
    textbuf[4] = 'S'; textbuf[5] = ' ';
    fmt_u16(textbuf + 6, bonus, 5);
    textbuf[11] = 0;
    field_text(84, 96, C_CYAN, textbuf);
    sound_music(MUSIC_ROUND_CLEAR);
    last_event = EV_ROUND_CLEAR;
}

static void enter_game_over(void)
{
    state = ST_GAME_OVER;
    state_timer = 180;
    video_clear_playfield();
    star_count = 0;
    dl_count = 0;
    field_text_big(56, 88, C_RED, "GAME OVER");
    sound_music(MUSIC_GAME_OVER);
    speech_say(SAY_GAME_OVER);
    last_event = EV_GAME_OVER;
}

static void enter_paused(void)
{
    state = ST_PAUSED;
    field_text(104, 96, C_WHITE, "PAUSED");
}

static void leave_paused(void)
{
    state = ST_PLAY;
    field_text(104, 96, C_BLACK, "PAUSED");   /* the next render restores sprites */
}

static void play_tick(u8 in, u8 pressed)
{
    if (pressed & (IN_PAUSE | IN_QUIT)) {
        enter_paused();
        return;
    }
    world_tick(in, 1);      /* the BLAST OFF track hands over to the ambient one itself */
    if (player_dead) {
        enter_dying();
        world_build_dl(0);
    } else if (round_done) {
        enter_round_clear();            /* sets its own display list */
        return;
    } else {
        world_build_dl(1);
    }
    stars_tick(cam_dx, cam_dy);
}

static void dying_tick(u8 in)
{
    world_tick(in, 0);
    world_build_dl(0);
    if (--state_timer == 0) {
        if (lives) --lives;
        hud_dirty |= HUD_LIVES;
        if (lives == 0) enter_game_over();
        else enter_play_respawn();
    }
}

static void round_clear_tick(void)
{
    dl_ship_at(ROUND_CLEAR_SHIP_Y);
    if (--state_timer == 0) {
        if (round_no < 99) ++round_no;
        world_new_round();
        enter_play_round();
    }
}

static void game_over_tick(void)
{
    dl_count = 0;
    if (--state_timer == 0) enter_title();
}

/* ------------------------------------------------------------------ */
/* main                                                                 */
/* ------------------------------------------------------------------ */
int main(void)                  /* never returns: the frame loop runs until QUIT */
{
    u8 in, pressed;
    u8 joy_mask = 0;

    REG8(TWSPEED) = 0;
    REG8(RAMRDOFF) = 0;
    REG8(RAMWRTOFF) = 0;
    ramworks_banks = ramworks_init();

    video_init();
    /* the probe loop runs about 1135 iterations per frame at 1 MHz */
    speed_iters = video_speed_probe();
    if (speed_iters == 0xFFFF) mhz = 99;
    else {
        u16 m = (speed_iters + 567) / 1135;
        mhz = m > 99 ? 99 : (u8)m;
    }
    /* one paddle poll of about 11 us at the measured clock (input.s) */
    input_joy_set_delay((u8)(mhz * 2 + 3));
    sound_init();

    frame = 0;
    score = 0;
    hi_score = 0;
    lives = 3;
    round_no = 1;
    condition = 0;
    player_x = START_X;
    player_y = START_Y;
    player_h = 0;
    bases_left = 0;
    base_count = 0;
    prev_in = 0;
    radar_n = 0;
    radar_new_n = 0;
    max_writes = 0;
    dropped_frames = 0;
    last_event = EV_NONE;
    state = ST_BOOT;

    hud_labels();
    hud_update();
    mailbox_init();
    enter_title();

    /* One pass per frame. video_wait_vbl returns right after line 0, where
     * the Appletini publishes the SHR shadow. The logic, the render burst
     * and the sound I/O then all finish before the next line 0, so every
     * published frame is complete. */
    for (;;) {
        video_wait_vbl();
        ++frame;

        /* the paddle timer is read by polling, about 1.4 ms of CPU time per
         * axis at any clock, so read one axis every fourth frame */
        if ((frame & 3) == 0) joy_mask = input_joy();
        in = input_keys() | joy_mask;
        pressed = in & (u8)~prev_in;
        prev_in = in;

        switch (state) {
        case ST_TITLE:
            title_tick(pressed);
            break;
        case ST_PLAY:
            play_tick(in, pressed);
            break;
        case ST_DYING:
            dying_tick(in);
            break;
        case ST_ROUND_CLEAR:
            round_clear_tick();
            break;
        case ST_GAME_OVER:
            game_over_tick();
            break;
        case ST_PAUSED:
            if (pressed & (IN_PAUSE | IN_QUIT | IN_START)) leave_paused();
            break;
        default:
            break;
        }

        if (state != ST_PAUSED) {
            video_render();
            if (video_frame_writes > max_writes) max_writes = video_frame_writes;
            if (video_frame_writes > WRITE_BUDGET) ++dropped_frames;
            hud_update();
            radar_update(state == ST_PLAY);
        }
        sound_update();
        mailbox_tick();
    }
}
