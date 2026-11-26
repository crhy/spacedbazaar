/* bz-format-choice.h
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

G_BEGIN_DECLS

/*
 * The three ways SpacedBazaar can put an application on the desktop:
 *
 *   apt      - the system package; not sandboxed
 *   flatpak  - the sandboxed build Bazaar installs today
 *   appimage - the upstream AppImage; not sandboxed
 *
 * INVALID means "no build at all", and is what an unrecognised name parses
 * to.
 */
typedef enum
{
  BZ_FORMAT_CHOICE_FORMAT_APT = 0,
  BZ_FORMAT_CHOICE_FORMAT_FLATPAK,
  BZ_FORMAT_CHOICE_FORMAT_APPIMAGE,
  BZ_FORMAT_CHOICE_FORMAT_INVALID,
} BzFormatChoiceFormat;

#define BZ_FORMAT_CHOICE_N_FORMATS 3

/*
 * What is known about one build of one application: whether it exists at all,
 * whether it is already installed, which version it carries, and how big its
 * download is in bytes. A NULL `version` means the version is not known yet
 * (an AppImage's version is only read when its upstream release is queried),
 * and a `download_size` of 0 means the size is not known either.
 */
typedef struct
{
  BzFormatChoiceFormat format;
  gboolean available;
  gboolean installed;
  const char *version;
  gint64 download_size;
} BzFormatChoiceOffer;

/*
 * One curated line of advice from data/format-advice.json: which build to
 * prefer for one application id, why, which upstream repository publishes the
 * AppImage when the advice names one, and which apt package exists when the
 * application also ships in the system package manager. A NULL repository or
 * package means that build is not offered for this application.
 */
typedef struct
{
  BzFormatChoiceFormat pick;
  const char *reason;
  const char *appimage_repo;
  const char *apt_package;
} BzFormatAdvice;

/*
 * The decision, plus the working out: the build to offer, one sentence saying
 * why, one line per format for the app page, the score each format earned, and
 * a note naming the format this application is already installed as (NULL when
 * none is). `overridden` is TRUE when the user chose a build explicitly, which
 * always wins over the curated advice as long as that build is available.
 */
typedef struct
{
  gint refcount; /* starts at 1 */

  BzFormatChoiceFormat pick;
  gboolean overridden;
  char *reason;
  char *installed_note;
  char *pick_version;
  gint64 pick_size;
  char *lines[BZ_FORMAT_CHOICE_N_FORMATS];
  gint scores[BZ_FORMAT_CHOICE_N_FORMATS];
} BzFormatChoice;

const char *
bz_format_choice_format_name (BzFormatChoiceFormat format);

const char *
bz_format_choice_format_label (BzFormatChoiceFormat format);

/*
 * TRUE only for flatpak. apt and AppImage run as ordinary programs against
 * the whole desktop, and the wording shown to the user says so plainly.
 */
gboolean
bz_format_choice_format_is_sandboxed (BzFormatChoiceFormat format);

BzFormatChoiceFormat
bz_format_choice_parse_format (const char *name);

/*
 * Compare two version strings segment by segment ("1.1.4" vs "1.1.0-beta").
 * A NULL version is unknown and sorts oldest; 0 means equal.
 */
gint
bz_format_choice_compare_versions (const char *a,
                                   const char *b);

/*
 * The version without its packaging suffix: what upstream actually released.
 * "1.1.4-1" (Debian revision), "1.1.4+dfsg" and "1.1.4~spaced1" are all
 * 1.1.4; anything that is part of the release itself ("1.1.4-beta1") is kept.
 * Freshness ignores a difference only in such a packaging suffix.
 */
char *
bz_format_choice_dup_release_version (const char *version);

/*
 * The curated advice for an application id, or NULL when nothing is curated
 * for it. The table is read once, from the installed data file, and a
 * missing or broken file simply means no advice: nothing is guessed.
 */
const BzFormatAdvice *
bz_format_advice_lookup (const char *app_id);

/*
 * TRUE when the package apt knows about is installed system-wide. Reads
 * dpkg's own record of installed files; nothing is run.
 */
gboolean
bz_format_choice_apt_package_is_installed (const char *package);

BzFormatChoice *
bz_format_choice_new (void);

BzFormatChoice *
bz_format_choice_ref (BzFormatChoice *self);

void
bz_format_choice_unref (BzFormatChoice *self);

G_DEFINE_AUTOPTR_CLEANUP_FUNC (BzFormatChoice, bz_format_choice_unref)

BzFormatChoiceFormat
bz_format_choice_get_pick (BzFormatChoice *self);

const char *
bz_format_choice_get_reason (BzFormatChoice *self);

gboolean
bz_format_choice_get_overridden (BzFormatChoice *self);

/*
 * The one line describing one format, as shown on the app page. NULL when
 * that format has no line at all.
 */
const char *
bz_format_choice_get_line (BzFormatChoice *self,
                           BzFormatChoiceFormat format);

/*
 * "Installed as Flatpak" when one of this application's builds is already
 * installed, and NULL when none is. The app page shows this in the
 * "Recommended for you" card and recommends nothing new.
 */
const char *
bz_format_choice_get_installed_note (BzFormatChoice *self);

/*
 * The winning build's version (NULL when not known yet) and download size in
 * bytes (0 when not known), for the card under the format badge.
 */
const char *
bz_format_choice_get_pick_version (BzFormatChoice *self);

gint64
bz_format_choice_get_pick_size (BzFormatChoice *self);

/*
 * Score the three builds and return the winner, in this order of weight:
 *
 * curated advice for this app 100 (more than every other signal combined),
 * already installed 50, the newest known version 20 (ignoring a difference
 * only in a packaging suffix), an older known version 5, sandboxing 15 when
 * the versions are equal, and the smallest known download 1, last. A build
 * that is not available is never scored. Ties go to the sandboxed build
 * first, then AppImage, then apt. The reason is the curated sentence when
 * the curated pick wins, otherwise a sentence about the reason this build
 * scored best.
 *
 * `offers` may be NULL, which means nothing is known about any build.
 */
BzFormatChoice *
bz_format_choice_evaluate (const char *app_id,
                           const BzFormatChoiceOffer *offers,
                           const char *override,
                           GError    **error);

G_END_DECLS
