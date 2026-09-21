; The Bilestoad SHR port: render engine.
;
; The original game logic is unchanged. It runs one logic tick for each
; drawn frame and draws every sprite through one routine (DHD). The port
; replaces the leaf routines:
;
;   CLEAR   begins a display list for the tick
;   DHD     records a sprite (shape, x, y) instead of drawing it
;   SWITCH  shows TICK_FRAMES video frames that move every sprite from its
;           place in the last tick to its place in this tick, then returns
;
; Video timing (Appletini): the renderer publishes the SHR shadow at line 0.
; Each frame is first drawn into an arena in main RAM that the accelerator
; does not mirror. The copy to SHR memory starts at the end of VBL, so the
; whole burst lands between two line-0 snapshots and cannot tear.
;
; Under the vTW, writes to main $0400-$0BFF and $2000-$5FFF and to aux
; $2000-$9FFF use the 1 MHz bus. Hot buffers therefore stay out of those
; ranges, and the draw path makes no $Cxxx access between VBL waits.

; ---------------------------------------------------------------------------
; Hardware
KBD         = $C000
RAMRD_OFF   = $C002
RAMRD_ON    = $C003
RAMWRT_OFF  = $C004
RAMWRT_ON   = $C005
RDVBLBAR    = $C019             ; bit 7 = 0 during vertical blanking
NEWVIDEO    = $C029             ; $C1 = SHR on, $01 = SHR off
TXTCLR      = $C050
TXTSET      = $C051
RWBANK      = $C073             ; RamWorks bank select
LCROM       = $C082             ; read ROM, LC write off
LCRAM2      = $C083             ; two reads: read and write LC RAM bank 2
SHR_PIXELS  = $2000
SHR_SCB     = $9D00
SHR_PALETTE = $9E00

; ---------------------------------------------------------------------------
; Limits and geometry. Coordinates are biased so that they stay positive:
; byte x = pixel x / 2 + 32, row = screen row + 40.
MAXENT      = 64
MAXRECT     = 64
MAXBLIP     = 48                ; one tick asks for about 40 radar blips
PF_X0       = 32                ; playfield: 124 bytes (248 pixels)
PF_X1       = 156
PF_Y0       = 48                ; playfield: screen rows 8-199
PF_Y1       = 240
ROW_BIAS    = 40
HGR_Y_TO_ROW = 12               ; row = YVAL - 36 + 8 + 40
BAND_ROWS   = 32                ; 124 * 32 bytes fits in the arena
BAND_MIN_WIDTH = 21             ; narrower: 192 rows still fit
SPAN_LIMIT  = 10                ; a larger background jump redraws all
TICK_FRAMES = 32                ; video frames for one logic tick
SNAP_DELTA  = 60                ; larger moves are not interpolated
ARENA       = $9C00
ARENA_END   = $BF00
SLOT_BASE   = $D000             ; LC RAM bank 2
SLOT_PAGES  = 2
NSLOTS      = 23
FETCH       = $0110             ; bank fetch routine, in the stack page

GROUND      = $11
WATER       = $22
COL_P1      = $88
COL_P2      = $BB
COL_GOAL    = $EE
COL_OTHER   = $44

; Engine zero page. These are the dropped draw code's temporaries.
SRC         = $05
DST         = $07
TMP         = $09
CNT         = $0B
ROWS        = $10
RX          = $9D               ; current rectangle
RY          = $9E
RW          = $9F
RH          = $A0
IX0         = $A1               ; intersection
IX1         = $A2
IY0         = $A3
IY1         = $A4
EBX         = $A5               ; current entity box
EBY         = $A6
EW          = $A7
EH          = $A8
REC         = $A9               ; directory record pointer
T1          = $AB
T2          = $AC

; ---------------------------------------------------------------------------
.segment "BSS"
cur_n:      .res 1
prv_n:      .res 1
cur_id:     .res MAXENT
cur_occ:    .res MAXENT
cur_shape:  .res MAXENT
cur_x:      .res MAXENT
cur_y:      .res MAXENT
prv_id:     .res MAXENT
prv_occ:    .res MAXENT
prv_shape:  .res MAXENT
prv_x:      .res MAXENT
prv_y:      .res MAXENT
; per tick
e_x0l:      .res MAXENT
e_x0h:      .res MAXENT
e_dx:       .res MAXENT
e_y0:       .res MAXENT
e_dy:       .res MAXENT
e_a0:       .res MAXENT
e_da:       .res MAXENT
e_base:     .res MAXENT         ; rotating set, or small shape number
e_kind:     .res MAXENT         ; 0 rotating, 1 resident
e_group:    .res MAXENT         ; 0/1 fighter, $FF single
e_layer:    .res MAXENT         ; 0 under the water, 1 over it
; per frame, new and old
n_vis:      .res MAXENT
n_bx:       .res MAXENT
n_by:       .res MAXENT
n_w:        .res MAXENT
n_h:        .res MAXENT
n_ptrl:     .res MAXENT
n_ptrh:     .res MAXENT
n_keyl:     .res MAXENT
n_keyh:     .res MAXENT
o_vis:      .res MAXENT
o_bx:       .res MAXENT
o_by:       .res MAXENT
o_w:        .res MAXENT
o_h:        .res MAXENT
o_keyl:     .res MAXENT
o_keyh:     .res MAXENT
o_group:    .res MAXENT
o_n:        .res 1
; drawn state carried from the last tick to the new entity numbers
e_match:    .res MAXENT         ; index in the last tick's list, or $FF
claimed:    .res MAXENT
t_vis:      .res MAXENT
t_bx:       .res MAXENT
t_by:       .res MAXENT
t_w:        .res MAXENT
t_h:        .res MAXENT
t_keyl:     .res MAXENT
t_keyh:     .res MAXENT
t_group:    .res MAXENT
; rectangles
rect_n:     .res 1
rect_x:     .res MAXRECT
rect_y:     .res MAXRECT
rect_w:     .res MAXRECT
rect_h:     .res MAXRECT
rect_pl:    .res MAXRECT
rect_ph:    .res MAXRECT
rect_done:  .res 1
rect_first: .res 1
arena_ptr:  .res 2
; fighter group boxes: min x, min y, max x, max y (max exclusive)
g_used:     .res 2
g_x0:       .res 2
g_y0:       .res 2
g_x1:       .res 2
g_y1:       .res 2
; window and background, per tick and per frame
w_x0:       .res 2
w_y0:       .res 2
w_dx:       .res 1
w_dy:       .res 1
w_x1:       .res 2
w_y1:       .res 2
w_valid:    .res 1
bg_new:     .res 14             ; 4 vertical lines (lo,hi... see bg_calc)
bg_old:     .res 14
frame_k:    .res 1
tick_first: .res 1
cur_layer:  .res 1
full_dirty: .res 1
l_sign:     .res 1
l_m:        .res 2
l_p:        .res 2
l_k:        .res 1
px_l:       .res 1
px_h:       .res 1
py:         .res 1
angle:      .res 1
phase:      .res 1
player_key: .res 1
; sprite slots
slot_keyl:  .res NSLOTS
slot_keyh:  .res NSLOTS
slot_stamp: .res NSLOTS
stamp:      .res 1
; panel
blip_n:     .res 1
blip_x:     .res MAXBLIP
blip_y:     .res MAXBLIP
blip_c:     .res MAXBLIP
oblip_n:    .res 1
oblip_x:    .res MAXBLIP
oblip_y:    .res MAXBLIP
score_old:  .res 4
shr_on:     .res 1
e_site:     .res 1

; bg record layout
BG_VX       = 0                 ; 4 bytes: vertical line byte x (0 = none)
BG_VP       = 4                 ; 4 bytes: vertical line pixel phase
BG_HY       = 8                 ; 4 bytes: horizontal line row (0 = none)
BG_WL       = 12                ; water: left limit, byte x (PF_X0 = none)
BG_WR       = 13                ; water: right start, byte x (PF_X1 = none)
; top and bottom limits follow in bg_wt/bg_wb
.segment "BSS"
bg_wt_new:  .res 1
bg_wb_new:  .res 1
bg_wt_old:  .res 1
bg_wb_old:  .res 1
bg_wlp_new: .res 1              ; pixel phase of the left coast
bg_wrp_new: .res 1
bg_wlp_old: .res 1
bg_wrp_old: .res 1

