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
    options = cli.parse_convert_args(["-f", ".CSV", "a.mzML", "--overwrite", "b.msd"])

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
        (["a.mzML", "-o", "x.png", "-d", "out"], "--output-dir works with --format"),
        (["a.mzML"], "say where to write"),
        (["a.mzML", "missing.mzML", "-f", "png"], "inputs not found"),
        (["a.mzML", "-f", "png", "-d", "b.msd"], "not a folder"),
        (["a.mzML", "-f", "png", "--size", "1920"], "not a size"),
        (["a.mzML", "-f", "png", "--size", "0x100"], "between 1 and"),
    ],
)
def test_convert_refuses_impossible_requests(files, capsys, argv, message):
    assert message in _convert_error(argv, capsys)


def test_convert_image_options(files, capsys):
    raster = cli.parse_convert_args(["a.mzML", "-f", "jpg", "--size", "800x600", "--dark"])
    svg = cli.parse_convert_args(["a.mzML", "-f", "svg", "--size", "800x600"])

    assert (raster.size, raster.dark) == ((800, 600), True)
    assert svg.size == cli.SVG_SIZE
    assert "--size does not apply to svg" in capsys.readouterr().err


def test_convert_warns_about_options_that_do_not_apply(files, capsys):
    options = cli.parse_convert_args(
        ["a.mzML", "-f", "txt", "--size", "800x600", "--dark", "--separator", "semicolon"]
    )

    assert options.separator == ";"
    err = capsys.readouterr().err
    assert "--size does not apply" in err and "--dark does not apply" in err


def test_convert_image_range(files, capsys):
    options = cli.parse_convert_args(["a.mzML", "-f", "png", "--range", "400.5:"])
    text = cli.parse_convert_args(["a.mzML", "-f", "txt", "--range", "400:500"])
    alias = cli.parse_convert_args(["a.mzML", "-f", "png", "--mz-range", "400-500"])

    assert options.mzRange == (400.5, None)
    assert text.mzRange is None
    assert alias.mzRange == (400.0, 500.0)
    assert "--range does not apply to txt" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["400", "500:400", ":", "a:b", "1:2:3"])
def test_convert_refuses_ranges_that_are_none(files, capsys, value):
    assert "--range" in _convert_error(["a.mzML", "-f", "png", "--range", value], capsys)


def test_convert_writes_peak_lists_as_text(files, capsys):
    options = cli.parse_convert_args(["a.mzML", "-f", "csv", "--peak-list", "--columns", "mz,z,envarea"])
    image = cli.parse_convert_args(["a.mzML", "-f", "png", "--peak-list"])

    assert options.peaklist and options.columns == ["mz", "z", "envarea"]
    assert not image.peaklist
    assert "--peak-list does not apply to png" in capsys.readouterr().err
    assert "unknown peak list column" in _convert_error(
        ["a.mzML", "-f", "csv", "--peak-list", "--columns", "mz,height"], capsys
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
        ["--find-peaks", "a.mzML", "--crop", "500:1500.5", "--math", "SquareRoot",
         "--baseline", "-f", "msd", "--find-peaks", "--math", "multiply", "--math", "SQRT"]
    )

    assert options.steps == [
        ("find-peaks", None),
        ("crop", (500.0, 1500.5)),
        ("math", "squareroot"),
        ("baseline", None),
        ("find-peaks", None),
        ("math", "multiply"),
        ("math", "squareroot"),
    ]
    assert options.command == cli.PROCESS_COMMAND
    assert options.inputs == [str(files / "a.mzML")]


def test_process_in_place_leaves_the_format_to_each_input(files):
    options = _process(["a.mzML", "b.msd", "--smooth", "--in-place"])

    assert options.inPlace and options.format is None and options.kind is None


def test_process_settings(files):
    options = _process(
        ["a.mzML", "--find-peaks", "-f", "msd", "--preset", "Default",
         "--set", "peakpicking.snThreshold = 10", "--set", "smoothing.method=GA"]
    )

    assert options.preset == "Default"
    assert options.settings == [
        ("peakpicking.snThreshold", "10", "--set"),
        ("smoothing.method", "GA", "--set"),
    ]


