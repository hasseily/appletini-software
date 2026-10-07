; s2_menut.s: the menus' glue for the host runs (parts s2menu1 and s2menu2;
; m11/s2menu2.mk links it), not the game: one MENUW with both menu parts
; linked (the hooks m2_page, m2_value, m2_bench are s2_menu2.s's), the
; STANDIN of the routine another part owns, and the sound log's buffer.
;
;   pl_mouseup  IIGS_MouseUp (the menu's MOUSE option): not in part
;               plinput's pl_poll, which has no byte left for upstream's
;               iigs_mouseon; nothing here.
;               pl_poll, pl_bind and pl_defaults are part plinput's
;               (src/native/pl_input.s, pl_keys.s)
;   s2m_sndbuf  the sounds s2_menu.s's sound gave sc_start (filled only
;               with -D S2M_SNDLOG, which no build here defines): a
;               count, then the sounds (at most 63)
;
; The checkpoints' entries (tools/native/s2menu1.py, s2menu2.py), each
; between m_load and m_save, the routine alone in the cost phase 30 (PHASE
; 0 around it):
;
;   t_frame     A bit 0: mv_tables first (a frame after the menu's open,
;               whose tables a run starts without), then m_display
;   t_close     m_close (I_MenuPaletteBack)
;   t_resp      m_responder with A, X (the event); its answer in t_ret,
;               the sound log emptied first
;   t_tick      m_ticker
;   t_save      mv_amem alone (the open's save: its time)
;   t_tables    mv_tables alone (the open's gray tables, slot and reds)
;   t_paused    m_frame: a paused frame whole (the input poll, sc_update,
;               fx_service, snd_refill, then m_display)

        .setcpu "65C02"

        .export pl_mouseup
        .export s2m_sndbuf, t_frame, t_close, t_resp, t_tick, t_ret, t_save
        .export t_paused, t_tables
        .import m_load, m_save, m_display, m_close, m_responder, m_ticker
        .import m_frame
        .import mv_tables, mv_amem

        .include "rlayout.inc"
        .include "s2.inc"

        .segment "S2CODE"

; STANDIN: IIGS_MouseUp (part plinput's open problem 2)
pl_mouseup:
        rts

t_frame:
        pha
        jsr load
        pla
        and #1
        beq :+
        jsr mv_tables
:       jsr phase
        jsr m_display
        bra save
t_close:
        jsr load
        jsr phase
        jsr m_close
        bra save
t_resp:
        pha
        phx
        stz s2m_sndbuf
        jsr load
        jsr phase
        plx
        pla
        jsr m_responder
        sta t_ret
        bra save
t_tick:
        jsr load
        jsr phase
        jsr m_ticker
        bra save
t_save:
        jsr load
        jsr phase
        jsr mv_amem
        bra save
t_tables:
        jsr load
        jsr phase
        jsr mv_tables
        bra save
t_paused:
        jsr load
        jsr phase
        jsr m_frame
save:   stz PHASE
        jmp m_save
load:   stz PHASE
        jmp m_load
phase:  lda #PHV_2D
        sta PHASE
        rts

        .segment "S2DATA"

s2m_sndbuf:
        .res 64
t_ret:  .res 1
