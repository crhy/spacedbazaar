# Changelog

Human-readable notes for distributors. The binary version is tracked by
`version.sh`; nothing here bumps it.

## Unreleased

### Screenshots: at least half of what SpacedBazaar publishes is dark (#15)

crhy/spacedbazaar#15 asked for "at LEAST a 50/50 mix of dark mode, since we are
a dark mode by default OS". The published set is now measured instead of
eyeballed: `scripts/check-screenshot-mix.py` reads the README gallery and the
`<image>` pins in `data/io.github.crhy.SpacedBazaar.metainfo.xml.in`, decodes
each PNG with `scripts/png_luminance.py` (standard library only, no PIL
dependency), and fails when fewer than half of the captures fall below a mean
Rec.709 luminance of 0.50.

Measured before, README gallery plus the Flathub pin: 4 of 8 dark.

| screenshot | mean luminance | counts as | published in |
| --- | --- | --- | --- |
| `spaced-bazaar-explore-2026-09.png` | 0.195 | dark | README |
| `search.png` | 0.719 | light | README |
| `categories.png` | 0.363 | dark | README |
| `library.png` | 0.873 | light | README |
| `flathub.png` | 0.840 | light | README |
| `bazaar-light.png` | 0.843 | light | README |
| `bazaar-dark.png` | 0.291 | dark | README |
| `spaced-bazaar-explore-dark-9.26.1.png` | 0.280 | dark | metainfo |

Measured after, the re-curated gallery: 5 of 7 dark (71%).

| screenshot | mean luminance | counts as | published in |
| --- | --- | --- | --- |
| `spaced-bazaar-explore-2026-09.png` | 0.195 | dark | README |
| `spaced-bazaar-search-dark-9.26.1.png` | 0.232 | dark | README |
| `categories.png` | 0.363 | dark | README |
| `spaced-bazaar-explore-dark-9.26.1.png` | 0.280 | dark | README + metainfo |
| `bazaar-dark.png` | 0.291 | dark | README |
| `library.png` | 0.873 | light | README |
| `flathub.png` | 0.840 | light | README |

`search.png` became `spaced-bazaar-search-dark-9.26.1.png`, the dark 9.26.1
catalog capture joined the gallery next to the September one, and `bazaar-light.png`
left the gallery; `library.png` and `flathub.png` stay because no dark capture of
those views is committed yet. No screenshot was recoloured, the Flathub pin
commit is unchanged, and the signed app catalog is untouched: measured over
`catalog/crhy-flatpaks.json` it was already 6 of 9 dark.
