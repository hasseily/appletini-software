/* SPDX-License-Identifier: MIT
 * A2LYNX's bounded libtini HTTP transport, adapted for binary body sinks. */
#include "mono_http.h"
#include "mono_mobile.h"
#include "mono_net.h"
#include "mono_gfx.h"
#include "http_client/libtini/net.h"
#include <conio.h>
#include <string.h>
#include <stdlib.h>

#pragma code-name ("NET")
#pragma rodata-name ("NET")

extern uint8_t mono_http_reply[512];
#define reply mono_http_reply
static ti_net_status status;
static ti_net_chunk chunk;
static ti_net_request request = {"GET", 0, mono_mobile_headers, 0, 0, 0, 0};
static const char *failure;
static char descriptor_failure[] = "HTTP descriptor E0";
char mono_http_type[64];
uint16_t mono_http_code, mono_http_length;
uint8_t mono_http_cut, ti_transfer_start;
uint8_t mono_http_transport_error, mono_http_card_error;
uint8_t mono_http_policy;
const char *mono_http_download_name;
char mono_http_message[192];

static uint8_t transport_error(uint8_t code)
{
    if (code && !mono_http_transport_error) {
        mono_http_transport_error = code;
        mono_http_card_error = ti_net_last_error();
        descriptor_failure[17] = (char)('0' + code);
        failure = descriptor_failure;
    }
    return code;
}

