/* main.c
 *
 * Copyright 2025 Adam Masciola
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

#define G_LOG_DOMAIN "BAZAAR::MAIN"

#include "config.h"

#include <bge.h>
#include <glib/gi18n.h>
#include <libdex.h>

#include "bz-application.h"
#include "refresh-worker.h"
#include "update-worker.h"

int
main (int   argc,
      char *argv[])
{
  int result = 0;

  if (argc > 1 && g_strcmp0 (argv[1], "--version") == 0)
    {
      g_print ("%s\n", PACKAGE_VCS_VERSION);
      return 0;
    }

  /* In the Flatpak, libflatpak writes a remote's summary to a temporary file
   * and asks the system helper, outside the sandbox, to read it.  The
   * sandbox's /tmp is private, so every system remote whose metadata had
   * changed failed to update ("Failed to open file /tmp/remote-summary..."),
   * and its AppStream data was never refreshed again.  The per-app runtime
   * directory is shared with the host at the same path. */
  if (g_getenv ("FLATPAK_ID") != NULL)
    {
      g_autofree char *shared_tmp = g_build_filename (
          g_get_user_runtime_dir (), "app", g_getenv ("FLATPAK_ID"), NULL);

      if (g_file_test (shared_tmp, G_FILE_TEST_IS_DIR))
        g_setenv ("TMPDIR", shared_tmp, TRUE);
    }

  dex_init ();

  bindtextdomain (GETTEXT_PACKAGE, LOCALEDIR);
  bind_textdomain_codeset (GETTEXT_PACKAGE, "UTF-8");
  textdomain (GETTEXT_PACKAGE);

  /* Init Bazaar GTK Extensions */
  bge_init ();

  if (argc > 1 && g_strcmp0 (argv[1], REFRESH_WORKER_CLI_OPTION) == 0)
    result = run_refresh_worker (argc, argv);
  else if (argc > 1 && g_strcmp0 (argv[1], UPDATE_WORKER_CLI_OPTION) == 0)
    result = run_update_worker (argc, argv);
  else
    {
      g_autoptr (BzApplication) app = NULL;

      app = g_object_new (
          BZ_TYPE_APPLICATION,
          "application-id", APPLICATION_ID,
          "flags", G_APPLICATION_HANDLES_COMMAND_LINE,
          "resource-base-path", "/io/github/crhy/SpacedBazaar",
          NULL);
      result = g_application_run (G_APPLICATION (app), argc, argv);
    }

  return result;
}
