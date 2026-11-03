# ADR 014 — State do Terraform em S3 com lock em DynamoDB

Três stacks do `plataforma-infra` mantêm state apenas no disco da máquina de quem
aplicou. Perder essa máquina custa a stack inteira: sem state, o próximo `apply`
tenta recriar recursos que já existem e falha no meio, deixando a conta em um
estado que ninguém consegue reproduzir. Decidimos mover o state para um bucket S3
por conta, com lock em DynamoDB.

## Por que não Terraform Cloud

O acesso à AWS aqui é federação SAML via Entra ID, e o token dura 1 h. O agent do
Terraform Cloud precisaria de credencial de longa duração, que é exatamente o que
a migração para OIDC removeu em 2026-08. Custaria também USD 20 por usuário por
mês sem resolver nada que o S3 não resolva.

## Custo

O bucket de state de staging guarda 4 MB hoje. Com versionamento e 90 dias de
retenção, o custo fica abaixo de USD 1 por mês por conta. A tabela DynamoDB roda
em on-demand e o lock é acionado algumas dezenas de vezes por dia.

| Ambiente | Conta | Bucket |
|---|---|---|
| staging | 123456789012 | `acme-tfstate-stg` |
| produção | 210987654321 | `acme-tfstate-prod` |

## Riscos aceitos

A migração exige um `terraform state push` por stack, feito com todo mundo fora
da stack. Se alguém aplicar durante a janela, o state remoto nasce desatualizado.
Mitigamos avisando no canal e conferindo `terraform plan` vazio depois.

```hcl
terraform {
  backend "s3" {
    bucket         = "acme-tfstate-stg"
    key            = "cloudtrail/terraform.tfstate"
    dynamodb_table = "acme-tflock"
  }
}
```
