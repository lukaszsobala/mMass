"""Tests for session (workspace) serialization -- gui.session.

The module is deliberately wx-free so these run headless like the rest of the
suite.
"""

import os

import pytest

session = pytest.importorskip("gui.session")


def _entry(path, **kwargs):
    entry = {
        "path": path,
        "title": os.path.splitext(os.path.basename(path))[0],
        "visible": True,
        "flipped": False,
        "offset": [0.0, 0.0],
        "colour": [0, 0, 255],
        "style": 100,
    }
    entry.update(kwargs)
    return entry


def test_session_roundtrip_preserves_documents_and_view():
    """Everything the session promises to remember survives write + read."""

    data = session.makeSession(
        documents=[
            _entry("/data/one.msd", colour=[255, 0, 0], style=101),
            _entry(
                "/data/two.msd",
                visible=False,
                flipped=True,
                offset=[1.5, -2.25],
                scan="42",
            ),
        ],
        currentDocument=1,
        xRange=(800.0, 1200.5),
        yRange=(0.0, 1000.0),
    )

    parsed = session.parseSessionXML(session.makeSessionXML(data))

    assert parsed["currentDocument"] == 1
    assert parsed["xRange"] == (800.0, 1200.5)
    assert parsed["yRange"] == (0.0, 1000.0)
    assert len(parsed["documents"]) == 2

    first, second = parsed["documents"]
    assert first["path"] == "/data/one.msd"
    assert first["colour"] == [255, 0, 0]
    assert first["style"] == 101
    assert first["visible"] is True
    assert first["scan"] is None

    assert second["visible"] is False
    assert second["flipped"] is True
    assert second["offset"] == [1.5, -2.25]
    assert second["scan"] == "42"


def test_session_roundtrip_escapes_special_characters():
    """Paths and titles with XML-special characters survive intact."""

    path = "/data/a & b <test>/'quoted' \"name\".msd"
    data = session.makeSession(documents=[_entry(path, title='He said "hi" & left')])

    parsed = session.parseSessionXML(session.makeSessionXML(data))

    assert parsed["documents"][0]["path"] == path
    assert parsed["documents"][0]["title"] == 'He said "hi" & left'


def test_session_file_roundtrip(tmp_path):
    """saveSession / parseSession go through the filesystem as UTF-8."""

    path = str(tmp_path / "work.mses")
    data = session.makeSession(
        documents=[_entry("/data/ångström.msd")], xRange=(0.0, 10.0)
    )
    session.saveSession(path, data)

    parsed = session.parseSession(path)
    assert parsed["documents"][0]["path"] == "/data/ångström.msd"
    assert parsed["xRange"] == (0.0, 10.0)


def test_session_without_view_parses():
    """A session saved before any spectrum was drawn has no stored ranges."""

    data = session.makeSession(documents=[_entry("/data/one.msd")])
    parsed = session.parseSessionXML(session.makeSessionXML(data))

    assert parsed["xRange"] is None
    assert parsed["yRange"] is None
    assert parsed["currentDocument"] is None


def test_parse_rejects_foreign_xml():
    """An mSD document (or any other XML) is not silently accepted."""

    with pytest.raises(ValueError):
        session.parseSessionXML('<?xml version="1.0" ?><mSD version="2.0"></mSD>')

    with pytest.raises(ValueError):
        session.parseSessionXML("this is not xml at all")


def test_parse_tolerates_unknown_and_malformed_attributes():
    """Unreadable attributes fall back to defaults instead of failing."""

    xml = (
        '<?xml version="1.0" ?>\n'
        '<mMassSession version="9.9">\n'
        '  <view xMin="junk" xMax="500" />\n'
        '  <documents current="7">\n'
        '    <document path="/data/one.msd" visible="maybe" style="x"'
        ' colour="zzzzzz" future="1" />\n'
        "    <document />\n"
        "  </documents>\n"
        "</mMassSession>"
    )

    parsed = session.parseSessionXML(xml)

    # a document without a path cannot be reopened, so it is dropped
    assert len(parsed["documents"]) == 1
    entry = parsed["documents"][0]
    assert entry["title"] == "one"  # derived from the file name
    assert entry["visible"] is True  # unreadable -> default
    assert entry["style"] is None
    assert entry["colour"] is None
    assert parsed["xRange"] is None  # incomplete -> no range
    # a current index pointing past the end of the list is dropped
    assert parsed["currentDocument"] is None


def test_resolve_session_reports_missing_documents(tmp_path):
    """Present files resolve; absent ones are reported, not raised."""

    present = tmp_path / "here.msd"
    present.write_text("x")

    data = session.makeSession(
        documents=[
            _entry(str(present)),
            _entry(str(tmp_path / "gone.msd")),
        ]
    )

    found, missing = session.resolveSession(data, str(tmp_path))

    assert [e["path"] for e in found] == [str(present)]
    assert [e["path"] for e in missing] == [str(tmp_path / "gone.msd")]


def test_resolve_finds_documents_moved_with_the_session(tmp_path):
    """A session copied together with its spectra still opens them."""

    moved = tmp_path / "spectrum.msd"
    moved.write_text("x")

    resolved = session.resolveDocumentPath(
        "/somewhere/that/never/existed/spectrum.msd", str(tmp_path)
    )
    assert resolved == str(moved)

    # without the session folder there is nothing to fall back to
    assert (
        session.resolveDocumentPath("/somewhere/that/never/existed/spectrum.msd")
        is None
    )


def test_resolve_keeps_extra_entry_keys(tmp_path):
    """Caller-added keys (e.g. the session index) survive resolution."""

    present = tmp_path / "here.msd"
    present.write_text("x")

    data = session.makeSession(documents=[_entry(str(present))])
    data["documents"][0]["sessionIndex"] = 3

    found, missing = session.resolveSession(data, str(tmp_path))

    assert not missing
    assert found[0]["sessionIndex"] == 3
