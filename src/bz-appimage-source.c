/* bz-appimage-source.c
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

#define G_LOG_DOMAIN  "BAZAAR::APPIMAGE-SOURCE"
#define BAZAAR_MODULE "appimage-source"

#include "config.h"

#include <glib/gi18n.h>
#include <gio/gio.h>
#include <glib/gstdio.h>
#include <json-glib/json-glib.h>
#include <libsoup/soup.h>
#include <libdex.h>

#include "bz-appimage-source.h"
#include "env.h"
#include "global-net.h"
#include "io.h"
#include "util.h"

/*
 * Only a finished x86_64 AppImage may be offered. Everything else a release
 * publishes next to it - the .zsync delta, signatures, checksums, metadata,
 * icons - is refused here rather than guessed at somewhere later.
 */
static const char *const non_runnable_suffixes[] = {
  ".zsync",
  ".asc",
  ".sig",
  ".part",
  ".desktop",
  ".png",
  ".svg",
  ".txt",
  ".yaml",
  ".yml",
  ".json",
};

static const char *const other_architectures[] = {
  "aarch64",
  "arm64",
  "armv7",
  "i386",
  "i686",
  "ppc64",
};

/*
 * GitHub's own `draft` and `prerelease` flags win when the response carries
 * them; these markers are the fallback for tag and title text. They are
 * deliberately blunt: a name matching any of them is never preferred over a
 * stable release.
 */
static const char *const prerelease_markers[] = {
  "rc",
  "beta",
  "alpha",
  "pre",
  "nightly",
  "dev",
  "snapshot",
  "preview",
};

/* Some projects publish one manifest for the whole release instead of one
   sidecar per asset. */
static const char *const checksums_manifest_name = "SHA256SUMS";

BZ_DEFINE_DATA (
    appimage_install,
    AppImageInstall,
    {
      BzAppImageRelease *release;
      char              *title;
      char              *icon_uri;
    },
    BZ_RELEASE_DATA (release, bz_appimage_release_unref);
    BZ_RELEASE_DATA (title, g_free);
    BZ_RELEASE_DATA (icon_uri, g_free));

BZ_DEFINE_DATA (
    appimage_uninstall,
    AppImageUninstall,
    {
      char *app_id;
    },
    BZ_RELEASE_DATA (app_id, g_free));

static DexFuture *
install_appimage_fiber (AppImageInstallData *data);

static DexFuture *
uninstall_appimage_fiber (AppImageUninstallData *data);

static gboolean
contains (const char *haystack,
          const char *needle)
{
  if (haystack == NULL || needle == NULL || needle[0] == '\0')
    return FALSE;

  return strstr (haystack, needle) != NULL;
}

/*
 * Upstream projects write their checksums in three shapes: "<digest>  <name>",
 * "<digest> *<name>" and, in a sidecar belonging to one asset only, a bare
 * "<digest>". The name is whatever follows the first whitespace run.
 */
static void
split_checksum_line (const char *line,
                     char      **out_digest,
                     char      **out_name)
{
  const char *cursor = NULL;
  const char *digest_start = NULL;
  const char *digest_end = NULL;
  const char *name_start = NULL;

  if (line == NULL)
    return;

  cursor = line;
  while (*cursor != '\0' && g_ascii_isspace (*cursor))
    cursor++;

  digest_start = cursor;
  while (*cursor != '\0' && !g_ascii_isspace (*cursor))
    cursor++;
  digest_end = cursor;

  while (*cursor != '\0' && g_ascii_isspace (*cursor))
    cursor++;

  name_start = cursor;

  if (out_digest != NULL)
    *out_digest = g_strdup_printf ("%.*s",
                                   (gint) (digest_end - digest_start),
                                   digest_start);
  if (out_name != NULL)
    *out_name = g_strdup (name_start);
}

static char *
dup_text_from_bytes (GBytes *bytes)
{
  gconstpointer data = NULL;
  gsize         size = 0;
  g_autofree char *text = NULL;

  if (bytes == NULL)
    return NULL;

  data = g_bytes_get_data (bytes, &size);
  text = g_new0 (gchar, size + 1);
  if (size > 0)
    memcpy (text, data, size);

  return g_steal_pointer (&text);
}

/*
 * Fetch a small text asset (a checksum sidecar) through Bazaar's shared HTTP
 * session, from inside a fiber.
 */
