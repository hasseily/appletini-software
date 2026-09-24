/* Doom for the Appletini -- the kernel as the game sees it, on the host
 * (tests/host/: the game's C compiled by gcc for the logic tests).
 *
 * Same declarations as src/game/kernel.h, served by host.c: far memory is
 * a 128-bank array the test fills from the converter's data files
 * (tools/wad2a2.py load_banks), the input block is a plain struct the test
 * sets, kernel_crash records its code and stops the tic with longjmp.
 * This directory comes before src/game on the host include path.
 */
#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

typedef unsigned long far_t;
#define FAR(bank, addr)  (((far_t)(uint8_t)(bank) << 16) | (uint16_t)(addr))
#define FAR_BANK(f)      ((uint8_t)((f) >> 16))
#define FAR_ADDR(f)      ((uint16_t)(f))

struct far_array {
    uint8_t  bank;
    uint16_t base;
    uint16_t size;
    uint8_t  log2;
};

struct kinput {
    int16_t mouse_dx;
    uint8_t buttons, move, key, newkey, weapon, flags;
};
#define KB_FIRE     0x01
#define KB_USE      0x02
#define KB_RUN      0x80
#define KM_FORWARD  0x01
#define KM_BACK     0x02
#define KM_LEFT     0x04
#define KM_RIGHT    0x08
#define KM_STRAFEL  0x10
#define KM_STRAFER  0x20
#define KF_MENU     0x01
#define KEY_ESC     0x1B

extern struct kinput kin;
extern uint16_t ktics;
extern uint8_t kbanks;

void far_read(far_t src, void *dst, unsigned int len);
void far_write(const void *src, far_t dst, unsigned int len);
void far_copy(far_t src, far_t dst, unsigned int len);
far_t far_elem(const struct far_array *a, unsigned int index);
unsigned char far_peek(far_t a);
void set_palette(unsigned char n);
void kernel_reboot(void);
void kernel_crash(unsigned char code);

void game_init(void);
void game_tic(void);
void game_frame(void);

#endif
