/* bz-format-choice.c
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

#define G_LOG_DOMAIN "BAZAAR::FORMAT-CHOICE"

#include "config.h"

#include <glib/gi18n.h>
#include <json-glib/json-glib.h>

#include "bz-format-choice.h"

/*
 * How much each fact is worth, in the order the rules are weighed: the
 * curated advice for a specific application outweighs everything else;
 * being already installed outranks freshness; sandboxing only matters when
 * the versions are equal; and the download being smaller is the very last
 * tie-breaker.
 */
#define ADVICE_WEIGHT 100
#define INSTALLED_WEIGHT 50
#define NEWEST_WEIGHT 20
#define KNOWN_VERSION_WEIGHT 5
#define SANDBOX_WEIGHT 15
#define SIZE_WEIGHT 1

/*
 * Ties go to the sandboxed build first: Bazaar's own install path, and the
 * only one of the three that contains the application.
 */
static const BzFormatChoiceFormat preference_order[] = {
  BZ_FORMAT_CHOICE_FORMAT_FLATPAK,
  BZ_FORMAT_CHOICE_FORMAT_APPIMAGE,
  BZ_FORMAT_CHOICE_FORMAT_APT,
};

static const struct
{
  BzFormatChoiceFormat format;
  const char *name;
  const char *label;
  gboolean sandboxed;
} format_names[] = {
  { BZ_FORMAT_CHOICE_FORMAT_APT, "apt", "apt", FALSE },
  { BZ_FORMAT_CHOICE_FORMAT_FLATPAK, "flatpak", "Flatpak", TRUE },
  { BZ_FORMAT_CHOICE_FORMAT_APPIMAGE, "appimage", "AppImage", FALSE },
};

/*
 * The curated advice table, read once from the installed data file. A
 * missing or malformed file means no advice at all: nothing is guessed, and
 * the sandboxed build stays the default.
 */
static GMutex advice_mutex = { 0 };
static gboolean advice_loaded = FALSE;
static GPtrArray *advice_rows = NULL;
static GHashTable *advice_table = NULL;

static void
free_advice_row (gpointer row)
{
  BzFormatAdvice *advice = row;

  if (advice == NULL)
    return;

  g_free ((gchar *) advice->reason);
  g_free ((gchar *) advice->appimage_repo);
  g_free ((gchar *) advice->apt_package);
  g_free (advice);
}

