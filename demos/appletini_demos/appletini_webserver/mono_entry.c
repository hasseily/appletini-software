/* SPDX-License-Identifier: MIT */
#include "mono_media.h"
#include <conio.h>
extern int mono_browser_main(void);
void mono_prefix_init(void);
int main(void)
{
    mono_prefix_init();
    if (!mono_overlay("MONO.WEB")) {
        cputs("A2MONO: cannot load MONO.WEB\r\n");
        cputs(mono_media_message); cputs("\r\nPress a key."); cgetc();
        return 1;
    }
    mono_media_init();
    return mono_browser_main();
}
