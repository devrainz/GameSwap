#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
command -v rpmbuild >/dev/null
version=$(python3 gameswap.py --version | awk '{print $2}')
python3 packaging/prepare-release.py --repository "${GITHUB_REPOSITORY:-devrainz/GameSwap}"
topdir=$(mktemp -d -t gameswap-rpm.XXXXXXXX)
mkdir -p "$topdir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
cp "dist/GameSwap-${version}.tar.gz" "$topdir/SOURCES/"
rpmbuild -ba --define "_topdir $topdir" packaging/gameswap.spec
mkdir -p dist/rpm
find "$topdir/RPMS" "$topdir/SRPMS" -type f -name '*.rpm' -exec cp {} dist/rpm/ \;
printf 'RPM packages: dist/rpm\n'
