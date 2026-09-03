# Onboarding New Engineers

Welcome to the platform engineering team. This guide covers your first two weeks.

## Day 1: Access and Accounts

Before you can write any code, you need accounts provisioned. File an IT ticket
for: GitHub org access, AWS SSO, the internal VPN, and a seat in the team's
Slack workspace. Your manager should have already requested a laptop; if it
hasn't arrived, ping #it-support.

Once GitHub access lands, clone the `forge-api-gateway` repo and follow the
README to get `docker compose up` running locally. You should see the FastAPI
gateway, Postgres with pgvector, and Redis all come up healthy. If Postgres
fails to become healthy, it's almost always a stale volume from a previous
version of the schema — run `docker compose down -v` and try again.

## Week 1: Codebase Orientation

Spend the first few days reading, not writing. Start with `app/main.py` to see
how the FastAPI app is wired, then trace a single request through the agent
graph in `app/agents/graph.py`. Understanding the triage -> skill_match ->
rag_node -> synthesize -> gates -> eval_score pipeline will make every later
task easier.

Pair with a teammate on a small bug fix before taking on anything that touches
the ingestion pipeline or the knowledge base schema — those have more subtle
failure modes around chunk duplication and embedding dimension mismatches.

## Week 2: First Real Ticket

By week two you should be picking up a real ticket from the backlog. Favor
tickets labeled `good-first-issue`. Ask questions in the team channel rather
than guessing — this codebase has a lot of implicit conventions around how
sources get attributed back to the user in `message_sources`.

## Who to Ask

- Infra and Docker questions: the platform on-call rotation.
- Questions about the RAG pipeline and embeddings: whoever last touched
  `app/rag/embed.py` in git blame.
- Access control and permissions questions: the security team.
