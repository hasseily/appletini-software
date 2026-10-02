# src/native/m11/s2draw.mk: part s2draw's builds (docs/SCREENS.md 7.3,
# docs/m11-parts/s2draw.md), read by src/native/m11.mk:
#
#   build/native/m11/s2draw/s2dt.*   the test image s2dt in P2DW's room:
#                                    s2_draw.s and s2_pub.s (the shared
#                                    objects), s2_beginstub.s (s2_begin's
#                                    test double), s2_drawt.s (the cases),
#                                    the far layer, MATHW and the test
#                                    driver s2_drv.s
#   build/native/m11/s2draw/s2pt.*   s2_pub.s alone in AMAPW's room, as
#                                    AMAPW links it (its 200 B budget)

S2DRAW_DIR := $(M11)/s2draw
$(eval $(call M11_COMMON,$(S2DRAW_DIR)))
S2DRAW_COMMON := $(S2DRAW_DIR)/s2_drv.o $(M11_COMMON_OBJS:%=$(S2DRAW_DIR)/%)
S2DRAW_OBJS := $(S2DRAW_DIR)/s2_drawt.o $(S2DRAW_DIR)/s2_draw.o \
               $(S2DRAW_DIR)/s2_pub.o $(S2DRAW_DIR)/s2_beginstub.o \
               $(S2DRAW_COMMON)
$(eval $(call M11_IMAGE,$(S2DRAW_DIR),s2dt,P2DW,$(S2DRAW_OBJS)))
# s2pt links s2_pub.o, which AMAPW's size table counts in its row s2_pub
# (s2layout.size_rows; request S2DRAW-2, applied in wave 2's integration)
S2PUB_OBJS := $(S2DRAW_DIR)/s2_pubt.o $(S2DRAW_DIR)/s2_pub.o \
              $(S2DRAW_DIR)/s2_beginstub.o $(S2DRAW_COMMON)
$(eval $(call M11_IMAGE,$(S2DRAW_DIR),s2pt,AMAPW,$(S2PUB_OBJS)))

.PHONY: s2draw_all
s2draw_all: gen $(S2DRAW_DIR)/s2dt.map $(S2DRAW_DIR)/s2pt.map

PARTS += s2draw
