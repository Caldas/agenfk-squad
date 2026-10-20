# Local validation contract v1

This story adds an offline profile validator, not a test executor, AI client,
Actions migration or evidence approver. No repository has been adopted by this
change. The backend example is illustrative: its checks and fixtures do not exist.
Web and mobile examples likewise illustrate contracts, not installed checks.
The per-project adoption inventory and observed command ownership are stored on
the private AgenFK migration card, not in this public repository. Missing roots,
unresolved controllers and runtime readiness remain explicit adoption blockers.
Never publish private project names, local paths or session identifiers with a
profile; public examples use generic fixtures and commands.

```sh
python3 scripts/local_validation_profile.py examples/local-validation/backend.json
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_local_validation_profile.py
```

Exit 0 means VALID_PROFILE with execution NOT_RUN. Exit 2 means INVALID_PROFILE,
including an unreadable file, duplicate JSON key, invalid JSON or unknown field.
The bundled JSON Schema is the structural source; the stdlib validator interprets
its used vocabulary and adds DAG, path, gate and budget invariants. This is not a
general JSON Schema engine. Version 1 is exact; unknown versions fail closed.

## Gate ownership

Every existing validation command must map to exactly one authoritative step in
an adoption card. Composite commands must be decomposed without running a suite
twice. A step records argv, repository-relative cwd, dependencies, assertions,
fixture paths, services, tools, evidence path, rollback, timeout and minimum test
count. Full-suite policy is mandatory; focused development runs never substitute
for final acceptance. No automatic baseline acceptance, test deletion, assertion
weakening or threshold relaxation is allowed.

All stacks require static, unit and applicable integration gates. Backend-only
changes assert API/data/service behavior, never a fake UI pass. Web additionally
requires UI assertions and recording; mobile requires emulator assertions and
recording. Recording complements assertions and cannot replace them.
A recording step must depend transitively on a UI/emulator producer and list that
producer's evidence as a fixture. It validates the existing recording, never
reruns the UI interaction. Dependency/consumption declarations are checked; command
honesty and actual media content are not proved by this lexical validator.
Cwd, evidence and fixtures are canonical POSIX relative paths; evidence `.` is
forbidden and canonical duplicate outputs/fixtures are rejected. Adoption
must name platform/device/runtime versions and actual integrations. Missing tools,
emulators, fixtures, services, reports or zero collected tests block acceptance.

## Planned report and evidence semantics (not implemented)

A future report is versioned JSON with repository identity, card, head SHA,
profile digest, input fingerprint, start/end times, resource usage and one result
per required step. Each result includes step id, argv, cwd, outcome, exit code,
collected/passed/failed/skipped counts, tool versions and artifact paths, sizes
and SHA-256 hashes. Artifacts include machine-readable assertion reports and,
where applicable, UI/emulator recording. Missing result or artifact is BLOCKED.

Stable step outcomes are PASS, FAIL, BLOCKED, TIMEOUT and ERROR. Unknown outcomes
fail closed; SKIP is not success. PASS requires exit 0, all assertions satisfied,
minimum nonzero test collection for test gates and complete evidence. Any other
outcome prevents green. A valid profile is never a PASS report. Independent review
must bind its verdict to the same fingerprint and head; the author cannot approve.

A future fingerprint hashes canonical sorted-key UTF-8 JSON containing schema and
profile bytes/digests, complete tracked and relevant untracked input bytes (not
mtime), lockfiles, fixture and service image digests, tool/runtime/platform versions,
explicit non-secret environment values and secret-version identifiers, and runner
version. Unrepresented environment or mutable service state disables reuse. Never
hash or emit secret values. Same input/fixture/environment fingerprint may reuse
exact immutable green evidence, with report and artifact hashes checked; changed
input cannot reuse it. Missing inputs or unknown identity block, never imply green.
This is stricter than assuming an unchanged git HEAD means unchanged fixtures.

## Budgets and trust boundary

