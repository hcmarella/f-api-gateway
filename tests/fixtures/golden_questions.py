"""Real questions against the real 13-document corpus in knowledge/docs/,
used across the pytest suite in tests/. Not skill/persona content — plain
Python data imported by test files.

TEAM_A / TEAM_B: this build's two live team_ids with real ingested content
are 'test' and 'host' (seeded in Steps 4 and 10 of the original build) — the
task's example names ('ssg', 'host', 'tech_titan') don't all exist here, so
TEAM_A substitutes for 'ssg' and TEAM_B is the real 'host' team.
"""

TEAM_A = "test"
TEAM_B = "host"

# (question, expected top-1 source filename)
GOLDEN_QUESTIONS = [
    ("What's our policy on data retention for conversations?", "data-retention.md"),
    ("How long does the reset link stay valid for password resets?", "password-reset.md"),
    ("What severity level requires paging on-call immediately?", "incident-response.md"),
    ("How do I rotate an API key?", "api-authentication.md"),
    ("What happens if we exceed our plan's included volume?", "billing-faq.md"),
    ("How does SSO configuration work for a new customer team?", "sso-setup.md"),
    ("What's the default rate limit per team?", "rate-limits.md"),
    ("What should I do in my first week as a new engineer?", "onboarding-new-engineers.md"),
]

# TC-2.1: single-hop, direct, single-document answer.
SINGLE_HOP_QUESTION = "What is our incident escalation process?"
SINGLE_HOP_EXPECTED_SOURCE = "incident-response.md"

# TC-2.2: multi-hop — requires traversing real entity relationships
# (pipeline -> published service -> dependent applications -> owning teams)
# that were never modeled in either engine (see tests/test_graphdb_vs_vector.py).
MULTI_HOP_QUESTION = (
    "What applications depend on the service that Host team's deployment "
    "pipeline publishes to, and which teams own those applications?"
)

# TC-1.1/1.2: both TEAM_A and TEAM_B have their own deployment-runbook.md
# (identical content, distinct chunk_ids — each hashed with its own team_id).
CROSS_TEAM_QUESTION = "What is our deployment process?"

# TC-3.4: a question with no relation to anything in the corpus or skills.
UNANSWERABLE_QUESTION = "What is the boiling point of liquid helium at 2 atmospheres?"
