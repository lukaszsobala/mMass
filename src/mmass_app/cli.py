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


CONVERT_COMMAND = "convert"

# formats mmass convert writes, by the name --to takes (the file extension
# without its dot, lowercase), with the kind of output each one is
OUTPUT_FORMATS = {
    "msd": "mSD",
    "mzml": "mzML",
    "mzxml": "mzXML",
    "txt": "ASCII",
    "xy": "ASCII",
    "asc": "ASCII",
    "csv": "ASCII",
    "mgf": "MGF",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "tif": "image",
    "tiff": "image",
    "bmp": "image",
    "svg": "image",
}

# spelling of the extensions of converted files
OUTPUT_EXTENSIONS = {"msd": ".msd", "mzml": ".mzML", "mzxml": ".mzXML"}

# formats mMass reads but has no writer for, named for the error message
READ_ONLY_FORMATS = {
    "mzdata": "mzData",
    "xml": "mzData/mzXML/mzML with an .xml extension",
    "mses": "session",
    "fa": "FASTA",
    "fsa": "FASTA",
    "faa": "FASTA",
    "fasta": "FASTA",
}

DEFAULT_IMAGE_SIZE = (1920, 1080)
# an SVG is drawn at a fixed size: it scales without losing detail, and the
# size only sets the proportions and how large the text is relative to the plot
SVG_SIZE = (960, 540)
MAX_IMAGE_SIZE = 16000

SEPARATORS = {"tab": "\t", "comma": ",", "semicolon": ";"}


@dataclass
class StartupOptions:
    """What the GUI should open once its main window is up."""

    documents: list[str] = field(default_factory=list)
    session: str | None = None


@dataclass
class ConvertOptions:
    """What mmass convert should convert, and into what."""

    inputs: list[str]
    format: str
    output: str | None = None
    outputDir: str | None = None
    scan: str | None = None
    size: tuple[int, int] = DEFAULT_IMAGE_SIZE
    separator: str = "\t"
    dark: bool = False
    overwrite: bool = False

    @property
    def kind(self):
        return OUTPUT_FORMATS[self.format]


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
            "reopens its documents and view; other files are added to it. "
            f"To convert documents without opening the GUI, see 'mmass "
            f"{CONVERT_COMMAND} --help'."
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


def parse_size(value):
    """Parse an image size given as WIDTHxHEIGHT in pixels."""

    parts = value.lower().replace("×", "x").split("x")
    try:
        if len(parts) != 2:
            raise ValueError
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a size in pixels such as 1920x1080"
        ) from None

    if not (0 < width <= MAX_IMAGE_SIZE and 0 < height <= MAX_IMAGE_SIZE):
        raise argparse.ArgumentTypeError(
            f"image width and height must be between 1 and {MAX_IMAGE_SIZE} pixels"
        )
    return width, height


def output_extension(name):
    """Return the file extension mmass convert gives a format."""

    return OUTPUT_EXTENSIONS.get(name, "." + name)


