"""Compatibility shim for legacy top-level module usage.

Canonical module location is `mmass_app.app`.
"""

from mmass_app.app import *  # noqa: F401,F403


if __name__ == "__main__":
    main()
