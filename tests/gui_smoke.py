import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="gameswap-config-"))
os.environ.setdefault("XDG_STATE_HOME", tempfile.mkdtemp(prefix="gameswap-state-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib
from gui import GameSwapApplication


def stop(application):
    application.quit()
    return GLib.SOURCE_REMOVE


application = GameSwapApplication()
GLib.timeout_add(500, stop, application)
raise SystemExit(application.run(["gameswap-gui-smoke"]))
