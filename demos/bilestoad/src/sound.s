; The Bilestoad SHR port: Phasor sound driver (slot 4).
;
; Phasor native mode gives four AY chips = twelve voices. The rules follow
; appletini-one/hdl/apple/mockingboard.sv:
;   * an access to $C0C8 selects Mockingboard mode, then $C0C5 adds native
;   * VIA-A answers at $C41x and VIA-B at $C48x (true in both modes)
;   * ORB bit 4 selects the first AY of a VIA, bit 3 the second, active low
;   * the PSG clock is doubled in native mode (the music table allows for it)
; Voice = chip * 3 + channel. Chips 0 and 1 hang on VIA-A, 2 and 3 on VIA-B.
; On a plain Mockingboard only chips 0 and 2 exist; the driver finds this
; with an AY register read-back and then skips chips 1 and 3.
;
; Time base: VIA-A timer 1 free-runs on the 1 MHz bus clock. snd_frame reads
; it once per video frame and runs one sound tick for each 1/60 s that has
; passed, so the tempo does not depend on the frame rate or on the CPU speed.
; No interrupt is used.

PH_MB       = $C0C8
PH_NATIVE   = $C0C5
VIA_A       = $C410
VIA_B       = $C480
V_ORB       = 0
V_ORA       = 1
V_DDRB      = 2
V_DDRA      = 3
V_T1CL      = 4
V_T1CH      = 5
V_ACR       = 11
V_IER       = 14
TICK_CYCLES = 17030             ; 1/60 s on the 1.0205 MHz bus clock
MAX_CATCHUP = 4
NVOICES     = 12
SFX_VOICE   = 8                 ; chip 2, channel C
MUSIC_VOLUME = 11
DECAY_TICKS = 5

.segment "BSS"
mb_only:    .res 1              ; 1 = no second AY behind each VIA
t1_last:    .res 2
t1_acc:     .res 2
m_ptr:      .res 2
m_wait:     .res 1
m_on:       .res 1
v_vol:      .res NVOICES
v_decay:    .res NVOICES
sfx_clang:  .res 1
sfx_noise:  .res 1
sfx_vol:    .res 1
ay_chip:    .res 1
ay_reg:     .res 1
ay_val:     .res 1

.segment "RODATA"
sel_latch:  .byte $0F, $17      ; first / second AY of a VIA
sel_write:  .byte $0E, $16
sel_read:   .byte $0D, $15
sel_idle:   .byte $0C, $14
voice_chip: .byte 0,0,0, 1,1,1, 2,2,2, 3,3,3
voice_chan: .byte 0,1,2, 0,1,2, 0,1,2, 0,1,2
.include "music.inc"

.segment "CODE"

snd_init:
    bit PH_MB
    bit PH_NATIVE
    lda #$1F
    sta VIA_A + V_DDRB
    sta VIA_B + V_DDRB
    lda #$FF
    sta VIA_A + V_DDRA
    sta VIA_B + V_DDRA
    stz VIA_A + V_ORB           ; reset the PSGs
    stz VIA_B + V_ORB
    lda #$0C
    sta VIA_A + V_ORB
    sta VIA_B + V_ORB
    lda #$7F
    sta VIA_A + V_IER           ; no interrupt source
    sta VIA_B + V_IER
    lda #$40
    sta VIA_A + V_ACR           ; timer 1 free-running
    lda #$FF
    sta VIA_A + V_T1CL
    sta VIA_A + V_T1CH          ; start
    stz mb_only
    ; Probe: register 0 of chip 0 and chip 1 hold different values only
    ; when two chips exist.
    ldx #0
    ldy #0
    lda #$55
    jsr ay_write
    ldx #1
    ldy #0
    lda #$AA
    jsr ay_write
    ldy #0
    sty VIA_A + V_ORA
    lda #$0F
    sta VIA_A + V_ORB           ; latch register 0 on chip 0
    lda #$0C
    sta VIA_A + V_ORB
    stz VIA_A + V_DDRA
    lda #$0D
    sta VIA_A + V_ORB           ; read
    lda VIA_A + V_ORA
    pha
    lda #$0C
    sta VIA_A + V_ORB
    lda #$FF
    sta VIA_A + V_DDRA
    pla
    cmp #$AA
    bne :+
    inc mb_only
:   jsr snd_quiet
    lda VIA_A + V_T1CL
    sta t1_last
    lda VIA_A + V_T1CH
    sta t1_last+1
    stz t1_acc
    stz t1_acc+1
    stz sfx_clang
    stz sfx_noise
    stz sfx_vol
    stz m_on
; fall through
; The table is: wait, event group, wait, event group ... so the first byte
; is a wait and the parser pointer starts at the first group.
music_restart:
    lda music_data
    sta m_wait
    lda #<(music_data + 1)
    sta m_ptr
    lda #>(music_data + 1)
    sta m_ptr+1
    rts

; Mixer: tones on, noise only on the effect channel; volumes zero.
snd_quiet:
    ldx #3
@chip:
    ldy #7
    lda #$38
    cpx #2
    bne :+
    lda #$18                    ; chip 2: noise on channel C
:   jsr ay_write
    ldy #8
@vol:
    lda #0
    jsr ay_write
    iny
    cpy #11
    bne @vol
    dex
    bpl @chip
    ldx #NVOICES - 1
@clear:
    stz v_vol,x
    dex
    bpl @clear
    rts

; X = chip 0-3, Y = register, A = value. Keeps X and Y.
ay_write:
    sta ay_val
    stx ay_chip
    sty ay_reg
    txa
    and #1
    beq :+
    lda mb_only
    bne @done                   ; that chip does not exist
    lda #1
