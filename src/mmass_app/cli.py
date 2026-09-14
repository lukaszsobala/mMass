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
PROCESS_COMMAND = "process"

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

SEPARATORS = {"tab": "\t", "comma": ",", "semicolon": ";", "space": " "}

# gui.doc.PEAKLIST_COLUMNS names, repeated for the same reason as above
PEAKLIST_COLUMNS = (
    "mz", "ai", "base", "int", "rel", "sn", "z", "mass", "fwhm", "resol",
    "envarea", "envint", "group",
)

# processing steps of mmass process, by option name: (help, what they change
# -- the "profile", the "peaks" or "both")
STEPS = {
    "crop": ("keep only the m/z range LOW:HIGH", "both"),
    "baseline": ("subtract the baseline", "profile"),
    "smooth": ("smooth the profile", "profile"),
    "findpeaks": (
        "find peaks, deisotoping them if the peak picking settings say so",
        "peaks",
    ),
    "deisotope": ("find isotopes and charges of the peaks", "peaks"),
    "math": (
        "apply a math operation to the profile and the peaks: normalize "
        "(scale to a maximum of 100 %%), multiply (by the math.multiplier "
        "setting) or squareroot (or sqrt)",
        "both",
    ),
}

# gui.processing.SINGLE_SPECTRUM_MATH, repeated for the same reason as above
MATH_OPERATIONS = ("normalize", "multiply", "squareroot")
# shorter names --math also takes
MATH_ALIASES = {"sqrt": "squareroot"}
# math operations of the GUI that take other spectra than the one processed
MULTI_SPECTRUM_MATH = (
    "combine", "overlay", "subtract", "averageall", "combineall", "overlayall",
)

# settings sections the steps use, which --set can change
SETTINGS_SECTIONS = ("math", "baseline", "smoothing", "peakpicking", "deisotoping")
# settings of those sections no step uses: the math operation is the step's
# argument, and no single-spectrum operation preserves peaks
UNUSED_SETTINGS = {"math.operation", "math.preservePeaks"}


@dataclass
class StartupOptions:
    """What the GUI should open once its main window is up."""

    documents: list[str] = field(default_factory=list)
    session: str | None = None


@dataclass
class ConvertOptions:
    """What mmass convert or mmass process should do, and what to write."""

    inputs: list[str]
    # the output format name; None when processing in place, where each
    # input keeps its own format
    format: str | None
    output: str | None = None
    outputDir: str | None = None
    scan: str | None = None
    size: tuple[int, int] = DEFAULT_IMAGE_SIZE
    separator: str = "\t"
    explicitSeparator: bool = False
    dark: bool = False
    overwrite: bool = False
    mzRange: tuple[float | None, float | None] | None = None
    peaklist: bool = False
    columns: list[str] | None = None
    # mmass process: [(step, argument)] in the order given, and the settings
    command: str = CONVERT_COMMAND
    steps: list[tuple[str, object]] = field(default_factory=list)
    inPlace: bool = False
    preset: str | None = None
    settings: list[tuple[str, str]] = field(default_factory=list)
    showSettings: bool = False

    @property
    def kind(self):
        return OUTPUT_FORMATS.get(self.format) if self.format else None


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
            f"{CONVERT_COMMAND} --help'; to process them, 'mmass "
            f"{PROCESS_COMMAND} --help'."
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


def _parse_mz_range(value, openEnded):
    parts = value.split(":")
    example = "400:1500" + (", 400: or :1500" if openEnded else "")
    try:
        if len(parts) != 2:
            raise ValueError
        low, high = (float(part) if part.strip() else None for part in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{value}' is not an m/z range such as {example}"
        ) from None

    if not openEnded and (low is None or high is None):
        raise argparse.ArgumentTypeError(
            f"'{value}' needs both ends of the m/z range, such as 400:1500"
        )
    if low is None and high is None:
        raise argparse.ArgumentTypeError(f"'{value}' is not an m/z range such as {example}")
    if low is not None and high is not None and low >= high:
        raise argparse.ArgumentTypeError(
            f"the m/z range {value} must go from the lower to the higher m/z"
        )
    return low, high


