# -------------------------------------------------------------------------
#     Copyright (C) 2005-2013 Martin Strohalm <www.mmass.org>

#     This program is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 3 of the License, or
#     (at your option) any later version.

#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#     GNU General Public License for more details.

#     Complete text of GNU GPL can be found in the file LICENSE.TXT in the
#     main directory of the program.
# -------------------------------------------------------------------------

"""Session (workspace) serialization.

A session records which documents are open, how each of them is displayed and
where the spectrum view is zoomed to, so a whole working set can be reopened in
one step. Document *contents* are never stored here -- only paths -- so every
document must be saved to disk before a session is written.

Since document paths are just references, a session can outlive the files it
points at (moved, renamed, on an unmounted volume). Restoring therefore never
assumes a path resolves: see resolveDocumentPath, and the caller is expected to
report whatever could not be found instead of failing the whole restore.

This module deliberately imports neither wx nor gui.config so the format stays
testable headless.
"""

# load libs
import os.path
import xml.dom.minidom

# SESSION FORMAT
# --------------

SESSION_VERSION = "1.0"
SESSION_EXTENSION = ".mses"
SESSION_WILDCARD = "mMass Session|*.mses"

# document display defaults, used for both missing attributes and new sessions
DOCUMENT_DEFAULTS = {
    "path": "",
    "title": "",
    "visible": True,
    "flipped": False,
    "offset": [0.0, 0.0],
    "colour": None,  # None -> keep the colour assigned on open
    "style": None,  # None -> keep the document's default line style
    "scan": None,  # current scan ID of an LC-MS document, as text
}


def makeSession(documents, currentDocument=None, xRange=None, yRange=None):
    """Build a session dict from document dicts and the current view.

    documents -- sequence of dicts holding a subset of DOCUMENT_DEFAULTS keys
    """

    docs = []
    for item in documents:
        entry = dict(DOCUMENT_DEFAULTS)
        entry.update(item)
        docs.append(entry)

    return {
        "version": SESSION_VERSION,
        "currentDocument": currentDocument,
        "xRange": _floatPair(xRange),
        "yRange": _floatPair(yRange),
        "documents": docs,
    }


# ----


def makeSessionXML(session):
    """Format session dict as mMass session XML."""

    buff = '<?xml version="1.0" encoding="utf-8" ?>\n'
    buff += '<mMassSession version="%s">\n\n' % _escape(SESSION_VERSION)

    # view
    view = ""
    xRange = _floatPair(session.get("xRange"))
    yRange = _floatPair(session.get("yRange"))
    if xRange:
        view += ' xMin="%f" xMax="%f"' % (xRange[0], xRange[1])
    if yRange:
        view += ' yMin="%f" yMax="%f"' % (yRange[0], yRange[1])
    buff += "  <view%s />\n\n" % view

    # documents
    current = session.get("currentDocument")
    if current is None:
        buff += "  <documents>\n"
    else:
        buff += '  <documents current="%d">\n' % int(current)

    for item in session.get("documents", []):
        entry = dict(DOCUMENT_DEFAULTS)
        entry.update(item)

        attrs = '      path="%s"\n' % _escape(entry["path"])
        attrs += '      title="%s"\n' % _escape(entry["title"])
        attrs += '      visible="%d"\n' % bool(entry["visible"])
        attrs += '      flipped="%d"\n' % bool(entry["flipped"])

        offset = _floatPair(entry["offset"]) or (0.0, 0.0)
        attrs += '      offsetX="%f"\n' % offset[0]
        attrs += '      offsetY="%f"' % offset[1]

        if entry["colour"] is not None:
            attrs += '\n      colour="%s"' % _colourToHex(entry["colour"])
        if entry["style"] is not None:
            attrs += '\n      style="%d"' % int(entry["style"])
        if entry["scan"] is not None:
            attrs += '\n      scan="%s"' % _escape(entry["scan"])

        buff += "    <document\n%s\n    />\n" % attrs

    buff += "  </documents>\n\n"
    buff += "</mMassSession>"

    return buff


# ----


