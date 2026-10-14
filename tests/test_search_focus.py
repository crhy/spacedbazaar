"""crhy/spaced#292: opening Search must put the cursor in the search field."""

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
WINDOW = (ROOT / "src/bz-window.c").read_text(encoding="utf-8")


class SearchFocusTests(unittest.TestCase):
    def test_every_way_into_search_focuses_the_field(self):
        # The Search tab, the Explore page's search button and shortcuts all
        # only change the visible page, so focus follows that change.
        self.assertIn('"notify::visible-child-name"', WINDOW)
        self.assertIn("G_CALLBACK (visible_page_changed_cb)", WINDOW)
        self.assertIn("gtk_widget_grab_focus (GTK_WIDGET (self->search_page));", WINDOW)

    def test_focus_waits_for_the_page_and_keeps_typed_text(self):
        self.assertIn("g_idle_add_full (G_PRIORITY_DEFAULT_IDLE, focus_search_idle", WINDOW)
        # Re-grabbing focus already inside the page would select what was typed.
        self.assertIn("gtk_widget_is_ancestor (focus, GTK_WIDGET (self->search_page))", WINDOW)


if __name__ == "__main__":
    unittest.main()
