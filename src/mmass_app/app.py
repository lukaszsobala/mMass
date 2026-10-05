"""Entry point of the mmass command.

Only the arguments are parsed here. The GUI (gui_app) and the converter are
imported once it is known which one is wanted, so --help answers at once and a
conversion or batch processing never starts the GUI.
"""

import os
import sys

from mmass_app import cli


def restore_library_path(environ=os.environ):
    """Give programs mMass starts the user's LD_LIBRARY_PATH back.

    The PyInstaller bootloader of the Linux packages puts the bundle first on
    LD_LIBRARY_PATH (saving any earlier value as LD_LIBRARY_PATH_ORIG), and
    child processes inherit it: the browser or PDF viewer mMass opens would
    then load the bundle's libgomp, libpython, wx, ... instead of their own.
    The dynamic loader reads the variable only at startup, so restoring it
    does not change how mMass itself finds the bundled libraries.
    """

    if not (getattr(sys, "frozen", False) and sys.platform.startswith("linux")):
        return
    original = environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        environ.pop("LD_LIBRARY_PATH", None)
    else:
        environ["LD_LIBRARY_PATH"] = original


def main(argv=None):
    restore_library_path()
    if argv is None:
        argv = sys.argv[1:]

    if argv[:1] in ([cli.CONVERT_COMMAND], [cli.PROCESS_COMMAND]):
        options = cli.parse_convert_args(argv[1:], command=argv[0])

        from mmass_app import convert

        return convert.run(options)

    options = cli.parse_args(argv)

    from mmass_app import gui_app

    return gui_app.run(options)


if __name__ == "__main__":
    sys.exit(main())
