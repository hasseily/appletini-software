#include "libtini.h"
#include <string.h>
volatile uint8_t net_mode, net_phase;
volatile uint16_t net_checks, net_failed;
static uint8_t reply[514], post[8]={0,1,2,3,4,5,6,7};
static ti_net_request request={"POST","https://example.test/a","Content-Type: application/json\r\n",post,8,1};
static ti_net_status status;
static ti_net_chunk chunk;
static uint16_t n,i;
static ti_error error;
static void check(uint8_t yes,uint16_t id){++net_checks;if(!yes&&!net_failed)net_failed=id;}
int main(void)
{
    net_phase=1;
    error=ti_net_probe(reply);
    if(net_mode==1||net_mode==2) {
        check(error==TI_E_UNAVAILABLE&&!ti_net_available(),1);return 0;
    }
    if(net_mode==3||net_mode==4) {
        check(error==TI_E_IO&&!ti_net_available(),3);
        check(ti_net_probe(reply)==TI_E_IO,4);return 0;
    }
    check(!error&&ti_net_available()&&ti_net_via_hz()==1017812UL,5);
    check(ti_net_start(&request)==TI_OK,6);
    net_phase=2;
    error=ti_net_poll(reply,&status);
    if(net_mode==6){check(error==TI_OK&&status.state==TI_NET_FAILED&&
        status.result==TI_NET_RESULT_NETWORK_NOT_READY,22);return 0;}
    if(net_mode==5){check(error==TI_E_HANDLE,7);return 0;}
    check(error==TI_OK&&status.state==TI_NET_DONE&&status.http_status==200,8);
    check(status.body_length==32768UL&&status.url_length==22,9);
    for(n=9;n<=512;++n) {
        memset(reply,0xCC,sizeof(reply));
        check(ti_net_read(TI_NET_BODY,123,reply,n,&chunk)==TI_OK,10);
        check(chunk.length==n-8&&chunk.data==reply+8&&chunk.state==TI_NET_MORE,11);
        for(i=0;i<chunk.length;++i)check(chunk.data[i]==(uint8_t)(123+i),12);
        for(i=n;i<514;++i)check(reply[i]==0xCC,13);
    }
    net_phase=3;
    check(ti_net_json("/scores/0/name")==TI_OK,14);
    check(ti_net_read(TI_NET_VALUE,0,reply,128,&chunk)==TI_OK,15);
    check(chunk.length==3&&chunk.state==TI_NET_END&&!memcmp(chunk.data,"ACE",3),16);
    check(ti_net_cancel()==TI_OK,17);
    check(ti_net_read(TI_NET_BODY,0,reply,8,&chunk)==TI_E_ARGUMENT,18);
    check(ti_net_read(TI_NET_BODY,0,reply,513,&chunk)==TI_E_ARGUMENT,19);
    request.url="";check(ti_net_start(&request)==TI_E_RANGE,20);
    net_phase=4;return 0;
}
