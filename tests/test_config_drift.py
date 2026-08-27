"""Guard that the deisotoping config keys the pipeline relies on still exist.

The envelope recalculation helper and its tests read a fixed set of keys from
config.processing["deisotoping"]. Their VALUES are user-tunable at runtime, so
this test only asserts the keys are present with compatible types -- catching a
rename or removal that would break the GUI wiring. It skips if gui.config can't
be imported (e.g. wxPython missing).
"""

import inspect
import re

import pytest

from .helpers import DEISOTOPING_KEYS


def test_deisotoping_keys_present_with_expected_types():
    try:
        from gui import config  # noqa: WPS433 (optional import)
    except Exception:
        pytest.skip("gui.config not importable in this environment")

    actual = config.processing["deisotoping"]
    for key, expected_type in DEISOTOPING_KEYS.items():
        assert key in actual, f"deisotoping config lost key: {key}"
        if expected_type is float:
            assert isinstance(actual[key], (int, float)), f"{key} not numeric"
        else:
            assert isinstance(actual[key], expected_type), (
                f"{key} expected {expected_type.__name__}, got {type(actual[key]).__name__}"
            )


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------

# Leaf settings that are deliberately NOT written to config.xml. Two kinds:
#
#   * code-owned constants -- service URLs and HTML report templates. The
#     in-code value must win on every launch; persisting them would pin a
#     user's config to whatever URL/template shipped when they first ran the
#     app, and they would never pick up a corrected one on upgrade.
#   * dead keys -- read somewhere (or nowhere) but never written by any GUI
#     control, so there is no user choice to remember.
#
# Anything NOT on this list must survive a save/load cycle. A new setting that
# shows up as unpersisted is either a bug in saveConfig or a conscious
# exclusion that belongs here with a reason.
NOT_PERSISTED = {
    # code-owned constants
    "main.latestVersionUrl",
    "massToFormula.PubChemScript",
    "massToFormula.ChemSpiderScript",
    "massToFormula.METLINScript",
    "massToFormula.HMDBScript",
    "massToFormula.LipidMAPSScript",
    "sequence.digest.listTemplateAmino",
    "sequence.digest.listTemplateCustom",
    "sequence.digest.matchTemplateAmino",
    "sequence.digest.matchTemplateCustom",
    "sequence.fragment.listTemplateAmino",
    "sequence.fragment.listTemplateCustom",
    "sequence.fragment.matchTemplateAmino",
    "sequence.fragment.matchTemplateCustom",
    "sequence.search.listTemplateAmino",
    "sequence.search.listTemplateCustom",
    # dead keys: no GUI control writes these
    "main.unlockGUI",
    "main.dataPrecision",
    "processing.peakpicking.monoisotopic",
    "massDefectPlot.xAxis",
}

_SECTIONS = (
    "main",
    "export",
    "spectrum",
    "match",
    "processing",
    "calibration",
    "sequence",
    "massCalculator",
    "massToFormula",
    "massDefectPlot",
    "compoundsSearch",
    "peakDifferences",
    "comparePeaklists",
    "spectrumGenerator",
    "envelopeFit",
    "mascot",
    "profound",
    "prospector",
)


def _leaves(node, prefix):
    """Yield dotted paths of every non-dict value under node."""

    for key, value in node.items():
        if isinstance(value, dict):
            yield from _leaves(value, "%s.%s" % (prefix, key))
        else:
            yield "%s.%s" % (prefix, key)


def test_every_user_setting_is_written_to_config_xml():
    """saveConfig must emit a <param> for every setting a user can change.

    The writer used to be hand-maintained alongside the default dicts and had
    silently drifted: 24 settings the GUI wrote at runtime were never
    serialized, so they reset to defaults on every launch.
    """

    try:
        from gui import config
    except Exception:
        pytest.skip("gui.config not importable in this environment")

    source = inspect.getsource(config)
    writer = source[source.index("def saveConfig(") : source.index("def _getParams(")]
    written = set(re.findall(r'<param name="(\w+)"', writer))

    unpersisted = {
        path
        for section in _SECTIONS
        for path in _leaves(getattr(config, section), section)
        if path.rsplit(".", 1)[1] not in written
    }

    assert unpersisted == NOT_PERSISTED, (
        "config.xml persistence drifted.\n"
        "  newly unpersisted (add to saveConfig, or to NOT_PERSISTED with a reason): %s\n"
        "  no longer unpersisted (drop from NOT_PERSISTED): %s"
        % (
            sorted(unpersisted - NOT_PERSISTED),
            sorted(NOT_PERSISTED - unpersisted),
        )
    )