static char *
fetch_text (const char *uri,
            GError    **error)
{
  g_autoptr (GBytes) bytes = NULL;

  bytes = dex_await_boxed (bz_fetch_uri_contents (uri), error);
  if (bytes == NULL)
    return NULL;

  return dup_text_from_bytes (bytes);
}

static gboolean
write_bytes_to_path (const char *path,
                     GBytes     *bytes,
                     GError    **error)
{
  g_autoptr (GFile) file = NULL;
  gconstpointer data = NULL;
  gsize         size = 0;

  if (path == NULL || bytes == NULL)
    return FALSE;

  data = g_bytes_get_data (bytes, &size);
  file = g_file_new_for_path (path);

  return g_file_replace_contents (file, (const gchar *) data, size, NULL,
                                  FALSE, G_FILE_CREATE_NONE, NULL, NULL,
                                  error);
}

static gboolean
write_text_to_path (const char *path,
                    const char *contents,
                    GError    **error)
{
  g_autoptr (GBytes) bytes = NULL;

  if (path == NULL || contents == NULL)
    return FALSE;

  bytes = g_bytes_new (contents, strlen (contents));
  return write_bytes_to_path (path, bytes, error);
}

static gboolean
ensure_parent_dir (const char *path,
                   GError    **error)
{
  g_autofree char *parent = NULL;

  if (path == NULL)
    return FALSE;

  parent = g_path_get_dirname (path);
  if (g_mkdir_with_parents (parent, 0755) != 0)
    {
      if (error != NULL && *error == NULL)
        *error = g_error_new (G_IO_ERROR, G_IO_ERROR_FAILED,
                              "could not create %s", parent);
      return FALSE;
    }

  return TRUE;
}

static char *
dup_safe_title (const char *title)
{
  g_autofree char *safe = NULL;
  gsize length = 0;

  if (title == NULL)
    return NULL;

  length = strlen (title);
  safe = g_new0 (gchar, length + 1);

  for (gsize i = 0; i < length; i++)
    {
      gchar c = title[i];

      /* a quote or a newline in the upstream title must not be able to
         break the launcher entry written for it */
      if (c == '"' || c == '\n' || c == '\r')
        c = ' ';

      safe[i] = c;
    }

  return g_steal_pointer (&safe);
}

