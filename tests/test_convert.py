"""mmass convert: reading any input and writing it in another format.

Conversion reads and writes through gui.doc, which imports wx (though it needs
no display), so this module skips where wx is unavailable. Image output needs a
display as well and skips without one.
"""

import json
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


def _process(*argv):
    options = cli.parse_convert_args(list(argv), command=cli.PROCESS_COMMAND)
    return convert.run(options)


# ---------------------------------------------------------------------------
# Impossible conversions are refused before anything is written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind, reason", [("session", "session"), ("fasta", "sequences")])
def test_documents_without_spectra_are_refused(files, tmp_path, capsys, kind, reason):
    status, _ = _convert(files[kind], "-f", "mzml", "-d", str(tmp_path / "out"))

    assert status == 1
    assert reason in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_output_never_replaces_its_input(files, capsys):
    status, _ = _convert(files["single"], "-f", "mzml")

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
    status, _ = _convert(files["single"], "-f", "msd", "-d", str(tmp_path / "out"))
    assert status == 0
    copy.write_bytes((tmp_path / "out" / "single.msd").read_bytes())

    status, _ = _convert(files["single"], str(copy), "-f", "txt", "-d", str(tmp_path / "txt"))

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


def test_peak_list_columns_match_the_gui():
    assert tuple(doc.PEAKLIST_COLUMNS) == tuple(cli.PEAKLIST_COLUMNS)


def test_math_operations_match_the_gui():
    from gui import processing

    assert processing.SINGLE_SPECTRUM_MATH == cli.MATH_OPERATIONS


def test_a_peak_list_is_written_as_text_with_a_header(files, tmp_path):
    target = tmp_path / "peaks.csv"

    assert _convert(files["single"], "-o", str(target), "--peak-list", "--columns", "mz,int,z")[0] == 0

    assert target.read_text().splitlines() == ["m/z,int,z", "405.0,100.0,"]


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


def _pattern(height=1000.0, rt=None, noise=2.0):
    """A noisy profile of a singly charged isotope pattern at m/z 405."""

    x = numpy.linspace(400.0, 410.0, 4000)
    y = numpy.random.RandomState(int(height)).uniform(0.0, noise, len(x))
    for isotope, share in enumerate((1.0, 0.22, 0.03)):
        centre = 405.0 + isotope * 1.00335
        y += height * share * numpy.exp(-0.5 * ((x - centre) / 0.02) ** 2)
    scan = mspy.scan(profile=numpy.column_stack([x, y]))
    scan.msLevel = 1
    scan.polarity = 1
    if rt is not None:
        scan.retentionTime = rt
    return scan


@pytest.fixture
def profiles(tmp_path):
    """A noisy profile spectrum without peaks, as msd and as text, and a run."""

    paths = {}
    document = doc.document()
    document.title = "profile"
    document.spectrum = _pattern()
    paths["msd"] = tmp_path / "profile.msd"
    paths["msd"].write_text(document.msd())

    paths["txt"] = tmp_path / "profile.txt"
    paths["txt"].write_text("".join("%f,%f\n" % tuple(point) for point in document.spectrum.profile))

    run = []
    for index in range(4):
        scan = _pattern(height=800.0 + 200 * index, rt=60.0 + 10 * index)
        scan.scanNumber = index + 1
        run.append(scan)
    paths["run"] = tmp_path / "run.mzML"
    mspy.writeMZML(run, {"title": "run"}).write(str(paths["run"]))
    return paths


def _settings(*argv):
    options = cli.parse_convert_args(
        ["--show-settings", *argv], command=cli.PROCESS_COMMAND
    )
    return convert.processing_settings(options)


def test_steps_give_what_the_processing_panel_gives(profiles, tmp_path):
    from gui import processing

    target = tmp_path / "out.msd"

    assert _process(str(profiles["msd"]), "--baseline", "--smooth", "--find-peaks", "-o", str(target)) == 0

    expected = _read(profiles["msd"], "mSD").spectrum
    settings = _settings()
    processing.subtractBaseline(expected, settings)
    processing.smoothScan(expected, settings)
    processing.pickPeaks(expected, settings)
    processed = _read(target, "mSD").spectrum
    assert len(processed.peaklist) == len(expected.peaklist) > 0
    assert [p.mz for p in processed.peaklist] == pytest.approx([p.mz for p in expected.peaklist])
    numpy.testing.assert_allclose(processed.profile, expected.profile, rtol=1e-6)


