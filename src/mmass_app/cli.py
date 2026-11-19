"""Command-line arguments of the mMass launcher.

This module must not import wxPython or the GUI modules: it is parsed before
the GUI starts and is tested headless.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

# gui.session.SESSION_EXTENSION, repeated here because importing the gui
# package would load the user's config as a side effect
SESSION_EXTENSION = ".mses"

# field codes a desktop launcher passes on verbatim when it does not expand
# them (seen with Wine desktop integrations)
LAUNCHER_PLACEHOLDERS = {"%f", "%F", "%u", "%U", "%i", "%c", "%k"}


CONVERT_COMMAND = "convert"
PROCESS_COMMAND = "process"

# the output name that writes to standard output
STDOUT = "-"

# formats mmass convert writes, by the name --format takes (the file extension
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

# gui.doc.PEAKLIST_COLUMNS names, repeated for the same reason as above, with
# what they hold
PEAKLIST_COLUMNS = {
    "mz": "m/z",
    "ai": "apex intensity, baseline included",
    "base": "baseline",
    "int": "intensity above the baseline",
    "rel": "relative intensity, %",
    "sn": "signal to noise",
    "z": "charge",
    "mass": "neutral mass",
    "fwhm": "peak width",
    "resol": "resolution",
    "envarea": "envelope area",
    "enverr": "envelope area uncertainty (one sigma)",
    "envint": "summed envelope intensity",
    "group": "group",
}
# longer names --columns also takes
COLUMN_ALIASES = {"intensity": "int", "charge": "z", "resolution": "resol"}

# processing steps of mmass process, by option name: (help, what they change
# -- the "profile", the "peaks" or "both")
STEPS = {
    "crop": ("keep only the m/z range LOW-HIGH, e.g. 500-3000", "both"),
    "baseline": ("subtract the baseline", "profile"),
    "smooth": ("smooth the profile", "profile"),
    "find-peaks": (
        "find peaks, deisotoping them if the peak picking settings say so",
        "peaks",
    ),
    "deisotope": ("find isotopes and charges of the peaks", "peaks"),
    "envelopes": (
        "turn every peak into an envelope and refit the envelopes already "
        "there, as Convert All to Envelopes does in the GUI",
        "peaks",
    ),
    "math": (
        "apply a math operation to the profile and the peaks: normalize "
        "(scale to a maximum of 100 %%), multiply (by the math.multiplier "
        "setting) or squareroot (or sqrt)",
        "both",
    ),
}
# other spellings of options, accepted but not listed in --help
OPTION_ALIASES = {
    "--findpeaks": "--find-peaks",
    "--peaklist": "--peak-list",
    "--mz-range": "--range",
}

# gui.processing.SINGLE_SPECTRUM_MATH, repeated for the same reason as above
MATH_OPERATIONS = ("normalize", "multiply", "squareroot")
# other names --math also takes
MATH_ALIASES = {"sqrt": "squareroot", "normalise": "normalize"}
# math operations of the GUI that take other spectra than the one processed
MULTI_SPECTRUM_MATH = (
    "combine", "overlay", "subtract", "averageall", "combineall", "overlayall",
)

# settings sections the steps use, which --set can change
SETTINGS_SECTIONS = ("math", "baseline", "smoothing", "peakpicking", "deisotoping")
# settings of those sections no step uses: the math operation is the step's
# argument, and no single-spectrum operation preserves peaks
UNUSED_SETTINGS = {"math.operation", "math.preservePeaks"}

# options a recipe may hold: what to do with a spectrum and how to write it,
# but not which files to read or where to write, nor anything destructive
RECIPE_OPTIONS = (
    *STEPS, "preset", "set", "peak-list", "columns", "separator", "size",
    "range", "dark",
)

EXIT_CODES = (
    "Exit status: 0 when every input was written, 1 when some inputs could not "
    "be, 2 when the arguments are wrong."
)


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
    dryRun: bool = False
    mzRange: tuple[float | None, float | None] | None = None
    peaklist: bool = False
    columns: list[str] | None = None
    # mmass process: [(step, argument)] in the order given, and the settings;
    # each setting is (key, value, where it was given)
    command: str = CONVERT_COMMAND
    steps: list[tuple[str, object]] = field(default_factory=list)
    inPlace: bool = False
    preset: str | None = None
    presetOrigin: str = "--preset"
    settings: list[tuple[str, str, str]] = field(default_factory=list)
    showSettings: bool = False

    @property
    def kind(self):
        return OUTPUT_FORMATS.get(self.format) if self.format else None

    @property
    def prog(self):
        return f"mmass {self.command}"


def get_version():
    """Return the installed mMass version."""

    try:
        import importlib.metadata

        return importlib.metadata.version("mmass")
    except Exception:
        return "unknown"


class Parser(argparse.ArgumentParser):
    """An argument parser taking only whole option names, with short errors."""

    def __init__(self, *args, **kwargs):
        # a prefix of an option (--dry for --dry-run) would stop working as
        # soon as another option starts alike
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message):
        self.exit(2, f"{self.prog}: error: {message}\nSee '{self.prog} --help'.\n")


def make_parser():
    """Return the argument parser of the mmass command."""

    parser = Parser(
        prog="mmass",
        usage=(
            "mmass [FILE ...]\n"
            f"       mmass {CONVERT_COMMAND} INPUT OUTPUT [options]\n"
            f"       mmass {CONVERT_COMMAND} INPUT ... -f FORMAT [-d DIR] [options]\n"
            f"       mmass {PROCESS_COMMAND} INPUT STEP ... OUTPUT [options]\n"
            f"       mmass {PROCESS_COMMAND} INPUT ... STEP ... "
            "(-f FORMAT [-d DIR] | --in-place) [options]\n"
            f"       mmass {CLUSTER_COMMAND} INPUT ... -d DIR [options]"
        ),
        description=(
            "mMass - Open Source Mass Spectrometry Tool.\n\n"
            "Without a command, mMass opens its window with the FILEs given.\n\n"
            "commands:\n"
            f"  {CONVERT_COMMAND}   convert spectra to other formats or images, "
            "without the GUI\n"
            f"  {PROCESS_COMMAND}   process spectra (crop, baseline, smooth, "
            "find peaks, ...) without the GUI\n"
            f"  {CLUSTER_COMMAND}   group spectra by similarity, without the GUI\n"
            f"See 'mmass COMMAND --help' for {CONVERT_COMMAND}, {PROCESS_COMMAND} "
            f"and {CLUSTER_COMMAND}."
        ),
        epilog=(
            "FILE can be an mzML, mzXML, mzData, MGF, mSD or XY/TXT/ASC spectrum,\n"
            "a Bruker fid file or dataset folder, or a FASTA file (its sequences\n"
            f"are imported). A session file ({SESSION_EXTENSION}) reopens its documents "
            "and view;\nother files are added to it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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


def warn(message, prog="mmass"):
    """Print a warning for a user starting mMass from a terminal."""

    print(f"{prog}: warning: {message}", file=sys.stderr)


def shown_path(path):
    """A path as a message shows it: relative when under the current folder."""

    if path == STDOUT:
        return "standard output"
    try:
        relative = os.path.relpath(path)
    except ValueError:
        # another drive on Windows
        return path
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return path
    return relative


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


# VALUES
# ------


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
    # m/z is never negative, so a dash separates the ends as well as a colon
    separator = ":" if ":" in value else "-"
    parts = value.split(separator)
    example = "400:1500 or 400-1500" + (", 400: or :1500" if openEnded else "")
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
    """Parse a --set argument [SECTION.]KEY=VALUE into ([SECTION.]KEY, VALUE)."""

    key, equals, setting = value.partition("=")
    key = key.strip()
    section, dot, name = key.partition(".")
    if not equals or not key or (dot and not (section and name)):
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a setting such as snThreshold=10 or "
            "peakpicking.snThreshold=10"
        )
    return key, setting.strip()


def parse_columns(value):
    """Parse a comma-separated list of peak list columns."""

    columns = []
    unknown = []
    for column in value.split(","):
        name = column.strip().lower()
        if not name:
            continue
        name = COLUMN_ALIASES.get(name, name)
        if name in PEAKLIST_COLUMNS:
            columns.append(name)
        else:
            unknown.append(column.strip())
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


def output_extension(name):
    """Return the file extension mmass convert gives a format."""

    return OUTPUT_EXTENSIONS.get(name, "." + name)


# ACTIONS
# -------


class _StepAction(argparse.Action):
    """Collect processing steps in the order they are given."""

    def __call__(self, parser, namespace, values, option_string=None):
        steps = list(getattr(namespace, self.dest) or [])
        steps.append((self.const, values if values != [] else None))
        setattr(namespace, self.dest, steps)


class _SettingAction(argparse.Action):
    """Collect --set settings with where they were given."""

    def __call__(self, parser, namespace, values, option_string=None, origin="--set"):
        settings = list(getattr(namespace, self.dest) or [])
        key, value = values
        settings.append((key, value, origin))
        setattr(namespace, self.dest, settings)


class _PresetAction(argparse.Action):
    """Keep --preset with where it was given."""

    def __call__(self, parser, namespace, values, option_string=None, origin="--preset"):
        setattr(namespace, self.dest, values)
        namespace.preset_origin = origin


class _RecipeAction(argparse.Action):
    """Apply the lines of a recipe file where --recipe is given.

    A recipe holds one option per line, written as on the command line with or
    without the leading dashes; its value follows a space or an equals sign.
    Blank lines and text after a # are ignored.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        path = str(values)
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError as exc:
            parser.error(f"cannot read the recipe {path}: {exc.strerror}")
        except UnicodeDecodeError:
            parser.error(f"the recipe {path} is not a text file")

        for number, line in enumerate(lines, start=1):
            where = f"recipe {path}, line {number}"
            text = re.sub(r"(^|\s)#.*$", "", line).strip()
            if not text:
                continue

            match = re.match(r"-{0,2}([A-Za-z][\w-]*)\s*(?:[=\s]\s*(.*))?$", text)
            if not match:
                parser.error(f"{where}: '{line.strip()}' is not an option")
            name, value = match.group(1).lower(), match.group(2)
            option = OPTION_ALIASES.get(f"--{name}", f"--{name}")

            if option[2:] not in RECIPE_OPTIONS:
                if option == "--recipe":
                    parser.error(f"{where}: a recipe cannot include another recipe")
                if option in parser._option_string_actions:
                    parser.error(
                        f"{where}: {option} belongs on the command line, not in "
                        "a recipe, which says what to do but not with which "
                        "files or where to write"
                    )
                parser.error(f"{where}: unknown option '{name}'")

            action = parser._option_string_actions[option]
            takes_value = action.nargs != 0
            if takes_value and not value:
                parser.error(f"{where}: {option[2:]} needs a value")
            if not takes_value and value:
                parser.error(f"{where}: {option[2:]} takes no value")

            converted: Any = []
            if takes_value:
                converted = value
                if callable(action.type):
                    try:
                        converted = action.type(value)
                    except argparse.ArgumentTypeError as exc:
                        parser.error(f"{where}: {exc}")
                if action.choices is not None and converted not in action.choices:
                    choices = ", ".join(map(str, action.choices))
                    parser.error(f"{where}: {option[2:]} must be one of {choices}")

            if isinstance(action, (_SettingAction, _PresetAction)):
                action(parser, namespace, converted, option, origin=where)
            elif takes_value or isinstance(action, _StepAction):
                action(parser, namespace, converted, option)
            else:
                action(parser, namespace, None, option)


