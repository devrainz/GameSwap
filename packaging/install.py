import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.devrainz.GameSwap"
MODULES = ("gameswap.py", "gui.py", "config.py", "state.py", "steam.py", "mover.py",
           "verify.py", "tui.py", "input_handler.py", "transfer_ui.py", "truckswap.py")


def install(prefix, destdir):
    prefix = Path(prefix)
    if not prefix.is_absolute():
        raise ValueError("Installation prefix must be absolute.")
    base = Path(destdir) / prefix.relative_to("/")
    data = base / "share/gameswap"
    data.mkdir(parents=True, exist_ok=True)
    for name in MODULES:
        shutil.copyfile(ROOT / name, data / name)
        (data / name).chmod(0o644)
    assets = data / "assets"
    assets.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "assets/logo.png", assets / "logo.png")
    for source, relative in ((ROOT / "assets/logo.png", f"share/icons/hicolor/512x512/apps/{APP_ID}.png"),
                             (ROOT / f"data/{APP_ID}.metainfo.xml", f"share/metainfo/{APP_ID}.metainfo.xml"),
                             (ROOT / "LICENSE", "share/licenses/gameswap/LICENSE")):
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o644)
    launcher = base / "bin/gameswap"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                        'sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "share/gameswap"))\n'
                        'from gameswap import main\nraise SystemExit(main())\n', encoding="utf-8")
    launcher.chmod(0o755)
    desktop = (ROOT / f"data/{APP_ID}.desktop").read_text(encoding="utf-8")
    if str(prefix) not in ("/usr", "/usr/local", "/app"):
        command = str(prefix / "bin/gameswap")
        command = command.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
        desktop = desktop.replace("Exec=gameswap", f'Exec="{command}"')
    target = base / f"share/applications/{APP_ID}.desktop"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop, encoding="utf-8")
    target.chmod(0o644)
    print(f"Installed GameSwap under {base}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="/usr/local")
    parser.add_argument("--destdir", default="/")
    args = parser.parse_args()
    install(args.prefix, args.destdir)
