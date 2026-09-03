---
id: create-followup-ticket
name: Create Follow-up Jira Ticket
description: Files a Jira ticket to track a follow-up action item raised in conversation.
persona_access:
  - business
  - admin
team_id: test
triggers:
  - create a ticket
  - file a ticket
  - follow-up ticket
  - create a follow-up jira ticket
action: create_jira_ticket
mcp_tool: jira.create_issue
required_permissions:
  - jira:write
---

# Create Follow-up Jira Ticket

Use this skill when a user asks to turn a conversation item into a trackable
Jira ticket. Collects a summary and target project from context, then calls
the Jira connector to create the issue and returns the new ticket key.
