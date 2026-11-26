"""crhy/spacedbazaar#35: Bazaar offers AppImages and picks the format that runs best.

The tests read the C, Blueprint and JSON sources: the machine this runs on has
no glib, no GTK and no meson, so the sources are the thing under test.
"""

from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).parents[1]
APPIMAGE_HEADER = (ROOT / "src/bz-appimage-source.h").read_text(encoding="utf-8")
APPIMAGE_SOURCE = (ROOT / "src/bz-appimage-source.c").read_text(encoding="utf-8")
CHOICE_HEADER = (ROOT / "src/bz-format-choice.h").read_text(encoding="utf-8")
CHOICE_SOURCE = (ROOT / "src/bz-format-choice.c").read_text(encoding="utf-8")
GROUP_HEADER = (ROOT / "src/bz-entry-group.h").read_text(encoding="utf-8")
GROUP_SOURCE = (ROOT / "src/bz-entry-group.c").read_text(encoding="utf-8")
FULL_VIEW_TEMPLATE = (ROOT / "src/bz-full-view.blp").read_text(encoding="utf-8")
FULL_VIEW_SOURCE = (ROOT / "src/bz-full-view.c").read_text(encoding="utf-8")
INSTALL_CONTROLS = (ROOT / "src/bz-install-controls.c").read_text(encoding="utf-8")
WINDOW = (ROOT / "src/bz-window.c").read_text(encoding="utf-8")
SRC_MESON = (ROOT / "src/meson.build").read_text(encoding="utf-8")
ROOT_MESON = (ROOT / "meson.build").read_text(encoding="utf-8")
POTFILES = (ROOT / "po/POTFILES.in").read_text(encoding="utf-8")
ADVICE = json.loads((ROOT / "data/format-advice.json").read_text(encoding="utf-8"))
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

FORMATS = ("apt", "flatpak", "appimage")


def function_body(source: str, name: str) -> str:
    """The definition of a GNU-style function, not a declaration or a call.

    Definitions start at column 0; call sites are indented, and declarations
    end with a semicolon before their body would open.
    """
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


def string_literals(source: str) -> list[str]:
    return re.findall(r'"(?:[^"\\]|\\)*"', source)


def advice_entries() -> list[dict]:
    return ADVICE["advice"]


class ModuleShapeTests(unittest.TestCase):
    def test_both_modules_exist_and_are_built(self):
        for name in ("bz-appimage-source", "bz-format-choice"):
            self.assertIn(f"'{name}.c'", SRC_MESON)
            self.assertIn(f"src/{name}.c", POTFILES)
            self.assertIn(name.replace("-", "_"), APPIMAGE_SOURCE + CHOICE_SOURCE)

    def test_the_three_formats_are_named_once(self):
        table = re.search(r"format_names\[\] = \{(.*?)\n\};", CHOICE_SOURCE, re.S)
        assert table is not None, "no format table in src/bz-format-choice.c"
        rows = re.findall(r"\{([^{}]*)\}", table.group(1), re.S)
        self.assertEqual(len(rows), 3)
        names = [re.search(r'"([a-z]+)"', row).group(1) for row in rows]
        self.assertEqual(sorted(names), sorted(FORMATS))

    def test_apt_and_appimage_are_declared_not_sandboxed(self):
        table = re.search(r"format_names\[\] = \{(.*?)\n\};", CHOICE_SOURCE, re.S)
        rows = re.findall(r"\{([^{}]*)\}", table.group(1), re.S)
        for row in rows:
            label = re.search(r'"([a-z]+)"', row).group(1)
            sandboxed = "TRUE" if "TRUE" in row else "FALSE"
            if label == "flatpak":
                self.assertEqual(sandboxed, "TRUE", row)
            else:
                self.assertEqual(sandboxed, "FALSE", row)

    def test_curated_advice_outranks_every_other_signal(self):
        weights = {
            name: int(value)
            for name, value in re.findall(
                r"#define (ADVICE|INSTALLED|NEWEST|KNOWN_VERSION|SANDBOX)_WEIGHT (\d+)",
                CHOICE_SOURCE)
        }
        self.assertEqual(set(weights),
                        {"ADVICE", "INSTALLED", "NEWEST", "KNOWN_VERSION", "SANDBOX"})
        advice = weights["ADVICE"]
        others = sum(v for k, v in weights.items() if k != "ADVICE")
        self.assertGreater(advice, others,
                           "curated advice must win over the sum of everything else")


