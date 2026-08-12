"""Tests for mspy parsers -- one real-file integration plus a small XY round-trip."""

import datetime
import math
import os.path

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
    assert from_folder is not False and from_fid is not False  # False on failure
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

    scan = mspy.parseBruker(fids[0]).scan()
    assert scan is not False  # parser returns False on failure
    profile = numpy.asarray(scan.profile, dtype=float)
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

    negative_scan = negative.scan()
    positive_scan = positive.scan()
    negative_list = negative.scanlist()
    positive_list = positive.scanlist()
    # parsers return False on failure
    assert negative_scan is not False and positive_scan is not False
    assert negative_list and positive_list

    assert negative_scan.polarity == -1
    assert next(iter(negative_list.values()))["polarity"] == -1

    assert positive_scan.polarity == 1
    assert next(iter(positive_list.values()))["polarity"] == 1


def test_parse_bruker_scanlist_carries_spectrum_type(sample_bruker):
    """Every key the scan picker reads is present.

    dlgSelectScans indexes scanlist entries directly, so a missing key raises
    rather than degrading -- which used to make picking a spot impossible for
    any dataset holding more than one acquisition.
    """

    scanlist = mspy.parseBruker(sample_bruker).scanlist()
    assert scanlist

    required = {
        "title", "scanNumber", "msLevel", "pointsCount", "polarity",
        "retentionTime", "lowMZ", "highMZ", "basePeakIntensity",
        "totIonCurrent", "precursorMZ", "precursorCharge", "spectrumType",
    }
    for entry in scanlist.values():
        assert required.issubset(entry)
        # a fid is the raw TOF trace
        assert entry["spectrumType"] == "continuous"


# ---------------------------------------------------------------------------
# Bruker: several datasets opened at once
# ---------------------------------------------------------------------------


def _write_fake_dataset(root, dataset, spot, owner, date):
    """Build a minimal <dataset>/<spot>/1/1SRef tree with a fid and an acqu.

    Only the metadata path is exercised, so the fid can stay empty -- reading
    the trace itself goes through pyOpenMS and is covered against real data.
    """

    folder = root / dataset / ("0_" + spot) / "1" / "1SRef"
    folder.mkdir(parents=True)
    (folder / "fid").write_bytes(b"")
    (folder / "acqu").write_text(
        "##$SPOTNO= <%s>\n"
        "##$OWNER= <%s>\n"
        "##$AQ_DATE= <%s>\n"
        "##$POLARI= <1>\n"
        "##$TD= <1000>\n"
        "##SPECTROMETER/DATASYSTEM= <Bruker Flex Series>\n" % (spot, owner, date)
    )
    return folder / "fid"


def test_parse_bruker_opens_several_datasets_at_once(tmp_path):
    """A folder holding several datasets opens as one list of acquisitions."""

    _write_fake_dataset(tmp_path, "PlateA", "M9", "alice", "2026-06-25T12:36:20")
    _write_fake_dataset(tmp_path, "PlateB", "M9", "bob", "2026-06-23T14:40:58")

    scanlist = mspy.parseBruker(str(tmp_path)).scanlist()
    assert len(scanlist) == 2

    # the spot alone would be 'M9' for both -- it is a plate position, so it
    # repeats across datasets and cannot identify an acquisition on its own
    titles = sorted(entry["title"] for entry in scanlist.values())
    assert titles == ["PlateA M9", "PlateB M9"]


def test_parse_bruker_metadata_is_per_acquisition(tmp_path):
    """Each acquisition reports its own operator and date, not the first one's."""

    _write_fake_dataset(tmp_path, "PlateA", "M9", "alice", "2026-06-25T12:36:20")
    _write_fake_dataset(tmp_path, "PlateB", "K7", "bob", "2026-06-23T14:40:58")

    parser = mspy.parseBruker(str(tmp_path))
    infos = {scanID: parser.info(scanID) for scanID in parser.scanlist()}
    assert len(infos) == 2

    byOwner = {info["operator"]: info for info in infos.values()}
    assert set(byOwner) == {"alice", "bob"}
    assert byOwner["alice"]["title"] == "PlateA M9"
    assert byOwner["bob"]["title"] == "PlateB K7"
    assert byOwner["alice"]["date"] != byOwner["bob"]["date"]

    # no scan given: the first acquisition, as before
    assert parser.info() == infos[min(infos)]


