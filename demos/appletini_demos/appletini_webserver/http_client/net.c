#include "internal.h"
#include "libtini/net.h"
#include <string.h>
#ifdef MONO_NET_OVERLAY
#pragma code-name ("NET")
#pragma rodata-name ("NET")
#endif
/* Assembly fixes these two bytes in startup-cleared NEARBSS. cc65 applies
 * the later bss-name pragma to earlier tentative C definitions too. */
extern uint8_t ti_net_poisoned, ti_net_ready;
#define ready ti_net_ready
#pragma bss-name ("BSS")
uint8_t ti_net_parameters[10], ti_net_tx_count, ti_net_rc;
const uint8_t *ti_net_tx[7];
uint16_t ti_net_tx_length[7], ti_net_rx_capacity, ti_net_rx_length;
uint8_t *ti_net_rx;
static uint8_t generation, header[14];
static uint32_t via_hz;
static uint8_t capabilities;
extern uint8_t ti_transfer_start;
void ti_net_exchange(void);
void ti_net_lock(void);
void ti_net_unlock(void);
uint16_t ti_net_rom_crc(void);
static uint16_t get16(const uint8_t *p) {return p[0]|((uint16_t)p[1]<<8);}
static uint32_t get32(const uint8_t *p) {return get16(p)|((uint32_t)get16(p+2)<<16);}
static void put16(uint8_t *p,uint16_t n) {p[0]=(uint8_t)n;p[1]=(uint8_t)(n>>8);}
static uint8_t writable(void *p,uint16_t n)
{
    uint16_t a=(uint16_t)p,b=(uint16_t)&ti_transfer_start;
    return p && (ti_near_valid(p,n,1)||(a>=b&&a-b<128&&n<=128-(a-b)));
}
static void parameters(uint8_t op,uint8_t selector)
{
    memset(ti_net_parameters,0,10);
    ti_net_parameters[0]=op;ti_net_parameters[1]=3;ti_net_parameters[5]=selector;
    ti_net_tx[0]=ti_net_parameters;ti_net_tx_length[0]=10;ti_net_tx_count=1;
    ti_net_rc=0;ti_net_rx_length=0;
}
static ti_error exchange(void)
{
    if(ti_net_poisoned)return TI_E_IO;
    ti_net_exchange();
    if(ti_net_poisoned)return TI_E_IO;
    if(ti_net_rc==0x21||ti_net_rc==0x60||ti_net_rc==0x66)return TI_E_UNAVAILABLE;
    if(ti_net_rc==0x2F)return TI_E_BUSY;
    return ti_net_rc?TI_E_IO:TI_OK;
}
static ti_error descriptor(uint8_t *p)
{
    ti_error e;
    parameters(0,0x82);ti_net_rx=p;ti_net_rx_capacity=64;e=exchange();
    if(e)return e;
    if(ti_net_rx_length!=64||memcmp(p,"ATNH",4)||p[4]!=1||p[5]!=64||(p[6]&15)!=15)
        return TI_E_UNAVAILABLE;
    via_hz=get32(p+44);capabilities=p[6];return TI_OK;
}
ti_error ti_net_probe(void *reply)
{
    uint16_t crc;
    ti_error e;
    if(!writable(reply,64))return TI_E_ARGUMENT;
    if(ti_net_poisoned)return TI_E_IO;
    ready=0;via_hz=0;
    ti_net_lock();
    crc=ti_net_rom_crc();
    ti_net_unlock();
    if(crc!=0x95D9)return TI_E_UNAVAILABLE;
    e=descriptor(reply);
    if(!e){generation=((uint8_t *)reply)[7];ready=1;}
    return e;
}
static ti_error control(uint8_t op,uint16_t length)
{
    ti_error e;
    put16(header,length);header[2]=1;header[3]=op;
    ti_net_tx[1]=header;ti_net_tx_length[1]=14;
    ti_net_rx_capacity=0;e=exchange();return e;
}
static ti_error unavailable(void)
{return ti_net_poisoned?TI_E_IO:TI_E_UNAVAILABLE;}

