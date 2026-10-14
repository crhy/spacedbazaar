"""Every entry that is not installed must count as installable (0.1.13 regression)."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "src/bz-entry-group.c").read_text(encoding="utf-8")


def reconcile_body() -> str:
    start = SOURCE.index("\nbz_entry_group_reconcile_with_installed_set (")
    return SOURCE[start : SOURCE.index("\n}\n", start)]


class ReconcileTests(unittest.TestCase):
    def test_installable_branch_belongs_to_the_installed_check(self):
        # 0.1.13 put another if between the installed check and its else, so
        # apps that were not installed never counted as installable and had
        # no Install button.
        self.assertRegex(
            reconcile_body(),
            re.compile(
                r"if \(g_hash_table_contains \(installed_set, uid\)\)\s*\{[^{}]*\}\s*else\s*\{\s*"
                r"flags \|= ENTRY_INSTALLABLE",
                re.S,
            ),
        )


if __name__ == "__main__":
    unittest.main()
