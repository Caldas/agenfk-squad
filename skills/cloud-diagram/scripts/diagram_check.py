#!/usr/bin/env python3
"""Check a .drawio diagram against the cloud-diagram skill's contract.

    python3 -I diagram_check.py [--allow TERM] [--] diagram.drawio [other.drawio ...]
    python3 -I diagram_check.py --help

A path that starts with - goes after --.

Prints one `FAIL <rule>: [page] <reason>` line per broken rule and exits 1,
or `ok <file>` and exits 0. A `WARN` line never fails. Exits 2 on a usage
error and 3 when a file cannot be read (not checked, not failed). A FAIL in
any file wins over an unreadable one.

Rules that fail:

  xml           the file is well-formed XML and carries no DOCTYPE or ENTITY
  compressed    every page is <mxGraphModel> in plain text, not a compressed
                blob the pull request diff cannot show
  structure     every page has <root>, exactly one root cell (no parent), at
                least one layer under it, and every cell has an id
  duplicate-id  no id repeats on the same page (0 and 1 repeat across pages)
  parent        the parent of every cell exists on the same page
  floating-edge every edge has a source and a target on the same page, so that
                moving the box in draw.io takes the line with it; sample lines
                inside a container labelled exactly Legend, Legenda or Key are
                exempt
  lexicon       no label carries a word from the writing skill's banned lexicon
                (a label that reads as AI-written); --allow TERM or
                <!-- writing: allow TERM --> downgrades it to WARN. Without the
                writing skill beside this one, a built-in list of 13 words
                applies and a `note:` line on stderr says so and why
  status        some label or page name states the drawing's status: CURRENT
                with a date (YYYY-MM-DD) or PROPOSED; without it the reader
                takes a proposal for the system that is running

Warnings:

  label-length  box label longer than 6 words, edge label longer than 4 (the
                title and text cells are exempt): the detail goes in the text
  unlabeled     plain box with no label and no icon (a fill with no outline is
                a backdrop, not a box)
  crowded       more than 25 boxes on one page: split into overview and detail

Only the XML a person reviews is checked. An exported .drawio.png or
.drawio.svg is a preview of this file; check the source.
"""
import html
import re
import sys
import xml.etree.ElementTree as ET
import xml.parsers.expat
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True   # importing slop_lint must not leave __pycache__ in the skill
# The lexicon lives in the writing skill, this one's sibling (skills/writing in the repo,
# ~/.claude/skills/writing installed). Without it, a minimal built-in lexicon applies, so
# the gate never passes blank, and main() says so on stderr.
_WRITING = Path(__file__).resolve().parents[2] / "writing" / "scripts"
LEXICON_FALLBACK = None   # why the built-in lexicon is in use, or None when the writing skill's is
try:
    sys.path.insert(0, str(_WRITING))
    from slop_lint import ALLOW_RE, BANNED_LEXICON, strip_accents  # noqa: E402
except ImportError as e:
    import unicodedata

    if isinstance(e, ModuleNotFoundError) and e.name == "slop_lint":
        LEXICON_FALLBACK = "the writing skill is not installed (no writing/scripts/slop_lint.py beside this skill)"
    else:
        LEXICON_FALLBACK = f"the writing skill's slop_lint does not export ALLOW_RE, BANNED_LEXICON and strip_accents ({e})"
    ALLOW_RE = re.compile(r"<!--\s*(?:writing|escrita):\s*allow\s+(.+?)\s*-->", re.I)
    # Detection data, not prose: the Portuguese words stay, owners label in either language.
    BANNED_LEXICON = {w: "say what the component does" for w in (
        "seamless", "robust", "cutting-edge", "next-gen", "leverage", "synergy", "revolutionary",
        "transformative", "robusto", "revolucionario", "transformador", "sinergia", "de ponta")}

    def strip_accents(text):
        return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
finally:
    if sys.path and sys.path[0] == str(_WRITING):
        sys.path.pop(0)

MAX_BOX_WORDS = 6
MAX_EDGE_WORDS = 4
MAX_BOXES = 25
BLOCK_TAG_RE = re.compile(r"<\s*/?\s*(br|div|p|li|tr|td|h[1-6])\b[^>]*>", re.I)
TAG_RE = re.compile(r"<[^>]+>")
LEGEND_RE = re.compile(r"^\s*(legend|legenda|key)\s*$", re.I)
# Bilingual on purpose: a label written in Portuguese states its status too.
PROPOSED_RE = re.compile(r"\b(proposed|planned|target state|proposta|proposto|planejad[oa])\b")
CURRENT_RE = re.compile(r"\b(current|as of|existing|atual|existente|em producao)\b")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
WRAPPERS = ("UserObject", "object")


