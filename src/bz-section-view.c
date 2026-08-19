/* bz-section-view.c
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

#include <bge.h>

#include "bz-application.h"
#include "bz-apps-page.h"
#include "bz-curated-section.h"
#include "bz-dynamic-list-view.h"
#include "bz-entry-group.h"
#include "bz-rich-app-tile.h"
#include "bz-section-view.h"
#include "bz-window.h"

struct _BzSectionView
{
  AdwBin parent_instance;

  BzCuratedSection *section;

  /* Template widgets */
  BgeMarkdownRender *subtitle;
};

G_DEFINE_FINAL_TYPE (BzSectionView, bz_section_view, ADW_TYPE_BIN)

enum
{
  PROP_0,

  PROP_SECTION,

  LAST_PROP
};
static GParamSpec *props[LAST_PROP] = { 0 };

static void
bz_section_view_dispose (GObject *object)
{
  BzSectionView *self = BZ_SECTION_VIEW (object);

  g_clear_object (&self->section);

  G_OBJECT_CLASS (bz_section_view_parent_class)->dispose (object);
}

static void
bz_section_view_get_property (GObject    *object,
                              guint       prop_id,
                              GValue     *value,
                              GParamSpec *pspec)
{
  BzSectionView *self = BZ_SECTION_VIEW (object);

  switch (prop_id)
    {
    case PROP_SECTION:
      g_value_set_object (value, bz_section_view_get_section (self));
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
bz_section_view_set_property (GObject      *object,
                              guint         prop_id,
                              const GValue *value,
                              GParamSpec   *pspec)
{
  BzSectionView *self = BZ_SECTION_VIEW (object);

  switch (prop_id)
    {
    case PROP_SECTION:
      bz_section_view_set_section (self, g_value_get_object (value));
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static gboolean
invert_boolean (gpointer object,
                gboolean value)
{
  return !value;
}

static gboolean
is_null (gpointer object,
         GObject *value)
{
  return value == NULL;
}

static gboolean
is_null_string (gpointer    object,
                const char *value)
{
  return value == NULL;
}

static char *
get_child_type (gpointer    object,
                const char *list_type)
{
  if (list_type != NULL && g_strcmp0 (list_type, "rich") == 0)
    return g_strdup ("BzRichAppTile");
  return g_strdup ("BzAppTile");
}

static guint
get_slice_length (gpointer object,
                  guint    overflow_count,
                  gboolean install_all_visible)
{
  if (overflow_count == 0 || install_all_visible)
    return 20;

  return MIN (overflow_count, 20);
}

static gboolean
show_more_visible (gpointer    object,
                   gboolean    enable_bulk_install,
                   GListModel *full_model,
                   guint       overflow_count)
{
  if (enable_bulk_install || full_model == NULL)
    return FALSE;

  return g_list_model_get_n_items (full_model) >
         (overflow_count == 0 ? 20 : MIN (overflow_count, 20));
}

static GListModel *
convert_to_groups (gpointer    object,
                   GListModel *value)
{
  BzStateInfo             *info    = NULL;
  BzApplicationMapFactory *factory = NULL;

  info    = bz_state_info_get_default ();
  factory = bz_state_info_get_application_factory (info);

  return bz_application_map_factory_generate (factory, value);
}

static void
install_all_clicked (BzSectionView *self,
                     GtkButton     *button)
{
  GtkWidget               *window   = NULL;
  BzCuratedAppidsInfo     *appids   = NULL;
  GListModel              *list     = NULL;
  guint                    n_appids = 0;
  BzStateInfo             *info     = NULL;
  BzApplicationMapFactory *factory  = NULL;
  g_autoptr (GListModel) groups     = NULL;

  window = gtk_widget_get_ancestor (GTK_WIDGET (self), BZ_TYPE_WINDOW);
  if (window == NULL)
    return;

  /* If the button is visible and the user clicked it, this must be non-null */
  appids = bz_curated_section_get_appids (self->section);
  list   = bz_curated_appids_info_get_list (appids);
  if (list == NULL)
    return;
  n_appids = g_list_model_get_n_items (list);
  if (n_appids == 0)
    return;

  /* TODO: bind state via object properties */
  info    = bz_state_info_get_default ();
  factory = bz_state_info_get_application_factory (info);

  groups = bz_application_map_factory_generate (factory, list);
  /* TODO: use signals to chain up the blueprints; it is cleaner, but more
     work... :( */
  bz_window_bulk_install (BZ_WINDOW (window), groups);
}

static void
show_more_clicked (BzSectionView *self,
                   GtkButton     *button)
{
  BzCuratedAppidsInfo *appids        = NULL;
  GListModel          *list          = NULL;
  g_autoptr (GListModel) groups      = NULL;
  BzStateInfo             *info      = NULL;
  BzApplicationMapFactory *factory   = NULL;
  AdwNavigationPage       *apps_page = NULL;
  GtkWidget               *nav_view  = NULL;
  const char              *title     = NULL;

  if (self->section == NULL)
    return;

  appids = bz_curated_section_get_appids (self->section);
  list   = bz_curated_appids_info_get_list (appids);
  if (list == NULL)
    return;

  info    = bz_state_info_get_default ();
  factory = bz_state_info_get_application_factory (info);
  groups  = bz_application_map_factory_generate (factory, list);

  title     = bz_curated_section_get_title (self->section);
  apps_page = bz_apps_page_new (title, groups);

  nav_view = gtk_widget_get_ancestor (GTK_WIDGET (self), ADW_TYPE_NAVIGATION_VIEW);
  if (nav_view != NULL)
    adw_navigation_view_push (ADW_NAVIGATION_VIEW (nav_view), apps_page);
}

static void
bz_section_view_class_init (BzSectionViewClass *klass)
{
  GObjectClass   *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->dispose      = bz_section_view_dispose;
  object_class->get_property = bz_section_view_get_property;
  object_class->set_property = bz_section_view_set_property;

  props[PROP_SECTION] =
      g_param_spec_object (
          "section",
          NULL, NULL,
          BZ_TYPE_CURATED_SECTION,
          G_PARAM_READWRITE | G_PARAM_EXPLICIT_NOTIFY | G_PARAM_STATIC_STRINGS);

  g_object_class_install_properties (object_class, LAST_PROP, props);

  g_type_ensure (BZ_TYPE_DYNAMIC_LIST_VIEW);

  gtk_widget_class_set_template_from_resource (widget_class, "/io/github/crhy/SpacedBazaar/bz-section-view.ui");
  gtk_widget_class_bind_template_child (widget_class, BzSectionView, subtitle);
  gtk_widget_class_bind_template_callback (widget_class, invert_boolean);
  gtk_widget_class_bind_template_callback (widget_class, is_null);
  gtk_widget_class_bind_template_callback (widget_class, is_null_string);
  gtk_widget_class_bind_template_callback (widget_class, get_child_type);
  gtk_widget_class_bind_template_callback (widget_class, convert_to_groups);
  gtk_widget_class_bind_template_callback (widget_class, install_all_clicked);
  gtk_widget_class_bind_template_callback (widget_class, show_more_clicked);
  gtk_widget_class_bind_template_callback (widget_class, get_slice_length);
  gtk_widget_class_bind_template_callback (widget_class, show_more_visible);
}

static void
bz_section_view_init (BzSectionView *self)
{
  gtk_widget_init_template (GTK_WIDGET (self));
}

GtkWidget *
bz_section_view_new (BzCuratedSection *section)
{
  return g_object_new (
      BZ_TYPE_SECTION_VIEW,
      "section", section,
      NULL);
}

void
bz_section_view_set_section (BzSectionView    *self,
                             BzCuratedSection *section)
{
  g_return_if_fail (BZ_IS_SECTION_VIEW (self));
  g_return_if_fail (section == NULL || BZ_IS_CURATED_SECTION (section));

  g_clear_object (&self->section);

  if (section != NULL)
    self->section = g_object_ref (section);

  g_object_notify_by_pspec (G_OBJECT (self), props[PROP_SECTION]);
}

BzCuratedSection *
bz_section_view_get_section (BzSectionView *self)
{
  g_return_val_if_fail (BZ_IS_SECTION_VIEW (self), NULL);
  return self->section;
}
