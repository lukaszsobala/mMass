"""Convert and process documents without the GUI (mmass convert, mmass process).

Documents are read with the same code the GUI opens them with (gui.doc),
processed with the same code as the Processing panel (gui.processing) and
written with the same writers it saves and exports with. Images are drawn on an
off-screen spectrum canvas styled like the spectrum panel, which needs a wx.App
and hence a display, but no window is ever shown.

Nothing here may assign to gui.config: its sections save themselves on every
change, and a command must never rewrite the user's settings. Processing uses
a plain copy of them instead.
"""

import contextlib
import dataclasses
import json
import math
import os
import shutil
import sys
import tempfile

from mmass_app import cli

# how many scan IDs an error message lists
LISTED_SCANS = 10

# formats written back by --in-place, by document type; the XY format keeps
# the extension of the file
IN_PLACE_FORMATS = {"mSD": "msd", "XY": None, "MGF": "mgf"}

# settings taking one of a few words, and settings that must be above zero
SETTING_CHOICES = {
    "smoothing.method": ("MA", "GA", "SG"),
    "peakpicking.poolScans": ("run", "window", "off"),
    "peakpicking.averagineType": ("protein", "carbohydrate", "lipid"),
    "deisotoping.labelEnvelope": ("1st", "monoisotope", "centroid", "isotopes"),
    "deisotoping.envelopeIntensity": ("maximum", "sum", "average"),
}
POSITIVE_SETTINGS = {
    "baseline.precision",
    "smoothing.windowSize",
    "smoothing.cycles",
    "deisotoping.maxCharge",
    "peakpicking.poolWindow",
}


class ConversionError(Exception):
    """A document that cannot be converted or processed as asked."""


def error(message, command=cli.CONVERT_COMMAND):
    print(f"mmass {command}: error: {message}", file=sys.stderr)


# SETTINGS
# --------


def processing_settings(options):
    """The processing settings the steps run with.

    A plain copy of the Processing panel's settings, changed by --preset and
    --set; gui.config itself is never changed.
    """

    from gui import config

    settings = json.loads(json.dumps(config.processing))

    if options.preset:
        if options.preset == "Default":
            preset = config.processing_defaults
        else:
            from gui import libs

            presets = libs.presets["processing"]
            if options.preset not in presets:
                names = ", ".join(["Default"] + sorted(presets))
                raise ConversionError(
                    f"there are no presets named '{options.preset}'; choose from {names}"
                )
            preset = presets[options.preset]
        for section, values in json.loads(json.dumps(preset)).items():
            if section in settings and isinstance(values, dict):
                settings[section].update(values)

        # the averagine model moved from deisotoping to peak picking; presets
        # saved before that still carry the old key
        legacy = preset.get("deisotoping", {}).get("averagineType")
        if legacy and "averagineType" not in preset.get("peakpicking", {}):
            settings["peakpicking"]["averagineType"] = legacy

    for key, text in options.settings:
        section, name = key.split(".", 1)
        if section not in cli.SETTINGS_SECTIONS:
            raise ConversionError(
                f"--set {key}: the steps use the settings sections "
                f"{', '.join(cli.SETTINGS_SECTIONS)}"
            )
        values = settings[section]
        if name not in values or isinstance(values[name], (list, dict)):
            known = ", ".join(
                sorted(k for k, v in values.items() if not isinstance(v, (list, dict)))
            )
            raise ConversionError(f"--set {key}: {section} has no setting {name}; it has {known}")
        values[name] = setting_value(key, text, values[name])

    return settings


def setting_value(key, text, current):
    """Convert a --set value to the type of the setting it changes."""

    if key in SETTING_CHOICES:
        if text not in SETTING_CHOICES[key]:
            raise ConversionError(
                f"--set {key}: choose from {', '.join(SETTING_CHOICES[key])}"
            )
        return text
    if isinstance(current, str):
        return text

    # switches are stored as 0 and 1
    words = {"true": 1, "yes": 1, "on": 1, "false": 0, "no": 0, "off": 0}
    if text.lower() in words:
        return words[text.lower()]

    try:
        value = int(text) if isinstance(current, int) and text.lstrip("+-").isdigit() else float(text)
    except ValueError:
        raise ConversionError(f"--set {key}: '{text}' is not a number") from None
    if not math.isfinite(value) or (key in POSITIVE_SETTINGS and value <= 0):
        raise ConversionError(f"--set {key}: '{text}' is out of range")
    return value


