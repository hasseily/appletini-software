; Existing //e/Appletini I/O only. No private SmartPort transport.
.setcpu "65C02"
.export _ti_display_level, _ti_key_pending, _ti_key_clear
.export _ti_video_on, _ti_video_off

.segment "CODE"
; Boolean: 1=active scanner display, 0=vertical blank. This is a sampled
; level, neither a wall clock nor proof the HDMI renderer presented a frame.
_ti_display_level:
        lda $C019
        and #$80
        beq done
        lda #1
done:   ldx #0
        rts

_ti_key_pending:
        lda $C000
        and #$80
        beq key_done
        lda #1
key_done:
        ldx #0
        rts

_ti_key_clear:
        bit $C010
        rts

; Fake SHR on the supported Appletini //e baseline. Normal CPU writes to
; AUX bank0 $2000-$9FFF publish the screen; banked working resources do not.
_ti_video_on:
        lda #$C1
        sta $C029
        rts

_ti_video_off:
        lda #$01
        sta $C029
        rts
