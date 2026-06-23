"""Tests for mspy.mod_basics -- m/z, mass error, mass defect, nominal mass."""

import math

import pytest

from mspy import mod_basics


def test_mz_neutral_to_singly_protonated():
    # neutral mass 1000 -> [M+H]+
    assert mod_basics.mz(1000.0, charge=1, currentCharge=0) == pytest.approx(1001.00728, abs=1e-3)


def test_mz_recalculates_from_existing_charge():
    # take a +1 ion back to neutral then to +2
    singly = mod_basics.mz(1000.0, charge=1, currentCharge=0)
    doubly = mod_basics.mz(singly, charge=2, currentCharge=1)
    assert doubly == pytest.approx((1000.0 + 2 * 1.00728) / 2.0, abs=1e-3)


def test_mz_to_zero_charge_returns_neutral():
    singly = mod_basics.mz(1000.0, charge=1, currentCharge=0)
    neutral = mod_basics.mz(singly, charge=0, currentCharge=1)
    assert neutral == pytest.approx(1000.0, abs=1e-3)


def test_mz_electron_agent():
    # electron capture style charging via "e"
    result = mod_basics.mz(1000.0, charge=1, currentCharge=0, agentFormula="e")
    assert result == pytest.approx(1000.0 + mod_basics.ELECTRON_MASS, abs=1e-6)


def test_delta_units():
    assert mod_basics.delta(1000.001, 1000.0, "Da") == pytest.approx(0.001, abs=1e-9)
    assert mod_basics.delta(1000.001, 1000.0, "ppm") == pytest.approx(1.0, abs=1e-3)
    assert mod_basics.delta(1010.0, 1000.0, "%") == pytest.approx(1.0, abs=1e-6)


def test_delta_unknown_units_raises():
    with pytest.raises(ValueError):
        mod_basics.delta(1.0, 1.0, "furlongs")


def test_nominalmass_rounding_modes():
    assert mod_basics.nominalmass(18.6, "floor") == 18
    assert mod_basics.nominalmass(18.2, "ceil") == 19
    assert mod_basics.nominalmass(18.6, "round") == 19


def test_nominalmass_unknown_rounding_raises():
    with pytest.raises(ValueError):
        mod_basics.nominalmass(18.0, "banker")


def test_md_fraction():
    assert mod_basics.md(1000.5, "fraction") == pytest.approx(0.5, abs=1e-9)


def test_md_standard():
    assert mod_basics.md(1000.5, "standard", rounding="floor") == pytest.approx(0.5, abs=1e-9)


def test_md_kendrick_ch2():
    # CH2 Kendrick mass defect is well-defined and finite
    val = mod_basics.md(1000.0, "kendrick", kendrickFormula="CH2")
    assert math.isfinite(val)


def test_md_unknown_type_raises():
    with pytest.raises(ValueError):
        mod_basics.md(1000.0, "nonsense")
