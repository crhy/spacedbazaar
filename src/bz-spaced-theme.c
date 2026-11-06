/* Follow the host palette without exposing the rest of its configuration. */
#include <adwaita.h>
#include <string.h>

#include "bz-spaced-theme.h"

typedef struct
{
  GtkCssProvider *provider;
  GdkDisplay    *display;
  GFileMonitor  *monitor;
  char          *directory;
  char          *watch_path;
  char          *path;
} SpacedTheme;

static gboolean watch_palette (SpacedTheme *theme);
static void clear_monitor (SpacedTheme *theme);

static void
reload_palette (SpacedTheme *theme)
{
  g_autofree char *css = NULL;
  AdwColorScheme scheme = ADW_COLOR_SCHEME_DEFAULT;

  if (g_file_get_contents (theme->path, &css, NULL, NULL) &&
      g_str_has_prefix (css, "/* spaced-theme: "))
    {
      /* The scheme and colours share one atomic file, so rapid switches
       * cannot combine the previous theme's dark flag with new colours. */
      char *end = strstr (css, " */");
      if (end && end - css >= 7 && strncmp (end - 7, " dark=1", 7) == 0)
        scheme = ADW_COLOR_SCHEME_FORCE_DARK;
      else if (end && end - css >= 7 && strncmp (end - 7, " dark=0", 7) == 0)
        scheme = ADW_COLOR_SCHEME_FORCE_LIGHT;
      else
        g_clear_pointer (&css, g_free);
    }
  else
    g_clear_pointer (&css, g_free);

  adw_style_manager_set_color_scheme (adw_style_manager_get_default (), scheme);
  gtk_css_provider_load_from_string (theme->provider, css ? css : "");
}

static void
palette_changed (GFileMonitor      *monitor,
                 GFile             *file,
                 GFile             *other_file,
                 GFileMonitorEvent  event,
                 gpointer           user_data)
{
  SpacedTheme *theme = user_data;
  g_autofree char *name = g_file_get_basename (file);
  g_autofree char *other = other_file ? g_file_get_basename (other_file) : NULL;
  g_autofree char *path = g_file_get_path (file);

  /* A deleted directory may already have been recreated at the same path. */
  if (g_strcmp0 (path, theme->watch_path) == 0 &&
      (event == G_FILE_MONITOR_EVENT_DELETED ||
       event == G_FILE_MONITOR_EVENT_RENAMED ||
       event == G_FILE_MONITOR_EVENT_MOVED_OUT ||
       event == G_FILE_MONITOR_EVENT_UNMOUNTED))
    clear_monitor (theme);

  if (watch_palette (theme) ||
      g_strcmp0 (name, "libadwaita.css") == 0 ||
      g_strcmp0 (other, "libadwaita.css") == 0)
    reload_palette (theme);
}

static void
clear_monitor (SpacedTheme *theme)
{
  if (theme->monitor)
    {
      g_signal_handlers_disconnect_by_data (theme->monitor, theme);
      g_file_monitor_cancel (theme->monitor);
      g_clear_object (&theme->monitor);
    }
}

static gboolean
watch_palette (SpacedTheme *theme)
{
  g_autofree char *directory = g_strdup (theme->directory);
  g_autoptr (GFile) file = NULL;
  g_autoptr (GFileMonitor) monitor = NULL;

  /* A first launch can precede palette generation. Watch the nearest existing
   * parent until the palette directory appears; no polling or idle wakeups. */
  while (!g_file_test (directory, G_FILE_TEST_IS_DIR))
    {
      char *parent = g_path_get_dirname (directory);
      if (g_strcmp0 (parent, directory) == 0)
        {
          g_free (parent);
          return FALSE;
        }
      g_free (directory);
      directory = parent;
    }
  if (theme->monitor && g_strcmp0 (directory, theme->watch_path) == 0)
    return FALSE;

  file = g_file_new_for_path (directory);
  monitor = g_file_monitor_directory (file, G_FILE_MONITOR_WATCH_MOVES, NULL, NULL);
  if (!monitor)
    return FALSE;
  clear_monitor (theme);
  theme->monitor = g_steal_pointer (&monitor);
  g_free (theme->watch_path);
  theme->watch_path = g_steal_pointer (&directory);
  g_signal_connect (theme->monitor, "changed", G_CALLBACK (palette_changed), theme);
  return TRUE;
}

static void
theme_free (gpointer data)
{
  SpacedTheme *theme = data;

  clear_monitor (theme);
  if (theme->display)
    gtk_style_context_remove_provider_for_display (
        theme->display, GTK_STYLE_PROVIDER (theme->provider));
  g_clear_object (&theme->display);
  g_clear_object (&theme->provider);
  g_free (theme->directory);
  g_free (theme->watch_path);
  g_free (theme->path);
  g_free (theme);
}

GObject *
bz_spaced_theme_new (void)
{
  GObject *owner = g_object_new (G_TYPE_OBJECT, NULL);
  SpacedTheme *theme = g_new0 (SpacedTheme, 1);
  const char *config = g_get_user_config_dir ();
  g_autofree char *fallback = NULL;
  GdkDisplay *display = gdk_display_get_default ();

  g_object_set_data_full (owner, "spaced-theme", theme, theme_free);
  if (g_file_test ("/.flatpak-info", G_FILE_TEST_EXISTS))
    {
      config = g_getenv ("HOST_XDG_CONFIG_HOME");
      if (!config || !g_path_is_absolute (config))
        {
          fallback = g_build_filename (g_get_home_dir (), ".config", NULL);
          config = fallback;
        }
    }
  theme->directory = g_build_filename (config, "spaced", NULL);
  theme->path = g_build_filename (theme->directory, "libadwaita.css", NULL);
  theme->provider = gtk_css_provider_new ();
  if (display)
    {
      theme->display = g_object_ref (display);
      gtk_style_context_add_provider_for_display (
          display, GTK_STYLE_PROVIDER (theme->provider),
          GTK_STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
    }
  /* Watch the directory, not the inode replaced by the atomic writer. */
  watch_palette (theme);
  reload_palette (theme);
  return owner;
}
