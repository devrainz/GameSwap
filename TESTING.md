# Testing GameSwap

Run the engine suite:

```bash
python3 -m unittest discover -s tests -v
```

Run the GUI smoke test on a desktop or virtual display:

```bash
dbus-run-session -- xvfb-run -a python3 tests/gui_smoke.py
```

The GUI smoke test starts the Adwaita application, creates its main window, and exits after a short timeout. It does not scan or modify Steam libraries.

Before a real swap, verify that Steam is closed, both drives are mounted, each library is a separate non-nested path, and the destination has room for a complete verified copy. Test first with small disposable Steam libraries.
