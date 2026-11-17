# Changelog

## Unreleased

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
- Seeded advice: FreeCAD is offered as the AppImage, because the FreeCAD 1.1.4
  flatpak freezes on Spaced; the root cause is under investigation. The
  Flatpak remains available as an explicit choice.
