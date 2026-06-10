"""Ingestion layer -- kéo data từ 3 nguồn về một schema chung (canonical record).

Nguồn (slide 13, 19):
    - PostgreSQL  : bảng ticket helpdesk      -> source_type="postgres"
    - Jira API    : issue vận hành             -> source_type="jira"
    - PDF/HTML SOP: policy & quy trình         -> source_type="file"

Lab này đọc từ data/sample/ thay cho kết nối thật, nhưng vẫn:
    - ghi raw snapshot kèm run_id (lineage),
    - mô phỏng các "điểm tử" (failure) khi bật --inject-corruption:
        * PostgreSQL sync 02:00 fail  -> mất ~28% row + freshness 17h (slide 3/31),
        * thêm 1 row policy có effective_date hỏng -> để expectation HALT (slide 27),
        * thêm 1 row OCR mojibake      -> để cleaning flag review.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import config


# Canonical schema mọi nguồn map về. Đây là "đầu vào" của data_contract.md.
CANONICAL_FIELDS = [
    "doc_id",
    "source_type",
    "source_uri",
    "title",
    "effective_date",
    "version",
    "ocr_confidence",
    "content",
]


@dataclass
class IngestResult:
    records: list[dict[str, Any]]
    # số row đọc được mỗi nguồn (cho volume monitoring)
    counts: dict[str, int]
    # thời điểm nạp xong mỗi nguồn (cho freshness monitoring)
    loaded_at: dict[str, datetime]
    notes: list[str] = field(default_factory=list)


def _row(doc_id, source_type, source_uri, title, effective_date, version, ocr, content):
    return {
        "doc_id": str(doc_id).strip(),
        "source_type": source_type,
        "source_uri": source_uri,
        "title": title,
        "effective_date": effective_date,
        "version": (version or None),
        "ocr_confidence": float(ocr) if ocr not in (None, "") else 1.0,
        "content": content if content is not None else "",
    }


def _read_postgres(drop_tail: int = 0) -> list[dict[str, Any]]:
    """Đọc ticket từ 'PostgreSQL' (CSV mẫu). drop_tail mô phỏng sync dở dang."""
    rows: list[dict[str, Any]] = []
    with open(config.SAMPLE_POSTGRES, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(
                _row(
                    doc_id=r["ticket_id"],
                    source_type="postgres",
                    source_uri=r["source_uri"],
                    title=r["subject"],
                    effective_date=r["updated_at"],
                    version=None,
                    ocr=1.0,
                    content=r["body"],
                )
            )
    if drop_tail:
        rows = rows[: max(0, len(rows) - drop_tail)]
    return rows


def _read_jira() -> list[dict[str, Any]]:
    with open(config.SAMPLE_JIRA, encoding="utf-8") as fh:
        issues = json.load(fh)
    return [
        _row(
            doc_id=i["key"],
            source_type="jira",
            source_uri=f"jira/{i['key']}",
            title=i["summary"],
            effective_date=i["updated"],
            version=None,
            ocr=1.0,
            content=i["description"],
        )
        for i in issues
    ]


def _read_files() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(config.SAMPLE_SOP, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(
                _row(
                    doc_id=r["doc_id"],
                    source_type="file",
                    source_uri=r["source_uri"],
                    title=r["title"],
                    effective_date=r["effective_date"],
                    version=r["version"],
                    ocr=r["ocr_confidence"],
                    content=r["content"],
                )
            )
    return rows


def _corruption_rows() -> list[dict[str, Any]]:
    """Row độc hại tiêm vào khi --inject-corruption (Sprint 3)."""
    return [
        # effective_date hỏng, không parse được -> expectation regex FAIL -> HALT
        _row(
            doc_id="95",
            source_type="file",
            source_uri="sop/holiday-policy-bad.pdf",
            title="Holiday Policy",
            effective_date="2026-13-45",
            version="v1",
            ocr=0.97,
            content="Chính sách nghỉ lễ: số ngày nghỉ theo quy định công ty.",
        ),
        # OCR mojibake (ký tự thay thế U+FFFD) -> cleaning flag human review
        _row(
            doc_id="96",
            source_type="file",
            source_uri="sop/scan-noisy.pdf",
            title="Noisy Scan SOP",
            effective_date="2026-02-09",
            version="v1",
            ocr=0.42,
            content="Quy tr�nh x� l� s� c� nghi�m tr�ng.",
        ),
    ]


def ingest_all(inject_corruption: bool = False) -> IngestResult:
    now = config.lab_now()

    pg_drop = 5 if inject_corruption else 0  # 5/18 ~= -28% volume (slide 25)
    postgres = _read_postgres(drop_tail=pg_drop)
    jira = _read_jira()
    files = _read_files()

    notes: list[str] = []
    loaded_at = {"postgres": now, "jira": now, "file": now}

    if inject_corruption:
        files = files + _corruption_rows()
        # Mô phỏng job 02:00 fail -> nguồn postgres "đứng" từ 17h trước (freshness page)
        loaded_at["postgres"] = config.stale_loaded_at()
        notes.append("ingest_02:00 retry exhausted -> postgres sync stale (freshness 17h)")
        notes.append(f"partial sync: dropped {pg_drop} postgres rows (volume drop)")
        notes.append("injected corruption rows: doc_id=95 (bad date), doc_id=96 (OCR mojibake)")

    # Mô phỏng pagination + rate-limit note cho API (slide 16)
    notes.append(f"jira API: fetched {len(jira)} issues via cursor pagination (rate-limit ok)")

    records = postgres + jira + files
    counts = {"postgres": len(postgres), "jira": len(jira), "file": len(files)}

    # Ghi raw snapshot kèm run_id (lineage / reproduce)
    config.ensure_dirs()
    run_id = config.make_run_id(now)
    snapshot = config.RAW / f"raw_{run_id.replace(':', '-')}.json"
    with open(snapshot, "w", encoding="utf-8") as fh:
        json.dump(
            {"run_id": run_id, "counts": counts, "records": records},
            fh,
            ensure_ascii=False,
            indent=2,
        )

    return IngestResult(records=records, counts=counts, loaded_at=loaded_at, notes=notes)
