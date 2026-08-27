"""Round-trip and migration coverage for the JSON library files.

The seven libraries (monomers, modifications, enzymes, presets, references,
compounds, mascot) moved from hand-written XML to JSON in 7.0. These tests
cover both directions: values written by the editors must survive a save/load
cycle, and a pre-7.0 XML library must migrate into the JSON one without loss.
"""

import json
import os

import pytest

mspy = pytest.importorskip("mspy")


@pytest.fixture(autouse=True)
def pristine_libraries():
    """Snapshot and restore the global libraries around every test.

    mspy keeps its libraries in module-level dicts, and these tests reload them
    with clear=True. Without a restore, the "_InternalAA" residues that
    saveMonomers deliberately omits would stay missing and every later
    digestion/fragmentation test in the session would fail.
    """

    saved = {
        "monomers": dict(mspy.monomers),
        "enzymes": dict(mspy.enzymes),
        "modifications": dict(mspy.modifications),
    }
    try:
        yield
    finally:
        for name, entries in saved.items():
            library = getattr(mspy, name)
            library.clear()
            library.update(entries)


@pytest.fixture
def libs_modules():
    """gui.libs + gui.config, or skip when wxPython is unavailable."""

    try:
        from gui import config, libs
    except Exception:
        pytest.skip("gui.libs not importable in this environment")
    return config, libs


def _monomerRows():
    return {
        abbr: (item.abbr, item.name, item.formula, item.category, tuple(item.losses))
        for abbr, item in mspy.monomers.items()
        if item.category != "_InternalAA"
    }


def test_monomers_round_trip(tmp_path):
    """A custom monomer, losses included, survives save -> load."""

    target = str(tmp_path / "monomers.json")
    mspy.monomers["ZzTest"] = mspy.monomer(
        abbr="ZzTest",
        formula="C2H3NO",
        losses=["H2O", "NH3"],
        name="test residue <&>",
        category="Custom",
    )
    try:
        before = _monomerRows()
        assert mspy.saveMonomers(target)
        mspy.loadMonomers(target, clear=True, replace=True)
        assert _monomerRows() == before
        assert list(mspy.monomers["ZzTest"].losses) == ["H2O", "NH3"]
    finally:
        mspy.monomers.pop("ZzTest", None)


def test_enzymes_round_trip(tmp_path):
    """modsBefore/modsAfter are booleans and must not be flattened."""

    target = str(tmp_path / "enzymes.json")
    mspy.enzymes["ZzCutter"] = mspy.enzyme(
        name="ZzCutter",
        expression="[KR]",
        nTermFormula="H",
        cTermFormula="OH",
        modsBefore=False,
        modsAfter=True,
    )
    try:
        assert mspy.saveEnzymes(target)
        mspy.loadEnzymes(target, clear=True)
        loaded = mspy.enzymes["ZzCutter"]
        assert loaded.expression == "[KR]"
        assert loaded.modsBefore is False
        assert loaded.modsAfter is True
    finally:
        mspy.enzymes.pop("ZzCutter", None)


def test_modifications_round_trip(tmp_path):
    """Characters that needed XML escaping must come back verbatim."""

    target = str(tmp_path / "modifications.json")
    mspy.modifications["ZzMod"] = mspy.modification(
        name="ZzMod",
        gainFormula="CH2",
        lossFormula="H",
        aminoSpecifity="ST",
        termSpecifity="N",
        description='angle <brackets> & "quotes"',
    )
    try:
        assert mspy.saveModifications(target)
        mspy.loadModifications(target, clear=True)
        assert mspy.modifications["ZzMod"].description == 'angle <brackets> & "quotes"'
    finally:
        mspy.modifications.pop("ZzMod", None)


def test_references_keep_full_mass_precision(tmp_path, libs_modules):
    """The XML writer rounded masses with %f; JSON must keep them exactly."""

    config, libs = libs_modules
    target = str(tmp_path / "references.json")
    mass = 1234.5678901234
    libs.references["ZzRefs"] = [("peak <one>", mass)]
    try:
        assert libs.saveReferences(target)
        libs.loadReferences(target)
        assert libs.references["ZzRefs"][0] == ("peak <one>", mass)
    finally:
        libs.references.pop("ZzRefs", None)


def test_compounds_round_trip(tmp_path, libs_modules):
    config, libs = libs_modules
    target = str(tmp_path / "compounds.json")
    compound = mspy.compound("C6H12O6")
    compound.description = "glucose & friends"
    libs.compounds["ZzGroup"] = {"ZzCompound": compound}
    try:
        assert libs.saveCompounds(target)
        libs.loadCompounds(target)
        loaded = libs.compounds["ZzGroup"]["ZzCompound"]
        assert loaded.expression == "C6H12O6"
        assert loaded.description == "glucose & friends"
    finally:
        libs.compounds.pop("ZzGroup", None)


