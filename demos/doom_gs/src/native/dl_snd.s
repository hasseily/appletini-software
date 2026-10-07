; dl_snd.s: the songs and the title loop (docs/PLAY.md), in the tic
; image's group DLG_SND, with s2t_st.s (the status bar's tic side, part
; s2stbar's) and its scratch block st_sb. A GPL-2 derivative of upstream's
; src/iigs/d_main65.s (D_DoAdvanceDemo), w_level65.s (W_NextDemo's steps)
; and s_sound65.s (musLevel, musTitle, musInter, musFinale: which song,
; once or looping) (Doom8088: Apple IIgs Edition, GPL-2).
;
;   s_song        A = a song (mus.UPSTREAM_SONGS' order: the songs'
;                 directory SONG_DIR in bank SONG_DIR_BANK, 3 bytes a
;                 song: its bank and address), X = SONG_LOOP or 0: S2's
;                 snd_start through fx_song (the effect player held while
;                 chip 3 is rewritten: docs/SCREENS.md), PAL or
;                 NTSC from the clock's CLK_STD, full volume (the menu's
;                 music volume changes no AY write: docs/SCREENS.md).
;                 Nothing on a card without native mode (fx_init's FX_ON
;                 0: no music, no effects)
;   s_levelsong   musLevel: the level's song, looping; one that plays goes
;                 on (a new life on the map)
;   d_doadvance   D_DoAdvanceDemo: the player not reborn, no user game,
;                 no action, the title page's state (GS_DEMOSCREEN); the
;                 next step of the demo sequence (W_NextDemo: the title
;                 page, demo3, the title page...): the title with its
;                 music (D_INTRO, once) for 30 s, or demo3 at the next tic
;                 (G_DeferedPlayDemo)
;   s_rinit       the renderer's state at the boot (its statics)
;   s_level       the level's frame block fields after its load (nodes,
;                 vertices, the sky) from its header in the store

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "s2.inc"
        .include "play.inc"
        .include "playsym.inc"
        .include "dl.inc"

        .import far_get, fc_call, fc_unbuilt, g_stop
        .export s_song, s_levelsong, d_doadvance, st_sb, s_rinit, s_level

PLR = G_PLAYER
TICRATE = UC_TICRATE

        .segment "DLGS"
FC_HERE .set DLG_SND

s_song: ldy FX_ON               ; no native mode: no music
        beq @rts
        sta DL_SONG
        stx GT_0                ; its flags
        sta GT_1                ; its directory entry: 3 x the song
        asl a
        adc GT_1
        clc
        adc #<SONG_DIR
        sta FA_SRC
        lda #>SONG_DIR
        adc #0
        sta FA_SRC+1
        lda #SONG_DIR_BANK
        sta FA_BANK
        lda #GT_2
        sta FA_DST
        stz FA_DST+1
        lda #3
        sta FA_N
        jsr far_get
        lda GT_2
        sta XS_snd_song_bank
        lda GT_3
        sta XS_snd_song_addr
        lda GT_4
        sta XS_snd_song_addr+1
        lda CLK_STD             ; bit 7 NTSC (S2's SONG_NTSC)
        and #$80
        ora GT_0
        sta XS_snd_song_flags
        stz XS_snd_song_matt
        jsr XS_fx_song
@rts:   rts

s_levelsong:
        lda G_GAMEMAP           ; E1M1-E1M9: songs 0-8
        dec a
        cmp DL_SONG
        beq :+
        ldx #SONG_LOOP
        bra s_song
:       rts

d_doadvance:
        stz PLR + PL_PLAYERSTATE        ; PST_LIVE: not reborn
        stz PLR + PL_PLAYERSTATE + 1
        stz DL_ADVDEMO
        stz G_USERGAME
        stz G_USERGAME+1
        stz G_GAMEACTION                ; (ga_nothing)
        stz G_GAMEACTION+1
        lda #<(TICRATE * 11)
        sta DL_PAGETIC
        lda #>(TICRATE * 11)
        sta DL_PAGETIC+1
        lda #UC_GS_DEMOSCREEN
        sta G_GAMESTATE
        stz G_GAMESTATE+1
        lda DL_DEMOSEQ                  ; W_NextDemo: 0, 1, 0, ...
        inc a
        cmp #2
        bcc :+
        lda #0
:       sta DL_DEMOSEQ
        cmp #0
        bne @demo
        lda #SONG_INTRO                 ; the title page: its music once,
        ldx #0                          ;   30 seconds
        jsr s_song
        lda #<(TICRATE * 30)
        sta DL_PAGETIC
        lda #>(TICRATE * 30)
        sta DL_PAGETIC+1
        rts
@demo:  lda #1                          ; G_DeferedPlayDemo("demo3"): the
        sta GA_0                        ;   name's reference (tag 1, the
        lda #<SYM_d_main_strDemo3       ;   symbol, offset 0: DEMOB's
        sta GA_1                        ;   directory names the lump so)
        lda #>SYM_d_main_strDemo3
        sta GA_2
        stz GA_3
        stz GA_4
        FCALL G_DeferedPlayDemo
        rts

