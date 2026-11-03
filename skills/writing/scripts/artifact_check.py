#!/usr/bin/env python3
"""Check a rendered HTML document against the writing skill's contract.

    python3 -I artifact_check.py page.html [other.html ...]

Prints one `FAIL <rule>: <reason>` line per broken rule and exits 1, or prints
`ok <file>` and exits 0. A `WARN` line never fails. Exits 3 when it could not
read the file (page not checked, which is different from failed).

Always, for every page:

  title         a <title> with text
  tokens        a :root{...} rule that defines custom properties (--name:value);
                colour and type come from tokens: the project's (a --ds-* block
                from its design system, see the design-reference skill) or the
                neutral template's
  ds-contract   every var(--ds-*) the page uses is defined in a :root: using the
                contract without pasting the block leaves the page with no colour
  local-image   no <img src> or <image href> pointing at a local path: in a
                published Artifact it becomes a broken image. Use inline SVG, a
                URL or data:

Only when the page declares itself bilingual, with two or more languages in
<html data-languages="pt en"> (the first is the language it opens in):

  toggle        the first element of <body> is a .langbar with a data-lang
                button for each declared language; visible, outside <template>
  i18n          <script type="application/json" id="i18n"> with one object per
                language, the same keys in all of them, none empty, every
                data-t and data-t-aria key present, no visible text outside
                data-t (translate="no", code and pre excepted) and a script that
                reads #i18n
  initial-language  <html lang> is the first declared language (pt matches pt-BR)
  export        html.render .langbar{display:none}: an exported PDF/PNG comes
                out without the bar
  languages     a page with a .langbar or #i18n that does not declare
                data-languages fails: a half-built toggle does not escape the check

No brand, logo or mandatory font rule: the look belongs to the project or to
the design-reference skill.
"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}
# Content whose text is not prose a reader needs translated.
NO_TEXT = {"script", "style", "code", "pre", "svg", "template", "noscript"}
# Elements that may precede the language bar inside <body>.
BEFORE_BAR = {"script", "style", "link", "meta", "title", "noscript", "template"}
# translate="no" covers a name, a number or a code token, not a block of prose.
SHORT = 6
CONTAINERS = {"html", "body", "main", "section", "article", "header", "footer", "div", "nav", "aside"}
# Opening one of these closes an open <p>, as the HTML parser does.
CLOSES_P = {"p", "div", "section", "article", "header", "footer", "main", "nav", "aside", "ul", "ol",
            "table", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "figure", "form", "hr"}
SELF_CLOSING_PEERS = {"li", "dt", "dd", "tr", "td", "th", "option"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []                       # (tag, flags) per open element
        self.root = None                      # attrs of <html>
        self.body = None                      # attrs of <body>
        self.body_level = 0                   # stack depth of <body> children
        self.first_child = None               # (tag, attrs, inside_template)
        self.bar_depth = None
        self.bar_buttons = set()
        self.bar_problem = None
        self.keys, self.aria_keys = set(), set()
        self.untagged = []
        self.css = []
        self.scripts = []
        self.payload = None
        self.uses, self.symbols = set(), set()
        self._script = None
        self.title_text = []                  # text of the document <title>
        self.local_images = []                # image src/href that points at the disk
        self.attr_text = []
        self.nt_text = []                     # text under each translate="no" element

    def _flags(self):
        return self.stack[-1][1] if self.stack else {}

    def _implied_end(self, tag):
        if tag in CLOSES_P:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == "p":
                    del self.stack[i:]
                    break
                if self.stack[i][0] in CONTAINERS:
                    break
        # A new row closes the open row and its cells; a new cell closes the open cell.
        peers = {"tr": ("tr", "td", "th"), "td": ("td", "th"), "th": ("td", "th")}.get(tag, (tag,))
        if tag in SELF_CLOSING_PEERS:
            for i in range(len(self.stack) - 1, -1, -1):
                name = self.stack[i][0]
                if name in peers:
                    del self.stack[i:]
                    if tag != "tr" or name == "tr":
                        break
                elif name in ("table", "tbody", "thead", "ul", "ol", "dl", "select") or name in CONTAINERS:
                    break

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        self._implied_end(tag)
        parent = self._flags()
        flags = dict(parent)
        if tag == "html":
            self.root = a
        if tag == "body":
            self.body = a
            self.body_level = len(self.stack) + 1
        # First element of the body (or of the document, for a page without <body>).
        level = self.body_level if self.body is not None else len([t for t, _ in self.stack if t in ("html", "head")])
        skip_link = (tag == "a" and a.get("href", "").startswith("#")
                     and "skip" in a.get("class", "").split())
        if (self.first_child is None and len(self.stack) == level and tag not in ("html", "head", "body")
                and tag not in BEFORE_BAR and not skip_link
                and not (tag == "svg" and a.get("aria-hidden") == "true")):
            self.first_child = (tag, a, parent.get("template", False))
        elif (self.first_child is not None and self.first_child[0] == "header" and "langbar" not in
              self.first_child[1].get("class", "").split() and len(self.stack) == level + 1
              and "langbar" in a.get("class", "").split() and not self.first_child[1].get("_seen")):
            self.first_child = (tag, a, parent.get("template", False))
        if self.first_child is not None and self.first_child[0] == "header" and len(self.stack) >= level + 1:
            self.first_child[1]["_seen"] = "1"
        if tag == "template":
            flags["template"] = True
        if "langbar" in a.get("class", "").split():
            if self.bar_depth is None:
                self.bar_depth = len(self.stack)
                style = re.sub(r"\s+", "", a.get("style", "")).lower()
                if ("hidden" in a or flags.get("template") or a.get("aria-hidden", "").lower() == "true"
                        or "display:none" in style or "visibility:hidden" in style):
                    self.bar_problem = "the language bar is hidden or inside <template>"
            flags["bar"] = True
        if flags.get("bar") and tag == "button" and a.get("data-lang"):
            self.bar_buttons.add(a["data-lang"].lower())
        if "data-t" in a:
            self.keys.add(a["data-t"])
            flags["tagged"] = True
        if "data-t-aria" in a:
            self.aria_keys.add(a["data-t-aria"])
        if a.get("translate", "").lower() == "no" and tag not in CONTAINERS:
            flags["nt"] = len(self.nt_text)
            self.nt_text.append([])
        if tag == "foreignobject":            # HTML inside a diagram is prose again
            flags.pop("svg", None)
            flags.pop("skip", None)
        if tag in NO_TEXT and not (tag == "svg" and a.get("aria-hidden") != "true"):
            flags["skip"] = True
        if tag == "svg" and a.get("aria-hidden") != "true":
            flags["svg"] = True
        for attr in ("alt", "title", "placeholder"):
            if re.search(r"[^\W\d_]{3,}", a.get(attr, "")) and f"data-t-{attr}" not in a and not flags.get("tagged"):
                self.attr_text.append(f'{attr}="{a[attr][:40]}"')
        if tag in ("img", "image"):
            src = (a.get("src") if tag == "img" else (a.get("href") or a.get("xlink:href"))) or ""
            if src.strip() and not re.match(r"^(https?:|data:|//)", src.strip(), re.I):
                self.local_images.append(src.strip()[:60])
        if tag == "use":
            href = a.get("href") or a.get("xlink:href") or ""
            if href.startswith("#") and not parent.get("code"):
                self.uses.add(href[1:])
        if tag in ("code", "pre"):
            flags["code"] = True
        if tag == "symbol" and a.get("id"):
            self.symbols.add(a["id"])
        if tag == "script":
            self._script = (a.get("type", "").lower(), a.get("id", ""))
        if tag in VOID:
            return
        self.stack.append((tag, flags))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        f = self._flags()
        top = self.stack[-1][0] if self.stack else ""
        if top == "title" and not any(name == "svg" for name, _ in self.stack):
            self.title_text.append(data)
        if top == "style":
            self.css.append(data)
        elif top == "script" and self._script is not None:
            kind, sid = self._script
            if kind == "application/json" and sid == "i18n":
                self.payload = data
            elif kind in ("", "text/javascript", "module"):
                self.scripts.append(data)
        elif f.get("svg") and top not in ("text", "tspan", "title"):
            return                            # geometry, not prose
        elif not f.get("skip") and not f.get("tagged") and re.search(r"[^\W\d_]", data):
            if f.get("nt") is not None:
                self.nt_text[f["nt"]].append(data.strip())
            else:
                self.untagged.append(data.strip())

    def close(self):
        super().close()
        # translate="no" covers a short name or token; a whole table or list is prose.
        for chunks in self.nt_text:
            text = " ".join(chunks)
            if len(text.split()) > SHORT:
                self.untagged.append(text)


def norm_css(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"\s+", "", text).lower()


def declared_languages(root):
    """Languages of <html data-languages>, in order, without repeats."""
    seen = []
    for code in re.split(r"[\s,]+", (root or {}).get("data-languages", "").strip().lower()):
        if code and code not in seen:
            seen.append(code)
    return seen


def check(html: str):
    fails, warns = [], []
    p = Page()
    p.feed(html)
    p.close()
    css = norm_css(" ".join(p.css))
    root = p.root or {}
    flat = re.sub(r"@[^{};]+\{", "", css)  # rules inside @media count too
    rules = re.findall(r"([^{}]+)\{([^}]*)\}", flat)

    # title
    if not " ".join(p.title_text).strip():
        fails.append(("title", "the page has no <title> with text"))

    # tokens
    if not any(":root" in sel and re.search(r"--[\w-]+:", body) for sel, body in rules):
        fails.append(("tokens", "no :root{--token:value} rule; colour and type come from tokens (the project's DESIGN.md or the template)"))
    defined = {n for sel, body in rules if ":root" in sel for n in re.findall(r"(--ds-[\w-]+):", body)}
    missing_ds = sorted(set(re.findall(r"var\((--ds-[\w-]+)", css)) - defined)
    if missing_ds:
        fails.append(("ds-contract", "the page uses " + ", ".join(missing_ds[:4]) + " without defining it in :root; paste "
                                     "the project's --ds-* block (design-reference) at the top of the <style>"))
    if "prefers-color-scheme:dark" not in css and "[data-theme" not in css:
        warns.append(("tokens", "no dark mode (@media (prefers-color-scheme: dark) or [data-theme])"))

    # local-image
    for src in p.local_images[:5]:
        fails.append(("local-image", f'image points at a local path "{src}": use inline SVG, a URL or data:'))

    langs = declared_languages(root)
    if len(langs) < 2:
        if p.bar_depth is not None or p.payload is not None:
            fails.append(("languages", 'the page has a language bar or an #i18n payload, but <html> does not '
                                       'declare data-languages with two languages (e.g. data-languages="pt en")'))
        elif p.root is not None and not root.get("lang"):
            warns.append(("initial-language", "<html> has no lang"))
        return fails, warns

    # toggle
    if p.bar_depth is None:
        fails.append(("toggle", 'no element with class "langbar" at the top of the page'))
    else:
        if p.bar_problem:
            fails.append(("toggle", "the language bar is hidden or inside <template>"))
        first = p.first_child
        if not first or "langbar" not in first[1].get("class", "").split():
            fails.append(("toggle", "the language bar is not the first element of the page"))
        for lang in langs:
            if lang not in p.bar_buttons:
                fails.append(("toggle", f'the language bar has no data-lang="{lang}" button'))

    # i18n
    if p.payload is None:
        fails.append(("i18n", 'the <script type="application/json" id="i18n"> payload is missing'))
    else:
        try:
            data = json.loads(p.payload)
        except json.JSONDecodeError as e:
            data = None
            fails.append(("i18n", f"the payload is not valid JSON ({e.msg}, line {e.lineno})"))
        if data is not None and not isinstance(data, dict):
            fails.append(("i18n", "the payload must be a JSON object with one object per language"))
            data = None
        if data is not None:
            tables = {lang: data.get(lang) for lang in langs}
            missing = [lang for lang, table in tables.items() if not isinstance(table, dict)]
            for lang in missing:
                fails.append(("i18n", f'the payload has no "{lang}" object'))
            if not missing:
                every = set().union(*(set(table) for table in tables.values()))
                common = set.intersection(*(set(table) for table in tables.values()))
                for k in sorted(every - common):
                    absent = ", ".join(lang for lang in langs if k not in tables[lang])
                    fails.append(("i18n", f'the key "{k}" is missing in: {absent}'))
                for lang, table in tables.items():
                    for k, v in table.items():
                        if not isinstance(v, str) or not v.strip():
                            fails.append(("i18n", f'the key "{k}" is empty in "{lang}"'))
                for k in sorted((p.keys | p.aria_keys) - common):
                    fails.append(("i18n", f'the data-t key "{k}" is not in the payload of every language'))
                for k in sorted(common):
                    values = {str(tables[lang][k]) for lang in langs}
                    if len(values) == 1 and re.search(r"[^\W\d_]{4,}", re.sub(r"<[^>]+>", "", values.pop())):
                        warns.append(("i18n", f'the key "{k}" is the same in every language; translate it or confirm it is a name'))
    for attr in p.attr_text[:5]:
        warns.append(("i18n", f'{attr} is not translated; use data-t-{attr.split("=")[0]} or confirm it is a name'))
    for text in p.untagged[:5]:
        fails.append(("i18n", f'visible text outside data-t: "{text[:60]}" (mark it with data-t or translate="no")'))
    reads = re.compile(r"""getElementById\(\s*["']i18n["']\s*\)|querySelector\(\s*["']#i18n["']\s*\)"""
                       r"""|["']#?i18n["'][\s\S]*(getElementById|querySelector)|(getElementById|querySelector)[\s\S]*["']#?i18n["']""")
    if not any(reads.search(s) and "data-lang" in s for s in p.scripts):
        fails.append(("i18n", "no script reads #i18n, so the buttons do not switch the language"))

    # initial-language
    if p.root is not None:
        lang = root.get("lang", "").lower()
        if lang != langs[0] and not lang.startswith(langs[0] + "-"):
            fails.append(("initial-language", f'<html lang="{root.get("lang", "")}">: the page opens in the first '
                                              f'declared language (lang="{langs[0]}")'))

    # export
    if not any("html.render.langbar" in sel.split(",") and "display:none" in body for sel, body in rules):
        fails.append(("export", "html.render .langbar{display:none} is missing; an exported PDF would keep the bar"))
    return fails, warns


def main(paths):
    if not paths:
        print("usage: artifact_check.py page.html [other.html ...]", file=sys.stderr)
        return 2
    status = 0
    for path in paths:
        try:
            html = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:                  # 3, not 1: page not checked, not failed
            print(f"ERROR {path}: could not read it ({e.strerror})")
            return 3
        fails, warns = check(html)
        if fails or warns:
            print(f"== {path}")
        for rule, reason in warns:
            print(f"WARN {rule}: {reason}")
        for rule, reason in fails:
            print(f"FAIL {rule}: {reason}")
        if fails:
            status = 1
        else:
            print(f"ok {path}")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
