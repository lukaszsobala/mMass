"""Round-trip tests for mSD document serialization (gui.doc).

These need the GUI stack (gui.doc imports wx/config), so they skip cleanly where
that is unavailable -- the rest of the suite stays headless.
"""

import os
import tempfile

import numpy
import pytest

import mspy

# gui.doc pulls in wx + config; skip the whole module if that import fails.
gdoc = pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")


def _roundtrip(peaks):
    """Serialize a peaklist to mSD and parse it back, returning the new peaklist."""
    d = gdoc.document()
    d.spectrum.setpeaklist(mspy.peaklist(peaks))
    xml = d.msd()

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "roundtrip.msd")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(xml)
    return xml, gdoc.parseMSD(path).getDocument().spectrum.peaklist


def test_fwhm_lock_survives_msd_roundtrip():
    """A user-locked FWHM (``_fwhmLocked``) persists across save + reload.

    The lock keeps a manually pinned width from being re-measured on the next
    envelope recalc; if it were dropped on save, reopening the document would let
    the width revert. An unlocked peak must NOT gain the flag.
    """
    locked = mspy.peak(mz=1802.0, ai=100.0, charge=1, isotope=0, fwhm=0.16)
    locked.attributes["_fwhmLocked"] = True
    locked.attributes["envelope"] = {
        "area": 137.0, "sumint": 800.0, "fwhm": 0.16, "shape": "gaussian",
        "isotopes": [(1802.0, 0.5), (1803.0, 0.5)],
    }
    plain = mspy.peak(mz=1900.0, ai=50.0, charge=1, isotope=0, fwhm=0.11)
    plain.attributes["envelope"] = {
        "area": 60.0, "sumint": 400.0, "fwhm": 0.11, "shape": "gaussian",
        "isotopes": [(1900.0, 1.0)],
    }

    xml, reloaded = _roundtrip([locked, plain])

    assert 'fwhmLocked="1"' in xml
    by_mz = {round(p.mz): p for p in reloaded}
    assert by_mz[1802].attributes.get("_fwhmLocked") is True
    assert not by_mz[1900].attributes.get("_fwhmLocked")
    # the locked width itself is preserved
    assert by_mz[1802].fwhm == pytest.approx(0.16, rel=1e-3)


def test_detected_isotope_count_survives_msd_roundtrip():
    """The envelope's ``detected`` count persists across save + reload.

    It records how many leading isotopes were real detected peaks rather than
    modelled tail -- the one thing a rebuild cannot re-derive, since the isotope
    peaks are consumed by the conversion. Dropped on save, a reloaded envelope
    would be measured against the bare theoretical extent and a genuinely measured
    isotope would be silently trimmed off on the next re-convert. An envelope
    saved WITHOUT the count (an older file) must come back without it, so it is
    still recognised as unverifiable rather than silently claiming detection.
    """

    recorded = mspy.peak(mz=1802.0, ai=100.0, charge=1, isotope=0, fwhm=0.16)
    recorded.attributes["envelope"] = {
        "area": 137.0, "sumint": 800.0, "fwhm": 0.16, "shape": "gaussian",
        "detected": 5, "averagineType": "lipid",
        "isotopes": [(1802.0 + i, w) for i, w in enumerate([0.5, 0.3, 0.15, 0.04, 0.01])],
    }
    legacy = mspy.peak(mz=1900.0, ai=50.0, charge=1, isotope=0, fwhm=0.11)
    legacy.attributes["envelope"] = {
        "area": 60.0, "sumint": 400.0, "fwhm": 0.11, "shape": "gaussian",
        "isotopes": [(1900.0, 1.0)],
    }

    xml, reloaded = _roundtrip([recorded, legacy])

    assert 'detected="5"' in xml
    by_mz = {round(p.mz): p for p in reloaded}
    assert by_mz[1802].attributes["envelope"]["detected"] == 5
    assert by_mz[1802].attributes["envelope"]["averagineType"] == "lipid"
    # an older envelope stays uncounted rather than gaining a fabricated one
    assert "detected" not in by_mz[1900].attributes["envelope"]



# ---------------------------------------------------------------------------
# LC-MS runs: every scan in one .msd
# ---------------------------------------------------------------------------


def _lcms_document():
    """A browsable three-scan run: shown scan 2, peaks picked in scans 1 and 3."""

    d = gdoc.document()
    d.title = "run"
    d.scanlist = {}
    d.scanCache = {}
    x = numpy.linspace(500.0, 510.0, 101)
    for scanID in (1, 2, 3):
        scan = mspy.scan(profile=numpy.column_stack([x, numpy.sin(x) + scanID * 2.0]))
        scan.scanNumber = scanID
        scan.msLevel = 1
        scan.retentionTime = 10.0 * scanID
        scan.polarity = 1
        scan.attributes["filterString"] = "FTMS + p ESI Full ms"
        if scanID != 2:
            peak = mspy.peak(mz=505.0 + scanID, ai=10.0 * scanID, charge=2, isotope=0, fwhm=0.02)
            peak.attributes["envelope"] = {
                "area": 3.0 * scanID, "sumint": 9.0, "fwhm": 0.02, "shape": "gaussian",
                "detected": 2, "averagineType": "protein",
                "isotopes": [(505.0 + scanID, 0.6), (505.5 + scanID, 0.4)],
            }
            scan.setpeaklist(mspy.peaklist([peak]))
        d.scanCache[scanID] = scan
        d.scanlist[scanID] = {
            "msLevel": 1, "retentionTime": 10.0 * scanID, "polarity": 1,
            "totIonCurrent": 100.0 * scanID, "basePeakIntensity": 5.0 * scanID,
            "spectrumType": "continuous", "filterString": "FTMS + p ESI Full ms",
            "scanNumber": scanID, "title": "",
        }
    ms2 = mspy.scan(peaklist=mspy.peaklist([mspy.peak(mz=150.0, ai=4.0)]))
    ms2.scanNumber = 4
    ms2.msLevel = 2
    ms2.precursorMZ = 506.0
    d.scanCache[4] = ms2
    d.scanlist[4] = {"msLevel": 2, "precursorMZ": 506.0, "spectrumType": "discrete",
                     "scanNumber": 4, "title": ""}
    d.currentScanID = 2
    d.spectrum = d.scanCache[2]
    return d


