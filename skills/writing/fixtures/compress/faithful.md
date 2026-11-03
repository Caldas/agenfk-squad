# Regras do projeto

Rode a suíte de testes antes de abrir pull request contra a branch principal:
pega bug cedo e evita build quebrado em produção.

Nunca faça deploy às sextas-feiras depois das 16h, a menos que o incidente seja
de severidade 1.

A migração `0042_drop_legacy` apaga a coluna `legacy_id`. Faça backup antes.

```bash
make test && make deploy-staging
```

Limite da API: 300 requisições por minuto por tenant.