def make_convert_parser():
    """Return the argument parser of the mmass convert command."""

    writable = ", ".join(OUTPUT_FORMATS)
    parser = argparse.ArgumentParser(
        prog=f"mmass {CONVERT_COMMAND}",
        description=(
            "Convert spectra to another format or draw them as images, "
            "without opening the GUI."
        ),
        epilog=(
            "Inputs are read like the GUI opens them: mzML, mzXML, mzData, MGF, "
            "mSD, XY/TXT/ASC, a Bruker fid file or dataset folder. Outputs: "
            f"{writable}. A file holding several spectra (an LC-MS run, an MGF "
            "or a Bruker folder of many acquisitions) is written whole to "
            "mzML, mzXML and, for LC-MS runs, msd; other outputs need one "
            "spectrum picked with --scan. Text outputs need profile data, "
            "MGF needs a peak list. Images use the spectrum settings of the "
            "GUI, e.g. labels and colours, on a light background."
        ),
    )
    parser.add_argument(
        "inputs", nargs="+", metavar="INPUT", help="documents to convert"
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="output file, its format given by the extension (one input only)",
    )
    target.add_argument(
        "-t",
        "--to",
        metavar="FORMAT",
        help=(
            "output format; each input is written beside it under the same "
            "name, or into --output-dir"
        ),
    )
    parser.add_argument(
        "-d",
        "--output-dir",
        metavar="DIR",
        help="folder to write --to outputs into (created if missing)",
    )
    parser.add_argument(
        "--scan",
        metavar="ID",
        help="the spectrum to convert from a file holding several",
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        metavar="WxH",
        help=(
            "raster image size in pixels (default: %dx%d); SVG images are "
            "vector graphics and ignore it" % DEFAULT_IMAGE_SIZE
        ),
    )
    parser.add_argument(
        "--dark", action="store_true", help="draw images on a dark background"
    )
    parser.add_argument(
        "--separator",
        choices=list(SEPARATORS),
        help="column separator of text outputs (default: comma for csv, tab otherwise)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace outputs that already exist"
    )
    return parser


def parse_convert_args(argv):
    """Parse and check mmass convert arguments into ConvertOptions.

    Everything that can be told from the arguments alone is checked here, so
    an impossible request fails before any file is read or written.
    """

    parser = make_convert_parser()
    # inputs may follow options, as in: mmass convert -t png *.mzML more.msd
    args = parser.parse_intermixed_args(argv)

    # output format
    if args.output:
        if len(args.inputs) > 1:
            parser.error("--output takes one input; use --to for several")
        if args.output_dir:
            parser.error("--output-dir works with --to; give --output a full path")
        name = os.path.splitext(args.output)[1].lower().lstrip(".")
        if os.path.basename(args.output).lower() == "fid":
            name = "fid"
        what = f"output file {args.output}"
    else:
        name = args.to.lower().lstrip(".")
        what = f"format '{args.to}'"

    if name not in OUTPUT_FORMATS:
        if name == "fid":
            parser.error("mMass reads Bruker fid data but cannot write it")
        if name in READ_ONLY_FORMATS:
            parser.error(
                f"mMass reads {READ_ONLY_FORMATS[name]} files but cannot write "
                f"them ({what}); write one of: {', '.join(OUTPUT_FORMATS)}"
            )
        if not name:
            parser.error(f"{what} has no extension to tell its format from")
        parser.error(
            f"unknown {what}; write one of: {', '.join(OUTPUT_FORMATS)}"
        )
    kind = OUTPUT_FORMATS[name]

    # inputs
    missing = [path for path in args.inputs if not os.path.exists(path)]
    for path in missing:
        warn(f"no such file or folder: {path}")
    if missing:
        parser.error("inputs not found")

    if args.output_dir and os.path.exists(args.output_dir):
        if not os.path.isdir(args.output_dir):
            parser.error(f"--output-dir {args.output_dir} is not a folder")

    # options that do not apply to this output
    size = args.size
    if size is not None and (kind != "image" or name == "svg"):
        warn(f"--size does not apply to {name} output, ignoring it")
    if size is None or name == "svg":
        size = SVG_SIZE if name == "svg" else DEFAULT_IMAGE_SIZE
    if args.dark and kind != "image":
        warn(f"--dark does not apply to {name} output, ignoring it")
    if args.separator and kind != "ASCII":
        warn(f"--separator does not apply to {name} output, ignoring it")
    separator = args.separator or ("comma" if name == "csv" else "tab")

    return ConvertOptions(
        inputs=[os.path.abspath(path) for path in args.inputs],
        format=name,
        output=os.path.abspath(args.output) if args.output else None,
        outputDir=os.path.abspath(args.output_dir) if args.output_dir else None,
        scan=args.scan,
        size=size,
        separator=SEPARATORS[separator],
        dark=args.dark,
        overwrite=args.overwrite,
    )
