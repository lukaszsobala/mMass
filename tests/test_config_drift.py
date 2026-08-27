"""Guard that the deisotoping config keys the pipeline relies on still exist.

The envelope recalculation helper and its tests read a fixed set of keys from
config.processing["deisotoping"]. Their VALUES are user-tunable at runtime, so
this test only asserts the keys are present with compatible types -- catching a
rename or removal that would break the GUI wiring. It skips if gui.config can't
be imported (e.g. wxPython missing).
"""

import json

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
    # a path where leading/trailing whitespace is significant
    ("main", "lastDir"): "/tmp/dir with trailing space ",
}


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


def test_user_added_links_survive_but_builtin_links_track_the_code(
    config_module, tmp_path
):
    """Custom links persist; built-in ones are re-read from the code each launch.

    Built-in link URLs must not be pinned by an old config -- that is how a
    corrected URL would never reach an existing user.
    """

    config = config_module
    builtin = sorted(config._builtinLinks)[0]
    config.links["myCustomLink"] = "https://example.invalid/mine"
    config.links[builtin] = "https://example.invalid/stale"

    target = str(tmp_path / "config.json")
    assert config.saveConfig(target)

    stored = json.loads(open(target).read())["links"]
    assert "myCustomLink" in stored
    assert builtin not in stored, "a built-in link must not be written"

    config.loadConfig(target)
    assert config.links["myCustomLink"] == "https://example.invalid/mine"


def test_not_persisted_list_matches_the_code(config_module):
    """config.NOT_PERSISTED must name exactly the settings saveConfig omits.

    The list drives the serializer, so a setting added to the defaults is
    persisted automatically -- no writer to hand-edit, which is how the old XML
    writer silently lost 24 settings. This catches the reverse mistake: an
    entry left on the list after the setting it excluded became user-facing.
    """

    config = config_module

    everything = set()
    kept = set()
    for section in _SECTIONS:
        defaults = config._plainCopy(getattr(config, section))
        everything |= set(_leaves(defaults, section))
        kept |= set(_leaves(config._stripExcluded(defaults, section), section))

    assert everything - kept == set(config.NOT_PERSISTED), (
        "NOT_PERSISTED drifted from what saveConfig actually omits:\n"
        "  omitted but not listed: %s\n"
        "  listed but still written: %s"
        % (
            sorted((everything - kept) - set(config.NOT_PERSISTED)),
            sorted(set(config.NOT_PERSISTED) - (everything - kept)),
        )
    )


def test_excluded_settings_are_absent_from_the_saved_file(config_module, tmp_path):
    """The exclusions must not reach disk at all, not merely be ignored on load."""

    config = config_module
    target = tmp_path / "config.json"
    assert config.saveConfig(str(target))
    written = json.loads(target.read_text())

    for path in config.NOT_PERSISTED:
        node = written
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        assert node is None, "%s was written to the settings file" % path


def test_corrupt_settings_file_does_not_prevent_startup(config_module, tmp_path, monkeypatch):
    """An unreadable config.json must fall back to defaults, not stop startup."""

    config = config_module
    baseline = config._snapshotSections()
    default_width = config.main["appWidth"]

    confdir = tmp_path / "confdir"
    confdir.mkdir()
    (confdir / config.CONFIG_FILENAME).write_text('{"main": {"appWidth": 4321')  # truncated
    monkeypatch.setattr(config, "confdir", str(confdir))

    config._restoreSections(baseline)
    config._initialize_runtime_config()  # must not raise

    assert config.main["appWidth"] == default_width
    assert (confdir / (config.CONFIG_FILENAME + ".corrupt")).exists(), (
        "the unreadable file must be kept for the user to recover"
    )
    # a fresh, readable settings file takes its place
    config.loadConfig(str(confdir / config.CONFIG_FILENAME))


def test_corrupt_legacy_xml_does_not_prevent_startup(config_module, tmp_path, monkeypatch):
    """A damaged pre-7.0 config.xml must not stop startup either.

    Migration declines and leaves the XML in place so a later release (or a
    repaired file) can still be migrated, rather than discarding it.
    """

    config = config_module
    baseline = config._snapshotSections()
    default_width = config.main["appWidth"]

    confdir = tmp_path / "confdir"
    confdir.mkdir()
    legacy = confdir / config.LEGACY_CONFIG_FILENAME
    legacy.write_text("<mMassConfig><main><param name=")  # truncated
    monkeypatch.setattr(config, "confdir", str(confdir))

    config._restoreSections(baseline)
    config._initialize_runtime_config()  # must not raise

    assert config.main["appWidth"] == default_width
    assert legacy.exists(), "an unmigratable config.xml must be left alone"


