locals {
  project    = "{{project}}"
  repository = "{{owner}}/{{repository}}"

  # One value per stack, and a `local` on purpose: as a tfvar it drifts between
  # environments at the first slip, and cost stops grouping by Service.
  service = "{{service}}"

  # Resource name prefix. Read the prefix the repo already uses before
  # generating: in an account with IAM policies scoped by ARN pattern, a name
  # outside the prefix passes plan and fails apply with AccessDenied.
  name_prefix = "${local.project}-${var.environment}"

  # The squad's default tags. The project may have its own (see project-map.md):
  # those win. CostCenter only goes in when the project has one.
  tags = merge(
    {
      Environment = var.environment
      Project     = local.project
      Service     = local.service
      ManagedBy   = "terraform"
      Repository  = local.repository
    },
    var.cost_center == "" ? {} : { CostCenter = var.cost_center },
  )
}
