/*
 * Appletini Bosconian -- shared C/asm contract.
 * See docs/DESIGN.md. Every module includes this header; asm modules mirror
 * the ZP and constant values in bosco.inc (kept in sync by hand).
 */
#ifndef BOSCO_H
#define BOSCO_H

typedef unsigned char u8;
typedef signed char s8;
typedef unsigned int u16;
typedef signed int s16;
typedef unsigned long u32;

#define REG8(a) (*(volatile u8*)(a))

/* ---- Apple //e / Appletini soft switches ---- */
#define KBD        0xC000
#define STORE80OFF 0xC000
#define STORE80ON  0xC001
#define RAMRDOFF   0xC002
#define RAMRDON    0xC003
#define RAMWRTOFF  0xC004
#define RAMWRTON   0xC005
#define KBDSTRB    0xC010
#define RDVBLBAR   0xC019
#define NEWVIDEO   0xC029
#define TEXTON     0xC051
#define BUTTON0    0xC061
#define BUTTON1    0xC062
#define PADDLE0    0xC064
#define PADDLE1    0xC065
#define PTRIG      0xC070
#define RAMWORKS   0xC073
#define TWSPEED    0xC074

/* Phasor / Mockingboard, slot 4, Mockingboard-compatible mode */
#define VIA_A_ORB  0xC400
#define VIA_A_ORA  0xC401
#define VIA_A_DDRB 0xC402
#define VIA_A_DDRA 0xC403
#define VIA_A_PCR  0xC40C
#define VIA_A_IFR  0xC40D
#define VIA_A_IER  0xC40E
#define VIA_B_ORB  0xC480
#define VIA_B_ORA  0xC481
#define VIA_B_DDRB 0xC482
#define VIA_B_DDRA 0xC483
#define VIA_B_PCR  0xC48C
#define VIA_B_IFR  0xC48D
#define VIA_B_IER  0xC48E
#define SSI_DUR    0xC440
#define SSI_INF    0xC441
#define SSI_RATE   0xC442
#define SSI_CTL    0xC443
#define SSI_FILT   0xC444

/* ---- screen ---- */
#define FIELD_W    256
#define FIELD_H    200
#define FIELD_CX   128
#define FIELD_CY   100
#define PANEL_BYTES 32          /* panel is byte columns 0..31 (pixels 256..319) */

/* palette indexes (docs/DESIGN.md section 3) */
#define C_BLACK 0
#define C_WHITE 1
#define C_LGRAY 2
#define C_DGRAY 3
#define C_RED 4
#define C_ORANGE 5
#define C_YELLOW 6
#define C_GREEN 7
#define C_CYAN 8
#define C_BLUE 9
#define C_DBLUE 10
#define C_MAGENTA 11
#define C_PINK 12
#define C_BROWN 13
#define C_DGREEN 14
#define C_LBLUE 15


/* ---- sprite ids (fixed order, docs/DESIGN.md section 9) ---- */
#define SPR_SHIP_0 0        /* 0..7  16x16 player, heading 0=N clockwise */
#define SPR_ITYPE_0 8       /* 8..15 12x12 */
#define SPR_PTYPE_0 16      /* 16..23 12x12 */
#define SPR_ETYPE_0 24      /* 24..27 12x12 spin */
#define SPR_MINE_0 28       /* 28..29 12x12 */
#define SPR_ASTEROID_0 30   /* 30..31 16x16 */
#define SPR_POD 32          /* 16x16 */
#define SPR_CORE_CLOSED 33  /* 16x16 */
#define SPR_CORE_OPEN 34    /* 16x16 */
#define SPR_EXPL_0 35       /* 35..38 16x16 */
#define SPR_SHOT_PLAYER 39  /* 2x6 */
#define SPR_SHOT_ENEMY 40   /* 4x4 */
#define SPR_MISSILE_0 41    /* 41..42 6x8 */
#define SPR_ICON_SHIP 43    /* 8x8 */
#define SPR_ICON_BASE 44    /* 8x8 */
#define SPR_POD_HIT 45      /* 16x16 */
#define SPR_BIGEXPL_0 46    /* 46..49 32x32 */
#define SPR_COUNT 50
extern const u8 spr_width[SPR_COUNT];   /* pixel width per id (build/assets.s) */
extern const u8 spr_height[SPR_COUNT];

/* ---- display list (main RAM, filled by C, read by video.s) ---- */
#define DL_MAX 96
struct DlItem {
    u8 id;      /* SPR_* */
    s16 x;      /* playfield pixel x of the sprite's left edge (may be off screen) */
    s16 y;      /* playfield pixel y of the top row (may be off screen) */
    u8 pad;
};
extern struct DlItem dl_items[DL_MAX];
extern u8 dl_count;

#define STAR_MAX 48
extern u8 star_x[STAR_MAX];
extern u8 star_y[STAR_MAX];
extern u8 star_color[STAR_MAX];
extern u8 star_count;
extern u16 video_frame_writes;

