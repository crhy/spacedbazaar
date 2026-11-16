/* bz-apt-alternatives.c
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

#include "config.h"

#include <glib/gi18n.h>

#include "bz-apt-alternatives.h"

/*
 * Apps where the apt build is not merely an alternative but genuinely the
 * better install on Spaced Linux: the app has to reach files, devices or
 * configuration outside the Flatpak sandbox, or the Flatpak re-bundles
 * system libraries and drivers the apt build would share.
 *
 * Everything here is deliberately narrow. An app that merely happens to
 * also exist in apt does not belong in this table; the reason has to be
 * true for that specific app.
 */
static const BzAptAlternative apt_alternatives[] = {
  { "org.bleachbit.BleachBit", "bleachbit",
    N_ ("Cleaning files outside the sandbox is the whole point of this app, and the Flatpak build cannot reach them") },
  { "org.gimp.GIMP", "gimp",
    N_ ("Scripts and extensions you install land in system GIMP folders that the Flatpak build never reads") },
  { "org.inkscape.Inkscape", "inkscape",
    N_ ("Uses the system's fonts, colour profiles and extension scripts that the Flatpak build re-bundles without") },
  { "org.audacityteam.Audacity", "audacity",
    N_ ("Talks to the host's audio devices and needs the system's ALSA and LADSPA plugins to work as expected") },
  { "org.ardour.Ardour", "ardour",
    N_ ("Records through the host's audio interfaces, so it wants the system's drivers rather than a re-bundled set") },
  { "org.videolan.VLC", "vlc",
    N_ ("Plays files and devices outside the sandbox and re-bundles the codecs the system already provides") },
};

gboolean
bz_apt_alternative_lookup (const char *app_id,
                           char      **package,
                           char     **reason)
{
  if (app_id == NULL)
    return FALSE;

  for (gsize i = 0; i < G_N_ELEMENTS (apt_alternatives); i++)
    {
      if (g_strcmp0 (apt_alternatives[i].app_id, app_id) != 0)
        continue;

      if (package != NULL)
        *package = g_strdup (apt_alternatives[i].package);
      if (reason != NULL)
        *reason = g_strdup (_ (apt_alternatives[i].reason));

      return TRUE;
    }

  return FALSE;
}
