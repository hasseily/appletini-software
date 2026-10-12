/* Regression for v1.5's keyboard identity probe followed by raw input. */
#include "adb.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    adb a;
    adb_init(&a, 0);
    adb_key(&a, 0x24, 1);
    adb_key(&a, 0x24, 0);
    adb_write(&a, 0x26, 0xf2, 0);
    assert(!(adb_read(&a, 0x27, 0) & ADB_DATA_FULL));
    assert(adb_read(&a, 0x27, 71591) & ADB_DATA_FULL);
    assert(adb_read(&a, 0x26, 71591) == 0x81);
    assert(adb_read(&a, 0x26, 71591) == 0x62);
    assert(adb_read(&a, 0x26, 71591) == 0x02);
    assert(a.key_count == 2);
    assert(!(adb_read(&a, 0x27, 71591) & ADB_DATA_FULL));
    adb_write(&a, 0x26, 0xc2, 71591);
    assert(adb_read(&a, 0x26, 143182) == 0x81);
    assert(adb_read(&a, 0x26, 143182) == 0x24);
    assert(adb_read(&a, 0x26, 143182) == 0xa4);
    adb_write(&a, 0x26, 0xc2, 143182);
    assert(adb_read(&a, 0x26, 214773) == 0x80);
    assert(a.unknown_commands == 0);
    puts("PASS: delayed keyboard identity, preserved key events, empty reply");
    return 0;
}