def test_steps_run_in_the_order_given(profiles, tmp_path):
    cropped_first = tmp_path / "cropped_first.msd"
    picked_first = tmp_path / "picked_first.msd"

    assert _process(str(profiles["msd"]), "--crop", "400:404", "--find-peaks", "-o", str(cropped_first)) == 0
    assert _process(str(profiles["msd"]), "--find-peaks", "--crop", "404:406", "-o", str(picked_first)) == 0

    assert not _read(cropped_first, "mSD").spectrum.haspeaks()
    picked = _read(picked_first, "mSD").spectrum
    assert [round(p.mz) for p in picked.peaklist] == [405]
    # cropping keeps the points next to either end
    assert 403.9 < picked.profile[:, 0].min() and picked.profile[:, 0].max() < 406.1


def test_settings_change_the_result_but_never_the_configuration(profiles, tmp_path):
    from gui import config

    before = json.dumps(config.processing, sort_keys=True)
    strict = tmp_path / "strict.msd"

    assert _process(str(profiles["msd"]), "--find-peaks", "-o", str(strict), "--set", "peakpicking.snThreshold=100000") == 0

    assert not _read(strict, "mSD").spectrum.haspeaks()
    assert json.dumps(config.processing, sort_keys=True) == before
    assert _settings("--preset", "Default")["baseline"] == config.processing_defaults["baseline"]


@pytest.mark.parametrize(
    "setting, message",
    [
        ("peakpicking.bogus=1", "has no setting bogus"),
        ("crop.lowMass=1", "settings sections"),
        ("smoothing.method=median", "choose from"),
        ("baseline.precision=-3", "out of range"),
        ("math.multiplier=0", "out of range"),
        ("baseline.offset=high", "not a number"),
        ("bogus=1", "there is no setting bogus"),
        ("preservePeaks=1", "write baseline.preservePeaks or smoothing.preservePeaks"),
    ],
)
def test_wrong_settings_stop_before_any_file(profiles, tmp_path, capsys, setting, message):
    target = tmp_path / "out.msd"

    assert _process(str(profiles["msd"]), "--baseline", "-o", str(target), "--set", setting) == 2

    assert message in capsys.readouterr().err
    assert not target.exists()


def test_settings_are_found_by_name_in_any_case():
    settings = _settings(
        "--set", "SNTHRESHOLD=7", "--set", "Smoothing.Method=ga", "--set", "baseline.preservepeaks=0",
        "--preset", "default",
    )

    assert settings["peakpicking"]["snThreshold"] == 7
    assert settings["smoothing"]["method"] == "GA"
    assert settings["baseline"]["preservePeaks"] == 0


def test_setting_errors_say_where_the_setting_was_given(profiles, tmp_path, capsys):
    recipe = tmp_path / "steps.recipe"
    recipe.write_text("find-peaks\nset snThreshold=lots\n")

    status = _process(str(profiles["msd"]), "--recipe", str(recipe), "-o", str(tmp_path / "out.msd"))

    assert status == 2
    assert f"recipe {recipe}, line 2: set snThreshold: 'lots' is not a number" in capsys.readouterr().err


def test_show_settings(capsys):
    options = cli.parse_convert_args(
        ["--show-settings", "--set", "deisotoping.maxCharge=3", "--set", "baseline.preservePeaks=no",
         "--set", "math.multiplier=2.5"],
        command=cli.PROCESS_COMMAND,
    )

    assert convert.run(options) == 0

    shown = json.loads(capsys.readouterr().out)
    assert set(shown) == set(cli.SETTINGS_SECTIONS)
    assert shown["deisotoping"]["maxCharge"] == 3
    assert shown["baseline"]["preservePeaks"] == 0
    assert shown["math"] == {"multiplier": 2.5}


def test_steps_start_from_the_users_settings(monkeypatch):
    from gui import config

    # the user's settings, as loaded from their config.json; setitem on the
    # plain dict inside, so nothing is saved
    changed = json.loads(json.dumps(config.processing))
    changed["peakpicking"]["snThreshold"] = 7.5
    changed["math"]["multiplier"] = 3
    monkeypatch.setattr(config, "processing", changed)

    settings = _settings()
    default = _settings("--preset", "Default")

    assert settings["peakpicking"]["snThreshold"] == 7.5
    assert settings["math"]["multiplier"] == 3
    assert default["peakpicking"]["snThreshold"] == config.processing_defaults["peakpicking"]["snThreshold"]


