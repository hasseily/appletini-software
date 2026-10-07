/*
 * The ProDOS 8 MLI stand-in of a2vm: the calls, files and error codes of
 * a2sim.py's FakeProDOS (the earlier Appletini Doom port's Python
 * model), so that a run of that port's DOOM.SYSTEM loader on a2vm
 * matched one on a2sim.py.
 *
 * Every file lives in the volume directory. OPEN of the volume directory
 * reads real ProDOS directory blocks, built the way the earlier port's
 * build_disk.py laid out its disks (as FakeProDOS did). Files written by the program stay in memory.
 *
 * The calls read and write main memory only, whatever the soft switches
 * say, as FakeProDOS does. How the call is reached (the JSR $BF00 trap)
 * is the machine's part (a2vm.c).
 */
#ifndef A2VM_PRODOS_H
#define A2VM_PRODOS_H

#include <stddef.h>
#include <stdint.h>

enum {
    PRODOS_MAX_OPEN = 8,
    PRODOS_E_BADCALL = 0x01, PRODOS_E_BADPATH = 0x40,
    PRODOS_E_TOOMANY = 0x42, PRODOS_E_BADREF = 0x43,
    PRODOS_E_NOPATH = 0x44, PRODOS_E_NOVOL = 0x45, PRODOS_E_NOFILE = 0x46,
    PRODOS_E_DUP = 0x47, PRODOS_E_ACCESS = 0x4E, PRODOS_E_EOF = 0x4C,
    PRODOS_E_POSITION = 0x4D,
    PRODOS_QUIT = -1,               /* prodos_call's result for QUIT */
    PRODOS_FAULT = -2               /* a2sim.py would have raised */
};

typedef struct {
    uint8_t *data;
    size_t length, capacity;
} prodos_buffer;

typedef struct {
    char name[17];
    uint8_t type;
    uint16_t aux;
    int live;                       /* 0 once destroyed */
    prodos_buffer buffer;
} prodos_file;

typedef struct {
    int used;
    int file;                       /* index in files, -1 the directory */
    prodos_buffer *buffer;          /* the file's, or `directory` */
    prodos_buffer directory;
    uint64_t pos;
    int dirty;
} prodos_open;

typedef struct a2vm_prodos {
    char volume[16];
    char prefix[20];
    char launched[64];
    prodos_file *files;             /* in the order of FakeProDOS's dict */
    size_t file_count, file_capacity;
    prodos_open open[PRODOS_MAX_OPEN + 1];  /* by reference number */
    uint8_t open_order[PRODOS_MAX_OPEN];    /* the dict's order of refs */
    unsigned open_count;
    int quit;
    uint64_t calls;
    uint32_t calls_crc;             /* CRC-32 of the (number, error) bytes */
    char fault[200];                /* why PRODOS_FAULT */
} a2vm_prodos;

a2vm_prodos *prodos_new(const char *volume, const char *launched);
void prodos_free(a2vm_prodos *p);

/* FakeProDOS.add: 0 and a message in `error` when the name is not a
   ProDOS name. */
int prodos_add(a2vm_prodos *p, const char *name, uint8_t type, uint16_t aux,
               const uint8_t *data, size_t length, char *error,
               size_t error_size);

/* Service call `number` with its parameter block at `parms` in `main`
   (64 KB). Returns the error code (0 on success), PRODOS_QUIT, or
   PRODOS_FAULT when FakeProDOS would have raised an exception (the
   reason in p->fault). Logs the call as FakeProDOS.calls does. */
int prodos_call(a2vm_prodos *p, uint8_t *main, uint8_t number,
                uint16_t parms);

/* The volume directory blocks FakeProDOS.directory_blocks gives (2048
   bytes, blocks 2-5). 0 and p->fault when build_disk would refuse. */
int prodos_directory(a2vm_prodos *p, prodos_buffer *out);

/* The path FakeProDOS.attach writes at $0280 (length byte first). */
size_t prodos_launch_path(const a2vm_prodos *p, uint8_t *out, size_t size);

uint32_t a2vm_crc32(uint32_t crc, const uint8_t *data, size_t length);

#endif
