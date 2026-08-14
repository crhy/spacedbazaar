/* bz-preferences-dialog.c
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

#include "bz-preferences-dialog.h"

#include <gio/gio.h>
#include <glib/gi18n.h>
#include <libdex.h>

#include "env.h"
#include "template-callbacks.h"
#include "util.h"

#define AUTOSTART_DESKTOP_FILE_NAME     "bazaar.desktop"
#define AUTOSTART_DESKTOP_RESOURCE_PATH "/io/github/kolunmi/Bazaar/bazaar.desktop"


struct _BzPreferencesDialog
{
  AdwPreferencesDialog parent_instance;

  BzStateInfo *state;
  GSettings   *settings;

  /* Template widgets */
  GtkCheckButton *automatic_updates_check;
  AdwSwitchRow   *auto_notif_switch;
  AdwSwitchRow   *only_foss_switch;
  AdwSwitchRow   *only_flathub_switch;
  AdwSwitchRow   *only_verified_switch;
  AdwSwitchRow   *hide_eol_switch;

};

G_DEFINE_FINAL_TYPE (BzPreferencesDialog, bz_preferences_dialog, ADW_TYPE_PREFERENCES_DIALOG)

enum
{
  PROP_0,

  PROP_STATE,

  LAST_PROP
};
static GParamSpec *props[LAST_PROP] = { 0 };

static void bind_settings (BzPreferencesDialog *self);
static void request_autostart (gboolean enable);

static DexFuture *
request_autostart_fiber (gpointer user_data);

static void
bz_preferences_dialog_dispose (GObject *object)
{
  BzPreferencesDialog *self = BZ_PREFERENCES_DIALOG (object);

  g_clear_object (&self->state);
  g_clear_object (&self->settings);

  G_OBJECT_CLASS (bz_preferences_dialog_parent_class)->dispose (object);
}




static void
bind_settings (BzPreferencesDialog *self)
{
  if (self->settings == NULL)
    return;

  /* Bind all boolean settings to their respective switches */
  g_settings_bind (self->settings, "show-only-foss",
                   self->only_foss_switch, "active",
                   G_SETTINGS_BIND_DEFAULT);

  g_settings_bind (self->settings, "show-only-flathub",
                   self->only_flathub_switch, "active",
                   G_SETTINGS_BIND_DEFAULT);

  g_settings_bind (self->settings, "show-only-verified",
                   self->only_verified_switch, "active",
                   G_SETTINGS_BIND_DEFAULT);

  g_settings_bind (self->settings, "hide-eol",
                   self->hide_eol_switch, "active",
                   G_SETTINGS_BIND_DEFAULT);

  g_settings_bind (self->settings, "auto-update",
                   self->automatic_updates_check, "active",
                   G_SETTINGS_BIND_DEFAULT);

  g_settings_bind (self->settings, "auto-update-notifications",
                   self->auto_notif_switch, "active",
                   G_SETTINGS_BIND_DEFAULT);

}

