"""Optional offline Pi contracts; PI_COMPAT_REQUIRE=1 makes missing runtime fatal."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


PI_PACKAGE = "@earendil-works/pi-coding-agent"


def is_pi_root(path):
    try:
        return json.loads((path / "package.json").read_text())["name"] == PI_PACKAGE
    except (OSError, ValueError, KeyError, TypeError):
        return False


def find_pi_root():
    explicit = os.environ.get("PI_COMPAT_PI_ROOT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not is_pi_root(root):
            raise ValueError("PI_COMPAT_PI_ROOT must point to the Pi package directory")
        return root
    executable = shutil.which("pi")
    if executable:
        for candidate in Path(executable).resolve().parents:
            if is_pi_root(candidate):
                return candidate
    # Long-running gate servers may not inherit an interactive NVM PATH.
    candidates = Path.home().glob(".nvm/versions/node/*/lib/node_modules/" + PI_PACKAGE)
    roots = [path for path in candidates if is_pi_root(path)]
    return max(roots, key=lambda path: (path / "package.json").stat().st_mtime, default=None)


class PiCompatibilityTests(unittest.TestCase):
    def test_pi_compatibility_contract(self):
        root = find_pi_root()
        if root is None:
            message = "Pi contracts need the installed " + PI_PACKAGE + " runtime"
            if os.environ.get("PI_COMPAT_REQUIRE") == "1":
                self.fail(message)
            self.skipTest(message + "; set PI_COMPAT_REQUIRE=1 to require them")
        bundled_node = root.parents[3] / "bin/node" if len(root.parents) > 3 else None
        node = str(bundled_node) if bundled_node and bundled_node.is_file() else shutil.which("node")
        self.assertIsNotNone(node, "The Pi Node runtime must be available")
        env = dict(os.environ, PI_COMPAT_PI_ROOT=str(root))
        env.pop("PI_CLAUDE_CHILD_DEPTH", None)  # Contract fixtures are independent parents.
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        repo = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [node, "--test", *(str(repo / "pi-compat" / name) for name in
                              ["test.mjs", "usage-dashboard.test.mjs", "vigia.test.mjs"])],
            cwd=repo, env=env, text=True, capture_output=True, timeout=120,
        )
        print(result.stdout)
        if result.returncode:
            print(result.stderr)
        self.assertEqual(result.returncode, 0, "Pi compatibility contract tests failed")


if __name__ == "__main__":
    unittest.main()
