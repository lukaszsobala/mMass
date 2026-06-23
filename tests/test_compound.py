"""Tests for mspy.obj_compound.compound -- formula parsing and mass calc."""

import pytest

import mspy

from .conftest import scalar


def test_composition_simple():
    assert mspy.compound("H2O").composition() == {"H": 2, "O": 1}


def test_composition_with_brackets():
    comp = mspy.compound("(CH2)3").composition()
    assert comp == {"C": 3, "H": 6}


def test_water_masses():
    water = mspy.compound("H2O")
    assert water.mass(0) == pytest.approx(18.010565, abs=1e-4)  # monoisotopic
    assert water.mass(1) == pytest.approx(18.0153, abs=1e-3)  # average


def test_glucose_monoisotopic_mass():
    assert mspy.compound("C6H12O6").mass(0) == pytest.approx(180.063388, abs=1e-4)


def test_nominal_mass():
    assert mspy.compound("H2O").nominalmass() == 18


def test_count_atoms():
    c = mspy.compound("C6H12O6")
    assert c.count("C") == 6
    assert c.count("H") == 12
    assert c.count("N") == 0


def test_formula_normalizes_c_and_h_first():
    # formula() lists carbon and hydrogen ahead of other elements
    f = mspy.compound("O6C6H12").formula()
    assert f.startswith("C6H12")


def test_rdbe_benzene():
    # benzene C6H6 has RDBE 4 (ring + 3 double bonds)
    assert mspy.rdbe("C6H6") == pytest.approx(4.0)


def test_mz_singly_protonated():
    glucose = mspy.compound("C6H12O6")
    mono = scalar(glucose.mass(0))
    mz = scalar(glucose.mz(1))
    # [M+H]+ adds one proton mass and divides by 1
    assert mz == pytest.approx(mono + 1.00728, abs=1e-3)


def test_mz_doubly_charged_is_about_half():
    cmpd = mspy.compound("C50H80N14O18")
    mz1 = scalar(cmpd.mz(1))
    mz2 = scalar(cmpd.mz(2))
    assert mz2 == pytest.approx((mz1 + 1.00728) / 2.0, abs=1e-2)


def test_frules_accepts_reasonable_organic():
    assert mspy.frules("C6H12O6") is True


def test_frules_rejects_absurd_hc_ratio():
    # H/C far outside the allowed window
    assert mspy.frules("C1H40") is False


def test_invalid_formula_raises():
    with pytest.raises(ValueError):
        mspy.compound("not a formula 123!!")


def test_mass_buffer_consistent_after_iadd():
    c = mspy.compound("H2O")
    c += "H2O"
    assert c.composition() == {"H": 4, "O": 2}
    assert c.mass(0) == pytest.approx(2 * 18.010565, abs=1e-3)
