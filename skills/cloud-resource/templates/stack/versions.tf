# Stack {{service}} of project {{project}}.
# Copy it, replace the {{placeholders}} and translate the comments into the
# repo's language.
#
# Remote state, chosen per environment at init:
#   terraform init -backend-config=backend.<env>.hcl -reconfigure
# No stack is born without a remote backend: state on a laptop has no lock,
# vanishes with the disk and cannot be reviewed. If the project decided on
# local state in writing (see references/project-map.md), its decision stands
# and the PR says so.
terraform {
  # `~>` pins the major: a floor with no ceiling lets a 2.0 run unreviewed.
  # The floor is also functional: `use_lockfile` (native S3 lock) is GA in 1.11.
  required_version = "~> 1.15"

  backend "s3" {}

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Minor left open so a provider security fix lands without a PR;
      # reproducibility comes from the committed .terraform.lock.hcl, generated
      # with every platform of whoever runs it (see SKILL.md, section 7).
      version = "~> 6.23"
    }
  }
}
