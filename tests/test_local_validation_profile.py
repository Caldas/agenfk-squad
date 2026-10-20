"""Behavioral profile validation; no commands in a profile are ever executed."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

# Importing by absolute path must not leave private paths in bytecode artifacts.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("profile", ROOT / "scripts/local_validation_profile.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / "examples/local-validation/backend.json").read_text())

    def test_valid_backend(self):
        self.assertEqual(MODULE.validate(self.profile), self.profile)

    def test_web_mobile_recording_dependency(self):
        for stack in ("web", "mobile"):
            p = json.loads((ROOT / f"examples/local-validation/{stack}.json").read_text())
            MODULE.validate(p)
            for field, value in (("needs", ["unit"]), ("fixtures", [])):
                bad = copy.deepcopy(p)
                bad["steps"][-1][field] = value
                with self.assertRaises(MODULE.InvalidProfile):
                    MODULE.validate(bad)

    def test_canonical_paths(self):
        self.profile["steps"][0].update(cwd="checks/./", fixtures=["fixtures/./a"])
        MODULE.validate(self.profile)
        self.assertEqual(self.profile["steps"][0]["cwd"], "checks")
        self.assertEqual(self.profile["steps"][0]["fixtures"], ["fixtures/a"])
        self.profile["steps"][1]["evidence"] = "evidence/./static.json"
        with self.assertRaises(MODULE.InvalidProfile):
            MODULE.validate(self.profile)

    def test_path_command_boundaries(self):
        for field in ("cwd", "evidence", "fixtures"):
            for path in ("../a", "C:/a", "a\\\\b", "a\x7fb", "a\tb"):
                p = copy.deepcopy(self.profile)
                p["steps"][0][field] = [path] if field == "fixtures" else path
                with self.assertRaises(MODULE.InvalidProfile):
                    MODULE.validate(p)
        for argv in (["cmd.exe", "/c", "true"], ["busybox", "sh"], ["ash"],
                     ["python3", "-cpass"], ["node", "--eval=1"], ["node", "-p1"], ["node", "x\t"]):
            p = copy.deepcopy(self.profile)
            p["steps"][0]["argv"] = argv
            with self.assertRaises(MODULE.InvalidProfile):
                MODULE.validate(p)
        for field, value in (("evidence", "."), ("evidence", "./"), ("timeout_seconds", 901)):
            p = copy.deepcopy(self.profile)
            p["steps"][0][field] = value
            with self.assertRaises(MODULE.InvalidProfile):
                MODULE.validate(p)

    def test_invalid_contracts(self):
        mutations = {
            "version": lambda p: p.update(version=2),
            "unknown": lambda p: p.update(override=True),
            "missing gate": lambda p: p["steps"].pop(),
            "cycle": lambda p: p["steps"][0].update(needs=["integration"]),
            "unknown dependency": lambda p: p["steps"][0].update(needs=["absent"]),
            "shell": lambda p: p["steps"][0].update(argv=["bash", "-c", "true"]),
            "metacharacter": lambda p: p["steps"][0].update(argv=["python3", "x;rm"]),
            "traversal": lambda p: p["steps"][0].update(cwd="../elsewhere"),
            "absolute evidence": lambda p: p["steps"][0].update(evidence="/tmp/pass"),
            "unbounded": lambda p: p["budget"].update(wall_seconds=0),
            "infinite": lambda p: p["review"].update(max_cost_usd=float("inf")),
            "repair": lambda p: p["review"].update(max_repair_cycles=3),
            "model": lambda p: p["review"].update(model="deepseek/latest"),
            "execution llm": lambda p: p["budget"].update(llm_calls=1),
            "unknown outcome": lambda p: p["steps"][0]["outcomes"].append("SKIP"),
            "zero tests": lambda p: p["steps"][1].update(min_tests=0),
            "duplicate id": lambda p: p["steps"][1].update(id="static"),
            "boolean version": lambda p: p.update(version=True),
            "web missing UI": lambda p: p.update(stack="web"),
            "mobile missing emulator": lambda p: p.update(stack="mobile"),
            "weaken full suite": lambda p: p.update(full_suite=False),
            "unknown nested": lambda p: p["steps"][0].update(allow_failure=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                profile = copy.deepcopy(self.profile)
                mutate(profile)
                with self.assertRaises(MODULE.InvalidProfile):
                    MODULE.validate(profile)

    def test_cli_does_not_execute_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            profile.write_text(json.dumps(self.profile))
            command = [sys.executable, str(ROOT / "scripts/local_validation_profile.py"), str(profile)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)["execution"], "NOT_RUN")
            bad_field = copy.deepcopy(self.profile)
            bad_field["unknown"] = True
            bad_outcome = copy.deepcopy(self.profile)
            bad_outcome["steps"][0]["outcomes"].append("SKIP")
            for raw in ('{', '{"version":1,"version":1}', '{"version":NaN}',
                        '{"version":Infinity}', json.dumps(bad_field), json.dumps(bad_outcome)):
                profile.write_text(raw)
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)["result"], "INVALID_PROFILE")
            profile.unlink()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