def shown_settings(settings):
    """The settings the steps use, as text."""

    return json.dumps(
        {section: settings[section] for section in cli.SETTINGS_SECTIONS}, indent=2
    )


# PLANNING
# --------


@dataclasses.dataclass
class Job:
    """One input, where it goes, and why it cannot, if it cannot."""

    path: str
    docType: str | bool
    output: str
    options: cli.ConvertOptions
    problem: str | None = None


def output_path(path, options):
    """Return where one input is written."""

    if options.inPlace:
        return os.path.realpath(path)
    if options.output:
        return options.output

    import mspy

    normalised = os.path.normpath(path)
    if os.path.isdir(normalised):
        folder, baseName = os.path.split(normalised)
    elif os.path.basename(normalised).lower() == "fid":
        # name a single acquisition after its dataset, not after "fid"
        folder, baseName = os.path.split(mspy.datasetDir(normalised))
    else:
        folder, fileName = os.path.split(normalised)
        baseName = os.path.splitext(fileName)[0]

    return os.path.join(
        options.outputDir or folder, baseName + cli.output_extension(options.format)
    )


def check_input(path, docType):
    """Refuse inputs that hold no spectrum to convert."""

    if docType == "session":
        raise ConversionError(
            "a session only lists documents and their view; convert the "
            "documents it lists instead"
        )
    if docType == "FASTA":
        raise ConversionError("a FASTA file holds sequences, not spectra")
    if not docType:
        if os.path.isdir(path):
            raise ConversionError("no Bruker fid data found in this folder")
        raise ConversionError("the document format is not recognised")


def in_place_options(path, docType, options):
    """The options writing one input back in its own format."""

    if docType in ("mzML", "mzXML"):
        raise ConversionError(
            f"mMass would rewrite the {docType} file with only the spectra and "
            "the few details it reads, dropping everything else; write the "
            f"results beside it instead, e.g. --to {docType.lower()} "
            "--output-dir processed"
        )
    if docType not in IN_PLACE_FORMATS:
        what = "Bruker fid data" if docType == "bruker" else f"{docType} files"
        raise ConversionError(
            f"mMass reads {what} but cannot write them; write the results "
            "with --to msd or --to mzml instead"
        )

    name = IN_PLACE_FORMATS[docType]
    if name is None:
        name = os.path.splitext(path)[1].lower().lstrip(".")
    kind = cli.OUTPUT_FORMATS[name]

    if options.peaklist and kind == "ASCII":
        raise ConversionError(
            "--peaklist would replace the spectrum in the file with its peak "
            "list; write the peak list with --to csv --peaklist instead"
        )
    problem = cli.steps_problem(options.steps, kind, name, False, inPlace=True)
    if problem:
        raise ConversionError(problem)

    separator = options.separator
    if kind == "ASCII" and not options.explicitSeparator:
        separator = text_separator(path)

    return dataclasses.replace(options, format=name, separator=separator, peaklist=False)