; ---------------------------------------------------------------------------
.segment "RODATA"

; HGR x (sprite convention, origin 28) to biased SHR pixel x:
; (x - 28) * 8 / 7 + 64 = (8x + 224) / 7
sxt_lo:
.repeat 256, I
    .byte <((8 * I + 224) / 7)
.endrepeat
sxt_hi:
.repeat 256, I
    .byte >((8 * I + 224) / 7)
.endrepeat
; HGR x (grid convention, origin 0) to biased SHR pixel x: 8x / 7 + 64
gxt_lo:
.repeat 256, I
    .byte <((8 * I) / 7 + 64)
.endrepeat
gxt_hi:
.repeat 256, I
    .byte >((8 * I) / 7 + 64)
.endrepeat

; SHR row address (row * 160 + $2000)
rowaddr_lo:
.repeat 200, I
    .byte <(SHR_PIXELS + I * 160)
.endrepeat
rowaddr_hi:
.repeat 200, I
    .byte >(SHR_PIXELS + I * 160)
.endrepeat

; Sprite byte to keep-mask: a zero nibble is clear.
masktab:
.repeat 256, I
    .byte ((I & $F0) = 0) * $F0 + ((I & $0F) = 0) * $0F
.endrepeat

; Player 2 colours: body shades 7,8,9 become 10,11,12.
.macro REMAP_NIBBLE value
    .if (value) >= 7 .and (value) <= 9
        .byte 0
    .endif
.endmacro
remap:
.repeat 256, I
    .byte (((I >> 4) + 3 * (((I >> 4) >= 7) .and ((I >> 4) <= 9))) << 4) | ((I & 15) + 3 * (((I & 15) >= 7) .and ((I & 15) <= 9)))
.endrepeat

; $0RGB colours, little endian.
palette:
    .word $0000                 ; 0 black (grid)
    .word $0151                 ; 1 ground green
    .word $014A                 ; 2 water blue
    .word $037D                 ; 3 water light
    .word $0FFF                 ; 4 white
    .word $0AAA                 ; 5 light grey
    .word $0555                 ; 6 dark grey
    .word $0FD5                 ; 7 player 1 light
    .word $0E82                 ; 8 player 1 mid
    .word $0841                 ; 9 player 1 dark
    .word $0DAF                 ; 10 player 2 light
    .word $095E                 ; 11 player 2 mid
    .word $0428                 ; 12 player 2 dark
    .word $0D11                 ; 13 red
    .word $0FE2                 ; 14 yellow
    .word $0112                 ; 15 sprite black

; 3x5 digits in a 2-byte cell, colour 4.
digits:
    .byte $44,$40, $40,$40, $40,$40, $40,$40, $44,$40   ; 0
    .byte $04,$00, $44,$00, $04,$00, $04,$00, $44,$40   ; 1
    .byte $44,$40, $00,$40, $44,$40, $40,$00, $44,$40   ; 2
    .byte $44,$40, $00,$40, $04,$40, $00,$40, $44,$40   ; 3
    .byte $40,$40, $40,$40, $44,$40, $00,$40, $00,$40   ; 4
    .byte $44,$40, $40,$00, $44,$40, $00,$40, $44,$40   ; 5
    .byte $44,$40, $40,$00, $44,$40, $40,$40, $44,$40   ; 6
    .byte $44,$40, $00,$40, $00,$40, $00,$40, $00,$40   ; 7
    .byte $44,$40, $40,$40, $44,$40, $40,$40, $44,$40   ; 8
    .byte $44,$40, $40,$40, $44,$40, $00,$40, $44,$40   ; 9

; Copied to FETCH. It runs from the stack page because RAMRD does not move
; pages 0 and 1: X = bank, SRC = address in the bank, DST = slot,
; CNT = pages.
fetch_image:
    stx RWBANK
    sta RAMRD_ON
    ldx CNT                     ; pages to copy, 1 to SLOT_PAGES
    ldy #0
@copy:
    lda (SRC),y
    sta (DST),y
    iny
    bne @copy
    inc SRC+1
    inc DST+1
    dex
    bne @copy
    sta RAMRD_OFF
    stz RWBANK
    rts
fetch_image_end:

.include "sprite_dir.inc"
.include "joint_tables.inc"

; ---------------------------------------------------------------------------
.segment "CODE"

; Placeholders for the dropped shift chains. The game still patches them.
MSHI:       .res 16, $60
BSHI:       .res 16, $60

; ---- RELOC: upstream moved the image; the port only sets up state --------
RELOC:
    sei                         ; the port uses no interrupt
    stz SND
    lda #<NOTE
    sta MPL
    lda #>NOTE
    sta MPH
    jsr install_fetch
    lda #$FF
    ldx #NSLOTS - 1
@slots:
    sta slot_keyh,x
    dex
    bpl @slots
    stz cur_n
    stz prv_n
    stz o_n
    stz shr_on
    stz w_valid
    jmp snd_init

install_fetch:
    ldx #fetch_image_end - fetch_image - 1
@copy:
    lda fetch_image,x
    sta FETCH,x
    dex
    bpl @copy
    rts

; ---- text and graphics selection ------------------------------------------
E_HOME:                         ; a text screen follows
    jsr shr_off
    jmp $FC58

GSOLVE:
    jsr shr_off
    rts

shr_off:
    lda #$01
    sta NEWVIDEO
    bit TXTSET
    stz shr_on
    jmp snd_quiet

TSOLVE:                         ; enter graphics
    lda shr_on
    bne @done
    jsr shr_setup
    lda #$C1
    sta NEWVIDEO
    bit TXTCLR
    inc shr_on
@done:
    rts

DSOLVE:                         ; upstream: a page-flip dissolve with clicks
    rts

; Palette, scan-line control bytes, clear screen, panel frame.
shr_setup:
    sta RAMWRT_ON
    ldx #31
@pal:
    lda palette,x
    sta SHR_PALETTE,x
    dex
    bpl @pal
    ldx #199
    lda #$00                    ; 320 mode, palette 0
@scb:
    sta SHR_SCB,x
    dex
    cpx #$FF
    bne @scb
    ; clear all 200 rows
    lda #<SHR_PIXELS
    sta DST
    lda #>SHR_PIXELS
    sta DST+1
    ldx #$7D                    ; $7D00 bytes
    ldy #0
    lda #$00
@clr:
    sta (DST),y
    iny
    bne @clr
    inc DST+1
    dex
    bne @clr
    ; panel: grey field with three black radar boxes
    ldx #8
@prow:
    lda rowaddr_lo,x
    sta DST
    lda rowaddr_hi,x
    sta DST+1
    txa
    sec
    sbc #8
    and #$3F
    cmp #61
    lda #$66
    bcs @fill
    lda #$00
@fill:
    ldy #159
@pcol:
    sta (DST),y
    dey
    cpy #124
    bne @pcol
    lda #$66                    ; left border of the panel
    sta (DST),y
    inx
    cpx #200
    bne @prow
    sta RAMWRT_OFF
    lda #1
    sta full_dirty
    stz o_n
    stz oblip_n
    lda #$FF
    sta score_old
    sta score_old+2
    rts

; ---- display list capture ---------------------------------------------------
CLEAR:                          ; start of a tick
    ldx cur_n
    stx prv_n
    beq @none
    dex
@copy:
    lda cur_id,x
    sta prv_id,x
    lda cur_occ,x
    sta prv_occ,x
    lda cur_shape,x
    sta prv_shape,x
    lda cur_x,x
    sta prv_x,x
    lda cur_y,x
    sta prv_y,x
    dex
    bpl @copy
@none:
    stz cur_n
    stz blip_n
    rts

DRAGRD:                         ; first call of BKGRND: sample sound requests
    jmp snd_sample
DRAOCN:
RADXO:
    rts

; A = call-site id. Inputs HDN, HDX, HDY, STATUS, PLAYER.
E_DHD:
    sta e_site
    lda STATUS
    bne @skip
    lda HDY
    cmp #240
    bcs @skip
    ldx cur_n
    cpx #MAXENT
    bcs @skip
    lda e_site
    ldy PLAYER
    beq :+
    ora #$40
