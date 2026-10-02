# MUSIC.hdv: a bootable ProDOS disk that plays the 13 songs on the Phasor.
#
#   make         assemble and link MUSIC.SYSTEM (build/), write MUSIC.hdv
#   make clean   remove build/ and MUSIC.hdv
#
# Needs cc65's ca65 and ld65 (2.18 or later), Python 3 and make.

CA65   = ca65
LD65   = ld65
PYTHON = python3

BUILD  = build
VOLUME = MUSIC
MASTER = assets/ProDOS_2_4_3.po

# the player's objects first, then the program's (the link order fixes the
# layout of each segment)
OBJECTS = player irq probe music aytime
OBJS    = $(foreach o,$(OBJECTS),$(BUILD)/$(o).o)

# the songs in the order of src/songs.inc: keys A to M
SONGS = E1M1 E1M2 E1M3 E1M4 E1M5 E1M6 E1M7 E1M8 E1M9 INTER INTRO VICTOR INTROA
SONG_FILES = $(foreach s,$(SONGS),songs/$(s).AY)

.PHONY: all clean

all: MUSIC.hdv

$(BUILD)/%.o: src/%.s src/sound.inc src/tables.inc src/songs.inc
	@mkdir -p $(BUILD)
	$(CA65) --cpu 65C02 -g -I src -o $@ -l $(BUILD)/$*.lst $<

# ld65 writes music.main ($2000-$3FFF) and music.lc ($E900-$FFFF):
# MUSIC.SYSTEM is the one, then the other
$(BUILD)/MUSIC.SYSTEM: $(OBJS) src/music.cfg
	$(LD65) -C src/music.cfg -o $(BUILD)/music -Ln $(BUILD)/music.lbl \
	    -m $(BUILD)/music.map $(OBJS)
	cat $(BUILD)/music.main $(BUILD)/music.lc > $@

MUSIC.hdv: $(BUILD)/MUSIC.SYSTEM $(SONG_FILES) PROFILE.TXT $(MASTER) \
           tools/mkdisk.py
	$(PYTHON) tools/mkdisk.py -o $@ -v $(VOLUME) -m $(MASTER) \
	    $(BUILD)/MUSIC.SYSTEM,SYS,2000 \
	    $(foreach f,$(SONG_FILES),$(f),BIN,1000) \
	    PROFILE.TXT,TXT,0000

clean:
	rm -rf $(BUILD) MUSIC.hdv
