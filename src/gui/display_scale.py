"""Helpers for UI scaling in legacy pixel-based UI code.

The scale factor compensates pixel-based metrics (icon bitmaps, widget
heights, spacings) on HiDPI displays. Font point sizes are deliberately NOT
scaled here -- the toolkit already renders points at the system DPI.

Resolution order for ``get_ui_scale()``:

1. ``MMASS_UI_SCALE`` -- explicit manual override (e.g. ``1.5``). Always wins.
2. ``MMASS_UI_AUTOSCALE=0`` -- disable autodetection, fall back to ``1.0``.
3. Autodetected system scale (Windows DPI, GNOME/KDE display scale, X11 DPI).
   On the native Wayland (GTK) backend autodetection reports no compensation:
   the compositor already scales the whole surface, like macOS/Retina. On the
   X11/XWayland backend GTK applies an integer window scale of its own
   (``GDK_SCALE`` / XSETTINGS ``Gdk/WindowScalingFactor``); that factor is
   divided out so we only compensate the residual the toolkit does not handle.
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


def enable_high_dpi_awareness() -> None:
    """Opt the process into per-monitor DPI awareness (Windows only).

    Must run before wx creates any window -- ideally before ``import wx`` --
    because process DPI awareness is locked in by the first caller. Without it a
    frozen/manifest-less build is treated as 96 DPI and Windows bitmap-stretches
    the whole UI on HiDPI displays, so text and icons look blurry (and our own
    scaling then compounds with the OS stretch). With it, Windows renders at the
    native resolution and wx draws fonts crisply at the real DPI.

    No-op on non-Windows; every probe is guarded so an old OS degrades quietly.
    """

    if not sys.platform.startswith("win"):
        return

    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return

    # Per-Monitor v2 (Win10 1703+): sharpest, follows per-monitor DPI changes.
    try:
        set_ctx = windll.user32.SetProcessDpiAwarenessContext
        set_ctx.restype = ctypes.c_bool
        set_ctx.argtypes = [ctypes.c_void_p]
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
        if set_ctx(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass

    # Per-Monitor (Win8.1+).
    try:
        windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass

    # System DPI aware (Vista+).
    try:
        windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# DETECTION
# ---------


def debug_report() -> dict:
    """Diagnostic snapshot of scale resolution, for MMASS_DPI_DEBUG.

    Pure (no wx); callers can fold in window/toolkit values separately.
    """

    report = {
        "platform": sys.platform,
        "env.MMASS_UI_SCALE": os.environ.get("MMASS_UI_SCALE", "") or "(unset)",
        "env.MMASS_UI_AUTOSCALE": os.environ.get("MMASS_UI_AUTOSCALE", "")
        or "(unset)",
        "detect_system_scale": detect_system_scale(),
        "get_ui_scale": get_ui_scale(),
    }
    if sys.platform.startswith("win"):
        import ctypes

        windll = getattr(ctypes, "windll", None)
        raw = {}
        if windll is not None:
            dpi = _windows_primary_monitor_dpi(windll)
            raw["GetDpiForMonitor"] = dpi
            try:
                raw["GetDpiForSystem"] = windll.user32.GetDpiForSystem()
            except Exception as exc:
                raw["GetDpiForSystem"] = f"err: {exc}"
            try:
                raw["GetScaleFactorForDevice"] = (
                    windll.shcore.GetScaleFactorForDevice(0)
                )
            except Exception as exc:
                raw["GetScaleFactorForDevice"] = f"err: {exc}"
        report["windows_raw"] = raw
    elif sys.platform != "darwin":
        report["linux_raw"] = {
            "native_wayland_gtk": _running_native_wayland_gtk(),
            "linux_scale": _detect_linux_scale(),
            "gtk_x11_window_scale": _gtk_x11_window_scale(),
        }
    return report


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

    # Primary monitor's *effective* DPI (Win8.1+). This is the most reliable
    # source: it reflects the user's chosen scale (125/150/200%) and, unlike
    # GetDpiForSystem, is independent of this process' DPI-awareness mode.
    dpi = _windows_primary_monitor_dpi(windll)
    if dpi:
        return dpi / 96.0

    # System DPI (Win10 1607+). Accurate once the process is DPI-aware, which we
    # ensure via enable_high_dpi_awareness() before this runs.
    try:
        dpi = windll.user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass

    # GetScaleFactorForDevice is documented as unreliable and frequently returns
    # SCALE_100_PERCENT even on HiDPI displays, so only trust a HiDPI answer.
    try:
        percent = windll.shcore.GetScaleFactorForDevice(0)  # DEVICE_PRIMARY
        if percent and percent > 100:
            return percent / 100.0
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


def _windows_primary_monitor_dpi(windll) -> int | None:
    """Effective DPI of the primary monitor via GetDpiForMonitor, or None."""

    import ctypes

    try:

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        user32 = windll.user32
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.MonitorFromPoint.argtypes = [POINT, ctypes.c_ulong]
        # MONITOR_DEFAULTTOPRIMARY == 1
        hmonitor = user32.MonitorFromPoint(POINT(0, 0), 1)
        if not hmonitor:
            return None

        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        get_dpi = windll.shcore.GetDpiForMonitor
        get_dpi.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        # MDT_EFFECTIVE_DPI == 0, S_OK == 0
        if get_dpi(hmonitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            if dpi_x.value:
                return dpi_x.value
    except Exception:
        return None
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


def _running_native_wayland_gtk() -> bool:
    """True when wx/GTK will draw on the native Wayland backend.

    GTK3 picks the Wayland backend whenever ``WAYLAND_DISPLAY`` is set, unless
    ``GDK_BACKEND`` forces something else (e.g. ``x11`` -> XWayland). On the
    native backend the compositor scales the whole surface by the output scale,
    so GTK already enlarges every pixel metric for us.
    """

    if not os.environ.get("WAYLAND_DISPLAY", "").strip():
        return False
    backend = os.environ.get("GDK_BACKEND", "").strip().lower()
    if backend and "wayland" not in backend:
        # Explicitly forced onto another backend (typically x11 / XWayland),
        # where GTK does *not* auto-scale and our compensation is still needed.
        return False
    return True


def _detect_linux() -> float | None:
    # Like macOS/Cocoa, GTK on the native Wayland backend renders the entire UI
    # at the compositor's output scale: fonts, layout and hardcoded pixel
    # metrics all track the display already. Re-applying the detected scale here
    # would double the size of buttons and widget widths, so report no
    # compensation.
    if _running_native_wayland_gtk():
        return None

    scale = _detect_linux_scale()
    if scale is None:
        return None

    # On the X11/XWayland backend GTK still applies an *integer* window scale of
    # its own (from GDK_SCALE or the XSETTINGS Gdk/WindowScalingFactor that a
    # compositor like Mutter/KWin publishes for XWayland clients). That already
    # enlarges every pixel metric, so compensating by the full detected scale on
    # top double-scales the UI -- e.g. GDK_BACKEND=x11 on GNOME @200% gave a 4x
    # UI (GTK 2x * our 2x). Divide the toolkit's own factor out and keep only the
    # residual (which is 1.0 for integer scales, but e.g. 1.5 for a 150% display
    # where GTK applies a window scale of 1 and only bumps the font DPI).
    window_scale = _gtk_x11_window_scale()
    if window_scale > 1:
        scale = scale / window_scale
    return scale


def _detect_linux_scale() -> float | None:
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


def _gtk_x11_window_scale() -> int:
    """Integer window scale GTK's X11 backend will apply to the UI.

    Mirrors GDK's own precedence: an explicit ``GDK_SCALE`` wins, otherwise the
    XSETTINGS ``Gdk/WindowScalingFactor`` published by the compositor (Mutter
    sets it to the per-monitor integer scale for XWayland clients). Defaults to
    1 when nothing applies (plain X11 with no HiDPI scaling).
    """

    raw = os.environ.get("GDK_SCALE", "").strip()
    if raw:
        try:
            value = int(float(raw))
            if value >= 1:
                return value
        except ValueError:
            pass

    value = _read_x11_xsetting_int("Gdk/WindowScalingFactor")
    if value and value >= 1:
        return value
    return 1


def _read_x11_xsetting_int(name: str) -> int | None:
    """Read an integer XSETTINGS value (e.g. Gdk/WindowScalingFactor) via Xlib.

    Parses the ``_XSETTINGS_SETTINGS`` property on the XSETTINGS manager window
    directly through libX11 so it works without GTK/wx. Returns None on any
    failure (no display, no manager, missing/non-int setting).
    """

    import ctypes

    try:
        xlib = ctypes.CDLL("libX11.so.6")
    except OSError:
        return None

    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    dpy = xlib.XOpenDisplay(None)
    if not dpy:
        return None

    try:
        xlib.XDefaultScreen.restype = ctypes.c_int
        xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
        xlib.XInternAtom.restype = ctypes.c_ulong
        xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        xlib.XGetSelectionOwner.restype = ctypes.c_ulong
        xlib.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xlib.XGetWindowProperty.restype = ctypes.c_int
        xlib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        xlib.XFree.argtypes = [ctypes.c_void_p]

        screen = xlib.XDefaultScreen(dpy)
        sel = xlib.XInternAtom(dpy, f"_XSETTINGS_S{screen}".encode(), False)
        owner = xlib.XGetSelectionOwner(dpy, sel)
        if not owner:
            return None
        prop = xlib.XInternAtom(dpy, b"_XSETTINGS_SETTINGS", False)

        actual_type = ctypes.c_ulong()
        actual_fmt = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        # AnyPropertyType == 0; request up to 16 MiB of the property in one go.
        status = xlib.XGetWindowProperty(
            dpy, owner, prop, 0, 1 << 22, False, 0,
            ctypes.byref(actual_type), ctypes.byref(actual_fmt),
            ctypes.byref(nitems), ctypes.byref(bytes_after), ctypes.byref(data),
        )
        if status != 0 or not data:
            return None
        try:
            buf = bytes(bytearray(data[i] for i in range(nitems.value)))
        finally:
            xlib.XFree(data)
        return _parse_xsettings_int(buf, name)
    finally:
        xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xlib.XCloseDisplay(dpy)


def _parse_xsettings_int(buf: bytes, name: str) -> int | None:
    """Find an integer setting by name in a raw _XSETTINGS_SETTINGS blob."""

    import struct

    try:
        if len(buf) < 12:
            return None
        endian = "<" if buf[0] == 0 else ">"  # byte-order flag
        (n_settings,) = struct.unpack(endian + "I", buf[8:12])
        off = 12
        for _ in range(n_settings):
            stype = buf[off]
            off += 2  # type byte + 1 pad
            (nlen,) = struct.unpack(endian + "H", buf[off:off + 2])
            off += 2
            key = buf[off:off + nlen].decode("latin-1")
            off += nlen
            off += (4 - nlen % 4) % 4  # pad name to 4 bytes
            off += 4                   # last-change serial
            if stype == 0:             # XSettingsTypeInteger
                (value,) = struct.unpack(endian + "i", buf[off:off + 4])
                off += 4
                if key == name:
                    return value
            elif stype == 1:           # XSettingsTypeString
                (slen,) = struct.unpack(endian + "I", buf[off:off + 4])
                off += 4 + slen
                off += (4 - slen % 4) % 4
            elif stype == 2:           # XSettingsTypeColor
                off += 8
            else:
                return None            # unknown type: cannot keep parsing
    except (IndexError, struct.error):
        return None
    return None
