"""Convert documents between formats without the GUI (mmass convert).

Documents are read with the same code the GUI opens them with (gui.doc) and
written with the same writers it saves and exports with. Images are drawn on an
off-screen spectrum canvas styled like the spectrum panel, which needs a wx.App
and hence a display, but no window is ever shown.

Nothing here may assign to gui.config: its sections save themselves on every
change, and a conversion must never rewrite the user's settings.
"""

import os
import sys

from mmass_app import cli

# how many scan IDs an error message lists
LISTED_SCANS = 10


class ConversionError(Exception):
    """A document that cannot be converted as asked."""


def error(message):
    print(f"mmass {cli.CONVERT_COMMAND}: error: {message}", file=sys.stderr)


# PLANNING
# --------


def output_path(path, options):
    """Return where one input is written."""

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


def plan(options):
    """Pair every input with its output, or with the reason it cannot be.

    Returns a list of (input, docType, output, problem) tuples, problem being
    None for the inputs that can be converted.
    """

    from gui import doc

    plans = []
    for path in options.inputs:
        docType = doc.documentType(path)
        output = output_path(path, options)
        problem = None
        try:
            check_input(path, docType)
            if os.path.normcase(output) == os.path.normcase(path):
                raise ConversionError(
                    "the output would replace the input; choose --output-dir"
                )
            if os.path.isdir(output):
                raise ConversionError(f"the output {output} is a folder")
            if os.path.exists(output) and not options.overwrite:
                raise ConversionError(
                    f"{output} already exists (use --overwrite to replace it)"
                )
        except ConversionError as exc:
            problem = str(exc)
        plans.append([path, docType, output, problem])

    # two inputs named alike would overwrite each other
    seen = {}
    for entry in plans:
        key = os.path.normcase(entry[2])
        if key in seen and entry[3] is None:
            entry[3] = f"{seen[key]} is written to the same {entry[2]}"
        seen.setdefault(key, entry[0])

    return [tuple(entry) for entry in plans]


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


def read(path, docType, options):
    """Read what one input contributes to the output.

    Returns a gui.doc document: a single spectrum, or an LC-MS run with every
    scan loaded when the whole run is written. A file of several spectra that
    are not a run (MGF, Bruker) becomes a run-less document holding all of
    them in scanCache, for mzML and mzXML output only.
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
            return document

        if options.scan is not None:
            scanID = find_scan(document.scanlist, options.scan)
            if scanID == document.currentScanID:
                document.scanCache[scanID] = document.spectrum
            if scanID not in document.scanCache:
                raise ConversionError(f"scan {options.scan} was not saved in it")
            return scan_document(document, scanID)
        if kind in ("mSD", "mzML", "mzXML"):
            return document
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

    if options.scan is not None:
        document = doc.readDocument(path, docType, find_scan(scanlist, options.scan))
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
    else:
        what = "acquisitions" if docType == "bruker" else "spectra"
        where = "folder" if os.path.isdir(path) else "file"
        raise ConversionError(
            f"the {where} holds {len(scanlist)} {what}; choose the one to write as "
            f"{options.format} with --scan ({scan_choices(scanlist)}), or "
            f"write all of them to mzML or mzXML"
        )

    if document is None:
        raise unreadable
    return document


def document_scans(document):
    """Every scan a document holds, in order."""

    if not document.scanCache:
        return [document.spectrum]

    # a run's cache starts with the scan shown first, so follow the scan list
    if document.currentScanID is not None:
        document.scanCache[document.currentScanID] = document.spectrum
    order = document.scanlist or document.scanCache
    return [document.scanCache[scanID] for scanID in order if scanID in document.scanCache]


# WRITING
# -------


def write(document, path, options):
    """Write a document read by read() in the requested format."""

    kind = options.kind
    spectrum = document.spectrum

    if kind == "mSD":
        if not any(scan.hasprofile() or scan.haspeaks() for scan in document_scans(document)):
            raise ConversionError("the document contains no data")
        write_text(path, document.msd())

    elif kind in ("mzML", "mzXML"):
        import mspy

        scans = document_scans(document)
        if not any(scan.hasprofile() or scan.haspeaks() for scan in scans):
            raise ConversionError("the document contains no data")
        info = {
            "title": document.title,
            "operator": document.operator,
            "contact": document.contact,
            "institution": document.institution,
            "instrument": document.instrument,
            "date": document.date,
        }
        writer = mspy.writeMZML if kind == "mzML" else mspy.writeMZXML
        try:
            writer(scans if len(scans) > 1 else scans[0], info).write(path)
        except OSError as exc:
            raise ConversionError(f"cannot write {path}: {exc.strerror}") from None

    elif kind == "ASCII":
        if not spectrum.hasprofile():
            raise ConversionError(
                f"the spectrum has no profile data to write as {options.format}, "
                "only a peak list; write it as mgf, mzml or msd instead"
            )
        separator = options.separator
        write_text(
            path,
            "".join("%f%s%f\n" % (mz, separator, ai) for mz, ai in spectrum.profile),
        )

    elif kind == "MGF":
        if not spectrum.haspeaks():
            raise ConversionError(
                "the spectrum has no peak list to write as mgf; pick peaks in "
                "mMass first, or write the profile as txt, mzml or msd"
            )
        write_text(path, mgf(document))

    elif kind == "image":
        if not (spectrum.hasprofile() or spectrum.haspeaks()):
            raise ConversionError("the spectrum contains no data to draw")
        render_image(document, path, options)


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

        width, height = options.size
        if options.format == "svg":
            canvas.getSVG(path, width, height)
            if not os.path.exists(path):
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


# COMMAND
# -------


def run(options):
    """Convert every input; return the exit status of the command."""

    failed = 0
    for path, docType, output, problem in plan(options):
        try:
            if problem:
                raise ConversionError(problem)
            document = read(path, docType, options)
            if options.outputDir:
                os.makedirs(options.outputDir, exist_ok=True)
            write(document, output, options)
        except ConversionError as exc:
            error(f"{path}: {exc}")
            failed += 1
            continue
        except Exception as exc:
            error(f"{path}: conversion failed: {exc!r}")
            failed += 1
            continue

        print(f"{path} -> {output}")

    return 1 if failed else 0