static DexFuture *
install_appimage_fiber (AppImageInstallData *data)
{
  BzAppImageRelease *release = data->release;
  g_autoptr (GError) local_error = NULL;
  g_autofree char *sidecar = NULL;
  g_autofree char *published = NULL;
  g_autofree char *computed = NULL;
  g_autofree char *install_path = NULL;
  g_autofree char *desktop_path = NULL;
  g_autofree char *desktop_contents = NULL;
  g_autofree char *icon_path = NULL;
  g_autoptr (GBytes) asset_bytes = NULL;
  g_autoptr (GChecksum) checksum = NULL;
  gconstpointer asset_data = NULL;
  gsize         asset_size = 0;

  if (release == NULL || release->asset_name == NULL ||
      release->download_url == NULL || release->sha256_url == NULL)
    return dex_future_new_for_error (
        g_error_new (BZ_APPIMAGE_ERROR, BZ_APPIMAGE_ERROR_NO_PUBLISHED_SHA256,
                     "no published SHA256 is known for this AppImage"));

  /*
   * 1. the digest the project published for this exact asset. A published
   * digest is required: an AppImage without one is never installed.
   */
  sidecar = fetch_text (release->sha256_url, &local_error);
  if (sidecar == NULL)
    return dex_future_new_for_error (g_steal_pointer (&local_error));

  published = bz_appimage_lookup_published_sha256 (sidecar, release->asset_name);
  if (published == NULL || !bz_appimage_sha256_is_valid (published))
    return dex_future_new_for_error (
        g_error_new (BZ_APPIMAGE_ERROR, BZ_APPIMAGE_ERROR_NO_PUBLISHED_SHA256,
                     "%s publishes no usable SHA256 for %s",
                     release->owner_repo ? release->owner_repo : "(unknown repo)",
                     release->asset_name));

  /*
   * 2. the bytes and their digest. Nothing at all is written to disk until
   * the two digests agree.
   */
  asset_bytes = dex_await_boxed (bz_fetch_uri_contents (release->download_url),
                                 &local_error);
  if (asset_bytes == NULL)
    return dex_future_new_for_error (g_steal_pointer (&local_error));

  checksum = g_checksum_new (G_CHECKSUM_SHA256);
  asset_data = g_bytes_get_data (asset_bytes, &asset_size);
  g_checksum_update (checksum, asset_data, (gssize) asset_size);
  computed = g_strdup (g_checksum_get_string (checksum));

  if (!bz_appimage_sha256_matches (published, computed))
    return dex_future_new_for_error (
        g_error_new (BZ_APPIMAGE_ERROR, BZ_APPIMAGE_ERROR_SHA256_MISMATCH,
                     "%s: the bytes fetched do not match the published SHA256 "
                     "%s (computed %s); nothing was installed",
                     release->asset_name, published, computed));

  /*
   * 3. the AppImage itself, under ~/Applications, made executable.
   */
  install_path = bz_appimage_dup_install_path (release->asset_name);
  if (install_path == NULL)
    return dex_future_new_for_error (
        g_error_new (BZ_APPIMAGE_ERROR, BZ_APPIMAGE_ERROR_UNSAFE_NAME,
                     "refusing the asset name %s", release->asset_name));

  if (!ensure_parent_dir (install_path, &local_error))
    return dex_future_new_for_error (g_steal_pointer (&local_error));

  if (!write_bytes_to_path (install_path, asset_bytes, &local_error))
    return dex_future_new_for_error (g_steal_pointer (&local_error));

  if (g_chmod (install_path, 0755) != 0)
    g_warning ("%s: could not make the AppImage executable", install_path);

  /*
   * 4. the launcher entry, and the icon beside it, so the installed app
   * appears under its own name and can never be mistaken for the Flatpak
   * entry of the same application.
   */
  desktop_path = bz_appimage_dup_desktop_path (release->app_id);
  desktop_contents = bz_appimage_dup_desktop_contents (release->app_id,
                                                       data->title,
                                                       release->asset_name);
  if (desktop_path == NULL || desktop_contents == NULL ||
      !ensure_parent_dir (desktop_path, NULL) ||
      !write_text_to_path (desktop_path, desktop_contents, &local_error))
    {
      g_warning ("%s: could not write the launcher entry: %s",
                 release->app_id,
                 local_error != NULL ? local_error->message : "(unknown)");
      g_clear_error (&local_error);
    }

  if (data->icon_uri != NULL)
    {
      g_autoptr (GBytes) icon_bytes = NULL;

      icon_path = bz_appimage_dup_icon_path (release->app_id);
      icon_bytes = dex_await_boxed (bz_fetch_uri_contents (data->icon_uri),
                                    &local_error);
      if (icon_bytes == NULL ||
          !ensure_parent_dir (icon_path, NULL) ||
          !write_bytes_to_path (icon_path, icon_bytes, &local_error))
        {
          g_warning ("%s: could not write the launcher icon: %s",
                     release->app_id,
                     local_error != NULL ? local_error->message : "(unknown)");
          g_clear_error (&local_error);
        }
    }

  g_debug ("%s: installed %s with a verified SHA256",
           release->app_id, install_path);

  return dex_future_new_true ();
}

static DexFuture *
uninstall_appimage_fiber (AppImageUninstallData *data)
{
  g_autoptr (GPtrArray) paths = NULL;
  gboolean removed_any = FALSE;

  paths = bz_appimage_dup_uninstall_paths (data->app_id, NULL);

  for (guint i = 0; i < paths->len; i++)
    {
      const char *path = g_ptr_array_index (paths, i);

      if (path == NULL || !g_file_test (path, G_FILE_TEST_EXISTS))
        continue;

      if (g_remove (path) != 0)
        g_warning ("could not remove %s", path);
      else
        removed_any = TRUE;
    }

  return dex_future_new_for_boolean (removed_any);
}

/* Public API */

GQuark
bz_appimage_error_quark (void)
{
  /*
   * A quark unique to this module: the address of a static in this
   * translation unit cannot collide with any other error domain in the
   * process, and no interning table has to be kept alive for it.
   */
  static const char domain_marker = 0;

  return (GQuark) (((guintptr) &domain_marker) & 0x7fffffff);
}

BzAppImageRelease *
bz_appimage_release_new (void)
{
  BzAppImageRelease *release = NULL;

  release = g_new0 (BzAppImageRelease, 1);
  release->refcount = 1;

  return release;
}

