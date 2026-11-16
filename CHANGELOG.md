# Changelog

## Unreleased

- The signed app catalog now lists both rhYciv captures: the original
  "create or load an empire" main-menu shot and the current main menu captured
  2026-09, pinned to the commit that already carries that file (#17).
- Every screenshot this repository hosts for itself is verified before
  publication: the pinned commit must exist here, the path must live under
  `screenshots/` and be present in that commit, the pin must name an exact
  commit SHA rather than a moving ref, and the bytes at that commit must still
  hash to the recorded SHA-256. A pin the repository cannot serve now stops the
  build before anything is staged, imported or signed, instead of shipping a
  broken tile to every installed Spaced Linux system (#17).
- New captures of the running game still need a desktop session, so that half
  of #17 remains open.
