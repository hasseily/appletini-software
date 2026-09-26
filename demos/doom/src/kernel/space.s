; Doom for the Appletini -- game/render address-space handoff.
; BANKED_GAME keeps near game pointers in main RAM and snapshots each phase
; into a backing bank. The legacy configuration below maps GAME through
; RAMRD/RAMWRT. Video writes are batched by target TURBO firmware; the
; simulator's fixed I/O surcharge is not a measurement of that batching.
;
; Legacy layout:
;   RENDER  $0200-$BFFF is main memory: RAMRD and RAMWRT off.
;   GAME    $0200-$BFFF is RamWorks bank 1: $C073 = 1, RAMRD and RAMWRT on.
;
; Both spaces share the main zero page, the stack (page 1) and the main
; language card, where all of this code runs: the language card does not
; move with RAMRD, so the switch can be made from here and the caller's
; next instruction comes from the other space. kspace says which space is
; current (SPACE_RENDER 0, SPACE_GAME 1): the far-access routines and
; set_palette read it to leave the machine as they found it.
;
; space_game and space_render keep A, X, Y and P. call_game (RENDER space
; only) runs the GAME routine at kcall with A, X, Y passed in and the
; callee's A, X, Y and P passed back, and returns in RENDER space. The
; switch is three soft-switch writes and one zero-page write.

.include "kernel.inc"

.ifdef BANKED_GAME
.import gb_init, gb_call
.import kbanks
.import _gamemap, render_map
.import _arena_ptr
.import __RZP_RUN__, __RZP_SIZE__
.import __DATA_RUN__, __RLOBSS_RUN__, __RLOBSS_SIZE__, __RBSS_RUN__, __RBSS_SIZE__
.import kmemclr
.import kbuf, amem_available
.export amem_load, amem_clear
.export call_game_active, game_phase_init
.export _kin, _kbanks

; Preserve the renderer's mutable regions, including self-modified code.
; Read-only regions are copied to its backing bank once at initialization.
; The first RZP_SIZE framebuffer bytes hold the saved renderer zero page.
; Game copies stop at the allocator's page-rounded high-water mark. Its
; unallocated tail and shared intercept/view scratch are dead at a handoff.
RENDER_END = >(VIEWBUF + __RZP_SIZE__ + $FF)
.export RENDER_END
.assert RENDER_END <= $B8, lderror, "renderer snapshot overlaps immutable AMEM overlays"
.assert __RLOBSS_RUN__ >= $0C00, lderror, "renderer low state moved below snapshot"
.assert __RLOBSS_RUN__ + __RLOBSS_SIZE__ <= $2000, lderror, "renderer low state exceeds snapshot"
.assert __RBSS_RUN__ >= $6000, lderror, "renderer high state moved below snapshot"
.assert __RBSS_RUN__ + __RBSS_SIZE__ <= VIEWBUF, lderror, "renderer state overlaps framebuffer"
.assert VIEWBUF = $8B80, lderror, "review renderer snapshot ranges after framebuffer move"

; The game-facing input and bank-count values must remain readable while
; auxiliary LC code is selected. Kernel originals live in main LC.
.segment "GINPUT"
_kin:       .res 8, 0
_kbanks:    .res 1, 0

.segment "KCODE"

; Renderer ZP is preserved in dead framebuffer bytes before the snapshot.
; Kernel ZP (clock, input and far API) stays live through both phases.
space_game:
        php
        pha
        phx
        phy
        ldx     #<__RZP_SIZE__-1
@zp:    lda     __RZP_RUN__,x
        sta     VIEWBUF,x
        dex
        cpx     #$FF
        bne     @zp
        bit     LCBANK1WR
        bit     LCBANK1WR
        lda     #$BB
        jsr     phase_batch
        bcc     @loaded
        lda     #RENDER_HOME_BANK
        ldx     #$02
        ldy     #$04
        jsr     phase_save
        lda     #RENDER_HOME_BANK
        ldx     #$0C
        ldy     #$20
        jsr     phase_save
        lda     #RENDER_HOME_BANK
        ldx     #$60
        ldy     #RENDER_END
        jsr     phase_save
        lda     #GAME_HOME_BANK
        ldx     #$02
        ldy     #$B8
        jsr     phase_load
@loaded:
        bit     LCBANK2WR
        bit     LCBANK2WR
        lda     #SPACE_GAME
        sta     kspace
        ply
        plx
        pla
        plp
        rts

