"""Agent surface tối giản -- embed + retrieve + answer (no external deps).

Mục đích: đo *ảnh hưởng của data lên câu trả lời agent* (before/after), KHÔNG phải
xây LLM thật. Vì vậy:
  - "embedding" = bag-of-words term-frequency (đủ để retrieval phân biệt chunk),
  - retriever   = cosine similarity, tie-break theo thứ tự nạp (store order),
  - answer      = trích câu trong chunk được retrieve top-1.

Chính sự tie-break theo store-order tái hiện đúng bug trong slide 3:
data bẩn (chưa dedupe/version) -> bản policy CŨ đứng trước -> agent trả lời "14 ngày" (SAI).
Sau clean -> chỉ còn bản v4 -> agent trả lời "7 ngày" (ĐÚNG).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import config

_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def embed(text: str) -> dict[str, float]:
    """Vector = term frequency (đủ cho lab; thay bằng model embedding thật khi production)."""
    tf = Counter(tokenize(text))
    return {term: float(n) for term, n in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Chunk:
    order: int
    doc_id: str
    version: str | None
    effective_date: str | None
    source_uri: str
    text: str
    vector: dict[str, float]


class VectorStore:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []

    def add_record(self, rec: dict[str, Any]) -> None:
        text = rec.get("content") or ""
        self.chunks.append(
            Chunk(
                order=len(self.chunks),
                doc_id=rec["doc_id"],
                version=rec.get("version"),
                effective_date=rec.get("effective_date"),
                source_uri=rec.get("source_uri", ""),
                text=text,
                vector=embed(text),
            )
        )

    def search(self, query: str, k: int = 1) -> list[tuple[float, Chunk]]:
        qv = embed(query)
        scored = [(_cosine(qv, c.vector), c) for c in self.chunks]
        # tie-break: điểm cao trước; bằng điểm -> chunk nạp trước thắng (store order)
        scored.sort(key=lambda sc: (-sc[0], sc[1].order))
        return scored[:k]

    def to_json(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "count": len(self.chunks),
            "chunks": [
                {
                    "doc_id": c.doc_id,
                    "version": c.version,
                    "effective_date": c.effective_date,
                    "source_uri": c.source_uri,
                    "text": c.text,
                }
                for c in self.chunks
            ],
        }


def build_store(records: list[dict[str, Any]]) -> VectorStore:
    store = VectorStore()
    for rec in records:
        store.add_record(rec)
    return store


def persist_store(store: VectorStore, run_id: str) -> None:
    config.ensure_dirs()
    out = config.EMBEDDED / "vector_store.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(store.to_json(run_id), fh, ensure_ascii=False, indent=2)


@dataclass
class Answer:
    text: str
    cited_doc: str
    cited_version: str | None
    cited_date: str | None
    score: float


def answer(store: VectorStore, question: str) -> Answer:
    hits = store.search(question, k=1)
    if not hits or hits[0][0] == 0.0:
        return Answer("Không tìm thấy thông tin trong cơ sở tri thức.", "-", None, None, 0.0)
    score, c = hits[0]
    return Answer(
        text=c.text,
        cited_doc=c.doc_id,
        cited_version=c.version,
        cited_date=c.effective_date,
        score=score,
    )
