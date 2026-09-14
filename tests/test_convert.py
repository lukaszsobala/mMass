"""mmass convert: reading any input and writing it in another format.

Conversion reads and writes through gui.doc, which imports wx (though it needs
no display), so this module skips where wx is unavailable. Image output needs a
display as well and skips without one.
"""

import os
import sys

import numpy
import pytest

import mspy

pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")

from gui import doc  # noqa: E402
from mmass_app import app, cli, convert  # noqa: E402


def _scan(height=100.0, rt=None, peaks=True):
    x = numpy.linspace(400.0, 410.0, 200)
    y = height * numpy.exp(-0.5 * ((x - 405.0) / 0.05) ** 2) + 1.0
    scan = mspy.scan(profile=numpy.column_stack([x, y]))
    scan.msLevel = 1
    scan.polarity = 1
    if rt is not None:
        scan.retentionTime = rt
    if peaks:
        scan.setpeaklist(mspy.peaklist([mspy.peak(mz=405.0, ai=height + 1.0, base=1.0)]))
    return scan


@pytest.fixture
def files(tmp_path):
    """One document of every kind mmass convert can be given."""

    paths = {}

    paths["single"] = str(tmp_path / "single.mzML")
    mspy.writeMZML(_scan(), {"title": "single"}).write(paths["single"])

    run = []
    for index in range(3):
        scan = _scan(height=50.0 + 25 * index, rt=60.0 + 10 * index)
        scan.scanNumber = index + 1
        run.append(scan)
    paths["run"] = str(tmp_path / "run.mzML")
    mspy.writeMZML(run, {"title": "run"}).write(paths["run"])

    paths["mgf"] = str(tmp_path / "spectra.mgf")
    with open(paths["mgf"], "w") as f:
        f.write("BEGIN IONS\nTITLE=a\n150.0 10.0\nEND IONS\n")
        f.write("BEGIN IONS\nTITLE=b\n250.0 20.0\n260.0 5.0\nEND IONS\n")

    paths["session"] = str(tmp_path / "view.mses")
    with open(paths["session"], "w") as f:
        f.write('<?xml version="1.0" encoding="utf-8" ?>\n<mMassSession version="1.0" />\n')

    paths["fasta"] = str(tmp_path / "proteins.fasta")
    with open(paths["fasta"], "w") as f:
        f.write(">p\nPEPTIDE\n")

    return paths


def _read(path, docType):
    document = doc.readDocument(str(path), docType)
    assert document is not None
    return document


def _parsed(value):
    assert value is not False  # parsers return False on failure
    return value


def _convert(*argv):
    options = cli.parse_convert_args(list(argv))
    return convert.run(options), options


# ---------------------------------------------------------------------------
# Impossible conversions are refused before anything is written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind, reason", [("session", "session"), ("fasta", "sequences")])
def test_documents_without_spectra_are_refused(files, tmp_path, capsys, kind, reason):
    status, _ = _convert(files[kind], "-t", "mzml", "-d", str(tmp_path / "out"))

    assert status == 1
    assert reason in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_output_never_replaces_its_input(files, capsys):
    status, _ = _convert(files["single"], "-t", "mzml")

    assert status == 1
    assert "replace the input" in capsys.readouterr().err


def test_existing_output_needs_overwrite(files, tmp_path, capsys):
    target = tmp_path / "exists.msd"
    target.write_text("keep me")

    assert _convert(files["single"], "-o", str(target))[0] == 1
    assert target.read_text() == "keep me"
    assert "--overwrite" in capsys.readouterr().err

    assert _convert(files["single"], "-o", str(target), "--overwrite")[0] == 0
    _read(target, "mSD")


def test_inputs_written_to_the_same_output_are_refused(files, tmp_path, capsys):
    other = tmp_path / "other"
    other.mkdir()
    copy = other / "single.msd"
    status, _ = _convert(files["single"], "-t", "msd", "-d", str(tmp_path / "out"))
    assert status == 0
    copy.write_bytes((tmp_path / "out" / "single.msd").read_bytes())

    status, _ = _convert(files["single"], str(copy), "-t", "txt", "-d", str(tmp_path / "txt"))

    assert status == 1
    assert "same" in capsys.readouterr().err
    assert os.listdir(tmp_path / "txt") == ["single.txt"]


def test_a_run_needs_a_scan_for_single_spectrum_outputs(files, tmp_path, capsys):
    status, _ = _convert(files["run"], "-o", str(tmp_path / "run.txt"))

    assert status == 1
    err = capsys.readouterr().err
    assert "--scan" in err and "1, 2, 3" in err

    assert _convert(files["run"], "-o", str(tmp_path / "run.txt"), "--scan", "2")[0] == 0
    points = numpy.loadtxt(tmp_path / "run.txt")
    assert points.shape == (200, 2)


def test_an_unknown_scan_lists_the_scans(files, tmp_path, capsys):
    status, _ = _convert(files["run"], "-o", str(tmp_path / "run.txt"), "--scan", "9")

    assert status == 1
    assert "no scan 9" in capsys.readouterr().err


def test_text_output_needs_profile_data(files, tmp_path, capsys):
    status, _ = _convert(files["mgf"], "-o", str(tmp_path / "peaks.txt"), "--scan", "0")

    assert status == 1
    assert "no profile data" in capsys.readouterr().err