def test_math_transforms_profile_and_peaks(profiles, tmp_path):
    source = _read(profiles["msd"], "mSD").spectrum
    targets = {}
    for operation in ("normalize", "multiply", "squareroot"):
        targets[operation] = tmp_path / f"{operation}.msd"
        argv = [str(profiles["msd"]), "--find-peaks", "--math", operation, "-o", str(targets[operation])]
        assert _process(*argv, "--set", "math.multiplier=2.5") == 0

    top = source.profile[:, 1].max()
    normalized = _read(targets["normalize"], "mSD").spectrum
    multiplied = _read(targets["multiply"], "mSD").spectrum
    rooted = _read(targets["squareroot"], "mSD").spectrum
    assert normalized.profile[:, 1].max() == pytest.approx(100.0, rel=1e-5)
    assert multiplied.profile[:, 1].max() == pytest.approx(2.5 * top, rel=1e-5)
    assert rooted.profile[:, 1].max() == pytest.approx(numpy.sqrt(top), rel=1e-5)
    assert all(spectrum.haspeaks() for spectrum in (normalized, multiplied, rooted))
    assert max(p.ai for p in normalized.peaklist) == pytest.approx(100.0, rel=1e-5)


@pytest.mark.parametrize(
    "setting, message",
    [("math.operation=subtract", "give the operation to --math"), ("math.preservePeaks=1", "no step uses")],
)
def test_math_settings_no_step_uses_are_refused(setting, message):
    with pytest.raises(convert.ConversionError, match=message):
        _settings("--set", setting)


def test_steps_lacking_their_data_are_errors(files, profiles, tmp_path, capsys):
    assert _process(str(profiles["msd"]), "--deisotope", "-o", str(tmp_path / "a.msd")) == 1
    assert "find them first with --find-peaks" in capsys.readouterr().err

    assert _process(files["mgf"], "--scan", "0", "--baseline", "-o", str(tmp_path / "b.msd")) == 1
    assert "only a peak list" in capsys.readouterr().err

    assert _process(str(profiles["msd"]), "--crop", "500:600", "-o", str(tmp_path / "c.msd")) == 1
    assert "no data is left" in capsys.readouterr().err


def test_every_scan_of_a_run_written_whole_is_processed(profiles, tmp_path):
    for pooling in ("run", "off"):
        target = tmp_path / f"{pooling}.msd"
        argv = ["--find-peaks", "-o", str(target), "--set", f"peakpicking.poolScans={pooling}"]

        assert _process(str(profiles["run"]), *argv) == 0

        document = _read(target, "mSD")
        assert len(document.scanCache) == 4
        assert all(scan.haspeaks() for scan in document.scanCache.values())


def test_one_scan_is_picked_like_the_scan_of_the_whole_run(profiles, tmp_path):
    # pooled peak picking pools the whole run, even for one scan of it
    whole = tmp_path / "whole.msd"
    one = tmp_path / "one.csv"

    assert _process(str(profiles["run"]), "--find-peaks", "-o", str(whole)) == 0
    assert _process(str(profiles["run"]), "--find-peaks", "--scan", "3", "-o", str(one), "--peak-list", "--columns", "mz,int") == 0

    scan = _read(whole, "mSD").scanCache[3]
    lines = one.read_text().splitlines()
    assert lines[0] == "m/z,int"
    picked = numpy.array([[float(value) for value in line.split(",")] for line in lines[1:]])
    assert len(picked) == len(scan.peaklist) > 0
    numpy.testing.assert_allclose(picked, [[p.mz, p.intensity] for p in scan.peaklist], rtol=1e-6)


def test_in_place_rewrites_the_input(profiles):
    path = profiles["msd"]
    os.chmod(path, 0o640)

    assert _process(str(path), "--find-peaks", "--in-place") == 0

    assert _read(path, "mSD").spectrum.haspeaks()
    assert os.stat(path).st_mode & 0o777 == 0o640
    assert os.listdir(path.parent).count(path.name) == 1
    assert not [name for name in os.listdir(path.parent) if name.startswith(".")]


def test_in_place_text_keeps_its_separator(profiles):
    path = profiles["txt"]
    before = numpy.loadtxt(path, delimiter=",")

    assert _process(str(path), "--math", "normalize", "--in-place") == 0

    after = numpy.loadtxt(path, delimiter=",")
    assert after[:, 1].max() == pytest.approx(100.0)
    numpy.testing.assert_allclose(after[:, 0], before[:, 0])


def test_a_failed_step_leaves_the_input_untouched(profiles, capsys):
    path = profiles["msd"]
    original = path.read_bytes()

    assert _process(str(path), "--baseline", "--deisotope", "--in-place") == 1

    assert "--deisotope needs peaks" in capsys.readouterr().err
    assert path.read_bytes() == original
    assert sorted(os.listdir(path.parent)) == ["profile.msd", "profile.txt", "run.mzML"]


