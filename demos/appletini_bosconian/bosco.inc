; Appletini Bosconian -- asm mirror of bosco.h (keep in sync by hand).
KBD        = $C000
STORE80OFF = $C000
RAMRDOFF   = $C002
RAMRDON    = $C003
RAMWRTOFF  = $C004
RAMWRTON   = $C005
ALTZPOFF   = $C008       ; main zero page, stack and language card
ALTZPON    = $C009       ; auxiliary ones
KBDSTRB    = $C010
RDVBLBAR   = $C019
NEWVIDEO   = $C029
TEXTON     = $C051
BUTTON0    = $C061
BUTTON1    = $C062
PADDLE0    = $C064
PADDLE1    = $C065
PTRIG      = $C070
RAMWORKS   = $C073
TWSPEED    = $C074
LCBANK2RD  = $C080       ; read: language card bank 2 RAM readable, write protected
LCBANK2WR  = $C083       ; read twice: bank 2 RAM readable and writable
LCBANK1RD  = $C088       ; read: bank 1 RAM readable, write protected
LCBANK1WR  = $C08B       ; read twice: bank 1 RAM readable and writable

PHASOR_MB  = $C0C8       ; read: Mockingboard mode
PHASOR_NATIVE = $C0C5    ; read after PHASOR_MB: Phasor native mode
VIA_A_ORB  = $C410       ; VIA-A answers at $C41x in both Phasor modes
VIA_A_ORA  = $C411
VIA_A_ORA_NH = $C41F     ; no-handshake ORA: keeps the CA1 speech flag
VIA_A_DDRB = $C412
VIA_A_DDRA = $C413
VIA_A_PCR  = $C41C
VIA_A_IFR  = $C41D
VIA_A_IER  = $C41E
VIA_B_ORB  = $C480
VIA_B_ORA  = $C481
VIA_B_ORA_NH = $C48F
VIA_B_DDRB = $C482
VIA_B_DDRA = $C483
VIA_B_PCR  = $C48C
VIA_B_IFR  = $C48D
VIA_B_IER  = $C48E
SSI_DUR    = $C440
SSI_INF    = $C441
SSI_RATE   = $C442
SSI_CTL    = $C443
SSI_FILT   = $C444

SHR_BASE   = $2000      ; AUX
SHR_ROW    = 160
SHR_SCB    = $9D00
SHR_PAL    = $9E00
FIELD_BYTES = 128       ; playfield bytes per row (x 0..255)
PANEL_BYTE0 = 128       ; first panel byte column

DL_MAX     = 96
STAR_MAX   = 48

; _spr_bank codes (tools/gen_assets.py): 0 = main memory, else the
; auxiliary language card (SPR_BANK_AUX), bank 1 if SPR_BANK_1 is set
SPR_BANK_1   = $02
SPR_BANK_AUX = $04

; zero page: video $20-$4F, sound $50-$5F, input $60-$6F, spare $70-$7F
ZP_VIDEO   = $20
ZP_SOUND   = $50
ZP_INPUT   = $60
ZP_SPARE   = $70