/* ---- video.s ---- */
void video_init(void);
void video_shutdown(void);
void video_wait_vbl(void);
u16  video_speed_probe(void);
void video_render(void);
void video_clear_playfield(void);
void video_clear_all(void);
void __fastcall__ video_set_panel_color(u8 color);      /* color used by the next panel_text/fill/dot */
void panel_text(u8 px, u8 py, u8 color, const char *s);
void panel_text_small(u8 px, u8 py, u8 color, const char *s);
void panel_fill(u8 px, u8 py, u8 wbytes, u8 h, u8 color);
void panel_dot(u8 px, u8 py, u8 color);
void panel_sprite(u8 px, u8 py, u8 id);
void field_text(u8 x, u8 y, u8 color, const char *s);
void field_text_big(u8 x, u8 y, u8 color, const char *s);

/* ---- sound.c / sound_io.s ---- */
#define MUSIC_NONE 0
#define MUSIC_TITLE 1
#define MUSIC_BLASTOFF 2
#define MUSIC_AMBIENT 3
#define MUSIC_ROUND_CLEAR 4
#define MUSIC_DEATH 5
#define MUSIC_GAME_OVER 6

#define SFX_NONE 0
#define SFX_SHOT 1
#define SFX_HIT 2
#define SFX_EXPLODE 3
#define SFX_POD 4
#define SFX_BASE 5
#define SFX_MINE 6
#define SFX_PLAYER_DIE 7
#define SFX_ALERT 8
#define SFX_SPY 9
#define SFX_EXTRA_LIFE 10
#define SFX_MISSILE 11

#define SAY_NONE 0xFF
#define SAY_BLAST_OFF 0
#define SAY_ALERT 1
#define SAY_SPY 2
#define SAY_RED 3
#define SAY_BATTLE 4
#define SAY_GAME_OVER 5

void sound_init(void);
void sound_update(void);
void __fastcall__ sound_music(u8 track);
void __fastcall__ sound_tempo(u8 level);
void __fastcall__ sound_sfx(u8 id);
void __fastcall__ speech_say(u8 phrase);
u8   speech_busy(void);
extern u8 sound_current_sfx;     /* mailbox */
extern u8 sound_current_track;   /* mailbox */
extern u8 speech_current;        /* mailbox, SAY_NONE when idle */

/* ---- input.s ---- */
#define IN_UP    0x01
#define IN_DOWN  0x02
#define IN_LEFT  0x04
#define IN_RIGHT 0x08
#define IN_FIRE  0x10
#define IN_START 0x20
#define IN_PAUSE 0x40
#define IN_QUIT  0x80
u8 input_keys(void);
void input_joy_calibrate(void);
u8 input_joy(void);

/* ---- ramworks_probe.s (copied from Invasion) ---- */
u8 __fastcall__ ramworks_probe(u8 bank);

/* ---- game states / events (mailbox) ---- */
#define ST_BOOT 0
#define ST_TITLE 1
#define ST_PLAY 2
#define ST_DYING 3
#define ST_GAME_OVER 4
#define ST_ROUND_CLEAR 5
#define ST_PAUSED 6

#define EV_NONE 0
#define EV_ROUND_START 1
#define EV_FORMATION 2
#define EV_SPY 3
#define EV_CONDITION 4
#define EV_BASE_DESTROYED 5
#define EV_PLAYER_DIED 6
#define EV_ROUND_CLEAR 7
#define EV_GAME_OVER 8
#define EV_EXTRA_LIFE 9

struct Mailbox {
    u8 magic[4];          /* 'A','1','3','B' */
    u8 state;             /* 4 */
    u8 frame_lo;          /* 5 */
    u8 frame_hi;          /* 6 */
    u32 score;            /* 7..10 */
    u8 round;             /* 11 */
    u8 lives;             /* 12 */
    u8 condition;         /* 13 */
    u16 player_x;         /* 14..15 */
    u16 player_y;         /* 16..17 */
    u8 heading;           /* 18 */
    u8 bases_left;        /* 19 */
    u8 enemies_alive;     /* 20 */
    u8 dl_count;          /* 21 */
    u16 frame_writes;     /* 22..23 */
    u16 max_frame_writes; /* 24..25 */
    u8 ramworks_banks;    /* 26 */
    u16 speed_probe;      /* 27..28 */
    u8 sfx_now;           /* 29 */
    u8 music_track;       /* 30 */
    u8 speech_phrase;     /* 31 */
    u8 input_mask;        /* 32 */
    u8 formation_active;  /* 33 */
    u8 spy_active;        /* 34 */
    u8 last_event;        /* 35 */
    u16 dropped_frames;   /* 36..37 */
    u8 star_count;        /* 38 */
    u8 reserved0;         /* 39 */
    u8 reserved1;         /* 40 */
};
#define MAILBOX ((volatile struct Mailbox*)0x0300)

#endif
