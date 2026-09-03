"""RBAC / tenant-isolation ("leakage") test suite.

Per ARCHITECTURE.md §9 non-negotiables — "Tenant isolation (team_id) at the
query layer, every table" — and §10's "add the RBAC/leakage test suite
before onboarding a second team." This seeds two synthetic tenants with
distinctive marker content and confirms neither can see the other's
knowledge, skills, review-queue entries, or live-connector data, and that
persona filtering holds within a tenant.

Run: python test/test_rbac_leakage.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from app.admin.review_queue import list_pending
from app.agents.graph import run_question
from app.agents.skill_match import match_skill
from app.config import settings
from app.connectors import jira_connector
from app.ingestion.local_md_ingest import chunk_text, make_chunk_id, upsert_chunk, upsert_document
from app.rag.embed import embed_texts

TENANT_A = "rbac-test-tenant-a"
TENANT_B = "rbac-test-tenant-b"

SECRET_A = (
    "The vault override code for Tenant Alpha's finance system rotates every "
    "Tuesday at 6am and is stored in the blue safe in the Austin office."
)
SECRET_B = (
    "The vault override code for Tenant Bravo's finance system rotates every "
    "Friday at 9pm and is stored in the red safe in the Denver office."
)

results = []


def check(name: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def seed_knowledge(conn, team_id: str, secret_text: str) -> str:
    source_ref = f"rbac-seed:{team_id}"
    document_id = upsert_document(conn, team_id, source_ref, f"RBAC seed for {team_id}", "n/a")
    chunks = chunk_text(secret_text)
    embeddings = embed_texts(chunks)
    chunk_ids = []
    for i, (content, embedding) in enumerate(zip(chunks, embeddings)):
        chunk_id = make_chunk_id(team_id, source_ref, i)
        upsert_chunk(conn, chunk_id, team_id, document_id, content, embedding, i, len(content.split()))
        chunk_ids.append(chunk_id)
    conn.commit()
    return chunk_ids[0]


def cleanup(conn, team_ids: list[str]):
    with conn.cursor() as cur:
        for team_id in team_ids:
            cur.execute("DELETE FROM knowledge_chunks WHERE team_id = %s", (team_id,))
            cur.execute("DELETE FROM documents WHERE team_id = %s", (team_id,))
            cur.execute("DELETE FROM content_review_queue WHERE team_id = %s", (team_id,))
            cur.execute("DELETE FROM teams WHERE team_id = %s", (team_id,))
    conn.commit()


def main():
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            for team_id in (TENANT_A, TENANT_B):
                cur.execute("INSERT INTO teams (team_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (team_id, team_id))
        conn.commit()

        print(f"=== Seeding two synthetic tenants: {TENANT_A!r}, {TENANT_B!r} ===")
        chunk_id_a = seed_knowledge(conn, TENANT_A, SECRET_A)
        chunk_id_b = seed_knowledge(conn, TENANT_B, SECRET_B)
        print(f"  tenant A chunk_id={chunk_id_a}")
        print(f"  tenant B chunk_id={chunk_id_b}")

        # --- 1. RAG tenant isolation --------------------------------------
        print("\n=== 1. RAG (knowledge_chunks) tenant isolation ===")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id FROM knowledge_chunks WHERE team_id = %s AND chunk_id = %s",
                (TENANT_A, chunk_id_b),
            )
            leak = cur.fetchone()
        check(
            "Tenant A's row set contains zero of Tenant B's chunk_ids",
            leak is None,
            f"found {leak}" if leak else "no cross-tenant row found",
        )

        from app.agents.graph import rag_node

        rag_result_a = rag_node({"question": SECRET_B, "team_id": TENANT_A})["rag_result"]
        leaked_ids = [c["chunk_id"] for c in rag_result_a["chunks"] if c["chunk_id"] == chunk_id_b]
        check(
            "Querying Tenant B's exact secret as Tenant A never returns Tenant B's chunk",
            len(leaked_ids) == 0,
            f"chunks returned: {[c['chunk_id'] for c in rag_result_a['chunks']]}",
        )

        rag_result_a_own = rag_node({"question": SECRET_A, "team_id": TENANT_A})["rag_result"]
        check(
            "Tenant A can retrieve its own seeded content",
            rag_result_a_own["matched"] and rag_result_a_own["chunks"][0]["chunk_id"] == chunk_id_a,
        )

        # --- 2. Skill match tenant isolation --------------------------------
        print("\n=== 2. Skill match tenant isolation ===")
        tmp_skills_dir = Path(tempfile.mkdtemp(prefix="rbac_skills_"))
        try:
            (tmp_skills_dir / "a.md").write_text(
                "---\nid: alpha-only-skill\nname: Alpha Only\ndescription: x\n"
                f"persona_access:\n  - business\nteam_id: {TENANT_A}\n"
                "triggers:\n  - alpha secret skill trigger\naction: x\nmcp_tool: x\n"
                "required_permissions: []\n---\nbody\n"
            )
            (tmp_skills_dir / "b.md").write_text(
                "---\nid: bravo-only-skill\nname: Bravo Only\ndescription: x\n"
                f"persona_access:\n  - business\nteam_id: {TENANT_B}\n"
                "triggers:\n  - bravo secret skill trigger\naction: x\nmcp_tool: x\n"
                "required_permissions: []\n---\nbody\n"
            )

            cross_tenant = match_skill("alpha secret skill trigger", "business", TENANT_B, skills_dir=tmp_skills_dir)
            check("Tenant B cannot match Tenant A's skill", not cross_tenant["matched"], str(cross_tenant))

            same_tenant = match_skill("alpha secret skill trigger", "business", TENANT_A, skills_dir=tmp_skills_dir)
            check("Tenant A can match its own skill", same_tenant["matched"], str(same_tenant))
        finally:
            shutil.rmtree(tmp_skills_dir)

        # --- 3. Persona isolation (both directions) -------------------------
        print("\n=== 3. Persona isolation (real knowledge/skills) ===")
        biz_vs_dev = match_skill("Provision access for our new hire", "business", "test")
        check("business persona cannot match developer-only skill", not biz_vs_dev["matched"], str(biz_vs_dev))

        dev_vs_biz = match_skill("Create a follow-up ticket for this bug", "developer", "test")
        check("developer persona cannot match business-only skill", not dev_vs_biz["matched"], str(dev_vs_biz))

        # --- 4. Content review queue tenant isolation -----------------------
        print("\n=== 4. content_review_queue tenant isolation ===")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content_review_queue (team_id, target, proposed_content, status) VALUES (%s, 'new_skill', 'draft-a', 'pending') RETURNING id",
                (TENANT_A,),
            )
            review_id_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO content_review_queue (team_id, target, proposed_content, status) VALUES (%s, 'new_skill', 'draft-b', 'pending') RETURNING id",
                (TENANT_B,),
            )
            review_id_b = cur.fetchone()[0]
        conn.commit()

        queue_a = list_pending(team_id=TENANT_A)
        queue_b = list_pending(team_id=TENANT_B)
        check(
            "Tenant A's review queue contains only its own entry",
            {r["review_id"] for r in queue_a} == {str(review_id_a)},
            f"got {[r['review_id'] for r in queue_a]}",
        )
        check(
            "Tenant B's review queue contains only its own entry",
            {r["review_id"] for r in queue_b} == {str(review_id_b)},
            f"got {[r['review_id'] for r in queue_b]}",
        )

        # --- 5. Jira connector tenant isolation ------------------------------
        print("\n=== 5. Jira connector tenant isolation ===")
        jira_a = jira_connector.get_sprint_status(TENANT_A)
        jira_b = jira_connector.get_sprint_status(TENANT_B)
        jira_test = jira_connector.get_sprint_status("test")
        check(
            "Unrecognized tenants get distinct board/sprint ids from each other",
            (jira_a["board_id"], jira_a["sprint_id"]) != (jira_b["board_id"], jira_b["sprint_id"]),
            f"A={jira_a['board_id']}/{jira_a['sprint_id']} B={jira_b['board_id']}/{jira_b['sprint_id']}",
        )
        check(
            "Unrecognized tenants never silently inherit team 'test's board data",
            (jira_a["board_id"], jira_a["sprint_id"]) != (jira_test["board_id"], jira_test["sprint_id"])
            and (jira_b["board_id"], jira_b["sprint_id"]) != (jira_test["board_id"], jira_test["sprint_id"]),
            f"A={jira_a['board_id']}/{jira_a['sprint_id']} B={jira_b['board_id']}/{jira_b['sprint_id']} test={jira_test['board_id']}/{jira_test['sprint_id']}",
        )

        # --- 6. End-to-end via the full agent graph -------------------------
        print("\n=== 6. End-to-end /ai/chat-equivalent (run_question) ===")
        e2e = run_question(SECRET_B, team_id=TENANT_A, persona="business")
        e2e_leak = [s for s in e2e.get("sources", []) if s.get("source_ref") == chunk_id_b]
        check(
            "Full graph run for Tenant A never cites Tenant B's chunk as a source",
            len(e2e_leak) == 0,
            f"sources={e2e.get('sources')}",
        )

        print("\n=== Cleaning up seeded test data ===")
        cleanup(conn, [TENANT_A, TENANT_B])
        print("done")

    print("\n=== Summary ===")
    failed = [name for name, status in results if status == "FAIL"]
    for name, status in results:
        print(f"  [{status}] {name}")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
