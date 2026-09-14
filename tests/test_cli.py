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
