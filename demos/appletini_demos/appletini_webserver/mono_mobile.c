/* SPDX-License-Identifier: MIT */
#include "mono_mobile.h"
#pragma rodata-name("LC")

/* Ask for a mobile page and less data. Sites may ignore these preferences.
 * Keep this resident while WEB, GIF, PNG and JPEG overlays replace each other. */
const char mono_mobile_headers[] =
    "User-Agent: Mozilla/5.0 (Mobile; APPLE2LYNX/1)\r\n"
    "Sec-CH-UA-Mobile: ?1\r\n"
    "Save-Data: on\r\n";
