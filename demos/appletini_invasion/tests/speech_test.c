/* Execute the production scheduler without booting the graphics engine.
 * sim65 treats slot addresses as RAM: script CA1 before each tick, and use
 * a sentinel to distinguish a register write from leaving it unchanged.
 * This checks the software's bus writes, not SSI synthesis or VIA circuitry.
 */
#include <stdio.h>
#include <stdlib.h>

#define main invasion_main
#include "main.c"
#undef main

static void check(u8 condition, const char* message)
{
    if (!condition) {
        puts(message);
        exit(1);
    }
}

/* Satisfy the uncalled game entry point. Accidental graphics calls fail. */
u8 __fastcall__ ramworks_probe(u8 bank)
{
    (void)bank;
    check(0, "unexpected RamWorks probe");
    return 0;
}
void aux_clear_video(void) { check(0, "unexpected video clear"); }
void __fastcall__ aux_color_row(u16 address)
{
    (void)address;
    check(0, "unexpected video color");
}
u8 __fastcall__ parallax_assets_load(void)
{
    check(0, "unexpected asset load");
    return 0;
}
void __fastcall__ parallax_render_slice(u8 rows)
{
    (void)rows;
    check(0, "unexpected parallax render");
}
void video_sprite_fast(void) { check(0, "unexpected sprite render"); }
void video_ship_fast(void) { check(0, "unexpected ship render"); }

/* $FF is a stream terminator, never a value sent to SSI_DUR. */
#define UNWRITTEN 0xFF

static void tick(u8 completion, u8 expected)
{
    REG8(VIA_IFR) = completion;
    REG8(SSI_DUR) = UNWRITTEN;
    speech_tick();
    check(REG8(SSI_DUR) == expected, "unexpected SSI DUR write");
    if (completion & 0x02) {
        check(REG8(VIA_IFR) == 0x02, "CA1 completion was not acknowledged");
    }
}

static void start(const u8* phrase)
{
    /* Include another flag so writing the CA1 acknowledgement is observable. */
    REG8(VIA_IFR) = 0x22;
    REG8(SSI_DUR) = UNWRITTEN;
    speech_start(phrase);
    check(REG8(VIA_IFR) == 0x02, "start did not clear stale CA1");
    check(REG8(SSI_DUR) == UNWRITTEN, "start replaced the phoneme prematurely");
    check(speech_active, "start left speech idle");
    /* The real VIA clears the written IFR bits; sim65 RAM does not. */
    REG8(VIA_IFR) = 0;
}

static void phrase_test(const u8* phrase, u8 ca1)
{
    u8 i;
    u8 wait;
    MAILBOX->speech_completions = 0;
    start(phrase);
    tick(0, phrase[0]);
    for (i = 1; ; ++i) {
        if (!ca1) {
            /* Twelve waiting frames, including after the final phoneme. */
            for (wait = 0; wait < 12; ++wait) {
                tick(0, UNWRITTEN);
                check(speech_active, "speech ended before phoneme completion");
                check(MAILBOX->speech_phoneme == phrase[(u8)(i - 1)],
                      "mailbox advanced before phoneme completion");
            }
        }
        /* The end marker must explicitly replace the last sound with PA. */
        tick(ca1 ? 0x22 : 0, phrase[i] == 0xFF ? 0x00 : phrase[i]);
        check(MAILBOX->speech_phoneme == phrase[i], "incorrect phrase mailbox");
        if (phrase[i] == 0xFF) break;
        check(speech_active, "speech ended within a phrase");
    }
    check(!speech_active, "phrase did not become idle");
    check(MAILBOX->speech_completions == (ca1 ? i : 0),
          "incorrect phoneme completion count");
    /* A repeating silent pause can raise CA1 again; idle must ignore it. */
    for (wait = 0; wait < 20; ++wait) {
        REG8(VIA_IFR) = 0x22;
        REG8(SSI_DUR) = UNWRITTEN;
        speech_tick();
        check(REG8(SSI_DUR) == UNWRITTEN, "idle rewrote the speech register");
        check(REG8(VIA_IFR) == 0x22, "idle consumed a pause completion");
        check(MAILBOX->speech_phoneme == 0xFF, "idle changed the mailbox");
    }
}

int main(void)
{
    phrase_test(phrase_boot, 1);
    phrase_test(phrase_wave, 1);
    phrase_test(phrase_over, 1);
    phrase_test(phrase_boot, 0);
    phrase_test(phrase_wave, 0);
    phrase_test(phrase_over, 0);

    /* Restart after the pause's stale completion, then wait for a new event. */
    start(phrase_wave);
    tick(0, phrase_wave[0]);
    tick(0, UNWRITTEN);
    check(MAILBOX->speech_phoneme == phrase_wave[0],
          "restart skipped the first phoneme");
    tick(0x22, phrase_wave[1]);
    puts("PASS Invasion speech: CA1, timeout, silent ending, idle, restart");
    return 0;
}