static void
bz_preferences_dialog_get_property (GObject    *object,
                                    guint       prop_id,
                                    GValue     *value,
                                    GParamSpec *pspec)
{
  BzPreferencesDialog *self = BZ_PREFERENCES_DIALOG (object);

  switch (prop_id)
    {
    case PROP_STATE:
      g_value_set_object (value, self->state);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
bz_preferences_dialog_set_property (GObject      *object,
                                    guint         prop_id,
                                    const GValue *value,
                                    GParamSpec   *pspec)
{
  switch (prop_id)
    {
    case PROP_STATE:
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static DexFuture *
request_autostart_fiber (gpointer user_data)
{
  gboolean enable = GPOINTER_TO_INT (user_data);

#ifdef SANDBOXED_LIBFLATPAK
  g_autoptr (GDBusConnection) bus = NULL;
  g_autoptr (GError) local_error  = NULL;
  g_autoptr (GVariant) reply      = NULL;
  g_autofree char *token          = NULL;
  GVariant        *options        = NULL;
  static guint     request_count  = 0;

  bus = dex_await_object (dex_bus_get (G_BUS_TYPE_SESSION), &local_error);
  if (bus == NULL)
    {
      g_warning ("Could not connect to session bus: %s", local_error->message);
      return dex_future_new_for_error (g_steal_pointer (&local_error));
    }

  token = g_strdup_printf ("bazaar_autostart_%u", request_count++);

  options = g_variant_new_parsed (
      "{'handle_token': <%s>, 'reason': <%s>, "
      "'autostart': <%b>, 'dbus-activatable': <false>, "
      "'commandline': <['bazaar-daemon', '--no-window']>}",
      token,
      _ ("Bazaar needs to run in the background to check for app updates"),
      enable);

  reply = dex_await_variant (
      dex_dbus_connection_call (
          bus, "org.freedesktop.portal.Desktop",
          "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Background",
          "RequestBackground", g_variant_new ("(s@a{sv})", "", options), NULL,
          G_DBUS_CALL_FLAGS_NONE, -1),
      &local_error);
  if (reply == NULL)
    {
      g_warning ("Failed to call RequestBackground: %s", local_error->message);
      return dex_future_new_for_error (g_steal_pointer (&local_error));
    }

  return dex_future_new_true ();
#else
  g_autoptr (GError) local_error = NULL;
  g_autofree char *autostart_dir = NULL;
  g_autofree char *dest_path     = NULL;
  g_autoptr (GFile) dir          = NULL;
  g_autoptr (GFile) dst          = NULL;

  autostart_dir = g_build_filename (g_get_user_config_dir (), "autostart", NULL);
  dest_path     = g_build_filename (autostart_dir, AUTOSTART_DESKTOP_FILE_NAME, NULL);

  dir = g_file_new_for_path (autostart_dir);
  dst = g_file_new_for_path (dest_path);

  if (!dex_await (dex_file_make_directory_with_parents (dir), &local_error) &&
      !g_error_matches (local_error, G_IO_ERROR, G_IO_ERROR_EXISTS))
    {
      g_warning ("Could not create autostart dir: %s", local_error->message);
      return dex_future_new_for_error (g_steal_pointer (&local_error));
    }
  g_clear_error (&local_error);
  if (enable)
    {
      g_autoptr (GFile) src = NULL;

      src = g_file_new_for_uri ("resource://" AUTOSTART_DESKTOP_RESOURCE_PATH);
      if (!dex_await (dex_file_copy (src, dst, G_FILE_COPY_OVERWRITE, G_PRIORITY_DEFAULT), &local_error))
        {
          g_warning ("Failed to install autostart file: %s", local_error->message);
          return dex_future_new_for_error (g_steal_pointer (&local_error));
        }
    }
  else
    {
      if (!dex_await (dex_file_delete (dst, G_PRIORITY_DEFAULT), &local_error) &&
          !g_error_matches (local_error, G_IO_ERROR, G_IO_ERROR_NOT_FOUND))
        {
          g_warning ("Failed to remove autostart file: %s", local_error->message);
          return dex_future_new_for_error (g_steal_pointer (&local_error));
        }
    }

  return dex_future_new_true ();
#endif
}

static void
request_autostart (gboolean enable)
{
  dex_future_disown (
      dex_scheduler_spawn (
          dex_scheduler_get_default (),
          bz_get_dex_stack_size (),
          request_autostart_fiber,
          GINT_TO_POINTER (enable),
          NULL));
}

static void
auto_updates_toggled_cb (GtkCheckButton      *button,
                         BzPreferencesDialog *self)
{
  request_autostart (gtk_check_button_get_active (self->automatic_updates_check));
}

static void
bz_preferences_dialog_class_init (BzPreferencesDialogClass *klass)
{
  GObjectClass   *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->set_property = bz_preferences_dialog_set_property;
  object_class->get_property = bz_preferences_dialog_get_property;
  object_class->dispose      = bz_preferences_dialog_dispose;

  props[PROP_STATE] =
      g_param_spec_object (
          "state",
          NULL, NULL,
          BZ_TYPE_STATE_INFO,
          G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  g_object_class_install_properties (object_class, LAST_PROP, props);

  gtk_widget_class_set_template_from_resource (widget_class, "/io/github/kolunmi/Bazaar/bz-preferences-dialog.ui");

  bz_widget_class_bind_all_util_callbacks (widget_class);

  gtk_widget_class_bind_template_child (widget_class, BzPreferencesDialog, only_foss_switch);
  gtk_widget_class_bind_template_child (widget_class, BzPreferencesDialog, only_flathub_switch);
  gtk_widget_class_bind_template_child (widget_class, BzPreferencesDialog, only_verified_switch);
  gtk_widget_class_bind_template_child (widget_class, BzPreferencesDialog, hide_eol_switch);
  gtk_widget_class_bind_template_child (widget_class, BzPreferencesDialog, automatic_updates_check);
  gtk_widget_class_bind_template_child (widget_class, BzPreferencesDialog, auto_notif_switch);
  gtk_widget_class_bind_template_callback (widget_class, auto_updates_toggled_cb);
}

static void
bz_preferences_dialog_init (BzPreferencesDialog *self)
{
  gtk_widget_init_template (GTK_WIDGET (self));
}

AdwDialog *
bz_preferences_dialog_new (BzStateInfo *state)
{
  BzPreferencesDialog *dialog = NULL;

  g_return_val_if_fail (BZ_IS_STATE_INFO (state), NULL);

  dialog        = g_object_new (BZ_TYPE_PREFERENCES_DIALOG, NULL);
  dialog->state = g_object_ref (state);
  g_object_get (state, "settings", &dialog->settings, NULL);
  bind_settings (dialog);

  g_object_notify_by_pspec (G_OBJECT (dialog), props[PROP_STATE]);
  return ADW_DIALOG (dialog);
}
