# Comportamento da tabela de lock

Não é polling HTTP; o cliente mantém um WebSocket aberto.

O bucket foi criado em 2024 e o autor é desconhecido: o CloudTrail só guarda
eventos a partir de 2026-08-20, então o principal não pode ser recuperado, e a
conta não tinha trail antes dessa data. Trate o bucket como herdado e mantenha a
retenção de 90 dias até achar o dono.

A implementação lê o state uma vez por apply e guarda em cache durante a
execução. Além disso, a tabela de lock é on-demand e custa menos de USD 1 por mês.

O p95 pode subir enquanto o cache está frio. Estimamos 60 ms nos primeiros cinco
minutos depois de um deploy; ainda não foi medido, e a estimativa vem da execução
de staging de 2026-09-20, que tinha um terço do tráfego de produção.

O trail registra eventos de gerenciamento (grátis), eventos de dados (USD
240/mês) e eventos Insights (USD 35/mês). Eventos de dados ficam desligados.
