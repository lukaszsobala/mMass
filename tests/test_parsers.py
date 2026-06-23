"""Tests for mspy parsers -- one real-file integration plus a small XY round-trip."""

import numpy
import pytest

import mspy


def test_parse_xy_continuous(tmp_path):
    path = tmp_path / "spectrum.xy"
    path.write_text("# comment\n1000.0 5.0\n1000.1 9.0\n1000.2 3.0\n")
    scan = mspy.parseXY(str(path)).scan(dataType="continuous")
    assert scan is not False  # parser returns False on failure
    profile = numpy.asarray(scan.profile, dtype=float)
    assert profile.shape == (3, 2)
    assert profile[1, 0] == pytest.approx(1000.1)
    assert profile[1, 1] == pytest.approx(9.0)


def test_parse_xy_discrete(tmp_path):
    path = tmp_path / "peaks.xy"
    path.write_text("500.0 100.0\n600.0 50.0\n")
    scan = mspy.parseXY(str(path)).scan(dataType="discrete")
    assert scan is not False  # parser returns False on failure
    assert len(scan.peaklist) == 2
    assert scan.peaklist[0].mz == pytest.approx(500.0)


def test_parse_xy_missing_file_raises():
    with pytest.raises(IOError):
        mspy.parseXY("/no/such/file.xy")


def test_parse_mzml_sample(sample_mzml):
    parser = mspy.parseMZML(sample_mzml)
    parser.load()
    scan_ids = parser.scanlist()
    assert isinstance(scan_ids, dict) and scan_ids  # at least one scan

    first_id = next(iter(scan_ids))
    scan = parser.scan(first_id)
    assert scan is not False  # parser returns False on failure
    profile = numpy.asarray(scan.profile, dtype=float)
    assert profile.ndim == 2 and profile.shape[1] == 2
    assert len(profile) > 0
    # m/z values are sorted and positive
    assert numpy.all(profile[:, 0] > 0)
    assert numpy.all(numpy.diff(profile[:, 0]) >= 0)
