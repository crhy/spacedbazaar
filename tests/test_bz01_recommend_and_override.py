"""crhy/spacedbazaar#35 (bz01): "Recommended for you" at the top of the app page,
AppImage as a third format, and the override row.

Offline with fakes, like the rest of this suite: the machine this runs on has
no glib, no GTK and no meson, so the sources and the shipped data are the
thing under test. Nothing here touches the network.
"""

from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).parents[1]
CHOICE_HEADER = (ROOT / "src/bz-format-choice.h").read_text(encoding="utf-8")
CHOICE_SOURCE = (ROOT / "src/bz-format-choice.c").read_text(encoding="utf-8")
APPIMAGE_HEADER = (ROOT / "src/bz-appimage-source.h").read_text(encoding="utf-8")
APPIMAGE_SOURCE = (ROOT / "src/bz-appimage-source.c").read_text(encoding="utf-8")
FULL_VIEW_TEMPLATE = (ROOT / "src/bz-full-view.blp").read_text(encoding="utf-8")
FULL_VIEW_SOURCE = (ROOT / "src/bz-full-view.c").read_text(encoding="utf-8")
WINDOW_SOURCE = (ROOT / "src/bz-window.c").read_text(encoding="utf-8")
LIBRARY_TEMPLATE = (ROOT / "src/bz-library-page.blp").read_text(encoding="utf-8")
LIBRARY_SOURCE = (ROOT / "src/bz-library-page.c").read_text(encoding="utf-8")
ADVICE = json.loads((ROOT / "data/format-advice.json").read_text(encoding="utf-8"))


def function_body(source: str, name: str) -> str:
    """The definition of a GNU-style function, not a declaration or a call."""
    pattern = re.compile(r"(?m)^" + re.escape(name) + r" \(")
    for match in pattern.finditer(source):
        brace = source.find("\n{\n", match.start())
        semicolon = source.find(";", match.start())
        if brace == -1:
            continue
        if semicolon != -1 and semicolon < brace:
            continue
        return source[match.start() : source.index("\n}\n", brace)]

    raise AssertionError(f"no definition of {name} in this file")


class RecommendationOrderTests(unittest.TestCase):
    def test_the_rules_are_weighted_in_the_documented_order(self):
        weights = {
            name: int(value)
            for name, value in re.findall(
                r"#define (ADVICE|INSTALLED|NEWEST|KNOWN_VERSION|SANDBOX|SIZE)_WEIGHT (\d+)",
                CHOICE_SOURCE)
        }
        self.assertEqual(set(weights),
                         {"ADVICE", "INSTALLED", "NEWEST", "KNOWN_VERSION",
                          "SANDBOX", "SIZE"})
        advice = weights["ADVICE"]
        others = sum(v for k, v in weights.items() if k != "ADVICE")
        self.assertGreater(advice, others,
                           "curated advice must win over the sum of everything else")
        # already installed outranks a newer version elsewhere plus sandboxing
        self.assertGreater(weights["INSTALLED"],
                           weights["NEWEST"] + weights["KNOWN_VERSION"] +
                           weights["SANDBOX"],
                           "already installed must outrank newest version")
        # the download size is the last tie to break, and the smallest one
        self.assertEqual(weights["SIZE"], min(weights.values()),
                         "smaller download must be the last rule weighed")

    def test_freshness_ignores_a_packaging_suffix_only_difference(self):
        self.assertIn("bz_format_choice_dup_release_version", CHOICE_HEADER)
        body = function_body(CHOICE_SOURCE, "bz_format_choice_dup_release_version")
        self.assertIn("is_packaging_suffix", body)
        suffix = function_body(CHOICE_SOURCE, "is_packaging_suffix")
        self.assertIn("dfsg", suffix)
        # a release label is never packaging: the suffix scan must refuse words
        self.assertIn("g_ascii_isdigit", suffix)
        evaluate = function_body(CHOICE_SOURCE, "bz_format_choice_evaluate")
        # the newest version is computed from the normalized release versions
        self.assertIn("bz_format_choice_dup_release_version (offer->version)",
                      evaluate)
        newest_at = evaluate.index("bz_format_choice_dup_release_version (offer->version)")
        newest_cmp = evaluate.index("bz_format_choice_compare_versions (release, newest) == 0")
        self.assertLess(newest_at, newest_cmp)

    def test_sandboxing_only_breaks_a_version_tie(self):
        evaluate = function_body(CHOICE_SOURCE, "bz_format_choice_evaluate")
        sandbox_at = evaluate.index("score += SANDBOX_WEIGHT")
        tie_at = evaluate.index("bz_format_choice_compare_versions (release, newest) == 0")
        self.assertLess(sandbox_at, tie_at,
                        "sandboxing is weighed before it is known whether versions tie")

    def test_smallest_download_earns_the_last_bonus(self):
        evaluate = function_body(CHOICE_SOURCE, "bz_format_choice_evaluate")
        self.assertIn("smallest_size", evaluate)
        self.assertIn("score += SIZE_WEIGHT", evaluate)
        size_at = evaluate.index("score += SIZE_WEIGHT")
        advice_at = evaluate.index("score += ADVICE_WEIGHT")
        self.assertLess(size_at, advice_at, "size is weighed before curated advice")

    def test_freeCAD_recommends_the_appimage_with_a_plain_word_reason(self):
        rows = [row for row in ADVICE["advice"] if "FreeCAD" in row["app_id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pick"], "appimage")
        self.assertIn("flatpak freezes", rows[0]["reason"])
        evaluate = function_body(CHOICE_SOURCE, "bz_format_choice_evaluate")
        self.assertIn("score += ADVICE_WEIGHT", evaluate)
        self.assertIn("advice->reason", CHOICE_SOURCE)