/* the caller must already hold advice_mutex */
static void
load_advice_locked (void)
{
  g_autofree char *contents = NULL;
  g_autoptr (JsonParser) parser = NULL;
  JsonNode *root = NULL;
  JsonObject *root_obj = NULL;
  JsonArray *entries = NULL;
  g_autoptr (GError) local_error = NULL;
  const char *advice_path = FORMAT_ADVICE_PATH;

  if (advice_loaded)
    return;

  advice_loaded = TRUE;
  advice_rows = g_ptr_array_new_with_free_func (free_advice_row);
  advice_table = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, NULL);

  /*
   * A development build runs from the source tree, where the installed file
   * is not in place yet; fall back to the copy next to the sources.
   */
  if (!g_file_get_contents (advice_path, &contents, NULL, &local_error))
    {
#ifdef DEVELOPMENT_FORMAT_ADVICE_PATH
      g_autofree char *dev_contents = NULL;

      if (g_file_get_contents (DEVELOPMENT_FORMAT_ADVICE_PATH, &dev_contents,
                               NULL, NULL))
        {
          advice_path = DEVELOPMENT_FORMAT_ADVICE_PATH;
          contents = g_steal_pointer (&dev_contents);
        }
      else
        {
          g_warning ("%s: could not be read (%s); no format advice is available",
                     advice_path, local_error->message);
          return;
        }
#else
      g_warning ("%s: could not be read (%s); no format advice is available",
                 advice_path, local_error->message);
      return;
#endif
    }

  parser = json_parser_new ();
  if (!json_parser_load_from_data (parser, contents, -1, &local_error))
    {
      g_warning ("%s: is not valid JSON (%s); no format advice is available",
                 advice_path, local_error->message);
      return;
    }

  root = json_parser_get_root (parser);
  if (root == NULL || !JSON_NODE_HOLDS_OBJECT (root))
    {
      g_warning ("%s: is not a JSON object; no format advice is available",
                 advice_path);
      return;
    }

  root_obj = json_node_get_object (root);
  if (!json_object_has_member (root_obj, "advice"))
    {
      g_warning ("%s: has no \"advice\" member; no format advice is available",
                 advice_path);
      return;
    }

  entries = json_object_get_array_member (root_obj, "advice");

  for (guint i = 0; i < json_array_get_length (entries); i++)
    {
      JsonObject *entry = json_array_get_object_element (entries, i);
      const char *app_id = NULL;
      const char *pick = NULL;
      const char *reason = NULL;
      BzFormatChoiceFormat format = BZ_FORMAT_CHOICE_FORMAT_INVALID;
      BzFormatAdvice *advice = NULL;

      if (entry == NULL || !json_object_has_member (entry, "app_id") ||
          !json_object_has_member (entry, "pick") ||
          !json_object_has_member (entry, "reason"))
        {
          g_warning ("%s: an advice entry names no application, no build and "
                     "no reason; it is ignored",
                     advice_path);
          continue;
        }

      app_id = json_object_get_string_member (entry, "app_id");
      pick = json_object_get_string_member (entry, "pick");
      reason = json_object_get_string_member (entry, "reason");
      format = bz_format_choice_parse_format (pick);

      if (app_id == NULL || app_id[0] == '\0' ||
          format == BZ_FORMAT_CHOICE_FORMAT_INVALID)
        {
          g_warning ("%s: advice for %s names the unknown build %s; it is ignored",
                     advice_path, app_id ? app_id : "(nothing)",
                     pick ? pick : "(nothing)");
          continue;
        }

      if (g_hash_table_contains (advice_table, app_id))
        {
          g_warning ("%s: %s is advised twice; the first line wins",
                     advice_path, app_id);
          continue;
        }

      advice = g_new0 (BzFormatAdvice, 1);
      advice->pick = format;
      advice->reason = g_strdup (reason);
      advice->appimage_repo =
          json_object_has_member (entry, "appimage_repo")
        ? g_strdup (json_object_get_string_member (entry, "appimage_repo"))
        : NULL;
      advice->apt_package =
          json_object_has_member (entry, "apt_package")
        ? g_strdup (json_object_get_string_member (entry, "apt_package"))
        : NULL;

      g_ptr_array_add (advice_rows, advice);
      g_hash_table_insert (advice_table, g_strdup (app_id), advice);
    }

  g_debug ("%s: %u applications have curated format advice",
           advice_path, advice_rows->len);
}

/* Public API */

const char *
bz_format_choice_format_name (BzFormatChoiceFormat format)
{
  for (gsize i = 0; i < G_N_ELEMENTS (format_names); i++)
    {
      if (format_names[i].format == format)
        return format_names[i].name;
    }

  return NULL;
}

const char *
bz_format_choice_format_label (BzFormatChoiceFormat format)
{
  for (gsize i = 0; i < G_N_ELEMENTS (format_names); i++)
    {
      if (format_names[i].format == format)
        return format_names[i].label;
    }

  return NULL;
}

gboolean
bz_format_choice_format_is_sandboxed (BzFormatChoiceFormat format)
{
  for (gsize i = 0; i < G_N_ELEMENTS (format_names); i++)
    {
      if (format_names[i].format == format)
        return format_names[i].sandboxed;
    }

  return FALSE;
}

BzFormatChoiceFormat
bz_format_choice_parse_format (const char *name)
{
  if (name == NULL)
    return BZ_FORMAT_CHOICE_FORMAT_INVALID;

  for (gsize i = 0; i < G_N_ELEMENTS (format_names); i++)
    {
      if (g_ascii_strcasecmp (format_names[i].name, name) == 0)
        return format_names[i].format;
    }

  return BZ_FORMAT_CHOICE_FORMAT_INVALID;
}

