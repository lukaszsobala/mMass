"""Tests for mspy parsers, each reading data the test writes itself."""

import base64
import datetime
import math
import os.path
import zlib

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


def _mzml_array(values, name, precision=64, compressed=False):
    """One <binaryDataArray>, encoded as mzML stores it (little-endian, base64)."""

    raw = numpy.asarray(values, dtype="<f8" if precision == 64 else "<f4").tobytes()
    if compressed:
        raw = zlib.compress(raw)
    encoded = base64.b64encode(raw).decode("ascii")

    return (
        '<binaryDataArray encodedLength="%d">'
        '<cvParam cvRef="MS" accession="MS:%s" name="%d-bit float"/>'
        '<cvParam cvRef="MS" accession="MS:%s" name="%s"/>'
        '<cvParam cvRef="MS" accession="MS:%s" name="%s"/>'
        "<binary>%s</binary>"
        "</binaryDataArray>"
        % (
            len(encoded),
            "1000523" if precision == 64 else "1000521",
            precision,
            "1000574" if compressed else "1000576",
            "zlib compression" if compressed else "no compression",
            "1000514" if name == "m/z array" else "1000515",
            name,
            encoded,
        )
    )


def test_parse_mzml(tmp_path):
    """A profile MS1 scan and a centroided MS2 scan read back as written.

    The two scans use the two encodings mzML writers pick between -- 64-bit
    zlib-compressed and 32-bit uncompressed -- so both decoders are covered.
    """

    profileMZ = numpy.linspace(500.0, 510.0, 11)
    profileIntensity = numpy.array([0, 1, 3, 9, 20, 35, 20, 9, 3, 1, 0], dtype=float)
    peakMZ = [150.25, 300.5, 450.75]
    peakIntensity = [10.0, 40.0, 25.0]

    path = tmp_path / "run.mzML"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">'
        '<run id="run"><spectrumList count="2">'
        # scan 1: profile MS1, positive
        '<spectrum index="0" id="scan=1" defaultArrayLength="11">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<cvParam cvRef="MS" accession="MS:1000128" name="profile spectrum"/>'
        '<cvParam cvRef="MS" accession="MS:1000130" name="positive scan"/>'
        '<scanList count="1"><scan>'
        '<cvParam cvRef="MS" accession="MS:1000016" name="scan start time"'
        ' value="1.5" unitName="minute"/>'
        "</scan></scanList>"
        '<binaryDataArrayList count="2">'
        + _mzml_array(profileMZ, "m/z array", compressed=True)
        + _mzml_array(profileIntensity, "intensity array", compressed=True)
        + "</binaryDataArrayList></spectrum>"
        # scan 2: centroided MS2 of a precursor picked in scan 1, negative
        + '<spectrum index="1" id="scan=2" defaultArrayLength="3">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum"/>'
        '<cvParam cvRef="MS" accession="MS:1000129" name="negative scan"/>'
        '<precursorList count="1"><precursor spectrumRef="scan=1">'
        '<selectedIonList count="1"><selectedIon>'
        '<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z"'
        ' value="505.0"/>'
        '<cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="2"/>'
        "</selectedIon></selectedIonList></precursor></precursorList>"
        '<binaryDataArrayList count="2">'
        + _mzml_array(peakMZ, "m/z array", precision=32)
        + _mzml_array(peakIntensity, "intensity array", precision=32)
        + "</binaryDataArrayList></spectrum>"
        "</spectrumList></run></mzML>"
    )

    parser = mspy.parseMZML(str(path))
    scanlist = parser.scanlist()
    assert isinstance(scanlist, dict)  # parsers return False on failure
    assert sorted(scanlist) == [1, 2]
    assert scanlist[1]["msLevel"] == 1 and scanlist[2]["msLevel"] == 2
    assert scanlist[2]["precursorMZ"] == pytest.approx(505.0)

    ms1 = parser.scan(1)
    assert ms1 is not False  # parser returns False on failure
    profile = numpy.asarray(ms1.profile, dtype=float)
    assert numpy.array_equal(profile[:, 0], profileMZ)
    assert numpy.array_equal(profile[:, 1], profileIntensity)
    assert ms1.polarity == 1
    assert ms1.retentionTime == pytest.approx(90.0)  # minutes -> seconds

    ms2 = parser.scan(2)
    assert ms2 is not False  # parser returns False on failure
    assert [peak.mz for peak in ms2.peaklist] == pytest.approx(peakMZ)
    assert [peak.ai for peak in ms2.peaklist] == pytest.approx(peakIntensity)
    assert ms2.polarity == -1
    assert ms2.parentScanNumber == 1
    assert ms2.precursorMZ == pytest.approx(505.0)
    assert ms2.precursorCharge == 2


