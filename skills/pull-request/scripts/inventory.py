#!/usr/bin/env python3
"""List the resources and functions a branch creates, deletes or changes.

    inventory.py [--repo DIR] [--base REF] [--diff FILE] [--format markdown|json] [--lang en|pt]

Reads `git diff <base>...HEAD` (or a saved diff) and matches declaration lines:
Terraform `resource`, `data` and `module` blocks, and function definitions in
Python, JavaScript/TypeScript, Go, shell, PowerShell, Rust, C# and Java. A name
declared on both sides of the diff is `changed`. It sees declarations, not
bodies: a resource whose arguments changed without its header line changing
only shows up in `terraform plan`, which stays the source of the
before-and-after table.

Standard library only. Run it with `python3 -I`.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SAFE_REF = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./-]*")
DEFAULT_BASES = ("origin/HEAD", "origin/main", "main", "origin/master", "master")
TF_EXT = (".tf", ".hcl")
TF_PATTERNS = (
    (re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"'), lambda m: f"{m[1]}.{m[2]}"),
    (re.compile(r'^\s*data\s+"([^"]+)"\s+"([^"]+)"'), lambda m: f"data.{m[1]}.{m[2]}"),
    (re.compile(r'^\s*module\s+"([^"]+)"'), lambda m: f"module.{m[1]}"),
)
FUNCTION_PATTERNS = {
    (".py",): [re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")],
    (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"): [
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\("),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|\w+)\s*(?::\s*[^=]+)?=>"),
    ],
    (".go",): [re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(")],
    (".sh", ".bash"): [re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{?\s*$"),
                       re.compile(r"^\s*function\s+([A-Za-z_][\w-]*)\s*\{?\s*$")],
    (".ps1", ".psm1"): [re.compile(r"^\s*function\s+([\w-]+)", re.I)],
    (".rs",): [re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)")],
    (".cs", ".java"): [re.compile(
        r"^\s*(?:public|private|protected|internal)(?:\s+(?:static|async|virtual|override|final|abstract|sealed))*"
        r"\s+[\w<>\[\],.?]+\s+(\w+)\s*\(")],
}


def _functions_for(path):
    for exts, patterns in FUNCTION_PATTERNS.items():
        if path.endswith(exts):
            return patterns
    return []


def _declarations(line, path):
    if path.endswith(TF_EXT):
        for pattern, name in TF_PATTERNS:
            m = pattern.match(line)
            if m:
                yield "resources", name(m)
        return
    for pattern in _functions_for(path):
        m = pattern.match(line)
        if m:
            yield "functions", m[1]
            return


def parse_diff(text):
    added, removed = {}, {}
    old_path = path = None
    for line in text.splitlines():
        if line.startswith("--- "):
            old_path = line[4:].removeprefix("a/").strip()
            continue
        if line.startswith("+++ "):
            new = line[4:].strip()
            path = old_path if new == "/dev/null" else new.removeprefix("b/")
            continue
        if path is None or line.startswith(("diff --git", "@@")):
            continue
        if line.startswith("+"):
            side = added
        elif line.startswith("-"):
            side = removed
        else:
            continue
        for category, name in _declarations(line[1:], path):
            side.setdefault((category, name, path), None)

    result = {c: {"created": [], "deleted": [], "changed": []} for c in ("resources", "functions")}
    for key in added:
        bucket = "changed" if key in removed else "created"
        result[key[0]][bucket].append({"name": key[1], "file": key[2]})
    for key in removed:
        if key not in added:
            result[key[0]]["deleted"].append({"name": key[1], "file": key[2]})
    return result


LABELS = {
    "en": {"resources": ("Resources", "Resource"), "functions": ("Functions", "Function"),
           "file": "File", "change": "Change", "none": "None.",
           "created": "Created", "deleted": "Deleted", "changed": "Changed"},
    "pt": {"resources": ("Recursos", "Recurso"), "functions": ("Funções", "Função"),
           "file": "Arquivo", "change": "Mudança", "none": "Nenhum.",
           "created": "Criado", "deleted": "Removido", "changed": "Alterado"},
}


def to_markdown(inventory, lang="en"):
    words = LABELS[lang]
    out = []
    for category in ("resources", "functions"):
        title, label = words[category]
        rows = [(i["name"], i["file"], words[change])
                for change in ("created", "deleted", "changed")
                for i in inventory[category][change]]
        out.append(f"### {title}\n")
        if not rows:
            out.append(words["none"] + "\n")
            continue
        out.append(f"| {label} | {words['file']} | {words['change']} |\n|---|---|---|")
        out += [f"| `{n}` | `{f}` | {c} |" for n, f, c in rows]
        out.append("")
    return "\n".join(out)


def base_refs(base=None):
    """Candidate bases. A base git could read as an option is dropped."""
    given = [f"origin/{base}", base] if base and SAFE_REF.fullmatch(base) else []
    return given + list(DEFAULT_BASES)


def git_diff(repo, base=None):
    for ref in base_refs(base):
        try:
            out = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv", f"{ref}...HEAD"],
                                 capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise SystemExit(f"git diff timed out in {repo}")
        if out.returncode == 0:
            return out.stdout
    raise SystemExit(f"git diff failed in {repo}: no base found, pass --base")


def main(argv=None):
    ap = argparse.ArgumentParser(description="List the resources and functions the branch creates, deletes or changes.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base")
    ap.add_argument("--diff", help="read a saved unified diff instead of running git")
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    ap.add_argument("--lang", choices=("en", "pt"), default="en", help="language of the markdown tables")
    args = ap.parse_args(argv)
    text = Path(args.diff).read_text(encoding="utf-8") if args.diff else git_diff(args.repo, args.base)
    inv = parse_diff(text)
    print(json.dumps(inv, indent=2) if args.format == "json" else to_markdown(inv, args.lang))
    return 0


if __name__ == "__main__":
    sys.exit(main())