def test_show_settings_needs_no_inputs():
    options = _process(["--show-settings", "--set", "baseline.offset=0"])

    assert options.showSettings and options.settings == [("baseline.offset", "0", "--set")]


@pytest.mark.parametrize(
    "argv, message",
    [
        (["a.mzML", "-f", "msd"], "no processing steps"),
        (["--baseline", "-f", "msd"], "no inputs"),
        (["a.mzML", "--baseline"], "--in-place to replace"),
        (["a.mzML", "--baseline", "--in-place", "-f", "msd"], "only one of --format and --in-place"),
        (["a.mzML", "--baseline", "--in-place", "-d", "out"], "not to --output-dir"),
        (["a.mzML", "--baseline", "--in-place", "--scan", "3"], "cannot pick one"),
        (["a.mzML", "--crop", "500:", "-f", "msd"], "both ends"),
        (["a.mzML", "--set", "snThreshold", "--find-peaks", "-f", "msd"], "not a setting"),
        (["a.mzML", "--find-peaks", "-f", "txt"], "peaks --find-peaks finds would be lost"),
        (["a.mzML", "--deisotope", "-f", "txt"], "peaks --deisotope"),
        (["a.mzML", "--find-peaks", "--baseline", "-f", "mgf"], "--baseline does not change"),
        (["a.mzML", "--smooth", "-f", "csv", "--peak-list"], "--smooth does not change"),
        (["a.mzML", "--math", "subtract", "-f", "msd"], "more spectra than the one"),
        (["a.mzML", "--math", "averageall", "-f", "msd"], "more spectra than the one"),
        (["a.mzML", "--math", "log", "-f", "msd"], "unknown math operation"),
        (["a.mzML", "--math", "-f", "msd"], "expected one argument"),
    ],
)
def test_process_refuses_impossible_requests(files, capsys, argv, message):
    assert message in _process_error(argv, capsys)


@pytest.mark.parametrize(
    "argv",
    [
        ["--baseline", "--find-peaks", "-f", "mgf"],
        ["--find-peaks", "-f", "csv", "--peak-list"],
        ["--crop", "1:2", "--math", "normalize", "-f", "mgf"],
        ["--find-peaks", "--deisotope", "-f", "png"],
        ["--baseline", "--smooth", "-f", "txt"],
    ],
)
def test_process_accepts_steps_the_output_keeps(files, argv):
    assert _process(["a.mzML", *argv]).steps


def test_process_warns_about_options_that_do_not_apply(files, capsys):
    options = _process(["a.mzML", "--baseline", "--in-place", "--overwrite", "--dark"])

    assert not options.overwrite
    err = capsys.readouterr().err
    assert "--overwrite does not apply" in err and "--dark does not apply to in-place" in err


