# Day 10 — ETL + Data Quality + Observability (CS + IT Helpdesk)

Pipeline `ingest → clean → monitor → validate → embed → publish` cho corpus tri thức
của trợ lý nội bộ CS + IT Helpdesk, kèm **expectation suite**, **freshness/observability
monitor** và **before/after eval** đo ảnh hưởng của data lên câu trả lời agent.

> Mục tiêu Day 10: phát hiện vấn đề data **trước khi user thấy agent trả lời sai**.
> "Garbage in → garbage out là bài toán hệ thống; debug pipeline trước khi debug model."

## ▶️ Chạy (1 lệnh, không cần `pip install`)

```bash
python etl_pipeline.py                      # happy path  -> PUBLISHED (exit 0)
python etl_pipeline.py --inject-corruption  # Sprint 3    -> incident + HALT (exit 1)
```

Yêu cầu: **Python ≥ 3.9** (chỉ dùng standard library). Không cần kết nối DB/API/Internet —
mọi nguồn đọc từ `data/sample/`.

## 📂 Folder tree (theo slide 39)

```
helpdesk-pipeline/
├── etl_pipeline.py              # orchestrator: ingest→clean→monitor→validate→embed→publish
├── config.py                   # run_id, ngưỡng SLA, golden questions
├── ingest/  sources.py         # đọc PostgreSQL + Jira API + PDF/HTML SOP → canonical schema
├── transform/ cleaning_rules.py# trim, parse date, unicode, dedupe/version, flag/reject
├── quality/ expectations.py    # expectation suite (mô phỏng Great Expectations) + PipelineHalt
├── monitoring/ freshness_check.py  # 5 pillars: freshness, volume, distribution, schema, lineage
├── agent/   rag.py             # embed + retrieve + answer (đo ảnh hưởng data lên agent)
├── eval/    before_after.py    # so sánh câu trả lời BEFORE (raw) vs AFTER (cleaned)
├── data/sample/                # postgres_tickets.csv, jira_tickets.json, sop_documents.csv
├── docs/                       # pipeline_architecture.md, data_contract.md, runbook.md
├── reports/                    # quality_report.md, before_after_eval.csv  (bằng chứng)
├── requirements.txt  .env.example  .gitignore
└── INDIVIDUAL_REPORT.md        # báo cáo cá nhân
```

## 🔢 Expected log (normal mode)

```
raw_records=35
cleaned_records=29
embedded_records=7          # KB docs (source_type=file); ticket/jira chỉ monitor, không embed
dropped_duplicates=3        # exact dup + superseded version
flagged_missing_date=2
run_id=2026-02-10T14:35
Pipeline status: PUBLISHED  | monitor worst=PASS
```

## 🧪 Bằng chứng (Evidence — slide 40)

| file | nội dung |
|---|---|
| `reports/before_after_eval.csv` | q1: BEFORE "14 ngày" ❌ → AFTER "7 ngày" ✅ (version supersede) |
| `reports/quality_report.md` | funnel record + expectation results + observability snapshot |
| `data/quarantine/quarantine.csv` | mọi row drop/flag + lý do + run_id |
| log `--inject-corruption` | freshness 🔴 PAGE 17h, volume −28%, `valid_date` FAIL → HALT |

## 🎬 Kịch bản demo 3 phút (slide 44)

1. **0:00–0:45** Use case + 3 nguồn (PostgreSQL ticket / Jira API / PDF SOP).
2. **0:45–1:30** `--inject-corruption` → chỉ vào `freshness 17h` + `volume −28%` trên log.
3. **1:30–2:30** Rerun `python etl_pipeline.py` (idempotent) → expectation PASS, publish.
4. **2:30–3:00** So sánh câu agent trước/sau (`before_after_eval.csv`) + `run_id` khớp.

## ✅ Mapping tới Deliverables Day 10 (slide 38)

| Deliverable | Tỉ trọng | Ở đâu |
|---|---|---|
| ETL pipeline | 45% | `etl_pipeline.py` + `ingest/` `transform/` `quality/` `monitoring/` `agent/` |
| Documentation | 25% | `docs/pipeline_architecture.md` · `data_contract.md` · `runbook.md` |
| Quality evidence | 20% | `reports/quality_report.md` · `before_after_eval.csv` · `quarantine.csv` |
| Individual report | 10% | `INDIVIDUAL_REPORT.md` |

## 🔁 Reproduce

```bash
# reset state nếu muốn baseline sạch
rm -f monitoring/state.json monitoring/baseline.json   # PowerShell: Remove-Item monitoring\state.json,monitoring\baseline.json
python etl_pipeline.py                # tạo baseline + evidence (PUBLISHED)
python etl_pipeline.py --inject-corruption   # incident (so sánh với baseline) -> HALT
```

> `run_id` cố định `2026-02-10T14:35` để reproduce; đổi bằng env `LAB_NOW` (ISO 8601).