@pytest.mark.parametrize(
    "kind, message",
    [("run", "dropping everything else"), ("mgf", "writes mgf files of one")],
)
def test_in_place_refuses_files_it_would_damage(files, profiles, capsys, kind, message):
    path = str(profiles["run"] if kind == "run" else files["mgf"])
    original = open(path, "rb").read()

    assert _process(path, "--math", "normalize", "--in-place") == 1

    assert message in capsys.readouterr().err
    assert open(path, "rb").read() == original


def test_one_failing_input_does_not_stop_the_others(files, profiles, tmp_path, capsys):
    out = tmp_path / "out"

    status = _process(files["fasta"], str(profiles["msd"]), str(profiles["txt"]), "--find-peaks", "-f", "msd", "-d", str(out))

    assert status == 1
    assert sorted(os.listdir(out)) == ["profile.msd"]
    captured = capsys.readouterr()
    assert "sequences, not spectra" in captured.err
    assert "same" in captured.err
    assert captured.out.count(" -> ") == 1


def test_a_dry_run_writes_nothing(profiles, tmp_path, capsys):
    out = tmp_path / "out"
    original = profiles["msd"].read_bytes()

    assert _process(str(profiles["msd"]), "--find-peaks", "-f", "msd", "-d", str(out), "--dry-run") == 0
    assert _process(str(profiles["msd"]), "--find-peaks", "--in-place", "--dry-run") == 0

    assert not out.exists()
    assert profiles["msd"].read_bytes() == original
    assert capsys.readouterr().out.count("dry run, nothing written") == 2
    assert sorted(os.listdir(tmp_path)) == ["profile.msd", "profile.txt", "run.mzML"]


def test_a_dry_run_still_finds_what_would_fail(profiles, tmp_path, capsys):
    assert _process(str(profiles["msd"]), "--deisotope", "-o", str(tmp_path / "a.msd"), "--dry-run") == 1

    assert "--deisotope needs peaks" in capsys.readouterr().err


def test_standard_output_gets_the_output_alone(profiles, capfdbinary):
    status = _process(str(profiles["msd"]), "--find-peaks", "-o", "-", "-f", "csv", "--peak-list", "--columns", "mz,z")

    assert status == 0
    captured = capfdbinary.readouterr()
    lines = captured.out.decode().splitlines()
    assert lines[0] == "m/z,z" and len(lines) > 1
    assert captured.err == b""


def test_messages_show_paths_relative_to_the_current_folder(profiles, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profile.png").write_text("")

    assert _convert("profile.msd", "-f", "msd", "-d", "out")[0] == 0
    assert _convert("profile.msd", "-f", "png")[0] == 1

    captured = capsys.readouterr()
    assert captured.out == f"profile.msd -> {os.path.join('out', 'profile.msd')}\n"
    assert "error: profile.msd: profile.png already exists" in captured.err


def test_a_recipe_processes_like_its_options(profiles, tmp_path):
    recipe = tmp_path / "peaks.recipe"
    recipe.write_text(
        "# peaks of the pattern as a peak list\n"
        "set snThreshold=10\n"
        "baseline\n"
        "find-peaks\n"
        "peak-list\n"
        "columns mz,int,z\n"
    )
    by_recipe = tmp_path / "recipe.csv"
    by_options = tmp_path / "options.csv"

    assert _process(str(profiles["msd"]), "--recipe", str(recipe), "-o", str(by_recipe)) == 0
    assert _process(
        str(profiles["msd"]), "--set", "snThreshold=10", "--baseline", "--find-peaks",
        "--peak-list", "--columns", "mz,int,z", "-o", str(by_options),
    ) == 0

    assert by_recipe.read_text() == by_options.read_text()
    assert by_recipe.read_text().startswith("m/z,int,z\n405.")


def test_the_command_dispatches_to_process(profiles, tmp_path):
    target = tmp_path / "out.msd"

    assert app.main(["process", str(profiles["msd"]), "--find-peaks", "-o", str(target)]) == 0
    assert _read(target, "mSD").spectrum.haspeaks()


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


@needs_display
@pytest.mark.parametrize("mzRange", ["404:406", "300:406", "404:"])
def test_images_can_show_an_mz_range(files, tmp_path, mzRange):
    target = tmp_path / "range.png"

    assert _convert(files["single"], "-o", str(target), "--size", "640x360", "--mz-range", mzRange)[0] == 0
    assert target.exists()


@needs_display
def test_an_mz_range_without_data_is_refused(files, tmp_path, capsys):
    target = tmp_path / "range.png"

    assert _convert(files["single"], "-o", str(target), "--mz-range", "500:600")[0] == 1

    assert "holds no data" in capsys.readouterr().err
    assert not target.exists()
    assert os.listdir(tmp_path) == [os.path.basename(files["single"])] or not any(
        name.startswith(".") for name in os.listdir(tmp_path)
    )
