/* bz-progress-ring.c
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
#include <gtk/gtk.h>
#include <cairo/cairo.h>
#include <math.h>

#include "bz-progress-ring.h"

struct _BzProgressRing
{
  GtkBox parent_instance;

  double fraction;
  double pulse_angle;
  guint  pulse_timeout_id;

  /* Template widgets */
  GtkWidget *ring;
  GtkWidget *label;
};

G_DEFINE_FINAL_TYPE (BzProgressRing, bz_progress_ring, GTK_TYPE_BOX)

enum
{
  PROP_0,

  PROP_FRACTION,

  LAST_PROP
};
static GParamSpec *props[LAST_PROP] = { 0 };

static gboolean
bz_progress_ring_pulse (gpointer user_data);

static void
bz_progress_ring_update_label (BzProgressRing *self);

static void
bz_progress_ring_start_pulse (BzProgressRing *self);

static void
bz_progress_ring_stop_pulse (BzProgressRing *self);

static void
bz_progress_ring_draw (GtkDrawingArea   *area,
                       GdkDrawingContext *context,
                       int                width,
                       int                height,
                       gpointer           data)
{
  BzProgressRing *self = NULL;
  cairo_t        *cr = NULL;
  g_autoptr (GdkRGBA) accent = NULL;
  double line_width = 8.0;
  double cx = 0.0;
  double cy = 0.0;
  double min_size = 0.0;
  double radius = 0.0;
  double fraction = 0.0;
  double start_angle = 0.0;
  double end_angle = 0.0;
  gboolean unknown = FALSE;

  self = BZ_PROGRESS_RING (data);
  cr = cairo_context_get_context (context);
  accent = adw_style_manager_get_accent_color_rgba (adw_style_manager_get_default ());

  cx = width / 2.0;
  cy = height / 2.0;
  min_size = width < height ? width : height;
  radius = (min_size - line_width) / 2.0;
  if (radius < 0.0)
    radius = 0.0;

  cairo_set_line_width (cr, line_width);
  cairo_set_line_cap (cr, CAIRO_LINE_CAP_ROUND);

  cairo_set_source_rgba (cr, accent->red, accent->green, accent->blue, 0.25);
  cairo_new_sub_path (cr);
  cairo_circle (cr, cx, cy, radius);
  cairo_stroke (cr);

  unknown = self->fraction < 0.0;
  if (unknown)
    {
      fraction = 0.25;
      start_angle = self->pulse_angle;
    }
  else
    {
      fraction = CLAMP (self->fraction, 0.0, 1.0);
      start_angle = -M_PI / 2.0;
    }

  if (unknown || fraction > 0.0)
    {
      cairo_set_source_rgba (cr, accent->red, accent->green, accent->blue, 1.0);
      cairo_new_sub_path (cr);

      if (!unknown && fraction >= 1.0)
        {
          cairo_circle (cr, cx, cy, radius);
        }
      else
        {
          end_angle = start_angle + fraction * 2.0 * M_PI;
          cairo_move_to (cr,
                         cx + radius * cos (start_angle),
                         cy + radius * sin (start_angle));
          cairo_arc (cr, cx, cy, radius, start_angle, end_angle);
        }

      cairo_stroke (cr);
    }
}

static gboolean
bz_progress_ring_pulse (gpointer user_data)
{
  BzProgressRing *self = NULL;

  self = BZ_PROGRESS_RING (user_data);
  self->pulse_angle += 0.05;
  if (self->pulse_angle >= 2.0 * M_PI)
    self->pulse_angle -= 2.0 * M_PI;

  gtk_widget_queue_draw (GTK_WIDGET (self));
  return G_SOURCE_CONTINUE;
}

static void
bz_progress_ring_update_label (BzProgressRing *self)
{
  g_autofree gchar *text = NULL;

  if (self->fraction < 0.0)
    text = g_strdup (_ ("…"));
  else
    text = g_strdup_printf ("%d%%",
                            (int) (CLAMP (self->fraction, 0.0, 1.0) * 100.0 + 0.5));

  gtk_label_set_label (GTK_LABEL (self->label), text);
}

