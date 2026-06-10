"""ETL pipeline cho trợ lý nội bộ CS + IT Helpdesk (Day 10 hands-on).

Run order (slide 39):  ingest -> clean -> monitor -> validate -> embed -> publish

    python etl_pipeline.py                     # chạy bình thường (happy path)
    python etl_pipeline.py --inject-corruption # Sprint 3: tiêm lỗi -> đo & HALT

Definition of Done (slide 41):
  - run_id gắn mọi artifact (raw/cleaned/embed/report)
  - log số record raw -> cleaned -> embedded (drop/flag có giải thích)
  - expectation suite chạy; fail -> pipeline dừng có kiểm soát
  - >= 1 bằng chứng before/after ảnh hưởng tới câu trả lời agent
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from typing import Any

import config
from ingest import sources
from transform import cleaning_rules
from quality import expectations
from monitoring import freshness_check as obs
from agent import rag
from eval import before_after

# In tiếng Việt ra console Windows không lỗi encoding
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def banner(text: str) -> None:
    print(f"\n=== {text} ===")


def write_quarantine(quarantined: list[dict[str, Any]], run_id: str) -> None:
    out = config.QUARANTINE / "quarantine.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "doc_id", "source_type", "source_uri", "action", "reason", "content"])
        for q in quarantined:
            w.writerow([
                run_id, q.get("doc_id"), q.get("source_type"), q.get("source_uri"),
                q.get("_action"), q.get("_reason"), (q.get("content") or "")[:120],
            ])


def write_cleaned(cleaned: list[dict[str, Any]], run_id: str) -> None:
    out = config.CLEANED / "cleaned.json"
    payload = []
    for r in cleaned:
        payload.append({k: v for k, v in r.items() if not k.startswith("_")})
    with open(out, "w", newline="", encoding="utf-8") as fh:
        json.dump({"run_id": run_id, "count": len(payload), "records": payload},
                  fh, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Quality report (Markdown) -- bằng chứng nộp bài
# ---------------------------------------------------------------------------
def build_quality_report(run_id: str, mode: str, stats: dict, suite, monitor,
                         embedded_n: int, ba_rows, halted_reason: str | None) -> str:
    now = config.lab_now().isoformat()
    L: list[str] = []
    L.append(f"# Quality Report -- CS/IT Helpdesk Pipeline")
    L.append("")
    L.append(f"- **run_id**: `{run_id}`")
    L.append(f"- **mode**: `{mode}`")
    L.append(f"- **generated_at (lab_now)**: `{now}`")
    L.append(f"- **status**: {'❌ HALTED' if halted_reason else '✅ PUBLISHED'}")
    if halted_reason:
        L.append(f"- **halt_reason**: `{halted_reason}`")
    L.append("")

    L.append("## 1. Record funnel (raw → cleaned → embedded)")
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---|")
    L.append(f"| raw_records | {stats['raw']} |")
    L.append(f"| cleaned_records | {stats['cleaned']} |")
    L.append(f"| embedded_records | {embedded_n} |")
    L.append(f"| dropped_empty | {stats['dropped_empty']} |")
    L.append(f"| dropped_duplicates | {stats['dropped_duplicates']} |")
    L.append(f"| dropped_superseded | {stats['dropped_superseded']} |")
    L.append(f"| flagged_missing_date | {stats['flagged_missing_date']} |")
    L.append(f"| flagged_low_ocr | {stats['flagged_low_ocr']} |")
    L.append(f"| invalid_date (contract breach) | {stats['invalid_date']} |")
    L.append("")

    L.append("## 2. Expectation suite (data quality as code)")
    L.append("")
    L.append("| expectation | column | result | unexpected |")
    L.append("|---|---|---|---|")
    for r in suite.results:
        L.append(f"| {r.name} | `{r.column}` | {'✅ PASS' if r.success else '❌ FAIL'} | {r.unexpected} |")
    L.append("")

    L.append("## 3. Observability snapshot (5 pillars)")
    L.append("")
    L.append("| pillar | check | status | value | detail |")
    L.append("|---|---|---|---|---|")
    icon = {"PASS": "🟢", "WARN": "🟡", "PAGE": "🔴"}
    for c in monitor.checks:
        L.append(f"| {c.pillar} | `{c.name}` | {icon.get(c.status,'')} {c.status} | {c.value} | {c.detail} |")
    L.append("")
    L.append("**Lineage**")
    L.append("")
    for line in monitor.lineage:
        L.append(f"- {line}")
    L.append("")

    L.append("## 4. Before / after -- ảnh hưởng lên câu trả lời agent")
    L.append("")
    if ba_rows:
        L.append("| câu hỏi | BEFORE (raw) | đúng? | AFTER (cleaned) | version | đúng? |")
        L.append("|---|---|---|---|---|---|")
        for r in ba_rows:
            L.append(
                f"| {r.question} | {r.before_answer} | {'✅' if r.before_correct else '❌'} "
                f"| {r.after_answer} | {r.after_version or '-'} | {'✅' if r.after_correct else '❌'} |"
            )
    else:
        L.append("> Pipeline HALT trước bước embed -> không publish data xấu cho agent (đúng thiết kế).")
        L.append("> Đây chính là bằng chứng observability bắt lỗi *trước khi user thấy câu trả lời sai*.")
    L.append("")
    return "\n".join(L)


def write_report(text: str) -> None:
    out = config.REPORTS / "quality_report.md"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def run(inject_corruption: bool) -> int:
    config.ensure_dirs()
    run_id = config.make_run_id()
    mode = "inject-corruption" if inject_corruption else "normal"
    print(f"# ETL pipeline -- run_id={run_id} mode={mode}")

    # --- Stage 1: INGEST ---
    banner("Stage 1/6  INGEST")
    ing = sources.ingest_all(inject_corruption=inject_corruption)
    for n in ing.notes:
        print(f"  - {n}")
    print(f"  raw per source: {ing.counts}  (total={sum(ing.counts.values())})")

    # --- Stage 2: CLEAN ---
    banner("Stage 2/6  CLEAN")
    clean = cleaning_rules.clean_records(ing.records, run_id)
    write_cleaned(clean.cleaned, run_id)
    write_quarantine(clean.quarantined, run_id)
    s = clean.stats
    print(f"  cleaned={s['cleaned']}  quarantined={s['quarantined']}")
    print(f"  drops: empty={s['dropped_empty']} dup={s['dropped_duplicates']} "
          f"superseded={s['dropped_superseded']}")
    print(f"  flags: missing_date={s['flagged_missing_date']} low_ocr={s['flagged_low_ocr']}")

    # --- Stage 3: MONITOR (quan sát trước khi gate) ---
    banner("Stage 3/6  MONITOR (observability)")
    monitor = obs.run_monitor(clean.cleaned, ing.counts, ing.loaded_at, run_id)
    for c in monitor.checks:
        flag = {"PASS": " ", "WARN": "!", "PAGE": "#"}[c.status]
        print(f"  [{flag}] {c.status:5} {c.name:28} {c.value}  {c.detail}")

    # --- Stage 4: VALIDATE (expectation suite, có thể HALT) ---
    banner("Stage 4/6  VALIDATE (expectation suite)")
    halted_reason = None
    embedded_n = 0
    ba_rows = None
    try:
        suite = expectations.validate_or_halt(clean.cleaned)
        for r in suite.results:
            print(f"  [{'PASS' if r.success else 'FAIL'}] {r.name}({r.column})")
    except expectations.PipelineHalt as exc:
        suite = expectations.run_suite(clean.cleaned)
        halted_reason = str(exc)
        for r in suite.results:
            print(f"  [{'PASS' if r.success else 'FAIL'}] {r.name}({r.column}) unexpected={r.unexpected}")
        print(f"  >> PipelineHalt: {exc}")

    if halted_reason is None:
        # --- Stage 5: EMBED ---
        # Agent KB chỉ gồm tài liệu SOP/policy (source_type='file'); ticket/jira là
        # data vận hành -> được clean & monitor nhưng không đưa vào vector store trả lời.
        banner("Stage 5/6  EMBED")
        kb_records = [r for r in clean.cleaned if r["source_type"] == "file"]
        store = rag.build_store(kb_records)
        rag.persist_store(store, run_id)
        embedded_n = len(store.chunks)
        print(f"  embedded_records (KB docs, source_type=file)={embedded_n} "
              f"-> data/embedded/vector_store.json")

        # --- Stage 6: PUBLISH + eval ---
        banner("Stage 6/6  PUBLISH + before/after eval")
        obs.save_baseline(ing.counts)
        obs.save_state(run_id, "PUBLISHED")
        ba_rows = before_after.run_before_after(ing.records, clean.cleaned, run_id)
        for r in ba_rows:
            print(f"  {r.qid}: BEFORE[{'OK' if r.before_correct else 'WRONG'}] "
                  f"-> AFTER[{'OK' if r.after_correct else 'WRONG'}]  "
                  f"(after cites doc={r.after_doc} {r.after_version or ''})")
    else:
        banner("Stage 5/6  EMBED -- SKIPPED (halted)")
        obs.save_state(run_id, "HALTED")
        print("  Không publish data xấu cho vector store (đúng thiết kế: detect before users complain).")

    # --- Lineage + report ---
    obs.build_lineage(monitor, ing.counts, s["cleaned"], embedded_n, run_id)
    report = build_quality_report(run_id, mode, s, suite, monitor, embedded_n, ba_rows, halted_reason)
    write_report(report)

    # --- Expected log block (slide 39) ---
    banner("Expected log")
    print(f"raw_records={s['raw']}")
    print(f"cleaned_records={s['cleaned']}")
    print(f"embedded_records={embedded_n}")
    print(f"dropped_duplicates={s['dropped_duplicates'] + s['dropped_superseded']}")
    print(f"flagged_missing_date={s['flagged_missing_date']}")
    print(f"run_id={run_id}")
    print(f"\nArtifacts: data/cleaned/cleaned.json | data/quarantine/quarantine.csv | "
          f"reports/quality_report.md | reports/before_after_eval.csv")
    print(f"Pipeline status: {'HALTED (expectation fail)' if halted_reason else 'PUBLISHED'}  "
          f"| monitor worst={monitor.worst}")

    return 1 if halted_reason else 0


def main() -> int:
    p = argparse.ArgumentParser(description="CS/IT Helpdesk ETL + Quality + Observability pipeline")
    p.add_argument("--inject-corruption", action="store_true",
                   help="Sprint 3: tiêm lỗi (sync fail, bad date, OCR noise) để đo & HALT")
    args = p.parse_args()
    return run(inject_corruption=args.inject_corruption)


if __name__ == "__main__":
    raise SystemExit(main())
