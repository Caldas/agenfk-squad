#!/usr/bin/env python3
"""Deterministic AI-slop linter for pt-BR and English prose (writing skill).

Scans prose only. Code blocks, inline code, YAML frontmatter, HTML comments,
mermaid blocks, tables and link targets are masked out before any check runs, so
a finding never lands on material the editorial rules require to stay verbatim.

Usage:
    slop_lint.py FILE [FILE ...] [--json] [--warn-as-error] [--allow TERM]
                 [--profile FILE]

A voice profile (--profile, see references/voice-profile.md) declares a
writer's habits: terms they use on purpose, whether they keep em dashes or
curly quotes. It relaxes only the mechanical checks that encode a default
habit; a banned construction, a generic heading or a fact is never relaxed.

Exit codes: 0 clean (or warnings only), 1 at least one ERROR, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# masking
# --------------------------------------------------------------------------

FENCE_RE = re.compile(r"^([ \t]*)(```+|~~~+)")

# Per-file state, filled by split_document and read by the wording checks.
# QUOTED holds the line numbers inside a blockquote: someone else's words, so a
# finding there is reported but never blocks. ALLOWED holds terms the document
# declares intentional via "<!-- writing: allow <term>, <term> -->", and
# ALLOW_EMOJI is set by "<!-- writing: allow-emoji -->". The Portuguese
# directive name "escrita:" is read too, so pt-BR documents keep working.
QUOTED: set[int] = set()
ALLOWED: set[str] = set()
ALLOW_EMOJI = False
# Terms allowed on the command line. split_document rebuilds ALLOWED from this
# plus whatever the file itself declares, so a --allow term survives every file.
CLI_ALLOWED: set[str] = set()
# Habits declared by a voice profile (--profile). A writer whose own sample is
# full of em dashes keeps them: the dash checks encode a default, not a fact.
PROFILE_DASHES = False
PROFILE_QUOTES = False
PROFILE_EMOJI = False

ALLOW_RE = re.compile(r"<!--\s*(?:writing|escrita):\s*allow\s+([^>]+?)\s*-->", re.I)
ALLOW_EMOJI_RE = re.compile(r"<!--\s*(?:writing|escrita):\s*allow-emoji\s*-->", re.I)

# A GFM table row needs at least one interior pipe; the separator row is the
# dashes-and-colons line under the header.
TABLE_ROW_RE = re.compile(r"^\|?(?:[^|\n]*\|){1,}[^|\n]*\|?$")
TABLE_SEP_RE = re.compile(r"^\|?[\s:|-]{4,}\|?$")


def split_document(text: str):
    """Return (prose_lines, table_lines, code_lines) as lists of (lineno, text).

    Prose lines keep their original numbering. Masked regions are replaced by an
    empty string so line numbers stay aligned for reporting.
    """
    global ALLOW_EMOJI
    QUOTED.clear()
    ALLOWED.clear()
    ALLOWED.update(CLI_ALLOWED)
    # Directives are read from the raw text, before HTML comments are masked.
    for m in ALLOW_RE.finditer(text):
        for term in re.split(r"[,;]", m.group(1)):
            term = strip_accents(term.strip()).lower()
            if term:
                ALLOWED.add(term)
    ALLOW_EMOJI = bool(ALLOW_EMOJI_RE.search(text))

    lines = text.splitlines()
    prose: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    in_frontmatter = False
    in_comment = False

    for i, raw in enumerate(lines, start=1):
        line = raw

        # YAML frontmatter (only when it opens on line 1)
        if i == 1 and line.strip() == "---":
            in_frontmatter = True
            prose.append((i, ""))
            continue
        if in_frontmatter:
            if line.strip() in ("---", "..."):
                in_frontmatter = False
            prose.append((i, ""))
            continue

        m = FENCE_RE.match(line)
        if m:
            marker = m.group(2)[0] * 3
            if not in_fence:
                in_fence = True
                fence_marker = marker
                prose.append((i, ""))
                continue
            if marker == fence_marker:
                in_fence = False
                prose.append((i, ""))
                continue
        if in_fence:
            prose.append((i, ""))
            continue

        stripped = line.strip()

        # HTML comments, including the body of a multi-line one.
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            prose.append((i, ""))
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            prose.append((i, ""))
            continue
        line = re.sub(r"<!--.*?-->", " ", line)
        stripped = line.strip()

        # Markdown tables and separators. GFM allows a row with no leading or
        # trailing pipe, so match on the cell structure, not the first char.
        if TABLE_SEP_RE.match(stripped) or TABLE_ROW_RE.match(stripped):
            prose.append((i, ""))
            continue

        # Blockquotes are usually a quotation or a before/after example. Keep
        # the text for the checks but record the line as quoted.
        if stripped.startswith(">"):
            QUOTED.add(i)
            line = re.sub(r"^\s*>+\s?", "", line)

        # Inline code, link targets, bare URLs and HTML tags are replaced by the
        # sentinel CODEREF rather than deleted: they are masked from the wording
        # checks, but they still count as project-specific material for the
        # portability check, which would otherwise flag a sentence whose only
        # specificity lives inside backticks.
        line = re.sub(r"(`+)(?:.+?)\1", " CODEREF ", line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"<https?://[^>]*>", " CODEREF ", line)
        line = re.sub(r"https?://\S+", " CODEREF ", line)
        line = re.sub(r"<[^>]{1,80}>", " ", line)
        prose.append((i, line))

    return prose


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


# --------------------------------------------------------------------------
# rule data
# --------------------------------------------------------------------------

BANNED_LEXICON = {
    # pt-BR — banned when used as filler. Reported so a human confirms the use.
    "robusto": "say what makes it reliable (SLA, test, redundancy)",
    "robusta": "say what makes it reliable",
    "abrangente": "say what is covered",
    "transformador": "say what changes, for whom",
    "transformadora": "say what changes, for whom",
    "revolucionario": "claim with no concrete referent",
    "revolucionaria": "claim with no concrete referent",
    "jornada": "use the real name of the phase (migration, rollout, onboarding)",
    "ecossistema": "name the systems",
    "estrategico": "say which decision this changes",
    "estrategica": "say which decision this changes",
    "sinergia": "name the concrete gain",
    "holistico": "empty in a technical document",
    "paradigma": "empty in a technical document",
    "alavancar": "use 'usar' (use)",
    "empoderar": "say what the person can now do",
    "disruptivo": "claim with no concrete referent",
    "escalavel": "say up to what load, measured how",
    # English equivalents
    "robust": "say what makes it reliable",
    "comprehensive": "say what is covered",
    "transformative": "say what changes, for whom",
    "revolutionary": "claim with no concrete referent",
    "journey": "name the actual phase",
    "ecosystem": "name the systems",
    "strategic": "say which decision this changes",
    "seamless": "say what the integration actually does",
    "leverage": "use 'use'",
    "cutting-edge": "claim with no concrete referent",
    "game-changing": "claim with no concrete referent",
    "delve": "banned construction",
    "unlock": "banned construction when used figuratively",
    # English, merged from humanizer and no-ai-slop. Terms that are load-bearing
    # in technical material are deliberately absent: gate, gating, harness, key,
    # pipeline, underscore (the character), highlight, additionally, valuable.
    "utilize": "use 'use'",
    "facilitate": "say what it actually does",
    "foster": "say what it actually does",
    "fostering": "say what it actually does",
    "streamline": "say what got shorter, by how much",
    "empower": "say what the person can now do",
    "elevate": "empty verb",
    "embark": "empty verb",
    "supercharge": "empty verb",
    "effortless": "say how many steps",
    "paradigm": "empty in a technical document",
    "holistic": "empty in a technical document",
    "synergy": "name the concrete gain",
    "tapestry": "empty abstract noun",
    "multifaceted": "name the facets",
    "meticulous": "empty adjective",
    "paramount": "empty adjective",
    "ever-evolving": "empty adjective",
    "state-of-the-art": "claim with no concrete referent",
    "game-changer": "claim with no concrete referent",
    "groundbreaking": "claim with no concrete referent",
    "testament": "state the fact, let the reader judge",
    "showcase": "use 'show' or state the fact",
    "showcasing": "use 'show' or state the fact",
    "pivotal": "empty adjective",
    "interplay": "name the two things and how they interact",
    "vibrant": "sales language",
    "nestled": "sales language",
    "breathtaking": "sales language",
    "renowned": "sales language",
    "disruptive": "claim with no concrete referent",
    # last entries from the humanizer high-frequency set that are safe here
    "intricate": "say what is actually complex",
    "intricacies": "name the parts",
    "garner": "state the amount or cut the claim",
    "enhance": "say what changed",
    "enhanced": "say what changed",
}

BANNED_CONSTRUCTIONS = [
    (r"\bnao (e|foi|sao|era) apenas\b[^.;!?]{0,120}?,\s*(e|mas)\b", "\"não é apenas X, é Y\""),
    (r"\bnao (e|foi|sao) so\b[^.;!?]{0,120}?,\s*(e|mas)\b", "\"não é só X, é Y\""),
    (r"\bnot (just|only|merely)\b[^.;!?]{0,120}?,?\s*(but|it'?s)\b", "\"not just X, but Y\""),
    (r"\bem um mundo cada vez mais\b", "\"em um mundo cada vez mais\""),
    (r"\bnum mundo cada vez mais\b", "\"num mundo cada vez mais\""),
    (r"\bin (an?|today'?s) increasingly\b", "\"in an increasingly ... world\""),
    (r"\bin today'?s (rapidly|fast-paced|ever-?changing|ever-?evolving|digital|modern|dynamic)\b",
     "generic opening"),
    (r"\bin (the|this) (modern|digital|current) (era|age|world)\b", "generic opening"),
    (r"\bthe landscape of\b", "generic opening: 'landscape' as an abstract noun"),
    (r"\bin this (article|document|post|guide),? (we|i|you)\b", "preamble"),
    (r"\blast but not least\b", "formulaic ending"),
    (r"\bno (cenario|contexto) atual\b", "generic opening"),
    (r"\bnos dias atuais\b", "generic opening"),
    (r"\bpor fim,? mas nao menos importante\b", "formulaic ending"),
    (r"\bvale (destacar|ressaltar|mencionar|notar|lembrar)\b", "\"vale destacar\""),
    (r"\b(e|era) importante (ressaltar|destacar|notar|mencionar|lembrar)\b", "\"é importante ressaltar\""),
    (r"\bcabe (destacar|ressaltar|mencionar)\b", "\"cabe destacar\""),
    (r"\bit'?s (important|worth) (to note|noting|mentioning|highlighting)\b", "\"it's important to note\""),
    (r"\bmergulhar (profundamente|fundo)\b", "\"mergulhar profundamente\""),
    (r"\b(desbloquear|destravar) o potencial\b", "\"desbloquear o potencial\""),
    (r"\bunlock(ing)? (the|its|your) (full )?potential\b", "\"unlock the potential\""),
    (r"\bem sua essencia\b", "\"em sua essência\""),
    (r"\bat its core\b", "\"at its core\""),
    (r"\bno mundo de hoje\b", "generic opening"),
    (r"\bnos dias de hoje\b", "generic opening"),
    (r"\bde forma geral\b", "filler"),
    (r"\bem ultima analise\b", "filler"),
    (r"\bpode-se dizer que\b", "filler"),
    (r"\bnao se trata de\b[^.;!?]{0,80}?,\s*(e|mas)\b", "\"não se trata de X, mas de Y\""),
    # chatbot residue
    (r"\bi hope this helps\b", "chatbot residue"),
    (r"\b(espero que (isso )?ajude|qualquer (duvida|coisa) (me )?(avise|chama))\b", "chatbot residue"),
    (r"\blet me know if (you|there)\b", "chatbot residue"),
    (r"\b(would|want) (you like )?me to\b.*\?", "chatbot residue"),
    (r"^\s*(certainly|of course|great question|absolutely)[!,]", "chatbot opening"),
    (r"\byou'?re absolutely right\b", "chatbot agreement"),
    (r"\b(great|excellent|brilliant|fantastic|impressive|wonderful) "
     r"(idea|question|point|approach|concept|suggestion)\b", "generic praise"),
    # throat-clearing and faux insight
    (r"\bhere'?s the thing\b", "throat-clearing"),
    (r"\b(let me be clear|i'?ll be honest|real talk)\b", "throat-clearing"),
    (r"^\s*(honestly|look)[,?]", "theatrical opening"),
    (r"\bthe uncomfortable truth is\b", "throat-clearing"),
    (r"\bwhat (most people|everyone) (gets? wrong|misses)\b", "faux insight"),
    (r"\b(here'?s )?what nobody tells you\b", "faux insight"),
    (r"\bthe part (everyone|most people) (misses|skips?)\b", "faux insight"),
    # announcing the next point
    (r"\blet'?s (dive in|dive into|explore|break this down|look at)\b", "announces instead of saying"),
    (r"\bhere'?s what you need to know\b", "announces instead of saying"),
    (r"\bwithout further ado\b", "announces instead of saying"),
    (r"\bvamos (explorar|mergulhar|analisar) (a|o|as|os)\b", "announces instead of saying"),
    (r"\bneste (documento|artigo),? (vamos|iremos)\b", "preamble"),
    # endings
    (r"^\s*(in (conclusion|summary)|ultimately|overall)\b", "generic ending"),
    (r"^\s*(em (conclusao|suma|resumo)|por fim(?!,? mas nao menos)|concluindo)\b",
     "generic ending"),
    (r"\bthe future looks bright\b", "empty optimistic ending"),
    (r"\bexciting times (lie |are )?ahead\b", "empty optimistic ending"),
    (r"\ba step in the right direction\b", "empty optimistic ending"),
    (r"\bwell positioned for\b", "empty optimistic ending"),
    # knowledge disclaimers and gap-filling
    (r"\bas of my last (training|update|knowledge)\b", "model disclaimer"),
    (r"\bwhile specific details (are|remain) (limited|scarce|not)\b", "disclaimer plus a guess"),
    (r"\bbased on (the )?available information\b", "model disclaimer"),
    (r"\b(maintains a low profile|prefers to stay out of the spotlight)\b", "guess presented as fact"),
    (r"\bit is believed that\b", "guess presented as fact"),
    # importance puffery
    (r"\b(stands|serves) as a (testament|reminder)\b", "importance puffery"),
    (r"\bmarks? a (pivotal|defining|key) (moment|turning point)\b", "importance puffery"),
    (r"\bplays? a (vital|crucial|key|central) role\b", "importance puffery"),
    (r"\bunderscores? (its|the|our) (importance|significance|commitment)\b", "importance puffery"),
    (r"\bsolidifies? (its|our) position\b", "importance puffery"),
    (r"\b(commitment|dedication) to (excellence|innovation|quality)\b", "importance puffery"),
    # last entries merged from humanizer and no-ai-slop
    (r"\bin the realm of\b", "vague: name the domain"),
    (r"\bde suma importancia\b", "importance puffery"),
    (r"\b(this changes everything|isso muda tudo)\b", "importance puffery"),
]

BANNED_HEADINGS = [
    (r"^vis(a|ã)o (abrangente|geral|completa|holistica|360)", "name what the section contains"),
    (r"^principais (insights|pontos|destaques|aprendizados|takeaways)", "name what the section contains"),
    (r"^destaques (estrategicos|principais)", "name what the section contains"),
    (r"^considera(c|ç)(o|õ)es finais", "the conclusion belongs at the start"),
    (r"^jornada de (implementa|ado|transforma)", "name the real phase"),
    (r"^(introdu(c|ç)(a|ã)o|conclus(a|ã)o|resumo executivo|contexto geral)$", "generic opening or ending"),
    (r"^(overview|key (insights|takeaways|highlights)|final (thoughts|considerations)|conclusion|introduction)$",
     "generic heading"),
    (r"^(the )?road ?map ahead$", "generic heading"),
    (r"^entendendo o\b", "generic heading"),
]

FILLER_HEDGES = [
    "basicamente", "essencialmente", "de certa forma", "de alguma forma",
    "fundamentalmente", "simplesmente", "obviamente", "claramente",
    "sem esforço",
    "basically", "essentially", "fundamentally", "arguably", "notably",
    "literally", "inevitably", "crucially",
]

# Certainty asserted instead of shown. The pt-BR adverbs "obviamente" and
# "claramente" already sit in FILLER_HEDGES and are not repeated here.
CERTAINTY_MARKERS = [
    r"\bundoubtedly\b", r"\bcertainly\b", r"\bundeniably\b", r"\bunquestionably\b",
    r"\bwithout (a|any) doubt\b", r"\bthere is no doubt\b",
    r"\bit is (clear|obvious|evident) that\b", r"\bclearly\b", r"\bobviously\b",
    r"\bsem (sombra de )?duvida\b", r"\binegavelmente\b", r"\bindubitavelmente\b",
    r"\bcertamente\b", r"\be (evidente|claro|obvio|inegavel) que\b", r"\bnao ha duvida\b",
]

# Connectives that announce a relation the sentences should carry themselves.
# Causal ones (because, therefore, as a result, however) are not here: they
# state a real relation. Density is the tell, so this feeds one count, not a
# finding per word.
GENERIC_TRANSITIONS = [
    r"\bfurthermore\b", r"\bmoreover\b", r"\badditionally\b", r"\bin addition\b",
    r"\bconsequently\b", r"\bon the other hand\b", r"\bimportantly\b",
    r"\bthat being said\b", r"\bwith that said\b", r"\bit should be noted\b",
    r"\balem disso\b", r"\bademais\b", r"\boutrossim\b", r"\bpor outro lado\b",
    r"\bconsequentemente\b", r"\bnesse sentido\b", r"\bdessa forma\b",
    r"\bdesse modo\b", r"\bsendo assim\b",
]

# Abstract nouns that hide who acts and what changes. One per sentence is
# ordinary technical prose ("the implementation reads the state once"); two or
# more in one sentence is the chain.
NOMINALIZATION_RE = re.compile(
    r"\b(implementation|optimi[sz]ation|transformation|enhancement|facilitation|"
    r"utili[sz]ation|alignment|enablement|prioriti[sz]ation|operationali[sz]ation|"
    r"implementacao|otimizacao|transformacao|aprimoramento|facilitacao|utilizacao|"
    r"alinhamento|habilitacao|priorizacao|operacionalizacao|viabilizacao)\b")

# Judgement calls: a real shape often hides here, so these are WARN, not ERROR.
SOFT_CONSTRUCTIONS = [
    # weasel attribution
    (r"\b(experts?|observers?|critics?|analysts?) (agree|argue|note|believe|have noted)\b",
     "vague attribution: name the source or cut the claim"),
    (r"\b(industry reports?|studies|research) (suggest|show|indicate)\b",
     "vague attribution: name the source or cut the claim"),
    (r"\b(especialistas|analistas) (afirmam|apontam|acreditam)\b",
     "vague attribution: name the source or cut the claim"),
    (r"\b(widely|generally) (regarded|considered) as\b",
     "vague attribution: name the source or cut the claim"),
    # shallow -ing analysis
    (r",\s*(highlighting|underscoring|emphasizing|reflecting|symbolizing|showcasing|"
     r"ensuring|fostering|contributing to|encompassing)\b",
     "shallow analysis in an -ing clause: state the consequence"),
    # avoiding is/has
    (r"\b(serves|stands) as (a|an|the)\b", "use 'is'"),
    (r"\b(boasts|features|offers) (a|an|over|more than)\b", "use 'has'"),
    # weak verb phrases
    (r"\bhas the ability to\b", "use 'can'"),
    (r"\b(made|make) a decision\b", "use 'decided' / 'decide'"),
    (r"\bprovides support for\b", "use 'supports'"),
    (r"\bis responsible for (handling|managing)\b", "use 'handles' / 'manages'"),
    (r"\b(realiza|efetua) (a|o) (verificacao|validacao|analise)\b", "use the direct verb"),
    # fake alternatives
    (r"\b(a tempting|an obvious) (approach|option) would be\b",
     "fake alternative: state the real constraint"),
    (r"\bone might be tempted to\b", "fake alternative: state the real constraint"),
    (r"\bit would be easy to just\b", "fake alternative: state the real constraint"),
    # objections nobody raised
    (r"\bi'?m not (saying|arguing|claiming)\b", "objection nobody raised"),
    (r"\bdon'?t get me wrong\b", "objection nobody raised"),
    (r"\bthis is not to say\b", "objection nobody raised"),
    # metadiscourse
    (r"\bthe key point is\b", "metadiscourse: delete it or replace it with the fact"),
    (r"\bas you can see\b", "metadiscourse: delete it or replace it with the fact"),
    (r"\bthis distinction matters\b", "metadiscourse: delete it or replace it with the fact"),
    (r"\bin other words\b", "metadiscourse: say it right the first time"),
    (r"\bvale (a pena )?entender que\b", "metadiscourse: delete it or replace it with the fact"),
    # revealing a deeper truth
    (r"\bthe real (question|issue|problem) is\b", "pseudo-revelation"),
    (r"\bwhat really matters\b", "pseudo-revelation"),
    (r"\bthe (deeper issue|heart of the matter)\b", "pseudo-revelation"),
    # stacked hedges
    (r"\b(could|might) (potentially|possibly|arguably)\b", "stacked hedge"),
    (r"\bit could be argued that\b", "stacked hedge"),
    (r"\bin some cases it may\b", "stacked hedge"),
    # formulaic sayings
    (r"\bis the (language|currency|architecture) of\b", "formulaic saying"),
    # false range
    (r"\bfrom [^,;.]{3,40} to [^,;.]{3,40},\s*from [^,;.]{3,40} to\b",
     "false range 'from X to Y': list the items"),
]

CURLY_RE = re.compile("[\u201c\u201d\u2018\u2019]")
# Matches both "- **Label:** text" and "- **Label**: text".
BOLD_LABEL_RE = re.compile(r"^\s*[-*+]\s+\*\*[^*\n]{2,40}(?::\*\*|\*\*\s*:)")

EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002700-\U000027BF" "\U00002600-\U000026FF"
    "\U0001F1E6-\U0001F1FF" "✅❌❗⭐" "]"
)

# "A, B e C": the tail of the pre-comma chunk, then two short items joined by
# "e"/"and". Items are bounded by punctuation so the first group cannot swallow
# the whole clause.
TRICOLON_RE = re.compile(
    r"([^,;:.!?()\[\]]+),\s+([^,;:.!?()\[\]]{2,40}?),?\s+(?:e|and)\s+"
    r"([^,;:.!?()\[\]]{2,40}?)(?=\s*[.,;:!?)\]]|\s*$)"
)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ý\"'“])")


@dataclass
class Finding:
    severity: str
    check: str
    line: int
    message: str
    evidence: str


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def severity(lineno: int, base: str = "ERROR", term: str = "") -> tuple[str, str]:
    """Return (severity, suffix). A finding inside a blockquote or on a term the
    document declared intentional is reported but does not block delivery."""
    if term and strip_accents(term).lower() in ALLOWED:
        return "WARN", " (declared intentional)"
    if lineno in QUOTED:
        return "WARN", " (inside a blockquote: quotation or example?)"
    return base, ""


def check_lexicon(prose, findings):
    for lineno, line in prose:
        flat = strip_accents(line).lower()
        for word, why in BANNED_LEXICON.items():
            if re.search(rf"\b{re.escape(word)}\b", flat):
                sev, note = severity(lineno, "ERROR", word)
                findings.append(Finding(
                    sev, "banned-lexicon", lineno,
                    f"'{word}': {why}{note}", line.strip()[:160]))


def scan_constructions(prose, table):
    # Markdown prose is hard-wrapped, so a multi-word construction routinely
    # straddles a line break. Test each line alone first; only if that misses,
    # test it joined with the following line. One finding per pattern per line,
    # reported at the line where the construction starts.
    for i, (lineno, line) in enumerate(prose):
        if not line.strip():
            continue
        flat = strip_accents(line).lower()
        nxt = prose[i + 1][1] if i + 1 < len(prose) else ""
        joined = strip_accents(f"{line.rstrip()} {nxt.lstrip()}").lower()
        for pattern, label in table:
            if re.search(pattern, flat):
                yield lineno, label, line.strip()[:160]
            elif nxt.strip() and re.search(pattern, joined):
                yield lineno, label, joined.strip()[:160]


def check_constructions(prose, findings):
    for lineno, label, evidence in scan_constructions(prose, BANNED_CONSTRUCTIONS):
        sev, note = severity(lineno, "ERROR")
        findings.append(Finding(
            sev, "banned-construction", lineno,
            f"banned construction: {label}{note}", evidence))


def check_headings(prose, findings):
    seen_first_words: dict[str, list[int]] = {}
    for lineno, line in prose:
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$", line)
        if not m:
            continue
        title = m.group(2).strip().rstrip(":")
        flat = strip_accents(title).lower()
        for pattern, why in BANNED_HEADINGS:
            if re.search(pattern, flat):
                findings.append(Finding(
                    "ERROR", "banned-heading", lineno,
                    f"generic heading: {why}", title[:120]))
                break
        words = [w for w in re.findall(r"[\wÀ-ſ']+", title)]
        if len(words) >= 3:
            caps = sum(1 for w in words[1:] if w[:1].isupper() and not w.isupper())
            if caps >= len(words) - 1:
                findings.append(Finding(
                    "WARN", "title-case-heading", lineno,
                    "Title Case heading; capitalise only the first word",
                    title[:120]))
        if words:
            seen_first_words.setdefault(strip_accents(words[0]).lower(), []).append(lineno)
    for word, linenos in seen_first_words.items():
        if len(linenos) >= 3:
            findings.append(Finding(
                "WARN", "heading-monotony", linenos[0],
                f"{len(linenos)} headings start with '{word}' (lines "
                f"{', '.join(map(str, linenos))})", word))


def check_tricolon(prose, findings):
    """Flag "A, B e C" where the three items are short and near-equal in length —
    the signature of a group built for rhythm rather than for content (rule 7)."""
    for lineno, line in prose:
        if line.lstrip().startswith("#"):
            continue
        for m in TRICOLON_RE.finditer(line):
            second = m.group(2).split()
            third = m.group(3).split()
            if not second or not third:
                continue
            if len(second) > 3 or len(third) > 3:
                continue
            if abs(len(second) - len(third)) > 1:
                continue
            # first item = the tail of the pre-comma chunk, same width as the third
            head = m.group(1).split()
            first = " ".join(head[-len(third):]) if head else ""
            if not first:
                continue
            items = [first, " ".join(second), " ".join(third)]
            findings.append(Finding(
                "WARN", "forced-tricolon", lineno,
                "group of three items of equal length; confirm that all "
                "three are facts, not rhythm", ", ".join(items)[:120]))


def check_list_ratio(prose, findings):
    body = [(n, l) for n, l in prose if l.strip() and not l.lstrip().startswith("#")]
    if len(body) < 12:
        return
    bullets = [n for n, l in body if re.match(r"^\s*([-*+]|\d+[.)])\s+", l)]
    ratio = len(bullets) / len(body)
    if ratio > 0.45:
        findings.append(Finding(
            "ERROR", "list-over-prose", bullets[0] if bullets else 1,
            f"{ratio:.0%} of the body lines are list items; the reasoning "
            "belongs in paragraphs", f"{len(bullets)}/{len(body)} lines"))
    elif ratio > 0.35:
        findings.append(Finding(
            "WARN", "list-over-prose", bullets[0] if bullets else 1,
            f"{ratio:.0%} of the body lines are lists", f"{len(bullets)}/{len(body)}"))

    # runs of >= 6 consecutive bullets
    run, start = 0, 0
    for n, l in body:
        if re.match(r"^\s*([-*+]|\d+[.)])\s+", l):
            if run == 0:
                start = n
            run += 1
        else:
            if run >= 7:
                findings.append(Finding(
                    "WARN", "long-bullet-run", start,
                    f"{run} bullets in a row; probably prose cut into pieces", ""))
            run = 0
    if run >= 7:
        findings.append(Finding("WARN", "long-bullet-run", start,
                                f"{run} bullets in a row", ""))


def sentences_of(prose):
    paras: list[tuple[int, str]] = []
    buf, start = [], None
    for n, l in prose:
        if l.lstrip().startswith("#") or re.match(r"^\s*([-*+]|\d+[.)])\s+", l):
            continue
        if l.strip():
            if start is None:
                start = n
            buf.append(l.strip())
        else:
            if buf:
                paras.append((start, " ".join(buf)))
            buf, start = [], None
    if buf:
        paras.append((start, " ".join(buf)))
    return paras


def check_rhythm(prose, findings):
    paras = sentences_of(prose)
    lengths, located = [], []
    for start, para in paras:
        for s in SENTENCE_SPLIT_RE.split(para):
            words = re.findall(r"[\wÀ-ſ]+", s)
            if len(words) >= 3:
                lengths.append(len(words))
                located.append((start, s))
    if len(lengths) >= 8:
        sd = statistics.pstdev(lengths)
        mean = statistics.fmean(lengths)
        if sd < 4.5:
            findings.append(Finding(
                "WARN", "uniform-rhythm", located[0][0],
                f"uniform sentence length (mean {mean:.0f}, deviation {sd:.1f} "
                "words); vary the rhythm", ""))
        # the count is the one already measured above: a regex inside the f-string broke
        # Python < 3.12 and, in raw form, matched only backslashes and "w" (always 0 words)
        long_ones = [(st, s, ln) for (st, s), ln in zip(located, lengths) if ln > 45]
        for st, s, ln in long_ones[:5]:
            findings.append(Finding(
                "WARN", "long-sentence", st,
                f"sentence of {ln} words", s[:120]))

    openers: dict[str, list[int]] = {}
    for start, para in paras:
        w = re.findall(r"[\wÀ-ſ]+", para)
        if w:
            openers.setdefault(strip_accents(w[0]).lower(), []).append(start)
    for word, lns in openers.items():
        if len(lns) >= 3 and word not in ("o", "a", "os", "as", "the"):
            findings.append(Finding(
                "WARN", "repeated-paragraph-opening", lns[0],
                f"{len(lns)} paragraphs start with '{word}' (lines "
                f"{', '.join(map(str, lns))})", word))


def check_density(prose, findings):
    text = " ".join(l for _, l in prose)
    words = len(re.findall(r"[\wÀ-ſ]+", text))
    if words < 120:
        return
    bold = len(re.findall(r"\*\*[^*\n]+\*\*", text))
    if bold / words * 100 > 3:
        findings.append(Finding(
            "WARN", "bold-density", 1,
            f"{bold} bold spans in {words} words; bold stops working "
            "when it is frequent", ""))
    # Count every em/en dash, spaced or not: the old regex only saw " — ".
    dashes = len(re.findall(r"[—–]", text))
    if not PROFILE_DASHES and dashes / words * 100 > 1.2:
        findings.append(Finding(
            "WARN", "dash-density", 1,
            f"{dashes} em or en dashes in {words} words", ""))


def check_misc(prose, findings):
    for lineno, line in prose:
        for m in EMOJI_RE.finditer(line):
            if ALLOW_EMOJI or PROFILE_EMOJI:
                findings.append(Finding("WARN", "emoji", lineno,
                                        "emoji (declared intentional)", m.group(0)))
            else:
                sev, note = severity(lineno, "ERROR")
                findings.append(Finding(sev, "emoji", lineno,
                                        f"emoji in a professional document{note}",
                                        m.group(0)))
        flat = strip_accents(line).lower()
        for hedge in FILLER_HEDGES:
            if re.search(rf"\b{re.escape(strip_accents(hedge))}\b", flat):
                findings.append(Finding("WARN", "filler", lineno,
                                        f"filler '{hedge}'", line.strip()[:120]))
        if re.search(r"\bcomo (um )?(modelo|IA|assistente) de linguagem\b", flat) or \
           re.search(r"\bas an ai (language )?model\b", flat):
            findings.append(Finding("ERROR", "chatbot-artifact", lineno,
                                    "chatbot text left in the document",
                                    line.strip()[:120]))
        if re.search(r"\b(certamente|com certeza|claro)[!,]", flat) and lineno < 8:
            findings.append(Finding("WARN", "chatbot-artifact", lineno,
                                    "chatbot opening", line.strip()[:120]))


PROPER_RE = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-ZÀ-Ý][\wÀ-ſ.-]{2,}")


def check_portability(prose, findings):
    """Sentences with no number, identifier, or proper noun could belong to any
    company. Rule 18. Heuristic — reported as WARN only."""
    for start, para in sentences_of(prose):
        for s in SENTENCE_SPLIT_RE.split(para):
            words = re.findall(r"[\wÀ-ſ]+", s)
            if len(words) < 10:
                continue
            has_number = bool(re.search(r"\d", s))
            has_proper = bool(PROPER_RE.search(s))
            has_tech = bool(re.search(
                r"\b(AWS|Terraform|GitHub|Jira|Datadog|Entra|Intune|IAM|S3|VPC|"
                r"CloudTrail|PR|ADR|CI|SLA|OIDC|Kubernetes|Lambda|RDS)\b", s))
            if not (has_number or has_proper or has_tech):
                findings.append(Finding(
                    "WARN", "portability", start,
                    "sentence with no number, proper noun or project term; "
                    "it could sit in any document", s.strip()[:140]))


def check_soft_constructions(prose, findings):
    # WARN-level shapes: frequently slop, occasionally the right sentence.
    for lineno, label, evidence in scan_constructions(prose, SOFT_CONSTRUCTIONS):
        findings.append(Finding("WARN", "soft-construction", lineno, label, evidence))


def check_dashes(prose, findings):
    # A dash with no space on either side is always wrong in this style, at any
    # density, and is the form the density check used to miss entirely.
    if PROFILE_DASHES:
        return
    for lineno, line in prose:
        for m in re.finditer(r"\w[—–]\w", line):
            findings.append(Finding(
                "WARN", "tight-dash", lineno,
                "dash glued to the words; use a full stop, a comma or parentheses",
                m.group(0)))


def check_quotes(prose, findings):
    # Curly quotes are a chatbot tell only in text destined for a plain-text
    # target (markdown, code, CLI). Reported as WARN so an editor's own habit or
    # a CMS that wants curly quotes does not block delivery.
    if PROFILE_QUOTES:
        return
    for lineno, line in prose:
        if CURLY_RE.search(line):
            findings.append(Finding(
                "WARN", "curly-quotes", lineno,
                "curly quotes; use straight quotes unless the format requires curly ones",
                line.strip()[:120]))


def check_bold_label_list(prose, findings):
    # Three or more consecutive "- **Label:** sentence" items is usually prose
    # wearing a list costume.
    run: list[int] = []
    for lineno, line in prose:
        if BOLD_LABEL_RE.match(line):
            run.append(lineno)
            continue
        if line.strip() == "":
            continue
        if len(run) >= 3:
            findings.append(Finding(
                "WARN", "bold-label-list", run[0],
                f"{len(run)} items shaped '- **Label:** sentence' (lines "
                f"{', '.join(map(str, run))}); usually prose", ""))
        run = []
    if len(run) >= 3:
        findings.append(Finding(
            "WARN", "bold-label-list", run[0],
            f"{len(run)} items shaped '- **Label:** sentence'; usually prose", ""))


def check_certainty(prose, findings):
    # "Undoubtedly" is a claim with the evidence left out. The fix is to show the
    # evidence or keep the hedge, never to strengthen the sentence further.
    for lineno, line in prose:
        flat = strip_accents(line).lower()
        for pattern in CERTAINTY_MARKERS:
            for m in re.finditer(pattern, flat):
                sev, note = severity(lineno, "WARN", m.group(0))
                findings.append(Finding(
                    sev, "unsupported-certainty", lineno,
                    f"certainty asserted without evidence: '{m.group(0)}'; show the "
                    f"evidence or keep the hedge{note}", line.strip()[:120]))


def check_transitions(prose, findings):
    text = " ".join(l for _, l in prose)
    words = len(re.findall(r"[\wÀ-ſ]+", text))
    if words == 0:
        return
    hits: list[tuple[int, str]] = []
    for lineno, line in prose:
        flat = strip_accents(line).lower()
        for pattern in GENERIC_TRANSITIONS:
            for m in re.finditer(pattern, flat):
                hits.append((lineno, m.group(0)))
    if len(hits) >= 3 and len(hits) / words * 100 > 0.8:
        lines = sorted({n for n, _ in hits})
        findings.append(Finding(
            "WARN", "transition-density", lines[0],
            f"{len(hits)} generic transitions in {words} words (lines "
            f"{', '.join(map(str, lines))}); cut the ones that do not link an argument",
            ", ".join(sorted({t for _, t in hits}))))


def check_nominalization(prose, findings):
    for start, para in sentences_of(prose):
        for s in SENTENCE_SPLIT_RE.split(para):
            flat = strip_accents(s).lower()
            nouns = NOMINALIZATION_RE.findall(flat)
            if len(nouns) >= 2:
                findings.append(Finding(
                    "WARN", "nominalization", start,
                    f"chain of abstract nouns ({', '.join(nouns)}); say "
                    "who does what, with the verb", s.strip()[:140]))


def check_paragraph_symmetry(prose, findings):
    # Equal-sized paragraphs are the paragraph-level twin of uniform-rhythm:
    # a template filled in, not an argument made.
    paras = sentences_of(prose)
    sizes = [n for n in (len(re.findall(r"[\wÀ-ſ]+", para)) for _, para in paras) if n > 0]
    if len(sizes) < 5:
        return
    mean = statistics.fmean(sizes)
    if mean < 20:
        return
    cv = statistics.pstdev(sizes) / mean
    if cv < 0.2:
        findings.append(Finding(
            "WARN", "uniform-paragraphs", paras[0][0],
            f"{len(sizes)} paragraphs of nearly equal size (mean {mean:.0f} "
            f"words, variation {cv:.0%}); vary them, or merge the ones that make one point",
            ", ".join(map(str, sizes))))


CHECKS = [check_lexicon, check_constructions, check_soft_constructions,
          check_headings, check_tricolon, check_list_ratio, check_rhythm,
          check_density, check_misc, check_dashes, check_quotes,
          check_bold_label_list, check_certainty, check_transitions,
          check_nominalization, check_paragraph_symmetry,
          check_portability]


def load_profile(path: Path) -> dict:
    """Read a voice profile: a YAML file, or a markdown file whose first
    ```yaml fence holds it. Only flat `key: value` pairs and `- item` lists are
    read, which is all the format defines, so no YAML library is needed."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"```ya?ml[^\n]*\n(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    data: dict = {}
    key = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if key and re.match(r"^\s*-\s+", line):
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(line.split("-", 1)[1].strip().strip("'\""))
            continue
        if line[0] in " \t":
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip("'\"")
            data[key] = val if val else []
    return data


def apply_profile(profile: dict) -> None:
    global PROFILE_DASHES, PROFILE_QUOTES, PROFILE_EMOJI
    allow = profile.get("allow", [])
    if isinstance(allow, str):
        allow = re.split(r"[,;]", allow)
    CLI_ALLOWED.update(strip_accents(t).lower() for t in allow if t.strip())
    PROFILE_DASHES = str(profile.get("dashes", "")).lower() in ("writer", "keep")
    PROFILE_QUOTES = str(profile.get("quotes", "")).lower() in ("curly", "writer", "keep")
    PROFILE_EMOJI = str(profile.get("emoji", "")).lower() in ("allow", "writer", "keep")


def clean_evidence(findings: list["Finding"]) -> None:
    for f in findings:
        f.evidence = re.sub(r"\s*CODEREF\s*", " ", f.evidence).strip()


def lint(path: Path) -> list[Finding]:
    prose = split_document(path.read_text(encoding="utf-8"))
    findings: list[Finding] = []
    for check in CHECKS:
        check(prose, findings)
    clean_evidence(findings)
    return sorted(findings, key=lambda f: (f.line, f.check))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn-as-error", action="store_true")
    ap.add_argument("--allow", action="append", default=[], metavar="TERM",
                    help="lexicon term to treat as intentional; repeatable. "
                         "The in-file equivalent is "
                         "'<!-- writing: allow <term> -->'")
    ap.add_argument("--profile", type=Path, metavar="FILE",
                    help="voice profile (references/voice-profile.md): allowed "
                         "terms and dash, quote and emoji habits")
    args = ap.parse_args()

    CLI_ALLOWED.update(strip_accents(x).lower() for x in args.allow)
    if args.profile is not None:
        if not args.profile.is_file():
            print(f"slop_lint: {args.profile}: profile not found", file=sys.stderr)
            return 2
        apply_profile(load_profile(args.profile))

    exit_code = 0
    report = {}
    for path in args.files:
        if not path.is_file():
            print(f"slop_lint: {path}: file not found", file=sys.stderr)
            return 2
        findings = lint(path)
        report[str(path)] = [asdict(f) for f in findings]
        errors = [f for f in findings if f.severity == "ERROR"]
        warns = [f for f in findings if f.severity == "WARN"]
        if errors or (args.warn_as_error and warns):
            exit_code = 1
        if args.json:
            continue
        print(f"\n=== {path} ===")
        if not findings:
            print("clean: no slop signal found")
        for f in findings:
            print(f"{path}:{f.line}: {f.severity}: [{f.check}] {f.message}")
            if f.evidence:
                print(f"    > {f.evidence}")
        print(f"\n{len(errors)} ERROR, {len(warns)} WARN")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
