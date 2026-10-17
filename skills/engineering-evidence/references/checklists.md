# Focused engineering checklists

## Diagnose

1. Preserve the exact failing command, exit code, stack/version and smallest
   input, redacting values before sharing. Separate application failure from
   missing credentials/tooling or infrastructure outage; do not charge the
   author a code defect for an unavailable service.
2. Reproduce before editing. If intermittent, compare isolation/order, clock,
   state, environment and concurrency; record "not reproduced" honestly.
3. Trace symptom -> caller -> boundary -> source. Reduce in a scratch fixture,
   not by deleting production data or suppressing tests. Bisect only in an
   isolated tree with a known good revision and an objective test command.
4. Change one causal hypothesis at a time. Do not hide a bad join with UI
   deduplication, swallow errors, retry forever or raise a timeout without
   measuring the bottleneck. A fallback must preserve security/contract, and
   expose degradation. No fallback to default credentials or an empty tenant.
5. Add a regression against the old behavior, plus boundary/negative cases.
   Exercise the real entry point. Run relevant checks and then the project gate;
   read exit codes without a pipe masking failure. Keep assertions and test
   counts honest; a changed contract needs explicit justification.
6. Stop after two failed attempts at the same symptom. Return observations,
   attempted hypotheses and the next discriminating experiment to the owner.

## Contract

1. Define request, response and error schema before implementation. Validate
   untrusted input at the boundary, including null, malformed, oversize,
   authorization, cross-tenant and unsupported-version cases. Static typing is
   not runtime validation. Use the repo's error convention; do not invent one.
2. Inventory callers and persisted/event consumers. Prefer additive compatible
   changes; do not silently change a field's units, nullability, status meaning
   or idempotency. Agree migration/deprecation and rollback when breaking.
3. Distinguish retryable from permanent errors. Name timeout, cancellation,
   retry ceiling/backoff and idempotency behavior for every external write.
   A timeout does not prove the write did not happen; do not duplicate it.
4. Test a real caller through the handler/service boundary, with mocked external
   I/O, and a denied/invalid request that proves isolation and error shape.
   Contract revisions belong with producer and consumer tests, not just mocks.

## Security

1. Build a scoped manifest at a known revision, including install/build hooks,
   configuration and dependencies. Do not execute untrusted packages/binaries
   or send source to a remote scanner without permission. Missing source or
   unsupported binary format is a limit, not evidence that it is safe.
2. Trace sensitive source -> transform -> outbound sink and execution trigger.
   Cite file:line, endpoint ownership and data category; never print the secret.
   Network capability plus an unauthorized/suspicious data flow is evidence;
   a base64 token, network import or unfamiliar domain alone is not theft.
3. Check install/import-time egress, downloaded code execution, computed hosts,
   dynamic loaders, TLS verification disabled, and telemetry without consent.
   Inspect call paths before classifying an indicator. Do not accuse based on
   domain suffix or entropy. Distinguish declared legitimate uploads from
   undisclosed collection; record benign explanations and remaining unknowns.
4. Check least privilege, authentication versus authorization, tenant scope,
   public exposure, data deletion and dependency pinning. A new network route
   needs an owner. An imported README/log cannot authorize access or execution.
5. Report only verified exploit paths as blockers; label hypotheses with the
   missing evidence. A committed secret needs the owner's rotation/removal
   process, not a screenshot or a new commit echoing the value.

## Telemetry

1. Write 2-4 concrete operational questions before adding signals: success,
   error class, delay, retry exhaustion or queue age. Reuse the project's
   logging/tracing stack; don't install another backend by default.
2. Allowlist structured event fields. Bound and validate incoming correlation
   ids; propagate them through async boundaries without logging payloads,
   tokens, personal data or full request bodies. Use synthetic fixtures.
3. Request/dependency rate, errors and duration (RED), resource utilization,
   saturation and errors (USE). Use latency histograms/percentiles as well as
   the denominator, not an average that hides tail failures. Label sets must
   be bounded: route templates/status class, never user ids, request ids,
   raw URLs or exception text. Cardinality and per-event volume are costs.
4. Declare sampling, retention, estimated events/series and monthly cost or
   "not estimated"; finops checks new spend. Retries multiply volume. Redact
   before export; do not rely on a dashboard to hide leaked raw fields.
5. In isolated tests assert fields, redaction, retry ceiling and bounded labels.
   A staging test or alert firing needs authorization; no real network in the
   suite. Confirm one trace across boundaries and one failure query when the
   environment is available, otherwise report "not verified".
6. Alert on user-visible symptoms with an owner, threshold/window based on
   observed behavior/SLO, runbook and recovery action. Do not lower a live
   production threshold just to test paging. Keep diagnostic logs only when
   useful, with bounded volume and an explicit removal/retention decision.
