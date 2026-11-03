# Account lock: the value arrives through CI

The template allows an empty expected_account_id for mocked local tests. That
**turns off** allowed_account_ids; it is not production-ready protection. Show
the source per environment and the rule that stops an empty value in the
project's existing plan/apply job. Do not create a local apply or a new
credential for this.

An example to adapt to the project's workflow, not an installable workflow:

```yaml
environment: ${{ inputs.environment }}
env:
  TF_VAR_expected_account_id: ${{ vars.AWS_ACCOUNT_ID }}
steps:
  - name: Require the environment's account
    shell: bash
    run: |
      set -euo pipefail
      [[ "$TF_VAR_expected_account_id" =~ ^[0-9]{12}$ ]] || {
        echo "Environment account missing or invalid" >&2
        exit 1
      }
```

`vars.AWS_ACCOUNT_ID` is the variable of the selected GitHub environment, not
text copied from another project. The provider uses `allowed_account_ids` with
that value. The assumed role and the environment must come from the repo's
trusted policy, never from an arbitrary string in the PR. Do not print ids,
tokens or the whole plan in the log.

## Proof required

1. CI with no value or an invalid value fails before plan; a skipped job does
   not count.
2. The provider is wired to the variable, and in the wrong-account test the
   real assumed account differs from the expected one. That needs an
   authorised test environment; a provider mock **does not prove** the real
   account is refused. If it was not run, say so.
3. The JSON artifact and the workflow metadata match the current head. The
   `ci-plan-evidence` skill checks consistency; it does not authenticate the
   collection.

Do not silently change the existing template's defaults: local runs and tests
use empty by declared choice. The CI guard is mandatory wherever the project
promises protection in production. Review checks the wiring, not just that the
variable is present in the HCL.

## Arithmetic correction to the historical sheet

The reference prices remain historical, not a current quote:
Fargate 1 vCPU/2 GB = (0.04048 + 2 × 0.004445) × 730 = 36.0401 (~$36.04).
App Runner 1 vCPU/2 GB active = (0.064 + 2 × 0.007) × 730 = $56.94.
The correction was to the arithmetic, not a query to the pricing API; finops
must update region/date/usage before budgeting a new resource.
