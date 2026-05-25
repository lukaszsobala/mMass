# load main config and libs
from gui import config
from gui import libs

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


class mMass(wx.App):
    """Run mMass run..."""

    def OnInit(self):
        """Init application."""

        # set some special wx params
        mwx.appInit()

        # init frame
        self.frame = mainFrame(None, -1, "mMass")

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

    def MacOpenFile(self, path):
        """ "Enable drag/drop under Mac."""

        if path != "mmass.py":
            self.frame.onDocumentOpen(path=path)

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
        socketserver.TCPServer.__init__(
            self, server_address, RequestHandlerClass, False
        )

    # ----

    def serve_forever(self):
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

        # get command
        command = self.request.recv(1024)
        self.request.sendall("Command received...\n")

        # raise main app frame
        self.server.app.Raise()

        # open path
        self.server.app.onServerCommand(command)

    # ----


def main():
    server = None

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

            app = mMass(0)
            app.MainLoop()

    # skip server
    else:
        app = mMass(0)
        app.MainLoop()


if __name__ == "__main__":
    main()
