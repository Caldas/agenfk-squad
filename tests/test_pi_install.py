"""Pi-only install isolation and backups; no Pi, Node or network required."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parent.parent


class PiInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="squad-pi-install-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.agent = self.home / "pi agent"
        self.bin = self.home / "bin"
        self.bin.mkdir()
        for command in ("omp", "agenfk"):
            target = self.bin / command
            target.write_text('#!/bin/sh\nprintf called > "$HOME/legacy-called"\nexit 99\n')
            target.chmod(0o700)
        self.env = dict(os.environ, HOME=str(self.home), PI_CODING_AGENT_DIR=str(self.agent),
                        CLAUDE_CONFIG_DIR=str(self.home / "claude-custom"))
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")

    def install(self, *args, script=None):
        return subprocess.run(["bash", str(script or REPO / "install.sh"), "--pi", *args],
                              env=self.env, cwd=REPO, text=True, capture_output=True, timeout=15)

    def test_pi_install_never_touches_claude_omp_or_the_merge_queue(self):
        for directory in (".claude", ".omp", "claude-custom"):
            (self.home / directory).mkdir()
            (self.home / directory / "sentinel").write_text(directory)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / "legacy-called").exists())
        self.assertFalse((self.home / ".local").exists())
        for directory in (".claude", ".omp", "claude-custom"):
            self.assertEqual(list((self.home / directory).iterdir()), [self.home / directory / "sentinel"])
            self.assertEqual((self.home / directory / "sentinel").read_text(), directory)
        config = self.agent / "claude-compat.json"
        self.assertEqual(json.loads(config.read_text())["swarmRoot"], str(REPO))
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        for name in ("claude-skills.ts", "usage-dashboard.ts"):
            self.assertIn(str(REPO / "pi-compat"), (self.agent / "extensions" / name).read_text())

    def test_existing_extensions_and_configuration_are_backed_up(self):
        extensions = self.agent / "extensions"
        extensions.mkdir(parents=True)
        original = self.home / "original.ts"
        original.write_text("original extension")
        (extensions / "claude-skills.ts").symlink_to(original)
        (extensions / "usage-dashboard.ts").write_text("original dashboard")
        config = self.agent / "claude-compat.json"
        previous = {"enabledHookCommands": ["a reviewed command"], "vigia": {"enabled": False}}
        config.write_text(json.dumps(previous))
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        backup = next((self.agent / "backups").iterdir())
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / "claude-skills.ts").read_text(), original.read_text())
        self.assertEqual((backup / "usage-dashboard.ts").read_text(), "original dashboard")
        self.assertEqual(json.loads((backup / "claude-compat.json").read_text()), previous)
        self.assertEqual(original.read_text(), "original extension")
        self.assertFalse((extensions / "claude-skills.ts").is_symlink())
        updated = json.loads(config.read_text())
        for key, value in previous.items():
            self.assertEqual(updated[key], value)
        # Restoring the printed backup recovers original extension/config contents.
        for name in ("claude-skills.ts", "usage-dashboard.ts"):
            (extensions / name).write_bytes((backup / name).read_bytes())
        config.write_bytes((backup / "claude-compat.json").read_bytes())
        self.assertEqual((extensions / "claude-skills.ts").read_text(), "original extension")
        self.assertEqual(json.loads(config.read_text()), previous)

    def test_malformed_configuration_does_not_overwrite_an_extension(self):
        extensions = self.agent / "extensions"
        extensions.mkdir(parents=True)
        (extensions / "claude-skills.ts").write_text("keep me")
        (self.agent / "claude-compat.json").write_text("[]")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((extensions / "claude-skills.ts").read_text(), "keep me")
        self.assertEqual((self.agent / "claude-compat.json").read_text(), "[]")

    def test_unrecognized_pi_options_fail_before_creating_directories(self):
        result = self.install("--unknown")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.agent.exists())
        self.assertFalse((self.home / "legacy-called").exists())

    def test_missing_pi_is_explicitly_skipped_unless_required(self):
        env = dict(self.env, PATH=str(self.bin), PI_COMPAT_REQUIRE="0", PYTHONDONTWRITEBYTECODE="1")
        env.pop("PI_COMPAT_PI_ROOT", None)
        command = [sys.executable, str(REPO / "tests/test_pi_compat.py")]
        optional = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(optional.returncode, 0, optional.stderr)
        self.assertIn("skipped=1", optional.stderr)
        env["PI_COMPAT_REQUIRE"] = "1"
        required = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
        self.assertNotEqual(required.returncode, 0)
        self.assertIn("Pi contracts need the installed", required.stderr)

    def test_invalid_explicit_pi_root_is_an_error_not_a_skip(self):
        env = dict(self.env, PI_COMPAT_PI_ROOT=str(self.home / "missing-runtime"),
                   PI_COMPAT_REQUIRE="0", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, str(REPO / "tests/test_pi_compat.py")],
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PI_COMPAT_PI_ROOT must point", result.stderr)
        self.assertNotIn("skipped=1", result.stderr)

    def test_checkout_and_destination_paths_with_spaces_are_valid(self):
        checkout = self.home / "checkout with spaces"
        checkout.symlink_to(REPO, target_is_directory=True)
        result = self.install(script=checkout / "install.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads((self.agent / "claude-compat.json").read_text())
        self.assertEqual(Path(config["swarmRoot"]).resolve(), REPO)
        text = (self.agent / "extensions" / "claude-skills.ts").read_text()
        self.assertIn("checkout with spaces", text)


if __name__ == "__main__":
    unittest.main()
