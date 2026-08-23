/*
 * Appletini Invasion -- an original fixed-shooter showcase for an enhanced
 * Apple //e with Appletini acceleration, DHGR interlace, 8 MB RamWorks,
 * vertical parallax, continuous Mockingboard AY music/effects, and SSI-263
 * speech.
 */

typedef unsigned char u8;
typedef signed char s8;
typedef unsigned int u16;

#define REG8(a) (*(volatile u8*)(a))

#define KBD        0xC000
#define KBDSTRB    0xC010
#define GAME_BUTTON0 0xC061
#define GAME_BUTTON1 0xC062
#define STORE80OFF 0xC000
#define RAMRDOFF   0xC002
#define RAMRDON    0xC003
#define RAMWRTOFF  0xC004
#define RAMWRTON   0xC005
#define COL80OFF   0xC00C
#define COL80ON    0xC00D
#define RDVBLBAR   0xC019
#define NEWVIDEO   0xC029
#define TEXTOFF    0xC050
#define MIXEDOFF   0xC052
#define PAGE1      0xC054
#define HIRESON    0xC057
#define DHGRON     0xC05E
#define DHGROFF    0xC05F
#define IOUDISON   0xC07E
#define RAMWORKS   0xC073
#define TWSPEED    0xC074

/* SSI writes at $C440-$C447 also mirror into the low-half VIA. Keep AY sound
 * on the independent high-half VIA so speech cannot pulse its control bus. */
#define VIA_ORB    0xC480
#define VIA_ORA    0xC48F
#define VIA_DDRB   0xC482
#define VIA_DDRA   0xC483
#define VIA_PCR    0xC48C
#define VIA_IFR    0xC48D
#define VIA_IER    0xC48E
#define SSI_DUR    0xC440
#define SSI_INF    0xC441
#define SSI_RATE   0xC442
#define SSI_CTL    0xC443
#define SSI_FILT   0xC444

#define PAGE_A     0x2000
#define PAGE_B     0x4000
#define VIDEO_ROWS 192
#define PLAYFIELD_TOP 20
#define PLAYFIELD_BOTTOM 180
#define PARALLAX_BOTTOM 178
#define PARALLAX_SOURCE_ROWS 384
#define PARALLAX_WOVEN_TOP (PLAYFIELD_TOP * 2)
#define PARALLAX_WOVEN_BOTTOM (PARALLAX_BOTTOM * 2)
#define PARALLAX_HEIGHT (PARALLAX_WOVEN_BOTTOM - PARALLAX_WOVEN_TOP)
#define PARALLAX_DENOMINATOR 20
#define PARALLAX_MODULUS (PARALLAX_SOURCE_ROWS * PARALLAX_DENOMINATOR)
#define PARALLAX_DEEP_SPEED 5
#define PARALLAX_NEBULA_SPEED 12
#define PARALLAX_ASTEROID_SPEED 28
#define PARALLAX_STATE_QUIET 3
#define PARALLAX_SLICE_ROWS 106
#define PARALLAX_SECOND_WOVEN (PARALLAX_WOVEN_TOP + PARALLAX_SLICE_ROWS)
#define PARALLAX_THIRD_WOVEN (PARALLAX_SECOND_WOVEN + PARALLAX_SLICE_ROWS)
#define PARALLAX_LAST_ROWS (PARALLAX_WOVEN_BOTTOM - PARALLAX_THIRD_WOVEN)
#define REPLAY_FIRST_BANK 6
#define VIDEO7_COLOR 0x80
#define FIELD_BYTES 4
#define ENEMY_COUNT 24
#define PLAYER_BULLET_COUNT 8
#define AUTOFIRE_DELAY 5
#define MUSIC_STEP_COUNT 32
#define MUSIC_STEP_FRAMES 6

#define PARALLAX_DEEP_ROW_LO     0x0068
#define PARALLAX_DEEP_ROW_HI     0x0069
#define PARALLAX_NEBULA_ROW_LO   0x006A
#define PARALLAX_NEBULA_ROW_HI   0x006B
#define PARALLAX_ASTEROID_ROW_LO 0x006C
#define PARALLAX_ASTEROID_ROW_HI 0x006D
#define PARALLAX_DEST_ROW_LO     0x006E
#define PARALLAX_DEST_ROW_HI     0x006F
#define SPRITE_X_ZP          0x0020
#define SPRITE_Y_ZP          0x0021
#define SPRITE_HEIGHT_ZP     0x0022
#define SPRITE_PTR_LO_ZP     0x0023
#define SPRITE_PTR_HI_ZP     0x0024

#define KEY_LEFT   0x08
#define KEY_RIGHT  0x15
#define KEY_SPACE  0x20
#define HELD_NONE  0
#define HELD_LEFT  1
#define HELD_RIGHT 2
#define HELD_FIRE  3
#define HELD_BLOCKED 4

extern u8 __fastcall__ ramworks_probe(u8 bank);
extern void aux_clear_video(void);
extern void __fastcall__ aux_color_row(u16 address);
extern u8 __fastcall__ parallax_assets_load(void);
extern void __fastcall__ parallax_render_slice(u8 row_count);
extern void video_sprite_fast(void);

struct DebugMailbox {
    u8 magic[4];
    u8 video_mode;
    u8 banks;
    u8 frame_lo;
    u8 frame_hi;
    u8 score;
    u8 lives;
    u8 enemies;
    u8 player_x;
    u8 mhz;
    u8 audio_flags;
    u8 speech_phoneme;
    u8 game_state;
    u8 player_bullets;
    u8 replay_bank;
    u8 speech_completions;
    u8 shots_fired;
    u8 deep_phase_lo;
    u8 deep_phase_hi;
    u8 nebula_phase_lo;
    u8 nebula_phase_hi;
    u8 asteroid_phase_lo;
    u8 asteroid_phase_hi;
    u8 music_step;
    u8 music_loops;
    u8 music_tick;
    u8 ay_mixer;
    u8 effect_kind;
    u8 lead_note;
    u8 bass_note;
    u8 music_events;
    u8 parallax_commits;
};

