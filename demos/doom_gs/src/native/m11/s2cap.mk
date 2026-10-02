# src/native/m11/s2cap.mk: part s2cap of milestone 11 (docs/SCREENS.md
# 6.1, 6.2, 7.3): the reference captures of upstream on ref816, host only
# (no image of its own).
#
#   build/native/m11/cases/RUN/        the cases of each run of 6.1
#                                      (index.json, cases.pack, blobs.pack,
#                                      calls.z), tools/native/s2cap.py
#   build/native/m11/s2cap/report.json the checkpoint's checks
#
#   make -C src/native -f m11.mk part P=s2cap    the tools' self-check
#                                                (the points resolve)
#   make -C src/native -f m11.mk s2cap-capture   the eleven runs (about
#                                                40 s, 2 jobs)
#   make -C src/native -f m11.mk s2cap-check     the checks, each run
#                                                captured again and compared
#                                                (about 3 minutes)
#   make -C src/native -f m11.mk s2cap-clean     removes the cases
#
# The captures are not part of `all` (M11_HOST): they need ref816 and the
# release image (MILESTONES.md "Setting up") and run the machine eleven
# times. Every variable and target starts with S2CAP_ or s2cap; the
# including makefile's default goal is left alone. ROOT can be set.

S2CAP_HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(S2CAP_HERE)../../..)
S2CAP_PYTHON ?= python3
S2CAP_TOOL := $(ROOT)/tools/native/s2cap.py
S2CAP_JOBS ?= 2

.PHONY: s2cap_all s2cap-capture s2cap-check s2cap-clean

PARTS += s2cap

s2cap_all:
	$(S2CAP_PYTHON) $(S2CAP_TOOL) --points > /dev/null

s2cap-capture:
	$(S2CAP_PYTHON) $(S2CAP_TOOL) --capture --jobs $(S2CAP_JOBS)

s2cap-check:
	$(S2CAP_PYTHON) $(S2CAP_TOOL) --check --twice --jobs $(S2CAP_JOBS)

s2cap-clean:
	rm -rf $(ROOT)/build/native/m11/cases
	rm -f $(ROOT)/build/native/m11/s2cap/report.json
