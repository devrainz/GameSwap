# Packaging GameSwap

GameSwap uses Python 3.11+, PyGObject, GTK4, libadwaita 1.2+, `rsync`, and `procps`. The program needs read/write access to the two Steam libraries, so sandboxed packages must request access to the locations where the user keeps Steam libraries.

## Native install

```bash
bash install.sh
```

This installs per-user under `~/.local`. For a system install:

```bash
sudo bash install.sh --system
```

The installer registers the `.desktop` launcher and scalable icon. The launcher opens the libadwaita UI; the old TUI remains available with `gameswap --tui`.

## Debian and Ubuntu

```bash
bash packaging/build-deb.sh
sudo apt install dist/gameswap_*_all.deb
```

The package is architecture-independent because it contains Python source and uses the distribution's GTK libraries.

## Arch Linux, yay, and paru

First publish the source tarball as a GitHub release, run `python3 packaging/prepare-release.py`, copy `dist/aur/PKGBUILD` into an AUR clone, and build it:

```bash
cd dist/aur
makepkg -si
```

After the package is submitted to the AUR, users can install it with:

```bash
yay -S gameswap
paru -S gameswap
```

## Fedora and RPM distributions

```bash
python3 packaging/prepare-release.py
mkdir -p ~/rpmbuild/SOURCES
cp dist/GameSwap-*.tar.gz ~/rpmbuild/SOURCES/
rpmbuild -ba --define "_topdir $HOME/rpmbuild" packaging/gameswap.spec
sudo dnf install ~/rpmbuild/RPMS/noarch/gameswap-*.rpm
```

## Flatpak

Flatpak is suitable for a desktop UI, but it requires explicit filesystem permissions for Steam libraries. The supplied manifest supports Wayland, X11 fallback, removable media, and Steam's common Flatpak path. A user with Steam libraries elsewhere may need to grant that directory with `flatpak override --user --filesystem=/path/to/library io.github.devrainz.GameSwap`.

```bash
bash packaging/build-flatpak.sh
flatpak --user install dist/GameSwap-x86_64.flatpak
flatpak run io.github.devrainz.GameSwap
```

The app uses `flatpak-spawn --host ps` for the Steam-running check. This is why the manifest requests the Flatpak D-Bus name. Flatpak sandbox access should stay as narrow as practical; its permission model documents XDG and filesystem grants in the [Flatpak sandbox permissions guide](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

## Snap

The supplied strict-confinement Snap requests `home`, removable media, and a `personal-files` plug for standard Steam locations. The Snap Store may require approval for personal-files access.

```bash
snapcraft
snapcraft install --dangerous gameswap_2.1.0_amd64.snap
```

When the snap is ready, authenticate, reserve the name, and publish the stable revision:

```bash
snapcraft login
snapcraft register gameswap
snapcraft upload --release=stable gameswap_2.1.0_amd64.snap
```

Canonical documents GTK4/GNOME extension requirements in its [GTK4 Snap guide](https://ubuntu.com/docs/snapcraft/9/how-to/integrations/craft-a-gtk4-app/) and publishing in its [Snap publishing guide](https://documentation.ubuntu.com/snapcraft/stable/how-to/publishing/publish-a-snap/).

## Release preparation

Run this after updating `VERSION` and pushing the source repository:

```bash
python3 packaging/prepare-release.py --repository devrainz/GameSwap
```

It creates a versioned source tarball, the release SHA256 file, a source-backed Flatpak manifest, and an AUR `PKGBUILD` with the correct checksum.

Pushing a `v*` tag runs the repository workflow, which publishes the generated artifacts to a GitHub release. Flatpak and Snap store submissions still require a maintainer account and review: fork the app into the [Flathub submissions repository](https://docs.flathub.org/docs/for-app-authors/submission), open a pull request, and upload the Snap with `snapcraft upload --release=stable` after `snapcraft login` and `snapcraft register gameswap`.
