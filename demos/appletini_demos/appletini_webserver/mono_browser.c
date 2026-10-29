/* SPDX-License-Identifier: MIT
 * A2MONO: A2LYNX navigation and HTML subset, mono DHGRi presentation.
 * The document lives in AUX0; image codecs replace this code overlay. */
#include "mono_gfx.h"
#include "mono_net.h"
#include "mono_media.h"
#include "mono_mouse.h"
#include "mono_document.h"
#include <conio.h>
#include <ctype.h>
#include <stdint.h>
#include <string.h>

#pragma code-name ("BROWSER")
#pragma rodata-name ("BROWSER")
#define URL_CAP 256U
#define LINK_MAX 32U
#define IMAGE_MAX 12U
#define CONTENT_ROW 1U
#define CONTENT_ROWS 43U
#define CONTENT_TOP 8U
#define IMAGE_ROWS 18U
#define COLUMNS 78U

typedef struct { uint16_t at, length, line; } anchor;
typedef struct { uint16_t at, length, line; } picture;
static anchor links[LINK_MAX];
static picture images[IMAGE_MAX];
static char current[URL_CAP], target[URL_CAP], reference[URL_CAP];
static char history[2][URL_CAP];
static char tagbuf[320], word[80], linebuf[81];
static uint8_t cache[128];
static uint16_t cache_at, top, total_lines;
static uint16_t cursor_at, layout_line, tag_at;
static uint8_t link_count, image_count, selected, history_count;
static uint8_t active_link, column, word_length, heading, suppressed;
static uint8_t link_pending;
static uint8_t have_network, truncated, plain_document, painting;
static uint8_t images_enabled;
static uint8_t mouse_shown, pointer_col, pointer_row, mouse_vbl, mouse_phase;
static uint8_t hit_testing, hit_col, hit_row, hit_link;
static uint8_t seeking;
static uint8_t download_links[LINK_MAX], download_seek;
#pragma rodata-name ("RODATA")
static const char demo[] =
    "<h1>A2MONO</h1>"
    "<p>The web, through an Apple II.</p>"
    "<p>A graphical HTTPS browser for Appletini. Crisp 560x384 monochrome "
    "DHGRi, with the page rendered by your Apple II.</p>"
    "<h2>Explore</h2>"
    "<p>Press G for a URL, or Tab then Return to follow a link. "
    "Space/P scroll. B goes back.</p>"
    "<p><a href=https://appletini.org/>Visit Appletini</a> | "
    "<a href=https://example.com/>Try Example.com</a></p>"
    "<h2>More than text</h2>"
    "<p>Press I to load images: GIF, PNG and baseline JPEG. Images start off "
    "on each page. Download links save files to your SD card. "
    "A mouse is optional.</p>";
#pragma rodata-name ("BROWSER")

/* Decode a URL fragment in place. '+' is literal; invalid escapes and NUL
 * cannot turn an invalid destination into a different valid anchor. */
static uint8_t fragment_decode(char *p)
{
    char *out=p;
    uint8_t c,d,n,value;
    while((c=(uint8_t)*p++)!=0) {
        if(c=='%') {
            value=0;
            for(n=0;n<2;++n) {
                d=(uint8_t)tolower((unsigned char)*p++);
                if(d>='0' && d<='9') d-='0';
                else if(d>='a' && d<='f') d-='a'-10;
                else return 0;
                value=(uint8_t)((value<<4)|d);
            }
            if(!value) return 0;
            c=value;
        }
        *out++=(char)c;
    }
    *out=0;return 1;
}

