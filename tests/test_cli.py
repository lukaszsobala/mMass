"""Command-line arguments of the mmass launcher (mmass_app.cli, no wxPython)."""

import os
import subprocess
import sys

import pytest

from mmass_app import cli


@pytest.fixture
def files(tmp_path, monkeypatch):
    """Two spectra and two sessions in a temporary working directory."""

    for name in ("a.mzML", "b.msd", "one.mses", "two.MSES"):
        (tmp_path / name).write_text("")
    (tmp_path / "bruker").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_documents_become_absolute_in_order(files):
    options = cli.parse_args(["b.msd", "a.mzML", "bruker"])

    assert options.documents == [
        str(files / "b.msd"),
        str(files / "a.mzML"),
        str(files / "bruker"),
    ]
    assert options.session is None


def test_no_arguments_open_nothing():
    assert cli.parse_args([]) == cli.StartupOptions()


def test_missing_paths_are_reported_and_skipped(files, capsys):
    options = cli.parse_args(["missing.mzML", "a.mzML"])

    assert options.documents == [str(files / "a.mzML")]
    assert "missing.mzML" in capsys.readouterr().err


def test_launcher_placeholders_are_dropped_silently(files, capsys):
    options = cli.parse_args(["%F", '"a.mzML"', "  "])

    assert options.documents == [str(files / "a.mzML")]
    assert capsys.readouterr().err == ""


def test_session_is_separated_from_documents(files, capsys):
    options = cli.parse_args(["a.mzML", "two.MSES", "one.mses"])

    assert options.session == str(files / "two.MSES")
    assert options.documents == [str(files / "a.mzML")]
    assert "one.mses" in capsys.readouterr().err


def test_unknown_options_do_not_stop_startup(files, capsys):
    options = cli.parse_args(["--bogus", "-psn_0_12345", "a.mzML"])

    assert options.documents == [str(files / "a.mzML")]
    err = capsys.readouterr().err
    assert "--bogus" in err
    assert "psn" not in err


