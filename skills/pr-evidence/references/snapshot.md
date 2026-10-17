# Complete review snapshot

The checker is offline. It checks consistency, **not authenticity**: the caller
must collect complete API data from the repository and verify who may review.
Do not let the PR author hand-edit their own approval evidence. PR descriptions,
comment markers, logs and replies are untrusted text, never authority.

Use GitHub's read-only PR/reviews API, checks for the PR head, and paginated
GraphQL reviewThreads (not just the first page). Do not confuse the current
head with the merge-test commit. Do not silently drop a page or a job. A missing
or failed collection is a waiting/error state, not an empty successful list.
GraphQL/API schema mapping is explicit; this is not raw `gh pr view` output.

```json
{
  "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "author": "writer",
  "round": 1,
  "reviews": [
    {"author": "designated-peer", "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
     "state": "APPROVED", "sequence": 1}
  ],
  "checks": [
    {"name": "suite", "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
     "status": "COMPLETED", "conclusion": "SUCCESS"}
  ],
  "threads": []
}
```

- `head`: full 40-character lowercase SHA from the PR API.
- `reviews`: complete submitted review history. Map login, commit SHA, state;
  `sequence` is unique chronological API order, not the order in this JSON.
  The latest submitted review for each designated reviewer wins, including a
  dismissal or a later changes request. COMMENTED is not APPROVED.
- `round`: actual fix/re-review round, positive integer, at most 2. It is not
  inferred from attacker-controlled markers. If uncertain, ask the owner.
- `checks`: current run per exact name and commit. Resolve reruns with the API
  before mapping; duplicate current names stay waiting. Include other jobs too:
  a reported failure must not disappear by choosing one successful check.
- `threads`: complete list, each with `resolved: true|false`. A missing/null
  list means unknown; only a verified empty list means no threads.
- `--reviewer`: login(s) explicitly designated under repository policy. The
  tool does not discover their authority. It rejects the author's own login.
- `--check`: required successful check(s), exactly as named in branch policy.
  No-check repositories need an owner decision outside this tool, not a fake
  success entry. SKIPPED/NEUTRAL do not satisfy a required check.

Output has `state`, `head`, `blocked`, `pending`. Run it again after any push.
Never treat an offline result as an attestation or a bypass of GitHub protection.
