"""Combining the scans under a range of an LC-MS chromatogram (issue #47).

Dragging across the chromatogram averages (or sums) the scans of the browsed
trace into one spectrum. The combined spectrum stands in for the shown scan but
is volatile: showing a scan drops it and saving the run leaves it out, while
"Extract Combined" keeps it as a document of its own that records what it was
made of.

The run-level checks use the ProteoWizard example run in spectra/, which
interleaves Orbitrap (FTMS) and ion trap (ITMS) full scans -- the two must never
be combined -- with centroided ion trap MS2 scans of a handful of precursors,
which are combined one precursor at a time.
"""

import os

import numpy
import pytest

import mspy

gdoc = pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")


PWIZ = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "spectra",
    "small.pwiz.1.1.mzML",
)


def _scan(x, y, number, rt=0.0):
    scan = mspy.scan(profile=numpy.column_stack([x, y]))
    scan.scanNumber = number
    scan.msLevel = 1
    scan.polarity = 1
    scan.retentionTime = rt
    return scan


# ---------------------------------------------------------------------------
# mspy.combinescans
# ---------------------------------------------------------------------------


def test_combine_averages_or_sums_scans_on_a_shared_raster():
    x = numpy.linspace(500.0, 501.0, 201)
    peak = numpy.exp(-0.5 * ((x - 500.5) / 0.01) ** 2)
    scans = [_scan(x, height * peak, i + 1, rt=float(i)) for i, height in enumerate((100.0, 200.0, 300.0))]

    averaged, used = mspy.combinescans(scans, align=False)
    summed, _used = mspy.combinescans(scans, average=False, align=False)

    assert used == [0, 1, 2]
    assert averaged.profile[:, 1].max() == pytest.approx(200.0, rel=1e-6)
    assert summed.profile[:, 1].max() == pytest.approx(600.0, rel=1e-6)
    assert averaged.retentionTime == pytest.approx(1.0)
    assert averaged.msLevel == 1 and averaged.polarity == 1
    assert averaged.scanNumber is None


def test_combine_never_mixes_scans_of_very_different_sampling():
    fine = numpy.linspace(500.0, 510.0, 5001)
    coarse = numpy.linspace(500.0, 510.0, 201)
    scans = [
        _scan(fine, numpy.ones(len(fine)), 1),
        _scan(coarse, numpy.ones(len(coarse)), 2),
        _scan(fine, numpy.ones(len(fine)), 3),
    ]

    _combined, used = mspy.combinescans(scans, align=False)

    assert used == [0, 2]


def test_combine_needs_data():
    assert mspy.combinescans([mspy.scan(), mspy.scan()]) == (None, [])


def _centroids(peaks, precursor=None):
    scan = mspy.scan(peaklist=mspy.peaklist([mspy.peak(mz=mz, ai=ai) for mz, ai in peaks]))
    scan.msLevel = 2 if precursor else 1
    scan.precursorMZ = precursor
    return scan


def test_centroided_scans_are_combined_peak_by_peak():
    # ion trap like: peaks never closer than ~0.6 Da in a scan, moving ~0.05 between scans
    scans = [
        _centroids([(300.0, 10.0), (300.6, 5.0), (450.02, 100.0)], precursor=810.79),
        _centroids([(300.05, 30.0), (450.0, 50.0), (451.0, 8.0)], precursor=810.75),
    ]

    averaged, used = mspy.combinescans(scans)
    summed, _used = mspy.combinescans(scans, average=False)

    assert used == [0, 1]
    assert not averaged.hasprofile()
    peaks = {round(peak.mz, 1): peak for peak in averaged.peaklist}
    assert sorted(peaks) == [300.0, 300.6, 450.0, 451.0]
    # intensity-weighted m/z, intensity averaged over both scans
    assert peaks[300.0].mz == pytest.approx((300.0 * 10 + 300.05 * 30) / 40)
    assert peaks[300.0].ai == pytest.approx(20.0)
    assert peaks[300.6].ai == pytest.approx(2.5)  # missing in one scan counts as zero
    assert sorted(peak.ai for peak in summed.peaklist)[-1] == pytest.approx(150.0)
    assert averaged.msLevel == 2
    assert averaged.precursorMZ == pytest.approx(810.77)


