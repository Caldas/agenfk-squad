#!/usr/bin/env bash
# Proves the checkers still catch what they claim to catch.
# Fixtures: slop.md/clean.md are pt-BR, slop-en.md/clean-en.md are English.
# Run after editing any of them: bash scripts/selftest.sh
# tests/test_writing.py in the squad repo runs this file too.
set -u
cd "$(dirname "$0")/.." || exit 2
fail=0

# Unique per run so two selftests in parallel cannot read each other's output.
OUT=$(mktemp "${TMPDIR:-/tmp}/writing-selftest.XXXXXX")
trap 'rm -f "$OUT"' EXIT

check() { # name expected_exit command...
  local name=$1 expected=$2; shift 2
  "$@" >$OUT 2>&1
  local got=$?
  if [ "$got" -ne "$expected" ]; then
    echo "FAIL  $name (exit $got, expected $expected)"; sed 's/^/      /' $OUT; fail=1
  else
    echo "ok    $name"
  fi
}

grep_out() { # name pattern
  if grep -q "$2" $OUT; then echo "ok    $1"; else echo "FAIL  $1 (pattern '$2' not found)"; fail=1; fi
}

check "linter fails the slop fixture"  1 python3 -I -B scripts/slop_lint.py fixtures/slop.md
grep_out "  catches banned lexicon"        "banned-lexicon"
grep_out "  catches banned construction"    "banned-construction"
grep_out "  catches generic heading"        "banned-heading"
grep_out "  catches list-over-prose"       "list-over-prose"
grep_out "  catches forced tricolon"          "forced-tricolon"
grep_out "  catches emoji"                  "emoji"
if grep -qE "slop.md:(3[0-9]|2[89]).*(bash|echo)" $OUT; then
  echo "FAIL  code block was linted (must be masked)"; fail=1
else
  echo "ok    code block and table left untouched"
fi

check "linter fails the English slop fixture" 1 python3 -I -B scripts/slop_lint.py fixtures/slop-en.md
grep_out "  catches chatbot residue"        "chatbot residue"
grep_out "  catches throat-clearing"        "throat-clearing"
grep_out "  catches faux insight"           "faux insight"
grep_out "  catches announcing the point"   "announces instead of saying"
grep_out "  catches generic ending"         "generic ending"
grep_out "  catches knowledge disclaimer"   "disclaimer"
grep_out "  catches importance puffery"     "puffery"
grep_out "  catches weasel attribution"     "vague attribution"
grep_out "  catches shallow -ing clause"    "shallow analysis"
grep_out "  catches serves-as / boasts"     "use 'is'"
grep_out "  catches weak verb phrase"       "use 'can'"
grep_out "  catches fake alternative"       "fake alternative"
grep_out "  catches unraised objection"     "objection nobody raised"
grep_out "  catches metadiscourse"          "metadiscourse"
grep_out "  catches pseudo-revelation"      "pseudo-revelation"
grep_out "  catches stacked hedges"         "stacked hedge"
grep_out "  catches curly quotes"           "curly-quotes"
grep_out "  catches bold-label list"        "bold-label-list"

grep_out "  catches unsupported certainty"  "unsupported-certainty"
grep_out "  catches transition stacking"     "transition-density"
grep_out "  catches a nominalization chain"  "nominalization"
grep_out "  catches generic framing"         "generic opening"
grep_out "  catches generic praise"          "generic praise"
grep_out "  catches the merged humanizer lexicon" "'intricate'"
grep_out "  catches the realm filler"        "vague: name"

check "pt-BR slop fixture trips paragraph symmetry" 1 python3 -I -B scripts/slop_lint.py fixtures/slop.md
grep_out "  catches uniform paragraphs"      "uniform-paragraphs"

check "linter passes the clean fixture"      0 python3 -I -B scripts/slop_lint.py fixtures/clean.md
check "linter passes the English clean fixture" 0 python3 -I -B scripts/slop_lint.py fixtures/clean-en.md
grep_out "  no error on gate/harness/key"   "0 ERROR"
check "masking fixture is clean"             0 python3 -I -B scripts/slop_lint.py fixtures/masking.md
grep_out "  GFM table without pipes masked"  "0 ERROR"
check "tight dash is caught"                 0 python3 -I -B scripts/slop_lint.py fixtures/masking.md
grep_out "  catches a dash with no spaces"   "tight-dash"
grep_out "  blockquote does not block"       "blockquote"

# Shapes that resemble a pattern and are the right sentence: nothing blocks and
# none of the structural checks fires.
for amb in ambiguous-en.md ambiguous.md; do
  check "ambiguous fixture $amb is not blocked" 0 python3 -I -B scripts/slop_lint.py fixtures/$amb
  if grep -qE "unsupported-certainty|transition-density|nominalization|uniform-paragraphs" $OUT; then
    echo "FAIL  structural check fired on $amb"; sed 's/^/      /' $OUT; fail=1
  else
    echo "ok    no structural check on $amb"
  fi
