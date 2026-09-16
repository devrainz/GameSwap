import json
import os
from pathlib import Path
from state import atomic_write

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONFIG_PATH = CONFIG_HOME / "gameswap" / "config.json"
LEGACY_CONFIG = CONFIG_HOME / "truckswap" / "config.json"
DEFAULT_CONFIG = {"main_library": None, "backup_library": None}


def normalize_library(path):
    library = Path(path).expanduser().resolve(strict=True)
    if library.name == "steamapps" and (library / "common").is_dir():
        library = library.parent
    steamapps = library / "steamapps"
    common = steamapps / "common"
    if not common.is_dir() or steamapps.is_symlink() or common.is_symlink():
        raise ValueError("Choose a Steam library containing a real steamapps/common directory.")
    return library


def save_config(config):
    atomic_write(CONFIG_PATH, config)


def load_config():
    path = CONFIG_PATH if CONFIG_PATH.exists() else LEGACY_CONFIG
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return {key: data.get(key) for key in DEFAULT_CONFIG}
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read {path}: {error}") from error


def set_library(library_type, path):
    if library_type not in DEFAULT_CONFIG:
        raise ValueError("Unknown library setting.")
    library = normalize_library(path)
    config = load_config()
    other_key = "backup_library" if library_type == "main_library" else "main_library"
    other = config.get(other_key)
    if other:
        other = Path(other).expanduser().resolve()
        if other == library or other in library.parents or library in other.parents:
            raise ValueError("Choose two separate, non-nested libraries.")
    config[library_type] = str(library)
    save_config(config)


def is_configured():
    return all(load_config().values())
