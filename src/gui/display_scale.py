"""Helpers for UI scaling in legacy pixel-based UI code.

The scale factor compensates pixel-based metrics (icon bitmaps, widget
heights, spacings) on HiDPI displays. Font point sizes are deliberately NOT
scaled here -- the toolkit already renders points at the system DPI.

Resolution order for ``get_ui_scale()``:

1. ``MMASS_UI_SCALE`` -- explicit manual override (e.g. ``1.5``). Always wins.
2. ``MMASS_UI_AUTOSCALE=0`` -- disable autodetection, fall back to ``1.0``.
3. Autodetected system scale (Windows DPI, GNOME/KDE display scale, X11 DPI).
4. ``1.0`` -- safe default when nothing can be detected.

Detection is import-safe: it never requires a running ``wx.App`` and any
failure (missing tool, odd environment, headless session) degrades quietly to
the next source. The result is cached so the (potentially subprocess-backed)
probes run at most once per process.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
import sys

# Manual override may shrink the UI; autodetection only ever enlarges it
# (auto-shrinking a correctly-sized 1.0 display would be surprising and risky).
_MIN_MANUAL_SCALE = 0.5
_MIN_AUTO_SCALE = 1.0
_MAX_SCALE = 4.0

# Probes that shell out are bounded so a hung helper can never stall startup.
_SUBPROCESS_TIMEOUT = 1.5

_FALSEY = {"0", "false", "no", "off"}


def _parse_positive_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


@functools.lru_cache(maxsize=1)
def get_ui_scale() -> float:
    """Get the effective UI scale factor (cached for the process lifetime).

    See the module docstring for the resolution order.
    """

    override = _parse_positive_float("MMASS_UI_SCALE")
    if override is not None:
        return max(_MIN_MANUAL_SCALE, min(_MAX_SCALE, override))

    if os.environ.get("MMASS_UI_AUTOSCALE", "1").strip().lower() in _FALSEY:
        return 1.0

    detected = detect_system_scale()
    if detected is None:
        return 1.0
    return max(_MIN_AUTO_SCALE, min(_MAX_SCALE, round(detected, 2)))


def scale_metric(value: int, scale: float) -> int:
    """Scale integer UI metrics, preserving -1 default-size sentinel."""

    if value == -1:
        return value
    return int(round(value * scale))


# DETECTION
# ---------


def detect_system_scale() -> float | None:
    """Best-effort detection of the OS display scale, or None if unknown.

    Never raises: every platform probe is wrapped so an unexpected
    environment falls through to the next source and finally to None.
    """

    try:
        if sys.platform.startswith("win"):
            return _detect_windows()
        if sys.platform == "darwin":
            return _detect_macos()
        return _detect_linux()
    except Exception:
        return None


def _run(args: list[str]) -> str | None:
    """Run a helper command, returning stdout or None on any failure."""

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


# Windows
# -------


def _detect_windows() -> float | None:
    import ctypes

    # `windll` only exists on Windows; fetch via getattr so type checkers and
    # non-Windows imports stay happy.
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    # GetScaleFactorForDevice (Win8.1+) reports the per-monitor scale the user
    # picked (125/150/...), independent of this process' DPI-awareness mode.
    try:
        percent = windll.shcore.GetScaleFactorForDevice(0)  # DEVICE_PRIMARY
        if percent:
            return percent / 100.0
    except Exception:
        pass

    # GetDpiForSystem (Win10 1607+) is accurate only for a DPI-aware process,
    # but harmless as a secondary source.
    try:
        dpi = windll.user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass

    # Oldest fallback: system DC logical pixels per inch.
    try:
        user32 = windll.user32
        gdi32 = windll.gdi32
        hdc = user32.GetDC(0)
        if hdc:
            try:
                dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            finally:
                user32.ReleaseDC(0, hdc)
            if dpi:
                return dpi / 96.0
    except Exception:
        pass

    return None


# macOS (low priority; integer backing scale only)
# -------------------------------------------------


def _detect_macos() -> float | None:
    # macOS/Cocoa renders the whole UI in points and scales fonts, layout and
    # hardcoded pixel metrics uniformly by the Retina backing factor, so sizes
    # already track the display. Re-applying that factor here would double the
    # UI size, so we probe the backing scale (for diagnostics / future
    # per-metric tuning) but deliberately report no compensation.
    _macos_backing_scale()
    return None


def _macos_backing_scale() -> float | None:
    """Retina backing scale of the main display (2.0 on Retina, 1.0 otherwise).

    Uses CoreGraphics directly so it works without a Cocoa run loop / wx.App.
    Untested (no macOS hardware available); guarded to fail to None.
    """

    import ctypes

    try:
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/"
            "CoreGraphics.framework/CoreGraphics"
        )
    except OSError:
        return None

    try:
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        display = cg.CGMainDisplayID()

        cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
        cg.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
        mode = cg.CGDisplayCopyDisplayMode(display)
        if not mode:
            return None
        try:
            cg.CGDisplayModeGetPixelWidth.restype = ctypes.c_size_t
            cg.CGDisplayModeGetPixelWidth.argtypes = [ctypes.c_void_p]
            cg.CGDisplayModeGetWidth.restype = ctypes.c_size_t
            cg.CGDisplayModeGetWidth.argtypes = [ctypes.c_void_p]
            pixel_width = cg.CGDisplayModeGetPixelWidth(mode)
            point_width = cg.CGDisplayModeGetWidth(mode)
        finally:
            cg.CGDisplayModeRelease.argtypes = [ctypes.c_void_p]
            cg.CGDisplayModeRelease(mode)
        if point_width:
            return pixel_width / point_width
    except Exception:
        return None
    return None


# Linux / Unix
# ------------


def _detect_linux() -> float | None:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

    # Compositor-specific probes give the true *current* scale (fractional aware)
    # for the active monitor, which is what we want for both X11 and Wayland.
    if any(name in desktop for name in ("gnome", "unity", "ubuntu", "cinnamon")):
        scale = _detect_gnome()
        if scale:
            return scale
    if any(name in desktop for name in ("kde", "plasma")):
        scale = _detect_kde()
        if scale:
            return scale

    # If neither matched (or the probe failed), still try both opportunistically
    # before falling back to generic toolkit/X11 signals.
    if "gnome" not in desktop and "ubuntu" not in desktop:
        scale = _detect_gnome()
        if scale:
            return scale
    if "kde" not in desktop and "plasma" not in desktop:
        scale = _detect_kde()
        if scale:
            return scale

    scale = _detect_toolkit_env()
    if scale:
        return scale

    return _detect_x11_dpi()


# Pattern for a Mutter logical-monitor tuple from GetCurrentState():
#   (x:int, y:int, scale:double, transform:uint32, primary:bool, [...], {...})
# The leading "int, int, float, int, bool" shape is unique to logical monitors
# and never matches the physical-monitor or mode tuples in the same payload.
_GNOME_LOGICAL_MONITOR = re.compile(
    r"\(\s*\d+,\s*\d+,\s*"          # x, y
    r"([0-9]+(?:\.[0-9]+)?),\s*"    # scale
    r"(?:uint32\s*)?\d+,\s*"        # transform
    r"(true|false)"                 # primary
)


def _detect_gnome() -> float | None:
    """Read the active logical-monitor scale from Mutter over D-Bus."""

    output = _run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.gnome.Mutter.DisplayConfig",
            "--object-path",
            "/org/gnome/Mutter/DisplayConfig",
            "--method",
            "org.gnome.Mutter.DisplayConfig.GetCurrentState",
        ]
    )
    if output:
        scale = _parse_gnome_state(output)
        if scale:
            return scale

    # Fallback: integer scaling-factor set via gsettings (X11 / non-fractional).
    output = _run(
        ["gsettings", "get", "org.gnome.desktop.interface", "scaling-factor"]
    )
    if output:
        match = re.search(r"(\d+)", output)
        if match:
            value = int(match.group(1))
            if value >= 1:  # 0 means "auto", which tells us nothing
                return float(value)

    return None


def _parse_gnome_state(output: str) -> float | None:
    primary_scale = None
    first_scale = None
    for match in _GNOME_LOGICAL_MONITOR.finditer(output):
        scale = float(match.group(1))
        if scale <= 0:
            continue
        if first_scale is None:
            first_scale = scale
        if match.group(2) == "true" and primary_scale is None:
            primary_scale = scale
    return primary_scale if primary_scale is not None else first_scale


def _detect_kde() -> float | None:
    """Read the active output scale from KScreen / kwin config."""

    # kscreen-doctor is the supported way to read live output state on Plasma.
    output = _run(["kscreen-doctor", "-o"])
    if output:
        # Prefer an output line flagged as enabled; otherwise take the first.
        scales = [float(m) for m in re.findall(r"[Ss]cale:\s*([0-9.]+)", output)]
        if scales:
            return scales[0]

    # Fall back to the persisted KWin output config (Wayland).
    scale = _detect_kde_config()
    if scale:
        return scale

    return None


def _detect_kde_config() -> float | None:
    import json

    config_home = os.environ.get(
        "XDG_CONFIG_HOME", os.path.expanduser("~/.config")
    )
    path = os.path.join(config_home, "kwinoutputconfig.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None

    # The schema has shifted across Plasma versions, so walk it generically and
    # collect every (priority, enabled, scale) we can find.
    candidates: list[tuple[bool, bool, float]] = []

    def walk(node):
        if isinstance(node, dict):
            scale = node.get("scale")
            if isinstance(scale, (int, float)) and scale > 0:
                enabled = bool(node.get("enabled", True))
                primary = bool(node.get("primary", False))
                candidates.append((primary, enabled, float(scale)))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    if not candidates:
        return None

    for primary, enabled, scale in candidates:
        if primary and enabled:
            return scale
    for _primary, enabled, scale in candidates:
        if enabled:
            return scale
    return candidates[0][2]


def _detect_toolkit_env() -> float | None:
    """Honour explicit toolkit scaling hints exported into the environment."""

    # GDK_SCALE is an integer multiplier GTK/wx will actually apply.
    raw = os.environ.get("GDK_SCALE", "").strip()
    if raw:
        try:
            value = float(raw)
            if value >= 1:
                return value
        except ValueError:
            pass

    # Qt-style hint, occasionally exported for legacy apps by Plasma.
    for name in ("QT_SCALE_FACTOR",):
        raw = os.environ.get(name, "").strip()
        if raw:
            try:
                value = float(raw)
                if value > 0:
                    return value
            except ValueError:
                pass

    return None


def _detect_x11_dpi() -> float | None:
    """Derive a scale from the X resource Xft.dpi (set by many DEs)."""

    output = _run(["xrdb", "-query"])
    if not output:
        return None
    match = re.search(r"^Xft\.dpi:\s*([0-9.]+)", output, re.MULTILINE)
    if not match:
        return None
    try:
        dpi = float(match.group(1))
    except ValueError:
        return None
    if dpi <= 0:
        return None
    scale = dpi / 96.0
    # Only treat a clearly-HiDPI DPI as a scale signal; 96 == 1.0.
    return scale if scale >= 1.05 else None