:   tay                         ; Y = 0 first AY, 1 second AY
    cpx #2
    bcs @via_b
    lda ay_reg
    sta VIA_A + V_ORA
    lda sel_latch,y
    sta VIA_A + V_ORB
    lda sel_idle,y
    sta VIA_A + V_ORB
    lda ay_val
    sta VIA_A + V_ORA
    lda sel_write,y
    sta VIA_A + V_ORB
    lda sel_idle,y
    sta VIA_A + V_ORB
    bra @done
@via_b:
    lda ay_reg
    sta VIA_B + V_ORA
    lda sel_latch,y
    sta VIA_B + V_ORB
    lda sel_idle,y
    sta VIA_B + V_ORB
    lda ay_val
    sta VIA_B + V_ORA
    lda sel_write,y
    sta VIA_B + V_ORB
    lda sel_idle,y
    sta VIA_B + V_ORB
@done:
    ldx ay_chip
    ldy ay_reg
    lda ay_val
    rts

; Called at the start of the background draw, before the game clears its
; requests: N2 = contact (clang), N5 = wound (noise).
snd_sample:
    lda N2
    beq :+
    sta sfx_clang
:   lda N5
    beq :+
    sta sfx_noise
:   ; music plays while the fighters cannot see each other, as upstream
    stz m_on
    lda SND
    bne :+
    lda INVIEW
    beq :+
    inc m_on
:   rts

; Once per video frame.
snd_frame:
    sec
    lda t1_last
    sbc VIA_A + V_T1CL
    sta T1
    lda t1_last+1
    sbc VIA_A + V_T1CH
    sta T2
    sec                         ; last -= elapsed
    lda t1_last
    sbc T1
    sta t1_last
    lda t1_last+1
    sbc T2
    sta t1_last+1
    clc
    lda t1_acc
    adc T1
    sta t1_acc
    lda t1_acc+1
    adc T2
    sta t1_acc+1
    lda #MAX_CATCHUP
    sta CNT
@more:
    lda t1_acc
    cmp #<TICK_CYCLES
    lda t1_acc+1
    sbc #>TICK_CYCLES
    bcc @done
    sec
    lda t1_acc
    sbc #<TICK_CYCLES
    sta t1_acc
    lda t1_acc+1
    sbc #>TICK_CYCLES
    sta t1_acc+1
    jsr snd_tick
    dec CNT
    bne @more
    stz t1_acc                  ; too far behind: drop the rest
    stz t1_acc+1
@done:
    rts

snd_tick:
    lda SND
    beq :+
    jmp snd_quiet
:   jsr sfx_tick
    lda m_on
    beq @decay
    dec m_wait
    bne @decay
    lda m_ptr                   ; the table pointer must be in zero page
    sta REC
    lda m_ptr+1
    sta REC+1
@group:
    ldy #0
    lda (REC),y
    cmp #$FE
    bne :+
    lda #<music_data            ; end of tune: loop
    sta REC
    lda #>music_data
    sta REC+1
    bra @wait
:   cmp #$FF
    beq @empty
    pha
    and #$0F
    tax                         ; voice
    iny
    lda (REC),y
    sta T1
    iny
    lda (REC),y
    sta T2
    jsr note_on
    clc
    lda REC
    adc #3
    sta REC
    bcc :+
    inc REC+1
:   pla
    bpl @group                  ; bit 7 marks the last event of the group
    bra @wait
@empty:
    inc REC
    bne @wait
    inc REC+1
@wait:
    ldy #0
    lda (REC),y
    sta m_wait
    inc REC
    bne :+
    inc REC+1
:   lda REC
    sta m_ptr
    lda REC+1
    sta m_ptr+1
@decay:
    ldx #NVOICES - 1
@voice:
    cpx #SFX_VOICE
    beq @next
    lda v_vol,x
    beq @next
    dec v_decay,x
    bne @next
    lda #DECAY_TICKS
    sta v_decay,x
    dec v_vol,x
    jsr voice_volume
@next:
    dex
    bpl @voice
    rts

; X = voice, T1/T2 = tone period.
note_on:
    cpx #SFX_VOICE
    beq @done
    stx TMP
    lda voice_chan,x
    asl
    tay                         ; register 0, 2 or 4
    lda voice_chip,x
    tax
    lda T1
    jsr ay_write
    iny
    lda T2
    jsr ay_write
    ldx TMP
    lda #MUSIC_VOLUME
    sta v_vol,x
    lda #DECAY_TICKS
    sta v_decay,x
    jsr voice_volume
@done:
    rts

; X = voice: write v_vol to the chip. Keeps X.
voice_volume:
    stx TMP
    lda voice_chan,x
    clc
    adc #8
    tay
    lda v_vol,x
    pha
    lda voice_chip,x
    tax
    pla
    jsr ay_write
    ldx TMP
    rts

; Effects use chip 2 channel C: tone + noise, fast decay.
sfx_tick:
    lda sfx_clang
    beq @noise
    stz sfx_clang
    ldx #2
    ldy #4                      ; tone C: a high, slightly rough pitch
    lda #$5C
    jsr ay_write
    iny
    lda #$00
    jsr ay_write
    ldy #6
    lda #$02                    ; noise period
    jsr ay_write
    lda #15
    sta sfx_vol
@noise:
    lda sfx_noise
    beq @run
    stz sfx_noise
    ldx #2
    ldy #4
    lda #$FF                    ; low rumble under the noise
    jsr ay_write
    iny
    lda #$07
    jsr ay_write
    ldy #6
    lda #$14
    jsr ay_write
    lda #15
    sta sfx_vol
@run:
    lda sfx_vol
    beq @done
    dec sfx_vol
    ldx #2
    ldy #10
    lda sfx_vol
    jsr ay_write
@done:
    rts
