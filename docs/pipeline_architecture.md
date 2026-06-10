# Pipeline Architecture — Trợ lý nội bộ CS + IT Helpdesk

> Day 10 — Data Pipeline & Data Observability. Mục tiêu: phát hiện vấn đề data
> **trước khi user thấy agent trả lời sai** ("detect before users complain").

## 1. Bức tranh tổng thể (Sources → Pipeline → Storage → Serving → Agent)

```
   Sources                 Pipeline                       Storage / Serving        Agent
 ┌────────────┐      ┌──────────────────────────┐      ┌──────────────────┐
 │ PostgreSQL │─CDC─▶│ ingest → clean → MONITOR │─────▶│ raw + cleaned    │
 │ (tickets)  │      │   → VALIDATE → embed     │      │ lake (json)      │
 ├────────────┤      │                          │      ├──────────────────┤      ┌─────────┐
 │ Jira API   │─poll▶│  run_id gắn mọi artifact │─────▶│ vector_store     │─RAG─▶│  Agent  │
 │ (issues)   │      │  expectations = hard gate│      │ (KB: SOP/policy) │      │ answer  │
 ├────────────┤      │  freshness/volume monitor│      ├──────────────────┤      └─────────┘
 │ PDF/HTML   │parse▶│  fail → PipelineHalt     │─────▶│ quarantine.csv   │
 │ SOP        │ OCR  └──────────────────────────┘      └──────────────────┘
 └────────────┘
```

- **Agent KB** (vector store dùng để trả lời) = chỉ tài liệu **SOP/policy** (`source_type=file`).
- **Ticket (PostgreSQL) + issue (Jira)** = data vận hành: vẫn đi qua clean + monitor
  (đóng góp volume/freshness), nhưng **không** nằm trong KB trả lời để tránh "nhiễu" retrieval.

## 2. Run order (slide 39)

```
ingest → clean → monitor → validate → embed → publish
```

| Stage | Module | Việc làm | Output |
|---|---|---|---|
| 1. ingest | `ingest/sources.py` | đọc 3 nguồn → canonical schema, ghi raw snapshot | `data/raw/raw_<run_id>.json` |
| 2. clean | `transform/cleaning_rules.py` | trim, parse date, unicode, dedupe/version, flag/reject | `data/cleaned/cleaned.json`, `data/quarantine/quarantine.csv` |
| 3. monitor | `monitoring/freshness_check.py` | 5 pillars: freshness, volume, distribution, schema, lineage | log + report |
| 4. validate | `quality/expectations.py` | expectation suite (hard gate) → **PipelineHalt** nếu fail | PASS/FAIL |
| 5. embed | `agent/rag.py` | embed KB docs → vector store | `data/embedded/vector_store.json` |
| 6. publish | `etl_pipeline.py` | cập nhật baseline + state, chạy before/after eval | `reports/*` |

> **Quan trọng**: monitor chạy **trước** validate để vẫn quan sát được kể cả khi
> pipeline sắp HALT (bắt "chạy nhưng sai", không chỉ "chạy thất bại").

## 3. Lineage (trace ngược khi có sự cố)

```
sources[file + jira + postgres] → queue → ingest_worker → raw(N)
raw → clean → cleaned(M) → validate(expectations)
cleaned → embed → vector_store(K)   [run_id=...]
```

Mỗi artifact gắn `run_id` (mặc định `2026-02-10T14:35`, override bằng env `LAB_NOW`).
Khi agent trả lời sai → đi ngược lineage: answer ← chunk ← vector_store ← cleaned ←
raw ← source, để xác định **step nào fail** (ingest? clean? embed?) thay vì đổ lỗi cho model.

## 4. Orchestration, retry & idempotency (slide 33, 35)

- **Schedule**: cron / event / backfill. Lab dùng 1 lệnh `python etl_pipeline.py`.
- **Retry**: backoff + DLQ + alert (mô phỏng ở ingest notes: `ingest_02:00 retry exhausted`).
- **Idempotency**: rerun 2 lần **không** tạo duplicate vector store, nhờ:
  - natural key `doc_id` + version supersede (giữ `effective_date` mới nhất),
  - vector store ghi đè theo `run_id` ("replace collection" thay vì append mù),
  - dedupe theo `content_hash`.

## 5. Storage layout

```
data/raw/        snapshot thô mỗi lần ingest (lineage)
data/cleaned/    cleaned.json (embed-eligible records)
data/embedded/   vector_store.json (KB cho agent)
data/quarantine/ quarantine.csv (mọi row drop/flag + lý do + run_id)
monitoring/      baseline.json (volume baseline), state.json (last_success_run)
reports/         quality_report.md, before_after_eval.csv (bằng chứng nộp bài)
```

## 6. Mở rộng lên production (không làm trong lab)

- Thay CSV/JSON mẫu bằng connector thật: PostgreSQL CDC (WAL slot), Jira REST + cursor
  pagination + token-bucket rate limit, PDF OCR + confidence score.
- Thay bag-of-words embedding bằng model embedding thật + vector DB (pgvector/Qdrant).
- Thay expectation suite stdlib bằng Great Expectations (API tương đương, xem `requirements.txt`).
- Orchestrator: Airflow/Prefect/Dagster với sensor partition + lineage tag `run_id`.