:   sta cur_id,x
    lda HDN
    and #$7F
    sta cur_shape,x
    lda HDX
    sta cur_x,x
    lda HDY
    sta cur_y,x
    jsr count_occurrence
    inc cur_n
@skip:
    rts

; FLOWER calls this with XVAL, YVAL and BLKL (FL1 or FL2).
ONEBOT:
    lda YVAL
    cmp #240
    bcs @skip
    ldx cur_n
    cpx #MAXENT
    bcs @skip
    lda #$3F
    sta cur_id,x
    ldy #$80
    lda BLKL
    cmp #<(FL1-1)
    beq :+
    iny
:   tya
    sta cur_shape,x
    lda XVAL
    sta cur_x,x
    lda YVAL
    sta cur_y,x
    jsr count_occurrence
    inc cur_n
@skip:
    rts

; Entry X is the n-th record with this id in this tick.
count_occurrence:
    stz T1
    txa
    beq @store
    tay
    dey
@scan:
    lda cur_id,y
    cmp cur_id,x
    bne :+
    inc T1
:   dey
    bpl @scan
@store:
    lda T1
    sta cur_occ,x
    rts

; Radar blip. XVAL = x (0-61); YVAL = row (0-60) plus $40 / $80 for the
; second / third box; DRNUM selects the owner.
RADMN:
    ldx blip_n
    cpx #MAXBLIP
    bcs @skip
    lda XVAL
    tay
    lda gxt_lo,y                ; 8x/7 + 64
    sec
    sbc #64
    lsr
    clc
    adc #124
    cmp #158
    bcc :+
    lda #158
:   sta blip_x,x                ; byte x on the screen
    lda YVAL
    and #$3F
    sta T1
    lda YVAL
    and #$C0                    ; $00, $40, $80 = box * 64
    clc
    adc T1
    clc
    adc #8
    sta blip_y,x
    ldy #COL_GOAL
    lda DRNUM
    cmp #$04
    bne :+
    ldy #COL_P1
:   cmp #$0C
    bne :+
    ldy #COL_P2
:   cmp #$08
    bne :+
    ldy #COL_OTHER
:   tya
    sta blip_c,x
    ; The game asks for some blips several times in one tick: keep one.
    txa
    beq @keep
    tay
    dey
@same:
    lda blip_x,y
    cmp blip_x,x
    bne :+
    lda blip_y,y
    cmp blip_y,x
    bne :+
    lda blip_c,x
    sta blip_c,y                ; the later owner wins
    rts
:   dey
    bpl @same
@keep:
    inc blip_n
@skip:
    rts

OUTSCO:
    rts                         ; scores are drawn from SC1/SC2 at SWITCH

; ---- SWITCH: show one tick ---------------------------------------------------
SWITCH:
    lda shr_on
    bne :+
    rts
:   bit LCRAM2                  ; sprite slots live in LC RAM bank 2
    bit LCRAM2
    jsr tick_setup
    lda #1
    sta frame_k
@frame:
    jsr frame_build             ; interpolate, find dirty rectangles
    stz rect_done
@pass:
    jsr render_pass             ; draw rectangles into the arena
    jsr wait_frame_start
    jsr copy_pass               ; burst to SHR memory
    lda rect_done
    cmp rect_n
    bcc @pass
    jsr frame_commit
    jsr snd_frame
    jsr poll_keys
    inc frame_k
    lda frame_k
    cmp #TICK_FRAMES + 1
    bcc @frame
    jsr panel_update
    bit LCROM
    ; Upstream SWITCH flips the page and then clears the new hidden page.
    ; Here that starts the display list of the next tick.
    jmp CLEAR

; End of VBL: the Appletini took its SHR snapshot at line 0 just now.
wait_frame_start:
@in_display:
    bit RDVBLBAR
    bmi @in_display
@in_vbl:
    bit RDVBLBAR
    bpl @in_vbl
    rts

poll_keys:
    lda KBD
    bpl @none
    cmp #$92                    ; CTRL-R restarts through ROM text screens
    bne :+
    bit LCROM
:   jsr PDL
@none:
    rts

; ---- per tick: pair entities and compute the interpolation terms ------------
tick_setup:
    ; window
    lda w_valid
    beq @snap_window
    sec
    lda WINDX
    sbc w_x1
    sta T1
    lda WINDXH
    sbc w_x1+1
    jsr small_delta
    bcs @snap_window
    sta w_dx
    sec
    lda WINDY
    sbc w_y1
    sta T1
    lda WINDYH
    sbc w_y1+1
    jsr small_delta
    bcs @snap_window
    sta w_dy
    lda w_x1
    sta w_x0
    lda w_x1+1
    sta w_x0+1
    lda w_y1
    sta w_y0
    lda w_y1+1
    sta w_y0+1
    bra @window_done
@snap_window:
    stz w_dx
    stz w_dy
    lda WINDX
    sta w_x0
    lda WINDXH
    sta w_x0+1
    lda WINDY
    sta w_y0
    lda WINDYH
    sta w_y0+1
    lda #1
    sta full_dirty
@window_done:
    lda WINDX
    sta w_x1
    lda WINDXH
    sta w_x1+1
    lda WINDY
    sta w_y1
    lda WINDYH
    sta w_y1+1
    lda #1
    sta w_valid

    lda #1
    sta tick_first              ; frame_build erases the last tick's boxes

    ldx #0
@ent:
    cpx cur_n
    bcc :+
    rts
:   jsr find_match              ; Y = index in prv, or $FF
    tya
    sta e_match,x
    ; position at t = 1
    lda cur_x,x
    sty T2
    tay
    lda sxt_lo,y
    sta e_x0l,x
    lda sxt_hi,y
    sta e_x0h,x
    clc
    lda cur_y,x
    adc #HGR_Y_TO_ROW
    sta e_y0,x
    stz e_dx,x
    stz e_dy,x
    ; shape
    lda cur_shape,x
    cmp #SMALL_FIRST
    bcs @resident
    lsr
    lsr
    lsr
    lsr
    sta e_base,x
    stz e_kind,x
    lda cur_shape,x
    and #$0F
    asl
    asl
    sta e_a0,x
    stz e_da,x
    bra @group
@resident:
    sec
    sbc #SMALL_FIRST
    cmp #$10                    ; $80/$81 = flowers
    bcc :+
    sbc #$10
    clc
    adc #FLOWER_FIRST
:   sta e_base,x
    lda #1
    sta e_kind,x
    stz e_a0,x
    stz e_da,x
@group:
    lda #1
    sta e_layer,x
    lda #$FF
    sta e_group,x
    lda cur_id,x
    and #$3F
    cmp #$3F
    bne :+
    stz e_layer,x               ; flowers lie under the water
:   cmp #2
    bcc @pair
    cmp #19
    bcs @pair
    lda cur_id,x
    asl
    asl                         ; carry = player bit ($40)
    lda #0
    rol
    sta e_group,x
@pair:
    ldy T2
    cpy #$FF
    beq @next
    ; x delta in SHR pixels
    lda prv_x,y
    phy
    tay
    sec
    lda e_x0l,x
    sbc sxt_lo,y
    sta T1
    lda e_x0h,x
    sbc sxt_hi,y
    jsr small_delta
    bcs @no_x
    sta e_dx,x
    lda sxt_lo,y
    sta e_x0l,x
    lda sxt_hi,y
    sta e_x0h,x
@no_x:
    ply
    ; y delta
    sec
    lda cur_y,x
    sbc prv_y,y
    sta T1
    lda #0
    sbc #0
    jsr small_delta
    bcs @no_y
    sta e_dy,x
    clc
    lda prv_y,y
    adc #HGR_Y_TO_ROW
    sta e_y0,x
@no_y:
    ; angle delta along the short arc, only inside one rotating set
    lda e_kind,x
    bne @next
    lda prv_shape,y
    eor cur_shape,x
    and #$F0
    bne @next
    lda prv_shape,y
    and #$0F
    sta T1
    lda cur_shape,x
    and #$0F
    sec
    sbc T1
    clc
    adc #8
    and #$0F
    sec
    sbc #8                      ; -8..7
    asl
    asl
    sta e_da,x
    lda T1
    asl
    asl
    sta e_a0,x