class AppImageDiscoveryTests(unittest.TestCase):
    def test_only_a_finished_x86_64_appimage_is_offered(self):
        self.assertIn('".AppImage"', APPIMAGE_SOURCE)
        self.assertIn("x86_64", APPIMAGE_SOURCE)
        for rejected in (".zsync", ".asc", ".sig"):
            self.assertIn(f'"{rejected}"', APPIMAGE_SOURCE)
        self.assertIn("aarch64", APPIMAGE_SOURCE)

    def test_stable_releases_are_considered_before_prereleases(self):
        body = function_body(APPIMAGE_SOURCE, "bz_appimage_release_from_json")
        first = body.index("release_from_releases (releases, app_id, owner_repo, FALSE")
        second = body.index("release_from_releases (releases, app_id, owner_repo, TRUE")
        self.assertLess(first, second)

    def test_drafts_are_never_offered(self):
        self.assertIn('"draft"', APPIMAGE_SOURCE)

    def test_a_published_sha256_is_required(self):
        self.assertIn("BZ_APPIMAGE_ERROR_NO_PUBLISHED_SHA256", APPIMAGE_HEADER)
        self.assertIn("bz_appimage_dup_sha256sums_asset_name", APPIMAGE_SOURCE)
        self.assertIn("SHA256SUMS", APPIMAGE_SOURCE)
        self.assertIn("bz_appimage_lookup_published_sha256", APPIMAGE_SOURCE)

    def test_the_downloaded_bytes_are_refused_when_the_hash_does_not_match(self):
        body = function_body(APPIMAGE_SOURCE, "install_appimage_fiber")
        mismatch = body.index("BZ_APPIMAGE_ERROR_SHA256_MISMATCH")
        written = body.index("write_bytes_to_path (install_path")
        self.assertLess(mismatch, written,
                        "nothing may be written before the digest is compared")
        self.assertIn("nothing was installed", body)

    def test_the_digest_is_computed_from_the_fetched_bytes(self):
        body = function_body(APPIMAGE_SOURCE, "install_appimage_fiber")
        self.assertIn("g_checksum_new (G_CHECKSUM_SHA256)", body)
        self.assertIn("bz_appimage_sha256_matches (published, computed)", body)

    def test_the_appimage_lands_in_applications_and_gets_a_launcher_and_icon(self):
        self.assertIn('g_build_filename (g_get_home_dir (), "Applications", NULL)',
                      APPIMAGE_SOURCE)
        self.assertIn("bz_appimage_dup_desktop_path", APPIMAGE_SOURCE)
        self.assertIn("bz_appimage_dup_icon_path", APPIMAGE_SOURCE)
        contents = function_body(APPIMAGE_SOURCE, "bz_appimage_dup_desktop_contents")
        self.assertIn("(AppImage)", contents)
        self.assertIn("[Desktop Entry]", contents)

    def test_uninstall_removes_only_what_it_installed(self):
        paths = function_body(APPIMAGE_SOURCE, "bz_appimage_dup_uninstall_paths")
        self.assertIn("bz_appimage_dup_desktop_path (app_id)", paths)
        self.assertIn("bz_appimage_dup_icon_path (app_id)", paths)
        body = function_body(APPIMAGE_SOURCE, "uninstall_appimage_fiber")
        self.assertIn("bz_appimage_dup_uninstall_paths", body)
        self.assertIn("g_remove (path)", body)
        for literal in string_literals(body):
            self.assertNotIn(".var", literal, "user data must survive an uninstall")

    def test_asset_names_cannot_escape_the_applications_directory(self):
        body = function_body(APPIMAGE_SOURCE, "bz_appimage_asset_name_is_safe")
        self.assertIn("strchr (asset_name, '/')", body)
        self.assertIn("g_ascii_iscntrl", body)
        install = function_body(APPIMAGE_SOURCE, "bz_appimage_dup_install_path")
        self.assertIn("bz_appimage_asset_name_is_safe (asset_name)", install)


