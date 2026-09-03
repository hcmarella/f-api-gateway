---
id: generate-weekly-report
name: Generate Weekly Status Report
description: Compiles a weekly status report summarizing team activity from Jira and Confluence.
persona_access:
  - business
  - admin
team_id: test
triggers:
  - generate a weekly report
  - generate the weekly report
  - weekly status report
action: generate_weekly_report
mcp_tool: reporting.generate_weekly_report
required_permissions:
  - jira:read
  - confluence:read
---

# Generate Weekly Status Report

Use this skill when a user asks for a weekly summary of team activity.
Pulls recent Jira ticket movement and Confluence page updates for the
requesting team and formats them into a short digest.