# ---------------------------------------------------------------------------
# Bruker flex (XMASS)
# ---------------------------------------------------------------------------
#
# Every acquisition below is written by the test itself: a fid of int32
# samples beside an acqu laid out as flexControl writes one, with invented
# calibration constants. What a real instrument stores was established
# against FlexAnalysis' own exports (see the CALIBRATION notes in
# parser_bruker.py); these tests pin that reading down.

# An invented 'Cubic Enhanced' calibration, stored the way flexControl stores
# one: the fitted constants in ##$NTBCal, an older quadratic left behind in
# ##$ML*, and ##$DELAY holding the block's DELAY rounded down.
CUBIC = {
    "delay": 30000.6,
    "dwell": 0.5,
    "ml2": 500.0,
    "ml1": 350000.0,
    "ml3": 0.3,
    "cubic": -0.002,
    "offset": -5.0,
}


def _write_acquisition(folder, fields, intensities=(), byteOrder="<"):
    """Write one acquisition: a fid of int32 samples and the acqu beside it.

    fields maps acqu names to values as they appear in the file, e.g.
    {'$TD': '1000', '.IONIZATION MODE': 'LD+'}.
    """

    folder.mkdir(parents=True)
    samples = numpy.asarray(intensities, dtype=byteOrder + "i4")
    (folder / "fid").write_bytes(samples.tobytes())

    lines = ["##TITLE=  XMASS Parameter file", "##JCAMPDX=  5.0"]
    lines += ["##%s= %s " % (name, value) for name, value in fields.items()]
    lines.append("##END=")
    (folder / "acqu").write_text("\n".join(lines) + "\n")

    return folder / "fid"


def _cubic_fields(count, **extra):
    """acqu fields for an MS1 acquisition carrying the CUBIC calibration."""

    block = "V1.0CTOF2CalibrationConstants %r %r %r %r %r %r %r 2" % (
        CUBIC["delay"],
        CUBIC["dwell"],
        CUBIC["ml2"],
        CUBIC["ml1"],
        CUBIC["ml3"],
        CUBIC["cubic"],
        CUBIC["offset"],
    )
    fields = {
        "SPECTROMETER/DATASYSTEM": " Bruker Flex Series",
        ".IONIZATION MODE": " LD+",
        "$BYTORDA": "0",
        "$DATE": "0",
        "$DELAY": "30000",
        "$DW": "0.5",
        "$HPClUse": "no",
        "$INSTRUM": "<FLEX-PC>",
        "$ML1": "340000.0",
        "$ML2": "520.0",
        "$ML3": "0.25",
        "$OWNER": "<alice>",
        "$POLARI": "1",
        "$SPType": "0",
        "$SPOTNO": "<A1>",
        "$TD": str(count),
        "$AQ_DATE": "<2026-01-01T12:00:00.000+01:00>",
        "$NTBCal": "<V3.0CCalibrator 12 1 V1.0CHPCData endCHPCData %s %s>"
        % (block, block),
    }
    fields.update(extra)
    return fields


def _cubic_time(mass):
    """Flight time of an m/z under the CUBIC calibration -- the forward model."""

    u = numpy.sqrt(numpy.asarray(mass) + CUBIC["offset"])
    scale = math.sqrt(1e12 / CUBIC["ml1"])
    return CUBIC["ml2"] + scale * u + CUBIC["ml3"] * u**2 + CUBIC["cubic"] * u**3


def _peak_trace(count):
    """A peak on a small baseline, so every sample has a distinct role."""

    index = numpy.arange(count)
    return (20 + 5000 * numpy.exp(-(((index - count / 3) / 15.0) ** 2))).astype(int)


def _tof_to_mz(time, ml1, ml2, ml3):
    """The TOF -> m/z calibration described by the ##$ML* fields alone."""

    b = math.sqrt(1e12 / ml1)
    c = ml2 - time
    root = (-b + math.sqrt(b * b - 4 * ml3 * c)) / (2 * ml3)
    return root * root


