import argparse
import shutil
import sys
from pathlib import Path
from config import is_configured, load_config, normalize_library, save_config, set_library
from input_handler import disable_raw_mode
from mover import move_steam_game, pack_game, unpack_game
from state import STATE_FILE, acquire_lock, clear_state, load_state, save_state
from transfer_ui import reset, set_game, set_progress, set_stage
from tui import browse_games, clear, logo, main_menu, safe_text, title
from verify import SPACE_MARGIN, check_environment, get_transfer_size, verify_game

VERSION = "2.1.0"


def screen(heading, message):
    clear()
    logo()
    title(heading)
    print(safe_text(message) if "\n" not in message else "\n".join(safe_text(line) for line in message.splitlines()))
    input("\nPress Enter to continue...")


def first_time_setup():
    clear()
    logo()
    title("Choose your Steam libraries")
    print("Use each library folder, or its steamapps folder. Leave blank to cancel.\n")
    main = input("Main library: ").strip()
    if not main:
        return False
    secondary = input("Secondary library: ").strip()
    if not secondary:
        return False
    main, secondary = normalize_library(main), normalize_library(secondary)
    if main == secondary or main in secondary.parents or secondary in main.parents:
        raise ValueError("Choose two separate, non-nested libraries.")
    save_config({"main_library": str(main), "backup_library": str(secondary)})
    return True


def handle_settings():
    while True:
        clear()
        logo()
        title("Library settings")
        config = load_config()
        print(f'Main: {safe_text(config["main_library"])}')
        print(f'Secondary: {safe_text(config["backup_library"])}')
        print("\n1) Change main library\n2) Change secondary library\n3) Back\n")
        choice = input("> ").strip()
        if choice not in ("1", "2"):
            return
        path = input("New library path (blank cancels): ").strip()
        if path:
            try:
                set_library("main_library" if choice == "1" else "backup_library", path)
            except (OSError, ValueError) as error:
                screen("Invalid library", str(error))


def plan_move(game, destination):
    check_environment()
    errors = verify_game(game, destination, check_space=True)
    if errors:
        raise ValueError(f'{game["name"]}:\n' + "\n".join(errors))
    return [pack_game(game, destination)]


def plan_swap(first, second):
    check_environment()
    if first["appid"] == second["appid"]:
        raise ValueError("Select two different games.")
    moves = [(first, second["library"]), (second, first["library"])]
    sizes = [get_transfer_size(game, destination)
             for game, destination in moves]
    for game, destination in moves:
        errors = verify_game(game, destination, check_space=False)
        if errors:
            raise ValueError(f'{game["name"]}:\n' + "\n".join(errors))
    for order in ((0, 1), (1, 0)):
        available = {}
        feasible = True
        for index in order:
            game, destination = moves[index]
            source_device = game["library"].stat().st_dev
            destination_device = destination.stat().st_dev
            available.setdefault(source_device, shutil.disk_usage(game["library"]).free)
            available.setdefault(destination_device, shutil.disk_usage(destination).free)
            if available[destination_device] < sizes[index] + SPACE_MARGIN:
                feasible = False
                break
            available[destination_device] -= sizes[index]
            available[source_device] += sizes[index]
        if feasible:
            return [pack_game(*moves[index]) for index in order]
    raise ValueError("Neither transfer order has enough estimated free space.\n"
                     "At least one destination must hold a full verified copy before its source is removed.")


def run_queue(journal, on_game=None, on_progress=None, on_stage=None, on_reset=None, should_pause=None):
    show_game = on_game or set_game
    show_progress = on_progress or set_progress
    show_stage = on_stage or set_stage
    reset_progress = on_reset or reset
    completed = journal["index"]
    try:
        while journal["index"] < len(journal["jobs"]):
            if should_pause and should_pause():
                return False, f"Operation paused. {completed}/{len(journal['jobs'])} transfers completed. Resume when ready."
            job = journal["jobs"][journal["index"]]
            reset_progress()
            show_game(job["name"], journal["index"] + 1, len(journal["jobs"]))
            result = move_steam_game(unpack_game(job), Path(job["destination"]),
                                     show_progress, show_stage, journal)
            if not result["success"]:
                return False, f'{journal["index"]}/{len(journal["jobs"])} transfers completed.\n{result["message"]}'
            completed = journal["index"] + 1
            journal["index"] = completed
            journal["transfer"] = None
            save_state(journal)
        try:
            clear_state()
        except OSError as error:
            noun = "Game" if len(journal["jobs"]) == 1 else "Both games"
            return True, f"{noun} moved. Recovery record cleanup is pending: {error}"
        if len(journal["jobs"]) == 1:
            return True, "Game was moved and verified successfully. You can reopen Steam."
        return True, "Both games were moved and verified successfully. You can reopen Steam."
    except KeyboardInterrupt:
        return False, f"Operation paused. {completed}/{len(journal['jobs'])} transfers completed.\nRestart GameSwap to resume."
    except (OSError, ValueError, RuntimeError) as error:
        if completed == len(journal["jobs"]):
            noun = "Game" if len(journal["jobs"]) == 1 else "Both games"
            return True, f"{noun} moved. Recovery record update is pending: {error}"
        return False, f"Operation paused: {error}\nRestart GameSwap to resume."