#define MAILBOX ((volatile struct DebugMailbox*)0x0300)

static u16 hgr_line[VIDEO_ROWS];
static u8 enemy_alive[ENEMY_COUNT];
static u8 player_x;
static s8 player_velocity;
static u8 enemy_x;
static u8 enemy_y;
static u8 enemy_right;
static u8 enemies_left;
static u8 player_bullet_active[PLAYER_BULLET_COUNT];
static u8 player_bullet_x[PLAYER_BULLET_COUNT];
static u8 player_bullet_y[PLAYER_BULLET_COUNT];
static u8 held_action;
static u8 fire_held;
static u8 fire_pending;
static u8 fire_cooldown;
static u8 shots_fired;
static u8 enemy_bullet_active;
static u8 enemy_bullet_x;
static u8 enemy_bullet_y;
static u8 fire_column;
static u8 frame_lo;
static u8 frame_hi;
static u8 game_frame;
static u8 score;
static u8 lives;
static u8 animation;
static u8 hud_dirty;
static u8 sfx_timer;
static u8 sfx_kind;
static u8 replay_bank;
static u8 replay_slot;

struct ParallaxPhase {
    u16 row;
    u8 fraction;
    u16 displayed_row;
    u16 displayed_units;
    u16 target_row;
    u16 target_units;
};

static struct ParallaxPhase deep_phase;
static struct ParallaxPhase nebula_phase;
static struct ParallaxPhase asteroid_phase;
static u8 parallax_render_state;
static u8 parallax_commits;

static u8 ay_shadow[11];
static u8 ay_mixer_shadow;
static u8 music_step;
static u8 music_subtick;
static u8 music_loops;
static u8 music_events;
static u8 music_lead_note;
static u8 music_bass_note;

static const u8* speech_phrase;
static u8 speech_index;
static u8 speech_timer;
static u8 speech_active;

/* Each row is page-A aux/main followed by page-B aux/main. */
static const u8 sprite_player[] = {
    0x08,0x00,0x1C,0x00, 0x1C,0x00,0x3E,0x08,
    0x3E,0x08,0x7F,0x1C, 0x7F,0x1C,0x7F,0x3E,
    0x7F,0x3E,0x7F,0x7F, 0x3E,0x7F,0x3E,0x7F,
    0x22,0x7F,0x63,0x7F, 0x41,0x22,0x41,0x22
};
static const u8 sprite_enemy_a[] = {
    0x14,0x14,0x1C,0x1C, 0x08,0x08,0x3E,0x3E,
    0x3E,0x3E,0x7F,0x7F, 0x6B,0x6B,0x7F,0x7F,
    0x7F,0x7F,0x7F,0x7F, 0x55,0x55,0x55,0x55,
    0x14,0x14,0x36,0x36, 0x22,0x22,0x22,0x22
};
static const u8 sprite_enemy_b[] = {
    0x14,0x14,0x5D,0x5D, 0x49,0x49,0x7F,0x7F,
    0x3E,0x3E,0x7F,0x7F, 0x6B,0x6B,0x7F,0x7F,
    0x7F,0x7F,0x7F,0x7F, 0x55,0x55,0x77,0x77,
    0x22,0x22,0x63,0x63, 0x41,0x41,0x41,0x41
};
static const u8 sprite_shot[] = {
    0x08,0x00,0x1C,0x00, 0x1C,0x00,0x1C,0x00,
    0x08,0x00,0x1C,0x00, 0x1C,0x00,0x1C,0x00
};
static const u8 sprite_bomb[] = {
    0x22,0x00,0x36,0x00, 0x14,0x00,0x1C,0x00,
    0x08,0x00,0x1C,0x00, 0x14,0x00,0x14,0x00
};

/* 5x7 font: digits, then A-Z. */
static const u8 font[] = {
    0x0E,0x11,0x13,0x15,0x19,0x11,0x0E,
    0x04,0x0C,0x04,0x04,0x04,0x04,0x0E,
    0x0E,0x11,0x01,0x02,0x04,0x08,0x1F,
    0x1E,0x01,0x01,0x0E,0x01,0x01,0x1E,
    0x02,0x06,0x0A,0x12,0x1F,0x02,0x02,
    0x1F,0x10,0x10,0x1E,0x01,0x01,0x1E,
    0x0E,0x10,0x10,0x1E,0x11,0x11,0x0E,
    0x1F,0x01,0x02,0x04,0x08,0x08,0x08,
    0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E,
    0x0E,0x11,0x11,0x0F,0x01,0x01,0x0E,
    0x0E,0x11,0x11,0x1F,0x11,0x11,0x11,
    0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E,
    0x0E,0x11,0x10,0x10,0x10,0x11,0x0E,
    0x1E,0x11,0x11,0x11,0x11,0x11,0x1E,
    0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F,
    0x1F,0x10,0x10,0x1E,0x10,0x10,0x10,
    0x0E,0x11,0x10,0x17,0x11,0x11,0x0F,
    0x11,0x11,0x11,0x1F,0x11,0x11,0x11,
    0x0E,0x04,0x04,0x04,0x04,0x04,0x0E,
    0x07,0x02,0x02,0x02,0x12,0x12,0x0C,
    0x11,0x12,0x14,0x18,0x14,0x12,0x11,
    0x10,0x10,0x10,0x10,0x10,0x10,0x1F,
    0x11,0x1B,0x15,0x15,0x11,0x11,0x11,
    0x11,0x19,0x15,0x13,0x11,0x11,0x11,
    0x0E,0x11,0x11,0x11,0x11,0x11,0x0E,
    0x1E,0x11,0x11,0x1E,0x10,0x10,0x10,
    0x0E,0x11,0x11,0x11,0x15,0x12,0x0D,
    0x1E,0x11,0x11,0x1E,0x14,0x12,0x11,
    0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E,
    0x1F,0x04,0x04,0x04,0x04,0x04,0x04,
    0x11,0x11,0x11,0x11,0x11,0x11,0x0E,
    0x11,0x11,0x11,0x11,0x11,0x0A,0x04,
    0x11,0x11,0x11,0x15,0x15,0x15,0x0A,
    0x11,0x11,0x0A,0x04,0x0A,0x11,0x11,
    0x11,0x11,0x0A,0x04,0x04,0x04,0x04,
    0x1F,0x01,0x02,0x04,0x08,0x10,0x1F
};

