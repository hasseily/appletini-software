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

ASSET_SOURCES := assets/sprites.txt assets/font8.txt
GEN_ASSETS := tools/gen_assets.py
HEADERS := $(wildcard *.h)

CFLAGS := -t none --cpu 65c02 --standard c99 -Oirs -I $(BUILD)
AFLAGS := -t none --cpu 65c02 --asm-include-dir .

.PHONY: all clean disk test smoke

all: $(SYSTEM)

$(BUILD) $(DIST):
	mkdir -p $@

# generated sprite tables: build/assets.s and build/assets.h
$(BUILD)/assets.s $(BUILD)/assets.h: $(GEN_ASSETS) $(ASSET_SOURCES) | $(BUILD)
	$(PYTHON) $(GEN_ASSETS) --assets assets --build $(BUILD) --quiet

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

$(DISK): $(SYSTEM) tools/build_disk.py | $(DIST)
	$(PYTHON) tools/build_disk.py --system $(SYSTEM) --output $@

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
