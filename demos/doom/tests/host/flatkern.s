; Doom for the Appletini -- the kernel as the py65 harness gives it to the
; GAME code (tests/host/gamesim.py, flat.cfg).
;
; The same names as src/kernel (the jump table, its zero-page parameters,
; the input block, the counters); each entry jumps to a trap_* label that
; is a bare RTS: the harness stops the CPU there, does the work in Python
; (far memory is a Python array of banks) and lets the RTS return.
; game_call is the harness's entry: JSR (hcall) then BRK at host_stop.

.setcpu "65C02"

.segment "KZP": zeropage
far_src:    .res 3
far_dst:    .res 3
far_ptr:    .res 2
far_len:    .res 2
far_idx:    .res 2
ktmp:       .res 8
hcall:      .res 2
.exportzp far_src, far_dst, far_ptr, far_len, far_idx, ktmp, hcall

.segment "KBSS"
kin:        .res 8
ktics:      .res 2
kbanks:     .res 1
kcrash:     .res 1
.export kin, _kin := kin, ktics, _ktics := ktics, kbanks, _kbanks := kbanks, kcrash

.segment "KJT"
kjt_far_read:   jmp     trap_far_read
kjt_far_write:  jmp     trap_far_write
kjt_far_copy:   jmp     trap_far_copy
kjt_far_elem:   jmp     trap_far_elem
kjt_set_palette: jmp    trap_rts
kjt_reboot:     jmp     trap_crash
kjt_crash:      jmp     trap_crash
.export kjt_far_read, kjt_far_write, kjt_far_copy, kjt_far_elem
.export kjt_set_palette, kjt_reboot, kjt_crash

.segment "KCODE"
trap_far_read:  rts
trap_far_write: rts
trap_far_copy:  rts
trap_far_elem:  rts
trap_rts:       rts
trap_crash:     sta     kcrash
host_stop:      brk
                brk
host_call:      jsr     @go
                bra     host_stop
@go:            jmp     (hcall)
.export trap_far_read, trap_far_write, trap_far_copy, trap_far_elem, trap_crash
.export host_stop, host_call