def test_parse_bruker_single_dataset_names_are_unqualified(tmp_path):
    """Opening one dataset labels its acquisitions by spot alone."""

    _write_fake_dataset(tmp_path, "PlateA", "M9", "alice", "2026-06-25T12:36:20")
    _write_fake_dataset(tmp_path, "PlateA", "K7", "alice", "2026-06-25T13:10:00")

    dataset = str(tmp_path / "PlateA")
    scanlist = mspy.parseBruker(dataset).scanlist()
    assert sorted(entry["title"] for entry in scanlist.values()) == ["K7", "M9"]

    # the document title still names the dataset, plus the spot to tell the
    # two acquisitions apart
    parser = mspy.parseBruker(dataset)
    titles = sorted(parser.info(scanID)["title"] for scanID in parser.scanlist())
    assert titles == ["PlateA K7", "PlateA M9"]


def test_parse_bruker_names_are_the_same_from_anywhere_in_one_dataset(tmp_path):
    """Where inside a dataset it was opened from does not change the labels.

    The folder browser cannot select the fid itself, so a single acquisition
    is opened by picking a folder somewhere above it -- the spot folder, the
    run, or the '1SRef'. All of those are still one dataset.
    """

    _write_fake_dataset(tmp_path, "PlateA", "M9", "alice", "2026-06-25T12:36:20")

    dataset = tmp_path / "PlateA"
    for opened in (
        dataset,
        dataset / "0_M9",
        dataset / "0_M9" / "1",
        dataset / "0_M9" / "1" / "1SRef",
        dataset / "0_M9" / "1" / "1SRef" / "fid",
    ):
        parser = mspy.parseBruker(str(opened))
        assert not parser.spansDatasets()
        titles = [entry["title"] for entry in parser.scanlist().values()]
        assert titles == ["M9"], opened

    # a second dataset alongside it is the case that needs the dataset name,
    # and it is the only one that adds it
    _write_fake_dataset(tmp_path, "PlateB", "M9", "bob", "2026-06-23T14:40:58")
    parent = mspy.parseBruker(str(tmp_path))
    assert parent.spansDatasets()
    assert sorted(entry["title"] for entry in parent.scanlist().values()) == [
        "PlateA M9",
        "PlateB M9",
    ]


def test_bruker_dataset_dir_walks_up_from_a_fid(tmp_path):
    """The dataset folder is recoverable from a fid opened on its own.

    The GUI leans on this to decide where results belong: a fid's own folder
    is the '1SRef' inside the acquisition tree, which is no place to save to.
    """

    fid = _write_fake_dataset(tmp_path, "PlateA", "M9", "alice", "2026-06-25T12:36:20")

    dataset = tmp_path / "PlateA"
    assert mspy.datasetDir(str(fid)) == str(dataset)
    # and so the folder holding the datasets is one further up
    assert os.path.dirname(mspy.datasetDir(str(fid))) == str(tmp_path)


def test_parse_bruker_spot_falls_back_to_the_spot_folder(tmp_path):
    """Without ##$SPOTNO the label is the spot folder, not the shared '1SRef'."""

    folder = tmp_path / "PlateA" / "0_M9" / "1" / "1SRef"
    folder.mkdir(parents=True)
    (folder / "fid").write_bytes(b"")
    (folder / "acqu").write_text("##$TD= <1000>\n")

    scanlist = mspy.parseBruker(str(tmp_path / "PlateA")).scanlist()
    assert [entry["title"] for entry in scanlist.values()] == ["0_M9"]
