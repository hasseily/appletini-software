/* Board check for speech. It prints what the slot-4 SSI-263 and the libtini
 * audio driver do on this machine, then waits for a key. Text screen only.
 *
 * RAW drives the SSI without the driver's speech code and polls both VIAs
 * for the CA1 flag that marks a finished phoneme. The driver lines say two
 * STARFALL phrases and report the result, the time taken and how often a
 * finished-phoneme flag was seen before the driver consumed it, with and
 * without joystick reads between updates. */
#include "libtini.h"
#include "speech_check_speech.h"
#define IO(a) (*(volatile uint8_t *)(a))

static uint8_t row;
static char line[41];
static ti_joystick stick;

static void print(void)
{
    uint8_t i, end = 0, *p = (uint8_t *)(0x400 + (row & 7) * 0x80 + (row >> 3) * 0x28);
    for (i = 0; i < 40; ++i) {
        if (!line[i]) end = 1;
        p[i] = (uint8_t)((end ? ' ' : line[i]) | 128);
    }
    if (row < 23) ++row;
}
/* Copy s to line at column at; returns the next column. */
static uint8_t put(uint8_t at, const char *s)
{
    while (*s && at < 40) line[at++] = *s++;
    line[at] = 0;
    return at;
}
static uint8_t num(uint8_t at, uint16_t value)
{
    char digits[6];
    uint8_t n = 0;
    do digits[n++] = (char)('0' + value % 10); while ((value /= 10) && n < 5);
    while (n && at < 40) line[at++] = digits[--n];
    line[at] = 0;
    return at;
}
/* Ticks are hundredths of a second. */
static uint8_t seconds(uint8_t at, uint16_t ticks)
{
    at = num(at, ticks / 100);
    line[at++] = '.';
    line[at++] = (char)('0' + ticks / 10 % 10);
    line[at++] = (char)('0' + ticks % 10);
    line[at] = 0;
    return put(at, "S");
}
static const char *error_name(ti_error e)
{
    static const char *const names[] = {"OK", "ARGUMENT", "STATE", "RANGE", "NOMEM", "HANDLE",
        "UNAVAILABLE", "TIMING", "BUSY", "IO", "FORMAT", "FULL"};
    return e < sizeof(names) / sizeof(names[0]) ? names[e] : "?";
}
static uint16_t ticks(void) { return (uint16_t)ti_audio_ticks(); }

/* After an SSI write, Mockingboard mode also wrote VIA-A: restore its ports
 * so AY 0 stays idle, as the driver does. */
static void ssi(uint8_t reg, uint8_t value)
{
    IO(0xC440 + reg) = value;
    IO(0xC413) = 255; IO(0xC412) = 31; IO(0xC410) = 0; IO(0xC410) = 12;
}
/* Wait up to one second for CA1 on either VIA; returns 1 for VIA-A $C400,
 * 2 for VIA-B $C480, 3 for both, 0 for neither. */
