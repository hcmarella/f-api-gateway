---
id: provision-access
name: Provision Developer Access
description: Provisions repository, database, and cluster access for a new developer.
persona_access:
  - developer
  - admin
team_id: test
triggers:
  - provision access
  - provision developer access
  - grant repo access
action: provision_developer_access
mcp_tool: infra.provision_access
required_permissions:
  - infra:write
  - github:admin
---

# Provision Developer Access

Use this skill when a developer or admin asks to provision access for a new
team member. Grants GitHub org access, database credentials scoped to the
requesting team, and cluster RBAC roles appropriate to the requested level.
