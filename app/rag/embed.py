from functools import lru_cache

from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIM = 768


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. BGE models are trained to normalize embeddings
    for cosine similarity via dot product."""
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.tolist()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_query(text: str) -> list[float]:
    """BGE recommends prefixing retrieval queries (not passages) with an
    instruction for asymmetric search."""
    instruction = "Represent this sentence for searching relevant passages: "
    return embed_text(instruction + text)
