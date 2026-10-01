; mmain.s: the masked phase's driver (docs/RENDER-MASKED.md 3.2, 3.3;
; milestone 8). A GPL-2 derivative of Webifi's IIgs DOOM
; (build/upstream/src/iigs/r_frame65.s drawMasked, :180-212).
;
; The phase's image is in W (the caller loaded it with mfar.s's far_mload
; after the front end), then
;
;   nm_masked   the drawseg copy (the drawsegs whose DSX1 is not 255: they
;               clip sprites or hold masked columns, the first DSW_MAX of
;               them in index order into W's DSW, one read window),
;               SPRBOUND into W (SPRB), the projection of the listed
;               sectors' things (mproj.s nm_project), the sort (nm_sort);
;               stage B: the sprites back to front (the sort's order from
;               its end: msprite.s nm_drawsprite, with the masked ranges
;               they uncover), then the drawsegs' masked columns not drawn
;               yet, the last drawseg first (mwall.s nm_mwall), and the
;               last batch of records into the staging; stage C: the weapon
;               and its flash between them (mpsp.s nm_psp: playerSkip).
;               Changes everything of the masked phase.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_get, far_dscopy, dsw_n, dsw_idx
        .import nm_project, nm_sort, nm_drawsprite, nm_mwall, md_dsptr
        .import mrec_flush, nm_vis, md_phdr, vis_lo, vis_hi, nm_psp
.ifdef CLIPLOG
        .import m_hook
.endif
        .export nm_masked, nm_rsetup, nm_visx

.macro MARK n
.ifdef RPROF
        pha
        lda #(n) * 2
        sta PHASE
        pla
.endif
.endmacro

        .segment "MASKW"

nm_masked:
        MARK 14                 ; the drawseg copy (RENDER-MASKED.md 4.4)
        ldx #0                  ; the drawsegs to copy, in index order
        ldy #0
@ds:    cpx DSCOUNT
        beq @copy
        lda DSX1,x
        cmp #$FF
        beq :+
        cpy #DSW_MAX
        bcs @copy
        txa
        sta dsw_idx,y
        iny
:       inx
        bra @ds
@copy:  sty dsw_n
        jsr far_dscopy
        lda #<SPRBOUND_T        ; SPRBOUND (the level's) into W
        sta FA_SRC
        lda #>SPRBOUND_T
        sta FA_SRC+1
        lda #<SPRB
        sta FA_DST
        lda #>SPRB
        sta FA_DST+1
        lda #SPRT
        sta FA_BANK
        lda #4 * NUMSPRITES
        sta FA_N
        jsr far_get
        MARK 11                 ; the projection (upstream's phase 11)
        jsr nm_project
        MARK 15                 ; the sort
        jsr nm_sort
        MARK 4                  ; the sprites and masked walls (upstream's
        jsr md_setup            ;   phase 4)
        lda NVIS                ; for (i = num_vissprite; --i >= 0; )
        sta MD_I                ;   R_DrawSprite(vissprite_ptrs[i])
@spr:   lda MD_I
        beq @segs
        dec MD_I
        ldx MD_I
        lda FRORD,x
        tax
        jsr nm_drawsprite
        bra @spr
@segs:  lda DS_TOT              ; the drawsegs' masked columns, the last
        sta DS_SLOT             ;   first (a drawseg with masked columns
        lda DSCOUNT             ;   has a DSX1 other than 255)
        sta MD_I
@seg:   lda MD_I
        beq @done
        dec MD_I
        ldx MD_I
        lda DSX1,x
        cmp #$FF
        beq @seg
        dec DS_SLOT
        stx DS_K
        jsr md_dsptr
        ldy #DS_MASKED+1
        lda (DS_P),y
        cmp #>DS_NULL
        bne :+
        dey
        lda (DS_P),y
        cmp #<DS_NULL
        beq @seg
:       ldy #DS_X1
        lda (DS_P),y
        sta MW_X
        ldy #DS_X2
        lda (DS_P),y
        sta MW_X2
        jsr nm_mwall
        bra @seg
@done:  MARK 16                 ; the weapon (RENDER-MASKED.md 4.4: 16)
.ifdef CLIPLOG
        jsr m_hook              ; (test builds: the harness's snapshot)
.endif
        jsr nm_psp
        jsr mrec_flush          ; the last batch
        MARK 0
        rts

; ---------------------------------------------------------------------------
; nm_rsetup, nm_visx: routine mode's entries (rdriver.s drv_mroutine): the
; draw phase's constants; R_DrawVisSprite of vissprite X as R_DrawSprite
; calls it (its patch header, the clips FLOORCLIP and CEILCLIP)
; ---------------------------------------------------------------------------
nm_rsetup = md_setup
nm_visx:
        stx DS_IDX
        lda vis_lo,x
        sta DS_VP
        lda vis_hi,x
        sta DS_VP+1
        ldy #VR_X1
        lda (DS_VP),y
        sta SP_X1
        ldy #VR_X2
        lda (DS_VP),y
        sta SP_X2
        ldy #VR_PATCH
        lda (DS_VP),y
        tax
        iny
        lda (DS_VP),y
        jsr md_phdr
        lda #<FLOORCLIP
        sta V_FCP
        lda #>FLOORCLIP
        sta V_FCP+1
        lda #<CEILCLIP
        sta V_CCP
        lda #>CEILCLIP
        sta V_CCP+1
        jmp nm_vis

; ---------------------------------------------------------------------------
; md_setup: the draw phase's constants: an empty batch, the view's clips +
; 1 (viewtop + 1, viewbottom + 1), the drawsegs that clip (DS_TOT), the
; clip log's start
; ---------------------------------------------------------------------------
md_setup:
        stz MRB
        lda VIEWTOP
        inc a
        sta SPRTOP
        lda VIEWBOT
        inc a
        sta SPRBOT
        ldx #0
        ldy #0
@c:     cpx DSCOUNT
        beq @n
        lda DSX1,x
        cmp #$FF
        beq :+
        iny
:       inx
        bra @c
@n:     sty DS_TOT
        stz CL_N
        lda #<SEAM_CLIPLOG
        sta CL_PTR
        lda #>SEAM_CLIPLOG
        sta CL_PTR+1
        rts