def test_parse_bruker_dataset_folder(tmp_path):
    """A dataset folder opens as its acquisition, every fid sample kept."""

    count = 4000
    trace = _peak_trace(count)
    _write_acquisition(
        tmp_path / "PlateA" / "0_A1" / "1" / "1SRef", _cubic_fields(count), trace
    )

    parser = mspy.parseBruker(str(tmp_path / "PlateA"))
    scanlist = parser.scanlist()
    assert scanlist  # parsers return False on failure
    entry = scanlist[1]
    assert entry["msLevel"] == 1
    assert entry["pointsCount"] == count

    scan = parser.scan(1)
    assert scan is not False  # parser returns False on failure
    profile = numpy.asarray(scan.profile, dtype=float)
    assert profile.shape == (count, 2)
    assert numpy.array_equal(profile[:, 1], trace)
    assert numpy.all(profile[:, 0] > 0)
    assert numpy.all(numpy.diff(profile[:, 0]) > 0)
    # base peak metadata agrees with the profile it was derived from
    assert scan.basePeakIntensity == trace.max()
    assert scan.basePeakMZ == profile[trace.argmax(), 0]


def test_parse_bruker_fid_directly(tmp_path):
    """Opening the fid itself gives the same spectrum as opening the folder."""

    count = 500
    dataset = tmp_path / "PlateA"
    fid = _write_acquisition(
        dataset / "0_A1" / "1" / "1SRef", _cubic_fields(count), _peak_trace(count)
    )

    from_folder = mspy.parseBruker(str(dataset)).scan()
    from_fid = mspy.parseBruker(str(fid)).scan()
    assert from_folder is not False and from_fid is not False  # False on failure
    assert numpy.array_equal(
        numpy.asarray(from_folder.profile), numpy.asarray(from_fid.profile)
    )
    assert from_folder.title == from_fid.title


def test_parse_bruker_reads_big_endian_fids(tmp_path):
    """##$BYTORDA= 1 means the fid's samples are big-endian."""

    count = 300
    trace = _peak_trace(count)
    fid = _write_acquisition(
        tmp_path / "PlateA" / "0_A1" / "1" / "1SRef",
        _cubic_fields(count, **{"$BYTORDA": "1"}),
        trace,
        byteOrder=">",
    )

    scan = mspy.parseBruker(str(fid)).scan()
    assert scan is not False  # parser returns False on failure
    assert numpy.array_equal(numpy.asarray(scan.profile)[:, 1], trace)


