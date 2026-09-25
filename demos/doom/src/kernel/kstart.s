; Doom for the Appletini -- kernel start, interrupts, crash and reboot, the
; jump table (docs/DESIGN.md section 8).
;
; The loader's installer jumps to kernel_start with A = the number of
; RamWorks banks, the language card read/write on bank 2, interrupts off
; and ProDOS gone. From here the machine is the kernel's:
;
;   1. the stack, the zero page ($02-$FF), the kernel's BSS (language
;      card), the renderer's BSS and the view buffer (main) are cleared;
;   2. video_init: SHR4 PAL256 with PLAYPAL 0 (video.s);
;   3. input_init: the mouse card, with its VBL interrupt (input.s);
;   4. the GAME space's C start-up (game_boot, src/game/crt0.s) runs
;      through call_game: C stack, BSS, game_init();
;   5. interrupts on, and the frame loop (frame.s) for good.
;
; The interrupt handler counts VBLs: the mouse card raises an IRQ at the
; start of vertical blanking (mode bit 3, mouse_card.sv); the handler
; checks the VBL cause bit, increments vbl_count only for that cause, and
; acknowledges the card (ACK bits 0 and 1). A stale physical IRQ level or
; an interrupt from another card must not advance the clock. The handler
; touches only the zero page, the stack and the card, so it runs in either
; space, whatever RAMRD, RAMWRT and $C073 say. BANKED_GAME supplies each
; auxiliary code bank with an IRQ bridge to the main kernel and stack;
; bank transitions themselves mask interrupts. A BRK lands in kernel_crash
; with code CRASH_BRK.
;
; The jump table at $E000 is how GAME-space code (src/game/kglue.s) calls
; the kernel; entries are only ever appended. Parameters are in the
; kernel's zero page (kernel.inc) unless noted:
;
;   $E000 far_read      far_src -> far_ptr, far_len bytes
;   $E003 far_write     far_ptr -> far_dst, far_len bytes
;   $E006 far_copy      far_src -> far_dst, far_len bytes
;   $E009 far_elem      A/X = far array descriptor, far_idx -> far_src
;   $E00C set_palette   A = PLAYPAL number 0..13
;   $E00F kernel_reboot
;   $E012 kernel_crash  A = crash code

.include "kernel.inc"
.include "profile.inc"

.import video_init, game_boot
.import __KBSS_RUN__, __KBSS_SIZE__, __RBSS_RUN__, __RBSS_SIZE__
.ifdef BANKED_GAME
.include "gamebanks.inc"
.import game_phase_init, gb_irq_status
.import amem_init
.export kmemclr
.endif

POWERUP     = $03F4
TEXT_ROW0   = $0400

CRASH_BRK   = $01               ; a BRK instruction
CRASH_NOMOUSE = $02             ; no mouse card in slot 2: no VBL clock

; ---------------------------------------------------------------------------
.segment "KZP": zeropage
kspace:     .res 1
kcall:      .res 2
vbl_count:  .res 1
vbl_high:   .res 1              ; hardware-time readout: 16-bit VBL clock
.assert vbl_high = vbl_count+1, error, "VBL clock must be contiguous"
ktmp:       .res 8

; ---------------------------------------------------------------------------
.segment "KJT"
.ifdef BANKED_GAME
; Physical main-LC entries. The game-facing entries below switch back to
; main context before touching these addresses.
kjt_main_far_read:     jmp far_read
kjt_main_far_write:    jmp far_write
kjt_main_far_copy:     jmp far_copy
kjt_main_far_elem:     jmp far_elem
kjt_main_set_palette:  jmp set_palette
kjt_main_reboot:       jmp kernel_reboot
kjt_main_crash:        jmp kernel_crash
.segment "GBANKCODE"
kjt_far_read:     GB_GATE GB_MAIN_CONTEXT, kjt_main_far_read
kjt_far_write:    GB_GATE GB_MAIN_CONTEXT, kjt_main_far_write
kjt_far_copy:     GB_GATE GB_MAIN_CONTEXT, kjt_main_far_copy
kjt_far_elem:     GB_GATE GB_MAIN_CONTEXT, kjt_main_far_elem
kjt_set_palette:  GB_GATE GB_MAIN_CONTEXT, kjt_main_set_palette
kjt_reboot:       GB_GATE GB_MAIN_CONTEXT, kjt_main_reboot
kjt_crash:        GB_GATE GB_MAIN_CONTEXT, kjt_main_crash
.else
kjt_far_read:     jmp far_read
kjt_far_write:    jmp far_write
kjt_far_copy:     jmp far_copy
kjt_far_elem:     jmp far_elem
kjt_set_palette:  jmp set_palette
kjt_reboot:       jmp kernel_reboot
kjt_crash:        jmp kernel_crash
.endif
.export kjt_far_read, kjt_far_write, kjt_far_copy, kjt_far_elem
.export kjt_set_palette, kjt_reboot, kjt_crash

; ---------------------------------------------------------------------------
.segment "KBSS"
kbanks:     .res 1              ; RamWorks banks found by the loader
kcrash:     .res 1              ; the last crash code
.export kbanks, kcrash
.ifndef BANKED_GAME
.export _kbanks := kbanks
.endif

; ---------------------------------------------------------------------------
.segment "KCODE"

kernel_start:
        sei
        cld
        ldx     #$FF
        txs
        tay                             ; Y = the bank count, kept to the end
        bit     LCBANK2WR
        bit     LCBANK2WR
        sta     RAMRDOFF
        sta     RAMWRTOFF
        sta     ALTZPOFF
        sta     $C000                   ; 80STORE off
        stz     TWSPEED
        ; the zero page, $02-$FF
        lda     #0
        ldx     #2