@next:
    inx
    jmp @ent

; In: T1 = low byte, A = high byte of a 16-bit difference.
; Out: carry clear and A = signed 8-bit delta when |delta| <= SNAP_DELTA.
small_delta:
    beq @positive
    cmp #$FF
    bne @far
    lda T1
    cmp #256 - SNAP_DELTA
    bcc @far
    clc
    rts
@positive:
    lda T1
    cmp #SNAP_DELTA + 1
    bcs @far
    clc
    rts
@far:
    sec
    rts

; X = current entity. Returns Y = previous entity with the same id and
; occurrence, or $FF.
find_match:
    ldy prv_n
    beq @none
    dey
@scan:
    lda prv_id,y
    cmp cur_id,x
    bne :+
    lda prv_occ,y
    cmp cur_occ,x
    beq @found
:   dey
    bpl @scan
@none:
    ldy #$FF
@found:
    rts

; A = signed delta. Returns A = delta * frame_k / TICK_FRAMES (toward zero).
lerp:
    beq @zero
    sta l_sign
    bpl :+
    eor #$FF
    inc a
:   sta l_m
    stz l_m+1
    stz l_p
    stz l_p+1
    lda frame_k
    sta l_k
@mul:
    lsr l_k
    bcc :+
    clc
    lda l_p
    adc l_m
    sta l_p
    lda l_p+1
    adc l_m+1
    sta l_p+1
:   asl l_m
    rol l_m+1
    lda l_k
    bne @mul
    ldy #5                      ; divide by TICK_FRAMES = 32
@shift:
    lsr l_p+1
    ror l_p
    dey
    bne @shift
    lda l_p
    bit l_sign
    bpl @zero
    eor #$FF
    inc a
@zero:
    rts

; ---- per frame ---------------------------------------------------------------
frame_build:
    stz rect_n
    stz g_used
    stz g_used+1
    inc stamp
    jsr bg_calc
    lda tick_first
    beq @entities
    ; First frame of a tick: the list changed, so entity numbers no longer
    ; match. A paired sprite keeps what the last frame drew for it, under
    ; its new number. Only a sprite with no partner is erased.
    stz tick_first
    jsr carry_drawn_state
@entities:
    ldx #0
@ent:
    cpx cur_n
    bcs @done
    jsr calc_entity
    jsr entity_changed
    bcc @same
    lda o_vis,x
    beq @new_only
    lda n_vis,x
    beq @old_only
    lda e_group,x
    and o_group,x
    cmp #$FF                    ; a single sprite before and now
    bne @old_only
    jsr add_union_box
    bra @same
@old_only:
    jsr add_old_box
@new_only:
    lda n_vis,x
    beq @same
    jsr add_new_box
@same:
    inx
    bra @ent
@done:
    jsr flush_groups
    lda full_dirty
    beq :+
    stz rect_n                  ; the bands cover every other rectangle
    jsr add_full_playfield
    stz full_dirty
:   rts

carry_drawn_state:
    ldx #MAXENT - 1
@reset:
    stz claimed,x
    stz t_vis,x
    dex
    bpl @reset
    ldx #0
@take:
    cpx cur_n
    bcs @erase
    ldy e_match,x
    cpy o_n                     ; $FF (no partner) is also >= o_n
    bcs @next
    lda #1
    sta claimed,y
    lda o_vis,y
    sta t_vis,x
    lda o_bx,y
    sta t_bx,x
    lda o_by,y
    sta t_by,x
    lda o_w,y
    sta t_w,x
    lda o_h,y
    sta t_h,x
    lda o_keyl,y
    sta t_keyl,x
    lda o_keyh,y
    sta t_keyh,x
    lda o_group,y
    sta t_group,x
@next:
    inx
    bra @take
@erase:
    ldx o_n
    beq @store
    dex
@old:
    lda o_vis,x
    beq :+
    lda claimed,x
    bne :+
    jsr add_old_box
:   dex
    bpl @old
@store:
    ldx #MAXENT - 1
@copy:
    lda t_vis,x
    sta o_vis,x
    lda t_bx,x
    sta o_bx,x
    lda t_by,x
    sta o_by,x
    lda t_w,x
    sta o_w,x
    lda t_h,x
    sta o_h,x
    lda t_keyl,x
    sta o_keyl,x
    lda t_keyh,x
    sta o_keyh,x
    lda t_group,x
    sta o_group,x
    dex
    bpl @copy
    lda cur_n
    sta o_n
    rts

flush_groups:
    ldy #1
@group:
    lda g_used,y
    beq @skip
    lda g_x0,y
    sta RX
    lda g_y0,y
    sta RY
    sec
    lda g_x1,y
    sbc g_x0,y
    sta RW
    sec
    lda g_y1,y
    sbc g_y0,y
    sta RH
    phy
    jsr push_rect
    ply
    lda #0
    sta g_used,y
@skip:
    dey
    bpl @group
    rts

; carry set when entity X differs from what the last frame drew
entity_changed:
    lda n_vis,x
    cmp o_vis,x
    bne @yes
    lda n_vis,x
    beq @no
    lda n_bx,x
    cmp o_bx,x
    bne @yes
    lda n_by,x
    cmp o_by,x
    bne @yes
    lda n_keyl,x
    cmp o_keyl,x
    bne @yes
    lda n_keyh,x
    cmp o_keyh,x
    bne @yes
@no:
    clc
    rts
@yes:
    sec
    rts

; One rectangle around the old and the new box of single sprite X.
add_union_box:
    lda o_bx,x
    cmp n_bx,x
    bcc :+
    lda n_bx,x
:   sta EBX
    clc
    lda o_bx,x
    adc o_w,x
    sta T1
    clc
    lda n_bx,x
    adc n_w,x
    cmp T1
    bcs :+
    lda T1
:   sec
    sbc EBX
    sta EW
    lda o_by,x
    cmp n_by,x
    bcc :+
    lda n_by,x
:   sta EBY
    clc
    lda o_by,x
    adc o_h,x
    bcc :+
    lda #$FF
:   sta T1
    clc
    lda n_by,x
    adc n_h,x
    bcc :+
    lda #$FF
:   cmp T1
    bcs :+
    lda T1
:   sec
    sbc EBY
    sta EH
    ldy #$FF
    jmp add_box

add_old_box:
    lda o_bx,x
    sta EBX
    lda o_by,x
    sta EBY
    lda o_w,x
    sta EW
    lda o_h,x
    sta EH
    ldy o_group,x
    jmp add_box
add_new_box:
    lda n_bx,x
    sta EBX
    lda n_by,x
    sta EBY
    lda n_w,x
    sta EW
    lda n_h,x
    sta EH
    ldy e_group,x
; Y = group (0, 1 or $FF). Box in EBX, EBY, EW, EH.
add_box:
    cpy #$FF
    bne @grouped
    lda EBX
    sta RX
    lda EBY
    sta RY
    lda EW
    sta RW
    lda EH
    sta RH
    phx
    jsr push_rect
    plx
    rts
@grouped:
    clc
    lda EBX
    adc EW
    sta T1                      ; right
    clc
    lda EBY
    adc EH
    bcc :+
    lda #$FF
:   sta T2                      ; bottom
    lda g_used,y
    bne @merge
    lda #1
    sta g_used,y
    lda EBX
    sta g_x0,y
    lda EBY
    sta g_y0,y
    lda T1
    sta g_x1,y
    lda T2
    sta g_y1,y
    rts
@merge:
    lda EBX
    cmp g_x0,y
    bcs :+
    sta g_x0,y
:   lda EBY
    cmp g_y0,y
    bcs :+
    sta g_y0,y
:   lda T1
    cmp g_x1,y
    bcc :+
    sta g_x1,y
:   lda T2
    cmp g_y1,y
    bcc :+
    sta g_y1,y
:   rts

add_full_playfield:
    lda #PF_Y0
    sta T2
