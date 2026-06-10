"""Central configuration for the CS + IT Helpdesk data pipeline (Day 10).

Mọi hằng số "biết được" của pipeline nằm ở đây: đường dẫn, ngưỡng SLA,
golden questions cho agent. Giữ ở một chỗ để docs/data_contract.md trỏ tới được.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SAMPLE = DATA / "sample"
RAW = DATA / "raw"
CLEANED = DATA / "cleaned"
EMBEDDED = DATA / "embedded"
QUARANTINE = DATA / "quarantine"
REPORTS = ROOT / "reports"
MON_STATE = ROOT / "monitoring" / "state.json"
MON_BASELINE = ROOT / "monitoring" / "baseline.json"

SAMPLE_POSTGRES = SAMPLE / "postgres_tickets.csv"
SAMPLE_JIRA = SAMPLE / "jira_tickets.json"
SAMPLE_SOP = SAMPLE / "sop_documents.csv"


def ensure_dirs() -> None:
    for d in (RAW, CLEANED, EMBEDDED, QUARANTINE, REPORTS, MON_STATE.parent):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Reproducible "now" -- giữ run_id ổn định khi chấm bài
# ---------------------------------------------------------------------------
# Mặc định khớp với "Expected log" trong slide 39 (run_id=2026-02-10T14:35).
# Có thể override bằng biến môi trường LAB_NOW (ISO 8601).
DEFAULT_LAB_NOW = "2026-02-10T14:35:00+00:00"


def lab_now() -> datetime:
    raw = os.environ.get("LAB_NOW", DEFAULT_LAB_NOW)
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def make_run_id(now: datetime | None = None) -> str:
    return (now or lab_now()).strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------------------
# SLA & monitoring thresholds (slide 8, 24, 25, 28)
# ---------------------------------------------------------------------------
# "policy refund phải reflect trong agent <= 4 giờ sau khi PDF ký"
FRESHNESS_SLA_HOURS = 4.0
FRESHNESS_WARN_RATIO = 0.5          # warn @ 50% SLA, page @ 100% SLA
VOLUME_DROP_WARN_PCT = 20.0         # cảnh báo nếu volume tụt > 20% so với baseline
NULL_RATE_WARN_PCT = 10.0           # cảnh báo nếu null-rate effective_date > 10%
MIN_OCR_CONFIDENCE = 0.60           # < 0.60 -> flag human review (quarantine)
LOW_OCR_WARN = 0.85                 # < 0.85 -> warn nhưng vẫn embed

# effective_date của data tri thức phải theo định dạng canonical này
DATE_REGEX = r"^\d{4}-\d{2}-\d{2}$"


# ---------------------------------------------------------------------------
# Golden questions (slide 9: "3 câu hỏi golden đặt trước cho agent")
# ---------------------------------------------------------------------------
GOLDEN_QUESTIONS = [
    {
        "id": "q1",
        "question": "Chính sách hoàn tiền (refund) cho khách trong bao nhiêu ngày?",
        "expect_keywords": ["7", "ngày"],
        "expect_doc": "12",            # doc_id của refund policy
        "stale_marker": "14",          # bản cũ trả lời "14 ngày" -> SAI
    },
    {
        "id": "q2",
        "question": "SLA thời gian phản hồi cho sự cố P1 là bao lâu?",
        "expect_keywords": ["2", "giờ"],
        "expect_doc": "58",
        "stale_marker": None,
    },
    {
        "id": "q3",
        "question": "Quy trình cấp quyền truy cập cần ai phê duyệt?",
        "expect_keywords": ["manager", "duyệt"],
        "expect_doc": "44",
        "stale_marker": None,
    },
]


def freshness_warn_hours() -> float:
    return FRESHNESS_SLA_HOURS * FRESHNESS_WARN_RATIO


def stale_loaded_at() -> datetime:
    """Mốc 'sync trễ' dùng cho kịch bản incident (slide 3/31: freshness=17h)."""
    return lab_now() - timedelta(hours=17)
