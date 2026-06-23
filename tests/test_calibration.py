"""Tests for mspy.mod_calibration -- recovering known calibration constants."""

import pytest

import mspy


def test_linear_single_point_is_pure_shift():
    fn, params, chi = mspy.calibration([(100.0, 101.0)], model="linear")
    assert fn(params, 100.0) == pytest.approx(101.0, abs=1e-9)


def test_linear_recovers_known_slope_and_shift():
    # reference = 2 * measured + 3
    data = [(x, 2.0 * x + 3.0) for x in (10.0, 20.0, 30.0, 40.0, 50.0)]
    fn, params, chi = mspy.calibration(data, model="linear")
    a, b = list(params)
    assert a == pytest.approx(2.0, rel=1e-3)
    assert b == pytest.approx(3.0, abs=1e-2)
    assert chi == pytest.approx(0.0, abs=1e-6)


def test_linear_predicts_held_out_point():
    data = [(x, 2.0 * x + 3.0) for x in (10.0, 20.0, 30.0, 40.0)]
    fn, params, _ = mspy.calibration(data, model="linear")
    assert fn(params, 100.0) == pytest.approx(203.0, rel=1e-3)


def test_quadratic_recovers_curve():
    # reference = 0.5 x^2 - x + 2
    data = [(x, 0.5 * x * x - x + 2.0) for x in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)]
    fn, params, chi = mspy.calibration(data, model="quadratic")
    a, b, c = list(params)
    assert a == pytest.approx(0.5, rel=1e-2)
    assert b == pytest.approx(-1.0, abs=5e-2)
    assert c == pytest.approx(2.0, abs=1e-1)
