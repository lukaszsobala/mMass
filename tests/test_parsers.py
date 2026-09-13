"""Tests for mspy parsers -- one real-file integration plus a small XY round-trip."""

import base64
import datetime
import hashlib
import math
import os.path
import re

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
    """The TOF -> m/z calibration described by the ##$ML* fields alone."""

    b = math.sqrt(1e12 / ml1)
    c = ml2 - time
    root = (-b + math.sqrt(b * b - 4 * ml3 * c)) / (2 * ml3)
    return root * root


def _calstar_references(fid_path):
    """Get flexControl's own reference peaks from ##$CalStar.

    Each <ac> records the raw flight time it was found at (<rv>) and the
    theoretical mass it was assigned (<cm>), so the pair is an independent
    check on the calibration -- it comes from the instrument, not from us.
    """

    params = mspy.parser_bruker._readAcqu(fid_path)
    calstar = params.get("CalStar", "")
    return [
        (float(tof), float(mass))
        for tof, mass in re.findall(
            r"<rv>([^<]+)</rv>.*?<cm>([^<]+)</cm>", calstar, re.DOTALL
        )
    ]


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


def test_parse_bruker_calibration_hits_the_reference_masses(sample_bruker):
    """The calibrated axis reproduces flexControl's own reference masses.

    This is the check that matters: ##$CalStar records the flight time of each
    calibrant and the mass it was assigned, so agreement there means the axis
    is right in absolute terms rather than merely self-consistent.
    """

    fids = mspy.findFIDs(sample_bruker)
    _ml1, _ml2, _ml3, delay, dw, td = _acqu_constants(fids[0])

    references = _calstar_references(fids[0])
    assert len(references) >= 4  # a usable calibration curve, not one anchor

    scan = mspy.parseBruker(fids[0]).scan()
    assert scan is not False  # parser returns False on failure
    masses = numpy.asarray(scan.profile, dtype=float)[:, 0]
    assert len(masses) == td

    # the axis is uniform in flight time, so a reference lands between samples
    times = delay + numpy.arange(td) * dw
    for tof, expected in references:
        found = numpy.interp(tof, times, masses)
        assert abs(found - expected) / expected < 50e-6


