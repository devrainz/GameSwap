#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p dist/flatpak-repo

flatpak-builder \
    --force-clean \
    --repo=dist/flatpak-repo \
    build-flatpak \
    packaging/flatpak/io.github.devrainz.GameSwap.json

flatpak build-bundle \
    dist/flatpak-repo \
    dist/GameSwap-x86_64.flatpak \
    io.github.devrainz.GameSwap
