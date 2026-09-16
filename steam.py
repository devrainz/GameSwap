import re
from pathlib import Path
from config import normalize_library

TOKEN = re.compile(r'\s+|//[^\n]*|"((?:\\.|[^"\\])*)"|([{}])')


def parse_manifest(content):
    tokens = []
    position = 0
    while position < len(content):
        match = TOKEN.match(content, position)
        if not match:
            raise ValueError("Invalid Steam manifest syntax.")
        position = match.end()
        if match.group(1) is not None:
            value = re.sub(r'\\(["\\])', r'\1', match.group(1))
            tokens.append(("text", value))
        elif match.group(2):
            tokens.append((match.group(2), match.group(2)))
    index = 0

    def object_values(nested=False):
        nonlocal index
        values = {}
        while index < len(tokens):
            kind, key = tokens[index]
            index += 1
            if kind == "}" and nested:
                return values
            if kind != "text" or index >= len(tokens):
                raise ValueError("Invalid Steam manifest entry.")
            kind, value = tokens[index]
            index += 1
            if kind == "{":
                value = object_values(True)
            elif kind != "text":
                raise ValueError("Invalid Steam manifest value.")
            values[key.casefold()] = value
        if nested:
            raise ValueError("Unclosed Steam manifest block.")
        return values

    return object_values().get("appstate", {})


def detect_game(library, appid):
    library = normalize_library(library)
    manifest = library / "steamapps" / f"appmanifest_{appid}.acf"
    if manifest.is_symlink() or not manifest.is_file():
        return None
    data = parse_manifest(manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("appid") != appid:
        return None
    folder = data.get("installdir", "")
    if not isinstance(folder, str) or not folder or folder in (".", "..") or "/" in folder or "\\" in folder:
        return None
    try:
        flags = int(data.get("stateflags", "0"))
    except (TypeError, ValueError):
        return None
    if flags <= 0:
        return None
    game_path = library / "steamapps" / "common" / folder
    if game_path.is_symlink() or not game_path.is_dir():
        return None
    return {"appid": appid, "name": str(data.get("name") or folder), "library": library,
            "game_path": game_path, "manifest": manifest}


def scan_library(library):
    library = normalize_library(library)
    games = []
    warnings = []
    for manifest in (library / "steamapps").glob("appmanifest_*.acf"):
        appid = manifest.stem.removeprefix("appmanifest_")
        if not appid.isdigit():
            continue
        try:
            game = detect_game(library, appid)
            if game:
                games.append(game)
            else:
                warnings.append(f"Skipped {manifest.name}: incomplete installation or unsupported path.")
        except (OSError, ValueError, RecursionError) as error:
            warnings.append(f"Skipped {manifest.name}: {error}")
    return sorted(games, key=lambda game: (game["name"].casefold(), game["appid"])), warnings


def filter_games(games, query):
    terms = query.casefold().split()
    return [game for game in games if all(term in f'{game["name"]} {game["appid"]}'.casefold() for term in terms)]


def game_items(game, destination_library):
    appid = game["appid"]
    source, destination = Path(game["library"]), Path(destination_library)
    layout = {"game": (Path("common") / Path(game["game_path"]).name, "dir"),
              "compatdata": (Path("compatdata") / appid, "dir"),
              "shadercache": (Path("shadercache") / appid, "dir"),
              "workshop": (Path("workshop/content") / appid, "dir"),
              "workshop_manifest": (Path("workshop") / f"appworkshop_{appid}.acf", "file"),
              "manifest": (Path(f"appmanifest_{appid}.acf"), "file")}
    return {key: {"source": source / "steamapps" / relative,
                  "destination": destination / "steamapps" / relative, "kind": kind}
            for key, (relative, kind) in layout.items()}


def installed_items(game, destination_library):
    import os
    return {key: item for key, item in game_items(game, destination_library).items()
            if os.path.lexists(item["source"])}