/* SSI-263 duration/phoneme streams, FF terminated. */
static const u8 phrase_boot[] = {
    0x08,0x27,0x20,0x0A,0x28,0x01,0x38,0x01,0x00,
    0x25,0x01,0x33,0x0A,0x38,0x30,0x00,0x11,0x38,0x20,0x05,0x38,0xFF
};
static const u8 phrase_wave[] = {0x23,0x05,0x33,0x00,0x29,0x20,0x01,0x1C,0xFF};
static const u8 phrase_over[] = {0x29,0x05,0x37,0x00,0x11,0x33,0x1C,0xFF};

/* AY periods for E2 through B5 at the Mockingboard's nominal 1.0227 MHz
 * clock. Entry zero is a rest. The score below is an original 32-step loop. */
static const u8 note_period_lo[] = {
    0x00, 0x08,0xDC,0x8C,0x45,0x06,0xE9,0xB3,0x84,
    0x6E,0x46,0x23,0x03,0xF4,0xDA,0xC2,0xB7,0xA3,
    0x91,0x81,0x7A,0x6D,0x61,0x5C,0x52,0x49,0x41
};
static const u8 note_period_hi[] = {
    0x00, 0x03,0x02,0x02,0x02,0x02,0x01,0x01,0x01,
    0x01,0x01,0x01,0x01,0x00,0x00,0x00,0x00,0x00,
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00
};
static const u8 music_lead[MUSIC_STEP_COUNT] = {
    18,20,22,20, 18,20,23,20, 17,20,22,20, 19,21,24,21,
    18,20,22,25, 24,22,21,20, 19,21,24,26, 25,24,22,20
};
static const u8 music_bass[MUSIC_STEP_COUNT] = {
     4, 4, 8, 8,  2, 2, 6, 6,  6, 6,10,10,  3, 3, 7, 7,
     4, 4, 8, 8,  2, 4, 6, 8,  3, 5, 7,10,  1, 5, 8,12
};

static void wait_vbl(void)
{
    while (REG8(RDVBLBAR) & 0x80) { }
    while (!(REG8(RDVBLBAR) & 0x80)) { }
}

static void build_line_table(void)
{
    u16 y;
    for (y = 0; y < VIDEO_ROWS; ++y) {
        hgr_line[y] = PAGE_A + ((y & 7) << 10)
                    + ((y & 0x38) << 4) + ((y >> 6) * 0x28);
    }
}

static void video_select(void)
{
    REG8(STORE80OFF) = 0;
    REG8(RAMRDOFF) = 0;
    REG8(RAMWRTOFF) = 0;
    REG8(RAMWORKS) = 0;
    REG8(NEWVIDEO) = 1;
    REG8(TEXTOFF) = 0;
    REG8(MIXEDOFF) = 0;
    REG8(PAGE1) = 0;
    REG8(HIRESON) = 0;
    REG8(IOUDISON) = 0;
    /* Commit Video-7 state 10 (MIX): bit 7 clear selects monochrome spans,
     * while bit 7 set preserves color graphics. Each C05F rising edge clocks
     * !80COL, first into bit 1 and then bit 0. Restore 80COL before the final
     * C05E so the selector commits with DHGR still enabled. */
    REG8(COL80OFF) = 0;
    REG8(DHGRON) = 0;
    REG8(DHGROFF) = 0;
    REG8(COL80ON) = 0;
    REG8(DHGRON) = 0;
    REG8(DHGROFF) = 0;
    REG8(COL80ON) = 0;
    REG8(DHGRON) = 0;
}

static void video_clear(void)
{
    volatile u8* p;
    REG8(RAMWORKS) = 0;
    REG8(RAMWRTOFF) = 0;
    for (p = (volatile u8*)PAGE_A; p < (volatile u8*)0x6000; ++p) *p = 0;
    aux_clear_video();
}

static void video_color_playfield(void)
{
    u8 y;
    u8 x;
    u16 address;

    /* Video-7 MIX uses the high bits of the interleaved DHGR bytes as
     * 8+8+8+4-dot monochrome/color selectors. Color the complete gameplay
     * rows in every field and plane so selector spans remain aligned even
     * when a sprite moves across an odd byte boundary. Text rows retain the
     * zeroes installed by video_clear and therefore render monochrome. */
    REG8(RAMWORKS) = 0;
    REG8(RAMWRTOFF) = 0;
    for (y = PLAYFIELD_TOP; y < PLAYFIELD_BOTTOM; ++y) {
        address = hgr_line[y];
        for (x = 0; x < 40; ++x) {
            REG8(address + x) = VIDEO7_COLOR;
            REG8(address + 0x2000 + x) = VIDEO7_COLOR;
        }
        aux_color_row(address);
    }
    REG8(RAMWRTOFF) = 0;
}

static void video_begin_dhgri(void)
{
    REG8(RAMWORKS) = 0;
    REG8(RAMWRTOFF) = 0;
    REG8(0x4078) = 0xC1;
    REG8(0x4079) = 0xB2;
    REG8(0x407A) = 0xCC;
    REG8(0x407B) = 0xE9;
    REG8(0x087C) = 0;
    REG8(0x407C) = 0xFF;
}

static void video_commit_dhgri(void)
{
    REG8(RAMWRTOFF) = 0;
    REG8(0x407C) = 1;
}

static void video_plane_write(u16 address, u8 value, u8 aux)
{
    REG8(aux ? RAMWRTON : RAMWRTOFF) = 0;
    REG8(address) = value;
    REG8(RAMWRTOFF) = 0;
}

static u8 hgr_glyph_bits(u8 value)
{
    /* Apple II graphics bytes put bit 0 at the left edge. The font source is
     * written in the conventional bit-4-at-left notation. */
    return (u8)(((value & 0x01) << 4)
              | ((value & 0x02) << 2)
              |  (value & 0x04)
              | ((value & 0x08) >> 2)
              | ((value & 0x10) >> 4));
}

