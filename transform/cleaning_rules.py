"""Transform / cleaning rules -- làm sạch & chuẩn hoá trước khi agent dùng (slide 21-23).

Bộ rule (khớp "Đáp án mẫu" slide 23):
  Clean / normalize
    1. Trim whitespace ở content & title.
    2. Parse date về YYYY-MM-DD (canonical).
    3. Unicode NFC + đánh dấu ký tự thay thế.
  Reject (cứng)
    4. Drop row nếu content rỗng sau trim.
    5. Drop duplicate theo content_hash; supersede version cũ theo natural key doc_id.
  Flag / quarantine
    6. effective_date thiếu -> flag review_missing_date, KHÔNG embed tới khi SME duyệt.
       OCR confidence thấp / mojibake -> flag low_ocr, chờ human review.
    7. Mọi drop/flag được log vào quarantine.csv kèm run_id.

"Transform = code + contract, không sửa tay ngay trước khi demo" (slide 21).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import config

REPLACEMENT_CHAR = "�"


# ---------------------------------------------------------------------------
# Rule 1-3: chuẩn hoá field
# ---------------------------------------------------------------------------
def normalize_unicode(text: str) -> str:
    """NFC normalize. Trả về (text_chuẩn, số ký tự thay thế gặp phải)."""
    return unicodedata.normalize("NFC", text)


def trim(text: str) -> str:
    # gộp khoảng trắng thừa + bỏ đầu/cuối
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: str | None) -> tuple[str | None, str]:
    """Chuẩn hoá date -> ('YYYY-MM-DD', status).

    status: 'ok' | 'missing' | 'invalid'
      - missing : None/rỗng  -> flag review (quarantine)
      - invalid : có giá trị nhưng không parse được -> giữ nguyên để expectation FAIL (halt)
    """
    if value is None or str(value).strip() == "":
        return None, "missing"
    raw = str(value).strip()
    fmts = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d")
    for fmt in fmts:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d"), "ok"
        except ValueError:
            continue
    return raw, "invalid"  # giữ giá trị xấu để contract bắt được


def content_hash(content: str, doc_id: str, source_type: str) -> str:
    payload = f"{source_type}|{doc_id}|{content}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Kết quả cleaning
# ---------------------------------------------------------------------------
@dataclass
class CleanResult:
    cleaned: list[dict[str, Any]]          # embed-eligible (đã qua mọi rule)
    quarantined: list[dict[str, Any]]      # flag/reject, KÈM lý do
    stats: dict[str, int] = field(default_factory=dict)


def _quarantine(record: dict[str, Any], action: str, reason: str) -> dict[str, Any]:
    q = dict(record)
    q["_action"] = action          # reject | flag
    q["_reason"] = reason
    return q


def clean_records(raw: list[dict[str, Any]], run_id: str) -> CleanResult:
    cleaned: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    stats = {
        "raw": len(raw),
        "dropped_empty": 0,
        "dropped_duplicates": 0,
        "dropped_superseded": 0,
        "flagged_missing_date": 0,
        "flagged_low_ocr": 0,
        "flagged_encoding": 0,
        "invalid_date": 0,
    }

    # --- Pass 1: chuẩn hoá field + reject content rỗng + flag missing/ocr ---
    staged: list[dict[str, Any]] = []
    for rec in raw:
        r = dict(rec)
        title = trim(normalize_unicode(r.get("title") or ""))
        content_raw = normalize_unicode(r.get("content") or "")
        content = trim(content_raw)
        r["title"] = title
        r["content"] = content

        # Rule 4: reject content rỗng
        if content == "":
            stats["dropped_empty"] += 1
            quarantined.append(_quarantine(r, "reject", "empty_content"))
            continue

        # Rule 2: parse date
        norm_date, date_status = parse_date(r.get("effective_date"))
        r["effective_date"] = norm_date
        r["effective_date_status"] = date_status
        if date_status == "invalid":
            stats["invalid_date"] += 1  # sẽ bị expectation suite bắt (halt)

        # Rule 3: đánh dấu mojibake
        notes: list[str] = []
        if REPLACEMENT_CHAR in content_raw:
            stats["flagged_encoding"] += 1
            notes.append("encoding_replacement_char")

        r["content_hash"] = content_hash(content, r["doc_id"], r["source_type"])
        r["_notes"] = notes
        staged.append(r)

    # --- Pass 2: dedupe exact (content_hash) ---
    seen_hash: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in staged:
        h = r["content_hash"]
        if h in seen_hash:
            stats["dropped_duplicates"] += 1
            quarantined.append(_quarantine(r, "reject", "duplicate_content_hash"))
            continue
        seen_hash.add(h)
        deduped.append(r)

    # --- Pass 3: version supersede theo natural key doc_id (giữ effective_date mới nhất) ---
    # Gom theo doc_id; nếu nhiều bản có date -> giữ bản mới nhất, các bản cũ -> superseded.
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for r in deduped:
        by_doc.setdefault(r["doc_id"], []).append(r)

    survivors: list[dict[str, Any]] = []
    for doc_id, group in by_doc.items():
        dated = [r for r in group if r["effective_date_status"] == "ok"]
        if len(group) == 1:
            survivors.append(group[0])
            continue
        if dated:
            winner = max(dated, key=lambda r: r["effective_date"])
            for r in group:
                if r is winner:
                    continue
                stats["dropped_superseded"] += 1
                quarantined.append(
                    _quarantine(r, "reject", f"superseded_by_{winner.get('version') or winner['effective_date']}")
                )
            survivors.append(winner)
        else:
            # không bản nào có date hợp lệ -> giữ bản đầu, phần còn lại superseded
            survivors.append(group[0])
            for r in group[1:]:
                stats["dropped_superseded"] += 1
                quarantined.append(_quarantine(r, "reject", "superseded_no_date"))

    # --- Pass 4: flag missing date / low OCR (quarantine, KHÔNG embed) ---
    for r in survivors:
        if r["effective_date_status"] == "missing":
            stats["flagged_missing_date"] += 1
            quarantined.append(_quarantine(r, "flag", "review_missing_date"))
            continue
        if r["ocr_confidence"] < config.MIN_OCR_CONFIDENCE or "encoding_replacement_char" in r["_notes"]:
            stats["flagged_low_ocr"] += 1
            quarantined.append(_quarantine(r, "flag", "review_low_ocr"))
            continue
        cleaned.append(r)

    stats["cleaned"] = len(cleaned)
    stats["quarantined"] = len(quarantined)
    return CleanResult(cleaned=cleaned, quarantined=quarantined, stats=stats)
