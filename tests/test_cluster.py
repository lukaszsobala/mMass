"""mmass cluster: grouping spectra by similarity from the command line.

The argument tests run headless without wx. Reading documents goes through
gui.doc, which imports wx (though it needs no display), so the end-to-end
tests skip where wx is unavailable.
"""

import csv
import inspect
import os
from xml.sax.saxutils import quoteattr

import pytest

import mspy
from mmass_app import cli

from .test_similarity import make_scan, random_peaks


# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------


def test_without_arguments_the_help_is_shown(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.parse_cluster_args([])
    assert exc.value.code == 0
    assert "mmass cluster" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["a.msd"],  # no -d
        ["-d", "out"],  # no inputs
        ["a.msd", "-d", "out", "--edge", "high"],
        ["a.msd", "-d", "out", "--top-k", "0"],
        ["a.msd", "-d", "out", "--tolerance", "0"],
        ["a.msd", "-d", "out", "--bootstrap", "-1"],
        ["a.msd", "-d", "out", "--source", "centroids"],
        ["a.msd", "-d", "out", "--seed", "-1"],
        ["a.msd", "-d", "out", "--tolerance", "inf"],
        ["a.msd", "-d", "out", "--baseline-window", "inf"],
        ["a.msd", "-d", "out", "--edge", "nan"],
        ["a.msd", "-d", "out", "--cut", "inf"],
    ],
)
def test_wrong_arguments_exit_with_2(argv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.parse_cluster_args(argv)
    assert exc.value.code == 2


def test_the_output_folder_must_not_be_a_file(tmp_path):
    taken = tmp_path / "taken"
    taken.write_text("x")
    with pytest.raises(SystemExit) as exc:
        cli.parse_cluster_args(["a.msd", "-d", str(taken)])
    assert exc.value.code == 2


def test_every_option_reaches_an_mspy_parameter(tmp_path):
    """The options are passed on as keyword arguments: a renamed parameter
    on either side must fail here, not in a user's run."""

    options = cli.parse_cluster_args(
        ["a.msd", "-d", str(tmp_path / "out"), "--edge", "auto", "--neutral-mass"]
    )
    mspy.similarityparams(**options.similarity)  # raises on unknown keys
    accepted = inspect.signature(mspy.groupspectra).parameters
    assert set(options.grouping) <= set(accepted)
    assert options.grouping["edge"] == "auto"
    assert options.similarity["neutralMass"] is True


def test_adducts_without_neutral_mass_are_ignored_with_a_warning(tmp_path, capsys):
    cli.parse_cluster_args(["a.msd", "-d", str(tmp_path / "o"), "--pos-adduct", "K"])
    assert "--pos-adduct applies with --neutral-mass" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------


@pytest.fixture
def gui_doc():
    return pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")


def _write(scan, path, title):
    mspy.writeMZML(scan, {"title": title}).write(str(path))
    return str(path)


@pytest.fixture
def families(tmp_path, gui_doc):
    """Two families of three spectra and one unrelated spectrum, as mzML."""

    base1 = random_peaks(101, 100, 900, 15)
    base2 = random_peaks(202, 100, 900, 15)
    paths = {}
    for name, base, seed in [
        ("a1", base1, 1),
        ("a2", base1, 2),
        ("a3", base1, 3),
        ("b1", base2, 4),
        ("b2", base2, 5),
        ("b3", base2, 6),
    ]:
        scan = make_scan(base + random_peaks(seed, 100, 900, 4), hi=950, seed=seed)
        paths[name] = _write(scan, tmp_path / f"{name}.mzML", name)
    loner = make_scan(random_peaks(303, 100, 900), hi=950, seed=9)
    paths["loner"] = _write(loner, tmp_path / "loner.mzML", "loner")
    return paths


def _run(*argv):
    from mmass_app import cluster

    return cluster.run(cli.parse_cluster_args([str(a) for a in argv]))


def _groups(folder):
    with open(os.path.join(folder, "groups.csv"), newline="", encoding="utf-8") as fh:
        return {row["spectrum"]: row for row in csv.DictReader(fh)}


def test_families_are_grouped_and_every_output_is_written(families, tmp_path, capsys):
    out = tmp_path / "out"
    assert _run(*families.values(), "-d", out, "--bootstrap", "20") == 0
    for name in cli.CLUSTER_OUTPUTS:
        assert (out / name).exists(), name
    rows = _groups(out)
    group = {name: rows[name]["group"] for name in rows}
    assert group["a1"] == group["a2"] == group["a3"]
    assert group["b1"] == group["b2"] == group["b3"]
    assert group["a1"] != group["b1"]
    assert group["loner"] not in (group["a1"], group["b1"])
    report = (out / "REPORT.md").read_text()
    assert "## Group" in report and "## Not grouped" in report
    assert "7 spectra" in capsys.readouterr().out


def test_existing_results_need_overwrite(families, tmp_path, capsys):
    out = tmp_path / "out"
    inputs = [families["a1"], families["a2"], families["b1"]]
    assert _run(*inputs, "-d", out, "--bootstrap", "0") == 0
    before = (out / "REPORT.md").stat().st_mtime_ns
    assert _run(*inputs, "-d", out, "--bootstrap", "0") == 2
    assert "--overwrite" in capsys.readouterr().err
    assert (out / "REPORT.md").stat().st_mtime_ns == before
    assert _run(*inputs, "-d", out, "--bootstrap", "0", "--overwrite") == 0


def test_without_bootstrap_no_co_membership_table_is_left(families, tmp_path):
    out = tmp_path / "out"
    inputs = [families["a1"], families["a2"], families["b1"]]
    assert _run(*inputs, "-d", out, "--bootstrap", "5") == 0
    assert (out / "co_membership.csv").exists()
    assert _run(*inputs, "-d", out, "--bootstrap", "0", "--overwrite") == 0
    assert not (out / "co_membership.csv").exists()


def test_an_unusable_input_is_reported_and_the_rest_grouped(families, tmp_path, capsys):
    fasta = tmp_path / "seq.fasta"
    fasta.write_text(">p\nPEPTIDE\n")
    out = tmp_path / "out"
    status = _run(families["a1"], families["a2"], fasta, "-d", out, "--bootstrap", "0")
    assert status == 1
    assert "sequences, not spectra" in capsys.readouterr().err
    assert len(_groups(out)) == 2


def test_fewer_than_two_spectra_is_an_error(families, tmp_path, capsys):
    assert _run(families["a1"], "-d", tmp_path / "out") == 1
    assert "at least two" in capsys.readouterr().err


def _session(path, documents):
    lines = [
        '<?xml version="1.0" encoding="utf-8" ?>',
        '<mMassSession version="1.0">',
        '  <documents current="0">',
    ]
    for doc_path, visible in documents:
        lines.append(f"    <document path={quoteattr(str(doc_path))} visible=\"{int(visible)}\" />")
    lines += ["  </documents>", "</mMassSession>"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def test_a_session_gives_its_visible_documents(families, tmp_path, capsys):
    session = _session(
        tmp_path / "set.mses",
        [
            (families["a1"], True),
            (families["a2"], True),
            (families["b1"], False),
        ],
    )
    out = tmp_path / "out"
    assert _run(session, "-d", out, "--bootstrap", "0") == 0
    assert set(_groups(out)) == {"a1", "a2"}
    assert "1 hidden document" in capsys.readouterr().err
    assert (
        _run(session, "-d", out, "--bootstrap", "0", "--include-hidden", "--overwrite")
        == 0
    )
    assert set(_groups(out)) == {"a1", "a2", "b1"}


def test_a_missing_session_document_is_reported(families, tmp_path, capsys):
    session = _session(
        tmp_path / "set.mses",
        [
            (families["a1"], True),
            (families["a2"], True),
            (str(tmp_path / "gone.mzML"), True),
        ],
    )
    assert _run(session, "-d", tmp_path / "out", "--bootstrap", "0") == 1
    assert "cannot be found" in capsys.readouterr().err


def test_spectra_of_the_same_title_get_their_folder(tmp_path, gui_doc):
    peaks = random_peaks(5, 100, 900)
    paths = []
    for day in ("day1", "day2"):
        folder = tmp_path / day / "good"
        folder.mkdir(parents=True)
        paths.append(
            _write(make_scan(peaks, hi=950, seed=len(paths)), folder / "x.mzML", "same")
        )
    out = tmp_path / "out"
    assert _run(*paths, "-d", out, "--bootstrap", "0") == 0
    assert set(_groups(out)) == {"same (day1)", "same (day2)"}


def test_polarities_get_separate_trees_unless_neutral_mass(tmp_path, gui_doc):
    glycans = [700.0, 862.05, 1024.1, 1186.16, 1348.2]
    paths = []
    for k, (polarity, shift) in enumerate(
        [(1, 22.989218), (1, 22.989218), (-1, -1.007276), (-1, -1.007276)]
    ):
        scan = make_scan(
            [(m + shift, 10.0) for m in glycans], hi=1400, polarity=polarity, seed=k
        )
        paths.append(_write(scan, tmp_path / f"s{k}.mzML", f"s{k}"))
    out = tmp_path / "out"
    assert _run(*paths, "-d", out, "--bootstrap", "0") == 0
    assert "different polarity were not compared" in (out / "REPORT.md").read_text()
    assert len((out / "trees.nwk").read_text().splitlines()) == 2
    rows = _groups(out)
    assert rows["s0"]["polarity"] == "positive" and rows["s2"]["polarity"] == "negative"

    out2 = tmp_path / "neutral"
    assert _run(*paths, "-d", out2, "--bootstrap", "0", "--neutral-mass") == 0
    assert len((out2 / "trees.nwk").read_text().splitlines()) == 1
    assert len({row["group"] for row in _groups(out2).values()}) == 1


def test_the_command_dispatches_to_cluster(families, tmp_path):
    from mmass_app import app

    out = tmp_path / "out"
    assert (
        app.main(
            [
                "cluster",
                families["a1"],
                families["b1"],
                families["a2"],
                "-d",
                str(out),
                "--bootstrap",
                "0",
            ]
        )
        == 0
    )
    assert (out / "REPORT.md").exists()


def test_a_session_document_that_fails_to_read_does_not_stop_the_rest(
    families, tmp_path, capsys, monkeypatch
):
    from mmass_app import cluster

    session = _session(
        tmp_path / "set.mses",
        [(families["a1"], True), (families["a2"], True), (families["b1"], True)],
    )
    real = cluster.read_input

    def flaky(path, scanArg=None, problems=None):
        if path == families["a1"]:
            raise OSError("vanished")
        return real(path, scanArg, problems)

    monkeypatch.setattr(cluster, "read_input", flaky)
    out = tmp_path / "out"
    assert _run(session, "-d", out, "--bootstrap", "0") == 1
    assert "vanished" in capsys.readouterr().err
    assert set(_groups(out)) == {"a2", "b1"}


def test_a_spectrum_without_data_is_refused(gui_doc):
    from mmass_app import cluster

    with pytest.raises(cluster.InputError, match="no data"):
        cluster._check_data(mspy.scan())


def _mgf(path, entries):
    lines = []
    for title, peaks in entries:
        lines += ["BEGIN IONS", f"TITLE={title}", "PEPMASS=950.0"]
        lines += [f"{mz:.4f} {ai:.1f}" for mz, ai in peaks]
        lines.append("END IONS")
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_centroided_mgf_spectra_are_compared_on_their_peaks(gui_doc, tmp_path):
    """Short MGF entries are read as peak lists: they must not score as
    empty profiles, and each title carries its scan number once."""

    base = random_peaks(31, 100, 900, 20)
    path = _mgf(
        tmp_path / "set.mgf",
        [("Sample", base), ("Sample", base[:-2]), ("Other", random_peaks(32, 100, 900, 20))],
    )
    out = tmp_path / "out"
    assert _run(path, "-d", out, "--bootstrap", "0") == 0
    rows = _groups(out)
    assert not any(label.count("[") > 1 for label in rows)
    with open(out / "similarity.csv", newline="", encoding="utf-8") as fh:
        table = list(csv.reader(fh))
    assert float(table[1][2]) > 0.5  # the two Sample entries


def test_an_empty_mgf_entry_is_left_out_on_its_own(gui_doc, tmp_path, capsys):
    base = random_peaks(31, 100, 900, 20)
    path = _mgf(tmp_path / "set.mgf", [("A", base), ("Empty", []), ("B", base[:-2])])
    out = tmp_path / "out"
    assert _run(path, "-d", out, "--bootstrap", "0") == 1
    assert "no data points or peaks" in capsys.readouterr().err
    assert len(_groups(out)) == 2