static void video_half_glyph(u8 half_x, u8 y, u8 glyph)
{
    u8 row;
    u8 bits;
    u16 address;
    u8 aux;
    aux = (u8)((half_x & 1) == 0);
    half_x >>= 1;
    for (row = 0; row < 7; ++row) {
        address = hgr_line[y + row] + half_x;
        bits = glyph == 0xFF ? 0 : hgr_glyph_bits(font[glyph * 7 + row]);
        video_plane_write(address, bits, aux);
        video_plane_write(address + 0x2000, bits, aux);
    }
    REG8(RAMWRTOFF) = 0;
}

static u8 glyph_for(u8 c)
{
    if (c >= '0' && c <= '9') return (u8)(c - '0');
    if (c >= 'A' && c <= 'Z') return (u8)(10 + c - 'A');
    return 0xFF;
}

static void video_text(u8 half_x, u8 y, const char* text)
{
    u8 glyph;
    while (*text && half_x < 80) {
        glyph = glyph_for((u8)*text++);
        if (glyph == 0xFF) {
            /* punctuation is deliberately geometric and tiny */
            if (text[-1] == '.') {
                static const u8 dot[7] = {0,0,0,0,0,4,4};
                u8 row;
                u16 address;
                u8 aux;
                aux = (u8)((half_x & 1) == 0);
                for (row = 0; row < 7; ++row) {
                    address = hgr_line[y + row] + (half_x >> 1);
                    video_plane_write(address, dot[row], aux);
                    video_plane_write(address + 0x2000, dot[row], aux);
                }
            } else {
                video_half_glyph(half_x, y, 0xFF);
            }
        } else {
            video_half_glyph(half_x, y, glyph);
        }
        ++half_x;
    }
    REG8(RAMWRTOFF) = 0;
}

static void video_border(void)
{
    u8 x;
    u16 address;
    address = hgr_line[178];
    for (x = 0; x < 40; ++x) {
        video_plane_write(address + x, 0xD5, 1);
        video_plane_write(address + x, 0xAA, 0);
        video_plane_write(address + 0x2000 + x, 0xD5, 1);
        video_plane_write(address + 0x2000 + x, 0xAA, 0);
    }
    REG8(RAMWRTOFF) = 0;
}

static void parallax_phase_reset(struct ParallaxPhase* phase)
{
    phase->row = 0;
    phase->fraction = 0;
    phase->displayed_row = 0;
    phase->displayed_units = 0;
    phase->target_row = 0;
    phase->target_units = 0;
}

static void parallax_phase_advance(struct ParallaxPhase* phase, u8 amount)
{
    u8 whole;
    u8 fraction;
    fraction = (u8)(phase->fraction + amount);
    whole = 0;
    while (fraction >= PARALLAX_DENOMINATOR) {
        fraction = (u8)(fraction - PARALLAX_DENOMINATOR);
        ++whole;
    }
    phase->fraction = fraction;
    phase->row = (u16)(phase->row + whole);
    if (phase->row >= PARALLAX_SOURCE_ROWS) {
        phase->row = (u16)(phase->row - PARALLAX_SOURCE_ROWS);
    }
}

static void parallax_init(void)
{
    parallax_phase_reset(&deep_phase);
    parallax_phase_reset(&nebula_phase);
    parallax_phase_reset(&asteroid_phase);
    parallax_render_state = PARALLAX_STATE_QUIET;
    parallax_commits = 0;
}

static void parallax_tick(void)
{
    parallax_phase_advance(&deep_phase, PARALLAX_DEEP_SPEED);
    parallax_phase_advance(&nebula_phase, PARALLAX_NEBULA_SPEED);
    parallax_phase_advance(&asteroid_phase, PARALLAX_ASTEROID_SPEED);
}

static u16 parallax_phase_units(const struct ParallaxPhase* phase)
{
    return (u16)(phase->row * PARALLAX_DENOMINATOR + phase->fraction);
}

static void parallax_capture_target(void)
{
    deep_phase.target_row = deep_phase.row;
    nebula_phase.target_row = nebula_phase.row;
    asteroid_phase.target_row = asteroid_phase.row;
    deep_phase.target_units = parallax_phase_units(&deep_phase);
    nebula_phase.target_units = parallax_phase_units(&nebula_phase);
    asteroid_phase.target_units = parallax_phase_units(&asteroid_phase);
}

static void parallax_promote_target(void)
{
    deep_phase.displayed_row = deep_phase.target_row;
    nebula_phase.displayed_row = nebula_phase.target_row;
    asteroid_phase.displayed_row = asteroid_phase.target_row;
    deep_phase.displayed_units = deep_phase.target_units;
    nebula_phase.displayed_units = nebula_phase.target_units;
    asteroid_phase.displayed_units = asteroid_phase.target_units;
}

static u16 parallax_source_row(u16 woven_row, u16 offset)
{
    woven_row = (u16)(woven_row + PARALLAX_SOURCE_ROWS - offset);
    if (woven_row >= PARALLAX_SOURCE_ROWS) {
        woven_row = (u16)(woven_row - PARALLAX_SOURCE_ROWS);
    }
    return woven_row;
}

static void parallax_render_rows(u16 woven_row, u8 row_count)
{
    u16 source_row;

    source_row = parallax_source_row(woven_row, deep_phase.target_row);
    REG8(PARALLAX_DEEP_ROW_LO) = (u8)source_row;
    REG8(PARALLAX_DEEP_ROW_HI) = (u8)(source_row >> 8);
    source_row = parallax_source_row(woven_row, nebula_phase.target_row);
    REG8(PARALLAX_NEBULA_ROW_LO) = (u8)source_row;
    REG8(PARALLAX_NEBULA_ROW_HI) = (u8)(source_row >> 8);
    source_row = parallax_source_row(woven_row, asteroid_phase.target_row);
    REG8(PARALLAX_ASTEROID_ROW_LO) = (u8)source_row;
    REG8(PARALLAX_ASTEROID_ROW_HI) = (u8)(source_row >> 8);
    REG8(PARALLAX_DEST_ROW_LO) = (u8)woven_row;
    REG8(PARALLAX_DEST_ROW_HI) = (u8)(woven_row >> 8);
    parallax_render_slice(row_count);
    REG8(RAMWORKS) = 0;
    REG8(RAMRDOFF) = 0;
    REG8(RAMWRTOFF) = 0;
}

