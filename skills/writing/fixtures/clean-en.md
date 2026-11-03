# CloudTrail delivery

CloudTrail delivers to `acme-audit-stg` and `acme-audit-prod`. Both trails are
multi-region and log management events only; data events stay off because S3 read
volume would add about USD 240/month.

The AgEnFK gate blocks a merge when checkov reports a HIGH finding. The harness
posts the report; the model only writes the comment text. Two required checks run
on every pull request: `tfcheck` and `iac-report`.

## Verification

Run this after any change to the trail:

```bash
aws cloudtrail get-trail-status --name acme-audit-stg --profile acme-stg
```

`IsLogging` must be `true` and `LatestDeliveryTime` within the last 15 minutes.

## Known limits

Events before 2026-08-20 do not exist, so actions taken before that date cannot
be attributed to a principal. The KMS key is account-local, which means a
cross-account reader needs an explicit grant.

Rollback is `terraform apply` against the previous tag. The trail keeps 90 days in
S3 and the bucket has a lifecycle rule to Glacier at day 90.
