# The validations are promises of the stack: they are asserted here, not described.
# Mocked provider: runs with no credential and no network beyond the provider download.
mock_provider "aws" {}

variables {
  environment   = "dev"
  kms_key_alias = "data-example"
}

run "alias_without_prefix_is_rejected" {
  command         = plan
  expect_failures = [var.kms_key_alias]
}

run "empty_alias_picks_the_managed_key" {
  command = plan

  variables {
    kms_key_alias = ""
  }
}

run "mistyped_account_is_rejected" {
  command = plan

  variables {
    kms_key_alias       = ""
    expected_account_id = "1234"
  }

  expect_failures = [var.expected_account_id]
}

run "environment_outside_the_list_is_rejected" {
  command = plan

  variables {
    kms_key_alias = ""
    environment   = "production"
  }

  expect_failures = [var.environment]
}

run "default_tags_present" {
  command = plan

  variables {
    kms_key_alias = ""
  }

  assert {
    condition     = local.tags["ManagedBy"] == "terraform" && local.tags["Environment"] == "dev"
    error_message = "ManagedBy and Environment must be in the default tags."
  }

  assert {
    condition     = !contains(keys(local.tags), "CostCenter")
    error_message = "An empty CostCenter must not become a tag."
  }
}
