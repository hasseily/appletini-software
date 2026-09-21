/*
 * Appletini Bosconian -- music, sound effects and speech.
 *
 * Hardware: Appletini virtual Phasor in Mockingboard mode, slot 4.
 *   AY-B (behind VIA-B, $C480) plays music on its three tone channels.
 *   AY-A (behind VIA-A, $C400) plays sound effects, one effect per channel,
 *   with priorities.
 *   SSI-263 speech at $C440-$C447. Those addresses also hit VIA-A registers
 *   (ORB, ORA, DDRB, DDRA, T1C-L), so after every SSI write the driver
 *   restores VIA-A (DDRA/DDRB, AY reset pulse) and resends every AY-A
 *   register.
 *
 * Bus rule: every $C4xx access slows the virtual TransWarp to 1 MHz for a
 * while, so all $C4xx traffic happens inside sound_init() and
 * sound_update() (one burst per frame). Both AY chips have a register
 * shadow; only registers whose value changed are written (6 bus accesses per
 * register). Worst case per frame: 2 x 11 registers x 6 = 132 accesses plus
 * a few speech accesses, well under 150. A quiet frame costs 0 accesses.
 *
 * All $C4xx primitives live in sound_io.s.
 */

#include "bosco.h"

/* ---- sound_io.s ---- */
void __fastcall__ ay_write_a(u8 reg, u8 val);
void __fastcall__ ay_write_b(u8 reg, u8 val);
void __fastcall__ ssi_write(u8 reg, u8 val);   /* reg = offset 0..4 from $C440 */
void via_a_prep(void);                          /* IER=$7F, PCR=0, IFR=$7F */
void via_b_prep(void);
void via_a_ddr(void);                           /* DDRA=$FF, DDRB=$07, ORB=0, ORB=4 */
void via_b_ddr(void);

/* SSI-263 register offsets for ssi_write() */
#define SSI_R_DUR  0
#define SSI_R_INF  1
#define SSI_R_RATE 2
#define SSI_R_CTL  3
#define SSI_R_FILT 4

/* ---- mailbox globals (bosco.h) ---- */
u8 sound_current_sfx;
u8 sound_current_track;
u8 speech_current;

/* =====================================================================
 * AY register shadows. want_* is what the engines ask for this frame,
 * shadow_* is what the chip holds. ay_flush() writes the difference.
 * Registers: 0-5 tone periods (lo/hi for A, B, C), 6 noise period,
 * 7 mixer (bit = 1 disables; bits 0-2 tone A-C, bits 3-5 noise A-C),
 * 8-10 volumes.
 * ===================================================================== */
#define AY_REGS 11
#define MIX_ALL_OFF 0x3F
#define MIX_TONES_ON 0x38

static u8 want_a[AY_REGS];
static u8 shadow_a[AY_REGS];
static u8 force_a;               /* resend every AY-A register */
static u8 want_b[AY_REGS];
static u8 shadow_b[AY_REGS];
static u8 force_b;

static void ay_flush_a(void)
{
    u8 r;
    for (r = 0; r < AY_REGS; ++r) {
        if (force_a || want_a[r] != shadow_a[r]) {
            shadow_a[r] = want_a[r];
            ay_write_a(r, want_a[r]);
        }
    }
    force_a = 0;
}

static void ay_flush_b(void)
{
    u8 r;
    for (r = 0; r < AY_REGS; ++r) {
        if (force_b || want_b[r] != shadow_b[r]) {
            shadow_b[r] = want_b[r];
            ay_write_b(r, want_b[r]);
        }
    }
    force_b = 0;
}

/* =====================================================================
 * Note table: chromatic E2..B5 for the 1.0227 MHz AY clock,
 * period = 63920 / Hz. Index 0 is a rest.
 * ===================================================================== */
#define NOTE_HOLD 0x7F           /* sequencer: keep the previous note sounding */