uint8_t ti_near_valid(const void *p, uint16_t n, uint8_t write)
{
    uint16_t a = (uint16_t)p;
    (void)write;
    return a >= 0x0800 && a < 0xBF00 && n <= 0xBF00 - a &&
           !(a < 0x6000 && a + n > 0x2000);
}
static const char *result_error(int16_t result)
{
    switch (result) {
    case -2: return "HTTP response limit; update Appletini firmware";
    case -103: return "Set Appletini RTC and UTC offset";
    case -104: return "HTTPS seed unavailable";
    case -105: return "HTTPS trust unavailable";
    /* Descriptor bytes 40..43 hold the firmware's TLS verification flags. */
    case -9984: return (reply[40]&8)?"TLS issuer untrusted; update CA bundle":
                                     "TLS certificate verification failed";
    case -111: return "Network not ready";
    case -106: return "DNS lookup failed";
    case -107: return "HTTP request timed out";
    case -110: return "Ethernet or storage is busy";
    default: return 0;
    }
}
static uint8_t metadata(uint8_t source, char *out, uint16_t n, uint16_t cap)
{
    uint16_t at = 0;
    if (n >= cap) { failure = "HTTP metadata too long"; return 0; }
    while (at < n) {
        if (ti_net_read(source, at, reply, sizeof(reply), &chunk) ||
            !chunk.length || chunk.length > n-at || chunk.state >= TI_NET_SOURCE_FAILED) {
            failure = "Invalid HTTP metadata"; return 0;
        }
        memcpy(out+at, chunk.data, chunk.length); at += chunk.length;
    }
    out[at] = 0;
    return 1;
}
uint8_t mono_http_probe(void) { return ti_net_probe(reply) == TI_OK; }
const char *mono_http_error(void) { return failure ? failure : "HTTP service unavailable"; }
static void progress(uint8_t cancelling)
{
    char *line=(char*)reply;
    uint8_t n;
    strcpy(line,cancelling?"Cancelling download":status.download_state==TI_NET_DL_WRITING?"Saving ":"Waiting for response");
    if(status.download_state==TI_NET_DL_WRITING && !cancelling) {
        ultoa(status.download_written,line+strlen(line),10);
        if(status.download_flags&1) {
            strcat(line,"/");ultoa(status.download_total,line+strlen(line),10);
        }
        strcat(line," bytes");
    }
    strcat(line," | ESC cancels");
    n=(uint8_t)strlen(line);while(n<80) line[n++]=' ';line[80]=0;
    mono_gfx_begin();mono_gfx_text(0,47,line,0);mono_gfx_commit();
}
uint8_t mono_http_get(char *url, uint16_t cap, mono_http_sink sink, uint16_t limit)
{
    uint16_t n;
    uint8_t stop = 0, ok = 0, cancelled=0, shown=255;
    uint32_t written=0xFFFFFFFFUL;
    failure = 0; mono_http_length = mono_http_code = 0; mono_http_cut = 0;
    mono_http_transport_error = mono_http_card_error = 0;
    mono_http_type[0] = 0;
    request.url = url;
    request.retain=mono_http_policy;request.download_name=mono_http_download_name;
    /* Reconcile a clean ARM session reset before a new request. Probe never
     * clears poison or writes to a channel with an abandoned transaction. */
    if (transport_error(ti_net_probe(reply))) {
        if (mono_http_transport_error == TI_E_IO) failure = "HTTP fault: restart browser";
        return 0;
    }
    if(mono_http_policy && !ti_net_download_capable()) {
        failure="Downloads need updated firmware";return mono_http_policy==4?MONO_HTTP_FILE_FAILED:0;
    }
    if (ti_net_start(&request)) { failure = "Cannot start HTTP"; return 0; }
    for (;;) {
        if (!cancelled && kbhit() && cgetc() == 27) {
            failure="Request cancelled";
            if(!mono_http_policy || transport_error(ti_net_cancel())) break;
            cancelled=1;shown=255;
        }
        if (transport_error(ti_net_poll(reply, &status))) break;
        /* File terminal states precede NET_FAILED/CANCELLED: never replace
         * the page with the raw body or a generic service error. */
        if(status.download_state==TI_NET_DL_DONE) {
            if(metadata(TI_NET_DOWNLOAD_PATH,mono_http_message+6,status.download_path_length,
                        sizeof(mono_http_message)-6)) {
                memcpy(mono_http_message,"Saved ",6);failure=mono_http_message;ok=MONO_HTTP_SAVED;
            } else ok=MONO_HTTP_FILE_FAILED;
            break;
        }
        if(status.download_state==TI_NET_DL_FAILED) {
            /* AUTO also waits here while a normal page is connecting. Report
             * TLS/DNS errors as request failures, before any file exists. */
            failure=result_error(status.download_result);
            if(!failure) {
                strcpy(mono_http_message,"Download failed: ");
                itoa(status.download_result,mono_http_message+strlen(mono_http_message),10);
                failure=mono_http_message;
            }
            ok=MONO_HTTP_FILE_FAILED;break;
        }
        if(status.download_state==TI_NET_DL_CANCELLED) {
            failure="Download cancelled";ok=MONO_HTTP_FILE_CANCELLED;break;
        }
        if(status.download_state==TI_NET_DL_WAITING || status.download_state==TI_NET_DL_WRITING) {
            if(shown!=status.download_state || written!=status.download_written) {
                progress(cancelled);shown=status.download_state;written=status.download_written;
            }
            continue;
        }
        if (status.state == TI_NET_FAILED || status.state == TI_NET_CANCELLED) {
            failure = result_error(status.result);
            if(!failure) failure="HTTP/S service failed";
            break;
        }
        mono_http_code = status.http_status;
        /* The ARM discards redirect bodies and follows up to three hops.
         * Its parser exposes each 3xx while the same request stays ACTIVE.
         * Do not reject or read that intermediate response. A terminal 3xx
         * still fails below, including a redirect without a usable target. */
        if (mono_http_code >= 300 && mono_http_code < 400 &&
            status.state == TI_NET_ACTIVE) continue;
        if (mono_http_code && (mono_http_code < 200 || mono_http_code >= 300)) {
            failure = "Server returned an HTTP error"; break;
        }
        if(mono_http_policy==TI_NET_FORCE_DOWNLOAD && mono_http_code) {
            failure="Server did not start download";ok=MONO_HTTP_FILE_FAILED;break;
        }
        if (ti_net_read(TI_NET_BODY, mono_http_length, reply, sizeof(reply), &chunk)) {
            failure = "HTTP body read failed"; break;
        }
        if (chunk.state >= TI_NET_SOURCE_FAILED) {
            failure = "HTTP body stream failed"; break;
        }
        n = chunk.length;
        if (n > limit - mono_http_length) { n = limit - mono_http_length; mono_http_cut = 1; }
        if (n) stop = sink(chunk.data, n);
        mono_http_length += n;
        if (stop == 2) { failure = "Response body rejected"; break; }
        if (stop || mono_http_cut || chunk.state == TI_NET_END) { ok = 1; break; }
        if (mono_http_length == limit) {
            /* Read one more descriptor/body to distinguish exact fit from truncation. */
            if (status.state == TI_NET_DONE && status.body_length == mono_http_length) { ok = 1; break; }
        }
    }
    if (ok==MONO_HTTP_BODY) {
        if (transport_error(ti_net_poll(reply, &status))) ok = 0;
        else if (status.state == TI_NET_FAILED || status.state == TI_NET_CANCELLED)
            { failure = "HTTP completion failed"; ok = 0; }
        else if (!metadata(TI_NET_URL, url, status.url_length, cap) ||
                 !metadata(TI_NET_CONTENT_TYPE, mono_http_type, status.content_type_length,
                           sizeof(mono_http_type))) ok = 0;
    }
    if(!cancelled && transport_error(ti_net_cancel())) ok=0;
    return !ok && mono_http_policy==TI_NET_FORCE_DOWNLOAD?MONO_HTTP_FILE_FAILED:ok;
}
