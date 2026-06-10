# Data Contract — Corpus tri thức cho agent CS + IT Helpdesk

> "Transform = code + contract, không sửa tay ngay trước khi demo" (slide 21).
> File này là nguồn-sự-thật cho schema, cleaning rules và mức độ nghiêm trọng.

## 1. Canonical schema (đầu vào mọi nguồn map về)

| field | type | bắt buộc | mô tả |
|---|---|---|---|
| `doc_id` | string | ✅ | **natural key**. Cùng `doc_id` = cùng tài liệu logic (mọi version). |
| `source_type` | enum(`postgres`,`jira`,`file`) | ✅ | nguồn gốc record. |
| `source_uri` | string | ✅ | đường dẫn/khoá nguồn (lineage). |
| `title` | string | ✅ | tiêu đề tài liệu. |
| `effective_date` | date `YYYY-MM-DD` | ✅ (sau clean) | thời điểm tài liệu có hiệu lực. |
| `version` | string | ❌ | nhãn version logic (vd `v4`) cho vector filter. |
| `ocr_confidence` | float [0,1] | ✅ | độ tin OCR; < 0.60 → human review. |
| `content` | string | ✅ | nội dung đã chuẩn hoá (NFC, trim). |

- **Encoding**: UTF-8, NFC. Đã test với dòng tiếng Việt có dấu.
- **Natural key**: `doc_id`. Hai tài liệu khác nhau **không** được trùng `doc_id`.

## 2. Cleaning rules (slide 23) — `transform/cleaning_rules.py`

**Clean / normalize**
1. Trim whitespace ở `title` & `content` (gộp khoảng trắng thừa).
2. Parse date về `YYYY-MM-DD` từ các format `YYYY-MM-DD`, `DD/MM/YY`, `DD/MM/YYYY`, `YYYY/MM/DD`.
3. Unicode NFC; đánh dấu ký tự thay thế `�` (mojibake).

**Reject (cứng) → quarantine**
4. `content` rỗng sau trim → `reject: empty_content`.
5. Trùng `content_hash` (sha256 của `source_type|doc_id|content`) → `reject: duplicate_content_hash`.
6. Version supersede theo natural key `doc_id`: giữ bản `effective_date` **mới nhất**;
   bản cũ → `reject: superseded_by_<version>`.

**Flag / quarantine (không embed tới khi SME duyệt)**
7. `effective_date` thiếu → `flag: review_missing_date`.
8. `ocr_confidence < 0.60` hoặc có mojibake → `flag: review_low_ocr`.

> Mọi drop/flag được ghi `data/quarantine/quarantine.csv` kèm `run_id` (audit).

## 3. Expectation suite (slide 24) — `quality/expectations.py`

Chạy trên tập **cleaned (embed-eligible)** SAU bước clean. Tất cả là **hard gate**:

| dimension | expectation | column |
|---|---|---|
| Completeness | `expect_column_values_to_not_be_null` | `content` |
| Uniqueness | `expect_column_values_to_be_unique` | `doc_id` |
| Completeness | `expect_column_values_to_not_be_null` | `effective_date` |
| Validity (format) | `expect_column_values_to_match_regex` `^\d{4}-\d{2}-\d{2}$` | `effective_date` |
| Validity (lịch) | `expect_column_values_to_be_valid_date` (bắt `2026-13-45`) | `effective_date` |

```python
if expectations_fail:
    raise PipelineHalt("bad data before agent")   # pipeline dừng có kiểm soát
```

## 4. Mức độ nghiêm trọng (slide 27): Halt / Quarantine / Warn

| mức | trường hợp | hành vi |
|---|---|---|
| **HALT** | duplicate primary key sau dedupe, `effective_date` sai lịch, schema contract fail | dừng pipeline, **không** publish, exit 1 |
| **QUARANTINE** | thiếu `effective_date`, OCR thấp / mojibake | giữ ở `quarantine.csv`, không embed, pipeline tiếp tục |
| **WARN** | volume lệch ≥ 20%, freshness ≥ 50% SLA, metadata thiếu (optional) | cảnh báo, vẫn chạy |

> Policy này được ghi rõ ở đây để **agent không nhầm nguồn "review" thành nguồn đáng tin**.

## 5. SLA freshness (slide 8) — nói bằng ngôn ngữ nghiệp vụ

> "Policy refund phải reflect trong agent **≤ 4 giờ** sau khi PDF ký."

- Đo điểm cuối: thời điểm `last_success_run` cập nhật `cleaned` / `vector_store`.
- Ngưỡng: **warn ≥ 50% SLA (2h)**, **page ≥ 100% SLA (4h)**.
- Phân loại nguồn: static PDF vs ticket stream **không** dùng chung một SLA (cấu hình per-source).
- Hiển thị cho user: "Dữ liệu tri thức cập nhật tới: …" để giảm kỳ vọng sai.

## 6. Golden questions (regression nhỏ cho agent, slide 9)

| id | câu hỏi | nguồn đúng | đáp án đúng | bẫy (bản cũ) |
|---|---|---|---|---|
| q1 | Chính sách hoàn tiền trong bao nhiêu ngày? | `doc_id=12` (refund **v4**) | **7 ngày** | "14 ngày" (v3) |
| q2 | SLA phản hồi sự cố P1? | `doc_id=58` | **2 giờ** | — |
| q3 | Cấp quyền truy cập cần ai duyệt? | `doc_id=44` | **manager duyệt** | — |

## 7. Owner (RACI rút gọn, slide 7)

| nguồn | owner | trách nhiệm |
|---|---|---|
| PostgreSQL tickets | Data Eng | CDC/watermark, freshness + replication lag |
| Jira/CRM API | AI Eng | pagination, rate-limit 429, checkpoint |
| PDF/HTML SOP | AI Eng + SME | OCR confidence, version sign-off, "đúng" policy |
| Vector store / agent | AI Eng | eval before/after, grounding |

> Lab solo: một người đóng nhiều vai, nhưng vẫn ghi rõ owner trên từng nguồn.
