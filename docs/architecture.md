# Architecture — Proposal Evaluator

สรุปจาก SA workflow (sa-skill Phase 1-4). เอกสารนี้เป็น source of truth ของ scope.

## Decisions (confirmed)

| หัวข้อ | มติ |
|--------|-----|
| Cloud | Azure ทั้งหมด |
| LLM | **Azure OpenAI (GPT-4o)** — ไม่ใช้ Claude/Anthropic |
| Backend | Azure Functions (Python, Consumption/serverless) |
| Database | Azure SQL (Basic tier) |
| Frontend | React + Vite + TypeScript → Azure Static Web Apps |
| Auth | Entra ID SSO (submitter + analyst; ไม่มี approval role) |
| Input | PDF เท่านั้น, ภาษาอังกฤษหลัก |
| Original file | เก็บถาวรใน Blob + versioning |
| Volume | 20-50 proposal/เดือน |
| Pass gate | ไม่มี hard gate — submitter ตัดสินใจเอง |

## Evaluation pipeline (F03 → F13)

```
upload (PDF)
  → validate format/size            (F03)
  → store original in Blob          (F04)
  → create submission + version     (F05)
  → extract text (Doc Intelligence, +OCR)   (F06/F07)
  → build proposal-master prompt    (F08)
  → call Azure OpenAI (JSON mode)   (F09)
  → parse + validate (Pydantic)     (F10)
  → compute weighted score in code  (F11)   ← deterministic, ไม่ให้ GPT คำนวณ
  → map verdict                     (F12)
  → persist (SQL) + render report   (F13)
  → Accept (F15) / Resubmit (F16) / Compare (F17)
```

## Key risk & mitigation

| Risk | Mitigation |
|------|-----------|
| GPT ประเมินไม่ตรง proposal-master (skill เขียนสำหรับ Claude) | prompt + JSON schema เข้ม, eval set, temp 0.2 |
| คะแนนแกว่ง (LLM non-determinism) | weighted score คำนวณใน `scoring.py`, temp ต่ำ |
| PDF layout ซับซ้อน parse เพี้ยน | Azure AI Document Intelligence + OCR fallback |
| proposal confidential | Blob private + encryption, RBAC, PDPA retention |

## Open [TBD]

- owner_id mapping จาก Entra ID claim (ยัง placeholder ใน `function_app.py`)
- retention policy (เก็บกี่เดือน)
- OCR ต้องรองรับ scanned PDF ระดับไหน
- proposal-master system prompt เต็ม (option 2)