def test_mgf_output_needs_a_peak_list(tmp_path, capsys):
    source = tmp_path / "profile.mzML"
    mspy.writeMZML(_scan(peaks=False), {}).write(str(source))

    status, _ = _convert(str(source), "-o", str(tmp_path / "profile.mgf"))

    assert status == 1
    assert "no peak list" in capsys.readouterr().err


def test_a_spectrum_collection_is_no_msd_run(files, tmp_path, capsys):
    status, _ = _convert(files["mgf"], "-o", str(tmp_path / "spectra.msd"))

    assert status == 1
    assert "mzML or mzXML" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Data survives conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("extension, docType", [("msd", "mSD"), ("mzXML", "mzXML"), ("xy", "XY")])
def test_a_spectrum_reads_back_unchanged(files, tmp_path, extension, docType):
    target = tmp_path / ("single." + extension)

    assert _convert(files["single"], "-o", str(target))[0] == 0

    original = _read(files["single"], "mzML").spectrum
    converted = _read(target, docType).spectrum
    numpy.testing.assert_allclose(converted.profile, original.profile, rtol=1e-6)
    if docType != "XY":
        assert [p.mz for p in converted.peaklist] == [p.mz for p in original.peaklist]


def test_csv_is_comma_separated(files, tmp_path):
    target = tmp_path / "single.csv"

    assert _convert(files["single"], "-o", str(target))[0] == 0

    assert target.read_text().splitlines()[0].count(",") == 1


def test_an_lcms_run_is_saved_whole_to_msd(files, tmp_path):
    target = tmp_path / "run.msd"

    assert _convert(files["run"], "-o", str(target))[0] == 0

    document = _read(target, "mSD")
    assert document.islcms()
    assert sorted(document.scanlist) == [1, 2, 3]
    assert len(document.scanCache) == 3


def test_an_lcms_msd_is_written_whole_to_mzml_in_scan_order(files, tmp_path):
    saved = tmp_path / "run.msd"
    target = tmp_path / "again.mzML"
    assert _convert(files["run"], "-o", str(saved))[0] == 0

    assert _convert(str(saved), "-o", str(target))[0] == 0

    parser = mspy.parseMZML(str(target))
    scanlist = parser.scanlist()
    assert isinstance(scanlist, dict)
    heights = [_parsed(parser.scan(scanID)).profile[:, 1].max() for scanID in scanlist]
    assert heights == sorted(heights)
    assert len(heights) == 3


def test_every_spectrum_of_an_mgf_goes_to_mzml(files, tmp_path):
    target = tmp_path / "spectra.mzML"

    assert _convert(files["mgf"], "-o", str(target))[0] == 0

    scans = mspy.parseMZML(str(target)).scanlist()
    assert isinstance(scans, dict)
    assert [meta["pointsCount"] for meta in scans.values()] == [1, 2]


def test_mgf_output_reads_back(files, tmp_path):
    target = tmp_path / "single.mgf"

    assert _convert(files["single"], "-o", str(target))[0] == 0

    scan = _parsed(mspy.parseMGF(str(target)).scan())
    assert [peak.mz for peak in scan.peaklist] == pytest.approx([405.0])


def test_outputs_are_named_after_bruker_datasets(tmp_path):
    fid = tmp_path / "dataset" / "0_A1" / "1" / "1SRef" / "fid"
    fid.parent.mkdir(parents=True)
    fid.write_bytes(b"")
    options = cli.ConvertOptions(inputs=[], format="png", outputDir=str(tmp_path / "out"))

    for path in (str(tmp_path / "dataset"), str(tmp_path / "dataset") + os.sep, str(fid)):
        assert convert.output_path(path, options) == str(tmp_path / "out" / "dataset.png")


def test_the_command_dispatches_to_convert(files, tmp_path):
    target = tmp_path / "single.msd"

    assert app.main(["convert", files["single"], "-o", str(target)]) == 0
    assert target.exists()


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

needs_display = pytest.mark.skipif(
    sys.platform.startswith("linux")
    and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="drawing needs a display",
)


@needs_display
@pytest.mark.parametrize("dark", [False, True])
def test_raster_images_have_the_requested_size(files, tmp_path, dark):
    import wx

    target = tmp_path / "single.png"
    argv = [files["single"], "-o", str(target), "--size", "640x360"]

    assert _convert(*argv, *(["--dark"] if dark else []))[0] == 0

    image = wx.Image(str(target))
    assert (image.GetWidth(), image.GetHeight()) == (640, 360)
    corner = (image.GetRed(0, 0), image.GetGreen(0, 0), image.GetBlue(0, 0))
    assert corner == ((30, 30, 30) if dark else (255, 255, 255))


@needs_display
def test_svg_ignores_the_size(files, tmp_path, capsys):
    import xml.dom.minidom

    target = tmp_path / "single.svg"

    assert _convert(files["single"], "-o", str(target), "--size", "640x360")[0] == 0

    assert "--size does not apply" in capsys.readouterr().err
    root = xml.dom.minidom.parse(str(target)).documentElement
    assert root is not None and root.tagName == "svg"
