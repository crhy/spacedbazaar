/* bz-flathub-curated-section.c
 *
 * Copyright 2026 Alexander Vanhee
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

#include "bz-dynamic-list-view.h"
#include "bz-flathub-curated-section.h"

struct _BzFlathubCuratedSection
{
  AdwBin parent_instance;

  BzFlathubCuratedSelection *selection;
  GListModel                *model;
  GtkSliceListModel         *slice_model;
  guint                      max_length;
  char                      *applied_css_class;

  GtkWidget         *root_box;
  GtkLabel          *title_label;
  GtkLabel          *subtitle_label;
  BzDynamicListView *list;
};

G_DEFINE_FINAL_TYPE (BzFlathubCuratedSection, bz_flathub_curated_section, ADW_TYPE_BIN)

enum
{
  PROP_0,

  PROP_SELECTION,
  PROP_MAX_LENGTH,

  LAST_PROP
};
static GParamSpec *props[LAST_PROP] = { 0 };

typedef struct
{
  const char *theme_key;
  const char *title;
  const char *subtitle;
} ThemeInfo;

static const ThemeInfo theme_info[] = {
  {  "new-year-new-workflows",  N_ ("New Year, New Workflows"),                N_ ("Apps to take notes, track tasks, and make plans") },
  { "free-software-favorites",              N_ ("Staff Picks"),                                         N_ ("Apps we love right now") },
  {       "spring-creativity",             N_ ("Get Creative"), N_ ("Essential apps for drawing, editing photos, and digital design") },
  {  "fresh-desktop-releases",        N_ ("Build Native Apps"),                  N_ ("Develop apps that feel at home on your system") },
  {       "staying-connected",            N_ ("Stay in Touch"),                 N_ ("Essential collaboration and communication apps") },
  {           "summer-travel",      N_ ("Ready for Vacations"),                 N_ ("Maps, transit, weather, and trip planning apps") },
  {        "back-to-learning",        N_ ("Smarter Every Day"),                    N_ ("Apps to help you study, research, and write") },
  {         "winter-comforts",                 N_ ("Get Cozy"),     N_ ("Great apps for reading, watching movies, and playing games") },
  {    "tools-for-developers", N_ ("Web Developer Essentials"),                    N_ ("Making websites is more fun with these apps") },
  {       "take-better-notes",        N_ ("Take Better Notes"),                        N_ ("Find your new favorite note taking tool") },
  {             "get-focused",              N_ ("Get Focused"),                                 N_ ("Great apps for task management") },
  {         "make-some-noise",          N_ ("Make Some Noise"),                          N_ ("Apps for creating and producing music") },
  {             "get-to-work",              N_ ("Get To Work"),                                          N_ ("Essential office apps") },
  {                      NULL,                            NULL,                                                                  NULL }
};

static const ThemeInfo *
get_theme_info (const char *theme_key);

static void
bz_flathub_curated_section_dispose (GObject *object)
{
  BzFlathubCuratedSection *self = BZ_FLATHUB_CURATED_SECTION (object);

  g_clear_object (&self->selection);
  g_clear_object (&self->model);
  g_clear_object (&self->slice_model);
  g_clear_pointer (&self->applied_css_class, g_free);

  G_OBJECT_CLASS (bz_flathub_curated_section_parent_class)->dispose (object);
}

static void
bz_flathub_curated_section_get_property (GObject    *object,
                                         guint       prop_id,
                                         GValue     *value,
                                         GParamSpec *pspec)
{
  BzFlathubCuratedSection *self = BZ_FLATHUB_CURATED_SECTION (object);

  switch (prop_id)
    {
    case PROP_SELECTION:
      g_value_set_object (value, bz_flathub_curated_section_get_selection (self));
      break;
    case PROP_MAX_LENGTH:
      g_value_set_uint (value, self->max_length);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
bz_flathub_curated_section_set_property (GObject      *object,
                                         guint         prop_id,
                                         const GValue *value,
                                         GParamSpec   *pspec)
{
  BzFlathubCuratedSection *self = BZ_FLATHUB_CURATED_SECTION (object);

  switch (prop_id)
    {
    case PROP_SELECTION:
      bz_flathub_curated_section_set_selection (self, g_value_get_object (value));
      break;
    case PROP_MAX_LENGTH:
      bz_flathub_curated_section_set_max_length (self, g_value_get_uint (value));
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
bz_flathub_curated_section_class_init (BzFlathubCuratedSectionClass *klass)
{
  GObjectClass   *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->dispose      = bz_flathub_curated_section_dispose;
  object_class->get_property = bz_flathub_curated_section_get_property;
  object_class->set_property = bz_flathub_curated_section_set_property;

  props[PROP_SELECTION] =
      g_param_spec_object (
          "selection",
          NULL, NULL,
          BZ_TYPE_FLATHUB_CURATED_SELECTION,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS | G_PARAM_EXPLICIT_NOTIFY);

  props[PROP_MAX_LENGTH] =
      g_param_spec_uint (
          "max-length",
          NULL, NULL,
          0, G_MAXUINT, 8,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS | G_PARAM_EXPLICIT_NOTIFY);

  g_object_class_install_properties (object_class, LAST_PROP, props);

  g_type_ensure (BZ_TYPE_DYNAMIC_LIST_VIEW);

  gtk_widget_class_set_template_from_resource (widget_class, "/io/github/crhy/SpacedBazaar/bz-flathub-curated-section.ui");
  gtk_widget_class_bind_template_child (widget_class, BzFlathubCuratedSection, root_box);
  gtk_widget_class_bind_template_child (widget_class, BzFlathubCuratedSection, title_label);
  gtk_widget_class_bind_template_child (widget_class, BzFlathubCuratedSection, subtitle_label);
  gtk_widget_class_bind_template_child (widget_class, BzFlathubCuratedSection, list);
}

static void
bz_flathub_curated_section_init (BzFlathubCuratedSection *self)
{
  self->max_length = 8;

  gtk_widget_init_template (GTK_WIDGET (self));
}

GtkWidget *
bz_flathub_curated_section_new (void)
{
  return g_object_new (BZ_TYPE_FLATHUB_CURATED_SECTION, NULL);
}

void
bz_flathub_curated_section_set_selection (BzFlathubCuratedSection   *self,
                                          BzFlathubCuratedSelection *selection)
{
  const char       *theme_key = NULL;
  const char       *slot      = NULL;
  const ThemeInfo *info      = NULL;

  g_return_if_fail (BZ_IS_FLATHUB_CURATED_SECTION (self));
  g_return_if_fail (selection == NULL || BZ_IS_FLATHUB_CURATED_SELECTION (selection));

  g_set_object (&self->selection, selection);

  g_clear_object (&self->slice_model);
  g_clear_object (&self->model);

  if (self->selection != NULL)
    {
      GtkStringList           *apps        = NULL;
      BzApplicationMapFactory *map_factory = NULL;

      theme_key   = bz_flathub_curated_selection_get_theme_key (self->selection);
      slot        = bz_flathub_curated_selection_get_slot (self->selection);
      apps        = bz_flathub_curated_selection_get_apps (self->selection);
      map_factory = bz_flathub_curated_selection_get_map_factory (self->selection);

      if (apps != NULL && map_factory != NULL)
        self->model = bz_application_map_factory_generate (
            map_factory, G_LIST_MODEL (apps));
    }

  if (self->model != NULL)
    self->slice_model = gtk_slice_list_model_new (
        g_object_ref (self->model), 0, self->max_length);

  info = get_theme_info (theme_key);

  if (info != NULL)
    {
      gtk_label_set_label (self->title_label, _ (info->title));
      gtk_label_set_label (self->subtitle_label, _ (info->subtitle));
      gtk_widget_set_visible (GTK_WIDGET (self->title_label), TRUE);
      gtk_widget_set_visible (GTK_WIDGET (self->subtitle_label), TRUE);
    }
  else
    {
      gtk_widget_set_visible (GTK_WIDGET (self->title_label), FALSE);
      gtk_widget_set_visible (GTK_WIDGET (self->subtitle_label), FALSE);
    }

  if (self->applied_css_class != NULL)
    {
      gtk_widget_remove_css_class (self->root_box, self->applied_css_class);
      g_clear_pointer (&self->applied_css_class, g_free);
    }

  if (slot != NULL)
    {
      self->applied_css_class = g_strdup (slot);
      gtk_widget_add_css_class (self->root_box, self->applied_css_class);
    }

  bz_dynamic_list_view_set_model (
      self->list,
      self->slice_model != NULL ? G_LIST_MODEL (self->slice_model) : NULL);

  g_object_notify_by_pspec (G_OBJECT (self), props[PROP_SELECTION]);
}

BzFlathubCuratedSelection *
bz_flathub_curated_section_get_selection (BzFlathubCuratedSection *self)
{
  g_return_val_if_fail (BZ_IS_FLATHUB_CURATED_SECTION (self), NULL);
  return self->selection;
}

void
bz_flathub_curated_section_set_max_length (BzFlathubCuratedSection *self,
                                           guint                    max_length)
{
  g_return_if_fail (BZ_IS_FLATHUB_CURATED_SECTION (self));

  if (self->max_length == max_length)
    return;

  self->max_length = max_length;

  if (self->slice_model != NULL)
    gtk_slice_list_model_set_size (self->slice_model, max_length);

  g_object_notify_by_pspec (G_OBJECT (self), props[PROP_MAX_LENGTH]);
}

static const ThemeInfo *
get_theme_info (const char *theme_key)
{
  int i = 0;

  if (theme_key == NULL)
    return NULL;

  for (i = 0; theme_info[i].theme_key != NULL; i++)
    {
      if (g_strcmp0 (theme_info[i].theme_key, theme_key) == 0)
        return &theme_info[i];
    }

  return NULL;
}

/* End of bz-flathub-curated-section.c */
