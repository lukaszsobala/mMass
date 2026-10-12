#!/usr/bin/env python3
"""Smoke test of a frozen mMass on Windows and macOS.

The counterpart of packaging/linux/smoke_test.sh, in Python because neither
system has a POSIX shell with awk and timeout to rely on:

1. headless: find the peaks of a synthetic spectrum and write them out, which
   runs the frozen NumPy, Numba (JIT compilation), parsers and writers, and
   loads wxPython;
2. GUI: start mMass with an empty configuration directory; still running
   after the wait, with its main window open and its configuration written,
   counts as success.

Both executables are windowed, so nothing they print is seen here and an
unhandled exception on Windows opens a dialog instead of ending the process:
hence the timeouts, and the look at the window titles.

Usage: smoke_test.py MMASS_EXECUTABLE
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HEADLESS_TIMEOUT = 300  # s; the first run compiles the Numba kernels
GUI_WAIT = 30  # s


def write_spectrum(path: Path) -> None:
    """Two Gaussian peaks, at m/z 1100 and 1150, on a noisy baseline."""

    def gauss(x: float, centre: float) -> float:
        d = (x - centre) / 0.05
        return math.exp(-d * d / 2) if d * d < 200 else 0.0

    rng = random.Random(1)
    with path.open("w", encoding="ascii") as f:
        for i in range(20000):
            x = 1000 + i * 0.01
            y = 100 + 20 * rng.random() + 5000 * gauss(x, 1100) + 2500 * gauss(x, 1150)
            f.write(f"{x:.4f}\t{y:.2f}\n")


def run(command: list[str], env: dict[str, str]) -> None:
    print("==", " ".join(command), flush=True)
    try:
        subprocess.run(command, env=env, check=True, timeout=HEADLESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        sys.exit(f"No result after {HEADLESS_TIMEOUT} s (an error dialog?)")
    except subprocess.CalledProcessError as error:
        sys.exit(f"Exit status {error.returncode}")


def window_titles(pid: int) -> list[str]:
    """Titles of the visible top-level windows of a process (Windows)."""

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buffer, 512)
            titles.append(buffer.value)
        return True

    user32.EnumWindows(collect, 0)
    return titles


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    mmass = str(Path(sys.argv[1]).resolve())

    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        env = {**os.environ, "MMASS_CONFIG_DIR": str(work / "config")}

        run([mmass, "--help"], env)

        spectrum = work / "spectrum.xy"
        peaks = work / "peaks.msd"
        table = work / "peaks.csv"
        write_spectrum(spectrum)
        run([mmass, "process", str(spectrum), "--find-peaks",
             "--set", "peakpicking.deisotoping=0", str(peaks)], env)
        run([mmass, "convert", str(peaks), str(table),
             "--peak-list", "--columns", "mz"], env)
        found = table.read_text(encoding="utf-8").split()
        if found != ["m/z", "1100.0", "1150.0"]:
            print("Unexpected peak list:", found)
            return 1

        print("== GUI start", flush=True)
        gui_config = work / "gui-config"
        fault_log = work / "mmass-faulthandler.log"
        env = {**os.environ, "MMASS_CONFIG_DIR": str(gui_config),
               "MMASS_FAULTHANDLER": "1"}
        process = subprocess.Popen([mmass], env=env, cwd=work)
        try:
            time.sleep(GUI_WAIT)
            status = process.poll()
            titles = window_titles(process.pid) if sys.platform == "win32" else None
        finally:
            process.kill()
            process.wait()

        failure = None
        if status is not None:
            failure = f"The GUI did not keep running (exit status {status})"
        elif titles is not None and not any(t.startswith("mMass") for t in titles):
            failure = f"No mMass window among the open windows: {titles}"
        elif not gui_config.is_dir() or not any(gui_config.iterdir()):
            failure = "The GUI wrote no configuration"
        if failure:
            print(failure)
            if fault_log.exists():
                print(fault_log.read_text(encoding="utf-8", errors="replace"))
            return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
