#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
command -v snapcraft >/dev/null
snapcraft --destructive-mode