static uint8_t wait_ca1(uint16_t *elapsed)
{
    uint16_t began = ticks();
    uint8_t flags;
    do {
        flags = (uint8_t)((IO(0xC41D) & 2 ? 1 : 0) | (IO(0xC48D) & 2 ? 2 : 0));
        if (flags) break;
    } while ((uint16_t)(ticks() - began) < 100);
    *elapsed = ticks() - began;
    IO(0xC41D) = 2; IO(0xC48D) = 2;
    return flags;
}
static void raw_check(void)
{
    ti_audio_config config = {TI_AUDIO_MOCKINGBOARD, 0, 0, 0, 0};
    const ti_phrase *phrase = &sc_speech.phrases[SAY_READY];
    uint16_t elapsed, total = 0;
    uint8_t i, via, a = 0, b = 0, done = 0, at;
    ti_error e = ti_audio_init(&config);
    if (e) { at = put(0, "RAW: AUDIO INIT "); put(at, error_name(e)); print(); return; }
    ssi(3, 0x80);                      /* CTL high: standby */
    ssi(0, 0xC0);                      /* mode 3, A/R active */
    IO(0xC41D) = 2; IO(0xC48D) = 2;
    ssi(3, 0x5A);                      /* CTL low latches the mode and starts */
    via = wait_ca1(&elapsed);
    at = put(0, "RAW START: CA1 ");
    at = put(at, via == 1 ? "VIA-A" : via == 2 ? "VIA-B" : via == 3 ? "BOTH" : "NONE");
    at = put(at, " ");
    seconds(at, elapsed);
    print();
    for (i = 0; i < phrase->length; ++i) {
        IO(0xC41D) = 2; IO(0xC48D) = 2;
        ssi(0, phrase->data[i]);
        via = wait_ca1(&elapsed);
        if (via & 1) ++a;
        if (via & 2) ++b;
        if (via) { ++done; total += elapsed; }
    }
    ssi(3, 0x80);
    at = put(0, "RAW PHONEMES ");
    at = num(at, done); at = put(at, "/"); at = num(at, phrase->length);
    at = put(at, " A:"); at = num(at, a); at = put(at, " B:"); at = num(at, b);
    at = put(at, " "); seconds(at, total);
    print();
    ti_audio_shutdown();
}
static void driver_check(const char *name, uint8_t personality, uint8_t joystick)
{
    ti_audio_config config = {0, 1, 0, 0, 0};
    uint16_t began, next = 0, failed_at = 0;
    uint8_t flag, last = 0, seen = 0, reads = 0, errors = 0, native, at;
    ti_error e, first = TI_OK, said;
    config.personality = personality;
    e = ti_audio_init(&config);
    at = put(0, name);
    if (e) { at = put(at, " INIT "); put(at, error_name(e)); print(); return; }
    native = personality == TI_AUDIO_PHASOR && ti_audio_voices() == 12;
    if (personality == TI_AUDIO_PHASOR && !native) {
        put(at, " NO PHASOR"); print(); ti_audio_shutdown(); return;
    }
    e = ti_speech_bind(&sc_speech);
    said = e ? e : ti_speech_say(SAY_READY, 1);
    if (!said) said = ti_speech_say(SAY_EXCELLENT, 1);
    if (said) { at = put(at, " SAY "); put(at, error_name(said)); print(); ti_audio_shutdown(); return; }
    began = ticks();
    while (ti_speech_busy() && (uint16_t)(ticks() - began) < 500) {
        /* Sample the finished-phoneme signal before the driver consumes it. */
        flag = native ? IO(0xC440) & 0x80 : (IO(0xC41D) | IO(0xC48D)) & 2;
        if (flag && !last) ++seen;
        last = flag;
        e = ti_audio_update();
        if (e && !first) { first = e; failed_at = ticks() - began; }
        if (joystick && (int16_t)(ticks() - next) >= 0) {
            ++reads;
            if (ti_joystick_read(&stick) != TI_OK) ++errors;
            next = ticks() + 3;
        }
    }
    at = put(at, " ");
    if (first) { at = put(at, error_name(first)); at = put(at, " AT "); at = seconds(at, failed_at); }
    else if (ti_speech_busy()) at = put(at, "STILL BUSY");
    else { at = put(at, "OK "); at = seconds(at, ticks() - began); }
    at = put(at, " SEEN "); at = num(at, seen);
    if (joystick) { at = put(at, " J"); at = num(at, reads); at = put(at, "/"); num(at, errors); }
    print();
    ti_audio_shutdown();
}
int main(void)
{
    uint8_t i, at;
    IO(0xC051) = 0; IO(0xC054) = 0; IO(0xC00C) = 0; IO(0xC000) = 0; IO(0xC00E) = 0;
    line[0] = 0;
    for (i = 0; i < 24; ++i) { row = i; print(); }
    row = 0;
    put(0, "LIBTINI SPEECH CHECK, SLOT 4"); print();
    put(0, "J = JOYSTICK READS/ERRORS"); print();
    row = 3;
    /* A counting VIA-B timer 2 moves within a few hundred reads. */
    IO(0xC488) = 255; IO(0xC489) = 255;
    for (i = 0; i < 200 && IO(0xC488) == 255 && IO(0xC489) == 255; ++i) {}
    at = put(0, "VIA-B T2 ");
    put(at, i < 200 ? "COUNTS" : "DOES NOT COUNT");
    print();
    raw_check();
    driver_check("MOCKINGBOARD", TI_AUDIO_MOCKINGBOARD, 0);
    driver_check("MB+JOYSTICK", TI_AUDIO_MOCKINGBOARD, 1);
    driver_check("PHASOR", TI_AUDIO_PHASOR, 0);
    driver_check("PH+JOYSTICK", TI_AUDIO_PHASOR, 1);
    ++row;
    put(0, "PRESS A KEY TO EXIT"); print();
    IO(0xC010) = 0;
    while (!(IO(0xC000) & 128)) {}
    IO(0xC010) = 0;
    return 0;
}