gint
bz_format_choice_compare_versions (const char *a,
                                   const char *b)
{
  const char *ia = NULL;
  const char *ib = NULL;

  if (g_strcmp0 (a, b) == 0)
    return 0;

  /* an unknown version is never newer than a known one */
  if (a == NULL)
    return -1;
  if (b == NULL)
    return 1;

  ia = a;
  ib = b;

  while (*ia != '\0' || *ib != '\0')
    {
      while (*ia != '\0' && !g_ascii_isalnum (*ia))
        ia++;
      while (*ib != '\0' && !g_ascii_isalnum (*ib))
        ib++;

      if (*ia == '\0' && *ib == '\0')
        break;
      if (*ia == '\0')
        return -1;
      if (*ib == '\0')
        return 1;

      if (g_ascii_isdigit (*ia) && g_ascii_isdigit (*ib))
        {
          gchar *end_a = NULL;
          gchar *end_b = NULL;
          gint64 num_a = 0;
          gint64 num_b = 0;

          num_a = g_ascii_strtoll (ia, &end_a, 10);
          num_b = g_ascii_strtoll (ib, &end_b, 10);

          if (num_a != num_b)
            return (num_a > num_b) - (num_a < num_b);

          ia = end_a;
          ib = end_b;
          continue;
        }

      if (g_ascii_isalpha (*ia) && g_ascii_isalpha (*ib))
        {
          while (g_ascii_isalpha (*ia) && g_ascii_isalpha (*ib))
            {
              if (*ia != *ib)
                return (*ia > *ib) - (*ia < *ib);

              ia++;
              ib++;
            }

          /* the longer word is the newer one: "beta" after "b" */
          if (g_ascii_isalpha (*ia))
            return 1;
          if (g_ascii_isalpha (*ib))
            return -1;

          continue;
        }

      /* a number against a word: the number is the release, the word is a
         suffix on it */
      if (g_ascii_isdigit (*ia))
        return 1;
      if (g_ascii_isalpha (*ia))
        return -1;
    }

  return 0;
}

/*
 * TRUE when the part after a '-' or '+' separator is a packaging suffix and
 * not part of the release: a bare revision number (Debian's "-1", Flatpak's
 * "-2"), an "r", "rev", "re" or "build" revision, or the "dfsg"/"ds" marks.
 * Anything with text in it ("beta1", "rc2", "spaced") belongs to the release
 * itself and is never treated as packaging.
 */
static gboolean
is_packaging_suffix (const char *suffix)
{
  const char *p = NULL;
  const char *digits = NULL;

  if (suffix == NULL || suffix[0] == '\0')
    return FALSE;

  if (g_strcmp0 (suffix, "dfsg") == 0 ||
      g_strcmp0 (suffix, "ds") == 0)
    return TRUE;

  if (g_str_has_prefix (suffix, "dfsg"))
    return TRUE;

  p = suffix;
  if (g_str_has_prefix (p, "rev") || g_str_has_prefix (p, "build"))
    p += 3;
  else if (g_str_has_prefix (p, "re"))
    p += 2;

  digits = p;
  while (*p != '\0')
    {
      if (!g_ascii_isdigit (*p) && *p != '.')
        return FALSE;
      p++;
    }

  return digits != p && g_ascii_isdigit (digits[0]);
}

char *
bz_format_choice_dup_release_version (const char *version)
{
  const char *p = NULL;

  if (version == NULL)
    return NULL;

  for (p = version; *p != '\0'; p++)
    {
      if (*p != '-' && *p != '+')
        continue;

      if (is_packaging_suffix (p + 1))
        return g_strndup (version, p - version);
    }

  return g_strdup (version);
}

gboolean
bz_format_choice_apt_package_is_installed (const char *package)
{
  g_autofree char *path = NULL;
  g_autofree char *file_name = NULL;

  if (package == NULL || package[0] == '\0')
    return FALSE;

  /* dpkg keeps a file list for every installed package; that file existing
     is the cheapest honest signal that the package is installed. Nothing is
     run. */
  file_name = g_strdup_printf ("%s.list", package);
  path = g_build_filename ("/var/lib/dpkg/info", file_name, NULL);

  return g_file_test (path, G_FILE_TEST_EXISTS);
}

const BzFormatAdvice *
bz_format_advice_lookup (const char *app_id)
{
  g_autoptr (GMutexLocker) locker = NULL;

  if (app_id == NULL)
    return NULL;

  locker = g_mutex_locker_new (&advice_mutex);
  load_advice_locked ();

  return g_hash_table_lookup (advice_table, app_id);
}

BzFormatChoice *
bz_format_choice_new (void)
{
  BzFormatChoice *choice = NULL;

  choice = g_new0 (BzFormatChoice, 1);
  choice->refcount = 1;
  choice->pick = BZ_FORMAT_CHOICE_FORMAT_INVALID;

  return choice;
}

BzFormatChoice *
bz_format_choice_ref (BzFormatChoice *self)
{
  if (self == NULL)
    return NULL;

  self->refcount++;
  return self;
}