space_render:
        php
        pha
        phx
        phy
        ; The original separated harness selected the renderer's map itself.
        ; Publish the actual game map before replacing its main-memory state.
        lda     _gamemap
        dec     a
        sta     render_map
        bit     LCBANK1WR
        bit     LCBANK1WR
        lda     #$BC
        jsr     phase_batch
        bcc     @loaded
        lda     #GAME_HOME_BANK
        ldx     #>__DATA_RUN__
        ldy     #$B8
        jsr     phase_save
        lda     #RENDER_HOME_BANK
        ldx     #$02
        ldy     #RENDER_END
        jsr     phase_load
@loaded:
        ldx     #<__RZP_SIZE__-1
@zp:    lda     VIEWBUF,x
        sta     __RZP_RUN__,x
        dex
        cpx     #$FF
        bne     @zp
        ; Every C call has returned before the handoff, so its software
        ; stack need not persist. The renderer starts with a clean view.
        lda     #<VIEWBUF
        sta     ktmp
        lda     #>VIEWBUF
        sta     ktmp+1
        lda     #<VIEWBUF_SIZE
        ldx     #>VIEWBUF_SIZE
        jsr     amem_clear
        bit     LCBANK2WR
        bit     LCBANK2WR
        stz     kspace
        ply
        plx
        pla
        plp
        rts

; A = backing bank, X = first page, Y = exclusive last page. Main LC bank 1
; must be selected. Both mappings are off on entry/return. The overlay loader
; and CPU fallback only change RAMRD/RAMWRT while executing resident LC.
.segment "KLC1TAIL"
; A = immutable batch overlay page. Carry clear means the handoff completed;
; carry set selects the original CPU path, without reloading a batch helper.
phase_batch:
        ldy     amem_available
        beq     @cpu
        jsr     amem_load
        jmp     kbuf
@cpu:   sec
        rts

phase_save:
        sta     far_dst+2
        cmp     #GAME_HOME_BANK
        bne     @copy
        ; Save the live extent in resident LC before replacing the game's
        ; BSS. Round upward without dropping an exact page boundary.
        ldy     _arena_ptr+1
        lda     _arena_ptr
        beq     @rounded
        iny
@rounded:
        sty     phase_game_end
@copy:
        clc
        bra     phase_transfer
phase_load:
        sta     far_dst+2
        cmp     #GAME_HOME_BANK
        bne     @copy
        ldy     phase_game_end
@copy:
        sec
phase_transfer:
        php
        phx
        phy
        lda     #$B8
        jsr     amem_load
        ply
        plx
        plp
        lda     far_dst+2
        jmp     kbuf

; Main LC bank 1 selected; read one immutable overlay page into LC kbuf.
; This direct BANKED_GAME far_read does not itself use the bounce buffer.
amem_load:
        sta     far_src+1
        stz     far_src
        lda     #RENDER_HOME_BANK
        sta     far_src+2
        lda     #<kbuf
        sta     far_ptr
        lda     #>kbuf
        sta     far_ptr+1
        stz     far_len
        lda     #1
        sta     far_len+1
        jmp     far_read

; RZP has already been restored from the first VIEWBUF bytes.
amem_clear:
        ldy     amem_available
        bne     @api
        jmp     kmemclr
@api:  lda     #$BA
        jsr     amem_load
        jmp     kbuf

; The first game load precedes allocator initialization and needs the whole
; initial image. Every later load uses the extent saved at the last handoff.
phase_game_end: .byte $B8
.export phase_game_end

.segment "KCODE"
game_phase_init:
        ; Keep the renderer's immutable tables/code in its backing image.
        bit     LCBANK1WR
        bit     LCBANK1WR
        lda     #RENDER_HOME_BANK
        ldx     #$02
        ldy     #RENDER_END
        jsr     phase_save
        bit     LCBANK2WR
        bit     LCBANK2WR
        jsr     space_game
        jsr     gb_init
        jsr     call_game_active
        jmp     space_render

; Several tics and packet construction share one game phase per frame.
call_game:
        jsr     space_game
        jsr     call_game_active
        jmp     space_render
call_game_active:
        lda     kbanks
        sta     _kbanks
        ldx     #7
@input: lda     kin,x
        sta     _kin,x
        dex
        bpl     @input
        jmp     (kcall)
.else
.segment "KCODE"

space_game:
        php
        pha
        lda     #GAME_BANK
        sta     RAMWORKS
        sta     RAMRDON
        sta     RAMWRTON
        sta     kspace                  ; SPACE_GAME = GAME_BANK = 1
        pla
        plp
        rts

space_render:
        php
        pha
        sta     RAMRDOFF
        sta     RAMWRTOFF
        lda     #SPACE_RENDER
        sta     kspace
        pla
        plp
        rts

call_game:
        jsr     space_game
        jsr     @go
        jmp     space_render
@go:    jmp     (kcall)
.endif