def test_two_peaks_of_one_scan_are_never_merged():
    scans = [
        _centroids([(500.0, 10.0), (500.001, 10.0), (700.0, 1.0), (900.0, 1.0)]),
        _centroids([(500.0005, 10.0), (700.0, 1.0), (900.0, 1.0)]),
    ]

    combined, _used = mspy.combinescans(scans)

    near500 = [peak for peak in combined.peaklist if abs(peak.mz - 500.0) < 0.01]
    assert len(near500) == 2


# ---------------------------------------------------------------------------
# Traces of the example run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pwiz():
    if not os.path.exists(PWIZ):
        pytest.skip("example run not available")
    parser = mspy.parseMZML(PWIZ)
    parser.load()
    return parser


def _trace(chromatograms, label):
    return next(trace for trace in chromatograms["traces"] if trace["label"] == label)


def test_fragment_spectra_share_a_trace_whatever_their_precursor(pwiz):
    scanlist = pwiz.scanlist()

    assert gdoc.traceKey(scanlist[3]) == gdoc.traceKey(scanlist[4])
    assert gdoc.traceKey(scanlist[3])[2] == "ITMS + c ESI d Full ms2 @cid35.00"
    assert gdoc.traceKey(scanlist[1]) == mspy.acquisitionkey(scanlist[1])

    # the run browses MS2 too; the scan picker's chromatogram stays MS1
    run = gdoc.makeChromatograms(scanlist, msn=True)
    assert [trace["label"] for trace in run["traces"]] == ["FTMS", "ITMS", "MS2"]
    ms2 = _trace(run, "MS2")
    assert ms2["msLevel"] == 2
    assert ms2["scans"][:5] == [3, 4, 5, 6, 7]
    assert len(ms2["scans"]) == sum(1 for meta in scanlist.values() if meta["msLevel"] == 2)
    assert "MS2" not in [trace["label"] for trace in gdoc.makeChromatograms(scanlist)["traces"]]


def test_a_range_of_fragment_spectra_splits_by_precursor(pwiz):
    scanlist = pwiz.scanlist()
    ms2 = _trace(gdoc.makeChromatograms(scanlist, msn=True), "MS2")

    scanIDs = gdoc.scansInRange(scanlist, ms2["key"], 0.0, 30.0)
    groups = dict(
        (round(mz, 1), ids) for mz, ids in gdoc.precursorGroups(scanlist, scanIDs)
    )

    # DDA picked 810.8 five times at 810.73-810.84, and 812.33 once
    assert groups[810.8] == [3, 10, 24, 37, 44]
    assert groups[812.3] == [7]
    assert all(len(ids) >= 1 for ids in groups.values())
    assert sum(len(ids) for ids in groups.values()) == len(scanIDs)


def test_fragment_spectra_of_one_precursor_combine(pwiz):
    scans = [pwiz.scan(scanID) for scanID in (3, 10, 24, 37, 44)]

    combined, used = mspy.combinescans(scans)

    assert used == [0, 1, 2, 3, 4]
    assert combined.msLevel == 2
    assert combined.precursorMZ == pytest.approx(810.786, abs=0.01)
    # the strongest fragment of every scan (736.6-736.7) is one peak of the combination
    top = max(combined.peaklist, key=lambda peak: peak.ai)
    assert top.mz == pytest.approx(736.66, abs=0.05)
    singles = [max(scan.peaklist, key=lambda peak: peak.ai).ai for scan in scans]
    assert min(singles) < top.ai < max(singles)


