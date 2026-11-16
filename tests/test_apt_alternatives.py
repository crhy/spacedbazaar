"""crhy/spacedbazaar#27: an apt version must be named, with why it can be better."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[1]
ALTERNATIVES = (ROOT / "src/bz-apt-alternatives.c").read_text(encoding="utf-8")
GROUP_HEADER = (ROOT / "src/bz-entry-group.h").read_text(encoding="utf-8")
GROUP_SOURCE = (ROOT / "src/bz-entry-group.c").read_text(encoding="utf-8")
FULL_VIEW_TEMPLATE = (ROOT / "src/bz-full-view.blp").read_text(encoding="utf-8")
FULL_VIEW_SOURCE = (ROOT / "src/bz-full-view.c").read_text(encoding="utf-8")
INSTALL_CONTROLS = (ROOT / "src/bz-install-controls.c").read_text(encoding="utf-8")
WINDOW = (ROOT / "src/bz-window.c").read_text(encoding="utf-8")

PACKAGE_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*")


def table_rows() -> list[str]:
    table = re.search(r"apt_alternatives\[\] = \{(.*?)\n\};", ALTERNATIVES, re.S)
    assert table is not None, "no apt alternative table in src/bz-apt-alternatives.c"
    return re.findall(r"\{([^{}]*)\}", table.group(1), re.S)


def row_strings(row: str) -> list[str]:
    return re.findall(r'"((?:[^"\\]|\\.)*)"', row)


def function_body(source: str, name: str) -> str:
    start = source.index(f"{name} (")
    return source[start : source.index("\n}\n", start)]


class AptAlternativeTableTests(unittest.TestCase):
    def test_the_table_offers_app_id_package_reason_triples(self):
        rows = table_rows()
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual(
                len(row_strings(row)), 3, f"expected id, package and reason: {row}"
            )

    def test_no_app_id_is_offered_twice(self):
        ids = [row_strings(row)[0] for row in table_rows()]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate app ids in {ids}")

    def test_every_app_id_is_a_flatpak_style_id(self):
        for row in table_rows():
            self.assertRegex(row_strings(row)[0], r"^[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+$")

    def test_every_package_is_a_valid_package_name(self):
        for row in table_rows():
            package = row_strings(row)[1]
            self.assertTrue(PACKAGE_RE.fullmatch(package), f"bad package: {package}")

    def test_every_reason_is_one_concrete_line(self):
        for row in table_rows():
            reason = row_strings(row)[2]
            self.assertTrue(reason.strip(), "empty reason")
            self.assertNotIn("\n", reason)
            self.assertLessEqual(len(reason), 120, f"reason too long: {reason}")

    def test_the_reasons_are_marked_for_translation(self):
        for row in table_rows():
            self.assertIn("N_ (", row)

    def test_the_lookup_reports_no_alternative_for_unknown_ids(self):
        self.assertRegex(
            ALTERNATIVES,
            re.compile(
                r"bz_apt_alternative_lookup \(const char \*app_id,\s*"
                r"char\s+\*\*package,\s*char\s+\*\*reason\)",
                re.S,
            ),
        )
        lookup = function_body(ALTERNATIVES, "bz_apt_alternative_lookup")
        self.assertIn("return FALSE;", lookup)
        self.assertIn("g_strcmp0 (apt_alternatives[i].app_id, app_id)", lookup)


class GroupAccessorTests(unittest.TestCase):
    def test_the_group_exposes_the_alternative(self):
        self.assertIn("bz_entry_group_get_apt_alternative", GROUP_HEADER)
        self.assertRegex(
            GROUP_SOURCE,
            re.compile(
                r"bz_entry_group_get_apt_alternative \(BzEntryGroup \*self,\s*"
                r"char\s+\*\*package,\s*char\s+\*\*reason\)",
                re.S,
            ),
        )

    def test_the_accessor_looks_the_group_id_up_in_the_table(self):
        body = function_body(GROUP_SOURCE, "bz_entry_group_get_apt_alternative")
        self.assertIn("bz_entry_group_get_id (self)", body)
        self.assertIn("bz_apt_alternative_lookup (id, package, reason)", body)


class AppPageTests(unittest.TestCase):
    def test_the_app_page_shows_the_alternative_under_the_title(self):
        name_box = FULL_VIEW_TEMPLATE.split("app_name_box", 1)[1].split('"bz-debug"', 1)[0]
        self.assertIn("apt_alternative_label", name_box)
        self.assertIn(
            "label: bind $format_apt_alternative_label("
            "template.entry-group as <$BzEntryGroup>) as <string>;",
            name_box,
        )
        self.assertIn("wrap: true;", name_box)
        self.assertIn("selectable: true;", name_box)

    def test_the_line_hides_itself_when_there_is_no_alternative(self):
        self.assertIn(
            "visible: bind $apt_alternative_exists("
            "template.entry-group as <$BzEntryGroup>) as <bool>;",
            FULL_VIEW_TEMPLATE,
        )

    def test_the_page_registers_the_callbacks_and_words_the_offer(self):
        self.assertIn(
            "gtk_widget_class_bind_template_callback (widget_class, "
            "apt_alternative_exists);",
            FULL_VIEW_SOURCE,
        )
        self.assertIn(
            "gtk_widget_class_bind_template_callback (widget_class, "
            "format_apt_alternative_label);",
            FULL_VIEW_SOURCE,
        )
        self.assertIn('_ ("Also in apt as %s: %s")', FULL_VIEW_SOURCE)


class InstallTimeTests(unittest.TestCase):
    def test_the_install_button_names_the_alternative(self):
        self.assertIn("set_install_btn_tooltip (self);", INSTALL_CONTROLS)
        self.assertIn("bz_entry_group_get_apt_alternative", INSTALL_CONTROLS)
        self.assertIn("sudo apt install %s", INSTALL_CONTROLS)

    def test_the_install_action_says_it_before_starting_the_install(self):
        action = function_body(WINDOW, "action_install_group")
        self.assertLess(
            action.index("notify_apt_alternative (self, group);"),
            action.index("try_transact ("),
        )
        self.assertIn("sudo apt install %s", WINDOW)

    def test_no_message_claims_bazaar_ran_apt(self):
        # The apt build is only ever offered: the command is spelled out for
        # the user to run, and nothing may read as if it had already happened.
        for source in (FULL_VIEW_SOURCE, INSTALL_CONTROLS, WINDOW):
            for literal in re.findall(r'"(?:[^"\\]|\\)*"', source):
                if "apt" not in literal:
                    continue
                self.assertNotIn("installed", literal.lower(), literal)
                self.assertNotRegex(literal, r"apt install(?:ed|s)\b")

    def test_the_offer_is_framed_as_the_users_own_command(self):
        for source in (INSTALL_CONTROLS, WINDOW):
            self.assertIn("To install that version instead, run:", source)


if __name__ == "__main__":
    unittest.main()