def _save(document, tmp_path):
    path = str(tmp_path / "run.msd")
    xml = document.msd()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(xml)
    return path, xml


def test_lcms_run_roundtrips_through_msd(tmp_path):
    original = _lcms_document()
    path, xml = _save(original, tmp_path)

    reloaded = gdoc.parseMSD(path).getDocument()

    assert reloaded.islcms()
    assert list(reloaded.scanlist) == [1, 2, 3, 4]
    assert reloaded.currentScanID == 2
    # the shown scan is the document's spectrum, not a second copy of it
    assert reloaded.scanCache[2] is reloaded.spectrum
    assert reloaded.scanSource is None
    assert reloaded.chromatograms == gdoc.makeChromatograms(original.scanlist)

    for scanID, scan in original.scanCache.items():
        back = reloaded.scanCache[scanID]
        assert back.msLevel == scan.msLevel
        assert back.retentionTime == scan.retentionTime
        assert back.precursorMZ == scan.precursorMZ
        assert back.attributes.get("filterString") == scan.attributes.get("filterString")
        if scan.hasprofile():
            assert numpy.allclose(back.profile, scan.profile, rtol=1e-6)
        assert len(back.peaklist) == len(scan.peaklist)
        for a, b in zip(back.peaklist, scan.peaklist, strict=True):
            assert a.mz == pytest.approx(b.mz)
            assert a.charge == b.charge
            assert a.attributes.get("envelope", {}).get("area") == b.attributes.get(
                "envelope", {}
            ).get("area")

    # saving the reloaded document writes the same file
    assert reloaded.msd() == xml


def test_lcms_msd_opens_as_its_shown_scan_without_chromatogram_support(tmp_path):
    """A reader that does not know <chromatogram> opens the shown scan, intact.

    mSD sections are looked up by tag name anywhere in the file. The shown scan
    here has no peaks, so its <peaklist> is not written at all -- if the other
    scans' peak lists reused that tag, such a reader would hand the shown scan
    the peaks of scan 1.
    """

    class olderParser(gdoc.parseMSD):
        def handleChromatogram(self):
            pass

    original = _lcms_document()
    path, _xml = _save(original, tmp_path)

    older = olderParser(path).getDocument()

    assert not older.islcms()
    assert numpy.allclose(older.spectrum.profile, original.spectrum.profile, rtol=1e-6)
    assert len(older.spectrum.peaklist) == 0


# ---------------------------------------------------------------------------
# Chromatogram traces
# ---------------------------------------------------------------------------


def _meta(rt, tic, filterString=None, msLevel=1, polarity=1):
    return {"msLevel": msLevel, "polarity": polarity, "retentionTime": rt,
            "totIonCurrent": tic, "basePeakIntensity": tic / 10.0,
            "filterString": filterString, "spectrumType": "continuous"}


def test_interleaved_scan_types_get_their_own_chromatogram_trace():
    """Alternating Orbitrap and ion trap full scans do not zigzag in one trace.

    Their ion currents differ, so a single TIC through both jumps between the
    two levels at every scan.
    """

    scanlist = {}
    for i in range(6):
        scanlist[2 * i + 1] = _meta(10.0 * i, 1e7 + i, "FTMS + p ESI Full ms [200.00-2000.00]")
        scanlist[2 * i + 2] = _meta(10.0 * i + 1, 1e6 + i, "ITMS + p ESI Full ms [200.00-2000.00]")
    scanlist[99] = _meta(5.0, 5e5, "ITMS + c ESI d Full ms2 810.79@cid35.00", msLevel=2)

    traces = gdoc.makeChromatograms(scanlist)["traces"]

    assert sorted(t["label"] for t in traces) == ["FTMS", "ITMS"]
    for trace in traces:
        currents = [tic for _rt, tic in trace["tic"]]
        assert len(currents) == 6
        assert currents == sorted(currents)  # monotonic here: no zigzag
        assert len(trace["bpc"]) == 6


def test_single_acquisition_run_has_one_unlabelled_trace():
    scanlist = {i: _meta(float(i), 100.0 + i, "FTMS + p ESI Full ms") for i in range(1, 5)}

    traces = gdoc.makeChromatograms(scanlist)["traces"]

    assert len(traces) == 1
    assert traces[0]["label"] == ""
    assert traces[0]["tic"][0] == pytest.approx((1.0 / 60.0, 101.0))


def test_chromatogram_labels_fall_back_when_the_analyser_is_shared():
    scanlist = {
        1: _meta(1.0, 10.0, "FTMS + p ESI Full ms [200.00-2000.00]"),
        2: _meta(2.0, 10.0, "FTMS + p ESI SIM ms [500.00-520.00]"),
        3: _meta(3.0, 10.0, "FTMS + p ESI Full ms [200.00-2000.00]"),
    }

    labels = sorted(t["label"] for t in gdoc.makeChromatograms(scanlist)["traces"])

    assert labels == ["FTMS + p ESI Full ms [200.00-2000.00]", "FTMS + p ESI SIM ms [500.00-520.00]"]
