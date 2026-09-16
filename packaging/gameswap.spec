Name:           gameswap
Version:        2.1.0
Release:        1%{?dist}
Summary:        Swap installed Steam games between libraries
License:        MIT
URL:            https://github.com/devrainz/GameSwap
Source0:        https://github.com/devrainz/GameSwap/releases/download/v%{version}/GameSwap-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3
BuildRequires:  make
Requires:       python3 >= 3.11
Requires:       python3-gobject
Requires:       gtk4 >= 4.8
Requires:       libadwaita >= 1.2
Requires:       rsync >= 3.2
Requires:       procps-ng

%description
Native GTK4 and libadwaita application for verified, resumable swaps of Steam games.

%prep
%setup -q -n GameSwap-%{version}

%build

%install
%make_install PREFIX=%{_prefix} PYTHON=%{__python3}

%files
%{_bindir}/gameswap
%{_datadir}/gameswap/
%{_datadir}/applications/io.github.devrainz.GameSwap.desktop
%{_datadir}/icons/hicolor/512x512/apps/io.github.devrainz.GameSwap.png
%{_datadir}/metainfo/io.github.devrainz.GameSwap.metainfo.xml
%license %{_datadir}/licenses/gameswap/LICENSE

%changelog
* Tue Sep 15 2026 Rainz <devrainz@users.noreply.github.com> - 2.1.0-1
- Native libadwaita interface
