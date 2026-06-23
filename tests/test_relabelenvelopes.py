"""Tests for envelope (re)labeling -- the heart of the recalculation pipeline.

Covers mspy.mod_peakpicking.relabelenvelopes and peaklist.labelenvelopes:
label/intensity modes, envelope metadata, idempotency of re-runs, and the
tail-length floor.
"""

import pytest

import mspy
from mspy import mod_peakpicking as mpp

from .conftest import assert_isotopes_equal, build_envelope_peaklist


def _deisotoped(charge=1, height=1000.0, fwhm=0.05):
    pl = build_envelope_peaklist(charge=charge, height=height, fwhm=fwhm)
    profile = mspy.profile(pl, fwhm=fwhm, points=20)
    pl.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)
    return pl, profile


# ---------------------------------------------------------------------------
# Label modes
# ---------------------------------------------------------------------------


def test_label_1st_collapses_to_monoisotopic_peak():
    pl, profile = _deisotoped()
    mono_mz = min(p.mz for p in pl)
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    assert len(pl) == 1
    assert pl[0].mz == pytest.approx(mono_mz, abs=1e-6)
    assert pl[0].isotope == 0
    assert pl[0].charge == 1


def test_label_isotopes_keeps_all_peaks_indexed():
    pl, profile = _deisotoped()
    n = len(pl)
    pl.labelenvelopes(label="isotopes", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    assert len(pl) == n
    assert [p.isotope for p in pl] == list(range(n))
    assert all(p.charge == 1 for p in pl)


def test_label_centroid_returns_single_charged_peak():
    pl, profile = _deisotoped()
    lo, hi = min(p.mz for p in pl), max(p.mz for p in pl)
    pl.labelenvelopes(label="centroid", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    assert len(pl) == 1
    assert pl[0].charge == 1
    assert lo <= pl[0].mz <= hi  # centroid sits within the cluster


def test_label_monoisotope_returns_single_peak():
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="monoisotope", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    assert len(pl) == 1
    assert pl[0].isotope == 0


# ---------------------------------------------------------------------------
# Intensity modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["maximum", "average", "sum"])
def test_intensity_modes_are_ordered(mode):
    """sum >= maximum >= average for a multi-peak envelope label."""
    results = {}
    for m in ("maximum", "average", "sum"):
        pl, profile = _deisotoped()
        pl.labelenvelopes(label="1st", intensity=m, signal=profile,
                          defaultFwhm=0.05, nonIdeality=0.4)
        results[m] = pl[0].ai

    assert results["sum"] >= results["maximum"] >= results["average"]
    assert results[mode] > 0.0


# ---------------------------------------------------------------------------
# Envelope metadata
# ---------------------------------------------------------------------------


def test_envelope_metadata_shape():
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    env = pl[0].attributes["envelope"]

    assert set(env.keys()) == {"area", "sumint", "fwhm", "shape", "isotopes"}
    assert env["shape"] == "gaussian"
    assert env["area"] > 0.0
    assert env["sumint"] > 0.0
    assert env["fwhm"] > 0.0
    assert len(env["isotopes"]) >= 1
    for mz, weight in env["isotopes"]:
        assert float(weight) >= 0.0
        assert float(mz) > 0.0


def test_envelope_isotope_mzs_are_ordered_and_spaced():
    charge = 2
    pl, profile = _deisotoped(charge=charge)
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    isotopes = pl[0].attributes["envelope"]["isotopes"]

    mzs = [float(mz) for mz, _ in isotopes]
    assert mzs == sorted(mzs)
    if len(mzs) >= 2:
        spacing = mzs[1] - mzs[0]
        assert spacing == pytest.approx(mspy.ISOTOPE_DISTANCE / charge, abs=0.03)


# ---------------------------------------------------------------------------
# Idempotency (key regression area)
# ---------------------------------------------------------------------------


def test_relabel_is_idempotent_on_isotope_positions():
    """Re-running labeling rebuilds the exact same isotope grid (stored-envelope path)."""
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    first = list(pl[0].attributes["envelope"]["isotopes"])

    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    second = list(pl[0].attributes["envelope"]["isotopes"])

    assert_isotopes_equal(first, second)


def test_relabel_idempotent_area_stable():
    """Area stays stable across re-runs against the same profile."""
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    area1 = pl[0].attributes["envelope"]["area"]
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    area2 = pl[0].attributes["envelope"]["area"]
    assert area2 == pytest.approx(area1, rel=1e-6)


def test_reconstruct_cluster_from_envelope_roundtrip():
    """_reconstruct_cluster_from_envelope rebuilds positions from stored metadata."""
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    parent = mspy.peak(mz=1000.0, ai=1000.0, charge=charge, isotope=0, fwhm=0.05)
    envelope = {
        "area": 100.0,
        "sumint": 200.0,
        "fwhm": 0.05,
        "shape": "gaussian",
        "isotopes": [(1000.0, 1.0), (1000.0 + diff, 0.6), (1000.0 + 2 * diff, 0.2)],
    }
    cluster = mpp._reconstruct_cluster_from_envelope(parent, envelope)

    assert [p.isotope for p in cluster] == [0, 1, 2]
    assert all(p.charge == charge for p in cluster)
    assert [round(p.mz, 6) for p in cluster] == [round(mz, 6) for mz, _ in envelope["isotopes"]]


# ---------------------------------------------------------------------------
# Tail length floor
# ---------------------------------------------------------------------------


def test_envelope_respects_min_length_floor():
    """A short detected cluster is extended to at least MIN_ENVELOPE_LENGTH isotopes."""
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    # Only two observed peaks, but the modeled envelope tail must reach the floor.
    peaks = [mspy.peak(mz=1500.0, ai=1000.0, fwhm=0.05),
             mspy.peak(mz=1500.0 + diff, ai=650.0, fwhm=0.05)]
    pl = mspy.peaklist(peaks)
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    pl.deisotope(maxCharge=2, mzTolerance=0.05, intTolerance=0.6)
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    env = pl[0].attributes["envelope"]
    assert len(env["isotopes"]) >= mpp.MIN_ENVELOPE_LENGTH


def test_labelenvelopes_without_profile_still_produces_envelope():
    """No profile -> area falls back to peak-height estimate, no crash."""
    pl, _ = _deisotoped()
    pl.labelenvelopes(label="1st", signal=None, defaultFwhm=0.05, nonIdeality=0.4)
    env = pl[0].attributes["envelope"]
    assert env["area"] > 0.0


def test_relabelenvelopes_requires_peaklist_object():
    with pytest.raises(TypeError):
        mpp.relabelenvelopes([mspy.peak(mz=1000.0, charge=1, isotope=0)])


def test_relabelenvelopes_empty_returns_empty():
    out = mpp.relabelenvelopes(mspy.peaklist([]))
    assert len(out) == 0
