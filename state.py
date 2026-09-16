import fcntl
import json
import os
import tempfile
from pathlib import Path

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "gameswap"
STATE_FILE = STATE_DIR / "transfer.json"


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=True, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def save_state(data):
    atomic_write(STATE_FILE, data)


def load_state():
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported recovery format.")
        jobs, index = data.get("jobs"), data.get("index")
        required = {"appid", "name", "library", "game_path", "manifest", "destination"}
        if not isinstance(jobs, list) or len(jobs) != 2 or type(index) is not int or not 0 <= index <= 2:
            raise ValueError("Invalid recovery queue.")
        for job in jobs:
            if not isinstance(job, dict) or not required.issubset(job):
                raise ValueError("Incomplete recovery job.")
            if any(not isinstance(job[key], str) for key in required):
                raise ValueError("Invalid recovery job value.")
        transfer = data.get("transfer")
        if transfer is not None:
            fields = {"id", "stage", "items", "source_device", "destination_device"}
            if not isinstance(transfer, dict) or not fields.issubset(transfer):
                raise ValueError("Incomplete transfer checkpoint.")
            if transfer["stage"] not in {"copying", "publishing", "cleanup", "done"}:
                raise ValueError("Invalid transfer stage.")
            if not isinstance(transfer["id"], str) or not isinstance(transfer["items"], list):
                raise ValueError("Invalid transfer checkpoint.")
            if any(not isinstance(key, str) for key in transfer["items"]):
                raise ValueError("Invalid transfer item.")
            if transfer["stage"] != "copying":
                receipts = transfer.get("receipts")
                if not isinstance(receipts, dict) or any(key not in receipts for key in transfer["items"]):
                    raise ValueError("Missing verification receipts.")
        return data
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read recovery file {STATE_FILE}: {error}") from error


def clear_state():
    STATE_FILE.unlink(missing_ok=True)
    sync_directory(STATE_FILE.parent)


def acquire_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    handle = (STATE_DIR / "instance.lock").open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another GameSwap instance is already running.") from None
    return handle