BzAppImageRelease *
bz_appimage_release_ref (BzAppImageRelease *self)
{
  if (self == NULL)
    return NULL;

  self->refcount++;
  return self;
}

void
bz_appimage_release_unref (BzAppImageRelease *self)
{
  if (self == NULL)
    return;

  if (--(self->refcount) > 0)
    return;

  g_free (self->app_id);
  g_free (self->owner_repo);
  g_free (self->tag_name);
  g_free (self->asset_name);
  g_free (self->download_url);
  g_free (self->sha256_url);
  g_free (self->published_sha256);
  g_free (self);
}

gboolean
bz_appimage_asset_is_runnable (const char *asset_name)
{
  if (asset_name == NULL)
    return FALSE;

  if (!g_str_has_suffix (asset_name, ".AppImage"))
    return FALSE;

  for (gsize i = 0; i < G_N_ELEMENTS (non_runnable_suffixes); i++)
    {
      if (g_str_has_suffix (asset_name, non_runnable_suffixes[i]))
        return FALSE;
    }

  return TRUE;
}

gboolean
bz_appimage_asset_matches_architecture (const char *asset_name)
{
  g_autofree char *lower = NULL;

  if (asset_name == NULL)
    return FALSE;

  lower = g_ascii_strdown (asset_name, -1);

  for (gsize i = 0; i < G_N_ELEMENTS (other_architectures); i++)
    {
      if (contains (lower, other_architectures[i]))
        return FALSE;
    }

  return contains (lower, "x86_64") ||
         contains (lower, "amd64") ||
         contains (lower, "x86-64");
}

gboolean
bz_appimage_release_is_prerelease (const char *tag_name,
                                   const char *name)
{
  g_autofree char *tag = NULL;
  g_autofree char *label = NULL;

  tag = tag_name ? g_ascii_strdown (tag_name, -1) : NULL;
  label = name ? g_ascii_strdown (name, -1) : NULL;

  if (tag == NULL && label == NULL)
    return TRUE;

  for (gsize i = 0; i < G_N_ELEMENTS (prerelease_markers); i++)
    {
      if (contains (tag, prerelease_markers[i]) ||
          contains (label, prerelease_markers[i]))
        return TRUE;
    }

  return FALSE;
}

gint
bz_appimage_select_asset (GPtrArray *asset_names)
{
  gsize found_len = 0;
  gint  found = -1;

  if (asset_names == NULL)
    return -1;

  for (guint i = 0; i < asset_names->len; i++)
    {
      const char *name = g_ptr_array_index (asset_names, i);
      gsize      name_len = 0;

      if (!bz_appimage_asset_is_runnable (name))
        continue;
      if (!bz_appimage_asset_matches_architecture (name))
        continue;

      name_len = g_utf8_strlen (name, -1);

      /* a release should not offer two x86_64 AppImages; when it does, the
         plainly named one wins over one carrying an extra suffix */
      if (found < 0 || name_len < found_len)
        {
          found = (gint) i;
          found_len = name_len;
        }
    }

  return found;
}

char *
bz_appimage_dup_sha256sums_asset_name (const char *asset_name)
{
  if (asset_name == NULL)
    return NULL;

  return g_strdup_printf ("%s-SHA256.txt", asset_name);
}

const char *
bz_appimage_dup_checksums_manifest_name (void)
{
  return checksums_manifest_name;
}

char *
bz_appimage_lookup_published_sha256 (const char *contents,
                                     const char *asset_name)
{
  const char *cursor = NULL;

  if (contents == NULL || asset_name == NULL)
    return NULL;

  cursor = contents;
  while (cursor != NULL)
    {
      const char *newline = NULL;
      g_autofree char *line = NULL;
      g_autofree char *digest = NULL;
      g_autofree char *name = NULL;
      g_autofree char *base = NULL;

      newline = strchr (cursor, '\n');
      if (newline != NULL)
        {
          line = g_strdup_printf ("%.*s", (gint) (newline - cursor), cursor);
          cursor = newline + 1;
        }
      else
        {
          line = g_strdup (cursor);
          cursor = NULL;
        }

      g_strstrip (line);
      if (line[0] == '\0')
        continue;

      split_checksum_line (line, &digest, &name);

      /* checksums manifests sometimes prefix the path with '*' or './' */
      if (name != NULL && name[0] == '*')
        {
          g_autofree char *stripped = g_strdup (name + 1);
          name = g_strdup (stripped);
        }

      base = (name != NULL && name[0] != '\0') ? g_path_get_basename (name)
                                               : NULL;

      if ((name != NULL && name[0] == '\0') ||
          g_strcmp0 (name, asset_name) == 0 ||
          g_strcmp0 (base, asset_name) == 0)
        {
          if (bz_appimage_sha256_is_valid (digest))
            return g_strdup (digest);
        }
    }

  return NULL;
}

