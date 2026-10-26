#!/usr/bin/env python3
"""The CI workflows keep running the tests that exist, on the systems the squad promises.

Self-checking: the exit code is the verdict. It reads .github/workflows as text (no YAML library needed) and
looks at steps, not at the file as a whole: what it guards is that a test file, a platform or a path filter
does not go missing without anyone noticing, and that a comment or a disabled step does not pass for a real one.
On Windows it also asks PowerShell's own parser whether install.ps1 and get.ps1 are valid scripts.

    python3 tests/test_ci_config.py
"""
import glob
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOWS = os.path.join(ROOT, ".github", "workflows")


def text(name):
    with open(os.path.join(FLOWS, name), encoding="utf-8") as fh:
        return fh.read()


TESTS = text("tests.yml")
INSTALLER = text("installer.yml")


def job(source, name):
    """The text of one job: from `  <name>:` to the next job (two-space indent) or the end."""
    m = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", source, re.S | re.M)
    assert m, f"no job {name}"
    return m.group(1)


def steps(source):
    """The steps that can run: comment lines gone, steps with `if: false` gone. A list of step texts."""
    body = source.split("\njobs:", 1)[1] if "\njobs:" in source else source
    body = "\n".join(line for line in body.split("\n") if not line.lstrip().startswith("#"))
    found = re.split(r"\n(?=      - )", body)
    return [step for step in found if "if: false" not in step and "if: ${{ false }}" not in step]


def test_the_windows_job_runs_the_whole_suite_on_a_windows_runner():
    win = job(TESTS, "windows")
    assert "runs-on: windows-latest" in win, win
    assert re.search(r"defaults:\n\s+run:\n\s+shell: bash", win), "the loop is POSIX shell syntax: Git Bash on the Windows runner"
    live = steps(win)
    loop = [st for st in live if "for t in tests/test_*.py; do" in st and 'python -B "$t"' in st]
    assert loop, "a live step loops over every test file by glob (the ones that are not for Windows skip themselves)"
    assert any("py_compile" in st and "hooks/*.py" in st for st in live), "the hooks are compiled on Windows"


def test_every_test_file_is_run_somewhere_on_linux():
    linux_steps = steps(job(TESTS, "watcher"))
    installer_steps = steps(INSTALLER)
    everywhere = [st for st in installer_steps if "runner.os == 'Windows'" not in st]
    ran = " ".join(linux_steps) + " " + " ".join(everywhere)
    missing = [os.path.basename(p) for p in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))
               if os.path.basename(p) not in ran]
    # the PowerShell installers say so and exit 0 on Linux, and run for real in the Windows-only installer step
    assert not missing, f"not run by a live step of the Linux job or the installer workflow: {missing}"
    win_only = " ".join(st for st in installer_steps if "runner.os == 'Windows'" in st)
    assert "test_install_ps1.py" in win_only and "test_get_ps1.py" in win_only, win_only


def test_every_test_path_the_workflows_name_exists():
    named = set(re.findall(r"tests/[A-Za-z0-9_]+\.py", TESTS + INSTALLER))
    gone = sorted(n for n in named if not os.path.isfile(os.path.join(ROOT, *n.split("/"))))
    assert not gone, gone


def test_the_installer_workflow_covers_windows_and_the_files_that_matter_there():
    assert "windows-latest" in INSTALLER, INSTALLER
    assert "timeout-minutes: ${{ matrix.os == 'windows-latest' && 30 || 10 }}" in INSTALLER, "PowerShell is slower: its own budget"
    filters = [block.split("\n\n")[0] for block in INSTALLER.split("    paths:\n")[1:]]
    assert len(filters) == 2, "one path filter under push and one under pull_request"
    for block in filters:
        for path in ("install.ps1", "get.ps1", "install.sh", "get.sh", "scripts/squad_settings.py", "hooks/manifest.json",
                     "tests/test_install_ps1.py", "tests/test_get_ps1.py", ".gitattributes"):
            assert f"      - {path}\n" in block + "\n", f"a change to {path} should run the installer workflow"


def test_the_private_path_check_is_the_script_not_a_one_line_grep():
    live = " ".join(steps(job(TESTS, "watcher")) + steps(job(TESTS, "windows")))
    assert live.count("python scripts/check_private_paths.py") == 2, "on Linux and on Windows"
    assert "grep -rnE '/home/" not in TESTS


def test_the_powershell_scripts_parse():
    if os.name != "nt":
        return        # PowerShell's own parser, on the platform that runs them
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        return
    for script in ("install.ps1", "get.ps1"):
        path = os.path.join(ROOT, script).replace("'", "''")
        cmd = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('" + path + "', [ref]$null, [ref]$e); "
               "if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }")
        r = subprocess.run([shell, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (script, r.stdout, r.stderr)


def test_the_workflows_are_valid_yaml_when_a_yaml_library_is_at_hand():
    try:
        import yaml
    except ImportError:
        print("skipped: no PyYAML here")
        return
    for name in ("tests.yml", "installer.yml"):
        doc = yaml.safe_load(text(name))
        assert isinstance(doc.get("jobs"), dict) and doc["jobs"], name


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