class RecommendationCardTests(unittest.TestCase):
    def test_the_card_sits_at_the_top_of_the_page_under_the_title(self):
        template = FULL_VIEW_TEMPLATE
        title_at = template.index('"app-title"')
        card_at = template.index("Box recommendation_card")
        other_at = template.index("Box other_formats_box")
        context_at = template.index("Box context_bar")
        self.assertLess(title_at, card_at, "the card must sit under the title")
        self.assertLess(card_at, other_at, "the row must sit under the card")
        self.assertLess(other_at, context_at)

    def test_the_card_shows_the_format_version_size_reason_and_one_button(self):
        card = FULL_VIEW_TEMPLATE.split("Box recommendation_card", 1)[1].split("Box other_formats_box", 1)[0]
        for name in ("recommend_badge", "recommend_version", "recommend_size",
                     "recommend_reason", "recommend_install_button"):
            self.assertIn(name, card)
        self.assertIn('clicked => $install_recommended_cb(template);', card)
        self.assertEqual(card.count("install_recommended_cb"), 1,
                         "exactly one big Install button on the card")

    def test_the_row_lists_every_format_with_its_own_install_button(self):
        row_box = FULL_VIEW_TEMPLATE.split("Box other_formats_box", 1)[1].split("Box context_bar", 1)[0]
        self.assertIn("_(\"Other ways to install\")", row_box)
        for fmt in ("apt", "flatpak", "appimage"):
            self.assertIn(f"other_{fmt}_row", row_box)
            self.assertIn(f'other_summary(template.entry-group as <$BzEntryGroup>, "{fmt}")', row_box)
            self.assertIn(f'clicked => $install_{fmt}_cb(template);', row_box)

    def test_installed_in_another_format_says_so_and_stops_recommending(self):
        self.assertIn('_ ("Installed as %s")', CHOICE_SOURCE)
        self.assertIn("bz_format_choice_get_installed_note", CHOICE_HEADER)
        card = FULL_VIEW_TEMPLATE.split("Box recommendation_card", 1)[1].split("Box other_formats_box", 1)[0]
        self.assertIn("recommend_installed_note", card)
        self.assertIn("$invert_boolean($recommend_installed(", card,
                      "the install button hides while something is installed")

    def test_the_page_registers_the_card_callbacks(self):
        for callback in ("recommend_badge", "recommend_version", "recommend_size",
                         "recommend_reason", "recommend_installed",
                         "recommend_installed_note", "recommend_install_label",
                         "other_formats_exists", "other_has_format",
                         "other_summary", "install_recommended_cb",
                         "install_apt_cb", "install_flatpak_cb",
                         "install_appimage_cb"):
            self.assertIn(
                "gtk_widget_class_bind_template_callback (widget_class, "
                f"{callback});",
                FULL_VIEW_SOURCE,
            )