def test_traces_keep_the_acquisition_and_scans_they_are_drawn_from(pwiz):
    scanlist = pwiz.scanlist()
    chromatograms = gdoc.makeChromatograms(scanlist)

    assert sorted(trace["label"] for trace in chromatograms["traces"]) == ["FTMS", "ITMS"]
    ftms = _trace(chromatograms, "FTMS")
    itms = _trace(chromatograms, "ITMS")
    assert ftms["scans"] == [1, 8, 15, 22, 29, 35, 42]
    assert itms["scans"] == [2, 9, 16, 23, 30, 36, 43]
    assert ftms["key"] == mspy.acquisitionkey(scanlist[1])
    assert len(ftms["tic"]) == len(ftms["scans"])


def test_a_range_takes_only_the_browsed_traces_scans(pwiz):
    scanlist = pwiz.scanlist()
    chromatograms = gdoc.makeChromatograms(scanlist)
    ftms = _trace(chromatograms, "FTMS")
    itms = _trace(chromatograms, "ITMS")

    # 4.0-17.2 covers FTMS 8, 15, 22, 29 but ion trap scan 30 (17.33) is past it
    assert gdoc.scansInRange(scanlist, ftms["key"], 4.0, 17.2) == [8, 15, 22, 29]
    assert gdoc.scansInRange(scanlist, itms["key"], 4.0, 17.2) == [9, 16, 23]


def test_combined_orbitrap_scans_keep_their_resolution(pwiz):
    scanlist = pwiz.scanlist()
    ftms = _trace(gdoc.makeChromatograms(scanlist), "FTMS")
    scans = [pwiz.scan(scanID) for scanID in ftms["scans"][:4]]

    combined, used = mspy.combinescans(scans)

    assert used == [0, 1, 2, 3]
    # each scan's calibration offset is removed, and it is only a few ppm
    assert all(abs(offset) < 10.0 for offset in combined.attributes["alignment"])
    # the average of the strongest peak stays at single-scan scale
    tops = [scan.profile[:, 1].max() for scan in scans]
    assert min(tops) * 0.5 < combined.profile[:, 1].max() <= max(tops)
    # an Orbitrap peak is still a few mDa wide: nothing was blurred onto a coarse raster
    x = combined.profile[:, 0]
    y = combined.profile[:, 1]
    apex = int(numpy.argmax(y))
    half = y[apex] / 2.0
    lo = apex
    while lo > 0 and y[lo] > half:
        lo -= 1
    hi = apex
    while hi < len(y) - 1 and y[hi] > half:
        hi += 1
    assert x[hi] - x[lo] < 0.05


# ---------------------------------------------------------------------------
# The combined spectrum in a run document
# ---------------------------------------------------------------------------


@pytest.fixture
def run(pwiz):
    scanlist = pwiz.scanlist()
    document = gdoc.document()
    document.title = "small"
    document.scanlist = scanlist
    document.chromatograms = gdoc.makeChromatograms(scanlist, msn=True)
    document.scanCache = {scanID: pwiz.scan(scanID) for scanID in scanlist}
    document.currentScanID = 1
    document.spectrum = document.scanCache[1]
    return document


def _combine(document, scanIDs):
    ftms = _trace(document.chromatograms, "FTMS")
    combined, used = mspy.combinescans([document.scanCache[i] for i in scanIDs])
    combination = {
        "mode": "average",
        "scans": [scanIDs[i] for i in used],
        "rtRange": (4.0, 17.2),
        "acquisition": ftms["key"][2],
        "source": document.title,
        "aligned": True,
    }
    document.showCombined(combined, combination, key=ftms["key"])
    return combined


