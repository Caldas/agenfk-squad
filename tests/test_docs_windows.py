#!/usr/bin/env python3
"""The Windows documentation matches the installers it describes.

Self-checking: the exit code is the verdict. Reads docs/installation.md, README.md and ROADMAP.md as text and
checks the contract a reader depends on: the Windows section exists, every option, variable, script and URL it
cites is real (read from get.ps1, install.ps1 and scripts/squad_settings.py, not typed again here), the
limitations that are true on Windows are stated, the places that used to say "Linux only" no longer do, and the
relative links of the pages that changed lead somewhere.

    python3 tests/test_docs_windows.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


INSTALLATION = read("docs", "installation.md")
README = read("README.md")
ROADMAP = read("ROADMAP.md")
GET_PS1 = read("get.ps1")
INSTALL_PS1 = read("install.ps1")
SETTINGS_PY = read("scripts", "squad_settings.py")
CONFIGURATION = read("docs", "configuration.md")


def section(text, heading, level=2):
    """The body under `## heading` (or `###` with level=3), up to the next heading of the same or a higher level."""
    marks = "#" * level
    # a `# comment` inside a fenced block is not a heading: hide it from the search, keep the offsets
    masked = re.sub(r"```.*?```", lambda f: re.sub(r"(?m)^#", "~", f.group(0)), text, flags=re.S)
    m = re.search(rf"^{marks} {re.escape(heading)}\s*\n(.*?)(?=^#{{1,{level}}} |\Z)", masked, re.S | re.M)
    assert m, f"no `{marks} {heading}` in the text"
    return text[m.start(1):m.end(1)]


WINDOWS = section(INSTALLATION, "Windows")


def code_of(text):
    """Fenced blocks and inline code, the places where a command or an option is written."""
    fenced = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    inline = re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))
    return "\n".join(fenced + inline)


def params(script):
    """The parameter names a PowerShell script declares: [switch]$Name, [string]$Name."""
    return set(re.findall(r"\[(?:switch|string|bool)\]\$([A-Za-z]+)", script))


def test_windows_section_exists_and_has_the_parts_a_reader_follows():
    names = re.findall(r"^### (.+)$", WINDOWS, re.M)
    for wanted in ("Requirements on Windows", "Install on Windows", "Update on Windows", "Uninstall on Windows",
                   "Known limitations on Windows", "WSL"):
        assert wanted in names, (wanted, names)


def test_requirements_name_what_trips_people_on_a_stock_windows():
    reqs = section(WINDOWS, "Requirements on Windows", level=3)
    for needle in ("Python 3.10", "git", "Microsoft Store", "python3", "PowerShell 5.1", "Developer Mode", "autocrlf"):
        assert needle in reqs, f"the requirements do not mention {needle!r}"


def test_the_requirements_table_no_longer_says_linux_or_macos_only():
    table = section(INSTALLATION, "Requirements")
    assert "| Linux or macOS |" not in table, "the row that excluded Windows is still there"
    assert "Windows 10" in table or "Windows 11" in table, table
    assert "msvcrt" in table or "file locking" in table.lower(), table


def test_every_option_the_section_cites_is_a_real_parameter():
    cited = set(re.findall(r"(?<![\w-])-([A-Z][A-Za-z]+)\b", code_of(WINDOWS)))
    assert cited, "the section cites no option at all"
    real = params(GET_PS1) | params(INSTALL_PS1)
    shell_flags = {"File", "NoProfile", "ExecutionPolicy", "Scope", "Force", "Recurse", "Path", "Command"}
    unknown = sorted(c for c in cited if c not in real and c not in shell_flags)
    assert not unknown, f"cited but declared by neither get.ps1 nor install.ps1: {unknown}"
    for must in ("Beta", "Ref", "Uninstall", "Purge", "NoSymlink"):
        assert must in cited, f"the section never shows -{must}"


def test_every_variable_the_section_cites_exists():
    cited = set(re.findall(r"\b(SQUAD_[A-Z_]+|CLAUDE_CONFIG_DIR)\b", WINDOWS))
    assert {"SQUAD_HOME", "SQUAD_PYTHON", "CLAUDE_CONFIG_DIR"} <= cited, cited
    for name in sorted(cited):
        assert name in GET_PS1 or name in INSTALL_PS1 or name in CONFIGURATION, f"{name} is documented but no script reads it"


def test_the_one_line_installer_is_the_url_get_ps1_itself_gives():
    url = re.search(r"\$GetUrl = '([^']+)'", GET_PS1).group(1)
    assert url in WINDOWS, f"the section does not show {url}"
    assert re.search(re.escape(url) + r"\s*\|\s*iex", WINDOWS), "the irm | iex form is missing"
    assert "[scriptblock]::Create" in WINDOWS, "the form that takes options (-Beta, -Uninstall) is missing"


def test_every_repository_path_the_section_cites_exists():
    cited = re.findall(r"\b((?:scripts|hooks|tests|docs|skills)[\\/][\w./\\-]+\.(?:py|ps1|md|json)|install\.ps1|get\.ps1)", WINDOWS)
    assert cited, "the section cites no file of the repository"
    missing = sorted({p for p in cited if not os.path.exists(os.path.join(ROOT, *re.split(r"[\\/]", p)))})
    assert not missing, f"cited but not in the repository: {missing}"


def test_the_settings_script_actions_the_section_uses_are_real():
    actions = set(re.findall(r"squad_settings\.py\s+(\w+)", WINDOWS))
    assert actions, "the section never says how to register the hooks by hand"
    real = set(re.search(r'choices=\[([^\]]+)\]', SETTINGS_PY).group(1).replace('"', "").replace(" ", "").split(","))
    assert actions <= real, (actions, real)


def test_the_limitations_that_are_true_on_windows_are_stated():
    lim = section(WINDOWS, "Known limitations on Windows", level=3)
    for needle in ("herdr", "/clear", "/clear-pickup pickup", "chmod", "copies.txt", "marked copy",
                   "Developer Mode", "renormalize"):
        assert needle in lim, f"the limitations do not mention {needle!r}"


def test_the_install_part_says_how_squad_turn_and_the_hooks_look_on_windows():
    for needle in ("squad-turn.cmd", "PATH", "forward slashes", "Store stub"):
        assert needle in WINDOWS, f"the Windows section does not mention {needle!r}"


def test_the_locations_stated_are_the_ones_the_scripts_use():
    assert r"%USERPROFILE%\.local\share\agenfk-squad" in WINDOWS
    assert "'.local' + chr(92)" not in GET_PS1 and ".local" + chr(92) + "share" + chr(92) + "agenfk-squad" in GET_PS1, "get.ps1 moved the clone"
    assert r"%USERPROFILE%\.local\bin" in WINDOWS and "'squad-turn.cmd'" in INSTALL_PS1
    assert "copies.txt" in WINDOWS and "'copies.txt'" in INSTALL_PS1


def test_the_python_fallback_sentence_is_what_get_ps1_does():
    reqs = section(WINDOWS, "Requirements on Windows", level=3)
    assert "SQUAD_PYTHON" in reqs and "py -3" in reqs and "stops" in reqs
    assert "interpreter it runs under" not in reqs, "only the hook command falls back to that, not the installer"
    assert "'py', '-3'" in GET_PS1 and "SQUAD_PYTHON" in GET_PS1


def test_a_stock_windows_can_follow_the_install_commands():
    install = section(WINDOWS, "Install on Windows", level=3)
    assert "Set-ExecutionPolicy -Scope Process" in install, "get.ps1 runs install.ps1, a script file: Restricted blocks it"
    assert "& (Join-Path $Dir 'install.ps1')" in GET_PS1, "if get.ps1 stops running a script file, this note can go"
    assert "same option" in section(WINDOWS, "Update on Windows", level=3), "a plain re-run means -Stable"


def test_the_wsl_note_says_which_claude_code_it_is_for():
    wsl = section(WINDOWS, "WSL", level=3)
    assert "install.sh" in wsl or "get.sh" in wsl, "WSL uses the Linux installer"
    assert "inside WSL" in wsl or "in WSL" in wsl, wsl
    assert "USERPROFILE" in wsl or "separate" in wsl, "the two homes are different: say so"


def test_no_page_still_says_windows_is_unsupported():
    assert "Windows: not supported" not in ROADMAP, "ROADMAP still lists Windows as unsupported"
    status = section(README, "Status")
    assert "Windows" in status, "README's Status does not say where it runs now"
    for text in (INSTALLATION, README):
        assert "| Linux or macOS |" not in text


def test_the_readme_quickstart_has_a_windows_path_and_links_the_section():
    quick = section(README, "Quickstart")
    assert "get.ps1" in quick or "Windows" in quick, "the quickstart has no Windows line"
    assert "docs/installation.md#windows" in README, "README does not link the Windows section"


def slug(heading):
    s = re.sub(r"[^\w\- ]", "", heading.lower()).strip()
    return re.sub(r"\s", "-", s)


def anchors(text):
    return {slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}


def test_relative_links_of_the_changed_pages_resolve():
    pages = {"README.md": README, os.path.join("docs", "installation.md"): INSTALLATION, "ROADMAP.md": ROADMAP}
    for rel, text in pages.items():
        base = os.path.dirname(os.path.join(ROOT, rel))
        for target, frag in re.findall(r"\]\((?!https?:|mailto:)([^)#\s]*)(?:#([^)\s]*))?\)", text):
            path = os.path.normpath(os.path.join(base, target)) if target else os.path.join(ROOT, rel)
            assert os.path.exists(path), f"{rel}: link to {target!r} leads nowhere"
            if frag and path.endswith(".md"):
                with open(path, encoding="utf-8") as fh:
                    assert frag in anchors(fh.read()), f"{rel}: {target}#{frag} has no such heading"


def test_the_docs_hold_no_real_person_s_home_directory():
    for name, text in (("installation.md", WINDOWS), ("README.md", README), ("ROADMAP.md", ROADMAP)):
        assert not re.search(r"[A-Za-z]:\\Users\\(?!<)[A-Za-z]", text), f"{name} shows a real profile path"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
