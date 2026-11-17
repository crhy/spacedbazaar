/* bz-appimage-source.h
 *
 * Copyright 2026 Adam Masciola
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include <glib.h>
#include <gio/gio.h>
#include <json-glib/json-glib.h>
#include <libdex.h>

G_BEGIN_DECLS

#define BZ_APPIMAGE_ERROR (bz_appimage_error_quark ())
GQuark bz_appimage_error_quark (void);

typedef enum
{
  BZ_APPIMAGE_ERROR_NO_ASSET = 0,
  BZ_APPIMAGE_ERROR_NO_PUBLISHED_SHA256,
  BZ_APPIMAGE_ERROR_SHA256_MISMATCH,
  BZ_APPIMAGE_ERROR_UNSAFE_NAME,
  BZ_APPIMAGE_ERROR_IO,
} BzAppImageError;

/*
 * One AppImage Bazaar has decided it may offer: which upstream release it
 * came from, which asset carries the bytes, which sidecar asset carries the
 * published digest, and (once fetched) what that digest is. Every field is a
 * copied string so the release outlives the JSON it was read from.
 *
 * `published_sha256` stays NULL until the sidecar has actually been fetched;
 * nothing is downloaded or written to disk before it is non-NULL and valid.
 */
typedef struct
{
  gint refcount; /* starts at 1 */

  char *app_id;
  char *owner_repo;
  char *tag_name;
  char *asset_name;
  char *download_url;
  char *sha256_url;
  char *published_sha256;
  gboolean prerelease;
} BzAppImageRelease;

BzAppImageRelease *
bz_appimage_release_new (void);

BzAppImageRelease *
bz_appimage_release_ref (BzAppImageRelease *self);

void
bz_appimage_release_unref (BzAppImageRelease *self);

G_DEFINE_AUTOPTR_CLEANUP_FUNC (BzAppImageRelease, bz_appimage_release_unref)

/*
 * Selection, all of it pure and offline, so it can be reviewed (and tested)
 * without a network:
 *
 * - bz_appimage_asset_is_runnable() accepts only a finished AppImage, never
 *   its .zsync delta, signature or metadata sidecar.
 * - bz_appimage_asset_matches_architecture() accepts only x86_64 (amd64
 *   spellings included) and refuses assets naming another architecture.
 * - bz_appimage_release_is_prerelease() is the fallback when GitHub's own
 *   `prerelease` flag is missing: rc/beta/alpha/nightly/dev/snapshot names
 *   count as pre-release, and stable releases are always preferred.
 * - bz_appimage_select_asset() picks one runnable x86_64 asset out of a
 *   release's asset names, or -1 when the release offers none.
 */
gboolean
bz_appimage_asset_is_runnable (const char *asset_name);

gboolean
bz_appimage_asset_matches_architecture (const char *asset_name);

gboolean
bz_appimage_release_is_prerelease (const char *tag_name,
                                   const char *name);

gint
bz_appimage_select_asset (GPtrArray *asset_names);

/*
 * The sidecar that is expected to carry the published digest for `asset_name`:
 * either "<asset>-SHA256.txt" next to the asset, or a "SHA256SUMS" manifest
 * covering the whole release. A published digest is required, never assumed.
 */
char *
bz_appimage_dup_sha256sums_asset_name (const char *asset_name);

/* the name of the release-wide manifest some projects publish instead */
const char *
bz_appimage_dup_checksums_manifest_name (void);

/*
 * Read the digest a project published for `asset_name` out of a
 * "<asset>-SHA256.txt" or "SHA256SUMS" body. Returns a newly allocated
 * lowercase hex string, or NULL when the body says nothing about that asset.
 */
char *
bz_appimage_lookup_published_sha256 (const char *contents,
                                     const char *asset_name);

gboolean
bz_appimage_sha256_is_valid (const char *candidate);

/*
 * Constant-time-ish comparison of the published digest with the digest
 * actually computed from the downloaded bytes. FALSE means the bytes are
 * refused: Bazaar never installs an AppImage whose digest does not match.
 */
gboolean
bz_appimage_sha256_matches (const char *published,
                            const char *computed);

/*
 * Refuse anything that could escape ~/Applications: no path separators, no
 * leading dot, no "..", no control characters.
 */
gboolean
bz_appimage_asset_name_is_safe (const char *asset_name);

/*
 * Where an installed AppImage lives, and what has to go when it is removed.
 * ~/Applications is the AppImage convention; the .desktop entry and the icon
 * go to the usual user locations so the launcher and the menu find it.
 */
char *
bz_appimage_dup_applications_dir (void);

char *
bz_appimage_dup_install_path (const char *asset_name);

char *
bz_appimage_dup_desktop_path (const char *app_id);

char *
bz_appimage_dup_icon_path (const char *app_id);

/*
 * The .desktop file Bazaar writes for an installed AppImage. The name is
 * "<app-id> (AppImage)" so it can never be mistaken for the Flatpak entry of
 * the same app, and Exec= points at the AppImage under ~/Applications.
 */
char *
bz_appimage_dup_desktop_contents (const char *app_id,
                                  const char *title,
                                  const char *asset_name);

/*
 * Every path an installed AppImage owns, newest first: the AppImage itself,
 * its .desktop entry and its icon. Uninstall removes exactly these and nothing
 * else; user data under ~/.var/app is left alone, as it is for any other
 * format.
 */
GPtrArray *
bz_appimage_dup_uninstall_paths (const char *app_id,
                                 const char *asset_name);

/*
 * TRUE when an AppImage for this app id is already present in
 * ~/Applications. A cheap directory scan, no network.
 */
gboolean
bz_appimage_is_installed (const char *app_id);

/*
 * Network and file I/O, kept behind these few functions:
 *
 * - bz_appimage_source_query_release_json() GETs the upstream release list
 *   for "owner/repo" through Bazaar's shared HTTP session.
 * - bz_appimage_release_from_json() is pure: it turns that response into a
 *   BzAppImageRelease (stable before pre-release, x86_64 asset, sidecar
 *   present) and refuses with an error otherwise.
 * - bz_appimage_source_install() fetches the sidecar, requires a published
 *   digest, downloads the asset, and only writes anything to disk once the
 *   computed digest matches. It then writes the .desktop entry and icon.
 * - bz_appimage_source_uninstall() removes exactly the installed paths.
 */
DexFuture *
bz_appimage_source_query_release_json (const char *owner_repo);

BzAppImageRelease *
bz_appimage_release_from_json (JsonNode   *node,
                               const char *app_id,
                               const char *owner_repo,
                               GError    **error);

DexFuture *
bz_appimage_source_install (BzAppImageRelease *release,
                            const char       *title,
                            const char       *icon_uri);

DexFuture *
bz_appimage_source_uninstall (const char *app_id);

G_END_DECLS
