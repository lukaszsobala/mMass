# load main config and libs
from gui import config

# Opt into per-monitor DPI awareness before wx initialises, otherwise Windows
# bitmap-stretches the whole UI on HiDPI displays (blurry text and icons).
from gui import display_scale

display_scale.enable_high_dpi_awareness()

# load libs
import os
import sys
import threading
import socket
import socketserver
import faulthandler
import wx

# load modules
from gui import mwx
from gui.main_frame import mainFrame


_FAULT_LOG_HANDLE = None


def _filter_benign_gtk_warnings():
    """Silence a benign but noisy GTK-on-Wayland warning.

    GTK 3.24 emits

        Gdk-CRITICAL **: gdk_wayland_window_set_dbus_properties_libgtk_only:
        assertion 'GDK_IS_WAYLAND_WINDOW (window)' failed

    every time a window, dialog, popup menu or tooltip is shown on Wayland. It
    is a known upstream GTK bug with no functional impact -- the property-setting
    simply no-ops after the assertion -- but during normal use it floods stderr.

    GTK writes it from C straight to file descriptor 2, so a Python-level
    sys.stderr wrapper cannot catch it. We splice a pipe in front of fd 2 and
    drop only that exact line in a background thread, passing every other byte
    (real errors, tracebacks, faulthandler output) through unchanged.

    Set MMASS_KEEP_GTK_WARNINGS=1 to disable the filter (e.g. when debugging).
    """

    if not sys.platform.startswith("linux"):
        return
    if not os.environ.get("WAYLAND_DISPLAY"):
        return
    if os.environ.get("MMASS_KEEP_GTK_WARNINGS", "0") == "1":
        return

    try:
        saved_fd = os.dup(2)
        read_fd, write_fd = os.pipe()
        os.dup2(write_fd, 2)
        os.close(write_fd)
    except OSError:
        return

    needle = b"gdk_wayland_window_set_dbus_properties_libgtk_only"

    def _pump():
        with os.fdopen(read_fd, "rb", buffering=0) as reader:
            buf = b""
            while True:
                chunk = reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if needle in line:
                        continue
                    os.write(saved_fd, line + b"\n")
            if buf:
                os.write(saved_fd, buf)

    threading.Thread(
        target=_pump, name="mmass-stderr-filter", daemon=True
    ).start()


def _setup_faulthandler():
    """Enable faulthandler for temporary crash diagnostics.

    Set MMASS_FAULTHANDLER=1 to enable.
    """

    if os.environ.get("MMASS_FAULTHANDLER", "0") != "1":
        return

    global _FAULT_LOG_HANDLE
    try:
        log_path = os.path.abspath("mmass-faulthandler.log")
        _FAULT_LOG_HANDLE = open(log_path, "a", buffering=1)
        _FAULT_LOG_HANDLE.write("\n=== mMass faulthandler enabled ===\n")
        _FAULT_LOG_HANDLE.write(f"pid={os.getpid()}\n")
        _FAULT_LOG_HANDLE.flush()
        faulthandler.enable(file=_FAULT_LOG_HANDLE, all_threads=True)
    except Exception:
        # Fall back to stderr if file setup fails.
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            pass


def _collect_startup_document_paths(argv):
    """Return only valid document paths from launcher command-line args."""

    ignored_placeholders = {"%f", "%F", "%u", "%U", "%i", "%c", "%k"}
    paths = []
    for item in argv:
        candidate = item.strip().strip('"')
        if not candidate:
            continue
        if candidate in ignored_placeholders:
            continue
        if os.path.exists(candidate):
            paths.append(candidate)
    return paths


