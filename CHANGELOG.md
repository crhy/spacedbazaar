# Changelog

## 0.1.16 (2026-11-26)

- Bazaar now scores the three ways an application can be installed - apt,
  Flatpak and AppImage - and offers the best one, with the reason shown next
  to the application's title and every build listed side by side on the app
  page. The advice is curated data (`format-advice.json`, installed with the
  app), scored against version freshness, sandboxing and what is already
  installed; a user's explicit choice always wins. apt and AppImage are
  labelled plainly as not sandboxed, and the Flatpak build remains the one
  Bazaar installs.
- An AppImage is found from the upstream project's own GitHub releases
  (`*x86_64*.AppImage`, stable releases before pre-releases) and is
  **required** to carry a published SHA256 (`<asset>-SHA256.txt` or
  `SHA256SUMS`): if the downloaded bytes do not match that digest, the
  download is refused and nothing is written. A verified AppImage installs to
  `~/Applications/` with its own `.desktop` entry and icon, and uninstalls by
  removing exactly those files.
- The app page now leads with a "Recommended for you" card: format badge,
  version, size, one plain-word reason and one big Install button that
  installs that build; a compact "Other ways to install" row under it lists
  every build side by side (version, size, sandboxed or not, short reason),
  each with its own Install button. An app already installed in another
  format says so on the card and recommends nothing new. The Library lists
  AppImages installed by Bazaar and removes exactly their files. The
  "installed" signal now outweighs a newer version elsewhere, a newer
  version ignores a packaging-suffix-only difference ("1.1.4" equals
  "1.1.4-1"), sandboxing only breaks a version tie, and the smaller
  download breaks the last tie.
- Seeded advice: FreeCAD is offered as the AppImage, because the FreeCAD 1.1.4
  flatpak freezes on Spaced; the root cause is under investigation. The
  Flatpak remains available as an explicit choice.
