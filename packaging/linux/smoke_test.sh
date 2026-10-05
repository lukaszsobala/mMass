#!/bin/sh
# Smoke test of a built or installed mMass.
#
# 1. headless: find the peaks of a synthetic spectrum and write them out, which
#    runs the frozen NumPy, Numba (JIT compilation), parsers and writers;
# 2. GUI: start mMass under Xvfb, which loads wxPython against the host GTK;
#    still running after the timeout, without a traceback, counts as success.
#
# Usage: smoke_test.sh MMASS_COMMAND [ARG...]   (needs awk, timeout and Xvfb)

set -eu

work=$(mktemp -d)
xvfb=""
cleanup() {
    [ -n "$xvfb" ] && kill "$xvfb" 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT
export MMASS_CONFIG_DIR="$work/config"

echo "== $* --help"
"$@" --help > /dev/null

echo "== headless processing"
awk 'function g(x, c) { d = (x - c) / 0.05; return d * d < 200 ? exp(-d * d / 2) : 0 }
     BEGIN { srand(1)
             for (i = 0; i < 20000; i++) {
                 x = 1000 + i * 0.01
                 printf "%.4f\t%.2f\n", x, 100 + 20 * rand() + 5000 * g(x, 1100) + 2500 * g(x, 1150)
             } }' > "$work/spectrum.xy"
"$@" process "$work/spectrum.xy" --find-peaks --set peakpicking.deisotoping=0 "$work/peaks.msd"
"$@" convert "$work/peaks.msd" "$work/peaks.csv" --peak-list --columns mz
peaks=$(tr -d '\r' < "$work/peaks.csv")
expected=$(printf 'm/z\n1100.0\n1150.0')
if [ "$peaks" != "$expected" ]; then
    echo "Unexpected peak list:"
    echo "$peaks"
    exit 1
fi

echo "== GUI start under Xvfb"
Xvfb :99 -screen 0 1280x1024x24 > /dev/null 2>&1 &
xvfb=$!
sleep 3
status=0
DISPLAY=:99 timeout 30 "$@" > "$work/gui.log" 2>&1 || status=$?
if [ "$status" -ne 124 ] || grep -q Traceback "$work/gui.log"; then
    echo "The GUI did not keep running (exit status $status):"
    cat "$work/gui.log"
    exit 1
fi

echo "Smoke test passed."