def parse_mz_range(value):
    """Parse an m/z range LOW:HIGH whose ends may be left out."""

    return _parse_mz_range(value, openEnded=True)


def parse_crop_range(value):
    """Parse an m/z range LOW:HIGH with both ends."""

    return _parse_mz_range(value, openEnded=False)


def parse_setting(value):
    """Parse a --set argument SECTION.KEY=VALUE into (SECTION.KEY, VALUE)."""

    key, equals, setting = value.partition("=")
    section, dot, name = key.strip().partition(".")
    if not equals or not dot or not section or not name:
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a setting such as peakpicking.snThreshold=10"
        )
    return f"{section}.{name}", setting.strip()


def parse_columns(value):
    """Parse a comma-separated list of peak list columns."""

    columns = [column.strip() for column in value.split(",") if column.strip()]
    unknown = [column for column in columns if column not in PEAKLIST_COLUMNS]
    if unknown or not columns:
        raise argparse.ArgumentTypeError(
            f"unknown peak list column {', '.join(unknown) or value!r}; choose "
            f"from {','.join(PEAKLIST_COLUMNS)}"
        )
    return columns


def parse_math(value):
    """Parse the operation of a --math step."""

    operation = value.strip().lower()
    operation = MATH_ALIASES.get(operation, operation)
    if operation in MULTI_SPECTRUM_MATH:
        raise argparse.ArgumentTypeError(
            f"'{value}' takes more spectra than the one processed; the command "
            f"line offers {', '.join(MATH_OPERATIONS)}"
        )
    if operation not in MATH_OPERATIONS:
        raise argparse.ArgumentTypeError(
            f"unknown math operation '{value}'; choose from "
            f"{', '.join(MATH_OPERATIONS + tuple(MATH_ALIASES))}"
        )
    return operation


class _StepAction(argparse.Action):
    """Collect processing steps in the order they are given."""

    def __call__(self, parser, namespace, values, option_string=None):
        steps = list(getattr(namespace, self.dest) or [])
        steps.append((self.const, values if values != [] else None))
        setattr(namespace, self.dest, steps)


def output_extension(name):
    """Return the file extension mmass convert gives a format."""

    return OUTPUT_EXTENSIONS.get(name, "." + name)


def stored_data(kind, peaklist):
    """What an output of a kind holds: {"profile", "peaks"} or a part of it."""

    if kind == "ASCII":
        return {"peaks"} if peaklist else {"profile"}
    if kind == "MGF":
        return {"peaks"}
    return {"profile", "peaks"}


def steps_problem(steps, kind, name, peaklist, inPlace=False):
    """Why the steps' results would not reach an output, or None.

    Profile steps are pointless for an output holding only peaks unless peaks
    are found after them; peak steps are lost on an output holding only the
    profile.
    """

    stored = stored_data(kind, peaklist)
    holder = f"a {name} file" if inPlace else f"{name} output"
    names = [step for step, _argument in steps]
    for index, step in enumerate(names):
        changes = STEPS[step][1]
        if changes == "peaks" and "peaks" not in stored:
            advice = (
                "write them with --to csv --peaklist or --to msd instead"
                if inPlace
                else "add --peaklist to write the peak list as text, or write msd"
            )
            return (
                f"{holder} holds only the profile, so the peaks --{step} finds "
                f"would be lost; {advice}"
            )
        if changes == "profile" and "profile" not in stored:
            if "findpeaks" not in names[index + 1:]:
                advice = "add --findpeaks after it" + (
                    "" if inPlace else ", or write msd or text"
                )
                return (
                    f"{holder} holds only the peak list, which --{step} does "
                    f"not change; {advice}"
                )
    return None