static void
bz_progress_ring_start_pulse (BzProgressRing *self)
{
  if (self->pulse_timeout_id == 0)
    self->pulse_timeout_id = g_timeout_add (80, bz_progress_ring_pulse, self);
}

static void
bz_progress_ring_stop_pulse (BzProgressRing *self)
{
  g_clear_handle_id (&self->pulse_timeout_id, g_source_remove);
}

static void
bz_progress_ring_dispose (GObject *object)
{
  BzProgressRing *self = BZ_PROGRESS_RING (object);

  bz_progress_ring_stop_pulse (self);

  G_OBJECT_CLASS (bz_progress_ring_parent_class)->dispose (object);
}

static void
bz_progress_ring_get_property (GObject    *object,
                               guint       prop_id,
                               GValue     *value,
                               GParamSpec *pspec)
{
  BzProgressRing *self = BZ_PROGRESS_RING (object);

  switch (prop_id)
    {
    case PROP_FRACTION:
      g_value_set_double (value, bz_progress_ring_get_fraction (self));
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
bz_progress_ring_set_property (GObject      *object,
                               guint         prop_id,
                               const GValue *value,
                               GParamSpec   *pspec)
{
  BzProgressRing *self = BZ_PROGRESS_RING (object);

  switch (prop_id)
    {
    case PROP_FRACTION:
      bz_progress_ring_set_fraction (self, g_value_get_double (value));
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
    }
}

static void
bz_progress_ring_class_init (BzProgressRingClass *klass)
{
  GObjectClass   *object_class = G_OBJECT_CLASS (klass);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (klass);

  object_class->dispose      = bz_progress_ring_dispose;
  object_class->get_property = bz_progress_ring_get_property;
  object_class->set_property = bz_progress_ring_set_property;

  props[PROP_FRACTION] =
      g_param_spec_double (
          "fraction",
          NULL, NULL,
          -1.0, G_MAXDOUBLE, -1.0,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS | G_PARAM_EXPLICIT_NOTIFY);

  g_object_class_install_properties (object_class, LAST_PROP, props);

  gtk_widget_class_set_template_from_resource (widget_class, "/io/github/crhy/SpacedBazaar/bz-progress-ring.ui");
  gtk_widget_class_bind_template_child (widget_class, BzProgressRing, ring);
  gtk_widget_class_bind_template_child (widget_class, BzProgressRing, label);
}

static void
bz_progress_ring_init (BzProgressRing *self)
{
  self->fraction = -1.0;
  self->pulse_angle = 0.0;

  gtk_widget_init_template (GTK_WIDGET (self));

  gtk_drawing_area_set_draw_func (GTK_DRAWING_AREA (self->ring),
                                  bz_progress_ring_draw,
                                  self,
                                  NULL);

  bz_progress_ring_update_label (self);
  bz_progress_ring_start_pulse (self);
}

GtkWidget *
bz_progress_ring_new (void)
{
  return g_object_new (BZ_TYPE_PROGRESS_RING, NULL);
}

void
bz_progress_ring_set_fraction (BzProgressRing *self,
                               double         fraction)
{
  double old = 0.0;

  g_return_if_fail (BZ_IS_PROGRESS_RING (self));

  old = self->fraction;
  if (fraction < 0.0)
    self->fraction = -1.0;
  else
    self->fraction = CLAMP (fraction, 0.0, 1.0);

  if (old == self->fraction)
    return;

  if (self->fraction < 0.0)
    bz_progress_ring_start_pulse (self);
  else
    bz_progress_ring_stop_pulse (self);

  bz_progress_ring_update_label (self);
  gtk_widget_queue_draw (GTK_WIDGET (self));
  g_object_notify_by_pspec (G_OBJECT (self), props[PROP_FRACTION]);
}

double
bz_progress_ring_get_fraction (BzProgressRing *self)
{
  g_return_val_if_fail (BZ_IS_PROGRESS_RING (self), -1.0);
  return self->fraction;
}