# ---------------------------------------------------------------------------
# Help, hints and spellings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "parse",
    [
        lambda argv: cli.parse_args(argv),
        lambda argv: cli.parse_convert_args(argv),
        lambda argv: cli.parse_convert_args(argv, command=cli.PROCESS_COMMAND),
    ],
    ids=["mmass", "convert", "process"],
)
def test_every_help_renders(parse, capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse(["--help"])

    assert exit_info.value.code == 0
    assert "usage: mmass" in capsys.readouterr().out


def test_the_launcher_help_lists_the_commands(capsys):
    with pytest.raises(SystemExit):
        cli.parse_args(["--help"])

    out = capsys.readouterr().out
    assert "mmass convert INPUT" in out and "mmass process INPUT" in out


@pytest.mark.parametrize("command", [cli.CONVERT_COMMAND, cli.PROCESS_COMMAND])
def test_a_command_without_arguments_shows_its_help(command, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.parse_convert_args([], command=command)

    assert exit_info.value.code == 0
    assert f"usage: mmass {command}" in capsys.readouterr().out


def test_errors_are_short(files, capsys):
    err = _convert_error(["a.mzML", "-o", "out.doc"], capsys)

    assert err.splitlines() == [
        "mmass convert: error: unknown output file out.doc; write one of: "
        + ", ".join(cli.OUTPUT_FORMATS),
        "See 'mmass convert --help'.",
    ]


def test_options_cannot_be_abbreviated(files, capsys):
    assert "unrecognized arguments: --ran" in _convert_error(
        ["a.mzML", "-f", "png", "--ran", "400:500"], capsys
    )


@pytest.mark.parametrize(
    "argv, message",
    [
        (["a.mzML", "b.msd", "c.png"], "c.png names one output file, for one input"),
        (["a.mzML", "b.msd"], "b.msd already exists, and as the last name it would be the output"),
        (["a.mzML", "bruker"], "bruker is a folder; to write into a folder, use --format FORMAT --output-dir bruker"),
        (["a.mzML", "out.png", "-d", "out"], "--output-dir works with --format"),
        (["a.mzML", "out.fasta"], "cannot write them (output file out.fasta)"),
        (["a.mzML"], "an output file after the input"),
        (["a.mzML", "b.msd", "-o", "out/"], "use --format FORMAT --output-dir out/"),
        (["a.mzML", "-o", "bruker"], "bruker is a folder"),
        (["a.mzML", "--find-peaks", "-f", "csv"], "use mmass process instead"),
        (["a.mzML", "--set=snThreshold=3", "-f", "csv"], "--set belongs to processing"),
        (["a.mzML", "-f", "csv", "-o", "b.csv"], "only one of --output and --format"),
        (["a.mzML", "-o", "-"], "needs --format FORMAT"),
        (["a.mzML", "b.msd", "-o", "-", "-f", "csv"], "only one input"),
    ],
)
def test_likely_mistakes_get_a_hint(files, capsys, argv, message):
    assert message in _convert_error(argv, capsys)


def test_an_output_file_can_follow_the_input(files, capsys):
    options = cli.parse_convert_args(["a.mzML", "out/Plot.SVG", "--dark"])
    replaced = cli.parse_convert_args(["a.mzML", "b.msd", "--overwrite"])
    processed = _process(["a.mzML", "--find-peaks", "peaks.csv", "--peak-list"])

    assert options.inputs == [str(files / "a.mzML")]
    assert (options.output, options.format, options.dark) == (str(files / "out" / "Plot.SVG"), "svg", True)
    assert (replaced.output, replaced.format) == (str(files / "b.msd"), "msd")
    assert (processed.output, processed.format, processed.peaklist) == (str(files / "peaks.csv"), "csv", True)
    assert capsys.readouterr().err == ""


def test_standard_output_takes_the_format_from_to(files):
    options = cli.parse_convert_args(["a.mzML", "-o", "-", "-f", "CSV", "--peak-list"])

    assert (options.output, options.format, options.peaklist) == ("-", "csv", True)


@pytest.mark.parametrize(
    "value, expected",
    [("400-1500", (400.0, 1500.0)), ("400.5-", (400.5, None)), ("-1500", (None, 1500.0))],
)
def test_ranges_take_a_dash(files, value, expected):
    options = cli.parse_convert_args(["a.mzML", "-f", "png", "--range", value])

    assert options.mzRange == expected


def test_columns_take_readable_names_in_any_case(files):
    options = cli.parse_convert_args(
        ["a.mzML", "-f", "csv", "--peak-list", "--columns", "MZ, Intensity,charge,resolution"]
    )

    assert options.columns == ["mz", "int", "z", "resol"]


def test_mgf_is_a_peak_list_already(files, capsys):
    cli.parse_convert_args(["a.mzML", "-f", "mgf", "--peak-list"])

    assert capsys.readouterr().err == ""


def test_old_spellings_still_work_but_are_not_listed(files, capsys):
    options = _process(["a.mzML", "--findpeaks", "-f", "csv", "--peaklist", "--math", "normalise"])

    assert options.steps == [("find-peaks", None), ("math", "normalize")]
    assert options.peaklist
    with pytest.raises(SystemExit):
        _process(["--help"])
    out = capsys.readouterr().out
    assert "--find-peaks" in out and "--findpeaks" not in out and "--peaklist" not in out
    assert "--range" in out and "--mz-range" not in out


def test_warnings_name_the_command(files, capsys):
    cli.parse_convert_args(["a.mzML", "-f", "txt", "--dark"])

    assert capsys.readouterr().err.startswith("mmass convert: warning:")


def test_bare_setting_keys(files):
    options = _process(["a.mzML", "--find-peaks", "-f", "msd", "--set", "snThreshold=4"])

    assert options.settings == [("snThreshold", "4", "--set")]


def test_dry_run(files):
    assert _process(["a.mzML", "--baseline", "--in-place", "--dry-run"]).dryRun


def test_paths_are_shown_relative_to_the_current_folder(files):
    assert cli.shown_path(str(files / "out" / "a.png")) == os.path.join("out", "a.png")
    assert cli.shown_path(os.path.dirname(str(files))) == os.path.dirname(str(files))
    assert cli.shown_path("-") == "standard output"


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------


def _recipe(files, text, name="steps.recipe"):
    (files / name).write_text(text)
    return name


def test_a_recipe_runs_where_it_is_given(files):
    recipe = _recipe(
        files,
        "# comment\n"
        "preset MALDI-TOF Peptides\n"
        "set snThreshold=8   # inline comment\n"
        "\n"
        "  crop 500-4000\n"
        "--baseline\n"
        "findpeaks\n"
        "math=sqrt\n"
        "peak-list\n"
        "columns mz, charge\n",
    )

    options = _process(
        ["a.mzML", "--smooth", "--recipe", recipe, "--deisotope", "-f", "csv", "--set", "snThreshold=9"]
    )

    assert options.steps == [
        ("smooth", None),
        ("crop", (500.0, 4000.0)),
        ("baseline", None),
        ("find-peaks", None),
        ("math", "squareroot"),
        ("deisotope", None),
    ]
    assert options.settings == [
        ("snThreshold", "8", f"recipe {recipe}, line 3"),
        ("snThreshold", "9", "--set"),
    ]
    assert (options.preset, options.presetOrigin) == ("MALDI-TOF Peptides", f"recipe {recipe}, line 2")
    assert options.peaklist and options.columns == ["mz", "z"]


def test_a_recipe_alone_is_enough_for_show_settings(files):
    recipe = _recipe(files, "set baseline.offset=0\n")

    options = _process(["--show-settings", "--recipe", recipe])

    assert options.settings == [("baseline.offset", "0", f"recipe {recipe}, line 1")]


@pytest.mark.parametrize(
    "text, message",
    [
        ("find-peaks\nformat csv\n", "line 2: --format belongs on the command line"),
        ("in-place\n", "line 1: --in-place belongs on the command line"),
        ("output-dir out\n", "--output-dir belongs on the command line"),
        ("recipe other\n", "cannot include another recipe"),
        ("crop 600\n", "line 1: '600' is not an m/z range"),
        ("baseline now\n", "baseline takes no value"),
        ("math\n", "math needs a value"),
        ("smoothen\n", "unknown option 'smoothen'"),
        ("separator pipe\n", "separator must be one of"),
        ("= 3\n", "is not an option"),
    ],
)
def test_recipe_mistakes_name_their_line(files, capsys, text, message):
    recipe = _recipe(files, text)

    err = _process_error(["a.mzML", "--recipe", recipe, "--find-peaks", "-f", "msd"], capsys)

    assert f"recipe {recipe}, " in err and message in err


def test_a_missing_recipe(files, capsys):
    assert "cannot read the recipe nope.txt" in _process_error(
        ["a.mzML", "--recipe", "nope.txt", "-f", "msd"], capsys
    )