class OverrideInstallTests(unittest.TestCase):
    def test_the_window_knows_how_to_install_each_format(self):
        self.assertIn('"window.install-format", "(ss)"', WINDOW_SOURCE)
        action = function_body(WINDOW_SOURCE, "action_install_format")
        self.assertIn("BZ_FORMAT_CHOICE_FORMAT_FLATPAK", action)
        self.assertIn("BZ_FORMAT_CHOICE_FORMAT_APPIMAGE", action)
        self.assertIn("BZ_FORMAT_CHOICE_FORMAT_APT", action)
        self.assertIn('"recommended"', action,
                      "the card installs whatever the choice picked")

    def test_the_override_installs_the_chosen_format_not_the_default(self):
        action = function_body(WINDOW_SOURCE, "action_install_format")
        flatpak_at = action.index("case BZ_FORMAT_CHOICE_FORMAT_FLATPAK:")
        appimage_at = action.index("case BZ_FORMAT_CHOICE_FORMAT_APPIMAGE:")
        parse_at = action.index("bz_format_choice_parse_format (format)")
        self.assertLess(parse_at, flatpak_at)
        self.assertLess(parse_at, appimage_at)
        self.assertIn("install_appimage_choice_fiber", action,
                      "the AppImage override really installs the AppImage")

    def test_the_appimage_install_requires_a_published_checksum(self):
        fiber = function_body(WINDOW_SOURCE, "install_appimage_choice_fiber")
        self.assertIn("bz_appimage_source_query_release_json", fiber)
        self.assertIn("bz_appimage_release_from_json", fiber)
        self.assertIn("BZ_APPIMAGE_ERROR_NO_PUBLISHED_SHA256", fiber)
        self.assertIn("Not offered: no published checksum", fiber)
        install_at = fiber.index("bz_appimage_source_install")
        no_checksum_at = fiber.index("BZ_APPIMAGE_ERROR_NO_PUBLISHED_SHA256")
        self.assertLess(no_checksum_at, install_at,
                        "nothing installs before the published checksum is required")

    def test_a_checksum_mismatch_is_refused_and_writes_nothing(self):
        fiber = function_body(APPIMAGE_SOURCE, "install_appimage_fiber")
        mismatch = fiber.index("BZ_APPIMAGE_ERROR_SHA256_MISMATCH")
        written = fiber.index("write_bytes_to_path (install_path")
        self.assertLess(mismatch, written,
                        "nothing may be written before the digest is compared")
        window_fiber = function_body(WINDOW_SOURCE, "install_appimage_choice_fiber")
        self.assertIn("BZ_APPIMAGE_ERROR_SHA256_MISMATCH", window_fiber)
        self.assertIn("nothing was installed", window_fiber)

    def test_the_update_check_compares_release_versions(self):
        self.assertIn("bz_appimage_dup_installed_version", APPIMAGE_HEADER)
        fiber = function_body(WINDOW_SOURCE, "install_appimage_choice_fiber")
        self.assertIn("bz_appimage_dup_installed_version", fiber)
        self.assertIn("bz_format_choice_compare_versions (release->tag_name", fiber)
        contents = function_body(APPIMAGE_SOURCE, "bz_appimage_dup_desktop_contents")
        self.assertIn("as an AppImage (version %s)", contents,
                      "the installed version is recorded so the check can read it back")

    def test_an_appimage_only_counts_as_installed_when_the_files_exist(self):
        body = function_body(APPIMAGE_SOURCE, "bz_appimage_is_installed")
        self.assertNotIn("paths->len > 0", body,
                         "the candidate paths are always listed; installed must mean present")
        self.assertIn("G_FILE_TEST_EXISTS", body)

    def test_the_installed_page_lists_the_appimages(self):
        self.assertIn("Installed as AppImages", LIBRARY_TEMPLATE)
        self.assertIn("appimage_installed_rows", LIBRARY_TEMPLATE)
        self.assertIn("bz_appimage_dup_installed_app_ids", LIBRARY_SOURCE)
        self.assertIn("bz_appimage_source_uninstall", LIBRARY_SOURCE)
        self.assertIn("bz_appimage_dup_installed_version", LIBRARY_SOURCE)

    def test_uninstall_removes_exactly_the_installed_files(self):
        paths = function_body(APPIMAGE_SOURCE, "bz_appimage_dup_uninstall_paths")
        self.assertIn("bz_appimage_dup_desktop_path (app_id)", paths)
        self.assertIn("bz_appimage_dup_icon_path (app_id)", paths)
        body = function_body(APPIMAGE_SOURCE, "uninstall_appimage_fiber")
        self.assertIn("bz_appimage_dup_uninstall_paths", body)
        self.assertIn("g_remove (path)", body)
        for literal in re.findall(r'"(?:[^"\\]|\\)*"', body):
            self.assertNotIn(".var", literal, "user data must survive an uninstall")


class HygieneTests(unittest.TestCase):
    def test_no_hard_coded_colours_were_added(self):
        for source in (CHOICE_SOURCE, FULL_VIEW_SOURCE, FULL_VIEW_TEMPLATE,
                       LIBRARY_SOURCE, WINDOW_SOURCE):
            for literal in re.findall(r'"(?:[^"\\]|\\)*"', source):
                self.assertNotRegex(literal, r"#[0-9a-fA-F]{3,8}\b")
                self.assertNotRegex(literal, r"rgba?\(")

    def test_no_systemd_no_daemon_and_no_bazaar_root(self):
        for source in (APPIMAGE_SOURCE, APPIMAGE_HEADER, CHOICE_SOURCE,
                       CHOICE_HEADER, FULL_VIEW_SOURCE):
            self.assertNotIn("systemd", source.lower())
            self.assertNotIn("daemon", source.lower())
        for source in (WINDOW_SOURCE, LIBRARY_SOURCE):
            for literal in re.findall(r'"(?:[^"\\]|\\)*"', source):
                self.assertNotIn("sudo", literal)
                self.assertNotIn("systemctl", literal)

    def test_the_release_is_documented(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("Recommended for you", changelog)
        metainfo = (ROOT / "data/io.github.crhy.SpacedBazaar.metainfo.xml.in").read_text(encoding="utf-8")
        self.assertIn('release version="0.1.16"', metainfo)


if __name__ == "__main__":
    unittest.main()
