; The music player for the Phasor: shared definitions.
;
; Everything the interrupt reads or writes is in the language card or the
; zero page.

; ---- the Phasor in slot 4 ------------------------------------------------
; VIA-A answers at $C41x and VIA-B at $C48x in both card modes.
VIA_A_ORB       = $C410
VIA_A_ORA       = $C411         ; ORA with handshake: the probe's one read
VIA_A_DDRB      = $C412
VIA_A_DDRA      = $C413
VIA_A_IER       = $C41E
VIA_A_ORA_NH    = $C41F         ; ORA without handshake (keeps CA1 for the SSI)
VIA_B_ORB       = $C480
VIA_B_DDRB      = $C482
VIA_B_DDRA      = $C483
VIA_B_T1CL      = $C484         ; VIA-B's timer 1: the music's clock
VIA_B_T1CH      = $C485
VIA_B_T1LL      = $C486
VIA_B_T1LH      = $C487
VIA_B_ACR       = $C48B
VIA_B_IFR       = $C48D
VIA_B_IER       = $C48E
VIA_B_ORA_NH    = $C48F
IFR_T1          = $40           ; IFR and IER bit 6: timer 1
PHASOR_MB       = $C0C8         ; Mockingboard mode
PHASOR_NATIVE   = $C0C5         ; then native mode: four AYs

; ORB values (bit 4 and bit 3: chip selects of the first and second AY of
; a VIA, active low; bit 2: reset, active low; bits 1-0: BDIR, BC1)
ORB_LATCH0      = $0F
ORB_WRITE0      = $0E
ORB_IDLE0       = $0C
ORB_LATCH1      = $17
ORB_WRITE1      = $16
ORB_IDLE1       = $14
ORB_READ0       = $0D           ; the probe's read of the first AY

; ---- the machine ----------------------------------------------------------
RAMRD_OFF       = $C002         ; reads of $0200-$BFFF from main memory
RAMRD_ON        = $C003         ;   or from the aux 64K

; ---- the player's state --------------------------------------------------
IDLE            = 0             ; phase[v]
ATTACK          = 1
DECAY           = 2
SUSTAIN         = 3
RELEASE         = 4
DRUM_HW         = 5
DRUM_SOFT       = 6

JUST_ON         = 1             ; flags[v]
OFF_PENDING     = 2

ENV_SUSTAINED   = 1             ; envelope flag

; ---- the song file -------------------------------------------------------
SONG_VERSION    = 1
ENV_SIZE        = 8             ; attack, decay, release (2 each), sustain, flags
DRUM_SIZE       = 6             ; tone, noise, envelope period (2), step (2)
MAX_ENVELOPES   = 20            ; the card's room for a song's tables:
MAX_DRUMS       = 23            ; 160 + 138 bytes (at most 300)

; ---- snd_probe's answer (probe.s): A, and carry set with no music ---------
SND_MUSIC       = 0             ; native mode, 4 chips: the music plays
SND_NO_MUSIC    = 1             ; the card cannot switch: no music

; ---- snd_start's arguments and results ------------------------------------
SONG_LOOP       = $01           ; snd_song_flags: loop at the end
SONG_NTSC       = $80           ; snd_song_flags: NTSC tables and tempo

ERR_VERSION     = 1             ; snd_error after a refused snd_start
ERR_LAYOUT      = 2
ERR_TABLES      = 3
ERR_LOOP        = 4
ERR_STREAM      = 5             ; the stream broke a rule while playing

RING_SIZE       = 1024          ; the song's ring buffer in the card
