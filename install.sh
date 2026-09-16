#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ${1:-} == --system ]]; then
    prefix=/usr/local
elif [[ $# == 0 ]]; then
    if [[ $EUID == 0 ]]; then
        echo 'Run without sudo for a per-user install, or use sudo bash install.sh --system.' >&2
        exit 1
    fi
    prefix="$HOME/.local"
else
    echo 'Usage: bash install.sh [--system]' >&2
    exit 1
fi
/usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Adw; assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 2)'
command -v rsync >/dev/null
command -v ps >/dev/null
/usr/bin/python3 packaging/install.py --prefix "$prefix"
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$prefix/share/applications"
fi
if command -v gtk-update-icon-cache >/dev/null && [[ -f "$prefix/share/icons/hicolor/index.theme" ]]; then
    gtk-update-icon-cache -f -t "$prefix/share/icons/hicolor"
fi
echo 'GameSwap is installed. Open it from your application menu.'