@band:
    lda #PF_X0
    sta RX
    lda T2
    sta RY
    lda #PF_X1 - PF_X0
    sta RW
    lda #32
    sta RH
    lda T2
    pha
    jsr push_rect
    pla
    clc
    adc #32
    sta T2
    cmp #PF_Y1
    bcc @band
    rts

; Clip RX, RY, RW, RH to the playfield and store the rectangle.
push_rect:
    ldx rect_n
    cpx #MAXRECT
    bcc :+
    rts                         ; list full: drop
:
    ; right and bottom
    clc
    lda RX
    adc RW
    bcc :+
    lda #$FF
:   cmp #PF_X1
    bcc :+
    lda #PF_X1
:   sta T1
    clc
    lda RY
    adc RH
    bcc :+
    lda #$FF
:   cmp #PF_Y1
    bcc :+
    lda #PF_Y1
:   sta T2
    lda RX
    cmp #PF_X0
    bcs :+
    lda #PF_X0
:   sta RX
    lda RY
    cmp #PF_Y0
    bcs :+
    lda #PF_Y0
:   sta RY
    sec
    lda T1
    sbc RX
    beq @empty
    bcs :+
@empty:
    rts                         ; nothing of it is in the playfield
:   sta rect_w,x
    sec
    lda T2
    sbc RY
    bcc @drop
    beq @drop
    sta RH
    ; Several sprites can share one place (the five flowers start that
    ; way): keep one copy of a rectangle.
    sec
    lda T1
    sbc RX
    sta T2                      ; width
    txa
    beq @unique
    tay
    dey
@same:
    lda rect_x,y
    cmp RX
    bne :+
    lda rect_y,y
    cmp RY
    bne :+
    lda rect_w,y
    cmp T2
    bne :+
    lda rect_h,y
    cmp RH
    bne :+
    rts
:   dey
    bpl @same
@unique:
    lda RX
    sta rect_x,x
    ; A rectangle must fit in the arena: wide ones are cut into bands.
@band:
    lda RY
    sta rect_y,x
    lda RH
    ldy rect_w,x
    cpy #BAND_MIN_WIDTH
    bcc @whole
    cmp #BAND_ROWS + 1
    bcc @whole
    lda #BAND_ROWS
@whole:
    sta rect_h,x
    inc rect_n
    sta T1
    sec
    lda RH
    sbc T1
    sta RH
    beq @drop
    clc
    lda RY
    adc T1
    sta RY
    ldy rect_w,x
    lda rect_x,x
    inx
    cpx #MAXRECT
    bcs @drop
    sta rect_x,x
    tya
    sta rect_w,x
    bra @band
@drop:
    rts

; Compute the screen box and the sprite of entity X for this frame.
calc_entity:
    stz n_vis,x
    ; x
    lda e_dx,x
    jsr lerp
    sta T1
    ldy #0
    ora #0
    bpl :+
    dey
:   clc
    lda e_x0l,x
    adc T1
    sta px_l
    tya
    adc e_x0h,x
    sta px_h
    ; y
    lda e_dy,x
    jsr lerp
    clc
    adc e_y0,x
    sta py
    ; directory record
    lda e_kind,x
    bne @resident
    lda e_da,x
    jsr lerp
    clc
    adc e_a0,x
    and #$3F
    sta angle
    lda e_base,x                ; index = set * 64 + angle
    lsr
    lsr
    sta T2
    lda e_base,x
    asl
    asl
    asl
    asl
    asl
    asl
    ora angle
    sta T1
    lda #<sprdir
    sta REC
    lda #>sprdir
    sta REC+1
    bra @record
@resident:
    lda e_base,x
    sta T1
    stz T2
    lda #<smalldir
    sta REC
    lda #>smalldir
    sta REC+1
@record:
    lda T1
    sta n_keyl,x
    lda T2
    sta n_keyh,x
    ; REC += index * 10 (SPRDIR_RECORD)
    asl T1
    rol T2                      ; * 2
    jsr @add_index
    asl T1
    rol T2
    asl T1
    rol T2                      ; * 8
    jsr @add_index
    bra @indexed
@add_index:
    clc
    lda REC
    adc T1
    sta REC
    lda REC+1
    adc T2
    sta REC+1
    rts
@indexed:
    ; left = px - hot x (signed)
    ldy #8
    lda (REC),y
    sta T1
    ldy #0
    ora #0
    bpl :+
    dey
:   sty T2
    sec
    lda px_l
    sbc T1
    sta px_l
    lda px_h
    sbc T2
    sta px_h
    cmp #2
    bcc :+
    rts                         ; negative or beyond 511: hidden
:
    lda px_l
    and #1
    sta phase
    lsr px_h
    lda px_l
    ror
    sta n_bx,x
    ; top = py - hot y
    ldy #9
    lda (REC),y
    bmi @hot_negative
    sta T1
    sec
    lda py
    sbc T1
    bcc @hidden
    bra @top
@hot_negative:
    eor #$FF
    inc a
    clc
    adc py
    bcs @hidden
@top:
    sta n_by,x
    cmp #PF_Y1
    bcs @hidden
    ldy #7
    lda (REC),y
    sta n_h,x
    clc
    adc n_by,x
    bcs :+
    cmp #PF_Y0 + 1
    bcc @hidden
:   clc
    lda #5
    adc phase
    tay
    lda (REC),y
    sta n_w,x
    clc
    adc n_bx,x
    bcs :+
    cmp #PF_X0 + 1
    bcc @hidden
:   lda n_bx,x
    cmp #PF_X1
    bcs @hidden
    ; the key also holds the x phase and the owner's colours
    lda phase
    lsr
    lda n_keyh,x
    bcc :+
    ora #$40
:   ldy e_group,x
    cpy #1
    bne :+
    ora #$20
:   sta n_keyh,x
    jsr sprite_data
    lda #1
    sta n_vis,x
@hidden:
    rts

; REC = directory record. Sets n_ptrl/n_ptrh for entity X.
sprite_data:
    lda phase
    asl
    inc a                       ; address at 1 (even x) or 3 (odd x)
    tay
    lda (REC),y
    sta SRC
    iny
    lda (REC),y
    sta SRC+1
    lda (REC)                   ; bank, 0 = resident
    bne @banked
    lda SRC
    sta n_ptrl,x
    lda SRC+1
    sta n_ptrh,x
    rts
@banked:
    sta T1                      ; bank
    ; look for the sprite in the slots
    ldy #NSLOTS - 1
@find:
    lda slot_keyl,y
    cmp n_keyl,x
    bne :+
    lda slot_keyh,y
    cmp n_keyh,x
    beq @hit
:   dey
    bpl @find
    ; miss: take the slot that was used longest ago
    ldy #NSLOTS - 1
    stz T2
    phx
    ldx #0
@oldest:
    sec
    lda stamp
    sbc slot_stamp,y
    cmp T2
    bcc :+
    sta T2
    tya
    tax
:   dey
    bpl @oldest
    txa
    tay
    plx
    lda n_keyl,x
    sta slot_keyl,y
    lda n_keyh,x
    sta slot_keyh,y
    jsr slot_address
    ; pages = high byte of (width * height) + 1
    lda n_w,x
    sta l_m
    lda n_h,x
    sta l_k
    jsr mul8
    lda l_p+1
    inc a
    sta CNT
    sta ROWS                    ; kept for the recolour pass
    phx
    phy
    ldx T1
    jsr FETCH
    ply
    plx
    lda n_keyh,x
    and #$20
    beq @hit
    jsr slot_address            ; player 2: change the body colours
    phx
    phy
    ldx ROWS
    ldy #0
@recolour:
    lda (DST),y
    beq :+
    phx
    tax
    lda remap,x
    plx
    sta (DST),y
:   iny
    bne @recolour
    inc DST+1
    dex
    bne @recolour
    ply
    plx
@hit:
    lda stamp
    sta slot_stamp,y
    jsr slot_address
    lda DST
    sta n_ptrl,x
    lda DST+1
    sta n_ptrh,x
    rts

; Y = slot. DST = slot address.
slot_address:
    stz DST
    tya
    asl                         ; SLOT_PAGES = 2
    clc
    adc #>SLOT_BASE
    sta DST+1
    rts

