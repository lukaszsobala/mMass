"""Tests for mspy parsers -- one real-file integration plus a small XY round-trip."""

import datetime
import math

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


# ---------------------------------------------------------------------------
# Bruker flex (XMASS)
# ---------------------------------------------------------------------------


def _acqu_constants(fid_path):
    """Read the TOF calibration constants from a fid's sibling acqu file."""

    params = mspy.parser_bruker._readAcqu(fid_path)
    return (
        float(params["ML1"]),
        float(params["ML2"]),
        float(params["ML3"]),
        float(params["DELAY"]),
        float(params["DW"]),
        int(params["TD"]),
    )


def _tof_to_mz(time, ml1, ml2, ml3):
    """Bruker's quadratic TOF -> m/z calibration, as OpenMS applies it."""

    b = math.sqrt(1e12 / ml1)
    c = ml2 - time
    root = (-b + math.sqrt(b * b - 4 * ml3 * c)) / (2 * ml3)
    return root * root


def test_parse_bruker_dataset_folder(sample_bruker):
    parser = mspy.parseBruker(sample_bruker)
    scan_ids = parser.scanlist()
    assert isinstance(scan_ids, dict) and scan_ids  # at least one acquisition

    first_id = next(iter(scan_ids))
    entry = scan_ids[first_id]
    assert entry["msLevel"] == 1
    assert entry["pointsCount"] > 0

    scan = parser.scan(first_id)
    assert scan is not False  # parser returns False on failure
    profile = numpy.asarray(scan.profile, dtype=float)
    assert profile.ndim == 2 and profile.shape[1] == 2
    # every point in the fid is kept: TD from acqu is the point count
    assert len(profile) == entry["pointsCount"]
    assert numpy.all(profile[:, 0] > 0)
    assert numpy.all(numpy.diff(profile[:, 0]) > 0)
    assert numpy.all(profile[:, 1] >= 0)
    # base peak metadata agrees with the profile it was derived from
    assert scan.basePeakIntensity == pytest.approx(profile[:, 1].max())


def test_parse_bruker_fid_directly(sample_bruker):
    """Opening the fid itself gives the same spectrum as opening the folder."""

    fids = mspy.findFIDs(sample_bruker)
    assert fids

    from_folder = mspy.parseBruker(sample_bruker).scan()
    from_fid = mspy.parseBruker(fids[0]).scan()
    assert numpy.array_equal(
        numpy.asarray(from_folder.profile), numpy.asarray(from_fid.profile)
    )
    assert from_folder.title == from_fid.title


def test_parse_bruker_applies_acqu_calibration(sample_bruker):
    """The m/z axis is the acqu calibration applied to the TOF axis.

    This is the whole point of going through pyOpenMS rather than unpacking
    the fid by hand -- the fid holds intensities only, and the TOF-to-m/z
    constants live in acqu.
    """

    fids = mspy.findFIDs(sample_bruker)
    ml1, ml2, ml3, delay, dw, td = _acqu_constants(fids[0])
    assert ml3 != 0  # quadratic term present, so the simple form would be wrong

    profile = numpy.asarray(mspy.parseBruker(fids[0]).scan().profile, dtype=float)
    assert len(profile) == td

    for index in (0, td // 2, td - 1):
        expected = _tof_to_mz(delay + index * dw, ml1, ml2, ml3)
        assert profile[index, 0] == pytest.approx(expected, rel=1e-9)


def test_parse_bruker_ignores_folder_without_data(tmp_path):
    assert mspy.findFIDs(str(tmp_path)) == []


def test_parse_bruker_reads_acquisition_metadata(sample_bruker):
    """Date, polarity and instrument come from acqu, not from the filesystem."""

    parser = mspy.parseBruker(sample_bruker)
    info = parser.info()

    # ##$AQ_DATE (the collection time), not the file's mtime -- ##$DATE is a
    # legacy unix-timestamp field that flex leaves at 0
    fids = mspy.findFIDs(sample_bruker)
    params = mspy.parser_bruker._readAcqu(fids[0])
    assert params["DATE"] == "0"
    expected = datetime.datetime.fromisoformat(params["AQ_DATE"]).ctime()
    assert info["date"] == expected

    # the instrument, not the acquisition PC name in ##$INSTRUM
    assert info["instrument"] == params["SPECTROMETER/DATASYSTEM"]
    assert info["operator"] == params["OWNER"]


def test_parse_bruker_polarity_reads_polari(tmp_path):
    """##$POLARI carries the polarity: 0 is negative, 1 is positive."""

    read = mspy.parser_bruker._polarity
    assert read({"POLARI": "0"}) == -1
    assert read({"POLARI": "1"}) == 1
    assert read({}) is None

    # ##.IONIZATION MODE is deliberately NOT consulted -- flexControl writes
    # 'LD+' there even for negative-mode runs, so trusting it (as OpenMS does)
    # reports every negative spectrum as positive
    assert read({".IONIZATION MODE": "LD+", "POLARI": "0"}) == -1
    assert read({".IONIZATION MODE": "LD+"}) is None


def test_parse_bruker_negative_and_positive_modes(sample_bruker, sample_bruker_positive):
    """A negative-mode and a positive-mode acquisition are told apart.

    Both files claim '##.IONIZATION MODE=  LD+', which is exactly why the
    parser ignores that field.
    """

    negative = mspy.parseBruker(sample_bruker)
    positive = mspy.parseBruker(sample_bruker_positive)

    for parser in (negative, positive):
        fid = mspy.findFIDs(parser.path)[0]
        params = mspy.parser_bruker._readAcqu(fid)
        assert params[".IONIZATION MODE"].endswith("+")  # unhelpfully constant

    assert negative.scan().polarity == -1
    assert next(iter(negative.scanlist().values()))["polarity"] == -1

    assert positive.scan().polarity == 1
    assert next(iter(positive.scanlist().values()))["polarity"] == 1
