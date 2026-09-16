PREFIX ?= /usr/local
DESTDIR ?= /
PYTHON ?= python3

.PHONY: install test gui-test deb flatpak rpm snap
install:
	$(PYTHON) packaging/install.py --prefix "$(PREFIX)" --destdir "$(DESTDIR)"

test:
	$(PYTHON) -m unittest discover -s tests -v

gui-test:
	dbus-run-session -- xvfb-run -a $(PYTHON) tests/gui_smoke.py

deb:
	bash packaging/build-deb.sh

flatpak:
	bash packaging/build-flatpak.sh

rpm:
	bash packaging/build-rpm.sh

snap:
	bash packaging/build-snap.sh
