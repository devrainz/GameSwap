import os
import select
import sys
import termios
import tty

_old_settings = None


def enable_raw_mode():
    global _old_settings
    if _old_settings is not None:
        return
    fd = sys.stdin.fileno()
    _old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    settings = termios.tcgetattr(fd)
    settings[0] &= ~termios.IXON
    termios.tcsetattr(fd, termios.TCSANOW, settings)


def disable_raw_mode():
    global _old_settings
    if _old_settings is not None:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _old_settings)
        _old_settings = None


def read_key(timeout=0):
    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], timeout)[0]:
        return None
    raw = os.read(fd, 1)
    if not raw:
        return "QUIT"
    if raw == b"\x1b":
        sequence = raw
        while len(sequence) < 8 and select.select([fd], [], [], 0.04)[0]:
            sequence += os.read(fd, 1)
            if len(sequence) > 2 and (sequence[-1:] == b"~" or sequence[-1:].isalpha()):
                break
        return {b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[5~": "PAGEUP",
                b"\x1b[6~": "PAGEDOWN", b"\x1b": "ESC"}.get(sequence)
    controls = {b"\r": "ENTER", b"\n": "ENTER", b"\x11": "QUIT", b"\x7f": "BACKSPACE",
                b"\x08": "BACKSPACE", b"\x15": "CLEAR", b"\x12": "REFRESH"}
    if raw in controls:
        return controls[raw]
    length = 1
    if raw[0] >= 0xC2:
        length = 2 if raw[0] < 0xE0 else 3 if raw[0] < 0xF0 else 4
    while len(raw) < length and select.select([fd], [], [], 0.05)[0]:
        raw += os.read(fd, 1)
    value = raw.decode("utf-8", errors="replace")
    return value if value.isprintable() else None


def get_key():
    while True:
        key = read_key(None)
        if key is not None:
            return key


def get_key_nonblocking():
    return read_key()
