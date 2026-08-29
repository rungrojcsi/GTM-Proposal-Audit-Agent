# Unit tests — shared/ modules (ส่วน B, proposal-evaluator API)

ทดสอบ business logic ใน `shared/` ที่ยังไม่ถูกครอบคลุมโดย `../eval/run_eval.py`
(ตัวนั้นทดสอบเฉพาะ `rubric.py`/`scoring.py`/`evaluation.py` — rubric normalization + scoring)

ทุก external dependency (Azure SQL, Azure OpenAI, Document Intelligence) ถูก mock —
**รันได้โดยไม่ต้องมี DB จริง ไม่ต้องมี Azure credential จริง**

## รัน

```bash
cd proposal-evaluator/api/tests
python -m unittest discover -s . -p "test_*.py" -v
```

ต้องติดตั้ง (ครั้งเดียว ถ้ายังไม่มี): `pip install azure-functions azure-ai-formrecognizer python-pptx azure-storage-blob`
(อยู่ใน `api/requirements.txt` อยู่แล้วสำหรับ deploy จริง — แค่ไม่เคยติดตั้งบน dev env นี้)

## ครอบคลุม

| ไฟล์ | ทดสอบ |
|---|---|
| `test_guard.py` | authorization gate แบบ fail-closed: `parse_allowlist`/`ip_allowed`, `check_network` (kill switch, fail-open เมื่อ DB ล่ม), `gate()` (endpoint ไม่ประกาศสิทธิ์ → 403, PUBLIC/AUTH_ONLY/page-gated), `thread_access` (ownership + view_all), `audit_declarations` (ตรวจ endpoint ลืมประกาศตอน startup) |
| `test_auth.py` | `client_ip` (X-Forwarded-For ตัวขวาสุด, ตัด port, IPv6), `parse_principal` (base64 SWA header), `current_user` (dev-mode vs guest vs DB role), RBAC helpers |
| `test_llm.py` | `json_text` (ตัด code fence/YAML frontmatter/prose รอบ JSON), `chat()` param auto-negotiation (max_tokens↔max_completion_tokens, ตัด temperature, retry exhaustion), provider selection (`get_provider`/`current_model`/`client_and_model`/`azure_client_and_model`/`list_models`) |
| `test_audit.py` | `_dump` serialization, `write()` ต้องไม่ raise แม้ DB ล้มเหลว (E4) |
| `test_extraction.py` | `extract_pdf` (Document Intelligence mock), `extract_pptx` (ใช้ python-pptx จริงสร้างไฟล์ทดสอบ), `extract_text` dispatch logic |
| `test_presentation.py` | `coach_guideline()` retry/backoff logic (rate-limit vs generic), text truncation 24000 ตัวอักษร |
| `test_project_content.py` | `extract_project_content()` — fire-safe: ต้องคืน `None` ไม่ raise เมื่อ LLM ล้มเหลวทุกครั้ง |
| `test_db.py` | ทุกฟังก์ชันใน `db.py` (~57 ฟังก์ชัน) ผ่าน fake pyodbc connection/cursor (`_dbfakes.py`) — SQL branch ถูกต้องตาม argument, param เรียงถูกตำแหน่ง, commit ตอนที่ควรเขียนจริง, error path เดิม (fail-closed) ยังทำงาน, รวม `get_dashboard()` ที่เป็น pure aggregation logic ตรวจ KPI/pipeline/trend/needs_attention ครบ |
| `test_function_app.py` | **golden test**: ทุก endpoint ที่ registered จริงใน `function_app.app` ต้องมีอยู่ใน `guard.ROUTE_PERMS`/`NON_HTTP_FUNCTIONS` (จับ endpoint ที่ลืมประกาศสิทธิ์อัตโนมัติ) + validation/audit-wiring ของ endpoint สำคัญ (prepare/evaluate/evaluate_worker/comments/thread_update/thread_delete/users_*/roles_*/settings_put/library_update/library_backfill/audit_list/db_migrate) + helper ล้วน (`_content_snapshot`/`_validate_network_settings`) |

## ขอบเขตที่ไม่ครอบคลุม

- `models.py` — pydantic schema ประกาศ (declarative, ไม่มี logic ให้ทดสอบ)
- integration จริงกับ Azure OpenAI/Document Intelligence/Azure SQL/Blob Storage — เฉพาะ mock ทั้งหมด
- endpoint ที่เป็น thin GET wrapper ซ้ำรูปแบบเดิม (เช่น `masterdata_list`/`roles_list`/`llm_models`/`library_list`) ไม่ได้ test แยกทีละตัว — ครอบคลุมทางอ้อมผ่าน route-consistency golden test
