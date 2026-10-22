#include "libtini.h"
#include "libtini/amem.h"

volatile uint8_t amem_mode,amem_phase;
volatile uint16_t amem_checks,amem_failed;
static uint8_t source[512],result[512];
static ti_handle a,b;
static uint16_t i;
static ti_error error;
static void check(uint8_t ok,uint16_t id)
{++amem_checks;if(!ok&&!amem_failed)amem_failed=id;}

int main(void)
{
    check(ti_init(1,4)==TI_OK,1);
    check(ti_res_alloc(TI_BANK_BYTES+1024,&a)==TI_OK,2);
    check(ti_res_alloc(512,&b)==TI_OK,3);
    check(ti_res_fill(a,0,0xEE,TI_BANK_BYTES+1024)==TI_OK,4);
    for(i=0;i<512;++i)source[i]=(uint8_t)(i*11+7);
    amem_phase=1;
    error=ti_amem_enable();
    if(amem_mode==11){
        check(error==TI_OK&&ti_amem_available(),1110);
        check(ti_shutdown()==TI_OK,1111);
        check(!ti_amem_available(),1112);
        return 0;
    }else if(amem_mode==1||amem_mode==2||amem_mode==12){
        check(error==TI_E_UNAVAILABLE&&!ti_amem_available(),10);
        check(ti_res_write(a,TI_BANK_BYTES-100,source,512)==TI_OK,11);
        check(ti_res_read(a,TI_BANK_BYTES-100,result,512)==TI_OK,12);
        for(i=0;i<512;++i)check(result[i]==source[i],13);
    }else if(amem_mode==9){
        check(error==TI_E_IO&&!ti_amem_available(),90);
        check(ti_amem_enable()==TI_E_IO,91);
    }else{
        check(error==TI_OK&&ti_amem_available(),20);
        amem_phase=2;
        error=ti_res_write(a,TI_BANK_BYTES-100,source,512);
        if(amem_mode>=4){
            check(error==TI_E_IO,40);
            if(amem_mode==4||amem_mode==8){
                check(!ti_amem_available(),41);
                check(ti_res_fill(b,0,0x22,256)==TI_E_IO,42);
                check(ti_amem_enable()==TI_E_IO,43);
            }
            ti_amem_disable();
            check(ti_res_read(a,TI_BANK_BYTES-100,result,512)==TI_OK,44);
            for(i=0;i<512;++i){
                uint16_t changed=amem_mode==4?8:(amem_mode==8?0:100);
                check(result[i]==(i<changed?source[i]:0xEE),45);
            }
        }else{
            check(error==TI_OK,21);
            check(ti_res_read(a,TI_BANK_BYTES-100,result,512)==TI_OK,22);
            for(i=0;i<512;++i)check(result[i]==source[i],23);
            if(!amem_mode){
                amem_phase=3;
                check(ti_res_fill(a,TI_BANK_BYTES-100,0x5A,512)==TI_OK,24);
                check(ti_res_read(a,TI_BANK_BYTES-100,result,512)==TI_OK,25);
                for(i=0;i<512;++i)check(result[i]==0x5A,26);
                amem_phase=4;
                check(ti_res_copy(b,0,a,TI_BANK_BYTES-100,512)==TI_OK,27);
                check(ti_res_read(b,0,result,512)==TI_OK,28);
                for(i=0;i<512;++i)check(result[i]==0x5A,29);
                check(ti_res_write(b,0,source,512)==TI_OK,30);
                amem_phase=5;
                check(ti_res_copy(b,1,b,0,511)==TI_OK,31); /* overlapping => CPU */
                check(ti_res_write(a,0,source,128)==TI_OK,32); /* small => CPU */
                ti_amem_disable();
                check(ti_res_read(b,0,result,512)==TI_OK,33);
                check(result[0]==source[0],34);
                for(i=1;i<512;++i)check(result[i]==source[i-1],35);
            }else ti_amem_disable();
            amem_phase=6;
            check(ti_res_write(a,TI_BANK_BYTES-100,source,512)==TI_OK,36);
            check(ti_res_read(a,TI_BANK_BYTES-100,result,512)==TI_OK,37);
            for(i=0;i<512;++i)check(result[i]==source[i],38);
        }
    }
    ti_amem_disable();
    check(!ti_amem_available(),98);
    check(ti_shutdown()==TI_OK,99);
    return 0;
}