class Cell:
    def __init__(self, el):
        inner = el.find("mxCell") if el.tag in WRAPPERS else el
        inner = inner if inner is not None else el
        self.id = el.get("id")
        self.label = plain(el.get("label") if el.tag in WRAPPERS else el.get("value"))
        self.parent = inner.get("parent")
        self.vertex = inner.get("vertex") == "1"
        self.edge = inner.get("edge") == "1"
        self.source = inner.get("source")
        self.target = inner.get("target")
        self.style = parse_style(inner.get("style") or "")

    @property
    def is_text(self):
        return "text" in self.style.get("", ()) or self.style.get("shape") == "text"

    @property
    def is_container(self):
        s = self.style
        return (s.get("container") == "1" or "swimlane" in s.get("", ())
                or "group" in s.get("", ()) or str(s.get("shape", "")).endswith(".group"))

    @property
    def is_backdrop(self):
        # An unlabeled fill with no outline (the export background) is page, not component.
        return not self.label and self.style.get("strokeColor") == "none" and not self.is_icon

    @property
    def is_icon(self):
        s = self.style
        return any(k in s for k in ("shape", "image", "resIcon", "prIcon")) or "image" in s.get("", ())


def plain(value):
    """Label text as a reader sees it: markup dropped, entities resolved."""
    # Block tags break words; inline ones (<b>, <span>) do not, so Ro<b>bust</b> stays one word.
    text = html.unescape(TAG_RE.sub("", BLOCK_TAG_RE.sub(" ", value or "")))
    return " ".join(text.split())


def parse_style(style):
    """draw.io style string into a dict; bare tokens (text, rounded...) go under ''."""
    out = {"": set()}
    for part in filter(None, (p.strip() for p in style.split(";"))):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
        else:
            out[""].add(part)
    return out


def pages(root):
    """(page name, mxGraphModel or None, fails) for each page of the document."""
    if root.tag == "mxGraphModel":
        return [("page 1", root, [])]
    if root.tag != "mxfile":
        return [("document", None, [("structure", f"root element is <{root.tag}>, expected <mxfile> or <mxGraphModel>")])]
    found = []
    for i, d in enumerate(root.findall("diagram"), 1):
        name = d.get("name") or d.get("id") or f"page {i}"
        model = d.find("mxGraphModel")
        if model is not None:
            found.append((name, model, []))
        elif (d.text or "").strip():
            found.append((name, None, [("compressed", "the page is a compressed blob; save it uncompressed "
                                        "(File > Properties > Compressed off) so the diff shows it")]))
        else:
            found.append((name, None, [("structure", "the page has no <mxGraphModel>")]))
    if not found:
        found.append(("document", None, [("structure", "<mxfile> with no <diagram> page")]))
    return found


class DtdFound(Exception):
    pass


def has_dtd(text):
    """True when expat itself meets a DOCTYPE or ENTITY declaration.

    The same parser that builds the tree decides, so no comment, processing
    instruction or encoding trick can show the guard one thing and ElementTree
    another. It stops at the declaration, before any entity is expanded."""
    def refuse(*_):
        raise DtdFound
    p = xml.parsers.expat.ParserCreate()
    p.StartDoctypeDeclHandler = refuse
    p.EntityDeclHandler = refuse
    try:
        p.Parse(text, True)
    except DtdFound:
        return True
    except xml.parsers.expat.ExpatError:
        return False                          # not well-formed: ElementTree reports it next
    return False


def in_legend(cell, by_id):
    """True when a container between the cell and its layer is labelled exactly Legend, Legenda or Key."""
    seen, pid = set(), cell.parent
    while pid in by_id and pid not in seen:
        node = by_id[pid]
        grandparent = by_id.get(node.parent)
        if grandparent is None or not grandparent.parent:
            return False                      # node is a layer or the root: never a legend
        if LEGEND_RE.match(node.label):
            return True
        seen.add(pid)
        pid = node.parent
    return False


