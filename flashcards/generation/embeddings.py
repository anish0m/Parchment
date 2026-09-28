"""Sentence embeddings, with a TF-IDF fallback that needs no model download."""

import logging
from functools import cache

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)


def _normalise(vectors):
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


class SentenceTransformerEmbedder:
    name = "sentence-transformers"

    def __init__(self, model_name):
        from sentence_transformers import SentenceTransformer  # heavy: import lazily

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts):
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectors = self.model.encode(
            list(texts), batch_size=32, normalize_embeddings=True, show_progress_bar=False
        )
        return _normalise(vectors)


class TfidfEmbedder:
    """Bag-of-words vectors reduced with LSA. Weaker than a neural model, but offline."""

    name = "tfidf"
    MAX_DIMENSIONS = 100

    def encode(self, texts):
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectorizer = TfidfVectorizer(stop_words="english", sublinear_tf=True, ngram_range=(1, 2))
        try:
            matrix = vectorizer.fit_transform(texts)
        except ValueError:  # nothing but stop words
            return np.zeros((len(texts), 1), dtype=np.float32)
        dimensions = min(self.MAX_DIMENSIONS, len(texts) - 1, matrix.shape[1] - 1)
        if dimensions >= 2:
            # Identical texts have zero variance; sklearn's variance ratios then divide
            # by zero, which doesn't affect the vectors themselves.
            with np.errstate(divide="ignore", invalid="ignore"):
                svd = TruncatedSVD(n_components=dimensions, random_state=0)
                matrix = svd.fit_transform(matrix)
        else:
            matrix = matrix.toarray()
        return _normalise(np.nan_to_num(matrix))


@cache
def _load_sentence_transformer(model_name):
    return SentenceTransformerEmbedder(model_name)


# Models that failed to load in this process, so auto mode doesn't retry a slow
# download on every material.
_unavailable = set()


def get_embedder():
    """The configured embedder; the model loads once per process and is reused."""
    backend = settings.EMBEDDING_BACKEND
    if backend == "tfidf" or (backend == "auto" and settings.EMBEDDING_MODEL in _unavailable):
        return TfidfEmbedder()
    try:
        return _load_sentence_transformer(settings.EMBEDDING_MODEL)
    except Exception as exc:
        if backend == "sentence-transformers":
            raise
        _unavailable.add(settings.EMBEDDING_MODEL)
        logger.warning("Embedding model unavailable (%s); using TF-IDF instead.", exc)
        return TfidfEmbedder()
