import shutil
from input_handler import disable_raw_mode, enable_raw_mode, get_key
from steam import filter_games, scan_library


def safe_text(value):
    return "".join(character if character.isprintable() else " " for character in str(value))


def clear():
    print("\033[2J\033[H", end="")


def logo():
    print("\033[1;36m ⇄  GameSwap\033[0m")


def title(text):
    print(f"\n{safe_text(text)}\n{'─' * min(54, shutil.get_terminal_size().columns - 1)}\n")


def footer():
    print("\n↑ ↓ Navigate · Enter Select · Esc Back · Ctrl+Q Quit")


def menu_select(title_text, options, description=""):
    selected = 0
    enable_raw_mode()
    try:
        while True:
            clear()
            logo()
            title(title_text)
            if description:
                print(description, "\n")
            for index, option in enumerate(options):
                print(f'{">" if index == selected else " "} {option}')
            footer()
            key = get_key()
            if key in ("QUIT", "ESC"):
                return None
            if key == "ENTER":
                return selected
            if key in ("UP", "DOWN"):
                selected = (selected + (1 if key == "DOWN" else -1)) % len(options)
    finally:
        disable_raw_mode()


def main_menu(config, first, second):
    description = (f'Main: {safe_text(config["main_library"])}\n'
                   f'Secondary: {safe_text(config["backup_library"])}\n\n'
                   f'Game 1: {safe_text(first["name"]) if first else "Choose from main library"}\n'
                   f'Game 2: {safe_text(second["name"]) if second else "Choose from secondary library"}')
    result = menu_select("Swap games between libraries", ["Choose game 1 · Main library",
                         "Choose game 2 · Secondary library", "Review and swap", "Settings", "Exit"], description)
    return None if result in (None, 4) else result


def browse_games(library, label):
    games, warnings = scan_library(library)
    selected = 0
    query = ""
    enable_raw_mode()
    try:
        while True:
            matches = filter_games(games, query)
            selected = min(selected, max(0, len(matches) - 1))
            columns, rows = shutil.get_terminal_size()
            page_size = max(1, rows - 13)
            start = selected // page_size * page_size
            clear()
            logo()
            title(label)
            print(safe_text(library)[:max(1, columns - 1)])
            print(f'\nSearch: {safe_text(query)}▏')
            print(f'{len(matches)} matches / {len(games)} installed · {len(warnings)} skipped\n')
            for index in range(start, min(start + page_size, len(matches))):
                game = matches[index]
                text = f'{">" if index == selected else " "} {safe_text(game["name"])} [{game["appid"]}]'
                print(text[:max(1, columns - 1)])
            if not matches:
                print("No matching installed games.")
            print("\nType to filter · ↑ ↓ / PgUp PgDn · Enter Select · Esc Back")
            print("Ctrl+U Clear search · Ctrl+R Refresh · Ctrl+Q Back")
            key = get_key()
            if key in ("QUIT", "ESC"):
                return None
            if key == "ENTER" and matches:
                return matches[selected]
            if key in ("UP", "DOWN", "PAGEUP", "PAGEDOWN") and matches:
                offset = {"UP": -1, "DOWN": 1, "PAGEUP": -page_size, "PAGEDOWN": page_size}[key]
                selected = max(0, min(len(matches) - 1, selected + offset))
            elif key == "REFRESH":
                games, warnings = scan_library(library)
                selected = 0
            elif key == "CLEAR":
                query, selected = "", 0
            elif key == "BACKSPACE":
                query, selected = query[:-1], 0
            elif len(key) == 1 and key.isprintable():
                query, selected = query + key, 0
    finally:
        disable_raw_mode()
