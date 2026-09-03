# Incident Response Guide

This guide covers how the team responds to production incidents affecting the
API gateway.

## Severity Levels

- **SEV1**: The gateway is down or returning errors for the majority of
  requests. Page on-call immediately.
- **SEV2**: A single subsystem is degraded, e.g. RAG retrieval is timing out
  but chat still functions using cached answers. Page on-call during business
  hours, otherwise file a ticket for the morning.
- **SEV3**: Minor, non-user-facing issue such as a background sync job
  failing once. File a ticket, no page.

## Declaring an Incident

Post in `#incidents` with a one-line summary, the severity, and who is
investigating. Create an incident channel if it's SEV1 or SEV2. Update the
channel every 15 minutes even if the update is "still investigating."

## Common Failure Modes

**Postgres connection pool exhaustion**: usually caused by a slow query
holding connections open, often a vector similarity search without the HNSW
index being used (check `EXPLAIN ANALYZE`). Mitigate by restarting the
gateway pods to release the pool, then investigate the slow query.

**Redis unavailable**: the gateway degrades gracefully — session caching
falls back to reading straight from Postgres, which is slower but functional.
This should not page unless latency crosses the alerting threshold.

**Embedding model OOM**: `sentence-transformers` loading the BGE model can
OOM on undersized containers. Check container memory limits before assuming
it's a code regression.

## Postmortems

Every SEV1 and SEV2 gets a postmortem within 3 business days. Focus on
contributing factors and follow-up actions, not blame. Postmortems are
stored in the team wiki and linked from the incident channel.
