"""Linux display-scale detection (gui.display_scale), without a display."""

import sys

import pytest

from gui import display_scale

# GetCurrentState from Mutter 40 (AlmaLinux 9) on X11; SCALE is the logical
# monitor's scale
MUTTER_STATE = (
    "(uint32 2, [(('screen', 'unknown', 'unknown', 'unknown'), "
    "[('2560x1600@60.000', 2560, 1600, 60.0, 1.0, [1.0, 2.0], "
    "{'is-current': <true>, 'is-preferred': <true>})], "
    "{'is-builtin': <false>, 'display-name': <'Unknown Display'>})], "
    "[(0, 0, SCALE, uint32 0, true, "
    "[('screen', 'unknown', 'unknown', 'unknown')], @a{sv} {})], "
    "{'layout-mode': <uint32 2>, 'global-scale-required': <true>})"
)


@pytest.fixture
def x11_session(monkeypatch, tmp_path):
    """An X11 session in which every probe answers nothing until told to."""

    monkeypatch.setattr(sys, "platform", "linux")
    for name in (
        "MMASS_UI_SCALE",
        "MMASS_UI_AUTOSCALE",
        "WAYLAND_DISPLAY",
        "GDK_BACKEND",
        "GDK_SCALE",
        "QT_SCALE_FACTOR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    # no kwinoutputconfig.json
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    answers = {
        # what gsettings prints; it must never be read as a scale
        "gsettings": "uint32 2\n",
    }
    xsettings = {}

    def run(args):
        return answers.get(args[0])

    monkeypatch.setattr(display_scale, "_run", run)
    monkeypatch.setattr(display_scale, "_read_x11_xsetting_int", xsettings.get)
    display_scale.get_ui_scale.cache_clear()
    yield answers, xsettings
    display_scale.get_ui_scale.cache_clear()


def test_no_compositor_answer_means_no_scaling(x11_session):
    # Mutter absent (another desktop, a remote session): "uint32 2" from
    # gsettings once parsed as 32 and gave a 4x UI
    assert display_scale.get_ui_scale() == 1.0


def test_mutter_scale_is_read(x11_session):
    answers, _xsettings = x11_session
    answers["gdbus"] = MUTTER_STATE.replace("SCALE", "1.5")

    assert display_scale.get_ui_scale() == 1.5


def test_gtk_window_scale_is_divided_out(x11_session):
    # GNOME on Xorg at 200%: GTK already doubles everything
    answers, xsettings = x11_session
    answers["gdbus"] = MUTTER_STATE.replace("SCALE", "2.0")
    xsettings["Gdk/WindowScalingFactor"] = 2

    assert display_scale.get_ui_scale() == 1.0


def test_native_wayland_is_left_to_the_compositor(x11_session, monkeypatch):
    answers, _xsettings = x11_session
    answers["gdbus"] = MUTTER_STATE.replace("SCALE", "2.0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    assert display_scale.get_ui_scale() == 1.0


def test_x11_dpi_is_the_last_resort(x11_session):
    answers, _xsettings = x11_session
    answers["xrdb"] = "Xft.antialias:\t1\nXft.dpi:\t192\n"

    assert display_scale.get_ui_scale() == 2.0
