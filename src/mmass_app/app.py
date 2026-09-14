"""Entry point of the mmass command.

Only the arguments are parsed here. The GUI (gui_app) and the converter are
imported once it is known which one is wanted, so --help answers at once and a
conversion or batch processing never starts the GUI.
"""

import sys

from mmass_app import cli


def main(argv=None):
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
