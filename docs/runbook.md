# Runbook — Sự cố data của agent CS + IT Helpdesk

> "Biến sự cố thành tài sản cho lần sau" (slide 37). Template: Symptom → Detection →
> Diagnosis → Mitigation → Prevention.

## 0. Triage có timebox (slide 34) — áp dụng khi user đang chờ (P1/policy)

| thời gian | việc | dashboard/metric |
|---|---|---|
| 0–5 phút | Freshness + `last_success_run` có trễ SLA không? | `freshness[*]` |
| 5–12 phút | Volume + error rate: step nào "im lặng" hoặc spike? | `volume[*]`, `null_rate` |
| 12–20 phút | Schema/contract + lineage tới bảng/file nguồn | `schema_contract`, lineage |

> Nếu chưa ra root cause → chuyển sang **giảm thiểu**: rollback publish hoặc bật banner
> "data đang cập nhật". Luôn **ghi incident note** kèm metric đã xem.

## 1. Thứ tự debug dashboard (slide 30, 31) — debug DATA trước khi debug MODEL

```
Freshness → Volume → Schema/Distribution → Lineage → Root cause
```

1. **Detect**  — freshness có trễ không?
2. **Isolate** — volume có rơi/spike không?
3. **Validate**— schema drift hay parse error?
4. **Trace lineage** — nguồn nào / step nào fail?
5. **Fix + rerun** — idempotent rerun + verify câu trả lời agent.

---

## 2. Incident đã xử lý — "Refund stale: agent trả lời 14 ngày"

> Tái hiện được bằng: `python etl_pipeline.py --inject-corruption`

**Symptom**
- User CS phản ánh: agent trả lời "Refund 14 ngày", policy thực tế là **7 ngày**.
- Triệu chứng: trả lời đúng *fact-cũ* nhưng sai version (freshness/publish/cache vector).

**Detection**
- `freshness[postgres] = 17.0h` → **🔴 PAGE** (SLA 4h). Job `ingest_02:00 retry exhausted`.
- `volume[postgres] = 13 rows (−28%)` → **🟡 WARN** so với baseline 18 (partial sync).
- Expectation suite: `valid_date(effective_date)` **FAIL** (1 row `2026-13-45`) → `PipelineHalt`.

**Diagnosis (theo lineage)**
- `refund-v4.pdf → ingest job → clean → chunk → vector policy_v4`.
- Điểm tử = **ingest** (sync 02:00 fail), **không phải model**. Bản v4 chưa vào store →
  retriever rơi về bản v3 cũ ("14 ngày").

**Mitigation**
- Pipeline **HALT có kiểm soát** trước bước embed → không publish data xấu (đúng thiết kế).
- Tạm thời: rollback publish về `run_id` tốt gần nhất hoặc bật banner "data đang cập nhật".

**Prevention**
- Expectation `valid_date` (đã thêm) + alert `freshness ≥ 100% SLA` (page).
- Dedupe + version supersede theo `doc_id` (giữ `effective_date` mới nhất) →
  loại bản cũ trước khi embed.
- Idempotent rerun: `python etl_pipeline.py` → verify `freshness < 4h` **và** agent trả lời
  "7 ngày" khớp policy v4 (xem `reports/before_after_eval.csv`, q1: BEFORE ❌ → AFTER ✅).

---

## 3. Idempotency — rerun an toàn (slide 35)

- Natural key `doc_id` + version supersede (không random UUID mỗi lần).
- Vector store ghi đè theo `run_id` (replace, không append mù) → rerun 2 lần **không**
  tạo duplicate chunk.
- Dedupe theo `content_hash` cho exact duplicate.

## 4. Peer-review checklist (slide 42)

- [ ] "Rerun 2 lần có duplicate vector không?" → không (idempotent).
- [ ] "Freshness đo ở bước nào — ingest hay publish?" → đo ở `last_success_run` (publish).
- [ ] "Record bị flag đi đâu — quarantine hay vẫn embed?" → quarantine, không embed.

## 5. Definition of Done (slide 41)

- [x] `run_id` gắn mọi artifact (raw/cleaned/embed/report).
- [x] Log số record raw → cleaned → embedded (drop/flag có giải thích).
- [x] Expectation suite chạy; fail → pipeline dừng có kiểm soát (`PipelineHalt`, exit 1).
- [x] ≥ 1 bằng chứng before/after ảnh hưởng câu trả lời agent (`before_after_eval.csv`).
- [x] "Chạy được trên máy giảng viên" = script + README + lệnh chạy 1 dòng, stdlib-only.