def test_combined_spectrum_stands_in_for_the_scan_until_one_is_shown(run):
    shown = run.spectrum
    shown.setpeaklist(mspy.peaklist([mspy.peak(mz=810.4, ai=5.0)]))

    combined = _combine(run, [8, 15, 22, 29])

    assert run.spectrum is combined
    assert run.currentScanID is None
    assert run.lastScanID() == 1
    assert run.shownScanKey() == gdoc.COMBINED_SCAN_ID
    assert not run.showsRunScan()
    assert combined.attributes["combination"]["scans"] == [8, 15, 22, 29]
    # the scan it replaced is cached with its peaks
    assert run.scanCache[1] is shown and len(shown.peaklist) == 1

    # a ruler drawn on the combined spectrum goes when the spectrum goes
    run.rulers.append(gdoc.ruler(810.0, 1.0, 811.0, 1.0, "x", scanID=gdoc.COMBINED_SCAN_ID))
    run.rulers.append(gdoc.ruler(810.0, 1.0, 811.0, 1.0, "y", scanID=1))

    run.showScan(8, run.scanCache[8])

    assert run.combined is None
    assert run.currentScanID == 8
    assert gdoc.COMBINED_SCAN_ID not in run.scanCache
    assert combined not in run.scanCache.values()
    assert [item.label for item in run.rulers] == ["y"]


def test_saving_a_run_leaves_the_combined_spectrum_out(run, tmp_path):
    _combine(run, [8, 15, 22, 29])
    run.spectrum.setpeaklist(mspy.peaklist([mspy.peak(mz=445.12, ai=1.0)]))
    run.rulers.append(gdoc.ruler(810.0, 1.0, 811.0, 1.0, "x", scanID=gdoc.COMBINED_SCAN_ID))

    xml = run.msd()
    assert "<combination" not in xml
    assert 'scanID="combined"' not in xml

    path = tmp_path / "run.msd"
    path.write_text(xml, encoding="utf-8")
    reloaded = gdoc.parseMSD(str(path)).getDocument()

    # reopened on the scan the combined spectrum replaced, every scan intact
    assert reloaded.currentScanID == 1
    assert reloaded.combined is None
    assert "combination" not in reloaded.spectrum.attributes
    assert len(reloaded.spectrum.peaklist) == 0
    assert set(reloaded.scanCache) == set(run.scanlist)
    for scanID in (1, 8, 29):
        assert len(reloaded.scanCache[scanID].profile) == len(run.scanCache[scanID].profile)


def test_extracted_combined_spectrum_records_what_it_was_made_of(run, tmp_path):
    combined = _combine(run, [8, 15, 22, 29])

    extracted = gdoc.document()
    extracted.title = "small [4 scans averaged]"
    extracted.spectrum = combined.duplicate()
    extracted.notes = gdoc.combinationText(combined.attributes["combination"], run.title)

    assert "Averaged spectrum of 4 scans of small" in extracted.notes
    assert "Scans: 8, 15, 22, 29" in extracted.notes

    path = tmp_path / "combined.msd"
    path.write_text(extracted.msd(), encoding="utf-8")
    reloaded = gdoc.parseMSD(str(path)).getDocument()

    combination = reloaded.spectrum.attributes["combination"]
    assert combination["mode"] == "average"
    assert combination["scans"] == [8, 15, 22, 29]
    assert combination["rtRange"] == pytest.approx((4.0, 17.2))
    assert combination["acquisition"].startswith("FTMS")
    assert combination["source"] == "small"
    assert combination["aligned"] is True
    assert "precursorMZ" not in combination
    assert len(reloaded.spectrum.profile) == len(combined.profile)


def test_extracted_fragment_combination_keeps_its_precursor(pwiz, tmp_path):
    combined, _used = mspy.combinescans([pwiz.scan(scanID) for scanID in (3, 10, 24)])

    extracted = gdoc.document()
    extracted.spectrum = combined
    combined.attributes["combination"] = {
        "mode": "sum", "scans": [3, 10, 24], "precursorMZ": combined.precursorMZ,
    }

    path = tmp_path / "ms2.msd"
    path.write_text(extracted.msd(), encoding="utf-8")
    reloaded = gdoc.parseMSD(str(path)).getDocument()

    combination = reloaded.spectrum.attributes["combination"]
    assert combination["mode"] == "sum"
    assert combination["precursorMZ"] == pytest.approx(combined.precursorMZ, abs=1e-5)
    assert reloaded.spectrum.msLevel == 2
    assert len(reloaded.spectrum.peaklist) == len(combined.peaklist)
