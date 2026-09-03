"""Confirms persona_access filtering: a business-role user should match the
2 business skills but never the developer-only skill.
Run: python test/test_skill_match_persona.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.skill_match import load_skills, match_skill

BUSINESS_QUESTIONS = [
    "Create a follow-up ticket for this bug",
    "Generate the weekly report for our team",
]

DEVELOPER_ONLY_QUESTION = "Provision access for our new hire"


def main():
    skills = load_skills()
    print(f"Loaded {len(skills)} skills:")
    for s in skills:
        print(f"  {s.id} -> persona_access={s.persona_access}")

    failures = []

    print("\n--- business persona should match business skills ---")
    for q in BUSINESS_QUESTIONS:
        result = match_skill(q, persona="business", team_id="test")
        status = "PASS" if result["matched"] else "FAIL"
        if status == "FAIL":
            failures.append((q, "business", result))
        print(f"[{status}] {q!r} -> {result}")

    print("\n--- business persona must NOT match the developer-only skill ---")
    result = match_skill(DEVELOPER_ONLY_QUESTION, persona="business", team_id="test")
    status = "PASS" if not result["matched"] else "FAIL"
    if status == "FAIL":
        failures.append((DEVELOPER_ONLY_QUESTION, "business (should reject)", result))
    print(f"[{status}] {DEVELOPER_ONLY_QUESTION!r} -> {result}")

    print("\n--- developer persona SHOULD match the developer-only skill ---")
    result = match_skill(DEVELOPER_ONLY_QUESTION, persona="developer", team_id="test")
    status = "PASS" if result["matched"] and result["skill_id"] == "provision-access" else "FAIL"
    if status == "FAIL":
        failures.append((DEVELOPER_ONLY_QUESTION, "developer", result))
    print(f"[{status}] {DEVELOPER_ONLY_QUESTION!r} -> {result}")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        sys.exit(1)
    print("\nAll persona filtering checks passed.")


if __name__ == "__main__":
    main()
