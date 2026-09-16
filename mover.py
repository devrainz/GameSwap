import os
import re
import shutil
import subprocess
import uuid
from collections import deque
from pathlib import Path
from config import normalize_library
from state import save_state, sync_directory
from steam import game_items, installed_items
from verify import check_environment, directory_receipt, file_hash, validate_item_path, verify_game


def operation_result(success, message, data=None):
    return {"success": success, "message": message, "data": data}


def pack_game(game, destination):
    return {**{key: str(value) for key, value in game.items()}, "destination": str(destination)}


def unpack_game(job):
    return {key: Path(value) if key in {"library", "game_path", "manifest"} else value
            for key, value in job.items() if key != "destination"}


def build_transfer(game, destination_library):
    source = normalize_library(game["library"])
    destination = normalize_library(destination_library)
    appid = game["appid"]
    folder = Path(game["game_path"]).name
    if not appid.isdigit() or folder in ("", ".", ".."):
        raise ValueError("Invalid transfer paths.")
    source_game = source / "steamapps/common" / folder
    source_manifest = source / "steamapps" / f"appmanifest_{appid}.acf"
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Libraries must be separate, non-nested directories.")
    if source_game != Path(game["game_path"]) or source_manifest != Path(game["manifest"]):
        raise ValueError("Transfer paths do not match the Steam library.")
    return {"source_game": source_game, "source_manifest": source_manifest,
            "destination_game": destination / "steamapps/common" / folder,
            "destination_manifest": destination / "steamapps" / source_manifest.name}


def _parse_rsync_progress(line):
    match = re.search(r"(\d+)%\s+(\S+/s)\s+(\d+:\d+:\d+)", line)
    return (int(match[1]), match[2], match[3]) if match else None


def copy_directory(source, destination, progress_callback=None):
    errors = deque(maxlen=8)
    command = ["rsync", "-aH", "--no-owner", "--no-group", "--checksum", "--partial",
               "--delete", "--fsync", "--info=progress2", "--", f"{source}/", f"{destination}/"]
    environment = dict(os.environ, LC_ALL="C")
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace", env=environment) as process:
        try:
            for line in process.stdout:
                progress = _parse_rsync_progress(line)
                if progress:
                    if progress_callback:
                        progress_callback(*progress)
                elif line.strip():
                    errors.append(line.strip())
            code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise
    if code:
        raise RuntimeError(f"rsync exited with code {code}: {'; '.join(errors)}")


