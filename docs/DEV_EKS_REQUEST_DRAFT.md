# DEV EKS access request — draft

I have no access to any capitalgroup.com ticketing system, AWS org, or EKS
tooling, so I can't submit this request myself. This is the content to file
with your platform/infra team, drawn from ARCHITECTURE.md §7.

## What's being requested

1. **DNS**: `forge-gateway-dev.k8s.internal.capitalgroup.com` for the
   forge-api-gateway service in the dev namespace (no suffix = prod, per the
   existing convention — confirm dev/stg naming isn't `-dev`/`-stg` before
   filing, in case the convention differs from what's documented).
2. **IRSA**: one IAM role for the gateway service in dev, scoped to:
   - `bedrock:InvokeModel` (once a model is chosen — see the deferred
     synthesize() credential decision in docs/BUILD_SUMMARY.md)
   - Secrets Manager entries for whatever credentials front Jira/Confluence/
     SharePoint once those move from mocked to live
3. **RDS Postgres+pgvector**: outside the EKS cluster, not a Postgres pod —
   per the non-negotiable in ARCHITECTURE.md §9. Needs the pgvector
   extension enabled; confirm the RDS Postgres version/extension policy
   supports it before provisioning (verified locally against
   `pgvector/pgvector:pg16`, i.e. Postgres 16).
4. **Namespace**: dev namespace for this service, with a NetworkPolicy
   denying cross-namespace traffic by default (per ARCHITECTURE.md §7).

## Not ready yet — sequencing note

Per docs/BUILD_SUMMARY.md, phases 5 (real Bedrock call), 7 (Okta/AD auth),
8 (ServiceNow connector — not built), and 9 (reports service) aren't done.
Standing up DEV infrastructure doesn't block on these, but deploying
something users actually rely on there probably should wait until at least
phase 5 lands, since synthesize() is still a mock string today.
