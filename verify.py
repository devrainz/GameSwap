import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path
from config import normalize_library

SPACE_MARGIN = 16 * 1024 * 1024


def check_rsync():
    return shutil.which("rsync") is not None


def is_steam_running():
    command = ["ps", "-eo", "comm="]
    if Path("/.flatpak-info").exists():
        command = ["flatpak-spawn", "--host", *command]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Cannot check whether Steam is running. Check host-process permissions; transfer blocked.") from error
    return any(name.strip().casefold() in {"steam", "steamwebhelper", "steam.exe", "steamservice.exe"}
               for name in result.stdout.splitlines())


def tree_entries(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Not a regular directory: {directory}")
    entries = {}
    for root, directories, files in os.walk(directory, followlinks=False, onerror=_walk_error):
        for name in directories + files:
            path = Path(root) / name
            info = path.lstat()
            relative = str(path.relative_to(directory))
            if stat.S_ISLNK(info.st_mode):
                entries[relative] = ("link", os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                entries[relative] = ("dir",)
            elif stat.S_ISREG(info.st_mode):
                entries[relative] = ("file", info.st_size, stat.S_IMODE(info.st_mode))
            else:
                raise ValueError(f"Unsupported special file: {path}")
    return entries


def _walk_error(error):
    raise error


def get_directory_size(directory):
    return sum(entry[1] for entry in tree_entries(directory).values() if entry[0] == "file")


def file_hash(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as file:
        while chunk := file.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()


def compare_files(source, destination):
    source, destination = Path(source), Path(destination)
    return (not source.is_symlink() and not destination.is_symlink() and source.is_file()
            and destination.is_file() and source.stat().st_size == destination.stat().st_size
            and file_hash(source) == file_hash(destination))


def directory_receipt(directory, progress_callback=None):
    entries = tree_entries(directory)
    total = sum(entry[1] for entry in entries.values() if entry[0] == "file")
    done = 0
    receipt = {}
    for relative, entry in entries.items():
        value = list(entry)
        if entry[0] == "file":
            value.append(file_hash(Path(directory) / relative))
            done += entry[1]
        receipt[relative] = value
        if progress_callback:
            progress_callback(int(done * 100 / total) if total else 100)
    if progress_callback:
        progress_callback(100)
    return receipt


def compare_directories(source, destination, progress_callback=None):
    if tree_entries(source) != tree_entries(destination):
        return False
    return directory_receipt(source, progress_callback) == directory_receipt(destination, progress_callback)


def verify_game(game, destination_library, check_space=True):
    from steam import detect_game, installed_items
    errors = []
    source = normalize_library(game["library"])
    destination = normalize_library(destination_library)
    if source == destination or source in destination.parents or destination in source.parents:
        errors.append("Libraries must be separate, non-nested directories.")
    current = detect_game(source, game["appid"])
    if not current or current["game_path"] != Path(game["game_path"]):
        errors.append("The source installation changed. Refresh the game browser.")
    items = installed_items(game, destination)
    for item in items.values():
        for path in (item["source"], item["destination"]):
            validate_item_path(path)
        if os.path.lexists(item["destination"]):
            errors.append(f'Destination already exists: {item["destination"]}')
    for library in (source, destination):
        for path in (library / "steamapps", library / "steamapps/common"):
            if not os.access(path, os.W_OK | os.X_OK):
                errors.append(f"Directory is not writable: {path}")
        lock = library / "steamapps" / f'appmanifest_{game["appid"]}.acf.lock'
        if os.path.lexists(lock):
            errors.append(f"Steam manifest lock exists: {lock}")
    if check_space and current:
        required = get_transfer_size(game, destination) + SPACE_MARGIN
        if shutil.disk_usage(destination).free < required:
            errors.append("Not enough free space to copy and verify this game before removing its source.")
    return errors


def check_environment():
    if not check_rsync():
        raise RuntimeError("rsync is not installed.")
    if is_steam_running():
        raise RuntimeError("Exit Steam and close both selected games before continuing.")


def validate_item_path(path):
    path = Path(path)
    if path.resolve() != path:
        raise ValueError(f"Transfer path uses a symbolic link: {path}")


def get_transfer_size(game, destination):
    from steam import installed_items
    total = 0
    for item in installed_items(game, destination).values():
        validate_item_path(item["source"])
        total += get_directory_size(item["source"]) if item["kind"] == "dir" else item["source"].stat().st_size
    return total
