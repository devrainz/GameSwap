import time
from tui import clear, logo, safe_text, title

_current_game = ""
_current_stage = "Preparing..."
_percent = 0
_speed = "--"
_eta = "--"
_transfer_number = 0
_total_transfers = 0
_last_draw = 0


def reset():
    global _percent, _speed, _eta, _current_stage, _last_draw
    _percent, _speed, _eta = 0, "--", "--"
    _current_stage, _last_draw = "Preparing...", 0


def set_game(game_name, transfer_number=0, total_transfers=0):
    global _current_game, _transfer_number, _total_transfers
    _current_game = game_name
    _transfer_number, _total_transfers = transfer_number, total_transfers
    redraw(True)


def redraw(force=False):
    global _last_draw
    now = time.monotonic()
    if not force and now - _last_draw < 0.15:
        return
    _last_draw = now
    clear()
    logo()
    title(f"Transferring game {_transfer_number}/{_total_transfers}")
    filled = int(32 * _percent / 100)
    print(f'{safe_text(_current_game)}\n\n{_current_stage}\n')
    print(f'{"█" * filled}{"░" * (32 - filled)} {_percent}%')
    print(f'\nSpeed: {_speed} · ETA: {_eta}\n')
    print("Ctrl+C pauses safely. Keep Steam and the selected games closed.")


def set_stage(stage):
    global _current_stage, _percent, _speed, _eta
    _current_stage, _percent, _speed, _eta = stage, 0, "--", "--"
    redraw(True)


def set_progress(percent, speed, eta):
    global _percent, _speed, _eta
    _percent = max(0, min(100, int(percent)))
    _speed, _eta = speed, eta
    redraw()
