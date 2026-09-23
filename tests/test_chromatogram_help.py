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
