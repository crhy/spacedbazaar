# Spaced GitHub Flatpak repository

SpacedBazaar treats GitHub releases as an input to a curated Flatpak remote,
not as an application repository by themselves. The resulting remote is named
`spaced-github` and uses these permanent public URLs:

- Descriptor: `https://crhy.github.io/spacedbazaar/spaced-github.flatpakrepo`
- OSTree repository: `https://crhy.github.io/spacedbazaar/flatpak-repo/`

The source catalog is [`catalog/crhy-flatpaks.json`](../catalog/crhy-flatpaks.json).
It records each expected application ID, repository, runtime, branch, supported
architecture, and release-asset pattern. The generated repository contains
AppStream metadata, so SpacedBazaar and other Flatpak stores can search it in
the same way they search Flathub.

## Trust and discovery policy

GitHub does not provide a global release-asset search API. Code search is not a
substitute: it searches source files rather than binary release assets, only
considers default branches and files below its size limit, and caps the result
and repository scope. See GitHub's
[REST search limits](https://docs.github.com/en/rest/search/search) and
[release API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).

Consequently, SpacedBazaar does not claim that it can find every Flatpak on
GitHub. It follows two separate policies:

1. `spaced-github` is curated and verified. Catalogued `crhy` release assets may
   be imported only after every validation below succeeds.
2. A future general GitHub search provider must label results as unverified,
   require an explicit per-bundle confirmation, and never install a result
   automatically. A `.flatpak` filename or MIME type is not evidence of trust.

The repository builder verifies, in order:

1. Normally, GitHub's `releases/latest` response is neither a draft nor a
   prerelease. An explicitly reviewed `release_pin` instead requests that exact
   tag and requires a matching SHA-256 for every architecture; this can select
   an approved prerelease. Drafts remain forbidden in both cases.
2. Exactly one asset matches the catalog's architecture-specific pattern.
3. The asset is fully uploaded and has a GitHub-provided SHA-256 digest.
4. The complete download matches both the advertised size and digest.
5. Importing the bundle succeeds with the installed, security-patched OSTree.
6. The bundle exports exactly the expected app ID, architecture, branch,
   runtime, and AppStream component.
7. Every app has reviewed PNG screenshots; HTTPS downloads match their pinned
   SHA-256 and expected image format. The images are hosted with the repository.
8. Publication is signed, including both AppStream metadata generations after
   inserting screenshots. Unsigned builds are for local verification only.

GitHub release assets remain mutable unless the release is made immutable. The
GitHub digest protects a particular download, but repository GPG signing is the
publisher trust boundary presented to users.

## Current catalog status

| Application | Published architectures | Status |
| --- | --- | --- |
| SpacedBazaar | `x86_64` | Publishable |
| Cards With Cats | `x86_64` | Publishable |
| Brutal Chess | `x86_64` | Publishable |
| Spaced Linux Welcome | `x86_64` | Publishable |
| Spaced Update | `x86_64` | Publishable |
| Voice2Text AI | `x86_64` | Publishable |
| rhYciv | `x86_64` | Publishable |

Every current application release exports matching AppStream metadata and a
non-empty icon, imports with patched OSTree, and is eligible for the signed
repository. A future blocked application remains in the normalized catalog
with a reason; it is never silently omitted or published until repaired.

## Build and test locally

The verifier uses only Python's standard library plus `flatpak`, `ostree`, and
`gpg`:

```sh
python3 scripts/spaced_github_repo.py validate
python3 -m unittest discover -s tests -v

python3 scripts/spaced_github_repo.py build \
  --output-dir build/spaced-github-pages \
  --cache-dir build/spaced-github-cache \
  --no-static-deltas
```

An unsigned local build writes `X-Spaced-Publishable=false` into its generated
descriptor. This makes the distinction visible in build artifacts. It is not
permission to publish an unsigned remote.

For a signed local release build:

```sh
python3 scripts/spaced_github_repo.py build \
  --output-dir build/spaced-github-pages \
  --cache-dir build/spaced-github-cache \
  --gpg-sign KEY_FINGERPRINT \
  --gpg-homedir /secure/path/to/gnupg \
  --require-signing
```

Use a new, empty output directory for every build. The command will not erase
an existing directory.

## GitHub Pages publication and signing

`.github/workflows/publish-spaced-github-repo.yml` runs deterministic tests on
pull requests and builds an unsigned verification artifact. Builds from
`main`, scheduled refreshes, and `main` workflow dispatches must be signed
before the Pages artifact can be uploaded.

Configure these encrypted repository Actions secrets before enabling Pages
publication:

- `SPACED_FLATPAK_GPG_SIGNING_KEY`: the full signing-key fingerprint.
- `SPACED_FLATPAK_GPG_PRIVATE_KEY_B64`: a base64 encoding of the exported
  private release key.

Never commit the private key, write it to workflow output, or place it in a
release asset. Restrict the key to repository signing, store its offline backup
separately, and rotate it through a reviewed catalog/repository migration. The
workflow intentionally fails when either secret is absent. GitHub Pages must
use **GitHub Actions** as its deployment source.

## Configure the client remote

After the first signed Pages deployment, configure the user remote with:

```sh
scripts/configure-spaced-github-remote.sh --user
```

The generated
`io.github.crhy.SpacedBazaar.flatpakref` is the preferred direct-install link.
It names `spaced-github` as the suggested origin, includes the repository's
public signing key, and names Flathub as the runtime source. SpacedBazaar's
0.2.0 GitHub release bundles are also created with both
`--repo-url=https://crhy.github.io/spacedbazaar/flatpak-repo/` and
`--runtime-repo=https://flathub.org/repo/flathub.flatpakrepo`, so a bundle
install does not strand the application on an unupdateable release asset.

The helper imports the signed descriptor and assigns priority `10`, higher than
Flatpak's default priority `1`. SpacedBazaar also gives `spaced-github` entries
a larger usefulness boost than duplicate Flathub entries. Flathub remains
enabled because it supplies the external GNOME and Freedesktop runtimes and the
broader application catalog.

Spaced Linux images should place the signed descriptor in
`/usr/share/flatpak/remotes.d/spaced-github.flatpakrepo` or run the helper during
image construction. Do not disable GPG verification to work around an initial
deployment or key problem.

## Release checklist

For each new CRHY application release:

1. Build with a currently supported Flatpak runtime and patched OSTree.
2. Export valid AppStream metainfo whose `<id>` exactly matches the Flatpak ID.
3. Use the catalogued branch consistently (`stable` or `master`).
4. For every supported architecture, attach exactly one matching `.flatpak`.
5. Build bundle deltas with bounded chunks; confirm a current patched Flatpak
   can import the bundle before publishing it.
6. Publish a stable release, or add an exact reviewed tag/SHA pin for a testing
   release. Never publish a draft. Keep asset bytes immutable after verification;
   a changed digest at a pinned tag intentionally stops catalog publication.
7. Run this repository workflow and review `build-report.json` before deploy.

These checks prevent filename drift, wrong-architecture bundles, ID changes,
missing store metadata, mutable-download surprises, and unsafe static deltas
from breaking every installed Spaced Linux system at once.

To promote a pinned app, verify the replacement bundle and update its tag,
asset pattern, and architecture digests together, or remove the pin to resume
following stable releases. A version-specific asset pattern avoids ambiguity
when CI also attaches an unversioned bundle to the same release. Changing this
Flatpak catalog does not opt the native OS into a testing APT suite.