frame_commit:
    ldx cur_n
    beq @bg
    dex
@copy:
    lda n_vis,x
    sta o_vis,x
    lda n_bx,x
    sta o_bx,x
    lda n_by,x
    sta o_by,x
    lda n_w,x
    sta o_w,x
    lda n_h,x
    sta o_h,x
    lda n_keyl,x
    sta o_keyl,x
    lda n_keyh,x
    sta o_keyh,x
    lda e_group,x
    sta o_group,x
    dex
    bpl @copy
@bg:
    ldx #13
@bgcopy:
    lda bg_new,x
    sta bg_old,x
    dex
    bpl @bgcopy
    lda bg_wt_new
    sta bg_wt_old
    lda bg_wb_new
    sta bg_wb_old
    lda bg_wlp_new
    sta bg_wlp_old
    lda bg_wrp_new
    sta bg_wrp_old
    rts

; ---- background: grid lines and water from the window position --------------
; The window moves with the fighters. Grid lines sit at offsets $20, $60,
; $A0, $E0 of each 256-pixel tile, and show only when the tile number has
; the matching bit set (a binary position aid, as upstream).
bg_calc:
    ; interpolated window -> T: wx in px_l/px_h, wy in T1/T2
    lda w_dx
    jsr lerp
    sta T1
    ldy #0
    ora #0
    bpl :+
    dey
:   clc
    lda w_x0
    adc T1
    sta px_l
    tya
    adc w_x0+1
    sta px_h
    lda w_dy
    jsr lerp
    sta T1
    ldy #0
    ora #0
    bpl :+
    dey
:   clc
    lda w_y0
    adc T1
    sta py
    tya
    adc w_y0+1
    sta angle                   ; wy high

    ldx #3
@lines:
    stz bg_new + BG_VX,x
    stz bg_new + BG_HY,x
    ; vertical: tile = wxh + (wxl >= offset)
    sec
    lda px_l
    sbc grid_offset,x
    eor #$FF
    ora #1
    sta T1                      ; XVAL
    lda px_h
    adc #0
    and grid_bit,x
    beq @horizontal
    lda T1
    cmp #217
    bcs @horizontal
    tay
    lda gxt_hi,y
    lsr
    lda gxt_lo,y
    pha
    ror
    sta bg_new + BG_VX,x
    pla
    and #1
    sta bg_new + BG_VP,x
@horizontal:
    sec
    lda py
    sbc grid_offset,x
    eor #$FF
    and #$FE
    sta T1
    lda angle
    adc #0
    and grid_bit,x
    beq @next
    lda T1
    cmp #192
    bcs @next
    clc
    adc #PF_Y0
    sta bg_new + BG_HY,x
@next:
    dex
    bpl @lines

    ; water: outside the island rectangle of the OCEAN table
    lda #PF_X0
    sta bg_new + BG_WL
    stz bg_wlp_new
    lda px_h
    cmp OCEAN
    bcs @right
    lda px_l
    eor #$FF                    ; 255 - wxl
    jsr grid_x_to_byte
    sta bg_new + BG_WL
    sty bg_wlp_new
@right:
    lda #PF_X1
    sta bg_new + BG_WR
    stz bg_wrp_new
    lda px_h
    cmp OCEAN+1
    bcc @top
    sec
    lda #216
    sbc px_l
    bcs :+
    lda #0
:   jsr grid_x_to_byte
    sta bg_new + BG_WR
    sty bg_wrp_new
@top:
    lda #PF_Y0
    sta bg_wt_new
    lda angle
    cmp OCEAN+2
    bcs @bottom
    lda py
    eor #$FF
    cmp #192
    bcc :+
    lda #192
:   clc
    adc #PF_Y0
    sta bg_wt_new
@bottom:
    lda #PF_Y1
    sta bg_wb_new
    lda angle
    cmp OCEAN+3
    bcc @dirty
    sec
    lda #192
    sbc py
    bcs :+
    lda #0
:   clc
    adc #PF_Y0
    sta bg_wb_new

@dirty:
    ; any change of the background redraws the whole playfield band set.
    ldx #13
@compare:
    lda bg_new,x
    cmp bg_old,x
    bne @changed
    dex
    bpl @compare
    lda bg_wt_new
    cmp bg_wt_old
    bne @changed
    lda bg_wb_new
    cmp bg_wb_old
    bne @changed
    lda bg_wlp_new
    cmp bg_wlp_old
    bne @changed
    lda bg_wrp_new
    cmp bg_wrp_old
    bne @changed
    rts
@changed:
    jmp bg_dirty

grid_offset: .byte $20, $60, $A0, $E0
grid_bit:    .byte 1, 2, 4, 8

; A = HGR x, grid convention. Returns A = biased byte x, Y = pixel phase.
grid_x_to_byte:
    tay
    lda gxt_lo,y
    and #1
    pha
    lda gxt_hi,y
    lsr
    lda gxt_lo,y
    ror
    cmp #PF_X1
    bcc :+
    lda #PF_X1
:   ply
    rts

; Dirty strips for each background item that moved: old and new place.
bg_dirty:
    ldx #3
@vertical:
    lda bg_new + BG_VX,x
    cmp bg_old + BG_VX,x
    bne @v_moved
    lda bg_new + BG_VP,x
    cmp bg_old + BG_VP,x
    beq @v_next
@v_moved:
    lda bg_old + BG_VX,x
    ldy bg_new + BG_VX,x
    jsr column_pair
@v_next:
    lda bg_new + BG_HY,x
    cmp bg_old + BG_HY,x
    beq @h_next
    lda bg_old + BG_HY,x
    ldy bg_new + BG_HY,x
    jsr row_pair
@h_next:
    dex
    bpl @vertical
    ; coasts
    lda bg_new + BG_WL
    cmp bg_old + BG_WL
    bne @wl
    lda bg_wlp_new
    cmp bg_wlp_old
    beq @wr_test
@wl:
    lda bg_old + BG_WL
    ldy bg_new + BG_WL
    jsr column_span
@wr_test:
    lda bg_new + BG_WR
    cmp bg_old + BG_WR
    bne @wr
    lda bg_wrp_new
    cmp bg_wrp_old
    beq @wt_test
@wr:
    lda bg_old + BG_WR
    ldy bg_new + BG_WR
    jsr column_span
@wt_test:
    lda bg_wt_new
    cmp bg_wt_old
    beq @wb_test
    ldy bg_wt_old
    jsr row_span
@wb_test:
    lda bg_wb_new
    cmp bg_wb_old
    beq @done
    ldy bg_wb_old
    jsr row_span
@done:
    rts

; A = old, Y = new byte x of a grid line (0 = none). A line moves by a pixel
; or two, so one strip covers both places. Keeps X.
column_pair:
    sta T1
    sty T2
    cmp #0
    beq @single
    cpy #0
    beq @single
    cmp T2
    bcc :+
    sty T1                      ; T1 = left, T2 = right
    sta T2
:   sec
    lda T2
    sbc T1
    cmp #3
    bcs @apart
    clc
    adc #2
    sta RW
    lda T1
    sta RX
    lda #PF_Y0
    sta RY
    lda #PF_Y1 - PF_Y0
    sta RH
    phx
    jsr push_rect
    plx
    rts
@apart:
    lda T2
    pha
    lda T1
    jsr column_strip
    pla
    jmp column_strip
@single:
    lda T1
    ora T2                      ; one of them is 0
    jmp column_strip

; The same for a horizontal line: A = old, Y = new row. Keeps X.
row_pair:
    sta T1
    sty T2
    cmp #0
    beq @single
    cpy #0
    beq @single
    cmp T2
    bcc :+
    sty T1
    sta T2
:   sec
    lda T2
    sbc T1
    cmp #3
    bcs @apart
    clc
    adc #1
    sta RH
    lda T1
    sta RY
    lda #PF_X0
    sta RX
    lda #PF_X1 - PF_X0
    sta RW
    phx
    jsr push_rect
    plx
    rts
@apart:
    lda T2
    pha
    lda T1
    jsr row_strip
    pla
    jmp row_strip
@single:
    lda T1
    ora T2
    jmp row_strip

