# Changelog

## Unreleased

- Curation review queue (crhy/spacedbazaar#10): `scripts/spaced_github_repo.py
  candidates` classifies every GitHub release fixture as `already-catalogued`,
  `reviewable` or `rejected` with a stable reason code, so curation scales by
  showing a human the evidence instead of trusting a `.flatpak` filename. The
  report carries no install, download, or command field: the tool never installs
  what nobody reviewed, matching the catalog policy
  `unverified_github_assets: never-install-automatically`. End-user voting and
  the CoinKitty reputation signal remain open - identities, anti-Sybil controls,
  appeals, and ranking transparency are still undecided.
