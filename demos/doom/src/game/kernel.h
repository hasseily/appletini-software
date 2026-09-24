/* Doom for the Appletini -- the kernel as the GAME space's C code sees it
 * (docs/DESIGN.md sections 4, 8 and 10).
 *
 * The game runs in RamWorks bank 1 (the GAME space). The kernel lives in
 * the main language card, which both spaces see: the functions below go
 * through its jump table at $E000 (src/game/kglue.s), and `kin`, the input
 * block, is read directly. Level data, graphics and tables are in other
 * RamWorks banks: "far" memory, reached only through far_read/far_write/
 * far_copy (or far_peek for one byte). A transfer stays inside its bank's
 * $0200-$BFFF; far arrays are chunked so that none of their elements
 * crosses a bank (struct far_array).
 */
#ifndef KERNEL_H
#define KERNEL_H

/* A far address: bits 0-15 the address, bits 16-23 the bank. */
typedef unsigned long far_t;
#define FAR(bank, addr)  (((far_t)(unsigned char)(bank) << 16) | (unsigned int)(addr))
#define FAR_BANK(f)      ((unsigned char)((f) >> 16))
#define FAR_ADDR(f)      ((unsigned int)(f))

/* A far array: element i is in bank (bank + (i >> log2)) at
 * base + (i & ((1 << log2) - 1)) * size. 6 bytes, as the kernel reads it. */
struct far_array {
    unsigned char bank;
    unsigned int  base;
    unsigned int  size;
    unsigned char log2;
};

/* The input block (src/kernel/input.s). mouse_dx, newkey, weapon, flags
 * and the fire/use presses latched between tics are cleared after the
 * first tic of each rendered frame. */
struct kinput {
    int           mouse_dx;     /* mouse X motion since last taken */
    unsigned char buttons;      /* KB_* */
    unsigned char move;         /* KM_*, from the held key */
    unsigned char key;          /* the held key, upper case, 0 = none */
    unsigned char newkey;       /* the last key pressed (upper case), 0 = none */
    unsigned char weapon;       /* 1..7: a digit key was pressed, else 0 */
    unsigned char flags;        /* KF_* */
};
#define KB_FIRE     0x01        /* Open Apple, left mouse button */
#define KB_USE      0x02        /* Closed Apple, right mouse button */
#define KB_RUN      0x80        /* the run toggle (Tab) */
#define KM_FORWARD  0x01        /* up arrow, W */
#define KM_BACK     0x02        /* down arrow, S */
#define KM_LEFT     0x04        /* left arrow: turn */
#define KM_RIGHT    0x08        /* right arrow: turn */
#define KM_STRAFEL  0x10        /* A or , */
#define KM_STRAFER  0x20        /* D or . */
#define KF_MENU     0x01        /* Esc */
#define KEY_ESC     0x1B

extern struct kinput kin;
extern unsigned int ktics;          /* tics run since boot */
extern unsigned char kbanks;        /* RamWorks banks (64..128) */

void __fastcall__ far_read(far_t src, void *dst, unsigned int len);
void __fastcall__ far_write(const void *src, far_t dst, unsigned int len);
void __fastcall__ far_copy(far_t src, far_t dst, unsigned int len);
far_t __fastcall__ far_elem(const struct far_array *a, unsigned int index);
unsigned char __fastcall__ far_peek(far_t a);

void __fastcall__ set_palette(unsigned char n);     /* PLAYPAL 0..13 */
void kernel_reboot(void);
void __fastcall__ kernel_crash(unsigned char code);

/* called by the kernel */
void game_init(void);
void game_tic(void);
void game_frame(void);          /* once per rendered frame, after the tics */

#endif
