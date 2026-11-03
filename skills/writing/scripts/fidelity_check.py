#!/usr/bin/env python3
"""Prove that an edited document lost no material fact and invented none.

Compares an original document against its rewritten version and reports every
number, unit, percentage, currency amount, date, version, ticket key, URL, file
path, code identifier, code block and table row that exists in one file but not
the other.

MISSING  = present in the original, gone from the rewrite -> information dropped.
INVENTED = present in the rewrite, absent from the original -> information made up.

REVIEW   = negation, modality or polarity vocabulary whose count moved -> the
           meaning may have flipped. The script does not judge it; a human does.

MISSING and INVENTED are failures. REVIEW blocks until acknowledged with
--accept-semantic. Rewording is invisible to the token diff by design: it
compares facts, not prose.

This is a detector, not a proof of fidelity. It proves that hashed regions are
byte-identical and that selected tokens balance. It cannot understand the whole
meaning of a sentence, so fidelity remains a rule you follow.

Usage:
    fidelity_check.py ORIGINAL REWRITE [--json] [--allow-added]
                      [--accept-semantic] [--ignore PATTERN]

Exit codes: 0 clean, 1 differences found, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

PATTERNS: dict[str, re.Pattern] = {
    # order matters: earlier patterns consume their text first
    "url": re.compile(r"https?://[^\s)>\]\"'`]+"),
    "ticket": re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b"),
    "version": re.compile(r"\bv?\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?\b"),
    "date": re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}/\d{2}/\d{2})\b"),
    "currency": re.compile(r"(?:R\$|US\$|\$|€|£)\s?\d[\d.,]*(?:\s?(?:mil|k|K|M|MM|bi))?"),
    "percent": re.compile(r"\d[\d.,]*\s?%"),
    "quantity": re.compile(
        r"\b\d[\d.,]*\s?(?:TB|GB|MB|KB|ms|µs|s|h|min|dias?|days?|meses|months?|"
        r"anos?|years?|vCPU|CPU|rps|req/s|QPS|USD|BRL)\b"),
    "aws_id": re.compile(r"\b(?:\d{12}|i-[0-9a-f]{8,17}|vpc-[0-9a-f]{8,17}|"
                         r"subnet-[0-9a-f]{8,17}|sg-[0-9a-f]{8,17}|arn:aws:[^\s`'\")]+)\b"),
    "cidr": re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b"),
    "ip": re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
    "path": re.compile(r"(?:(?:~|\.{1,2})?/[\w.@+-]+){2,}/?"),
    "identifier": re.compile(
        r"\b(?:[a-z][a-z0-9]*(?:[_-][a-z0-9]+)+|"          # snake_case / kebab-case
        r"[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+|"              # CamelCase
        r"[A-Z]{2,}(?:_[A-Z0-9]+)+|"                       # UPPER_SNAKE
        r"\w+\.(?:tf|py|ts|js|json|yaml|yml|md|sh|sql|tfvars|csv|html))\b"),
    "number": re.compile(r"(?<![\w.$/-])\d[\d.,]*(?![\w.%$/-])"),
}

FENCE_RE = re.compile(r"^([ \t]*)(```+|~~~+)")


INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1", re.S)
LINK_TARGET_RE = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)")
HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)
TABLE_ROW_RE = re.compile(r"^\s*\|?(?:[^|\n]*\|){1,}[^|\n]*\|?\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]{4,}\|?\s*$")


def digest(blob: str) -> str:
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def extract(text: str) -> dict[str, Counter]:
    """Extract fact tokens by category, plus digests of every region that must
    survive an edit byte for byte: fenced code, inline code, frontmatter, HTML
    comments, link targets and table rows."""
    facts: dict[str, Counter] = {k: Counter() for k in PATTERNS}
    for extra in ("code_block", "table_row", "frontmatter", "inline_code",
                  "html_comment", "link_target"):
        facts[extra] = Counter()

    # YAML frontmatter is configuration, not prose: hash the whole block so a
    # changed license, version or title cannot pass as a reword.
    fm = re.match(r"\A---\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|\Z)", text, re.S)
    if fm:
        facts["frontmatter"][digest(fm.group(1).strip())] += 1

    # Inline code, link targets and HTML comments are extracted from the whole
    # document before any line walking, so a wrapped span still registers.
    for m in INLINE_CODE_RE.finditer(text):
        span = re.sub(r"\s+", " ", m.group(2)).strip()
        if span:
            facts["inline_code"][span] += 1
    for m in LINK_TARGET_RE.finditer(text):
        facts["link_target"][m.group(1)] += 1
    for m in HTML_COMMENT_RE.finditer(text):
        body = re.sub(r"\s+", " ", m.group(1)).strip()
        if body:
            facts["html_comment"][digest(body)] += 1

    lines = text.splitlines()
    prose_parts: list[str] = []
    code_buf: list[str] = []
    in_fence = False
    fence_marker = ""

    for line in lines:
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(2)[0] * 3
            if not in_fence:
                in_fence, fence_marker, code_buf = True, marker, []
                continue
            if marker == fence_marker:
                in_fence = False
                blob = "\n".join(code_buf).strip()
                if blob:
                    first = code_buf[0].strip()[:60] if code_buf else ""
                    facts["code_block"][f"{digest(blob)} :: {first}"] += 1
                continue
        if in_fence:
            code_buf.append(line)
            continue

        stripped = line.strip()
        # GFM allows a table row without the leading and trailing pipe.
        if TABLE_ROW_RE.match(stripped) and not TABLE_SEP_RE.match(stripped):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            norm = " | ".join(re.sub(r"\s+", " ", c) for c in cells if c)
            if norm:
                facts["table_row"][norm] += 1
        prose_parts.append(line)

    prose = "\n".join(prose_parts)
    remaining = prose
    for name, pattern in PATTERNS.items():
        for m in pattern.finditer(remaining):
            token = m.group(0).strip().rstrip(".,;:)")
            if token:
                facts[name][token] += 1
        remaining = pattern.sub(" ", remaining)
    return facts


# Meaning-flipping vocabulary. A faithful reword keeps these counts; a changed
# count means a requirement, a permission or a direction may have moved. The
# script never decides whether the change is correct — it hands the pair to a
# human. Negation particles are counted as one aggregate, so swapping "not X"
# for "without X" stays quiet while adding or dropping a negation does not.
NEGATION_RE = re.compile(
    r"\b(?:not|n't|no|never|without|neither|nor|"
    r"nao|não|nunca|jamais|sem|nem|tampouco)\b", re.I)

SEMANTIC_TERMS = {
    "polarity": ["approved", "rejected", "enabled", "disabled", "public",
                 "private", "allow", "allowed", "deny", "denied", "reversible",
                 "irreversible", "aprovado", "reprovado", "rejeitado",
                 "habilitado", "desabilitado", "publico", "público", "privado",
                 "permitido", "negado", "reversivel", "reversível"],
    "modality": ["must", "shall", "should", "may", "required", "optional",
                 "mandatory", "deve", "devera", "deverá", "pode", "podera",
                 "poderá", "obrigatorio", "obrigatório", "opcional"],
    "direction": ["before", "after", "increase", "decrease", "raise", "reduce",
                  "antes", "depois", "aumentar", "aumento", "reduzir",
                  "reducao", "redução"],
}


def semantic_profile(text: str) -> Counter:
    prof = Counter()
    prof["negation"] = len(NEGATION_RE.findall(text))
    for group, terms in SEMANTIC_TERMS.items():
        for term in terms:
            n = len(re.findall(rf"\b{re.escape(term)}\b", text, re.I))
            if n:
                prof[f"{group}:{term}"] += n
    return prof


def semantic_diff(original: Counter, rewrite: Counter):
    out = []
    for key in sorted(set(original) | set(rewrite)):
        a, b = original.get(key, 0), rewrite.get(key, 0)
        if a != b:
            out.append((key, a, b))
    return out


def diff(original: dict[str, Counter], rewrite: dict[str, Counter]):
    missing, added = [], []
    for category in original:
        a, b = original[category], rewrite[category]
        for token, count in a.items():
            delta = count - b.get(token, 0)
            if delta > 0:
                missing.append((category, token, delta))
        for token, count in b.items():
            delta = count - a.get(token, 0)
            if delta > 0:
                added.append((category, token, delta))
    return missing, added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("original", type=Path)
    ap.add_argument("rewrite", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-added", action="store_true",
                    help="new tokens become a warning instead of an error (use only when "
                         "the user asked for new content on purpose)")
    ap.add_argument("--ignore", action="append", default=[],
                    help="regex of a token to ignore; repeatable")
    ap.add_argument("--accept-semantic", action="store_true",
                    help="acknowledge negation, modality and polarity changes "
                         "as intentional after checking them")
    args = ap.parse_args()

    for p in (args.original, args.rewrite):
        if not p.is_file():
            print(f"fidelity_check: {p}: file not found", file=sys.stderr)
            return 2

    ignores = [re.compile(p) for p in args.ignore]

    def ignored(token: str) -> bool:
        return any(r.search(token) for r in ignores)

    o = extract(args.original.read_text(encoding="utf-8"))
    r = extract(args.rewrite.read_text(encoding="utf-8"))
    missing, added = diff(o, r)
    missing = [x for x in missing if not ignored(x[1])]
    added = [x for x in added if not ignored(x[1])]

    orig_text = args.original.read_text(encoding="utf-8")
    rew_text = args.rewrite.read_text(encoding="utf-8")
    semantic = semantic_diff(semantic_profile(orig_text), semantic_profile(rew_text))
    semantic = [x for x in semantic if not ignored(x[0])]

    if args.json:
        print(json.dumps({
            "original": str(args.original), "rewrite": str(args.rewrite),
            "missing": [{"category": c, "token": t, "count": n} for c, t, n in missing],
            "added": [{"category": c, "token": t, "count": n} for c, t, n in added],
            "review": [{"term": k, "original": a, "rewrite": b} for k, a, b in semantic],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"=== fidelity: {args.original} -> {args.rewrite} ===")
        if not missing and not added and not semantic:
            print("clean: no fact dropped, no fact invented, "
                  "no change of meaning detected")
        if missing:
            print(f"\nMISSING ({len(missing)}): information gone from the rewrite:")
            for c, t, n in sorted(missing):
                print(f"  [{c}] {t}" + (f"  (x{n})" if n > 1 else ""))
        if added:
            label = "WARNING" if args.allow_added else "INVENTED"
            print(f"\n{label} ({len(added)}): only in the rewrite:")
            for c, t, n in sorted(added):
                print(f"  [{c}] {t}" + (f"  (x{n})" if n > 1 else ""))
        if semantic:
            label = "WARNING" if args.accept_semantic else "REVIEW"
            print(f"\n{label} ({len(semantic)}): vocabulary that changes meaning; "
                  "check each sentence by hand:")
            for key, a, b in semantic:
                print(f"  [{key}] original {a} -> rewrite {b}")
            print("  the script does not decide whether the change is right. Check it "
                  "and, if it is intentional, run again with --accept-semantic")

    if missing:
        return 1
    if added and not args.allow_added:
        return 1
    if semantic and not args.accept_semantic:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
