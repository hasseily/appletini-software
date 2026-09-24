# Doom (Freedoom Phase 1) for the Appletini
#
#   make            the data, then DOOM.SYSTEM and the images RENDER.BIN,
#                   LC.BIN, GAME.BIN in $(BUILD)
#   make disk       dist/Appletini-DOOM.hdv (a ProDOS volume sized to the data)
#   make test       the unit tests (py65 and pure Python)
#   make STANDIN=1  the same with the platform's stand-in data set
#                   (tools/make_standin.py) in build/standin
#
# The data: tools/wad2a2.py converts FREEDOOM (default build/freedoom1.wad,
# fetched by tools/fetch_freedoom.py) into build/data. Without the
# converter, or with STANDIN=1, the stand-in data set is used and the
# build goes to build/standin (it has its own doomdata.inc/doomdata.h, so
# its binaries differ). The link (src/doom.cfg) writes all four program
# files at once into $(BUILD). APPLETINI_ROOT points at the appletini-one
# checkout (ProDOS master image, enhanced //e ROM for the test machine).

APPLETINI_ROOT ?= ../../../appletini-one
FREEDOOM ?= build/freedoom1.wad
PYTHON ?= python3
CA65 ?= ca65
CC65 ?= cc65
LD65 ?= ld65

ifeq ($(STANDIN)$(if $(wildcard tools/wad2a2.py),,1),)
BUILD ?= build
# the converted data stays in build/data whatever BUILD is (parallel builds
# such as BUILD=build/rtrack/ share it)
DATA ?= build/data
else
STANDIN := 1
BUILD ?= build/standin
DATA ?= $(BUILD)/data
endif
DIST := dist
DISK := $(DIST)/Appletini-DOOM.hdv

KERNEL_S := kstart space far video input frame loader
# the renderer: src/render/*.s against the converted data; the stand-in data
# has no map, texture or flat directory, so that build keeps the platform's
# test pattern (src/render/stub.s) as render_frame
ifeq ($(STANDIN),)
RENDER_S := $(filter-out stub,$(patsubst src/render/%.s,%,$(wildcard src/render/*.s)))
else
RENDER_S := stub
endif
# the GAME space's sources (another directory can stand in, e.g. a snapshot
# of them while they are being worked on)
GAMESRC ?= src/game
GAME_S := $(patsubst $(GAMESRC)/%.s,%,$(wildcard $(GAMESRC)/*.s))
GAME_C := $(patsubst $(GAMESRC)/%.c,%,$(wildcard $(GAMESRC)/*.c))

OBJS := $(addprefix $(BUILD)/kernel/,$(addsuffix .o,$(KERNEL_S))) \
	$(addprefix $(BUILD)/render/,$(addsuffix .o,$(RENDER_S))) \
	$(addprefix $(BUILD)/game/,$(addsuffix .o,$(GAME_S) $(GAME_C)))
PROGRAM := $(BUILD)/DOOM.SYSTEM $(BUILD)/RENDER.BIN $(BUILD)/LC.BIN $(BUILD)/GAME.BIN

AFLAGS := --cpu 65c02 -g -I src/kernel -I $(DATA)
CFLAGS := -t none --cpu 65c02 --standard c99 -Oirs -g -I $(GAMESRC) -I $(DATA)
DATA_STAMP := $(DATA)/manifest.json

.PHONY: all disk test clean

all: $(PROGRAM)

# --- the data -------------------------------------------------------------
ifeq ($(STANDIN),)
$(DATA_STAMP): tools/wad2a2.py $(FREEDOOM)
	$(PYTHON) tools/wad2a2.py --wad $(FREEDOOM) --out $(DATA)

$(FREEDOOM):
	$(PYTHON) tools/fetch_freedoom.py --out $(dir $(FREEDOOM))
else
$(DATA_STAMP): tools/make_standin.py
	$(PYTHON) tools/make_standin.py --out $(DATA) $(if $(wildcard $(FREEDOOM)),--wad $(FREEDOOM))
endif

$(DATA)/doomdata.inc $(DATA)/doomdata.h: $(DATA_STAMP)

# the renderer's generated tables, once tools/gen_tables.py exists
ifneq ($(wildcard tools/gen_tables.py),)
TABLES_STAMP := $(BUILD)/tables.stamp
$(TABLES_STAMP): tools/gen_tables.py | $(BUILD)
	$(PYTHON) tools/gen_tables.py --out $(BUILD)
	touch $@
AFLAGS += -I $(BUILD)
OBJS += $(BUILD)/render/tables.o

$(BUILD)/render/tables.o: $(TABLES_STAMP) | $(BUILD)/render
	$(CA65) $(AFLAGS) -o $@ $(BUILD)/render/tables.s
endif

# --- assemble, compile, link ----------------------------------------------
$(BUILD)/kernel/%.o: src/kernel/%.s src/kernel/kernel.inc $(DATA)/doomdata.inc $(TABLES_STAMP) | $(BUILD)/kernel
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/render/%.o: src/render/%.s $(wildcard src/render/*.inc) src/kernel/kernel.inc $(DATA)/doomdata.inc $(TABLES_STAMP) | $(BUILD)/render
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/game/%.o: $(GAMESRC)/%.s $(wildcard $(GAMESRC)/*.inc) src/kernel/rview.inc | $(BUILD)/game
	$(CA65) $(AFLAGS) -I $(GAMESRC) -o $@ $<

$(BUILD)/game/%.s: $(GAMESRC)/%.c $(wildcard $(GAMESRC)/*.h) $(DATA)/doomdata.h | $(BUILD)/game
	$(CC65) $(CFLAGS) -o $@ $<

$(BUILD)/game/%.o: $(BUILD)/game/%.s
	$(CA65) $(AFLAGS) -o $@ $<

.PRECIOUS: $(BUILD)/game/%.s

$(PROGRAM) &: $(OBJS) src/doom.cfg
	$(LD65) -C src/doom.cfg -m $(BUILD)/doom.map -Ln $(BUILD)/doom.lbl --dbgfile $(BUILD)/doom.dbg \
		-o $(BUILD)/ $(OBJS) none.lib
	$(PYTHON) tools/check_link.py --build $(BUILD)

# --- the disk -------------------------------------------------------------
disk: $(DISK)

$(DISK): $(PROGRAM) $(DATA_STAMP) tools/build_disk.py | $(DIST)
	$(PYTHON) tools/build_disk.py --build $(BUILD) --data $(DATA) --output $@ \
		--master $(APPLETINI_ROOT)/software/ProDOS_2_4_3.po

# --- tests ----------------------------------------------------------------
# the platform tests build their own stand-in configuration (build/standin)
test:
	@status=0; for t in $(sort $(wildcard tests/test_*.py)); do echo "== $$t"; $(PYTHON) $$t || status=1; done; exit $$status

$(BUILD) $(BUILD)/kernel $(BUILD)/render $(BUILD)/game $(DIST):
	mkdir -p $@

# keeps the converted data and the WAD
clean:
	rm -rf $(BUILD)/kernel $(BUILD)/render $(BUILD)/game $(PROGRAM) $(BUILD)/doom.* \
		$(BUILD)/tables.stamp build/standin $(DIST)
