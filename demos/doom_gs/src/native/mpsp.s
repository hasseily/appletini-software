; mpsp.s: the weapon's draw in the native renderer's masked phase
; (docs/RENDER-MASKED.md 3.2 phase 11; milestone 8, stage C). A GPL-2
; derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/r_frame65.s
; playerSkip, playerSprites, psSetup, pspDraw0, pspSprite, :656-854,
; :945-958, :1035-1048; r_sprite65.s wcDraw3, wdDraw, wpCheck, wdProf,
; :794-880, :1303-1448), written for the 65C02.
;
;   nm_psp      playerSkip: in a frame that skips the weapon rows (FR_SKIP)
;               W_WSK = 0, psSetup with mfloorclip = WCLIP, then pspDraw0;
;               else playerSprites: psSetup, pspDraw0 (the weapon), then
;               pspSprite of the flash (psprite 1). pspDraw0: when the clip
;               pass made this frame's weapon (MM_WPOK), wdDraw: its records
;               from its profile (wdProf: each column's posts that start
;               above V_HI, from the lowest up, rows V_YH0 + a to min(V_YH0
;               + b, V_HI), one texture position for all, a step of 1.0),
;               or R_DrawVisSprite when the clip is WCLIP, the lump has no
;               profile or wpStart refuses it; else pspSprite. pspSprite
;               (wpsp.s ps_vis) then R_DrawVisSprite (wcDraw3 with VS_CLIP
;               0; MM_WPOK 0): mvis.s nm_vis on the weapon's vissprite
;               (WVIS: FRVIS with pspSprite's constants: scale 1.0, xiscale
;               2.0, fracstep 512), the clips WCLIP or the view's bottom +
;               1 (CLIPBUF) and 0 (MCCLIP). The records go through the
;               masked copy of rrec.s (the page model), with FSCUT and the
;               covered ranges (mvis.s vtexrec). A test build's clip log
;               names the weapon's calls $FF00 + the psprite.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import mps_vis, mwp_find, mwp_start, mwp_list, mwp_head, nm_vis
        .import md_phdr
        .import vtexrec
        .export nm_psp

        .segment "MASKW"

; ===========================================================================
; nm_psp
; ===========================================================================
nm_psp:
        lda FR_SKIP
        ora FR_SKIP+1
        sta WP_SKIP
        beq @sprites
        stz W_WSK               ; playerSkip: the sprites are done
        ldx #0                  ; pspDraw0 with mfloorclip = WCLIP
        bra pspdraw0
@sprites:
        ldx #0                  ; playerSprites: the weapon, then the flash
        jsr pspdraw0
        ldx #1
        bra pspsprite

; pspdraw0: the weapon (X = 0): its draw from the clip pass's vissprite
; (wdDraw) when MM_WPOK, else pspSprite
pspdraw0:
        lda MM_WPOK
        bne wddraw
pspsprite:
        jsr mps_vis             ; X = the psprite
        bcs @none               ; no state, or off the side
        stz MM_WPOK             ; wcDraw3 (VS_CLIP 0): MM_WPOK 0, then
        jmp visdraw             ;   R_DrawVisSprite
@none:  rts

; wddraw: wdDraw (the clip pass made FRVIS: MM_WPOK), X = 0
wddraw:
        stz MM_WPOK
        stx WP_PSP
        lda WP_SKIP             ; wpCheck: mfloorclip is screenheightarray
        bne visdraw             ;   (not WCLIP)
        lda FRVIS+FV_PAGE       ; not the shadow weapon (the clip pass skips
        beq visdraw             ;   it: never here)
        ; (fracstep 512, the full view, W_WSK 0: always)
        jsr mwp_head            ; the patch's header (the clip pass's copy
        jsr mwp_find            ;   in the front end's W is gone)
        bcs visdraw
        jsr mwp_start
        cmp #1
        beq @done               ; nothing shows
        bcs visdraw             ; the old code
        jmp wdprof
@done:  rts

; ===========================================================================
; visdraw: R_DrawVisSprite of FRVIS, psprite WP_PSP (nm_vis on WVIS)
; ===========================================================================
visdraw:
        ldy #VISREC_SIZE - 1    ; the vissprite: pspSprite's fields and
        lda #0                  ;   constants (the rest nm_vis does not
:       sta WVIS,y              ;   read)
        dey
        bpl :-
        lda FRVIS+FV_X1
        sta WVIS+VR_X1
        sta SP_X1
        lda FRVIS+FV_X2
        sta WVIS+VR_X2
        sta SP_X2
        lda #1                  ; scale 1.0
        sta WVIS+VR_SCALE+2
        lda #2                  ; xiscale 2.0
        sta WVIS+VR_XISCALE+2
        lda FRVIS+FV_SFRAC      ; startfrac: its high word
        sta WVIS+VR_STARTFRAC+2
        lda FRVIS+FV_SFRAC+1
        sta WVIS+VR_STARTFRAC+3
        ldx #3