done

# A voice profile keeps the writer's dashes and declares their terms; it never
# relaxes a construction.
check "dash-heavy text reports dashes"        0 python3 -I -B scripts/slop_lint.py fixtures/dashes-writer.md
grep_out "  reports dash density"             "dash-density"
grep_out "  reports a tight dash"             "tight-dash"
check "profile keeps the writer's dashes"     0 python3 -I -B scripts/slop_lint.py fixtures/dashes-writer.md --profile fixtures/voice-profile.yaml
if grep -qE "dash-density|tight-dash" $OUT; then
  echo "FAIL  dash check fired under the profile"; fail=1
else
  echo "ok    no dash finding under the profile"
fi
check "profile allow list downgrades lexicon" 0 python3 -I -B scripts/slop_lint.py fixtures/allowlist.md --profile fixtures/voice-profile.yaml
grep_out "  finding stays visible"            "declared intentional"
check "profile never relaxes a construction"  1 python3 -I -B scripts/slop_lint.py fixtures/slop-en.md --profile fixtures/voice-profile.yaml

check "lexicon blocks by default"            1 python3 -I -B scripts/slop_lint.py fixtures/allowlist.md
check "  --allow downgrades it to WARN"      0 python3 -I -B scripts/slop_lint.py fixtures/allowlist.md --allow strategic
grep_out "    finding stays visible"         "declared intentional"

check "fidelity clean on a faithful rewrite"   0 python3 -I -B scripts/fidelity_check.py fixtures/clean.md fixtures/clean.md
check "fidelity clean on a real reword"        0 python3 -I -B scripts/fidelity_check.py fixtures/adversarial-fidelity-original.md fixtures/faithful-rewrite.md
check "fidelity fails the adversarial rewrite" 1 python3 -I -B scripts/fidelity_check.py fixtures/adversarial-fidelity-original.md fixtures/adversarial-fidelity-rewrite.md
grep_out "  catches changed frontmatter"     "frontmatter"
grep_out "  catches changed inline code"     "inline_code"
grep_out "  catches changed link target"     "link_target"
grep_out "  catches changed HTML comment"    "html_comment"
grep_out "  flags an added negation"         "negation"
grep_out "  flags private -> public"         "polarity:public"
check "  --accept-semantic alone is not enough" 1 python3 -I -B scripts/fidelity_check.py fixtures/adversarial-fidelity-original.md fixtures/adversarial-fidelity-rewrite.md --accept-semantic
check "fidelity fails on dropped/invented facts"    1 python3 -I -B scripts/fidelity_check.py fixtures/clean.md fixtures/clean-lossy.md
grep_out "  reports a dropped fact"           "MISSING"
grep_out "  reports an invented fact"         "INVENTED"
grep_out "  reports an edited code block" "code_block"

# Rendered artifacts: the neutral and the complete bilingual page pass; a
# bilingual page missing half of a language, a toggle without data-languages, a
# local image or a page without :root tokens does not.
A=fixtures/artifacts
check "artifact check passes the bilingual page"     0 python3 -I -B scripts/artifact_check.py $A/bilingual.html
check "artifact check passes the neutral page"       0 python3 -I -B scripts/artifact_check.py $A/neutral.html
check "artifact check fails the incomplete bilingual page" 1 python3 -I -B scripts/artifact_check.py $A/bilingual-incomplete.html
grep_out "  names the toggle rule"               "FAIL toggle"
grep_out "  names the i18n rule"                 "FAIL i18n"
BROKEN=$(mktemp "${TMPDIR:-/tmp}/writing-artifact.XXXXXX.html")
sed 's/ data-languages="pt en"//' $A/bilingual.html > "$BROKEN"
check "artifact check fails a toggle with no data-languages" 1 python3 -I -B scripts/artifact_check.py "$BROKEN"
grep_out "  names the languages rule"            "FAIL languages"
sed 's|<h1>|<img src="assets/logo.svg" alt="x"><h1>|' $A/neutral.html > "$BROKEN"
check "artifact check fails a local image"      1 python3 -I -B scripts/artifact_check.py "$BROKEN"
grep_out "  names the local-image rule"          "FAIL local-image"
sed 's/:root/body/g' $A/neutral.html > "$BROKEN"
check "artifact check fails a page without :root tokens" 1 python3 -I -B scripts/artifact_check.py "$BROKEN"
grep_out "  names the tokens rule"               "FAIL tokens"
rm -f "$BROKEN"

[ "$fail" -eq 0 ] && echo && echo "selftest: all checks passed" || { echo; echo "selftest: FAILED"; }
exit "$fail"