static void video_sprite(u8 x, u8 y, const u8* sprite, u8 height)
{
    REG8(SPRITE_X_ZP) = x;
    REG8(SPRITE_Y_ZP) = y;
    REG8(SPRITE_HEIGHT_ZP) = height;
    REG8(SPRITE_PTR_LO_ZP) = (u8)(u16)sprite;
    REG8(SPRITE_PTR_HI_ZP) = (u8)((u16)sprite >> 8);
    video_sprite_fast();
    REG8(RAMWRTOFF) = 0;
}

static void ay_write(u8 reg, u8 value)
{
    REG8(VIA_ORA) = reg;
    REG8(VIA_ORB) = 7;
    REG8(VIA_ORB) = 4;
    REG8(VIA_ORA) = value;
    REG8(VIA_ORB) = 6;
    REG8(VIA_ORB) = 4;
}

static void ay_write_cached(u8 reg, u8 value)
{
    if (ay_shadow[reg] == value) return;
    ay_shadow[reg] = value;
    ay_write(reg, value);
}

static void ay_note(u8 channel, u8 note, u8 volume)
{
    u8 reg;
    reg = (u8)(channel << 1);
    if (!note) {
        ay_write_cached((u8)(8 + channel), 0);
        return;
    }
    ay_write_cached(reg, note_period_lo[note]);
    ay_write_cached((u8)(reg + 1), note_period_hi[note]);
    ay_write_cached((u8)(8 + channel), volume);
}

static void music_begin(void)
{
    music_step = 0;
    music_subtick = 0;
    music_loops = 0;
    music_events = 1;
    music_lead_note = music_lead[0];
    music_bass_note = music_bass[0];
}

static void audio_render(void)
{
    u8 lead_volume;
    u8 bass_volume;
    u8 mixer;

    /* The lead gates briefly at the end of each tracker row. Speech ducks
     * both voices but never pauses the score. */
    lead_volume = (u8)(speech_active ? 7 : 10);
    bass_volume = (u8)(speech_active ? 5 : 7);
    if (music_subtick == MUSIC_STEP_FRAMES - 1) lead_volume = 0;
    ay_note(0, music_lead_note, lead_volume);
    ay_note(1, music_bass_note, bass_volume);

    /* A and B are permanently owned by music. Channel C belongs to effects,
     * so autofire and explosions cannot interrupt either musical voice. */
    mixer = 0x3C;
    if (sfx_timer && sfx_kind == 1) {
        ay_write_cached(4, (u8)(0x38 + ((7 - sfx_timer) << 3)));
        ay_write_cached(5, 0);
        ay_write_cached(10, (u8)(sfx_timer + 8));
        mixer = 0x38;
    } else if (sfx_timer && sfx_kind == 2) {
        ay_write_cached(6, (u8)(3 + (12 - sfx_timer)));
        ay_write_cached(10, (u8)(sfx_timer + 2));
        mixer = 0x1C;
    } else {
        ay_write_cached(4, 0);
        ay_write_cached(5, 0);
        ay_write_cached(6, 0);
        ay_write_cached(10, 0);
    }
    ay_write_cached(7, mixer);
    ay_mixer_shadow = mixer;
}

static void audio_init(void)
{
    u8 reg;
    /* Poll CA1 completions without enabling 6502 IRQs; ProDOS is not allowed
     * to leave this private game VIA in an incompatible state. */
    REG8(VIA_IER) = 0x7F;
    REG8(VIA_PCR) = 0;
    REG8(VIA_IFR) = 0x7F;

    /* Program speech while the mirrored low-half VIA pins are still inputs. */
    REG8(SSI_CTL) = 0x80;
    REG8(SSI_DUR) = 0xC0;
    REG8(SSI_INF) = 0x40;
    REG8(SSI_RATE) = 0xA8;
    REG8(SSI_CTL) = 0x5A;
    REG8(SSI_FILT) = 0xE8;

    REG8(VIA_DDRA) = 0xFF;
    REG8(VIA_DDRB) = 0x07;
    REG8(VIA_ORB) = 0;
    REG8(VIA_ORB) = 4;
    for (reg = 0; reg < 11; ++reg) ay_shadow[reg] = 0xFF;
    ay_write_cached(7, 0x3F);
    ay_write_cached(8, 0);
    ay_write_cached(9, 0);
    ay_write_cached(10, 0);
    sfx_kind = 0;
    sfx_timer = 0;
    music_begin();
    audio_render();
}

static void sfx_fire(void)
{
    /* An explosion owns the effects channel until its noise tail finishes. */
    if (sfx_kind == 2 && sfx_timer) return;
    sfx_kind = 1;
    sfx_timer = 7;
}

static void sfx_explosion(void)
{
    sfx_kind = 2;
    sfx_timer = 12;
}

static void audio_tick(void)
{
    if (!sfx_timer) sfx_kind = 0;
    ++music_subtick;
    if (music_subtick == MUSIC_STEP_FRAMES) {
        music_subtick = 0;
        ++music_step;
        ++music_events;
        if (music_step == MUSIC_STEP_COUNT) {
            music_step = 0;
            ++music_loops;
        }
        music_lead_note = music_lead[music_step];
        music_bass_note = music_bass[music_step];
    }
    audio_render();
    if (sfx_timer) --sfx_timer;
}

static void speech_start(const u8* phrase)
{
    speech_phrase = phrase;
    speech_index = 0;
    speech_timer = 0;
    speech_active = 1;
    REG8(VIA_IFR) = 0x02;
}