def test_parse_bruker_applies_the_cubic_calibration(tmp_path):
    """Each sample's m/z is the cubic's root at that sample's flight time.

    Two ways of getting this wrong are pinned here. The ##$ML* fields hold a
    stale quadratic, and reading them instead is thousands of ppm out. And the
    flight time of sample i is DELAY + i*DW with the DELAY from the ##$NTBCal
    block: the rounded ##$DELAY puts the whole axis tens of ppm out.
    """

    count = 4000
    fid = _write_acquisition(
        tmp_path / "PlateA" / "0_A1" / "1" / "1SRef",
        _cubic_fields(count),
        _peak_trace(count),
    )

    scan = mspy.parseBruker(str(fid)).scan()
    assert scan is not False  # parser returns False on failure
    masses = numpy.asarray(scan.profile, dtype=float)[:, 0]

    times = CUBIC["delay"] + numpy.arange(count) * CUBIC["dwell"]
    assert numpy.allclose(_cubic_time(masses), times, rtol=0, atol=1e-6)

    # (so ##$DELAY, 0.6 ns earlier, fails the check above by a wide margin)
    # and the quadratic in ##$ML* is far away
    errors = [
        abs(masses[i] - _tof_to_mz(times[i], 340000.0, 520.0, 0.25)) / masses[i]
        for i in (0, count // 2, count - 1)
    ]
    assert min(errors) > 1e-3


def test_bruker_calibration_falls_back_to_the_quadratic():
    """An acquisition with no ##$NTBCal block is read from ##$ML* as before."""

    params = {
        "ML1": 330000.0,
        "ML2": 120.0,
        "ML3": -0.3,
        "DELAY": 40000,
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


def test_parse_bruker_lift_inverts_the_precursor_polynomial(tmp_path):
    """Inside its range the polynomial is inverted; outside, its tangent is.

    tof - T0 = P(sqrt(m/z)) for the precursor's own polynomial, time counted
    from the DELAY in the block rather than from ##$DELAY. The ##$ML* fields
    of a LIFT acquisition are placeholders and must not be used.
    """

    coefficients = [500.0, 1000.0, 10.0, 0.0125]
    delay, dwell, t0, precursor, uLow = 20000.4, 0.4, 15000.0, 900.0, 9.0
    count = 100000
    fid = _write_acquisition(
        tmp_path / "PlateA" / "0_A1" / "1" / "900.0000.LIFT" / "1SRef",
        {
            "$BYTORDA": "0",
            "$DELAY": "20000",
            "$DW": "0.40000001",
            "$HPClOrd": "0",
            "$HPClUse": "yes",
            "$ML1": "20000",
            "$ML2": "0",
            "$ML3": "0",
            "$POLARI": "1",
            "$Parent": repr(precursor),
            "$SPOTNO": "<A1>",
            "$SPType": "2",
            "$TD": str(count),
            "$NTBCal": "<%s>"
            % _lift_block(delay, dwell, t0, precursor, coefficients, uLow),
        },
        _peak_trace(count),
    )

    scan = mspy.parseBruker(str(fid)).scan()
    assert scan is not False  # parser returns False on failure
    assert scan.msLevel == 2
    assert scan.precursorMZ == pytest.approx(precursor)
    masses = numpy.asarray(scan.profile, dtype=float)[:, 0]
    assert numpy.all(numpy.diff(masses) > 0)

    curve = numpy.polynomial.Polynomial(coefficients)
    times = delay + numpy.arange(count) * dwell - t0
    roots = numpy.sqrt(masses)
    uHigh = math.sqrt(precursor)
    inside = (roots >= uLow) & (roots <= uHigh)
    assert 0 < inside.sum() < count  # the spectrum runs past both ends

    assert numpy.allclose(curve(roots[inside]), times[inside], rtol=0, atol=1e-7)

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


def test_parse_bruker_reads_acquisition_metadata(tmp_path):
    """Date, operator and instrument come from acqu, not from the filesystem."""

    fid = _write_acquisition(
        tmp_path / "PlateA" / "0_A1" / "1" / "1SRef", _cubic_fields(10), [0] * 10
    )

    info = mspy.parseBruker(str(fid)).info()
    assert (
        info["date"]
        == datetime.datetime.fromisoformat("2026-01-01T12:00:00.000+01:00").ctime()
    )
    assert info["operator"] == "alice"
    # the instrument, not the acquisition PC name in ##$INSTRUM
    assert info["instrument"] == "Bruker Flex Series"


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


def test_parse_bruker_negative_and_positive_modes(tmp_path):
    """A negative-mode and a positive-mode acquisition are told apart.

    Both say '##.IONIZATION MODE=  LD+', as flexControl writes it whatever
    the polarity, which is exactly why the parser ignores that field.
    """

    for polari, expected in (("0", -1), ("1", 1)):
        fid = _write_acquisition(
            tmp_path / ("Plate" + polari) / "0_A1" / "1" / "1SRef",
            _cubic_fields(10, **{"$POLARI": polari}),
            [0] * 10,
        )
        parser = mspy.parseBruker(str(fid))
        scan = parser.scan()
        scanlist = parser.scanlist()
        assert scan is not False and scanlist  # parsers return False on failure
        assert scan.polarity == expected
        assert scanlist[1]["polarity"] == expected


def test_parse_bruker_scanlist_carries_spectrum_type(tmp_path):
    """Every key the scan picker reads is present.

    dlgSelectScans indexes scanlist entries directly, so a missing key raises
    rather than degrading -- which used to make picking a spot impossible for
    any dataset holding more than one acquisition.
    """

    for spot in ("A1", "A2"):
        _write_acquisition(
            tmp_path / "PlateA" / ("0_" + spot) / "1" / "1SRef",
            _cubic_fields(10, **{"$SPOTNO": "<%s>" % spot}),
            [0] * 10,
        )

    scanlist = mspy.parseBruker(str(tmp_path / "PlateA")).scanlist()
    assert scanlist and len(scanlist) == 2  # parsers return False on failure

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
    the trace and calibrating it is covered above.
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
