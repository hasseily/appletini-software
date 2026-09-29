/*
 * The ADB microcontroller of the Apple IIgs, as far as the game uses it:
 * $C026 (commands in, bytes out), $C027 (status and interrupt enables)
 * and $C024 (mouse reports).
 *
 * The game turns off the controller's polling of the keyboard (command
 * $04 with mode bit 0) and enables service requests from address 2
 * (command $52). When the keyboard holds key bytes, the controller sends
 * a byte with bit 3 set; the game answers with Talk register 0 of
 * address 2 (command $C2), and after the bus time of the Talk the
 * controller sends $81 and the two key bytes of the register, or $80
 * when the keyboard had none. A key byte is bit 7 set for a release and
 * the ADB key code in bits 0-6; $FF fills the second byte.
 *
 * The controller polls the mouse; a report with motion or a button
 * change sets bit 7 of $C027 and gives the X byte then the Y byte at
 * $C024 (bit 7 of X: button 1 up, of Y: button 0 up; bits 0-6 the
 * signed move).
 *
 * Time is in master clocks of the IIgs, as in doc.h. Key bytes that
 * arrive while the controller still polls the keyboard itself wait: the
 * model has no path to the $C000 keyboard register, which the game does
 * not read.
 */
#ifndef ADB_H
#define ADB_H

#include <stdint.h>

enum {
    ADB_KEY_QUEUE = 64,
    ADB_OUT_QUEUE = 16,
    /* $C027: status bits and the interrupt enables the game writes. */
    ADB_MOUSE_FULL = 0x80, ADB_MOUSE_IRQ = 0x40, ADB_DATA_FULL = 0x20,
    ADB_DATA_IRQ = 0x10, ADB_KEY_IRQ = 0x04, ADB_MOUSE_Y_NEXT = 0x02
};

typedef struct {
    /* bytes from the controller, read at $C026 */
    uint8_t out[ADB_OUT_QUEUE];
    unsigned out_head, out_count;
    uint8_t out_last;

    /* a command being received: its first byte, the data still due */
    uint8_t command, data_due, data[4], data_count;

    uint8_t modes;              /* bit 0: the keyboard is not polled */
    uint8_t srq_enabled;        /* a bit for each ADB address */
    uint8_t enables;            /* the writable bits of $C027 */

    uint8_t keys[ADB_KEY_QUEUE];
    unsigned key_head, key_count;
    int srq_out;                /* a service request not yet answered */
    int talk_due;               /* a Talk to the keyboard is on the bus */
    uint64_t talk_time;         /* when its answer comes */

    int mouse_dx, mouse_dy;     /* motion not yet reported */
    uint8_t buttons;            /* bit 0: button 0 down, bit 1: button 1 */
    uint8_t reported_buttons;
    uint8_t mouse_x, mouse_y;   /* the report in $C024 */
    int mouse_full, mouse_y_next;
    uint8_t mouse_last;

    uint64_t next_poll;

    /* commands the model does not implement, and resets asked for */
    unsigned unknown_commands;
    uint8_t last_unknown;
    unsigned system_resets;
} adb;

void adb_init(adb *a, uint64_t now);

/* The polls and Talk answers due at or before master clock `now`. */
void adb_run(adb *a, uint64_t now);

/* The master clock of the next poll or answer. */
uint64_t adb_next_event(const adb *a);

/* $C024, $C026 and $C027, by the low byte of the address. */
uint8_t adb_read(adb *a, uint8_t reg, uint64_t now);
void adb_write(adb *a, uint8_t reg, uint8_t value, uint64_t now);

/* The controller's interrupt: a byte or a mouse report with its enable. */
int adb_irq(const adb *a);

/* Input from a script: a key pressed or released (ADB key code 0-127),
   mouse motion, a mouse button (0 or 1) pressed or released. */
void adb_key(adb *a, uint8_t code, int down);
void adb_mouse_move(adb *a, int dx, int dy);
void adb_mouse_button(adb *a, int button, int down);

#endif
