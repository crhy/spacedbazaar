#include <adwaita.h>
#include <glib/gstdio.h>
#include "bz-spaced-theme.h"

static void
wait_for_events (void)
{
  gint64 deadline = g_get_monotonic_time () + 500 * G_TIME_SPAN_MILLISECOND;
  while (g_get_monotonic_time () < deadline)
    {
      while (g_main_context_iteration (NULL, FALSE));
      g_usleep (1000);
    }
}

static void
write_palette (const char *path, gboolean dark)
{
  g_autofree char *temporary = g_strconcat (path, ".tmp", NULL);
  g_autofree char *css = g_strdup_printf (
      "/* spaced-theme: Test dark=%d */\n"
      "@define-color window_bg_color %s;\n", dark, dark ? "#123456" : "#abcdef");
  g_assert_true (g_file_set_contents (temporary, css, -1, NULL));
  g_assert_cmpint (g_rename (temporary, path), ==, 0);
  wait_for_events ();
}

static void
assert_palette (gboolean dark)
{
  GdkRGBA actual, expected;
  g_autoptr (GtkWidget) widget = g_object_ref_sink (gtk_label_new ("test"));
  g_assert_cmpint (adw_style_manager_get_color_scheme (adw_style_manager_get_default ()),
                  ==, dark ? ADW_COLOR_SCHEME_FORCE_DARK : ADW_COLOR_SCHEME_FORCE_LIGHT);
  g_assert_true (gtk_style_context_lookup_color (gtk_widget_get_style_context (widget),
                                                "window_bg_color", &actual));
  g_assert_true (gdk_rgba_parse (&expected, dark ? "#123456" : "#abcdef"));
  g_assert_true (gdk_rgba_equal (&actual, &expected));
}

int
main (int argc, char **argv)
{
  g_autofree char *tmp = g_dir_make_tmp ("spaced-bazaar-theme-XXXXXX", NULL);
  g_autofree char *config = g_build_filename (tmp, "config", NULL);
  g_autofree char *directory = g_build_filename (config, "spaced", NULL);
  g_autofree char *path = g_build_filename (directory, "libadwaita.css", NULL);
  g_assert_nonnull (tmp);
  /* Flatpak intentionally uses the HOST path, not its private XDG config. */
  g_setenv ("HOST_XDG_CONFIG_HOME", config, TRUE);
  g_setenv ("XDG_CONFIG_HOME", config, TRUE);
  adw_init ();
  GObject *theme = bz_spaced_theme_new ();
  g_assert_cmpint (adw_style_manager_get_color_scheme (adw_style_manager_get_default ()),
                  ==, ADW_COLOR_SCHEME_DEFAULT);
  /* Both config and spaced can be missing when the consumer starts. */
  g_assert_cmpint (g_mkdir_with_parents (directory, 0700), ==, 0);
  write_palette (path, TRUE);
  assert_palette (TRUE);
  g_object_unref (theme);
  theme = bz_spaced_theme_new ();
  assert_palette (TRUE);
  for (int i = 0; i < 6; i++)
    {
      write_palette (path, i % 2);
      assert_palette (i % 2);
    }
  g_assert_true (g_file_set_contents (path, "invalid CSS without palette metadata", -1, NULL));
  wait_for_events ();
  g_assert_cmpint (adw_style_manager_get_color_scheme (adw_style_manager_get_default ()),
                  ==, ADW_COLOR_SCHEME_DEFAULT);
  write_palette (path, FALSE);
  assert_palette (FALSE);
  g_assert_cmpint (g_unlink (path), ==, 0);
  wait_for_events ();
  g_assert_cmpint (adw_style_manager_get_color_scheme (adw_style_manager_get_default ()),
                  ==, ADW_COLOR_SCHEME_DEFAULT);
  g_assert_cmpint (g_rmdir (directory), ==, 0);
  wait_for_events ();
  g_assert_cmpint (g_mkdir (directory, 0700), ==, 0);
  write_palette (path, TRUE);
  assert_palette (TRUE);
  /* Replacing the whole directory before events dispatch must re-arm its watch. */
  g_assert_cmpint (g_unlink (path), ==, 0);
  g_assert_cmpint (g_rmdir (directory), ==, 0);
  g_assert_cmpint (g_mkdir (directory, 0700), ==, 0);
  write_palette (path, FALSE);
  assert_palette (FALSE);
  write_palette (path, TRUE);
  assert_palette (TRUE);
  g_object_unref (theme);
  /* Pending events must not access the released provider or callback state. */
  write_palette (path, TRUE);
  g_unlink (path);
  g_rmdir (directory);
  g_rmdir (config);
  g_rmdir (tmp);
  g_print ("Spaced palette: missing/recreated directories, atomic switches, colors, invalid/deleted file and cleanup PASS\n");
  return 0;
}
