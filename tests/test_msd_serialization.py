"""Round-trip tests for mSD document serialization (gui.doc).

These need the GUI stack (gui.doc imports wx/config), so they skip cleanly where
that is unavailable -- the rest of the suite stays headless.
"""

import os
import tempfile

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
