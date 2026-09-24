; The render packet (src/game/rview.h is the definition; keep both equal).
; The game builds it in the GAME space at _rview; render_frame copies
; RV_HEADER + nthings * RT_SIZE bytes of it into main memory first.

RV_MAXTHINGS  = 128

RV_X          = 0               ; int32 sub-units (1/16 map unit)
RV_Y          = 4
RV_Z          = 8
RV_ANGLE      = 12              ; BAM16
RV_EXTRALIGHT = 14
RV_FIXEDCMAP  = 15              ; stored colormap 0..15, $FF none
RV_TIC        = 16              ; u16
RV_NTHINGS    = 18
RV_NPSPRITES  = 19
RV_PSPRITES   = 20              ; 2 x RP_SIZE
RV_THINGS     = 40              ; RV_MAXTHINGS x RT_SIZE
RV_HEADER     = RV_THINGS

RP_SPRITE     = 0               ; $FF = layer off
RP_FRAME      = 1               ; bit 7 full bright
RP_SX         = 2               ; int32 16.16, Doom's 320x200 screen
RP_SY         = 6
RP_SIZE       = 10

RT_X          = 0               ; int32 sub-units
RT_Y          = 4
RT_Z          = 8               ; feet
RT_ANGLE      = 12              ; BAM16
RT_SPRITE     = 14
RT_FRAME      = 15              ; bit 7 full bright
RT_FLAGS      = 16              ; bit 0 shadow (fuzz)
RT_SECTOR     = 18              ; u16
RT_SIZE       = 20

RT_SHADOW     = $01
RT_FULLBRIGHT = $80
