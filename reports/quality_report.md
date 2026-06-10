# Quality Report -- CS/IT Helpdesk Pipeline

- **run_id**: `2026-02-10T14:35`
- **mode**: `normal`
- **generated_at (lab_now)**: `2026-02-10T14:35:00+00:00`
- **status**: ✅ PUBLISHED

## 1. Record funnel (raw → cleaned → embedded)

| metric | value |
|---|---|
| raw_records | 35 |
| cleaned_records | 29 |
| embedded_records | 7 |
| dropped_empty | 1 |
| dropped_duplicates | 2 |
| dropped_superseded | 1 |
| flagged_missing_date | 2 |
| flagged_low_ocr | 0 |
| invalid_date (contract breach) | 0 |

## 2. Expectation suite (data quality as code)

| expectation | column | result | unexpected |
|---|---|---|---|
| not_null | `content` | ✅ PASS | 0 |
| unique | `doc_id` | ✅ PASS | 0 |
| not_null | `effective_date` | ✅ PASS | 0 |
| match_regex | `effective_date` | ✅ PASS | 0 |
| valid_date | `effective_date` | ✅ PASS | 0 |

## 3. Observability snapshot (5 pillars)

| pillar | check | status | value | detail |
|---|---|---|---|---|
| freshness | `freshness[file]` | 🟢 PASS | 0.0h | SLA=4h (warn>2h, page>4h) |
| freshness | `freshness[jira]` | 🟢 PASS | 0.0h | SLA=4h (warn>2h, page>4h) |
| freshness | `freshness[postgres]` | 🟢 PASS | 0.0h | SLA=4h (warn>2h, page>4h) |
| volume | `volume[file]` | 🟢 PASS | 11 rows (+0%) | baseline=11 |
| volume | `volume[jira]` | 🟢 PASS | 6 rows (+0%) | baseline=6 |
| volume | `volume[postgres]` | 🟢 PASS | 18 rows (+0%) | baseline=18 |
| distribution | `null_rate[effective_date]` | 🟢 PASS | 0% | 0/29 rows null |
| distribution | `content_length` | 🟢 PASS | min=23 median=48 max=90 |  |
| distribution | `cardinality[doc_id]` | 🟢 PASS | 29 unique |  |
| schema | `schema_contract` | 🟢 PASS | stable |  |

**Lineage**

- sources[file(11) + jira(6) + postgres(18)] -> queue -> ingest_worker -> raw(35)
- raw -> clean -> cleaned(29) -> validate(expectations)
- cleaned -> embed -> vector_store(7)  [run_id=2026-02-10T14:35]

## 4. Before / after -- ảnh hưởng lên câu trả lời agent

| câu hỏi | BEFORE (raw) | đúng? | AFTER (cleaned) | version | đúng? |
|---|---|---|---|---|---|
| Chính sách hoàn tiền (refund) cho khách trong bao nhiêu ngày? | Chính sách hoàn tiền: Khách được hoàn tiền trong vòng 14 ngày kể từ ngày mua. | ❌ | Chính sách hoàn tiền: Khách được hoàn tiền trong vòng 7 ngày kể từ ngày mua. | v4 | ✅ |
| SLA thời gian phản hồi cho sự cố P1 là bao lâu? | Sự cố P1: thời gian phản hồi theo SLA là 2 giờ, kèm leo thang lên quản lý trực. | ✅ | Sự cố P1: thời gian phản hồi theo SLA là 2 giờ, kèm leo thang lên quản lý trực. | v1 | ✅ |
| Quy trình cấp quyền truy cập cần ai phê duyệt? | Quy trình cấp quyền: mọi yêu cầu truy cập phải được manager phê duyệt trước khi cấp quyền. | ✅ | Quy trình cấp quyền: mọi yêu cầu truy cập phải được manager phê duyệt trước khi cấp quyền. | v2 | ✅ |
