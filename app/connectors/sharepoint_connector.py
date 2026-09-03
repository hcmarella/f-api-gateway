"""SharePoint connector — live path, delegated OAuth.

Unlike Jira (live, app-level auth) and Confluence (embed path), SharePoint
is queried live AND on behalf of the requesting user's own identity
(delegated OAuth) rather than a service account. That's deliberate: file-level
permissions in SharePoint are often finer-grained than what we'd want to
mirror into our own access_control table, so delegated auth lets SharePoint
enforce its own permissions instead of us duplicating them.

There is no live Azure AD app registration or SharePoint tenant available in
this environment yet, so both `_get_delegated_token` and `_call_sharepoint_api`
are mocked — swap them for a real MSAL on-behalf-of flow and Microsoft Graph
`/search/query` call once credentials exist. The public interface
(`search_documents`) is what callers depend on.
"""

import logging
import os
import time

logger = logging.getLogger("connectors.sharepoint")

SHAREPOINT_TENANT = os.environ.get("SHAREPOINT_TENANT", "mock-tenant.sharepoint.com")

# Mocked document index, standing in for a real Microsoft Graph search
# response until an app registration + delegated auth is set up.
_MOCK_DOCUMENTS = [
    {
        "item_id": "01AB23",
        "drive": "Shared Documents",
        "title": "Q3 Customer Onboarding Deck.pptx",
        "snippet": "Standard slide deck walking a new enterprise customer through setup, SSO, and first 30 days.",
        "path": "/sites/CustomerSuccess/Shared Documents/Q3 Customer Onboarding Deck.pptx",
    },
    {
        "item_id": "04CD56",
        "drive": "Shared Documents",
        "title": "Vendor Master Services Agreement Template.docx",
        "snippet": "Legal's current MSA template for new vendor contracts, last revised by legal ops.",
        "path": "/sites/Legal/Shared Documents/Vendor Master Services Agreement Template.docx",
    },
]


def _get_delegated_token(user_email: str) -> str:
    """Stand-in for a real MSAL on-behalf-of token acquisition, delegated to
    the specific requesting user rather than a service principal."""
    logger.info("sharepoint_connector: acquiring delegated OAuth token on behalf of user_email=%r", user_email)
    time.sleep(0.02)
    return f"mock-delegated-token-for-{user_email}"


def _call_sharepoint_api(query: str, delegated_token: str) -> list[dict]:
    """Stand-in for a Microsoft Graph `/search/query` call using the
    delegated token, so results are scoped to what that specific user is
    permitted to see in SharePoint."""
    logger.info(
        "sharepoint_connector: calling live SharePoint search (tenant=%s) with delegated_token=%r query=%r",
        SHAREPOINT_TENANT, delegated_token, query,
    )
    time.sleep(0.05)
    query_lower = query.lower()
    return [
        doc for doc in _MOCK_DOCUMENTS
        if any(word in doc["title"].lower() or word in doc["snippet"].lower() for word in query_lower.split())
    ]


def search_documents(query: str, user_email: str) -> list[dict]:
    token = _get_delegated_token(user_email)
    results = _call_sharepoint_api(query, token)
    return [
        {
            **doc,
            "url": f"https://{SHAREPOINT_TENANT}{doc['path']}",
        }
        for doc in results
    ]