gboolean
bz_appimage_sha256_is_valid (const char *candidate)
{
  gsize length = 0;

  if (candidate == NULL)
    return FALSE;

  length = strlen (candidate);
  if (length != 64)
    return FALSE;

  for (gsize i = 0; i < length; i++)
    {
      if (!g_ascii_isxdigit (candidate[i]))
        return FALSE;
    }

  return TRUE;
}

gboolean
bz_appimage_sha256_matches (const char *published,
                            const char *computed)
{
  if (!bz_appimage_sha256_is_valid (published) ||
      !bz_appimage_sha256_is_valid (computed))
    return FALSE;

  return g_ascii_strcasecmp (published, computed) == 0;
}

gboolean
bz_appimage_asset_name_is_safe (const char *asset_name)
{
  gsize length = 0;

  if (asset_name == NULL || asset_name[0] == '\0')
    return FALSE;

  if (asset_name[0] == '.' ||
      strchr (asset_name, '/') != NULL ||
      strchr (asset_name, '\\') != NULL)
    return FALSE;

  length = strlen (asset_name);
  for (gsize i = 0; i < length; i++)
    {
      if (g_ascii_iscntrl (asset_name[i]))
        return FALSE;
    }

  return TRUE;
}

char *
bz_appimage_dup_applications_dir (void)
{
  return g_build_filename (g_get_home_dir (), "Applications", NULL);
}

char *
bz_appimage_dup_install_path (const char *asset_name)
{
  g_autofree char *dir = NULL;

  if (!bz_appimage_asset_name_is_safe (asset_name))
    return NULL;

  dir = bz_appimage_dup_applications_dir ();
  return g_build_filename (dir, asset_name, NULL);
}

char *
bz_appimage_dup_desktop_path (const char *app_id)
{
  g_autofree char *file_name = NULL;

  if (app_id == NULL)
    return NULL;

  file_name = g_strdup_printf ("%s-AppImage.desktop", app_id);
  return g_build_filename (g_get_home_dir (), ".local", "share",
                           "applications", file_name, NULL);
}

char *
bz_appimage_dup_icon_path (const char *app_id)
{
  g_autofree char *file_name = NULL;

  if (app_id == NULL)
    return NULL;

  file_name = g_strdup_printf ("%s.png", app_id);
  return g_build_filename (g_get_home_dir (), ".local", "share", "icons",
                           "hicolor", "256x256", "apps", file_name, NULL);
}

char *
bz_appimage_dup_desktop_contents (const char *app_id,
                                  const char *title,
                                  const char *asset_name)
{
  g_autofree char *install_path = NULL;
  g_autofree char *safe_title = NULL;
  g_autofree char *name = NULL;

  if (app_id == NULL)
    return NULL;

  install_path = bz_appimage_dup_install_path (asset_name);
  if (install_path == NULL)
    return NULL;

  /* the entry names the format, so it can never be confused with the Flatpak
     entry of the same application */
  safe_title = title ? dup_safe_title (title) : g_strdup (app_id);
  name = g_strdup_printf ("%s (AppImage)", safe_title);

  return g_strdup_printf ("[Desktop Entry]\n"
                          "Version=1.0\n"
                          "Type=Application\n"
                          "Name=%s\n"
                          "Comment=Installed by SpacedBazaar as an AppImage\n"
                          "Exec=%s\n"
                          "Path=%s\n"
                          "Icon=%s\n"
                          "Terminal=false\n"
                          "StartupNotify=false\n",
                          name, install_path,
                          bz_appimage_dup_applications_dir (), app_id);
}

