; Optional hardware VBL sampling. Markers clobber A/P, only in main context.
.ifndef DOOM_PROFILE_INC
DOOM_PROFILE_INC = 1
PROF_IDLE = 0
PROF_GAME_COPY = 2
PROF_GAME = 4
PROF_PACKET = 6
PROF_DEBUG = 8
PROF_RENDER_COPY = 10
PROF_SETUP = 12
PROF_WALLS = 14
PROF_PLANES = 16
PROF_THINGS = 18
PROF_MASKED = 20
PROF_PRESENT = 22
PROF_BLIT = 24
PROF_COUNT = 13
.ifdef PROFILE
.globalzp profile_stage
.global profile_tick, profile_publish
.endif
.macro PROFILE_STAGE stage
.ifdef PROFILE
        lda #stage
        sta profile_stage
.endif
.endmacro
.endif
