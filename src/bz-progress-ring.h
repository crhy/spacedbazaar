/* bz-progress-ring.h
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

#pragma once

#include <adwaita.h>

G_BEGIN_DECLS

#define BZ_TYPE_PROGRESS_RING (bz_progress_ring_get_type ())
G_DECLARE_FINAL_TYPE (BzProgressRing, bz_progress_ring, BZ, PROGRESS_RING, AdwBin)

GtkWidget *
bz_progress_ring_new (void);

void
bz_progress_ring_set_fraction (BzProgressRing *self,
                               double          fraction);

double
bz_progress_ring_get_fraction (BzProgressRing *self);

G_END_DECLS
