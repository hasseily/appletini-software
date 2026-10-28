/* Repeated HTTPS/JSON example. Host checks can set the exported URL, method,
 * pointer, retain flag and go byte. The program uses the actual SDK path. */
#include "libtini.h"
#include <string.h>
volatile uint8_t netcheck_phase,netcheck_error,netcheck_go;
volatile uint16_t netcheck_http,netcheck_bytes;
volatile int16_t netcheck_result;
volatile uint8_t netcheck_retain=1;
char netcheck_url[128]="https://httpbin.org/anything";
char netcheck_method[8]="POST";
char netcheck_pointer[128]="/json/message";
static uint8_t reply[128],key;
static ti_net_request request={netcheck_method,netcheck_url,"Content-Type: application/json\r\n","{\"message\":\"hello from libtini\"}",0,1};
static ti_net_status status;
static ti_net_chunk chunk;
static uint16_t offset;
static void title(void)
{
    static const char message[]="HTTP/S + JSON   KEY: RUN   Q: QUIT";
    uint8_t i;volatile uint8_t *text=(volatile uint8_t *)0x400;
    for(i=0;i<sizeof(message)-1;++i)text[i]=message[i]|0x80;
}
int main(void)
{
    title();
    for(;;) {
        while(!netcheck_go) {
            ti_input_poll();
            if(ti_input_key(&key)==TI_OK){if(key=='Q'||key=='q')return 0;netcheck_go=1;}
        }
        key=0;netcheck_phase=1;netcheck_error=ti_net_probe(reply);
        netcheck_http=netcheck_bytes=offset=0;netcheck_result=0;
        if(!netcheck_error) {
            request.body_length=!strcmp(netcheck_method,"POST")?strlen(request.body):0;
            request.retain=netcheck_retain;netcheck_phase=2;
            netcheck_error=ti_net_start(&request);
        }
        while(!netcheck_error) {
            ti_input_poll();
            if(ti_input_key(&key)==TI_OK&&(key=='Q'||key=='q')){ti_net_cancel();return 0;}
            netcheck_error=ti_net_poll(reply,&status);if(netcheck_error)break;
            netcheck_http=status.http_status;netcheck_result=status.result;
            if(status.state==TI_NET_FAILED||status.state==TI_NET_CANCELLED){netcheck_error=TI_E_IO;break;}
            if(!netcheck_retain) {
                netcheck_error=ti_net_read(TI_NET_BODY,offset,reply,sizeof(reply),&chunk);
                if(netcheck_error)break;
                if(chunk.state==TI_NET_SOURCE_FAILED||chunk.state==TI_NET_LOST){netcheck_error=TI_E_IO;break;}
                if(chunk.length>65535U-offset){netcheck_error=TI_E_RANGE;break;}
                netcheck_bytes+=chunk.length;offset+=chunk.length;
                if(chunk.state==TI_NET_END){netcheck_phase=4;break;}
            } else if(netcheck_phase==2&&status.state==TI_NET_DONE) {
                netcheck_error=ti_net_json(netcheck_pointer);netcheck_phase=3;
            } else if(netcheck_phase==3&&status.json_state!=TI_JSON_PENDING) {
                if(status.json_state!=TI_JSON_FOUND){netcheck_error=TI_E_FORMAT;break;}
                netcheck_error=ti_net_read(TI_NET_VALUE,offset,reply,sizeof(reply),&chunk);
                if(netcheck_error)break;
                netcheck_bytes+=chunk.length;offset+=chunk.length;
                if(chunk.state==TI_NET_END){netcheck_phase=4;break;}
            }
        }
        if(netcheck_error&&!ti_net_poll(reply,&status))netcheck_result=status.result;
        ti_net_cancel();netcheck_go=0;
        ((volatile uint8_t *)0x400)[80]=netcheck_error?'F'|0x80:'P'|0x80;
    }
}
