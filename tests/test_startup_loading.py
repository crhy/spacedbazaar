"""Guard the initial catalog loading lifecycle."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "src/bz-application.c").read_text(
    encoding="utf-8"
)
WINDOW_TEMPLATE = (ROOT / "src/bz-window.blp").read_text(encoding="utf-8")
BUSY_FALSE = "bz_state_info_set_busy (self->state, FALSE);"


def function_body(name: str) -> str:
    definition = re.search(rf"\n{name} \([^;]*?\)\n\{{", SOURCE, re.DOTALL)
    if definition is None:
        raise AssertionError(f"function not found: {name}")

    start = definition.end() - 1
    depth = 0

    for position in range(start, len(SOURCE)):
        if SOURCE[position] == "{":
            depth += 1
        elif SOURCE[position] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start : position + 1]

    raise AssertionError(f"unterminated function: {name}")


class StartupLoadingTests(unittest.TestCase):
    def test_loading_page_shows_current_sync_task(self):
        loading_page = WINDOW_TEMPLATE.split('name: "loading";', 1)[1].split(
            'name: "main";', 1
        )[0]
        self.assertIn("background-task-label", loading_page)

    def test_setup_does_not_reveal_explore_before_sync_starts(self):
        self.assertNotIn(BUSY_FALSE, function_body("init_fiber"))

    def test_backend_notifications_do_not_reveal_explore_early(self):
        self.assertNotIn(BUSY_FALSE, function_body("respond_to_flatpak_fiber"))

    def test_joined_sync_reveals_explore_when_data_is_ready(self):
        make_sync = function_body("make_sync_future")
        self.assertLess(
            make_sync.index("dex_future_all ("),
            make_sync.index("(DexFutureCallback) sync_finally"),
        )
        self.assertIn(BUSY_FALSE, function_body("sync_finally"))


if __name__ == "__main__":
    unittest.main()
