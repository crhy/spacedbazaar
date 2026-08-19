<h1 align="center">
<img src="data/icons/SpacedBazaar.svg" width="128" height="128" />
<br/>
SpacedBazaar
</h1>

> [!IMPORTANT]
> This is **space**dbazaar, the [Spaced Linux](https://github.com/crhy/spaced)
> fork of Bazaar. It tracks upstream `main` and carries Spaced Linux-specific
> fixes that upstream has not yet merged. Current delta:
> - `Install apps for the current user`: normal installs go directly to the
>   user installation and no longer show a redundant “this user / all users”
>   chooser. System-installation
>   installs driven from inside the sandboxed app fail after the download with
>   "Path does not exist" ([bazaar-org/bazaar#1298](https://github.com/bazaar-org/bazaar/issues/1298),
>   Spaced Linux issue #61),
>   while user-installation installs work. Existing system installs remain
>   visible and removable.
> - `Independent Flatpak identity`: `io.github.crhy.SpacedBazaar` can be
>   installed alongside the original Bazaar without replacing or launching it.
> - `SpacedBazaar.svg` icon: the app store's brand in the Spaced Linux colors.
> - `Portable Flatpak access`: the bundle uses the standard XDG data mount and
>   contains no account-specific home-directory paths.
>   Releases ship as x86_64 and aarch64 Flatpak bundles on the
>   [releases page](https://github.com/crhy/spacedbazaar/releases).

> [!NOTE]
> If you are a distributor/packager who would like to learn how to customize
> Bazaar, take a look at the [docs](/docs/overview.md).

> [!NOTE]
> If you are interested in contributing code to Bazaar (Thank you!), please see
> the [contributing guide](/CONTRIBUTING.md).

> [!NOTE]
> If you are interested in contributing translations to Bazaar (Thank you!),
> please see the [Damned Lies Module](https://l10n.gnome.org/module/bazaar/).

SpacedBazaar is an app store for Linux with a focus on discovering and installing
apps and add-ons from Flatpak remotes, particularly
[Flathub](https://flathub.org/). The UX emphasizes supporting the developers who
make the Linux desktop possible. SpacedBazaar features a "curated" tab that can be
configured by distributors.

SpacedBazaar implements the GNOME Shell search-provider D-Bus interface. A KRunner
[plugin](https://github.com/bazaar-org/krunner-bazaar) is available for use on
the KDE Plasma desktop.

Thanks to [Tobias Bernard](https://tobiasbernard.com/), [Jakub
Steiner](http://jimmac.eu), and [Sam Hewitt](https://snwh.org) for designing
Bazaar's market stall icon.

### Installing

Download the bundle for your architecture from the
[latest GitHub release](https://github.com/crhy/spacedbazaar/releases/latest),
then install it for your user:

```sh
flatpak install --user ./SpacedBazaar-x86_64.flatpak
```

The aarch64 bundle is named `SpacedBazaar-aarch64.flatpak`. The release is not
the Flathub Bazaar package: it has its own ID and may be installed alongside it.

[![Build Flatpak](https://github.com/crhy/spacedbazaar/actions/workflows/build-flatpak.yml/badge.svg)](https://github.com/crhy/spacedbazaar/actions/workflows/build-flatpak.yml)

### Supporting

You can support Spaced Linux development at
[spacedlinux.com](https://spacedlinux.com/#donate).

#### Code of Conduct

SpacedLinux Code of Conduct:
All facets of Spaced Linux are Free.  You can say and call anyone whatever you want.  We endorse absolute freedom of speech, including screaming fire in a theater.
