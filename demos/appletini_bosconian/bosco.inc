; Appletini Bosconian -- asm mirror of bosco.h (keep in sync by hand).
KBD        = $C000
STORE80OFF = $C000
RAMRDOFF   = $C002
RAMRDON    = $C003
RAMWRTOFF  = $C004
RAMWRTON   = $C005
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

VIA_A_ORB  = $C400
VIA_A_ORA  = $C401
VIA_A_ORA_NH = $C40F     ; no-handshake ORA: keeps the CA1 speech flag
VIA_A_DDRB = $C402
VIA_A_DDRA = $C403
VIA_A_PCR  = $C40C
VIA_A_IFR  = $C40D
VIA_A_IER  = $C40E
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

; zero page: video $20-$4F, sound $50-$5F, input $60-$6F, spare $70-$7F
ZP_VIDEO   = $20
ZP_SOUND   = $50
ZP_INPUT   = $60
