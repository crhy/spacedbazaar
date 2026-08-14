<h1 align="center">
<img src="data/icons/hicolor/scalable/apps/io.github.kolunmi.Bazaar.svg" width="128" height="128" />
<br/>
SpacedBazaar
</h1>

> [!IMPORTANT]
> This is **space**dbazaar, the [Spaced Linux](https://github.com/crhy/spaced)
> fork of Bazaar. It tracks upstream `main` and carries Spaced Linux-specific
> fixes that upstream has not yet merged. Current delta:
> - `Prefer user-installation sources when installing from the sandbox`: the
>   install dialog, shift-click install, and bulk-install paths now preselect
>   the user-installation source whenever one exists. System-installation
>   installs driven from inside the sandboxed app fail after the download with
>   "Path does not exist" ([bazaar-org/bazaar#1298]
>   (https://github.com/bazaar-org/bazaar/issues/1298), Spaced Linux issue #61),
>   while user-installation installs work. System installations remain the
>   preselected source when no user source exists and for removals.

> [!NOTE]
> If you are a distributor/packager who would like to learn how to customize
> Bazaar, take a look at the [docs](/docs/overview.md).

> [!NOTE]
> If you are interested in contributing code to Bazaar (Thank you!), please see
> the [contributing guide](/CONTRIBUTING.md).

> [!NOTE]
> If you are interested in contributing translations to Bazaar (Thank you!),
> please see the [Damned Lies Module](https://l10n.gnome.org/module/bazaar/).

Bazaar is a new app store for GNOME with a focus on discovering and installing
apps and add-ons from Flatpak remotes, particularly
[Flathub](https://flathub.org/). The UX emphasizes supporting the developers who
make the Linux desktop possible. Bazaar features a "curated" tab that can be
configured by distributors.

Bazaar implements the gnome-shell search provider dbus interface. A krunner
[plugin](https://github.com/bazaar-org/krunner-bazaar) is available for use on
the KDE Plasma desktop.

Thanks to [Tobias Bernard](https://tobiasbernard.com/), [Jakub
Steiner](http://jimmac.eu), and [Sam Hewitt](https://snwh.org) for designing
Bazaar's market stall icon.

### Installing

Pre-built binaries are distributed via Flathub and GitHub actions:

<a href='https://flathub.org/apps/details/io.github.kolunmi.Bazaar'><img width='240' alt='Get it on Flathub' src='https://flathub.org/api/badge?svg&locale=en'/></a>

[![Build Flatpak and Upload Artifact](https://github.com/bazaar-org/bazaar/actions/workflows/build-flatpak.yml/badge.svg)](https://github.com/bazaar-org/bazaar/actions/workflows/build-flatpak.yml)

There also exist packages for [Debian](https://tracker.debian.org/pkg/bazaar)
and [Arch](https://archlinux.org/packages/extra/x86_64/bazaar/). These are not
directly supported but should work fine. If you encounter a bug on any package
of Bazaar other than the flatpak, ensure the bug also exists on the flatpak
before reporting it here.

### Supporting

You can support rhY and his work at links for venmo and bitcoin on SpacedLinux.com  Note: If you support him, he will eventually build OpenAirShips.com and make governments and corporations obsolete and irrelevant.

#### Code of Conduct

SpacedLinux Code of Conduct:
All facets of Spaced Linux are Free.  You can say and call anyone whatever you want.  We endorse absolute freedom of speech, including screaming fire in a theater.