GPtrArray *
bz_appimage_dup_uninstall_paths (const char *app_id,
                                 const char *asset_name)
{
  g_autoptr (GPtrArray) paths = NULL;
  g_autofree char *dir = NULL;
  GDir *dir_handle = NULL;
  const gchar *entry_name = NULL;

  paths = g_ptr_array_new_with_free_func (g_free);
  if (app_id == NULL)
    return g_steal_pointer (&paths);

  /* every AppImage in ~/Applications whose name starts with this app id is
     one this app installed */
  dir = bz_appimage_dup_applications_dir ();
  dir_handle = g_dir_open (dir, 0, NULL);
  if (dir_handle != NULL)
    {
      while ((entry_name = g_dir_read_name (dir_handle)) != NULL)
        {
          if (!g_str_has_suffix (entry_name, ".AppImage"))
            continue;
          if (!g_str_has_prefix (entry_name, app_id))
            continue;

          g_ptr_array_add (paths, g_build_filename (dir, entry_name, NULL));
        }

      g_dir_close (dir_handle);
    }

  if (asset_name != NULL)
    {
      g_autofree char *install_path = bz_appimage_dup_install_path (asset_name);

      if (install_path != NULL)
        g_ptr_array_add (paths, g_strdup (install_path));
    }

  g_ptr_array_add (paths, bz_appimage_dup_desktop_path (app_id));
  g_ptr_array_add (paths, bz_appimage_dup_icon_path (app_id));

  return g_steal_pointer (&paths);
}

gboolean
bz_appimage_is_installed (const char *app_id)
{
  g_autoptr (GPtrArray) paths = NULL;
  gboolean installed = FALSE;

  paths = bz_appimage_dup_uninstall_paths (app_id, NULL);

  /* the desktop entry and the icon are counted too, so a half-removed
     install is still reported as present until it is cleaned up */
  installed = paths->len > 0;

  return installed;
}

DexFuture *
bz_appimage_source_query_release_json (const char *owner_repo)
{
  g_autofree char *uri = NULL;

  if (owner_repo == NULL)
    return dex_future_new_for_error (
        g_error_new (G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                     "no upstream repository to query"));

  uri = g_strdup_printf ("https://api.github.com/repos/%s/releases", owner_repo);
  return bz_https_query_json (uri);
}

static BzAppImageRelease *
release_from_releases (JsonArray  *releases,
                       const char *app_id,
                       const char *owner_repo,
                       gboolean    allow_prerelease,
                       gboolean   *saw_without_digest)
{
  if (releases == NULL || app_id == NULL || owner_repo == NULL)
    return NULL;

  for (guint i = 0; i < json_array_get_length (releases); i++)
    {
      JsonObject *release = json_array_get_object_element (releases, i);
      JsonArray *assets = NULL;
      g_autoptr (GPtrArray) asset_names = NULL;
      g_autofree char *tag = NULL;
      g_autofree char *title = NULL;
      g_autofree char *asset_name = NULL;
      g_autofree char *sidecar_name = NULL;
      g_autofree char *asset_url = NULL;
      g_autofree char *sidecar_url = NULL;
      BzAppImageRelease *result = NULL;
      gboolean prerelease = FALSE;
      gint selected = -1;

      if (release == NULL)
        continue;

      /* a draft is not a publication at all */
      if (json_object_has_member (release, "draft") &&
          json_object_get_boolean_member (release, "draft"))
        continue;

      tag = json_object_has_member (release, "tag_name")
        ? g_strdup (json_object_get_string_member (release, "tag_name"))
        : NULL;
      title = json_object_has_member (release, "name")
        ? g_strdup (json_object_get_string_member (release, "name"))
        : NULL;

      prerelease = json_object_has_member (release, "prerelease")
        ? json_object_get_boolean_member (release, "prerelease")
        : bz_appimage_release_is_prerelease (tag, title);

      if (prerelease && !allow_prerelease)
        continue;

      if (!json_object_has_member (release, "assets"))
        continue;
      assets = json_object_get_array_member (release, "assets");

      asset_names = g_ptr_array_new_with_free_func (g_free);
      for (guint j = 0; j < json_array_get_length (assets); j++)
        {
          JsonObject *asset = json_array_get_object_element (assets, j);

          if (asset == NULL || !json_object_has_member (asset, "name"))
            continue;

          g_ptr_array_add (asset_names,
                           g_strdup (json_object_get_string_member (asset,
                                  "name")));
        }

      selected = bz_appimage_select_asset (asset_names);
      if (selected < 0)
        continue;

      asset_name = g_strdup (g_ptr_array_index (asset_names, (guint) selected));
      sidecar_name = bz_appimage_dup_sha256sums_asset_name (asset_name);

      for (guint j = 0; j < json_array_get_length (assets); j++)
        {
          JsonObject *asset = json_array_get_object_element (assets, j);
          const char *name = NULL;
          const char *url = NULL;

          if (asset == NULL || !json_object_has_member (asset, "name") ||
              !json_object_has_member (asset, "browser_download_url"))
            continue;

          name = json_object_get_string_member (asset, "name");
          url = json_object_get_string_member (asset, "browser_download_url");

          if (g_strcmp0 (name, asset_name) == 0 && asset_url == NULL)
            asset_url = g_strdup (url);
          else if (g_strcmp0 (name, sidecar_name) == 0 && sidecar_url == NULL)
            sidecar_url = g_strdup (url);
          else if (g_strcmp0 (name, checksums_manifest_name) == 0 &&
                   sidecar_url == NULL)
            sidecar_url = g_strdup (url);
        }

      if (asset_url == NULL)
        continue;

      /* the digest is required: either the per-asset sidecar or the release
         wide manifest, never a guess */
      if (sidecar_url == NULL)
        {
          if (saw_without_digest != NULL)
            *saw_without_digest = TRUE;
          continue;
        }

      result = bz_appimage_release_new ();
      result->app_id = g_strdup (app_id);
      result->owner_repo = g_strdup (owner_repo);
      result->tag_name = g_strdup (tag);
      result->asset_name = g_steal_pointer (&asset_name);
      result->download_url = g_steal_pointer (&asset_url);
      result->sha256_url = g_steal_pointer (&sidecar_url);
      result->prerelease = prerelease;

      return result;
    }

  return NULL;
}

