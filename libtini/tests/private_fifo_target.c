#include "libtini.h"
volatile uint8_t fifo_mode,fifo_failed;
static uint8_t reply[64];
extern uint8_t ti_private_poisoned,ti_net_poisoned;
int main(void)
{
    if(fifo_mode==0) {
        if(ti_net_probe(reply)!=TI_E_IO)fifo_failed=1;
        if(ti_amem_enable()!=TI_E_IO)fifo_failed=2;
    } else {
        if(ti_amem_enable()!=TI_E_IO)fifo_failed=3;
        if(ti_net_probe(reply)!=TI_E_IO)fifo_failed=4;
    }
    if(!ti_private_poisoned||!ti_net_poisoned||ti_net_available()||ti_amem_available())fifo_failed=5;
    if(&ti_private_poisoned!=&ti_net_poisoned)fifo_failed=6;
    return 0;
}
