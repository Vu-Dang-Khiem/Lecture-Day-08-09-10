"""Before / after eval -- đo ảnh hưởng của data lên câu trả lời agent (slide 38, 40).

BEFORE : agent trả lời trên store dựng từ RAW (chưa clean) -> bản policy cũ thắng.
AFTER  : agent trả lời trên store dựng từ CLEANED -> bản policy mới + version metadata.

Xuất reports/before_after_eval.csv làm bằng chứng nộp bài.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Any

import config
from agent import rag


@dataclass
class Row:
    qid: str
    question: str
    before_answer: str
    before_doc: str
    before_correct: bool
    after_answer: str
    after_doc: str
    after_version: str | None
    after_date: str | None
    after_correct: bool


def _is_correct(ans: rag.Answer, gq: dict[str, Any]) -> bool:
    text = ans.text.lower()
    has_keywords = all(kw.lower() in text for kw in gq["expect_keywords"])
    stale = gq.get("stale_marker")
    no_stale = True if stale is None else (stale.lower() not in text)
    return has_keywords and no_stale


def _kb_only(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agent KB = tài liệu SOP/policy (source_type='file'); ticket/jira là data vận hành.

    BEFORE dùng RAW file records (chưa dedupe/version -> bản policy cũ còn đó),
    AFTER dùng cleaned file records (đã supersede sang bản mới + version metadata).
    """
    return [r for r in records if r.get("source_type") == "file" and (r.get("content") or "").strip()]


def run_before_after(raw_records: list[dict[str, Any]],
                     cleaned_records: list[dict[str, Any]],
                     run_id: str) -> list[Row]:
    before_store = rag.build_store(_kb_only(raw_records))
    after_store = rag.build_store(_kb_only(cleaned_records))

    rows: list[Row] = []
    for gq in config.GOLDEN_QUESTIONS:
        b = rag.answer(before_store, gq["question"])
        a = rag.answer(after_store, gq["question"])
        rows.append(
            Row(
                qid=gq["id"],
                question=gq["question"],
                before_answer=b.text,
                before_doc=b.cited_doc,
                before_correct=_is_correct(b, gq),
                after_answer=a.text,
                after_doc=a.cited_doc,
                after_version=a.cited_version,
                after_date=a.cited_date,
                after_correct=_is_correct(a, gq),
            )
        )
    _write_csv(rows, run_id)
    return rows


def _write_csv(rows: list[Row], run_id: str) -> None:
    config.ensure_dirs()
    out = config.REPORTS / "before_after_eval.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "run_id", "question_id", "question",
            "before_answer", "before_doc", "before_correct",
            "after_answer", "after_doc", "after_version", "after_effective_date", "after_correct",
        ])
        for r in rows:
            w.writerow([
                run_id, r.qid, r.question,
                r.before_answer, r.before_doc, r.before_correct,
                r.after_answer, r.after_doc, r.after_version, r.after_date, r.after_correct,
            ])