def make_convert_parser(command=CONVERT_COMMAND):
    """Return the argument parser of mmass convert or mmass process."""

    process = command == PROCESS_COMMAND
    writable = ", ".join(OUTPUT_FORMATS)
    inputs_epilog = (
        "Inputs are read like the GUI opens them: mzML, mzXML, mzData, MGF, "
        "mSD, XY/TXT/ASC, a Bruker fid file or dataset folder. Outputs: "
        f"{writable}. A file holding several spectra (an LC-MS run, an MGF "
        "or a Bruker folder of many acquisitions) is written whole to "
        "mzML, mzXML and, for LC-MS runs, msd; other outputs need one "
        "spectrum picked with --scan. Text outputs hold the profile, or the "
        "peak list with --peaklist; MGF holds the peak list. Images use the "
        "spectrum settings of the GUI, e.g. labels and colours, on a light "
        "background."
    )

    if process:
        parser = argparse.ArgumentParser(
            prog=f"mmass {PROCESS_COMMAND}",
            description=(
                "Process spectra without opening the GUI: run the steps in the "
                "order they are given, then write the result, or rewrite the "
                "inputs with --in-place."
            ),
            epilog=(
                "Steps use the settings of the Processing panel of the GUI, "
                "which --preset and --set change for this command only. Each "
                "input is processed on its own and written to its own output. "
                "In an LC-MS run written whole, every scan is processed, and "
                "peaks are found in pooled scans if the settings say so. "
                "--in-place rewrites msd, txt, xy, asc and single-spectrum mgf "
                "files; each is replaced only once it has been processed and "
                "written in full. " + inputs_epilog
            ),
        )
    else:
        parser = argparse.ArgumentParser(
            prog=f"mmass {CONVERT_COMMAND}",
            description=(
                "Convert spectra to another format or draw them as images, "
                "without opening the GUI."
            ),
            epilog=inputs_epilog
            + f" To process spectra as well, see 'mmass {PROCESS_COMMAND} --help'.",
        )

    parser.add_argument(
        "inputs",
        nargs="*" if process else "+",
        metavar="INPUT",
        help="documents to process" if process else "documents to convert",
    )

    if process:
        steps = parser.add_argument_group("steps, run in the order given")
        for step, (text, _changes) in STEPS.items():
            if step == "crop":
                steps.add_argument(
                    "--crop",
                    dest="steps",
                    action=_StepAction,
                    const=step,
                    type=parse_crop_range,
                    metavar="LOW:HIGH",
                    help=text,
                )
            elif step == "math":
                steps.add_argument(
                    "--math",
                    dest="steps",
                    action=_StepAction,
                    const=step,
                    type=parse_math,
                    metavar="OPERATION",
                    help=text,
                )
            else:
                steps.add_argument(
                    f"--{step}",
                    dest="steps",
                    action=_StepAction,
                    const=step,
                    nargs=0,
                    help=text,
                )

        settings = parser.add_argument_group("settings")
        settings.add_argument(
            "--preset",
            metavar="NAME",
            help=(
                "start from processing presets saved in the GUI; 'Default' "
                "gives the built-in settings, the same on every computer"
            ),
        )
        settings.add_argument(
            "--set",
            dest="settings",
            action="append",
            default=[],
            type=parse_setting,
            metavar="SECTION.KEY=VALUE",
            help="change one setting, e.g. peakpicking.snThreshold=10 (repeatable)",
        )
        settings.add_argument(
            "--show-settings",
            action="store_true",
            help="print the settings the steps would use, and exit",
        )

    outputs = parser.add_argument_group("output")
    target = outputs.add_mutually_exclusive_group(required=not process)
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
    if process:
        target.add_argument(
            "--in-place",
            action="store_true",
            help="replace each input with its processed version",
        )
    outputs.add_argument(
        "-d",
        "--output-dir",
        metavar="DIR",
        help="folder to write --to outputs into (created if missing)",
    )
    outputs.add_argument(
        "--scan",
        metavar="ID",
        help=(
            "the spectrum to process from a file holding several"
            if process
            else "the spectrum to convert from a file holding several"
        ),
    )
    outputs.add_argument(
        "--overwrite", action="store_true", help="replace outputs that already exist"
    )

    text = parser.add_argument_group("text outputs")
    text.add_argument(
        "--peaklist",
        action="store_true",
        help="write the peak list instead of the profile",
    )
    text.add_argument(
        "--columns",
        type=parse_columns,
        metavar="LIST",
        help=(
            "peak list columns, comma-separated, from: "
            f"{','.join(PEAKLIST_COLUMNS)} (default: the columns of Export "
            "Peak List in the GUI)"
        ),
    )
    text.add_argument(
        "--separator",
        choices=list(SEPARATORS),
        help="column separator (default: comma for csv, tab otherwise)",
    )

    images = parser.add_argument_group("images")
    images.add_argument(
        "--size",
        type=parse_size,
        metavar="WxH",
        help=(
            "raster image size in pixels (default: %dx%d); SVG images are "
            "vector graphics and ignore it" % DEFAULT_IMAGE_SIZE
        ),
    )
    images.add_argument(
        "--mz-range",
        type=parse_mz_range,
        metavar="LOW:HIGH",
        help=(
            "draw only this m/z range, e.g. 400:1500; leave out an end to "
            "draw to the end of the spectrum, e.g. 400:"
        ),
    )
    images.add_argument(
        "--dark", action="store_true", help="draw images on a dark background"
    )
    return parser