void
bz_format_choice_unref (BzFormatChoice *self)
{
  if (self == NULL)
    return;

  if (--(self->refcount) > 0)
    return;

  g_free (self->reason);
  g_free (self->installed_note);
  g_free (self->pick_version);
  for (guint i = 0; i < BZ_FORMAT_CHOICE_N_FORMATS; i++)
    g_free (self->lines[i]);

  g_free (self);
}

BzFormatChoiceFormat
bz_format_choice_get_pick (BzFormatChoice *self)
{
  if (self == NULL)
    return BZ_FORMAT_CHOICE_FORMAT_INVALID;

  return self->pick;
}

const char *
bz_format_choice_get_reason (BzFormatChoice *self)
{
  if (self == NULL)
    return NULL;

  return self->reason;
}

gboolean
bz_format_choice_get_overridden (BzFormatChoice *self)
{
  if (self == NULL)
    return FALSE;

  return self->overridden;
}

const char *
bz_format_choice_get_line (BzFormatChoice *self,
                           BzFormatChoiceFormat format)
{
  if (self == NULL)
    return NULL;

  if (format > BZ_FORMAT_CHOICE_FORMAT_APPIMAGE)
    return NULL;

  return self->lines[format];
}

const char *
bz_format_choice_get_installed_note (BzFormatChoice *self)
{
  if (self == NULL)
    return NULL;

  return self->installed_note;
}

const char *
bz_format_choice_get_pick_version (BzFormatChoice *self)
{
  if (self == NULL)
    return NULL;

  return self->pick_version;
}

gint64
bz_format_choice_get_pick_size (BzFormatChoice *self)
{
  if (self == NULL)
    return 0;

  return self->pick_size;
}

