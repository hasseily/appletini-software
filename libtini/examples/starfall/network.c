#include "libtini.h"
#include "game.h"
#include "network.h"
#include <string.h>
#pragma code-name ("TINET")
#pragma rodata-name ("TINET")
#pragma bss-name ("TINETBSS")
extern uint8_t ti_transfer_start;
#define reply (&ti_transfer_start)
/* The existing drawing helpers remain resident. Network code and scratch
 * borrow their own overlay only while the game-over panel is open. */
void rect(int16_t,int16_t,uint16_t,uint16_t,uint8_t);
void text(int16_t,int16_t,const char *,uint8_t);
void present(int16_t,int16_t,uint16_t,uint16_t);
enum { EDIT, ID_WAIT, ID_JSON, POST_WAIT, POST_JSON, LADDER_WAIT, ROW_NAME, ROW_SCORE, FINISHED, OFFLINE };
uint8_t sf_online_phase;
#define phase sf_online_phase
extern uint8_t sf_online_saved;
static uint8_t row,typed;
static uint32_t last_tick;
static ti_net_request request;
static ti_net_status status;
static ti_net_chunk chunk;
char sf_online_name[13],sf_online_run_id[33];
#define name sf_online_name
#define id sf_online_run_id
static char post[200],line[32],path[32],digits[11];
static const char base[]="https://appletini.org/leaderboards/starfall";
static char url[64];
static void hint(const char *s)
{rect(12,166,216,28,0);text(16,168,s,9);text(16,182,"TAB: TOP 10  ESC: BACK",2);present(12,166,216,28);}
static void failed(void){phase=OFFLINE;hint("OFFLINE - PLAY STILL WORKS");}
static uint8_t start(const char *tail,const char *method,const char *body)
{
    strcpy(url,base);strcat(url,tail);
    request.url=url;request.method=method;request.headers=body?"Content-Type: application/json\r\n":0;
    request.body=body;request.body_length=body?strlen(body):0;request.retain=1;
    if(ti_net_start(&request)){failed();return 0;}return 1;
}
static void number(uint32_t value)
{
    char *s=digits;
    ti_digits(digits,value,10);while(*s=='0'&&s[1])++s;strcat(post,s);
}
static uint8_t value(void)
{
    if(ti_net_read(TI_NET_VALUE,0,reply,128,&chunk)||chunk.state!=TI_NET_END||chunk.length>32) {failed();return 0;}
    return 1;
}
static void pointer(const char *s,uint8_t next)
{if(ti_net_json(s)){failed();return;}phase=next;}
static void row_pointer(const char *field,uint8_t next)
{
    strcpy(path,"/scores/0/");path[8]=(char)('0'+row);strcat(path,field);pointer(path,next);
}
uint32_t sf_online_clock(void)
{return ti_net_probe(reply)==TI_OK?ti_net_via_hz():0;}
void sf_online_begin(void)
{
    phase=EDIT;row=typed=0;if(!sf_online_saved)strcpy(name,"PLAYER");last_tick=ti_audio_ticks();
    rect(12,18,216,176,0);text(16,22,"STARFALL ONLINE RANKINGS",5);
    strcpy(line,"NAME: ");strcat(line,name);text(16,46,line,4);text(16,66,"TYPE A PUBLIC GAME NAME",2);
    text(16,82,"ENTER: SEND THIS RUN",9);present(12,18,216,148);
    if(ti_net_probe(reply))failed();else hint("CHOOSE A NAME TO SUBMIT");
}
uint8_t sf_online_key(uint8_t key)
{
    if(key==27){ti_net_cancel();return 1;}
    if(key==9||(key=='L'&&phase!=EDIT)) {
        rect(12,38,216,124,0);text(16,40,"RANK  NAME         SCORE",2);present(12,38,216,124);
        if(start("/api/ladder","GET",0)){phase=LADDER_WAIT;hint("GETTING TOP 10...");}return 0;
    }
    if(phase!=EDIT)return 0;
    if(sf_online_saved) {
        if(key==13&&start("/api/runs","POST",post)){phase=POST_WAIT;hint("SENDING RUN...");}
        return 0;
    }
    if(key==13) {
        while(name[0]&&name[strlen(name)-1]==' ')name[strlen(name)-1]=0;
        if(!name[0])strcpy(name,"PLAYER");
        if(start("/api/run-id","GET",0)){phase=ID_WAIT;hint("STARTING SUBMISSION...");}
    } else if(key==8||key==127) {
        if(strlen(name))name[strlen(name)-1]=0;
    } else if((key>='A'&&key<='Z')||(key>='0'&&key<='9')||key==' '||key=='.'||key=='_'||key=='-') {
        if(!typed){name[0]=0;typed=1;}
        if(!name[0]&&!((key>='A'&&key<='Z')||(key>='0'&&key<='9')))return 0;
        if(strlen(name)<12){uint8_t at=strlen(name);name[at]=key;name[at+1]=0;}
    }
    rect(16,46,208,10,0);strcpy(line,"NAME: ");strcat(line,name);text(16,46,line,4);present(16,46,208,10);return 0;
}
void sf_online_poll(void)
{
    uint32_t now=ti_audio_ticks();
    if(now==last_tick||phase==EDIT||phase>=FINISHED)return;
    last_tick=now;
    if(ti_net_poll(reply,&status)){failed();return;}
    if(status.state==TI_NET_FAILED||status.state==TI_NET_CANCELLED){failed();return;}
    if(phase==ID_WAIT||phase==POST_WAIT||phase==LADDER_WAIT) {
        if(status.state!=TI_NET_DONE)return;
        if(status.http_status!=200){failed();return;}
        if(phase==ID_WAIT)pointer("/run_id",ID_JSON);
        else if(phase==POST_WAIT)pointer("/rank",POST_JSON);
        else {row=0;row_pointer("name",ROW_NAME);}
        return;
    }
    if(status.json_state==TI_JSON_PENDING)return;
    if(status.json_state==TI_JSON_MISSING&&phase==ROW_NAME){phase=FINISHED;hint("TOP 10 COMPLETE");return;}
    if(status.json_state!=TI_JSON_FOUND||!value()){failed();return;}
    if(phase==ID_JSON) {
        if(chunk.length!=32){failed();return;}
        memcpy(id,chunk.data,32);id[32]=0;
        strcpy(post,"{\"run_id\":\"");strcat(post,id);strcat(post,"\",\"name\":\"");strcat(post,name);
        strcat(post,"\",\"version\":\"1.0-net1\",\"platform\":\"appletini\",\"score\":");number(sf_state.score);
        strcat(post,",\"sector\":");number((uint16_t)sf_state.sector+1);
        strcat(post,",\"kills\":");number(sf_state.kills);strcat(post,"}");
        sf_online_saved=1;
        if(start("/api/runs","POST",post)){phase=POST_WAIT;hint("SENDING RUN...");}
    } else if(phase==POST_JSON) {
        if(chunk.length>7){failed();return;}
        strcpy(line,"BEST RANK: ");memcpy(line+11,chunk.data,chunk.length);line[11+chunk.length]=0;
        phase=FINISHED;hint(line);
    } else if(phase==ROW_NAME) {
        memset(line,' ',26);line[26]=0;line[0]=(char)('0'+(row+1)/10);line[1]=(char)('0'+(row+1)%10);
        if(chunk.length>12){failed();return;}memcpy(line+4,chunk.data,chunk.length);row_pointer("score",ROW_SCORE);
    } else if(phase==ROW_SCORE) {
        if(chunk.length>7){failed();return;}memcpy(line+18,chunk.data,chunk.length);
        text(16,54+row*11,line,4);present(16,54+row*11,208,10);
        if(++row==10){phase=FINISHED;hint("TOP 10 COMPLETE");}else row_pointer("name",ROW_NAME);
    }
}
uint8_t sf_online_panel(void)
{
    uint8_t key;
    sf_online_begin();
    for(;;) {
        ti_audio_update();ti_input_poll();sf_online_poll();
        while(ti_input_key(&key)==TI_OK) {
            if(key>='a'&&key<='z')key-=32;
            if(key=='Q'&&phase!=EDIT){ti_net_cancel();return 1;}
            if(sf_online_key(key))return 0;
        }
    }
}
