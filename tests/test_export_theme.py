"""Exported images and printouts choose their colours, whatever the screen shows.

The spectrum panel is built without being shown, under a light or a dark
system theme (patched); it needs a display for the wx.App and skips without.
"""

import os

import numpy
import pytest

import mspy

panel_spectrum = pytest.importorskip("gui.panel_spectrum", reason="GUI stack (wx) not available")
from gui import doc, mwx  # noqa: E402
from mspy import plot_canvas, plot_objects  # noqa: E402

LIGHT_COLOUR = [16, 71, 185]


@pytest.fixture
def wx_app():
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and os.name != "nt":
        pytest.skip("no display for a wx.App")
    wx = pytest.importorskip("wx")
    app = wx.App.Get() or wx.App(False)
    from gui import images

    if "bgrToolbarNoBorder" not in images.lib:
        images.loadImages()
    return app


def _document(dark):
    x = numpy.linspace(500.0, 1500.0, 4001)
    y = 1000.0 * numpy.exp(-0.5 * ((x - 1000.0) / 0.5) ** 2) + 10.0
    document = doc.document()
    document.title = "test"
    document.spectrum = mspy.scan(profile=numpy.column_stack([x, y]))
    # documents keep their colour inverted while the app is dark
    document.colour = mwx.invertColour(LIGHT_COLOUR) if dark else list(LIGHT_COLOUR)  # pyright: ignore[reportAttributeAccessIssue]
    return document


@pytest.fixture(params=[False, True], ids=["light-system", "dark-system"])
def spectrum(request, wx_app, monkeypatch):
    import wx

    dark = request.param
    monkeypatch.setattr(plot_canvas, "_is_dark_mode", lambda: dark)
    monkeypatch.setattr(plot_objects, "_is_dark_mode", lambda: dark)
    plot_objects.invalidate_dark_mode_cache()

    class Parent(wx.Frame):
        """Stands in for the main frame; its handlers do nothing."""

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    parent = Parent(None, -1, "test", size=wx.Size(800, 600))
    documents = [_document(dark)]
    panel = panel_spectrum.panelSpectrum(parent, documents)
    panel.SetSize(wx.Size(800, 600))
    panel.appendLastSpectrum()
    panel.selectSpectrum(0)
    yield panel, dark
    panel.Destroy()
    parent.Destroy()
    plot_objects.invalidate_dark_mode_cache()


def _pixel(bitmap, x, y):
    image = bitmap.ConvertToImage()
    return (image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y))


def _shown(panel, dark):
    """The panel draws as the system theme says, document colour included."""

    canvas = panel.spectrumCanvas
    assert canvas.isDark() == dark
    assert canvas.properties["canvasColour"] == plot_canvas.THEME_COLOURS[dark]["canvasColour"]
    assert plot_objects._is_dark_mode_cached() == dark
    colour = mwx.invertColour(LIGHT_COLOUR) if dark else LIGHT_COLOUR
    assert list(panel.documents[0].colour) == colour
    assert list(panel.container[2].properties["spectrumColour"]) == colour


@pytest.mark.parametrize("export", [False, True], ids=["light-image", "dark-image"])
def test_image_has_the_chosen_colours(spectrum, export):
    panel, dark = spectrum

    bitmap = panel.getBitmap(600, 400, None, dark=export)

    assert _pixel(bitmap, 2, 2) == plot_canvas.THEME_COLOURS[export]["canvasColour"]
    _shown(panel, dark)


def test_image_as_shown(spectrum):
    panel, dark = spectrum

    bitmap = panel.getBitmap(600, 400, None)

    assert _pixel(bitmap, 2, 2) == plot_canvas.THEME_COLOURS[dark]["canvasColour"]


def test_document_colours_follow_the_image_theme(spectrum):
    panel, dark = spectrum

    with panel.drawnInTheme(not dark):
        assert panel.spectrumCanvas.isDark() == (not dark)
        colour = list(panel.container[2].properties["spectrumColour"])
        assert colour == (LIGHT_COLOUR if dark else mwx.invertColour(LIGHT_COLOUR))

    _shown(panel, dark)


def test_nested_themes_restore_the_enclosing_one(spectrum):
    panel, dark = spectrum

    with panel.drawnInTheme(not dark):
        bitmap = panel.getBitmap(600, 400, None, dark=dark)
        assert _pixel(bitmap, 2, 2) == plot_canvas.THEME_COLOURS[dark]["canvasColour"]

        # back in the enclosing theme, canvas and document colours alike
        canvas = panel.spectrumCanvas
        assert canvas.isDark() == (not dark)
        assert plot_objects._is_dark_mode_cached() == (not dark)
        outer = plot_canvas.THEME_COLOURS[not dark]["canvasColour"]
        assert canvas.properties["canvasColour"] == outer
        colour = list(panel.container[2].properties["spectrumColour"])
        assert colour == (LIGHT_COLOUR if dark else mwx.invertColour(LIGHT_COLOUR))

    _shown(panel, dark)


def test_svg_has_the_chosen_colours(spectrum, tmp_path):
    panel, dark = spectrum
    path = tmp_path / "spectrum.svg"

    panel.getSVG(str(path), 600, 400, None, dark=False)

    text = path.read_text()
    assert 'fill="#1E1E1E"' not in text
    assert 'fill="#FFFFFF"' in text
    _shown(panel, dark)


def test_printout_is_light(spectrum):
    import wx

    panel, dark = spectrum
    printout = panel.getPrintout(1, "test")
    bitmap = wx.Bitmap(1000, 700, 24)
    dc = wx.MemoryDC(bitmap)
    printout.GetDC = lambda: dc
    printout.GetPPIPrinter = lambda: (25, 25)
    printout.GetPageSizePixels = lambda: (1000, 700)
    printout.IsPreview = lambda: False

    printout.OnPrintPage(1)
    dc.SelectObject(wx.NullBitmap)

    # a point inside the plot area, away from the spectrum's peak
    assert _pixel(bitmap, 300, 400) == (255, 255, 255)
    _shown(panel, dark)