BzFormatChoice *
bz_format_choice_evaluate (const char *app_id,
                           const BzFormatChoiceOffer *offers,
                           const char *override,
                           GError    **error)
{
  g_autoptr (BzFormatChoice) choice = NULL;
  const BzFormatAdvice *advice = NULL;
  g_autofree char *newest = NULL;
  gint64 smallest_size = 0;
  BzFormatChoiceFormat pick = BZ_FORMAT_CHOICE_FORMAT_INVALID;
  gint best_score = G_MININT;

  choice = bz_format_choice_new ();
  advice = bz_format_advice_lookup (app_id);

  /*
   * The newest version any build of this application is known to carry,
   * packaging suffix ignored: "1.1.4" and "1.1.4-1" are the same release,
   * and neither is newer than the other.
   */
  if (offers != NULL)
    {
      for (guint i = 0; i < BZ_FORMAT_CHOICE_N_FORMATS; i++)
        {
          const BzFormatChoiceOffer *offer = &offers[i];
          g_autofree char *release = NULL;

          if (!offer->available || offer->version == NULL)
            continue;

          release = bz_format_choice_dup_release_version (offer->version);

          if (newest == NULL ||
              bz_format_choice_compare_versions (release, newest) > 0)
            {
              g_free (newest);
              newest = g_steal_pointer (&release);
            }
        }

      /* the smallest download any build offers, when the size is known */
      for (guint i = 0; i < BZ_FORMAT_CHOICE_N_FORMATS; i++)
        {
          const BzFormatChoiceOffer *offer = &offers[i];

          if (!offer->available || offer->download_size <= 0)
            continue;

          if (smallest_size == 0 || offer->download_size < smallest_size)
            smallest_size = offer->download_size;
        }
    }

  for (guint p = 0; p < G_N_ELEMENTS (preference_order); p++)
    {
      BzFormatChoiceFormat format = preference_order[p];
      const BzFormatChoiceOffer *offer = NULL;
      g_autofree char *release = NULL;
      gint score = 0;

      if (offers == NULL)
        continue;

      offer = &offers[format];
      if (!offer->available)
        {
          choice->scores[format] = G_MININT;
          continue;
        }

      score = 0;

      if (bz_format_choice_format_is_sandboxed (format))
        score += SANDBOX_WEIGHT;
      if (offer->installed)
        score += INSTALLED_WEIGHT;

      if (offer->version != NULL)
        {
          score += KNOWN_VERSION_WEIGHT;

          release = bz_format_choice_dup_release_version (offer->version);
          if (newest != NULL &&
              bz_format_choice_compare_versions (release, newest) == 0)
            score += NEWEST_WEIGHT;
        }

      /* smaller download breaks the last tie, and only the last one */
      if (smallest_size > 0 &&
          offer->download_size > 0 &&
          offer->download_size == smallest_size)
        score += SIZE_WEIGHT;

      if (advice != NULL && advice->pick == format)
        score += ADVICE_WEIGHT;

      choice->scores[format] = score;

      if (score > best_score)
        {
          best_score = score;
          pick = format;
        }
    }

  /* the user's own choice wins outright, as long as that build exists */
  if (override != NULL)
    {
      BzFormatChoiceFormat chosen = bz_format_choice_parse_format (override);

      if (chosen != BZ_FORMAT_CHOICE_FORMAT_INVALID && offers != NULL &&
          offers[chosen].available)
        {
          choice->pick = chosen;
          choice->overridden = TRUE;
        }
    }

  if (choice->pick == BZ_FORMAT_CHOICE_FORMAT_INVALID)
    choice->pick = pick;

  if (choice->pick == BZ_FORMAT_CHOICE_FORMAT_INVALID)
    {
      if (error != NULL && *error == NULL)
        *error = g_error_new (G_IO_ERROR, G_IO_ERROR_NOT_FOUND,
                              "no build of %s is offered",
                              app_id ? app_id : "(nothing)");

      for (guint i = 0; i < BZ_FORMAT_CHOICE_N_FORMATS; i++)
        choice->lines[i] = g_strdup ("");

      return g_steal_pointer (&choice);
    }

  for (guint i = 0; i < BZ_FORMAT_CHOICE_N_FORMATS; i++)
    {
      const BzFormatChoiceOffer *offer = (offers != NULL) ? &offers[i] : NULL;
      BzFormatChoiceFormat format = (BzFormatChoiceFormat) i;
      const char *label = bz_format_choice_format_label (format);
      g_autofree char *version = NULL;
      g_autofree char *size = NULL;
      g_autofree char *line = NULL;

      if (offer != NULL && format == choice->pick)
        {
          choice->pick_version = offer->version ? g_strdup (offer->version) : NULL;
          choice->pick_size = offer->download_size;
        }

      if (offer == NULL || !offer->available)
        {
          choice->lines[i] = g_strdup_printf (_ ("%s: not offered for this app"),
                                              label);
          continue;
        }

      /* an unknown version or size is simply left out: the line never says
         "not known", it just names what is known */
      if (offer->version != NULL)
        {
          g_autofree char *version_text =
              g_strdup_printf (_ ("version %s"), offer->version);

          version = g_strdup_printf (", %s", version_text);
        }
      else
        version = g_strdup ("");

      size = offer->download_size > 0
               ? g_strdup_printf (", %s", g_format_size ((guint64) offer->download_size))
               : g_strdup ("");

      line = g_strdup_printf ("%s: %s, %s%s%s",
                              label,
                              offer->installed ? _ ("already installed")
                                               : _ ("not installed"),
                              bz_format_choice_format_is_sandboxed (format)
                                ? _ ("sandboxed")
                                : _ ("not sandboxed"),
                              size,
                              version);

      choice->lines[i] = g_steal_pointer (&line);

      if (offer->installed && choice->installed_note == NULL)
        choice->installed_note = g_strdup_printf (_ ("Installed as %s"), label);
    }

  /*
   * The reason is user wording, never the working-out: what the user gets
   * out of this build, in a sentence. The curated sentence wins when it is
   * the curated pick; otherwise the reason names the rule that actually
   * decided it.
   */
  if (choice->overridden)
    {
      choice->reason = g_strdup_printf (
        _ ("you chose the %s build for this app, so Bazaar offers that one"),
        bz_format_choice_format_label (choice->pick));
    }
  else if (advice != NULL && advice->pick == choice->pick)
    choice->reason = g_strdup (advice->reason);
  else if (offers != NULL && offers[choice->pick].installed)
    choice->reason = g_strdup (_ ("Already installed"));
  else
    {
      gboolean is_newest = FALSE;

      if (offers != NULL && newest != NULL &&
          offers[choice->pick].version != NULL)
        {
          g_autofree char *release =
              bz_format_choice_dup_release_version (
                  offers[choice->pick].version);

          is_newest = bz_format_choice_compare_versions (release, newest) == 0;
        }

      if (is_newest)
        choice->reason = g_strdup (_ ("Newest version"));
      else if (bz_format_choice_format_is_sandboxed (choice->pick))
        choice->reason = g_strdup (
          _ ("Sandboxed: kept apart from your files"));
      else
        choice->reason = g_strdup (_ ("Runs best on Spaced"));
    }

  return g_steal_pointer (&choice);
}
