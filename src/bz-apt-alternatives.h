/* bz-apt-alternatives.h
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
 * An app that SpacedBazaar can install from a Flatpak remote but that also
 * exists as an apt package on Spaced Linux, together with the one-line
 * reason the apt build is worth preferring for that particular app.
 *
 * Only apps where the apt build genuinely does something the Flatpak build
 * cannot are listed; see bz_apt_alternative_lookup for the table.
 */
typedef struct
{
  const char *app_id;
  const char *package;
  const char *reason;
} BzAptAlternative;

/*
 * Look up the apt alternative for a Flatpak app id.
 *
 * When found, `package` and `reason` receive newly allocated copies (the
 * reason is translated); when there is no alternative for `app_id` nothing
 * is written and FALSE is returned. Either out-parameter may be NULL.
 *
 * Bazaar never runs apt: this only tells the user that the package exists
 * and the exact command they can run themselves.
 */
gboolean
bz_apt_alternative_lookup (const char *app_id,
                           char      **package,
                           char     **reason);

G_END_DECLS
