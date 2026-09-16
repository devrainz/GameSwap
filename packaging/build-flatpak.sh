#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
flatpak-builder --user --force-clean --install-deps-from=flathub --repo=dist/flatpak-repo \
    build-flatpak packaging/flatpak/io.github.devrainz.GameSwap.json
flatpak build-bundle dist/flatpak-repo dist/GameSwap-x86_64.flatpak io.github.devrainz.GameSwap \
    --arch=x86_64 --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo
