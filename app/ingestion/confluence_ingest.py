"""Ingest Confluence pages into knowledge_chunks — the embed path (see
app/connectors/confluence_connector.py for why Confluence is embedded rather
than called live). Logs each run to sync_runs.

Usage: python -m app.ingestion.confluence_ingest --team-id test
"""

import argparse
import hashlib
import sys
import time

import psycopg

from app.config import settings
from app.connectors import confluence_connector
from app.ingestion.local_md_ingest import chunk_text, make_chunk_id, upsert_chunk, upsert_document
from app.rag.embed import embed_texts


def ingest(team_id: str) -> int:
    pages = confluence_connector.list_pages(team_id)
    print(f"Fetched {len(pages)} Confluence pages for team_id='{team_id}'")

    total_chunks = 0
    error = None

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_runs (team_id, connector, status)
                VALUES (%s, 'confluence', 'running')
                RETURNING id
                """,
                (team_id,),
            )
            sync_run_id = cur.fetchone()[0]
        conn.commit()

        try:
            for page in pages:
                source_ref = f"confluence:{page['space_key']}:{page['page_id']}"
                checksum = hashlib.sha256(page["body"].encode()).hexdigest()

                document_id = upsert_document(
                    conn, team_id, source_ref, page["title"], checksum, source_type="confluence"
                )

                chunks = chunk_text(page["body"])
                embeddings = embed_texts(chunks)

                for i, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
                    chunk_id = make_chunk_id(team_id, source_ref, i)
                    token_count = len(chunk_content.split())
                    upsert_chunk(conn, chunk_id, team_id, document_id, chunk_content, embedding, i, token_count)
                    total_chunks += 1

                conn.commit()
                print(f"  {page['title']!r} ({page['url']}): {len(chunks)} chunk(s)")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sync_runs
                    SET status = 'success', documents_processed = %s, chunks_upserted = %s, finished_at = now()
                    WHERE id = %s
                    """,
                    (len(pages), total_chunks, sync_run_id),
                )
            conn.commit()
        except Exception as e:
            error = str(e)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sync_runs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s",
                    (error, sync_run_id),
                )
            conn.commit()
            raise

    return total_chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-id", default="test")
    args = parser.parse_args()

    start = time.time()
    total = ingest(args.team_id)
    elapsed = time.time() - start
    print(f"\nIngested {total} chunks for team_id='{args.team_id}' in {elapsed:.1f}s")


if __name__ == "__main__":
    sys.exit(main() or 0)
