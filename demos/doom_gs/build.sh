#!/bin/sh
# Builds build/native/DOOM.hdv from nothing: fetches upstream and its
# release image, runs the release on the reference machine for the tables
# the renderer takes from it, then assembles and links every part of the
# game and writes the disk. About a minute; needs python3, cc, make and
# cc65 (ca65, ld65) on PATH, and appletini-one's ProDOS_2_4_3.po (beside
# this repository, or APPLETINI_ROOT).
set -e
cd "$(dirname "$0")"
JOBS=${JOBS:-8}

python3 tools/fetch_upstream.py
python3 tools/v816/imgmatch.py > /dev/null
make -s -j"$JOBS" -C tools/ref816
python3 tools/ref816/make_image.py > /dev/null
python3 tools/native/rendercap.py --jobs "$JOBS" > /dev/null
python3 tools/native/rtables.py > /dev/null
make -s -j"$JOBS" -C tools/a2vm
make -s -j"$JOBS" -C src/sound
make -s -j"$JOBS" -C src/native -f render.mk
python3 tools/native/wadconv.py --store > /dev/null
make -s -j"$JOBS" -C src/native -f level.mk
make -s -j"$JOBS" -C src/native -f m11.mk > /dev/null
# the tic code's placement in the core and the slots (docs/SPEED.md)
mkdir -p build/native/game/shared
cp tools/native/gplace-f122.json build/native/game/shared/placement.json
python3 tools/native/playdisk.py
