#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
task_stage=$(mktemp -d -t gameswap-deb.XXXXXXXX)
version=$(python3 gameswap.py --version | awk '{print $2}')
python3 packaging/install.py --prefix /usr --destdir "$task_stage"
install -d "$task_stage/DEBIAN" dist
python3 - "$task_stage" "$version" <<'PY'
import sys
from pathlib import Path
root, version = Path(sys.argv[1]), sys.argv[2]
size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) // 1024
(root / 'DEBIAN/control').write_text(f'''Package: gameswap
Version: {version}-1
Section: games
Priority: optional
Architecture: all
Maintainer: Rainz <devrainz@users.noreply.github.com>
Installed-Size: {size}
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0 (>= 4.8), gir1.2-adw-1 (>= 1.2), rsync (>= 3.2), procps
Homepage: https://github.com/devrainz/GameSwap
Description: Swap installed Steam games between libraries
 Native GTK4 and libadwaita interface with verified, resumable transfers.
''')
PY
dpkg-deb --root-owner-group --build "$task_stage" "dist/gameswap_${version}-1_all.deb"
echo "Build staging directory retained at: $task_stage"
