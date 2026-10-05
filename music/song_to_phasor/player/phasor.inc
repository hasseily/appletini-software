; Public constants for the PHS1 player; ca65, 65C02, Phasor in slot 4.
PHS_OK              = 0
PHS_ERR_HEADER      = 1
PHS_ERR_READ        = 2
PHS_ERR_COMMAND     = 3
PHS_ERR_TIME        = 4
PHS_ERR_BUDGET      = 5
PHS_ERR_READER      = 6

; Fail closed when a corrupt stream would monopolize an interrupt.
; These are limits, not a guarantee that this workload fits one timer period.
PHS_MAX_RECORDS     = 64
PHS_MAX_WRITES      = 255

PHS_VIA0_ORB        = $C410
PHS_VIA0_DDRB       = $C412
PHS_VIA0_DDRA       = $C413
PHS_VIA0_IER        = $C41E
PHS_VIA0_ORA_NH     = $C41F
PHS_VIA1_ORB        = $C480
PHS_VIA1_DDRB       = $C482
PHS_VIA1_DDRA       = $C483
PHS_VIA1_IER        = $C48E
PHS_VIA1_ORA_NH     = $C48F
PHS_SSI0           = $C420
PHS_SSI1           = $C440
