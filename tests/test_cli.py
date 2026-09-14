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


def test_cli_imports_neither_wx_nor_gui():
    # in a fresh interpreter, since other tests may have imported gui already
    code = (
        "import sys, mmass_app.cli; "
        "sys.exit(any(m == 'wx' or m.startswith(('wx.', 'gui')) for m in sys.modules))"
    )
    src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
    env = dict(os.environ, PYTHONPATH=src)

    assert subprocess.run([sys.executable, "-c", code], env=env).returncode == 0
