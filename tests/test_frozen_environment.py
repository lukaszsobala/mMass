"""Behaviour that matters in the packaged (frozen) Linux build."""

import sys

import pytest

from mmass_app import app


@pytest.fixture
def frozen_linux(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")


def test_bundle_library_path_is_dropped(frozen_linux):
    environ = {"LD_LIBRARY_PATH": "/opt/mmass/_internal"}

    app.restore_library_path(environ)

    assert environ == {"PYINSTALLER_RESET_ENVIRONMENT": "1"}


def test_user_library_path_is_restored(frozen_linux):
    environ = {
        "LD_LIBRARY_PATH": "/opt/mmass/_internal:/home/u/lib",
        "LD_LIBRARY_PATH_ORIG": "/home/u/lib",
    }

    app.restore_library_path(environ)

    assert environ == {
        "LD_LIBRARY_PATH": "/home/u/lib",
        "PYINSTALLER_RESET_ENVIRONMENT": "1",
    }


def test_library_path_untouched_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    environ = {"LD_LIBRARY_PATH": "/usr/local/lib"}

    app.restore_library_path(environ)

    assert environ == {"LD_LIBRARY_PATH": "/usr/local/lib"}


def test_multiprocessing_helpers_are_diverted_first(monkeypatch):
    # a frozen build runs its own executable again for multiprocessing's
    # helper processes; unless freeze_support() runs before the arguments
    # are parsed, each helper starts another (empty) mMass window
    import multiprocessing

    class Diverted(Exception):
        pass

    def freeze_support():
        raise Diverted

    def parse_args(argv):
        raise AssertionError("arguments parsed before freeze_support()")

    monkeypatch.setattr(multiprocessing, "freeze_support", freeze_support)
    monkeypatch.setattr(app.cli, "parse_args", parse_args)

    helper = "from multiprocessing.resource_tracker import main;main(5)"
    with pytest.raises(Diverted):
        app.main(["-B", "-S", "-I", "-c", helper])


def test_unwritable_config_directory_reports_failure(tmp_path):
    # e.g. the read-only bundled configs/ of a packaged install: a failed
    # write must be reported, not raised (it used to crash the GUI at start)
    config = pytest.importorskip(
        "gui.config", reason="GUI dependencies (xdgenvpy) not available"
    )
    missing = tmp_path / "missing" / "config.json"

    assert config.write_file_atomically(str(missing), b"{}") is False
