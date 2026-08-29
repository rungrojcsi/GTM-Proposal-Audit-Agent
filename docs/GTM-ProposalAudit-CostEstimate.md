# Proposal Evaluator — ประเมินต้นทุน Azure: Azure LLM vs Local LLM

*จัดทำ 2026-08-04 | ขอบเขต: ปริมาณการใช้งาน 30 proposals/เดือน | อ้างอิงจากโค้ดจริง (function_app.py, evaluation.py, extraction.py) + ราคา retail Azure ณ วันที่จัดทำ*

## 1. Executive Summary

- ต้นทุนรวมทั้ง 2 scenario **ใกล้เคียงกันมาก** ต่างกันไม่ถึง 30 บาท/เดือน
- **Scenario A (Azure LLM, gpt-5.4-mini): ~$15.4/เดือน (~515 บาท)**
- **Scenario B (Local LLM): ~$14.5-15/เดือน (~490-500 บาท)**
- สาเหตุ: fixed infrastructure (SQL + Static Web Apps) กิน **>90%** ของบิลทั้งคู่ ที่ปริมาณ 30 proposals/เดือน ค่าโมเดลภาษา (LLM) เล็กเกินกว่าจะสร้างความต่างมีนัยสำคัญ
- **เหตุผลที่ควรสลับไป Local LLM คือ privacy/data residency ไม่ใช่การประหยัดต้นทุน** ที่ปริมาณงานนี้

## 2. ขอบเขตและสมมติฐาน

- ปริมาณ: 30 proposals ใหม่/เดือน (v1, ไม่นับ resubmission/version แก้ไข)
- ขนาดไฟล์เฉลี่ย: proposal ~15-20 หน้า, ผสม PDF/PPTX
- อ้างอิง pipeline จริงจากโค้ด — ไม่ใช่การประมาณลอยๆ

## 3. ต้นทุนคงที่ (Fixed Infrastructure) — เหมือนกันทั้ง 2 Scenario

| รายการ | Tier ที่ deploy จริง | ค่าใช้จ่าย/เดือน (USD) | ประมาณ THB |
|---|---|---|---|
| Azure SQL Database | Basic (5 DTU) | ~$4.90-5.00 | ~165-170 |
| Azure Static Web Apps | Standard | $9.00 | ~300 |
| Azure Functions | Consumption (Y1) | $0 (อยู่ในเควตาฟรี 1M executions + 400K GB-s/เดือน) | 0 |
| Blob + Queue Storage | LRS | <$0.10 | <3 |
| **รวมคงที่** | | **~$14/เดือน** | **~470 บาท** |

Confidence: **สูง** — ราคา retail จาก Azure ตรงกับ SKU ที่ deploy อยู่จริง

## 4. ต้นทุนผันแปร — Document Intelligence (OCR)

- เฉพาะไฟล์ **PDF** เท่านั้นที่ยิงไป Azure AI Document Intelligence (`prebuilt-read`)
- PPTX ใช้ python-pptx (ฟรี, ไม่มีค่าใช้จ่าย)
- ราคา: $1.50 ต่อ 1,000 หน้า
- ประมาณ 300-600 หน้า/เดือน (30 proposals, ผสม PDF/PPTX) → **$0.45-0.90/เดือน (~15-30 บาท)**
- **สำคัญ: รายการนี้เหมือนกันทั้ง 2 scenario** เพราะ OCR ยังเป็น Azure เสมอ ไม่มี code path ไป local (แม้ runner มี typhoon-ocr-3b พร้อมใช้ ยังไม่ implement)

## 5. Scenario A — Azure LLM (gpt-5.4-mini)

Pipeline ต่อ proposal ใหม่ 1 ตัว เรียก LLM **3 ครั้ง** (ตรวจจากโค้ดจริง):

1. `detect_metadata` — ดึงชื่อลูกค้า/โปรเจค (input สั้น ≤6,000 ตัวอักษร)
2. `evaluate_proposal` — การประเมินหลัก (system prompt 10,070 ตัวอักษร + เนื้อ proposal เต็ม)
3. `extract_project_content` — ดึงข้อมูล price/cost/schedule (input ≤24,000 ตัวอักษร)

