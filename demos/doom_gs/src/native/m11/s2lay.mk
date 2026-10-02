# src/native/m11/s2lay.mk: part s2lay's builds (docs/SCREENS.md 7.3), read
# by src/native/m11.mk (always, before the part named by P):
#
#   build/native/m11/s2lay/s2lt.*    the test image s2lt in P2DW's room
#                                    (s2_lt.s: s2t_nop, s2t_echo, s2t_stop)
#                                    with MATHW, AUXW, the far layer and the
#                                    test driver s2_drv.s at $F900 (its stub
#                                    handler)
#   build/native/m11/shared/gen/*    the shared includes (m11.mk's gen)
#
# Other parts instantiate m11.mk's M11_COMMON and M11_IMAGE the same way
# for their own directory.

S2LAY_DIR := $(M11)/s2lay
$(eval $(call M11_COMMON,$(S2LAY_DIR)))
S2LAY_OBJS := $(S2LAY_DIR)/s2_lt.o $(S2LAY_DIR)/s2_drv.o \
              $(M11_COMMON_OBJS:%=$(S2LAY_DIR)/%)
$(eval $(call M11_IMAGE,$(S2LAY_DIR),s2lt,P2DW,$(S2LAY_OBJS)))

.PHONY: s2lay_all
s2lay_all: gen $(S2LAY_DIR)/s2lt.map

PARTS += s2lay