class FormatChoiceTests(unittest.TestCase):
    def test_the_group_exposes_the_choice(self):
        self.assertIn("bz_entry_group_get_format_choice", GROUP_HEADER)
        self.assertRegex(
            GROUP_SOURCE,
            re.compile(
                r"bz_entry_group_get_format_choice \(BzEntryGroup \*self,\s*"
                r"const char\s+\*override,\s*"
                r"GError\s+\*\*error\)",
                re.S,
            ),
        )

    def test_the_group_offers_all_three_builds(self):
        body = function_body(GROUP_SOURCE, "bz_entry_group_get_format_choice")
        for fmt in FORMATS:
            self.assertIn(f"offers[BZ_FORMAT_CHOICE_FORMAT_{fmt.upper()}]", body)
        self.assertIn("bz_format_choice_evaluate (app_id, offers, override, error)",
                      body)

    def test_the_user_override_wins(self):
        body = function_body(CHOICE_SOURCE, "bz_format_choice_evaluate")
        override = body.index("bz_format_choice_parse_format (override)")
        fallback = body.index("choice->pick = pick;")
        self.assertLess(override, fallback)
        self.assertIn("choice->overridden = TRUE", body)
        self.assertIn("offers[chosen].available", body,
                      "an override may only pick a build that exists")

    def test_existing_installs_are_part_of_the_score(self):
        self.assertIn("INSTALLED_WEIGHT", CHOICE_SOURCE)
        self.assertIn("bz_format_choice_apt_package_is_installed", CHOICE_SOURCE)
        self.assertIn("bz_appimage_is_installed (app_id)", GROUP_SOURCE)
        self.assertIn("bz_entry_group_get_removable (self) > 0", GROUP_SOURCE)

    def test_sandboxing_is_said_plainly(self):
        self.assertIn('_ ("not sandboxed")', CHOICE_SOURCE)
        self.assertIn("_ (\"sandboxed\")", CHOICE_SOURCE)
        self.assertIn("That build is not sandboxed.", INSTALL_CONTROLS)
        self.assertIn("That build is not sandboxed.", WINDOW)

    def test_the_advice_file_is_installed_and_reachable(self):
        self.assertIn("install_data(", ROOT_MESON)
        self.assertRegex(
            ROOT_MESON,
            re.compile(r"install_data\(\s*'data/format-advice.json',\s*"
                       r"install_dir: get_option\('datadir'\) / 'bazaar',",
                       re.S),
        )
        self.assertIn("config_h.set_quoted('FORMAT_ADVICE_PATH'", ROOT_MESON)
        self.assertIn("FORMAT_ADVICE_PATH", CHOICE_SOURCE)

    def test_the_advice_json_parses_and_names_freeCAD(self):
        self.assertEqual(ADVICE["version"], 1)
        rows = advice_entries()
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertRegex(row["app_id"], r"^[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+$")
            self.assertIn(row["pick"], FORMATS)
            self.assertTrue(row["reason"].strip())
            self.assertNotIn("\n", row["reason"])
        ids = [row["app_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate app ids: {ids}")

    def test_freeCAD_is_offered_as_the_appimage_with_the_investigated_reason(self):
        rows = {row["app_id"]: row for row in advice_entries()}
        freecad = [row for app_id, row in rows.items() if "FreeCAD" in app_id]
        self.assertEqual(len(freecad), 1, "exactly one FreeCAD line is expected")
        self.assertEqual(freecad[0]["pick"], "appimage")
        self.assertIn("flatpak", freecad[0]["reason"])
        self.assertIn("under investigation", freecad[0]["reason"])

    def test_nothing_is_advised_for_an_app_without_evidence(self):
        for row in advice_entries():
            self.assertNotIn("probably", row["reason"].lower())
            self.assertNotIn("maybe", row["reason"].lower())


class AppPageTests(unittest.TestCase):
    def test_the_app_page_shows_every_format_side_by_side(self):
        row_box = FULL_VIEW_TEMPLATE.split("other_formats_box", 1)[1].split("Box context_bar", 1)[0]
        self.assertIn('label: _("Other ways to install");', row_box)
        for fmt in FORMATS:
            self.assertIn(f"Box other_{fmt}_row", row_box)
            self.assertIn(
                f'label: bind $other_summary(template.entry-group '
                f'as <$BzEntryGroup>, "{fmt}") as <string>;',
                row_box,
            )
        card = FULL_VIEW_TEMPLATE.split("Box recommendation_card", 1)[1].split("Box other_formats_box", 1)[0]
        self.assertIn("recommend_install_button", card)

    def test_a_row_hides_itself_when_that_build_does_not_exist(self):
        for fmt in FORMATS:
            self.assertIn(
                f'visible: bind $other_has_format(template.entry-group '
                f'as <$BzEntryGroup>, "{fmt}") as <bool>;',
                FULL_VIEW_TEMPLATE,
            )

    def test_the_page_registers_the_callbacks(self):
        for callback in ("other_formats_exists", "other_has_format",
                         "other_summary"):
            self.assertIn(
                "gtk_widget_class_bind_template_callback (widget_class, "
                f"{callback});",
                FULL_VIEW_SOURCE,
            )

    def test_the_headline_names_the_recommended_build(self):
        card = FULL_VIEW_TEMPLATE.split("Box recommendation_card", 1)[1].split("Box other_formats_box", 1)[0]
        self.assertIn('label: _("Recommended for you");', card)
        self.assertIn('_ ("Install %s")', FULL_VIEW_SOURCE)


class InstallTimeTests(unittest.TestCase):
    def test_the_install_button_names_the_recommended_build(self):
        self.assertIn("set_install_btn_tooltip (self);", INSTALL_CONTROLS)
        self.assertIn("bz_entry_group_get_format_choice", INSTALL_CONTROLS)

    def test_the_window_says_it_before_starting_the_install(self):
        action = function_body(WINDOW, "action_install_group")
        self.assertLess(
            action.index("notify_format_choice (self, group);"),
            action.index("try_transact ("),
        )

    def test_no_message_claims_bazaar_installed_another_format(self):
        # Bazaar installs the format the user asked for; the listings only
        # name the other builds, so no listing string may read as if one had
        # already been installed. The override paths the user presses do
        # report their own result and are excluded from the scan.
        window = WINDOW
        for name in ("install_appimage_choice_fiber", "action_install_format"):
            window = window.replace(function_body(window, name), "")
        for source in (FULL_VIEW_SOURCE, INSTALL_CONTROLS, window):
            for literal in string_literals(source):
                if "AppImage" not in literal and "apt" not in literal:
                    continue
                self.assertNotRegex(literal.lower(), r"installed (the|an|this)")
                self.assertNotRegex(literal.lower(), r"was installed")

    def test_the_flatpak_build_stays_the_one_bazaar_installs(self):
        self.assertIn("Bazaar installs the Flatpak build.", INSTALL_CONTROLS)
        self.assertIn("Bazaar installs the Flatpak build.", WINDOW)


class ThemeAndHygieneTests(unittest.TestCase):
    def test_no_hard_coded_colours_were_added(self):
        for source in (APPIMAGE_SOURCE, CHOICE_SOURCE, FULL_VIEW_SOURCE,
                       FULL_VIEW_TEMPLATE, GROUP_SOURCE, INSTALL_CONTROLS):
            for literal in string_literals(source):
                self.assertNotRegex(literal, r"#[0-9a-fA-F]{3,8}\b")
                self.assertNotRegex(literal, r"rgba?\(")

    def test_no_systemd_and_no_new_daemon_are_introduced(self):
        for source in (APPIMAGE_SOURCE, APPIMAGE_HEADER, CHOICE_SOURCE,
                       CHOICE_HEADER, GROUP_SOURCE, FULL_VIEW_SOURCE):
            self.assertNotIn("systemd", source.lower())
            self.assertNotIn("daemon", source.lower())

    def test_the_change_is_documented(self):
        self.assertIn("AppImage", CHANGELOG)
        self.assertIn("format", CHANGELOG.lower())
        self.assertIn("AppImage", README)


if __name__ == "__main__":
    unittest.main()