def _show_dpi_debug(frame):
    """Show a HiDPI diagnostics dialog (enabled via MMASS_DPI_DEBUG=1)."""

    from gui import display_scale, images

    lines = ["mMass HiDPI diagnostics", ""]
    for key, value in display_scale.debug_report().items():
        lines.append(f"{key}: {value}")

    lines.append("")
    for label, getter in (
        ("frame.GetDPIScaleFactor", frame.GetDPIScaleFactor),
        ("frame.GetContentScaleFactor", frame.GetContentScaleFactor),
    ):
        try:
            lines.append(f"{label}: {getter()}")
        except Exception as exc:
            lines.append(f"{label}: err: {exc}")

    try:
        bmp = images.lib["toolsOpen"]
        lines.append(f"lib['toolsOpen'] size: {bmp.GetWidth()}x{bmp.GetHeight()}")
    except Exception as exc:
        lines.append(f"lib['toolsOpen'] size: err: {exc}")

    try:
        lines.append(f"wx.SMALL_FONT pt: {wx.SMALL_FONT.GetPointSize()}")
    except Exception:
        pass

    wx.MessageBox("\n".join(lines), "mMass DPI debug", wx.OK | wx.ICON_INFORMATION)


class mMass(wx.App):
    """Run mMass run..."""

    def OnInit(self):
        """Init application."""

        # set some special wx params
        mwx.appInit()

        # init frame
        self.frame = mainFrame(None, -1, "mMass")

        # optional HiDPI diagnostics
        if os.environ.get("MMASS_DPI_DEBUG", "0") == "1":
            _show_dpi_debug(self.frame)

        # show frame
        self.SetTopWindow(self.frame)
        try:
            wx.GetApp().Yield()
        except Exception:
            pass

        # Open only valid file paths from command line. Some launchers
        # (including Wine desktop integrations) pass non-file placeholders.
        startup_paths = _collect_startup_document_paths(sys.argv[1:])
        if startup_paths:
            self.frame.onDocumentDropped(paths=startup_paths)

        return True

    # ----

    def OnExit(self):
        """Exit application."""

        return super().OnExit()

    # ----

    def MacOpenFile(self, fileName):
        """ "Enable drag/drop under Mac."""

        if fileName != "mmass.py":
            self.frame.onDocumentOpen(path=fileName)

    # ----

    def MacReopenApp(self):
        """Called when the doc icon is clicked."""

        try:
            self.GetTopWindow().Raise()
        except Exception:
            pass

    # ----


class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """TCP communication server."""

    def __init__(self, server_address, RequestHandlerClass):
        self.allow_reuse_address = True
        self.stopped = False
        self.app: mainFrame | None = None
        socketserver.TCPServer.__init__(
            self, server_address, RequestHandlerClass, False
        )

    # ----

    def serve_forever(self, poll_interval=0.5):
        while not self.stopped:
            self.handle_request()

    # ----

    def force_stop(self):
        self.server_close()
        self.stopped = True

    # ----


class TCPServerHandler(socketserver.BaseRequestHandler):
    """TCP communication server handler."""

    def handle(self):
        server = self.server
        if not isinstance(server, TCPServer):
            return

        # get command
        command = self.request.recv(1024).decode("utf-8", errors="ignore")
        self.request.sendall(b"Command received...\n")

        if server.app is None:
            return

        # raise main app frame
        server.app.Raise()

        # open path
        server.app.onServerCommand(command)

    # ----


def main():
    server = None

    _filter_benign_gtk_warnings()
    _setup_faulthandler()

    # use server
    if False:  # TODO: fix this, having worked out what the server is for

        # init server params
        HOST = socket.gethostname()
        PORT = config.main["serverPort"]

        # get command
        command = ""
        if len(sys.argv) > 1:
            command = sys.argv[-1]

        # try to connect to existing server
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print(f"host: {HOST}")
            print(f"port: {PORT}")
            sock.connect((HOST, PORT))
            sock.sendall(command)
            sock.close()
            sys.exit()

        # init new app and server
        except socket.error:

            server = TCPServer((HOST, PORT), TCPServerHandler)
            server.server_bind()
            server.server_activate()
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.setDaemon(True)
            server_thread.start()

            app = mMass(False)
            server.app = app.frame
            app.MainLoop()

    # skip server
    else:
        app = mMass(False)
        app.MainLoop()


if __name__ == "__main__":
    main()