def test_presets_round_trip(tmp_path, libs_modules):
    """Processing presets are nested dicts; the JSON form keeps their shape."""

    config, libs = libs_modules
    target = str(tmp_path / "presets.json")
    libs.presets["operator"]["ZzOp"] = {
        "operator": "me",
        "contact": "c",
        "institution": "i",
        "instrument": "inst",
    }
    libs.presets["fragments"]["ZzFrag"] = ["a", "b", "y"]
    libs.presets["modifications"]["ZzMods"] = [["Acetyl", "nTerm", "fixed"]]
    try:
        assert libs.savePresets(target)
        libs.loadPresets(target)
        assert libs.presets["operator"]["ZzOp"]["operator"] == "me"
        assert libs.presets["fragments"]["ZzFrag"] == ["a", "b", "y"]
        assert libs.presets["modifications"]["ZzMods"] == [
            ["Acetyl", "nTerm", "fixed"]
        ]
    finally:
        for group in ("operator", "fragments", "modifications"):
            libs.presets[group].pop("ZzOp", None)
            libs.presets[group].pop("ZzFrag", None)
            libs.presets[group].pop("ZzMods", None)


LEGACY_MONOMERS_XML = """<?xml version="1.0" encoding="utf-8" ?>
<mspyMonomers version="1.0">
  <monomer abbr="ZzOld" name="legacy residue" formula="C2H3NO" category="Custom" losses="H2O;NH3" />
</mspyMonomers>
"""


def test_legacy_library_is_migrated_once_and_kept(tmp_path, libs_modules, monkeypatch):
    """monomers.xml becomes monomers.json, with the XML renamed, not deleted."""

    config, libs = libs_modules
    monkeypatch.setattr(config, "confdir", str(tmp_path))
    (tmp_path / "monomers.xml").write_text(LEGACY_MONOMERS_XML)

    try:
        migrated = config.migrateLegacyLibrary(
            "monomers",
            lambda path: mspy.loadMonomersXML(path, clear=True),
            mspy.saveMonomers,
        )
        assert migrated is True
        assert (tmp_path / "monomers.json").exists()
        assert (tmp_path / "monomers.xml.migrated").exists(), (
            "the original library must be kept, not deleted"
        )
        assert not (tmp_path / "monomers.xml").exists()

        stored = json.loads((tmp_path / "monomers.json").read_text())
        entry = stored["monomers"]["ZzOld"]
        assert entry["formula"] == "C2H3NO"
        # ";"-joined in XML, a real array in JSON
        assert entry["losses"] == ["H2O", "NH3"]

        # a second startup must not re-migrate
        assert (
            config.migrateLegacyLibrary(
                "monomers",
                lambda path: mspy.loadMonomersXML(path, clear=True),
                mspy.saveMonomers,
            )
            is False
        )
    finally:
        mspy.monomers.pop("ZzOld", None)


def test_migration_does_not_clobber_an_existing_json(tmp_path, libs_modules, monkeypatch):
    """If the JSON already exists, the XML must be left completely alone."""

    config, libs = libs_modules
    monkeypatch.setattr(config, "confdir", str(tmp_path))
    (tmp_path / "monomers.xml").write_text(LEGACY_MONOMERS_XML)
    (tmp_path / "monomers.json").write_text('{"schemaVersion": 1, "monomers": {}}')

    assert (
        config.migrateLegacyLibrary(
            "monomers",
            lambda path: mspy.loadMonomersXML(path, clear=True),
            mspy.saveMonomers,
        )
        is False
    )
    assert (tmp_path / "monomers.xml").exists()
    assert json.loads((tmp_path / "monomers.json").read_text())["monomers"] == {}


def test_bundled_defaults_are_json_and_complete(libs_modules):
    """Every library ships a bundled JSON default and no stale XML."""

    config, libs = libs_modules
    bundled = config.get_default_config_source_dir()
    present = set(os.listdir(bundled))

    for name in config.LIBRARY_NAMES:
        assert name + ".json" in present, "missing bundled default: %s.json" % name

    assert not [f for f in present if f.endswith(".xml")], (
        "bundled XML defaults should have been removed: %s"
        % sorted(f for f in present if f.endswith(".xml"))
    )


def test_migration_keeps_the_internal_amino_acids(tmp_path, libs_modules, monkeypatch):
    """Migrating monomers.xml must not drop mspy's built-in residues.

    saveMonomers() deliberately omits the "_InternalAA" category, so migrating
    with clear=True would wipe those residues from the live library and they
    would never come back from the migrated file -- breaking every digestion
    and fragmentation afterwards.
    """

    config, libs = libs_modules
    internal_before = {
        abbr for abbr, item in mspy.monomers.items() if item.category == "_InternalAA"
    }
    assert internal_before, "expected mspy to define internal amino acids"

    monkeypatch.setattr(config, "confdir", str(tmp_path))
    (tmp_path / "monomers.xml").write_text(LEGACY_MONOMERS_XML)

    assert config.migrateLegacyLibrary(
        "monomers",
        libs._XML_LOADERS["monomers"],
        mspy.saveMonomers,
    )
    mspy.loadMonomers(config.getLibraryPath("monomers"), clear=False)

    internal_after = {
        abbr for abbr, item in mspy.monomers.items() if item.category == "_InternalAA"
    }
    assert internal_after == internal_before, "migration dropped internal residues"
    assert "ZzOld" in mspy.monomers, "the user's own monomer must be carried over"
