"""Data observability -- 5 pillars (slide 25, 28).

    1. Freshness     : data có cập nhật đúng nhịp không?  (vs SLA 4h, warn 50% / page 100%)
    2. Volume        : số record có rơi/spike đột ngột không?  (vs baseline)
    3. Distribution  : null-rate / độ dài / cardinality có lệch bất thường không?
    4. Schema        : cấu trúc có drift không?  (so với contract canonical)
    5. Lineage       : biết lỗi đi từ nguồn nào tới output nào.

Ngưỡng cảnh báo: PASS / WARN / PAGE (slide 8).
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import config

PASS, WARN, PAGE = "PASS", "WARN", "PAGE"

# schema mà mọi record phải có sau ingest (cho schema-drift check)
EXPECTED_SCHEMA = {
    "doc_id", "source_type", "source_uri", "title",
    "effective_date", "version", "ocr_confidence", "content",
}


@dataclass
class Check:
    pillar: str
    name: str
    status: str
    value: str
    detail: str = ""


@dataclass
class MonitorReport:
    checks: list[Check] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)

    @property
    def worst(self) -> str:
        order = {PASS: 0, WARN: 1, PAGE: 2}
        return max((c.status for c in self.checks), key=lambda s: order[s], default=PASS)

    def add(self, *args, **kwargs):
        self.checks.append(Check(*args, **kwargs))


# ---------------------------------------------------------------------------
# Pillar 1: Freshness
# ---------------------------------------------------------------------------
def check_freshness(report: MonitorReport, loaded_at: dict[str, datetime]) -> None:
    now = config.lab_now()
    sla = config.FRESHNESS_SLA_HOURS
    warn_h = config.freshness_warn_hours()
    for source, ts in sorted(loaded_at.items()):
        hours = (now - ts).total_seconds() / 3600.0
        if hours >= sla:
            status = PAGE
        elif hours >= warn_h:
            status = WARN
        else:
            status = PASS
        report.add(
            "freshness", f"freshness[{source}]", status,
            f"{hours:.1f}h",
            f"SLA={sla:.0f}h (warn>{warn_h:.0f}h, page>{sla:.0f}h)",
        )


# ---------------------------------------------------------------------------
# Pillar 2: Volume (vs baseline)
# ---------------------------------------------------------------------------
def _load_baseline() -> dict[str, int]:
    if config.MON_BASELINE.exists():
        with open(config.MON_BASELINE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_baseline(counts: dict[str, int]) -> None:
    config.ensure_dirs()
    with open(config.MON_BASELINE, "w", encoding="utf-8") as fh:
        json.dump(counts, fh, ensure_ascii=False, indent=2)


def check_volume(report: MonitorReport, counts: dict[str, int]) -> None:
    baseline = _load_baseline()
    for source, n in sorted(counts.items()):
        base = baseline.get(source)
        if base is None or base == 0:
            report.add("volume", f"volume[{source}]", PASS, f"{n} rows", "no baseline yet")
            continue
        delta = (n - base) / base * 100.0
        status = WARN if abs(delta) >= config.VOLUME_DROP_WARN_PCT else PASS
        report.add(
            "volume", f"volume[{source}]", status,
            f"{n} rows ({delta:+.0f}%)",
            f"baseline={base}",
        )


# ---------------------------------------------------------------------------
# Pillar 3: Distribution / anomaly (slide 28)
# ---------------------------------------------------------------------------
def check_distribution(report: MonitorReport, records: list[dict[str, Any]]) -> None:
    if not records:
        report.add("distribution", "null_rate[effective_date]", WARN, "n/a", "empty batch")
        return
    n = len(records)
    null_dates = sum(1 for r in records if not r.get("effective_date"))
    null_rate = null_dates / n * 100.0
    status = WARN if null_rate >= config.NULL_RATE_WARN_PCT else PASS
    report.add("distribution", "null_rate[effective_date]", status, f"{null_rate:.0f}%",
               f"{null_dates}/{n} rows null")

    lengths = [len(r.get("content") or "") for r in records]
    report.add("distribution", "content_length", PASS,
               f"min={min(lengths)} median={int(statistics.median(lengths))} max={max(lengths)}")

    cardinality = len({r["doc_id"] for r in records})
    report.add("distribution", "cardinality[doc_id]", PASS, f"{cardinality} unique")

    moji = sum(1 for r in records if "encoding_replacement_char" in (r.get("_notes") or []))
    if moji:
        report.add("distribution", "ocr_noise", WARN, f"{moji} rows", "ký tự thay thế (mojibake)")


# ---------------------------------------------------------------------------
# Pillar 4: Schema drift
# ---------------------------------------------------------------------------
def check_schema(report: MonitorReport, records: list[dict[str, Any]]) -> None:
    drift = set()
    for r in records:
        missing = EXPECTED_SCHEMA - set(r.keys())
        drift |= missing
    if drift:
        report.add("schema", "schema_contract", PAGE, "DRIFT", f"thiếu cột: {sorted(drift)}")
    else:
        report.add("schema", "schema_contract", PASS, "stable")


# ---------------------------------------------------------------------------
# Pillar 5: Lineage
# ---------------------------------------------------------------------------
def build_lineage(report: MonitorReport, counts: dict[str, int], cleaned_n: int,
                  embedded_n: int, run_id: str) -> None:
    src = " + ".join(f"{k}({v})" for k, v in sorted(counts.items()))
    report.lineage = [
        f"sources[{src}] -> queue -> ingest_worker -> raw({sum(counts.values())})",
        f"raw -> clean -> cleaned({cleaned_n}) -> validate(expectations)",
        f"cleaned -> embed -> vector_store({embedded_n})  [run_id={run_id}]",
    ]


def run_monitor(records: list[dict[str, Any]], counts: dict[str, int],
                loaded_at: dict[str, datetime], run_id: str) -> MonitorReport:
    """Quan sát SAU clean, TRƯỚC validate -- để bắt 'chạy nhưng sai' kể cả khi sẽ halt."""
    report = MonitorReport()
    check_freshness(report, loaded_at)
    check_volume(report, counts)
    check_distribution(report, records)
    check_schema(report, records)
    return report


def save_state(run_id: str, status: str) -> None:
    config.ensure_dirs()
    state = {
        "last_run_id": run_id,
        "last_status": status,
        "last_success_run": config.make_run_id() if status == "PUBLISHED" else _prev_success(),
    }
    with open(config.MON_STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def _prev_success() -> str | None:
    if config.MON_STATE.exists():
        with open(config.MON_STATE, encoding="utf-8") as fh:
            return json.load(fh).get("last_success_run")
    return None