#pragma code-name ("LC")
static uint8_t starts(const char *s, const char *p)
{
    /* These scheme/type prefixes use lowercase ASCII and : / + only. */
    while (*p) if ((uint8_t)(*s++|32U) != (uint8_t)*p++) return 0;
    return 1;
}
#pragma code-name ("BROWSER")
static void status(const char *s)
{
    uint8_t n = 0;
    memset(linebuf, ' ', 80); linebuf[80] = 0;
    while (s[n] && n < 80) { linebuf[n] = s[n]; ++n; }
    mono_gfx_text(0, 47, linebuf, 0);
}
static void chrome(void)
{
    memset(linebuf, ' ', 80); linebuf[80] = 0;
    mono_gfx_text(0, 0, linebuf, 0);
    mono_gfx_text(0, 45, linebuf, 0);
    mono_gfx_text(0, 46, linebuf, 0);
    strncpy(linebuf, current, 79);
    mono_gfx_text(0, 0, linebuf, 0);
    mono_gfx_text(0, 45, "G URL  TAB/ARROWS links  ENTER open  SPACE/P scroll  B back  R reload  I images", 0);
    mono_gfx_text(0, 46, mono_mouse_available?
        "[BACK] [UP] [DOWN] [URL] [HOME] [QUIT] | Mouse: click links":
        " Q quit  H home  ESC cancel  |  Images wait for I on each page", 0);
}
static uint8_t source(uint16_t at)
{
    uint16_t n;
    if (at >= mono_document_length) return 0;
    if (at < cache_at || at-cache_at >= sizeof(cache)) {
        cache_at = at; n = mono_document_length-at;
        if (n > sizeof(cache)) n = sizeof(cache);
        mono_document_read(at, cache, n);
    }
    return cache[at-cache_at];
}
/* Resolve into a distinct output buffer, preserving query-only links and
 * removing dot segments. Unsupported schemes cannot become HTTP requests. */
