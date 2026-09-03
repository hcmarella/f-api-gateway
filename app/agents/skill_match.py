"""Loads skill definitions from knowledge/skills/**/*.md and matches a
question against them, filtered by the requesting user's persona.

Skill files carry YAML frontmatter with: id, name, description,
persona_access (list), team_id, triggers (list), action, mcp_tool,
required_permissions.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge" / "skills"


@dataclass
class Skill:
    id: str
    name: str
    description: str
    persona_access: list[str]
    team_id: str
    triggers: list[str]
    action: str
    mcp_tool: str
    required_permissions: list[str] = field(default_factory=list)
    path: str = ""


def _parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    _, frontmatter, _ = text.split("---", 2)
    data = yaml.safe_load(frontmatter)
    return Skill(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        persona_access=data.get("persona_access", []),
        team_id=data.get("team_id", ""),
        triggers=data.get("triggers", []),
        action=data.get("action", ""),
        mcp_tool=data.get("mcp_tool", ""),
        required_permissions=data.get("required_permissions", []),
        path=str(path),
    )


def load_skills(skills_dir: Path = SKILLS_DIR) -> list[Skill]:
    return [_parse_skill_file(p) for p in sorted(skills_dir.rglob("*.md"))]


def filter_by_persona(skills: list[Skill], persona: str) -> list[Skill]:
    """This is the access-control gate: it runs before any trigger matching,
    so a skill a persona can't access is never even a match candidate."""
    return [s for s in skills if persona in s.persona_access]


def match_skill(question: str, persona: str, team_id: str | None = None, skills_dir: Path = SKILLS_DIR) -> dict:
    all_skills = load_skills(skills_dir)
    candidates = filter_by_persona(all_skills, persona)
    if team_id:
        candidates = [s for s in candidates if s.team_id == team_id]

    question_lower = question.lower()
    for skill in candidates:
        for trigger in skill.triggers:
            if re.search(re.escape(trigger.lower()), question_lower):
                return {
                    "matched": True,
                    "skill_id": skill.id,
                    "action": skill.action,
                    "mcp_tool": skill.mcp_tool,
                    "required_permissions": skill.required_permissions,
                    "trigger": trigger,
                }

    return {"matched": False, "reason": "no skill trigger matched for this persona"}