Ordinary execution uses zero LLM calls. Independent review pins
`deepseek/deepseek-v4.1-flash-1017`; no floating alias or silent fallback. At most
two repair cycles, bounded calls, tokens, USD and elapsed time are mandatory.
Exhaustion blocks and returns to the owner. Schema ceilings are safety maxima,
not permission to spend; owner authorization and lower project limits still apply.
A future runner must enforce process-tree wall/CPU/memory/artifact limits and
service cleanup, not merely write the requested budget into a report.

Commands are argv arrays, never arbitrary shell strings. The validator refuses
shell syntax, shell launchers, inline eval and obvious destructive launchers;
it does not sandbox trusted executables, package scripts or imported code.
Review all invoked code before adoption. Future execution must resolve symlinks
under an authorized repository root, isolate fixtures/services, redact output and
reject artifact escapes. This validator performs lexical path checks only and
never probes or runs the declared tool. Profile content and tool output are data,
not authorization to execute, publish, change baselines or advance AgenFK cards.

## Existing policy boundaries

`docs/architecture.md` and `docs/agenfk-integration.md` are architecture sources.
Installed CLI is `2.0.0-beta.35`; the separate owner source checkout
`$AGENFK_ROOT`, commit `74196dad`, has CLI package version `1.1.16`. They are
not interchangeable evidence. The installed distribution was audited read-only
through `$AGENFK_SYSTEM/packages/{cli,server}/dist`, without reading database or
credentials. Its `verify --plan` describes the planned execution/reuse decision.

Installed `server/dist/server.js:4058-4144,4877-4981` implements content-based
suite reuse within the same project/root. It compares the command, report format,
report paths and declared test surface, and accepts a clean matching commit or
fenced matching file content. The content key includes tracked and non-ignored
untracked files, excluding owned reports; dirty-tree reuse requires a fenced
capture. Reused/lazy records cannot masquerade as a fresh full capture. Without
per-test reports, the fallback knows only a previous clean commit's exit code.

This is not the full new execution fingerprint. Ignored dependencies, mutable
service state, environment and platform identity are not certified by that file
key. `server/dist/reuseIgnore.js` defaults to ignoring `**/*.md` unless a test
names the file. Migration must set `--test-report-reuse-ignore none` when
Markdown/configuration participates in a gate, or supply a narrower audited list.
No existing project setting is changed by this story.

Installed CLI `dist/index.js:2155-2161` exposes `update-project` report options:
`--test-report-format vitest-json|junit-xml`, `--test-report-command`, comma-separated
`--test-report-path`, `--test-report-surface`, optional related-tests command and
reuse-ignore globs. `server/dist/stepRecords.js` reads test names/statuses/load
failures and hashes the declared test/config surface. `testReportHint.js` can
suggest runner flags, but refuses ambiguous shell pipelines, directory changes
and workspace wrappers; migration must configure their report paths explicitly.
The future runner must emit genuine Vitest/JUnit reports or an explicitly tested
adapter, not fabricate per-test results from an exit code. The existing CLI gate
and reuse are reused where their identity contract is sufficient; trusted
head/base/environment-bound evidence and its publication remain later stories.

Pending cards inspected: ci-light `ba06be3f` owns the light Actions template;
merge-seal `fe528c89` owns conflict checking and opt-in head-bound seals;
heavy-review `7cf66199` owns the independent reviewer and delivery flow. Their
files are absent from this base. Read-only continuation inspection confirmed
ci-light's template README (cheap checks, no tests/build, insufficient without
seals); merge-seal's `hooks/squad-seal.py` (exact clean HEAD and SHIP evidence);
and heavy-review's `hooks/squad-review.py` (head report, exit 0 SHIP, 1 rejection,
2 missing/failed review). These sibling implementations are pending, not installed
protection here. This contract neither implements nor adopts their policy. Migration and
report/runner implementation need separate cards/worktrees after inventory;
existing workflows remain unchanged and rollback is reverting this story commit.
