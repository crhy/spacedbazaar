# Changelog

## 0.1.16 (2026-11-26)

- Bazaar now scores the three ways an application can be installed - apt,
  Flatpak and AppImage - and offers the best one, with the reason shown next
  to the application's title and the other builds listed side by side on the
  app page. The advice is curated data (`format-advice.json`, installed with
  the app), scored against version freshness, sandboxing and what is already
  installed; a user's explicit choice always wins. apt and AppImage are
  labelled plainly as not sandboxed, and the page's Install button installs
  the recommended build, naming it ("Install AppImage").
- An AppImage is found from the upstream project's own GitHub releases
  (`*x86_64*.AppImage`, stable releases before pre-releases) and is
  **required** to carry a published SHA256 (`<asset>-SHA256.txt` or
  `SHA256SUMS`): if the downloaded bytes do not match that digest, the
  download is refused and nothing is written. A verified AppImage installs to
  `~/Applications/` with its own `.desktop` entry and icon, and uninstalls by
  removing exactly those files.
- The app page now leads with a "Recommended for you" card: one rounded,
  accent-bordered card holding the "Recommended for you" title, a format
  badge pill (icon plus "AppImage", "Flatpak" or "System package"), the
  version and size when known, and one plain-word reason. The page's own
  Install button names the recommended build ("Install AppImage") and
  installs it; there is no second Install button on the card. A compact
  "Other ways to install" row under the card lists the other builds only
  (version, size, sandboxed or not, short reason), each with its own
  Install button; apt is not listed, since Bazaar cannot install system
  packages. An app already installed in another format says so on the card
  and recommends nothing new. The Library lists
  AppImages installed by Bazaar and removes exactly their files. The
  "installed" signal now outweighs a newer version elsewhere, a newer
  version ignores a packaging-suffix-only difference ("1.1.4" equals
  "1.1.4-1"), sandboxing only breaks a version tie, and the smaller
  download breaks the last tie.
- Seeded advice: FreeCAD is offered as the AppImage, because it "Runs best
  on Spaced. The Flatpak version freezes on this desktop." The
  Flatpak remains available as an explicit choice.