def check_page(name, model, allowed):
    fails, warns, labels = [], [], []
    tag = f"[{name}]"
    root = model.find("root")
    if root is None:
        return [("structure", f"{tag} <mxGraphModel> with no <root>")], warns, labels
    cells = [Cell(el) for el in root if el.tag == "mxCell" or el.tag in WRAPPERS]
    by_id = {c.id: c for c in cells if c.id}

    if any(not c.id for c in cells):
        fails.append(("structure", f"{tag} a cell with no id"))
    # The root is the one cell with no parent and a layer is any child of it. draw.io's own
    # templates use random ids (X-0, X-1), and a page may hold several layers or lose layer 1.
    roots = [c for c in cells if not c.parent]
    layers = [c for c in cells if roots and c.parent == roots[0].id]
    if not roots:
        fails.append(("structure", f"{tag} no root cell: one cell must have no parent"))
    elif not layers:
        fails.append(("structure", f"{tag} no layer: missing a cell with parent {roots[0].id!r}"))
    for cid, n in Counter(c.id for c in cells if c.id).items():
        if n > 1:
            fails.append(("duplicate-id", f"{tag} id {cid!r} used by {n} cells"))
    for c in roots[1:]:
        fails.append(("parent", f"{tag} cell {c.id!r} has no parent"))
    if roots and layers:                      # otherwise every cell would repeat the structure failure
        for c in cells:
            if c.parent and c.parent not in by_id:
                fails.append(("parent", f"{tag} cell {c.id!r} points to parent {c.parent!r}, which is not on this page"))
        for c in cells:                       # a parent loop never reaches the root
            seen, pid = {c.id}, c.parent
            while pid in by_id and by_id[pid].parent and pid not in seen:
                seen.add(pid)
                pid = by_id[pid].parent
            if pid in seen:
                fails.append(("parent", f"{tag} cell {c.id!r} is in a parent loop that never reaches the root"))

    edge_ids = {c.id for c in cells if c.edge}
    boxes = 0
    for c in cells:
        words = len(c.label.split())
        if c.edge and not in_legend(c, by_id):    # a legend's sample lines have no shape to attach to
            for end in ("source", "target"):
                ref = getattr(c, end)
                if not ref:
                    fails.append(("floating-edge", f"{tag} edge {c.id!r} has no {end}; attach it to a shape"))
                elif ref not in by_id:
                    fails.append(("floating-edge", f"{tag} edge {c.id!r}: {end} {ref!r} is not on this page"))
        if (c.edge or c.parent in edge_ids) and words > MAX_EDGE_WORDS:
            warns.append(("label-length", f"{tag} label of edge {c.id!r} has {words} words; at most {MAX_EDGE_WORDS}"))
        if c.label:
            labels.append(c.label)
            flat = strip_accents(c.label).lower()
            for word, why in BANNED_LEXICON.items():
                if re.search(rf"\b{re.escape(word)}\b", flat):
                    finding = ("lexicon", f"{tag} label of cell {c.id!r} {c.label!r}: '{word}', {why}")
                    (warns if word in allowed else fails).append(finding)
        if not c.vertex or c.parent in edge_ids:      # edge label cells ride on their edge
            continue
        if c.is_text:
            continue
        if words > MAX_BOX_WORDS:
            warns.append(("label-length", f"{tag} label of cell {c.id!r} has {words} words; a box takes at most {MAX_BOX_WORDS}"))
        if c.is_container or c.is_backdrop:
            continue
        boxes += 1
        if not c.label and not c.is_icon:
            warns.append(("unlabeled", f"{tag} cell {c.id!r} is a box with no label"))
    if boxes > MAX_BOXES:
        warns.append(("crowded", f"{tag} {boxes} boxes on one page; split into an overview and detail pages"))
    return fails, warns, labels


def check(text, allowed=()):
    allowed = {strip_accents(a).lower() for a in allowed}
    for m in ALLOW_RE.finditer(text):
        allowed |= {strip_accents(t.strip()).lower() for t in re.split(r"[,;]", m.group(1)) if t.strip()}
    if has_dtd(text):
        return [("xml", "a .drawio never carries DOCTYPE or ENTITY; refused before reading")], []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [("xml", f"malformed XML ({e})")], []
    fails, warns, labels = [], [], []
    for name, model, page_fails in pages(root):
        fails += [(r, f"[{name}] {m}") for r, m in page_fails]
        labels.append(name)
        if model is not None:
            f, w, lab = check_page(name, model, allowed)
            fails, warns, labels = fails + f, warns + w, labels + lab
    if root.tag in ("mxfile", "mxGraphModel"):
        flat = [strip_accents(t).lower() for t in labels]
        proposed = any(PROPOSED_RE.search(t) for t in flat)
        current_dated = any(CURRENT_RE.search(t) and DATE_RE.search(t) for t in flat)
        if not (proposed or current_dated):
            current_undated = any(CURRENT_RE.search(t) for t in flat)
            fails.append(("status", "the drawing says it is current but has no date (YYYY-MM-DD)" if current_undated else
                                    "no label or page name states the status: CURRENT as of YYYY-MM-DD "
                                    "(with the source) or PROPOSED"))
    return fails, warns


def main(argv):
    paths, allowed, args = [], [], iter(argv)
    for a in args:
        if a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        if a == "--":                         # everything after it is a path, even "-x.drawio"
            paths.extend(args)
            break
        if a == "--allow":
            term = next(args, None)
            if term is None:
                print("usage: --allow needs a term", file=sys.stderr)
                return 2
            allowed.append(term)
        elif a.startswith("--allow="):
            allowed.append(a.split("=", 1)[1])
        elif a.startswith("-"):
            print(f"usage: unknown option {a} (a path that starts with - goes after --)", file=sys.stderr)
            return 2
        else:
            paths.append(a)
    if not paths:
        print("usage: diagram_check.py [--allow TERM] [--] diagram.drawio [other.drawio ...]", file=sys.stderr)
        return 2
    if LEXICON_FALLBACK:
        print(f"note: lexicon check uses the built-in list of {len(BANNED_LEXICON)} words: {LEXICON_FALLBACK}",
              file=sys.stderr)
    failed = unreadable = False
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:                  # unverified, not failing; keep checking the rest
            print(f"ERROR {path}: could not read it ({e.strerror})")
            unreadable = True
            continue
        fails, warns = check(text, allowed)
        if fails or warns:
            print(f"== {path}")
        for rule, reason in warns:
            print(f"WARN {rule}: {reason}")
        for rule, reason in fails:
            print(f"FAIL {rule}: {reason}")
        if fails:
            failed = True
        else:
            print(f"ok {path}")
    return 1 if failed else 3 if unreadable else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