LEGACY_XML = """<?xml version="1.0" encoding="utf-8" ?>
<mMassConfig version="1.0">
  <main>
    <param name="appWidth" value="1972" type="int" />
    <param name="mzDigits" value="3" type="int" />
    <param name="lastDir" value="/data/runs" type="unicode" />
    <param name="cursorInfo" value="mz;dist;ppm;z;area" type="str" />
    <param name="peaklistColumns" value="mz;int;rel;sn" type="str" />
  </main>
  <recent>
    <path value="/data/a.msd" />
    <path value="/data/b.msd" />
  </recent>
  <colours>
    <colour value="1047b9" />
    <colour value="328c00" />
  </colours>
  <spectrum>
    <param name="tickColour" value="ff4b4b" type="str" />
  </spectrum>
  <processing>
    <deisotoping>
      <param name="maxCharge" value="3" type="int" />
      <param name="envelopeNonIdeality" value="0.75" type="float" />
    </deisotoping>
  </processing>
  <prospector>
    <msfit>
      <param name="proteinMassHigh" value="300" type="unicode" />
    </msfit>
  </prospector>
</mMassConfig>
"""


def test_legacy_xml_is_migrated_once_and_kept(config_module, tmp_path, monkeypatch):
    """config.xml becomes config.json, with the XML renamed aside, not deleted."""

    config = config_module
    baseline = config._snapshotSections()

    confdir = tmp_path / "confdir"
    confdir.mkdir()
    (confdir / config.LEGACY_CONFIG_FILENAME).write_text(LEGACY_XML)
    monkeypatch.setattr(config, "confdir", str(confdir))

    config._restoreSections(baseline)
    config._initialize_runtime_config()

    assert (confdir / config.CONFIG_FILENAME).exists()
    assert (confdir / (config.LEGACY_CONFIG_FILENAME + ".migrated")).exists(), (
        "the original config.xml must be kept, not deleted"
    )
    assert not (confdir / config.LEGACY_CONFIG_FILENAME).exists()

    # values carried across, with the XML-only encodings decoded
    assert config.main["appWidth"] == 1972
    assert config.main["mzDigits"] == 3
    assert config.main["lastDir"] == "/data/runs"
    assert config.main["cursorInfo"] == ["mz", "dist", "ppm", "z", "area"]
    assert config.main["peaklistColumns"] == ["mz", "int", "rel", "sn"]
    assert list(config.recent) == ["/data/a.msd", "/data/b.msd"]
    assert list(config.colours[0]) == [16, 71, 185]
    assert list(config.spectrum["tickColour"]) == [255, 75, 75]
    assert config.processing["deisotoping"]["maxCharge"] == 3
    assert config.processing["deisotoping"]["envelopeNonIdeality"] == 0.75

    # the XML writer emitted several numeric fields as type="unicode", so they
    # came back as strings and `value * 1000` silently built a 3000-character
    # string instead of multiplying. The declared default is numeric; migration
    # restores that.
    assert config.prospector["msfit"]["proteinMassHigh"] == 300
    assert config.prospector["msfit"]["proteinMassHigh"] * 1000 == 300000

    # a second startup must not re-migrate
    assert config.migrateLegacyConfigXML() is False


def test_unknown_keys_dropped_and_new_settings_keep_defaults(config_module, tmp_path):
    """Merge semantics: unknown keys ignored, absent keys keep their default."""

    config = config_module
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps(
            {
                "schemaVersion": config.CONFIG_SCHEMA_VERSION,
                "main": {"mzDigits": 5, "aRetiredSetting": 123},
                "notASection": {"x": 1},
            }
        )
    )

    default_int_digits = config.main["intDigits"]
    config.loadConfig(str(target))

    assert config.main["mzDigits"] == 5, "stored value must win"
    assert "aRetiredSetting" not in config.main, "unknown key must not be kept"
    assert config.main["intDigits"] == default_int_digits, (
        "a setting absent from the file must keep its in-code default"
    )


def test_atomic_write_leaves_no_partial_file(config_module, tmp_path):
    """write_file_atomically must not leave a temp file or a truncated target."""

    config = config_module
    target = tmp_path / "thing.xml"
    target.write_bytes(b"original contents")

    assert config.write_file_atomically(str(target), b"replacement")
    assert target.read_bytes() == b"replacement"
    assert list(tmp_path.iterdir()) == [target], "temp file left behind"


def test_atomic_write_follows_symlinks(config_module, tmp_path):
    """Writing a symlinked config must update the target, not replace the link.

    A user may point references.xml (or any config) at shared or external
    storage. os.replace() onto the link path would swap the LINK for a regular
    file and silently detach that setup.
    """

    config = config_module
    target = tmp_path / "elsewhere.xml"
    target.write_bytes(b"original")
    link = tmp_path / "linked.xml"
    link.symlink_to(target)

    assert config.write_file_atomically(str(link), b"updated")

    assert link.is_symlink(), "the symlink was replaced by a regular file"
    assert target.read_bytes() == b"updated", "the link target was not updated"