static uint8_t resolve(const char *base, const char *href, char *out)
{
    const char *p, *path, *query;
    uint16_t n, i, a, b;
    if (!*href || *href == '#') return 0;
    if (starts(href,"about:")) {
        if (strcmp(href,"about:demo") && strcmp(href,"about:sample")) return 0;
        strcpy(out,href); return 1;
    }
    if (starts(href,"http://") || starts(href,"https://")) {
        if (strlen(href) >= URL_CAP) return 0;
        strcpy(out,href);
    } else if (href[0]=='/' && href[1]=='/') {
        strcpy(out,starts(base,"https:")?"https:":"http:");
        if (strlen(href)+strlen(out)>=URL_CAP) return 0;
        strcat(out,href);
    } else {
        p = strstr(base,"://"); if (!p) return 0;
        path = strpbrk(p+3,"/?#");
        if (!path) path = base+strlen(base);
        query=strpbrk(href,"/?#");p=strchr(href,':');
        if(p && (!query || p<query)) return 0;
        if (*href=='/') n=(uint16_t)(path-base);
        else if (*href=='?') { query=strpbrk(path,"?#"); n=query?(uint16_t)(query-base):(uint16_t)strlen(base); }
        else {
            query=strpbrk(path,"?#"); if (!query) query=base+strlen(base);
            p=query; while(p>path && p[-1]!='/') --p;
            n=(uint16_t)(p-base);
        }
        if (n+strlen(href)+2>=URL_CAP) return 0;
        memcpy(out,base,n);
        if (*href!='/' && *href!='?' && (n==0 || out[n-1]!='/')) out[n++]='/';
        strcpy(out+n,href);
    }
    p=strchr(out,'#'); if(p) out[p-out]=0;
    p=strstr(out,"://"); if(!p || !p[3]) return 0;
    a=(uint16_t)(p-out)+3;
    while(out[a] && out[a]!='/' && out[a]!='?') ++a;
    if(out[a]!='/') {
        n=(uint16_t)strlen(out);if(n==URL_CAP-1) return 0;
        memmove(out+a+1,out+a,n-a+1);out[a]='/';
    }
    i=a+1;
        while (out[i] && out[i]!='?') {
            if (out[i]=='.' && (out[i+1]=='/' || !out[i+1] || out[i+1]=='?')) {
                b=i+1; if(out[b]=='/') ++b; memmove(out+i,out+b,strlen(out+b)+1);
            } else if(out[i]=='.' && out[i+1]=='.' && (out[i+2]=='/' || !out[i+2] || out[i+2]=='?')) {
                b=i+2; if(out[b]=='/') ++b;
                n=i; if(n>a+1) { --n; while(n>a+1 && out[n-1]!='/') --n; }
                memmove(out+n,out+b,strlen(out+b)+1); i=n;
            } else { while(out[i] && out[i]!='/' && out[i]!='?') ++i; if(out[i]=='/') ++i; }
        }
    return 1;
}
static void extract(uint16_t at, uint16_t length)
{
    uint16_t n=0;
    if(length>=URL_CAP) { reference[0]=0; return; }
    while(length--) {
        if(length>=4 && source(at)=='&' && source(at+1)=='a' && source(at+2)=='m' && source(at+3)=='p' && source(at+4)==';') {
            reference[n++]='&'; at+=5; length-=4;
        } else reference[n++]=(char)source(at++);
    }
    reference[n]=0;
}
static void newline(void) { ++layout_line; column=0; }
static void flush_word(void)
{
    uint16_t y, j;
    uint8_t inverse;
    if(!word_length) return;
    if(column && column+word_length+1>COLUMNS) newline();
    else if(column) ++column;
    if(link_pending && active_link!=255) {
        links[active_link].line=layout_line; link_pending=0;
    }
    word[word_length]=0;
    if(hit_testing && active_link!=255 && hit_row>=CONTENT_ROW && hit_row<44 &&
       layout_line==top+hit_row-CONTENT_ROW && hit_col>=column+1 && hit_col<column+1+word_length)
        hit_link=active_link;
    if(painting && layout_line>=top && layout_line<top+CONTENT_ROWS) {
        inverse=(uint8_t)(active_link!=255 && active_link==selected);
        mono_gfx_text(column+1,(uint8_t)(layout_line-top+CONTENT_ROW),word,(uint8_t)!inverse);
        if(active_link!=255 && !inverse) {
            y=(layout_line-top+CONTENT_ROW)*8U+7;
            for(j=0;j<(uint16_t)word_length*7U;++j) mono_gfx_pixel((uint16_t)(column+1)*7U+j,y,0);
        }
    }
    column+=word_length; word_length=0;
}
static void character(uint8_t c)
{
    if(c<=32) { flush_word(); return; }
    if(c>=127) c='?';
    if(heading) c=(uint8_t)toupper(c);
    word[word_length++]=(char)c;
    if(word_length==COLUMNS) { flush_word(); newline(); }
}
static void block(uint8_t blank)
{
    flush_word(); if(column) newline(); if(blank && layout_line) newline();
}
/* Attribute result points into the original document, never a copied pool. */
static uint8_t attribute(const char *wanted, uint16_t *at, uint16_t *length)
{
    uint16_t i=0,start,n,j;
    uint8_t q,match;
    while(tagbuf[i] && !isspace((unsigned char)tagbuf[i])) ++i;
    while(tagbuf[i]) {
        while(isspace((unsigned char)tagbuf[i]) || tagbuf[i]=='/') ++i;
        start=i;
        while(isalnum((unsigned char)tagbuf[i]) || tagbuf[i]=='-' || tagbuf[i]=='_') ++i;
        n=i-start;
        if(!n) { if(tagbuf[i]) ++i; continue; }
        match=n==strlen(wanted);
        if(match) for(j=0;j<n;++j)
            if(tolower((unsigned char)tagbuf[start+j])!=wanted[j]) {match=0;break;}
        while(isspace((unsigned char)tagbuf[i])) ++i;
        if(tagbuf[i]!='=') {
            if(match) {*at=tag_at+i;*length=0;return 1;}
            continue;
        }
        ++i; while(isspace((unsigned char)tagbuf[i])) ++i;
        q=(uint8_t)tagbuf[i]; if(q=='\'' || q=='"') ++i; else q=0;
        *at=i; while(tagbuf[i] && (q?tagbuf[i]!=q:!isspace((unsigned char)tagbuf[i]) && tagbuf[i]!='>')) ++i;
        *length=i-*at;
        if(match) { *at+=tag_at; return 1; }
        if(q && tagbuf[i]) ++i;
    }
    return 0;
}
static void parse_tag(void)
{
    uint16_t n=0,at,length;
    uint8_t q=0,c,closing=0;
    char name[12];
    tag_at=cursor_at;
    if(source(cursor_at)=='!' && source(cursor_at+1)=='-' && source(cursor_at+2)=='-') {
        cursor_at+=3;
        while(cursor_at<mono_document_length) {
            if(source(cursor_at)=='-' && source(cursor_at+1)=='-' && source(cursor_at+2)=='>') {cursor_at+=3;break;}
            ++cursor_at;
        }
        return;
    }
    while(cursor_at<mono_document_length) {
        c=source(cursor_at++);
        if(c=='>' && !q) break;
        if(c=='\'' || c=='"') { if(!q) q=c; else if(q==c) q=0; }
        if(n<sizeof(tagbuf)-1) tagbuf[n++]=(char)c;
    }
    tagbuf[n]=0; n=0;
    if(tagbuf[0]=='/') { closing=1; ++n; }
    at=0;
    while(isalnum((unsigned char)tagbuf[n])) { if(at<sizeof(name)-1) name[at++]=(char)tolower((unsigned char)tagbuf[n]); ++n; }
    name[at]=0;
    if(!strcmp(name,"script") || !strcmp(name,"style") || !strcmp(name,"head")) {
        /* HEAD encloses SCRIPT/STYLE. Closing a child must retain HEAD. */
        c=name[0]=='h'?1:name[1]=='c'?2:4;
        if(closing) suppressed&=(uint8_t)~c; else suppressed|=c;
        return;
    }
    if(suppressed || !name[0]) return;
    q=0;
    if(seeking && !closing && (seeking==1 || !strcmp(name,"a")) &&
       attribute(seeking==1?"id":"name",&at,&length)) {
        extract(at,length);
        if(!strcmp(reference,target)) { q=1;seeking=0; }
    }
    if(!strcmp(name,"a")) {
        flush_word();
        if(closing) { active_link=255; link_pending=0; }
        else if(link_count<LINK_MAX && attribute("href",&at,&length) && length<URL_CAP) {
            active_link=link_count; links[link_count].at=at; links[link_count].length=length;
            download_links[link_count]=attribute("download",&at,&length);
            if(download_seek && selected==link_count && download_links[link_count]) extract(at,length);
            links[link_count++].line=layout_line;
            link_pending=1;
        }
    } else if(!strcmp(name,"img") && !closing) {
        block(0);
        if(q) {top=layout_line;q=0;}
        if(image_count<IMAGE_MAX && attribute("src",&at,&length) && length<URL_CAP) {
            if(link_pending && active_link!=255) {
                links[active_link].line=layout_line; link_pending=0;
            }
            images[image_count].at=at; images[image_count].length=length;
            images[image_count++].line=layout_line;
            if(hit_testing && active_link!=255 && hit_col>=1 && hit_col<79 && hit_row>=CONTENT_ROW && hit_row<44 &&
               top+hit_row-CONTENT_ROW>=layout_line && top+hit_row-CONTENT_ROW<layout_line+(images_enabled?IMAGE_ROWS:1))
                hit_link=active_link;
            if(!images_enabled && painting && layout_line>=top && layout_line<top+CONTENT_ROWS)
                mono_gfx_text(1,(uint8_t)(layout_line-top+CONTENT_ROW),"[Image: I]",1);
            layout_line+=images_enabled?IMAGE_ROWS:1; newline();
        } else { character('[');character('I');character('M');character('G');character(']');block(0); }
    } else if(name[0]=='h' && name[1]>='1' && name[1]<='6' && !name[2]) { block(1); heading=!closing; }
    else if(!strcmp(name,"p") || !strcmp(name,"blockquote")) block(1);
    else if(!strcmp(name,"br") || !strcmp(name,"div") || !strcmp(name,"tr") || !strcmp(name,"ul") || !strcmp(name,"ol")) block(0);
    else if(!strcmp(name,"li")) { block(0); if(!closing) {character('*');character(' ');} }
    else if(!strcmp(name,"td") || !strcmp(name,"th")) character(' ');
    if(q) top=layout_line;
}
static void entity(void)
{
    uint16_t value=0;
    uint8_t n=0,c;
    char token[12];
    while(cursor_at<mono_document_length && n<sizeof(token)-1) {
        c=source(cursor_at); if(c==';') { ++cursor_at; break; }
        if(!isalnum(c) && c!='#') break;
        token[n++]=(char)c; ++cursor_at;
    }
    token[n]=0;
    if(!strcmp(token,"amp")) c='&'; else if(!strcmp(token,"lt")) c='<';
    else if(!strcmp(token,"gt")) c='>'; else if(!strcmp(token,"quot")) c='"';
    else if(!strcmp(token,"apos")) c='\''; else if(!strcmp(token,"nbsp")) c=' ';
    else if(token[0]=='#') {
        uint8_t i=1,base=10,d;
        if(token[i]=='x' || token[i]=='X') { base=16; ++i; }
        while(token[i]) { d=(uint8_t)tolower(token[i++]); d=d>='a'?(uint8_t)(d-'a'+10):(uint8_t)(d-'0'); if(d>=base) break; value=value*base+d; }
        c=(value>=32 && value<127)?(uint8_t)value:'?';
    } else c='?';
    character(c);
}
static void layout(void)
{
    uint8_t c;
    cursor_at=layout_line=0; cache_at=0xFFFF;
    column=word_length=heading=suppressed=link_count=image_count=link_pending=0; active_link=255;
    while(cursor_at<mono_document_length) {
        c=source(cursor_at++);
        /* Script/style raw text can contain '<' operators and quotes. Only
         * closing tags are significant until the raw-text element ends. */
        if(!plain_document && c=='<' && (!(suppressed&6) || source(cursor_at)=='/')) parse_tag();
        else if(!suppressed) { if(!plain_document && c=='&') entity(); else character(c); }
    }
    block(0); total_lines=layout_line+1;
}
static void draw(uint8_t pictures)
{
    uint8_t i;
    int16_t y;
    mono_gfx_begin();
    if(pictures) mono_gfx_clear(0);
    painting=1; layout(); chrome();
    status(truncated?"Page truncated":!images_enabled?"Images off | I loads":have_network?"HTTPS OK":"Demo | No HTTP");
    mono_gfx_commit();
    if(!pictures || !images_enabled) return;
    for(i=0;i<image_count;++i) {
        if(images[i].line>=top+CONTENT_ROWS || images[i].line+IMAGE_ROWS<=top) continue;
        y=((int16_t)images[i].line-(int16_t)top)*8+CONTENT_TOP;
        if(y>=352 || y+(int16_t)IMAGE_ROWS*8<=CONTENT_TOP) continue;
        extract(images[i].at,images[i].length);
        if(resolve(current,reference,target)) {
            status("Loading image... ESC cancels");
            mono_gfx_commit();
            mono_gfx_clip(CONTENT_TOP,352);
            if(!mono_media(target,7,y,546,IMAGE_ROWS*8)) {
                if(y>=CONTENT_TOP) mono_gfx_text(1,(uint8_t)(y/8),"[No image]",1);
                status(mono_media_message);
            } else status("Image decoded");
            mono_gfx_clip(0,384);
            mono_gfx_commit();
        }
    }
}
static void push(void);
/* target holds the candidate URL. Defer replacement until ordinary body
 * bytes reach the resident sink; saved files leave the current page intact. */
