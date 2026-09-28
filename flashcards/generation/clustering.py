"""Groups chunk embeddings into concepts."""

from dataclasses import dataclass, field

import numpy as np

MIN_CHUNKS_TO_CLUSTER = 4
# Roughly one concept per this many chunks (about 700 words). Silhouette scores
# alone are too flat to pick k reliably (TF-IDF vectors score ~0.02 for every k),
# so they only choose within a band around this size-based target.
CHUNKS_PER_CONCEPT = 6
K_BAND = 2
REPRESENTATIVES = 4  # chunks per concept sent on for card generation


@dataclass
class Concept:
    """A group of related chunks, in document order."""

    chunk_indices: list[int]
    representative_indices: list[int]
    keywords: list[str] = field(default_factory=list)

    @property
    def first_index(self):
        return min(self.chunk_indices)


def choose_labels(vectors, max_clusters):
    """Cluster labels for each vector.

    k is aimed at the document's length and fine-tuned by silhouette score.
    """
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = len(vectors)
    if n < MIN_CHUNKS_TO_CLUSTER:
        return np.zeros(n, dtype=int)

    best_labels, best_score = np.zeros(n, dtype=int), -1.0
    target = min(max_clusters, max(2, round(n / CHUNKS_PER_CONCEPT)))
    lower = max(2, target - K_BAND)
    upper = min(max_clusters, n // 2, target + K_BAND)
    for k in range(lower, max(lower, upper) + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(vectors)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(vectors, labels, metric="cosine")
        if score > best_score:
            best_labels, best_score = labels, score
    return _merge_singletons(vectors, best_labels)


def _merge_singletons(vectors, labels):
    """Moves one-chunk clusters (usually stray text) into their nearest real cluster."""
    labels = labels.copy()
    sizes = {label: int((labels == label).sum()) for label in set(labels)}
    big = [label for label, size in sizes.items() if size > 1]
    if not big:
        return labels
    centroids = {label: vectors[labels == label].mean(axis=0) for label in big}
    for label, size in sizes.items():
        if size == 1:
            i = int(np.flatnonzero(labels == label)[0])
            labels[i] = max(big, key=lambda b: float(vectors[i] @ centroids[b]))
    return labels


def build_concepts(vectors, labels, texts):
    """Concepts in the order they first appear, each with its most central chunks."""
    concepts = []
    for label in sorted(set(labels)):
        members = [int(i) for i in np.flatnonzero(labels == label)]
        centroid = vectors[members].mean(axis=0)
        by_centrality = sorted(members, key=lambda i: -float(vectors[i] @ centroid))
        concepts.append(
            Concept(
                chunk_indices=members,
                representative_indices=sorted(by_centrality[:REPRESENTATIVES]),
            )
        )
    _add_keywords(concepts, texts)
    return sorted(concepts, key=lambda c: c.first_index)


def _add_keywords(concepts, texts):
    """Terms that set each concept apart from the others (TF-IDF across concepts)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    documents = [" ".join(texts[i] for i in c.chunk_indices) for c in concepts]
    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b",
        sublinear_tf=True,
    )
    try:
        matrix = vectorizer.fit_transform(documents).toarray()
    except ValueError:
        return
    terms = vectorizer.get_feature_names_out()
    for concept, row in zip(concepts, matrix, strict=True):
        ranked = [terms[i] for i in np.argsort(-row) if row[i] > 0]
        keywords = []
        for term in ranked:
            # Skip a word already covered by a chosen phrase, and vice versa.
            if any(term in kept or kept in term for kept in keywords):
                continue
            keywords.append(term)
            if len(keywords) == 5:
                break
        concept.keywords = keywords