def text_separator(path):
    """The column separator of a text spectrum, to write it back alike."""

    try:
        with open(path, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or not (line[0].isdigit() or line[0] in "+-."):
                    continue
                for separator in ("\t", ";", ","):
                    if separator in line:
                        return separator
                return " "
    except OSError:
        pass
    return "\t"


def plan(options):
    """Pair every input with its output, or with the reason it cannot be."""

    from gui import doc

    jobs = []
    for path in options.inputs:
        docType = doc.documentType(path)
        job = Job(path, docType, output_path(path, options), options)
        try:
            check_input(path, docType)
            if options.inPlace:
                job.options = in_place_options(path, docType, options)
                if not os.access(job.output, os.W_OK):
                    raise ConversionError("the file cannot be written")
            else:
                if os.path.normcase(job.output) == os.path.normcase(path):
                    raise ConversionError(
                        "the output would replace the input; choose --output-dir"
                        + (", or --in-place" if options.command == cli.PROCESS_COMMAND else "")
                    )
                if os.path.isdir(job.output):
                    raise ConversionError(f"the output {job.output} is a folder")
                if os.path.exists(job.output) and not options.overwrite:
                    raise ConversionError(
                        f"{job.output} already exists (use --overwrite to replace it)"
                    )
        except ConversionError as exc:
            job.problem = str(exc)
        jobs.append(job)

    # two inputs named alike would overwrite each other, and a file given
    # twice would be processed twice
    seen = {}
    for job in jobs:
        key = os.path.normcase(job.output)
        if key in seen and job.problem is None:
            job.problem = f"{seen[key]} is written to the same {job.output}"
        seen.setdefault(key, job.path)

    return jobs


# READING
# -------


def find_scan(scanlist, scanArg):
    """Return the scanlist key the --scan argument names."""

    for scanID in scanlist:
        if str(scanID) == scanArg:
            return scanID

    raise ConversionError(
        f"there is no scan {scanArg}; {scan_choices(scanlist)}"
    )


def scan_choices(scanlist):
    """Describe the scans of a file for an error message."""

    ids = [str(scanID) for scanID in scanlist]
    listed = ", ".join(ids[:LISTED_SCANS])
    if len(ids) > LISTED_SCANS:
        listed += ", ..."
    return f"its {len(ids)} scans are {listed}"


def scan_document(document, scanID):
    """Make a single-spectrum document of one scan of an LC-MS run document."""

    from gui import doc

    single = doc.document()
    for name in ("format", "path", "title", "date", "operator", "contact",
                 "institution", "instrument", "notes"):
        setattr(single, name, getattr(document, name))
    single.spectrum = document.scanCache[scanID]
    single.title += " [%s]" % scanID
    return single


def show_scan(document, scanID):
    """Make one scan of an LC-MS run document its current spectrum."""

    if document.currentScanID is not None:
        document.scanCache[document.currentScanID] = document.spectrum
    if scanID not in document.scanCache:
        raise ConversionError(f"scan {scanID} was not saved in it")
    document.currentScanID = scanID
    document.spectrum = document.scanCache[scanID]


def load_run_scans(document):
    """Load every scan of a run document read from a raw file into its cache."""

    from gui import doc

    parser = doc.makeScanParser(*document.scanSource)
    if parser is None:
        raise ConversionError("the run's scans cannot be read")
    parser.load()
    for scanID in document.scanlist:
        if scanID not in document.scanCache:
            scan = parser.scan(scanID)
            if scan is None or scan is False:
                raise ConversionError(f"scan {scanID} cannot be read")
            document.scanCache[scanID] = scan
    document.scanSource = None


def needs_run(options, settings):
    """Whether one scan of a run is processed with the rest of the run.

    Peaks found in pooled scans come from the whole run, even for one scan.
    """

    if settings is None or not any(step == "findpeaks" for step, _ in options.steps):
        return False

    from gui import processing

    return processing.isPooled(settings)


def read(path, docType, options, settings=None):
    """Read what one input contributes to the output.

    Returns (document, scanID). The document is a gui.doc document: a single
    spectrum, or an LC-MS run with every scan loaded when the whole run is
    written or one scan of it is processed with the others. A file of several
    spectra that are not a run (MGF, Bruker) becomes a run-less document
    holding all of them in scanCache, for mzML and mzXML output only. scanID
    names the scan of a run that is written, or is None when the document is
    written as it is.
    """

    from gui import doc

    kind = options.kind
    wholeFile = kind in ("mzML", "mzXML")
    unreadable = ConversionError("the document is damaged or contains no data")

    # documents holding one spectrum, or an LC-MS run saved as msd
    if docType in ("mSD", "XY"):
        document = doc.readDocument(path, docType)
        if document is None:
            raise unreadable

        if not document.islcms():
            if options.scan is not None:
                raise ConversionError(
                    "the document holds a single spectrum, --scan does not apply"
                )
            return document, None

        if options.scan is not None:
            scanID = find_scan(document.scanlist, options.scan)
            show_scan(document, scanID)
            return document, scanID
        if kind in ("mSD", "mzML", "mzXML"):
            return document, None
        raise ConversionError(
            f"the document is an LC-MS run; choose the spectrum to write as "
            f"{options.format} with --scan ({scan_choices(document.scanlist)})"
        )

    # files that may hold several scans
    parser = doc.makeScanParser(path, docType)
    if parser is None:
        raise unreadable
    scanlist = parser.scanlist()
    if not isinstance(scanlist, dict) or not scanlist:
        raise unreadable

    scanID = None
    if options.scan is not None:
        scanID = find_scan(scanlist, options.scan)
        if docType in doc.RUN_FORMATS and len(scanlist) > 1 and needs_run(options, settings):
            document = doc.readRun(path, docType, scanlist)
            if document is None:
                raise unreadable
            load_run_scans(document)
            show_scan(document, scanID)
            return document, scanID
        document = doc.readDocument(path, docType, scanID)
        scanID = None
    elif len(scanlist) == 1:
        document = doc.readDocument(path, docType)
    elif docType in doc.RUN_FORMATS and (wholeFile or kind == "mSD"):
        document = doc.readRun(path, docType, scanlist)
        if document is not None:
            load_run_scans(document)
    elif wholeFile:
        document = doc.readDocument(path, docType)
        if document is not None:
            parser.load()
            document.scanCache = {}
            for scanID in scanlist:
                scan = parser.scan(scanID)
                if scan is None or scan is False:
                    raise ConversionError(f"scan {scanID} cannot be read")
                document.scanCache[scanID] = scan
            scanID = None
    else:
        what = "acquisitions" if docType == "bruker" else "spectra"
        where = "folder" if os.path.isdir(path) else "file"
        if options.inPlace:
            raise ConversionError(
                f"the file holds {len(scanlist)} spectra, and mMass writes "
                f"{options.format} files of one; write the results with --to "
                "mzml instead"
            )
        raise ConversionError(
            f"the {where} holds {len(scanlist)} {what}; choose the one to write as "
            f"{options.format} with --scan ({scan_choices(scanlist)}), or "
            f"write all of them to mzML or mzXML"
        )

    if document is None:
        raise unreadable
    return document, scanID


def document_scans(document):
    """Every scan a document holds, in order."""

    if not document.scanCache:
        return [document.spectrum]

    # a run's cache starts with the scan shown first, so follow the scan list
    if document.currentScanID is not None:
        document.scanCache[document.currentScanID] = document.spectrum
    order = document.scanlist or document.scanCache
    return [document.scanCache[scanID] for scanID in order if scanID in document.scanCache]


# PROCESSING
# ----------


def cached_scans(document, scanIDs):
    """Scans of a run for pooling: every scan was loaded when it was read."""

    return {scanID: document.scanCache.get(scanID) for scanID in scanIDs}


def apply_steps(document, scanID, options, settings):
    """Run the processing steps on a document read by read(), in place.

    Steps run on every scan written: the one scan named by scanID, or every
    scan of the document. Scans lacking the data a step needs are skipped, as
    the GUI skips them, but a step none of them can take is an error.
    """

    from gui import processing

    scans = [document.scanCache[scanID]] if scanID is not None else document_scans(document)
    what = "spectra" if len(scans) > 1 else "spectrum"

    def with_profile(step):
        usable = [scan for scan in scans if scan.hasprofile()]
        if not usable:
            raise ConversionError(
                f"--{step} needs profile data, and the {what} "
                f"{'have' if len(scans) > 1 else 'has'} only a peak list"
            )
        return usable

    for step, argument in options.steps:
        if step == "crop":
            low, high = argument
            for scan in scans:
                scan.crop(low, high)
            processing.cropNotations(document, low, high)
            if not any(scan.hasprofile() or scan.haspeaks() for scan in scans):
                raise ConversionError(
                    f"no data is left after --crop {low:g}:{high:g}"
                )
            continue

        if step == "baseline":
            for scan in with_profile(step):
                processing.subtractBaseline(scan, settings)

        elif step == "smooth":
            for scan in with_profile(step):
                processing.smoothScan(scan, settings)

        elif step == "findpeaks":
            usable = with_profile(step)
            if document.islcms() and processing.isPooled(settings):
                processing.pickPeaksPooled(
                    document, settings, cached_scans, allScans=scanID is None
                )
            else:
                for scan in usable:
                    processing.pickPeaks(scan, settings)

        elif step == "deisotope":
            usable = [scan for scan in scans if scan.haspeaks()]
            if not usable:
                raise ConversionError(
                    f"--deisotope needs peaks, and the {what} "
                    f"{'have' if len(scans) > 1 else 'has'} none; find them first with --findpeaks"
                )
            for scan in usable:
                processing.deisotopeScan(scan, settings)

        elif step == "normalize":
            for scan in scans:
                scan.normalize()

        processing.clearNotations(document)


# WRITING
# -------


def write(document, path, options):
    """Write a document read by read() in the requested format.

    The output is written beside its destination under a temporary name and
    moved into place once complete, so a failure never leaves a half-written
    file, nor destroys the input processed in place.
    """

    kind = options.kind
    spectrum = document.spectrum

    if kind in ("mSD", "mzML", "mzXML"):
        if not any(scan.hasprofile() or scan.haspeaks() for scan in document_scans(document)):
            raise ConversionError("the document contains no data")

    if kind == "mSD":
        text = document.msd()
        with replacing(path) as temporary:
            write_text(temporary, text)

    elif kind in ("mzML", "mzXML"):
        import mspy

        scans = document_scans(document)
        info = {
            "title": document.title,
            "operator": document.operator,
            "contact": document.contact,
            "institution": document.institution,
            "instrument": document.instrument,
            "date": document.date,
        }
        writer = mspy.writeMZML if kind == "mzML" else mspy.writeMZXML
        with replacing(path) as temporary:
            writer(scans if len(scans) > 1 else scans[0], info).write(temporary)

    elif kind == "ASCII" and options.peaklist:
        if not spectrum.haspeaks():
            raise ConversionError(
                "the spectrum has no peak list to write; "
                + (
                    "find peaks with --findpeaks"
                    if options.command == cli.PROCESS_COMMAND
                    else f"find peaks with mmass {cli.PROCESS_COMMAND} --findpeaks"
                )
            )
        from gui import config, doc

        columns = options.columns or [
            name for name in doc.PEAKLIST_COLUMNS if name in config.export["peaklistColumns"]
        ]
        text = doc.peaklistText(spectrum.peaklist, columns, options.separator, headers=True)
        with replacing(path) as temporary:
            write_text(temporary, text)

    elif kind == "ASCII":
        if not spectrum.hasprofile():
            raise ConversionError(
                f"the spectrum has no profile data to write as {options.format}, "
                f"only a peak list; write it with --peaklist, or as mgf, mzml or msd"
            )
        separator = options.separator
        text = "".join("%f%s%f\n" % (mz, separator, ai) for mz, ai in spectrum.profile)
        with replacing(path) as temporary:
            write_text(temporary, text)

    elif kind == "MGF":
        if not spectrum.haspeaks():
            raise ConversionError(
                "the spectrum has no peak list to write as mgf; "
                + (
                    "find peaks with --findpeaks"
                    if options.command == cli.PROCESS_COMMAND
                    else f"find peaks with mmass {cli.PROCESS_COMMAND} --findpeaks"
                )
                + ", or write the profile as txt, mzml or msd"
            )
        text = mgf(document)
        with replacing(path) as temporary:
            write_text(temporary, text)

    elif kind == "image":
        if not (spectrum.hasprofile() or spectrum.haspeaks()):
            raise ConversionError("the spectrum contains no data to draw")
        with replacing(path) as temporary:
            render_image(document, temporary, options)


@contextlib.contextmanager
def replacing(path):
    """Write to a temporary file that replaces path once written."""

    folder, name = os.path.split(path)
    base, extension = os.path.splitext(name)
    try:
        handle, temporary = tempfile.mkstemp(prefix=f".{base}.", suffix=extension, dir=folder)
    except OSError as exc:
        raise ConversionError(f"cannot write {path}: {exc.strerror}") from None
    os.close(handle)

    try:
        yield temporary

        # a replaced file keeps its permissions, a new one gets the usual ones
        if os.path.exists(path):
            shutil.copymode(path, temporary)
        else:
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(temporary, 0o666 & ~umask)
        os.replace(temporary, path)
    except OSError as exc:
        raise ConversionError(f"cannot write {path}: {exc.strerror}") from None
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def write_text(path, text):
    try:
        with open(path, "wb") as f:
            f.write(text.encode("utf-8"))
    except OSError as exc:
        raise ConversionError(f"cannot write {path}: {exc.strerror}") from None


def mgf(document):
    """Format a document's peak list as MGF."""

    spectrum = document.spectrum
    buff = "BEGIN IONS\n"
    buff += "TITLE=%s\n" % document.title.replace("\n", " ")
    if spectrum.precursorMZ:
        buff += "PEPMASS=%f\n" % spectrum.precursorMZ
    if spectrum.precursorCharge:
        buff += "CHARGE=%d%s\n" % (
            abs(spectrum.precursorCharge),
            "-" if spectrum.precursorCharge < 0 else "+",
        )
    for peak in spectrum.peaklist:
        buff += "%f %f\n" % (peak.mz, peak.intensity)
    buff += "END IONS\n"
    return buff


# IMAGES
# ------

_app = None


def render_image(document, path, options):
    """Draw a document's spectrum into an image file."""

    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise ConversionError(
            "drawing images needs a graphical display; on a machine without "
            "one, run the command under xvfb-run"
        )

    import wx

    # the canvas draws off-screen, but wx still needs an application
    global _app
    if wx.GetApp() is None:
        _app = wx.App(False)

    from mspy import plot_canvas, plot_objects
    from gui import config, mwx, panel_spectrum

    dark = options.dark
    plot_objects.force_dark_mode(dark)

    # the document takes the colour the GUI gives the first document it opens
    colour = list(config.colours[0])
    document.colour = mwx.invertColour(colour) if dark else colour

    frame = wx.Frame(None)
    try:
        canvas = plot_canvas.canvas(frame)
        canvas.setProperties(**plot_canvas.THEME_COLOURS[dark])
        panel_spectrum.applyCanvasConfig(canvas)

        container = plot_objects.container([])
        spectrum = plot_objects.spectrum(document.spectrum)
        container.append(spectrum)
        panel_spectrum.applySpectrumConfig(spectrum, document, current=True)
        canvas.draw(container)
        if options.mzRange:
            draw_range(canvas, container, options.mzRange)

        width, height = options.size
        if options.format == "svg":
            canvas.getSVG(path, width, height)
            if not os.path.getsize(path):
                raise ConversionError(f"cannot write {path}")
            return

        fileTypes = {
            "png": wx.BITMAP_TYPE_PNG,
            "jpg": wx.BITMAP_TYPE_JPEG,
            "jpeg": wx.BITMAP_TYPE_JPEG,
            "tif": wx.BITMAP_TYPE_TIF,
            "tiff": wx.BITMAP_TYPE_TIF,
            "bmp": wx.BITMAP_TYPE_BMP,
        }
        image = canvas.getBitmap(width, height).ConvertToImage()
        image.SetOption(wx.IMAGE_OPTION_QUALITY, "100")
        if not image.SaveFile(path, fileTypes[options.format]):
            raise ConversionError(f"cannot write {path}")
    finally:
        frame.Destroy()


def draw_range(canvas, container, mzRange):
    """Redraw a canvas showing only an m/z range.

    The range may reach past the data, so that images of several spectra can
    share their axis; it must overlap it, though. Intensities are scaled to
    the range when the GUI autoscales them.
    """

    minX, maxX = canvas.getMaxXRange()
    low = minX if mzRange[0] is None else mzRange[0]
    high = maxX if mzRange[1] is None else mzRange[1]
    if low >= high or low >= maxX or high <= minX:
        shown = ":".join("" if end is None else f"{end:g}" for end in mzRange)
        raise ConversionError(
            f"the m/z range {shown} holds no data; the spectrum spans "
            f"{minX:.4f} to {maxX:.4f}"
        )

    if canvas.properties["autoScaleY"]:
        yAxis = canvas.getMaxYRange(max(low, minX), min(high, maxX))
    else:
        yAxis = canvas.getMaxYRange()
    canvas.draw(container, (low, high), yAxis)


# COMMAND
# -------


def run(options):
    """Convert or process every input; return the exit status of the command."""

    command = options.command

    settings = None
    if options.steps or options.showSettings:
        try:
            settings = processing_settings(options)
        except ConversionError as exc:
            error(str(exc), command)
            return 2
    if options.showSettings:
        print(shown_settings(settings))
        return 0

    failed = 0
    for job in plan(options):
        try:
            if job.problem:
                raise ConversionError(job.problem)
            document, scanID = read(job.path, job.docType, job.options, settings)
            if options.steps:
                apply_steps(document, scanID, job.options, settings)
            if scanID is not None:
                document = scan_document(document, scanID)
            if options.outputDir:
                os.makedirs(options.outputDir, exist_ok=True)
            write(document, job.output, job.options)
        except ConversionError as exc:
            error(f"{job.path}: {exc}", command)
            failed += 1
            continue
        except Exception as exc:
            error(f"{job.path}: {command} failed: {exc!r}", command)
            failed += 1
            continue

        if options.inPlace:
            print(f"{job.path}: processed in place")
        else:
            print(f"{job.path} -> {job.output}")

    return 1 if failed else 0