; A = byte x of a grid line (0 = none): a strip 2 bytes wide, full height.
column_strip:
    beq @none
    sta RX
    lda #2
    sta RW
    lda #PF_Y0
    sta RY
    lda #PF_Y1 - PF_Y0
    sta RH
    phx
    jsr push_rect
    plx
@none:
    rts

row_strip:
    beq @none
    sta RY
    lda #1
    sta RH
    lda #PF_X0
    sta RX
    lda #PF_X1 - PF_X0
    sta RW
    phx
    jsr push_rect
    plx
@none:
    rts

; Columns between byte x A and Y (either order), full height, plus 1 byte.
column_span:
    sty T1
    cmp T1
    bcc :+
    pha
    lda T1
    ply
    sty T1
:   sta RX
    sec
    lda T1
    sbc RX
    cmp #SPAN_LIMIT
    bcs span_too_large
    clc
    adc #2
    sta RW
    lda #PF_Y0
    sta RY
    lda #PF_Y1 - PF_Y0
    sta RH
    jmp push_rect

span_too_large:
    lda #1
    sta full_dirty
    rts

; Rows between A and Y (either order), full width.
row_span:
    sty T1
    cmp T1
    bcc :+
    pha
    lda T1
    ply
    sty T1
:   sta RY
    sec
    lda T1
    sbc RY
    cmp #SPAN_LIMIT
    bcs span_too_large
    clc
    adc #1
    sta RH
    lda #PF_X0
    sta RX
    lda #PF_X1 - PF_X0
    sta RW
    jmp push_rect

; ---- render rectangles into the arena ---------------------------------------
render_pass:
    lda #<ARENA
    sta arena_ptr
    lda #>ARENA
    sta arena_ptr+1
    lda rect_done
    sta rect_first
@next:
    ldx rect_done
    cpx rect_n
    bcs @full
    ; size = w * h
    lda rect_w,x
    sta l_m
    stz l_m+1
    stz l_p
    stz l_p+1
    lda rect_h,x
    sta l_k
@mul:
    lsr l_k
    bcc :+
    clc
    lda l_p
    adc l_m
    sta l_p
    lda l_p+1
    adc l_m+1
    sta l_p+1
:   asl l_m
    rol l_m+1
    lda l_k
    bne @mul
    clc
    lda arena_ptr
    adc l_p
    sta T1
    lda arena_ptr+1
    adc l_p+1
    sta T2
    cmp #>ARENA_END
    bcs @full
    lda arena_ptr
    sta rect_pl,x
    lda arena_ptr+1
    sta rect_ph,x
    lda T1
    sta arena_ptr
    lda T2
    sta arena_ptr+1
    jsr render_rect
    inc rect_done
    bra @next
@full:
    rts

; Row walking for the current rectangle. TMP = row pointer.
first_row:
    lda DST
    sta TMP
    lda DST+1
    sta TMP+1
    rts

next_row:
    clc
    lda TMP
    adc RW
    sta TMP
    bcc :+
    inc TMP+1
:   rts

; A = row index in the rectangle. TMP = DST + A * RW. Keeps X.
row_pointer:
    sta l_k
    lda RW
    sta l_m
    jsr mul8
    clc
    lda DST
    adc l_p
    sta TMP
    lda DST+1
    adc l_p+1
    sta TMP+1
    rts

; l_p = l_m * l_k (8 x 8 bits). Keeps X and Y.
mul8:
    stz l_m+1
    stz l_p
    stz l_p+1
@bit:
    lsr l_k
    bcc :+
    clc
    lda l_p
    adc l_m
    sta l_p
    lda l_p+1
    adc l_m+1
    sta l_p+1
:   asl l_m
    rol l_m+1
    lda l_k
    bne @bit
    rts

; Y = column, A = mask: AND the mask into that column on every row.
column_and:
    sta T2
    lda #0
; Y = column, T2 = keep mask, A = bits to set, on every row. Keeps X.
column_mix:
    sta l_sign
    phx
    jsr first_row
    ldx RH
@row:
    lda (TMP),y
    and T2
    ora l_sign
    sta (TMP),y
    jsr next_row
    dex
    bne @row
    plx
    rts

; X = row count, TMP = first row: fill whole rows with water.
water_rows:
    lda #WATER
    ldy RW
    dey
@fill:
    sta (TMP),y
    dey
    bpl @fill
    jsr next_row
    dex
    bne water_rows
    rts

; X = rectangle index.
render_rect:
    lda rect_x,x
    sta RX
    lda rect_y,x
    sta RY
    lda rect_w,x
    sta RW
    lda rect_h,x
    sta RH
    lda rect_pl,x
    sta DST
    lda rect_ph,x
    sta DST+1
    phx
    ; Background. Each grid line and coast is tested once for the
    ; rectangle, not once for each row: most rectangles are thin strips,
    ; 192 rows high, and the per-row tests were the main cost of a scroll
    ; frame. Order as upstream: ground, grid, then water over both.
    ; 1: ground
    jsr first_row
    ldx RH
@ground_row:
    lda #GROUND
    ldy RW
    dey
@ground:
    sta (TMP),y
    dey
    bpl @ground
    clc
    lda TMP
    adc RW
    sta TMP
    bcc :+
    inc TMP+1
:   dex
    bne @ground_row
    ; 2: horizontal grid lines
    ldx #3
@hline:
    lda bg_new + BG_HY,x
    beq @hline_next
    sec
    sbc RY
    bcc @hline_next
    cmp RH
    bcs @hline_next
    jsr row_pointer
    lda #$00
    ldy RW
    dey
@hline_fill:
    sta (TMP),y
    dey
    bpl @hline_fill
@hline_next:
    dex
    bpl @hline
    ; 3: vertical grid lines, 2 pixels wide. With an odd pixel phase the
    ; line covers the low nibble of one byte and the high nibble of the next.
    ldx #3
@vline:
    lda bg_new + BG_VX,x
    beq @vline_next
    sec
    sbc RX
    sta T1                      ; column in the rectangle, $FF = one left
    lda bg_new + BG_VP,x
    bne @vline_odd
    ldy T1
    cpy RW
    bcs @vline_next
    lda #$00
    jsr column_and
    bra @vline_next
@vline_odd:
    ldy T1
    cpy RW
    bcs :+
    lda #$F0
    jsr column_and
:   ldy T1
    iny
    cpy RW
    bcs @vline_next
    lda #$0F
    jsr column_and
@vline_next:
    dex
    bpl @vline
    ; 4: flowers lie under the water, as upstream
    lda #0
    jsr draw_layer
    ; 5: water. Rows above the north coast and below the south coast.
    sec
    lda bg_wt_new
    sbc RY
    bcc @south
    beq @south
    cmp RH
    bcc :+
    lda RH
:   tax
    jsr first_row
    jsr water_rows
@south:
    sec
    lda bg_wb_new
    sbc RY
    bcs :+
    lda #0
:   cmp RH
    bcs @west
    pha
    jsr row_pointer
    pla
    eor #$FF
    sec
    adc RH                      ; rows = RH - start
    tax
    jsr water_rows
@west:
    ; columns left of the west coast
    sec
    lda bg_new + BG_WL
    sbc RX
    bcc @east
    cmp RW
    bcc :+
    lda RW
:   sta T1                      ; whole water columns
    cmp #0                      ; STA sets no flags
    beq @west_edge
    jsr first_row
    ldx RH
@west_row:
    lda #WATER
    ldy T1
    dey
@west_fill:
    sta (TMP),y
    dey
    bpl @west_fill
    jsr next_row
    dex
    bne @west_row
@west_edge:
    lda bg_wlp_new
    beq @east
    ldy T1
    cpy RW
    bcs @east
    lda #$0F                    ; keep the right pixel, left pixel = water
    sta T2
    lda #WATER & $F0
    jsr column_mix
@east:
    ; columns from the east coast to the right edge
    stz T2
    sec
    lda bg_new + BG_WR
    sbc RX
    bcs :+
    lda #0                      ; the coast is left of the rectangle
    bra @east_start
