; math.inc: the native math's zero page, tables and soft switches
; (src/native/MATH.md). Included by math.s and the renderer's sources.

; ---------------------------------------------------------------------------
; Zero page: the math block, main $B0-$D7 (40 bytes of overlay 2 of
; docs/MEMORY_MAP.md). Every phase that calls the math keeps it
; for the math; the replay ($48-$6F) and the IRQ ($D8-$FF) never touch it.
; mt_init sets the table pointers' high bytes once; nothing else writes
; them.
; ---------------------------------------------------------------------------
MZ      = $B0

; the quarter-square pointers of a multiplier word: slot 0 its low byte,
; slot 1 its high byte (setw); (Pxx),y reads f(m + y) and f(y - m)
PSL0    = MZ + $00          ; SQL + m0
PSH0    = MZ + $02          ; SQH + m0
PNL0    = MZ + $04          ; NSL + (m0 ^ $FF)
PNH0    = MZ + $06          ; NSH + (m0 ^ $FF)
PSL1    = MZ + $08
PSH1    = MZ + $0A
PNL1    = MZ + $0C
PNH1    = MZ + $0E

M_A     = MZ + $10          ; first operand, 4 bytes, little-endian
M_B     = MZ + $14          ; second operand
M_R     = MZ + $18          ; result
MT      = MZ + $1C          ; 12 temporaries, MT+0 - MT+11
M_T     = MT                ; the remainder of the divides (4 bytes)
MT_E    = MT + 6            ; a table entry read by mt_far (4 bytes)
MT_P    = MT + 10           ; the address mt_far reads (2 bytes)

; ---------------------------------------------------------------------------
; Tables in fast memory: the quarter squares, main card bank 1 (selected
; in every phase but the replay: MEMORY_MAP rule 1), 512 bytes each,
; page aligned. f(n) = floor(n * n / 4).
; ---------------------------------------------------------------------------
SQL     = $D000             ; f(n) low bytes, n = 0-511
SQH     = $D200             ; f(n) high bytes
NSL     = $D400             ; f(n - 255) low bytes
NSH     = $D600             ; f(n - 255) high bytes

; ---------------------------------------------------------------------------
; Tables in RamWorks (the tables banks of MEMORY_MAP.md), read by
; mt_far through RAMRD windows. Every plane is a byte plane.
; ---------------------------------------------------------------------------
MT_TBANK = 120              ; sine, tangent to angle, quarter sine
MT_RLO   = 121              ; RECIP_TABLE low bytes
MT_RHI   = 122              ; RECIP_TABLE high bytes

SINELO  = $2000             ; |finesine[x]|, x = 0-8191, low bytes
SINEHI  = $4000             ;   high bytes (the sign is bit 12 of x)
TANTO0  = $6000             ; tantoangleTable, 2,049 entries, byte 0
TANTO_STRIDE = 9            ;   bytes 1-3 each 9 pages later
QUARTLO = $8400             ; finesineTable_part_1, 2,048 words, low
QUARTHI = $8C00             ;   high bytes
RECIPT  = $2000             ; RECIP_TABLE entry i at RECIPT + i, i < 32768

; ---------------------------------------------------------------------------
; Persistent state (main $0300-$03EF, MEMORY_MAP.md)
; ---------------------------------------------------------------------------
MT_PRND = $03EE             ; P_Random's index
MT_MRND = $03EF             ; M_Random's index

; ---------------------------------------------------------------------------
; Soft switches
; ---------------------------------------------------------------------------
RAMRDOFF = $C002
RAMRDON  = $C003
RAMWRTOFF = $C004
RAMWRTON = $C005
RWBANK   = $C073
