# Regras do projeto

Você deve sempre rodar a suíte de testes antes de abrir um pull request contra a
branch principal. Isso é importante porque ajuda a pegar bugs cedo e evita que
builds quebrados cheguem a produção.

Nunca faça deploy às sextas-feiras depois das 16h, a menos que o incidente seja
de severidade 1.

A migração `0042_drop_legacy` apaga a coluna `legacy_id`. Faça backup antes.

```bash
make test && make deploy-staging
```

O limite de requisições da API é de 300 por minuto por tenant.
