# src/native/calib.mk: CALIB.SYSTEM, the calibration disk's program
# (calib.s, calib.cfg; docs/results/calib.md), assembled with ca65 and
# linked with ld65 (cc65 2.18) into build/native/calib/obj:
#
#   CALIB.SYSTEM            the program (ProDOS loads it at $2000)
#   calib.lbl, .map, .lst   symbols (VICE labels), map, listing
#
# It includes GEN's files, which tools/native/calibdisk.py writes from the
# play build (build/native/play): calibplay.inc (the addresses), far.bin,
# kern.bin, pw.bin (the game's routines) and calibpred.inc (a2vm's
# figures). The disk, build/native/CALIB.hdv, is calibdisk.py's:
#
#   python3 tools/native/calibdisk.py          the gen, this make, a2vm,
#                                              the disk
#   make -f calib.mk ROOT=$PWD                 this program alone (GEN
#                                              must exist)
#   make -f calib.mk clean                     removes OUT

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
CALIB ?= $(ROOT)/build/native/calib
GEN ?= $(CALIB)/gen
OUT ?= $(CALIB)/obj
SRC ?= $(HERE)calib.s

CA65 = ca65
LD65 = ld65
ASFLAGS = --cpu 65C02 -g -I $(GEN) --bin-include-dir $(GEN)
GENFILES = $(GEN)/calibplay.inc $(GEN)/calibpred.inc $(GEN)/far.bin \
           $(GEN)/kern.bin $(GEN)/pw.bin

.PHONY: all clean

all: $(OUT)/CALIB.SYSTEM

$(GENFILES):
	@echo "no $@: run python3 tools/native/calibdisk.py" >&2
	@exit 1

$(OUT)/calib.o: $(SRC) $(GENFILES)
	@mkdir -p $(OUT)
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/calib.lst $(SRC)

$(OUT)/CALIB.SYSTEM: $(OUT)/calib.o $(HERE)calib.cfg
	$(LD65) -C $(HERE)calib.cfg -o $@ -Ln $(OUT)/calib.lbl \
	    -m $(OUT)/calib.map $(OUT)/calib.o

clean:
	rm -rf $(OUT)
