"""Peak list columns: the Copy dialog and the Export panel offer the same ones.

Both store their choice in config.export["peaklistColumns"], so a column one
of them lacks was dropped whenever the other was applied. The windows are
built without being shown; they need a display for the wx.App and skip
without.
"""

import os

import pytest

import mspy

peaklistPanel = pytest.importorskip("gui.panel_peaklist", reason="GUI stack (wx) not available")
from gui import config, doc  # noqa: E402
from gui import panel_document_export as exportPanel  # noqa: E402

ENVELOPE_COLUMNS = ["mz", "envarea", "enverr", "envint"]


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


@pytest.fixture
def columns(monkeypatch):
    monkeypatch.setitem(config.export, "peaklistColumns", list(ENVELOPE_COLUMNS))
    monkeypatch.setitem(config.export, "peaklistFormat", "ASCII with Headers")
    monkeypatch.setitem(config.export, "peaklistSeparator", "tab")


def test_every_written_column_can_be_chosen():
    names = [name for name, _, _ in peaklistPanel.EXPORT_COLUMNS]

    assert sorted(names) == sorted(doc.PEAKLIST_COLUMNS)


@pytest.fixture
def export(wx_app, columns):
    import wx

    class Parent(wx.Frame):
        """Stands in for the main frame: the current peak list."""

        def __init__(self):
            wx.Frame.__init__(self, None, -1, "test")
            peak = mspy.peak(500.0, ai=1000.0)
            peak.attributes["envelope"] = {"area": 12.5, "areaError": 0.5, "sumint": 3000.0}
            self.peaklist = mspy.peaklist([peak])

        def getCurrentPeaklist(self, filters=""):
            return self.peaklist

    parent = Parent()
    panel = exportPanel.panelDocumentExport(parent, tool="peaklist")
    yield panel
    panel.Destroy()
    parent.Destroy()


def test_export_panel_keeps_the_envelope_columns(export):
    assert all(export.peaklistColumns[name].IsChecked() for name in ENVELOPE_COLUMNS)

    assert export.getParams()

    assert config.export["peaklistColumns"] == ENVELOPE_COLUMNS


def test_export_panel_writes_the_envelope_columns(export, tmp_path):
    path = tmp_path / "peaks.txt"
    export.getParams()

    export.runExportPeaklist(str(path))

    header, row = path.read_text().splitlines()
    assert header.split("\t") == ["m/z", "env. area", "env. area err.", "sum. env. int."]
    assert [float(value) for value in row.split("\t")] == [500.0, 12.5, 0.5, 3000.0]


def test_copy_dialog_keeps_the_columns_it_did_not_show_changed(wx_app, columns):
    import wx

    parent = wx.Frame(None, -1, "test")
    dialog = peaklistPanel.dlgCopy(parent)
    dialog.columns["envint"].SetValue(False)

    dialog.getData()

    assert config.export["peaklistColumns"] == ["mz", "envarea", "enverr"]
    dialog.Destroy()
    parent.Destroy()