:       sta     $00,x
        inx
        bne     :-
        ; BSS: the kernel's (language card), the renderer's and the view buffer
        lda     #<__KBSS_RUN__
        ldx     #>__KBSS_RUN__
        sta     ktmp
        stx     ktmp+1
        lda     #<__KBSS_SIZE__
        ldx     #>__KBSS_SIZE__
        jsr     kmemclr
        lda     #<__RBSS_RUN__
        ldx     #>__RBSS_RUN__
        sta     ktmp
        stx     ktmp+1
        lda     #<__RBSS_SIZE__
        ldx     #>__RBSS_SIZE__
        jsr     kmemclr
        lda     #<VIEWBUF
        ldx     #>VIEWBUF
        sta     ktmp
        stx     ktmp+1
        lda     #<VIEWBUF_SIZE
        ldx     #>VIEWBUF_SIZE
        jsr     kmemclr
        sty     kbanks
        stz     kspace
        jsr     video_init
        jsr     input_init
        bcc     :+
        lda     #CRASH_NOMOUSE
        jmp     kernel_crash
:
.ifdef BANKED_GAME
        jsr     amem_init
.endif
        lda     #<game_boot
        sta     kcall
        lda     #>game_boot
        sta     kcall+1
.ifdef BANKED_GAME
        jsr     game_phase_init
.else
        jsr     call_game
.endif
        cli
        jmp     frame_loop

; kmemclr: clear A/X (lo/hi) bytes from ktmp. Keeps Y.
kmemclr:
        phy
        sta     ktmp+2
        lda     #0
        ldy     #0
        cpx     #0
        beq     @rest
@page:  sta     (ktmp),y
        iny
        bne     @page
        inc     ktmp+1
        dex
        bne     @page
@rest:  ldx     ktmp+2
        beq     @done
@byte:  sta     (ktmp),y
        iny
        dex
        bne     @byte
@done:  ply
        rts

; ---------------------------------------------------------------------------
; the interrupt handler: the mouse card's VBL interrupt, or a BRK
; ---------------------------------------------------------------------------
irq_entry:
        pha
        phx
        tsx
        lda     $0103,x                 ; the pushed P
        and     #$10
        bne     @brk
        jsr     irq_mouse_service
        plx
        pla
        rti
@brk:   lda     #CRASH_BRK
        ; fall through

; ---------------------------------------------------------------------------
; kernel_crash: A = code. The text screen shows "DOOM CRASH $cc" and the
; machine stops here (kernel_crash_stop; tools/run_doom.py reports it).
; ---------------------------------------------------------------------------
kernel_crash:
        sei
        sta     kcrash
        sta     RAMRDOFF
        sta     RAMWRTOFF
        sta     ALTZPOFF
        lda     #$01
        sta     NEWVIDEO                ; SHR off
        sta     TEXTON
        sta     $C00C                   ; 40 columns
        ldx     #crash_msg_end-crash_msg-1
:       lda     crash_msg,x
        ora     #$80
        sta     TEXT_ROW0,x
        dex
        bpl     :-
        lda     kcrash
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     crash_hex
        sta     TEXT_ROW0+crash_msg_end-crash_msg
        lda     kcrash
        and     #$0F
        jsr     crash_hex
        sta     TEXT_ROW0+crash_msg_end-crash_msg+1
kernel_crash_stop:
        bra     kernel_crash_stop
crash_hex:
        cmp     #10
        bcc     :+
        adc     #6
:       adc     #'0'+$80
        rts
.export kernel_crash_stop

.ifdef BANKED_GAME
; Called with the main mapping and suspended main stack restored by gb_irq.
; Keep banking gateway scratch intact and leave all mapping switches alone.
gb_irq_service:
        lda     gb_irq_status
        and     #$10
        beq     irq_mouse_service
        lda     #CRASH_BRK
        jmp     kernel_crash
.export gb_irq_service
.endif

; Shared by both IRQ routes. Read the cause before consuming it. In TURBO,
; the virtual card can release IRQ before the sampled physical IRQ pin has
; caught up, so a second entry can legitimately have no VBL pending.
; A/X are saved by each caller; Y and all mapping switches stay untouched.
irq_mouse_service:
        ldx     MOUSE_STATUS
        lda     #3
        sta     MOUSE_ACK
        txa
        and     #$08                    ; only the mouse VBL cause is a tick
        beq     @done
        inc     vbl_count
        bne     :+
        inc     vbl_count+1
:
.ifdef PROFILE
        jmp     profile_tick
.endif
@done:  rts

crash_msg:
        .byte   "DOOM CRASH $"
crash_msg_end:

; ---------------------------------------------------------------------------
; kernel_reboot: back to the ROM's cold start (Quit restarts the machine).
; ---------------------------------------------------------------------------
kernel_reboot:
        sei
        lda     #0
        sta     MOUSE_MODE              ; no more interrupts
        sta     RAMWORKS
        sta     RAMRDOFF
        sta     RAMWRTOFF
        sta     ALTZPOFF
        lda     #$01
        sta     NEWVIDEO
        sta     TEXTON
        stz     POWERUP                 ; not a warm start
        bit     LCROM                   ; the ROM's vectors
        jmp     ($FFFC)

nmi_entry:
        rti

; ---------------------------------------------------------------------------
.segment "KVECTORS"
        .word   nmi_entry
        .word   kernel_reboot
        .word   irq_entry