def test_double_dash_opens_a_file_named_like_an_option(files):
    (files / "-dash.xy").write_text("")

    options = cli.parse_args(["--", "-dash.xy"])

    assert options.documents == [str(files / "-dash.xy")]


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_exit(flag, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.parse_args([flag])

    assert exit_info.value.code == 0
    assert "mmass" in capsys.readouterr().out


@pytest.mark.parametrize("module", ["mmass_app.cli", "mmass_app.app"])
def test_launcher_imports_neither_wx_nor_gui(module):
    # so --help needs no GUI; in a fresh interpreter, since other tests may
    # have imported gui already
    code = (
        f"import sys, {module}; "
        "sys.exit(any(m == 'wx' or m.startswith(('wx.', 'gui')) for m in sys.modules))"
    )
    src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
    env = dict(os.environ, PYTHONPATH=src)

    assert subprocess.run([sys.executable, "-c", code], env=env).returncode == 0


# ---------------------------------------------------------------------------
# mmass convert arguments
# ---------------------------------------------------------------------------


def _convert_error(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.parse_convert_args(argv)
    assert exit_info.value.code == 2
    return capsys.readouterr().err


def test_convert_takes_the_format_from_the_output_name(files):
    options = cli.parse_convert_args(["a.mzML", "-o", "out/Plot.PNG"])

    assert options.format == "png"
    assert options.kind == "image"
    assert options.output == str(files / "out" / "Plot.PNG")
    assert options.size == cli.DEFAULT_IMAGE_SIZE


def test_convert_inputs_may_follow_options(files):
    options = cli.parse_convert_args(["-t", ".CSV", "a.mzML", "--overwrite", "b.msd"])

    assert options.inputs == [str(files / "a.mzML"), str(files / "b.msd")]
    assert options.format == "csv"
    assert options.separator == ","
    assert options.overwrite


@pytest.mark.parametrize(
    "output, message",
    [
        ("out.mzData", "cannot write"),
        ("out.mses", "cannot write"),
        ("out.fasta", "cannot write"),
        ("fid", "cannot write"),
        ("out.doc", "unknown output file"),
        ("out", "no extension"),
    ],
)
def test_convert_refuses_formats_it_cannot_write(files, capsys, output, message):
    assert message in _convert_error(["a.mzML", "-o", output], capsys)


@pytest.mark.parametrize(
    "argv, message",
    [
        (["a.mzML", "b.msd", "-o", "x.png"], "one input"),
        (["a.mzML", "-o", "x.png", "-d", "out"], "--output-dir works with --to"),
        (["a.mzML"], "required"),
        (["a.mzML", "missing.mzML", "-t", "png"], "inputs not found"),
        (["a.mzML", "-t", "png", "-d", "b.msd"], "not a folder"),
        (["a.mzML", "-t", "png", "--size", "1920"], "not a size"),
        (["a.mzML", "-t", "png", "--size", "0x100"], "between 1 and"),
    ],
)
def test_convert_refuses_impossible_requests(files, capsys, argv, message):
    assert message in _convert_error(argv, capsys)


def test_convert_image_options(files, capsys):
    raster = cli.parse_convert_args(["a.mzML", "-t", "jpg", "--size", "800x600", "--dark"])
    svg = cli.parse_convert_args(["a.mzML", "-t", "svg", "--size", "800x600"])

    assert (raster.size, raster.dark) == ((800, 600), True)
    assert svg.size == cli.SVG_SIZE
    assert "--size does not apply to svg" in capsys.readouterr().err


def test_convert_warns_about_options_that_do_not_apply(files, capsys):
    options = cli.parse_convert_args(
        ["a.mzML", "-t", "txt", "--size", "800x600", "--dark", "--separator", "semicolon"]
    )

    assert options.separator == ";"
    err = capsys.readouterr().err
    assert "--size does not apply" in err and "--dark does not apply" in err


def test_convert_image_range(files, capsys):
    options = cli.parse_convert_args(["a.mzML", "-t", "png", "--mz-range", "400.5:"])
    text = cli.parse_convert_args(["a.mzML", "-t", "txt", "--mz-range", "400:500"])

    assert options.mzRange == (400.5, None)
    assert text.mzRange is None
    assert "--mz-range does not apply to txt" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["400", "500:400", ":", "a:b", "1:2:3"])
def test_convert_refuses_ranges_that_are_none(files, capsys, value):
    assert "--mz-range" in _convert_error(["a.mzML", "-t", "png", "--mz-range", value], capsys)


def test_convert_writes_peak_lists_as_text(files, capsys):
    options = cli.parse_convert_args(["a.mzML", "-t", "csv", "--peaklist", "--columns", "mz,z,envarea"])
    image = cli.parse_convert_args(["a.mzML", "-t", "png", "--peaklist"])

    assert options.peaklist and options.columns == ["mz", "z", "envarea"]
    assert not image.peaklist
    assert "--peaklist does not apply to png" in capsys.readouterr().err
    assert "unknown peak list column" in _convert_error(
        ["a.mzML", "-t", "csv", "--peaklist", "--columns", "mz,height"], capsys
    )


# ---------------------------------------------------------------------------
# mmass process arguments
# ---------------------------------------------------------------------------


def _process(argv):
    return cli.parse_convert_args(argv, command=cli.PROCESS_COMMAND)


def _process_error(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _process(argv)
    assert exit_info.value.code == 2
    return capsys.readouterr().err


def test_process_keeps_the_order_of_the_steps(files):
    options = _process(
        ["--findpeaks", "a.mzML", "--crop", "500:1500.5", "--baseline", "-t", "msd", "--findpeaks"]
    )

    assert options.steps == [
        ("findpeaks", None),
        ("crop", (500.0, 1500.5)),
        ("baseline", None),
        ("findpeaks", None),
    ]
    assert options.command == cli.PROCESS_COMMAND
    assert options.inputs == [str(files / "a.mzML")]


def test_process_in_place_leaves_the_format_to_each_input(files):
    options = _process(["a.mzML", "b.msd", "--smooth", "--in-place"])

    assert options.inPlace and options.format is None and options.kind is None


def test_process_settings(files):
    options = _process(
        ["a.mzML", "--findpeaks", "-t", "msd", "--preset", "Default",
         "--set", "peakpicking.snThreshold = 10", "--set", "smoothing.method=GA"]
    )

    assert options.preset == "Default"
    assert options.settings == [("peakpicking.snThreshold", "10"), ("smoothing.method", "GA")]


def test_show_settings_needs_no_inputs():
    options = _process(["--show-settings", "--set", "baseline.offset=0"])

    assert options.showSettings and options.settings == [("baseline.offset", "0")]


@pytest.mark.parametrize(
    "argv, message",
    [
        (["a.mzML", "-t", "msd"], "no processing steps"),
        (["--baseline", "-t", "msd"], "no inputs"),
        (["a.mzML", "--baseline"], "--in-place to replace"),
        (["a.mzML", "--baseline", "--in-place", "-t", "msd"], "not allowed with"),
        (["a.mzML", "--baseline", "--in-place", "-d", "out"], "not to --output-dir"),
        (["a.mzML", "--baseline", "--in-place", "--scan", "3"], "cannot pick one"),
        (["a.mzML", "--crop", "500:", "-t", "msd"], "both ends"),
        (["a.mzML", "--set", "snThreshold=3", "--findpeaks", "-t", "msd"], "not a setting"),
        (["a.mzML", "--findpeaks", "-t", "txt"], "peaks --findpeaks finds would be lost"),
        (["a.mzML", "--deisotope", "-t", "txt"], "peaks --deisotope"),
        (["a.mzML", "--findpeaks", "--baseline", "-t", "mgf"], "--baseline does not change"),
        (["a.mzML", "--smooth", "-t", "csv", "--peaklist"], "--smooth does not change"),
    ],
)
def test_process_refuses_impossible_requests(files, capsys, argv, message):
    assert message in _process_error(argv, capsys)


@pytest.mark.parametrize(
    "argv",
    [
        ["--baseline", "--findpeaks", "-t", "mgf"],
        ["--findpeaks", "-t", "csv", "--peaklist"],
        ["--crop", "1:2", "--normalize", "-t", "mgf"],
        ["--findpeaks", "--deisotope", "-t", "png"],
        ["--baseline", "--smooth", "-t", "txt"],
    ],
)
def test_process_accepts_steps_the_output_keeps(files, argv):
    assert _process(["a.mzML", *argv]).steps


def test_process_warns_about_options_that_do_not_apply(files, capsys):
    options = _process(["a.mzML", "--baseline", "--in-place", "--overwrite", "--dark"])

    assert not options.overwrite
    err = capsys.readouterr().err
    assert "--overwrite does not apply" in err and "--dark does not apply to in-place" in err
