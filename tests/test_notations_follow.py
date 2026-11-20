"""Annotations, sequence matches and difference rulers follow the spectrum.

No processing step deletes them: calibration moves them along the m/z axis,
and steps that change intensities carry them as mspy carries the peaks it
keeps. gui.processing and gui.doc import wx, so the module skips where the GUI
stack is unavailable.
"""

import numpy
import pytest

import mspy

processing = pytest.importorskip("gui.processing", reason="GUI stack (wx) not available")
gdoc = pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")


def _settings():
    return {
        "baseline": {"precision": 15, "offset": 0.0, "allowNegative": 0, "preservePeaks": 0},
        "smoothing": {"method": "GA", "windowSize": 0.3, "cycles": 2, "preservePeaks": 0},
        "math": {"multiplier": 3.0, "preservePeaks": 0},
    }


def _document():
    """A peak at 500 standing on a baseline of 200, annotated and labelled."""

    x = numpy.linspace(495.0, 505.0, 2001)
    y = 200.0 + 1000.0 * numpy.exp(-0.5 * ((x - 500.0) / 0.05) ** 2)
    document = gdoc.document()
    document.spectrum = mspy.scan(profile=numpy.column_stack([x, y]))
    document.annotations.append(gdoc.annotation("M", 500.0, 1200.0, base=200.0))
    document.rulers.append(gdoc.ruler(500.0, 1200.0, 501.0, 200.0, height=1500.0))
    return document


def test_baseline_correction_takes_the_baseline_off_the_labels():
    document = _document()
    processing.subtractBaseline(document.spectrum, _settings(), document)

    (annotation,) = document.annotations
    assert annotation.base == pytest.approx(0.0, abs=20.0)
    assert annotation.ai - annotation.base == pytest.approx(1000.0, rel=0.03)
    (ruler,) = document.rulers
    assert ruler.ai1 == pytest.approx(1000.0, rel=0.03)
    assert ruler.height == 1500.0  # put there by hand


def test_smoothing_reads_the_labels_off_the_smoothed_profile():
    document = _document()
    processing.smoothScan(document.spectrum, _settings(), document)

    profile = document.spectrum.profile
    expected = numpy.interp(500.0, profile[:, 0], profile[:, 1])
    assert expected < 1100.0  # the apex came down
    assert document.annotations[0].ai == pytest.approx(expected)
    assert document.annotations[0].base == 200.0
    assert document.rulers[0].ai1 == pytest.approx(expected)


@pytest.mark.parametrize(
    "operation, change",
    [
        ("normalize", lambda v: v / 12.0),
        ("multiply", lambda v: v * 3.0),
        ("squareroot", numpy.sqrt),
    ],
)
def test_math_scales_the_labels_as_the_profile(operation, change):
    document = _document()
    processing.mathScan(document.spectrum, operation, _settings(), document)

    (annotation,) = document.annotations
    assert annotation.ai == pytest.approx(change(1200.0))
    assert annotation.base == pytest.approx(change(200.0))
    (ruler,) = document.rulers
    assert (ruler.ai1, ruler.ai2) == pytest.approx((change(1200.0), change(200.0)))
    assert ruler.height == pytest.approx(change(1500.0))


def test_subtracting_a_spectrum_reads_the_labels_off_the_difference():
    document = _document()
    other = mspy.scan(profile=document.spectrum.profile * numpy.array((1.0, 0.25)))
    processing.mathPair(document.spectrum, "subtract", other, False, document)

    assert document.annotations[0].ai == pytest.approx(0.75 * 1200.0, rel=0.01)


def test_matches_follow_like_annotations():
    document = _document()
    sequence = mspy.sequence("PEPTIDE")
    sequence.matches = [gdoc.match("b2", 500.0, 1200.0, base=200.0)]
    document.sequences.append(sequence)
    processing.mathScan(document.spectrum, "multiply", _settings(), document)

    assert sequence.matches[0].ai == pytest.approx(3600.0)


def test_calibration_moves_annotations_matches_and_rulers():
    document = _document()
    sequence = mspy.sequence("PEPTIDE")
    sequence.matches = [gdoc.match("b2", 501.0, 300.0)]
    document.sequences.append(sequence)

    processing.recalibrateNotations(document, lambda params, mz: mz + params[0], (0.5,))

    assert document.annotations[0].mz == 500.5
    assert sequence.matches[0].mz == 501.5
    assert (document.rulers[0].mz1, document.rulers[0].mz2) == (500.5, 501.5)


def test_a_scan_not_shown_carries_only_its_own_rulers():
    """In an LC-MS run the annotations belong to the spectrum shown; a scan
    processed in the background takes only the rulers filed under it."""

    document = _document()
    shown = document.spectrum
    background = mspy.scan(profile=shown.profile.copy())
    document.scanCache = {7: background}
    document.rulers.append(gdoc.ruler(500.0, 1200.0, 501.0, 200.0, scanID=7))

    processing.mathScan(background, "multiply", _settings(), document)

    assert document.annotations[0].ai == 1200.0
    assert document.rulers[0].ai1 == 1200.0  # filed under no scan: the one shown
    assert document.rulers[1].ai1 == pytest.approx(3600.0)
