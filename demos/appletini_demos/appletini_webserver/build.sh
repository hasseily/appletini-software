#!/bin/sh
# POSIX equivalent of build.bat: builds the three network apps with cc65.
set -e
cd "$(dirname "$0")"

if ! command -v cl65 >/dev/null 2>&1; then
    echo "ERROR: cl65 was not found in PATH." >&2
    exit 1
fi
if [ ! -f ip65/ip65_web.lib ]; then
    echo "ERROR: missing ip65/ip65_web.lib" >&2
    exit 1
fi
mkdir -p build

build() {
    name=$1
    shift
    cl65 -t apple2 --cpu 6502 -Oirs --warnings-as-errors \
        -C apple2-system.cfg \
        -m "build/$name.map" \
        -l "build/$name.lst" \
        -o "build/$name.SYSTEM" \
        "$@" appletini_net.c appletini_timer.s ip65/ip65_web.lib
}

build A2WEBSRV webserver.c
build A2LEGACY browser_legacy.c
cl65 -t apple2 --cpu 6502 -Oirs --warnings-as-errors -C apple2-system.cfg -I http_client \
    -m build/A2BROWSE.map -Ln build/A2BROWSE.lbl -o build/A2BROWSE.SYSTEM \
    browser.c appletini_http.c http_client/net.c http_client/net.s
build A2IMG a2img.c a2img_net.s

echo "Built build/A2WEBSRV.SYSTEM, build/A2BROWSE.SYSTEM and build/A2IMG.SYSTEM"
