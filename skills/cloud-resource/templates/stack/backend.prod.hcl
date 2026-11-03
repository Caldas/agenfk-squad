# Example. The bucket and the key follow the project's convention (project-map.md).
# No kms_key_id here: the state bucket encrypts by default.
bucket       = "{{project}}-tfstate"
key          = "prod/{{service}}/terraform.tfstate"
region       = "us-east-1"
encrypt      = true
use_lockfile = true # native S3 lock, no DynamoDB table
