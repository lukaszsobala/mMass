"""mMass application package."""


def main():
    """Start mMass; imported lazily so mmass_app.cli stays free of wxPython."""

    from .app import main as _main

    return _main()
