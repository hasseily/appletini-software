/* SPDX-License-Identifier: MIT
 * Focused real-6502 HTTP/FIFO harness, executed by mono_http_redirect.py. */
#include "../mono_http.h"
#include "../mono_gfx.h"
#include <string.h>

char test_url[256] = "https://start.test/old/page";
unsigned char test_body[32], test_length, test_result;
const char *test_error;

unsigned char kbhit(void) { return 0; }
char cgetc(void) { return 27; }
void mono_gfx_begin(void) { }
void mono_gfx_commit(void) { }
void mono_gfx_text(unsigned char column, unsigned char row, const char *text,
                   unsigned char inverse)
{ (void)column; (void)row; (void)text; (void)inverse; }

static unsigned char sink(const unsigned char *data, unsigned int length)
{
    if (length > sizeof(test_body) - test_length) return 2;
    memcpy(test_body + test_length, data, length);
    test_length += length;
    return 0;
}

int main(void)
{
    if (!mono_http_probe()) { test_result = 3; return 0; }
    test_result = mono_http_get(test_url, sizeof(test_url), sink, sizeof(test_body));
    test_error = mono_http_error();
    return 0;
}
