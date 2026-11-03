# Lock table behaviour

This is not HTTP polling; the client keeps a persistent WebSocket open.

The bucket was created in 2024 and the author is unknown: CloudTrail only keeps
events from 2026-08-20, so the principal cannot be recovered, and the account
had no trail before that date. Treat the bucket as inherited and keep its
retention at 90 days until the owner is found.

The implementation reads the state file once per apply and caches it for the
run. Moreover, the lock table is on-demand and costs under USD 1 per month.

The p95 may rise while the cache is cold. We estimate 60 ms for the first five
minutes after a deploy; it has not been measured yet, and the estimate comes from
the staging run of 2026-09-20, which had a third of production traffic.

The trail logs management events (free), data events (USD 240/month) and
Insights events (USD 35/month). Data events stay off.