:   cmp RW
    bcs @background_done
    ldy bg_wrp_new
    beq @east_start
    pha                         ; odd phase: right pixel of this byte
    tay
    lda #$F0
    sta T2
    lda #WATER & $0F
    jsr column_mix
    pla
    inc a
    cmp RW
    bcs @background_done
@east_start:
    sta T1
    jsr first_row
    ldx RH
@east_row:
    lda #WATER
    ldy T1
@east_fill:
    sta (TMP),y
    iny
    cpy RW
    bcc @east_fill
    jsr next_row
    dex
    bne @east_row
@background_done:
    ; 6: sprites over the water, in the game's draw order
    lda #1
    jsr draw_layer
    plx
    rts

; A = layer. Draw every visible sprite of that layer into the rectangle.
draw_layer:
    sta cur_layer
    ldx #0
@sprite:
    cpx cur_n
    bcs @done
    lda n_vis,x
    beq @next
    lda e_layer,x
    cmp cur_layer
    bne @next
    jsr blit_clipped
@next:
    inx
    bra @sprite
@done:
    rts

; Draw entity X into the rectangle (RX, RY, RW, RH at rect_pl/ph), clipped.
blit_clipped:
    ; horizontal overlap
    lda n_bx,x
    sta IX0
    clc
    adc n_w,x
    bcc :+
    lda #$FF
:   sta IX1
    clc
    lda RX
    adc RW
    cmp IX1
    bcs :+
    sta IX1
:   lda RX
    cmp IX0
    bcc :+
    sta IX0
:   lda IX0
    cmp IX1
    bcc :+
    rts
:   ; vertical overlap
    lda n_by,x
    sta IY0
    clc
    adc n_h,x
    bcc :+
    lda #$FF
:   sta IY1
    clc
    lda RY
    adc RH
    cmp IY1
    bcs :+
    sta IY1
:   lda RY
    cmp IY0
    bcc :+
    sta IY0
:   lda IY0
    cmp IY1
    bcc :+
    rts
:   phx
    ; SRC = data + (IY0 - by) * w + (IX0 - bx)
    lda n_w,x
    sta EW
    sec
    lda IY0
    sbc n_by,x
    sta l_k
    lda n_ptrl,x
    sta SRC
    lda n_ptrh,x
    sta SRC+1
    sec
    lda IX0
    sbc n_bx,x
    clc
    adc SRC
    sta SRC
    bcc :+
    inc SRC+1
:   lda l_k
    beq @src_done
@src_rows:
    clc
    lda SRC
    adc EW
    sta SRC
    bcc :+
    inc SRC+1
:   dec l_k
    bne @src_rows
@src_done:
    ; TMP = rect + (IY0 - RY) * RW + (IX0 - RX)
    ldx rect_done
    lda rect_pl,x
    sta TMP
    lda rect_ph,x
    sta TMP+1
    sec
    lda IX0
    sbc RX
    clc
    adc TMP
    sta TMP
    bcc :+
    inc TMP+1
:   sec
    lda IY0
    sbc RY
    beq @dst_done
    sta l_k
@dst_rows:
    clc
    lda TMP
    adc RW
    sta TMP
    bcc :+
    inc TMP+1
:   dec l_k
    bne @dst_rows
@dst_done:
    sec
    lda IX1
    sbc IX0
    sta CNT
    sec
    lda IY1
    sbc IY0
    sta ROWS
@row:
    ldy CNT
    dey
@byte:
    lda (SRC),y
    beq @skip
    tax
    lda masktab,x
    beq @opaque
    and (TMP),y
    sta T1
    txa
    ora T1
    sta (TMP),y
    dey
    bpl @byte
    bra @row_end
@opaque:
    txa
    sta (TMP),y
@skip:
    dey
    bpl @byte
@row_end:
    clc
    lda SRC
    adc EW
    sta SRC
    bcc :+
    inc SRC+1
:   clc
    lda TMP
    adc RW
    sta TMP
    bcc :+
    inc TMP+1
:   dec ROWS
    bne @row
    plx
    rts

; ---- copy the arena to SHR memory -------------------------------------------
; RAMWRT sends writes to auxiliary memory; reads stay in main memory.
copy_pass:
    ldx rect_first
    cpx rect_done
    bcc :+
    rts
:   sta RAMWRT_ON
@rect:
    lda rect_pl,x
    sta SRC
    lda rect_ph,x
    sta SRC+1
    lda rect_h,x
    sta ROWS
    lda rect_w,x
    sta CNT
    sec
    lda rect_y,x
    sbc #ROW_BIAS
    sta T2
    sec
    lda rect_x,x
    sbc #PF_X0
    sta T1
@row:
    ldy T2
    clc
    lda rowaddr_lo,y
    adc T1
    sta DST
    lda rowaddr_hi,y
    adc #0
    sta DST+1
    ldy CNT
    dey
@byte:
    lda (SRC),y
    sta (DST),y
    dey
    bpl @byte
    clc
    lda SRC
    adc CNT
    sta SRC
    bcc :+
    inc SRC+1
:   inc T2
    dec ROWS
    bne @row
    inx
    cpx rect_done
    bcc @rect
    sta RAMWRT_OFF
    rts

; ---- panel: radar blips and scores, once per tick ---------------------------
; RAMWRT is on only around the pixel writes: while it is on, every write to
; $0200-$BFFF goes to auxiliary memory, engine variables included.
panel_update:
    ldx oblip_n
    beq @draw
    dex
@erase:
    lda oblip_x,x
    sta T1
    ldy oblip_y,x
    lda #$00
    jsr blip
    dex
    bpl @erase
@draw:
    ldx blip_n
    stx oblip_n
    beq @scores
    dex
@plot:
    lda blip_x,x
    sta oblip_x,x
    sta T1
    lda blip_y,x
    sta oblip_y,x
    tay
    lda blip_c,x
    jsr blip
    dex
    bpl @plot
@scores:
    lda SC1H
    cmp score_old
    bne @s1
    lda SC1L
    cmp score_old+1
    beq @s2_test
@s1:
    lda SC1H
    sta score_old
    lda SC1L
    sta score_old+1
    ldx #0                      ; byte x
    jsr score
@s2_test:
    lda SC2H
    cmp score_old+2
    bne @s2
    lda SC2L
    cmp score_old+3
    beq @done
@s2:
    lda SC2H
    sta score_old+2
    lda SC2L
    sta score_old+3
    ldx #112
    ldy #2
    jsr score_at
@done:
    rts

; A = colour byte, T1 = byte x, Y = screen row: 4 x 3 pixels.
blip:
    pha
    lda #3
    sta ROWS
@row:
    clc
    lda rowaddr_lo,y
    adc T1
    sta DST
    lda rowaddr_hi,y
    adc #0
    sta DST+1
    pla
    pha
    phy
    ldy #1
    sta RAMWRT_ON
    sta (DST),y
    dey
    sta (DST),y
    sta RAMWRT_OFF
    ply
    iny
    cpy #200
    bcs :+
    dec ROWS
    bne @row
:   pla
    rts

; Four BCD digits and a fixed zero in the status rows. X = byte x.
score:
    ldy #0
score_at:                       ; Y = index into score_old (0 or 2)
    stx T1
    lda score_old+1,y
    sta T2                      ; low BCD byte
    lda score_old,y
    pha
    lsr
    lsr
    lsr
    lsr
    jsr digit
    pla
    and #$0F
    jsr digit
    lda T2
    lsr
    lsr
    lsr
    lsr
    jsr digit
    lda T2
    and #$0F
    jsr digit
    lda #0
; A = digit, T1 = byte x (advances by 2).
digit:
    sta TMP
    asl
    asl
    adc TMP
    asl                         ; * 10
    tax
    ldy #1                      ; screen rows 1-5
@row:
    clc
    lda rowaddr_lo,y
    adc T1
    sta DST
    lda rowaddr_hi,y
    adc #0
    sta DST+1
    phy
    ldy #0
    sta RAMWRT_ON
    lda digits,x
    sta (DST),y
    iny
    lda digits+1,x
    sta (DST),y
    sta RAMWRT_OFF
    ply
    inx
    inx
    iny
    cpy #6
    bne @row
    inc T1
    inc T1
    rts