# Every setting a GUI control writes at runtime, with a value distinct from its
# default, so a round-trip that silently drops one is caught by value and not
# just by key.
ROUND_TRIP_VALUES = {
    ("spectrum", "normalize"): 1,
    ("processing", "math", "operation"): "multiply",
    ("processing", "math", "multiplier"): 2.5,
    ("processing", "math", "preservePeaks"): 0,
    ("processing", "baseline", "preservePeaks"): 0,
    ("processing", "smoothing", "preservePeaks"): 0,
    ("processing", "deisotoping", "isotopeShift"): 0.0125,
    ("processing", "batch", "baseline"): 1,
    ("processing", "batch", "deisotoping"): 1,
    ("processing", "batch", "stepOrder"): [
        "crop",
        "math",
        "smoothing",
        "baseline",
        "peakpicking",
        "deisotoping",
        "deconvolution",
    ],
    ("sequence", "search", "mass"): 1234.5678,
    ("massCalculator", "patternIntensity"): 77.0,
    ("massCalculator", "patternBaseline"): 3.0,
    ("massCalculator", "patternShift"): -0.25,
    ("massDefectPlot", "showAllDocuments"): 1,
    ("comparePeaklists", "compare"): "theoretical",
    ("spectrumGenerator", "showFlipped"): 1,
    ("envelopeFit", "loss"): "H{2}",
    ("envelopeFit", "gain"): "D",
    ("envelopeFit", "scaleMin"): 3,
    ("envelopeFit", "scaleMax"): 42,
    ("mascot", "common", "title"): 'a search <&> "quoted"',
    ("mascot", "mis", "peptideMass"): "999.5",
    ("profound", "title"): "profound title",
    ("prospector", "common", "title"): "prospector title",
    ("prospector", "mstag", "peptideMass"): "555.25",
    # a path where leading/trailing whitespace is significant -- _escape() used
    # to strip() it away
    ("main", "lastDir"): "/tmp/dir with trailing space ",
}


@pytest.fixture
def config_module():
    """gui.config with autosave off and every section restored afterwards.

    Without this, assigning to config.* in a test fires ConfigDict's autosave,
    which writes the *developer's own* ~/.config/mmass/config.xml -- saveConfig
    bound its default path at import time, so monkeypatching config.confdir
    does not redirect it.
    """

    try:
        from gui import config
    except Exception:
        pytest.skip("gui.config not importable in this environment")

    snapshot = config._snapshotSections()
    with config._suspendAutoSave():
        try:
            yield config
        finally:
            config._restoreSections(snapshot)


def test_snapshot_does_not_trigger_autosave(config_module):
    """Taking a snapshot must not write config.xml even once.

    _snapshotSections() used to copy.deepcopy() the sections, which rebuilds
    each ConfigDict through the overridden __setitem__ and fired one full
    config.xml rewrite per key -- several hundred per snapshot.
    """

    config = config_module
    calls = []
    original = config.saveConfig
    config.saveConfig = lambda *a, **kw: (calls.append(1), original(*a, **kw))[1]
    try:
        config._snapshotSections()
    finally:
        config.saveConfig = original

    assert calls == [], "_snapshotSections() triggered %d saveConfig calls" % len(calls)


def _dig(module, path):
    node = getattr(module, path[0])
    for key in path[1:-1]:
        node = node[key]
    return node


def test_user_settings_survive_save_and_load(config_module, tmp_path):
    """Values written by the GUI must come back after save -> load."""

    config = config_module
    baseline = config._snapshotSections()

    for path, value in ROUND_TRIP_VALUES.items():
        _dig(config, path)[path[-1]] = value

    target = str(tmp_path / "config.xml")
    assert config.saveConfig(target), "saveConfig reported failure"

    config._restoreSections(baseline)  # back to in-code defaults
    config.loadConfig(target)

    lost = {
        ".".join(path): (value, _dig(config, path)[path[-1]])
        for path, value in ROUND_TRIP_VALUES.items()
        if _dig(config, path)[path[-1]] != value
    }
    assert not lost, "settings did not survive the round-trip: %s" % lost


def test_corrupt_config_does_not_prevent_startup(config_module, tmp_path, monkeypatch):
    """A truncated config.xml must fall back to defaults, not stop startup.

    A half-written config.xml raises ExpatError, which is not an OSError, so it
    used to escape `import gui.config` entirely and stop the app from starting,
    with no in-app way to recover.
    """

    config = config_module
    baseline = config._snapshotSections()
    default_width = config.main["appWidth"]

    # a real config carrying a non-default value, then truncated
    config.main["appWidth"] = 4321
    full = str(tmp_path / "config.xml")
    assert config.saveConfig(full)
    damaged = open(full, "rb").read()[:800]

    config._restoreSections(baseline)
    assert default_width != 4321

    confdir = tmp_path / "confdir"
    confdir.mkdir()
    (confdir / "config.xml").write_bytes(damaged)
    monkeypatch.setattr(config, "confdir", str(confdir))

    config._initialize_runtime_config()  # must not raise

    assert config.main["appWidth"] == default_width, (
        "a corrupt config must leave the in-code defaults in place"
    )
    assert (confdir / "config.xml.corrupt").exists(), (
        "the unreadable file must be kept for the user to recover"
    )
    # and a fresh, readable config takes its place
    assert (confdir / "config.xml").exists()
    config.loadConfig(str(confdir / "config.xml"))


def test_atomic_write_leaves_no_partial_file(config_module, tmp_path):
    """write_file_atomically must not leave a temp file or a truncated target."""

    config = config_module
    target = tmp_path / "thing.xml"
    target.write_bytes(b"original contents")

    assert config.write_file_atomically(str(target), b"replacement")
    assert target.read_bytes() == b"replacement"
    assert list(tmp_path.iterdir()) == [target], "temp file left behind"
