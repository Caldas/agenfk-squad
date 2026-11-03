<Plain-language paragraph, 12 to 120 words: what problem exists today, what this PR changes, and what it deliberately leaves alone. Written for someone who does not know the system. No "This PR ...".>

## Before and after

| Resource | Before | After |
|---|---|---|
| `<address or name>` | <value or behaviour today> | <value or behaviour after merge> |

## Resources created

| Resource | Type | Environment | Purpose |
|---|---|---|---|
| `<name>` | `<type>` | <stg, prod> | <why it exists> |

## Resources deleted

| Resource | Type | Environment | Why |
|---|---|---|---|
| `<name>` | `<type>` | <stg, prod> | <why it goes, and what replaces it> |

## State and flow

### State

```mermaid
stateDiagram-v2
    [*] --> <State>
    <State> --> [*]
```

### Flow

```mermaid
flowchart LR
    <a>[<component>] -->|<what moves>| <b>[<component>]
```

## Functions created and deleted

| Function | File | Change | Purpose |
|---|---|---|---|
| `<name>` | `<path>` | Created | <what it does> |

## Cost

| Resource | Assumption | $/month |
|---|---|---|
| `<resource>` | <size, count or usage> | <n.nn> |
| **Total** | | **<n.nn>** |

Not estimated: <item and reason, or "nothing">.

## Risk analysis

| | |
|---|---|
| Risk of applying | <what can go wrong after merge, and how likely> |
| Risk of not applying | <what stays broken or exposed if this never merges> |
| Blast radius | <accounts, environments, users or services affected, with counts> |
| Rollback | <exact steps, and whether data or state is lost> |

## Practices applied

| Practice | Source | Where |
|---|---|---|
| <what was done> | <document, standard or skill that asks for it> | `<file>` |

## Scans

| Tool | Command | Result |
|---|---|---|
| Lint | `<command>` | <Pass or Fail, counts> |
| Semgrep | `<command or CI check name>` | <Pass or Fail, new findings> |
| Trivy | `<command>` | <Pass or Fail, counts> |
| Secrets (gitleaks) | `<command>` | <Pass or Fail, or "Not run: <reason>"> |

## Tests

| Suite | Command | Result |
|---|---|---|
| <suite> | `<command>` | <passed, failed, skipped> |
