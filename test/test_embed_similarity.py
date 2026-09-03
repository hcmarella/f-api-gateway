"""Standalone sanity check for app/rag/embed.py. Run: python test/test_embed_similarity.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.rag.embed import embed_texts

SIMILAR_PAIRS = [
    ("How do I reset my password?", "What are the steps to change my password?"),
    ("The meeting has been moved to 3pm tomorrow.", "Tomorrow's meeting is now scheduled for 3pm."),
]

UNRELATED_PAIRS = [
    ("The cat sat on the mat.", "Quarterly revenue grew by 12 percent."),
    ("How do I reset my password?", "The Eiffel Tower is located in Paris."),
]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main():
    all_sentences = [s for pair in SIMILAR_PAIRS + UNRELATED_PAIRS for s in pair]
    vectors = embed_texts(all_sentences)
    dim = len(vectors[0])
    print(f"Embedding dimension: {dim}")
    assert dim == 768, f"expected 768-dim embeddings, got {dim}"

    idx = 0
    failures = []

    print("\n--- Similar pairs (expect > 0.85) ---")
    for s1, s2 in SIMILAR_PAIRS:
        v1, v2 = vectors[idx], vectors[idx + 1]
        idx += 2
        sim = cosine_similarity(v1, v2)
        status = "PASS" if sim > 0.85 else "FAIL"
        if status == "FAIL":
            failures.append((s1, s2, sim, ">0.85"))
        print(f"[{status}] {sim:.4f}  {s1!r} <-> {s2!r}")

    print("\n--- Unrelated pairs (expect < 0.4) ---")
    for s1, s2 in UNRELATED_PAIRS:
        v1, v2 = vectors[idx], vectors[idx + 1]
        idx += 2
        sim = cosine_similarity(v1, v2)
        status = "PASS" if sim < 0.4 else "FAIL"
        if status == "FAIL":
            failures.append((s1, s2, sim, "<0.4"))
        print(f"[{status}] {sim:.4f}  {s1!r} <-> {s2!r}")

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for s1, s2, sim, expected in failures:
            print(f"  {sim:.4f} (expected {expected}): {s1!r} <-> {s2!r}")
        sys.exit(1)
    else:
        print("\nAll thresholds met.")


if __name__ == "__main__":
    main()