static void load(uint8_t remember)
{
    uint8_t result,plain=0,cut=0;
    mono_document_pending=1;
    status("Loading... ESC cancels"); mono_gfx_commit();
    if(!strcmp(target,"about:demo")) {
        mono_document_reset();mono_document_pending=0;
        mono_document_append((const uint8_t *)demo,sizeof(demo)-1);
        result=MONO_HTTP_BODY;
    } else if(!have_network) {
        mono_document_pending=0;status("HTTP/S firmware required");mono_gfx_commit();return;
    } else result=mono_net_page(target,URL_CAP,mono_document_append,mono_document_capacity);
    if(result!=MONO_HTTP_BODY && mono_document_pending) {
        mono_document_pending=0;status(mono_net_error());mono_gfx_commit();return;
    }
    if(result!=MONO_HTTP_BODY) {
        mono_document_reset();
        strcpy(reference,mono_net_error());
        mono_document_append((const uint8_t *)reference,strlen(reference));plain=1;
    } else if(strcmp(target,"about:demo")) {
        cut=mono_http_cut;
        if(!starts(mono_http_type,"text/html") && !starts(mono_http_type,"application/xhtml+xml")) plain=1;
    }
    if(mono_document_pending) mono_document_reset();mono_document_pending=0;
    if(resolve(target,target,reference)) strcpy(target,reference);
    if(remember==1) push();else if(remember==2 && history_count) --history_count;
    strcpy(current,target);top=0;selected=0;images_enabled=0;plain_document=plain;truncated=cut;
    draw(1);
}
static void push(void)
{
    if(history_count==2) { memcpy(history,history+1,URL_CAP); --history_count; }
    strcpy(history[history_count++],current);
}
static uint8_t prompt(void)
{
    uint8_t c;
    uint16_t n=0;
    target[0]=0;
    for(;;) {
        status("URL: "); mono_gfx_text(5,47,target,0); mono_gfx_commit();
        c=(uint8_t)cgetc();
        if(c==27) return 0;
        if(c==13) return n!=0;
        if(c==8 || c==127) { if(n) target[--n]=0; }
        else if(c>=32 && c<127 && n<URL_CAP-1) { target[n++]=(char)c; target[n]=0; }
    }
}
static void hide_pointer(void)
{
    if(mouse_shown) {
        mono_gfx_begin();mono_gfx_invert(pointer_col,pointer_row,1);mono_gfx_commit();
        mouse_shown=0;
    }
}
static uint8_t input_key(void)
{
    uint8_t flags,vbl;
    if(!mono_mouse_available) return (uint8_t)cgetc();
    for(;;) {
        if(kbhit()) {hide_pointer();return (uint8_t)cgetc();}
        vbl=(*(volatile uint8_t *)0xC019)&128;
        if(vbl==mouse_vbl) continue;
        mouse_vbl=vbl;
        /* Leave a complete quiet frame between pointer publications. The
         * paired-page renderer waits for stable video memory before decode. */
        mouse_phase=(mouse_phase+1)&3;
        if(mouse_phase) continue;
        flags=mono_mouse_poll();
        if((flags&MONO_MOUSE_MOVED) || !mouse_shown) {
            hide_pointer();pointer_col=mono_mouse_x;pointer_row=mono_mouse_y;
            mono_gfx_begin();mono_gfx_invert(pointer_col,pointer_row,1);mono_gfx_commit();mouse_shown=1;
        }
        if(!(flags&MONO_MOUSE_PRESSED)) continue;
        hide_pointer();
        if(pointer_row==46) {
            if(pointer_col<6) return 'b';
            if(pointer_col>=7 && pointer_col<11) return 'p';
            if(pointer_col>=12 && pointer_col<18) return ' ';
            if(pointer_col>=19 && pointer_col<24) return 'g';
            if(pointer_col>=25 && pointer_col<31) return 'h';
            if(pointer_col>=32 && pointer_col<38) return 'q';
        }
        hit_col=pointer_col;hit_row=pointer_row;hit_link=255;hit_testing=1;painting=0;
        layout();hit_testing=0;
        if(hit_link!=255) {selected=hit_link;return 13;}
    }
}
int mono_browser_main(void)
{
    uint8_t c, old;
    uint16_t previous;
    char *fragment;
    have_network=mono_net_probe();
    mono_document_init();
    mono_mouse_init();
    mono_gfx_init(); strcpy(target,"about:demo"); load(0);
    for(;;) {
        c=input_key(); old=selected; previous=top;
        if(c=='q' || c=='Q' || c==27) break;
        if(c==10 || c==9) { if(link_count && selected+1<link_count) ++selected; }
        else if(c==11) { if(selected) --selected; }
        else if(c==' ') { if(top+CONTENT_ROWS<total_lines) top+=CONTENT_ROWS-1; }
        else if(c=='p' || c=='P') top=top>CONTENT_ROWS-1?top-CONTENT_ROWS+1:0;
        else if((c==13 || c==21) && selected<link_count) {
            extract(links[selected].at,links[selected].length);
            if(reference[0]=='#') strcpy(target,current);
            else if(!resolve(current,reference,target)) continue;
            if(download_links[selected]) {
                reference[0]=0;download_seek=1;painting=0;layout();download_seek=0;reference[127]=0;
                mono_net_download(target,reference);status(mono_net_error());mono_gfx_commit();continue;
            }
            fragment=strchr(reference,'#');
            if(fragment && !strcmp(target,current)) {
                strcpy(target,fragment+1);
                if(!fragment_decode(target)) continue;
                if(!target[0]) top=0;
                else {
                    seeking=1;painting=0;layout();
                    if(seeking) {seeking=2;layout();}
                    if(seeking && !strcmp(target,"top")) {top=0;seeking=0;}
                    if(seeking) {seeking=0;continue;}
                }
                draw(1);
            } else load(1);
            continue;
        } else if(c==8 || c=='b' || c=='B') {
            if(history_count) {strcpy(target,history[history_count-1]);load(2);} continue;
        } else if(c=='h' || c=='H') {strcpy(target,"about:demo");load(1);continue;}
        else if(c=='r' || c=='R') {strcpy(target,current);load(0);continue;}
        else if(c=='i' || c=='I') { images_enabled=1;draw(1);continue; }
        else if(c=='g' || c=='G') {
            if(prompt()) {
                if(strstr(target,"://") || starts(target,"about:")) strcpy(reference,target);
                else { strcpy(reference,"https://");strncat(reference,target,URL_CAP-9); }
                if(resolve(current,reference,target)) {load(1);continue;}
            }
            draw(0);continue;
        }
        if(old!=selected && selected<link_count) {
            if(links[selected].line<top) top=links[selected].line;
            else if(links[selected].line>=top+CONTENT_ROWS) top=links[selected].line-CONTENT_ROWS+1;
        }
        if(previous!=top) draw(1); else if(old!=selected) draw(0);
    }
    hide_pointer();mono_mouse_disable();mono_gfx_end();return 0;
}
