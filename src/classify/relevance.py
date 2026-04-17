from __future__ import annotations

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency at runtime
    SentenceTransformer = None

from src.domain.models import ThreadContext

TOPICS = [
    "save prompts and organize prompt libraries",
    "find reusable prompts for ChatGPT, Claude, Midjourney, Cursor, or Lovable",
    "stop rewriting prompts from scratch every time",
    "prompt workflow, prompt storage, prompt discovery, prompt reuse",
    "consistent AI outputs and better prompt structure",
]


class RelevanceClassifier:
    def __init__(self):
        self.model = SentenceTransformer("BAAI/bge-small-en-v1.5") if SentenceTransformer else None
        self.topic_embeddings = self.model.encode(TOPICS).tolist() if self.model else None

    def score(self, thread: ThreadContext):
        text = thread.combined_text.lower()
        keyword_hits = sum(
            token in text
            for token in [
                "prompt",
                "prompts",
                "chatgpt",
                "claude",
                "cursor",
                "lovable",
                "midjourney",
                "stable diffusion",
                "system prompt",
                "reuse",
                "library",
            ]
        )
        keyword_score = min(1.0, 0.18 * keyword_hits)
        if self.model and self.topic_embeddings:
            embedding = self.model.encode([thread.combined_text]).tolist()[0]
            similarities = []
            for topic_embedding in self.topic_embeddings:
                numerator = sum(a * b for a, b in zip(embedding, topic_embedding, strict=False))
                a_mag = sum(a * a for a in embedding) ** 0.5
                b_mag = sum(b * b for b in topic_embedding) ** 0.5
                similarities.append(numerator / (a_mag * b_mag))
            return round(max(0.0, max(similarities)), 3)
        return round(keyword_score, 3)