ประมาณ token ต่อ proposal (ขนาดกลาง ~20,000 ตัวอักษร): input รวม ~14,500 tokens / output รวม ~3,000 tokens

⚠️ **ราคา gpt-5.4-mini บน Azure GlobalStandard ไม่มีแหล่งทางการยืนยันชัดเจน** (โมเดลใหม่) พบตัวเลขไม่ตรงกันระหว่างแหล่งข้อมูล — ใช้ตัวเลขฝั่งสูงเพื่อความปลอดภัยของประมาณการ (**Confidence: กลาง**)

- ค่า LLM ≈ $0.024/proposal → **30 proposals ≈ $0.6-0.9/เดือน (~20-30 บาท)**

**รวม Scenario A: ~$14 (infra) + ~$0.7 (DocIntel) + ~$0.7 (LLM) ≈ $15.4/เดือน (~515 บาท)**

## 6. Scenario B — Local LLM

🔴 **ข้อเท็จจริงสำคัญจากการอ่านโค้ดจริง — "Local LLM = ไม่มีค่า LLM เลย" ไม่ถูกต้อง 100%:**

1. `detect_metadata` **hardcode ให้ใช้ Azure เสมอ** (`force_azure=True`) ไม่ว่าจะเลือก provider เป็น local หรือไม่ (เหตุผล: local ช้าเกินไปสำหรับ sync call ที่ต้องตอบเร็ว)
2. Document Intelligence (OCR) **ยังเป็น Azure เสมอ** เช่นกัน (ดูข้อ 4)
3. สิ่งที่ประหยัดได้จริงมีแค่ 2 ใน 3 LLM call ต่อ proposal (`evaluate_proposal` + `extract_project_content`)

| รายการ | ค่าใช้จ่าย/เดือน |
|---|---|
| Infra คงที่ | ~$14 (เหมือน Scenario A) |
| Document Intelligence | ~$0.5-0.9 (เหมือน Scenario A) |
| detect_metadata (forced Azure) | ~$0.04 (เล็กน้อยมาก) |
| evaluate_proposal + extract_project_content | $0 (รันบน runner CSI, ไม่ขึ้นบิล Azure) |
| **รวม** | **~$14.5-15/เดือน (~490-500 บาท)** |

**ส่วนต่าง A vs B ≈ $0.6-0.9/เดือน (~20-30 บาท) เท่านั้น**

## 7. สิ่งที่ไม่รวมในตัวเลข (สำคัญต่อการตัดสินใจ)

- **GPU/runner ที่ CSI network ไม่ได้ฟรีจริง** — แค่ไม่ขึ้นบิล Azure subscription นี้เท่านั้น เป็นต้นทุน infra อื่นที่ CSI แบกอยู่แล้ว (hardware/electricity) — ถ้านับรวม ผลอาจพลิกกลับด้าน (Local แพงกว่า)
- **ข้อจำกัดด้าน performance ของ Local (กระทบความเป็นไปได้ ไม่ใช่ต้นทุน):** จากผลทดสอบจริง — เฉพาะโมเดล `gpt-oss:20b` (~3.4 นาที/audit ผ่าน async queue) และ `gemma4:latest` (~90 วินาที) ใช้งานได้จริงที่ปริมาณนี้ **`gemma4:31b` ใช้ไม่ได้เลย** (~40-70 นาที ชน Function timeout 10 นาทีทุกครั้ง)

## 8. บทสรุป

ที่ปริมาณ 30 proposals/เดือน ต้นทุน Azure ทั้ง 2 scenario ต่างกันไม่ถึง 30 บาท/เดือน เพราะ fixed infrastructure (SQL + SWA) ครองสัดส่วนหลักของบิล การสลับไป Local LLM **ควรตัดสินใจด้วยเหตุผลด้าน privacy/data residency** (ข้อมูล proposal ไม่ออกนอกองค์กร) — ไม่ใช่เพื่อประหยัดต้นทุน ต้นทุนจะเริ่มต่างชัดเจนก็ต่อเมื่อปริมาณงานโตขึ้นมาก (หลักร้อย-พันproposals/เดือน) เพราะค่า Azure OpenAI โตเชิงเส้นตามปริมาณ ขณะที่ Local คงที่