def parseSessionXML(text):
    """Parse mMass session XML and return a session dict.

    Raises ValueError if the data is not an mMass session; individual malformed
    attributes are ignored in favour of the defaults, so a session written by a
    newer/older build still opens as far as it can be understood.
    """

    try:
        document = xml.dom.minidom.parseString(text)
    except Exception as e:
        raise ValueError("Session data cannot be parsed.") from e

    rootTags = document.getElementsByTagName("mMassSession")
    if not rootTags:
        raise ValueError("Data is not an mMass session.")
    root = rootTags[0]

    session = {
        "version": root.getAttribute("version") or "",
        "currentDocument": None,
        "xRange": None,
        "yRange": None,
        "documents": [],
    }

    # view
    viewTags = root.getElementsByTagName("view")
    if viewTags:
        view = viewTags[0]
        session["xRange"] = _floatPair(
            (_getFloat(view, "xMin"), _getFloat(view, "xMax"))
        )
        session["yRange"] = _floatPair(
            (_getFloat(view, "yMin"), _getFloat(view, "yMax"))
        )

    # documents
    documentsTags = root.getElementsByTagName("documents")
    if not documentsTags:
        return session

    session["currentDocument"] = _getInt(documentsTags[0], "current")

    for documentTag in documentsTags[0].getElementsByTagName("document"):
        path = documentTag.getAttribute("path")
        if not path:
            continue

        entry = dict(DOCUMENT_DEFAULTS)
        entry["path"] = path
        entry["title"] = documentTag.getAttribute("title") or os.path.splitext(
            os.path.basename(path)
        )[0]
        entry["visible"] = _getBool(documentTag, "visible", True)
        entry["flipped"] = _getBool(documentTag, "flipped", False)
        entry["offset"] = [
            _getFloat(documentTag, "offsetX") or 0.0,
            _getFloat(documentTag, "offsetY") or 0.0,
        ]
        entry["colour"] = _hexToColour(documentTag.getAttribute("colour"))
        entry["style"] = _getInt(documentTag, "style")
        entry["scan"] = documentTag.getAttribute("scan") or None

        session["documents"].append(entry)

    # a current index that no longer addresses a document is meaningless
    if session["currentDocument"] is not None and not (
        0 <= session["currentDocument"] < len(session["documents"])
    ):
        session["currentDocument"] = None

    return session


# ----


def parseSession(path):
    """Read and parse a session file."""

    with open(path, "rb") as f:
        text = f.read()

    return parseSessionXML(text.decode("utf-8", "replace"))


# ----


def saveSession(path, session):
    """Write session dict to a file as XML."""

    with open(path, "wb") as f:
        f.write(makeSessionXML(session).encode("utf-8"))


# ----


def resolveDocumentPath(path, sessionDir=None):
    """Locate a session document, or return None if it cannot be found.

    Sessions store absolute paths, but a whole working set is often moved or
    copied together with its session file. So if the stored path is gone, the
    same file name next to the session file counts as the same document.
    """

    if not path:
        return None

    if os.path.isfile(path):
        return path

    if sessionDir:
        candidate = os.path.join(sessionDir, os.path.basename(path))
        if os.path.isfile(candidate):
            return candidate

    return None


# ----


def resolveSession(session, sessionDir=None):
    """Split session documents into resolvable ones and missing ones.

    Returns (found, missing) where found is a list of document dicts with their
    'path' updated to where the file actually is, and missing is a list of the
    document dicts that could not be located (paths left as stored).
    """

    found = []
    missing = []
    for entry in session.get("documents", []):
        path = resolveDocumentPath(entry.get("path"), sessionDir)
        if path is None:
            missing.append(entry)
        else:
            resolved = dict(entry)
            resolved["path"] = path
            found.append(resolved)

    return found, missing


# HELPERS
# -------


def _escape(text):
    """Clear special characters such as <> etc."""

    search = ("&", '"', "'", "<", ">")
    replace = ("&amp;", "&quot;", "&#39;", "&lt;", "&gt;")
    text = str(text)
    for x, item in enumerate(search):
        text = text.replace(item, replace[x])

    return text


# ----


def _floatPair(value):
    """Convert a two-item sequence to a (float, float) tuple, else None."""

    if not value:
        return None

    try:
        first, second = value
        if first is None or second is None:
            return None
        return (float(first), float(second))
    except (TypeError, ValueError):
        return None


# ----


def _getFloat(element, name):
    """Get float attribute value or None."""

    try:
        return float(element.getAttribute(name))
    except (TypeError, ValueError):
        return None


# ----


def _getInt(element, name):
    """Get int attribute value or None."""

    try:
        return int(element.getAttribute(name))
    except (TypeError, ValueError):
        return None


# ----


def _getBool(element, name, default):
    """Get bool attribute value or default."""

    value = element.getAttribute(name)
    if value == "":
        return default

    try:
        return bool(int(value))
    except (TypeError, ValueError):
        pass

    value = value.lower()
    if value in ("true", "yes"):
        return True
    if value in ("false", "no"):
        return False

    return default


# ----


def _colourToHex(colour):
    """Format an (R,G,B) colour as a hex triplet."""

    return "%02X%02X%02X" % tuple(int(c) for c in tuple(colour)[:3])


# ----


def _hexToColour(value):
    """Parse a hex colour triplet into an [R,G,B] list, or None."""

    if not value or len(value) < 6:
        return None

    try:
        return [int(value[i : i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return None
