"""Hover help of the chromatogram's trace buttons (gui.panel_chromatogram).

The buttons are named by the analyser token of a Thermo filter string ("FTMS",
"ITMS") or by MS level; their tooltips say in a line what that is.
"""

import pytest

chrom = pytest.importorskip("gui.panel_chromatogram", reason="GUI stack (wx) not available")


def test_survey_trace_names_its_analyser():
    trace = {"key": (1, 1, "FTMS + p ESI Full ms [200.00-2000.00]", None), "msLevel": 1, "scans": [1, 8]}

    assert chrom.traceHelp(trace) == (
        "Fourier transform analyser (Orbitrap or FT-ICR): high resolution.\n"
        "FTMS + p ESI Full ms [200.00-2000.00], 2 scans"
    )


def test_fragment_trace_does_not_explain_the_analyser_again():
    trace = {"key": (2, 1, "ITMS + c ESI d Full ms2 @cid35.00", None), "msLevel": 2, "scans": [3]}

    assert chrom.traceHelp(trace) == (
        "Fragment spectra (MS/MS), one dot per spectrum.\n"
        "ITMS + c ESI d Full ms2 @cid35.00, 1 scan"
    )


def test_unknown_acquisitions_are_not_guessed_at():
    trace = {"key": (1, 1, "IC1", None), "msLevel": 1, "scans": [1, 2, 3]}

    assert chrom.traceHelp(trace) == "Full scans (MS1).\nIC1, 3 scans"


@pytest.fixture
def light(monkeypatch):
    # the colours need no wx.App (and so no display) in the light theme
    monkeypatch.setattr(chrom.mwx.images, "is_dark_mode", lambda: False)


def _traces():
    return {
        "traces": [
            {"label": label, "msLevel": level, "tic": [(0.1, 1.0), (0.2, 2.0)], "bpc": [(0.1, 1.0), (0.2, 2.0)]}
            for label, level in (("FTMS", 1), ("ITMS", 1), ("MS2", 2))
        ]
    }


def test_hidden_traces_are_not_drawn_unless_browsed(light):
    # TIC and BPC of three traces is six lines; hiding two leaves the browsed pair
    plots = chrom.makeChromatogramPlots(_traces(), showBPC=True, active=0, hidden={0, 1, 2})

    assert [plot.properties["legend"] for plot in plots] == ["TIC FTMS", "BPC FTMS"]


def test_a_hidden_trace_leaves_the_others_their_colours(light):
    shown = chrom.makeChromatogramPlots(_traces(), showBPC=False)
    fewer = chrom.makeChromatogramPlots(_traces(), showBPC=False, hidden={1})

    assert [plot.properties["legend"] for plot in fewer] == ["TIC FTMS", "TIC MS2"]
    assert fewer[1].properties["lineColour"] == shown[2].properties["lineColour"]
