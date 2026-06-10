"""Data quality as code -- expectation suite (slide 24).

Mô phỏng API của Great Expectations nhưng thuần stdlib:
    batch.expect_column_values_to_not_be_null("content")
    batch.expect_column_values_to_be_unique("doc_id")
    batch.expect_column_values_to_match_regex("effective_date", DATE_REGEX)
    if expectations_fail:
        raise PipelineHalt("bad data before agent")

6 dimensions (slide 24): completeness, accuracy, consistency, uniqueness, timeliness, validity.
Mức nghiêm trọng (slide 27): ở đây mọi expectation đều là HARD gate (halt) vì đã
chạy SAU bước clean -- row "mềm" (missing date, low OCR) đã được quarantine trước đó.
"""
from __future__ import annotations

import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable

import config


def _is_valid_iso_date(value: Any) -> bool:
    """True nếu là ngày lịch hợp lệ YYYY-MM-DD (bắt cả tháng 13, ngày 45)."""
    if value is None:
        return False
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


class PipelineHalt(Exception):
    """Raise khi data vi phạm contract cứng -> dừng pipeline có kiểm soát."""


@dataclass
class ExpectationResult:
    name: str
    column: str
    success: bool
    unexpected: int
    detail: str = ""


@dataclass
class SuiteResult:
    results: list[ExpectationResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def failed(self) -> list[ExpectationResult]:
        return [r for r in self.results if not r.success]


class Batch:
    """Một 'batch' record để chạy expectation lên (giống GE Validator)."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = records
        self.results: list[ExpectationResult] = []

    def _column(self, col: str) -> list[Any]:
        return [r.get(col) for r in self.records]

    def _add(self, name, column, predicate: Callable[[Any], bool], detail_fmt: str):
        bad = [v for v in self._column(column) if not predicate(v)]
        res = ExpectationResult(
            name=name,
            column=column,
            success=(len(bad) == 0),
            unexpected=len(bad),
            detail=("" if not bad else detail_fmt.format(sample=bad[:3])),
        )
        self.results.append(res)
        return res

    # --- các expectation kiểu Great Expectations ---
    def expect_column_values_to_not_be_null(self, column: str):
        return self._add(
            "not_null", column,
            lambda v: v is not None and str(v).strip() != "",
            "null/empty values, ví dụ: {sample}",
        )

    def expect_column_values_to_be_unique(self, column: str):
        seen: dict[Any, int] = {}
        for v in self._column(column):
            seen[v] = seen.get(v, 0) + 1
        dups = [k for k, n in seen.items() if n > 1]
        res = ExpectationResult(
            "unique", column, success=(len(dups) == 0),
            unexpected=len(dups),
            detail=("" if not dups else f"duplicate keys: {dups[:3]}"),
        )
        self.results.append(res)
        return res

    def expect_column_values_to_match_regex(self, column: str, pattern: str):
        rx = re.compile(pattern)
        return self._add(
            "match_regex", column,
            lambda v: v is not None and bool(rx.match(str(v))),
            "không khớp regex, ví dụ: {sample}",
        )

    def expect_column_values_to_be_valid_date(self, column: str):
        # validity thật: bắt date đúng format nhưng sai lịch (vd 2026-13-45)
        return self._add(
            "valid_date", column, _is_valid_iso_date,
            "không phải ngày lịch hợp lệ, ví dụ: {sample}",
        )


def run_suite(cleaned: list[dict[str, Any]]) -> SuiteResult:
    """Chạy expectation suite lên tập cleaned (embed-eligible).

    Vì missing-date & low-OCR đã được quarantine ở bước clean nên ở đây:
      - content     : completeness  (not null)
      - doc_id      : uniqueness    (sau dedupe/supersede phải unique)
      - effective_date: validity    (đúng định dạng canonical) + completeness
    """
    batch = Batch(cleaned)
    batch.expect_column_values_to_not_be_null("content")
    batch.expect_column_values_to_be_unique("doc_id")
    batch.expect_column_values_to_not_be_null("effective_date")
    batch.expect_column_values_to_match_regex("effective_date", config.DATE_REGEX)
    batch.expect_column_values_to_be_valid_date("effective_date")
    return SuiteResult(results=list(batch.results))


def validate_or_halt(cleaned: list[dict[str, Any]]) -> SuiteResult:
    suite = run_suite(cleaned)
    if not suite.success:
        reasons = "; ".join(f"{r.name}({r.column})={r.unexpected}" for r in suite.failed)
        raise PipelineHalt(f"bad data before agent -> {reasons}")
    return suite