:       lda FRVIS+FV_TMID,x
        sta WVIS+VR_TMID,x
        dex
        bpl :-
        lda #>512               ; fracstep
        sta WVIS+VR_FSTEP+1
        lda FRVIS+FV_PATCH
        sta WVIS+VR_PATCH
        lda FRVIS+FV_PATCH+1
        sta WVIS+VR_PATCH+1
        lda FRVIS+FV_PAGE
        sta WVIS+VR_PAGE
        lda #<WVIS
        sta DS_VP
        lda #>WVIS
        sta DS_VP+1
        lda WP_PSP              ; (the clip log: $FF00 + the psprite)
        ora #$80
        sta DS_IDX
        ldx FRVIS+FV_PATCH      ; its patch header into PHB
        lda FRVIS+FV_PATCH+1
        jsr md_phdr
        ldx #VIEWWIDTH - 1      ; mceilingclip: negonearray (0 as a clip +
:       stz MCCLIP,x            ;   1); mfloorclip: WCLIP, or
        dex                     ;   screenheightarray (viewbottom + 1)
        cpx #$FF
        bne :-
        lda #<MCCLIP
        sta V_CCP
        lda #>MCCLIP
        sta V_CCP+1
        lda WP_SKIP
        beq @view
        lda #<WCLIP
        sta V_FCP
        lda #>WCLIP
        sta V_FCP+1
        jmp nm_vis
@view:  lda VIEWBOT
        inc a
        ldx #VIEWWIDTH - 1
:       sta CLIPBUF,x
        dex
        cpx #$FF
        bne :-
        lda #<CLIPBUF
        sta V_FCP
        lda #>CLIPBUF
        sta V_FCP+1
        jmp nm_vis

; ===========================================================================
; wdprof: wdProf's records, from the profile WP_K (mwp_start made WP_N
; columns' entries in WPENT)
; ===========================================================================
wdprof:
        lda FRVIS+FV_PAGE       ; W_CMP: the records' page
        sta V_CMP
        lda WPHB+PH_BANK        ; the patch: R_SRC's bank, its address
        sta V_PB
        lda FRVIS+FV_TMID       ; TF, TI: (texturemid >> 7 - (CENTERY + 1)
        asl a                   ;   << 9 + (V_YH0 + 1) << 9) >> 1, 16 bits
        lda FRVIS+FV_TMID+1
        rol a
        sta WP_T
        lda FRVIS+FV_TMID+2
        rol a
        sec
        sbc #>((CENTERY + 1) << 9)
        sta WP_T+1
        lda WP_YH0
        inc a
        asl a
        clc
        adc WP_T+1
        lsr a
        sta WP_TF+1
        lda WP_T
        ror a
        sta WP_TF
        lda WP_YH0              ; V_YH0 - 1
        dec a
        sta WP_YM1
        stz V_S2                ; the step: 1.0 (fracstep >> 1)
        lda #1
        sta V_S2+1
        lda #<WPENT
        sta WP_E
        lda #>WPENT
        sta WP_E+1
        lda FRVIS+FV_X1
        sta WP_X
        lda WP_N
        sta WP_I
@col:   jsr mwp_list
        ldx #0                  ; the lowest post of the column
@post:  lda WPLST,x             ; a + 1 (0: no more posts)
        beq @next
        lda WP_HI               ; hi <= a: at V_HI or below
        cmp WPLST,x
        bcc @up
        lda WPLST,x             ; the rows: V_YH0 + a, min(V_YH0 + b, V_HI)
        clc
        adc WP_YM1
        sta V_YL
        lda WP_HI
        cmp WPLST+1,x
        lda WP_VHI
        bcc :+
        lda WPLST+1,x
        clc
        adc WP_YM1
:       sta V_YH1
        clc                     ; the texels: the patch + their offset (16
        lda WPLST+3,x           ;   bits); vtexrec adds 3 to V_COL
        adc WPHB+PH_ADDR
        tay
        lda WPLST+4,x
        adc WPHB+PH_ADDR+1
        sta V_COL+1
        tya
        sec
        sbc #3
        sta V_COL
        bcs :+
        dec V_COL+1
:       lda WP_TF
        sta V_T
        lda WP_TF+1
        sta V_T+1
        phx
        ldx WP_X
        jsr vtexrec             ; FSCUT, the room, the K_TEX record, CVSET
        plx
@up:    inx                     ; the post above
        inx
        inx
        inx
        inx
        bra @post
@next:  inc WP_X
        clc
        lda WP_E
        adc #2
        sta WP_E
        bcc :+
        inc WP_E+1
:       dec WP_I
        bne @col
        rts
