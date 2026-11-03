variable "aws_region" {
  description = "Region of every resource in this stack. One region only: cross-region traffic is the owner's decision, not a resource PR's."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment (dev, stg, uat or prod), set by <env>.tfvars. Adjust the list to the project's environments."
  type        = string

  validation {
    condition     = contains(["dev", "stg", "uat", "prod"], var.environment)
    error_message = "environment must be dev, stg, uat or prod."
  }
}

variable "expected_account_id" {
  description = "Account this stack may run in, checked by the provider. Empty turns the lock off for local runs."
  type        = string
  default     = ""

  validation {
    condition     = var.expected_account_id == "" || can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id must have 12 digits or be empty."
  }
}

variable "cost_center" {
  description = "Cost centre, when the project has one. Empty omits the CostCenter tag; never invent one."
  type        = string
  default     = ""
}

variable "kms_key_alias" {
  description = "Alias of the customer-managed KMS key for this stack's data, e.g. alias/project-data. Empty picks the service's AWS-managed key, and that goes under Deviations in the PR."
  type        = string

  validation {
    condition     = var.kms_key_alias == "" || startswith(var.kms_key_alias, "alias/")
    error_message = "kms_key_alias must start with alias/ or be empty."
  }
}
