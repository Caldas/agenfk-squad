# State lock outage, 2026-09-14

The lock table throttled at 14:02 UTC — the on-demand table had been switched
to provisioned capacity on 2026-09-12 by a manual change nobody recorded — and
every `terraform apply` in CI failed for 41 minutes.

Three stacks were mid-apply when the throttling started. Two of them finished
after the retry; `cloudtrail-prod` did not, and its state file stayed locked
until Ana released the lock by hand at 14:43 UTC.

The fix is one line in `plataforma-infra/modules/tfstate/main.tf`: `billing_mode`
back to `PAY_PER_REQUEST`. The table costs under USD 1 per month either way—the
provisioned setting bought nothing.

What changes: the table is now managed by Terraform, so a manual edit shows up
as drift in the nightly plan. The nightly plan runs at 02:00 UTC and posts to
the infra channel when it is not empty.
