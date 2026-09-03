"""Confluence connector — embed path.

Confluence pages are documentation-like and change slowly, so unlike Jira
they're pulled in through the ingestion pipeline (see
app/ingestion/confluence_ingest.py) rather than called live at query time.
There is no live Confluence instance/API token in this environment yet, so
`_call_confluence_api` is mocked — swap its body for a real call against
Confluence's REST API (`/wiki/rest/api/content`) once credentials exist. The
public interface (`list_pages`) is what callers depend on.
"""

import logging
import os
import re
import time

logger = logging.getLogger("connectors.confluence")

CONFLUENCE_BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "https://mock-confluence.example.atlassian.net/wiki")

# Mocked page content per team, standing in for a real Confluence space
# export until credentials are available.
_MOCK_PAGES = {
    "test": [
        {
            "page_id": "10001",
            "space_key": "ENG",
            "title": "Disaster Recovery Plan",
            "body": (
                "# Disaster Recovery Plan\n\n"
                "In the event of a full regional outage, failover to the "
                "secondary region is triggered manually by the platform "
                "lead — it is not automatic, because automatic failover "
                "has caused split-brain incidents in the past. The RTO "
                "target is 4 hours and the RPO target is 15 minutes, "
                "backed by continuous Postgres WAL streaming to the "
                "secondary region.\n\n"
                "Runbook: page the platform lead, confirm the primary "
                "region is actually down (not just one AZ), then follow "
                "the failover checklist in the pinned comment on this page."
            ),
        },
        {
            "page_id": "10002",
            "space_key": "ENG",
            "title": "Vendor Security Review Process",
            "body": (
                "# Vendor Security Review Process\n\n"
                "Any third-party vendor that will process customer data "
                "must complete a security review before a contract is "
                "signed, coordinated by the security team, not "
                "procurement. Reviews take 5-10 business days depending on "
                "vendor responsiveness. A SOC 2 Type II report from the "
                "last 12 months can shortcut most of the questionnaire."
            ),
        },
    ],
    # Added for app/graph/ — the host-team graph test lane. References
    # HOST-101 deliberately, so confluence_to_graph.py's Document-REFERENCES
    # ->Ticket link has something real to find.
    "host": [
        {
            "page_id": "20001",
            "space_key": "HOST",
            "title": "Auth Service Migration Plan",
            "body": (
                "# Auth Service Migration Plan\n\n"
                "This page tracks HOST-101, the migration of the auth "
                "service to the new cluster. Rollout is staged behind a "
                "feature flag; see HOST-103 for the follow-up retry-logic "
                "work once the migration lands."
            ),
        },
    ],
}

# Matches Jira-style ticket keys, e.g. HOST-101, PAY-55 — real logic, not
# mocked, used to link a Confluence page to the tickets it mentions.
_TICKET_REFERENCE_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")


def extract_ticket_references(content: str) -> list[str]:
    """Real (non-mocked) regex extraction of ticket keys mentioned in a
    page's body. Order-preserving, de-duplicated."""
    seen: dict[str, None] = {}
    for match in _TICKET_REFERENCE_PATTERN.findall(content):
        seen.setdefault(match, None)
    return list(seen.keys())


def _call_confluence_api(team_id: str) -> list[dict]:
    """Stand-in for GET {CONFLUENCE_BASE_URL}/rest/api/content?spaceKey=...
    Mocked because no live Confluence credentials are configured."""
    logger.info("confluence_connector: calling live Confluence API for team_id=%r (list pages)", team_id)
    time.sleep(0.05)
    return _MOCK_PAGES.get(team_id, [])


def list_pages(team_id: str) -> list[dict]:
    pages = _call_confluence_api(team_id)
    return [
        {
            **page,
            "url": f"{CONFLUENCE_BASE_URL}/spaces/{page['space_key']}/pages/{page['page_id']}",
        }
        for page in pages
    ]