static const u8 note_lo[45] = {
    0x00, 0x08, 0xDC, 0xB3, 0x8C, 0x68, 0x45, 0x24, 0x06, 0xE9, 0xCD, 0xB3,
    0x9B, 0x84, 0x6E, 0x5A, 0x46, 0x34, 0x23, 0x12, 0x03, 0xF4, 0xE7, 0xDA,
    0xCD, 0xC2, 0xB7, 0xAD, 0xA3, 0x9A, 0x91, 0x89, 0x81, 0x7A, 0x73, 0x6D,
    0x67, 0x61, 0x5C, 0x56, 0x52, 0x4D, 0x49, 0x45, 0x41
};
static const u8 note_hi[45] = {
    0x00, 0x03, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x01, 0x01, 0x01,
    0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

#define N_E2 1
#define N_F2 2
#define N_FS2 3
#define N_G2 4
#define N_GS2 5
#define N_A2 6
#define N_AS2 7
#define N_B2 8
#define N_C3 9
#define N_CS3 10
#define N_D3 11
#define N_DS3 12
#define N_E3 13
#define N_F3 14
#define N_FS3 15
#define N_G3 16
#define N_GS3 17
#define N_A3 18
#define N_AS3 19
#define N_B3 20
#define N_C4 21
#define N_CS4 22
#define N_D4 23
#define N_DS4 24
#define N_E4 25
#define N_F4 26
#define N_FS4 27
#define N_G4 28
#define N_GS4 29
#define N_A4 30
#define N_AS4 31
#define N_B4 32
#define N_C5 33
#define N_CS5 34
#define N_D5 35
#define N_DS5 36
#define N_E5 37
#define N_F5 38
#define N_FS5 39
#define N_G5 40
#define N_GS5 41
#define N_A5 42
#define N_AS5 43
#define N_B5 44

#define H_ NOTE_HOLD
#define R_ 0

/* =====================================================================
 * Music tracks. A track is a list of steps; each step is three bytes:
 *   lead note, bass note, arpeggio chord id (0 = no arpeggio).
 * 0 = rest, NOTE_HOLD = keep the previous value, otherwise a note index.
 * The arpeggio channel cycles the three chord notes every two frames.
 * All tunes are original.
 * ===================================================================== */

/* chords for the arpeggio channel (three notes each; id 0 = none) */
#define CH_NONE 0
#define CH_AM 1
#define CH_F 2
#define CH_G 3
#define CH_E 4
#define CH_C 5
#define CH_DM 6
#define CH_EM 7
static const u8 chord_notes[8][3] = {
    { 0, 0, 0 },
    { N_A3, N_C4, N_E4 },       /* Am */
    { N_F3, N_A3, N_C4 },       /* F  */
    { N_G3, N_B3, N_D4 },       /* G  */
    { N_E3, N_GS3, N_B3 },      /* E  */
    { N_C4, N_E4, N_G4 },       /* C  */
    { N_D4, N_F4, N_A4 },       /* Dm */
    { N_E4, N_G4, N_B4 }        /* Em */
};

/* MUSIC_TITLE: A minor, 32 steps x 8 frames, loops (about 4.3 s). */
static const u8 title_steps[32 * 3] = {
    N_A4, N_A2, CH_AM,   H_,   N_A2, H_,     N_C5, N_A3, H_,     H_,   N_A2, H_,
    N_E5, N_F2, CH_F,    H_,   N_F2, H_,     N_D5, N_F3, H_,     N_C5, N_F2, H_,
    N_B4, N_G2, CH_G,    H_,   N_G2, H_,     N_G4, N_G3, H_,     H_,   N_G2, H_,
    N_B4, N_E2, CH_E,    H_,   N_E2, H_,     N_GS4,N_E3, H_,     N_B4, N_E2, H_,
    N_A4, N_A2, CH_AM,   H_,   N_A2, H_,     N_E5, N_A3, H_,     H_,   N_A2, H_,
    N_A5, N_F2, CH_F,    H_,   N_F2, H_,     N_G5, N_F3, H_,     N_E5, N_F2, H_,
    N_F5, N_G2, CH_G,    N_E5, N_G2, H_,     N_D5, N_G3, H_,     H_,   N_G2, H_,
    N_C5, N_E2, CH_E,    N_B4, N_E2, H_,     N_A4, N_E3, H_,     H_,   N_E2, H_
};

/* MUSIC_BLASTOFF: rising fanfare, 15 steps x 6 frames = 90 frames (1.5 s),
 * then MUSIC_AMBIENT. */
static const u8 blastoff_steps[15 * 3] = {
    N_A4, N_A3, CH_AM,   N_C5, N_A3, H_,     N_E5, N_A3, H_,     N_A5, N_A2, H_,
    H_,   H_,   H_,      H_,   H_,   H_,     R_,   R_,   CH_NONE,
    N_E5, N_F2, CH_F,    N_G5, N_G2, CH_G,   N_A5, N_A2, CH_AM,  H_,   H_,   H_,
    H_,   H_,   H_,      H_,   H_,   H_,     H_,   H_,   H_
};

/* MUSIC_ROUND_CLEAR: C major jingle, 20 steps x 6 frames = 120 frames (2 s),
 * then silence. */
static const u8 clear_steps[20 * 3] = {
    N_G4, N_C3, CH_C,    N_C5, H_,   H_,     N_E5, N_G2, H_,     N_G5, H_,   H_,
    H_,   N_C3, H_,      N_E5, H_,   H_,     N_G5, N_G2, H_,     H_,   H_,   H_,
    H_,   N_C3, H_,      R_,   R_,   CH_NONE,
    N_A5, N_F3, CH_F,    N_G5, H_,   H_,     N_E5, N_G2, CH_G,   N_C5, H_,   H_,
    N_D5, N_G2, H_,      H_,   H_,   H_,     N_E5, N_C3, CH_C,   H_,   H_,   H_,
    H_,   H_,   H_,      H_,   H_,   H_
};

/* MUSIC_DEATH: descending phrase, 10 steps x 6 frames = 60 frames (1 s). */
static const u8 death_steps[10 * 3] = {
    N_E5, N_E3, CH_NONE, N_D5, N_D3, H_,     N_C5, N_C3, H_,     N_B4, N_B2, H_,
    N_A4, N_A2, H_,      N_G4, N_G2, H_,     N_F4, N_F2, H_,     N_E4, N_E2, H_,
    N_D4, N_E2, H_,      N_C4, N_E2, H_
};

/* MUSIC_GAME_OVER: slow phrase, 15 steps x 12 frames = 180 frames (3 s). */
static const u8 over_steps[15 * 3] = {
    N_A4, N_A2, CH_AM,   H_,   H_,   H_,     N_G4, N_G2, CH_G,   H_,   H_,   H_,
    N_F4, N_F2, CH_F,    H_,   H_,   H_,     N_E4, N_E2, CH_E,   H_,   H_,   H_,
    H_,   H_,   H_,      N_D4, N_F2, CH_DM,  N_C4, N_G2, CH_C,   N_B3, N_E2, CH_E,
    N_A3, N_A2, CH_AM,   H_,   H_,   H_,     H_,   H_,   H_
};

struct Track {
    const u8 *steps;
    u8 nsteps;
    u8 fps;      /* frames per step */
    u8 next;     /* track after the last step: same id = loop */
};

static const struct Track tracks[7] = {
    { 0, 0, 0, MUSIC_NONE },                              /* MUSIC_NONE */
    { title_steps, 32, 8, MUSIC_TITLE },                  /* MUSIC_TITLE */
    { blastoff_steps, 15, 6, MUSIC_AMBIENT },             /* MUSIC_BLASTOFF */
    { 0, 0, 0, MUSIC_AMBIENT },                           /* MUSIC_AMBIENT (generator) */
    { clear_steps, 20, 6, MUSIC_NONE },                   /* MUSIC_ROUND_CLEAR */
    { death_steps, 10, 6, MUSIC_NONE },                   /* MUSIC_DEATH */
    { over_steps, 15, 12, MUSIC_NONE }                    /* MUSIC_GAME_OVER */
};

/* ---- sequencer state ---- */
static u8 seq_track;             /* MUSIC_* now playing */
static const u8 *seq_pos;        /* current step (3 bytes) */
static u8 seq_step;
static u8 seq_subtick;           /* frame inside the step */
static u8 seq_lead;              /* sounding notes (0 = rest) */
static u8 seq_bass;
static u8 seq_chord;
static u8 seq_lead_age;          /* frames since the lead note started */
static u8 seq_arp_idx;           /* 0..2 chord note */
static u8 seq_arp_tick;

/* ---- ambient generator state ---- */
static u8 amb_tempo;             /* 0 green .. 2 red */
static u8 amb_pulse_t;
static u8 amb_phase;
static u8 amb_ping_t;
static u8 amb_ping_v;
static const u8 amb_pulse_len[3] = { 16, 11, 7 };
#define AMB_PING_PERIOD 96

/* ---- speech state (defined early: music ducks while speaking) ---- */
static u8 speech_active;
#define SPEECH_QUEUE 3
static u8 speech_queue[SPEECH_QUEUE]; /* phrases waiting, in order */
static u8 speech_queued;         /* entries used in speech_queue */
static const u8 *speech_ptr;
static u8 speech_index;
static u8 speech_timer;

static void seq_set_period(u8 chan, u8 note)
{
    u8 r = (u8)(chan << 1);
    want_b[r] = note_lo[note];
    want_b[(u8)(r + 1)] = note_hi[note];
}

static u8 duck(u8 vol)
{
    if (speech_active && vol > 3) return (u8)(vol - 3);
    return vol;
}

static void seq_load_step(void)
{
    u8 n;
    n = seq_pos[0];
    if (n != NOTE_HOLD) { seq_lead = n; seq_lead_age = 0; }
    n = seq_pos[1];
    if (n != NOTE_HOLD) seq_bass = n;
    n = seq_pos[2];
    if (n != NOTE_HOLD) {
        if (n != seq_chord) { seq_arp_idx = 0; seq_arp_tick = 0; }
        seq_chord = n;
    }
}

/* the step after the current one (for the end-of-step gate) */
static const u8 *seq_next_step(void)
{
    const struct Track *t = &tracks[seq_track];
    if ((u8)(seq_step + 1) < t->nsteps) return seq_pos + 3;
    if (t->next == seq_track) return t->steps;
    return 0;
}

static void music_silence(void)
{
    /* volumes off; the mixer is left as it is so a quiet frame costs nothing */
    want_b[8] = 0;
    want_b[9] = 0;
    want_b[10] = 0;
}

static void ambient_tick(void)
{
    u8 vol;

    /* engine pulse on channel A: two low pitches alternate */
    if (amb_pulse_t == 0) {
        if (amb_phase) { want_b[0] = 0x07; want_b[1] = 0x04; }   /* 1031 */
        else           { want_b[0] = 0x91; want_b[1] = 0x03; }   /* 913 */
        vol = 11;
    } else if (amb_pulse_t < 2) {
        vol = 11;
    } else if (amb_pulse_t < 4) {
        vol = 8;
    } else {
        vol = 6;
    }
    want_b[8] = duck(vol);
    ++amb_pulse_t;
    if (amb_pulse_t >= amb_pulse_len[amb_tempo]) {
        amb_pulse_t = 0;
        amb_phase ^= 1;
    }

    /* channel B silent */
    want_b[9] = 0;

    /* sparse high ping on channel C */
    if (amb_ping_t == 0) {
        amb_ping_t = AMB_PING_PERIOD;
        amb_ping_v = 8;
        want_b[4] = 0x3D;          /* 61: about 1048 Hz */
        want_b[5] = 0x00;
    }
    --amb_ping_t;
    if (amb_ping_v) {
        want_b[10] = duck(amb_ping_v);
        --amb_ping_v;
    } else {
        want_b[10] = 0;
    }
    want_b[7] = MIX_TONES_ON;
}

static void seq_tick(void)
{
    const struct Track *t = &tracks[seq_track];
    const u8 *next;
    u8 last;
    u8 vol;

    if (seq_subtick == 0) seq_load_step();
    last = (u8)(seq_subtick == (u8)(t->fps - 1));
    next = last ? seq_next_step() : 0;

    /* lead: channel A, short attack then steady, gated on the last frame */
    if (seq_lead) {
        seq_set_period(0, seq_lead);
        vol = seq_lead_age ? 11 : 13;
        if (last && (next == 0 || next[0] != NOTE_HOLD)) vol = 0;
        want_b[8] = duck(vol);
    } else {
        want_b[8] = 0;
    }
    ++seq_lead_age;

    /* bass: channel B */
    if (seq_bass) {
        seq_set_period(1, seq_bass);
        vol = 10;
        if (last && (next == 0 || next[1] != NOTE_HOLD)) vol = 0;
        want_b[9] = duck(vol);
    } else {
        want_b[9] = 0;
    }

    /* arpeggio: channel C cycles the chord every two frames */
    if (seq_chord) {
        seq_set_period(2, chord_notes[seq_chord][seq_arp_idx]);
        want_b[10] = duck(7);
        seq_arp_tick ^= 1;
        if (!seq_arp_tick) {
            ++seq_arp_idx;
            if (seq_arp_idx == 3) seq_arp_idx = 0;
        }
    } else {
        want_b[10] = 0;
    }
    want_b[7] = MIX_TONES_ON;

    /* advance */
    ++seq_subtick;
    if (seq_subtick >= t->fps) {
        seq_subtick = 0;
        ++seq_step;
        seq_pos += 3;
        if (seq_step >= t->nsteps) {
            if (t->next == seq_track) {
                seq_step = 0;
                seq_pos = t->steps;
            } else {
                sound_music(t->next);
            }
        }
    }
}

static void music_tick(void)
{
    if (seq_track == MUSIC_AMBIENT) {
        ambient_tick();
    } else if (seq_track == MUSIC_NONE) {
        music_silence();
    } else {
        seq_tick();
    }
}

void __fastcall__ sound_music(u8 track)
{
    if (track > MUSIC_GAME_OVER) track = MUSIC_NONE;
    seq_track = track;
    seq_pos = tracks[track].steps;
    seq_step = 0;
    seq_subtick = 0;
    seq_lead = 0;
    seq_bass = 0;
    seq_chord = 0;
    seq_lead_age = 0;
    seq_arp_idx = 0;
    seq_arp_tick = 0;
    amb_pulse_t = 0;
    amb_phase = 0;
    amb_ping_t = 24;
    amb_ping_v = 0;
    sound_current_track = track;
}

void __fastcall__ sound_tempo(u8 level)
{
    if (level > 2) level = 2;
    amb_tempo = level;
}

/* =====================================================================
 * Sound effects on AY-A. Three slots, one per channel. Each effect is a
 * small generator: sfx_gen() turns (id, frame) into tone period, noise
 * period and volume. A new effect takes a free slot, else it steals the
 * slot with the lowest priority when its own priority is at least as high.
 * ===================================================================== */
struct SfxSlot {
    u8 id;       /* SFX_NONE = free */
    u8 t;        /* frames played */
    u8 len;
    u8 prio;
    u8 retrig;   /* SFX_ALERT: restart when the loop ends */
};
static struct SfxSlot sfx_slot[3];

static const u8 sfx_len[12]  = { 0, 6, 10, 18, 12, 40, 24, 50, 60, 30, 20, 12 };
static const u8 sfx_prio[12] = { 0, 1,  3,  5,  4,  8,  6,  9,  7,  5,  7,  2 };

/* generator output */
static u16 g_period;
static u8 g_noise;               /* 0xFF = no noise */
static u8 g_vol;
static u8 g_tone;                /* 1 = tone on */
static const u8 life_periods[5] = { 122, 97, 82, 61, 48 };

#define NO_NOISE 0xFF

static void sfx_gen(u8 id, u8 t)
{
    g_tone = 1;
    g_noise = NO_NOISE;
    switch (id) {
    case SFX_SHOT:          /* short falling blip */
        g_period = (u16)(90 + ((u16)t << 4));
        g_vol = (u8)(12 - (t << 1));
        break;
    case SFX_HIT:           /* tone + noise, fading */
        g_period = (u16)(150 + ((u16)t << 3));
        g_noise = 8;
        g_vol = (u8)(12 - t);
        break;
    case SFX_EXPLODE:       /* noise decay */
        g_tone = 0;
        g_period = 0;
        g_noise = (u8)(14 + (t >> 1));
        g_vol = (u8)(13 - (t >> 1));
        break;
    case SFX_POD:           /* pod hit: tone + noise */
        g_period = (u16)(220 + ((u16)t << 4));
        g_noise = 12;
        g_vol = (u8)(13 - t);
        break;
    case SFX_BASE:          /* long noise plus a descending tone */
        g_period = (u16)(180 + ((u16)t << 3));
        g_noise = (u8)(18 + (t >> 2));
        g_vol = (u8)(15 - (t >> 2));
        break;
    case SFX_MINE:          /* big low noise */
        g_period = (u16)(900 + ((u16)t << 5));
        g_noise = (u8)(24 + (t >> 2));
        g_vol = (u8)(15 - (t >> 1));
        break;
    case SFX_PLAYER_DIE:    /* long downward sweep, noise joins later */
        g_period = (u16)(120 + ((u16)t << 4));
        if (t > 16) g_noise = (u8)(10 + (t >> 2));
        g_vol = (u8)(14 - (t >> 2));
        break;
    case SFX_ALERT:         /* two-tone siren, 16 frames per tone */
        g_period = (t & 16) ? 340 : 260;
        g_vol = 11;
        break;
    case SFX_SPY:           /* warble */
        g_period = (t & 4) ? 230 : 190;
        g_vol = (u8)(10 - (t >> 3));
        break;
    case SFX_EXTRA_LIFE:    /* rising arpeggio, one note per 4 frames */
        g_period = life_periods[t >> 2];
        g_vol = ((t & 3) == 3) ? 8 : 12;
        break;
    case SFX_MISSILE:       /* rising whoosh */
        g_period = (u16)(320 - ((u16)t << 4));
        g_noise = 5;
        g_vol = (u8)(9 - (t >> 2));
        break;
    default:
        g_tone = 0;
        g_period = 0;
        g_vol = 0;
        break;
    }
}

void __fastcall__ sound_sfx(u8 id)
{
    u8 i;
    u8 prio;
    u8 victim;
    u8 vprio;
    u8 vt;

    if (id == SFX_NONE || id > SFX_MISSILE) return;
    prio = sfx_prio[id];

    /* already playing: the siren loops, everything else restarts */
    for (i = 0; i < 3; ++i) {
        if (sfx_slot[i].id == id) {
            if (id == SFX_ALERT) sfx_slot[i].retrig = 1;
            else sfx_slot[i].t = 0;
            sound_current_sfx = id;
            return;
        }
    }

    /* free slot, else the lowest-priority (then oldest) slot */
    victim = 0xFF;
    vprio = 0xFF;
    vt = 0;
    for (i = 0; i < 3; ++i) {
        if (sfx_slot[i].id == SFX_NONE) { victim = i; vprio = 0; break; }
        if (sfx_slot[i].prio < vprio ||
            (sfx_slot[i].prio == vprio && sfx_slot[i].t > vt)) {
            victim = i;
            vprio = sfx_slot[i].prio;
            vt = sfx_slot[i].t;
        }
    }
    if (prio < vprio) return;          /* everything playing matters more */

    sfx_slot[victim].id = id;
    sfx_slot[victim].t = 0;
    sfx_slot[victim].len = sfx_len[id];
    sfx_slot[victim].prio = prio;
    sfx_slot[victim].retrig = 0;
    sound_current_sfx = id;
}

static void sfx_tick(void)
{
    u8 i;
    u8 mixer = MIX_ALL_OFF;
    u8 noise_prio = 0;
    u8 top_prio = 0;
    u8 top_id = SFX_NONE;
    u8 r;
    struct SfxSlot *s;

    for (i = 0; i < 3; ++i) {
        s = &sfx_slot[i];
        r = (u8)(i << 1);
        if (s->id == SFX_NONE) {
            want_a[(u8)(8 + i)] = 0;
            continue;
        }
        sfx_gen(s->id, s->t);
        if (g_tone) {
            want_a[r] = (u8)g_period;
            want_a[(u8)(r + 1)] = (u8)(g_period >> 8);
            mixer &= (u8)~(1 << i);
        }
        if (g_noise != NO_NOISE) {
            mixer &= (u8)~(8 << i);
            if (s->prio >= noise_prio) {
                noise_prio = s->prio;
                want_a[6] = (u8)(g_noise & 0x1F);
            }
        }
        want_a[(u8)(8 + i)] = (u8)(g_vol & 0x0F);

        ++s->t;
        if (s->t >= s->len) {
            if (s->retrig) {
                s->t = 0;
                s->retrig = 0;
            } else {
                s->id = SFX_NONE;       /* finished: silent from the next frame */
                continue;
            }
        }
        if (s->prio >= top_prio) { top_prio = s->prio; top_id = s->id; }
    }
    want_a[7] = mixer;
    sound_current_sfx = top_id;
}

/* =====================================================================
 * Speech. One phrase at a time, up to three queued in order (CONDITION
 * RED, BATTLE STATIONS and the formation's ALERT can arrive within two
 * frames). A phoneme is sent to the
 * SSI-263 DUR register; the next one goes out when the chip raises CA1
 * (VIA IFR bit 1) or after a 12-frame timeout. The SSI write also hits
 * VIA-A ORB, so VIA-A is restored and AY-A is fully resent afterwards.
 * ===================================================================== */

/* SSI-263 phoneme codes, duration in bits 7-6, $FF ends the phrase. */
static const u8 phrase_blast_off[] = {
    0x24, 0x20, 0x0C, 0x30, 0x28, 0x00, 0x10, 0x34, 0xFF   /* B L AE S T - AW F */
};
static const u8 phrase_alert[] = {
    0x18, 0x20, 0x1C, 0x28, 0x00, 0x18, 0x20, 0x1C, 0x28, 0xFF /* UH L ER T - UH L ER T */
};
static const u8 phrase_spy[] = {
    0x30, 0x27, 0x05, 0x00, 0x32, 0x07, 0x27, 0x00,          /* S P AY - SCH I P - */
    0x30, 0x05, 0x28, 0x07, 0x25, 0xFF                       /* S AY T I D */
};
static const u8 phrase_red[] = {
    0x29, 0x18, 0x38, 0x25, 0x07, 0x32, 0x18, 0x38, 0x00,    /* K UH N D I SCH UH N - */
    0x1D, 0x0A, 0x25, 0xFF                                   /* R EH D */
};
static const u8 phrase_battle[] = {
    0x24, 0x0C, 0x28, 0x18, 0x20, 0x00,                      /* B AE T UH L - */
    0x30, 0x28, 0x05, 0x32, 0x18, 0x38, 0x2F, 0xFF           /* S T AY SCH UH N Z */
};
static const u8 phrase_game_over[] = {
    0x29, 0x05, 0x37, 0x00, 0x11, 0x33, 0x1C, 0xFF           /* K AY M - O V ER */
};
static const u8 *const phrases[6] = {
    phrase_blast_off, phrase_alert, phrase_spy, phrase_red, phrase_battle,
    phrase_game_over
};

#define SPEECH_TIMEOUT 12
#define IFR_CA1 0x02

void __fastcall__ speech_say(u8 phrase)
{
    if (phrase > SAY_GAME_OVER) return;
    if (speech_active) {
        if (speech_queued < SPEECH_QUEUE) speech_queue[speech_queued++] = phrase;
        return;
    }
    speech_active = 1;
    speech_current = phrase;
    speech_ptr = phrases[phrase];
    speech_index = 0;
    speech_timer = 0;
}

u8 speech_busy(void)
{
    return (u8)(speech_active || speech_queued);
}

static void speech_send(u8 phoneme)
{
    ssi_write(SSI_R_DUR, phoneme);
    via_a_ddr();
    force_a = 1;
}

static void speech_tick(void)
{
    u8 phoneme;
    u8 done;

    if (!speech_active) {
        if (speech_queued == 0) return;
        phoneme = speech_queue[0];
        --speech_queued;
        for (done = 0; done < speech_queued; ++done) {
            speech_queue[done] = speech_queue[done + 1];
        }
        speech_say(phoneme);
    }
    if (speech_index) {
        /* wait for the current phoneme: CA1 flag on either VIA, or timeout */
        done = (u8)((REG8(VIA_B_IFR) | REG8(VIA_A_IFR)) & IFR_CA1);
        if (done) {
            REG8(VIA_B_IFR) = IFR_CA1;
            REG8(VIA_A_IFR) = IFR_CA1;
        } else if (speech_timer) {
            --speech_timer;
            return;
        }
    } else {
        /* new phrase: drop a stale completion flag */
        REG8(VIA_B_IFR) = IFR_CA1;
        REG8(VIA_A_IFR) = IFR_CA1;
    }
    phoneme = speech_ptr[speech_index];
    ++speech_index;
    if (phoneme == 0xFF) {
        speech_active = 0;
        speech_current = SAY_NONE;
        return;
    }
    speech_send(phoneme);
    speech_timer = SPEECH_TIMEOUT;
}

/* =====================================================================
 * Public entry points
 * ===================================================================== */
void sound_init(void)
{
    u8 r;

    sound_current_sfx = SFX_NONE;
    sound_current_track = MUSIC_NONE;
    speech_current = SAY_NONE;
    speech_active = 0;
    speech_queued = 0;
    speech_index = 0;
    speech_timer = 0;
    amb_tempo = 0;
    for (r = 0; r < 3; ++r) sfx_slot[r].id = SFX_NONE;
    sound_music(MUSIC_NONE);

    /* VIAs: no interrupts, CA1 negative edge, flags cleared */
    via_a_prep();
    via_b_prep();

    /* speech chip setup while the VIA-A port pins are still inputs */
    ssi_write(SSI_R_CTL, 0x80);
    ssi_write(SSI_R_DUR, 0xC0);
    ssi_write(SSI_R_INF, 0x40);
    ssi_write(SSI_R_RATE, 0xA8);
    ssi_write(SSI_R_CTL, 0x5A);
    ssi_write(SSI_R_FILT, 0xE8);

    /* ports to the AYs, reset both chips */
    via_a_ddr();
    via_b_ddr();

    /* silence: mixer off, volumes 0, every register written once */
    for (r = 0; r < AY_REGS; ++r) {
        want_a[r] = 0;
        want_b[r] = 0;
    }
    want_a[7] = MIX_ALL_OFF;
    want_b[7] = MIX_ALL_OFF;
    force_a = 1;
    force_b = 1;
    ay_flush_b();
    ay_flush_a();
}

void sound_update(void)
{
    music_tick();
    sfx_tick();
    speech_tick();      /* may write the SSI-263 and set force_a */
    ay_flush_b();
    ay_flush_a();       /* after speech, so a clobbered AY-A is fixed now */
}
