"""crhy/spacedbazaar#35 (bz02): polish the "Recommended for you" card.

Claude's review of bz01, one test class per finding B1-B7. Offline with
fakes like the rest of this suite: the sources and the shipped data are the
thing under test. Nothing here touches the network.
"""

from pathlib import Path
import json
import unittest


ROOT = Path(__file__).parents[1]
CHOICE_SOURCE = (ROOT / "src/bz-format-choice.c").read_text(encoding="utf-8")
FULL_VIEW_TEMPLATE = (ROOT / "src/bz-full-view.blp").read_text(encoding="utf-8")
FULL_VIEW_SOURCE = (ROOT / "src/bz-full-view.c").read_text(encoding="utf-8")
GROUP_SOURCE = (ROOT / "src/bz-entry-group.c").read_text(encoding="utf-8")
INSTALL_CONTROLS = (ROOT / "src/bz-install-controls.c").read_text(encoding="utf-8")
TRANSACTION_DIALOG = (ROOT / "src/bz-transaction-dialog.c").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "src/style.css").read_text(encoding="utf-8")
ADVICE = json.loads((ROOT / "data/format-advice.json").read_text(encoding="utf-8"))


def card_text():
    return (FULL_VIEW_TEMPLATE
            .split("Box recommendation_card", 1)[1]
            .split("Box other_formats_box", 1)[0])


class OneInstallButtonTests(unittest.TestCase):
    """B1: the header button installs the RECOMMENDED format and says so;
    the card keeps badge + reason and no button."""

    def test_the_card_has_no_install_button(self):
        card = card_text()
        self.assertNotIn("Button", card)
        self.assertNotIn("install_recommended_cb", FULL_VIEW_SOURCE)
        self.assertNotIn("recommend_install_label", FULL_VIEW_SOURCE)

    def test_the_header_button_names_the_recommended_build(self):
        self.assertIn("_ (\"Install %s\")", INSTALL_CONTROLS)
        self.assertIn("set_install_btn_label", INSTALL_CONTROLS)
        self.assertIn('"lbl-install"', INSTALL_CONTROLS)

    def test_the_header_button_installs_the_recommended_build(self):
        self.assertIn('"window.install-format"', INSTALL_CONTROLS)
        self.assertIn('"recommended"', INSTALL_CONTROLS)


class LiteralUnderscoresTests(unittest.TestCase):
    """B2: no button may show a literal underscore."""

    def test_no_install_label_carries_a_mnemonic_underscore(self):
        for source in (FULL_VIEW_TEMPLATE, TRANSACTION_DIALOG,
                       INSTALL_CONTROLS):
            self.assertNotIn('"_Install', source)

    def test_the_override_rows_say_plain_install(self):
        row_box = (FULL_VIEW_TEMPLATE
                   .split("Box other_formats_box", 1)[1]
                   .split("Box context_bar", 1)[0])
        self.assertEqual(row_box.count('label: _("Install");'), 2,
                         "one plain Install button per other-format row")


class OtherFormatsRowTests(unittest.TestCase):
    """B3: the row lists only the formats other than the recommended one."""

    def test_the_recommended_build_is_never_repeated_in_the_row(self):
        self.assertIn("bz_format_choice_get_pick (choice) == parsed",
                      FULL_VIEW_SOURCE)

    def test_the_row_exists_only_for_a_build_other_than_the_pick(self):
        self.assertIn("other_has_format (object, group,",
                      FULL_VIEW_SOURCE,
                      "the row heading waits for a real other-format row")


class VersionAndSizeDisplayTests(unittest.TestCase):
    """B4: unknown version/size are hidden, not announced; known versions
    come from the format's own source."""

    def test_no_listing_says_version_not_known(self):
        for source in (CHOICE_SOURCE, FULL_VIEW_SOURCE):
            self.assertNotIn("version not known", source)

    def test_the_flatpak_version_is_the_remote_appdata_release(self):
        self.assertIn('"version-history"', GROUP_SOURCE)
        self.assertIn("bz_release_get_version", GROUP_SOURCE)

    def test_the_appimage_version_is_the_release_tag_recorded_at_install(self):
        self.assertIn("bz_appimage_dup_installed_version", GROUP_SOURCE)

    def test_the_card_hides_an_unknown_version_and_size(self):
        self.assertIn('if (version == NULL)', FULL_VIEW_SOURCE)
        self.assertIn('if (size <= 0)', FULL_VIEW_SOURCE)


class UserWordingTests(unittest.TestCase):
    """B5: user wording, not developer wording."""

    def test_freeCAD_advice_is_user_wording(self):
        rows = [row for row in ADVICE["advice"] if "FreeCAD" in row["app_id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["reason"],
            "Runs best on Spaced. The Flatpak version freezes on this desktop.",
        )
        self.assertNotIn("under investigation", rows[0]["reason"].lower())

    def test_the_scored_reasons_are_user_wording(self):
        self.assertIn('_ ("Newest version")', CHOICE_SOURCE)
        self.assertIn('_ ("Sandboxed: kept apart from your files")', CHOICE_SOURCE)
        self.assertIn('_ ("Already installed")', CHOICE_SOURCE)
        for developer in ("under investigation", "the best match offered"):
            self.assertNotIn(developer, CHOICE_SOURCE)


class CardStylingTests(unittest.TestCase):
    """B6: title, badge pill, version and reason inside one rounded card
    with the theme accent border; no hard-coded colours."""

    def test_the_card_uses_the_named_card_and_badge_styles(self):
        card = card_text()
        self.assertIn('"recommend-card"', card)
        self.assertIn('"recommend-badge"', card)

    def test_the_badge_is_a_pill_of_icon_plus_format_name(self):
        card = card_text()
        self.assertIn('icon-name: bind $recommend_badge_icon(', card)
        for icon in ("flathub-symbolic", "application-x-executable-symbolic",
                     "package-x-generic-symbolic"):
            self.assertIn(icon, FULL_VIEW_SOURCE)

    def test_the_title_sits_inside_the_card_padding(self):
        card = card_text()
        self.assertIn('label: _("Recommended for you");', card)
        self.assertIn(".recommend-card {", STYLE_CSS)
        self.assertIn("padding:", STYLE_CSS.split(".recommend-card {")[1])

    def test_the_border_comes_from_the_desktop_accent(self):
        css = STYLE_CSS.split(".recommend-card {")[1].split("}")[0]
        self.assertIn("var(--accent-color)", css)
        self.assertNotIn("#", css)


class AptRowsNotListedTests(unittest.TestCase):
    """B7: apt rows Bazaar cannot install are not listed at all."""

    def test_the_page_has_no_apt_row(self):
        self.assertNotIn("apt", FULL_VIEW_TEMPLATE.split("Box other_formats_box", 1)[1]
                         .split("Box context_bar", 1)[0])
        self.assertIn("parsed == BZ_FORMAT_CHOICE_FORMAT_APT", FULL_VIEW_SOURCE)

    def test_no_apt_install_button_is_bound(self):
        self.assertNotIn("install_apt_cb", FULL_VIEW_SOURCE)


if __name__ == "__main__":
    unittest.main()
