#include "appletini_http.h"
#include "http_client/libtini/net.h"
#include <conio.h>
#include <ctype.h>
#include <string.h>
static uint8_t reply[128];
static ti_net_status status;
static ti_net_chunk chunk;
static ti_net_request request={"GET",0,0,0,0,0};
static char content_type[128];
static const char *error;
/* The browser owns its near RAM. These stubs adapt the standalone MIT client
 * to cc65's Apple II startup, without the SDK's memory or audio modules. */
uint8_t ti_transfer_start;
uint8_t ti_near_valid(const void *p,uint16_t n,uint8_t write)
{
    uint16_t a=(uint16_t)p;
    (void)write;return a>=0x200&&a<0xC000&&n<=0xC000-a;
}
static uint8_t prefix(const char *s,const char *p)
{while(*p)if(tolower(*s++)!=*p++)return 0;return 1;}
static uint8_t text(uint8_t source,char *out,uint16_t length)
{
    uint16_t at=0;
    if(length>=128){error="Redirect URL or content type is too long";return 0;}
    while(at<length) {
        if(ti_net_read(source,at,reply,sizeof(reply),&chunk)||!chunk.length||
           chunk.state==TI_NET_SOURCE_FAILED||chunk.state==TI_NET_LOST||chunk.length>length-at) {
            error="Invalid metadata reply";return 0;
        }
        memcpy(out+at,chunk.data,chunk.length);at+=chunk.length;
    }
    out[at]=0;return 1;
}
static const char *failure(void)
{
    return status.result==-103?"Set the RTC and UTC offset":
                  status.result==-104?"HTTPS seed setup is required":
                  status.result==-105?"HTTPS trust roots are missing":
                  status.result==-9984?"Certificate verification failed":
                  status.result==TI_NET_RESULT_NETWORK_NOT_READY?"Network not ready; try again":
                  status.result==-106?"DNS lookup failed":
                  status.result==-107?"HTTP request timed out":
                  status.result==-110?"Ethernet or storage is busy":
                  "HTTP/S failed; check certificate, clock and network";
}
uint8_t appletini_http_probe(void){return ti_net_probe(reply)==TI_OK;}
const char *appletini_http_error(void){return error?error:"HTTP service failed";}
uint8_t appletini_http_fetch(char url[128],char *body,uint16_t capacity,
                            uint16_t *length,uint8_t *cut,uint8_t *plain)
{
    uint16_t at=0,n;
    uint8_t ok=0;
    error=0;*cut=*plain=0;*length=0;request.url=url;
    if(ti_net_start(&request)){error="Cannot start HTTP service";return 0;}
    for(;;) {
        if(kbhit()&&cgetc()==27){error="Request cancelled";break;}
        if(ti_net_poll(reply,&status)){error="HTTP service reply failed";break;}
        if(status.state==TI_NET_FAILED||status.state==TI_NET_CANCELLED) {
            error=failure();break;
        }
        if(ti_net_read(TI_NET_BODY,at,reply,sizeof(reply),&chunk)) {error="Body read failed";break;}
        if(chunk.state==TI_NET_SOURCE_FAILED) {
            /* The backend can fail between the descriptor poll and BODY read. */
            error=ti_net_poll(reply,&status)?"Body stream lost":failure();break;
        }
        if(chunk.state==TI_NET_LOST){error="Body stream lost";break;}
        n=chunk.length;if(n>capacity-at)n=capacity-at;
        memcpy(body+at,chunk.data,n);at+=n;
        if(n<chunk.length){*cut=1;break;}
        if(chunk.state==TI_NET_END)break;
    }
    if(!error) {
        if(ti_net_poll(reply,&status)||!text(TI_NET_URL,url,status.url_length)||
           !text(TI_NET_CONTENT_TYPE,content_type,status.content_type_length)) {
            if(!error)error="Metadata read failed";
        } else if(!prefix(content_type,"text/")&&!prefix(content_type,"application/xhtml+xml")) {
            error="This page has no supported text Content-Type";
        } else {
            *plain=!prefix(content_type,"text/html")&&!prefix(content_type,"application/xhtml+xml");
            body[at]=0;*length=at;ok=1;
        }
    }
    ti_net_cancel();return ok;
}