def parse_convert_args(argv, command=CONVERT_COMMAND):
    """Parse and check mmass convert or process arguments into ConvertOptions.

    Everything that can be told from the arguments alone is checked here, so
    an impossible request fails before any file is read or written.
    """

    process = command == PROCESS_COMMAND
    parser = make_convert_parser(command)
    # inputs may follow options, as in: mmass convert -t png *.mzML more.msd
    args = parser.parse_intermixed_args(argv)

    steps = getattr(args, "steps", None) or []
    inPlace = getattr(args, "in_place", False)
    showSettings = getattr(args, "show_settings", False)

    if process and not showSettings:
        if not steps:
            parser.error(
                "no processing steps given, e.g. --baseline --findpeaks; to "
                f"convert without processing, use mmass {CONVERT_COMMAND}"
            )
        if not args.inputs:
            parser.error("no inputs given")
        if not (args.output or args.to or inPlace):
            parser.error(
                "say where to write the results: --output FILE, --to FORMAT, "
                "or --in-place to replace the inputs"
            )

    if showSettings:
        return ConvertOptions(
            inputs=[],
            format=None,
            command=command,
            preset=args.preset,
            settings=args.settings,
            showSettings=True,
        )

    # output format
    name = None
    kind = None
    what = ""
    if inPlace:
        if args.output_dir:
            parser.error("--in-place writes each input back where it is, not to --output-dir")
        if args.scan is not None:
            parser.error(
                "--in-place rewrites whole files, so --scan cannot pick one "
                "spectrum of them; write it out with --output or --to instead"
            )
        if args.overwrite:
            warn("--overwrite does not apply to --in-place, ignoring it")
    elif args.output:
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

    if name is not None:
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

        problem = steps_problem(steps, kind, name, args.peaklist and kind == "ASCII")
        if problem:
            parser.error(problem)

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
    shown = name or "in-place"
    size = args.size
    if size is not None and (kind != "image" or name == "svg"):
        warn(f"--size does not apply to {shown} output, ignoring it")
    if size is None or name == "svg":
        size = SVG_SIZE if name == "svg" else DEFAULT_IMAGE_SIZE
    if args.dark and kind != "image":
        warn(f"--dark does not apply to {shown} output, ignoring it")
    if args.mz_range and kind != "image":
        warn(
            f"--mz-range does not apply to {shown} output, ignoring it"
            + ("; --crop cuts the data itself" if process else "")
        )
    if args.separator and kind not in ("ASCII", None):
        warn(f"--separator does not apply to {shown} output, ignoring it")
    if args.peaklist and kind not in ("ASCII", None):
        warn(f"--peaklist does not apply to {shown} output, ignoring it")
    if args.columns and not args.peaklist:
        warn("--columns applies to --peaklist output, ignoring it")
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
        overwrite=args.overwrite and not inPlace,
        mzRange=args.mz_range if kind == "image" else None,
        peaklist=args.peaklist and kind in ("ASCII", None),
        columns=args.columns,
        command=command,
        steps=steps,
        inPlace=inPlace,
        preset=getattr(args, "preset", None),
        settings=getattr(args, "settings", []),
        # an explicit --separator also sets the separator of in-place text
        # files, which otherwise keep their own
        explicitSeparator=args.separator is not None,
    )
