# Báo cáo cá nhân — Day 10 (Data Pipeline & Observability)

- **Họ tên**: Vũ Đăng Khiêm
- **Use case**: Trợ lý nội bộ CS + IT Helpdesk
- **run_id**: `2026-02-10T14:35`
- **Lệnh chạy**: `python etl_pipeline.py` (và `--inject-corruption` cho kịch bản incident)

> Theo khung 4 ý của slide 40.

## 1. Phần tôi phụ trách

Làm **solo** nên đảm nhận toàn bộ các vai (ghi rõ owner trên từng nguồn ở `data_contract.md`):

- **AI/Applied**: data contract cho corpus, golden questions, eval before/after.
- **Data Eng**: ingest 3 nguồn (PostgreSQL ticket / Jira API / PDF SOP) về canonical schema,
  cleaning rules, pipeline SLA.
- **SRE/Platform**: freshness/volume monitor, alert (warn/page), runbook + idempotency.
- **Product/SME**: định nghĩa "đúng" cho policy refund (7 ngày, version v4) và sign-off.

Artifact đầu ra: `etl_pipeline.py`, `transform/cleaning_rules.py`, `quality/expectations.py`,
`monitoring/freshness_check.py`, 3 file `docs/`, và bằng chứng trong `reports/`.

## 2. Một lỗi / quyết định kỹ thuật chính

**Quyết định: expectation `valid_date` phải kiểm tra ngày *lịch hợp lệ*, không chỉ regex format.**

Ban đầu validity dùng regex `^\d{4}-\d{2}-\d{2}$`. Khi tiêm corruption row
`effective_date = 2026-13-45`, regex **vẫn pass** (đúng format `\d{4}-\d{2}-\d{2}`) →
pipeline không HALT và data xấu lọt tới agent. Tôi bổ sung
`expect_column_values_to_be_valid_date` (dùng `datetime.strptime("%Y-%m-%d")`) để bắt tháng 13 /
ngày 45 → `PipelineHalt`. Đây đúng tinh thần slide 27: "schema/format hợp lệ ≠ giá trị hợp lệ".

**Quyết định kiến trúc**: Agent KB chỉ embed tài liệu SOP/policy (`source_type=file`);
ticket/jira là data vận hành (chỉ monitor volume/freshness, không đưa vào vector store trả lời)
→ tránh ticket "lấn" retrieval và làm agent trích sai nguồn.

## 3. Bằng chứng trước / sau

**Before/after answer quality** (`reports/before_after_eval.csv`):

| câu hỏi | BEFORE (raw, chưa clean) | AFTER (cleaned) | kết quả |
|---|---|---|---|
| Refund bao nhiêu ngày? | "Refund **14 ngày**" (bản v3 cũ) ❌ | "Refund **7 ngày**" (v4) ✅ | **đã fix** |
| SLA P1? | "2 giờ" ✅ | "2 giờ" (doc 58) ✅ | ổn định |
| Cấp quyền ai duyệt? | "manager duyệt" ✅ | "manager duyệt" (doc 44 v2) ✅ | ổn định |

Nguyên nhân fix q1: dedupe + **version supersede theo `doc_id`** giữ bản `effective_date`
mới nhất (v4) → loại bản v3 trước khi embed.

**Quality / observability** (`reports/quality_report.md` + log):

| metric | normal | `--inject-corruption` |
|---|---|---|
| freshness[postgres] | 🟢 0.0h | 🔴 **PAGE 17.0h** (sync 02:00 fail) |
| volume[postgres] | 🟢 18 rows | 🟡 **−28%** (13 rows) |
| expectation `valid_date` | ✅ PASS | ❌ **FAIL → PipelineHalt** |
| pipeline status | PUBLISHED (exit 0) | **HALTED** (exit 1, không publish) |

Record funnel (normal): `raw=35 → cleaned=29 → embedded(KB)=7`;
`dropped_duplicates=3`, `flagged_missing_date=2` (đều ghi `quarantine.csv` kèm lý do).

## 4. Một cải tiến tiếp theo

Thêm **SLI cho agent** (slide 29) vào monitor: *citation freshness p95* (tuổi trung bình
của chunk được trích) và *retrieval hit@k* trên golden set — để bắt được trường hợp
"ingest chạy nhưng retrieval lệch" mà 5 pillars chưa đủ phản ánh. Kế tiếp là thay
bag-of-words embedding bằng model embedding thật + vector DB để hit@k phản ánh đúng production.