BzAppImageRelease *
bz_appimage_release_from_json (JsonNode   *node,
                               const char *app_id,
                               const char *owner_repo,
                               GError    **error)
{
  JsonArray *releases = NULL;
  gboolean saw_without_digest = FALSE;
  BzAppImageRelease *release = NULL;

  if (node == NULL || !JSON_NODE_HOLDS_ARRAY (node))
    {
      if (error != NULL && *error == NULL)
        *error = g_error_new (G_IO_ERROR, G_IO_ERROR_INVALID_DATA,
                              "the release response is not a list");
      return NULL;
    }

  releases = json_node_get_array (node);

  /* stable releases are always considered before pre-releases */
  release = release_from_releases (releases, app_id, owner_repo, FALSE,
                                   &saw_without_digest);
  if (release == NULL)
    release = release_from_releases (releases, app_id, owner_repo, TRUE,
                                     &saw_without_digest);

  if (release == NULL)
    {
      if (error != NULL && *error == NULL)
        {
          if (saw_without_digest)
            *error = g_error_new (BZ_APPIMAGE_ERROR,
                                  BZ_APPIMAGE_ERROR_NO_PUBLISHED_SHA256,
                                  "%s has an x86_64 AppImage with no published "
                                  "SHA256", owner_repo);
          else
            *error = g_error_new (BZ_APPIMAGE_ERROR,
                                  BZ_APPIMAGE_ERROR_NO_ASSET,
                                  "%s publishes no x86_64 AppImage", owner_repo);
        }
    }

  return release;
}

DexFuture *
bz_appimage_source_install (BzAppImageRelease *release,
                            const char       *title,
                            const char       *icon_uri)
{
  g_autoptr (AppImageInstallData) data = NULL;

  if (release == NULL)
    return dex_future_new_for_error (
        g_error_new (G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                     "no AppImage release to install"));

  data = appimage_install_data_new ();
  data->release = bz_appimage_release_ref (release);
  data->title = g_strdup (title);
  data->icon_uri = g_strdup (icon_uri);

  return dex_scheduler_spawn (bz_get_io_scheduler (), bz_get_dex_stack_size (),
                              (DexFiberFunc) install_appimage_fiber,
                              appimage_install_data_ref (data),
                              appimage_install_data_unref);
}

DexFuture *
bz_appimage_source_uninstall (const char *app_id)
{
  g_autoptr (AppImageUninstallData) data = NULL;

  if (app_id == NULL)
    return dex_future_new_for_error (
        g_error_new (G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                     "no app id to uninstall"));

  data = appimage_uninstall_data_new ();
  data->app_id = g_strdup (app_id);

  return dex_scheduler_spawn (bz_get_io_scheduler (), bz_get_dex_stack_size (),
                              (DexFiberFunc) uninstall_appimage_fiber,
                              appimage_uninstall_data_ref (data),
                              appimage_uninstall_data_unref);
}