def test_parse_bruker_prefers_the_cubic_calibration(sample_bruker):
    """##$NTBCal wins over ##$ML*, which is stale whenever the two disagree.

    Dropping back to the quadratic is not a small error -- it is thousands of
    ppm, and it grows with mass -- so this pins which constants are used.
    """

    fids = mspy.findFIDs(sample_bruker)
    ml1, ml2, ml3, delay, dw, td = _acqu_constants(fids[0])

    constants = mspy.parser_bruker._ctof2Constants(
        mspy.parser_bruker._readAcqu(fids[0])
    )
    assert constants is not None  # this dataset was calibrated 'Cubic Enhanced'
    assert constants[5] != 0  # a genuine cubic term, not a quadratic in disguise

    scan = mspy.parseBruker(fids[0]).scan()
    assert scan is not False  # parser returns False on failure
    masses = numpy.asarray(scan.profile, dtype=float)[:, 0]

    # the quadratic the ##$ML* fields alone describe is far away, and further
    # the heavier the ion gets
    errors = [
        abs(masses[i] - _tof_to_mz(delay + i * dw, ml1, ml2, ml3)) / masses[i]
        for i in (0, td // 2, td - 1)
    ]
    assert min(errors) > 1e-3
    assert errors[0] < errors[-1]


def test_bruker_calibration_falls_back_to_the_quadratic():
    """An acquisition with no ##$NTBCal block is read from ##$ML* as before."""

    params = {
        "ML1": 322877.857415489,
        "ML2": 125.829745293329,
        "ML3": -0.275017182564298,
        "DELAY": 39451,
        "DW": 0.2,
        "TD": 8,
    }
    assert mspy.parser_bruker._ctof2Constants(params) is None

    masses = mspy.parser_bruker._massAxis(params, 8)
    assert masses is not None  # None means the constants could not be read
    for index in range(8):
        expected = _tof_to_mz(
            params["DELAY"] + index * params["DW"],
            params["ML1"],
            params["ML2"],
            params["ML3"],
        )
        assert masses[index] == pytest.approx(expected, rel=1e-12)


def test_bruker_hpc_correction_is_applied_within_its_limits():
    """High Precision Calibration subtracts its polynomial, but only in range.

    No dataset to hand was acquired with HPC on (##$HPClUse= no throughout),
    so the arithmetic is pinned here against a hand-built acqu instead.
    """

    masses = numpy.array([100.0, 500.0, 1000.0, 5000.0])
    params = {
        "HPClUse": "yes",
        "HPClBLo": 400.0,
        "HPClBHi": 2000.0,
        "HPClOrd": 2,
        # coefficients are stored lowest power first: 1 + 0.5m
        "HPCStr": "V1.0VectorDouble 2 1.0 0.5 c2 0 c0 0",
    }

    corrected = mspy.parser_bruker._applyHPC(masses, params)

    # outside [400, 2000] the mass is untouched
    assert corrected[0] == pytest.approx(100.0)
    assert corrected[3] == pytest.approx(5000.0)
    # inside, m -> m - (1 + 0.5m)
    assert corrected[1] == pytest.approx(500.0 - (1.0 + 0.5 * 500.0))
    assert corrected[2] == pytest.approx(1000.0 - (1.0 + 0.5 * 1000.0))

    # and nothing happens at all unless the acquisition asked for it
    params["HPClUse"] = "no"
    assert numpy.array_equal(mspy.parser_bruker._applyHPC(masses, params), masses)


# ---------------------------------------------------------------------------
# Bruker: LIFT (MS/MS)
# ---------------------------------------------------------------------------


def _mzxml_reference(path):
    """Read FlexAnalysis' mzXML export: (fid it came from, precursor, m/z, intensity).

    The fid is found by the SHA-1 the export records for it, since the path
    it records is the acquisition PC's and the dataset may have been moved or
    renamed since. The precursor is None for an MS1 spectrum.

    The export drops zero-intensity samples and stores 32-bit floats, so it
    is compared point by point rather than as a whole array.
    """

    with open(path, encoding="latin-1") as document:
        text = document.read()

    source = re.search(r'<parentFile [^>]*fileSha1="([0-9a-f]+)"', text)
    precursor = re.search(r"<precursorMz[^>]*>([^<]+)</precursorMz>", text)
    peaks = re.search(
        r'<peaks precision="32" byteOrder="network" pairOrder="m/z-int">([^<]*)</peaks>',
        text,
    )
    assert source and peaks, path

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fids = []
    for fid in mspy.findFIDs(os.path.join(root, "spectra")):
        with open(fid, "rb") as document:
            if hashlib.sha1(document.read()).hexdigest() == source.group(1):
                fids.append(fid)
    assert len(fids) == 1, path

    values = numpy.frombuffer(base64.b64decode(peaks.group(1)), dtype=">f4")
    mass = float(precursor.group(1)) if precursor else None

    return fids[0], mass, values[0::2], values[1::2]


def test_parse_bruker_lift_matches_flexanalysis(sample_bruker_exports):
    """A LIFT spectrum gets the m/z axis FlexAnalysis itself gives it.

    Its ##$ML* fields are placeholders, so the old reading put a 1000 Da
    fragment at m/z 59. The bound is the precision of the reference: m/z in
    the export is a 32-bit float, whose step is up to 0.12 ppm here.
    """

    checked = 0
    for export in sample_bruker_exports:
        fid, precursor, expectedMZ, expectedIntensity = _mzxml_reference(export)
        if precursor is None:
            continue  # not a LIFT spectrum
        checked += 1

        parser = mspy.parseBruker(fid)
        scan = parser.scan()
        assert scan is not False, export  # parser returns False on failure
        profile = numpy.asarray(scan.profile, dtype=float)
        masses = profile[:, 0]
        assert numpy.all(numpy.diff(masses) > 0), export

        # pair each exported point with the nearest sample; the intensities
        # agreeing proves the pairing is the right one
        index = numpy.clip(numpy.searchsorted(masses, expectedMZ), 1, len(masses) - 1)
        closer = numpy.abs(masses[index - 1] - expectedMZ) < numpy.abs(
            masses[index] - expectedMZ
        )
        index = numpy.where(closer, index - 1, index)
        assert numpy.array_equal(profile[index, 1], expectedIntensity), export

        errors = numpy.abs(masses[index] - expectedMZ) / expectedMZ
        assert errors.max() < 0.2e-6, export

        # and it is labelled as the MS/MS spectrum it is
        assert scan.msLevel == 2
        assert scan.precursorMZ == pytest.approx(precursor, abs=1e-6)
        scanlist = parser.scanlist()
        assert scanlist  # parsers return False on failure
        entry = scanlist[1]
        assert entry["msLevel"] == 2
        assert entry["precursorMZ"] == pytest.approx(precursor, abs=1e-6)

    if not checked:
        pytest.skip("no LIFT exports among the available mzXML")


def _lift_block(delay, dwell, t0, precursor, coefficients, uLow):
    """Build a V1.0CLift2CalibrationConstants block laid out as flexControl does."""

    def polynomial(values, mass, low, high):
        return "V1.0CCalibPolynomial V1.0VectorDouble %d %s %r %r %r" % (
            len(values),
            " ".join(repr(value) for value in values),
            mass,
            low,
            high,
        )

    identity = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    uHigh = math.sqrt(precursor)
    block = " ".join(
        [
            "V1.0CLift2CalibrationConstants V3.0CTOFCalibrationConstants",
            "%r %r 0 0 0 2 1" % (delay, dwell),
            # one calibrant, deliberately NOT the curve for this precursor
            polynomial([1.0, 900.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1500.0, 8.0, 38.7),
            polynomial(identity, 1500.0, 30.0, 1500.0),
            "V1.0VectorDouble 3 0 1.0 0.0",
            "0 0 %r %r %r" % (t0, t0, precursor),
            polynomial(coefficients, precursor, uLow, uHigh),
            polynomial(identity, precursor, 13.0, precursor),
            "0 0 1 1 1 0",
        ]
    )
    # the field repeats the block, as flexControl writes it
    return "V3.0CCalibrator 10 1 V1.0CHPCData endCHPCData %s %s" % (block, block)


def test_bruker_lift_calibration_inverts_the_precursor_polynomial():
    """Inside its range the polynomial is inverted; outside, its tangent is.

    tof - T0 = P(sqrt(m/z)) for the precursor's own polynomial, time counted
    from the DELAY in the block rather than from ##$DELAY.
    """

    coefficients = [500.0, 1000.0, 10.0, 0.0125]
    delay, dwell, t0, precursor, uLow = 20000.4, 0.4, 15000.0, 900.0, 9.0
    params = {
        "SPType": "2",
        "Parent": str(precursor),
        # placeholders, as in a real LIFT acqu, and an integer DELAY that
        # must not be used
        "DELAY": "20000",
        "DW": "0.40000001",
        "ML1": "20000",
        "ML2": "0",
        "ML3": "0",
        "NTBCal": _lift_block(delay, dwell, t0, precursor, coefficients, uLow),
    }

    lift = mspy.parser_bruker._liftCalibration(params)
    assert lift is not None  # None means the block could not be read
    assert lift[0] == delay and lift[2] == t0

    count = 100000
    masses = mspy.parser_bruker._massAxis(params, count)
    assert masses is not None
    assert numpy.all(numpy.diff(masses) > 0)

    curve = numpy.polynomial.Polynomial(coefficients)
    times = delay + numpy.arange(count) * dwell - t0
    roots = numpy.sqrt(masses)
    inside = (roots >= uLow) & (roots <= math.sqrt(precursor))
    assert 0 < inside.sum() < count  # the spectrum runs past both ends

    assert numpy.allclose(curve(roots[inside]), times[inside], rtol=0, atol=1e-7)

    uHigh = math.sqrt(precursor)
    for end, outside in ((uLow, roots < uLow), (uHigh, roots > uHigh)):
        assert outside.any()
        tangent = curve(end) + curve.deriv()(end) * (roots[outside] - end)
        assert numpy.allclose(tangent, times[outside], rtol=0, atol=1e-7)


def test_bruker_lift_calibration_rejects_a_block_it_cannot_read():
    """A block of another layout is not guessed at."""

    coefficients = [500.0, 1000.0, 10.0, 0.0125]
    block = _lift_block(20000.4, 0.4, 15000.0, 900.0, coefficients, 9.0)
    read = mspy.parser_bruker._liftCalibration

    assert read({"NTBCal": block}) is not None
    # truncated partway through the precursor's polynomial
    assert read({"NTBCal": block[: block.index("0.0125")]}) is None
    # the polynomial after T0 is not for the precursor named beside it
    marker = " V1.0CCalibPolynomial"
    wrongPrecursor = block.replace("900.0" + marker, "950.0" + marker, 1)
    assert read({"NTBCal": wrongPrecursor}) is None
    # no LIFT block at all
    assert read({"NTBCal": "V1.0CTOF2CalibrationConstants 1 2 3"}) is None


def test_parse_bruker_lift_sits_in_the_same_dataset_as_its_spot(tmp_path):
    """LIFT's extra '<precursor>.LIFT' folder does not look like another dataset.

    And the precursor names it, since the MS1 spectrum on the same spot would
    otherwise carry the same label.
    """

    ms1 = _write_fake_dataset(tmp_path, "PlateA", "A1", "alice", "2026-01-01T12:00:00")

    folder = tmp_path / "PlateA" / "0_A1" / "1" / "900.1234.LIFT" / "1SRef"
    folder.mkdir(parents=True)
    (folder / "fid").write_bytes(b"")
    (folder / "acqu").write_text(
        (tmp_path / "PlateA" / "0_A1" / "1" / "1SRef" / "acqu").read_text()
        + "##$SPType= 2\n##$Parent= 900.123456789\n"
    )
    lift = folder / "fid"

    assert mspy.datasetDir(str(lift)) == mspy.datasetDir(str(ms1))
    assert mspy.datasetDir(str(lift)) == str(tmp_path / "PlateA")

    parser = mspy.parseBruker(str(tmp_path / "PlateA"))
    assert not parser.spansDatasets()
    scanlist = parser.scanlist()
    assert scanlist  # parsers return False on failure

    entries = sorted(scanlist.values(), key=lambda entry: entry["msLevel"])
    assert [entry["title"] for entry in entries] == ["A1", "A1 LIFT 900.1235"]
    assert [entry["msLevel"] for entry in entries] == [1, 2]
    assert entries[0]["precursorMZ"] is None
    assert entries[1]["precursorMZ"] == pytest.approx(900.123456789)

    # ##$Parent is a placeholder outside LIFT and is not reported
    assert mspy.parser_bruker._precursorMZ({"SPType": "0", "Parent": "1000"}) is None


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
    # 'LD+' there even for negative-mode runs, so trusting it reports every
    # negative spectrum as positive
    assert read({".IONIZATION MODE": "LD+", "POLARI": "0"}) == -1
    assert read({".IONIZATION MODE": "LD+"}) is None


def test_parse_bruker_negative_and_positive_modes(
    sample_bruker, sample_bruker_positive
):
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
        "title",
        "scanNumber",
        "msLevel",
        "pointsCount",
        "polarity",
        "retentionTime",
        "lowMZ",
        "highMZ",
        "basePeakIntensity",
        "totIonCurrent",
        "precursorMZ",
        "precursorCharge",
        "spectrumType",
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
    the trace and calibrating it is covered against real data above.
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
    assert scanlist  # parsers return False on failure
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
    scanlist = parser.scanlist()
    assert scanlist  # parsers return False on failure
    infos = {scanID: parser.info(scanID) for scanID in scanlist}
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
    assert scanlist  # parsers return False on failure
    assert sorted(entry["title"] for entry in scanlist.values()) == ["K7", "M9"]

    # the document title still names the dataset, plus the spot to tell the
    # two acquisitions apart
    parser = mspy.parseBruker(dataset)
    scanlist = parser.scanlist()
    assert scanlist
    titles = sorted(parser.info(scanID)["title"] for scanID in scanlist)
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
        scanlist = parser.scanlist()
        assert scanlist, opened  # parsers return False on failure
        titles = [entry["title"] for entry in scanlist.values()]
        assert titles == ["M9"], opened

    # a second dataset alongside it is the case that needs the dataset name,
    # and it is the only one that adds it
    _write_fake_dataset(tmp_path, "PlateB", "M9", "bob", "2026-06-23T14:40:58")
    parent = mspy.parseBruker(str(tmp_path))
    assert parent.spansDatasets()
    parentList = parent.scanlist()
    assert parentList
    assert sorted(entry["title"] for entry in parentList.values()) == [
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
    assert scanlist  # parsers return False on failure
    assert [entry["title"] for entry in scanlist.values()] == ["0_M9"]
