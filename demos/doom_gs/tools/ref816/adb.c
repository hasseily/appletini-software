/*
 * ADB microcontroller: see adb.h.
 *
 * Timing: the controller polls every ADB_POLL master clocks (11 ms, the
 * period of its automatic poll) and answers a Talk ADB_TALK master
 * clocks after the command (the 5 ms of bus time that the game's
 * comments give). Commands are taken at once, so bit 0 of $C027 (the
 * command register is full) never reads 1.
 */
#include "adb.h"

#include <string.h>

enum {
    ADB_POLL = 157500,          /* 11.0 ms of 14.31818 MHz */
    ADB_TALK = 71591,           /* 5.0 ms */
    KEYBOARD = 2,               /* the ADB address of the keyboard */
    MODE_NO_KEYBOARD_POLL = 0x01,
    SRQ_BYTE = 0x08,            /* a service request of the keyboard */
    ANSWER = 0x80,              /* bits 0-2: the bytes that follow - 1 */
    NO_KEY = 0xff,
    MOUSE_MOVE_LIMIT = 63
};

enum {
    CMD_ABORT = 0x01, CMD_SET_MODES = 0x04, CMD_CLEAR_MODES = 0x05,
    CMD_RESET_SYSTEM = 0x10, CMD_SRQ_ON = 0x50, CMD_SRQ_OFF = 0x70,
    CMD_TALK = 0xc0
};

void adb_init(adb *a, uint64_t now)
{
    memset(a, 0, sizeof *a);
    a->next_poll = now + ADB_POLL;
}

static void send(adb *a, uint8_t byte)
{
    if (a->out_count == ADB_OUT_QUEUE)
        return;                 /* the controller's buffer is full */
    a->out[(a->out_head + a->out_count) % ADB_OUT_QUEUE] = byte;
    a->out_count++;
}

static int keyboard_requests(const adb *a)
{
    return (a->modes & MODE_NO_KEYBOARD_POLL) &&
           (a->srq_enabled & 1u << KEYBOARD) && a->key_count &&
           !a->srq_out && !a->talk_due;
}

static uint8_t take_key(adb *a)
{
    if (!a->key_count)
        return NO_KEY;
    uint8_t key = a->keys[a->key_head];
    a->key_head = (a->key_head + 1) % ADB_KEY_QUEUE;
    a->key_count--;
    return key;
}

static void answer_talk(adb *a)
{
    a->talk_due = 0;
    a->srq_out = 0;
    if (!a->key_count) {
        send(a, ANSWER);
        return;
    }
    uint8_t first = take_key(a);
    uint8_t second = take_key(a);
    send(a, ANSWER | 1);
    send(a, first);
    send(a, second);
}

static int clamp(int value)
{
    if (value > MOUSE_MOVE_LIMIT)
        return MOUSE_MOVE_LIMIT;
    if (value < -MOUSE_MOVE_LIMIT)
        return -MOUSE_MOVE_LIMIT;
    return value;
}

static void mouse_report(adb *a)
{
    int dx = clamp(a->mouse_dx), dy = clamp(a->mouse_dy);
    a->mouse_dx -= dx;
    a->mouse_dy -= dy;
    a->reported_buttons = a->buttons;
    a->mouse_x = (uint8_t)((dx & 0x7f) | (a->buttons & 2 ? 0 : 0x80));
    a->mouse_y = (uint8_t)((dy & 0x7f) | (a->buttons & 1 ? 0 : 0x80));
    a->mouse_full = 1;
    a->mouse_y_next = 0;
}

static void poll(adb *a)
{
    if (!a->mouse_full && (a->mouse_dx || a->mouse_dy ||
                           a->buttons != a->reported_buttons))
        mouse_report(a);
    if (keyboard_requests(a)) {
        send(a, SRQ_BYTE);
        a->srq_out = 1;
    }
}

void adb_run(adb *a, uint64_t now)
{
    for (;;) {
        uint64_t next = adb_next_event(a);
        if (next > now)
            return;
        if (a->talk_due && a->talk_time == next)
            answer_talk(a);
        else {
            poll(a);
            a->next_poll += ADB_POLL;
        }
    }
}

