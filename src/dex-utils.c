/* dex-utils.c
 *
 * Copyright 2026 Eva M
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

#include <gobject/gvaluecollector.h>

#include "dex-utils.h"

typedef enum
{
  CALLBACK_THEN,
  CALLBACK_CATCH,
  CALLBACK_FINALLY,
} CallbackKind;

DEX_DEFINE_CLOSURE_TYPE (
    Trampoline,
    trampoline,
    DEX_DEFINE_CLOSURE_VALUE (GCallback, callback),
    DEX_DEFINE_CLOSURE_POINTER (GArray *, values, g_array_unref))

static DexFuture *
make_callback_future (CallbackKind kind,
                      DexFuture   *future,
                      GCallback    callback,
                      guint        n_params,
                      va_list      args);

static DexFuture *
trampoline_future_cb (DexFuture  *future,
                      Trampoline *state);

DexFuture *
bz_future_thenv (DexFuture *future,
                 GCallback  callback,
                 guint      n_params,
                 ...)
{
  va_list args;

  va_start (args, n_params);
  future = make_callback_future (CALLBACK_THEN, future, callback, n_params, args);
  va_end (args);

  return future;
}

DexFuture *
bz_future_catchv (DexFuture *future,
                  GCallback  callback,
                  guint      n_params,
                  ...)
{
  va_list args;

  va_start (args, n_params);
  future = make_callback_future (CALLBACK_CATCH, future, callback, n_params, args);
  va_end (args);

  return future;
}

DexFuture *
bz_future_finallyv (DexFuture *future,
                    GCallback  callback,
                    guint      n_params,
                    ...)
{
  va_list args;

  va_start (args, n_params);
  future = make_callback_future (CALLBACK_FINALLY, future, callback, n_params, args);
  va_end (args);

  return future;
}

static DexFuture *
make_callback_future (CallbackKind kind,
                      DexFuture   *future,
                      GCallback    callback,
                      guint        n_params,
                      va_list      args)
{
  g_autofree char *errmsg   = NULL;
  g_autoptr (GArray) values = NULL;

  values = g_array_new (FALSE, TRUE, sizeof (GValue));
  g_array_set_clear_func (values, (GDestroyNotify) g_value_unset);
  g_array_set_size (values, n_params + 1);

  /* The first value is the future result */
  g_value_init (&g_array_index (values, GValue, 0), G_TYPE_POINTER);

  for (guint i = 1; i < n_params + 1; i++)
    {
      GType   gtype = va_arg (args, GType);
      GValue *dest  = &g_array_index (values, GValue, i);
      GValue  value = G_VALUE_INIT;

      G_VALUE_COLLECT_INIT (&value, gtype, args, 0, &errmsg);

      if (errmsg != NULL)
        break;

      g_value_init (dest, gtype);
      g_value_copy (&value, dest);
      g_value_unset (&value);
    }

  if (errmsg != NULL)
    future = dex_future_new_reject (DEX_ERROR,
                                    DEX_ERROR_TYPE_MISMATCH,
                                    "Failed to trampoline to callback: %s",
                                    errmsg);
  else
    {
      Trampoline *state = NULL;

      state           = trampoline_new ();
      state->values   = g_steal_pointer (&values);
      state->callback = callback;

      switch (kind)
        {
        case CALLBACK_THEN:
          future = dex_future_then (
              future,
              (DexFutureCallback) trampoline_future_cb,
              g_steal_pointer (&state),
              (GDestroyNotify) trampoline_free);
          break;
        case CALLBACK_CATCH:
          future = dex_future_catch (
              future,
              (DexFutureCallback) trampoline_future_cb,
              g_steal_pointer (&state),
              (GDestroyNotify) trampoline_free);
          break;
        case CALLBACK_FINALLY:
          future = dex_future_finally (
              future,
              (DexFutureCallback) trampoline_future_cb,
              g_steal_pointer (&state),
              (GDestroyNotify) trampoline_free);
          break;
        default:
          g_assert_not_reached ();
        }
    }

  return future;
}

static DexFuture *
trampoline_future_cb (DexFuture  *future,
                      Trampoline *state)
{
  g_autoptr (GClosure) closure = NULL;
  GValue   return_value        = G_VALUE_INIT;
  gpointer res;

  g_assert (state != NULL);
  g_assert (state->callback != NULL);
  g_assert (state->values != NULL);

  g_value_init (&return_value, G_TYPE_POINTER);
  g_value_set_pointer (&g_array_index (state->values, GValue, 0), future);

  closure = g_cclosure_new (state->callback, NULL, NULL);
  g_closure_set_marshal (closure, g_cclosure_marshal_generic);
  g_closure_invoke (closure,
                    &return_value,
                    state->values->len,
                    (const GValue *) (gpointer) state->values->data,
                    NULL);
  res = g_value_get_pointer (&return_value);

  g_value_unset (&g_array_index (state->values, GValue, 0));
  g_value_unset (&return_value);

  return res;
}