def move_steam_game(game, destination_library, progress_callback=None, stage_callback=None, journal=None):
    if journal is None:
        raise ValueError("A saved swap journal is required.")
    build_transfer(game, destination_library)
    transfer = journal.get("transfer")

    def stage(key, message):
        transfer["stage"] = key
        save_state(journal)
        if stage_callback:
            stage_callback(message)

    def devices_present():
        for key, library in (("source_device", game["library"]), ("destination_device", destination_library)):
            if normalize_library(library).stat().st_dev != transfer[key]:
                raise RuntimeError("A library mount changed. Reconnect the original drive before resuming.")
        for item in items.values():
            validate_item_path(item["source"])
            validate_item_path(item["destination"])

    def verify_progress(percent):
        if progress_callback:
            progress_callback(percent, "Verifying", "--")

    def receipt(path, kind):
        if kind == "dir":
            return directory_receipt(path, verify_progress)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Not a regular file: {path}")
        return file_hash(path)

    try:
        check_environment()
        if transfer is None:
            errors = verify_game(game, destination_library)
            if errors:
                raise RuntimeError("\n".join(errors))
            transfer = {"id": uuid.uuid4().hex, "stage": "copying",
                        "source_device": Path(game["library"]).stat().st_dev,
                        "destination_device": Path(destination_library).stat().st_dev,
                        "items": list(installed_items(game, destination_library))}
            journal["transfer"] = transfer
            save_state(journal)
        if not re.fullmatch(r"[0-9a-f]{32}", transfer["id"]):
            raise ValueError("Invalid recovery directory identifier.")
        layout = game_items(game, destination_library)
        if not {"game", "manifest"}.issubset(transfer["items"]) or any(key not in layout for key in transfer["items"]):
            raise ValueError("Invalid recovery item list.")
        items = {key: layout[key] for key in transfer["items"]}
        staging = Path(destination_library) / "steamapps" / f'.gameswap-{transfer["id"]}'
        validate_item_path(staging)
        for key, item in items.items():
            item["staged"] = staging / (key if item["kind"] == "dir" else f"{key}.acf")
            validate_item_path(item["staged"])
        devices_present()
        if transfer["stage"] == "done":
            return operation_result(True, f'{game["name"]} moved successfully.')
        if transfer["stage"] == "copying":
            errors = verify_game(game, destination_library, check_space=False)
            if errors:
                raise RuntimeError("\n".join(errors))
            stage("copying", "Copying game and Steam data...")
            staging.mkdir(mode=0o700, exist_ok=True)
            receipts = {}
            for key, item in items.items():
                devices_present()
                if stage_callback:
                    stage_callback(f"Copying {key.replace('_', ' ')}...")
                if item["kind"] == "dir":
                    copy_directory(item["source"], item["staged"], progress_callback)
                else:
                    shutil.copyfile(item["source"], item["staged"])
                    with item["staged"].open("rb") as file:
                        os.fsync(file.fileno())
                if stage_callback:
                    stage_callback(f"Verifying {key.replace('_', ' ')}...")
                expected = receipt(item["source"], item["kind"])
                if receipt(item["staged"], item["kind"]) != expected:
                    raise RuntimeError(f"{key} verification failed. Original and staged files were kept.")
                receipts[key] = expected
            transfer["receipts"] = receipts
            sync_directory(staging)
            stage("publishing", "Installing verified copy...")
        if transfer["stage"] == "publishing":
            check_environment()
            devices_present()
            for item in items.values():
                staged, target = item["staged"], item["destination"]
                if os.path.lexists(staged):
                    if os.path.lexists(target):
                        raise RuntimeError(f"Destination appeared during transfer: {target}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    staged.rename(target)
                    sync_directory(target.parent)
                    sync_directory(staging)
                elif not target.exists():
                    raise RuntimeError(f"Verified copy is missing: {target}")
            stage("cleanup", "Checking installed copy before cleanup...")
        if transfer["stage"] != "cleanup":
            raise ValueError("Unrecognized recovery stage.")
        check_environment()
        devices_present()
        for key, item in items.items():
            if receipt(item["destination"], item["kind"]) != transfer["receipts"][key]:
                raise RuntimeError(f"Installed {key} changed. Source cleanup was blocked.")
        for key, item in items.items():
            if not item["source"].exists():
                continue
            remaining = receipt(item["source"], item["kind"])
            expected = transfer["receipts"][key]
            if item["kind"] == "dir":
                changed = any(expected.get(name) != value for name, value in remaining.items())
            else:
                changed = expected != remaining
            if changed:
                raise RuntimeError(f"Source {key} changed. Both copies were kept for inspection.")
        if stage_callback:
            stage_callback("Removing original files...")
        check_environment()
        devices_present()
        for key in ["manifest"] + [key for key in items if key != "manifest"]:
            item = items[key]
            source = item["source"]
            if source.exists():
                if item["kind"] == "dir":
                    shutil.rmtree(source)
                else:
                    source.unlink()
                sync_directory(source.parent)
        if staging.exists():
            staging.rmdir()
            sync_directory(staging.parent)
        stage("done", "Transfer finished.")
        if progress_callback:
            progress_callback(100, "Done", "--")
        return operation_result(True, f'{game["name"]} moved successfully.')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        phase = transfer.get("stage") if transfer else None
        if phase == "done":
            return operation_result(True, f'{game["name"]} moved; completion notice failed: {error}')
        message = "Transfer paused"
        if phase == "cleanup":
            message = "Destination installed; source cleanup is pending"
        return operation_result(False, f"{message}: {error}\nResume this operation from GameSwap.")