uint64_t adb_next_event(const adb *a)
{
    if (a->talk_due && a->talk_time < a->next_poll)
        return a->talk_time;
    return a->next_poll;
}

int adb_irq(const adb *a)
{
    return ((a->enables & ADB_DATA_IRQ) && a->out_count) ||
           ((a->enables & ADB_MOUSE_IRQ) && a->mouse_full);
}

/* The number of data bytes that follow a command byte. */
static uint8_t data_bytes(uint8_t command)
{
    if (command == CMD_SET_MODES || command == CMD_CLEAR_MODES)
        return 1;
    return 0;
}

static void execute(adb *a, uint64_t now)
{
    uint8_t command = a->command;
    if (command == CMD_SET_MODES)
        a->modes |= a->data[0];
    else if (command == CMD_CLEAR_MODES)
        a->modes &= (uint8_t)~a->data[0];
    else if (command == CMD_ABORT)
        a->data_due = 0;
    else if (command == CMD_RESET_SYSTEM)
        a->system_resets++;
    else if ((command & 0xf0) == CMD_SRQ_ON)
        a->srq_enabled |= (uint8_t)(1u << (command & 0x0f));
    else if ((command & 0xf0) == CMD_SRQ_OFF)
        a->srq_enabled &= (uint8_t)~(1u << (command & 0x0f));
    else if (command == (CMD_TALK | KEYBOARD)) {
        /* In the controller's command set $Cx is Talk register 0 of
           address x. */
        a->talk_due = 1;
        a->talk_time = now + ADB_TALK;
    } else {
        a->unknown_commands++;
        a->last_unknown = command;
    }
}

static void command_byte(adb *a, uint8_t value, uint64_t now)
{
    if (a->data_due) {
        a->data[a->data_count++] = value;
        if (--a->data_due == 0)
            execute(a, now);
        return;
    }
    a->command = value;
    a->data_count = 0;
    a->data_due = data_bytes(value);
    if (!a->data_due)
        execute(a, now);
}

uint8_t adb_read(adb *a, uint8_t reg, uint64_t now)
{
    adb_run(a, now);
    switch (reg) {
    case 0x24:
        if (!a->mouse_full)
            return a->mouse_last;
        if (!a->mouse_y_next) {
            a->mouse_y_next = 1;
            a->mouse_last = a->mouse_x;
        } else {
            a->mouse_y_next = 0;
            a->mouse_full = 0;
            a->mouse_last = a->mouse_y;
        }
        return a->mouse_last;
    case 0x26:
        if (a->out_count) {
            a->out_last = a->out[a->out_head];
            a->out_head = (a->out_head + 1) % ADB_OUT_QUEUE;
            a->out_count--;
        }
        return a->out_last;
    default:
        return (uint8_t)((a->mouse_full ? ADB_MOUSE_FULL : 0) |
                         (a->out_count ? ADB_DATA_FULL : 0) |
                         (a->mouse_y_next ? ADB_MOUSE_Y_NEXT : 0) |
                         a->enables);
    }
}

void adb_write(adb *a, uint8_t reg, uint8_t value, uint64_t now)
{
    adb_run(a, now);
    if (reg == 0x26)
        command_byte(a, value, now);
    else if (reg == 0x27)
        a->enables = value & (ADB_MOUSE_IRQ | ADB_DATA_IRQ | ADB_KEY_IRQ);
}

void adb_key(adb *a, uint8_t code, int down)
{
    if (a->key_count == ADB_KEY_QUEUE)
        return;                 /* the keyboard's buffer is full */
    a->keys[(a->key_head + a->key_count) % ADB_KEY_QUEUE] =
        (uint8_t)((code & 0x7f) | (down ? 0 : 0x80));
    a->key_count++;
}

void adb_mouse_move(adb *a, int dx, int dy)
{
    a->mouse_dx += dx;
    a->mouse_dy += dy;
}

void adb_mouse_button(adb *a, int button, int down)
{
    uint8_t bit = (uint8_t)(button ? 2 : 1);
    if (down)
        a->buttons |= bit;
    else
        a->buttons &= (uint8_t)~bit;
}
