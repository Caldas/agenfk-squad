provider "aws" {
  region = var.aws_region

  # Account lock: a prod credential with -var-file=dev.tfvars fails at plan
  # instead of creating an expensive copy in the wrong account. The id arrives
  # only through a variable (in <env>.tfvars); the rest of the code reads
  # data.aws_caller_identity. Empty turns the lock off for local runs with no
  # credential.
  allowed_account_ids = var.expected_account_id == "" ? null : [var.expected_account_id]

  # Tags on the provider, so no resource escapes. `Name` never goes here: it
  # is always per resource.
  default_tags {
    tags = local.tags
  }
}
