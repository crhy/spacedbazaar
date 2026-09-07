"""Keep remote setup fail closed using a fake Flatpak command."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts/configure-spaced-github-remote.sh"


class ConfigureRemoteTests(unittest.TestCase):
    def run_configure(self, url="", failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flatpak = root / "flatpak"
            flatpak.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_LOG"
if [ "$1" = remotes ]; then
    if [ "$TEST_FAILURE" = 1 ]; then exit 1; fi
    if [ -n "$TEST_URL" ]; then printf 'spaced-github\\t%s\\n' "$TEST_URL"; fi
fi
""")
            flatpak.chmod(0o755)
            log = root / "commands"
            environment = os.environ.copy()
            environment.pop("FLATPAK_ID", None)
            environment.update(PATH=f"{root}:/usr/bin:/bin", TEST_LOG=str(log),
                               TEST_URL=url, TEST_FAILURE=str(int(failure)))
            result = subprocess.run(["sh", str(SCRIPT)], env=environment,
                                    capture_output=True, text=True)
            return result, log.read_text().splitlines()

    def test_unexpected_remote_is_not_enabled_or_modified(self):
        result, commands = self.run_configure("https://example.invalid/untrusted")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected URL", result.stderr)
        self.assertEqual(len(commands), 1)

    def test_failed_remote_listing_is_not_treated_as_missing(self):
        result, commands = self.run_configure(failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(commands), 1)

    def test_existing_canonical_remote_retains_signature_verification(self):
        result, commands = self.run_configure("https://crhy.github.io/spacedbazaar/flatpak-repo/")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("remote-modify --user --gpg-verify", commands[1])

    def test_missing_remote_uses_signed_descriptor(self):
        result, commands = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("remote-add --user --noninteractive", commands[1])
        self.assertTrue(commands[1].endswith("https://crhy.github.io/spacedbazaar/spaced-github.flatpakrepo"))


if __name__ == "__main__":
    unittest.main()