; ---------------------------------------------------------------------------
; s_rinit: the renderer's state at the boot (upstream's: its statics 0,
; validcount 1, the sky flat's pic): the frame block 0 (every persistent
; field of the renderer: the fill stamps, the weapon skip, the vertex
; cache's stamp, FZ_POS, rw_scalestep, the plane colours), VALIDCOUNT 1,
; SKYFLAT the sky's pic byte ($FE: levelconv.py's SKY_PIC), the spans'
; stamps 0, WPREV 0; TEXTRANS the identity (R_GetTexture's texturetranslation
; [n] = n for every texture a load makes; the flow's g_resume sets only
; basepic .. basepic + 2 again, the only ones P_UpdateSpecials changes)
; ---------------------------------------------------------------------------
s_rinit:
        ldx #0
:       txa
        sta TEXTRANS,x
        inx
        bne :-
        ldx #PL_FB_END - FB - 1
:       stz FB,x
        dex
        bpl :-
        lda #1
        sta VALIDCOUNT
        lda #$FE
        sta SKYFLAT
        ldx #FV_SIZE - 1
:       stz WPREV,x
        dex
        bpl :-
        lda #>PL_SPANS
        sta GT_1
        stz GT_0
        lda #0
        ldy #0
:       sta (GT_0),y
        iny
        bne :-
        inc GT_1
        ldx GT_1
        cpx #>PL_SPANS_END
        bne :-
        rts
        .assert <PL_SPANS = 0 && <PL_SPANS_END = 0, error, "the spans' pages"

; ---------------------------------------------------------------------------
; s_level: the level's frame block fields after its load (upstream's
; numnodes, numvertexes and the sky's slots, which the frame reads):
; NUMNODES, NVERT, SKYBANK/SKYLO/SKYHI from
; the map's header in the store (its directory: STORE_DIR_BANK:STORE_DIR).
; A map the directory lacks: GS_ERROR (the load found it: never)
; ---------------------------------------------------------------------------
s_level:
        ldx #STORE_DIR_HEAD     ; the entry of G_GAMEMAP: map, bank, address
@find:  stx GT_4
        lda #STORE_DIR_BANK
        sta FA_BANK
        txa
        clc
        adc #<STORE_DIR
        sta FA_SRC
        lda #>STORE_DIR
        adc #0
        sta FA_SRC+1
        lda #GT_0
        sta FA_DST
        stz FA_DST+1
        lda #PL_DIR_ENTRY
        sta FA_N
        jsr far_get
        lda GT_0
        cmp G_GAMEMAP
        beq @found
        lda GT_4
        clc
        adc #PL_DIR_ENTRY
        tax
        cmp #STORE_DIR_HEAD + PL_DIR_ENTRY * STORE_DIR_MAPS
        bcc @find
        lda #GS_ERROR
        jmp g_stop
@found: lda #LHC_NODES
        ldx #<NUMNODES
        ldy #2
        jsr s_hget
        lda #LHC_VERTICES
        ldx #<NVERT
        ldy #2
        jsr s_hget
        lda #PL_LH_SKY
        ldx #<SKYBANK
        ldy #3
s_hget: clc                     ; Y bytes at the header + A, to page 3's X
        adc GT_2
        sta FA_SRC
        lda GT_3
        adc #0
        sta FA_SRC+1
        lda GT_1
        sta FA_BANK
        stx FA_DST
        lda #>NUMNODES
        sta FA_DST+1
        sty FA_N
        jmp far_get
        .assert >NUMNODES = >NVERT && >NUMNODES = >SKYBANK, error, "page 3"

; the status bar's tic side's scratch block (s2t_st.s: live only inside a
; call; s2t_st calls nothing that pages a group)
st_sb:  .res 32
