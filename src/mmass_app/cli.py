"""Command-line arguments of the mMass launcher.

This module must not import wxPython or the GUI modules: it is parsed before
the GUI starts and is tested headless.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field

# gui.session.SESSION_EXTENSION, repeated here because importing the gui
# package would load the user's config as a side effect
SESSION_EXTENSION = ".mses"

# field codes a desktop launcher passes on verbatim when it does not expand
# them (seen with Wine desktop integrations)
LAUNCHER_PLACEHOLDERS = {"%f", "%F", "%u", "%U", "%i", "%c", "%k"}


@dataclass
class StartupOptions:
    """What the GUI should open once its main window is up."""

    documents: list[str] = field(default_factory=list)
    session: str | None = None


def get_version():
    """Return the installed mMass version."""

    try:
        import importlib.metadata

        return importlib.metadata.version("mmass")
    except Exception:
        return "unknown"


def make_parser():
    """Return the argument parser of the mmass command."""

    parser = argparse.ArgumentParser(
        prog="mmass",
        description="mMass - Open Source Mass Spectrometry Tool.",
        epilog=(
            "FILE can be an mzML, mzXML, mzData, MGF, mSD or XY/TXT/ASC "
            "spectrum, a Bruker fid file or dataset folder, or a FASTA file "
            f"(its sequences are imported). A session file ({SESSION_EXTENSION}) "
            "reopens its documents and view; other files are added to it."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="FILE",
        help="documents or a session to open at startup",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {get_version()}"
    )
    return parser


def warn(message):
    """Print a warning for a user starting mMass from a terminal."""

    print(f"mmass: warning: {message}", file=sys.stderr)


def collect_paths(items):
    """Sort path arguments into StartupOptions.

    Unexpanded launcher placeholders are dropped silently; missing paths and
    extra sessions are reported on stderr and skipped.
    """

    options = StartupOptions()
    for item in items:
        candidate = item.strip().strip('"')
        if not candidate or candidate in LAUNCHER_PLACEHOLDERS:
            continue
        if not os.path.exists(candidate):
            warn(f"no such file or folder: {candidate}")
            continue

        # absolute, so the recent-files list and saved sessions stay valid
        path = os.path.abspath(candidate)
        if path.lower().endswith(SESSION_EXTENSION):
            if options.session is None:
                options.session = path
            else:
                warn(f"only one session can be opened, ignoring {candidate}")
        else:
            options.documents.append(path)

    return options


def parse_args(argv=None):
    """Parse launcher arguments into StartupOptions.

    Exits for --help and --version. Nothing else stops the GUI from starting,
    since a user starting mMass from a desktop launcher would never see the
    error: unknown options are reported on stderr and ignored.
    """

    if argv is None:
        argv = sys.argv[1:]

    args, unknown = make_parser().parse_known_args(argv)
    for item in unknown:
        # older macOS Finder launches add a process serial number
        if not item.startswith("-psn_"):
            warn(f"ignoring unknown option {item}")

    return collect_paths(args.paths)