ti_error ti_net_start(const ti_net_request *r)
{
    uint16_t m,u,h,d,total;
    ti_error e;
    if(!ready)return unavailable();
    if(!r||!r->method||!r->url||(r->retain&~7U)||
       ((r->retain&1U)&&(r->retain&6U))||(!r->body&&r->body_length))return TI_E_ARGUMENT;
    if((r->retain&6U)&&!(capabilities&16U))return TI_E_UNAVAILABLE;
    if((r->retain&4U)&&(strcmp(r->method,"GET")||r->body_length))return TI_E_ARGUMENT;
    m=strlen(r->method);u=strlen(r->url);h=r->headers?strlen(r->headers):0;
    d=r->download_name?strlen(r->download_name):0;
    if(!m||m>15||!u||u>1000||h>1000||r->body_length>1000||d>127)return TI_E_RANGE;
    if(d&&!(r->retain&4U))return TI_E_ARGUMENT;
    total=12+m+u+h+r->body_length+d;if(total>1012)return TI_E_FULL;
    parameters(4,0x82);memset(header,0,14);header[4]=r->retain;header[5]=(uint8_t)m;
    put16(header+6,u);put16(header+8,h);put16(header+10,r->body_length);
    put16(header+12,d);
    ti_net_tx[2]=(const uint8_t *)r->method;ti_net_tx_length[2]=m;
    ti_net_tx[3]=(const uint8_t *)r->url;ti_net_tx_length[3]=u;
    ti_net_tx[4]=(const uint8_t *)r->headers;ti_net_tx_length[4]=h;
    ti_net_tx[5]=r->body;ti_net_tx_length[5]=r->body_length;
    ti_net_tx[6]=(const uint8_t *)r->download_name;ti_net_tx_length[6]=d;ti_net_tx_count=7;
    e=control(1,total);if(!e&&!++generation)++generation;return e;
}
ti_error ti_net_poll(void *reply,ti_net_status *out)
{
    uint8_t *p=reply;
    ti_error e;
    if(!ready)return unavailable();
    if(!out||!writable(reply,64))return TI_E_ARGUMENT;
    e=descriptor(p);if(e)return e;
    if(p[7]!=generation)return TI_E_HANDLE;
    out->generation=p[7];out->state=p[8];out->retained=p[9];out->result=(int16_t)get16(p+10);
    out->http_status=get16(p+12);out->json_state=p[14];out->json_type=p[15];
    out->body_length=get32(p+16);out->buffered=get32(p+20);out->value_length=get32(p+24);
    out->url_length=get16(p+28);out->content_type_length=get16(p+30);
    out->download_state=p[48];out->download_flags=p[49];out->download_result=(int16_t)get16(p+50);
    out->download_written=get32(p+52);out->download_total=get32(p+56);
    out->download_path_length=get16(p+60);return TI_OK;
}
ti_error ti_net_read(uint8_t source,uint16_t offset,void *reply,uint16_t capacity,ti_net_chunk *out)
{
    uint8_t *p=reply;
    ti_error e;
    if(!ready)return unavailable();
    if(!out||source<0x83||source>0x87||capacity<9||capacity>512||!writable(reply,capacity))return TI_E_ARGUMENT;
    parameters(0,source);put16(ti_net_parameters+6,offset);put16(ti_net_parameters+8,capacity);
    ti_net_rx=reply;ti_net_rx_capacity=capacity;e=exchange();if(e)return e;
    if(ti_net_rx_length<8||get16(p+6)!=ti_net_rx_length-8||get32(p+2)!=offset||p[1]<1||p[1]>4)return TI_E_FORMAT;
    if(p[0]!=generation)return TI_E_HANDLE;
    out->state=p[1];out->length=get16(p+6);out->data=p+8;return TI_OK;
}
ti_error ti_net_json(const char *pointer)
{
    uint16_t n;
    if(!ready)return unavailable();
    if(!pointer)return TI_E_ARGUMENT;
    n=strlen(pointer);if(n>1000)return TI_E_RANGE;
    parameters(4,0x82);memset(header,0,14);put16(header+6,n);
    ti_net_tx[2]=(const uint8_t *)pointer;ti_net_tx_length[2]=n;ti_net_tx_count=3;
    return control(3,12+n);
}
ti_error ti_net_cancel(void)
{
    if(!ready)return unavailable();
    parameters(4,0x82);memset(header,0,14);ti_net_tx_count=2;return control(2,12);
}
uint8_t ti_net_available(void){return ready&&!ti_net_poisoned;}
uint8_t ti_net_last_error(void){return ti_net_rc;}
uint32_t ti_net_via_hz(void){return ready?via_hz:0;}
uint8_t ti_net_download_capable(void){return (capabilities&16U)!=0;}
