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

/* A circular progress indicator with the percentage in its centre, used
 * while the app catalogs load (crhy/spaced#291).  A fraction of zero or
 * less means "not known yet": a short arc turns until real progress
 * arrives.  Known progress glides between steps with the same spring as
 * BzProgressBar. */

#include "config.h"

#include <math.h>

#include "bz-progress-ring.h"

#define RING_LINE_WIDTH  8.0
#define PULSE_ARC        (G_PI / 2.0)
#define PULSE_PERIOD_US  (1200 * G_TIME_SPAN_MILLISECOND)

struct _BzProgressRing
{
  AdwBin parent_instance;

  double fraction;
  double shown;
  guint  pulse_tick;

  AdwAnimation *animation;

  /* Template widgets */
  GtkDrawingArea *ring;
  GtkLabel       *label;
};

G_DEFINE_FINAL_TYPE (BzProgressRing, bz_progress_ring, ADW_TYPE_BIN)

enum
{
  PROP_0,

  PROP_FRACTION,

  LAST_PROP
};
static GParamSpec *props[LAST_PROP] = { 0 };

static gboolean
known (BzProgressRing *self)
{
  return self->fraction > 0.0;
}

static void
draw_ring (GtkDrawingArea *area,
           cairo_t        *cr,
           int             width,
           int             height,
           gpointer        user_data)
{
  BzProgressRing *self   = BZ_PROGRESS_RING (user_data);
  GdkRGBA         accent = { 0 };
  double          cx     = width / 2.0;
  double          cy     = height / 2.0;
  double          radius = (MIN (width, height) - RING_LINE_WIDTH) / 2.0;
  double          start  = -G_PI / 2.0;
  double          sweep  = 0.0;

  if (radius <= 0.0)
    return;

  gtk_widget_get_color (GTK_WIDGET (area), &accent);
  {
    g_autoptr (GdkRGBA) style_accent = NULL;

    style_accent = adw_style_manager_get_accent_color_rgba (adw_style_manager_get_default ());
    if (style_accent != NULL)
      accent = *style_accent;
  }

  cairo_set_line_width (cr, RING_LINE_WIDTH);
  cairo_set_line_cap (cr, CAIRO_LINE_CAP_ROUND);

  /* Track */
  cairo_set_source_rgba (cr, accent.red, accent.green, accent.blue, 0.2);
  cairo_arc (cr, cx, cy, radius, 0.0, 2.0 * G_PI);
  cairo_stroke (cr);

  if (known (self))
    sweep = CLAMP (self->shown, 0.0, 1.0) * 2.0 * G_PI;
  else
    {
      gint64 now = g_get_monotonic_time ();

      start += (double) (now % PULSE_PERIOD_US) / PULSE_PERIOD_US * 2.0 * G_PI;
      sweep = PULSE_ARC;
    }

  if (sweep <= 0.0)
    return;

  cairo_set_source_rgba (cr, accent.red, accent.green, accent.blue, 1.0);
  cairo_arc (cr, cx, cy, radius, start, start + sweep);
  cairo_stroke (cr);
}

static void
update_label (BzProgressRing *self)
{
  g_autofree char *text = NULL;

  if (known (self))
    text = g_strdup_printf ("%d%%", (int) round (CLAMP (self->shown, 0.0, 1.0) * 100.0));
  else
    text = g_strdup ("");

  gtk_label_set_label (self->label, text);
}

static gboolean
pulse_tick_cb (GtkWidget     *widget,
               GdkFrameClock *frame_clock,
               gpointer       user_data)
{
  BzProgressRing *self = BZ_PROGRESS_RING (user_data);

  gtk_widget_queue_draw (GTK_WIDGET (self->ring));
  return G_SOURCE_CONTINUE;
}

static void
update_pulse (BzProgressRing *self)
{
  /* Tick callbacks only run while the widget is mapped, so a hidden ring
   * costs nothing. */
  if (!known (self) && self->pulse_tick == 0)
    self->pulse_tick = gtk_widget_add_tick_callback (GTK_WIDGET (self), pulse_tick_cb, self, NULL);
  else if (known (self) && self->pulse_tick != 0)
    {
      gtk_widget_remove_tick_callback (GTK_WIDGET (self), self->pulse_tick);
      self->pulse_tick = 0;
    }
}

static void
animate_cb (double   value,
            gpointer user_data)
{
  BzProgressRing *self = BZ_PROGRESS_RING (user_data);

  self->shown = value;
  update_label (self);
  gtk_widget_queue_draw (GTK_WIDGET (self->ring));
}

static void
bz_progress_ring_dispose (GObject *object)
{
  BzProgressRing *self = BZ_PROGRESS_RING (object);

  if (self->pulse_tick != 0)
    {
      gtk_widget_remove_tick_callback (GTK_WIDGET (self), self->pulse_tick);
      self->pulse_tick = 0;
    }
  g_clear_object (&self->animation);

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
          -G_MAXDOUBLE, G_MAXDOUBLE, 0.0,
          G_PARAM_READWRITE | G_PARAM_EXPLICIT_NOTIFY);

  g_object_class_install_properties (object_class, LAST_PROP, props);

  gtk_widget_class_set_template_from_resource (widget_class, "/io/github/crhy/SpacedBazaar/bz-progress-ring.ui");
  gtk_widget_class_bind_template_child (widget_class, BzProgressRing, ring);
  gtk_widget_class_bind_template_child (widget_class, BzProgressRing, label);
}

static void
bz_progress_ring_init (BzProgressRing *self)
{
  AdwAnimationTarget *target = NULL;
  AdwSpringParams    *spring = NULL;

  gtk_widget_init_template (GTK_WIDGET (self));
  gtk_drawing_area_set_draw_func (self->ring, draw_ring, self, NULL);

  target = adw_callback_animation_target_new (animate_cb, self, NULL);
  spring = adw_spring_params_new (1.0, 0.5, 200.0);

  self->animation = adw_spring_animation_new (
      GTK_WIDGET (self),
      0.0,
      0.0,
      spring,
      target);
  adw_spring_animation_set_epsilon (
      ADW_SPRING_ANIMATION (self->animation), 0.00025);

  update_label (self);
  update_pulse (self);
}

GtkWidget *
bz_progress_ring_new (void)
{
  return g_object_new (BZ_TYPE_PROGRESS_RING, NULL);
}

void
bz_progress_ring_set_fraction (BzProgressRing *self,
                               double          fraction)
{
  double last = 0.0;

  g_return_if_fail (BZ_IS_PROGRESS_RING (self));

  last           = self->fraction;
  self->fraction = fraction > 0.0 ? MIN (fraction, 1.0) : 0.0;
  if (G_APPROX_VALUE (last, self->fraction, 0.001))
    return;

  update_pulse (self);

  if (!known (self) || self->fraction < last)
    {
      /* Unknown again, or a fresh sync started over: jump, don't rewind. */
      adw_animation_reset (self->animation);
      animate_cb (self->fraction, self);
    }
  else
    {
      adw_spring_animation_set_value_from (
          ADW_SPRING_ANIMATION (self->animation),
          self->shown);
      adw_spring_animation_set_value_to (
          ADW_SPRING_ANIMATION (self->animation),
          self->fraction);
      adw_animation_play (self->animation);
    }

  g_object_notify_by_pspec (G_OBJECT (self), props[PROP_FRACTION]);
}

double
bz_progress_ring_get_fraction (BzProgressRing *self)
{
  g_return_val_if_fail (BZ_IS_PROGRESS_RING (self), 0.0);
  return self->fraction;
}
