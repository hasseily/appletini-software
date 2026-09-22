CC65_PREFIX ?=
CL65 := $(CC65_PREFIX)cl65
PYTHON ?= python3

BUILD := build
DIST := dist
PROGRAM := $(BUILD)/BOSCO
SYSTEM := $(BUILD)/BOSCO.SYSTEM
DISK := $(DIST)/Appletini-Bosconian.hdv
CFG := bosconian.cfg

# Every .c and .s in this directory is part of the program. crt0.o must be
# first (its STARTUP segment is the entry point at $2000), main.o next,
# then the rest in a fixed order, then the generated sprite/font tables.
SRCS_C := $(wildcard *.c)
SRCS_S := $(filter-out crt0.s,$(wildcard *.s))
ORDERED_C := $(filter main.c,$(SRCS_C)) $(filter-out main.c,$(SRCS_C))
OBJECTS := $(BUILD)/crt0.o \
	$(patsubst %.c,$(BUILD)/%.o,$(ORDERED_C)) \
	$(patsubst %.s,$(BUILD)/%.o,$(SRCS_S)) \
	$(BUILD)/assets.o

# Sprite art: the drawn art in assets/, or -- with ROMS=/path/to/bosco.zip
# (a MAME Bosconian ROM set you own; also an unpacked directory) -- the
# arcade graphics that tools/bosco_rom.py converts through assets/rom_map.txt.
ROMS ?=
ifneq ($(ROMS),)
SPRITES_TXT := $(BUILD)/rom/sprites.txt
FONT_TXT := $(BUILD)/rom/font8.txt
else
SPRITES_TXT := assets/sprites.txt
FONT_TXT := assets/font8.txt
endif
ASSET_SOURCES := $(SPRITES_TXT) $(FONT_TXT)
GEN_ASSETS := tools/gen_assets.py
SPRFILE := $(BUILD)/BOSCO.SPR
HEADERS := $(wildcard *.h)

CFLAGS := -t none --cpu 65c02 --standard c99 -Oirs -I $(BUILD)
AFLAGS := -t none --cpu 65c02 --asm-include-dir .

.PHONY: all clean disk test smoke measure profile

all: $(SYSTEM)

$(BUILD) $(DIST):
	mkdir -p $@

# arcade graphics and font converted from the ROM set (only with ROMS=...)
$(BUILD)/rom/sprites.txt $(BUILD)/rom/font8.txt: tools/bosco_rom.py assets/rom_map.txt assets/sprites.txt assets/font8.txt $(ROMS) | $(BUILD)
	$(PYTHON) tools/bosco_rom.py $(ROMS) --map assets/rom_map.txt --out $(BUILD)/rom

# generated sprite tables: build/assets.s, build/assets.h and the sprite
# file BOSCO.SPR that the game loads into the auxiliary language card
$(BUILD)/assets.s $(BUILD)/assets.h $(SPRFILE): $(GEN_ASSETS) $(ASSET_SOURCES) | $(BUILD)
	$(PYTHON) $(GEN_ASSETS) --assets assets --sprites $(SPRITES_TXT) --font $(FONT_TXT) --build $(BUILD) --quiet

$(BUILD)/assets.o: $(BUILD)/assets.s | $(BUILD)
	$(CL65) $(AFLAGS) -c -o $@ $<

$(BUILD)/%.o: %.c $(HEADERS) $(BUILD)/assets.h | $(BUILD)
	$(CL65) $(CFLAGS) -c -o $@ $<

$(BUILD)/%.o: %.s bosco.inc | $(BUILD)
	$(CL65) $(AFLAGS) -c -o $@ $<

$(PROGRAM): $(OBJECTS) $(CFG) | $(BUILD)
	$(CL65) $(AFLAGS) -C $(CFG) -m $(BUILD)/BOSCO.map \
		-Ln $(BUILD)/BOSCO.lbl -o $@ $(OBJECTS)

$(SYSTEM): $(PROGRAM) tools/build_system.py | $(BUILD)
	$(PYTHON) tools/build_system.py --program $(PROGRAM) --output $@

disk: $(DISK)

$(DISK): $(SYSTEM) $(SPRFILE) tools/build_disk.py | $(DIST)
	$(PYTHON) tools/build_disk.py --system $(SYSTEM) --sprites $(SPRFILE) --output $@

# python unit tests (py65 for the asm modules, pure python for the tools)
test:
	@status=0; \
	for t in $(sort $(wildcard tests/test_*.py)); do \
		echo "== $$t"; \
		$(PYTHON) $$t || status=1; \
	done; \
	exit $$status

smoke: $(DISK)
	$(PYTHON) tools/smoke_test.py --disk $(DISK)

clean:
	rm -rf $(BUILD) $(DIST)

# Per-frame CPU cycles and 1 MHz-bus bytes in the py65 test machine
# (tools/a2sim.py). `profile` rebuilds with -g in build/prof so static C
# functions get labels, then charges cycles to routines.
PROF := $(BUILD)/prof
ROM ?= ../../../appletini-one/docs/Apple2e_Enhanced.rom

measure: $(SYSTEM)
	$(PYTHON) tools/measure_frames.py --rom $(ROM) --frames 900

profile: $(SYSTEM) build/assets.s
	mkdir -p $(PROF)
	for c in $(SRCS_C); do $(CL65) $(CFLAGS) -g -c -o $(PROF)/$${c%.c}.o $$c || exit 1; done
	for a in crt0.s $(SRCS_S); do $(CL65) $(AFLAGS) -g -c -o $(PROF)/$${a%.s}.o $$a || exit 1; done
	$(CL65) $(AFLAGS) -g -c -o $(PROF)/assets.o build/assets.s
	$(CL65) -t none --cpu 65c02 -C bosconian.cfg -Ln $(PROF)/BOSCO.lbl -o $(PROF)/BOSCO \
		$(PROF)/crt0.o $(PROF)/main.o $(filter-out $(PROF)/crt0.o $(PROF)/main.o,$(addprefix $(PROF)/,$(SRCS_C:.c=.o) $(SRCS_S:.s=.o))) $(PROF)/assets.o
	cmp $(PROF)/BOSCO $(BUILD)/BOSCO
	$(PYTHON) tools/measure_frames.py --rom $(ROM) --frames 300 --profile --labels $(PROF)/BOSCO.lbl
