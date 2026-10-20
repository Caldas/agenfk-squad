"""Run the Pi compatibility contract tests with the locally installed Pi runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


class PiCompatibilityTests(unittest.TestCase):
    def test_pi_compatibility_contract(self):
        pi = shutil.which("pi")
        root = Path(pi).resolve().parent if pi else None
        if root:
            while root != root.parent and not (root / "package.json").is_file():
                root = root.parent
        # AgenFK's long-running server may not inherit an interactive NVM PATH.
        # Locate the actual installed package/runtime, without skipping its tests.
        if not root or not (root / "package.json").is_file():
            explicit = os.environ.get("PI_COMPAT_PI_ROOT")
            candidates = ([Path(explicit)] if explicit else []) + sorted(
                Path.home().glob(".nvm/versions/node/*/lib/node_modules/@earendil-works/pi-coding-agent"),
                key=lambda path: (path / "package.json").stat().st_mtime,
                reverse=True,
            )
            root = next((path for path in candidates if (path / "package.json").is_file()), None)
        self.assertIsNotNone(root, "Pi must be installed to validate the compatibility adapter")
        bundled_node = root.parents[3] / "bin/node"
        node = str(bundled_node) if bundled_node.is_file() else shutil.which("node")
        self.assertIsNotNone(node, "The installed Pi Node runtime must be available")
        env = dict(os.environ, PI_COMPAT_PI_ROOT=str(root))
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        repo = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [node, "--test", str(repo / "pi-compat/test.mjs"), str(repo / "pi-compat/usage-dashboard.test.mjs"), str(repo / "pi-compat/vigia.test.mjs")],
            cwd=repo, env=env, text=True, capture_output=True, timeout=120,
        )
        print(result.stdout)
        if result.returncode:
            print(result.stderr)
        self.assertEqual(result.returncode, 0, "Pi compatibility contract tests failed")


if __name__ == "__main__":
    unittest.main()