static void speech_tick(void)
{
    u8 phoneme;
    if (!speech_active) return;
    if (speech_index) {
        if (REG8(VIA_IFR) & 0x02) {
            REG8(VIA_IFR) = 0x02;
            ++MAILBOX->speech_completions;
        } else if (speech_timer) {
            --speech_timer;
            return;
        }
    }
    phoneme = speech_phrase[speech_index++];
    if (phoneme == 0xFF) {
        speech_active = 0;
        MAILBOX->speech_phoneme = 0xFF;
        return;
    }
    REG8(SSI_DUR) = phoneme;
    MAILBOX->speech_phoneme = phoneme;
    /* CA1 normally advances the stream at the real phoneme boundary. The
     * timeout keeps speech moving on partial clones without truncating the
     * slowest RATE-$A profile. */
    speech_timer = 12;
}

static u8 ramworks_init(void)
{
    u8 bank;
    u8 found;
    found = 1;
    for (bank = 1; bank < 128; ++bank) {
        REG8(RAMWORKS) = bank;
        REG8(RAMWRTON) = 0;
        REG8(0x1000) = bank;
        REG8(0x1001) = (u8)~bank;
        REG8(0x1002) = 'R';
        REG8(0x1003) = 'W';
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

static u8 player_bullet_count(void)
{
    u8 bullet;
    u8 count;
    count = 0;
    for (bullet = 0; bullet < PLAYER_BULLET_COUNT; ++bullet) {
        if (player_bullet_active[bullet]) ++count;
    }
    return count;
}

static void replay_record(void)
{
    u8 bullets;
    u8 offset;
    volatile u8* record;
    bullets = player_bullet_count();
    offset = (u8)(replay_slot << 3);
    record = (volatile u8*)(0x1100 + offset);
    REG8(RAMWORKS) = replay_bank;
    REG8(RAMWRTON) = 0;
    record[0] = frame_lo;
    record[1] = player_x;
    record[2] = enemy_x;
    record[3] = enemy_y;
    record[4] = bullets;
    record[5] = enemy_bullet_y;
    record[6] = enemies_left;
    record[7] = score;
    REG8(RAMWRTOFF) = 0;
    REG8(RAMWORKS) = 0;
    ++replay_slot;
    if (replay_slot == 32) {
        replay_slot = 0;
        ++replay_bank;
        if (replay_bank == 128) replay_bank = REPLAY_FIRST_BANK;
    }
    MAILBOX->replay_bank = replay_bank;
}

static void formation_reset(void)
{
    u8 i;
    for (i = 0; i < ENEMY_COUNT; ++i) enemy_alive[i] = 1;
    for (i = 0; i < PLAYER_BULLET_COUNT; ++i) player_bullet_active[i] = 0;
    enemies_left = ENEMY_COUNT;
    enemy_x = 7;
    enemy_y = 32;
    enemy_right = 1;
    enemy_bullet_active = 0;
    animation = 0;
    hud_dirty = 1;
}

static void game_reset(void)
{
    score = 0;
    lives = 3;
    player_x = 20;
    player_velocity = 0;
    held_action = HELD_NONE;
    fire_held = 0;
    fire_pending = 0;
    fire_cooldown = 0;
    shots_fired = 0;
    formation_reset();
}

static void draw_invaders(void)
{
    u8 row;
    u8 col;
    u8 index;
    u8 x;
    u8 y;
    const u8* sprite;
    sprite = animation ? sprite_enemy_b : sprite_enemy_a;
    index = 0;
    y = enemy_y;
    for (row = 0; row < 4; ++row) {
        x = enemy_x;
        for (col = 0; col < 6; ++col) {
            if (enemy_alive[index]) video_sprite(x, y, sprite, 8);
            ++index;
            x = (u8)(x + 5);
        }
        y = (u8)(y + 15);
    }
}

static void draw_dynamic(void)
{
    u8 bullet;
    draw_invaders();
    video_sprite(player_x, 164, sprite_player, 8);
    for (bullet = 0; bullet < PLAYER_BULLET_COUNT; ++bullet) {
        if (player_bullet_active[bullet]) {
            video_sprite(player_bullet_x[bullet], player_bullet_y[bullet], sprite_shot, 4);
        }
    }
    if (enemy_bullet_active) video_sprite(enemy_bullet_x, enemy_bullet_y, sprite_bomb, 4);
}

static void draw_hud(void)
{
    char value[3];
    static const char hex[] = "0123456789ABCDEF";
    value[0] = hex[score >> 4];
    value[1] = hex[score & 15];
    value[2] = 0;
    video_text(1, 2, "SCORE");
    video_text(7, 2, value);
    value[0] = (char)('0' + lives);
    value[1] = 0;
    video_text(68, 2, "LIVES");
    video_text(74, 2, value);
    hud_dirty = 0;
}

static u8 player_fire(void)
{
    u8 bullet;
    for (bullet = 0; bullet < PLAYER_BULLET_COUNT; ++bullet) {
        if (!player_bullet_active[bullet]) {
            player_bullet_active[bullet] = 1;
            player_bullet_x[bullet] = player_x;
            player_bullet_y[bullet] = 158;
            ++shots_fired;
            sfx_fire();
            return 1;
        }
    }
    return 0;
}

static void input_tick(void)
{
    u8 key;
    u8 any_key_down;
    u8 independent_fire;
    key = REG8(KBD);
    if (key & 0x80) {
        key &= 0x7F;
        if (key == KEY_SPACE) {
            /* Queue one shot even if the key was released before this game
             * tick. C010's //e AKD bit keeps subsequent shots flowing while
             * Space remains physically held. */
            if (held_action == HELD_NONE) {
                fire_pending = 1;
                held_action = HELD_FIRE;
                fire_held = 1;
            } else if (held_action == HELD_FIRE) {
                fire_held = 1;
            } else {
                if (held_action != HELD_BLOCKED) fire_pending = 1;
                held_action = HELD_BLOCKED;
                fire_held = 0;
            }
            player_velocity = 0;
        } else if (key == KEY_LEFT || key == 'A' || key == 'a'
                   || key == 'J' || key == 'j') {
            fire_held = 0;
            if (held_action == HELD_NONE || held_action == HELD_LEFT) {
                held_action = HELD_LEFT;
                player_velocity = -1;
            } else {
                held_action = HELD_BLOCKED;
                player_velocity = 0;
            }
        } else if (key == KEY_RIGHT || key == 'D' || key == 'd'
                   || key == 'L' || key == 'l') {
            fire_held = 0;
            if (held_action == HELD_NONE || held_action == HELD_RIGHT) {
                held_action = HELD_RIGHT;
                player_velocity = 1;
            } else {
                held_action = HELD_BLOCKED;
                player_velocity = 0;
            }
        } else if (key == 'R' || key == 'r') {
            game_reset();
        } else {
            held_action = HELD_NONE;
            fire_held = 0;
            player_velocity = 0;
        }
    }

    /* On an Apple //e, reading C010 clears the strobe and returns AKD in bit
     * 7. Tie both movement and autofire to that physical key level so an
     * arrow release stops the ship without waiting for another keypress. The
     * keyboard exposes only one latched key, so different overlapping action
     * keys are blocked until every key is released instead of risking stuck
     * movement. The independent Apple/game buttons below support firing while
     * an arrow remains held. */
    any_key_down = REG8(KBDSTRB) & 0x80;
    if (!any_key_down) {
        held_action = HELD_NONE;
        fire_held = 0;
        player_velocity = 0;
    } else if (held_action == HELD_FIRE) {
        fire_held = 1;
    }
    independent_fire = (REG8(GAME_BUTTON0) | REG8(GAME_BUTTON1)) & 0x80;
    if (fire_cooldown) {
        --fire_cooldown;
    } else if ((fire_held || fire_pending || independent_fire) && player_fire()) {
        fire_pending = 0;
        fire_cooldown = AUTOFIRE_DELAY;
    }
}

static void player_bullet_tick(void)
{
    u8 bullet;
    u8 row;
    u8 col;
    u8 index;
    u8 x;
    u8 y;
    u8 hit;
    for (bullet = 0; bullet < PLAYER_BULLET_COUNT; ++bullet) {
        if (!player_bullet_active[bullet]) continue;
        if (player_bullet_y[bullet] < 24) {
            player_bullet_active[bullet] = 0;
            continue;
        }
        player_bullet_y[bullet] = (u8)(player_bullet_y[bullet] - 3);
        index = 0;
        y = enemy_y;
        hit = 0;
        for (row = 0; row < 4 && !hit; ++row) {
            x = enemy_x;
            for (col = 0; col < 6; ++col) {
                if (enemy_alive[index] && player_bullet_x[bullet] == x
                    && player_bullet_y[bullet] >= y
                    && player_bullet_y[bullet] < y + 9) {
                    enemy_alive[index] = 0;
                    player_bullet_active[bullet] = 0;
                    --enemies_left;
                    score = (u8)(score + 3 + row);
                    hud_dirty = 1;
                    sfx_explosion();
                    hit = 1;
                    break;
                }
                ++index;
                x = (u8)(x + 5);
            }
            y = (u8)(y + 15);
        }
    }
}

static void enemy_bullet_tick(void)
{
    u8 delta;
    if (!enemy_bullet_active) {
        if ((game_frame & 0x3F) == 0) {
            enemy_bullet_active = 1;
            enemy_bullet_x = (u8)(enemy_x + fire_column * 5);
            enemy_bullet_y = (u8)(enemy_y + 57);
            ++fire_column;
            if (fire_column == 6) fire_column = 0;
        }
        return;
    }
    enemy_bullet_y = (u8)(enemy_bullet_y + 2);
    if (enemy_bullet_y >= 160) {
        delta = enemy_bullet_x > player_x
              ? (u8)(enemy_bullet_x - player_x) : (u8)(player_x - enemy_bullet_x);
        if (delta <= 1) {
            enemy_bullet_active = 0;
            if (lives) --lives;
            hud_dirty = 1;
            sfx_explosion();
            if (!lives) {
                speech_start(phrase_over);
                game_reset();
            }
        } else if (enemy_bullet_y > 174) {
            enemy_bullet_active = 0;
        }
    }
}

static void formation_tick(void)
{
    if ((game_frame & 7) != 0) return;
    animation ^= 1;
    if (enemy_right) {
        if (enemy_x >= 13) {
            enemy_right = 0;
            enemy_y = (u8)(enemy_y + 4);
        } else {
            ++enemy_x;
        }
    } else {
        if (enemy_x <= 1) {
            enemy_right = 1;
            enemy_y = (u8)(enemy_y + 4);
        } else {
            --enemy_x;
        }
    }
    if (enemy_y >= 102) {
        if (lives) --lives;
        hud_dirty = 1;
        sfx_explosion();
        if (!lives) {
            speech_start(phrase_over);
            game_reset();
        } else {
            formation_reset();
        }
    }
}

static void game_tick(void)
{
    input_tick();
    if (player_velocity < 0 && player_x > 1) --player_x;
    if (player_velocity > 0 && player_x < 38) ++player_x;
    formation_tick();
    player_bullet_tick();
    enemy_bullet_tick();
    if (!enemies_left) {
        speech_start(phrase_wave);
        formation_reset();
    }
    ++game_frame;
}

static void mailbox_init(u8 banks)
{
    MAILBOX->magic[0] = 0;
    MAILBOX->video_mode = 1;
    MAILBOX->banks = banks;
    MAILBOX->frame_lo = frame_lo;
    MAILBOX->frame_hi = frame_hi;
    MAILBOX->score = score;
    MAILBOX->lives = lives;
    MAILBOX->enemies = enemies_left;
    MAILBOX->player_x = player_x;
    MAILBOX->mhz = 33;
    MAILBOX->audio_flags = 7;
    MAILBOX->speech_phoneme = 0;
    MAILBOX->game_state = 1;
    MAILBOX->player_bullets = 0;
    MAILBOX->replay_bank = replay_bank;
    MAILBOX->speech_completions = 0;
    MAILBOX->shots_fired = 0;
    MAILBOX->deep_phase_lo = 0;
    MAILBOX->deep_phase_hi = 0;
    MAILBOX->nebula_phase_lo = 0;
    MAILBOX->nebula_phase_hi = 0;
    MAILBOX->asteroid_phase_lo = 0;
    MAILBOX->asteroid_phase_hi = 0;
    MAILBOX->music_step = music_step;
    MAILBOX->music_loops = music_loops;
    MAILBOX->music_tick = music_subtick;
    MAILBOX->ay_mixer = ay_mixer_shadow;
    MAILBOX->effect_kind = sfx_kind;
    MAILBOX->lead_note = music_lead_note;
    MAILBOX->bass_note = music_bass_note;
    MAILBOX->music_events = music_events;
    MAILBOX->parallax_commits = parallax_commits;
    /* Publish the handshake only after every payload byte is initialized. */
    MAILBOX->magic[1] = '1';
    MAILBOX->magic[2] = '3';
    MAILBOX->magic[3] = 'I';
    MAILBOX->magic[0] = 'A';
}

static void mailbox_parallax_tick(void)
{
    MAILBOX->deep_phase_lo = (u8)deep_phase.displayed_units;
    MAILBOX->deep_phase_hi = (u8)(deep_phase.displayed_units >> 8);
    MAILBOX->nebula_phase_lo = (u8)nebula_phase.displayed_units;
    MAILBOX->nebula_phase_hi = (u8)(nebula_phase.displayed_units >> 8);
    MAILBOX->asteroid_phase_lo = (u8)asteroid_phase.displayed_units;
    MAILBOX->asteroid_phase_hi = (u8)(asteroid_phase.displayed_units >> 8);
}

static void mailbox_parallax_target_tick(void)
{
    /* Publish while A2Li still holds the preceding weave. Once marker $01 is
     * visible, a paused debugger sees the exact target phases just committed. */
    MAILBOX->deep_phase_lo = (u8)deep_phase.target_units;
    MAILBOX->deep_phase_hi = (u8)(deep_phase.target_units >> 8);
    MAILBOX->nebula_phase_lo = (u8)nebula_phase.target_units;
    MAILBOX->nebula_phase_hi = (u8)(nebula_phase.target_units >> 8);
    MAILBOX->asteroid_phase_lo = (u8)asteroid_phase.target_units;
    MAILBOX->asteroid_phase_hi = (u8)(asteroid_phase.target_units >> 8);
    ++parallax_commits;
    MAILBOX->parallax_commits = parallax_commits;
}

static void mailbox_tick(void)
{
    MAILBOX->frame_lo = frame_lo;
    MAILBOX->frame_hi = frame_hi;
    MAILBOX->score = score;
    MAILBOX->lives = lives;
    MAILBOX->enemies = enemies_left;
    MAILBOX->player_x = player_x;
    MAILBOX->player_bullets = player_bullet_count();
    MAILBOX->shots_fired = shots_fired;
    mailbox_parallax_tick();
    MAILBOX->music_step = music_step;
    MAILBOX->music_loops = music_loops;
    MAILBOX->music_tick = music_subtick;
    MAILBOX->ay_mixer = ay_mixer_shadow;
    MAILBOX->effect_kind = sfx_kind;
    MAILBOX->lead_note = music_lead_note;
    MAILBOX->bass_note = music_bass_note;
    MAILBOX->music_events = music_events;
    MAILBOX->parallax_commits = parallax_commits;
}

int main(void)
{
    u8 banks;
    REG8(TWSPEED) = 0;
    REG8(RAMRDOFF) = 0;
    REG8(RAMWRTOFF) = 0;
    build_line_table();
    banks = ramworks_init();
    if (banks != 128 || !parallax_assets_load()) return 1;
    video_select();
    video_clear();
    video_color_playfield();
    parallax_init();
    video_begin_dhgri();
    parallax_capture_target();
    parallax_promote_target();
    parallax_render_rows(PARALLAX_WOVEN_TOP, PARALLAX_SLICE_ROWS);
    parallax_render_rows(PARALLAX_SECOND_WOVEN, PARALLAX_SLICE_ROWS);
    parallax_render_rows(PARALLAX_THIRD_WOVEN, PARALLAX_LAST_ROWS);
    video_border();
    video_text(31, 10, "APPLETINI INVASION");
    video_text(3, 181, "65C02 33MHZ  DHGRI  8MB RAMWORKS");
    audio_init();
    game_reset();
    replay_bank = REPLAY_FIRST_BANK;
    replay_slot = 0;
    frame_lo = 0;
    frame_hi = 0;
    game_frame = 0;
    mailbox_init(banks);
    draw_hud();
    draw_dynamic();
    mailbox_parallax_tick();
    video_commit_dhgri();
    speech_start(phrase_boot);

    for (;;) {
        wait_vbl();
        parallax_tick();

        /* Recompose one third of the exact three-layer source during each of
         * three VBLs. A2Li holds the preceding complete weave until the third
         * slice commits; the fourth VBL remains free of base-video writes. */
        if (parallax_render_state == 0) {
            video_begin_dhgri();
            game_tick();
            parallax_capture_target();
            parallax_render_rows(PARALLAX_WOVEN_TOP, PARALLAX_SLICE_ROWS);
            parallax_render_state = 1;
        } else if (parallax_render_state == 1) {
            parallax_render_rows(PARALLAX_SECOND_WOVEN, PARALLAX_SLICE_ROWS);
            parallax_render_state = 2;
        } else if (parallax_render_state == 2) {
            parallax_render_rows(PARALLAX_THIRD_WOVEN, PARALLAX_LAST_ROWS);
            game_tick();
            if (hud_dirty) draw_hud();
            draw_dynamic();
            mailbox_parallax_target_tick();
            video_commit_dhgri();
            parallax_promote_target();
            parallax_render_state = PARALLAX_STATE_QUIET;
        } else {
            /* One full VBL without base-video writes is mandatory after each
             * commit. Non-video audio, speech, and RamWorks replay work below
             * remains safe during this settling frame. */
            parallax_render_state = 0;
        }
        audio_tick();
        speech_tick();
        replay_record();
        ++frame_lo;
        if (!frame_lo) ++frame_hi;
        mailbox_tick();
    }
    return 0;
}