# CHECKS
# ------


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
                "write them with --format csv --peak-list or --format msd instead"
                if inPlace
                else "add --peak-list to write the peak list as text, or write msd"
            )
            return (
                f"{holder} holds only the profile, so the peaks --{step} finds "
                f"would be lost; {advice}"
            )
        if changes == "profile" and "profile" not in stored:
            if "find-peaks" not in names[index + 1:]:
                advice = "add --find-peaks after it" + (
                    "" if inPlace else ", or write msd or text"
                )
                return (
                    f"{holder} holds only the peak list, which --{step} does "
                    f"not change; {advice}"
                )
    return None


# PARSERS
# -------


def make_convert_parser(command=CONVERT_COMMAND):
    """Return the argument parser of mmass convert or mmass process."""

    process = command == PROCESS_COMMAND
    writable = ", ".join(OUTPUT_FORMATS)
    inputs_epilog = (
        "Inputs: mzML, mzXML, mzData, MGF, "
        "mSD, XY/TXT/ASC, a Bruker fid file or dataset folder. Outputs: "
        f"{writable}. A file holding several spectra (an LC-MS run, an MGF "
        "or a Bruker folder of many acquisitions) is written whole to "
        "mzML, mzXML and, for LC-MS runs, msd; other outputs need one "
        "spectrum picked with --scan. Text outputs hold the profile, or the "
        "peak list with --peak-list; MGF holds the peak list. Images use the "
        "spectrum settings of the GUI."
    )

    if process:
        parser = Parser(
            prog=f"mmass {PROCESS_COMMAND}",
            usage=(
                f"mmass {PROCESS_COMMAND} INPUT STEP ... OUTPUT [options]\n"
                f"       mmass {PROCESS_COMMAND} INPUT ... STEP ... "
                "(-f FORMAT [-d DIR] | --in-place) [options]\n"
                f"       mmass {PROCESS_COMMAND} INPUT ... --recipe FILE "
                "(OUTPUT | -f FORMAT [-d DIR] | --in-place) [options]\n"
                f"       mmass {PROCESS_COMMAND} --show-settings [--recipe FILE] "
                "[--preset NAME] [--set KEY=VALUE ...]"
            ),
            description=(
                "Process spectra without opening the GUI: run the steps in the "
                "order they are given, then write the result, or rewrite the "
                "inputs with --in-place."
            ),
            epilog=(
                "Steps use your settings from the Processing panel of the GUI, "
                "which --preset and --set change for this command only. A recipe file lists "
                "steps and settings, one per line as on the command line, e.g. "
                "'find-peaks' or 'set snThreshold=10'; # starts a comment. " + inputs_epilog
            ),
        )
    else:
        parser = Parser(
            prog=f"mmass {CONVERT_COMMAND}",
            usage=(
                f"mmass {CONVERT_COMMAND} INPUT OUTPUT [options]\n"
                f"       mmass {CONVERT_COMMAND} INPUT ... -f FORMAT [-d DIR] [options]"
            ),
            description=(
                "Convert spectra to another format or draw them as images, "
                "without opening the GUI."
            ),
            epilog=inputs_epilog
            + f" To process spectra as well, see 'mmass {PROCESS_COMMAND} --help'."
        )

    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="INPUT",
        help=(
            f"documents to {'process' if process else 'convert'}; without "
            "--output or --format, the last name is the output file, its format "
            "given by its extension"
        ),
    )

    if process:
        steps = parser.add_argument_group("steps, run in the order given")
        for step, (text, _changes) in STEPS.items():
            names = [f"--{step}"]
            names += [alias for alias, name in OPTION_ALIASES.items() if name == names[0]]
            kwargs: dict[str, Any] = {"nargs": 0}
            if step == "crop":
                kwargs = {"type": parse_crop_range, "metavar": "LOW-HIGH"}
            elif step == "math":
                kwargs = {"type": parse_math, "metavar": "OPERATION"}
            steps.add_argument(
                names[0], dest="steps", action=_StepAction, const=step, help=text, **kwargs
            )
            for alias in names[1:]:
                steps.add_argument(
                    alias, dest="steps", action=_StepAction, const=step,
                    help=argparse.SUPPRESS, **kwargs,
                )

        settings = parser.add_argument_group("settings")
        settings.add_argument(
            "--recipe",
            action=_RecipeAction,
            metavar="FILE",
            help="run the steps and settings listed in a file, where it is given",
        )
        settings.add_argument(
            "--preset",
            action=_PresetAction,
            metavar="NAME",
            help=(
                "start from processing presets saved in the GUI; 'Default' "
                "gives the built-in settings, the same on every computer"
            ),
        )
        settings.add_argument(
            "--set",
            dest="settings",
            action=_SettingAction,
            default=[],
            type=parse_setting,
            metavar="[SECTION.]KEY=VALUE",
            help=(
                "change one setting, e.g. snThreshold=10; the section is "
                "needed only for a key several sections have (repeatable)"
            ),
        )
        settings.add_argument(
            "--show-settings",
            action="store_true",
            help="print the settings the steps would use, and exit",
        )

    outputs = parser.add_argument_group("output")
    outputs.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help=(
            "output file, its format given by the extension (one input only), "
            "which can also follow the input without -o; "
            "- writes to standard output, in the format given by --format"
        ),
    )
    outputs.add_argument(
        "-f",
        "--format",
        metavar="FORMAT",
        help=(
            "output format; each input is written beside it under the same "
            "name, or into --output-dir"
        ),
    )
    if process:
        outputs.add_argument(
            "--in-place",
            action="store_true",
            help="replace each input with its processed version",
        )
    outputs.add_argument(
        "-d",
        "--output-dir",
        metavar="DIR",
        help="folder to write --format outputs into (created if missing)",
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
    outputs.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "read and process every input and report what would be written, "
            "but write nothing"
        ),
    )

    text = parser.add_argument_group("text outputs")
    text.add_argument(
        "--peak-list",
        dest="peaklist",
        action="store_true",
        help="write the peak list instead of the profile",
    )
    text.add_argument(
        "--peaklist", dest="peaklist", action="store_true", help=argparse.SUPPRESS
    )
    text.add_argument(
        "--columns",
        type=parse_columns,
        metavar="LIST",
        help=(
            "peak list columns, comma-separated (default: the columns of Export "
            "Peak List in the GUI): "
            + ", ".join(
                f"{name} ({meaning})" if meaning != name else name
                for name, meaning in PEAKLIST_COLUMNS.items()
            ).replace("%", "%%")
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
        "--range",
        dest="mz_range",
        type=parse_mz_range,
        metavar="LOW-HIGH",
        help=(
            "draw only this m/z range, e.g. 400-1500 or 400:1500; leave out an "
            "end to draw to the end of the spectrum, e.g. 400-"
        ),
    )
    images.add_argument(
        "--mz-range", dest="mz_range", type=parse_mz_range, help=argparse.SUPPRESS
    )
    images.add_argument(
        "--dark", action="store_true", help="draw images on a dark background"
    )
    return parser


def _process_only_options():
    """Option names mmass process takes and mmass convert does not."""

    convert = make_convert_parser(CONVERT_COMMAND)._option_string_actions
    process = make_convert_parser(PROCESS_COMMAND)._option_string_actions
    return set(process) - set(convert)


def parse_convert_args(argv, command=CONVERT_COMMAND):
    """Parse and check mmass convert or process arguments into ConvertOptions.

    Everything that can be told from the arguments alone is checked here, so
    an impossible request fails before any file is read or written.
    """

    process = command == PROCESS_COMMAND
    parser = make_convert_parser(command)
    prog = parser.prog

    if not argv:
        parser.print_help()
        parser.exit(0)

    if not process:
        processOnly = _process_only_options()
        for item in argv:
            if item == "--":
                break
            name = item.split("=", 1)[0]
            if name in processOnly:
                parser.error(
                    f"{name} belongs to processing; use mmass {PROCESS_COMMAND} "
                    f"instead of mmass {CONVERT_COMMAND}"
                )

    # inputs may follow options, as in: mmass convert -f png *.mzML more.msd
    args = parser.parse_intermixed_args(argv)

    steps = getattr(args, "steps", None) or []
    inPlace = getattr(args, "in_place", False)
    showSettings = getattr(args, "show_settings", False)
    settings = getattr(args, "settings", [])
    preset = getattr(args, "preset", None)
    presetOrigin = getattr(args, "preset_origin", "--preset")

    if showSettings:
        return ConvertOptions(
            inputs=[],
            format=None,
            command=command,
            preset=preset,
            presetOrigin=presetOrigin,
            settings=settings,
            showSettings=True,
        )

    # where to write: without --output, --format or --in-place, the last of
    # several names is the output file, as in: mmass convert in.mzML out.png
    namedOutput = False
    if not (args.output or args.format or inPlace) and len(args.inputs) > 1:
        args.output = args.inputs.pop()
        namedOutput = True
        if os.path.exists(args.output) and not os.path.isdir(args.output) and not args.overwrite:
            parser.error(
                f"{args.output} already exists, and as the last name it would be "
                "the output file; add --overwrite to replace it, or give "
                "--format FORMAT to convert every file named"
            )
    if not (args.output or args.format or inPlace):
        parser.error(
            "say where to write the results: an output file after the input, "
            "--output FILE or --format FORMAT"
            + (", or --in-place to replace the inputs" if process else "")
        )
    if process and not steps:
        parser.error(
            "no processing steps given, e.g. --baseline --find-peaks; to "
            f"convert without processing, use mmass {CONVERT_COMMAND}"
        )
    if not args.inputs:
        parser.error("no inputs given")

    toStdout = args.output == STDOUT
    targets = [
        name for name, given in
        (("--output", args.output and not toStdout), ("--format", args.format), ("--in-place", inPlace))
        if given
    ]
    if len(targets) > 1:
        parser.error(f"give only one of {' and '.join(targets)}")

    name = None
    kind = None
    what = ""
    if inPlace:
        if toStdout:
            parser.error("--in-place writes each input back where it is, not to standard output")
        if args.output_dir:
            parser.error("--in-place writes each input back where it is, not to --output-dir")
        if args.scan is not None:
            parser.error(
                "--in-place rewrites whole files, so --scan cannot pick one "
                "spectrum of them; write it out with --output or --format instead"
            )
        if args.overwrite:
            warn("--overwrite does not apply to --in-place, ignoring it", prog)
    elif toStdout:
        if not args.format:
            parser.error("writing to standard output (--output -) needs --format FORMAT")
        if len(args.inputs) > 1:
            parser.error("only one input can be written to standard output")
        if args.output_dir:
            parser.error("--output - writes to standard output, not to --output-dir")
        name = args.format.lower().lstrip(".")
        what = f"format '{args.format}'"
    elif args.output:
        given = args.output if namedOutput else f"--output {args.output}"
        folder = args.output.endswith(("/", os.sep)) or os.path.isdir(args.output)
        if folder:
            parser.error(
                f"{given} is a folder; to write into a folder, use --format "
                f"FORMAT --output-dir {args.output}"
            )
        if len(args.inputs) > 1:
            parser.error(
                f"{given} names one output file, for one input; to convert "
                "several files, use --format FORMAT"
            )
        if args.output_dir:
            parser.error(
                "--output-dir works with --format; give the output file a full path"
            )
        name = os.path.splitext(args.output)[1].lower().lstrip(".")
        if os.path.basename(args.output).lower() == "fid":
            name = "fid"
        what = f"output file {args.output}"
    else:
        name = args.format.lower().lstrip(".")
        what = f"format '{args.format}'"

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
        warn(f"no such file or folder: {path}", prog)
    if missing:
        parser.error("inputs not found")

    if args.output_dir and os.path.exists(args.output_dir):
        if not os.path.isdir(args.output_dir):
            parser.error(f"--output-dir {args.output_dir} is not a folder")

    # options that do not apply to this output
    shown = name or "in-place"
    size = args.size
    if size is not None and (kind != "image" or name == "svg"):
        warn(f"--size does not apply to {shown} output, ignoring it", prog)
    if size is None or name == "svg":
        size = SVG_SIZE if name == "svg" else DEFAULT_IMAGE_SIZE
    if args.dark and kind != "image":
        warn(f"--dark does not apply to {shown} output, ignoring it", prog)
    if args.mz_range and kind != "image":
        warn(
            f"--range does not apply to {shown} output, ignoring it"
            + ("; --crop cuts the data itself" if process else ""),
            prog,
        )
    if args.separator and kind not in ("ASCII", None):
        warn(f"--separator does not apply to {shown} output, ignoring it", prog)
    # an MGF file is a peak list already
    if args.peaklist and kind not in ("ASCII", "MGF", None):
        warn(f"--peak-list does not apply to {shown} output, ignoring it", prog)
    if args.columns and not args.peaklist:
        warn("--columns applies to --peak-list output, ignoring it", prog)
    separator = args.separator or ("comma" if name == "csv" else "tab")

    return ConvertOptions(
        inputs=[os.path.abspath(path) for path in args.inputs],
        format=name,
        output=STDOUT if toStdout else os.path.abspath(args.output) if args.output else None,
        outputDir=os.path.abspath(args.output_dir) if args.output_dir else None,
        scan=args.scan,
        size=size,
        separator=SEPARATORS[separator],
        dark=args.dark,
        overwrite=args.overwrite and not inPlace,
        dryRun=args.dry_run,
        mzRange=args.mz_range if kind == "image" else None,
        peaklist=args.peaklist and kind in ("ASCII", None),
        columns=args.columns,
        command=command,
        steps=steps,
        inPlace=inPlace,
        preset=preset,
        presetOrigin=presetOrigin,
        settings=settings,
        # an explicit --separator also sets the separator of in-place text
        # files, which otherwise keep their own
        explicitSeparator=args.separator is not None,
    )


# MMASS CLUSTER
# -------------

CLUSTER_COMMAND = "cluster"

# what mmass cluster writes into its output folder
CLUSTER_OUTPUTS = (
    "REPORT.md",
    "groups.csv",
    "similarity.csv",
    "similarity_cosine.csv",
    "co_membership.csv",
    "trees.nwk",
)


@dataclass
class ClusterOptions:
    """What mmass cluster should compare and group, and where to write."""

    inputs: list[str]
    outputDir: str
    overwrite: bool = False
    includeHidden: bool = False
    # keyword arguments of mspy.similaritymatrix and mspy.groupspectra
    similarity: dict[str, Any] = field(default_factory=dict)
    grouping: dict[str, Any] = field(default_factory=dict)


def _positive(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a number") from None
    if not number > 0:
        raise argparse.ArgumentTypeError(f"'{value}' must be above zero")
    return number


def _nonnegative(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a number") from None
    if number < 0:
        raise argparse.ArgumentTypeError(f"'{value}' must not be negative")
    return number


def _count(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a whole number") from None
    if number < 0:
        raise argparse.ArgumentTypeError(f"'{value}' must not be negative")
    return number


def _edge(value):
    if value.lower() == "auto":
        return "auto"
    try:
        return float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is neither a number nor 'auto'") from None


def make_cluster_parser():
    """Return the argument parser of mmass cluster."""

    parser = Parser(
        prog=f"mmass {CLUSTER_COMMAND}",
        usage=f"mmass {CLUSTER_COMMAND} INPUT ... -d DIR [options]",
        description=(
            "Group spectra by the similarity of their whole profiles, without "
            "opening the GUI. The similarity is corrected for the m/z range the "
            "spectra cover and for the similarity expected by chance (0 = as "
            "alike as chance, 1 = identical). For fragment spectra, neutral "
            "losses from the precursor count as well as fragment ions. Groups are "
            "communities of a network of similar spectra; a bootstrap gives each "
            "pair the share of replicates in which both fall in one group."
        ),
        epilog=(
            "Inputs: mSD, XY/TXT/ASC, mzML, mzXML, mzData, MGF, a Bruker fid "
            "file or dataset folder, or a session (the documents it shows; "
            "--include-hidden adds the hidden ones). Every spectrum of an MGF or "
            "of a Bruker folder of many acquisitions is used; an LC-MS run is used "
            "only through a session that names one of its scans. Spectra of "
            "different polarity are compared only with --neutral-mass. Outputs, "
            f"in DIR: {', '.join(CLUSTER_OUTPUTS)}. The spectra should be "
            "calibrated: a shifted m/z axis makes related spectra look unrelated. "
            "Exit status: 0 when every input was used, 1 when some could not be, "
            "2 when the arguments are wrong."
        ),
    )
    parser.add_argument("inputs", nargs="*", metavar="INPUT", help="spectra or sessions to group")
    parser.add_argument(
        "-d", "--output-dir", metavar="DIR", help="folder for the results (made if missing)"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace results already in DIR"
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="also use the documents a session hides",
    )

    sim = parser.add_argument_group("similarity")
    sim.add_argument(
        "--source",
        choices=("profile", "peaks"),
        default="profile",
        help="compare the profiles (default) or the peak lists",
    )
    sim.add_argument(
        "--axes",
        choices=("both", "mz", "loss"),
        default="both",
        help="spectra with a precursor m/z: compare fragment m/z, losses from the "
        "precursor or both (default); spectra without one are compared on m/z, "
        "and 'loss' needs a precursor in every spectrum",
    )
    sim.add_argument("--tolerance", type=_positive, default=0.2, metavar="DA",
                     help="m/z tolerance (default 0.2)")
    sim.add_argument("--min-mz", type=_nonnegative, default=50.0, metavar="MZ",
                     help="low-mass limit (default 50)")
    sim.add_argument("--isolation", type=_nonnegative, default=6.0, metavar="DA",
                     help="half-width left out around a precursor (default 6)")
    sim.add_argument("--snr", type=_nonnegative, default=5.0, metavar="N",
                     help="keep signal above N times the local noise (default 5)")
    sim.add_argument("--baseline-window", type=_positive, default=5.0, metavar="DA",
                     help="width of the baseline (default 5)")
    sim.add_argument("--noise-window", type=_positive, default=25.0, metavar="DA",
                     help="width of the noise estimate (default 25)")
    sim.add_argument("--grid", type=_positive, default=0.1, metavar="DA",
                     help="step of the m/z grid (default 0.1)")
    sim.add_argument("--transform", choices=("sqrt", "log", "none"), default="sqrt",
                     help="intensity transform (default sqrt)")
    sim.add_argument("--no-weighting", action="store_true",
                     help="do not weight rare signals above ones every spectrum has")
    sim.add_argument("--no-chance-correction", action="store_true",
                     help="use the shared-range cosine without the chance correction")
    sim.add_argument("--neutral-mass", action="store_true",
                     help="compare positive with negative spectra on neutral mass")
    sim.add_argument("--pos-adduct", choices=("H", "Na", "K", "NH4"), default="Na",
                     help="with --neutral-mass: positive ions are [M+X]+ (default Na)")
    sim.add_argument("--neg-adduct", choices=("H", "Cl", "HCOO"), default="H",
                     help="with --neutral-mass: negative ions are [M-H]- (H, default), "
                     "[M+Cl]- or [M+HCOO]-")

    grp = parser.add_argument_group("grouping")
    grp.add_argument("--groups", choices=("network", "tree"), default="network",
                     help="network communities (default) or a cut of the tree")
    grp.add_argument("--edge", type=_edge, default=0.2, metavar="S",
                     help="network edge threshold on the corrected similarity "
                     "(default 0.2), or 'auto'")
    grp.add_argument("--top-k", type=int, default=3, metavar="K",
                     help="an edge needs both spectra among each other's K most "
                     "similar (default 3)")
    grp.add_argument("--resolution", type=_positive, default=1.0, metavar="R",
                     help="higher gives smaller network groups (default 1)")
    grp.add_argument("--cut", type=float, default=0.3, metavar="S",
                     help="with --groups tree: similarity at which the tree is cut "
                     "(default 0.3)")
    grp.add_argument("--bootstrap", type=_count, default=200, metavar="N",
                     help="bootstrap replicates (default 200; 0 = none)")
    grp.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    return parser


def parse_cluster_args(argv):
    """Parse and check mmass cluster arguments into ClusterOptions."""

    parser = make_cluster_parser()
    if not argv:
        parser.print_help()
        parser.exit(0)
    args = parser.parse_intermixed_args(argv)
    if not args.inputs:
        parser.error("no inputs given")
    if not args.output_dir:
        parser.error("the results need a folder: give it with -d DIR")
    if os.path.exists(args.output_dir) and not os.path.isdir(args.output_dir):
        parser.error(f"{args.output_dir} is not a folder")
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")
    if not args.neutral_mass:
        for name, value, default in (("--pos-adduct", args.pos_adduct, "Na"),
                                     ("--neg-adduct", args.neg_adduct, "H")):
            if value != default:
                warn(f"{name} applies with --neutral-mass, ignoring it", parser.prog)

    return ClusterOptions(
        inputs=[os.path.abspath(path) for path in args.inputs],
        outputDir=os.path.abspath(args.output_dir),
        overwrite=args.overwrite,
        includeHidden=args.include_hidden,
        similarity={
            "source": args.source,
            "axes": args.axes,
            "binWidth": args.grid,
            "tolerance": args.tolerance,
            "minMZ": args.min_mz,
            "isolation": args.isolation,
            "baselineWindow": args.baseline_window,
            "noiseWindow": args.noise_window,
            "snr": args.snr,
            "transform": args.transform,
            "weighting": "none" if args.no_weighting else "rarity",
            "chanceCorrection": not args.no_chance_correction,
            "neutralMass": args.neutral_mass,
            "posAdduct": args.pos_adduct,
            "negAdduct": args.neg_adduct,
        },
        grouping={
            "method": args.groups,
            "edge": args.edge,
            "topK": args.top_k,
            "resolution": args.resolution,
            "cut": args.cut,
            "replicates": args.bootstrap,
            "seed": args.seed,
        },
    )
