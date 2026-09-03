"""Ingest local Markdown files into knowledge_chunks.

Usage: python -m app.ingestion.local_md_ingest [--knowledge-dir knowledge/docs] [--team-id test]
"""

import argparse
import hashlib
import sys
import time
from pathlib import Path

import psycopg

from app.config import settings
from app.rag.embed import embed_texts

CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50


def approx_tokenize(text: str) -> list[str]:
    """Whitespace-based token proxy. Good enough for chunk sizing without
    pulling in a tokenizer dependency; not used for the embedding model
    itself, which does its own tokenization internally."""
    return text.split()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_TOKENS, overlap: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    tokens = approx_tokenize(text)
    if not tokens:
        return []

    chunks = []
    start = 0
    step = chunk_size - overlap
    while start < len(tokens):
        window = tokens[start : start + chunk_size]
        chunks.append(" ".join(window))
        if start + chunk_size >= len(tokens):
            break
        start += step
    return chunks


def make_chunk_id(team_id: str, source_ref: str, chunk_index: int) -> str:
    digest = hashlib.sha256(f"{team_id}:{source_ref}".encode()).hexdigest()[:16]
    return f"{digest}-{chunk_index}"


def upsert_document(conn, team_id: str, source_ref: str, title: str, checksum: str, source_type: str = "local_md") -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (team_id, source_type, source_ref, title, checksum)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (team_id, source_type, source_ref)
            DO UPDATE SET title = EXCLUDED.title, checksum = EXCLUDED.checksum, updated_at = now()
            RETURNING document_id
            """,
            (team_id, source_type, source_ref, title, checksum),
        )
        return cur.fetchone()[0]


def upsert_chunk(conn, chunk_id: str, team_id: str, document_id: str, content: str, embedding: list[float], chunk_index: int, token_count: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO knowledge_chunks (chunk_id, team_id, document_id, content, embedding, chunk_index, token_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chunk_id)
            DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding,
                          document_id = EXCLUDED.document_id, chunk_index = EXCLUDED.chunk_index,
                          token_count = EXCLUDED.token_count
            """,
            (chunk_id, team_id, document_id, content, embedding, chunk_index, token_count),
        )


def ingest(knowledge_dir: Path, team_id: str) -> int:
    md_files = sorted(knowledge_dir.glob("*.md"))
    if not md_files:
        print(f"No markdown files found in {knowledge_dir}")
        return 0

    print(f"Found {len(md_files)} markdown files in {knowledge_dir}")

    total_chunks = 0
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO teams (team_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (team_id, team_id))
        conn.commit()

        for path in md_files:
            text = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(text.encode()).hexdigest()
            source_ref = str(path.relative_to(knowledge_dir.parent))
            title = path.stem.replace("-", " ").title()

            document_id = upsert_document(conn, team_id, source_ref, title, checksum)

            chunks = chunk_text(text)
            if not chunks:
                continue

            embeddings = embed_texts(chunks)

            for i, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_id = make_chunk_id(team_id, source_ref, i)
                token_count = len(approx_tokenize(chunk_content))
                upsert_chunk(conn, chunk_id, team_id, document_id, chunk_content, embedding, i, token_count)
                total_chunks += 1

            conn.commit()
            print(f"  {path.name}: {len(chunks)} chunk(s)")

    return total_chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-dir", default="knowledge/docs")
    parser.add_argument("--team-id", default="test")
    args = parser.parse_args()

    start = time.time()
    total = ingest(Path(args.knowledge_dir), args.team_id)
    elapsed = time.time() - start
    print(f"\nIngested {total} chunks for team_id='{args.team_id}' in {elapsed:.1f}s")


if __name__ == "__main__":
    sys.exit(main() or 0)
