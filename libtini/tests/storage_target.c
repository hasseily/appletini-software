#include "libtini.h"
#include "libtini/storage.h"
#include "internal.h"

volatile uint8_t storage_mode, storage_phase;
volatile uint16_t storage_checks, storage_failed, storage_pauses, storage_resumes;
static uint16_t nested_length;
static uint8_t nested_failed;
static uint8_t data[640], result[640], line[128];
static uint16_t i,j,length;
static ti_handle handle,slots[8];
static uint32_t size;
static const char *bad_packs[] = {"BADSIG.TPK","DUP.TPK","OVERLAP.TPK","BADNAME.TPK","TAIL.TPK","ZERO.TPK","DIRSHORT.TPK"};
static void check(uint8_t ok,uint16_t id)
{ ++storage_checks;if(!ok&&!storage_failed)storage_failed=id; }
static void pause_audio(void)
{++storage_pauses;if(ti_file_read("HELLO",line,128,&nested_length)!=TI_E_BUSY)nested_failed=1;}
static void resume_audio(void){++storage_resumes;}

int main(void)
{
    ti_storage_pause_hook=pause_audio;ti_storage_resume_hook=resume_audio;
    if(storage_mode==7){
        data[0]=0x45;
        check(ti_file_write("NOINIT",data,1)==TI_OK,700);
        check(ti_file_read("NOINIT",result,1,&length)==TI_OK&&length==1&&result[0]==0x45,701);
        return 0;
    }
    check(ti_init(1,6)==TI_OK,1);
    if(storage_mode==1){
        check(ti_file_read("HELLO",result,640,&length)==TI_E_IO,101);
        check(!length&&ti_file_last_error()==0x4C,102);
    }else if(storage_mode==2){
        check(ti_pack_load("GOOD.TPK","A_DATA",&handle,&size)==TI_E_IO,201);
        check(!handle&&!size,202);
        for(i=0;i<8;++i)check(ti_res_alloc(1,&slots[i])==TI_OK,203);
        for(i=0;i<8;++i)ti_res_free(slots[i]);
    }else if(storage_mode==3){
        check(ti_file_read("HELLO",result,640,&length)==TI_E_IO,301);
        check(ti_file_last_error()==0x27,302);
    }else if(storage_mode==4){
        check(ti_diag_video_begin()==TI_OK,401);
        for(i=0;i<128;++i)line[i]=0x77;
        ti_diag_video_write(0x2000,line,128);
        storage_phase=1;
        check(ti_file_write("SAVE",line,128)==TI_OK,402);
        storage_phase=2;
        ti_io_bank=0;ti_io_addr=0x2000;ti_io_near=result;ti_io_len=128;ti_cpu_read();
        for(i=0;i<128;++i)check(result[i]==0x77,403);
        check(ti_file_read("HELLO",result,640,&length)==TI_OK&&length==300,404);
        storage_phase=3;
        check(ti_diag_video_end()==TI_OK,405);
    }else if(storage_mode==5){
        check(ti_diag_video_begin()==TI_OK,501);
        for(i=0;i<7;++i)check(ti_res_alloc(1,&slots[i])==TI_OK,502);
        check(ti_file_write("SAVE",data,1)==TI_E_NOMEM,503);
        for(i=0;i<7;++i)ti_res_free(slots[i]);
    }else if(storage_mode==6){
        check(ti_pack_load("GOOD.TPK","A_DATA",&handle,&size)==TI_E_IO,601);
        check(!handle&&!size&&ti_file_last_error()==0x27,602);
    }else if(storage_mode==8||storage_mode==9||storage_mode==10){
        check(ti_file_write("SAVE",data,128)==TI_E_IO,801);
        check(ti_file_last_error()==(storage_mode==9?0x4C:0x27),802);
    }else if(storage_mode==11){
        check(ti_pack_load("GOOD.TPK","A_DATA",&handle,&size)==TI_E_IO,1101);
        check(!handle&&!size&&ti_file_last_error()==0x27,1102);
        for(i=0;i<8;++i)check(ti_res_alloc(1,&slots[i])==TI_OK,1103);
        for(i=0;i<8;++i)ti_res_free(slots[i]);
    }else{
        check(ti_file_read("HELLO",result,640,&length)==TI_OK&&length==300,10);
        for(i=0;i<300;++i)check(result[i]==(uint8_t)(i*13+9),11);
        check(ti_file_last_error()==0,12);
        check(ti_file_read("HELLO",result,20,&length)==TI_E_RANGE&&!length,13);
        check(ti_file_read("MISSING",result,640,&length)==TI_E_IO&&ti_file_last_error()==0x46,14);
        check(ti_file_read("bad",result,640,&length)==TI_E_ARGUMENT,15);
        check(ti_file_read("_BAD",result,640,&length)==TI_E_ARGUMENT,16);
        check(ti_file_read("HELLO",(void*)0xBF00,1,&length)==TI_E_RANGE,17);
        for(i=0;i<512;++i)data[i]=(uint8_t)(i*17+31);
        check(ti_file_write("SAVE",data,512)==TI_OK,18);
        check(ti_file_read("SAVE",result,640,&length)==TI_OK&&length==512,19);
        for(i=0;i<512;++i)check(result[i]==data[i],20);
        check(ti_file_write("SAVE",data,3)==TI_OK,21);
        check(ti_file_read("SAVE",result,640,&length)==TI_OK&&length==3,22);
        check(ti_file_write("EMPTY",0,0)==TI_OK,23);
        check(ti_file_read("EMPTY",0,0,&length)==TI_OK&&!length,24);
        check(ti_pack_load("GOOD.TPK","A_DATA",&handle,&size)==TI_OK&&size==600,25);
        check(ti_res_read(handle,0,result,600)==TI_OK,26);
        for(i=0;i<600;++i)check(result[i]==(uint8_t)(i*7+3),27);
        check(ti_res_free(handle)==TI_OK,28);
        check(ti_pack_load("GOOD.TPK","MISSING",&handle,&size)==TI_E_UNAVAILABLE&&!handle&&!size,29);
        for(j=0;j<7;++j)check(ti_pack_load(bad_packs[j],"A_DATA",&handle,&size)==TI_E_FORMAT&&!handle&&!size,30+j);
        for(i=0;i<8;++i)check(ti_res_alloc(1,&slots[i])==TI_OK,40);
        check(ti_pack_load("GOOD.TPK","A_DATA",&handle,&size)==TI_E_NOMEM&&!handle&&!size,41);
        for(i=0;i<8;++i)ti_res_free(slots[i]);
        check(ti_pack_load("GOOD.TPK","ZED",&handle,&size)==TI_OK&&size==32,42);
        check(ti_res_free(handle)==TI_OK,43);
    }
    check(storage_pauses==storage_resumes,90);
    check(!nested_failed,92);
    check(ti_shutdown()==TI_OK,91);
    return 0;
}
