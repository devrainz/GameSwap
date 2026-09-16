import argparse
import hashlib
import json
import re
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_ID = "io.github.devrainz.GameSwap"


def prepare(repository):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Use a GitHub repository in owner/name format.")
    version = re.search(r'^VERSION = "([0-9.]+)"', (ROOT / "gameswap.py").read_text(), re.M)[1]
    DIST.mkdir(exist_ok=True)
    archive = DIST / f"GameSwap-{version}.tar.gz"
    files = [*ROOT.glob("*.py"), ROOT / "Makefile", ROOT / "install.sh", ROOT / "README.md",
             ROOT / "PACKAGING.md", ROOT / "TESTING.md", ROOT / "LICENSE", ROOT / ".gitignore"]
    for folder in ("assets", "data", "packaging", "snap", "tests", ".github"):
        files.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    with tarfile.open(archive, "w:gz") as output:
        for path in sorted(set(files)):
            output.add(path, arcname=f"GameSwap-{version}/{path.relative_to(ROOT)}", recursive=False)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    url = f"https://github.com/{repository}/releases/download/v{version}/{archive.name}"
    aur = DIST / "aur"
    aur.mkdir(exist_ok=True)
    pkgbuild = (ROOT / "packaging/aur/PKGBUILD").read_text()
    pkgbuild = pkgbuild.replace("REPLACE_WITH_RELEASE_SHA256", digest).replace("devrainz/GameSwap", repository)
    (aur / "PKGBUILD").write_text(pkgbuild)
    manifest = json.loads((ROOT / f"packaging/flatpak/{APP_ID}.json").read_text())
    manifest["modules"][-1]["sources"] = [{"type": "archive", "url": url, "sha256": digest}]
    flathub = DIST / "flathub"
    flathub.mkdir(exist_ok=True)
    (flathub / f"{APP_ID}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copyfile(ROOT / "packaging/flatpak/flathub.json", flathub / "flathub.json")
    (DIST / "SOURCE-SHA256.txt").write_text(f"{digest}  {archive.name}\n")
    print(f"Source: {archive}\nSHA256: {digest}\nAUR: {aur}\nFlathub: {flathub}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default="devrainz/GameSwap")
    prepare(parser.parse_args().repository)