def check_recovery():
    journal = load_state()
    if not journal:
        legacy = Path(".truckswap_state.json")
        if legacy.exists():
            screen("Old TruckSwap recovery record", f"Found {legacy.resolve()}.\n"
                   "Its format does not contain enough information for safe automatic recovery.\n"
                   "Inspect the old transfer and both libraries, then rename this record before using GameSwap.")
            return False
        return True
    jobs, index = journal.get("jobs"), journal.get("index")
    if not isinstance(jobs, list) or len(jobs) not in (1, 2) or not isinstance(index, int) or not 0 <= index <= len(jobs):
        raise ValueError(f"Invalid transfer queue in {STATE_FILE}. No files were moved.")
    clear()
    logo()
    title("Resume unfinished transfer")
    print(f"Completed: {index}/{len(jobs)}\n")
    for job in jobs:
        print(f'{safe_text(job["name"])} → {safe_text(job["destination"])}')
    print(f'\nStage: {safe_text((journal.get("transfer") or {}).get("stage", "waiting"))}')
    if input("\nResume? [y/N]: ").strip().casefold() != "y":
        return False
    success, message = run_queue(journal)
    screen("Transfer complete" if success else "Transfer paused", message)
    return success and load_state() is None


def swap_games(first, second):
    if not first or not second:
        screen("Choose both games", "Select game 1 from the main library and game 2 from the secondary library.")
        return
    jobs = plan_swap(first, second)
    clear()
    logo()
    title("Review swap")
    for index, job in enumerate(jobs, 1):
        size = get_transfer_size(unpack_game(job), job["destination"]) / 1024 ** 3
        print(f'{index}. {safe_text(job["name"])} ({size:.2f} GiB)')
        print(f'   From: {safe_text(job["library"])}\n   To:   {safe_text(job["destination"])}\n')
    print("Close Steam and both games. Keep both drives connected until completion.")
    print("Free space is checked again before each transfer.")
    if input("\nStart swap? [y/N]: ").strip().casefold() != "y":
        return
    check_environment()
    journal = {"version": 1, "jobs": jobs, "index": 0, "transfer": None}
    save_state(journal)
    success, message = run_queue(journal)
    screen("Transfer complete" if success else "Transfer paused", message)


def main():
    parser = argparse.ArgumentParser(description="Swap two installed Steam games between Linux libraries.")
    parser.add_argument("--version", action="version", version=f"GameSwap {VERSION}")
    parser.add_argument("--tui", action="store_true", help="Use the legacy terminal interface")
    args = parser.parse_args()
    if not args.tui:
        try:
            from gui import launch
        except (ImportError, ValueError) as error:
            print(f"GameSwap needs GTK 4, libadwaita 1.2+ and PyGObject: {error}", file=sys.stderr)
            print("See PACKAGING.md for your distro's packages, or run with --tui.", file=sys.stderr)
            return 1
        return launch()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Run GameSwap in an interactive terminal.", file=sys.stderr)
        return 1
    lock = acquire_lock()
    try:
        if not check_recovery():
            return 0
        if not is_configured() and not first_time_setup():
            return 0
        first = second = None
        while True:
            if load_state() is not None and not check_recovery():
                return 0
            config = load_config()
            selected = main_menu(config, first, second)
            if selected is None:
                return 0
            try:
                if selected == 0:
                    choice = browse_games(config["main_library"], "Game 1 · Main library")
                    first = choice or first
                elif selected == 1:
                    choice = browse_games(config["backup_library"], "Game 2 · Secondary library")
                    second = choice or second
                elif selected == 2:
                    swap_games(first, second)
                    first = second = None
                elif selected == 3:
                    handle_settings()
                    first = second = None
            except (OSError, ValueError, RuntimeError) as error:
                screen("Cannot continue", str(error))
    finally:
        disable_raw_mode()
        lock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nGameSwap closed. Any unfinished swap can be resumed on the next launch.")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"GameSwap: {error}", file=sys.stderr)
        raise SystemExit(1)
